# 项目内部审计：投稿材料包证据盘点与等级分类

- 审计对象：论文《选择性预测与结构准入协同的长江流域中共党史时空知识图谱构建》投稿材料整理包（本仓库根目录）
- 审计目的：为 Phase 2 独立多模型共识参考（IMCR）及 v3 新实验提供现有证据边界、证据等级与可复用实现清单
- 审计依据：`GOAL.md` 第一至第五节；本审计仅盘点既有文件，未修改任何已有文件，未运行任何模型
- 路径约定：以下所有相对路径均以本仓库根目录 `D:\REDCULTUREDATA\投稿材料_代码数据整理包` 为基准

---

## 1. 仓库结构总览与数据资产清单

### 1.1 顶层结构（`README.md` 第 9–19 行）

| 目录 | 内容 |
|---|---|
| `manuscript/` | 论文旧稿 docx、期刊投稿指南、8 篇范文参考（PDF/DOC） |
| `data/release_databases/` | 发布数据库：`red_culture_stkg_final_v2.sqlite`（约 1.19 GB，已核实为真实文件而非 LFS 指针）、`red_culture_stkg_semantic_v2.sqlite`（约 1.09 GB）、`stkg_v2_creative_media_enrichment.sqlite`（约 2 MB） |
| `data/graph_export/` | Neo4j 导出：`nodes.csv`（1,062,247 节点）、`relationships.csv`（2,984,015 关系），见 `metadata/CURRENT_RELEASE.json` |
| `data/source_data/` | `master_data.csv`、`stkg_v2_entity_classifier.joblib`、`stkg_v2_entity_classifier.sqlite` |
| `code/scripts/` | V2 构建脚本 255–294 号共 40 个（语义修复、Qwen 裁决、物化、导出、发布） |
| `code/tests/` | 40 个 pytest 测试文件 |
| `code/stkg_ui_v2/` | 中文检索界面（app.py + static） |
| `schema/` | `stkg_schema_v1.yaml`、`event_role_mapping_v1.yaml`、`culture_form_mapping_v1.yaml`、`evolution_rules_v1.yaml`、`competency_query_contract_v2.yaml`、`competency_questions_v2.md` |
| `queries/cq_v2/` | 26 个能力查询 SQL（cq01–cq26） |
| `documents/` | 文献分析、数据字典、研究报告、语义修复方案 4 份 |
| `audit/` | 全量审计 `stkg_v2_full_audit.md/.json`、能力查询、Neo4j 验证等 12 个证据文件 |
| `metadata/` | `CURRENT_RELEASE.json`、`release_manifest.json`、整理包文件清单（含 SHA-256） |
| `submission_work/final_submission/` | 第一轮投稿包（旧稿 + 未完全核验的审计记录） |
| `submission_work/final_submission_v2/` | 终稿 Word/PDF、8 幅图、4 组实验（02/03/05/07）、实验管线脚本、交叉核验记录 |

### 1.2 核心数据资产

- **最终图谱**：152,979 个规范实体、424,150 条整合断言、466,312 条来源关联、28,065 个 EventFrame、11,532 个 CultureState（`audit/stkg_v2_full_audit.md` 第 9–21 行；`documents/STKG_V2_FINAL_RESEARCH_REPORT.md` 第 4 节）。最终库 SHA-256：`a199d736b9ec436b3d5f244e874718604b6c84955a505f31f90a3e28c51a9ee7`（同两文件一致）。
- **ERA（集成参考标注）712 条**：`submission_work/final_submission_v2/experiments/05_ablation/FROZEN_EVALUATION_MANIFEST.json` 字段 `ai_gold.rows=712`，文件 SHA-256 `1190ed0d7a4ec16b34712293f47992d624788ba4734c2bfce4020d51de0a9c0f`；任务分布 entity_type 203 / event_role 101 / relation_semantic 148 / space_owner 15 / space_role 102 / time_owner 19 / time_role 124。**注意**：ERA 原始文件 `AI_GOLD_LABELS.csv` 不在本整理包内，其引用路径为包外绝对路径 `D:\REDCULTUREDATA\dual_paper_project\paper_A_method\04_results\AI_GOLD_LABELS.csv`（`submission_work/final_submission_v2/experiments/03_selective_inference/risk_coverage_audit.json` 的 `inputs.gold` 字段）；整理包内仅 `experiments/02_baselines/BASELINE_SPLIT_MANIFEST.csv`（712 行，含 `model_target` 即参考标签与 train/dev/test 划分：416/137/159）和 `BASELINE_RUNS.csv`（1,113 行，含 `gold_label` 列）携带标签信息。
- **历史缓存模型输出**：`llm_predictions.csv` 同样位于包外（`run_baseline_experiments.py` 第 39 行 `LLM_PATH`），整理包内只有其回放结果（`BASELINE_RUNS.csv` 中 M3 行）。

