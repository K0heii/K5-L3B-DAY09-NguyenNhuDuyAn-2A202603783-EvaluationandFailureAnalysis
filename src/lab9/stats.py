"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class
_VALID_LABELS = frozenset({"PASS", "FAIL"})


def _normalize_labels(human: Sequence[str], judge: Sequence[str]) -> tuple[list[str], list[str]]:
    if len(human) != len(judge):
        raise ValueError(f"human and judge length mismatch: {len(human)} != {len(judge)}")
    norm_h = [str(x).strip().upper() for x in human]
    norm_j = [str(x).strip().upper() for x in judge]
    bad = (set(norm_h) | set(norm_j)) - _VALID_LABELS
    if bad:
        raise ValueError(f"expected binary PASS/FAIL labels, got {sorted(bad)}")
    return norm_h, norm_j


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    norm_h, norm_j = _normalize_labels(human, judge)
    tp = fp = fn = tn = 0
    for h, j in zip(norm_h, norm_j):
        if h == POS and j == POS:
            tp += 1
        elif h != POS and j == POS:
            fp += 1
        elif h == POS and j != POS:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    # precision = tp/(tp+fp), recall = tp/(tp+fn); return 0.0 when the denominator is 0
    cm = confusion(human, judge)
    p = cm["tp"] / (cm["tp"] + cm["fp"]) if (cm["tp"] + cm["fp"]) else 0.0
    r = cm["tp"] / (cm["tp"] + cm["fn"]) if (cm["tp"] + cm["fn"]) else 0.0
    return p, r


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    cm = confusion(human, judge)
    n = cm["tp"] + cm["fp"] + cm["fn"] + cm["tn"]
    if n == 0:
        raise ValueError("cannot compute Cohen's kappa on empty sequences")
    p_o = (cm["tp"] + cm["tn"]) / n
    p_e = (
        (cm["tp"] + cm["fn"]) * (cm["tp"] + cm["fp"])
        + (cm["tn"] + cm["fp"]) * (cm["tn"] + cm["fn"])
    ) / (n * n)
    denom = 1.0 - p_e
    if abs(denom) <= 1e-12:
        raise ValueError("Cohen's kappa is undefined when p_e == 1")
    return (p_o - p_e) / denom


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1]."""
    denom = sensitivity + specificity - 1.0
    if abs(denom) <= 1e-12:
        raise ValueError("Rogan-Gladen is undefined when sensitivity + specificity == 1")
    raw = (observed_rate + specificity - 1.0) / denom
    return min(1.0, max(0.0, raw))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    import numpy as np
    from scipy.stats import bootstrap

    if len(a) != len(b):
        raise ValueError(f"paired sequences must have equal length: {len(a)} != {len(b)}")
    if not a:
        raise ValueError("cannot bootstrap empty sequences")
    arr_a = np.asarray(a, dtype=float)
    arr_b = np.asarray(b, dtype=float)
    if np.array_equal(arr_a, arr_b):
        return (0.0, 0.0, 0.0)
    diff = float(np.mean(arr_a - arr_b))
    res = bootstrap(
        (arr_a, arr_b),
        lambda x, y, axis=-1: np.mean(x - y, axis=axis),
        n_resamples=n_resamples,
        paired=True,
        method="percentile",
        confidence_level=confidence,
        rng=np.random.default_rng(rng),
    )
    return (diff, float(res.confidence_interval.low), float(res.confidence_interval.high))


def _validate_nck(n: int, c: int, k: int) -> None:
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (n, c, k)):
        raise ValueError(f"n, c, k must be integers, got {(n, c, k)!r}")
    if n <= 0 or k <= 0 or k > n or c < 0 or c > n:
        raise ValueError(f"invalid (n, c, k)=({n}, {c}, {k}): require 0 <= c <= n and 1 <= k <= n")


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    _validate_nck(n, c, k)
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    _validate_nck(n, c, k)
    if c < k:
        return 0.0
    return math.comb(c, k) / math.comb(n, k)
