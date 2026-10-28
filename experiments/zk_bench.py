"""ZK-10 / RQ3: what does a Circom + SnarkJS Groth16 ownership proof cost on this machine?

For each configuration that has been set up (sigil.zk.circom.setup), measures over --runs proofs:
constraints, witness time, proving time, verification time, proof and key sizes, and the peak memory
of the SnarkJS (node) processes. A configuration that is only compiled (`sigil zk-info`) is listed with
its size from the .r1cs header and the Powers of Tau it would need. Writes experiments/results/zk_bench.json
and docs/reports/zk_bench.md.

    .venv/Scripts/python experiments/zk_bench.py --runs 3
"""
import argparse
import json
import math
import platform
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import psutil

from sigil import protocol as P
from sigil.zk import circom as Z

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")       # the report prints θ; Windows consoles default to cp1252
ap = argparse.ArgumentParser()
ap.add_argument("--runs", type=int, default=3)
args = ap.parse_args()

CONFIGS = [P.Config(), P.Config(T=256, max_err=32),
           P.Config(M=2304, layer="layer3.1.conv2")]     # one ResNet-18 layer (CIFAR-10, experiments/robustness)


def r1cs_header(path: Path) -> dict:
    """Constraint and wire counts from a .r1cs header (snarkjs r1cs info runs out of memory on large circuits)."""
    with open(path, "rb") as f:
        if f.read(4) != b"r1cs":
            raise ValueError(f"{path} is not an r1cs file")
        _, sections = struct.unpack("<II", f.read(8))
        for _ in range(sections):
            kind, size = struct.unpack("<IQ", f.read(12))
            if kind == 1:
                n8, = struct.unpack("<I", f.read(4))
                f.read(n8)
                wires, pub_out, pub_in, _ = struct.unpack("<IIII", f.read(16))
                f.read(8)
                constraints, = struct.unpack("<I", f.read(4))
                return {"constraints": constraints, "wires": wires,
                        "ptau_power": math.ceil(math.log2(constraints + pub_in + pub_out + 1))}
            f.seek(size, 1)
    raise ValueError(f"{path}: no header section")


def embed_like(seed, pkh, cfg, scale=0.02):
    X = P.key_matrix(seed, pkh, cfg).astype(float)
    target = P.signature_bits(seed, pkh, cfg).astype(float) * 2 - 1
    w = X.T @ target / cfg.M * scale
    for _ in range(300):
        bad = np.sign(X @ P.quantize(w, cfg)) != target
        if not bad.any():
            return w
        w += 0.5 * scale * (X[bad].T @ target[bad]) / cfg.M
    raise RuntimeError("could not construct a watermarked vector")


class PeakNodeRSS:
    """Samples the summed RSS of node.exe/node child processes while a step runs."""
    def __enter__(self):
        self.peak, self._stop = 0, False
        me = psutil.Process()
        def loop():
            while not self._stop:
                try:
                    rss = sum(c.memory_info().rss for c in me.children(recursive=True))
                    self.peak = max(self.peak, rss)
                except psutil.Error:
                    pass
                time.sleep(0.05)
        self._t = threading.Thread(target=loop, daemon=True)
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop = True
        self._t.join()


