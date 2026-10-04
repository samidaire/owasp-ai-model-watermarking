"""Work-factor maths for demo D2 (the thief's seed search). Pure Python: no torch, no numpy,
so it can be unit-tested anywhere (tests/test_d2_math.py)."""
import math


def binom_tail_le(n: int, k: int, p: float = 0.5) -> float:
    """P[Bin(n, p) <= k]: chance that one random seed passes at threshold k/n."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def d2_work_estimate(p_per_try: float, tries: int, seconds: float) -> dict:
    """Cost of a seed search that succeeds with probability p_per_try per seed, at the rate
    measured in the demo (tries seeds in `seconds` on one core).

    seeds_for_half      ~ ln 2 / p: seeds needed for a ~50% chance of one forgery
    single_core_seconds = seeds_for_half / rate
    single_core_hours   = single_core_seconds / 3600   (HOURS; FIX-01: this used to hold seconds)
    """
    if not 0 < p_per_try < 1:
        raise ValueError("p_per_try must be in (0, 1)")
    if tries <= 0 or seconds <= 0:
        raise ValueError("tries and seconds must be positive")
    rate = tries / seconds
    seeds_for_half = math.log(2) / p_per_try
    single_core_seconds = seeds_for_half / rate
    return {
        "seeds_per_s": rate,
        "log2_work": math.log2(1 / p_per_try),
        "seeds_for_half": seeds_for_half,
        "single_core_seconds": single_core_seconds,
        "single_core_hours": single_core_seconds / 3600,
    }
