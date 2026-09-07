"""GOAL 20 / 7.3 / 19: judge output parsing, validation and bounded retry.

Runs entirely offline via JudgeClient dry-run mode with scripted fake
responders; no network, no real API keys.
"""

from __future__ import annotations

import json

import pytest

from judge_client import (
    MODEL_OUTPUT_INVALID,
    JudgeClient,
    JudgeClientError,
    JudgeConfig,
    extract_json_object,
    load_judge_config,
    validate_judge_output,
)

LABELS = ("SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED")


def _valid_obj(task_id="T-1", decision="SUPPORTED"):
    return {
        "task_id": task_id,
        "decision": decision,
        "confidence": 0.9,
        "evidence": ["证据A"],
        "reason_code": "OK",
        "explanation": "because",
        "insufficient_evidence": False,
    }


# ---------------------------------------------------------------------------
# validate_judge_output
# ---------------------------------------------------------------------------


def test_valid_json_accepted():
    parsed, err = validate_judge_output(json.dumps(_valid_obj()), "T-1", LABELS)
    assert err is None
    assert parsed["decision"] == "SUPPORTED"
    assert parsed["confidence"] == 0.9


def test_code_fence_and_prose_tolerated():
    raw = '好的，结果如下：\n```json\n' + json.dumps(_valid_obj(), ensure_ascii=False) + "\n```\n谢谢"
    parsed, err = validate_judge_output(raw, "T-1", LABELS)
    assert err is None and parsed["decision"] == "SUPPORTED"


def test_not_json_rejected():
    parsed, err = validate_judge_output("I think it is supported.", "T-1", LABELS)
    assert parsed is None and err and "json_extraction_failed" in err


def test_broken_json_rejected():
    parsed, err = validate_judge_output('{"task_id": "T-1", "decision": ', "T-1", LABELS)
    assert parsed is None and err


@pytest.mark.parametrize("missing", ["decision", "confidence", "evidence", "reason_code", "explanation", "insufficient_evidence"])
def test_missing_key_rejected(missing):
    obj = _valid_obj()
    del obj[missing]
    parsed, err = validate_judge_output(json.dumps(obj), "T-1", LABELS)
    assert parsed is None and "missing key" in err


def test_decision_outside_allowed_labels_rejected():
    obj = _valid_obj(decision="TOTALLY_SUPPORTED")  # free-text style label
    parsed, err = validate_judge_output(json.dumps(obj), "T-1", LABELS)
    assert parsed is None and "not in allowed labels" in err


def test_task_id_mismatch_rejected():
    parsed, err = validate_judge_output(json.dumps(_valid_obj(task_id="T-2")), "T-1", LABELS)
    assert parsed is None and "task_id mismatch" in err


@pytest.mark.parametrize("bad_conf", [-0.1, 1.5, "high", True])
def test_confidence_range_and_type(bad_conf):
    obj = _valid_obj()
    obj["confidence"] = bad_conf
    parsed, err = validate_judge_output(json.dumps(obj), "T-1", LABELS)
    assert parsed is None and "confidence" in err


def test_insufficient_evidence_must_be_bool():
    obj = _valid_obj()
    obj["insufficient_evidence"] = 1  # int is not bool
    parsed, err = validate_judge_output(json.dumps(obj), "T-1", LABELS)
    assert parsed is None and "insufficient_evidence" in err


def test_extract_json_object_balanced():
    assert json.loads(extract_json_object('xx {"a": {"b": 1}} yy')) == {"a": {"b": 1}}
    with pytest.raises(ValueError):
        extract_json_object("no object here")
    with pytest.raises(ValueError):
        extract_json_object('{"a": 1')  # unbalanced


# ---------------------------------------------------------------------------
# JudgeClient retry behaviour (dry-run, scripted responder)
# ---------------------------------------------------------------------------


class ScriptedResponder:
    """Returns queued responses in order, then repeats the last one."""

    def __init__(self, queue):
        self.queue = list(queue)
        self.calls = 0

    def __call__(self, task_id, allowed_labels):
        self.calls += 1
        if len(self.queue) > 1:
            return self.queue.pop(0)
        return self.queue[0]


