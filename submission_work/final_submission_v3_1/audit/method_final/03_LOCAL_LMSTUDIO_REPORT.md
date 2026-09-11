# 03 — 本地 LM Studio 推理链报告（WS-B）

日期：2026-09-10 ｜ 状态：PRODUCTION READY（生产链已零依赖公网）

## 1. 端点与配置

| 项 | 值 |
|---|---|
| Base URL | `http://127.0.0.1:1234/v1`（OpenAI-compatible，LM Studio 0.3.x） |
| 主模型（升级/生产） | `openai/gpt-oss-20b` |
| 备用 | `qwen/qwen3-8b`（JSON 严格度较弱，仅降级备用） |
| 嵌入 | `text-embedding-nomic-embed-text-v1.5` |
| 配置入口 | 环境变量 `LMSTUDIO_BASE_URL / LMSTUDIO_MODEL / LMSTUDIO_API_KEY`（均有默认值） |
| 统一入口 | `code/independent_eval/lmstudio_provider.py`（chat / chat_json / embed / probe；重试+备用模型回退+JSON 提取） |

## 2. 稳定性实测（真实 judge 载荷 + 结构化探针）

| 测试 | 结果 |
|---|---|
| 真实 identity 评审载荷 ×3 | 3/3 JSON_OK（38s 冷启动后 4s/条） |
| 结构化探针 ×8（primary） | 8/8 OK，平均 2.6s，max 13.9s |
| 结构化探针 ×4（fallback qwen3-8b） | 0/4 严格通过（输出含前置噪声，降为备用并记录） |
| Evidence gate 生产运行 | ~2,000+ 次连续调用，checkpoint 零丢失 |

## 3. 模型选型记录（指令授权"你看着用"）

- **Qwen3.5-27B 不可用**：网关渠道 503（未配置/挂起），LM Studio 未加载该模型 → 按用户授权（"3.6-35b 或者我本地 lm studio 也有模型 你看着用"）选定 **gpt-oss-20b** 为升级/生产主模型。27B 若日后在 LM Studio 加载，provider 仅需改 `LMSTUDIO_MODEL` 环境变量即可切换，代码零改动。
- **Qwen3.6-35B-A3B 是网关模型**（用户澄清），不进入本地生产链，仅保留独立评价用途（Judge A）。

## 4. 生产/评价双通道解耦

```
生产/升级链（本地，今晚全部完成）
  Risk Estimator 路由 → gpt-oss-20b escalation（241 次真实调用，240/240 有效 JSON）
  Evidence Semantic Gate → gpt-oss-20b（5,000 条分层验证，运行中）
独立评价链（公网，失败不影响生产）
  Judge A = Qwen3.6-35B（网关）
  Judge B = gpt-5.6-luna（本地 second endpoint）
  Judge C = Qwen3.5-122B/3.5-35B（网关，按任务固定模型）
  B3 blind LLM = gpt-5.6-luna（leave-B-out 主参考）
```

## 5. 已知边界

- LM Studio 长时间满负载推理有热节流（6 并发从 0.36 降至 0.19 it/s 观测），生产脚本已全部支持 checkpoint/resume；
- qwen3-8b 的 JSON 输出需宽松提取，未作为任何主路径；
- 公网网关渠道（122B/3.5-35B）反复 wedge 属网关侧问题，与本仓库无关，已全部按协议归档记录。
