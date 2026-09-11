# FINAL SCOPE REPORT：三票共识重建 Selective Scope Closure（指令 §4）

- 生成时间：2026-09-10T07:42:31+00:00（全自动、确定性、无人工；管线 `code/experiment_pipelines/run_selective_scope_closure_v2.py`，测试 `code/tests/test_selective_scope_closure_v2.py`）
- **口径：三票 IMCR 共识**。唯一裁判 = `IMCR_V4_SCOPE_REVALIDATION_V2_ALL.csv` 的 `reference_label`（Judge A+B+C 多数票解码，110 strong + 77 weak = 187 条）；**旧两票结果（96.6%）作废**，由本报告替代（见 §6 对比）。

## 0. 结论摘要

- 三票口径 held-out（83 条，其中参考已分胜负 62 条）：
  - old closure（全 REWRITE）semantic agreement = **37.1%**（23/62）；
  - new selective closure actionable agreement = **89.3%**（25/28），弃权 34 条（弃权率 54.8%，actionable 覆盖 45.2%）；保守口径（弃权记错）= **40.3%**；
  - 配对精确 McNemar p = **2.74e-05**（old 错 new 对 25 vs old 对 new 错 3）。
- 与旧两票结果对比：v1 actionable agreement 96.6%（两票 decided 仅 35 条）→ v2 89.3%（三票 decided 62 条）；三票口径的结论在更大可评分母上成立，旧 96.6% 的高数值部分源于两票 DISAGREE 大量退出分母。

## 1. 三票参考（唯一裁判）

- 来源：`D:\REDCULTUREDATA\投稿材料_代码数据整理包\submission_work\final_submission_v3_1\experiments\01_reference_rebuild\scope_revalidation_v2\IMCR_V4_SCOPE_REVALIDATION_V2_ALL.csv`；解码链：A/B/C 三票 → IMCR V4 多数票聚合 → `reference_label`（已解码，与 `imcr_label_decoded` 逐条核验一致，0 不符）。
- 构成：110 strong_consensus + 77 weak_consensus = **187 条**；标签分布：AFTER_BETTER=56，BEFORE_BETTER=101，BOTH_WRONG=8，INSUFFICIENT_EVIDENCE=22。
- 已分胜负（decided，可评）= AFTER_BETTER / BEFORE_BETTER；未分胜负（不可评）= BOTH_WRONG / INSUFFICIENT_EVIDENCE / EQUIVALENT。
- **21 条 unresolved 不入参考**：不参与规则学习、不进入任何 agreement 分母（任务清单见 `CLOSURE3_SUMMARY.json` 的 `three_vote_reference.unresolved_task_ids`）。

## 2. 变换类型分类（join 口径）

- 规则：按 `task_id` 一对一 join `SCOPE_BY_TYPE_ERRORS.csv` 的 `transformation_type` 列，208 条全覆盖（无空值、无未知类型）。
- 类型分布（全量）：

| transformation_type | 全量 n |
|---|---:|
| `event_location→context_location` | 90 |
| `event_location→relation_location` | 5 |
| `mixed` | 16 |
| `other` | 37 |
| `unknown→event_occurrence` | 60 |

## 3. book-grouped 60/40 切分（规则写明）

- **B1 book 键**：SCOPE_REVALIDATION_V2_METADATA.csv 的 books 列容错解析（严格 json → 单引号归一 json → ast.literal_eval）；空/[] → 无书 → nobook:{task_id} 单任务分量按同一确定性 60/40 hash 参与分配（同 data/frozen_splits 对 no-book 任务 hash 分配的精神，种子同为 20260908）；来源分布：nobook_single_task_component=184，metadata_books_column=24。
- **B2 并查集分量原子**：任务—书二部图并查集（复用 `build_frozen_splits.py` 思路），同书任务（含 unresolved 任务）并入同一分量，分量绝不跨 learn/held-out。
- **B3 无书任务**：单任务分量（键 `nobook:{task_id}`），按 60/40 hash 与其他分量一起参与分配，不强制塞入 held-out（同 `data/frozen_splits` 对 no-book 任务 hash 分配的精神）。
- **B4 确定性排序**：分量按 sha256(seed:closure3:cid) 升序，**种子 = 20260908**（与 `data/frozen_splits/SPLIT_MANIFEST.json` 同种子）。
- **B5 预算**：累计任务数 ≤ round(0.60×208) = 125 的最大前缀 → learn，其余 → held-out。
- 实际切分：**learn 125 条（60.1%） / held-out 83 条（39.9%）**，201 个分量（learn 122 / heldout 79）；逐任务归属见 `CLOSURE3_SUMMARY.json` 的 `split` 节。学习与评价严格隔离，零回流。

