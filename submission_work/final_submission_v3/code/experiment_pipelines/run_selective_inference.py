#!/usr/bin/env python3
"""Compute tie-aware selective-inference curves from per-sample baseline runs.

v3 port of ``final_submission_v2/code/experiment_pipelines/run_selective_inference.py``
(GOAL.md section 13, Phase 7).  The v2 computation is preserved verbatim; the
only behavioural extension is the ``--reference`` switch:

* ``--reference era`` (default): reproduce the v2 run exactly.  Correctness
  flags recorded in ``BASELINE_RUNS.csv`` (computed against the ERA integrated
  reference annotation) are used unchanged.  With the copied inputs this mode
  is bit-for-bit comparable with
  ``final_submission_v2/experiments/03_selective_inference/``.
* ``--reference imcr_strong``: re-evaluate correctness against the independent
  multi-model consensus reference
  ``experiments/08_independent_reference/IMCR_REFERENCE_STRONG.csv``
  (strong-consensus rows only), produced by the Phase-2 blind judge pipeline.
* ``--reference imcr_all``: same, against ``IMCR_REFERENCE_ALL.csv``
  (strong + weak consensus rows).

IMCR semantics (no silent ERA fallback):

* The reference CSV must exist; a missing file raises ``FileNotFoundError``
  with an explicit message.  There is no fallback to ERA.
* Required reference columns: ``sample_id``, ``task_type``,
  ``reference_label`` (non-empty).  An optional ``consensus_tier`` column is
  validated when present (``imcr_strong`` accepts only ``strong_consensus``;
  ``imcr_all`` accepts ``strong_consensus`` and ``weak_consensus``).
* Reference rows are joined to baseline runs on ``(sample_id, task_type)``;
  duplicate keys are an error.
* Only reference-covered samples are evaluated: a baseline-run row whose
  ``(sample_id, task_type)`` is absent from the reference is excluded from
  every curve, so the denominator becomes the IMCR-covered subset of the
  frozen task test set (recorded as ``denominator_policy`` /
  ``reference_coverage`` metadata).
* For covered rows, ``correct`` is recomputed as
  ``prediction == reference_label`` (row covered and available), and
  ``safe_correct`` as ``correct AND hard_constraint_pass`` — the same
  derivation the v2 baseline builder used against ERA.

Coverage always uses the full (reference-covered) frozen task test set as
denominator.  A rejected row is routed to review; no LLM call is performed.
AURC and AUGRC are reported only when every test row has a numeric score, the
test set has at least eight rows, and at least four distinct score levels are
available.

GOAL-13 point metrics that v2 did not report (selective accuracy, error
exposure, macro-F1 on accepted, macro-F1 on full denominator) are computed by
reusing ``code/independent_eval/metrics.py`` and written to
``<prefix>SELECTIVE_GOAL13_METRICS.csv``; the same module cross-checks the
AURC/AUGRC values of the primary constrained curves.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import roc_auc_score

SCRIPT = Path(__file__).resolve()
CODE_DIR = SCRIPT.parents[1]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

# GOAL.md section 13 Phase 7: reuse the independently tested metric
# implementations instead of rewriting the mathematical definitions.
from independent_eval import metrics as selective_metrics

V3_ROOT = SCRIPT.parents[2]
EXTERNAL_INPUTS_DIR = V3_ROOT / "data" / "external_inputs"
REFERENCE_DIR = V3_ROOT / "experiments" / "08_independent_reference"
DEFAULT_OUTDIR = V3_ROOT / "experiments" / "13_selective_inference_independent"

DEFAULT_RUNS_PATH = EXTERNAL_INPUTS_DIR / "BASELINE_RUNS.csv"
DEFAULT_BASELINE_AUDIT_PATH = EXTERNAL_INPUTS_DIR / "baseline_experiment_audit.json"
DEFAULT_GOLD_PATH = EXTERNAL_INPUTS_DIR / "AI_GOLD_LABELS.csv"
DEFAULT_IMCR_STRONG_PATH = REFERENCE_DIR / "IMCR_REFERENCE_STRONG.csv"
DEFAULT_IMCR_ALL_PATH = REFERENCE_DIR / "IMCR_REFERENCE_ALL.csv"

REFERENCE_MODES = ("era", "imcr_strong", "imcr_all")
IMCR_REQUIRED_COLUMNS = ("sample_id", "task_type", "reference_label")
IMCR_STRONG_TIERS = {"strong_consensus"}
IMCR_ALL_TIERS = {"strong_consensus", "weak_consensus"}

SCORE_METHODS = {
    "M1_rule_only",
    "M2_classifier_only",
    "M4_rule_plus_cached_llm",
    "M6_full_v2_replay",
}
FIXED_THRESHOLDS = sorted(
    {round(value / 20, 2) for value in range(21)} | {0.80, 0.85, 0.90, 0.95, 0.98, 0.99},
    reverse=True,
)
MIN_AREA_N = 8
MIN_UNIQUE_SCORES = 4
BOOTSTRAP_SEED = 20260730
BOOTSTRAP_ITERATIONS = 2000
OWNER_PROXY_TASKS = {"time_owner", "space_owner"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    # utf-8-sig：兼容 IMCR 参考文件（build_imcr_consensus 以 utf-8-sig 落盘，
    # 首列名会带 BOM，plain utf-8 读取会误报缺列）。
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def numeric_confidence(row: dict[str, str]) -> float | None:
    raw = str(row.get("confidence") or "").strip()
    if not raw:
        return None
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"non-finite confidence for {row['sample_id']} {row['method_id']}")
    return value


# ---------------------------------------------------------------------------
# IMCR reference loading (GOAL.md Phase 7 --reference modes)
# ---------------------------------------------------------------------------


def load_imcr_reference(path: Path, mode: str) -> dict[tuple[str, str], str]:
    """Load an IMCR reference CSV into a ``(sample_id, task_type) -> label`` map.

    Raises a clear error when the file is missing or malformed; there is no
    silent fallback to ERA.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"--reference {mode} requires the IMCR reference file '{path}', "
            "which does not exist. This file is generated by the Phase-2 blind "
            "judge pipeline (experiments/08_independent_reference/). Run that "
            "pipeline first; no fallback to ERA is performed."
        )
    rows = read_csv(path)
    if not rows:
        raise ValueError(f"IMCR reference file '{path}' is empty")
    missing = [c for c in IMCR_REQUIRED_COLUMNS if c not in rows[0]]
    if missing:
        raise ValueError(
            f"IMCR reference file '{path}' is missing required columns {missing}; "
            f"expected at least {list(IMCR_REQUIRED_COLUMNS)}"
        )
    allowed_tiers = IMCR_STRONG_TIERS if mode == "imcr_strong" else IMCR_ALL_TIERS
    has_tier = "consensus_tier" in rows[0]
    reference: dict[tuple[str, str], str] = {}
    for row in rows:
        label = str(row.get("reference_label") or "").strip()
        if not label:
            raise ValueError(
                f"IMCR reference file '{path}' has an empty reference_label for "
                f"sample_id={row.get('sample_id')!r} task_type={row.get('task_type')!r}; "
                "unresolved items must be omitted, not emitted with an empty label"
            )
        if has_tier:
            tier = str(row.get("consensus_tier") or "").strip()
            if tier and tier not in allowed_tiers:
                raise ValueError(
                    f"--reference {mode} does not accept consensus_tier={tier!r} "
                    f"(allowed: {sorted(allowed_tiers)}) in '{path}'"
                )
        key = (row["sample_id"], row["task_type"])
        if key in reference:
            raise ValueError(
                f"IMCR reference file '{path}' has duplicate key {key}; "
                "exactly one reference label per (sample_id, task_type) is required"
            )
        reference[key] = label
    return reference


