# -*- coding: utf-8 -*-
"""批C_案例网络.py — L01–L16 案例与知识网络（16张）"""
import sys, os, collections
sys.path.insert(0, r"D:\REDCULTUREDATA\可视化输出\10_生成脚本")
from style_lib import *
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np
import pandas as pd
import networkx as nx

MID = r"D:\REDCULTUREDATA\可视化输出\11_数据中间表"
SCR = "批C_案例网络.py"
T34 = pd.read_csv(os.path.join(MID, "T34_严格层边表31067.csv"))
T36 = pd.read_csv(os.path.join(MID, "T36_大事件Top30.csv"))
T17 = pd.read_csv(os.path.join(MID, "T17_事件框架全表.csv"))
TYPE_COLOR = {"Person": M["雾蓝"], "Organization": M["橄榄"], "Event": M["陶砂"],
              "Place": M["青灰"], "Document": M["暮蓝"], "Institution": M["驼灰"],
              "Concept": M["灰紫"], "Artifact": M["绛陶"], "TimePeriod": M["烟粉"]}

def event_network(fig_id, zh, csv_name, note):
    df = pd.read_csv(os.path.join(MID, csv_name))
    if df.empty:
        print(f"[skip] {fig_id} 无数据"); return
    ev_name = df["事件名"].value_counts().index[0]
    df = df[df["事件名"] == ev_name]
    cnt = df["关联对象"].value_counts()
    top = cnt.head(26).index.tolist()
    dft = df[df["关联对象"].isin(top)].drop_duplicates(subset=["关联对象"])
    G = nx.Graph()
    G.add_node(ev_name, t="Event", hub=1)
    for _, r in dft.iterrows():
        G.add_edge(ev_name, r["关联对象"], p=pz(r["谓词"]), rc=r["角色类别"])
    deg = dict(G.degree())
    fig, ax = new_fig(10.2, 7.2)
    pos = nx.spring_layout(G, seed=42, k=0.34, weight=None)
    for u, v, d in G.edges(data=True):
        ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]], color=AXIS, lw=0.7, alpha=0.45, zorder=1)
    for n, d in G.nodes(data=True):
        t = d.get("t") or (dft.set_index("关联对象").loc[n, "对象类型"] if n != ev_name else "Event")
        c = TYPE_COLOR.get(t, M["石板"])
        s = 300 + 90 * deg[n] if n == ev_name else 60 + 26 * deg[n]
        ax.scatter(*pos[n], s=s, color=c, zorder=3, edgecolors="white", linewidths=0.8)
    ax.scatter(*pos[ev_name], s=1500, color=TIER_C["STRICT"], zorder=4, edgecolors="white", linewidths=1.4)
    ax.annotate(ev_name, pos[ev_name], fontsize=13, fontweight="bold", color="white",
                ha="center", va="center", zorder=5)
    lab_n = min(18, len(top))
    for n in cnt.head(lab_n).index:
        if n == ev_name: continue
        ax.annotate(n, pos[n], fontsize=8.5, color=INK, ha="center", va="center",
                    xytext=(0, -12), textcoords="offset points", zorder=5)
    ax.set_title(f"「{ev_name}」事件中心严格层知识网络")
    ax.set_xlim(-1.08, 1.08); ax.set_ylim(-1.08, 1.08); ax.axis("off")
    from matplotlib.lines import Line2D
    present = set()
    for n in G.nodes:
        if n == ev_name: continue
        present.add(dft.set_index("关联对象").loc[n, "对象类型"])
    handles = [Line2D([], [], marker='o', ls='', color=TYPE_COLOR.get(t, M["石板"]), label=ez(t)) for t in sorted(present)]
    handles.append(Line2D([], [], marker='o', ls='', color=TIER_C["STRICT"], markersize=11, label=f"中心事件"))
    ax.legend(handles=handles, loc="upper left", fontsize=9, frameon=False)
    fig.text(0.01, 0.012, f"数据源：最终库 research_event_roles/evidence_gate_tier（严格层）；邻居节点 Top{lab_n}", fontsize=8, color=FAINT)
    save_fig(fig, fig_id, zh, "案例网络", SCR, [csv_name], note)

