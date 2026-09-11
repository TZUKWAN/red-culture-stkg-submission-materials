# 12a · STKG 最小升级规格（MISSING/PARTIAL 项）

对应审计：`12_STKG_MODEL_REPORT.md`（7 项判定：SATISFIED 1 / PARTIAL 5 / MISSING 1）。
原则：**只补缺口，不推倒重来**；全部新表挂在 final 库 `research_` 命名空间下，保持现有外键图不变；每项标注实现成本。

成本图例：
- **[schema-only]**——只加表/列/视图/索引，无数据变动，当晚可完成；
- **[需要回填]**——加结构后需一次 INSERT/UPDATE 从库内既有数据机械推导（或含少量清洗），当晚~1 天；
- **[需要重建]**——需要外部数据源或重跑状态分层/过闸流程，数天。

按"今晚可实现"顺序排列：

| 序 | 项 | 对应审计项 | 成本 | 一句话 |
|----|-----|-----------|------|--------|
| U1 | 帧级 provenance 视图 | STKG-2 | **[schema-only]** | 用现有 links×provenance 一条视图补齐帧级证据链 |
| U2 | 断言状态键 + 身份碰撞去重 | STKG-1 | **[schema-only]+小回填(655组)** | 把事实上的 (s,p,o,τ,λ) 身份变成声明式唯一约束 |
| U3 | CultureState 时间区间 | STKG-6/STKG-4 | **[schema-only]+机械回填** | state 自身获得 time_start/end |
| U4 | 事件帧前驱后继表 | STKG-2 | **[schema-only]+回填(696帧)** | 补帧间时序，明确标注"非因果" |
| U5 | 时间区间关系表（Allen） | STKG-4 | **[schema-only]+机械回填(56,014 fact)** | before/after/overlaps/during/… 落成表 |
| U6 | role-owner 覆盖率提升 | STKG-5 | **[需要回填]** | 从 Event 链路与锚点回填 owner/role，覆盖率 1.3%→约 25%+ |
| U7 | 空间层级关系表（typed） | STKG-3 | **[需要回填（含清洗）]** | located_in/part_of 收编为带有效期、带审核位的层级边 |
| U8 | PlaceVersion 地名版本表 | STKG-3 | **[需要回填+外部政区沿革数据]** | 同名地名不同时期政区归属/级别版本 |
| U9 | time_precision / role 语义修复 | STKG-4/5 | **[需要回填（模型批处理）]** | 消 81.6% 的 'unknown' |
| U10 | 演化层扩容 | STKG-7 | **[需要重建]** | 提升 trusted 状态覆盖后重跑候选→过闸 |

---

## U1 帧级 provenance 视图（STKG-2）[schema-only]

**缺口**：provenance 只挂 fact 级，EventFrame 无法直接出示证据（审计扫描帧级 provenance 表 = 0）。

```sql
-- 只读视图，不迁移任何数据
CREATE VIEW IF NOT EXISTS v_research_event_frame_provenance AS
SELECT DISTINCT
    l.event_id,
    p.provenance_id,
    p.provenance_kind,
    p.source_table,
    p.source_record_id,
    p.evidence_ids_json
FROM research_event_assertion_links l
JOIN research_assertion_provenance p ON p.fact_id = l.fact_id;

-- 验证：每帧证据行数分布
-- SELECT count(*), count(DISTINCT event_id) FROM v_research_event_frame_provenance;
```

成本：**schema-only**，分钟级。零风险（视图）。

---

## U2 断言状态键 + 身份碰撞去重（STKG-1）[schema-only + 小回填]

**缺口**：(s,p,o,τ,λ) 身份目前只是事实上的散列，无声明式约束：655 组 (s,p,o,time_raw,place_raw) 完全相同的"碰撞"并存；另有大量 null-vs-值 未调和变体。

