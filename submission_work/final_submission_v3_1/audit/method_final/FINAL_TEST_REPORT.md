> [HISTORICAL 2026-09-16] 历史实验存档：本报告的数字属于**当时局部实验**，不是全库结论；最终权威数字见 AUTHORITATIVE_RESULTS.md。

# FINAL TEST REPORT — 方法冻结后唯一一次 TEST 正式评价（指令 §25）

日期：2026-09-11 ｜ 工作线：final_submission_v3_1 ｜ 评价脚本：`code/experiment_pipelines/run_frozen_test_eval.py`
输出目录：`experiments/02_selective_semantic/frozen_test/`

---

## 0. 单次运行声明

> **本表为方法冻结后唯一一次 TEST 评价，此前 TEST 未参与任何训练或调参。**
> 本运行（2026-09-11T01:21:32+00:00，wall 80.2 s）之后，不得再根据其结果修改任何方法组件。
>
> 此前全部训练/选型/阈值学习/升级调用路径均有显式 TEST 排除断言
> （`run_risk_routing.assert_no_test_samples` + `EscalationRunner` 的 `BLOCKED_TEST_SPLIT` 硬闸）；
> 冻结的 risk_routing/SUMMARY.json 记录 `guards.test_split_excluded=true`（test 排除 n=62）。
> 本脚本是唯一一次授权对 TEST 样本打分与升级的脚本：DEV/VAL 的升级决策全部只读复用既有缓存
> （96 条，不发新调用）；新调用只发生在 TEST 升级段。

---

## 1. 冻结声明（config hash + 各组件版本）

| 组件 | 冻结值 | 来源（冻结工件） |
|---|---|---|
| 消融配置 | `config_hash = 929c6a51430b85e3`（S0_production_faithful + DEV 学到 theta_c/theta + isotonic 校准） | `experiments/02_selective_semantic/ABLATION_SUMMARY_strong_test.json` |
| Risk Estimator | `DecisionTree_max_depth4`（DEV strong 标签拟合，n=166，seed=20260908；**VAL AUPRC = 0.7283**） | `risk_routing/RISK_MODEL_CARD.json` |
| tau_accept | `0.6666666666666666`（VAL 上按效用+coverage floor 学习，冻结阈值表） | `risk_routing/SUMMARY.json` → `tau_accept_by_budget["b030"]["val"]` |
| 操作预算 | b = 30%（升级预算上限；k = round-half-up(0.30·n)） | 指令 §25 |
| 三路路由语义 | ESCALATE = split 内 r_hat 最高前 k（并列按 (-r_hat, sample_id) 字典序）；AUTO_ACCEPT = 非升级且 clf_pred 存在且 r_hat ≤ tau_accept；ABSTAIN = 其余；clf_pred 缺失 → r_hat = 1.0（永不 AUTO_ACCEPT） | `run_risk_routing.py` 各预算点语义（import 复用，未修改） |
| 升级模型 | 本地 LM Studio `openai/gpt-oss-20b`，temperature=0；prompt `risk_routing.escalation.v1`（sha256 `2c67d6cd…ba804`） | `risk_routing/SUMMARY.json` escalation 段 |
| 切分 | book-grouped 冻结切分（dev 254 / val 66 / test 62） | `data/frozen_splits/SPLIT_MANIFEST.json`（sha256 已入 SUMMARY） |
| 质量参考（主口径） | leave-B-out（`IMCR_REFERENCE_LEAVE_B_OUT.csv`，judge_removed=B；strong 共识只作敏感性附注，禁止作为质量上限） | `FINAL_RISK_ROUTING_REPORT.md` 口径更正 |

**运行前核验（全部通过，写入 frozen_test/SUMMARY.json `verification`）**：

- 确定性重训 risk 模型：chosen 与 VAL AUPRC 与模型卡逐位一致（0.728264）；
- r_hat 复用核验：与既有 `ROUTING_RUNS_{dev,val}.csv` 逐样本比对 n=320，max|Δ| = 3.33e-07（≤1e-6）；
- 路由复现核验：DEV/VAL 在 b=30% 的路由计数（160/76/18 与 41/20/5）与冻结 `QUALITY_BUDGET_CURVE.csv` b030 行一致；
- 升级 prompt sha256 与冻结值逐位一致；DEV/VAL 升级决策 96 条全部来自只读缓存（95 OK + 1 条既有 ERROR 记录按政策回退基础预测）。

