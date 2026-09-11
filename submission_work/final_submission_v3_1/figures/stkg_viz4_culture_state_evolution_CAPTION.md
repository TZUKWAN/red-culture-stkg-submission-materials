# VIZ-4 · CultureState 演化：form × stage × region 热力图与 U3 时间区间分布

- **生成时间**: 2026-09-11 05:05:15 +0800
- **脚本**: `code/experiment_pipelines/build_stkg_visualizations.py`（确定性：无随机过程，全部排序含稳定次序键）
- **图文件**: `figures/stkg_viz4_culture_state_evolution.png`

## 数据来源与查询

**Q1 全部文化态（form/stage/河段/观测层/时间区间/时间来源）**

```sql
SELECT culture_form_code, stage_code, basin_section_id, observation_tier, state_time_start,
       state_time_source, supporting_event_count
FROM research_culture_states
ORDER BY state_id
```

**Q2 文化形态字典**

```sql
SELECT culture_form_code, label_zh FROM research_culture_forms ORDER BY culture_form_code
```

**Q3 历史阶段字典**

```sql
SELECT stage_code, stage_label_zh, stage_order FROM research_historical_stages ORDER BY stage_order
```

**Q4 支撑事件链接（按阶段）**

```sql
SELECT s.stage_code, COUNT(*) AS n_links
FROM research_culture_state_events e JOIN research_culture_states s USING (state_id)
GROUP BY s.stage_code ORDER BY n_links DESC, s.stage_code
```

## 数据规模（真实查询行数）

- 文化态行数: **11,532**
- form × stage 组合数: **7 × 8 = 56**
- 热力图非零格（3 河段合计）: **127**
- 支撑事件链接行数: **13,336**
- 有 U3 时间区间的文化态: **11,532**
- 数据源: **red_culture_stkg_final_v3_1.sqlite（V3_1 副本库，含 U1-U8）**

## 使用说明
- 图中所有数字均为上图时刻对上述数据库执行 SQL 的真实统计；数据库只读打开。
- 附加说明见 `audit/method_final/14_VISUALIZATION_REPORT.md`。
