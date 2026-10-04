"""DEMO E2: does the OWNER's verification key accept the THIEF's proof?
(params private, no commitment; run after 05_ezkl_spike.py --vis private --who owner, and
 05_ezkl_spike.py --vis private --who thief --keep-onnx)

Besides proof validity, the verifier checks the proofs' PUBLIC signals (interim FIX-02,
zk_checks.py): the score is 64 and the public input is the suspect model's watermark vector.
The thief's circuit model and the recompiled circuit/witness are deleted afterwards (FIX-03;
KEEP_ONNX=1 keeps them)."""
# EZKL reads $HOME (set by Git Bash, not by PowerShell/cmd) and panics if it is missing.
import os as _os
from pathlib import Path as _Path
_os.environ.setdefault("HOME", str(_Path.home()))
import asyncio, atexit, hashlib, inspect, shutil
from pathlib import Path
import ezkl
import torch

def run(fn, *a, **kw):
    async def _c():
        r = fn(*a, **kw)
        return await r if inspect.isawaitable(r) else r
    return asyncio.run(_c())

from wm_core import RESULTS, banner, load_model, wm_vector
from zk_checks import public_signal_report


def suspect_vector():
    """The expected public input: the stolen model's watermark vector, built exactly as 05_ezkl_spike.py does."""
    w = wm_vector(load_model("watermarked", torch.device("cpu"))).detach()
    return (w / w.std()).flatten().tolist()


banner("DEMO E2: thief's forged proof checked against the OWNER's verification key")
R = RESULTS
own, thf, x = R / "ezkl_private_owner", R / "ezkl_private_thief", R / "vk_crosscheck"
if not (thf / "extract.onnx").exists():
    raise SystemExit("  (thief's circuit model missing: run 05_ezkl_spike.py --vis private --who thief --keep-onnx first)")
x.mkdir(exist_ok=True)


def delete_circuit_files():
    """FIX-03: circuit models, compiled circuits and witnesses embed the (forged) key; don't leave them."""
    if _os.environ.get("KEEP_ONNX") == "1":
        return
    for f in (thf / "extract.onnx", thf / "extract.onnx.data", x / "thief.compiled", x / "witness.json"):
        try:
            f.unlink(missing_ok=True)
        except OSError as e:
            print(f"  WARNING: could not delete {f.name} ({e.strerror})")


atexit.register(delete_circuit_files)                     # also if a step below fails
import json
# use exactly the SRS the owner's proof was made with (public, or the TEST-ONLY fallback)
SRS = str(own / json.loads((own / "summary.json").read_text()).get("srs_file", "kzg.srs"))
shutil.copy(own / "settings.json", x / "settings.json")            # owner's settings, thief's model
run(ezkl.compile_circuit, str(thf / "extract.onnx"), str(x / "thief.compiled"), str(x / "settings.json"))
run(ezkl.gen_witness, str(thf / "input.json"), str(x / "thief.compiled"), str(x / "witness.json"), srs_path=SRS)
run(ezkl.setup, str(x / "thief.compiled"), str(x / "vk.key"), str(x / "pk.key"), srs_path=SRS)
h = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]
print("owner VK                  :", h(own / "vk.key"))
print("thief VK (owner settings) :", h(x / "vk.key"))
run(ezkl.prove, str(x / "witness.json"), str(x / "thief.compiled"), str(x / "pk.key"), str(x / "proof.json"), srs_path=SRS)
ok = run(ezkl.verify, str(x / "proof.json"), str(own / "settings.json"), str(own / "vk.key"), srs_path=SRS)
print("thief proof verified under OWNER's VK:", ok)
delete_circuit_files()

# ---- public-signal checks (FIX-02): which values were proven, not just "some valid proof"
ok_owner = run(ezkl.verify, str(own / "proof.json"), str(own / "settings.json"), str(own / "vk.key"), srs_path=SRS)
settings = json.loads((own / "settings.json").read_text())
expected = suspect_vector()
public_checks = {
    "owner": public_signal_report(json.loads((own / "proof.json").read_text()), settings, expected, ok_owner),
    "thief_under_owner_vk": public_signal_report(json.loads((x / "proof.json").read_text()), settings, expected, ok),
}
for name, c in public_checks.items():
    detail = "; ".join(c["reasons"]) or "score = 64, public input = the suspect model's w"
    print(f"public signals, {name:<20}: {'ACCEPT' if c['accepted'] else 'REJECT'}  ({detail})")
print("  -> Without a published commitment, the verifier cannot tell owner and thief apart.")
(x / "pk.key").unlink()

# ---- structured results for the web UI (additive)
from demo_common import current_commitment, write_json
write_json("vk_crosscheck.json", {"commitment": current_commitment(), "owner_vk": h(own / "vk.key"),
                                  "thief_vk": h(x / "vk.key"), "identical": h(own / "vk.key") == h(x / "vk.key"),
                                  "thief_verified_under_owner_vk": bool(ok),
                                  "public_checks": public_checks})
