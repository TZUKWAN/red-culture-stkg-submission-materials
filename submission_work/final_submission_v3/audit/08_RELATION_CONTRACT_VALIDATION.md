# 08 — 关系契约（Relation Contract）changed-set 独立验证报告

> **证据等级声明**：本报告全部结论属于 **E 级（independent evaluation，独立评价）**。所有"一致"均指"与独立 AI 参考标签一致"。本报告的核心结论是**否定性的**：在独立 AI 参考下，关系契约组件的语义有效性**未获证明**，且该任务上 judge 一致性接近随机——这一诚实发现必须随任何相关数字一同进入论文（GOAL §二十七：不得美化不利结果）。

- 样本：`experiments/08_independent_reference/RELATION_CONTRACT_SAMPLE.csv`（640 行 = 320 changed + 320 matched control，`sample_role` 实测计数；抽样审计 `RELATION_CONTRACT_SAMPLE_AUDIT.json`）
- changed 全集来源：`experiments/10_structural_validation/RELATION_CONTRACT_CHANGED_SET.csv`（3412 行，`release_tier` 全为 contextual、`wo_tier` 全为 strict_semantic，实测）
- judge 可见信息限制：640 条中仅 3 条附带真实证据文本（协议 §5.2 明文），judge 可据此答 insufficient_evidence
- 图件：`figures/imcr_relation_contract_validation.png/.pdf`（GOAL §三十 图D，AUDIT PASS）

---

## 1. judge 一致性：κ=0.037 的诚实呈现

来源：`JUDGE_RELIABILITY_SUMMARY.csv`（relation_contract 行）、`JUDGE_PAIRWISE_AGREEMENT.csv`。

- Fleiss κ = **0.0368**，Krippendorff α (nominal) = 0.0373，平均两两一致率 0.3563；
- 两两 Cohen's κ：A–B 0.1756、A–C **0.0156**、B–C 0.1155；
- LOJO 标签稳定率：剔 A 0.3605 / 剔 B 0.4493 / 剔 C 0.4293；
- strong/weak/unresolved = 66/486/88（strong 仅占 10.3%）。

含义：**三 judge 对"该关系在严格语义契约下是否成立"没有形成超出随机水平的共识**。可能原因的分层讨论（任务信息不足 → 标签边界模糊 → 模型先验差异 → 真实语义歧义）见 `04A_IMCR_JUDGE_RELIABILITY.md` §5，此处不重复。直接约束：本任务上任何 accuracy 都只是"与一个低稳定参考的一致性"，证据强度低于其他任务型。

## 2. 参考标签构成（changed vs control）

来源：`IMCR_REFERENCE_STRONG.csv` / `IMCR_REFERENCE_ALL.csv` 中 relation_contract 行按 `sample_role`（经 `RELATION_CONTRACT_SAMPLE.csv` fact_id 映射）实测。

| 口径 | 角色 | n_labeled | invalid | context_only | insufficient_evidence | valid |
|---|---|---|---|---|---|---|
| strong | changed | 27 | 19 | 1 | 7 | 0 |
| strong | control | 39 | 17 | 5 | 17 | 0 |
| ALL | changed | 265 | 113 | 80 | 72 | 0 |
| ALL | control | 287 | 76 | 95 | 114 | 2 |
| leave-B-out | changed | 116 | 22 | 79 | 15 | 0 |

注意三点：(1) 三 judge 几乎从不判 `valid`（strong 中 0 条）——在无原文证据的条件下，没有一条 changed 关系被独立参考确认为"严格契约语义成立"；(2) strong 口径下 changed 行 19/27 判 `invalid`；(3) leave-B 参考的构成大幅右移到 `context_only`（79/116），口径敏感性极高。

## 3. B12（生产端路由）一致率 0.024 的含义

生产端把 3412 条 changed 断言全部路由到 contextual 层（映射 contextual→`context_only`），且**恒不预测 `invalid`**（无"判伪"标签，`audit/04_BASELINE_DESIGN.md` §4.2 披露）。主口径评价（`imcr_strong_SELECTIVE_GOAL13_METRICS.csv`）：

- B12 relation_contract：coverage 0.6364（结构门保留 42/66），一致率 **0.0238** [0.0042, 0.1232]（1/42，Wilson CI 来自 `WILSON_CI_TABLE.csv`）；
- 唯一正确条目为参考=context_only 且生产路由=context_only 的 1 条（`IMCR_BASELINE_RUNS.csv` × `IMCR_REFERENCE_STRONG.csv` 联表实测：(context_only→context_only, gate=1)=1）。

