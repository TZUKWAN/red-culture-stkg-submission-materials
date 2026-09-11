# FINAL CROSS-SOURCE REPORT：实体语义预测的三切分跨来源稳健性（指令 §18）

- 生成时间：2026-09-11（全自动、确定性、无人工；管线 `code/experiment_pipelines/run_cross_source_robustness.py`，测试 `code/tests/test_cross_source_robustness.py`，全部输出 `experiments/09_cross_source_robustness/`）
- **口径：weak-label（如实声明）**。训练与 held-out 评价标签均为生产分类器分数表 `entity_predictions.predicted_type`（`class_gate_pass=1`，1,210 行），与生产 M3 训练语料逐行一致；held-out 弱标签仅用于与生产口径对齐的**切分间相对比较**。**IMCR 独立参考（strong labels）不进入本实验的任何训练或评价调用**（那是独立评价线，见 04 号报告）。
- 生产底座直接复用：`experiments/02_selective_semantic/predictor_upgrade/M3_improved_predictor.joblib`（route `B_embed_lr`，nomic-embed 768d + LogisticRegression），加载校验通过；每个切分用其 train 子集重训生产同款 LR 头（超参逐项取自生产 `clf.get_params()`：C=2、class_weight=balanced、max_iter=5000、lbfgs；唯一偏离 `random_state=20260910`，本实验 seed）。

## 0. 结论摘要

- **随机切分确实高估稳健性，但高估的口径不在 accuracy，而在 balanced accuracy 与选择性风险**：
  - 相对 **book-grouped**（同书完整性）：macro-F1 高估 **3.0 点**（0.4313 → 0.4012），balanced accuracy 高估 **5.7 点**（0.4752 → 0.4183）；
  - 相对 **province holdout**（整省留出，湖北省）：accuracy / macro-F1 基本持平（ΔmF1 = **+0.0003**），但 **selective risk 恶化 8.2 点**（0.1290 → 0.2105）、**AURC 恶化 4.4 点**（0.2526 → 0.2962）——即部署时的置信门控（conf≥0.5）在跨省来源上错误率接近翻倍；
  - 退化梯度（macro-F1）：random 0.4313 → book_grouped 0.4012 → province_holdout 0.4316：**同书泄漏消除带来主要退化，整省位移的退化体现在风险-coverage 曲线而非点预测精度**。
- **掉得最狠的类（top3，ΔF1 = province/random 与 book/random 之差）**：**Concept**（0.1818 → 0.00，稀有类在非随机切分下消失，−0.1818）、**Event**（0.4086 → 0.3529，−0.0557）、**Person**（0.4533 → 0.4000，−0.0533）。Document 反而在 book-grouped 上 +0.22（held-out 支持数 13→17 的小类构成效应）。
- 结构性发现：本语料 572 个有书实体中 **569 个（99.5%）同属一个并查集互引分量**（《中共党史人物传》多卷本 + 县市党史资料密集互引），实体级"同书不跨切分"的 80/20 **结构性不可达**；最大分量按构造归 train（与 `data/frozen_splits` R1 同惯例），book-grouped held-out 因此几乎全由无书实体构成（242 中仅 2 个有书）。其退化 = 同书泄漏消除 + 无书实体人群位移的叠加，两者在本设计下不可分，如实披露。

## 1. 语料与生产底座

- 训练语料：`data/source_data/stkg_v2_entity_classifier.sqlite` 表 `entity_predictions`，`class_gate_pass=1` 共 **1,210 行**（唯一名 946；sha256 `0343ba31…`）。weak 标签分布：Organization 550、Place 222、Event 156、Person 145、Institution 77、Document 52、Concept 6、ValueFacet 2。
- 生产工件：`M3_improved_predictor.joblib`（sha256 `2beea958…`，route B_embed_lr，类空间 8 类 = 语料弱标签空间，n_train=1210 校验一致）。
- 溯源链（只读，与 `build_frozen_splits.py` 同连接方式）：`entity_predictions.entity_id → research_entity_members.source_entity_id → canonical_entity_id → research_assertions（成员断言）→ research_assertion_provenance.evidence_ids_json → up.evidence_registry.source_title`（书）；省 = 成员断言 → `research_assertion_regions` → `research_study_regions.province_name`。覆盖：有书实体 572 / 无书 638（其中无成员断言 11、有断言无证据 534+11 的一部分），distinct 书 986；有省实体 398（120 个跨省）。
- **嵌入缓存谱系（重要发现）**：2026-09-11 实测 LM Studio 在线重嵌入与生产 M3 缓存向量同名文本 cosine 仅 **0.572**（后端漂移），且漂移向量上 LR 连训练集都拟合不动（train acc ≈7%）。故本实验共享缓存（`09_cross_source_robustness/emb_cache/`）**从生产 M3 缓存原值复制种子（946/946 向量，m3 cache sha256 `de8f4e27…`），在线补嵌 0 条**；三切分严格共用同一份缓存，切分间可比。该漂移本身提示：生产工件不可用当前在线后端重训，只能以冻结缓存复现。

