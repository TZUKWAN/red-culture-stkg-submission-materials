# KNOWN_LIMITATIONS — 如实声明（不做任何掩饰）

1. **抽取召回边界**：图谱断言来自文献抽取管线，召回有边界——原文中有而图谱没有的
   关系必然存在。本项目质量主张只覆盖"已入图谱断言的证据支持精度"，不主张全文召回率。
2. **PlaceVersion 覆盖有限**：全库仅 72 条 PlaceVersion（历史政区名变化），远低于
   实际历史地名变异数量；地域视图不得当作历史地理权威。
3. **CultureState 等派生层陈旧**：`research_culture_states.observation_tier`、
   时空单元格、阶段-区域指标、演进推断等由 v2 管线按**旧 strict 集**推导；最终分层
   后未重导（重导需完整管线重跑）。明细见最终库 `release_derivation_ledger` 表
   （5 项 STALE_AS_OF 记录）。引用这些聚合时必须附带此声明。
4. **Culture-form 支持基收缩**：最终分层后 31,827 条支持行因断言降为 unresolved 被
   删除（未决事实不能充当支持），culture-form 支持统计与 v2 报告数字不可直接对比。
5. **外部模型依赖**：Level-B 完整重跑需要用户自备 LM Studio + qwen3.5-4b；
   temperature=0 不保证跨后端逐 token 一致（详见 REPRODUCE.md）。
6. **模型随机性残余**：并发/批次会轻微改变 greedy 数值路径（09-13 实测：换并发后
   引号类输出缺陷率从 ~5% 漂移到 ~60%，已由解析层修复消除其对判定的影响，但现象
   本身证明非 bitwise 确定性）。
7. **版权边界**：源文献（983 册）全文不随包分发；发布物仅含派生断言、短引文
   （≤400 字符）与页码指针。分发边界见 DATA_RIGHTS_MANIFEST.csv。
8. **LLM 判定主观性**：PARTIAL/UNSUPPORTED 边界存在模型主观性；独立双裁判审计
   量化了该不确定性（见 experiments/quality_audit/AUDIT_REPORT.md），但未消除。
9. **时序关系为计算层**：5.6M 断言时序对由时间规范化标签推导（Allen 区间代数），
   非文献显式陈述；其中 causality_status 字段不构成因果主张。
10. **搜索延迟边界**：实体搜索为中文 LIKE 扫描（152,979 实体），p50 ≈1.2s/次，
    未达 <500ms 理想值；已通过两段式查询 + 并发服务器消除"单查询阻塞整个 UI"的
    严重问题。后续可引入 FTS5 + 中文分词进一步优化。
