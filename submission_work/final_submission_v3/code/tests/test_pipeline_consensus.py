# -*- coding: utf-8 -*-
"""test_pipeline_consensus.py — build_imcr_consensus.py 离线冒烟测试。

覆盖：raw_runs 聚合、3-judge 共识三档（strong/weak/unresolved）、
unresolved 不产生伪标签、A/B 标签解码回 before/after、三个统计 CSV、
manifest、judge 数不是 3/5 时的明确报错。全程离线。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

PIPELINE_DIR = Path(__file__).resolve().parent.parent / "experiment_pipelines"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

import imcr_task_defs as defs  # noqa: E402
import build_imcr_consensus as bic  # noqa: E402


def _write_raw(raw_root: Path, task_type: str, judge: str,
               decisions: dict[str, str | None]) -> None:
    """decisions: task_id -> decision（None 表示 MODEL_OUTPUT_INVALID）。"""
    task_dir = raw_root / task_type
    task_dir.mkdir(parents=True, exist_ok=True)
    path = task_dir / f"{judge}.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for tid, decision in decisions.items():
            rec = {
                "task_id": tid,
                "judge_name": judge,
                "model_id": f"fake-model-{judge.lower()}",
                "provider": "test",
                "prompt_version": defs.PROMPT_VERSION,
                "temperature": 0.0,
                "top_p": 1.0,
                "seed": 1,
                "timestamp": "2026-09-07T00:00:00+00:00",
                "raw_response": "{}",
                "parsed_response": (
                    {"task_id": tid, "decision": decision, "confidence": 0.9,
                     "evidence": [], "reason_code": "TEST", "explanation": "t",
                     "insufficient_evidence": False}
                    if decision is not None else None
                ),
                "retry_count": 0,
                "validation_error": None if decision is not None else "test",
                "status": "OK" if decision is not None else "MODEL_OUTPUT_INVALID",
                "dry_run": True,
                "task_type": task_type,
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))


def _build_identity_fixture(tmp_path: Path) -> Path:
    raw_root = tmp_path / "raw"
    _write_raw(raw_root, "identity_pair", "A",
               {"P1": "same_entity", "P2": "same_entity", "P3": "same_entity",
                "P4": "same_entity", "P5": None})
    _write_raw(raw_root, "identity_pair", "B",
               {"P1": "same_entity", "P2": "same_entity", "P3": "different_entity",
                "P4": "same_entity", "P5": "same_entity"})
    _write_raw(raw_root, "identity_pair", "C",
               {"P1": "same_entity", "P2": "different_entity", "P3": "insufficient_evidence",
                "P4": "insufficient_evidence", "P5": "same_entity"})
    return raw_root


def test_consensus_three_tiers(tmp_path):
    raw_root = _build_identity_fixture(tmp_path)
    out_dir = tmp_path / "out"
    result = bic.run(raw_root, out_dir, tmp_path / "payloads")
    assert result["tasks"][0]["n_strong_consensus"] == 1  # P1 3/3
    assert result["tasks"][0]["n_weak_consensus"] == 3    # P2/P4 2/3, P5 两票有效且一致
    assert result["tasks"][0]["n_unresolved"] == 1        # P3 三票三分

    all_rows = {r["task_id"]: r for r in _read_csv(out_dir / "IMCR_REFERENCE_ALL.csv")}
    strong_rows = {r["task_id"]: r for r in _read_csv(out_dir / "IMCR_REFERENCE_STRONG.csv")}
    assert set(strong_rows) == {"P1"}
    assert strong_rows["P1"]["imcr_label"] == "same_entity"
    # unresolved 绝不进入任何参考集、不产生伪标签
    assert "P3" not in all_rows and "P3" not in strong_rows
    # P5：A 票无效，B/C 两票一致 → weak（无效票不参与多数决）
    assert all_rows["P5"]["consensus_tier"] == "weak_consensus"
    assert all_rows["P5"]["n_valid_votes"] == "2"


def test_ab_label_decoding(tmp_path):
    raw_root = tmp_path / "raw"
    for judge, dec in (("A", "A_BETTER"), ("B", "A_BETTER"), ("C", "B_BETTER")):
        _write_raw(raw_root, "scope_adjustment", judge, {"SA-T-1": dec})
    payloads_dir = tmp_path / "payloads"
    payloads_dir.mkdir()
    with open(payloads_dir / "SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING.csv", "w",
              encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["task_id", "a", "b", "seed"])
        writer.writeheader()
        writer.writerow({"task_id": "SA-T-1", "a": "after", "b": "before", "seed": "1"})
    out_dir = tmp_path / "out"
    bic.run(raw_root, out_dir, payloads_dir)
    rows = _read_csv(out_dir / "IMCR_REFERENCE_ALL.csv")
    assert rows[0]["imcr_label"] == "A_BETTER"           # 原始 a/b 语义保留
    assert rows[0]["imcr_label_decoded"] == "AFTER_BETTER"  # a 展示位对应 after


def test_statistics_csvs_and_manifest(tmp_path):
    raw_root = _build_identity_fixture(tmp_path)
    out_dir = tmp_path / "out"
    bic.run(raw_root, out_dir, tmp_path / "payloads")

    pair_rows = _read_csv(out_dir / "JUDGE_PAIRWISE_AGREEMENT.csv")
    assert {(r["judge_a"], r["judge_b"]) for r in pair_rows} == {
        ("A", "B"), ("A", "C"), ("B", "C")}
    assert all("cohens_kappa" in r for r in pair_rows)

    rel = {r["metric"]: r["value"] for r in _read_csv(out_dir / "JUDGE_RELIABILITY_SUMMARY.csv")}
    for metric in ("n_tasks", "fleiss_kappa", "krippendorff_alpha_nominal",
                   "mean_pairwise_agreement"):
        assert metric in rel
    assert rel["n_tasks"] == "5"

    loo_rows = _read_csv(out_dir / "LEAVE_ONE_JUDGE_OUT.csv")
    assert {r["judge_removed"] for r in loo_rows} == {"A", "B", "C"}

    manifest = json.load(open(out_dir / "IMCR_CONSENSUS_MANIFEST.json", encoding="utf-8"))
    assert manifest["experiment_id"] == "imcr_consensus_build"
    assert manifest["dry_run"] is True
    assert set(manifest["model_ids"]) == {"fake-model-a", "fake-model-b", "fake-model-c"}
    for name in ("IMCR_REFERENCE_STRONG.csv", "IMCR_REFERENCE_ALL.csv",
                 "JUDGE_PAIRWISE_AGREEMENT.csv", "JUDGE_RELIABILITY_SUMMARY.csv",
                 "LEAVE_ONE_JUDGE_OUT.csv"):
        assert len(manifest["output_files"][name]) == 64


def test_wrong_judge_count_rejected(tmp_path):
    raw_root = tmp_path / "raw"
    for judge in ("A", "B", "C", "D"):  # 4 个 judge：GOAL 7.4 未定义
        _write_raw(raw_root, "identity_pair", judge, {"P1": "same_entity"})
    with pytest.raises(ValueError, match="3 或 5"):
        bic.run(raw_root, tmp_path / "out", tmp_path / "payloads")


def test_missing_raw_root_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        bic.run(tmp_path / "nonexistent", tmp_path / "out", tmp_path / "payloads")
