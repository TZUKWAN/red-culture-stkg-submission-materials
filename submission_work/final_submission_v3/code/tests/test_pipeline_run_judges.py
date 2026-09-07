# -*- coding: utf-8 -*-
"""test_pipeline_run_judges.py — run_judges.py 离线冒烟测试。

覆盖：judge 环境变量发现、未配置时的明确报错、dry-run 确定性、--resume、
--limit、raw 记录 11 项字段（GOAL 19）、API key 不落盘。全程不联网。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PIPELINE_DIR = Path(__file__).resolve().parent.parent / "experiment_pipelines"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

import imcr_task_defs as defs  # noqa: E402
import run_judges  # noqa: E402
from blind_payload import build_blind_payload  # noqa: E402
from judge_client import JudgeClientError  # noqa: E402

#: GOAL 19 节要求的 11 项运行元数据字段
GOAL_11_FIELDS = (
    "model_id", "provider", "prompt_version", "temperature", "top_p", "seed",
    "timestamp", "raw_response", "parsed_response", "retry_count",
    "validation_error",
)


def _make_payloads_dir(tmp_path: Path, task_type: str = "entity_type", n: int = 5) -> Path:
    """用真实 spec 造一个小 payload 文件（标准文件名）。"""
    spec = defs.PIPELINE_TASK_SPECS[task_type]
    payloads_dir = tmp_path / "payloads"
    payloads_dir.mkdir()
    path = payloads_dir / defs.TASK_REGISTRY[task_type]["output"]
    lines = []
    for i in range(n):
        if task_type == "entity_type":
            record = defs.entity_type_record(
                {
                    "sample_id": f"ET-T-{i}",
                    "canonical_name": f"实体{i}",
                    "aliases_json": "[]",
                    "context_assertions": "",
                    "source_excerpt": "",
                }
            )
        else:  # pragma: no cover - 本测试只用 entity_type
            raise ValueError(task_type)
        payload, meta = build_blind_payload(
            record, spec, seed=1, prompt_template=defs.PROMPT_TEMPLATES[task_type]
        )
        lines.append(
            json.dumps(
                {
                    "task_id": meta["task_id"],
                    "task_type": task_type,
                    "prompt_version": meta["prompt_version"],
                    "allowed_labels": meta["allowed_labels"],
                    "prompt_sha256": meta["prompt_sha256"],
                    "payload": payload,
                },
                ensure_ascii=False,
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payloads_dir


def test_discover_judges_dry_run_default_three():
    configs = run_judges.discover_judges(dry_run=True, judge_names=None)
    assert [c.name for c in configs] == ["A", "B", "C"]
    assert all(c.model.startswith("dry-run-model-") for c in configs)


def test_discover_judges_real_mode_requires_env(monkeypatch):
    for name in ("A", "B", "C", "D", "E"):
        for suffix in ("BASE_URL", "API_KEY", "MODEL"):
            monkeypatch.delenv(f"JUDGE_{name}_{suffix}", raising=False)
    with pytest.raises(JudgeClientError) as excinfo:
        run_judges.discover_judges(dry_run=False, judge_names=None)
    assert ".env.example" in str(excinfo.value)


def test_discover_judges_real_mode_partial_env(monkeypatch):
    for name in ("A", "B", "C", "D", "E"):
        for suffix in ("BASE_URL", "API_KEY", "MODEL"):
            monkeypatch.delenv(f"JUDGE_{name}_{suffix}", raising=False)
    monkeypatch.setenv("JUDGE_B_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("JUDGE_B_API_KEY", "secret-key")
    monkeypatch.setenv("JUDGE_B_MODEL", "example-model-1")
    configs = run_judges.discover_judges(dry_run=False, judge_names=None)
    assert [c.name for c in configs] == ["B"]
    assert configs[0].provider == "api.example.com"


def test_dry_run_end_to_end_and_record_fields(tmp_path):
    payloads_dir = _make_payloads_dir(tmp_path, n=5)
    out_root = tmp_path / "out"
    summary = run_judges.run(
        payloads_dir, out_root,
        dry_run=True, judge_names=["A", "B", "C"], limit=None,
        resume=False, overwrite=False, tasks=["entity_type"],
        temperature=0.0, top_p=1.0,
    )
    assert summary["tasks"]["entity_type/A"]["OK"] == 5
    raw_path = out_root / "raw_runs" / "entity_type" / "A.jsonl"
    records = [json.loads(l) for l in open(raw_path, encoding="utf-8")]
    assert len(records) == 5
    for rec in records:
        for field in GOAL_11_FIELDS:
            assert field in rec, f"missing GOAL-19 field {field}"
        assert rec["status"] == "OK"
        assert rec["dry_run"] is True
        assert rec["task_type"] == "entity_type"
        assert rec["parsed_response"]["decision"] in defs.ENTITY_TYPE_LABELS
        # API key 占位符绝不落盘
        assert "dry-run-placeholder" not in json.dumps(rec, ensure_ascii=False)


def test_dry_run_is_deterministic(tmp_path):
    payloads_dir = _make_payloads_dir(tmp_path, n=5)
    kwargs = dict(
        dry_run=True, judge_names=["A", "B", "C"], limit=None,
        resume=False, overwrite=True, tasks=["entity_type"],
        temperature=0.0, top_p=1.0,
    )
    run_judges.run(payloads_dir, tmp_path / "o1", **kwargs)
    run_judges.run(payloads_dir, tmp_path / "o2", **kwargs)
    a = (tmp_path / "o1" / "raw_runs" / "entity_type" / "A.jsonl").read_text(encoding="utf-8")
    b = (tmp_path / "o2" / "raw_runs" / "entity_type" / "A.jsonl").read_text(encoding="utf-8")
    # 时间戳逐行可能相同也可能不同，按 decision 比较
    da = [json.loads(l)["parsed_response"]["decision"] for l in a.splitlines()]
    db = [json.loads(l)["parsed_response"]["decision"] for l in b.splitlines()]
    assert da == db


def test_resume_skips_completed(tmp_path):
    payloads_dir = _make_payloads_dir(tmp_path, n=5)
    out_root = tmp_path / "out"
    kwargs = dict(
        dry_run=True, judge_names=["A"], limit=None,
        resume=False, overwrite=False, tasks=["entity_type"],
        temperature=0.0, top_p=1.0,
    )
    run_judges.run(payloads_dir, out_root, **kwargs)
    summary = run_judges.run(payloads_dir, out_root, **{**kwargs, "resume": True})
    assert summary["tasks"]["entity_type/A"]["SKIPPED"] == 5
    assert summary["tasks"]["entity_type/A"]["n_attempted"] == 0
    # 文件未翻倍
    records = open(out_root / "raw_runs" / "entity_type" / "A.jsonl", encoding="utf-8").read()
    assert len(records.strip().splitlines()) == 5


def test_limit_and_refuse_overwrite(tmp_path):
    payloads_dir = _make_payloads_dir(tmp_path, n=5)
    out_root = tmp_path / "out"
    kwargs = dict(
        dry_run=True, judge_names=["A"], limit=2,
        resume=False, overwrite=False, tasks=["entity_type"],
        temperature=0.0, top_p=1.0,
    )
    run_judges.run(payloads_dir, out_root, **kwargs)
    records = open(out_root / "raw_runs" / "entity_type" / "A.jsonl", encoding="utf-8").read()
    assert len(records.strip().splitlines()) == 2
    # 已有输出且未给 --resume/--overwrite：拒绝运行，保护真实记录
    with pytest.raises(FileExistsError):
        run_judges.run(payloads_dir, out_root, **kwargs)
