# -*- coding: utf-8 -*-
"""patch_statistics_wording.py — 两个统计口径修补落盘。

修补 1：加权总体 STRICT 机会率改用设计型 CI（bootstrap_weighted_ci 产物），
       全库条数区间 = CI × 311,992。
修补 2：99.28% 的表述改为真实分子/分母（A=965 / N=972，FP 4/972）+ Wilson CI，
       并写入 AUDIT_RESULTS.json 的 detail 字段；正文禁止再写「n=4,427」。
另：写入方法定型叙述 + 三层证据链 + 93,754/299,329 的来源分解。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

V31 = Path(__file__).resolve().parents[2]
CN_TZ = timezone(timedelta(hours=8))
now = datetime.now(CN_TZ).isoformat()

# ---------- 修补 2a：门内审计 json 补 detail ----------
qa = V31 / "release_final" / "experiments" / "quality_audit" / "AUDIT_RESULTS.json"
res = json.loads(qa.read_text(encoding="utf-8"))
res["strict_support_precision_strong_consensus_detail"] = {
    "definition": "production STRICT 样本中，双裁判形成强共识（五档一致）的判定里，"
                  "判为 FULLY_SUPPORTED/PARTIALLY_SUPPORTED 的比例",
    "point": 0.9928,
    "ci95_wilson": [0.9852, 0.9965],
    "A_supported": 965,
    "B_contradicted_by_consensus": 4,
    "N_strong_consensus_strict": 972,
    "fully_only_precision": {"point": 0.8066, "ci95_wilson": [0.7806, 0.8302],
                             "A_fully": 784, "N": 972},
    "false_positive_rate": {"point": 0.0041, "ci95_wilson": [0.0016, 0.0105],
                            "B": 4, "N": 972},
    "phrasing_rule": "禁止写「99.28%（n=4,427）」；规范表述：在 4,427 条分层独立"
                     "审计样本中，对 STRICT 样本形成强共识的判定显示其证据支持精度"
                     "为 99.28%（965/972）。",
    "patched_at": now,
}
qa.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
print("[patch] AUDIT_RESULTS.json detail written")

# ---------- 修补 2b/1：报告口径 ----------
# AUTHORITATIVE_RESULTS.md
p = V31 / "AUTHORITATIVE_RESULTS.md"
t = p.read_text(encoding="utf-8")
t = t.replace(
    "- 门内 STRICT（n=4,427 盲评）：强共识支撑精度 **0.9928**（PASS 线 0.90），FP 0.0041",
    "- 门内 STRICT（4,427 条分层独立审计样本）：对 STRICT 样本形成强共识的判定"
    "（**n=972**）显示证据支持精度 **99.28%（965/972，95%CI [0.9852, 0.9965]）**；"
    "强共识误报率 0.41%（4/972，95%CI [0.0016, 0.0105]）")
t = t.replace(
    "- 门外宇宙（n=5,000 分层，seed=20260916，双裁判）：见 OUTSIDE_GATE_AUDIT_RESULTS.json\n"
    "  （strict 机会率 / 分 blocker 机会率 / 精度–覆盖解释）",
    "- 门外宇宙（n=5,000 分层，seed=20260916，双裁判，双有效 n=4,957）：\n"
    "  强共识 STRICT 机会率样本口径 0.63%（31/4,957，95%CI [0.44%, 0.89%]）；\n"
    "  **加权总体 0.66%，设计型 95%CI [0.40%, 0.97%]**，对应全库条数区间\n"
    "  **[1,257, 3,019] / 311,992**（stratified bootstrap B=10,000，seed=20260916）\n"
    "  详见 OUTSIDE_GATE_AUDIT_RESULTS.json 的 weighted_strict_opportunity_design_ci。\n\n"
    "## 二之二、方法定型叙述（论文口径）\n\n"
    "本文提出一种面向历史文献知识规范化的**级联式准入方法**：首先通过实体语义、身份、"
    "关系及时空约束判断结构化断言是否具备严格准入可能性；不满足条件的断言根据其"
    "不确定性保留为上下文（CONTEXTUAL）或未决（UNRESOLVED）状态，仅对仍具有严格"
    "准入可能性的候选执行高成本证据语义核验。由此在保留全部结构化信息的同时，将"
    "高确定性知识与需要上下文解释或进一步核验的信息分离。Evidence Gate 定义为\n"
    "strict-admission verification，不是 full-universe classifier。\n\n"
    "## 二之三、三层证据链（论文结果叙事）\n\n"
    "1. **全库没有被随意丢弃**：424,150 条断言全部具有可重放准入路径——112,158 条\n"
    "   进入严格候选，268,047 条进入上下文状态，43,945 条进入未决状态，\n"
    "   无法解释的历史状态为 0（replay 六项零检查 ALL PASS）。\n"
    "2. **前置结构合格 ≠ 证据已充分支持**：对 112,158 条严格候选逐条证据语义核验后，\n"
    "   仅 31,067 条保持严格准入；31,282 条调整为上下文，49,809 条转为未决。\n"
    "   结论：结构规范化合格，不代表证据已经充分支持规范断言。\n"
    "3. **保守准入没有造成大规模高质量知识漏失**：对门外 311,992 条开展 5,000 条\n"
    "   分层双模型盲审（双有效 4,957），证据支持完全一致率 81.26% [80.15, 82.32]，\n"
    "   κ=0.514；强共识下仅 0.63%（样本）/0.66%（加权总体）被认为仍具 STRICT 机会。\n\n"
    "## 二之四、最终三层的来源分解（写作定版）\n\n"
    "- **UNRESOLVED 93,754 = 43,945（前置准入）+ 49,809（证据语义核验）**；\n"
    "  前者 = scope 冲突 27,492 + 端点实体类型未决 16,393 + 人工遗留 60；\n"
    "  后者 = 证据不支持 47,576 + 证据冲突 127 + 无可定位证据 2,106。\n"
    "- **CONTEXTUAL 299,329 = 268,047（前置准入）+ 31,282（核验后降级）**；\n"
    "  前者 = 谓词未完成规范化 264,635 + 不满足关系域约束 3,412；\n"
    "  后者 = PARTIAL（谓词不在 partial-strict 集）27,704 + INSUFFICIENT 3,578。\n"
    "- 三层全部有来源、有原因、有路径、有审计。")
p.write_text(t, encoding="utf-8")
print("[patch] AUTHORITATIVE_RESULTS.md updated")

# FULL_ADMISSION_CLOSURE_REPORT.md：问题 8 的精确表述 + 加权 CI
p2 = V31 / "experiments" / "10_full_universe_admission_closure" / "FULL_ADMISSION_CLOSURE_REPORT.md"
t2 = p2.read_text(encoding="utf-8")
t2 = t2.replace(
    "**问题 8 答案**：最终 STRICT precision = **0.9928**（门内独立双裁判强共识口径，\n"
    "n=4,427，95% CI 见 AUDIT_RESULTS.json；FP 率 0.0041）。",
    "**问题 8 答案**：最终 STRICT precision = **0.9928 = 965/972**（95%CI "
    "[0.9852, 0.9965]；强共识误报率 0.41% = 4/972，95%CI [0.0016, 0.0105]）。\n"
    "规范表述：在 4,427 条分层独立审计样本中，对 STRICT 样本形成强共识的判定\n"
    "（n=972）显示其证据支持精度为 99.28%。禁止写「99.28%（n=4,427）」。")
t2 = t2.replace(
    "| 总体强共识 STRICT 机会率 | 0.0063 | [0.0044, 0.0089] | 31/4,957 |",
    "| 总体强共识 STRICT 机会率（样本口径） | 0.0063 | [0.0044, 0.0089] | 31/4,957 |")
t2 = t2.replace(
    "| **加权总体 STRICT 机会率**（还原至 311,992） | **0.0066** | — | ≈2,070 条 |",
    "| **加权总体 STRICT 机会率**（还原至 311,992） | **0.0066** | "
    "**[0.0040, 0.0097]**（stratified bootstrap B=10,000，seed=20260916） | "
    "点估计 ≈2,070 条；**条数区间 [1,257, 3,019]** |")
p2.write_text(t2, encoding="utf-8")
print("[patch] FULL_ADMISSION_CLOSURE_REPORT.md updated")

# OUTSIDE_GATE_AUDIT_REPORT.md：加权行补 CI
p3 = V31 / "experiments" / "10_full_universe_admission_closure" / "OUTSIDE_GATE_AUDIT_REPORT.md"
t3 = p3.read_text(encoding="utf-8")
t3 = t3.replace(
    "| **强共识总体加权（按 blocker stratum 权重还原到 311,992）** | **0.0066** |",
    "| **强共识总体加权（按 blocker stratum 权重还原到 311,992）** | "
    "**0.0066，设计型 95%CI [0.0040, 0.0097]**（stratified bootstrap B=10,000，"
    "seed=20260916；条数区间 [1,257, 3,019]） |")
p3.write_text(t3, encoding="utf-8")
print("[patch] OUTSIDE_GATE_AUDIT_REPORT.md updated")

# FINAL_RELEASE_REPORT.md：审计行精确化
p4 = V31 / "release_final" / "reports" / "FINAL_RELEASE_REPORT.md"
t4 = p4.read_text(encoding="utf-8")
t4 = t4.replace(
    "| **独立质量审计（预注册协议）** | **PASS — STRICT 支撑精度 0.9928（强共识口径）** |",
    "| **独立质量审计（预注册协议）** | **PASS — 4,427 条分层独立审计样本中，"
    "STRICT 样本强共识判定的证据支持精度 99.28%（965/972，95%CI [0.9852, 0.9965]）** |")
t4 = t4.replace(
    "| STRICT 支撑精度（强共识） | **0.9928** | ≥0.90 预注册 PASS 线；超过同类历史人文 KG ~90% 基准 |",
    "| STRICT 支撑精度（强共识） | **0.9928 = 965/972**（95%CI [0.9852, 0.9965]）| "
    "≥0.90 预注册 PASS 线；超过同类历史人文 KG ~90% 基准 |")
t4 = t4.replace(
    "| STRICT 误报率（强共识判 NEG） | 0.0041 | 0.4% |",
    "| STRICT 误报率（强共识判 NEG） | 0.0041 = 4/972（95%CI [0.0016, 0.0105]） | 0.4% |")
p4.write_text(t4, encoding="utf-8")
print("[patch] FINAL_RELEASE_REPORT.md updated")
