# -*- coding: utf-8 -*-
"""批B_图谱结构.py — B01–B16 图谱总体规模与结构（16张）"""
import sys, os, json, collections
sys.path.insert(0, r"D:\REDCULTUREDATA\可视化输出\10_生成脚本")
from style_lib import *
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import networkx as nx
import squarify
import adjustText as aj

MID = r"D:\REDCULTUREDATA\可视化输出\11_数据中间表"
SCR = "批B_图谱结构.py"
T02 = pd.read_csv(os.path.join(MID, "T02_实体类型分布.csv"))
T03 = pd.read_csv(os.path.join(MID, "T03_谓词分布.csv"))
T04 = pd.read_csv(os.path.join(MID, "T04_谓词规范化映射.csv"))
T12 = pd.read_csv(os.path.join(MID, "T12_实体度分布.csv"))
T13 = pd.read_csv(os.path.join(MID, "T13_高频实体Top150.csv"))
T21 = pd.read_csv(os.path.join(MID, "T21_关系契约88谓词.csv"))
T34 = pd.read_csv(os.path.join(MID, "T34_严格层边表31067.csv"))
TYPE_COLOR = {"Person": M["雾蓝"], "Event": M["陶砂"], "Place": M["青灰"], "Organization": M["橄榄"],
              "Concept": M["灰紫"], "Document": M["暮蓝"], "Institution": M["驼灰"], "Artifact": M["绛陶"],
              "TimePeriod": M["烟粉"], "AdministrativeRegion": M["石板"]}


# ---------- B01 实体类型树图 ----------
fig, ax = new_fig(9.6, 5.8)
sizes = T02["数量"].values
labels = [f"{ez(t)}\n{n:,}" for t, n in zip(T02["实体类型"], sizes)]
norm = mpl.colors.Normalize(vmin=0, vmax=len(sizes))
cmap = mpl.colors.LinearSegmentedColormap.from_list("mor", BLUE_SEQ)
squarify.plot(sizes=sizes, color=[cmap(norm(i)) for i in range(len(sizes))], label=labels, ax=ax, pad=True,
              text_kwargs={"fontsize": 8.6, "color": INK})
ax.axis("off"); ax.set_title("规范实体类型规模树图（152,979 实体，16 类）")
fig.text(0.01, 0.012, "数据源：research_entities（最终库）", fontsize=8, color=FAINT)
save_fig(fig, "B01", "实体类型规模树图", "图谱结构", SCR, ["T02"], "人物最多，事件与地点次之")

# ---------- B02 类型×验证状态旭日图 ----------
fig, ax = new_fig(8.2, 7.2, subplot_kw=dict(polar=True))
top8 = T02.head(8)
tvals = top8["数量"].values
tcol = SEQ10[:8]
inner_w = tvals / tvals.sum() * 2 * np.pi
pend_ratio = (top8["类型未决"] / top8["数量"]).fillna(0).values
left = 0
bars = ax.bar(x=[left + w / 2 for w in inner_w], height=0.42, width=inner_w, bottom=0.28,
              color=tcol, edgecolor="white", lw=1.2, align="edge")
for i, (l, w, t, n) in enumerate(zip([0] + list(np.cumsum(inner_w)[:-1]), inner_w, top8["实体类型"], tvals)):
    ax.text(l + w / 2, 0.49, f"{ez(t)} {n/10000:.1f}万", rotation=0, ha="center", fontsize=8.2, color=INK)
# 外环：每类型内分 已验证/未决 两段
for i, (l, w, r) in enumerate(zip([0] + list(np.cumsum(inner_w)[:-1]), inner_w, pend_ratio)):
    ax.bar(x=l, height=0.22, width=w * (1 - r), bottom=0.74, color=tcol[i], alpha=0.55, edgecolor="white", lw=0.8, align="edge")
    if r > 0.001:
        ax.bar(x=l + w * (1 - r), height=0.22, width=w * r, bottom=0.74, color=M["绛陶"], alpha=0.75,
               edgecolor="white", lw=0.8, align="edge")
ax.set_yticks([]); ax.set_xticks([])
ax.set_ylim(0, 1.05)
from matplotlib.patches import Patch
ax.legend(handles=[Patch(fc=M["雾蓝"], alpha=0.55, label="类型已验证"), Patch(fc=M["绛陶"], alpha=0.75, label="类型未决（4,762）")],
          loc="lower center", bbox_to_anchor=(0.5, -0.12), ncol=2)
