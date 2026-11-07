# 历史叠加层记录与源码缺口

2026-11-07 整理时，仅找到下列 4 份历史文件，按原字节同步：

- [SHA256SUMS.txt](SHA256SUMS.txt)
- [CASCADE_INPUT_HASHES.json](manifests/CASCADE_INPUT_HASHES.json)
- [FINAL_NUMBERS_V3_2.json](manifests/FINAL_NUMBERS_V3_2.json)
- [VERIFY_REPORT.json](verification/VERIFY_REPORT.json)

旧校验清单还引用 `AUTHORITATIVE_RESULTS_v3_2.md`、`build_overlay_manifest.py`、`README_FIRST.md` 和 `verify_release_v3_2.py`。这些原文件未在当前项目及清理归档中找到，见 [SOURCE_GAPS.json](SOURCE_GAPS.json)。

因此，旧 SHA256SUMS 是未齐全历史包的记录，`VERIFY_REPORT.json` 中的历史 ALL PASS 不是本次重跑结论。当前入口不提供不存在的验证命令。本次新增 `scripts/verify_repository_snapshot.py` 仅验证同步文件和入口完整性，不替代原研究验证源码。
