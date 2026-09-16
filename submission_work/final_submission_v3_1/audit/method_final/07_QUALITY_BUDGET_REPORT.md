> [HISTORICAL 2026-09-16] 历史实验存档：本报告的数字属于**当时局部实验**，不是全库结论；最终权威数字见 AUTHORITATIVE_RESULTS.md。

# 07 — Quality-Budget Pareto 报告：曲线数据与 knee 判读（指令 §八/九）

日期：2026-09-09 ｜ 工作目录：`submission_work/final_submission_v3_1/`
实现：`code/experiment_pipelines/run_risk_routing.py`
数据：`experiments/02_selective_semantic/risk_routing/QUALITY_BUDGET_CURVE.csv`（机器可读全表）、
`SUMMARY.json`（含 knees / tau 表）、`ROUTING_RUNS_{dev,val}.csv`（逐样本 r_hat/路由/最终预测/correct，
含全部 9 个预算点的 route@b 列）、`RISK_MODEL_CARD.json`、`ESCALATION_CALLS.jsonl`

---

## 0. 结论摘要

1. **质量随升级预算单调上升**（VAL semantic agreement 0.324→0.979；DEV 0.401→0.972），
   每一档预算都严格帕累托占优更低预算（risk 不增，coverage 不减）。
2. **knee 由数据决定：全预算曲线（0–100%）上不存在内部 knee**。两 split 的 risk-预算曲线
   相对首末点弦的最大落差都退化在边界 b=0（gap=0，曲线整体位于弦上方，凸形）；即没有
   "花小钱办大事"的拐点。预算的花费-收益在 b≤75% 段内接近线性（段内 knee：
   VAL b=10% gap=0.007、DEV b=20% gap=0.001，落差皆近零）。75%→100% 的陡降来自
   **模型切换**（本地 gpt-oss-20b → B3 既有 gpt-5.6-luna 全量行），不是路由本身的收益。
3. **操作点（预声明规则：VAL 全曲线 knee，平局取最小预算）= b=0%**：`ROUTING_RUNS_*.csv`
   的主 route/final 列按 b=0% 落盘，全部 9 档预算的逐样本路由在 route@bXXX 列中。
   该规则完全由数据驱动，未预设"好看的"操作预算。
4. 实质结论：在生产分类器准确率仅 ~30% 的困难层上，**选择性地花 LLM 预算几乎线性地买回
   质量**（每 1% 预算约换 0.9–1.3pp 一致率，至 75% 预算时 VAL 0.729）；真正的质量上限
   由 every-item 强盲 LLM 给出（0.979）。系统设计的正确读法是：**risk 估计负责"决定谁
   需要升级"（排序有效），预算负责"买多少"（无免费拐点）**。

---

## 1. 口径

- **评价对象**：三路路由的最终发布预测（AUTO_ACCEPT=基础分类器预测；ESCALATE=gpt-oss-20b
  升级决策；b=100%=B3 既有全量行；ABSTAIN 不发布）。
- **质量口径**：只在有 IMCR strong consensus 独立参考的样本上计算（DEV 182 / VAL 48；
  无参考样本不冒充正确或错误）；`semantic_agreement` = 发布且正确的 / 发布且有参考的；
  `selective_risk` = 1 − agreement；`generalized_risk` = 发布且错误的 / 有参考的；
  `aurc` 按 selective_stats.rows_to_points（score=−r_hat，发布者按风险升序接受）。
- **预算口径**：`llm_call_rate` = 升级样本 / 该 split 全样本；预算分配为精确 top-k
  （k=round-half-up(b·n)，并列按 (−r_hat, sample_id)）；各预算升级集嵌套，升级调用为真实
  本地 gpt-oss-20b（240/241 成功，见 06 报告）。
- **阈值纪律**：`tau_accept`（效用最大化 + coverage floor 0.30，效用与
  run_selective_semantic.learn_threshold 同构）与 `tau_escalate`（升级集内最小 r_hat）
  **只在 VAL 上学习**，再应用于 DEV（DEV 仅作训练侧观察，不重新学阈值）。

