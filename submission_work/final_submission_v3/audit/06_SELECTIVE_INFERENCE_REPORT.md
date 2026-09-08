# 06 — IMCR 选择性推断实验报告（三参考模式）

> **证据等级声明**：本报告全部结论属于 **E 级（independent evaluation，独立评价）**。"风险"均为**选择性风险**（接受集中与独立 AI 参考不一致的比例），"正确"均为"与独立参考一致"；不涉及事实真值主张（GOAL §二十七）。

- 三种参考模式（同一评价器 `run_selective_inference.py`，三次运行）：
  1. `imcr_strong`（主口径）：`experiments/13_selective_inference_independent/imcr_strong/`
  2. `imcr_all`（strong+weak）：`experiments/13_selective_inference_independent/imcr_all/`
  3. `leave_b_out`（B3 主对照参考）：`experiments/13_selective_inference_independent/leave_b_out/`
- 管线自检：三目录 `*_RISK_COVERAGE_REPORT.md` 均 Result: PASS；AUGRC 闭式交叉校验最大差 5.551e-17（strong）/ 1.110e-16（leave_b_out）；bootstrap 每 applicable 曲线 2000 次固定种子、逐 replicate 落盘（strong 目录 BOOTSTRAP 48000 行 + 表头）。
- 各模式评价分母（来自各模式 SELECTIVE_GOAL13_METRICS.csv 的 n_total 列）：

| 任务 | imcr_strong | imcr_all | leave_b_out |
|---|---|---|---|
| entity_type | 276 | 366 | 309 |
| relation_contract | 66 | 552 | 248 |
| scope_adjustment | 111 | 184 | 136 |
| identity_pair | 399 | 586 | 456 |
| provenance_support | 394 | 905 | 491 |

（对应参考集行数 1246 / 2593 / 1640，`IMCR_CONSENSUS_MANIFEST.json`。）

---

## 1. GOAL-13 点指标（主口径 imcr_strong，B12 与 B3）

来源：`imcr_strong/imcr_strong_SELECTIVE_GOAL13_METRICS.csv`（管线产出的全部行）与 `experiments/14_statistical_tests/WILSON_CI_TABLE.csv`。**口径披露**：GOAL13 文件中 B12 缺 scope_adjustment 与 identity_pair 两行（该两格无逐条置信、管线未产出指标行）；下表这两格的数字取自 WILSON_CI_TABLE.csv 的 B12 行（coverage/一致率/CI），其 selective_risk、广义风险由 correct/error 直接计算（60/111=0.5405、141/399=0.3534），macro-F1 与 B11 行相同（B11 与 B12 共享同一预测与恒接受行为，见 `imcr_strong_RISK_COVERAGE_SUMMARY.csv` 两行 unique_score=1）。

| 方法×任务 | n | 接受数 | coverage | 一致率（选择性准确率） | 选择性风险 | 广义风险 | safe_coverage | macro-F1(接受/全分母) | 来源 |
|---|---|---|---|---|---|---|---|---|---|
| B12 entity_type | 276 | 41 | 0.1486 | **0.9268** | 0.0732 | 0.0109 | 0.1377 | 0.7306 / 0.2470 | GOAL13 |
| B12 relation_contract | 66 | 42 | 0.6364 | **0.0238** | 0.9762 | 0.6212 | 0.0152 | 0.0208 / 0.0202 | GOAL13 |
| B12 scope_adjustment | 111 | 111 | 1.0 | 0.4595 [0.3697,0.5520] | 0.5405 | 0.5405 | 0.4595 | 0.2099（同 B11 行） | WILSON |
| B12 identity_pair | 399 | 399 | 1.0 | 0.6466 [0.5985,0.6919] | 0.3534 | 0.3534 | 0.6466 | 0.3752（同 B11 行） | WILSON |
| B12 provenance_support | 394 | 394 | 1.0 | 0.3046 | 0.6954 | 0.6954 | 0.3046 | 0.1860 | GOAL13 |
| B3 entity_type | 276 | 250 | 0.9058 | **0.9880** | 0.0120 | 0.0109 | 0.8949 | 0.9274 / 0.8451 | GOAL13 |
| B3 relation_contract | 66 | 66 | 1.0 | 0.9394（含同模型票，见 §5） | 0.0606 | 0.0606 | 0.9394 | 0.9042 | GOAL13 |
| B3 scope_adjustment | 111 | 111 | 1.0 | 0.8108 | 0.1892 | 0.1892 | 0.8108 | 0.6672 | GOAL13 |
| B3 identity_pair | 399 | 399 | 1.0 | 0.9524 | 0.0476 | 0.0476 | 0.9524 | 0.6823 | GOAL13 |
| B3 provenance_support | 394 | 394 | 1.0 | 0.9365 | 0.0635 | 0.0635 | 0.9365 | 0.8822 | GOAL13 |

