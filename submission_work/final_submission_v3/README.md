> [SUPERSEDED 2026-09-16] 本目录为历史版本存档；最终权威数字见
> `submission_work/final_submission_v3_1/AUTHORITATIVE_RESULTS.md`。

# final_submission_v3 — 独立 AI 评价体系（IMCR）与论文证据升级包

在完全保留 V2 工程、原实验与数据库的前提下，补建的独立评价链路。证据等级：
本轮全部结论为 E 级（independent evaluation）；旧 ERA 结论为 C/D 级，两者不得混用。

## 目录
- `audit/`：审计与报告（GOAL §二十九 清单；00 审计、03 协议、04 设计、04A-16 报告集）
- `code/`：`independent_eval/`（盲化/客户端/共识/指标/清单）+ `experiment_pipelines/`（judge 运行、共识、独立基线、选择性预测、统计检验、图表）
- `data/external_inputs/`：冻结的 V2 输入（BASELINE_RUNS 等，SHA-256 见 manifest）
- `experiments/08-14/`：judge 原始记录 → 共识 → 独立基线 → 选择性预测三模式 → 统计检验
- `figures/`：图 A-D（png/pdf + chart contract + audit）
- `manuscript/`：重写后的实验章节（md/docx）+ 新旧映射 + 82 项数字校验脚本
- `tables/`：表 A-F

## 复现主链（详见 audit/15_FINAL_REPRODUCIBILITY_GUIDE.md）
```
judge 运行（环境变量 JUDGE_{A,B,C}_*）→ build_imcr_consensus.py
→ run_independent_baselines.py → run_blind_llm_baseline.py（合并）
→ run_selective_inference.py --reference imcr_strong|imcr_all（及 leave-B-out 对照）
→ run_statistical_tests.py --fill → build_imcr_figures.py 四图
```

## OLD EVIDENCE ↔ NEW INDEPENDENT EVIDENCE
见 `audit/13_FINAL_EVIDENCE_SUMMARY.md`（映射总表）、`audit/14_PAPER_RESULT_MAPPING.csv`
（逐 claim 处置）与 `manuscript/OLD_TO_NEW_MAPPING.md`（章节级映射）。
要点：旧摘要三数字 0.7632/0.9914/0.0086 为 ERA 共享通道自指结果（保留须标注
"相对于 ERA 的一致性结果"）；IMCR 口径下的新数字与不利发现（relation_contract judge
κ=0.037、盲 LLM 多任务优于 Full）在报告集中如实呈现。
