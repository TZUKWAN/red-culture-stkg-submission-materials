# OUTSIDE GATE AUDIT REPORT — 门外宇宙独立双裁判盲评

生成：2026-09-17T04:44:59.132735+08:00　样本：n=4957（协议 5,000，
seed=20260916，分层：primary_blocking_reason/predicate/source_book）
裁判：Judge A = gpt-oss-20b，Judge B = qwen/qwen3-8b（均独立于生产模型 qwen3.5-4b；
盲评：不可见 tier/blocking reason/decision path/生产判定）。

## 一致性指标

| 指标 | 值 |
|---|---|
| 五档 evidence_support 完全一致率 | 0.8126 [95%CI 0.8015,0.8232] (4028/4957) |
| Cohen's kappa（evidence_support） | 0.5136 |
| recommended_state 一致率 | 0.8899 [95%CI 0.8808,0.8983] (4411/4957) |
| strict_eligible 一致率 | 0.9352 [95%CI 0.9280,0.9418] (4636/4957) |
| identity_decidable 一致率 | 0.1818 [95%CI 0.1713,0.1927] (901/4957) |
| relation_supported 一致率 | 0.7109 [95%CI 0.6981,0.7234] (3524/4957) |
| scope_decidable 一致率 | 0.2582 [95%CI 0.2462,0.2706] (1280/4957) |

## STRICT 机会（selective precision–coverage 的 coverage 侧）

| 指标 | 值 |
|---|---|
| Judge A 判 strict_eligible=YES | 0.0583 [95%CI 0.0521,0.0652] (289/4957) |
| Judge B 判 strict_eligible=YES | 0.0115 [95%CI 0.0089,0.0149] (57/4957) |
| 强共识（双 YES）样本口径 | 0.0063 [95%CI 0.0044,0.0089] (31/4957) |
| **强共识总体加权（按 blocker stratum 权重还原到 311,992）** | **0.0066，设计型 95%CI [0.0040, 0.0097]**（stratified bootstrap B=10,000，seed=20260916；条数区间 [1,257, 3,019]） |
| CONTEXTUAL 层强共识 strict 机会 | 0.0068 [95%CI 0.0043,0.0109] (17/2483) |
| UNRESOLVED 层强共识 strict 机会 | 0.0057 [95%CI 0.0034,0.0095] (14/2474) |
| 门外样本 exact tier 还原一致率 | 0.4303 [95%CI 0.4166,0.4441] (2133/4957) |

## 分 blocker 的强共识 STRICT 机会率

| blocking reason | 机会率 | 分子/分母 |
|---|---|---|
| hard_blocker:endpoint_entity_type_unresolved | 0.0045 | 4/898 |
| hard_blocker:manual_review_legacy | 0.0 | 0/3 |
| hard_blocker:scope_conflict_model_review | 0.0064 | 10/1573 |
| strict_candidate_conjunct_failed:predicate_raw_not_normalized | 0.0067 | 16/2404 |
| strict_candidate_conjunct_failed:relation_domain_range_violation | 0.0127 | 1/79 |

## 解释（十、解释原则）

门外样本的 STRICT 机会是 **selective admission 以 coverage 换 precision 的预期代价**，
不是系统错误：门外断言因 raw 谓词未归一化 / 关系域违反 / 端点实体类型未决 / scope
冲突而被结构准入提前排除。其 STRICT 机会主要受证据可及性限制
（无证据指针的断言裁判判 NO_EVIDENCE，无法升级）。论文必须同时报告：
严格层 precision（门内审计 0.9928）× coverage（112,158/424,150 结构候选率）
以及本报告的升级机会率。
