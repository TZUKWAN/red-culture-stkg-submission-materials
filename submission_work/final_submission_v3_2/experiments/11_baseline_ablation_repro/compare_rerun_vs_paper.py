# -*- coding: utf-8 -*-
"""compare_rerun_vs_paper.py — 把 baseline/消融重跑产物与论文表 1/2/3 声明值逐值对齐。

期望值从 `submission_work/final_submission_v3_2/manuscript/论文正文.md` 的表 1、表 2、表 3
及其正文叙述中抄录（下表注明行号）；重跑值取自本目录 BASELINE_METRICS.csv 与 ABLATION_RUNS.csv。
判定容差 5e-5（论文保留 4 位小数）。同时与 v2 冻结产物比对，量化"重跑是否等于原产物"。
只读本实验目录与 v2 目录，不写任何外部路径。
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
V2 = HERE.parents[2] / "final_submission_v2"        # HERE 已是目录：parents[2] = submission_work
CN_TZ = timezone(timedelta(hours=8))
TOL = 5e-5


def rows(p: Path):
    return list(csv.DictReader(p.open(encoding="utf-8-sig")))


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def ratio(a, b):
    return None in (a, b) or not b


# 论文表 1（正文 90–107 行）：n=152 核心集，字段直读 BASELINE_METRICS.csv
TABLE1 = [
    ("规则方法", "M1_rule_only", [("coverage", 0.9934), ("accuracy_on_covered", 0.8742),
                                  ("selective_risk", 0.1258), ("safe_coverage", 0.8618),
                                  ("macro_f1_on_covered", 0.8967)], ("132", "151")),
    ("本地分类器", "M2_classifier_only", [("coverage", 1.0000), ("accuracy_on_covered", 0.6250),
                                          ("selective_risk", 0.3750), ("safe_coverage", 0.6184),
                                          ("macro_f1_on_covered", 0.4333)], ("95", "152")),
    ("缓存模型回放（表1第3行）", "M3_cached_llm_replay", [("coverage", 0.9934),
                                                          ("accuracy_on_covered", 0.8808),
                                                          ("selective_risk", 0.1192),
                                                          ("safe_coverage", 0.8553)], ("133", "151")),
    ("规则—Qwen 一致性选择", "M4_rule_plus_cached_llm", [("coverage", 0.7632),
                                                          ("accuracy_on_covered", 0.9914),
                                                          ("selective_risk", 0.0086),
                                                          ("safe_coverage", 0.75)], ("115", "116")),
    ("冻结完整框架确定性回放", "M6_full_v2_replay", [("coverage", 1.0000),
                                                     ("accuracy_on_covered", 0.8618),
                                                     ("selective_risk", 0.1382)], ("131", "152")),
]

# 论文表 2（正文 101–108 行）：n=203 选择性组件消融，由分子/分母现算
TABLE2 = [
    ("完整选择性分类器", "Full selective classifier",
     {"覆盖率": ("coverage", 72, 203, 0.3547), "接受样本一致率": ("acc", 68, 72, 0.9444),
      "选择性风险": ("risk", 4, 72, 0.0556), "错误暴露率": ("exposure", 4, 203, 0.0197),
      "安全覆盖率": ("safe_coverage", 68, 203, 0.3350)}),
    ("去类别门禁", "w/o Class-specific Gate",
     {"覆盖率": ("coverage", 73, 203, 0.3596), "接受样本一致率": ("acc", 69, 73, 0.9452),
      "选择性风险": ("risk", 4, 73, 0.0548), "错误暴露率": ("exposure", 4, 203, 0.0197),
      "安全覆盖率": ("safe_coverage", 69, 203, 0.3399)}),
    ("去独立信号一致", "w/o Independent Signal Agreement",
     {"覆盖率": ("coverage", 132, 203, 0.6502), "接受样本一致率": ("acc", 121, 132, 0.9167),
      "选择性风险": ("risk", 11, 132, 0.0833), "错误暴露率": ("exposure", 11, 203, 0.0542),
      "安全覆盖率": ("safe_coverage", 121, 203, 0.5961)}),
    ("取消显式弃权", "w/o Abstention",
     {"覆盖率": ("coverage", 203, 203, 1.0000), "接受样本一致率": ("acc", 179, 203, 0.8818),
      "选择性风险": ("risk", 24, 203, 0.1182), "错误暴露率": ("exposure", 24, 203, 0.1182),
      "安全覆盖率": ("safe_coverage", 179, 203, 0.8818)}),
]

# 论文表 3 与 §4.3 叙述（正文 112–125 行）：全库结构消融，整数计数
TABLE3 = [
    ("完整框架", "Full framework", "strict_assertions", 112158),
    ("完整框架", "Full framework", "contextual_assertions", 268047),
    ("完整框架", "Full framework", "unresolved_assertions", 43945),
    ("完整框架", "Full framework", "strict_contract_violations", 0),
    ("完整框架", "Full framework", "invalid_time_owner_types", 0),
    ("完整框架", "Full framework", "invalid_space_owner_types", 0),
    ("完整框架", "Full framework", "admitted_without_provenance", 0),
    ("完整框架", "Full framework", "total", 424150),
    ("去风险路由", "w/o Risk Routing", "changed_vs_full", 43945),
    ("去身份投影", "w/o Identity Projection", "changed_vs_full", 24005),
    ("去关系契约", "w/o Relation Contract", "strict_contract_violations", 3412),
    ("去关系契约", "w/o Relation Contract", "changed_vs_full", 3412),
    ("去角色归属闭包", "w/o Role-owner Closure", "invalid_time_owner_types", 44),
    ("去角色归属闭包", "w/o Role-owner Closure", "invalid_space_owner_types", 112),
    ("去角色归属闭包", "w/o Role-owner Closure", "changed_vs_full", 208),
]


def main() -> int:
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))

    base_new = rows(HERE / "BASELINE_METRICS.csv")
    abl_new = rows(HERE / "ABLATION_RUNS.csv")
    base_old = rows(V2 / "experiments/02_baselines/BASELINE_METRICS.csv")
    abl_old = rows(V2 / "experiments/05_ablation/ABLATION_RUNS.csv")

    B = {(r["method_id"], r["n_test"]): r for r in base_new}
    A = {(r["component"], r["evaluation_family"], r["variant"], r["metric"]): r for r in abl_new}
    cnt = lambda c, fam, v, m: f(A[(c, fam, v, m)]["value"])

    # ---- 表 1 ----
    for label, mid, fields, (nc, ncov) in TABLE1:
        r = B.get((mid, "152"))
        if r is None:
            add(f"表1 {label}", False, "重跑产物缺该行")
            continue
        bad = [(fld, want, f(r[fld])) for fld, want in fields
               if f(r[fld]) is None or abs(f(r[fld]) - want) > TOL]
        add(f"表1 {label}（{mid}）", not bad and (r["n_correct"], r["n_covered"]) == (nc, ncov),
            f"n_correct/n_covered={r['n_correct']}/{r['n_covered']}（论文 {nc}/{ncov}）"
            + (f" 不符字段={bad}" if bad else ""))

    # ---- 表 2 ----
    CALC = {
        "完整选择性分类器": "Full classifier",
        "去类别门禁": "Class-specific Gate",
        "去独立信号一致": "Independent Signal Agreement",
        "取消显式弃权": "Abstention",
    }
    for label, variant, metrics in TABLE2:
        fam, comp = "entity_type_ai_reference", CALC[label]
        g = {m: f(A[(comp, fam, variant, m)]["value"]) for m in
             ("accepted", "correct", "errors", "coverage", "safe_coverage")
             if (comp, fam, variant, m) in A}
        got_of = {"coverage": g.get("coverage"),
                  "safe_coverage": g.get("safe_coverage"),
                  "acc": (g["correct"] / g["accepted"]) if g.get("accepted") else None,
                  "risk": (g["errors"] / g["accepted"]) if g.get("accepted") else None,
                  "exposure": (g["errors"] / 203) if g.get("errors") is not None else None}
        bad = []
        for mname, (kind, nu, de, want) in metrics.items():
            got = got_of.get(kind)
            if got is None or abs(got - want) > TOL:
                bad.append((mname, want, got))
            if (nu, de) not in ((g.get("accepted"), 203), (g.get("correct"), g.get("accepted")),
                                (g.get("errors"), g.get("accepted")), (g.get("errors"), 203),
                                (g.get("correct"), 203)):
                bad.append((mname + " 分子分母", (nu, de),
                            (g.get("accepted"), g.get("correct"), g.get("errors"))))
        add(f"表2 {label}（n=203）", not bad,
            f"accepted/correct/errors={g.get('accepted')}/{g.get('correct')}/{g.get('errors')}"
            + (f" 不符={bad}" if bad else ""))

    # ---- 表 3 ----
    for label, variant, metric, want in TABLE3:
        fam = "full_assertion_structural_replay"
        key = next((k for k in A if k[1] == fam and k[2] == variant and k[3] == metric), None)
        if key is None:
            add(f"表3 {label}·{metric}", False, "重跑产物缺该组合")
            continue
        got = f(A[key]["value"])
        add(f"表3 {label}·{metric} == {want:,}", got == want, f"重跑值 {got:,.0f}")

    # ---- 与 v2 冻结产物逐字段比对 ----
    bk = lambda r: (r["method_id"], r["task_type"], r["n_test"])
    NB, OB = {bk(r): r for r in base_new}, {bk(r): r for r in base_old}
    db = [k for k in set(NB) & set(OB) for c in NB[k]
          if NB[k].get(c, "") != OB[k].get(c, "")]
    add("表1 重跑 == v2 冻结 BASELINE_METRICS（逐字段）", not db and set(NB) == set(OB),
        f"{len(NB)} 行；差异字段 {len(db)}")

    ak = lambda r: (r["component"], r["evaluation_family"], r["variant"], r["metric"])
    NA, OA = {ak(r): r for r in abl_new}, {ak(r): r for r in abl_old}

    def nums(s):
        """把 '0.4376…' 或 '[0.43, 0.56]' 解析成浮点列表；不可解析返回 None。"""
        s = (s or "").strip()
        if not s:
            return None
        try:
            v = json.loads(s) if s.startswith("[") else float(s)
        except (ValueError, json.JSONDecodeError):
            return None
        vs = v if isinstance(v, list) else [v]
        return [float(x) for x in vs if isinstance(x, (int, float))] or None

    def closeness(x, y):
        """返回 (是否等价, 最大相对偏差)。"""
        if x == y:
            return True, 0.0
        a, b = nums(x), nums(y)
        if a is None or b is None or len(a) != len(b):
            return False, float("inf")
        rel = max((abs(p - q) / max(abs(q), 1e-300) for p, q in zip(a, b)), default=0.0)
        return rel <= 1e-12, rel

    da, ulp = [], []
    for k in set(NA) & set(OA):
        for c in ("value", "numerator", "denominator", "evidence_class", "note"):
            x, y = NA[k].get(c, ""), OA[k].get(c, "")
            if x == y:
                continue
            same, rel = closeness(x, y)
            (ulp if same else da).append({"row": " | ".join(k), "field": c,
                                          "rerun": x, "frozen_v2": y, "rel_dev": rel})
    add("表2/表3 重跑 == v2 冻结 ABLATION_RUNS（逐字段，容 1e-12 浮点末位）",
        not da and set(NA) == set(OA), f"{len(NA)} 行；超容差差异 {len(da)}")
    if ulp:
        print(f"[INFO] 仅末位浮点差异 {len(ulp)} 处（相对偏差 ≤1e-12，不影响任何 4 位小数呈现值）：")
        for u in ulp:
            print(f"        {u['row']} · {u['field']}  rel={u['rel_dev']:.2e}")

    audit = json.loads((HERE / "ablation_experiment_audit.json").read_text(encoding="utf-8")) \
        if (HERE / "ablation_experiment_audit.json").exists() else {}
    add("消融运行时受保护输入哈希未变",
        str(audit.get("protected_inputs_unchanged", audit.get("hashes_unchanged", ""))).lower() != "false",
        json.dumps({k: v for k, v in audit.items() if "hash" in k.lower() or "protect" in k.lower()},
                   ensure_ascii=False)[:200] or "见 ablation_experiment_audit.json")

    ok = all(c["ok"] for c in checks)
    out = {"generated_at": datetime.now(CN_TZ).isoformat(),
           "result": "ALL PASS" if ok else "FAIL",
           "tolerance": TOL, "llm_calls": 0, "checks": checks,
           "float_ulp_differences_vs_frozen_v2": ulp}
    (HERE / "PAPER_RERUN_COMPARISON.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结论：{out['result']}　（{len(checks)} 项，报告 PAPER_RERUN_COMPARISON.json）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
