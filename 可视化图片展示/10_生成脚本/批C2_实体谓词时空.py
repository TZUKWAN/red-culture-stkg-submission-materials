# -*- coding: utf-8 -*-
"""批C2_实体谓词时空.py — C01–C10 实体层（10张）+ D01–D08 谓词关系（8张）+ E01–E16 时空（16张）"""
import sys, os, json, collections
sys.path.insert(0, r"D:\REDCULTUREDATA\可视化输出\10_生成脚本")
from style_lib import *
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import networkx as nx

MID = r"D:\REDCULTUREDATA\可视化输出\11_数据中间表"
SCR = "批C2_实体谓词时空.py"
TYPE_COLOR = {"Person": M["雾蓝"], "Event": M["陶砂"], "Place": M["青灰"], "Organization": M["橄榄"],
              "Concept": M["灰紫"], "Document": M["暮蓝"], "Institution": M["驼灰"], "Artifact": M["绛陶"],
              "TimePeriod": M["烟粉"], "AdministrativeRegion": M["石板"]}
T01 = pd.read_csv(os.path.join(MID, "T01_省域断言统计.csv"))
T02 = pd.read_csv(os.path.join(MID, "T02_实体类型分布.csv"))
T03 = pd.read_csv(os.path.join(MID, "T03_谓词分布.csv"))
T05 = pd.read_csv(os.path.join(MID, "T05_断言时间年分布.csv"))
T13 = pd.read_csv(os.path.join(MID, "T13_高频实体Top150.csv"))
T16 = pd.read_csv(os.path.join(MID, "T16_历史阶段×省域时空格.csv"))
T17 = pd.read_csv(os.path.join(MID, "T17_事件框架全表.csv"))
T18 = pd.read_csv(os.path.join(MID, "T18_地点版本演化.csv"))
T19 = pd.read_csv(os.path.join(MID, "T19_事件关系.csv"))
T20 = pd.read_csv(os.path.join(MID, "T20_作用域调整汇总.csv"))
T22 = pd.read_csv(os.path.join(MID, "T22_文化状态统计.csv"))
T23 = pd.read_csv(os.path.join(MID, "T23_身份决议794.csv"))
T24 = pd.read_csv(os.path.join(MID, "T24_名称聚类规模.csv"))
T25 = pd.read_csv(os.path.join(MID, "T25_标签投票来源.csv"))
T27 = pd.read_csv(os.path.join(MID, "T27_语义冲突类型.csv"))
T28 = pd.read_csv(os.path.join(MID, "T28_时序关系类型.csv"))
T32 = pd.read_csv(os.path.join(MID, "T32_人物活跃年份.csv"))
T34 = pd.read_csv(os.path.join(MID, "T34_严格层边表31067.csv"))
T36 = pd.read_csv(os.path.join(MID, "T36_大事件Top30.csv"))
T37 = pd.read_csv(os.path.join(MID, "T37_风险层分布.csv"))
T37b = pd.read_csv(os.path.join(MID, "T37b_置信度分布.csv"))
T38 = pd.read_csv(os.path.join(MID, "T38_流域分段统计.csv"))
E20 = pd.read_csv(os.path.join(MID, "E20_论文表1_资料列表.csv"))

# ============ C 实体层 ============
def c_bar(fid, zh, df, valcol, labcol, color, note, xl="度"):
    fig, ax = new_fig(7.2, 6.6)
    d = df[::-1]
    ax.barh(range(len(d)), d[valcol], color=color, height=0.62, zorder=3)
    ax.set_yticks(range(len(d))); ax.set_yticklabels([wrap_zh(x, 10) for x in d[labcol]], fontsize=8.6)
    for i, v in enumerate(d[valcol]):
        ax.annotate(f"{v:,}", (v, i), xytext=(5, 0), textcoords="offset points", va="center", fontsize=8, color=INK)
    ax.set_xlabel(xl)
    despine(ax); light_grid(ax, axis="x")
    fig.text(0.01, 0.012, "数据源：T13_高频实体Top150 / T36_大事件Top30", fontsize=8, color=FAINT)
    save_fig(fig, fid, zh, "实体层", SCR, ["T13"], note)

for fid, zh, tp, col in [("C01", "高频人物Top20", "Person", M["雾蓝"]), ("C02", "高频组织Top20", "Organization", M["橄榄"]),
                          ("C03", "高频地点Top20", "Place", M["青灰"])]:
    sub = T13[T13["类型"] == tp].head(20)
    c_bar(fid, zh, sub, "度", "实体名", col, f"{ez(tp)}枢纽排行（严格层度）")

sub = T36.head(20)[::-1]
fig, ax = new_fig(7.2, 6.8)
ax.barh(range(len(sub)), sub["严格断言数"], color=M["陶砂"], height=0.62, zorder=3)
ax.set_yticks(range(len(sub))); ax.set_yticklabels([wrap_zh(x, 10) for x in sub["事件名"]], fontsize=8.6)
for i, v in enumerate(sub["严格断言数"]):
    ax.annotate(f"{v}", (v, i), xytext=(5, 0), textcoords="offset points", va="center", fontsize=8, color=INK)
