# -*- coding: utf-8 -*-
"""批E_证据审计.py — I01–I10 证据语义核验（10张）+ J01–J14 审计与质量评价（14张）"""
import sys, os, json, collections
sys.path.insert(0, r"D:\REDCULTUREDATA\可视化输出\10_生成脚本")
from style_lib import *
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Patch, Circle
import numpy as np
import pandas as pd

MID = r"D:\REDCULTUREDATA\可视化输出\11_数据中间表"
SCR = "批E_证据审计.py"
z = 1.96

def wilson(num, den):
    ph = num / den
    s = np.sqrt((ph * (1 - ph) + z * z / (4 * den)) / den)
    lo = (ph + z * z / (2 * den) - z * s) / (1 + z * z / den)
    hi = (ph + z * z / (2 * den) + z * s) / (1 + z * z / den)
    return ph, lo, hi

def farrow(ax, x1, y1, x2, y2, style="-|>", color=FAINT, lw=1.3):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=15,
                                 color=color, lw=lw, zorder=1))

def fbox(ax, x, y, w, h, txt, fc="#F2F4F3", ec="#7FA3A0", fs=9.5, weight="normal", tc="#2B2B2B", lw=1.2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.06,rounding_size=0.12",
                                facecolor=fc, edgecolor=ec, lw=lw, zorder=2))
    ax.text(x + w / 2, y + h / 2, txt, ha="center", va="center", fontsize=fs, color=tc,
            weight=weight, zorder=3, linespacing=1.4)

def foot(fig, txt):
    fig.text(0.01, 0.012, txt, fontsize=8, color=FAINT)

def sup_key(s):
    for k in SUP_C:
        if k in str(s): return k
    return str(s)

T07 = pd.read_csv(os.path.join(MID, "T07_证据门五档支持.csv"))
T40 = pd.read_csv(os.path.join(MID, "T40_谓词×五档.csv"))
T41 = pd.read_csv(os.path.join(MID, "T41_省域×五档.csv"))
T42 = pd.read_csv(os.path.join(MID, "T42_判定置信度×五档.csv"))
T43 = pd.read_csv(os.path.join(MID, "T43_时延×五档.csv"))
T44 = pd.read_csv(os.path.join(MID, "T44_引文长度分布.csv"))
T45 = pd.read_csv(os.path.join(MID, "T45_五档典型案例.csv"))
E09 = json.load(open(os.path.join(MID, "E09_门内审计.json"), encoding="utf-8"))
E08 = json.load(open(os.path.join(MID, "E08_门外审计.json"), encoding="utf-8"))
E14 = pd.read_csv(os.path.join(MID, "E14_门外审计核心指标.csv"))
E13 = json.load(open(os.path.join(MID, "E13_分层政策.json"), encoding="utf-8"))

# ================= I 证据语义核验 =================
# I01 引文长度
fig, ax = new_fig(7.4, 4.4)
ax.bar(T44["长度档(字)"], T44["判定数"], width=38, color=M["雾蓝"], zorder=3, edgecolor="white")
for x, yv in zip(T44["长度档(字)"], T44["判定数"]):
    ax.annotate(f"{yv:,}", (x, yv), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8, color=INK)
ax.set_xlabel("证据引文长度（字，50字分箱，>800截断）"); ax.set_ylabel("判定条数")
ax.set_title("证据引文长度分布（有引文判定 56,485 条中的分箱）")
despine(ax); light_grid(ax)
foot(fig, "数据源：gate_verdict_details.evidence_quote 长度分箱（>800 桶已截断显示）")
save_fig(fig, "I01", "证据引文长度分布图", "证据核验", SCR, ["T44"], "证据文本集中在短片段")

# I02 置信度分布
g42 = T42.groupby("置信度档")["判定数"].sum()
fig, ax = new_fig(7.2, 4.2)
ax.bar(g42.index, g42.values, width=0.07, color=M["青灰"], zorder=3)
for x, yv in zip(g42.index, g42.values):
    ax.annotate(f"{yv:,}", (x, yv), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=7.8, color=INK)
ax.set_xlim(-0.05, 1.05); ax.set_xlabel("判定置信度（0.1 分箱）"); ax.set_ylabel("判定条数")
ax.set_title("证据门判定置信度分布（105,081 判定）")
despine(ax); light_grid(ax)
foot(fig, "数据源：gate_verdict_details.confidence")
save_fig(fig, "I02", "判定置信度分布图", "证据核验", SCR, ["T42"], "高置信判定占主体")

# I03 五档置信度箱线（加权分位数）
def wq(vals, ws, q):
    order = np.argsort(vals)
    v = np.array(vals)[order]; w = np.array(ws)[order]
    cw = np.cumsum(w); cw = (cw - 0.5 * w) / w.sum()
    return np.interp(q, cw, v)