要点：B12 的广义风险（全分母错误暴露）在 relation 上高达 0.6212、provenance 0.6954——即生产框架在 strong 参考口径下把大量与独立参考不一致的断言放进发布层。这不是"事实错误率"，而是结构路由与独立 AI 共识的偏离度。

## 2. 风险–覆盖曲线与门槛如何塑造接受集（B 系列消融）

来源：`imcr_strong/imcr_strong_RISK_COVERAGE_SUMMARY.csv`（constrained_selective 主曲线行）。

| 方法×任务 | n_prediction_available | n_numeric_scored | score_coverage | unique scores | max_coverage | area_status |
|---|---|---|---|---|---|---|
| B12 entity_type | 276 | **41** | 0.1486 | 4 | 0.1486 | applicable（主曲线）；score-only 诊断 not_applicable_incomplete_score_coverage |
| B11 entity_type | 276 | 276 | 0.1486（gate 后） | 1 | 0.1486 | not_applicable_insufficient_discrete_points |
| B10 entity_type | 276 | 41 | 0.1486 | 4 | 0.1486 | not_applicable_incomplete_score_coverage |
| B12 relation_contract | 66 | 66 | 0.6364（gate 保留 42） | 4/3 | 0.6364 | 主曲线 insufficient_discrete_points；score-only applicable |
| B12 scope_adjustment | 111 | **0** | 0.0 | 0 | 0.0 | not_available_no_numeric_confidence |
| B12 identity_pair | 399 | **0** | 0.0 | 0 | 0.0 | not_available_no_numeric_confidence |
| B12 provenance_support | 394 | 394 | 1.0 | 4 | 1.0 | applicable |
| B3 全部任务 | 全覆盖 | 全覆盖 | 1.0（entity constrained 0.9058） | 11–20 | ≤1.0 | applicable |

**B 系列门槛对接受集的影响（解读）**：

1. **entity_type 的硬门截断**：B12 预测 382 条实体全部存在，但 328 条 `fallback_unresolved` 无置信度且 `hard_constraint_pass=0`（`IMCR_BASELINE_RUNS.csv` 实测），主曲线只允许 41 条进入接受集——这就是 B12 coverage=0.1486 的来源。管线"不虚构代理分数、不硬造曲线"的设计使 Full 的实体风险–覆盖曲线被硬门如实截短（`audit/04_BASELINE_DESIGN.md` §10）。
2. **B10（去结构门）与 B12 同点**：B10 = B12 预测全体 gate=1，但 entity 上可用分数仍只有 41 条，故 constrained 曲线与 B12 重合（SUMMARY 两行 score_coverage 同为 0.1486）——结构门与置信分数在该任务上部分冗余。
3. **B11（去弃权）退化为单点**：confidence 恒 1.0 → unique_score_count=1，曲线只有 coverage 单点（0.1486/0.6364/1.0），面积指标显式 not_applicable——"无弃权就没有选择性推断"被数据直接呈现。
4. **scope/identity 无逐条置信**：B12 在这两个任务上无任何数值置信（设计禁止虚构代理分数），面积指标 `not_available_no_numeric_confidence`，只报点指标；B3 用模型自报置信度获得完整曲线（scope AURC=0.2702、identity AURC=0.0089）。

