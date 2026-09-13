# FINAL EXPERIMENT COMPARISON — V2/V3 旧结果 vs V3_1 最终方法

日期：2026-09-10 ｜ 逐项对比旧结果、新结果、变化原因（五类归因：IMPLEMENTATION_FIX / METHOD_IMPROVEMENT / EVALUATION_FIX / DATA_REPAIR / STKG_UPGRADE）。
原则：**评价口径修复不伪装成算法效果提升**；每行标注数字类别（MEASURED/SAMPLED/ESTIMATED/DERIVED）。

## 一、评价体系

| 项 | V2/V3 旧 | V3_1 新 | 变化 | 原因分类 |
|---|---|---|---|---|
| 评价参考 | ERA 共享通道（生产链自指） | IMCR 三模型盲评共识（890 strong / 1,524 labeled） | 重构 | EVALUATION_FIX |
| relation 一致性 | κ=0.037（637/640 无原文） | κ=0.541，strong 459/759（SAMPLED=全量 800×3 中 800 changed/control 全带证据） | 修复任务定义 | EVALUATION_FIX + DATA_REPAIR |
| scope 评价 | 两票、无原文 | 三票、205/208 带原文；κ=0.467 | 补证据+第三票 | EVALUATION_FIX |
| identity 评价 | 隐藏实体类型（类型盲区） | 类型可见；κ=0.406 | 修复任务定义 | EVALUATION_FIX |
| B3 盲 LLM 参考 | gpt-5.6-luna 对含同模型票参考（0.988，自指） | leave-B-out 干净参考（0.713-0.742） | 量化膨胀 27pt | EVALUATION_FIX |

## 二、语义预测与升级路由（entity_type，IMCR strong / leave-B-out）

| 方法 | 旧结果 | 新结果（TEST，n=62） | 变化原因 |
|---|---|---|---|
| 生产忠实 S0 | 无 | cov 0.065 / acc 0.250 | MEASURED 定版：生产准入天然只放行 2.6% |
| 盲 LLM every-item | “0.9914 一致率”（ERA 自指） | leave-B-out acc 0.726（SAMPLED n=48） | EVALUATION_FIX：污染修正后的真实上限 |
| Risk 路由升级段 | 无 | 升级段一致率 0.80（9:1 翻转，n=15） | METHOD_IMPROVEMENT |
| Risk Estimator | 无（confidence 直用） | AUPRC 0.728（独立参考训练） | METHOD_IMPROVEMENT |

**同预算路由对比（DEV+VAL pooled，paired bootstrap 2000）**：R6 对 R2 confidence 在 20%/40% 预算显著占优（+4.6pt [+1.2,+8.1] p=0.007；+4.2pt [+0.4,+8.1] p=0.032）、对 R3 margin 在 20% 显著（+5.0pt p=0.010）；对 R1 random 不显著（n=261 边界）。最终判语：**略优**——不宣称“精准路由”，论文表述为“风险排序提供一定预算分配增益”。

## 三、质量预算（主曲线 = 本地 gpt-oss-20b 同模型）

0%=0.276 → 10%=0.353 → 20%=0.429 → 30%=0.475 → 40%=0.540 → 50%=0.598 → 75%=0.743 → **100%=0.828**；
外部参考线 gpt-5.6-luna（leave-B-out）= 0.881。
诚实结论：质量随预算近线性，无免费拐点；75% 本地预算达到外部强模型 84.5% 的质量。

## 四、结构修正组件

| 组件 | V2/V3 旧 | V3_1 新 | 原因分类 |
|---|---|---|---|
| Scope closure | 全量改写；三票强共识 BEFORE 64.5% vs AFTER 25.5%（改写方向不被支持） | 选择性闭包：held-out actionable 89.3% vs old 37.1%（McNemar p=2.7e-05）；unknown→event_occurrence 未达显著改判 UNRESOLVED（保守） | EVALUATION_FIX（三票重建）+ METHOD_IMPROVEMENT（选择性化） |
| Relation Contract 语义主张 | 旧“3412 改写证明语义质量”（无证据基础） | 废除语义主张；changed 58.8% vs control 67.8%（p≈0.04）支持率更低——改写集中在线边界模糊断言 | EVALUATION_FIX |

## 五、证据体系

| 项 | V2/V3 旧 | V3_1 新 | 原因分类 |
|---|---|---|---|
| “无证据”strict | 61,997 条判定“无证据” | 96.6% 恢复证据定位（A 2,841/B 16,705/C 40,345），仅 D 2,106 真无 | DATA_REPAIR |
| strict 层质量 | “有指针即可 strict” | 分层语义门验证 5,000 条；**NEW STRICT ≈ 35,226 [33,744–36,708]（ESTIMATED）**；全库逐条重分层运行中（13,497 已 MEASURED：strict 2,063/contextual 2,480/unresolved 8,954，偏难层优先） | DATA_REPAIR + STKG_UPGRADE |
| 三概念分离 | lineage/locatable/support 混同 | 三者分别报告（§6 指令） | EVALUATION_FIX |

## 六、STKG 能力（U1-U8 落地于副本库，全 MEASURED）

| 升级 | 结果 |
|---|---|
| U1 帧级 provenance | 160,245 行；98.92% 帧有证据链 |
| U2 状态身份 | 655 组碰撞清零（654 merged + 1 kept） |
| U3 CultureState 区间 | 11,532 状态 100% 有时间区间（回退显式标注） |
| U4/U5 时序 | 8,695 帧间 + 5,636,370 同域 Allen 关系（basis+precision 全带） |
| U7 空间层 | 382 条 located_in（类型约束，0 非空间端点） |
| U8 PlaceVersion | 72 个语料证据支持的改名版本（覆盖 0.22%，如实声明） |

## 七、数字类别声明

- MEASURED：评价原始票（4,824+5,000+3,530）、重分层逐条（进行中 13,497/112,158）、STKG 升级行数、闭包 held-out；
- SAMPLED：证据门分层（5,000）、抽取召回（120 页×3）；
- ESTIMATED：全库 strict 35,226（抽样外推；与逐条物化并行推进）；
- DERIVED：所有聚合指标（κ/AURC/CI）由代码从原始行计算。

## 十、FINAL：全量证据语义门（2026-09-14 定版，取代一切估计口径）

- 生产模型：qwen3.5-4b（原生 API，reasoning=off，temperature=0）；判定档案 127,633 条（gzip 归档）。
- 证据门宇宙（旧 strict 重分层宇宙）112,158 条 **逐条 MEASURED，零持留**：
  STRICT **31,067** / CONTEXTUAL **31,282** / UNRESOLVED **49,809**。
- 全库断言宇宙 424,150 条最终三层：strict_semantic 31,067 / contextual 299,329 / unresolved 93,754
  （门宇宙之外的 311,992 条保留其历史口径，不属本轮重分层定义域）。
- 三概念分离：A_lineage 0.4472 / B_localization 0.9812 / C_semantic_support(measured) 0.2823。
- 独立质量审计：预注册协议（盲样本 4,427，双独立裁判 gpt-oss-20b + qwen3-8b），
  结果见 release_final/experiments/quality_audit/AUDIT_RESULTS.json。
- 离线复现：release_final/reproduce/replay_all.py 六步全 PASS（重放 0 差异）。
- 权威数字源：release_final/manifests/FINAL_NUMBERS.json（禁止手抄历史数字）。