## 2. 三种切分（seed=20260910，全部确定性 SHA-256 哈希，无 RNG 状态）

| 切分 | 规则 | n_train | n_heldout |
|---|---|---:|---:|
| `random` | 实体按 sha256(seed:random:eid) 升序取前 round(0.8N)（忽略书来源，基线口径） | 968 | 242 |
| `book_grouped` | 实体—书并查集分量；**最大分量（569 实体互引核心）按构造归 train**；其余分量按 sha256(seed:bg:cid) 序补足 train 预算；无书实体单列 `nobook:{eid}` 组同序分配（同书绝不跨切分，held-out 诊断同书共享=0 验证） | 968 | 242 |
| `province_holdout` | 留出一个完整省份的全部实体：选实体关联数**中位数**的省（51=湖北省，与江苏省并列取 province_order 小者）；跨省实体整体归 held-out 保证省份完整；无省实体留 train | 1159 | 51 |

省份实体关联数：江西 82、贵州 81、云南 77、四川 75、安徽 75、湖南 64、**湖北 51**、江苏 51、重庆 47、上海 28、浙江 10、青海 2、西藏 1（13 省中位数 = 51）。

切分间泄漏诊断（held-out 侧）：

| 切分 | 同名实体也在 train | 与 train 共享≥1 书 | held-out 有书实体 |
|---|---:|---:|---:|
| random | 85/242（35.1%） | 101/242 | 103 |
| book_grouped | 84/242 | **0**（构造保证） | 2 |
| province_holdout | 10/51（19.6%） | 36/51 | 38 |

解读：random 的 held-out 有 98% 的有书实体与 train 共书、35% 完全同名——近重复泄漏通道全开；book_grouped 关闭了共书通道，但**同名通道依然存在**（84 个：重名实体大量跨书出现），故其退化主要来自无书实体人群位移；province 的跨书共享（36）反映书本身跨省分布，属真实跨来源条件。

## 3. 三切分 held-out 全部指标（weak-label 口径）

| 指标 | random | book_grouped | province_holdout (湖北) |
|---|---:|---:|---:|
| n_train / n_heldout | 968 / 242 | 968 / 242 | 1159 / 51 |
| accuracy | **0.5413** | 0.5331 | 0.5490 |
| macro-F1 | **0.4313** | 0.4012 | 0.4316 |
| balanced accuracy | **0.4752** | 0.4183 | 0.4149 |
| coverage（conf≥0.5） | 0.2562 | 0.2975 | 0.3725 |
| selective risk（coverage 内错误率） | **0.1290** | 0.1389 | 0.2105 |
| AURC（梯形积分） | **0.2526** | 0.2421 | 0.2962 |

- AURC 口径：`selective_stats.rows_to_points` 阈值扫描（score=conf 降序，含 coverage=0 原点）+ 手写梯形积分；曲线含原点故全错曲线积分 = 1−1/(2n)。
- coverage 普遍偏低（0.26–0.37）且 selective risk 远低于 overall error：置信门控有效但保守，与生产 M3 的欠校准发现一致。

### 3.1 退化梯度（Δ 相对 random）

| 口径 | book_grouped − random | province_holdout − random |
|---|---:|---:|
| macro-F1 | **−0.0301** | +0.0003 |
| accuracy | −0.0082 | +0.0077 |
| balanced accuracy | **−0.0569** | −0.0603 |
| selective risk | +0.0099 | **+0.0815** |
| AURC | −0.0105 | **+0.0436** |

**结论（随机切分是否高估）**：是。随机切分相对 book-grouped 高估 macro-F1 3.0 点、balanced accuracy 5.7 点；相对整省留出，点预测精度（acc/mF1）因 held-out 构成变化（湖北 51 条、coverage 更高）基本持平，但 **selective risk 高估 8.2 点、AURC 高估 4.4 点**。稳妥表述：随机切分给出的"泛化画像"系统性偏乐观，且其偏乐观集中在**类别均衡纠偏后的召回（balanced accuracy）与选择性风险口径**，而不体现在粗粒度 accuracy 上。

## 4. 逐类 F1 shift（held-out；F1 按该切分 held-out 出现的类计算，zero_division=0）

