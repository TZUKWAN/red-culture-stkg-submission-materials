# 07 — 208 条时空作用域调整的独立验证报告

> **证据等级声明**：本报告全部结论属于 **E 级（independent evaluation，独立评价）**。所有"更优/正确"均指"与独立 AI 参考的偏好一致"，不构成对历史事实本身正确性的判断（GOAL §二十七措辞边界：只能写"提高/未提高时空语义归属合理性"，不得写"修正了历史错误"）。

- 任务全集：`experiments/10_structural_validation/SCOPE_ADJUSTMENT_TASKS.jsonl`（208 条全量，不抽样；`SCOPE_ADJUSTMENT_EXTRACTION_AUDIT.json` `total_adjustments=208`，`outputs...rows=208`）
- 共识参考：`experiments/08_independent_reference/IMCR_REFERENCE_STRONG.csv` / `IMCR_REFERENCE_ALL.csv` 中 task_type=scope_adjustment 行
- 盲化与解码：A/B 匿名展示位 + `payloads/SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING.csv`（sha256 `63856b42…`，见 `figures/imcr_scope_validation_AUDIT.json` `inputs.ab_mapping`）
- 图件：`figures/imcr_scope_validation.png/.pdf`（GOAL §三十 图C，AUDIT PASS）

---

## 1. 任务构成（抽取向 judge 隐藏生产标签）

来源：`SCOPE_ADJUSTMENT_EXTRACTION_AUDIT.json`（`dimension_distribution` / `*_role_transitions`；生产字段 semantic_status、risk_tier、research_tier 已从 payload 剔除）。

- 维度：time_role_changed 104、time_owner_changed 103、space_role_changed 120、space_owner_changed 111、时空同时变化 16；仅时间 88、仅空间 104。
- 典型转移：时间角色 unknown→event_occurrence 60；空间角色 event_location→context_location 90、event_location→relation_location 21。
- 数据库一致性检查：`research_scope_adjustments.final_*` 与 `research_assertions` 当前值 mismatch_count=0。
- 调整原因全部为 `final_entity_type_scope_closure`（208/208）。

盲评协议：closure 前/后状态确定性随机化为 a/b 展示位（`SHA-256(f"{seed}::{task_id}")` 首字节奇偶；主种子 20260907），judge 以 A_BETTER/B_BETTER 作答，共识聚合后解码回 BEFORE_/AFTER_（协议 §2.4）。

## 2. judge 共识分布（诚实核心：改后状态未获多数偏好）

来源：`IMCR_REFERENCE_STRONG.csv` / `IMCR_REFERENCE_ALL.csv` 中 scope_adjustment 行的 `imcr_label_decoded` 实测统计；unresolved 计数来自 `IMCR_CONSENSUS_MANIFEST.json`（24）。图C 直观呈现同一分布。

| 参考口径 | labeled | BEFORE_BETTER | AFTER_BETTER | EQUIVALENT | BOTH_WRONG | INSUFFICIENT_EVIDENCE | unresolved |
|---|---|---|---|---|---|---|---|
| strong（3/3 一致） | 111 | **58** | **51** | 0 | 0 | 2 | 24（不进参考） |
| strong+weak（ALL） | 184 | **97** | **70** | 0 | 1 | 16 | 24 |
| leave-B-out（2/2） | 136 | 71 | 59 | 0 | 0 | 6 | 72 |
| leave-A-out（2/2） | 123 | 65 | 52 | 0 | 0 | 6 | 85 |

**核心诚实发现**：在两个主参考口径下，judge 共识更常认为 **改前（BEFORE）状态更优**（strong：58 vs 51；ALL：97 vs 70）。即 208 条作用域调整作为整体，**未通过独立 AI 参考的语义合理性验证**。逐 judge 解码票（图C 右panel，`raw_runs/scope_adjustment/*.jsonl` 实测）显示三 judge 单票均接近 50/50（A：94 vs 92；B：81 vs 80；C：87 vs 87），共识层面 BEFORE 仅以微弱多数领先——正确的结论是"**独立证据不支持'闭包后状态系统性更优'的主张**"，而非"闭包使质量变差"。

