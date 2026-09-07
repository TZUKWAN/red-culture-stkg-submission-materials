"""GOAL 13 / 18: selective-prediction metrics and statistical inference.

Curve metrics are checked against hand-computed trapezoid areas; Wilson CI
against literature values; bootstrap against seeded reproducibility;
McNemar against a known contingency table.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from metrics import (
    augrc,
    aurc,
    bootstrap_ci,
    coverage,
    error_exposure,
    generalized_risk,
    macro_f1_on_accepted,
    macro_f1_on_full_denominator,
    mcnemar_test,
    paired_bootstrap_diff_ci,
    risk_coverage_curve,
    safe_coverage,
    save_bootstrap_replicates,
    selective_accuracy,
    selective_risk,
    selective_summary,
    wilson_ci,
)

# ---------------------------------------------------------------------------
# Hand-constructed risk-coverage curves with known areas
# ---------------------------------------------------------------------------

#: 4 items; descending-score acceptance; the single error is ranked LAST.
SCORES_BEST = [0.9, 0.8, 0.7, 0.6]
CORRECT_BEST = [1, 1, 1, 0]

#: Same items but the error is ranked FIRST (worst ordering).
CORRECT_WORST = [0, 1, 1, 1]


def test_curve_shape_and_origin():
    points = risk_coverage_curve(SCORES_BEST, CORRECT_BEST)
    assert points[0].coverage == 0.0 and points[0].selective_risk == 0.0
    assert [round(p.coverage, 4) for p in points] == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert [round(p.selective_risk, 4) for p in points] == [0.0, 0.0, 0.0, 0.0, 0.25]
    assert [round(p.generalized_risk, 4) for p in points] == [0.0, 0.0, 0.0, 0.0, 0.25]


def test_aurc_known_value_best_ordering():
    # Trapezoid over (0,0) (.25,0) (.5,0) (.75,0) (1,.25): area = .25*.25/2
    points = risk_coverage_curve(SCORES_BEST, CORRECT_BEST)
    assert aurc(points) == pytest.approx(0.03125, abs=1e-12)
    assert aurc(points, normalize=True) == pytest.approx(0.03125, abs=1e-12)
    # generalized risk equals selective risk * coverage here -> same shape
    assert augrc(points) == pytest.approx(0.03125, abs=1e-12)


def test_aurc_known_value_worst_ordering():
    # risks: (0,0) (.25,1) (.5,.5) (.75,1/3) (1,.25)
    # area = .125 + .1875 + .25*(5/12) + .25*(7/24) = 47/96
    points = risk_coverage_curve(SCORES_BEST, CORRECT_WORST)
    assert aurc(points) == pytest.approx(47 / 96, abs=1e-12)
    # generalized risk is constant 0.25 after coverage .25:
    # area = .25*(.25)/2 + .25*.75 = 0.03125 + 0.1875 = 0.21875
    assert augrc(points) == pytest.approx(0.21875, abs=1e-12)


def test_aurc_zero_for_perfect_curve():
    points = risk_coverage_curve(SCORES_BEST, [1, 1, 1, 1])
    assert aurc(points) == 0.0
    assert augrc(points) == 0.0


def test_curve_ties_accepted_together():
    # Two items share score 0.5 -> single non-origin point at coverage 1.
    points = risk_coverage_curve([0.5, 0.5], [1, 0])
    assert len(points) == 2
    assert points[-1].coverage == 1.0
    assert points[-1].errors == 1
    assert aurc(points) == pytest.approx(0.25, abs=1e-12)


def test_empty_curve_rejected():
    with pytest.raises(ValueError):
        risk_coverage_curve([], [])
    with pytest.raises(ValueError):
        aurc([])


# ---------------------------------------------------------------------------
# Scalar selective metrics
# ---------------------------------------------------------------------------


def test_scalar_metrics_hand_values():
    accepted = [1, 1, 1, 0]  # item 4 abstained
    correct = [1, 1, 0, 0]   # item 3 accepted but wrong; item 4 wrong too
    assert coverage(accepted, correct) == pytest.approx(0.75)
    assert selective_risk(accepted, correct) == pytest.approx(1 / 3)
    assert selective_accuracy(accepted, correct) == pytest.approx(2 / 3)
    assert generalized_risk(accepted, correct) == pytest.approx(0.25)
    assert safe_coverage(accepted, correct) == pytest.approx(0.5)
    # 1 of the 2 total errors leaked into accepted output
    assert error_exposure(accepted, correct) == pytest.approx(0.5)


def test_selective_risk_nan_when_nothing_accepted():
    assert math.isnan(selective_risk([0, 0], [1, 0]))
    assert math.isnan(selective_accuracy([0, 0], [1, 0]))
    assert math.isnan(error_exposure([1, 1], [1, 1]))  # zero errors total


def test_macro_f1_accepted_vs_full_denominator():
    y_true = ["P", "P", "E", "E"]
    y_pred = ["P", None, "E", "O"]  # one abstention, one wrong
    # accepted only (3 items): P -> F1 1; E -> tp=1, fn=1 (item 4 wrong)
    # -> F1 2/3; macro = (1 + 2/3) / 2 = 5/6
    assert macro_f1_on_accepted(y_true, y_pred) == pytest.approx(5 / 6, abs=1e-12)
    # full denominator: P recall 1/2 (abstention counts as FN) -> F1 = 2/3;
    # E recall 1/2 -> F1 = 2/3; macro = 2/3 < accepted-only figure
    full = macro_f1_on_full_denominator(y_true, y_pred)
    assert full == pytest.approx((2 / 3 + 2 / 3) / 2, abs=1e-12)


def test_selective_summary_bundle():
    s = selective_summary(
        SCORES_BEST,
        CORRECT_BEST,
        threshold=0.65,
        y_true=["A", "A", "B", "B"],
        y_pred=["A", "A", "B", "B"],
    )
    assert s["n"] == 4
    assert s["coverage"] == pytest.approx(0.75)
    assert s["selective_risk"] == 0.0
    assert s["aurc"] == pytest.approx(0.03125, abs=1e-12)
    assert s["macro_f1_on_accepted"] == pytest.approx(1.0)
    assert "macro_f1_on_full_denominator" in s


# ---------------------------------------------------------------------------
# Wilson CI against literature values
# ---------------------------------------------------------------------------


def test_wilson_ci_literature_values():
    # Wilson score interval for 25/100 (R prop.test without continuity
    # correction / statsmodels method='wilson'): (0.175452, 0.343045)
    low, high = wilson_ci(25, 100)
    assert low == pytest.approx(0.17545211362287674, abs=1e-9)
    assert high == pytest.approx(0.34304463548061603, abs=1e-9)


def test_wilson_ci_edge_cases():
    low, high = wilson_ci(0, 10)
    assert low == 0.0 and high == pytest.approx(0.2775327998628892, abs=1e-9)
    low, high = wilson_ci(10, 10)
    assert low == pytest.approx(0.7224672001371107, abs=1e-9)
    assert high == pytest.approx(1.0, abs=1e-12)
    with pytest.raises(ValueError):
        wilson_ci(5, 0)
    with pytest.raises(ValueError):
        wilson_ci(11, 10)


def test_wilson_ci_narrower_than_normal_approx_and_contains_p():
    low, high = wilson_ci(50, 100)
    assert low < 0.5 < high
    assert (high - low) < 0.2  # normal-approx width would be ~0.196


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_seed_reproducibility():
    data = list(range(20))
    stat = lambda a: float(np.mean(a))
    r1 = bootstrap_ci(data, stat, n_replicates=500, seed=20260401)
    r2 = bootstrap_ci(data, stat, n_replicates=500, seed=20260401)
    assert r1.replicates == r2.replicates
    assert r1.ci_low == r2.ci_low and r1.ci_high == r2.ci_high
    r3 = bootstrap_ci(data, stat, n_replicates=500, seed=99)
    assert r3.replicates != r1.replicates


def test_bootstrap_all_replicates_saved(tmp_path):
    data = [1, 0, 1, 1, 0, 1, 1, 1, 0, 1]
    r = bootstrap_ci(data, lambda a: float(np.mean(a)), n_replicates=200, seed=7)
    assert len(r.replicates) == 200
    assert r.ci_low <= r.estimate <= r.ci_high
    out = tmp_path / "replicates.json"
    save_bootstrap_replicates(r, str(out))
    import json

    saved = json.loads(out.read_text(encoding="utf-8"))
    assert len(saved["replicates"]) == 200
    assert saved["seed"] == 7


def test_bootstrap_ci_contains_true_mean():
    rng = np.random.default_rng(0)
    data = rng.normal(5.0, 1.0, 200).tolist()
    r = bootstrap_ci(data, lambda a: float(np.mean(a)), n_replicates=1000, seed=1)
    assert r.ci_low < 5.0 < r.ci_high


def test_paired_bootstrap_diff_ci():
    rng = np.random.default_rng(3)
    n = 200
    a = (rng.random(n) > 0.15).astype(int)  # ~85% correct
    b = (rng.random(n) > 0.50).astype(int)  # ~50% correct
    stat = lambda x: float(np.mean(x))
    r = paired_bootstrap_diff_ci(a, b, stat, n_replicates=1000, seed=11)
    assert r.estimate == pytest.approx(float(a.mean() - b.mean()))
    assert r.ci_low > 0  # clearly better system -> CI excludes 0
    r_same = paired_bootstrap_diff_ci(a, b, stat, n_replicates=1000, seed=11)
    assert r_same.replicates == r.replicates
    with pytest.raises(ValueError):
        paired_bootstrap_diff_ci([1, 2], [1], stat)


# ---------------------------------------------------------------------------
# McNemar against a known contingency table
# ---------------------------------------------------------------------------


def test_mcnemar_known_table_exact():
    # b = 25, c = 5: exact binomial p = 2 * P(X <= 5; n=30, p=.5)
    res = mcnemar_test(25, 5, exact=True)
    assert res["method"] == "exact_binomial"
    assert res["n_discordant"] == 30
    assert res["p_value"] == pytest.approx(0.0003249142318964005, rel=1e-9)


def test_mcnemar_known_table_chi2():
    # continuity-corrected chi2 = (|25-5|-1)^2 / 30 = 361/30 = 12.0333...
    res = mcnemar_test(25, 5, exact=False)
    assert res["statistic"] == pytest.approx(361 / 30, abs=1e-12)
    assert res["p_value"] == pytest.approx(0.0005225753951242464, rel=1e-9)


def test_mcnemar_no_discordance_rejected():
    with pytest.raises(ValueError):
        mcnemar_test(0, 0)


def test_mcnemar_symmetric_nonsignificant():
    res = mcnemar_test(10, 10, exact=True)
    assert res["p_value"] == pytest.approx(1.0)
