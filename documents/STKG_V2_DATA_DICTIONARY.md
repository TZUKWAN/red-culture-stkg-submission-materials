# 长江流域红色文化时空知识图谱 V2 数据字典

更新时间：2026-07-15  
最终数据库：`derived/red_culture_stkg_final_v2.sqlite`

## 1. 通用约定

- 所有主键均为稳定字符串 ID，不使用节点名称作为主键。
- `source_*` 字段保存进入 V2 前的原始或来源侧值；无 `source_` 前缀的字段为 V2 规范值。
- `*_json` 必须是合法 JSON；数组去重并按确定性顺序存储。
- 未知值使用 `NULL` 或受控枚举 `unknown`，不使用“待定”“不详”等自由文本冒充规范值。
- 规范名称使用 Unicode NFKC、首尾空白清理和统一空白；别名保留在 `aliases_json`，不覆盖规范名称。
- 时间显示只允许 `YYYY年`、`YYYY年M月` 及其区间形式；缺失精度不得补造。
- 所有研究结论必须能够通过 `fact_id` 回到 `research_assertion_provenance`。

## 2. 规范实体

### `research_entities`

| 字段 | 类型 | 含义与约束 |
|---|---|---|
| `entity_id` | TEXT PK | V2 规范实体稳定 ID |
| `canonical_name` | TEXT | 规范中文名称，非空 |
| `entity_type` | TEXT | 最终实体类型 |
| `semantic_family` | TEXT | Agent、SpatialEntity、InformationObject、ConceptualEntity 等研究族 |
| `aliases_json` | JSON | 已确认别名、字、号、曾用名和规范变体 |
| `integrated_member_count` | INTEGER | 被合并的 V2 成员数量，至少 1 |
| `source_entity_count` | INTEGER | 来源实体数量，至少 1 |
| `type_validation_status` | ENUM | `validated` 或 `fallback_unresolved` |
| `confidence` | REAL/NULL | 类型或融合置信度 |
| `method_version` | TEXT | 生成规则版本 |
| `created_at` | TEXT | 生成时间 |

受控实体类型包括：Person、Event、Place、AdministrativeRegion、CulturalSite、Organization、Institution、SocialGroup、Artifact、Document、CreativeWork、Spirit、ValueFacet、Concept、Position、TimePeriod。

### `research_entity_members`

保存来源实体到规范实体的多对一映射。关键字段为 `source_entity_id`、`canonical_entity_id`、来源名称/类型、语义类型、映射状态、映射原因和来源别名。该表用于解释“蔡和森/蔡林彬/林彬”“毛泽东/毛润之”“邓小平/邓希贤”等名称为何指向同一规范实体。

## 3. 断言与来源

### `research_assertions`

| 字段组 | 字段 | 含义 |
|---|---|---|
| 标识 | `fact_id` | 整合断言稳定 ID |
| 来源端点 | `source_subject_id`, `source_object_id` | V2 映射前的实体 ID |
| 规范主语 | `subject_id`, `subject_name`, `subject_type` | 规范主语及最终类型 |
| 规范宾语 | `object_id`, `object_name`, `object_type` | 规范宾语及最终类型 |
| 关系 | `predicate` | 受控关系或 `raw:*` 保守原关系 |
| 原始时间 | `time_raw` | 来源时间文本，不覆盖 |
| 结构化时间 | `time_start`, `time_end` | ISO 日期边界，用于计算 |
| 时间精度 | `time_precision` | `unknown/year/month/period` |
| 时间显示 | `normalized_time_label` | 统一中文显示 |
| 时间语义 | `time_role` | 时间的语义角色 |
| 时间归属 | `source_time_owner_id`, `time_owner_id` | 来源侧和规范时间 owner |
| 原始地点 | `place_raw` | 来源地点文本，不覆盖 |
| 空间锚点 | `source_canonical_place_id`, `canonical_space_anchor_id` | 来源侧和规范空间实体 |
| 空间语义 | `space_role` | 空间角色 |
| 空间归属 | `source_space_owner_id`, `space_owner_id` | 来源侧和规范空间 owner |
| 行政字段 | `province`, `city`, `county` | 规范行政区字段 |
| 流域字段 | `basin_section` | 上游、中游、下游或空 |
| 语义状态 | `semantic_status` | 规则/模型裁决状态 |
| 置信信息 | `confidence`, `risk_tier` | 置信度和风险层 |
| 研究层 | `research_tier` | `strict_semantic/contextual/unresolved` |
| 来源规模 | `source_member_count` | 聚合来源成员数 |
| 时间戳 | `source_created_at` | 来源记录生成时间 |

`research_tier` 的使用规则：

