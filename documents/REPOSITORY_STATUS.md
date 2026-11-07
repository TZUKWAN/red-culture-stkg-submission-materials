# 仓库版本与本次同步范围

整理日期：2026-11-07。远端：`TZUKWAN/red-culture-stkg-submission-materials`。

## 当前入口

1. 最新完整审阅稿：`manuscript/revisions/20261015_round4/`，保留 2026-10-15 的文件内容和审阅状态。
2. 稿件生成依赖：`manuscript/revisions/20261015_round3/`。生成脚本包含原工作区绝对路径，原样保存供检查；不宣称脱离原数据工作区即可从头重建论文。
3. 数据基线：`submission_work/final_submission_v3_1/release_final/`，原数据库 SHA-256 为 `020d490533a9a4e4d1eaafe0dc5c9c5f63959f798f8d8b254a9494cb3146875a`。此值来自既有发布清单，本次没有重新跑全量数据库审计。
4. 级联准入：`submission_work/final_submission_v3_2/experiments/cascaded_admission_stage_effect/`。保留既有估计量、分子分母和历史结果。

`metadata/CURRENT_RELEASE.json` 管理数据与实验入口，`metadata/LATEST_MANUSCRIPT.json` 管理最新稿件。更新论文入口不会把冻结数据库改称新版本。

## 本次纳入

- Round 4 Word、同版 PDF、独立图包、验收记录、问题表、主张溯源表、题录表和作者确认单。
- Round 4 已有小型证据、历史核验 JSON、生成脚本及其直接 Round 3 依赖。
- 此前未提交的 v3_2 基线/消融补充输出、生成副本及比较脚本，运行日志除外。
- 历史叠加层幸存的 4 份记录。缺少的原始源码列在其 `SOURCE_GAPS.json` 中，清单自述的历史通过状态与本次同步检查分开记录。
- 根 README、稿件入口、同步文件清单、标准库文件验证工具和忽略规则。

## 保留与限制

来源工作副本有 939 个已跟踪文件缺失。本次从 `origin/main` 的已有历史建立独立工作副本，只接入明确选择的内容，避免把缺失状态转化为仓库清空。历史代码、LFS 指针、旧论文和图件继续留在原路径。

仅时间戳变化的冻结审计报告与运行日志没有覆盖到远端。没有新增模型实验、修改冻结参考、启动本地服务或提交论文。

旧稿件验收记录中标注的作者声明、数据公开、题录和图件来源问题继续保留。本次只验证同步文件完整性、目录入口与链接；不把旧的“通过”文字当作本次重新执行的研究验收。
