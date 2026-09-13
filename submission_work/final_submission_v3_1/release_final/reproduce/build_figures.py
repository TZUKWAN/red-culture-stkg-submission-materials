# -*- coding: utf-8 -*-
"""build_figures.py — 从 FINAL_NUMBERS/FINAL_TIERING 生成论文核心图（离线可重放）。

产物：release_final/figures/*.png（300dpi，出版级）
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT.parent / "experiments" / "07_provenance_semantic_gate"
FIG = ROOT / "figures"
GOLD, TEAL, GRAY, BLUE = "#c9a86a", "#4fd1c5", "#8a96ad", "#6f9fd8"

plt.rcParams.update({
    "font.family": ["Noto Sans SC", "Microsoft YaHei", "SimHei", "sans-serif"],
    "axes.unicode_minus": False, "figure.dpi": 300, "savefig.bbox": "tight",
    "axes.facecolor": "#f7f8fa", "axes.edgecolor": "#c8cdd6",
})


def main() -> int:
    FIG.mkdir(parents=True, exist_ok=True)

    # 图 1：证据门三层
    nums = json.loads((ROOT / "manifests" / "FINAL_NUMBERS.json").read_text(encoding="utf-8"))
    m = {x["metric"]: x["value"] for x in nums["metrics"]}
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    bars = ax.bar(["STRICT", "CONTEXTUAL", "UNRESOLVED"],
                  [m["gate_strict"], m["gate_contextual"], m["gate_unresolved"]],
                  color=[GOLD, BLUE, GRAY], width=0.62)
    for b in bars:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 600,
                f"{int(b.get_height()):,}", ha="center", fontsize=9)
    ax.set_ylabel("断言数（旧 strict 重分层宇宙 112,158）")
    ax.set_title("证据语义门最终三层（MEASURED，零持留）", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(FIG / "fig_gate_tiers.png")
    plt.close(fig)

    # 图 2：层 × 五档分布（来自 FINAL_TIERING_SUMMARY stats 段或 CSV 重算）
    cnt: Counter = Counter()
    strata = ("aligned", "mismatch_with_evidence", "recovery_A", "recovery_B", "recovery_C")
    for r in csv.DictReader(open(GATE / "FINAL_TIERING.csv", encoding="utf-8-sig")):
        cnt[(r["bucket"] if r["bucket"] in ("aligned", "mismatch_with_evidence")
             else "recovery_" + r["recovery_class"], r["semantic_support"])] += 1
    labels5 = ["FULLY_SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED",
               "CONTRADICTED", "INSUFFICIENT"]
    colors5 = [GOLD, "#e0d5b8", GRAY, "#d07b6a", BLUE]
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    bottom = [0] * len(strata)
    for lab, c in zip(labels5, colors5):
        vals = [cnt[(st, lab)] for st in strata]
        ax.barh(strata, vals, left=bottom, color=c, label=lab, height=0.6)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.set_xlabel("断言数")
    ax.set_title("各层 × 五档判定分布（生产队列 105,081 条）", fontsize=11)
    ax.legend(fontsize=7, ncol=5, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(FIG / "fig_strata_decisions.png")
    plt.close(fig)

    # 图 3：独立审计精度
    ar = json.loads((ROOT / "experiments" / "quality_audit" / "AUDIT_RESULTS.json")
                    .read_text(encoding="utf-8"))
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    ax.barh(["STRICT 支撑精度\n(强共识)", "STRICT 误报率\n(强共识)"],
            [ar["strict_support_precision_strong_consensus"],
             ar["strict_false_positive_rate"]],
            color=[TEAL, "#d07b6a"], height=0.5)
    ax.axvline(0.90, color=GOLD, linestyle="--", linewidth=1)
    ax.text(0.905, -0.28, "PASS 线 0.90", color=GOLD, fontsize=8)
    ax.set_xlim(0, 1.05)
    ax.set_title(f"独立双裁判盲评审计（n={ar['n_judged_both']}，决策 {ar['decision']}）",
                 fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(FIG / "fig_audit_precision.png")
    plt.close(fig)

    print(f"[figures] wrote 3 figures -> {FIG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