ax.set_xlabel("严格断言数"); despine(ax); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：T36_大事件Top30", fontsize=8, color=FAINT)
save_fig(fig, "C04", "高频事件Top20", "实体层", SCR, ["T36"], "事件框架规模排行")

# C05 名称聚类规模
fig, ax = new_fig(7.0, 4.4)
ax.bar(T24["成员数"].head(12), T24["聚类数"].head(12), color=M["灰紫"], width=0.62, zorder=3)
ax.set_yscale("log"); ax.set_xlabel("聚类成员数"); ax.set_ylabel("聚类数（log）")
ax.set_title("跨来源名称聚类规模分布（3,094 个聚类）")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：v2_name_clusters（语义集成库）", fontsize=8, color=FAINT)
save_fig(fig, "C05", "名称聚类规模分布", "实体层", SCR, ["T24"], "绝大多数聚类为2-3成员")

# C06 身份决议方式
fig, ax = new_fig(7.4, 4.6)
rescol = [c for c in T23.columns if "resolution" in c.lower() or "决定" in c or "方式" in c]
if rescol:
    vc = T23[rescol[0]].value_counts().head(10)
    ax.barh([wrap_zh(str(x), 12) for x in vc.index][::-1], vc.values[::-1], color=SEQ10[:len(vc)][::-1], height=0.62, zorder=3)
    for i, v in enumerate(vc.values[::-1]):
        ax.annotate(f"{v}", (v, i), xytext=(5, 0), textcoords="offset points", va="center", fontsize=8.4, color=INK)
else:
    ax.text(0.5, 0.5, "T23 无决议方式列", ha="center")
ax.set_xlabel("决议条数")
ax.set_title("实体身份决议构成（794 项投影决议）")
despine(ax); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：v2_identity_resolutions", fontsize=8, color=FAINT)
save_fig(fig, "C06", "身份决议方式构成", "实体层", SCR, ["T23"], "规范投影全部收敛到自映射代表元")

# C07 语义冲突类型
fig, ax = new_fig(7.6, 4.8)
vc = T27.head(10)
ax.barh([wrap_zh(str(x), 12) for x in vc["冲突类型"]][::-1], vc["数量"][::-1], color=SAND_SEQ[:len(vc)][::-1], height=0.62, zorder=3)
for i, v in enumerate(vc["数量"][::-1]):
    ax.annotate(f"{v:,}", (v, i), xytext=(5, 0), textcoords="offset points", va="center", fontsize=8.4, color=INK)
ax.set_xscale("log"); ax.set_xlabel("冲突数（log）")
ax.set_title("构建期语义冲突类型分布（74,636 条）")
despine(ax); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：v2_semantic_conflicts", fontsize=8, color=FAINT)
save_fig(fig, "C07", "语义冲突类型分布", "实体层", SCR, ["T27"], "时间冲突与端点未决为主")

# C08 标签投票来源热力
pv = T25.pivot_table(index="标注函数", columns="单元类型", values="票数", aggfunc="sum").fillna(0)
fig, ax = new_fig(8.6, 5.2)
cmapg = mpl.colors.LinearSegmentedColormap.from_list("mg", GREEN_SEQ)
im = ax.imshow(np.log10(pv.values + 1), cmap=cmapg, aspect="auto")
ax.set_xticks(range(len(pv.columns))); ax.set_xticklabels([wrap_zh(c, 8) for c in pv.columns], fontsize=8, rotation=28, ha="right")
ax.set_yticks(range(len(pv.index))); ax.set_yticklabels([wrap_zh(str(x), 16) for x in pv.index], fontsize=7.6)
for i in range(len(pv.index)):
    for j in range(len(pv.columns)):
        v = pv.values[i, j]
        if v > 0:
            ax.text(j, i, f"{v/10000:.1f}万" if v > 10000 else f"{v:.0f}", ha="center", va="center", fontsize=7,
                    color="#FFFFFF" if v > pv.values.max() * 0.5 else INK)
ax.set_title("标签投票来源构成（841,097 票，色=log10 票数）")
cb = fig.colorbar(im, ax=ax, shrink=0.8); cb.set_label("log10(票数)", fontsize=9)
despine(ax, keep=())
fig.text(0.01, 0.012, "数据源：v2_label_votes", fontsize=8, color=FAINT)
save_fig(fig, "C08", "标签投票来源热力图", "实体层", SCR, ["T25"], "规则/词法/模型三类标注函数的票数结构")

# C09 高频实体类型构成对比
topT = T13.head(150)["类型"].value_counts()
avgd = T13.head(150).groupby("类型")["度"].mean()
fig, ax = new_fig(7.6, 4.8)
xs = np.arange(len(topT))
ax.bar(xs, topT.values, color=[TYPE_COLOR.get(t, M["石板"]) for t in topT.index], width=0.6, zorder=3, alpha=0.9)
for x, (t, c) in zip(xs, topT.items()):
    ax.annotate(f"平均度\n{avgd[t]:.0f}", (x, c), xytext=(0, 6), textcoords="offset points", ha="center", fontsize=7.4, color=FAINT)
ax.set_xticks(xs); ax.set_xticklabels([ez(t) for t in topT.index], fontsize=8.6)
ax.set_ylabel("Top150 高频实体数"); ax.set_ylim(0, max(topT.values) * 1.22)
ax.set_title("高频实体的类型构成与平均度")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：T13_高频实体Top150", fontsize=8, color=FAINT)
save_fig(fig, "C09", "高频实体类型构成对比", "实体层", SCR, ["T13"], "枢纽实体中人物与地名占绝对多数")

