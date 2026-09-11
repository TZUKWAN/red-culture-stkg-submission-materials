# FINAL · STKG 升级 U1–U8 实施报告（V2 库副本）

- 实施对象：`submission_work/final_submission_v3_1/data/repaired_release/red_culture_stkg_final_v3_1.sqlite`
  （源库 `data/release_databases/red_culture_stkg_final_v2.sqlite`，sha256 `a199d736b9ec436b…` 的逐字节副本 + 升级；**旧库与 sem 库全程只读**）
- 参考库：`data/release_databases/red_culture_stkg_semantic_v2.sqlite`（ATTACH `mode=ro`，只读参考）
- 语料（U8 只读扫描）：`data/source_data/master_data.csv`，sha256-16 `6ce4f7f3341e3350`，98,762 行
- 选择性规则（U6 唯一裁判）：`experiments/05_scope_repair/v2_/CLOSURE3_RULES.json`，sha256-16 `1121a0288854f280`
- 规格：`audit/method_final/12a_STKG_UPGRADE_SPEC.md`（U1–U10）；基线判定：`12_STKG_MODEL_REPORT.md`（SATISFIED 1 / PARTIAL 5 / MISSING 1）
- 实施脚本：`code/experiment_pipelines/apply_stkg_upgrades.py`（幂等，每升级项一个事务，台账 `stkg_upgrade_log` 记录，`--only U1..U8` 可单项重跑）
- 测试：`code/tests/test_stkg_upgrades.py`（fixture sqlite，11 项断言全过；U2 canonical 唯一 / U4 relation_basis / U5 Allen 手算 / U7 组织父节点拒绝与名称复核位 / U8 证据建版本与降级 / 幂等 / 完整性自检）
- 实施日期：2026-09-10（U1–U5）→ 2026-09-11（U6–U8 + 全量自检）

---

## 结论先行

U1–U8 全部在副本库落地：新增/物化对象 **8 个升级产物**（`event_frame_provenance`、`research_assertion_identity_collisions` + `v_assertion_state_identity` + 部分唯一索引、culture state 时间列、`event_frame_temporal`、`assertion_temporal_relations`、`research_place_relations`、`research_place_versions`），全部挂在副本库新命名空间、不改既有外键图。完整性自检全绿：`quick_check=ok`、`foreign_key_errors=0`、strict 关系契约违例 **0**、无效 time/space owner 引用 **0**、悬挂 EventFrame **0**、非空间层级端点 **0**。

对应 12 报告七项判定中：STKG-1（身份声明化）、STKG-2（帧级证据链 + 帧间时序）、STKG-4（Allen 区间代数）、STKG-6（状态自身时间区间）的缺口均已闭合；STKG-3（空间语义）由 U7/U8 建立最小框架（层级 382 边、地名版本 72 行，覆盖有限如实报告）；STKG-5（role-owner 覆盖率）按三票学习规则**零回填**（见 U6 节）——这是规则表判定结果，不是遗漏。

---

## 0. 基线（副本 = V2 升级前，BASELINE 台账）

| 对象 | 行数 |
|---|---|
| research_entities | 152,979 |
| research_assertions | 424,150（strict 112,158 / contextual 268,047 / unresolved 43,945） |
| research_assertion_provenance | 466,312 |
| research_event_frames | 28,065 |
| research_event_assertion_links | 140,830 |
| research_culture_states | 11,532 |
| research_event_relations | 499 |
| research_evolution_transitions | 4 |

自检 `counts_all_match_source = True`：全部基表行数与升级前逐一相符（升级零删改既有行；U2 仅加列打标，物理保留）。

---

## 1. U1 — EventFrame provenance（帧级证据链物化）

**缺口**（12 报告 STKG-2）：provenance 只挂 fact 级，帧无法出示证据。

**实现**：`research_event_assertion_links × research_assertion_provenance` 全链物化为表 `event_frame_provenance(frame_id, assertion_id, provenance_id, provenance_kind, evidence_ids_json)`。

