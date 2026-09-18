# CONSENSUS_RECONCILIATION — 972/973 差异逐条调和

日期：2026-09-19　结论：**差异完全解释，冻结审计 972 为准确口径，予以采用。**

## 一、冲突来源

| 口径 | STRICT 强共识 n | supported | negative(UNSUP+CONTRA) | insufficient |
|---|---|---|---|---|
| 冻结审计（score_quality_audit.py，权威） | **972** | 965 | 4（含 CONTRADICTED 1） | 3 |
| 上一轮级联脚本（analyze_cascaded_stages.py） | 973（错误） | 965 | 4 | 3（另单列 CONTRADICTED 1） |

上一轮脚本把 CONTRADICTED 同时计入 `unsupported`（4，已含）与单列的
`contradicted`（1），造成 **CONTRADICTED 双计 +1**，972 → 973。

## 二、逐 fact_id 差异记录（全量，共 1 条）

| fact_id | Judge A | Judge B | 旧冻结分类 | 新脚本分类 | 差异原因 | 最终采用口径 |
|---|---|---|---|---|---|---|
| IFACT-003a226a1c4689f5d4caecc1 | CONTRADICTED | CONTRADICTED | negative（=UNSUPPORTED+CONTRADICTED，4 条之一） | 被 同时计入 unsupported(4) 与 contradicted(1) | 类别定义非互斥：CONTRADICTED ⊂ negative | 采用冻结分类：negative（互斥三分：supported/negative/insufficient） |

复算验证：supported 965 + negative 4 + insufficient 3 = **972**，与
`AUDIT_RESULTS.json` 的 `strict_support_precision_strong_consensus_detail`
（A=965，B=4，N=972）逐项一致。

## 三、修正措施

1. 修正 `analyze_cascaded_stages.py` 的分类为互斥三分
   （supported = FULLY+PARTIAL；negative = UNSUPPORTED+CONTRADICTED；
   insufficient 单列），任何分类合计必须等于 consensus_n。
2. 冻结审计（AUDIT_RESULTS.json）未做任何修改。
3. 上轮 42.55%/16.40%/29.79%/22.20%/+26.15pp 等无条件占比退出论文正文，
   移入诊断附录并更名为 unconditional strong-consensus support share。