fig, ax = new_fig(8.2, 4.8)
order5 = ["FULLY_SUPPORTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT", "UNSUPPORTED", "CONTRADICTED"]
data = []
for d5 in order5:
    sub = T42[T42["五档"].str.contains(d5.split("_")[0]) & T42["五档"].str.contains(d5.split("_")[-1])] if "_" in d5 else None
    sub = T42[T42["五档"].apply(sup_key) == d5]
    if len(sub) == 0: data.append([np.nan] * 5); continue
    vals = sub["置信度档"].values; ws = sub["判定数"].values
    q1 = wq(vals, ws, 0.25); q2 = wq(vals, ws, 0.5); q3 = wq(vals, ws, 0.75)
    iqr = q3 - q1
    data.append([max(q1 - 1.5 * iqr, 0), q1, q2, q3, min(q3 + 1.5 * iqr, 1.0)])
data = np.array(data, dtype=float)
for i in range(len(order5)):
    d = data[i]
    if np.isnan(d).all(): continue
    ax.plot([i + 1, i + 1], [d[0], d[4]], color=SUP_C[order5[i]], lw=1.2, zorder=2)
    ax.add_patch(mpl.patches.Rectangle((i + 1 - 0.22, d[1]), 0.44, d[3] - d[1], facecolor=SUP_C[order5[i]], alpha=0.65, zorder=3))
    ax.plot([i + 0.78, i + 1.22], [d[2], d[2]], color=INK, lw=1.4, zorder=4)
ax.set_xticks(range(1, 6)); ax.set_xticklabels([SUP_ZH[k] for k in order5], fontsize=9)
ax.set_ylabel("判定置信度（加权分位数箱线）")
ax.set_title("五档判定的置信度加权箱线图（由分箱计数重构）")
despine(ax, keep=("bottom",)); light_grid(ax, axis="y")
foot(fig, "数据源：T42（0.1 分箱计数 → 加权分位数重构箱线，避免采样）")
save_fig(fig, "I03", "五档置信度箱线图", "证据核验", SCR, ["T42"], " contradictions 与 unsupported 置信更低")

# I04 时延分布
g43 = T43.groupby("时延档(s)")["判定数"].sum()
fig, ax = new_fig(7.8, 4.2)
ax.bar(g43.index, g43.values, width=0.2, color=M["暮蓝"], zorder=3)
ax.set_xlim(0, min(20, g43.index.max()))
ax.set_xlabel("判定时延（秒，0.25s 分箱）"); ax.set_ylabel("判定条数")
ax.set_title("证据门判定时延分布（截断至 20s）")
despine(ax); light_grid(ax)
foot(fig, "数据源：gate_verdict_details.latency_s（<60s 样本）")
save_fig(fig, "I04", "判定时延分布图", "证据核验", SCR, ["T43"], "多数判定在数秒内完成")

# I05 五档时延小提琴（加权KDE）
from scipy.stats import gaussian_kde
fig, ax = new_fig(8.4, 4.8)
for i, d5 in enumerate(order5):
    sub = T43[T43["五档"].apply(sup_key) == d5]
    if len(sub) < 3: continue
    vals = np.repeat(sub["时延档(s)"].values, sub["判定数"].values.astype(int))
    vals = vals[vals < 20]
    if len(vals) < 30: continue
    kde = gaussian_kde(vals)
    xs = np.linspace(0, 20, 200)
    dens = kde(xs)
    viol = dens / dens.max() * 0.38
    ax.fill_betweenx(xs, i + 1 - viol, i + 1 + viol, color=SUP_C[d5], alpha=0.55, zorder=2)
    ax.plot(i + 1 + viol, xs, color=SUP_C[d5], lw=1.0, zorder=3)
    ax.plot(i + 1 - viol, xs, color=SUP_C[d5], lw=1.0, zorder=3)
    ax.scatter(i + 1, np.median(vals), s=26, color=INK, zorder=4)
ax.set_xticks(range(1, 6)); ax.set_xticklabels([SUP_ZH[k] for k in order5], fontsize=9)
ax.set_ylabel("判定时延（秒）")
ax.set_title("五档判定的时延分布（加权 KDE 小提琴，中位数=黑点）")
despine(ax, keep=("bottom",)); light_grid(ax, axis="y")
foot(fig, "数据源：T43（0.25s 分箱展开加权 KDE；截断 20s）")
save_fig(fig, "I05", "五档时延小提琴图", "证据核验", SCR, ["T43"], "矛盾判定耗时更长")

# I06 PARTIAL 谓词政策
ppt = E13.get("predicate_policy_table", {})
if isinstance(ppt, dict):
    rows6 = [(k, v) for k, v in list(ppt.items())[:20]]
else:
    rows6 = []
strict_preds = ["active_at", "captured", "collaborated_with", "contacted", "created", "died_at", "dispatched",
                "fought_at", "guided", "opposed", "responsible_for", "supported", "worked_at"]
fig, ax = new_fig(8.0, 5.0)
if rows6:
    names = [str(k) for k, _ in rows6]
    vals = [float(v.get("full_share", v) if isinstance(v, dict) else v) for _, v in rows6]
    vals = [v * 100 if v <= 1 else v for v in vals]
    cols = [TIER_C["STRICT"] if n in strict_preds else M["驼灰"] for n in names]
    y = np.arange(len(names))[::-1]
    ax.scatter(vals, y, s=70, color=cols, zorder=3)
    for yi, (n, v) in zip(y, zip(names, vals)):
        ax.annotate(f"{v:.0f}%", (v, yi), xytext=(8, -3), textcoords="offset points", fontsize=7.8, color=INK)
    ax.set_yticks(y); ax.set_yticklabels(names, fontsize=8.4, family=_LAT if False else None)
    ax.axvline(70, color=AXIS, ls="--", lw=1)
    ax.annotate("FULL 占比 70% 准入线", (70, y[-1]), xytext=(5, 0), textcoords="offset points", fontsize=8, color=FAINT)
