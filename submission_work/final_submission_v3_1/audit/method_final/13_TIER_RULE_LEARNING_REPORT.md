> [HISTORICAL 2026-09-16] 历史实验存档：本报告的数字属于**当时局部实验**，不是全库结论；最终权威数字见 AUTHORITATIVE_RESULTS.md。

# 13 — TIER 规则学习：从 5,000 条验证数据学习确定性判定规则（指令 §5.2）

- 生成时间：2026-09-11T04:21:52+08:00｜方法版本：`tier-rule-learning-v1`（全自动、确定性、无 LLM 调用、无人工）
- 目标：把证据语义门（5,000 条分层 LLM 五档验证）的判定知识压缩成**确定性特征规则**，让大部分断言免 LLM 直接判定（指令 §5.2“确定性高置信过滤”），只把规则无法高置信判定的断言留给 LLM 队列。
- 门槛（任务 §2，与 FINAL_TIERING 安全规则同标准）：precision ≥ 95% 且 Wilson 95% 下界 ≥ 90%，训练覆盖 ≥ 30；**并要求 1/4 验证集复现**（val n ≥ 15、val precision ≥ 95%、val Wilson 下界 ≥ 90%）方可标 HIGH-CONFIDENCE 免 LLM。
- 输入（全部只读）：`EVIDENCE_GATE_VERDICTS.jsonl`（4,999 行验证）、`STRICT_ALIGNMENT.csv`（112,158 行）、`EVIDENCE_RECOVERY.csv`、`FINAL_TIERING_FEATURES.csv`（全库确定性特征，同一 EvidenceResolver 证据组装）、`EVIDENCE_GATE_SUMMARY.json`（PARTIAL→strict 谓词映射表）。sha256 见 SUMMARY。

## 1. 特征构建与一致性核对

- DEV 特征从 verdict 的证据文本**重新计算**（双名命中 subj_hit/obj_hit、双名间距 gap/≤80 close、谓词中文线索 pred_cue / cue_between、证据长度、n_evidence），再 join 对齐/恢复特征（bucket/stratum、predicate、subject/object 类型、time/place、match_mode、recovery_class）。
- 一致性核对：重算特征 vs `FINAL_TIERING_FEATURES.csv`（应用侧特征源）在 4,971 条 DEV 行上逐特征比对，全部一致 = **True**（subj_hit 4,971/4,971；obj_hit 4,971/4,971；pred_cue 4,971/4,971；pred_cue_between 4,971/4,971；evidence_len 4,971/4,971；n_evidence 4,971/4,971）→ 训练与应用特征零偏移。
- stratum 字段与派生 stratum 不一致：0 条。
- 有效验证 4,971 条（跳过非五档判定：CALL_FAILED 28）。五档分布：{"UNSUPPORTED": 2600, "INSUFFICIENT": 521, "FULLY_SUPPORTED": 1158, "PARTIALLY_SUPPORTED": 592, "CONTRADICTED": 100}

## 2. 规则学习（3/4 训练，1/4 验证，seed=20260910）

- 切分：排序 fact_id + `random.Random(20260910)` 洗牌，train 3,728 / val 1,243。**验证集绝不参与规则选择**：原子枚举、达标筛选、去重、规则数量全部由训练集决定；验证集只做最终 HIGH-CONFIDENCE 复核（逐条通过/不通过，不据此挑规则、不据此调参）。
- 穷举规则空间：≤4 个原子条件的合取，候选原子 72 个（训练支持 <30 的原子提前剪枝——合取只会缩小覆盖），共评估 39,605 个模式（各深度 frontier {"1": 72, "2": 1112, "3": 7912, "4": 30509}，安全阀触发 = False）。
- 目标档：FULLY_SUPPORTED（→STRICT）/ UNSUPPORTED / INSUFFICIENT（后两者 = 可免 LLM 直接出否定/降级结论）。PARTIALLY_SUPPORTED 与 CONTRADICTED 本质依赖语义细节，不设规则，一律 needs_llm。
- 训练集达标候选（precision≥95% 且 Wilson 下界≥90%，n≥30）：FULLY_SUPPORTED=0；UNSUPPORTED=286；INSUFFICIENT=0。


