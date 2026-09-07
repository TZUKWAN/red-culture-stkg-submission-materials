"""Adjudicate one exact-name entity cluster without applying a single review."""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

base_worker = importlib.import_module("257_qwen_adjudicate_one_stkg_v2_task")
from stkg_contract import strong_entity_type_hint
from stkg_v2_semantics import (
    SPECIALIZED_TYPES,
    entity_model_contraindication,
    entity_context_contraindication,
    refine_lexical_hint,
    semantic_family,
    spatial_model_contraindication,
    strict_v2_entity_type_hint,
    type_facets,
)


DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
MODEL = base_worker.MODEL
MAX_ATTEMPTS = base_worker.MAX_ATTEMPTS
ENTITY_TYPES = base_worker.ENTITY_TYPES
FIRST_TASK = "entity_name_cluster_first_review"
SECOND_TASK = "entity_name_cluster_second_review"
PROMPT_VERSION = "stkg-v2-name-cluster-adjudication-10"

AMBIGUITY_PATTERNS = (
    r"可能(?:是|属于)", r"也可能", r"无法(?:确定|区分|判断)",
    r"难以(?:确定|区分|判断)", r"信息不足", r"上下文不足",
    r"(?:均|都)(?:合理|可行|可能)",
)


def cluster_members(con: sqlite3.Connection, cluster_id: str) -> list[sqlite3.Row]:
    return con.execute(
        "select e.* from v2_name_cluster_members m join v2_entities e "
        "on e.entity_id=m.entity_id where m.cluster_id=? order by e.entity_id",
        (cluster_id,),
    ).fetchall()


def member_context(con: sqlite3.Connection, entity_id: str, limit: int = 10) -> list[dict]:
    return base_worker.entity_context(con, entity_id)[:limit]


def build_prompt(con: sqlite3.Connection, task: sqlite3.Row) -> tuple[str, list[sqlite3.Row]]:
    payload = json.loads(task["payload_json"])
    cluster_id = str(payload["cluster_id"])
    cluster = con.execute(
        "select * from v2_name_clusters where cluster_id=?", (cluster_id,)
    ).fetchone()
    members = cluster_members(con, cluster_id)
    if not members:
        raise ValueError("name cluster has no members")
    round_number = 2 if task["task_type"] == SECOND_TASK else 1
    ordered = list(reversed(members)) if round_number == 2 else members
    member_key_by_id = {
        str(member["entity_id"]): f"M{index:03d}"
        for index, member in enumerate(members, start=1)
    }
    accepted_same_name = [
        {"type": row[0], "count": row[1]}
        for row in con.execute(
            "select coalesce(semantic_entity_type,source_entity_type),count(*) "
            "from v2_entities where canonical_name=? and semantic_status='auto_accepted' "
            "group by coalesce(semantic_entity_type,source_entity_type) order by 1",
            (cluster["canonical_name"],),
        )
    ]
    member_payload = []
    for member in ordered:
        name = str(member["canonical_name"])
        source_type = str(member["source_entity_type"])
        member_payload.append({
            "member_key": member_key_by_id[str(member["entity_id"])],
            "source_type": source_type,
            "aliases": json.loads(member["aliases_json"]),
            "source_member_count": member["member_count"],
            "strict_lexical_hint": refine_lexical_hint(
                name, source_type, strong_entity_type_hint(name)
            ),
            "relation_context": member_context(con, str(member["entity_id"])),
        })
    task_text = (
        "这是第二次独立反证复核。不要假设第一次判断正确；逐个寻找旧类型和直觉类型的反例。"
        if round_number == 2 else
        "这是第一次独立语义判断。逐个实体根据自身关系上下文判断，不要按多数旧标签投票。"
    )
    prompt = {
        "task": (
            task_text
            + "一次只处理一个完全同名的实体簇。相同名称可能是同一对象的重复节点，也可能是人物、事件、作品、文献等同名异物。"
            "不核查历史事实真假，不新增事实。source_type、strict_lexical_hint和same_name_accepted只是候选信号，不是真值。"
            "必须对每个member_key单独判断；上下文不足必须unknown，不能为了统一而统一。"
            "Organization是边界和结构明确的正式组织；SocialGroup是因共同身份、信念或行动而作为集体行动者出现的社会群体。"
            "民兵、群众、敌军、红军战士等未指明正式建制的泛称集体，有具体行动语境时应为SocialGroup；只表示抽象类别时才是Concept，不能标成Person或Organization。"
            "Person必须是具体人物。名称具有严格组织结构标志时，不能改成Document、Event等不同语义家族。"
            "工作组、护团等具有明确组织边界的名称应保留Organization，不得降级成宽泛SocialGroup。"
            "三大纪律八项注意是规范/文献/作品语义，苏维埃是制度、组织或概念语义，二者都不是SocialGroup。"
            "电台这类裸词可能同时指机构和设备；没有可拆分的单一指称时必须unknown，不能强选Organization或Artifact。"
            "中共党员等角色泛称不是单个具体Person；还乡团是有组织边界的Organization，不得降级为SocialGroup。"
            "三大队、四中队等编号建制是Organization；名称整体以成立结尾时表示成立事件，不是组织本身。"
            "读后感是Document；来源已为Place且以寨结尾的原子地名不能改成Organization。"
            "缴获、查获、没收、收缴等开头的动作结果短语不是单个Artifact；无法拆出具体物品实体时必须unknown。"
            "AdministrativeRegion/CulturalSite是Place子类，Institution是Organization子类，Organization是SocialGroup子类，Spirit/ValueFacet/Position是Concept子类。"
            "若更具体子类仍合理，应保留子类。identity_groups只列你能确认指向同一现实对象的ID组，不确定则留空。"
            "members只使用本簇短键M001等，不提供内部实体ID；必须原样返回每个member_key且不得增删。"
            "accepted_same_name_references只提供只读类型统计，其中没有待判断成员；严禁把这些参考项虚构成assignment或identity_group成员。"
        ),
        "review_round": round_number,
        "cluster_id": cluster_id,
        "canonical_name": cluster["canonical_name"],
        "members": member_payload,
        "accepted_same_name_references": accepted_same_name,
        "allowed_entity_types": sorted(ENTITY_TYPES),
        "output_schema": {
            "assignments": [{
                "member_key": "exact supplied M001-style key",
                "decision": "keep|retype|unknown",
                "final_type": "allowed type, or empty for unknown",
                "confidence": "0..1",
                "reason_code": "short snake_case",
                "explanation": "one concise Chinese sentence grounded in this member context",
            }],
            "identity_groups": [["member_key", "member_key"]],
            "cluster_explanation": "one concise Chinese sentence",
        },
    }
    return json.dumps(prompt, ensure_ascii=False, sort_keys=True), members


