# -*- coding: utf-8 -*-
"""批C_跨源效率.py — K01–K10 跨来源稳健性与构建效率（10张）"""
import sys, os, json
sys.path.insert(0, r"D:\REDCULTUREDATA\可视化输出\10_生成脚本")
from style_lib import *
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

MID = r"D:\REDCULTUREDATA\可视化输出\11_数据中间表"
SCR = "批C_跨源效率.py"
E07 = json.load(open(os.path.join(MID, "E07_跨来源.json"), encoding="utf-8"))
MX = E07["metrics"]; SPLITS = ["random", "book_grouped", "province_holdout"]
SPLIT_ZH = {"random": "随机切分", "book_grouped": "书籍分组", "province_holdout": "湖北省留出"}
E24 = pd.read_csv(os.path.join(MID, "E24_论文表5_效率实验.csv"))

# ---------- K01 三切分核心指标对比（分组点图） ----------
fig, ax = new_fig(7.6, 4.8)
metrics = [("accuracy", "准确率"), ("macro_f1", "Macro-F1"), ("balanced_accuracy", "平衡准确率"),
           ("coverage", "覆盖率"), ("selective_risk", "选择性风险")]
xs = np.arange(len(metrics))
for i, sp in enumerate(SPLITS):
    vals = [MX[sp][k] for k, _ in metrics]
    ax.scatter(xs, vals, s=90, color=SEQ10[i], label=SPLIT_ZH[sp], zorder=3)
    for x, v in zip(xs, vals):
        ax.annotate(f"{v:.3f}", (x, v), textcoords="offset points", xytext=(0, 9),
                    ha="center", fontsize=8.5, color=FAINT)
ax.set_xticks(xs); ax.set_xticklabels([m[1] for m in metrics])
ax.set_ylabel("指标值"); ax.set_ylim(0.30, 0.66)
ax.set_title("三种切分方式下的实体语义预测性能对比")
despine(ax); light_grid(ax); ax.legend(loc="upper right", ncol=3)
fig.text(0.01, 0.012, "数据源：experiments/09_cross_source_robustness/CROSS_SOURCE_SUMMARY.json（weak-label 口径，n=1210）",
         fontsize=8, color=FAINT)
save_fig(fig, "K01", "三种切分方式性能对比", "跨来源稳健性", SCR, ["E07_跨来源.json"],
         "随机切分高估宏观F1约3.0点、平衡准确率5.7点；湖北留出风险翻倍")

# ---------- K02 风险指标哑铃 ----------
fig, ax = new_fig(7.2, 4.0)
risk_pairs = [("selective_risk", "选择性风险"), ("aurc_trapezoid", "AURC（风险-覆盖面积）")]
base = MX["random"]
for j, (k, lab) in enumerate(risk_pairs):
    y = 1 - j
    for i, sp in enumerate(SPLITS):
        v = MX[sp][k]
        ax.plot([v, v], [y - .16, y + .16], color=SEQ10[i], lw=2.4)
        ax.scatter([v], [y], s=70, color=SEQ10[i], zorder=3)
        ax.annotate(f"{SPLIT_ZH[sp]} {v:.3f}", (v, y), textcoords="offset points",
                    xytext=(0, 12 if i != 1 else -16), ha="center", fontsize=8.5, color=SEQ10[i])
ax.set_yticks([1, 0]); ax.set_yticklabels([l for _, l in risk_pairs])
ax.set_xlabel("风险指标值（越低越好）")
ax.set_xlim(0.10, 0.34)
ax.set_title("跨来源切分的选择性风险恶化")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：CROSS_SOURCE_SUMMARY.json；湖北省留出使选择性风险 0.129→0.211（+8.2点）", fontsize=8, color=FAINT)
save_fig(fig, "K02", "切分方式的风险指标哑铃图", "跨来源稳健性", SCR, ["E07_跨来源.json"],
         "跨省部署时置信门控错误率接近翻倍")