# C10 人物活跃年份山脊图
top8p = T32["人物"].value_counts().head(8).index
years = np.arange(1900, 1951)
fig, ax = new_fig(8.8, 6.4)
for i, p_ in enumerate(top8p):
    pp = T32[T32["人物"] == p_].set_index("年")["断言数"].reindex(years, fill_value=0).values.astype(float)
    if pp.max() == 0: continue
    dens = np.convolve(pp, np.ones(5) / 5, mode="same")
    base = i * 1.0
    ax.fill_between(years, base, base + dens / dens.max() * 0.9, color=SEQ10[i % 10], alpha=0.55, zorder=i + 1)
    ax.plot(years, base + dens / dens.max() * 0.9, color=SEQ10[i % 10], lw=1.1, zorder=i + 2)
    ax.annotate(wrap_zh(p_, 8), (1901, base + 0.30), fontsize=8.4, color=INK, va="center", zorder=10)
ax.set_xlabel("年份"); ax.set_yticks([])
ax.set_xlim(1900, 1950)
ax.set_title("高频人物活跃年份山脊图（断言数年度分布，Top8 人物）")
despine(ax, keep=("bottom",))
fig.text(0.01, 0.012, "数据源：T32_人物活跃年份（严格层时间可达断言）", fontsize=8, color=FAINT)
save_fig(fig, "C10", "高频人物活跃年份山脊图", "实体层", SCR, ["T32"], "人物活跃高峰与革命时期高度吻合")

# ============ D 谓词与关系 ============
# D01 规范化覆盖率点图
p = T03.copy(); p["raw"] = p["谓词"].astype(str).str.startswith("raw:")
g = p.groupby("谓词").agg(总数=("断言数", "sum"))
rawc = p[p["raw"]].set_index("谓词")["断言数"]
g["rawn"] = [rawc.get(idx, 0) if not idx.startswith("raw:") else 0 for idx in g.index]
# 聚合到规范谓词层：把 raw:X 的数量并入 X
canon = collections.Counter()
for name_, tot in g["总数"].items():
    key = name_[4:] if name_.startswith("raw:") else name_
    canon[key] += tot
raws = collections.Counter()
for name_ in g.index:
    if name_.startswith("raw:"):
        raws[name_[4:]] += g.loc[name_, "总数"]
topc = sorted(canon, key=canon.get, reverse=True)[:20]
rates = [100 * (1 - raws.get(k, 0) / canon[k]) for k in topc]
fig, ax = new_fig(7.4, 6.4)
y = np.arange(len(topc))[::-1]
ax.scatter(rates, y, s=[30 + 100 * np.log10(1 + canon[k]) for k in topc], color=M["雾蓝"], zorder=3)
for yi, (k, r) in enumerate(zip(topc, rates)):
    ax.annotate(f"{r:.0f}%", (r, yi), xytext=(8, 0), textcoords="offset points", va="center", fontsize=7.8, color=INK)
ax.set_yticks(y); ax.set_yticklabels([pz(k) for k in topc], fontsize=8.4)
ax.set_xlabel("规范化覆盖率（非原始形式占比，%）"); ax.set_xlim(-6, 112)
ax.set_title("高频谓词的规范化覆盖率（气泡=总断言量）")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：T03_谓词分布（raw: 前缀归并统计）", fontsize=8, color=FAINT)
save_fig(fig, "D01", "谓词规范化覆盖率点图", "谓词关系", SCR, ["T03"], "头部谓词覆盖不均，关联类谓词大量残留原始形式")

# D02 未归一原始谓词 Top20
rawp = p[p["raw"]].sort_values("断言数", ascending=False).head(20)[::-1]
fig, ax = new_fig(7.4, 6.6)
ax.barh(range(len(rawp)), rawp["断言数"], color=M["驼灰"], height=0.62, zorder=3)
ax.set_yticks(range(len(rawp))); ax.set_yticklabels([pz(x) for x in rawp["谓词"]], fontsize=8.2)
for i, v in enumerate(rawp["断言数"]):
    ax.annotate(f"{v:,}", (v, i), xytext=(5, 0), textcoords="offset points", va="center", fontsize=7.8, color=INK)
ax.set_xlabel("断言数")
ax.set_title("未归一原始谓词 Top20（上下文层主要来源）")
despine(ax); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：T03_谓词分布", fontsize=8, color=FAINT)
save_fig(fig, "D02", "未归一原始谓词构成", "谓词关系", SCR, ["T03"], "原始·关联一项即 6.9 万条")

# D03 主语→宾语类型冲积图
flows = collections.Counter()
for s, o in zip(T34["主体类型"], T34["客体类型"]):
    flows[(s, o)] += 1
topf = flows.most_common(10)
fig, ax = new_fig(10.2, 6.8)
ax.set_xlim(0, 10.2); ax.set_ylim(0, 6.8); ax.axis("off")
lt = collections.OrderedDict(); rt = collections.OrderedDict()
for (s, o), w in topf:
    lt[ez(s)] = lt.get(ez(s), 0) + w
    rt[ez(o)] = rt.get(ez(o), 0) + w
