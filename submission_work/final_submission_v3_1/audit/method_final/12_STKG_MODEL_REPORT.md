> [HISTORICAL 2026-09-16] 历史实验存档：本报告的数字属于**当时局部实验**，不是全库结论；最终权威数字见 AUTHORITATIVE_RESULTS.md。

# 12 · 时空知识图谱（STKG）身份与语义审计报告

- 审计对象：`data/release_databases/red_culture_stkg_final_v2.sqlite`（sha256 `a199d736…9ee7`）+ ATTACH `red_culture_stkg_semantic_v2.sqlite`（sha256 `fbfb6529…bb377`，与 build 元数据一致）+ ATTACH 上游 `red_culture_semantic_integration_v1.sqlite`
- 审计方式：只读（`mode=ro` URI），连接方式与 `build_provenance_alignment.py` 的 `connect_final() + attach_integration()` 完全一致
- 审计脚本：`code/experiment_pipelines/audit_stkg_identity.py`（复现命令：`python audit_stkg_identity.py`，输出机器可读 JSON，含全部证据 SQL 与结果）
- 审计日期：2026-09-09
- 主库对象：44 表 + 17 视图（61 项）；sem 库：23 表 + 1 视图（24 项）；全部表名见附录 A

---

## 结论先行：系统现在算不算 STKG？

**不算完整的时空知识图谱。** 它目前是一个**证据链完备的"带时间戳的历史事实断言库 + 事件/文化状态聚合层"**：

- **时间**作为事实身份维度已真实生效（同一 s-p-o 在不同时间下是不同 fact_id，STKG-1），时间区间**表示**字段存在（time_start/end/precision），但没有任何区间-区间关系代数（STKG-4）；
- **空间**维度基本不成立：除研究区脚手架（13 条省→流域段）外没有政区层级、没有历史沿革、没有地名版本（STKG-3 是唯一 MISSING 项）；
- **Event 帧与 CultureState 聚合层**是真实的一等结构（角色、断言链、时空胞、观察层级齐备，STKG-6 全链路可回溯到证据），但事件帧之间没有前驱后继（STKG-2）；
- **role-owner 机制**schema 与上游均存在、指向正确，但覆盖率仅 1–2%（STKG-5）；
- **演化层**设计上明确防住了"时间先后冒充因果"（`causality_status` 强制 `not_inferred`、候选全部由显式谓词触发），但 11,532 个 CultureState 仅产出 **4 条**发布转换（STKG-7）。

判定汇总：**SATISFIED 1 项，PARTIAL 5 项，MISSING 1 项。**

---

## 判定总表

| # | 要求 | 判定 | 一句话证据 |
|---|------|------|-----------|
| STKG-1 | 时空参与事实身份 (s,p,o,τ,λ) | **PARTIAL** | 424,150 断言中 59,526 组同 s-p-o 的 time_raw 不同、各自独立 fact_id（其中 883 组为多个非空时段）；但身份键未声明未约束：仍有 655 组 (s,p,o,time_raw,place_raw) 完全相同却并存两个 fact_id |
| STKG-2 | Event 一等对象 | **PARTIAL** | 28,065 个 event frame 聚合了角色（54,033 条）、断言链（140,830 条）、时空胞（7,067 个）；但帧间无前驱后继（只有 499 条 part_of/influenced），无帧级 provenance，27,369/28,065 帧无观测时间 |
| STKG-3 | 空间语义（located_in/政区沿革/PlaceVersion） | **MISSING** | 唯一结构化层级是 13 条 `within_basin`（研究区脚手架）；located_in 只是 466 条严格层零散断言（无有效期、有错挂噪声）；全库无 jurisdiction/succession/place_version 表，实体表无 valid_from/valid_to，上游 212,945 实体 valid_from/valid_to 全空 |
| STKG-4 | 时间语义（区间关系代数） | **PARTIAL** | 区间表示字段在（77,930/424,150 断言有 time_start/end；阶段成员 contained 61,137 + cross_stage_interval 34,221）；但 before/after/overlaps/starts/ends/contains 等**区间关系表不存在**（全库模式扫描 = 0），时序只能靠 stage_order |
| STKG-5 | role-owner 机制 | **PARTIAL** | 机制存在且指向正确（time_owner→Person 4,668/Event 910；space_owner→Event 7,673；anchor→Place 62,415/AdministrativeRegion 42,894）；但 time_owner 全库覆盖 5,672/424,150（1.3%），space_owner 8,060（1.9%），time_role='unknown' 占 81.6% |
| STKG-6 | CultureState | **SATISFIED** | 11,532 个状态承载 subject+form+stage+region+basin+observation_tier（trusted 958/asserted 1,873/context 8,701）；回溯链验证通过：state→support(196,547)→fact→provenance→**35,423 个**不同 evidence_id（库内共 1,073,648） |
| STKG-7 | 演化关系 | **PARTIAL** | 设计有据：候选全部由 10 条显式谓词规则触发、无同主体纯时序候选（=0）、`causality_status='not_inferred'` 强制、build 元数据自述"不从时序推断因果"；但 159 候选仅 **4 条**发布（全部 memorialized_as），上游 evolution_transitions 表 0 行 |

