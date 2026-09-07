"""GOAL 7.4 / 7.5: consensus aggregation and judge-reliability statistics."""

from __future__ import annotations

import math

import pytest

from consensus import (
    STRONG_CONSENSUS,
    UNRESOLVED,
    WEAK_CONSENSUS,
    aggregate_all,
    cohens_kappa,
    consensus_label,
    fleiss_kappa,
    krippendorff_alpha_nominal,
    leave_one_judge_out,
    pairwise_agreement,
    reliability_summary,
    write_leave_one_judge_out_csv,
    write_pairwise_agreement_csv,
    write_reliability_summary_csv,
)

J3 = ["A", "B", "C"]
J5 = ["A", "B", "C", "D", "E"]


# ---------------------------------------------------------------------------
# Consensus tiers — 3-judge panel
# ---------------------------------------------------------------------------


def test_three_judge_strong_consensus():
    r = consensus_label(["X", "X", "X"], 3)
    assert r.tier == STRONG_CONSENSUS and r.label == "X" and r.winning_votes == 3


def test_three_judge_weak_consensus():
    r = consensus_label(["X", "X", "Y"], 3)
    assert r.tier == WEAK_CONSENSUS and r.label == "X" and r.winning_votes == 2


def test_three_judge_full_split_unresolved():
    r = consensus_label(["X", "Y", "Z"], 3)
    assert r.tier == UNRESOLVED
    # GOAL 7.4: unresolved must NOT fabricate a pseudo gold label
    assert r.label is None


def test_three_judge_invalid_votes_do_not_count():
    r = consensus_label(["X", "X", "MODEL_OUTPUT_INVALID"], 3)
    assert r.tier == WEAK_CONSENSUS and r.label == "X" and r.n_valid_votes == 2
    r2 = consensus_label(["X", None, "MODEL_OUTPUT_INVALID"], 3)
    assert r2.tier == UNRESOLVED and r2.label is None


# ---------------------------------------------------------------------------
# Consensus tiers — 5-judge panel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "votes,tier,label",
    [
        (["X"] * 5, STRONG_CONSENSUS, "X"),
        (["X"] * 4 + ["Y"], STRONG_CONSENSUS, "X"),
        (["X"] * 3 + ["Y", "Y"], WEAK_CONSENSUS, "X"),
        (["X"] * 3 + ["Y", "Z"], WEAK_CONSENSUS, "X"),
        (["X", "X", "Y", "Y", "Z"], UNRESOLVED, None),
        (["X", "X", "Y", "Y", None], UNRESOLVED, None),
        (["X"] * 3 + ["Y", "MODEL_OUTPUT_INVALID"], WEAK_CONSENSUS, "X"),
    ],
)
def test_five_judge_tiers(votes, tier, label):
    r = consensus_label(votes, 5)
    assert r.tier == tier
    assert r.label == label
    if tier == UNRESOLVED:
        assert r.label is None  # never a forced majority pseudo-label


def test_unsupported_panel_size_rejected():
    with pytest.raises(ValueError):
        consensus_label(["X", "X"], 2)
    with pytest.raises(ValueError):
        consensus_label(["X"] * 4, 4)


def test_aggregate_all_matrix_shape_check():
    with pytest.raises(ValueError):
        aggregate_all([["X", "X", "X"], ["X", "X"]])


# ---------------------------------------------------------------------------
# Reliability statistics against hand-computed values
# ---------------------------------------------------------------------------

#: 3 raters x 4 subjects; hand-computed Fleiss kappa = 1/3.
FLEISS_MATRIX = [
    ["A", "A", "A"],
    ["B", "B", "B"],
    ["A", "A", "B"],
    ["A", "B", "B"],
]


def test_fleiss_kappa_hand_value():
    # subjects P_i = 1, 1, 1/3, 1/3 -> P_bar = 2/3; marginals 6/12, 6/12
    # -> P_e = 0.5; kappa = (2/3 - 1/2) / (1/2) = 1/3
    assert fleiss_kappa(FLEISS_MATRIX) == pytest.approx(1 / 3, abs=1e-12)


def test_fleiss_kappa_perfect_and_undefined():
    perfect = [["A", "A", "A"], ["B", "B", "B"]]
    # P_bar = 1, P_e = 0.5 -> kappa = 1
    assert fleiss_kappa(perfect) == pytest.approx(1.0)
    single_category = [["A", "A", "A"], ["A", "A", "A"]]
    assert math.isnan(fleiss_kappa(single_category))  # P_e == 1 -> undefined
    mixed = [["A", "B", "C"]] * 2  # raters never agree
    v = fleiss_kappa(mixed)
    assert v <= 0.0


def test_krippendorff_alpha_hand_value():
    # Coincidence matrix o = [[4,1],[1,2]], n = 8:
    # D_o = 2/8 = 0.25; D_e = (5*3 + 3*5)/(8*7) = 30/56
    # alpha = 1 - 0.25 / (30/56) = 0.5333...
    matrix = [[0, 0], [0, 0], [1, 1], [0, 1]]
    alpha = krippendorff_alpha_nominal(matrix)
    assert alpha == pytest.approx(8 / 15, abs=1e-9)  # 0.5333...


