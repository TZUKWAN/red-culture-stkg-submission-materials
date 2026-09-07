"""Selective-prediction metrics and statistical inference for the IMCR
evaluation.

Implements GOAL.md section 13 (selective-prediction metric set) and
section 18 (statistical analysis requirements):

Point metrics
    coverage, selective accuracy, selective risk, generalized risk,
    safe coverage, error exposure, macro-F1 on accepted, macro-F1 on the
    full denominator, AURC, normalized AURC, AUGRC, normalized AUGRC.

Inference
    Wilson score CI, fixed-seed percentile bootstrap CI (all replicates
    returned/savable), paired bootstrap difference CI, and McNemar's test
    (exact binomial and chi-square with continuity correction, via scipy
    for the tail probabilities).

Definitions follow the existing ``run_selective_inference.py`` pipeline so
the IMCR evaluation is directly comparable with the production numbers:
coverage uses the *full frozen task set* as denominator; selective risk is
errors over accepted; generalized risk is errors over total; safe coverage
is accepted-and-correct over total.

Dependencies: standard library + numpy + scipy (McNemar tails only).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Callable, Hashable, Sequence

import numpy as np
from scipy.stats import binom, chi2 as chi2_dist

__all__ = [
    "RiskCoveragePoint",
    "risk_coverage_curve",
    "aurc",
    "augrc",
    "coverage",
    "selective_accuracy",
    "selective_risk",
    "generalized_risk",
    "safe_coverage",
    "error_exposure",
    "macro_f1_on_accepted",
    "macro_f1_on_full_denominator",
    "selective_summary",
    "wilson_ci",
    "bootstrap_ci",
    "paired_bootstrap_diff_ci",
    "mcnemar_test",
    "save_bootstrap_replicates",
]

# ---------------------------------------------------------------------------
# Risk-coverage curve
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskCoveragePoint:
    threshold: float
    coverage: float
    accepted: int
    errors: int
    selective_risk: float
    generalized_risk: float
    safe_coverage: float


def _accepted_mask(scores: Sequence[float], threshold: float) -> np.ndarray:
    return np.asarray(scores, dtype=float) >= threshold


def risk_coverage_curve(
    scores: Sequence[float],
    correct: Sequence[int | bool],
) -> list[RiskCoveragePoint]:
    """Exact risk-coverage curve: accept all items with score >= threshold.

    Thresholds sweep the distinct score values (descending); the origin
    point ``(coverage=0, risk=0)`` is prepended so that trapezoid
    integration over ``[0, max_coverage]`` is well defined.  Ties are
    accepted together (``accept_all_equal_scores`` policy, matching the
    production pipeline).
    """
    scores_arr = np.asarray(scores, dtype=float)
    correct_arr = np.asarray([int(c) for c in correct], dtype=int)
    if scores_arr.shape[0] != correct_arr.shape[0]:
        raise ValueError("scores and correct must have equal length")
    total = int(scores_arr.shape[0])
    if total == 0:
        raise ValueError("empty evaluation set")

    points: list[RiskCoveragePoint] = [
        RiskCoveragePoint(
            threshold=math.inf,
            coverage=0.0,
            accepted=0,
            errors=0,
            selective_risk=0.0,
            generalized_risk=0.0,
            safe_coverage=0.0,
        )
    ]
    for threshold in sorted(set(scores_arr.tolist()), reverse=True):
        mask = _accepted_mask(scores_arr, threshold)
        accepted = int(mask.sum())
        errors = int((correct_arr[mask] == 0).sum())
        safe = accepted - errors
        points.append(
            RiskCoveragePoint(
                threshold=float(threshold),
                coverage=accepted / total,
                accepted=accepted,
                errors=errors,
                selective_risk=(errors / accepted) if accepted else 0.0,
                generalized_risk=errors / total,
                safe_coverage=safe / total,
            )
        )
    return points


def _trapezoid(xs: Sequence[float], ys: Sequence[float]) -> float:
    return float(np.trapezoid(np.asarray(ys, dtype=float), np.asarray(xs, dtype=float)))


def aurc(points: Sequence[RiskCoveragePoint], normalize: bool = False) -> float:
    """Area under the risk-coverage curve (trapezoid over coverage).

    With ``normalize=True`` the area is divided by the maximum coverage
    reached (``aurc_normalized_by_max_coverage`` in the production
    pipeline), making curves with different score availability comparable.
    """
    if not points:
        raise ValueError("curve is empty")
    cov = [p.coverage for p in points]
    risk = [p.selective_risk for p in points]
    if any(c2 < c1 for c1, c2 in zip(cov, cov[1:])):
        raise ValueError("points must be sorted by non-decreasing coverage")
    area = _trapezoid(cov, risk)
    if normalize:
        max_cov = max(cov)
        if max_cov <= 0:
            raise ValueError("cannot normalize: max coverage is zero")
        area /= max_cov
    return area


def augrc(points: Sequence[RiskCoveragePoint], normalize: bool = False) -> float:
    """Area under the *generalized* risk-coverage curve (trapezoid)."""
    if not points:
        raise ValueError("curve is empty")
    cov = [p.coverage for p in points]
    risk = [p.generalized_risk for p in points]
    if any(c2 < c1 for c1, c2 in zip(cov, cov[1:])):
        raise ValueError("points must be sorted by non-decreasing coverage")
    area = _trapezoid(cov, risk)
    if normalize:
        max_cov = max(cov)
        if max_cov <= 0:
            raise ValueError("cannot normalize: max coverage is zero")
        area /= max_cov
    return area


# ---------------------------------------------------------------------------
# Scalar selective-prediction metrics (one acceptance decision per item)
# ---------------------------------------------------------------------------


def _check_aligned(accepted: Sequence[Any], correct: Sequence[Any]) -> tuple[np.ndarray, np.ndarray]:
    acc = np.asarray([int(a) for a in accepted], dtype=int)
    cor = np.asarray([int(c) for c in correct], dtype=int)
    if acc.shape != cor.shape:
        raise ValueError("accepted and correct must have equal length")
    if acc.size == 0:
        raise ValueError("empty evaluation set")
    return acc, cor


def coverage(accepted: Sequence[int | bool], correct: Sequence[int | bool]) -> float:
    """Accepted / total (full frozen task set denominator)."""
    acc, _ = _check_aligned(accepted, correct)
    return float(acc.sum() / acc.size)


def selective_risk(accepted: Sequence[int | bool], correct: Sequence[int | bool]) -> float:
    """Errors among accepted / accepted.  NaN when nothing was accepted."""
    acc, cor = _check_aligned(accepted, correct)
    n_acc = int(acc.sum())
    if n_acc == 0:
        return math.nan
    return float(((acc == 1) & (cor == 0)).sum() / n_acc)


def selective_accuracy(accepted: Sequence[int | bool], correct: Sequence[int | bool]) -> float:
    """1 - selective_risk (NaN when nothing was accepted)."""
    risk = selective_risk(accepted, correct)
    return math.nan if math.isnan(risk) else 1.0 - risk


def generalized_risk(accepted: Sequence[int | bool], correct: Sequence[int | bool]) -> float:
    """Errors among accepted / total (abstention carries no risk)."""
    acc, cor = _check_aligned(accepted, correct)
    return float(((acc == 1) & (cor == 0)).sum() / acc.size)


def safe_coverage(accepted: Sequence[int | bool], correct: Sequence[int | bool]) -> float:
    """Accepted-and-correct / total."""
    acc, cor = _check_aligned(accepted, correct)
    return float(((acc == 1) & (cor == 1)).sum() / acc.size)


def error_exposure(accepted: Sequence[int | bool], correct: Sequence[int | bool]) -> float:
    """Fraction of *all* errors that leak through into accepted output.

    ``errors_accepted / errors_total``.  Requires correctness labels for
    the full denominator (available for IMCR-labeled evaluation sets).
    Returns NaN when the system makes no errors at all.
    """
    acc, cor = _check_aligned(accepted, correct)
    errors_total = int((cor == 0).sum())
    if errors_total == 0:
        return math.nan
    errors_accepted = int(((acc == 1) & (cor == 0)).sum())
    return errors_accepted / errors_total


# ---------------------------------------------------------------------------
# Macro-F1
# ---------------------------------------------------------------------------


def _per_class_f1(
    y_true: Sequence[Hashable],
    y_pred: Sequence[Hashable | None],
) -> dict[Hashable, dict[str, float]]:
    """Per-class precision/recall/F1; ``None`` prediction = abstained."""
    classes = sorted(set(y_true), key=str)
    out: dict[Hashable, dict[str, float]] = {}
    for c in classes:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == c and p == c)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != c and p == c)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == c and p != c)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )
        out[c] = {"precision": precision, "recall": recall, "f1": f1}
    return out


def macro_f1_on_accepted(
    y_true: Sequence[Hashable],
    y_pred: Sequence[Hashable | None],
) -> float:
    """Macro-F1 computed over accepted items only (pred is not None)."""
    pairs = [(t, p) for t, p in zip(y_true, y_pred) if p is not None]
    if not pairs:
        return math.nan
    per_class = _per_class_f1([t for t, _ in pairs], [p for _, p in pairs])
    return float(np.mean([v["f1"] for v in per_class.values()]))


def macro_f1_on_full_denominator(
    y_true: Sequence[Hashable],
    y_pred: Sequence[Hashable | None],
) -> float:
    """Macro-F1 over the full evaluation set; abstentions count as
    non-predictions (they inflate FN of the true class)."""
    if not y_true:
        return math.nan
    per_class = _per_class_f1(y_true, y_pred)
    return float(np.mean([v["f1"] for v in per_class.values()]))


def selective_summary(
    scores: Sequence[float],
    correct: Sequence[int | bool],
    threshold: float,
    y_true: Sequence[Hashable] | None = None,
    y_pred: Sequence[Hashable | None] | None = None,
) -> dict[str, Any]:
    """Point metrics at one operating threshold plus curve areas."""
    scores_arr = np.asarray(scores, dtype=float)
    accepted = (scores_arr >= threshold).astype(int)
    points = risk_coverage_curve(scores, correct)
    summary: dict[str, Any] = {
        "n": len(correct),
        "threshold": threshold,
        "coverage": coverage(accepted, correct),
        "selective_accuracy": selective_accuracy(accepted, correct),
        "selective_risk": selective_risk(accepted, correct),
        "generalized_risk": generalized_risk(accepted, correct),
        "safe_coverage": safe_coverage(accepted, correct),
        "error_exposure": error_exposure(accepted, correct),
        "aurc": aurc(points),
        "aurc_normalized": aurc(points, normalize=True),
        "augrc": augrc(points),
        "augrc_normalized": augrc(points, normalize=True),
    }
    if y_true is not None and y_pred is not None:
        gated_pred: list[Hashable | None] = [
            p if a else None for a, p in zip(accepted, y_pred)
        ]
        summary["macro_f1_on_accepted"] = macro_f1_on_accepted(y_true, gated_pred)
        summary["macro_f1_on_full_denominator"] = macro_f1_on_full_denominator(
            y_true, gated_pred
        )
    return summary


# ---------------------------------------------------------------------------
# Confidence intervals and tests (GOAL 18)
# ---------------------------------------------------------------------------


def wilson_ci(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    ``k`` successes out of ``n`` trials; returns ``(low, high)``.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= k <= n:
        raise ValueError("k must satisfy 0 <= k <= n")
    from scipy.stats import norm

    z = float(norm.ppf(1 - (1 - confidence) / 2))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(frozen=True)
class BootstrapResult:
    estimate: float
    ci_low: float
    ci_high: float
    n_replicates: int
    seed: int
    replicates: tuple[float, ...]  # GOAL 13.2: every replicate is kept

    def to_dict(self, include_replicates: bool = True) -> dict[str, Any]:
        out = {
            "estimate": self.estimate,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "n_replicates": self.n_replicates,
            "seed": self.seed,
        }
        if include_replicates:
            out["replicates"] = list(self.replicates)
        return out


def bootstrap_ci(
    data: Sequence[Any],
    statistic: Callable[[np.ndarray], float],
    n_replicates: int = 2000,
    seed: int = 42,
    confidence: float = 0.95,
) -> BootstrapResult:
    """Percentile bootstrap CI with a fixed seed.

    Every replicate statistic is retained in the result (GOAL 13.2
    requires saving each replicate, not only the summary).
    """
    arr = np.asarray(data)
    if arr.shape[0] == 0:
        raise ValueError("empty data")
    rng = np.random.default_rng(seed)
    reps = np.empty(n_replicates, dtype=float)
    for i in range(n_replicates):
        sample = arr[rng.integers(0, arr.shape[0], arr.shape[0])]
        reps[i] = statistic(sample)
    alpha = 1 - confidence
    low, high = np.percentile(reps, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return BootstrapResult(
        estimate=float(statistic(arr)),
        ci_low=float(low),
        ci_high=float(high),
        n_replicates=n_replicates,
        seed=seed,
        replicates=tuple(float(x) for x in reps),
    )


def paired_bootstrap_diff_ci(
    data_a: Sequence[Any],
    data_b: Sequence[Any],
    statistic: Callable[[np.ndarray], float],
    n_replicates: int = 2000,
    seed: int = 42,
    confidence: float = 0.95,
) -> BootstrapResult:
    """Paired bootstrap CI for ``statistic(a) - statistic(b)``.

    The same resample indices are applied to both aligned datasets in
    every replicate (paired system comparison, GOAL 18).
    """
    arr_a, arr_b = np.asarray(data_a), np.asarray(data_b)
    if arr_a.shape[0] != arr_b.shape[0] or arr_a.shape[0] == 0:
        raise ValueError("paired data must be non-empty and equally sized")
    rng = np.random.default_rng(seed)
    n = arr_a.shape[0]
    reps = np.empty(n_replicates, dtype=float)
    for i in range(n_replicates):
        idx = rng.integers(0, n, n)
        reps[i] = statistic(arr_a[idx]) - statistic(arr_b[idx])
    alpha = 1 - confidence
    low, high = np.percentile(reps, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return BootstrapResult(
        estimate=float(statistic(arr_a) - statistic(arr_b)),
        ci_low=float(low),
        ci_high=float(high),
        n_replicates=n_replicates,
        seed=seed,
        replicates=tuple(float(x) for x in reps),
    )


def mcnemar_test(b: int, c: int, exact: bool = True) -> dict[str, float | int | str]:
    """McNemar's test on discordant pairs of a paired binary comparison.

    ``b`` = items where system A is correct and system B is wrong;
    ``c`` = items where system B is correct and system A is wrong.

    ``exact=True`` uses the exact binomial test (recommended for small
    b + c); otherwise the chi-square statistic with continuity
    correction is reported.  Tail probabilities come from scipy.
    """
    if b < 0 or c < 0:
        raise ValueError("discordant counts must be non-negative")
    n = b + c
    if n == 0:
        raise ValueError("no discordant pairs; McNemar is undefined")
    if exact:
        k = min(b, c)
        p_value = float(min(1.0, 2.0 * binom.cdf(k, n, 0.5)))
        return {
            "method": "exact_binomial",
            "b": b,
            "c": c,
            "n_discordant": n,
            "statistic": float(k),
            "p_value": p_value,
        }
    statistic = (abs(b - c) - 1) ** 2 / n
    return {
        "method": "chi2_continuity_corrected",
        "b": b,
        "c": c,
        "n_discordant": n,
        "statistic": float(statistic),
        "p_value": float(chi2_dist.sf(statistic, df=1)),
    }


def save_bootstrap_replicates(result: BootstrapResult, path: str) -> str:
    """Persist every bootstrap replicate (GOAL 13.2: no summary-only saves)."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result.to_dict(include_replicates=True), fh, indent=2)
    return path