---

## 逐项审计详情

### STKG-1 时空参与事实身份 — PARTIAL

**问题**：断言身份是否为 (s,p,o,τ,λ) 四元组——同一 s-p-o 在不同时间/空间下是不同事实状态——还是 time/place 只是附加属性？

**真实查询结果**（`research_assertions`，主库）：

| 查询 | 结果 |
|------|------|
| 总断言数 / 去重 (s,p,o) 数 | 424,150 / 325,286 |
| 出现 >1 次的 (s,p,o) 组 | 95,230 |
| 其中 time_raw 不同的组（含 null-vs-值） | **59,526** |
| 其中存在多个**非空**不同 time_raw 的组（真正多时段） | **883** |
| 同 (s,p,o,time_raw) 但 place_raw 不同的组 | 37,057 |
| (s,p,o,time_raw,place_raw) **完全相同**却分开的组 | **655**（655 组各含 2 条） |
| provenance 行数 / 覆盖 fact 数 | 466,312 / 424,150（每 fact 至少 1 条，kind: integrated_fact_member 453,955 + integrated_topic_fact_member 12,357） |

**多时段实例真实存在**，例如（非合并、各自独立 fact_id）：

| subject | predicate | object | time_raw | time_start~end | place |
|---|---|---|---|---|---|
| 杨匏安 | participated_in | 五卅运动 | 1925年5月-1925年5月 | 1925-05-01 ~ 1925-05-31 | 香港 |
| 杨匏安 | participated_in | 五卅运动 | 五卅 | 1924-01-01 ~ 1927-07-31 | 上海 |
| 杨成元 | participated_in | 长征 | 红军 | 1927-08-01 ~ 1937-07-06 | — |
| 杨成元 | participated_in | 长征 | 1935年3月-1935年3月 | 1935-03-01 ~ 1935-03-31 | — |

**判定理由**：
- 支持面：时间/空间确实参与事实实例区分——不同 time_raw/place_raw 的同 s-p-o 各持有独立 fact_id 与独立 provenance，没有被合并成一条"附加属性"；这满足了 STKG-1 的核心语义。
- 不足面：(1) 身份键是**事实上的**内容散列（upstream `canonical_fact_clusters.fact_signature` 为 sha256），schema 层**没有声明** (s,p,o,τ,λ) 唯一约束，导致 655 组五元组完全相同的"身份碰撞"并存；(2) 大量区分是"null-vs-值"的未调和变体（如 赵书俊 participated_in 六路围攻 一条无时间一条 1934年），缺一次身份调和；(3) τ/λ 只以字段形式存在，没有有效期语义（valid_from/valid_to）。

---

### STKG-2 Event 一等对象 — PARTIAL

**表清单**：final 库 event/time/space 相关表 9 张：`research_event_frames`、`research_event_assertion_links`、`research_event_roles`、`research_event_role_catalog`、`research_event_relations`、`research_event_spatiotemporal_cells`、`research_event_cell_support`、`research_first_observed_states`（事件相关）、`research_historical_stages`；相关视图 7 个（v_research_event_times / event_places / event_actor_roles / event_backbone_frames / event_backbone_assertions / event_occurrence_times / event_culture_roles）。sem 库另有 `v2_event_time_closures`、`v2_event_time_guard_overrides`、`v2_time_display`。全部表名见附录 A。

**真实查询结果**：

