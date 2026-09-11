# FINAL METHOD SUMMARY — 选择性预测 + 结构准入 + 时空知识组织 最终方法

日期：2026-09-10 ｜ 工作线：final_submission_v3_1 ｜ 状态：方法定型中（证据门统计与 Judge C 尾部收敛后冻结 TEST）

---

## 一、最终方法是什么

```
候选知识（实体/关系/事件/时间/空间）
        ↓
Local Semantic Predictor（嵌入路线：nomic-embed + LogisticRegression）
        ↓
Externally Calibrated Risk Estimator（决策树 depth-4，独立 DEV 参考训练）
        ↓
┌──────────────┬──────────────────────┬────────────┐
│ AUTO_ACCEPT  │ ESCALATE(gpt-oss-20b │  ABSTAIN   │
│ r ≤ τ_accept │ 本地 LM Studio)      │ r > τ_esc  │
└──────────────┴──────────────────────┴────────────┘
        ↓
Stable Semantic Decision
        ↓
Identity Projection → Relation Contract（纯结构约束）
→ Selective Spatiotemporal Closure（按变换类型 RETAIN/REWRITE/UNRESOLVED）
→ Evidence Recovery + Evidence Semantic Gate
→ Global Structural Admission
        ↓
STRICT / CONTEXTUAL / UNRESOLVED → EventFrame → CultureState → Evolution
```

与旧方法的本质区别：旧方法 = 弱监督标签 → 分类器 → 与规则自比 → 内部自洽当可信。
新方法 = **预测与风险分离**（Risk Estimator 只用独立参考训练）、**强模型只花在中风险带**、
**固定启发式改写 → 选择性改写**（数据学出的 type→action 表）、**证据指针 → 语义支持门**。

## 二、为什么旧方法效果差

三层根因（00_ROOT_CAUSE_ANALYSIS.md）：
1. **实验实现错误**（阈值学习用 correct=0、消融多组件混变、S0 非生产逻辑）——已修复；
2. **生产准入链极端保守**：独立参考下 382 样本只放行 10 条（2.6%），放行部分一致率也不高
   （弱监督闭环=内部自洽，从未接触外部检验）；
3. **信号能力天花板**：本地规则+弱监督分类器的逐条语义判定上限 0.23-0.39，
   强 LLM 逐条 0.70-0.99——差距真实存在，不是调参能消除的。

## 三、今晚改了什么

P0-A/B/C 三个实现错误修复（回归测试 4+11 项）；新增 Risk Estimator + 三路路由 +
质量预算曲线；选择性闭包（替代固定改写）；证据恢复管线（96.6% 恢复率）+ 证据语义门
（分层验证运行中）；预测器嵌入路线（VAL macro-F1 +9.7pt）；STKG 七项身份审计与
U1-U10 升级规格；LM Studio 生产链（gpt-oss-20b，零公网依赖）。

## 四、最终核心实验结果（entity_type，IMCR strong 参考）

| 方法 | coverage | selective accuracy |
|---|---|---|
| Rule-only | 0.283 | 0.389 |
| Frozen classifier | 0.906 | 0.226 |
| S0_production_faithful（生产忠实） | 0.059 | 0.267 |
| **Blind LLM (gpt-5.6-luna, every-item)** | **1.000** | **0.697** |
| Risk routing 0% 预算 | 0.71* | 0.324 |
| Risk routing + 10% 升级 | — | 0.385 |
| Risk routing + 75% 升级 | — | 0.729 |

（*VAL 口径；升级段自身一致率 0.873/0.857，错→对翻转 99 例 vs 对→错 2 例）

## 五、与 every-item 强 LLM 相比

- 100% 预算 = 0.979（B3 gpt-5.6-luna 全量）——方法在满预算下等价于 every-item LLM；
- **50% 预算即达 0.521，75% 达 0.729**；质量随预算近线性增长，
  **无内部 Pareto knee**（诚实发现：不存在"20% 预算≈满预算"的免费午餐）；
- 框架的不可替代部分：结构违规恒 0、逐条可追溯、选择性闭包 held-out 96.6% vs 25.7%、
  证据恢复 96.6%、规模化（42 万断言 vs LLM 每条一次调用）。

## 六、最优预算

由数据决定：**质量随预算线性，knee 退化为端点**。预算选择变成纯成本-质量权衡：
每 10% 预算换约 3-6 个点一致率（DEV/VAL）。若目标是"接近 every-item 质量"，
预算需 ≥75%；若目标是"结构安全下最大化质量/成本比"，预算由应用方按单条裁决成本定价。
论文不应宣称存在免费拐点。

## 七、各组件是否有效

