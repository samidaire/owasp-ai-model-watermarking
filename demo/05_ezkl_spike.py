"""DEMO E (stretch): zero-knowledge proof of Uchida watermark extraction with EZKL (Halo2/KZG).

Statement proven:  "I know a private key X (64x288) and signature s in {-1,+1}^64 such that,
on the suspect model's PUBLIC watermark vector w, score = #{j : s_j * (X_j . w) >= 1} = 64."

  --vis private : params are private witnesses (ZKROWNN-style, NO commitment)
  --vis hashed  : EZKL also outputs a Poseidon hash of the private params as a public value,
                  i.e. a ZK-friendly commitment to (X, s) that can be published at embedding time
  --who thief   : prove with the thief's FORGED key instead (demo C's counterfeit)

EZKL licence note: no open-source licence file in the EZKL repo (01 report, gap G5).
Research/demo use only. SRS from ezkl.get_srs (public); falls back to gen_srs (TEST ONLY).
"""
# EZKL reads $HOME (set by Git Bash, not by PowerShell/cmd) and panics if it is missing.
import os as _os
from pathlib import Path as _Path
_os.environ.setdefault("HOME", str(_Path.home()))
import argparse
import asyncio
import inspect
import json
import os
import time

import ezkl
import torch
import torch.nn as nn

from wm_core import RESULTS, T_BITS, banner, device, load_model, load_owner, text_to_bits, wm_vector

ap = argparse.ArgumentParser()
ap.add_argument("--vis", choices=["private", "hashed"], default="private")
ap.add_argument("--who", choices=["owner", "thief"], default="owner")
args = ap.parse_args()

OUT = RESULTS / f"ezkl_{args.vis}_{args.who}"
OUT.mkdir(parents=True, exist_ok=True)
P = {k: str(OUT / v) for k, v in dict(onnx="extract.onnx", data="input.json", settings="settings.json",
                                       compiled="extract.compiled", srs="kzg.srs", witness="witness.json",
                                       vk="vk.key", pk="pk.key", proof="proof.json").items()}


def run(fn, *a, **kw):
    """Call inside a running event loop (some EZKL calls, e.g. get_srs, require one)."""
    async def _call():
        r = fn(*a, **kw)
        return await r if inspect.isawaitable(r) else r
    return asyncio.run(_call())


def timed(label, fn, *a, **kw):
    t0 = time.time()
    r = run(fn, *a, **kw)
    dt = time.time() - t0
    print(f"  {label:<18} {dt:8.2f}s   -> {r if not isinstance(r, (dict, list)) else 'ok'}")
    return r, dt


class ExtractScore(nn.Module):
    def __init__(self, X, s):
        super().__init__()
        self.X = nn.Parameter(X.clone())
        self.s = nn.Parameter(s.clone())

    def forward(self, w):
        m = (w @ self.X.T) * self.s                        # signed margins, shape [1, 64]
        agree = torch.relu(m) - torch.relu(m - 1.0)        # 1 if margin >= 1, 0 if <= 0
        return agree.sum(dim=1, keepdim=True)              # public score (64 = all bits agree)


dev = torch.device("cpu")
_, _, _, X, b = load_owner(dev)
stolen = load_model("watermarked", dev)
w = wm_vector(stolen).detach()
w = (w / w.std()).unsqueeze(0)                            # public, sign-preserving normalisation

if args.who == "thief":
    target = torch.from_numpy(text_to_bits("MALLORY!")).float()
    g = torch.Generator().manual_seed(0)
    R = torch.randn(T_BITS, w.shape[1], generator=g)
    while True:                                             # resample rows with small margins:
        small = (R @ w[0]).abs() < 1.5                      # a forger can always pick large ones
        if not small.any():
            break
        R[small] = torch.randn(int(small.sum()), w.shape[1], generator=g)
    sgn = torch.sign(R @ w[0])
    R = R * (sgn * (target * 2 - 1)).unsqueeze(1)          # demo C's sign-fit forgery
    X, s = R, target * 2 - 1
else:
    s = b.float() * 2 - 1

model = ExtractScore(X, s).eval()
with torch.no_grad():
    plain = model(w).item()
    margins = ((w @ X.T) * s)[0]
banner(f"DEMO E: EZKL proof  (params={args.vis}, prover={args.who})")
print(f"  Plain PyTorch score : {plain:.0f}/64   (min signed margin {margins.min():.2f})")

try:   # EZKL's tract parser wants the legacy (TorchScript) exporter's output
    torch.onnx.export(model, (w,), P["onnx"], input_names=["input"], output_names=["output"],
                      opset_version=13, dynamo=False, do_constant_folding=True)
except Exception as e:
    print(f"  legacy ONNX export unavailable ({e}); using dynamo exporter")
    torch.onnx.export(model, (w,), P["onnx"], input_names=["input"], output_names=["output"], opset_version=18)