ltot = sum(lt.values()); rtot = sum(rt.values())
def vstack(d, tot, x0=0.35, x1=9.85, H=5.6, gap=0.09):
    y = 0.5; pos_ = {}
    for k, v in d.items():
        h = v / tot * (H - gap * (len(d) - 1))
        pos_[k] = (y, h); y += h + gap
    return pos_
Lp = vstack(lt, ltot); Rp = vstack(rt, rtot)
for k, (y, h) in Lp.items():
    ax.add_patch(mpl.patches.FancyBboxPatch((0.35, y), 0.62, h, boxstyle="round,pad=0.02", color=SEQ10[0], alpha=0.9))
    ax.text(0.30, y + h / 2, f"{k} {lt[k]:,}", ha="right", va="center", fontsize=8.6, color=INK)
for k, (y, h) in Rp.items():
    ax.add_patch(mpl.patches.FancyBboxPatch((9.25, y), 0.62, h, boxstyle="round,pad=0.02", color=M["陶砂"], alpha=0.9))
    ax.text(9.95, y + h / 2, f"{k} {rt[k]:,}", ha="left", va="center", fontsize=8.6, color=INK)
for (s, o), w in topf:
    es, eo = ez(s), ez(o)
    sy, sh = Lp[es]; dy, dh = Rp[eo]
    fs = w / lt[es]; fd = w / rt[eo]
    sy2 = sy + sh * fs; dy2 = dy + dh * fd
    xs = np.linspace(0.97, 9.25, 100)
    yy = 0.5 * (sy2 + dy2) - 0.5 * (sy2 - dy2) * np.cos(np.pi * (xs - 0.97) / (9.25 - 0.97))
    ax.fill_between(xs, yy, yy + min(sh * fs, dh * fd), color=SEQ10[0], alpha=0.28)
ax.set_title("严格层主语类型 → 宾语类型组合冲积图（Top10 组合）")
fig.text(0.01, 0.012, "数据源：T34_严格层边表31067", fontsize=8, color=FAINT)
save_fig(fig, "D03", "类型组合冲积图", "谓词关系", SCR, ["T34"], "人物→组织与人物→事件是知识骨架")

# D04 谓词共现网络
G = nx.Graph()
pc = collections.Counter()
bysub = collections.defaultdict(set)
for s, pr in zip(T34["主体ID"], T34["谓词"]):
    bysub[s].add(pr)
for s, prs in bysub.items():
    prs = sorted(prs)
    for i in range(len(prs)):
        for j in range(i + 1, len(prs)):
            pc[(prsi := prs[i], prs[j])] += 1
toppc = pc.most_common(40)
for (a, b), w in toppc:
    G.add_edge(pz(a), pz(b), w=w)
fig, ax = new_fig(10.2, 7.2)
pos = nx.spring_layout(G, seed=13, k=0.42)
wg = dict(G.degree(weight="w"))
for u, v, d in G.edges(data=True):
    ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]], color=AXIS, lw=0.4 + 0.5 * np.log1p(d["w"]), alpha=0.55, zorder=1)
for n_ in G.nodes:
    ax.scatter(*pos[n_], s=50 + 6 * wg.get(n_, 1), color=M["雾蓝"], zorder=3, edgecolors="white", linewidths=0.6)
lab = sorted(wg, key=wg.get, reverse=True)[:18]
for n_ in lab:
    ax.annotate(n_, pos[n_], fontsize=8.4, color=INK, xytext=(0, 8), textcoords="offset points", ha="center")
ax.set_title("谓词共现网络（同一主体上的谓词对，Top40 边）")
ax.axis("off")
fig.text(0.01, 0.012, "数据源：T34_严格层边表31067", fontsize=8, color=FAINT)
save_fig(fig, "D04", "谓词共现网络", "谓词关系", SCR, ["T34"], "参与/隶属/发生于构成共现核心")

# D05 时序关系类型
t28 = T28.sort_values("数量")
fig, ax = new_fig(7.4, 4.6)
tm = {"equals": "同一时刻", "after": "之后", "before": "之前", "contains": "包含", "during": "期间",
      "overlaps": "重叠", "meets": "相接", "starts": "开始", "ends": "结束"}
ax.barh([tm.get(k, k) for k in t28["时序关系类型"]], t28["数量"] / 10000, color=BLUE_SEQ[2:2+len(t28)][::-1], height=0.62, zorder=3)
for i, v in enumerate(t28["数量"]):
    ax.annotate(f"{v:,}", (v / 10000, i), xytext=(5, 0), textcoords="offset points", va="center", fontsize=8, color=INK)
ax.set_xlabel("关系对数（百万）")
ax.set_title("断言间时序关系类型分布（563.6 万对）")
despine(ax); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：assertion_temporal_relations（最终库全表聚合）", fontsize=8, color=FAINT)
save_fig(fig, "D05", "时序关系类型分布", "谓词关系", SCR, ["T28"], "同一时刻与先后关系占九成")