ax.set_title("实体类型 × 类型验证状态（内环规模 / 外环验证构成）", pad=18)
fig.text(0.01, 0.012, "数据源：research_entities type_validation_status", fontsize=8, color=FAINT)
save_fig(fig, "B02", "实体类型验证状态旭日图", "图谱结构", SCR, ["T02"], "类型未决实体与严格计算隔离")

# ---------- B03 谓词长尾 log-log ----------
freq = T03["断言数"].sort_values(ascending=False).values
fig, ax = new_fig(7.0, 4.6)
ax.loglog(np.arange(1, len(freq) + 1), freq, color=M["雾蓝"], lw=1.6)
ax.set_xlabel("谓词排名（log）"); ax.set_ylabel("断言频次（log）")
ax.set_title("谓词频次长尾分布（12,885 个谓词形式）")
despine(ax); light_grid(ax, axis="both")
fig.text(0.01, 0.012, "数据源：research_assertions predicate（含 raw: 原始形式）", fontsize=8, color=FAINT)
save_fig(fig, "B03", "谓词频次长尾分布", "图谱结构", SCR, ["T03"], "头部谓词主导、尾部极长")

# ---------- B04 高频谓词 Top30 ----------
p = T03.copy(); p["raw"] = p["谓词"].astype(str).str.startswith("raw:")
top = p.sort_values("断言数", ascending=False).head(30)[::-1]
fig, ax = new_fig(7.6, 8.4)
ax.barh(range(len(top)), top["断言数"], color=[M["驼灰"] if r else M["雾蓝"] for r in top["raw"]], height=0.66, zorder=3)
ax.set_yticks(range(len(top))); ax.set_yticklabels([pz(x) for x in top["谓词"]], fontsize=8)
for i, v in enumerate(top["断言数"]):
    ax.annotate(f"{v:,}", (v, i), xytext=(5, 0), textcoords="offset points", va="center", fontsize=7.6, color=INK)
from matplotlib.patches import Patch
ax.legend(handles=[Patch(fc=M["雾蓝"], label="规范谓词"), Patch(fc=M["驼灰"], label="原始谓词（raw:）")], loc="lower right")
ax.set_xlabel("断言数"); ax.set_title("高频谓词 Top30（双色区分原始/规范）")
despine(ax); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：T03_谓词分布", fontsize=8, color=FAINT)
save_fig(fig, "B04", "高频谓词构成", "图谱结构", SCR, ["T03"], "未归一原始谓词占据头部的相当比例")

# ---------- B05 谓词规范化 Sankey ----------
t4 = T04.groupby(["原始谓词", "规范谓词"])["断言数"].sum().reset_index()
t4 = t4[t4["断言数"] >= 3000].sort_values("断言数", ascending=False).head(14)
lefts = collections.OrderedDict()
rights = collections.OrderedDict()
for _, r in t4.iterrows():
    lefts[str(r["原始谓词"])] = lefts.get(str(r["原始谓词"]), 0) + r["断言数"]
    rights[str(r["规范谓词"])] = rights.get(str(r["规范谓词"]), 0) + r["断言数"]
Ltot = sum(lefts.values()); Rtot = sum(rights.values())
fig, ax = new_fig(10.6, 7.6)
ax.set_xlim(0, 10.6); ax.set_ylim(0, 7.6); ax.axis("off")
def stack(d, x, gap=0.10):
    tot = sum(d.values()); y = 0.35; out = {}
    for k, v in d.items():
        h = (v / tot) * (7.6 - 0.7 - gap * (len(d) - 1))
        out[k] = (y, h); y += h + gap
    return out
Lp = stack(lefts, 0); Rp = stack(rights, 0)
lcol = {k: SEQ10[i % 10] for i, k in enumerate(lefts)}
for k, (y, h) in Lp.items():
    ax.add_patch(mpl.patches.Rectangle((0.5, y), 0.28, h, color=lcol[k], alpha=0.92))
    ax.text(0.42, y + h / 2, f"{pz(k)}  {lefts[k]:,}", ha="right", va="center", fontsize=8.4, color=INK)
for k, (y, h) in Rp.items():
    ax.add_patch(mpl.patches.Rectangle((9.8, y), 0.28, h, color=M["雾蓝"], alpha=0.92))
    ax.text(10.18, y + h / 2, f"{pz(k)}  {rights[k]:,}", ha="left", va="center", fontsize=8.4, color=INK)
