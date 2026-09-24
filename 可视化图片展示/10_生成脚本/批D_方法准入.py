# -*- coding: utf-8 -*-
"""批D_方法准入.py — F01–F16 选择性预测（16张）+ G01–G08 时空作用域（8张）+ H01–H18 级联准入（18张）"""
import sys, os, json, collections
sys.path.insert(0, r"D:\REDCULTUREDATA\可视化输出\10_生成脚本")
from style_lib import *
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Patch, Circle
import numpy as np
import pandas as pd
import squarify

MID = r"D:\REDCULTUREDATA\可视化输出\11_数据中间表"
SCR = "批D_方法准入.py"

def fbox(ax, x, y, w, h, txt, fc="#F2F4F3", ec=M["青灰"], fs=9.5, weight="normal", tc=INK, lw=1.2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.06,rounding_size=0.12",
                                facecolor=fc, edgecolor=ec, lw=lw, zorder=2))
    ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center", fontsize=fs, color=tc,
            weight=weight, zorder=3, linespacing=1.4)

def farrow(ax, x1, y1, x2, y2, style="-|>", color=FAINT, lw=1.3):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=15,
                                 color=color, lw=lw, zorder=1))

def foot(fig, txt):
    fig.text(0.01, 0.012, txt, fontsize=8, color=FAINT)

# ================= F 选择性预测与风险路由 =================
E21 = pd.read_csv(os.path.join(MID, "E21_论文表2A_选择性语义判定.csv"))
E22 = pd.read_csv(os.path.join(MID, "E22_论文表3_组件消融.csv"))
E01 = pd.read_csv(os.path.join(MID, "E01_预算曲线.csv"))
E02 = pd.read_csv(os.path.join(MID, "E02_路由对比.csv"))
E04 = pd.read_csv(os.path.join(MID, "E04_冻结测试三split.csv"))
E05 = pd.read_csv(os.path.join(MID, "E05_消融12变体TEST.csv"))

# F01 四方法多维点图
fig, ax = new_fig(8.6, 5.2)
metrics = ["接受覆盖率", "接受样本一致率", "选择性风险", "安全覆盖率", "MacroF1"]
xs = np.arange(len(metrics))
for i, m in enumerate(E21["方法"]):
    vals = [E21[E21["方法"] == m][c].values[0] for c in metrics]
    ax.scatter(xs, vals, s=90, color=SEQ10[i], label=m, zorder=3)
    for x, v in zip(xs, vals):
        ax.annotate(f"{v:.3f}".rstrip("0").rstrip("."), (x, v), xytext=(0, 8), textcoords="offset points",
                    ha="center", fontsize=7.2, color=FAINT)
ax.set_xticks(xs); ax.set_xticklabels([wrap_zh(x, 6) for x in metrics], fontsize=9)
ax.set_ylabel("指标值"); ax.set_ylim(0.55, 1.08)
ax.set_title("四种选择性语义判定方法多维对比（n=152 核心评价样本）")
ax.legend(fontsize=8.4, loc="lower left")
despine(ax); light_grid(ax)
foot(fig, "数据源：论文表2 Panel A（规则—Qwen一致性选择：覆盖率0.7632、一致率0.9914、风险0.0086）")
save_fig(fig, "F01", "四种语义判定方法对比点图", "选择性预测", SCR, ["E21"], "规则—Qwen一致性选择以覆盖率换精度")

# F02 slope
fig, ax = new_fig(7.4, 5.0)
a = E21[E21["方法"] == "规则方法"].iloc[0]
b = E21[E21["方法"] == "规则—Qwen一致性选择"].iloc[0]
for i, c in enumerate(metrics):
    ax.plot([0, 1], [a[c], b[c]], "-o", color=SEQ10[i], lw=1.6, ms=6)
    ax.annotate(wrap_zh(c, 6), (0, a[c]), xytext=(-8, 0), textcoords="offset points", ha="right", fontsize=8.4, color=INK)
    ax.annotate(f"{b[c]:.4f}", (1, b[c]), xytext=(8, 0), textcoords="offset points", ha="left", fontsize=8.4, color=INK)
ax.set_xticks([0, 1]); ax.set_xticklabels(["规则方法", "规则—Qwen一致性选择"])
ax.set_xlim(-0.55, 1.35)
ax.set_title("规则 vs 一致性选择的指标斜率图")
despine(ax, keep=()); light_grid(ax)
foot(fig, "数据源：论文表2 Panel A")
save_fig(fig, "F02", "规则与一致性选择斜率图", "选择性预测", SCR, ["E21"], "风险从0.126降至0.009")

# F03 组件消融哑铃
fig, ax = new_fig(8.0, 4.6)
pairs = [("覆盖率", "覆盖率"), ("接受样本一致率", "接受样本一致率"), ("选择性风险", "选择性风险"), ("错误暴露率", "错误暴露率")]
ys = np.arange(len(E22))[::-1]
for yi, (_, r) in zip(ys, E22.iterrows()):
    if r["变体"] == "完整选择性分类器":
        continue
    pass
for yi, (_, r) in zip(ys, E22.iterrows()):
    base = E22[E22["变体"] == "完整选择性分类器"].iloc[0]
    for pi, (c, _) in enumerate(pairs):
        pass
# 每变体一行：完整(基准点) vs 去除(点)
labels = E22["变体"].tolist()
for yi, (_, r) in zip(ys, E22.iterrows()):
    ax.scatter(r["覆盖率"], yi, s=70, color=M["雾蓝"], zorder=3)
    ax.scatter(r["选择性风险"], yi, s=70, color=M["绛陶"], zorder=3)
    ax.annotate(f"覆盖{r['覆盖率']:.3f}", (r["覆盖率"], yi), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=7.6, color=M["雾蓝"])
    ax.annotate(f"风险{r['选择性风险']:.3f}", (r["选择性风险"], yi), xytext=(0, -13), textcoords="offset points", ha="center", fontsize=7.6, color=M["绛陶"])
ax.set_yticks(ys); ax.set_yticklabels([wrap_zh(x, 10) for x in labels], fontsize=9)
ax.set_xlabel("指标值（蓝=覆盖率，红=选择性风险）")
ax.set_title("选择性组件消融：各变体的覆盖-风险组合")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
foot(fig, "数据源：论文表3（n=203；去独立信号后覆盖0.3547→0.6502、风险0.0556→0.0833）")
save_fig(fig, "F03", "选择性组件消融哑铃图", "选择性预测", SCR, ["E22"], "独立信号与弃权是错误暴露控制关键")

# F04 预算曲线
curve = E01.copy()
bcol = curve.columns[0]
agcol = [c for c in curve.columns if "一致" in c or "agree" in c.lower()][0]
groupcol = [c for c in curve.columns if "总体" in c or "split" in c.lower() or "pooled" in str(curve[c].dtype).lower()]
fig, ax = new_fig(7.6, 5.0)
pooled = curve[curve[bcol].astype(str).str.contains("pooled", case=False, na=False)] if curve[bcol].dtype == object else curve
ax.plot(pooled[bcol], pooled[agcol], "-o", color=M["雾蓝"], lw=2, ms=6, zorder=3)
ax.axhline(0.8812, color=M["陶砂"], ls="--", lw=1.2)
ax.annotate("gpt-5.6-luna every-item 参考线 0.8812", (pooled[bcol].iloc[3], 0.8812), xytext=(0, 7),
            textcoords="offset points", fontsize=8.6, color=M["陶砂"])
ax.axvline(30, color=AXIS, ls=":", lw=1)
ax.annotate("操作预算 b=30%", (30, pooled[agcol].min()), xytext=(6, 2), textcoords="offset points", fontsize=8.6, color=FAINT)
ax.set_xlabel("升级预算（%）"); ax.set_ylabel("一致率（leave-B-out 主口径）")
ax.set_title("升级预算—质量曲线（同模型 gpt-oss-20b，pooled DEV+VAL）")
despine(ax); light_grid(ax)
foot(fig, "数据源：budget_v2/CURVE_LOCAL.csv（b=0: 0.2759 → b=100%: 0.8276，Δ=+0.5517）")
save_fig(fig, "F04", "升级预算质量曲线", "选择性预测", SCR, ["E01"], "质量随预算近似线性，无免费拐点")

# F05 翻转结构
bts = [5, 10, 20, 30, 40, 50, 75, 100]
w2r = [10, 20, 40, 53, 70, 85, 125, 151]
r2w = [0, 0, 0, 1, 1, 1, 3, 7]
fig, ax = new_fig(7.6, 4.6)
ax.plot(bts, w2r, "-o", color=M["橄榄"], lw=2, label="错→对（升级获益）")
ax.plot(bts, r2w, "-s", color=M["绛陶"], lw=2, label="对→错（升级损失）")
for x, yv in zip(bts, w2r):
    ax.annotate(f"{yv}", (x, yv), xytext=(0, 7), textcoords="offset points", ha="center", fontsize=7.8, color=M["橄榄"])
ax.set_xlabel("升级预算（%）"); ax.set_ylabel("翻转样本数")
ax.set_title("升级翻转结构：各预算点均净获益")
ax.legend()
despine(ax); light_grid(ax)
foot(fig, "数据源：FINAL_RISK_ROUTING_REPORT.md §2（R6 pooled，100%时 151:7）")
save_fig(fig, "F05", "预算翻转结构图", "选择性预测", SCR, ["E01"], "升级始终净换出质量")

