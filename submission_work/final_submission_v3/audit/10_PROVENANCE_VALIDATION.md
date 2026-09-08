# 10 — 来源支持度（Provenance Support）独立验证与 Provenance Gate 定位报告

> **证据等级声明**：本报告全部结论属于 **E 级（independent evaluation，独立评价）**。所有"支持"均指"独立 AI 参考判断断言文本获得来源文本支持"，不等于历史事实为真（GOAL §二十七：只能写"来源支持率/发布安全不变量"，不得写"保证事实正确"）。

- 样本：`experiments/12_provenance_validation/PROVENANCE_SUPPORT_SAMPLE.csv`（1000 行）与 `PROVENANCE_SUPPORT_METADATA.csv`（1000 行）
- 参考集：`IMCR_REFERENCE_STRONG.csv` / `IMCR_REFERENCE_LEAVE_B_OUT.csv` 中 task_type=provenance_support 行
- judge 可见：断言文本 + **真实来源文本**（多段以 `---` 分隔拆为列表）+ 来源书名（协议 §5.5），本任务是五类中证据最充分的一类
- 评价输入：`IMCR_BASELINE_RUNS.csv`；配对检验：`14_statistical_tests/PAIRED_BOOTSTRAP_DELTAS.csv`、`MCNEMAR_TESTS.csv`
- 图件：图A/B 的 provenance 面板（`figures/imcr_risk_coverage.png`、`figures/imcr_aurc_augrc_ci.png`）

---

## 1. 三层样本构成

来源：`PROVENANCE_SUPPORT_METADATA.csv` 实测。

| research_tier | 条数 | semantic_status 构成 | risk_tier 构成 |
|---|---|---|---|
| strict_semantic | 400 | auto_accepted 400 | A 340 / B 37 / C 23（A/B 合计约 94%） |
| contextual | 300 | auto_accepted 300 | — |
| unresolved | 300 | model_review 299 / manual_review 1 | C 299 / D 1 |

provenance 行数：1 行 808、2 行 190、3 行 1、4 行 1（`n_provenance_rows` 实测）——所有抽样断言至少有 1 条谱系指针，即全部位于"发布门之后"。

## 2. 参考标签构成（strong 口径）

来源：`IMCR_REFERENCE_STRONG.csv`（provenance_support 行）实测。

fully_supported 134 / partially_supported 96 / unsupported 152 / contradicted 2 / insufficient_evidence 10（n=394）。

要点：**发布层（strict_semantic）断言中，独立参考判 unsupported 152 条、contradicted 2 条**——即"有谱系指针"不等于"来源文本实际支持断言"。这正是 GOAL §十一 要求做来源支持度实验的动因，也是旧证据链未覆盖的盲区。ALL 口径（n=905）：fully 286 / partially 307 / unsupported 267 / contradicted 18 / insufficient 27。

## 3. B12（生产端映射）与 B3（盲 LLM）一致率

来源：`imcr_strong/..._SELECTIVE_GOAL13_METRICS.csv`、`WILSON_CI_TABLE.csv`；分层联表为本轮实测。

| 口径 | B12 总体 | B12 strict | B12 contextual | B12 unresolved | B3 总体 |
|---|---|---|---|---|---|
| imcr_strong (n=394) | **0.3046** [0.2612, 0.3517]（120/394） | 78/178 = 0.438 | 38/117 = 0.325 | 4/99 = 0.040 | 0.9365 [0.9080, 0.9567]（369/394） |
| leave_b_out (n=491) | 0.3116（153/491） | 103/221 = 0.466 | 42/150 = 0.280 | 8/120 = 0.067 | 0.7984（392/491） |
| imcr_all (n=905) | 0.2851（258/905） | — | — | — | 0.7989（723/905） |

（B3 分层：strict 171/178=0.961、contextual 107/117=0.915、unresolved 91/99=0.919，strong 口径实测。）

**解读（分层）**：

1. 生产映射把 strict_semantic 映射为 `fully_supported`：在真实来源文本下，参考只有 78/178 支持"完全支持"——**strict 层的"严格语义准入"与"来源文本完全支持"是两个不同的概念**，前者无外部语义评价，后者才是本实验测的量。
2. 生产端恒不预测 `unsupported`/`contradicted`（`audit/04_BASELINE_DESIGN.md` §4.5 披露），而参考在 strong 口径下判 unsupported 152 条——这 152 条全部自动成为 B12 的错误，是 0.3046 的主要构成。
3. B3 的高一致率（0.9365）在本任务上是**最可信**的一组盲 LLM 数字：payload 含真实来源文本（不似 relation 只有 3 条证据）、leave-B 口径仍达 0.7984、judge 一致性中等（Fleiss κ=0.4207，`JUDGE_RELIABILITY_SUMMARY.csv`）。

