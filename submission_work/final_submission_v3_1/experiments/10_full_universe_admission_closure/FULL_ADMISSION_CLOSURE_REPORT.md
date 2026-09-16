# FULL ADMISSION CLOSURE REPORT — 全库结构准入闭环

生成：2026-09-16　实验目录：`experiments/10_full_universe_admission_closure/`
配套重放器：`code/experiment_pipelines/replay_full_admission.py`（六项零检查 ALL PASS）

## 一、424,150 条每一条如何得到最终状态？（问题 1）

每条断言的最终状态 = **两级确定性流水线的合成**，全部可从冻结输入重放：

1. **v2 结构准入**（冻结规则 `284_materialize_stkg_v2_research_base.py` L671-674 CASE，
   本实验用 importlib 原样加载并逐条重求值）：
   `semantic_status='auto_accepted' ∧ predicate 非 raw:* ∧ 双端点实体类型 validated
   ∧ relation_domain_range_pass_v2(...)` 全部成立 → **strict 候选（pre-gate strict_semantic，
   112,158 条）**；auto_accepted 但有 conjunct 失败 → **pre-gate CONTEXTUAL（268,047）**；
   semantic_status ∈ {model_review, manual_review} → **pre-gate UNRESOLVED（43,945）**。
   重放结果与升级管线 BASELINE 普查（stkg_upgrade_log，2026-09-10T16:15:39）逐层一致。
2. **证据语义门**（仅 strict 候选 112,158 进入；qwen3.5-4b，reasoning=off，T=0）：
   FINAL_TIERING.csv 给出 31,067 / 31,282 / 49,809，零持留。
3. 门外 311,992 条保留其 pre-gate 终态（contextual / unresolved）。

## 二、为什么只有 112,158 条进入 Evidence Gate？（问题 2）

Evidence Gate 的定义是 **strict-admission verification**（严格准入核验），
不是 full-universe classifier。只有通过 v2 全部结构准入 conjunct（规范化谓词、
双端点实体类型已验证、关系域约束兼容）的断言才具有 STRICT 准入可能性；
其余 311,992 条已被某个确定性结构条件提前定性（见下），对其调用语义门
只会重复其已知的结构排除原因。这是 selective admission 设计：以 coverage 换 precision。

## 三、43,945 条前置 UNRESOLVED 的逐条原因（问题 3；unexplained = 0）

| primary_blocking_reason | 条数 | 代码依据 |
|---|---|---|
| scope_conflict_model_review | 27,492 | 256 脚本：scope 冲突 → semantic_status='model_review', risk='C' |
| endpoint_entity_type_unresolved | 16,393 | 256 脚本：端点实体 type_validation_status ≠ validated → model_review |
| manual_review_legacy | 60 | 人工审查遗留（manual_review） |
| **合计** | **43,945** | 逐条重放 0 mismatch；UNEXPLAINED_QUEUE.csv 为空 |

## 四、268,047 条前置 CONTEXTUAL 为何未进 STRICT 候选？（问题 4）

strict 候选 CASE 的失败 conjunct（每条记录全部失败项，primary 取首失败项）：

| primary_blocking_reason | 条数 |
|---|---|
| predicate_raw_not_normalized（raw:* 非规范化谓词） | 264,635 |
| relation_domain_range_violation（关系域约束违反） | 3,412 |
| （subject/object_entity_type_not_validated 在 raw 之前无主因行；
  明细见 LEDGER.soft_blockers 列） | — |
| **合计** | **268,047** |

即 98.7% 的前置 CONTEXTUAL 携带非规范化谓词（`raw:*`），从未形成受控关系，
结构上不构成 STRICT 候选。

## 五、无法解释的历史 tier？（问题 5）

**0。** UNEXPLAINED_QUEUE.csv 为空文件（仅表头）；
`replay_full_admission.py` 的 unexplained_unresolved=0、
blocking_reason_missing_non_strict=0、decision_path_missing=0。

## 六～八、门外样本的 STRICT 机会、性质与最终 STRICT 精度（问题 6/7/8）

**审计执行**：n=5,000（CONTEXTUAL 2,500 / UNRESOLVED 2,500，seed=20260916，
按 primary_blocking_reason/predicate/source_book 分层，pop≥500 的 blocker 层 ≥50），
双独立裁判盲评（gpt-oss-20b + qwen3-8b），双裁判有效联合判定 **n=4,957**。

| 指标 | 点估计 | 95% CI | 分子/分母 |
|---|---|---|---|
| 裁判 evidence_support 完全一致率 | 0.8126 | [0.8015, 0.8232] | 4,028/4,957 |
| Cohen's kappa（evidence_support） | 0.5136 | — | — |
| recommended_state 一致率 | 0.8899 | [0.8808, 0.8983] | 4,411/4,957 |
| strict_eligible 一致率 | 0.9352 | [0.9280, 0.9418] | 4,636/4,957 |
| **CONTEXTUAL 强共识 STRICT 机会率** | **0.0068** | [0.0043, 0.0109] | 17/2,483 |
| **UNRESOLVED 强共识 STRICT 机会率** | **0.0057** | [0.0034, 0.0095] | 14/2,474 |
| 总体强共识 STRICT 机会率 | 0.0063 | [0.0044, 0.0089] | 31/4,957 |
| **加权总体 STRICT 机会率**（还原至 311,992） | **0.0066** | — | ≈2,070 条 |

分 blocker 强共识 STRICT 机会率：raw 谓词 0.67%（16/2,404）、scope 冲突 0.64%
（10/1,573）、端点类型未决 0.45%（4/898）、关系域违反 1.27%（1/79）、manual 遗留
0%（0/3）——**所有 blocker 层均 <1.3%**。

**问题 6 答案**：门外 5,000 样本中强共识 STRICT 机会 31 条（0.63%）；
按 stratum 权重还原总体 ≈ 0.66% × 311,992 ≈ **2,070 条**（CI 上界 ~0.89% ≈ 2,780 条）。

**问题 7 答案**：这是 **selective precision–coverage tradeoff 的预期代价，不是错误**。
结构准入以「未归一化谓词/端点类型未决/scope 冲突」提前排除的断言，其证据可及性
天然受限（样本中大量 NO_EVIDENCE/INSUFFICIENT），0.66% 的机会率以 99.28% 的
严格层精度为对价；两条路线在论文中必须成对报告。

**问题 8 答案**：最终 STRICT precision = **0.9928**（门内独立双裁判强共识口径，
n=4,427，95% CI 见 AUDIT_RESULTS.json；FP 率 0.0041）。

## 九、全库最终三层（问题 9）

**STRICT 31,067 / CONTEXTUAL 299,329 / UNRESOLVED 93,754**（合计 424,150）。

## 十、可重放性（问题 10）

是。`python code/experiment_pipelines/replay_full_admission.py`：
row_count_diff=0、fact_id_diff=0、tier_diff=0、pre_gate_tier_diff=0、
decision_path_missing=0、blocking_reason_missing_non_strict=0、unexplained_unresolved=0。
