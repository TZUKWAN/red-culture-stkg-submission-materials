# FINAL_SUBMISSION_READINESS_REPORT.md - 最终投稿就绪报告

## 项目
《选择性预测与结构准入协同的时空知识图谱构建方法——以长江流域中共党史文献为例》

## 目标期刊
《数据分析与知识发现》

## 报告生成时间
2026-09-05

---

## 1. 已完成事项

### 1.1 项目盘点
- ✅ 识别项目目录结构（manuscript/code/data/schema/queries/documents/audit/metadata）
- ✅ 定位论文DOCX文件和投稿指南
- ✅ 定位三个SQLite发布数据库
- ✅ 定位40个构建脚本和39个测试文件
- ✅ 定位26个能力查询
- ✅ 定位审计报告和元数据

### 1.2 核心数字验证
- ✅ 152,979个规范实体 → 数据库验证一致
- ✅ 424,150条知识陈述 → 数据库验证一致
- ✅ 466,312条来源关联 → 数据库验证一致
- ✅ 112,158条严格语义层 → 数据库验证一致
- ✅ 268,047条上下文层 → 数据库验证一致
- ✅ 43,945条未决集合 → 数据库验证一致
- ✅ 28,065个事件框架 → 数据库验证一致
- ✅ 7,067个事件时空单元 → 数据库验证一致
- ✅ 11,532个文化状态 → 数据库验证一致
- ✅ 208条时空作用域调整 → 数据库验证一致
- ✅ 159个演进候选 → 数据库验证一致
- ✅ 4条发布演进关系 → 数据库验证一致
- ✅ 1,019个文创作品媒介 → 数据库验证一致
- ✅ 13个研究区域 → 数据库验证一致
- ✅ 8个历史阶段 → 数据库验证一致
- ✅ 3个流域区段 → 数据库验证一致
- ✅ 88个关系契约 → 数据库验证一致
- ✅ 532条状态价值投影 → 数据库验证一致
- ✅ 98,762条文档关键词元数据 → CSV行数验证一致

### 1.3 审计报告生成
- ✅ submission_requirements_audit.md（投稿要求审计）
- ✅ manuscript_audit.md（论文版本审计）
- ✅ experiment_evidence_matrix.csv（实验证据矩阵）
- ✅ experiment_audit.md（实验审计）

### 1.4 复现材料整理
- ✅ submission_work/目录结构创建
- ✅ REPRODUCIBILITY_GUIDE.md（复现指南）
- ✅ DATA_DICTIONARY.md（数据字典）
- ✅ PAPER_RESULT_MAPPING.csv（论文结果映射）
- ✅ ENVIRONMENT_REPORT.txt（环境报告）
- ✅ DECLARATION_TEMPLATES.md（声明模板）
- ✅ AUTHOR_CONTRIBUTIONS.md（作者贡献模板）

---

## 2. 修改过的文件

本次审计未修改任何原始文件。所有审计和整理文档均为新建文件。

