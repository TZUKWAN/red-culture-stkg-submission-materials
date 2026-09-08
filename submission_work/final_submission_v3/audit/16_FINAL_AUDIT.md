# 16 — 最终审计报告（FINAL AUDIT）

> **证据等级声明**：本审计覆盖 audit/04A、05、06、07、08、09、10、12、13、15 号报告与 tables/tableA–F 的全部关键数字；被审计对象均为 **E 级（independent evaluation）** 证据产物；结构回放类数字为 B 级（deterministic replay）并单独标注。

- 审计方式：用独立 Python 脚本（%TEMP%\final_audit_checks.py，审计用临时脚本，不入仓库数据文件）对下表每一项"期望值"从其声明的来源 CSV/JSON **重新计算**并逐位比较；浮点比较容差 1e-4（标注 tol=1e-6 者为 1e-6）。
- 审计结果：**51/51 项全部一致（PASS）**，0 项 FAIL。审计时间：2026-09-07。
- 审计中发现并在报告内更正的两处来源标注问题（数字本身无误）：
  1. `imcr_strong_SELECTIVE_GOAL13_METRICS.csv` 中 **B12 无 scope_adjustment / identity_pair 行**（该两格无逐条置信，管线未产出指标行）；B12 的 scope 0.4595（n=111）与 identity 0.6466（n=399）的正确来源是 `WILSON_CI_TABLE.csv` 的 B12 行。06/07 号报告已把来源标注改为 WILSON，并在 06 号 §1/§4 加口径披露；macro-F1 0.2099/0.3752 与 B11 行相同（B11/B12 共享预测与恒接受行为）。
  2. 09 号报告 identity 的分组联表分母（剔除参考 insufficient_evidence：strong 397、leave-B 454）与 GOAL13 全分母口径（399/456）不同，已在 09 号 §3 表内双口径并注。

## 审计核对明细（51 项）