- `strict_semantic`：受控关系、端点类型通过层级感知 domain/range、实体类型已验证；可用于严格分析。
- `contextual`：记录有效但关系为 raw、端点类型或语义强度不足；可用于检索和上下文，不用于强机制结论。
- `unresolved`：仍有语义冲突或信息不足；保留但不进入正式推断。

### 时间角色 `time_role`

| 值 | 含义 |
|---|---|
| `event_occurrence` | 事件发生时间，owner 必须是 Event |
| `relation_validity` | 任职、隶属、参与等关系有效期 |
| `biographical` | 人物生平时间，owner 必须是 Person |
| `creation_or_publication` | 作品、文献或物品创作/出版时间 |
| `commemoration_or_reception` | 纪念、传播、改编或接受时间 |
| `source_document_time` | 来源文档自身时间 |
| `context_time` | 只有上下文相关性，不归属强事件时间 |
| `unknown` | 无结构化时间或无法判断 |

### 空间角色 `space_role`

| 值 | 含义 |
|---|---|
| `event_location` | 事件发生地点，owner 必须是 Event |
| `relation_location` | 关系发生或有效地点 |
| `biographical_location` | 人物生平地点，owner 必须是 Person |
| `creation_or_publication_location` | 创作、出版或制作地点 |
| `commemoration_or_reception_location` | 纪念、传播或接受地点 |
| `context_location` | 只有上下文空间相关性 |
| `unknown` | 无可用空间锚点或无法判断 |

### `research_scope_adjustments`

保存最终实体身份/类型闭包造成的时空角色变化。字段同时保留来源角色、来源 owner、来源 owner 的规范映射、最终角色、最终 owner、调整原因和方法版本。该表只记录变化行，不覆盖来源语义库。

### `research_assertion_provenance`

每行将 `fact_id` 连接到来源成员、专题来源、来源表、来源记录 ID、原主客体/关系、旧候选 ID、原生记录 ID、证据 ID、SourceRecord ID 和完整元数据 JSON。一个断言可有多条来源；最终库不存在无来源断言。

## 4. 时间与空间维表

### `research_historical_stages`

字段包括 `stage_code`、`stage_order`、中文阶段名、起止日期、映射版本和快照版本。共 8 个冻结阶段。阶段成员关系位于 `research_assertion_stage_memberships`，跨阶段区间可连接多个阶段，不强压为单一阶段。

### `research_study_regions`

冻结长江流域与长江经济带叠加后的 13 省区市：青海、西藏、四川、云南、贵州、重庆、湖北、湖南、江西、安徽、江苏、上海、浙江。字段包括 `region_id`、省级全称、流域区段、顺序和定义版本。

### 其他空间表

- `research_basin_sections`：上游、中游、下游；
- `research_assertion_regions`：断言到省区市的多值成员关系；
- `research_assertion_basins`：断言到流域区段的多值成员关系；
- `research_region_hierarchy`：省区市到流域区段的层级；
- `research_region_geometries`：行政边界、坐标系、空间精度和显示中心。

`province/city/county` 不是唯一空间表示。跨省事实必须使用成员表，不能把斜线组合文本当作一个省份。

## 5. 事件层

### `research_event_frames`

| 字段 | 含义 |
|---|---|
| `event_id`, `event_name` | Event 实体 |
| `all_assertion_count` | 连接该事件的全部断言数 |
| `strict_assertion_count` | 严格断言数 |
| `controlled_role_count` | 受控事件角色数 |
| `occurrence_time_fact_count` | 合法事件发生时间断言数 |
| `trusted_time_fact_count` | 达到可信门槛的时间断言数 |
| `event_location_fact_count` | 合法事件地点断言数 |
| `stage_count`, `region_count` | 可观察阶段/区域数 |
| `observed_time_start/end` | 事件发生时间观察范围 |
| `observed_time_status` | `trusted/asserted_candidate/none` |
| `frame_status` | `strict_backbone/context_only/isolated` |

`research_event_assertion_links` 保存事件与所有断言的连接；`research_event_roles` 只保存通过类型和关系门禁的事件角色；`research_event_relations` 只保存显式 Event→Event 结构关系。人物任职时间、作品出版时间和上下文时间不会进入事件发生时间。

## 6. 红色文化形态与状态

### 七类文化形态

| 代码 | 中文 |
|---|---|
| `HistoricalPractice` | 历史实践 |
| `InstitutionalPractice` | 制度与组织实践 |
| `MaterialCulture` | 物质文化 |
| `DocumentaryCulture` | 文献文化 |
| `CreativeNarrative` | 文艺叙事 |
| `SpiritValue` | 精神与价值 |
| `MemoryTransmission` | 记忆与传播 |

