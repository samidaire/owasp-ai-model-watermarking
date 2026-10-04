"""DEMO E2: does the OWNER's verification key accept the THIEF's proof?
(params private, no commitment; run after 05_ezkl_spike.py --vis private for owner and thief)"""
# EZKL reads $HOME (set by Git Bash, not by PowerShell/cmd) and panics if it is missing.
import os as _os
from pathlib import Path as _Path
_os.environ.setdefault("HOME", str(_Path.home()))
import asyncio, hashlib, inspect, shutil
from pathlib import Path
import ezkl

def run(fn, *a, **kw):
    async def _c():
        r = fn(*a, **kw)
        return await r if inspect.isawaitable(r) else r
    return asyncio.run(_c())

from wm_core import RESULTS, banner
banner("DEMO E2: thief's forged proof checked against the OWNER's verification key")
R = RESULTS
own, thf, x = R / "ezkl_private_owner", R / "ezkl_private_thief", R / "vk_crosscheck"
x.mkdir(exist_ok=True)
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
print("  -> Without a published commitment, the verifier cannot tell owner and thief apart.")
(x / "pk.key").unlink()

# ---- structured results for the web UI (additive)
from demo_common import current_commitment, write_json
write_json("vk_crosscheck.json", {"commitment": current_commitment(), "owner_vk": h(own / "vk.key"),
                                  "thief_vk": h(x / "vk.key"), "identical": h(own / "vk.key") == h(x / "vk.key"),
                                  "thief_verified_under_owner_vk": bool(ok)})
