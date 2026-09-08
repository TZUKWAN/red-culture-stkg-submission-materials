# -*- coding: utf-8 -*-
"""build_imcr_consensus_v31.py — v4 重建任务的共识构建（P0-6/7/8）。

与 V3 build_imcr_consensus 同一数学（复用 independent_eval.consensus），面向
v3_1 的三个 v4 任务族：relation_semantic_v2 / scope_revalidation_v2 /
identity_revalidation_v2。

输出（每任务族，写入 experiments/01_reference_rebuild/）：
  {task}/IMCR_V4_{TASK}_STRONG.csv      3/3 强共识（primary 参考）
  {task}/IMCR_V4_{TASK}_ALL.csv         strong+weak
  {task}/JUDGE_PAIRWISE_AGREEMENT.csv   两两一致率 + Cohen κ
  {task}/JUDGE_RELIABILITY_SUMMARY.csv  Fleiss κ / Krippendorff α 等
  {task}/LEAVE_ONE_JUDGE_OUT.csv        逐 judge 剔除稳定性
  {task}/IMCR_V4_{TASK}_LEAVE_B_OUT.csv leave-B-out（B3 同模型独立性对照）
  {task}/IMCR_V4_CONSENSUS_MANIFEST.json

scope_revalidation_v2 的 A_/B_ 标签按 payloads 的 AB_MAPPING 解码回 BEFORE/AFTER。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

V3_1 = Path(__file__).resolve().parents[2]
V3 = V3_1.parent / "final_submission_v3"
for p in (str(V3 / "code"), str(V3 / "code" / "independent_eval"), str(V3 / "code" / "experiment_pipelines")):
    if p not in sys.path:
        sys.path.insert(0, p)

import consensus as consensus_mod  # noqa: E402
from consensus import (  # noqa: E402
    UNRESOLVED,
    aggregate_all,
    build_matrix,
    decode_ab_label,
    load_ab_mapping,
    reliability_summary,
    pairwise_agreement,
    leave_one_judge_out,
    reduced_panel_labels,
)
from manifest import build_manifest, write_manifest, sha256_file  # noqa: E402
from _common import MASTER_SEED  # noqa: E402

RAW_ROOT = V3_1 / "experiments" / "01_reference_rebuild" / "raw_runs"
OUT = V3_1 / "experiments" / "01_reference_rebuild"
PAYLOADS = OUT / "payloads"

V4_TASKS = ["relation_semantic_v2", "scope_revalidation_v2", "identity_revalidation_v2"]

REFERENCE_FIELDS = [
    "task_type", "task_id", "sample_id", "reference_label",
    "imcr_label", "imcr_label_decoded", "consensus_tier",
    "n_valid_votes", "winning_votes", "vote_distribution", "judges", "dry_run",
]
LOQ_FIELDS = REFERENCE_FIELDS + ["judge_removed"]


def build_rows(task_type: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    runs_path = RAW_ROOT / task_type / ""
    recs: list[dict[str, Any]] = []
    for jf in sorted((RAW_ROOT / task_type).glob("*.jsonl")):
        for line in jf.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                r["_file"] = jf.name
                recs.append(r)
    # 复用 V3 的矩阵构建（同一 (task_id, judge) 以最后 OK 为准）
    task_ids, judges, matrix, meta = build_matrix(recs)
    results = aggregate_all(matrix, judges)

    ab_map = {}
    if task_type == "scope_revalidation_v2":
        ab_map = load_ab_mapping(PAYLOADS)

    reference_rows, loq_rows = [], []
    all_model_ids: set[str] = set()
    for m in meta.values():
        all_model_ids.update(v for v in m.get("model_ids", {}).values() if v)

    tier_counts: dict[str, int] = {}
    for tid, res in zip(task_ids, results):
        tier_counts[res.tier] = tier_counts.get(res.tier, 0) + 1
        decoded = decode_ab_label(res.label, ab_map.get(tid)) if task_type == "scope_revalidation_v2" else res.label
        row = {
            "task_type": task_type,
            "task_id": tid,
            "sample_id": tid,
            "reference_label": (decoded if decoded else (res.label or "")),
            "imcr_label": res.label if res.label is not None else "",
            "imcr_label_decoded": decoded if decoded is not None else "",
            "consensus_tier": res.tier,
            "n_valid_votes": res.n_valid_votes,
            "winning_votes": res.winning_votes,
            "vote_distribution": json.dumps({str(k): v for k, v in res.vote_distribution.items()}, ensure_ascii=False, sort_keys=True),
            "judges": ";".join(judges),
            "dry_run": meta[tid].get("dry_run", False),
        }
        if res.tier in ("strong_consensus", "weak_consensus"):
            reference_rows.append(row)
        if res.label is not None:
            loq_rows.append({**row, "consensus_tier": "weak_consensus", "judge_removed": ""})  # 占位，稍后按 judge 填

    return reference_rows, loq_rows, task_ids, {"judges": judges, "matrix": matrix, "meta": meta, "tier_counts": tier_counts, "all_model_ids": all_model_ids, "results": results}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="*", default=V4_TASKS)
    args = ap.parse_args()

    summary_out: dict[str, Any] = {}
    for task_type in args.tasks:
        out_dir = OUT / task_type
        out_dir.mkdir(parents=True, exist_ok=True)
        reference_rows, _loq_rows, task_ids, ctx = build_rows(task_type)
        judges = ctx["judges"]

        pairwise_rows = []
        matrix = ctx["matrix"]
        n = len(judges)
        for i in range(n):
            for j in range(i + 1, n):
                compared = agree = 0
                for row in matrix:
                    a, b = row[i], row[j]
                    if a in consensus_mod.INVALID_VOTES or b in consensus_mod.INVALID_VOTES:
                        continue
                    compared += 1
                    agree += int(a == b)
                kappa = consensus_mod.cohens_kappa(
                    [r[i] for r in matrix], [r[j] for r in matrix]
                )
                pairwise_rows.append(
                    {"task_type": task_type, "judge_a": judges[i], "judge_b": judges[j],
                     "n_compared": compared, "n_agree": agree,
                     "agreement": (agree / compared) if compared else float("nan"),
                     "cohens_kappa": kappa}
                )
        rel = reliability_summary(matrix, judges)
        reliability_rows = [{"task_type": task_type, "metric": k, "value": v} for k, v in rel.items()]
        lojo_rows = [{"task_type": task_type, **r} for r in leave_one_judge_out(matrix, judges)]

        strong_rows = [r for r in reference_rows if r["consensus_tier"] == "strong_consensus"]
        all_rows = [r for r in reference_rows if r["consensus_tier"] in ("strong_consensus", "weak_consensus")]

        def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
            with open(path, "w", encoding="utf-8-sig", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)

        write_csv(out_dir / f"IMCR_V4_{task_type.upper()}_STRONG.csv", strong_rows, REFERENCE_FIELDS)
        write_csv(out_dir / f"IMCR_V4_{task_type.upper()}_ALL.csv", all_rows, REFERENCE_FIELDS)
        write_csv(out_dir / f"JUDGE_PAIRWISE_AGREEMENT_{task_type}.csv", pairwise_rows,
                  ["task_type", "judge_a", "judge_b", "n_compared", "n_agree", "agreement", "cohens_kappa"])
        write_csv(out_dir / f"JUDGE_RELIABILITY_SUMMARY_{task_type}.csv", reliability_rows,
                  ["task_type", "metric", "value"])
        write_csv(out_dir / f"LEAVE_ONE_JUDGE_OUT_{task_type}.csv", lojo_rows,
                  ["task_type", "judge_removed", "n_tasks", "n_labeled_full_panel", "n_unchanged_after_removal", "stability"])

        # leave-one-out 参考（对称三份；B3=gpt-5.6-luna 主对照为 LEAVE_B）
        loq_files: list[Path] = []
        loq_counts: dict[str, int] = {}
        ab_map = load_ab_mapping(PAYLOADS) if task_type == "scope_revalidation_v2" else {}
        for drop in judges:
            reduced = reduced_panel_labels(matrix, judges, drop)
            remaining = [j for j in judges if j != drop]
            rows: list[dict[str, Any]] = []
            for tid, res in zip(task_ids, reduced):
                if res.label is None:
                    continue
                decoded = decode_ab_label(res.label, ab_map.get(tid)) if task_type == "scope_revalidation_v2" else res.label
                rows.append({
                    "task_type": task_type, "task_id": tid, "sample_id": tid,
                    "reference_label": (decoded if decoded else (res.label or "")),
                    "imcr_label": res.label,
                    "imcr_label_decoded": decoded if decoded is not None else "",
                    "consensus_tier": res.tier,
                    "n_valid_votes": res.n_valid_votes,
                    "winning_votes": res.winning_votes,
                    "vote_distribution": json.dumps({str(k): v for k, v in res.vote_distribution.items()}, ensure_ascii=False, sort_keys=True),
                    "judges": ";".join(remaining),
                    "judge_removed": drop,
                    "dry_run": False,
                })
            f = out_dir / f"IMCR_V4_{task_type.upper()}_LEAVE_{drop}_OUT.csv"
            write_csv(f, rows, LOQ_FIELDS)
            loq_files.append(f)
            loq_counts[f.name] = len(rows)

        manifest = build_manifest(
            f"imcr_v4_consensus_{task_type}",
            prompt_sha256="UNAVAILABLE",
            model_ids=sorted(ctx["all_model_ids"]),
            seed=MASTER_SEED,
            repo_dir=str(V3_1),
            extra={
                "judges": judges,
                "tier_counts": ctx["tier_counts"],
                "n_strong": len(strong_rows),
                "n_all": len(all_rows),
                "n_leave_one_out": loq_counts,
                "raw_run_files": sorted(p.name for p in (RAW_ROOT / task_type).glob("*.jsonl")),
            },
        )
        write_manifest(manifest, out_dir / f"IMCR_V4_CONSENSUS_MANIFEST_{task_type}.json")
        summary_out[task_type] = {"tiers": ctx["tier_counts"], "strong": len(strong_rows), "all": len(all_rows)}
        print(f"[consensus_v31] {task_type}: tiers={ctx['tier_counts']} strong={len(strong_rows)} all={len(all_rows)}")

    (OUT / "V4_CONSENSUS_SUMMARY.json").write_text(
        json.dumps(summary_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
