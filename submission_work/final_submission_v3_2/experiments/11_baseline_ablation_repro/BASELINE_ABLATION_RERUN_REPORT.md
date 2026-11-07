# BASELINE / ABLATION 重跑报告（v3_2 第 11 号实验）

执行：2026-09-24　**0 次模型调用、0 次网络请求**（两脚本 docstring 自证 `actual_llm_calls: 0`）
产物目录：本目录（`final_submission_v3_2/experiments/11_baseline_ablation_repro/`）
被重跑的代码：`final_submission_v2/code/experiment_pipelines/run_baseline_experiments.py`
与 `run_component_ablations.py` 的副本（**唯一改动是输入根路径**，见下）。

## 一、怎么重跑的

论文表 1/2/3 的产出代码只在 v2 世代存在（详见第四节溯源）。副本改动仅两处、不涉及任何计算逻辑：

| 副本 | 改动 | 原因 |
|---|---|---|
| `run_baseline_experiments_v2copy.py:42` | `ROOT = SCRIPT.parents[4]` → `Path(env REDCULTURE_ROOT or "D:/REDCULTUREDATA")` | 副本换层级后 parents[4] 指不到原工作树，找不到 AI_GOLD 等输入 |
| `run_component_ablations_v2copy.py:28` 前 | 插入 `sys.path` 指向 `dual_paper_project/paper_A_method/revision/05_ablation` | `frozen_v2_replay` 模块不在投稿包内 |

输出全部落在本目录（两脚本 `OUTDIR = 脚本所在目录`）。**v2 目录与外部输入目录零写入**，
`find -newermt 2026-09-24` 复查为空。

### 前置：六个受保护输入逐字节一致

`FROZEN_EVALUATION_MANIFEST.json`（2026-07-30）登记的六个 sha256 与今日实测全部 MATCH：

| 输入 | 大小 |
|---|---|
| red_culture_stkg_semantic_v2.sqlite | 1,094,549,504 B |
| red_culture_stkg_final_v2.sqlite | 1,187,962,880 B |
| derived/stkg_v2_entity_classifier.sqlite | 4,112,384 B |
| models/stkg_v2_entity_classifier.joblib | 17,492,249 B |
| AI_GOLD_LABELS.csv | 77,541 B |
| controlled_eval_samples.csv | 478,255 B |

消融脚本运行时自身也做了 before/after 校验（`ablation_experiment_audit.json → source_hashes_before`），
结论 unchanged。

## 二、结果：全部复现

`python compare_rerun_vs_paper.py` → **27 项 ALL PASS**（`PAPER_RERUN_COMPARISON.json`）。

- **表 1**（n=152 核心集五方法）：重跑 `BASELINE_METRICS.csv` 63 行与 v2 冻结产物**逐字段 0 差异**；
  五行全部命中：规则方法 0.9934/0.8742(=132/151)/0.1258/0.8618/0.8967；
  本地分类器 1.0000/0.6250(95/152)/0.3750/0.6184/0.4333；
  缓存模型回放 0.9934/0.8808(133/151)；规则—Qwen 一致性 0.7632(116/152)/0.9914(115/116)/0.0086/0.75；
  完整框架确定性回放 1.0000/0.8618(131/152)。
- **表 2**（n=203 选择性组件消融）：四个变体的 accepted/correct/errors 全中
  （72/68/4、73/69/4、132/121/11、203/179/24），派生率与论文 4 位小数完全一致
  （0.3547/0.9444/0.0556/0.0197/0.3350；0.6502/0.0833/0.0542；1.0000/0.1182）。
- **表 3**（全库结构消融 424,150 条）：完整框架 strict 112,158 / ctx 268,047 / unres 43,945、
  四类违例均 0；去风险路由 changed 43,945；去身份投影 24,005（唯一端点 147,698→148,811）；
  去关系契约 3,412；去角色归属闭包 44/112、changed 208；去全局闭包 27,475；去来源门禁 0。
- **重跑 vs v2 冻结 ABLATION_RUNS**：174 行、键集合一致，**超容差差异 0**；
  仅 2 处 Wilson CI 数组的末位浮点不同（`0.4376043769222226…` vs `…2227`，相对偏差 2.54e-16），
  出现在 Role-owner Closure 的 `selective_accuracy_ci95`，源于 numpy/Python 版本差异，
  对任何呈现位（4 位小数）零影响。已在比对报告 `float_ulp_differences_vs_frozen_v2` 单列披露。

