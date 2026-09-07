"""Consensus aggregation and judge-reliability statistics for the IMCR.

Implements GOAL.md sections 7.4 (consensus rules) and 7.5 (agreement
statistics):

* 3 judges: 3/3 -> strong_consensus, 2/3 -> weak_consensus, else unresolved.
* 5 judges: >=4/5 -> strong_consensus, 3/5 -> weak_consensus, else
  unresolved.
* ``unresolved`` never fabricates a pseudo gold label by majority vote:
  the aggregated label is ``None``.
* Pairwise agreement, Fleiss' kappa, Krippendorff's alpha (nominal),
  Cohen's kappa (when applicable), and leave-one-judge-out stability.
* CSV writers for JUDGE_PAIRWISE_AGREEMENT.csv,
  JUDGE_RELIABILITY_SUMMARY.csv and LEAVE_ONE_JUDGE_OUT.csv.

Pure standard library + math; no third-party dependency.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from typing import Any, Hashable, Mapping, Sequence

__all__ = [
    "STRONG_CONSENSUS",
    "WEAK_CONSENSUS",
    "UNRESOLVED",
    "ConsensusResult",
    "consensus_label",
    "aggregate_all",
    "pairwise_agreement",
    "fleiss_kappa",
    "krippendorff_alpha_nominal",
    "cohens_kappa",
    "leave_one_judge_out",
    "reduced_panel_labels",
    "reliability_summary",
    "write_pairwise_agreement_csv",
    "write_reliability_summary_csv",
    "write_leave_one_judge_out_csv",
]

STRONG_CONSENSUS = "strong_consensus"
WEAK_CONSENSUS = "weak_consensus"
UNRESOLVED = "unresolved"

#: Vote values that never count as a judge decision (invalid/missing output).
INVALID_VOTES: frozenset[Any] = frozenset({None, "", "MODEL_OUTPUT_INVALID"})

Label = Hashable
Votes = Sequence[Label | None]


@dataclass(frozen=True)
class ConsensusResult:
    """Aggregated outcome for one task."""

    label: Label | None  # None when unresolved — never a forced majority
    tier: str  # strong_consensus | weak_consensus | unresolved
    n_valid_votes: int
    winning_votes: int
    vote_distribution: dict[Label, int]


def _valid_votes(votes: Votes) -> list[Label]:
    return [v for v in votes if v not in INVALID_VOTES]


def consensus_label(votes: Votes, n_models: int | None = None) -> ConsensusResult:
    """Apply the GOAL 7.4 consensus rule to one task's judge votes.

    ``votes`` holds one entry per judge; invalid entries (``None`` or
    ``MODEL_OUTPUT_INVALID``) are dropped before counting.  ``n_models``
    defaults to ``len(votes)`` and must be 3 or 5.
    """
    if n_models is None:
        n_models = len(votes)
    if n_models not in (3, 5):
        raise ValueError("consensus rules are defined for 3 or 5 judges")

    valid = _valid_votes(votes)
    distribution: dict[Label, int] = {}
    for v in valid:
        distribution[v] = distribution.get(v, 0) + 1
    winning = max(distribution.values(), default=0)
    winner = (
        max(distribution.items(), key=lambda kv: (kv[1], str(kv[0])))[0]
        if distribution
        else None
    )

    if n_models == 3:
        if winning >= 3:
            tier, label = STRONG_CONSENSUS, winner
        elif winning == 2:
            tier, label = WEAK_CONSENSUS, winner
        else:
            tier, label = UNRESOLVED, None
    else:  # n_models == 5
        if winning >= 4:
            tier, label = STRONG_CONSENSUS, winner
        elif winning == 3:
            tier, label = WEAK_CONSENSUS, winner
        else:
            tier, label = UNRESOLVED, None

    return ConsensusResult(
        label=label,
        tier=tier,
        n_valid_votes=len(valid),
        winning_votes=winning,
        vote_distribution=distribution,
    )


def aggregate_all(
    matrix: Sequence[Votes],
    judges: Sequence[str] | None = None,
) -> list[ConsensusResult]:
    """Aggregate a full ``tasks x judges`` decision matrix."""
    if not matrix:
        return []
    n_models = len(matrix[0])
    if any(len(row) != n_models for row in matrix):
        raise ValueError("all rows must have the same number of judge votes")
    return [consensus_label(row, n_models) for row in matrix]


# ---------------------------------------------------------------------------
# Agreement statistics (GOAL 7.5)
# ---------------------------------------------------------------------------


def pairwise_agreement(
    matrix: Sequence[Votes], judges: Sequence[str]
) -> list[dict[str, Any]]:
    """Observed agreement for every judge pair over co-valid tasks."""
    rows: list[dict[str, Any]] = []
    n = len(judges)
    for i in range(n):
        for j in range(i + 1, n):
            compared = agree = 0
            for row in matrix:
                a, b = row[i], row[j]
                if a in INVALID_VOTES or b in INVALID_VOTES:
                    continue
                compared += 1
                agree += int(a == b)
            rows.append(
                {
                    "judge_a": judges[i],
                    "judge_b": judges[j],
                    "n_compared": compared,
                    "n_agree": agree,
                    "agreement": (agree / compared) if compared else math.nan,
                }
            )
    return rows


def fleiss_kappa(matrix: Sequence[Votes]) -> float:
    """Fleiss' kappa (generalised to per-subject valid-rater counts).

    Subjects with fewer than two valid votes are excluded.  Returns
    ``math.nan`` when the statistic is undefined.
    """
    subjects: list[dict[Label, int]] = []
    for row in matrix:
        counts: dict[Label, int] = {}
        for v in row:
            if v in INVALID_VOTES:
                continue
            counts[v] = counts.get(v, 0) + 1
        if sum(counts.values()) >= 2:
            subjects.append(counts)
    if not subjects:
        return math.nan

    categories = sorted({c for s in subjects for c in s}, key=str)
    n_subjects = len(subjects)
    p_i: list[float] = []
    totals = {c: 0 for c in categories}
    total_assignments = 0
    for counts in subjects:
        n_i = sum(counts.values())
        sq = sum(v * v for v in counts.values())
        p_i.append((sq - n_i) / (n_i * (n_i - 1)))
        for c in categories:
            totals[c] += counts.get(c, 0)
        total_assignments += n_i
    p_bar = sum(p_i) / n_subjects
    p_e = sum((totals[c] / total_assignments) ** 2 for c in categories)
    if p_e >= 1.0:
        return math.nan  # perfect trivial agreement; kappa undefined
    return (p_bar - p_e) / (1.0 - p_e)


def krippendorff_alpha_nominal(matrix: Sequence[Votes]) -> float:
    """Krippendorff's alpha for nominal data with missing values.

    Uses the coincidence-matrix formulation: each unit with ``n_u`` valid
    votes contributes each ordered pair of votes with weight
    ``1 / (n_u - 1)``.  Returns ``math.nan`` when undefined.
    """
    coincidence: dict[tuple[Label, Label], float] = {}
    for row in matrix:
        valid = _valid_votes(row)
        n_u = len(valid)
        if n_u < 2:
            continue
        weight = 1.0 / (n_u - 1)
        # ordered pairs of DISTINCT positions (i != j); self-pairs excluded
        for i, a in enumerate(valid):
            for j, b in enumerate(valid):
                if i == j:
                    continue
                key = (a, b)
                coincidence[key] = coincidence.get(key, 0.0) + weight
    if not coincidence:
        return math.nan

    marginals: dict[Label, float] = {}
    for (a, _b), val in coincidence.items():
        marginals[a] = marginals.get(a, 0.0) + val
    n = sum(marginals.values())
    if n <= 1:
        return math.nan

    d_o = sum(val for (a, b), val in coincidence.items() if a != b) / n
    d_e = 0.0
    for c, n_c in marginals.items():
        for k, n_k in marginals.items():
            if c != k:
                d_e += n_c * n_k
    d_e /= n * (n - 1)
    if d_e == 0.0:
        return math.nan
    return 1.0 - d_o / d_e


def cohens_kappa(labels_a: Sequence[Label], labels_b: Sequence[Label]) -> float:
    """Cohen's kappa between two raters (complete paired data)."""
    if len(labels_a) != len(labels_b):
        raise ValueError("label sequences must have equal length")
    n = len(labels_a)
    if n == 0:
        return math.nan
    categories = sorted(set(labels_a) | set(labels_b), key=str)
    p_o = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / n
    p_e = 0.0
    for c in categories:
        pa = sum(1 for a in labels_a if a == c) / n
        pb = sum(1 for b in labels_b if b == c) / n
        p_e += pa * pb
    if p_e >= 1.0:
        return math.nan
    return (p_o - p_e) / (1.0 - p_e)