---

## 2. 消融 12 变体 TEST 表（reference = strong，config 929c6a51430b85e3）

重跑命令 `python run_selective_semantic.py --reference strong --split test`；输出已刷新
（`ABLATION_RUNS_strong_test.csv` / `ABLATION_SUMMARY_strong_test.json`），与冻结前逐位一致
（确定性复现，config hash 不变）。n = 62 TEST 样本（strong 参考标注 46）。

| 变体 | coverage | selective_accuracy | selective_risk |
|---|---|---|---|
| **S0_production_faithful（冻结生产配置）** | **0.0645** | **0.2500** | **0.7500** |
| S0_rule_first_legacy（对照） | 0.6452 | 0.5000 | 0.5000 |
| S1_wo_class_gate | 0.0323 | 0.0000 | 1.0000 |
| S2_wo_evidence_agreement | 0.4839 | 0.4000 | 0.6000 |
| S3_wo_contradiction_guard | 0.0645 | 0.2500 | 0.7500 |
| S4_wo_abstention | 0.0645 | 0.2500 | 0.7500 |
| S5_wo_structural_admission | 0.0645 | 0.2500 | 0.7500 |
| S6_rule_only | 0.2742 | 0.5294 | 0.4706 |
| S7_classifier_only | 0.9516 | 0.3220 | 0.6780 |
| S8_blind_llm_only | 1.0000 | 0.7097 | 0.2903 |
| S9_rule_plus_classifier | 1.0000 | 0.4355 | 0.5645 |
| S10_rule_plus_blind_llm | 1.0000 | 0.6452 | 0.3548 |

读法：S0 生产保真控制器以极低 coverage（4/62）换取保守发布；去掉任一守卫组件
（S1–S5 单变量消融）在 TEST 上要么进一步收缩 coverage（S1），要么不改变发布集（S3/S4/S5
的发布集与 S0 相同），单变量破坏在 n=62 上读不出改善。全量发布类基线（S7–S10）coverage=1，
selective_risk 即广义风险。TEST 数字仅作冻结确认，不据此改任何组件。

---

## 3. Risk Routing TEST 单次评价

### 3.1 路由与调用

- TEST n=62：**ESCALATE 19**（= 预算上限 round(0.30·62)；其中 15 条有 leave-B-out 参考）、
  AUTO_ACCEPT 41、ABSTAIN 2；派生升级带下界 tau_escalate = 0.84375（与 VAL 冻结值一致）。
- **真实升级调用 19 条（本地 LM Studio gpt-oss-20b）全部成功**：status=OK 19、decision_valid 19、
  无 ERROR，平均时延 7.23 s；留痕 `frozen_test/ESCALATION_CALLS_TEST.jsonl`
  （逐条 prompt/payload sha256，prompt sha 与冻结值一致）。
- 无效决策回退政策未触发（无回退行）；升级样本中 3 条无 base 预测（TEST 全部 3 条无
  clf_pred 样本都落入最高风险带），由升级直接给出发布预测。

### 3.2 DEV / VAL / TEST 三列对比（同口径：b=30% 三路路由 + leave-B-out 主参考）

| 指标 | DEV | VAL | **TEST** |
|---|---|---|---|
| n（全样本 / 有参考） | 254 / 207 | 66 / 54 | **62 / 48** |
| n（accept / escalate / abstain） | 160 / 76 / 18 | 41 / 20 / 5 | **41 / 19 / 2** |
| LLM 调用率 | 0.2992 | 0.3030 | **0.3065** |
| **coverage（发布/有参考）** | 0.9372 | 0.9259 | **0.9792** |
| **selective_accuracy** | 0.5103 | 0.4600 | **0.6170** |
| **selective_risk** | 0.4897 | 0.5400 | **0.3830** |
| generalized_risk | 0.4589 | 0.5000 | **0.3750** |
| AURC | 0.6045 | 0.7655 | **0.5914** |
| 升级段一致率（escalated∩labeled） | 0.7778（n=63） | 0.7333（n=15） | **0.8000（n=15）** |
| 接受段一致率（auto-accept∩labeled） | 0.3817 | 0.3429 | **0.5313** |
| 错→对（升级段） | 28 | 4 | **9** |
| 对→错（升级段） | 1 | 0 | **1** |