```sql
-- 1) 碰撞报告表（回填 = 一条 INSERT..SELECT，655 组）
CREATE TABLE research_assertion_identity_collisions (
    collision_group_id TEXT PRIMARY KEY,          -- sha256(spo+time+place)
    subject_id TEXT NOT NULL, predicate TEXT NOT NULL, object_id TEXT NOT NULL,
    time_raw TEXT, place_raw TEXT,
    member_fact_ids_json TEXT NOT NULL CHECK(json_valid(member_fact_ids_json)),
    resolution TEXT NOT NULL DEFAULT 'pending'
        CHECK(resolution IN ('pending','merged','kept_distinct_source')),
    resolved_at TEXT
);

-- 2) 处置策略（保守）：同组 fact 的 provenance 并入保留 fact，其余 fact 打 merged 标记后归档；
--    若两条来自互斥来源（provenance.source_record_id 不相交且 member_status 冲突）则 kept_distinct_source。
-- 3) 约束生效（处置完成后）：
CREATE UNIQUE INDEX IF NOT EXISTS ux_assertions_state_identity
    ON research_assertions(
        subject_id, predicate, object_id,
        coalesce(time_start,'#'), coalesce(time_end,'#'),
        coalesce(canonical_space_anchor_id,'#'));
```

成本：**schema-only + 一次 655 组去重回填**（处置逻辑 <100 行脚本）。null-vs-值 调和（59,526 组中 time_raw 为 null 的变体）另列 U9 批处理，不阻塞本项。

---

## U3 CultureState 时间区间（STKG-6 / STKG-4）[schema-only + 机械回填]

**缺口**：`research_culture_states` 无自身 time_start/end（审计：state 无区间字段，时长只能退化为 stage 区间）。

```sql
ALTER TABLE research_culture_states ADD COLUMN state_time_start TEXT;
ALTER TABLE research_culture_states ADD COLUMN state_time_end   TEXT;
ALTER TABLE research_culture_states ADD COLUMN state_time_source TEXT
    CHECK(state_time_source IN ('member_event_minmax','stage_interval','mixed'))
    DEFAULT 'stage_interval';

-- 回填：优先成员事件的观测时间 min/max，缺失则退回 stage 区间
UPDATE research_culture_states SET
    state_time_start = (SELECT MIN(f.observed_time_start)
                        FROM research_culture_state_events se
                        JOIN research_event_frames f ON f.event_id = se.event_id
                        WHERE se.state_id = research_culture_states.state_id
                          AND f.observed_time_start IS NOT NULL),
    state_time_end   = (SELECT MAX(f.observed_time_end)
                        FROM research_culture_state_events se
                        JOIN research_event_frames f ON f.event_id = se.event_id
                        WHERE se.state_id = research_culture_states.state_id
                          AND f.observed_time_end IS NOT NULL);

UPDATE research_culture_states SET state_time_source =
    CASE WHEN state_time_start IS NOT NULL THEN
        CASE WHEN state_time_start = (SELECT time_start FROM research_historical_stages
                                      WHERE stage_code = research_culture_states.stage_code)
             THEN 'stage_interval' ELSE 'mixed' END
    ELSE 'stage_interval' END;
```

成本：**schema-only + 一次机械回填**（3 条 UPDATE，分钟级）。注意 trusted 帧仅 95/28,065，多数 state 会退到 stage_interval——这正是 U4/U9 要放大的上游信号。

---

## U4 事件帧前驱后继表（STKG-2）[schema-only + 回填 696 帧]

**缺口**：帧间只有 499 条 part_of/influenced，无时序关系；而 696 帧有观测时间（trusted 95 + asserted 601），足以先建结构化时序。

```sql
CREATE TABLE research_event_frame_sequence (
    predecessor_event_id TEXT NOT NULL REFERENCES research_entities(entity_id),
    successor_event_id   TEXT NOT NULL REFERENCES research_entities(entity_id),
    sequence_basis TEXT NOT NULL CHECK(sequence_basis IN
        ('observed_end_before_start','explicit_part_of','explicit_influenced')),
    gap_days INTEGER,                       -- successor.start - predecessor.end（可为负=重叠）
    evidence_fact_ids_json TEXT NOT NULL DEFAULT '[]'
        CHECK(json_valid(evidence_fact_ids_json)),
    causality_status TEXT NOT NULL DEFAULT 'not_inferred'
        CHECK(causality_status = 'not_inferred'),   -- 与 research_event_relations 同款硬约束
    PRIMARY KEY (predecessor_event_id, successor_event_id, sequence_basis)
) WITHOUT ROWID;

-- 回填（示意）：同一主体（共享参与者）且时间可比较的帧对
INSERT INTO research_event_frame_sequence
    (predecessor_event_id, successor_event_id, sequence_basis, gap_days, evidence_fact_ids_json)
SELECT a.event_id, b.event_id, 'observed_end_before_start',
       CAST(julianday(b.observed_time_start) - julianday(a.observed_time_end) AS INTEGER),
       '[]'
FROM research_event_frames a
JOIN research_event_frames b
  ON a.observed_time_end IS NOT NULL AND b.observed_time_start IS NOT NULL
 AND b.observed_time_start >= a.observed_time_end
 AND a.event_id <> b.event_id
JOIN research_event_roles ra ON ra.event_id = a.event_id
JOIN research_event_roles rb ON rb.event_id = b.event_id AND rb.counterpart_id = ra.counterpart_id
GROUP BY a.event_id, b.event_id;
```

