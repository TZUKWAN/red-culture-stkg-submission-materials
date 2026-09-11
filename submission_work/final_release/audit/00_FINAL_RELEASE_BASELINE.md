# 00 — FINAL RELEASE 基线

日期：2026-09-11 ｜ 基线 commit：见 `git log HEAD` ｜ 本文档在冻结前持续更新

## 环境
- Python 3.13.2 (miniconda)
- 关键包：scikit-learn, numpy, matplotlib, scipy, joblib
- 本地推理：LM Studio @ http://127.0.0.1:1234/v1
  - openai/gpt-oss-20b（升级/生产/证据门主模型）
  - qwen/qwen3-8b（identity judge / 备用）
  - google/gemma-4-e4b（加载失败已记录）
  - text-embedding-nomic-embed-text-v1.5（嵌入）
- 公网网关：http://218.197.140.7:3001/v1（仅独立评价 Judge A 用途）

## 独立评价 Judge
- Judge A = Qwen3.6-35B-A3B @ 218.197.140.7:3001
- Judge B = gpt-5.6-luna @ localhost:57882
- Judge C（按任务固定）= Qwen3.5-122B(relation) / Qwen3.5-35B(scope) / qwen3-8b@LM Studio(identity)

## 数据库
- V2 源库：data/release_databases/red_culture_stkg_final_v2.sqlite（SHA-256 见 BASELINE_FREEZE_MANIFEST）
- V3_1 副本：final_submission_v3_1/data/repaired_release/（U1-U8 已落地）
- FINAL 库：final_release/database/red_culture_stkg_final.sqlite（待构建）

## 当前规模
- entities: ~30,899 ｜ assertions: 424,150
- 旧分层：strict 112,158 / contextual 268,047 / unresolved 43,945
- 语义门验证（5,000 诊断）：新 strict ESTIMATED 35,226 [33,744–36,708]
- 证据恢复：96.6% 可定位（D 类 2,106 真无支持）
- FINAL_TIERING_CHECKPOINT: 13,702+/105,053（后台队列运行中）

## 已完成实验（全部真实运行）
1. relation 三票语义评价（κ=0.541, strong 459/759）
2. scope 208 三票评价（κ=0.467, strong 110/187）
3. identity 600 三票评价（κ=0.406, strong 320/578）
4. 证据恢复 96.6% + 语义门 5,000 分层验证
5. 嵌入预测器升级（VAL mF1 +9.7pt, ECE 减半）
6. Risk Estimator 决策树（AUPRC 0.728, 独立参考训练）
7. 三路路由 + 质量预算曲线（0%→100%）
8. 模型无关路由证明（gpt-oss-20b + qwen3-8b 双模型）
9. 跨来源三切分稳健性
10. 冻结 TEST 消融（config 929c6a5）
11. STKG U1-U8 副本库落地（563 万 Allen 关系、382 空间层、72 PlaceVersion）
12. 120 页抽取召回诊断（Entity Recall 4.1%，96 页未消费）
13. 6 张出版级可视化

## 待完成（FINAL RELEASE 全部工作项）
见 FINAL_METHOD_SUMMARY.md 待完成节 + 本轮新增：
- 302,230 页全量 cheap screening
- 多通道候选生成（deterministic + production + local LLM）
- Recall DEV/TEST 新基准（150-250 页 each）
- 105k 语义门队列完成 → processing_status/semantic_tier 分离
- FINAL DB 构建 + STKG U1-U8 重跑
- STKG competency benchmark K0-K3
- FINAL_NUMBERS.json 自动生成
- RELEASE_LOCK.json + Git tag stkg-final-release-2026
