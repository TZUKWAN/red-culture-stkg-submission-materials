# -*- coding: utf-8 -*-
"""build_imcr_consensus.py — 聚合 judge 原始记录，形成 IMCR 共识参考集。

用法：

    python build_imcr_consensus.py \
        --raw-root experiments/08_independent_reference/raw_runs \
        --out-dir  experiments/08_independent_reference \
        --payloads-dir experiments/08_independent_reference/payloads

行为（GOAL 7.4 / 7.5 / 21）：
* 读取 {raw_root}/{task_type}/{judge}.jsonl，拼成 任务 × judge 决策矩阵；
  非法/缺失输出记为无效票，绝不用无效票参与多数决。
* 共识规则：3 judge——3/3 strong、2/3 weak、其余 unresolved；
  5 judge——≥4/5 strong、3/5 weak、其余 unresolved。
  unresolved 不生成任何标签（不强制多数票伪造参考标签）。
* 输出：
  - IMCR_REFERENCE_STRONG.csv  仅 strong_consensus（Primary 评价基准）
  - IMCR_REFERENCE_ALL.csv     strong + weak（Secondary 评价基准）
  - JUDGE_PAIRWISE_AGREEMENT.csv（含 Cohen's kappa）
  - JUDGE_RELIABILITY_SUMMARY.csv（Fleiss' kappa / Krippendorff's alpha 等）
  - LEAVE_ONE_JUDGE_OUT.csv
  - IMCR_CONSENSUS_MANIFEST.json
* scope_adjustment 的 A_/B_ 标签依据 payloads 目录下的 A/B 映射 CSV
  解码回 BEFORE_/AFTER_ 语义（imcr_label_decoded 列）。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

CODE_DIR = Path(__file__).resolve().parents[1]
for _p in (str(CODE_DIR), str(CODE_DIR / "independent_eval"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import consensus as consensus_mod  # noqa: E402
from consensus import (  # noqa: E402
    STRONG_CONSENSUS,
    UNRESOLVED,
    WEAK_CONSENSUS,
    aggregate_all,
    cohens_kappa,
    leave_one_judge_out,
    pairwise_agreement,
)
from manifest import build_manifest, sha256_file, write_manifest  # noqa: E402
from _common import MASTER_SEED  # noqa: E402

import imcr_task_defs as defs  # noqa: E402

DEFAULT_RAW_ROOT = defs.EXP08 / "raw_runs"
DEFAULT_OUT_DIR = defs.EXP08
DEFAULT_PAYLOADS_DIR = defs.EXP08 / "payloads"

REFERENCE_FIELDS = [
    "task_type",
    "task_id",
    "imcr_label",
    "imcr_label_decoded",
    "consensus_tier",
    "n_valid_votes",
    "winning_votes",
    "vote_distribution",
    "judges",
    "dry_run",
]


# ---------------------------------------------------------------------------
# raw_runs 读取
# ---------------------------------------------------------------------------


def load_raw_runs(raw_root: Path, task_type: str) -> dict[str, dict[str, dict[str, Any]]]:
    """{judge_name: {task_id: record}}；judge 按文件名（字母序）排列。"""
    task_dir = raw_root / task_type
    out: dict[str, dict[str, dict[str, Any]]] = {}
    if not task_dir.is_dir():
        return out
    for path in sorted(task_dir.glob("*.jsonl")):
        judge = path.stem
        records: dict[str, dict[str, Any]] = {}
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                tid = str(rec.get("task_id"))
                # 同一 task_id 多条记录时取最后一条（与 --resume 语义一致：
                # 已成功任务不会重跑，重复只会来自显式 overwrite 前的历史）
                if tid not in records or rec.get("status") == "OK":
                    records[tid] = rec
        out[judge] = records
    return out


def build_matrix(
    runs: dict[str, dict[str, dict[str, Any]]]
) -> tuple[list[str], list[str], list[list[Any]], dict[str, Any]]:
    """返回 (task_ids, judges, matrix, per_task_meta)。"""
    judges = sorted(runs.keys())
    task_ids = sorted({tid for recs in runs.values() for tid in recs})
    matrix: list[list[Any]] = []
    meta: dict[str, Any] = {}
    for tid in task_ids:
        row: list[Any] = []
        for judge in judges:
            rec = runs[judge].get(tid)
            if rec is None or rec.get("status") != "OK" or not rec.get("parsed_response"):
                row.append(None)
                continue
            row.append(rec["parsed_response"].get("decision"))
        matrix.append(row)
        meta[tid] = {
            "dry_run": any(
                (runs[j].get(tid) or {}).get("dry_run") for j in judges
            ),
            "model_ids": {
                j: (runs[j].get(tid) or {}).get("model_id") for j in judges
            },
        }
    return task_ids, judges, matrix, meta


# ---------------------------------------------------------------------------
# A/B 标签解码
# ---------------------------------------------------------------------------


def load_ab_mapping(payloads_dir: Path) -> dict[str, dict[str, str]]:
    path = payloads_dir / defs.TASK_REGISTRY["scope_adjustment"]["ab_mapping_output"]
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return {r["task_id"]: {"a": r["a"], "b": r["b"]} for r in csv.DictReader(fh)}


def decode_ab_label(label: Any, mapping: dict[str, str] | None) -> Any:
    """把 A_BETTER/B_BETTER 解码为 BEFORE_BETTER/AFTER_BETTER。"""
    if label not in ("A_BETTER", "B_BETTER") or not mapping:
        return label
    shown = "a" if label == "A_BETTER" else "b"
    return "BEFORE_BETTER" if mapping.get(shown) == "before" else "AFTER_BETTER"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def _fmt(value: Any) -> Any:
    if isinstance(value, float) and math.isnan(value):
        return "NaN"
    return value


def run(raw_root: Path, out_dir: Path, payloads_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ab_mapping = load_ab_mapping(payloads_dir)

    reference_rows: list[dict[str, Any]] = []
    pairwise_rows: list[dict[str, Any]] = []
    reliability_rows: list[dict[str, Any]] = []
    loo_rows: list[dict[str, Any]] = []
    manifest_tasks: list[dict[str, Any]] = []
    all_model_ids: set[str] = set()

    for task_type in defs.ALL_TASK_TYPES:
        runs = load_raw_runs(raw_root, task_type)
        if not runs:
            continue
        task_ids, judges, matrix, meta = build_matrix(runs)
        if len(judges) not in (3, 5):
            raise ValueError(
                f"任务 {task_type} 有 {len(judges)} 个 judge（{judges}）；"
                "GOAL 7.4 共识规则只定义了 3 或 5 个 judge 的档位"
            )
        results = aggregate_all(matrix, judges)
        for m in meta.values():
            all_model_ids.update(mid for mid in m["model_ids"].values() if mid)

        tier_counts: Counter[str] = Counter()
        for tid, res in zip(task_ids, results):
            tier_counts[res.tier] += 1
            decoded = (
                decode_ab_label(res.label, ab_mapping.get(tid))
                if task_type == "scope_adjustment"
                else res.label
            )
            reference_rows.append(
                {
                    "task_type": task_type,
                    "task_id": tid,
                    "imcr_label": res.label if res.label is not None else "",
                    "imcr_label_decoded": decoded if decoded is not None else "",
                    "consensus_tier": res.tier,
                    "n_valid_votes": res.n_valid_votes,
                    "winning_votes": res.winning_votes,
                    "vote_distribution": json.dumps(
                        {str(k): v for k, v in res.vote_distribution.items()},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "judges": ";".join(judges),
                    "dry_run": meta[tid]["dry_run"],
                }
            )

        # 一致性统计（复用 independent_eval.consensus，不重写指标）
        for pair in pairwise_agreement(matrix, judges):
            i, j = judges.index(pair["judge_a"]), judges.index(pair["judge_b"])
            paired_a = [
                row[i]
                for row in matrix
                if row[i] not in consensus_mod.INVALID_VOTES
                and row[j] not in consensus_mod.INVALID_VOTES
            ]
            paired_b = [
                row[j]
                for row in matrix
                if row[i] not in consensus_mod.INVALID_VOTES
                and row[j] not in consensus_mod.INVALID_VOTES
            ]
            kappa = cohens_kappa(paired_a, paired_b) if paired_a else math.nan
            pairwise_rows.append({"task_type": task_type, **pair, "cohens_kappa": _fmt(kappa)})

        summary = consensus_mod.reliability_summary(matrix, judges)
        for key, value in summary.items():
            if key == "judges":
                value = ";".join(value)
            reliability_rows.append(
                {"task_type": task_type, "metric": key, "value": _fmt(value)}
            )

        for row in leave_one_judge_out(matrix, judges):
            loo_rows.append({"task_type": task_type, **{k: _fmt(v) for k, v in row.items()}})

        manifest_tasks.append(
            {
                "task_type": task_type,
                "n_tasks": len(task_ids),
                "judges": judges,
                "n_strong_consensus": tier_counts[STRONG_CONSENSUS],
                "n_weak_consensus": tier_counts[WEAK_CONSENSUS],
                "n_unresolved": tier_counts[UNRESOLVED],
            }
        )

    if not manifest_tasks:
        raise FileNotFoundError(f"在 {raw_root} 下未找到任何 raw_runs 记录")

    # IMCR 参考集：STRONG 只含 strong；ALL 含 strong + weak（GOAL 7.4 Primary/Secondary）
    strong_rows = [r for r in reference_rows if r["consensus_tier"] == STRONG_CONSENSUS]
    all_rows = [
        r
        for r in reference_rows
        if r["consensus_tier"] in (STRONG_CONSENSUS, WEAK_CONSENSUS)
    ]

    def _write(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    strong_path = out_dir / "IMCR_REFERENCE_STRONG.csv"
    all_path = out_dir / "IMCR_REFERENCE_ALL.csv"
    pair_path = out_dir / "JUDGE_PAIRWISE_AGREEMENT.csv"
    rel_path = out_dir / "JUDGE_RELIABILITY_SUMMARY.csv"
    loo_path = out_dir / "LEAVE_ONE_JUDGE_OUT.csv"
    _write(strong_path, strong_rows, REFERENCE_FIELDS)
    _write(all_path, all_rows, REFERENCE_FIELDS)
    _write(
        pair_path,
        pairwise_rows,
        ["task_type", "judge_a", "judge_b", "n_compared", "n_agree", "agreement", "cohens_kappa"],
    )
    _write(rel_path, reliability_rows, ["task_type", "metric", "value"])
    _write(
        loo_path,
        loo_rows,
        [
            "task_type",
            "judge_removed",
            "n_tasks",
            "n_labeled_full_panel",
            "n_unchanged_after_removal",
            "stability",
        ],
    )

    dry_run_flag = any(r["dry_run"] for r in reference_rows)
    manifest = build_manifest(
        "imcr_consensus_build",
        prompt_sha256="UNAVAILABLE",
        model_ids=sorted(all_model_ids),
        seed=MASTER_SEED,
        repo_dir=CODE_DIR.parents[1],
        extra={
            "description": (
                "IMCR 共识参考集构建清单（GOAL 7.4/7.5/21）"
                + ("；DRY_RUN 演练输出，不得用于论文" if dry_run_flag else "")
            ),
            "dry_run": dry_run_flag,
            "raw_root": str(raw_root),
            "tasks": manifest_tasks,
            "output_files": {
                p.name: sha256_file(p)
                for p in (strong_path, all_path, pair_path, rel_path, loo_path)
            },
            "n_reference_strong": len(strong_rows),
            "n_reference_all": len(all_rows),
        },
    )
    manifest_path = write_manifest(manifest, out_dir / "IMCR_CONSENSUS_MANIFEST.json")

    print(f"[build_imcr_consensus] manifest: {manifest_path}")
    for t in manifest_tasks:
        print(
            f"  {t['task_type']:<20} n={t['n_tasks']:<5} "
            f"strong={t['n_strong_consensus']} weak={t['n_weak_consensus']} "
            f"unresolved={t['n_unresolved']} judges={','.join(t['judges'])}"
        )
    print(f"  IMCR_REFERENCE_STRONG.csv rows={len(strong_rows)}")
    print(f"  IMCR_REFERENCE_ALL.csv    rows={len(all_rows)}")
    return {"tasks": manifest_tasks, "n_strong": len(strong_rows), "n_all": len(all_rows)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--payloads-dir", type=Path, default=DEFAULT_PAYLOADS_DIR)
    args = parser.parse_args(argv)
    run(args.raw_root, args.out_dir, args.payloads_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
