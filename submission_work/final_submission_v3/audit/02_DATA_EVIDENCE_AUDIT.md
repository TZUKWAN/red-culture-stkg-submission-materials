# 02 — 数据证据审计

本文件是 GOAL §二十九清单的 02 号交付，汇总数据层证据审计结论；详细论证见
`00_PROJECT_AUDIT.md`（证据分级 A–F）与 `PAPER_CLAIM_EVIDENCE_MATRIX.csv`（40 行逐项矩阵）。

## 数据资产与冻结
- 发布库：`data/release_databases/red_culture_stkg_final_v2.sqlite`（SHA-256 见 `BASELINE_FREEZE_MANIFEST.json`，Phase 0 冻结 55 文件）。
- 语义库（sem attached）与包外集成库（evidence_registry，只读）链路见 `code/independent_eval/_common.py`。
- IMCR 五任务集共 2830 条冻结样本：entity_type 382 / relation_contract 640 / scope_adjustment 208 / identity_pair 600 / provenance_support 1000；payload 盲化泄漏扫描 2830 条零命中（`code/tests/test_no_production_label_leakage.py` 39 例常驻回归）。

## 上游语料数字状态（承 00 号审计）
983 册 / 302230 页 / 282165 候选 / 67791 本地证据 / 17450 Qwen 裁决 五项仍为
NOT_FULLY_VERIFIED（库内最接近口径 16090/6966 均不符）；论文中已按
`14_PAPER_RESULT_MAPPING.csv` 处置（删除或改写），不作为结论依据。

## 本轮新增证据层
- IMCR 独立评价：三 judge（A=Qwen3.6-35B-A3B，B=gpt-5.6-luna，C=minimax-m3:free）×2830 任务 = 8490 次正式调用（另 B3 盲 LLM 2830 次 fresh 调用），全部记录含 GOAL §十九 11 字段；渠道故障与换型史见 `03_IMCR_PROTOCOL.md` §12 与 `raw_runs/_archived_judgeA_attempts/`。
- 证据等级：本轮全部结论为 E 级（independent evaluation）；旧 ERA 结论为 C/D 级（共享通道），两者在 `13_FINAL_EVIDENCE_SUMMARY.md` 与 `14_PAPER_RESULT_MAPPING.csv` 中逐项映射。
