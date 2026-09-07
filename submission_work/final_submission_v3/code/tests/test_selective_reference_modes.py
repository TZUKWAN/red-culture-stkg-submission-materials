"""Tests for the ``--reference`` modes of the v3 selective-inference pipeline
(GOAL.md section 13, Phase 7).

Covered behaviour:

* ``--reference imcr_strong`` / ``imcr_all`` raise a clear error when the IMCR
  reference file is missing — there is no silent fallback to ERA, and no
  output files are produced.
* ``--reference era`` writes CSV outputs whose schema is byte-identical to the
  frozen v2 outputs in
  ``final_submission_v2/experiments/03_selective_inference/``.
* ``--reference imcr_strong`` runs end-to-end on a tiny synthetic reference:
  correctness is recomputed against ``reference_label`` (not the ERA gold),
  samples absent from the reference are excluded from the denominator, and
  the ERA gold file is never required in IMCR mode.

All tests run offline on synthetic inputs with a small bootstrap-iteration
count; the production default remains 2000.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
CODE_DIR = TESTS_DIR.parent
for p in (str(CODE_DIR), str(CODE_DIR / "independent_eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

from experiment_pipelines import run_selective_inference as rsi

V2_OUTPUT_DIR = (
    TESTS_DIR.parents[2] / "final_submission_v2" / "experiments" / "03_selective_inference"
)

RUNS_FIELDS = [
    "sample_id",
    "task_type",
    "item_id",
    "split",
    "method_id",
    "method_name",
    "evidence_class",
    "comparison_tier",
    "overlap_status",
    "primary_comparison_eligible",
    "evaluation_eligibility",
    "availability_status",
    "gold_label",
    "prediction",
    "confidence",
    "covered",
    "correct",
    "hard_constraint_pass",
    "constraint_gate_source",
    "safe_correct",
    "actual_llm_calls",
    "source_artifact",
    "note",
]

METHODS = {
    "M2_classifier_only": "Classifier proxy",
    "M6_full_v2_replay": "Full V2 replay",
}
N_SAMPLES = 12
TASK = "entity_type"


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _synthetic_runs() -> list[dict[str, object]]:
    """12 entity_type samples x 2 scored methods; ERA gold is 'Event' for all.

    Sample s12 fails the hard constraint.  All ERA correctness flags are 1
    (predictions equal the ERA gold), so any error appearing under an IMCR
    reference must come from the recomputation against ``reference_label``.
    """
    rows: list[dict[str, object]] = []
    for index in range(N_SAMPLES):
        sample_id = f"ET-s{index + 1:02d}"
        confidence = 0.50 + 0.02 * index
        hard_pass = 0 if index == N_SAMPLES - 1 else 1
        for method_id, method_name in METHODS.items():
            rows.append(
                {
                    "sample_id": sample_id,
                    "task_type": TASK,
                    "item_id": f"IENT-{index:04d}",
                    "split": "test",
                    "method_id": method_id,
                    "method_name": method_name,
                    "evidence_class": "actual_run",
                    "comparison_tier": "shared-channel diagnostic",
                    "overlap_status": "synthetic",
                    "primary_comparison_eligible": 1,
                    "evaluation_eligibility": "core_eligible_task",
                    "availability_status": "available",
                    "gold_label": "Event",
                    "prediction": "Event",
                    "confidence": f"{confidence:.12f}",
                    "covered": 1,
                    "correct": 1,
                    "hard_constraint_pass": hard_pass,
                    "constraint_gate_source": "synthetic gate",
                    "safe_correct": hard_pass,
                    "actual_llm_calls": 0,
                    "source_artifact": "synthetic",
                    "note": "synthetic test row",
                }
            )
    return rows


def _synthetic_reference(cover_last_two: bool = False) -> list[dict[str, object]]:
    """IMCR reference over s01..s10 (s11/s12 uncovered); s03 relabelled."""
    n = N_SAMPLES if cover_last_two else N_SAMPLES - 2
    rows = []
    for index in range(n):
        rows.append(
            {
                "sample_id": f"ET-s{index + 1:02d}",
                "task_type": TASK,
                "reference_label": "Place" if index == 2 else "Event",
                "consensus_tier": "strong_consensus",
            }
        )
    return rows


@pytest.fixture()
def synthetic_inputs(tmp_path: Path) -> dict[str, Path]:
    runs_path = tmp_path / "BASELINE_RUNS.csv"
    _write_csv(runs_path, _synthetic_runs(), RUNS_FIELDS)
    audit_path = tmp_path / "baseline_experiment_audit.json"
    audit_path.write_text(json.dumps({"result": "PASS"}), encoding="utf-8")
    gold_path = tmp_path / "AI_GOLD_LABELS.csv"
    _write_csv(
        gold_path,
        [
            {"sample_id": f"ET-s{i + 1:02d}", "task_type": TASK, "ai_gold": "Event"}
            for i in range(N_SAMPLES)
        ],
        ["sample_id", "task_type", "ai_gold"],
    )
    reference_path = tmp_path / "IMCR_REFERENCE_STRONG.csv"
    _write_csv(
        reference_path,
        _synthetic_reference(),
        ["sample_id", "task_type", "reference_label", "consensus_tier"],
    )
    return {
        "runs": runs_path,
        "audit": audit_path,
        "gold": gold_path,
        "reference": reference_path,
    }


def _run(args: list[str]) -> dict[str, object]:
    return rsi.main(["--bootstrap-iterations", "10", *args])


def test_missing_imcr_reference_errors_no_silent_fallback(
    synthetic_inputs: dict[str, Path], tmp_path: Path
) -> None:
    missing = tmp_path / "NOT_YET_GENERATED.csv"  # judge pipeline has not run
    outdir = tmp_path / "out_missing"
    for mode, flag in (("imcr_strong", "--imcr-strong-path"), ("imcr_all", "--imcr-all-path")):
        with pytest.raises(FileNotFoundError, match="IMCR"):
            _run(
                [
                    "--reference", mode,
                    "--runs-path", str(synthetic_inputs["runs"]),
                    "--baseline-audit-path", str(synthetic_inputs["audit"]),
                    "--gold-path", str(synthetic_inputs["gold"]),
                    flag, str(missing),
                    "--output-dir", str(outdir),
                    "--output-prefix", f"{mode}_",
                ]
            )
        # No fallback to ERA: no curve outputs may have been produced.
        assert not list(outdir.glob("*.csv"))
        assert not list(outdir.glob("*.json"))


def test_imcr_reference_schema_validation(synthetic_inputs: dict[str, Path], tmp_path: Path) -> None:
    bad_reference = tmp_path / "BAD_REFERENCE.csv"
    _write_csv(
        bad_reference,
        [{"sample_id": "ET-s01", "task_type": TASK, "label": "Event"}],
        ["sample_id", "task_type", "label"],
    )
    with pytest.raises(ValueError, match="reference_label"):
        _run(
            [
                "--reference", "imcr_strong",
                "--runs-path", str(synthetic_inputs["runs"]),
                "--baseline-audit-path", str(synthetic_inputs["audit"]),
                "--imcr-strong-path", str(bad_reference),
                "--output-dir", str(tmp_path / "out_bad"),
            ]
        )


@pytest.mark.skipif(not V2_OUTPUT_DIR.is_dir(), reason="v2 frozen outputs not present")
def test_era_mode_schema_matches_v2(synthetic_inputs: dict[str, Path], tmp_path: Path) -> None:
    outdir = tmp_path / "out_era"
    result = _run(
        [
            "--reference", "era",
            "--runs-path", str(synthetic_inputs["runs"]),
            "--baseline-audit-path", str(synthetic_inputs["audit"]),
            "--gold-path", str(synthetic_inputs["gold"]),
            "--output-dir", str(outdir),
            "--output-prefix", "era_",
        ]
    )
    assert result["result"] == "PASS"
    for filename in (
        "RISK_COVERAGE_POINTS.csv",
        "RISK_COVERAGE_SUMMARY.csv",
        "RISK_COVERAGE_BOOTSTRAP.csv",
    ):
        with (V2_OUTPUT_DIR / filename).open(newline="", encoding="utf-8") as handle:
            v2_header = handle.readline().rstrip("\n")
        with (outdir / f"era_{filename}").open(newline="", encoding="utf-8") as handle:
            v3_header = handle.readline().rstrip("\n")
        assert v3_header == v2_header, f"schema drift in {filename}"


def test_imcr_mode_synthetic_reference_end_to_end(
    synthetic_inputs: dict[str, Path], tmp_path: Path
) -> None:
    outdir = tmp_path / "out_imcr"
    result = _run(
        [
            "--reference", "imcr_strong",
            "--runs-path", str(synthetic_inputs["runs"]),
            "--baseline-audit-path", str(synthetic_inputs["audit"]),
            # IMCR mode must not require the ERA gold file at all:
            "--gold-path", str(tmp_path / "DOES_NOT_EXIST.csv"),
            "--imcr-strong-path", str(synthetic_inputs["reference"]),
            "--output-dir", str(outdir),
            "--output-prefix", "imcr_strong_",
        ]
    )
    assert result["result"] == "PASS"
    assert result["reference_mode"] == "imcr_strong"

    with (outdir / "imcr_strong_RISK_COVERAGE_SUMMARY.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        summaries = list(csv.DictReader(handle))
    constrained = [
        row
        for row in summaries
        if row["method_id"] == "M2_classifier_only"
        and row["curve_mode"] == "constrained_selective"
    ]
    assert len(constrained) == 1
    row = constrained[0]
    # s11/s12 are not covered by the reference: denominator shrinks 12 -> 10.
    assert int(row["n_total"]) == N_SAMPLES - 2
    # Correctness recomputed against reference_label: s03 (Place vs predicted
    # Event) is the only error among the 10 covered, hard-passing samples.
    assert float(row["max_coverage"]) == pytest.approx(1.0)
    assert float(row["full_threshold_selective_risk"]) == pytest.approx(0.1)

    # GOAL-13 supplementary metrics are emitted with the metrics.py columns.
    goal13_path = outdir / "imcr_strong_SELECTIVE_GOAL13_METRICS.csv"
    assert goal13_path.exists()
    with goal13_path.open(newline="", encoding="utf-8") as handle:
        goal13 = list(csv.DictReader(handle))
    assert goal13, "GOAL-13 metrics CSV must not be empty"
    for column in ("selective_accuracy", "error_exposure", "macro_f1_on_accepted",
                   "macro_f1_on_full_denominator", "aurc", "augrc"):
        assert column in goal13[0]
    goal13_m2 = [r for r in goal13 if r["method_id"] == "M2_classifier_only"]
    assert len(goal13_m2) == 1
    assert float(goal13_m2[0]["selective_risk"]) == pytest.approx(0.1)
    assert float(goal13_m2[0]["selective_accuracy"]) == pytest.approx(0.9)

    # The audit records the IMCR reference, not the ERA gold, as the input.
    audit = json.loads(
        (outdir / "imcr_strong_risk_coverage_audit.json").read_text(encoding="utf-8")
    )
    assert audit["reference_mode"] == "imcr_strong"
    assert "imcr_reference" in audit["inputs"]
    assert "gold" not in audit["inputs"]
    assert audit["reference_metadata"]["excluded_sample_keys"] == 2


def test_era_and_imcr_modes_disagree_only_via_reference(
    synthetic_inputs: dict[str, Path], tmp_path: Path
) -> None:
    """Same runs: era keeps frozen flags (zero risk), imcr finds the flipped label."""
    common = [
        "--runs-path", str(synthetic_inputs["runs"]),
        "--baseline-audit-path", str(synthetic_inputs["audit"]),
        "--gold-path", str(synthetic_inputs["gold"]),
    ]
    era_dir = tmp_path / "cmp_era"
    _run([*common, "--reference", "era", "--output-dir", str(era_dir), "--output-prefix", "era_"])
    imcr_dir = tmp_path / "cmp_imcr"
    _run(
        [
            *common,
            "--reference", "imcr_strong",
            "--imcr-strong-path", str(synthetic_inputs["reference"]),
            "--output-dir", str(imcr_dir),
            "--output-prefix", "imcr_strong_",
        ]
    )

    def selective_risk(path: Path) -> float:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if (
                    row["method_id"] == "M2_classifier_only"
                    and row["curve_mode"] == "constrained_selective"
                ):
                    return float(row["full_threshold_selective_risk"])
        raise AssertionError("curve summary row not found")

    assert selective_risk(era_dir / "era_RISK_COVERAGE_SUMMARY.csv") == pytest.approx(0.0)
    assert selective_risk(imcr_dir / "imcr_strong_RISK_COVERAGE_SUMMARY.csv") == pytest.approx(0.1)