# ---------- K03 实体类型×切分 F1 热力 ----------
classes = ["Organization", "Place", "Person", "Event", "Institution", "Document", "Concept", "ValueFacet"]
mat = np.array([[MX[sp]["per_class_f1"][c] for sp in SPLITS] for c in classes])
fig, ax = new_fig(6.8, 5.4)
im = ax.imshow(mat, cmap=mpl.colors.LinearSegmentedColormap.from_list("m", GREEN_SEQ), vmin=0, vmax=0.9, aspect="auto")
ax.set_xticks(range(3)); ax.set_xticklabels([SPLIT_ZH[s] for s in SPLITS])
ax.set_yticks(range(len(classes))); ax.set_yticklabels([ez(c) for c in classes])
for i in range(len(classes)):
    for j in range(3):
        sup = MX[SPLITS[j]]["per_class_support"][classes[i]]
        ax.text(j, i, f"{mat[i,j]:.2f}\n(n={sup})", ha="center", va="center", fontsize=8.5,
                color="#2F4A2B" if mat[i, j] > 0.45 else FAINT)
ax.set_title("各实体类型在三切分下的 F1")
cb = fig.colorbar(im, ax=ax, shrink=0.75, pad=0.02); cb.set_label("F1", fontsize=9)
despine(ax, keep=()); fig.text(0.01, 0.012, "数据源：CROSS_SOURCE_SUMMARY.json per_class_f1/per_class_support", fontsize=8, color=FAINT)
save_fig(fig, "K03", "实体类型×切分F1热力图", "跨来源稳健性", SCR, ["E07_跨来源.json"],
         "稀有类（概念）在非随机切分下消失")

# ---------- K04 掉幅最大类别瀑布 ----------
fig, ax = new_fig(7.2, 4.2)
drops = []
for c in classes:
    f_r = MX["random"]["per_class_f1"][c]
    worst = min(MX["book_grouped"]["per_class_f1"][c], MX["province_holdout"]["per_class_f1"][c])
    drops.append((c, worst - f_r))
drops.sort(key=lambda x: x[1])
sel = drops[:6]
xs = np.arange(len(sel))
ax.bar(xs, [d for _, d in sel], color=[M["绛陶"] if d < 0 else M["橄榄"] for _, d in sel], width=0.55, zorder=3)
for x, (c, d) in zip(xs, sel):
    ax.annotate(f"{d:+.3f}", (x, d), textcoords="offset points", xytext=(0, -14 if d < 0 else 8),
                ha="center", fontsize=9, color=INK)
ax.set_xticks(xs); ax.set_xticklabels([ez(c) for c, _ in sel])
ax.axhline(0, color=AXIS, lw=0.8)
ax.set_ylabel("F1 变化（相对随机切分）")
ax.set_title("非随机切分下退化最严重的实体类型")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：CROSS_SOURCE_SUMMARY.json；取书籍分组与湖北留出中较差者", fontsize=8, color=FAINT)
save_fig(fig, "K04", "退化最大实体类别瀑布图", "跨来源稳健性", SCR, ["E07_跨来源.json"],
         "概念-0.18、事件-0.06、人物-0.05 为最大退化类")

# ---------- K05 同书互引分量结构 ----------
fig, ax = new_fig(7.2, 4.2)
ps = E07["provenance_stats"]
vals = [ps["n_entities_with_book"], ps["n_entities_no_book"]]
# 572 有书实体中 569 同属一个分量
import matplotlib.patches as mp
tot = vals[0] + vals[1]
ax.barh([1], [569 / tot * 100], color=M["雾蓝"], height=0.42, zorder=3, label="同一互引分量（不可拆分）")
ax.barh([1], [(572 - 569) / tot * 100], left=569 / tot * 100, color=M["橄榄"], height=0.42, zorder=3)
ax.barh([0], [vals[1] / tot * 100], color=M["陶砂"], height=0.42, zorder=3, label="无书实体（可分组）")
ax.set_yticks([1, 0]); ax.set_yticklabels(["有书实体 572", "无书实体 638"])
ax.set_xlabel("占 1210 实体语料比例（%）")
for x, t, c in [(569 / tot * 50, "569（99.5%）", "#FFFFFF"), ((569 + 1.5) / tot * 100 + 8, "3", INK),
                (vals[1] / tot * 50, "638", "#FFFFFF")]:
    if t == "3":
        ax.annotate(t, (x, 1), fontsize=8.5, color=INK, ha="center", va="center")
    else:
        ax.text(x, 1 if t.startswith("569") else 0, t, ha="center", va="center", fontsize=9, color=c)
