# 04 — 语义预测器三路线升级对比（M3：entity_type predictor upgrade）

日期：2026-09-09 ｜ 状态：完成（B 路线胜出并落盘为 `M3_improved_predictor`；DEV 规则下升级幅度未达 2 个百分点显著性阈值，见 §5 判定）

## 1. 任务与三条路线

指令 §五 的预测器升级对比：在独立参考（IMCR strong，**只做评价**）上，比较三条 entity_type 语义预测器路线（均在同一 weak-label 训练集上拟合，模型可输出类空间 = 训练 weak 标签空间）：

| 路线 | 定义 | 关键超参 |
|---|---|---|
| **A** `A_char_tfidf_sgd` | 复现生产基线：char TF-IDF + SGDClassifier | TF-IDF(char 3-5, min_df=2, sublinear_tf, l2)；SGD loss=log_loss, alpha=2e-6, max_iter=40, elasticnet, learning_rate=optimal, class_weight=balanced（对齐生产 260 脚本 / `stkg_v2_entity_classifier.joblib` 实测超参；ngram 按指令用 (3,5)，生产为 (1,4)） |
| **B** `B_embed_lr` | nomic-embed 嵌入 + 线性分类头 | `lmstudio_provider.embed`（本地 127.0.0.1:1234，批量 64，npy 缓存）768 维 → LogisticRegression(C=2, class_weight=balanced, max_iter=5000) |
| **C** `C_fused_char_embed` | 稀疏词法 ⊕ 嵌入融合 | A 的 char TF-IDF 稀疏块 ⊕ L2 归一化嵌入块拼接 → LogisticRegression(C=2, class_weight=balanced) |

统一入口：`code/experiment_pipelines/run_predictor_upgrade.py`（seed=20260908，三次运行结果逐位一致）。

## 2. 训练集构成与泄漏声明

| 项 | 值 |
|---|---|
| 训练集来源 | `data/source_data/stkg_v2_entity_classifier.sqlite` 表 `entity_predictions`（sha256 见 `TRAIN_MANIFEST.json`） |
| 准入条件 | `class_gate_pass=1` 的全部行：**1210 / 6813** |
| weak 标签 | `predicted_type`（生产分类器分数表自带）；分布：Organization 550, Place 222, Event 156, Person 145, Institution 77, Document 52, Concept 6, ValueFacet 2（8 类） |
| 训练文本 | `canonical_name`（表无 aliases 列；confidence/margin 仅记录未用作样本权重） |
| 评价集 | `V3/experiments/08_independent_reference/IMCR_REFERENCE_STRONG.csv` entity_type 行（276 条带参考标签）；实体名取自 `run_selective_semantic.build_signal_frame()`（只读复用，仅取 `name` 字段作为模型输入） |
| 切分 | `V3_1/data/frozen_splits/SPLIT_MANIFEST.json`（entity_type 前缀键）：带参考标签样本 **DEV=182、VAL=48**；TEST（46 条带参考标签）**未运行、未读取、未评价** |
| **泄漏声明** | ① weak 标签来自生产分类器（260 冻结模型）分数表，与 IMCR 独立评审过程零重叠；② IMCR 参考标签仅出现在评价路径（`evaluate_split` 的 y_true），**不进入任何训练/拟合调用**；③ 阈值/超参未在 VAL 上搜索（DEV 决策、VAL 观察、TEST 冻结不碰） |

## 3. 结果（IMCR strong 参考，点预测全量输出，无弃权）

| 路线 | split | n | accuracy | macro-F1 | bal. acc | ECE(10 bins) | Brier | Δmacro-F1 vs A |
|---|---|---|---|---|---|---|---|---|
| A_char_tfidf_sgd | DEV | 182 | 0.148 | 0.104 | 0.147 | 0.398 | 1.157 | — |
| A_char_tfidf_sgd | VAL | 48 | 0.250 | 0.069 | 0.129 | 0.397 | 1.103 | — |
| **B_embed_lr** | DEV | 182 | **0.236** | **0.113** | **0.181** | **0.182** | 0.965 | +0.9 pt |
| **B_embed_lr** | VAL | 48 | **0.354** | **0.166** | 0.175 | 0.278 | 0.923 | **+9.7 pt** |
| C_fused_char_embed | DEV | 182 | 0.214 | 0.107 | 0.168 | 0.259 | 0.986 | +0.3 pt |
| C_fused_char_embed | VAL | 48 | 0.354 | 0.154 | 0.175 | **0.208** | **0.914** | +8.4 pt |

补充（仅参考标签可被 weak 标签空间覆盖的类上计 macro-F1）：A 0.208/0.162（DEV/VAL），B **0.226/0.387**，C 0.213/0.358。