# F06 路由对比
routes = [("R1 随机", 0.4368), ("R2 置信", 0.4253), ("R3 margin", 0.4368), ("R4 熵", 0.4368),
          ("R5 分歧", 0.4483), ("R6 风险(r_hat)", 0.4751), ("R7 oracle", 0.5402)]
fig, ax = new_fig(8.0, 4.8)
cols = [M["石板"]] * 5 + [TIER_C["STRICT"], M["驼灰"]]
xs = np.arange(len(routes))
ax.bar(xs, [v for _, v in routes], color=cols, width=0.6, zorder=3)
for x, (n, v) in zip(xs, routes):
    ax.annotate(f"{v:.4f}", (x, v), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.4, color=INK)
ax.set_xticks(xs); ax.set_xticklabels([n for n, _ in routes], fontsize=8.8)
ax.set_ylim(0.38, 0.60); ax.set_ylabel("一致率（b=30%，pooled）")
ax.set_title("七种路由策略一致率对比（R6 判语：略优）")
despine(ax); light_grid(ax)
foot(fig, "数据源：ROUTING_COMPARISON.csv（18项配对bootstrap：5显著正/13不显著/0显著负）")
save_fig(fig, "F06", "七种路由策略对比", "选择性预测", SCR, ["E02"], "风险排序稳定优于单信号启发式")

# F07 路由 bump（相对 R6 的差值排名）
bts2 = [5, 10, 20, 30, 40, 50]
r1 = [0.3218, 0.3525, 0.3908, 0.4368, 0.4828, 0.5556]
r2 = [0.3103, 0.3563, 0.3831, 0.4253, 0.4981, 0.5670]
r3 = [0.3103, 0.3563, 0.3793, 0.4368, 0.4943, 0.5632]
r5 = [0.3142, 0.3448, 0.4215, 0.4483, 0.4981, 0.5556]
r6 = [0.3142, 0.3525, 0.4291, 0.4751, 0.5402, 0.5977]
series = [("R1随机", r1), ("R2置信", r2), ("R3margin", r3), ("R5分歧", r5), ("R6风险", r6)]
fig, ax = new_fig(8.4, 5.0)
for i, (nm, vs) in enumerate(series):
    rk = [sorted([s_[k] for _, s_ in series], reverse=True).index(v) + 1 for k, v in enumerate(vs)]
    ax.plot([str(b) + "%" for b in bts2], rk, "-o", color=SEQ10[i], lw=1.8, ms=6, label=nm)
ax.invert_yaxis(); ax.set_yticks([1, 2, 3, 4, 5]); ax.set_ylabel("一致率排名")
ax.set_title("各路由策略跨预算的排名变化")
ax.legend(fontsize=8.4, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.12))
despine(ax, keep=("bottom",)); light_grid(ax, axis="y")
foot(fig, "数据源：ROUTING_COMPARISON.csv（R4 略去以保持可读）")
save_fig(fig, "F07", "路由策略跨预算排名图", "选择性预测", SCR, ["E02"], "R6 在中段预算稳定第一")

# F08 R6 vs R2/R3 森林图
items = [("b=20% vs R2", 0.0460, 0.0115, 0.0805), ("b=20% vs R3", 0.0498, 0.0115, 0.0881),
         ("b=30% vs R2", 0.0498, 0.0077, 0.0920), ("b=30% vs R3", 0.0383, 0.0000, 0.0805),
         ("b=40% vs R2", 0.0421, 0.0038, 0.0805), ("b=40% vs R3", 0.0460, 0.0153, 0.0805),
         ("b=40% vs R4", 0.0460, 0.0115, 0.0805),
         ("b=5% vs R1", -0.0077, -0.0421, 0.0268), ("b=30% vs R1", 0.0383, -0.0268, 0.0996)]
fig, ax = new_fig(8.0, 5.4)
ys = np.arange(len(items))[::-1]
for yi, (n, d, lo, hi) in zip(ys, items):
    sig = lo > 0
    c = M["雾蓝"] if sig else M["驼灰"]
    ax.plot([lo, hi], [yi, yi], color=c, lw=2.2, zorder=3)
    ax.scatter([d], [yi], s=56, color=c, zorder=4)
    ax.annotate(f"{d:+.3f}", (d, yi), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=7.6, color=c)
ax.axvline(0, color=AXIS, lw=1, ls="--")
ax.set_yticks(ys); ax.set_yticklabels([n for n, *_ in items], fontsize=8.6)
ax.set_xlabel("Δ一致率（R6 − 对手，95% CI，paired bootstrap 2000 次）")
ax.set_title("R6 路由优势的置信区间森林图（深色=显著为正）")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
foot(fig, "数据源：ROUTING_BOOTSTRAP.json（5项CI全正/13不显著/0显著负）")
save_fig(fig, "F08", "路由优势森林图", "选择性预测", SCR, ["E03"], "显著优势集中在中段预算与置信/margin对手")

# F09 三split分组点
fig, ax = new_fig(8.2, 4.8)
mets = ["覆盖率", "选择准确率", "选择性风险", "升级段一致率", "接受段一致率"]
dev = [0.9372, 0.5103, 0.4897, 0.7778, 0.3817]
val = [0.9259, 0.4600, 0.5400, 0.7333, 0.3429]
tes = [0.9792, 0.6170, 0.3830, 0.8000, 0.5313]
xs = np.arange(len(mets))
for i, (nm, vs, c) in enumerate([("DEV", dev, SEQ10[0]), ("VAL", val, SEQ10[1]), ("TEST", tes, SEQ10[3])]):
    ax.scatter(xs + (i - 1) * 0.12, vs, s=76, color=c, label=nm, zorder=3)
    for x, v in zip(xs + (i - 1) * 0.12, vs):
        ax.annotate(f"{v:.2f}", (x, v), xytext=(0, 7), textcoords="offset points", ha="center", fontsize=6.8, color=FAINT)
ax.set_xticks(xs); ax.set_xticklabels([wrap_zh(m, 6) for m in mets], fontsize=9)
ax.set_ylabel("指标值")
ax.set_title("风险路由三列评价：DEV / VAL / TEST（b=30%）")
ax.legend()
despine(ax); light_grid(ax)
foot(fig, "数据源：frozen_test/SUMMARY.json（TEST n=62，方法冻结后唯一一次评价）")
save_fig(fig, "F09", "三列评价分组点图", "选择性预测", SCR, ["E04"], "TEST与DEV/VAL同向且不劣")

# F10 12变体点图
fig, ax = new_fig(8.2, 5.4)
xs = E05["覆盖率"]
ys = E05["选择准确率"]
sz = 30 + 500 * E05["选择性风险"]
cols = [TIER_C["STRICT"] if s == "S0生产保真(冻结)" else M["石板"] for s in E05["变体"]]
ax.scatter(xs, ys, s=sz, color=cols, alpha=0.85, zorder=3, edgecolors="white")
for x, y, n in zip(xs, ys, E05["变体"]):
    if n in ("S0生产保真(冻结)", "S8仅盲LLM", "S7仅分类器", "S1去类别门禁"):
        ax.annotate(n, (x, y), xytext=(7, 6), textcoords="offset points", fontsize=7.8, color=INK)
ax.set_xlabel("覆盖率"); ax.set_ylabel("选择准确率")
ax.set_title("十二变体消融：覆盖—准确—风险气泡图（点大小=选择性风险）")
despine(ax); light_grid(ax)
foot(fig, "数据源：FINAL_TEST_REPORT.md §2（TEST n=62，参考=strong，仅作冻结确认）")
save_fig(fig, "F10", "十二变体消融气泡图", "选择性预测", SCR, ["E05"], "生产配置以极低覆盖保守发布")

# F11 TEST 路由决策流
fig, ax = new_fig(10.0, 4.4)
ax.set_xlim(0, 10); ax.set_ylim(0, 4.4); ax.axis("off")
fbox(ax, 0.4, 1.7, 1.7, 1.1, "TEST 样本\nn=62", fc="#EDF1F4", ec=M["雾蓝"], fs=11, weight="bold")
fbox(ax, 3.0, 3.0, 2.3, 1.0, "AUTO_ACCEPT 自动接受\n41 条", fc="#EFF3EE", ec=M["橄榄"])
fbox(ax, 3.0, 1.75, 2.3, 1.0, "ESCALATE 升级裁决\n19 条（全部调用成功）", fc="#F3F0EA", ec=M["陶砂"])
fbox(ax, 3.0, 0.5, 2.3, 1.0, "ABSTAIN 显式弃权\n2 条", fc="#F3F1F1", ec=M["绛陶"])
farrow(ax, 2.2, 2.4, 2.95, 3.4); farrow(ax, 2.2, 2.25, 2.95, 2.25); farrow(ax, 2.2, 2.1, 2.95, 1.1)
fbox(ax, 6.2, 3.0, 3.2, 1.0, "接受段一致率 0.531\n（15 条有参考：8/15）", fc="#FFFFFF", ec=GRID)
fbox(ax, 6.2, 1.75, 3.2, 1.0, "升级段一致率 0.800（12/15）\n错→对 9 ： 对→错 1", fc="#FFFFFF", ec=M["陶砂"])
farrow(ax, 5.35, 3.5, 6.15, 3.5); farrow(ax, 5.35, 2.25, 6.15, 2.25)
ax.text(5.0, 4.15, "冻结 TEST 单次评价：升级段一致率显著高于接受段，路由机制方向复现", ha="center", fontsize=9.5, color=INK)
foot(fig, "数据源：FINAL_TEST_REPORT.md §3（升级模型 gpt-oss-20b，温度0；留痕 ESCALATION_CALLS_TEST.jsonl）")
save_fig(fig, "F11", "TEST路由决策流图", "选择性预测", SCR, ["E04"], "9:1 净翻转验证高风险升级设计")

