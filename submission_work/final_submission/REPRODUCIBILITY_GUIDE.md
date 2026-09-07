# REPRODUCIBILITY_GUIDE.md - 数据与代码复现指南

## 项目概述

本文档描述如何复现论文《选择性预测与结构准入协同的时空知识图谱构建方法——以长江流域中共党史文献为例》中的实验结果。

---

## 1. 环境要求

### 运行环境
- 操作系统：Windows 10/11
- Python：3.11+
- 数据库：SQLite 3.x
- 可选：Neo4j（用于图谱可视化）

### 依赖包
- sqlite3（Python标准库）
- csv（Python标准库）
- json（Python标准库）
- joblib（用于分类器模型）
- scikit-learn（用于分类器训练，如需重跑）
- python-docx（用于DOCX处理）

---

## 2. 数据文件

### 发布数据库
| 文件 | 路径 | SHA-256 | 用途 |
|---|---|---|---|
| 最终研究库 | `data/release_databases/red_culture_stkg_final_v2.sqlite` | `a199d736b9ec436b3d5f244e874718604b6c84955a505f31f90a3e28c51a9ee7` | 所有核心统计和查询 |
| 语义库 | `data/release_databases/red_culture_stkg_semantic_v2.sqlite` | `fbfb6529335e1c838270c63eee53c92a568c2b075354f7ad5f9d5815b88bb377` | 语义层中间结果 |
| 文创媒介库 | `data/release_databases/stkg_v2_creative_media_enrichment.sqlite` | `fde1f05b01709520a334dd88a58de6e501f36d2d0a182675516098b122a1d13f` | 文创作品媒介分类 |

### 分类器
| 文件 | 路径 | 用途 |
|---|---|---|
| 分类器模型 | `data/source_data/stkg_v2_entity_classifier.joblib` | 实体类型本地分类器 |
| 分类器元数据 | `data/source_data/stkg_v2_entity_classifier.sqlite` | 分类器训练/验证记录 |

### 图谱导出
| 文件 | 路径 | SHA-256 |
|---|---|---|
| Neo4j节点 | `data/graph_export/nodes.csv` | `1155838b569955884fdff9c29ec57c1c2aa13a54df39948a7fdc6480073887d8` |
| Neo4j关系 | `data/graph_export/relationships.csv` | `30c88bea6eb9ec29c5e2d092a74ab9c3ddc41f4a9355fac83ce82ea99bb0695b` |

---

## 3. 代码执行顺序

### 完整构建流程（40个脚本）
构建流程按编号顺序执行，从255到294：

1. `255_initialize_stkg_v2_semantic_repair.py` - 初始化V2语义修复
2. `256_label_and_fuse_stkg_v2_semantics.py` - 标签融合语义
3. `257_qwen_adjudicate_one_stkg_v2_task.py` - 单条Qwen裁决
4. `258_qwen_stkg_v2_task_pool.py` - Qwen任务池
5. `259_resolve_compatible_stkg_v2_subtypes.py` - 子类型消歧
6. `260_train_evaluate_stkg_v2_entity_classifier.py` - 训练评估实体分类器
7. `261_prepare_stkg_v2_classifier_review.py` - 准备分类器审查
8. `262_flag_stkg_v2_identity_ambiguity.py` - 标记身份歧义
9. `263_prepare_stkg_v2_model_second_review.py` - 准备模型二次审查
10. `264_close_stkg_v2_classifier_same_type.py` - 同类型分类器闭合
11. `265_reopen_identity_conflicts_closed_by_type_review.py` - 重开类型审查冲突
12. `266_add_stkg_v2_semantic_query_indexes.py` - 添加语义查询索引
13. `267_materialize_stkg_v2_cultural_sites.py` - 物化文化遗址
14. `268_materialize_stkg_v2_spatial_anchors.py` - 物化空间锚点
15. `269_restore_stkg_v2_strict_place_descriptors.py` - 恢复严格地点描述符
16. `270_resolve_stkg_v2_spatial_reference_entities.py` - 解析空间参考实体
17. `271_sync_stkg_v2_entity_type_hierarchy.py` - 同步实体类型层级
18. `272_audit_stkg_v2_spatial_model_contraindications.py` - 审计空间模型禁忌
19. `273_resolve_stkg_v2_strict_same_name_consensus.py` - 解析严格同名共识
20. `274_resolve_stkg_v2_strict_structure.py` - 解析严格结构
21. `275_prepare_stkg_v2_name_cluster_reviews.py` - 准备名称聚类审查
22. `276_qwen_adjudicate_one_stkg_v2_name_cluster.py` - 单条Qwen名称聚类裁决
23. `277_reset_stkg_v2_name_cluster_reviews_for_social_group.py` - 重置社会群体名称聚类审查
24. `278_remediate_stkg_v2_name_cluster_guard_violations.py` - 修复名称聚类门禁违例
25. `279_close_stkg_v2_global_structure_constraints.py` - 闭合全局结构约束
26. `280_close_stkg_v2_relation_and_name_consensus.py` - 闭合关系和名称共识
27. `281_close_stkg_v2_unresolved_semantics.py` - 闭合未解决语义
28. `282_close_stkg_v2_event_time_semantics.py` - 闭合事件时间语义
29. `283_close_stkg_v2_canonical_identity_and_space.py` - 闭合规范身份和空间
30. `284_materialize_stkg_v2_research_base.py` - 物化研究基础
31. `285_build_stkg_v2_event_culture.py` - 构建事件文化
32. `286_build_stkg_v2_evolution.py` - 构建演进
33. `287_export_stkg_v2_neo4j.py` - 导出Neo4j
34. `288_verify_stkg_v2_neo4j.py` - 验证Neo4j
35. `289_enrich_stkg_v2_creative_media.py` - 丰富文创媒介
36. `290_materialize_stkg_v2_final.py` - 最终物化
37. `291_import_stkg_v2_neo4j.py` - 导入Neo4j
38. `292_run_stkg_v2_competency_queries.py` - 运行能力查询
39. `293_audit_stkg_v2_full.py` - 全量审计
40. `294_publish_stkg_v2.py` - 发布V2

