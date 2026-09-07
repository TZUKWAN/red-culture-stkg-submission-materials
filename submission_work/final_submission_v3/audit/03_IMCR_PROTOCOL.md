# 03 IMCR 协议：独立多模型共识参考（Independent Multi-model Consensus Reference）

- 文档版本：imcr-protocol v1.0（2026-09-07）
- 适用代码：`code/independent_eval/`（blind_payload / judge_client / consensus / manifest）与 `code/experiment_pipelines/`（imcr_task_defs / build_judge_payloads / run_judges / build_imcr_consensus）
- 协议依据：`GOAL.md` 第三节（术语边界）、第七节（盲化与共识）、第八至十一节（任务定义）、第十九至二十一节（运行日志、输出校验、可重复性）
- 主种子：v3 master seed = 20260907；各任务派生种子 = `SHA-256(task_name|20260907)` 前 8 字节取模 2³¹（`code/independent_eval/_common.py::derive_seed`）

---

## 1. 术语边界（强制性）

IMCR 是一套**与生产标签构造链解耦的外部 AI 评价参考**，不是事实真值。

**允许的称谓**（论文与报告中只能使用这些）：

- 独立多模型共识参考
- 外部 AI 参考标注
- 独立 AI 共识评价集

**禁止的称谓**（GOAL 第三节）：

- 不得称“人工金标准”
- 不得称“ground truth”
- 不得称“事实真值”

理由：ERA（Integrated Reference Annotation，712 条）的产生与规则、source type、lexical hint、schema vote、历史 Qwen 输出等生产信号存在不同程度共享，不能继续作为新实验的唯一外部正确性依据。IMCR 仍然属于 AI 评价，只是其判断通道与生产标签构造链解耦。任何基于 IMCR 的结论必须表述为“在独立 AI 参考下的一致性/支持度”，不得表述为“事实正确率”（GOAL 第二十七节措辞边界）。

## 2. 盲化规则

### 2.1 白名单机制（judge 可见字段）

每个任务类型在 `code/experiment_pipelines/imcr_task_defs.py::PIPELINE_TASK_SPECS` 中以 `TaskSpec.allowed_fields` 显式声明 judge 可见字段。**白名单之外的任何字段一律不进入 payload**。judge 只能看到（GOAL 7.1）：

1. 待判断对象本身（名称、断言文本、状态 a/b 等）；
2. 必要的原始文本证据（真实证据原文节选，未内置时明确标注）；
3. 必要的局部关系上下文（来源层面谓词表面形式等）；
4. 冻结后的 Schema 定义（类型相容性约定摘要）；
5. 必要的类型定义（实体类型 / time_role / space_role 定义表）；
6. 必要的任务说明（prompt 模板）。

### 2.2 黑名单机制（judge 绝不可见）

以下生产信号不得以任何形式进入 judge payload——既不得作为任意嵌套层级的字典键，也不得作为 token 嵌入字符串值（`blind_payload.py::BLACKLIST_KEYS` / `BLACKLIST_VALUE_TOKENS`，键先做规范化：小写、非字母数字归为 `_`）：

`era` / `era_label` / `gold_label` / `gold` / `prediction` / `predicted_label` / `final_label` / `risk_tier` / `semantic_status` / `auto_accepted` / `review_status` / `lexical_hint` / `schema_votes` / `cached_llm_prediction` / `cached_qwen_prediction` / `classifier_prediction` / `rule_prediction` / `model_confidence` / `historical_model_confidence` / `correctness_flag` / `correct` / `canonical_entity_id` / `merge_status` / `majority_label` / `consensus_label` / `reference_label` / `human_label`

条件性黑名单：`source_type` 当其本身为待评价信号时一并盲化（本协议 5 类任务全部启用 `blind_source_type=True`，从严处理）。

同时禁止：

- 把生产系统输出作为 prompt 中的“参考意见”；
- scope_adjustment 任务中向 judge 透露状态 a/b 与 closure 前/后的对应关系；
- identity_pair 任务中提供 canonical_entity_id、最终 merge 结果、existing mapping status（GOAL 10.2）。

### 2.3 泄漏拦截与检测

