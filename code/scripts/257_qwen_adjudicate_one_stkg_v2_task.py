"""Use one remote Qwen call to adjudicate one STKG V2 semantic task."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from stkg_contract import strong_entity_type_hint
from stkg_v2_semantics import (
    TYPE_PARENT, refine_lexical_hint, semantic_family, spatial_model_contraindication,
    strict_v2_entity_type_hint, type_facets,
)


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
PROJECT_CONFIG = ROOT / "extract_temporal_llm.py"
MODEL = "Qwen3.5-122B-A10B"
PROMPT_VERSION = "stkg-v2-semantic-adjudication-4"
MAX_ATTEMPTS = 30
CLASSIFIER_REVIEW_TASK = "entity_type_classifier_review"
MODEL_SECOND_REVIEW_TASK = "entity_type_model_second_review"
ENTITY_TYPES = {
    "Spirit", "ValueFacet", "Person", "Organization", "Event", "Place", "TimePeriod",
    "Document", "Artifact", "CreativeWork", "Institution", "AdministrativeRegion",
    "BasinSection", "CulturalSite", "EvolutionStage", "Position", "Concept", "SocialGroup",
}


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


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
        raise RuntimeError("remote Qwen API endpoint or key is not configured")
    if base.endswith("/chat/completions"):
        endpoint = base
    elif base.endswith("/v1"):
        endpoint = base + "/chat/completions"
    else:
        endpoint = base + "/v1/chat/completions"
    hostname = (urllib.parse.urlparse(endpoint).hostname or "").lower()
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("V2 adjudication must use the authorized remote Qwen service, not LM Studio")
    return endpoint, key


def parse_json_object(content: str) -> dict:
    cleaned = re.sub(r"<think[\s\S]*?</think>", "", str(content or ""), flags=re.I).strip()
    decoder = json.JSONDecoder()
    for index, character in enumerate(cleaned):
        if character != "{":
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
    message = envelope["choices"][0]["message"]
    content = "\n".join(
        str(value) for value in (message.get("content"), message.get("reasoning_content")) if value
    )
    return parse_json_object(content)


def entity_context(con: sqlite3.Connection, entity_id: str) -> list[dict]:
    rows = con.execute(
        "select a.fact_id,a.predicate,"
        "case when a.subject_id=? then 'subject' else 'object' end endpoint_role,"
        "case when a.subject_id=? then o.canonical_name else s.canonical_name end other_name,"
        "case when a.subject_id=? then coalesce(o.semantic_entity_type,o.source_entity_type) "
        "else coalesce(s.semantic_entity_type,s.source_entity_type) end other_type,"
        "a.time_start,a.place_raw "
        "from v2_assertion_scopes a join v2_entities s on s.entity_id=a.subject_id "
        "join v2_entities o on o.entity_id=a.object_id "
        "where a.subject_id=? or a.object_id=? "
        "order by case when a.predicate like 'raw:%' then 1 else 0 end,a.fact_id limit 24",
        (entity_id, entity_id, entity_id, entity_id, entity_id),
    ).fetchall()
    return [
        {
            "fact_id": row[0], "predicate": row[1], "endpoint_role": row[2],
            "other_name": row[3], "other_type": row[4], "time_start": row[5], "place_raw": row[6],
        }
        for row in rows
    ]


def build_entity_prompt(con: sqlite3.Connection, task: sqlite3.Row) -> str:
    payload = json.loads(task["payload_json"])
    entity = con.execute(
        "select canonical_name,source_entity_type,aliases_json from v2_entities where entity_id=?",
        (task["unit_id"],),
    ).fetchone()
    return json.dumps(
        {
            "task": (
                "只判断一个知识图谱实体节点的正确类型，不核查历史事实真假，不创建新事实，不合并不同ID。"
                "同名可以对应不同真实对象，例如事件与同名文艺作品；必须依据当前节点自己的别名、关系方向和相邻节点判断。"
                "source_type只是旧标签，不保证正确；lexical_hint和schema_votes也只是候选信号。"
                "Organization表示有明确组织边界和结构的正式组织；SocialGroup表示因共同身份、信念或行动而作为集体行动者出现的正式或非正式社会群体。"
                "仅表示类别而没有具体集体行动语境的军阀、工人、群众、知识分子等仍属于Concept；不能把SocialGroup和Concept混为一谈。"
                "Person也必须是具体人物，泛称身份或群体不是Person。只有一个类型被上下文明确支持时才能给高置信度；理由中若出现多个可能类型必须输出unknown。"
                "类型存在父子层级：AdministrativeRegion和CulturalSite是Place子类，Institution是Organization子类，Organization是SocialGroup子类，Spirit/ValueFacet/Position是Concept子类。"
                "若source_type是更具体的子类而上下文只支持其父类，应保留更具体的source_type；只有明确证明原子类错误时才改类型。"
                "若final_type与source_type相同，decision必须是keep；若不同，decision必须是retype。"
                "若上下文不足以区分，必须输出unknown，不能猜测。"
            ),
            "entity_id": task["unit_id"],
            "canonical_name": entity["canonical_name"],
            "aliases": json.loads(entity["aliases_json"]),
            "source_type": entity["source_entity_type"],
            "lexical_hint": refine_lexical_hint(
                str(entity["canonical_name"]), str(entity["source_entity_type"]),
                strong_entity_type_hint(entity["canonical_name"]),
            ),
            "schema_votes": payload.get("schema_votes", {}),
            "risk_flags": payload.get("risk_flags", []),
            "relation_context": entity_context(con, task["unit_id"]),
            "allowed_entity_types": sorted(ENTITY_TYPES),
            "output_schema": {
                "decision": "keep|retype|unknown",
                "final_type": "allowed entity type, or empty when unknown",
                "confidence": "0..1",
                "reason_code": "short snake_case code",
                "explanation": "one concise Chinese sentence based only on supplied context",
            },
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def build_event_time_prompt(con: sqlite3.Connection, task: sqlite3.Row) -> str:
    payload = json.loads(task["payload_json"])
    event = con.execute(
        "select canonical_name,aliases_json from v2_entities where entity_id=?", (task["unit_id"],)
    ).fetchone()
    candidates = []
    for item in payload.get("candidates", []):
        row = con.execute(
            "select a.fact_id,a.predicate,a.time_raw,a.time_start,a.time_end,a.time_precision,"
            "s.canonical_name,coalesce(s.semantic_entity_type,s.source_entity_type),"
            "o.canonical_name,coalesce(o.semantic_entity_type,o.source_entity_type),a.place_raw "
            "from v2_assertion_scopes a join v2_entities s on s.entity_id=a.subject_id "
            "join v2_entities o on o.entity_id=a.object_id where a.fact_id=?",
            (item["fact_id"],),
        ).fetchone()
        if row:
            candidates.append({
                "fact_id": row[0], "predicate": row[1], "time_raw": row[2],
                "time_start": row[3], "time_end": row[4], "time_precision": row[5],
                "subject": row[6], "subject_type": row[7], "object": row[8],
                "object_type": row[9], "place_raw": row[10],
            })
    previous_failure = con.execute(
        "select error_message from v2_model_failures where task_id=? "
        "order by attempt desc,created_at desc limit 1",
        (task["task_id"],),
    ).fetchone()
    return json.dumps(
        {
            "task": (
                "判断给定候选日期是否表示这个事件自身的发生时间，只做时间语义归属，不核查史实真假，不新增日期。"
                "人物生平、参与关系、来源文档、后续纪念、作品创作和宽泛历史阶段时间都不能冒充事件发生时间。"
                "只能在给定fact_id中选择；每个候选必须且只能进入accepted、rejected或unknown之一。"
                "三个数组必须两两互斥，严禁把同一个fact_id同时放入两个数组。"
                "accepted表示该记录可作为事件发生时间，rejected表示只能作为上下文时间，unknown表示材料不足。"
            ),
            "event_id": task["unit_id"],
            "event_name": event["canonical_name"],
            "aliases": json.loads(event["aliases_json"]),
            "controlled_year_conflict": payload.get("controlled_year_conflict", False),
            "candidates": candidates,
            "previous_validator_feedback": (
                str(previous_failure[0])
                if previous_failure
                else ""
            ),
            "output_schema": {
                "accepted_fact_ids": ["fact_id"],
                "rejected_fact_ids": ["fact_id"],
                "unknown_fact_ids": ["fact_id"],
                "confidence": "0..1 overall confidence",
                "reason_code": "short snake_case code",
                "explanation": "one concise Chinese sentence based only on supplied candidates",
            },
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def validate_entity_result(
    result: dict, source_type: str, canonical_name: str = ""
) -> tuple[str, str | None, float, str, str]:
    decision = str(result.get("decision") or "").strip().lower()
    final_type = str(result.get("final_type") or "").strip() or None
    confidence = max(0.0, min(1.0, float(result.get("confidence") or 0.0)))
    reason_code = str(result.get("reason_code") or "").strip()[:120]
    explanation = str(result.get("explanation") or "").strip()[:1000]
    if decision not in {"keep", "retype", "unknown"}:
        raise ValueError("invalid entity type decision")
    if decision == "unknown":
        return decision, None, confidence, reason_code or "unknown", explanation
    if final_type not in ENTITY_TYPES:
        raise ValueError("invalid final entity type")
    if (
        TYPE_PARENT.get(source_type) == final_type
        and not (source_type == "Organization" and final_type == "SocialGroup")
        and strict_v2_entity_type_hint(canonical_name, source_type) != final_type
    ):
        final_type = source_type
    expected_decision = "keep" if final_type == source_type else "retype"
    if decision != expected_decision:
        decision = expected_decision
        reason_code = reason_code or "normalized_decision_from_final_type"
    ambiguity_patterns = (
        r"可能(?:是|属于)", r"也可能", r"无法(?:确定|区分|判断)", r"难以(?:确定|区分|判断)",
        r"信息不足", r"上下文不足", r"属于[^，。；]{0,30}(?:或|或者)[^，。；]{0,30}(?:范畴|类型)",
        r"(?:组织|机构|地点|事件|人物|概念)[^，。；]{0,12}(?:或|或者)[^，。；]{0,12}(?:组织|机构|地点|事件|人物|概念)",
        r"(?:均|都)(?:合理|可行|可能)",
    )
    if any(re.search(pattern, explanation) for pattern in ambiguity_patterns):
        return "unknown", None, min(confidence, 0.50), "ambiguous_explanation", explanation
    contraindication = spatial_model_contraindication(canonical_name, str(final_type or ""))
    if contraindication:
        return "unknown", None, min(confidence, 0.50), contraindication, explanation
    if confidence < 0.90:
        return "unknown", None, confidence, reason_code or "low_confidence", explanation
    return decision, final_type, confidence, reason_code or decision, explanation


def validate_classifier_review(
    validated: tuple[str, str | None, float, str, str], predicted_type: str
) -> tuple[bool, str]:
    decision, final_type, confidence, _, _ = validated
    if decision == "unknown":
        return False, "model_unknown"
    if confidence < 0.95:
        return False, "model_confidence_below_review_gate"
    if decision != "retype" or final_type != predicted_type:
        return False, "classifier_model_disagreement"
    return True, "classifier_model_consensus"


def validate_model_second_review(
    validated: tuple[str, str | None, float, str, str], prior_type: str,
    prior_confidence: float = 1.0,
) -> tuple[bool, str]:
    decision, final_type, confidence, _, _ = validated
    if decision == "unknown":
        return False, "second_model_unknown"
    if prior_confidence < 0.95:
        return False, "prior_model_confidence_below_review_gate"
    if confidence < 0.95:
        return False, "second_model_confidence_below_review_gate"
    if final_type != prior_type:
        return False, "model_model_disagreement"
    return True, "model_model_consensus"


def validate_event_time_result(result: dict, candidate_ids: set[str]) -> tuple[list[str], list[str], list[str], float, str, str]:
    accepted = [str(value) for value in result.get("accepted_fact_ids", [])]
    rejected = [str(value) for value in result.get("rejected_fact_ids", [])]
    unknown = [str(value) for value in result.get("unknown_fact_ids", [])]
    if any(len(values) != len(set(values)) for values in (accepted, rejected, unknown)):
        raise ValueError("duplicate event time fact id")
    accepted_set, rejected_set, unknown_set = set(accepted), set(rejected), set(unknown)
    if (
        accepted_set.intersection(rejected_set)
        or accepted_set.intersection(unknown_set)
        or rejected_set.intersection(unknown_set)
    ):
        raise ValueError("event time decision lists must be disjoint")
    flattened = accepted + rejected + unknown
    if set(flattened) != candidate_ids or len(flattened) != len(candidate_ids):
        raise ValueError("event time decisions must partition all candidate fact ids")
    confidence = max(0.0, min(1.0, float(result.get("confidence") or 0.0)))
    reason_code = str(result.get("reason_code") or "").strip()[:120] or "event_time_adjudication"
    explanation = str(result.get("explanation") or "").strip()[:1000]
    if confidence < 0.90:
        unknown = sorted(candidate_ids)
        accepted = []
        rejected = []
    return accepted, rejected, unknown, confidence, reason_code, explanation


def call_qwen(endpoint: str, key: str, prompt: str, timeout: int) -> str:
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "/no_think 你是中文时空知识图谱语义裁决器。一次只处理一个事件，只输出JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 900,
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
    return raw


def ensure_runtime_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        create table if not exists v2_model_failures(
          failure_id text primary key,
          task_id text not null references v2_model_tasks(task_id),
          attempt integer not null check(attempt between 1 and 30),
          model text not null,
          prompt_version text not null,
          error_type text not null,
          error_message text not null,
          raw_response text not null,
          created_at text not null
        ) without rowid;
        create index if not exists idx_v2_model_failures_task
          on v2_model_failures(task_id,attempt);
        """
    )


