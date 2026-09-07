# -*- coding: utf-8 -*-
"""test_pipeline_build_payloads.py — build_judge_payloads.py 离线冒烟测试。

覆盖（GOAL 22）：payload 构建的白名单过滤、黑名单泄漏拦截、A/B 盲化与
独立映射文件、清单（prompt_sha256 / 行数）输出。全部在 tmp_path 上运行，
不触碰真实样本文件，不联网。
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
from blind_payload import (  # noqa: E402
    LeakageError,
    build_blind_payload,
    scan_for_leakage,
)
import build_judge_payloads as bjp  # noqa: E402


def _write_entity_sample(path: Path, n: int = 3, extra_columns: dict | None = None) -> Path:
    fields = ["sample_id", "entity_id", "canonical_name", "aliases_json",
              "context_assertions", "source_excerpt"]
    if extra_columns:
        fields += list(extra_columns.keys())
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for i in range(n):
            row = {
                "sample_id": f"ET-TEST-{i:04d}",
                "entity_id": f"IENT-test{i}",
                "canonical_name": f"测试实体{i}",
                "aliases_json": "[]",
                "context_assertions": f"某事件 —发生于→ 测试实体{i}",
                "source_excerpt": "测试文献节选。",
            }
            if extra_columns:
                row.update({k: v for k, v in extra_columns.items()})
            writer.writerow(row)
    return path


def test_entity_type_payloads_built_and_clean(tmp_path, monkeypatch):
    sample = _write_entity_sample(tmp_path / "sample.csv", n=3)
    monkeypatch.setitem(
        defs.TASK_REGISTRY, "entity_type",
        {"input": sample, "output": "ENTITY_TYPE_PAYLOADS.jsonl", "kind": "csv"},
    )
    entry = bjp.build_task_payloads("entity_type", tmp_path / "out")
    assert entry["rows"] == 3
    assert len(entry["prompt_sha256"]) == 64

    lines = [
        json.loads(l)
        for l in open(entry["payload_file"], encoding="utf-8")
        if l.strip()
    ]
    assert len(lines) == 3
    for line in lines:
        assert line["task_type"] == "entity_type"
        assert line["prompt_version"] == defs.PROMPT_VERSION
        assert line["allowed_labels"] == list(defs.ENTITY_TYPE_LABELS)
        # 白名单之外零字段（task_id 之外恰好 6 个白名单字段）
        assert set(line["payload"]) <= set(defs.PIPELINE_TASK_SPECS["entity_type"].allowed_fields)
        # 深度泄漏扫描：键与值都不得命中黑名单
        assert scan_for_leakage(line) == []


def test_production_columns_never_forwarded(tmp_path, monkeypatch):
    """即使原始 CSV 携带生产标签列，payload 也不得包含（白名单机制）。"""
    sample = _write_entity_sample(
        tmp_path / "sample.csv", n=1,
        extra_columns={"risk_tier": "A", "semantic_status": "auto_accepted",
                       "era_label": "Place"},
    )
    monkeypatch.setitem(
        defs.TASK_REGISTRY, "entity_type",
        {"input": sample, "output": "ENTITY_TYPE_PAYLOADS.jsonl", "kind": "csv"},
    )
    entry = bjp.build_task_payloads("entity_type", tmp_path / "out")
    line = json.loads(open(entry["payload_file"], encoding="utf-8").readline())
    text = json.dumps(line, ensure_ascii=False)
    for token in ("risk_tier", "semantic_status", "era_label", "auto_accepted"):
        assert token not in text


def test_blacklisted_content_raises_leakage_error():
    spec = defs.PIPELINE_TASK_SPECS["entity_type"]
    record = defs.entity_type_record(
        {
            "sample_id": "ET-BAD-1",
            "canonical_name": "坏样本",
            "aliases_json": "[]",
            "context_assertions": "该实体 risk_tier=high，应判 Place",  # 值内嵌黑名单 token
            "source_excerpt": "",
        }
    )
    with pytest.raises(LeakageError):
        build_blind_payload(record, spec, seed=123)


def test_scope_adjustment_ab_blinding(tmp_path, monkeypatch):
    tasks_path = tmp_path / "tasks.jsonl"
    task = {
        "task_id": "SA-TEST-1",
        "fact_id": "IFACT-test",
        "assertion_context": {
            "subject_name": "某组织", "subject_type": "Organization",
            "predicate": "occurred_at", "object_name": "某地", "object_type": "Place",
            "time_raw": "1949年", "time_start": None, "time_end": None,
            "time_precision": "year", "normalized_time_label": "1949年",
            "place_raw": "长江流域", "province": None, "city": None, "county": None,
            # 以下生产字段必须被白名单挡在 payload 之外
            "semantic_status": "model_review", "risk_tier": "C",
            "research_tier": "unresolved",
        },
        "provenance": {"record_count": 1, "source_predicates": ["raw:发生于"]},
        "source_evidence_text": None,
        "source_evidence_text_note": "测试：证据文本未内置。",
        "state_a": {"time_role": "event_occurrence",
                    "time_owner": {"entity_id": "X", "name": "某组织", "type": "Organization"},
                    "space_role": "event_location",
                    "space_owner": {"entity_id": "X", "name": "某组织", "type": "Organization"}},
        "state_b": {"time_role": "relation_validity", "time_owner": None,
                    "space_role": "relation_location", "space_owner": None},
    }
    tasks_path.write_text(json.dumps(task, ensure_ascii=False) + "\n", encoding="utf-8")
    mapping_path = tmp_path / "ab.csv"
    with open(mapping_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["task_id", "fact_id", "state_a_corresponds_to",
                            "state_b_corresponds_to", "derived_seed"])
        writer.writeheader()
        writer.writerow({"task_id": "SA-TEST-1", "fact_id": "IFACT-test",
                         "state_a_corresponds_to": "before",
                         "state_b_corresponds_to": "after", "derived_seed": "1"})
    monkeypatch.setitem(
        defs.TASK_REGISTRY, "scope_adjustment",
        {"input": tasks_path, "ab_mapping_input": mapping_path,
         "output": "SCOPE_ADJUSTMENT_PAYLOADS.jsonl",
         "ab_mapping_output": "SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING.csv",
         "kind": "jsonl"},
    )
    entry = bjp.build_task_payloads("scope_adjustment", tmp_path / "out")
    line = json.loads(open(entry["payload_file"], encoding="utf-8").readline())
    payload_text = json.dumps(line["payload"], ensure_ascii=False)
    # payload 中只有匿名 a/b，绝不出现 before/after 字样或生产字段
    assert "a" in line["payload"] and "b" in line["payload"]
    assert "before" not in payload_text and "after" not in payload_text
    for token in ("semantic_status", "risk_tier", "research_tier"):
        assert token not in payload_text
    # A/B 映射写独立文件
    mapping_rows = list(csv.DictReader(open(entry["ab_mapping_file"], encoding="utf-8")))
    assert mapping_rows[0]["task_id"] == "SA-TEST-1"
    assert {mapping_rows[0]["a"], mapping_rows[0]["b"]} == {"before", "after"}
    # a/b 展示状态确为 before/after 状态之一（内容正确对应）
    state_a_json = json.dumps(
        {"time_role": "event_occurrence", "time_owner": "某组织（Organization）",
         "space_role": "event_location", "space_owner": "某组织（Organization）"},
        ensure_ascii=False, sort_keys=True)
    shown = {"a": line["payload"]["a"], "b": line["payload"]["b"]}
    key_for_before = "a" if mapping_rows[0]["a"] == "before" else "b"
    assert json.dumps(shown[key_for_before], ensure_ascii=False, sort_keys=True) == state_a_json

    # 确定性：同种子重建，a/b 分配不变
    entry2 = bjp.build_task_payloads("scope_adjustment", tmp_path / "out2")
    line2 = json.loads(open(entry2["payload_file"], encoding="utf-8").readline())
    assert line2["payload"]["a"] == line["payload"]["a"]


def test_manifest_written(tmp_path, monkeypatch):
    sample = _write_entity_sample(tmp_path / "sample.csv", n=2)
    monkeypatch.setitem(
        defs.TASK_REGISTRY, "entity_type",
        {"input": sample, "output": "ENTITY_TYPE_PAYLOADS.jsonl", "kind": "csv"},
    )
    monkeypatch.setattr(bjp, "CODE_DIR", Path(__file__).resolve().parent.parent)
    rc = bjp.main(["--tasks", "entity_type", "--out-dir", str(tmp_path / "out")])
    assert rc == 0
    manifest = json.load(open(tmp_path / "out" / "PAYLOAD_BUILD_MANIFEST.json", encoding="utf-8"))
    assert manifest["experiment_id"] == "imcr_payload_build"
    assert manifest["total_rows"] == 2
    assert manifest["tasks"][0]["rows"] == 2
    assert len(manifest["tasks"][0]["prompt_sha256"]) == 64
