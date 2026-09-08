# -*- coding: utf-8 -*-
"""run_judges_v31.py — v4 重建任务的 judge 运行器（P0-6/7/8）。

与 V3 run_judges.py 同构（judge 发现、resume、并发、有界重试、11 字段日志、
key 不落盘），但任务注册表换为 v3_1 的三个重建任务族（prompt_version=imcr.v4）：

* relation_semantic_v2   —— 断言是否被原文证据支持（五档语义支持标签）
* scope_revalidation_v2  —— role-owner 调整前后哪个更符合证据（A/B 盲评）
* identity_revalidation_v2 —— 两个实体名是否指同一实体（类型可见）

judge 配置沿用环境变量 JUDGE_{A..E}_BASE_URL/API_KEY/MODEL（与 V3 相同三 judge）。
输出：{out_root}/raw_runs/{task_type}/{judge}.jsonl + 运行摘要。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping

V3_1 = Path(__file__).resolve().parents[2]
V3 = V3_1.parent / "final_submission_v3"
for p in (str(V3 / "code"), str(V3 / "code" / "independent_eval"), str(V3 / "code" / "experiment_pipelines"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from judge_client import (  # noqa: E402
    JudgeClient,
    JudgeClientError,
    JudgeConfig,
    load_judge_config,
)
from _common import derive_seed, MASTER_SEED  # noqa: E402

PROMPT_VERSION = "imcr.v4"

TASKS: dict[str, dict[str, Any]] = {
    "relation_semantic_v2": {
        "payloads": V3_1 / "experiments" / "01_reference_rebuild" / "payloads" / "RELATION_SEMANTIC_V2_PAYLOADS.jsonl",
        "template": (
            "你是独立的历史知识图谱语义评审。给你一条断言（subject—predicate—object，含实体类型）"
            "和若干段真实文献证据文本。你的唯一任务：判断证据文本是否支持该断言。\n"
            "标签定义：\n"
            "SUPPORTED=证据明确陈述了该断言的内容；\n"
            "CONTEXTUAL_ONLY=证据仅提供间接或背景支持，断言需补充额外语境才成立；\n"
            "UNSUPPORTED=证据存在但不陈述、不支持该断言；\n"
            "CONTRADICTED=证据与断言相矛盾；\n"
            "INSUFFICIENT_EVIDENCE=证据缺失或过于稀薄，无法判断。\n"
            "只依据给出的证据，不得用未给出的知识补足。若 evidence_excerpts 为空，判 INSUFFICIENT_EVIDENCE。\n"
            "输出且仅输出一个 JSON 对象：{\"task_id\":..., \"decision\":..., \"confidence\":0-1, "
            "\"evidence\":[引用证据关键句], \"reason_code\":简短代码, \"explanation\":一句话理由, "
            "\"insufficient_evidence\":bool}"
        ),
    },
    "scope_revalidation_v2": {
        "payloads": V3_1 / "experiments" / "01_reference_rebuild" / "payloads" / "SCOPE_REVALIDATION_V2_PAYLOADS.jsonl",
        "template": (
            "你是独立的历史知识图谱时空标注评审。给定一条断言（含时间与空间表述）和两种不同的"
            "时间/空间角色标注方案（state a 与 state b），以及真实文献证据文本。"
            "角色定义见 schema_definitions。你的任务：依据证据判断哪种标注方案更符合原文语义。\n"
            "标签定义：A_BETTER=a 更符合证据；B_BETTER=b 更符合证据；EQUIVALENT=两种标注等价；"
            "BOTH_WRONG=两种标注都不符合证据；INSUFFICIENT_EVIDENCE=证据不足。\n"
            "a/b 与原文先后顺序无关，不要猜测哪个来自生产系统。只依据给出的证据。\n"
            "输出且仅输出一个 JSON 对象：{\"task_id\":..., \"decision\":..., \"confidence\":0-1, "
            "\"evidence\":[引用证据关键句], \"reason_code\":简短代码, \"explanation\":一句话理由, "
            "\"insufficient_evidence\":bool}"
        ),
    },
    "identity_revalidation_v2": {
        "payloads": V3_1 / "experiments" / "01_reference_rebuild" / "payloads" / "IDENTITY_REVALIDATION_V2_PAYLOADS.jsonl",
        "template": (
            "你是独立的历史实体消歧评审。给定两个实体指称（名称、别名、实体类型）各自的上下文"
            "（关系邻居、时间、空间、文献证据）。任务：判断 A 与 B 是否指同一现实世界实体。\n"
            "标签定义：same_entity=证据支持二者指同一实体；different_entity=证据表明是不同实体"
            "（类型不同、地域不同、时代不同、或明确为不同个体）；insufficient_evidence=证据不足。\n"
            "实体类型是合法的消歧证据。只依据给出的信息。\n"
            "输出且仅输出一个 JSON 对象：{\"task_id\":..., \"decision\":..., \"confidence\":0-1, "
            "\"evidence\":[引用关键上下文], \"reason_code\":简短代码, \"explanation\":一句话理由, "
            "\"insufficient_evidence\":bool}"
        ),
    },
}

OUT_ROOT = V3_1 / "experiments" / "01_reference_rebuild"


def discover_judges(judge_names: list[str] | None) -> list[JudgeConfig]:
    names = judge_names or ["A", "B", "C", "D", "E"]
    configs = []
    for name in names:
        try:
            configs.append(load_judge_config(name))
        except JudgeClientError:
            continue
    if not configs:
        raise JudgeClientError(
            "未配置任何 judge：请设置 JUDGE_{A,B,C}_BASE_URL/_API_KEY/_MODEL 环境变量"
        )
    return configs


def load_payloads(path: Path) -> list[dict[str, Any]]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def completed_ids(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("status") == "OK":
            done.add(str(rec.get("task_id")))
    return done


def build_messages(template: str, row: Mapping[str, Any]) -> list[dict[str, str]]:
    # task_id 注入 payload：模型必须回显同一 task_id（schema 校验依赖它）。
    payload = {"task_id": row["task_id"], **row["payload"]}
    return [
        {"role": "system", "content": template},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
    ]


def run(judges: list[JudgeConfig], tasks: list[str], workers: int, timeout: float, max_retries: int, limit: int | None = None) -> dict[str, Any]:
    call_seed = derive_seed("v31_judge_calls", MASTER_SEED)
    summary: dict[str, Any] = {}
    for task_type in tasks:
        reg = TASKS[task_type]
        rows = load_payloads(reg["payloads"])
        if limit is not None:
            rows = rows[:limit]
        for cfg in judges:
            raw_path = OUT_ROOT / "raw_runs" / task_type / f"{cfg.name}.jsonl"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            done = completed_ids(raw_path)
            pending = [r for r in rows if r["task_id"] not in done]
            client = JudgeClient(cfg, timeout=timeout, max_transport_retries=max_retries)
            counts = {"OK": 0, "MODEL_OUTPUT_INVALID": 0, "TRANSPORT_ERROR": 0, "SKIPPED": len(rows) - len(pending)}
            lock = threading.Lock()
            fh = open(raw_path, "a", encoding="utf-8")

            def _one(row: dict[str, Any]) -> dict[str, Any]:
                rec = client.judge(
                    row["task_id"],
                    row["allowed_labels"],
                    prompt_version=PROMPT_VERSION,
                    messages=build_messages(reg["template"], row),
                    temperature=0.0,
                    top_p=1.0,
                    seed=call_seed,
                )
                line = rec.to_dict()
                line["task_type"] = task_type
                line["prompt_sha256"] = row["prompt_sha256"]
                line["status"] = rec.status
                return line

            with fh:
                if workers <= 1:
                    for row in pending:
                        line = _one(row)
                        fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
                        fh.flush()
                        counts[line["status"]] += 1
                else:
                    with ThreadPoolExecutor(max_workers=workers) as pool:
                        futures = [pool.submit(_one, row) for row in pending]
                        for fut in as_completed(futures):
                            line = fut.result()
                            with lock:
                                fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
                                fh.flush()
                                counts[line["status"]] += 1
            summary[f"{task_type}/{cfg.name}"] = counts
            print(f"[run_judges_v31] {task_type}/{cfg.name}: {counts}")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--judges", nargs="*", default=None)
    ap.add_argument("--tasks", nargs="*", default=list(TASKS))
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--max-transport-retries", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None, help="每任务类型最多处理条数（冒烟用）")
    args = ap.parse_args()
    for t in args.tasks:
        if t not in TASKS:
            print(f"未知任务类型 {t}", file=sys.stderr)
            return 2
    try:
        judges = discover_judges(args.judges)
    except JudgeClientError as e:
        print(f"[run_judges_v31] {e}", file=sys.stderr)
        return 2
    run(judges, args.tasks, args.workers, args.timeout, args.max_transport_retries, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