### 3.1 类型 × split × 参考标签构成

| transformation_type | learn n（A/B/decided/不入参考） | heldout n（A/B/decided/不入参考） |
|---|---|---|
| `event_location→context_location` | 55（6/39/45/5） | 35（3/25/28/3） |
| `event_location→relation_location` | 5（0/2/2/2） | 0（0/0/0/0） |
| `mixed` | 9（0/8/8/1） | 7（0/6/6/0） |
| `other` | 24（10/5/15/3） | 13（6/1/7/2） |
| `unknown→event_occurrence` | 32（17/8/25/1） | 28（14/7/21/4） |

*A/B/decided/不入参考 = AFTER_BETTER / BEFORE_BETTER / 已分胜负 / NOT_IN_REFERENCE。

## 4. learn 规则表（仅在 60% learn ∩ 三票参考内学习）

- 判据：decided = AFTER_BETTER + BEFORE_BETTER（三票共识已分胜负）；**REWRITE**：双侧精确二项 p<0.05 且 AFTER 占优且 decided≥10；**RETAIN**：p<0.05 且 BEFORE 占优且 decided≥10；其余 **UNRESOLVED**（保守弃权）。learn 内未见类型 apply 时同样 UNRESOLVED。
- held-out 不参与规则学习（无回流）；规则可由 learn 任务逐一复算（见测试）。

| transformation_type | action | learn n | decided | AFTER : BEFORE | AFTER 胜率 | 双侧精确二项 p | 判据 |
|---|---|---:|---:|---:|---:|---:|---|
| `event_location→context_location` | **RETAIN** | 55 | 45 | 6 : 39 | 13.3% | 0.00000 | decided=45>=10 且 p=0.00000<0.05 |
| `event_location→relation_location` | **UNRESOLVED** | 5 | 2 | 0 : 2 | 0.0% | 0.50000 | decided=2<10 |
| `mixed` | **UNRESOLVED** | 9 | 8 | 0 : 8 | 0.0% | 0.00781 | decided=8<10 |
| `other` | **UNRESOLVED** | 24 | 15 | 10 : 5 | 66.7% | 0.30176 | p=0.30176>=0.05（不显著） |
| `unknown→event_occurrence` | **UNRESOLVED** | 32 | 25 | 17 : 8 | 68.0% | 0.10775 | p=0.10775>=0.05（不显著） |

## 5. held-out 新旧对比（裁判 = 三票解码标签）

- 旧 closure（生产现状）：全部候选 REWRITE 为 after。
- 新 closure：按 §4 规则（REWRITE / RETAIN / UNRESOLVED 弃权）。
- 映射：REWRITE 且裁判=AFTER_BETTER → 对；RETAIN 且裁判=BEFORE_BETTER → 对；裁判未分胜负（BOTH_WRONG/INSUFFICIENT_EVIDENCE）与不入参考（21 条 unresolved）不可评。

| 口径 | n | 正确 | semantic agreement |
|---|---:|---:|---:|
| old（全 REWRITE，decided 分母） | 62 | 23 | **37.1%** |
| new（规则，actionable=REWRITE/RETAIN） | 28（弃权 34） | 25 | **89.3%** |
| new（保守：弃权记错，分母=全部 decided） | 62 | 25 | 40.3% |

- actionable coverage：decided 上 **45.2%**，held-out 全量上 33.7%；abstention rate：decided 上 **54.8%**，held-out 全量上 57.8%。
- 配对（同一批 28 条 actionable decided 任务的二值配对）：双方全对 0、双方全错 0、**old 对 new 错 3、old 错 new 对 25**；精确 McNemar p = **2.74e-05**。
- 结构安全：REWRITE 只改 role/owner 四字段（程序化核验 416 个 A/B 展示位，越界键 0 个），**structural violations = 0**（论证见 §8）。

### 5.1 held-out 分类型对比

| transformation_type | action_new | heldout n | 不入参考 | decided | old 正确 | new 正确(actionable) | new 弃权 |
|---|---|---:|---:|---:|---:|---:|---:|
| `event_location→context_location` | RETAIN | 35 | 3 | 28 | 3 | 25 | 0 |
| `mixed` | UNRESOLVED | 7 | 0 | 6 | 0 | 0 | 6 |
| `other` | UNRESOLVED | 13 | 2 | 7 | 6 | 0 | 7 |
| `unknown→event_occurrence` | UNRESOLVED | 28 | 4 | 21 | 14 | 0 | 21 |

## 6. 新旧对比表：v1 两票口径（作废） vs v2 三票口径（本报告）