## 4. 配对 bootstrap：Full 显著劣于盲 LLM（GOAL §十八 paired comparison）

来源：`14_statistical_tests/PAIRED_BOOTSTRAP_DELTAS.csv`（唯一 applicable 配对）、`PAIRED_BOOTSTRAP_REPLICATES.csv`（2000 行逐 replicate）。

- **ΔAURC(Full−B3) = +0.3752 [0.3426, 0.4073]**（n=394，2000 replicates，seed=707394621）
- **ΔAUGRC(Full−B3) = +0.3320 [0.3070, 0.3583]**
- 点值与 13 号实验交叉核对：Full AURC 0.39365 − B3 AURC 0.01848 = 0.37517（`imcr_strong_RISK_COVERAGE_SUMMARY.csv`；图B AUDIT `areas_crosscheck` max_abs_diff=0.000e+00）

正号且区间远离 0：**Full 框架在来源支持度任务上的选择性风险面积显著劣于盲 LLM**。McNemar 同向（`MCNEMAR_TESTS.csv`：Full 8:257 负于 B3，p=1.89e-65；Full vs B1 120:0 只反映规则基线无该组件）。leave_b_out 口径复核：ΔAURC=+0.3224 [0.2883, 0.3548]（`leave_b_out/PAIRED_BOOTSTRAP_DELTAS.csv`），结论不依赖含同模型票的主参考。

## 5. Provenance Gate 的定位：发布安全不变量（GOAL §十六）

GOAL §十六 要求 Provenance Gate"实事求是"。v3 用两个实验组合定位它：

**(1) 全库确定性回放：发布后零差异（金丝雀性质）**

来源：`STRUCTURAL_REPLAY_AUDIT.json`。v3 重放 `w/o Provenance Gate` 在 424,150 条断言上 changed_vs_full = **0**，与 v2 报告一致（`ERA_REPLAY_PARITY_REPORT.json` 同目录基准）。含义仅是：当前发布库中所有 strict 断言均已带谱系（门后饱和），**不能**写成"来源门禁无作用"。

**(2) 故障注入压力测试：100% 拦截（负控实验）**

来源：`PROVENANCE_GATE_STRESS_SUMMARY.json`（`PROVENANCE_GATE_STRESS_TEST.csv/.md`、`PROVENANCE_GATE_FAULT_INJECTION.csv`）。实验性质声明为"synthetic failure-injection stress test / negative-control，不构成真实数据上的性能声明"（json `experiment_nature`）：

| 注入比例 | 注入数（strict 112,158 中删除 provenance 引用） | 被拦落数 | block_rate | 对照组误伤 |
|---|---|---|---|---|
| 1% | 1,122 | 1,122 | 1.0 | 0（n=423,028） |
| 5% | 5,608 | 5,608 | 1.0 | 0（n=418,542） |
| 20% | 22,432 | 22,432 | 1.0 | 0（n=401,718） |

被注入断言状态转移 strict_semantic → contextual（降层而非删除），基线三层数（112,158 / 268,047 / 43,945）与发布库逐位一致（`baseline_match=true`），三项 verification_asserts 全 true。

**论文定位结论**：Provenance Gate 应表述为"**发布安全不变量**"——在正常数据上不可观察（changed=0 的饱和性），但在故障注入下以 100% 拦截率、0 误伤保持发布层不含无谱系断言；其价值是防御性的，而非质量提升性的。不得声称"来源门禁提升了事实正确率"。

## 6. 论文处置建议（4.7 节）

1. 主数字换成 IMCR 口径：strong 参考 n=394，B12 一致率 0.3046 [0.2612, 0.3517]，B3 0.9365；ΔAURC +0.375 [0.343, 0.407]——**旧论文无此口径的任何数字**。
2. 必须披露：strict 层 178 条可评价断言中仅 0.438 获"完全支持"评价、152 条被参考判 unsupported；建议论文把"strict_semantic"更名为/解释为"结构准入层"，避免读者将其等同于"来源完全支持层"。
3. Provenance Gate 按 §5 的"发布安全不变量"定位书写，两个实验（0 差异回放 + 故障注入 100% 拦截）并列引用。
