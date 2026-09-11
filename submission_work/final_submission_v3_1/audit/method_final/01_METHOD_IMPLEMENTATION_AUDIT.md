# 01 — 方法实现审计：生产机制精确规范与 S0 保真重构（P0-B / P0-C）

日期：2026-09-09 ｜ 工作目录：`submission_work/final_submission_v3_1/`
被审计对象：`code/experiment_pipelines/run_selective_semantic.py`（entity_type 选择性语义实验，382 规范实体，S0–S10）
生产代码依据（逐行核对，以真实代码为准）：

- `code/scripts/256_label_and_fuse_stkg_v2_semantics.py`（规则侧融合，528 行）
- `code/scripts/260_train_evaluate_stkg_v2_entity_classifier.py`（冻结分类器，392 行）
- 依赖：`final_submission_v3/data/external_inputs/stkg_v2_semantics.py`、`stkg_contract.py`
- 实验信号重放：`final_submission_v3/code/experiment_pipelines/run_independent_baselines.py`（B1/B2/B7 的生成方式）

---

## 0. 结论摘要

1. **生产分类器准入路径（260）与任务书预期一致**：classifier prediction → class-specific reliability gate → lexical/schema support（agreement，硬性资格合取）→ strict contradiction guard（词法严格提示不一致即否决）→ eligible/abstain。**不存在**"规则存在就用规则否则用分类器"的无条件回退。
2. 旧 S0_full 的"规则行存在即替换预测"+ agreement 计分加成 + 守卫/结构门信号重叠，与生产机制不符，且导致 **S3、S5 消融为空操作**（旧 dev 数字：S0/S3/S5 coverage=0.591、sel_acc=0.320 完全相同）。
3. 重构：新增 `S0_production_faithful`（1:1 复刻生产准入机制）；旧逻辑整体保留为 `S0_rule_first_legacy` 供对比；S1–S5 相对 faithful 版**各只改一个声明组件**；全部输出行新增 `changed_components` 字段。
4. 两处**已声明偏差**（均有代码级论证，见 §3.3/§3.4）：类门阈值选择准则（样本量限制）与 contra/词法否决的组件归属（旧归属导致消融退化）。

---

## 1. 生产机制精确规范（逐行核对）

### 1.1 规则侧（256 `label_entities` → `fuse_entity_type`）

每个源级实体（`v2_entities`）的输入信号：

| 信号 | 来源 | 缺失行为 |
|---|---|---|
| `source_type` | `v2_entities.source_entity_type` | 恒存在 |
| `lexical` | `refine_lexical_hint(name, source_type, strong_entity_type_hint(name))` = `strict_v2_entity_type_hint(name, source_type)`（严格词法提示；子串匹配一律弃权，返回 `""`） | `""` = 无词法信号 |
| `schema_votes` | `collect_schema_votes`：遍历 `v2_assertion_scopes` 的受控谓词；`RELATIONS[p]` 的 `source_types` 为单集时 subject 投一票，`target_types` 为单集时 object 投一票 | 空 Counter = 无 schema 信号 |
| `cross_type_name` | 同一 `canonical_name` 的 distinct source_entity_type 数 > 1 | False |

`fuse_entity_type(source_type, lexical, schema_votes, cross_type_name)` 决策表（`stkg_v2_semantics.py` L469–518，精确抄录）：

```
schema_decisive := top_schema 且 top_count>=2 且 top_count-second_count>=2
若 cross_type_name:
    若 preserve_specialized_source_in_name_collision(...)      → source_type, auto_accepted, conf=0.98, risk=B
    若 schema_decisive 且 (无 lexical 或 lexical==top_schema)   → top_schema,  auto_accepted, conf=0.97, risk=B
    否则                                                        → None, model_review, conf=None, risk=C
若 lexical 且 lexical != source_type:
    若 source_type∈SPECIALIZED_TYPES 且 lexical=="Event" 且非 decisive → None, model_review, C
    若 schema_decisive 且 top_schema∉{lexical, source_type}     → None, model_review, C   # lexical_schema_conflict
    否则                                                        → lexical, auto_accepted, conf=0.98, B
若 schema_decisive 且 top_schema != source_type                 → top_schema, auto_accepted, conf=0.96, B
若 lexical==source_type 或 (decisive 且 top_schema==source_type) → source_type, auto_accepted, conf=0.98, A
否则                                                            → source_type, auto_accepted, conf=0.92, B
```