成本：**schema-only + 回填**（候选对由 696 帧限定，量级可控）。`causality_status='not_inferred'` 硬约束保证不把时序冒充因果（延续 STKG-7 的既有防线）。

---

## U5 时间区间关系表（STKG-4）[schema-only + 机械回填]

**缺口**：全库无任何区间-区间关系表（审计扫描 = 0）；77,930 条断言有显式区间却只能做阶段包含。

```sql
CREATE TABLE research_temporal_relations (
    left_fact_id  TEXT NOT NULL REFERENCES research_assertions(fact_id),
    right_fact_id TEXT NOT NULL REFERENCES research_assertions(fact_id),
    relation_code TEXT NOT NULL CHECK(relation_code IN
        ('before','after','meets','met_by','overlaps','overlapped_by',
         'starts','started_by','ends','ended_by','during','contains','equals')),
    left_scope  TEXT NOT NULL CHECK(left_scope  IN ('assertion_interval','owner_interval')),
    right_scope TEXT NOT NULL CHECK(right_scope IN ('assertion_interval','owner_interval')),
    computed_at TEXT NOT NULL,
    PRIMARY KEY (left_fact_id, right_fact_id, relation_code)
) WITHOUT ROWID;
```

回填（纯 SQL 的 13 分支 CASE，作用于**同主体共现对**；审计测得该范围 = 56,014 个 fact，量级一次跑完）：

```sql
INSERT INTO research_temporal_relations
SELECT a.fact_id, b.fact_id,
  CASE
    WHEN a.time_end  <  b.time_start THEN 'before'
    WHEN a.time_start >  b.time_end  THEN 'after'
    WHEN a.time_end  =  b.time_start THEN 'meets'
    WHEN a.time_start = b.time_start AND a.time_end = b.time_end THEN 'equals'
    WHEN a.time_start >= b.time_start AND a.time_end <= b.time_end THEN 'during'
    WHEN a.time_start <= b.time_start AND a.time_end >= b.time_end THEN 'contains'
    WHEN a.time_start =  b.time_start THEN 'starts'
    WHEN a.time_end   =  b.time_end   THEN 'ends'
    ELSE 'overlaps' END,
  'assertion_interval', 'assertion_interval', datetime('now')
FROM research_assertions a
JOIN research_assertions b
  ON a.subject_id = b.subject_id AND a.fact_id < b.fact_id
WHERE a.time_start IS NOT NULL AND a.time_end IS NOT NULL
  AND b.time_start IS NOT NULL AND b.time_end IS NOT NULL;
```

成本：**schema-only + 机械回填**（单条 INSERT..SELECT）。事件 chronology 查询（`v_research_event_times` × 本表）与 state duration（U3 区间 × 本表）随之解锁。

---

## U6 role-owner 覆盖率提升（STKG-5）[需要回填]

**缺口**：机制完整但 time_owner 覆盖 1.3%、space_owner 1.9%、time_role='unknown' 81.6%。

两条规则先行（全部可 SQL 推导，无需模型）：

