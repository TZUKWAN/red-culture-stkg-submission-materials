# -*- coding: utf-8 -*-
"""Task 3 (GOAL Phase 5 / section 11): provenance support-rate sample.

Real source text is resolved along the chain
  research_assertions.fact_id
    -> research_assertion_provenance.evidence_ids_json
       (fallback: integrated_fact_members.evidence_ids_json via source_member_id)
    -> upstream evidence_registry.evidence_text   (real OCR/literature excerpt)

The structured statement itself is NEVER used as source evidence.

Judge-visible output: experiments/12_provenance_validation/PROVENANCE_SUPPORT_SAMPLE.csv
Scoring-only sidecar: PROVENANCE_SUPPORT_METADATA.csv  (carries research_tier)
Manifest:             PROVENANCE_SUPPORT_SAMPLE.manifest.json
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (EXP12, MASTER_SEED, attach_integration, connect_final,
                     db_hashes, derive_seed, now_iso, sha256_file, write_csv,
                     write_manifest)

TASK_NAME = "provenance_support_sample"
QUOTAS = {"strict_semantic": 400, "contextual": 300, "unresolved": 300}
MAX_EVIDENCE_PER_FACT = 2
EVIDENCE_TRUNC = 600

JUDGE_FIELDS = ["sample_id", "fact_id", "subject_name", "predicate", "predicate_label_zh",
                "object_name", "time_label", "time_raw", "place_text",
                "evidence_texts", "source_titles"]
META_FIELDS = ["sample_id", "fact_id", "research_tier", "semantic_status", "confidence",
               "risk_tier", "subject_id", "object_id", "n_provenance_rows",
               "n_evidence_ids", "evidence_ids"]


def main() -> None:
    seed = derive_seed(TASK_NAME)
    rng = random.Random(seed)
    con = connect_final()
    attach_integration(con)
    hashes = db_hashes()

    # ---- member-level evidence fallback map ----------------------------------
    member_ev: dict[str, list[str]] = {}
    for r in con.execute(
        "SELECT source_fact_id, evidence_ids_json FROM up.integrated_fact_members"
        " WHERE evidence_ids_json != '[]'"
    ):
        try:
            member_ev[r["source_fact_id"]] = json.loads(r["evidence_ids_json"])
        except json.JSONDecodeError:
            pass

    # ---- fact -> evidence ids --------------------------------------------------
    fact_ev: dict[str, set[str]] = defaultdict(set)
    fact_nprov: dict[str, int] = defaultdict(int)
    for r in con.execute(
        "SELECT fact_id, source_member_id, evidence_ids_json FROM research_assertion_provenance"
    ):
        fact_nprov[r["fact_id"]] += 1
        try:
            fact_ev[r["fact_id"]].update(json.loads(r["evidence_ids_json"] or "[]"))
        except json.JSONDecodeError:
            pass
        fact_ev[r["fact_id"]].update(member_ev.get(r["source_member_id"], []))

    # ---- assertions -------------------------------------------------------------
    pred_zh = {r["predicate"]: r["label_zh"]
               for r in con.execute("SELECT predicate, label_zh FROM research_relation_contract")}
    by_tier: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in con.execute(
        "SELECT fact_id, subject_id, subject_name, predicate, object_id, object_name,"
        "       normalized_time_label, time_raw, place_raw, province, city, county,"
        "       semantic_status, confidence, risk_tier, research_tier"
        " FROM research_assertions"
    ):
        if fact_ev.get(r["fact_id"]):
            by_tier[r["research_tier"]].append(r)

    availability = {t: len(v) for t, v in by_tier.items()}

    # ---- stratified sampling ------------------------------------------------------
    picked: list[sqlite3.Row] = []
    shortfall = {}
    for tier, quota in QUOTAS.items():
        pool = by_tier.get(tier, [])
        rng.shuffle(pool)
        take = pool[:quota]
        if len(take) < quota:
            shortfall[tier] = {"quota": quota, "available": len(pool)}
        picked.extend(take)

    # ---- batch-fetch evidence text + source title -----------------------------------
    need_ev: set[str] = set()
    for r in picked:
        need_ev.update(list(fact_ev[r["fact_id"]])[: MAX_EVIDENCE_PER_FACT * 2])
    ev_text: dict[str, tuple[str, str]] = {}
    need = sorted(need_ev)
    for i in range(0, len(need), 400):
        chunk = need[i:i + 400]
        marks = ",".join("?" * len(chunk))
        for r in con.execute(
            f"SELECT evidence_id, evidence_text, source_title FROM up.evidence_registry"
            f" WHERE evidence_id IN ({marks}) AND evidence_text IS NOT NULL", chunk):
            ev_text[r["evidence_id"]] = (r["evidence_text"], r["source_title"] or "")

    # ---- rows -------------------------------------------------------------------------
    judge_rows, meta_rows = [], []
    n = 0
    missing_text = 0
    for r in picked:
        n += 1
        sid = f"PRV3-{n:04d}"
        texts, titles = [], []
        for eid in sorted(fact_ev[r["fact_id"]]):
            if eid in ev_text:
                t, ti = ev_text[eid]
                texts.append(t[:EVIDENCE_TRUNC])
                if ti:
                    titles.append(ti)
            if len(texts) >= MAX_EVIDENCE_PER_FACT:
                break
        if not texts:
            missing_text += 1
        place = r["place_raw"] or "/".join(x for x in (r["province"], r["city"], r["county"]) if x)
        judge_rows.append({
            "sample_id": sid, "fact_id": r["fact_id"],
            "subject_name": r["subject_name"], "predicate": r["predicate"],
            "predicate_label_zh": pred_zh.get(r["predicate"], ""),
            "object_name": r["object_name"],
            "time_label": r["normalized_time_label"] or "", "time_raw": r["time_raw"] or "",
            "place_text": place or "",
            "evidence_texts": "\n---\n".join(texts),
            "source_titles": "；".join(sorted(set(titles))),
        })
        meta_rows.append({
            "sample_id": sid, "fact_id": r["fact_id"], "research_tier": r["research_tier"],
            "semantic_status": r["semantic_status"], "confidence": r["confidence"],
            "risk_tier": r["risk_tier"], "subject_id": r["subject_id"], "object_id": r["object_id"],
            "n_provenance_rows": fact_nprov[r["fact_id"]],
            "n_evidence_ids": len(fact_ev[r["fact_id"]]),
            "evidence_ids": json.dumps(sorted(fact_ev[r["fact_id"]]), ensure_ascii=False),
        })

    sample_path = EXP12 / "PROVENANCE_SUPPORT_SAMPLE.csv"
    meta_path = EXP12 / "PROVENANCE_SUPPORT_METADATA.csv"
    write_csv(sample_path, JUDGE_FIELDS, judge_rows)
    write_csv(meta_path, META_FIELDS, meta_rows)

    strata = defaultdict(int)
    for r in picked:
        strata[r["research_tier"]] += 1
    manifest = {
        "experiment_id": "v3_provenance_support_sample",
        "task_name": TASK_NAME,
        "master_seed": MASTER_SEED,
        "derived_seed": seed,
        "timestamp": now_iso(),
        **hashes,
        "row_count": len(judge_rows),
        "quotas": QUOTAS,
        "strata_research_tier": dict(strata),
        "facts_with_real_evidence_available": availability,
        "stratum_shortfalls": shortfall,
        "sampled_rows_without_text": missing_text,
        "source_text_resolution": (
            "research_assertion_provenance.evidence_ids_json "
            "(fallback integrated_fact_members.evidence_ids_json via source_member_id) "
            "-> upstream red_culture_semantic_integration_v1.evidence_registry.evidence_text; "
            "structured statement text never used as evidence"
        ),
        "upstream_db_read_only": True,
        "blinding_note": "research_tier and other production attributes only in PROVENANCE_SUPPORT_METADATA.csv",
        "output_files": {
            sample_path.name: {"path": str(sample_path), "sha256": sha256_file(sample_path), "rows": len(judge_rows)},
            meta_path.name: {"path": str(meta_path), "sha256": sha256_file(meta_path), "rows": len(meta_rows)},
        },
    }
    write_manifest(EXP12, "PROVENANCE_SUPPORT_SAMPLE.manifest.json", manifest)
    print("rows:", len(judge_rows), "strata:", dict(strata))
    print("availability:", availability)
    print("shortfalls:", shortfall, "missing_text:", missing_text)
    con.close()


if __name__ == "__main__":
    main()