event_network("L01", "南昌起义事件中心知识网络", "T35_案例_南昌起义.csv", "132条严格断言汇聚582个受控角色")
event_network("L02", "八七会议事件中心知识网络", "T35_案例_八七会议.csv", "会议类事件的组织连接形态")
event_network("L03", "遵义会议事件中心知识网络", "T35_案例_遵义会议.csv", "转折性会议的知识汇聚")
event_network("L04", "秋收起义事件中心知识网络", "T35_案例_秋收起义.csv", "起义类事件的空间组织特征")

# ---------- L05 四案例结构对比 ----------
fig, ax = new_fig(7.6, 4.6)
events = ["南昌起义", "秋收起义", "八七会议", "遵义会议"]
mets = ["严格断言数", "受控角色数", "省域数"]
vals = {}
for e in events:
    row = T17[T17["事件名"] == e]
    if len(row) == 0:
        row = T36[T36["事件名"].str.contains(e, na=False)]
    vals[e] = [float(row["严格断言数"].max() if len(row) else 0),
               float(row["受控角色数"].max() if len(row) else 0),
               float(row["省域数"].max() if len(row) else 0)]
xs = np.arange(3)
for i, e in enumerate(events):
    ax.scatter(xs, [vals[e][j] for j in range(3)], s=110, color=SEQ10[i], label=e, zorder=3)
    for j in range(3):
        ax.annotate(f"{vals[e][j]:.0f}", (xs[j], vals[e][j]), textcoords="offset points",
                    xytext=(0, 10), ha="center", fontsize=8.5, color=FAINT)
ax.set_yscale("log"); ax.set_xticks(xs); ax.set_xticklabels(mets)
ax.set_ylabel("数值（对数刻度）")
ax.set_title("四个代表性事件框架的结构规模对比")
despine(ax); light_grid(ax); ax.legend()
fig.text(0.01, 0.012, "数据源：research_event_frames（最终库）", fontsize=8, color=FAINT)
save_fig(fig, "L05", "四案例事件结构对比", "案例网络", SCR, ["T17_事件框架全表.csv"],
         "南昌起义在三个维度上均为最大")

# ---------- L06 南昌起义角色构成 ----------
dfn = pd.read_csv(os.path.join(MID, "T35_案例_南昌起义.csv"))
rc = dfn["角色类别"].value_counts()
fig, ax = new_fig(7.0, 4.2)
ax.barh([wrap_zh(x, 8) for x in rc.index][::-1], rc.values[::-1],
        color=[SEQ10[i % 10] for i in range(len(rc))][::-1], height=0.62, zorder=3)
for i, v in enumerate(rc.values[::-1]):
    ax.annotate(f"{v}", (v, i), textcoords="offset points", xytext=(6, 0), va="center", fontsize=9, color=INK)
ax.set_xlabel("角色连接数"); ax.set_title("「南昌起义」事件框架的角色类型构成")
despine(ax); light_grid(ax, axis="x")
fig.text(0.01, 0.012, "数据源：research_event_roles（南昌起义相关事件框架）", fontsize=8, color=FAINT)
save_fig(fig, "L06", "南昌起义角色类型构成", "案例网络", SCR, ["T35_案例_南昌起义.csv"],
         "人物参与是事件框架的主要连接")

# ---------- L07 人物—组织网络 ----------
po = T34[(T34["主体类型"] == "Person") & (T34["客体类型"] == "Organization")]
ecnt = po.groupby(["主体名", "客体名"]).size().sort_values(ascending=False)
top_edges = ecnt.head(70)
G = nx.Graph()
for (s, o), w in top_edges.items():
    G.add_edge(s, o, w=w)
deg = dict(G.degree())
keep = [n for n, d in deg.items() if d >= 2]
G = G.subgraph(keep).copy() if keep else G
deg = dict(G.degree())  # 子图后重算，避免标注失效节点
fig, ax = new_fig(10.2, 7.2)
pos = nx.spring_layout(G, seed=7, k=0.30)
for u, v, d in G.edges(data=True):
    ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]], color=AXIS, lw=0.35 + d["w"] * 0.16,
            alpha=0.5, zorder=1)
