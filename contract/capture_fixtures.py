"""Record contract/fixtures from REAL runs streamed through a live demo server.

  demo/.venv/Scripts/python demo/server.py --port 8790        # live mode, in another terminal
  python contract/capture_fixtures.py --port 8790

Writes fixtures/logs/<step>.log (exactly the lines the server streamed), fixtures/state.json,
fixtures/steps.json and fixtures/job.json. Never runs "retrain" (it would replace the owner key);
logs/retrain.log is maintained by hand and labelled as such.
"""
import argparse
import json
import time
import urllib.request
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures"
STEPS = ["evaluate", "attacks", "forgery", "committed", "zk", "zk_hashed", "all"]

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8790)
ap.add_argument("--skip", nargs="*", default=[], help="steps to skip (e.g. zk_hashed)")
args = ap.parse_args()
B = f"http://127.0.0.1:{args.port}"


def get(path):
    return json.load(urllib.request.urlopen(B + path))


def run(step):
    req = urllib.request.Request(B + "/api/run", data=json.dumps({"step": step}).encode(),
                                 headers={"Content-Type": "application/json"})
    job = json.load(urllib.request.urlopen(req))
    while True:
        time.sleep(1)
        j = get(f"/api/jobs/{job['id']}")
        if not j["running"]:
            return j


assert get("/api/state")["mode"] == "live", "capture from a LIVE server, not --simulate"
(FIX / "logs").mkdir(parents=True, exist_ok=True)
last = None
for step in STEPS:
    if step in args.skip:
        continue
    j = run(step)
    print(f"{step:<10} exit={j['code']} lines={j['lines']} {j['ended'] - j['started']:.1f}s")
    assert j["code"] == 0, f"{step} failed; not saving its log"
    (FIX / "logs" / f"{step}.log").write_text("\n".join(j["output"]) + "\n", encoding="utf-8")
    last = j
(FIX / "state.json").write_text(json.dumps(get("/api/state"), indent=2), encoding="utf-8")
(FIX / "steps.json").write_text(json.dumps(get("/api/steps"), indent=2), encoding="utf-8")
if last:
    (FIX / "job.json").write_text(json.dumps({**last, "output": last["output"][:12] + ["..."]}, indent=2), encoding="utf-8")
print("fixtures written to", FIX)
