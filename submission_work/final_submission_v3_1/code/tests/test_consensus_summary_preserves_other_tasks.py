# -*- coding: utf-8 -*-
"""test_consensus_summary_preserves_other_tasks.py — 指令 §21 回归测试。

V4_CONSENSUS_SUMMARY.json 必须按任务键增量更新（read-modify-write + 原子写），
单任务共识运行不得抹掉其他任务的既有统计。
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiment_pipelines"))

mod = importlib.import_module("build_imcr_consensus_v31")


def test_summary_update_preserves_other_tasks(tmp_path, monkeypatch):
    summary = tmp_path / "V4_CONSENSUS_SUMMARY.json"
    summary.write_text(
        json.dumps({"scope_revalidation_v2": {"strong": 110, "all": 187},
                    "identity_revalidation_v2": {"strong": 321, "all": 586}},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    # 不真正跑共识：直接调 main 的写盘逻辑等价段——通过 monkeypatch build_rows
    # 与 write_manifest，使 --tasks relation_semantic_v2 只更新 relation 键。
    fake_ctx = {
        "judges": ["A", "B", "C"],
        "ab_map": {},
        "matrix": [],
        "meta": {},
        "tier_counts": {},
        "all_model_ids": set(),
        "results": [],
    }

    def fake_build_rows(task_type):
        return [], [], [], fake_ctx

    monkeypatch.setattr(mod, "build_rows", fake_build_rows)
    monkeypatch.setattr(mod, "OUT", tmp_path)  # 隔离：不得写真实 summary

    captured = {}

    def fake_write_manifest(manifest, path):
        captured["manifest"] = manifest
        Path(path).write_text("{}", encoding="utf-8")
        return str(path)

    monkeypatch.setattr(mod, "write_manifest", fake_write_manifest)

    rc = mod.main(["--tasks", "relation_semantic_v2"])
    assert rc == 0
    data = json.loads(summary.read_text(encoding="utf-8"))
    # relation 键已更新
    assert "relation_semantic_v2" in data
    # scope / identity 键必须保留（§21：禁止整文件覆盖）
    assert data.get("scope_revalidation_v2", {}).get("strong") == 110
    assert data.get("identity_revalidation_v2", {}).get("strong") == 321