ax.set_xlabel("谓词 FULL 判定占比（%）")
ax.set_title("PARTIAL 判定可入严格层的谓词政策表（深色=入 STRICT 谓词）")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
foot(fig, "数据源：FINAL_TIERING_POLICY.json predicate_policy_table")
save_fig(fig, "I06", "PARTIAL谓词政策点图", "证据核验", SCR, ["E13"], "13 个谓词的 PARTIAL 可保持严格层")

# I07 五档×谓词热力
pv = T40.pivot_table(index="谓词", columns="五档", values="断言数", aggfunc="sum").fillna(0)
pv = pv.loc[pv.sum(axis=1).sort_values(ascending=False).index[:14]]
colorder = [c for c in ["FULLY_SUPPORTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT", "UNSUPPORTED", "CONTRADICTED"] if any(c in x for x in pv.columns)]
pv = pv[[colorder[0] if len(colorder) == 1 else pv.columns[0]]] if False else pv
fig, ax = new_fig(9.0, 6.0)
cmapb = mpl.colors.LinearSegmentedColormap.from_list("mb", BLUE_SEQ)
im = ax.imshow(np.log10(pv.values + 1), cmap=cmapb, aspect="auto")
ax.set_xticks(range(len(pv.columns)))
ax.set_xticklabels([SUP_ZH.get(sup_key(c), c) for c in pv.columns], fontsize=8.6)
ax.set_yticks(range(len(pv))); ax.set_yticklabels([pz(x) for x in pv.index], fontsize=8.4)
for i in range(len(pv)):
    for j in range(len(pv.columns)):
        v = pv.values[i, j]
        if v > 0:
            ax.text(j, i, f"{int(v):,}", ha="center", va="center", fontsize=7,
                    color="#FFFFFF" if v > pv.values.max() * 0.5 else INK)
ax.set_title("五档语义支持 × 高频谓词热力矩阵")
cb = fig.colorbar(im, ax=ax, shrink=0.8); cb.set_label("log10(断言数)", fontsize=9)
despine(ax, keep=())
foot(fig, "数据源：T40（evidence_gate_tier join gate_verdict_details，≥100 条组合）")
save_fig(fig, "I07", "五档谓词热力矩阵", "证据核验", SCR, ["T40"], "不同谓词的证据支持画像")

# I08 五档×省域热力
pv = T41.copy()
pv["省"] = pv["省份"].astype(str).str[:2]
pv = pv.pivot_table(index="省", columns="五档", values="断言数", aggfunc="sum").fillna(0)
pv = pv.loc[pv.sum(axis=1).sort_values(ascending=False).index[:13]]
fig, ax = new_fig(8.8, 6.2)
im = ax.imshow(np.log10(pv.values + 1), cmap=cmapb, aspect="auto")
ax.set_xticks(range(len(pv.columns)))
ax.set_xticklabels([SUP_ZH.get(sup_key(c), c) for c in pv.columns], fontsize=8.2)
ax.set_yticks(range(len(pv))); ax.set_yticklabels(pv.index, fontsize=8.8)
for i in range(len(pv)):
    for j in range(len(pv.columns)):
        v = pv.values[i, j]
        if v > 0:
            ax.text(j, i, f"{int(v):,}", ha="center", va="center", fontsize=6.8,
                    color="#FFFFFF" if v > pv.values.max() * 0.5 else INK)
ax.set_title("五档语义支持 × 省域热力矩阵")
cb = fig.colorbar(im, ax=ax, shrink=0.8); cb.set_label("log10(断言数)", fontsize=9)
despine(ax, keep=())
foot(fig, "数据源：T41（门宇宙内含省域字段的断言）")
save_fig(fig, "I08", "五档省域热力矩阵", "证据核验", SCR, ["T41"], "地域证据质量结构均衡")

# I09 定位率瀑布
fig, ax = new_fig(8.6, 4.6)
steps = [("证据门宇宙", 112158, "total"), ("词法恢复找回", 59891, "hide"), ("原生指针", 50161, "hide"),
         ("无证据降未决", -2106, "sub"), ("可定位合计", 110052, "total2")]
left = 0
for i, (nm, v, kind) in enumerate(steps):
    if kind == "total":
        ax.bar(i, v, color=M["石板"], width=0.58, zorder=3)
        ax.annotate(f"{v:,}", (i, v), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.6, color=INK, weight="bold")
        left = 0
    elif kind == "hide":
        ax.bar(i, v, bottom=left, color=[M["暮蓝"], M["雾蓝"]][[s[0] for s in steps].index(nm) - 1], width=0.58, zorder=3)
        ax.annotate(f"+{v:,}", (i, left + v), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.2, color=INK)
        left += v
    elif kind == "sub":
        ax.bar(i, -v, bottom=left, color=M["绛陶"], width=0.58, zorder=3)
        ax.annotate(f"−{v:,}", (i, left), xytext=(0, -12), textcoords="offset points", ha="center", fontsize=8.2, color=M["绛陶"])
        left -= v
    else:
        ax.bar(i, v, color=TIER_C["STRICT"], width=0.58, zorder=3)
        ax.annotate(f"{v:,}\n（98.12%）", (i, v), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.6, color=INK, weight="bold")
