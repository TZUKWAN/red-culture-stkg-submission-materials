# 05 — IMCR 独立基线实验报告（B1–B12）

> **证据等级声明**：本报告全部结论属于 **E 级（independent evaluation，独立评价）**。所有一致率均为"在独立 AI 参考集（IMCR）下与参考标签的一致性"，不是事实正确率；所有基线预测均为 fresh 产物或冻结生产字段按固定映射读出，未复用任何 ERA 缓存结果（`audit/04_BASELINE_DESIGN.md` §0）。

- 主参考集：`experiments/08_independent_reference/IMCR_REFERENCE_STRONG.csv`（1246 行）
- 预测行：`experiments/09_independent_baselines/IMCR_BASELINE_RUNS.csv`（实测 31130 行 = 11 方法 × 5 任务型 × 样本数 2830；`INDEPENDENT_BASELINE_AUDIT.json` `n_runs_rows=31130`）
- 统计：`experiments/14_statistical_tests/WILSON_CI_TABLE.csv`（Wilson 95% CI，主参考 imcr_strong 口径）；审计结论 `INDEPENDENT_BASELINE_AUDIT.json` `result=PASS`

---

## 1. 方法清单与可用性矩阵

11 个落盘方法 + 1 个等价引用方法（B6）。矩阵来源：`experiments/09_independent_baselines/BASELINE_AVAILABILITY_MATRIX.csv`（60 行）与 `IMCR_BASELINE_RUNS.csv` availability_status 实测（available 15774 行 / not_available 15356 行）。✓=available（含 partial），✗=not_available。

| 方法 | entity_type (382) | relation_contract (640) | scope_adjustment (208) | identity_pair (600) | provenance_support (1000) |
|---|---|---|---|---|---|
| B1 Rule-only | ✓ 382 | ✓ 640 | ✗ 208 | ✗ 600 | ✗ 1000 |
| B2 Frozen classifier | ✓ 347/382（partial） | ✗ | ✗ | ✗ | ✗ |
| B3 Blind LLM（fresh） | ✓ 382 | ✓ 640 | ✓ 208 | ✓ 600 | ✓ 1000 |
| B4 Rule+classifier | ✓ 379/382（partial） | ✗ | ✗ | ✗ | ✗ |
| B5 Rule+blind LLM | ✓ 382 | ✓ 640 | ✗ | ✗ | ✗ |
| B6 Classifier conf 阈值 | ≡ B2 置信阈值扫描（不另发行，避免同数双计） | — | — | — | — |
| B7 Classifier margin | ✓ 347/382（partial） | ✗ | ✗ | ✗ | ✗ |
| B8 Entropy 阈值 | ✓ 347/382（partial） | ✗ | ✗ | ✗ | ✗ |
| B9 Rule–model agreement | ✓ 350/382（partial） | ✓ 640 | ✗ | ✗ | ✗ |
| B10 选择性、无结构门 | ✓ | ✓ | ✓ | ✓ | ✓ |
| B11 结构门、无弃权 | ✓ | ✓ | ✓ | ✓ | ✓ |
| B12 Full framework | ✓ | ✓ | ✓ | ✓ | ✓ |

partial 缺行原因（`BASELINE_AVAILABILITY_MATRIX.csv` `reason` 列）：

- B2/B7/B8 entity_type 缺 35 行："no member has a row in the frozen classifier score table"（冻结分类器分数表无该规范实体任何成员的分数行）；
- B4 entity_type 缺 3 行："rule abstained and no usable B2 frozen classifier prediction"；
- B9 entity_type 缺 32 行："agreement signal unavailable: rule or B2 frozen classifier prediction missing"；
- B3 五任务型全部 2830/2830 available（0 缺行）。

## 2. NOT_AVAILABLE 注册表（可审计缺口）

来源：`IMCR_BASELINE_RUNS.csv` 中 `availability_status=not_available` 的 15356 行，按（方法×任务）聚合；`INDEPENDENT_BASELINE_MANIFEST.json` `not_available_registry` 逐条记录一致。

