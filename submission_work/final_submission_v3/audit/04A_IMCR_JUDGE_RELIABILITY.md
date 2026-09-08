# 04A — IMCR Judge 面板可靠性与一致性报告

> **证据等级声明**：本报告全部结论属于 **E 级（independent evaluation，独立评价）**。IMCR（独立多模型共识参考）是与生产标签构造链解耦的外部 AI 参考标注，**不是**事实真值、不是人工金标准（`audit/03_IMCR_PROTOCOL.md` §1 术语边界）。本报告所有"一致性"均指"与独立 AI 参考的一致性"，不得表述为"事实正确率"（GOAL §二十七措辞边界）。
>
> 编号说明：GOAL §二十九 要求 `04_IMCR_JUDGE_RELIABILITY.md`，该编号已被 `04_BASELINE_DESIGN.md` 占用，故本文件按任务约定使用 `04A_` 前缀。

- 报告日期：2026-09-07（数字提取自 2026-09-08 冻结的实验产物）
- 依赖证据：`experiments/08_independent_reference/`（JUDGE_RELIABILITY_SUMMARY.csv、JUDGE_PAIRWISE_AGREEMENT.csv、LEAVE_ONE_JUDGE_OUT.csv、IMCR_CONSENSUS_MANIFEST.json、raw_runs/）、`audit/03_IMCR_PROTOCOL.md` §11/§12

---

## 1. Judge 面板构成与两次换型说明

Primary 面板 = 3 个 judge，覆盖 3 个模型家族（`IMCR_CONSENSUS_MANIFEST.json` `model_ids` 字段；`audit/03_IMCR_PROTOCOL.md` §11）：

| 槽位 | 模型（model exact ID） | 家族 | 角色 |
|---|---|---|---|
| Judge A | `Qwen3.6-35B-A3B` | Qwen | judge（非唯一 judge，满足 GOAL 7.2） |
| Judge B | `gpt-5.6-luna` | GPT | judge；同时是 B3 盲 LLM 基线同模型（见 §6 与 12_EXPERIMENT_LIMITS.md） |
| Judge C | `minimax/minimax-m3:free` | MiniMax | judge（OpenRouter free 档） |

**两次换型（协议 §12/§12.1，均有归档与用户确认记录）**：

1. 第一任 Judge A = `Qwen3.5-122B-A10B`，渠道自 2026-09-07 13:25 UTC 起持续挂起（entity_type 339 OK + 43 TRANSPORT_ERROR，`raw_runs/_archived_judgeA_attempts/2026-09-07_qwen3.5-122b/README.md`），更换为 `Qwen3.5-35B-A3B`。
2. 第二任 `Qwen3.5-35B-A3B` 运行约 107 OK 后于 2026-09-08 渠道劣化挂起（118 OK + 26 TRANSPORT_ERROR，`raw_runs/_archived_judgeA_attempts/2026-09-08_qwen3.5-35b/`），最终更换为 `Qwen3.6-35B-A3B`。该渠道在 B3 基线 2830 条连续调用中 0 传输错误、0 无效输出（`INDEPENDENT_BASELINE_MANIFEST.json` `b3_stats`）。

被替换模型的全部记录归档于 `raw_runs/_archived_judgeA_attempts/`（含逐批 README），**不参与共识聚合**；一个 judge 槽位 = 一个模型实例（协议 §12"旧记录处置"）。Judge D（`nvidia/nemotron-3-ultra` free 档）因 HTTP 429 持续失败未入面板（协议 §11；尝试记录 `raw_runs/_archived_nonpanel/2026-09-07_nemotron_smoke/`）。

**正式运行记录完整性**（来源：`raw_runs/{task}/{A,B,C}.jsonl` 逐行统计）：

