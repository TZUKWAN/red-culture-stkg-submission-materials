# 05 — Risk Estimator 报告：特征、选型、重要性（指令 §五/六）

日期：2026-09-09 ｜ 工作目录：`submission_work/final_submission_v3_1/`
实现：`code/experiment_pipelines/run_risk_routing.py`
输出：`experiments/02_selective_semantic/risk_routing/RISK_MODEL_CARD.json`（本报告机器可读版）、
`ROUTING_RUNS_{dev,val}.csv`、`QUALITY_BUDGET_CURVE.csv`、`SUMMARY.json`、`ESCALATION_CALLS.jsonl`
测试：`code/tests/test_risk_routing.py`（9 项断言全部通过）

---

## 0. 结论摘要

1. **任务**：对 entity_type 382 规范实体的生产预测（B2 冻结分类器，生产机制预测源恒为分类器）
   估计错误风险 `r_hat = P(clf_pred wrong | features)`，供三路路由（AUTO_ACCEPT / ESCALATE /
   ABSTAIN）使用。
2. **标签来源（唯一）**：IMCR 独立参考 `IMCR_REFERENCE_STRONG.csv`（strong consensus）的
   entity_type 行；`wrong = 1 ⟺ clf_pred ≠ reference_label`。**未使用**任何 weak
   auto_accepted 标签（硬约束，代码内显式声明 + SUMMARY.guards 固化）。
3. **拟合纪律**：只在 DEV 拟合（n=166：DEV 254 中有独立参考且有分类器候选者）；选型与阈值
   只用 VAL；TEST 62 样本被 `assert_no_test_samples` 显式过滤并在训练/打分/升级全部路径断言。
4. **选型结果**：DecisionTree(max_depth=4)（VAL AUPRC=0.728）击败 LogisticRegression（0.652）
   与 CalibratedLR-sigmoid（0.650）；选型规则为"VAL AUPRC 达到 best−0.01 的最简单候选"，
   LR 因低于容差出局。
5. **特征重要性 top5（选中模型）**：`clf_conf`（0.264）> `entropy_margin_approx`（0.199）>
   `pred_Concept`（0.184）> `pred_Document`（0.147）> `rule_clf_agreement`（0.114）——
   分类器自身置信与间隔主导，其次是被预测类别（类别级错误率差异大）与规则-分类器一致性。
6. **工程发现（重要）**：sklearn 1.8.0 的 `CalibratedClassifierCV` 在本数据配置下输出与底层
   LR 概率**完全反序**（spearman=−1.000，训练集低风险区正确率 0.102 < 随机水平），已定位到
   其 `predict_proba` 路径经 `_get_response_values(response_method=["decision_function",
   "predict_proba"])` 优先取 decision_function、与校准器拟合尺度不相容。为保证候选模型可审计，
   CalibratedLR(sigmoid) 按 Platt (1999) 原义显式实现（5 折集成 + 折叠外两参 sigmoid），
   行为由测试固化（与 LR 秩相关 +0.96）。干净合成数据上 sklearn 原实现行为正常，
   说明这是配置级不相容而非普适 bug，但本仓库一律使用显式实现。

---

## 1. 数据与标签

| 项 | 值 |
|---|---|
| 信号帧 | `run_selective_semantic.build_signal_frame()`（import 复用，未修改）：382 样本，B1 规则 / B2 分类器 / B7 margin / B3=gpt-5.6-luna 盲 LLM 信号齐备 |
| 独立参考 | `V3/experiments/08_independent_reference/IMCR_REFERENCE_STRONG.csv`（strong consensus，覆盖 276/382：DEV 182 / VAL 48 / TEST 46） |
| 训练集（DEV） | 有参考且有 clf_pred：**166 行**；wrong 率 **0.687**（生产分类器在该层准确率仅 31%） |
| 选型集（VAL） | 有参考且有 clf_pred：**43 行**；wrong 率 0.698 |
| 弃用 | 无参考样本（不参与训练/质量评价）、clf_pred 缺失样本（DEV 24 / VAL 8：路由政策 r_hat=1.0，永不 AUTO_ACCEPT）、全部 TEST 样本 |

---

## 2. 特征清单（29 维）

连续/二值 10 维 + 被预测类别 onehot 19 维（类别域 = `stkg_v2_semantics.TYPE_FAMILY` 键 + OTHER）：

| 特征 | 定义 |
|---|---|
| `clf_conf` | B2 冻结分类器置信 |
| `clf_margin` | B7 top1−top2 概率间隔 |
| `entropy_margin_approx` | 由 margin 近似的归一化熵 H₂(0.5+clip(margin,0,1)/2)（margin∈(0,1)，指令允许 margin 近似） |
| `rule_conf` | B1 规则置信（缺失→0） |
| `rule_clf_agreement` | rule_pred == clf_pred（均存在） |
| `rule_hit` | 规则给出候选 |
| `lexical_contradiction` | `stkg_v2_semantics.entity_model_contraindication(name, primary_source_type, clf_pred)` 非空（生产硬约束门信号，实时重算） |
| `type_family_member` | clf_pred ∈ TYPE_FAMILY |
| `validated` | sampling_metadata.type_validation_status == validated |
| `source_multiplicity` | integrated_member_count（成员数） |
| `pred_<Class>` ×19 | clf_pred 类别 onehot |