| 方法×任务 | 行数 | 原因（note 前缀） |
|---|---|---|
| B1 × scope_adjustment | 208 | 无对应规则组件（设计 §3 N/A） |
| B1 × identity_pair | 600 | 无对应规则组件 |
| B1 × provenance_support | 1000 | 无对应规则组件 |
| B2 × relation_contract / scope / identity / provenance | 640/208/600/1000 | 设计时即 N/A（无该任务组件） |
| B2/B7/B8 × entity_type | 各 35 | 冻结分数表无成员分数行 |
| B4 × relation_contract / scope / identity / provenance | 640/208/600/1000 | 设计时 N/A |
| B4 × entity_type | 3 | 规则弃权且 B2 无可用预测 |
| B5 × scope / identity / provenance | 208/600/1000 | 设计时 N/A |
| B7/B8 × relation_contract / scope / identity / provenance | 各 640/208/600/1000 | 设计时 N/A |
| B9 × scope / identity / provenance | 208/600/1000 | 设计时 N/A |
| B9 × entity_type | 32 | 规则或 B2 预测缺失致一致性信号不可得 |
| B6（全部任务） | 0 行 | 按设计即 B2 的置信阈值扫描，不另发预测行 |

设计约束"NOT_AVAILABLE 行不得携带预测"经审计通过（`INDEPENDENT_BASELINE_AUDIT.json` `no_not_available_row_carries_prediction: true`，`n_bad_not_available_rows=0`）。

## 3. 预测映射策略（生产端 B12 及其派生）

映射版本 `imcr-baseline-mapping.v1`（`INDEPENDENT_BASELINE_AUDIT.json` `mapping_strategy_version`；spec sha256 `319e561a…`），逐条写在 `IMCR_BASELINE_RUNS.csv` note 列。摘自 `audit/04_BASELINE_DESIGN.md` §4 并与落盘数据核对：

| 任务 | B12 预测 | 置信度 | 结构门 | 披露要点 |
|---|---|---|---|---|
| entity_type | `research_entities.entity_type` | 生产 confidence | `type_validation_status=='validated'` | **382 条中 328 条为 fallback_unresolved，无置信度、gate=0**（IMCR_BASELINE_RUNS.csv note 实测：328 行 note 含 `type_validation_status=fallback_unresolved`，confidence 空且 hard_constraint_pass=0） |
| relation_contract | strict_semantic→`valid`；contextual→`context_only`；unresolved→`insufficient_evidence` | 生产 confidence | `semantic_status=='auto_accepted' AND risk_tier∈{A,B}` | 生产端**恒不预测 `invalid`**（无"判伪"标签）；640 行实测 gate=1 者 462 |
| scope_adjustment | 恒 `AFTER_BETTER`（闭包后状态即系统主张） | 无（不虚构代理分数） | gate=1 | 严格口径：仅参考=AFTER_BETTER 记 correct |
| identity_pair | 规范成员共属查询 → `same_entity`/`different_entity` | 无 | gate=1 | 600/600 置信度空（生产身份归并无逐对置信） |
| provenance_support | strict_semantic→`fully_supported`；contextual→`partially_supported`；unresolved→`insufficient_evidence` | 生产 confidence | `n_provenance_rows>0`（发布安全不变量） | 恒不预测 `unsupported`/`contradicted` |

B12 预测分布实测（IMCR_BASELINE_RUNS.csv）：entity_type 16 类有预测（Person 60 / Event 59 / Place 55 / Organization 52 / Concept 46 …）；relation_contract valid 142 / context_only 320 / insufficient_evidence 178；scope AFTER_BETTER 208；identity same 300 / different 300；provenance fully 400 / partially 300 / insufficient 300。

规则/分类器/盲 LLM 映射（B1/B2/B4/B5/B7/B8/B9/B3）见 `audit/04_BASELINE_DESIGN.md` §5/§6；B3 为 gpt-5.6-luna 对冻结盲化 payload 的 fresh 调用（2830 条 OK，`INDEPENDENT_BASELINE_MANIFEST.json` `b3_stats.calls_per_task`），不复用 judge 票。

## 4. 逐任务×方法一致率（Wilson 95% CI，主参考 = imcr_strong）

来源：`experiments/14_statistical_tests/WILSON_CI_TABLE.csv`。coverage 的 n = 该任务在 strong 参考下的覆盖数；selective_accuracy 的 n = 接受（curve 工作点）或全覆盖（point_only）数。表中记"acc（n=…）"；完整 CI 见源 CSV。

