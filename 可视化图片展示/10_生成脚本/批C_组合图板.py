# -*- coding: utf-8 -*-
"""批C_组合图板.py — 8 组组合图板（板1-板8），对应清单 §29 推荐主题。
每板 2×2 或 1×3 子图布局，子图编号(a)(b)(c)(d)，统一样式，适合论文单页。"""
import sys, os, json, collections
sys.path.insert(0, r"D:\REDCULTUREDATA\可视化输出\10_生成脚本")
from style_lib import *
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Rectangle
import numpy as np
import pandas as pd

MID = r"D:\REDCULTUREDATA\可视化输出\11_数据中间表"
SCR = "批C_组合图板.py"
BOARD = r"D:\REDCULTUREDATA\可视化输出\05_组合图板"

def board_fig(fig_id, zh, w, h, nrows, ncols, note, data_src, size="特大"):
    fig, axes = plt.subplots(nrows, ncols, figsize=(w, h))
    fig.suptitle("")  # 不用 suptitle，标题由各板自定
    return fig, np.atleast_2d(axes)

def panel_label(ax, s):
    ax.text(-0.08, 1.06, s, transform=ax.transAxes, fontsize=13, fontweight="bold", color=INK)

def foot(fig, txt):
    fig.text(0.01, 0.008, txt, fontsize=8, color=FAINT)

def save_board(fig, fig_id, zh, note, src):
    fn = f"{fig_id}_{zh}"
    fig.savefig(os.path.join(BOARD, fn + ".png"), dpi=300, bbox_inches="tight", facecolor=PAPER)
    fig.savefig(os.path.join(BOARD, fn + ".svg"), bbox_inches="tight", facecolor=PAPER)
    fig.savefig(os.path.join(BOARD, fn + ".pdf"), bbox_inches="tight", facecolor=PAPER)
    with open(os.path.join(r"D:\REDCULTUREDATA\可视化输出\12_图件清单", "生成登记.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"图号": fig_id, "图名": zh, "文件名": fn, "类别": "组合图板",
                            "脚本": SCR, "数据源": src, "说明": note, "格式": ["png", "svg", "pdf"]},
                           ensure_ascii=False) + "\n")
    plt.close(fig)
    print(f"[saved] {fn}")

T01 = pd.read_csv(os.path.join(MID, "T01_省域断言统计.csv"))
T01s = T01[~T01["省份"].str.contains("/", na=False)].sort_values("断言总数", ascending=False)
T05 = pd.read_csv(os.path.join(MID, "T05_断言时间年分布.csv"))
T02 = pd.read_csv(os.path.join(MID, "T02_实体类型分布.csv"))
T03 = pd.read_csv(os.path.join(MID, "T03_谓词分布.csv"))
T07 = pd.read_csv(os.path.join(MID, "T07_证据门五档支持.csv"))

def sup_key(s):
    for k in SUP_C:
        if k in str(s):
            return k
    return str(s)

T09 = pd.read_csv(os.path.join(MID, "T09_级联准入漏斗.csv"))
T10 = pd.read_csv(os.path.join(MID, "T10_全库三层归因.csv"))
T11 = pd.read_csv(os.path.join(MID, "T11_来源成员数分布.csv"))
T16 = pd.read_csv(os.path.join(MID, "T16_历史阶段×省域时空格.csv"))
T36 = pd.read_csv(os.path.join(MID, "T36_大事件Top30.csv"))
T45 = pd.read_csv(os.path.join(MID, "T45_五档典型案例.csv"))
E15 = json.load(open(os.path.join(MID, "E15_门内审计核心指标.csv")) if False else open(os.path.join(MID, "E09_门内审计.json"), encoding="utf-8"))
E14 = json.load(open(os.path.join(MID, "E08_门外审计.json"), encoding="utf-8"))

# ============ 板1 语料与图谱总体规模 ============
fig, axes = board_fig("板1", "语料与图谱总体规模组合图板", 12.6, 8.6, 2, 2, "", ["T01","T02","T03","T05"])
ax = axes[0][0]
prov = T01s.head(13)[::-1]
ax.barh(prov["省份"], prov["断言总数"] / 10000, color=M["雾蓝"], height=0.62, zorder=3)
for i, v in enumerate((prov["断言总数"] / 10000).values):
    ax.annotate(f"{v:.1f}", (v, i), xytext=(4, 0), textcoords="offset points", va="center", fontsize=8, color=INK)
ax.set_xlabel("断言数（万）"); ax.set_title("十三省域知识产出规模")
panel_label(ax, "(a)"); despine(ax); light_grid(ax, axis="x")