---

## 3. 候选模型与选型（VAL AUPRC，偏好最简单）

| 候选 | DEV AUPRC | VAL AUPRC | 说明 |
|---|---|---|---|
| LogisticRegression（标准化 + L2） | 0.890 | 0.652 | 最简单；VAL 首选未达容差 |
| **DecisionTree(max_depth=4)** | 0.816 | **0.728** | **选中**（VAL 最佳；简单性序中 LR 出局后首个达标者） |
| CalibratedLR(sigmoid)（显式 EnsemblePlattLR） | — | 0.650 | 与 LR 排序几乎一致（校准不改排序），AUPRC 天然贴近 LR |

选型规则（代码常量 `SIMPLICITY_ORDER` / `AUPRC_TOLERANCE=0.01`）：按简单性序
LR → DT(4) → CalibratedLR，取第一个 VAL AUPRC ≥ best−0.01 的候选。
本例 best=0.728（DT），LR 0.652 < 0.718 出局，DT 即 best 被选中。

> 注：AUPRC 为排序型指标，秩保持的校准不改变其值，故"正确实现的 CalibratedLR"在
> AUPRC 上只能贴近 LR；这是该候选仅作校准对照、不预期超越 LR 的结构性原因。

---

## 4. 特征重要性（选中模型 DecisionTree max_depth=4，importance 归一和=1）

| 排名 | 特征 | importance |
|---|---|---|
| 1 | `clf_conf` | 0.264 |
| 2 | `entropy_margin_approx` | 0.199 |
| 3 | `pred_Concept` | 0.184 |
| 4 | `pred_Document` | 0.147 |
| 5 | `rule_clf_agreement` | 0.114 |

判读：分类器自身不确定性（置信、间隔熵）是首要风险信号；其后是类别级错误率
（Concept 类预测错误率极高、Document 类预测基本可靠——onehot 承担了类别条件风险），
规则-分类器一致性提供独立佐证。完整表见 `RISK_MODEL_CARD.json`
（`feature_importance_tree` / `feature_importance_top5`；LR/CalibratedLR 路径另有
标准化系数全表）。

---

## 5. 行为质量（与路由的衔接）

- 合成数据契约测试：三个候选在可分离合成集上留出 AUPRC 全部 > 0.9（`test_risk_routing.py`）。
- 真实数据：VAL 上 DT 的 r_hat 离散层级少（0 / 0.667 / 1.0 等少数叶值），路由精度受
  叶粒度限制（见 §6 缺陷）；但 top-k 升级排序在预算曲线上有效——真实升级将 DEV 高风险段
  正确率从 0.225 拉到 0.873（见 06 报告）。

---

## 6. 缺陷与局限（如实声明）

1. **训练规模小**：n=166、wrong 率 0.687，正类（wrong）占多；AUPRC 随机基线=0.687，
   LR/CalibratedLR 的 VAL AUPRC 仅勉强高于基线，VAL AUPRC 差异（43 行）处于噪声量级。
2. **参考的循环性**：IMCR strong consensus 由 LLM judge 投票构成；"risk 真值"与 B3/B3 族
   模型（用于 b=100% 对照）存在模型族重叠风险，绝对数字应理解为"对 judge 共识的一致率"
   而非人工金标正确率（见 07 报告 §5）。
3. **DT 叶粒度粗**：max_depth=4 + onehot 主导使 r_hat 只有少数离散值，`tau_accept` 无法
   精细分离低风险区；b=0% 时 VAL coverage floor（0.30，沿用 run_selective_semantic 口径）
   强制接受一个正确率仅 ~0.32 的接受区（vs 全体 0.30）。
4. **熵为 margin 的单调近似**：与 clf_margin 信息冗余（单调反演），仅按指令列入并命名
   `entropy_margin_approx`，不引入独立信息。
5. **单次运行**：sklearn 随机性已由 seed=20260908 固定，结果可复现，但无多次重跑方差；
   报告不附置信区间。

---

## 7. 硬约束落实核查

| 约束 | 落实 |
|---|---|
| TEST 不进入训练/选阈值/打分/升级 | `assert_no_test_samples` 在 main 训练前、`EscalationRunner.ensure` 内双重断言；SUMMARY.guards 记录排除数（62） |
| risk 标签只来自独立参考 | 标签构造唯一入口 `int(frame[s]["clf_pred"] != reference[s])`，reference 仅 `load_reference("strong")` |
| 禁止 weak auto_accepted 标签做 risk 真值 | 未读取任何 auto_accepted 信号；SUMMARY.guards.weak_auto_accepted_labels_used=false |