# D06 事件关系类型
vc = T19["关系"].value_counts()
fig, ax = new_fig(7.2, 4.4)
ax.bar([str(x) for x in vc.index], vc.values, color=[SEQ10[i % 10] for i in range(len(vc))], width=0.58, zorder=3)
for i, v in enumerate(vc.values):
    ax.annotate(f"{v}", (i, v), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.4, color=INK)
ax.set_ylabel("关系条数")
ax.set_title("事件间关系类型分布（499 条）")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：T19_事件关系", fontsize=8, color=FAINT)
save_fig(fig, "D06", "事件关系类型分布", "谓词关系", SCR, ["T19"], "事件关联以时序与因果为主")

# D07 谓词×时间角色堆叠
tr = T34.copy()
tr["trole"] = tr["时间"].fillna("无时间")
def role_bin(x):
    if x == "无时间" or pd.isna(x): return "无时间"
    try:
        y = int(str(x)[:4])
    except Exception:
        return "无时间"
    if y <= 1923: return "1923前"
    if y <= 1927: return "1924-27"
    if y <= 1937: return "1928-37"
    if y <= 1945: return "1938-45"
    if y <= 1949: return "1946-49"
    return "1949后"
tr["期"] = tr["时间"].apply(role_bin)
top15 = T34["谓词"].value_counts().head(15).index
pv = tr[tr["谓词"].isin(top15)].pivot_table(index="谓词", columns="期", values="主体ID", aggfunc="count").fillna(0)
pvc = pv.div(pv.sum(axis=1), axis=0)
periods = ["1923前", "1924-27", "1928-37", "1938-45", "1946-49", "1949后", "无时间"]
periods = [p_ for p_ in periods if p_ in pvc.columns]
fig, ax = new_fig(8.2, 6.2)
left = np.zeros(len(pvc))
for i, p_ in enumerate(periods):
    ax.barh([pz(x) for x in pvc.index], pvc[p_], left=left, color=SEQ10[i % 10], height=0.66, label=p_, zorder=3)
    left += pvc[p_].values
ax.set_xlim(0, 1.0); ax.set_xlabel("占比")
ax.set_title("高频谓词断言的时间分布构成（严格层）")
ax.legend(fontsize=8, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.10))
despine(ax, keep=("bottom",))
fig.text(0.01, 0.012, "数据源：T34_严格层边表31067", fontsize=8, color=FAINT)
save_fig(fig, "D07", "谓词时间分布堆叠图", "谓词关系", SCR, ["T34"], "不同谓词的时间重心不同")

# D08 类型组合热力
m8 = collections.Counter()
for s, o in zip(T34["主体类型"], T34["客体类型"]):
    m8[(ez(s), ez(o))] += 1
rs = sorted({k[0] for k in m8}); cs = sorted({k[1] for k in m8})
mat = np.zeros((len(rs), len(cs)))
for (a, b), c in m8.items():
    mat[rs.index(a), cs.index(b)] = c
fig, ax = new_fig(9.0, 6.2)
cmapb = mpl.colors.LinearSegmentedColormap.from_list("mb", BLUE_SEQ)
im = ax.imshow(np.log10(mat + 1), cmap=cmapb, aspect="auto")
ax.set_xticks(range(len(cs))); ax.set_xticklabels(cs, fontsize=8.2, rotation=38, ha="right")
ax.set_yticks(range(len(rs))); ax.set_yticklabels(rs, fontsize=8.4)
for i in range(len(rs)):
    for j in range(len(cs)):
        if mat[i, j] >= 50:
            ax.text(j, i, f"{int(mat[i,j]):,}", ha="center", va="center", fontsize=7.4,
                    color="#FFFFFF" if mat[i, j] > mat.max() * 0.5 else INK)
ax.set_xlabel("宾语类型"); ax.set_ylabel("主语类型")
ax.set_title("严格层类型组合热力图（色=log10 计数，格=计数）")
cb = fig.colorbar(im, ax=ax, shrink=0.82); cb.set_label("log10(断言数)", fontsize=9)
despine(ax, keep=())
fig.text(0.01, 0.012, "数据源：T34_严格层边表31067", fontsize=8, color=FAINT)
save_fig(fig, "D08", "类型组合热力图", "谓词关系", SCR, ["T34"], "人物→组织组合计数最高")

# ============ E 时空 ============
# E01 阶段×省域热力
stage_map = {0: "建党前", 1: "建党与大革命", 2: "土地革命", 3: "抗日战争", 4: "解放战争", 5: "革命和建设", 6: "改革开放", 7: "新时代"}
T16["阶段名"] = T16["阶段序"].map(stage_map)
pv = T16.pivot_table(index="阶段序", columns="省份", values="时间证据数", aggfunc="sum").fillna(0)
order = ["上海市", "江苏省", "安徽省", "江西省", "湖北省", "湖南省", "重庆市", "四川省", "贵州省", "云南省", "浙江省", "青海省", "西藏自治区"]
order = [p_ for p_ in order if p_ in pv.columns]
pv = pv[order]
fig, ax = new_fig(9.6, 5.8)
cmapb = mpl.colors.LinearSegmentedColormap.from_list("mb", BLUE_SEQ)
im = ax.imshow(np.log10(pv.values + 1), cmap=cmapb, aspect="auto")
ax.set_xticks(range(len(order))); ax.set_xticklabels([p_[:2] for p_ in order], fontsize=8.6)
ax.set_yticks(range(len(pv))); ax.set_yticklabels([stage_map[i] for i in pv.index], fontsize=8.4)
for i in range(len(pv)):
    for j in range(len(order)):
        v = pv.values[i, j]
        if v > 0:
            ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=6.8,
                    color="#FFFFFF" if v > pv.values.max() * 0.5 else INK)