| # | 结果 | 核对项 | 期望值 | 复算值 | 来源文件 |
|---|---|---|---|---|---|
| 1 | PASS | 共识 strong 总数 1246 | expect: 1246 | actual: 1246 | IMCR_CONSENSUS_MANIFEST.json |
| 2 | PASS | 共识 all 总数 2593 | expect: 2593 | actual: 2593 | IMCR_CONSENSUS_MANIFEST.json |
| 3 | PASS | leave-B-out 行数 1640 | expect: 1640 | actual: 1640 | IMCR_CONSENSUS_MANIFEST.json |
| 4 | PASS | unresolved 总数 237 | expect: 237 | actual: 237 | IMCR_CONSENSUS_MANIFEST.json |
| 5 | PASS | entity Fleiss κ=0.7803 | expect: 0.7803 | actual: 0.7803 | JUDGE_RELIABILITY_SUMMARY.csv |
| 6 | PASS | relation Fleiss κ=0.0368 | expect: 0.0368 | actual: 0.0368 | JUDGE_RELIABILITY_SUMMARY.csv |
| 7 | PASS | scope Fleiss κ=0.4492 | expect: 0.4492 | actual: 0.4492 | JUDGE_RELIABILITY_SUMMARY.csv |
| 8 | PASS | identity Fleiss κ=0.4311 | expect: 0.4311 | actual: 0.4311 | JUDGE_RELIABILITY_SUMMARY.csv |
| 9 | PASS | provenance Fleiss κ=0.4207 | expect: 0.4207 | actual: 0.4207 | JUDGE_RELIABILITY_SUMMARY.csv |
| 10 | PASS | relation strong=66 | expect: 66 | actual: 66 | JUDGE_RELIABILITY_SUMMARY.csv |
| 11 | PASS | relation A-C κ=0.0156 | expect: 0.0156 | actual: 0.0156 | JUDGE_PAIRWISE_AGREEMENT.csv |
| 12 | PASS | entity B-C agreement=0.7827 | expect: 0.7827 | actual: 0.7827 | JUDGE_PAIRWISE_AGREEMENT.csv |
| 13 | PASS | relation LOJO 剔A=0.3605 | expect: 0.3605 | actual: 0.3605 | LEAVE_ONE_JUDGE_OUT.csv |
| 14 | PASS | scope strong BEFORE=58/AFTER=51/INSUF=2 | expect: 58/51/2 | actual: 58/51/2 | IMCR_REFERENCE_STRONG.csv(scope) |
| 15 | PASS | provenance strong unsupported=152 | expect: 152 | actual: 152 | IMCR_REFERENCE_STRONG.csv(provenance) |
| 16 | PASS | relation strong invalid=36/context=6/insuf=24/valid=0 | expect: 36/6/24/0 | actual: 36/6/24/0 | IMCR_REFERENCE_STRONG.csv(relation) |
| 17 | PASS | scope ALL BEFORE=97/AFTER=70 | expect: 97/70 | actual: 97/70 | IMCR_REFERENCE_ALL.csv(scope) |
| 18 | PASS | judge C provenance 1000 行中 38 条 INVALID | expect: 1000/38 | actual: 1000/38 | C.jsonl |
| 19 | PASS | IMCR_BASELINE_RUNS 行数=31130 | expect: 31130 | actual: 31130 | IMCR_BASELINE_RUNS.csv |
| 20 | PASS | B12 entity 328 条无置信度 | expect: 328 | actual: 328 | IMCR_BASELINE_RUNS.csv(B12 entity) |
| 21 | PASS | B12 scope 恒 AFTER_BETTER 208 | expect: 208/208 | actual: 208/208 | IMCR_BASELINE_RUNS.csv(B12 scope) |
| 22 | PASS | 基线审计 result=PASS | expect: PASS | actual: PASS | INDEPENDENT_BASELINE_AUDIT.json |
| 23 | PASS | 可用行 15774 / 不可用 15356 | expect: 15774/15356 | actual: 15774/15356 | INDEPENDENT_BASELINE_AUDIT.json+IMCR_BASELINE_RUNS.csv |
| 24 | PASS | B3 模型 gpt-5.6-luna | expect: ['gpt-5.6-luna'] | actual: ['gpt-5.6-luna'] | INDEPENDENT_BASELINE_MANIFEST.json |
| 25 | PASS | B3 各任务 OK 全满(2830) | expect: 2830 | actual: 2830 | INDEPENDENT_BASELINE_MANIFEST.json b3_stats |
| 26 | PASS | B12 entity 一致率 0.9268 (41 接受) | expect: (0.926829268292683, 41) | actual: (0.926829268292683, 41) | imcr_strong_SELECTIVE_GOAL13_METRICS.csv |
| 27 | PASS | B12 relation 一致率 0.0238 (n=42) | expect: 0.0238/42 | actual: 0.0238/42 | imcr_strong_SELECTIVE_GOAL13_METRICS.csv |
| 28 | PASS | B12 scope 0.4595 (n=111, WILSON; GOAL13 无 B12 scope 行) | expect: (0.4594594594594595, 111) | actual: (0.4594594594594595, 111) | WILSON_CI_TABLE.csv |
| 29 | PASS | B12 identity 0.6466 (n=399, WILSON; GOAL13 无 B12 identity 行) | expect: (0.6466165413533834, 399) | actual: (0.6466165413533834, 399) | WILSON_CI_TABLE.csv |
| 30 | PASS | B3 relation(strong,含同模型票) 0.9394 | expect: 0.9394 | actual: 0.9394 | imcr_strong_SELECTIVE_GOAL13_METRICS.csv |
| 31 | PASS | B3 leave-B 五任务 0.9234/0.2863/0.6985/0.8662/0.7984 | expect: [0.9234, 0.2863, 0.6985, 0.8662, 0.7984] | actual: [0.9234, 0.2863, 0.6985, 0.8662, 0.7984] | leave_b_out_SELECTIVE_GOAL13_METRICS.csv |
| 32 | PASS | B12 provenance AURC=0.3936 | expect: 0.3936 | actual: 0.3936 | imcr_strong_RISK_COVERAGE_SUMMARY.csv |
| 33 | PASS | B12 entity score_coverage=0.1486 | expect: 0.1486 | actual: 0.1486 | imcr_strong_RISK_COVERAGE_SUMMARY.csv |
| 34 | PASS | B11 entity unique_score=1(单点) | expect: 1 | actual: 1 | imcr_strong_RISK_COVERAGE_SUMMARY.csv |
| 35 | PASS | B12 entity CI=[0.8057,0.9748] n=41 | expect: 0.8057..0.9748..41 | actual: 0.8057..0.9748..41 | WILSON_CI_TABLE.csv |
| 36 | PASS | ΔAURC(Full−B3)=0.3752 [0.3426,0.4073] | expect: (0.3752, 0.3426, 0.4073) | actual: (0.3752, 0.3426, 0.4073) | PAIRED_BOOTSTRAP_DELTAS.csv |
| 37 | PASS | McNemar entity Full vs B3 = 2:141 p=1.85e-39 | expect: 2/141/1.8469e-39 | actual: 2/141/1.8469e-39 | MCNEMAR_TESTS.csv |
| 38 | PASS | McNemar scope Full vs B3 = 7:46 p=4.00e-08 | expect: 7/46/4.003e-08 | actual: 7/46/4.003e-08 | MCNEMAR_TESTS.csv |
| 39 | PASS | McNemar 配对数 25(strong 口径 5 任务×5 基线) | expect: 25 | actual: 25 | MCNEMAR_TESTS.csv |
| 40 | PASS | w/o Relation Contract changed=3412 且违例=3412 | expect: 3412/3412 | actual: 3412/3412 | STRUCTURAL_REPLAY_AUDIT.json |
| 41 | PASS | w/o Role-owner 44 时间+112 空间, changed=208 | expect: 44/112/208 | actual: 44/112/208 | STRUCTURAL_REPLAY_AUDIT.json |
| 42 | PASS | 总回放断言 424150 | expect: 424150 | actual: 424150 | STRUCTURAL_REPLAY_AUDIT.json |
| 43 | PASS | 208 条调整 & mismatch=0 | expect: 208/0 | actual: 208/0 | SCOPE_ADJUSTMENT_EXTRACTION_AUDIT.json |
| 44 | PASS | changed set 3412 行且全部 release_tier=contextual | expect: 3412/contextual | actual: 3412/contextual | RELATION_CONTRACT_CHANGED_SET.csv |
| 45 | PASS | provenance 三层 400/300/300 | expect: 400/300/300 | actual: 400/300/300 | PROVENANCE_SUPPORT_METADATA.csv |
| 46 | PASS | 故障注入 20% 注入 22432 全拦截 FP=0 | expect: 22432/22432/1.0/0 | actual: 22432/22432/1.0/0 | PROVENANCE_GATE_STRESS_SUMMARY.json |
| 47 | PASS | identity 正例 217/217、硬负例 41/180 | expect: 217/217 | 41/180 | actual: 217/217 |
| 48 | PASS | org_vs_place 0/40、similar_name_person 34/34 | expect: 0/40 | 34/34 | actual: 0/40 |
| 49 | PASS | 代码 commit 一致(共识/基线/统计三处) | expect: 00498cd8d3a412b6d60620eb7c79ec4baf26f5c0（三处一致） | actual: 00498cd8d3a412b6d60620eb7c79ec4baf26f5c0（三处一致） | 三个 manifest 的 code_commit |
| 50 | PASS | B3 派生种子 707394621 | expect: 707394621 | actual: 707394621 | STATISTICAL_ANALYSIS_MANIFEST.json seed_policy |
| 51 | PASS | ERA 回放 parity verdict=PASS | expect: PASS | actual: PASS | ERA_REPLAY_PARITY_REPORT.json |
## 复核说明