def call_qwen(endpoint: str, key: str, prompt: str, timeout: int, round_number: int) -> str:
    body = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "/no_think 你是中文知识图谱同名实体语义审计器。"
                    + ("执行独立反证复核。" if round_number == 2 else "执行首次独立判断。")
                    + "只输出JSON。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 5000,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def validate_cluster_result(
    result: dict,
    members: list[sqlite3.Row],
    contexts_by_entity: dict[str, list[dict]] | None = None,
) -> dict:
    contexts_by_entity = contexts_by_entity or {}
    member_by_id = {str(row["entity_id"]): row for row in members}
    member_key_to_id = {
        f"M{index:03d}": str(row["entity_id"])
        for index, row in enumerate(members, start=1)
    }
    cluster_source_types = {str(row["source_entity_type"]) for row in members}
    assignments = result.get("assignments")
    if not isinstance(assignments, list):
        raise ValueError("assignments must be a list")
    supplied_ids = [
        member_key_to_id.get(str(item.get("member_key") or ""), str(item.get("entity_id") or ""))
        for item in assignments
    ]
    if len(supplied_ids) != len(set(supplied_ids)) or set(supplied_ids) != set(member_by_id):
        raise ValueError("assignments must cover every cluster member exactly once")
    validated_assignments = []
    for item, supplied_id in zip(assignments, supplied_ids):
        entity_id = supplied_id
        member = member_by_id[entity_id]
        source_type = str(member["source_entity_type"])
        name = str(member["canonical_name"])
        decision = str(item.get("decision") or "").strip().lower()
        final_type = str(item.get("final_type") or "").strip() or None
        confidence = max(0.0, min(1.0, float(item.get("confidence") or 0.0)))
        reason_code = str(item.get("reason_code") or "").strip()[:120] or "cluster_review"
        explanation = str(item.get("explanation") or "").strip()[:1000]
        if decision not in {"keep", "retype", "unknown"}:
            raise ValueError("invalid cluster decision")
        if decision == "unknown":
            final_type = None
        else:
            if final_type not in ENTITY_TYPES:
                raise ValueError("invalid cluster final type")
            decision = "keep" if final_type == source_type else "retype"
            if any(re.search(pattern, explanation) for pattern in AMBIGUITY_PATTERNS):
                decision, final_type, confidence = "unknown", None, min(confidence, 0.5)
                reason_code = "ambiguous_explanation"
            contraindication = entity_model_contraindication(
                name, source_type, str(final_type or ""), cluster_source_types
            )
            if not contraindication:
                contraindication = entity_context_contraindication(
                    name,
                    source_type,
                    str(final_type or ""),
                    contexts_by_entity.get(entity_id, ()),
                )
            if contraindication:
                decision, final_type, confidence = "unknown", None, min(confidence, 0.5)
                reason_code = contraindication
        if confidence < 0.90 and decision != "unknown":
            decision, final_type = "unknown", None
            reason_code = "low_confidence"
        validated_assignments.append({
            "entity_id": entity_id,
            "decision": decision,
            "final_type": final_type,
            "confidence": confidence,
            "reason_code": reason_code,
            "explanation": explanation,
        })

    identity_groups = result.get("identity_groups") or []
    if not isinstance(identity_groups, list):
        raise ValueError("identity_groups must be a list")
    seen: set[str] = set()
    validated_groups = []
    identity_group_warnings = []
    for group in identity_groups:
        if not isinstance(group, list):
            identity_group_warnings.append("non_list_identity_group_dropped")
            continue
        ids = [member_key_to_id.get(str(value), str(value)) for value in group]
        if len(ids) < 2 or len(ids) != len(set(ids)) or not set(ids) <= set(member_by_id):
            identity_group_warnings.append("invalid_identity_group_dropped")
            continue
        if seen.intersection(ids):
            identity_group_warnings.append("overlapping_identity_group_dropped")
            continue
        seen.update(ids)
        validated_groups.append(sorted(ids))
    return {
        "assignments": sorted(validated_assignments, key=lambda item: item["entity_id"]),
        "identity_groups": sorted(validated_groups),
        "identity_group_warnings": identity_group_warnings,
        "cluster_explanation": str(result.get("cluster_explanation") or "").strip()[:1000],
    }