## 3. AURC / AUGRC 及 95% CI（imcr_strong，applicable 曲线）

来源：`imcr_strong_RISK_COVERAGE_SUMMARY.csv`（aurc/augrc/aurc_bootstrap_ci95_low–high/augrc_bootstrap_ci95_low–high 列，2000 次固定种子 percentile bootstrap）。

| 方法×任务 | AURC [95% CI] | AUGRC [95% CI] |
|---|---|---|
| B3 entity_type | 0.00056 [0.00000, 0.00186] | 0.00048 [0.00000, 0.00157] |
| B12 entity_type（受限于 41 条接受集） | 0.00670 [0.00000, 0.01703] | 0.00074 [0.00000, 0.00198] |
| B3 relation_contract | 0.02265 [0.00070, 0.05722] | 0.01756 [0.00069, 0.04201] |
| B3 scope_adjustment | 0.27021 [0.16042, 0.38564] | 0.11497 [0.06885, 0.16444] |
| B3 identity_pair | 0.00886 [0.00345, 0.01605] | 0.00731 [0.00310, 0.01261] |
| B3 provenance_support | 0.01848 [0.00992, 0.02947] | 0.01499 [0.00843, 0.02279] |
| B12 provenance_support | **0.39365** [0.36500, 0.42449] | **0.34694** [0.32278, 0.37118] |

强模式主曲线有效面积 14 条 / 全部有效 24 条（`imcr_strong_RISK_COVERAGE_REPORT.md`）。B12 在 provenance 上的 AURC 是 B3 的约 21 倍（0.39365 vs 0.01848，区间不重叠）。

## 4. 三模式横向对比（B12/B3 一致率与 AURC 随参考集宽严的变化）

来源：三目录 SELECTIVE_GOAL13_METRICS.csv 与 RISK_COVERAGE_SUMMARY.csv。

**B12 Full framework 一致率**：

| 任务 | imcr_strong | imcr_all | leave_b_out |
|---|---|---|---|
| entity_type | 0.9268（41/276） | 0.8302（53/366） | 0.8958（48/309） |
| relation_contract | 0.0238（1/42） | 0.2087（82/393） | 0.4301（80/186） |
| scope_adjustment | 0.4595（51/111） | 0.3804（70/184） | 0.4338（59/136） |
| identity_pair | 0.6466（258/399） | 0.5870（344/586） | 0.6404（292/456） |
| provenance_support | 0.3046（120/394） | 0.2851（258/905） | 0.3116（153/491） |

**B3 盲 LLM 一致率**：

| 任务 | imcr_strong（含同模型票） | imcr_all | leave_b_out（主对照） |
|---|---|---|---|
| entity_type | 0.9880 | 0.9151 | 0.9234 |
| relation_contract | 0.9394 | 0.6268 | **0.2863** |
| scope_adjustment | 0.8108 | 0.7174 | 0.6985 |
| identity_pair | 0.9524 | 0.8703 | 0.8662 |
| provenance_support | 0.9365 | 0.7989 | 0.7984 |

**解读**：

（来源说明：本节两表 B12 的 scope/identity 格取自各模式 `*_RISK_COVERAGE_SUMMARY.csv` 对应 B11 行与 WILSON_CI_TABLE——B12 在 GOAL13 文件中缺该两格，因无逐条置信未产出指标行；B11 与 B12 预测与接受行为完全相同，数值一致。B12 scope imcr_all 的 0.3804 已由 `IMCR_BASELINE_RUNS.csv` × `IMCR_REFERENCE_ALL.csv` 联表独立复核为 70/184。）

