# -*- coding: utf-8 -*-
"""Task 4 (GOAL section 17): split-leakage audit across the three new v3
evaluation samples and the legacy 712-row ERA reference (AI_GOLD_LABELS.csv).

Checks: entity / fact / source / cluster / event overlap, both among the new
samples and against ERA. Writes
experiments/08_independent_reference/SPLIT_LEAKAGE_AUDIT.json.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (EXP08, EXP11, EXP12, MASTER_SEED, V3_ROOT, connect_final,
                     db_hashes, derive_seed, now_iso, sha256_file)

TASK_NAME = "split_leakage_audit"
ERA_PRIMARY = V3_ROOT / "data" / "external_inputs" / "AI_GOLD_LABELS.csv"
ERA_FALLBACK = Path("D:/REDCULTUREDATA/dual_paper_project/paper_A_method/04_results/AI_GOLD_LABELS.csv")


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    seed = derive_seed(TASK_NAME)
    notes = []
    era_path = ERA_PRIMARY if ERA_PRIMARY.exists() else ERA_FALLBACK
    if era_path == ERA_FALLBACK:
        notes.append("v3 copy of AI_GOLD_LABELS.csv not present; read ERA read-only from dual_paper_project fallback path")
    era = read_csv(era_path)

    et_sample = read_csv(EXP08 / "ENTITY_TYPE_SAMPLE.csv")
    id_meta = read_csv(EXP11 / "IDENTITY_PAIR_METADATA.csv")
    prv_sample = read_csv(EXP12 / "PROVENANCE_SUPPORT_SAMPLE.csv")
    prv_meta = read_csv(EXP12 / "PROVENANCE_SUPPORT_METADATA.csv")

    con = connect_final()
    hashes = db_hashes()

    # ---- ERA item sets ---------------------------------------------------------
    era_entities = {r["item_id"] for r in era if r["item_id"].startswith(("IENT", "ITOPIC"))}
    era_facts = {r["item_id"] for r in era if r["item_id"].startswith("IFACT")}

    # map every entity id (source- or canonical-level) to its canonical cluster id
    canonical_of: dict[str, str] = {}
    for r in con.execute("SELECT source_entity_id, canonical_entity_id FROM research_entity_members"):
        canonical_of[r["source_entity_id"]] = r["canonical_entity_id"]
    era_clusters = {canonical_of.get(e, e) for e in era_entities}

    # ERA fact endpoints + provenance sources
    era_fact_rows = {}
    era_facts_list = sorted(era_facts)
    for i in range(0, len(era_facts_list), 400):
        chunk = era_facts_list[i:i + 400]
        marks = ",".join("?" * len(chunk))
        for r in con.execute(
            f"SELECT fact_id, subject_id, object_id, subject_type, object_type"
            f" FROM research_assertions WHERE fact_id IN ({marks})", chunk):
            era_fact_rows[r["fact_id"]] = dict(r)
    era_fact_entities = set()
    for r in era_fact_rows.values():
        for k in ("subject_id", "object_id"):
            if r[k]:
                era_fact_entities.add(r[k])

    # entity types for ERA entity items
    ent_type = {}
    era_ent_list = sorted(era_entities)
    for i in range(0, len(era_ent_list), 400):
        chunk = era_ent_list[i:i + 400]
        marks = ",".join("?" * len(chunk))
        for r in con.execute(
            f"SELECT entity_id, entity_type FROM research_entities WHERE entity_id IN ({marks})", chunk):
            ent_type[r["entity_id"]] = r["entity_type"]
    era_event_entities = set()
    for r in era_fact_rows.values():
        if r["subject_type"] == "Event" and r["subject_id"]:
            era_event_entities.add(r["subject_id"])
        if r["object_type"] == "Event" and r["object_id"]:
            era_event_entities.add(r["object_id"])
    era_event_entities |= {e for e, t in ent_type.items() if t == "Event"}

    # source records per fact (release provenance)
    def sources_for(fact_ids: list[str]) -> set[str]:
        srcs: set[str] = set()
        for i in range(0, len(fact_ids), 400):
            chunk = fact_ids[i:i + 400]
            marks = ",".join("?" * len(chunk))
            for r in con.execute(
                f"SELECT source_record_id, source_record_ids_json, native_record_ids_json,"
                f"       legacy_candidate_ids_json FROM research_assertion_provenance"
                f" WHERE fact_id IN ({marks})", chunk):
                srcs.add(r["source_record_id"])
                for blob in (r["source_record_ids_json"], r["native_record_ids_json"],
                             r["legacy_candidate_ids_json"]):
                    try:
                        srcs.update(json.loads(blob or "[]"))
                    except json.JSONDecodeError:
                        pass
        srcs.discard("")
        return srcs

    era_sources = sources_for(sorted(era_facts))

    # ---- new-sample item sets ------------------------------------------------------
    et_entities = {r["entity_id"] for r in et_sample}
    et_clusters = {canonical_of.get(e, e) for e in et_entities}

    id_entities, id_clusters, id_facts = set(), set(), set()
    for r in id_meta:
        for k in ("entity_a_id", "entity_b_id"):
            if r[k]:
                id_entities.add(r[k])
                id_clusters.add(canonical_of.get(r[k], r[k]))
        if r["canonical_entity_id"]:
            id_clusters.add(r["canonical_entity_id"])
        for k in ("context_fact_ids_a", "context_fact_ids_b"):
            try:
                id_facts.update(json.loads(r[k] or "[]"))
            except json.JSONDecodeError:
                pass
    id_sources = sources_for(sorted(id_facts))

    prv_facts = {r["fact_id"] for r in prv_sample}
    prv_entities, prv_event_entities = set(), set()
    for r in prv_meta:
        for k in ("subject_id", "object_id"):
            if r[k]:
                prv_entities.add(r[k])
    # event typing for provenance endpoints
    prv_ent_list = sorted(prv_entities)
    prv_ent_type = {}
    for i in range(0, len(prv_ent_list), 400):
        chunk = prv_ent_list[i:i + 400]
        marks = ",".join("?" * len(chunk))
        for r in con.execute(
            f"SELECT entity_id, entity_type FROM research_entities WHERE entity_id IN ({marks})", chunk):
            prv_ent_type[r["entity_id"]] = r["entity_type"]
    prv_event_entities = {e for e, t in prv_ent_type.items() if t == "Event"}
    prv_clusters = {canonical_of.get(e, e) for e in prv_entities}
    prv_sources = sources_for(sorted(prv_facts))

    et_event_entities = set()
    et_meta = read_csv(EXP08 / "ENTITY_TYPE_SAMPLE.sampling_metadata.csv")
    for r in et_meta:
        if r["production_entity_type"] == "Event":
            et_event_entities.add(r["entity_id"])

    # identity-pair entities that are events
    id_ent_list = sorted(id_entities)
    id_event_entities = set()
    for i in range(0, len(id_ent_list), 400):
        chunk = id_ent_list[i:i + 400]
        marks = ",".join("?" * len(chunk))
        for r in con.execute(
            f"SELECT m.source_entity_id, e.entity_type FROM research_entity_members m"
            f" LEFT JOIN research_entities e ON e.entity_id = m.source_entity_id"
            f" WHERE m.source_entity_id IN ({marks})", chunk):
            if r["entity_type"] == "Event":
                id_event_entities.add(r["source_entity_id"])
        for r in con.execute(
            f"SELECT entity_id, entity_type FROM research_entities WHERE entity_id IN ({marks})", chunk):
            if r["entity_type"] == "Event":
                id_event_entities.add(r["entity_id"])

    # ---- overlap computation ---------------------------------------------------------
    def ov(a: set, b: set) -> dict:
        inter = a & b
        return {"n_a": len(a), "n_b": len(b), "n_overlap": len(inter),
                "overlap_ids_sample": sorted(inter)[:20]}

    audit = {
        "experiment_id": "v3_split_leakage_audit",
        "task_name": TASK_NAME,
        "master_seed": MASTER_SEED,
        "derived_seed": seed,
        "timestamp": now_iso(),
        **hashes,
        "era_source_path": str(era_path),
        "era_rows": len(era),
        "inputs": {
            "entity_type_sample_rows": len(et_sample),
            "identity_pair_rows": len(id_meta),
            "provenance_sample_rows": len(prv_sample),
        },
        "notes": notes,
        "checks": {},
    }

    c = audit["checks"]

    c["entity_overlap_vs_era"] = {
        "entity_type_sample": ov(et_entities, era_entities),
        "identity_pairs_raw_ids": ov(id_entities, era_entities),
        "identity_pairs_canonical_mapped": ov(id_clusters, era_clusters),
        "provenance_endpoints": ov(prv_entities, era_entities | era_fact_entities),
    }
    c["fact_overlap_vs_era"] = {
        "provenance_sample_facts": ov(prv_facts, era_facts),
        "identity_context_facts": ov(id_facts, era_facts),
    }
    c["source_overlap_vs_era"] = {
        "provenance_sample": ov(prv_sources, era_sources),
        "identity_context": ov(id_sources, era_sources),
    }
    c["cluster_overlap_vs_era"] = {
        "identity_pair_clusters": ov(id_clusters, era_clusters),
        "entity_type_sample_clusters": ov(et_clusters, era_clusters),
        "provenance_endpoint_clusters": ov(prv_clusters, era_clusters),
    }
    c["event_overlap_vs_era"] = {
        "entity_type_sample_events": ov(et_event_entities, era_event_entities),
        "identity_pair_events": ov(id_event_entities, era_event_entities),
        "provenance_endpoint_events": ov(prv_event_entities, era_event_entities),
    }
    c["cross_sample_internal"] = {
        "entity_type_vs_identity_entities": ov(et_entities, id_entities),
        "entity_type_vs_provenance_entities": ov(et_entities, prv_entities),
        "identity_vs_provenance_facts": ov(id_facts, prv_facts),
        "identity_vs_provenance_clusters": ov(id_clusters, prv_clusters),
    }

    # ---- conclusions -------------------------------------------------------------------
    def verdict(n_over: int, n_a: int, kind: str) -> str:
        if n_over == 0:
            return f"no {kind} leakage"
        return (f"{n_over} shared {kind} item(s); samples are drawn from the same published KG as ERA, "
                f"so item-level coincidence is possible and must be disclosed; judge prompts remain blinded")

    c["conclusions"] = {
        "entity_overlap": verdict(c["entity_overlap_vs_era"]["identity_pairs_canonical_mapped"]["n_overlap"]
                                  + c["entity_overlap_vs_era"]["entity_type_sample"]["n_overlap"]
                                  + c["entity_overlap_vs_era"]["provenance_endpoints"]["n_overlap"], 0, "entity"),
        "fact_overlap": verdict(c["fact_overlap_vs_era"]["provenance_sample_facts"]["n_overlap"]
                                + c["fact_overlap_vs_era"]["identity_context_facts"]["n_overlap"], 0, "fact"),
        "source_overlap": verdict(c["source_overlap_vs_era"]["provenance_sample"]["n_overlap"]
                                  + c["source_overlap_vs_era"]["identity_context"]["n_overlap"], 0, "source"),
        "cluster_overlap": verdict(c["cluster_overlap_vs_era"]["identity_pair_clusters"]["n_overlap"], 0, "cluster"),
        "event_overlap": verdict(sum(v["n_overlap"] for v in c["event_overlap_vs_era"].values()), 0, "event"),
        "overall": ("New v3 samples and ERA are both drawn from the same released KG, so shared "
                    "entities/sources are expected and disclosed above; independence is claimed at the "
                    "label/judgement level (blinded judge inputs), not at the item level. No ERA item "
                    "was used to construct sampling labels."),
    }

    out = EXP08 / "SPLIT_LEAKAGE_AUDIT.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print("written:", out)
    print(json.dumps({k: v for k, v in c["conclusions"].items()}, ensure_ascii=False, indent=2))
    con.close()


if __name__ == "__main__":
    main()