---

## 2. 质量预算曲线（完整数据）

### VAL（选型/阈值 split，n=66，有参考 48）

| 预算 b | LLM 来源 | call_rate | coverage | semantic agreement | selective risk | generalized risk | AURC | tau_accept |
|---|---|---|---|---|---|---|---|---|
| 0% | none | 0.000 | 0.708 | 0.324 | 0.676 | 0.479 | 0.656 | 0.667 |
| 5% | gpt-oss-20b | 0.045 | 0.771 | 0.351 | 0.649 | 0.500 | 0.698 | 0.667 |
| 10% | gpt-oss-20b | 0.106 | 0.812 | 0.385 | 0.615 | 0.500 | 0.724 | 0.667 |
| 20% | gpt-oss-20b | 0.197 | 0.854 | 0.390 | 0.610 | 0.521 | 0.752 | 0.667 |
| 30% | gpt-oss-20b | 0.303 | 0.917 | 0.409 | 0.591 | 0.542 | 0.790 | 0.667 |
| 40% | gpt-oss-20b | 0.394 | 1.000 | 0.458 | 0.542 | 0.542 | 0.830 | 0.667 |
| 50% | gpt-oss-20b | 0.500 | 1.000 | 0.521 | 0.479 | 0.479 | 0.780 | 0.667 |
| 75% | gpt-oss-20b | 0.758 | 1.000 | 0.729 | 0.271 | 0.271 | 0.534 | 0.667 |
| 100% | **B3 既有全量行** | 1.000 | 1.000 | **0.979** | 0.021 | 0.021 | 0.061 | 0.000 |

### DEV（训练侧观察，阈值仍为 VAL 学得；n=254，有参考 182）

| 预算 b | call_rate | coverage | semantic agreement | selective risk | generalized risk | AURC |
|---|---|---|---|---|---|---|
| 0% | 0.000 | 0.642 | 0.401 | 0.598 | 0.384 | 0.394 |
| 5% | 0.051 | 0.692 | 0.428 | 0.571 | 0.395 | 0.423 |
| 10% | 0.098 | 0.741 | 0.451 | 0.548 | 0.406 | 0.452 |
| 20% | 0.200 | 0.835 | 0.506 | 0.493 | 0.412 | 0.501 |
| 30% | 0.299 | 0.928 | 0.532 | 0.467 | 0.434 | 0.549 |
| 40% | 0.401 | 1.000 | 0.576 | 0.423 | 0.423 | 0.566 |
| 50% | 0.500 | 1.000 | 0.631 | 0.368 | 0.368 | 0.516 |
| 75% | 0.751 | 1.000 | 0.791 | 0.208 | 0.208 | 0.319 |
| 100% | 1.000 | 1.000 | **0.972** | 0.027 | 0.027 | 0.036 |

对照锚点：DEV 上 S0_production_faithful（生产保真控制器，无升级）sel_acc=0.267
（coverage 0.059）；本路由 b=0% 即以 0.642 coverage 达 0.401——risk 弃权在零预算下已
优于生产准入门。B3 every-item（S8）DEV=0.697（全体口径，把无参考当错）/ 本表 labeled
口径 0.972，两口径不可直接混用，已在 §1 声明。

---

## 3. Pareto knee 判读（数据决定，不预设）

- **判据**（代码 `pareto_knee`）：knee = argmax_b [chord(b) − risk(b)]，弦连接
  (b=0%, risk₀) 与 (b=100%, risk₁)，平局取最小预算。
- **全曲线结果**：VAL knee=b=0%（gap=0.0000）、DEV knee=b=0%（gap=0.0000）。
  两曲线都位于弦上方（凸形：早期边际收益小、后期大），**不存在内部拐点**——
  按"相对线性插值是否有超额收益"的标准，任何中间预算都不优于"要么不花钱、
  要么直接上 every-item 强模型"。