rows, sized = [], []
for cfg in CONFIGS:
    art = Z.artifacts(cfg)
    if not (art.zkey.exists() and art.vkey.exists()):
        if art.r1cs.exists():
            sized.append({"circuit": art.name, "T": cfg.T, "M": cfg.M, "max_err": cfg.max_err, "layer": cfg.layer,
                          **r1cs_header(art.r1cs), "r1cs_bytes": art.r1cs.stat().st_size})
            print(json.dumps(sized[-1]))
        else:
            print(f"skip {art.name}: not compiled or set up")
        continue
    info = Z.r1cs_info(art)
    transcript = json.loads(art.transcript.read_text()) if art.transcript.exists() else {}
    seed, pkh = P.new_seed(), P.pk_hash(bytes(range(32)))
    w = embed_like(seed, pkh, cfg)
    inp = P.circuit_input(seed, P.quantize(w, cfg), pkh, cfg, nonce=42)
    wit, prv, ver, peaks = [], [], [], []
    for _ in range(args.runs):
        with PeakNodeRSS() as mem:
            proof, public, t = Z.prove(cfg, inp)
        peaks.append(mem.peak)
        wit.append(t["witness_s"])
        prv.append(t["prove_s"])
        t0 = time.time()
        assert Z.verify_snark(art.vkey, proof, public)
        ver.append(time.time() - t0)
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "p.json").write_text(json.dumps(proof))
        proof_bytes = (Path(tmp) / "p.json").stat().st_size
    med = statistics.median
    rows.append({
        "circuit": art.name, "T": cfg.T, "M": cfg.M, "max_err": cfg.max_err,
        "constraints": info["of_constraints"], "ptau": transcript.get("ptau"),
        "setup_s": transcript.get("setup_seconds"),
        "witness_s_median": round(med(wit), 3), "prove_s_median": round(med(prv), 3),
        "verify_s_median": round(med(ver), 3), "proof_json_bytes": proof_bytes,
        "zkey_bytes": art.zkey.stat().st_size, "vkey_bytes": art.vkey.stat().st_size,
        "peak_node_rss_bytes": max(peaks), "runs": args.runs,
    })
    print(json.dumps(rows[-1]))

env = {"cpu": platform.processor() or platform.machine(), "logical_cpus": psutil.cpu_count(),
       "ram_bytes": psutil.virtual_memory().total, "os": platform.platform(),
       "node": subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip(),
       "python": sys.version.split()[0]}
git = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
out = {"env": env, "git_commit": git, "rows": rows, "compiled_not_set_up": sized}
(ROOT / "experiments" / "results").mkdir(parents=True, exist_ok=True)
(ROOT / "experiments" / "results" / "zk_bench.json").write_text(json.dumps(out, indent=2))

mb = lambda b: f"{b / 2**20:.1f} MiB"   # noqa: E731
lines = ["# ZK-10 / RQ3: cost of Circom + SnarkJS Groth16 ownership proofs", "",
         f"Generated by `experiments/zk_bench.py` (median of {args.runs} runs) on {env['cpu']}, "
         f"{env['logical_cpus']} logical CPUs, {env['ram_bytes'] / 2**30:.1f} GiB RAM, node {env['node']}. "
         "Proving uses snarkjs (WebAssembly, CPU only). Peak memory is sampled every 50 ms.", "",
         "| Circuit | Constraints | ptau | Setup | Witness | Prove | Verify | Proof (JSON) | zkey | vkey | Peak RAM |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
for r in rows:
    lines.append(f"| T={r['T']}, M={r['M']}, θ={r['max_err']}/{r['T']} | {r['constraints']:,} | {r['ptau']} | "
                 f"{r['setup_s']} s | {r['witness_s_median']} s | {r['prove_s_median']} s | {r['verify_s_median']} s | "
                 f"{r['proof_json_bytes']:,} B | {mb(r['zkey_bytes'])} | {r['vkey_bytes']:,} B | {mb(r['peak_node_rss_bytes'])} |")
lines += ["", "A Groth16 proof is three curve points (2 in G1, 1 in G2): 256 bytes uncompressed in binary form; "
              "the JSON encoding above is larger. Verification time includes starting node."]
if sized:
    lines += ["", "**Compiled but not set up** (size from the .r1cs header; no proving key on this machine):", "",
              "| Circuit | Layer | Constraints | Wires | ptau needed | .r1cs |", "|---|---|---|---|---|---|"]
    for r in sized:
        lines.append(f"| T={r['T']}, M={r['M']}, θ={r['max_err']}/{r['T']} | `{r['layer']}` | {r['constraints']:,} | "
                     f"{r['wires']:,} | 2^{r['ptau_power']} | {mb(r['r1cs_bytes'])} |")
(ROOT / "docs" / "reports").mkdir(parents=True, exist_ok=True)
(ROOT / "docs" / "reports" / "zk_bench.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