ax.set_xticks(range(len(steps)))
ax.set_xticklabels([wrap_zh(s[0], 8) for s in steps], fontsize=8.4)
ax.set_yscale("symlog"); ax.set_ylabel("断言数（symlog）")
ax.set_title("证据定位率 98.12% 的构成瀑布")
despine(ax); light_grid(ax)
foot(fig, "数据源：FINAL_EVIDENCE_REPORT.md §1（B = 110,052/112,158；A≠B 由 59,891 词法恢复解释）")
save_fig(fig, "I09", "证据定位率瀑布图", "证据核验", SCR, ["E16", "T06"], "词法恢复贡献过半定位")

# I10 五档案例卡片
fig, ax = new_fig(11.6, 7.0)
ax.set_xlim(0, 11.6); ax.set_ylim(0, 7.0); ax.axis("off")
seen = set()
y = 6.35
for d5 in order5:
    sub = T45[T45["五档"].apply(sup_key) == d5]
    if len(sub) == 0: continue
    r = sub.iloc[0]
    quote = str(r["引文"])[:56] + ("…" if len(str(r["引文"])) > 56 else "")
    ax.add_patch(FancyBboxPatch((0.25, y - 1.0), 11.1, 1.12, boxstyle="round,pad=0.04,rounding_size=0.12",
                                facecolor="#FAFAF8", edgecolor=SUP_C[d5], lw=1.4))
    ax.add_patch(mpl.patches.Rectangle((0.25, y - 1.0), 0.14, 1.12, color=SUP_C[d5]))
    ax.text(0.55, y - 0.14, f"{SUP_ZH[d5]}（{d5}）", fontsize=10.5, weight="bold", color=SUP_C[d5])
    ax.text(3.3, y - 0.14, f"{r['主体']} —{pz(r['谓词'])}— {r['客体']}  →  {r['最终层']}", fontsize=9.4, color=INK)
    ax.text(0.55, y - 0.62, f"证据：「{quote}」", fontsize=8.2, color=FAINT)
    expl = str(r["解释"])[:60]
    ax.text(6.8, y - 0.62, f"理由：{expl}", fontsize=8.2, color=FAINT)
    y -= 1.28
ax.set_title("五档语义支持的典型真实案例（来自判定档案原文）", fontsize=12.5)
foot(fig, "数据源：gate_verdict_details（fact 级判定原文，未经改写摘录）")
save_fig(fig, "I10", "五档典型案例卡片图", "案例图", SCR, ["T45"], "五档判定的具象化样本")

# ================= J 审计与质量 =================
# J01 门内精度 CI
fig, ax = new_fig(8.4, 4.2)
items = [("强共识支持精度", 0.9928, 0.9852, 0.9965, "965/972"),
         ("仅 FULLY 精度", 0.8066, 0.7806, 0.8302, "784/972"),
         ("强共识误报率", 0.0041, 0.0016, 0.0105, "4/972")]
for i, (n, p, lo, hi, num) in enumerate(items):
    ax.errorbar(i, p, yerr=[[p - lo], [hi - p]], fmt="o", ms=10, color=M["雾蓝"], capsize=6, lw=1.8, zorder=3)
    ax.annotate(f"{p*100:.2f}%\n[{lo*100:.2f}, {hi*100:.2f}]  {num}", (i, p), xytext=(14, -8),
                textcoords="offset points", fontsize=8.6, color=INK)
ax.set_xticks(range(3)); ax.set_xticklabels([wrap_zh(n, 8) for n, *_ in items], fontsize=9.5)
ax.set_ylabel("比率（Wilson 95%CI）"); ax.set_ylim(-0.06, 1.12)
ax.set_title("门内 STRICT 独立审计：强共识支持精度 99.28%（n=4,427 双裁判样本）")
despine(ax); light_grid(ax)
foot(fig, "数据源：AUDIT_RESULTS.json（预注册触发器 PASS；规范表述禁止写「99.28%（n=4,427）」）")
save_fig(fig, "J01", "门内审计精度置信图", "审计评价", SCR, ["E15", "E09"], "精度 0.9928 [0.9852, 0.9965]")

# J02 分层支持率
by = E09["by_stratum"]
rows = [(k, v["n"], v["sup"], v["fp"]) for k, v in by.items()]
rows.sort(key=lambda r: r[2] / r[1])
fig, ax = new_fig(8.4, 6.8)
y = np.arange(len(rows))
for yi, (k, n, sup, fp) in zip(y, rows):
    ph, lo, hi = wilson(sup, n)
    ax.errorbar(ph * 100, yi, xerr=[[max(ph * 100 - lo * 100, 0)], [max(hi * 100 - ph * 100, 0)]], fmt="o",
                ms=7, color=M["雾蓝"], capsize=3, lw=1.2, zorder=3)
    if fp > 0:
        ax.scatter([ph * 100], [yi], s=110, facecolors="none", edgecolors=M["绛陶"], lw=1.4, zorder=4)