ax.set_title("事件时空格证据强度：历史阶段 × 省域（时间证据数）")
cb = fig.colorbar(im, ax=ax, shrink=0.82); cb.set_label("log10(证据数)", fontsize=9)
despine(ax, keep=())
fig.text(0.01, 0.012, "数据源：research_event_spatiotemporal_cells（7,067 格，时间+地点+语境证据合计口径见E02）", fontsize=8, color=FAINT)
save_fig(fig, "E01", "历史阶段省域时空热力图", "时空图", SCR, ["T16"], "土地革命时期为全域峰值")

# E02 证据类型强度
pv2 = T16.pivot_table(index="阶段序", columns="省份", values="地点证据数", aggfunc="sum").fillna(0)
pv2 = pv2[order]
cmapg = mpl.colors.LinearSegmentedColormap.from_list("mg", GREEN_SEQ)
fig, ax = new_fig(9.6, 5.8)
im = ax.imshow(np.log10(pv2.values + 1), cmap=cmapg, aspect="auto")
ax.set_xticks(range(len(order))); ax.set_xticklabels([p_[:2] for p_ in order], fontsize=8.6)
ax.set_yticks(range(len(pv2))); ax.set_yticklabels([stage_map[i] for i in pv2.index], fontsize=8.4)
ax.set_title("事件时空格：地点证据密度（log 色标）")
cb = fig.colorbar(im, ax=ax, shrink=0.82); cb.set_label("log10(地点证据数)", fontsize=9)
despine(ax, keep=())
fig.text(0.01, 0.012, "数据源：research_event_spatiotemporal_cells", fontsize=8, color=FAINT)
save_fig(fig, "E02", "地点证据密度热力图", "时空图", SCR, ["T16"], "空间证据与时间证据格局一致")

# E03 事件框架年代分布
T17v = T17.dropna(subset=["观测起"]).copy()
T17v["年"] = T17v["观测起"].astype(str).str[:4].astype(int)
T17v = T17v[(T17v["年"] >= 1850) & (T17v["年"] <= 2020)]
fig, ax = new_fig(8.4, 4.6)
bins = np.arange(1850, 2021, 10)
ax.hist(T17v["年"], bins=bins, color=M["雾蓝"], edgecolor="white", linewidth=0.6, zorder=3)
ax.set_xlabel("事件观测起始年（10年分段）"); ax.set_ylabel("事件框架数")
ax.set_title("事件框架年代分布（观测起始年非空的框架）")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：T17_事件框架全表（28,065 框架中观测起非空部分）", fontsize=8, color=FAINT)
save_fig(fig, "E03", "事件框架年代分布", "时空图", SCR, ["T17"], "1920-1940年代为事件密集期")

# E04 重大事件时间轴
te = T36.head(24).merge(T17[["事件名", "观测起", "观测止"]].drop_duplicates("事件名"), on="事件名", how="left")
fig, ax = new_fig(9.0, 7.0)
for i, (_, r) in enumerate(te.iterrows()):
    y = len(te) - i
    try:
        y0 = int(str(r["观测起"])[:4]) if pd.notna(r["观测起"]) else None
    except Exception:
        y0 = None
    try:
        y1 = int(str(r["观测止"])[:4]) if pd.notna(r["观测止"]) else None
    except Exception:
        y1 = None
    if y0 and y1 and y1 > y0:
        ax.plot([y0, y1], [y, y], color=M["陶砂"], lw=4.5, solid_capstyle="round", alpha=0.85, zorder=3)
        ax.scatter([y0, y1], [y, y], s=18, color=M["陶砂"], zorder=4)
    elif y0:
        ax.scatter(y0, y, s=64, color=M["陶砂"], zorder=4)
    else:
        ax.scatter(1927, y, s=26, color=M["驼灰"], alpha=0.5, zorder=3)
ax.set_yticks(range(1, len(te) + 1)); ax.set_yticklabels([wrap_zh(x, 8) for x in te["事件名"]], fontsize=8.2)
ax.set_xlabel("年份")
ax.set_title("重大事件框架时间轴（Top24，点=单年，粗线=区间）")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：T36 × T17 观测时间（无观测时间的以灰色点示意）", fontsize=8, color=FAINT)
save_fig(fig, "E04", "重大事件时间轴", "时空图", SCR, ["T36", "T17"], "事件时间集中于1925-1949")

# E05 四大案例时间链
cases = [("八七会议", 1927.58), ("南昌起义", 1927.58), ("秋收起义", 1927.70), ("遵义会议", 1935.0)]
fig, ax = new_fig(9.0, 3.6)
ax.axhline(0, color=AXIS, lw=1.2, zorder=1)
for i, (nm, t) in enumerate(cases):
    ax.scatter(t, 0, s=200, color=SEQ10[i], zorder=3, edgecolors="white", linewidths=1.2)
    ax.annotate(f"{nm}\n（{'1927-08-07' if nm=='八七会议' else '1927-08-01' if nm=='南昌起义' else '1927-09-10' if nm=='秋收起义' else '1935-01-15'}）",
                (t, 0), xytext=(0, 24 if i % 2 == 0 else -40), textcoords="offset points", ha="center",
                fontsize=9.5, color=INK, zorder=4,
                arrowprops=dict(arrowstyle="-", color=FAINT, lw=0.7))