def test_retry_recovers_from_invalid_output():
    responder = ScriptedResponder(["garbage", json.dumps(_valid_obj())])
    client = JudgeClient(dry_run=True, fake_responder=responder, max_retries=3)
    rec = client.judge("T-1", LABELS, prompt_version="v1", payload={"task_id": "T-1"})
    assert rec.status == "OK"
    assert rec.retry_count == 1
    assert rec.validation_error is None
    assert rec.parsed_response["decision"] == "SUPPORTED"
    assert responder.calls == 2


def test_retry_cap_marks_model_output_invalid():
    responder = ScriptedResponder(["bad1", "bad2", "bad3", "bad4"])
    client = JudgeClient(dry_run=True, fake_responder=responder, max_retries=3)
    rec = client.judge("T-1", LABELS, prompt_version="v1", payload={"task_id": "T-1"})
    assert rec.status == MODEL_OUTPUT_INVALID
    assert rec.retry_count == 3  # 1 initial + 3 retries = 4 attempts
    assert responder.calls == 4
    assert rec.parsed_response is None
    assert rec.validation_error is not None
    # the answer is never hand-corrected into a label
    assert rec.parsed_response is None


def test_label_violation_counts_as_invalid_and_retries():
    bad = json.dumps(_valid_obj(decision="NOT_A_LABEL"))
    responder = ScriptedResponder([bad])
    client = JudgeClient(dry_run=True, fake_responder=responder, max_retries=1)
    rec = client.judge("T-1", LABELS, prompt_version="v1", payload={"task_id": "T-1"})
    assert rec.status == MODEL_OUTPUT_INVALID
    assert "not in allowed labels" in rec.validation_error


def test_dry_run_default_is_deterministic():
    c1 = JudgeClient(dry_run=True)
    c2 = JudgeClient(dry_run=True)
    r1 = c1.judge("T-9", LABELS, prompt_version="v1", payload={"task_id": "T-9"})
    r2 = c2.judge("T-9", LABELS, prompt_version="v1", payload={"task_id": "T-9"})
    assert r1.status == r2.status == "OK"
    assert r1.parsed_response == r2.parsed_response
    assert r1.dry_run and r1.model_id == "dry-run-model"


def test_record_contains_all_goal19_fields():
    rec = JudgeClient(dry_run=True).judge(
        "T-1", LABELS, prompt_version="v2", payload={"task_id": "T-1"},
        temperature=0.0, top_p=1.0, seed=7,
    )
    d = rec.to_dict()
    for f in (
        "model_id", "provider", "prompt_version", "temperature", "top_p",
        "seed", "timestamp", "raw_response", "parsed_response",
        "retry_count", "validation_error",
    ):
        assert f in d
    assert d["prompt_version"] == "v2" and d["seed"] == 7
    assert d["temperature"] == 0.0 and d["top_p"] == 1.0


# ---------------------------------------------------------------------------
# Credential handling (GOAL 19)
# ---------------------------------------------------------------------------


def test_config_only_from_env_and_never_serialised():
    env = {
        "JUDGE_A_BASE_URL": "https://api.example.com/v1",
        "JUDGE_A_API_KEY": "sk-secret-123",
        "JUDGE_A_MODEL": "model-x-2025",
    }
    cfg = load_judge_config("A", env)
    assert cfg.model == "model-x-2025"
    assert cfg.provider == "api.example.com"
    assert "sk-secret-123" not in repr(cfg)
    assert "api_key" not in cfg.to_safe_dict()


def test_missing_env_raises_without_values():
    with pytest.raises(JudgeClientError) as excinfo:
        load_judge_config("B", {})
    msg = str(excinfo.value)
    assert "JUDGE_B_API_KEY" in msg


def test_api_key_scrubbed_from_records():
    cfg = JudgeConfig(
        name="A",
        base_url="https://api.example.com/v1",
        api_key="sk-secret-123",
        model="m",
    )
    client = JudgeClient(cfg, dry_run=True,
                         fake_responder=lambda t, l: json.dumps(_valid_obj()))
    rec = client.judge("T-1", LABELS, prompt_version="v1", payload={"task_id": "T-1"})
    blob = rec.to_jsonl()
    assert "sk-secret-123" not in blob


def test_non_dry_run_requires_config():
    with pytest.raises(JudgeClientError):
        JudgeClient(config=None, dry_run=False)