- 参考集从 strong（3/3）放宽到 all（含 2/3 weak）后，所有方法一致率下降——weak 档纳入了更多 judge 分歧条目，评价更严苛；主口径结论以 strong 为准，all 作稳健性检查。
- B12 的 relation 数字从 0.024（strong）升到 0.43（leave_b_out）：这不是"框架变好"，而是参考标签构成变化（strong 参考中 changed 行 19/27 为 invalid，而生产端恒不预测 invalid；leave-B 参考中 context_only 占比大增，恰好命中生产端 contextual 路由）。跨模式比较必须连同 04A 号报告 κ=0.037 的低一致性一起陈述。
- B3 的 relation 0.939（strong）→0.286（leave_b_out）是同模型自证膨胀的量化（05 号报告 §6）；B3 的其余任务两口径差 0.07–0.14，膨胀幅度远小于 relation。

## 5. 配对 bootstrap：Full − 盲 LLM 面积差

来源：`experiments/14_statistical_tests/PAIRED_BOOTSTRAP_DELTAS.csv`（imcr_strong 口径）与 `leave_b_out/PAIRED_BOOTSTRAP_DELTAS.csv`。仅一个配对通过面积门（其余全部给出显式 not_applicable_* 状态，不静默丢弃）。

- **provenance_support，n=394，2000 replicates（seed=707394621）**：
  - ΔAURC(Full−B3) = **+0.3752 [0.3426, 0.4073]**（imcr_strong）；leave_b_out 口径 +0.3224 [0.2883, 0.3548]
  - ΔAUGRC(Full−B3) = **+0.3320 [0.3070, 0.3583]**（imcr_strong）；leave_b_out 口径 +0.2896 [0.2619, 0.3158]
  - 正号 = Full 的选择性风险面积显著**劣于**盲 LLM（区间不含 0）。
- relation_contract 在 leave_b_out 口径出现一对适用配对：ΔAURC = −0.3876 [−0.4871, −0.2864]（负号 = Full 面积小于 B3）——但该口径下 B3 的 relation 曲线本身就差（AURC=0.6494），且 relation 参考低一致（κ=0.037），此结果只作记录，不作为 Full 优势证据引用。
- 其余全部配对显式 `not_applicable_incomplete_score_coverage / no_numeric_confidence / insufficient_discrete_points`（DELTA CSV 状态列），与 13 号实验面积门一致。

## 6. ERA 回放等价性（旧实验未被动过）

`era_replay/ERA_REPLAY_PARITY_REPORT.json`：verdict=PASS，tolerance 1e-09，v2 全部 RISK_COVERAGE_POINTS 曲线逐格复算 0 mismatch（如 M1_rule_only|entity_type|constrained_selective 27 行 max_abs_diff=0.0）。旧 ERA 结果可在新管线中逐位复现，从而"旧实验保留 + 新证据升级"（GOAL §二十八）有机器校验背书。

## 7. 图件

- 图A `figures/imcr_risk_coverage.png/.pdf`（5 面板，2795 行曲线点，AUDIT PASS）
- 图B `figures/imcr_aurc_augrc_ci.png/.pdf`（provenance ΔAURC/ΔAUGRC 95% CI，与 14 号 DELTAS 交叉核对 max_abs_diff=0.000e+00，AUDIT PASS）
- 图C `figures/imcr_scope_validation.png/.pdf`（见 07 号报告）
- 图D `figures/imcr_relation_contract_validation.png/.pdf`（见 08 号报告）

## 8. 小结（论文 4.2/4.3 节要点）

1. 主口径下，Full framework 只在 entity_type 的极小接受集（41 条，coverage 0.1486）上达到 0.9268 一致率；其余任务全覆盖点一致率 0.024–0.647。
2. 盲 LLM 在全部任务型上一致率与风险面积均优于 Full；provenance 差距 ΔAURC=+0.375 [0.343, 0.407] 显著。
3. 结构门/弃权消融的结论是"数据不支持旧叙事"：去结构门（B10）未改变接受集（分数本身已截断），去弃权（B11）退化为单点无法评价面积。
4. 任何跨模式数字必须与参考集定义（strong 1246 / all 2593 / leave-B 1640 行）和 judge 一致性分级（04A）捆绑陈述。
