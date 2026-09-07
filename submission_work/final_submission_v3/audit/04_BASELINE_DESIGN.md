# 04 — IMCR 独立基线实验设计（GOAL Phase 6，B1–B12）

状态：DESIGNED 2026-09-07（judge 运行期定稿；实现必须逐条遵守本文件，任何偏离须先改本文件并记录原因）。

## 0. 目标与总体口径

所有新基线统一在 IMCR 参考集上评价（GOAL 十二）。不得使用旧缓存结果假装 fresh run；无法运行的基线显式记 `NOT_AVAILABLE`，不得用替代实现冒充。

- **Primary 参考集**：`IMCR_REFERENCE_STRONG.csv`（3-judge strong，GOAL 7.4）。
- **Secondary 参考集**：`IMCR_REFERENCE_ALL.csv`（strong + weak）。
- **独立性对照参考集**：`IMCR_REFERENCE_LEAVE_QWEN_OUT.csv`（剔除 judge A=Qwen 家族槽位，B/C 两票 2/2 一致记 weak_consensus，其余 unresolved 不落盘；GOAL 12.1）。
- 评价器：`run_selective_inference.py --reference imcr_strong / imcr_all`（LOQ 对照用同一评价器以 `--imcr-strong-path/--imcr-all-path` 指向 LOQ 文件运行）。
- 基线预测一旦由本设计固定，**不得因结果不利而回改**（GOAL 第二节）。

## 1. 任务集与 sample_id 命名空间

| task_type | n | sample_id 前缀 | item_id 字段 |
|---|---|---|---|
| entity_type | 382 | ETV3- | IENTREPAIR- 规范实体 |
| relation_contract | 640 | RC-S- | IFACT- 断言 |
| scope_adjustment | 208 | SA- | IFACT- 断言 |
| identity_pair | 600 | IDP3- | pair_id（两实体） |
| provenance_support | 1000 | PRV3- | IFACT- 断言 |

与 v2 ERA 的 159 样本（ET-/ER-/... 前缀）零交集（已验证），不存在样本复用。

## 2. 输出 schema（23 列，与 v2 BASELINE_RUNS.csv 完全同构）

```
sample_id, task_type, item_id, split, method_id, method_name, evidence_class,
comparison_tier, overlap_status, primary_comparison_eligible, evaluation_eligibility,
availability_status, gold_label, prediction, confidence, covered, correct,
hard_constraint_pass, constraint_gate_source, safe_correct, actual_llm_calls,
source_artifact, note
```

固定取值：`split=independent_eval`；`evidence_class=actual_run`；`comparison_tier=independent_reference`；`overlap_status=independent_of_era`；`primary_comparison_eligible=1`；`covered=correct=safe_correct=0`（由 `apply_imcr_reference` 在评价时按参考标签重算并过滤）；`gold_label=""`（ERA gold 不适用于 IMCR 样本）。`note` 必须写明该行预测所用的映射规则（见 §4/§5）。

## 3. 基线 × 任务型可用性矩阵

| 基线 | entity_type | relation_contract | scope_adjustment | identity_pair | provenance_support |
|---|---|---|---|---|---|
| B1 Rule-only | ✓ 规则引擎 | ✓ 契约表 | N/A | N/A | N/A |
| B2 Frozen classifier | ✓ 冻结分数表 | N/A | N/A | N/A | N/A |
| B3 Blind LLM | ✓ | ✓ | ✓ | ✓ | ✓ |
| B4 Rule+classifier | ✓ | N/A | N/A | N/A | N/A |
| B5 Rule+blind LLM | ✓ | ✓ | N/A | N/A | N/A |
| B6 Classifier conf 阈值 | ≡B2 曲线 | N/A | N/A | N/A | N/A |
| B7 Classifier margin | ✓（独立行） | N/A | N/A | N/A | N/A |
| B8 Entropy 阈值 | ✓（joblib proba 可得时） | N/A | N/A | N/A | N/A |
| B9 Rule-model agreement gate | ✓ | ✓（model=blind LLM） | N/A | N/A | N/A |
| B10 选择性、无结构门 | ✓ | ✓ | ✓ | ✓ | ✓ |
| B11 结构门、无弃权 | ✓ | ✓ | ✓ | ✓ | ✓ |
| B12 Full framework | ✓ | ✓ | ✓ | ✓ | ✓ |

N/A 行照样落盘（`availability_status=not_available`，prediction/confidence 空，note 注明 `NOT_AVAILABLE: <原因>`），保证方法×任务网格完整、缺口可审计。B6 不另发重复行：B2 的置信阈值扫描即 B6（报告中同名引用），避免同数双计；B7/B8 是不同置信信号，发独立行。