### 4.1 entity_type（strong 参考 n=276）

| 方法 | coverage（n=276） | 一致率（n=接受数） |
|---|---|---|
| B12 Full framework | 0.1486 [0.1114, 0.1953]（41/276） | **0.9268** [0.8057, 0.9748]（n=41，38/41） |
| B10 选择性无结构门 | 同 B12（消融） | 同 B12 |
| B11 结构门无弃权 | 同 B12 | 同 B12 |
| B3 Blind LLM | 0.9058 [0.8656, 0.9349]（250/276） | **0.9880** [0.9653, 0.9959]（n=250，247/250） |
| B5 Rule+blind LLM | 0.8949 [0.8532, 0.9258]（247/276） | 0.8583 [0.8093, 0.8963]（n=247） |
| B4 Rule+classifier | 0.4891 [0.4307, 0.5478]（135/276） | 0.4815 [0.3989, 0.5651]（n=135） |
| B2 Frozen classifier | 0.2971 [0.2463, 0.3535]（82/276） | 0.3780 [0.2808, 0.4862]（n=82） |
| B7 margin / B8 entropy | 同 B2 | 同 B2 |
| B1 Rule-only | 0.2500 [0.2026, 0.3043]（69/276） | 0.5362 [0.4198, 0.6489]（n=69） |
| B9 agreement gate | 0.1920 [0.1499, 0.2426]（53/276） | 0.3962 [0.2759, 0.5306]（n=53） |

要点：B12 的 entity 一致率 0.9268 看似高，但其接受集只有 41 条（score coverage 0.1486）——328/382 生产实体为 fallback_unresolved 无置信度，硬门如实编码后 Full 只能在极小覆盖上运行（详见 06 号报告）。B3 在 coverage 0.9058 下一致率 0.9880，显著优于 Full 的运行点。

### 4.2 relation_contract（strong 参考 n=66）

| 方法 | coverage（n=66） | 一致率 |
|---|---|---|
| B12 / B11 | 0.6364 [0.5158, 0.7419]（42/66） | **0.0238** [0.0042, 0.1232]（n=42，1/42） |
| B10 | 1.0（66/66） | 0.1061 [0.0523, 0.2031]（7/66） |
| B3 Blind LLM | 1.0 | 0.9394 [0.8543, 0.9762]（62/66；注意：主参考含同模型 Judge B 票，见 §6） |
| B1 Rule-only | 0.2424 [0.1551, 0.3581]（16/66） | 0.0 [0, 0.1936]（0/16） |
| B5 / B9 | 同 B1 coverage | 0.0（0/16） |
| B2/B4/B7/B8 | 0.0（N/A 任务） | — |

### 4.3 scope_adjustment（strong 参考 n=111；无逐条置信 → 仅点指标）

| 方法 | coverage | 一致率（n=111） |
|---|---|---|
| B12 / B11 / B10 | 1.0 [0.9665, 1.0] | 0.4595 [0.3697, 0.5520]（51/111，严格 AFTER_BETTER 口径） |
| B3 Blind LLM | 1.0 | 0.8108 [0.7280, 0.8728]（90/111） |
| B1/B2/B4/B5/B7/B8/B9 | 0.0（N/A 任务或全弃权） | — |

### 4.4 identity_pair（strong 参考 n=399；point_only）

| 方法 | coverage | 一致率（n=399） |
|---|---|---|
| B12 / B11 | 1.0 [0.9905, 1.0] | 0.6466 [0.5985, 0.6919]（258/399） |
| B3 Blind LLM | 1.0 | 0.9524 [0.9268, 0.9693]（380/399） |
| 其余 | 0.0（N/A 任务） | — |

### 4.5 provenance_support（strong 参考 n=394）

| 方法 | coverage | 一致率（n=394） |
|---|---|---|
| B12 / B11 / B10 | 1.0 [0.9903, 1.0] | 0.3046 [0.2612, 0.3517]（120/394） |
| B3 Blind LLM | 1.0 | 0.9365 [0.9080, 0.9567]（369/394） |
| 其余 | 0.0（N/A 任务） | — |

### 4.6 类别不均衡指标（GOAL §十八）

