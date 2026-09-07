# 长江流域红色文化时空知识图谱 V2

本发布包用于研究“长江流域红色文化如何演进”。红色文化是研究对象，红色精神是可选分析线索。

## 核心文件

- `databases/red_culture_stkg_final_v2.sqlite`：最终研究数据库；
- `databases/red_culture_stkg_semantic_v2.sqlite`：实体、关系和时空语义决策库；
- `databases/stkg_v2_creative_media_enrichment.sqlite`：文艺作品媒介分类审计库；
- `graph/nodes.csv`、`graph/relationships.csv`：完整 Neo4j 导入数据；
- `schema/`：能力问题和映射规则；
- `queries/cq_v2/`：26 个论文能力查询；
- `documents/`：研究报告、数据字典、文献分析和构建方案；
- `audit/`：全量审计、构建报告、Neo4j/UI 验证和最终测试日志；
- `code/`：V2 构建脚本、测试和中文研究界面。

## 当前规模

- 152,979 个规范实体；
- 424,150 条断言；
- 466,312 条来源关联；
- 28,065 个事件框架；
- 11,532 个文化状态；
- 159 个演进候选，4 个通过门禁的显式演进关系；
- 1,062,247 个 Neo4j 节点；
- 2,984,015 条 Neo4j 关系。

## 使用边界

- `strict_semantic` 可用于严格关系分析；`contextual` 用于检索和上下文；`unresolved` 保留但不用于强结论。
- `first_observed` 表示数据集内首次观察，不表示历史起源。
- 共现、相似和时间先后不自动构成传播、继承、转化或因果。
- 本轮不做逐条外部史实复核；每条断言保留来源链，使用者可按需回查。
- 时间和空间未知值不得用猜测补齐。

完整方法和结果见 `documents/STKG_V2_FINAL_RESEARCH_REPORT.md`，字段定义见 `documents/STKG_V2_DATA_DICTIONARY.md`，发布完整性见 `release_manifest.json` 和 `audit/stkg_v2_full_audit.json`。
