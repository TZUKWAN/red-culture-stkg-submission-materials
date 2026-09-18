# 面向知识规范化与级联准入的历史文献时空知识图谱构建方法——以长江流域中共党史文献为例

本仓库是论文《面向知识规范化与级联准入的历史文献时空知识图谱构建方法——以长江流域中共党史文献为例》（目标期刊：数据分析与知识发现）的投稿材料与可复现发布包集中整理副本。

> 本仓库中的大型 SQLite 数据库和 CSV 数据文件由 Git LFS 管理。完整克隆前请安装 Git LFS，并在克隆后执行 `git lfs pull`。

## 权威入口（审稿人从这里进入）

1. **权威数字清单**：[`submission_work/final_submission_v3_1/AUTHORITATIVE_RESULTS.md`](submission_work/final_submission_v3_1/AUTHORITATIVE_RESULTS.md)
   ——论文最终数字只允许引用该文件列出的六个权威来源。
2. **最终发布数据库**：`submission_work/final_submission_v3_1/release_final/data/red_culture_stkg_final.sqlite`
   （SHA256 = `020d490533a9a4e4d1eaafe0dc5c9c5f63959f798f8d8b254a9494cb3146875a`，424,150 条断言 / 152,979 实体）
3. **一键复现**：`submission_work/final_submission_v3_1/release_final/reproduce/replay_all.py`
   （Level-A 离线回放，六步校验，约 10 秒，无需网络与 LLM）
4. **图谱浏览器 / 一键 EXE**：`submission_work/final_submission_v3_1/YangtzeSTKG-Reproduce.exe`
   （或 `python release_final/app/server.py`）
5. **最新论文正文**：[`submission_work/final_submission_v3_2/manuscript/论文正文.md`](submission_work/final_submission_v3_2/manuscript/论文正文.md)

## 核心结果（与 AUTHORITATIVE_RESULTS.md 一致）

- 全库 **424,150** 条结构化断言全部具有可重放的准入路径：
  112,158 条进入严格候选，268,047 条进入上下文状态，43,945 条进入未决状态，无法解释的历史状态为 0。
- 112,158 条严格候选经证据语义核验：**STRICT 31,067 / CONTEXTUAL 31,282 / UNRESOLVED 49,809**（零持留）。
- 独立双裁判审计（4,427 条分层样本）：对 STRICT 样本形成强共识的判定显示证据支持精度
  **99.28%（965/972，95%CI 0.9852–0.9965）**；
  级联阶段增益：直接发布候选的支持率仅 22.20%（总体加权），核验后最终严格层为 **42.55%**。
- 门外 311,992 条的 5,000 条分层双模型盲审：加权 STRICT 机会仅 **0.66%（95%CI 0.40–0.97）**，
  前置准入未造成大规模高质量知识遗漏。

## 目录

- `submission_work/final_submission_v3_2/`：**本轮工作目录**——级联准入阶段增益实验、修订后论文正文（manuscript/）、CHANGELOG。
- `submission_work/final_submission_v3_1/`：**最终发布包**（release_final/：可复现包、最终数据库、审计、图谱浏览器、EXE）与全库准入闭环实验（experiments/10_full_universe_admission_closure/）。
- `manuscript/`、`submission_work/final_submission_v2|v3/`：**历史版本存档（SUPERSEDED）**，其中数字不得作为论文引用来源。
- `data/`、`code/`、`schema/`、`queries/`、`documents/`、`audit/`、`metadata/`：历史构建材料与版本元数据（v2 时代，仅作参考）。

## 重要说明

1. 本目录由原文件复制生成，原工作空间文件未移动、未覆盖；历史版本目录顶部均带 SUPERSEDED 横幅。
2. 数据库、图谱导出和原始数据的公开范围按 `submission_work/final_submission_v3_1/release_final/manifests/DATA_RIGHTS_MANIFEST.csv` 执行；源文献全文不入包。
3. 版本核验依据：`release_final/manifests/RELEASE_LOCK.json`、`FINAL_NUMBERS.json`（db_sha256）、`dist/SHA256SUMS.txt`、`metadata/CURRENT_RELEASE.json`。
4. 源文献语料涉及版权与授权，公开前需逐项确认（含 ScienceDB/DOI 预留接口，录用后补充）。