# F12 边际增益
bts3 = [0, 5, 10, 20, 30, 40, 50, 75, 100]
ag = [0.2759, 0.3142, 0.3525, 0.4291, 0.4751, 0.5402, 0.5977, 0.7433, 0.8276]
gains = []
labels = []
for i in range(1, len(bts3)):
    span = bts3[i] - bts3[i - 1]
    gains.append((ag[i] - ag[i - 1]) / span * 100)
    labels.append(f"{bts3[i-1]}-{bts3[i]}%")
fig, ax = new_fig(7.8, 4.4)
ax.bar(labels, gains, color=M["雾蓝"], width=0.6, zorder=3)
for i, v in enumerate(gains):
    ax.annotate(f"{v:.1f}", (i, v), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8, color=INK)
ax.set_ylabel("每 10% 预算的一致率增益（pp）")
ax.set_title("升级预算的边际增益：全程近似线性、无免费拐点")
despine(ax); light_grid(ax)
foot(fig, "数据源：由 CURVE_LOCAL pooled 一致率差分计算")
save_fig(fig, "F12", "预算边际增益图", "选择性预测", SCR, ["E01"], "6.4–7.7 pp/10% 全程稳定")

# F13 本地终点 vs 参考线瀑布
fig, ax = new_fig(7.6, 4.4)
steps = [("本地 every-item\n终点", 0.8276, None), ("升级模型\n能力差距", 0.0536, "delta"), ("更强模型\n参考线", 0.8812, "total")]
cum = 0
for i, (n, v, kind) in enumerate(steps):
    if kind == "delta":
        ax.bar(i, v, bottom=cum, color=M["陶砂"], width=0.55, zorder=3)
        ax.annotate(f"+{v:.4f}", (i, cum + v), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=9, color=INK)
        cum += v
    else:
        ax.bar(i, v, color=TIER_C["STRICT"] if i == 0 else M["驼灰"], width=0.55, zorder=3)
        ax.annotate(f"{v:.4f}", (i, v), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=9, color=INK)
ax.plot([0.28, 0.72], [0.8276, 0.8276], color=AXIS, ls=":", lw=1)
ax.set_xticks(range(3)); ax.set_xticklabels([s[0] for s in steps], fontsize=9)
ax.set_ylim(0.75, 0.95); ax.set_ylabel("一致率（leave-B-out）")
ax.set_title("本地升级终点与参考线差距分解（5.4pp）")
despine(ax); light_grid(ax)
foot(fig, "数据源：FINAL_RISK_ROUTING_REPORT.md §0（差距主要归因升级模型能力差异）")
save_fig(fig, "F13", "本地终点与参考线瀑布图", "选择性预测", SCR, ["E01"], "曲线全程同模型，差距来自模型能力")

# F14 接受段/升级段哑铃
fig, ax = new_fig(7.4, 4.2)
splits = ["DEV", "VAL", "TEST"]
acc = [0.3817, 0.3429, 0.5313]
esc = [0.7778, 0.7333, 0.8000]
for i, s in enumerate(splits):
    y = len(splits) - i
    ax.plot([acc[i], esc[i]], [y, y], color=GRID, lw=3, zorder=2)
    ax.scatter(acc[i], y, s=72, color=M["驼灰"], zorder=3)
    ax.scatter(esc[i], y, s=72, color=M["陶砂"], zorder=3)
    ax.annotate(f"{acc[i]:.3f}", (acc[i], y), xytext=(0, -14), textcoords="offset points", ha="center", fontsize=8, color=M["驼灰"])
    ax.annotate(f"{esc[i]:.3f}", (esc[i], y), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=8, color=M["陶砂"])
ax.set_yticks([1, 2, 3]); ax.set_yticklabels(splits[::-1])
ax.set_xlabel("一致率（有参考样本）")
ax.set_title("升级段与接受段一致率哑铃图")
from matplotlib.lines import Line2D
ax.legend(handles=[Line2D([], [], marker="o", ls="", color=M["驼灰"], label="接受段"),
                   Line2D([], [], marker="o", ls="", color=M["陶砂"], label="升级段")], loc="lower right")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
foot(fig, "数据源：frozen_test/SUMMARY.json 三列对比表")
save_fig(fig, "F14", "接受升级段哑铃图", "选择性预测", SCR, ["E04"], "升级段一致率高出 25–27pp")

# F15 广义风险曲线
fig, ax = new_fig(7.2, 4.4)
risk = [1 - a for a in ag]
ax.plot(bts3, risk, "-o", color=M["绛陶"], lw=2, ms=6)
for x, yv in zip(bts3, risk):
    ax.annotate(f"{yv:.3f}", (x, yv), xytext=(0, -13), textcoords="offset points", ha="center", fontsize=7.6, color=FAINT)
ax.set_xlabel("升级预算（%）"); ax.set_ylabel("广义风险（1 − 一致率）")
ax.set_title("广义风险随升级预算单调下降")
despine(ax); light_grid(ax)
foot(fig, "数据源：CURVE_LOCAL pooled（风险 0.724 → 0.172）")
save_fig(fig, "F15", "广义风险预算曲线", "选择性预测", SCR, ["E01"], "预算增加 55pp 风险下降")

# F16 自动接受门概念图
fig, ax = new_fig(10.4, 5.6)
ax.set_xlim(0, 10.4); ax.set_ylim(0, 5.6); ax.axis("off")
fbox(ax, 0.3, 2.3, 1.6, 1.2, "候选知识\nx = (s,p,o,t,k,S)", fc="#EDF1F4", ec=M["雾蓝"], fs=9)
fbox(ax, 2.6, 4.3, 2.4, 0.9, "置信度 L(x) ≥ θ(c) ?", fc="#FFFFFF", ec=M["青灰"], fs=9)
fbox(ax, 2.6, 3.1, 2.4, 0.9, "概率间隔 Δ(x) ≥ δ(c) ?", fc="#FFFFFF", ec=M["青灰"], fs=9)
fbox(ax, 2.6, 1.9, 2.4, 0.9, "独立信号 C(x) ≥ 1 ?", fc="#FFFFFF", ec=M["青灰"], fs=9)
fbox(ax, 2.6, 0.7, 2.4, 0.9, "强反证 H(x) = 0 ?", fc="#FFFFFF", ec=M["青灰"], fs=9)
fbox(ax, 6.0, 2.9, 2.0, 1.2, "g(x) = 1\n自动接受资格", fc="#EFF3EE", ec=M["橄榄"], fs=10, weight="bold")
fbox(ax, 6.0, 0.7, 2.0, 1.2, "g(x) = 0\n不具自动资格", fc="#F3F1F1", ec=M["绛陶"], fs=10, weight="bold")
fbox(ax, 8.4, 2.9, 1.7, 1.2, "进入结构准入\n（第二道门）", fc="#F0F2F4", ec=M["雾蓝"], fs=8.6)
fbox(ax, 8.4, 1.2, 1.7, 1.2, "升级裁决（LLM）\n或保持未决", fc="#F3F0EA", ec=M["陶砂"], fs=8.6)
for yv in (4.75, 3.55, 2.35, 1.15):
    farrow(ax, 1.95, 2.9, 2.55, yv)
for yv in (4.75, 3.55, 2.35, 1.15):
    farrow(ax, 5.05, yv, 5.95, 3.5 if yv > 2.5 else 1.3)
farrow(ax, 8.05, 3.5, 8.35, 3.5); farrow(ax, 8.05, 1.3, 8.35, 1.6)
ax.text(5.2, 0.15, "θ(c)：验证支持数≥50、精确率≥0.98、Wilson 下限≥0.95 的最低档；δ(c)=0；独立信号=严格词法/Schema 投票",
        ha="left", fontsize=7.6, color=FAINT)
ax.set_title("自动接受门 g(x)：四条件合取的选择性预测门禁（论文 §3.2）")
foot(fig, "数据源：论文 §3.2 方法描述（参数确定遵循训练-验证-核心评价分离协议）")
save_fig(fig, "F16", "自动接受门概念图", "方法概念", SCR, ["论文§3.2"], "四条件合取形成显式弃权边界")

