# METHOD_MAP — 论文内容 ↔ 代码 ↔ 数据 ↔ 输出

| 论文内容 | 代码 | 数据/输入 | 输出/数字 |
|---|---|---|---|
| §1 引言（时空知识图谱+选择性预测） | — | — | README_FIRST 概览 |
| §2 相关工作 | — | — | docs/MODEL_MANIFEST.md |
| §3.1 断言抽取与规范化 | `code/experiment_pipelines/build_provenance_alignment.py` | 源文献库（V2 只读） | research_assertions 424,150；STRICT_ALIGNMENT.csv |
| §3.2 证据恢复（A/B/C/D 类） | `build_evidence_recovery.py` | 证据注册表 | EVIDENCE_RECOVERY.csv；B_localization=0.9812 |
| §3.3 证据语义门（五档判定） | `run_evidence_semantic_gate.py` + `independent_eval/lmstudio_provider.py` | 冻结 prompt（configs/PROMPTS.txt） | checkpoint 127,633 条 |
| §3.4 确定性快路径与安全规则 | `build_final_tiering.py features/learn/policy` | DEV 5,000（3/4 学 1/4 验，seed 固定） | FINAL_TIERING_RULES.json / FINAL_TIERING_POLICY.json |
| §3.5 §5.3 三层映射 | `build_final_tiering.py finalize`（dev_tier/assign_all） | 冻结 policy | FINAL_TIERING.csv 112,158；STRICT 31,067/CTX 31,282/UNRES 49,809 |
| §4.1 全库口径与台账 | `release_final/audit/make_universe_ledger.py` | 最终库只读 SQL | UNIVERSE_LEDGER.json/.csv |
| §4.2 一致性审计（判定正确性） | `release_final/audit/replay_final_tiering.py` | checkpoint+policy | REBUILD_DIFF.json（0 差异） |
| §4.3 独立质量审计 | `freeze_quality_audit_protocol.py` / `run_quality_audit.py` / `score_quality_audit.py` | 盲样本 4,427，双裁判 | AUDIT_RESULTS.json / AUDIT_REPORT.md |
| §4.4 最终数据库与硬审计 | `release_final/code/build_final_db.py` | FINAL_TIERING.csv | FINAL_DB_MANIFEST.json（违规=0） |
| §5 论文数字 | `release_final/code/generate_final_numbers.py` | 最终库 + 台账 | FINAL_NUMBERS.json/.csv（唯一权威源） |
| §6 一键复现 | `release_final/reproduce/replay_all.py` | 归档产物 | REPLAY_REPORT.json（全 PASS） |
| §7 图谱浏览器 | `release_final/app/` | 最终库 | 本地 Web UI（搜索/展开/证据链/时间轴/最短路/导出） |
| 附录 A 局限性 | — | release_derivation_ledger | docs/KNOWN_LIMITATIONS.md |
| 附录 B 修复审计 | — | RUN.log / checkpoint salvaged | docs/AUDIT_TRAIL.md |