| MEASURED | 值 |
|---|---|
| 物化行数 | 160,245 |
| 帧总数 | 28,065 |
| 有 provenance 的帧 | **27,761（覆盖率 98.9168%）** |
| 无 provenance 的帧 | 304 |
| 可定位证据（evidence 非空数组）帧 | **11,116（覆盖率 39.6081%）** |
| 覆盖的不同断言 | 134,750 |
| 帧 id 与 sem Event 实体命中 | 28,065 / 28,065 |

---

## 2. U2 — 事实状态身份（(s,p,o,τ,λ) 声明式身份）

**缺口**（STKG-1 PARTIAL）：655 组 (s,p,o,time_raw,place_raw) 完全相同的"身份碰撞"并存；身份只是事实上的散列。

**实现**：`research_assertions` 加 `merged_into / merge_rule` 列（物理保留不删行）→ 同 (s,p,o,τ,λ) 组内 canonical = 字典序最小 fact_id，其余打 `merged_into`（归并 provenance）→ 碰撞表 + 身份视图 `v_assertion_state_identity` + 对未合并行的部分唯一索引 `ux_assertions_state_identity`。

| MEASURED | 值 |
|---|---|
| 文本五元组碰撞组 | **655** |
| 处置 = merged | **654** |
| 处置 = kept_distinct_source（归一化 (τ,λ) 分歧，留待 U9） | **1** |
| 状态身份组 / 组内事实 | 774 / 1,551 |
| 打 merged_into 的事实（规则 state_identity_exact_v1） | **777** |
| canonical 事实 | 423,373（= 424,150 − 777） |
| 断言总数（不变） | 424,150 |
| 身份唯一部分索引 | 1（已建） |
| 视图 v_assertion_state_identity 组数 | 423,373 |
| 单身份最大 provenance 成员数 | 10 |
| merged 链自引用/指向非 canonical 违例 | **0** |

655 组 = 审计口径精确复现；残余 `u2_residual_text_quintet_duplicate_canonical_groups = 1` 即唯一 kept_distinct 组（同文本、归一化键分歧，保守不合并）。

---

## 3. U3 — CultureState 时间区间（trusted > asserted > stage）

**缺口**（STKG-6/4 PARTIAL）：state 自身无时间区间，时长退化为 stage 区间。

**实现**：`research_culture_states` 加 `state_time_start/end/precision/source + derived_from_events_json + fallback_to_stage`；三档优先级回填：trusted 成员事件 → asserted 成员事件 → stage 区间（回退显式 `fallback_to_stage=1`，绝不伪装成精确时间）。

| MEASURED | 值 |
|---|---|
| states 总数 / 有 state 时间 | 11,532 / **11,532（100%）** |
| source = member_events_trusted | **1,704** |
| source = member_events_asserted | **2,109** |
| source = stage_interval（fallback_to_stage=1） | **7,719（66.9%）** |
| 精度分布 | stage_interval 7,719 / year 1,831 / period 1,214 / month 768 |
| source-flag 一致性违例 | **0** |

fallback 占 2/3 仍是上游可信时间稀缺的真实信号（12a 预期一致，供 U9/U10 放大）。

---

## 4. U4 — EventFrame 时序（帧间区间比较，非因果）

**缺口**（STKG-2 PARTIAL）：28,065 帧之间无任何时序关系表。

**实现**：`event_frame_temporal(frame_a, frame_b, relation, relation_basis, time_precision, confidence, causality_status)`；候选限制 = **共享参与者**（`research_event_roles.counterpart_id`）的带观测时间帧对（严禁 424k 帧笛卡尔积）；relation 由观测区间比较（before/after/overlaps/during）；`causality_status='not_inferred'` 硬约束。

