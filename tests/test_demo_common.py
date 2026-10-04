"""demo/demo_common.py: atomic result writes and a commitment reader that never raises (FIX-11),
and log scrubbing of absolute user paths (FIX-15)."""
import json
import os

import pytest

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


def test_scrub_paths_makes_this_checkout_relative():
    rel = os.path.join("demo", "05_ezkl_spike.py")
    assert demo_common.scrub_paths(f"{demo_common.REPO / rel}:100: DeprecationWarning") == f"{rel}:100: DeprecationWarning"
    assert demo_common.scrub_paths(f"Saved {demo_common.REPO.as_posix()}/demo/results/a.json") == "Saved demo/results/a.json"


@pytest.mark.parametrize("line, expected", [
    (r"  Saved C:\Users\alice\Documents\Projects\OWASP AI Model Watermarking\demo\results\ezkl_private_owner\summary.json",
     r"  Saved demo\results\ezkl_private_owner\summary.json"),
    (r"C:\Users\alice\Documents\Projects\OWASP AI Model Watermarking\demo\05_ezkl_spike.py:100: DeprecationWarning: x",
     r"demo\05_ezkl_spike.py:100: DeprecationWarning: x"),
    ('  File "/home/alice/src/owasp/demo/run_all.py", line 3', '  File "demo/run_all.py", line 3'),
    (r"HOME=C:\Users\Yash\AppData\Local", r"HOME=~\AppData\Local"),
    ("cache at /Users/bob/.cache/x and /c/Users/carol/y", "cache at ~/.cache/x and ~/y"),
    ("python C:/Users/dave/venv/Scripts/python.exe", "python ~/venv/Scripts/python.exe"),
])
def test_scrub_paths_hides_other_users(line, expected):
    assert demo_common.scrub_paths(line) == expected


@pytest.mark.parametrize("line", ["  Search time : 2.1s (9,381 seeds/s)", "owner:yash", "results/attacks.png",
                                  "http://127.0.0.1:8765/api/state", "https://example.com/home/page", "$ python 02_attacks.py",
                                  "x = a/home/b"])
def test_scrub_paths_leaves_other_lines_alone(line):
    assert demo_common.scrub_paths(line) == line


def test_served_run_log_has_no_personal_paths():
    text = (demo_common.RESULTS / "run_log.txt").read_text(encoding="utf-8")
    assert scrub_all(text) == text
    assert "Users\\" not in text and "/home/" not in text


def scrub_all(text):
    return "\n".join(demo_common.scrub_paths(line) for line in text.split("\n"))


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
