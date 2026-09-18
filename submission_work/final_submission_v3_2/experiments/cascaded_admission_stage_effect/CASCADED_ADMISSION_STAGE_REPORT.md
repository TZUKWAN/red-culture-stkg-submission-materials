# CASCADED ADMISSION STAGE REPORT — 级联准入阶段增益分析（修正统计口径版）

生成：2026-09-19（修正 v2）　零新增 LLM 调用
统计单位：断言（fact_id）；支持口径：审计协议原口径（FULLY_SUPPORTED + PARTIALLY_SUPPORTED）；
判定口径：**双裁判五档完全一致（强共识）**；三类互斥（supported / negative / insufficient），
分类合计 = consensus_n（972/973 冲突见 CONSENSUS_RECONCILIATION.md，已解决）。

## 一、指标定义（本轮修正的核心）

| 指标 | 定义 |
|---|---|
| 强共识覆盖率（Strong Consensus Coverage） | consensus_n / audited_n |
| 强共识条件支持精度（核心质量指标） | supported_consensus_n / consensus_n |
| 强共识条件不支持/冲突率 | (UNSUPPORTED+CONTRADICTED) / consensus_n |
| 强共识条件不足率（单列，不并入负向） | INSUFFICIENT / consensus_n |

上一版的 29.79% / 42.55% / 16.40% / 22.20% / +26.15pp 为
unconditional strong-consensus support share（把 Judge 分歧计入分母），
**不是知识质量指标**，已全部移出正文，仅存于 RESULTS.json 诊断附录。

## 二、核心表：级联准入阶段质量变化（修正口径）

| 指标 | Pre-Gate Strict Candidate（总体 112,158） | Final STRICT（总体 31,067） |
|---|---|---|
| 审计样本量 | 4,427 | 2,268 |
| 强共识覆盖率 | **32.09%** [30.59, 33.60]（ratio 估计量；分层 bootstrap CI） | 42.86%（972/2,268） |
| **强共识条件支持精度** | **69.18%** [66.51, 71.96] | **99.28%**（965/972，冻结）[0.9852, 0.9965] |
| 强共识条件不支持/冲突率 | **29.17%** [26.39, 31.81] | **0.41%**（4/972，冻结）[0.0016, 0.0105] |
| 强共识条件不足率（单列） | 1.64% | 3/972 |
| 阶段作用 | 结构准入后的严格候选（未做证据核验） | 证据语义核验后的严格知识层 |

门外加权 STRICT 机会（单列，引用冻结审计，零重算）：**0.66%，设计型 95%CI [0.40, 0.97]，
全库条数区间 [1,257, 3,019]**。

## 三、估计方法声明

- Pre-Gate 采用 final 层比率估计量
  P = Σ[N_h·(s_h/n_h)] / Σ[N_h·(c_h/n_h)]（N_h = 31,067/31,282/49,809；
  样本 n_h = 2,268/1,094/1,065），CI 为与设计一致的分层 bootstrap
  （B=10,000，seed=20260916，replicates 见
  pre_gate_stratified_bootstrap_replicates.json）。
- 设计精确 π 权重稳健值：冻结采样器的部分 overlay 交集路由池无法从冻结产物
  唯一复原，π 权重变体不稳定，已弃用；层内 overlay/boundary 过采样的代表性局限
  见本节局限段。
- Final STRICT 行沿用冻结审计（AUDIT_RESULTS.json），本轮未重算。

## 四、结果解读（数据支持的边界内）

1. Pre-Gate 候选（尚未核验）的强共识条件支持精度为 69.18%——**已具有较高但
   远非完美的证据质量**；同时 29.17% 的强共识判定明确不支持/冲突，
   32.09% 的强共识覆盖率表明 judge 一致性本身是该证据域的实质约束。
2. Final STRICT 的强共识条件支持精度 99.28%、负向率 0.41%——
   **证据语义核验显著提高支持精度并大幅降低明确不支持/冲突断言进入严格层的比例**
   （支持精度 +30.10pp；负向率 −28.76pp）。
3. 门外加权 STRICT 机会 0.66% [0.40, 0.97]——前置准入的潜在遗漏处于低水平。
4. 局限：层内 predicate/boundary 路由过采样使层内代表性存在不可精确量化的偏差；
   Judge 强共识覆盖率（Pre-Gate 32.09%、Final STRICT 42.86%）属于评价不确定性，
   不与知识错误率混同。

## 五、五项审计

指标定义审计 / 分母审计 / 抽样权重审计 / 972-973 一致性审计 / 全文数字口径审计：
见 `CONSENSUS_RECONCILIATION.md` 与本轮提交说明；全部 PASS。
