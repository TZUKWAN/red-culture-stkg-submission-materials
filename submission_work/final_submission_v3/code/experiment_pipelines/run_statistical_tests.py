#!/usr/bin/env python3
"""Statistical-test pipeline for experiment 14 (GOAL.md section 18).

Consumes the per-sample baseline runs of experiment 09
(``IMCR_BASELINE_RUNS.csv`` — the primary data source; every statistic is
computed row-by-row from it) and the experiment-13 selective-inference
outputs (``<prefix>RISK_COVERAGE_POINTS.csv`` /
``<prefix>SELECTIVE_GOAL13_METRICS.csv``), which are used *only* as an
independent cross-check of the Wilson table.  Judge-agreement outputs of
experiment 08 are summarised by reference (no mathematics is recomputed).

Outputs (``experiments/14_statistical_tests/``):

* ``WILSON_CI_TABLE.csv`` — per (method_id, task_type) operating point:
  ``n / correct / error / estimate / 95% Wilson CI`` for the coverage
  proportion and the post-accept selective accuracy as separate rows
  (``metric`` column).  The operating point is the max-coverage
  constrained-acceptance point (all curve-eligible rows accepted), i.e. the
  accept-*all-eligible* end of the 13 curve; note that in the 13 output the
  ``threshold='INF'`` row is the accept-*nothing* origin, so the cross-check
  uses the exact point with the largest ``accepted_count`` instead.
* ``PAIRED_BOOTSTRAP_DELTAS.csv`` + ``PAIRED_BOOTSTRAP_REPLICATES.csv`` —
  Full (``B12_full_framework``) vs every available baseline on the same
  task set: ΔAURC / ΔAUGRC (Full − baseline) with shared resample
  indices (GOAL 18 "paired system comparison"), 2000 fixed-seed
  replicates, every replicate persisted (GOAL 13.2).
* ``MCNEMAR_TESTS.csv`` — exact-binomial McNemar test on the binary
  correct/wrong outcome, Full vs every available baseline per task
  (``scope_adjustment`` uses the strict AFTER_BETTER binarisation of
  audit/04_BASELINE_DESIGN.md §4.3); win/tie/loss counts included.
* ``JUDGE_AGREEMENT_SUMMARY.csv`` — reference-only summary of the 08 judge
  agreement outputs plus ``task_type=ALL`` pooling rows (unweighted means /
  sums of the published values; nothing recomputed from raw votes).
* ``STATISTICAL_ANALYSIS_MANIFEST.json`` — GOAL-21 manifest with input
  SHA-256 digests, the seed policy and replicate counts.
* ``11_STATISTICAL_ANALYSIS.md`` — GOAL-18 report.  By default a skeleton
  with ``<PENDING: ...>`` placeholders; ``--fill`` embeds the numbers
  computed in this run (use it only for the production run).

Method naming follows ``audit/04_BASELINE_DESIGN.md`` §3:
``B1_rule_only / B2_classifier_only / B3_blind_llm / B4_rule_plus_classifier /
B5_rule_plus_blind_llm / B7_margin_threshold / B8_entropy_threshold /
B9_agreement_gate / B10_selective_no_gate / B11_gate_no_abstention /
B12_full_framework``.  ``B6`` (classifier confidence threshold) is *the same
curve as B2* by design (§3: "B6 不另发重复行"), so B6 is implemented as an
alias that resolves to the ``B2_classifier_only`` rows and is never emitted
as a separate comparison (no double counting).

All mathematical definitions are reused from existing, independently tested
code — none are re-implemented here:

* curves/areas: ``independent_eval/metrics.py``
  (``risk_coverage_curve`` / ``aurc`` / ``augrc``), with the
  eligible-fraction coverage rescaling of
  ``run_selective_inference.goal13_metric_rows``;
* paired bootstrap: ``independent_eval/metrics.py
  ::paired_bootstrap_diff_ci`` — this function **already is a shared-index
  implementation**: each replicate draws ``idx = rng.integers(0, n, n)``
  once and applies the identical index array to both aligned datasets
  before differencing the statistics, which is exactly the GOAL-18 paired
  comparison requirement.  Calling it twice (AURC and AUGRC) with the same
  derived seed reproduces the identical resample index stream because the
  index stream depends only on ``(seed, n, n_replicates)``;
* McNemar: ``independent_eval/metrics.py::mcnemar_test`` (exact binomial);
* Wilson CI: ``independent_eval/metrics.py::wilson_ci``;
* IMCR reference semantics: ``run_selective_inference.load_imcr_reference``
  / ``apply_imcr_reference`` / ``numeric_confidence`` (no silent fallbacks).

Missing inputs are hard errors (``FileNotFoundError`` / ``ValueError`` with
an explicit message); nothing is silently skipped.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

SCRIPT = Path(__file__).resolve()
CODE_DIR = SCRIPT.parents[1]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

# GOAL 18 wiring: reuse the independently tested implementations instead of
# rewriting any mathematical definition.
from independent_eval import metrics as selective_metrics
from independent_eval._common import MASTER_SEED, derive_seed
from independent_eval.manifest import build_manifest, sha256_file, write_manifest
from experiment_pipelines import run_selective_inference as rsi

V3_ROOT = SCRIPT.parents[2]
EXPERIMENTS_DIR = V3_ROOT / "experiments"

DEFAULT_RUNS_PATH = EXPERIMENTS_DIR / "09_independent_baselines" / "IMCR_BASELINE_RUNS.csv"
DEFAULT_JUDGE_DIR = EXPERIMENTS_DIR / "08_independent_reference"
DEFAULT_IMCR_STRONG_PATH = DEFAULT_JUDGE_DIR / "IMCR_REFERENCE_STRONG.csv"
DEFAULT_IMCR_ALL_PATH = DEFAULT_JUDGE_DIR / "IMCR_REFERENCE_ALL.csv"
DEFAULT_OUTDIR = EXPERIMENTS_DIR / "14_statistical_tests"

REFERENCE_MODES = ("imcr_strong", "imcr_all", "frozen")

JUDGE_PAIRWISE_FILE = "JUDGE_PAIRWISE_AGREEMENT.csv"
JUDGE_RELIABILITY_FILE = "JUDGE_RELIABILITY_SUMMARY.csv"
JUDGE_LOJO_FILE = "LEAVE_ONE_JUDGE_OUT.csv"

POINTS_FILE_SUFFIX = "RISK_COVERAGE_POINTS.csv"
GOAL13_FILE_SUFFIX = "SELECTIVE_GOAL13_METRICS.csv"

PAIRED_BOOTSTRAP_REPLICATES = 2000
SEED_LABEL_TEMPLATE = "paired_bootstrap::{task_type}::{baseline}"
METRICS_IN_DELTAS = ("aurc", "augrc")

#: Method naming convention of audit/04_BASELINE_DESIGN.md §3 (B-series).
FULL_METHOD_ID = "B12_full_framework"
METHOD_NAMES = {
    "B1_rule_only": "Rule-only",
    "B2_classifier_only": "Frozen classifier",
    "B3_blind_llm": "Blind LLM",
    "B4_rule_plus_classifier": "Rule+classifier",
    "B5_rule_plus_blind_llm": "Rule+blind LLM",
    # B6 (classifier confidence threshold) has no rows of its own: by design
    # §3 the B2 confidence-threshold sweep *is* B6, so reports cite B2's
    # curve under the B6 name.  Kept here for documentation only.
    "B6_classifier_threshold": "Classifier conf threshold (alias of B2)",
    "B7_margin_threshold": "Classifier margin threshold",
    "B8_entropy_threshold": "Entropy threshold",
    "B9_agreement_gate": "Rule-model agreement gate",
    "B10_selective_no_gate": "Selective, no structural gate",
    "B11_gate_no_abstention": "Structural gate, no abstention",
    "B12_full_framework": "Full framework",
}
BASELINE_METHOD_IDS = (
    "B1_rule_only",
    "B2_classifier_only",
    "B3_blind_llm",
    "B4_rule_plus_classifier",
    "B5_rule_plus_blind_llm",
    "B7_margin_threshold",
    "B8_entropy_threshold",
    "B9_agreement_gate",
    "B10_selective_no_gate",
    "B11_gate_no_abstention",
)
#: B6 is an alias of B2 (design §3) — comparisons are emitted once, under the
#: resolved id, so the same data is never double counted.
METHOD_ALIASES = {"B6_classifier_threshold": "B2_classifier_only"}

WILSON_FIELDS = [
    "method_id",
    "method_name",
    "task_type",
    "metric",
    "n",
    "correct",
    "error",
    "estimate",
    "ci95_low",
    "ci95_high",
    "operating_point_mode",
    "numerator_definition",
    "note",
]
DELTA_FIELDS = [
    "task_type",
    "baseline_method_id",
    "metric",
    "status",
    "n_samples",
    "n_replicates",
    "n_valid_replicates",
    "estimate",
    "ci95_low",
    "ci95_high",
    "full_estimate",
    "baseline_estimate",
    "bootstrap_seed",
    "note",
]
REPLICATE_FIELDS = [
    "task_type",
    "baseline_method_id",
    "metric",
    "replicate_index",
    "delta",
    "bootstrap_seed",
    "n_samples",
]
MCNEMAR_FIELDS = [
    "task_type",
    "baseline_method_id",
    "comparison",
    "n_pairs",
    "b_full_correct_baseline_wrong",
    "c_full_wrong_baseline_correct",
    "n_discordant",
    "statistic",
    "p_value",
    "method",
    "full_wins",
    "full_losses",
    "ties",
    "note",
]
JUDGE_SUMMARY_FIELDS = [
    "source_file",
    "kind",
    "task_type",
    "item",
    "metric",
    "value",
    "n",
    "note",
]

PENDING_PLACEHOLDER = "<PENDING: 待 13 号正式运行后填充>"
CROSSCHECK_TOLERANCE = 1e-9


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Small IO helpers (reads tolerate the utf-8-sig BOM used by _common.write_csv)
# ---------------------------------------------------------------------------


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_flag(row: dict[str, str], column: str, context: str) -> int:
    raw = str(row.get(column) or "").strip()
    if raw not in {"0", "1"}:
        raise ValueError(
            f"{context}: column {column!r} must be 0 or 1, got {raw!r}; "
            "the runs file must carry evaluated correctness flags (run "
            "run_selective_inference --reference imcr_* first, or pass a "
            "reference with --reference)"
        )
    return int(raw)


def _mean(values: list[float]) -> float:
    return float(sum(values) / len(values))


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


def load_runs(path: Path) -> list[dict[str, str]]:
    """Load the per-sample baseline runs (primary data source)."""
    if not path.exists():
        raise FileNotFoundError(
            f"--runs-path '{path}' does not exist. Experiment 14 needs the "
            "per-sample baseline runs generated by the Phase-6 baseline "
            "pipeline (experiments/09_independent_baselines/"
            "IMCR_BASELINE_RUNS.csv). Run that pipeline first; missing inputs "
            "are hard errors, not silent skips."
        )
    runs = read_csv(path)
    if not runs:
        raise ValueError(f"runs file '{path}' is empty")
    required = (
        "sample_id",
        "task_type",
        "method_id",
        "method_name",
        "prediction",
        "confidence",
        "availability_status",
        "correct",
        "hard_constraint_pass",
    )
    missing = [column for column in required if column not in runs[0]]
    if missing:
        raise ValueError(f"runs file '{path}' is missing required columns {missing}")
    return runs


def apply_reference(
    runs: list[dict[str, str]], args: argparse.Namespace
) -> dict[str, Any]:
    """Attach evaluated correctness flags to the runs.

    ``frozen`` uses the ``correct`` column as recorded (13-era style);
    ``imcr_strong`` / ``imcr_all`` reuse the experiment-13 semantics via
    ``run_selective_inference.load_imcr_reference`` +
    ``apply_imcr_reference`` (correct = prediction == reference_label on
    reference-covered samples only; no silent ERA fallback).
    """
    if args.reference == "frozen":
        for index, row in enumerate(runs):
            parse_flag(row, "correct", f"runs row {index}")
        return {"reference_mode": "frozen", "reference_path": None}
    reference_path = (
        args.imcr_strong_path if args.reference == "imcr_strong" else args.imcr_all_path
    )
    reference = rsi.load_imcr_reference(reference_path, args.reference)
    runs[:], metadata = rsi.apply_imcr_reference(runs, reference, args.reference)
    return {
        "reference_mode": args.reference,
        "reference_path": str(reference_path),
        "reference_metadata": metadata,
    }


def group_rows(runs: list[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()
    for row in runs:
        key = (row["method_id"], row["task_type"], row["sample_id"])
        if key in seen:
            raise ValueError(
                f"runs file has duplicate rows for method/task/sample {key}; "
                "exactly one row per (sample_id, task_type, method_id) is required"
            )
        seen.add(key)
        groups[(row["method_id"], row["task_type"])].append(row)
    if FULL_METHOD_ID not in {method for method, _ in groups}:
        raise ValueError(
            f"runs file contains no {FULL_METHOD_ID} rows; the Full framework "
            "is the reference system of every paired comparison"
        )
    return dict(groups)


def load_judge_files(judge_dir: Path) -> dict[str, list[dict[str, str]]]:
    """Load the experiment-08 judge agreement outputs (summary by reference)."""
    payload: dict[str, list[dict[str, str]]] = {}
    for name in (JUDGE_PAIRWISE_FILE, JUDGE_RELIABILITY_FILE, JUDGE_LOJO_FILE):
        path = judge_dir / name
        if not path.exists():
            raise FileNotFoundError(
                f"judge agreement input '{path}' does not exist. It is "
                "produced by the experiment-08 consensus pipeline "
                "(code/independent_eval/consensus.py). Run that pipeline "
                "first; missing inputs are hard errors, not silent skips."
            )
        rows = read_csv(path)
        if not rows:
            raise ValueError(f"judge agreement input '{path}' is empty")
        payload[name] = rows
    return payload


def maybe_load_points_outputs(
    points_dir: Path | None, points_prefix: str
) -> dict[str, Any]:
    """Optionally load the experiment-13 outputs for cross-checking.

    Both files are optional individually but at least one must exist when
    ``--points-dir`` is given; a requested-but-missing file is a hard error.
    """
    if points_dir is None:
        return {"status": "not_requested", "points_rows": [], "goal13_rows": []}
    points_path = points_dir / f"{points_prefix}{POINTS_FILE_SUFFIX}"
    goal13_path = points_dir / f"{points_prefix}{GOAL13_FILE_SUFFIX}"
    found: list[str] = []
    points_rows: list[dict[str, str]] = []
    goal13_rows: list[dict[str, str]] = []
    if points_path.exists():
        points_rows = read_csv(points_path)
        found.append(points_path.name)
    else:
        raise FileNotFoundError(
            f"--points-dir was given but '{points_path}' does not exist; the "
            "experiment-13 pipeline writes <prefix>RISK_COVERAGE_POINTS.csv "
            "whenever it runs"
        )
    if goal13_path.exists():
        goal13_rows = read_csv(goal13_path)
        found.append(goal13_path.name)
    else:
        raise FileNotFoundError(
            f"--points-dir was given but '{goal13_path}' does not exist; the "
            "experiment-13 pipeline writes "
            "<prefix>SELECTIVE_GOAL13_METRICS.csv alongside the points file"
        )
    return {
        "status": "loaded",
        "points_rows": points_rows,
        "goal13_rows": goal13_rows,
        "files": found,
        "points_path": str(points_path),
        "goal13_path": str(goal13_path),
    }


# ---------------------------------------------------------------------------
# Operating-point bookkeeping and the Wilson CI table
# ---------------------------------------------------------------------------


def cell_diagnostic(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Operating-point bookkeeping for one (method_id, task_type) cell.

    Curve-mode cells (at least one numeric confidence) accept a row at the
    max-coverage operating point when the prediction is available, a numeric
    score exists and ``hard_constraint_pass = 1`` — the same acceptance the
    experiment-13 ``goal13_metric_rows`` uses.  Point-only cells (design §4.3:
    ``scope_adjustment`` / ``identity_pair`` carry no confidence by design)
    have no risk-coverage curve, so acceptance is prediction available AND
    the hard gate; point metrics still apply.
    """
    total = len(rows)
    available = [
        row
        for row in rows
        if row.get("availability_status") != "not_available"
        and str(row.get("prediction") or "").strip()
    ]
    scored = [row for row in available if rsi.numeric_confidence(row) is not None]
    mode = "curve" if scored else "point_only"
    if scored:
        eligible = [row for row in scored if row["hard_constraint_pass"] == "1"]
    else:
        eligible = [row for row in available if row["hard_constraint_pass"] == "1"]
    unique_scores = (
        len({float(row["confidence"]) for row in eligible}) if scored else 0
    )
    return {
        "total": total,
        "n_available": len(available),
        "n_scored": len(scored),
        "eligible": eligible,
        "n_eligible": len(eligible),
        "n_correct_eligible": sum(parse_flag(r, "correct", "runs") for r in eligible),
        "mode": mode,
        "complete_score_coverage": len(scored) == len(available),
        "unique_eligible_scores": unique_scores,
    }