**绝对水平偏低的主因是标签空间失配（结构性上界，对三路线同等作用）**：DEV 参考含 16 类，weak 标签空间仅覆盖 8 类——SocialGroup(21)、CulturalSite(13)、Position(10)、AdministrativeRegion(9)、Artifact(8)、OTHER、TimePeriod、Spirit 在 DEV 参考中存在但训练集从未出现，三路线对这些类必然 0 召回，macro-F1 上界 ≈ 8/16 = 0.5。对照：生产冻结分类器单信号（S7_classifier_only）在同 DEV 上 selective_accuracy=0.226@coverage 0.906，盲 LLM（S8）=0.697——纯名称弱监督分类器离饱和还很远。

## 4. 嵌入链路（本地、批量、缓存、断点续跑）

| 项 | 值 |
|---|---|
| 后端 | LM Studio `text-embedding-nomic-embed-text-v1.5`（本地 `127.0.0.1:1234`，`lmstudio_provider.embed`，全程无公网） |
| 规模 | 946 条唯一文本（1210 训练行 + 230 评价名去重后），768 维 |
| 耗时 | 冷启动 **10.4 s**（batch=64，约 11 ms/条）；训练拟合 A/B/C = 0.03/0.24/0.62 s；管线总时长 25.3 s（含 build_signal_frame ~13 s） |
| 缓存/断点 | `emb_cache/EMB_CACHE.npy` + `.keys.json`，每 500 条新嵌入落盘一次（实测 512/946 checkpoint 触发）；中断续跑已验证（二次运行 0 条重算、0.0 s） |

## 5. 判定

- **胜者 = B_embed_lr**：DEV 与 VAL macro-F1 均为三路线最高，同时校准显著优于 A（DEV ECE 0.182 vs 0.398；Brier 0.965 vs 1.157），已落盘为 `experiments/02_selective_semantic/predictor_upgrade/M3_improved_predictor.joblib`（附 `.metadata.json`；B/C 工件预测时需本地 LM Studio embeddings 在线，加载方式见 metadata `load_hint`）。
- **显著性（预注册规则：DEV 决策、macro-F1 差 >2 个百分点算显著升级）**：DEV 上 B 领先 A 仅 **+0.9 pt，未达阈值 → 按 DEV 规则不构成显著升级**；但 VAL 观察值 **+9.7 pt**（远超 2 pt）且 B 在 accuracy/bal-acc/ECE/Brier 全指标、两切分上均不劣于 A。综合结论：**嵌入路线方向性胜出，但按最严格的 DEV 规则应表述为"未达 DEV 显著性阈值、VAL 强烈支持"**——与弱监督小训练集（1210 条、8 类）的容量限制一致。
- C（融合）未优于 B：char TF-IDF 块把 A 的类失衡倾向（DEV 上 A 退化地把 114/182 预测为 Place）部分带入融合头，融合仅在 ECE 上略优于 B（VAL 0.208 vs 0.278）。

## 6. 结论与边界

1. 在仅用 `canonical_name` + 1210 条弱标签的约束下，**nomic-embed 嵌入路线（B）是 M3_improved_predictor**：精度、均衡指标与校准全面优于 char TF-IDF 生产复现基线（A），融合路线（C）无附加收益。
2. macro-F1 的天花板由 weak 标签空间（8 类）与参考空间（DEV 16 类）的失配决定；若要继续提升，需扩充弱标签覆盖类（SocialGroup/CulturalSite/AdministrativeRegion/Position 等）而非继续调分类头。
3. 边界：B/C 工件推理依赖本地 LM Studio embeddings 服务（127.0.0.1，离线不可用，与生产链本地化原则一致）；本次未触碰 TEST；未做统计显著性检验（n_val=48 过小，仅报告点估计与预注册阈值规则）。

## 7. 产物与复现

| 文件 | 说明 |
|---|---|
| `code/experiment_pipelines/run_predictor_upgrade.py` | 管线（训练集构建 / 嵌入缓存 / 三路线 / 指标 / 判定 / 落盘） |
| `code/tests/test_predictor_upgrade.py` | 冒烟测试 8 项（指标解析性质、缓存断点续跑、三路线微数据可拟合、判定规则），全部通过，无网络依赖 |
| `experiments/02_selective_semantic/predictor_upgrade/M3_improved_predictor.joblib`(+`.metadata.json`) | 胜者工件（路线 B） |
| `…/PREDICTOR_UPGRADE_SUMMARY.json` / `PREDICTOR_UPGRADE_METRICS.csv` / `PREDICTOR_UPGRADE_RUNS.csv` | 全量配置、指标、逐样本预测 |
| `…/TRAIN_MANIFEST.json`、`…/emb_cache/` | 训练集构成与哈希；嵌入缓存 |

复现：`python code/experiment_pipelines/run_predictor_upgrade.py`（需本地 LM Studio 已加载 nomic 嵌入模型；冷启动 ~25 s，热缓存 ~13 s）。本次仅新建文件，未修改任何既有文件。
