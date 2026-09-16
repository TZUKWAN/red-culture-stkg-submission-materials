# -*- coding: utf-8 -*-
"""replay_full_admission.py — 全库 424,150 条准入轨迹确定性重放与硬验收。

从冻结输入（源库只读 + FINAL_TIERING.csv + 冻结 284 规则）独立重算每条断言的
pre_gate_tier / blocking reasons / decision path，与已提交的
experiments/10_full_universe_admission_closure/FULL_UNIVERSE_ADMISSION_LEDGER.csv
逐行对账。六项检查任一非零即 FAIL：
  row_count_diff / fact_id_diff / tier_diff / decision_path_missing /
  blocking_reason_missing_non_strict / unexplained_unresolved

用法：python replay_full_admission.py [--report <输出 json>]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

V31 = Path(__file__).resolve().parents[2]
REPO = V31.parents[1]
CLOSURE = V31 / "experiments" / "10_full_universe_admission_closure"
SRC_DB = V31 / "data" / "repaired_release" / "red_culture_stkg_final_v3_1.sqlite"
FINAL_TIERING = V31 / "experiments" / "07_provenance_semantic_gate" / "FINAL_TIERING.csv"
LEDGER = CLOSURE / "FULL_UNIVERSE_ADMISSION_LEDGER.csv"
SCRIPT_284 = REPO / "code" / "scripts" / "284_materialize_stkg_v2_research_base.py"
DEPS = V31.parent / "final_submission_v3" / "data" / "external_inputs"
CN_TZ = timezone(timedelta(hours=8))


def load_frozen_284():
    if str(DEPS) not in sys.path:
        sys.path.insert(0, str(DEPS))
    spec = importlib.util.spec_from_file_location("replay_frozen_284", SCRIPT_284)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["replay_frozen_284"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=str(CLOSURE / "FULL_ADMISSION_REPLAY_REPORT.json"))
    args = ap.parse_args()
    frozen = load_frozen_284()
    relation_ok = frozen.relation_domain_range_pass_v2

    con = sqlite3.connect(f"file:{SRC_DB}?mode=ro", uri=True)
    gate: dict[str, str] = {}
    for r in csv.DictReader(open(FINAL_TIERING, encoding="utf-8-sig")):
        gate[r["fact_id"]] = r["final_tier"]
    ent_status = {eid: st for eid, st in con.execute(
        "SELECT entity_id, type_validation_status FROM research_entities")}

    recomputed: dict[str, dict] = {}
    cur = con.execute(
        "SELECT a.fact_id, a.semantic_status, a.research_tier, a.predicate, "
        "a.merged_into, a.subject_id, a.object_id, a.subject_type, a.object_type, "
        "es.type_validation_status, eo.type_validation_status "
        "FROM research_assertions a "
        "LEFT JOIN research_entities es ON es.entity_id=a.subject_id "
        "LEFT JOIN research_entities eo ON eo.entity_id=a.object_id")
    while True:
        batch = cur.fetchmany(20000)
        if not batch:
            break
        for (fid, sem_status, research_tier, pred, merged, sid, oid,
             subj_type, obj_type, s_status, o_status) in batch:
            in_gate = fid in gate
            pred_raw = str(pred or "").startswith("raw:")
            subj_ok = (s_status == "validated")
            obj_ok = (o_status == "validated")
            rel_ok = relation_ok(pred, subj_type, obj_type)
            if sem_status == "auto_accepted":
                pre = "contextual"
                soft = []
                if pred_raw:
                    soft.append("predicate_raw_not_normalized")
                if not subj_ok:
                    soft.append("subject_entity_type_not_validated")
                if not obj_ok:
                    soft.append("object_entity_type_not_validated")
                if not rel_ok:
                    soft.append("relation_domain_range_violation")
                primary = ("strict_candidate_conjunct_failed:" + soft[0]
                           if soft else "")
                if not soft:
                    pre = "strict_semantic"
            else:
                pre = "unresolved"
                hard = []
                if not subj_ok or not obj_ok:
                    hard.append("endpoint_entity_type_unresolved")
                if sem_status == "manual_review":
                    hard.append("manual_review_legacy")
                    primary = "hard_blocker:manual_review_legacy"
                elif hard:
                    primary = "hard_blocker:endpoint_entity_type_unresolved"
                else:
                    hard.append("scope_conflict_model_review")
                    primary = "hard_blocker:scope_conflict_model_review"
                soft = hard
            final_tier = gate[fid] if in_gate else research_tier
            if in_gate:
                path = (f"v2_semantic_normalization[auto_accepted]"
                        f"->strict_candidate_check[pass]"
                        f"->evidence_gate_final[{final_tier}]")
            elif pre == "unresolved":
                path = (f"v2_semantic_normalization[{sem_status}]"
                        f"->excluded_from_strict_layer[{primary}]"
                        f"->unresolved(outside_gate)")
            else:
                path = (f"v2_semantic_normalization[auto_accepted]"
                        f"->strict_candidate_check[fail]->contextual(outside_gate)")
            recomputed[fid] = {
                "pre_gate_tier": pre, "final_tier": final_tier,
                "primary_blocking_reason": primary,
                "decision_path": path, "soft_blockers": ";".join(soft),
                "hard_blockers": ";".join(hard) if sem_status != "auto_accepted" else "",
            }
    con.close()

    committed: dict[str, dict] = {}
    with open(LEDGER, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            committed[r["fact_id"]] = r

    rc_ids, cm_ids = set(recomputed), set(committed)
    tier_diff = sum(1 for f in rc_ids & cm_ids
                    if recomputed[f]["final_tier"] != committed[f]["final_tier"])
    pre_diff = sum(1 for f in rc_ids & cm_ids
                   if recomputed[f]["pre_gate_tier"] != committed[f]["pre_gate_tier"])
    path_missing = sum(1 for f in rc_ids & cm_ids
                       if not committed[f].get("decision_path"))
    reason_missing = sum(
        1 for f in rc_ids & cm_ids
        if committed[f]["final_tier"] != "STRICT"
        and not (committed[f].get("primary_blocking_reason")
                 or committed[f].get("hard_blockers")
                 or committed[f].get("soft_blockers")))
    unexplained_unresolved = sum(
        1 for f in rc_ids & cm_ids
        if committed[f]["pre_gate_tier"] == "unresolved"
        and not committed[f].get("primary_blocking_reason"))
    report = {
        "generated_at": datetime.now(CN_TZ).isoformat(),
        "row_count_diff": abs(len(recomputed) - len(committed)),
        "fact_id_diff": len(rc_ids ^ cm_ids),
        "tier_diff": tier_diff,
        "pre_gate_tier_diff": pre_diff,
        "decision_path_missing": path_missing,
        "blocking_reason_missing_non_strict": reason_missing,
        "unexplained_unresolved": unexplained_unresolved,
        "all_zero": (len(recomputed) == len(committed) and not (rc_ids ^ cm_ids)
                     and tier_diff == 0 and pre_diff == 0 and path_missing == 0
                     and reason_missing == 0 and unexplained_unresolved == 0),
        "recomputed_tier_counts": dict(Counter(
            r["final_tier"] for r in recomputed.values())),
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print(f"[replay] rows={len(recomputed):,} tier_diff={tier_diff} "
          f"pre_diff={pre_diff} path_missing={path_missing} "
          f"reason_missing={reason_missing} unexplained={unexplained_unresolved} "
          f"all_zero={report['all_zero']}")
    return 0 if report["all_zero"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