### 规则表（训练达标候选——注意：全部未过验证复核，**不可应用**，仅透明记录）
| 规则 | 目标 | 条件 | 训练 n | 训练 precision | 训练 Wilson95 | 训练 recall | 验证 n | 验证 precision | 验证 Wilson95 | HIGH-CONF |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R-UNSU-01 | UNSUPPORTED | subj_type=Artifact | 41 | 1.0000 | [0.9143, 1.0000] | 0.0210 | 13 | 1.0 | [0.7719, 1.0000] | NO |
| R-UNSU-02 | UNSUPPORTED | elen:le50 AND subj_type=Artifact | 39 | 1.0000 | [0.9103, 1.0000] | 0.0199 | 13 | 1.0 | [0.7719, 1.0000] | NO |
| R-UNSU-03 | UNSUPPORTED | n:nev1 AND subj_type=Artifact | 39 | 1.0000 | [0.9103, 1.0000] | 0.0199 | 12 | 1.0 | [0.7575, 1.0000] | NO |
| R-UNSU-04 | UNSUPPORTED | stratum=mismatch_with_evidence AND subj_type=Artifact | 39 | 1.0000 | [0.9103, 1.0000] | 0.0199 | 11 | 1.0 | [0.7412, 1.0000] | NO |
| R-UNSU-05 | UNSUPPORTED | elen:le50 AND n:nev1 AND subj_type=Artifact | 37 | 1.0000 | [0.9059, 1.0000] | 0.0189 | 12 | 1.0 | [0.7575, 1.0000] | NO |
| R-UNSU-06 | UNSUPPORTED | elen:le50 AND stratum=mismatch_with_evidence AND subj_type=Artifact | 37 | 1.0000 | [0.9059, 1.0000] | 0.0189 | 11 | 1.0 | [0.7412, 1.0000] | NO |
| R-UNSU-07 | UNSUPPORTED | n:nev1 AND stratum=mismatch_with_evidence AND subj_type=Artifact | 37 | 1.0000 | [0.9059, 1.0000] | 0.0189 | 10 | 1.0 | [0.7225, 1.0000] | NO |
| R-UNSU-08 | UNSUPPORTED | elen:le50 AND n:nev1 AND stratum=mismatch_with_evidence AND subj_type=Artifact | 35 | 1.0000 | [0.9011, 1.0000] | 0.0179 | 10 | 1.0 | [0.7225, 1.0000] | NO |

- FULLY_SUPPORTED 最接近门槛的训练集规则（**未达标**，仅透明记录）：`gap:le40 AND n:nev3 AND pred=active_at AND pred_cue_between=0` → 训练 n=36、precision=0.9167、Wilson LB=0.7817（vs 门槛：precision -0.0333、LB -0.1183，正值=高于门槛）。
- UNSUPPORTED 最接近门槛的训练集规则（**未达标**，仅透明记录）：`elen:le50 AND obj_type=Document AND stratum=mismatch_with_evidence` → 训练 n=54、precision=0.9630、Wilson LB=0.8746（vs 门槛：precision +0.0130、LB -0.0254，正值=高于门槛）。

**结论（如实报告）：穷举空间内没有任何规则同时通过训练与验证双重门槛——即当前无可用的免 LLM 判定规则（STRICT / UNSUPPORTED / INSUFFICIENT 三者皆无）；待判定队列除 policy 规则 R0 外只能整体进 LLM。**

- **FULLY_SUPPORTED**：训练达标候选 0；全空间最好训练 precision 仅 0.9167（n=36，Wilson LB 0.7817），距 0.95 门槛差距过大 → 拒绝。
- **UNSUPPORTED**：训练达标候选 286 条（覆盖集去重后 8 条，训练 precision 1.0000–1.0000），但验证复核全部未通过：验证 n 仅 10–13（< 最小验证覆盖 15），验证 Wilson LB 0.723–0.772（< 0.90）→ 复现性不足，拒绝。
- **INSUFFICIENT**：训练达标候选 0，且全空间未出现 precision≥0.85 且 k≥20 的候选（最高精度更低）→ 拒绝。

### DEV 上 pipeline 级评估（规则集整体，first-match）

- **train**（n=3,728）：规则判定 0 条（覆盖 0.00%）；FULLY_SUPPORTED: 预测 0 / 正确 0 / precision NA；UNSUPPORTED: 预测 0 / 正确 0 / precision NA；INSUFFICIENT: 预测 0 / 正确 0 / precision NA。
- **val**（n=1,243）：规则判定 0 条（覆盖 0.00%）；FULLY_SUPPORTED: 预测 0 / 正确 0 / precision NA；UNSUPPORTED: 预测 0 / 正确 0 / precision NA；INSUFFICIENT: 预测 0 / 正确 0 / precision NA。

## 3. 全库应用模拟（112,158 行）

- policy 规则 **R0**（非学习规则，与语义门“空证据强制 INSUFFICIENT、不耗模型调用”同款）：`stratum=recovery_D 或 evidence_empty → INSUFFICIENT`，覆盖 2,106 条真无证据断言。