`research_culture_form_rules` 保存类型/关系到文化形态的规则；`research_culture_form_support` 保存支持事实；`research_entity_culture_forms` 保存最终实体-形态-角色分配。Person、Place、Organization、Institution 和 CulturalSite 不会仅凭类型自动成为文化载体。

### `research_culture_states`

一个状态表示“某红色文化主体在某历史阶段、某省域/流域区段、以某文化形态被数据观察到”。核心字段为：

- 主体：`culture_subject_id/name/type`；
- 形态：`culture_form_code`；
- 时间：`stage_code/label/order`；
- 空间：`region_id/province_name/basin_section_id`；
- 观察层：`observation_tier`；
- 支撑：`supporting_fact_count`、`supporting_event_count`、`source_member_count`；
- 门禁：`has_controlled_explicit_support`、`state_status`、`state_key`。

观察层级：

- `trusted_event_spacetime`：事件时空达到可信门槛；
- `asserted_event_spacetime`：有事件时空断言但未达到可信门槛；
- `relation_context`：关系上下文观察，不等同于事件发生。

配套表：

- `research_culture_state_support`：状态到支持断言；
- `research_culture_state_events`：状态到事件；
- `research_culture_state_actors`：状态中的人物/组织角色；
- `research_culture_state_semantic_members`：精神、文献、作品等语义成员；
- `research_culture_state_value_facets`：通过显式 Spirit→ValueFacet 关系形成的价值内涵投影。

## 7. 演进层

### `research_evolution_transition_candidates`

保存所有规则生成的候选，包括候选类型、起止状态、支持事实、置信度、是否满足发布条件及拦截原因。候选保留不等于论文可直接使用。

### `research_evolution_transitions`

只保存通过发布门禁的显式结构关系。字段包括 `transition_id`、类型、起止状态、派生规则、审核状态、置信度和支持事实数。`research_evolution_transition_support` 将每条发布关系连接到候选和支持断言。

禁止规则：仅有时间先后、共现、相似或共同价值内涵时，不生成传播、继承、转化或因果关系。

## 8. 文艺作品媒介

### `research_creative_work_media`

| 字段 | 含义 |
|---|---|
| `entity_id`, `canonical_name` | CreativeWork 实体 |
| `media_type` | 受控媒介类型或“未知” |
| `classification_method` | 继承、规则或千问语义分类 |
| `task_status` | `completed/unknown` |
| `confidence` | 分类置信度 |
| `attempts` | 模型调用次数 |
| `model`, `prompt_version` | 模型与提示版本 |
| `reason_code`, `explanation` | 决策理由 |
| `source_members_json`, `source_media_json`, `context_json` | 输入上下文 |
| `raw_response` | 模型原始响应，仅审计使用 |
| `updated_at` | 更新时间 |

最终受控媒介包括歌曲、小说、话剧、电影、诗歌、戏剧、剧本、歌剧、舞蹈、纪录片、电视剧、报告文学、舞剧、雕塑、曲艺、漫画、理论著作、文集、连环画、动画片、绘画、广播剧、散文、民间传说、秧歌剧等。

## 9. Neo4j 映射

主要节点标签：Entity 及其具体类型、Assertion、SourceRecord、HistoricalStage、StudyRegion、BasinSection、CultureForm、EventCell、CultureState、TransitionCandidate、EvolutionTransition、TransitionType。

主要关系：SUBJECT_OF、OBJECT、SEMANTIC_RELATION、SUPPORTED_BY、DURING_STAGE、AT_PLACE、IN_STUDY_REGION、IN_BASIN_SECTION、EVENT_ROLE、EVENT_RELATION、HAS_CULTURE_FORM、HAS_SPATIOTEMPORAL_CELL、STATE_OF、STATE_DURING、STATE_IN_REGION、STATE_IN_BASIN、STATE_HAS_FORM、STATE_EVENT、STATE_ACTOR、STATE_SEMANTIC_MEMBER、STATE_VALUE_FACET，以及候选/发布演进关系。

Neo4j 中 `stable_id` 是机器标识，`name` 和 `caption` 是显示名称。看到字母数字 ID 不表示没有实体内容；浏览器样式应使用 `name` 或 `caption` 作为节点标题。

## 10. 质量门禁

- 严格关系必须通过层级感知 domain/range；
- 每条断言至少一条来源；
- 结构化时间必须有非 unknown 角色，无时间必须为 unknown；
- 强时间/空间角色必须有类型正确的 owner；
- CultureState 必须同时有支持事实和事件；
- 发布演进的起止状态必须为可信状态；
- CreativeWork 必须有媒介行，允许“未知”；
- 所有生成步骤记录输入/输出 SHA-256；
- 最终发布前执行 SQLite、能力查询、Neo4j、UI、全量约束和分层抽样审计。