| MEASURED | 值 |
|---|---|
| 关系行数（= 同主体候选对数） | **8,695**（对照：timed 帧仅 696，笛卡尔积约 24 万对被候选限制排除） |
| 涉及帧 | 528 |
| relation 分布 | after 3,079 / before 2,815 / during 2,713 / overlaps 88 |
| confidence | trusted/trusted=0.9，混合=0.7，asserted/asserted=0.5 |
| 缺 relation_basis 行 | **0** |
| causality_status 违例 | **0** |
| 复算不一致 | **0** |

---

## 5. U5 — Allen 区间关系（断言级时间代数）

**缺口**（STKG-4 PARTIAL）：77,930 条显式区间断言无任何区间-区间关系表。

**实现**：`assertion_temporal_relations(left_fact_id, right_fact_id, relation_code, relation_basis, time_precision, causality_status, computed_at)`；Allen 9 分支（before/after/meets/overlaps/during/contains/starts/ends/equals）；候选限制 = 同实体 subject ∪ 同事件链 ∪ 同 CultureState 主体；仅 canonical（未合并）事实参与。

| MEASURED | 值 |
|---|---|
| 关系行数 | **5,636,370** |
| 候选族 | 同实体 3,248,879 / 同事件 945,385 / 同状态主体 1,442,106 |
| 涉及 left facts | 53,319 |
| relation 分布 | equals 2,755,067 / after 970,961 / before 970,363 / contains 378,696 / during 341,380 / overlaps 140,701 / meets 53,908 / starts 22,927 / ends 2,367 |
| 精度分布 | period 3,953,608 / year 1,428,582 / month 254,180 |
| merged 事实混入 | **0** |
| 缺 basis / 非因果违例 / 自环对 | **0 / 0 / 0** |
| 全量复算不一致 | **0** |

---

## 6. U6 — role-owner 选择性回填（规则表裁判 ⇒ 0 行回填）

**缺口**（STKG-5 PARTIAL）：time_owner 覆盖 1.3%、space_owner 1.9%、time_role='unknown' 81.6%。12a 给出两条全局规则（R1/R2），但**本项目三票共识实验（05_scope_repair v2）已学习并否决了该全局启发式**。

**实现**：唯一裁判 = `CLOSURE3_RULES.json` 的 type→action。规则表实际内容：

| scope 变换类 | action | 三票统计 |
|---|---|---|
| event_location→context_location | **RETAIN** | decided=45，after 胜率 0.133，p=5.4e-7 |
| event_location→relation_location | **UNRESOLVED** | decided=2 < 10 |
| mixed | **UNRESOLVED** | decided=8 < 10 |
| other | **UNRESOLVED** | p=0.302 不显著 |
| unknown→event_occurrence | **UNRESOLVED** | decided=25，after 胜率 0.68，**p=0.1078 ≥ 0.05 不显著** |
| unseen_type_default | UNRESOLVED | — |

⇒ **REWRITE 类 = ∅，回填 0 行**；只测候选、不动数据：

| MEASURED | 值 |
|---|---|
| rewrite_classes | `[]` |
| 候选：unknown→event_occurrence（Event 主体、canonical） | 37,794 |
| 候选：event_location→context_location / relation_location | 7,668 / 7,668 |
| **rows_backfilled** | **0** |
| time_owner 覆盖率（前 = 后） | 1.3373% |
| space_owner 覆盖率（前 = 后） | 1.9003% |
| time_role unknown 率（前 = 后） | 81.6268% |
| space_role unknown 率（前 = 后） | 75.0949% |
| 全局启发式 | False（未使用） |

**诚实结论**：三票参考（110 strong + 77 weak）中 R1 方向虽然 68% 胜率但未过显著性门槛，规则表判 UNRESOLVED；按"只回填 REWRITE 类"的约束，U6 不产生任何 role-owner 覆盖率提升。覆盖率提升需 U9 模型批处理或更大概率值的三票复核，本文如实报告为零。

---

## 7. U7 — 最小空间语义层（research_place_relations）

**缺口**（STKG-3 MISSING）：无结构化政区层级；located_in 为零散断言且有错挂（如 `曹市区 located_in 农救会`）。

