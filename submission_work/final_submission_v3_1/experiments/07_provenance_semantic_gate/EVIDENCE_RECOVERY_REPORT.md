# Evidence Recovery Audit — no_evidence 断言四类判定与自动恢复

- 生成时间：2026-09-10T02:52:42+08:00
- 方法版本：`evidence-recovery-v1`（全自动、确定性、无人工；数据库只读）
- 输入：`STRICT_ALIGNMENT.csv`（bucket=no_evidence，共 61,997 条；sha256 前 8 位 `e7426bd3`）
- 产物：`EVIDENCE_RECOVERY.csv` / `EVIDENCE_RECOVERY_SUMMARY.json` / 本报告
- 总耗时：0.2 分钟（13 s）

## 1. 背景

strict 层 112,158 条断言词法对齐后 61,997 条落入 no_evidence
（fact → provenance.evidence_ids_json 为空）。"指针为空"不等于"没有原文"：
上游集成管线中证据以 `up.fact_evidence`（FACT→EVD 绑定）、`up.topic_fact_candidates`
（metadata 证据引文）等形式存在，部分绑定在发布库裁剪/聚簇去重中丢失。
本次审计对每条 no_evidence 断言判定其原文可恢复性并定位候选证据。

## 2. lineage 列勘察（步骤 1 结论）

对 `research_assertion_provenance` 采样核查（含全部 no_evidence 行全量统计）：

| 列 | no_evidence 行的实际形态 |
| --- | --- |
| source_member_id | `FACT-*` 68,617 行 + `TOPICFACT-*` 2,373 行 |
| legacy_candidate_ids_json | `["LEG-*"]`（68,617 行非空） |
| native_record_ids_json | `["KGREL-*"]`（68,617 行非空） |
| evidence_ids_json | 全部 `[]`（0 条悬空指针） |
| source_record_ids_json / metadata_json | 基本为 `[]` / `{}`；TOPICFACT 行 metadata 内含 evidence_quote |

可回溯键：source_member_id → `up.fact_evidence`；LEG →
`up.fact_cluster_members` → canonical FACT → `up.fact_evidence`；
KGREL → `up.legacy_fact_candidates.native_record_id` → LEG；TOPICFACT →
`up.topic_fact_candidates.metadata_json.evidence_quote`。

## 3. 四类定义与判定规则

| 类 | 定义 | 自动判定条件（按优先级） | match_mode |
| --- | --- | --- | --- |
| A | 证据真实存在但 ID 映射丢失 | lineage 命中（fact_evidence/聚簇头/TOPICFACT 证据或引文）或 direct_source 命中（同 (subject,predicate,object) 兄弟 provenance 行或 sem.v2_assertion_scopes 同三元组事实带证据） | lineage / direct_source |
| B | 有 lineage 但 evidence_registry 绑定失败 | 词法双名同现于**同一**证据行（强命中） | lexical_both (same_row) |
| C | 原文存在但 quote/span 未定位 | 词法双名命中但**异行**（split），或仅单名命中（+time_raw 优先排序，弱命中） | lexical_both (split) / lexical_subject / lexical_object |
| D | 真的无原文支持 | 全链路无命中 | none |

B/C 边界按命中强度记录（same_row 强 / split·single 弱），不强行区分，
与任务规约一致。所有词法命中均为 FTS trigram/滑窗检索后的**已验证子串命中**
（取回原文逐条复核），仅作恢复定位，不当作语义支持。

## 4. 计数结果

| 类 | 条数 | 占比 | 含义 |
| --- | --- | --- | --- |
| A | 2,841 | 4.6% | strict 候选可修复（证据直接回接） |
| B | 16,705 | 26.9% | strict 候选可修复（绑定重建） |
| C | 40,345 | 65.1% | strict 候选可修复（弱恢复，需复核样例） |
| D | 2,106 | 3.4% | 降级（无可定位原文） |

- 恢复率（A+B+C）/N = **96.6%**（59,891/61,997）
- match_mode 分布：{"lexical_both": 37276, "lexical_subject": 14801, "lexical_object": 4973, "none": 2106, "direct_source": 1455, "lineage": 1386}
- 命中强度分布：{"same_row": 16705, "single": 19774, "split": 20571, "no_hit": 2106, "sibling_triple": 1455, "topic_metadata_quote": 1386}
- 路径分解：`up.fact_evidence`/聚簇头 lineage（registry_ids）
  0 条；
  TOPICFACT metadata 引文 1386 条；
  同三元组兄弟 direct_source 1455 条。

关键发现：no_evidence 桶内 `up.fact_evidence`（FACT→EVD）与 LEG/KGREL→
canonical-FACT 聚簇头路径 **0 命中**——这批断言在上游集成库中即从未建立
证据绑定（并非发布裁剪时丢失）；A 类完全来自 TOPICFACT metadata 引文与
同 (subject,predicate,object) 兄弟事实的直接证据，其余可恢复空间由词法层
定位（B 同行双名强定位 / C 弱定位）。

## 5. 对 P0-9 语义门重分层的含义

- **A/B/C 共 59,891 条 = strict 候选可修复**：已定位到候选证据原文
  （A 有确定 ID/引文，B 同行双名强定位，C 弱定位）。P0-9 重分层时这些断言
  不应再按 no_evidence 处理，可带候选证据进入语义验证（LLM 只需确认
  语义支持，而非从零检索）。
- **D 共 2,106 条 = 降级**：三条链路均无可定位原文，按 GOAL P0-9 规约
  从 strict 候选降级（不再作为高置信发布断言）。
- C 类为弱恢复：单名命中仅表示原文可能相关，判定本身仍是自动规则；
  SUMMARY.json 已附 50 条随机样例（seed=20260907）供后续人工可读性抽查，
  抽查不改变本审计的自动判定。

## 6. 约束与可复现性

- 三个数据库全部 `mode=ro` 只读打开；无任何写库操作。
- evidence_registry（1,073,648 行）仅流式/分块访问：FTS trigram 索引查询 +
  2 字名一次滑窗扫描（rowid 上限 3000/名），未全量载入文本。
- 每条断言候选证据上限 5 条；排序全部确定性（rowid / evidence_id 字典序）。
- 分块 checkpoint：`EVIDENCE_RECOVERY_CHECKPOINT.jsonl`，可中断续跑
  （本次执行已从 checkpoint 续跑）。
- 随机样例 seed=20260907；输入 CSV sha256 已记录于 SUMMARY.json。