for _, r in t4.iterrows():
    src = str(r["原始谓词"]); dst = str(r["规范谓词"])
    sy, sh = Lp[src]; dy, dh = Rp[dst]
    frac_src = r["断言数"] / lefts[src]; frac_dst = r["断言数"] / rights[dst]
    sy2 = sy + sh * frac_src; dy2 = dy + dh * frac_dst
    yl = sy + sh * (frac_src * 0 + 0)  # 起点按流厚
    ys = sy; yd = dy
    # 简化：按目标顺序排流带
    xs = np.linspace(0.78, 9.8, 120)
    s0 = sy + sh * frac_src; t0 = dy + dh * frac_dst
    yy = np.linspace(ys, yd, 120)
    ax.fill_between(xs, yy, yy + min(sh * frac_src, dh * frac_dst), color=lcol.get(src, M["雾蓝"]), alpha=0.30)
ax.set_title("原始谓词 → 规范谓词 映射流（Top 流量，≥3,000 条）")
fig.text(0.01, 0.012, "数据源：T04_谓词规范化映射（provenance 源谓词 × 断言谓词）", fontsize=8, color=FAINT)
save_fig(fig, "B05", "谓词规范化映射流", "图谱结构", SCR, ["T04"], "多支原始谓词向规范谓词收敛")

# ---------- B06 主语类型×谓词气泡矩阵 ----------
t14 = pd.read_csv(os.path.join(MID, "T14_主语类型×谓词矩阵.csv"))
piv = t14.pivot_table(index="谓词", columns="主语类型", values="断言数", aggfunc="sum").fillna(0)
piv = piv.loc[piv.sum(axis=1).sort_values(ascending=False).index[:15]]
piv = piv[piv.sum().sort_values(ascending=False).index[:8]]
fig, ax = new_fig(9.6, 6.4)
for yi, pred in enumerate(piv.index):
    for xi, st in enumerate(piv.columns):
        v = piv.loc[pred, st]
        if v <= 0: continue
        ax.scatter(xi, yi, s=20 + 240 * np.log10(1 + v), color=M["雾蓝"], alpha=0.75, zorder=3, edgecolors="white")
        if v > 3000:
            ax.annotate(f"{v/10000:.1f}万" if v > 10000 else f"{v:.0f}", (xi, yi), ha="center", va="center", fontsize=7, color="#FFFFFF")
ax.set_yticks(range(len(piv.index))); ax.set_yticklabels([pz(x) for x in piv.index], fontsize=8.4)
ax.set_xticks(range(len(piv.columns))); ax.set_xticklabels([ez(c) for c in piv.columns], fontsize=9)
ax.set_title("主语类型 × 谓词气泡矩阵（气泡 = 断言数）")
despine(ax); light_grid(ax, axis="both")
fig.text(0.01, 0.012, "数据源：T14_主语类型×谓词矩阵（≥200 条组合）", fontsize=8, color=FAINT)
save_fig(fig, "B06", "主语类型谓词气泡矩阵", "图谱结构", SCR, ["T14"], "人物-参与/领导、事件-发生于构成主体组合")

# ---------- B07 度分布 log-log ----------
mid_map = {"1": 1, "2": 2, "3-5": 4, "6-10": 8, "11-20": 15, "21-50": 35, "51-100": 75, ">100": 160}
xs = [mid_map[k] for k in T12["度区间"]]
fig, ax = new_fig(7.0, 4.6)
ax.loglog(xs, T12["实体数"], "o-", color=M["雾蓝"], lw=1.6, ms=6)
ax.set_xlabel("节点度（log，区间中值）"); ax.set_ylabel("实体数（log）")
ax.set_title("实体度分布（严格层 31,067 断言）")
despine(ax); light_grid(ax, axis="both")
fig.text(0.01, 0.012, "数据源：T12_实体度分布（由严格层边表统计）", fontsize=8, color=FAINT)
save_fig(fig, "B07", "实体度分布", "图谱结构", SCR, ["T12"], "绝大多数实体度≤5，少数枢纽度极高")

# ---------- B08 CCDF ----------
vals = []
for k, n in zip(T12["度区间"], T12["实体数"]):
    vals += [mid_map[k]] * n
