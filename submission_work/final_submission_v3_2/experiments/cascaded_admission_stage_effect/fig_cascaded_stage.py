# -*- coding: utf-8 -*-
"""fig_cascaded_stage.py — 级联准入前后严格知识证据质量变化（单图，出版级）。"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
FIG = HERE.parents[1] / "figures"
GOLD, BLUE, GRAY = "#c9a86a", "#4f9dd1", "#8a96ad"

plt.rcParams.update({
    "font.family": ["Noto Sans SC", "Microsoft YaHei", "SimHei", "sans-serif"],
    "axes.unicode_minus": False, "figure.dpi": 300, "savefig.bbox": "tight",
})

stages = ["Pre-Gate Strict Candidate\n（112,158 条候选；若直接发布）",
          "Final STRICT\n（31,067 条；证据语义核验后）"]
rates = [29.79, 42.55]
cis = [(28.47, 31.16), (40.53, 44.59)]
colors = [GRAY, BLUE]

fig, ax = plt.subplots(figsize=(6.0, 3.8))
bars = ax.bar(stages, rates, color=colors, width=0.5,
              yerr=[[r - c[0] for r, c in zip(rates, cis)],
                    [c[1] - r for r, c in zip(rates, cis)]],
              capsize=6, error_kw={"elinewidth": 1.2})
for b, r, c in zip(bars, rates, cis):
    ax.text(b.get_x() + b.get_width() / 2, c[1] + 1.2,
            f"{r:.2f}%", ha="center", fontsize=10, fontweight="bold")
ax.annotate("", xy=(1, 46.5), xytext=(0, 34),
            arrowprops={"arrowstyle": "->", "color": GOLD, "lw": 1.6})
ax.text(0.52, 41.5, "+26.15 pp\n（强共识口径）", color="#8a6d1f", fontsize=9,
        ha="center")
ax.set_ylim(0, 55)
ax.set_ylabel("独立双裁判强共识证据支持率")
ax.set_title("级联准入前后严格知识证据质量变化", fontsize=12)
ax.spines[["top", "right"]].set_visible(False)
ax.text(0.99, -0.16,
        "样本：4,427 条分层独立审计（强共识口径）；误差线为 95%CI。"
        "门外加权 STRICT 机会 0.66% [0.40, 0.97]。",
        transform=ax.transAxes, ha="right", fontsize=7.5, color="#6b7893")
FIG.mkdir(parents=True, exist_ok=True)
for suffix in ("png", "pdf"):
    fig.savefig(FIG / f"fig_cascaded_admission_stage_effect.{suffix}")
plt.close(fig)
print(f"[fig] wrote fig_cascaded_admission_stage_effect.png/pdf -> {FIG}")
