"""D2 work-factor maths (FIX-01): single_core_hours must be HOURS, not seconds."""
import json
import math
from pathlib import Path

import pytest

from d2_math import binom_tail_le, d2_work_estimate

P_64_8 = 2.7813e-10        # P[Bin(64, 0.5) <= 8]


def test_binomial_tail_for_the_demo_threshold():
    p = binom_tail_le(64, 8)
    assert p == pytest.approx(P_64_8, rel=1e-4)
    assert binom_tail_le(64, 64) == pytest.approx(1.0)
    assert binom_tail_le(4, 0) == pytest.approx(1 / 16)


def test_work_estimate_is_in_hours():
    p = binom_tail_le(64, 8)
    tries, seconds = 20000, 2.132
    est = d2_work_estimate(p, tries, seconds)
    rate = tries / seconds
    tries_needed = math.log(2) / p
    assert est["log2_work"] == pytest.approx(31.74, abs=0.01)
    assert est["seeds_per_s"] == pytest.approx(rate)
    assert est["seeds_for_half"] == pytest.approx(tries_needed)
    assert est["single_core_hours"] == pytest.approx(tries_needed / rate / 3600)
    assert est["single_core_seconds"] == pytest.approx(est["single_core_hours"] * 3600)


def test_saved_run_is_about_71_core_hours():
    """FIX-01 acceptance: the saved D2 run (9,381 seeds/s) costs ~71 single-core hours, not ~257,000."""
    d2 = json.loads((Path(__file__).resolve().parents[1] / "demo" / "results" / "committed_seed.json")
                    .read_text(encoding="utf-8"))["d2"]
    est = d2_work_estimate(d2["p_per_try"], d2["tries"], d2["seconds"])
    assert est["single_core_hours"] == pytest.approx(71, abs=2)
    assert est["seeds_for_half"] == pytest.approx(d2["seeds_for_half"])


@pytest.mark.parametrize("args", [(0, 1, 1), (1, 1, 1), (0.1, 0, 1), (0.1, 1, 0)])
def test_rejects_nonsense(args):
    with pytest.raises(ValueError):
        d2_work_estimate(*args)