**含义（GOAL §十五 的明文约束）**：

1. 旧论文用 ERA 148 条"契约正例饱和子集"（Full 与 w/o 均 148/148，`ablation_experiment_summary.json` `discrimination_status=saturated_shared_proxy_subset`）暗示契约组件有效——该路径已被 GOAL 明文禁止。IMCR 的 640 条含真实 changed 行的设计下，组件的**语义收益没有被独立证据显示**：生产端"改后路由"（contextual）在 strong 参考下与参考一致率仅 0.0238。
2. 但同样**不能**据此说"契约有害"：changed 行的改前状态（strict_semantic→`valid` 映射）在 strong 参考下同样几乎不被支持（参考 valid=0 条）；即"改前/改后两种路由都得不到低一致性参考的支持"，真正可下的结论只有——**该任务上参考本身不成立（κ=0.037），组件有效性处于"未证明"状态**。
3. 3412 条契约违例的消除（`STRUCTURAL_REPLAY_AUDIT.json` `w/o Relation Contract.strict_contract_violations=3412`，v3 重放与 v2 逐位一致 match=true）是 B 级确定性结构事实，仍然成立；它说明契约在**结构上**阻止了主体—客体类型违例进入 strict 层，但**不能**外推为语义正确性收益。

## 4. changed vs control 分组一致率

来源：`IMCR_BASELINE_RUNS.csv` × 参考 CSV × `RELATION_CONTRACT_SAMPLE.csv` 联表（本轮实测）。

| 方法 | 口径 | changed | control |
|---|---|---|---|
| B12 | strong | 1/27 = 0.037 | 6/39 = 0.154 |
| B12 | ALL | 80/265 = 0.302 | 48/287 = 0.167 |
| B12 | leave-B-out | 79/116 = 0.681 | 7/132 = 0.053 |
| B3 | strong | 25/27 = 0.926 | 37/39 = 0.949 |
| B3 | leave-B-out | 29/116 = 0.250 | 42/132 = 0.318 |
| B1 | strong | 19/27 = 0.704 | 17/39 = 0.436 |

图D 采用 ALL 口径的 B12 changed=0.3019 / control=0.1672（`imcr_relation_contract_validation_AUDIT.json` `checks` detail，changed=265、control=287）。B12 在 leave-B-out 上 changed 高达 0.681 是参考构成位移的产物（context_only 在该口径占 79/116），不能解读为"契约路由对 changed 行有效"；B3 的 strong 口径 0.926/0.949 含同模型 Judge B 票（其 leave-B-out 口径跌至 0.25/0.32，见 05 号报告 §6）。

## 5. McNemar 检验（strong 口径，n=66）

来源：`14_statistical_tests/MCNEMAR_TESTS.csv`。

| 对比 | Full 胜:负 | 平 | p |
|---|---|---|---|
| Full vs B1 规则 | 7:36 | 23 | 8.96e-06 |
| Full vs B3 盲 LLM | 1:56 | 9 | 8.05e-16 |
| Full vs B4 | 7:0 | 59 | 0.0156 |

leave_b_out 口径（`leave_b_out/MCNEMAR_TESTS.csv`）：Full vs B1 = 85:40（p=7.03e-05）；Full vs B3 = 79:64（p=0.2416，不显著）。两组检验共同指向：**没有任何口径显示 Full 在关系契约上优于盲 LLM**；strong 口径下 Full 显著劣于 B1 与 B3。

## 6. 面积指标适用性

来源：`imcr_strong_RISK_COVERAGE_SUMMARY.csv`。B12 relation 主曲线（constrained，gate 后 42 条、3 个唯一分数）`not_applicable_insufficient_discrete_points`；B12/B3 配对 bootstrap 同状态（`PAIRED_BOOTSTRAP_DELTAS.csv`）。B3 主曲线 applicable（AURC 0.0226 [0.0007, 0.0572]）。论文不得在该任务上引用 Full 的 AURC/AUGRC。

## 7. 论文处置建议（4.5 节）

1. 保留结构层事实（B 级）：3412 条违例的确定性与 v2/v3 逐位一致。
2. 语义层如实写：640 条 changed+control 盲评中 judge κ=0.037（接近随机）、strong 参考下 0/66 条获得 valid 确认、生产改后路由一致率 0.024——**关系契约的语义有效性未获独立 AI 参考支持，该组件当前只能以"结构准入约束"定位，不得宣称"语义修正能力"**。
3. 附上信息不足的机制披露：judge 仅在 3/640 条上有原文证据；未来工作=证据增强后重评。