ax.set_xlim(1927.2, 1935.6); ax.set_ylim(-1.4, 1.4)
ax.set_yticks([]); ax.set_xlabel("年份")
ax.set_title("论文代表性案例事件时间链")
despine(ax, keep=("bottom",))
fig.text(0.01, 0.012, "数据源：论文§4.3 点名事件（观测时间取自 T17/历史常识核对）", fontsize=8, color=FAINT)
save_fig(fig, "E05", "四案例事件时间链", "时空图", SCR, ["T17"], "八七会议→南昌起义→秋收起义→遵义会议")

# E06 地名版本区间
T18v = T18.dropna(subset=["起"]).copy()
def yr(x):
    try: return int(str(x)[:4])
    except Exception: return None
T18v["y0"] = T18v["起"].apply(yr); T18v["y1"] = T18v["止"].apply(yr)
T18v = T18v.dropna(subset=["y0"])
T18v["y1"] = T18v["y1"].fillna(2026).clip(upper=2026)
T18v = T18v.sort_values(["y0", "历史名"]).head(46)
fig, ax = new_fig(8.8, 8.0)
for i, (_, r) in enumerate(T18v.iterrows()):
    ax.plot([r["y0"], max(r["y1"], r["y0"] + 1)], [i, i], color=M["驼灰"], lw=4, solid_capstyle="round", alpha=0.8, zorder=3)
ax.set_yticks(range(len(T18v)))
ax.set_yticklabels([wrap_zh(x, 9) for x in T18v["历史名"]], fontsize=7.4)
ax.set_xlabel("年份")
ax.set_title("历史地名版本区间（PlaceVersion 前46条，按起始年排序）")
despine(ax, keep=("bottom",)); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：research_place_versions（72 版本）", fontsize=8, color=FAINT)
save_fig(fig, "E06", "历史地名版本演化区间图", "时空图", SCR, ["T18"], "同名地点的沿革版本结构")

# E07 地名版本行政层级
vc = T18["行政层级"].fillna("未标注").value_counts()
fig, ax = new_fig(7.0, 4.2)
ax.bar([wrap_zh(str(x), 10) for x in vc.index], vc.values, color=SAND_SEQ[:len(vc)], width=0.56, zorder=3)
for i, v in enumerate(vc.values):
    ax.annotate(f"{v}", (i, v), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.6, color=INK)
ax.set_ylabel("版本数")
ax.set_title("历史地名版本的行政层级构成")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：T18_地点版本演化", fontsize=8, color=FAINT)
save_fig(fig, "E07", "地名版本行政层级构成", "时空图", SCR, ["T18"], "县级版本占主体")

# E08 文化状态阶段×形态
pv = T22.pivot_table(index="阶段序", columns="文化形态", values="状态数", aggfunc="sum").fillna(0)
fig, ax = new_fig(9.0, 5.2)
bottom = np.zeros(len(pv))
for i, c in enumerate(pv.columns):
    ax.bar([stage_map[i] for i in pv.index], pv[c], bottom=bottom, color=SEQ10[i % 10], width=0.6, label=wrap_zh(str(c), 8), zorder=3)
    bottom += pv[c].values
ax.set_ylabel("文化状态数")
ax.set_title("文化状态的历史阶段 × 文化形态构成")
ax.legend(fontsize=7.6, ncol=2, loc="upper left")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：T22_文化状态统计（11,532 状态）", fontsize=8, color=FAINT)
save_fig(fig, "E08", "文化状态阶段形态堆叠图", "时空图", SCR, ["T22"], "土地革命时期状态最密集")

# E09 文化状态省域
pvc = T22[~T22["省份"].astype(str).str.contains("/", na=False)].groupby("省份")["状态数"].sum().sort_values()
fig, ax = new_fig(7.0, 4.8)
ax.barh(pvc.index, pvc.values, color=BLUE_SEQ[3], height=0.62, zorder=3)
for i, v in enumerate(pvc.values):
    ax.annotate(f"{v:,}", (v, i), xytext=(5, 0), textcoords="offset points", va="center", fontsize=8, color=INK)
ax.set_xlabel("文化状态数")
ax.set_title("文化状态的省域分布（单省归属）")
despine(ax); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：T22_文化状态统计", fontsize=8, color=FAINT)
save_fig(fig, "E09", "文化状态省域分布", "时空图", SCR, ["T22"], "湘鄂赣川为文化状态密集省")

# E10 事件规模对数直方
v = T17["严格断言数"].clip(lower=0)
v = v[v > 0]
fig, ax = new_fig(7.2, 4.4)
ax.hist(np.log10(v), bins=np.arange(0, 2.8, 0.2), color=M["青灰"], edgecolor="white", linewidth=0.6, zorder=3)
ax.set_xticks(range(0, 3)); ax.set_xticklabels(["1", "10", "100"])
ax.set_xlabel("事件严格断言数（log10）"); ax.set_ylabel("事件框架数")
ax.set_title("事件框架规模分布（严格断言>0 的框架）")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：T17_事件框架全表", fontsize=8, color=FAINT)
save_fig(fig, "E10", "事件规模对数直方图", "时空图", SCR, ["T17"], "多数事件仅1-2条严格断言，少数大事件突出")

