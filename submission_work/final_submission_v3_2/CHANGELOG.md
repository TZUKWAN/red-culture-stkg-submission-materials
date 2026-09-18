# CHANGELOG — final_submission_v3_2（级联准入阶段增益 + 论文修订）

生成：2026-09-18　基于：final_submission_v3_1（最终发布包）+ 本轮新增分析

## 一、本轮新增的分析（唯一新增实验）

**级联准入整体有效性实验（Cascaded Admission Stage-wise Effectiveness Analysis）**
位置：`experiments/cascaded_admission_stage_effect/`
脚本：`analyze_cascaded_stages.py`（零新增 LLM 调用，全部复用既有冻结审计）
数据源：
- `release_final/experiments/quality_audit/SAMPLE_KEY.json`（4,427 样本及其最终层）
- `release_final/experiments/quality_audit/JUDGE_gpt_oss_20b_VERDICTS.jsonl`
- `release_final/experiments/quality_audit/JUDGE_qwen_qwen3_8b_VERDICTS.jsonl`
- 层总体规模常量（31,067/31,282/49,809，源自 FINAL_NUMBERS.json）

**指标定义（2026-09-19 修正版，替代同日初版口径）**：核心质量指标一律为
**强共识条件指标**（分母 = 双裁判五档完全一致的样本），两指标独立报告：
①强共识覆盖率 = consensus_n / audited_n；②强共识条件支持精度 =
supported_consensus_n / consensus_n（FULLY+PARTIAL）；负向率与不足率单列。

新增数字（全部可在 `audit/CASCADED_ADMISSION_EVIDENCE_MAP.md` 溯源）：
- Pre-Gate Strict Candidate（若直接发布）：
  强共识覆盖率 32.09%（95%CI 30.59–33.60，final 层比率估计量）；
  强共识条件支持精度 69.18%（95%CI 66.51–71.96）；
  强共识条件负向率 29.17%（95%CI 26.39–31.81）；不足率 1.64%。
- Final STRICT（冻结口径）：支持精度 99.28%（965/972，95%CI [0.9852, 0.9965]）；
  负向率 0.41%（4/972）；强共识覆盖率 972/2,268。
- 准入结局分组（强共识条件口径）：kept 99.28% vs downgraded 57.00%（支持精度）；
  负向率 0.41% vs 40.10%。
- **[WITHDRAWN 同日]** 初版曾以 29.79%/42.55%/16.40%/22.20%/+26.15pp
  （unconditional strong-consensus support share，分母含 Judge 分歧）作为
  知识质量指标——该口径混合评价不确定性与知识质量，已全部撤出论文正文，
  仅保留于 RESULTS.json 诊断附录（diagnostic_unconditional_shares）。McNemar 不适用（分组为观测分层而非同一对象两次测量）。

## 二、直接引用的既有权威结果（零重算）

- 门外加权 STRICT 机会 0.66%，设计型 95%CI [0.40, 0.97]，条数区间 [1,257, 3,019]：
  `experiments/10_full_universe_admission_closure/OUTSIDE_GATE_AUDIT_RESULTS.json`
  → `weighted_strict_opportunity_design_ci`（冻结审计，本轮未重算口径）。
- 严格候选构成：268,047（raw 谓词 264,635 + 域违反 3,412）、
  43,945（scope 冲突 27,492 + 端点类型 16,393 + 人工遗留 60）、112,158：
  `experiments/10_full_universe_admission_closure/FULL_UNIVERSE_ADMISSION_SUMMARY.json`。
- 99.28% = 965/972（95%CI [0.9852, 0.9965]）、FP 0.41% = 4/972：
  `release_final/experiments/quality_audit/AUDIT_RESULTS.json`
  → `strict_support_precision_strong_consensus_detail`（本轮补分子/分母/CI）。
- 最终三层 31,067/31,282/49,809 与全库 31,067/299,329/93,754：
  `release_final/manifests/FINAL_NUMBERS.json`。
- UNRESOLVED 49,809 分解（47,576/127/2,106）与 CONTEXTUAL 31,282 分解
  （27,704/3,578）：FINAL_TIERING.csv 按 semantic_support 交叉计数。

## 三、论文表达调整（不改变实验数字）

- 题名（中/英）更新为「面向知识规范化与级联准入……」。
- 摘要 [结果] 改为级联口径（424,150 → 112,158 → 31,067/31,282/49,809），
  并新增一句阶段增益关键结果；关键词更新。
- §2 重排为 2.1/2.2/2.3 三方面 + 研究评述（原引文号 [8]–[36] 全部保留）。
- §3 标题更新并补一句「证据语义核验位于前置准入之后」。
- 新增 §4.5「全库级联准入及阶段增益分析」（含表 5、图 fig_cascaded_admission_stage_effect）；
  原「4.5 本地确定性构建链」重编号为 4.6。
- §5 新增「结构规范化合格 ≠ 证据语义充分支持」讨论段；
  §6 收束级联准入整体实证结果。
- 参考文献：李锦辉等《嵌入关系耦合度的电力调度知识图谱构建方法研究》
  **不在当前正文 45 条实际引用中**（全库检索无此条目）；若后续版本重新引用，
  其网络首发日期必须记为 **2026-04-11**（以原论文首发信息为准），
  不得使用曾误写的 2026-09-04。核对说明已写入正文末尾。

## 四、本轮没有重新运行的已有实验

- 未重新调用任何 LLM（0 次新增模型调用）。
- 未重跑：证据语义门（112,158）、门内 4,427 双裁判审计、门外 5,000 双裁判审计、
  scope 208 条盲评、Relation Contract 3,412 条专项、Identity Projection、
  全库确定性回放（replay_all.py 仅作周期性确认，结果不变）、效率实验、
  选择性预测 152 条核心评价。
- 未修改：FINAL_TIERING.csv、FINAL_NUMBERS.json（本轮只新增，不改既有数字）、
  AUDIT_RESULTS.json（仅在既有字段外新增 detail 字段）、门外审计冻结结果。

## 五、入口修复

- 仓库 `README.md`：新题名 + 权威入口（release_final / AUTHORITATIVE_RESULTS /
  v3_2 manuscript）+ v2/v3 目录标为历史存档。
- `metadata/CURRENT_RELEASE.json`：由 red-culture-stkg-v2-1 更新为
  red-culture-stkg-final-2026-09（canonical DB 指向 release_final 数据库，
  含 final_tiers、gate_tiers、release_package、EXE/zip 哈希与 git tag）。
