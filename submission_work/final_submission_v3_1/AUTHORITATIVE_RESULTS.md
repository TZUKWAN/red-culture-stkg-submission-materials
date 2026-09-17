# AUTHORITATIVE_RESULTS — 论文最终数字唯一权威清单

冻结时间：2026-09-16　适用范围：TZUKWAN/red-culture-stkg-submission-materials @ final_submission_v3_1

## 一、唯一允许引用的数字来源（六个文件）

| # | 文件 | 权威内容 |
|---|---|---|
| 1 | `release_final/manifests/FINAL_NUMBERS.json`（及 .csv） | 全部论文核心指标（31 项机读，含 db_sha256） |
| 2 | `audit/method_final/FINAL_EVIDENCE_REPORT.md` | 证据门三层最终结果与方法报告 |
| 3 | `audit/method_final/FINAL_SCOPE_REPORT.md` | scope 选择性闭包最终结果 |
| 4 | `release_final/experiments/quality_audit/AUDIT_RESULTS.json` | 门内 STRICT 独立双裁判审计（0.9928 PASS） |
| 5 | `experiments/10_full_universe_admission_closure/FULL_UNIVERSE_ADMISSION_SUMMARY.json` | 全库 424,150 准入台账与归因 |
| 6 | `experiments/10_full_universe_admission_closure/OUTSIDE_GATE_AUDIT_RESULTS.json` | 门外宇宙独立双裁判审计 |

派生规则：论文表格/图/摘要的每一个数字，必须能在上述文件中找到
（或由其字段按注明公式直接推导）；引用时注明 universe。

## 二、核心定版数字（截至本文件冻结时点）

### 全库（424,150 条 research_assertions）
- 最终三层：**STRICT 31,067 / CONTEXTUAL 299,329 / UNRESOLVED 93,754**
- 证据门宇宙（旧 strict 重分层宇宙）= **112,158**；门外 = **311,992**
  （pre-gate CONTEXTUAL 268,047 + pre-gate UNRESOLVED 43,945）

### 证据门宇宙 112,158（Evidence Semantic Gate 定义域）
- **STRICT 31,067 / CONTEXTUAL 31,282 / UNRESOLVED 49,809**（零持留）
- 生产模型 qwen3.5-4b（reasoning=off，T=0，无回退）；判定档案 127,633 条

### 门外宇宙 311,992 的准入归因（FULL_UNIVERSE_ADMISSION_SUMMARY.json）
- pre-gate CONTEXTUAL 268,047 = strict 候选 conjunct 失败：
  raw 谓词未归一化 264,635 + 关系域约束违反 3,412（284 脚本 CASE 规则重放，0 mismatch）
- pre-gate UNRESOLVED 43,945 = v2 语义规格化即被排除：
  scope 冲突 model_review 27,492 + 端点实体类型未决 16,393 + manual_review 遗留 60
- **unexplained = 0**

### 独立审计
- 门内 STRICT（4,427 条分层独立审计样本）：对 STRICT 样本形成强共识的判定（**n=972**）显示证据支持精度 **99.28%（965/972，95%CI [0.9852, 0.9965]）**；强共识误报率 0.41%（4/972，95%CI [0.0016, 0.0105]）
- 门外宇宙（n=5,000 分层，seed=20260916，双裁判，双有效 n=4,957）：
  强共识 STRICT 机会率样本口径 0.63%（31/4,957，95%CI [0.44%, 0.89%]）；
  **加权总体 0.66%，设计型 95%CI [0.40%, 0.97%]**，对应全库条数区间
  **[1,257, 3,019] / 311,992**（stratified bootstrap B=10,000，seed=20260916）
  详见 OUTSIDE_GATE_AUDIT_RESULTS.json 的 weighted_strict_opportunity_design_ci。

## 二之二、方法定型叙述（论文口径）

本文提出一种面向历史文献知识规范化的**级联式准入方法**：首先通过实体语义、身份、关系及时空约束判断结构化断言是否具备严格准入可能性；不满足条件的断言根据其不确定性保留为上下文（CONTEXTUAL）或未决（UNRESOLVED）状态，仅对仍具有严格准入可能性的候选执行高成本证据语义核验。由此在保留全部结构化信息的同时，将高确定性知识与需要上下文解释或进一步核验的信息分离。Evidence Gate 定义为
strict-admission verification，不是 full-universe classifier。

## 二之三、三层证据链（论文结果叙事）

1. **全库没有被随意丢弃**：424,150 条断言全部具有可重放准入路径——112,158 条
   进入严格候选，268,047 条进入上下文状态，43,945 条进入未决状态，
   无法解释的历史状态为 0（replay 六项零检查 ALL PASS）。
2. **前置结构合格 ≠ 证据已充分支持**：对 112,158 条严格候选逐条证据语义核验后，
   仅 31,067 条保持严格准入；31,282 条调整为上下文，49,809 条转为未决。
   结论：结构规范化合格，不代表证据已经充分支持规范断言。
3. **保守准入没有造成大规模高质量知识漏失**：对门外 311,992 条开展 5,000 条
   分层双模型盲审（双有效 4,957），证据支持完全一致率 81.26% [80.15, 82.32]，
   κ=0.514；强共识下仅 0.63%（样本）/0.66%（加权总体）被认为仍具 STRICT 机会。

## 二之四、最终三层的来源分解（写作定版）

- **UNRESOLVED 93,754 = 43,945（前置准入）+ 49,809（证据语义核验）**；
  前者 = scope 冲突 27,492 + 端点实体类型未决 16,393 + 人工遗留 60；
  后者 = 证据不支持 47,576 + 证据冲突 127 + 无可定位证据 2,106。
- **CONTEXTUAL 299,329 = 268,047（前置准入）+ 31,282（核验后降级）**；
  前者 = 谓词未完成规范化 264,635 + 不满足关系域约束 3,412；
  后者 = PARTIAL（谓词不在 partial-strict 集）27,704 + INSUFFICIENT 3,578。
- 三层全部有来源、有原因、有路径、有审计。

## 三、其它报告的地位

- `audit/method_final/` 下除上述第 2、3 项外的全部报告：**HISTORICAL**
  （历史局部实验存档，已加横幅；其数字不得进入论文）。
- `FINAL_METHOD_SUMMARY.md`：整体 HISTORICAL；其中旧估计
  「NEW STRICT ≈ 35,226 [33,744–36,708]」与旧 scope 两票结果已就地标注 **SUPERSEDED**
  （最终值 STRICT 31,067 / FINAL_SCOPE_REPORT）。
- `FINAL_EXPERIMENT_COMPARISON.md`：§1–§9 HISTORICAL；§10 为最终定版段。
- `submission_work/final_submission`、`final_submission_v2`、`final_submission_v3`、
  `final_release`：整目录 **SUPERSEDED**（历史版本存档，不可作为数字来源）。