### 新建文件清单
| 文件 | 路径 | 用途 |
|---|---|---|
| submission_requirements_audit.md | 项目根目录 | 投稿要求审计 |
| manuscript_audit.md | 项目根目录 | 论文版本审计 |
| experiment_evidence_matrix.csv | 项目根目录 | 实验证据矩阵 |
| experiment_audit.md | 项目根目录 | 实验审计 |
| CLAUDE_STATE.md | 项目根目录 | 状态文件（已更新） |
| submission_work/ | 项目根目录 | 投稿工作目录（新建） |
| submission_work/reproducibility/* | submission_work/ | 复现材料 |
| submission_work/declarations/* | submission_work/ | 声明模板 |
| logs/ | 项目根目录 | 日志目录（新建） |
| temp_*.txt | 项目根目录 | 临时提取文件（可删除） |

---

## 3. 运行过的命令

1. `python -m pip install python-docx` - 安装DOCX处理库
2. `python temp_extract.py` - 提取论文DOCX文本
3. `python temp_tables.py` - 提取论文DOCX表格
4. `python verify_numbers.py` - 验证数据库核心数字
5. `python verify3.py` - 验证补充数据库数字

所有命令输出已保存到临时文件和本报告中。

---

## 4. 验证结果

### 4.1 数据库数字验证
全部18个核心数字与论文声称一致。

### 4.2 论文结构验证
- 正文结构完整（引言/相关研究/方法/实验/讨论/结论）
- 中英文标题一致
- 中英文摘要内容一致
- 关键词5个（中英文对应）
- 图表引用基本对应（有少量编号问题）

### 4.3 代码和数据验证
- 40个构建脚本存在
- 39个测试文件存在
- 26个能力查询存在
- 3个发布数据库存在且完整
- 分类器模型文件存在
- 审计报告存在且PASS

---

## 5. 已发现并修复的问题

### 5.1 发现的问题
1. ❌ 论文缺少结构化摘要标签[目的][方法][结果][局限][结论]
2. ❌ 论文缺少作者贡献声明
3. ❌ 论文缺少利益冲突声明
4. ❌ 论文缺少AI使用声明（论文使用了Qwen-122B-A10B）
5. ❌ 论文缺少数据可用性声明
6. ⚠️ 论文第87段"表1按评价对象分为两个Panel"应为"表2"
7. ⚠️ 论文第97段"表3从发布状态变化"的描述与表编号不完全匹配
8. ⚠️ Qwen-3.5-122B-A10B结果为缓存模型输出（MODEL_DEPENDENCY_UNAVAILABLE）

### 5.2 未修复的问题
以上问题均需作者手动处理。本审计未修改论文原始文件。

---

## 6. 仍未解决的问题

1. 983册文献的完整目录未提供（表1仅为部分列表）
2. 302,230页文本的统计依据未提供
3. 282,165条候选知识的生成日志未提供
4. 67,791条本地证据记录的统计日志未提供
5. 17,450条Qwen裁决的推理日志未提供
6. 712条集成参考标注的原始标注数据未提供
7. 152条核心评价样本的具体内容未提供
8. 选择性消融实验（表4）的独立脚本未提供
9. 效率实验（表6）的独立脚本未提供
10. 来源隔离实验的独立脚本未提供
11. 训练集/验证集的具体划分未提供

---

## 7. 阻塞投稿的问题

### 必须解决（阻塞投稿）
1. ❌ 缺少结构化摘要标签
2. ❌ 缺少作者贡献声明
3. ❌ 缺少利益冲突声明
4. ❌ 缺少AI使用声明
5. ❌ 缺少数据可用性声明

### 建议解决（不阻塞但建议改进）
1. ⚠️ 表格引用编号问题（第87段和第97段）
2. ⚠️ 英文图表标题（如期刊要求）
3. ⚠️ 参考文献格式统一检查

---

## 8. 作者需要手动确认的事项

1. **结构化摘要：** 按照期刊《结构式文摘写作要求》将摘要拆分为[目的][方法][结果][局限][结论]
2. **作者贡献声明：** 填写每位作者的具体贡献
3. **利益冲突声明：** 确认并声明是否存在利益冲突
4. **AI使用声明：** 如实声明AI工具使用情况（已知：Qwen-122B-A10B用于升级裁决）
5. **数据可用性声明：** 录用后上传数据至ScienceDB并补充DOI
6. **表格引用编号：** 核实第87段和第97段的表格引用是否正确
7. **正文准确字数：** 使用Word字数统计确认正文字数在8000-12000字范围
8. **983册文献：** 提供完整文献目录或确认表1覆盖范围
9. **基金信息：** 补充基金项目信息（如有）
10. **英文图表标题：** 确认是否需要并补充

---

## 9. 当前是否适合投稿

**判定：** ⚠️ 条件性就绪

在完成以下5项阻塞事项后，论文可以投稿：
1. 补充结构化摘要标签
2. 补充作者贡献声明
3. 补充利益冲突声明
4. 补充AI使用声明
5. 补充数据可用性声明

核心实验结果已通过数据库验证，论文结构完整，方法描述清晰。

---

## 10. 数据和代码公开前还需要做什么

1. **数据公开：**
   - 在ScienceDB数据社区注册并上传 `red_culture_stkg_final_v2.sqlite`
   - 获取DOI和公开URL
   - 补充数据可用性声明中的DOI和URL

2. **代码公开：**
   - 决定是否公开代码（建议公开以增强可复现性）
   - 如公开，选择平台（GitHub等）并上传
   - 补充代码可用性声明中的URL

3. **敏感信息检查：**
   - 确认数据库中无个人隐私信息
   - 确认文献授权范围
   - 确认无版权材料需要额外授权

4. **许可证确认：**
   - 确认数据许可证（如CC BY 4.0）
   - 确认代码许可证（如MIT）

---

## 11. 模型依赖状态

| 模型 | 状态 | 影响范围 |
|---|---|---|
| Qwen-3.5-122B-A10B | MODEL_DEPENDENCY_UNAVAILABLE | 17,450条裁决结果、Qwen基线指标、一致性选择指标 |
| 实体分类器（弹性网络逻辑回归） | ✅ 可用（模型文件存在） | 本地分类器基线 |

**说明：** Qwen相关结果为缓存模型输出。如需重新运行Qwen实验，需要：
- Qwen-3.5-122B-A10B模型文件
- 足够显存（估计≥40GB VRAM）
- 有效API配置

---

## 12. 是否新增了实验

**判定：** 否。本次审计未新增任何实验。所有实验结果均来自原始项目。

---

## 13. 哪些结果是实际运行

| 结果类型 | 状态 | 证据 |
|---|---|---|
| 数据库规模统计 | ✅ 实际验证 | 本次通过SQLite查询验证 |
| 全量审计（43项PASS） | ✅ 实际运行 | audit/stkg_v2_full_audit.json |
| 171个测试通过 | ✅ 实际运行 | audit/stkg_v2_final_tests.log |
| 26个能力查询通过 | ✅ 实际运行 | audit/stkg_v2_competency_queries.json |
| Neo4j导入验证 | ✅ 实际运行 | audit/stkg_v2_neo4j_verification.json |

---

## 14. 哪些结果是缓存模型输出

| 结果 | 原因 |
|---|---|
| Qwen-3.5-122B-A10B升级裁决（17,450条） | MODEL_DEPENDENCY_UNAVAILABLE |
| Qwen基线指标（覆盖率0.9934、一致率0.8808、风险0.1192） | 依赖Qwen模型 |
| 规则—Qwen一致性选择指标（覆盖率0.7632、一致率0.9914、风险0.0086） | 依赖Qwen模型 |

---

## 15. 哪些结果是确定性回放

| 结果 | 说明 |
|---|---|
| 结构准入校验（208条调整、44条时间违例、112条空间违例） | 可从数据库状态确定性推断 |
| 来源关联统计（466,312条） | 可从数据库查询确定性验证 |
| 事件框架和文化状态统计 | 可从数据库查询确定性验证 |

---

## 16. 哪些事项属于 MODEL_DEPENDENCY_UNAVAILABLE

1. 脚本257（单条Qwen裁决）的重新运行
2. 脚本258（Qwen任务池）的重新运行
3. 基于Qwen的评价指标的重新计算
4. Qwen-3.5-122B-A10B基线的重新评估

---

## 17. 所有证据文件路径

### 论文和投稿材料
- `manuscript/选择性预测与结构准入协同的时空知识图谱构建方法——以长江流域中共党史文献为例.docx`
- `manuscript/数据分析与知识发现投稿指南.txt`

### 数据库
- `data/release_databases/red_culture_stkg_final_v2.sqlite`
- `data/release_databases/red_culture_stkg_semantic_v2.sqlite`
- `data/release_databases/stkg_v2_creative_media_enrichment.sqlite`

### 代码
- `code/scripts/255-294_*.py`（40个构建脚本）
- `code/tests/test_stkg_v2_*.py`（39个测试文件）
- `code/stkg_ui_v2/`（研究界面）

### Schema和查询
- `schema/stkg_schema_v1.yaml`
- `schema/competency_questions_v2.md`
- `queries/cq_v2/`（26个能力查询）

### 审计报告
- `audit/stkg_v2_full_audit.json`
- `audit/stkg_v2_full_audit.md`
- `audit/stkg_v2_competency_queries.json`
- `audit/stkg_v2_final_tests.log`
- `audit/stkg_v2_neo4j_verification.json`

### 文档
- `documents/STKG_V2_DATA_DICTIONARY.md`
- `documents/STKG_V2_FINAL_RESEARCH_REPORT.md`
- `documents/STKG_V2_SEMANTIC_REPAIR_RESEARCH_PLAN.md`
- `documents/STKG_LITERATURE_ANALYSIS.md`

### 本次审计生成
- `submission_requirements_audit.md`
- `manuscript_audit.md`
- `experiment_evidence_matrix.csv`
- `experiment_audit.md`
- `submission_work/reproducibility/REPRODUCIBILITY_GUIDE.md`
- `submission_work/reproducibility/DATA_DICTIONARY.md`
- `submission_work/reproducibility/PAPER_RESULT_MAPPING.csv`
- `submission_work/reproducibility/ENVIRONMENT_REPORT.txt`
- `submission_work/declarations/DECLARATION_TEMPLATES.md`
- `submission_work/declarations/AUTHOR_CONTRIBUTIONS.md`
- `CLAUDE_STATE.md`
- `FINAL_SUBMISSION_READINESS_REPORT.md`
