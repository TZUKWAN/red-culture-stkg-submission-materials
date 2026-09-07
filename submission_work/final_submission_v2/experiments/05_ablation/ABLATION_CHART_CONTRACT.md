# 消融实验图表合同

## 分析问题与可支持结论

- 问题一：在共享代理 AI 参考集上，关闭类别门禁、独立信号一致性或弃权后，覆盖率、选择性风险和错误暴露如何共同变化？
- 问题二：在 424,150 条冻结断言的确定性回放中，关闭结构组件会产生哪些不同单位的结构后果？
- 可支持结论：独立信号与弃权呈现覆盖—风险权衡；契约、身份投影、role-owner 与风险路由在全库回放中阻止可计数的结构偏差。
- 不支持的结论：共享代理参考集不应解释为独立专家逐条标注集；不同结构指标的计数不可相加或解释为统一性能分数；provenance 的零差异不等于组件无用。

## 图形选择

- 左面板：同一比率单位的分组条形图，展示完整方法及三个移除变体的 coverage、selective risk、unsafe exposure。
- 右面板：六个独立结构指标卡，各自保留指标名称、单位、证据类和精确数值，不使用共同数轴，不做可加总暗示。
- 关系契约的 148 条 AI 参考样本因均为 contract-positive，只作为“共享代理饱和”说明；图中使用全库 3,412 条新增严格契约违例。
- role-owner 同时显示 44 条时间 owner 与 112 条空间 owner 结构错误。
- provenance 显示 0 差异，并标注“发布后饱和 canary：424,150 条均已有 lineage”。

## 数据与口径

- `ABLATION_FIGURE_DATA.csv`
- `ablation_experiment_summary.json`
- `ABLATION_PREDICTIONS.csv`
- actual-run 与 deterministic-replay 分开标注；无在线 LLM 调用。

## 视觉规范

- 本地 Matplotlib 静态输出；12×7.5 英寸，PNG 200 dpi 与单页 PDF。
- 蓝色 `#2F5597`：覆盖率/完整组件；橙色 `#D97706`：选择性风险或组件移除；深灰 `#444444`：错误暴露及中性说明。
- 使用填充、描边、网纹和直接标签，不只依赖颜色。
- 比率轴从 0 起；结构卡无共用数轴。

## 输出与 QA

- `fig_component_ablation.png`
- `fig_component_ablation.pdf`
- `ABLATION_FIGURE_AUDIT.json`
- 最终 PNG 原尺寸目视检查；PDF 页数、文件哈希和来源哈希自动检查。