vals = np.sort(np.array(vals))
n = len(vals)
ccdf = 1 - np.arange(1, n + 1) / n
fig, ax = new_fig(7.0, 4.6)
ax.loglog(vals, ccdf, color=M["陶砂"], lw=1.6)
ax.set_xlabel("节点度 d（log）"); ax.set_ylabel("P(D ≥ d)（log）")
ax.set_title("度分布互补累积函数（CCDF）")
despine(ax); light_grid(ax, axis="both")
fig.text(0.01, 0.012, "数据源：由 T12 度区间展开近似", fontsize=8, color=FAINT)
save_fig(fig, "B08", "度分布CCDF曲线", "图谱结构", SCR, ["T12"], "重尾特征明显")

# ---------- B09 高频实体 Top30 棒棒糖 ----------
t13 = T13.head(30)[::-1]
fig, ax = new_fig(7.4, 8.6)
cols = [TYPE_COLOR.get(t, M["石板"]) for t in t13["类型"]]
ax.hlines(range(len(t13)), 0, t13["度"], color=[c for c in cols], lw=1.6, alpha=0.7)
ax.scatter(t13["度"], range(len(t13)), s=64, color=cols, zorder=3)
for i, (nm, d) in enumerate(zip(t13["实体名"], t13["度"])):
    ax.annotate(f"{nm}  {d}", (d, i), xytext=(6, 0), textcoords="offset points", va="center", fontsize=7.8, color=INK)
ax.set_xlabel("节点度"); ax.set_yticks([])
ax.set_title("高频实体 Top30（颜色 = 类型）")
handles = [plt.Line2D([], [], marker="o", ls="", color=TYPE_COLOR[t], label=ez(t)) for t in ["Person", "Organization", "Place", "Event"] if t in set(T13.head(30)["类型"])]
ax.legend(handles=handles, loc="lower right")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：T13_高频实体Top150", fontsize=8, color=FAINT)
save_fig(fig, "B09", "高频实体Top30棒棒糖图", "图谱结构", SCR, ["T13"], "枢纽以人物与地名为主")


# ---------- B10 严格层核心网络 ----------
deg = collections.Counter()
for s in T34["主体ID"]: deg[s] += 1
for o in T34["客体ID"]: deg[o] += 1
topn = {e for e, _ in sorted(deg.items(), key=lambda kv: -kv[1])[:150]}
sub = T34[T34["主体ID"].isin(topn) & T34["客体ID"].isin(topn)]
G = nx.from_pandas_edgelist(sub, "主体ID", "客体ID", create_using=nx.Graph())
G = G.subgraph([n for n in G.nodes if n in topn]).copy()
name = dict(zip(T34["主体ID"], T34["主体名"])); name.update(dict(zip(T34["客体ID"], T34["客体名"])))
typ = dict(zip(T34["主体ID"], T34["主体类型"])); typ.update(dict(zip(T34["客体ID"], T34["客体类型"])))
fig, ax = new_fig(11, 7.6)
pos = nx.spring_layout(G, seed=42, k=0.30)
for u, v in G.edges():
    ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]], color=GRID, lw=0.5, alpha=0.6, zorder=1)
dg = dict(G.degree())
for n_ in G.nodes:
    ax.scatter(*pos[n_], s=14 + 3.2 * dg[n_], color=TYPE_COLOR.get(typ.get(n_, ""), M["石板"]),
               zorder=3, edgecolors="white", linewidths=0.5)
lab = sorted(dg, key=dg.get, reverse=True)[:22]
texts = [ax.annotate(name.get(n_, n_), pos[n_], fontsize=8, color=INK, zorder=4) for n_ in lab]
aj.adjust_text(texts, ax=ax, arrowprops=dict(arrowstyle="-", color=FAINT, lw=0.5))
ax.set_title("严格层核心实体网络（度 Top150 诱导子图）"); ax.axis("off")
handles = [plt.Line2D([], [], marker="o", ls="", color=TYPE_COLOR[t], label=ez(t)) for t in TYPE_COLOR if t in set(typ.values())]
ax.legend(handles=handles, loc="upper left", fontsize=8.4)
fig.text(0.01, 0.012, "数据源：T34_严格层边表31067（networkx spring_layout, seed=42）", fontsize=8, color=FAINT)
save_fig(fig, "B10", "严格层核心实体网络", "图谱结构", SCR, ["T34"], "人物-地名-组织枢纽结构清晰")

