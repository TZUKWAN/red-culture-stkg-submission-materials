# -*- coding: utf-8 -*-
"""selective_stats.py — P0-3：选择性预测的修复版统计口径。

修复项（相对 V3 run_statistical_tests 的口径）：
* McNemar 只在双方**共同 accepted** 的样本上比较正确性（弃权样本的潜在预测
  不再被当作已发布预测），并必须报告 n_shared_accepted / coverage_A / coverage_B。
* 新增 Risk@Coverage（在固定覆盖率上限下比较 selective risk）与
  Coverage@Risk（在固定 selective risk 上限下比较 coverage）。
* matched-coverage 比较：两条 risk-coverage 曲线在公共覆盖网格上的
  paired risk difference（共享重采样索引）。

所有函数只依赖逐样本行：
    row = {sample_id, accepted(0/1), correct(0/1), score(float|None), gate(0/1)}
`accepted` = 该系统真实接受并发布了预测；`correct` 仅当 accepted 且预测等于参考时为 1；
弃权行 correct 恒为 0 且 accepted=0（其预测不得参与任何已发布正确性统计）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

Row = Mapping[str, Any]

__all__ = [
    "rows_to_points",
    "risk_at_coverage",
    "coverage_at_risk",
    "mcnemar_on_jointly_accepted",
    "matched_coverage_risk_difference",
    "risk_coverage_curve_from_rows",
]


def _as_int(v: Any) -> int:
    return int(v)


def rows_to_points(rows: Sequence[Row]) -> list[dict[str, float]]:
    """逐样本行 → 阈值扫描点（按 score 降序接受；无 score 的行只在 coverage=0 出现）。

    曲线语义与 V3 一致：score>=θ 且 accepted 才计入；denominator=全部样本。
    """
    scored = sorted(
        (
            (float(r["score"]), _as_int(r["correct"]))
            for r in rows
            if _as_int(r["accepted"]) == 1 and r.get("score") is not None
        ),
        key=lambda t: (-t[0], t[1]),
    )
    total = len(rows)
    points: list[dict[str, float]] = [
        {"threshold": math.inf, "coverage": 0.0, "n_accepted": 0, "errors": 0, "selective_risk": 0.0}
    ]
    for idx, (score, correct) in enumerate(scored, start=1):
        errors_prev = points[-1]["errors"] + (1 - correct)
        points.append(
            {
                "threshold": score,
                "coverage": idx / total,
                "n_accepted": idx,
                "errors": errors_prev,
                "selective_risk": errors_prev / idx,
            }
        )
    return points


def risk_coverage_curve_from_rows(rows: Sequence[Row]) -> list[dict[str, float]]:
    return rows_to_points(rows)


def _risk_at(points: list[dict[str, float]], coverage: float) -> float:
    """coverage<=c 的最小 selective risk（曲线随 coverage 增大风险单调不增时即曲线在 c 处的风险）。"""
    best = math.inf
    for p in points:
        if p["coverage"] <= coverage + 1e-12:
            best = min(best, p["selective_risk"])
    return best


def risk_at_coverage(points: list[dict[str, float]], targets: Sequence[float] = (0.1, 0.2, 0.3, 0.5)) -> dict[str, float | None]:
    """Risk@Coverage：coverage ≤ c 时可达到的最小 selective risk；不可达返回 None。"""
    out: dict[str, float | None] = {}
    for c in targets:
        risks = [p["selective_risk"] for p in points if p["coverage"] <= c + 1e-12]
        out[f"risk@{c:.0%}"] = min(risks) if risks else None
    return out


def coverage_at_risk(points: list[dict[str, float]], limits: Sequence[float] = (0.01, 0.05, 0.10)) -> dict[str, float | None]:
    """Coverage@Risk：selective risk ≤ r 时可达到的最大 coverage；不可达返回 None。"""
    out: dict[str, float | None] = {}
    for r in limits:
        covs = [p["coverage"] for p in points if p["selective_risk"] <= r + 1e-12]
        out[f"coverage@risk<={r:.0%}"] = max(covs) if covs else None
    return out


def mcnemar_on_jointly_accepted(
    rows_a: Sequence[Row],
    rows_b: Sequence[Row],
    *,
    system_a_name: str = "A",
    system_b_name: str = "B",
) -> dict[str, Any]:
    """修正版 McNemar：只在两系统**共同 accepted** 的样本上比较 correctness。

    返回 n_shared_accepted、双方各自 coverage、b/c（A 对 B 错）、精确二项 p 值。
    弃权样本不贡献 b/c。若 n_discordant==0，p=1.0（约定），仍落一行。
    """
    idx_a = {str(r["sample_id"]): r for r in rows_a}
    idx_b = {str(r["sample_id"]): r for r in rows_b}
    shared = [k for k in idx_a if k in idx_b]
    joint = [
        k
        for k in shared
        if _as_int(idx_a[k]["accepted"]) == 1 and _as_int(idx_b[k]["accepted"]) == 1
    ]
    b = c = 0
    for k in joint:
        ca, cb = _as_int(idx_a[k]["correct"]), _as_int(idx_b[k]["correct"])
        if ca and not cb:
            b += 1
        elif cb and not ca:
            c += 1
    n_disc = b + c
    p = _binom_twosided(b, c)
    return {
        "comparison": f"{system_a_name}_vs_{system_b_name}",
        "n_shared_accepted": len(joint),
        "n_shared_total": len(shared),
        "coverage_a": len([r for r in rows_a if _as_int(r["accepted"]) == 1]) / len(rows_a) if rows_a else 0.0,
        "coverage_b": len([r for r in rows_b if _as_int(r["accepted"]) == 1]) / len(rows_b) if rows_b else 0.0,
        "b_a_correct_b_wrong": b,
        "c_a_wrong_b_correct": c,
        "n_discordant": n_disc,
        "statistic": float(min(b, c)),
        "p_value": p,
        "method": "mcnemar_exact_on_jointly_accepted",
    }


def _binom_twosided(b: int, c: int) -> float:
    """精确二项双侧 p：2*P(X<=min(b,c)), X~Bin(b+c, 0.5)；b+c=0 → 1.0。"""
    if b + c == 0:
        return 1.0
    n, k = b + c, min(b, c)
    total = 2**n
    cum = 0
    for i in range(0, k + 1):
        cum += math.comb(n, i)
    p = 2 * cum / total
    return min(1.0, p)


def matched_coverage_risk_difference(
    rows_a: Sequence[Row],
    rows_b: Sequence[Row],
    *,
    grid: Sequence[float] | None = None,
    n_bootstrap: int = 2000,
    seed: int = 20260908,
) -> dict[str, Any]:
    """matched-coverage 配对比较：公共覆盖网格上 (risk_b - risk_a) 的逐点差 + paired bootstrap CI。

    共享重采样索引：每个 replicate 对同一批样本重采样一次，同时重算两系统曲线。
    返回逐网格点的均值差与 95% percentile CI，以及面积型汇总（网格上差的均值）。
    """
    if grid is None:
        grid = [round(0.05 * i, 2) for i in range(1, 21)]  # 0.05..1.00
    total = len(rows_a)
    if len(rows_b) != total:
        raise ValueError("matched comparison requires identical sample sets")
    idx_a = {str(r["sample_id"]): r for r in rows_a}
    idx_b = {str(r["sample_id"]): r for r in rows_b}
    keys = [str(r["sample_id"]) for r in rows_a]

    def curve(indices: Sequence[int], side: str) -> dict[float, float]:
        rows = []
        for i in indices:
            r = (idx_a if side == "a" else idx_b)[keys[i]]
            rows.append(r)
        pts = rows_to_points(rows)
        out = {}
        for c in grid:
            out[c] = _risk_at(pts, c)
        return out

    point_est = curve(range(total), "a")
    point_est_b = curve(range(total), "b")
    import random

    rng = random.Random(seed)
    reps: list[dict[float, float]] = []
    for _ in range(n_bootstrap):
        idxs = [rng.randrange(total) for _ in range(total)]
        ca = curve(idxs, "a")
        cb = curve(idxs, "b")
        reps.append({c: cb[c] - ca[c] for c in grid})
    per_grid: dict[str, dict[str, float]] = {}
    for c in grid:
        diffs = sorted(r[c] for r in reps if not math.isnan(r[c]))
        valid = [d for d in diffs if not math.isnan(d)]
        mean = sum(valid) / len(valid) if valid else math.nan
        lo = valid[int(0.025 * len(valid))] if valid else math.nan
        hi = valid[min(len(valid) - 1, int(0.975 * len(valid)))] if valid else math.nan
        per_grid[f"cov_{c:.2f}"] = {
            "mean_diff_b_minus_a": mean,
            "ci95_low": lo,
            "ci95_high": hi,
        }
    return {
        "grid": list(grid),
        "risk_a_full": point_est,
        "risk_b_full": point_est_b,
        "diff_b_minus_a_point": {c: point_est_b[c] - point_est[c] for c in grid},
        "bootstrap_mean_diff_b_minus_a": {c: per_grid[f"cov_{c:.2f}"]["mean_diff_b_minus_a"] for c in grid},
        "bootstrap_ci95": per_grid,
        "n_bootstrap": n_bootstrap,
        "seed": seed,
        "note": "positive diff = A has smaller risk at that coverage (A better)",
    }
