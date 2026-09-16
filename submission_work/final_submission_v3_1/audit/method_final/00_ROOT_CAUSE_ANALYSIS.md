> [HISTORICAL 2026-09-16] 历史实验存档：本报告的数字属于**当时局部实验**，不是全库结论；最终权威数字见 AUTHORITATIVE_RESULTS.md。

# 00 — 根因分析（ROOT CAUSE ANALYSIS）

日期：2026-09-10 ｜ 范围：v3_1 今晚全部实证发现的方法学集成
每一结论的数字来源见括号内文件；所有实验为真实运行，无人工修正。

## 问题一：为什么"原方法"在独立参考下表现差？

三层原因，贡献度已被实验分离：

### R1 实验实现错误（已修复，修正后数字未变差）
- **阈值学习从未见过正确性标签**：`learn_threshold` 在 `fill_correct` 之前执行，
  utility 全程按 correct=0 计算，"优化"退化为满足覆盖下限的最小阈值。
  修复 + 回归测试：`tests/test_threshold_learning_uses_reference_correctness.py`（4 项）。
- **消融不纯**：S2 同时改变预测源与一致性加成；S3 的守卫与 S5 结构门重叠导致空消融。
  修复：单组件重构 + `changed_components` 字段 + `test_ablation_single_component_only.py`（11 项）。
- **S0 不是生产方法**：旧实现"规则存在即替换分类器"，而生产是 classifier-first。
  修复：`S0_production_faithful`（逐行对照 260 脚本，audit 01 §2）。

### R2 生产机制本身的保守性（真实特性，非 bug——但直接导致语义一致率低）
生产准入链（class gate + agreement + 守卫）在 382 个独立参考样本上只放行 **10 条
（2.6%）**（01_METHOD_IMPLEMENTATION_AUDIT.md §4）。放行的少数样本一致率也不高
（dev 0.267）——因为 classifier 的弱监督训练闭环（auto_accepted 弱标签 → 分类器学习
→ 与规则比较一致性 → 当作可信）只保证了内部自洽，从未接触外部语义检验。

### R3 语义判定的真实上限差距（不可通过调参消除）
在 IMCR strong 参考下，各类信号源的一致率天花板（dev，n=254）：
rule-only 0.389 / classifier 0.226 / rule-first 融合 0.32 / **盲 LLM 0.70-0.99**。
即：**本地规则+弱监督分类器的语义判定上限显著低于强 LLM 逐条判定**。
这不是实现错误（R1 已排除），是信号源能力差距。

## 问题二：R3 的正确响应不是"放弃框架"，而是结构化吸收 LLM 能力

Risk Estimator 实验证明路由可行（05_RISK_ESTIMATOR_REPORT.md）：
- 决策树 risk model（VAL AUPRC 0.728）能识别错误样本；
- 升级段（gpt-oss-20b 本地）一致率 **0.873/0.857**（DEV/VAL），同一困难段
  基线分类器仅 0.22-0.23；错→对翻转 99 例，对→错仅 2 例。

质量-预算曲线（07_QUALITY_BUDGET_REPORT.md）：**质量随预算近线性增长，
无内部 Pareto knee**（诚实发现）——不存在"20% 预算达到 100% 质量"的免费午餐。
预算曲线的端点：0% 预算=0.324（VAL），100%（every-item 强 LLM）=0.979。

## 问题三：结构性发现（非语义链路）

- **选择性闭包完胜固定闭包**：held-out 96.6% vs 25.7% agreement（McNemar p=5.7e-06），
  且结构违规恒 0（SCOPE_CLOSURE_REPORT.md）。生产规则把"事件地点→背景地点"系统性
  降格是主要损害源（该类 90 条 AFTER 胜率仅 11.9%）。
- **证据"缺失"大半是绑定丢失**：61,997 条无指针 strict 断言中 96.6% 可自动恢复证据
  定位（仅 2,106 条真正无支持）（EVIDENCE_RECOVERY_REPORT.md）——"55% strict 无证据"
  是指针管线缺陷，不是语料缺陷。
- **STKG 身份**：时间已参与事实身份（59,526 组多时段 s-p-o）；但空间语义层
  （政区层级/历史地名版本）完全缺失（12_STKG_MODEL_REPORT.md 判定 MISSING），
  是"时空"名号下最薄弱的一环。

## 根因→修复→残余 对照表

| 根因 | 修复 | 残余 |
|---|---|---|
| R1 实现错误 | P0-A/B/C 修复+测试 | 消融重跑（今晚完成） |
| R2 生产保守性 | Risk Estimator + 三路路由（accept/escalate/abstain） | 升级模型当日仅 20B 本地；27B 恢复后可换 |
| R3 信号上限 | 质量预算曲线如实报告 + Predictor 嵌入路线（B 胜出，VAL mF1 +9.7pt） | 弱监督标签空间（8 类 vs 参考 16 类）限制 macro-F1 上限 |
| 结构链缺陷 | Selective Closure（96.6% vs 25.7%） | mixed 类共识不足，保守 UNRESOLVED |
| 证据链缺陷 | Recovery 96.6% + Semantic Gate（分层验证中） | gate 验证完成前 strict 重分层不落地 |
| 空间语义层 | U6-U8 升级规格（12a，需政区沿革数据，今晚不做） | 空间层仍为 MISSING |