| 任务 | A（Qwen3.6-35B-A3B） | B（gpt-5.6-luna） | C（minimax-m3:free） |
|---|---|---|---|
| entity_type（382） | 382 OK | 382 OK | 382 OK |
| relation_contract（640） | 640 OK | 640 OK | 640 OK |
| scope_adjustment（208） | 208 OK | 208 OK | 208 OK |
| identity_pair（600） | 600 OK + 2 TRANSPORT_ERROR | 600 OK | 600 OK |
| provenance_support（1000） | 1000 OK | 1000 OK | 962 OK + 38 MODEL_OUTPUT_INVALID |

无效票在计票前剔除、不参与多数决（协议 §6）；provenance_support 上 A–C、B–C 两两比较因此按 962 条共同有效任务计算（`JUDGE_PAIRWISE_AGREEMENT.csv` `n_compared` 列）。调用参数：`temperature=0.0`、`top_p=1.0`、seed=`1220050458`（= `derive_seed("imcr_judge_calls")`）、prompt 版本 `imcr.v3.1`，三 judge 全部一致（raw_runs 各 jsonl 记录字段）。

---

## 2. 共识三档分布（3-judge 规则：3/3 strong、2/3 weak、其余 unresolved）

来源：`JUDGE_RELIABILITY_SUMMARY.csv`（n_strong/n_weak/n_unresolved 列）与 `IMCR_CONSENSUS_MANIFEST.json` `tasks` 数组，两处一致。

| 任务型 | 任务数 | strong (3/3) | weak (2/3) | unresolved |
|---|---|---|---|---|
| entity_type | 382 | 276 | 90 | 16 |
| relation_contract | 640 | 66 | 486 | 88 |
| scope_adjustment | 208 | 111 | 73 | 24 |
| identity_pair | 600 | 399 | 187 | 14 |
| provenance_support | 1000 | 394 | 511 | 95 |
| **合计** | **2830** | **1246** | **1347** | **237** |

- Primary 参考集 = `IMCR_REFERENCE_STRONG.csv`（1246 行，实测行数一致）；Secondary = `IMCR_REFERENCE_ALL.csv`（2593 行 = 1246 + 1347）。unresolved 237 条不进入任何参考集、不强制多数票（`IMCR_CONSENSUS_MANIFEST.json` `n_reference_strong=1246`、`n_reference_all=2593`；协议 §6）。
- leave-one-judge-out 参考集行数：LEAVE_A=1621、LEAVE_B=1640、LEAVE_C=1824（`IMCR_CONSENSUS_MANIFEST.json` `n_reference_leave_one_out`；`IMCR_REFERENCE_LEAVE_B_OUT.csv` 实测 1640 行一致）。

**解读**：strong 档占比在 relation_contract 上只有 66/640 = 10.3%（66/640，来源同表），而在 identity_pair 上为 66.5%（399/600）。这直接预示 §4 的低一致性问题。

## 3. 两两一致率与 Cohen's kappa

来源：`JUDGE_PAIRWISE_AGREEMENT.csv`（保留 4 位小数）。

| 任务型 | 对 | n_compared | 观察一致率 | Cohen's κ |
|---|---|---|---|---|
| entity_type | A–B | 382 | 0.8115 | 0.7916 |
| entity_type | A–C | 382 | 0.8089 | 0.7888 |
| entity_type | B–C | 382 | 0.7827 | 0.7615 |
| relation_contract | A–B | 640 | 0.3703 | 0.1756 |
| relation_contract | A–C | 640 | 0.3875 | 0.0156 |
| relation_contract | B–C | 640 | 0.3109 | 0.1155 |
| scope_adjustment | A–B | 208 | 0.7067 | 0.5422 |
| scope_adjustment | A–C | 208 | 0.6538 | 0.4342 |
| scope_adjustment | B–C | 208 | 0.5913 | 0.3769 |
| identity_pair | A–B | 600 | 0.7983 | 0.4435 |
| identity_pair | A–C | 600 | 0.7600 | 0.4076 |
| identity_pair | B–C | 600 | 0.7483 | 0.4679 |
| provenance_support | A–B | 1000 | 0.6510 | 0.5227 |
| provenance_support | A–C | 962 | 0.5104 | 0.3615 |
| provenance_support | B–C | 962 | 0.5728 | 0.3997 |

