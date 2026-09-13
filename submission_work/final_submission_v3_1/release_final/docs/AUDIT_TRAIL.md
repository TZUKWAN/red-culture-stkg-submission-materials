# AUDIT_TRAIL — 最终发布前的全部修复（按时间序，均有机器留痕）

| # | 时间 | 问题 | 根因 | 修复 | 影响 | 独立验证 |
|---|---|---|---|---|---|---|
| 1 | 09-12 | 队列实际用 gpt-oss-20b，qwen 仅 58 条 | 启动命令未传模型，provider 默认旧模型 | DEFAULT_MODEL=qwen3.5-4b；fallback 置空；checkpoint 按模型过滤 | 105,083 条重跑 | checkpoint model 分布 |
| 2 | 09-12 | qwen3.5 思考无法关闭 | 兼容端点忽略 chat_template_kwargs | 原生 /api/v1/chat + reasoning="off" | 全部判定 | 空闲探针 reasoning_output_tokens=0 |
| 3 | 09-12 | 畸形 JSON 炸整个队列 | extract_json 抛裸 JSONDecodeError | 转 LMStudioError → CALL_FAILED 可重试 | 稳定性 | 队列零崩溃 |
| 4 | 09-12 | 系统卡死（16GB 显存溢出） | 6 workers × 4 KV 槽 × 8192 超显存 | workers=2 + 并行槽 2（后按稳定性放宽） | 吞吐换稳定 | 长跑无冻结 |
| 5 | 09-13 | 6 成判定 CALL_FAILED | 换并发后输出分布漂移，字符串内未转义引号 | 解析层确定性转义修复（不改语义） | 失败率 60%→1.2% | 重放对账 0 差异 |
| 6 | 09-13/14 | LM Studio 服务挂→队列空转 | 服务进程死亡，模型未自动恢复 | 服务唤醒 + 模型重载；看门狗守护 | 45 条重测 | RUN.log |
| 7 | 09-14 00:5x | 剩 18 条顽固解析失败 | 漏逗号/漏右括号/引号被吞 | schema 兜底提取（枚举不匹配即失败，不猜） | 17/18 救回，salvaged 留痕 | salvaged=17 审计 |
| 8 | 09-14 00:1x | pending_hold=28 | DEV 阶段 28 条 CALL_FAILED 被当"已测"跳过 | 计划只认有效五档判定；28 条重测全成 | 112,158 全测 | pending_hold=0 |
| 9 | 09-14 | 报告/文档模型名错配 | 模板硬编码 gpt-oss-20b | 模板动态化（DEFAULT_MODEL）；历史报告保留原文 | FINAL_EVIDENCE_REPORT 等 | grep 复扫 |
| 10 | 09-14 | 生产库 tier 陈旧（strict=2,063） | v2 基座未物化最终分层 | PHASE4 重建：4 表事实级刷新 + frames 聚合重算 + 陈旧派生台账 | 全库三层落库 | FINAL_DB_MANIFEST 硬审计全零 |
| 11 | 09-14 | cfs 表 CHECK 约束拒绝 unresolved | 未决事实不能当文化形态支持 | 该类支持行删除并如实计数（31,827 行） | 约束满足 | manifest 记录 |

## 不可篡改锚

- 基线快照：`audit/00_BASELINE_SNAPSHOT.json`（e1dd933，全文件 SHA256）
- 判定档案：`FINAL_TIERING_CHECKPOINT.jsonl.gz`（127,633 条，127,633=17,552 历史 + 110,081 生产含重试）
- 一键复核：`reproduce/replay_all.py` → `audit/REPLAY_REPORT.json`