- **构建期拦截**：`build_blind_payload` 对白名单输出与最终 payload 做两轮深度扫描（键 + 字符串值），任何命中立即抛 `LeakageError`，整个 payload 构建中止——不静默剔除、不放行。
- **独立检测**：`code/tests/test_no_production_label_leakage.py` 与 `code/tests/test_pipeline_build_payloads.py` 自动检查 payload 中不出现 GOAL 第 22 节点名的全部字段。
- **本批验证**：已对 5 类任务全部 2830 条生成 payload 逐条执行 `scan_for_leakage` 并对 payload 文件全文检索 `risk_tier|semantic_status|auto_accepted|gold_label|era_label|release_tier|changed_set|sample_role|canonical_entity_id|merge_status`，零命中（见本文件第 10 节）。

### 2.4 A/B 随机化（before/after 盲化）

scope_adjustment 任务的 closure 前/后两个状态，先依据既有 `experiments/10_structural_validation/SCOPE_ADJUSTMENT_AB_MAPPING.csv` 把 `state_a/state_b` 解析为 before/after 语义，再由 `build_blind_payload` 依据 `SHA-256(f"{seed}::{task_id}")` 首字节奇偶确定性随机化为展示位 a/b。payload 中只出现 `a`/`b`，**不出现 before/after 字样**；a/b 与 before/after 的映射写入独立文件 `experiments/08_independent_reference/payloads/SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING.csv`（列：task_id, a, b, seed），该文件不向 judge 暴露。judge 以 `A_BETTER/B_BETTER` 作答，共识聚合阶段再据映射解码回 `BEFORE_BETTER/AFTER_BETTER`（`build_imcr_consensus.py::decode_ab_label`）。

## 3. Judge 配置要求

### 3.1 数量与家族

- 至少 **3 个**独立 judge 模型；API 资源允许时优先 **5 个**（GOAL 7.2）。
- judge 必须来自 **至少 2 个不同模型家族**。
- 生产过程中使用过的 **Qwen 不得成为唯一 judge**；当 Qwen 在 judge 面板中时，Primary 参考须另附 **leave-Qwen-out** 版本（剔除 Qwen 票后按同一共识规则重聚合，复用 `consensus.leave_one_judge_out` 的逐剔除机制）——以避免“同一模型既生成 prediction 又参与 reference majority、再计算它与自身参考的一致率”（GOAL 12.1）。
- 一个模型不能看到另一个模型的输出；**第一层标签必须真正独立**，不得使用“模型辩论后统一答案”。

### 3.2 配置方式

judge 通过环境变量槽位 `JUDGE_A` … `JUDGE_E` 配置，每个槽位三个变量（`JUDGE_{NAME}_BASE_URL` / `JUDGE_{NAME}_API_KEY` / `JUDGE_{NAME}_MODEL`），模板见仓库根目录 `.env.example`。API Key 只能从环境变量读取，严禁写入 Python 文件、JSON、CSV、Git、日志、论文（GOAL 19）；客户端在写盘前主动擦除任何 key 出现（`judge_client.JudgeClient._redact`）。

`run_judges.py` 自动发现已配置槽位；一个都未配置时明确报错并提示 `.env.example`。共识档位由实际参与 judge 数决定：只允许 3 或 5，其他数量（如 4）会被 `build_imcr_consensus.py` 拒绝。

### 3.3 调用参数

默认 `temperature=0.0`、`top_p=1.0`，调用种子 = `derive_seed("imcr_judge_calls")`；API 支持 seed 时随请求发送并记录。

## 4. Judge 输出 JSON schema

每个 judge 对每条任务输出且仅输出一个 JSON 对象（GOAL 7.3；校验实现 `judge_client.validate_judge_output`）：

```json
{
  "task_id": "<原样回填>",
  "decision": "<该任务 allowed labels 之一>",
  "confidence": 0.0,
  "evidence": ["<证据摘录或要点>"],
  "reason_code": "<机器可读原因码>",
  "explanation": "<中文简要说明>",
  "insufficient_evidence": false
}
```

校验规则：必须可解析为 JSON（容忍 markdown 代码围栏）；7 个字段齐全且类型正确；`task_id` 与请求一致；`decision ∈ allowed_labels`；`confidence ∈ [0,1]` 且为数值；`insufficient_evidence` 为真布尔。不允许自由文本代替结构化 label。

