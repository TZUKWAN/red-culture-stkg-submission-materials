# VIZ-5 · 全库分层总览：十年 × 河段断言密度 + research_tier 层叠对比（PNG + 交互 HTML）

- **生成时间**: 2026-09-11 05:05:15 +0800
- **脚本**: `code/experiment_pipelines/build_stkg_visualizations.py`（确定性：无随机过程，全部排序含稳定次序键）
- **图文件**: `figures/stkg_viz5_overview_tiers.png` / stkg_viz5_overview_tiers.html（交互版：悬停查看每格分层计数）

## 数据来源与查询

**Q1 带时间断言（fact_id, 年份, research_tier）**

```sql
SELECT a.fact_id, substr(a.time_start, 1, 4) AS year4, a.research_tier
FROM research_assertions a
WHERE a.time_start IS NOT NULL AND a.time_start <> ''
ORDER BY a.fact_id
```

**Q2 断言 × 河段规范归属（research_assertion_basins）**

```sql
SELECT b.fact_id, b.basin_section_id, b.membership_order
FROM research_assertion_basins b
ORDER BY b.fact_id, b.membership_order
```

**Q3 全库 research_tier 计数**

```sql
SELECT research_tier, COUNT(*) FROM research_assertions GROUP BY research_tier
```

## 数据规模（真实查询行数）

- 全库断言总数: **424,150**
- strict / contextual / unresolved: **112,158 / 268,047 / 43,945**
- 带时间断言（1850–2026）: **77,930**
- 具规范三段归属的带时间断言: **52,053**
- 断言-河段归属对: **69,687**
- 跨段断言（每段各计一次）: **9,625**
- 热力图规模: **3 河段 × 17 十年 = 51 格（非零 46）**
- 数据源: **red_culture_stkg_final_v3_1.sqlite（V3_1 副本库，含 U1-U8）**

## 使用说明
- 图中所有数字均为上图时刻对上述数据库执行 SQL 的真实统计；数据库只读打开。
- 附加说明见 `audit/method_final/14_VISUALIZATION_REPORT.md`。
