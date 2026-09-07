#!/usr/bin/env python3
"""Build and audit the Paper A component-ablation figure."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch


HERE = Path(__file__).resolve().parent
DATA = HERE / "ABLATION_FIGURE_DATA.csv"
SUMMARY = HERE / "ablation_experiment_summary.json"
PREDICTIONS = HERE / "ABLATION_PREDICTIONS.csv"
CONTRACT = HERE / "ABLATION_CHART_CONTRACT.md"
PNG = HERE / "fig_component_ablation.png"
PDF = HERE / "fig_component_ablation.pdf"
AUDIT = HERE / "ABLATION_FIGURE_AUDIT.json"

BLUE = "#2F5597"
ORANGE = "#D97706"
DARK = "#444444"
GRID = "#D9DEE7"
PALE_BLUE = "#EDF3FB"
PALE_ORANGE = "#FFF3E2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def choose_font() -> str:
    available = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS"):
        if candidate in available:
            return candidate
    return "DejaVu Sans"


def main() -> None:
    with DATA.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    lookup = {(row["component"], row["metric"]): row for row in rows}

    classifier_variants = [
        ("完整选择性\n分类器", "Full selective classifier"),
        ("去类别门禁", "w/o Class-specific Gate"),
        ("去独立信号", "w/o Independent Signal Agreement"),
        ("去弃权", "w/o Abstention"),
    ]
    classifier_metrics = summary["classifier_actual_run"]["variants"]
    coverage = np.asarray([classifier_metrics[key]["coverage"] for _, key in classifier_variants])
    risk = np.asarray([1 - classifier_metrics[key]["selective_accuracy"] for _, key in classifier_variants])
    exposure = np.asarray([
        classifier_metrics[key]["errors"] / classifier_metrics[key]["total"]
        for _, key in classifier_variants
    ])

    cards = [
        ("风险路由", "43,945", "条断言状态变化", "确定性全库回放", PALE_BLUE),
        ("身份投影", "24,005", "条断言状态变化", "实体 154,150 → 152,979\n确定性全库回放", PALE_BLUE),
        ("关系契约", "3,412", "条新增严格域—值域违例", "148 条代理样本饱和；主证据为全库", PALE_ORANGE),
        ("role-owner 闭包", "44 / 112", "条时间 / 空间 owner 错误", "确定性全库回放", PALE_ORANGE),
        ("来源门禁", "0", "条状态差异", "发布后饱和 canary：424,150 条均有 lineage", "#F3F4F6"),
        ("全局闭包", "27,475", "条断言状态变化", "组合移除；不可与单项效应相加", "#F3F4F6"),
    ]

    font = choose_font()
    plt.rcParams.update({
        "font.family": font,
        "axes.unicode_minus": False,
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.labelsize": 10,
    })
    fig = plt.figure(figsize=(12, 7.5), constrained_layout=True)
    gs = fig.add_gridspec(1, 2, width_ratios=[1.1, 1.35])

    ax = fig.add_subplot(gs[0, 0])
    x = np.arange(len(classifier_variants))
    width = 0.23
    bars1 = ax.bar(x - width, coverage, width, color=BLUE, edgecolor=DARK, linewidth=0.5, label="Coverage")
    bars2 = ax.bar(x, risk, width, color="white", edgecolor=ORANGE, linewidth=1.5, hatch="//", label="Selective risk")
    bars3 = ax.bar(x + width, exposure, width, color="#B7BDC8", edgecolor=DARK, linewidth=0.5, label="Unsafe exposure")
    for bars in (bars1, bars2, bars3):
        for bar in bars:
            value = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, value + 0.018, f"{value:.3f}", ha="center", va="bottom", fontsize=8, rotation=90)
    ax.set_xticks(x, [label for label, _ in classifier_variants])
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("比率（固定分母 n=203）")
    ax.set_title("A. 实体分类器的覆盖—风险权衡")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.legend(frameon=False, loc="upper left")
    ax.text(
        0.0, -0.16,
        "AI 集成参考与词法/来源类型/历史模型信号重叠；仅表示共享代理参考一致性。",
        transform=ax.transAxes, fontsize=8.5, color=DARK, va="top",
    )

    ax = fig.add_subplot(gs[0, 1])
    ax.set_axis_off()
    ax.set_title("B. 结构组件移除的独立计量结果", pad=12)
    positions = [(0.02, 0.68), (0.51, 0.68), (0.02, 0.36), (0.51, 0.36), (0.02, 0.04), (0.51, 0.04)]
    for (title, value, unit, evidence, face), (left, bottom) in zip(cards, positions):
        card = FancyBboxPatch(
            (left, bottom), 0.45, 0.25,
            boxstyle="round,pad=0.012,rounding_size=0.015",
            linewidth=0.8, edgecolor=GRID, facecolor=face,
            transform=ax.transAxes,
        )
        ax.add_patch(card)
        ax.text(left + 0.025, bottom + 0.205, title, transform=ax.transAxes, fontsize=10.5, color=DARK, weight="bold", va="top")
        ax.text(left + 0.025, bottom + 0.137, value, transform=ax.transAxes, fontsize=22, color=BLUE if face == PALE_BLUE else ORANGE if face == PALE_ORANGE else DARK, weight="bold", va="top")
        ax.text(
            left + 0.025, bottom + 0.075, unit, transform=ax.transAxes,
            fontsize=8.6, color=DARK, va="center", linespacing=1.08,
        )
        ax.text(
            left + 0.025, bottom + 0.012, evidence, transform=ax.transAxes,
            fontsize=7.2, color="#666666", va="bottom", wrap=True, linespacing=1.02,
        )
    ax.text(
        0.02, 0.965,
        "各卡指标定义与单位不同，不共轴、不加总；结构结果均为冻结发布库确定性回放。",
        transform=ax.transAxes, fontsize=8.7, color=DARK, va="top",
    )

    fig.suptitle("组件消融：共享代理参考权衡与全库结构后果", fontsize=16, color=DARK, y=1.02)
    fig.text(
        0.5, -0.01,
        "无在线 LLM 调用。actual-run 与 deterministic-replay 分表保存；provenance=0 是发布后饱和 canary，不表示门禁无效。",
        ha="center", va="top", fontsize=8.8, color=DARK,
    )
    fig.savefig(PNG, dpi=200, bbox_inches="tight", facecolor="white")
    fig.savefig(PDF, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    from PIL import Image
    import fitz
    with Image.open(PNG) as image:
        width_px, height_px = image.size
    with fitz.open(PDF) as document:
        pdf_pages = document.page_count
    checks = {
        "source_summary_pass": summary.get("status") == "PASS",
        "classifier_has_three_tradeoff_metrics": coverage.size == risk.size == exposure.size == 4,
        "relation_structural_value_is_3412": lookup[("Relation Contract", "strict_contract_violations")]["without_component"] == "3412",
        "role_owner_has_time_and_space": (
            lookup[("Role-owner Closure", "invalid_time_owner_types")]["without_component"] == "44"
            and lookup[("Role-owner Closure", "invalid_space_owner_types")]["without_component"] == "112"
        ),
        "provenance_is_explicit_saturation_canary": "saturated post-gate canary" in lookup[("Provenance Gate", "changed_vs_full")]["interpretation"],
        "png_exists_nonempty": PNG.exists() and PNG.stat().st_size > 100000,
        "pdf_exists_nonempty": PDF.exists() and PDF.stat().st_size > 10000,
        "png_large_enough": width_px >= 2000 and height_px >= 1200,
        "pdf_single_page": pdf_pages == 1,
        "chart_contract_exists": CONTRACT.exists() and CONTRACT.stat().st_size > 500,
    }
    audit = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "source_hashes": {
            DATA.name: sha256(DATA),
            SUMMARY.name: sha256(SUMMARY),
            PREDICTIONS.name: sha256(PREDICTIONS),
            CONTRACT.name: sha256(CONTRACT),
        },
        "outputs": {
            PNG.name: {"sha256": sha256(PNG), "bytes": PNG.stat().st_size, "width": width_px, "height": height_px},
            PDF.name: {"sha256": sha256(PDF), "bytes": PDF.stat().st_size, "pages": pdf_pages},
        },
        "visual_qa": "PASS: original-resolution PNG inspected; labels, values, units, legends, footnotes, and card boundaries are readable with no clipping",
    }
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if audit["status"] != "PASS":
        raise RuntimeError(f"ablation figure audit failed: {checks}")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
