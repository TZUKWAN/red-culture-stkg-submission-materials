#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_imcr_figures.py — GOAL.md §三十 新论文图表（图A–图D）渲染管线。

四个子命令，各自独立渲染一张图并输出 PNG + PDF + 图表契约（CHART_CONTRACT）
+ 渲染审计（AUDIT）：

* ``risk_coverage``                图A Independent risk-coverage curves
    输入 13 号目录 ``<prefix>RISK_COVERAGE_POINTS.csv``（与
    era_replay\\era_RISK_COVERAGE_POINTS.csv 完全同构的 31 列格式），
    主曲线 ``curve_mode=constrained_selective``，每 task_type 一个面板的
    small-multiple 布局；n<8 与 evaluation 不合格任务面板按 era 图同规则排除。
* ``aurc_augrc_ci``                图B AURC/AUGRC comparison with 95% CI
    输入 14 号目录 ``PAIRED_BOOTSTRAP_DELTAS.csv``（列定义见
    ``run_statistical_tests.DELTA_FIELDS``：长表 ``metric ∈ {aurc, augrc}``，
    ``estimate = Full − baseline``，负值 = Full 更优）；每 task_type 一个面板，
    各基线的 ΔAURC / ΔAUGRC 点估计 + 95% CI 误差条，y=0 参考线。
    若 13 号目录存在 ``<prefix>RISK_COVERAGE_SUMMARY.csv`` 或
    ``<prefix>SELECTIVE_GOAL13_METRICS.csv``，则用其 AURC/AUGRC 列做交叉核验
    （缺失时跳过并在 audit 记录，不报错）。
* ``scope_validation``             图C 208 scope adjustments before vs after
    输入 08 号 ``IMCR_REFERENCE_ALL.csv``（scope_adjustment 行，
    ``reference_label`` 已解码为 BEFORE_BETTER/AFTER_BETTER/...）+
    （可选 ``--raw-root``）各 judge 原始票，经
    ``build_imcr_consensus.decode_ab_label`` 按
    ``payloads\\SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING.csv`` 解码。
    左 = 共识标签分布（含 unresolved，取自 manifest manifest_tasks），
    右 = 各 judge 与共识的 before/after 偏好堆叠条。
* ``relation_contract_validation`` 图D Relation contract changed-set validation
    输入 ``RELATION_CONTRACT_SAMPLE.csv``（sample_role=changed/control）+
    ``IMCR_REFERENCE_ALL.csv``（relation_contract 行）+（若存在）
    09 号 ``IMCR_BASELINE_RUNS.csv`` 的 B12_full_framework/relation_contract 行
    （正确性按 run_selective_inference.apply_imcr_reference 语义重算）。

通用约定：

* 图内文字使用中文；字体走 Microsoft YaHei / SimHei / Noto Sans CJK SC 回退链，
  ``axes.unicode_minus=False``；全部 rc 设置经 ``mpl.rc_context`` 生效，
  不写全局 rcParams。
* palette：两个色根（蓝 #2F6B9A / 橙 #C58A24）+ 中性灰；颜色之外一律以
  marker / linestyle / 面板位置做冗余编码。
* 所有数字字段从 CSV 读取，脚本内不硬编码任何实验数值。
* 输入缺失时报错明确（FileNotFoundError/ValueError，指明路径）；
  每图支持 ``--synthetic`` 生成固定种子（MASTER_SEED 派生）的合成演示数据，
  图面打 SYNTHETIC 水印、contract/audit 标 ``synthetic: true``。

用法示例::

    python build_imcr_figures.py risk_coverage                # 图A（默认真实路径）
    python build_imcr_figures.py aurc_augrc_ci --stats-dir experiments/14_statistical_tests
    python build_imcr_figures.py scope_validation --raw-root experiments/08_independent_reference/raw_runs
    python build_imcr_figures.py relation_contract_validation
    python build_imcr_figures.py risk_coverage --synthetic    # 冒烟
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib as mpl  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