关键语义：
- **规则侧自身就有弃权**：`model_review` 实体的 `final_type=None`，不进入严格语义层（256 报告 limitations 明示"model_review entities are unresolved and are not admitted to the strict semantic layer"），转成 `v2_model_tasks` 的 pending 任务交给分类器（260）。
- `entity_model_contraindication` **不在 256 中调用**；它在生产/评价体系中的角色是**硬约束结构门**（V3 `run_independent_baselines.entity_rule_gate`：`TYPE_FAMILY 成员 ∧ ¬entity_model_contraindication`，B12 的 constraint gate），用于否决 model label，其 docstring 即"Reject high-confidence model labels that contradict strict entity semantics"。

### 1.2 分类器侧（260）——生产准入机制本体

**特征/训练**（L228–245）：name char TF-IDF(1–4 gram, min_df=2, max_features=180k, sublinear) ⊕ relation-context word TF-IDF（`OUT/IN::predicate::邻接实体有效类型` 计数 top-80；邻接类型用 `semantic_entity_type or source_entity_type`）；`SGDClassifier(loss="log_loss", penalty="elasticnet", alpha=2e-6, l1_ratio=0.05, max_iter=40, tol=1e-4, class_weight="balanced", random_state=20260714, average=True)`。训练集 = `auto_accepted` 且留出验证折之外的实体。

**类特异性可靠门（class gate）**（L38, L64–86, L260–272）：在生产验证折上按**预测类别**分组，对置信网格 `THRESHOLDS=(0.90, 0.95, 0.98, 0.99, 0.995)` 逐档计算 support/precision/Wilson LB95；合格 = `support>=50 ∧ precision>=0.98 ∧ wilson_lower_95>=0.95`；取**最小合格档**；无合格档 → **该类无门（None）**。

**pending 实体准入决策**（L274–305，精确抄录语义）：

```
predicted        = argmax predict_proba            # 分类器预测，永不被规则替换
confidence       = max predict_proba               # 原始置信，无校准
margin           = p(1) - p(2)                     # 仅记录，不参与准入
lexical          = refine_lexical_hint(name, source_type, strong_entity_type_hint(name)) or None
schema_top       = task payload schema_votes 的 most_common（无票则 None）
agreement        = predicted ∈ {lexical, schema_top}（排除空值）
strict_not_contra= (not lexical) or (lexical == predicted)   # 词法严格否决
gate             = class_gates[predicted]          # 类门按预测类取
gate_pass        = gate 存在 且 confidence >= gate.threshold
eligible_rule_candidate = gate_pass AND agreement AND strict_not_contra
```

### 1.3 缺信号时的行为（生产）

| 缺失信号 | 生产行为 |
|---|---|
| 无 lexical 且无 schema 票 | `agreement=False` → **不 eligible**（弃权。独立信号一致性是硬性资格条件） |
| lexical 缺失（None/""） | strict guard 自动通过（`not lexical` 为真）；agreement 退化由 schema_top 决定 |
| 预测类无 class gate | `gate_pass=False` → **不 eligible** |
| 实体非 pending（无分类器任务） | 分类器根本不产生预测；实体类型由规则侧 256 决定 |
| 规则侧 model_review（融合弃权） | 无规则类型 → 进入分类器路径，按上述准入判定 |

---

## 2. 与旧 S0_full 的差异清单（重构前 → 生产）

