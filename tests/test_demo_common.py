"""demo/demo_common.py: atomic result writes and a commitment reader that never raises (FIX-11)."""
import json

import demo_common


def test_write_json_is_atomic_and_leaves_no_temp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(demo_common, "RESULTS", tmp_path)
    demo_common.write_json("a.json", {"x": 1})
    demo_common.write_json("sub/summary.json", {"y": [1, 2]})       # subfolder is created
    demo_common.write_json("a.json", {"x": 2})                      # replace an existing file
    assert json.loads((tmp_path / "a.json").read_text(encoding="utf-8")) == {"x": 2}
    assert json.loads((tmp_path / "sub" / "summary.json").read_text(encoding="utf-8")) == {"y": [1, 2]}
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == ["a.json", "summary.json"]


def test_failed_write_keeps_the_old_file(tmp_path, monkeypatch):
    target = tmp_path / "r.json"
    target.write_text('{"old": true}', encoding="utf-8")

    def broken_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(demo_common.os, "replace", broken_replace)
    try:
        demo_common.write_json(target, {"new": True})
        raise AssertionError("expected OSError")
    except OSError:
        pass
    assert json.loads(target.read_text(encoding="utf-8")) == {"old": True}
    assert [p.name for p in tmp_path.iterdir()] == ["r.json"]                   # temp file cleaned up


def test_current_commitment_never_raises(tmp_path):
    p = tmp_path / "public_commitment.json"
    assert demo_common.current_commitment(tmp_path) is None                     # missing
    for bad in ('{"commitment_sha256": "ab', "[]", '"x"', "{}", '{"commitment_sha256": 5}', ""):
        p.write_text(bad, encoding="utf-8")
        assert demo_common.current_commitment(tmp_path) is None, bad
    p.write_bytes(b"\xff\xfe\x00")
    assert demo_common.current_commitment(tmp_path) is None
    p.write_text('{"commitment_sha256": "abc123"}', encoding="utf-8")
    assert demo_common.current_commitment(tmp_path) == "abc123"
