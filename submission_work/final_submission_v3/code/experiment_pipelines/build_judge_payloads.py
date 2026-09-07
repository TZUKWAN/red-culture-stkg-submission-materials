# -*- coding: utf-8 -*-
"""build_judge_payloads.py — 把 5 类 IMCR 样本统一转成盲化 judge payload JSONL。

用法（默认路径即 v3 标准布局，无需参数）：

    python build_judge_payloads.py [--tasks entity_type ...] [--out-dir PATH]

行为：
* 读取 5 类既有样本（只读，不修改任何已有文件）；
* 逐条调用 independent_eval.blind_payload.build_blind_payload：
  - 白名单字段之外的任何生产字段一律不进入 payload；
  - 黑名单键/值（ERA 标签、prediction、risk_tier、semantic_status 等）一旦
    出现即抛 LeakageError，整个构建立即失败——绝不静默放行；
  - scope_adjustment 的 before/after 经 (seed, task_id) 确定性随机化为 a/b，
    映射写入独立 CSV（payload 内零 before/after 字样）；
* 每个任务类型输出一个 JSONL：每行
  {task_id, task_type, prompt_version, allowed_labels, prompt_sha256, payload}；
* 输出 PAYLOAD_BUILD_MANIFEST.json：每文件的行数、prompt_sha256、payload 文件
  与输入文件的 sha256、种子、code commit、时间戳（GOAL 21）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

CODE_DIR = Path(__file__).resolve().parents[1]
for _p in (str(CODE_DIR), str(CODE_DIR / "independent_eval"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from blind_payload import (  # noqa: E402
    build_blind_payload,
    prompt_sha256,
    write_ab_mapping,
)
from manifest import build_manifest, sha256_file, write_manifest  # noqa: E402
from _common import MASTER_SEED  # noqa: E402

import imcr_task_defs as defs  # noqa: E402


def build_task_payloads(task_type: str, out_dir: Path) -> dict[str, Any]:
    """构建一个任务类型的全部 payload，返回该文件的清单条目。"""
    spec = defs.PIPELINE_TASK_SPECS[task_type]
    reg = defs.TASK_REGISTRY[task_type]
    input_path: Path = reg["input"]
    template = defs.PROMPT_TEMPLATES[task_type]
    template_sha = prompt_sha256(template)
    seed = defs.task_seed(task_type)

    evidence_by_fact = None
    if task_type == "relation_contract":
        evidence_by_fact = defs.load_evidence_by_fact()

    ab_rows: list[dict[str, Any]] = []
    if task_type == "scope_adjustment":
        ab_rows = defs.read_csv_rows(reg["ab_mapping_input"])
        ab_mapping = {r["task_id"]: r for r in ab_rows}

    if reg["kind"] == "csv":
        raw_rows: list[Any] = defs.read_csv_rows(input_path)
    else:
        raw_rows = defs.read_jsonl(input_path)

    lines: list[str] = []
    ab_records: list[dict[str, Any]] = []
    n_with_evidence = 0
    for raw in raw_rows:
        if task_type == "entity_type":
            record = defs.entity_type_record(raw)
        elif task_type == "relation_contract":
            record = defs.relation_contract_record(raw, evidence_by_fact)
        elif task_type == "scope_adjustment":
            record = defs.scope_adjustment_record(raw, ab_mapping)
        elif task_type == "identity_pair":
            record = defs.identity_pair_record(raw)
        elif task_type == "provenance_support":
            record = defs.provenance_support_record(raw)
        else:  # pragma: no cover - 注册表守卫
            raise ValueError(f"unknown task type: {task_type}")

        # build_blind_payload 内部执行白名单过滤 + 黑名单深扫描；
        # 任何泄漏都会抛 LeakageError 并中止整个构建。
        payload, meta = build_blind_payload(
            record, spec, seed=seed, prompt_template=template
        )
        if record.get("evidence_excerpts"):
            n_with_evidence += 1
        line = {
            "task_id": meta["task_id"],
            "task_type": task_type,
            "prompt_version": meta["prompt_version"],
            "allowed_labels": meta["allowed_labels"],
            "prompt_sha256": template_sha,
            "payload": payload,
        }
        lines.append(json.dumps(line, ensure_ascii=False, sort_keys=True))
        if "ab_mapping" in meta:
            ab_records.append(
                {
                    "task_id": meta["task_id"],
                    "a": meta["ab_mapping"]["a"],
                    "b": meta["ab_mapping"]["b"],
                    "seed": seed,
                }
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / reg["output"]
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + ("\n" if lines else ""))

    ab_mapping_path = None
    if ab_records:
        ab_mapping_path = out_dir / reg["ab_mapping_output"]
        write_ab_mapping(ab_records, str(ab_mapping_path))

    entry: dict[str, Any] = {
        "task_type": task_type,
        "input_file": str(input_path),
        "input_sha256": sha256_file(input_path),
        "payload_file": str(out_path),
        "payload_sha256": sha256_file(out_path),
        "rows": len(lines),
        "n_with_evidence_excerpts": n_with_evidence,
        "prompt_version": spec.prompt_version,
        "prompt_sha256": template_sha,
        "allowed_labels": list(spec.allowed_labels),
        "seed": seed,
        "ab_mapping_file": str(ab_mapping_path) if ab_mapping_path else None,
        "ab_mapping_sha256": (
            sha256_file(ab_mapping_path) if ab_mapping_path else None
        ),
    }
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tasks",
        nargs="*",
        default=list(defs.ALL_TASK_TYPES),
        choices=list(defs.ALL_TASK_TYPES),
        help="只构建指定任务类型（默认全部 5 类）",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=defs.EXP08 / "payloads",
        help="payload 输出目录（默认 experiments/08_independent_reference/payloads/）",
    )
    args = parser.parse_args(argv)

    entries = [build_task_payloads(t, args.out_dir) for t in args.tasks]

    combined_prompt_sha = prompt_sha256(
        json.dumps(
            {e["task_type"]: e["prompt_sha256"] for e in entries},
            sort_keys=True,
        )
    )
    manifest = build_manifest(
        "imcr_payload_build",
        prompt_sha256=combined_prompt_sha,
        model_ids=[],
        seed=MASTER_SEED,
        repo_dir=CODE_DIR.parents[1],
        extra={
            "description": "IMCR 盲化 judge payload 构建清单（GOAL 7.1/7.3/21）",
            "dry_run": False,
            "tasks": entries,
            "total_rows": sum(e["rows"] for e in entries),
        },
    )
    manifest_path = write_manifest(manifest, args.out_dir / "PAYLOAD_BUILD_MANIFEST.json")

    print(f"[build_judge_payloads] manifest: {manifest_path}")
    for e in entries:
        print(
            f"  {e['task_type']:<20} rows={e['rows']:<5} "
            f"prompt_sha256={e['prompt_sha256'][:16]}… -> {e['payload_file']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
