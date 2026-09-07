# -*- coding: utf-8 -*-
"""test_judge_concurrency.py — run_judges --workers 并发与 judge_client 传输退避的离线测试。

全程 mock / dry-run，不联网：
* --workers>1 与串行产出相同的 task_id 集合与 OK 状态（顺序无关）；
* --resume 在并发模式下幂等（已有 OK 的 task_id 不重跑、不重复落盘）；
* JudgeClient 对 429 按 Retry-After 有界退避后成功，sleep 被 mock，无 tight loop；
* 不可重试 HTTP 错误（401）立即失败，不消耗重试；
* 超过 max_transport_retries 后记录 TRANSPORT_ERROR。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PIPELINE_DIR = Path(__file__).resolve().parent.parent / "experiment_pipelines"
for _p in (str(PIPELINE_DIR), str(PIPELINE_DIR.parent / "independent_eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import imcr_task_defs as defs  # noqa: E402
import run_judges  # noqa: E402
from judge_client import (  # noqa: E402
    JudgeClient,
    JudgeClientError,
    JudgeConfig,
)

from test_pipeline_run_judges import _make_payloads_dir  # noqa: E402


def _run(tmp_path: Path, workers: int, resume: bool = False) -> Path:
    out_root = tmp_path / "out"
    run_judges.run(
        tmp_path / "payloads",
        out_root,
        dry_run=True,
        judge_names=["A"],
        limit=None,
        resume=resume,
        overwrite=False,
        tasks=["entity_type"],
        temperature=0.0,
        top_p=1.0,
        workers=workers,
    )
    return out_root / "raw_runs" / "entity_type" / "A.jsonl"


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_workers_parallel_matches_serial(tmp_path):
    _make_payloads_dir(tmp_path, n=12)
    serial = _read_lines(_run(tmp_path, workers=1))

    tmp2 = tmp_path / "p2"
    tmp2.mkdir()
    _make_payloads_dir(tmp2, n=12)
    parallel = _read_lines(_run(tmp2, workers=8))

    key = lambda r: (r["task_id"], r["status"], json.dumps(r["parsed_response"], sort_keys=True))
    assert sorted(map(key, serial)) == sorted(map(key, parallel))
    assert all(r["status"] == "OK" for r in parallel)
    assert len(parallel) == 12


def test_workers_resume_idempotent(tmp_path):
    _make_payloads_dir(tmp_path, n=10)
    path = _run(tmp_path, workers=4, resume=True)
    first = _read_lines(path)
    assert len(first) == 10
    # 再跑两次 resume：不应新增任何记录
    _run(tmp_path, workers=4, resume=True)
    _run(tmp_path, workers=1, resume=True)
    assert _read_lines(path) == first


def _fake_ok(task_id: str, allowed_labels):
    return {
        "task_id": task_id,
        "decision": list(allowed_labels)[0],
        "confidence": 0.9,
        "evidence": ["e"],
        "reason_code": "OK",
        "explanation": "x",
        "insufficient_evidence": False,
    }


_CFG = JudgeConfig(name="T", base_url="http://fake.local/v1", api_key="k", model="m")


def test_429_retry_after_backoff_then_success(monkeypatch):
    sleeps: list[float] = []
    calls = {"n": 0}

    def flaky(self, messages, temperature, top_p, seed):
        calls["n"] += 1
        if calls["n"] == 1:
            raise JudgeClientError(
                "HTTP 429 from provider fake.local", status_code=429, retry_after=7.0
            )
        return json.dumps(_fake_ok("T-1", ["L1"]))

    monkeypatch.setattr(JudgeClient, "_http_raw", flaky)
    client = JudgeClient(_CFG, sleep_fn=sleeps.append)
    rec = client.judge("T-1", ["L1"], prompt_version="v1", messages=[{"role": "user", "content": "{}"}])
    assert rec.status == "OK"
    assert sleeps == [7.0]  # 尊重 Retry-After，且只睡一次（无 tight loop）
    assert calls["n"] == 2


def test_429_exponential_backoff_without_retry_after(monkeypatch):
    sleeps: list[float] = []

    def always_429(self, messages, temperature, top_p, seed):
        raise JudgeClientError("HTTP 429 from provider fake.local", status_code=429)

    monkeypatch.setattr(JudgeClient, "_http_raw", always_429)
    client = JudgeClient(_CFG, max_transport_retries=3, sleep_fn=sleeps.append)
    rec = client.judge("T-1", ["L1"], prompt_version="v1", messages=[{"role": "user", "content": "{}"}])
    assert rec.status == "TRANSPORT_ERROR"
    assert sleeps == [2.0, 4.0, 8.0]  # base=2 指数退避，有界


def test_non_retryable_http_fails_immediately(monkeypatch):
    sleeps: list[float] = []
    calls = {"n": 0}

    def unauthorized(self, messages, temperature, top_p, seed):
        calls["n"] += 1
        raise JudgeClientError("HTTP 401 from provider fake.local", status_code=401)

    monkeypatch.setattr(JudgeClient, "_http_raw", unauthorized)
    client = JudgeClient(_CFG, sleep_fn=sleeps.append)
    rec = client.judge("T-1", ["L1"], prompt_version="v1", messages=[{"role": "user", "content": "{}"}])
    assert rec.status == "TRANSPORT_ERROR"
    assert calls["n"] == 1
    assert sleeps == []
