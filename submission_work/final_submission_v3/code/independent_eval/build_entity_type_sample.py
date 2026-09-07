# -*- coding: utf-8 -*-
"""Task 1 (GOAL 8.1): stratified + targeted entity-type evaluation sample.

Output (judge-safe):  experiments/08_independent_reference/ENTITY_TYPE_SAMPLE.csv
Sidecar (scoring only): ENTITY_TYPE_SAMPLE.sampling_metadata.csv
Manifest:               ENTITY_TYPE_SAMPLE.manifest.json

Judge-visible columns never include the production entity_type, confidence,
risk flags, or any other production-system judgement; those live only in the
sampling-metadata sidecar.
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (EXP08, MASTER_SEED, attach_integration, connect_final,
                     db_hashes, derive_seed, now_iso, sha256_file, write_csv,
                     write_manifest)

TASK_NAME = "entity_type_sample"
TARGET_TOTAL = 400          # within the 300-500 band required by GOAL 8.1
LAYER_FLOOR = 10            # per-type minimum quota (subject to availability)
LAYER_CAP = 60
MAX_CONTEXT_ASSERTIONS = 3

JUDGE_FIELDS = ["sample_id", "entity_id", "canonical_name", "aliases_json",
                "context_assertions", "source_excerpt"]
META_FIELDS = ["sample_id", "entity_id", "production_entity_type", "semantic_family",
               "type_validation_status", "min_member_confidence", "member_risk_tiers",
               "member_risk_flags", "same_name_multi_type", "integrated_member_count",
               "sampling_priority_score", "stratum_quota"]


def main() -> None:
    seed = derive_seed(TASK_NAME)
    rng = random.Random(seed)
    con = connect_final()
    attach_integration(con)

    hashes = db_hashes()

    # ---- load canonical entities -------------------------------------------
    ents = {}
    for r in con.execute(
        "SELECT entity_id, canonical_name, entity_type, semantic_family, aliases_json,"
        "       type_validation_status, integrated_member_count FROM research_entities"
    ):
        ents[r["entity_id"]] = dict(r)

    # ---- aggregate source-level production attributes per canonical ---------
    agg = defaultdict(lambda: {"conf": [], "tiers": set(), "flags": set()})
    for r in con.execute(
        "SELECT m.canonical_entity_id, e.confidence, e.risk_tier, e.risk_flags_json"
        " FROM research_entity_members m"
        " JOIN sem.v2_entities e ON e.entity_id = m.source_entity_id"
    ):
        a = agg[r["canonical_entity_id"]]
        if r["confidence"] is not None:
            a["conf"].append(r["confidence"])
        if r["risk_tier"]:
            a["tiers"].add(r["risk_tier"])
        try:
            a["flags"].update(json.loads(r["risk_flags_json"] or "[]"))
        except json.JSONDecodeError:
            pass

    # ---- same-name-multi-type flag (canonical release graph) ----------------
    name_types = defaultdict(set)
    for e in ents.values():
        name_types[e["canonical_name"]].add(e["entity_type"])
    multi_type_names = {n for n, ts in name_types.items() if len(ts) > 1}

    # ---- priority score ------------------------------------------------------
    def priority(eid: str) -> float:
        e = ents[eid]
        a = agg.get(eid, {"conf": [], "tiers": set(), "flags": set()})
        s = 0.0
        if e["type_validation_status"] == "fallback_unresolved":
            s += 3.0
        if any(f.startswith("unresolved_entity_type") for f in a["flags"]):
            s += 3.0
        if "lexical_source_type_conflict" in a["flags"]:
            s += 2.0
        if e["canonical_name"] in multi_type_names:
            s += 2.0
        if "same_name_multiple_source_types" in a["flags"]:
            s += 1.0
        if a["conf"] and min(a["conf"]) < 0.8:
            s += 1.0
        return s

    # ---- stratified quotas ---------------------------------------------------
    by_type = defaultdict(list)
    for eid, e in ents.items():
        by_type[e["entity_type"]].append(eid)
    total = len(ents)
    big = {t: ids for t, ids in by_type.items() if round(TARGET_TOTAL * len(ids) / total) >= LAYER_FLOOR}
    small = {t: ids for t, ids in by_type.items() if t not in big}
    quotas = {t: min(LAYER_CAP, max(LAYER_FLOOR, 0)) for t in small}  # floor for small
    quotas = {t: LAYER_FLOOR for t in small}
    remaining = TARGET_TOTAL - sum(quotas.values())
    big_total = sum(len(v) for v in big.values())
    for t, ids in big.items():
        quotas[t] = min(LAYER_CAP, max(LAYER_FLOOR, round(remaining * len(ids) / big_total)))

    # ---- select --------------------------------------------------------------
    selected: dict[str, list[str]] = {}
    shortfall = {}
    for t in sorted(by_type):
        ids = by_type[t]
        scored = sorted(ids, key=lambda e: (-priority(e), rng.random()))
        q = quotas.get(t, LAYER_FLOOR)
        take = scored[:q]
        selected[t] = take
        if len(take) < q:
            shortfall[t] = {"quota": q, "available": len(ids)}

    # ---- judge-visible context ----------------------------------------------
    pred_zh = {r["predicate"]: r["label_zh"]
               for r in con.execute("SELECT predicate, label_zh FROM research_relation_contract")}

    def fetch_context(eid: str) -> tuple[list[str], list[str]]:
        rows = con.execute(
            "SELECT fact_id, subject_name, predicate, object_name, normalized_time_label,"
            "       time_raw, place_raw, province, city, county, research_tier"
            " FROM research_assertions WHERE subject_id = ? OR object_id = ?"
            " ORDER BY CASE research_tier WHEN 'strict_semantic' THEN 0"
            "              WHEN 'contextual' THEN 1 ELSE 2 END, fact_id LIMIT ?",
            (eid, eid, MAX_CONTEXT_ASSERTIONS),
        ).fetchall()
        ctx, facts = [], []
        for r in rows:
            lab = pred_zh.get(r["predicate"], r["predicate"])
            t = r["normalized_time_label"] or r["time_raw"] or ""
            p = r["place_raw"] or "/".join(x for x in (r["province"], r["city"], r["county"]) if x)
            s = f"{r['subject_name']} —{lab}→ {r['object_name']}"
            if t:
                s += f"（时间：{t}）"
            if p:
                s += f"（地点：{p}）"
            ctx.append(s)
            facts.append(r["fact_id"])
        return ctx, facts

    def fetch_excerpt(fact_ids: list[str]) -> str:
        if not fact_ids:
            return ""
        marks = ",".join("?" * len(fact_ids))
        ev_ids: list[str] = []
        for r in con.execute(
            f"SELECT p.evidence_ids_json, m.evidence_ids_json AS m_ev"
            f" FROM research_assertion_provenance p"
            f" LEFT JOIN up.integrated_fact_members m ON m.source_fact_id = p.source_member_id"
            f" WHERE p.fact_id IN ({marks})",
            fact_ids,
        ):
            for blob in (r["evidence_ids_json"], r["m_ev"]):
                try:
                    ev_ids.extend(json.loads(blob or "[]"))
                except json.JSONDecodeError:
                    pass
            if ev_ids:
                break
        if not ev_ids:
            return ""
        marks2 = ",".join("?" * len(ev_ids))
        r = con.execute(
            f"SELECT evidence_text FROM up.evidence_registry"
            f" WHERE evidence_id IN ({marks2}) AND evidence_text IS NOT NULL LIMIT 1",
            ev_ids,
        ).fetchone()
        return (r["evidence_text"][:400] if r and r["evidence_text"] else "")

    judge_rows, meta_rows = [], []
    n = 0
    for t in sorted(selected):
        for eid in selected[t]:
            n += 1
            e = ents[eid]
            a = agg.get(eid, {"conf": [], "tiers": set(), "flags": set()})
            ctx, facts = fetch_context(eid)
            excerpt = fetch_excerpt(facts)
            judge_rows.append({
                "sample_id": f"ETV3-{n:04d}",
                "entity_id": eid,
                "canonical_name": e["canonical_name"],
                "aliases_json": e["aliases_json"] or "[]",
                "context_assertions": "\n".join(ctx),
                "source_excerpt": excerpt,
            })
            meta_rows.append({
                "sample_id": f"ETV3-{n:04d}",
                "entity_id": eid,
                "production_entity_type": e["entity_type"],
                "semantic_family": e["semantic_family"],
                "type_validation_status": e["type_validation_status"],
                "min_member_confidence": (min(a["conf"]) if a["conf"] else ""),
                "member_risk_tiers": json.dumps(sorted(a["tiers"]), ensure_ascii=False),
                "member_risk_flags": json.dumps(sorted(a["flags"]), ensure_ascii=False),
                "same_name_multi_type": e["canonical_name"] in multi_type_names,
                "integrated_member_count": e["integrated_member_count"],
                "sampling_priority_score": priority(eid),
                "stratum_quota": quotas.get(t, LAYER_FLOOR),
            })

    sample_path = EXP08 / "ENTITY_TYPE_SAMPLE.csv"
    meta_path = EXP08 / "ENTITY_TYPE_SAMPLE.sampling_metadata.csv"
    write_csv(sample_path, JUDGE_FIELDS, judge_rows)
    write_csv(meta_path, META_FIELDS, meta_rows)

    strata = {t: len(v) for t, v in sorted(selected.items())}
    manifest = {
        "experiment_id": "v3_entity_type_sample",
        "task_name": TASK_NAME,
        "master_seed": MASTER_SEED,
        "derived_seed": seed,
        "timestamp": now_iso(),
        **hashes,
        "row_count": len(judge_rows),
        "target_total": TARGET_TOTAL,
        "strata_entity_type": strata,
        "stratum_shortfalls": shortfall,
        "priority_rule": (
            "fallback_unresolved +3; unresolved_entity_type flag (rule/model conflict) +3; "
            "lexical_source_type_conflict +2; same-name-multi-type in canonical graph +2; "
            "same_name_multiple_source_types +1; min member confidence <0.8 +1; seeded random tiebreak"
        ),
        "judge_visible_fields": JUDGE_FIELDS,
        "blinding_note": "production entity_type/confidence/risk flags only in sampling_metadata sidecar",
        "output_files": {
            p.name: {"path": str(p), "sha256": sha256_file(p), "rows": len(judge_rows) if p == sample_path else len(meta_rows)}
            for p in (sample_path, meta_path)
        },
    }
    write_manifest(EXP08, "ENTITY_TYPE_SAMPLE.manifest.json", manifest)
    print("rows:", len(judge_rows))
    print("strata:", json.dumps(strata, ensure_ascii=False))
    print("shortfalls:", shortfall)
    con.close()


if __name__ == "__main__":
    main()
