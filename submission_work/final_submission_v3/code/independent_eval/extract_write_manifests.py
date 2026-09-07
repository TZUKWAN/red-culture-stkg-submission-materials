#!/usr/bin/env python3
"""收尾：回填 SCOPE_ADJUSTMENT_EXTRACTION_AUDIT.json 的 44/112 结论 notes，
并为数据准备阶段全部产出写 .manifest.json（experiment_id、database_sha256、seed、code、timestamp、行数、文件 sha256）。
只新增/更新 v3 自有文件，不碰任何已有文件。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\REDCULTUREDATA\投稿材料_代码数据整理包")
V3 = ROOT / "submission_work" / "final_submission_v3"
MASTER_SEED = 20260907
FINAL_DB_SHA256 = "a199d736b9ec436b3d5f244e874718604b6c84955a505f31f90a3e28c51a9ee7"
SEMANTIC_DB_SHA256 = "fbfb6529335e1c838270c63eee53c92a568c2b075354f7ad5f9d5815b88bb377"

NOW = datetime.now(timezone.utc).isoformat()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def count_rows(p: Path) -> int:
    if p.suffix == ".jsonl":
        with open(p, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    if p.suffix == ".csv":
        with open(p, encoding="utf-8-sig") as f:
            return max(0, sum(1 for _ in f) - 1)
    return -1  # json 审计文件不按行计


def write_manifest(target: Path, experiment_id: str, code_file: str, seed_info: dict, extra: dict | None = None):
    manifest = {
        "manifest_id": f"{target.stem}.manifest",
        "experiment_id": experiment_id,
        "created_at_utc": NOW,
        "target_file": target.name,
        "target_relative_path": target.relative_to(ROOT).as_posix(),
        "target_sha256": sha256_file(target),
        "target_size_bytes": target.stat().st_size,
        "target_rows": count_rows(target),
        "master_seed": MASTER_SEED,
        "derived_seeds": seed_info,
        "code": code_file,
        "databases": {
            "final": {"path": "data/release_databases/red_culture_stkg_final_v2.sqlite", "sha256": FINAL_DB_SHA256},
            "semantic": {"path": "data/release_databases/red_culture_stkg_semantic_v2.sqlite", "sha256": SEMANTIC_DB_SHA256},
        },
        "database_open_mode": "read-only (file:...?mode=ro)",
    }
    if extra:
        manifest.update(extra)
    out = target.with_suffix(target.suffix + ".manifest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("manifest ->", out.name)


def main() -> None:
    # 1) 回填 44/112 结论到 SCOPE_ADJUSTMENT_EXTRACTION_AUDIT.json
    scope_audit_path = V3 / "experiments" / "10_structural_validation" / "SCOPE_ADJUSTMENT_EXTRACTION_AUDIT.json"
    replay_audit_path = V3 / "experiments" / "10_structural_validation" / "STRUCTURAL_REPLAY_AUDIT.json"
    scope_audit = json.loads(scope_audit_path.read_text(encoding="utf-8"))
    replay_audit = json.loads(replay_audit_path.read_text(encoding="utf-8"))
    cross = replay_audit["owner_validity_cross_scope_adjustments"]
    scope_audit["notes"] = [
        "44/112 与 208 的关系（由 extract_relation_contract_replay.py 全库确定性重放核实，详见 STRUCTURAL_REPLAY_AUDIT.json）：",
        f"w/o Role-owner Closure 下全局非法时间 owner={cross['wo_role_owner_invalid_time_owner_count_global']}、非法空间 owner={cross['wo_role_owner_invalid_space_owner_count_global']}，与 v2 报告的 44/112 完全一致（可复现）。",
        f"44 条非法时间 owner 与 112 条非法空间 owner 对应的断言全部落在 208 条 scope_adjustments 内（时间 {cross['invalid_time_owner_in_scope_208']}/44、空间 {cross['invalid_space_owner_in_scope_208']}/112）；任一维度非法共 {cross['scope_208_with_any_invalid_owner']} 条，其中 16 条时间与空间同时非法（44+112-140=16，与 both_time_and_space_changed=16 自洽）。",
        f"208 条中其余 {cross['scope_208_without_invalid_owner']} 条无非法 owner，系其他闭包原因（unknown 角色重分类、context/relation 角色 owner 置空、身份融合后 owner 失效等）。",
        "结论：44/112 是 208 条调整中‘owner 类型非法’子集的诊断计数，二者不是并列数字；44+112=156 ≠ 208 属正常，论文行文不应混用。",
    ]
    scope_audit_path.write_text(json.dumps(scope_audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print("updated SCOPE_ADJUSTMENT_EXTRACTION_AUDIT.json notes")

    # 2) 各产出 manifest
    ev = V3 / "experiments"
    write_manifest(
        ev / "10_structural_validation" / "SCOPE_ADJUSTMENT_TASKS.jsonl",
        "v3-10-structural-validation-scope-adjustments",
        "submission_work/final_submission_v3/code/independent_eval/extract_scope_adjustment_tasks.py",
        {"scope_adjustment_ab_blinding": 11613091355876745079},
    )
    write_manifest(
        ev / "10_structural_validation" / "SCOPE_ADJUSTMENT_AB_MAPPING.csv",
        "v3-10-structural-validation-scope-adjustments",
        "submission_work/final_submission_v3/code/independent_eval/extract_scope_adjustment_tasks.py",
        {"scope_adjustment_ab_blinding": 11613091355876745079},
        {"confidentiality": "盲化映射文件，judge 流程不可见"},
    )
    write_manifest(
        ev / "10_structural_validation" / "SCOPE_ADJUSTMENT_EXTRACTION_AUDIT.json",
        "v3-10-structural-validation-scope-adjustments",
        "submission_work/final_submission_v3/code/independent_eval/extract_scope_adjustment_tasks.py",
        {"scope_adjustment_ab_blinding": 11613091355876745079},
    )
    write_manifest(
        ev / "10_structural_validation" / "RELATION_CONTRACT_CHANGED_SET.csv",
        "v3-10-structural-validation-relation-contract-replay",
        "submission_work/final_submission_v3/code/independent_eval/extract_relation_contract_replay.py",
        {},
        {"deterministic_replay": True},
    )
    write_manifest(
        ev / "10_structural_validation" / "STRUCTURAL_REPLAY_AUDIT.json",
        "v3-10-structural-validation-relation-contract-replay",
        "submission_work/final_submission_v3/code/independent_eval/extract_relation_contract_replay.py",
        {},
    )
    sample_audit = json.loads(
        (ev / "08_independent_reference" / "RELATION_CONTRACT_SAMPLE_AUDIT.json").read_text(encoding="utf-8")
    )
    write_manifest(
        ev / "08_independent_reference" / "RELATION_CONTRACT_SAMPLE.csv",
        "v3-08-independent-reference-relation-contract-sample",
        "submission_work/final_submission_v3/code/independent_eval/sample_relation_contract_sample.py",
        sample_audit["derived_seeds"],
    )
    write_manifest(
        ev / "08_independent_reference" / "RELATION_CONTRACT_SAMPLE_AUDIT.json",
        "v3-08-independent-reference-relation-contract-sample",
        "submission_work/final_submission_v3/code/independent_eval/sample_relation_contract_sample.py",
        sample_audit["derived_seeds"],
    )
    write_manifest(
        V3 / "data" / "external_inputs" / "EXTERNAL_INPUTS_MANIFEST.json",
        "v3-data-preparation-external-inputs",
        "submission_work/final_submission_v3/code/independent_eval/extract_external_inputs_manifest.py",
        {},
    )


if __name__ == "__main__":
    main()