---

## 2. 现有实验/结果的证据等级分类表

等级定义（沿用 `GOAL.md` 第二节）：
- **A** = actual run（真实新鲜运行）
- **B** = deterministic replay（确定性重放）
- **C** = cached model output（缓存模型输出）
- **D** = shared-reference diagnostic（共享参考诊断，与生产信号共享通道）
- **E** = independent evaluation（独立评价）
- **F** = unavailable experiment（不可运行）

说明：A/B/C 是运行方式，D 是解释资格，二者正交；本表同时列出。全库范围内未发现任何 E 级证据（对 `experiments/` 下全部 json/csv 检索 `independent_evaluation` 无命中）。

| # | 实验/结果 | 文件位置 | 运行等级 | 共享通道标记 | 依据（字段/行） |
|---|---|---|---|---|---|
| 1 | M1 Rule-only（规则基线，7 任务 + 汇总） | `experiments/02_baselines/ACTUAL_RUN_BASELINE_METRICS.csv` | **A + D** | `overlap_status=shared_gold_rule_channel`；`primary_comparison_eligible=0` | `BASELINE_EXPERIMENT_REPORT.md` 第 13 行："current deterministic run, but it shares a rule channel with the AI gold; diagnostic only" |
| 2 | M2 Classifier-only（TF-IDF + 逻辑回归，held-out） | 同上 | **A**（唯一允许主比较的方法） | `comparison_tier=held-out supervised proxy benchmark`；`primary_comparison_eligible=1` | `BASELINE_EXPERIMENT_REPORT.md` 第 14 行："the target is still the current AI gold and is not label-independent factual evidence"——即 M2 仅是"针对 AI 参考标签的监督代理" |
| 3 | M3 cached LLM replay（LLM-only 缓存回放） | `experiments/02_baselines/REPLAY_AND_CACHED_BASELINE_METRICS.csv` | **C + D** | `evidence_class=cached_model_output`；`shared_gold_llm_channel` | `BASELINE_AVAILABILITY.csv` 第 5 行："the same predictions contributed directly to AI gold admission" |
| 4 | M4 Rule + cached LLM agreement | 同上 | **C + D** | `shared_gold_rule_and_llm_channels` | 同上文件；**论文摘要数字 0.7632/0.9914/0.0086 即来自该方法**（见第 4 节） |
| 5 | M3 live LLM-only | — | **F** | `not_available` | `BASELINE_AVAILABILITY.csv`："No live LLM inference was authorized or executed in this run"；`BASELINE_EXPERIMENT_REPORT.md` 第 8、19 行 |
| 6 | M5 无全局闭包配置 | — | **F** | `not_available` | `BASELINE_AVAILABILITY.csv` 第 7 行："No frozen per-sample outputs or runnable pre-closure harness exist" |
| 7 | M6 Full V2 framework（冻结回放） | `REPLAY_AND_CACHED_BASELINE_METRICS.csv` | **B + D** | `evidence_class=deterministic_replay`；`shared_system_signal` | `BASELINE_EXPERIMENT_REPORT.md` 第 16 行："deterministic frozen-output replay with shared system signals; listed separately from actual runs" |
| 8 | 选择性分类器消融（n=203，Full / 去类别门禁 / 去独立信号一致 / 去弃权） | `experiments/05_ablation/ablation_experiment_summary.json` → `classifier_actual_run`；`ABLATION_RUNS.csv` | **A + D** | `overlap_status=shared_proxy_reference` | 每个变体块的 `interpretation` 字段："AI ensemble reference shares source-type, lexical, contract, and/or historical model signals; report as proxy-reference consistency, not independent accuracy" |
| 9 | 关系契约参考子集消融（n=148，饱和） | 同上 → `relation_contract_actual_run` | **A + D（无辨别力）** | `discrimination_status=saturated_shared_proxy_subset` | 148 条 Full 与 w/o 均 148/148；`ablation_experiment_audit.json` truthfulness_notes："the 148 relation-reference rows are contract-positive by construction and cannot identify contract-removal harm" |
| 10 | role-owner 参考子集消融（n=260，不命中） | 同上 → `role_owner_actual_run` | **A + D（无辨别力）** | `facts_intersecting_208_scope_adjustments=0`；`discrimination_status=no_adjusted_fact_in_ai_reference_subset` | `ablation_experiment_audit.json` truthfulness_notes："the role-owner AI-reference subset intersects zero of the 208 release scope adjustments" |
| 11 | 全库结构消融（去风险路由 43,945 / 去身份投影 24,005 / 去关系契约 3,412 违例 / 去 role-owner 闭包 44+112 错误、208 变化 / 去全局闭包 27,475 / 去来源门禁 0） | `ablation_experiment_summary.json` → `structural_deterministic_replay` | **B** | 结构性指标，不涉参考标签 | `FROZEN_EVALUATION_MANIFEST.json` `evidence_contract`："deterministic_replay: component toggle over frozen saved ledgers"；审计 truthfulness_notes："structural results are deterministic replay, not independent accuracy and not online LLM inference" |
| 12 | 身份投影回放（154,150 → 152,979，减少 1,171） | 同上 → `identity_projection_replay` | **B** | — | 该块 `evidence_class` 字段明确为 `deterministic_replay` |
| 13 | 风险—覆盖曲线与 AURC/AUGRC（20 条有效曲线、10 条主约束曲线、2000 次固定种子 bootstrap） | `experiments/03_selective_inference/risk_coverage_summary.json`、`RISK_COVERAGE_REPORT.md` | 随方法而定（M1/M2 为 A，M6 为 B，缓存 LLM 无数值置信度不出面积） | 各曲线 `comparison_tier`/`overlap_status` 字段 | `RISK_COVERAGE_REPORT.md` 第 5–9 行：Curve rows 1750、valid areas 20、primary 10、bootstrap 2000×40000 行、Live LLM calls 0 |
| 14 | 端到端效率（5 档规模 × 5 次重复） | `experiments/07_efficiency/END_TO_END_SUMMARY.csv`、`ABLATION_EFFICIENCY_HANDOFF.md` | **A**（其中 `cached_model_output_replay` 阶段为 C） | 计时类证据，不涉标签 | `END_TO_END_SUMMARY.csv` 每行 `evidence_class` 列：多数 `actual_run`，cached 回放行为 `cached_model_output` |
| 15 | 26 个能力查询、全量结构审计 | `audit/stkg_v2_competency_queries.json`、`audit/stkg_v2_full_audit.md/.json` | **A（构建期历史运行，非本轮实验）** | 结构一致性证据 | `audit/stkg_v2_full_audit.md` 第 23–50 行全 PASS |
| 16 | E 级独立评价 | — | **E：不存在** | — | 全库无 `independent_evaluation` 标记；这正是 IMCR 要补的缺口 |