非法输出触发有界重试（最多 3 次追加尝试）；达到上限标记 `MODEL_OUTPUT_INVALID` 并落盘原始响应，**绝不手工改答案、绝不为凑共识修改 judge 结果**（GOAL 20）。

## 5. 各任务定义与 allowed labels

### 5.1 entity_type（实体类型，GOAL 8.1）

- 样本：`experiments/08_independent_reference/ENTITY_TYPE_SAMPLE.csv`（382 行，分层抽样）。
- judge 可见：entity_name、aliases、context_assertions、source_excerpt、candidate_types、type_definitions。
- allowed labels：`Person / Event / Place / Organization / Institution / Concept / Document / Artifact / CreativeWork / Spirit / ValueFacet / AdministrativeRegion / CulturalSite / SocialGroup / Position / TimePeriod / OTHER`（16 个实际存在类型 + OTHER；抽样分层属性只用于抽样，不进 prompt）。

### 5.2 relation_contract（关系语义/关系契约，GOAL 8.2、十五节）

- 样本：`experiments/08_independent_reference/RELATION_CONTRACT_SAMPLE.csv`（640 行 = 320 changed + 320 matched control）。`sample_role`、`changed_set_full_tier`、`changed_set_wo_tier`、`risk_tier`、`semantic_status`、`release_tier` 等全部为生产标签，不进入 payload。
- judge 可见：subject_text/subject_type、relation_text（谓词）、object_text/object_type、evidence_excerpts（仅当 fact_id 命中来源支持样本的真实证据文本时附带；640 行中 3 行命中，其余为空——judge 可据此判 insufficient_evidence，该限制如实保留）、schema_definitions（严格语义层准入约定摘要）。
- allowed labels：`valid / invalid / context_only / insufficient_evidence`。
- 派生比较（下游分析，不在 payload 内）：changed 行的 before 状态 = w/o Relation Contract 层（strict_semantic），after 状态 = Full framework 层（contextual）；以 IMCR 标签映射评价 before/after 何者与独立证据一致（valid→strict 准入正确；invalid/context_only→contextual 路由正确）。

### 5.3 scope_adjustment（时空作用域调整，GOAL 8.3/8.4、九节）

- 样本：`experiments/10_structural_validation/SCOPE_ADJUSTMENT_TASKS.jsonl`（**208 条全量**，不抽样）。
- judge 可见：assertion_text（由 subject/predicate/object 名称与类型、时间/空间表述组成；`semantic_status`/`risk_tier`/`research_tier` 已剔除）、evidence_excerpts 与 evidence_availability_note（发布库仅存谱系指针、原始文本未内置的说明如实展示）、local_relation_context（来源谓词表面形式）、schema_definitions（time_role/space_role 定义表）、匿名状态 a/b。
- allowed labels（a/b 展示位语义）：`A_BETTER / B_BETTER / EQUIVALENT / BOTH_WRONG / INSUFFICIENT_EVIDENCE`；共识后解码为 `BEFORE_BETTER / AFTER_BETTER / EQUIVALENT / BOTH_WRONG / INSUFFICIENT_EVIDENCE`。
- 下游指标（GOAL 九节）：before/after correctness、delta、paired improvement、95% CI、win/tie/loss、paired bootstrap CI、binary matched 时加 McNemar。

### 5.4 identity_pair（实体规范化/身份投影，GOAL 十节）

- 样本：`experiments/11_identity_validation/IDENTITY_PAIR_TASKS.jsonl`（600 对，含 positive merge candidate 与真实 hard negative）。
- judge 可见：name_a/name_b、aliases_a/aliases_b、relation_context_a/relation_context_b（各自独立）、time_info、space_info、evidence_a/evidence_b。绝不提供 canonical_entity_id、merge 结果、mapping status。
- allowed labels：`same_entity / different_entity / insufficient_evidence`。

### 5.5 provenance_support（来源支持度，GOAL 十一节）

- 样本：`experiments/12_provenance_validation/PROVENANCE_SUPPORT_SAMPLE.csv`（1000 行，strict_semantic/contextual/unresolved 三层分层；分层标签本身不进入 payload）。
- judge 可见：assertion_text（主—谓—宾 + 时间/空间表述）、evidence_excerpts（真实来源文本，多段以 `---` 分隔已拆为列表）、citation_metadata（来源书名）。不允许用结构化后的 statement 冒充 source evidence。
- allowed labels：`fully_supported / partially_supported / unsupported / contradicted / insufficient_evidence`。