ax = axes[0][1]
tt = T05.groupby("年")["总数"].sum()
ax.fill_between(tt.index, tt.values / 1000, color=M["雾蓝"], alpha=0.30, zorder=2)
ax.plot(tt.index, (tt.rolling(7, center=True).mean() / 1000), color=TIER_C["STRICT"], lw=1.6, zorder=3)
for y in (1927, 1937, 1949):
    ax.axvline(y, color=AXIS, lw=0.9, ls="--", zorder=1)
    ax.annotate(str(y), (y, ax.get_ylim()[1] * 0.92), fontsize=8.5, color=FAINT, ha="center")
ax.set_xlabel("年份"); ax.set_ylabel("断言数（千）"); ax.set_title("知识的时间分布与革命史节点")
panel_label(ax, "(b)"); despine(ax); light_grid(ax)

ax = axes[1][0]
top8 = T02.head(8)
xs = np.arange(len(top8))
ax.bar(xs, top8["数量"] / 10000, color=SEQ10[:8], width=0.62, zorder=3)
ax.set_xticks(xs); ax.set_xticklabels([ez(t) for t in top8["实体类型"]], fontsize=8.5)
for x, v in zip(xs, top8["数量"] / 10000):
    ax.annotate(f"{v:.2f}", (x, v), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8, color=FAINT)
ax.set_ylabel("实体数（万）"); ax.set_title("规范实体类型构成（Top8）")
panel_label(ax, "(c)"); despine(ax); light_grid(ax)

ax = axes[1][1]
p = T03.copy(); p["is_raw"] = p["谓词"].astype(str).str.startswith("raw:")
g = p.groupby("is_raw")["断言数"].sum()
vals = [g.get(False, 0), g.get(True, 0)]
xs = np.arange(2)
ax.bar(xs, [vals[0] / 10000, vals[1] / 10000], color=[M["雾蓝"], M["驼灰"]], width=0.45, zorder=3)
for x, v in zip(xs, vals):
    ax.annotate(f"{v/10000:.1f}万", (x, v / 10000), xytext=(0, 4), textcoords="offset points",
                ha="center", fontsize=9, color=INK)
ax.set_xticks(xs); ax.set_xticklabels(["规范谓词", "原始谓词（raw:）"])
ax.set_ylabel("断言数（万）"); ax.set_title("谓词规范化程度总览")
panel_label(ax, "(d)"); despine(ax); light_grid(ax)
fig.suptitle("语料与图谱总体规模", x=0.5, y=0.985, fontsize=15, fontweight="bold", color=INK)
foot(fig, "数据源：最终库 research_assertions / research_entities / research_study_regions（sha256 020d4905…）；(a)跨省组合断言未计入单省")
save_board(fig, "板1", "语料与图谱总体规模组合图板", "四联板：省域规模/时间分布/实体构成/谓词规范化",
           ["T01", "T05", "T02", "T03"])

# ============ 板2 级联准入总览 ============
fig, axes = board_fig("板2", "全库级联准入组合图板", 12.6, 8.6, 2, 2, "", ["T09","T10","T07","E16"])
fun = dict(zip(T09["阶段"], T09["断言数"]))
ax = axes[0][0]
stages = [("全库入口", 424150), ("严格候选（证据门）", 112158), ("证据可定位", 110052), ("STRICT（严格层）", 31067)]
ymax = 424150
for i, (lab, v) in enumerate(stages):
    w = v / ymax
    ax.barh(3 - i, w * 100, color=TIER_C["STRICT"] if i == 3 else SEQ10[i], height=0.58, zorder=3)
    ax.annotate(f"{v:,}（{v/424150*100:.1f}%）", (w * 100, 3 - i), xytext=(5, 0),
                textcoords="offset points", va="center", fontsize=9, color=INK)
ax.set_yticks(range(4)); ax.set_yticklabels([s[0] for s in stages][::-1], fontsize=9.5)
ax.set_xlabel("占全库比例（%）"); ax.set_xlim(0, 118)
ax.set_title("级联准入漏斗（全库→严格层）")
panel_label(ax, "(a)"); despine(ax, keep=("left", "bottom")); light_grid(ax, axis="x")

ax = axes[0][1]
labels = ["STRICT\n31,067", "CONTEXTUAL\n299,329", "UNRESOLVED\n93,754"]
vals = [31067, 299329, 93754]
wedges, _ = ax.pie(vals, colors=[TIER_C["STRICT"], TIER_C["CONTEXTUAL"], TIER_C["UNRESOLVED"]],
                   startangle=90, counterclock=False,
                   wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2))