# ---------- B11 连通分量 ----------
comps = sorted((len(c) for c in nx.connected_components(G)), reverse=True)
fig, ax = new_fig(7.2, 4.4)
ax.bar(range(min(len(comps), 20)), comps[:20], color=M["青灰"], width=0.62, zorder=3)
ax.set_yscale("log"); ax.set_xlabel("分量序号（按规模）"); ax.set_ylabel("节点数（log）")
ax.set_title(f"核心子图连通分量（最大 {comps[0]} 节点，共 {len(comps)} 个）")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：B10 同一子图统计", fontsize=8, color=FAINT)
save_fig(fig, "B11", "连通分量规模分布", "图谱结构", SCR, ["T34"], "单一主分量主导")

# ---------- B12 社区结构 ----------
com = list(nx.community.greedy_modularity_communities(G))
com = sorted(com, key=len, reverse=True)[:8]
fig, ax = new_fig(11, 7.6)
for u, v in G.edges():
    ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]], color=GRID, lw=0.5, alpha=0.6, zorder=1)
for ci, c in enumerate(com):
    for n_ in c:
        ax.scatter(*pos[n_], s=12 + 2.6 * dg.get(n_, 1), color=SEQ10[ci % 10], zorder=3, edgecolors="white", linewidths=0.4)
    cx = np.mean([pos[n_][0] for n_ in c]); cy = np.mean([pos[n_][1] for n_ in c])
    main_type = collections.Counter(typ.get(n_) for n_ in c).most_common(1)[0][0]
    ax.annotate(f"社区{ci+1}·以{ez(main_type)}为主", (cx, cy), fontsize=9, color=INK, ha="center",
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=AXIS, lw=0.7, alpha=0.85), zorder=5)
ax.set_title(f"核心子图社区结构（greedy modularity，前 8 社区）"); ax.axis("off")
fig.text(0.01, 0.012, "数据源：T34 同一子图，networkx greedy_modularity_communities", fontsize=8, color=FAINT)
save_fig(fig, "B12", "核心子图社区结构", "图谱结构", SCR, ["T34"], "社区对应地域与主题聚集")

# ---------- B13 度 vs 介数 ----------
bt = nx.betweenness_centrality(G, k=min(200, len(G)), seed=42)
nodes300 = sorted(dg, key=dg.get, reverse=True)[:300]
fig, ax = new_fig(7.4, 5.2)
for n_ in nodes300:
    ax.scatter(dg[n_], max(bt[n_], 1e-5), s=18 + dg[n_] * 1.2, color=TYPE_COLOR.get(typ.get(n_, ""), M["石板"]),
               alpha=0.75, zorder=3, edgecolors="none")
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlabel("节点度（log）"); ax.set_ylabel("介数中心性（log）")
ax.set_title("度与介数中心性的关系（Top300 节点）")
despine(ax); light_grid(ax, axis="both")
fig.text(0.01, 0.012, "数据源：T34 子图，近似介数（k=200, seed=42）", fontsize=8, color=FAINT)
save_fig(fig, "B13", "度与介数中心性散点", "图谱结构", SCR, ["T34"], "高介数枢纽桥接多个社区")

# ---------- B14 关系契约定义域值域热力 ----------
import ast as _ast
pairs = collections.Counter()
for _, r in T21.iterrows():
    try:
        ds = _ast.literal_eval(r["定义域类型"]); ts = _ast.literal_eval(r["值域类型"])
    except Exception:
        continue
    for d in ds:
        for t in ts:
            pairs[(ez(d), ez(t))] += 1
rows_ = sorted({k[0] for k in pairs}); cols_ = sorted({k[1] for k in pairs})
mat = np.zeros((len(rows_), len(cols_)))
for (d, t), c in pairs.items():
    mat[rows_.index(d), cols_.index(t)] = c
fig, ax = new_fig(9.2, 6.6)
cmapb = mpl.colors.LinearSegmentedColormap.from_list("mb", BLUE_SEQ)
im = ax.imshow(mat, cmap=cmapb, aspect="auto")
ax.set_xticks(range(len(cols_))); ax.set_xticklabels(cols_, fontsize=8, rotation=38, ha="right")
ax.set_yticks(range(len(rows_))); ax.set_yticklabels(rows_, fontsize=8.4)
for i in range(len(rows_)):
    for j in range(len(cols_)):
        if mat[i, j] > 0:
            ax.text(j, i, int(mat[i, j]), ha="center", va="center", fontsize=7.6,
                    color="#FFFFFF" if mat[i, j] > mat.max() * 0.55 else INK)