for n in G.nodes:
    t = "Person" if n in set(po["主体名"]) else "Organization"
    ax.scatter(*pos[n], s=24 + 16 * deg[n], color=TYPE_COLOR[t], zorder=3, edgecolors="white", linewidths=0.5)
topn = sorted(deg, key=deg.get, reverse=True)[:16]
for n in topn:
    ax.annotate(n, pos[n], fontsize=8.5, color=INK, xytext=(0, 7), textcoords="offset points", ha="center")
ax.set_title("严格层高频人物—组织关联网络")
ax.axis("off")
from matplotlib.lines import Line2D
ax.legend(handles=[Line2D([], [], marker='o', ls='', color=TYPE_COLOR["Person"], label='人物'),
                   Line2D([], [], marker='o', ls='', color=TYPE_COLOR["Organization"], label='组织')],
          loc="upper left")
fig.text(0.01, 0.012, "数据源：research_assertions 严格层（Person–Organization 边，按共现频次 Top70）", fontsize=8, color=FAINT)
save_fig(fig, "L07", "人物组织高频网络", "案例网络", SCR, ["T34_严格层边表31067.csv"],
         "人物-组织构成党史知识的骨架连接")

# ---------- L08 省域共现网络 ----------
pairs = collections.Counter()
for p in T34["省份"].dropna().unique():
    if "/" not in str(p): continue
    ps = sorted(str(p).split("/"))
    for i in range(len(ps)):
        for j in range(i + 1, len(ps)):
            pairs[(ps[i], ps[j])] += 1
wcnt = collections.Counter()
for (a, b), w in pairs.items():
    wcnt[a] += w; wcnt[b] += w
provs = sorted(wcnt, key=wcnt.get, reverse=True)[:13]
G = nx.Graph()
for p in provs: G.add_node(p)
for (a, b), w in pairs.items():
    if a in provs and b in provs: G.add_edge(a, b, w=w)
fig, ax = new_fig(9.6, 7.0)
pos = nx.circular_layout(G)
for u, v, d in G.edges(data=True):
    ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]], color=M["雾蓝"],
            lw=0.5 + 1.4 * np.log1p(d["w"]), alpha=0.45, zorder=1)
for n in G.nodes:
    ax.scatter(*pos[n], s=80 + 14 * wcnt[n], color=M["陶砂"], zorder=3, edgecolors="white", linewidths=0.8)
    ax.annotate(n, pos[n], fontsize=9.5, color=INK, xytext=(0, 12), textcoords="offset points", ha="center")
ax.set_title("严格层知识的省域共现网络（跨省断言）")
ax.set_xlim(-1.25, 1.25); ax.set_ylim(-1.25, 1.25); ax.axis("off")
fig.text(0.01, 0.012, "数据源：research_assertions 严格层 province 字段（跨省组合拆对计数）", fontsize=8, color=FAINT)
save_fig(fig, "L08", "省域共现网络", "案例网络", SCR, ["T34_严格层边表31067.csv"],
         "鄂湘赣三省构成跨省知识的核心三角")

# ---------- L09 典型人物活动档案 ----------
T32 = pd.read_csv(os.path.join(MID, "T32_人物活跃年份.csv"))
person = T32["人物"].value_counts().index[0]
pp = T32[T32["人物"] == person].sort_values("年")
fig, ax = new_fig(8.6, 4.4)
ax.bar(pp["年"], pp["断言数"], color=M["雾蓝"], width=0.8, zorder=3)
peak = pp.loc[pp["断言数"].idxmax()]
ax.annotate(f"{int(peak['年'])}年 峰值{int(peak['断言数'])}条", (peak["年"], peak["断言数"]),
            textcoords="offset points", xytext=(0, 10), ha="center", fontsize=9, color=INK)
ax.set_xlabel("年份"); ax.set_ylabel("涉及断言数（严格层时间可达）")
ax.set_title(f"「{person}」在图谱中的年份活跃档案")
despine(ax); light_grid(ax)
fig.text(0.01, 0.012, "数据源：research_assertions（subject_type=Person，1900–1950，≥3条/年）", fontsize=8, color=FAINT)
save_fig(fig, "L09", "典型人物活动档案", "案例网络", SCR, ["T32_人物活跃年份.csv"],
         f"{person}为图谱最高频人物，活跃高峰反映革命关键期")