for wdg, lab in zip(wedges, labels):
    ang = np.deg2rad((wdg.theta1 + wdg.theta2) / 2)
    x, y = np.cos(ang) * 0.79, np.sin(ang) * 0.79
    ax.text(x, y, lab, ha="center", va="center", fontsize=8.6, color="white", fontweight="bold")
ax.text(0, 0, "全库\n424,150", ha="center", va="center", fontsize=11, fontweight="bold", color=INK)
ax.set_title("最终三层知识状态构成")
panel_label(ax, "(b)")

ax = axes[1][0]
t10s = T10.sort_values("断言数")
ax.barh([wrap_zh(x, 12) for x in t10s["归因路径"]], t10s["断言数"] / 10000,
        color=[TIER_C["UNRESOLVED"] if "UNRESOLVED" in p else (TIER_C["CONTEXTUAL"] if "CONTEXTUAL" in p else TIER_C["STRICT"]) for p in t10s["归因路径"]],
        height=0.62, zorder=3)
ax.set_xlabel("断言数（万）"); ax.set_title("三层知识状态来源分解（11条归因路径）")
panel_label(ax, "(c)"); despine(ax); light_grid(ax, axis="x")

ax = axes[1][1]
sup = T07.sort_values("断言数", ascending=False)
xs = np.arange(len(sup))
ax.bar(xs, sup["断言数"] / 10000, color=[SUP_C[sup_key(s)] for s in sup["语义支持等级"]], width=0.6, zorder=3)
for x, v in zip(xs, sup["断言数"]):
    ax.annotate(f"{v:,}", (x, v / 10000), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.5, color=INK)
ax.set_xticks(xs); ax.set_xticklabels([SUP_ZH[sup_key(s["语义支持等级"])].split("(")[0] for _, s in sup.iterrows()], fontsize=9)
ax.set_ylabel("断言数（万）"); ax.set_title("证据语义门五档支持分布")
panel_label(ax, "(d)"); despine(ax); light_grid(ax)
fig.suptitle("全库级联准入总览", x=0.5, y=0.985, fontsize=15, fontweight="bold", color=INK)
foot(fig, "数据源：AUTHORITATIVE_RESULTS.md 定版数字 + gate_verdict_details（105,081判定档案）")
save_board(fig, "板2", "全库级联准入组合图板", "漏斗/环形/归因/五档四联板",
           ["T09", "T10", "T07", "AUTHORITATIVE_RESULTS"])

# ============ 板3 证据语义核验（三概念+定位桶+五档案例） ============
fig, axes = board_fig("板3", "证据语义核验组合图板", 12.6, 4.4, 1, 3, "", ["E16","T06","T07"])
ax = axes[0][0]
abc = [("A 谱系完整率", 44.72, 50161, 112158), ("B 证据定位率", 98.12, 110052, 112158), ("C 语义支持率", 28.23, 31067, 110052)]
xs = np.arange(3)
for i, (n, v, num, den) in enumerate(abc):
    # Wilson 95% CI
    z = 1.96; ph = num / den
    lo = (ph + z*z/(2*den) - z*np.sqrt((ph*(1-ph)+z*z/(4*den))/den)) / (1+z*z/den)
    hi = (ph + z*z/(2*den) + z*np.sqrt((ph*(1-ph)+z*z/(4*den))/den)) / (1+z*z/den)
    ax.errorbar(i, v, yerr=[[v - lo*100], [hi*100 - v]], fmt="o", ms=10,
                color=SEQ10[i], capsize=5, lw=1.6, zorder=3)
    ax.annotate(f"{v:.2f}%", (i, v), xytext=(12, -3), textcoords="offset points", fontsize=9.5, color=INK)
ax.set_xticks(xs); ax.set_xticklabels(["A 谱系", "B 定位", "C 支持"])
ax.set_ylabel("比率（%，Wilson 95%CI）"); ax.set_ylim(0, 112)
ax.set_title("三概念分离：有链≠可取回≠真支持")
panel_label(ax, "(a)"); despine(ax); light_grid(ax)