## 4. 生产端（B12 及其派生）预测映射——逐任务型

生产字段一律以冻结时点 release 库为准（sidecar 元数据/直查 final DB，均只读）。

### 4.1 entity_type（B12）
- prediction = `research_entities.entity_type`（规范实体发布类型）。
- confidence = `research_entities.confidence`。
- hard_constraint_pass = `type_validation_status=='validated'`（生产类型门）。
- source_artifact=`production_release_fields`；note 记 `entity_type+type_validation_status`。

### 4.2 relation_contract（B12）——release_tier → IMCR 四标签映射
- `strict_semantic` → `valid`；`contextual` → `context_only`；`unresolved` → `insufficient_evidence`。
- **`invalid` 恒不预测**（披露：生产端无"判伪"标签，未准入断言只落在 unresolved 档）。
- confidence = `research_assertions.confidence`；gate = `semantic_status=='auto_accepted' AND risk_tier∈{A,B}`。

### 4.3 scope_adjustment（B12）
- prediction = `AFTER_BETTER` 恒定（闭包后状态即系统主张；IMCR 解码标签空间）。
- confidence = 空（`research_scope_adjustments` 无分级置信字段；不虚构代理分数）→ 无风险-覆盖曲线，仅点指标。
- gate = 1（调整即发布的一部分）。
- 评价语义（严格口径，论文须披露）：参考 `AFTER_BETTER` 才算 correct；`EQUIVALENT/BOTH_WRONG/INSUFFICIENT/BEFORE_BETTER` 均计 error。win/tie/loss 分布在 14 号实验另行报告。

### 4.4 identity_pair（B12）
- prediction = 规范成员共属查询：`research_entity_members` 中 entity_a_id 与 entity_b_id 落入同一 canonical_entity_id → `same_entity`，否则 `different_entity`。
- confidence = 空（生产身份归并无逐对分级置信）。
- gate = 1。

### 4.5 provenance_support（B12）——research_tier → IMCR 五标签映射
- `strict_semantic` → `fully_supported`；`contextual` → `partially_supported`；`unresolved` → `insufficient_evidence`。
- **`unsupported/contradicted` 恒不预测**（披露：生产端未建模这两种判定）。
- confidence = `research_assertions.confidence`；gate = `n_provenance_rows>0`（发布安全不变量）。

## 5. 规则/分类器基线（B1/B2/B4/B7/B8/B9）

### 5.1 B1 Rule-only
- entity_type：复用 v2 规则引擎（`stkg_v2_semantics.fuse_entity_type` + `strong_entity_type_hint` + `v2_assertion_scopes` schema votes）。规范实体先在成员级（源级 IENT-）逐个求规则预测，聚合取置信最高成员的预测；并列取成员间多数类型，再并列取类型字典序。confidence = 所选成员置信。gate = 对所选预测执行 `entity_model_contraindication`。
- relation_contract：查 `research_relation_contract`：谓词存在且 subject_type∈source_types ∧ object_type∈target_types → (`valid`, 0.99)；谓词存在但类型不兼容 → (`invalid`, 0.90)；谓词未知 → 弃权（prediction 空）。gate = 预测 `valid`。
- 其余任务型 NOT_AVAILABLE（无对应规则组件）。

### 5.2 B2 Frozen classifier（仅 entity_type）
- 冻结生产分类器分数表 `data/source_data/stkg_v2_entity_classifier.sqlite::entity_predictions`（源级 IENT- 键；列 predicted_type/confidence/margin/class_gate_pass）。
- 成员聚合与 B1 同法（最高置信成员）。gate = 所选成员 `class_gate_pass`。成员无分数行的实体 → `availability_status=not_available`。
- **B7**：同行预测，confidence = 所选成员 margin。**B8**：经 joblib 重载打 proba 时计算归一化熵 `1−H/Hmax`（聚合取所选成员文本）；joblib 不提供 proba 则 B8 全网格 NOT_AVAILABLE。

### 5.3 B4 / B5 / B9
- B4（entity_type）：规则有预测用规则（置信、门随规则），否则用 B2 预测。
- B5（entity_type、relation_contract）：规则有预测用规则，否则用 B3 盲 LLM 预测。
- B9（entity_type：model=B2；relation_contract：model=B3）：prediction = 规则预测（规则弃权则空）；confidence = 规则与模型预测一致 ? 1.0 : 0.0（两档信号；面积指标自然不适用）。