def claim_task(con: sqlite3.Connection, task_type: str | None, task_id: str | None) -> sqlite3.Row | None:
    con.execute("begin immediate")
    if task_id:
        task = con.execute(
            "select * from v2_model_tasks where task_id=? and status in ('pending','retryable_error') and attempts<?",
            (task_id, MAX_ATTEMPTS),
        ).fetchone()
    else:
        sql = (
            "select * from v2_model_tasks where status in ('pending','retryable_error') and attempts<? "
            + ("and task_type=? " if task_type else "")
            + "order by case status when 'pending' then 0 else 1 end,priority,created_at,task_id limit 1"
        )
        params = (MAX_ATTEMPTS, task_type) if task_type else (MAX_ATTEMPTS,)
        task = con.execute(sql, params).fetchone()
    if not task:
        con.rollback()
        return None
    now = datetime.now().isoformat(timespec="seconds")
    con.execute(
        "update v2_model_tasks set status='processing',attempts=attempts+1,updated_at=? where task_id=?",
        (now, task["task_id"]),
    )
    con.commit()
    return task


def process_one(database: Path, task_type: str | None, task_id: str | None, timeout: int) -> dict:
    endpoint, key = api_config()
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    ensure_runtime_schema(con)
    task = claim_task(con, task_type, task_id)
    if not task:
        con.close()
        return {"status": "no_task"}
    raw = ""
    try:
        if task["task_type"] in {
            "entity_type", CLASSIFIER_REVIEW_TASK, MODEL_SECOND_REVIEW_TASK
        }:
            prompt = build_entity_prompt(con, task)
        elif task["task_type"] == "event_occurrence_time_adjudication":
            prompt = build_event_time_prompt(con, task)
        else:
            raise ValueError(f"unsupported task type: {task['task_type']}")
        raw = call_qwen(endpoint, key, prompt, timeout)
        parsed = parse_response(raw)
        now = datetime.now().isoformat(timespec="seconds")
        decision_id = stable_id("V2DEC", task["task_id"], int(task["attempts"]) + 1, PROMPT_VERSION)
        if task["task_type"] in {
            "entity_type", CLASSIFIER_REVIEW_TASK, MODEL_SECOND_REVIEW_TASK
        }:
            entity = con.execute(
                "select source_entity_type,canonical_name from v2_entities where entity_id=?",
                (task["unit_id"],)
            ).fetchone()
            entity_result = validate_entity_result(
                parsed, str(entity[0]), str(entity[1])
            )
            decision, final_type, confidence, reason_code, explanation = entity_result
            validated = {
                "decision": decision, "final_type": final_type, "confidence": confidence,
                "reason_code": reason_code, "explanation": explanation,
            }
            review_accepted = True
            if task["task_type"] == CLASSIFIER_REVIEW_TASK:
                payload = json.loads(task["payload_json"])
                predicted_type = str(payload["classifier_predicted_type"])
                review_accepted, review_outcome = validate_classifier_review(
                    entity_result, predicted_type
                )
                validated.update({
                    "classifier_predicted_type": predicted_type,
                    "classifier_confidence": payload.get("classifier_confidence"),
                    "review_outcome": review_outcome,
                    "review_accepted": review_accepted,
                })
            elif task["task_type"] == MODEL_SECOND_REVIEW_TASK:
                payload = json.loads(task["payload_json"])
                prior_type = str(payload["prior_model_type"])
                review_accepted, review_outcome = validate_model_second_review(
                    entity_result, prior_type, float(payload.get("prior_confidence") or 0.0)
                )
                validated.update({
                    "prior_model_type": prior_type,
                    "prior_decision_id": payload.get("prior_decision_id"),
                    "review_outcome": review_outcome,
                    "review_accepted": review_accepted,
                })
            if decision == "unknown" or not review_accepted:
                task_status = "manual_review"
                source_type = str(entity[0])
                con.execute(
                    "update v2_entities set semantic_entity_type=null,semantic_status='manual_review',"
                    "confidence=?,risk_tier='D',decision_sources_json=json_insert(decision_sources_json,'$[#]',?),"
                    "risk_flags_json=json_insert(risk_flags_json,'$[#]','model_unknown'),updated_at=?,"
                    "semantic_family=?,type_facets_json=? where entity_id=?",
                    (
                        confidence, f"{MODEL}:{PROMPT_VERSION}", now,
                        semantic_family(source_type),
                        json.dumps(type_facets(source_type), ensure_ascii=False), task["unit_id"],
                    ),
                )
                if task["task_type"] in {CLASSIFIER_REVIEW_TASK, MODEL_SECOND_REVIEW_TASK}:
                    con.execute(
                        "update v2_model_tasks set status='manual_review',updated_at=? "
                        "where unit_kind='entity' and unit_id=? and task_type='entity_type'",
                        (now, task["unit_id"]),
                    )
            else:
                task_status = "completed"
                decision_source = f"{MODEL}:{PROMPT_VERSION}"
                if task["task_type"] == CLASSIFIER_REVIEW_TASK:
                    payload = json.loads(task["payload_json"])
                    decision_source += f"+{payload.get('classifier_model_version', 'classifier')}"
                elif task["task_type"] == MODEL_SECOND_REVIEW_TASK:
                    decision_source += "+independent_model_second_review"
                con.execute(
                    "update v2_entities set semantic_entity_type=?,semantic_status='auto_accepted',"
                    "confidence=?,risk_tier='B',decision_sources_json=json_insert(decision_sources_json,'$[#]',?),"
                    "updated_at=?,semantic_family=?,type_facets_json=? where entity_id=?",
                    (
                        final_type, confidence, decision_source, now,
                        semantic_family(str(final_type)),
                        json.dumps(type_facets(str(final_type)), ensure_ascii=False), task["unit_id"],
                    ),
                )
                if task["task_type"] in {CLASSIFIER_REVIEW_TASK, MODEL_SECOND_REVIEW_TASK}:
                    con.execute(
                        "update v2_model_tasks set status='completed',updated_at=? "
                        "where unit_kind='entity' and unit_id=? and task_type='entity_type'",
                        (now, task["unit_id"]),
                    )
                con.execute(
                    "update v2_semantic_conflicts set status='resolved',resolution_decision_id=?,resolved_at=? "
                    "where unit_kind='entity' and unit_id=? and status='open' "
                    "and conflict_type<>'identity_ambiguity'",
                    (decision_id, now, task["unit_id"]),
                )
        else:
            payload = json.loads(task["payload_json"])
            candidate_ids = {str(item["fact_id"]) for item in payload.get("candidates", [])}
            accepted, rejected, unknown, confidence, reason_code, explanation = validate_event_time_result(
                parsed, candidate_ids
            )
            validated = {
                "accepted_fact_ids": accepted, "rejected_fact_ids": rejected,
                "unknown_fact_ids": unknown, "confidence": confidence,
                "reason_code": reason_code, "explanation": explanation,
            }
            task_status = "manual_review" if unknown else "completed"
            for fact_id in accepted:
                con.execute(
                    "update v2_assertion_scopes set semantic_status='auto_accepted',risk_tier='B',confidence=?,"
                    "decision_sources_json=json_insert(decision_sources_json,'$[#]',?),updated_at=? where fact_id=?",
                    (confidence, f"{MODEL}:{PROMPT_VERSION}", now, fact_id),
                )
            for fact_id in rejected:
                con.execute(
                    "update v2_assertion_scopes set time_role='context_time',time_owner_id=null,"
                    "semantic_status='auto_accepted',risk_tier='B',confidence=?,"
                    "decision_sources_json=json_insert(decision_sources_json,'$[#]',?),updated_at=? where fact_id=?",
                    (confidence, f"{MODEL}:{PROMPT_VERSION}", now, fact_id),
                )
            for fact_id in unknown:
                con.execute(
                    "update v2_assertion_scopes set semantic_status='manual_review',risk_tier='D',confidence=?,"
                    "decision_sources_json=json_insert(decision_sources_json,'$[#]',?),updated_at=? where fact_id=?",
                    (confidence, f"{MODEL}:{PROMPT_VERSION}", now, fact_id),
                )
            if not unknown:
                con.execute(
                    "update v2_semantic_conflicts set status='resolved',resolution_decision_id=?,resolved_at=? "
                    "where unit_kind='entity' and unit_id=? and conflict_type in "
                    "('controlled_event_time_year_conflict','raw_event_time_requires_review') and status='open'",
                    (decision_id, now, task["unit_id"]),
                )
        con.execute(
            "insert into v2_model_decisions values(?,?,?,?,?,?,?,?,?)",
            (
                decision_id, task["task_id"], MODEL, PROMPT_VERSION, raw,
                json.dumps(validated, ensure_ascii=False, sort_keys=True), 1,
                float(validated.get("confidence") or 0.0), now,
            ),
        )
        con.execute(
            "update v2_model_tasks set status=?,updated_at=? where task_id=?",
            (task_status, now, task["task_id"]),
        )
        con.commit()
        result = {
            "status": task_status,
            "task_id": task["task_id"],
            "task_type": task["task_type"],
            "decision": validated.get("decision", "partitioned_event_times"),
            "confidence": validated.get("confidence"),
            "model": MODEL,
        }
        con.close()
        return result
    except Exception as exc:
        now = datetime.now().isoformat(timespec="seconds")
        attempts = int(task["attempts"]) + 1
        status = "manual_review" if attempts >= MAX_ATTEMPTS else "retryable_error"
        try:
            con.rollback()
            failure_id = stable_id(
                "V2FAIL", task["task_id"], attempts, PROMPT_VERSION, type(exc).__name__
            )
            con.execute(
                "insert or replace into v2_model_failures values(?,?,?,?,?,?,?,?,?)",
                (
                    failure_id, task["task_id"], attempts, MODEL, PROMPT_VERSION,
                    type(exc).__name__, str(exc)[:2000], raw, now,
                ),
            )
            con.execute(
                "update v2_model_tasks set status=?,updated_at=? where task_id=?",
                (status, now, task["task_id"]),
            )
            con.commit()
        finally:
            con.close()
        return {
            "status": status,
            "task_id": task["task_id"],
            "task_type": task["task_type"],
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DATABASE)
    parser.add_argument(
        "--task-type",
        choices=(
            "entity_type", CLASSIFIER_REVIEW_TASK, MODEL_SECOND_REVIEW_TASK,
            "event_occurrence_time_adjudication",
        ),
    )
    parser.add_argument("--task-id")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    print(json.dumps(
        process_one(args.db, args.task_type, args.task_id, args.timeout), ensure_ascii=False
    ))


if __name__ == "__main__":
    main()
