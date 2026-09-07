# -*- coding: utf-8 -*-
"""run_blind_llm_baseline.py — B3 盲 LLM 基线：对冻结 IMCR payload 做 fresh 调用。

设计规范：audit/04_BASELINE_DESIGN.md §6（B3 独立于 judge 面板的 fresh 调用）。

用法：

    # 真实运行（配置来自环境变量 BLIND_LLM_BASE_URL / BLIND_LLM_API_KEY / BLIND_LLM_MODEL）
    python run_blind_llm_baseline.py

    # 离线演练（确定性假响应，不联网）
    python run_blind_llm_baseline.py --dry-run --limit 5 --out-dir <tmp>

    # 断点续跑：跳过已有 status==OK 的 task_id
    python run_blind_llm_baseline.py --resume

行为契约：
* 模型槽位：env 变量 BLIND_LLM_BASE_URL/API_KEY/MODEL（judge A 为 Qwen3.5-122B，
  B3 须为不同模型实例；对 Qwen 家族基线使用 leave-Qwen-out 参考集评价，§12.1）。
* 输入：与 judge 完全相同的冻结盲化 payload（experiments/08_independent_reference/
  payloads/*.jsonl）与 prompt 模板（imcr_task_defs.PROMPT_TEMPLATES）——B3 与 judge
  的差异只在模型与调用参数记录。
* 调用合规：复用 judge_client.JudgeClient（temperature=0、top_p=1.0、
  seed=derive_seed("blind_llm_baseline")，JSON 校验 + 有界重试 + 达到上限标记
  MODEL_OUTPUT_INVALID，绝不手工改答案）；调用日志写
  {out-dir}/blind_llm_runs/{task_type}.jsonl，字段与 judge raw_runs 同构
  （GOAL 19 的 11 项 + task_type/prompt_sha256/status/dry_run）+ blind_baseline: true；
  API key 永不落盘。
* 解码：scope_adjustment 的 A_/B_ 标签按 payloads/SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING.csv
  解码回 BEFORE_/AFTER_（与 judge 共识同一映射文件、同一 decode_ab_label）。
* 硬约束门（§6）：entity_type=TYPE_FAMILY+contraindication；relation_contract=
  契约类型兼容（valid 主张须与 research_relation_contract 相容）；其余任务型 gate=1。
* 输出 {out-dir}/IMCR_BLIND_LLM_RUNS.csv：23 列 schema（§2），method_id=B3_blind_llm，
  prediction=模型 decision（解码后）、confidence=模型自报 confidence、
  actual_llm_calls=1+retry_count；无效输出的样本落 availability_status=not_available
  （prediction 空），原始无效记录保留在 jsonl 日志。
* 安全默认：输出日志已存在且未给 --resume/--overwrite 时拒绝运行。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping, Sequence

CODE_DIR = Path(__file__).resolve().parents[1]
for _p in (
    str(CODE_DIR),
    str(CODE_DIR / "independent_eval"),
    str(Path(__file__).resolve().parent),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from judge_client import (  # noqa: E402
    JudgeClient,
    JudgeClientError,
    JudgeConfig,
    MODEL_OUTPUT_INVALID,
)
from _common import connect_final, derive_seed, write_csv  # noqa: E402
import imcr_task_defs as defs  # noqa: E402
from run_judges import (  # noqa: E402
    build_messages,
    load_completed_task_ids,
    load_payload_file,
    make_dry_run_responder,
)
from build_imcr_consensus import decode_ab_label, load_ab_mapping  # noqa: E402
from run_independent_baselines import (  # noqa: E402
    BLIND_LOG_DIR,
    BLIND_RUNS_NAME,
    EXP09,
    GATE_B3_ENTITY,
    GATE_B3_RELATION,
    InputPaths,
    RUNS_FIELDS,
    SRC_B3,
    default_input_paths,
    load_relation_contract,
)

B3_METHOD_ID = "B3_blind_llm"
B3_METHOD_NAME = "Blind LLM (fresh)"

ENV_EXAMPLE_HINT = (
    "未配置盲 LLM 基线。请设置环境变量 BLIND_LLM_BASE_URL / BLIND_LLM_API_KEY / "
    "BLIND_LLM_MODEL（模型实例须区别于 judge A 的 Qwen3.5-122B-A10B）；"
    "或使用 --dry-run 做离线演练。"
)


# ---------------------------------------------------------------------------
# 配置发现
# ---------------------------------------------------------------------------


def load_blind_config(env: Mapping[str, str] | None = None) -> JudgeConfig:
    """从 BLIND_LLM_{BASE_URL,API_KEY,MODEL} 载入 B3 模型配置（key 不落盘）。"""
    environ = os.environ if env is None else env
    missing = [
        var
        for var in ("BLIND_LLM_BASE_URL", "BLIND_LLM_API_KEY", "BLIND_LLM_MODEL")
        if not environ.get(var)
    ]
    if missing:
        raise JudgeClientError(
            f"missing environment variables for blind LLM baseline: {', '.join(missing)}"
        )
    return JudgeConfig(
        name="BLIND",
        base_url=environ["BLIND_LLM_BASE_URL"],
        api_key=environ["BLIND_LLM_API_KEY"],
        model=environ["BLIND_LLM_MODEL"],
    )


def discover_blind_config(dry_run: bool, env: Mapping[str, str] | None = None) -> JudgeConfig:
    """dry-run 返回合成配置（不联网）；真实模式缺任一变量即明确报错。"""
    if dry_run:
        return JudgeConfig(
            name="BLIND",
            base_url="http://dry-run.local/v1",
            api_key="dry-run-placeholder",  # 仅内存占位，永不落盘
            model="dry-run-blind-llm",
        )
    return load_blind_config(env)


# ---------------------------------------------------------------------------
# 硬约束门（§6，与 B1 同型）
# ---------------------------------------------------------------------------


def build_gate_resources(
    conn,
    inputs: InputPaths,
    payloads_dir: Path,
    task_types: Sequence[str],
) -> dict[str, Any]:
    """B3 门所需的最小只读资源：entity 样本→entity_id、成员源类型集、关系契约。"""
    resources: dict[str, Any] = {
        "entity_ids": {},
        "member_types": {},
        "relation_contract": {},
    }
    if "entity_type" in task_types:
        sample_path = inputs.entity_type_sample
        if sample_path.exists():
            resources["entity_ids"] = {
                r["sample_id"]: r["entity_id"] for r in defs.read_csv_rows(sample_path)
            }
    if "relation_contract" in task_types:
        resources["relation_contract"] = load_relation_contract(conn)
    return resources


def member_source_types(conn, canonical_id: str) -> tuple[str, ...]:
    """规范实体的成员 source_entity_type 集合（contraindication 的 cluster 输入）。"""
    rows = conn.execute(
        "select source_entity_type from research_entity_members where canonical_entity_id=?",
        (canonical_id,),
    ).fetchall()
    return tuple(sorted({str(r["source_entity_type"]) for r in rows}))


def b3_hard_constraint(
    task_type: str,
    prediction: str | None,
    payload: Mapping[str, Any],
    resources: Mapping[str, Any],
    conn,
) -> tuple[bool, str]:
    """对 B3 预测执行与 B1 同型的硬约束检查（§6）。

    entity_type：TYPE_FAMILY + entity_model_contraindication（用盲化实体名 +
    成员源类型簇；source_type 留空——盲化 payload 不含该信号）。
    relation_contract：prediction=='valid' 的主张须与 research_relation_contract
    的 domain/range 相容（类型相容是 valid 的必要条件）；其余标签不主张严格
    语义成立，结构上门恒过。其余任务型 gate=1。
    """
    if not prediction:
        return False, "empty prediction"
    if task_type == "entity_type":
        from run_independent_baselines import entity_rule_gate

        entity_id = resources["entity_ids"].get(str(payload.get("task_id", "")), "")
        cluster = resources["member_types"].get(entity_id)
        if cluster is None and entity_id and conn is not None:
            cluster = member_source_types(conn, entity_id)
            resources["member_types"][entity_id] = cluster
        ok = entity_rule_gate(str(payload.get("entity_name") or ""), "", prediction, cluster or ())
        return ok, GATE_B3_ENTITY
    if task_type == "relation_contract":
        if prediction != "valid":
            return True, GATE_B3_RELATION
        spec = resources["relation_contract"].get(str(payload.get("relation_text") or ""))
        ok = bool(
            spec
            and str(payload.get("subject_type") or "") in spec["source_types"]
            and str(payload.get("object_type") or "") in spec["target_types"]
        )
        return ok, GATE_B3_RELATION
    return True, "no structural gate for this task type (design §6)"


# ---------------------------------------------------------------------------
# 阶段 1：fresh 调用 → jsonl 日志
# ---------------------------------------------------------------------------


def run_calls(
    payloads_dir: Path,
    out_dir: Path,
    *,
    dry_run: bool,
    limit: int | None,
    resume: bool,
    overwrite: bool,
    tasks: Sequence[str],
    temperature: float,
    top_p: float,
    workers: int = 1,
    timeout: float = 60.0,
    max_transport_retries: int = 4,
    fake_responder=None,
) -> dict[str, Any]:
    cfg = discover_blind_config(dry_run)
    call_seed = derive_seed("blind_llm_baseline")
    summary: dict[str, Any] = {"model": cfg.to_safe_dict(), "tasks": {}}
    if dry_run:
        client = JudgeClient(
            cfg,
            dry_run=True,
            fake_responder=fake_responder if fake_responder is not None else make_dry_run_responder(cfg.model),
        )
    else:
        client = JudgeClient(
            cfg, timeout=timeout, max_transport_retries=max_transport_retries
        )

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

        log_path = out_dir / BLIND_LOG_DIR / f"{task_type}.jsonl"
        if log_path.exists() and not (resume or overwrite):
            raise FileExistsError(
                f"输出日志已存在：{log_path}；使用 --resume 续跑或 --overwrite 覆盖"
            )
        done = load_completed_task_ids(log_path) if resume else set()
        if overwrite and log_path.exists():
            log_path.unlink()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        counts = {"OK": 0, MODEL_OUTPUT_INVALID: 0, "TRANSPORT_ERROR": 0, "SKIPPED": 0}
        pending = [row for row in rows if row["task_id"] not in done]
        counts["SKIPPED"] = len(rows) - len(pending)

        def _call_one(row: Mapping[str, Any]) -> dict[str, Any]:
            record = client.judge(
                row["task_id"],
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
            line["status"] = record.status
            line["blind_baseline"] = True
            return line

        # 写入串行化：worker 只负责调用，主线程逐条 append + flush（--resume 幂等）
        write_lock = threading.Lock()
        with open(log_path, "a", encoding="utf-8") as fh:
            if workers <= 1:
                for row in pending:
                    line = _call_one(row)
                    fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
                    fh.flush()
                    counts[line["status"]] = counts.get(line["status"], 0) + 1
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(_call_one, row) for row in pending]
                    for fut in as_completed(futures):
                        line = fut.result()
                        with write_lock:
                            fh.write(
                                json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n"
                            )
                            fh.flush()
                            counts[line["status"]] = counts.get(line["status"], 0) + 1
        summary["tasks"][task_type] = counts
        print(f"[run_blind_llm_baseline] {task_type}: {counts} -> {log_path}")
    return summary


# ---------------------------------------------------------------------------
# 阶段 2：日志 → IMCR_BLIND_LLM_RUNS.csv（23 列）
# ---------------------------------------------------------------------------


def load_latest_records(log_dir: Path, task_type: str) -> dict[str, dict[str, Any]]:
    """task_id → 该任务最新一条调用记录（同 task_id 多条时取最后一条）。"""
    path = log_dir / f"{task_type}.jsonl"
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            out[str(rec.get("task_id"))] = rec
    return out


def load_item_id_maps(inputs: InputPaths) -> dict[str, dict[str, str]]:
    """task_type → {sample_id: item_id}（从冻结样本文件补全 item_id 列）。"""
    maps: dict[str, dict[str, str]] = {}
    if inputs.entity_type_sample.exists():
        maps["entity_type"] = {
            r["sample_id"]: r["entity_id"] for r in defs.read_csv_rows(inputs.entity_type_sample)
        }
    if inputs.relation_contract_sample.exists():
        maps["relation_contract"] = {
            r["sample_id"]: r["fact_id"]
            for r in defs.read_csv_rows(inputs.relation_contract_sample)
        }
    if inputs.scope_adjustment_tasks.exists():
        maps["scope_adjustment"] = {
            r["task_id"]: r["fact_id"] for r in defs.read_jsonl(inputs.scope_adjustment_tasks)
        }
    if inputs.identity_pair_tasks.exists():
        maps["identity_pair"] = {
            r["pair_id"]: r["pair_id"] for r in defs.read_jsonl(inputs.identity_pair_tasks)
        }
    if inputs.provenance_sample.exists():
        maps["provenance_support"] = {
            r["sample_id"]: r["fact_id"] for r in defs.read_csv_rows(inputs.provenance_sample)
        }
    return maps


def build_b3_rows(
    payloads_dir: Path,
    log_dir: Path,
    *,
    inputs: InputPaths,
    conn=None,
    tasks: Sequence[str],
) -> list[dict[str, Any]]:
    """从调用日志构建 23 列 B3 行：解码 scope A/B 标签、执行硬约束门、
    无效输出落 not_available。"""
    ab_mapping = load_ab_mapping(payloads_dir)
    gate_resources = build_gate_resources(conn, inputs, payloads_dir, tasks)
    item_maps = load_item_id_maps(inputs)
    rows: list[dict[str, Any]] = []
    for task_type in tasks:
        records = load_latest_records(log_dir, task_type)
        for task_id in sorted(records):
            rec = records[task_id]
            status = str(rec.get("status"))
            parsed = rec.get("parsed_response") or {}
            item_map = item_maps.get(task_type, {})
            base = {
                "sample_id": task_id,
                "task_type": task_type,
                "item_id": item_map.get(task_id, task_id),
                "split": "independent_eval",
                "method_id": B3_METHOD_ID,
                "method_name": B3_METHOD_NAME,
                "evidence_class": "actual_run",
                "comparison_tier": "independent_reference",
                "overlap_status": "independent_of_era",
                "primary_comparison_eligible": 1,
                "evaluation_eligibility": "core_eligible_task",
                "gold_label": "",
                "covered": 0,
                "correct": 0,
                "safe_correct": 0,
                "actual_llm_calls": int(rec.get("retry_count") or 0) + 1,
                "source_artifact": SRC_B3,
            }
            if status != "OK" or not parsed:
                reason = (
                    f"{status}: {rec.get('validation_error')}"
                    if status == MODEL_OUTPUT_INVALID
                    else f"no valid blind LLM output ({status})"
                )
                base.update(
                    availability_status="not_available",
                    prediction="",
                    confidence="",
                    hard_constraint_pass=0,
                    constraint_gate_source="not_available",
                    note=f"NOT_AVAILABLE: {reason}",
                )
                rows.append(base)
                continue
            raw_label = str(parsed.get("decision") or "")
            label = (
                decode_ab_label(raw_label, ab_mapping.get(task_id))
                if task_type == "scope_adjustment"
                else raw_label
            )
            # 门所需的 payload 字段：从日志找回（raw 记录不含 payload，重读 payload 文件）
            payload_fields = _payload_lookup(payloads_dir, task_type).get(task_id, {})
            gate, gate_source = b3_hard_constraint(
                task_type, label, {**payload_fields, "task_id": task_id}, gate_resources, conn
            )
            note = (
                f"mapping=fresh blind LLM decision on frozen IMCR payload "
                f"(prompt_template=imcr_task_defs.PROMPT_TEMPLATES[{task_type}], "
                f"temperature=0, top_p=1, seed=derive_seed('blind_llm_baseline')); "
                f"confidence=model self-reported"
            )
            if task_type == "scope_adjustment":
                note += (
                    "; A_/B_ labels decoded to BEFORE_/AFTER_ via "
                    "SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING.csv (decode_ab_label)"
                )
            note += f"; gate={gate_source}"
            base.update(
                availability_status="available",
                prediction=label,
                confidence=f"{float(parsed.get('confidence')):.12f}",
                hard_constraint_pass=int(bool(gate)),
                constraint_gate_source=gate_source,
                note=note,
            )
            rows.append(base)
    return rows


_PAYLOAD_CACHE: dict[str, dict[str, dict[str, Any]]] = {}


def _payload_lookup(payloads_dir: Path, task_type: str) -> dict[str, dict[str, Any]]:
    """task_id → 盲化 payload 字典（门所需的实体名/类型/谓词）。"""
    cache_key = str(payloads_dir)
    if cache_key not in _PAYLOAD_CACHE:
        _PAYLOAD_CACHE[cache_key] = {}
    if task_type not in _PAYLOAD_CACHE[cache_key]:
        path = payloads_dir / defs.TASK_REGISTRY[task_type]["output"]
        lookup: dict[str, dict[str, Any]] = {}
        if path.exists():
            for row in load_payload_file(path):
                lookup[str(row["task_id"])] = dict(row.get("payload") or {})
        _PAYLOAD_CACHE[cache_key][task_type] = lookup
    return _PAYLOAD_CACHE[cache_key][task_type]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run(
    payloads_dir: Path,
    out_dir: Path,
    *,
    dry_run: bool,
    limit: int | None,
    resume: bool,
    overwrite: bool,
    tasks: Sequence[str],
    temperature: float = 0.0,
    top_p: float = 1.0,
    workers: int = 1,
    timeout: float = 60.0,
    max_transport_retries: int = 4,
    conn=None,
    inputs: InputPaths | None = None,
    fake_responder=None,
) -> dict[str, Any]:
    """阶段 1 fresh 调用 + 阶段 2 构建 IMCR_BLIND_LLM_RUNS.csv。返回摘要 dict。"""
    inputs = inputs or default_input_paths()
    out_dir = Path(out_dir)
    owned = conn is None
    con = connect_final() if owned else conn
    try:
        summary = run_calls(
            payloads_dir,
            out_dir,
            dry_run=dry_run,
            limit=limit,
            resume=resume,
            overwrite=overwrite,
            tasks=tasks,
            temperature=temperature,
            top_p=top_p,
            workers=workers,
            fake_responder=fake_responder,
        )
        rows = build_b3_rows(
            payloads_dir,
            out_dir / BLIND_LOG_DIR,
            inputs=inputs,
            conn=con,
            tasks=tasks,
        )
        n_available = sum(1 for r in rows if r["availability_status"] == "available")
        print(
            f"[run_blind_llm_baseline] IMCR_BLIND_LLM_RUNS.csv rows={len(rows)} "
            f"(available={n_available}, not_available={len(rows) - n_available})"
        )
        write_csv(out_dir / BLIND_RUNS_NAME, RUNS_FIELDS, rows)
        summary["n_rows"] = len(rows)
        summary["n_available"] = n_available
        summary["runs_csv"] = str(out_dir / BLIND_RUNS_NAME)
        return summary
    finally:
        if owned and con is not None:
            con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payloads-dir", type=Path, default=defs.EXP08 / "payloads")
    parser.add_argument("--out-dir", type=Path, default=EXP09)
    parser.add_argument("--dry-run", action="store_true", help="确定性假响应，不联网")
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
    parser.add_argument(
        "--workers", type=int, default=1, help="并发 worker 数（有界；默认 1 纯串行）"
    )
    parser.add_argument(
        "--timeout", type=float, default=120.0, help="单次 HTTP 调用超时秒数"
    )
    parser.add_argument(
        "--max-transport-retries", type=int, default=4, help="传输级有界重试次数"
    )
    args = parser.parse_args(argv)
    if args.overwrite and args.resume:
        parser.error("--overwrite 与 --resume 不能同时使用")
    if args.workers < 1:
        parser.error("--workers 必须 >= 1")
    try:
        run(
            args.payloads_dir,
            args.out_dir,
            dry_run=args.dry_run,
            limit=args.limit,
            resume=args.resume,
            overwrite=args.overwrite,
            tasks=args.tasks,
            temperature=args.temperature,
            top_p=args.top_p,
            workers=args.workers,
            timeout=args.timeout,
            max_transport_retries=args.max_transport_retries,
        )
    except JudgeClientError as exc:
        print(f"[run_blind_llm_baseline] 配置错误：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