| 层 | 层规模 | 规则可判定 | 免 LLM 覆盖率 | 剩余 LLM 队列 |
| --- | --- | --- | --- | --- |
| aligned | 44,025 | 0 | 0.00% | 44,025 |
| mismatch_with_evidence | 6,136 | 0 | 0.00% | 6,136 |
| recovery_A | 2,841 | 0 | 0.00% | 2,841 |
| recovery_B | 16,705 | 0 | 0.00% | 16,705 |
| recovery_C | 40,345 | 0 | 0.00% | 40,345 |
| recovery_D | 2,106 | 2,106 | 100.00% | 0 |
| **合计** | **112,158** | **2,106** | **1.88%** | **110,052** |

- 规则可判定覆盖率：**1.88%**（2,106 / 112,158）；其中判 STRICT(FULLY) 0 条。
- 剩余 LLM 队列：**110,052 条**；按 0.5 it/s @ 6 workers（≈2 s/条有效吞吐，与 gate 实测单条延迟 10–14 s × 6 并发一致）折算：**61.14 小时（≈2.55 天）**。

## 4. 与分层抽样估计 35,226 的一致性核对

- 基线：语义门外推估计 new strict ≈ **35,226**（95% CI [33,744, 36,708]，FULLY + strict-predicate PARTIAL，宇宙 110,052，排除 recovery_D）。
- 规则直接判 STRICT：**0 条**（只含高置信 FULLY 子集，天然是基线的保守子集）。
- 队列内剩余 strict 估计（按 DEV 分层 strict 率 × 各层剩余队列，外推仅用于一致性核对、不参与规则选择）：**≈35,225 条**。
- 隐含全库 strict（规则 + 队列外推）≈ **35,225**，vs 基线 35,226：差 -1 （-0.00%），落在基线 95% CI [33,744, 36,708] 内。
- 差异解释（如实）：(1) 规则判 STRICT 是基线的**保守子集**——只保留precision≥95% 且验证复现的特征组合，大量真 FULLY（尤其证据中双名分离、无线索词的表述）必须留给 LLM；(2) 队列剩余部分的外推继承 DEV 分层抽样误差（±~2.5%）；(3) 基线含 strict-mapped PARTIAL，规则只判 FULLY，该部分全部计入队列外推。三个来源合成的隐含总数与抽样估计同量级，两套方法交叉印证一致。
- **本场景特有说明**：规则最终未判任何 STRICT（rule_strict=0），上述“隐含全库 strict”完全来自对剩余队列的分层外推——它与基线 35,226 只差 -1 条（0.003%），说明本实验复算的分层 strict 率（FULLY + strict-predicate PARTIAL）与语义门原估计构型一致；但这也意味着规则学习对 STRICT 队列的“免 LLM 化”贡献为 0，35,226 条 strict 的确认仍需 LLM 逐条判定。

## 5. 局限

1. DEV 判定本身来自本地模型（gpt-oss-20b，temperature=0），规则学的是“模型判定”而非金标准真值；若模型系统性偏差存在，规则会继承。
2. 词法/线索特征无法覆盖语义等价表述（如代词、别名、事件名转述），此类断言只能留在 LLM 队列——这是覆盖率而非精度损失。
3. 验证集仅 1/4（≈1,243 条），小覆盖规则在验证端 Wilson 下界容易不达标而被拒——保守方向正确，但会低估可免 LLM 覆盖率。最接近可用边缘的两类规则（若未来扩标注值得重测）：(a) `subj_type=Artifact` 角的 UNSUPPORTED 规则族（训练 precision=1.0，n=35–41，但验证覆盖仅 10–13）；(b) `mentioned_in + 证据≤50字` 的 UNSUPPORTED 族（训练 precision=0.963、n=54，但训练 Wilson LB=0.875 < 0.90）。
4. R0 覆盖的 recovery_D 为恢复审计认定的真无证据（策略判定而非学习判定），其 INSUFFICIENT 语义与语义门“空证据强制”一致。

## 6. 产物

- `experiments/07_provenance_semantic_gate/RULE_LEARNING_RULES.csv` — 规则表（policy + 达标规则 + near-miss 透明记录）
- `experiments/07_provenance_semantic_gate/RULE_LEARNING_APPLICATION.csv` — 112,158 行全量应用（rule_id / rule_verdict / needs_llm）
- `experiments/07_provenance_semantic_gate/RULE_LEARNING_SUMMARY.json` — 全部统计与 sha256 溯源
- `audit/method_final/13_TIER_RULE_LEARNING_REPORT.md` — 本报告
