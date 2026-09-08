# 15 — 最终可复现性指南

> 本指南给出从论文数字到 raw run 的追踪路径与实际 CLI 序列。所有命令在仓库根 `D:\REDCULTUREDATA\投稿材料_代码数据整理包` 下执行；代码位于 `submission_work/final_submission_v3/code/`。API key 只从环境变量读取（`.env.example` 提供变量名清单，GOAL §十九）。

---

## 1. 追踪链（paper claim → raw run）

```
paper claim（论文数字）
  → 表/图（V3/tables/table*.csv、V3/figures/imcr_*.png，均带 _CHART_CONTRACT.json/_AUDIT.json）
  → 实验汇总 CSV（experiments/13_*/、experiments/14_*/）
  → 参考集/预测行（experiments/08_independent_reference/IMCR_REFERENCE_*.csv、
     experiments/09_independent_baselines/IMCR_BASELINE_RUNS.csv，31130 行）
  → judge/盲LLM 原始记录（experiments/08_independent_reference/raw_runs/{task}/{A,B,C}.jsonl，
     每行 11 字段：model_id/provider/prompt_version/temperature/top_p/seed/timestamp/
     raw_response/parsed_response/retry_count/validation_error）
  → 盲化 payload（experiments/08_independent_reference/payloads/*.jsonl + PAYLOAD_BUILD_MANIFEST.json）
  → 样本抽取（08/ENTITY_TYPE_SAMPLE.csv 等 + 各 .manifest.json，含输入库 SHA-256）
  → 原始发布库（data/release_databases/red_culture_stkg_final_v2.sqlite，
     SHA-256 a199d736…，只读打开）
```

每个 manifest 均记录输入/输出文件的 SHA-256；文件级校验用 `sha256sum` 逐位核对。

## 2. 版本与种子信息（从各 manifest 提取）

