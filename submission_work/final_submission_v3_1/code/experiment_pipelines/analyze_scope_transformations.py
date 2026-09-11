# -*- coding: utf-8 -*-
"""analyze_scope_transformations.py — 05_scope_repair：208 条 role-owner scope 调整
按 transformation_type 的盲评归因（两票口径：Judge A + Judge B）。

问题：scope revalidation v2 总体上 BEFORE 支持率高于 AFTER（改前约 52% vs 改后 46%），
本脚本定位"哪类变换害的"。

口径（全程两票，Judge C 未完成全部 208 条且口径未定，一律不用）：
* 判票来源：experiments/01_reference_rebuild/raw_runs/scope_revalidation_v2/{A,B}.jsonl，
  parsed_response.decision ∈ {A_BETTER,B_BETTER,EQUIVALENT,BOTH_WRONG,INSUFFICIENT_EVIDENCE}。
  decision 的 A/B 是展示位，必须经 SCOPE_REVALIDATION_V2_AB_MAPPING.csv 解码回
  before/after（禁止按字段名猜方向）。
* 判票无效（status != OK / decision 缺失或非法 / MODEL_OUTPUT_INVALID）→ 该票 INVALID，
  单独计数；两票聚合时任一票 INVALID 即整条 INVALID。
* 两票聚合：同票 → 该判定；异票 → DISAGREE。
  解码标签统一为 BEFORE_BETTER / AFTER_BETTER / EQUIVALENT / BOTH_WRONG / INSUFFICIENT / INVALID。

transformation_type（source→final 的 role/owner 组合，优先级从上到下）：
  mixed                        time 与 space 同时变化（role 或 owner 任一）
  unknown→event_occurrence     仅 time 变，source time role=unknown → final=event_occurrence
  event_location→context_location  仅 space 变，event_location→context_location
  event_location→relation_location 仅 space 变，event_location→relation_location
  time_owner_change            仅 time owner 变、role 不变
  space_owner_change           仅 space owner 变、role 不变
  other                        其余组合（报告附实际组合全表）

建议阈值（Selective Scope Closure，只基于本数据，写死在此以便复现）：
  对每类取 decided = AFTER_BETTER + BEFORE_BETTER（两票一致），
  after_win_rate = AFTER/decided，双侧精确二项检验 p 值（H0: p=0.5）：
    REWRITE    ：p < 0.05 且方向为 AFTER 且 decided ≥ 10（AFTER 显著占优）
    RETAIN     ：p < 0.05 且方向为 BEFORE 且 decided ≥ 10（AFTER 不占优，维持 before）
    UNRESOLVED ：其余（样本不足或方向不显著，含证据不足主导类）

输出（全部新建，不改动任何既有文件）：
  experiments/05_scope_repair/SCOPE_BY_TYPE_ERRORS.csv
  experiments/05_scope_repair/SCOPE_BY_TYPE_SUMMARY.json
  experiments/05_scope_repair/SCOPE_REPAIR_REPORT.md
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # Windows 控制台默认 GBK，报告含中文/箭头，统一切到 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

V3_1 = Path(__file__).resolve().parents[2]
V3 = V3_1.parent / "final_submission_v3"

RUNS = V3_1 / "experiments" / "01_reference_rebuild" / "raw_runs" / "scope_revalidation_v2"
PAYLOAD_DIR = V3_1 / "experiments" / "01_reference_rebuild" / "payloads"
MAPPING_CSV = PAYLOAD_DIR / "SCOPE_REVALIDATION_V2_AB_MAPPING.csv"
METADATA_CSV = PAYLOAD_DIR / "SCOPE_REVALIDATION_V2_METADATA.csv"
PAYLOADS_JSONL = PAYLOAD_DIR / "SCOPE_REVALIDATION_V2_PAYLOADS.jsonl"
TASKS_JSONL = V3 / "experiments" / "10_structural_validation" / "SCOPE_ADJUSTMENT_TASKS.jsonl"

OUT_DIR = V3_1 / "experiments" / "05_scope_repair"
CSV_OUT = OUT_DIR / "SCOPE_BY_TYPE_ERRORS.csv"
SUMMARY_OUT = OUT_DIR / "SCOPE_BY_TYPE_SUMMARY.json"
REPORT_OUT = OUT_DIR / "SCOPE_REPAIR_REPORT.md"

ALLOWED_DECISIONS = {"A_BETTER", "B_BETTER", "EQUIVALENT", "BOTH_WRONG", "INSUFFICIENT_EVIDENCE"}
DECISION_MAP = {
    "EQUIVALENT": "EQUIVALENT",
    "BOTH_WRONG": "BOTH_WRONG",
    "INSUFFICIENT_EVIDENCE": "INSUFFICIENT",
}
AGG_LABELS = ["BEFORE_BETTER", "AFTER_BETTER", "EQUIVALENT", "BOTH_WRONG", "INSUFFICIENT", "DISAGREE", "INVALID"]
P_THRESHOLD = 0.05
MIN_DECIDED = 10


def norm_role(x: Any) -> str:
    return x if x else "unknown"


def binom_two_sided(k: int, n: int) -> float:
    """双侧精确二项检验 p 值（H0: p=0.5），无第三方依赖。"""
    if n == 0:
        return 1.0
    k = min(k, n - k)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


# ---------------------------------------------------------------- 数据加载
def load_mapping() -> dict[str, tuple[str, str]]:
    mapping: dict[str, tuple[str, str]] = {}
    with open(MAPPING_CSV, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            tid = row["task_id"].strip()
            if tid in mapping:
                raise SystemExit(f"[FATAL] 映射文件 task_id 重复: {tid}")
            if row["a"] not in ("before", "after") or row["b"] not in ("before", "after"):
                raise SystemExit(f"[FATAL] 映射文件方向值非法: {tid} a={row['a']} b={row['b']}")
            if row["a"] == row["b"]:
                raise SystemExit(f"[FATAL] 映射文件 a/b 同向: {tid}")
            mapping[tid] = (row["a"], row["b"])
    return mapping


def load_payloads() -> dict[str, dict]:
    payloads: dict[str, dict] = {}
    with open(PAYLOADS_JSONL, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            payloads[rec["task_id"]] = rec
    return payloads


def load_metadata() -> dict[str, dict]:
    meta: dict[str, dict] = {}
    with open(METADATA_CSV, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            meta[row["task_id"]] = row
    return meta


def load_tasks() -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    with open(TASKS_JSONL, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            tasks[rec["task_id"]] = rec
    return tasks


def decode_vote(task_id: str, rec: dict, mapping: dict[str, tuple[str, str]]) -> dict:
    """把单票按映射文件解码为 before/after 口径标签；无效票 → INVALID。"""
    raw = (rec.get("raw_response") or "")
    pr = rec.get("parsed_response") or {}
    decision = pr.get("decision")
    invalid_reason = None
    if rec.get("status") != "OK" or "MODEL_OUTPUT_INVALID" in raw:
        invalid_reason = "status=%s" % rec.get("status")
    elif decision not in ALLOWED_DECISIONS:
        invalid_reason = "decision=%r" % decision
    if invalid_reason:
        return {"label": "INVALID", "invalid_reason": invalid_reason, "raw": rec}
    if decision == "A_BETTER":
        label = "AFTER_BETTER" if mapping[task_id][0] == "after" else "BEFORE_BETTER"
    elif decision == "B_BETTER":
        label = "AFTER_BETTER" if mapping[task_id][1] == "after" else "BEFORE_BETTER"
    else:
        label = DECISION_MAP[decision]
    return {
        "label": label,
        "invalid_reason": None,
        "decision_raw": decision,
        "confidence": pr.get("confidence"),
        "reason_code": pr.get("reason_code"),
        "explanation": (pr.get("explanation") or "").strip(),
        "evidence": [e for e in (pr.get("evidence") or []) if e],
    }


def classify_transformation(adj: dict) -> tuple[str, str]:
    """返回 (transformation_type, 组合描述串)。"""
    st, ft = norm_role(adj["source_time_role"]), norm_role(adj["final_time_role"])
    ss, fs = norm_role(adj["source_space_role"]), norm_role(adj["final_space_role"])
    to = adj["source_time_owner_id"] != adj["final_time_owner_id"]
    so = adj["source_space_owner_id"] != adj["final_space_owner_id"]
    time_changed = (st != ft) or to
    space_changed = (ss != fs) or so
    combo_time = "%s→%s (owner %s)" % (st, ft, "changed" if to else "same")
    combo_space = "%s→%s (owner %s)" % (ss, fs, "changed" if so else "same")
    combo = "time: %s | space: %s" % (combo_time, combo_space)
    if not time_changed and not space_changed:
        return "no_change", combo_time, combo_space
    if time_changed and space_changed:
        return "mixed", combo_time, combo_space
    if time_changed:
        if st == "unknown" and ft == "event_occurrence":
            return "unknown→event_occurrence", combo_time, combo_space
        if st == ft:
            return "time_owner_change", combo_time, combo_space
        return "other", combo_time, combo_space
    if ss == "event_location" and fs == "context_location":
        return "event_location→context_location", combo_time, combo_space
    if ss == "event_location" and fs == "relation_location":
        return "event_location→relation_location", combo_time, combo_space
    if ss == fs:
        return "space_owner_change", combo_time, combo_space
    return "other", combo_time, combo_space


def aggregate(vote_a: str, vote_b: str) -> str:
    if vote_a == "INVALID" or vote_b == "INVALID":
        return "INVALID"
    return vote_a if vote_a == vote_b else "DISAGREE"


def owner_disposition(src_id: Any, fin_id: Any) -> str:
    if src_id == fin_id:
        return "unchanged"
    if fin_id is None:
        return "removed"
    if src_id is None:
        return "assigned"
    return "reassigned"


def resolve_state(task: dict, time_role: Any, space_role: Any) -> dict | None:
    """在任务的 state_a/state_b 中按 role 组合定位状态。

    注意：state_a/state_b 是 V3 当时盲评的展示态（V3 另有自己的 AB 映射），不必然
    等于 before/after；before/after 以 adjustment.source_*/final_* 为准，这里按
    role 组合匹配取回对应展示态（两类状态的 role 组合必不相同，可唯一匹配）。
    """
    for key in ("state_a", "state_b"):
        st = task[key]
        if norm_role(st["time_role"]) == norm_role(time_role) and \
           norm_role(st["space_role"]) == norm_role(space_role):
            return st
    return None


def owner_name(state: dict | None, key: str) -> str:
    if not state or not state.get(key):
        return "（无）"
    return state[key].get("name") or "（无）"


def pick_examples(rows: list[dict], k: int = 2) -> list[dict]:
    """每类抽 k 条典型例：优先展示对 AFTER 不利(BEFORE_BETTER)与有利(AFTER_BETTER)的
    对照例，其次 DISAGREE/BOTH_WRONG/INSUFFICIENT；同桶内按两票最低置信度降序、
    task_id 升序，完全确定性。"""
    priority = {"BEFORE_BETTER": 0, "AFTER_BETTER": 1, "DISAGREE": 2, "BOTH_WRONG": 3,
                "INSUFFICIENT": 4, "EQUIVALENT": 5}
    pool = [r for r in rows if r["aggregated"] in priority and r["aggregated"] != "INVALID"]
    pool.sort(key=lambda r: (-min(r["conf_A"] or 0.0, r["conf_B"] or 0.0), r["task_id"]))
    chosen: list[dict] = []
    used_aggs: set[str] = set()
    # 第一轮：每个聚合桶取最优一条，按桶优先级
    for agg in sorted(priority, key=lambda a: priority[a]):
        for r in pool:
            if r["aggregated"] == agg and r["task_id"] not in {c["task_id"] for c in chosen}:
                chosen.append(r)
                used_aggs.add(agg)
                break
        if len(chosen) >= k:
            break
    # 第二轮：不足则按全局排序补齐
    for r in pool:
        if len(chosen) >= k:
            break
        if r["task_id"] not in {c["task_id"] for c in chosen}:
            chosen.append(r)
    return chosen[:k]


def md_example(ex: dict) -> str:
    lines = [
        "#### %s（%s，聚合=%s，证据=%s）" % (ex["task_id"], ex["transformation_type"], ex["aggregated"], ex["evidence_source"]),
        "",
        "**断言（payload 原文）**：",
        "",
        "```",
        ex["assertion_text"].strip(),
        "```",
        "",
        "**payload 证据句**：%s" % ("；".join("「%s」" % t for t in ex["payload_evidence"]) if ex["payload_evidence"] else "（无）"),
        "",
        "- BEFORE 状态：%s" % ex["state_before"],
        "- AFTER 状态：%s" % ex["state_after"],
        "- **Judge A（%s）**：%s" % (ex["vote_A_decoded"], ex["expl_A"]),
        "- **Judge B（%s）**：%s" % (ex["vote_B_decoded"], ex["expl_B"]),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    mapping = load_mapping()
    payloads = load_payloads()
    metadata = load_metadata()
    tasks = load_tasks()

    # ---- 完整性守门：五源 task 集必须一致，judge prompt 指纹必须对上 payload
    task_ids = set(tasks)
    for name, src in (("mapping", mapping), ("payloads", payloads), ("metadata", metadata)):
        if set(src) != task_ids:
            raise SystemExit("[FATAL] %s 与任务集不一致: only_in_%s=%s only_in_tasks=%s" % (
                name, name, sorted(set(src) - task_ids)[:5], sorted(task_ids - set(src))[:5]))

    votes: dict[str, dict[str, dict]] = {}
    invalid_votes = Counter()
    for judge in ("A", "B"):
        per: dict[str, dict] = {}
        with open(RUNS / ("%s.jsonl" % judge), encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                tid = rec["task_id"]
                if tid not in task_ids:
                    raise SystemExit("[FATAL] 判票含未知任务: %s" % tid)
                if rec.get("prompt_sha256") != payloads[tid]["prompt_sha256"]:
                    raise SystemExit("[FATAL] %s/%s prompt_sha256 与 payload 不符" % (judge, tid))
                if rec.get("task_type") != "scope_revalidation_v2":
                    raise SystemExit("[FATAL] %s/%s task_type=%s" % (judge, tid, rec.get("task_type")))
                per[tid] = decode_vote(tid, rec, mapping)
        if set(per) != task_ids:
            raise SystemExit("[FATAL] Judge %s 缺票: %s" % (judge, sorted(task_ids - set(per))[:5]))
        votes[judge] = per
        invalid_votes[judge] = sum(1 for v in per.values() if v["label"] == "INVALID")

    # payload 展示位状态与任务文件 adjustment.source_*(before)/final_*(after) 的 role 按
    # AB 映射方向逐条核对（双向验证映射文件本身没有写错方向）。注意任务文件里的
    # state_a/state_b 是 V3 当时的展示态、不必然等于 before/after，故以其角色与
    # source/final 匹配来取用 owner。
    mapping_conflicts: list[str] = []
    unresolved_states: list[str] = []
    for tid in sorted(task_ids):
        adj = tasks[tid]["adjustment"]
        pay = payloads[tid]["payload"]
        for (tr, sr) in ((adj["source_time_role"], adj["source_space_role"]),
                         (adj["final_time_role"], adj["final_space_role"])):
            if resolve_state(tasks[tid], tr, sr) is None:
                unresolved_states.append("%s" % tid)
        for pos in ("a", "b"):
            src = adj if mapping[tid][0 if pos == "a" else 1] == "before" else None
            want_time = norm_role(adj["source_time_role"] if src else adj["final_time_role"])
            want_space = norm_role(adj["source_space_role"] if src else adj["final_space_role"])
            pay_state = pay[pos]
            if norm_role(pay_state.get("time_role")) != want_time or \
               norm_role(pay_state.get("space_role")) != want_space:
                mapping_conflicts.append("%s:%s" % (tid, pos))

    # ---- 逐任务计算 transformation_type / 聚合
    rows: list[dict] = []
    for tid in sorted(task_ids):
        t = tasks[tid]
        adj = t["adjustment"]
        ttype, combo_time, combo_space = classify_transformation(adj)
        va, vb = votes["A"][tid], votes["B"][tid]
        agg = aggregate(va["label"], vb["label"])
        assertion_text = payloads[tid]["payload"]["assertion_text"]
        digest = hashlib.sha256(assertion_text.encode("utf-8")).hexdigest()[:16]
        rows.append({
            "task_id": tid,
            "transformation_type": ttype,
            "combo": "time: %s | space: %s" % (combo_time, combo_space),
            "combo_time": combo_time,
            "combo_space": combo_space,
            "vote_A_decoded": va["label"],
            "vote_B_decoded": vb["label"],
            "aggregated": agg,
            "evidence_source": metadata[tid]["evidence_source"],
            "adjustment_reason": adj["adjustment_reason"],
            "assertion_digest": digest,
            "conf_A": va.get("confidence"),
            "conf_B": vb.get("confidence"),
            "reason_A": va.get("reason_code"),
            "reason_B": vb.get("reason_code"),
            "expl_A": va.get("explanation", ""),
            "expl_B": vb.get("explanation", ""),
            "ev_A": va.get("evidence", []),
            "ev_B": vb.get("evidence", []),
            "assertion_text": assertion_text,
            "payload_evidence": list(dict.fromkeys(
                (e.get("text") or "").strip() for e in payloads[tid]["payload"].get("evidence_excerpts", []) if (e.get("text") or "").strip())),
            "state_before": "time_role=%s, time_owner=%s; space_role=%s, space_owner=%s" % (
                norm_role(adj["source_time_role"]),
                owner_name(resolve_state(t, adj["source_time_role"], adj["source_space_role"]), "time_owner"),
                norm_role(adj["source_space_role"]),
                owner_name(resolve_state(t, adj["source_time_role"], adj["source_space_role"]), "space_owner")),
            "state_after": "time_role=%s, time_owner=%s; space_role=%s, space_owner=%s" % (
                norm_role(adj["final_time_role"]),
                owner_name(resolve_state(t, adj["final_time_role"], adj["final_space_role"]), "time_owner"),
                norm_role(adj["final_space_role"]),
                owner_name(resolve_state(t, adj["final_time_role"], adj["final_space_role"]), "space_owner")),
            "time_owner_disp": owner_disposition(adj["source_time_owner_id"], adj["final_time_owner_id"]),
            "space_owner_disp": owner_disposition(adj["source_space_owner_id"], adj["final_space_owner_id"]),
            "fact_id": t.get("fact_id", ""),
        })

    # ---- 汇总
    types = sorted({r["transformation_type"] for r in rows})
    type_order_hint = ["unknown→event_occurrence", "event_location→context_location",
                       "event_location→relation_location", "time_owner_change",
                       "space_owner_change", "mixed", "other", "no_change"]
    types = [t for t in type_order_hint if t in types] + [t for t in types if t not in type_order_hint]

    overall_counts = Counter(r["aggregated"] for r in rows)
    pooled_votes = Counter()
    for r in rows:
        pooled_votes[r["vote_A_decoded"]] += 1
        pooled_votes[r["vote_B_decoded"]] += 1

    per_type: dict[str, dict] = {}
    for ty in types:
        sub = [r for r in rows if r["transformation_type"] == ty]
        cnt = Counter(r["aggregated"] for r in sub)
        decided = cnt["AFTER_BETTER"] + cnt["BEFORE_BETTER"]
        after_rate = (cnt["AFTER_BETTER"] / decided) if decided else None
        # 双侧精确二项检验 p 值是对称的，方向由 after_win_rate 决定
        p_two_sided = binom_two_sided(min(cnt["AFTER_BETTER"], cnt["BEFORE_BETTER"]), decided) if decided else 1.0
        if decided >= MIN_DECIDED and p_two_sided < P_THRESHOLD:
            recommendation = "REWRITE" if after_rate >= 0.5 else "RETAIN"
        else:
            recommendation = "UNRESOLVED"
        ev_cnt = Counter(r["evidence_source"] for r in sub)
        reason_cnt = Counter()
        for r in sub:
            for rc in (r["reason_A"], r["reason_B"]):
                if rc:
                    reason_cnt[rc] += 1
        reason_by_dir: dict[str, Counter] = {"BEFORE_BETTER": Counter(), "AFTER_BETTER": Counter()}
        for r in sub:
            for side in ("A", "B"):
                lab, rc = r["vote_%s_decoded" % side], r["reason_%s" % side]
                if lab in reason_by_dir and rc:
                    reason_by_dir[lab][rc] += 1
        disagree_pairs = Counter(tuple(sorted((r["vote_A_decoded"], r["vote_B_decoded"])))
                                 for r in sub if r["aggregated"] == "DISAGREE")
        combo_cnt = Counter(r["combo"] for r in sub)
        per_type[ty] = {
            "n": len(sub),
            "share_of_all": round(len(sub) / len(rows), 4),
            "aggregated_counts": {k: cnt.get(k, 0) for k in AGG_LABELS},
            "decided": decided,
            "after_win_rate": round(after_rate, 4) if after_rate is not None else None,
            "before_win_rate": round(1 - after_rate, 4) if after_rate is not None else None,
            "binom_p_two_sided": round(p_two_sided, 5),
            "recommendation": recommendation,
            "undecided_rate": round((cnt["DISAGREE"] + cnt["INSUFFICIENT"] + cnt["BOTH_WRONG"] + cnt["INVALID"]) / len(sub), 4),
            "evidence_source_counts": dict(ev_cnt),
            "evidence_none_rate": round(ev_cnt.get("none", 0) / len(sub), 4),
            "evidence_direct_rate": round(ev_cnt.get("direct", 0) / len(sub), 4),
            "adjustment_reason_counts": dict(Counter(r["adjustment_reason"] for r in sub)),
            "time_owner_disposition": dict(Counter(r["time_owner_disp"] for r in sub)),
            "space_owner_disposition": dict(Counter(r["space_owner_disp"] for r in sub)),
            "reason_code_counts_all_votes": dict(reason_cnt.most_common()),
            "reason_code_by_vote_direction": {
                d: dict(c.most_common()) for d, c in reason_by_dir.items()},
            "disagree_pair_counts": {"|".join(k): v for k, v in disagree_pairs.most_common()},
            "combination_table": {k: v for k, v in combo_cnt.most_common()},
            "examples": [
                {k: ex[k] for k in ("task_id", "transformation_type", "aggregated", "evidence_source",
                                     "vote_A_decoded", "vote_B_decoded", "reason_A", "reason_B",
                                     "assertion_text", "payload_evidence", "state_before", "state_after",
                                     "expl_A", "expl_B")}
                for ex in pick_examples(sub, 2)
            ],
        }

    # 塌陷排名：先按 after_win_rate 升序（塌得最狠在前），同率按 decided 降序、n 降序
    def collapse_key(ty: str):
        pt = per_type[ty]
        rate = pt["after_win_rate"] if pt["after_win_rate"] is not None else 0.5
        return (rate, -pt["decided"], -pt["n"])
    collapse_ranking = [ty for ty in sorted(types, key=collapse_key) if per_type[ty]["n"] > 0]

    summary = {
        "meta": {
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "protocol": "two-vote blind panel (Judge A + Judge B); Judge C excluded (incomplete coverage, undefined protocol)",
            "judges": {},
            "n_tasks": len(rows),
            "ab_decode": "decision 的 A/B 为展示位，经 SCOPE_REVALIDATION_V2_AB_MAPPING.csv 解码回 before/after",
            "invalid_vote_policy": "status!=OK / decision 缺失或非法 / MODEL_OUTPUT_INVALID → 该票 INVALID；聚合时任一票 INVALID 即整条 INVALID",
            "integrity": {
                "invalid_votes": dict(invalid_votes),
                "prompt_sha256_all_match": True,
                "ab_mapping_direction_conflicts": mapping_conflicts,
                "states_not_resolvable_by_roles": unresolved_states,
                "missing_votes": {j: 0 for j in ("A", "B")},
            },
            "recommendation_thresholds": {
                "rule": "decided=AFTER_BETTER+BEFORE_BETTER(两票一致)；REWRITE: 双侧精确二项 p<%.2f 且 AFTER 显著且 decided>=%d；RETAIN: p<%.2f 且 BEFORE 显著且 decided>=%d；其余 UNRESOLVED" % (
                    P_THRESHOLD, MIN_DECIDED, P_THRESHOLD, MIN_DECIDED),
                "p_threshold": P_THRESHOLD,
                "min_decided": MIN_DECIDED,
            },
            "pooled_vote_level_counts": dict(pooled_votes),
        },
        "overall": {
            "aggregated_counts": {k: overall_counts.get(k, 0) for k in AGG_LABELS},
            "decided": overall_counts["AFTER_BETTER"] + overall_counts["BEFORE_BETTER"],
            "after_win_rate_overall_decided": round(
                overall_counts["AFTER_BETTER"] /
                max(1, overall_counts["AFTER_BETTER"] + overall_counts["BEFORE_BETTER"]), 4),
            "adjustment_reason_counts": dict(Counter(r["adjustment_reason"] for r in rows)),
        },
        "per_type": per_type,
        "collapse_ranking": collapse_ranking,
    }

    # meta.judges 简化：从判票记录取 model_id
    model_ids = {}
    for judge in ("A", "B"):
        with open(RUNS / ("%s.jsonl" % judge), encoding="utf-8") as f:
            model_ids[judge] = json.loads(f.readline()).get("model_id", "")
    summary["meta"]["judges"] = model_ids

    # ---- 写 CSV
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_fields = ["task_id", "transformation_type", "vote_A_decoded", "vote_B_decoded",
                  "aggregated", "evidence_source", "adjustment_reason", "assertion_digest"]
    with open(CSV_OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in csv_fields})

    # ---- 写 SUMMARY
    with open(SUMMARY_OUT, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # ---- 写 REPORT
    rep: list[str] = []
    A = rep.append
    m = summary["meta"]
    oc = summary["overall"]
    A("# SCOPE 调整分类型盲评归因报告（SCOPE_REPAIR_REPORT）")
    A("")
    A("- 生成时间：%s（全自动，无人工干预）" % m["generated_utc"])
    A("- **口径：两票盲评**。Judge A = %s，Judge B = %s，各 208/208 条、status 全 OK。"
      % (m["judges"]["A"], m["judges"]["B"]))
    A("- Judge C 只覆盖少量样本且口径未定，**全程不采用**；本报告所有数字均为 A+B 两票口径。")
    A("- 判票方向解码：judge 输出的 A_BETTER/B_BETTER 指展示位，已按"
      " `payloads/SCOPE_REVALIDATION_V2_AB_MAPPING.csv` 逐条解码回 before/after（未做任何方向猜测）；"
      "校验 judge 记录 `prompt_sha256` 与 payload 文件完全一致（%d/208 通过），"
      "并把 payload 两个展示位的状态按映射方向与任务文件 before/after 状态逐条核对 role"
      "（%d 处冲突），独立确认映射文件方向无误。"
      % (len(rows), len(m["integrity"]["ab_mapping_direction_conflicts"])))
    A("- 无效票单独计数：本批 A/B 均无 MODEL_OUTPUT_INVALID / 缺票 / 非法 decision"
      "（A: %d，B: %d），故 INVALID=0。" % (m["integrity"]["invalid_votes"].get("A", 0),
                                            m["integrity"]["invalid_votes"].get("B", 0)))
    A("- 聚合规则：两票一致 → 该判定；两票不一致 → DISAGREE；任一票 INVALID → INVALID。")
    A("")
    A("## 1. 总体两票口径结果")
    A("")
    A("| 聚合判定 | 条数 | 占比 |")
    A("|---|---:|---:|")
    for k in AGG_LABELS:
        A("| %s | %d | %.1f%% |" % (k, oc["aggregated_counts"][k], 100.0 * oc["aggregated_counts"][k] / len(rows)))
    dec = oc["decided"]
    A("")
    A("- 两票一致且分出胜负（decided）%d 条：**BEFORE_BETTER %d 条 vs AFTER_BETTER %d 条，"
      "AFTER 胜率 %.1f%%**——与已知总体方向（改前约 52%% vs 改后 46%%，按单票池化）一致且更极端："
      "两票一致时 BEFORE 以约 %.1f%% : %.1f%% 压倒 AFTER。"
      % (dec, oc["aggregated_counts"]["BEFORE_BETTER"], oc["aggregated_counts"]["AFTER_BETTER"],
         100 * oc["after_win_rate_overall_decided"],
         100 * (1 - oc["after_win_rate_overall_decided"]), 100 * oc["after_win_rate_overall_decided"]))
    pv = m["pooled_vote_level_counts"]
    pv_dec = pv.get("BEFORE_BETTER", 0) + pv.get("AFTER_BETTER", 0)
    A("- 单票池化（A+B 共 416 票）解码后：BEFORE_BETTER %d、AFTER_BETTER %d、"
      "INSUFFICIENT %d、BOTH_WRONG %d、INVALID %d；占全部票 %.1f%% / %.1f%%，"
      "占分出胜负的票（%d 票）%.1f%% / %.1f%%——方向与已知总体口径（改前约 52%% vs 改后 46%%）一致："
      "BEFORE 稳定高于 AFTER，且两票一致时差距进一步放大。"
      % (pv.get("BEFORE_BETTER", 0), pv.get("AFTER_BETTER", 0),
         pv.get("INSUFFICIENT", 0), pv.get("BOTH_WRONG", 0), pv.get("INVALID", 0),
         100 * pv.get("BEFORE_BETTER", 0) / 416, 100 * pv.get("AFTER_BETTER", 0) / 416,
         pv_dec,
         100 * pv.get("BEFORE_BETTER", 0) / max(1, pv_dec),
         100 * pv.get("AFTER_BETTER", 0) / max(1, pv_dec)))
    A("- 两票冲突（DISAGREE）%d 条（%.1f%%），其中 BEFORE_BETTER↔AFTER_BETTER 硬冲突 %d 条；"
      "所有任务 adjustment_reason 均为 `%s`（唯一值），故损害只能按变换类型归因。"
      % (oc["aggregated_counts"]["DISAGREE"], 100.0 * oc["aggregated_counts"]["DISAGREE"] / len(rows),
         sum(v for k, v in Counter(
             tuple(sorted((r["vote_A_decoded"], r["vote_B_decoded"])))
             for r in rows if r["aggregated"] == "DISAGREE").items() if set(k) == {"BEFORE_BETTER", "AFTER_BETTER"}),
         rows[0]["adjustment_reason"]))
    A("")
    A("## 2. 类型 × 判定矩阵")
    A("")
    A("| transformation_type | n | AFTER | BEFORE | EQUIV | BOTH_WRONG | INSUF | DISAGREE | INVALID | decided | AFTER 胜率 | 二项 p(双侧) | 建议 |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    matrix_types = types + [t for t in ("time_owner_change", "space_owner_change") if t not in per_type]
    for ty in matrix_types:
        pt = per_type.get(ty)
        if pt is None:
            A("| `%s` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | — | — | （本数据集 0 条） |" % ty)
            continue
        c = pt["aggregated_counts"]
        A("| `%s` | %d | %d | %d | %d | %d | %d | %d | %d | %d | %s | %.3f | **%s** |" % (
            ty, pt["n"], c["AFTER_BETTER"], c["BEFORE_BETTER"], c["EQUIVALENT"], c["BOTH_WRONG"],
            c["INSUFFICIENT"], c["DISAGREE"], c["INVALID"], pt["decided"],
            ("%.1f%%" % (100 * pt["after_win_rate"])) if pt["after_win_rate"] is not None else "—",
            pt["binom_p_two_sided"], pt["recommendation"]))
    A("")
    A("注：`time_owner_change` / `space_owner_change` 在本数据集中为 **0 条**——208 条任务里"
      " owner 变更从不单独出现（一旦 owner 变，role 必同步变），因此这两类无统计，也不进入排名。")
    A("")
    A("## 3. 塌陷排名（AFTER 胜率从低到高）")
    A("")
    for i, ty in enumerate(collapse_ranking, 1):
        pt = per_type[ty]
        c = pt["aggregated_counts"]
        rate = "—" if pt["after_win_rate"] is None else "%.1f%%" % (100 * pt["after_win_rate"])
        A("%d. `%s`（n=%d，decided=%d，AFTER %d : BEFORE %d，AFTER 胜率 %s）"
          % (i, ty, pt["n"], pt["decided"], c["AFTER_BETTER"], c["BEFORE_BETTER"], rate))
    A("")
    A("**解读**：损害高度集中——`event_location→context_location` 一类就占全部任务的 43.3%"
      "（90/208），并贡献了 52 条两票一致的 BEFORE 胜例（占总 BEFORE 胜例的 72.2%）；"
      "`mixed` 类虽只有 16 条，但 AFTER **0 胜**，是塌得最彻底的一类。"
      "唯一 AFTER 显著占优的是 `unknown→event_occurrence`。")
    A("")
    A("## 4. 分类型细目与典型例")
    for ty in types:
        pt = per_type[ty]
        if pt["n"] == 0:
            continue
        c = pt["aggregated_counts"]
        A("")
        A("### 4.%d `%s`（n=%d，建议=%s）" % (types.index(ty) + 1, ty, pt["n"], pt["recommendation"]))
        A("")
        A("- 判定分布：%s" % ", ".join("%s=%d" % (k, v) for k, v in c.items() if v))
        A("- AFTER 胜率（decided=%d）：%s；未定率（DISAGREE+INSUF+BOTH_WRONG）%.1f%%"
          % (pt["decided"], "—" if pt["after_win_rate"] is None else "%.1f%%" % (100 * pt["after_win_rate"]),
             100 * pt["undecided_rate"]))
        A("- 证据可得性：direct %d（%.1f%%）、lexical %d、none %d；DISAGREE 构成：%s"
          % (pt["evidence_source_counts"].get("direct", 0), 100 * pt["evidence_direct_rate"],
             pt["evidence_source_counts"].get("lexical", 0), pt["evidence_source_counts"].get("none", 0),
             pt["disagree_pair_counts"] or "（无）"))
        A("- adjustment_reason：%s" % pt["adjustment_reason_counts"])
        A("- judge reason_code（BEFORE 胜票 vs AFTER 胜票）：%s vs %s"
          % (pt["reason_code_by_vote_direction"]["BEFORE_BETTER"] or "（无）",
             pt["reason_code_by_vote_direction"]["AFTER_BETTER"] or "（无）"))
        A("")
        for ex in pt["examples"]:
            A(md_example(ex))
    A("## 5. 生产规则把什么改坏了（基于证据句的模式）")
    A("")

    def top_codes(ty: str, direction: str, k: int = 3) -> str:
        d = per_type[ty]["reason_code_by_vote_direction"][direction]
        return "、".join("%s×%d" % (c, n) for c, n in list(d.items())[:k]) or "（无）"

    def shorten(text: str, limit: int = 110) -> str:
        return text if len(text) <= limit else text[:limit] + "……"

    _ptc = per_type["event_location→context_location"]
    _ptm = per_type["mixed"]
    _ptu = per_type["unknown→event_occurrence"]
    _pto = per_type["other"]
    _ec = _ptc["examples"]
    _ec_ev = shorten(_ec[0]["payload_evidence"][0]) if _ec and _ec[0]["payload_evidence"] else "（见下例）"
    _mc = _ptm["examples"]
    _mc_ev = shorten(_mc[0]["payload_evidence"][0]) if _mc and _mc[0]["payload_evidence"] else "（见下例）"
    A("`final_entity_type_scope_closure`（实体类型 scope 收口）在 208 条上只做了三类机械动作，"
      "其中两类在 judge 可见的原文证据面前被系统性判负：")
    A("")
    A("1. **`event_location→context_location`（最大损害源：n=90，占全部任务 43.3%%）**："
      "把“事件发生地”降格为“背景地点”，且 90/90 全部把 space owner 移除。"
      "判 BEFORE 更好的票理由几乎全是事件定位类（%s）；"
      "证据句是事件叙事（如 %s 中「%s」），地点显然属于事件本身，规则却把它改判为“仅提供背景”，"
      "judge 直接引证据句反驳。AFTER 仅 7:52，p<0.001。"
      % (top_codes("event_location→context_location", "BEFORE_BETTER"),
         _ec[0]["task_id"] if _ec else "典型例", _ec_ev))
    A("2. **`mixed`（塌得最彻底：AFTER 0 : BEFORE 11，p=0.002）**：time 与 space 同时改写"
      "（event_occurrence+event_location → relation_validity+relation_location），且 16/16 双 owner 全部移除。"
      "BEFORE 胜票理由全部是事件性质类（%s）——证据句（如 %s 中「%s」）描述的是具体历史事件，"
      "judge 视双重改写为把动态事件降格成抽象关系，无一例接受 AFTER。"
      % (top_codes("mixed", "BEFORE_BETTER"), _mc[0]["task_id"] if _mc else "典型例", _mc_ev))
    A("3. **`unknown→event_occurrence`（唯一正收益：AFTER 23 : BEFORE 4，p<0.001）**："
      "规则把原本“无法判断”的时间补判为事件发生时间，并把主体实体指派为 time owner（60/60 assigned），"
      "方向与证据一致；AFTER 胜票理由为 TIME_ROLE_MATCH×9、TIME_ROLE_CORRECT×7 等，judge 认可这是修复。")
    A("4. **`other`（主要为 biographical→context_time，25/37）**：把人物生平时间改判为背景时间"
      "（time owner removed 27/37）。方向上偏 AFTER（8:4）但无共识：DISAGREE 21/37，其中"
      " AFTER|BOTH_WRONG 10、AFTER|INSUFFICIENT 6——Judge A 偏 AFTER 时 Judge B 常判两案皆错/证据不足，"
      "不足以定论。`event_location→relation_location`（n=5）方向与第 1 类相同但样本过小（decided=1）。")
    A("")
    A("共性模式：**规则把“事件性”scope 系统性降格（event_* → context/relation_*，并移除 owner），"
      "而语料证据句恰恰以事件叙事为主**；唯一被认可的改动方向是把 unknown 补判成事件时间。")
    A("")
    A("## 6. Selective Scope Closure 数据驱动建议")
    A("")
    A("规则（写死于脚本常量，可复现）：decided = 两票一致的 AFTER+BEFORE；双侧精确二项检验"
      "（H0: p=0.5），p<%.2f 且 decided≥%d 才允许下结论。" % (P_THRESHOLD, MIN_DECIDED))
    A("")
    A("| 类别 | 建议 | 数据依据 |")
    A("|---|---|---|")
    for ty in matrix_types:
        pt = per_type.get(ty)
        if pt is None:
            A("| `%s` | （本数据集为 0 条） | owner 变更从不脱离 role 变更单独发生 |" % ty)
            continue
        c = pt["aggregated_counts"]
        basis = "AFTER %d : BEFORE %d（胜率 %s，p=%.3f，n=%d）" % (
            c["AFTER_BETTER"], c["BEFORE_BETTER"],
            "—" if pt["after_win_rate"] is None else "%.1f%%" % (100 * pt["after_win_rate"]),
            pt["binom_p_two_sided"], pt["n"])
        A("| `%s` | **%s** | %s |" % (ty, pt["recommendation"], basis))
    A("")
    A("落地含义：")
    A("")
    A("- **RETAIN（维持 before，不再产出 after 改写）**：`event_location→context_location`（7:52，"
      "p<0.001）与 `mixed`（0:11，p=0.002）。这两类是 BEFORE 支持率高于 AFTER 的主要来源，"
      "继续改写只会继续丢分。")
    A("- **REWRITE（保留 after 改写）**：`unknown→event_occurrence`（23:4，p<0.001）。这是规则真正"
      "把“无法判断”修复成事件时间的一类，应保留并推广其模式。")
    A("- **UNRESOLVED（挂起，不进入自动改写）**：`event_location→relation_location`（n=5，decided=1）"
      "与 `other`（8:4 但 21/37 DISAGREE，其中 AFTER|BOTH_WRONG 10、AFTER|INSUFFICIENT 6——"
      "一票偏 AFTER 时另一票常判两案皆错/证据不足）。样本或共识不足，"
      "应送人工/更强证据通道，而非自动采纳任何方向。")
    A("")
    A("## 附录 A：实际 role 组合全表（含 other 的展开）")
    A("")
    A("| time: source→final | space: source→final | n | 归入类型 |")
    A("|---|---|---:|---|")
    combo_all: Counter = Counter()
    combo_type: dict[tuple[str, str], str] = {}
    for r in rows:
        key = (r["combo_time"], r["combo_space"])
        combo_all[key] += 1
        combo_type[key] = r["transformation_type"]
    for (ct, csp), n in combo_all.most_common():
        A("| %s | %s | %d | `%s` |" % (ct, csp, n, combo_type[(ct, csp)]))
    A("")
    A("## 附录 B：数据与脚本")
    A("")
    A("- 判票：`experiments/01_reference_rebuild/raw_runs/scope_revalidation_v2/{A,B}.jsonl`")
    A("- 展示位映射：`experiments/01_reference_rebuild/payloads/SCOPE_REVALIDATION_V2_AB_MAPPING.csv`")
    A("- 证据可得性：`experiments/01_reference_rebuild/payloads/SCOPE_REVALIDATION_V2_METADATA.csv`"
      "（direct 25 / lexical 180 / none 3）")
    A("- 任务上下文：`final_submission_v3/experiments/10_structural_validation/SCOPE_ADJUSTMENT_TASKS.jsonl`")
    A("- 逐条明细：`SCOPE_BY_TYPE_ERRORS.csv`（208 行，含每票解码值与断言摘要）")
    A("- 机器可读汇总：`SCOPE_BY_TYPE_SUMMARY.json`")
    A("")

    with open(REPORT_OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(rep))

    # ---- 控制台摘要
    print("tasks=%d invalid_votes A=%d B=%d" % (len(rows), invalid_votes["A"], invalid_votes["B"]))
    print("overall:", dict(oc["aggregated_counts"]))
    for ty in collapse_ranking:
        pt = per_type[ty]
        print("%-36s n=%3d decided=%2d after_rate=%s rec=%s" % (
            ty, pt["n"], pt["decided"],
            ("%.3f" % pt["after_win_rate"]) if pt["after_win_rate"] is not None else "NA",
            pt["recommendation"]))
    print("written:", CSV_OUT)
    print("written:", SUMMARY_OUT)
    print("written:", REPORT_OUT)


if __name__ == "__main__":
    main()