| # | 组件 | 旧 S0_full（重构前） | 生产（256/260） | 判定 |
|---|---|---|---|---|
| D1 | 预测源 | `if rule_p: pred=rule else pred=clf`——规则行存在即替换分类器 | 分类器路径中 prediction 恒为分类器输出；规则类型只属于规则侧（256），且规则侧自身可弃权（model_review）。B1 行存在 ≠ 融合 auto_accepted | **不符，重构** |
| D2 | 证据一致性 | agreement 仅作 score+0.1 软加成（可被阈值淹没；规则来源才生效） | 硬性资格合取：agreement=False → 不 eligible（260 L304） | **不符，重构** |
| D3 | 置信/分数 | isotonic 校准；规则来源时用规则置信 | 原始 max proba，无校准、无加成 | **不符，重构**（faithful 版用原始 B2 置信） |
| D4 | 矛盾守卫 | `entity_model_contraindication` 非空即否决（作为独立守卫） | 生产分类器准入的 strict guard = 词法严格提示不一致（`lexical ∧ lexical≠pred`，260 L293）；`entity_model_contraindication` 的生产角色是结构硬约束门 | **归属错位，重构**（见 §3.4） |
| D5 | 结构准入 | TYPE_FAMILY 成员 ∧ ¬contra | V3 生产评价体系 `entity_rule_gate` 同款（TYPE_FAMILY ∧ contra） | 一致，保留 |
| D6 | 类门阈值来源 | DEV 上以 utility+coverage-floor 网格学习（P0-A 修复后） | 生产验证集固定网格 + precision≥0.98 ∧ WilsonLB≥0.95 ∧ support≥50 取最小合格档 | **已声明偏差**（见 §3.3） |
| D7 | 守卫/结构信号重叠 | contra 同时出现在守卫与结构门（`structural_ok = TF ∧ ¬contra`）→ S3 消融在逻辑上被结构门包含，**退化为空操作**（旧 dev：S0=S3=S5 cov 0.591 / sel_acc 0.320） | 生产中两信号本就不同（词法 guard vs contraindication 结构门） | **消融不纯，重构** |

---

## 3. S0_production_faithful 重构规范

### 3.1 信号源（沿用现有 frame，确定性生产组件重放）

| 实验信号 | frame 来源 | 生产对应物 |
|---|---|---|
| `pred` / `conf` | B2 分类器行（生产 260 冻结模型重放，select_best_member 聚合） | predicted / confidence（原始 max proba） |
| `margin` | B7 行；**按生产原样仅记录、不参与准入** | margin |
| 规则/词法-_schema 独立证据 | B1 规则行 prediction = 256 `fuse_entity_type` 重放（含 schema votes；model_review 时无行/无预测） | lexical + schema_top 的融合产物 |
| `lexical` | `sem.refine_lexical_hint(name, primary_source_type, sem.strong_entity_type_hint(name))` 现场重算 | 260 L285 同式 |
| contraindication / TYPE_FAMILY | `sem.entity_model_contraindication` / `sem.TYPE_FAMILY` 现场重算 | V3 硬约束门同款 |

### 3.2 决策流水线（每样本，按生产 260 L292–304 顺序）

```
① 候选信号   pred=B2 预测, conf=B2 原始置信；B2 缺失 → 弃权(no_candidate_signal)   [生产：非 pending 无分类器输出]
② 类门       θ = θ_c[pred]（DEV 学习）；θ 缺失(类未见) → 弃权(no_class_gate)；
             conf < θ → 弃权(class_gate_abstain)                                    [生产：gate 缺失/不达阈值 → 不 eligible]
③ 证据一致性 agreement := (rule_pred 存在 且 rule_pred == pred)；
             不满足 → 弃权(evidence_agreement_fail)                                 [生产：agreement 为硬性资格合取]
④ 矛盾守卫   lexical 存在 且 lexical != pred → 否决(contradiction_guard, violation=1) [生产：strict_signal_not_contradicted]
⑤ 结构准入   pred ∉ TYPE_FAMILY 或 contra(name,stype,pred) 非空 → 否决(structural_admission, violation=1) [生产硬约束门]
⑥ eligible   ①–⑤ 全过 → accepted，score=conf                                        [生产：eligible_rule_candidate]
```