# E11 跨省域数分布
vc = T17["省域数"].value_counts().sort_index()
fig, ax = new_fig(7.0, 4.2)
ax.bar(vc.index, vc.values, color=M["雾蓝"], width=0.6, zorder=3)
for x, yv in zip(vc.index, vc.values):
    ax.annotate(f"{yv:,}", (x, yv), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=7.8, color=INK)
ax.set_yscale("log"); ax.set_xlabel("事件涉及省域数"); ax.set_ylabel("事件框架数（log）")
ax.set_title("事件的空间跨度分布")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：T17_事件框架全表 region_count", fontsize=8, color=FAINT)
save_fig(fig, "E11", "事件空间跨度分布", "时空图", SCR, ["T17"], "多数事件限于1省，跨省事件以长征线为主")

# E13 三层时间面积
tt = T05.groupby("年")[["严格层", "上下文层", "未决层"]].sum()
fig, ax = new_fig(8.6, 4.6)
ax.stackplot(tt.index, [tt["严格层"], tt["上下文层"], tt["未决层"]],
             colors=[TIER_C["STRICT"], TIER_C["CONTEXTUAL"], TIER_C["UNRESOLVED"]],
             labels=["严格层", "上下文层", "未决层"], alpha=0.88)
ax.set_xlabel("年份"); ax.set_ylabel("断言数")
ax.set_title("断言时间分布 × 知识状态构成")
ax.legend(loc="upper right", fontsize=9)
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：T05_断言时间年分布", fontsize=8, color=FAINT)
save_fig(fig, "E13", "时间与知识状态面积图", "时空图", SCR, ["T05"], "革命年代产出量最大且严格层占比更高")

# E14 观测层构成
pv = T16.pivot_table(index="阶段序", columns="观测层", values="时间证据数", aggfunc="sum").fillna(0)
pvn = pv.div(pv.sum(axis=1), axis=0)
fig, ax = new_fig(8.6, 4.8)
bottom = np.zeros(len(pvn))
for i, c in enumerate(pvn.columns):
    ax.bar([stage_map[i] for i in pvn.index], pvn[c], bottom=bottom, color=GREEN_SEQ[1 + 2 * (i % 3)], width=0.6, label=str(c), zorder=3)
    bottom += pvn[c].values
ax.set_ylabel("占比"); ax.set_ylim(0, 1.0)
ax.set_title("各历史阶段时空格的观测层构成（按时间证据加权）")
ax.legend(fontsize=8.4, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.12))
despine(ax, keep=("bottom",))
fig.text(0.01, 0.012, "数据源：T16_历史阶段×省域时空格", fontsize=8, color=FAINT)
save_fig(fig, "E14", "观测层构成百分比图", "时空图", SCR, ["T16"], "观测层质量在各时期保持稳定")

# E15 文化形态 bump
pv = T22.pivot_table(index="阶段序", columns="文化形态", values="状态数", aggfunc="sum").fillna(0)
ranks = pv.rank(ascending=False, axis=1)
fig, ax = new_fig(8.8, 5.6)
for i, c in enumerate(pv.columns):
    ax.plot([stage_map[i] for i in pv.index], ranks[c], "-o", color=SEQ10[i % 10], lw=1.8, ms=6, label=wrap_zh(str(c), 8))
ax.invert_yaxis(); ax.set_ylabel("排名（1 = 状态数最多）")
ax.set_title("文化形态在各历史阶段的排名变化（bump chart）")
ax.legend(fontsize=8, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.14))
despine(ax, keep=("bottom",)); light_grid(ax, axis="y")
fig.text(0.01, 0.012, "数据源：T22_文化状态统计", fontsize=8, color=FAINT)
save_fig(fig, "E15", "文化形态排名bump图", "时空图", SCR, ["T22"], "形态兴衰与历史阶段对应")

# E16 人物活动档案
person = T32["人物"].value_counts().index[1] if T32["人物"].value_counts().index[0] in ("毛泽东",) else T32["人物"].value_counts().index[0]
pp = T32[T32["人物"] == person].sort_values("年")
fig, ax = new_fig(8.4, 4.4)
ax.bar(pp["年"], pp["断言数"], color=M["雾蓝"], width=0.75, zorder=3)
pk = pp.loc[pp["断言数"].idxmax()]
ax.annotate(f"峰值 {int(pk['年'])} 年（{int(pk['断言数'])} 条）", (pk["年"], pk["断言数"]),
            xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8.8, color=INK)
ax.set_xlabel("年份"); ax.set_ylabel("涉及断言数")
ax.set_title(f"「{person}」的活动年份档案（严格层）")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：T32_人物活跃年份", fontsize=8, color=FAINT)
save_fig(fig, "E16", "典型人物活动年份档案", "时空图", SCR, ["T32"], f"{person}的年度活跃结构")

print("批C2（C01-C10, D01-D08, E01-E16）完成")
