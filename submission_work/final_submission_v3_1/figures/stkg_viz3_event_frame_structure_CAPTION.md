# VIZ-3 · EventFrame 结构一页式展示（Top-2 事件帧：参与者 / 时间区间 / 空间足迹 / 角色 / 断言数 / 证据数）

- **生成时间**: 2026-09-11 05:05:15 +0800
- **脚本**: `code/experiment_pipelines/build_stkg_visualizations.py`（确定性：无随机过程，全部排序含稳定次序键）
- **图文件**: `figures/stkg_viz3_event_frame_structure.png`

## 数据来源与查询

**Q1 Top-2 事件帧**

```sql
SELECT event_id, event_name, all_assertion_count, strict_assertion_count, controlled_role_count,
       occurrence_time_fact_count, trusted_time_fact_count, event_location_fact_count,
       stage_count, region_count, observed_time_start, observed_time_end, observed_time_status,
       frame_status
FROM research_event_frames
ORDER BY all_assertion_count DESC, event_id
LIMIT 2
```

**Q2 帧内角色类别分布**

```sql
SELECT role_category, COUNT(*) AS n, COUNT(DISTINCT fact_id) AS n_facts
FROM research_event_roles WHERE event_id = ?
GROUP BY role_category ORDER BY n DESC, role_category
```

**Q3 Top 参与者**

```sql
SELECT counterpart_name, role_code, COUNT(*) AS n
FROM v_research_event_actor_roles WHERE event_id = ?
GROUP BY counterpart_name, role_code ORDER BY n DESC, counterpart_name LIMIT 8
```

**Q4 时空单元（阶段×省份×观测层）**

```sql
SELECT province_name, observation_tier, COUNT(*) AS n_cells,
       SUM(time_evidence_count + place_evidence_count + context_evidence_count) AS n_evidence
FROM research_event_spatiotemporal_cells WHERE event_id = ?
GROUP BY province_name, observation_tier
ORDER BY n_evidence DESC, province_name
```

**Q5 帧内地点 Top6**

```sql
SELECT event_location_name, COUNT(*) AS n
FROM v_research_event_places WHERE event_id = ?
GROUP BY event_location_name ORDER BY n DESC, event_location_name LIMIT 6
```

**Q6 帧间时序关系（U4）**

```sql
SELECT relation, COUNT(*) FROM event_frame_temporal
WHERE frame_a = ? OR frame_b = ? GROUP BY relation ORDER BY 2 DESC, relation
```

**Q7 帧证据行（U1 provenance）**

```sql
SELECT COUNT(*) AS n_rows, COUNT(DISTINCT assertion_id) AS n_assertions
FROM event_frame_provenance WHERE frame_id = ?
```

## 数据规模（真实查询行数）

- 帧①·皖南事变: **断言 2,231（严格 614），角色行 614，参与者对 27+，时空单元 8，证据行 2,558**
- 帧②·红军长征: **断言 1,481（严格 318），角色行 318，参与者对 18+，时空单元 12，证据行 1,602**

## 使用说明
- 图中所有数字均为上图时刻对上述数据库执行 SQL 的真实统计；数据库只读打开。
- 附加说明见 `audit/method_final/14_VISUALIZATION_REPORT.md`。