组件清单（声明组件，供消融与 changed_components 使用）：`candidate_source`（①，分类器候选+原始置信）、`class_gate`（② 的类特异性 θ_c）、`abstention`（② 的阈值弃权行为）、`evidence_agreement`（③）、`contradiction_guard`（④）、`structural_admission`（⑤）。

### 3.3 已声明偏差一：类门阈值选择准则（必然的样本量适配）

生产准则要求每个类在验证折上 support≥50（置信≥0.90 档）。本实验仅 382 样本（DEV=254，且 B2 行覆盖 347），任何单类都不可能达到 support≥50 → 逐字复刻会使**所有类无门、全弃权**，实验退化。因此 faithful 版保留生产的**类门结构**（按预测类的置信阈值；类未见→弃权），但阈值改由 DEV 上 `learn_threshold`（utility 最大化 + coverage floor 0.30，P0-A 修复后的既有机制）学习。这是实验级 n 的强制适配，非自由发挥；生产的网格/Wilson 准则原样记录于 §1.2 供审阅。学习输入 = DEV 上分类器候选的 (原始置信, 预测对独立参考的是非) 对——与生产 `per_class_rows`（验证折 (confidence, correct) 对）同构；correct 依旧先于阈值学习回填（P0-A 契约）。

### 3.4 已声明偏差二：contraindication 否决归属结构门，词法否决归属矛盾守卫（消融单变量纯度所必需）

任务书中 S3 的字面描述（"去 contraindication 否决"）沿自旧实现；但旧实现中守卫（contra）⊂ 结构门（TYPE_FAMILY ∧ contra），去掉守卫后结构门仍否决同一批样本——**S3 是空消融**（旧 dev 数字 S0=S3=S5 为证）。以真实代码为准：生产分类器准入的 strict contradiction guard 就是**词法严格提示不一致否决**（260 L293），而 `entity_model_contraindication` 的生产角色是**结构硬约束门**（V3 `entity_rule_gate`，其 docstring 明示"reject model labels"）。重构后每个否决信号唯一归属一个组件：

- `contradiction_guard`（S3 消融）= 词法严格否决（生产 260 语义）；
- `structural_admission`（S5 消融）= TYPE_FAMILY + contraindication（与任务书 S5 描述逐字一致，与 V3 生产硬约束门同款）。

两变体均非退化、互不包含，且各自更贴近其生产对应物。

### 3.5 S2 拆分论证（agreement 与 fusion 解绑）

旧实现中 agreement 语义绑定规则优先融合：agreement 仅在"规则来源且与分类器一致"时对 score +0.1，去掉它必然牵动候选源。faithful 版中候选源恒为分类器（生产语义），agreement 是纯准入合取（生产 260 语义），与候选源选择**正交**。因此 S2（去 agreement）不触碰 fusion——规则优先融合完整保留在 `S0_rule_first_legacy` 与 S9/S10 基线中供对比。

### 3.6 忠实性核对表