ax = axes[0][1]
T06 = pd.read_csv(os.path.join(MID, "T06_六层定位桶.csv")).sort_values("规模")
y = np.arange(len(T06))
ax.barh(y, T06["规模"] / 1000, color=M["青灰"], height=0.6, zorder=2, label="定位桶规模")
ax.barh(y, T06["已测STRICT"] / 1000, color=TIER_C["STRICT"], height=0.6, zorder=3, label="其中严格层")
ax.set_yticks(y); ax.set_yticklabels(T06["定位桶"], fontsize=8.6)
for i, (s, st) in enumerate(zip(T06["规模"], T06["已测STRICT"])):
    ax.annotate(f" {st/s*100:.1f}%", (s / 1000, i), xytext=(5, 0), textcoords="offset points",
                va="center", fontsize=8.4, color=INK)
ax.set_xlabel("断言数（千）"); ax.set_xlim(0, 56)
ax.set_title("六层证据定位桶与严格层转化率")
ax.legend(loc="lower right", fontsize=8.5)
panel_label(ax, "(b)"); despine(ax); light_grid(ax, axis="x")

ax = axes[0][2]
sup = T07.sort_values("断言数")
ax.barh([SUP_ZH[sup_key(s)] for s in sup["语义支持等级"]], sup["断言数"] / 10000,
        color=[SUP_C[sup_key(s)] for s in sup["语义支持等级"]], height=0.6, zorder=3)
for i, v in enumerate(sup["断言数"]):
    ax.annotate(f"{v:,}", (v / 10000, i), xytext=(5, 0), textcoords="offset points", va="center", fontsize=8.5, color=INK)
ax.set_xlabel("断言数（万，注意对数观感——UNSUPPORTED 4.5万与 CONTRADICTED 27条差距悬殊）")
ax.set_xscale("log"); ax.set_xlim(0.5, 12)
ax.set_title("五档语义支持结构（对数轴）")
panel_label(ax, "(c)"); despine(ax); light_grid(ax, axis="x")
fig.suptitle("证据语义核验：来源追溯 → 证据定位 → 语义支持", x=0.5, y=1.0, fontsize=15, fontweight="bold", color=INK)
foot(fig, "数据源：FINAL_EVIDENCE_REPORT.md 三概念分离、六层定位桶；gate_verdict_details 五档判定（checkpoint 105,081）")
save_board(fig, "板3", "证据语义核验组合图板", "A/B/C三概念+定位桶+五档三联板",
           ["E16", "T06", "T07"])

# ============ 板4 门内门外双向审计 ============
fig, axes = board_fig("板4", "门内门外双向审计组合图板", 12.6, 4.4, 1, 3, "", ["E09","E08"])
ax = axes[0][0]
items = [("强共识支持精度", 0.9928, 0.9852, 0.9965), ("仅FULLY精度", 0.8066, 0.7806, 0.8302),
         ("强共识误报率", 0.0041, 0.0016, 0.0105), ("五档完全一致率", 0.3598, None, None)]
xs = np.arange(len(items))
for i, (n, p, lo, hi) in enumerate(items):
    if lo is not None:
        ax.errorbar(i, p, yerr=[[p - lo], [hi - p]], fmt="o", ms=9, color=M["雾蓝"], capsize=5, lw=1.6, zorder=3)
    else:
        ax.scatter(i, p, s=80, color=M["雾蓝"], zorder=3)
    ax.annotate(f"{p*100:.2f}%", (i, p), xytext=(10, -2), textcoords="offset points", fontsize=8.8, color=INK)
ax.set_xticks(xs); ax.set_xticklabels([wrap_zh(n, 6) for n, *_ in items], fontsize=8.6)
ax.set_ylabel("比率"); ax.set_ylim(-0.05, 1.12)
ax.set_title("门内 STRICT 独立审计（n=4,427 双裁判）")
panel_label(ax, "(a)"); despine(ax); light_grid(ax)

ax = axes[0][1]
o = [("五档一致率", 0.8126, 0.8015, 0.8232), ("推荐状态一致率", 0.8899, 0.8808, 0.8983),
     ("严格资格一致率", 0.9352, 0.9280, 0.9418), ("三层精确一致", 0.4303, 0.4166, 0.4441)]
for i, (n, p, lo, hi) in enumerate(o):
    ax.errorbar(i, p, yerr=[[p - lo], [hi - p]], fmt="s", ms=9, color=M["陶砂"], capsize=5, lw=1.6, zorder=3)
    ax.annotate(f"{p*100:.1f}%", (i, p), xytext=(10, -2), textcoords="offset points", fontsize=8.8, color=INK)
ax.set_xticks(range(4)); ax.set_xticklabels([wrap_zh(n, 6) for n, *_ in o], fontsize=8.6)
ax.set_ylim(0.30, 1.02)
ax.set_title("门外宇宙审计（n=5,000 分层，双有效 4,957）")
panel_label(ax, "(b)"); despine(ax); light_grid(ax)

