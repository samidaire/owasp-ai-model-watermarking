"""Interim FIX-02: a ZK proof is accepted only if its PUBLIC signals are right, not merely valid.
Uses the saved EZKL runs in demo/results/ezkl_*/ (proof.json, settings.json, input.json)."""
import copy
import json
from pathlib import Path

import pytest

from zk_checks import BN254_P, check_public_signals, input_tolerance, public_signal_report

RESULTS = Path(__file__).resolve().parents[1] / "demo" / "results"


def load(run):
    d = RESULTS / f"ezkl_{run}"
    read = lambda name: json.loads((d / name).read_text(encoding="utf-8"))  # noqa: E731
    return read("proof.json"), read("settings.json"), read("input.json")["input_data"][0]


def owner_hash():
    return load("hashed_owner")[0]["pretty_public_inputs"]["processed_params"][0][0]


def test_tolerance_comes_from_settings():
    _, settings, _ = load("private_owner")
    assert settings["run_args"]["input_scale"] == 13
    assert input_tolerance(settings) == 2 ** -13 * 2


def test_owner_proof_with_its_own_input_is_accepted():
    proof, settings, w = load("private_owner")
    accepted, reasons = check_public_signals(proof, settings, w, verified=True)
    assert accepted and reasons == []
    r = public_signal_report(proof, settings, w, verified=True)
    assert r["score"] == 64 and r["input_matches_suspect_model"] and r["max_input_diff"] <= r["input_tolerance"]


def test_unverified_proof_is_rejected():
    proof, settings, w = load("private_owner")
    accepted, reasons = check_public_signals(proof, settings, w, verified=False)
    assert not accepted and reasons == ["proof did not verify"]


def test_small_quantisation_noise_is_tolerated():
    proof, settings, w = load("private_owner")
    tol = input_tolerance(settings)
    nudged = [x + 0.4 * tol for x in w]
    assert check_public_signals(proof, settings, nudged, verified=True)[0]


@pytest.mark.parametrize("change", ["one_value", "all_values", "other_model", "shorter"])
def test_proof_made_on_a_different_model_is_rejected(change):
    proof, settings, w = load("private_owner")
    tol = input_tolerance(settings)
    other = {"one_value": [w[0] + 3 * tol] + w[1:], "all_values": [x + 3 * tol for x in w],
             "other_model": [-x for x in w], "shorter": w[:-1]}[change]
    accepted, reasons = check_public_signals(proof, settings, other, verified=True)
    assert not accepted
    assert len(reasons) == 1 and "suspect model's watermark vector" in reasons[0]


def test_score_edited_to_zero_is_rejected():
    proof, settings, w = load("private_owner")
    forged = copy.deepcopy(proof)
    forged["pretty_public_inputs"]["rescaled_outputs"] = [["0"]]
    accepted, reasons = check_public_signals(forged, settings, w, verified=True)
    assert not accepted
    assert any("public score is 0, expected 64" in r for r in reasons)
    assert any("do not match the values the proof verifies" in r for r in reasons)   # pretty != instances


def test_score_zero_in_the_verified_instances_is_rejected():
    """Even a consistent proof (instances and pretty fields agree) is rejected when its score is 0."""
    proof, settings, w = load("private_owner")
    forged = copy.deepcopy(proof)
    forged["pretty_public_inputs"]["rescaled_outputs"] = [["0"]]
    forged["pretty_public_inputs"]["outputs"] = [["0x" + "0" * 64]]
    forged["instances"][0][-1] = (0).to_bytes(32, "little").hex()
    accepted, reasons = check_public_signals(forged, settings, w, verified=True)
    assert not accepted and reasons == ["public score is 0, expected 64 (every signature bit must agree)"]


def test_edited_public_input_is_caught_by_the_instance_cross_check():
    """Rewriting the readable input to the suspect's w does not help: the proof verifies other values."""
    proof, settings, w = load("private_owner")
    forged = copy.deepcopy(proof)
    shifted = [x + 1.0 for x in w]
    forged["instances"][0][:288] = [((round(x * 2 ** 13)) % BN254_P).to_bytes(32, "little").hex() for x in shifted]
    accepted, reasons = check_public_signals(forged, settings, w, verified=True)
    assert not accepted and any("do not match the values the proof verifies" in r for r in reasons)


def test_e2_public_checks_cannot_tell_owner_and_thief_apart():
    """Without a commitment the thief's proof is about the same model and also scores 64."""
    proof, settings, w = load("private_thief")
    assert check_public_signals(proof, settings, w, verified=True) == (True, [])


def test_e3_owner_accepted_thief_rejected_by_commitment():
    proof, settings, w = load("hashed_owner")
    assert check_public_signals(proof, settings, w, verified=True, expected_param_hash=owner_hash()) == (True, [])
    proof, settings, w = load("hashed_thief")
    accepted, reasons = check_public_signals(proof, settings, w, verified=True, expected_param_hash=owner_hash())
    assert not accepted and reasons == ["Poseidon commitment to the private params != the published commitment"]


def test_missing_public_values_are_rejected():
    _, settings, w = load("private_owner")
    accepted, reasons = check_public_signals({}, settings, w, verified=True)
    assert not accepted and any("no pretty_public_inputs" in r for r in reasons)