def compare_reviews(
    first: dict,
    second: dict,
    members: list[sqlite3.Row],
    contexts_by_entity: dict[str, list[dict]] | None = None,
) -> tuple[dict, dict]:
    contexts_by_entity = contexts_by_entity or {}
    first_by_id = {item["entity_id"]: item for item in first["assignments"]}
    second_by_id = {item["entity_id"]: item for item in second["assignments"]}
    accepted: dict[str, str] = {}
    unresolved: dict[str, str] = {}
    cluster_source_types = {str(row["source_entity_type"]) for row in members}
    for member in members:
        entity_id = str(member["entity_id"])
        left = first_by_id[entity_id]
        right = second_by_id[entity_id]
        final_type = left.get("final_type")
        if (
            left.get("decision") == "unknown"
            or right.get("decision") == "unknown"
            or not final_type
        ):
            unresolved[entity_id] = "one_or_both_reviews_unknown"
            continue
        if final_type != right.get("final_type"):
            unresolved[entity_id] = "review_type_disagreement"
            continue
        if float(left.get("confidence") or 0) < 0.95 or float(right.get("confidence") or 0) < 0.95:
            unresolved[entity_id] = "review_confidence_below_gate"
            continue
        source_type = str(member["source_entity_type"])
        contraindication = entity_model_contraindication(
            str(member["canonical_name"]), source_type, str(final_type), cluster_source_types
        )
        if not contraindication:
            contraindication = entity_context_contraindication(
                str(member["canonical_name"]),
                source_type,
                str(final_type),
                contexts_by_entity.get(entity_id, ()),
            )
        if contraindication:
            unresolved[entity_id] = contraindication
            continue
        if source_type in SPECIALIZED_TYPES and final_type != source_type:
            unresolved[entity_id] = "specialized_cross_type_requires_topic_audit"
            continue
        accepted[entity_id] = str(final_type)
    return accepted, unresolved


def latest_decision(con: sqlite3.Connection, task_id: str) -> dict:
    row = con.execute(
        "select decision_json from v2_model_decisions where task_id=? and validator_pass=1 "
        "order by created_at desc,decision_id desc limit 1",
        (task_id,),
    ).fetchone()
    if not row:
        raise ValueError("first review decision is missing")
    return json.loads(row[0])


