# MODEL_MANIFEST — 模型角色清单

| 模型 | 角色 | 阶段 | 参数/规约 | 判定记录位置 |
|---|---|---|---|---|
| `qwen3.5-4b` | **最终全量证据语义门（生产 gate）** | 2026-09-12/13，105,081 判定 | 本地 LM Studio，原生 API，`reasoning="off"`，temperature=0，max_tokens=500 | `FINAL_TIERING_CHECKPOINT.jsonl.gz`（model=qwen3.5-4b） |
| `openai/gpt-oss-20b` | DEV 分层验证（5,000 抽样）与历史实验（升级实验/风险路由/质量预算曲线） | 2026-09 上旬，历史阶段 | 本地 LM Studio，temperature=0 | `EVIDENCE_GATE_VERDICTS.jsonl` 等（model=openai/gpt-oss-20b） |
| `qwen/qwen3-8b` | 独立质量审计 Judge B（盲评，不参与生产） | 2026-09-14 | 本地，原生 API，reasoning=off | `release_final/experiments/quality_audit/JUDGE_qwen_qwen3_8b_VERDICTS.jsonl` |
| `openai/gpt-oss-20b` | 独立质量审计 Judge A（盲评，不参与生产） | 2026-09-14 | 本地，temperature=0 | `.../JUDGE_gpt_oss_20b_VERDICTS.jsonl` |
| `text-embedding-nomic-embed-text-v1.5` | 语义特征/检索嵌入 | 全程 | 本地 | 衍生特征表 |

## 硬规约（生产链）

1. 生产 gate 主模型固定 `qwen3.5-4b`；**禁止静默回退**（provider 默认 fallback 为空）。
2. qwen3.5-4b 与 qwen3-8b 走 LM Studio 原生 `/api/v1/chat` 并显式 `reasoning="off"`
   （兼容端点无法关闭其思考通道）。
3. checkpoint 按模型字段严格过滤：旧模型记录仅作历史审计，不混入 finalize。
4. DEV 阶段 28 条 gpt-oss-20b CALL_FAILED 已由生产队列以 qwen3.5-4b 重测覆盖。

## Prompt 与解析

- 生产裁判 prompt：`configs/PROMPTS.txt`（含 SHA256）；解析层含未转义引号修复与
  schema 兜底提取，salvaged 使用逐条留痕（checkpoint `salvaged` 字段；
  最终库 `gate_verdict_details.salvaged`）。
- 兜底提取只信任显式出现的 `"decision": "<五档枚举>"`，缺失即 CALL_FAILED，绝不猜测。