## 6. B3 Blind LLM（独立于 judge 面板的 fresh 调用）

- **模型**：`Qwen3.6-35B-A3B` @ 218.197.140.7:3001（judge A 为 Qwen3.5-122B-A10B——不同模型实例；且 §12.1 允许"Qwen 作 baseline 时配 leave-Qwen-out 参考"）。
- **输入**：与 judge 完全相同的冻结盲化 payload（`payloads/*.jsonl`）与 prompt 模板——B3 与 judge 的差异只在模型与调用参数记录。
- **调用合规**：沿用 `judge_client`（环境变量 `BLIND_LLM_BASE_URL/API_KEY/MODEL`，temperature=0、top_p=1、seed=derive_seed("blind_llm_baseline")，JSON 校验+有界重试+MODEL_OUTPUT_INVALID 落盘，11 字段日志全存）。
- **解码**：scope_adjustment 的 A_/B_ 标签按 `payloads/SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING.csv` 解码回 BEFORE/AFTER（与 judge 共识同一映射文件）。
- **gate**：对 B3 预测执行与 B1 同型的硬约束检查（entity_type：TYPE_FAMILY+contraindication；relation_contract：契约类型兼容；其余任务型 gate=1）。
- **评价**：主对照 = `IMCR_REFERENCE_LEAVE_QWEN_OUT.csv`；同时报告对 Primary 的结果作透明性附注。confidence = 模型自报 confidence。

## 7. B10 / B11（选择性机制消融，作用于 B12 预测）

- B10 = B12 预测，`hard_constraint_pass=1` 全体（结构门禁用；constrained 曲线退化为纯分数曲线）。
- B11 = B12 预测，confidence 恒 "1.0"（无弃权；曲线单点 coverage=1）。
- 二者与 B12 共用 prediction 列，method_id/name 不同，note 注明消融语义。

## 8. 管线与产物

```
code/experiment_pipelines/run_independent_baselines.py     # B1/B2/B4-B12（B3 除外）
code/experiment_pipelines/run_blind_llm_baseline.py        # B3 fresh 调用
  → experiments/09_independent_baselines/IMCR_BASELINE_RUNS.csv        （B3 就绪后合并）
  → experiments/09_independent_baselines/BASELINE_AVAILABILITY_MATRIX.csv
  → experiments/09_independent_baselines/INDEPENDENT_BASELINE_MANIFEST.json
评价：
  run_selective_inference.py --runs-path 09/IMCR_BASELINE_RUNS.csv \
      --reference imcr_strong [--imcr-strong-path 08/IMCR_REFERENCE_LEAVE_QWEN_OUT.csv 用于 B3 对照] \
      --output-dir 13/imcr_strong --output-prefix imcr_strong_   （imcr_all 同理）
```

- `run_blind_llm_baseline.py` 单独产出 `IMCR_BLIND_LLM_RUNS.csv`；`run_independent_baselines.py --append-runs <file>` 合并去重（键：sample_id+task_type+method_id）后写最终 IMCR_BASELINE_RUNS.csv。合并与生成全程幂等。
- manifest 记录：各方法×任务行数、NOT_AVAILABLE 注册表、B3 model_id/调用统计、生产字段映射策略版本、DB SHA-256（复用 `_common.db_manifest`）。
- 评价的门：`baseline_experiment_audit.json` 等价物 = `09/INDEPENDENT_BASELINE_AUDIT.json`（result=PASS 要求：网格完整、无 NOT_AVAILABLE 行携带预测、映射策略校验和一致）。

## 9. 统计检验接线（14 号实验输入）

- Full(B12) vs B1/B2/B3/B6 的 ΔAURC/ΔAUGRC：paired bootstrap（共同重采样索引，2000 replicates，逐 replicate 落盘）。
- 逐方法×任务 coverage/accuracy：Wilson 95% CI。
- scope_adjustment：B12 vs B3 的 McNemar（binary paired：IMCR=AFTER_BETTER 与否）；win/tie/loss。
- judge 一致性：Fleiss/Krippendorff/LOJO 已由 08 输出，14 只做汇总引用。

## 10. 明确不做

- 不为凑曲线给 scope/identity/provenance 发明代理性置信分数。
- 不把 judge 的票复用为 B3 预测（fresh 调用强制）。
- 不在 B12 映射之外引入任何"更利于叙事"的标签改写。
- B 系列预测文件生成后冻结；重算仅允许修正实现 bug（须在 manifest 记 changelog）。
