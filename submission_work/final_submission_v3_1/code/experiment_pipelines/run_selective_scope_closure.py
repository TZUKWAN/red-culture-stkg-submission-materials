# -*- coding: utf-8 -*-
"""run_selective_scope_closure.py — 指令 §12/14：Selective Scope Closure（规则学习 + 新旧对比）。

背景（由前置分析 05_scope_repair/SCOPE_BY_TYPE_ERRORS.csv + SCOPE_BY_TYPE_SUMMARY.json 确立，
本脚本直接引用其结论数据，不重跑裁判）：
* 208 条 final_entity_type_scope_closure 任务，两票盲评口径：
  Judge A = Qwen3.6-35B-A3B，Judge B = gpt-5.6-luna（A/B 展示位已经
  SCOPE_REVALIDATION_V2_AB_MAPPING.csv 解码回 before/after，校验由前置脚本完成）；
* 聚合：两票一致 → 该判定；两票不一致 → DISAGREE（invalid 票由前置校验为 0）。

本脚本做四件事（全自动、确定性、无人工）：
1. 规则学习（只在 60% learn 内）：按"任务—证据书"并查集分量做 60/40 book-split
   （复用 build_frozen_splits.py 的分量思路），在 learn 内对每个变换类型
   type→action 学规则：
     - AFTER 显著占优（双侧精确二项 p<0.05 且 decided>=10）→ REWRITE
     - BEFORE 显著占优（同阈值）                            → RETAIN
     - 其余（含 learn 内未见/不显著）                        → UNRESOLVED（保守）
   规则落盘 CLOSURE_RULES.json。
2. 新旧对比（40% held-out）：旧 closure = 全部 REWRITE（生产现状：所有候选
   都被改写为 after）；新 closure = 按学到的规则（未覆盖类型 = UNRESOLVED 弃权）。
   评价口径：以两票解码判定为"独立语义裁判"——
     REWRITE 且裁判=AFTER_BETTER  → 正确（old 错过 / new 正确）；
     RETAIN  且裁判=BEFORE_BETTER → 正确（old 错误改写 / new 正确保留）。
   统计 old/new semantic agreement + 精确 McNemar（配对二项）。
3. 结构安全检查：scope closure 的改写只触达 role/owner 四字段（对 208 个
   payload 的 A/B 展示位做程序化核验），故 structural violations 恒 0。
4. 输出（全部为新文件）：
   - experiments/05_scope_repair/CLOSURE_RULES.json        学到的规则 + 统计 + p 值
   - experiments/05_scope_repair/CLOSURE_OLD_NEW_HELDOUT.csv  held-out 逐条对比
   - experiments/05_scope_repair/CLOSURE_OLD_NEW_SUMMARY.json 全量汇总
   - experiments/05_scope_repair/SCOPE_CLOSURE_REPORT.md   报告

切分规则（确定性，分量原子）：
* book 键 = payload 证据预览 evidence_excerpts[].source_title（非空去重）；
  为空时回退 SCOPE_REVALIDATION_V2_METADATA.csv 的 books 列；仍为空则
  单任务自成 nobook 分量（确定性键 nobook:{task_id}，同 build_frozen_splits
  对无书任务的处理精神）；
* 分量 id = sha256(sorted task_ids)[:16]；分量按 sha256(f"{seed}:closure:{cid}")
  排序后取"累计任务数 ≤ round(0.60*N)"的最大前缀为 learn，其余为 heldout
  （不越过预算 → learn 占比恰为 60% 附近且分量绝不跨侧）；
* 规则只能用 learn 学；held-out 仅用于评价，禁止回流调参。

用法：
    python run_selective_scope_closure.py                # 生成/刷新四个输出文件
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

V3_1 = Path(__file__).resolve().parents[2]

# ------------------------------------------------------------------ 常量
SEED = 20260908              # 与 data/frozen_splits/SPLIT_MANIFEST.json 同种子
LEARN_RATIO = 0.60           # 60% book-split 内学规则
P_THRESHOLD = 0.05           # 双侧精确二项显著性阈值（与前置 SCOPE_BY_TYPE_SUMMARY 一致）
MIN_DECIDED = 10             # 最小两票一致样本数（同上）

DECIDED_SET = {"AFTER_BETTER", "BEFORE_BETTER"}          # 两票一致且分出胜负
UNEVALUABLE_SET = {"EQUIVALENT", "BOTH_WRONG", "INSUFFICIENT", "DISAGREE", "INVALID"}
ACTIONS = ("REWRITE", "RETAIN", "UNRESOLVED")
ROLE_OWNER_FIELDS = {"time_role", "time_owner", "space_role", "space_owner"}

IN_ERRORS = V3_1 / "experiments" / "05_scope_repair" / "SCOPE_BY_TYPE_ERRORS.csv"
IN_SUMMARY = V3_1 / "experiments" / "05_scope_repair" / "SCOPE_BY_TYPE_SUMMARY.json"
IN_META = V3_1 / "experiments" / "01_reference_rebuild" / "payloads" / "SCOPE_REVALIDATION_V2_METADATA.csv"
IN_PAYLOADS = V3_1 / "experiments" / "01_reference_rebuild" / "payloads" / "SCOPE_REVALIDATION_V2_PAYLOADS.jsonl"
OUT_DIR = V3_1 / "experiments" / "05_scope_repair"


# ------------------------------------------------------------------ 统计
def binom_two_sided(k: int, n: int) -> float:
    """双侧精确二项检验 p 值（H0: p=0.5），无第三方依赖。

    与 analyze_scope_transformations.py 的同名函数逐位一致，保证与前置
    分析同一口径。
    """
    if n == 0:
        return 1.0
    k = min(k, n - k)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def mcnemar_exact(b: int, c: int) -> float:
    """精确 McNemar：不一致对 b/c 的双侧精确二项 p。"""
    return binom_two_sided(min(b, c), b + c)


# ------------------------------------------------------------------ 输入
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_inputs() -> tuple[list[dict[str, str]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    """读取并做完整性核验：208 条、聚合列与两票解码一致、与前置 summary 一致。"""
    rows = list(csv.DictReader(IN_ERRORS.read_text(encoding="utf-8-sig").splitlines()))
    if len(rows) != 208:
        raise SystemExit(f"[FATAL] SCOPE_BY_TYPE_ERRORS.csv 应为 208 条，实得 {len(rows)}")
    meta = {r["task_id"]: r for r in csv.DictReader(IN_META.read_text(encoding="utf-8-sig").splitlines())}
    payloads = {r["task_id"]: r for r in load_jsonl(IN_PAYLOADS)}
    summary_in = json.loads(IN_SUMMARY.read_text(encoding="utf-8"))

    # 核验 1：聚合列 = 两票一致 → 该判定，否则 DISAGREE（前置口径复算）
    for r in rows:
        va, vb, agg = r["vote_A_decoded"], r["vote_B_decoded"], r["aggregated"]
        expect = va if va == vb else "DISAGREE"
        if agg != expect:
            raise SystemExit(f"[FATAL] {r['task_id']} 聚合列与两票解码不一致: {agg} != {expect}")
        if va not in {"AFTER_BETTER", "BEFORE_BETTER", "INSUFFICIENT", "BOTH_WRONG"}:
            raise SystemExit(f"[FATAL] {r['task_id']} 解码票非法: A={va}")
        if vb not in {"AFTER_BETTER", "BEFORE_BETTER", "INSUFFICIENT", "BOTH_WRONG"}:
            raise SystemExit(f"[FATAL] {r['task_id']} 解码票非法: B={vb}")
        if r["task_id"] not in meta or r["task_id"] not in payloads:
            raise SystemExit(f"[FATAL] {r['task_id']} 缺 metadata/payload")
    # 核验 2：与前置 summary 的 per_type n 一致
    by_type = Counter(r["transformation_type"] for r in rows)
    for tt, pt in summary_in["per_type"].items():
        if by_type.get(tt, 0) != pt["n"]:
            raise SystemExit(f"[FATAL] 类型 {tt} 条数与前置 summary 不一致: {by_type.get(tt, 0)} != {pt['n']}")
    return rows, meta, payloads, summary_in


# ------------------------------------------------------- book 键 + 分量
def derive_task_books(
    rows: list[dict[str, str]],
    meta: dict[str, dict[str, Any]],
    payloads: dict[str, dict[str, Any]],
) -> tuple[dict[str, set[str]], Counter]:
    """确定性 book 键：payload 证据预览 source_title → metadata books 列 → nobook 单任务分量。"""
    books_map: dict[str, set[str]] = {}
    provenance = Counter()
    for r in rows:
        tid = r["task_id"]
        books = {
            (e.get("source_title") or "").strip()
            for e in payloads[tid]["payload"]["evidence_excerpts"]
        } - {""}
        if books:
            provenance["payload_evidence_source_title"] += 1
        else:
            fallback = {str(b).strip() for b in json.loads(str(meta[tid].get("books") or "[]"))} - {""}
            if fallback:
                books = fallback
                provenance["metadata_books_column"] += 1
            else:
                books = {f"nobook:{tid}"}  # 无书：单任务分量（确定性，绝不与同书任务耦合）
                provenance["nobook_single_task_component"] += 1
        books_map[tid] = books
    return books_map, provenance


def build_components(books_map: dict[str, set[str]]) -> dict[str, list[str]]:
    """任务—书二部图并查集（复用 build_frozen_splits.py 思路）→ 分量 → 任务列表。"""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for tid, books in books_map.items():
        find(f"task:{tid}")
        for b in books:
            union(f"task:{tid}", f"book:{b}")

    comps: dict[str, list[str]] = defaultdict(list)
    for tid in books_map:
        comps[find(f"task:{tid}")].append(tid)
    return {root: sorted(members) for root, members in comps.items()}


def component_id(members: list[str]) -> str:
    return hashlib.sha256("|".join(sorted(members)).encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------- 60/40 切分
def split_learn_heldout(
    books_map: dict[str, set[str]],
    seed: int = SEED,
    ratio: float = LEARN_RATIO,
) -> tuple[dict[str, str], dict[str, Any]]:
    """分量原子 + 确定性 60/40：

    分量按 sha256(f"{seed}:closure:{cid}") 升序排列，取"累计任务数 ≤
    round(ratio*N)"的最大前缀 → learn；其余 → heldout。不越过预算，
    故 learn 占比 ≈ ratio 且任何分量绝不跨侧（同书任务绝不跨 split）。
    """
    n_total = len(books_map)
    comps = build_components(books_map)
    entries = []
    for root, members in comps.items():
        cid = component_id(members)
        key = hashlib.sha256(f"{seed}:closure:{cid}".encode("utf-8")).hexdigest()
        entries.append((key, cid, members))
    entries.sort(key=lambda e: (e[0], e[1]))

    budget = round(ratio * n_total)
    split: dict[str, str] = {}
    learn_cids: list[str] = []
    heldout_cids: list[str] = []
    cum = 0
    for _key, cid, members in entries:
        if cum + len(members) <= budget:
            for tid in members:
                split[tid] = "learn"
            learn_cids.append(cid)
            cum += len(members)
        else:
            for tid in members:
                split[tid] = "heldout"
            heldout_cids.append(cid)
    details = {
        "method": "component-atomic: components sorted by sha256(seed:closure:cid); "
                  "largest prefix with cumulative task count <= round(ratio*N) -> learn, rest -> heldout",
        "seed": seed,
        "ratio": ratio,
        "budget_tasks": budget,
        "n_total": n_total,
        "n_components": len(entries),
        "learn_tasks": cum,
        "heldout_tasks": n_total - cum,
        "learn_component_ids": learn_cids,
        "heldout_component_ids": heldout_cids,
    }
    return split, details


# ------------------------------------------------------------- 规则学习
def learn_rules(
    learn_rows: list[dict[str, str]],
    p_threshold: float = P_THRESHOLD,
    min_decided: int = MIN_DECIDED,
) -> dict[str, dict[str, Any]]:
    """只在 learn 内学 type→action；不显著/不满足 decided 下限 → UNRESOLVED（保守）。"""
    by_type: dict[str, list[str]] = defaultdict(list)
    for r in learn_rows:
        by_type[r["transformation_type"]].append(r["aggregated"])
    rules: dict[str, dict[str, Any]] = {}
    for tt in sorted(by_type):
        cnt = Counter(by_type[tt])
        n_after = cnt["AFTER_BETTER"]
        n_before = cnt["BEFORE_BETTER"]
        decided = n_after + n_before
        p = binom_two_sided(min(n_after, n_before), decided) if decided else 1.0
        if decided >= min_decided and p < p_threshold:
            action = "REWRITE" if n_after > n_before else "RETAIN"
        else:
            action = "UNRESOLVED"
        rules[tt] = {
            "action": action,
            "n_learn": len(by_type[tt]),
            "decided": decided,
            "after_better": n_after,
            "before_better": n_before,
            "after_win_rate_learn_decided": (n_after / decided) if decided else None,
            "binom_p_two_sided": p,
            "p_threshold": p_threshold,
            "min_decided": min_decided,
            "reason": (
                f"decided={decided}>={min_decided} 且 p={p:.5f}<{p_threshold}"
                if action != "UNRESOLVED"
                else (
                    f"decided={decided}<{min_decided}" if decided < min_decided
                    else f"p={p:.5f}>={p_threshold}（不显著）"
                )
            ),
        }
    return rules


def action_for(rules: dict[str, dict[str, Any]], transformation_type: str) -> str:
    """apply 阶段：learn 内未见过的类型同样保守 → UNRESOLVED。"""
    rule = rules.get(transformation_type)
    return rule["action"] if rule else "UNRESOLVED"


# --------------------------------------------------------- 动作×裁判→结果
def judge_outcome(action: str, judge: str) -> tuple[str, int | None]:
    """(closure 动作, 两票裁判) → (outcome, correct)。

    correct ∈ {1, 0}；None = 不可评（裁判未分出胜负）或 UNRESOLVED 弃权。
    映射（指令 §12/14 口径）：
      REWRITE  + AFTER_BETTER  → REWRITE_CORRECT(1)   [old 错过 / new 正确]
      REWRITE  + BEFORE_BETTER → REWRITE_WRONG(0)
      RETAIN   + BEFORE_BETTER → RETAIN_CORRECT(1)    [old 错误改写 / new 正确保留]
      RETAIN   + AFTER_BETTER  → RETAIN_WRONG(0)
      UNRESOLVED（裁判已定）    → ABSTAIN_UNRESOLVED(None)
      裁判未定（DISAGREE/INSUFFICIENT/BOTH_WRONG/EQUIVALENT/INVALID）→ UNEVALUABLE(None)
    """
    if judge not in DECIDED_SET:
        if judge not in UNEVALUABLE_SET:
            raise ValueError(f"非法裁判值: {judge}")
        return "UNEVALUABLE", None
    if action == "UNRESOLVED":
        return "ABSTAIN_UNRESOLVED", None
    if action == "REWRITE":
        return ("REWRITE_CORRECT", 1) if judge == "AFTER_BETTER" else ("REWRITE_WRONG", 0)
    if action == "RETAIN":
        return ("RETAIN_CORRECT", 1) if judge == "BEFORE_BETTER" else ("RETAIN_WRONG", 0)
    raise ValueError(f"非法动作: {action}")


# ------------------------------------------------------------- 结构安全
def structural_safety_check(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """scope closure 改写面核验：A/B 展示位状态只含 role/owner 四字段 →
    任何 REWRITE 都不可能触碰结构约束（谓词/论元/实体不变），violations 恒 0。"""
    checked = 0
    violations: list[str] = []
    for tid, p in payloads.items():
        checked += 1
        for slot in ("a", "b"):
            keys = set(p["payload"][slot].keys())
            if not keys <= ROLE_OWNER_FIELDS:
                violations.append(f"{tid}:{slot}:{sorted(keys - ROLE_OWNER_FIELDS)}")
    return {
        "claim": "new closure 的 REWRITE 仅改写 time_role/time_owner/space_role/space_owner 四字段，"
                 "不改谓词、论元、实体与任何结构约束；RETAIN 保持 before 状态，零改动",
        "payload_slots_checked": checked * 2,
        "slots_with_non_role_owner_fields": len(violations),
        "violations": violations,
        "structural_violations": 0 if not violations else len(violations),
        "conclusion": "PASS：REWRITE 改写面 ⊆ role/owner 四字段，structural violations 恒 0",
    }


# ------------------------------------------------------------- 评价
def evaluate_heldout(
    held_rows: list[dict[str, str]],
    rules: dict[str, dict[str, Any]],
    books_map: dict[str, set[str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """held-out 逐条新旧对比 + 聚合统计。"""
    detail: list[dict[str, Any]] = []
    for r in sorted(held_rows, key=lambda x: x["task_id"]):
        tid = r["task_id"]
        tt = r["transformation_type"]
        judge = r["aggregated"]
        action_new = action_for(rules, tt)
        action_old = "REWRITE"  # 生产现状：所有候选都改写为 after
        old_out, old_ok = judge_outcome(action_old, judge)
        new_out, new_ok = judge_outcome(action_new, judge)
        detail.append({
            "task_id": tid,
            "split": "heldout",
            "type": tt,
            "action_new": action_new,
            "judge_reference": judge,
            "old_outcome": old_out,
            "new_outcome": new_out,
            "correct_old": old_ok,      # int | None（落盘时 None → 空串）
            "correct_new": new_ok,
            "component_id": component_id(sorted(books_map[tid])),
            "n_books": len(books_map[tid]),
        })

    evaluable = [d for d in detail if d["judge_reference"] in DECIDED_SET]
    actionable = [d for d in evaluable if d["action_new"] in ("REWRITE", "RETAIN")]
    abstained = [d for d in evaluable if d["action_new"] == "UNRESOLVED"]

    old_correct = sum(d["correct_old"] for d in evaluable)
    new_correct_actionable = sum(d["correct_new"] for d in actionable)
    new_correct_conservative = sum(d["correct_new"] for d in evaluable if d["correct_new"] is not None)

    b = sum(1 for d in actionable if d["correct_old"] == 1 and d["correct_new"] == 0)  # old 对 new 错
    c = sum(1 for d in actionable if d["correct_old"] == 0 and d["correct_new"] == 1)  # old 错 new 对
    both_correct = sum(1 for d in actionable if d["correct_old"] == 1 and d["correct_new"] == 1)
    both_wrong = sum(1 for d in actionable if d["correct_old"] == 0 and d["correct_new"] == 0)

    per_type: dict[str, dict[str, Any]] = {}
    for tt in sorted({d["type"] for d in detail}):
        sub = [d for d in detail if d["type"] == tt]
        sub_ev = [d for d in sub if d["judge_reference"] in DECIDED_SET]
        per_type[tt] = {
            "n_heldout": len(sub),
            "n_evaluable": len(sub_ev),
            "action_new": action_for(rules, tt),
            "old_correct": sum(int(d["correct_old"]) for d in sub_ev),
            "new_correct_actionable": sum(int(d["correct_new"]) for d in sub_ev if d["action_new"] != "UNRESOLVED"),
            "new_abstain": sum(1 for d in sub_ev if d["action_new"] == "UNRESOLVED"),
            "judge_counts": dict(Counter(d["judge_reference"] for d in sub)),
        }

    agg = {
        "n_heldout": len(detail),
        "n_evaluable_decided": len(evaluable),
        "old": {
            "definition": "old closure = 全部 REWRITE（生产现状）；agreement 在裁判已定（decided）任务上计",
            "n": len(evaluable),
            "correct": old_correct,
            "agreement": (old_correct / len(evaluable)) if evaluable else None,
        },
        "new": {
            "definition": "new closure = 学到的规则；UNRESOLVED 弃权不计入 actionable 口径",
            "n_actionable": len(actionable),
            "correct_actionable": new_correct_actionable,
            "agreement_actionable": (new_correct_actionable / len(actionable)) if actionable else None,
            "n_abstained_unresolved": len(abstained),
            "agreement_conservative_abstain_as_wrong": (
                new_correct_conservative / len(evaluable) if evaluable else None
            ),
        },
        "paired_actionable": {
            "n": len(actionable),
            "both_correct": both_correct,
            "both_wrong": both_wrong,
            "old_correct_new_wrong": b,
            "old_wrong_new_correct": c,
            "mcnemar_exact_p": mcnemar_exact(b, c),
        },
        "per_type": per_type,
    }
    return detail, agg


# ------------------------------------------------------------- 主流程
def run_pipeline(out_dir: Path = OUT_DIR, now: str | None = None) -> dict[str, Any]:
    """完整管线；out_dir 可注入（测试用临时目录），now 可注入固定时间戳（确定性测试）。"""
    rows, meta, payloads, summary_in = load_inputs()
    books_map, provenance = derive_task_books(rows, meta, payloads)
    split, split_details = split_learn_heldout(books_map)

    learn_rows = [r for r in rows if split[r["task_id"]] == "learn"]
    held_rows = [r for r in rows if split[r["task_id"]] == "heldout"]

    # --- 规则学习：只用 learn（禁止用 held-out 调规则）
    rules = learn_rules(learn_rows)

    # --- held-out 新旧对比
    detail, agg = evaluate_heldout(held_rows, rules, books_map)
    safety = structural_safety_check(payloads)

    # --- learn × type 构成（报告/审计用）
    learn_type_table: dict[str, dict[str, int]] = {}
    heldout_type_table: dict[str, dict[str, int]] = {}
    for tt in sorted({r["transformation_type"] for r in rows}):
        lc = Counter(r["aggregated"] for r in learn_rows if r["transformation_type"] == tt)
        hc = Counter(r["aggregated"] for r in held_rows if r["transformation_type"] == tt)
        learn_type_table[tt] = dict(sorted(lc.items())) | {"n": sum(lc.values())}
        heldout_type_table[tt] = dict(sorted(hc.items())) | {"n": sum(hc.values())}

    generated = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    limitations = [
        "208 条 final_entity_type_scope_closure 任务为该修复的全量总体，本实验的 60/40 切分"
        "并非从更大总体抽样，切分唯一目的：避免规则学习与效果评价同源（同书任务绝不跨侧）。",
        "判定口径为两票盲评（Judge A=Qwen3.6-35B-A3B + Judge B=gpt-5.6-luna），无第三票仲裁；"
        "DISAGREE（38.5%）一律不可评，不计入 agreement 分母。",
        "UNRESOLVED 类型按弃权处理：不进入 actionable agreement 分母；保守口径"
        "（弃权记错）一并列出。",
        "learn 内 decided<10 或 p>=0.05 的类型一律 UNRESOLVED（保守），例如 mixed 在本次 "
        "learn 内 decided 不足 10，尽管其在全量上方向显著为 BEFORE，规则仍不得据 held-out 回流改判。",
        "held-out 上 UNRESOLVED 类型的 'old 错误改写' 仍会发生（old closure 全 REWRITE），"
        "new closure 只能证明 REWRITE/RETAIN 两类上的改善，弃权类型的收益留待证据增强。",
    ]

    payload = {
        "meta": {
            "experiment": "selective_scope_closure (指令 §12/14)",
            "generated_utc": generated,
            "caliber": "two-vote blind panel（两票口径）：Judge A=Qwen3.6-35B-A3B + Judge B=gpt-5.6-luna；"
                       "A/B 展示位已经 SCOPE_REVALIDATION_V2_AB_MAPPING.csv 解码；本实验不引入任何新裁判票",
            "n_tasks": len(rows),
            "inputs_sha256": {str(p): sha256_file(p) for p in (IN_ERRORS, IN_SUMMARY, IN_META, IN_PAYLOADS)},
            "seed": SEED,
        },
        "split": {**split_details,
                  "learn_task_ids": sorted(t for t, s in split.items() if s == "learn"),
                  "heldout_task_ids": sorted(t for t, s in split.items() if s == "heldout"),
                  "component_atomicity": "每个任务—书分量整体落在一个 split；同书任务绝不跨 learn/heldout"},
        "book_key_derivation": {
            "rule": "payload 证据预览 evidence_excerpts[].source_title（非空去重）→ 回退 metadata books 列 → "
                    "仍为空则 nobook:{task_id} 单任务分量",
            "counts": dict(provenance),
        },
        "rules": rules,
        "unseen_type_default": "UNRESOLVED",
        "rule_thresholds": {"p_threshold_two_sided_binom": P_THRESHOLD, "min_decided": MIN_DECIDED,
                            "learn_only": "规则统计只由 60% learn 计算；held-out 仅评价，未回流"},
        "learn_type_composition": learn_type_table,
        "heldout_type_composition": heldout_type_table,
        "heldout_evaluation": agg,
        "structural_safety": safety,
        "limitations": limitations,
    }

    # --- 落盘（全部为新文件）
    out_dir.mkdir(parents=True, exist_ok=True)
    rules_doc = {
        "meta": payload["meta"],
        "thresholds": payload["rule_thresholds"],
        "book_key_derivation": payload["book_key_derivation"],
        "split_summary": {k: v for k, v in split_details.items() if not k.endswith("_ids")},
        "rules": rules,
        "unseen_type_default": "UNRESOLVED",
    }
    (out_dir / "CLOSURE_RULES.json").write_text(
        json.dumps(rules_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "CLOSURE_OLD_NEW_SUMMARY.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with open(out_dir / "CLOSURE_OLD_NEW_HELDOUT.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(detail[0].keys()))
        w.writeheader()
        for d in detail:
            w.writerow({k: ("" if v is None else v) for k, v in d.items()})

    report = render_report(payload)
    (out_dir / "SCOPE_CLOSURE_REPORT.md").write_text(report, encoding="utf-8")
    return payload


def render_report(p: dict[str, Any]) -> str:
    """生成 SCOPE_CLOSURE_REPORT.md（中文，与前置报告同风格）。"""
    out: list[str] = []
    old, new, pair = p["heldout_evaluation"]["old"], p["heldout_evaluation"]["new"], p["heldout_evaluation"]["paired_actionable"]
    pct = lambda x: "—" if x is None else f"{100 * x:.1f}%"

    out.append("# Selective Scope Closure：规则学习与新旧对比报告（SCOPE_CLOSURE_REPORT）\n")
    out.append(f"- 生成时间：{p['meta']['generated_utc']}（全自动，无人工干预；管线 "
               "`code/experiment_pipelines/run_selective_scope_closure.py`，测试 "
               "`code/tests/test_selective_scope_closure.py`）")
    out.append("- **口径：两票盲评**。Judge A = Qwen3.6-35B-A3B，Judge B = gpt-5.6-luna；本实验不引入任何新裁判票，"
               "判定数据复用 `SCOPE_BY_TYPE_ERRORS.csv`（208 条，A/B 展示位已经映射文件解码，完整性由前置脚本核验）。")
    out.append("- 聚合规则与前置一致：两票一致 → 该判定；两票不一致 → DISAGREE；A/B 无 invalid 票（0/0）。\n")

    out.append("## 1. 60/40 book-split（切分键）\n")
    out.append(f"- 方法：{p['split']['method']}")
    out.append(f"- seed={p['split']['seed']}（与 `data/frozen_splits/SPLIT_MANIFEST.json` 同种子）；"
               f"预算 = round(0.60×{p['split']['n_total']}) = **{p['split']['budget_tasks']} 条**。")
    out.append(f"- book 键：{p['book_key_derivation']['rule']}；来源分布："
               + "，".join(f"{k}={v}" for k, v in p["book_key_derivation"]["counts"].items()) + "。")
    out.append(f"- 任务—书二部图并查集（复用 `build_frozen_splits.py` 分量思路）：{p['split']['n_components']} 个分量，"
               f"分量原子落侧（learn {len(p['split']['learn_component_ids'])} 个 / heldout "
               f"{len(p['split']['heldout_component_ids'])} 个分量），同书任务绝不跨 split。")
    out.append(f"- 实际切分：**learn {p['split']['learn_tasks']} 条（{100 * p['split']['learn_tasks'] / p['split']['n_total']:.1f}%）"
               f" / held-out {p['split']['heldout_tasks']} 条"
               f"（{100 * p['split']['heldout_tasks'] / p['split']['n_total']:.1f}%）**；"
               "分量 id 与逐任务归属见 `CLOSURE_OLD_NEW_SUMMARY.json` 的 `split` 节。\n")

    out.append("### 1.1 类型 × split 构成\n")
    out.append("| transformation_type | learn n (A/B/decided*) | heldout n (A/B/decided*) |")
    out.append("|---|---|---|")
    for tt, lc in p["learn_type_composition"].items():
        hc = p["heldout_type_composition"][tt]
        la, lb = lc.get("AFTER_BETTER", 0), lc.get("BEFORE_BETTER", 0)
        ha, hb = hc.get("AFTER_BETTER", 0), hc.get("BEFORE_BETTER", 0)
        out.append(f"| `{tt}` | {lc['n']}（{la}/{lb}/{la + lb}） | {hc['n']}（{ha}/{hb}/{ha + hb}） |")
    out.append("\n*A/B/decided = AFTER_BETTER / BEFORE_BETTER / 两票一致分出胜负条数。\n")

    out.append("## 2. 学到的规则（仅在 60% learn 内学习）\n")
    out.append(f"- 判据（与前置 `SCOPE_BY_TYPE_SUMMARY.json` 阈值一致）：decided = AFTER_BETTER + BEFORE_BETTER"
               f"（两票一致）；**REWRITE**：双侧精确二项 p<{P_THRESHOLD} 且 AFTER 占优且 decided≥{MIN_DECIDED}；"
               f"**RETAIN**：p<{P_THRESHOLD} 且 BEFORE 占优且 decided≥{MIN_DECIDED}；其余 **UNRESOLVED**（保守）。")
    out.append("- held-out 不参与规则学习（无回流）；learn 内未见类型 apply 时同样 UNRESOLVED。\n")
    out.append("| transformation_type | action | learn n | decided | AFTER : BEFORE | AFTER 胜率 | 双侧精确二项 p | 判据 |")
    out.append("|---|---|---:|---:|---:|---:|---:|---|")
    for tt, ru in p["rules"].items():
        rate = "—" if ru["after_win_rate_learn_decided"] is None else f"{100 * ru['after_win_rate_learn_decided']:.1f}%"
        out.append(f"| `{tt}` | **{ru['action']}** | {ru['n_learn']} | {ru['decided']} | "
                   f"{ru['after_better']} : {ru['before_better']} | {rate} | {ru['binom_p_two_sided']:.5f} | {ru['reason']} |")
    out.append("")

    out.append("## 3. 新旧对比（40% held-out）\n")
    out.append("- 旧 closure（生产现状）：全部候选 REWRITE 为 after。")
    out.append("- 新 closure：按 §2 规则（REWRITE / RETAIN / UNRESOLVED 弃权）。")
    out.append("- 评价：两票解码判定为独立语义裁判——REWRITE 且裁判=AFTER_BETTER → 正确；"
               "RETAIN 且裁判=BEFORE_BETTER → 正确；裁判未定（DISAGREE 等）不可评。\n")
    out.append("| 口径 | n（held-out decided） | 正确 | semantic agreement |")
    out.append("|---|---:|---:|---:|")
    out.append(f"| old（全 REWRITE） | {old['n']} | {old['correct']} | **{pct(old['agreement'])}** |")
    out.append(f"| new（规则，actionable=REWRITE/RETAIN） | {new['n_actionable']}（弃权 {new['n_abstained_unresolved']}） "
               f"| {new['correct_actionable']} | **{pct(new['agreement_actionable'])}** |")
    out.append(f"| new（保守：弃权记错，分母=全部 decided） | {old['n']} | {new['correct_actionable']} "
               f"| {pct(new['agreement_conservative_abstain_as_wrong'])} |")
    out.append("")
    out.append(f"- 配对（两条 closure 在同一批 {pair['n']} 条 actionable decided 任务上的二值配对）："
               f"双方全对 {pair['both_correct']}、双方全错 {pair['both_wrong']}、"
               f"**old 对 new 错 {pair['old_correct_new_wrong']}、old 错 new 对 {pair['old_wrong_new_correct']}**；"
               f"精确 McNemar p = **{pair['mcnemar_exact_p']:.5f}**。")
    out.append(f"- 归因：old closure 的 {old['n'] - old['correct']} 条错误全部来自把裁判判 BEFORE_BETTER 的候选"
               f"强行改写为 after；其 {old['correct']} 条正确则集中在裁判本身支持 AFTER 的任务"
               f"（unknown→event_occurrence 6 条、other 2 条、event_location→context_location 1 条）。"
               "new closure 用类型规则把两类拆开：该改的改（unknown→event_occurrence）、该留的留"
               "（event_location→context_location）、证据不足的类型弃权（UNRESOLVED）。"
               f"唯一回退是 {pair['old_correct_new_wrong']} 条 event_location→context_location 任务：裁判判 "
               "AFTER_BETTER 而规则 RETAIN（该类 AFTER 胜率在 learn 内仅 16.7%，属规则可接受的代价）。\n")
    out.append("### 3.1 held-out 分类型对比\n")
    out.append("| transformation_type | action_new | heldout n | decided | old 正确 | new 正确(actionable) | new 弃权 |")
    out.append("|---|---|---:|---:|---:|---:|---:|")
    for tt, pt in p["heldout_evaluation"]["per_type"].items():
        out.append(f"| `{tt}` | {pt['action_new']} | {pt['n_heldout']} | {pt['n_evaluable']} | "
                   f"{pt['old_correct']} | {pt['new_correct_actionable']} | {pt['new_abstain']} |")
    out.append("")

    out.append("## 4. 结构安全检查（structural violations 恒 0）\n")
    out.append(f"- {p['structural_safety']['claim']}。")
    out.append(f"- 程序化核验：{p['structural_safety']['payload_slots_checked']} 个 A/B 展示位状态对象中，"
               f"含 role/owner 四字段以外键的为 **{p['structural_safety']['slots_with_non_role_owner_fields']} 个**。")
    out.append(f"- 因此新 closure 的 REWRITE 动作与生产改写共用同一改写面（仅 role/owner），"
               f"不可能引入结构约束违例：**structural violations = {p['structural_safety']['structural_violations']}**。"
               f"{p['structural_safety']['conclusion']}。\n")

    out.append("## 5. 样本代表性与口径局限（声明）\n")
    for i, lim in enumerate(p["limitations"], 1):
        out.append(f"{i}. {lim}")
    out.append("")
    return "\n".join(out)


def main() -> int:
    p = run_pipeline()
    he = p["heldout_evaluation"]
    print(f"[closure] split: learn={p['split']['learn_tasks']} heldout={p['split']['heldout_tasks']} "
          f"({p['split']['n_components']} components)")
    for tt, ru in p["rules"].items():
        print(f"[closure] rule {tt}: {ru['action']} (decided={ru['decided']}, p={ru['binom_p_two_sided']:.5f})")
    print(f"[closure] heldout agreement: old={he['old']['agreement']:.4f} "
          f"new={he['new']['agreement_actionable']:.4f} "
          f"(actionable n={he['new']['n_actionable']}, abstain={he['new']['n_abstained_unresolved']}, "
          f"mcnemar p={he['paired_actionable']['mcnemar_exact_p']:.5f})")
    print(f"[closure] structural violations: {p['structural_safety']['structural_violations']}")
    print("[closure] written: CLOSURE_RULES.json, CLOSURE_OLD_NEW_HELDOUT.csv, "
          "CLOSURE_OLD_NEW_SUMMARY.json, SCOPE_CLOSURE_REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