---

## 3. 现有证据边界分析

### 3.1 ERA 与生产信号的共享通道（原文证据）

- `GOAL.md` 第 129 行："ERA 的产生与规则、source type、lexical hint、schema vote、历史 Qwen 输出等生产信号存在不同程度共享。"
- `experiments/05_ablation/ablation_experiment_summary.json`（每个 actual-run 块的 `interpretation` 字段，亦重复于 `ABLATION_RUNS.csv` 每行 note）："AI ensemble reference shares source-type, lexical, contract, and/or historical model signals; report as proxy-reference consistency, not independent accuracy"。
- `experiments/02_baselines/BASELINE_EXPERIMENT_REPORT.md` 第 13–16 行分别声明：M1 与 AI gold 共享规则通道；M3/M4 为 "cached shared-gold-channel diagnostics; not independent accuracy evidence"；M6 为 "shared system signals"。
- `BASELINE_AVAILABILITY.csv` 给出逐方法的 `overlap_status`：`shared_gold_rule_channel`（M1）、`gold_supervised_disjoint_test`（M2）、`shared_gold_llm_channel`（M3 缓存）、`shared_gold_rule_and_llm_channels`（M4）、`shared_system_signal`（M6）。

### 3.2 关键事实的出处对照

| 事实 | 数值 | 出处文件与位置 |
|---|---|---|
| ERA 总规模 | 712 条 | `experiments/05_ablation/FROZEN_EVALUATION_MANIFEST.json` → `ai_gold.rows=712`；`experiments/02_baselines/BASELINE_EXPERIMENT_REPORT.md` 第 4 行 |
| 固定测试集 / 核心集 | 159 / 152 条 | `BASELINE_EXPERIMENT_REPORT.md` 第 5–7 行（split seed `paper-a-baseline-stratified-v1-20260730`；排除 4 条 time-owner + 3 条 space-owner 共享代理行）；`experiments/02_baselines/BASELINE_SPLIT_MANIFEST.csv`（712 行：train 416 / dev 137 / test 159，本审计实测统计） |
| 208 条时空作用域调整 | 208 | `ablation_experiment_summary.json` → `structural_deterministic_replay["w/o Role-owner Closure"].changed_vs_full=208`；`documents/STKG_V2_FINAL_RESEARCH_REPORT.md` 第 5.3 节（60 条时间闭合 + 44 条时间归属降级 + 120 条空间归属降级，部分同断言）；`audit/stkg_v2_full_audit.md` 第 12 行 `scope_adjustments: 208` |
| role-owner 消融非法 owner | 44 时间 + 112 空间 | `ablation_experiment_summary.json` → `w/o Role-owner Closure` 的 `invalid_time_owner_types=44`、`invalid_space_owner_types=112`；`experiments/07_efficiency/ABLATION_EFFICIENCY_HANDOFF.md` 消融结论段 |
| 260 个 role-owner AI 评价任务与 208 条交集为 0 | 260 / 0 | `ablation_experiment_summary.json` → `role_owner_actual_run.n=260`、`facts_intersecting_208_scope_adjustments=0`；`ablation_experiment_audit.json` truthfulness_notes 末条 |
| 3412 条 relation contract 违例 | 3,412 | `ablation_experiment_summary.json` → `w/o Relation Contract.strict_contract_violations=3412`、`changed_vs_full=3412` |
| 148 条饱和关系契约参考子集 | 148/148（两个变体同分） | `ablation_experiment_summary.json` → `relation_contract_actual_run.n=148`、`discrimination_status=saturated_shared_proxy_subset` |
| 身份投影变化 | 24,005 | `ablation_experiment_summary.json` → `w/o Identity Projection.changed_vs_full=24005`；另有 `identity_projection_replay`：154,150 源实体 → 152,979 规范实体，减少 1,171 |
| 全局闭包变化 | 27,475 | 同上 → `w/o Global Closure.changed_vs_full=27475` |
| 来源门禁变化 | 0（饱和 canary） | 同上 → `w/o Provenance Gate.changed_vs_full=0`；`ablation_experiment_audit.json` truthfulness_notes："provenance-gate effect can be null on a post-gate release where every assertion already has lineage" |
| 风险—覆盖实验规模 | 20 条有效曲线 / 10 条主约束曲线 / 2000 次 bootstrap | `experiments/03_selective_inference/RISK_COVERAGE_REPORT.md` 第 5–8 行；`risk_coverage_audit.json` → `applicable_area_curve_count=20`、`applicable_primary_constrained_curve_count=10`、`bootstrap_iterations_per_applicable_curve=2000`、`bootstrap_raw_row_count=40000`；AUGRC 闭式交叉校验最大差 5.551e-17 |
| 风险路由消融 | 43,945 条状态改变 | `ablation_experiment_summary.json` → `w/o Risk Routing.changed_vs_full=43945`；路由分布见 `risk_routing_replay`（deterministic_rule 295,097 / local_classifier_or_rule 85,107 / manual_review 60 / model_or_manual_review 43,886） |

