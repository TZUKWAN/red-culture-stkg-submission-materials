> [HISTORICAL 2026-09-16] 历史实验存档：本报告的数字属于**当时局部实验**，不是全库结论；最终权威数字见 AUTHORITATIVE_RESULTS.md。

# 06 — Selective Escalation 报告：盲升级 prompt 与真实调用统计（指令 §六/七）

日期：2026-09-09 ｜ 工作目录：`submission_work/final_submission_v3_1/`
实现：`code/experiment_pipelines/run_risk_routing.py`（`EscalationRunner` / `escalation_payload`）
留痕：`experiments/02_selective_semantic/risk_routing/ESCALATION_CALLS.jsonl`（逐条：payload 哈希、
prompt 哈希、模型、时延、decision/confidence、status）+ `SUMMARY.json.escalation`
测试：`code/tests/test_risk_routing.py::test_escalation_payload_blind_no_reference_leak` 等

---

## 0. 结论摘要

1. **真实升级调用 241 次目标（DEV 191 + VAL 50，即 5%–75% 各预算升级集的并集），成功 240，
   有效 JSON 决策 240/240（100%），唯一失败 1 例为确定性畸形 JSON（temperature=0 下三次重试
   同败，路由上回退基础预测并留完整错误记录）**。时延均值 14.0s、最大 20.5s
   （本地 LM Studio 单请求串行排队，openai/gpt-oss-20b，temperature=0，top_p=1）。
2. **升级模型质量（在高风险/困难段上）**：被升级且有独立参考的样本中，gpt-oss-20b 决策与
   IMCR strong consensus 一致率 DEV **0.873**（124/142）、VAL **0.857**（30/35）；同一批样本
   生产分类器一致率仅 DEV 0.225 / VAL 0.229（含无分类器候选样本）。翻转统计：DEV 80 错→对 /
   2 对→错；VAL 19 错→对 / 0 对→错。
3. **b=100% every-item 对照**不新增调用：使用 V3 既有 B3 全量行（IMCR_BLIND_LLM_RUNS.csv 的
   gpt-5.6-luna 真实盲 LLM 记录，382/382 全覆盖），every-item 一致率 DEV 0.972 / VAL 0.979。

---

## 1. 升级 prompt（与 run_judges_v31.py identity 模板同风格）

System（全文，`prompt_version=risk_routing.escalation.v1`，sha256=2c67d6cd…ba804）：

```
你是独立的历史知识图谱实体类型评审。给定一个实体的名称、别名、它在语料中参与的
关系上下文与文献节选，以及候选类型集合 candidate_types 和各类型定义 type_definitions。
你的唯一任务：依据给出的信息判断该实体最合理的类型。
约束：只允许从 candidate_types 列出的类型中选择一个；证据不足或不属于任何候选类型时
选择 OTHER；不得臆测输入之外的信息；输入中不含任何系统标签或参考答案，也不要猜测其存在。
输出且仅输出一个 JSON 对象：{"task_id":..., "decision":..., "confidence":0-1,
"evidence":[引用证据关键句], "reason_code":简短代码, "explanation":一句话理由,
"insufficient_evidence":bool}
```

User payload（白名单字段，逐字段固化于测试）：

```json
{"task_id": "<sample_id>", "entity_name": "<canonical_name>", "aliases": [...],
 "context_assertions": "...", "source_excerpt": "...",
 "candidate_types": [17 个 ENTITY_TYPE_LABELS],
 "type_definitions": {17 个类型的中文定义}}
```

### 泄漏防护核查

| 项 | 状态 |
|---|---|
| 生产标签（production_entity_type） | **不在** payload 任何字段中（`escalation_payload` 仅从 meta 白名单取值，生产类型被排除） |
| 独立参考标签 / 正确性信号 | 不在 payload；调用侧无法得知参考 |
| 路由元信息（r_hat / 是否被判为高风险） | 不在 payload（模型不知道自己是"被升级者"） |
| TEST split | `assert_no_test_samples` + `EscalationRunner._call` 内联断言（BLOCKED_TEST_SPLIT），本轮回路 0 次测试调用 |
| 留痕可审计 | 每条记录 payload_sha256 / prompt_sha256 / started_utc / latency / status；JSONL 断点续跑（status=OK 视为完成） |

---

## 2. 真实调用统计

| 项 | 值 |
|---|---|
| 目标调用（并集 5%–75%） | 241（DEV 191 + VAL 50） |
| status=OK | 240（JSONL 总记录 242，含冒烟与失败重试留痕） |
| decision 落在候选类型内 | 240/240 |
| 失败 | 1（ETV3-0041，DEV：`Expecting ',' delimiter` 畸形 JSON，temperature=0 下确定性复现；该样本在各预算路由中回退基础预测，`final_source=base_prediction_fallback`） |
| latency | 均值 14.0s / 最大 20.5s（LM Studio 本地服务单请求排队；与 03_LOCAL_LMSTUDIO_REPORT.md 的"热身后 ~4s/条"一致量级，多 worker 并发受服务端串行化限制） |
| decision 置信（模型自报） | 均值 DEV 0.914 / VAL 0.888 |
| 决策分布（节选） | Place/CulturalSite/SocialGroup/Position/TimePeriod/OTHER… 高风险段集中在 Place（地理名）与组织/群体类专名 |

---

## 3. 升级效果（被升级样本上的逐样本对照）

| split | 被升级样本 | 有参考 | 升级后一致率 | 基础分类器一致率（同样本） | 错→对 | 对→错 |
|---|---|---|---|---|---|---|
| DEV | 190 | 142 | **0.873** | 0.225 | 80 | 2 |
| VAL | 50 | 35 | **0.857** | 0.229 | 19 | 0 |

判读：risk 路由把升级预算精确投放在生产分类器 ~22% 一致率的困难层（无候选信号、低置信、
类别级高风险），gpt-oss-20b 在同一层达到 ~86–87% 一致率，净翻转约 +78（DEV）/ +19（VAL）。
升级决策替换原预测后，预算曲线的质量增益全部来自这批真实调用（见 07 报告）。

---

## 4. 与 b=100% every-item 对照（B3 既有行）的关系

- B3（gpt-5.6-luna，fresh 盲 LLM，382/382 全量）：every-item 一致率 DEV 0.972 / VAL 0.979，
  显著高于本地 gpt-oss-20b 的升级段 0.86–0.87 与全量外推水平。
- 因此 07 报告的质量-预算曲线中 75%→100% 的陡降是**模型切换**（本地 20B → 云端盲 LLM 记录）
  的结果，不代表本地升级模型的边际质量；07 报告另给 b≤75% 单模型段的 knee 诊断。

---

## 5. 复跑与断点

- `python run_risk_routing.py --workers N`：JSONL 缓存优先，仅对无 OK 记录的样本发新调用；
  `--skip-escalation` 纯分析模式；`--limit-escalation K` 冒烟模式。
- 本轮最终 artifacts 生成于缓存完备状态（fresh_calls_made=238+1 重试；新增调用 0）。
