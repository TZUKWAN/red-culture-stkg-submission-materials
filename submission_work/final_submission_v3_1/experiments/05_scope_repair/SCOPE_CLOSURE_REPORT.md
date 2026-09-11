# Selective Scope Closure：规则学习与新旧对比报告（SCOPE_CLOSURE_REPORT）

- 生成时间：2026-09-09T19:15:42+00:00（全自动，无人工干预；管线 `code/experiment_pipelines/run_selective_scope_closure.py`，测试 `code/tests/test_selective_scope_closure.py`）
- **口径：两票盲评**。Judge A = Qwen3.6-35B-A3B，Judge B = gpt-5.6-luna；本实验不引入任何新裁判票，判定数据复用 `SCOPE_BY_TYPE_ERRORS.csv`（208 条，A/B 展示位已经映射文件解码，完整性由前置脚本核验）。
- 聚合规则与前置一致：两票一致 → 该判定；两票不一致 → DISAGREE；A/B 无 invalid 票（0/0）。

## 1. 60/40 book-split（切分键）

- 方法：component-atomic: components sorted by sha256(seed:closure:cid); largest prefix with cumulative task count <= round(ratio*N) -> learn, rest -> heldout
- seed=20260908（与 `data/frozen_splits/SPLIT_MANIFEST.json` 同种子）；预算 = round(0.60×208) = **125 条**。
- book 键：payload 证据预览 evidence_excerpts[].source_title（非空去重）→ 回退 metadata books 列 → 仍为空则 nobook:{task_id} 单任务分量；来源分布：nobook_single_task_component=12，payload_evidence_source_title=196。
- 任务—书二部图并查集（复用 `build_frozen_splits.py` 分量思路）：105 个分量，分量原子落侧（learn 77 个 / heldout 28 个分量），同书任务绝不跨 split。
- 实际切分：**learn 125 条（60.1%） / held-out 83 条（39.9%）**；分量 id 与逐任务归属见 `CLOSURE_OLD_NEW_SUMMARY.json` 的 `split` 节。

### 1.1 类型 × split 构成

| transformation_type | learn n (A/B/decided*) | heldout n (A/B/decided*) |
|---|---|---|
| `event_location→context_location` | 49（6/30/36） | 41（1/22/23） |
| `event_location→relation_location` | 4（0/1/1） | 1（0/0/0） |
| `mixed` | 11（0/7/7） | 5（0/4/4） |
| `other` | 30（6/4/10） | 7（2/0/2） |
| `unknown→event_occurrence` | 31（17/4/21） | 29（6/0/6） |

*A/B/decided = AFTER_BETTER / BEFORE_BETTER / 两票一致分出胜负条数。

## 2. 学到的规则（仅在 60% learn 内学习）

- 判据（与前置 `SCOPE_BY_TYPE_SUMMARY.json` 阈值一致）：decided = AFTER_BETTER + BEFORE_BETTER（两票一致）；**REWRITE**：双侧精确二项 p<0.05 且 AFTER 占优且 decided≥10；**RETAIN**：p<0.05 且 BEFORE 占优且 decided≥10；其余 **UNRESOLVED**（保守）。
- held-out 不参与规则学习（无回流）；learn 内未见类型 apply 时同样 UNRESOLVED。

| transformation_type | action | learn n | decided | AFTER : BEFORE | AFTER 胜率 | 双侧精确二项 p | 判据 |
|---|---|---:|---:|---:|---:|---:|---|
| `event_location→context_location` | **RETAIN** | 49 | 36 | 6 : 30 | 16.7% | 0.00007 | decided=36>=10 且 p=0.00007<0.05 |
| `event_location→relation_location` | **UNRESOLVED** | 4 | 1 | 0 : 1 | 0.0% | 1.00000 | decided=1<10 |
| `mixed` | **UNRESOLVED** | 11 | 7 | 0 : 7 | 0.0% | 0.01562 | decided=7<10 |
| `other` | **UNRESOLVED** | 30 | 10 | 6 : 4 | 60.0% | 0.75391 | p=0.75391>=0.05（不显著） |
| `unknown→event_occurrence` | **REWRITE** | 31 | 21 | 17 : 4 | 81.0% | 0.00720 | decided=21>=10 且 p=0.00720<0.05 |

