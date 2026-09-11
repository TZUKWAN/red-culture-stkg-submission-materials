# 14 · STKG 可视化套件报告（VIZ-1 … VIZ-6）

- 生成时间：2026-09-11 05:05:15 +0800
- 脚本：`code/experiment_pipelines/build_stkg_visualizations.py`（新建文件，未修改任何既有文件）
- 主数据源：`red_culture_stkg_final_v3_1.sqlite`（U1-U8 升级齐全）；回退库：`red_culture_stkg_final_v2.sqlite`（仅当 V3_1 某表缺失/为空时使用）
- 本次执行：SQL 查询 43 次，覆盖行数合计 226,109；按库分布：{'v3_1': 43}
- 回退触发情况：**无（全部表/视图均取自 V3_1 副本库）**
- 中文字体解析：{"requested_chain": ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Source Han Sans SC", "PingFang SC", "Arial Unicode MS", "DejaVu Sans"], "resolved": "Microsoft YaHei", "cjk_capable": true}
- 确定性：无随机过程；Top-N、坐标、配色与排序均由稳定次序键（ORDER BY 唯一化 + 固定容量）决定；PNG 内容不含时间戳，已验证连续重跑 6 张 PNG 字节级一致（CAPTION/报告中的生成时间为运行元数据）。
- 数据库访问：一律 `mode=ro` 只读打开，未发生任何写操作。

## 图件清单与数据规模

| 编号 | 文件（figures/） | 内容 | 数据规模（真实查询） |
|---|---|---|---|
| VIZ-1 | `figures/stkg_viz1_event_spacetime_density.png` | 长江流域事件时空密度热力图（十年×河段/省份 + Top 地点） | 时间断言 848 条 / distinct 事件 675；事件-地点对 960（双要素事件 649） |
| VIZ-2 | `figures/stkg_viz2_person_trajectories.png` | Top3 人物时间线 + 断言邻居网络（matplotlib 多面板版） | 3 人 × (时间线条目 ≤26 + 网络 16 邻居)；参与断言 Top3 合计 1,856 条 |
| VIZ-2H | `figures/stkg_viz2_person_trajectories.html` | 同上交互版（自包含 HTML，悬停明细/人物切换） | 3 人物页签；内嵌节点 51 个、边 48 条 |
| VIZ-3 | `figures/stkg_viz3_event_frame_structure.png` | Top-2 EventFrame 一页式结构展示 | 皖南事变 断言 2,231/证据行 2,558/时空单元 8、红军长征 断言 1,481/证据行 1,602/时空单元 12 |
| VIZ-4 | `figures/stkg_viz4_culture_state_evolution.png` | CultureState form×stage×region 热力图 + U3 时间区间分布 | 11,532 文化态（U3 时间区间覆盖 11,532）；支撑事件链接 13,336 条 |
| VIZ-5 | `figures/stkg_viz5_overview_tiers.png` | 全库十年×河段密度 + research_tier 层叠 | 3 河段 × 17 十年 = 51 热力格；带时间断言 77,930 条（具河段归属 52,053） |
| VIZ-5H | `figures/stkg_viz5_overview_tiers.html` | 同上交互版（逐格分层计数悬停） | 内嵌 51 个热力格（每格含分层计数）+ 17 根层叠柱 |
| VIZ-6 | `figures/stkg_viz6_method_architecture.png` | 最终方法架构示意（标注 MEASURED 实测数字） | 424,150 断言 / 466,312 证据成员 / 28,065 帧 / 11,532 文化态 全流程数字标注 |

## VIZ-2 入选人物（按参与 distinct 断言数 Top3）

- **毛泽东**：参与断言 1,017 条 / 事件 494 个；时间线条目 26（组织/职务 266 项候选、事件参与 55 项候选，各取断言数前 13）；网络邻居 16 个。
- **贺龙**：参与断言 458 条 / 事件 224 个；时间线条目 24（组织/职务 129 项候选、事件参与 11 项候选，各取断言数前 13）；网络邻居 16 个。
- **朱德**：参与断言 381 条 / 事件 167 个；时间线条目 26（组织/职务 109 项候选、事件参与 18 项候选，各取断言数前 13）；网络邻居 16 个。

## 每图 SQL 与行数

每张 PNG 配套 `figures/stkg_*_CAPTION.md`，含：图题、完整 SQL、真实行数、生成时间、数据源标注。

## 交互 HTML 说明

- 两张交互 HTML（VIZ-2、VIZ-5）均为**自包含单文件**（内联 CSS/JS 与数据，无 CDN、无外部字体请求），
  布局坐标在 Python 生成期确定性计算后内嵌；交互仅限悬停提示、人物切换与高亮。
- 环境内无 pyvis，VIZ-2 按规范回退为 matplotlib 多面板 PNG，同时另出交互 HTML 以满足『2 张交互 HTML』交付。

## 数据源回退策略

- 解析顺序：V3_1 副本库 → V2 主库（按表/视图粒度判空）。本次执行回退触发：**无**。
- 若未来在 V2 库复现：CultureState 的 U3 时间区间列（state_time_start 等）在 V2 不存在，脚本将如实降级并标注。

## 复现

```bash
cd submission_work/final_submission_v3_1/code/experiment_pipelines
python build_stkg_visualizations.py
```