# ================= G 时空作用域 =================
# G01 分流 Sankey
fig, ax = new_fig(10.8, 7.0)
ax.set_xlim(0, 10.8); ax.set_ylim(0, 7.0); ax.axis("off")
nodes = [
    ("候选总体\n208", 0.4, 2.7, 1.6, 1.6, M["石板"]),
    ("三票参考\n187", 2.9, 3.2, 1.6, 1.2, M["雾蓝"]),
    ("不入参考\n21", 2.9, 0.9, 1.6, 0.9, M["驼灰"]),
    ("learn\n125", 5.3, 4.9, 1.5, 0.9, M["暮蓝"]),
    ("held-out\n83", 5.3, 3.3, 1.5, 0.9, M["青灰"]),
    ("可判定\n62", 7.4, 3.4, 1.4, 0.8, M["雾蓝"]),
    ("明确决策\n28", 7.4, 1.9, 1.4, 0.8, M["橄榄"]),
    ("一致 25\n错误 3", 9.4, 2.3, 1.2, 1.0, TIER_C["STRICT"]),
    ("弃权\n34", 9.4, 1.0, 1.2, 0.8, M["绛陶"]),
]
for t, x, y, w, h, c in nodes:
    fbox(ax, x, y, w, h, t, fc="#FFFFFF", ec=c, fs=9.5, weight="bold", tc=c)
farrow(ax, 2.05, 3.5, 2.85, 3.8); farrow(ax, 2.05, 3.3, 2.85, 1.35)
farrow(ax, 4.55, 3.9, 5.25, 5.2); farrow(ax, 4.55, 3.7, 5.25, 3.75)
farrow(ax, 6.85, 3.75, 7.35, 3.8); farrow(ax, 6.85, 3.6, 7.35, 2.3)
farrow(ax, 8.85, 2.5, 9.35, 2.8); farrow(ax, 8.85, 2.3, 9.35, 1.4)
ax.text(5.4, 6.5, "McNemar 精确检验 p = 2.74e-05（old错new对 25 : old对new错 3）", ha="center", fontsize=9.5, color=INK)
ax.text(5.4, 6.0, "held-out 83 条中：可判定 62 → 明确决策 28（一致 25，89.3%）· 弃权 34（54.8%）", ha="center", fontsize=9, color=FAINT)
ax.set_title("时空作用域选择性闭包分流图（208 条候选的完整路径）")
foot(fig, "数据源：FINAL_SCOPE_REPORT.md（三票 IMCR 共识，book-grouped 60/40 切分，seed=20260908）")
save_fig(fig, "G01", "作用域闭包分流图", "时空作用域", SCR, ["E06"], "选择性闭包弃权34条保守决策")

# G02 变换类型
tt = pd.DataFrame([("event_location→context_location", 90), ("unknown→event_occurrence", 60),
                   ("other", 37), ("mixed", 16), ("event_location→relation_location", 5)],
                  columns=["类型", "n"])[::-1]
fig, ax = new_fig(8.0, 4.4)
ax.barh(range(len(tt)), tt["n"], color=SEQ10[:5][::-1], height=0.62, zorder=3)
ax.set_yticks(range(len(tt))); ax.set_yticklabels([wrap_zh(x.replace("→", " → "), 16) for x in tt["类型"]], fontsize=8.6)
for i, v in enumerate(tt["n"]):
    ax.annotate(f"{v}", (v, i), xytext=(5, 0), textcoords="offset points", va="center", fontsize=8.6, color=INK)
ax.set_xlabel("任务条数")
ax.set_title("时空作用域调整的变换类型构成（208 条）")
despine(ax); light_grid(ax, axis="x")
foot(fig, "数据源：FINAL_SCOPE_REPORT.md §2（SCOPE_BY_TYPE_ERRORS.csv）")
save_fig(fig, "G02", "作用域变换类型构成", "时空作用域", SCR, ["E06"], "事件地点误标为语境地点占四成")

# G03 切分结构
fig, ax = new_fig(8.6, 3.8)
ax.set_xlim(0, 8.6); ax.set_ylim(0, 3.8); ax.axis("off")
fbox(ax, 0.3, 1.3, 2.0, 1.2, "201 个\nbook-grouped 分量", fc="#EDF1F4", ec=M["雾蓝"], fs=10)
fbox(ax, 3.2, 2.2, 2.3, 1.0, "learn 125 条（60.1%）", fc="#F0F2F4", ec=M["暮蓝"], fs=10)
fbox(ax, 3.2, 0.7, 2.3, 1.0, "held-out 83 条（39.9%）", fc="#F3F0EA", ec=M["陶砂"], fs=10)
farrow(ax, 2.35, 2.0, 3.15, 2.7); farrow(ax, 2.35, 1.7, 3.15, 1.2)
ax.text(6.0, 2.6, "同一本书的任务绝不跨侧", fontsize=9.2, color=INK)
ax.text(6.0, 2.0, "（并查集分量原子分配）", fontsize=9.2, color=INK)
ax.text(6.0, 1.2, "排序键 sha256(seed:closure3:cid)\nseed = 20260908", fontsize=8.4, color=FAINT)
ax.set_title("学习/留出切分结构：防泄漏设计")
foot(fig, "数据源：FINAL_SCOPE_REPORT.md §3（learn 122 / heldout 79 分量）")
save_fig(fig, "G03", "作用域切分结构图", "时空作用域", SCR, ["E06"], "零回流切分保证评价独立")

# G04 类型×标签矩阵
gm = pd.DataFrame([
    ["event_location→context_location", 55, 35, 6, 3, 25],
    ["event_location→relation_location", 5, 0, 0, 0, 0],
    ["mixed", 9, 7, 0, 0, 0],
    ["other", 24, 13, 6, 6, 0],
    ["unknown→event_occurrence", 32, 28, 17, 14, 0],
], columns=["类型", "learn", "heldout", "A胜learn", "A胜held", "new对held"])
fig, ax = new_fig(9.2, 4.8)
disp = gm[["类型", "learn", "heldout", "A胜learn", "A胜held", "new对held"]].set_index("类型")
cmapb = mpl.colors.LinearSegmentedColormap.from_list("mb", BLUE_SEQ)
im = ax.imshow(disp.values, cmap=cmapb, aspect="auto")
ax.set_xticks(range(len(disp.columns)))
ax.set_xticklabels(["learn", "held-out", "learn中AFTER优", "held中AFTER优", "held中新规则对"], fontsize=8.2)
ax.set_yticks(range(len(disp))); ax.set_yticklabels([wrap_zh(x, 18) for x in disp.index], fontsize=7.8)
for i in range(len(disp)):
    for j in range(len(disp.columns)):
        ax.text(j, i, disp.values[i, j], ha="center", va="center", fontsize=8,
                color="#FFFFFF" if disp.values[i, j] > 40 else INK)
ax.set_title("变换类型 × 切分 × 三票标签构成矩阵")
despine(ax, keep=())
foot(fig, "数据源：FINAL_SCOPE_REPORT.md §3.1/§5.1（AFTER_BETTER = 改写更优）")
save_fig(fig, "G04", "变换类型标签矩阵", "时空作用域", SCR, ["E06"], "仅 context_location 类有可学习规则")

# G05 新旧对比哑铃
fig, ax = new_fig(8.0, 3.6)
items = [("旧闭包（全 REWRITE）", 37.1), ("新闭包（保守口径：弃权记错）", 40.3), ("新闭包（actionable）", 89.3)]
ys = np.arange(len(items))[::-1]
ax.hlines(ys, 0, [v for _, v in items], color=GRID, lw=3)
ax.scatter([v for _, v in items], ys, s=90, color=[M["驼灰"], M["暮蓝"], TIER_C["STRICT"]], zorder=3)
for y, (_, v) in zip(ys, items):
    ax.annotate(f"{v:.1f}%", (v, y), xytext=(10, 0), textcoords="offset points", va="center", fontsize=10, color=INK)
ax.set_yticks(ys); ax.set_yticklabels([n for n, _ in items], fontsize=9.5)
ax.set_xlim(0, 100); ax.set_xlabel("held-out 语义一致率（%，decided 分母 62 条）")
ax.set_title("固定式改写 vs 规则式选择性闭包")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
foot(fig, "数据源：FINAL_SCOPE_REPORT.md §5（三票口径；旧两票 96.6% 已作废）")
save_fig(fig, "G05", "新旧闭包一致率对比图", "时空作用域", SCR, ["E06"], "actionable 口径一致率 89.3%")

# G06 McNemar 四象限
fig, ax = new_fig(7.6, 5.0)
ax.add_patch(mpl.patches.Rectangle((0, 0), 1, 1, fill=False, lw=1.4, edgecolor=AXIS))
ax.scatter([0.3], [0.3], s=0)
ax.annotate("双对 0", (0.25, 0.75), ha="center", fontsize=11, color=FAINT)
ax.annotate("old对\nnew错 3", (0.75, 0.75), ha="center", fontsize=12, color=M["绛陶"])
ax.annotate("old错\nnew对 25", (0.25, 0.25), ha="center", fontsize=14, color=TIER_C["STRICT"], weight="bold")
ax.annotate("双错 0", (0.75, 0.25), ha="center", fontsize=11, color=FAINT)
ax.set_xlim(0, 1); ax.set_ylim(0, 1)
ax.set_xticks([0.25, 0.75]); ax.set_xticklabels(["新闭包：对", "新闭包：错"])
ax.set_yticks([0.25, 0.75]); ax.set_yticklabels(["旧闭包：错", "旧闭包：对"])
ax.set_title("McNemar 配对翻转（n=28 actionable，精确 p=2.74e-05）")
foot(fig, "数据源：FINAL_SCOPE_REPORT.md §5（25:3 净翻转）")
save_fig(fig, "G06", "McNemar配对翻转图", "时空作用域", SCR, ["E06"], "选择性闭包显著优于固定改写")