---

## 4. 论文旧数字的出处定位

| 旧数字 | 出处（整理包内） | 对应 v2 证据 | 备注 |
|---|---|---|---|
| 0.7632 coverage | 旧稿 `manuscript/选择性预测与结构准入协同的时空知识图谱构建方法——以长江流域中共党史文献为例.docx`（出现 4 次）；终稿 `submission_work/final_submission_v2/...学术创新强化版.docx`（3 次，表述为"覆盖116条"）；`submission_work/final_submission/PAPER_RESULT_MAPPING.csv` 第 16、28 行（标 UNVERIFIED） | **恰等于 M4（规则+缓存 LLM）在 152 条核心集上的 coverage=0.763158**（`experiments/02_baselines/REPLAY_AND_CACHED_BASELINE_METRICS.csv` 与 `BASELINE_METRICS.csv` 的 M4 `__CORE_ELIGIBLE_TASKS__` 行：n_covered=116、n_correct=115） | 旧论文头条数字对应一个 **C+D 级**（缓存、共享通道）方法，不是 Full framework 的独立准确率 |
| 0.9914 agreement | 同上（旧稿 4 次、终稿 5 次）；`submission_work/final_submission/experiment_audit.md` 第 44 行 | 同上 M4 行 `accuracy_on_covered=0.991379` | 同上 |
| 0.0086 selective risk | 同上（旧稿 4 次、终稿 5 次） | 同上 M4 行 `selective_risk=0.008621` | 同上 |
| 712 条 ERA | 终稿 docx（1 次，"712条集成参考标注（ensemble reference annotations，ERA）"）；`FROZEN_EVALUATION_MANIFEST.json`；`BASELINE_EXPERIMENT_REPORT.md` 第 4 行；`ABLATION_EFFICIENCY_HANDOFF.md` | 见 3.2 表 | 旧稿 docx 中无 "ERA" 字样（实测检索 0 次），该术语系 v2 终稿引入 |
| 152 条评价集 | 两版 docx 均 8 次（"152条核心评价样本"）；`submission_work/final_submission/experiment_evidence_matrix.csv` EXP-03/EXP-04 行 | `BASELINE_EXPERIMENT_REPORT.md` 第 6 行；各 CSV 的 `__CORE_ELIGIBLE_TASKS__` 行 n_test=152 | — |
| 0.9934 / 0.8808 / 0.1192（Qwen 基线） | `submission_work/final_submission/experiment_audit.md` 第 194 行；`experiment_evidence_matrix.csv` EXP-03 行 | 恰等于 M3 cached LLM 核心集行：availability 0.993421、accuracy_on_covered 0.880795、selective_risk 0.119205（`REPLAY_AND_CACHED_BASELINE_METRICS.csv`） | 同为 C+D 级缓存证据 |
| 983 册文献 / 302,230 页 / 282,165 条候选 / 67,791 条本地证据 / 17,450 条 Qwen 裁决 | 仅出现于 `submission_work/final_submission/` 旧包审计文件（`manuscript_audit.md` 第 85–91、110 行全部标 UNVERIFIED；`FINAL_SUBMISSION_READINESS_REPORT.md` 第 135–139 行称目录/日志未提供）与 `GOAL.md` 第 248–252 行；v2 终稿正文沿用 983 册与 17,450 条（`FINAL_CHANGELOG.md`） | **v2 实验文件中无任何对应统计** | 属 Phase 1 必须补证据或降级表述的数字 |
| 全库规模 424,150 / 466,312 / 152,979 / 112,158 | `audit/stkg_v2_full_audit.md`；`documents/STKG_V2_FINAL_RESEARCH_REPORT.md` 第 4 节；`metadata/CURRENT_RELEASE.json` | 数据库可复核（文件真实存在且非 LFS 指针） | A 级历史运行产物 |

