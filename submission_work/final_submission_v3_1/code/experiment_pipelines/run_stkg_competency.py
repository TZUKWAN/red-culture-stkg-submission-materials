# -*- coding: utf-8 -*-
"""run_stkg_competency.py — STKG Competency Benchmark K0-K3（指令 §28-31）。"""
import json, sqlite3, hashlib, time, random, sys, os
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "repaired_release" / "red_culture_stkg_final_v3_1.sqlite"
OUT = Path(__file__).resolve().parents[2] / "experiments" / "stkg_competency"
SEED = 20260911
N_Q = 40

def db():
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    return con

def q(con, sql, params=()):
    return con.execute(sql, params).fetchall()

def generate_and_evaluate():
    con = db()
    rng = random.Random(SEED)
    results = []
    # Q1-Q3: event time/place/trajectory
    events = q(con, """SELECT DISTINCT a.fact_id, a.subject_name, a.normalized_time_label, a.place_raw,
        a.time_role, a.space_role, a.time_owner_id, a.space_owner_id,
        a.research_tier, a.semantic_status, a.confidence
        FROM research_assertions a WHERE a.predicate='occurred_at'
        AND a.research_tier='strict_semantic' AND a.confidence > 0.8 LIMIT 200""")
    rng.shuffle(events)
    for r in events[:N_Q]:
        fid = r["fact_id"]
        k0 = q(con, "SELECT 1 FROM research_assertions WHERE fact_id=?", (fid,))
        k1 = q(con, "SELECT normalized_time_label, place_raw FROM research_assertions WHERE fact_id=?", (fid,))
        k2 = q(con, "SELECT time_role, time_owner_id, space_role, space_owner_id FROM research_assertions WHERE fact_id=?", (fid,))
        k3_prov = q(con, "SELECT provenance_id FROM research_assertion_provenance WHERE fact_id=?", (fid,))
        k3_frame = q(con, """SELECT ef.event_id AS frame_id FROM research_event_assertion_links efa
            JOIN research_event_frames ef ON ef.event_id = efa.event_id WHERE efa.fact_id=? LIMIT 1""", (fid,))
        results.append({"q_type": "Q1_event_timeplace", "fact_id": fid, "subject": r["subject_name"],
            "tier": r["research_tier"],
            "K0_answerable": bool(k0), "K1_answerable": bool(k1),
            "K2_role_correct": bool(k2 and k2[0]["time_role"] and k2[0]["time_role"] != "unknown"),
            "K3_evidence_traced": bool(k3_prov), "K3_frame_linked": bool(k3_frame)})
    # Q4-Q5: person trajectory
    persons = q(con, """SELECT e.entity_id, e.canonical_name, COUNT(DISTINCT a.fact_id) as cnt
        FROM research_entities e JOIN research_assertions a ON a.subject_id=e.entity_id
        WHERE e.entity_type='Person' GROUP BY e.entity_id HAVING cnt>=5 LIMIT 100""")
    rng.shuffle(persons)
    for p in persons[:N_Q]:
        aids = q(con, "SELECT fact_id FROM research_assertions WHERE subject_id=? LIMIT 10", (p["entity_id"],))
        fid_list = [a["fact_id"] for a in aids]
        if not fid_list: continue
        k0 = q(con, "SELECT subject_name, predicate, object_name FROM research_assertions WHERE subject_id=? LIMIT 5", (p["entity_id"],))
        k2 = q(con, """SELECT a.time_role, a.space_role, a.normalized_time_label FROM research_assertions a
            WHERE a.subject_id=? AND a.time_role!='unknown' LIMIT 3""", (p["entity_id"],))
        k3_frame = q(con, "SELECT COUNT(DISTINCT event_id) as n FROM research_event_assertion_links WHERE fact_id IN (SELECT fact_id FROM research_assertions WHERE subject_id=?)", (p["entity_id"],))
        results.append({"q_type": "Q2_person_trajectory", "entity_id": p["entity_id"], "person": p["canonical_name"],
            "K0_answerable": bool(k0), "K2_temporal_context": bool(k2), "K3_frame_linked": bool(k3_frame and k3_frame[0]["n"] > 0)})
    # Q6-Q7: CultureState
    cs = q(con, """SELECT cs.state_id, cs.culture_form_code, cs.stage_label_zh, cs.region_id,
        cs.state_time_start, cs.state_time_end, cs.state_time_source,
        COUNT(se.event_id) as n_events
        FROM research_culture_states cs
        LEFT JOIN research_culture_state_events se ON cs.state_id = se.state_id
        GROUP BY cs.state_id LIMIT 200""")
    rng.shuffle(cs)
    for c in cs[:N_Q]:
        results.append({"q_type": "Q6_CultureState", "state_id": c["state_id"],
            "form": c["culture_form_code"], "stage": c["stage_label_zh"], "region": c["region_id"],
            "has_time": bool(c["state_time_start"]), "n_events": c["n_events"],
            "time_source": c["state_time_source"]})
    return results

if __name__ == "__main__":
    from collections import defaultdict, Counter
    con = db()
    results = generate_and_evaluate()
    OUT.mkdir(parents=True, exist_ok=True)
    OUT.joinpath("COMPETENCY_RESULTS.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    by_type = defaultdict(Counter)
    for r in results:
        t = r.get("q_type", "?")
        by_type[t]["n"] += 1
        for k in ("K0_answerable", "K1_answerable", "K2_answerable", "K2_role_correct", "K3_evidence_traced", "K3_frame_linked"):
            if r.get(k): by_type[t][k] += 1
    print(json.dumps({str(k): dict(v) for k, v in by_type.items()}, ensure_ascii=False, indent=1))
    con.close()