# G07 角色调整流向（208条）
t20 = pd.read_csv(os.path.join(MID, "T20_作用域调整汇总.csv"))
flow = t20.groupby(["原空间角色", "新空间角色"])["条数"].sum().reset_index().sort_values("条数", ascending=False).head(6)
fig, ax = new_fig(9.2, 5.0)
lt = collections.OrderedDict(); rt = collections.OrderedDict()
for _, r in flow.iterrows():
    lt[str(r["原空间角色"])] = lt.get(str(r["原空间角色"]), 0) + r["条数"]
    rt[str(r["新空间角色"])] = rt.get(str(r["新空间角色"]), 0) + r["条数"]
tot = sum(lt.values())
fig = plt.figure(figsize=(9.4, 4.8))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 9.4); ax.set_ylim(0, 4.8); ax.axis("off")
Lp = {}; y = 0.5
for k, v in sorted(lt.items(), key=lambda kv: -kv[1]):
    h = v / tot * 3.2; Lp[k] = (y, h); y += h + 0.1
Rp = {}; y = 0.5
for k, v in sorted(rt.items(), key=lambda kv: -kv[1]):
    h = v / tot * 3.2; Rp[k] = (y, h); y += h + 0.1
colk = {k: SEQ10[i % 10] for i, k in enumerate(lt)}
for k, (yy, h) in Lp.items():
    ax.add_patch(mpl.patches.FancyBboxPatch((0.5, yy), 1.5, h, boxstyle="round,pad=0.02", color=colk[k], alpha=0.9))
    ax.text(0.4, yy + h / 2, f"{wrap_zh(k, 10)} {lt[k]}", ha="right", va="center", fontsize=8.6, color=INK)
for k, (yy, h) in Rp.items():
    ax.add_patch(mpl.patches.FancyBboxPatch((7.4, yy), 1.5, h, boxstyle="round,pad=0.02", color=M["橄榄"], alpha=0.9))
    ax.text(9.0, yy + h / 2, f"{wrap_zh(k, 10)} {rt[k]}", ha="left", va="center", fontsize=8.6, color=INK)
for _, r in flow.iterrows():
    src = str(r["原空间角色"]); dst = str(r["新空间角色"])
    sy, sh = Lp[src]; dy, dh = Rp[dst]
    fs = r["条数"] / lt[src]; fd = r["条数"] / rt[dst]
    sy2 = sy + sh * fs; dy2 = dy + dh * fd
    xs = np.linspace(2.0, 7.4, 100)
    yy = 0.5 * (sy2 + dy2) - 0.5 * (sy2 - dy2) * np.cos(np.pi * (xs - 2.0) / 5.4)
    ax.fill_between(xs, yy, yy + min(sh * fs, dh * fd), color=colk[src], alpha=0.3)
ax.set_title("208 条时空作用域调整的空间角色流向（前6 流量）", fontsize=12)
foot(fig, "数据源：research_scope_adjustments（最终库）")
save_fig(fig, "G07", "作用域角色流向图", "时空作用域", SCR, ["T20"], "event_location→context_location 为主流")

# G08 取值-角色-归属概念图
fig, ax = new_fig(10.4, 5.0)
ax.set_xlim(0, 10.4); ax.set_ylim(0, 5.0); ax.axis("off")
fbox(ax, 0.35, 2.9, 2.6, 1.5, "取值 value\n例：1935-01-15 / 遵义", fc="#EDF1F4", ec=M["雾蓝"], fs=10)
fbox(ax, 3.6, 2.9, 2.9, 1.5, "语义角色 role\nevent_time / life_time /\nwork_time / source_time …", fc="#F0F2F4", ec=M["青灰"], fs=9)
fbox(ax, 7.1, 2.9, 2.9, 1.5, "归属对象 owner\n遵义会议（事件）/\n某人物 / 某文献", fc="#F3F0EA", ec=M["陶砂"], fs=9.5)
farrow(ax, 3.0, 3.65, 3.55, 3.65); farrow(ax, 6.55, 3.65, 7.05, 3.65)
ax.text(5.2, 4.75, "时空统一表示：ST = (取值, 语义角色, 归属对象)", ha="center", fontsize=11.5, weight="bold", color=INK)
fbox(ax, 1.4, 0.9, 3.4, 1.2, "强角色：归属对象必须存在\n且类型 ∈ Ωr（类型合法）", fc="#EFF3EE", ec=M["橄榄"], fs=9.4)
fbox(ax, 5.6, 0.9, 3.4, 1.2, "归属对象待确认 → 保留原文/候选角色\n→ 进入上下文层等待复核", fc="#F3F1F1", ec=M["绛陶"], fs=9.4)
farrow(ax, 4.85, 3.4, 3.6, 2.15); farrow(ax, 5.55, 3.4, 6.8, 2.15)
ax.text(5.2, 0.35, "结构准入后重校验：208 项作用域调整在实体规范投影后自动重执行", ha="center", fontsize=8.8, color=FAINT)
ax.set_title("“取值—语义角色—归属对象”时空表示机制（论文 §3.3）")
foot(fig, "数据源：论文 §3.3 与 research_scope_adjustments")
save_fig(fig, "G08", "时空三元表示概念图", "方法概念", SCR, ["论文§3.3"], "时空语义按角色区分归属")

# ================= H 级联准入 =================
def sankey2(ax, stages, W=11.0, H=7.4):
    """stages: [(标题, [(名称, 值, 色), ...])] 每列堆叠流。"""
    ncol = len(stages)
    colw = W / ncol
    colx = [i * colw + colw * 0.16 for i in range(ncol)]
    for ci, (title, items) in enumerate(stages):
        tot = sum(v for _, v, _ in items)
        y = 0.35; Hx = H - 1.0
        pos = []
        for nm, v, c in items:
            h = v / tot * Hx
            pos.append((nm, y, h, c, v))
            y += h + 0.07
        if ci == 0:
            stages[0] = (title, items, pos, colx[ci], colw * 0.5)
        else:
            stages[ci] = (title, items, pos, colx[ci], colw * 0.5)
    for ci, st in enumerate(stages):
        title, items, pos, x, w = st
        for nm, yy, h, c, v in pos:
            ax.add_patch(mpl.patches.FancyBboxPatch((x, yy), w, h, boxstyle="round,pad=0.015",
                                                    facecolor=c, edgecolor="white", lw=0.8, alpha=0.92))
            if h > 0.16:
                ax.text(x + w / 2, yy + h / 2, f"{nm}\n{v:,}", ha="center", va="center", fontsize=7.6,
                        color="#FFFFFF", weight="bold")
        ax.text(x + w / 2, H - 0.12, title, ha="center", fontsize=9.5, color=INK, weight="bold")

fig, ax = new_fig(11.6, 7.6)
ax.set_xlim(0, 11.6); ax.set_ylim(0, 7.6); ax.axis("off")
stages = [
    ("全库入口", [("全库断言", 424150, M["石板"])]),
    ("前置分层（结构准入）", [("严格候选", 112158, TIER_C["STRICT"]),
                       ("上下文（谓词未归一 264,635 + 域违例 3,412）", 268047, TIER_C["CONTEXTUAL"]),
                       ("未决（scope 27,492 + 端点 16,393 + 人工 60）", 43945, TIER_C["UNRESOLVED"])]),
    ("证据语义门", [("可定位证据", 110052, M["雾蓝"]), ("无证据 recovery_D", 2106, M["驼灰"])]),
    ("门内再分层", [("STRICT", 31067, TIER_C["STRICT"]), ("CONTEXTUAL", 31282, TIER_C["CONTEXTUAL"]),
              ("UNRESOLVED", 49809, TIER_C["UNRESOLVED"])]),
    ("全库最终三层", [("STRICT 31,067", 31067, TIER_C["STRICT"]),
                ("CONTEXTUAL = 268,047+31,282", 299329, TIER_C["CONTEXTUAL"]),
                ("UNRESOLVED = 43,945+49,809", 93754, TIER_C["UNRESOLVED"])]),
]
sankey2(ax, stages, W=11.6, H=7.6)
ax.set_title("全库级联准入总流：424,150 条断言的完整分层路径（Sankey）", fontsize=12.5)
foot(fig, "数据源：AUTHORITATIVE_RESULTS.md 定版数字（replay 六项零检查 PASS，unexplained=0）")
save_fig(fig, "H01", "全库级联准入总流桑基图", "级联准入", SCR, ["T09", "T10"], "全库三层全部有来源有路径")

# H02 漏斗
fig, ax = new_fig(8.6, 5.4)
stagesf = [("全库断言", 424150), ("严格候选（证据门宇宙）", 112158), ("证据可定位", 110052), ("最终严格层", 31067)]
ymax = 424150
for i, (nm, v) in enumerate(stagesf):
    w = v / ymax
    y = 3 - i
    ax.add_patch(mpl.patches.Polygon([[50 - w * 46, y - 0.36], [50 + w * 46, y - 0.36], [50 + w * 46, y + 0.36], [50 - w * 46, y + 0.36]],
                                     closed=True, facecolor=[M["石板"], M["雾蓝"], M["暮蓝"], TIER_C["STRICT"]][i], alpha=0.92))
    ax.text(50, y, f"{nm}  {v:,}（{v/424150*100:.1f}%）", ha="center", va="center", fontsize=9.6,
            color="#FFFFFF", weight="bold")
