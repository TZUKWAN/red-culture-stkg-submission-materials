# -*- coding: utf-8 -*-
"""run_judges.py — 对盲化 payload 逐任务调用 IMCR judge 模型并落盘原始记录。

用法：

    # 真实运行（judge 配置来自环境变量 JUDGE_{A..E}_BASE_URL/API_KEY/MODEL）
    python run_judges.py

    # 离线演练（确定性假响应，不联网；默认 3 个假 judge A/B/C）
    python run_judges.py --dry-run --limit 12 \
        --out-root experiments/08_independent_reference/dry_run

    # 断点续跑：跳过已有 status==OK 的 task_id
    python run_judges.py --resume

行为契约：
* judge 发现：非 dry-run 时扫描 JUDGE_A..E 环境变量，三个变量齐全才算
  配置完成；一个都未配置时明确报错并指向 .env.example（GOAL 19）。
* 每个 (task_type, judge) 的原始调用记录追加写入
  {out_root}/raw_runs/{task_type}/{judge}.jsonl，每行含 GOAL 19 节 11 项
  字段 + task_type/prompt_sha256/dry_run 标记；API key 永不落盘。
* 输出 JSON 经 judge_client.validate_judge_output 校验，非法输出有界重试，
  达到上限标记 MODEL_OUTPUT_INVALID，绝不手工改答案（GOAL 20）。
* 安全默认：输出文件已存在且未给 --resume/--overwrite 时拒绝运行，
  防止误覆盖真实 judge 记录。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

CODE_DIR = Path(__file__).resolve().parents[1]
for _p in (str(CODE_DIR), str(CODE_DIR / "independent_eval"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from judge_client import (  # noqa: E402
    JUDGE_NAMES,
    JudgeClient,
    JudgeClientError,
    JudgeConfig,
    load_judge_config,
)
from _common import MASTER_SEED, derive_seed  # noqa: E402

import imcr_task_defs as defs  # noqa: E402

DEFAULT_OUT_ROOT = defs.EXP08
DEFAULT_PAYLOADS_DIR = defs.EXP08 / "payloads"

ENV_EXAMPLE_HINT = (
    "未配置任何 judge。请先复制 .env.example 为 .env 并填写 "
    "JUDGE_{A..E}_BASE_URL / JUDGE_{A..E}_API_KEY / JUDGE_{A..E}_MODEL，"
    "再通过环境变量载入（set / export）；或使用 --dry-run 做离线演练。"
)


# ---------------------------------------------------------------------------
# judge 发现与 dry-run 假响应
# ---------------------------------------------------------------------------


def discover_judges(
    dry_run: bool, judge_names: Sequence[str] | None
) -> list[JudgeConfig]:
    """返回本次启用的 judge 配置列表。

    dry-run 模式下生成合成配置（不联网）；真实模式从环境变量发现，
    一个都未配置时抛 JudgeClientError 并提示 .env.example。
    """
    if dry_run:
        names = list(judge_names) if judge_names else ["A", "B", "C"]
        return [
            JudgeConfig(
                name=n.upper(),
                base_url="http://dry-run.local/v1",
                api_key="dry-run-placeholder",  # 仅内存占位，永不落盘
                model=f"dry-run-model-{n.lower()}",
            )
            for n in names
        ]
    configs: list[JudgeConfig] = []
    for name in JUDGE_NAMES:
        if judge_names and name not in [j.upper() for j in judge_names]:
            continue
        try:
            configs.append(load_judge_config(name))
        except JudgeClientError:
            continue  # 该 judge 未配置，跳过
    if not configs:
        raise JudgeClientError(ENV_EXAMPLE_HINT)
    return configs


def make_dry_run_responder(model_id: str):
    """确定性假响应：标签由 sha256(model_id + task_id) 决定。

    与 judge_client 默认假响应（只哈希 task_id）不同，这里把模型 ID 混入
    哈希，使不同假 judge 产生可复现的分歧，从而能演练 weak/unresolved
    共识档位。
    """

    def responder(task_id: str, allowed_labels: Sequence[str]) -> Mapping[str, Any]:
        labels = list(allowed_labels)
        digest = hashlib.sha256(f"{model_id}::{task_id}".encode("utf-8")).digest()
        label = labels[digest[0] % len(labels)]
        return {
            "task_id": task_id,
            "decision": label,
            "confidence": round(0.5 + (digest[1] % 50) / 100.0, 4),
            "evidence": [f"dry-run evidence from {model_id} for {task_id}"],
            "reason_code": "DRY_RUN",
            "explanation": "确定性离线占位响应（DRY_RUN，非真实模型输出）。",
            "insufficient_evidence": label == "insufficient_evidence"
            or label == "INSUFFICIENT_EVIDENCE",
        }

    return responder


# ---------------------------------------------------------------------------
# payload 读取与续跑
# ---------------------------------------------------------------------------


def load_payload_file(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_completed_task_ids(path: Path) -> set[str]:
    """--resume：收集已有记录中 status==OK 的 task_id。"""
    done: set[str] = set()
    if not path.exists():
        return done
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("status") == "OK":
                done.add(str(rec.get("task_id")))
    return done


def build_messages(template: str, payload: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": template},
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        },
    ]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run(
    payloads_dir: Path,
    out_root: Path,
    *,
    dry_run: bool,
    judge_names: Sequence[str] | None,
    limit: int | None,
    resume: bool,
    overwrite: bool,
    tasks: Sequence[str],
    temperature: float,
    top_p: float,
) -> dict[str, Any]:
    configs = discover_judges(dry_run, judge_names)
    call_seed = derive_seed("imcr_judge_calls", MASTER_SEED)
    summary: dict[str, Any] = {"judges": [c.to_safe_dict() for c in configs], "tasks": {}}

    for task_type in tasks:
        reg = defs.TASK_REGISTRY[task_type]
        payload_path = payloads_dir / reg["output"]
        if not payload_path.exists():
            raise FileNotFoundError(
                f"payload 文件不存在：{payload_path}；请先运行 build_judge_payloads.py"
            )
        rows = load_payload_file(payload_path)
        if limit is not None:
            rows = rows[:limit]
        template = defs.PROMPT_TEMPLATES[task_type]

        for cfg in configs:
            raw_path = out_root / "raw_runs" / task_type / f"{cfg.name}.jsonl"
            if raw_path.exists() and not (resume or overwrite):
                raise FileExistsError(
                    f"输出文件已存在：{raw_path}；使用 --resume 续跑或 --overwrite 覆盖"
                )
            done = load_completed_task_ids(raw_path) if resume else set()
            if overwrite and raw_path.exists():
                raw_path.unlink()
            raw_path.parent.mkdir(parents=True, exist_ok=True)

            if dry_run:
                client = JudgeClient(
                    cfg, dry_run=True, fake_responder=make_dry_run_responder(cfg.model)
                )
            else:
                client = JudgeClient(cfg)

            counts = {"OK": 0, "MODEL_OUTPUT_INVALID": 0, "TRANSPORT_ERROR": 0, "SKIPPED": 0}
            with open(raw_path, "a", encoding="utf-8") as fh:
                for row in rows:
                    task_id = row["task_id"]
                    if task_id in done:
                        counts["SKIPPED"] += 1
                        continue
                    record = client.judge(
                        task_id,
                        row["allowed_labels"],
                        prompt_version=row["prompt_version"],
                        messages=build_messages(template, row["payload"]),
                        temperature=temperature,
                        top_p=top_p,
                        seed=call_seed,
                    )
                    line = record.to_dict()
                    line["task_type"] = task_type
                    line["prompt_sha256"] = row["prompt_sha256"]
                    fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
                    counts[record.status] = counts.get(record.status, 0) + 1
            key = f"{task_type}/{cfg.name}"
            summary["tasks"][key] = {"n_attempted": len(rows) - counts["SKIPPED"], **counts}
            print(f"[run_judges] {key}: {summary['tasks'][key]} -> {raw_path}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payloads-dir", type=Path, default=DEFAULT_PAYLOADS_DIR)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--dry-run", action="store_true", help="确定性假响应，不联网")
    parser.add_argument(
        "--judges",
        nargs="*",
        default=None,
        help="启用的 judge 名（如 A B C）；dry-run 默认 A B C，真实模式默认环境已配置者",
    )
    parser.add_argument("--limit", type=int, default=None, help="每任务类型最多处理条数")
    parser.add_argument("--resume", action="store_true", help="跳过已成功的 task_id")
    parser.add_argument("--overwrite", action="store_true", help="删除已有输出后重跑")
    parser.add_argument(
        "--tasks",
        nargs="*",
        default=list(defs.ALL_TASK_TYPES),
        choices=list(defs.ALL_TASK_TYPES),
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    args = parser.parse_args(argv)

    if args.overwrite and args.resume:
        parser.error("--overwrite 与 --resume 不能同时使用")

    try:
        run(
            args.payloads_dir,
            args.out_root,
            dry_run=args.dry_run,
            judge_names=args.judges,
            limit=args.limit,
            resume=args.resume,
            overwrite=args.overwrite,
            tasks=args.tasks,
            temperature=args.temperature,
            top_p=args.top_p,
        )
    except JudgeClientError as exc:
        print(f"[run_judges] 配置错误：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