**实现**：`research_place_relations(place_relation_id, child_place_id, parent_place_id, relation∈{located_in,part_of,contains,within_basin}, evidence_id, status)`；**类型硬约束：双端 `research_entities.entity_type ∈ {Place, AdministrativeRegion, CulturalSite}`**（组织/人物/概念一律不得为空间端点）。三个确定性来源：

1. **S1 显式断言收编**：strict located_in/part_of → `auto_typed`；contextual → `needs_review`；unresolved 不收编；
2. **S2 行政字段链**：断言 province/city/county 字段成组（city located_in province、county located_in city），地名必须**唯一空间归属**（同名含非空间类型 → type_ambiguous 弃用）；
3. **S3 within_basin**：basin 段（上游/中游/下游）**不是 research_entities 实体**，按类型约束 0 行——省→流域段仍由冻结表 `research_region_hierarchy`（13 条）与 fact 级 `research_assertion_basins` 承载，本表不重复、不虚构父节点。

**配套清洗（规则化，12a"配套清洗"条款）**：父节点名带组织后缀（会/局/部/处/署/所/军/队/校/厂/社/馆/委/厅/司/团/党）→ auto_typed 降级 `needs_review`（上游把农救会等组织误标为 Place，entity_type 硬约束无法拦截，交复核位）；环检测（DFS）→ 环上边 `rejected`。

| MEASURED | 值 |
|---|---|
| 层级边总数 | **382**（全部 located_in） |
| S1 显式断言收编 | 206 |
| S2 字段链 | 478 组候选 → **176 条成边**（302 组弃用：无空间实体 281 / 多空间同名 16 / 类型歧义 5） |
| S3 within_basin | 13 组候选 → **0 条**（basin 段非实体，如实报告） |
| status | auto_typed **372** / needs_review **7** / rejected **3** |
| 组织名父节点复核位（7 个） | 农救会、华同运输公司、成都市军管会、民权镇公所、理化研究所、被服厂、黄都中心校 |
| 环上拒绝（3 条） | 毕节↔贵州 互指 2 条 + 汉口自环 1 条 |
| 非空间端点 / 悬挂 / 自环(active) / 重复对 / 活动环 | **0 / 0 / 0 / 0 / 0** |
| 有父节点的不同地点 | 346 |

样例（auto_typed）：武汉市 located_in 湖北省；南昌市 located_in 江西省；汉口 located_in 湖北武昌；水阳镇 located_in 苏南抗日根据地。

---

## 8. U8 — PlaceVersion 最小框架（research_place_versions）

**缺口**（STKG-3 MISSING）：全库无地名版本；1,982 组同名同类型 Place 实体无时期维度。

**实现**：`research_place_versions(place_version_id, canonical_place_id, historical_name, valid_from, valid_to, admin_level, parent_place_id, evidence_id, status, derived_pattern)`——**只对语料证据句可自动支持的实体名变更建版本**（模式：`原名X/原称X`、`A改称/改名/改为B`、`时属Z`），**无证据不创建**。确定性守卫：

- current 侧名必须**唯一归属空间类型**（人名/组织名同名 → 拒绝，5,758 次命中该守卫）；
- 另一侧名必须是实体名或带政区/地名后缀（117 次拒绝）；
- 泛称（一区/专区类）、归属标记（"划归X改为Y"中的 X 是归属而非旧名）、枚举语境（顿号/右括号前）→ **needs_review 降级**（共 22 行，证据位保留供复核）；
- valid_from 仅取证据句窗口内显式年份（23 行有），无则 NULL，**绝不伪填**；
- 每行必含语料证据 id（`master_data.csv` 的 `id` 列），corpus sha256 入台账。

