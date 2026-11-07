from __future__ import annotations

import math
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import networkx as nx
from matplotlib import font_manager


ROOT = Path(r"D:\REDCULTUREDATA")
OUT = ROOT / "revision_output" / "20261015_round3" / "working"
CSV = ROOT / "可视化输出" / "11_数据中间表" / "T34_严格层边表31067.csv"

FONT = r"C:\Windows\Fonts\simsun.ttc"
try:
    font_manager.fontManager.addfont(FONT)
    plt.rcParams["font.family"] = "SimSun"
except Exception:
    pass
plt.rcParams["axes.unicode_minus"] = False


def forest(name: str, title: str, values: list[tuple[str, float, float, float]]) -> Path:
    fig, ax = plt.subplots(figsize=(8.4, 2.0), dpi=220)
    y = list(range(len(values)))[::-1]
    for yi, (label, point, lo, hi) in zip(y, values):
        color = "#2f8f83" if "支持" in label else "#b2544d"
        ax.hlines(yi, lo, hi, color=color, linewidth=2.4)
        ax.plot(point, yi, marker="s", color=color, markersize=7)
        ax.text(min(99, hi + 1.2), yi, f"{point:.2f}% [{lo:.2f}, {hi:.2f}]", va="center", fontsize=9, color="#555555")
    ax.set_yticks(y, [x[0] for x in values])
    ax.set_xlim(0, 100)
    ax.set_xlabel("强共识条件指标（%）")
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold")
    ax.grid(axis="x", color="#dddddd", linewidth=0.7)
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.01, 0.01, "数据源：AUDIT_RESULTS.json；分母为双裁判五档标签完全一致的样本", fontsize=8, color="#666666")
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    path = OUT / name
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def event_graph() -> Path:
    df = pd.read_csv(CSV)
    event = "南昌起义"
    rows = df[(df["客体名"] == event) | (df["主体名"] == event)].copy()
    # Keep a single event-centered network with role edges from the strict-layer edge table.
    rows["neighbor"] = rows.apply(lambda r: r["主体名"] if r["客体名"] == event else r["客体名"], axis=1)
    rows["neighbor_type"] = rows.apply(lambda r: r["主体类型"] if r["客体名"] == event else r["客体类型"], axis=1)
    rows["role"] = rows.apply(lambda r: r["谓词"], axis=1)
    rows = rows[rows["neighbor"].notna()].drop_duplicates(subset=["neighbor", "role"])
    role_order = {"organized": 0, "led": 1, "participated_in": 2, "occurred_at": 3, "influenced": 4}
    rows["rank"] = rows["role"].map(role_order).fillna(9)
    rows = rows.sort_values(["rank", "neighbor"]).head(12)

    G = nx.DiGraph()
    G.add_node(event, kind="Event")
    for _, r in rows.iterrows():
        G.add_node(r["neighbor"], kind=r["neighbor_type"])
        if r["客体名"] == event:
            G.add_edge(r["neighbor"], event, label=r["role"])
        else:
            G.add_edge(event, r["neighbor"], label=r["role"])

    colors = {"Event": "#e07a5f", "Person": "#4f81bd", "Organization": "#59a14f", "Place": "#f2b134", "Document": "#8e6bbd"}
    node_colors = [colors.get(G.nodes[n].get("kind"), "#999999") for n in G.nodes]
    pos = {event: (0, 0)}
    neighbors = [n for n in G.nodes if n != event]
    for i, n in enumerate(neighbors):
        angle = math.pi / 2 + (i - (len(neighbors) - 1) / 2) * (math.pi / (len(neighbors) + 1))
        pos[n] = (2.6 * math.cos(angle), 1.7 * math.sin(angle))

    fig, ax = plt.subplots(figsize=(9.2, 6.2), dpi=220)
    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=[1700 if n == event else 900 for n in G.nodes], edgecolors="#333333", linewidths=1, ax=ax)
    nx.draw_networkx_edges(G, pos, edge_color="#5b6770", arrows=True, arrowstyle="-|>", arrowsize=18, width=1.2, connectionstyle="arc3,rad=0.04", min_source_margin=14, min_target_margin=16, ax=ax)
    nx.draw_networkx_labels(G, pos, font_size=9, font_family="SimSun", ax=ax)
    role_zh = {"organized": "组织", "led": "领导", "participated_in": "参与", "occurred_at": "发生于", "influenced": "影响"}
    labels = {(u, v): role_zh.get(d["label"], d["label"]) for u, v, d in G.edges(data=True)}
    nx.draw_networkx_edge_labels(G, pos, edge_labels=labels, font_size=8, font_family="SimSun", label_pos=0.55, bbox=dict(alpha=0.75, color="white", pad=0.2), ax=ax)
    # Keep the title and data-scope note on separate figure-level lines.  The
    # previous axes-level placement overlapped after bbox_inches='tight'.
    fig.suptitle("南昌起义严格层事件关系网络", x=0.06, y=0.985, ha="left", fontsize=13, fontweight="bold")
    fig.text(0.06, 0.915, "数据源：T34严格层边表；箭头由主体指向南昌起义，节点类型和关系展示名来自同一数据表", fontsize=8.5, color="#666666")
    ax.axis("off")
    fig.tight_layout(rect=[0.02, 0.02, 0.98, 0.87])
    path = OUT / "fig9_nanchang_event_network_round3.png"
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


if __name__ == "__main__":
    paths = [
        forest("fig4_pre_gate_precision_round3.png", "级联准入前置候选的条件证据支持精度", [("支持精度", 69.18, 66.51, 71.96), ("不支持或冲突率", 29.17, 26.39, 31.81)]),
        forest("fig5_final_strict_precision_round3.png", "最终严格层的条件证据支持精度", [("支持精度", 99.28, 98.52, 99.65), ("不支持或冲突率", 0.41, 0.16, 1.05)]),
        event_graph(),
    ]
    print("\n".join(str(p) for p in paths))