ax = axes[0][2]
# 双向评价：精度侧 vs 遗漏侧
ax.add_patch(FancyBboxPatch((0.6, 2.2), 3.6, 1.9, boxstyle="round,pad=0.1,rounding_size=0.12",
                            facecolor="#EDF1F4", edgecolor=M["雾蓝"], lw=1.4))
ax.text(2.4, 3.75, "门内：精度侧", ha="center", fontsize=11, fontweight="bold", color=INK)
ax.text(2.4, 2.95, "99.28% 支持精度\n（965/972 强共识）\n误报仅 0.41%", ha="center", fontsize=9.2, color=INK, linespacing=1.5)
ax.add_patch(FancyBboxPatch((6.0, 2.2), 3.6, 1.9, boxstyle="round,pad=0.1,rounding_size=0.12",
                            facecolor="#F6F1EA", edgecolor=M["陶砂"], lw=1.4))
ax.text(7.8, 3.75, "门外：遗漏侧", ha="center", fontsize=11, fontweight="bold", color=INK)
ax.text(7.8, 2.95, "强共识 STRICT 机会率\n样本 0.63% / 加权 0.66%\n[0.40%, 0.97%]", ha="center", fontsize=9.2, color=INK, linespacing=1.5)
ax.add_patch(FancyArrowPatch((4.4, 3.15), (5.8, 3.15), arrowstyle="<|-|>", mutation_scale=16, color=FAINT, lw=1.3))
ax.text(5.1, 3.38, "双向\n质量", ha="center", fontsize=8.6, color=FAINT, linespacing=1.3)
ax.text(5.1, 1.55, "保守准入未造成大规模高质量知识漏失", ha="center", fontsize=10, color=INK, fontweight="bold")
ax.text(5.1, 0.75, "κ：门内0.184 vs 门外0.514", ha="center", fontsize=9, color=FAINT)
ax.set_xlim(0, 10.2); ax.set_ylim(0.3, 4.4); ax.axis("off")
ax.set_title("门内/门外双向质量评价框架")
panel_label(ax, "(c)")
fig.suptitle("门内 STRICT 审计 × 门外宇宙审计：双向质量评价", x=0.5, y=1.0, fontsize=15, fontweight="bold", color=INK)
foot(fig, "数据源：AUDIT_RESULTS.json（PASS）/ OUTSIDE_GATE_AUDIT_RESULTS.json（seed=20260916，stratified bootstrap B=10,000）")
save_board(fig, "板4", "门内门外双向审计组合图板", "门内CI+门外CI+双向框架三联板",
           ["E09", "E08"])

# ============ 板5 选择性预测与风险路由 ============
fig, axes = board_fig("板5", "选择性预测与风险路由组合图板", 12.6, 4.4, 1, 3, "", ["E01","E02","E21"])
curve = pd.read_csv(os.path.join(MID, "E01_预算曲线.csv"))
ax = axes[0][0]
bcol = [c for c in curve.columns if "budget" in c.lower() or "预算" in c][0]
pooled = curve[curve[curve.columns[0]].astype(str).str.contains("pooled|POOLED|pooled", case=False, na=False)]
if len(pooled) == 0:
    pooled = curve
agcol = [c for c in curve.columns if "agree" in c.lower() or "一致" in c][0]
ax.plot(pooled[bcol] * 100 if pooled[bcol].max() <= 1 else pooled[bcol], pooled[agcol], "-o",
        color=M["雾蓝"], lw=2, ms=6, zorder=3)
ax.axhline(0.8812, color=M["陶砂"], ls="--", lw=1.2)
ax.annotate("gpt-5.6-luna 参考线 0.8812", (52, 0.8812), xytext=(0, 6), textcoords="offset points", fontsize=8.6, color=M["陶砂"])
ax.axvline(30, color=AXIS, ls=":", lw=1)
ax.annotate("操作点 b=30%", (30, 0.30), xytext=(6, 0), textcoords="offset points", fontsize=8.6, color=FAINT)
ax.set_xlabel("升级预算（%）"); ax.set_ylabel("一致率（leave-B-out）")
ax.set_title("预算-质量曲线（gpt-oss-20b 同模型）")
panel_label(ax, "(a)"); despine(ax); light_grid(ax)

ax = axes[0][1]
routes = [("R1 随机", 0.4368), ("R2 置信", 0.4253), ("R3 margin", 0.4368), ("R4 熵", 0.4368),
          ("R5 分歧", 0.4483), ("R6 风险", 0.4751), ("R7 oracle", 0.5402)]