SCRIPT = Path(__file__).resolve()
CODE_DIR = SCRIPT.parents[1]
for _p in (str(CODE_DIR), str(CODE_DIR / "independent_eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 复用既有、已被独立测试的实现，不重写任何数学或共识逻辑。
from independent_eval import metrics as selective_metrics  # noqa: E402
from independent_eval._common import MASTER_SEED, derive_seed  # noqa: E402
from experiment_pipelines import build_imcr_consensus as consensus_builder  # noqa: E402
from experiment_pipelines import imcr_task_defs as defs  # noqa: E402
from experiment_pipelines import run_selective_inference as rsi  # noqa: E402

V3_ROOT = SCRIPT.parents[2]
EXPERIMENTS_DIR = V3_ROOT / "experiments"
DEFAULT_FIGURES_DIR = V3_ROOT / "figures"

EXP08 = EXPERIMENTS_DIR / "08_independent_reference"
EXP09 = EXPERIMENTS_DIR / "09_independent_baselines"
EXP13 = EXPERIMENTS_DIR / "13_selective_inference_independent"
EXP14 = EXPERIMENTS_DIR / "14_statistical_tests"

DEFAULT_POINTS_DIR = EXP13 / "imcr_strong"
DEFAULT_STATS_DIR = EXP14
DEFAULT_REFERENCE_CSV = EXP08 / "IMCR_REFERENCE_ALL.csv"
DEFAULT_SAMPLE_CSV = EXP08 / "RELATION_CONTRACT_SAMPLE.csv"
DEFAULT_PAYLOADS_DIR = EXP08 / "payloads"
DEFAULT_MANIFEST_JSON = EXP08 / "IMCR_CONSENSUS_MANIFEST.json"
DEFAULT_RUNS_CSV = EXP09 / "IMCR_BASELINE_RUNS.csv"

POINTS_FILE_GLOB = "*RISK_COVERAGE_POINTS.csv"
SUMMARY_FILE_GLOB = "*RISK_COVERAGE_SUMMARY.csv"
GOAL13_FILE_GLOB = "*SELECTIVE_GOAL13_METRICS.csv"
DELTAS_FILE_NAME = "PAIRED_BOOTSTRAP_DELTAS.csv"
AB_MAPPING_FILE_NAME = "SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING.csv"

#: era 图同规则：任务样本量低于该值不进图（run_selective_inference.MIN_AREA_N）。
MIN_TASK_N = rsi.MIN_AREA_N  # 8

FULL_METHOD_ID = "B12_full_framework"
#: ΔAURC/ΔAUGRC 长表中的 metric 取值（run_statistical_tests.METRICS_IN_DELTAS）。
DELTA_METRICS = ("aurc", "augrc")

# ---------------------------------------------------------------------------
# palette：两个色根 + 中性色（GOAL palette_policy: hard two-root cap plus neutrals）
# ---------------------------------------------------------------------------

BLUE = "#2F6B9A"  # 色根 1（基线族）
ORANGE = "#C58A24"  # 色根 2（完整框架族）
GRID = "#D8DDE3"
DARK = "#1F2937"
MUTED = "#4B5563"
NEUTRALS = ("#4B5563", "#8A8F98", "#6B7280", "#A8ADB5", "#52606D")
UNRESOLVED_COLOR = "#C3C7CD"

#: 任务类型中文标签（IMCR 五类 + era_replay 开发验证会出现的任务名）。
TASK_LABELS_ZH: dict[str, str] = {
    "entity_type": "实体类型",
    "relation_contract": "关系契约",
    "scope_adjustment": "时空范围校正",
    "identity_pair": "实体同一性",
    "provenance_support": "来源支持",
    # era_replay（开发验证用）任务名
    "relation_semantic": "关系语义",
    "event_role": "事件角色",
    "time_role": "时间角色",
    "space_role": "空间角色",
    "time_owner": "时间归属（owner 代理）",
    "space_owner": "空间归属（owner 代理）",
}

#: 面板排序（先 IMCR 任务序，后 era 任务名，未知任务按字母序缀后）。
TASK_ORDER: tuple[str, ...] = (
    "entity_type",
    "relation_contract",
    "scope_adjustment",
    "identity_pair",
    "provenance_support",
    "relation_semantic",
    "event_role",
    "time_role",
    "space_role",
)

#: 方法中文标签（B 系列为 09/13/14 号正式命名；M 系列仅供 era_replay 开发验证）。
METHOD_LABELS_ZH: dict[str, str] = {
    "B1_rule_only": "仅规则 (B1)",
    "B2_classifier_only": "冻结分类器 (B2)",
    "B2_frozen_classifier": "冻结分类器 (B2)",
    "B3_blind_llm": "盲 LLM (B3)",
    "B4_rule_plus_classifier": "规则+分类器 (B4)",
    "B5_rule_plus_blind_llm": "规则+盲 LLM (B5)",
    "B6_classifier_threshold": "分类器阈值 (B6=B2)",
    "B7_margin_threshold": "分类器间隔阈值 (B7)",
    "B7_classifier_margin": "分类器间隔阈值 (B7)",
    "B8_entropy_threshold": "熵阈值 (B8)",
    "B9_agreement_gate": "规则-模型一致门 (B9)",
    "B9_rule_model_agreement": "规则-模型一致门 (B9)",
    "B10_selective_no_gate": "仅选择无结构门 (B10)",
    "B10_selective_no_structural_gate": "仅选择无结构门 (B10)",
    "B11_gate_no_abstention": "仅结构门无弃权 (B11)",
    "B11_structural_gate_no_abstention": "仅结构门无弃权 (B11)",
    "B12_full_framework": "完整框架 (B12)",
    # era_replay（开发验证用）方法名
    "M1_rule_only": "仅规则 (M1)",
    "M2_classifier_only": "分类器代理 (M2)",
    "M4_rule_plus_cached_llm": "规则+缓存 LLM (M4)",
    "M6_full_v2_replay": "V2 全量重放 (M6)",
}

#: 方法绘图顺序（出现在数据中的方法按此序排列，未知方法按字母序缀后）。
METHOD_ORDER: tuple[str, ...] = (
    "B1_rule_only",
    "B2_classifier_only",
    "B2_frozen_classifier",
    "B3_blind_llm",
    "B4_rule_plus_classifier",
    "B5_rule_plus_blind_llm",
    "B7_margin_threshold",
    "B7_classifier_margin",
    "B8_entropy_threshold",
    "B9_agreement_gate",
    "B9_rule_model_agreement",
    "B10_selective_no_gate",
    "B10_selective_no_structural_gate",
    "B11_gate_no_abstention",
    "B11_structural_gate_no_abstention",
    "B12_full_framework",
    "M1_rule_only",
    "M2_classifier_only",
    "M4_rule_plus_cached_llm",
    "M6_full_v2_replay",
)

#: 非颜色冗余编码：method_id -> (linestyle, marker)。颜色仅用两个色根 + 中性灰。
METHOD_STYLES: dict[str, tuple[str, str, str]] = {
    # color, linestyle, marker
    "B12_full_framework": (ORANGE, "-", "s"),
    "M6_full_v2_replay": (ORANGE, "--", "s"),
    "B2_classifier_only": (BLUE, "-", "o"),
    "B2_frozen_classifier": (BLUE, "-", "o"),
    "M2_classifier_only": (BLUE, "-", "o"),
    "B1_rule_only": (BLUE, "--", "^"),
    "M1_rule_only": (BLUE, "--", "^"),
    "B3_blind_llm": (BLUE, "-.", "D"),
    "B4_rule_plus_classifier": (BLUE, ":", "v"),
    "M4_rule_plus_cached_llm": (BLUE, ":", "v"),
    "B5_rule_plus_blind_llm": (BLUE, (0, (3, 1, 1, 1)), "P"),
}
_MARKER_CYCLE = ("o", "^", "D", "v", "P", "X", "*", "h", "d", "<")
_DASH_CYCLE = ("--", "-.", ":", (0, (3, 1, 1, 1)), (0, (5, 2, 1, 2)), "--", "-.")


def method_style(method_id: str, fallback_index: int = 0) -> tuple[str, str, str]:
    """(color, linestyle, marker)；显式表优先，其余方法按中性灰循环。"""
    if method_id in METHOD_STYLES:
        return METHOD_STYLES[method_id]
    return (
        NEUTRALS[fallback_index % len(NEUTRALS)],
        _DASH_CYCLE[fallback_index % len(_DASH_CYCLE)],
        _MARKER_CYCLE[fallback_index % len(_MARKER_CYCLE)],
    )


def method_label(method_id: str) -> str:
    return METHOD_LABELS_ZH.get(method_id, method_id)


def task_label(task_type: str) -> str:
    return TASK_LABELS_ZH.get(task_type, task_type)


def task_sort_key(task_type: str) -> tuple[int, str]:
    known = TASK_ORDER.index(task_type) if task_type in TASK_ORDER else len(TASK_ORDER)
    return (known, task_type)


def method_sort_key(method_id: str) -> tuple[int, str]:
    known = METHOD_ORDER.index(method_id) if method_id in METHOD_ORDER else len(METHOD_ORDER)
    return (known, method_id)


# ---------------------------------------------------------------------------
# scope_adjustment / relation_contract 标签的中文映射与绘图顺序
# ---------------------------------------------------------------------------

#: 解码后共识标签（BEFORE_/AFTER_ 语义）的展示顺序与配色。
SCOPE_LABEL_ORDER: tuple[str, ...] = (
    "BEFORE_BETTER",
    "AFTER_BETTER",
    "EQUIVALENT",
    "BOTH_WRONG",
    "INSUFFICIENT_EVIDENCE",
)
SCOPE_LABEL_ZH = {
    "BEFORE_BETTER": ("改前更优", BLUE),
    "AFTER_BETTER": ("改后更优", ORANGE),
    "EQUIVALENT": ("两者相当", NEUTRALS[0]),
    "BOTH_WRONG": ("两者皆误", NEUTRALS[1]),
    "INSUFFICIENT_EVIDENCE": ("证据不足", NEUTRALS[2]),
    "UNRESOLVED": ("未达成共识", UNRESOLVED_COLOR),
    "INVALID": ("无效/缺失票", "#D8DDE3"),
}

RELATION_LABEL_ORDER: tuple[str, ...] = (
    "valid",
    "invalid",
    "context_only",
    "insufficient_evidence",
)
RELATION_LABEL_ZH = {
    "valid": ("语义成立", BLUE),
    "invalid": ("语义不成立", ORANGE),
    "context_only": ("仅作上下文", NEUTRALS[0]),
    "insufficient_evidence": ("证据不足", NEUTRALS[1]),
    "UNLABELED": ("未获参考标签", UNRESOLVED_COLOR),
}

ROLE_ZH = {"changed": "changed（改后集合）", "control": "control（对照集合）"}


# ---------------------------------------------------------------------------
# 小型 IO / 契约工具（与 experiment_pipelines 既有脚本同风格）
# ---------------------------------------------------------------------------


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """utf-8-sig 容错读取（与 _common.write_csv 的 BOM 输出对齐）。"""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def require_file(path: Path, hint: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(
            f"输入文件不存在: {path}（{hint}）。该输入由对应管线生成；"
            "若仅想冒烟渲染管线，请加 --synthetic。"
        )
    return path


def input_record(path: Path, row_count: int | None = None) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "row_count": row_count if row_count is not None else None,
    }


def require_columns(rows: Sequence[dict[str, str]], columns: Iterable[str], path: Path) -> None:
    if not rows:
        raise ValueError(f"输入文件为空: {path}")
    missing = [c for c in columns if c not in rows[0]]
    if missing:
        raise ValueError(f"输入文件 {path.name} 缺少必需列 {missing}（路径: {path}）")


def _to_float(value: str, context: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context}: 期望数值，得到 {value!r}") from exc
    if not math.isfinite(out):
        raise ValueError(f"{context}: 期望有限数值，得到 {value!r}")
    return out


def _to_int(value: str, context: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context}: 期望整数，得到 {value!r}") from exc


def synthetic_rng(label: str) -> np.random.Generator:
    """固定种子（MASTER_SEED 派生）的合成数据随机源，保证可复现。"""
    return np.random.default_rng(derive_seed(label, MASTER_SEED))


# ---------------------------------------------------------------------------
# 字体：SimHei / Microsoft YaHei 回退链（不写全局 rcParams，经 rc_context 生效）
# ---------------------------------------------------------------------------

FONT_CHAIN_CJK = (
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "PingFang SC",
    "Arial Unicode MS",
)


def resolve_cjk_font() -> dict[str, Any]:
    """解析可用中文字体；返回记录进 audit 的解析结果。"""
    available = {font.name for font in font_manager.fontManager.ttflist}
    resolved = next((name for name in FONT_CHAIN_CJK if name in available), "DejaVu Sans")
    return {
        "requested_chain": [*FONT_CHAIN_CJK, "DejaVu Sans"],
        "resolved": resolved,
        "cjk_capable": resolved in FONT_CHAIN_CJK,
    }


def figure_rc(font: dict[str, Any]) -> dict[str, Any]:
    chain = [font["resolved"]]
    chain += [name for name in [*FONT_CHAIN_CJK, "DejaVu Sans"] if name != font["resolved"]]
    return {
        "font.family": "sans-serif",
        "font.sans-serif": chain,
        "axes.unicode_minus": False,
        "font.size": 10,
        "axes.titlesize": 10.5,
        "axes.labelsize": 10,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
    }


def stamp_synthetic(fig: plt.Figure) -> None:
    """合成演示数据水印：大字 SYNTHETIC + 角标说明。"""
    fig.text(
        0.5,
        0.52,
        "SYNTHETIC",
        ha="center",
        va="center",
        rotation=22,
        fontsize=56,
        color="#9CA3AF",
        alpha=0.45,
        zorder=100,
    )
    fig.text(
        0.995,
        0.008,
        "合成演示数据（SYNTHETIC DEMO，固定种子）——不可用于论文",
        ha="right",
        va="bottom",
        fontsize=8.5,
        color=MUTED,
        zorder=100,
    )


# ---------------------------------------------------------------------------
# 审计/契约骨架
# ---------------------------------------------------------------------------


def base_contract(
    *,
    figure_id: str,
    analytical_question: str,
    supported_takeaway: str,
    family: str,
    variant: str,
    x_axis: str,
    y_axis: str,
    palette: dict[str, str],
    non_color: dict[str, str],
    input_records: list[dict[str, Any]],
    outputs: list[str],
    synthetic: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "figure_id": figure_id,
        "analytical_question": analytical_question,
        "supported_takeaway": supported_takeaway,
        "family": family,
        "variant": variant,
        "renderer": "static Matplotlib PNG/PDF",
        "palette_policy": "hard two-root cap plus neutrals",
        "palette": palette,
        "non_color_distinction": non_color,
        "x_axis": x_axis,
        "y_axis": y_axis,
        "input_files": input_records,
        "output": outputs,
        "qa_surface": "exported PNG at 240 dpi and PDF",
        "generated_at": utc_now(),
        "synthetic": synthetic,
        "font": resolve_cjk_font(),
    }
    if extra:
        contract.update(extra)
    return contract


def base_audit(
    *,
    figure: str,
    synthetic: bool,
    inputs: dict[str, Any],
    checks: list[dict[str, Any]],
    panels: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    render: dict[str, Any],
    notes: list[str] | None = None,
) -> dict[str, Any]:
    errors = [c for c in checks if not c.get("passed", False)]
    return {
        "figure": figure,
        "generated_at": utc_now(),
        "result": "PASS" if not errors else "FAIL",
        "synthetic": synthetic,
        "synthetic_watermark": synthetic,
        "font": resolve_cjk_font(),
        "inputs": inputs,
        "checks": checks,
        "panels": panels,
        "excluded": excluded,
        "render": render,
        "notes": notes or [],
        "errors": [
            {"name": c["name"], "detail": c.get("detail", "")} for c in errors
        ],
    }


def check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def output_paths(out_dir: Path, prefix: str, slug: str) -> dict[str, Path]:
    return {
        "png": out_dir / f"{prefix}{slug}.png",
        "pdf": out_dir / f"{prefix}{slug}.pdf",
        "contract": out_dir / f"{prefix}{slug}_CHART_CONTRACT.json",
        "audit": out_dir / f"{prefix}{slug}_AUDIT.json",
    }


def save_figure(fig: plt.Figure, png: Path, pdf: Path) -> None:
    png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png, dpi=240, facecolor="white")
    fig.savefig(pdf, facecolor="white")
    plt.close(fig)


def ordered_methods(method_ids: Iterable[str]) -> list[str]:
    return sorted(set(method_ids), key=method_sort_key)


# ===========================================================================
# 图A risk_coverage
# ===========================================================================

#: era_RISK_COVERAGE_POINTS.csv 的 31 列（synthetic 生成按此同构输出）。
POINTS_FIELDS_31 = [
    "method_id",
    "method_name",
    "task_type",
    "evidence_class",
    "comparison_tier",
    "overlap_status",
    "evaluation_eligibility",
    "curve_mode",
    "primary_curve",
    "acceptance_rule",
    "point_type",
    "point_index",
    "threshold",
    "accepted_count",
    "total_count",
    "coverage",
    "error_count",
    "selective_risk",
    "generalized_risk",
    "safe_count",
    "safe_coverage",
    "abstained_count",
    "abstention_rate",
    "review_escalation_count",
    "review_escalation_rate",
    "llm_or_review_escalation_rate",
    "actual_llm_calls",
    "actual_llm_call_rate",
    "score_direction",
    "tie_policy",
    "denominator_policy",
]

POINTS_REQUIRED_COLUMNS = (
    "method_id",
    "task_type",
    "curve_mode",
    "point_type",
    "coverage",
    "selective_risk",
    "total_count",
)


def resolve_points_file(points_dir: Path | None, points_file: Path | None) -> Path:
    if points_file is not None:
        return require_file(points_file, "13 号目录 <prefix>RISK_COVERAGE_POINTS.csv")
    directory = points_dir or DEFAULT_POINTS_DIR
    if not directory.is_dir():
        raise FileNotFoundError(
            f"--points-dir 不存在: {directory}（13 号 selective-inference 输出目录，"
            f"应包含 {POINTS_FILE_GLOB}）；请先运行 run_selective_inference.py 或加 --synthetic。"
        )
    matches = sorted(directory.glob(POINTS_FILE_GLOB))
    if not matches:
        raise FileNotFoundError(
            f"在 --points-dir '{directory}' 下未找到 {POINTS_FILE_GLOB}；"
            "该目录应包含 run_selective_inference.py 的输出。"
        )
    if len(matches) > 1:
        raise ValueError(
            f"--points-dir '{directory}' 下有多个 points 文件 {matches}；"
            "请用 --points-file 显式指定其一。"
        )
    return matches[0]


def load_risk_coverage_points(
    points_dir: Path | None, points_file: Path | None
) -> tuple[list[dict[str, str]], Path, dict[str, Any]]:
    path = resolve_points_file(points_dir, points_file)
    rows = read_csv_rows(path)
    require_columns(rows, POINTS_REQUIRED_COLUMNS, path)
    return rows, path, input_record(path, len(rows))


def prepare_risk_coverage_panels(
    rows: list[dict[str, str]], min_task_n: int = MIN_TASK_N, methods: list[str] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """筛选主曲线并按 task_type 组装面板数据。

    返回 (panels, excluded, checks)。排除规则与 era 图一致：
    (1) ``evaluation_eligibility`` 以 ``evaluation_ineligible`` 开头的任务
        （era 语义：owner 代理参考不进入主比较）；
    (2) 任务样本量 ``n < min_task_n``（默认 8，``MIN_AREA_N``）。
    仅使用主曲线 ``curve_mode=constrained_selective`` 的 ``exact_unique`` 点。
    """
    primary = [
        row
        for row in rows
        if row.get("curve_mode") == "constrained_selective"
        and row.get("point_type") == "exact_unique"
        and str(row.get("selective_risk") or "").strip() != ""
    ]
    if methods:
        allow = set(methods)
        primary = [row for row in primary if row.get("method_id") in allow]
    by_task: dict[str, list[dict[str, str]]] = {}
    for row in primary:
        by_task.setdefault(row["task_type"], []).append(row)

    panels: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    monotonic_ok = True
    coverage_bounds_ok = True
    for task_type in sorted(by_task, key=task_sort_key):
        task_rows = by_task[task_type]
        n_total = max(_to_int(row["total_count"], f"points[{task_type}].total_count") for row in task_rows)
        eligibility = sorted({str(row.get("evaluation_eligibility") or "") for row in task_rows})
        ineligible = [value for value in eligibility if value.startswith("evaluation_ineligible")]
        if ineligible:
            excluded.append(
                {
                    "task_type": task_type,
                    "n": n_total,
                    "reason": (
                        "evaluation_eligibility=" + ";".join(eligible_ineligible for eligible_ineligible in ineligible)
                        + "（era 同规则：owner 代理参考不进入主比较）"
                    ),
                }
            )
            continue
        if n_total < min_task_n:
            excluded.append(
                {
                    "task_type": task_type,
                    "n": n_total,
                    "reason": f"n={n_total} < minimum_task_n_for_figure={min_task_n}",
                }
            )
            continue
        method_curves: dict[str, list[tuple[float, float]]] = {}
        for row in task_rows:
            method_id = row["method_id"]
            coverage = _to_float(row["coverage"], f"points[{task_type}/{method_id}].coverage")
            risk = _to_float(row["selective_risk"], f"points[{task_type}/{method_id}].selective_risk")
            method_curves.setdefault(method_id, []).append((coverage, risk))
            coverage_bounds_ok &= -1e-9 <= coverage <= 1 + 1e-9 and -1e-9 <= risk <= 1 + 1e-9
        curves: list[dict[str, Any]] = []
        for method_id in ordered_methods(method_curves):
            pts = sorted(method_curves[method_id])
            # era canary 同规则：随阈值放松（行序）coverage 单调不减
            raw_coverages = [
                _to_float(row["coverage"], f"points[{task_type}/{method_id}].coverage")
                for row in task_rows
                if row["method_id"] == method_id
            ]
            monotonic_ok &= all(b + 1e-9 >= a for a, b in zip(raw_coverages, raw_coverages[1:]))
            curves.append(
                {
                    "method_id": method_id,
                    "label": method_label(method_id),
                    "n_points": len(pts),
                    "coverage": [p[0] for p in pts],
                    "selective_risk": [p[1] for p in pts],
                }
            )
        if curves:
            panels.append({"task_type": task_type, "label": task_label(task_type), "n": n_total, "curves": curves})

    checks.append(check("coverage_and_risk_within_unit_square", coverage_bounds_ok, "coverage/selective_risk ∈ [0,1]"))
    checks.append(
        check("coverage_monotonic_as_threshold_relaxes", monotonic_ok, "行序（阈值放松方向）coverage 非降")
    )
    checks.append(check("panels_nonempty", bool(panels), f"panels={len(panels)}"))
    return panels, excluded, checks


def synthetic_points_rows() -> list[dict[str, str]]:
    """固定种子合成 31 列 points 数据：3 任务 × 4 方法（仅供管线冒烟）。"""
    rng = synthetic_rng("imcr_figure_a_synthetic_points")
    tasks = [("entity_type", 40), ("scope_adjustment", 12), ("tiny_task", 4)]
    methods = [
        ("B1_rule_only", "Rule-only", 0.16),
        ("B2_classifier_only", "Frozen classifier", 0.10),
        ("B4_rule_plus_classifier", "Rule+classifier", 0.08),
        ("B12_full_framework", "Full framework", 0.05),
    ]
    rows: list[dict[str, str]] = []
    for task_type, n_total in tasks:
        for method_id, method_name, base_risk in methods:
            n_points = 9
            coverages = np.linspace(0.08, 0.99, n_points)
            risks = np.clip(base_risk + coverages * float(rng.uniform(0.25, 0.5)) + rng.normal(0, 0.01, n_points), 0.0, 1.0)
            for index in range(n_points):
                rows.append(
                    {
                        "method_id": method_id,
                        "method_name": method_name,
                        "task_type": task_type,
                        "evidence_class": "actual_run",
                        "comparison_tier": "independent_reference",
                        "overlap_status": "independent_of_era",
                        "evaluation_eligibility": "core_eligible_task",
                        "curve_mode": "constrained_selective",
                        "primary_curve": "1",
                        "acceptance_rule": "score>=threshold AND hard_constraint_pass=1",
                        "point_type": "exact_unique",
                        "point_index": str(index),
                        "threshold": f"{1.0 - coverages[index]:.6f}",
                        "accepted_count": str(int(round(coverages[index] * n_total))),
                        "total_count": str(n_total),
                        "coverage": f"{coverages[index]:.6f}",
                        "error_count": str(int(round(risks[index] * coverages[index] * n_total))),
                        "selective_risk": f"{risks[index]:.6f}",
                        "generalized_risk": "",
                        "safe_count": "0",
                        "safe_coverage": "",
                        "abstained_count": "0",
                        "abstention_rate": "",
                        "review_escalation_count": "0",
                        "review_escalation_rate": "",
                        "llm_or_review_escalation_rate": "",
                        "actual_llm_calls": "0",
                        "actual_llm_call_rate": "0",
                        "score_direction": "higher_is_safer",
                        "tie_policy": "accept_all_equal_scores",
                        "denominator_policy": "full_frozen_task_test_set",
                    }
                )
    return rows


def render_risk_coverage(
    panels: list[dict[str, Any]],
    acceptance_rule: str,
    paths: dict[str, Path],
    font: dict[str, Any],
    synthetic: bool,
) -> dict[str, Any]:
    columns = 3
    rows_count = max(1, math.ceil(len(panels) / columns))
    with mpl.rc_context(figure_rc(font)):
        fig, axes = plt.subplots(rows_count, columns, figsize=(11.4, 3.45 * rows_count), squeeze=False)
        style_fallback = 0
        seen_styles: dict[str, tuple[str, str, str]] = {}
        for axis, panel in zip(axes.flat, panels):
            for curve in panel["curves"]:
                method_id = curve["method_id"]
                if method_id not in seen_styles:
                    seen_styles[method_id] = method_style(method_id, style_fallback)
                    style_fallback += 1
                color, linestyle, marker = seen_styles[method_id]
                axis.plot(
                    curve["coverage"],
                    curve["selective_risk"],
                    linestyle=linestyle,
                    marker=marker,
                    markersize=3.4,
                    linewidth=1.8,
                    color=color,
                    label=curve["label"],
                )
            axis.set_title(f"{panel['label']}（n={panel['n']}）", fontsize=10, loc="left")
            axis.set_xlim(0, 1.02)
            axis.set_ylim(0, 1.02)
            axis.set_xlabel("覆盖率 Coverage（固定全测试集分母）")
            axis.set_ylabel("选择性风险 Selective risk")
            axis.grid(True, color=GRID, linewidth=0.7, alpha=0.8)
            axis.spines[["top", "right"]].set_visible(False)
        for axis in axes.flat[len(panels):]:
            axis.axis("off")
        if seen_styles:
            # 图例一律由代理线构建：跨面板聚合全部方法（首个面板未必含全部方法）
            proxy = [
                Line2D([0], [0], color=color, linestyle=ls, marker=mk, markersize=4.5, label=method_label(mid))
                for mid, (color, ls, mk) in seen_styles.items()
            ]
            labels = [line.get_label() for line in proxy]
            fig.legend(proxy, labels, loc="upper center", ncol=min(len(labels), 4), frameon=False, bbox_to_anchor=(0.5, 0.962))
        fig.suptitle("独立参考下的风险—覆盖曲线（约束选择模式）", fontsize=15, y=0.995)
        fig.text(
            0.5,
            0.925,
            f"主曲线准入规则：{acceptance_rule}；未通过者转入人工复核。",
            ha="center",
            va="top",
            fontsize=9.5,
            color=MUTED,
        )
        fig.tight_layout(rect=(0.02, 0.02, 0.99, 0.87))
        if synthetic:
            stamp_synthetic(fig)
        save_figure(fig, paths["png"], paths["pdf"])
    return {
        "n_panels": len(panels),
        "n_curves": sum(len(p["curves"]) for p in panels),
        "method_styles": {mid: {"color": c, "linestyle": ls, "marker": mk} for mid, (c, ls, mk) in seen_styles.items()},
    }


def run_risk_coverage(args: argparse.Namespace) -> int:
    synthetic = bool(getattr(args, "synthetic", False))
    if synthetic:
        rows = synthetic_points_rows()
        inputs: dict[str, Any] = {
            "points": {"synthetic": True, "seed": derive_seed("imcr_figure_a_synthetic_points", MASTER_SEED),
                        "row_count": len(rows), "columns": len(rows[0])}
        }
        input_records: list[dict[str, Any]] = []
        note = "SYNTHETIC 演示数据（固定种子），不代表任何真实实验结果。"
    else:
        rows, points_path, record = load_risk_coverage_points(args.points_dir, args.points_file)
        inputs = {"points": record}
        input_records = [record]
        note = ""

    panels, excluded, checks = prepare_risk_coverage_panels(
        rows, min_task_n=args.min_task_n, methods=args.methods
    )
    if not panels:
        raise ValueError(
            "图A 无可绘面板：所有任务均被排除或无 constrained_selective 主曲线数据；"
            f"排除项={excluded}。若为冒烟测试请加 --synthetic。"
        )
    # acceptance_rule 取自主曲线（constrained_selective）行，而非诊断曲线行
    constrained_rows = [row for row in rows if row.get("curve_mode") == "constrained_selective"]
    rule_source = constrained_rows or rows
    acceptance_rules = sorted({str(row.get("acceptance_rule") or "") for row in rule_source} - {""})
    acceptance_rule = acceptance_rules[0] if acceptance_rules else "score>=threshold AND hard_constraint_pass=1"

    paths = output_paths(Path(args.out_dir), args.prefix, "risk_coverage")
    paths["png"].parent.mkdir(parents=True, exist_ok=True)
    font = resolve_cjk_font()
    render = render_risk_coverage(panels, acceptance_rule, paths, font, synthetic)

    palette = {mid: style["color"] for mid, style in render["method_styles"].items()}
    non_color = {mid: f"{style['linestyle']} {style['marker']}" for mid, style in render["method_styles"].items()}
    contract = base_contract(
        figure_id="imcr_figure_A_risk_coverage",
        analytical_question=(
            "在独立多模型共识参考下，随低置信预测被路由到人工复核，"
            "选择性风险下降多少，付出的覆盖率代价是多少？"
        ),
        supported_takeaway=(
            "图A 仅报告经验风险—覆盖权衡：完整框架（B12）与各独立基线在同一冻结"
            "测试集分母下的 constrained_selective 主曲线；不对未评价样本外推。"
        ),
        family="Uncertainty & Benchmark",
        variant="small-multiple risk-coverage line charts",
        x_axis="覆盖率 Coverage（固定全测试集分母）",
        y_axis="已接纳预测的选择性风险 Selective risk",
        palette=palette,
        non_color=non_color,
        input_records=input_records,
        outputs=[str(paths["png"].resolve()), str(paths["pdf"].resolve())],
        synthetic=synthetic,
        extra={
            "curve_mode": "constrained_selective",
            "acceptance_rule": acceptance_rule,
            "data_sufficiency": {
                "minimum_task_n_for_figure": args.min_task_n,
                "excluded_from_figure": [e["task_type"] for e in excluded],
                "exclusion_reasons": {e["task_type"]: e["reason"] for e in excluded},
            },
        },
    )
    audit = base_audit(
        figure="imcr_figure_A_risk_coverage",
        synthetic=synthetic,
        inputs=inputs,
        checks=checks,
        panels=[
            {
                "task_type": p["task_type"],
                "n": p["n"],
                "curves": [
                    {"method_id": c["method_id"], "n_points": c["n_points"]} for c in p["curves"]
                ],
            }
            for p in panels
        ],
        excluded=excluded,
        render={
            **render,
            "dpi": 240,
            "outputs": {k: str(v.resolve()) for k, v in paths.items()},
            "n_input_columns": len(rows[0]),
        },
        notes=[note] if note else [],
    )
    write_json(paths["contract"], contract)
    write_json(paths["audit"], audit)
    print(f"[build_imcr_figures] 图A risk_coverage -> {paths['png']}")
    return 0


# ===========================================================================
# 图B aurc_augrc_ci
# ===========================================================================

DELTA_REQUIRED_COLUMNS = (
    "task_type",
    "baseline_method_id",
    "metric",
    "status",
    "estimate",
    "ci95_low",
    "ci95_high",
)


def resolve_deltas_file(stats_dir: Path | None, deltas_file: Path | None) -> Path:
    if deltas_file is not None:
        return require_file(deltas_file, "14 号目录 PAIRED_BOOTSTRAP_DELTAS.csv")
    directory = stats_dir or DEFAULT_STATS_DIR
    path = directory / DELTAS_FILE_NAME
    if not path.is_file():
        raise FileNotFoundError(
            f"未找到配对 bootstrap deltas 文件: {path}；请先运行 "
            "run_statistical_tests.py（14 号）或加 --synthetic。"
        )
    return path


def discover_areas_file(areas_dir: Path | None, areas_file: Path | None) -> Path | None:
    """13 号 SUMMARY/GOAL13 文件（可选交叉核验输入）。

    仅当显式提供 ``--areas-file`` / ``--areas-dir`` 时启用：找不到文件返回
    None（audit 记 skipped），绝不静默回落到仓库默认路径，避免测试与开发
    验证混入与当前 deltas 无关的真实文件。
    """
    if areas_file is not None:
        return require_file(areas_file, "13 号目录 <prefix>RISK_COVERAGE_SUMMARY.csv / <prefix>SELECTIVE_GOAL13_METRICS.csv")
    if areas_dir is None or not areas_dir.is_dir():
        return None
    for pattern in (SUMMARY_FILE_GLOB, GOAL13_FILE_GLOB):
        matches = sorted(areas_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def load_delta_rows(path: Path) -> list[dict[str, str]]:
    rows = read_csv_rows(path)
    require_columns(rows, DELTA_REQUIRED_COLUMNS, path)
    return rows


def prepare_delta_panels(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """按 task_type 组装 ΔAURC/ΔAUGRC 误差条数据（仅 status=applicable）。"""
    panels: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    identity_ok = True
    ci_contains_estimate = True
    by_task: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_task.setdefault(row["task_type"], []).append(row)

    for task_type in sorted(by_task, key=task_sort_key):
        task_rows = by_task[task_type]
        applicable = [row for row in task_rows if row.get("status") == "applicable"]
        for row in task_rows:
            if row.get("status") != "applicable":
                excluded.append(
                    {
                        "task_type": task_type,
                        "baseline_method_id": row.get("baseline_method_id", ""),
                        "metric": row.get("metric", ""),
                        "reason": f"status={row.get('status', '')}",
                    }
                )
                continue
        if not applicable:
            excluded.append(
                {"task_type": task_type, "reason": "无 applicable 配对（area gate 未满足）"}
            )
            continue
        metric_values: dict[str, dict[str, dict[str, float | None]]] = {"aurc": {}, "augrc": {}}
        n_samples = 0
        for row in applicable:
            baseline = row["baseline_method_id"]
            metric = row["metric"]
            if metric not in metric_values:
                excluded.append(
                    {"task_type": task_type, "baseline_method_id": baseline, "metric": metric,
                     "reason": f"未知 metric={metric}"}
                )
                continue
            ctx = f"deltas[{task_type}/{baseline}/{metric}]"
            estimate = _to_float(row["estimate"], f"{ctx}.estimate")
            low_raw, high_raw = str(row.get("ci95_low") or ""), str(row.get("ci95_high") or "")
            low = _to_float(low_raw, f"{ctx}.ci95_low") if low_raw else None
            high = _to_float(high_raw, f"{ctx}.ci95_high") if high_raw else None
            if low is not None and high is not None:
                ci_contains_estimate &= low - 1e-12 <= estimate <= high + 1e-12
            full_raw, base_raw = row.get("full_estimate") or "", row.get("baseline_estimate") or ""
            if full_raw and base_raw:
                identity_ok &= abs(
                    (float(full_raw) - float(base_raw)) - estimate
                ) <= 1e-6
            metric_values[metric][baseline] = {
                "estimate": estimate,
                "ci95_low": low,
                "ci95_high": high,
                "full_estimate": float(full_raw) if full_raw else None,
                "baseline_estimate": float(base_raw) if base_raw else None,
            }
            n_samples = max(n_samples, _to_int(row.get("n_samples") or 0, f"{ctx}.n_samples"))
        baselines = ordered_methods(
            [b for metric in DELTA_METRICS for b in metric_values[metric]]
        )
        if not baselines:
            excluded.append({"task_type": task_type, "reason": "无可绘基线"})
            continue
        panels.append(
            {
                "task_type": task_type,
                "label": task_label(task_type),
                "n_samples": n_samples,
                "baselines": baselines,
                "values": metric_values,
            }
        )

    checks.append(check("delta_identity_full_minus_baseline", identity_ok, "estimate = full_estimate − baseline_estimate（±1e-6）"))
    checks.append(check("ci95_contains_point_estimate", ci_contains_estimate, "ci95_low ≤ estimate ≤ ci95_high"))
    checks.append(check("panels_nonempty", bool(panels), f"panels={len(panels)}"))
    return panels, excluded, checks


def areas_crosscheck(
    areas_path: Path | None, panels: list[dict[str, Any]]
) -> dict[str, Any]:
    """用 13 号 SUMMARY/GOAL13 的 AURC/AUGRC 列交叉核验 full/baseline 绝对量。"""
    if areas_path is None:
        return {"status": "skipped", "detail": "未提供 13 号 SUMMARY/GOAL13 文件（--areas-file/--areas-dir）"}
    rows = read_csv_rows(areas_path)
    areas: dict[tuple[str, str], dict[str, float]] = {}
    for row in rows:
        key = (row.get("method_id", ""), row.get("task_type", ""))
        entry: dict[str, float] = {}
        for column, metric in (("aurc_trapezoid", "aurc"), ("augrc_trapezoid", "augrc"),
                               ("aurc", "aurc"), ("augrc", "augrc")):
            raw = str(row.get(column) or "")
            if raw:
                try:
                    entry.setdefault(metric, float(raw))
                except ValueError:
                    continue
        if entry:
            areas.setdefault(key, {}).update(entry)
    worst = 0.0
    compared = 0
    for panel in panels:
        for metric in DELTA_METRICS:
            for baseline, value in panel["values"][metric].items():
                full_area = areas.get((FULL_METHOD_ID, panel["task_type"]), {}).get(metric)
                base_area = areas.get((baseline, panel["task_type"]), {}).get(metric)
                if full_area is not None and base_area is not None:
                    # 交叉核验：配对差值估计 vs 13 号目录两方法绝对面积之差
                    diff = abs((full_area - base_area) - float(value["estimate"]))
                    worst = max(worst, diff)
                    compared += 1
    return {
        "status": "compared" if compared else "no_overlap",
        "detail": f"areas={areas_path.name}, n_compared={compared}, max_abs_diff={worst:.3e}",
        "max_abs_diff": worst,
        "n_compared": compared,
    }


def synthetic_delta_rows() -> list[dict[str, str]]:
    """固定种子合成 deltas：2 任务 × 3 基线 × 2 metric + 1 条 not_applicable。"""
    rng = synthetic_rng("imcr_figure_b_synthetic_deltas")
    rows: list[dict[str, str]] = []
    for task_type, n_samples in (("entity_type", 40), ("scope_adjustment", 12)):
        for baseline in ("B1_rule_only", "B2_classifier_only", "B4_rule_plus_classifier"):
            for metric in DELTA_METRICS:
                estimate = float(rng.uniform(-0.08, 0.02))
                low, high = estimate - float(rng.uniform(0.01, 0.05)), estimate + float(rng.uniform(0.01, 0.05))
                rows.append(
                    {
                        "task_type": task_type,
                        "baseline_method_id": baseline,
                        "metric": metric,
                        "status": "applicable",
                        "n_samples": str(n_samples),
                        "n_replicates": "200",
                        "n_valid_replicates": "200",
                        "estimate": f"{estimate:.6f}",
                        "ci95_low": f"{low:.6f}",
                        "ci95_high": f"{high:.6f}",
                        "full_estimate": f"{0.12 + estimate:.6f}",
                        "baseline_estimate": "0.120000",
                        "bootstrap_seed": str(derive_seed(f"synthetic::{task_type}::{baseline}")),
                        "note": "synthetic demo row",
                    }
                )
    rows.append(
        {
            "task_type": "provenance_support",
            "baseline_method_id": "B1_rule_only",
            "metric": "aurc",
            "status": "not_applicable_insufficient_scores",
            "n_samples": "3",
            "note": "area gate reused from run_selective_inference",
        }
    )
    return rows


def render_aurc_augrc_ci(
    panels: list[dict[str, Any]],
    paths: dict[str, Path],
    font: dict[str, Any],
    synthetic: bool,
) -> dict[str, Any]:
    columns = min(2, max(1, len(panels)))
    rows_count = max(1, math.ceil(len(panels) / columns))
    with mpl.rc_context(figure_rc(font)):
        fig, axes = plt.subplots(rows_count, columns, figsize=(6.6 * columns, 4.4 * rows_count), squeeze=False)
        metric_style = {
            "aurc": {"color": BLUE, "marker": "o", "label": "ΔAURC（Full−基线）"},
            "augrc": {"color": ORANGE, "marker": "s", "label": "ΔAUGRC（Full−基线）"},
        }
        plotted_panels = 0
        for axis, panel in zip(axes.flat, panels):
            baselines = panel["baselines"]
            x = np.arange(len(baselines), dtype=float)
            offsets = {"aurc": -0.17, "augrc": 0.17}
            for metric in DELTA_METRICS:
                style = metric_style[metric]
                estimates, lows, highs, xs = [], [], [], []
                for index, baseline in enumerate(baselines):
                    value = panel["values"][metric].get(baseline)
                    if not value or value["estimate"] is None:
                        continue
                    estimates.append(value["estimate"])
                    lows.append(
                        max(0.0, value["estimate"] - value["ci95_low"])
                        if value["ci95_low"] is not None
                        else 0.0
                    )
                    highs.append(
                        max(0.0, value["ci95_high"] - value["estimate"])
                        if value["ci95_high"] is not None
                        else 0.0
                    )
                    xs.append(x[index] + offsets[metric])
                if estimates:
                    axis.errorbar(
                        xs,
                        estimates,
                        yerr=[lows, highs],
                        linestyle="none",
                        marker=style["marker"],
                        markersize=5,
                        capsize=3,
                        linewidth=1.4,
                        color=style["color"],
                        label=style["label"],
                    )
            axis.axhline(0.0, color=MUTED, linewidth=1.0, linestyle="--")
            axis.set_xticks(x)
            axis.set_xticklabels([method_label(b) for b in baselines], rotation=30, ha="right", fontsize=8.5)
            axis.set_title(f"{panel['label']}（n={panel['n_samples']}）", loc="left", fontsize=10)
            axis.set_ylabel("面积差 Full − 基线（负值=完整框架更优）")
            axis.grid(True, axis="y", color=GRID, linewidth=0.7, alpha=0.8)
            axis.spines[["top", "right"]].set_visible(False)
            axis.legend(frameon=False, fontsize=8.5, loc="best")
            plotted_panels += 1
        for axis in axes.flat[plotted_panels:]:
            axis.axis("off")
        fig.suptitle("AURC / AUGRC 配对比较（Full − 基线，95% bootstrap CI）", fontsize=14, y=0.99)
        fig.tight_layout(rect=(0.0, 0.02, 1.0, 0.94))
        if synthetic:
            stamp_synthetic(fig)
        save_figure(fig, paths["png"], paths["pdf"])
    return {"n_panels": plotted_panels, "n_errorbar_series": 2 * plotted_panels, "dpi": 240}


def run_aurc_augrc_ci(args: argparse.Namespace) -> int:
    synthetic = bool(getattr(args, "synthetic", False))
    notes: list[str] = []
    if synthetic:
        rows = synthetic_delta_rows()
        inputs: dict[str, Any] = {
            "deltas": {
                "synthetic": True,
                "seed": derive_seed("imcr_figure_b_synthetic_deltas", MASTER_SEED),
                "row_count": len(rows),
            }
        }
        input_records: list[dict[str, Any]] = []
        areas_path: Path | None = None
    else:
        deltas_path = resolve_deltas_file(args.stats_dir, args.deltas_file)
        rows = load_delta_rows(deltas_path)
        record = input_record(deltas_path, len(rows))
        inputs = {"deltas": record}
        input_records = [record]
        areas_path = discover_areas_file(args.areas_dir, args.areas_file)
        if areas_path is None:
            notes.append(
                "未提供/未找到 13 号 SUMMARY/GOAL13（--areas-file/--areas-dir），"
                "AURC/AUGRC 绝对量交叉核验跳过。"
            )

    panels, excluded, checks = prepare_delta_panels(rows)
    if not panels:
        raise ValueError(
            f"图B 无可绘面板：没有任何 task_type 存在 applicable 配对；排除项={excluded}。"
            "若为冒烟测试请加 --synthetic。"
        )
    crosscheck = areas_crosscheck(areas_path, panels)
    if areas_path is not None and not synthetic:
        input_records.append(input_record(areas_path))
        inputs["areas_crosscheck_file"] = input_record(areas_path)

    paths = output_paths(Path(args.out_dir), args.prefix, "aurc_augrc_ci")
    paths["png"].parent.mkdir(parents=True, exist_ok=True)
    font = resolve_cjk_font()
    render = render_aurc_augrc_ci(panels, paths, font, synthetic)

    palette = {"ΔAURC": BLUE, "ΔAUGRC": ORANGE}
    non_color = {"ΔAURC": "circle marker, left offset", "ΔAUGRC": "square marker, right offset"}
    contract = base_contract(
        figure_id="imcr_figure_B_aurc_augrc_ci",
        analytical_question=(
            "在同一冻结测试集上，完整框架相对各独立基线的 AURC/AUGRC 面积差"
            "及其 95% 置信区间如何？负值表示完整框架更优。"
        ),
        supported_takeaway=(
            "图B 报告配对 bootstrap（共享重采样索引）下的 ΔAURC/ΔAUGRC 点估计与"
            "95% CI（Full − 基线，负值 = Full 更优）；area gate 未满足的配对不入图。"
        ),
        family="Uncertainty & Benchmark",
        variant="per-task errorbar chart with y=0 reference",
        x_axis="独立基线（每 task_type 一个面板）",
        y_axis="面积差 Full − 基线（负值 = 完整框架更优）",
        palette=palette,
        non_color=non_color,
        input_records=input_records,
        outputs=[str(paths["png"].resolve()), str(paths["pdf"].resolve())],
        synthetic=synthetic,
        extra={
            "delta_sign": "Full - baseline (negative = Full better)",
            "bootstrap": {
                "shared_resample_indices": True,
                "source": "run_statistical_tests.py / metrics.paired_bootstrap_diff_ci",
            },
            "areas_crosscheck": crosscheck,
        },
    )
    audit = base_audit(
        figure="imcr_figure_B_aurc_augrc_ci",
        synthetic=synthetic,
        inputs=inputs,
        checks=checks + [check("areas_crosscheck", crosscheck["status"] != "compared" or crosscheck["max_abs_diff"] <= 1e-6, crosscheck["detail"])],
        panels=[
            {
                "task_type": p["task_type"],
                "n_samples": p["n_samples"],
                "baselines": p["baselines"],
                "metrics": DELTA_METRICS,
            }
            for p in panels
        ],
        excluded=excluded,
        render={**render, "outputs": {k: str(v.resolve()) for k, v in paths.items()}},
        notes=notes,
    )
    write_json(paths["contract"], contract)
    write_json(paths["audit"], audit)
    print(f"[build_imcr_figures] 图B aurc_augrc_ci -> {paths['png']}")
    return 0


# ===========================================================================
# 图C scope_validation
# ===========================================================================

REFERENCE_REQUIRED_COLUMNS = ("task_type", "sample_id")


def _label_of(row: dict[str, str]) -> str:
    """参考标签解析：reference_label → imcr_label_decoded → imcr_label。"""
    for column in ("reference_label", "imcr_label_decoded", "imcr_label"):
        value = str(row.get(column) or "").strip()
        if value:
            return value
    return ""


def load_scope_reference(path: Path) -> tuple[Counter, dict[str, Any]]:
    require_file(path, "08 号目录 IMCR_REFERENCE_ALL.csv")
    rows = read_csv_rows(path)
    require_columns(rows, REFERENCE_REQUIRED_COLUMNS, path)
    counts: Counter[str] = Counter()
    for row in rows:
        if row.get("task_type") != "scope_adjustment":
            continue
        label = _label_of(row)
        if label:
            counts[label] += 1
    return counts, input_record(path, len(rows))


def load_scope_totals(
    manifest_path: Path | None, raw_root: Path | None, labeled: int
) -> dict[str, Any]:
    """共识总任务数与 unresolved：manifest manifest_tasks 优先，raw_root 兜底。"""
    if manifest_path is not None and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        for entry in manifest.get("tasks", []):
            if entry.get("task_type") == "scope_adjustment":
                n_tasks = int(entry.get("n_tasks", 0))
                n_unresolved = int(entry.get("n_unresolved", max(0, n_tasks - labeled)))
                return {
                    "source": "manifest",
                    "n_tasks": n_tasks,
                    "n_unresolved": n_unresolved,
                    "manifest_path": str(manifest_path.resolve()),
                }
    if raw_root is not None:
        task_dir = raw_root / "scope_adjustment"
        if task_dir.is_dir():
            task_ids: set[str] = set()
            for jsonl in sorted(task_dir.glob("*.jsonl")):
                for line in jsonl.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if rec.get("task_id"):
                        task_ids.add(str(rec.get("task_id")))
            if task_ids:
                return {
                    "source": "raw_runs",
                    "n_tasks": len(task_ids),
                    "n_unresolved": max(0, len(task_ids) - labeled),
                    "manifest_path": None,
                }
    return {
        "source": "labeled_only",
        "n_tasks": labeled,
        "n_unresolved": 0,
        "manifest_path": None,
    }


def load_judge_vote_counts(
    raw_root: Path, payloads_dir: Path
) -> tuple[dict[str, Counter], dict[str, Any], dict[str, Any]]:
    """各 judge 的解码后 before/after 偏好分布（复用 build_imcr_consensus 逻辑）。"""
    if not raw_root.is_dir():
        raise FileNotFoundError(
            f"--raw-root 不存在: {raw_root}（08 号 raw_runs 目录）；不传 --raw-root 则跳过 judge 面板。"
        )
    ab_mapping = consensus_builder.load_ab_mapping(payloads_dir)
    if not ab_mapping:
        raise FileNotFoundError(
            f"在 {payloads_dir} 下未找到有效的 {AB_MAPPING_FILE_NAME}；"
            "无法把 A_BETTER/B_BETTER 解码回 BEFORE_/AFTER_ 语义。"
        )
    runs = consensus_builder.load_raw_runs(raw_root, "scope_adjustment")
    if not runs:
        raise FileNotFoundError(
            f"在 {raw_root / 'scope_adjustment'} 下未找到任何 judge jsonl 记录。"
        )
    invalid_votes = {"", "MODEL_OUTPUT_INVALID", "None"}
    judge_counts: dict[str, Counter] = {}
    for judge, records in runs.items():
        counts: Counter[str] = Counter()
        for _task_id, rec in records.items():
            decision = ""
            if rec.get("status") == "OK" and rec.get("parsed_response"):
                decision = str(rec["parsed_response"].get("decision") or "")
            if decision in invalid_votes:
                counts["INVALID"] += 1
                continue
            decoded = consensus_builder.decode_ab_label(decision, ab_mapping.get(_task_id))
            counts[str(decoded)] += 1
        judge_counts[judge] = counts
    mapping_record = input_record(payloads_dir / AB_MAPPING_FILE_NAME)
    return judge_counts, {"judges": sorted(judge_counts), "raw_root": str(raw_root.resolve())}, mapping_record


def synthetic_scope_data() -> tuple[Counter, dict[str, Any], dict[str, Counter], dict[str, Any]]:
    """固定种子合成：208 任务规模演示数据（共识 + 三 judge 票）。"""
    rng = synthetic_rng("imcr_figure_c_synthetic_scope")
    n_tasks = 208
    labels = ["BEFORE_BETTER", "AFTER_BETTER", "EQUIVALENT", "BOTH_WRONG", "INSUFFICIENT_EVIDENCE"]
    consensus = Counter()
    judge_counts = {judge: Counter() for judge in ("A", "B", "C")}
    for index in range(n_tasks):
        roll = float(rng.uniform())
        if roll < 0.06:  # unresolved：不出参考标签，judge 票散乱
            for judge in judge_counts:
                judge_counts[judge][labels[int(rng.integers(0, len(labels)))]] += 1
            continue
        label = labels[int(rng.integers(0, 3))] if roll < 0.9 else labels[3 + int(rng.integers(0, 2))]
        consensus[label] += 1
        for judge in judge_counts:
            agree = float(rng.uniform()) < 0.78
            judge_counts[judge][label if agree else labels[int(rng.integers(0, len(labels)))]] += 1
    for judge in judge_counts:
        judge_counts[judge]["INVALID"] += int(rng.integers(0, 3))
    totals = {
        "source": "synthetic_manifest",
        "n_tasks": n_tasks,
        "n_unresolved": n_tasks - sum(consensus.values()),
        "manifest_path": None,
    }
    inputs = {"synthetic": True, "seed": derive_seed("imcr_figure_c_synthetic_scope", MASTER_SEED)}
    return consensus, totals, judge_counts, inputs


def render_scope_validation(
    consensus: Counter,
    totals: dict[str, Any],
    judge_counts: dict[str, Counter] | None,
    paths: dict[str, Path],
    font: dict[str, Any],
    synthetic: bool,
) -> dict[str, Any]:
    n_panels = 2 if judge_counts else 1
    with mpl.rc_context(figure_rc(font)):
        fig, axes = plt.subplots(1, n_panels, figsize=(6.9 * n_panels + 0.7, 4.9), squeeze=False)

        # 左：共识标签分布（含 unresolved）
        axis = axes[0][0]
        order = [label for label in SCOPE_LABEL_ORDER if consensus.get(label)]
        values = [consensus.get(label, 0) for label in order]
        if totals.get("n_unresolved"):
            order = order + ["UNRESOLVED"]
            values = values + [int(totals["n_unresolved"])]
        colors = [SCOPE_LABEL_ZH[label][1] for label in order]
        bars = axis.bar(range(len(order)), values, color=colors, edgecolor="white")
        axis.set_xticks(range(len(order)))
        axis.set_xticklabels([SCOPE_LABEL_ZH[label][0] for label in order], rotation=25, ha="right", fontsize=8.8)
        for bar, value in zip(bars, values):
            axis.text(bar.get_x() + bar.get_width() / 2, value, str(value), ha="center", va="bottom", fontsize=8.5)
        axis.set_ylabel("任务数")
        axis.set_title(
            f"共识标签分布（已标 {sum(consensus.values())} / 共 {totals['n_tasks']}，"
            f"unresolved {totals['n_unresolved']}）",
            loc="left",
            fontsize=10,
        )
        axis.grid(True, axis="y", color=GRID, linewidth=0.7, alpha=0.8)
        axis.spines[["top", "right"]].set_visible(False)

        # 右：各 judge 与共识的 before/after 偏好堆叠条
        if judge_counts:
            axis = axes[0][1]
            groups: list[tuple[str, Counter]] = [
                (f"Judge {judge}", counts) for judge, counts in sorted(judge_counts.items())
            ]
            consensus_counts: Counter = Counter(consensus)
            if totals.get("n_unresolved"):
                consensus_counts["UNRESOLVED"] = int(totals["n_unresolved"])
            groups.append(("共识", consensus_counts))
            segment_order = [
                *SCOPE_LABEL_ORDER,
                *([label for label in ("UNRESOLVED", "INVALID") if any(label in c for _, c in groups)]),
            ]
            x = np.arange(len(groups))
            bottoms = np.zeros(len(groups))
            for label in segment_order:
                values = np.array([counts.get(label, 0) for _, counts in groups], dtype=float)
                if not values.any():
                    continue
                axis.bar(
                    x,
                    values,
                    bottom=bottoms,
                    color=SCOPE_LABEL_ZH[label][1],
                    edgecolor="white",
                    label=SCOPE_LABEL_ZH[label][0],
                )
                bottoms += values
            axis.set_xticks(x)
            axis.set_xticklabels([name for name, _ in groups], fontsize=9)
            axis.set_ylabel("票数 / 任务数")
            axis.set_title("各 judge 与共识的改前/改后偏好构成", loc="left", fontsize=10)
            axis.legend(frameon=False, fontsize=8, ncol=2, loc="upper right")
            axis.grid(True, axis="y", color=GRID, linewidth=0.7, alpha=0.8)
            axis.spines[["top", "right"]].set_visible(False)
        fig.suptitle(
            f"时空范围校正任务（scope_adjustment，共 {totals['n_tasks']} 条）的改前/改后共识校验",
            fontsize=14,
            y=0.99,
        )
        fig.tight_layout(rect=(0.0, 0.02, 1.0, 0.93))
        if synthetic:
            stamp_synthetic(fig)
        save_figure(fig, paths["png"], paths["pdf"])
    return {
        "n_panels": n_panels,
        "judge_panel": bool(judge_counts),
        "dpi": 240,
    }


def run_scope_validation(args: argparse.Namespace) -> int:
    synthetic = bool(getattr(args, "synthetic", False))
    notes: list[str] = []
    checks: list[dict[str, Any]] = []
    if synthetic:
        consensus, totals, judge_counts, inputs = synthetic_scope_data()
        input_records: list[dict[str, Any]] = []
    else:
        consensus, reference_record = load_scope_reference(args.reference_csv)
        totals = load_scope_totals(args.manifest_json, args.raw_root, sum(consensus.values()))
        if totals["source"] == "labeled_only":
            notes.append(
                "未找到 manifest/raw_runs：unresolved 无法独立推断，按 0 处理（labeled 即全部）。"
            )
        judge_counts = None
        judge_record: dict[str, Any] = {}
        mapping_record: dict[str, Any] = {}
        if args.raw_root:
            judge_counts, judge_record, mapping_record = load_judge_vote_counts(
                args.raw_root, args.payloads_dir
            )
        inputs = {
            "reference": reference_record,
            "totals": totals,
            **({"judge_votes": judge_record} if judge_record else {}),
            **({"ab_mapping": mapping_record} if mapping_record else {}),
        }
        input_records = [reference_record]
        if totals.get("manifest_path"):
            manifest_path = Path(totals["manifest_path"])
            input_records.append(input_record(manifest_path))
    checks.append(
        check(
            "labeled_plus_unresolved_equals_total",
            sum(consensus.values()) + int(totals.get("n_unresolved") or 0) <= totals["n_tasks"] + 1e-9,
            f"labeled={sum(consensus.values())}, unresolved={totals.get('n_unresolved')}, total={totals['n_tasks']}",
        )
    )
    checks.append(check("labeled_nonempty", bool(consensus), f"labeled={sum(consensus.values())}"))
    unknown = sorted(set(consensus) - set(SCOPE_LABEL_ORDER))
    checks.append(check("labels_in_allowed_set", not unknown, f"unknown={unknown}"))
    if not consensus:
        raise ValueError(
            f"scope_adjustment 在参考集中没有任何已标任务（{args.reference_csv}）；"
            "若为冒烟测试请加 --synthetic。"
        )

    paths = output_paths(Path(args.out_dir), args.prefix, "scope_validation")
    paths["png"].parent.mkdir(parents=True, exist_ok=True)
    font = resolve_cjk_font()
    render = render_scope_validation(consensus, totals, judge_counts, paths, font, synthetic)

    palette = {SCOPE_LABEL_ZH[label][0]: SCOPE_LABEL_ZH[label][1] for label in [*SCOPE_LABEL_ORDER, "UNRESOLVED"]}
    non_color = {SCOPE_LABEL_ZH[label][0]: f"stack segment #{index + 1}" for index, label in enumerate(SCOPE_LABEL_ORDER)}
    contract = base_contract(
        figure_id="imcr_figure_C_scope_validation",
        analytical_question=(
            "208 条时空范围校正任务在盲评三 judge 共识下，改前/改后偏好的分布如何？"
            "各 judge 与共识是否同向？"
        ),
        supported_takeaway=(
            "图C 报告 scope_adjustment 共识标签分布（含 unresolved 计数）与各 judge "
            "解码后偏好的构成对比；A/B 匿名标签经 SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING "
            "解码回 BEFORE_/AFTER_ 语义。"
        ),
        family="Independent reference validation",
        variant="distribution bar + judge stacked composition",
        x_axis="标签 / judge",
        y_axis="任务数（左）/ 票数（右）",
        palette=palette,
        non_color=non_color,
        input_records=input_records,
        outputs=[str(paths["png"].resolve()), str(paths["pdf"].resolve())],
        synthetic=synthetic,
        extra={
            "label_decoding": "build_imcr_consensus.decode_ab_label + SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING.csv",
            "unresolved_source": totals.get("source"),
        },
    )
    audit = base_audit(
        figure="imcr_figure_C_scope_validation",
        synthetic=synthetic,
        inputs=inputs,
        checks=checks,
        panels=[
            {"panel": "consensus_distribution", "labeled": sum(consensus.values()), "total": totals["n_tasks"], "unresolved": totals.get("n_unresolved")},
            *(
                [
                    {
                        "panel": "judge_votes",
                        "judges": {judge: dict(counts) for judge, counts in sorted(judge_counts.items())},
                    }
                ]
                if judge_counts
                else []
            ),
        ],
        excluded=[] if judge_counts or synthetic else [
            {"panel": "judge_votes", "reason": "未提供 --raw-root，judge 原始票面板跳过"}
        ],
        render={**render, "outputs": {k: str(v.resolve()) for k, v in paths.items()}},
        notes=notes,
    )
    write_json(paths["contract"], contract)
    write_json(paths["audit"], audit)
    print(f"[build_imcr_figures] 图C scope_validation -> {paths['png']}")
    return 0


# ===========================================================================
# 图D relation_contract_validation
# ===========================================================================

SAMPLE_REQUIRED_COLUMNS = ("sample_id", "sample_role")


def load_relation_inputs(
    sample_csv: Path, reference_csv: Path
) -> tuple[dict[str, str], Counter, dict[str, str], dict[str, Any], dict[str, Any]]:
    """读 RELATION_CONTRACT_SAMPLE.csv 与 IMCR_REFERENCE_ALL.csv（relation_contract 行）。

    返回 (role_map, role_totals, reference_labels, sample_record, reference_record)。
    """
    require_file(sample_csv, "08 号目录 RELATION_CONTRACT_SAMPLE.csv")
    require_file(reference_csv, "08 号目录 IMCR_REFERENCE_ALL.csv")
    sample_rows = read_csv_rows(sample_csv)
    require_columns(sample_rows, SAMPLE_REQUIRED_COLUMNS, sample_csv)
    role_map: dict[str, str] = {}
    role_totals: Counter[str] = Counter()
    for row in sample_rows:
        if row.get("sample_role") in ("changed", "control"):
            role_map[row["sample_id"]] = row["sample_role"]
            role_totals[row["sample_role"]] += 1

    reference_rows = read_csv_rows(reference_csv)
    require_columns(reference_rows, REFERENCE_REQUIRED_COLUMNS, reference_csv)
    reference = {
        row["sample_id"]: _label_of(row)
        for row in reference_rows
        if row.get("task_type") == "relation_contract" and _label_of(row)
    }
    return (
        role_map,
        role_totals,
        reference,
        input_record(sample_csv, len(sample_rows)),
        input_record(reference_csv, len(reference_rows)),
    )


def prepare_relation_groups(
    role_totals: Counter, role_map: dict[str, str], reference: dict[str, str]
) -> tuple[dict[str, Counter], dict[str, int], list[dict[str, Any]]]:
    """changed/control 两组的共识标签构成；unlabeled = 组内样本数 − 已标数。"""
    composition: dict[str, Counter] = {"changed": Counter(), "control": Counter()}
    unlabeled: dict[str, int] = {"changed": 0, "control": 0}
    excluded: list[dict[str, Any]] = []
    for sample_id, label in sorted(reference.items()):
        role = role_map.get(sample_id)
        if role is None:
            excluded.append(
                {"sample_id": sample_id, "reason": "sample_id 不在 RELATION_CONTRACT_SAMPLE 的 changed/control 集内"}
            )
            continue
        composition[role][label] += 1
    for role in ("changed", "control"):
        unlabeled[role] = max(0, role_totals.get(role, 0) - sum(composition[role].values()))
    return composition, unlabeled, excluded


def b12_relation_accuracy(
    runs_csv: Path, reference_csv: Path, role_map: dict[str, str]
) -> tuple[dict[str, dict[str, Any]] | None, dict[str, Any], dict[str, Any]]:
    """B12 在 changed/control 两组上的准确率（apply_imcr_reference 语义重算）。

    返回 (accuracy | None, meta, runs_record)。runs 文件不存在 / 无 B12 行 /
    组内无参考覆盖行时 accuracy 为 None（面板跳过，audit 记录原因）。
    """
    if not runs_csv.is_file():
        return None, {
            "status": "runs_not_found",
            "detail": f"{runs_csv} 不存在，B12 准确率面板跳过（该输入为可选）",
        }, {"path": str(runs_csv.resolve()), "exists": False}
    try:
        reference_map = rsi.load_imcr_reference(reference_csv, "imcr_all")
    except ValueError as exc:  # 旧版参考文件缺 reference_label/sample_id 列等
        reference_rows = read_csv_rows(reference_csv)
        reference_map = {
            (row["sample_id"], row["task_type"]): _label_of(row)
            for row in reference_rows
            if row.get("task_type") == "relation_contract" and _label_of(row)
        }
        if not reference_map:
            raise ValueError(f"参考文件 {reference_csv} 无 relation_contract 标签：{exc}") from exc
    all_rows = read_csv_rows(runs_csv)
    runs_rows = [
        row
        for row in all_rows
        if row.get("task_type") == "relation_contract" and row.get("method_id") == FULL_METHOD_ID
    ]
    runs_record = input_record(runs_csv, len(all_rows))
    if not runs_rows:
        return None, {
            "status": "no_b12_rows",
            "detail": f"{runs_csv.name} 无 {FULL_METHOD_ID}/relation_contract 行，准确率面板跳过",
        }, runs_record
    retained, _meta = rsi.apply_imcr_reference(runs_rows, reference_map, "imcr_all")
    accuracy: dict[str, dict[str, Any]] = {}
    for role in ("changed", "control"):
        group = [row for row in retained if role_map.get(row["sample_id"]) == role]
        n = len(group)
        if n == 0:
            return None, {
                "status": "empty_group",
                "detail": f"B12 在 {role} 组没有 reference 覆盖行，准确率面板跳过",
            }, runs_record
        k = sum(int(float(row["correct"])) for row in group)
        low, high = selective_metrics.wilson_ci(k, n)
        accuracy[role] = {"accuracy": k / n, "n": n, "correct": k, "ci95_low": low, "ci95_high": high}
    return accuracy, {"status": "ok", "rows_retained": len(retained)}, runs_record



def render_relation_contract_validation(
    composition: dict[str, Counter],
    unlabeled: dict[str, int],
    accuracy: dict[str, dict[str, Any]] | None,
    paths: dict[str, Path],
    font: dict[str, Any],
    synthetic: bool,
) -> dict[str, Any]:
    n_panels = 2 if accuracy else 1
    with mpl.rc_context(figure_rc(font)):
        fig, axes = plt.subplots(1, n_panels, figsize=(6.9 * n_panels + 0.7, 4.9), squeeze=False)

        axis = axes[0][0]
        roles = [role for role in ("changed", "control") if role in composition]
        segment_order = [
            label
            for label in RELATION_LABEL_ORDER
            if any(composition[role].get(label) for role in roles)
        ]
        if any(unlabeled.get(role) for role in roles):
            segment_order.append("UNLABELED")
        x = np.arange(len(roles))
        bottoms = np.zeros(len(roles))
        for label in segment_order:
            values = np.array(
                [
                    composition[role].get(label, 0) if label != "UNLABELED" else unlabeled.get(role, 0)
                    for role in roles
                ],
                dtype=float,
            )
            axis.bar(
                x,
                values,
                bottom=bottoms,
                width=0.55,
                color=RELATION_LABEL_ZH[label][1],
                edgecolor="white",
                label=RELATION_LABEL_ZH[label][0],
            )
            bottoms += values
        axis.set_xticks(x)
        axis.set_xticklabels([ROLE_ZH.get(role, role) for role in roles], fontsize=9.5)
        axis.set_ylabel("样本数")
        axis.set_title("changed vs control 的共识标签构成", loc="left", fontsize=10)
        axis.legend(frameon=False, fontsize=8.5, ncol=2)
        axis.grid(True, axis="y", color=GRID, linewidth=0.7, alpha=0.8)
        axis.spines[["top", "right"]].set_visible(False)

        if accuracy:
            axis = axes[0][1]
            roles_acc = [role for role in ("changed", "control") if role in accuracy]
            estimates = [accuracy[role]["accuracy"] for role in roles_acc]
            errors = [
                [
                    max(0.0, accuracy[role]["accuracy"] - accuracy[role]["ci95_low"])
                    for role in roles_acc
                ],
                [
                    max(0.0, accuracy[role]["ci95_high"] - accuracy[role]["accuracy"])
                    for role in roles_acc
                ],
            ]
            bars = axis.bar(
                np.arange(len(roles_acc)),
                estimates,
                yerr=errors,
                capsize=5,
                width=0.55,
                color=[BLUE, ORANGE][: len(roles_acc)],
                edgecolor="white",
            )
            for index, (bar, role) in enumerate(zip(bars, roles_acc)):
                axis.text(
                    bar.get_x() + bar.get_width() / 2,
                    accuracy[role]["ci95_high"],
                    f"{accuracy[role]['accuracy']:.3f}（n={accuracy[role]['n']}）",
                    ha="center",
                    va="bottom",
                    fontsize=9,
                )
            axis.set_xticks(np.arange(len(roles_acc)))
            axis.set_xticklabels([ROLE_ZH.get(role, role) for role in roles_acc], fontsize=9.5)
            axis.set_ylim(0, 1.05)
            axis.set_ylabel("B12 准确率（95% Wilson CI）")
            axis.set_title("完整框架（B12）在两组上的准确率", loc="left", fontsize=10)
            axis.grid(True, axis="y", color=GRID, linewidth=0.7, alpha=0.8)
            axis.spines[["top", "right"]].set_visible(False)
        fig.suptitle("关系契约 changed 集与对照集的独立共识校验", fontsize=14, y=0.99)
        fig.tight_layout(rect=(0.0, 0.02, 1.0, 0.93))
        if synthetic:
            stamp_synthetic(fig)
        save_figure(fig, paths["png"], paths["pdf"])
    return {"n_panels": n_panels, "accuracy_panel": bool(accuracy), "dpi": 240}


def synthetic_relation_data() -> tuple[dict[str, Counter], dict[str, int], dict[str, dict[str, Any]] | None]:
    """固定种子合成：changed/control 各 40 样本 + B12 runs 行。"""
    rng = synthetic_rng("imcr_figure_d_synthetic_relation")
    labels = list(RELATION_LABEL_ORDER)
    composition = {"changed": Counter(), "control": Counter()}
    unlabeled = {"changed": 0, "control": 0}
    sample_rows: list[dict[str, str]] = []
    reference_rows: list[dict[str, str]] = []
    for role, probs in (("changed", (0.42, 0.26, 0.2, 0.12)), ("control", (0.72, 0.12, 0.1, 0.06))):
        for index in range(40):
            sample_id = f"RC-{'S' if role == 'changed' else 'C'}-{index + 1:04d}"
            sample_rows.append({"sample_id": sample_id, "sample_role": role})
            if float(rng.uniform()) < 0.08:
                unlabeled[role] += 1
                continue
            label = labels[int(rng.choice(4, p=probs))]
            composition[role][label] += 1
            reference_rows.append(
                {"sample_id": sample_id, "task_type": "relation_contract", "reference_label": label}
            )
    runs_rows: list[dict[str, str]] = []
    for row in reference_rows:
        correct = float(rng.uniform()) < (0.7 if row["sample_id"].startswith("RC-S") else 0.85)
        prediction = row["reference_label"] if correct else labels[int(rng.integers(0, 4))]
        runs_rows.append(
            {
                "sample_id": row["sample_id"],
                "task_type": "relation_contract",
                "method_id": FULL_METHOD_ID,
                "method_name": "Full framework",
                "availability_status": "available",
                "prediction": prediction,
                "confidence": "0.9",
                "covered": "0",
                "correct": "0",
                "hard_constraint_pass": "1",
                "safe_correct": "0",
                "actual_llm_calls": "0",
                "note": "synthetic demo row",
            }
        )
    # 复用生产语义重算正确性（apply_imcr_reference）
    reference_map = {
        (row["sample_id"], row["task_type"]): row["reference_label"] for row in reference_rows
    }
    retained, _ = rsi.apply_imcr_reference(runs_rows, reference_map, "imcr_all")
    role_by_sample = {row["sample_id"]: row["sample_role"] for row in sample_rows}
    accuracy: dict[str, dict[str, Any]] = {}
    for role in ("changed", "control"):
        group = [row for row in retained if role_by_sample.get(row["sample_id"]) == role]
        n = len(group)
        k = sum(int(float(row["correct"])) for row in group)
        low, high = selective_metrics.wilson_ci(k, n)
        accuracy[role] = {"accuracy": k / n, "n": n, "correct": k, "ci95_low": low, "ci95_high": high}
    return composition, unlabeled, accuracy


def run_relation_contract_validation(args: argparse.Namespace) -> int:
    synthetic = bool(getattr(args, "synthetic", False))
    notes: list[str] = []
    if synthetic:
        composition, unlabeled, accuracy = synthetic_relation_data()
        inputs: dict[str, Any] = {
            "synthetic": True,
            "seed": derive_seed("imcr_figure_d_synthetic_relation", MASTER_SEED),
        }
        input_records: list[dict[str, Any]] = []
    else:
        role_map, role_totals, reference, sample_record, reference_record = load_relation_inputs(
            args.sample_csv, args.reference_csv
        )
        composition, unlabeled, group_excluded = prepare_relation_groups(role_totals, role_map, reference)
        if not composition["changed"] and not composition["control"]:
            raise ValueError(
                f"relation_contract 在参考集中没有任何可分组标签（sample={args.sample_csv}, "
                f"reference={args.reference_csv}）；若为冒烟测试请加 --synthetic。"
            )
        accuracy, acc_meta, runs_record = b12_relation_accuracy(args.runs_csv, args.reference_csv, role_map)
        if accuracy is None:
            notes.append(acc_meta.get("detail", str(acc_meta)))
        inputs = {
            "sample": sample_record,
            "reference": reference_record,
            **({"runs": runs_record} if runs_record else {}),
            "b12_accuracy_meta": acc_meta,
        }
        input_records = [sample_record, reference_record, *([runs_record] if runs_record else [])]

    checks = [
        check(
            "changed_and_control_both_present",
            bool(composition["changed"]) and bool(composition["control"]),
            f"changed={sum(composition['changed'].values())}, control={sum(composition['control'].values())}",
        )
    ]
    if accuracy:
        checks.append(
            check(
                "accuracy_within_unit_interval",
                all(0.0 <= v["accuracy"] <= 1.0 for v in accuracy.values()),
                json.dumps({k: round(v["accuracy"], 4) for k, v in accuracy.items()}, ensure_ascii=False),
            )
        )
    paths = output_paths(Path(args.out_dir), args.prefix, "relation_contract_validation")
    paths["png"].parent.mkdir(parents=True, exist_ok=True)
    font = resolve_cjk_font()
    render = render_relation_contract_validation(composition, unlabeled, accuracy, paths, font, synthetic)

    palette = {RELATION_LABEL_ZH[label][0]: RELATION_LABEL_ZH[label][1] for label in [*RELATION_LABEL_ORDER, "UNLABELED"]}
    non_color = {RELATION_LABEL_ZH[label][0]: f"stack segment #{index + 1}" for index, label in enumerate(RELATION_LABEL_ORDER)}
    contract = base_contract(
        figure_id="imcr_figure_D_relation_contract_validation",
        analytical_question=(
            "关系契约 changed 集（改后语义）与 control 对照集在独立共识参考下的"
            "标签构成是否不同？完整框架在两组上的准确率是否有差异？"
        ),
        supported_takeaway=(
            "图D 对比 changed/control 两组的共识标签构成，并在存在 09 号基线运行时"
            "给出 B12_full_framework 在两组上的准确率（95% Wilson CI）；"
            "正确性按 apply_imcr_reference 语义在参考覆盖样本上重算。"
        ),
        family="Independent reference validation",
        variant="grouped stacked composition + accuracy errorbar",
        x_axis="样本组（changed / control）",
        y_axis="样本数（左）/ 准确率（右）",
        palette=palette,
        non_color=non_color,
        input_records=input_records,
        outputs=[str(paths["png"].resolve()), str(paths["pdf"].resolve())],
        synthetic=synthetic,
        extra={
            "role_column": "RELATION_CONTRACT_SAMPLE.sample_role",
            "accuracy_definition": "correct = covered AND prediction == reference_label（imcr_all）",
        },
    )
    audit = base_audit(
        figure="imcr_figure_D_relation_contract_validation",
        synthetic=synthetic,
        inputs=inputs,
        checks=checks,
        panels=[
            {
                "panel": "composition",
                "changed": dict(composition["changed"]),
                "control": dict(composition["control"]),
                "unlabeled": unlabeled,
            },
            *( [{"panel": "b12_accuracy", **{role: stats for role, stats in accuracy.items()}}] if accuracy else [] ),
        ],
        excluded=[
            *(group_excluded if not synthetic else []),
            *(
                []
                if (accuracy or synthetic)
                else [{"panel": "b12_accuracy", "reason": "09 号 IMCR_BASELINE_RUNS.csv 不存在或无 B12/relation_contract 行"}]
            ),
        ],
        render={**render, "outputs": {k: str(v.resolve()) for k, v in paths.items()}},
        notes=notes,
    )
    write_json(paths["contract"], contract)
    write_json(paths["audit"], audit)
    print(f"[build_imcr_figures] 图D relation_contract_validation -> {paths['png']}")
    return 0


# ===========================================================================
# CLI
# ===========================================================================


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GOAL.md §三十 新论文图表（图A–图D）渲染管线。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="figure", required=True)

    p_a = sub.add_parser("risk_coverage", help="图A：独立风险—覆盖曲线（small-multiple）")
    p_a.add_argument("--points-dir", type=Path, default=DEFAULT_POINTS_DIR)
    p_a.add_argument("--points-file", type=Path, default=None)
    p_a.add_argument("--methods", nargs="*", default=None, help="只画这些 method_id（默认画数据中出现的全部）")
    p_a.add_argument("--min-task-n", type=int, default=MIN_TASK_N)
    _add_output_args(p_a)

    p_b = sub.add_parser("aurc_augrc_ci", help="图B：ΔAURC/ΔAUGRC 配对比较 95% CI 误差条")
    p_b.add_argument("--stats-dir", type=Path, default=DEFAULT_STATS_DIR)
    p_b.add_argument("--deltas-file", type=Path, default=None)
    p_b.add_argument("--areas-dir", type=Path, default=None, help="13 号 SUMMARY/GOAL13 所在目录（显式提供时启用 AURC/AUGRC 交叉核验）")
    p_b.add_argument("--areas-file", type=Path, default=None)
    _add_output_args(p_b)

    p_c = sub.add_parser("scope_validation", help="图C：208 条 scope adjustments 改前/改后共识校验")
    p_c.add_argument("--reference-csv", type=Path, default=DEFAULT_REFERENCE_CSV)
    p_c.add_argument("--raw-root", type=Path, default=None, help="08 号 raw_runs 目录（可选；提供则画 judge 偏好面板）")
    p_c.add_argument("--payloads-dir", type=Path, default=DEFAULT_PAYLOADS_DIR)
    p_c.add_argument("--manifest-json", type=Path, default=DEFAULT_MANIFEST_JSON)
    _add_output_args(p_c)

    p_d = sub.add_parser("relation_contract_validation", help="图D：关系契约 changed 集共识校验")
    p_d.add_argument("--sample-csv", type=Path, default=DEFAULT_SAMPLE_CSV)
    p_d.add_argument("--reference-csv", type=Path, default=DEFAULT_REFERENCE_CSV)
    p_d.add_argument("--runs-csv", type=Path, default=DEFAULT_RUNS_CSV, help="09 号 IMCR_BASELINE_RUNS.csv（若存在则画 B12 准确率面板）")
    _add_output_args(p_d)

    return parser.parse_args(argv)


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_FIGURES_DIR)
    parser.add_argument("--prefix", default="imcr_")
    parser.add_argument("--synthetic", action="store_true", help="使用固定种子合成演示数据（图面打 SYNTHETIC 水印）")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.figure == "risk_coverage":
        return run_risk_coverage(args)
    if args.figure == "aurc_augrc_ci":
        return run_aurc_augrc_ci(args)
    if args.figure == "scope_validation":
        return run_scope_validation(args)
    if args.figure == "relation_contract_validation":
        return run_relation_contract_validation(args)
    raise ValueError(f"未知子命令: {args.figure}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError) as exc:
        print(f"[build_imcr_figures] 错误: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
