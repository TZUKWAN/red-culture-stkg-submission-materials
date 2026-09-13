# YangtzeSTKG-Reproduce — Release Notes (stkg-final-reproducible-2026)

长江流域中共党史时空知识图谱：最终质量最大化、可复现发布。

## 亮点

- **全量 MEASURED**：112,158 条旧 strict 断言经 qwen3.5-4b 证据语义门逐条判定
  （reasoning=off，无静默回退），STRICT 31,067 / CONTEXTUAL 31,282 / UNRESOLVED 49,809，零持留。
- **一键离线复现**：`reproduce/replay_all.py` 六步全 PASS——checkpoint 完整性 →
  独立重放 FINAL_TIERING（112,158 行逐行对账 0 差异）→ 数据库哈希闭环 → 硬结构审计 0 违规。
  无网络、无 LLM、约 8 秒。
- **一键 EXE**：`YangtzeSTKG-Reproduce.exe` 双击即用（验证 / 复现 / 浏览图谱 / 查看数据），
  不需要 Python / Neo4j / 终端。
- **证据链浏览器**：WebGL 图谱（搜索、渐进展开、三层筛选、时间轴、证据抽屉、最短路、导出），
  每条边可下钻到断言 → 判定（置信度/引文/模型理由）→ 溯源指针。
- **独立质量审计**：预注册协议 + 双独立裁判盲评（gpt-oss-20b、qwen3-8b，均不参与生产判定），
  4,427 分层样本（含 salvaged 与置信度边界强覆盖）。
- **诚实审计**：11 项修复全程留痕（AUDIT_TRAIL.md）；10 项已知局限如实声明
  （含 CultureState 等派生层陈旧台账，见库内 release_derivation_ledger 表）。

## 资产

| 文件 | 说明 |
|---|---|
| `PUBLIC_REPRO_PACKAGE.zip` | 完整可复现包（代码+文档+审计+最终库+EXE） |
| `YangtzeSTKG-Reproduce.exe` | Windows 一键入口（需配合包内 data/ 目录） |
| `SHA256SUMS.txt` | 全部资产哈希 |
| `FINAL_RELEASE_REPORT.md` | 发布报告（含指标、审计与 UAT 结果） |

## 数据边界

源文献全文不受授权分发；包内仅含派生断言、≤400 字引文与页码指针。
详见 `manifests/DATA_RIGHTS_MANIFEST.csv`。
