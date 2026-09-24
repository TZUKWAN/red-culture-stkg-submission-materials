# BASELINE & ABLATION RERUN REPORT — 2026-09-19

范围：选择性预测基线与消融实验全套重跑（零新增 LLM 调用）
执行方式：确定性重放（frozen 输入 + 当前冻结脚本）

## 一、执行内容

| 实验 | 命令 | 结果位置 |
|---|---|---|
| 消融 × 6 组合 | `run_selective_semantic.py --reference {strong,leave_b_out} --split {dev,val,test}` | `02_selective_semantic/ABLATION_{RUNS,SUMMARY}_*.csv/json`（原地刷新） |
| 冻结 TEST 基线路由评价（cache-only） | `run_frozen_test_eval.py --skip-escalation` | `02_selective_semantic/frozen_test/`（SUMMARY/ROUTING_RUNS 刷新） |

## 二、重现性结果

### 消融套件（12 件产物）

- **11/12 字节级完全一致**（全部 RUNS csv 与 5/6 summary）。
- 1 件差异：`ABLATION_{RUNS,SUMMARY}_leave_b_out_dev` —— 定性为**陈旧产物刷新**，
  非复现失败：
  - 旧件生成于 09-08 22:08（旧版脚本：无 `changed_components` 列；
    S0 为单变体 `S0_full`），此后未随 09-10 新版脚本刷新
    （同组的 val/test 均已在 09-10 刷新）。
  - 连续性证明：旧 `S0_full`（n=254，cov 0.4331，sel_acc 0.3636）
    与新 `S0_rule_first_legacy` **逐位一致**（legacy 对照按设计保留旧逻辑）。
  - 新增/替换：`S0_production_faithful`（生产保真口径，cov 0.0394）与
    `changed_components` 字段为当前脚本 schema。
- 原始旧件完整保留于 `rerun_20260919_backup/`（12 件）。

### 冻结 TEST 评价（cache-only 重放）

- 19 次 TEST 升级调用全部来自既有真实缓存（2026-09-11 gpt-oss-20b 实调记录），
  本轮 fresh_calls = 0。
- 全部指标与已提交版本**逐字节一致**（coverage/selective_accuracy/risk/AURC/
  escalation_segment_agreement 等无任何变化）；差异仅 created_utc、
  fresh_calls_made=0、wall_seconds 三个元数据字段。

## 三、本轮修复的两个脚本缺陷（为完成重放所必需）

1. `run_selective_semantic.py` 无缺陷；`run_frozen_test_eval.py` 两处：
   - `build_readonly_cache()` 未包含 `TEST_ESC_LOG`，导致 `--skip-escalation`
     永远无法找到 TEST 缓存记录（断言必失败）→ 已并入合并列表。
   - SUMMARY 的 `escalation_model` 直接取当前 `DEFAULT_MODEL`，重放模式下会
     误记为 qwen3.5-4b（真实调用为 gpt-oss-20b）→ 改为从缓存调用的 `model`
     字段读取，防溯源腐蚀。

## 四、与论文的关系

- 消融与基线结论**不变**：所有已提交数字均在重放中复现；
  leave_b_out_dev 的陈旧产物刷新不触及论文引用的任何数字
  （论文 §4.2 引用的是 TEST 口径与 strong/leave_b_out 的 val/test 结果）。
- TEST 基线数字（selective_accuracy 0.6170 / risk 0.3830 等）与已发表版本一致。

## 五、产物清单

- 刷新产物：`experiments/02_selective_semantic/ABLATION_*`（12 件）、
  `frozen_test/`（4 件）
- 原件备份：`experiments/02_selective_semantic/rerun_20260919_backup/`（12 件）
- 重放 replicates：无（本套实验为确定性重放，无随机性；消融 bootstrap 如需
  可由 RUNS csv 直接重算）
- 本报告：`RERUN_20260919_REPORT.md`