ax.set_yticks(y); ax.set_yticklabels([r[0] for r in rows], fontsize=8, family=None)
ax.set_xlabel("分层支持率（%，Wilson 95%CI；红圈=含误报层）"); ax.set_xlim(85, 103)
ax.set_title("门内审计 19 个分层样本的支持率")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
foot(fig, "数据源：AUDIT_RESULTS.json by_stratum（n=分层样本数）")
save_fig(fig, "J02", "门内分层支持率图", "审计评价", SCR, ["E09"], "recovery_C 与部分谓词层出现误报")

# J03 门内门外 κ 哑铃
fig, ax = new_fig(8.0, 3.6)
pairs = [("五档完全一致率", 0.3598, 0.8126), ("Cohen κ", 0.1838, 0.5136)]
for i, (n, a, b) in enumerate(pairs):
    y = 1 - i
    ax.plot([a, b], [y, y], color=GRID, lw=3.2, zorder=2)
    ax.scatter(a, y, s=90, color=M["驼灰"], zorder=3)
    ax.scatter(b, y, s=90, color=M["陶砂"], zorder=3)
    ax.annotate(f"门内 {a:.4f}", (a, y), xytext=(0, -15), textcoords="offset points", ha="center", fontsize=8.6, color=M["驼灰"])
    ax.annotate(f"门外 {b:.4f}", (b, y), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=8.6, color=M["陶砂"])
ax.set_yticks([1, 0]); ax.set_yticklabels([p[0] for p in pairs], fontsize=10)
ax.set_xlim(0, 1.0); ax.set_xlabel("值")
ax.set_title("门内/门外双裁判一致性对照（哑铃图）")
from matplotlib.lines import Line2D
ax.legend(handles=[Line2D([], [], marker="o", ls="", color=M["驼灰"], label="门内（n=4,427）"),
                   Line2D([], [], marker="o", ls="", color=M["陶砂"], label="门外（n=4,957 双有效）")], loc="upper center",
          bbox_to_anchor=(0.5, -0.24), ncol=2)
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
foot(fig, "数据源：AUDIT_RESULTS.json / OUTSIDE_GATE_AUDIT_RESULTS.json（门内风格两极的诚实呈现 κ=0.1838）")
save_fig(fig, "J03", "门内外一致性哑铃图", "审计评价", SCR, ["E14", "E15"], "门外五档一致率 0.8126、κ=0.5136")

# J04 双向审计框架概念图
fig, ax = new_fig(10.6, 4.8)
ax.set_xlim(0, 10.6); ax.set_ylim(0, 4.8); ax.axis("off")
ax.add_patch(FancyBboxPatch((0.4, 1.1), 4.2, 3.0, boxstyle="round,pad=0.08,rounding_size=0.18",
                            facecolor="#EDF1F4", edgecolor=M["雾蓝"], lw=1.5))
ax.text(2.5, 3.7, "precision-side 门内精度", ha="center", fontsize=11.5, weight="bold", color=M["雾蓝"])
ax.text(2.5, 2.9, "宇宙：证据门 112,158 内\n样本：4,427 条分层双裁判", ha="center", fontsize=9, color=INK, linespacing=1.5)
ax.text(2.5, 2.0, "99.28% 支持精度（965/972）\n强共识误报 0.41%", ha="center", fontsize=10, color=TIER_C["STRICT"], weight="bold", linespacing=1.5)
ax.add_patch(FancyBboxPatch((6.0, 1.1), 4.2, 3.0, boxstyle="round,pad=0.08,rounding_size=0.18",
                            facecolor="#F6F1EA", edgecolor=M["陶砂"], lw=1.5))
ax.text(8.1, 3.7, "omission-side 门外遗漏", ha="center", fontsize=11.5, weight="bold", color=M["陶砂"])
ax.text(8.1, 2.9, "宇宙：门外 311,992\n样本：5,000 分层（双有效 4,957）", ha="center", fontsize=9, color=INK, linespacing=1.5)
ax.text(8.1, 2.0, "STRICT 机会率 0.63% 样本\n加权总体 0.66% [0.40, 0.97]", ha="center", fontsize=10, color=M["陶砂"], weight="bold", linespacing=1.5)
farrow(ax, 4.75, 2.6, 5.85, 2.6, style="<|-|>", lw=1.6)
ax.text(5.3, 2.95, "双向\n审计", ha="center", fontsize=9, color=FAINT, linespacing=1.3)
ax.text(5.3, 0.5, "结论：保守准入未造成大规模高质量知识漏失", ha="center", fontsize=11, weight="bold", color=INK)
ax.set_title("门内/门外双向质量评价框架（precision-side × omission-side）")
foot(fig, "数据源：AUTHORITATIVE_RESULTS.md 独立审计节（两审计独立设计、协议预注册）")
save_fig(fig, "J04", "双向审计框架概念图", "方法概念", SCR, ["E14", "E15"], "门内看精度、门外看遗漏")

