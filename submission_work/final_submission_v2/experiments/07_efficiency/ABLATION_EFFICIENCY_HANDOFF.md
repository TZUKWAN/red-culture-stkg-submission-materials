# 论文 A 消融与端到端效率实验交接

## 完成状态

- 消融实验审计：`PASS`。
- 端到端效率审计：`PASS`。
- 消融图审计及原分辨率目视检查：`PASS`。
- 效率图审计及原分辨率目视检查：`PASS`。
- 专项测试：`8 passed`。
- 冻结 V2、分类器数据库、模型文件、712 条集成参考标注和受控样本文件的运行前后 SHA-256 完全一致。
- 未调用外部 AI、本地 LLM 或在线 LLM；本地模型仅为既有 TF-IDF + SGD 分类器。

## 消融结论

- 完整结构回放与发布库 `424,150 / 424,150` 条状态一致，固定点违例、严格契约违例、owner 类型错误和缺失来源均为 0。
- 去风险路由：43,945 条断言状态改变。
- 去身份投影：24,005 条断言状态改变；实体投影从 154,150 个源实体收敛至 152,979 个规范实体，减少 1,171 个。
- 去关系契约：新增 3,412 条严格域—值域违例。
- 去 role-owner 闭包：新增 44 条时间 owner 和 112 条空间 owner 类型错误。
- 去全局闭包：27,475 条断言状态改变，并出现 3,412 条严格契约违例及 44/112 条时空 owner 错误。
- 去来源门禁：发布库上差异为 0；这是 424,150 条断言均已具备 lineage 的发布后饱和 canary，不表示来源门禁无效。
- 分类器共享代理参考：完整选择性方法 coverage=0.35468、selective risk=0.05556、unsafe exposure=0.01970；去独立信号后分别为 0.65025、0.08333、0.05419；去弃权后为 1.0、0.11823、0.11823。
- 关系契约的 148 条 AI 参考记录全部为 contract-positive，两个变体均 148/148；该子集没有辨别力，主证据使用全库 3,412 条结构违例。
- role-owner AI 参考子集未命中 208 条发布 scope adjustment，因此配对得分不具辨别力，主证据使用全库 44/112 条结构错误。

## 端到端效率

五档均真实运行 5 次，并使用拉丁方轮换执行顺序。warm-process 不含模型包加载；model-load-inclusive 含每次真实 `joblib.load`。正式运行前有小规模预热且未清空 OS 文件缓存，因此不称 OS-level cold start。缓存模型输出回放与在线 LLM 均不计入两种总耗时。

| 规模 | warm 中位数（IQR）/s | 含加载中位数（IQR）/s | warm 吞吐/断言·s⁻¹ | 含加载吞吐/断言·s⁻¹ | 峰值 RSS 中位数/MB |
|---:|---:|---:|---:|---:|---:|
| 10% | 16.675（15.868—16.798） | 17.192（16.586—17.446） | 2,543.68 | 2,467.20 | 430.027 |
| 25% | 21.433（19.564—22.548） | 21.927（20.039—23.656） | 4,947.46 | 4,835.87 | 540.115 |
| 50% | 32.530（30.696—34.670） | 33.033（31.134—35.465） | 6,519.29 | 6,420.05 | 845.173 |
| 75% | 41.195（39.388—41.280） | 41.911（39.915—41.936） | 7,722.06 | 7,590.24 | 1,147.044 |
| 100% | 45.900（44.468—46.633） | 46.749（45.120—47.221） | 9,240.76 | 9,073.01 | 1,428.836 |

100% 规模的逐运行占比中位数：数据读取 77.47%，规则与标注 11.13%，特征向量化 3.90%，role-owner 闭包 1.77%，一致性检查 1.19%，关系契约 0.96%；模型包加载占含加载口径 1.276%。

描述性五点拟合：

- warm 线性：截距 13.9211 s，斜率 `7.9913e-5 s/assertion`，R²=0.9820；幂律指数 0.4605，原空间 R²=0.9837。
- 含加载线性：截距 14.3307 s，斜率 `8.0847e-5 s/assertion`，R²=0.9833；幂律指数 0.4546，原空间 R²=0.9826。
- 上述拟合只描述五个规模中位数；固定读取开销会影响截距和幂律指数，不能作为渐近复杂度证明。

## 关键输出

- `05_ablation/ABLATION_RUNS.csv`
- `05_ablation/ABLATION_PREDICTIONS.csv`
- `05_ablation/ablation_experiment_summary.json`
- `05_ablation/ablation_experiment_audit.json`
- `05_ablation/fig_component_ablation.png|pdf`
- `07_efficiency/END_TO_END_RUNS.csv`
- `07_efficiency/END_TO_END_SUMMARY.csv`
- `07_efficiency/SCALING_FITS.csv`
- `07_efficiency/end_to_end_efficiency_summary.json`
- `07_efficiency/end_to_end_efficiency_audit.json`
- `07_efficiency/fig_end_to_end_efficiency.png|pdf`

## 验证命令与 Debug 记录

- `python run_component_ablations.py`：最终 `PASS`。
- `python run_end_to_end_efficiency.py`：25 次运行、每次 16 个记录阶段，最终 `PASS`。
- `python build_ablation_figure.py`：最终 `PASS`；身份投影卡首次目视发现文字重叠，拆分单位和证据行后重新生成并复查通过。
- `python build_efficiency_figure.py`：最终 `PASS`。
- `pytest tests/test_paper_a_revision_ablation_efficiency.py -q`：`8 passed`。
- role-owner 首次 canary 因同一事实同时属于 role 与 owner 任务而触发临时表主键重复；改为稳定去重后重跑通过。
- 项目虚拟环境无 `pypdf`；PDF 页数审计改用项目已安装的 PyMuPDF (`fitz`)，重新运行通过。
- 与旧 `test_paper_a_experiment_integrity.py` 联跑时，正文正在被主线重构，数学审计仍保存旧正文 SHA；结果为 17 通过、1 个陈旧哈希失败。正文定稿后必须由主线重跑 `audit_mathematical_formalization.py`。