# ---------------------------------------------------------------------------
# Leave-one-judge-out stability (GOAL 7.5)
# ---------------------------------------------------------------------------


def reduced_panel_labels(
    matrix: Sequence[Votes], judges: Sequence[str], judge_to_remove: str
) -> list[ConsensusResult]:
    """Re-aggregate a decision matrix with one judge removed.

    Applies the GOAL 7.4 reduced-panel rules: 3 or 5 remaining judges use
    ``consensus_label``; a reduced 2-judge panel uses 2/2 agree ->
    weak_consensus, else unresolved (no strong tier is possible with two
    judges).  Raises ``ValueError`` for unsupported panel shapes or when
    ``judge_to_remove`` is absent.
    """
    if judge_to_remove not in judges:
        raise ValueError(f"judge {judge_to_remove!r} not in panel {list(judges)}")
    drop = judges.index(judge_to_remove)
    reduced_matrix = [[v for k, v in enumerate(row) if k != drop] for row in matrix]
    reduced_n = len(judges) - 1
    if reduced_n in (3, 5):
        return [consensus_label(r, reduced_n) for r in reduced_matrix]
    if reduced_n == 2:
        results: list[ConsensusResult] = []
        for r in reduced_matrix:
            valid = _valid_votes(r)
            if len(valid) == 2 and valid[0] == valid[1]:
                results.append(ConsensusResult(valid[0], WEAK_CONSENSUS, 2, 2, {valid[0]: 2}))
            else:
                results.append(ConsensusResult(None, UNRESOLVED, len(valid), 0, {}))
        return results
    raise ValueError("unsupported reduced panel size")  # pragma: no cover - defensive