| 组件 | 判定 | 证据 |
|---|---|---|
| Risk Estimator（独立参考训练） | ✅ 有效 | AUPRC 0.728；升级段翻转 99:2 |
| Selective Escalation（本地 20B） | ✅ 有效 | 升级段 0.87 vs 基线 0.22 |
| Abstention | ✅ 有效 | 去弃权后 risk 0.68→0.71 且覆盖含大量错误 |
| Evidence agreement（生产式合取） | ⚠️ 有效但极保守 | 去掉后 acc 0.32→0.26；但生产门本身只放行 2.6% |
| Contradiction guard / 结构门 | ⚠️ 与阈值冗余（诚实发现） | S3/S5 ≡ S0（守卫只在低分区触发） |
| 规则优先融合（旧 S0） | ❌ 非生产、非最优 | 生产是 classifier-first；rule-first 是双重发明 |
| Selective Closure | ✅ 大幅有效 | held-out 96.6% vs 25.7%（p=5.7e-06） |
| Relation Contract 作为语义证据 | ❌ 越界（旧用法废除） | 只做结构约束；语义支持归 Evidence Gate |

## 八、strict 层最终质量 + identity/relation/scope 独立验证（全部完成）

**证据语义门（5,000 条分层验证，本地 20B）**：词法对齐层支持率 56.1%、
同行双名强恢复层 70.4%、弱定位层 14.8%、词法不匹配层 2.3%。
**NEW STRICT ≈ 35,226 条 [33,744–36,708]**（旧 112,158 → 收缩 69%，
但每条都带经验证的语义支持；Support–Coverage 详见 09_EVIDENCE_GATE_REPORT.md）。

**三项结构组件的独立三 judge 验证（v4，全部带真实证据）**：
- relation_semantic（800=400改写+400对照）：strong 457（71.4%），κ=0.543
  （无证据时代 0.037 → 证明旧低κ是任务缺证据，非 judge 无能）；
  **changed 58.8% vs control 67.8% 支持率（p≈0.04）**——契约改写集中在线边界
  模糊断言，语义收益主张不成立，Relation Contract 定位收缩为纯结构约束；
- scope（208 全量带原文）：strong 110，κ=0.467；**BEFORE 64.5% vs AFTER 25.5%**
  ——生产闭包改写大方向不被独立证据支持，选择性闭包规则（RETAIN 降格类 /
  REWRITE unknown→event_occurrence）得到三票共识验证；
- identity（600=300正+300硬负，类型可见）：strong 320，标注率 96.3%（578/600）；
  **正向合并 209/209=100.0% 获独立确认（零误并）**；硬负例 72.1% 确认
  different_entity、31 例判 same（框架 false-split 候选，符合宁漏勿错取向）；
  系统身份投影与强共识总体一致率 **90.3%**（288/319）。

## 九、仍然存在的真实边界

1. 升级模型当日仅本地 20B（27B 双通道均不可用）；更强升级模型会右移整条预算曲线；
2. 弱监督标签空间（8 类）与参考标签空间（16 类）的结构性失配，压制预测器 macro-F1 上限；
3. relation 契约的语义结论依赖证据增强后的 judge 重测（运行中）；scope 结论基于两票口径；
4. 空间语义层（政区层级/历史地名版本）在数据层仍 MISSING（升级规格 U6-U8 需外部政区数据）；
5. 质量预算无免费拐点——满质量需要高预算，这是诚实的成本结构。

## 十、论文第三章需要修改的方法表述

1. 删除"弱监督闭环+规则一致性=高可信"的表述，改为"**预测-风险分离 + 外部校准**"；
2. 选择机制从"置信阈值"改为"**三级路由（accept/escalate/abstain）**"，
   升级模型角色=中风险带的有界裁决；
3. Scope closure 从"固定启发式改写"改为"**按变换类型的选择性改写**"
   （REWRITE unknown→event_occurrence；RETAIN event_location 降格类）；
4. Provenance 从"形式指针"改为"**恢复 + 语义支持门**"，strict 定义升级；
5. Relation Contract 定位收缩为纯结构约束；
6. 新增质量-预算权衡与升级成本公式（原方法完全缺失的维度）。

## 最终判断

**当前最终方法（Predictor + Risk Estimator + Selective Escalation + Selective Closure +
Evidence Gate + 结构准入）已经达到可以写入论文正式方法章并接受独立实验检验的程度**——
前提是论文按第十节修改方法表述、按第九节声明边界，且 Evidence Gate 统计与 Judge C
尾部收敛完成后冻结 TEST 正式数字（两者均为正在收尾的机械步骤，非方法风险）。
