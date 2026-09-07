"""GOAL 7.1: before/after A/B randomisation.

Same seed + task_id -> same order; across many task_ids the two orders are
roughly balanced; the a/b mapping is invertible; the payload itself never
contains the words before/after.
"""

from __future__ import annotations

import json

from blind_payload import (
    TASK_SPECS,
    ab_assignment,
    build_blind_payload,
    invert_ab_assignment,
    write_ab_mapping,
)

AB_SPEC = TASK_SPECS["temporal_spatial_fix"]


def _record(task_id):
    return {
        "task_id": task_id,
        "assertion_text": f"断言 {task_id}",
        "evidence_excerpts": ["证据甲", "证据乙"],
        "before": {"span": "旧版本文本"},
        "after": {"span": "新版本文本"},
    }


def test_same_seed_same_order():
    for tid in ("TS-1", "TS-2", "TS-99"):
        m1 = ab_assignment(tid, seed=2026)
        m2 = ab_assignment(tid, seed=2026)
        assert m1 == m2
        assert set(m1) == {"a", "b"}
        assert set(m1.values()) == {"before", "after"}


def test_different_seeds_can_flip_order():
    outcomes = {ab_assignment("TS-1", seed=s)["a"] for s in range(50)}
    assert outcomes == {"before", "after"}


def test_distribution_balanced_across_task_ids():
    counts = {"before": 0, "after": 0}
    n = 400
    for i in range(n):
        m = ab_assignment(f"TS-{i:04d}", seed=2026)
        counts[m["a"]] += 1
    # deterministic hash -> fixed split; require rough balance (40%-60%)
    assert 0.40 * n <= counts["before"] <= 0.60 * n


def test_mapping_invertible():
    m = ab_assignment("TS-77", seed=5)
    inv = invert_ab_assignment(m)
    assert inv == {"before": "a" if m["a"] == "before" else "b",
                   "after": "b" if m["b"] == "after" else "a"}
    assert invert_ab_assignment(inv) == m


def test_payload_uses_ab_and_carries_no_before_after():
    payload, meta = build_blind_payload(_record("TS-5"), AB_SPEC, seed=2026)
    blob = json.dumps(payload, ensure_ascii=False)
    assert "before" not in blob and "after" not in blob
    assert set(payload["a"]) == {"span"}
    mapping = meta["ab_mapping"]
    # the anonymised slots resolve back to the original values
    originals = {"before": {"span": "旧版本文本"}, "after": {"span": "新版本文本"}}
    assert payload["a"] == originals[mapping["a"]]
    assert payload["b"] == originals[mapping["b"]]


def test_ab_mapping_file_written_separately(tmp_path):
    records = []
    for i in range(10):
        tid = f"TS-{i}"
        m = ab_assignment(tid, seed=42)
        records.append({"task_id": tid, "a": m["a"], "b": m["b"], "seed": 42})
    path = tmp_path / "AB_MAPPING.csv"
    write_ab_mapping(records, str(path))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "task_id,a,b,seed"
    assert len(lines) == 11
    # mapping file reproduces the deterministic assignments exactly
    for line in lines[1:]:
        tid, a, b, seed = line.split(",")
        m = ab_assignment(tid, seed=int(seed))
        assert m == {"a": a, "b": b}
