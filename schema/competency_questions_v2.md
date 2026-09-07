# 长江流域红色文化演进时空知识图谱能力问题 V2

V2能力问题围绕“长江流域红色文化如何演进”组织。红色文化是研究对象，红色精神是可选语义线索；`first_observed`只表示数据集内首次观测，候选关系不得冒充历史因果。

| ID | 能力问题 | 主要层级 | 关键口径 |
|---|---|---|---|
| CQ01 | 各历史阶段的七类红色文化形态如何变化？ | CultureState | 按观察层级分别统计 |
| CQ02 | 13省区市在各阶段的文化形态结构有何差异？ | CultureState | 不把未知空间强行分配 |
| CQ03 | 上中下游各阶段的文化形态结构有何差异？ | CultureState | 使用冻结流域区段映射 |
| CQ04 | 可信、单条候选和关系上下文状态各占多少？ | CultureState | 三层结果不得混算 |
| CQ05 | 事件发生时间的可信度和覆盖情况如何？ | EventFrame | 可信时间与候选时间分开 |
| CQ06 | 哪些可信事件连接较多人物、组织和文化对象？ | EventFrame | 只用受控事件角色 |
| CQ07 | 人物在不同阶段和地区参与哪些事件？ | EventRole | 返回角色和观察层级 |
| CQ08 | 组织机构在不同阶段和地区承担哪些事件角色？ | EventRole | Organization与Institution均保留 |
| CQ09 | 地点与哪些事件、阶段和省域相连？ | EventRole | 地点角色与事件状态同时返回 |
| CQ10 | 某文化对象的阶段、区域和形态轨迹是什么？ | CultureState | 状态逐行可追溯 |
| CQ11 | 哪些演进关系已经通过显式结构门禁？ | EvolutionTransition | 只发布可信状态端点 |
| CQ12 | 演进候选为什么被发布或拦截？ | TransitionCandidate | 输出门禁原因 |
| CQ13 | 哪些事件被明确纪念化或物质化？ | Transition | 共现不得冒充转化 |
| CQ14 | 红色精神与价值内涵有哪些显式关系？ | Spirit/ValueFacet | 只用受控事实 |
| CQ15 | 红色精神通过哪些实体类型得到体现？ | Assertion | 每条连接保留fact_id |
| CQ16 | 哪些价值内涵跨阶段、跨地区出现？ | CultureState | 描述数据分布，不推断继承 |
| CQ17 | 文艺作品的媒介类型构成如何？ | CreativeWork | 具体类型与未知均进入分母 |
| CQ18 | 文艺作品在何阶段、何省域形成可观察状态？ | CreativeWork/State | 无时间作品不补猜阶段 |
| CQ19 | 各语义层事实的来源谱系覆盖如何？ | Provenance | 每条断言至少一条来源 |
| CQ20 | 严格、上下文和未解决断言分别有多少？ | ScopedAssertion | 未解决记录不删除 |
| CQ21 | 时间角色与时间精度分布如何？ | ScopedAssertion | 人物、事件、作品时间分开 |
| CQ22 | 空间角色与省市县覆盖情况如何？ | ScopedAssertion | 事件地点与上下文地点分开 |
| CQ23 | 规范实体类型与验证状态分布如何？ | CanonicalEntity | fallback单列 |
| CQ24 | 哪些规范实体整合了别名或多个来源实体？ | Identity | 返回成员数与别名 |
| CQ25 | 各对象在数据集内的首次观测状态是什么？ | CultureState | 不表述为历史起源 |
| CQ26 | 哪些记录因语义、时间或空间边界不能进入严格分析？ | QualityBoundary | 按排除维度汇总 |

所有查询位于 `stkg/queries/cq_v2`，由 `scripts/292_run_stkg_v2_competency_queries.py` 以SQLite只读授权器执行并记录数据库执行前后哈希。
