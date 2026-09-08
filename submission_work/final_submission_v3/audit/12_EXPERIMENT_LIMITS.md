# 12 — 实验局限清单（诚实披露）

> 本报告逐条列出 IMCR 独立评价体系的局限。目的不是弱化结论，而是给论文写作与读者划出证据强度的边界。每条局限均注明影响范围与已在何处缓解。

---

## L1. 3 个 judge 均为 AI 模型，不是领域专家，也不是人类盲评

- 影响范围：全部 E 级结论。
- 说明：面板为 Qwen3.6-35B-A3B / gpt-5.6-luna / minimax-m3:free（`IMCR_CONSENSUS_MANIFEST.json` `model_ids`）。模型 judge 与人类专家在党史史实判断上可能存在系统性差异（训练数据偏差、时代叙事差异）。所有结论只能表述为"独立 AI 参考下的一致性"。
- 缓解：协议 §1 术语边界强制；judge ≥3 且 ≥2 家族；报告全部使用 IMCR 称谓而非"金标准"。
- 残余风险：三家模型可能共享相似的预训练语料偏差，"家族独立"不等于"认知独立"。无法用本项目数据量化。

## L2. relation_contract 任务上 judge 一致性接近随机（κ=0.037）

- 影响范围：08 号报告全部数字、论文 4.5 节关系契约部分。
- 说明：Fleiss κ=0.0368、两两一致率 0.3563（`JUDGE_RELIABILITY_SUMMARY.csv`）；strong 仅 66/640。机制上与 payload 证据稀缺直接相关：640 条中仅 3 条附带真实证据文本（协议 §5.2 明文）。
- 缓解：低一致性作为主发现如实写；结论定位为"未证明"而非"无效"；LOJO 与多口径（strong/all/leave-B）并列展示。
- 残余风险：任何基于该任务参考的单点数字（如 B12 的 0.024）都可能随参考构成翻转（leave-B 口径 B12 changed 组升至 0.681，08 号报告 §4）。

## L3. B3 盲 LLM 与 Judge B 同模型（gpt-5.6-luna）

- 影响范围：所有 B3 相关比较（05/06 号报告）。
- 说明：Judge A 槽位两次渠道故障后，B3 由 Qwen3.6-35B-A3B 改为 gpt-5.6-luna（协议 §12.1），与 Judge B 同模型。B3 对主参考（含 Judge B 票）的一致率存在自证膨胀，relation 上最严重（0.9394 → leave-B 0.2863，差 0.653）。
- 缓解：按 GOAL §12.1，B3 的主对照参考集固定为 leave-B-out（`IMCR_REFERENCE_LEAVE_B_OUT.csv`，1640 行，2/2 规则）；对主参考的数字只作膨胀量化附注。
- 残余风险：leave-B-out 参考仅 2 judge 弱共识，覆盖数少（1640 vs 2593）、且 2/2 规则下评委分歧条目全部退场；B3 与 Judge A/C 无同模型问题，但"盲 LLM 与 judge 共享第三方语料先验"不可排除。

## L4. Judge A 槽位两次换型与单网关依赖

- 影响范围：面板构成、运行时间线。
- 说明：Judge A 依次为 Qwen3.5-122B-A10B（339 OK + 43 TRANSPORT_ERROR 后渠道挂起）→ Qwen3.5-35B-A3B（约 107 OK 后同模式挂起）→ Qwen3.6-35B-A3B（`raw_runs/_archived_judgeA_attempts/` 两份 README；协议 §12/§12.1）。Judge D（nemotron-3-ultra free 档）因持续 HTTP 429 未能入面板（协议 §11）。三个在役 judge 全部经同一网关 218.197.140.7:3001（Qwen 槽位）或 OpenRouter free 档（minimax），存在单点依赖。
- 缓解：换型均经用户确认、旧记录整体归档不混票；最终模型在 2830 条 B3 调用中 0 传输错误。
- 残余风险：正式运行（2026-09-07 10:04 UTC 至 09-08 00:39 UTC）跨两次故障窗口，A 的五个任务全部由第三任模型 fresh 完成；无法排除不同时期渠道负载对响应质量的未观测影响。

## L5. OpenRouter free 档（Judge C）的无效输出

- 影响范围：provenance_support 任务两两统计的分母。
- 说明：judge C 在 provenance_support 上 38/1000 条达到重试上限记 MODEL_OUTPUT_INVALID（`raw_runs/provenance_support/C.jsonl` 实测），A–C、B–C 两两一致性按 962 条计算（`JUDGE_PAIRWISE_AGREEMENT.csv` `n_compared`）。
- 缓解：无效票剔除制（协议 §6）、不手工改答案（GOAL §二十）。
- 残余风险：被剔除的 38 条可能系统性地更难，unresolved 率在该任务被轻微低估。