| 维度 | 结果 | 评价 |
|------|------|------|
| EventFrame 数量 | 28,065（strict_backbone 16,801 / context_only 10,960 / isolated 304） | 一等对象存在 |
| participants/roles | `research_event_roles` 54,033 条；participant 22,073、leader 10,604、organizer 3,910、commander 1,828、executor 1,318…；role_catalog 按 (predicate,endpoint) 受控 | ✅ 组织了参与者与角色 |
| assertions | `research_event_assertion_links` 140,830 条，覆盖 27,761 个事件 | ✅ |
| 时间区间 | 帧上 `observed_time_start/end` + status：**trusted 仅 95、asserted_candidate 601、none 27,369**；逐 fact 发生时间在 links（occurrence_time_*） | ⚠️ 97% 帧无帧级区间 |
| 空间足迹 | `research_event_spatiotemporal_cells` 7,067 个 (event,stage,region) 胞；`v_research_event_places` | ✅（胞粒度=阶段×省） |
| 前驱后继 | `research_event_relations` 仅 499 条：influenced 388 + part_of 111；按 before/after/precedes/follows/successor_of/predecessor_of 扫描 = **0** | ❌ 缺失 |
| provenance | 帧级 provenance 表不存在（扫描=0）；证据只挂 fact 级 | ❌ 缺失 |

**判定理由**：EventFrame 不是统计表——它通过 links/roles/cells 真实组织了参与者、角色、断言与时空足迹；但作为"一等对象"缺三件：帧间时序（前驱后继）、帧级区间（绝大多数帧无 trusted 时间）、帧级 provenance。

---

### STKG-3 空间语义 — MISSING

**真实查询结果**：

| 查询 | 结果 |
|------|------|
| 空间类实体 | Place 26,369、AdministrativeRegion 2,044、CulturalSite 254 |
| `research_region_hierarchy` 全部内容 | **仅 13 条，relation_code 全部 = `within_basin`**（省→长江流域段，derivation_method='frozen_study_region_definition'） |
| located_in / part_of 断言 | located_in：strict 466 + contextual 35 + unresolved 102；part_of：strict 111 + contextual 8。无时间有效期字段绑定 |
| located_in 质量（抽样） | 存在错挂噪声：`曹市区 located_in 农救会`（父节点是组织名）、`徽州 located_in 江西赤区`；无政区级别标注 |
| 历史政区/沿革/地名版本表 | 全库（main+sem+up）模式扫描 jurisdiction/succession/place_version/administrative = **0 张表** |
| 实体有效期字段 | `research_entities` 无 valid_from/valid_to（pragma=0）；上游 `up.entities` 212,945 实体 valid_from/valid_to 非空 = **0** |
| 同名同类型 Place 多实体（潜在版本素材） | 1,982 组，无任何时期维度区分 |
| sem 空间锚定 | `v2_assertion_spatial_anchors`：spatial_entity 105,382 / none 318,077 / raw_only 358；edge_type 仅 AT_PLACE/AT_NAMED_SITE |

**判定理由**：除 `canonical_space_anchor_id`（指向 Place/AdministrativeRegion 实体的 AT 边）之外，系统**没有**任何结构化的 located_in/part_of/contains 层级、没有历史辖区（historical jurisdiction）、没有行政区划沿革（administrative succession）、没有 PlaceVersion（同一地名不同时期的政区归属/范围版本）。`research_region_geometries` 提供的是当代省界几何（研究区画图用），不是历史地理。located_in 只是散落在断言层的 raw 事实，且带错挂噪声、无时间有效期。**系统性空间语义层缺失。**

---

### STKG-4 时间语义 — PARTIAL

**真实查询结果**：

| 查询 | 结果 |
|------|------|
| time_precision 分布 | unknown 346,220（81.6%）、period 41,118、year 23,947、month 12,865 |
| time_start/end 覆盖 | 77,930/424,150（18.4%）断言有显式区间；其中 start≠end 的区间形 75,458 |
| 阶段成员语义 | `research_assertion_stage_memberships` 95,358 条：contained 61,137、cross_stage_interval 34,221（仅两种"包含"语义） |
| **区间-区间关系表** | before/after/overlaps/during/starts/ends/time_relation/chronology/temporal_relation 模式扫描 = **0** |
| 事件发生时间 | time_role='event_occurrence' 断言 910 条；帧级 trusted 时间仅 95 帧 |
| 阶段轴 | `research_historical_stages` 13 阶段（有 time_start/end/stage_order） |