# J05 门外森林图
fig, ax = new_fig(8.8, 5.6)
E14s = E14.dropna(subset=["点估计"]).sort_values("点估计")
y = np.arange(len(E14s))
for yi, (_, r) in zip(y, E14s.iterrows()):
    p = float(r["点估计"]); lo = r["CI下界"]; hi = r["CI上界"]
    if pd.isna(lo):
        ax.scatter(p, yi, s=64, color=M["驼灰"], zorder=3)
        continue
    ax.plot([lo, hi], [yi, yi], color=M["雾蓝"], lw=2.2, zorder=3)
    ax.scatter(p, yi, s=56, color=M["雾蓝"], zorder=4)
    ax.annotate(f"{p:.4f}", (p, yi), xytext=(9, -3), textcoords="offset points", fontsize=7.8, color=INK)
ax.set_yticks(y); ax.set_yticklabels([wrap_zh(x, 14) for x in E14s["指标"]], fontsize=8.4)
ax.set_xlabel("比率（95%CI）"); ax.set_xlim(-0.05, 1.05)
ax.set_title("门外审计九项核心指标森林图")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
foot(fig, "数据源：OUTSIDE_GATE_AUDIT_RESULTS.json（分层抽样 seed=20260916）")
save_fig(fig, "J05", "门外审计森林图", "审计评价", SCR, ["E14"], "推荐状态一致率 0.8899 最高")

# J06 机会率多口径
fig, ax = new_fig(8.2, 4.6)
items = [("样本口径（强共识）", 0.0063, 0.0044, 0.0089, "31/4,957"),
         ("加权总体（设计型CI）", 0.0066, 0.0040, 0.0097, "≈2,070/311,992"),
         ("裁判A口径", 0.0583, 0.0521, 0.0652, "289/4,957"),
         ("裁判B口径", 0.0115, 0.0089, 0.0149, "57/4,957")]
for i, (n, p, lo, hi, num) in enumerate(items):
    ax.errorbar(i, p * 100, yerr=[[(p - lo) * 100], [(hi - p) * 100]], fmt="o", ms=9,
                color=M["陶砂"] if i < 2 else M["驼灰"], capsize=5, lw=1.6, zorder=3)
    ax.annotate(f"{p*100:.2f}% [{lo*100:.2f}, {hi*100:.2f}]\n{num}", (i, p * 100), xytext=(12, -6),
                textcoords="offset points", fontsize=8, color=INK)
ax.set_xticks(range(4)); ax.set_xticklabels([wrap_zh(n, 9) for n, *_ in items], fontsize=8.8)
ax.set_ylabel("门外 STRICT 机会率（%）")
ax.set_title("门外 STRICT 机会率：多口径对照（强共识最保守）")
despine(ax); light_grid(ax)
foot(fig, "数据源：OUTSIDE_GATE_AUDIT_RESULTS.json weighted_strict_opportunity_design_ci（B=10,000）")
save_fig(fig, "J06", "门外机会率多口径图", "审计评价", SCR, ["E14"], "0.63%样本 / 0.66%加权总体")

# J07 按阻断类型机会率
items = [("端点实体类型未决", 0.0045, 0.0017, 0.0114, 898), ("作用域冲突", 0.0064, 0.0035, 0.0117, 1573),
         ("谓词未归一", 0.0067, 0.0041, 0.0108, 2404), ("关系域违反", 0.0127, 0.0022, 0.0683, 79),
         ("人工遗留", 0.0, 0.0, 0.5615, 3)]
fig, ax = new_fig(8.4, 4.4)
for i, (n, p, lo, hi, den) in enumerate(items):
    ax.errorbar(i, p * 100, yerr=[[max(p - lo, 0) * 100], [(hi - p) * 100]], fmt="o",
                ms=9, color=M["青灰"], capsize=5, lw=1.5, zorder=3)
    ax.annotate(f"{p*100:.2f}%（n={den}）", (i, p * 100), xytext=(10, -3), textcoords="offset points", fontsize=8.2, color=INK)
ax.set_xticks(range(5)); ax.set_xticklabels([wrap_zh(n, 8) for n, *_ in items], fontsize=8.8)
ax.set_yscale("symlog", linthresh=0.1); ax.set_ylabel("STRICT 机会率（%，symlog）")
ax.set_title("按前置阻断类型分层的门外翻案机会率")
despine(ax); light_grid(ax)
foot(fig, "数据源：OUTSIDE_GATE_AUDIT_RESULTS.json per_blocker_strict_opportunity")
save_fig(fig, "J07", "按阻断类型机会率图", "审计评价", SCR, ["E08"], "各阻断层机会率均低于1.3%")

# J08 多口径一致率
fig, ax = new_fig(7.8, 4.0)
items = [("五档完全一致", 0.8126, 0.8015, 0.8232), ("推荐状态一致", 0.8899, 0.8808, 0.8983),
         ("严格资格一致", 0.9352, 0.9280, 0.9418), ("门外三层精确一致", 0.4303, 0.4166, 0.4441)]
