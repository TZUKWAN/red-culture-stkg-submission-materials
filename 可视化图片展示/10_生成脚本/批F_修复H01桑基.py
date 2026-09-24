# -*- coding: utf-8 -*-
"""批F_修复H01桑基.py — 重绘 H01 全库级联准入 Sankey（带流带 + 短标签）"""
import sys, os
sys.path.insert(0, r"D:\REDCULTUREDATA\可视化输出\10_生成脚本")
from style_lib import *
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import numpy as np

SCR = "批F_修复H01桑基.py"
W, H = 13.2, 7.8
fig, ax = plt.subplots(figsize=(W, H))
ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")

cols = [("全库入口", 0.95, 0.80), ("前置分层", 3.25, 0.80), ("证据语义门", 5.75, 0.80),
        ("门内再分层", 8.25, 0.80), ("最终三层", 10.75, 0.80)]
TOP, BOT = H - 0.85, 0.55

CI = {"全库断言": 0, "严格候选": 1, "前置上下文": 1, "前置未决": 1, "可定位": 2, "无证据": 2,
      "门STRICT": 3, "门CTX": 3, "门UNRES": 3, "终STRICT": 4, "终CTX": 4, "终UNRES": 4}
nodes = {
 "全库断言": dict(v=424150, c="#7D8B99", label="全库断言\n424,150"),
 "严格候选": dict(v=112158, c=TIER_C["STRICT"], label="严格候选\n112,158"),
 "前置上下文": dict(v=268047, c=TIER_C["CONTEXTUAL"], label="上下文\n268,047"),
 "前置未决": dict(v=43945, c=TIER_C["UNRESOLVED"], label="未决 43,945"),
 "可定位": dict(v=110052, c="#6E8CA0", label="可定位证据\n110,052"),
 "无证据": dict(v=2106, c="#AD9E8C", label="无证据 2,106"),
 "门STRICT": dict(v=31067, c=TIER_C["STRICT"], label="STRICT\n31,067"),
 "门CTX": dict(v=31282, c=TIER_C["CONTEXTUAL"], label="CONTEXTUAL\n31,282"),
 "门UNRES": dict(v=49809, c=TIER_C["UNRESOLVED"], label="UNRESOLVED\n49,809"),
 "终STRICT": dict(v=31067, c=TIER_C["STRICT"], label="STRICT\n31,067"),
 "终CTX": dict(v=299329, c=TIER_C["CONTEXTUAL"], label="CONTEXTUAL\n299,329"),
 "终UNRES": dict(v=93754, c=TIER_C["UNRESOLVED"], label="UNRESOLVED\n93,754"),
}
for nm, d in nodes.items():
    d["x"] = cols[CI[nm]][1]; d["w"] = cols[CI[nm]][2]

colorder = {0: ["全库断言"], 1: ["前置上下文", "严格候选", "前置未决"],
            2: ["可定位", "无证据"], 3: ["门UNRES", "门CTX", "门STRICT"],
            4: ["终CTX", "终UNRES", "终STRICT"]}
col_factor = {}
for ci, names in colorder.items():
    tot = sum(nodes[n]["v"] for n in names)
    span = TOP - BOT - 0.12 * (len(names) - 1)
    col_factor[ci] = span / tot
    y = BOT
    for n in names:
        h = nodes[n]["v"] * col_factor[ci]
        nodes[n]["y"] = y; nodes[n]["h"] = h
        y += h + 0.12

links = [
 ("全库断言", "严格候选", 112158), ("全库断言", "前置上下文", 268047), ("全库断言", "前置未决", 43945),
 ("严格候选", "可定位", 110052), ("严格候选", "无证据", 2106),
 ("可定位", "门STRICT", 31067), ("可定位", "门CTX", 31282), ("可定位", "门UNRES", 47703),
 ("无证据", "门UNRES", 2106),
 ("门STRICT", "终STRICT", 31067), ("门CTX", "终CTX", 31282), ("门UNRES", "终UNRES", 49809),
 ("前置上下文", "终CTX", 268047), ("前置未决", "终UNRES", 43945),
]
src_off = {}; dst_off = {}
for s, t, v in links:
    src_off.setdefault(s, 0.0); dst_off.setdefault(t, 0.0)
for s, t, v in links:
    sd = nodes[s]; td = nodes[t]
    fs = col_factor[CI[s]]; ft = col_factor[CI[t]]
    h_s = v * fs; h_t = v * ft
    y_s = sd["y"] + sd["h"] - src_off[s] - h_s
    y_t = td["y"] + td["h"] - dst_off[t] - h_t
    src_off[s] += h_s; dst_off[t] += h_t
    x0 = sd["x"] + sd["w"]; x1 = td["x"]
    xs = np.linspace(x0, x1, 100)
    ymid = (y_s + y_t) / 2
    yy = ymid + (y_s - ymid) * np.cos(np.pi * (xs - x0) / (x1 - x0))
    ax.fill_between(xs, yy, yy + min(h_s, h_t), color=td["c"], alpha=0.30, zorder=1)

for nm, d in nodes.items():
    ax.add_patch(FancyBboxPatch((d["x"], d["y"]), d["w"], d["h"], boxstyle="round,pad=0.012,rounding_size=0.03",
                                facecolor=d["c"], edgecolor="white", lw=1.0, alpha=0.94, zorder=3))
    if nm == "全库断言":
        ax.text(d["x"] + d["w"] + 0.10, d["y"] + d["h"] / 2, d["label"], ha="left", va="center",
                fontsize=8.2, color=INK, weight="bold", zorder=4)
    elif CI[nm] == 4:
        ax.text(d["x"] - 0.10, d["y"] + d["h"] / 2, d["label"], ha="right", va="center",
                fontsize=8.2, color=INK, weight="bold", zorder=4)
    elif d["h"] > 0.30:
        ax.text(d["x"] + d["w"] / 2, d["y"] + d["h"] / 2, d["label"], ha="center", va="center",
                fontsize=8.2, color="#FFFFFF", weight="bold", zorder=4)
    elif d["h"] > 0.10:
        ax.text(d["x"] + d["w"] + 0.08, d["y"] + d["h"] / 2, d["label"], ha="left", va="center",
                fontsize=7.2, color=INK, zorder=4)
for title, x, w in cols:
    ax.text(x + w / 2, H - 0.42, title, ha="center", fontsize=10.5, color=INK, weight="bold")
ax.set_title("全库级联准入总流：424,150 条断言的完整分层路径（Sankey）", fontsize=13)
fig.text(0.01, 0.012, "数据源：AUTHORITATIVE_RESULTS.md 定版数字。前置上下文=谓词未归一 264,635 + 关系域违例 3,412；"
                      "前置未决=作用域冲突 27,492 + 端点未决 16,393 + 人工遗留 60；门内 UNRESOLVED 49,809 含无证据 2,106；"
                      "replay 六项零检查 PASS（unexplained=0）", fontsize=7.8, color=FAINT)

for d in [r"D:\REDCULTUREDATA\可视化输出\01_候选图总库", r"D:\REDCULTUREDATA\可视化输出\02_精选图", r"D:\REDCULTUREDATA\可视化输出\03_正文主图"]:
    os.makedirs(d, exist_ok=True)
    fn = os.path.join(d, "H01_全库级联准入总流桑基图")
    fig.savefig(fn + ".png", dpi=300, bbox_inches="tight", facecolor=PAPER)
    fig.savefig(fn + ".svg", bbox_inches="tight", facecolor=PAPER)
    fig.savefig(fn + ".pdf", bbox_inches="tight", facecolor=PAPER)
print("H01 重绘完成")