1. **浮点一致性**：所有百分数保留 4 位小数引用；与源 CSV 全精度值差 ≤5e-5（表内 CI 端点同）。ΔAURC 点值与 13 号 SUMMARY 交叉核对 max_abs_diff=0.000e+00（`figures/imcr_aurc_augrc_ci_AUDIT.json` `areas_crosscheck`）。
2. **覆盖范围**：本表覆盖 judge 一致性（04A）、基线网格与可用性（05）、三模式选择推断与面积（06）、scope（07）、relation（08）、identity（09）、provenance 与门压力测试（10）、可复现性种子（15）的关键数字；13/14 号映射 CSV 中的定性判断不适用数值核对，其引用数字均已包含在上表对应行。
3. **已知的口径性事实（非错误，报告内已披露）**：
   - GOAL13 文件缺 B12 scope/identity 行（见上）；
   - judge C 在 provenance 上 38 条 MODEL_OUTPUT_INVALID，两两统计分母 962（`JUDGE_PAIRWISE_AGREEMENT.csv` n_compared）；
   - leave_b_out 运行的 `reference_mode` 字段记录为 "imcr_all"（2-judge 重聚合沿用 all 档规则），实际参考文件为 `IMCR_REFERENCE_LEAVE_B_OUT.csv`（1640 行，`leave_b_out_risk_coverage_audit.json` `reference_metadata.reference_row_count=1640`）——引用时以文件与行数为准；
   - raw_runs/identity_pair/A.jsonl 含 2 条 TRANSPORT_ERROR（600 OK），共识计票前剔除。
4. **审计脚本与临时摘要文件**（extract1–8.py、build_tables2.py、final_audit_checks.py）均在 %TEMP%，未写入仓库数据目录；仓库内被修改/新增的文件仅限本任务交付清单（audit/04A–16 号、tables/tableA–F）。

## 交付文件清单（本任务新增）

| 文件 | 说明 |
|---|---|
| audit/04A_IMCR_JUDGE_RELIABILITY.md | judge 面板与一致性 |
| audit/05_BASELINE_REPORT.md | B1–B12 基线 |
| audit/06_SELECTIVE_INFERENCE_REPORT.md | 三模式选择性推断 |
| audit/07_SCOPE_ADJUSTMENT_VALIDATION.md | 208 条 scope 盲评 |
| audit/08_RELATION_CONTRACT_VALIDATION.md | 640 条关系契约盲评 |
| audit/09_IDENTITY_VALIDATION.md | 600 对身份盲评 |
| audit/10_PROVENANCE_VALIDATION.md | 来源支持度与门定位 |
| audit/12_EXPERIMENT_LIMITS.md | 局限清单（L1–L12） |
| audit/13_FINAL_EVIDENCE_SUMMARY.md | 新旧证据映射总表 |
| audit/14_PAPER_RESULT_MAPPING.csv | 机器可读映射（20 行） |
| audit/15_FINAL_REPRODUCIBILITY_GUIDE.md | 追踪链与 CLI |
| audit/16_FINAL_AUDIT.md | 本文件 |
| tables/tableA_judge_agreement.csv … tableF_provenance_support.csv | GOAL §三十 表 A–F |

结论：**报告集数字与来源 CSV/JSON 逐位一致，审计通过（51/51 PASS）**。