---

## 5. IMCR 新评价体系可复用的现有实现清单

所有脚本位于 `submission_work/final_submission_v2/code/experiment_pipelines/`（注意：脚本中输入路径均为包外绝对路径，复用时需改写路径适配层，见第 6 节风险）。

| 可复用单元 | 脚本与函数 | 用途 |
|---|---|---|
| 分层固定划分 | `run_baseline_experiments.py`：`build_split_manifest()`（第 213 行）、`stable_rank()`（209） | IMCR 评价集可按同一种子 `paper-a-baseline-stratified-v1-20260730` 复现 train/dev/test 划分，保证与旧实验样本级可比 |
| 任务特征与上下文解析 | 同上：`parse_context()`（185）、`feature_text()`（263）、`model_target()`（203）、`owner_side()`（192） | judge 任务构造时可复用样本字段组织方式 |
| 结构硬门槛 | 同上：`hard_constraint_pass()`（557）、`constraint_gate_source()`（617） | 独立评价下的 safe coverage 可沿用同一任务级硬约束定义，保持口径一致 |
| 指标计算 | 同上：`metric_row()`（679）、`macro_f1()`（638）、`clopper_pearson()`（661，Wilson 区间在消融脚本中另有使用） | 覆盖率/一致率/选择性风险/安全覆盖率计算直接复用 |
| 风险—覆盖曲线 | `run_selective_inference.py`：`curve_point()`（102）、`exact_curve()`（163，exact tie-grouped）、`trapezoid_area()`（190）、`failure_auroc()`（198）、`nearest_risk_at_coverage()`（206）、`max_coverage_at_risk()`（214）、`summarize_curve()`（223） | IMCR 上的选择性推断曲线与 AURC/AUGRC 可完全沿用（口径已写入 `risk_coverage_summary.json` 的 `definitions`） |
| 固定种子 bootstrap | 同上：`stable_bootstrap_seed()`（411，SHA-256 前 32 位派生每曲线种子，全局种子 20260730）、`bootstrap_area_rows()`（416，2000 次）、`percentile_interval()`（444，NumPy linear 分位数） | 统计检验的置信区间实现直接复用，种子方案可平行扩展到 IMCR（换种子字符串前缀即可） |
| 消融/结构回放框架 | `run_component_ablations.py`：`metric_rows()`（68）、`classifier_ablations()`（121）、`relation_contract_ablation()`（202）、`role_owner_ablation()`（303）、`owner_type_valid()`（411）、`structural_replay()`（436）、`identity_projection_replay()`（626） | 10/11/12 号新实验（结构、身份、谱系验证）可在同一确定性回放框架上加独立评价层 |
| 效率计时 | `run_end_to_end_efficiency.py`：`PeakMemoryMonitor`（93）、`timed()`（115）、`stable_digest()`（121）、五档缩放与各阶段函数 | 若需重测效率或新增 IMCR 构建耗时，可复用计时骨架 |
| 审计金丝雀模式 | `ablation_experiment_audit.json` 与 `risk_coverage_audit.json` 的 checks/canaries 结构；`FROZEN_EVALUATION_MANIFEST.json` 的 `protected_sources` 前后哈希对照 | v3 每个实验都应沿用"运行前后受保护文件 SHA-256 不变 + truthfulness_notes"的审计模板 |
| 图表契约 | `experiments/05_ablation/ABLATION_CHART_CONTRACT.md`、`03_selective_inference/RISK_COVERAGE_CHART_CONTRACT.json`、`07_efficiency/EFFICIENCY_CHART_CONTRACT.md` | 图件"可支持/不支持结论"先行声明的模式可直接套用到新图 |