ax.set_xlim(0, 100); ax.set_ylim(-0.6, 3.7); ax.axis("off")
ax.set_title("级联准入漏斗（居中对称编码）")
foot(fig, "数据源：T09_级联准入漏斗（AUTHORITATIVE_RESULTS 定版）")
save_fig(fig, "H02", "级联准入漏斗图", "级联准入", SCR, ["T09"], "逐级收窄至严格层 7.3%")

# H03 三层来源瀑布
fig, ax = new_fig(9.6, 5.2)
steps = [("STRICT", 31067, "base", TIER_C["STRICT"]),
         ("+前置上下文", 268047, "add", TIER_C["CONTEXTUAL"]),
         ("+核验降级", 31282, "add", TIER_C["CONTEXTUAL"]),
         ("CONTEXTUAL 合计", 299329, "total", M["青灰"]),
         ("+前置未决", 43945, "add", TIER_C["UNRESOLVED"]),
         ("+核验未决", 49809, "add", TIER_C["UNRESOLVED"]),
         ("UNRESOLVED 合计", 93754, "total", M["陶砂"])]
cum = 0
for i, (nm, v, kind, c) in enumerate(steps):
    if kind == "add":
        ax.bar(i, v, bottom=cum, color=c, width=0.6, alpha=0.9, zorder=3)
        ax.annotate(f"+{v:,}", (i, cum + v), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8, color=INK)
        cum += v
    else:
        ax.bar(i, v, color=c, width=0.6, zorder=3)
        ax.annotate(f"{v:,}", (i, v), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.4, color=INK, weight="bold")
        cum = v if kind == "total" and i == 3 else cum
ax.set_xticks(range(len(steps)))
ax.set_xticklabels([wrap_zh(s[0], 9) for s in steps], fontsize=8.2)
ax.set_yscale("log"); ax.set_ylabel("断言数（log）")
ax.set_title("全库三层知识状态来源分解瀑布（log 轴）")
despine(ax); light_grid(ax)
foot(fig, "数据源：AUTHORITATIVE_RESULTS.md §二之四（11条归因路径全部落账）")
save_fig(fig, "H03", "三层来源分解瀑布图", "级联准入", SCR, ["T10"], "299,329 与 93,754 的双重来源")

# H04 门外阻断树图
fig, ax = new_fig(9.8, 5.4)
blocks = [("谓词未完成规范化", 264635), ("作用域冲突 model_review", 27492), ("端点实体类型未决", 16393),
          ("关系域约束违反", 3412), ("人工遗留", 60)]
cmapb = mpl.colors.LinearSegmentedColormap.from_list("mb", [SAND_SEQ[2], SAND_SEQ[5], SAND_SEQ[7]])
squarify.plot(sizes=[b[1] for b in blocks],
              label=[f"{b[0]}\n{b[1]:,}\n({b[1]/311992*100:.1f}%)" for b in blocks],
              color=[SAND_SEQ[6], SAND_SEQ[4], SAND_SEQ[3], SAND_SEQ[2], SAND_SEQ[1]], ax=ax, pad=True,
              text_kwargs={"fontsize": 9, "color": "#FFFFFF" if True else INK})
ax.axis("off")
ax.set_title("门外宇宙 311,992 条的阻断归因树图")
foot(fig, "数据源：FULL_UNIVERSE_ADMISSION_SUMMARY.json（284 条 CASE 规则重放，0 mismatch）")
save_fig(fig, "H04", "门外阻断归因树图", "级联准入", SCR, ["T10"], "谓词未归一占门外 84.8%")

# H05 证据门宇宙构成
fig, ax = new_fig(8.6, 4.2)
universes = [("证据门宇宙 112,158", [("STRICT", 31067), ("CONTEXTUAL", 31282), ("UNRESOLVED", 49809)]),
             ("门外宇宙 311,992", [("前置上下文", 268047), ("前置未决", 43945)])]
y0 = 1
for un, parts in universes:
    left = 0; tot = sum(v for _, v in parts)
    for nm, v in parts:
        ax.barh(y0, v / tot * 100, left=left, color=TIER_C.get(nm.split("（")[0], M["驼灰"]) if nm in TIER_C else (M["暮蓝"] if "上下" in nm else TIER_C["UNRESOLVED"]), height=0.5, zorder=3)
        if v / tot > 0.08:
            ax.text(left + v / tot * 50, y0, f"{nm}\n{v:,}（{v/tot*100:.1f}%）", ha="center", va="center", fontsize=8, color="#FFFFFF", weight="bold")
        left += v / tot * 100
    y0 -= 1
ax.set_yticks([1, 0]); ax.set_yticklabels([u for u, _ in universes], fontsize=10)
ax.set_xlim(0, 100); ax.set_xlabel("宇宙内占比（%）")
ax.set_title("证据门内/门外两个宇宙的内部构成")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
foot(fig, "数据源：FINAL_NUMBERS.json / FULL_UNIVERSE_ADMISSION_SUMMARY.json")
save_fig(fig, "H05", "证据门宇宙构成图", "级联准入", SCR, ["T09"], "门内再分层与门外前置归因")

# H06 六层定位桶
T06 = pd.read_csv(os.path.join(MID, "T06_六层定位桶.csv")).sort_values("规模")
fig, ax = new_fig(8.6, 4.8)
y = np.arange(len(T06))
ax.barh(y, T06["规模"] / 1000, color=M["青灰"], height=0.6, zorder=2)
ax.barh(y, T06["已测STRICT"] / 1000, color=TIER_C["STRICT"], height=0.6, zorder=3)
ax.set_yticks(y); ax.set_yticklabels(T06["定位桶"], fontsize=8.6)
for i, (s, st) in enumerate(zip(T06["规模"], T06["已测STRICT"])):
    ax.annotate(f"STRICT 率 {st/s*100:.1f}%（{st:,}/{s:,}）", (s / 1000, i), xytext=(5, 0),
                textcoords="offset points", va="center", fontsize=7.8, color=INK)
ax.set_xlabel("断言数（千）"); ax.set_xlim(0, 58)
ax.set_title("六层证据定位桶与严格层转化（浅=桶规模，深=严格层）")
despine(ax); light_grid(ax, axis="x")
foot(fig, "数据源：FINAL_EVIDENCE_REPORT.md §2（aligned 支持率最高、recovery_C 大而不强）")
save_fig(fig, "H06", "六层证据定位桶图", "级联准入", SCR, ["T06"], "A≠B 的直接证据：59,891 条靠词法恢复")

# H07 五档结构
T07 = pd.read_csv(os.path.join(MID, "T07_证据门五档支持.csv"))
def sup_key(s):
    for k in SUP_C:
        if k in str(s): return k
    return str(s)
sup = T07.copy()
sup["key"] = sup["语义支持等级"].apply(sup_key)
sup = sup.sort_values("断言数")
fig, ax = new_fig(8.2, 4.4)
ax.barh([SUP_ZH[k] for k in sup["key"]], sup["断言数"], color=[SUP_C[k] for k in sup["key"]], height=0.62, zorder=3)
for i, v in enumerate(sup["断言数"]):
    ax.annotate(f"{v:,}（{v/105081*100:.1f}%）", (v, i), xytext=(5, 0), textcoords="offset points", va="center", fontsize=8.2, color=INK)
ax.set_xscale("log"); ax.set_xlim(8, 200000)
ax.set_xlabel("判定条数（log）")
ax.set_title("证据语义门五档支持结构（105,081 判定档案）")
despine(ax); light_grid(ax, axis="x")
foot(fig, "数据源：gate_verdict_details（不含 recovery_D 规约的 2,106 条）")
save_fig(fig, "H07", "五档语义支持结构图", "证据核验", SCR, ["T07"], "无支持与部分支持为主体")

# H08 五档×层热力
T08b = pd.read_csv(os.path.join(MID, "T08b_五档与最终层交叉.csv"))
pv = T08b.pivot_table(index="语义支持等级", columns="最终层", values="断言数", aggfunc="sum").fillna(0)
pv = pv.reindex(index=[k for k in ["FULLY_SUPPORTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT", "UNSUPPORTED", "CONTRADICTED"] if any(k in s for s in pv.index)],
                columns=[c for c in ["STRICT", "CONTEXTUAL", "UNRESOLVED"] if c in pv.columns])
fig, ax = new_fig(7.8, 5.0)
cmapb = mpl.colors.LinearSegmentedColormap.from_list("mb", BLUE_SEQ)
im = ax.imshow(np.log10(pv.values + 1), cmap=cmapb, aspect="auto")
ax.set_xticks(range(len(pv.columns))); ax.set_xticklabels([TIER_ZH.get(c, c) for c in pv.columns], fontsize=9)
ax.set_yticks(range(len(pv))); ax.set_yticklabels([SUP_ZH[sup_key(x)] for x in pv.index], fontsize=8.6)
for i in range(len(pv)):
    for j in range(len(pv.columns)):
        v = pv.values[i, j]
        if v > 0:
            ax.text(j, i, f"{int(v):,}", ha="center", va="center", fontsize=8,
                    color="#FFFFFF" if v > pv.values.max() * 0.5 else INK)
