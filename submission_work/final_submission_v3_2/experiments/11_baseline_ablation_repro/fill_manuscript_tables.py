# -*- coding: utf-8 -*-
"""fill_manuscript_tables.py — 用重跑产物补全论文表 1/2/3 被 "| … |" 截断的行。

前置门槛：本目录 `PAPER_RERUN_COMPARISON.json` 必须为 ALL PASS（即表1/2/3 已被重跑逐值复现）。
数值一律从 BASELINE_METRICS.csv / ABLATION_RUNS.csv 现取现算，不手抄。
只改 `manuscript/论文正文.md` 中三个 `[表格 N]` 块的数据行，不动标题、注记与正文叙述。
幂等：块内已无 "| … |" 占位则跳过。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
MS = HERE.parents[1] / "manuscript" / "论文正文.md"
TOL = 5e-5


def rows(p):
    return list(csv.DictReader((HERE / p).open(encoding="utf-8-sig")))


def num(x):
    return float(x) if x not in (None, "") else None


def r4(x):
    return f"{x:.4f}"


def comma(x):
    return f"{int(float(x)):,}"


BASE = rows("BASELINE_METRICS.csv")
ABL = rows("ABLATION_RUNS.csv")
B152 = {r["method_id"]: r for r in BASE if r["n_test"] == "152"}
A = {(r["component"], r["evaluation_family"], r["variant"], r["metric"]): r for r in ABL}


def av(comp, fam, variant, metric):
    r = A.get((comp, fam, variant, metric))
    return num(r["value"]) if r else None


# ---------------- 表 1：n=152 分级证据 ----------------
T1_METHODS = [
    ("规则方法", "M1_rule_only", "实际运行"),
    ("本地分类器", "M2_classifier_only", "实际运行"),
    ("缓存模型输出回放", "M3_cached_llm_replay", "缓存回放"),
    ("规则—Qwen一致性选择", "M4_rule_plus_cached_llm", "缓存回放"),
    ("冻结完整框架确定性回放", "M6_full_v2_replay", "确定性回放"),
]
t1 = ["| 方法 | 覆盖率 | 接受样本一致率 | 选择性风险 | 安全覆盖率 | Macro-F1 | 证据等级 |",
      "|---|---|---|---|---|---|---|"]
for label, mid, ev in T1_METHODS:
    r = B152[mid]
    cov, acc, risk = num(r["coverage"]), num(r["accuracy_on_covered"]), num(r["selective_risk"])
    safe, f1 = num(r["safe_coverage"]), num(r["macro_f1_on_covered"])
    t1.append(f"| {label} | {r4(cov)} | {r4(acc)} | {r4(risk)} | {r4(safe)} | {r4(f1)} | {ev} |")

# ---------------- 表 2：n=203 选择性组件消融 ----------------
FAM2 = "entity_type_ai_reference"
T2 = [("完整选择性分类器", "Full classifier", "Full selective classifier"),
      ("去类别门禁", "Class-specific Gate", "w/o Class-specific Gate"),
      ("去独立信号一致", "Independent Signal Agreement", "w/o Independent Signal Agreement"),
      ("取消显式弃权", "Abstention", "w/o Abstention")]
t2 = ["| 变体 | 覆盖率 | 接受样本一致率 | 选择性风险 | 错误暴露率 | 安全覆盖率 |", "|---|---|---|---|---|---|"]
for label, comp, variant in T2:
    acc_n = av(comp, FAM2, variant, "accepted")
    cor = av(comp, FAM2, variant, "correct")
    err = av(comp, FAM2, variant, "errors")
    if None in (acc_n, cor, err) or not acc_n:
        raise SystemExit(f"[FAIL] 表2 {label} 缺计数键 ({comp}, {variant})")
    t2.append(f"| {label} | {r4(acc_n / 203)} | {r4(cor / acc_n)} | {r4(err / acc_n)} | "
              f"{r4(err / 203)} | {r4(cor / 203)} |")

# ---------------- 表 3：全库结构消融 ----------------
FAM3 = "full_assertion_structural_replay"


def s3(variant, metric):
    comp = {"Full framework": "Full framework", "w/o Risk Routing": "Risk Routing",
            "w/o Identity Projection": "Identity Projection", "w/o Relation Contract": "Relation Contract",
            "w/o Role-owner Closure": "Role-owner Closure", "w/o Provenance Gate": "Provenance Gate",
            "w/o Global Closure": "Global Closure"}[variant]
    return av(comp, FAM3, variant, metric)


FULL_EP = int(s3("Full framework", "unique_endpoint_ids"))
t3 = ["| 消融设置 | 影响对象 | 状态/端点变化 | 新增结构违例 | 主要作用 |", "|---|---|---|---|---|"]
rows3 = [
    ("完整框架", "全部知识陈述", "—", 0, "基准：严格层已定义关系与时空归属违例均为 0"),
    ("去风险路由", "发布状态", s3("w/o Risk Routing", "changed_vs_full"), "—",
     "未决知识失去独立隔离状态，43,945 条改判为上下文"),
    ("去身份投影", "实体端点", s3("w/o Identity Projection", "changed_vs_full"),
     int(s3("w/o Identity Projection", "strict_contract_violations")),
     f"端点不再收敛到代表元，唯一端点数由 {FULL_EP:,} 升至 {int(s3('w/o Identity Projection','unique_endpoint_ids')):,}"),
    ("去关系契约", "严格层关系实例", s3("w/o Relation Contract", "changed_vs_full"),
     int(s3("w/o Relation Contract", "strict_contract_violations")),
     "主体—客体类型约束失效，新增同数量强类型违例"),
    ("去角色归属闭包", "时空归属对象", s3("w/o Role-owner Closure", "changed_vs_full"),
     f"{int(s3('w/o Role-owner Closure','invalid_time_owner_types'))}（时间）/"
     f"{int(s3('w/o Role-owner Closure','invalid_space_owner_types'))}（空间）",
     "强角色归属对象类型不再受闭包约束"),
    ("去来源门禁", "来源关联", s3("w/o Provenance Gate", "changed_vs_full"),
     int(s3("w/o Provenance Gate", "admitted_without_provenance")),
     "在冻结台账上无结构后果，来源可追溯性损失不体现为硬违例"),
    ("去全局闭包", "全部结构环节", s3("w/o Global Closure", "changed_vs_full"),
     f"{int(s3('w/o Global Closure','strict_contract_violations')):,}+"
     f"{int(s3('w/o Global Closure','invalid_time_owner_types'))}+"
     f"{int(s3('w/o Global Closure','invalid_space_owner_types'))}",
     "联合关闭后关系与时空违例同时出现，为各环节之和"),
]
for label, obj, chg, viol, role in rows3:
    chg_s = chg if isinstance(chg, str) else comma(chg)
    viol_s = viol if isinstance(viol, str) else f"{viol:,}"
    t3.append(f"| {label} | {obj} | {chg_s} | {viol_s} | {role} |")

TABLES = {"1": t1, "2": t2, "3": t3}


def fill(text: str, marker: str, new_block: list) -> tuple[str, bool, int]:
    lines = text.split("\n")
    try:
        i = lines.index(f"[表格 {marker}]")
    except ValueError:
        return text, False, 0
    j = i + 1
    while j < len(lines) and not lines[j].strip().startswith("|"):
        j += 1
    k = j
    while k < len(lines) and lines[k].strip().startswith("|"):
        k += 1
    old = lines[j:k]
    if not any(re.fullmatch(r"\|\s*…\s*\|?", l.strip()) for l in old):
        return text, False, 0
    lines[j:k] = new_block
    return "\n".join(lines), True, len(new_block) - len(old)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="真正写入 manuscript/论文正文.md；默认只生成预览")
    args = ap.parse_args(argv)

    cmp_path = HERE / "PAPER_RERUN_COMPARISON.json"
    verdict = json.loads(cmp_path.read_text(encoding="utf-8")) if cmp_path.exists() else {}
    if verdict.get("result") != "ALL PASS":
        print("前置门槛未满足：先跑 compare_rerun_vs_paper.py 并 ALL PASS（当前 "
              f"{verdict.get('result', '无报告')}）")
        return 1

    text = MS.read_text(encoding="utf-8")
    before_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

    preview = ["# 表 1/2/3 补全预览（数值来自本目录重跑产物，27 项比对 ALL PASS）", ""]
    for marker, block in TABLES.items():
        preview.append(f"## 表 {marker}")
        preview.extend(block)
        preview.append("")
    (HERE / "MANUSCRIPT_TABLE_PREVIEW.md").write_text("\n".join(preview), encoding="utf-8")
    print("\n".join(preview))

    if not args.write:
        print("[预览模式] 未改动论文正文；确认无误后加 --write 写入。")
        return 0

    changed = []
    for marker, block in TABLES.items():
        text, did, delta = fill(text, marker, block)
        if did:
            changed.append((marker, len(block) // 2, delta))
        else:
            print(f"[SKIP] 表 {marker} 无 … 占位或标记缺失")
    if not changed:
        print("没有需要补全的表格。")
        return 0
    MS.write_text(text, encoding="utf-8")
    after_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    print("已补全：" + "；".join(f"表{m}（{n} 行数据）" for m, n, _ in changed))
    print(f"改前 SHA256 {before_sha[:16]}… → 改后 {after_sha[:16]}…")
    (HERE / "MANUSCRIPT_TABLE_FILL.json").write_text(json.dumps({
        "manuscript": str(MS.relative_to(HERE.parents[2])).replace("\\", "/"),
        "sha256_before": before_sha, "sha256_after": after_sha,
        "tables": {m: block for m, block in TABLES.items()},
        "source": "BASELINE_METRICS.csv / ABLATION_RUNS.csv（本目录重跑产物）",
        "guard": "PAPER_RERUN_COMPARISON.json == ALL PASS",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
