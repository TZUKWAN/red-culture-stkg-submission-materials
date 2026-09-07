"""Create an audited CreativeWork media enrichment for the STKG V2 entities."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V2_DATABASE = ROOT / "derived" / "red_culture_stkg_evolution_v2.sqlite"
V1_MEDIA_DATABASE = ROOT / "derived" / "creative_media_enrichment_v1.sqlite"
OUTPUT = ROOT / "derived" / "stkg_v2_creative_media_enrichment.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_creative_media.json"
PROJECT_CONFIG = ROOT / "extract_temporal_llm.py"
MODEL = "Qwen3.5-122B-A10B"
PROMPT_VERSION = "stkg-v2-creative-media-qwen-v2"
BUILD_VERSION = "red-culture-stkg-v2-creative-media-1"
ALLOWED_MEDIA_TYPES = {
    "小说", "散文", "报告文学", "诗歌", "歌曲", "歌剧", "话剧", "戏剧", "秧歌剧", "剧本",
    "舞剧", "舞蹈", "电影", "纪录片", "电视剧", "动画片", "广播剧",
    "连环画", "漫画", "绘画", "雕塑", "壁报", "曲艺", "理论著作",
    "文集", "民间传说", "其他", "未知",
}


SCHEMA = """
pragma foreign_keys=on;
create table creative_media_metadata(
  key text primary key,
  value_json text not null check(json_valid(value_json))
) without rowid;

create table creative_media_tasks(
  entity_id text primary key,
  canonical_name text not null,
  media_type text,
  classification_method text not null check(classification_method in (
    'inherited_v1_member_consensus','qwen_v2_semantic_classification'
  )),
  task_status text not null check(task_status in (
    'pending','processing','completed','unknown','retryable_error','manual_review'
  )),
  confidence real check(confidence is null or confidence between 0 and 1),
  attempts integer not null check(attempts between 0 and 30),
  model text,
  prompt_version text,
  reason_code text,
  explanation text,
  source_members_json text not null check(json_valid(source_members_json)),
  source_media_json text not null check(json_valid(source_media_json)),
  context_json text not null check(json_valid(context_json)),
  raw_response text,
  last_error text,
  updated_at text not null
) without rowid;

create index idx_v2_creative_media_status
  on creative_media_tasks(task_status,attempts,entity_id);
create index idx_v2_creative_media_type
  on creative_media_tasks(media_type,classification_method);

create view v_creative_media_final as
select entity_id,canonical_name,media_type,classification_method,task_status,confidence,
       attempts,model,prompt_version,reason_code,explanation,source_members_json,
       source_media_json,context_json,raw_response,updated_at
