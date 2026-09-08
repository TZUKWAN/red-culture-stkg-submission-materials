# 09 — 身份投影 / 实体规范化独立验证报告

> **证据等级声明**：本报告全部结论属于 **E 级（independent evaluation，独立评价）**。"同实体/不同实体"的判定均为"与独立 AI 参考一致"，相关风险均应表述为"身份误合并风险"，不得表述为"错误合并了真实历史人物"之类的事实性断言（GOAL §二十七）。

- 任务集：`experiments/11_identity_validation/IDENTITY_PAIR_TASKS.jsonl`（600 对）与 `IDENTITY_PAIR_METADATA.csv`（600 行）
- 参考集：`IMCR_REFERENCE_STRONG.csv` / `IMCR_REFERENCE_LEAVE_B_OUT.csv` 中 task_type=identity_pair 行
- 盲化：payload 不含 canonical_entity_id、merge 结果、mapping status（协议 §2.2/§5.4）
- 评价输入：`IMCR_BASELINE_RUNS.csv`（B12/B3/B1 等 identity_pair 行）

---

## 1. 600 对的构成（正例 / 硬负例）

来源：`IDENTITY_PAIR_METADATA.csv` 实测计数。

| 字段 | 取值分布 |
|---|---|
| pair_kind | **positive_merge_candidate 300 / hard_negative 300** |
| true_merge_status | merged_same_canonical 300 / distinct_canonical 300 |
| name_relation | same_name 510 / similar_name 90 |
| category | identity_reduction 300、org_vs_place_same_name 60、same_name_mixed_type 60、same_name_person 50、similar_name_person 50、alias_name_collision 40、event_vs_work_same_name 40 |

硬负例即"名字相同/相似但生产系统判定为不同规范实体（或同名异型）的对照对"，其存在使"全预测 same_entity"的作弊策略无法得高分——这是相对旧 ERA 评价的关键设计升级。

## 2. judge 一致性

来源：`JUDGE_RELIABILITY_SUMMARY.csv`（identity_pair 行）。

- Fleiss κ = 0.4311、Krippendorff α = 0.4314、平均两两一致率 0.7689（观察一致率高而 κ 中等：三 judge 都倾向 `same_entity`，类别不均衡拉低κ）；
- LOJO 稳定性 0.7662–0.8174（`LEAVE_ONE_JUDGE_OUT.csv`）；
- strong/weak/unresolved = 399/187/14；
- strong 参考标签构成（`IMCR_REFERENCE_STRONG.csv` 实测）：same_entity 356 / different_entity 41 / insufficient_evidence 2。

单票行为差异（`raw_runs/identity_pair/*.jsonl` 实测）：A 判 insufficient_evidence 仅 4 次，B 111 次，C 105 次——分歧主要来自"证据不足以判定"的门槛差异，而非同/异的直接对立。

## 3. B12（生产身份归并）与 B3（盲 LLM）一致率

来源：`imcr_strong/..._SELECTIVE_GOAL13_METRICS.csv`、`WILSON_CI_TABLE.csv`、leave_b_out 同名文件；分组数字为 `IMCR_BASELINE_RUNS.csv` × `IDENTITY_PAIR_METADATA.csv` × 参考 CSV 联表实测。

| 口径 | B12 总体 | B12 正例 | B12 硬负例 | B3 总体 | B3 正例 | B3 硬负例 |
|---|---|---|---|---|---|---|
| imcr_strong (参考 n=399) | 0.6466 [0.5985, 0.6919]（GOAL13/Wilson 口径 n=399，含 2 条参考 insufficient 记错；分组联表剔除后分母 397） | **217/217 = 1.000** | **41/180 = 0.228** | 0.9524 [0.9268, 0.9693]（n=399，同上口径） | 216/217 = 0.995 | 162/180 = 0.900 |
| leave_b_out (参考 n=456) | 0.6404（GOAL13 口径 n=456；剔除参考 insufficient 后 292/454=0.6432） | 230/230 = 1.000 | 62/224 = 0.277 | 0.8662（n=456 口径） | 221/230 = 0.961 | 172/224 = 0.768 |
| leave_a_out（剔除参考 insufficient 后分母 402 = 449−47） | 0.6517（262/402） | 218/218 = 1.000 | 44/184 = 0.239 | 0.9502（382/402） | 217/218 = 0.995 | 165/184 = 0.897 |

