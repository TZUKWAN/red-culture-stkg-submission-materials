# 旧稿实验章节 → V3 重写稿映射（OLD_TO_NEW_MAPPING）

- 旧稿：`submission_work/final_submission_v2/选择性预测与结构准入协同的长江流域中共党史时空知识图谱构建_投稿终稿_学术创新强化版.docx`（只读，未修改）
- 新稿：`submission_work/final_submission_v3/manuscript/experiment_chapter_rewritten.md` / `.docx`
- 旧稿图表对照依据：`submission_work/final_submission_v2/FIGURE_TABLE_FORMULA_MAPPING.md`
- 修改原则：GOAL §二十五（4.1–4.8）、§二十六（实验→审计→再改论文）、§二十七（措辞边界）、§二十八（旧实验不删除）、§三十（表A–F、图A–D）

## 1. 小节级映射

| 旧稿小节 | 处置 | 新稿位置 | 理由 |
|---|---|---|---|
| 4.1 数据对象、模型配置与评价协议 | **重写+扩充** | 4.1（4.1.1–4.1.4） | 旧稿仅以 ERA(712)/159/152 为统一参照，且未披露 ERA 与生产信号的共享通道。新稿改为 ERA/IMCR 双轨制，补齐盲评协议、judge 面板（3 家族）、共识规则、leave-one-out 参考、judge 一致性（表A）与统计口径；旧"983 册/302,230 页"语料规模在 PAPER_CLAIM_EVIDENCE_MATRIX 中为 NOT_FULLY_VERIFIED，新稿不再引用 |
| 4.2 选择性预测结果与组件分析（表1、表2、图3） | **改写+降级+拆分** | 4.2 + 4.3 | 旧表1（152 条核心集 M1–M6）整体降级为 C+D 级"相对于 ERA 的一致性结果"，仅作历史对照保留（新 4.2 末：era_replay 逐位复现 PASS）；旧表2（203 条实体消融）属共享代理参考诊断（D 级），其结论由新表C（B10/B11/B12 独立消融）替代；新表B/图A 为 IMCR 独立基线比较。旧稿隐含"框架标签质量优于强 LLM"的主张被新证据否定（B3 盲 LLM 五任务全胜，McNemar entity 2:141），必须如实写入并改写判断 |
| 4.3 结构准入结果与全库消融（表3、图4、图5、图6） | **保留（Panel A）+新增（Panel B）** | 4.4 + 4.5 | 旧表3/图4 的全库确定性消融原样保留为新表D Panel A（B 级，结构合法性口径，全部标注"相对于冻结发布库的结构一致性结果"）；图5/图6（事件框架查询、南昌起义子图）属方法演示，不涉参考标签，保留于方法/案例部分，不进实验章节。208 条修正与 3,412 条契约变化的语义验证为全新 Panel B（4.5，E 级），其结论对旧稿不利（scope 方向未获确认、relation κ=0.037 参考失效），必须如实写入 |
| 4.4 来源追溯与跨来源检验（图7） | **重写+扩充** | 4.7 | 旧稿仅有链路演示（图7 保留于方法部分）；新 4.7 补 1,000 条三层来源支持盲评（表F，支持率梯度 64.6%>57.3%>48.5%，以及严格层 33.7% 未获支持的负结果）、Provenance Gate 重新定位为发布安全不变量（w/o=0 的正确解释）+故障注入压力测试（100% 拦截、0 假阳性）、配对 ΔAURC(Full−B3)=+0.375 的劣势结果（图B） |
| 4.5 本地确定性构建链的规模与效率（表4、图8） | **保留** | 4.8 | 计时类证据（A 级）不受 ERA 自指影响，五档×5 次结果原样沿用，仅补证据等级标注与 IMCR 评价链成本披露（11,320 次调用） |

## 2. 旧表 → 新表映射

| 旧表 | 处置 | 新表 | 理由 |
|---|---|---|---|
| 表1（152 条核心集分级证据） | 降级保留 | 新 4.2 末文字（era_replay 复现；数字标注"相对于 ERA 的一致性结果"） | C+D 级共享通道诊断，不得作为主要证据；头条数字 0.7632/0.9914/0.0086 逐位等于 M4 的 coverage/accuracy_on_covered/selective_risk（0.763158/0.991379/0.008621） |
| 表2（203 条实体选择性消融） | 替代 | 表C（B10/B11/B12，IMCR strong） | 旧消融参考为共享代理（shared_proxy_reference），无独立解释资格；新消融在独立参考上重做 |
| 表3（全库结构消融） | 保留 | 表D Panel A | 确定性回放（B 级）本身有效，仅限结构合法性解释；数据文件 `v2/experiments/05_ablation/ablation_experiment_summary.json` 未覆盖 |
| 表4（五档效率） | 保留 | 新 4.8 文字引用 | A 级计时证据；`v2/experiments/07_efficiency/END_TO_END_SUMMARY.csv` 未覆盖 |
| —（无） | 新增 | 表A judge 一致性 | GOAL §三十；judge 可靠性是本章结论强度的调节变量 |
| —（无） | 新增 | 表B 独立基线比较 | GOAL §三十；主证据表 |
| —（无） | 新增 | 表E 身份投影验证 | 600 对 + 300 难负例，旧稿无任何身份归并的独立验证 |
| —（无） | 新增 | 表F 来源支持质量 | 1,000 条三层盲评，旧稿无语义层面的来源支持证据 |