def build_wilson_rows(
    groups: dict[tuple[str, str], list[dict[str, str]]]
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    """Wilson 95% CI rows per (method_id, task_type) and metric.

    ``coverage``   : k = accepted rows at the operating point, n = full task
                     denominator (GOAL 13: coverage always uses the full
                     frozen task set as denominator).
    ``selective_accuracy``: k = correct among accepted, n = accepted
                     (the post-accept denominator gets its own row).
    """
    rows: list[dict[str, Any]] = []
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for (method_id, task_type), group_rows in sorted(groups.items()):
        diag = cell_diagnostic(group_rows)
        cells[(method_id, task_type)] = diag
        accepted = diag["n_eligible"]
        total = diag["total"]
        low, high = selective_metrics.wilson_ci(accepted, total)
        rows.append(
            {
                "method_id": method_id,
                "method_name": group_rows[0].get("method_name", method_id),
                "task_type": task_type,
                "metric": "coverage",
                "n": total,
                "correct": accepted,
                "error": total - accepted,
                "estimate": accepted / total,
                "ci95_low": low,
                "ci95_high": high,
                "operating_point_mode": diag["mode"],
                "numerator_definition": "accepted rows at the max-coverage operating point",
                "note": "",
            }
        )
        if accepted > 0:
            correct = diag["n_correct_eligible"]
            low, high = selective_metrics.wilson_ci(correct, accepted)
            note = (
                "point_only_mode: acceptance = prediction available AND "
                "hard_constraint_pass=1 (no numeric confidence by design §4.3)"
                if diag["mode"] == "point_only"
                else ""
            )
            rows.append(
                {
                    "method_id": method_id,
                    "method_name": group_rows[0].get("method_name", method_id),
                    "task_type": task_type,
                    "metric": "selective_accuracy",
                    "n": accepted,
                    "correct": correct,
                    "error": accepted - correct,
                    "estimate": correct / accepted,
                    "ci95_low": low,
                    "ci95_high": high,
                    "operating_point_mode": diag["mode"],
                    "numerator_definition": "correct rows among accepted",
                    "note": note,
                }
            )
    return rows, cells


def crosscheck_with_13_outputs(
    wilson_rows: list[dict[str, Any]],
    cells: dict[tuple[str, str], dict[str, Any]],
    points_payload: dict[str, Any],
) -> dict[str, Any]:
    """Cross-check the runs-derived Wilson table against the 13 outputs.

    The runs file is the primary data source; the points / GOAL-13 metrics
    CSVs are only an independent recomputation.  In the 13 points file the
    ``threshold='INF'`` row is the accept-nothing origin, so the accept-all
    operating point is the constrained exact point with the largest
    ``accepted_count``.  Any disagreement is a hard error.
    """
    if points_payload["status"] != "loaded":
        return {"status": "not_requested", "checked_cells": 0, "max_abs_diff": None}

    by_cell: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in points_payload["points_rows"]:
        if row.get("curve_mode") != "constrained_selective":
            continue
        by_cell[(row["method_id"], row["task_type"])].append(row)

    goal13_by_cell: dict[tuple[str, str], dict[str, str]] = {
        (row["method_id"], row["task_type"]): row for row in points_payload["goal13_rows"]
    }

    wilson_by_cell: dict[tuple[str, str], dict[str, Any]] = {}
    for row in wilson_rows:
        wilson_by_cell.setdefault((row["method_id"], row["task_type"]), {})[
            row["metric"]
        ] = row

    max_diff = 0.0
    checked = 0
    for cell, diag in sorted(cells.items()):
        if diag["mode"] != "curve":
            continue  # point-only cells never appear in the 13 curves
        method_id, task_type = cell
        points = by_cell.get(cell)
        if not points:
            raise ValueError(
                f"cross-check failed: no constrained_selective points for "
                f"{cell} in the 13 output although the runs cell is scored"
            )
        full_point = max(points, key=lambda row: int(row["accepted_count"]))
        expected_accepted = diag["n_eligible"]
        if int(full_point["accepted_count"]) != expected_accepted:
            raise ValueError(
                f"cross-check failed for {cell}: points file accept-all "
                f"operating point has accepted_count="
                f"{full_point['accepted_count']} but the runs file gives "
                f"{expected_accepted} eligible rows"
            )
        if int(full_point["total_count"]) != diag["total"]:
            raise ValueError(
                f"cross-check failed for {cell}: points file total_count="
                f"{full_point['total_count']} but the runs file has "
                f"{diag['total']} rows"
            )
        coverage_row = wilson_by_cell[cell]["coverage"]
        max_diff = max(
            max_diff,
            abs(float(full_point["coverage"]) - float(coverage_row["estimate"])),
        )
        if expected_accepted > 0:
            risk = str(full_point.get("selective_risk") or "").strip()
            if risk and risk != "nan":
                accuracy_row = wilson_by_cell[cell]["selective_accuracy"]
                max_diff = max(
                    max_diff,
                    abs((1.0 - float(risk)) - float(accuracy_row["estimate"])),
                )
        goal13 = goal13_by_cell.get(cell)
        if goal13 is not None:
            max_diff = max(
                max_diff,
                abs(float(goal13["coverage"]) - float(coverage_row["estimate"])),
            )
            accuracy_row = wilson_by_cell[cell].get("selective_accuracy")
            goal13_accuracy = str(goal13.get("selective_accuracy") or "").strip()
            if accuracy_row is not None and goal13_accuracy and goal13_accuracy != "nan":
                max_diff = max(
                    max_diff,
                    abs(float(goal13_accuracy) - float(accuracy_row["estimate"])),
                )
        checked += 1

    # Cells present in the 13 output but absent from the runs file mean the
    # two inputs describe different experiment grids — refuse silently
    # agreeing on the intersection.
    runs_curve_cells = {cell for cell, diag in cells.items() if diag["mode"] == "curve"}
    extra = sorted(set(by_cell) - runs_curve_cells)
    if extra:
        raise ValueError(
            f"cross-check failed: the 13 points file contains cells {extra} "
            "that are absent from the runs file; inputs describe different "
            "experiment grids"
        )
    if max_diff > CROSSCHECK_TOLERANCE:
        raise ValueError(
            f"cross-check failed: max |difference| between runs-derived and "
            f"13-output operating points is {max_diff!r} > {CROSSCHECK_TOLERANCE!r}"
        )
    return {
        "status": "passed",
        "checked_cells": checked,
        "max_abs_diff": max_diff,
        "files": points_payload.get("files", []),
        "points_path": points_payload.get("points_path"),
        "goal13_path": points_payload.get("goal13_path"),
    }


# ---------------------------------------------------------------------------
# Paired bootstrap (shared resample indices)
# ---------------------------------------------------------------------------

_PACKED_DTYPE = [("score", "f8"), ("correct", "i8"), ("eligible", "?")]


def make_area_statistic(metric: str, universe_n: int):
    """AURC/AUGRC over a resampled packed array (reuses metrics.py math).

    Curve construction and the trapezoid areas come from
    ``independent_eval.metrics``; the coverage axis is rescaled by the
    eligible fraction exactly like ``run_selective_inference
    .goal13_metric_rows`` so the areas use the full frozen task set as
    denominator.  A resample without any eligible row yields NaN (recorded,
    never silently dropped from the replicate file).
    """

    def statistic(sample: np.ndarray) -> float:
        rows = sample[sample["eligible"]]
        if rows.shape[0] == 0:
            return math.nan
        raw_points = selective_metrics.risk_coverage_curve(rows["score"], rows["correct"])
        ratio = rows.shape[0] / universe_n
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
        if metric == "aurc":
            return selective_metrics.aurc(points)
        return selective_metrics.augrc(points)

    return statistic


def pack_cell(
    rows: list[dict[str, str]], universe: list[str], diag: dict[str, Any]
) -> np.ndarray:
    """Pack one method's rows over the shared sample universe.

    ``eligible`` follows the cell operating-point rule (curve mode: numeric
    score AND hard gate; point-only mode: hard gate), so non-eligible rows
    can never be accepted at any threshold inside a resample.
    """
    by_id = {row["sample_id"]: row for row in rows}
    packed = np.zeros(len(universe), dtype=_PACKED_DTYPE)
    eligible_ids = {row["sample_id"] for row in diag["eligible"]}
    for position, sample_id in enumerate(universe):
        row = by_id[sample_id]
        packed[position]["correct"] = parse_flag(row, "correct", f"runs row {sample_id}")
        packed[position]["eligible"] = sample_id in eligible_ids
        if packed[position]["eligible"]:
            packed[position]["score"] = float(row["confidence"])
    return packed


def applicability_status(
    full_diag: dict[str, Any], base_diag: dict[str, Any], n_samples: int
) -> str | None:
    """Reuse the experiment-13 area gate (rsi.MIN_AREA_N / MIN_UNIQUE_SCORES)."""
    for diag in (full_diag, base_diag):
        if diag["mode"] == "point_only":
            return "not_applicable_no_numeric_confidence"
    if n_samples < rsi.MIN_AREA_N:
        return "not_applicable_small_n"
    for diag in (full_diag, base_diag):
        if not diag["complete_score_coverage"]:
            return "not_applicable_incomplete_score_coverage"
        if diag["unique_eligible_scores"] < rsi.MIN_UNIQUE_SCORES:
            return "not_applicable_insufficient_discrete_points"
    return None


def paired_replicate0_delta(
    packed_full: np.ndarray,
    packed_base: np.ndarray,
    statistic,
    seed: int,
) -> float:
    """Re-derive replicate 0 from the shared index stream.

    ``metrics.paired_bootstrap_diff_ci`` draws, for replicate i,
    ``idx = np.random.default_rng(seed).integers(0, n, n)`` in order and
    applies the same ``idx`` to both arrays.  Regenerating the first index
    array and differencing the two statistics must therefore reproduce
    replicate 0 exactly — the production-run proof that the comparison is
    paired (GOAL 18).
    """
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, packed_full.shape[0], packed_full.shape[0])
    return statistic(packed_full[idx]) - statistic(packed_base[idx])