```sql
-- R1：主体/宾语是 Event 的断言 → 时间归该事件所有（审计：Event 参与且 time_role='unknown'
--     的断言 = 99,976 条；time_role='event_occurrence' 现仅 910 条，说明该规则只跑过一角）
UPDATE research_assertions
SET time_owner_id = subject_id,
    time_role     = 'event_occurrence'
WHERE subject_type = 'Event' AND time_role = 'unknown';

-- R2：fact 已在事件链路且链路带 event_location → 空间归该事件所有
UPDATE research_assertions
SET space_owner_id = (SELECT l.event_id FROM research_event_assertion_links l
                      WHERE l.fact_id = research_assertions.fact_id
                        AND l.event_location_id IS NOT NULL
                      LIMIT 1),
    space_role     = 'event_location'
WHERE space_role = 'unknown'
  AND canonical_space_anchor_id IS NULL
  AND EXISTS (SELECT 1 FROM research_event_assertion_links l
              WHERE l.fact_id = research_assertions.fact_id
                AND l.event_location_id IS NOT NULL);
```

成本：**需要回填**（两条 UPDATE + 抽样人检 100 条 + 更新 build 元数据 limitations）。预期 time_role 未知率 81.6%→约 58%，space_owner 覆盖 1.9%→约 20%。剩余 'unknown' 归 U9 模型批处理。

---

## U7 空间层级关系表（STKG-3）[需要回填（含清洗）]

**缺口**（唯一 MISSING 项的一半）：无结构化层级；located_in 只是 466 条严格层 raw 断言，无级别、无有效期、有错挂（`曹市区 located_in 农救会`）。

```sql
CREATE TABLE research_place_relations (
    place_relation_id TEXT PRIMARY KEY,
    child_place_id    TEXT NOT NULL REFERENCES research_entities(entity_id),
    parent_place_id   TEXT NOT NULL REFERENCES research_entities(entity_id),
    relation_code     TEXT NOT NULL CHECK(relation_code IN ('located_in','part_of','contains')),
    admin_level_child  TEXT,      -- country/province/prefecture/county/town/village/site/area
    admin_level_parent TEXT,
    valid_time_start  TEXT, valid_time_end TEXT,   -- NULL=NULL 表示全程有效
    basis         TEXT NOT NULL CHECK(basis IN ('explicit_assertion','manual_review','administrative_atlas')),
    source_fact_id TEXT REFERENCES research_assertions(fact_id),
    review_status  TEXT NOT NULL CHECK(review_status IN ('auto_typed','needs_review','accepted','rejected'))
) WITHOUT ROWID;

-- 回填（第一步，显式断言收编）：
INSERT INTO research_place_relations
SELECT 'PLREL-' || substr(fact_id,7), subject_id, object_id,
       CASE predicate WHEN 'located_in' THEN 'located_in'
                      WHEN 'part_of'    THEN 'part_of' END,
       NULL, NULL, NULL, NULL, 'explicit_assertion', fact_id,
       CASE WHEN research_tier='strict_semantic' THEN 'needs_review' ELSE 'rejected' END
FROM research_assertions
WHERE predicate IN ('located_in','part_of')
  AND subject_type IN ('Place','AdministrativeRegion')
  AND object_type  IN ('Place','AdministrativeRegion')
  AND research_tier = 'strict_semantic';   -- 466+111 条；contextual 仅入 needs_review 队列
```

配套清洗（人工/规则）：父子类型校验（parent 名含"区/县/市/省"白名单）、环检测（`WITH RECURSIVE` 找 cycle → rejected）。

成本：**需要回填（含清洗）**，1–2 天内可交付一个"可信子集 + 待审队列"的层级层。

---

## U8 PlaceVersion 地名版本表（STKG-3）[需要回填 + 外部政区沿革数据]

**缺口**（唯一 MISSING 项的另一半）：全库无地名版本——1,982 组同名同类型 Place 实体没有时期维度；上游 212,945 实体 valid_from/valid_to 全空。

```sql
CREATE TABLE research_place_versions (
    place_version_id  TEXT PRIMARY KEY,
    place_id          TEXT NOT NULL REFERENCES research_entities(entity_id),
    name_zh           TEXT NOT NULL,
    admin_level       TEXT NOT NULL,       -- province/prefecture/county/town/village/site
    parent_version_id TEXT REFERENCES research_place_versions(place_version_id),
    valid_time_start  TEXT NOT NULL,
    valid_time_end    TEXT,                -- NULL = 开放区间
    boundary_geometry_ref TEXT,            -- 可空，指向 research_region_geometries(boundary_id)
    source_id         TEXT NOT NULL,
    UNIQUE(place_id, name_zh, valid_time_start)
) WITHOUT ROWID;

-- 断言→版本的绑定（让 located_in 带上"哪个时期"）：
ALTER TABLE research_place_relations
    ADD COLUMN child_version_id  TEXT REFERENCES research_place_versions(place_version_id);
ALTER TABLE research_place_relations
    ADD COLUMN parent_version_id TEXT REFERENCES research_place_versions(place_version_id);
```