---

## 6. 风险与注意事项

1. **包外依赖（最高优先级）**：v2 四个实验脚本均以 `SCRIPT.parents[4]`（即 `D:\REDCULTUREDATA`）为根，引用包外的 `dual_paper_project\paper_A_method\04_results\AI_GOLD_LABELS.csv`、`llm_predictions.csv`、`controlled_eval_samples.csv`，以及 `releases\red_culture_stkg_v2\` 和 `scripts\stkg_contract.py`、`scripts\stkg_v2_semantics.py`（`run_baseline_experiments.py` 第 36–66 行）。`stkg_contract.py` 与 `stkg_v2_semantics.py` **不在本整理包 `code/scripts/` 内**（该目录只有 255–294 号构建脚本）。因此：在整理包内直接重跑 v2 实验管线不可行；Phase 0 冻结时必须先把这些输入文件复制入包或建立只读挂载，否则所有"复现"声明不成立。
2. **头条数字的证据错位**：论文摘要的 0.7632/0.9914/0.0086 对应 M4（缓存规则+Qwen 一致性，C+D 级），而非 A 级新鲜运行或独立评价；按 `GOAL.md` 第 1538–1552 行，若保留必须写成"相对于 ERA 的一致性结果"。IMCR 完成后摘要应优先报告 IMCR 结果。
3. **两个"无辨别力"子集**：关系契约 148 条参考样本两个变体均 148/148（饱和）；role-owner 260 个任务与 208 条真实 scope adjustment 交集为 0。这两个子集**不能**用作相应组件有效性的证据；当前主证据是全库确定性回放（3,412 / 44+112 / 208）。IMCR 抽样设计若复用 ERA 样本，必须重新检验其对新结论的辨别力。
4. **计数口径不一致需澄清**：研究报告第 5.3 节把 208 条调整分解为 60（时间闭合）+44（时间归属降级）+120（空间归属降级，部分同断言），而消融回放报告非法 owner 为 44+112=156、断言级 changed=208。**120（研究报告）与 112（消融）不一致**，属"调整条目数 / 断言数 / 违例数"三种单位的混用风险；v3 论文引用前须以 `research_scope_adjustments` 表为准重新核对。
5. **去全局闭包是捆绑移除**：`ablation_experiment_audit.json` truthfulness_notes 明确指出 "global closure is a bundled removal and is not the sum of isolated component effects"（27,475 ≠ 3,412+24,005+208+…），论文不得把各组件变化数相加。
6. **来源门禁零差异是发布后饱和**：`w/o Provenance Gate` changed=0 仅说明发布库 424,150 条断言均已有 lineage（金丝雀性质），不能写成"来源门禁无作用"。谱系验证（12 号实验）需另设可辨别任务。
7. **旧包数字链未闭环**：983 册 / 302,230 页 / 282,165 条候选 / 67,791 条本地证据 / 17,450 条裁决在整理包内只有 UNVERIFIED 记录（`submission_work/final_submission/manuscript_audit.md` 第 110 行判定），v2 实验未提供任何佐证。Phase 1 的 `PAPER_CLAIM_EVIDENCE_MATRIX.csv` 必须对这五条给出结论。
8. **M2 主比较的局限**：M2 虽是唯一 `primary_comparison_eligible` 的方法，但其训练目标仍是 ERA（监督代理），在 IMCR 出现前不存在任何"标签独立"的比较基准；论文表 1 的 M1–M6 同框比较均受共享通道影响，需在正文显式声明。
9. **样本规模小**：固定测试集 159 条、核心集 152 条、owner 类任务仅 15/19 条（且已被排除出主比较）；20 条有效曲线中不少任务 n≤42。IMCR 评价集规模与功效分析必须先行，否则 bootstrap 区间将宽到无法支持结论（现有曲线已有实例：M1 space_role AURC 95% CI 为 [0.028, 0.287]）。
10. **术语纪律**：IMCR 不得称"金标准/ground truth"（`GOAL.md` 第 145–155 行）；终稿已统一为"集成参考标注（ERA）"，v3 新增表述须沿用"独立多模型共识参考"。
11. **Git LFS 与数据库只读**：两个发布库已确认为真实文件（非指针），但 Phase 0 仍须按 `GOAL.md` 第 221–238 行生成 `BASELINE_FREEZE_MANIFEST.json` 并逐文件核对 SHA-256（整理包 `metadata/整理包文件清单.csv/.json` 已有哈希可对照）。
12. **时间线一致性**：各实验产物时间戳为 2026-07-30（`ablation_experiment_summary.json`、`risk_coverage_summary.json` 等），交叉核验记录为 2026-09-05（`FINAL_CONTENT_CROSSREF_AUDIT.md`）；v3 新实验的时间戳体系应与冻结 manifest 关联，避免新旧批次混淆。

---

## 附：本审计的关键数字自查清单

| 数字 | 本审计引用位置 | 核实状态 |
|---|---|---|
| 712 ERA / 159 测试 / 152 核心 | §3.2 表 | 已核实（manifest json + 报告 + 实测 CSV 统计一致） |
| 208 scope adjustments | §3.2 表 | 已核实（消融 json + 研究报告 §5.3 + 全量审计三处一致） |
| 44 / 112 非法 owner | §3.2 表 | 已核实 |
| 260 任务零交集 | §3.2 表 | 已核实 |
| 3,412 契约违例 | §3.2 表 | 已核实 |
| 148 饱和子集 | §3.2 表 | 已核实 |
| 24,005 / 27,475 / 0 | §3.2 表 | 已核实 |
| 20 / 10 曲线、2000×40000 bootstrap | §3.2 表 | 已核实 |
| 0.7632 / 0.9914 / 0.0086 = M4 核心集 | §4 表 | 已核实（逐位对应 0.763158 / 0.991379 / 0.008621） |
| 0.9934 / 0.8808 / 0.1192 = M3 核心集 | §4 表 | 已核实（新增发现，逐位对应） |
| 983 / 302,230 / 282,165 / 67,791 / 17,450 | §4 表、§6-7 | 已定位出处，均 UNVERIFIED |