xs = np.arange(len(routes))
cols = [M["石板"]] * 5 + [TIER_C["STRICT"], M["驼灰"]]
ax.bar(xs, [v for _, v in routes], color=cols, width=0.6, zorder=3)
for x, (n, v) in zip(xs, routes):
    ax.annotate(f"{v:.3f}", (x, v), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.6, color=INK)
ax.set_xticks(xs); ax.set_xticklabels([n for n, _ in routes], fontsize=8.6)
ax.set_ylim(0.38, 0.58); ax.set_ylabel("一致率（b=30%）")
ax.set_title("七种路由策略对比（R6 判语：略优）")
panel_label(ax, "(b)"); despine(ax); light_grid(ax)

ax = axes[0][2]
ab = pd.read_csv(os.path.join(MID, "E21_论文表2A_选择性语义判定.csv"))
meth = ab["方法"].tolist()
metrics = ["接受覆盖率", "接受样本一致率", "安全覆盖率", "MacroF1"]
xs = np.arange(len(metrics))
for i, m in enumerate(meth):
    vals = [ab[ab["方法"] == m][c].values[0] for c in metrics]
    ax.scatter(xs, vals, s=76, color=SEQ10[i], label=m, zorder=3)
ax.set_xticks(xs); ax.set_xticklabels(["接受覆盖率", "接受一致率", "安全覆盖率", "Macro-F1"], fontsize=8.6)
ax.set_ylim(0.55, 1.05); ax.set_ylabel("指标值")
ax.set_title("四种语义判定方法对比（n=152 核心评价）")
ax.legend(fontsize=7.8, loc="lower left")
panel_label(ax, "(c)"); despine(ax); light_grid(ax)
fig.suptitle("选择性预测与风险路由：预算换质量、风险排序优于启发式", x=0.5, y=1.0, fontsize=15, fontweight="bold", color=INK)
foot(fig, "数据源：budget_v2/CURVE_LOCAL.csv、ROUTING_COMPARISON.csv；论文表2（n=152，规则—Qwen 一致性选择风险 0.0086）")
save_board(fig, "板5", "选择性预测与风险路由组合图板", "预算曲线+路由对比+方法对比三联板",
           ["E01", "E02", "E21"])

# ============ 板6 时空作用域 ============
fig, axes = board_fig("板6", "时空作用域与历史格局组合图板", 12.6, 4.4, 1, 3, "", ["T16","T36","E06"])
ax = axes[0][0]
pv = T16.pivot_table(index="阶段序", columns="省份", values="时间证据数", aggfunc="sum").fillna(0)
order = ["上海市", "江苏省", "安徽省", "江西省", "湖北省", "湖南省", "重庆市", "四川省", "贵州省", "云南省", "浙江省", "青海省", "西藏自治区"]
order = [p for p in order if p in pv.columns]
pv = pv[order]
cmap = mpl.colors.LinearSegmentedColormap.from_list("m", BLUE_SEQ)
im = ax.imshow(np.log1p(pv.values), cmap=cmap, aspect="auto")
ax.set_xticks(range(len(order))); ax.set_xticklabels([p[:2] for p in order], fontsize=8, rotation=45)
_stage_map = {0: "建党前", 1: "建党与大革命", 2: "土地革命", 3: "抗日战争", 4: "解放战争", 5: "革命和建设", 6: "改革开放", 7: "新时代"}
stages = [_stage_map.get(int(i), str(i)) for i in pv.index]
ax.set_yticks(range(len(pv))); ax.set_yticklabels(stages, fontsize=8.4)
ax.set_title("事件时空格证据强度（log 色标）")
panel_label(ax, "(a)"); despine(ax, keep=())

ax = axes[0][1]
tt = T36.head(15)[::-1]
ax.barh([wrap_zh(n, 8) for n in tt["事件名"]], tt["严格断言数"], color=M["陶砂"], height=0.62, zorder=3)
for i, v in enumerate(tt["严格断言数"]):
    ax.annotate(f"{v}", (v, i), xytext=(4, 0), textcoords="offset points", va="center", fontsize=8.4, color=INK)
ax.set_xlabel("严格断言数"); ax.set_title("重大事件框架规模（Top15）")
panel_label(ax, "(b)"); despine(ax); light_grid(ax, axis="x")

