"""Poseidon in Python must equal circomlibjs (and therefore circomlib's circuit) bit for bit (CR-05)."""
import json
from pathlib import Path

import pytest

from sigil.field import P
from sigil.poseidon import poseidon

VECTORS = json.loads((Path(__file__).parent / "vectors" / "poseidon_circomlibjs.json").read_text())["vectors"]


@pytest.mark.parametrize("v", VECTORS, ids=lambda v: f"n{len(v['inputs'])}")
def test_matches_circomlibjs(v):
    assert poseidon([int(x) for x in v["inputs"]]) == int(v["output"])


def test_all_arities_covered():
    assert {len(v["inputs"]) for v in VECTORS} == set(range(1, 17))


@pytest.mark.parametrize("bad", [[], [0] * 17, [P], [-1]])
def test_rejects_bad_inputs(bad):
    with pytest.raises(ValueError):
        poseidon(bad)