# ---------- L10–L14 案例路径图 ----------
T45 = pd.read_csv(os.path.join(MID, "T45_五档典型案例.csv"))
T46 = pd.read_csv(os.path.join(MID, "T46_无证据典型案例.csv"))

def case_path(fig_id, zh, row, tier_note, note):
    fig, ax = new_fig(10.6, 4.3)
    ax.set_xlim(0, 10.6); ax.set_ylim(0, 4.3); ax.axis("off")
    def box(x, y, w, h, title, lines, fc, ec):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08,rounding_size=0.12",
                                    facecolor=fc, edgecolor=ec, lw=1.2, zorder=2))
        ax.text(x + w / 2, y + h - 0.30, title, ha="center", fontsize=10.5, fontweight="bold", color=INK, zorder=3)
        ax.text(x + w / 2, y + h / 2 - 0.16, "\n".join(lines), ha="center", va="center",
                fontsize=8.8, color=INK, zorder=3, linespacing=1.45)
    def arrow(x1, x2, y):
        ax.add_patch(FancyArrowPatch((x1, y), (x2, y), arrowstyle="-|>", mutation_scale=15,
                                     color=FAINT, lw=1.3, zorder=1))
    dec = str(row["五档"]); ft = str(row["最终层"])
    sup_c = SUP_C[dec]; tier_c = TIER_C.get(ft, M["石板"])
    quote = str(row["引文"])[:52] + "…" if len(str(row["引文"])) > 52 else str(row["引文"])
    box(0.25, 1.05, 2.35, 2.5, "原文证据（可定位）", [wrap_zh(quote, 11)], "#F4F1EA", M["驼灰"])
    box(3.05, 1.05, 1.95, 2.5, "知识断言", [f"{row['主体']}", f"—{pz(row['谓词'])}—", f"{row['客体']}"], "#F2F4F3", M["青灰"])
    box(5.45, 1.05, 1.75, 2.5, "语义支持判定", [SUP_ZH[dec], "（证据门五档）"], "#F0F2F4", sup_c)
    box(7.65, 1.05, 1.75, 2.5, "最终知识状态", [tier_note, f"{ft}"], "#F3F1EC", tier_c)
    arrow(2.68, 3.0, 2.3); arrow(5.06, 5.4, 2.3); arrow(7.26, 7.6, 2.3)
    ax.text(5.45, 3.95, f"{row['主体']} —{pz(row['谓词'])}— {row['客体']}", ha="center",
            fontsize=11, fontweight="bold", color=INK)
    expl = wrap_zh(str(row["解释"]), 44)
    ax.text(5.45, 0.52, "判定理由：" + expl, ha="center", fontsize=8.8, color=FAINT)
    fig.text(0.01, 0.012, "数据源：gate_verdict_details × research_assertions × evidence_gate_tier（最终库）", fontsize=8, color=FAINT)
    save_fig(fig, fig_id, zh, "案例路径", SCR, ["T45_五档典型案例.csv"], note)

r_full = T45[(T45["五档"] == "FULLY_SUPPORTED") & (T45["最终层"] == "STRICT")].iloc[0]
case_path("L10", "严格层典型准入路径", r_full, "严格层", "证据完全支持→保持严格层")
r_ctx = T45[(T45["五档"] == "PARTIALLY_SUPPORTED") & (T45["最终层"] == "CONTEXTUAL")].iloc[0]
case_path("L11", "上下文层典型路径", r_ctx, "上下文层", "部分支持且谓词不在strict集→降级上下文层")
r_uns = T45[(T45["五档"] == "UNSUPPORTED")].iloc[0]
case_path("L12", "未决层典型路径", r_uns, "未决层", "证据不支持→转入未决集合")
r_con = T45[(T45["五档"] == "CONTRADICTED")].iloc[0]
case_path("L13", "相矛盾典型案例", r_con, "未决层", "证据与断言时间/空间矛盾→未决")
r_ps = T45[(T45["五档"] == "PARTIALLY_SUPPORTED") & (T45["最终层"] == "STRICT")].iloc[0]
case_path("L14", "部分支持入严格层案例", r_ps, "严格层", "active_at 属 PARTIAL-strict 谓词→保持严格层")

