# DATA_DICTIONARY.md - 数据字典

## 数据库：red_culture_stkg_final_v2.sqlite

### 核心实体表

#### research_entities（规范实体）
| 字段 | 类型 | 含义 |
|---|---|---|
| entity_id | TEXT PK | V2规范实体稳定ID |
| canonical_name | TEXT | 规范中文名称 |
| entity_type | TEXT | 最终实体类型（Person/Event/Place/Organization等） |
| semantic_family | TEXT | 语义族（Agent/SpatialEntity等） |
| aliases_json | JSON | 已确认别名列表 |
| integrated_member_count | INTEGER | 被合并的成员数 |
| source_entity_count | INTEGER | 来源实体数 |
| type_validation_status | TEXT | validated或fallback_unresolved |
| confidence | REAL | 类型置信度 |

**记录数：** 152,979

#### research_entity_members（实体成员映射）
| 字段 | 类型 | 含义 |
|---|---|---|
| source_entity_id | TEXT | 来源实体ID |
| canonical_entity_id | TEXT | 规范实体ID |

**记录数：** 154,150

---

### 断言与来源表

#### research_assertions（研究断言）
| 字段 | 类型 | 含义 |
|---|---|---|
| fact_id | TEXT PK | 整合断言稳定ID |
| subject_id | TEXT | 规范主体ID |
| object_id | TEXT | 规范宾语ID |
| predicate | TEXT | 受控关系或raw:*原关系 |
| time_start | TEXT | 结构化时间起点 |
| time_end | TEXT | 结构化时间终点 |
| time_precision | TEXT | unknown/year/month/period |
| normalized_time_label | TEXT | 统一中文时间显示 |
| time_role | TEXT | 时间语义角色 |
| time_owner_id | TEXT | 时间归属对象 |
| space_role | TEXT | 空间角色 |
| space_owner_id | TEXT | 空间归属对象 |
| province | TEXT | 规范省字段 |
| basin_section | TEXT | 上游/中游/下游 |
| semantic_status | TEXT | 语义状态 |
| research_tier | TEXT | strict_semantic/contextual/unresolved |
| confidence | REAL | 置信度 |

**记录数：** 424,150

**研究层级分布：**
- strict_semantic: 112,158
- contextual: 268,047
- unresolved: 43,945

#### research_assertion_provenance（断言来源）
| 字段 | 类型 | 含义 |
|---|---|---|
| fact_id | TEXT FK | 关联断言ID |
| source_member_id | TEXT | 来源成员ID |
| source_record_id | TEXT | 来源记录ID |

**记录数：** 466,312

#### research_scope_adjustments（时空作用域调整）
| 字段 | 类型 | 含义 |
|---|---|---|
| fact_id | TEXT FK | 关联断言ID |
| original_time_role | TEXT | 原时间角色 |
| final_time_role | TEXT | 最终时间角色 |
| original_space_role | TEXT | 原空间角色 |
| final_space_role | TEXT | 最终空间角色 |
| adjustment_reason | TEXT | 调整原因 |

**记录数：** 208

---

### 时间与空间维表

#### research_historical_stages（历史阶段）
**记录数：** 8
- 建党前传播与孕育
- 建党与大革命
- 土地革命战争
- 全民族抗日战争
- 解放战争
- 社会主义革命和建设
- 改革开放和社会主义现代化建设
- 新时代

#### research_study_regions（研究区域）
**记录数：** 13
- 青海、西藏、四川、云南、贵州、重庆、湖北、湖南、江西、安徽、江苏、上海、浙江

#### research_basin_sections（流域区段）
**记录数：** 3
- 上游、中游、下游

---

### 事件层

#### research_event_frames（事件框架）
| 字段 | 类型 | 含义 |
|---|---|---|
| event_id | TEXT PK | 事件实体ID |
| event_name | TEXT | 事件名称 |
| all_assertion_count | INTEGER | 全部断言数 |
| strict_assertion_count | INTEGER | 严格断言数 |
| observed_time_start | TEXT | 观测时间起点 |
| observed_time_end | TEXT | 观测时间终点 |
| frame_status | TEXT | strict_backbone/context_only/isolated |

**记录数：** 28,065

#### research_event_spatiotemporal_cells（事件时空单元）
**记录数：** 7,067

#### research_event_roles（事件角色）
**记录数：** 54,033

---

### 红色文化层

#### research_culture_states（文化状态）
| 字段 | 类型 | 含义 |
|---|---|---|
| culture_subject_id | TEXT | 文化主体ID |
| culture_form_code | TEXT | 文化形态代码 |
| stage_code | TEXT | 历史阶段代码 |
| region_id | TEXT | 研究区域ID |
| observation_tier | TEXT | 观察层级 |

**记录数：** 11,532

**文化形态分布：**
| 形态 | 总数 | 可信数 |
|---|---|---|
| HistoricalPractice | 7,066 | 201 |
| InstitutionalPractice | 3,898 | 647 |
| MemoryTransmission | 183 | 47 |
| SpiritValue | 178 | 32 |
| DocumentaryCulture | 97 | 16 |
| MaterialCulture | 61 | 11 |
| CreativeNarrative | 49 | 4 |

#### research_culture_state_value_facets（状态价值投影）
**记录数：** 532

---

### 演进层

#### research_evolution_transition_candidates（演进候选）
**记录数：** 159

#### research_evolution_transitions（发布演进关系）
**记录数：** 4
- 红军长征 → 扎西红军纪念馆
- 红军长征 → 嵩明红军长征纪念碑
- 秋收起义 → 铜鼓纪念馆
- 苏南反顽战役 → 苏南反顽战役阵亡将士纪念塔

---

### 文创媒介

#### research_creative_work_media（文创作品媒介）
| 字段 | 类型 | 含义 |
|---|---|---|
| entity_id | TEXT FK | 作品实体ID |
| media_type | TEXT | 受控媒介类型 |
| classification_method | TEXT | 分类方法 |
| confidence | REAL | 置信度 |

**记录数：** 1,019

**主要媒介类型：** 歌曲275、小说165、话剧156、电影74、诗歌69、戏剧55、剧本46等

---

### 关系约束

#### research_relation_contract（关系契约）
**记录数：** 88
- 88个受控谓词，每个谓词定义允许的主体类型集合Dₚ和客体类型集合Rₚ
