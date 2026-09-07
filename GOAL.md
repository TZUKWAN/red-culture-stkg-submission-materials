/goal

你现在需要接管并继续完善以下科研项目：

Repository:
TZUKWAN/red-culture-stkg-submission-materials

论文：
《选择性预测与结构准入协同的长江流域中共党史时空知识图谱构建——以长江流域中共党史文献为例》

当前目标期刊：
《数据分析与知识发现》

========================================
一、最终目标
========================================

不要重做现有知识图谱，不要推翻已有V2工程，不要为了“看起来实验更多”机械增加实验。

你的核心任务是：

在完全保留现有V2知识图谱、现有实验、现有代码和现有审计结果的基础上，补建一套与原生产标签链路尽可能解耦的“独立AI评价体系”，重新验证：

1. 选择性预测机制是否真的能够降低错误风险；
2. 结构准入机制是否真的能够改善语义和结构质量；
3. 实体规范化/身份投影是否真的改善实体一致性；
4. 时间—空间role/owner闭包所做的208条修正是否具有语义合理性；
5. 关系契约处理的3412条差异是否具有真实质量意义；
6. 来源谱系是否真正支持已经发布的知识断言；
7. Full framework相对于规则、分类器、LLM和简单阈值方法是否具有稳定优势；
8. 上述优势是否能够在独立于原ERA构造过程的评价集上成立。

最终交付结果必须形成：

“原工程结果 + 独立AI参考评价 + targeted structural validation + 完整选择性预测实验 + 完整统计检验 + 可复现代码 + 论文实验章节重写”

的一套闭环证据。

不得凭空构造实验结果。
不得修改原始实验数字来满足论文叙事。
任何结论必须来自真实运行结果。

如果新实验结果否定原论文部分判断，必须修改论文判断。

========================================
二、必须首先理解的现有证据边界
========================================

开始工作前，完整阅读并理解：

README.md

documents/
    STKG_LITERATURE_ANALYSIS.md
    STKG_V2_DATA_DICTIONARY.md
    STKG_V2_FINAL_RESEARCH_REPORT.md
    STKG_V2_SEMANTIC_REPAIR_RESEARCH_PLAN.md

schema/

code/scripts/

code/tests/

audit/

submission_work/final_submission/

submission_work/final_submission_v2/

特别必须阅读：

submission_work/final_submission_v2/README.md

submission_work/final_submission_v2/FINAL_CONTENT_CROSSREF_AUDIT.md

submission_work/final_submission_v2/FIGURE_TABLE_FORMULA_MAPPING.md