ax = axes[0][2]
T18 = pd.read_csv(os.path.join(MID, "T18_地点版本演化.csv"))
T18s = T18.dropna(subset=["起"]).head(24)
for i, (_, r) in enumerate(T18s.iterrows()):
    try:
        y0 = int(str(r["起"])[:4]); y1 = int(str(r["止"])[:4])
    except Exception:
        continue
    y1 = min(y1, 2026)
    ax.plot([y0, y1], [i, i], color=M["驼灰"], lw=5, solid_capstyle="round", alpha=0.75, zorder=2)
ax.set_yticks(range(len(T18s)))
ax.set_yticklabels([wrap_zh(n, 8) for n in T18s["历史名"]], fontsize=7.4)
ax.set_xlabel("年份"); ax.set_title("历史地名版本区间（PlaceVersion，前24条）")
panel_label(ax, "(c)"); despine(ax); light_grid(ax, axis="x")
fig.suptitle("时空作用域与历史格局", x=0.5, y=1.0, fontsize=15, fontweight="bold", color=INK)
foot(fig, "数据源：research_event_spatiotemporal_cells（7,067格）/ research_event_frames / research_place_versions（72版本）")
save_board(fig, "板6", "时空作用域与历史格局组合图板", "时空热力+事件规模+地名版本三联板",
           ["T16", "T36", "T18"])

# ============ 板7 谓词规范化与关系契约 ============
fig, axes = board_fig("板7", "谓词规范化与关系结构组合图板", 12.6, 4.4, 1, 3, "", ["T03","T04","T21"])
ax = axes[0][0]
p = T03.copy(); p["类"] = np.where(p["谓词"].astype(str).str.startswith("raw:"), "原始", "规范")
top = p.groupby("谓词")["断言数"].sum().sort_values(ascending=False).head(18)
tt = p[p["谓词"].isin(top.index)].pivot_table(index="谓词", columns="类", values="断言数", aggfunc="sum").fillna(0)
tt = tt.loc[top.index[:18]]
tt = tt.div(tt.sum(axis=1), axis=0)
y = np.arange(len(tt))[::-1]
ax.barh(y, tt.get("规范", pd.Series(0, index=tt.index)), color=M["雾蓝"], height=0.62, zorder=3, label="规范谓词")
ax.barh(y, tt.get("原始", pd.Series(0, index=tt.index)), left=tt.get("规范", pd.Series(0, index=tt.index)),
        color=M["驼灰"], height=0.62, zorder=3, label="原始（raw:）")
ax.set_yticks(y); ax.set_yticklabels([pz(x) for x in tt.index], fontsize=8.2)
ax.set_xlabel("占比"); ax.set_xlim(0, 1.0)
ax.set_title("高频谓词的规范化构成")
ax.legend(fontsize=8.5, loc="lower right")
panel_label(ax, "(a)"); despine(ax); light_grid(ax, axis="x")

ax = axes[0][1]
T04 = pd.read_csv(os.path.join(MID, "T04_谓词规范化映射.csv"))
t4 = T04.groupby("原始谓词")["断言数"].sum().sort_values(ascending=False).head(8)
xs = np.arange(len(t4))
ax.bar(xs, t4.values / 10000, color=M["驼灰"], width=0.6, zorder=3)
for x, v in zip(xs, t4.values):
    ax.annotate(f"{v/10000:.1f}万", (x, v / 10000), xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8.4, color=INK)
ax.set_xticks(xs); ax.set_xticklabels([wrap_zh(pz(x), 7) for x in t4.index], fontsize=8, rotation=30, ha="right")
ax.set_ylabel("涉及断言数（万）"); ax.set_title("未归一原始谓词 Top8（主要阻断源）")
panel_label(ax, "(b)"); despine(ax); light_grid(ax)

ax = axes[0][2]
T21 = pd.read_csv(os.path.join(MID, "T21_关系契约88谓词.csv"))
import ast
pairs = collections.Counter()
for _, r in T21.iterrows():
    try:
        ds = ast.literal_eval(r["定义域类型"]) if isinstance(r["定义域类型"], str) else []
        ts = ast.literal_eval(r["值域类型"]) if isinstance(r["值域类型"], str) else []
    except Exception:
        continue
    for d in ds:
        for t in ts:
            pairs[(ez(d), ez(t))] += 1
