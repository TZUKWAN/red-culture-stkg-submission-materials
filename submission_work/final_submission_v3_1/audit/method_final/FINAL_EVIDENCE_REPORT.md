# FINAL EVIDENCE REPORT — 全库逐条 MEASURED 重分层（三概念分离）

- 生成时间：2026-09-14T01:49:10+08:00｜方法版本：`final-tiering-v1`（全自动、无人工、seed 写死、checkpoint 可复现）
- 模型：`qwen3.5-4b`（LM Studio 本地，temperature=0，`lmstudio_provider.chat_json`，workers≤6）
- 冻结 policy：`FINAL_TIERING_POLICY.json`（先冻结成 JSON 再应用；LLM prompt/证据组装 = `run_evidence_semantic_gate.py` 同款）
- 重分层对象：112,158 条 strict 断言（STRICT_ALIGNMENT 全量，数据库只读，不建新库）
- 上游统计估计（对照基线）：分层抽样 5,000 条 → new strict ≈ **35,226** [33,744–36,708]（外推，非逐条）

## 0. 结论速览

- MEASURED（gate_method = rule / llm，逐条确定计数）：**strict 31,067 ／ contextual 31,282 ／ unresolved 49,809**
- 保守持留（LLM 队列未及，CONTEXTUAL 持留、不计入 MEASURED）：**0**
- FINAL_TIERING.csv 全表三层计数：STRICT 31,067 ／ CONTEXTUAL 31,282 ／ UNRESOLVED 49,809
- 与统计估计对照（同宇宙 110,052 条，排除 recovery_D）：估计 35,226 vs 实测 **31,067**（差 -4,159.0）。LLM 队列已清空，MEASURED 即全库确定数。

## 1. 三概念分离（指令 §6 的 A/B/C 三个数，全部实测确定数）

| 概念 | 定义 | 分子 | 分母 | 数值 |
| --- | --- | --- | --- | --- |
| A. lineage completeness | 有原生溯源指针（provenance evidence_ids≥1，bucket ∈ aligned/mismatch_with_evidence）的 strict 断言占比 | 50,161 | 112,158 | **44.72%** |
| B. evidence localization rate | 证据文本可定位（direct 指针或恢复类 A/B/C；仅 recovery_D 不可定位）的占比 | 110,052 | 112,158 | **98.12%** |
| C. semantic support rate (measured) | 已测（rule/llm）且可定位断言中，证据在语义上支持（FULLY / 安全规则 / PARTIAL-strict-predicate）的占比 | 31,067 | 110,052 | **28.23%** |

三者正交：A 说"有没有溯源链"，B 说"证据文本能否取回"，C 说"取回的证据是否真支持"。
A ≠ B：61,997 条无原生指针，但其中
59,891 条靠词法恢复（A/B/C）找回了证据文本。
B ≠ C：可定位 ≠ 支持——recovery_C 层（40,345 条）定位成功但 DEV 抽样语义支持率仅约 14.8%。

## 2. 各层重分层结果（rule/llm 已测 vs 保守持留）

| 层 | 层规模 | 已测（rule+llm） | 已测 STRICT | 已测占比 |
| --- | --- | --- | --- | --- |
| aligned | 44,025 | 44,025 | 18,597 | 100.0% |
| mismatch_with_evidence | 6,136 | 6,136 | 71 | 100.0% |
| recovery_A | 2,841 | 2,841 | 1,444 | 100.0% |
| recovery_B | 16,705 | 16,705 | 7,182 | 100.0% |
| recovery_C | 40,345 | 40,345 | 3,773 | 100.0% |
| recovery_D | 2,106 | 2,106 | 0 | 100.0% |

按 gate_method：rule（确定性快路径 + 安全规则）= {"UNRESOLVED": 2106}；
llm（qwen3.5-4b 五档判定）= {"UNRESOLVED": 47703, "CONTEXTUAL": 31282, "STRICT": 31067}。

