# VIZ-6 · 最终方法架构图（候选抽取 → Predictor → Risk Routing → 三路 → 结构准入 → 分层 → EventFrame → CultureState）

- **生成时间**: 2026-09-11 05:05:15 +0800
- **脚本**: `code/experiment_pipelines/build_stkg_visualizations.py`（确定性：无随机过程，全部排序含稳定次序键）
- **图文件**: `figures/stkg_viz6_method_architecture.png`

## 数据来源与查询

**Q1 断言分层计数**

```sql
SELECT research_tier, COUNT(*) FROM research_assertions GROUP BY 1
```

**Q2 语义门计数**

```sql
SELECT semantic_status, COUNT(*) FROM research_assertions GROUP BY 1
```

**Q3 风险层计数**

```sql
SELECT risk_tier, COUNT(*) FROM research_assertions GROUP BY 1
```

**Q4 溯源成员 / 实体 / 帧间时序 / 断言时序**

```sql
SELECT COUNT(*) FROM research_assertion_provenance;
SELECT COUNT(*) FROM research_entities;
SELECT COUNT(*) FROM event_frame_temporal;
SELECT COUNT(*) FROM assertion_temporal_relations;
```

**Q5 U2 同一性视图**

```sql
SELECT COUNT(*), SUM(member_fact_count) FROM v_assertion_state_identity
```

**Q6 EventFrame / CultureState 结构计数**

```sql
SELECT frame_status, COUNT(*) FROM research_event_frames GROUP BY 1;
SELECT observation_tier, COUNT(*) FROM research_culture_states GROUP BY 1;
SELECT COUNT(*) FROM research_culture_state_events;
```

## 数据规模（真实查询行数）

- 溯源证据成员: **466,312**
- 融合断言: **424,150**
- 实体: **152,979**
- semantic_status auto/model/manual: **380,205 / 43,885 / 60**
- risk_tier A/B/C/D: **295,097 / 85,107 / 43,886 / 60**
- strict / contextual / unresolved: **112,158 / 268,047 / 43,945**
- U2 规范同一性键（成员断言合计）: **423,373（424,150）**
- EventFrame（strict_backbone）: **28,065（16,801）**
- 帧间时序关系（U4）/ 断言时序关系（U5）: **8,695 / 5,636,370**
- CultureState（trusted/asserted/context）: **11,532（958/1,873/8,701）**
- 数据源: **red_culture_stkg_final_v3_1.sqlite（V3_1 副本库，含 U1-U8）**

## 使用说明
- 图中所有数字均为上图时刻对上述数据库执行 SQL 的真实统计；数据库只读打开。
- 附加说明见 `audit/method_final/14_VISUALIZATION_REPORT.md`。
