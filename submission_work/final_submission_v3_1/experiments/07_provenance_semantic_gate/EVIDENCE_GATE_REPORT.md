# Evidence Semantic Gate — 分层语义验证报告（指令 §13）

- 生成时间：2026-09-10T09:58:30+08:00
- 方法版本：`evidence-semantic-gate-v1`（全自动、fixed-seed、无人工；判定全部来自本地模型输出）
- 模型：`openai/gpt-oss-20b`（LM Studio 本地，temperature=0，`lmstudio_provider.chat_json`，4 并发）
- 输入：`STRICT_ALIGNMENT.csv`（sha256 前 8 位 `e7426bd3`）、
  `EVIDENCE_RECOVERY.csv`（sha256 前 8 位 `f4c15555`）
- 抽样 seed：**20260909**（每层对排序后 fact_id 做 `random.Random(seed).sample`，清单见 `SAMPLE_IDS.json`）
- 判定样本：5 层共 5,000 条；执行 0 条，
  耗时 0.0 分钟（均延迟 None s/条，
  checkpoint 每 200 条落盘、可续跑）
- 空证据强制判 INSUFFICIENT：0 条（不消耗模型调用）

## 1. 方法

五档语义支持判定：给模型 normalized assertion
（`subject —predicate— object` + 时间/空间表述）与证据原文（≤800 字，最多
3 条拼接），要求**只依据证据**输出
`decision/confidence/evidence_quote/explanation` 的 JSON，禁止外部知识。
五档定义：FULLY_SUPPORTED（证据明确完整支持全部要素）/ PARTIALLY_SUPPORTED
（部分支持，如时间/地点/范围不完全吻合）/ UNSUPPORTED（证据相关但不含所述关系）/
CONTRADICTED（矛盾）/ INSUFFICIENT（证据缺失或不足）。

分层设计（词法结果 ≠ 语义结果，各层语义支持率未知，须分别估计）：
mismatch_with_evidence（有证据但词法不含实体名，高风险）、recovery_B（同行双名
强恢复）、recovery_C（弱定位恢复）、recovery_A（确定证据 ID，高置信校准层）、
aligned（词法对齐但从未做语义验证的 44k）。

## 2. 各层五档分布与支持率（Wilson 95% CI）

| 层 | 层规模 N | 样本 n | 有效判定 | FULLY | PARTIAL | UNSUPP | CONTRA | INSUFF | 支持率 (FULLY+PARTIAL) | 95% CI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mismatch_with_evidence | 6,136 | 1,500 | 1,500 | 14 | 21 | 1153 | 11 | 301 | 2.3% | [1.7%, 3.2%] |
| recovery_B | 16,705 | 1,000 | 974 | 418 | 268 | 210 | 45 | 33 | 70.4% | [67.5%, 73.2%] |
| recovery_C | 40,345 | 800 | 800 | 50 | 68 | 592 | 9 | 81 | 14.8% | [12.5%, 17.4%] |
| recovery_A | 2,841 | 200 | 200 | 45 | 26 | 100 | 0 | 29 | 35.5% | [29.2%, 42.4%] |
| aligned | 44,025 | 1,500 | 1,497 | 631 | 209 | 545 | 35 | 77 | 56.1% | [53.6%, 58.6%] |

样本合计五档分布（n=4,971）：FULLY 1,158
（23.3%）｜PARTIAL 592
（11.9%）｜UNSUPPORTED 2,600
（52.3%）｜CONTRADICTED 100
（2.0%）｜INSUFFICIENT 521
（10.5%）。

### 各层判定明细样本

**mismatch_with_evidence**（n=1,500）：

| FULLY_SUPPORTED | 14 | 0.9% |
| PARTIALLY_SUPPORTED | 21 | 1.4% |
| UNSUPPORTED | 1153 | 76.9% |
| CONTRADICTED | 11 | 0.7% |
| INSUFFICIENT | 301 | 20.1% |

**recovery_B**（n=1,000）：

| FULLY_SUPPORTED | 418 | 42.9% |
| PARTIALLY_SUPPORTED | 268 | 27.5% |
| UNSUPPORTED | 210 | 21.6% |
| CONTRADICTED | 45 | 4.6% |
| INSUFFICIENT | 33 | 3.4% |

**recovery_C**（n=800）：

| FULLY_SUPPORTED | 50 | 6.2% |
| PARTIALLY_SUPPORTED | 68 | 8.5% |
| UNSUPPORTED | 592 | 74.0% |
| CONTRADICTED | 9 | 1.1% |
| INSUFFICIENT | 81 | 10.1% |

**recovery_A**（n=200）：

| FULLY_SUPPORTED | 45 | 22.5% |
| PARTIALLY_SUPPORTED | 26 | 13.0% |
| UNSUPPORTED | 100 | 50.0% |
| CONTRADICTED | 0 | 0.0% |
| INSUFFICIENT | 29 | 14.5% |