| MEASURED | 值 |
|---|---|
| 语料扫描行数 | 98,762 |
| 模式关键词命中 | 原名 1,122 / 原称 15 / 改称 678 / 改名 629 / 改名为 480 / 改为 2,947 / 当时属 48 / 时属 17 |
| 版本行数 | **72**（former_name 26 / renamed_to 35 / same_period_parent 11） |
| status | **auto_evidence 45 / needs_review 27** |
| 带显式 valid_from | 23（如 红安县←黄安县 1932、金寨←立煌 1939） |
| 覆盖空间实体 | 62 / 28,667（**0.2163%**，同名多实体各自建行） |
| 类型违例 / 悬挂 / 缺证据 / 自然键重复 | **0 / 0 / 0 / 0** |

样例（auto_evidence，均带语料证据 id）：金寨←立煌（1939）；红安←黄安；红安县←黄安县（1932）；大方←大定；泰县←泰州；东阳镇（时属江北县）。needs_review 样例：一区←三区（泛称）；游击区←苏区（泛称）；江边区←元谋县（"划归元谋县改为江边区"，元谋县实为归属）。

**覆盖有限如实声明**：0.22% 的实体覆盖率符合"证据句模式匹配"的定位；政区沿革 gazetteer 属外部数据源（12a U8 成本栏），本阶段未引入，故同期政区归属/级别版本仍大面积缺失，禁止伪填。

---

## 9. 完整性自检（全量实际查询值，`--verify-only` 终态）

| 检查 | 实际查询值 |
|---|---|
| PRAGMA quick_check | **ok** |
| PRAGMA foreign_key_check 错误数 | **0** |
| 基表行数与升级前逐一相符 | **True** |
| strict 关系契约违例（hierarchy-aware 契约判定） | **0** |
| 无 provenance 断言 | **0** |
| 层守恒违例（tier 非法值） | **0** |
| 历史阶段数 | 8 |
| 无效 time_owner / space_owner / space_anchor / state_subject 引用 | **0 / 0 / 0 / 0** |
| U1 悬挂链行（帧/断言/provenance 失配） | **0** |
| U2 残余状态身份重复 canonical 组 | **0** |
| U2 残余文本五元组重复 canonical 组 | 1（kept_distinct_source，归一化分歧，留 U9） |
| U2 merged 身份不一致 / 指向非 canonical | **0 / 0** |
| U2 pending 碰撞组 | **0** |
| U2 身份视图零 provenance 行 | **0** |
| U3 source-flag 一致性违例 / 无时间状态 / fallback 伪装精确 | **0 / 0 / 0** |
| U4 缺 basis / 非因果 / 复算不一致 / 无共享参与者行 | **0 / 0 / 0 / 0** |
| U5 复算不一致 / 非因果 / 缺 basis / 自环对 | **0 / 0 / 0 / 0** |
| U6 台账回填行数 / REWRITE 类 / 覆盖率与台账一致 | **0 / [] / True** |
| U7 非空间端点 / 悬挂 / 自环(active) / 重复对 / 活动环 | **0 / 0 / 0 / 0 / 0** |
| U7 auto_typed 带组织名父节点 | **0**（7 条已降 needs_review） |
| U8 非空间地点 / 非空间父 / 悬挂 / 缺证据 / 自然键重复 | **0 / 0 / 0 / 0 / 0** |

---

## 10. 副本库最终 MEASURED 计数全表

