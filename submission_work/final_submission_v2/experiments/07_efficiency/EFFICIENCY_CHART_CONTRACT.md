# 端到端效率图表合同

## 分析问题与可支持结论

- 问题：冻结 V2 数据规模从 10% 增至 100% 时，本地确定性流水线的 warm-process 与 model-load-inclusive 耗时、阶段构成、拟合残差和峰值内存如何变化？
- 可支持结论：报告五个规模点、每点五次真实运行的中位数与 IQR；展示一次真实模型包加载对含加载口径的增量，并说明读取阶段的固定开销。正式运行前有小规模预热且未清空 OS 文件缓存，因此不称 OS-level cold start。
- 不支持的结论：五个规模点的线性或幂律拟合不能证明渐近复杂度，也不能代表在线 LLM 延迟。

## 图形选择

- 图族：有序规模比较、阶段构成、拟合残差、资源占用。
- 具体形式：四联静态研究图。
  1. warm/含模型加载中位耗时及 IQR 点线图；
  2. 100% 规模各真实阶段中位耗时横向条形图；
  3. warm-process 线性与幂律拟合残差图；
  4. 各规模最大 RSS 中位数点线图。
- 数据充分性：5 个固定规模点，每点 5 次重复；规模不是时间序列，因此以点、区间和直接数值为主，连线只表达有序规模。
- 拟合：同时给出线性和幂律预测、逐点残差与 R²；图注明确“描述性五点拟合”。

## 数据与口径

- 原始明细：`END_TO_END_RUNS.csv`。
- 汇总：`end_to_end_efficiency_summary.json`、`END_TO_END_SUMMARY.csv`。
- 拟合明细：`SCALING_FITS.csv`。
- warm-process：不含模型包加载、缓存模型输出回放及在线 LLM。
- model-load-inclusive：包含每次真实模型包加载；不含缓存模型输出回放及在线 LLM；内部产物字段仍保留 `cold_start_deterministic_total`。
- 缓存回放单列；在线 LLM 为 `NOT_AVAILABLE`。

## 视觉规范

- 渲染器：本地 Matplotlib 静态输出。
- 画布：12×9 英寸，白底，PNG 200 dpi 与单页 PDF。
- 主色：蓝色 `#2F5597`；对照色：橙色 `#D97706`；中性参照：深灰 `#444444`、浅灰 `#D9DEE7`。
- 非颜色区分：warm 为实心圆/实线，含加载口径为白心方块/虚线；拟合残差使用不同点形与线型。
- 禁止：3D、渐变、双纵轴、截断条形轴、把缓存回放称为模型推理。

## 输出与 QA

- `fig_end_to_end_efficiency.png`
- `fig_end_to_end_efficiency.pdf`
- `EFFICIENCY_FIGURE_AUDIT.json`
- QA 面：最终 PNG 原尺寸目视检查；PDF 页数、可读取性、文件哈希和来源哈希自动检查。