敏感性附注（strong 共识口径，含 Judge B，**禁止作为质量上限**）：
TEST selective_accuracy 0.6444、升级段一致率 0.8571（错→对 9 : 对→错 1）；DEV/VAL 相应为
0.5325/0.8269 与 0.4091/0.7000。

### 3.3 判读

1. TEST 与 DEV/VAL 同向且不劣于 DEV/VAL：升级段一致率 0.80（DEV 0.78 / VAL 0.73），
   翻转净为正（9:1），接受段一致率显著低于升级段（0.53 vs 0.80）——
   "高 r_hat → 升级换决策"的路由机制在未见数据上复现了 DEV/VAL 的方向。
2. TEST selective_risk（0.383）低于 DEV（0.490）/VAL（0.540），主因是 TEST 有参考子集
   （n=48）的错率基础更低、且 2 条高 r_hat 弃权样本未进入发布集；样本量小，不做过强声明。
3. 三个 split 的派生 tau_escalate 完全一致（0.84375），即 TEST 的 r_hat 分布头部与
   VAL 冻结阈值带吻合，无分布漂移迹象。

---

## 4. 产物清单（全部落盘）

| 文件 | 内容 |
|---|---|
| `experiments/02_selective_semantic/frozen_test/SUMMARY.json` | 冻结声明、核验、三列对比表、单次运行声明、输入 sha256 |
| `experiments/02_selective_semantic/frozen_test/ROUTING_RUNS_TEST.csv` | TEST 62 行逐样本路由与终判（LOB/strong 双正确列、升级决策、r_hat） |
| `experiments/02_selective_semantic/frozen_test/ROUTING_RUNS_DEVVAL_REEVAL.csv` | DEV/VAL 同口径重算逐样本行（审计用，升级决策全部只读缓存） |
| `experiments/02_selective_semantic/frozen_test/ESCALATION_CALLS_TEST.jsonl` | 19 条 TEST 真实调用留痕（prompt/payload sha256、时延、决策） |
| `experiments/02_selective_semantic/ABLATION_RUNS_strong_test.csv` / `ABLATION_SUMMARY_strong_test.json` | 消融 TEST 重跑刷新（与冻结前逐位一致） |
| `code/experiment_pipelines/run_frozen_test_eval.py` | 评价脚本（只 import 复用 `run_risk_routing` / `run_selective_semantic` / `lmstudio_provider`，未修改任何既有文件） |

---

## 5. 诚实边界

1. **样本量小（n=62，有 leave-B-out 参考 48 条；升级段有参考 15 条）**：单条样本约对应
   2 个百分点的一致率，任何 TEST 读数都只有方向性意义；本报告不做显著性检验、不计算
   置信区间（样本量不足以支撑），仅陈述点估计与符号。
2. 参考仍是 LLM-judge 共识（leave-B-out 去除与升级模型无族重叠的 Judge B），所有"一致率"
   读作"对去 B 共识的一致率"，不等于人工金标正确率；strong 口径数字只作敏感性附注。
3. 升级模型只有本地 gpt-oss-20b 单模型、temperature=0；更强升级模型会整体右移质量。
4. 操作预算 b=30% 由冻结指令给定（"预算 b=30% 内"）；冻结 SUMMARY 的 VAL knee 判读为
   b=0（强参考口径下的退化拐点），与本运行的操作点不同，报告如实并列、不以 TEST 结果
   追认任何预算选择。
5. TEST 消融表只用于冻结确认（重跑与冻结前逐位一致）；它不提供任何改方法的依据，
   按 §0 声明，本运行之后方法组件不得再改。
6. DEV/VAL 同口径数字为重算值（升级决策复用既有缓存，质量参考换为 leave-B-out），
   与旧 strong 口径的 QUALITY_BUDGET_CURVE 数字不可直接互比。