| 生产机制要素 | faithful 实现 | 状态 |
|---|---|---|
| prediction = 分类器 argmax，不被规则替换 | ① pred=B2 | 精确 |
| confidence = 原始 max proba（无校准/加成） | ① conf=B2 原始置信 | 精确 |
| margin 仅记录不参与决策 | frame 记录，不进入判定 | 精确 |
| 类特异性门按预测类取、缺门弃权 | ② θ_c[pred]，未见类弃权 | 结构精确；选择准则见 §3.3（已声明偏差） |
| agreement 硬性资格合取（无独立信号→弃权） | ③ rule_pred（=256 融合重放）缺失或不一致→弃权 | 精确¹ |
| strict guard = 词法严格提示不一致否决 | ④ 同式重算 lexical | 精确 |
| contraindication = 结构硬约束门（TYPE_FAMILY+contra） | ⑤ 同款 | 精确 |
| 规则侧融合自身弃权（model_review） | B1 无行 → ③ 自然失配弃权 | 精确 |
| 阈值/校准只在 DEV 学习 | θ_c/θ_global 仅 DEV 学习；faithful 不使用校准 | 精确 |

¹ 生产 agreement 集合为 {lexical, schema_top}，实验 frame 不携带逐实体 schema 票（B1 融合已聚合之），以 B1 融合输出为独立证据代理——已声明映射（§3.1）。

---

## 4. 单变量消融组件表（P0-C）

每个消融变体相对 `S0_production_faithful` **只改变一个声明组件**；候选源与分数（prediction/score 输入）在 S0 与 S1–S5 间**逐样本恒等**（由 `tests/test_ablation_single_component_only.py` 固化）。

| 变体 | 改变的唯一组件 | 改动内容 | 不变组件 |
|---|---|---|---|
| S1_wo_class_gate | class_gate | 按类 θ_c → 全局 θ_global（DEV 学习） | 候选源/分数/agreement/守卫/结构/弃权机制 |
| S2_wo_evidence_agreement | evidence_agreement | 移除准入合取③ | 候选源/分数/类门/守卫/结构/弃权（fusion 不在 faithful 路径中，见 §3.5） |
| S3_wo_contradiction_guard | contradiction_guard | 移除词法否决④ | 候选源/分数/类门/agreement/结构/弃权 |
| S4_wo_abstention | abstention | 去阈值弃权（②不再因 conf<θ 弃权） | 候选源/分数/agreement/守卫/结构（守卫全保留） |
| S5_wo_structural_admission | structural_admission | 移除 TYPE_FAMILY+contraindication 门⑤ | 候选源/分数/类门/agreement/守卫/弃权 |

### changed_components 字段定义

所有变体输出行新增 `changed_components`（相对 S0_production_faithful 改变的声明组件，逗号分隔；S0 本身 = `none`）：

| 变体 | changed_components |
|---|---|
| S0_production_faithful | `none` |
| S0_rule_first_legacy | `candidate_source,score_calibration,evidence_agreement`（规则优先替换候选源；isotonic 校准+规则置信；agreement 由硬合取退化为 +0.1 加成。守卫/结构/弃权组件同名保留） |
| S1…S5 | 单组件名（见上表） |
| S6_rule_only | `candidate_source,class_gate,abstention,evidence_agreement,contradiction_guard,structural_admission` |
| S7_classifier_only | `class_gate,abstention,evidence_agreement,contradiction_guard,structural_admission`（候选源与 S0 相同） |
| S8_blind_llm_only | `candidate_source,class_gate,abstention,evidence_agreement,contradiction_guard,structural_admission` |
| S9_rule_plus_classifier / S10_rule_plus_blind_llm | `candidate_source,class_gate,abstention,evidence_agreement,contradiction_guard,structural_admission` |

---

## 6. DEV 首跑结果与机制活性诊断（--reference strong --split dev，2026-09-09）

学习结果（只在 DEV 上）：faithful θ_global=0.90，θ_c 13 类（Person/Place/Institution=0.95，Event=0.85，Organization=0.80，Concept=0.80，Document/CreativeWork=0.65，Spirit=0.55，AdministrativeRegion=0.45，Artifact/Position/ValueFacet=0.05）；legacy θ_global_legacy=0.35（旧路径）。