## 3. B12（生产端主张 = AFTER_BETTER）严格口径一致率

严格口径（`audit/04_BASELINE_DESIGN.md` §4.3，论文须披露）：仅当参考 = AFTER_BETTER 才记 correct；EQUIVALENT/BOTH_WRONG/INSUFFICIENT/BEFORE_BETTER 均计 error。B12 对 208 条恒预测 AFTER_BETTER、无逐条置信（`IMCR_BASELINE_RUNS.csv` 实测：scope_adjustment 208 行 prediction 全为 AFTER_BETTER、confidence 全空）。

来源：B12 行取自 `14_statistical_tests/WILSON_CI_TABLE.csv`（B12 scope_adjustment selective_accuracy 行，n=111；GOAL13 文件无 B12 scope 行）；B3 行取自 `imcr_strong/imcr_strong_SELECTIVE_GOAL13_METRICS.csv`；ALL/leave-B 口径由 `IMCR_BASELINE_RUNS.csv` × 参考 CSV 联表复算。

| 口径 | B12 一致率（=AFTER 记对） | B3 一致率 | n |
|---|---|---|---|
| imcr_strong | 0.4595 [0.3697, 0.5520]（51/111） | 0.8108 [0.7280, 0.8728]（90/111） | 111 |
| imcr_all | 0.3804（70/184） | 0.7174（132/184） | 184 |
| leave_b_out | 0.4338（59/136） | 0.6985（95/136） | 136 |

B12 的 95% CI 覆盖 0.5 之下沿——不能声称"改后状态与独立参考多数一致"。

## 4. win / tie / loss 与 McNemar（B12 vs B3，二值化 = 参考是否 AFTER_BETTER）

来源：`14_statistical_tests/MCNEMAR_TESTS.csv`（task_type=scope_adjustment 行；win/tie/loss = full_wins/ties/full_losses）。

| 口径 | B12 胜 | 平 | B12 负 | 精确二项 p |
|---|---|---|---|---|
| imcr_strong（n=111） | 7 | 58 | 46 | 4.00e-08 |
| leave_b_out（n=136） | 13 | 74 | 49 | 4.82e-06 |

即：在共享样本集上，盲 LLM 与共识同向的条目显著多于生产恒选 AFTER 的条目。

对照组（同一文件）：B12 vs B1 规则 = 51:0（p=8.88e-16）——B1 对 scope 无规则组件（coverage=0，`WILSON_CI_TABLE.csv`），该对比只说明"有预测优于无预测"，无语义含义。

## 5. 与旧证据的关系（GOAL §二十八）

- 旧证据：全库确定性回放 `w/o Role-owner Closure` changed_vs_full=208（B 级 deterministic replay；`STRUCTURAL_REPLAY_AUDIT.json` `variant_stats`，与 v2 报告 208 一致 cross_checks.match=true）。该数字只说明"闭包改变了 208 条断言的时空归属"，**从未证明改变方向在语义上更优**。
- 新证据（本报告）：IMCR 对这 208 条的盲评显示改后状态未获多数偏好（§2），生产主张严格口径一致率 0.4595（strong）/0.3804（all）。
- 处置：论文 4.5 节必须改写——208 条调整的**结构变化本身**可保留为确定性回放事实（B 级），但**不得**再表述为"提高了时空归属合理性"；应表述为"独立 AI 参考未显示改后状态系统性更优（改前 58 vs 改后 51，strong 口径），该闭包的语义收益未获独立证据支持，需要人工复核或证据增强后重评"。

## 6. 局限（详见 12_EXPERIMENT_LIMITS.md）

- 参考仍为 AI judge 而非领域专家；scope 任务 payload 中证据文本可用性不均（发布库仅存谱系指针时如实标注 evidence_availability_note，协议 §5.3）。
- strong 口径仅覆盖 111/208；weak 档 73 条方向分布与 strong 一致（BEFORE 居多），unresolved 24 条不参与统计。
- 判定的是"a/b 两状态何者更优"，无法评价"两者都错"之外第三种更优归属（BOTH_WRONG 仅 1 条，ALL 口径）。