| 对象 | 行数 | 性质 |
|---|---|---|
| research_entities | 152,979 | V2 原表（未改） |
| research_assertions | 424,150 | V2 原表 + merged_into 标记列（777 merged / 423,373 canonical） |
| ├ strict_semantic | 112,158 | |
| ├ contextual | 268,047 | |
| └ unresolved | 43,945 | |
| research_assertion_provenance | 466,312 | V2 原表（未改） |
| research_event_frames | 28,065 | V2 原表（未改） |
| research_event_assertion_links | 140,830 | V2 原表（未改） |
| research_culture_states | 11,532 | V2 原表 + 6 个时间列（全部有区间） |
| research_event_relations | 499 | V2 原表（未改） |
| research_evolution_transitions | 4 | V2 原表（未改） |
| **event_frame_provenance** | **160,245** | U1 物化表 |
| **research_assertion_identity_collisions** | **655** | U2 碰撞台账（654 merged + 1 kept_distinct） |
| **v_assertion_state_identity** | **423,373** 组 | U2 身份视图 |
| **event_frame_temporal** | **8,695** | U4 帧间时序 |
| **assertion_temporal_relations** | **5,636,370** | U5 Allen 区间关系 |
| **research_place_relations** | **382** | U7 空间层级（372 auto / 7 review / 3 rejected） |
| **research_place_versions** | **72** | U8 地名版本（45 auto / 27 review） |
| stkg_upgrade_log | 9 | BASELINE + U1–U8 台账 |

## 11. 覆盖率汇总（U1–U8）

| 升级项 | 覆盖率（MEASURED） |
|---|---|
| U1 帧→provenance | **98.92%**（27,761/28,065）；可定位证据 39.61% |
| U2 身份去重 | 655/655 组全部处置（654 merged + 1 kept_distinct）；canonical 唯一索引生效 |
| U3 状态时间区间 | **100%**（11,532/11,532；其中 33.1% 来自成员事件、66.9% 显式 stage 回退） |
| U4 帧间时序 | 8,695 对 / 696 带观测时间帧、528 帧入网（候选限制生效，0 笛卡尔积） |
| U5 Allen 关系 | 5.64M 对 / 53,319 left facts；零 merged 混入 |
| U6 role-owner | **0 行回填**（规则表 UNRESOLVED 裁决）；候选 37,794/7,668 已测 |
| U7 空间层级 | 382 边 / 346 地点有父；302 字段链候选因类型歧义弃用；within_basin 0（父节点非实体） |
| U8 地名版本 | 72 行 / 62 实体（**0.22%**，仅语料证据支持者） |

## 12. 局限与后续（如实）

1. **U6 覆盖率零提升是规则裁决结果**：三票学习未通过显著性门槛（p=0.108），依"只回填 REWRITE 类"约束不回填。若需 1.3%→25%+ 的覆盖率，须 U9 模型批处理或三票复核翻案，不应由全局启发式达成。
2. **U7 within_basin 为 0**：basin 段在 KG 中不是实体；省→流域段关系保留在冻结表 `research_region_hierarchy`（13 条）与 fact 级 `research_assertion_basins`。若要入表需先建 BasinSection 实体类型。
3. **U8 覆盖 0.22%**：模式匹配只能覆盖语料中显式改名句；27 条 needs_review（泛称/归属标记/枚举语境）与 U7 的 7 条组织名父节点均已打复核位而非静默收纳；政区沿革 gazetteer（外部源）未引入。
4. **上游类型噪声**：农救会、平汉路局等组织在上游被误标为 Place——entity_type 硬约束因此放行，由名称后缀复核位兜底（7 条）。根治需上游类型修订（超出本副本升级范围）。
5. U2 的 1 组 kept_distinct_source 与 59,526 组 null-vs-值 time_raw 变体仍留给 U9（模型批处理）。

## 13. 复现命令

```bash
cd submission_work/final_submission_v3_1
python code/experiment_pipelines/apply_stkg_upgrades.py                 # U1-U8 + 自检（副本已升级则逐项 SKIP 并打印计数）
python code/experiment_pipelines/apply_stkg_upgrades.py --only U8 --force U8 --no-copy   # 单项强制重建
python code/experiment_pipelines/apply_stkg_upgrades.py --verify-only   # 只跑完整性自检
python -m pytest code/tests/test_stkg_upgrades.py -q                    # 11 项 fixture 测试
```

台账核对：`SELECT upgrade, applied_at, measured_json FROM stkg_upgrade_log ORDER BY upgrade;`
（终态：BASELINE + U1..U8 全记录；最近一次终检 2026-09-11，quick_check=ok、全部不变量为 0。）
