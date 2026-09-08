# 01 — 参考独立性与面板变更审计（v3_1）

日期：2026-09-08 ｜ 状态：已执行（本文件随运行更新）

## 1. P0-1：B3 盲 LLM 参考污染修复

### V3 的问题（实证）
- V3 中 B3 与 Judge B 同为 gpt-5.6-luna；primary strong 参考含 Judge B 票。
- 实证污染量级：B3 relation_contract 对 primary 一致率 0.939，对 leave-B-out 仅 0.286——
  同模型票贡献了约 65 个百分点的虚高。entity/provenance/scope/identity 同向膨胀。

### v3_1 修复（方案 A）
- **新 B3 = nvidia/nemotron-3-ultra-550b-a55b:free @OpenRouter**：不属于 judge 面板
  A/B/C 的任何模型实例（不同家族），保持相同冻结盲 payload、相同 schema、
  temperature=0、fresh 全量调用（2830 条，运行中）。
- B3 主评价参考 = 三 judge IMCR strong（无任何 nemotron 票，无自指）。
- 旧 gpt-5.6-luna 的 B3 记录保留于 V3（不删除、不再用于主评价）。

## 2. Judge C 槽位模型更换（OpenRouter 免费档失效）

- **事实**：2026-09-08 起 `minimax/minimax-m3:free` 从 OpenRouter 免费列表下架
  （/v1/models 不再返回，调用 HTTP 404，800 次尝试全部失败即证据）。
  其他免费档候选全部 HTTP 429（inkling 403 无权限；nemotron-super/ling/gemma 持续 429）。
  key 为免费档（is_free_tier=true，无付费额度）。
- **修复**：Judge C 槽位更换为 **Qwen3.5-35B-A3B @218.197.140.7:3001**（用户网关，
  实测 0.3s 延迟可用；与 Judge A 的 Qwen3.6-35B-A3B 为不同模型实例）。
- **新面板**：A=Qwen3.6-35B-A3B，B=gpt-5.6-luna，C=Qwen3.5-35B-A3B。
- **独立性核算**：三个不同模型实例、两个家族（Qwen、GPT），满足 GOAL 7.4
  ≥3 judge、≥2 家族、Qwen 非唯一 judge；B3=nemotron 与面板零交集，
  其主评价参考不含任何同模型票。
- **披露义务**：面板家族数由 3 降为 2（Qwen 双实例），论文报告面板时必须如实列出
  三个模型 ID 与家族； judge 一致性统计（κ 等）按实测值报告，不做家族加权补偿。
- **换型前后记录**：C 槽位 minimax 在 v4 任务上无有效输出（404 全失败），
  不存在需要弃用的部分完成记录；V3 中 minimax 的历史记录保留于 V3 raw_runs。

## 3. 换型影响与守恒检查

| 项 | V3 | v3_1 |
|---|---|---|
| Judge A | Qwen3.6-35B-A3B | 不变 |
| Judge B | gpt-5.6-luna | 不变 |
| Judge C | minimax-m3:free（已 404） | Qwen3.5-35B-A3B |
| B3 | gpt-5.6-luna（与 Judge B 同模型=污染） | nemotron-3-ultra（面板外） |
| B3 主参考 | strong（含同模型票=污染）/leave-B-out 双轨 | strong（无同模型票）单轨 |
| 家族数 | 3（Qwen/GPT/MiniMax） | 2（Qwen/GPT）——如实披露 |

## 4. 遗留风险
- OpenRouter 免费档容量波动大；若 nemotron 中途不可用，按协议记录后降速续跑，
  不换 B3 模型（避免再次重置）。
- 网关渠道（Qwen 系）此前两次 wedge；A/C 并发已控制在 4+2，若再 wedge 则
  降并发+探针续跑，历史按 _archived_judgeA_attempts 同规格归档。

## 5. B3 二次变更：nemotron 配额耗尽，回退方案 B（2026-09-08 晚）

- nemotron-3-ultra 免费档当日配额耗尽：重跑 404 次尝试全部 HTTP 429（06:04–14:05 UTC），
  仅 20 条 OK（凌晨配额窗口内完成）。实时探测持续 429，当日不会恢复。
- 按指令 §22（记录错误、保持独立性、继续）与 P0-1 方案 B：**B3 = gpt-5.6-luna**
  （2830 条真实 fresh 调用记录，与 v4 冻结 payload 完全同源），主评价参考 =
  **IMCR_REFERENCE_LEAVE_B_OUT**（剔除 Judge B 票后的 2-judge 共识）；
  对 primary（含 Judge B 票）的数字仅作自指敏感性附注，不再进入任何主表。
- 实证：entity_type 上 B3 对 leave-B-out 一致率 0.713（coverage 1.0），
  对 primary 为 0.988——同模型票膨胀约 27 个百分点，方向与 relation 一致。
- nemotron 的 404 次失败尝试记录保留于
  `experiments/02_selective_semantic/blind_llm_runs/entity_type.jsonl`（审计证据）。

## 6. Judge C 三次变更：3.5-35B 退化，改用 122B（2026-09-09）

- Qwen3.5-35B-A3B 在 v4 真实长载荷下退化至 0.1–2.6 条/分（间歇 5–15 分钟停顿），
  过夜仅推进 49 条；其 230 条记录归档于
  `raw_runs/_archived_judgeC_attempts/2026-09-08_qwen3.5-35b/`（不参与共识）。
- 实测 Qwen3.5-122B-A10B 同载荷 11s/条、上线后 14 条/分，**Judge C 最终 =
  Qwen3.5-122B-A10B**（与 Judge A 的 Qwen3.6-35B-A3B 仍为不同模型实例；
  面板家族数不变仍为 2，披露义务同 §2）。
- 预计 ~2h 完成 relation 800 + scope 208 + identity 600。
