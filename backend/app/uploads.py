"""Model uploads (API-05): size limit, extension and magic-byte checks, SHA-256 on receipt, storage outside
the static root, framework detection, and layer listing with safe loaders only (never pickle).

  .pt     PyTorch zip archive (torch.save since 1.6) containing <name>/data.pkl. Raw pickle files are refused:
          they can only be read by unpickling. Layers are listed with torch.load(weights_only=True).
  .keras  Keras 3 zip archive with config.json (layers read from that JSON).
  .h5     HDF5 signature (layers read from the model_config attribute with h5py, if installed).
  .onnx   protobuf ModelProto (starts with the ir_version field); checked with onnx.checker when installed.
Files are content-addressed: <upload folder>/<sha[:2]>/<sha><ext>.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

from .problems import ProblemError

FRAMEWORKS = {".pt": "pytorch", ".h5": "keras", ".keras": "keras", ".onnx": "onnx"}
HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"
ZIP_MAGIC = b"PK\x03\x04"


def safe_filename(name: str | None) -> str:
    base = Path((name or "").replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._\-]+", "_", base).strip("._") or "model"
    return base[-200:]


def extension_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext not in FRAMEWORKS:
        raise ProblemError(415, f"unsupported model file type {ext or '(none)'}: use .pt, .h5, .keras or .onnx",
                           title="Unsupported Media Type")
    return ext


def _varint(data: bytes, i: int) -> tuple[int, int]:
    v = shift = 0
    while i < len(data) and shift < 64:
        b = data[i]
        v |= (b & 0x7F) << shift
        i += 1
        if not b & 0x80:
            return v, i
        shift += 7
    raise ValueError("truncated varint")


def check_magic(ext: str, head: bytes) -> None:
    bad = None
    if ext in (".pt", ".keras"):
        if head[:1] == b"\x80" and ext == ".pt":
            bad = "this .pt file is a raw pickle; only the zip format (torch.save, PyTorch >= 1.6) is accepted, " \
                  "because pickles can only be read by executing them"
        elif not head.startswith(ZIP_MAGIC):
            bad = f"a {ext} file must be a zip archive"
    elif ext == ".h5":
        if not any(head[o:o + 8] == HDF5_MAGIC for o in (0, 512, 1024, 2048) if len(head) >= o + 8):
            bad = "a .h5 file must start with the HDF5 signature"
    elif ext == ".onnx":
        try:
            if head[:1] != b"\x08":
                raise ValueError
            ir_version, _ = _varint(head, 1)
            if not 1 <= ir_version <= 100:
                raise ValueError
        except ValueError:
            bad = "a .onnx file must be an ONNX ModelProto (it starts with the ir_version field)"
    if bad:
        raise ProblemError(422, bad, title="Invalid model file")


def check_structure(ext: str, path: Path) -> None:
    """Deeper checks that never execute anything from the file."""
    if ext in (".pt", ".keras"):
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
        except zipfile.BadZipFile as e:
            raise ProblemError(422, f"not a valid zip archive: {e}", title="Invalid model file") from e
        if ext == ".pt" and not any(n.endswith("/data.pkl") or n == "data.pkl" for n in names):
            raise ProblemError(422, "not a PyTorch archive (no data.pkl entry)", title="Invalid model file")
        if ext == ".keras" and "config.json" not in names:
            raise ProblemError(422, "not a Keras 3 archive (no config.json)", title="Invalid model file")
    elif ext == ".onnx":
        try:
            import onnx
        except ImportError:
            return
        try:
            onnx.checker.check_model(str(path))
        except Exception as e:  # noqa: BLE001 - any checker failure means "not a valid model"
            raise ProblemError(422, f"onnx.checker rejected the model: {str(e).splitlines()[0][:300]}",
                               title="Invalid model file") from e


def store_upload(src, filename: str, uploads: Path, max_bytes: int) -> dict:
    """Stream `src` (a binary file object) into the upload folder, validating as it goes."""
    name = safe_filename(filename)
    ext = extension_of(name)
    uploads.mkdir(parents=True, exist_ok=True)
    tmpdir = uploads / ".incoming"
    tmpdir.mkdir(exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=tmpdir, suffix=ext)
    h, size, head = hashlib.sha256(), 0, b""
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise ProblemError(413, f"the file is larger than the {max_bytes:,}-byte limit",
                                       title="Payload Too Large")
                if len(head) < 4096:
                    head += chunk[:4096 - len(head)]
                h.update(chunk)
                out.write(chunk)
        if size == 0:
            raise ProblemError(422, "the file is empty", title="Invalid model file")
        check_magic(ext, head)
        check_structure(ext, Path(tmp))
        sha = h.hexdigest()
        rel = Path(sha[:2]) / f"{sha}{ext}"
        final = uploads / rel
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            os.unlink(tmp)
        else:
            os.replace(tmp, final)
        return {"filename": name, "extension": ext, "framework": FRAMEWORKS[ext], "sha256": sha, "size_bytes": size,
                "stored_path": rel.as_posix()}
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------------------------- layer listing
def list_layers(path: Path, ext: str) -> list[dict] | None:
    """Named weight tensors / layers, using safe loaders only. None if no loader is available."""
    try:
        if ext == ".onnx":
            import onnx
            m = onnx.load(str(path), load_external_data=False)
            return [{"name": t.name, "shape": list(t.dims)} for t in m.graph.initializer if len(t.dims) >= 2]
        if ext == ".keras":
            with zipfile.ZipFile(path) as z:
                cfg = json.loads(z.read("config.json"))
            return _keras_layers(cfg)
        if ext == ".h5":
            import h5py
            with h5py.File(path, "r") as f:
                raw = f.attrs.get("model_config")
            if raw is None:
                return []
            return _keras_layers(json.loads(raw.decode() if isinstance(raw, bytes) else raw))
        if ext == ".pt":
            import torch
            obj = torch.load(str(path), map_location="cpu", weights_only=True)    # SDK-04 safe loader
            if isinstance(obj, dict) and "state_dict" in obj and isinstance(obj["state_dict"], dict):
                obj = obj["state_dict"]
            if isinstance(obj, dict):
                return [{"name": k, "shape": list(v.shape)} for k, v in obj.items()
                        if hasattr(v, "shape") and len(v.shape) >= 2]
            return []
    except ImportError:
        return None
    except Exception as e:  # noqa: BLE001 - a file we can't parse has no listable layers
        raise ProblemError(422, f"could not read the layers ({e.__class__.__name__})", title="Invalid model file") from e
    return None


def _keras_layers(cfg) -> list[dict]:
    layers = (cfg.get("config") or {}).get("layers") or [] if isinstance(cfg, dict) else []
    out = []
    for layer in layers:
        if isinstance(layer, dict):
            c = layer.get("config") or {}
            out.append({"name": c.get("name") or layer.get("name"), "class_name": layer.get("class_name")})
    return out
