# DATA_DICTIONARY — 最终库核心表与字段

库：`release_final/data/red_culture_stkg_final.sqlite`（只读使用）
全库断言宇宙 424,150；证据门宇宙（旧 strict 重分层宇宙）112,158。

## 身份与断言

### research_entities（152,979 行）
| 字段 | 说明 |
|---|---|
| entity_id | 规范实体 ID（IENT-*） |
| canonical_name / aliases_json | 规范名 / 别名数组 |
| entity_type | Person/Organization/Event/Place/Document/Concept/Institution/… |
| semantic_family | 语义族（SpatialEntity 等） |
| type_validation_status / confidence | 类型校验状态与置信 |

### research_assertions（424,150 行）— 主断言表
| 字段 | 说明 |
|---|---|
| fact_id | 断言 ID（IFACT-*，主键） |
| subject_id/object_id + *_name/*_type | 规范化三元组主体/客体 |
| predicate | 关系谓词（led/participated_in/active_at/…） |
| time_raw / time_start / time_end / time_precision / normalized_time_label / time_role | 原文时间表述与规范化时间 |
| place_raw / canonical_space_anchor_id | 原文空间表述与空间锚 |
| research_tier | **全库三层**：strict_semantic / contextual / unresolved |

## 证据语义门

### evidence_gate_tier（112,158 行）— 最终分层结果
gate_method（rule/llm）· semantic_support（五档/NO_EVIDENCE）· final_tier（STRICT/CONTEXTUAL/UNRESOLVED）

### gate_verdict_details（105,081 行）— 逐条判定明细（UI 证据抽屉数据源）
decision（五档）· confidence · evidence_quote（≤400 字引文）· explanation（模型理由原话）·
salvaged（解析兜底审计标志）· latency_s · model · judged_at

### release_derivation_ledger — 陈旧派生台账
table_name · columns · status(STALE_AS_OF_FINAL_TIERING) · reason · refresh_path

## 结构对象

| 表 | 行数 | 说明 |
|---|---|---|
| research_event_frames | 28,065 | EventFrame（事件帧：时间/地点/角色聚合，strict_assertion_count 已按最终层重算） |
| research_event_assertion_links | 140,830 | 帧-断言链接（fact 级 research_tier 已同步） |
| research_culture_states | 11,532 | CultureState（observation_tier 为陈旧派生，见台账） |
| research_culture_form_support | 46,002 | 文化形态支持（fact 级 tier 已同步；31,827 行 unresolved 支持已删） |
| research_place_versions | 72 | 历史政区名版本（覆盖有限，见 KNOWN_LIMITATIONS） |
| research_event_relations / research_place_relations | 499 / 382 | 事件/地点关系 |
| assertion_temporal_relations | 5,636,370 | 断言时序关系对（计算层） |
| research_assertion_provenance | 466,312 | 溯源指针（evidence_ids_json → 证据注册表） |

## 视图

v_research_strict_assertions（31,067）· v_research_contextual_assertions（299,329）·
v_research_unresolved_assertions（93,754）· v_research_event_* / v_research_culture_* 等 21 个。