## 4. 多 judge 一致性：Fleiss κ、Krippendorff α 与 LOJO 稳定性

来源：`JUDGE_RELIABILITY_SUMMARY.csv`（fleiss_kappa、krippendorff_alpha_nominal、min/mean_leave_one_judge_out_stability 列）；LOJO 逐剔除明细见 `LEAVE_ONE_JUDGE_OUT.csv`。

| 任务型 | Fleiss κ | Krippendorff α (nominal) | 平均两两一致率 | LOJO 稳定性 min / mean | 一致性评级（Landis–Koch 惯例） |
|---|---|---|---|---|---|
| entity_type | **0.7803** | 0.7805 | 0.8010 | 0.8169 / 0.8361 | 好（substantial） |
| scope_adjustment | 0.4492 | 0.4501 | 0.6506 | 0.6685 / 0.7355 | 中等（moderate） |
| identity_pair | 0.4311 | 0.4314 | 0.7689 | 0.7662 / 0.7873 | 中等 |
| provenance_support | 0.4207 | 0.4191 | 0.5781 | 0.5425 / 0.6236 | 中等 |
| relation_contract | **0.0368** | 0.0373 | 0.3563 | 0.3605 / 0.4130 | **接近随机（slight）** |

全任务平均（`JUDGE_AGREEMENT_SUMMARY.csv` task_type=ALL 行，未加权均值）：Fleiss κ = 0.4236，Krippendorff α = 0.4237，平均两两一致率 0.6310，LOJO 均值 0.6791。

LOJO（逐 judge 剔除后参考标签不变比例，`LEAVE_ONE_JUDGE_OUT.csv`）要点：

- entity_type 剔除任一 judge 稳定性 0.8169–0.8470：参考集对单 judge 依赖低。
- relation_contract 剔除 A/B/C 稳定性仅 0.3605/0.4493/0.4293：参考集本身高度依赖面板构成，进一步说明该任务上"参考"不稳定（与 §5 呼应）。
- provenance_support 剔除 B 时稳定性最低（0.5425），与 judge B 在该任务上倾向 `partially_supported`（430/1000，raw_runs/provenance_support/B.jsonl 实测）有关。

## 5. relation_contract 低一致性专属小节（诚实发现，不过度解读）

**事实**：三 judge 在 640 条关系契约任务上的 Fleiss κ = 0.0368、Krippendorff α = 0.0373、平均两两一致率 0.3563（来源同 §4）。这接近"随机一致"水平，是本项目最重要的一条诚实发现：**在当前 payload 信息条件下，"关系契约语义是否成立"没有可复现的独立 AI 参考多数**。

**各 judge 标签分布**（来源：`raw_runs/relation_contract/{A,B,C}.jsonl` parsed_response.decision 实测统计）：

| judge | valid | invalid | context_only | insufficient_evidence | 平均置信度 |
|---|---|---|---|---|---|
| A（Qwen3.6-35B-A3B） | 4 | 212 | 328 | 96 | 0.838 |
| B（gpt-5.6-luna） | 1 | 289 | 8 | 342 | 0.967 |
| C（minimax-m3:free） | 6 | 77 | 366 | 191 | 0.686 |

**可能原因的分层讨论**（按证据强度排序；以下为假设分析，非结论）：

