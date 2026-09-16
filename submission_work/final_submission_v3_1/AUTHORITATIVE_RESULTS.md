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
- 门内 STRICT（n=4,427 盲评）：强共识支撑精度 **0.9928**（PASS 线 0.90），FP 0.0041
- 门外宇宙（n=5,000 分层，seed=20260916，双裁判）：见 OUTSIDE_GATE_AUDIT_RESULTS.json
  （strict 机会率 / 分 blocker 机会率 / 精度–覆盖解释）

## 三、其它报告的地位

- `audit/method_final/` 下除上述第 2、3 项外的全部报告：**HISTORICAL**
  （历史局部实验存档，已加横幅；其数字不得进入论文）。
- `FINAL_METHOD_SUMMARY.md`：整体 HISTORICAL；其中旧估计
  「NEW STRICT ≈ 35,226 [33,744–36,708]」与旧 scope 两票结果已就地标注 **SUPERSEDED**
  （最终值 STRICT 31,067 / FINAL_SCOPE_REPORT）。
- `FINAL_EXPERIMENT_COMPARISON.md`：§1–§9 HISTORICAL；§10 为最终定版段。
- `submission_work/final_submission`、`final_submission_v2`、`final_submission_v3`、
  `final_release`：整目录 **SUPERSEDED**（历史版本存档，不可作为数字来源）。