import onnx
_m = onnx.load(P["onnx"])
print(f"  ONNX: ir_version={_m.ir_version} opset={[o.version for o in _m.opset_import]} "
      f"ops={sorted({n.op_type for n in _m.graph.node})}")
if _m.ir_version > 8:
    _m.ir_version = 8
    onnx.save(_m, P["onnx"])
json.dump({"input_data": [w.flatten().tolist()]}, open(P["data"], "w"))

ra = ezkl.PyRunArgs()
ra.input_visibility = "public"
ra.output_visibility = "public"
ra.param_visibility = args.vis
import threading
import psutil
_peak = {"rss": 0}
def _monitor():
    proc = psutil.Process()
    while not _peak.get("stop"):
        _peak["rss"] = max(_peak["rss"], proc.memory_info().rss)
        time.sleep(0.1)
threading.Thread(target=_monitor, daemon=True).start()
times = {}
_, times["gen_settings"] = timed("gen_settings", ezkl.gen_settings, P["onnx"], P["settings"], py_run_args=ra)
_, times["calibrate"] = timed("calibrate", ezkl.calibrate_settings, P["data"], P["onnx"], P["settings"], "resources")
_, times["compile"] = timed("compile_circuit", ezkl.compile_circuit, P["onnx"], P["compiled"], P["settings"])
logrows = json.load(open(P["settings"]))["run_args"]["logrows"]
srs = P["srs"]
try:
    _, times["srs"] = timed("get_srs (public)", ezkl.get_srs, P["settings"], None, srs)
    srs_kind = "public (get_srs)"
except Exception as e:
    # Write the test SRS to its OWN file: overwriting kzg.srs would poison the cached public SRS,
    # and every later online run would then fail its hash check and fall back again.
    srs = str(OUT / "kzg_test.srs")
    print(f"  get_srs failed ({e}); using gen_srs -> TEST-ONLY SRS")
    _, times["srs"] = timed("gen_srs (TEST)", ezkl.gen_srs, srs, logrows)
    srs_kind = "TEST-ONLY (gen_srs)"
_, times["gen_witness"] = timed("gen_witness", ezkl.gen_witness, P["data"], P["compiled"], P["witness"], srs_path=srs)
_, times["setup"] = timed("setup", ezkl.setup, P["compiled"], P["vk"], P["pk"], srs_path=srs)
_, times["prove"] = timed("prove", ezkl.prove, P["witness"], P["compiled"], P["pk"], P["proof"], srs_path=srs)
ok, times["verify"] = timed("verify", ezkl.verify, P["proof"], P["settings"], P["vk"], srs_path=srs)

proof = json.load(open(P["proof"]))
pretty = proof.get("pretty_public_inputs") or {}
summary = {
    "params_visibility": args.vis, "prover": args.who, "verified": bool(ok), "logrows": logrows, "srs": srs_kind,
    "srs_file": os.path.basename(srs),
    "plain_score": plain,
    "public_outputs": pretty.get("rescaled_outputs"),
    "public_param_hashes": pretty.get("processed_params") or pretty.get("outputs_hashes") or None,
    "proof_bytes": os.path.getsize(P["proof"]), "vk_bytes": os.path.getsize(P["vk"]),
    "pk_bytes": os.path.getsize(P["pk"]), "seconds": {k: round(v, 3) for k, v in times.items()},
    "peak_rss_bytes": _peak["rss"],
}
_peak["stop"] = True
from demo_common import current_commitment   # web UI: detect results made with an older owner key
summary["commitment"] = current_commitment()
summary["min_margin"] = float(margins.min())
pp = pretty.get("processed_params")
if pp:
    summary["param_commitment_poseidon"] = pp
json.dump(summary, open(OUT / "summary.json", "w"), indent=2)
if not os.environ.get("KEEP_PK"):
    os.remove(P["pk"])                                      # proving keys can be ~10 GB; size is logged
banner("DEMO E RESULT")
print(f"  verified={summary['verified']}  logrows={logrows}  SRS={srs_kind}")
print(f"  public output (score)  : {summary['public_outputs']}")
if args.vis == "hashed":
    print(f"  public Poseidon commitment to private params: {str(pp)[:80]}")
print(f"  prove {times['prove']:.2f}s | verify {times['verify'] * 1000:.0f} ms | proof {summary['proof_bytes'] / 1024:.1f} KB "
      f"| vk {summary['vk_bytes'] / 1024:.1f} KB | pk {summary['pk_bytes'] / 2**20:.1f} MB "
      f"| peak RAM {summary['peak_rss_bytes'] / 2**30:.2f} GiB")
print(f"  Saved {OUT / 'summary.json'}")