def test_krippendorff_alpha_perfect_agreement():
    matrix = [["A", "A", "A"], ["B", "B", "B"], ["A", "A", "A"]]
    assert krippendorff_alpha_nominal(matrix) == pytest.approx(1.0)


def test_krippendorff_alpha_handles_missing_votes():
    matrix = [["A", "A", None], ["B", "B", "MODEL_OUTPUT_INVALID"], ["A", "A", "A"]]
    alpha = krippendorff_alpha_nominal(matrix)
    assert alpha == pytest.approx(1.0)


def test_cohens_kappa_hand_value():
    # po = 3/4; marginals a=(0.5,0.5), b=(0.25,0.75) -> pe = 0.5
    # kappa = (0.75 - 0.5) / 0.5 = 0.5
    a = [0, 0, 1, 1]
    b = [0, 1, 1, 1]
    assert cohens_kappa(a, b) == pytest.approx(0.5)
    assert cohens_kappa([1, 1, 0], [1, 1, 0]) == pytest.approx(1.0)


def test_pairwise_agreement_counts():
    matrix = [
        ["X", "X", "Y"],
        ["X", "Y", None],       # None excluded from every pair
        ["Z", "Z", "Z"],
    ]
    rows = pairwise_agreement(matrix, J3)
    by_pair = {(r["judge_a"], r["judge_b"]): r for r in rows}
    ab = by_pair[("A", "B")]
    assert ab["n_compared"] == 3 and ab["n_agree"] == 2
    assert ab["agreement"] == pytest.approx(2 / 3)
    ac = by_pair[("A", "C")]
    assert ac["n_compared"] == 2 and ac["n_agree"] == 1
    assert ac["agreement"] == pytest.approx(0.5)


def test_leave_one_judge_out_stability():
    matrix = [
        ["X", "X", "X"],  # strong; removing any judge keeps X (2-judge weak)
        ["X", "X", "Y"],  # weak X; removing C keeps X, removing A/B -> split
        ["X", "Y", "Z"],  # unresolved; not counted in stability denominator
    ]
    rows = leave_one_judge_out(matrix, J3)
    by_judge = {r["judge_removed"]: r for r in rows}
    # Full panel labeled 2 tasks (X, X). Removing C: reduced pairs
    # (X,X) and (X,X) -> both reproduce. Removing A: (X,X) and (X,Y)
    # -> only task 1 reproduces.
    assert by_judge["C"]["n_labeled_full_panel"] == 2
    assert by_judge["C"]["stability"] == pytest.approx(1.0)
    assert by_judge["A"]["stability"] == pytest.approx(0.5)


def test_reliability_summary_fields():
    matrix = [["X", "X", "X"], ["X", "X", "Y"], ["X", "Y", "Z"]]
    s = reliability_summary(matrix, J3)
    assert s["n_tasks"] == 3 and s["n_judges"] == 3
    assert s["n_strong_consensus"] == 1
    assert s["n_weak_consensus"] == 1
    assert s["n_unresolved"] == 1
    assert -1.0 <= s["fleiss_kappa"] <= 1.0
    assert -1.0 <= s["krippendorff_alpha_nominal"] <= 1.0


# ---------------------------------------------------------------------------
# CSV writers (GOAL 7.5 outputs)
# ---------------------------------------------------------------------------


def test_csv_writers(tmp_path):
    matrix = [
        ["X", "X", "X"],
        ["X", "X", "Y"],
        ["X", "Y", "Z"],
        ["Y", "Y", "Y"],
    ]
    p1 = tmp_path / "JUDGE_PAIRWISE_AGREEMENT.csv"
    p2 = tmp_path / "JUDGE_RELIABILITY_SUMMARY.csv"
    p3 = tmp_path / "LEAVE_ONE_JUDGE_OUT.csv"
    write_pairwise_agreement_csv(matrix, J3, str(p1))
    write_reliability_summary_csv(matrix, J3, str(p2))
    write_leave_one_judge_out_csv(matrix, J3, str(p3))
    text1 = p1.read_text(encoding="utf-8")
    assert "judge_a,judge_b,n_compared,n_agree,agreement" in text1.splitlines()[0]
    assert len(text1.splitlines()) == 4  # header + 3 pairs
    text2 = p2.read_text(encoding="utf-8")
    assert "fleiss_kappa" in text2 and "krippendorff_alpha_nominal" in text2
    text3 = p3.read_text(encoding="utf-8")
    assert "judge_removed" in text3.splitlines()[0]
    assert len(text3.splitlines()) == 4  # header + 3 judges


def test_csv_writers_five_judges(tmp_path):
    matrix = [
        ["X", "X", "X", "X", "Y"],
        ["X", "X", "X", "Y", "Y"],
        ["X", "X", "Y", "Y", "Z"],
    ]
    p = tmp_path / "JUDGE_PAIRWISE_AGREEMENT.csv"
    write_pairwise_agreement_csv(matrix, J5, str(p))
    assert len(p.read_text(encoding="utf-8").splitlines()) == 11  # C(5,2)=10 pairs
