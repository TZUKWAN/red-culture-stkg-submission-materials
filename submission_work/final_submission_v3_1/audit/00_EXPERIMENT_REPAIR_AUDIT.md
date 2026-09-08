# 00 — V3 实验体系修复审计（EXPERIMENT REPAIR AUDIT）

日期：2026-09-08 ｜ 基线：git ce5a90d6522986e0ea17fd4e5042e316e0d926fc（V3 最终态，完整保留不覆盖）
修复工作目录：`submission_work/final_submission_v3_1/`

## 0. 冻结指纹（本轮起点）

| 对象 | 值 |
|---|---|
| git commit | ce5a90d6522986e0ea17fd4e5042e316e0d926fc |
| final DB | a199d736b9ec436b3d5f244e874718604b6c84955a505f31f90a3e28c51a9ee7 |
| semantic DB | fbfb6529335e1c838270c63eee53c92a568c2b075354f7ad5f9d5815b88bb377 |
| IMCR_REFERENCE_STRONG.csv | 798a29a52be82c30…（full 值见 manifests） |
| IMCR_REFERENCE_ALL.csv | f1a52f697bc528a5… |
| LEAVE_{A,B,C}_OUT | 6f41e1b3… / 50bd576f… / cd0faeee… |
| Judge A | Qwen3.6-35B-A3B @218.197.140.7:3001 |
| Judge B | gpt-5.6-luna @localhost:57882 |
| Judge C | minimax/minimax-m3:free @OpenRouter |
| V3 B3（被本审计否定的主评价） | gpt-5.6-luna（与 Judge B 同模型） |
| V3.1 新 B3 | nvidia/nemotron-3-ultra-550b-a55b:free @OpenRouter（面板外独立模型，Plan A） |

---

## 1. 逐项审计：V3 各实验"评价什么 / 实际测到什么 / 与第三章定义是否一致"

### 1.1 IMCR 参考集本身（08）
- **评价什么**：三模型盲评共识（strong=3/3，weak=2/3），作为独立语义参考。
- **实际测到**：entity_type κ=0.78 可用；scope/identity/provenance κ≈0.42–0.45 中等；**relation_contract κ=0.037（接近随机）**。
- **审计结论**：参考集机制正确（盲化、三家族、留一参考、无生产字段泄漏——泄漏扫描零命中），但 **relation_contract 的 payload 缺语义信息**：640 条中仅 3 条带真实原文证据（其余 evidence_excerpts 为空）。judge 只看到 (subject, predicate, object, 类型) 四元组而没有原文，等于让三个模型对"这条三元组在历史文献里是否成立"做无凭据猜测。**κ=0.037 首先是任务定义/证据缺失问题，其次才是模型分歧。** → 修复：P0-6。

### 1.2 独立基线（09）：B12 的"统一语义映射"是评价对象错位（P0-2）
- **表面评价**：Full framework 在 IMCR 上的"语义正确率"。
- **实际测到**：production 发布状态（release_tier/research_tier/adjustment 方向/canonical 共属/证据存在性）经人工映射投影到 IMCR 标签空间的重合率。
- **逐任务判定**：
  - entity_type：`research_entities.entity_type` 确实是系统的语义预测 → **该任务是真实的语义评价**（B12 0.927 on 41 接受/276 覆盖；328/382 实体生产端 fallback_unresolved 无置信度，硬门如实编码，已披露）。保留，纳入链 A。
  - relation_contract：`strict_semantic→valid; contextual→context_only; unresolved→insufficient_evidence` 把**发布分层**冒充**语义判定**。0.024 的"一致率"不构成对方法语义质量的测量（B12 的 4 标签空间里 `invalid` 恒不预测，参考里 judge 却大量投 invalid/context_only）。**映射废除。**
  - scope_adjustment：恒预测 `AFTER_BETTER` 测的是"共识是否支持闭包方向"，属于链 C（结构改变的语义验证），不是选择性分类。
  - identity_pair：canonical 共属查询是系统**决策重放**，不是身份消歧能力的测量（且 V3 的 payload 隐藏了实体类型——消歧的合法语义输入）。归入链 B/C 重新设计。
  - provenance_support：`research_tier→支持度` 是分层重放。B12 0.305 的真实含义是"生产分层与共识支持度不一致率高"——这是**发布层质量问题**（链 D）的信号，不是"分类器 accuracy"。
- **修复**：P0-2 拆四条实验链（A 选择性语义预测 / B 结构准入 / C 结构改变的语义验证 / D 发布层质量），不再把所有任务强行塞进一个"Full 分类器"。