| class | 支撑 (r/b/p) | F1 random | F1 book | F1 province | Δ book−rand | Δ prov−rand |
|---|---|---:|---:|---:|---:|---:|
| **Concept** | 2 / 1 / 0 | 0.1818 | 0.0000 | 0.0000 | **−0.1818** | **−0.1818** |
| **Event** | 34 / 39 / 5 | 0.4086 | 0.3364 | 0.3529 | −0.0722 | **−0.0557** |
| **Person** | 35 / 24 / 8 | 0.4533 | 0.3750 | 0.4000 | −0.0783 | **−0.0533** |
| Institution | 13 / 7 / 5 | 0.8462 | 0.7692 | 0.8889 | −0.0770 | +0.0427 |
| Place | 44 / 22 / 13 | 0.6098 | 0.5098 | 0.6957 | −0.1000 | +0.0859 |
| Organization | 101 / 131 / 17 | 0.6429 | 0.6952 | 0.6154 | +0.0523 | −0.0275 |
| Document | 13 / 17 / 3 | 0.3077 | 0.5238 | 0.5000 | +0.2161 | +0.1923 |
| ValueFacet | 0 / 1 / 0 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

**掉得最狠 top3（按 |Δ province−random| 排序，book 口径同序）**：
1. **Concept**：稀有类（全语料仅 6 条），随机切分靠同名近重复撞对一部分（F1 0.18），切断来源后 F1 归零——稀有类在跨来源条件下的崩溃代表；
2. **Event**（−0.056 / −0.072）：中等支撑类的稳定退化，事件名高度模板化、同书复用强；
3. **Person**（−0.053 / −0.078）：人名跨书重名率高，随机切分按名字记忆即可得分，跨来源必须靠语境。

注意 Document/Place 在 province 口径反而上升：51 条湖北 held-out 的类构成与 random 不同（Place 13 条 vs 按 80/20 应约 8 条），小分母上方差大，不构成稳健的"提升"结论。

## 5. 局限与披露

1. **weak-label 口径**：所有指标以生产分类器弱标签为准绳，衡量的是"与生产口径的一致性"，非人工真值精度；三切分间为同口径相对比较，梯度结论不受弱标签噪声系统性偏置的明显影响（噪声对三切分同向），但绝对数值不可与 IMCR strong 口径互换。
2. **book-grouped 的结构退化**：互引核心 569/572 使分量级 80/20 不可达；最大分量按构造归 train 后，held-out 几乎全为无书实体，其 −3.0 点 mF1 是"同书泄漏消除 + 无书人群位移"的合成效应，本设计无法分离（已在 §2 披露）。
3. **province holdout 样本小**：51 条（中位数省），指标抽样噪声显著（尤其逐类 F1）；湖北省与江苏省并列 51，按 province_order 取湖北（规则固化，换江苏不改变结论方向）。
4. **嵌入后端漂移**（§1）：本实验全部结论建立在生产冻结缓存向量上；若用当前在线后端重嵌，生产底座不可复现。建议在 release manifest 中固化嵌入缓存为工件。
5. 单 seed（20260910）、单次切分：三切分对比为描述性证据，无重复抽样置信区间；delta 的方向在 hash 换 seed 下未做敏感性分析（本指令限定 seed 固定）。

## 6. 可复现性与产物

- 运行：`python code/experiment_pipelines/run_cross_source_robustness.py`（≈12s；缓存命中时三切分训练各 <0.1s）；测试：`python -m pytest code/tests/test_cross_source_robustness.py`（9 通过）。
- 确定性核验：两次运行除计时字段外 `CROSS_SOURCE_SUMMARY.json` 完全一致；切分为纯 SHA-256 哈希分配，无 RNG 状态。
- 环境：Python 3.13.2 / scikit-learn 1.8.0 / numpy 2.3.5；输入 sha256：语料 `0343ba31…`、M3 工件 `2beea958…`、M3 缓存 `de8f4e27…`、final DB `a199d736…`、integration DB `f4eb4f06…`（全量记录于 `CROSS_SOURCE_SUMMARY.json`）。
- 产物：`experiments/09_cross_source_robustness/` 下 `CROSS_SOURCE_SUMMARY.json`（总 manifest）、`CROSS_SOURCE_METRICS.csv`、`CROSS_SOURCE_PER_CLASS_F1.csv`、`CROSS_SOURCE_PREDICTIONS.csv`（逐实体预测，含 covered/correct）、`CROSS_SOURCE_SPLITS.json`（逐实体切分归属 + 规则）、`emb_cache/`（共享缓存 + 谱系 meta）。
- 泄漏声明：IMCR 参考零接触；训练仅用各切分 train 子集的弱标签与嵌入，held-out 只进预测路径。