## 6. 共识规则（GOAL 7.4）

| 面板规模 | strong_consensus | weak_consensus | unresolved |
|---|---|---|---|
| 3 judge | 3/3 一致 | 2/3 一致 | 其余 |
| 5 judge | ≥4/5 一致 | 3/5 一致 | 其余 |

- 无效票（`MODEL_OUTPUT_INVALID` / 缺失 / 传输错误）在计票前剔除，不参与多数决。
- **unresolved 不得强制多数票生成伪真值**：`consensus_label` 对 unresolved 返回 `label=None`，参考集中不出现该任务。
- **Primary evaluation 只使用 strong_consensus**（`IMCR_REFERENCE_STRONG.csv`）；**Secondary evaluation 使用 strong + weak**（`IMCR_REFERENCE_ALL.csv`）。
- leave-one-judge-out：逐一移除一个 judge 按缩减面板（3→2 时 2/2 一致记 weak；5→4 不允许，需预先固定面板为 3 或 5）重聚合，检查最终标签稳定性（`LEAVE_ONE_JUDGE_OUT.csv`）。

## 7. 一致性统计（GOAL 7.5）

每任务类型计算并输出：

- `JUDGE_PAIRWISE_AGREEMENT.csv`：两两 judge 的观察一致率（co-valid 任务上）+ Cohen's kappa；
- `JUDGE_RELIABILITY_SUMMARY.csv`：任务数、共识三档计数、平均两两一致率、Fleiss' kappa、Krippendorff's alpha（nominal，支持缺失票）、LOJO 稳定性最小/均值；
- `LEAVE_ONE_JUDGE_OUT.csv`：逐 judge 剔除后的标签稳定率。

实现全部复用 `code/independent_eval/consensus.py`，管线脚本不重写任何统计量。

## 8. 运行日志（GOAL 19，每次调用 11 项字段）

`raw_runs/{task_type}/{judge}.jsonl` 每行记录：

`model_id`、`provider`（base_url 主机名）、`prompt_version`、`temperature`、`top_p`、`seed`、`timestamp`（UTC ISO-8601）、`raw_response`、`parsed_response`、`retry_count`、`validation_error`

另附 `task_id`、`judge_name`、`status`（OK / MODEL_OUTPUT_INVALID / TRANSPORT_ERROR）、`dry_run`、`task_type`、`prompt_sha256`。API key 与 Authorization 头绝不落盘。

## 9. 可重复性（GOAL 21）

- payload 构建清单：`payloads/PAYLOAD_BUILD_MANIFEST.json`——每任务文件的行数、prompt_sha256、payload/输入文件 sha256、A/B 种子、code commit、时间戳；
- 共识清单：`IMCR_CONSENSUS_MANIFEST.json`——model_ids、共识分布、输出文件 sha256、dry_run 标记；
- prompt 模板版本：`imcr.v3.1`（`imcr_task_defs.PROMPT_VERSION`），模板文本固定于代码中，prompt_sha256 随每条记录落盘；
- 追踪链：paper claim → 表/图 → IMCR CSV → raw JSONL → task_id → 样本文件 → 原始证据。

## 10. 证据等级标注约定

- IMCR 及其全部派生结果标注为 **E 级（independent evaluation）**，与旧 ERA 体系结果（D 级 shared-reference diagnostic / C 级 cached model output）明确区分；论文表格必须保留该证据等级列（GOAL 第二节）。
- **DRY_RUN 约定**：`run_judges.py --dry-run` 产生的一切文件只进 `experiments/08_independent_reference/dry_run/`，记录与 manifest 均带 `dry_run: true`，目录内附 `README_DRY_RUN.txt`；dry-run 数字**严禁**进入论文或正式报告，也不得与真实 judge 输出混放。
- 本批已完成的 DRY_RUN 验证（每类 12 条 × 3 假 judge，仅验证链路，非实验结果）共识分布：entity_type strong 0 / weak 5 / unresolved 7；relation_contract 0/7/5；scope_adjustment 1/6/5；identity_pair 2/9/1；provenance_support 0/4/8。