**判定理由**：时间**表示**字段齐备（start/end/precision + 阶段重叠区间），足以表示"点/区间+精度"，也能回答"哪些断言落在哪个阶段"；但**区间代数不存在**——没有 before/after/meets/overlaps/starts/ends/during/contains 任何关系表，事件先后只能靠 stage_order（13 档粗粒度）排序；event chronology（仅 696 帧有观测时间）、state duration（CultureState 无自身区间）、transition 时序均无法表达。**表示层 PARTIAL、代数层 MISSING。**

---

### STKG-5 role-owner 机制 — PARTIAL

**真实查询结果**（`research_assertions` 424,150 行全量；括号内为严格层 112,158 行）：

| 字段 | 覆盖 | 指向（entity_type 分布） |
|------|------|--------------------------|
| time_role | 8 个受控值；**unknown 346,220（81.6%）**，context_time 51,437、relation_validity 20,821、biographical 4,668、event_occurrence 910 | — |
| time_owner_id | 5,672（1.3%；严格层 984，0.9%） | Person 4,668、Event 910、Document 65、CreativeWork 17、Artifact 6、Institution 5 |
| space_role | 8 个受控值；unknown 318,515（75.1%） | — |
| space_owner_id | 8,060（1.9%；严格层 1,963） | Event 7,673、Person 373、其余个位数 |
| canonical_space_anchor_id | **105,635（24.9%）** | Place 62,415、AdministrativeRegion 42,894、Institution 294、CulturalSite 28 |
| link 层（140,830 条） | time_owner 971、space_owner 7,710、event_location 7,673 | 与断言层一致 |

**判定理由**：机制**确认存在且完整**：schema（`research_assertions` 8 个受控 role 值 ×2）、上游（`v2_assertion_scopes` 同款字段 + `v2_event_time_closures`/`v2_event_time_guard_overrides` 调解记录）、owner 指向均语义正确（时间归 Person/Event 所有，空间归 Event/Place 所有）。问题是**覆盖率**而非缺表：time_owner 1.3%、space_owner 1.9%、role 未知率 75–82%。空间锚定（anchor 24.9%）远好于 owner 归属。

---

### STKG-6 CultureState — SATISFIED

**真实查询结果**：

| 查询 | 结果 |
|------|------|
| 状态数 | 11,532；`state_key` 唯一约束（subject×form×stage×region×basin 组合） |
| 承载维度 | culture_subject（实体引用）+ culture_form_code + stage_code/label/order + region_id/province + basin_section_id **+ observation_tier 三档** |
| observation_tier | trusted_event_spacetime 958 / asserted_event_spacetime 1,873 / relation_context 8,701 |
| state_status | stable_multi_event 707 / explicit_single_event 2,370 / context_candidate 8,455 |
| 组织的 events | `research_culture_state_events` 13,336 条（state→event→cell_id，join cells 与 frames 全部命中） |
| 组织的 actors/roles | state_actors 689,950 条（带 role_code/event_id/fact_id）；state_roles 11,774（culture_subject 7,066、institutional_actor 3,898、transmission_medium 99…） |
| 回溯链 1（支撑） | state→`research_culture_state_support` 196,547 条→fact_id→`research_assertion_provenance`（join 238,810 行）→`evidence_ids_json`→**35,423 个**不同 evidence_id（上游 `evidence_registry` 共 1,073,648 条） |
| 回溯链 2（事件帧） | state→events→`research_event_spatiotemporal_cells`→`research_event_frames` join 成功 |
| 附加 | semantic_members 2,235（Spirit/ValueFacet）、value_facets 532、first_observed_states 6,723（明确标注"数据集首现≠历史起源"） |

**判定理由**：相关表**全部存在**且**承载了要求的全部维度**（subject+form+stage+region+events+observation tier），EventFrame→assertion→evidence 回溯两条链均以真实 join 验证通过。弱点（不影响本项判定，列入升级项）：state 自身无 time_start/end（时长只能等于 stage 区间），且 75.5% 的状态 tier 是 relation_context。

---

### STKG-7 演化关系 — PARTIAL

**真实查询结果**：