### 1.3 B3 盲 LLM 的参考污染（P0-1）
- V3 事实：B3=gpt-5.6-luna 与 Judge B 同模型同实例。主参考（strong，含 B 票）下 B3 relation 一致率 0.939；leave-B-out 下塌陷至 0.286。**同模型票对 B3 主数字的污染被数据实证**（这正是旧论文 0.9914 的同构错误在 B3 身上的重演）。
- V3 的缓解（leave-B-out 文件）方向正确，但主表/图仍暴露了受污染口径的对比，产生"B3 五任务全面优于 Full"的过强表述。
- **修复**：P0-1 方案 A——B3 更换为面板外独立模型 nemotron-3-ultra（已探测 10/10 连发成功），2830 条 fresh 重跑，主评价直接用三 judge strong 参考。已启动。

### 1.4 选择性预测统计口径（P0-3）
- McNemar 用 raw `prediction==reference` 计 correct：**未接受/弃权样本的潜在预测也被当作已发布预测参与 b/c 统计**——与选择性预测定义不一致（第三章的机制核心是弃权）。
- 缺 Risk@Coverage / Coverage@Risk / matched-coverage 比较；AURC/AUGRC 有但对数稀少（applicable 门严格）。
- **修复**：McNemar 只在双方共同 accepted 集合上做并报告 n_shared_accepted/coverage_A/coverage_B；新增 Risk@C 与 C@Risk；配套 `test_mcnemar_respects_acceptance.py` 等 16 个自动测试。

### 1.5 消融不是真消融（P0-4）
- V3 的 B10（去结构门）/B11（去弃权）只覆盖第三章五组件中的两个，且"类特异性可靠门 / 证据一致性 / 反向冲突抑制"从未被单独消掉——S 系列消融缺失。
- **修复**：P0-4 在 entity_type 上实现 S0–S10 十一种变体，逐组件移除，其余冻结。

### 1.6 无 DEV/TEST 隔离（P0-5）
- V3 的所有阈值/映射/评价都在同一 IMCR 集合上设计与报告——设计集=评价集，存在过拟合风险（虽未发生主动调参，但程序上无法自证）。
- **修复**：book-grouped 切分（防同书泄漏），DEV(60)/VAL(20)/TEST(20)，manifest 固化 + SHA 记录；所有后续调优只碰 DEV/VAL，TEST 冻结至算法冻结后一次性评价。

### 1.7 scope/identity/provenance payload 证据不足（P0-6/7/8/9）
- scope_adjustment payload 无原始文献句（judge 只看到结构化断言+类型定义）。
- identity payload 隐藏实体类型——实体类型是消歧的合法语义输入，隐藏它制造了系统性伪失败（org_vs_place 40/40 被共识判同：类型盲区的直接证据）。
- provenance 的 B12 是分层重放；strict 层的语义支持从未被真正验证。
- **修复**：三者全部以"judge 可见真实原文证据、不可见生产决策"重建 payload 并重评；scope 按变换类型做误差定位后允许算法修复（DEV 上），在冻结 TEST 上比较新旧 closure。

### 1.8 哪些是真缺陷、哪些只是评价定义错误
| 项 | 判定 |
|---|---|
| relation κ=0.037 | **评价定义错误为主**（payload 无证据）；修复后重测 |
| B12 relation 0.024 / provenance 0.305 | **评价对象错位**（分层≠分类）；废除映射 |
| B3 relation 0.939 vs 0.286 | **参考污染**；换独立模型 |
| McNemar 含弃权样本 | **统计口径错误** |
| scope AFTER 不优于 BEFORE | **待定**：payload 无原文 + 未按规则类型分解 → 先修评价再定位算法 |
| identity org_vs_place 40/40 判同 | **评价缺陷为主**（类型盲区）；修复后重测 |
| entity_type 0.927 且生产端 328/382 fallback_unresolved 无置信 | **真实方法现状**（诚实保留；选择机制在此数据上的价值正是把 unresolved 挡在 strict 外） |
| 分类器/门未校准未调优 | **真实方法提升空间**（P1，DEV 上做） |

## 2. 修复工作总计划（与 GOAL 优先级一致）

P0-1 B3 独立重跑（已启动，nemotron）→ P0-3 统计修复+测试 → P0-5 切分固化 → P0-2/P0-4 链 A 重构+真消融 → P0-6 relation 证据重建重评 → P0-7 scope 原文重建+误差定位+算法修复 → P0-8 identity 类型可见重评 → P0-9 provenance 语义门+重发布 → P1 召回/跨源/校准/门优化 → 逐项测试 → FINAL_EXPERIMENT_COMPARISON.md。

## 3. 本审计的自我声明
- 本文件只做诊断，不含任何新实验数字的"修正"；所有新数字产生于 v3_1 的新运行。
- V2/V3 文件零修改；V3.1 全部新建。