| 项 | 值 | 来源 |
|---|---|---|
| v3 代码 commit | `00498cd8d3a412b6d60620eb7c79ec4baf26f5c0` | IMCR_CONSENSUS_MANIFEST.json / INDEPENDENT_BASELINE_MANIFEST.json / STATISTICAL_ANALYSIS_MANIFEST.json（三处一致） |
| 冻结时仓库 commit | `d418042b55c76a61579d8f4d2e6447039c38808f`（dirty：GOAL.md 与 v3 目录未入库） | audit/BASELINE_FREEZE_MANIFEST.json `git` |
| 主种子 | 20260907 | 各 manifest `seed` |
| judge 调用种子 | 1220050458 = derive_seed("imcr_judge_calls") | raw_runs/*.jsonl `seed` 字段 |
| 派生种子算法 | SHA-256(`task_name|20260907`) 前 8 字节 mod 2³¹ | audit/03_IMCR_PROTOCOL.md §0；code/independent_eval/_common.py::derive_seed |
| A/B 盲化种子 | 11613091355876745079 | SCOPE_ADJUSTMENT_EXTRACTION_AUDIT.json `derived_seed` |
| 配对 bootstrap 种子 | provenance_support::B3_blind_llm → 707394621 | STATISTICAL_ANALYSIS_MANIFEST.json `seed_policy.per_pair_seeds` |
| prompt 版本 | imcr.v3.1 | raw_runs `prompt_version`；imcr_task_defs.PROMPT_VERSION |
| 调用参数 | temperature=0.0, top_p=1.0 | raw_runs 逐行记录 |
| Python（冻结时） | 3.12.14（BASELINE_FREEZE_MANIFEST）；本地复现环境 3.13 亦可 | audit/BASELINE_FREEZE_MANIFEST.json `python` |
| 输入库 SHA-256 | final `a199d736…`；semantic `fbfb6529…` | 各 manifest `db_manifest` |
| judge 模型 | A=Qwen3.6-35B-A3B；B=gpt-5.6-luna；C=minimax/minimax-m3:free | IMCR_CONSENSUS_MANIFEST.json `model_ids` |
| B3 盲 LLM | gpt-5.6-luna（与 Judge B 同模型 → 主对照 leave-B-out） | INDEPENDENT_BASELINE_MANIFEST.json `b3_stats.model_ids` |

## 3. 复现命令序列（实际 CLI）

### 阶段 0：冻结与冻结清单
```
python submission_work/final_submission_v3/code/experiment_pipelines/generate_baseline_freeze_manifest.py
```

### 阶段 1：样本与任务构建（08/10/11/12 号输入）
```
python code/independent_eval/build_entity_type_sample.py            # 382 条实体分层样本
python code/independent_eval/sample_relation_contract_sample.py     # 320 changed + 320 control
python code/independent_eval/extract_scope_adjustment_tasks.py      # 208 条全量 + A/B 语义映射
python code/independent_eval/build_identity_pairs.py                # 300 正例 + 300 硬负例
python code/independent_eval/build_provenance_sample.py             # 1000 条三层
python code/independent_eval/extract_write_manifests.py             # 各样本 manifest + SHA-256
```

### 阶段 2：盲化 payload（泄漏拦截内置）
```
python code/experiment_pipelines/build_judge_payloads.py            # 产出 08/payloads/*.jsonl
#  独立泄漏检测：pytest code/tests/test_no_production_label_leakage.py
```

### 阶段 3：judge 运行（槽位 JUDGE_A/B/C 经环境变量）
```
python code/experiment_pipelines/run_judges.py --resume
#  链路演练（不联网）：--dry-run（产物只进 dry_run/，严禁入论文）
```

### 阶段 4：共识参考集
```
python code/experiment_pipelines/build_imcr_consensus.py
#  产出：IMCR_REFERENCE_STRONG/ALL/LEAVE_{A,B,C}_OUT.csv、JUDGE_PAIRWISE_AGREEMENT.csv、
#        JUDGE_RELIABILITY_SUMMARY.csv、LEAVE_ONE_JUDGE_OUT.csv、IMCR_CONSENSUS_MANIFEST.json
```

### 阶段 5：独立基线
```
python code/experiment_pipelines/run_blind_llm_baseline.py          # B3 fresh 2830 条
python code/experiment_pipelines/run_independent_baselines.py --append-runs experiments/09_independent_baselines/IMCR_BLIND_LLM_RUNS.csv
#  产出：IMCR_BASELINE_RUNS.csv（31130 行）、BASELINE_AVAILABILITY_MATRIX.csv、
#        INDEPENDENT_BASELINE_AUDIT.json（PASS）、INDEPENDENT_BASELINE_MANIFEST.json
```

### 阶段 6：选择性推断（13 号，三种参考模式）
```
python code/experiment_pipelines/run_selective_inference.py --reference imcr_strong --output-dir experiments/13_selective_inference_independent/imcr_strong --output-prefix imcr_strong_
python code/experiment_pipelines/run_selective_inference.py --reference imcr_all    --output-dir experiments/13_selective_inference_independent/imcr_all    --output-prefix imcr_all_
python code/experiment_pipelines/run_selective_inference.py --reference imcr_all --imcr-all-path experiments/08_independent_reference/IMCR_REFERENCE_LEAVE_B_OUT.csv --output-dir experiments/13_selective_inference_independent/leave_b_out --output-prefix leave_b_out_
python code/experiment_pipelines/run_selective_inference.py --reference era --output-prefix era_ --output-dir experiments/13_selective_inference_independent/era_replay   # 旧 ERA 曲线历史复现
python code/experiment_pipelines/verify_era_replay_parity.py        # ERA 逐位一致校验（PASS）
```

### 阶段 7：统计检验（14 号）
```
python code/experiment_pipelines/run_statistical_tests.py --reference imcr_strong --points-dir experiments/13_selective_inference_independent/imcr_strong --points-prefix imcr_strong_ --fill
#  leave-B-out 子目录同法：--reference imcr_all --imcr-all-path .../IMCR_REFERENCE_LEAVE_B_OUT.csv --output-dir experiments/14_statistical_tests/leave_b_out
```

### 阶段 8：结构/来源专项（10/12 号）
```
python code/independent_eval/extract_relation_contract_replay.py    # 3412 条 changed set
python code/independent_eval/run_provenance_gate_stress.py          # 门故障注入 1%/5%/20%
```

### 阶段 9：图件（GOAL §三十 图A–D，含 AUDIT/CHART_CONTRACT）
```
python code/experiment_pipelines/build_imcr_figures.py risk_coverage                --areas-dir experiments/13_selective_inference_independent/imcr_strong
python code/experiment_pipelines/build_imcr_figures.py aurc_augrc_ci                --areas-dir experiments/13_selective_inference_independent/imcr_strong
python code/experiment_pipelines/build_imcr_figures.py scope_validation             --raw-root experiments/08_independent_reference/raw_runs
python code/experiment_pipelines/build_imcr_figures.py relation_contract_validation
```

## 4. 复现核对清单

1. 输入库 SHA-256 与 manifest 一致（只读模式打开，`file:...?mode=ro`）。
2. payload 的 prompt_sha256 与 raw_runs 逐行 `prompt_sha256` 一致。
3. 共识清单中 7 个输出文件 SHA-256 逐一复算（`IMCR_CONSENSUS_MANIFEST.json` `output_files`）。
4. `INDEPENDENT_BASELINE_AUDIT.json` 四项 check 全 true、result=PASS。
5. 13 号三个 REPORT.md Result=PASS、AUGRC 闭式交叉差 ≤1.12e-16；14 号 manifest canaries 全 true。
6. 图件 AUDIT result=PASS、`synthetic=false`。
7. 本仓库无任何 API key 落盘（`grep -ri "sk-\|Authorization" --include="*.jsonl" --include="*.csv" experiments/` 应零命中；judge_client 写盘前 redact）。

## 5. 不可复现项（如实声明）

- 在役 judge/B3 模型为第三方在线服务，模型版本可能随服务端下线/更新而漂移；原始响应已全量落盘（raw_response），解析与统计可离线复现，重新调用不保证逐位一致（temperature=0 下同版本模型通常一致，但 provider 侧无承诺）。
- OpenRouter free 档（judge C）与单网关（Qwen 槽位）存在可用性风险，历史故障记录见 `raw_runs/_archived_*`。
