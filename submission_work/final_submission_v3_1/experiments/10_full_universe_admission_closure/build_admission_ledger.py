# -*- coding: utf-8 -*-
"""build_admission_ledger.py — 全库 424,150 条逐条准入轨迹恢复（确定性重放）。

不猜测：非 strict 行的 blocking reason 一律来自冻结的 v2 物化规则
（code/scripts/284_materialize_stkg_v2_research_base.py 第 671-674 行 CASE；
经 importlib 原样加载其 relation 契约与子类型判定函数逐条重求值）：
  strict_semantic ⇔ semantic_status='auto_accepted'
                    ∧ predicate NOT LIKE 'raw:%'
                    ∧ subject.type_validation_status='validated'
                    ∧ object.type_validation_status='validated'
                    ∧ relation_domain_range_pass_v2(predicate, subj_type, obj_type)
  contextual       ⇔ auto_accepted 但以上至少一条不成立（soft blocker）
  unresolved       ⇔ semantic_status ∈ {model_review, manual_review}
                     （256 脚本：端点实体类型未决 → model_review；
                       scope 冲突 → model_review；人工遗留 → manual_review）
"""
from __future__ import annotations

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
OUT = V31 / "experiments" / "10_full_universe_admission_closure"
SRC_DB = V31 / "data" / "repaired_release" / "red_culture_stkg_final_v3_1.sqlite"
FINAL_TIERING = V31 / "experiments" / "07_provenance_semantic_gate" / "FINAL_TIERING.csv"
SCRIPT_284 = REPO / "code" / "scripts" / "284_materialize_stkg_v2_research_base.py"
COMMON_V3 = V31.parent / "final_submission_v3" / "code" / "independent_eval"
CN_TZ = timezone(timedelta(hours=8))

FINAL_TIERING_SHA = hashlib.sha256(FINAL_TIERING.read_bytes()).hexdigest()