规模与耗时：baseline 约 1 分钟（含 1.19GB+1.09GB 库只读）；消融约 2.5 分钟（全库 424,150 条结构重放）。

## 三、顺带查出的正文缺陷

1. **表 1/2/3/4 在 `manuscript/论文正文.md` 里是残缺的**：每个 `[表格 N]` 块只放了表头 + 2 行数据 +
   一行 `| … |`。正文却写"表1汇报五种方法""消融…如表2"，实际应分别为 5/4/7/5 行。
   全仓检索 `[表格` 只命中 `论文正文.md` 与 `论文正文_base.md`，没有任何脚本消费这些标记，
   也没有 v3_2 世代的 Word 交付物 → 不像是有意的占位约定。
2. `[表格 5]`（级联阶段增益表）**标记缺失**（表体本身完整，在 146–155 行），
   而表 1/2/3/4 都有标记；表 5 排在表 4 之前。
3. 补全行由 `fill_manuscript_tables.py` 从重跑 CSV 现取现算生成（默认预览模式，
   需 `--write` 才写入正文），见 `MANUSCRIPT_TABLE_PREVIEW.md`。
   表 3 的"主要作用"列为本次新写的描述性文字，需作者定稿。

## 四、溯源结论（重要）

- 表 1/2/3 的数字**全部出自 v2 世代产物**，且**不在 v3_1 的六个权威来源、也不在
  `FINAL_NUMBERS.json` 的 31 项 metrics 里**。表内数字与正文叙述（132/151、95/152、116、115、131）
  与 v2 冻结 CSV 完全一致，故这些是"v2 层证据"，其 `evidence_class` 为
  actual_run / cached_replay / deterministic_replay 三类混合，正文表 1 的"证据等级"列已如实区分。
- `final_submission_v3_1/experiments/` 下 `03_true_ablation/`、`04_relation_semantic/`、
  `06_identity_revalidation/` **三个目录为空**，全库检索这三个目录名 0 次引用 → 是占位目录，
  并非产物丢失；对应功能实际分散在 `01_reference_rebuild/`、`02_selective_semantic/`、`05_scope_repair/`。
- v3_1 自己的消融是**另一套口径**（`run_selective_semantic.py` 的 S0–S10 变体、
  IMCR strong 参考、book-grouped 冻结切分、test n=62/276、含 generalized_risk/AURC/risk@x），
  与论文表 2（712ERA→n=203、"去类别门禁/去独立信号一致/取消显式弃权"）**名称与样本量都对不上**。
  若要求表 2 改由 v3_1 世代出数，等于换实验重做，论文数字必须变。

## 五、尚未重跑的部分（需要本地模型）

baseline 与消融本身不需要模型。但 v3_1 世代的升级/裁判链需要 LM Studio，当前
1234/1235 端口无监听（8080 是 Docker 里的 SearXNG）。若要在 v3_1 口径下重跑：

- `run_selective_semantic.py`、`run_risk_routing.py`：DEV/VAL 全读缓存，可离线重跑；
- `run_budget_curves.py`、`run_routing_model_agnostic.py`、`run_frozen_test_eval.py`、
  `run_predictor_upgrade.py`（嵌入）、`run_cross_source_robustness.py`（缺嵌时）：**需要 gpt-oss-20b /
  gemma-4-e4b / qwen3-8b / nomic-embed 在线服务**；
- 其中 `run_frozen_test_eval.py` 顶部声明是"方法冻结后**唯一一次** TEST 正式评价"，
  第二次运行会违反其自身协议（约 19 条 TEST 升级新调用不可避免）——不建议重跑，除非明确批准。

## 六、复现命令

```bash
cd submission_work/final_submission_v3_2/experiments/11_baseline_ablation_repro
python run_baseline_experiments_v2copy.py      # 表1，约 1 分钟
python run_component_ablations_v2copy.py       # 表2/表3，约 2.5 分钟
python compare_rerun_vs_paper.py               # 27 项对齐，ALL PASS
python fill_manuscript_tables.py               # 表1/2/3 补全预览（--write 才写入正文）
```
