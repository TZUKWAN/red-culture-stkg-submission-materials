# 归档：Judge A 槽位 Qwen3.5-122B-A10B 记录（2026-09-08）

该网关渠道自 2026-09-07 13:25 UTC 起持续挂起（连接接受但 >5 分钟无响应，重试全部超时），
经用户同意将 Judge A 槽位更换为 Qwen3.5-35B-A3B（同 Qwen 家族、同网关、与 B3 盲 LLM
Qwen3.6-35B-A3B 为不同模型实例）。本目录归档旧模型全部原始记录，**不参与任何共识聚合**，
仅作审计证据保留：

- entity_type/A.jsonl：339 OK（10:03–13:25 UTC）+ 43 TRANSPORT_ERROR（14:34–15:23 UTC，渠道劣化期）
- scope_adjustment/A.jsonl：空文件（渠道已挂起时创建，无任何记录）

协议修订见 audit/03_IMCR_PROTOCOL.md §12。共识构建按文件 globs 只读取各任务目录，
本目录不在任何任务目录下，不会被聚合。