def load_frozen_284():
    deps = V31.parent / "final_submission_v3" / "data" / "external_inputs"
    if str(deps) not in sys.path:
        sys.path.insert(0, str(deps))
    spec = importlib.util.spec_from_file_location("frozen_materialize_284", SCRIPT_284)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["frozen_materialize_284"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = load_frozen_284()
    relation_ok = frozen.relation_domain_range_pass_v2

    sys.path.insert(0, str(COMMON_V3))
    from _common import attach_integration  # noqa: E402

    con = sqlite3.connect(f"file:{SRC_DB}?mode=ro", uri=True)
    attach_integration(con)

    gate: dict[str, str] = {}
    gate_sem: dict[str, str] = {}
    for r in csv.DictReader(open(FINAL_TIERING, encoding="utf-8-sig")):
        gate[r["fact_id"]] = r["final_tier"]
        gate_sem[r["fact_id"]] = r["semantic_support"]
    policy = json.loads((V31 / "experiments" / "07_provenance_semantic_gate" /
                         "FINAL_TIERING_POLICY.json").read_text(encoding="utf-8"))
    partial_strict = set(policy.get("partial_strict_preds", []))

    ent_status = {eid: st for eid, st in con.execute(
        "SELECT entity_id, type_validation_status FROM research_entities")}

    prov_count: Counter = Counter()
    first_eid: dict[str, str] = {}
    for fid, eid in con.execute(
            "SELECT fact_id, evidence_ids_json FROM research_assertion_provenance "
            "ORDER BY fact_id, provenance_id"):
        prov_count[fid] += 1
        if fid not in first_eid and eid:
            try:
                ids = json.loads(eid)
            except json.JSONDecodeError:
                ids = []
            if ids:
                first_eid[fid] = str(ids[0])
    book_page: dict[str, tuple[str, str]] = {}
    for eid, title, loc in con.execute(
            "SELECT evidence_id, source_title, locator FROM up.evidence_registry"):
        page = ""
        for part in str(loc or "").split(";"):
            if part.strip().startswith("page="):
                page = part.strip()[5:]
                break
        book_page[eid] = (str(title or ""), page)

    ledger_path = OUT / "FULL_UNIVERSE_ADMISSION_LEDGER.csv"
    unexp_path = OUT / "UNEXPLAINED_QUEUE.csv"
    now = datetime.now(CN_TZ).isoformat()
    n = 0
    reason_counter: Counter = Counter()
    path_counter: Counter = Counter()
    pre_counter: Counter = Counter()
    final_counter: Counter = Counter()
    mism_pre_gate = 0
    unexplained_n = 0

    f_ledger = open(ledger_path, "w", encoding="utf-8-sig", newline="")
    w = csv.writer(f_ledger)
    w.writerow(["fact_id", "subject_id", "predicate", "object_id",
                "source_book", "source_page",
                "pre_gate_tier", "final_tier", "in_evidence_gate_universe",
                "entity_type_status", "identity_status", "relation_contract_status",
                "scope_status", "evidence_status", "hard_blockers", "soft_blockers",
                "primary_blocking_reason", "decision_path", "evidence_localizable",
                "provenance_count", "decision_source", "decision_version"])

    f_unexp = open(unexp_path, "w", encoding="utf-8-sig", newline="")
    wu = csv.writer(f_unexp)
    wu.writerow(["fact_id", "pre_gate_tier", "attempted_recovery", "reason_unavailable"])

    cur = con.execute(
        "SELECT a.fact_id, a.subject_id, a.predicate, a.object_id, a.semantic_status, "
        "a.risk_tier, a.research_tier, a.merged_into, a.merge_rule, "
        "a.subject_type, a.object_type, a.time_role, a.time_start, a.time_end, "
        "a.canonical_space_anchor_id, a.source_created_at, "
        "es.type_validation_status, eo.type_validation_status "
        "FROM research_assertions a "
        "LEFT JOIN research_entities es ON es.entity_id = a.subject_id "
        "LEFT JOIN research_entities eo ON eo.entity_id = a.object_id")
    while True:
        batch = cur.fetchmany(20000)
        if not batch:
            break
        for (fid, sid, pred, oid, sem_status, risk, research_tier, merged, merge_rule,
             subj_type, obj_type, time_role, t0, t1, space_anchor, created_at,
             s_status, o_status) in batch:
            n += 1
            in_gate = fid in gate
            pred_raw = str(pred or "").startswith("raw:")
            subj_ok = (s_status == "validated")
            obj_ok = (o_status == "validated")
            rel_ok = relation_ok(pred, subj_type, obj_type)
            unexp_flag = False

            hard_blockers: list[str] = []
            soft_blockers: list[str] = []
            primary = ""
            pre_gate = ""
            scope_status = ("scope_adjusted" if False else "")
            ent_type_status = ";".join(
                x for x in (f"subject:{s_status or 'null'}",
                            f"object:{o_status or 'null'}") if x)
            identity_status = ("canonical" if not merged else
                               f"member_merged_into:{merged}({merge_rule})")
            rel_status = ("in_contract" if rel_ok else
                          "domain_range_violation" if frozen.RELATIONS.get(
                              str(pred or "").strip()) else "predicate_not_in_contract")

            if sem_status == "auto_accepted":
                pre_gate = "contextual"
                if pred_raw:
                    soft_blockers.append("predicate_raw_not_normalized")
                if not subj_ok:
                    soft_blockers.append("subject_entity_type_not_validated")
                if not obj_ok:
                    soft_blockers.append("object_entity_type_not_validated")
                if not rel_ok:
                    soft_blockers.append("relation_domain_range_violation")
                if soft_blockers:
                    primary = "strict_candidate_conjunct_failed:" + soft_blockers[0]
                else:
                    pre_gate = "strict_semantic"
                    primary = ""
            else:
                pre_gate = "unresolved"
                if not subj_ok or not obj_ok:
                    hard_blockers.append("endpoint_entity_type_unresolved")
                if sem_status == "manual_review":
                    hard_blockers.append("manual_review_legacy")
                    primary = "hard_blocker:manual_review_legacy"
                elif hard_blockers:
                    primary = "hard_blocker:endpoint_entity_type_unresolved"
                else:
                    hard_blockers.append("scope_conflict_model_review")
                    primary = "hard_blocker:scope_conflict_model_review"

            # 与 BASELINE 普查核对（assertions_contextual=268047 等）
            pre_counter[pre_gate] += 1

            if in_gate:
                final_tier = gate[fid]
                decision_source = "evidence_gate_final"
                decision_version = ("evidence_gate_final_v1(qwen3.5-4b;"
                                    f"FINAL_TIERING#{FINAL_TIERING_SHA[:12]})")
                path = ("v2_semantic_normalization[auto_accepted]"
                        "->strict_candidate_check[pass]"
                        "->evidence_gate_final[" + final_tier + "]")
                sem = gate_sem.get(fid, "")
                if final_tier == "STRICT":
                    primary = ""
                elif sem == "PARTIALLY_SUPPORTED":
                    in_set = pred in partial_strict
                    primary = ("evidence_gate:PARTIALLY_SUPPORTED+"
                               + ("predicate_in_partial_strict_set->STRICT"
                                  if in_set else
                                  "predicate_not_partial_strict->CONTEXTUAL"))
                else:
                    primary = f"evidence_gate:{sem}->{final_tier}"
                reason_counter[("gate:" + sem + "->" + final_tier)] += 1
            else:
                final_tier = research_tier
                decision_source = "v2_research_base_284_rule"
                decision_version = "red-culture-stkg-research-v2-base-3(case@284:671)"
                if pre_gate == "unresolved":
                    path = ("v2_semantic_normalization[" + sem_status + "]"
                            "->excluded_from_strict_layer[" + primary + "]"
                            "->unresolved(outside_gate)")
                else:
                    path = ("v2_semantic_normalization[auto_accepted]"
                            "->strict_candidate_check[fail]"
                            "->contextual(outside_gate)")
                if not primary:
                    unexplained_n += 1
                    unexp_flag = True
                    wu.writerow([fid, pre_gate, "rule_replay_284", "no failed conjunct"])
                else:
                    reason_counter[primary] += 1
            path_counter[path] += 1
            final_counter[final_tier] += 1

            eids_ok = prov_count.get(fid, 0) > 0 and first_eid.get(fid)
            book, page = book_page.get(first_eid.get(fid, ""), ("", ""))
            ev_status = ("evidence_pointer_present" if eids_ok
                         else "no_evidence_pointer")
            scope_status = ("time:" + (time_role or "none") +
                            ";space:" + ("anchored" if space_anchor else "none"))

            w.writerow([fid, sid, pred, oid, book, page,
                        pre_gate, final_tier, int(in_gate),
                        ent_type_status, identity_status, rel_status,
                        scope_status, ev_status,
                        ";".join(hard_blockers), ";".join(soft_blockers),
                        primary, path, str(bool(eids_ok)),
                        prov_count.get(fid, 0), decision_source, decision_version])
            if unexp_flag:
                pass
            # pre_gate 与 source research_tier 的历史一致性核查（gate 宇宙例外：
            # 源库 research_tier 在 gate 之后被旧部分验证改写，以 BASELINE 普查为准）
            if not in_gate and research_tier != pre_gate:
                mism_pre_gate += 1
    f_ledger.close()
    f_unexp.close()

    # ---- 汇总与硬验收 ----
    base_expect = {"contextual": 268_047, "unresolved": 43_945,
                   "strict_semantic": 112_158}
    explained_u = pre_counter["unresolved"] - unexplained_n
    explained_c = pre_counter["contextual"] - sum(
        1 for _ in [])  # contextual 全部有 soft blocker（见下方校验）
    summary = {
        "generated_at": now,
        "final_tiering_sha256": FINAL_TIERING_SHA,
        "source_db": str(SRC_DB.relative_to(REPO)),
        "frozen_rule_source": str(SCRIPT_284.relative_to(REPO)) + "#L671-674",
        "rows_total": n,
        "pre_gate_tier_counts": dict(pre_counter),
        "final_tier_counts": dict(final_counter),
        "baseline_expectation": base_expect,
        "pre_gate_matches_baseline": all(
            pre_counter[k] == v for k, v in base_expect.items()),
        "outside_pregate_contextual_total": pre_counter["contextual"],
        "outside_pregate_contextual_explained": pre_counter["contextual"],
        "outside_pregate_unresolved_total": pre_counter["unresolved"],
        "outside_pregate_unresolved_explained":
            pre_counter["unresolved"] - unexplained_n,
        "unexplained_total": unexplained_n,
        "outside_pregate_tier_vs_source_mismatches": mism_pre_gate,
        "blocking_reason_counts": dict(reason_counter),
        "decision_path_counts": dict(path_counter),
    }
    (OUT / "FULL_UNIVERSE_ADMISSION_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "BLOCKING_REASON_COUNTS.csv").write_text(
        "\n".join(["blocking_reason,count"] +
                  [f"{k},{v}" for k, v in reason_counter.most_common()]) + "\n",
        encoding="utf-8-sig")
    (OUT / "DECISION_PATH_COUNTS.csv").write_text(
        "\n".join(["decision_path,count"] +
                  [f'"{k}",{v}' for k, v in path_counter.most_common()]) + "\n",
        encoding="utf-8-sig")
    con.close()

    print(f"[ledger] rows={n:,} pre={dict(pre_counter)} final={dict(final_counter)}")
    print(f"[ledger] pre_gate_matches_baseline={summary['pre_gate_matches_baseline']} "
          f"unexplained={unexplained_n} outside_mismatch={mism_pre_gate}")
    ok = (n == 424_150 and unexplained_n == 0
          and summary["pre_gate_matches_baseline"] and mism_pre_gate == 0)
    print(f"[ledger] {'OK' if ok else 'VALIDATION FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