ax.set_xlabel("值域类型"); ax.set_ylabel("定义域类型")
ax.set_title("88 个关系契约的类型组合分布")
cb = fig.colorbar(im, ax=ax, shrink=0.8); cb.set_label("契约谓词数", fontsize=9)
despine(ax, keep=())
fig.text(0.01, 0.012, "数据源：research_relation_contract（多类型展开计数）", fontsize=8, color=FAINT)
save_fig(fig, "B14", "关系契约类型组合热力图", "图谱结构", SCR, ["T21"], "人物→组织与人物→事件为主要契约方向")

# ---------- B15 实体类型填充圆 ----------
t15 = T02.head(10).reset_index(drop=True)
fig, ax = new_fig(9.6, 5.6)
areas = t15["数量"].values
radii = np.sqrt(areas / areas.max()) * 1.0
xs, ys = [], []
cx = 0.0; cy = 0.0; rowh = 0.0
placed = []
for i, r in enumerate(radii):
    if i == 0:
        xs.append(0); ys.append(0); placed.append(r); rowh = 2 * r; cx = r
        continue
    cx += r + placed[-1] + 0.06
    if cx > 4.4:
        cx = r; cy -= (rowh + 0.12); rowh = 2 * r
    xs.append(cx); ys.append(cy); placed.append(r)
for i, r in enumerate(t15.itertuples()):
    ax.add_patch(plt.Circle((xs[i], ys[i]), radii[i], color=SEQ10[i % 10], alpha=0.85))
    ax.annotate(f"{ez(r.实体类型)}\n{r.数量:,}", (xs[i], ys[i]), ha="center", va="center", fontsize=8.2,
                color="#FFFFFF" if radii[i] > 0.4 else INK)
ax.set_xlim(-1.2, 5.4); ax.set_ylim(-2.6, 1.6)
ax.set_aspect("equal"); ax.axis("off")
ax.set_title("实体类型规模填充圆（Top10，面积∝数量）")
fig.text(0.01, 0.012, "数据源：T02_实体类型分布", fontsize=8, color=FAINT)
save_fig(fig, "B15", "实体类型填充圆", "图谱结构", SCR, ["T02"], "与树图互为备选编码")

# ---------- B16 高频谓词三层哑铃 ----------
t34p = T34.copy()
pred_order = t34p["谓词"].value_counts().head(12).index
rows16 = []
for pr in pred_order:
    sub = t34p[t34p["谓词"] == pr]
    tot = len(sub)
    strict = (sub["主体名"].notna()).sum()  # 全部为严格层
    rows16.append((pr, tot))
# 严格层边表本身全是严格层 → 需与全库谓词频次对比：取 T03 规范谓词频次 vs 严格层频次
t03c = T03[~T03["谓词"].astype(str).str.startswith("raw:")].set_index("谓词")["断言数"]
strict_cnt = T34["谓词"].value_counts()
rows16 = []
for pr in pred_order:
    total = t03c.get(pr, 0); st = strict_cnt.get(pr, 0)
    if total > 0:
        rows16.append((pz(pr), st / total * 100, 100))
fig, ax = new_fig(7.8, 6.2)
y = np.arange(len(rows16))
ax.hlines(y, [r[1] for r in rows16], [r[2] for r in rows16], color=GRID, lw=2.6, zorder=2)
ax.scatter([r[1] for r in rows16], y, s=64, color=TIER_C["STRICT"], zorder=3, label="严格层占比")
ax.scatter([r[2] for r in rows16], y, s=64, color=M["驼灰"], zorder=3, label="全库（=100%）")
for i, r in enumerate(rows16):
    ax.annotate(f"{r[1]:.1f}%", (r[1], i), xytext=(7, 0), textcoords="offset points", va="center", fontsize=8, color=INK)
ax.set_yticks(y); ax.set_yticklabels([r[0] for r in rows16], fontsize=8.6)
ax.set_xlabel("占全库同谓词断言比例（%）"); ax.set_xlim(-2, 112)
ax.set_title("高频谓词的严格层转化率（哑铃图）")
ax.legend(loc="lower right")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：T03（全库规范谓词）× T34（严格层）", fontsize=8, color=FAINT)
save_fig(fig, "B16", "高频谓词严格层转化率哑铃图", "图谱结构", SCR, ["T03", "T34"], "不同谓词的证据支持强度差异显著")

print("批B（B01-B16）完成")