数据文件：表A `experiments/08_independent_reference/JUDGE_RELIABILITY_SUMMARY.csv`；表B/C `experiments/13_selective_inference_independent/imcr_strong/imcr_strong_SELECTIVE_GOAL13_METRICS.csv` + `experiments/14_statistical_tests/WILSON_CI_TABLE.csv`；表D Panel A `v2/experiments/05_ablation/ablation_experiment_summary.json`、Panel B `experiments/08_independent_reference/IMCR_REFERENCE_*.csv` + `experiments/10_structural_validation/*`；表E `experiments/11_identity_validation/*`；表F `experiments/12_provenance_validation/*`。

## 3. 旧图 → 新图映射

| 旧图 | 处置 | 新图 |
|---|---|---|
| 图1 研究框架 | 保留（方法部分，不涉评价） | — |
| 图2 图谱规模与分层 | 保留（4.1 规模段文字引用） | — |
| 图3 ERA 风险—覆盖 | 降级为历史对照 | 图A（IMCR strong 独立风险—覆盖，`figures/imcr_risk_coverage.png`）；图B（ΔAURC/ΔAUGRC 95%CI，`figures/imcr_aurc_augrc_ci.png`） |
| 图4 结构违例拦截 | 保留（表D Panel A 引用） | 图C（208 条改前/改后盲评，`figures/imcr_scope_validation.png`）；图D（关系契约 changed/control，`figures/imcr_relation_contract_validation.png`） |
| 图5/图6 事件框架查询与子图 | 保留（方法/案例部分） | — |
| 图7 来源追溯链路 | 保留（方法部分） | 表F 为其新增语义层证据 |
| 图8 效率 | 保留 | 新 4.8 引用 |

## 4. 旧数字 → 新表述映射（凡保留必带限定）

| 旧数字 | 旧稿含义 | 证据等级（V3 审计） | 新稿处置 |
|---|---|---|---|
| 0.7632 / 0.9914 / 0.0086 | 头条结果：覆盖/一致率/选择性风险 | C+D（M4 缓存+共享通道；era_replay 逐位复现 PASS） | 保留为"相对于 ERA 的一致性结果"（新 4.2 末、4.9(1)），摘要不再作为主结果 |
| 0.9934 / 0.8808 / 0.1192 | Qwen 基线 | C+D（M3 缓存） | 从摘要/结论删除；如引用同表1一并降级 |
| 712 ERA / 159 测试 / 152 核心 | 统一评价参照 | A（历史构造）+D（共享通道） | 保留为历史对照轨（新 4.1.1），不再作外部正确性 |
| 44 / 112 非法归属、208 条调整 | 结构消融+表示贡献 | B（确定性回放） | 保留（表D Panel A、4.5.1）；语义合理性主张降级为"未获独立确认、方向存否"（strong：改后 45.9% vs 改前 52.3%） |
| 3,412 条契约违例 | 结构消融 | B | 保留结构口径（4.4）；语义有效性结论改为"结构效应确定、语义效应未定"（κ=0.037 参考失效，4.5.2）；旧 148 条饱和子集论证删除（无辨别力） |
| 1,171 身份归并 / 24,005 / 27,475 / 43,945 / 0 | 结构消融 | B | 保留（4.4），"捆绑移除不可相加""0=发布后饱和"两处解释边界随表给出 |
| 0.8713 分类器验证集指标 | 方法质量 | A（held-out，但目标是 ERA） | 不再进实验章节主结果；如保留须注明监督代理性质 |
| 983 册 / 302,230 页 / 282,165 / 67,791 / 17,450 | 语料规模 | UNVERIFIED（PAPER_CLAIM_EVIDENCE_MATRIX） | 全部不再引用（新 4.1.1 明示） |
| 152,979 / 424,150 / 466,312 / 112,158 / 268,047 / 43,945 / 28,065 / 11,532 | 图谱规模 | A（数据库可复核） | 保留（4.1.1、4.4、4.7） |

## 5. 措辞边界核查（§二十七）

- 全文无"金标准/ground truth/事实真值/事实正确率/消除错误/高准确率历史事实识别"表述；IMCR 统一称"独立多模型共识参考/外部 AI 参考标注"。
- 与 IMCR 的比较一律表述为"与独立参考的一致率/一致性""选择性风险""结构违例""来源支持率""层间梯度"。
- 旧数字保留处均带"相对于 ERA 的一致性结果"限定。
- 不利结果未弱化：盲 LLM 五任务全胜（含 2:141）、ΔAURC=+0.375 劣势、scope 改前 52.3% 占优、relation κ=0.037、严格层 33.7% 未获支持、生产置信信号无正向排序力，全部正文如实呈现并写入 4.9 诚实发现清单。