from creative_media_tasks
where task_status in ('completed','unknown');
"""


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_assignment(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    match = re.search(rf"^{re.escape(name)}\s*=\s*[\"']([^\"'\r\n]+)", text, re.M)
    return match.group(1).strip() if match else ""


def api_config() -> tuple[str, str]:
    base = (
        os.getenv("QWEN_API_BASE")
        or read_assignment(PROJECT_CONFIG, "QWEN_API_BASE")
        or read_assignment(PROJECT_CONFIG, "LM_STUDIO_URL")
    ).rstrip("/")
    key = (
        os.getenv("QWEN_API_KEY")
        or read_assignment(PROJECT_CONFIG, "QWEN_API_KEY")
        or read_assignment(PROJECT_CONFIG, "API_KEY")
    )
    if not base or not key:
        raise RuntimeError("Qwen API endpoint or key is not configured")
    if "127.0.0.1" in base or "localhost" in base.lower():
        raise RuntimeError("The V2 media task must use the configured remote Qwen service")
    if base.endswith("/chat/completions"):
        endpoint = base
    elif base.endswith("/v1"):
        endpoint = base + "/chat/completions"
    else:
        endpoint = base + "/v1/chat/completions"
    return endpoint, key


def parse_json_object(content: str) -> dict:
    cleaned = re.sub(r"<think[\s\S]*?</think>", "", str(content or ""), flags=re.I).strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("Qwen response contains no JSON object")


def parse_response(raw: str) -> dict:
    envelope = json.loads(raw)
    message = envelope["choices"][0].get("message", {})
    content = "\n".join(
        str(value)
        for value in (message.get("content"), message.get("reasoning_content"))
        if value
    )
    return parse_json_object(content)


def validate_model_result(value: dict) -> tuple[str, float, str, str]:
    media_type = str(value.get("media_type") or "").strip()
    reason_code = str(value.get("reason_code") or "").strip()
    explanation = str(value.get("explanation") or "").strip()
    try:
        confidence = float(value.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence is not numeric") from exc
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise ValueError(f"media_type not in controlled vocabulary: {media_type!r}")
    if not 0 <= confidence <= 1:
        raise ValueError(f"confidence out of range: {confidence}")
    if not reason_code or not explanation:
        raise ValueError("reason_code or explanation is empty")
    if media_type != "未知" and confidence < 0.90:
        return (
            "未知",
            confidence,
            "low_confidence_model_suggestion",
            f"模型建议{media_type}，但置信度低于0.90，保留未知。{explanation}",
        )
    return media_type, confidence, reason_code, explanation


def relation_context(con: sqlite3.Connection, entity_id: str) -> list[dict]:
    rows = con.execute(
        """
        select fact_id,predicate,
               case when subject_id=? then object_name else subject_name end counterpart_name,
               case when subject_id=? then object_type else subject_type end counterpart_type,
               normalized_time_label,province,city,county,research_tier
        from research_assertions
        where subject_id=? or object_id=?
        order by case research_tier when 'strict_semantic' then 0 when 'contextual' then 1 else 2 end,
                 fact_id
        limit 30
        """,
        (entity_id, entity_id, entity_id, entity_id),
    ).fetchall()
    return [dict(row) for row in rows]


def build_prompt(task: sqlite3.Row) -> str:
    context = json.loads(task["context_json"])
    return canonical_json(
        {
            "task": "判断一个红色文艺作品的媒介类型。只使用给定名称和关系上下文，不补造史实；信息不足返回未知。",
            "entity_id": task["entity_id"],
            "canonical_name": task["canonical_name"],
            "relation_context": context.get("relation_context", []),
            "allowed_media_types": sorted(ALLOWED_MEDIA_TYPES),
            "output_schema": {
                "media_type": "受控值或未知",
                "confidence": "0到1",
                "reason_code": "简短snake_case代码",
                "explanation": "一句中文理由，只引用名称或给定上下文",
            },
        }
    )


def call_qwen(endpoint: str, key: str, task: sqlite3.Row, timeout: int) -> tuple[str, dict]:
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "/no_think 你是文艺作品媒介类型分类器。一次一条，只输出JSON。"},
            {"role": "user", "content": build_prompt(task)},
        ],
        "temperature": 0.0,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    return raw, parse_response(raw)


def load_v1_media(path: Path) -> dict[str, dict]:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return {
            str(row["entity_id"]): dict(row)
            for row in con.execute("select * from v_creative_media_final order by entity_id")
        }
    finally:
        con.close()


def seed_tasks(con: sqlite3.Connection, v2_path: Path, v1_media: dict[str, dict]) -> dict:
    source = sqlite3.connect(f"file:{v2_path.as_posix()}?mode=ro&immutable=1", uri=True)
    source.row_factory = sqlite3.Row
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        works = source.execute(
            "select entity_id,canonical_name from research_entities "
            "where entity_type='CreativeWork' order by entity_id"
        ).fetchall()
        members: dict[str, list[str]] = defaultdict(list)
        for row in source.execute(
            "select canonical_entity_id,source_entity_id from research_entity_members "
            "order by canonical_entity_id,source_entity_id"
        ):
            members[str(row["canonical_entity_id"])].append(str(row["source_entity_id"]))
        inherited = 0
        pending = 0
        rows = []
        for work in works:
            entity_id = str(work["entity_id"])
            source_ids = members.get(entity_id, [])
            decisions = [v1_media[source_id] for source_id in source_ids if source_id in v1_media]
            media_types = sorted({str(item["media_type"]) for item in decisions})
            if len(media_types) > 1:
                raise RuntimeError(f"Conflicting inherited media types for {entity_id}: {media_types}")
            context = {"relation_context": relation_context(source, entity_id)}
            if media_types:
                decision = decisions[0]
                rows.append(
                    (
                        entity_id, work["canonical_name"], media_types[0],
                        "inherited_v1_member_consensus",
                        "unknown" if media_types[0] == "未知" else "completed",
                        float(decision["confidence"]), 0, decision["model"], decision["prompt_version"],
                        "inherited_v1_member_consensus",
                        "V2规范实体的V1成员媒介决定一致，继承已审计结果。",
                        canonical_json(source_ids),
                        canonical_json(
                            [
                                {
                                    "source_entity_id": item["entity_id"],
                                    "media_type": item["media_type"],
                                    "classification_method": item["classification_method"],
                                    "confidence": item["confidence"],
                                }
                                for item in decisions
                            ]
                        ),
                        canonical_json(context), None, None, now,
                    )
                )
                inherited += 1
            else:
                rows.append(
                    (
                        entity_id, work["canonical_name"], None,
                        "qwen_v2_semantic_classification", "pending", None, 0, MODEL,
                        PROMPT_VERSION, None, None, canonical_json(source_ids), "[]",
                        canonical_json(context), None, None, now,
                    )
                )
                pending += 1
        con.executemany("insert into creative_media_tasks values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
        return {"creative_works": len(works), "inherited": inherited, "qwen_pending": pending}
    finally:
        source.close()


def process_qwen_tasks(
    con: sqlite3.Connection,
    endpoint: str,
    key: str,
    max_attempts: int,
    timeout: int,
) -> dict:
    completed_this_run = 0
    technical_errors = 0
    while True:
        task = con.execute(
            "select * from creative_media_tasks where task_status in ('pending','retryable_error') "
            "and attempts<? order by entity_id limit 1",
            (max_attempts,),
        ).fetchone()
        if task is None:
            break
        attempts = int(task["attempts"]) + 1
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        con.execute(
            "update creative_media_tasks set task_status='processing',attempts=?,last_error=null,updated_at=? "
            "where entity_id=?",
            (attempts, now, task["entity_id"]),
        )
        con.commit()
        try:
            raw, parsed = call_qwen(endpoint, key, task, timeout)
            media_type, confidence, reason_code, explanation = validate_model_result(parsed)
            status = "unknown" if media_type == "未知" else "completed"
            con.execute(
                "update creative_media_tasks set media_type=?,task_status=?,confidence=?,model=?,"
                "prompt_version=?,reason_code=?,explanation=?,raw_response=?,last_error=null,updated_at=? "
                "where entity_id=?",
                (
                    media_type, status, confidence, MODEL, PROMPT_VERSION, reason_code,
                    explanation, raw, datetime.now().astimezone().isoformat(timespec="seconds"),
                    task["entity_id"],
                ),
            )
            con.commit()
            completed_this_run += 1
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError) as exc:
            technical_errors += 1
            status = "manual_review" if attempts >= max_attempts else "retryable_error"
            con.execute(
                "update creative_media_tasks set task_status=?,last_error=?,updated_at=? where entity_id=?",
                (
                    status, f"{type(exc).__name__}: {exc}"[:1000],
                    datetime.now().astimezone().isoformat(timespec="seconds"), task["entity_id"],
                ),
            )
            con.commit()
            if status != "manual_review":
                time.sleep(min(2 ** min(attempts, 5), 30))
    return {"completed_this_run": completed_this_run, "technical_errors": technical_errors}


def validate_database(con: sqlite3.Connection, expected_count: int) -> tuple[dict, list[str]]:
    con.row_factory = sqlite3.Row
    status_counts = dict(con.execute(
        "select task_status,count(*) from creative_media_tasks group by task_status"
    ))
    media_counts = dict(con.execute(
        "select media_type,count(*) from v_creative_media_final group by media_type order by media_type"
    ))
    checks = {
        "quick_check": con.execute("pragma quick_check").fetchone()[0],
        "foreign_key_errors": len(con.execute("pragma foreign_key_check").fetchall()),
        "task_count": con.execute("select count(*) from creative_media_tasks").fetchone()[0],
        "final_count": con.execute("select count(*) from v_creative_media_final").fetchone()[0],
        "nonfinal_count": con.execute(
            "select count(*) from creative_media_tasks where task_status not in ('completed','unknown')"
        ).fetchone()[0],
        "invalid_media_count": con.execute(
            "select count(*) from creative_media_tasks where task_status in ('completed','unknown') "
            "and (media_type is null or trim(media_type)='')"
        ).fetchone()[0],
        "qwen_final_count": con.execute(
            "select count(*) from creative_media_tasks where classification_method="
            "'qwen_v2_semantic_classification' and task_status in ('completed','unknown')"
        ).fetchone()[0],
        "qwen_missing_raw_response": con.execute(
            "select count(*) from creative_media_tasks where classification_method="
            "'qwen_v2_semantic_classification' and task_status in ('completed','unknown') "
            "and (raw_response is null or trim(raw_response)='')"
        ).fetchone()[0],
        "attempts_over_30": con.execute(
            "select count(*) from creative_media_tasks where attempts>30"
        ).fetchone()[0],
    }
    failures = []
    if checks["quick_check"] != "ok":
        failures.append(f"quick_check={checks['quick_check']}")
    if checks["foreign_key_errors"]:
        failures.append(f"foreign_key_errors={checks['foreign_key_errors']}")
    for key in ("nonfinal_count", "invalid_media_count", "qwen_missing_raw_response", "attempts_over_30"):
        if checks[key]:
            failures.append(f"{key}={checks[key]}")
    if checks["task_count"] != expected_count or checks["final_count"] != expected_count:
        failures.append(
            f"coverage={checks['task_count']}/{checks['final_count']} expected={expected_count}"
        )
    return {"checks": checks, "status_counts": status_counts, "media_counts": media_counts}, failures


def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def build(v2_path: Path, v1_media_path: Path, output: Path, report_path: Path, timeout: int) -> dict:
    for required in (v2_path, v1_media_path):
        if not required.exists():
            raise FileNotFoundError(required)
    v2_hash = sha256(v2_path)
    v1_media_hash = sha256(v1_media_path)
    temporary = output.with_name(f".{output.name}.tmp")
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(temporary) + suffix).unlink(missing_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(temporary)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(SCHEMA)
        v1_media = load_v1_media(v1_media_path)
        seed = seed_tasks(con, v2_path, v1_media)
        endpoint, key = api_config()
        qwen = process_qwen_tasks(con, endpoint, key, max_attempts=30, timeout=timeout)
        con.execute(
            "insert into creative_media_metadata values(?,?)",
            ("build", canonical_json({"version": BUILD_VERSION, "seed": seed, "model": MODEL})),
        )
        con.commit()
        validation, failures = validate_database(con, seed["creative_works"])
    finally:
        con.close()
    source_unchanged = sha256(v2_path) == v2_hash and sha256(v1_media_path) == v1_media_hash
    if not source_unchanged:
        failures.append("source database changed during enrichment")
    if failures:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("V2 creative media validation failed: " + "; ".join(failures))
    temporary.replace(output)
    report = {
        "status": "PASS",
        "build_version": BUILD_VERSION,
        "sources": {
            "v2_evolution": {"path": str(v2_path.resolve()), "sha256": v2_hash},
            "v1_media": {"path": str(v1_media_path.resolve()), "sha256": v1_media_hash},
            "unchanged": source_unchanged,
        },
        "output": {
            "path": str(output.resolve()), "size_bytes": output.stat().st_size,
            "sha256": sha256(output),
        },
        "seed": seed,
        "qwen": {"model": MODEL, "prompt_version": PROMPT_VERSION, **qwen},
        "validation": validation,
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    atomic_write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2-database", type=Path, default=V2_DATABASE)
    parser.add_argument("--v1-media-database", type=Path, default=V1_MEDIA_DATABASE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    report = build(
        args.v2_database.resolve(), args.v1_media_database.resolve(),
        args.output.resolve(), args.report.resolve(), args.timeout,
    )
    print(canonical_json({
        "status": report["status"], "output": report["output"],
        "seed": report["seed"], "qwen": report["qwen"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
