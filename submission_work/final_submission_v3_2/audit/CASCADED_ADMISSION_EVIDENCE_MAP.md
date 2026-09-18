# CASCADED ADMISSION EVIDENCE MAP — 每个数字来自哪里

逐项说明《级联准入阶段增益分析》中每个数字的来源文件、字段与计算方法。
本轮**零新增 LLM 调用**；除新组合计算外全部直接引用既有权威结果。

## 分析脚本与输入

- 脚本：`experiments/cascaded_admission_stage_effect/analyze_cascaded_stages.py`
- 输入 1：`release_final/experiments/quality_audit/SAMPLE_KEY.json`
  （4,427 条样本的 fact_id 与 production_tier；全部属于 112,158 门宇宙，
  即全部为 pre-gate strict candidate）
- 输入 2/3：`release_final/experiments/quality_audit/
  JUDGE_gpt_oss_20b_VERDICTS.jsonl`、`JUDGE_qwen_qwen3_8b_VERDICTS.jsonl`
  （双裁判五档判定；parse_ok 过滤后联合有效 n=4,427）
- 总体规模常量：STRICT 31,067 / →CTX 31,282 / →UNRES 49,809
  （来源：`release_final/manifests/FINAL_NUMBERS.json` 的
  `gate_strict` / `gate_contextual` / `gate_unresolved`）

## 逐数字溯源

| 数字 | 值 | 来源文件 → 字段/计算 |
|---|---|---|
| Pre-Gate 样本量 | 4,427 | SAMPLE_KEY.json 条数（全部门宇宙） |
| Pre-Gate 支持数 1,319 | 1,319 | 双裁判 verdicts 中 `decision==decision` 且 ∈ {FULLY, PARTIAL} 的条数（强共识口径） |
| Pre-Gate 样本支持率 29.79% [28.47, 31.16] | 计算 | wilson(1319, 4427) |
| Pre-Gate 总体加权率 22.20% [21.06, 23.38] | 计算 | 按 final 层构成加权（层支持率 × 31,067/31,282/49,809 ÷ 112,158）+ 分层 bootstrap B=10,000 seed=20260916 |
| Final STRICT 样本量 2,268 | 2,268 | SAMPLE_KEY.json 中 production_tier=STRICT 的条数（抽样框=该层） |
| Final STRICT 支持率 42.55% [40.53, 44.59] | 计算 | wilson(965, 2268)；965 = 该层内强共识且 ∈ {FULLY, PARTIAL} |
| Final STRICT 内部 99.28% = 965/972 | 引用 | quality_audit/AUDIT_RESULTS.json → `strict_support_precision_strong_consensus_detail`（仅强共识子集的另一口径，与本表口径不同，不得混用） |
| kept 支持率 42.55% [40.53, 44.59] | 计算 | 同 Final STRICT 行（kept = final STRICT） |
| downgraded 支持率 16.40% [14.89, 18.02] | 计算 | wilson(354, 2159)；downgraded = final ∈ {CONTEXTUAL, UNRESOLVED} |
| 差值 +26.15pp，Newcombe [23.56, 28.69] | 计算 | newcombe(965,2268,354,2159) |
| 差值 bootstrap CI [23.62, 28.67] | 计算 | 按结局层重采样 B=10,000 seed=20260916 |
| Fisher 精确 p（双侧） | <1e-6 | 2×2 精确检验（kept: 965/2268 vs downgraded: 354/2159） |
| 检验选择说明 | — | McNemar 不适用（kept/downgraded 为观测分层，非同一对象两次测量） |
| 裁判分歧条数 2,816 / 1,295 | 计算 | n − (支持+不支持+冲突+不足)；分歧不计支持（保守口径） |
| 门外加权 STRICT 机会 0.66% [0.40, 0.97]，条数 [1,257, 3,019] | **引用，零重算** | `experiments/10_full_universe_admission_closure/OUTSIDE_GATE_AUDIT_RESULTS.json` → `weighted_strict_opportunity_design_ci` |
| 门外样本强共识机会 0.63% (31/4,957) | 引用 | 同上（strong consensus 口径） |

## 与其他权威数字的关系

- 31,067 / 31,282 / 49,809：与 `FINAL_NUMBERS.json`、`AUTHORITATIVE_RESULTS.md` 一致。
- 0.9928（965/972）与 42.55%（965/2,268）：分子同为 965，分母口径不同
  （前者=强共识 STRICT 子集；后者=全部 kept 样本，分歧不计支持）。
  论文中两口径并存时必须分别注明。
- 0.66% [0.40, 0.97]：门外审计冻结结果，本轮未重算任何口径。