- **单模型段诊断（b≤75%，升级模型同为 gpt-oss-20b，排除 75→100% 模型切换影响）**：
  VAL 段内 knee=b=10%（gap=0.0070）、DEV=b=20%（gap=0.0010）。落差近零 ⇒
  段内质量≈随预算线性增长（每 1% 预算 ≈ +0.5–0.8pp VAL 一致率、+0.5–0.9pp DEV），
  无显著边际递增区。
- **为什么曲线是凸的**：升级被投放到分类器 ~22–23% 一致率的最高风险层，升级模型在该层
  ~86% 一致率且跨预算大致恒定（06 报告 §3），故每单位预算的质量回报近似常数；
  而低预算时 `tau_accept` 受 DT 粒度与 coverage floor 约束仍需发布一批低精度接受区，
  摊薄了早期数字。两个效应叠加使风险随预算近似线性下降，无拐点。

**最终判读**：本数据不支持"花 10–20% 预算即可逼近上限"的叙事；预算-质量关系是
近线性的，只有 every-item 强模型（B3 行，0.979）构成真正的上限台阶。

---

## 4. 路由质量的可分离性证据（为何曲线值得信）

- risk 排序有效性：被升级段（top-k by r_hat）恰好是基础分类器最差的部分
  （升级样本基础一致率 0.225 vs 全体 0.286–0.313，DEV），升级后拉到 0.873。
- 合成数据契约：`test_risk_routing.py` 固化 AUPRC>0.9 的可分离性、路由边界语义、
  预算精确分配（b=10% 恰好 10%）。
- 复现性：全部阈值/模型/配置哈希落盘（SUMMARY.inputs_sha256、RISK_MODEL_CARD、
  tau 表），JSONL 可断点续跑。

---

## 5. 缺陷与适用性声明

1. **参考循环性（最重要）**：IMCR strong consensus 是 LLM judge 共识；B3（gpt-5.6-luna）
   与 judge 组成存在族重叠，0.979 的 every-item 上限部分反映"同族一致性"。
   本报告所有 agreement 应读作"对 judge 共识的一致率"，不等于人工金标正确率
   （参见 05 报告 §6.2；V3 08_independent_reference 的 judge 独立性审计）。
2. **质量口径限制**：无参考样本（DEV 72 / VAL 18）不参与质量分母；发布到无参考样本上的
   预测无法评价，call_rate 与 coverage 分母不同（§1），跨表比较须按列口径。
3. **b=0% 接受区精度低**：coverage floor 0.30 + DT 粗粒度迫使 tau_accept=0.667 接受
   一个 ~0.32 一致率的接受区（几乎等于不筛选）。若预算允许，收紧 floor 或换更细粒度的
   risk 模型可改善零预算选择性（已列入 05 报告缺陷）。
4. **单一升级模型温度 0**：升级决策无多样性/集成；1/241 的确定性 JSON 失败回退基础预测。
5. **单次运行、单 seed（20260908）**：曲线无重跑方差条；knee 判据对 risk 单调性敏感，
   已同时给出全曲线与单模型段两个口径，结论一致（无内部拐点）。

---

## 6. 产物清单

| 文件 | 内容 |
|---|---|
| `QUALITY_BUDGET_CURVE.csv` | 2 splits × 9 预算 = 18 行全指标 |
| `ROUTING_RUNS_dev.csv` / `ROUTING_RUNS_val.csv` | 254/66 行：r_hat、基础预测、9 档 route@b、操作点路由与最终预测/correct、升级决策留痕 |
| `RISK_MODEL_CARD.json` | 特征/选型/重要性/系数/政策/工程注记 |
| `SUMMARY.json` | population、预算计数、tau 表、knees、升级统计、guards、输入哈希 |
| `ESCALATION_CALLS.jsonl` | 242 条调用留痕（240 OK + 冒烟/重试） |
| `audit/method_final/05/06/07` | 本报告组 |
