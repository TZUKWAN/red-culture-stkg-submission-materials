# VIZ-2 · 人物时空轨迹：参与断言最多的 3 位人物的时间线与断言邻居网络（PNG 多面板 + 交互 HTML）

- **生成时间**: 2026-09-11 05:05:15 +0800
- **脚本**: `code/experiment_pipelines/build_stkg_visualizations.py`（确定性：无随机过程，全部排序含稳定次序键）
- **图文件**: `figures/stkg_viz2_person_trajectories.png` / stkg_viz2_person_trajectories.html（交互版）

## 数据来源与查询

**Q1 参与断言 Top3 人物（事件角色 × 实体表）**

```sql
SELECT ar.counterpart_id, ar.counterpart_name, COUNT(DISTINCT ar.fact_id) AS n_facts,
       COUNT(DISTINCT ar.event_id) AS n_events
FROM v_research_event_actor_roles ar
JOIN research_entities en ON en.entity_id = ar.counterpart_id AND en.entity_type = 'Person'
GROUP BY ar.counterpart_id, ar.counterpart_name
ORDER BY n_facts DESC, ar.counterpart_id
LIMIT 3
```

**Q2 每人带时间区间的组织/职务关系断言（按谓词×对象聚合）**

```sql
SELECT r.predicate, r.object_name, MIN(r.time_start) AS s, MAX(COALESCE(NULLIF(r.time_end,''), r.time_end, r.time_start)) AS e,
       COUNT(*) AS n
FROM research_assertions r
WHERE r.subject_id = ? AND r.time_start IS NOT NULL AND r.time_start <> ''
  AND r.predicate IN ('member_of','held_position_in','led','organized')
GROUP BY r.predicate, r.object_name
ORDER BY n DESC, s, r.object_name
```

**Q3 每人带发生时间的事件参与断言（事件时间视图 × 角色视图，附 Top1 地点）**

```sql
SELECT t.event_name, MIN(t.occurrence_time_start) AS s, MAX(t.occurrence_time_end) AS e,
       COUNT(DISTINCT ar.fact_id) AS n,
       (SELECT pl.event_location_name FROM v_research_event_places pl
        WHERE pl.event_id = t.event_id GROUP BY pl.event_location_name
        ORDER BY COUNT(*) DESC, pl.event_location_name LIMIT 1) AS top_place
FROM v_research_event_actor_roles ar
JOIN v_research_event_times t ON t.event_id = ar.event_id
WHERE ar.counterpart_id = ?
GROUP BY t.event_id, t.event_name
ORDER BY n DESC, s, t.event_name
```

**Q4 每人直接断言邻居网络 Top16（research_assertions × research_entities）**

```sql
SELECT x.entity_id, x.canonical_name, x.entity_type, COUNT(*) AS n
FROM research_assertions r
JOIN research_entities x ON x.entity_id = (CASE WHEN r.subject_id = :pid THEN r.object_id ELSE r.subject_id END)
WHERE r.subject_id = :pid OR r.object_id = :pid
GROUP BY x.entity_id, x.canonical_name, x.entity_type
ORDER BY n DESC, x.canonical_name, x.entity_id
LIMIT 16
```

## 数据规模（真实查询行数）

- Top3 人物: **毛泽东(参与断言 1,017 / 事件 494)、贺龙(参与断言 458 / 事件 224)、朱德(参与断言 381 / 事件 167)**
- 时间线条目（3 人合计）: **76**
- 网络节点（3 人合计，含中心）: **51**
- 网络边（3 人合计）: **48**
- HTML 数据: **自包含（无 CDN），节点坐标由 Python 确定性生成**
- 数据源: **red_culture_stkg_final_v3_1.sqlite（V3_1 副本库，含 U1-U8）**

## 使用说明
- 图中所有数字均为上图时刻对上述数据库执行 SQL 的真实统计；数据库只读打开。
- 附加说明见 `audit/method_final/14_VISUALIZATION_REPORT.md`。