1. **任务信息不足（payload 层面，可证实）**：judge 只能看到主语/谓词/宾语名称与类型 + schema 定义；640 条中仅 3 条命中来源支持样本的真实证据文本（`audit/03_IMCR_PROTOCOL.md` §5.2 明确记录"evidence_excerpts 仅当 fact_id 命中来源支持样本时附带；640 行中 3 行命中"）。换言之，绝大多数条目是在无原文证据的条件下判断谓词语义，judge 之间只能依赖各自先验，分歧自然大。B 将 342/640 判为 `insufficient_evidence`（占 53.4%）与这一限制相符。
2. **标签语义边界的模糊性（任务定义层面）**：`valid / invalid / context_only / insufficient_evidence` 四档中，`invalid` 与 `context_only` 的分界依赖对谓词"严格语义层准入约定"的解释（schema_definitions 摘要进入 payload，但解释空间仍大）。A 与 C 大量使用 `context_only`（328/366），B 几乎不用（8），说明三家模型对该边界的操作化定义实质不同。
3. **模型家族先验差异（模型层面）**：A/B/C 的平均自报置信度 0.838/0.967/0.686 差异明显；B 高置信地集中判 `invalid`+`insufficient_evidence`（631/640），C 低置信地集中判 `context_only`。这种"家族性标签先验"与具体条目质量无关的部分会系统性压低 κ。
4. **真实语义歧义（语料层面，无法排除）**：党史文献中的谓词（如"纪念""参加""位于"的引申用法）本身可能既非严格契约语义也非纯上下文语义；不排除部分条目确无唯一正确标签。

**处理原则**（对应 08_RELATION_CONTRACT_VALIDATION.md）：

- Primary（strong）参考集在该任务上仅 66 条且标签分布偏斜（invalid 36 / insufficient_evidence 24 / context_only 6，`IMCR_REFERENCE_STRONG.csv` 实测），基于它的任何 accuracy 数字都必须与 κ=0.037 一同报告；
- 不得将该任务的任何结果表述为"关系契约有效/无效的证明"；GOAL §十五明确不能再用旧论文 148 条饱和子集（Full 与 w/o 均 148/148）证明 relation contract 有效；
- 结论定位为：**在独立 AI 参考下，关系契约组件的语义有效性未获证明**——这本身是论文的贡献性诚实陈述，而非需要掩盖的失败。

## 6. 面板独立性与 B3 同模型的透明性附注

- B3 盲 LLM 基线 = `gpt-5.6-luna`，与 Judge B 同模型（`INDEPENDENT_BASELINE_MANIFEST.json` `b3_stats.model_ids`；协议 §12.1）。按 GOAL §12.1 处理：B3 的**主对照参考集为 leave-B-out IMCR**（剔除 Judge B 票后按 2-judge 2/2 规则重聚合，`IMCR_REFERENCE_LEAVE_B_OUT.csv`，1640 行）；对 Primary 的结果只作透明性附注，用于量化同模型自证膨胀（详见 06/05 号报告）。
- leave-Qwen-out（= LEAVE_A_OUT，1621 行）作为 Qwen 家族独立性对照保留（`IMCR_CONSENSUS_MANIFEST.json` `loo_reference_judge="A"`；LEAVE_QWEN_OUT 与 LEAVE_A_OUT 文件 sha256 相同：`6f41e1b3…`）。

## 7. 小结（供论文 4.1 节引用）

1. 面板满足 GOAL 7.2/7.4：3 judge、3 家族、Qwen 非唯一 judge；raw_runs 共 8492 行 judge 调用记录（2830 任务 × 3 judge = 8490 成功目标行，另含 judge A 在 identity_pair 上的 2 条 TRANSPORT_ERROR 记录），每行 11 字段日志齐全（逐目录实测）。
2. entity_type 上一致性好（Fleiss κ=0.7803），scope/identity/provenance 中等（0.42–0.45），relation_contract 接近随机（0.0368）——后续所有 per-task 结论的可信度必须按此分级陈述。
3. strong 共识覆盖 1246/2830（44.0%），即 Primary 口径只评价"三 judge 完全一致"的子集；weak 档与 unresolved 的存在本身就是盲评不完美的量化，必须写进论文而非隐藏。