## L6. unresolved 237 条（8.4%）不进入任何参考集

- 影响范围：全部 per-task 分母。
- 说明：3-judge 无多数即 unresolved（entity 16 / relation 88 / scope 24 / identity 14 / provenance 95；`JUDGE_RELIABILITY_SUMMARY.csv`），共识管线不强制多数票（协议 §6）。评价只覆盖参考可判定子集（strong 1246 或 all 2593）。
- 缓解：三档分布全文公开；unresolved 计数在图C 等图件中显示。
- 残余风险：能被一致判定的条目可能偏"容易"，方法在难条目上的行为未被评价；论文必须写明分母是"参考覆盖数"而非全样本。

## L7. 生产端 B12 的三条结构性披露

1. **entity_type 328/382 条 fallback_unresolved**：生产实体类型字段在冻结时点有 328 条无置信度且 type_validation_status=fallback_unresolved（`IMCR_BASELINE_RUNS.csv` note 实测），硬门如实编码后 B12 entity 的 score coverage 只有 0.1486（`imcr_strong_RISK_COVERAGE_SUMMARY.csv`）。Full 的 entity 高一致率（0.9268）只在 41 条接受集上成立。
2. **恒不预测"判伪"标签**：relation 的 `invalid`、provenance 的 `unsupported`/`contradicted` 生产端无对应档位（`audit/04_BASELINE_DESIGN.md` §4.2/§4.5）。参考判该类标签时 B12 自动计错——这是映射口径的必然，不是系统"漏判"的同义词，论文必须写明。
3. **scope/identity 无逐条置信**：不虚构代理分数（设计 §10），代价是这两个任务无 B12 风险–覆盖曲线，面积类结论缺失。

## L8. scope_adjustment 评价的方向性约束

- 影响：07 号报告。
- 说明：B12 恒预测 AFTER_BETTER（闭包后即系统主张），评价是"单点主张 vs 五选一参考"，无法区分"闭包后更差"与"闭包后无差异但 judge 偏好噪声"；且参考本身 BEFORE 58 vs AFTER 51（strong）接近对半，微弱多数不能支撑强结论。
- 缓解：win/tie/loss、多口径、McNemar 并报；结论限定为"未获支持"而非"变差"。

## L9. 统计功效与小样本

- 影响：全部区间宽度。
- 说明：strong 口径下 relation 仅 66 条（B12 接受集 42 条）、scope 111 条；Wilson CI 与 bootstrap 区间宽（如 B12 relation 一致率 CI [0.0042, 0.1232]，`WILSON_CI_TABLE.csv`）。配对 bootstrap 仅 1 个配对通过面积门（provenance，`STATISTICAL_ANALYSIS_MANIFEST.json` `bootstrap.applicable_pairs=1`），其余 49 对显式 not_applicable。
- 缓解：GOAL §十八要求的全套指标（n/coverage/correct/error/estimate/CI + macro-F1）已全量落盘；未通过门的配对给出显式状态而非删除。
- 残余风险：多重比较未做校正；24+ 个 McNemar 检验的 p 值应视为探索性。

## L10. 单一种子与确定性

- 说明：主种子 20260907 贯穿抽样（如 entity 派生种子 1348020344，`ENTITY_TYPE_SAMPLE.manifest.json`）、judge 调用（1220050458）、A/B 盲化（11613091355876745079，`SCOPE_ADJUSTMENT_EXTRACTION_AUDIT.json`）、bootstrap（逐配对派生）。全部固定种子、可复现，但没有多种子方差估计；temperature=0 也使模型侧无随机性。
- 缓解：seed 策略与逐 replicate 落盘（GOAL §13.2/§21）。

## L11. 证据文本可用性不均

- 说明：五类任务中只有 provenance_support（1000/1000）与 scope（部分）携带真实来源文本；relation 仅 3/640（见 L2）；entity/identity 提供的是上下文断言与别名而非原文节选（协议 §5.1/§5.4）。judge 的"证据不足"回答率差异（B 在 relation 342 次 insufficient）部分源于此。
- 缓解：payload 内以 evidence_availability_note 如实标注不可用（协议 §5.3）。

## L12. 未覆盖的旧论文数字

- 说明：983 册 / 302,230 页 / 282,165 条候选 / 67,791 条本地证据 / 98,762 条关键词元数据 / 17,450 条裁决等旧稿数字仍为 UNVERIFIED（`audit/PAPER_CLAIM_EVIDENCE_MATRIX.csv` F 级行）；IMCR 未触及效率实验（07_efficiency）与演化实验（v3 无新数据）。这些数字在论文中只能删除、降级表述或补充证据，不得与 IMCR 结果混排。