top = pairs.most_common(12)
xs = np.arange(len(top))
ax.bar(xs, [c for _, c in top], color=M["青灰"], width=0.6, zorder=3)
ax.set_xticks(xs); ax.set_xticklabels([f"{d}→{t}" for (d, t), _ in top], fontsize=7.6, rotation=38, ha="right")
ax.set_ylabel("契约谓词数"); ax.set_title("关系契约的类型组合（88谓词）")
panel_label(ax, "(c)"); despine(ax); light_grid(ax)
fig.suptitle("谓词规范化与关系契约结构", x=0.5, y=1.0, fontsize=15, fontweight="bold", color=INK)
foot(fig, "数据源：research_assertions predicate 字段、T04 映射表、research_relation_contract（88谓词）")
save_board(fig, "板7", "谓词规范化与关系结构组合图板", "规范化构成+阻断源+契约组合三联板",
           ["T03", "T04", "T21"])

# ============ 板8 典型案例与知识组织 ============
fig, axes = board_fig("板8", "典型案例与知识组织组合图板", 12.6, 8.6, 2, 2, "", ["T35","T45","T32"])
ax = axes[0][0]
evs = ["南昌起义", "秋收起义", "遵义会议", "八七会议"]
roles = collections.Counter()
for e in evs:
    df = pd.read_csv(os.path.join(MID, f"T35_案例_{e}.csv"))
    df = df[df["事件名"].str.contains(e.split("起义")[0] if "起义" in e else e, na=False)]
    for rc, c in df["角色类别"].value_counts().head(4).items():
        roles[rc] += c
top = roles.most_common(6)
xs = np.arange(len(top))
ax.bar(xs, [c for _, c in top], color=SEQ10[:6], width=0.6, zorder=3)
ax.set_xticks(xs); ax.set_xticklabels([wrap_zh(r, 6) for r, _ in top], fontsize=8.4)
ax.set_ylabel("角色连接数（四事件合计）"); ax.set_title("代表性事件的角色结构")
panel_label(ax, "(a)"); despine(ax); light_grid(ax)

ax = axes[0][1]
r = T45[(T45["五档"] == "FULLY_SUPPORTED")].iloc[0]
ax.axis("off")
ax.set_xlim(0, 1); ax.set_ylim(0, 1)
ax.add_patch(FancyBboxPatch((0.05, 0.15), 0.9, 0.72, boxstyle="round,pad=0.03,rounding_size=0.05",
                            facecolor="#F2F4F3", edgecolor=SUP_C["FULLY_SUPPORTED"], lw=1.4))
ax.text(0.5, 0.78, "典型完全支持案例（STRICT）", ha="center", fontsize=10.5, fontweight="bold", color=INK)
ax.text(0.5, 0.60, f"{r['主体']} —{pz(r['谓词'])}— {r['客体']}", ha="center", fontsize=9.6, color=INK)
q = str(r["引文"])[:88]
ax.text(0.5, 0.38, "证据：「" + q + "…」", ha="center", fontsize=8.4, color=FAINT, wrap=True)
ax.text(0.5, 0.22, "判定：证据语义完全支持，保持严格层发布", ha="center", fontsize=8.8, color=SUP_C["FULLY_SUPPORTED"])
panel_label(ax, "(b)")

ax = axes[1][0]
T32 = pd.read_csv(os.path.join(MID, "T32_人物活跃年份.csv"))
person = T32["人物"].value_counts().index[0]
pp = T32[T32["人物"] == person].sort_values("年")
ax.fill_between(pp["年"], pp["断言数"], color=M["雾蓝"], alpha=0.32)
ax.plot(pp["年"], pp["断言数"], color=TIER_C["STRICT"], lw=1.4)
ax.set_xlabel("年份"); ax.set_ylabel("涉及断言数"); ax.set_title(f"「{person}」活动年份档案")
panel_label(ax, "(c)"); despine(ax); light_grid(ax)

ax = axes[1][1]
T19 = pd.read_csv(os.path.join(MID, "T19_事件关系.csv"))
rc = T19["关系"].value_counts().head(8)
xs = np.arange(len(rc))
ax.bar(xs, rc.values, color=[SEQ10[i % 10] for i in range(len(rc))], width=0.6, zorder=3)
ax.set_xticks(xs); ax.set_xticklabels(rc.index, fontsize=8.4)
ax.set_ylabel("关系条数"); ax.set_title("事件间关系类型分布（499条）")
panel_label(ax, "(d)"); despine(ax); light_grid(ax)
fig.suptitle("典型案例与知识组织", x=0.5, y=0.985, fontsize=15, fontweight="bold", color=INK)
foot(fig, "数据源：research_event_roles / gate_verdict_details / research_assertions / research_event_relations")
save_board(fig, "板8", "典型案例与知识组织组合图板", "角色结构+案例卡+人物档案+事件关系四联板",
           ["T35", "T45", "T32", "T19"])

print("组合图板 8 组全部完成")
