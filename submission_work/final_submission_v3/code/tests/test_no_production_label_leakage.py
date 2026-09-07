"""GOAL 22: test_no_production_label_leakage.py

The blind payload builder must raise LeakageError whenever a blacklisted
production-label field appears — as a dict key at ANY nesting depth, or as
a token embedded inside a string value.
"""

from __future__ import annotations

import pytest

from blind_payload import (
    BLACKLIST_KEYS,
    TASK_SPECS,
    LeakageError,
    ab_assignment,
    assert_no_leakage,
    build_blind_payload,
    scan_for_leakage,
)

SPEC = TASK_SPECS["entity_type"]
AB_SPEC = TASK_SPECS["temporal_spatial_fix"]

CLEAN_RECORD = {
    "task_id": "ET-0001",
    "entity_name": "中共一大",
    "entity_text": "中国共产党第一次全国代表大会于1921年在上海召开。",
    "source_context": "节选自党史文献第12页。",
    "candidate_types": ["Person", "Event", "Organization", "Place", "Document"],
    "type_definitions": {"Event": "具有明确时间地点的历史事件"},
}

# Every key the GOAL (7.1 / 22) names as blinded must trigger the error.
GOAL_NAMED_KEYS = [
    "era_label",
    "gold_label",
    "prediction",
    "final_label",
    "risk_tier",
    "semantic_status",
    "auto_accepted",
    "review_status",
    "lexical_hint",
    "schema_votes",
    "cached_llm_prediction",
    "classifier_prediction",
    "rule_prediction",
    "model_confidence",
    "correctness_flag",
    "canonical_entity_id",
    "merge_status",
    "era",
]


def _clean_payload():
    payload, _meta = build_blind_payload(CLEAN_RECORD, SPEC, seed=1234)
    return payload


def test_clean_record_passes():
    payload = _clean_payload()
    assert payload["task_id"] == "ET-0001"
    assert set(payload) <= {"task_id", *SPEC.allowed_fields}
    # whitelist silently drops non-whitelisted production fields... but the
    # deep scan must still catch them if they are smuggled INSIDE a
    # whitelisted field.


@pytest.mark.parametrize("key", GOAL_NAMED_KEYS)
def test_blacklisted_key_at_top_level(key):
    with pytest.raises(LeakageError):
        assert_no_leakage({"task_id": "x", key: "Person"})


@pytest.mark.parametrize("key", GOAL_NAMED_KEYS)
def test_blacklisted_key_at_any_nesting_depth(key):
    nested = {"task_id": "x", "context": {"deep": {"deeper": [{"deepest": {key: 1}}]}}}
    with pytest.raises(LeakageError):
        assert_no_leakage(nested)


@pytest.mark.parametrize("key", GOAL_NAMED_KEYS)
def test_blacklisted_key_case_and_separator_insensitive(key):
    # "Risk Tier", "RISK-TIER" style cosmetic variants must not bypass.
    variant = key.replace("_", " ").title().replace(" ", "-")
    with pytest.raises(LeakageError):
        assert_no_leakage({"task_id": "x", variant: "high"})


@pytest.mark.parametrize(
    "token",
    [
        "era_label",
        "gold_label",
        "prediction",
        "risk_tier",
        "semantic_status",
        "auto_accepted",
        "schema_votes",
        "lexical_hint",
        "cached_llm_prediction",
        "classifier_prediction",
    ],
)
def test_blacklisted_token_inside_string_value(token):
    record = dict(CLEAN_RECORD)
    record["source_context"] = f"该样本的 {token}=high，仅供人工参考。"
    with pytest.raises(LeakageError):
        build_blind_payload(record, SPEC, seed=1234)


def test_leakage_inside_ab_values():
    record = {
        "task_id": "TS-0001",
        "assertion_text": "某事件发生于1935年。",
        "evidence_excerpts": ["遵义会议于1935年1月召开。"],
        "before": {"relation": "located_in", "note": "含 risk_tier 标注"},
        "after": {"relation": "located_in", "note": "干净"},
    }
    with pytest.raises(LeakageError):
        build_blind_payload(record, AB_SPEC, seed=7)


def test_source_type_conditionally_blacklisted():
    # entity_type spec blinds source_type (it is a signal under evaluation).
    record = dict(CLEAN_RECORD)
    record["source_context"] = {"text": "正文", "source_type": "official"}
    with pytest.raises(LeakageError):
        build_blind_payload(record, SPEC, seed=1)
    # A spec without blind_source_type would tolerate it.
    from blind_payload import TaskSpec

    relaxed = TaskSpec(
        task_type="t",
        allowed_fields=("task_id", "source_context"),
        allowed_labels=("X",),
        blind_source_type=False,
    )
    payload, _ = build_blind_payload(record, relaxed, seed=1)
    assert payload["source_context"]["source_type"] == "official"


def test_payload_never_contains_before_after_strings():
    record = {
        "task_id": "TS-0002",
        "assertion_text": "断言文本",
        "evidence_excerpts": ["证据"],
        "before": {"value": "旧版本"},
        "after": {"value": "新版本"},
    }
    payload, meta = build_blind_payload(record, AB_SPEC, seed=99)
    assert "before" not in payload and "after" not in payload
    assert set(("a", "b")) <= set(payload)
    # the mapping lives only in meta, to be written to a separate file
    assert meta["ab_mapping"] in ({"a": "before", "b": "after"}, {"a": "after", "b": "before"})
    import json

    assert "before" not in json.dumps(payload, ensure_ascii=False)
    assert "after" not in json.dumps(payload, ensure_ascii=False)


def test_scan_reports_violations_without_raising():
    violations = scan_for_leakage({"a": {"risk_tier": "high"}})
    assert violations and "risk" in violations[0].lower()


def test_blacklist_constant_covers_goal_22_names():
    required = {
        "era",
        "era_label",
        "gold_label",
        "prediction",
        "risk_tier",
        "semantic_status",
        "auto_accepted",
        "schema_votes",
        "lexical_hint",
        "cached_llm_prediction",
        "classifier_prediction",
    }
    assert required <= set(BLACKLIST_KEYS)
