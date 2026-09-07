# -*- coding: utf-8 -*-
"""Read-back validation for the v3 data-preparation outputs (tasks 1-4).

Asserts: files parse, row counts hit their targets, judge-visible files carry
no production/leakage fields, and manifest hashes match the files on disk.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

V3 = Path(__file__).resolve().parents[2]
EXP08 = V3 / "experiments" / "08_independent_reference"
EXP11 = V3 / "experiments" / "11_identity_validation"
EXP12 = V3 / "experiments" / "12_provenance_validation"

FORBIDDEN_HEADER_TOKENS = [
    "canonical_entity_id", "mapping_status", "merge_status", "true_merge_status",
    "entity_type", "production", "research_tier", "risk_tier", "risk_flag",
    "confidence", "type_validation_status", "semantic_status", "priority",
]
FORBIDDEN_VALUE_TOKENS = ["canonical_entity_id", "mapping_status", "true_merge_status"]

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()


def read_csv(p: Path):
    with open(p, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        return rows, rows[0].keys() if rows else []


def check_blind(header, rows, label: str) -> None:
    bad_h = [h for h in header for tok in FORBIDDEN_HEADER_TOKENS if tok in h.lower()]
    check(not bad_h, f"{label}: judge header free of production fields (bad={bad_h})")
    bad_cells = 0
    for r in rows:
        for v in r.values():
            if isinstance(v, str) and any(tok in v for tok in FORBIDDEN_VALUE_TOKENS):
                bad_cells += 1
                break
    check(bad_cells == 0, f"{label}: judge cell values free of leakage tokens (bad_rows={bad_cells})")


def check_manifest(p: Path, label: str) -> None:
    m = json.load(open(p, encoding="utf-8"))
    for fname, info in m["output_files"].items():
        ok = sha256(Path(info["path"])) == info["sha256"]
        check(ok, f"{label}: manifest sha256 matches for {fname}")
    check(bool(m.get("derived_seed")) and m.get("master_seed") == 20260907,
          f"{label}: manifest records master+derived seed")
    check("final_db_sha256" in m, f"{label}: manifest records database_sha256")


# ---- Task 1 -----------------------------------------------------------------
rows, header = read_csv(EXP08 / "ENTITY_TYPE_SAMPLE.csv")
check(300 <= len(rows) <= 500, f"entity-type sample rows in [300,500]: {len(rows)}")
check_blind(header, rows, "ENTITY_TYPE_SAMPLE")
check_manifest(EXP08 / "ENTITY_TYPE_SAMPLE.manifest.json", "ENTITY_TYPE_SAMPLE")
m1 = json.load(open(EXP08 / "ENTITY_TYPE_SAMPLE.manifest.json", encoding="utf-8"))
check(m1["row_count"] == len(rows), "ENTITY_TYPE_SAMPLE manifest row_count matches")
meta1, _ = read_csv(EXP08 / "ENTITY_TYPE_SAMPLE.sampling_metadata.csv")
check(len(meta1) == len(rows), "sampling metadata row count matches sample")

# ---- Task 2 -----------------------------------------------------------------
tasks = [json.loads(l) for l in open(EXP11 / "IDENTITY_PAIR_TASKS.jsonl", encoding="utf-8")]
meta2, mh2 = read_csv(EXP11 / "IDENTITY_PAIR_METADATA.csv")
check(len(tasks) == len(meta2), f"identity tasks/metadata row counts match: {len(tasks)}/{len(meta2)}")
npos = sum(1 for r in meta2 if r["pair_kind"] == "positive_merge_candidate")
nneg = len(meta2) - npos
check(200 <= npos <= 400 and 200 <= nneg <= 400, f"pos/neg in [200,400]: {npos}/{nneg}")
check_blind(tasks[0].keys(), tasks, "IDENTITY_PAIR_TASKS")
allowed_keys = {"pair_id", "name_a", "name_b", "aliases_a", "aliases_b",
                "relation_context_a", "relation_context_b", "time_info_a", "time_info_b",
                "space_info_a", "space_info_b", "evidence_a", "evidence_b"}
check(all(set(t.keys()) <= allowed_keys for t in tasks), "IDENTITY_PAIR_TASKS keys restricted to blinded field set")
check_manifest(EXP11 / "IDENTITY_PAIR_TASKS.manifest.json", "IDENTITY_PAIR_TASKS")

# ---- Task 3 -----------------------------------------------------------------
rows3, h3 = read_csv(EXP12 / "PROVENANCE_SUPPORT_SAMPLE.csv")
check(len(rows3) >= 500, f"provenance sample rows >=500: {len(rows3)}")
check(len(rows3) == 1000, f"provenance sample hit preferred 1000: {len(rows3)}")
meta3, _ = read_csv(EXP12 / "PROVENANCE_SUPPORT_METADATA.csv")
from collections import Counter
tiers = Counter(r["research_tier"] for r in meta3)
check(tiers == {"strict_semantic": 400, "contextual": 300, "unresolved": 300},
      f"provenance strata match quotas: {dict(tiers)}")
check(all(r["evidence_texts"].strip() for r in rows3), "every provenance row has real source text")
check_blind(h3, rows3, "PROVENANCE_SUPPORT_SAMPLE")
check_manifest(EXP12 / "PROVENANCE_SUPPORT_SAMPLE.manifest.json", "PROVENANCE_SUPPORT_SAMPLE")

# ---- Task 4 -----------------------------------------------------------------
audit = json.load(open(EXP08 / "SPLIT_LEAKAGE_AUDIT.json", encoding="utf-8"))
need = {"entity_overlap_vs_era", "fact_overlap_vs_era", "source_overlap_vs_era",
        "cluster_overlap_vs_era", "event_overlap_vs_era", "conclusions"}
check(need <= set(audit["checks"]) , "SPLIT_LEAKAGE_AUDIT covers all five overlap checks + conclusions")

print()
if failures:
    print(f"VALIDATION FAILED: {len(failures)} problem(s)")
    sys.exit(1)
print("ALL VALIDATION CHECKS PASSED")
