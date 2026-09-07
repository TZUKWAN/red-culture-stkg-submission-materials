#!/usr/bin/env python3
"""Build publication-grade Chinese figures from frozen Paper A experiment CSVs.

This script does not recompute experiments.  It only reads audited baseline and
selective-inference artifacts, creates figure-specific CSVs, and renders PNG/PDF
outputs.  ``--manual-qa-passed`` may be supplied only after the rendered PNGs
have been visually inspected.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


SCRIPT = Path(__file__).resolve()
BASE_DIR = SCRIPT.parent
ROOT = SCRIPT.parents[4]
SELECTIVE_DIR = ROOT / "dual_paper_project/paper_A_method/revision/03_selective_inference"
CORE_FIG_DIR = BASE_DIR / "figures"
RISK_FIG_DIR = SELECTIVE_DIR / "figures"

BASELINE_METRICS = BASE_DIR / "BASELINE_METRICS.csv"
BASELINE_AUDIT = BASE_DIR / "baseline_experiment_audit.json"
RISK_POINTS = SELECTIVE_DIR / "RISK_COVERAGE_POINTS.csv"
RISK_SUMMARY = SELECTIVE_DIR / "RISK_COVERAGE_SUMMARY.csv"
RISK_AUDIT = SELECTIVE_DIR / "risk_coverage_audit.json"

CORE_DATA = CORE_FIG_DIR / "CORE_METRICS_FIGURE_DATA.csv"
CORE_CONTRACT = CORE_FIG_DIR / "CORE_METRICS_CHART_CONTRACT.json"
CORE_PNG = CORE_FIG_DIR / "core_metrics_by_evidence_zh.png"
CORE_PDF = CORE_FIG_DIR / "core_metrics_by_evidence_zh.pdf"
CORE_AUDIT = CORE_FIG_DIR / "core_metrics_figure_audit.json"

RISK_DATA = RISK_FIG_DIR / "RISK_COVERAGE_FIGURE_DATA.csv"
RISK_CONTRACT = RISK_FIG_DIR / "RISK_COVERAGE_ZH_CHART_CONTRACT.json"
RISK_PNG = RISK_FIG_DIR / "risk_coverage_constrained_zh.png"
RISK_PDF = RISK_FIG_DIR / "risk_coverage_constrained_zh.pdf"
RISK_FIG_AUDIT = RISK_FIG_DIR / "risk_coverage_figure_audit.json"

METHOD_ORDER = [
    "M1_rule_only",
    "M2_classifier_only",
    "M3_cached_llm_replay",
    "M4_rule_plus_cached_llm",
    "M6_full_v2_replay",
]
METHOD_LABELS = {
    "M1_rule_only": "M1 规则法",
    "M2_classifier_only": "M2 分类器",
    "M3_cached_llm_replay": "M3c 缓存 LLM",
    "M4_rule_plus_cached_llm": "M4 规则+缓存 LLM",
    "M6_full_v2_replay": "M6 全框架回放",
}
EVIDENCE_ORDER = ["actual_run", "cached_model_output", "deterministic_replay"]
EVIDENCE_LABELS = {
    "actual_run": "当前实际运行\nactual_run",
    "cached_model_output": "历史缓存输出\ncached_model_output",
    "deterministic_replay": "冻结确定性回放\ndeterministic_replay",
}
METRICS = [
    ("coverage", "覆盖率 Coverage", "n_covered", "n_test"),
    ("accuracy_on_covered", "已接纳准确率", "n_correct", "n_covered"),
    ("safe_coverage", "安全覆盖率", "n_safe_correct", "n_test"),
]
METRIC_STYLE = {
    "coverage": {"color": "#2F6B9A", "hatch": "//"},
    "accuracy_on_covered": {"color": "#C58A24", "hatch": ".."},
    "safe_coverage": {"color": "#6E7F3A", "hatch": "xx"},
}
TASK_ORDER = ["entity_type", "event_role", "relation_semantic", "space_role", "time_role"]
TASK_LABELS = {
    "entity_type": "实体类型",
    "event_role": "事件角色",
    "relation_semantic": "关系语义",
    "space_role": "空间角色",
    "time_role": "时间角色",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def output_record(path: Path, row_count: int | None = None) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "row_count": row_count,
    }


def configure_chinese_fonts() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "font.size": 10,
            "axes.titlesize": 11,
            "axes.labelsize": 10,
        }
    )


def build_core_data() -> list[dict[str, Any]]:
    metrics = read_csv(BASELINE_METRICS)
    rows = {
        row["method_id"]: row
        for row in metrics
        if row["task_type"] == "__CORE_ELIGIBLE_TASKS__"
        and row["method_id"] in METHOD_ORDER
    }
    if set(rows) != set(METHOD_ORDER):
        raise AssertionError("core metric method set mismatch")
    output = []
    for method_index, method_id in enumerate(METHOD_ORDER):
        source = rows[method_id]
        if source["evidence_class"] == "not_available":
            raise AssertionError("NOT_AVAILABLE methods must not enter plotted core data")
        for metric_index, (metric_code, metric_label, numerator_field, denominator_field) in enumerate(METRICS):
            value = float(source[metric_code])
            numerator = int(source[numerator_field])
            denominator = int(source[denominator_field])
            expected = numerator / denominator if denominator else 0.0
            if abs(value - expected) > 1e-6:
                raise AssertionError(f"core metric does not recompute: {method_id} {metric_code}")
            output.append(
                {
                    "method_id": method_id,
                    "method_label": METHOD_LABELS[method_id],
                    "method_order": method_index,
                    "method_name": source["method_name"],
                    "evidence_class": source["evidence_class"],
                    "evidence_label": EVIDENCE_LABELS[source["evidence_class"]].replace("\n", " / "),
                    "comparison_tier": source["comparison_tier"],
                    "overlap_status": source["overlap_status"],
                    "evaluation_eligibility": source["evaluation_eligibility"],
                    "n_test": int(source["n_test"]),
                    "metric_code": metric_code,
                    "metric_label": metric_label,
                    "metric_order": metric_index,
                    "numerator": numerator,
                    "denominator": denominator,
                    "value": value,
                }
            )
    return output


def render_core_figure(data: list[dict[str, Any]]) -> None:
    configure_chinese_fonts()
    by_evidence: dict[str, list[str]] = defaultdict(list)
    for method_id in METHOD_ORDER:
        evidence = next(row["evidence_class"] for row in data if row["method_id"] == method_id)
        by_evidence[evidence].append(method_id)

    fig, axes = plt.subplots(
        1,
        3,
        figsize=(14.2, 6.25),
        sharey=True,
        gridspec_kw={"width_ratios": [2.0, 2.0, 1.15]},
    )
    bar_width = 0.23
    offsets = np.asarray([-bar_width, 0.0, bar_width])
    legend_handles = []
    legend_labels = []
    for axis, evidence in zip(axes, EVIDENCE_ORDER):
        methods = by_evidence[evidence]
        x = np.arange(len(methods), dtype=float)
        for metric_index, (metric_code, metric_label, _num, _den) in enumerate(METRICS):
            values = [
                next(
                    float(row["value"])
                    for row in data
                    if row["method_id"] == method_id and row["metric_code"] == metric_code
                )
                for method_id in methods
            ]
            style = METRIC_STYLE[metric_code]
            bars = axis.bar(
                x + offsets[metric_index],
                values,
                width=bar_width,
                color=style["color"],
                edgecolor="#27313A",
                linewidth=0.7,
                hatch=style["hatch"],
                label=metric_label,
                zorder=3,
            )
            if not legend_handles:
                pass
            for bar, value in zip(bars, values):
                axis.text(
                    bar.get_x() + bar.get_width() / 2,
                    value + 0.025,
                    f"{value:.3f}",
                    ha="center",
                    va="bottom",
                    fontsize=8.3,
                    rotation=0,
                    color="#27313A",
                )
            if axis is axes[0]:
                legend_handles.append(bars[0])
                legend_labels.append(metric_label)
        axis.set_title(EVIDENCE_LABELS[evidence], loc="left", fontweight="bold", pad=12)
        axis.set_xticks(x, [METHOD_LABELS[method_id] for method_id in methods])
        axis.set_ylim(0, 1.11)
        axis.set_yticks(np.linspace(0, 1, 6))
        axis.grid(axis="y", color="#D8DDE3", linewidth=0.8, alpha=0.9, zorder=0)
        axis.spines[["top", "right"]].set_visible(False)
        axis.spines[["left", "bottom"]].set_color("#5F6B76")
    axes[0].set_ylabel("比例（0—1）")
    fig.suptitle("核心可评估任务的覆盖率、已接纳准确率与安全覆盖率（n=152）", fontsize=15.5, y=0.975)
    fig.text(
        0.5,
        0.902,
        "按证据等级分面；数值来自同一冻结测试分母。NOT_AVAILABLE 方法不绘制为 0。",
        ha="center",
        fontsize=10.5,
        color="#4B5563",
    )
    fig.legend(
        legend_handles,
        legend_labels,
        loc="upper center",
        ncol=3,
        frameon=False,
        bbox_to_anchor=(0.5, 0.842),
    )
    fig.text(
        0.012,
        0.018,
        "注：M1、M3c、M4 与集成参考标注共享规则或缓存模型通道；M2 为监督代理基准；M6 为共享系统信号的冻结回放。未绘制：M3-live、M5。",
        fontsize=8.7,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0.02, 0.055, 0.995, 0.775), w_pad=2.0)
    fig.savefig(CORE_PNG, dpi=300, facecolor="white")
    fig.savefig(
        CORE_PDF,
        facecolor="white",
        metadata={"Creator": "Paper A audited figure builder", "CreationDate": None, "ModDate": None},
    )
    plt.close(fig)


def build_risk_data() -> list[dict[str, Any]]:
    points = read_csv(RISK_POINTS)
    output = []
    method_labels = {
        "M2_classifier_only": "M2 分类器代理",
        "M6_full_v2_replay": "M6 全框架回放",
    }
    for row in points:
        if (
            row["curve_mode"] != "constrained_selective"
            or row["point_type"] != "exact_unique"
            or row["method_id"] not in method_labels
            or row["task_type"] not in TASK_ORDER
        ):
            continue
        risk_value = 0.0 if not row["selective_risk"] else float(row["selective_risk"])
        output.append(
            {
                "method_id": row["method_id"],
                "method_label": method_labels[row["method_id"]],
                "task_type": row["task_type"],
                "task_label": TASK_LABELS[row["task_type"]],
                "curve_mode": row["curve_mode"],
                "primary_curve": int(row["primary_curve"]),
                "point_index": int(row["point_index"]),
                "threshold": row["threshold"],
                "is_zero_anchor": int(row["threshold"] == "INF"),
                "accepted_count": int(row["accepted_count"]),
                "total_count": int(row["total_count"]),
                "coverage": float(row["coverage"]),
                "selective_risk": "" if not row["selective_risk"] else float(row["selective_risk"]),
                "plot_selective_risk": risk_value,
                "safe_coverage": float(row["safe_coverage"]),
                "review_escalation_rate": float(row["review_escalation_rate"]),
                "acceptance_rule": row["acceptance_rule"],
                "evaluation_eligibility": row["evaluation_eligibility"],
                "overlap_status": row["overlap_status"],
            }
        )
    return sorted(output, key=lambda row: (TASK_ORDER.index(row["task_type"]), row["method_id"], row["point_index"]))


def render_risk_figure(data: list[dict[str, Any]]) -> None:
    configure_chinese_fonts()
    colors = {"M2_classifier_only": "#2F6B9A", "M6_full_v2_replay": "#C58A24"}
    styles = {"M2_classifier_only": ("-", "o"), "M6_full_v2_replay": ("--", "s")}
    labels = {"M2_classifier_only": "M2 分类器代理", "M6_full_v2_replay": "M6 全框架回放"}
    fig, axes = plt.subplots(2, 3, figsize=(12.5, 8.2), sharex=True, sharey=True, squeeze=False)
    for panel_index, (axis, task) in enumerate(zip(axes.flat, TASK_ORDER)):
        task_rows = [row for row in data if row["task_type"] == task]
        n = next(int(row["total_count"]) for row in task_rows)
        for method_id in ("M2_classifier_only", "M6_full_v2_replay"):
            rows = [row for row in task_rows if row["method_id"] == method_id]
            line, marker = styles[method_id]
            axis.plot(
                [float(row["coverage"]) for row in rows],
                [float(row["plot_selective_risk"]) for row in rows],
                linestyle=line,
                marker=marker,
                markersize=3.7,
                linewidth=1.9,
                color=colors[method_id],
                label=labels[method_id],
            )
        axis.set_title(f"{TASK_LABELS[task]}（n={n}）", loc="left", fontweight="bold")
        axis.set_xlim(0, 1.02)
        axis.set_ylim(0, 1.02)
        axis.set_xlabel("覆盖率 Coverage")
        axis.set_ylabel("选择性风险 Selective Risk" if panel_index % 3 == 0 else "")
        axis.grid(True, color="#D8DDE3", linewidth=0.75, alpha=0.9)
        axis.spines[["top", "right"]].set_visible(False)
    axes.flat[-1].axis("off")
    handles, legend_labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.915))
    fig.suptitle("约束选择推断的风险—覆盖曲线（冻结集成参考标注测试集）", fontsize=16, y=0.985)
    fig.text(
        0.5,
        0.945,
        "准入条件：s(x) ≥ τ 且 H(x)=1；拒绝样本进入复核，本轮未调用在线 LLM。",
        ha="center",
        fontsize=10.5,
        color="#4B5563",
    )
    fig.text(
        0.012,
        0.018,
        "注：time_owner、space_owner 经专门审计判定为共享代理诊断，未进入主图；M2 为监督代理，M6 为共享系统信号回放，曲线衡量与集成参考标注的一致性。",
        fontsize=8.8,
        color="#4B5563",
    )
    fig.tight_layout(rect=(0.025, 0.06, 0.99, 0.88), h_pad=2.0, w_pad=1.5)
    fig.savefig(RISK_PNG, dpi=300, facecolor="white")
    fig.savefig(
        RISK_PDF,
        facecolor="white",
        metadata={"Creator": "Paper A audited figure builder", "CreationDate": None, "ModDate": None},
    )
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual-qa-passed", action="store_true")
    args = parser.parse_args()
    CORE_FIG_DIR.mkdir(parents=True, exist_ok=True)
    RISK_FIG_DIR.mkdir(parents=True, exist_ok=True)

    source_paths = [BASELINE_METRICS, BASELINE_AUDIT, RISK_POINTS, RISK_SUMMARY, RISK_AUDIT]
    hashes_before = {str(path): sha256_file(path) for path in source_paths}
    baseline_audit = json.loads(BASELINE_AUDIT.read_text(encoding="utf-8"))
    risk_audit = json.loads(RISK_AUDIT.read_text(encoding="utf-8"))
    if baseline_audit.get("result") != "PASS" or risk_audit.get("result") != "PASS":
        raise AssertionError("source experiment audits must pass before figure rendering")

    core_data = build_core_data()
    risk_data = build_risk_data()
    write_csv(CORE_DATA, core_data, list(core_data[0].keys()))
    write_csv(RISK_DATA, risk_data, list(risk_data[0].keys()))

    core_contract = {
        "analytical_question": "How do core-eligible Coverage, covered accuracy, and Safe Coverage compare while preserving evidence class?",
        "supported_takeaway": "Values are comparable only within the frozen 152-row core denominator; evidence facets prevent actual, cached, and replay outputs from being visually conflated.",
        "family": "Comparison & Ranking",
        "variant": "three evidence facets with grouped bars and direct values",
        "surface": "publication static PNG/PDF",
        "language": "Chinese with English metric/method abbreviations retained",
        "data": str(CORE_DATA),
        "denominator": 152,
        "facets": EVIDENCE_LABELS,
        "not_available_policy": "M3_live_llm_only and M5_no_global_closure are omitted, never plotted as zero",
        "palette_policy": "three approved roots plus neutral outlines",
        "non_color_encoding": "distinct hatch pattern for every metric",
        "outputs": [str(CORE_PNG), str(CORE_PDF)],
    }
    risk_contract = {
        "analytical_question": "Under the formal constrained gate, how does selective risk change as coverage increases?",
        "supported_takeaway": "Only constrained_selective exact points are plotted; score-only diagnostics and owner proxies are excluded.",
        "family": "Uncertainty & Benchmark",
        "variant": "small-multiple risk-coverage lines",
        "surface": "publication static PNG/PDF",
        "language": "Chinese with M2/M6 and English axis terms retained",
        "curve_mode": "constrained_selective",
        "acceptance_rule": "score >= threshold AND hard_constraint_pass = 1",
        "data": str(RISK_DATA),
        "tasks": TASK_ORDER,
        "owner_policy": "time_owner and space_owner excluded after dedicated applicability audit",
        "palette_policy": "hard two-root cap plus neutrals",
        "non_color_encoding": "solid circle versus dashed square",
        "outputs": [str(RISK_PNG), str(RISK_PDF)],
    }
    write_json(CORE_CONTRACT, core_contract)
    write_json(RISK_CONTRACT, risk_contract)
    render_core_figure(core_data)
    render_risk_figure(risk_data)

    hashes_after = {str(path): sha256_file(path) for path in source_paths}
    core_methods = {row["method_id"] for row in core_data}
    core_canaries = {
        "baseline_audit_pass": baseline_audit.get("result") == "PASS",
        "source_hashes_unchanged": hashes_before == hashes_after,
        "core_denominator_152": {int(row["n_test"]) for row in core_data} == {152},
        "three_metrics_per_method": Counter(row["method_id"] for row in core_data)
        == Counter({method_id: 3 for method_id in METHOD_ORDER}),
        "not_available_not_plotted_as_zero": core_methods == set(METHOD_ORDER),
        "all_values_recompute": all(
            abs(float(row["value"]) - int(row["numerator"]) / int(row["denominator"])) <= 1e-6
            for row in core_data
        ),
        "values_in_unit_interval": all(0 <= float(row["value"]) <= 1 for row in core_data),
        "png_exists": CORE_PNG.exists() and CORE_PNG.stat().st_size > 0,
        "pdf_exists": CORE_PDF.exists() and CORE_PDF.stat().st_size > 0,
        "manual_visual_qa_passed": bool(args.manual_qa_passed),
    }
    risk_canaries = {
        "risk_audit_pass": risk_audit.get("result") == "PASS",
        "source_hashes_unchanged": hashes_before == hashes_after,
        "only_constrained_selective": {row["curve_mode"] for row in risk_data}
        == {"constrained_selective"},
        "only_primary_methods": {row["method_id"] for row in risk_data}
        == {"M2_classifier_only", "M6_full_v2_replay"},
        "owner_tasks_excluded": not any(
            row["task_type"] in {"time_owner", "space_owner"} for row in risk_data
        ),
        "all_five_core_tasks_present": {row["task_type"] for row in risk_data} == set(TASK_ORDER),
        "all_points_primary": all(int(row["primary_curve"]) == 1 for row in risk_data),
        "all_acceptance_rules_constrained": all(
            row["acceptance_rule"] == "score>=threshold AND hard_constraint_pass=1"
            for row in risk_data
        ),
        "coverage_and_risk_in_unit_interval": all(
            0 <= float(row["coverage"]) <= 1
            and 0 <= float(row["plot_selective_risk"]) <= 1
            for row in risk_data
        ),
        "png_exists": RISK_PNG.exists() and RISK_PNG.stat().st_size > 0,
        "pdf_exists": RISK_PDF.exists() and RISK_PDF.stat().st_size > 0,
        "manual_visual_qa_passed": bool(args.manual_qa_passed),
    }
    core_audit = {
        "generated_at": utc_now(),
        "result": "PASS" if all(core_canaries.values()) else "PENDING_VISUAL_QA",
        "canaries": core_canaries,
        "inputs": {
            "baseline_metrics": output_record(BASELINE_METRICS, len(read_csv(BASELINE_METRICS))),
            "baseline_audit": output_record(BASELINE_AUDIT),
        },
        "outputs": {
            "figure_data": output_record(CORE_DATA, len(core_data)),
            "chart_contract": output_record(CORE_CONTRACT),
            "png": output_record(CORE_PNG),
            "pdf": output_record(CORE_PDF),
        },
        "visual_qa": {
            "status": "PASS" if args.manual_qa_passed else "PENDING",
            "inspection_scope": "title, subtitle, facets, legend, direct values, Chinese glyphs, clipping, overlap, footnote, evidence separation",
        },
    }
    risk_figure_audit = {
        "generated_at": utc_now(),
        "result": "PASS" if all(risk_canaries.values()) else "PENDING_VISUAL_QA",
        "canaries": risk_canaries,
        "inputs": {
            "risk_points": output_record(RISK_POINTS, len(read_csv(RISK_POINTS))),
            "risk_summary": output_record(RISK_SUMMARY, len(read_csv(RISK_SUMMARY))),
            "risk_audit": output_record(RISK_AUDIT),
        },
        "outputs": {
            "figure_data": output_record(RISK_DATA, len(risk_data)),
            "chart_contract": output_record(RISK_CONTRACT),
            "png": output_record(RISK_PNG),
            "pdf": output_record(RISK_PDF),
        },
        "visual_qa": {
            "status": "PASS" if args.manual_qa_passed else "PENDING",
            "inspection_scope": "Chinese title/axes/legend, hard-gate subtitle, five task panels, owner exclusion note, line/marker distinction, clipping, overlap",
        },
    }
    write_json(CORE_AUDIT, core_audit)
    write_json(RISK_FIG_AUDIT, risk_figure_audit)
    print(
        json.dumps(
            {
                "core_result": core_audit["result"],
                "risk_result": risk_figure_audit["result"],
                "core_data_rows": len(core_data),
                "risk_data_rows": len(risk_data),
                "manual_qa_passed": bool(args.manual_qa_passed),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