def apply_imcr_reference(
    runs: list[dict[str, str]], reference: dict[tuple[str, str], str], mode: str
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Restrict runs to reference-covered samples and recompute correctness.

    Returns the filtered rows (copies; input rows are not mutated) plus
    coverage metadata.  ``correct`` / ``safe_correct`` follow the same
    derivation the v2 baseline builder applied against ERA:
    ``correct = covered AND prediction == reference_label`` and
    ``safe_correct = correct AND hard_constraint_pass``.
    """
    covered_keys = {(row["sample_id"], row["task_type"]) for row in runs}
    reference_covered = covered_keys & set(reference)
    if not reference_covered:
        raise ValueError(
            f"--reference {mode}: no baseline-run sample is covered by the IMCR "
            "reference; check that the reference was built on the same frozen "
            "test split"
        )
    output: list[dict[str, str]] = []
    for row in runs:
        key = (row["sample_id"], row["task_type"])
        if key not in reference:
            continue
        new_row = dict(row)
        covered = bool(new_row["prediction"]) and new_row["availability_status"] != "not_available"
        correct = bool(covered) and new_row["prediction"] == reference[key]
        new_row["correct"] = str(int(correct))
        new_row["safe_correct"] = str(int(correct and new_row["hard_constraint_pass"] == "1"))
        output.append(new_row)
    metadata = {
        "reference_row_count": len(reference),
        "baseline_sample_keys": len(covered_keys),
        "reference_covered_sample_keys": len(reference_covered),
        "excluded_sample_keys": len(covered_keys - set(reference)),
        "rows_retained": len(output),
        "rows_excluded": len(runs) - len(output),
    }
    return output, metadata


# ---------------------------------------------------------------------------
# v2 curve machinery (preserved verbatim)
# ---------------------------------------------------------------------------


def curve_point(
    rows: list[dict[str, str]],
    threshold: float,
    point_type: str,
    point_index: int,
    curve_mode: str,
) -> dict[str, Any]:
    total = len(rows)
    accepted = [
        row
        for row in rows
        if row["availability_status"] != "not_available"
        and row["prediction"]
        and (score := numeric_confidence(row)) is not None
        and score >= threshold
        and (curve_mode == "score_only_diagnostic" or row["hard_constraint_pass"] == "1")
    ]
    accepted_count = len(accepted)
    errors = sum(int(row["correct"]) == 0 for row in accepted)
    safe = sum(int(row["safe_correct"]) for row in accepted)
    abstained = total - accepted_count
    prototype = rows[0]
    return {
        "method_id": prototype["method_id"],
        "method_name": prototype["method_name"],
        "task_type": prototype["task_type"],
        "evidence_class": prototype["evidence_class"],
        "comparison_tier": prototype["comparison_tier"],
        "overlap_status": prototype["overlap_status"],
        "evaluation_eligibility": prototype["evaluation_eligibility"],
        "curve_mode": curve_mode,
        "primary_curve": int(curve_mode == "constrained_selective"),
        "acceptance_rule": (
            "score>=threshold AND hard_constraint_pass=1"
            if curve_mode == "constrained_selective"
            else "score>=threshold (diagnostic only; ignores hard gate)"
        ),
        "point_type": point_type,
        "point_index": point_index,
        "threshold": "INF" if math.isinf(threshold) else f"{threshold:.12f}",
        "accepted_count": accepted_count,
        "total_count": total,
        "coverage": accepted_count / total if total else 0.0,
        "error_count": errors,
        "selective_risk": errors / accepted_count if accepted_count else "",
        "generalized_risk": errors / total if total else 0.0,
        "safe_count": safe,
        "safe_coverage": safe / total if total else 0.0,
        "abstained_count": abstained,
        "abstention_rate": abstained / total if total else 0.0,
        "review_escalation_count": abstained,
        "review_escalation_rate": abstained / total if total else 0.0,
        "llm_or_review_escalation_rate": abstained / total if total else 0.0,
        "actual_llm_calls": 0,
        "actual_llm_call_rate": 0.0,
        "score_direction": "higher_is_safer",
        "tie_policy": "accept_all_equal_scores",
        "denominator_policy": "full_frozen_task_test_set",
    }


def exact_curve(rows: list[dict[str, str]], curve_mode: str) -> list[dict[str, Any]]:
    thresholds = sorted(
        {
            score
            for row in rows
            if row["availability_status"] != "not_available"
            and row["prediction"]
            and (score := numeric_confidence(row)) is not None
            and (curve_mode == "score_only_diagnostic" or row["hard_constraint_pass"] == "1")
        },
        reverse=True,
    )
    points = [curve_point(rows, math.inf, "exact_unique", 0, curve_mode)]
    points.extend(
        curve_point(rows, threshold, "exact_unique", index, curve_mode)
        for index, threshold in enumerate(thresholds, start=1)
    )
    return points


def fixed_curve(rows: list[dict[str, str]], curve_mode: str) -> list[dict[str, Any]]:
    return [
        curve_point(rows, threshold, "fixed_grid", index, curve_mode)
        for index, threshold in enumerate(FIXED_THRESHOLDS)
    ]


def trapezoid_area(points: list[dict[str, Any]], field: str) -> float:
    coverage = np.asarray([float(row["coverage"]) for row in points], dtype=float)
    values = np.asarray(
        [0.0 if row[field] == "" else float(row[field]) for row in points], dtype=float
    )
    return float(np.trapezoid(values, coverage))


def failure_auroc(rows: list[dict[str, str]]) -> float | None:
    labels = np.asarray([1 - int(row["correct"]) for row in rows], dtype=int)
    if len(set(labels.tolist())) < 2:
        return None
    scores = np.asarray([-float(row["confidence"]) for row in rows], dtype=float)
    return float(roc_auc_score(labels, scores))


def nearest_risk_at_coverage(points: list[dict[str, Any]], target: float) -> float | None:
    eligible = [row for row in points if row["selective_risk"] != ""]
    if not eligible:
        return None
    chosen = min(eligible, key=lambda row: (abs(float(row["coverage"]) - target), -float(row["coverage"])))
    return float(chosen["selective_risk"])


def max_coverage_at_risk(points: list[dict[str, Any]], risk_limit: float) -> float | None:
    eligible = [
        row
        for row in points
        if row["selective_risk"] != "" and float(row["selective_risk"]) <= risk_limit
    ]
    return max((float(row["coverage"]) for row in eligible), default=None)


def summarize_curve(
    rows: list[dict[str, str]], points: list[dict[str, Any]], curve_mode: str
) -> dict[str, Any]:
    prototype = rows[0]
    prediction_available = [
        row
        for row in rows
        if row["availability_status"] != "not_available"
        and row["prediction"]
    ]
    numeric_scored = [
        row for row in prediction_available
        if numeric_confidence(row) is not None
    ]
    hard_eligible = [row for row in prediction_available if row["hard_constraint_pass"] == "1"]
    curve_scored = (
        [row for row in numeric_scored if row["hard_constraint_pass"] == "1"]
        if curve_mode == "constrained_selective"
        else numeric_scored
    )
    unique_scores = len({float(row["confidence"]) for row in curve_scored})
    total = len(rows)
    complete = (
        len(curve_scored) == len(hard_eligible)
        if curve_mode == "constrained_selective"
        else len(curve_scored) == total
    )
    owner_proxy = prototype["task_type"] in OWNER_PROXY_TASKS
    area_applicable = (
        not owner_proxy
        and bool(curve_scored)
        and complete
        and total >= MIN_AREA_N
        and unique_scores >= MIN_UNIQUE_SCORES
    )
    area_status = (
        "not_applicable_primary_ineligible_owner_proxy"
        if owner_proxy
        else (
            "applicable"
            if area_applicable
            else (
                "not_applicable_no_curve_eligible_predictions"
                if not curve_scored
                else (
                    "not_applicable_incomplete_score_coverage"
                    if not complete
                    else "not_applicable_insufficient_discrete_points"
                )
            )
        )
    )
    aurc = trapezoid_area(points, "selective_risk") if area_applicable else None
    augrc = trapezoid_area(points, "generalized_risk") if area_applicable else None
    accuracy = (
        sum(int(row["correct"]) for row in curve_scored) / len(curve_scored)
        if curve_scored
        else None
    )
    auroc_f = (
        failure_auroc(curve_scored)
        if area_applicable
        and curve_mode == "score_only_diagnostic"
        and len(curve_scored) == total
        else None
    )
    augrc_formula = None
    if (
        area_applicable
        and curve_mode == "score_only_diagnostic"
        and auroc_f is not None
        and accuracy is not None
    ):
        augrc_formula = (1 - auroc_f) * accuracy * (1 - accuracy) + 0.5 * (1 - accuracy) ** 2
    full_point = points[-1]
    max_coverage = float(full_point["coverage"])
    return {
        "method_id": prototype["method_id"],
        "method_name": prototype["method_name"],
        "task_type": prototype["task_type"],
        "evidence_class": prototype["evidence_class"],
        "comparison_tier": prototype["comparison_tier"],
        "overlap_status": prototype["overlap_status"],
        "evaluation_eligibility": prototype["evaluation_eligibility"],
        "curve_mode": curve_mode,
        "primary_curve": int(curve_mode == "constrained_selective"),
        "n_total": total,
        "n_prediction_available": len(prediction_available),
        "n_numeric_scored": len(numeric_scored),
        "n_hard_constraint_eligible": len(hard_eligible),
        "n_scored": len(curve_scored),
        "score_coverage": len(curve_scored) / total if total else 0.0,
        "structural_eligibility_rate": len(hard_eligible) / total if total else 0.0,
        "unique_score_count": unique_scores,
        "max_coverage": max_coverage,
        "target_80pct_coverage_reached": int(max_coverage >= 0.80),
        "full_threshold_selective_risk": (
            None if full_point["selective_risk"] == "" else float(full_point["selective_risk"])
        ),
        "full_threshold_safe_coverage": float(full_point["safe_coverage"]),
        "risk_nearest_80pct_coverage": nearest_risk_at_coverage(points, 0.80),
        "max_coverage_at_risk_le_5pct": max_coverage_at_risk(points, 0.05),
        "area_status": area_status,
        "aurc_trapezoid": aurc,
        "augrc_trapezoid": augrc,
        "aurc_normalized_by_max_coverage": (
            None if aurc is None or max_coverage <= 0 else aurc / max_coverage
        ),
        "augrc_normalized_by_max_coverage": (
            None if augrc is None or max_coverage <= 0 else augrc / max_coverage
        ),
        "failure_detection_auroc": auroc_f,
        "augrc_closed_form_check": augrc_formula,
        "augrc_check_abs_diff": (
            None if augrc is None or augrc_formula is None else abs(augrc - augrc_formula)
        ),
        "bootstrap_seed": None,
        "bootstrap_iterations": 0,
        "aurc_bootstrap_ci95_low": None,
        "aurc_bootstrap_ci95_high": None,
        "augrc_bootstrap_ci95_low": None,
        "augrc_bootstrap_ci95_high": None,
        "integration_rule": (
            "primary: trapezoid over exact tie-grouped constrained coverage points on [0,max_coverage]; acceptance requires score>=threshold AND hard_constraint_pass=1"
            if curve_mode == "constrained_selective"
            else "diagnostic: trapezoid over exact tie-grouped score-only coverage points; ignores hard_constraint_pass"
        ),
        "actual_llm_calls": 0,
    }


def no_score_summary(rows: list[dict[str, str]], curve_mode: str) -> dict[str, Any]:
    prototype = rows[0]
    return {
        "method_id": prototype["method_id"],
        "method_name": prototype["method_name"],
        "task_type": prototype["task_type"],
        "evidence_class": prototype["evidence_class"],
        "comparison_tier": prototype["comparison_tier"],
        "overlap_status": prototype["overlap_status"],
        "evaluation_eligibility": prototype["evaluation_eligibility"],
        "curve_mode": curve_mode,
        "primary_curve": int(curve_mode == "constrained_selective"),
        "n_total": len(rows),
        "n_prediction_available": sum(bool(row["prediction"]) for row in rows),
        "n_numeric_scored": 0,
        "n_hard_constraint_eligible": sum(
            bool(row["prediction"]) and row["hard_constraint_pass"] == "1" for row in rows
        ),
        "n_scored": 0,
        "score_coverage": 0.0,
        "structural_eligibility_rate": (
            sum(bool(row["prediction"]) and row["hard_constraint_pass"] == "1" for row in rows)
            / len(rows)
            if rows
            else 0.0
        ),
        "unique_score_count": 0,
        "max_coverage": 0.0,
        "target_80pct_coverage_reached": 0,
        "full_threshold_selective_risk": None,
        "full_threshold_safe_coverage": 0.0,
        "risk_nearest_80pct_coverage": None,
        "max_coverage_at_risk_le_5pct": None,
        "area_status": (
            "not_applicable_primary_ineligible_owner_proxy"
            if prototype["task_type"] in OWNER_PROXY_TASKS
            else "not_available_no_numeric_confidence"
        ),
        "aurc_trapezoid": None,
        "augrc_trapezoid": None,
        "aurc_normalized_by_max_coverage": None,
        "augrc_normalized_by_max_coverage": None,
        "failure_detection_auroc": None,
        "augrc_closed_form_check": None,
        "augrc_check_abs_diff": None,
        "bootstrap_seed": None,
        "bootstrap_iterations": 0,
        "aurc_bootstrap_ci95_low": None,
        "aurc_bootstrap_ci95_high": None,
        "augrc_bootstrap_ci95_low": None,
        "augrc_bootstrap_ci95_high": None,
        "integration_rule": f"{curve_mode}: not applicable because no numeric confidence; no curve fabricated",
        "actual_llm_calls": 0,
    }


def stable_bootstrap_seed(method_id: str, task_type: str, curve_mode: str) -> int:
    payload = f"{BOOTSTRAP_SEED}|{method_id}|{task_type}|{curve_mode}".encode("utf-8")
    return int(hashlib.sha256(payload).hexdigest()[:8], 16)


def bootstrap_area_rows(
    rows: list[dict[str, str]],
    curve_mode: str,
    iterations: int = BOOTSTRAP_ITERATIONS,
) -> tuple[list[dict[str, Any]], int]:
    prototype = rows[0]
    seed = stable_bootstrap_seed(prototype["method_id"], prototype["task_type"], curve_mode)
    rng = np.random.default_rng(seed)
    output = []
    for index in range(iterations):
        sampled_indices = rng.integers(0, len(rows), size=len(rows))
        sampled = [rows[int(value)] for value in sampled_indices]
        points = exact_curve(sampled, curve_mode)
        output.append(
            {
                "method_id": prototype["method_id"],
                "task_type": prototype["task_type"],
                "curve_mode": curve_mode,
                "replicate_index": index,
                "bootstrap_seed": seed,
                "sample_size": len(rows),
                "aurc_trapezoid": trapezoid_area(points, "selective_risk"),
                "augrc_trapezoid": trapezoid_area(points, "generalized_risk"),
            }
        )
    return output, seed


def percentile_interval(values: list[float], alpha: float = 0.05) -> tuple[float, float]:
    array = np.asarray(values, dtype=float)
    return (
        float(np.quantile(array, alpha / 2, method="linear")),
        float(np.quantile(array, 1 - alpha / 2, method="linear")),
    )


# ---------------------------------------------------------------------------
# GOAL-13 point metrics via code/independent_eval/metrics.py
# ---------------------------------------------------------------------------

GOAL13_FIELDS = [
    "method_id",
    "method_name",
    "task_type",
    "reference_mode",
    "n_total",
    "n_accepted_operating_point",
    "coverage",
    "selective_accuracy",
    "selective_risk",
    "generalized_risk",
    "safe_coverage",
    "error_exposure",
    "macro_f1_on_accepted",
    "macro_f1_on_full_denominator",
    "aurc",
    "aurc_normalized",
    "augrc",
    "augrc_normalized",
]


def goal13_metric_rows(
    groups: dict[tuple[str, str], list[dict[str, str]]],
    reference_mode: str,
    reference: dict[tuple[str, str], str] | None,
) -> list[dict[str, Any]]:
    """GOAL.md section 13 metric set at the max-coverage operating point.

    The acceptance set is the primary constrained one (prediction available,
    numeric score, ``hard_constraint_pass = 1``); all curve-eligible rows are
    accepted at the operating point, so ``coverage`` equals the summary's
    ``max_coverage``.  All quantities are computed with
    ``independent_eval.metrics`` — the mathematical definitions are not
    re-implemented here.  Per-row true labels are the ERA gold in ``era``
    mode and the IMCR reference label otherwise.
    """
    output: list[dict[str, Any]] = []
    for (method_id, task_type), rows in sorted(groups.items()):
        eligible = [
            row
            for row in rows
            if row["availability_status"] != "not_available"
            and row["prediction"]
            and numeric_confidence(row) is not None
            and row["hard_constraint_pass"] == "1"
        ]
        if not eligible:
            continue
        eligible_ids = {id(row) for row in eligible}
        accepted_flags = [int(id(row) in eligible_ids) for row in rows]
        correct_flags = [int(row["correct"]) for row in rows]
        if reference is not None:
            y_true = [reference[(row["sample_id"], row["task_type"])] for row in rows]
        else:
            y_true = [row["gold_label"] for row in rows]
        y_pred = [
            row["prediction"] if flag else None
            for row, flag in zip(rows, accepted_flags)
        ]
        scores = [float(row["confidence"]) for row in eligible]
        correct_eligible = [int(row["correct"]) for row in eligible]
        # metrics.risk_coverage_curve normalises by the length of the passed
        # (curve-eligible) arrays; the production pipeline uses the full
        # frozen task test set as denominator.  Rescale the coverage axis and
        # the total-normalised fields by len(eligible)/len(rows) so the
        # trapezoid areas are directly comparable with the v2 summaries.
        raw_points = selective_metrics.risk_coverage_curve(scores, correct_eligible)
        ratio = len(eligible) / len(rows)
        points = [
            selective_metrics.RiskCoveragePoint(
                threshold=point.threshold,
                coverage=point.coverage * ratio,
                accepted=point.accepted,
                errors=point.errors,
                selective_risk=point.selective_risk,
                generalized_risk=point.generalized_risk * ratio,
                safe_coverage=point.safe_coverage * ratio,
            )
            for point in raw_points
        ]
        max_cov = max(p.coverage for p in points)
        output.append(
            {
                "method_id": method_id,
                "method_name": rows[0]["method_name"],
                "task_type": task_type,
                "reference_mode": reference_mode,
                "n_total": len(rows),
                "n_accepted_operating_point": len(eligible),
                "coverage": selective_metrics.coverage(accepted_flags, correct_flags),
                "selective_accuracy": selective_metrics.selective_accuracy(
                    accepted_flags, correct_flags
                ),
                "selective_risk": selective_metrics.selective_risk(
                    accepted_flags, correct_flags
                ),
                "generalized_risk": selective_metrics.generalized_risk(
                    accepted_flags, correct_flags
                ),
                "safe_coverage": selective_metrics.safe_coverage(
                    accepted_flags, correct_flags
                ),
                "error_exposure": selective_metrics.error_exposure(
                    accepted_flags, correct_flags
                ),
                "macro_f1_on_accepted": selective_metrics.macro_f1_on_accepted(
                    y_true, y_pred
                ),
                "macro_f1_on_full_denominator": selective_metrics.macro_f1_on_full_denominator(
                    y_true, y_pred
                ),
                "aurc": selective_metrics.aurc(points),
                "aurc_normalized": (
                    selective_metrics.aurc(points, normalize=True) if max_cov > 0 else None
                ),
                "augrc": selective_metrics.augrc(points),
                "augrc_normalized": (
                    selective_metrics.augrc(points, normalize=True) if max_cov > 0 else None
                ),
            }
        )
    return output


def goal13_crosscheck_max_diff(
    goal13_rows: list[dict[str, Any]], summaries: list[dict[str, Any]]
) -> float:
    """Largest |metrics.py area - v2 summary area| over applicable curves."""
    by_key = {(row["method_id"], row["task_type"]): row for row in goal13_rows}
    worst = 0.0
    for summary in summaries:
        if summary["curve_mode"] != "constrained_selective":
            continue
        if summary["area_status"] != "applicable":
            continue
        row = by_key.get((summary["method_id"], summary["task_type"]))
        if row is None:
            return math.inf
        worst = max(
            worst,
            abs(float(row["aurc"]) - float(summary["aurc_trapezoid"])),
            abs(float(row["augrc"]) - float(summary["augrc_trapezoid"])),
        )
    return worst


def make_figure(
    all_points: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    figure_png: Path,
    figure_pdf: Path,
) -> None:
    selected_methods = ("M2_classifier_only", "M6_full_v2_replay")
    task_totals = {
        row["task_type"]: int(row["n_total"])
        for row in summaries
        if row["method_id"] == "M2_classifier_only"
        and row["task_type"] not in OWNER_PROXY_TASKS
        and int(row["n_total"]) >= MIN_AREA_N
    }
    tasks = sorted(task_totals)
    if not tasks:
        raise AssertionError("no sufficiently populated tasks for risk-coverage figure")

    colors = {"M2_classifier_only": "#2F6B9A", "M6_full_v2_replay": "#C58A24"}
    styles = {"M2_classifier_only": ("-", "o"), "M6_full_v2_replay": ("--", "s")}
    labels = {"M2_classifier_only": "Classifier proxy", "M6_full_v2_replay": "Full V2 replay"}
    columns = 3
    rows_count = math.ceil(len(tasks) / columns)
    fig, axes = plt.subplots(rows_count, columns, figsize=(11.4, 3.45 * rows_count), squeeze=False)
    for axis, task in zip(axes.flat, tasks):
        for method_id in selected_methods:
            points = [
                row
                for row in all_points
                if row["point_type"] == "exact_unique"
                and row["curve_mode"] == "constrained_selective"
                and row["task_type"] == task
                and row["method_id"] == method_id
                and row["selective_risk"] != ""
            ]
            if not points:
                continue
            line, marker = styles[method_id]
            axis.plot(
                [float(row["coverage"]) for row in points],
                [float(row["selective_risk"]) for row in points],
                linestyle=line,
                marker=marker,
                markersize=3.4,
                linewidth=1.8,
                color=colors[method_id],
                label=labels[method_id],
            )
        axis.set_title(f"{task} (n={task_totals[task]})", fontsize=10, loc="left")
        axis.set_xlim(0, 1.02)
        axis.set_ylim(0, 1.02)
        axis.set_xlabel("Coverage")
        axis.set_ylabel("Selective risk")
        axis.grid(True, color="#D8DDE3", linewidth=0.7, alpha=0.8)
        axis.spines[["top", "right"]].set_visible(False)
    for axis in axes.flat[len(tasks) :]:
        axis.axis("off")
    handles, legend_labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.945))
    fig.suptitle("Risk–coverage curves on the frozen AI-gold test split", fontsize=15, y=0.995)
    fig.text(
        0.5,
        0.965,
        "Primary constrained mode: accept only when confidence passes and all hard constraints pass; rejected rows route to review.",
        ha="center",
        va="top",
        fontsize=9.5,
        color="#4B5563",
    )
    fig.text(
        0.01,
        0.01,
        "M2 is a held-out supervised proxy; M6 is a shared-signal replay. No live LLM calls; owner proxies are excluded.",
        fontsize=8.5,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0.02, 0.04, 0.99, 0.92))
    fig.savefig(figure_png, dpi=240, facecolor="white")
    fig.savefig(figure_pdf, facecolor="white")
    plt.close(fig)


def output_record(path: Path, row_count: int | None = None) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "row_count": row_count,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Selective-inference risk-coverage pipeline (v3, GOAL.md Phase 7)."
    )
    parser.add_argument(
        "--reference",
        choices=REFERENCE_MODES,
        default="era",
        help=(
            "correctness reference: 'era' reproduces the v2 ERA-based run; "
            "'imcr_strong' / 'imcr_all' re-evaluate against the independent "
            "multi-model consensus reference (no silent ERA fallback)."
        ),
    )
    parser.add_argument("--runs-path", type=Path, default=DEFAULT_RUNS_PATH)
    parser.add_argument("--baseline-audit-path", type=Path, default=DEFAULT_BASELINE_AUDIT_PATH)
    parser.add_argument("--gold-path", type=Path, default=DEFAULT_GOLD_PATH)
    parser.add_argument("--imcr-strong-path", type=Path, default=DEFAULT_IMCR_STRONG_PATH)
    parser.add_argument("--imcr-all-path", type=Path, default=DEFAULT_IMCR_ALL_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument(
        "--output-prefix",
        default="",
        help="prefix prepended to every output file name (e.g. 'era_')",
    )
    parser.add_argument(
        "--bootstrap-iterations",
        type=int,
        default=BOOTSTRAP_ITERATIONS,
        help="fixed-seed bootstrap replicates per applicable curve (testing hook; "
        "the production value is 2000)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    reference_mode = args.reference
    outdir = args.output_dir
    outdir.mkdir(parents=True, exist_ok=True)
    prefix = args.output_prefix
    iterations = args.bootstrap_iterations
    if iterations <= 0:
        raise ValueError("--bootstrap-iterations must be positive")

    runs_path = args.runs_path
    baseline_audit_path = args.baseline_audit_path
    gold_path = args.gold_path

    points_path = outdir / f"{prefix}RISK_COVERAGE_POINTS.csv"
    summary_csv_path = outdir / f"{prefix}RISK_COVERAGE_SUMMARY.csv"
    bootstrap_path = outdir / f"{prefix}RISK_COVERAGE_BOOTSTRAP.csv"
    goal13_path = outdir / f"{prefix}SELECTIVE_GOAL13_METRICS.csv"
    summary_json_path = outdir / f"{prefix}risk_coverage_summary.json"
    audit_path = outdir / f"{prefix}risk_coverage_audit.json"
    report_path = outdir / f"{prefix}RISK_COVERAGE_REPORT.md"
    contract_path = outdir / f"{prefix}RISK_COVERAGE_CHART_CONTRACT.json"
    figure_png = outdir / f"{prefix}risk_coverage_curves.png"
    figure_pdf = outdir / f"{prefix}risk_coverage_curves.pdf"

    baseline_audit = json.loads(baseline_audit_path.read_text(encoding="utf-8"))
    if baseline_audit.get("result") != "PASS":
        raise AssertionError("baseline audit must pass before selective-inference evaluation")
    runs = read_csv(runs_path)
    if not runs:
        raise AssertionError("BASELINE_RUNS.csv is empty")

    reference: dict[tuple[str, str], str] | None = None
    reference_path: Path | None = None
    reference_metadata: dict[str, Any] | None = None
    if reference_mode == "era":
        if not gold_path.exists():
            raise FileNotFoundError(
                f"--reference era requires the ERA gold file '{gold_path}'"
            )
    else:
        reference_path = (
            args.imcr_strong_path if reference_mode == "imcr_strong" else args.imcr_all_path
        )
        reference = load_imcr_reference(reference_path, reference_mode)
        runs, reference_metadata = apply_imcr_reference(runs, reference, reference_mode)

    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in runs:
        groups[(row["method_id"], row["task_type"])].append(row)

    all_points: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    bootstrap_rows: list[dict[str, Any]] = []
    for key, rows in sorted(groups.items()):
        for curve_mode in ("constrained_selective", "score_only_diagnostic"):
            if not any(numeric_confidence(row) is not None for row in rows):
                summaries.append(no_score_summary(rows, curve_mode))
                continue
            exact = exact_curve(rows, curve_mode)
            fixed = fixed_curve(rows, curve_mode)
            all_points.extend(exact)
            all_points.extend(fixed)
            summary = summarize_curve(rows, exact, curve_mode)
            if summary["area_status"] == "applicable":
                replicates, seed = bootstrap_area_rows(rows, curve_mode, iterations=iterations)
                bootstrap_rows.extend(replicates)
                aurc_low, aurc_high = percentile_interval(
                    [float(row["aurc_trapezoid"]) for row in replicates]
                )
                augrc_low, augrc_high = percentile_interval(
                    [float(row["augrc_trapezoid"]) for row in replicates]
                )
                summary.update(
                    {
                        "bootstrap_seed": seed,
                        "bootstrap_iterations": iterations,
                        "aurc_bootstrap_ci95_low": aurc_low,
                        "aurc_bootstrap_ci95_high": aurc_high,
                        "augrc_bootstrap_ci95_low": augrc_low,
                        "augrc_bootstrap_ci95_high": augrc_high,
                    }
                )
            summaries.append(summary)

    point_fields = list(all_points[0].keys())
    summary_fields = list(summaries[0].keys())
    write_csv(points_path, all_points, point_fields)
    write_csv(summary_csv_path, summaries, summary_fields)
    bootstrap_fields = [
        "method_id",
        "task_type",
        "curve_mode",
        "replicate_index",
        "bootstrap_seed",
        "sample_size",
        "aurc_trapezoid",
        "augrc_trapezoid",
    ]
    write_csv(bootstrap_path, bootstrap_rows, bootstrap_fields)

    goal13_rows = goal13_metric_rows(groups, reference_mode, reference)
    write_csv(goal13_path, goal13_rows, GOAL13_FIELDS)
    goal13_max_diff = goal13_crosscheck_max_diff(goal13_rows, summaries)

    chart_contract = {
        "analytical_question": "How much selective risk is removed as low-confidence predictions are routed to review, and at what coverage cost?",
        "supported_takeaway": "The figure reports the empirical trade-off only; M2 is a held-out AI-gold proxy and M6 is a shared-signal frozen replay.",
        "curve_mode": "constrained_selective",
        "acceptance_rule": "score >= threshold AND hard_constraint_pass = 1",
        "family": "Uncertainty & Benchmark",
        "variant": "small-multiple risk-coverage line charts",
        "data_sufficiency": {
            "minimum_task_n_for_figure": MIN_AREA_N,
            "minimum_unique_scores_for_area": MIN_UNIQUE_SCORES,
            "scatter_or_temporal_claim": False,
            "excluded_from_figure": sorted(OWNER_PROXY_TASKS),
            "exclusion_reason": "dedicated role-owner audit marks owner references evaluation-ineligible for primary comparison",
        },
        "renderer": "static Matplotlib PNG/PDF",
        "palette_policy": "hard two-root cap plus neutrals",
        "palette": {"Classifier proxy": "#2F6B9A", "Full V2 replay": "#C58A24"},
        "non_color_distinction": {"Classifier proxy": "solid circle", "Full V2 replay": "dashed square"},
        "x_axis": "Coverage, fixed full-test denominator",
        "y_axis": "Selective risk among accepted predictions",
        "output": [str(figure_png), str(figure_pdf)],
        "qa_surface": "exported PNG at 240 dpi and PDF",
    }
    write_json(contract_path, chart_contract)
    inline_figure_rendered = any(row["method_id"] in SCORE_METHODS for row in summaries)
    if inline_figure_rendered:
        # v2/ERA 运行（M 系列方法号）：内联 small-multiple 图与 era 逐格对齐。
        make_figure(all_points, summaries, figure_png, figure_pdf)
    else:
        # IMCR 独立基线运行（B 系列方法号）：era 风格图不适用（方法选择硬编码
        # M2/M6）；GOAL 13.1 的 IMCR 风险-覆盖图由 build_imcr_figures.py 渲染。
        print(
            "[run_selective_inference] B-series runs detected: skipping inline "
            "ERA-style figure; render the IMCR figure via build_imcr_figures.py"
        )

    applicable = [row for row in summaries if row["area_status"] == "applicable"]
    formula_checks = [
        float(row["augrc_check_abs_diff"])
        for row in applicable
        if row["augrc_check_abs_diff"] is not None
    ]
    reference_input_block: dict[str, Any] = {"reference_mode": reference_mode}
    if reference_mode == "era":
        reference_input_block["era_gold"] = str(gold_path)
        reference_input_block["era_gold_sha256"] = sha256_file(gold_path)
    else:
        assert reference_path is not None
        reference_input_block["imcr_reference"] = str(reference_path)
        reference_input_block["imcr_reference_sha256"] = sha256_file(reference_path)
        reference_input_block["imcr_reference_coverage"] = reference_metadata

    summary_json = {
        "generated_at": utc_now(),
        "result": "PASS",
        "input": {
            "baseline_runs": str(runs_path),
            "baseline_runs_sha256": sha256_file(runs_path),
            **reference_input_block,
        },
        "definitions": {
            "primary_curve_mode": "constrained_selective",
            "primary_acceptance": "score >= threshold AND hard_constraint_pass = 1",
            "diagnostic_curve_mode": "score_only_diagnostic; ignores hard constraints and cannot represent automatic admission",
            "coverage": "accepted_count / full frozen task test count"
            + ("" if reference_mode == "era" else " (IMCR-reference-covered subset)"),
            "selective_risk": "accepted errors / accepted_count",
            "generalized_risk": "accepted errors / full frozen task test count",
            "safe_coverage": "accepted, reference-correct, hard-constraint-passing rows / full frozen task test count",
            "abstention_rate": "1 - coverage",
            "review_escalation_rate": "abstained rows / full frozen task test count; this run performs no LLM call",
            "aurc": "trapezoid integral over exact tie-grouped points on each curve's achievable [0,max_coverage] domain",
            "augrc": "trapezoid integral of generalized risk on the same achievable coverage domain",
            "tie_policy": "all rows with equal confidence are accepted together",
            "score_direction": "higher confidence is safer",
            "owner_applicability": "time_owner and space_owner curves are diagnostic only and excluded from primary areas/figure",
            "correctness_reference": (
                "ERA integrated reference annotation (frozen flags in BASELINE_RUNS.csv)"
                if reference_mode == "era"
                else f"IMCR ({reference_mode}); correct = prediction == reference_label on reference-covered samples only"
            ),
        },
        "area_gate": {
            "constrained_selective": "numeric score required for every hard-constraint-eligible prediction; integration ends at max achievable coverage",
            "score_only_diagnostic": "numeric score required for the full frozen task test set",
            "minimum_n": MIN_AREA_N,
            "minimum_unique_scores": MIN_UNIQUE_SCORES,
        },
        "bootstrap": {
            "global_seed": BOOTSTRAP_SEED,
            "per_curve_seed": "first 32 bits of SHA-256(global_seed|method_id|task_type|curve_mode)",
            "iterations": iterations,
            "interval": "percentile 95% using NumPy linear quantiles",
            "raw_replicates": str(bootstrap_path),
        },
        "goal13_point_metrics": {
            "path": str(goal13_path),
            "computed_with": "code/independent_eval/metrics.py",
            "operating_point": "max-coverage constrained acceptance (all curve-eligible rows accepted)",
            "aurc_augrc_crosscheck_max_abs_diff": goal13_max_diff,
        },
        "curve_summaries": summaries,
        "actual_llm_calls": 0,
        "references": [
            "https://jmlr.csail.mit.edu/papers/v11/el-yaniv10a.html",
            "https://proceedings.neurips.cc/paper_files/paper/2024/file/047c84ec50bd8ea29349b996fc64af4b-Paper-Conference.pdf",
        ],
    }
    write_json(summary_json_path, summary_json)

    exact_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in all_points:
        if row["point_type"] == "exact_unique":
            exact_groups[(row["method_id"], row["task_type"], row["curve_mode"])].append(row)
    monotonic = True
    denominator_fixed = True
    arithmetic_valid = True
    for key, points in exact_groups.items():
        points.sort(key=lambda row: int(row["point_index"]))
        coverages = [float(row["coverage"]) for row in points]
        monotonic &= all(left <= right + 1e-15 for left, right in zip(coverages, coverages[1:]))
        denominators = {int(row["total_count"]) for row in points}
        denominator_fixed &= len(denominators) == 1
        for row in points:
            total = int(row["total_count"])
            accepted = int(row["accepted_count"])
            errors = int(row["error_count"])
            safe = int(row["safe_count"])
            arithmetic_valid &= (
                0 <= errors <= accepted <= total
                and 0 <= safe <= accepted
                and abs(float(row["coverage"]) - accepted / total) <= 1e-12
                and abs(float(row["safe_coverage"]) - safe / total) <= 1e-12
                and abs(float(row["abstention_rate"]) - (total - accepted) / total) <= 1e-12
            )

    bootstrap_by_curve: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in bootstrap_rows:
        bootstrap_by_curve[(row["method_id"], row["task_type"], row["curve_mode"])].append(row)
    bootstrap_ci_valid = True
    for summary in applicable:
        rows_for_curve = bootstrap_by_curve[
            (summary["method_id"], summary["task_type"], summary["curve_mode"])
        ]
        aurc_interval = percentile_interval([float(row["aurc_trapezoid"]) for row in rows_for_curve])
        augrc_interval = percentile_interval([float(row["augrc_trapezoid"]) for row in rows_for_curve])
        bootstrap_ci_valid &= (
            len(rows_for_curve) == iterations
            and int(summary["bootstrap_iterations"]) == iterations
            and abs(float(summary["aurc_bootstrap_ci95_low"]) - aurc_interval[0]) <= 1e-15
            and abs(float(summary["aurc_bootstrap_ci95_high"]) - aurc_interval[1]) <= 1e-15
            and abs(float(summary["augrc_bootstrap_ci95_low"]) - augrc_interval[0]) <= 1e-15
            and abs(float(summary["augrc_bootstrap_ci95_high"]) - augrc_interval[1]) <= 1e-15
        )
    bootstrap_reproducible = True
    if applicable:
        first = applicable[0]
        original_rows = groups[(first["method_id"], first["task_type"])]
        first_run, first_seed = bootstrap_area_rows(
            original_rows, first["curve_mode"], iterations=10
        )
        second_run, second_seed = bootstrap_area_rows(
            original_rows, first["curve_mode"], iterations=10
        )
        bootstrap_reproducible = first_seed == second_seed and first_run == second_run

    def expected_area_gate(row: dict[str, Any]) -> bool:
        if row["task_type"] in OWNER_PROXY_TASKS or int(row["n_scored"]) <= 0:
            return False
        complete = (
            int(row["n_scored"]) == int(row["n_hard_constraint_eligible"])
            if row["curve_mode"] == "constrained_selective"
            else int(row["n_scored"]) == int(row["n_total"])
        )
        return bool(
            complete
            and int(row["n_total"]) >= MIN_AREA_N
            and int(row["unique_score_count"]) >= MIN_UNIQUE_SCORES
        )

    constrained_acceptance_valid = True
    for point in all_points:
        if point["curve_mode"] != "constrained_selective":
            continue
        source_rows = groups[(point["method_id"], point["task_type"])]
        threshold = math.inf if point["threshold"] == "INF" else float(point["threshold"])
        accepted_rows = [
            row
            for row in source_rows
            if row["availability_status"] != "not_available"
            and row["prediction"]
            and (score := numeric_confidence(row)) is not None
            and score >= threshold
            and row["hard_constraint_pass"] == "1"
        ]
        constrained_acceptance_valid &= (
            len(accepted_rows) == int(point["accepted_count"])
            and all(row["hard_constraint_pass"] == "1" for row in accepted_rows)
        )

    canaries = {
        "baseline_audit_pass": baseline_audit.get("result") == "PASS",
        "points_nonempty": bool(all_points),
        "summaries_nonempty": bool(summaries),
        "coverage_monotonic_as_threshold_relaxes": monotonic,
        "fixed_denominator_within_each_curve": denominator_fixed,
        "curve_arithmetic_valid": arithmetic_valid,
        "safe_coverage_never_exceeds_coverage": all(
            float(row["safe_coverage"]) <= float(row["coverage"]) + 1e-15 for row in all_points
        ),
        "review_escalation_equals_abstention": all(
            abs(float(row["review_escalation_rate"]) - float(row["abstention_rate"])) <= 1e-15
            for row in all_points
        ),
        "actual_llm_calls_zero": all(int(row["actual_llm_calls"]) == 0 for row in all_points),
        "area_only_when_gate_satisfied": all(
            (row["area_status"] == "applicable") == expected_area_gate(row)
            for row in summaries
        ),
        "primary_curve_is_constrained_selective": all(
            int(row["primary_curve"]) == int(row["curve_mode"] == "constrained_selective")
            for row in all_points + summaries
        ),
        "constrained_accepted_rows_pass_hard_gate": constrained_acceptance_valid,
        "score_only_is_diagnostic_not_primary": all(
            int(row["primary_curve"]) == 0
            for row in all_points + summaries
            if row["curve_mode"] == "score_only_diagnostic"
        ),
        "owner_proxy_excluded_from_primary_area": all(
            row["area_status"] == "not_applicable_primary_ineligible_owner_proxy"
            and row["evaluation_eligibility"]
            == "evaluation_ineligible_for_primary_owner_shared_proxy"
            for row in summaries
            if row["task_type"] in OWNER_PROXY_TASKS
        ),
        "cached_models_have_no_fabricated_points": not any(
            row["method_id"] in {"M3_live_llm_only", "M3_cached_llm_replay"}
            for row in all_points
        ),
        "augrc_closed_form_crosscheck": all(value <= 1e-12 for value in formula_checks),
        "goal13_metrics_crosscheck": goal13_max_diff <= 1e-12,
        "bootstrap_replicate_count_complete": len(bootstrap_rows) == len(applicable) * iterations,
        "bootstrap_ci_recomputes_from_raw_replicates": bootstrap_ci_valid,
        "bootstrap_fixed_seed_reproducible": bootstrap_reproducible,
        # 内联图仅对 v2/ERA（M 系列）运行渲染；B 系列运行由 build_imcr_figures 出图。
        "figure_png_exists": (not inline_figure_rendered)
        or (figure_png.exists() and figure_png.stat().st_size > 0),
        "figure_pdf_exists": (not inline_figure_rendered)
        or (figure_pdf.exists() and figure_pdf.stat().st_size > 0),
    }
    outputs = {
        "points": output_record(points_path, len(all_points)),
        "summary_csv": output_record(summary_csv_path, len(summaries)),
        "bootstrap": output_record(bootstrap_path, len(bootstrap_rows)),
        "goal13_metrics": output_record(goal13_path, len(goal13_rows)),
        "summary_json": output_record(summary_json_path),
        "chart_contract": output_record(contract_path),
        # B 系列运行跳过内联 ERA 图（GOAL 13.1 的 IMCR 图由 build_imcr_figures
        # 渲染），此处如实记录 not_rendered 而不是哈希不存在的文件。
        "figure_png": (
            output_record(figure_png)
            if figure_png.exists()
            else {"path": str(figure_png.resolve()), "rendered": False,
                  "note": "B-series runs: inline ERA-style figure not rendered"}
        ),
        "figure_pdf": (
            output_record(figure_pdf)
            if figure_pdf.exists()
            else {"path": str(figure_pdf.resolve()), "rendered": False,
                  "note": "B-series runs: inline ERA-style figure not rendered"}
        ),
    }
    input_records: dict[str, Any] = {
        "baseline_runs": output_record(runs_path, len(runs)),
        "baseline_audit": output_record(baseline_audit_path),
    }
    if reference_mode == "era":
        input_records["gold"] = output_record(
            gold_path, len(read_csv(gold_path))
        )
    else:
        assert reference_path is not None
        input_records["imcr_reference"] = output_record(reference_path, len(reference or {}))
    audit = {
        "generated_at": utc_now(),
        "result": "PASS" if all(canaries.values()) else "FAIL",
        "reference_mode": reference_mode,
        "reference_metadata": reference_metadata,
        "inputs": input_records,
        "canaries": canaries,
        "applicable_area_curve_count": len(applicable),
        "applicable_primary_constrained_curve_count": sum(
            row["curve_mode"] == "constrained_selective" for row in applicable
        ),
        "applicable_score_only_diagnostic_curve_count": sum(
            row["curve_mode"] == "score_only_diagnostic" for row in applicable
        ),
        "formula_crosscheck_count": len(formula_checks),
        "maximum_augrc_crosscheck_abs_diff": max(formula_checks, default=0.0),
        "goal13_metrics_crosscheck_max_abs_diff": goal13_max_diff,
        "bootstrap_iterations_per_applicable_curve": iterations,
        "bootstrap_raw_row_count": len(bootstrap_rows),
        "outputs": outputs,
        "scope_notes": [
            "No confidence is fabricated for cached LLM rows; no cached-LLM AURC/AUGRC is reported.",
            "Primary constrained_selective acceptance requires both the confidence threshold and hard_constraint_pass=1.",
            "score_only_diagnostic curves are retained only to expose the effect of the hard gate and cannot represent automatic admission.",
            "Constrained AURC/AUGRC integrate over each method's achievable [0,max_coverage] domain; normalized areas are also reported.",
            "M2 remains an AI-gold supervised proxy and M6 remains a shared-system-signal deterministic replay.",
            "Owner proxy tasks are excluded from primary areas and the figure by the dedicated role-owner audit.",
            "Review escalation is a routing counter only; actual LLM calls remain zero.",
            f"Correctness reference for this run: {reference_mode}.",
            *(
                []
                if reference_mode == "era"
                else [
                    "IMCR mode evaluates only reference-covered samples; the curve denominator is the IMCR-covered subset of the frozen task test set.",
                    "A missing IMCR reference file is a hard error; no silent fallback to ERA exists.",
                ]
            ),
        ],
    }
    write_json(audit_path, audit)
    if audit["result"] != "PASS":
        raise AssertionError(f"selective inference audit failed: {canaries}")

    report_lines = [
        "# Paper A selective-inference report (v3)",
        "",
        f"- Result: **{audit['result']}**",
        f"- Correctness reference: **{reference_mode}**",
        f"- Curve rows: {len(all_points)}",
        f"- Curves with valid AURC/AUGRC: {len(applicable)}",
        f"- Primary constrained curves with valid areas: {audit['applicable_primary_constrained_curve_count']}",
        f"- Maximum AUGRC closed-form cross-check difference: `{audit['maximum_augrc_crosscheck_abs_diff']:.3e}`",
        f"- GOAL-13 metrics.py AURC/AUGRC cross-check difference: `{goal13_max_diff:.3e}`",
        f"- Bootstrap: {iterations} fixed-seed replicates for each applicable curve; raw rows `{len(bootstrap_rows)}`",
        "- Live LLM calls: **0**",
        "",
        "## Metric definitions",
        "",
        "- Primary coverage accepts a row only when `score >= threshold` and `hard_constraint_pass = 1`; the denominator remains the full frozen task test set.",
        "- Score-only curves are diagnostic and are never interpreted as method automatic-admission performance.",
        "- Selective risk is the error proportion among accepted predictions.",
        "- Generalized risk is accepted errors divided by the full test denominator.",
        "- Safe coverage requires reference agreement and the task-specific hard-constraint gate already recorded in `BASELINE_RUNS.csv`.",
        "- Rejected rows are counted as review escalation; this is not an LLM-call count.",
        "- Primary AURC/AUGRC use trapezoidal integration over exact tie-grouped constrained points on the achievable `[0,max_coverage]` domain; normalized areas are also retained.",
        f"- AURC/AUGRC 95% intervals use fixed-seed percentile bootstrap; every replicate is retained in `{prefix}RISK_COVERAGE_BOOTSTRAP.csv`.",
        f"- GOAL-13 point metrics (selective accuracy, error exposure, macro-F1 on accepted, macro-F1 on full denominator) are computed with `code/independent_eval/metrics.py` in `{prefix}SELECTIVE_GOAL13_METRICS.csv`.",
        "",
        "## Reference mode",
        "",
        *(
            [
                "- `--reference era`: correctness flags frozen in `BASELINE_RUNS.csv` (ERA integrated reference annotation) are used unchanged; this mode reproduces the v2 numbers.",
            ]
            if reference_mode == "era"
            else [
                f"- `--reference {reference_mode}`: correctness is recomputed as `prediction == reference_label` against the IMCR file; only reference-covered samples are evaluated.",
                "- The IMCR file is produced by the Phase-2 blind judge pipeline; a missing file is a hard error (no ERA fallback).",
            ]
        ),
        "",
        "## Evidence interpretation",
        "",
        "- M2 is a held-out supervised proxy against the unchanged AI gold.",
        "- M6 is a frozen deterministic replay with shared system signals.",
        "- Cached LLM outputs have no numeric confidence and directly contributed to gold construction, so no cached-LLM area metric is produced.",
        "- Owner reference tasks remain shared-proxy diagnostics and do not enter primary areas or the figure.",
        "",
        "## References",
        "",
        "- El-Yaniv and Wiener, risk–coverage foundations: https://jmlr.csail.mit.edu/papers/v11/el-yaniv10a.html",
        "- Traub et al., generalized risk and AUGRC: https://proceedings.neurips.cc/paper_files/paper/2024/file/047c84ec50bd8ea29349b996fc64af4b-Paper-Conference.pdf",
    ]
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    result = {
        "result": audit["result"],
        "reference_mode": reference_mode,
        "point_rows": len(all_points),
        "curve_summaries": len(summaries),
        "applicable_area_curves": len(applicable),
        "maximum_augrc_check_diff": audit["maximum_augrc_crosscheck_abs_diff"],
        "goal13_crosscheck_max_abs_diff": goal13_max_diff,
        "actual_llm_calls": 0,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    main()