| 变体 | coverage | selective_accuracy | selective_risk | changed_components |
|---|---|---|---|---|
| S0_production_faithful | 0.059 (15/254) | 0.267 | 0.733 | none |
| S0_rule_first_legacy | 0.591 (150/254) | 0.320 | 0.680 | candidate_source,score_calibration,evidence_agreement |
| S1_wo_class_gate | 0.024 (6/254) | 0.167 | 0.833 | class_gate |
| S2_wo_evidence_agreement | 0.425 (108/254) | 0.296 | 0.704 | evidence_agreement |
| S3_wo_contradiction_guard | 0.059 (15/254) | 0.267 | 0.733 | contradiction_guard |
| S4_wo_abstention | 0.079 (20/254) | 0.300 | 0.700 | abstention |
| S5_wo_structural_admission | 0.059 (15/254) | 0.267 | 0.733 | structural_admission |
| S6_rule_only | 0.283 | 0.389 | 0.611 | （见 §4） |
| S7_classifier_only | 0.906 | 0.226 | 0.774 | （见 §4） |
| S8_blind_llm_only | 1.000 | 0.697 | 0.303 | （见 §4） |
| S9_rule_plus_classifier | 0.996 | 0.285 | 0.715 | （见 §4） |
| S10_rule_plus_blind_llm | 1.000 | 0.610 | 0.390 | （见 §4） |

**忠实性交叉验证（生产重放口径）**：382 样本中 B2 可用 347；生产自身类门（冻结模型自带的 class_gate_pass）放行 109（31.4%）；规则-agreement 29；生产门∧agreement = **10**。即按生产原始阈值，382 样本也只有 ~10 个 eligible 候选。faithful S0 在 dev 接受 15/254（DEV 学习阈值低于生产 0.90+ 网格）与生产机制的天然产出完全同量级——**低覆盖率是生产准入机制的属性，不是实现缺陷**。

**阶段活性诊断（dev 逐阶段）**：254 样本中 230 有分类器候选 → agreement 通过仅 20 → 门后 17 → **在 agreement+门通过子集内，词法守卫与结构门零触发**（全帧上词法守卫会在 16 例触发、contra 在 25 例触发，但这些样本全部 agreement 失配——词法/规则证据与分类器冲突时融合自然不一致，与生产 `eligible_rule_candidate` 的设计动机一致）。因此：

- dev 上 S3≡S0、S5≡S0 是**数据性质**（否决条件与 agreement 通过集不相交），不是构造退化：`tests/test_ablation_single_component_only.py` 用命中各组件条件的 fixture 证明 S3/S5 的组件独立可触发且只影响声明组件；在 S2 放开 agreement 的大候选池上，守卫+结构门的合计效果清晰可见（S2 0.425 vs S7 0.906）。
- 解释力度提示：在 382 规范实体样本上，agreement 合取是主导约束（S0→S2 覆盖 0.059→0.425），类门次之（S0→S1 反而 0.059→0.024，因全局 θ=0.90 高于多数类的 θ_c），守卫/结构门在该机制路径内为零触发——论文报告消融表时应同时给出各组件的条件触发率（本节数字），避免把"零触发"误读为"组件无用"。

---

## 7. 不变性约束（本轮保持）

1. **P0-A 回归不回退**：`fill_correct(variants, reference)` 在 `main()` 中先于 `learn_threshold(dev_controller)`；阈值/正确性仍由独立参考回填驱动；`tests/test_threshold_learning_uses_reference_correctness.py` 全部通过。
2. 阈值只在 DEV split 学习；无任何手工常数取代学习值（isotonic 校准仅 legacy 家族沿用，亦只在 DEV 拟合）。
3. 数据信号冻结不变（B1/B2/B7/B3 行、IMCR 参考、frozen splits）；本审计只改变"选择机制"的构造。
4. 旧 S0 数字可复现性：`S0_rule_first_legacy` 保留旧逻辑全路径（规则优先融合、isotonic 校准、+0.1 加成、独立学习的 legacy θ_c），用于与 faithful 版对照。