分母约定说明：GOAL13/Wilson 口径把参考标签为 insufficient_evidence 的条目按错误计入（分母=参考全部行）；分组联表口径将其剔除（分母少 2 条，strong）/少 2 条（leave-B）。两口径数字并报，论文择一并注明。

**核心发现（必须如实写入论文，注意方向）**：

1. **生产身份归并在正例上零分歧**：所有口径下 B12 对 positive_merge_candidate 的一致率为 1.000——已合并对全部被独立参考确认同实体，**没有任何证据显示生产系统存在已提交的误合并（false merge）**。
2. **硬负例分歧的方向是"参考判同、生产判异"**：strong 参考下 B12 硬负例一致率 0.228（41/180）。联表实测（`IMCR_BASELINE_RUNS.csv` × `IDENTITY_PAIR_METADATA.csv` × `IMCR_REFERENCE_STRONG.csv`）：180 个被评价硬负例中，参考判 same_entity 139、different_entity 41，而 B12 全部按共属查询判 different_entity——即**分歧全部是"独立参考认为同名对是同一实体、生产保持分离"**，不构成"生产误合并"的证据。
3. **分歧高度集中于 judge 看不到类型信息的同名异型类**（payload 按协议 §5.4 只含名称、别名、上下文与时空信息，不含实体类型）：org_vs_place_same_name 0/40 正确（参考 40/40 全判 same）、same_name_mixed_type 0/40（参考 40/40 same）、event_vs_work_same_name 1/30；而类型相容的 similar_name_person 上 B12 一致率 **34/34 = 1.000**。这表明低一致率主要由盲评 payload 未向 judge 暴露实体类型所致——judge（以及看到同样信息的 B3）无法识别"同名异型"陷阱，参考在该子集上的可靠性存疑。
4. 因此 B3 在 identity 上对参考的高一致率（strong 0.9524）必须谨慎解读：B3 与 judge 使用同一盲化 payload、共享同一信息盲区（且对主参考还叠加与 Judge B 同模型的膨胀，leave-B 口径降至 0.8662），其"更一致"不等于"更正确"。

## 4. McNemar 检验（strong 口径，n=399）

来源：`14_statistical_tests/MCNEMAR_TESTS.csv`（task_type=identity_pair 行）。

| 对比 | Full 胜:负 | 平 | p |
|---|---|---|---|
| Full vs B1 规则 | 258:0 | 141 | 4.32e-78 |
| Full vs B3 盲 LLM | 10:132 | 257 | **2.57e-28** |
| Full vs B4/B5/B8 | 258:0 | 141 | 4.32e-78 |

B1/B4/B5/B8 在 identity 任务上均 NOT_AVAILABLE（coverage=0），对比只有"有预测 vs 无预测"含义；有效对比只有 B3，盲 LLM 对参考的一致率显著更高——但按 §3 第 4 条，这主要是"共享同一 payload 信息集（含类型盲区）+ 主参考含同模型票"的结果，论文引用时必须附带该限定。leave_b_out 口径同向（33:136，p=4.71e-16，`leave_b_out/MCNEMAR_TESTS.csv`）。

## 5. 结构回放事实（B 级，继续成立）

来源：`STRUCTURAL_REPLAY_AUDIT.json`。

- `identity_projection_replay` 链路：154,150 源实体 → 152,979 规范实体，合并减量 1,171（与 v2 报告一致，`PAPER_CLAIM_EVIDENCE_MATRIX.csv` VERIFIED 行）；
- `w/o Identity Projection` changed_vs_full = 24,005（确定性结构后果）。

这些是确定性回放事实；本报告的 IMCR 结果为其补充语义维度：**1,171 次合并中，已合并对（正例）与独立参考零分歧，但同名/近名对照（硬负例）的一致率 0.228 表明归并的判别边界偏松**。

## 6. 论文处置建议（4.6 节）

1. 可写："在 600 对（含 300 硬负例）的独立盲评中，生产身份投影对全部已合并候选对与独立参考一致（217/217，strong 口径），未观察到已提交的误合并"；
2. 必须同时写："但对同名/近名硬负例对照，生产判定与独立参考的一致率仅 0.228（41/180），显示归并边界偏松、存在身份误合并风险；盲 LLM 对照为 0.900，McNemar p=2.57e-28"；
3. 不得写"消除了身份误合并"（GOAL §二十七禁用句式）。