回填数据源（按优先级）：民国/共和国政区沿革 gazetteer（外部导入）→ 1,982 组同名实体的时期拆分 → `research_assertions` 中带 time_start 的 located_in 事实（自动给已有边标定有效期）。上游 `up.entities.valid_from/valid_to` 同步回填，使实体层获得历史有效性。

成本：**需要回填 + 外部数据源**，数天（依赖 gazetteer 的获取与许可）。这是把系统从"当代空间脚手架"升级为"历史地理层"的关键项。

---

## U9 time_precision / role 语义修复（STKG-4/5）[需要回填（模型批处理）]

**缺口**：time_precision='unknown' 346,220（81.6%）、time_role='unknown' 346,220、space_role='unknown' 318,515——大部分断言只有 time_raw 原文，无精度、无角色。

规格：
1. 规则层先行（正则：`YYYY`、`YYYY年M月`、`民国N年`、`红军时期` 等映射到 year/month/period/era；预期可消解相当比例，参照上游 v2 已有 `v2_time_display` 显示层可复用）；
2. 剩余送模型批处理（复用上游 `v2_model_tasks/v2_model_decisions` 通道与 `v2_event_time_closures` 的调解模式），输出 time_precision/time_role/time_start/end，写回 `research_assertions` 对应列并记录 `decision_sources_json`；
3. 附带消费 U2 留下的 null-vs-值 未调和变体（同 s-p-o 一条无时间一条有时间 → 保守合并为"时间未知状态引用已知状态"，不删 fact）。

成本：**需要回填（模型批处理）**，规则部分 1 晚，模型部分视预算 1–3 天。

---

## U10 演化层扩容（STKG-7）[需要重建]

**缺口**：机制与因果防线完好，但 159 候选 → 仅 4 发布；105 条卡 `nontrusted_state`、49 条卡 `ambiguous_spatiotemporal_expansion`；上游 `evolution_transitions` 0 行。

规格（保持现有闸门语义，只扩大可信输入）：
1. **状态分层重算**：对 8,701 个 relation_context 状态跑 U6/U9 的 owner/时间回填，把满足"trusted/asserted 时空支撑 ≥1 事件"者升为 asserted_event_spacetime（预计消化大部分 `nontrusted_state` 闸门）；
2. **歧义闸门细化**：`ambiguous_spatiotemporal_expansion` 的 49 条候选补充区间判定（U5 的 Allen 关系可直接作为"时空唯一匹配"的判定输入），可升降级为 published/rejected；
3. 重跑 `research_evolution_transition_candidates → research_evolution_transitions` 管线（现有 10 条规则不动，可增补 `located_in` 版本化后的 `shifted_to/spread_to` 空间规则，依赖 U8）；
4. 上游 `evolution_transitions/evolution_transition_evidence` 若继续为空则在发布库 build 元数据中显式标注"上游演化层未启用"，避免误导。

成本：**需要重建**（状态分层重算 + 候选重跑），数天；因果边界约束（`causality_status='not_inferred'`、谓词触发、support 可回溯）**原样保留**。

---

## 今晚最短路径（若只做三件事）

1. **U1**（视图，分钟级）——EventFrame 立即获得证据链；
2. **U2**（身份键 + 655 组去重）——STKG-1 从"事实上的身份"变为"声明式身份"，可把 STKG-1 判定推到 SATISFIED；
3. **U5**（Allen 关系表 + 同主体回填）——一次性补上系统最大的时间语义缺口（STKG-4 的代数层），并直接服务 U10 的歧义闸门。

完成 U1–U5 后复跑 `audit_stkg_identity.py` 预期判定变化：STKG-1 PARTIAL→SATISFIED、STKG-4 PARTIAL→SATISFIED、STKG-2 PARTIAL（仍缺 trusted 帧时间，需 U9）、STKG-6 SATISFIED（区间补齐后弱点消除）。
