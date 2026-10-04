"""The verifier's procedure (ZK-06): a proof counts only if EVERY check below passes.

A valid SNARK on its own proves nothing useful (FIX-02): the public signals must be the ones the
verifier expects. Each failed check produces its own named reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import protocol as P
from .records import parse_time, registration_hash, verify_receipt, verify_registration


@dataclass
class Verdict:
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"accepted": self.accepted, "reasons": self.reasons, "checks": self.checks}


def expected_public_signals(registration: dict, claim: dict, suspect_w_q) -> list[str]:
    cfg = P.Config.from_dict(registration["config"])
    return [registration["pk_hash"], registration["config_hash"], registration["commitment"],
            str(P.w_hash(np.asarray(suspect_w_q, dtype=np.int64), cfg)), claim["nonce"]]


def verify_ownership(*, proof: dict, public: list[str], registration: dict, receipt: dict, claim: dict,
                     suspect_w, suspect_model_sha256: str, trusted_registry_keys: set[str],
                     vkey_path: Path | None = None, snark_verifier=None) -> Verdict:
    """suspect_w: the suspect model's Uchida vector (float), recomputed by the VERIFIER from the file."""
    reasons, checks = [], {}

    def check(name: str, ok: bool, reason: str):
        checks[name] = bool(ok)
        if not ok:
            reasons.append(reason)

    reg_problems = verify_registration(registration)
    check("registration_valid", not reg_problems, "registration invalid: " + "; ".join(reg_problems))
    rcp_problems = verify_receipt(receipt, registration, trusted_registry_keys)
    check("receipt_valid", not rcp_problems, "registry receipt invalid: " + "; ".join(rcp_problems))
    try:
        before = parse_time(receipt["registered_at"]) < parse_time(claim["opened_at"])
    except (KeyError, ValueError, TypeError, AttributeError):
        before = False
    check("registered_before_claim", before, "registration is not earlier than the claim")
    check("claim_matches_registration", claim.get("registration_sha256") == registration_hash(registration),
          "claim refers to a different registration")
    check("claim_matches_suspect", claim.get("suspect_model_sha256") == suspect_model_sha256,
          "claim refers to a different suspect model file")

    try:
        cfg = P.Config.from_dict(registration["config"])
        w_q = P.quantize(suspect_w, cfg)
        expected = expected_public_signals(registration, claim, w_q)
    except (KeyError, ValueError) as e:
        check("suspect_vector_valid", False, f"cannot recompute the suspect vector: {e}")
        return Verdict(False, reasons, checks)

    names = P.PUBLIC_SIGNALS
    got = [str(x) for x in public]
    check("public_signal_count", len(got) == len(expected), "wrong number of public signals")
    if len(got) == len(expected):
        for n, g, e in zip(names, got, expected):
            reason = {"w_hash": "proof is about a different model (w_hash mismatch)",
                      "nonce": "proof was made for a different claim (nonce mismatch: replay?)",
                      "commitment": "proof opens a different commitment",
                      "pk_hash": "proof is for a different owner key",
                      "config_hash": "proof uses a different watermark configuration"}[n]
            check(f"public_{n}", g == e, reason)

    if snark_verifier is None:
        from .zk.circom import artifacts, verify_snark
        vkey_path = vkey_path or artifacts(cfg).vkey
        snark_verifier = lambda: verify_snark(vkey_path, proof, public)  # noqa: E731
    check("snark_valid", bool(snark_verifier()), "the zk-SNARK does not verify")
    return Verdict(not reasons, reasons, checks)
