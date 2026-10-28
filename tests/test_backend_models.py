"""API-05: model upload validation (size, extension, magic bytes, structure), SHA-256 on receipt, storage
outside the static root, framework detection and safe layer listing."""
import hashlib
import io
import json
import pickle
import zipfile
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("onnx")

from backend.testing import add_user, app_client, bearer, onnx_model_bytes  # noqa: E402

LIMIT = 200_000


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("models")
    with app_client(tmp, max_upload_bytes=LIMIT) as (app, client):
        add_user(app, "olivia", "owner")
        add_user(app, "victor", "verifier")
        yield app, client, {"olivia": bearer(client, "olivia"), "victor": bearer(client, "victor")}


def up(client, headers, data: bytes, filename: str, **form):
    return client.post("/api/v2/models", headers=headers, files={"file": (filename, io.BytesIO(data))}, data=form)


def zip_bytes(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in entries.items():
            z.writestr(k, v)
    return buf.getvalue()


ONNX = onnx_model_bytes(np.linspace(-0.01, 0.01, 288))


def test_valid_onnx_upload(env):
    app, client, H = env
    r = up(client, H["olivia"], ONNX, "../../My Model!.onnx", name="mnist", description="test")
    assert r.status_code == 201, r.text
    m = r.json()
    art = m["artifacts"][0]
    assert m["purpose"] == "watermarked" and m["name"] == "mnist"
    assert art["sha256"] == hashlib.sha256(ONNX).hexdigest() and art["size_bytes"] == len(ONNX)
    assert art["framework"] == "onnx" and art["filename"] == "My_Model_.onnx"          # sanitised, no path
    s = app.state.settings
    stored = Path(s.uploads) / art["sha256"][:2] / f"{art['sha256']}.onnx"
    assert stored.read_bytes() == ONNX
    for root in (Path(s.ui_dir).resolve(), Path(s.results_dir).resolve()):
        assert root not in stored.resolve().parents                                     # outside static roots
    layers = client.get(f"/api/v2/artifacts/{art['id']}/layers", headers=H["victor"]).json()
    assert layers["layers"] == [{"name": "conv2.weight", "shape": [4, 32, 3, 3]}]
    assert client.get(f"/api/v2/models/{m['id']}", headers=H["victor"]).json() == m
    found = client.get("/api/v2/models", headers=H["victor"], params={"sha256": art["sha256"]}).json()
    assert [x["id"] for x in found] == [m["id"]]


@pytest.mark.parametrize("name,data,status,detail", [
    ("model.exe", b"MZ\x90\x00", 415, "unsupported model file type"),
    ("model.pkl", pickle.dumps({"a": 1}), 415, "unsupported"),
    ("model", b"\x08\x07", 415, "unsupported"),
    ("model.pt", pickle.dumps({"weights": [1, 2]}), 422, "raw pickle"),
    ("model.pt", b"not a zip at all", 422, "zip archive"),
    ("model.pt", zip_bytes({"archive/version": "3"}), 422, "no data.pkl"),
    ("model.keras", zip_bytes({"metadata.json": "{}"}), 422, "no config.json"),
    ("model.h5", b"GIF89a" + b"\x00" * 100, 422, "HDF5 signature"),
    ("model.onnx", b"\x7fELF\x02\x01", 422, "ONNX ModelProto"),
    ("model.onnx", b"\x08\x07" + b"\xff" * 64, 422, "onnx.checker"),
    ("model.onnx", b"", 422, "empty"),
])
def test_bad_files_are_rejected(env, name, data, status, detail):
    app, client, H = env
    r = up(client, H["olivia"], data, name)
    assert r.status_code == status and detail in r.json()["detail"], r.text
    assert r.headers["content-type"] == "application/problem+json"
    incoming = Path(app.state.settings.uploads) / ".incoming"
    assert not incoming.exists() or not any(incoming.iterdir())                         # temp files cleaned up


def test_size_limit(env):
    app, client, H = env
    r = up(client, H["olivia"], b"\x08\x07" + b"\x00" * (LIMIT + 10), "big.onnx")      # streamed, then refused
    assert r.status_code == 413 and "limit" in r.json()["detail"]
    r = up(client, H["olivia"], b"\x08\x07" + b"\x00" * (LIMIT + 2 * 1024 * 1024), "huge.onnx")
    assert r.status_code == 413                                                         # refused by Content-Length


def test_zip_formats_are_accepted_without_unpickling(env):
    app, client, H = env
    # A .pt archive whose pickle would run code if loaded with pickle: accepted as bytes, never unpickled
    evil = pickle.dumps(type("X", (), {"__reduce__": lambda self: (print, ("pwned",))})())
    r = up(client, H["olivia"], zip_bytes({"archive/data.pkl": evil, "archive/version": "3"}), "evil.pt")
    assert r.status_code == 201 and r.json()["artifacts"][0]["framework"] == "pytorch"
    art_id = r.json()["artifacts"][0]["id"]
    try:
        import torch  # noqa: F401
    except ImportError:
        pytest.skip("torch not installed: layer listing of .pt files needs torch.load(weights_only=True)")
    r = client.get(f"/api/v2/artifacts/{art_id}/layers", headers=H["olivia"])
    assert r.status_code == 422                                                         # weights_only refuses it

    cfg = {"class_name": "Sequential", "config": {"layers": [{"class_name": "Conv2D", "config": {"name": "conv2"}}]}}
    r = up(client, H["olivia"], zip_bytes({"config.json": json.dumps(cfg), "metadata.json": "{}"}), "m.keras")
    assert r.status_code == 201 and r.json()["artifacts"][0]["framework"] == "keras"
    layers = client.get(f"/api/v2/artifacts/{r.json()['artifacts'][0]['id']}/layers", headers=H["olivia"]).json()
    assert layers["layers"] == [{"name": "conv2", "class_name": "Conv2D"}]


def test_real_torch_checkpoint_layers(env, tmp_path):
    torch = pytest.importorskip("torch")
    app, client, H = env
    p = tmp_path / "m.pt"
    torch.save({"conv2.weight": torch.zeros(8, 4, 3, 3), "conv2.bias": torch.zeros(8)}, p)
    r = up(client, H["olivia"], p.read_bytes(), "m.pt")
    assert r.status_code == 201
    layers = client.get(f"/api/v2/artifacts/{r.json()['artifacts'][0]['id']}/layers", headers=H["olivia"]).json()
    assert layers["layers"] == [{"name": "conv2.weight", "shape": [8, 4, 3, 3]}]


def test_purpose_follows_the_role(env):
    app, client, H = env
    r = up(client, H["victor"], ONNX, "suspect.onnx")
    assert r.status_code == 201 and r.json()["purpose"] == "suspect"
    assert up(client, H["victor"], ONNX, "x.onnx", purpose="watermarked").status_code == 403
    assert client.post("/api/v2/models", files={"file": ("x.onnx", io.BytesIO(ONNX))}).status_code == 401
    r = client.get("/api/v2/models", headers=H["olivia"], params={"purpose": "suspect"}).json()
    assert r and all(m["purpose"] == "suspect" for m in r)


def test_embedding_report(env):
    from sigil import protocol as P
    from sigil.identity import KeyPair
    app, client, H = env
    art = up(client, H["olivia"], ONNX, "e.onnx").json()["artifacts"][0]
    owner = client.post("/api/v2/owners", headers=H["olivia"],
                        json={"public_key": KeyPair.generate().public_hex, "label": "o"}).json()
    r = client.post("/api/v2/embeddings", headers=H["olivia"],
                    json={"model_artifact_id": art["id"], "owner_id": owner["id"], "config": P.Config().to_dict(),
                          "metrics": {"accuracy_before": 0.9869, "accuracy_after": 0.9866, "owner_errors": 0}})
    assert r.status_code == 201 and r.json()["config_hash"] == str(P.config_hash(P.Config()))
    r = client.post("/api/v2/embeddings", headers=H["olivia"],
                    json={"model_artifact_id": art["id"], "owner_id": owner["id"], "config": {"T": 64},
                          "metrics": {}})
    assert r.status_code == 422
    r = client.post("/api/v2/embeddings", headers=H["olivia"],
                    json={"model_artifact_id": art["id"], "owner_id": owner["id"], "config": P.Config().to_dict(),
                          "metrics": {}, "seed": "123"})
    assert r.status_code == 422                                                          # never accepts a seed
    assert len(client.get("/api/v2/embeddings", headers=H["victor"]).json()) == 1
