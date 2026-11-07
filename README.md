# 历史文献时空知识图谱：代码、复现材料与论文审阅稿

本仓库整理长江流域中共党史时空知识图谱研究的代码、冻结实验材料和论文版本。最近一次仓库整理日期为 **2026-11-07**；本次纳入的最新完整论文文件来自 **2026-10-15 Round 4**。

## 最新论文文件

| 文件 | 入口 |
|---|---|
| 可编辑 Word | [Round 4 审阅稿 DOCX](manuscript/revisions/20261015_round4/论文_审阅稿_round4_基于已知最新稿.docx) |
| 同版 PDF | [Round 4 审阅稿 PDF](manuscript/revisions/20261015_round4/论文_审阅稿_round4_基于已知最新稿.pdf) |
| 独立图件包 | [PNG / PDF / SVG ZIP](manuscript/revisions/20261015_round4/图件_PNG_PDF_SVG_round4.zip) |
| 历史验收记录 | [定稿验收报告](manuscript/revisions/20261015_round4/定稿验收报告.md) |
| 尚待确认事项 | [作者确认单](manuscript/revisions/20261015_round4/作者确认单.md) |

**当前是审阅稿。** 原记录仍包含指定主稿未找到、作者声明与数据链接待确认、部分题录待核及图件源文件缺口。本次同步保持这些状态；同步成功不代表论文通过投稿验收。历史验收报告和研究脚本原样保留，其陈述不等同于本次重新运行了研究实验。

机器可读入口：[最新稿件](metadata/LATEST_MANUSCRIPT.json) · [逐文件 SHA-256 清单](metadata/SYNC_SNAPSHOT_20261107.json) · [版本与同步说明](documents/REPOSITORY_STATUS.md)。

## 数据与实验版本

| 范围 | 入口 | 使用说明 |
|---|---|---|
| 冻结数据及证据门 | [v3_1 结果来源](submission_work/final_submission_v3_1/AUTHORITATIVE_RESULTS.md)、[发布包说明](submission_work/final_submission_v3_1/release_final/README_FIRST.md) | 保留原数据库哈希和实验身份 |
| 级联准入分析 | [v3_2 级联结果 JSON](submission_work/final_submission_v3_2/experiments/cascaded_admission_stage_effect/CASCADED_ADMISSION_STAGE_RESULTS.json) | 使用原有统计定义；与论文审阅稿版本分开管理 |
| 基线与消融补充 | [2026-09-24 重跑记录](submission_work/final_submission_v3_2/experiments/11_baseline_ablation_repro/BASELINE_ABLATION_RERUN_REPORT.md) | 本次同步已有产物，没有重新调用模型 |
| 历史论文正文 | [v3_2 Markdown](submission_work/final_submission_v3_2/manuscript/论文正文.md) | 保留为历史实验语境，不作为最新全文入口 |
| 不完整的历史叠加层 | [源文件缺失说明](submission_work/final_submission_v3_2/release_final_v3_2/README.md) | 原验证脚本缺失，历史 ALL PASS 不代表现在可完整重跑 |

冻结发布清单记录 152,979 个规范实体、424,150 条结构化断言，门内候选 112,158 条。它们是各自版本的数据规模。99.28% 是双裁判形成强共识的严格层样本中 965/972 的条件支持比例；门外机会估计使用另一总体，不能与全库准确率、召回率混用。具体统计条件以对应结果文件为准。

## 仓库导航

- [研究代码](code/)、[模式与约束](schema/)、[查询](queries/)、[历史构建文档](documents/)、[构建审计](audit/)。
- [v3_1 冻结复现目录](submission_work/final_submission_v3_1/release_final/)与 [v3_2 分析目录](submission_work/final_submission_v3_2/)。
- [论文修订快照](manuscript/revisions/)：Round 4 完整交付及其用到的 Round 3 生成依赖。
- [历史可视化](可视化图片展示/)：既有图件库；当前审阅稿的图件以最新论文文件表中的 ZIP 为准。
- [历史数据目录](data/)：早期 SQLite 和部分 CSV 由 Git LFS 管理。

## 验证本次同步文件

在仓库根目录运行，使用 Python 标准库，无需启动数据库或模型服务：

```bash
python scripts/verify_repository_snapshot.py
```

检查同步清单的大小与哈希、DOCX/ZIP 完整性、PDF 文件结构、JSON/CSV 可读性、当前入口和内部相对链接。它验证仓库整理与文件传输，不重新判定历史统计结论。

研究复现按 [冻结复现说明](submission_work/final_submission_v3_1/release_final/docs/REPRODUCE.md)执行。大型发布数据库和分发包不在普通 Git 文件树中；可在 [GitHub Releases](https://github.com/TZUKWAN/red-culture-stkg-submission-materials/releases) 查阅已有附件与校验清单。早期 LFS 文件需安装 Git LFS 并按需运行 `git lfs pull`。

## 文件边界

原始 OCR 全文、外部参考论文全文、本机环境、凭据、临时日志和渲染缓存不纳入这次同步。原始史料的权利边界见 [DATA_RIGHTS_MANIFEST.csv](submission_work/final_submission_v3_1/release_final/manifests/DATA_RIGHTS_MANIFEST.csv)。既有历史提交保留；本机缺失文件没有被直接批量提交为远端删除。