ax.set_xlim(0, 100)
ax.set_title("同书互引分量使实体级书籍切分结构性不可达")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=2)
fig.text(0.01, 0.012, "数据源：CROSS_SOURCE_SUMMARY.json provenance_stats；《中共党史人物传》多卷本+县市资料密集互引", fontsize=8, color=FAINT)
save_fig(fig, "K05", "同书互引分量结构图", "跨来源稳健性", SCR, ["E07_跨来源.json"],
         "99.5%有书实体属于同一并查集分量")

# ---------- K06 效率：时间-规模（中位数+IQR带） ----------
fig, ax = new_fig(7.4, 4.6)
sizes = E24["规模"].tolist()
x = np.arange(len(sizes))
hot = E24["热启动中位s"].values
iqr_h = E24["热启动IQR"].values if "热启动IQR" in E24 else None
load = E24["含加载中位s"].values
ax.fill_between(x, hot - 2.165, hot + 2.165, color=M["雾蓝"], alpha=0.14, label="100% IQR 参考（±2.165s）")
ax.plot(x, hot, "-o", color=M["雾蓝"], lw=2, ms=6, label="热启动中位数", zorder=4)
ax.plot(x, load, "--s", color=M["陶砂"], lw=1.8, ms=5.5, label="含本地模型加载", zorder=4)
for xi, v in zip(x, hot):
    ax.annotate(f"{v:.1f}", (xi, v), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8.5, color=FAINT)
ax.annotate("45.900s", (4, load[4]), textcoords="offset points", xytext=(0, -15), ha="center", fontsize=8.5, color=M["陶砂"])
ax.set_xticks(x); ax.set_xticklabels([f"{s}\n({n:,})" for s, n in zip(sizes, E24["陈述数"])], fontsize=9)
ax.set_xlabel("知识规模（陈述数）"); ax.set_ylabel("构建时间（秒，中位数）")
ax.set_title("本地图谱构建链时间随规模稳定增长")
despine(ax); light_grid(ax); ax.legend(loc="upper left")
fig.text(0.01, 0.012, "数据源：论文表5（每档5次重复，中位数；IQR见论文§4.5）", fontsize=8, color=FAINT)
save_fig(fig, "K06", "构建链时间-规模曲线", "构建效率", SCR, ["E24_论文表5_效率实验.csv"],
         "100%规模热启动中位45.9s，加载开销仅0.849s")

# ---------- K07 吞吐-规模 ----------
fig, ax = new_fig(7.0, 4.4)
th = E24["热启动吞吐"].values
ax.plot(x, th, "-o", color=M["橄榄"], lw=2.2, ms=6, zorder=4)
for xi, v in zip(x, th):
    ax.annotate(f"{v:,.0f}", (xi, v), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8.5, color=FAINT)
ax.set_xticks(x); ax.set_xticklabels(sizes)
ax.set_xlabel("知识规模"); ax.set_ylabel("吞吐（条/秒，热启动）")
ax.set_title("构建链吞吐随规模上升并趋于饱和")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：论文表5", fontsize=8, color=FAINT)
save_fig(fig, "K07", "构建链吞吐-规模曲线", "构建效率", SCR, ["E24_论文表5_效率实验.csv"],
         "100%规模吞吐9,241条/s")

# ---------- K08 内存-规模 ----------
fig, ax = new_fig(7.0, 4.4)
rss = E24["峰值RSS_MB"].values
ax.plot(x, rss, "-o", color=M["陶砂"], lw=2.2, ms=6, zorder=4)
for xi, v in zip(x, rss):
    ax.annotate(f"{v:,.0f}", (xi, v), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8.5, color=FAINT)