LLM 五档合并分布（DEV 5,000 + 本队列 checkpoint 105,081 条）：
{"UNSUPPORTED": 47576, "INSUFFICIENT": 3578, "FULLY_SUPPORTED": 23257, "PARTIALLY_SUPPORTED": 35514, "CONTRADICTED": 127}

## 3. 确定性快路径与安全规则学习（DEV 3/4 学、1/4 验）

- 快路径（无 LLM）：recovery_D → UNRESOLVED（§5.3 NO_EVIDENCE 档）；命中安全规则 → STRICT（免 LLM）。
- 安全规则接受标准：在 DEV train（3/4，seed=20260910）上经验支持率 ≥95%
  且 Wilson 95% 下界 ≥90%（n≥30），并必须在 DEV test（1/4）
  上同样达标（n≥15）——双验证通过才可免 LLM。
- 全部候选规则的 train/test 支持率、覆盖率与接受结论见 `FINAL_TIERING_RULES.json`；
  本回合应用的安全规则：

（本回合无规则同时通过 train/test 安全标准——没有免 LLM 的 STRICT 判定，除 recovery_D 规约外全部走 LLM。）

## 4. Predicate PARTIAL policy 表（§5.3，冻结于 policy JSON 后应用）

FULL 占比 ≥70% 的 predicate，PARTIAL 判定可入 STRICT，否则 CONTEXTUAL
（full+partial n<10 默认 CONTEXTUAL）。入 STRICT 的 predicate：
**active_at、captured、collaborated_with、contacted、created、died_at、dispatched、fought_at、guided、opposed、responsible_for、supported、worked_at**
（完整表：`FINAL_TIERING_POLICY.json.predicate_policy_table`。）

## 5. LLM 队列执行情况（如实报告）

- 优先级（错放风险高的层先跑）：mismatch 全量 → recovery_B 全量 → recovery_A 全量 →
  aligned 固定 seed 补验（n=3000，seed=20260910）→ aligned 余量 → recovery_C；
- checkpoint：`FINAL_TIERING_CHECKPOINT.jsonl` 每 500 条 fsync，断点续跑；
  CALL_FAILED/UNPARSEABLE 记录保留并在续跑时自动重试；
- 完成度：
  - aligned: 44,025 / 44,025（100.0%）
  - mismatch_with_evidence: 6,136 / 6,136（100.0%）
  - recovery_A: 2,841 / 2,841（100.0%）
  - recovery_B: 16,705 / 16,705（100.0%）
  - recovery_C: 40,345 / 40,345（100.0%）
  - recovery_D: 2,106 / 2,106（100.0%）

## 6. 局限性

1. 单一本地判定模型（qwen3.5-4b，temperature=0），PARTIAL/UNSUPPORTED 边界存在模型主观性（同上游 gate）。
2. 证据拼接 ≤800 字/3 条，超长尾部截断，可能低估 FULLY_SUPPORTED。
3. 队列未清空时，MEASURED 为已完成口径的确定数（非估计）；未测行保守持留 CONTEXTUAL，
   不外推补齐；持留清单由 `gate_method=none` 精确给定，续跑后重放 finalize 即可更新。
4. 安全规则只授予 STRICT，不授予任何负判定；UNRESOLVED 全部来自 LLM 负档或 recovery_D 规约。
5. C（semantic support rate）以已测可定位集合为分母，逐条判定随队列推进单调更全，但每一条都是实测。

## 7. 可复现性

- seed 写死：rules_split=20260910，aligned_supplement=20260910；输入 sha256 见
  `FINAL_TIERING_SUMMARY.json` 与 `FINAL_TIERING_POLICY.json`；
- 数据库只读（mode=ro），不建新库；本阶段不物化新库（下一阶段）；
- 重放路径：`features → learn → policy → queue(可断点续跑) → finalize`；
- LLM 队列判定输入/输出逐条落盘（assertion / evidence_text / decision / confidence /
  evidence_quote / explanation / latency），可第三方逐步复查。
