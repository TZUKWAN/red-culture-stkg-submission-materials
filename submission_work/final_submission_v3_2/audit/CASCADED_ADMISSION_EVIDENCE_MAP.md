# CASCADED ADMISSION EVIDENCE MAP — 每个数字来自哪里（修正口径版 v2）

逐项说明《级联准入阶段增益分析（修正口径）》中每个数字的来源文件、字段与计算方法。
本轮**零新增 LLM 调用**；除新组合计算外全部直接引用既有权威结果。
统计口径：**强共识条件指标**（分母 = 双裁判五档完全一致的样本）；
分类互斥三分（supported / negative / insufficient），合计 = consensus_n。

## 分析脚本与输入

- 脚本：`experiments/cascaded_admission_stage_effect/analyze_cascaded_stages.py`
- 输入 1：`release_final/experiments/quality_audit/SAMPLE_KEY.json`
  （4,427 条样本 fact_id 与 production_tier；全部属于 112,158 门宇宙，
  即全部为 pre-gate strict candidate）
- 输入 2/3：`release_final/experiments/quality_audit/
  JUDGE_gpt_oss_20b_VERDICTS.jsonl`、`JUDGE_qwen_qwen3_8b_VERDICTS.jsonl`
- 抽样设计：`release_final/configs/FINAL_QUALITY_AUDIT_PROTOCOL.json`
  （actual_alloc_by_tier_stratum + 抽样 seed 20260914）
- 层总体：`FINAL_NUMBERS.json`（STRICT 31,067 / →CTX 31,282 / →UNRES 49,809）

## 逐数字溯源

| 数字 | 值 | 来源/计算 |
|---|---|---|
| Pre-Gate 审计样本量 | 4,427 | SAMPLE_KEY.json 条数（全部门宇宙 = pre-gate strict candidate） |
| Pre-Gate 强共识覆盖率 | 32.09% [30.59, 33.60] | final 层比率估计量 Σ[N_h·(c_h/n_h)]/ΣN_h；CI=分层 bootstrap（B=10,000，seed=20260916） |
| Pre-Gate 强共识条件支持精度 | **69.18%** [66.51, 71.96] | 同估计量，分子用 s_h（supported = FULLY+PARTIAL） |
| Pre-Gate 强共识条件负向率 | 29.17% [26.39, 31.81] | 同估计量，neg_h（UNSUPPORTED+CONTRADICTED） |
| Pre-Gate 强共识条件不足率 | 1.64% | ins_h，单列不并入负向 |
| Final STRICT 强共识条件支持精度 | **99.28% = 965/972** [0.9852, 0.9965] | 冻结审计 AUDIT_RESULTS.json → `strict_support_precision_strong_consensus_detail` |
| Final STRICT 强共识条件负向率 | **0.41% = 4/972** [0.0016, 0.0105] | 同上 |
| Final STRICT 强共识覆盖率 | 42.86% = 972/2,268 | 计算（仅说明 Judge 一致性覆盖，不与知识错误率混同） |
| kept vs downgraded（强共识条件支持精度） | 99.28% vs 57.00%（354/639） | 计算；差值 Newcombe CI 见 RESULTS.json |
| kept vs downgraded（强共识条件负向率） | 0.41% vs 40.10% | 计算 |
| 门外加权 STRICT 机会 | 0.66% [0.40, 0.97]，条数 [1,257, 3,019] | **引用冻结审计**（OUTSIDE_GATE_AUDIT_RESULTS.json → weighted_strict_opportunity_design_ci），零重算 |
| 门外样本强共识机会 0.63%（31/4,957） | 引用 | 同上 |

## 已撤口径（诊断附录，不得进入论文结论）

29.79%、42.55%、16.40%、22.20%、+26.15pp 为
unconditional strong-consensus support share（分母含 Judge 分歧），
仅存于 `CASCADED_ADMISSION_STAGE_RESULTS.json` 的
`diagnostic_unconditional_shares`，不得称为 accuracy/precision/support
quality/evidence support rate。

## 与其他权威数字的关系

- 99.28%（965/972）与 69.18%（Pre-Gate 比率估计量）：分母口径不同
  （前者=STRICT 层强共识子集；后者=全部门宇宙加权），分别对应两阶段。
- 分解数字（47,576/127/2,106；27,704/3,578；264,635/3,412；27,492/16,393/60）
  与 FINAL_TIERING.csv / FULL_UNIVERSE_ADMISSION_SUMMARY.json 交叉核对一致。
