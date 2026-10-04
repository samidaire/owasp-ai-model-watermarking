"""Public-signal checks for the EZKL proofs of demo E (interim FIX-02). Pure Python: no torch, no ezkl.

ezkl.verify() only says "this proof is valid for SOME public values". A verifier must also check
WHICH public values it was made for:
  1. the proof verified (the caller passes ezkl.verify's result in);
  2. the public score (the circuit's one output) is 64: every signature bit agrees;
  3. the public input is the SUSPECT model's watermark vector w, within the input quantisation
     tolerance 2 * 2**-input_scale (input_scale from settings.json). The caller computes w exactly as
     05_ezkl_spike.py does: wm_vector(stolen) / std, flattened, as a list of floats;
  4. optionally (E3, params "hashed"): the Poseidon hash of the private params is the owner's
     published commitment.
The readable values come from proof.json's `pretty_public_inputs` (`rescaled_inputs`,
`rescaled_outputs`, `processed_params`). Those fields are NOT covered by the proof, so they are
also cross-checked against `instances`, the field elements the proof actually verifies
(layout: param hashes, then inputs, then outputs; 32-byte little-endian hex).
"""
BN254_P = 0x30644E72E131A029B85045B68181585D2833E84879B9709143E1F593F0000001
EXPECTED_SCORE = 64


def _flat(x):
    if isinstance(x, (list, tuple)):
        return [v for item in x for v in _flat(item)]
    return [x]


def _felt_le(h: str) -> int:
    """Instance encoding: 64 hex chars, little-endian."""
    return int.from_bytes(bytes.fromhex(h), "little")


def _felt_be(h: str) -> int:
    """pretty_public_inputs encoding: '0x...' big-endian."""
    return int(h, 16)


def _signed(v: int) -> int:
    return v - BN254_P if v > BN254_P // 2 else v


def input_scale(settings: dict) -> int:
    ra = settings.get("run_args") or {}
    if "input_scale" in ra:
        return int(ra["input_scale"])
    return int(settings["model_input_scales"][0])


def output_scale(settings: dict) -> int:
    scales = settings.get("model_output_scales")
    return int(scales[0]) if scales else input_scale(settings)


def input_tolerance(settings: dict) -> float:
    """Inputs are fixed-point with 2**-input_scale resolution; allow two quanta."""
    return 2.0 ** -input_scale(settings) * 2


def _instance_mismatch(proof, settings, hashes, inputs, outputs):
    """None if the pretty values are exactly what the proof's instances encode, else a reason."""
    inst = proof.get("instances")
    if not inst:
        return "proof.json has no instances"
    try:
        vals = [_felt_le(h) for h in _flat(inst)]
        hash_vals = [_felt_be(h) for h in hashes]
    except (TypeError, ValueError):
        return "proof.json instances are malformed"
    if len(vals) != len(hashes) + len(inputs) + len(outputs):
        return (f"pretty_public_inputs do not match the proof's instances "
                f"({len(vals)} instances vs {len(hashes)} + {len(inputs)} + {len(outputs)} public values)")
    nh, ni = len(hashes), len(inputs)
    qi, qo = 2.0 ** -input_scale(settings), 2.0 ** -output_scale(settings)
    ok = (vals[:nh] == hash_vals
          and all(abs(_signed(v) * qi - x) <= qi / 2 for v, x in zip(vals[nh:nh + ni], inputs))
          and all(abs(_signed(v) * qo - y) <= qo / 2 for v, y in zip(vals[nh + ni:], outputs)))
    return None if ok else "pretty_public_inputs do not match the values the proof verifies (edited?)"


def public_signal_report(proof: dict, settings: dict, expected_input, verified: bool,
                         expected_score: int = EXPECTED_SCORE, expected_param_hash=None) -> dict:
    """All checks, with details for the results JSON. `accepted` is True only if every check passes."""
    reasons = []
    if not verified:
        reasons.append("proof did not verify")
    pretty = proof.get("pretty_public_inputs") or {}
    if not pretty:
        reasons.append("proof.json has no pretty_public_inputs")
    try:
        inputs = [float(v) for v in _flat(pretty.get("rescaled_inputs") or [])]
        outputs = [float(v) for v in _flat(pretty.get("rescaled_outputs") or [])]
    except (TypeError, ValueError):
        inputs, outputs = [], []
        reasons.append("pretty_public_inputs are malformed")
    hashes = [str(h) for h in _flat(pretty.get("processed_params") or [])]

    score = outputs[0] if len(outputs) == 1 else None
    if score is None:
        reasons.append(f"expected exactly one public output (the score), found {len(outputs)}")
    elif score != expected_score:
        reasons.append(f"public score is {score:g}, expected {expected_score} (every signature bit must agree)")

    expected = [float(x) for x in expected_input]
    tol = input_tolerance(settings)
    max_diff = None
    if len(inputs) != len(expected):
        reasons.append(f"public input has {len(inputs)} values; the suspect model's watermark vector has {len(expected)}")
    else:
        max_diff = max((abs(a - b) for a, b in zip(inputs, expected)), default=0.0)
        if max_diff > tol:
            reasons.append(f"public input is not the suspect model's watermark vector "
                           f"(max |difference| {max_diff:.3g} > tolerance {tol:.3g})")

    if expected_param_hash is not None:
        if len(hashes) != 1:
            reasons.append(f"expected one public Poseidon commitment to the private params, found {len(hashes)}")
        elif _felt_be(hashes[0]) != _felt_be(str(expected_param_hash)):
            reasons.append("Poseidon commitment to the private params != the published commitment")

    mismatch = _instance_mismatch(proof, settings, hashes, inputs, outputs)
    if mismatch:
        reasons.append(mismatch)

    return {"accepted": not reasons, "reasons": reasons, "verified": bool(verified),
            "score": score, "expected_score": expected_score,
            "input_matches_suspect_model": max_diff is not None and max_diff <= tol,
            "max_input_diff": max_diff, "input_tolerance": tol,
            "param_hash": hashes[0] if hashes else None, "expected_param_hash": expected_param_hash}


def check_public_signals(proof: dict, settings: dict, expected_input, verified: bool,
                         expected_score: int = EXPECTED_SCORE, expected_param_hash=None):
    """(accepted, reasons). Reasons are empty when the proof is accepted."""
    r = public_signal_report(proof, settings, expected_input, verified, expected_score, expected_param_hash)
    return r["accepted"], r["reasons"]