**注意：** 脚本257和258需要Qwen-3.5-122B-A10B模型可用。当前环境MODEL_DEPENDENCY_UNAVAILABLE，这两个脚本无法运行。

---

## 4. 数据库查询验证

### 核心数字复核

```sql
-- 规范实体数（论文声称：152,979）
SELECT COUNT(*) FROM research_entities;

-- 整合断言数（论文声称：424,150）
SELECT COUNT(*) FROM research_assertions;

-- 来源关联系数（论文声称：466,312）
SELECT COUNT(*) FROM research_assertion_provenance;

-- 严格语义层数量（论文声称：112,158）
SELECT COUNT(*) FROM research_assertions WHERE research_tier = 'strict_semantic';

-- 上下文层数量（论文声称：268,047）
SELECT COUNT(*) FROM research_assertions WHERE research_tier = 'contextual';

-- 未决集合数量（论文声称：43,945）
SELECT COUNT(*) FROM research_assertions WHERE research_tier = 'unresolved';

-- 事件框架数（论文声称：28,065）
SELECT COUNT(*) FROM research_event_frames;

-- 事件时空单元数（论文声称：7,067）
SELECT COUNT(*) FROM research_event_spatiotemporal_cells;

-- 文化状态数（论文声称：11,532）
SELECT COUNT(*) FROM research_culture_states;

-- 时空作用域调整数（论文声称：208）
SELECT COUNT(*) FROM research_scope_adjustments;

-- 演进候选数（论文声称：159）
SELECT COUNT(*) FROM research_evolution_transition_candidates;

-- 发布演进关系数（论文声称：4）
SELECT COUNT(*) FROM research_evolution_transitions;

-- 文创媒介数（论文声称：1,019）
SELECT COUNT(*) FROM research_creative_work_media;

-- 研究区域数（论文声称：13）
SELECT COUNT(*) FROM research_study_regions;

-- 历史阶段数（论文声称：8）
SELECT COUNT(*) FROM research_historical_stages;

-- 流域区段数（论文声称：3）
SELECT COUNT(*) FROM research_basin_sections;

-- 关系契约数（论文声称：88）
SELECT COUNT(*) FROM research_relation_contract;

-- 精神-价值链接数（论文声称：1,386）
SELECT COUNT(*) FROM research_spirit_value_links;

-- 状态价值投影数（论文声称：532）
SELECT COUNT(*) FROM research_culture_state_value_facets;
```

---

## 5. 代码与论文表格映射

| 论文表格 | 对应代码/数据 | 可复现性 |
|---|---|---|
| 表1（部分资料列表） | 原始文献目录（未在整理包中提供完整列表） | 需作者补充 |
| 表2（选择性判定与完整流程结果） | 评价脚本（未提供独立评估脚本） | 部分（Qwen依赖不可用） |
| 表3（完整构建流程） | 同表2 Panel B | 部分 |
| 表4（选择性组件消融） | 消融脚本（未提供独立消融脚本） | UNVERIFIED |
| 表5（结构准入全库消融） | scripts/255-294可重跑对比 | 可重跑 |
| 表6（效率实验） | 效率测试脚本（未提供） | UNVERIFIED |

---

## 6. 代码与论文图形映射

| 论文图形 | 内容 | 数据来源 |
|---|---|---|
| 图1 | 研究框架 | 设计图（非数据生成） |
| 图2 | 图谱总览 | Neo4j导出数据 |
| 图3 | 任务风险—覆盖曲线 | 评价脚本输出 |
| 图4 | 结构准入前后违例 | 数据库查询 |
| 图5 | 事件框架案例 | 数据库查询 |
| 图6 | 南昌起义子图 | 数据库查询 |
| 图7 | 来源追溯链 | 数据库查询 |
| 图8 | 效率实验 | 效率测试输出 |

---

## 7. 已知限制和不可复现部分

1. **Qwen-3.5-122B-A10B模型依赖：** 当前环境无可用模型，17,450条Qwen裁决结果和基于Qwen的基线指标（表2中Qwen行和规则—Qwen一致性选择行）为缓存输出，无法重新运行。
2. **原始文献目录：** 983册文献的完整目录未在整理包中提供，表1仅为部分资料列表。
3. **评价集：** 712条集成参考标注和152条核心评价样本的原始标注未在整理包中提供。
4. **效率实验：** 效率测试的独立脚本未提供，表5（效率）数据为论文报告值。
5. **分类器训练细节：** 117,954条训练样本和29,369条验证样本的具体划分未在整理包中提供。
6. **来源隔离实验：** 42条角色参考样本和24个来源连通分量的具体划分未提供。