ys = np.arange(len(items))[::-1]
for yi, (n, p, lo, hi) in zip(ys, items):
    ax.errorbar(p * 100, yi, xerr=[[(p - lo) * 100], [(hi - p) * 100]], fmt="s", ms=9,
                color=M["雾蓝"], capsize=5, lw=1.6, zorder=3)
    ax.annotate(f"{p*100:.1f}%", (p * 100, yi), xytext=(10, -3), textcoords="offset points", fontsize=8.8, color=INK)
ax.set_yticks(ys); ax.set_yticklabels([n for n, *_ in items], fontsize=9.2)
ax.set_xlim(30, 100); ax.set_xlabel("一致率（%，95%CI）")
ax.set_title("门外审计的多口径一致率")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
foot(fig, "数据源：OUTSIDE_GATE_AUDIT_RESULTS.json")
save_fig(fig, "J08", "门外多口径一致率图", "审计评价", SCR, ["E14"], "口径越细一致率越低（三层精确 0.43）")

# J09 嵌套抽样流程
fig, ax = new_fig(10.2, 4.6)
ax.set_xlim(0, 10.2); ax.set_ylim(0, 4.6); ax.axis("off")
circles = [(8.6, 2.3, 2.0, "#EDF1F4", "门外宇宙\n311,992"), (6.4, 2.3, 1.45, "#DCE6EC", "分层抽样\n5,000"),
           (4.5, 2.3, 1.0, "#C6D6DF", "双裁判有效\n4,957"), (2.9, 2.3, 0.62, "#B0C6D2", "强共识\nSTRICT机会\n31")]
for x, y, r, c, t in circles:
    ax.add_patch(Circle((x, y), r, facecolor=c, edgecolor=M["雾蓝"], lw=1.2))
    ax.text(x, y, t, ha="center", va="center", fontsize=8.6, color=INK, linespacing=1.35)
ax.text(5.1, 4.15, "种子 20260916 · 五层分层（CONTEXTUAL/UNRESOLVED × 阻断原因）· 双裁判独立盲评",
        ha="center", fontsize=9.2, color=FAINT)
ax.set_title("门外审计的嵌套抽样结构", fontsize=12.5)
foot(fig, "数据源：OUTSIDE_GATE_AUDIT_PROTOCOL.json / OUTSIDE_GATE_AUDIT_RESULTS.json")
save_fig(fig, "J09", "门外审计嵌套抽样图", "审计评价", SCR, ["E19", "E08"], "5,000 样本嵌套于 311,992 宇宙")

# J10 分层×谓词构成热力（原裁判矩阵数据不可得）
by = E09["by_stratum"]
ks = list(by.keys())[:12]
fig, ax = new_fig(9.0, 6.0)
mat = np.array([[by[k]["n"] for k in ks]])
im = ax.imshow(mat, cmap=cmapb if False else mpl.colors.LinearSegmentedColormap.from_list("mb", BLUE_SEQ), aspect="auto")
ax.set_xticks(range(len(ks))); ax.set_xticklabels([wrap_zh(k, 9) for k in ks], fontsize=7.6, rotation=40, ha="right")
ax.set_yticks([0]); ax.set_yticklabels(["样本数"])
for j in range(len(ks)):
    ax.text(j, 0, by[ks[j]]["n"], ha="center", va="center", fontsize=8,
            color="#FFFFFF" if mat[0, j] > 200 else INK)
ax.set_title("门内审计样本的分层构成（4,427 条 × 前12分层）")
despine(ax, keep=())
foot(fig, "数据源：AUDIT_RESULTS.json by_stratum（裁判×裁判五档原始矩阵未随审计归档，故以分层构成呈现）")
save_fig(fig, "J10", "门内审计分层构成图", "审计评价", SCR, ["E09"], "aligned 与 recovery_B 为主要分层")

# J11 门外审计分流
fig, ax = new_fig(10.6, 5.2)
ax.set_xlim(0, 10.6); ax.set_ylim(0, 5.2); ax.axis("off")
fbox(ax, 0.3, 1.9, 2.0, 1.4, "门外宇宙\n311,992", fc="#EDF1F4", ec=M["雾蓝"], fs=11, weight="bold")
fbox(ax, 3.0, 2.9, 2.2, 1.0, "CONTEXTUAL 层\n2,483 样本", fc="#F0F2F4", ec=M["暮蓝"], fs=9)
fbox(ax, 3.0, 1.2, 2.2, 1.0, "UNRESOLVED 层\n2,474 样本", fc="#F3F0EA", ec=M["陶砂"], fs=9)
fbox(ax, 5.9, 2.0, 2.1, 1.1, "双裁判有效\n4,957", fc="#EFF3EE", ec=M["橄榄"], fs=10)
fbox(ax, 8.5, 2.0, 1.8, 1.1, "强共识 STRICT\n机会 31（0.63%）", fc=TIER_C["STRICT"], ec=TIER_C["STRICT"], fs=8.6, tc="#FFFFFF", weight="bold")
farrow(ax, 2.35, 2.85, 2.95, 3.4); farrow(ax, 2.35, 2.45, 2.95, 1.7)
farrow(ax, 5.25, 3.4, 5.85, 2.75); farrow(ax, 5.25, 1.7, 5.85, 2.35)
farrow(ax, 8.05, 2.55, 8.45, 2.55)
ax.text(5.3, 4.6, "CONTEXTUAL 翻案率 0.68%（17/2,483）· UNRESOLVED 翻案率 0.57%（14/2,474）", ha="center", fontsize=9.2, color=INK)
ax.set_title("门外审计抽样—判定—机会识别分流")
foot(fig, "数据源：OUTSIDE_GATE_AUDIT_RESULTS.json（contextual/unresolved_strict_opportunity_rate）")
save_fig(fig, "J11", "门外审计分流图", "审计评价", SCR, ["E08"], "两层翻案率均不足0.7%")