submission_work/final_submission_v2/experiments/02_baselines/*

submission_work/final_submission_v2/experiments/03_selective_inference/*

submission_work/final_submission_v2/experiments/05_ablation/*

submission_work/final_submission_v2/experiments/07_efficiency/*

以及以下实验脚本：

run_baseline_experiments.py
run_selective_inference.py
run_component_ablations.py
run_end_to_end_efficiency.py
build_ablation_figure.py
build_publication_figures.py

首先输出一份内部审计：

experiments/08_independent_ai_evaluation/00_PROJECT_AUDIT.md

明确区分：

A. actual run
B. deterministic replay
C. cached model output
D. shared-reference diagnostic
E. independent evaluation
F. unavailable experiment

任何后续论文表格也必须保留这种证据等级。

========================================
三、绝对不能继续沿用ERA作为唯一“真值”
========================================

现有712条ERA只能保留为：

Integrated Reference Annotation / 集成参考标注

它可以继续用于：
- 历史实验复现；
- 与旧论文数字对应；
- 诊断性比较；
- 方法演化追踪。

它不能继续作为新实验的唯一外部正确性依据。

原因必须在实验设计中显式处理：

ERA的产生与规则、source type、lexical hint、schema vote、历史Qwen输出等生产信号存在不同程度共享。

因此新建：

Independent Multi-model Consensus Reference

建议内部缩写：

IMCR

中文：

独立多模型共识参考集

注意：

不要把IMCR称为“人工金标准”。
不要称为“ground truth”。
不要称为“事实真值”。

论文中应称：

“独立多模型共识参考”
“外部AI参考标注”
“独立AI共识评价集”

它仍然属于AI评价，只是与生产标签构造链解耦。

========================================
四、建立新的工作目录
========================================

不得覆盖02、03、05、07中的任何已有文件。

新建：

submission_work/final_submission_v3/

其中至少包含：

code/
    independent_eval/
    experiment_pipelines/

experiments/
    08_independent_reference/
    09_independent_baselines/
    10_structural_validation/
    11_identity_validation/
    12_provenance_validation/
    13_selective_inference_independent/
    14_statistical_tests/

figures/

tables/

audit/

manuscript/

qa/

所有新输出均进入v3。

任何原始数据库只读。

========================================
五、Phase 0：冻结当前项目
========================================

第一步不得直接跑模型。

先冻结当前release。

记录：

1. 当前Git commit SHA；
2. CURRENT_RELEASE.json；
3. release_manifest.json；
4. final SQLite SHA-256；
5. semantic SQLite SHA-256；
6. master_data.csv SHA-256；
7. Schema文件SHA-256；
8. 所有已有实验CSV/JSON的SHA-256；
9. Python版本；
10. package版本；
11. random seeds；
12. 当前日期时间。

生成：

audit/BASELINE_FREEZE_MANIFEST.json

之后所有实验都必须引用这个manifest。

如果Git LFS文件没有完整拉取：

先检查：

git lfs install
git lfs pull

确认：

data/release_databases/red_culture_stkg_final_v2.sqlite

不是135字节LFS pointer，而是真实约1.19GB数据库。

不要在LFS未完成的状态下假装进行了数据库实验。

========================================
六、Phase 1：重新审计论文中的所有数据来源
========================================

逐项检查论文中的数字。

尤其检查过去审计中尚未完整验证的：

983册文献
302230页文本
282165条候选知识
67791条本地证据
17450条Qwen裁决

从：

数据库
日志
CSV
JSON
代码
manifest
历史输出

中寻找真实证据。

给每个数字建立：

claim
value
source_file
source_table
source_query
reproducible
evidence_level
notes

形成：

audit/PAPER_CLAIM_EVIDENCE_MATRIX.csv

如果某个数字找不到可重复验证的来源：

不得猜。

标：

NOT_FULLY_VERIFIED

然后检查该数字是否应：
A. 从论文删除；
B. 改为近似描述；
C. 补充可复现统计脚本。

优先补统计脚本。

========================================
七、Phase 2：构建真正盲化的IMCR
========================================

这是本轮最重要的实验。

--------------------------------
7.1 基本原则
--------------------------------

独立judge模型在判断时绝对不能看到：

ERA label
existing prediction
final label
risk_tier
semantic_status
auto_accepted
review status
source_type（如果source_type本身就是待评价信号）
lexical_hint
schema_votes
cached Qwen prediction
classifier prediction
rule prediction
historical model confidence
existing correctness flag

也不能把生产系统输出作为prompt中的“参考意见”。

judge模型只能看到：

1. 待判断对象；
2. 必要的原始文本证据；
3. 必要的局部关系上下文；
4. 冻结后的Schema定义；
5. 必要的类型定义；
6. 必要的任务说明。

评价过程必须blind。

--------------------------------
7.2 judge模型
--------------------------------

至少使用3个独立judge模型。

如果API资源允许，优先使用5个。

要求：

至少来自2个不同模型家族。

生产过程中使用过的Qwen不能成为唯一judge。

最佳方案：

Judge A
Judge B
Judge C
Judge D
Judge E

不同模型独立调用。

一个模型不能看到另一个模型的输出。

不能使用“模型辩论后统一答案”作为第一层标签。

第一层必须真正独立。

--------------------------------
7.3 输出格式
--------------------------------

每个judge统一JSON：

{
  "task_id": "",
  "decision": "",
  "confidence": 0.0,
  "evidence": [],
  "reason_code": "",
  "explanation": "",
  "insufficient_evidence": false
}

每个任务单独设计allowed labels。

不要允许自由文本答案代替结构化label。

--------------------------------
7.4 共识规则
--------------------------------

如果3模型：

3/3一致：
strong_consensus

2/3一致：
weak_consensus

其余：
unresolved

如果5模型：

4/5或5/5：
strong_consensus

3/5：
weak_consensus

其余：
unresolved

Primary evaluation：

只使用strong_consensus。

Secondary evaluation：

使用strong + weak。

unresolved不得强制多数票生成伪真值。

--------------------------------
7.5 一致性统计
--------------------------------

至少计算：

pairwise agreement
Fleiss' kappa
Krippendorff's alpha

适用时计算：

Cohen's kappa

另外做：

leave-one-judge-out consensus stability

即逐一移除一个模型重新形成共识，检查最终标签稳定性。

输出：

JUDGE_PAIRWISE_AGREEMENT.csv
JUDGE_RELIABILITY_SUMMARY.csv
LEAVE_ONE_JUDGE_OUT.csv

========================================
八、IMCR必须包含哪些任务
========================================

不要简单随机抽152条。

现有评价集最大的缺陷之一就是没有覆盖真正发生变化的困难样本。

新参考集必须采用：

stratified + targeted sampling。

========================================
8.1 Entity Type
========================================

目标：

验证实体分类和选择性分类能力。

建议样本：

300—500条。

分层：

Person
Event
Place
Organization
Institution
Concept
Document
Artifact
CreativeWork
Spirit
ValueFacet
AdministrativeRegion
CulturalSite
SocialGroup
其他实际存在类型

优先加入：

高风险类型
旧分类器低置信样本
规则与模型冲突样本
同名异类样本
类型层级冲突样本

但注意：

这些属性只用于抽样。

judge prompt中不能暴露生产系统判断。

========================================
8.2 Relation Semantic / Relation Contract
========================================

现有148条relation reference是饱和子集，区分力不足。

重新构建。

重点利用全库消融中：

w/o Relation Contract

相对于Full framework发生变化的3412条。

从3412条中抽：

至少300条。

再抽matched controls：

至少300条。

matched control尽量按照：

predicate
subject type
object type
stage
risk level

进行匹配。

新的judge任务：

判断：

关系语义是否成立；
关系是否与主客体类型相容；
是否应进入strict semantic层。

允许标签：

valid
invalid
context_only
insufficient_evidence

最终比较：

Full Relation Contract
w/o Relation Contract

在独立IMCR上的质量差异。

========================================
8.3 Time Role / Time Owner
========================================

现有评价不能证明208条修正。

因此：

必须对208条research_scope_adjustments中的全部相关记录进行评价。

不要抽样漏掉它们。

对每条记录生成：

before state
after state

但judge不能知道谁是before、谁是after。

进行随机A/B盲化。

judge判断：

时间是否属于该事件/人物/关系/作品；
正确time_role是什么；
正确owner是谁；
是否只能作为context time。

任务至少包括：

event_occurrence
relation_validity
biographical
creation_or_publication
commemoration_or_reception
source_document_time
context_time
unknown

输出：

TIME_SCOPE_BLIND_JUDGMENTS.csv

计算：

before correctness
after correctness
delta
paired improvement
95% CI

========================================
8.4 Space Role / Space Owner
========================================

与时间完全相同。

对208条scope adjustments涉及的空间记录全部进入候选。

盲化before/after。

标签：

event_location
relation_location
biographical_location
creation_or_publication_location
commemoration_or_reception_location
context_location
unknown

计算：

before vs after。

========================================
九、Phase 3：专门验证208条时空作用域调整
========================================

这是必须形成一个独立实验的小节。

现有全库结构结果表明：

去掉Role-owner Closure后：

invalid_time_owner_types = 44
invalid_space_owner_types = 112
changed_vs_full = 208

现有结果只能说明：

结构约束消除了结构不一致。

新实验必须回答：

这208次改变在语义上是不是合理。

设计：

所有208条全量评估。

对于每条：

A版本 = closure前
B版本 = closure后

随机交换顺序。

judge不知道哪个来自最终系统。

每个judge分别回答：

1. A是否合理；
2. B是否合理；
3. A/B哪个更符合证据；
4. 是否信息不足。

主要指标：

before accuracy/consistency
after accuracy/consistency
absolute improvement
relative error reduction
win / tie / loss
paired bootstrap CI

如果是binary matched判断：

增加McNemar test。

结果形成：

SCOPE_ADJUSTMENT_VALIDATION.csv
SCOPE_ADJUSTMENT_SUMMARY.csv
SCOPE_ADJUSTMENT_BOOTSTRAP.csv

这是论文结构准入贡献的重要外部语义证据。

========================================
十、Phase 4：实体规范化/身份投影实验
========================================

现有消融显示：

source_entities = 154150
projected_entities = 152979

identity reductions = 1171

去掉identity projection：

changed_vs_full = 24005

因此必须验证：

这些身份合并到底是在减少重复实体，还是误合并。

--------------------------------
10.1 构建pair evaluation
--------------------------------

从发生identity projection的cluster中提取：

positive merge candidate pairs。

同时建立hard negative：

同名不同实体
相似名称不同实体
同姓同名
事件与同名作品
机构与地点同名
历史人物别名与真实不同人物

尽可能从真实数据中寻找hard negative。

不要优先使用人为随机负例。

--------------------------------
10.2 judge输入
--------------------------------

只能提供：

名称A
名称B
各自别名
各自独立关系上下文
时间信息
空间信息
必要来源证据

不能直接提供：

canonical_entity_id
最终merge结果
existing mapping status

--------------------------------
10.3 judge标签
--------------------------------

same_entity
different_entity
insufficient_evidence

--------------------------------
10.4 指标
--------------------------------

pair precision
pair recall
pair F1
false merge rate
false split rate

如果能够构造完整reference clusters：

进一步计算：

B³ precision
B³ recall
B³ F1

如果不能保证完整cluster reference：

不要伪造cluster-level指标。

========================================
十一、Phase 5：来源支持度实验
========================================

现有图谱强调：

所有研究结论通过fact_id回到provenance。

这个优势目前主要由结构检查支持。

新增真实语义支持评价。

--------------------------------
11.1 抽样
--------------------------------

从：

strict_semantic
contextual
unresolved

三层分层抽样。

建议：

strict_semantic 400
contextual 300
unresolved 300

总计约1000条。

如果API成本较高：

最低不得少于500条。

--------------------------------
11.2 输入
--------------------------------

待评价：

subject
predicate
object
time
space

以及其真正来源文本。

必须从：

research_assertion_provenance

进一步返回真实SourceRecord/原始文本。

先检查真实文本究竟存在哪张表。

不能用已经结构化后的statement本身冒充source evidence。

--------------------------------
11.3 AI判断
--------------------------------

fully_supported
partially_supported
unsupported
contradicted
insufficient_evidence

--------------------------------
11.4 指标
--------------------------------

各tier：

support rate
unsupported rate
contradiction rate
insufficient evidence rate

尤其计算：

strict_semantic中的
fully + partially supported比例

以及：

unsupported/contradicted admission rate

用来评价严格语义层到底是否具有更高的证据质量。

========================================
十二、Phase 6：重新做独立基线实验
========================================

所有新基线统一在IMCR上计算。

不能继续只报告对ERA的一致率。

至少设置：

B1 Rule-only

B2 Frozen local classifier

B3 Blind LLM-only

B4 Rule + classifier

B5 Rule + blind LLM

B6 Classifier confidence threshold

B7 Classifier margin threshold

B8 Entropy threshold
如果模型提供可用概率分布。

B9 Rule-model agreement gate

B10 Selective prediction without structural admission

B11 Structural admission without selective abstention

B12 Full proposed framework

如果某基线实际上无法运行：

明确写：

NOT_AVAILABLE

不得使用旧缓存结果假装fresh run。

--------------------------------
12.1 Blind LLM baseline
--------------------------------

Blind LLM baseline必须使用独立于judge共识的模型。

例如：

如果Qwen作为baseline，

judge共识的Primary reference尽量不要包含该Qwen。

或者：

形成leave-Qwen-out IMCR。

必须避免：

同一个模型既生成prediction又参与reference majority，

然后计算它与自己形成的参考的一致率。

========================================
十三、Phase 7：重新跑选择性预测实验
========================================

复用现有：

run_selective_inference.py

不要重新写一套数学定义。

修改为支持：

--reference era
--reference imcr_strong
--reference imcr_all

至少重新计算：

coverage
selective accuracy
selective risk
generalized risk
safe coverage
error exposure
macro-F1 on accepted
macro-F1 on full denominator
AURC
normalized AURC
AUGRC
normalized AUGRC

注意：

论文里以后必须严格区分：

Macro-F1 on accepted

和：

Macro-F1 on full denominator

不能再统一写成模糊的“Macro-F1”。

--------------------------------
13.1 Risk-Coverage curve
--------------------------------

重新绘图：

横轴：
coverage

纵轴：
selective risk

至少画：

Rule
Classifier
Blind LLM
simple confidence threshold
Full framework

不要为了图好看隐藏失败曲线。

--------------------------------
13.2 Bootstrap
--------------------------------

至少：

2000 fixed-seed bootstrap replicates。

如果计算资源允许：

5000。

保存每一个replicate。

不要只保存summary。

计算：

AURC 95% CI
AUGRC 95% CI

以及Full framework相对于主要baseline的：

ΔAURC
ΔAUGRC
95% CI

========================================
十四、Phase 8：结构准入的独立验证
========================================

现有结构消融继续保留：

Full framework
w/o Risk Routing
w/o Identity Projection
w/o Relation Contract
w/o Role-owner Closure
w/o Provenance Gate
w/o Global Closure

现有确定性结果继续使用。

但新论文必须把：

“内部结构完整性”

与：

“外部语义质量”

分开报告。

建议形成两个Panel。

Panel A：
Full-database deterministic structural audit

报告：

strict contract violations
invalid time owner
invalid space owner
release state changes
entity count changes
fixed point violations

Panel B：
Independent AI semantic validation

报告：

AI-supported correctness
before-after preference
semantic error rate
IMCR agreement

这样才能真正说明结构准入既：

保证结构合法，

也提高语义合理性。

========================================
十五、关系契约3412条专项实验
========================================

建立：

RELATION_CONTRACT_CHANGED_SET.csv

包含全部3412条。

然后对其中至少300条分层评价。

matched control至少300。

Primary问题：

Full framework处理后的状态，相对于w/o Relation Contract是否更符合独立证据。

指标：

valid strict admission precision
invalid strict admission rate
context-only routing accuracy
before-after preference

不要再用原来148条全部通过的reference subset证明relation contract有效。

========================================
十六、Provenance Gate要实事求是
========================================

现有消融显示：

w/o Provenance Gate

changed_vs_full = 0

原因是当前发布数据本身没有无provenance断言。

因此：

不能在论文中把Provenance Gate描述成“在当前数据上显著提高性能”。

正确表述是：

它是一个发布安全不变量。

如果需要测试其能力：

可以新增一个明确标记为：

synthetic failure-injection stress test

的实验。

人工/程序化删除一部分provenance引用，

检查gate能否阻止这些断言进入strict layer。

注意：

这种实验必须明确叫：

stress test
fault injection
negative-control

绝不能和真实语料实验混在一起。

========================================
十七、数据集切分必须防止泄漏
========================================

禁止简单随机逐行split造成同一实体、同一来源、同一事件出现在train和test。

根据任务使用group split。

Entity classification：

按entity_id / entity cluster分组。

Relation：

至少按fact_id和实体pair控制。

Identity：

按identity cluster分组。

Provenance：

至少按source document分组。

Event相关任务：

优先按event_id分组。

如果同一历史事件的大量邻接事实同时进入train/test，
视为潜在泄漏。

建立：

SPLIT_LEAKAGE_AUDIT.json

自动检查：

entity overlap
fact overlap
source overlap
cluster overlap
event overlap

========================================
十八、统计分析要求
========================================

不要只报告点估计。

所有核心实验至少报告：

n
coverage
correct
error
estimate
95% CI

使用：

Wilson CI
bootstrap CI

按照指标类型选择。

paired system comparison优先使用：

paired bootstrap

binary paired结果适用时：

McNemar test

多模型judge一致性：

Fleiss kappa
Krippendorff alpha

如果类别极不均衡：

必须同时报告：

macro-F1
per-class precision
per-class recall
per-class F1

不能只报告accuracy。

========================================
十九、API与模型运行要求
========================================

所有AI调用必须：

1. 保存model exact ID；
2. 保存API provider；
3. 保存prompt version；
4. 保存temperature；
5. 保存top_p；
6. 保存seed（如果API支持）；
7. 保存timestamp；
8. 保存raw response；
9. 保存parsed response；
10. 保存retry count；
11. 保存validation error。

API Key：

只能从环境变量读取。

严禁写入：

Python文件
JSON
CSV
Git
日志
论文

新建：

.env.example

只写变量名。

========================================
二十、AI响应验证
========================================

不能相信模型一定输出合法JSON。

所有AI judge调用必须实现：

JSON schema validator。

非法输出：

retry。

最大retry次数固定。

达到上限：

mark MODEL_OUTPUT_INVALID

不能手工改答案。

不得人工修改judge结果让共识成立。

========================================
二十一、实验可重复性
========================================

所有采样必须固定seed。

每一个实验生成manifest：

experiment_id
database_sha256
schema_sha256
sample_manifest_sha256
prompt_sha256
model_ids
seed
code_commit
timestamp

任何论文中的数字必须能够通过：

paper claim
↓
table/figure
↓
summary CSV/JSON
↓
raw run
↓
sample ID
↓
source evidence

完整追踪。

========================================
二十二、代码测试
========================================

给新增代码编写pytest。

至少覆盖：

sample generation
blind-field leakage
judge parser
consensus aggregation
metric calculation
AURC
AUGRC
bootstrap
split leakage
before-after randomization
manifest hashing

特别写一个测试：

test_no_production_label_leakage.py

自动检查judge payload中不能出现：

ERA
gold_label
prediction
risk_tier
semantic_status
auto_accepted
schema_votes
lexical_hint
cached_llm_prediction
classifier_prediction

========================================
二十三、可选实验：事件框架质量
========================================

完成前面核心实验以后，如果资源允许，再增加：

EventFrame independent evaluation。

抽：

trusted event
asserted candidate
context-only

各类事件。

评价：

event identity
occurrence time
event location
actor role
support evidence

建议100—200个EventFrame。

这个实验是SECONDARY。

不要因为做这个而耽误前面的核心实验。

========================================
二十四、演进关系实验
========================================

检查当前论文是否对：

159 evolution candidates
4 published transitions

作了重要方法结论。

如果是：

对4条published transitions全部做AI证据复核。

再从159候选中分层抽样。

评价：

explicitly supported transition
temporal-only association
co-occurrence
insufficient evidence

验证现有发布门禁是否能够阻止：

仅共现
仅时间先后
仅相似
仅共同价值

被误写成传播、继承、转化或因果关系。

如果论文并未将演进关系作为核心方法证据，
则这一部分可以作为Supplementary。

========================================
二十五、最终实验结构建议
========================================

重构后的论文实验部分建议形成：

4.1 数据、任务与独立评价协议

介绍：

原始语料
V2图谱
ERA
IMCR
blind judging
judge agreement
数据划分
评价指标

4.2 选择性预测的独立基线比较

报告：

Rule
Classifier
Blind LLM
简单选择阈值
Proposed

表：
主要独立评价结果

图：
risk-coverage curve

4.3 选择机制消融

报告：

class-specific gate
signal agreement
abstention
structure gate

4.4 结构准入的全库约束效应

保留现有全库确定性消融。

4.5 结构修正的独立语义验证

重点：

208 scope adjustments
3412 relation contract changes

4.6 身份投影与实体规范化验证

重点：

1171 identity reductions
hard negatives
false merge

4.7 来源可追溯性与证据支持

报告：

strict/contextual/unresolved

三个层次的来源支持质量。

4.8 效率与规模扩展

保留现有五档规模、5次重复实验。

========================================
二十六、论文修改原则
========================================

不要先改论文。

必须：

实验完成
→ 审计
→ 确认结果
→ 再改论文。

尤其检查当前论文中：

0.7632 coverage
0.9914 agreement
0.0086 selective risk

这些旧ERA结果。

如果保留：

必须明确写成：

“相对于ERA的一致性结果”

不能让读者理解成：

外部历史事实准确率。

新增IMCR以后：

摘要和结论优先报告IMCR结果。

ERA结果可放：

旧实验对照
补充实验
历史复现

========================================
二十七、论文措辞边界
========================================

除非外部评价真正支持，否则不得写：

“证明事实完全正确”
“实现高准确率历史事实识别”
“消除了历史事实错误”
“达到真实历史金标准”

允许根据实验写：

“提高独立AI参考下的一致性”
“降低选择性风险”
“降低结构违例”
“提高来源支持率”
“提高时空语义归属合理性”
“降低身份误合并风险”

区分：

事实真实性
语义一致性
结构合法性
来源支持度
模型一致性

五个概念。

========================================
二十八、现有实验不要删除
========================================

02_baselines
03_selective_inference
05_ablation
07_efficiency

全部保留。

新实验属于证据升级。

不要为了简化结构删除旧实验。

最终README中建立：

OLD EVIDENCE
NEW INDEPENDENT EVIDENCE

之间的映射。

========================================
二十九、最终输出文件
========================================

至少生成：

01_PROJECT_AUDIT.md
02_DATA_EVIDENCE_AUDIT.md
03_IMCR_PROTOCOL.md
04_IMCR_JUDGE_RELIABILITY.md
05_BASELINE_REPORT.md
06_SELECTIVE_INFERENCE_REPORT.md
07_SCOPE_ADJUSTMENT_VALIDATION.md
08_RELATION_CONTRACT_VALIDATION.md
09_IDENTITY_VALIDATION.md
10_PROVENANCE_VALIDATION.md
11_STATISTICAL_ANALYSIS.md
12_EXPERIMENT_LIMITS.md
13_FINAL_EVIDENCE_SUMMARY.md
14_PAPER_RESULT_MAPPING.csv
15_FINAL_REPRODUCIBILITY_GUIDE.md
16_FINAL_AUDIT.md

以及所有：

raw JSONL
CSV
bootstrap CSV
manifest
plots
tables
logs

========================================
三十、必须生成的新论文图表
========================================

至少准备：

表A
Independent judge agreement

表B
Independent baseline comparison

表C
Selective prediction ablation

表D
Structural admission deterministic + semantic validation

表E
Identity projection validation

表F
Provenance support quality

图A
Independent risk-coverage curves

图B
AURC/AUGRC comparison with 95% CI

图C
208 scope adjustments before vs after

图D
Relation contract changed-set validation

如正文篇幅不足：

表E/F和图D可以进补充材料。

========================================
三十一、最终验收条件
========================================

只有同时满足以下条件，任务才算完成：

[ ] Git LFS数据真实可用
[ ] current release已冻结
[ ] 论文核心数字已重新建立证据映射
[ ] IMCR实现真正盲化
[ ] judge payload无生产标签泄漏
[ ] 至少3个独立AI judge
[ ] judge一致性统计完成
[ ] strong consensus reference建立
[ ] Entity Type独立评价完成
[ ] Relation Contract changed-set评价完成
[ ] 208 Scope Adjustments全部评价完成
[ ] Identity Projection评价完成
[ ] Provenance Support评价完成
[ ] Independent baselines完成
[ ] Blind LLM baseline完成
[ ] risk-coverage重新计算
[ ] AURC/AUGRC及CI完成
[ ] paired statistical comparison完成
[ ] 所有原始run保存
[ ] 所有figure可由脚本重建
[ ] 所有table可由脚本重建
[ ] 所有新代码测试通过
[ ] 原数据库hash未变化
[ ] 旧实验文件未覆盖
[ ] 新旧证据等级明确区分
[ ] 论文实验章节根据真实结果重写
[ ] 摘要、讨论、结论同步更新
[ ] 最终数字与CSV/JSON逐项交叉核验
[ ] 最终Word/PDF图表与正文结果一致

========================================
三十二、执行方式
========================================

不要只给我计划。

直接从仓库盘点开始执行。

执行顺序固定：

审计
→ 冻结
→ 数据准备
→ IMCR构建
→ judge运行
→ 共识审计
→ baseline
→ selective inference
→ structural validation
→ identity validation
→ provenance validation
→ statistics
→ figures/tables
→ manuscript rewrite
→ final audit

每完成一个阶段：

记录：

Completed
Evidence
New files
Key findings
Problems
Next step

不得因为发现旧实验存在不足就删除旧结果。

不得为了保持原论文结论而选择性报告。

如果新结果与旧结论冲突：

明确指出冲突，
定位原因，
修改论文。

最终目标不是把论文“包装得更好看”。

最终目标是让：

数据
代码
方法
实验
图表
论文结论

形成一条可以被第三方逐步复查的证据链。