"""Apply deterministic label functions and risk-aware fusion to the V2 ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from stkg_contract import RELATIONS, strong_entity_type_hint  # noqa: E402
from stkg_v2_semantics import (  # noqa: E402
    classify_space_scope,
    classify_time_scope,
    fuse_entity_type,
    refine_lexical_hint,
    relation_roles,
)


CONFIG = ROOT / "stkg" / "config" / "stkg_v2_semantic_repair.yaml"
METHOD_VERSION = "stkg-v2-label-fusion-2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def load_config(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("V2 config must be a mapping")
    return value


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.unlink(missing_ok=True)
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def insert_batches(con: sqlite3.Connection, sql: str, rows, size: int = 5000) -> int:
    batch = []
    count = 0
    for row in rows:
        batch.append(row)
        count += 1
        if len(batch) >= size:
            con.executemany(sql, batch)
            batch.clear()
    if batch:
        con.executemany(sql, batch)
    return count


def collect_schema_votes(con: sqlite3.Connection) -> dict[str, Counter[str]]:
    votes: dict[str, Counter[str]] = defaultdict(Counter)
    for subject_id, predicate, object_id in con.execute(
        "select subject_id,predicate,object_id from v2_assertion_scopes where predicate not like 'raw:%'"
    ):
        spec = RELATIONS.get(str(predicate))
        if spec is None:
            continue
        if len(spec.source_types) == 1:
            votes[str(subject_id)][next(iter(spec.source_types))] += 1
        if len(spec.target_types) == 1:
            votes[str(object_id)][next(iter(spec.target_types))] += 1
    return votes


def label_entities(con: sqlite3.Connection, now: str) -> dict:
    schema_votes = collect_schema_votes(con)
    name_types = {
        str(name): int(type_count)
        for name, type_count in con.execute(
            "select canonical_name,count(distinct source_entity_type) from v2_entities group by canonical_name"
        )
    }
    vote_rows = []
    update_rows = []
    conflict_rows = []
    model_rows = []
    retypes = Counter()
    statuses = Counter()
    risks = Counter()
    for entity_id, name, source_type in con.execute(
        "select entity_id,canonical_name,source_entity_type from v2_entities order by entity_id"
    ):
        entity_id = str(entity_id)
        name = str(name)
        source_type = str(source_type)
        lexical = refine_lexical_hint(name, source_type, strong_entity_type_hint(name))
        per_entity_schema = schema_votes.get(entity_id, Counter())
        fusion = fuse_entity_type(source_type, lexical, per_entity_schema, name_types[name] > 1)
        vote_rows.append((
            stable_id("VOTE", "entity", entity_id, "entity_type", "source_type_prior", source_type),
            "entity", entity_id, "entity_type", "source_type_prior", source_type, "support", 1.0,
            "source_type_prior", "{}", METHOD_VERSION, now,
        ))
        if lexical:
            vote_rows.append((
                stable_id("VOTE", "entity", entity_id, "entity_type", "strong_lexical_hint", lexical),
                "entity", entity_id, "entity_type", "strong_lexical_hint", lexical, "support", 4.0,
                "strong_lexical_hint", json.dumps({"name": name}, ensure_ascii=False), METHOD_VERSION, now,
            ))
        if per_entity_schema:
            top_label, top_count = per_entity_schema.most_common(1)[0]
            weight = min(4.0, 1.0 + math.log1p(top_count))
            vote_rows.append((
                stable_id("VOTE", "entity", entity_id, "entity_type", "controlled_schema_votes", top_label),
                "entity", entity_id, "entity_type", "controlled_schema_votes", top_label, "support", weight,
                "controlled_schema_votes",
                json.dumps(dict(per_entity_schema), ensure_ascii=False, sort_keys=True), METHOD_VERSION, now,
            ))
        update_rows.append((
            fusion.final_type, fusion.status, fusion.confidence, fusion.risk_tier,
            json.dumps(fusion.decision_sources, ensure_ascii=False),
            json.dumps(fusion.risk_flags, ensure_ascii=False), METHOD_VERSION, now, entity_id,
        ))
        statuses[fusion.status] += 1
        risks[fusion.risk_tier] += 1
        if fusion.final_type and fusion.final_type != source_type:
            retypes[f"{source_type}->{fusion.final_type}"] += 1
        for flag in fusion.risk_flags:
            severity = "error" if flag in {"lexical_schema_conflict"} else "warning"
            conflict_id = stable_id("CONFLICT", "entity", entity_id, flag)
            conflict_rows.append((
                conflict_id, "entity", entity_id, flag, severity,
                json.dumps({"name": name, "source_type": source_type, "lexical_hint": lexical,
                            "schema_votes": dict(per_entity_schema)}, ensure_ascii=False),
                "open" if fusion.status == "model_review" else "resolved",
                None, now, None if fusion.status == "model_review" else now,
            ))
        if fusion.status == "model_review":
            payload = {
                "entity_id": entity_id,
                "name": name,
                "source_type": source_type,
                "lexical_hint": lexical,
                "schema_votes": dict(per_entity_schema),
                "risk_flags": list(fusion.risk_flags),
            }
            model_rows.append((
                stable_id("TASK", "entity", entity_id, "entity_type"), "entity", entity_id,
                "entity_type", json.dumps(payload, ensure_ascii=False), "pending", 0, 20, now, now,
            ))
    insert_batches(con, "insert into v2_label_votes values(?,?,?,?,?,?,?,?,?,?,?,?)", vote_rows)
    con.executemany(
        "update v2_entities set semantic_entity_type=?,semantic_status=?,confidence=?,risk_tier=?,"
        "decision_sources_json=?,risk_flags_json=?,method_version=?,updated_at=? where entity_id=?",
        update_rows,
    )
    insert_batches(con, "insert into v2_semantic_conflicts values(?,?,?,?,?,?,?,?,?,?)", conflict_rows)
    insert_batches(con, "insert into v2_model_tasks values(?,?,?,?,?,?,?,?,?,?)", model_rows)
    return {
        "statuses": dict(statuses),
        "risk_tiers": dict(risks),
        "retypes": dict(sorted(retypes.items())),
        "label_votes": len(vote_rows),
        "conflicts": len(conflict_rows),
        "model_tasks": len(model_rows),
    }


def label_assertions(con: sqlite3.Connection, now: str) -> dict:
    entity_types = {
        str(entity_id): (str(final_type) if final_type else str(source_type), str(status))
        for entity_id, source_type, final_type, status in con.execute(
            "select entity_id,source_entity_type,semantic_entity_type,semantic_status from v2_entities"
        )
    }
    vote_rows = []
    update_rows = []
    conflict_rows = []
    statuses = Counter()
    risks = Counter()
    time_roles = Counter()
    space_roles = Counter()
    for row in con.execute(
        "select fact_id,subject_id,predicate,object_id,time_start,canonical_place_id "
        "from v2_assertion_scopes order by fact_id"
    ):
        fact_id, subject_id, predicate, object_id, time_start, place_id = map(
            lambda value: None if value is None else str(value), row
        )
        subject_type, subject_status = entity_types[subject_id]
        object_type, object_status = entity_types[object_id]
        time_label = classify_time_scope(
            predicate, time_start, subject_id, subject_type, object_id, object_type
        )
        space_label = classify_space_scope(
            predicate, place_id, subject_id, subject_type, object_id, object_type
        )
        subject_role, object_role, family, direction = relation_roles(predicate)
        endpoint_unresolved = subject_status != "auto_accepted" or object_status != "auto_accepted"
        risk = "C" if endpoint_unresolved else max(time_label.risk_tier, space_label.risk_tier)
        status = "model_review" if endpoint_unresolved else "auto_accepted"
        confidence = min(time_label.confidence, space_label.confidence)
        flags = []
        if endpoint_unresolved:
            flags.append("unresolved_endpoint_entity_type")
        if predicate.startswith("raw:"):
            flags.append("raw_predicate_context_only")
        sources = [time_label.rationale, space_label.rationale, "controlled_predicate" if not predicate.startswith("raw:") else "raw_predicate"]
        update_rows.append((
            subject_role, object_role, family, direction,
            time_label.role, time_label.owner_id, space_label.role, space_label.owner_id,
            status, confidence, risk, json.dumps(sources, ensure_ascii=False),
            json.dumps(flags, ensure_ascii=False), METHOD_VERSION, now, fact_id,
        ))
        if time_start:
            vote_rows.append((
                stable_id("VOTE", "assertion", fact_id, "time_role", time_label.rationale, time_label.role),
                "assertion", fact_id, "time_role", time_label.rationale, time_label.role, "support",
                time_label.confidence, time_label.rationale, "{}", METHOD_VERSION, now,
            ))
        if place_id:
            vote_rows.append((
                stable_id("VOTE", "assertion", fact_id, "space_role", space_label.rationale, space_label.role),
                "assertion", fact_id, "space_role", space_label.rationale, space_label.role, "support",
                space_label.confidence, space_label.rationale, "{}", METHOD_VERSION, now,
            ))
        vote_rows.append((
            stable_id("VOTE", "assertion", fact_id, "predicate_family", "predicate_route", family),
            "assertion", fact_id, "predicate_family", "predicate_route", family, "support", 1.0,
            "controlled_or_raw_route", "{}", METHOD_VERSION, now,
        ))
        if endpoint_unresolved:
            conflict_rows.append((
                stable_id("CONFLICT", "assertion", fact_id, "unresolved_endpoint_entity_type"),
                "assertion", fact_id, "unresolved_endpoint_entity_type", "error",
                json.dumps({"subject_status": subject_status, "object_status": object_status}, ensure_ascii=False),
                "open", None, now, None,
            ))
        statuses[status] += 1
        risks[risk] += 1
        time_roles[time_label.role] += 1
        space_roles[space_label.role] += 1
        if len(vote_rows) >= 20000:
            insert_batches(con, "insert into v2_label_votes values(?,?,?,?,?,?,?,?,?,?,?,?)", vote_rows)
            vote_rows.clear()
        if len(update_rows) >= 10000:
            con.executemany(
                "update v2_assertion_scopes set subject_role=?,object_role=?,predicate_family=?,predicate_direction=?,"
                "time_role=?,time_owner_id=?,space_role=?,space_owner_id=?,semantic_status=?,confidence=?,risk_tier=?,"
                "decision_sources_json=?,risk_flags_json=?,method_version=?,updated_at=? where fact_id=?",
                update_rows,
            )
            update_rows.clear()
        if len(conflict_rows) >= 5000:
            insert_batches(con, "insert into v2_semantic_conflicts values(?,?,?,?,?,?,?,?,?,?)", conflict_rows)
            conflict_rows.clear()
    if vote_rows:
        insert_batches(con, "insert into v2_label_votes values(?,?,?,?,?,?,?,?,?,?,?,?)", vote_rows)
    if update_rows:
        con.executemany(
            "update v2_assertion_scopes set subject_role=?,object_role=?,predicate_family=?,predicate_direction=?,"
            "time_role=?,time_owner_id=?,space_role=?,space_owner_id=?,semantic_status=?,confidence=?,risk_tier=?,"
            "decision_sources_json=?,risk_flags_json=?,method_version=?,updated_at=? where fact_id=?",
            update_rows,
        )
    if conflict_rows:
        insert_batches(con, "insert into v2_semantic_conflicts values(?,?,?,?,?,?,?,?,?,?)", conflict_rows)
    return {
        "statuses": dict(statuses),
        "risk_tiers": dict(risks),
        "time_roles": dict(time_roles),
        "space_roles": dict(space_roles),
    }


def route_event_time_conflicts(con: sqlite3.Connection, now: str) -> dict:
    grouped = defaultdict(list)
    for row in con.execute(
        "select fact_id,time_owner_id,predicate,time_start,time_end,risk_tier,semantic_status "
        "from v2_assertion_scopes where time_role='event_occurrence' order by time_owner_id,time_start,fact_id"
    ):
        grouped[str(row[1])].append(tuple(None if value is None else str(value) for value in row))
    raw_routed = 0
    conflict_owners = 0
    conflict_assertions = 0
    task_rows = []
    conflict_rows = []
    for owner_id, rows in grouped.items():
        controlled_rows = [row for row in rows if not row[2].startswith("raw:") and row[5] == "A"]
        controlled_start_years = {row[3][:4] for row in controlled_rows if row[3]}
        broad_controlled = any(
            row[3] and row[4] and row[3][:4].isdigit() and row[4][:4].isdigit()
            and int(row[4][:4]) - int(row[3][:4]) > 2
            for row in controlled_rows
        )
        controlled_conflict = len(controlled_start_years) > 1 or broad_controlled
        raw_fact_ids = [row[0] for row in rows if row[2].startswith("raw:")]
        affected = [row[0] for row in controlled_rows] if controlled_conflict else []
        affected.extend(raw_fact_ids)
        affected = sorted(set(affected))
        if not affected:
            continue
        if controlled_conflict:
            conflict_owners += 1
            conflict_assertions += len(set(row[0] for row in controlled_rows))
        raw_routed += len(raw_fact_ids)
        con.executemany(
            "update v2_assertion_scopes set semantic_status='model_review',risk_tier='C',"
            "risk_flags_json=json_insert(risk_flags_json,'$[#]',?),updated_at=? where fact_id=?",
            [
                ("event_occurrence_time_conflict" if controlled_conflict else "raw_event_time_requires_review", now, fact_id)
                for fact_id in affected
            ],
        )
        task_type = "event_occurrence_time_adjudication"
        payload = {
            "event_id": owner_id,
            "controlled_year_conflict": controlled_conflict,
            "candidates": [
                {
                    "fact_id": row[0], "predicate": row[2], "time_start": row[3],
                    "time_end": row[4], "source_risk_tier": row[5],
                }
                for row in rows
            ],
        }
        task_rows.append((
            stable_id("TASK", "entity", owner_id, task_type), "entity", owner_id, task_type,
            json.dumps(payload, ensure_ascii=False), "pending", 0, 10, now, now,
        ))
        conflict_type = "controlled_event_time_year_conflict" if controlled_conflict else "raw_event_time_requires_review"
        conflict_rows.append((
            stable_id("CONFLICT", "entity", owner_id, conflict_type), "entity", owner_id,
            conflict_type, "error", json.dumps(payload, ensure_ascii=False), "open", None, now, None,
        ))
    if task_rows:
        insert_batches(con, "insert into v2_model_tasks values(?,?,?,?,?,?,?,?,?,?)", task_rows)
    if conflict_rows:
        insert_batches(con, "insert into v2_semantic_conflicts values(?,?,?,?,?,?,?,?,?,?)", conflict_rows)
    return {
        "raw_event_time_assertions_routed": raw_routed,
        "controlled_conflict_event_owners": conflict_owners,
        "controlled_conflict_assertions_routed": conflict_assertions,
        "event_time_model_tasks": len(task_rows),
    }


def collect_assertion_metrics(con: sqlite3.Connection, closure: dict) -> dict:
    def distribution(column: str) -> dict[str, int]:
        return {
            str(key): int(value)
            for key, value in con.execute(
                f"select {column},count(*) from v2_assertion_scopes group by {column} order by {column}"
            )
        }
    return {
        "statuses": distribution("semantic_status"),
        "risk_tiers": distribution("risk_tier"),
        "time_roles": distribution("time_role"),
        "space_roles": distribution("space_role"),
        "event_time_consistency_closure": closure,
    }


def validation_metrics(con: sqlite3.Connection) -> dict[str, int]:
    queries = {
        "pending_entities": "select count(*) from v2_entities where semantic_status='pending'",
        "pending_assertions": "select count(*) from v2_assertion_scopes where semantic_status='pending'",
        "timed_unknown": "select count(*) from v2_assertion_scopes where time_start is not null and time_role='unknown'",
        "untimed_scoped": "select count(*) from v2_assertion_scopes where time_start is null and time_role<>'unknown'",
        "event_occurrence_without_owner": "select count(*) from v2_assertion_scopes where time_role='event_occurrence' and time_owner_id is null",
        "participation_as_event_occurrence": "select count(*) from v2_assertion_scopes where predicate in ('participated_in','led','organized','commanded','carried_out') and time_role='event_occurrence'",
        "generic_raw_as_event_occurrence": "select count(*) from v2_assertion_scopes where predicate in ('raw:关联','raw:时间关联') and time_role='event_occurrence'",
        "event_occurrence_owner_not_event": (
            "select count(*) from v2_assertion_scopes a join v2_entities e on e.entity_id=a.time_owner_id "
            "where a.time_role='event_occurrence' and coalesce(e.semantic_entity_type,e.source_entity_type)<>'Event'"
        ),
        "assertions_missing_roles": "select count(*) from v2_assertion_scopes where subject_role is null or object_role is null or predicate_family is null or predicate_direction is null",
        "open_fatal_conflicts": "select count(*) from v2_semantic_conflicts where status='open' and severity='fatal'",
        "model_attempts_over_30": "select count(*) from v2_model_tasks where attempts>30",
        "auto_event_occurrence_risk_not_a": (
            "select count(*) from v2_assertion_scopes where time_role='event_occurrence' "
            "and semantic_status='auto_accepted' and risk_tier<>'A'"
        ),
        "auto_event_occurrence_multi_year_owners": (
            "select count(*) from (select time_owner_id from v2_assertion_scopes "
            "where time_role='event_occurrence' and semantic_status='auto_accepted' "
            "group by time_owner_id having count(distinct substr(time_start,1,4))>1)"
        ),
    }
    return {key: int(con.execute(sql).fetchone()[0]) for key, sql in queries.items()}


def run(database: Path) -> dict:
    database = database.resolve()
    before_hash = sha256(database)
    temporary = database.with_name(f".{database.name}.label-fusion.tmp")
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(temporary) + suffix).unlink(missing_ok=True)
    shutil.copyfile(database, temporary)
    con = sqlite3.connect(str(temporary), timeout=120)
    con.execute("pragma foreign_keys=on")
    con.execute("pragma journal_mode=delete")
    con.execute("pragma synchronous=full")
    now = datetime.now().isoformat(timespec="seconds")
    try:
        con.execute("begin immediate")
        con.execute("delete from v2_label_votes")
        con.execute("delete from v2_semantic_conflicts")
        con.execute("delete from v2_model_decisions")
        con.execute("delete from v2_model_tasks")
        con.execute(
            "update v2_entities set semantic_entity_type=null,semantic_status='pending',confidence=null,risk_tier=null,"
            "decision_sources_json='[]',risk_flags_json='[]',method_version=null,updated_at=null"
        )
        con.execute(
            "update v2_assertion_scopes set subject_role=null,object_role=null,predicate_family=null,predicate_direction=null,"
            "time_role='unknown',time_owner_id=null,space_role='unknown',space_owner_id=null,semantic_status='pending',"
            "confidence=null,risk_tier=null,decision_sources_json='[]',risk_flags_json='[]',method_version=null,updated_at=null"
        )
        entity_metrics = label_entities(con, now)
        label_assertions(con, now)
        event_time_closure = route_event_time_conflicts(con, now)
        assertion_metrics = collect_assertion_metrics(con, event_time_closure)
        checks = validation_metrics(con)
        failures = [f"{key}={value}" for key, value in checks.items() if value != 0]
        if failures:
            raise RuntimeError("V2 label fusion validation failed: " + "; ".join(failures))
        metrics = {"entities": entity_metrics, "assertions": assertion_metrics, "validation": checks}
        con.execute(
            "insert into v2_build_events(phase,action,result,metrics_json,created_at) values(?,?,?,?,?)",
            ("B-C", "label_and_fuse_semantics", "PASS", json.dumps(metrics, ensure_ascii=False), now),
        )
        con.commit()
        quick_check = str(con.execute("pragma quick_check").fetchone()[0])
        foreign_key_errors = len(con.execute("pragma foreign_key_check").fetchall())
        if quick_check != "ok" or foreign_key_errors:
            raise RuntimeError(f"V2 label fusion integrity failed: quick_check={quick_check}, foreign_key_errors={foreign_key_errors}")
    except Exception:
        con.rollback()
        con.close()
        temporary.unlink(missing_ok=True)
        raise
    else:
        con.close()
    if sha256(database) != before_hash:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("V2 input ledger changed before atomic replacement")
    os.replace(temporary, database)
    return {
        "input_sha256": before_hash,
        "output_sha256": sha256(database),
        "output_size_bytes": database.stat().st_size,
        "quick_check": quick_check,
        "foreign_key_errors": foreign_key_errors,
        **metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    config = load_config(args.config)
    database = resolve_path(str(config["outputs"]["semantic_work_database"]))
    baseline_report = json.loads(resolve_path(str(config["outputs"]["baseline_report"])).read_text(encoding="utf-8"))
    if baseline_report.get("result") != "PASS":
        raise RuntimeError("V2 baseline report is not PASS")
    current_hash = sha256(database)
    allowed_hashes = {str(baseline_report["output"]["sha256"])}
    prior_report_path = resolve_path(str(config["outputs"]["label_fusion_report"]))
    if prior_report_path.exists():
        prior_report = json.loads(prior_report_path.read_text(encoding="utf-8"))
        if prior_report.get("result") == "PASS":
            allowed_hashes.add(str(prior_report.get("output", {}).get("sha256", "")))
    if current_hash not in allowed_hashes:
        raise RuntimeError("V2 work database differs from all accepted PASS reports")
    result = run(database)
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "result": "PASS",
        "version": METHOD_VERSION,
        "input": {"database": str(database), "sha256": result["input_sha256"]},
        "output": {"database": str(database), "sha256": result["output_sha256"], "size_bytes": result["output_size_bytes"]},
        "database_checks": {"quick_check": result["quick_check"], "foreign_key_errors": result["foreign_key_errors"]},
        "entity_fusion": result["entities"],
        "assertion_fusion": result["assertions"],
        "semantic_validation": result["validation"],
        "limitations": [
            "model_review entities are unresolved and are not admitted to the strict semantic layer",
            "raw unscoped dates are context_time, not event occurrence time",
            "relation validity is distinct from event occurrence time",
            "no external historical fact verification is performed in this phase",
        ],
        "failures": [],
    }
    write_json_atomic(prior_report_path, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