| 指标 | v1（两票 A+B，作废） | v2（三票 A+B+C，本报告） |
|---|---|---|
| 裁判 | 两票一致才可评（DISAGREE 38.5% 不可评） | 三票多数票解码，187/208 有参考标签 |
| held-out 规模 | 83 条 | 83 条 |
| held-out decided（可评分母） | 35 | 62 |
| old agreement（全 REWRITE） | 25.7%（9/35） | **37.1%**（23/62） |
| new actionable agreement | 96.6% （28/29） | **89.3%**（25/28） |
| new 保守口径（弃权记错） | 80.0% | **40.3%** |
| new 弃权条数 | 6 | 34 |
| 精确 McNemar p | 5.72e-06 | **2.74e-05** |

- **对比结论**：v1 的 96.6% 是在两票 decided 仅 35 条的小分母上取得的——38.5% 的两票 DISAGREE 任务整体退出评价；三票口径把第三票的裁决纳入后，可评分母扩大到 62 条，new closure 的 actionable agreement 为 **89.3%**、保守口径 **40.3%**，且 McNemar 显著（p=2.74e-05）。v1 结果作废，以本报告为准；两口径的动作定义、映射与阈值完全一致，差异全部来自裁判聚合方式（详见 §7）。

## 7. 两票 vs 三票口径差异说明

1. 裁判票数：v1 用两票盲评（A+B），两票不一致即 DISAGREE（208 条中 80 条，38.5%）不可评；v2 用三票 IMCR 共识（A+B+C 多数票解码），187/208 条获得确定参考标签（110 strong + 77 weak），21 条三票仍 unresolved 的任务不入参考、不参与学习与评分。
2. 参考标签来源：v1 的判定 = 两票一致时的解码票；v2 的判定 = reference_label（IMCR V4 已解码，与 imcr_label_decoded 逐条核验一致）。
3. book 键：v1 = payload 证据预览 evidence_excerpts[].source_title 优先、books 列回退；v2 按指令只用 SCOPE_REVALIDATION_V2_METADATA.csv 的 books 列（容错 JSON 解析），无书任务为单任务分量按 60/40 hash 分配。
4. 切分 hash 域：v1 = sha256(f"{seed}:closure:{cid}")，v2 = sha256(f"{seed}:closure3:{cid}")；两者同种子 20260908、同分量原子规则，但 book 键不同导致分量不同，两侧任务集合不要求一致，亦不可互相回流。
5. 可评分母：v1 held-out decided = 35/83（两票一致才可评）；v2 held-out decided = 三票共识分出胜负的任务数（DISAGREE 被第三票消解，decided 占比大幅上升）。
6. 规则判据不变：每类型 AFTER:BEFORE 双侧精确二项 p<0.05 且 decided>=10；不变式：learn/held-out 严格隔离、UNRESOLVED 弃权、REWRITE/RETAIN 动作映射一致。

## 8. 结构安全论证（structural violations 恒 0）

- new closure 的 REWRITE 仅改写 time_role/time_owner/space_role/space_owner 四字段，不改谓词、论元、实体与任何结构约束；RETAIN 保持 before 状态，零改动。
- 程序化核验：对 208 个 payload 的 A/B 展示位状态对象逐一检查，416 个槽位中含 role/owner 四字段以外键的为 **0 个**。
- 因此新 closure 的 REWRITE 与生产改写共用同一改写面（仅 time_role/time_owner/space_role/space_owner），不可能引入结构约束违例：**structural violations = 0**。PASS：REWRITE 改写面 ⊆ role/owner 四字段，structural violations 恒 0。

## 9. 局限声明

1. 208 条 final_entity_type_scope_closure 任务为该修复的全量总体，本实验的 60/40 切分并非从更大总体抽样；切分唯一目的：避免规则学习与效果评价同源（同书任务绝不跨侧）。
2. 三票参考仅 187/208 条（110 strong + 77 weak）；21 条 unresolved 任务不入参考：不参与规则学习，也不进入任何 agreement 分母（held-out 上仅计入全量覆盖率口径）。
3. 参考标签中 INSUFFICIENT_EVIDENCE（22 条）与 BOTH_WRONG（8 条）为已解码但未分胜负，按动作正确性口径不可评（REWRITE/RETAIN 都不可能'对'），不计入 agreement 分母。
4. UNRESOLVED 类型按弃权处理：不进入 actionable agreement 分母；保守口径（弃权记错）一并列出。
5. learn 内 decided<10 或 p>=0.05 的类型一律 UNRESOLVED（保守）；即便其在 held-out 上方向显著，规则也不得据 held-out 回流改判。
6. v1（两票）与 v2（三票）的切分与可评分母不同，96.6% → 新值的对比是口径级对比，不能解释为同一批任务上的逐条升降。