**aligned**（n=1,500）：

| FULLY_SUPPORTED | 631 | 42.1% |
| PARTIALLY_SUPPORTED | 209 | 14.0% |
| UNSUPPORTED | 545 | 36.4% |
| CONTRADICTED | 35 | 2.3% |
| INSUFFICIENT | 77 | 5.1% |

## 3. Support-Coverage 的含义

词法 strict 层的"覆盖率"只说明**存在证据指针/可恢复证据文本**（coverage），
不说明证据在语义上真的支持断言。本次 semantic gate 度量的是
**支持质量（support）**：词法覆盖的断言中有多少比例能被证据原文在语义上
完整/部分支持。两者相乘才是有效覆盖：例如某层词法覆盖 100%、语义支持率 60%，
则该层的有效语义覆盖只有约 60%。低支持层即"词法假阳/证据错配"的主要来源
（mismatch_with_evidence 层即典型：有证据指针但原文不含实体名）。

## 4. 按 predicate 的系统性差异

支持率前/后差异见 `EVIDENCE_GATE_PREDICATE.csv`（层 × predicate 与跨层 PARTIAL 表）。
主要发现（n≥30 的 predicate）：

| predicate | 合并样本 n | 支持率 |
| --- | --- | --- |
| collaborated_with | 36 | 63.9% |
| held_position_in | 198 | 60.6% |
| captured | 34 | 55.9% |
| worked_at | 58 | 50.0% |
| member_of | 264 | 47.0% |
| dispatched | 45 | 46.7% |
| stationed_at | 71 | 43.7% |
| active_at | 495 | 41.6% |
| created | 41 | 41.5% |
| organized | 284 | 41.2% |
| carried_out | 47 | 36.2% |
| led | 999 | 35.6% |
| has_value_facet | 93 | 35.5% |
| supported | 79 | 31.6% |
| guided | 73 | 31.5% |
| participated_in | 913 | 28.9% |
| opposed | 42 | 28.6% |
| occurred_at | 325 | 28.0% |
| contacted | 47 | 27.7% |
| influenced | 185 | 25.4% |
| governed | 33 | 24.2% |
| fought_at | 54 | 20.4% |
| commanded | 89 | 18.0% |
| mentioned_in | 103 | 2.9% |

（差异解释：`active_at/occurred_at` 类空间/时间谓词依赖证据中的同现表述，而 `led/participated_in` 等关系谓词对证据表述方式更敏感——详见 CSV。）
## 5. DEV 重分层规则与 PARTIAL predicate 表

规则：FULLY_SUPPORTED→**strict**；PARTIALLY_SUPPORTED→按 predicate 表决定
**strict/contextual**；UNSUPPORTED / CONTRADICTED→**unresolved**；
INSUFFICIENT→**contextual**；解析失败/调用失败→不计入比率（待复核）。

PARTIAL predicate 表数据依据（跨 5 层合并的 PARTIAL 判定，n=592）：
入 strict 条件 = `n_partial≥25` 且 `mean_confidence≥0.7`
且 `share(conf≥0.75)≥0.5`；不满足或样本不足 → 默认 contextual。

| predicate | n_partial | mean_conf | share(conf≥0.75) | 映射 |
| --- | --- | --- | --- | --- |
| led | 148 | 0.692 | 100.0% | contextual |
| participated_in | 111 | 0.703 | 100.0% | strict |
| member_of | 57 | 0.716 | 100.0% | strict |
| organized | 49 | 0.709 | 100.0% | strict |
| held_position_in | 37 | 0.751 | 100.0% | strict |
| occurred_at | 32 | 0.663 | 100.0% | contextual |
| active_at | 30 | 0.662 | 100.0% | contextual |
| influenced | 17 | 0.679 | 100.0% | contextual |
| has_value_facet | 13 | 0.665 | 100.0% | contextual |
| stationed_at | 11 | 0.668 | 100.0% | contextual |
| commanded | 9 | 0.694 | 100.0% | contextual |
| carried_out | 7 | 0.657 | 100.0% | contextual |
| collaborated_with | 6 | 0.683 | 100.0% | contextual |
| captured | 5 | 0.706 | 100.0% | contextual |
| guided | 5 | 0.690 | 100.0% | contextual |
| worked_at | 5 | 0.620 | 100.0% | contextual |
| dispatched | 4 | 0.713 | 100.0% | contextual |
| supported | 4 | 0.688 | 100.0% | contextual |
| created | 4 | 0.713 | 100.0% | contextual |
| governed | 3 | 0.633 | 100.0% | contextual |
| colleague_of | 3 | 0.700 | 100.0% | contextual |
| fought_at | 3 | 0.683 | 100.0% | contextual |
| contacted | 2 | 0.675 | 100.0% | contextual |
| arrested_at | 2 | 0.700 | 100.0% | contextual |
| traveled_to | 2 | 0.650 | 100.0% | contextual |
| opposed | 2 | 0.750 | 100.0% | contextual |
| authored | 2 | 0.800 | 100.0% | contextual |
| comrade_of | 2 | 0.650 | 100.0% | contextual |
| part_of | 2 | 0.700 | 100.0% | contextual |
| responsible_for | 2 | 0.750 | 100.0% | contextual |
| met_with | 2 | 0.650 | 100.0% | contextual |
| protected | 1 | 0.650 | 100.0% | contextual |
| died_at | 1 | 0.600 | 100.0% | contextual |
| family_of | 1 | 0.900 | 100.0% | contextual |
| imprisoned_at | 1 | 0.700 | 100.0% | contextual |
| used_artifact | 1 | 0.700 | 100.0% | contextual |
| implemented | 1 | 0.650 | 100.0% | contextual |
| introduced | 1 | 0.600 | 100.0% | contextual |
| liberated | 1 | 0.800 | 100.0% | contextual |
| active_during | 1 | 0.650 | 100.0% | contextual |
| appointed | 1 | 0.600 | 100.0% | contextual |
| visited | 1 | 0.650 | 100.0% | contextual |