ax.set_title("五档语义支持 × 最终层交叉矩阵")
cb = fig.colorbar(im, ax=ax, shrink=0.8); cb.set_label("log10(条数)", fontsize=9)
despine(ax, keep=())
foot(fig, "数据源：T08b（evidence_gate_tier × gate_verdict_details）")
save_fig(fig, "H08", "五档与层交叉热力图", "证据核验", SCR, ["T08b"], "PARTIAL 入 STRICT 仅限 strict 谓词")

# H09 三层概念图
fig, ax = new_fig(10.8, 6.0)
ax.set_xlim(0, 10.8); ax.set_ylim(0, 6.0); ax.axis("off")
bands = [
    ("A · 来源追溯（谱系）", "provenance evidence_ids ≥ 1", "112,158", 44.72, TIER_C["STRICT"], 3.9),
    ("B · 证据定位（可取回）", "direct 指针 + 词法恢复 A/B/C", "110,052", 98.12, M["雾蓝"], 2.35),
    ("C · 语义支持（真支持）", "FULLY / 安全规则 / PARTIAL-strict", "31,067", 28.23, M["橄榄"], 0.8),
]
for nm, desc, cnt, rate, c, y in bands:
    ax.add_patch(FancyBboxPatch((1.6, y), 7.6, 1.15, boxstyle="round,pad=0.05,rounding_size=0.16",
                                facecolor=c, alpha=0.14, edgecolor=c, lw=1.4))
    ax.text(2.0, y + 0.82, nm, fontsize=11.5, weight="bold", color=INK)
    ax.text(2.0, y + 0.34, desc, fontsize=8.8, color=FAINT)
    ax.text(8.9, y + 0.58, f"{cnt}\n{rate}%", fontsize=10.5, ha="center", va="center", color=c, weight="bold")
for y1, y2, lab in [(3.9, 2.35, "词法恢复找回 59,891\n（A≠B）"), (2.35, 0.8, "取回 ≠ 支持\nrecovery_C 仅约14.8%（B≠C）")]:
    farrow(ax, 5.4, y1, 5.4, y2 + 1.15, lw=1.6)
    ax.text(5.62, (y1 + y2 + 1.15) / 2 - 0.05, lab, fontsize=8, color=FAINT, va="center")
ax.set_title("三层证据链：来源追溯 → 证据定位 → 语义支持（三概念正交）", fontsize=12.5)
foot(fig, "数据源：FINAL_EVIDENCE_REPORT.md §1（A 44.72% / B 98.12% / C 28.23%，均为全库确定数）")
save_fig(fig, "H09", "三层证据链概念图", "方法概念", SCR, ["E16"], "论文最关键概念图：有链≠可取回≠真支持")

# H10 三概念量化点图
E16 = pd.read_csv(os.path.join(MID, "E16_三概念分离ABC.csv"))
fig, ax = new_fig(7.4, 4.2)
z = 1.96
for i, (_, r) in enumerate(E16.iterrows()):
    ph = r["分子"] / r["分母"]
    s = np.sqrt((ph * (1 - ph) + z * z / (4 * r["分母"])) / r["分母"])
    lo = (ph + z * z / (2 * r["分母"]) - z * s) / (1 + z * z / r["分母"])
    hi = (ph + z * z / (2 * r["分母"]) + z * s) / (1 + z * z / r["分母"])
    ax.errorbar(i, ph * 100, yerr=[[ph * 100 - lo * 100], [hi * 100 - ph * 100]], fmt="o", ms=10,
                color=SEQ10[i], capsize=5, lw=1.6, zorder=3)
    ax.annotate(f"{r['比率']*100:.2f}%（{int(r['分子']):,}/{int(r['分母']):,}）", (i, ph * 100),
                xytext=(12, -4), textcoords="offset points", fontsize=9, color=INK)
ax.set_xticks(range(3)); ax.set_xticklabels(["A 谱系完整率", "B 证据定位率", "C 语义支持率"], fontsize=9.5)
ax.set_ylabel("比率（%，Wilson 95%CI）"); ax.set_ylim(0, 115)
ax.set_title("三概念分离的量化（全库确定数）")
despine(ax); light_grid(ax)
foot(fig, "数据源：FINAL_NUMBERS.json A_lineage / B_localization / C_semantic_support")
save_fig(fig, "H10", "三概念量化点图", "证据核验", SCR, ["E16"], "A、B、C 三率显著分离")

# H11 各桶转化率+CI
fig, ax = new_fig(8.2, 4.6)
T06s = pd.read_csv(os.path.join(MID, "T06_六层定位桶.csv"))
T06s["rate"] = T06s["已测STRICT"] / T06s["规模"] * 100
T06s = T06s.sort_values("rate")
for i, (_, r) in enumerate(T06s.iterrows()):
    ph = r["已测STRICT"] / r["规模"]
    s = np.sqrt((ph * (1 - ph) + z * z / (4 * r["规模"])) / r["规模"])
    lo = max((ph + z * z / (2 * r["规模"]) - z * s) / (1 + z * z / r["规模"]), 0)
    hi = (ph + z * z / (2 * r["规模"]) + z * s) / (1 + z * z / r["规模"])
    ax.errorbar(ph * 100, i, xerr=[[ph * 100 - lo * 100], [hi * 100 - ph * 100]], fmt="o", ms=8,
                color=M["雾蓝"], capsize=4, lw=1.4, zorder=3)
    ax.annotate(f"{ph*100:.1f}%", (ph * 100, i), xytext=(10, -3), textcoords="offset points", fontsize=8.6, color=INK)
ax.set_yticks(range(len(T06s))); ax.set_yticklabels(T06s["定位桶"], fontsize=8.6)
ax.set_xlabel("严格层转化率（%，Wilson 95%CI）"); ax.set_xlim(-4, 60)
ax.set_title("各定位桶的严格层转化率与置信区间")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
foot(fig, "数据源：T06（桶规模 × 已测STRICT）")
save_fig(fig, "H11", "定位桶转化率置信图", "证据核验", SCR, ["T06"], "aligned 42.2% 与 recovery_B 43.0% 最高")

# H12 判定方法构成
T08 = pd.read_csv(os.path.join(MID, "T08_证据门分层方法.csv"))
gmeth = T08.groupby("判定方法")["断言数"].sum()
fig, ax = new_fig(7.2, 2.9)
left = 0; tot = gmeth.sum()
for k, v in gmeth.items():
    ax.barh(0, v / tot * 100, left=left, color=M["陶砂"] if k == "rule" else M["雾蓝"], height=0.5, zorder=3)
    ax.text(left + v / tot * 50, 0, f"{k}  {v:,}（{v/tot*100:.2f}%）", ha="center", va="center", fontsize=8.6,
            color="#FFFFFF", weight="bold")
    left += v / tot * 100
ax.set_yticks([]); ax.set_xlim(0, 100); ax.set_xlabel("占比（%）")
ax.set_title("证据门判定方法构成（rule = recovery_D 规约）")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
foot(fig, "数据源：T08_证据门分层方法（112,158 条）")
save_fig(fig, "H12", "判定方法构成图", "证据核验", SCR, ["T08"], "97.8% 由本地 LLM 逐条判定")

# H13 分层流（第二种编码）
fig, ax = new_fig(10.6, 5.6)
ax.set_xlim(0, 10.6); ax.set_ylim(0, 5.6); ax.axis("off")
lanes = [
    ("严格路径", 31067, TIER_C["STRICT"], 4.4, "严格候选→证据定位→五档判定→STRICT"),
    ("上下文路径", 299329, TIER_C["CONTEXTUAL"], 2.6, "前置上下文 268,047 ∪ 核验降级 31,282"),
    ("未决路径", 93754, TIER_C["UNRESOLVED"], 0.8, "前置未决 43,945 ∪ 核验未决 49,809"),
]
for nm, v, c, y, desc in lanes:
    wbar = 3.2 + 4.4 * v / 299329
    ax.add_patch(FancyBboxPatch((0.6, y), wbar, 1.15, boxstyle="round,pad=0.04,rounding_size=0.2",
                                facecolor=c, alpha=0.85, edgecolor="none"))
    ax.text(0.85, y + 0.72, nm, fontsize=11, weight="bold", color="#FFFFFF")
    ax.text(0.85, y + 0.3, f"{v:,} 条", fontsize=9.5, color="#FFFFFF")
    ax.text(0.85 + wbar + 0.25, y + 0.55, desc, fontsize=8.8, color=FAINT, va="center")
ax.set_title("级联准入分层流图（条带厚度 ∝ 断言量，同一逻辑的第二种编码）")
foot(fig, "数据源：AUTHORITATIVE_RESULTS.md 定版数字")
save_fig(fig, "H13", "级联准入分层流图", "级联准入", SCR, ["T09"], "三种视觉编码之二")

