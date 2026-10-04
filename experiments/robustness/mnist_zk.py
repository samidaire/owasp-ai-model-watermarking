"""ROB-05, ZK in the loop: a Groth16 ownership proof for every attacked MNIST model of one seed.

For each suspect file saved by mnist_matrix.py (seed ``zk_seed``, white-box model) the owner tries to prove
ownership with sigil.zk.circom.prove and the verifier runs sigil.verify.verify_ownership: registration
(owner-signed), registry receipt, a fresh claim nonce, public signals recomputed from the suspect file
itself, and the SNARK. Expected: the proof verifies iff the watermark survives (errors <= max_err), because
the circuit enforces the same threshold. For the realigned permutation rows the owner discloses the
permutation with the claim and the verifier applies it to the suspect file before recomputing w (it can
check that the reordering is functionally neutral).

If the Groth16 setup for the config is missing (circuits/build/<name>.zkey, the wasm and keys/<name>.vkey.json
under SIGIL_CIRCUITS) every row is written as "pending setup" together with the decision of the Python
reference implementation, and the script exits 0.

    SIGIL_CIRCUITS=<repo>/circuits python experiments/robustness/mnist_zk.py
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np
import torch

from common import CKPT, HERE, RESULT_SCHEMA, RESULTS, Owner, device, env_info, keypair, load_config, log, sha256_file, write_json
from sigil import attacks as A
from sigil import protocol as P
from sigil.records import make_claim, make_receipt, make_registration
from sigil.verify import verify_ownership
from wm_core import Net


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "mnist.yaml"))
    args = ap.parse_args()
    cfg = load_config(args.config)
    s = cfg["zk_seed"]
    wmc = cfg["watermark"]
    pcfg = P.Config(T=wmc["T"], M=wmc["M"], layer=wmc["layer"], scale_bits=wmc["scale_bits"], w_bits=wmc["w_bits"],
                    max_err=wmc["max_err"])
    dev = torch.device("cpu")              # proving is CPU work; weights are read from the files
    owner = Owner(f"m5/mnist/owner/{s}", pcfg)
    registry = keypair("m5/registry/ed25519")
    prefix = cfg.get("ckpt_prefix", "mnist")
    folder = CKPT / f"{prefix}_attacked_s{s}"
    manifest = json.loads((folder / "manifest.json").read_text())
    registered = CKPT / f"{prefix}_wm_s{s}.pt"
    reg = make_registration(owner.keys, owner.seed, pcfg, sha256_file(registered), created_at="2026-10-01T09:00:00Z")
    rcp = make_receipt(registry, reg, registered_at="2026-10-01T09:00:01Z")

    status, Z, why = "complete", None, None
    try:
        from sigil.zk import circom as Z
        a = Z.artifacts(pcfg)
        missing = [str(p) for p in (a.zkey, a.wasm, a.vkey) if not p.exists()]
        if missing:
            status, why = "pending setup", "missing: " + ", ".join(missing)
    except Exception as e:      # toolchain not found
        status, why = "pending setup", f"{type(e).__name__}: {e}"
    log(f"ZK status: {status} {why or ''}")

    rows = []
    for item in manifest:
        f = folder / item["file"]
        suspect = Net().to(dev)
        suspect.load_state_dict(torch.load(f, map_location=dev, weights_only=True))
        if item.get("realign_perm") is not None:
            suspect = A.permute_channels(suspect, wmc["producer"], wmc["layer"], perm=item["realign_perm"])
        w = A.uchida_vector(suspect.conv2.weight).detach().double().numpy()
        w_q = P.quantize(w, pcfg)
        det = owner.detect(w_q)
        row = {"attack": item["attack"], "family": item["family"], "errors": det.errors, "survived": det.accepted,
               "realigned": item.get("realign_perm") is not None}
        if status != "complete":
            row.update({"proof_verifies": "pending setup", "reference_decision": det.accepted})
            rows.append(row)
            continue
        claim = make_claim(reg, sha256_file(f))
        t0 = time.time()
        try:
            proof, public, timing = Z.prove(pcfg, P.circuit_input(owner.seed, w_q, owner.pkh, pcfg, int(claim["nonce"])))
            row.update({"proof_generated": True, **timing})
        except Z.ZkError as e:
            row.update({"proof_generated": False, "proof_verifies": False, "reason": str(e).splitlines()[0],
                        "consistent": det.accepted is False, "seconds": round(time.time() - t0, 2)})
            rows.append(row)
            log(f"{item['attack']:<55s} errors={det.errors:2d} -> no witness (rejected)")
            continue
        t1 = time.time()
        v = verify_ownership(proof=proof, public=public, registration=reg, receipt=rcp, claim=claim, suspect_w=w,
                             suspect_model_sha256=sha256_file(f), trusted_registry_keys={registry.public_hex})
        row.update({"proof_verifies": v.accepted, "reasons": v.reasons, "verify_s": round(time.time() - t1, 3),
                    "consistent": v.accepted == det.accepted, "seconds": round(time.time() - t0, 2)})
        rows.append(row)
        log(f"{item['attack']:<55s} errors={det.errors:2d} -> proof verifies: {v.accepted}")
    out = {"schema": RESULT_SCHEMA, "experiment": "mnist_zk", "config": cfg, "seed": s, "env": env_info(device()),
           "protocol_config": pcfg.to_dict(), "circuit": Z.circuit_name(pcfg) if Z else None, "status": status,
           "status_detail": why, "registration_commitment": reg["commitment"], "rows": rows,
           "all_consistent": all(r.get("consistent", True) for r in rows) if status == "complete" else None}
    write_json(RESULTS / f"{cfg.get('out', 'mnist_matrix').replace('matrix', 'zk')}.json", out)
    log(f"done ({status})")


if __name__ == "__main__":
    main()
