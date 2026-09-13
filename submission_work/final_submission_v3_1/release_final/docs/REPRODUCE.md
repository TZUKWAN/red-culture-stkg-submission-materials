# REPRODUCE — 复现指南（两级）

## Level A：离线精确回放（审稿人主路径，必须可用）

**不重新调用任何 LLM、不需要网络、不需要 LM Studio / API key。**

```bat
cd release_final
python reproduce\replay_all.py
```

步骤与验收（全部 PASS 才算通过，输出 `audit/REPLAY_REPORT.json`）：

1. 归档 checkpoint gzip 与冻结 policy 的 SHA256 对照基线快照；
2. checkpoint 流式解析（127,633 条，畸形 JSON 必须为 0）；
3. 独立重放器按冻结 policy 从 checkpoint + dev 判定重建
   `FINAL_TIERING_REBUILT.csv`，与 `FINAL_TIERING.csv` 112,158 行逐行对账（差异必须为 0）；
4. 最终数据库 SHA256 与 `FINAL_NUMBERS.json` 记录闭环；
5. 最终库硬结构违规 = 0（pending / 无效 tier / CALL_FAILED 泄漏 / 孤儿 / 重复）。

参考耗时：本机（NVMe SSD，Python 3.13）约 8–10 秒。

## Level B：完整推理重跑（可选，方法可重复性验证）

从原始证据重新调用本地模型。要求：

- LM Studio + 模型 `qwen3.5-4b`（加载参数：`--gpu max --context-length 24576 --parallel 6`）；
- 冻结 prompt 见 `configs/PROMPTS.txt`（含 SHA256）；
- 生产入口：`submission_work/final_submission_v3_1/code/experiment_pipelines/build_final_tiering.py`
  的 `features → learn → policy → queue → finalize` 流水线。

**诚实声明**：temperature=0 不保证跨硬件/推理后端逐 token 一致。Level B 的目标是
方法可重复运行（同一输入 → 同一分布的判定），不是 bitwise 复现。每次请求的
模型 ID、参数、原始响应、解析状态全部落盘于 checkpoint，可逐步复查。

## 完整重建最终数据库

```bat
python release_final\code\build_final_db.py        # 源库哈希校验 → 复制 → tier 刷新 → 硬审计
python release_final\code\generate_final_numbers.py # 重新生成论文数字
```

顺序固定：build → numbers →（任何 UI/验证前）。库字节级哈希依赖操作序列，
复现时以本顺序产出的 `FINAL_NUMBERS.json.final_db_sha256` 为准。