def process_one(database: Path, task_type: str, task_id: str | None, timeout: int) -> dict:
    if task_type not in {FIRST_TASK, SECOND_TASK}:
        raise ValueError("unsupported name cluster task type")
    endpoint, key = base_worker.api_config()
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    base_worker.ensure_runtime_schema(con)
    task = base_worker.claim_task(con, task_type, task_id)
    if not task:
        con.close()
        return {"status": "no_task"}
    raw = ""
    try:
        prompt, members = build_prompt(con, task)
        round_number = 2 if task_type == SECOND_TASK else 1
        raw = call_qwen(endpoint, key, prompt, timeout, round_number)
        parsed = base_worker.parse_response(raw)
        contexts_by_entity = {
            str(member["entity_id"]): member_context(con, str(member["entity_id"]))
            for member in members
        }
        validated = validate_cluster_result(parsed, members, contexts_by_entity)
        now = datetime.now().isoformat(timespec="seconds")
        decision_id = base_worker.stable_id(
            "V2DEC", task["task_id"], int(task["attempts"]) + 1, PROMPT_VERSION
        )
        cluster_id = str(json.loads(task["payload_json"])["cluster_id"])
        accepted: dict[str, str] = {}
        unresolved: dict[str, str] = {}
        con.execute("begin immediate")
        if task_type == FIRST_TASK:
            second_task_id = base_worker.stable_id("V2TASK", cluster_id, SECOND_TASK)
            second_payload = dict(json.loads(task["payload_json"]))
            second_payload["review_round"] = 2
            con.execute(
                "insert or ignore into v2_model_tasks values(?,?,?,?,?,?,?,?,?,?)",
                (
                    second_task_id, "entity", task["unit_id"], SECOND_TASK,
                    json.dumps(second_payload, ensure_ascii=False, sort_keys=True),
                    "pending", 0, task["priority"], now, now,
                ),
            )
            con.execute(
                "update v2_name_clusters set status='pending_second',updated_at=? where cluster_id=?",
                (now, cluster_id),
            )
        else:
            first_task_id = base_worker.stable_id("V2TASK", cluster_id, FIRST_TASK)
            first = latest_decision(con, first_task_id)
            accepted, unresolved = compare_reviews(
                first, validated, members, contexts_by_entity
            )
            for member in members:
                entity_id = str(member["entity_id"])
                final_type = accepted.get(entity_id)
                if not final_type:
                    continue
                con.execute(
                    "update v2_entities set semantic_entity_type=?,semantic_status='auto_accepted',"
                    "confidence=0.95,risk_tier='B',semantic_family=?,type_facets_json=?,"
                    "decision_sources_json=json_insert(decision_sources_json,'$[#]',?),"
                    "method_version=?,updated_at=? where entity_id=? and semantic_status='model_review'",
                    (
                        final_type, semantic_family(final_type),
                        json.dumps(type_facets(final_type), ensure_ascii=False),
                        f"{MODEL}:{PROMPT_VERSION}:double_review", PROMPT_VERSION, now, entity_id,
                    ),
                )
                con.execute(
                    "update v2_model_tasks set status='completed',updated_at=? "
                    "where unit_kind='entity' and unit_id=? and task_type='entity_type' "
                    "and status='pending'",
                    (now, entity_id),
                )
                con.execute(
                    "update v2_semantic_conflicts set status='resolved',resolution_decision_id=?,"
                    "resolved_at=? where unit_kind='entity' and unit_id=? and status='open' "
                    "and conflict_type<>'identity_ambiguity'",
                    (decision_id, now, entity_id),
                )
            con.execute(
                "update v2_name_clusters set status=?,updated_at=? where cluster_id=?",
                ("completed" if not unresolved else "manual_review", now, cluster_id),
            )
            validated["double_review_accepted"] = accepted
            validated["double_review_unresolved"] = unresolved
        con.execute(
            "insert into v2_model_decisions values(?,?,?,?,?,?,?,?,?)",
            (
                decision_id, task["task_id"], MODEL, PROMPT_VERSION, raw,
                json.dumps(validated, ensure_ascii=False, sort_keys=True), 1,
                min((float(item["confidence"]) for item in validated["assignments"]), default=0.0),
                now,
            ),
        )
        con.execute(
            "update v2_model_tasks set status='completed',updated_at=? where task_id=?",
            (now, task["task_id"]),
        )
        con.commit()
        result = {
            "status": "completed",
            "task_id": task["task_id"],
            "task_type": task_type,
            "cluster_id": cluster_id,
            "member_count": len(members),
            "accepted_member_count": len(accepted),
            "unresolved_member_count": len(unresolved),
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
            failure_id = base_worker.stable_id(
                "V2FAIL", task["task_id"], attempts, PROMPT_VERSION, type(exc).__name__
            )
            con.execute(
                "insert or ignore into v2_model_failures values(?,?,?,?,?,?,?,?,?)",
                (
                    failure_id, task["task_id"], attempts, MODEL, PROMPT_VERSION,
                    type(exc).__name__, str(exc)[:2000], raw[-4000:], now,
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
            "task_type": task_type,
            "error_type": type(exc).__name__,
            "error": str(exc)[:1000],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DATABASE)
    parser.add_argument("--task-type", choices=(FIRST_TASK, SECOND_TASK), required=True)
    parser.add_argument("--task-id")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    result = process_one(args.db, args.task_type, args.task_id, args.timeout)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