# H14 管道板（第三种编码）
fig, ax = new_fig(10.6, 6.4)
ax.set_xlim(0, 10.6); ax.set_ylim(0, 6.4); ax.axis("off")
ax.add_patch(FancyBboxPatch((0.4, 0.4), 9.8, 5.6, boxstyle="round,pad=0.06,rounding_size=0.3",
                            facecolor="#FAFAF8", edgecolor=AXIS, lw=1.6))
pipes = [("① 前置结构分层", "全库 424,150 → 严格候选 112,158 / 上下文 268,047 / 未决 43,945", 4.5, M["石板"]),
         ("② 证据定位", "112,158 → 可定位 110,052（98.12%）· 无证据 2,106 → 未决", 3.2, M["暮蓝"]),
         ("③ 语义支持判定", "qwen3.5-4b 五档：FULLY 22,099 · PARTIAL 34,922 · UNSUP 44,976 · INSUF 3,057 · CONTRA 27", 1.9, M["雾蓝"]),
         ("④ 分层发布", "STRICT 31,067 · CONTEXTUAL 299,329 · UNRESOLVED 93,754", 0.75, TIER_C["STRICT"])]
for nm, desc, y, c in pipes:
    ax.add_patch(FancyBboxPatch((0.9, y), 8.8, 0.95, boxstyle="round,pad=0.04,rounding_size=0.18",
                                facecolor=c, alpha=0.12, edgecolor=c, lw=1.3))
    ax.text(1.15, y + 0.62, nm, fontsize=10.5, weight="bold", color=c)
    ax.text(1.15, y + 0.26, desc, fontsize=8.4, color=INK)
    if y > 1:
        farrow(ax, 5.3, y, 5.3, y - 0.35)
ax.text(5.3, 6.15, "级联准入管道板（同一逻辑的第三种编码）", ha="center", fontsize=12.5, weight="bold", color=INK)
foot(fig, "数据源：AUTHORITATIVE_RESULTS.md 定版数字（判定档案 127,633 条）")
save_fig(fig, "H14", "级联准入管道板图", "级联准入", SCR, ["T09"], "三种视觉编码之三")

# H15 前置上下文阻断
fig, ax = new_fig(7.6, 2.7)
parts = [("谓词未完成规范化", 264635), ("不满足关系域约束", 3412)]
left = 0
for i, (nm, v) in enumerate(parts):
    ax.barh(0, v, left=left, color=[M["驼灰"], M["绛陶"]][i], height=0.52, zorder=3)
    ax.text(left + v / 2, 0, f"{nm} {v:,}（{v/268047*100:.2f}%）", ha="center", va="center", fontsize=8.8,
            color="#FFFFFF", weight="bold")
    left += v
ax.set_yticks([]); ax.set_xlim(0, 268047); ax.set_xlabel("断言数")
ax.set_title("前置上下文 268,047 的阻断构成")
despine(ax, keep=("bottom",))
foot(fig, "数据源：FULL_UNIVERSE_ADMISSION_SUMMARY.json")
save_fig(fig, "H15", "前置上下文阻断构成图", "级联准入", SCR, ["T10"], "99% 以上为谓词未归一")

# H16 未决双重来源
fig, ax = new_fig(8.0, 4.4)
parts = [("前置：作用域冲突", 27492), ("前置：端点未决", 16393), ("前置：人工遗留", 60),
         ("核验：证据不支持", 47576), ("核验：证据冲突", 127), ("核验：无证据", 2106)]
cols = [M["暮蓝"], M["雾蓝"], M["石板"], TIER_C["UNRESOLVED"], M["绛陶"], M["驼灰"]]
y = np.arange(len(parts))[::-1]
ax.barh(y, [v for _, v in parts], color=cols, height=0.62, zorder=3)
ax.set_yticks(y); ax.set_yticklabels([n for n, _ in parts], fontsize=8.8)
for yi, (_, v) in zip(y, parts):
    ax.annotate(f"{v:,}", (v, yi), xytext=(5, 0), textcoords="offset points", va="center", fontsize=8.2, color=INK)
ax.set_xscale("log"); ax.set_xlim(30, 300000); ax.set_xlabel("断言数（log）")
ax.set_title("UNRESOLVED 93,754 的双重来源分解")
despine(ax); light_grid(ax, axis="x")
foot(fig, "数据源：AUTHORITATIVE_RESULTS.md §二之四")
save_fig(fig, "H16", "未决层双重来源图", "级联准入", SCR, ["T10"], "证据不支持 47,576 为最大来源")

# H17 replay 六零检查
rep = {"strict候选计数": 0, "上下文计数": 0, "未决计数": 0, "归因差异数": 0, "字段差异": 0, "硬结构违规": 0}
fig, ax = new_fig(8.6, 3.4)
ax.set_xlim(0, 8.6); ax.set_ylim(0, 3.4); ax.axis("off")
for i, (k, v) in enumerate(rep.items()):
    x = 0.4 + (i % 3) * 2.8; y = 1.75 - (i // 3) * 1.35
    ax.add_patch(FancyBboxPatch((x, y), 2.5, 1.05, boxstyle="round,pad=0.05,rounding_size=0.14",
                                facecolor="#EFF3EE", edgecolor=M["橄榄"], lw=1.4))
    ax.text(x + 0.28, y + 0.52, "✓", fontsize=17, color=M["橄榄"], va="center", weight="bold")
    ax.text(x + 0.62, y + 0.63, k, fontsize=9.4, color=INK, va="center")
    ax.text(x + 0.62, y + 0.28, f"差异 = {v}", fontsize=8.4, color=M["橄榄"], va="center")
ax.text(4.3, 3.15, "全库重放（replay）六项零检查全部 PASS", ha="center", fontsize=12, weight="bold", color=INK)
ax.text(4.3, 0.22, "424,150 条全部可重放：unexplained = 0；BASELINE 三层计数逐位一致", ha="center", fontsize=8.8, color=FAINT)
foot(fig, "数据源：FULL_ADMISSION_REPLAY_REPORT.json（seed=20260916）")
save_fig(fig, "H17", "全库重放零检查图", "级联准入", SCR, ["E10"], "可复现性的机器核验")

# H18 方法总流程
fig, ax = new_fig(11.6, 7.0)
ax.set_xlim(0, 11.6); ax.set_ylim(0, 7.0); ax.axis("off")
fbox(ax, 0.3, 5.5, 2.0, 1.0, "候选抽取\n282,165 候选", fc="#EDF1F4", ec=M["雾蓝"], fs=9)
fbox(ax, 2.9, 5.5, 2.5, 1.0, "一级控制：选择性预测\n规则/分类器/LLM + 显式弃权", fc="#F0F2F4", ec=M["青灰"], fs=8.8)
fbox(ax, 6.0, 5.5, 2.5, 1.0, "二级控制：结构准入\n身份投影/关系契约/时空/来源", fc="#F0F2F4", ec=M["青灰"], fs=8.8)
fbox(ax, 9.1, 5.5, 2.2, 1.0, "前置三层\n112,158 / 268,047 / 43,945", fc="#F3F0EA", ec=M["陶砂"], fs=8.4)
fbox(ax, 6.0, 3.9, 2.5, 1.0, "证据语义门\n定位 110,052 · 五档判定", fc="#EFF3EE", ec=M["橄榄"], fs=8.8)
fbox(ax, 9.1, 3.9, 2.2, 1.0, "严格层派生\nEventFrame 28,065\nCultureState 11,532", fc="#F0F2F4", ec=M["暮蓝"], fs=8)
fbox(ax, 2.9, 3.9, 2.5, 1.0, "上下文层 / 未决集合\n（保留来源与决策记录）", fc="#F3F1F1", ec=M["绛陶"], fs=8.6)
fbox(ax, 2.9, 2.2, 8.4, 1.0, "全库最终三层：STRICT 31,067 · CONTEXTUAL 299,329 · UNRESOLVED 93,754（466,312 来源关联，全部可返回原文）",
     fc=TIER_C["STRICT"], ec=TIER_C["STRICT"], fs=9.6, tc="#FFFFFF", weight="bold")
fbox(ax, 2.9, 0.7, 8.4, 0.9, "独立审计：门内 99.28% 支持精度（965/972 强共识）· 门外 STRICT 机会率 0.63%（样本）/0.66%（加权）",
     fc="#FAF7F0", ec=M["陶砂"], fs=8.8)
farrow(ax, 2.35, 6.0, 2.85, 6.0); farrow(ax, 5.45, 6.0, 5.95, 6.0); farrow(ax, 8.55, 6.0, 9.05, 6.0)
farrow(ax, 7.25, 5.45, 7.25, 4.95); farrow(ax, 5.95, 4.4, 5.45, 4.4)
farrow(ax, 4.15, 5.45, 4.15, 4.95)
farrow(ax, 7.0, 3.85, 7.0, 3.25); farrow(ax, 4.15, 3.85, 4.15, 3.25)
farrow(ax, 7.1, 2.15, 7.1, 1.65)
ax.set_title("级联准入方法总流程：从候选知识到分层发布的连续质量控制链", fontsize=12.5)
foot(fig, "数据源：AUTHORITATIVE_RESULTS.md 方法定型叙述 + FINAL_NUMBERS.json")
save_fig(fig, "H18", "级联准入方法总流程图", "方法概念", SCR, ["AUTHORITATIVE_RESULTS"], "论文方法总图")

print("批D（F01-F16, G01-G08, H01-H18）完成")