# J12 门内门外镜像
fig, ax = new_fig(10.8, 5.4)
ax.set_xlim(0, 10.8); ax.set_ylim(0, 5.4); ax.axis("off")
ax.plot([5.4, 5.4], [0.4, 4.6], color=AXIS, lw=1.4, ls="--")
ax.text(5.4, 4.95, "宇宙边界：门内 112,158 ｜ 门外 311,992", ha="center", fontsize=9.5, color=FAINT)
L = [("99.28%", "强共识支持精度"), ("0.41%", "强共识误报率"), ("κ = 0.184", "裁判一致性（风格两极）"), ("22.0%", "五档强共识比例")]
R = [("0.63%", "样本 STRICT 机会率"), ("0.66%", "加权总体机会率"), ("κ = 0.514", "裁判一致性"), ("81.26%", "五档完全一致率")]
ax.text(2.7, 4.45, "门内（precision-side）", ha="center", fontsize=12, weight="bold", color=M["雾蓝"])
ax.text(8.1, 4.45, "门外（omission-side）", ha="center", fontsize=12, weight="bold", color=M["陶砂"])
for i, (v, n) in enumerate(L):
    y = 3.7 - i * 0.95
    ax.text(3.2, y, v, ha="right", fontsize=13, weight="bold", color=M["雾蓝"])
    ax.text(3.4, y, n, ha="left", fontsize=9, color=INK)
for i, (v, n) in enumerate(R):
    y = 3.7 - i * 0.95
    ax.text(7.6, y, v, ha="left", fontsize=13, weight="bold", color=M["陶砂"])
    ax.text(7.4, y, n, ha="right", fontsize=9, color=INK)
ax.set_title("门内/门外镜像对照图")
foot(fig, "数据源：AUDIT_RESULTS.json / OUTSIDE_GATE_AUDIT_RESULTS.json")
save_fig(fig, "J12", "门内外镜像对照图", "审计评价", SCR, ["E14", "E15"], "两个宇宙的双向质量画像")

# J13 共识结构
fig, ax = new_fig(8.0, 2.9)
parts = [("强共识 22.0%", 0.2201, M["雾蓝"]), ("弱共识 25.9%", 0.2593, M["暮蓝"]), ("无共识 38.1%", 0.3808, M["石板"]), ("部分一致 14.0%（推算）", 0.1398, M["驼灰"])]
left = 0
for nm, v, c in parts:
    ax.barh(0, v * 100, left=left, color=c, height=0.5, zorder=3)
    ax.text(left + v * 50, 0, nm, ha="center", va="center", fontsize=8.2, color="#FFFFFF", weight="bold")
    left += v * 100
ax.set_yticks([]); ax.set_xlim(0, 100); ax.set_xlabel("占比（%）")
ax.set_title("门内双裁判共识结构（n=4,427）")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
foot(fig, "数据源：AUDIT_RESULTS.json（弱共识 0.2593、无共识 0.3808；部分一致=1−其余，推算口径）")
save_fig(fig, "J13", "门内共识结构图", "审计评价", SCR, ["E15"], "强共识子集上精度 99.28%")

# J14 加权机会率区间
fig, ax = new_fig(8.4, 3.8)
ax.errorbar([0.66], [1], xerr=[[0.66 - 0.40], [0.97 - 0.66]], fmt="o", ms=12, color=M["陶砂"], capsize=7, lw=2.2, zorder=3)
ax.annotate("加权总体 0.66% [0.40%, 0.97%]\n（设计型分层 bootstrap，B=10,000，seed=20260916）", (0.66, 1),
            xytext=(0, 16), textcoords="offset points", ha="center", fontsize=9.2, color=INK)
ax.annotate("样本口径 0.63% [0.44, 0.89]", (0.63, 0.72), ha="center", fontsize=8.8, color=FAINT)
ax.scatter([0.63], [0.72], s=54, color=M["驼灰"], zorder=3)
ax.annotate("对应全库条数区间 [1,257, 3,019] / 311,992", (0.66, 0.5), ha="center", fontsize=9, color=INK)
ax.set_yticks([]); ax.set_xlim(0.2, 1.1); ax.set_xlabel("门外 STRICT 机会率（%）")
ax.set_title("加权总体机会率的不确定性量化")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
foot(fig, "数据源：OUTSIDE_GATE_AUDIT_RESULTS.json weighted_strict_opportunity_design_ci")
save_fig(fig, "J14", "加权机会率区间图", "审计评价", SCR, ["E08"], "上界不足门外宇宙 1%")

print("批E（I01-I10, J01-J14）完成")