## 3. 新旧对比（40% held-out）

- 旧 closure（生产现状）：全部候选 REWRITE 为 after。
- 新 closure：按 §2 规则（REWRITE / RETAIN / UNRESOLVED 弃权）。
- 评价：两票解码判定为独立语义裁判——REWRITE 且裁判=AFTER_BETTER → 正确；RETAIN 且裁判=BEFORE_BETTER → 正确；裁判未定（DISAGREE 等）不可评。

| 口径 | n（held-out decided） | 正确 | semantic agreement |
|---|---:|---:|---:|
| old（全 REWRITE） | 35 | 9 | **25.7%** |
| new（规则，actionable=REWRITE/RETAIN） | 29（弃权 6） | 28 | **96.6%** |
| new（保守：弃权记错，分母=全部 decided） | 35 | 28 | 80.0% |

- 配对（两条 closure 在同一批 29 条 actionable decided 任务上的二值配对）：双方全对 6、双方全错 0、**old 对 new 错 1、old 错 new 对 22**；精确 McNemar p = **0.00001**。
- 归因：old closure 的 26 条错误全部来自把裁判判 BEFORE_BETTER 的候选强行改写为 after；其 9 条正确则集中在裁判本身支持 AFTER 的任务（unknown→event_occurrence 6 条、other 2 条、event_location→context_location 1 条）。new closure 用类型规则把两类拆开：该改的改（unknown→event_occurrence）、该留的留（event_location→context_location）、证据不足的类型弃权（UNRESOLVED）。唯一回退是 1 条 event_location→context_location 任务：裁判判 AFTER_BETTER 而规则 RETAIN（该类 AFTER 胜率在 learn 内仅 16.7%，属规则可接受的代价）。

### 3.1 held-out 分类型对比

| transformation_type | action_new | heldout n | decided | old 正确 | new 正确(actionable) | new 弃权 |
|---|---|---:|---:|---:|---:|---:|
| `event_location→context_location` | RETAIN | 41 | 23 | 1 | 22 | 0 |
| `event_location→relation_location` | UNRESOLVED | 1 | 0 | 0 | 0 | 0 |
| `mixed` | UNRESOLVED | 5 | 4 | 0 | 0 | 4 |
| `other` | UNRESOLVED | 7 | 2 | 2 | 0 | 2 |
| `unknown→event_occurrence` | REWRITE | 29 | 6 | 6 | 6 | 0 |

## 4. 结构安全检查（structural violations 恒 0）

- new closure 的 REWRITE 仅改写 time_role/time_owner/space_role/space_owner 四字段，不改谓词、论元、实体与任何结构约束；RETAIN 保持 before 状态，零改动。
- 程序化核验：416 个 A/B 展示位状态对象中，含 role/owner 四字段以外键的为 **0 个**。
- 因此新 closure 的 REWRITE 动作与生产改写共用同一改写面（仅 role/owner），不可能引入结构约束违例：**structural violations = 0**。PASS：REWRITE 改写面 ⊆ role/owner 四字段，structural violations 恒 0。

## 5. 样本代表性与口径局限（声明）

1. 208 条 final_entity_type_scope_closure 任务为该修复的全量总体，本实验的 60/40 切分并非从更大总体抽样，切分唯一目的：避免规则学习与效果评价同源（同书任务绝不跨侧）。
2. 判定口径为两票盲评（Judge A=Qwen3.6-35B-A3B + Judge B=gpt-5.6-luna），无第三票仲裁；DISAGREE（38.5%）一律不可评，不计入 agreement 分母。
3. UNRESOLVED 类型按弃权处理：不进入 actionable agreement 分母；保守口径（弃权记错）一并列出。
4. learn 内 decided<10 或 p>=0.05 的类型一律 UNRESOLVED（保守），例如 mixed 在本次 learn 内 decided 不足 10，尽管其在全量上方向显著为 BEFORE，规则仍不得据 held-out 回流改判。
5. held-out 上 UNRESOLVED 类型的 'old 错误改写' 仍会发生（old closure 全 REWRITE），new closure 只能证明 REWRITE/RETAIN 两类上的改善，弃权类型的收益留待证据增强。