# ---------- L15 事件关系网络 ----------
T19 = pd.read_csv(os.path.join(MID, "T19_事件关系.csv"))
G = nx.from_pandas_edgelist(T19, "源事件", "目标事件", edge_attr=True, create_using=nx.Graph())
deg = dict(G.degree())
keep = sorted(deg, key=deg.get, reverse=True)[:80]
G = G.subgraph(keep).copy()
rel_types = T19["关系"].value_counts().index.tolist()[:6]
relc = {r: SEQ10[i] for i, r in enumerate(rel_types)}
fig, ax = new_fig(10.4, 7.2)
pos = nx.spring_layout(G, seed=11, k=0.36)
for u, v, d in G.edges(data=True):
    c = relc.get(d["关系"], M["石板"])
    ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]], color=c, lw=0.8, alpha=0.5, zorder=1)
for n in G.nodes:
    ax.scatter(*pos[n], s=30 + 10 * deg[n], color=M["暮蓝"], zorder=3, edgecolors="white", linewidths=0.5)
topn = sorted(dict(G.degree()).items(), key=lambda kv: -kv[1])[:18]
for n, d in topn:
    ax.annotate(n, pos[n], fontsize=8.5, color=INK, xytext=(0, 7), textcoords="offset points", ha="center")
ax.set_title(f"事件间关系网络（Top{len(G)}事件，{len(T19)}条关系）")
ax.axis("off")
from matplotlib.lines import Line2D
ax.legend(handles=[Line2D([], [], color=c, label=r) for r, c in relc.items()], loc="upper left", fontsize=9)
fig.text(0.01, 0.012, "数据源：research_event_relations（499条，最终库）", fontsize=8, color=FAINT)
save_fig(fig, "L15", "事件关系网络", "案例网络", SCR, ["T19_事件关系.csv"],
         "事件关联呈链式历史叙事结构")

# ---------- L16 核心实体自我网络 ----------
subj_deg = T34["主体名"].value_counts()
hub = subj_deg.index[0]
ego_edges = T34[(T34["主体名"] == hub) | (T34["客体名"] == hub)]
G = nx.Graph()
G.add_node(hub, t="hub")
for _, r in ego_edges.iterrows():
    other = r["客体名"] if r["主体名"] == hub else r["主体名"]
    t = r["客体类型"] if r["主体名"] == hub else r["主体类型"]
    G.add_node(other, t=t)
    G.add_edge(hub, other)
deg = dict(G.degree())
if len(G) > 46:
    keep = sorted(deg, key=deg.get, reverse=True)[:46]
    G = G.subgraph(keep).copy()
deg = dict(G.degree())
fig, ax = new_fig(9.8, 7.0)
pos = nx.spring_layout(G, seed=5, k=0.36)
for u, v in G.edges():
    ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]], color=AXIS, lw=0.7, alpha=0.45, zorder=1)
for n, d in G.nodes(data=True):
    if d.get("t") == "hub":
        ax.scatter(*pos[n], s=1600, color=TIER_C["STRICT"], zorder=4, edgecolors="white", linewidths=1.4)
        ax.annotate(n, pos[n], fontsize=12.5, fontweight="bold", color="white", ha="center", va="center", zorder=5)
    else:
        c = TYPE_COLOR.get(d.get("t"), M["石板"])
        ax.scatter(*pos[n], s=46, color=c, zorder=3, edgecolors="white", linewidths=0.5)
for n, d in sorted(deg.items(), key=lambda kv: -kv[1])[1:15]:
    ax.annotate(n, pos[n], fontsize=8.2, color=INK, xytext=(0, -11), textcoords="offset points", ha="center")
ax.set_title(f"「{hub}」自我网络（严格层邻域）")
ax.axis("off")
fig.text(0.01, 0.012, "数据源：research_assertions 严格层（主体/客体邻接，Top46邻域）", fontsize=8, color=FAINT)
save_fig(fig, "L16", "核心实体自我网络", "案例网络", SCR, ["T34_严格层边表31067.csv"],
         f"枢纽实体「{hub}」连接多类型历史对象")

print("批次C（L01-L16）完成")