# 线性参考
k = (rss[-1] - rss[0]) / (424150 - 42415)
ref = k * (E24["陈述数"].values - 42415) + rss[0]
ax.plot(x, ref, ":", color=AXIS, lw=1.2)
ax.annotate("近线性参考", (2.1, ref[2] + 40), fontsize=8.5, color=FAINT)
ax.set_xticks(x); ax.set_xticklabels(sizes)
ax.set_xlabel("知识规模"); ax.set_ylabel("峰值内存（MB）")
ax.set_title("构建链峰值内存近线性增长")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：论文表5", fontsize=8, color=FAINT)
save_fig(fig, "K08", "构建链内存-规模曲线", "构建效率", SCR, ["E24_论文表5_效率实验.csv"],
         "100%规模峰值RSS 1,428.8MB")

# ---------- K09 100%规模耗时构成瀑布 ----------
fig, ax = new_fig(7.6, 4.4)
steps = [("来源读取", 36.125), ("规则与标注", 5.188), ("特征向量化", 1.788),
         ("时空与归属检查", 0.772), ("本地分类器推理", 0.165)]
cum = 0
for i, (n, v) in enumerate(steps):
    ax.bar(i, v, bottom=cum, color=SEQ10[i], width=0.58, zorder=3)
    ax.annotate(f"{v:.3f}s\n({v/46.749*100:.1f}%)", (i, cum + v / 2), ha="center", va="center",
                fontsize=8.5, color="#FFFFFF")
    cum += v
ax.bar(len(steps), cum, color=INK, width=0.58, zorder=3)
ax.annotate(f"{cum:.3f}s", (len(steps), cum / 2), ha="center", va="center", fontsize=9, color="#FFFFFF")
ax.set_xticks(range(len(steps) + 1))
ax.set_xticklabels([wrap_zh(n, 5) for n, _ in steps] + ["含加载总计"], fontsize=9)
ax.set_ylabel("耗时（秒）")
ax.set_title("100%规模下构建链耗时构成：来源读取是主瓶颈")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：论文§4.5（中位耗时，占比以含加载46.749s为分母）", fontsize=8, color=FAINT)
save_fig(fig, "K09", "满规模耗时构成瀑布图", "构建效率", SCR, ["论文§4.5"],
         "来源读取36.1s占77.5%，为优化关键")

# ---------- K10 热启动 vs 含加载哑铃 ----------
fig, ax = new_fig(7.2, 4.2)
for i, s in enumerate(sizes):
    y = len(sizes) - 1 - i
    ax.plot([hot[i], load[i]], [y, y], color=GRID, lw=2.4, zorder=2)
    ax.scatter([hot[i]], [y], s=64, color=M["雾蓝"], zorder=3)
    ax.scatter([load[i]], [y], s=64, color=M["陶砂"], zorder=3)
    ax.annotate(f"Δ{load[i]-hot[i]:.2f}s", ((hot[i]+load[i])/2, y), textcoords="offset points",
                xytext=(0, 9), ha="center", fontsize=8, color=FAINT)
ax.set_yticks(range(len(sizes))); ax.set_yticklabels(sizes[::-1])
ax.set_xlabel("构建时间（秒，中位数）")
ax.set_title("热启动与含模型加载的耗时对比")
from matplotlib.lines import Line2D
ax.legend(handles=[Line2D([], [], marker='o', ls='', color=M["雾蓝"], label='热启动'),
                   Line2D([], [], marker='o', ls='', color=M["陶砂"], label='含加载')], loc="lower right")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：论文表5", fontsize=8, color=FAINT)
save_fig(fig, "K10", "热启动与含加载耗时哑铃图", "构建效率", SCR, ["E24_论文表5_效率实验.csv"],
         "各档加载开销均小于1秒")

print("批次C（K01-K10）完成")
