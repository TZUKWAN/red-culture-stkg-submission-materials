# -*- coding: utf-8 -*-
"""Task 2 (GOAL Phase 4 / section 10): identity-projection pair evaluation tasks.

Positive merge-candidate pairs come from research_entity_members rows with
mapping_status='canonicalized' (the 1171 real identity reductions). Hard
negatives are mined from real name collisions in the release graph.

Judge-visible output (blinded): experiments/11_identity_validation/IDENTITY_PAIR_TASKS.jsonl
Scoring-only sidecar:           IDENTITY_PAIR_METADATA.csv
Manifest:                       IDENTITY_PAIR_TASKS.manifest.json

The JSONL never contains canonical_entity_id, merge results, or mapping status;
those appear only in the metadata sidecar.
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (EXP11, MASTER_SEED, attach_integration, connect_final,
                     db_hashes, derive_seed, now_iso, sha256_file, write_csv,
                     write_manifest)

TASK_NAME = "identity_pair_tasks"
N_POSITIVE = 300
NEG_QUOTAS = {                       # hard-negative categories mined from real data
    "same_name_mixed_type": 60,      # 同名异类（如 地名 vs 行政区）
    "same_name_person": 50,          # 同姓同名不同人物
    "similar_name_person": 50,       # 同姓、编辑距离<=2 的不同人物
    "event_vs_work_same_name": 40,   # 事件与同名作品/文献
    "org_vs_place_same_name": 60,    # 机构与地点同名
    "alias_name_collision": 40,      # 别名撞上另一真实人物正名
}
MAX_CTX = 4

META_FIELDS = ["pair_id", "pair_kind", "category", "entity_a_id", "entity_b_id",
               "entity_a_name", "entity_b_name", "true_merge_status",
               "canonical_entity_id", "member_mapping_statuses", "name_relation",
               "context_fact_ids_a", "context_fact_ids_b"]


def levenshtein(a: str, b: str, limit: int = 3) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        row_min = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            row_min = min(row_min, v)
        if row_min > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def main() -> None:
    seed = derive_seed(TASK_NAME)
    rng = random.Random(seed)
    con = connect_final()
    attach_integration(con)
    hashes = db_hashes()

    pred_zh = {r["predicate"]: r["label_zh"]
               for r in con.execute("SELECT predicate, label_zh FROM research_relation_contract")}

    # ---- assertion context index (canonical + source endpoints) -------------
    subj_idx: dict[str, list[sqlite3.Row]] = defaultdict(list)
    obj_idx: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in con.execute(
        "SELECT fact_id, source_subject_id, subject_id, subject_name, predicate,"
        "       object_name, source_object_id, object_id, normalized_time_label, time_raw,"
        "       place_raw, province, city, county, research_tier FROM research_assertions"
    ):
        for key in (r["subject_id"], r["source_subject_id"]):
            if key:
                subj_idx[key].append(r)
        for key in (r["object_id"], r["source_object_id"]):
            if key:
                obj_idx[key].append(r)

    def context_for(eid: str) -> tuple[list[str], list[str], str, list[str]]:
        rows = subj_idx.get(eid, []) + obj_idx.get(eid, [])
        rows.sort(key=lambda r: ({"strict_semantic": 0, "contextual": 1}.get(r["research_tier"], 2), r["fact_id"]))
        ctx, times, places, facts = [], [], [], []
        seen = set()
        for r in rows:
            if r["fact_id"] in seen:
                continue
            seen.add(r["fact_id"])
            lab = pred_zh.get(r["predicate"], r["predicate"])
            ctx.append(f"{r['subject_name']} —{lab}→ {r['object_name']}")
            t = r["normalized_time_label"] or r["time_raw"]
            if t:
                times.append(t)
            p = r["place_raw"] or "/".join(x for x in (r["province"], r["city"], r["county"]) if x)
            if p:
                places.append(p)
            facts.append(r["fact_id"])
            if len(ctx) >= MAX_CTX:
                break
        return ctx, sorted(set(times))[:3], "；".join(sorted(set(places))[:3]), facts

    # ---- evidence excerpt lookup (batched at the end) ------------------------
    def evidence_map(fact_ids: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for i in range(0, len(fact_ids), 400):
            chunk = fact_ids[i:i + 400]
            marks = ",".join("?" * len(chunk))
            ev: dict[str, list[str]] = defaultdict(list)
            for r in con.execute(
                f"SELECT p.fact_id, p.evidence_ids_json, m.evidence_ids_json AS m_ev"
                f" FROM research_assertion_provenance p"
                f" LEFT JOIN up.integrated_fact_members m ON m.source_fact_id = p.source_member_id"
                f" WHERE p.fact_id IN ({marks})", chunk):
                for blob in (r["evidence_ids_json"], r["m_ev"]):
                    try:
                        ev[r["fact_id"]].extend(json.loads(blob or "[]"))
                    except json.JSONDecodeError:
                        pass
            all_ev = sorted({e for v in ev.values() for e in v})
            texts: dict[str, str] = {}
            for j in range(0, len(all_ev), 400):
                sub = all_ev[j:j + 400]
                m2 = ",".join("?" * len(sub))
                for r in con.execute(
                    f"SELECT evidence_id, evidence_text FROM up.evidence_registry"
                    f" WHERE evidence_id IN ({m2}) AND evidence_text IS NOT NULL", sub):
                    texts[r["evidence_id"]] = r["evidence_text"]
            for fid, ids in ev.items():
                for e in ids:
                    if e in texts:
                        out[fid] = texts[e][:300]
                        break
        return out

    # ---- positive pairs -------------------------------------------------------
    members = con.execute(
        "SELECT source_entity_id, canonical_entity_id, source_canonical_name,"
        "       source_entity_type, mapping_status, source_aliases_json"
        " FROM research_entity_members"
    ).fetchall()
    by_canonical: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for m in members:
        by_canonical[m["canonical_entity_id"]].append(m)

    pos_pairs = []
    for cid, ms in by_canonical.items():
        if len(ms) < 2:
            continue
        if not any(m["mapping_status"] == "canonicalized" for m in ms):
            continue
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                pos_pairs.append((cid, ms[i], ms[j]))
    pos_avail = len(pos_pairs)
    rng.shuffle(pos_pairs)
    pos_take = pos_pairs[:N_POSITIVE]

    # ---- canonical entity table for hard negatives ----------------------------
    ents = {r["entity_id"]: dict(r) for r in con.execute(
        "SELECT entity_id, canonical_name, entity_type, aliases_json FROM research_entities")}

    name_groups: dict[str, list[str]] = defaultdict(list)
    for eid, e in ents.items():
        name_groups[e["canonical_name"]].append(eid)

    alias_index: dict[str, list[str]] = defaultdict(list)
    for eid, e in ents.items():
        try:
            for a in json.loads(e["aliases_json"] or "[]"):
                alias_index[a].append(eid)
        except json.JSONDecodeError:
            pass

    def pairs_from_groups(pred) -> list[tuple[str, str]]:
        out = set()
        for ids in name_groups.values():
            if len(ids) < 2:
                continue
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    a, b = ids[i], ids[j]
                    if pred(ents[a], ents[b]):
                        out.add(tuple(sorted((a, b))))
        return sorted(out)

    cand: dict[str, list[tuple[str, str]]] = {}
    cand["same_name_mixed_type"] = pairs_from_groups(
        lambda a, b: a["entity_type"] != b["entity_type"])
    cand["same_name_person"] = pairs_from_groups(
        lambda a, b: a["entity_type"] == "Person" and b["entity_type"] == "Person")
    cand["event_vs_work_same_name"] = pairs_from_groups(
        lambda a, b: {a["entity_type"], b["entity_type"]} & {"Event"}
        and {a["entity_type"], b["entity_type"]} & {"CreativeWork", "Document"})
    cand["org_vs_place_same_name"] = pairs_from_groups(
        lambda a, b: {a["entity_type"], b["entity_type"]} & {"Organization", "Institution"}
        and {a["entity_type"], b["entity_type"]} & {"Place", "AdministrativeRegion", "CulturalSite"})

    # similar-name persons: same surname, edit distance 1-2, different name
    persons_by_surname: dict[str, list[str]] = defaultdict(list)
    for eid, e in ents.items():
        if e["entity_type"] == "Person" and len(e["canonical_name"]) >= 2:
            persons_by_surname[e["canonical_name"][0]].append(eid)
    sim = set()
    for ids in persons_by_surname.values():
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                na, nb = ents[ids[i]]["canonical_name"], ents[ids[j]]["canonical_name"]
                if na != nb and levenshtein(na, nb, 2) <= 2:
                    sim.add(tuple(sorted((ids[i], ids[j]))))
    cand["similar_name_person"] = sorted(sim)

    # alias collisions: A's alias equals B's canonical name
    acol = set()
    for alias, a_ids in alias_index.items():
        for b_id in name_groups.get(alias, []):
            for a_id in a_ids:
                if a_id != b_id:
                    acol.add(tuple(sorted((a_id, b_id))))
    cand["alias_name_collision"] = sorted(acol)

    # sample hard negatives per category
    neg_take: list[tuple[str, str, str]] = []   # (category, a, b)
    neg_avail = {}
    for cat, quota in NEG_QUOTAS.items():
        pool = cand.get(cat, [])
        neg_avail[cat] = len(pool)
        rng.shuffle(pool)
        for a, b in pool[:quota]:
            neg_take.append((cat, a, b))

    # ---- assemble contexts -----------------------------------------------------
    def ent_facts(eid: str):
        return context_for(eid)

    all_facts: list[str] = []
    pair_ctx: dict[str, dict] = {}

    def build_ctx(eid: str) -> dict:
        if eid in pair_ctx:
            return pair_ctx[eid]
        ctx, times, places, facts = ent_facts(eid)
        pair_ctx[eid] = {"ctx": ctx, "times": times, "places": places,
                         "facts": facts,
                         "fact0": facts[0] if facts else None}
        if facts:
            all_facts.append(facts[0])
        return pair_ctx[eid]

    tasks, meta = [], []
    n = 0
    for cid, ma, mb in pos_take:
        n += 1
        pid = f"IDP3-{n:04d}"
        ca, cb = build_ctx(ma["source_entity_id"]), build_ctx(mb["source_entity_id"])
        tasks.append({
            "pair_id": pid,
            "name_a": ma["source_canonical_name"], "name_b": mb["source_canonical_name"],
            "aliases_a": ma["source_aliases_json"] or "[]",
            "aliases_b": mb["source_aliases_json"] or "[]",
            "relation_context_a": ca["ctx"], "relation_context_b": cb["ctx"],
            "time_info_a": ca["times"], "time_info_b": cb["times"],
            "space_info_a": ca["places"], "space_info_b": cb["places"],
            "evidence_a": "", "evidence_b": "",   # filled after batched lookup
            "_fact_a": ca["fact0"], "_fact_b": cb["fact0"],
        })
        meta.append({
            "pair_id": pid, "pair_kind": "positive_merge_candidate", "category": "identity_reduction",
            "entity_a_id": ma["source_entity_id"], "entity_b_id": mb["source_entity_id"],
            "entity_a_name": ma["source_canonical_name"], "entity_b_name": mb["source_canonical_name"],
            "true_merge_status": "merged_same_canonical", "canonical_entity_id": cid,
            "member_mapping_statuses": ";".join(sorted({ma["mapping_status"], mb["mapping_status"]})),
            "name_relation": "same_name" if ma["source_canonical_name"] == mb["source_canonical_name"] else "different_name",
            "context_fact_ids_a": json.dumps(ca["facts"], ensure_ascii=False),
            "context_fact_ids_b": json.dumps(cb["facts"], ensure_ascii=False),
        })
    for cat, a, b in neg_take:
        n += 1
        pid = f"IDP3-{n:04d}"
        ea, eb = ents[a], ents[b]
        ca, cb = build_ctx(a), build_ctx(b)
        tasks.append({
            "pair_id": pid,
            "name_a": ea["canonical_name"], "name_b": eb["canonical_name"],
            "aliases_a": ea["aliases_json"] or "[]", "aliases_b": eb["aliases_json"] or "[]",
            "relation_context_a": ca["ctx"], "relation_context_b": cb["ctx"],
            "time_info_a": ca["times"], "time_info_b": cb["times"],
            "space_info_a": ca["places"], "space_info_b": cb["places"],
            "evidence_a": "", "evidence_b": "",
            "_fact_a": ca["fact0"], "_fact_b": cb["fact0"],
        })
        meta.append({
            "pair_id": pid, "pair_kind": "hard_negative", "category": cat,
            "entity_a_id": a, "entity_b_id": b,
            "entity_a_name": ea["canonical_name"], "entity_b_name": eb["canonical_name"],
            "true_merge_status": "distinct_canonical", "canonical_entity_id": "",
            "member_mapping_statuses": "",
            "name_relation": ("same_name" if ea["canonical_name"] == eb["canonical_name"] else "similar_name"),
            "context_fact_ids_a": json.dumps(ca["facts"], ensure_ascii=False),
            "context_fact_ids_b": json.dumps(cb["facts"], ensure_ascii=False),
        })

    # ---- batched evidence excerpts --------------------------------------------
    ev_map = evidence_map(sorted(set(f for f in all_facts if f)))
    for t in tasks:
        fa, fb = t.pop("_fact_a"), t.pop("_fact_b")
        t["evidence_a"] = ev_map.get(fa, "")
        t["evidence_b"] = ev_map.get(fb, "")

    # ---- write -----------------------------------------------------------------
    tasks_path = EXP11 / "IDENTITY_PAIR_TASKS.jsonl"
    meta_path = EXP11 / "IDENTITY_PAIR_METADATA.csv"
    EXP11.mkdir(parents=True, exist_ok=True)
    with open(tasks_path, "w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    write_csv(meta_path, META_FIELDS, meta)

    n_pos = sum(1 for m in meta if m["pair_kind"] == "positive_merge_candidate")
    n_neg = len(meta) - n_pos
    manifest = {
        "experiment_id": "v3_identity_pair_tasks",
        "task_name": TASK_NAME,
        "master_seed": MASTER_SEED,
        "derived_seed": seed,
        "timestamp": now_iso(),
        **hashes,
        "row_count": len(tasks),
        "positive_pairs": n_pos,
        "positive_availability": pos_avail,
        "hard_negative_pairs": n_neg,
        "hard_negative_availability": neg_avail,
        "hard_negative_quota": NEG_QUOTAS,
        "blinding_note": ("JSONL carries only names/aliases/independent relation context/time-space/"
                          "evidence; canonical_entity_id, merge result and mapping status are "
                          "restricted to IDENTITY_PAIR_METADATA.csv (scoring only)"),
        "output_files": {
            tasks_path.name: {"path": str(tasks_path), "sha256": sha256_file(tasks_path), "rows": len(tasks)},
            meta_path.name: {"path": str(meta_path), "sha256": sha256_file(meta_path), "rows": len(meta)},
        },
    }
    write_manifest(EXP11, "IDENTITY_PAIR_TASKS.manifest.json", manifest)
    print("pairs:", len(tasks), "pos:", n_pos, "neg:", n_neg)
    print("pos availability:", pos_avail)
    print("neg availability:", neg_avail)
    con.close()


if __name__ == "__main__":
    main()
