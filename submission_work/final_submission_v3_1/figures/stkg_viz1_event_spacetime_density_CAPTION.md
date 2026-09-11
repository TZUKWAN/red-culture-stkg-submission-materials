# VIZ-1 · 长江流域红色事件时空密度（事件 occurred_at→地点断言，十年 × 河段/省份）

- **生成时间**: 2026-09-11 05:05:15 +0800
- **脚本**: `code/experiment_pipelines/build_stkg_visualizations.py`（确定性：无随机过程，全部排序含稳定次序键）
- **图文件**: `figures/stkg_viz1_event_spacetime_density.png` / 另含交互版无；VIZ-1 仅 PNG

## 数据来源与查询

**Q1 事件发生时间断言（v_research_event_occurrence_times）**

```sql
SELECT ot.fact_id, ot.subject_id, ot.subject_name, ot.time_start, ot.time_end,
       ot.basin_section, ot.province, ot.research_tier
FROM v_research_event_occurrence_times ot
ORDER BY ot.fact_id
```

**Q2 事件-地点断言（v_research_event_places × 有时间事件）**

```sql
SELECT pl.event_id, pl.event_location_name, pl.event_location_type, COUNT(*) AS n_facts
FROM v_research_event_places pl
WHERE pl.event_id IN (SELECT DISTINCT subject_id FROM v_research_event_occurrence_times)
GROUP BY pl.event_id, pl.event_location_name, pl.event_location_type
ORDER BY n_facts DESC, pl.event_location_name, pl.event_id
```

## 数据规模（真实查询行数）

- occurred_at 时间断言行数: **848**
- 有发生时间的 distinct 事件数: **675**
- 事件-地点断言对（distinct event×place×type）: **960**
- 既有时间又有地点的事件数: **649**
- 热力图 (a) 单元格总数 / 非零格: **35 / 27**
- 热力图 (b) 单元格总数 / 非零格: **77 / 49**
- 数据源: **red_culture_stkg_final_v3_1.sqlite（V3_1 副本库，含 U1-U8）**

## 使用说明
- 图中所有数字均为上图时刻对上述数据库执行 SQL 的真实统计；数据库只读打开。
- 附加说明见 `audit/method_final/14_VISUALIZATION_REPORT.md`。