def leave_one_judge_out(
    matrix: Sequence[Votes], judges: Sequence[str]
) -> list[dict[str, Any]]:
    """Re-form consensus after removing each judge in turn.

    Stability for judge ``j`` is the fraction of tasks whose full-panel
    consensus label is reproduced by the panel without ``j``.  Removal of a
    judge reduces the panel size; the GOAL 7.4 rule for the *reduced* panel
    size (3 or 5) is applied.  For a 3-judge panel the reduced 2-judge panel
    uses the rule: 2/2 agree -> weak_consensus, else unresolved (no
    strong tier is possible with two judges).
    """
    full = aggregate_all(matrix, judges)
    rows: list[dict[str, Any]] = []
    for drop in range(len(judges)):
        reduced = reduced_panel_labels(matrix, judges, judges[drop])

        labeled = unchanged = 0
        for f, r in zip(full, reduced):
            if f.label is None:
                continue
            labeled += 1
            unchanged += int(r.label == f.label)
        rows.append(
            {
                "judge_removed": judges[drop],
                "n_tasks": len(matrix),
                "n_labeled_full_panel": labeled,
                "n_unchanged_after_removal": unchanged,
                "stability": (unchanged / labeled) if labeled else math.nan,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Reliability summary + CSV writers
# ---------------------------------------------------------------------------


def reliability_summary(
    matrix: Sequence[Votes], judges: Sequence[str]
) -> dict[str, Any]:
    """One-shot reliability summary over a full decision matrix."""
    results = aggregate_all(matrix, judges)
    n = len(results)
    tiers = {
        STRONG_CONSENSUS: sum(1 for r in results if r.tier == STRONG_CONSENSUS),
        WEAK_CONSENSUS: sum(1 for r in results if r.tier == WEAK_CONSENSUS),
        UNRESOLVED: sum(1 for r in results if r.tier == UNRESOLVED),
    }
    pair_rows = pairwise_agreement(matrix, judges)
    agreements = [r["agreement"] for r in pair_rows if not math.isnan(r["agreement"])]
    loo = leave_one_judge_out(matrix, judges)
    stabilities = [r["stability"] for r in loo if not math.isnan(r["stability"])]
    return {
        "n_tasks": n,
        "n_judges": len(judges),
        "judges": list(judges),
        "n_strong_consensus": tiers[STRONG_CONSENSUS],
        "n_weak_consensus": tiers[WEAK_CONSENSUS],
        "n_unresolved": tiers[UNRESOLVED],
        "mean_pairwise_agreement": (
            sum(agreements) / len(agreements) if agreements else math.nan
        ),
        "fleiss_kappa": fleiss_kappa(matrix),
        "krippendorff_alpha_nominal": krippendorff_alpha_nominal(matrix),
        "min_leave_one_judge_out_stability": (
            min(stabilities) if stabilities else math.nan
        ),
        "mean_leave_one_judge_out_stability": (
            sum(stabilities) / len(stabilities) if stabilities else math.nan
        ),
    }


def _write_csv(path: str, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> str:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({f: row.get(f, "") for f in fields})
    return path


def write_pairwise_agreement_csv(
    matrix: Sequence[Votes], judges: Sequence[str], path: str
) -> str:
    """Write JUDGE_PAIRWISE_AGREEMENT.csv (GOAL 7.5)."""
    rows = pairwise_agreement(matrix, judges)
    return _write_csv(
        path, rows, ["judge_a", "judge_b", "n_compared", "n_agree", "agreement"]
    )


def write_reliability_summary_csv(
    matrix: Sequence[Votes], judges: Sequence[str], path: str
) -> str:
    """Write JUDGE_RELIABILITY_SUMMARY.csv (GOAL 7.5)."""
    summary = reliability_summary(matrix, judges)
    rows = [
        {"metric": k, "value": v}
        for k, v in summary.items()
        if k != "judges"
    ]
    rows.append({"metric": "judges", "value": ";".join(summary["judges"])})
    return _write_csv(path, rows, ["metric", "value"])


def write_leave_one_judge_out_csv(
    matrix: Sequence[Votes], judges: Sequence[str], path: str
) -> str:
    """Write LEAVE_ONE_JUDGE_OUT.csv (GOAL 7.5)."""
    rows = leave_one_judge_out(matrix, judges)
    return _write_csv(
        path,
        rows,
        [
            "judge_removed",
            "n_tasks",
            "n_labeled_full_panel",
            "n_unchanged_after_removal",
            "stability",
        ],
    )