def build_paired_bootstrap(
    groups: dict[tuple[str, str], list[dict[str, str]]],
    cells: dict[tuple[str, str], dict[str, Any]],
    n_replicates: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """ΔAURC / ΔAUGRC (Full − baseline) per (task_type, baseline).

    Pairing guarantee: ``selective_metrics.paired_bootstrap_diff_ci`` is a
    shared-index implementation (see module docstring); the same derived
    seed is used for the AURC and AUGRC calls, so both metrics are differenced
    on the identical resample index stream.
    """
    if n_replicates <= 0:
        raise ValueError("--bootstrap-replicates must be positive")
    tasks = sorted({task for method, task in groups if method == FULL_METHOD_ID})
    present_methods = {method for method, _ in groups}
    baselines = [
        method for method in BASELINE_METHOD_IDS if method in present_methods
    ]
    delta_rows: list[dict[str, Any]] = []
    replicate_rows: list[dict[str, Any]] = []
    pair_info: dict[str, Any] = {"pairs": [], "n_applicable": 0}
    for task_type in tasks:
        full_rows = groups[(FULL_METHOD_ID, task_type)]
        full_universe_ids = {row["sample_id"] for row in full_rows}
        for baseline_id in baselines:
            if (baseline_id, task_type) not in groups:
                continue  # baseline not available for this task type
            base_rows = groups[(baseline_id, task_type)]
            universe = sorted(full_universe_ids & {row["sample_id"] for row in base_rows})
            full_diag = cells[(FULL_METHOD_ID, task_type)]
            base_diag = cells[(baseline_id, task_type)]
            status = applicability_status(full_diag, base_diag, len(universe))
            info = {
                "task_type": task_type,
                "baseline_method_id": baseline_id,
                "n_samples": len(universe),
                "status": status or "applicable",
                "bootstrap_seed": None,
            }
            pair_info["pairs"].append(info)
            if status is not None:
                for metric in METRICS_IN_DELTAS:
                    delta_rows.append(
                        {
                            "task_type": task_type,
                            "baseline_method_id": baseline_id,
                            "metric": metric,
                            "status": status,
                            "n_samples": len(universe),
                            "note": f"area gate reused from run_selective_inference: {status}",
                        }
                    )
                continue
            packed_full = pack_cell(full_rows, universe, full_diag)
            packed_base = pack_cell(base_rows, universe, base_diag)
            seed = derive_seed(SEED_LABEL_TEMPLATE.format(task_type=task_type, baseline=baseline_id))
            info["bootstrap_seed"] = seed
            statistics = {
                metric: make_area_statistic(metric, len(universe))
                for metric in METRICS_IN_DELTAS
            }
            for metric in METRICS_IN_DELTAS:
                result = selective_metrics.paired_bootstrap_diff_ci(
                    packed_full,
                    packed_base,
                    statistics[metric],
                    n_replicates=n_replicates,
                    seed=seed,
                )
                finite = [value for value in result.replicates if math.isfinite(value)]
                if finite:
                    low, high = (
                        float(value)
                        for value in np.percentile(finite, [2.5, 97.5])
                    )
                else:
                    low = high = None
                full_estimate = statistics[metric](packed_full)
                base_estimate = statistics[metric](packed_base)
                delta_rows.append(
                    {
                        "task_type": task_type,
                        "baseline_method_id": baseline_id,
                        "metric": metric,
                        "status": "applicable",
                        "n_samples": len(universe),
                        "n_replicates": n_replicates,
                        "n_valid_replicates": len(finite),
                        "estimate": result.estimate,
                        "ci95_low": low,
                        "ci95_high": high,
                        "full_estimate": full_estimate,
                        "baseline_estimate": base_estimate,
                        "bootstrap_seed": seed,
                        "note": (
                            "paired bootstrap with shared resample indices "
                            "(metrics.paired_bootstrap_diff_ci); Full - baseline; "
                            "negative delta = Full has the smaller area (better)"
                        ),
                    }
                )
                for index, value in enumerate(result.replicates):
                    replicate_rows.append(
                        {
                            "task_type": task_type,
                            "baseline_method_id": baseline_id,
                            "metric": metric,
                            "replicate_index": index,
                            "delta": value,  # NaN resamples persist as 'nan'
                            "bootstrap_seed": seed,
                            "n_samples": len(universe),
                        }
                    )
                # Production-run proof of the shared-index property: replicate 0
                # must equal the difference computed on the regenerated index.
                expected0 = paired_replicate0_delta(
                    packed_full, packed_base, statistics[metric], seed
                )
                actual0 = result.replicates[0]
                same_nan = math.isnan(expected0) == math.isnan(actual0)
                if not same_nan or (
                    not math.isnan(expected0) and abs(expected0 - actual0) > 1e-12
                ):
                    raise AssertionError(
                        f"paired bootstrap is not sharing resample indices for "
                        f"{task_type}/{baseline_id}/{metric}: replicate 0 "
                        f"{actual0!r} != re-derived {expected0!r}"
                    )
            pair_info["n_applicable"] += 1
    return delta_rows, replicate_rows, pair_info


# ---------------------------------------------------------------------------
# McNemar (binary paired outcome)
# ---------------------------------------------------------------------------


def build_mcnemar_rows(
    groups: dict[tuple[str, str], list[dict[str, str]]]
) -> list[dict[str, Any]]:
    """Exact-binomial McNemar on the binary correct/wrong outcome.

    ``b`` = Full correct & baseline wrong; ``c`` = Full wrong & baseline
    correct.  ``scope_adjustment`` applies the strict AFTER_BETTER
    binarisation of design §4.3 (correct = prediction == AFTER_BETTER), which
    the recomputed ``correct`` flag already encodes.  With no discordant
    pairs the exact binomial is trivially 1.0; the row is kept with an
    explicit note (no silent dropping).
    """
    rows: list[dict[str, Any]] = []
    tasks = sorted({task for method, task in groups if method == FULL_METHOD_ID})
    present_methods = {method for method, _ in groups}
    baselines = [m for m in BASELINE_METHOD_IDS if m in present_methods]
    for task_type in tasks:
        full_rows = groups[(FULL_METHOD_ID, task_type)]
        full_correct = {
            row["sample_id"]: parse_flag(row, "correct", "runs") for row in full_rows
        }
        for baseline_id in baselines:
            if (baseline_id, task_type) not in groups:
                continue
            base_correct = {
                row["sample_id"]: parse_flag(row, "correct", "runs")
                for row in groups[(baseline_id, task_type)]
            }
            universe = sorted(set(full_correct) & set(base_correct))
            b = sum(1 for sid in universe if full_correct[sid] and not base_correct[sid])
            c = sum(1 for sid in universe if base_correct[sid] and not full_correct[sid])
            ties = len(universe) - b - c
            if b + c == 0:
                p_value = 1.0
                statistic_value: float | str = 0.0
                method = "exact_binomial"
                note = "no discordant pairs; exact binomial p set to 1.0"
            else:
                result = selective_metrics.mcnemar_test(b, c, exact=True)
                p_value = float(result["p_value"])
                statistic_value = float(result["statistic"])
                method = str(result["method"])
                note = (
                    "binary outcome = correct flag; scope_adjustment applies the "
                    "strict AFTER_BETTER binarisation (design §4.3)"
                    if task_type == "scope_adjustment"
                    else "binary outcome = correct flag on the shared sample set"
                )
            rows.append(
                {
                    "task_type": task_type,
                    "baseline_method_id": baseline_id,
                    "comparison": "full_vs_baseline_correct_flag",
                    "n_pairs": len(universe),
                    "b_full_correct_baseline_wrong": b,
                    "c_full_wrong_baseline_correct": c,
                    "n_discordant": b + c,
                    "statistic": statistic_value,
                    "p_value": p_value,
                    "method": method,
                    "full_wins": b,
                    "full_losses": c,
                    "ties": ties,
                    "note": note,
                }
            )
    return rows


# ---------------------------------------------------------------------------
# Judge agreement summary (reference only — no mathematics recomputed)
# ---------------------------------------------------------------------------


def _parse_value(raw: str) -> float | str:
    text = str(raw).strip()
    try:
        return float(text)
    except ValueError:
        return text


def build_judge_summary(judge_payload: dict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    """Summarise the 08 judge outputs and add task_type=ALL pooling rows.

    ALL rows are unweighted means (or sums for ``n_*`` count metrics) of the
    published per-task values — the agreement statistics themselves are never
    recomputed from raw votes.
    """
    rows: list[dict[str, Any]] = []

    pairwise = judge_payload[JUDGE_PAIRWISE_FILE]
    required = {"task_type", "judge_a", "judge_b", "n_compared", "agreement", "cohens_kappa"}
    missing = required - set(pairwise[0])
    if missing:
        raise ValueError(f"{JUDGE_PAIRWISE_FILE} is missing columns {sorted(missing)}")
    per_pair: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in pairwise:
        rows.append(
            {
                "source_file": JUDGE_PAIRWISE_FILE,
                "kind": "pairwise",
                "task_type": row["task_type"],
                "item": f"{row['judge_a']}_vs_{row['judge_b']}",
                "metric": "agreement",
                "value": _parse_value(row["agreement"]),
                "n": int(row["n_compared"]),
                "note": "",
            }
        )
        rows.append(
            {
                "source_file": JUDGE_PAIRWISE_FILE,
                "kind": "pairwise",
                "task_type": row["task_type"],
                "item": f"{row['judge_a']}_vs_{row['judge_b']}",
                "metric": "cohens_kappa",
                "value": _parse_value(row["cohens_kappa"]),
                "n": int(row["n_compared"]),
                "note": "",
            }
        )
        per_pair[(row["judge_a"], row["judge_b"])].append(row)
    for (judge_a, judge_b), group in sorted(per_pair.items()):
        rows.append(
            {
                "source_file": JUDGE_PAIRWISE_FILE,
                "kind": "pairwise",
                "task_type": "ALL",
                "item": f"{judge_a}_vs_{judge_b}",
                "metric": "agreement",
                "value": _mean([float(row["agreement"]) for row in group]),
                "n": sum(int(row["n_compared"]) for row in group),
                "note": "task_type=ALL: unweighted mean across task rows; not recomputed from raw votes",
            }
        )
        rows.append(
            {
                "source_file": JUDGE_PAIRWISE_FILE,
                "kind": "pairwise",
                "task_type": "ALL",
                "item": f"{judge_a}_vs_{judge_b}",
                "metric": "cohens_kappa",
                "value": _mean([float(row["cohens_kappa"]) for row in group]),
                "n": sum(int(row["n_compared"]) for row in group),
                "note": "task_type=ALL: unweighted mean across task rows; not recomputed from raw votes",
            }
        )

    reliability = judge_payload[JUDGE_RELIABILITY_FILE]
    required = {"task_type", "metric", "value"}
    missing = required - set(reliability[0])
    if missing:
        raise ValueError(f"{JUDGE_RELIABILITY_FILE} is missing columns {sorted(missing)}")
    per_metric: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in reliability:
        value = _parse_value(row["value"])
        rows.append(
            {
                "source_file": JUDGE_RELIABILITY_FILE,
                "kind": "reliability",
                "task_type": row["task_type"],
                "item": "",
                "metric": row["metric"],
                "value": value,
                "n": "",
                "note": "",
            }
        )
        per_metric[row["metric"]].append(row)
    for metric, group in sorted(per_metric.items()):
        values = [str(row["value"]).strip() for row in group]
        numeric: list[float] | None = []
        for value in values:
            parsed = _parse_value(value)
            if isinstance(parsed, float):
                numeric.append(parsed)
            else:
                numeric = None
                break
        if metric.startswith("n_"):
            if numeric is None:
                raise ValueError(
                    f"{JUDGE_RELIABILITY_FILE}: count metric {metric!r} has "
                    f"non-numeric values {values}"
                )
            pooled: float | str = float(sum(numeric))
            note = "task_type=ALL: sum of per-task counts"
        elif numeric is not None:
            pooled = _mean(numeric)
            note = "task_type=ALL: unweighted mean across task rows"
        else:
            pooled = ";".join(sorted({value for value in values}))
            note = "task_type=ALL: distinct published values"
        rows.append(
            {
                "source_file": JUDGE_RELIABILITY_FILE,
                "kind": "reliability",
                "task_type": "ALL",
                "item": "",
                "metric": metric,
                "value": pooled,
                "n": "",
                "note": note,
            }
        )

    lojo = judge_payload[JUDGE_LOJO_FILE]
    required = {"task_type", "judge_removed", "n_tasks", "stability"}
    missing = required - set(lojo[0])
    if missing:
        raise ValueError(f"{JUDGE_LOJO_FILE} is missing columns {sorted(missing)}")
    per_judge: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in lojo:
        rows.append(
            {
                "source_file": JUDGE_LOJO_FILE,
                "kind": "leave_one_judge_out",
                "task_type": row["task_type"],
                "item": f"removed_{row['judge_removed']}",
                "metric": "stability",
                "value": _parse_value(row["stability"]),
                "n": int(row["n_tasks"]),
                "note": "",
            }
        )
        per_judge[row["judge_removed"]].append(row)
    for judge_removed, group in sorted(per_judge.items()):
        rows.append(
            {
                "source_file": JUDGE_LOJO_FILE,
                "kind": "leave_one_judge_out",
                "task_type": "ALL",
                "item": f"removed_{judge_removed}",
                "metric": "stability",
                "value": _mean([float(row["stability"]) for row in group]),
                "n": sum(int(row["n_tasks"]) for row in group),
                "note": "task_type=ALL: unweighted mean across task rows",
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def build_statistical_manifest(
    args: argparse.Namespace,
    runs: list[dict[str, str]],
    reference_info: dict[str, Any],
    crosscheck: dict[str, Any],
    pair_info: dict[str, Any],
    canaries: dict[str, bool],
) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "runs": {
            "path": str(args.runs_path),
            "sha256": sha256_file(args.runs_path),
            "rows": len(runs),
            "role": "primary per-sample data source",
        }
    }
    if reference_info.get("reference_path"):
        inputs["reference"] = {
            "path": reference_info["reference_path"],
            "sha256": sha256_file(Path(reference_info["reference_path"])),
            "mode": reference_info["reference_mode"],
        }
    for judge_name in (JUDGE_PAIRWISE_FILE, JUDGE_RELIABILITY_FILE, JUDGE_LOJO_FILE):
        path = args.judge_dir / judge_name
        inputs[judge_name] = {"path": str(path), "sha256": sha256_file(path)}
    if crosscheck["status"] == "passed":
        inputs["selective_points_crosscheck"] = {
            "points_path": crosscheck.get("points_path"),
            "goal13_path": crosscheck.get("goal13_path"),
            "files": crosscheck.get("files", []),
        }
    seed_labels = {
        f"{pair['task_type']}::{pair['baseline_method_id']}": pair["bootstrap_seed"]
        for pair in pair_info["pairs"]
        if pair["bootstrap_seed"] is not None
    }
    return build_manifest(
        experiment_id="14_statistical_tests",
        seed=MASTER_SEED,
        extra={
            "pipeline": "code/experiment_pipelines/run_statistical_tests.py",
            "goal_section": "GOAL.md section 18 (statistical analysis requirements)",
            "inputs": inputs,
            "seed_policy": {
                "master_seed": MASTER_SEED,
                "derivation": (
                    "derive_seed('paired_bootstrap::{task_type}::{baseline}') = "
                    "SHA-256(label | master_seed)[:8] big-endian mod 2**31 "
                    "(code/independent_eval/_common.py)"
                ),
                "per_pair_seeds": seed_labels,
            },
            "bootstrap": {
                "n_replicates": args.bootstrap_replicates,
                "implementation": (
                    "independent_eval.metrics.paired_bootstrap_diff_ci — shared "
                    "resample indices (idx drawn once per replicate, applied to "
                    "both systems); AURC and AUGRC use the same derived seed and "
                    "therefore the identical index stream"
                ),
                "delta_sign": "Full - baseline (negative delta = Full better on AURC/AUGRC)",
                "per_replicate_output": "PAIRED_BOOTSTRAP_REPLICATES.csv (GOAL 13.2)",
                "area_gate": {
                    "minimum_n": rsi.MIN_AREA_N,
                    "minimum_unique_scores": rsi.MIN_UNIQUE_SCORES,
                    "source": "run_selective_inference constants",
                },
                "applicable_pairs": pair_info["n_applicable"],
                "pairs": pair_info["pairs"],
            },
            "wilson_crosscheck": crosscheck,
            "canaries": canaries,
        },
    )


# ---------------------------------------------------------------------------
# GOAL-18 report (skeleton or --fill)
# ---------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        return repr(value)
    return str(value)


def _wilson_line(row: dict[str, Any]) -> str:
    return (
        f"- `{row['task_type']}` / `{row['method_id']}` ({row['metric']}): "
        f"n={row['n']}, correct={row['correct']}, error={row['error']}, "
        f"estimate={_fmt(row['estimate'])}, "
        f"95% Wilson CI=[{_fmt(row['ci95_low'])}, {_fmt(row['ci95_high'])}]"
    )


def build_report(
    *,
    fill: bool,
    reference_info: dict[str, Any],
    runs_path: Path,
    wilson_rows: list[dict[str, Any]],
    delta_rows: list[dict[str, Any]],
    mcnemar_rows: list[dict[str, Any]],
    judge_rows: list[dict[str, Any]],
    crosscheck: dict[str, Any],
    goal13_rows: list[dict[str, str]],
    n_replicates: int,
) -> str:
    """GOAL-18 report.  Without ``--fill`` every numeric block stays a
    ``<PENDING: ...>`` placeholder; with ``--fill`` the numbers computed in
    this run are embedded automatically (sections without data keep their
    placeholder)."""
    pending = not fill
    lines: list[str] = [
        "# Statistical analysis (experiment 14, GOAL section 18)",
        "",
        f"- Report mode: **{'FILLED' if fill else 'SKELETON'}**"
        + ("" if fill else " (rerun with `--fill` once the production data exists)"),
        f"- Correctness reference: **{reference_info['reference_mode']}**",
        f"- Primary per-sample input: `{runs_path.name}`",
        f"- Bootstrap replicates per comparison: **{n_replicates}** "
        "(fixed seed, shared resample indices, every replicate saved to "
        "`PAIRED_BOOTSTRAP_REPLICATES.csv`)",
        f"- Generated at: {utc_now()}",
        "",
        "## 1. Operating-point table: n / coverage / correct / error / estimate / 95% CI",
        "",
        "GOAL 18 requires, for every method x task cell, the denominator `n`,",
        "the coverage, the raw correct/error counts, the point estimate and a",
        "95% interval.  Coverage (k = accepted, n = full frozen task set) and",
        "post-accept selective accuracy (k = correct, n = accepted) are",
        "reported as separate rows of `WILSON_CI_TABLE.csv` (`metric` column).",
        "",
    ]
    if pending or not wilson_rows:
        lines.append(f"- {PENDING_PLACEHOLDER}")
    else:
        lines.extend(_wilson_line(row) for row in wilson_rows)

    lines += [
        "",
        "## 2. Wilson score intervals",
        "",
        "- Interval type: Wilson score interval (no continuity correction),",
        "  `independent_eval/metrics.py::wilson_ci`; endpoints clipped to [0, 1].",
        "- Chosen for binomial proportions at small n; bootstrap intervals are",
        "  reserved for the curve-area differences below (GOAL 18: choose by",
        "  metric type).",
        (
            ""
            if crosscheck["status"] == "not_requested"
            else f"- Cross-check vs experiment-13 outputs: **{crosscheck['status']}** "
            f"over {crosscheck.get('checked_cells', 0)} cells, max |diff| = "
            f"{_fmt(crosscheck.get('max_abs_diff'))}."
        ),
        "",
        "## 3. Paired bootstrap ΔAURC / ΔAUGRC (Full − baseline)",
        "",
        "- Paired system comparison: both systems are re-evaluated on the",
        "  **same resample index array** in every replicate",
        "  (`metrics.paired_bootstrap_diff_ci` is a shared-index",
        "  implementation); AURC and AUGRC use the identical index stream.",
        f"- {n_replicates} fixed-seed replicates; seed =",
        "  `derive_seed(\"paired_bootstrap::{task_type}::{baseline}\")`.",
        "- ΔAURC/ΔAUGRC = Full − baseline; negative deltas mean Full has the",
        "  smaller area (better).  Percentile 95% CIs over the finite replicates.",
        "- Per-replicate values: `PAIRED_BOOTSTRAP_REPLICATES.csv` (GOAL 13.2:",
        "  replicates are saved, not summary-only).",
        "- Pairs failing the experiment-13 area gate are listed with an",
        "  explicit `not_applicable_*` status instead of being dropped.",
        "",
    ]
    applicable = [row for row in delta_rows if row.get("status") == "applicable"]
    if pending or not applicable:
        lines.append(f"- {PENDING_PLACEHOLDER}")
    else:
        for row in applicable:
            lines.append(
                f"- `{row['task_type']}` vs `{row['baseline_method_id']}` "
                f"({row['metric']}): Δ={_fmt(row['estimate'])}, "
                f"95% CI=[{_fmt(row['ci95_low'])}, {_fmt(row['ci95_high'])}], "
                f"n={row['n_samples']}, valid replicates={row['n_valid_replicates']}"
            )
        non_applicable = [row for row in delta_rows if row.get("status") != "applicable"]
        if non_applicable:
            lines.append(
                "- Not applicable (explicit status): "
                + ", ".join(
                    sorted(
                        {
                            f"{row['task_type']}/{row['baseline_method_id']}={row['status']}"
                            for row in non_applicable
                        }
                    )
                )
            )

    lines += [
        "",
        "## 4. McNemar test (binary paired outcomes)",
        "",
        "- Exact binomial McNemar on the correct/wrong outcome over the shared",
        "  sample set (`metrics.mcnemar_test`, exact binomial tails via scipy).",
        "- `scope_adjustment` uses the strict AFTER_BETTER binarisation",
        "  (design §4.3); win/tie/loss counts are reported alongside b/c.",
        "",
    ]
    if pending or not mcnemar_rows:
        lines.append(f"- {PENDING_PLACEHOLDER}")
    else:
        for row in mcnemar_rows:
            lines.append(
                f"- `{row['task_type']}` vs `{row['baseline_method_id']}`: "
                f"b={row['b_full_correct_baseline_wrong']}, c={row['c_full_wrong_baseline_correct']}, "
                f"n={row['n_pairs']}, statistic={_fmt(row['statistic'])}, "
                f"p={_fmt(row['p_value'])}, win/tie/loss={row['full_wins']}/{row['ties']}/{row['full_losses']}"
            )

    lines += [
        "",
        "## 5. Multi-judge agreement (Fleiss kappa, Krippendorff alpha, LOJO)",
        "",
        "- Summarised by reference from the experiment-08 outputs",
        "  (`JUDGE_RELIABILITY_SUMMARY.csv`: Fleiss kappa and nominal",
        "  Krippendorff alpha; `JUDGE_PAIRWISE_AGREEMENT.csv`: pairwise",
        "  agreement and Cohen's kappa; `LEAVE_ONE_JUDGE_OUT.csv`: stability).",
        "- No agreement statistic is recomputed here; `task_type=ALL` rows are",
        "  unweighted means (or sums for counts) of the published values.",
        "",
    ]
    if pending or not judge_rows:
        lines.append(f"- {PENDING_PLACEHOLDER}")
    else:
        for row in judge_rows:
            if row["task_type"] != "ALL":
                continue
            lines.append(
                f"- [{row['kind']}] {row['item'] or '-'} {row['metric']} = {_fmt(row['value'])}"
                + (f" (n={row['n']})" if row["n"] != "" else "")
            )

    lines += [
        "",
        "## 6. Class imbalance: macro-F1 and per-class precision / recall / F1",
        "",
        "- Accuracy alone is not reported for imbalanced label spaces (GOAL 18).",
        "- Macro-F1 on accepted and on the full denominator below come from",
        "  `<prefix>SELECTIVE_GOAL13_METRICS.csv`",
        "  (`metrics.macro_f1_on_accepted` / `macro_f1_on_full_denominator`).",
        "- Per-class precision / recall / F1 accompany every accuracy-style",
        "  claim in the paper tables (GOAL 18 requirement).",
        "",
    ]
    if pending or not goal13_rows:
        lines.append(f"- {PENDING_PLACEHOLDER}")
    else:
        for row in goal13_rows:
            lines.append(
                f"- `{row['task_type']}` / `{row['method_id']}`: "
                f"macro-F1 on accepted = {row['macro_f1_on_accepted']}, "
                f"macro-F1 on full denominator = {row['macro_f1_on_full_denominator']}"
            )

    lines += [
        "",
        "## 7. Reproducibility",
        "",
        "- Master seed 20260907; per-comparison seeds derived with",
        "  `derive_seed` (SHA-256 of the label and the master seed); the full",
        "  seed table is in `STATISTICAL_ANALYSIS_MANIFEST.json`.",
        "- Input SHA-256 digests are recorded in the manifest.",
        "- Missing inputs are hard errors; no silent fallbacks exist.",
        "",
        "## References",
        "",
        "- Wilson, E. B. (1927). Probable inference, the law of succession, and",
        "  statistical inference. JASA 22, 209–212.",
        "- McNemar, Q. (1947). Note on the sampling error of the difference",
        "  between correlated proportions or percentages. Psychometrika 12, 153–157.",
        "- Fleiss, J. L. (1971). Measuring nominal scale agreement among many",
        "  raters. Psychological Bulletin 76, 378–382.",
        "- Krippendorff, K. Content Analysis: An Introduction to Its Methodology.",
        "- Efron, B., & Tibshirani, R. (1993). An Introduction to the Bootstrap.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Experiment-14 statistical-test pipeline (GOAL.md section 18): "
            "Wilson CIs, paired bootstrap ΔAURC/ΔAUGRC, McNemar tests and the "
            "judge-agreement summary."
        )
    )
    parser.add_argument("--runs-path", type=Path, default=DEFAULT_RUNS_PATH)
    parser.add_argument(
        "--reference",
        choices=REFERENCE_MODES,
        default="imcr_strong",
        help=(
            "correctness source: 'imcr_strong'/'imcr_all' recompute correct "
            "against the IMCR reference (reusing the experiment-13 semantics); "
            "'frozen' uses the correct column recorded in the runs file"
        ),
    )
    parser.add_argument("--imcr-strong-path", type=Path, default=DEFAULT_IMCR_STRONG_PATH)
    parser.add_argument("--imcr-all-path", type=Path, default=DEFAULT_IMCR_ALL_PATH)
    parser.add_argument(
        "--points-dir",
        type=Path,
        default=None,
        help=(
            "experiment-13 output directory used only to cross-check the "
            "Wilson table (e.g. experiments/13_selective_inference_independent/"
            "imcr_strong); optional — the runs file remains the primary source"
        ),
    )
    parser.add_argument(
        "--points-prefix",
        default="",
        help="prefix of the 13 output file names inside --points-dir (e.g. 'imcr_strong_')",
    )
    parser.add_argument("--judge-dir", type=Path, default=DEFAULT_JUDGE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument(
        "--bootstrap-replicates",
        type=int,
        default=PAIRED_BOOTSTRAP_REPLICATES,
        help="paired-bootstrap replicates per (task, baseline) comparison "
        "(testing hook; the production value is 2000)",
    )
    parser.add_argument(
        "--fill",
        action="store_true",
        help="embed the numbers computed in this run into "
        "11_STATISTICAL_ANALYSIS.md instead of leaving <PENDING: ...> "
        "placeholders; use only for the production run",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    outdir = args.output_dir
    outdir.mkdir(parents=True, exist_ok=True)

    runs = load_runs(args.runs_path)
    reference_info = apply_reference(runs, args)
    groups = group_rows(runs)
    points_payload = maybe_load_points_outputs(args.points_dir, args.points_prefix)
    judge_payload = load_judge_files(args.judge_dir)

    wilson_rows, cells = build_wilson_rows(groups)
    crosscheck = crosscheck_with_13_outputs(wilson_rows, cells, points_payload)

    delta_rows, replicate_rows, pair_info = build_paired_bootstrap(
        groups, cells, args.bootstrap_replicates
    )
    mcnemar_rows = build_mcnemar_rows(groups)
    judge_rows = build_judge_summary(judge_payload)

    wilson_path = outdir / "WILSON_CI_TABLE.csv"
    deltas_path = outdir / "PAIRED_BOOTSTRAP_DELTAS.csv"
    replicates_path = outdir / "PAIRED_BOOTSTRAP_REPLICATES.csv"
    mcnemar_path = outdir / "MCNEMAR_TESTS.csv"
    judge_path = outdir / "JUDGE_AGREEMENT_SUMMARY.csv"
    manifest_path = outdir / "STATISTICAL_ANALYSIS_MANIFEST.json"
    report_path = outdir / "11_STATISTICAL_ANALYSIS.md"

    write_csv(wilson_path, wilson_rows, WILSON_FIELDS)
    write_csv(deltas_path, delta_rows, DELTA_FIELDS)
    write_csv(replicates_path, replicate_rows, REPLICATE_FIELDS)
    write_csv(mcnemar_path, mcnemar_rows, MCNEMAR_FIELDS)
    write_csv(judge_path, judge_rows, JUDGE_SUMMARY_FIELDS)

    # ------------------------------------------------------------------
    # Canaries (GOAL-21 audit culture): every claim the pipeline makes is
    # machine-checked before the run is allowed to report PASS.
    # ------------------------------------------------------------------
    coverage_cells = {(row["method_id"], row["task_type"]) for row in wilson_rows if row["metric"] == "coverage"}
    accuracy_cells = {(row["method_id"], row["task_type"]) for row in wilson_rows if row["metric"] == "selective_accuracy"}
    expected_accuracy_cells = {
        cell for cell, diag in cells.items() if diag["n_eligible"] > 0
    }
    applicable_deltas = [row for row in delta_rows if row.get("status") == "applicable"]
    expected_replicates = len(applicable_deltas) * args.bootstrap_replicates
    canaries = {
        "wilson_coverage_row_per_cell": coverage_cells == set(cells),
        "wilson_accuracy_row_iff_accepted": accuracy_cells == expected_accuracy_cells,
        "wilson_crosscheck_ok": crosscheck["status"] in {"passed", "not_requested"},
        "paired_shared_index_replicate0_verified": True,  # build_paired_bootstrap raises otherwise
        "paired_replicates_complete": len(replicate_rows) == expected_replicates,
        "delta_estimate_matches_full_minus_baseline": all(
            abs(float(row["estimate"]) - (float(row["full_estimate"]) - float(row["baseline_estimate"])))
            <= 1e-12
            for row in applicable_deltas
        ),
        "bootstrap_seed_matches_derive_seed": all(
            int(row["bootstrap_seed"])
            == derive_seed(
                SEED_LABEL_TEMPLATE.format(
                    task_type=row["task_type"], baseline=row["baseline_method_id"]
                )
            )
            for row in applicable_deltas
        ),
        "mcnemar_p_in_unit_interval": all(
            0.0 <= float(row["p_value"]) <= 1.0 for row in mcnemar_rows
        ),
        "mcnemar_exact_binomial_only": all(row["method"] == "exact_binomial" for row in mcnemar_rows),
        "judge_all_rows_present": {
            row["kind"] for row in judge_rows if row["task_type"] == "ALL"
        }
        == {"pairwise", "reliability", "leave_one_judge_out"},
    }

    report = build_report(
        fill=args.fill,
        reference_info=reference_info,
        runs_path=args.runs_path,
        wilson_rows=wilson_rows,
        delta_rows=delta_rows,
        mcnemar_rows=mcnemar_rows,
        judge_rows=judge_rows,
        crosscheck=crosscheck,
        goal13_rows=points_payload.get("goal13_rows", []),
        n_replicates=args.bootstrap_replicates,
    )
    report_path.write_text(report, encoding="utf-8")
    canaries["report_written"] = report_path.exists() and report_path.stat().st_size > 0

    manifest = build_statistical_manifest(
        args, runs, reference_info, crosscheck, pair_info, canaries
    )
    write_manifest(manifest, manifest_path)

    if not all(canaries.values()):
        raise AssertionError(f"statistical-analysis audit failed: {canaries}")

    result = {
        "result": "PASS",
        "reference_mode": reference_info["reference_mode"],
        "wilson_rows": len(wilson_rows),
        "delta_rows": len(delta_rows),
        "applicable_delta_pairs": pair_info["n_applicable"],
        "replicate_rows": len(replicate_rows),
        "mcnemar_rows": len(mcnemar_rows),
        "judge_summary_rows": len(judge_rows),
        "report_mode": "filled" if args.fill else "skeleton",
        "crosscheck_status": crosscheck["status"],
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    main()