| 查询 | 结果 |
|------|------|
| 发布转换 | `research_evolution_transitions` **仅 4 条**，全部 `memorialized_as`（review_status 强制 'published_structural_explicit'） |
| 候选池 | 159 条；闸门分布：nontrusted_state 105、ambiguous_spatiotemporal_expansion 49、unique_explicit_spatiotemporal_match 4、unique_trusted_state_pair 1 |
| 证据边界 | `research_evolution_transition_support` 5 条（transition→candidate→supporting_fact_id，逐条可回溯断言）；`research_evolution_transition_candidates` 记录 derivation_kind 与 gate_reason |
| **因果边界** | `research_event_relations.causality_status` CHECK 强制 = `'not_inferred'`（499/499）；候选中同主体仅靠阶段先后者为 **0**；10 条规则全部要求显式源谓词（adapted_from / commemorates / inherited_from / originated_from_event / represented_in / symbolized_by / transmitted_by / disseminated_at / disseminates） |
| build 元数据自述 | limitations: *"no causality or evolution is inferred from sequence alone"* |
| 上游对照 | `up.evolution_transitions` = **0 行**、`up.evolution_transition_evidence` = **0 行**（上游演化表为空壳） |

**判定理由**：
- **没有把时间先后冒充因果**——这一点有硬约束证据（CHECK 约束 + 规则全部谓词触发 + 同主体纯时序候选为 0 + 自述 limitation），且有 evidence 边界字段（support→fact_id 全链可回溯）。
- 但演化**覆盖近乎为零**：11,532 个 CultureState 只有 4 条发布演化关系（且 105/159 候选卡在 nontrusted_state，49 条卡在时空歧义），上游演化表是空的。机制在、产出不在，故 PARTIAL。

---

## 附录 A：库表全清单

### 主库（final）44 表 + 17 视图

表：research_assertion_basins, research_assertion_provenance, research_assertion_regions, research_assertion_stage_memberships, research_assertions, research_basin_sections, research_build_metadata, research_creative_media_types, research_creative_work_media, research_culture_form_rules, research_culture_form_support, research_culture_forms, research_culture_state_actors, research_culture_state_events, research_culture_state_roles, research_culture_state_semantic_members, research_culture_state_support, research_culture_state_value_facets, research_culture_states, research_entities, research_entity_culture_forms, research_entity_members, research_event_assertion_links, research_event_cell_support, research_event_frames, research_event_relations, research_event_role_catalog, research_event_roles, research_event_spatiotemporal_cells, research_evolution_transition_candidates, research_evolution_transition_support, research_evolution_transitions, research_first_observed_states, research_historical_stages, research_region_geometries, research_region_hierarchy, research_relation_contract, research_scope_adjustments, research_spirit_value_links, research_stage_region_culture_metrics, research_study_regions, research_transition_rules, research_transition_types

视图：v_research_contextual_assertions, v_research_contextual_culture_states, v_research_creative_work_media, v_research_creative_works, v_research_culture_state_trajectory, v_research_event_actor_roles, v_research_event_backbone_assertions, v_research_event_backbone_frames, v_research_event_culture_roles, v_research_event_occurrence_times, v_research_event_places, v_research_event_times, v_research_published_evolution, v_research_stage_culture_metrics, v_research_strict_assertions, v_research_trusted_culture_states, v_research_unresolved_assertions, v_research_valid_spatial_assertions

### sem 库 23 表 + 1 视图

表：v2_assertion_scopes, v2_assertion_spatial_anchors, v2_build_events, v2_entities, v2_entity_identity_map, v2_entity_type_closures, v2_event_time_closures, v2_event_time_guard_overrides, v2_identity_resolutions, v2_label_votes, v2_metadata, v2_model_decisions, v2_model_failures, v2_model_tasks, v2_name_cluster_members, v2_name_clusters, v2_rule_resolutions, v2_semantic_conflicts, v2_source_baseline, v2_spatial_conflict_closures, v2_time_display（视图）, v2_entity_type_effective（视图）, sqlite_sequence

（上游整合库另 ATTACH 为 `up`，含 event_frames/event_roles/canonical_fact_clusters/culture_states/evolution_transitions（0 行）/evidence_registry(1,073,648) 等，用于证据回溯。）

## 附录 B：升级规格

见同目录 `12a_STKG_UPGRADE_SPEC.md`（按"今晚可实现"排序，标注 schema-only / 需要回填 / 需要重建）。
