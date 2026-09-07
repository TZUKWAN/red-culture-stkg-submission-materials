#!/usr/bin/env python3
"""Compare a v3 ``--reference era`` replay against the frozen v2 CSVs.

GOAL.md section 13 Phase 7 regression gate: every curve, every point of
``RISK_COVERAGE_POINTS.csv`` / ``RISK_COVERAGE_SUMMARY.csv`` /
``RISK_COVERAGE_BOOTSTRAP.csv`` must match the v2 originals cell by cell
(float tolerance 1e-9; non-numeric cells compared as strings).

Writes ``ERA_REPLAY_PARITY_REPORT.json`` with a per-file, per-curve breakdown
and an overall ``verdict`` (``PASS`` only when every compared cell matches).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
V3_ROOT = SCRIPT.parents[2]
SUBMISSION_WORK = V3_ROOT.parent
DEFAULT_V2_DIR = SUBMISSION_WORK / "final_submission_v2" / "experiments" / "03_selective_inference"
DEFAULT_V3_DIR = V3_ROOT / "experiments" / "13_selective_inference_independent" / "era_replay"

FILES = [
    ("RISK_COVERAGE_POINTS.csv", ("method_id", "task_type", "curve_mode")),
    ("RISK_COVERAGE_SUMMARY.csv", ("method_id", "task_type", "curve_mode")),
    ("RISK_COVERAGE_BOOTSTRAP.csv", ("method_id", "task_type", "curve_mode")),
]


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def as_float(value: str) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def compare_file(
    v2_path: Path, v3_path: Path, curve_keys: tuple[str, ...], tolerance: float
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "v2_path": str(v2_path),
        "v3_path": str(v3_path),
        "verdict": "PASS",
        "mismatches": [],
        "per_curve": {},
    }
    if not v2_path.exists():
        report["verdict"] = "FAIL"
        report["mismatches"].append(f"v2 file missing: {v2_path}")
        return report
    if not v3_path.exists():
        report["verdict"] = "FAIL"
        report["mismatches"].append(f"v3 file missing: {v3_path}")
        return report

    v2_header, v2_rows = read_csv(v2_path)
    v3_header, v3_rows = read_csv(v3_path)
    if v2_header != v3_header:
        report["verdict"] = "FAIL"
        report["mismatches"].append(
            f"header mismatch: v2={v2_header} v3={v3_header}"
        )
        return report
    report["columns"] = len(v2_header)
    if len(v2_rows) != len(v3_rows):
        report["verdict"] = "FAIL"
        report["mismatches"].append(
            f"row count mismatch: v2={len(v2_rows)} v3={len(v3_rows)}"
        )
        return report
    report["rows"] = len(v2_rows)

    def curve_id(row: dict[str, str]) -> str:
        return "|".join(row.get(key, "") for key in curve_keys)

    max_abs_diff = 0.0
    for index, (v2_row, v3_row) in enumerate(zip(v2_rows, v3_rows)):
        curve = curve_id(v2_row)
        curve_state = report["per_curve"].setdefault(
            curve, {"rows": 0, "mismatched_cells": 0, "max_abs_diff": 0.0, "verdict": "PASS"}
        )
        curve_state["rows"] += 1
        if curve_id(v3_row) != curve:
            report["verdict"] = "FAIL"
            curve_state["verdict"] = "FAIL"
            curve_state["mismatched_cells"] += 1
            report["mismatches"].append(
                f"row {index}: curve key mismatch v2={curve!r} v3={curve_id(v3_row)!r}"
            )
            continue
        for column in v2_header:
            left, right = v2_row[column], v3_row[column]
            left_f, right_f = as_float(left), as_float(right)
            if left_f is not None and right_f is not None:
                if math.isnan(left_f) and math.isnan(right_f):
                    continue
                diff = abs(left_f - right_f)
                max_abs_diff = max(max_abs_diff, diff)
                curve_state["max_abs_diff"] = max(curve_state["max_abs_diff"], diff)
                if diff > tolerance:
                    report["verdict"] = "FAIL"
                    curve_state["verdict"] = "FAIL"
                    curve_state["mismatched_cells"] += 1
                    if len(report["mismatches"]) < 50:
                        report["mismatches"].append(
                            f"row {index} column {column}: v2={left!r} v3={right!r} |diff|={diff:.3e}"
                        )
            elif left != right:
                report["verdict"] = "FAIL"
                curve_state["verdict"] = "FAIL"
                curve_state["mismatched_cells"] += 1
                if len(report["mismatches"]) < 50:
                    report["mismatches"].append(
                        f"row {index} column {column}: v2={left!r} v3={right!r}"
                    )
    report["max_abs_diff"] = max_abs_diff
    report["curves"] = len(report["per_curve"])
    report["curves_passing"] = sum(
        state["verdict"] == "PASS" for state in report["per_curve"].values()
    )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v2-dir", type=Path, default=DEFAULT_V2_DIR)
    parser.add_argument("--v3-dir", type=Path, default=DEFAULT_V3_DIR)
    parser.add_argument("--v3-prefix", default="era_")
    parser.add_argument("--tolerance", type=float, default=1e-9)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="report path; defaults to <v3-dir>/ERA_REPLAY_PARITY_REPORT.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    output_path = args.output or (args.v3_dir / "ERA_REPLAY_PARITY_REPORT.json")
    file_reports = {}
    for filename, curve_keys in FILES:
        file_reports[filename] = compare_file(
            args.v2_dir / filename,
            args.v3_dir / f"{args.v3_prefix}{filename}",
            curve_keys,
            args.tolerance,
        )
    verdict = "PASS" if all(r["verdict"] == "PASS" for r in file_reports.values()) else "FAIL"
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "verdict": verdict,
        "tolerance": args.tolerance,
        "v2_dir": str(args.v2_dir),
        "v3_dir": str(args.v3_dir),
        "v3_prefix": args.v3_prefix,
        "files": file_reports,
        "per_curve_verdicts": {
            f"{filename}::{curve}": state["verdict"]
            for filename, file_report in file_reports.items()
            for curve, state in file_report.get("per_curve", {}).items()
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"verdict": verdict, "report": str(output_path)}, ensure_ascii=False))
    return report


if __name__ == "__main__":
    main()