`{imcr_strong}_SELECTIVE_GOAL13_METRICS.csv` 提供 macro-F1：B12 entity 接受集 macro-F1=0.7306 / 全分母 0.2470；B12 relation 0.0208 / 0.0202；B12 provenance 0.1860；B3 entity 0.9274 / 0.8451、identity 0.6823、provenance 0.8822、relation 0.9042、scope 0.6672。**论文引用任何 accuracy 时必须同表给出 macro-F1 与 Wilson CI**（参考标签类别极不均衡，如 strong 参考下 provenance 的 unsupported=152 而 contradicted=2，`IMCR_REFERENCE_STRONG.csv` 实测）。

## 5. 配对检验摘要（Full vs 主要基线，来源 `MCNEMAR_TESTS.csv`）

| 任务 | 对比 | Full 胜:负 | p（精确二项） | 结论 |
|---|---|---|---|---|
| entity_type (n=276) | Full vs B1 规则 | 90:0 | 1.62e-27 | Full 显著优于规则 |
| entity_type (n=276) | Full vs B3 盲 LLM | 2:141 | **1.85e-39** | 盲 LLM 显著优于 Full |
| identity_pair (n=399) | Full vs B3 | 10:132 | 2.57e-28 | 盲 LLM 显著优于 Full |
| provenance (n=394) | Full vs B3 | 8:257 | 1.89e-65 | 盲 LLM 显著优于 Full |
| relation (n=66) | Full vs B1 | 7:36 | 8.96e-06 | 两者都差，B1 更差 |
| relation (n=66) | Full vs B3 | 1:56 | 8.05e-16 | 盲 LLM 显著优于 Full |
| scope (n=111) | Full vs B3 | 7:46 | 4.00e-08 | 盲 LLM 显著优于 Full |

诚实结论：**在全部 5 个任务型上，盲 LLM（B3）对 strong 参考的一致性都显著高于生产 Full framework**（其中 relation/scope/provenance/entity 的差异经 McNemar 显著）；Full 相对规则基线（B1）的优势只在 entity_type 与结构可评价任务上成立。这与旧论文"Full framework 全面最优"的叙事不同，是必须改写的关键点。

## 6. B3 与 Judge B 同模型的自指膨胀量化（透明性附注）

B3（gpt-5.6-luna）对**主参考（imcr_strong，含 Judge B 票）**与对**leave-B-out 参考（剔除同模型票）**的一致率之差：

| 任务 | 对 strong（含同模型票） | 对 leave-B-out | 差值 | 来源 |
|---|---|---|---|---|
| entity_type | 0.9880（247/250） | 0.9234（n=309） | ≈0.065 | imcr_strong / leave_b_out SELECTIVE_GOAL13_METRICS.csv（B3 行） |
| relation_contract | **0.9394**（62/66） | **0.2863**（n=248） | **0.653** | 同上 |
| scope_adjustment | 0.8108（90/111） | 0.6985（n=136） | 0.112 | 同上 |
| identity_pair | 0.9524（380/399） | 0.8662（n=456） | 0.086 | 同上 |
| provenance_support | 0.9365（369/394） | 0.7984（n=491） | 0.138 | 同上 |

relation_contract 上 0.939 → 0.286 的塌陷（0.653）正是 GOAL §12.1 方法论论点（同一模型既产 prediction 又参与 reference majority 会自证膨胀）的实证：**论文引用 B3 relation 数字时只能用 leave-B-out 口径 0.2863**，0.9394 仅可作为膨胀量化证据。leave-B-out 参考为 2-judge 弱共识（A/C 2/2 一致才入集，`IMCR_REFERENCE_LEAVE_B_OUT.csv` 1640 行），其结论与 04A 号报告 relation 低一致性发现共同约束解读。

## 7. 小结

1. 网格完整（11 方法 × 5 任务 = 60 格，`INDEPENDENT_BASELINE_AUDIT.json` `grid_complete=true`），缺口全部显式注册（15356 行 NOT_AVAILABLE，原因可审计）。
2. 生产端映射三条披露必须写进论文：entity 328 条 fallback_unresolved、relation/provenance 恒不预测"判伪"类标签、scope/identity 无逐条置信。
3. 主口径结论：Full framework 的比较优势仅存在于"小覆盖+硬门接受集"上（entity 0.9268@coverage 0.1486）；全覆盖点上一致率 0.024–0.647；盲 LLM 在全部任务型上一致率更高且检验显著。