入 strict 的 predicate（n≥25 且置信度达标）：held_position_in、member_of、organized、participated_in
## 6. 全库外推（分层抽样统计估计，非逐条验证）

**明确标注：以下为分层抽样的统计估计**（每层 simple random sample + 有限总体校正；
点估计 ±1.96·SE），逐条全量语义验证留待后续。外推宇宙 = 5 层合计
110,052 条；recovery_D 2,106 条真无证据不参与外推
（无可验证证据，按恢复审计降级）。

| 层 | 层规模 | 样本有效 n | 样本 strict 率 | 估计 strict 条数 | SE |
| --- | --- | --- | --- | --- | --- |
| mismatch_with_evidence | 6,136 | 1,500 | 1.5% | 94 | ±17 |
| recovery_B | 16,705 | 974 | 55.8% | 9,313 | ±258 |
| recovery_C | 40,345 | 800 | 10.4% | 4,186 | ±431 |
| recovery_A | 2,841 | 200 | 26.5% | 753 | ±86 |
| aligned | 44,025 | 1,497 | 47.4% | 20,880 | ±558 |

**全库 new strict size 估计：35,226 条（95% CI [33,744, 36,708]）**
（词法 strict 层 112,158 条 → 语义门后约 31.4%）。

五档全库估计：FULLY_SUPPORTED 28,944 [27,566, 30,323]；PARTIALLY_SUPPORTED 14,627 [13,445, 15,809]；UNSUPPORTED 55,622 [53,945, 57,298]；CONTRADICTED 2,300 [1,809, 2,791]；INSUFFICIENT 8,559 [7,561, 9,556]。

DEV 三层全库估计：strict 35,226 ／
contextual 16,904 ／
unresolved 57,922
（另有 recovery_D 2,106 条真无证据降级）。

## 7. 局限性

1. **词法恢复的 B/C 层证据相关性弱于 direct**：B（同行双名同现）只保证两个实体名
   同时出现在同一证据行，不保证所述关系就是断言关系；C（弱定位/单名/异行）相关性
   更弱。这两层是恢复候选而非确证证据，其语义支持率应解读为"恢复链路上限"。
2. **抽样估计而非普查**：各层支持率由 n=200–1,500 的固定 seed 样本估计，CI 为
   抽样不确定性；层内若存在与 predicate/实体类型相关的异质性，层内分层可进一步
   收窄（本次已给出层 × predicate 明细供后续加权）。
3. **单一本地判定模型**：全部判定来自 gpt-oss-20b（temperature=0，JSON 稳定），
   未经第二模型或人工仲裁；PARTIAL 与 UNSUPPORTED 的边界判例存在模型主观性。
4. **证据截断**：每条断言最多拼接 3 条证据、总长 ≤800 字，超长
   证据尾部被截断，可能低估 FULLY_SUPPORTED；A 层少量 metadata 引文只有 120 字预览。
5. **INSUFFICIENT 的双重来源**：证据文本为空（强制判）与模型判证据不足混在同一档，
   已在逐条记录 `forced` 字段区分。

## 8. 可复现性

- seed=20260909 写死；抽样、证据拼接顺序（evidence_id 字典序）、判定顺序全部确定性。
- checkpoint：`EVIDENCE_GATE_CHECKPOINT.jsonl`（追加写、每 200 条 fsync），
  断点续跑只跳过已完成 fact_id。
- 判定输入/输出逐条落盘 `EVIDENCE_GATE_VERDICTS.jsonl`（含 assertion、evidence_text、
  decision、confidence、evidence_quote、explanation、latency）。
- 输入 CSV 的 sha256 记录于 `EVIDENCE_GATE_SUMMARY.json`；数据库只读。
- 本次执行已从 checkpoint 续跑。
