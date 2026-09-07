"""Create the isolated V2 semantic repair ledger from the immutable V1 release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "stkg" / "config" / "stkg_v2_semantic_repair.yaml"

TIME_ROLES = (
    "event_occurrence",
    "relation_validity",
    "biographical",
    "creation_or_publication",
    "commemoration_or_reception",
    "source_document_time",
    "context_time",
    "unknown",
)
SPACE_ROLES = (
    "event_location",
    "relation_location",
    "biographical_location",
    "creation_or_publication_location",
    "commemoration_or_reception_location",
    "source_document_location",
    "context_location",
    "unknown",
)
SEMANTIC_STATUSES = ("pending", "auto_accepted", "model_review", "manual_review", "excluded")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_config(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("V2 semantic repair config must be a mapping")
    return value


def sql_enum(values: tuple[str, ...]) -> str:
    return ",".join("'" + value.replace("'", "''") + "'" for value in values)


def schema_sql() -> str:
    return f"""
    create table v2_metadata(
      key text primary key,
      value_json text not null check(json_valid(value_json))
    ) without rowid;

    create table v2_source_baseline(
      singleton integer primary key check(singleton=1),
      source_database text not null,
      source_sha256 text not null check(length(source_sha256)=64),
      source_size_bytes integer not null check(source_size_bytes>0),
      entity_count integer not null,
      assertion_count integer not null,
      provenance_count integer not null,
      event_entity_count integer not null,
      timed_assertion_count integer not null,
      assertion_with_place_count integer not null,
      captured_at text not null
    );

    create table v2_entities(
      entity_id text primary key,
      canonical_name text not null,
      source_entity_type text not null,
      semantic_entity_type text,
      member_count integer not null check(member_count>=1),
      aliases_json text not null check(json_valid(aliases_json)),
      semantic_status text not null default 'pending'
        check(semantic_status in ({sql_enum(SEMANTIC_STATUSES)})),
      confidence real check(confidence is null or confidence between 0 and 1),
      risk_tier text check(risk_tier is null or risk_tier in ('A','B','C','D')),
      decision_sources_json text not null default '[]' check(json_valid(decision_sources_json)),
      risk_flags_json text not null default '[]' check(json_valid(risk_flags_json)),
      method_version text,
      updated_at text,
      semantic_family text,
      type_facets_json text not null default '[]' check(json_valid(type_facets_json))
    ) without rowid;
    create index idx_v2_entity_status on v2_entities(semantic_status,risk_tier);
    create index idx_v2_entity_name on v2_entities(canonical_name,source_entity_type);

    create table v2_assertion_scopes(
      fact_id text primary key,
      subject_id text not null references v2_entities(entity_id),
      predicate text not null,
      object_id text not null references v2_entities(entity_id),
      source_subject_type text not null,
      source_object_type text not null,
      time_raw text,
      time_start text,
      time_end text,
      time_precision text not null,
      place_raw text,
      canonical_place_id text,
      subject_role text,
      object_role text,
      predicate_family text,
      predicate_direction text,
      time_role text not null default 'unknown' check(time_role in ({sql_enum(TIME_ROLES)})),
      time_owner_id text references v2_entities(entity_id),
      space_role text not null default 'unknown' check(space_role in ({sql_enum(SPACE_ROLES)})),
      space_owner_id text references v2_entities(entity_id),
      semantic_status text not null default 'pending'
        check(semantic_status in ({sql_enum(SEMANTIC_STATUSES)})),
      confidence real check(confidence is null or confidence between 0 and 1),
      risk_tier text check(risk_tier is null or risk_tier in ('A','B','C','D')),
      decision_sources_json text not null default '[]' check(json_valid(decision_sources_json)),
      risk_flags_json text not null default '[]' check(json_valid(risk_flags_json)),
      method_version text,
      updated_at text
    ) without rowid;
    create index idx_v2_assertion_status on v2_assertion_scopes(semantic_status,risk_tier);
    create index idx_v2_assertion_time_role on v2_assertion_scopes(time_role,time_owner_id);
    create index idx_v2_assertion_space_role on v2_assertion_scopes(space_role,space_owner_id);
    create index idx_v2_assertion_endpoints on v2_assertion_scopes(subject_id,object_id);

    create table v2_label_votes(
      vote_id text primary key,
      unit_kind text not null check(unit_kind in ('entity','assertion')),
      unit_id text not null,
      dimension text not null check(dimension in
        ('entity_type','subject_role','object_role','predicate_family','predicate_direction','time_role','time_owner','space_role','space_owner')),
      label_function text not null,
      proposed_value text,
      vote text not null check(vote in ('support','oppose','abstain')),
      weight real not null check(weight>0),
      rationale_code text not null,
      details_json text not null check(json_valid(details_json)),
      method_version text not null,
      created_at text not null,
      unique(unit_kind,unit_id,dimension,label_function,proposed_value)
    ) without rowid;
    create index idx_v2_votes_unit on v2_label_votes(unit_kind,unit_id,dimension);

    create table v2_semantic_conflicts(
      conflict_id text primary key,
      unit_kind text not null check(unit_kind in ('entity','assertion')),
      unit_id text not null,
      conflict_type text not null,
      severity text not null check(severity in ('warning','error','fatal')),
      details_json text not null check(json_valid(details_json)),
      status text not null check(status in ('open','resolved','accepted_unknown','excluded')),
      resolution_decision_id text,
      detected_at text not null,
      resolved_at text
    ) without rowid;
    create index idx_v2_conflicts on v2_semantic_conflicts(status,severity,conflict_type);

    create table v2_model_tasks(
      task_id text primary key,
      unit_kind text not null check(unit_kind in ('entity','assertion')),
      unit_id text not null,
      task_type text not null,
      payload_json text not null check(json_valid(payload_json)),
      status text not null check(status in ('pending','processing','completed','retryable_error','manual_review')),
      attempts integer not null default 0 check(attempts between 0 and 30),
      priority integer not null default 100,
      created_at text not null,
      updated_at text not null,
      unique(unit_kind,unit_id,task_type)
    ) without rowid;
    create index idx_v2_model_queue on v2_model_tasks(status,priority,created_at);

    create table v2_model_decisions(
      decision_id text primary key,
      task_id text not null references v2_model_tasks(task_id),
      model text not null,
      prompt_version text not null,
      raw_response text not null,
      decision_json text not null check(json_valid(decision_json)),
      validator_pass integer not null check(validator_pass in (0,1)),
      confidence real check(confidence is null or confidence between 0 and 1),
      created_at text not null
    ) without rowid;
    create index idx_v2_model_decisions_task on v2_model_decisions(task_id,created_at);

    create table v2_model_failures(
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
    create index idx_v2_model_failures_task on v2_model_failures(task_id,attempt);

    create table v2_rule_resolutions(
      resolution_id text primary key,
      task_id text not null,
      unit_id text not null,
      rule_name text not null,
      before_json text not null check(json_valid(before_json)),
      after_json text not null check(json_valid(after_json)),
      created_at text not null
    ) without rowid;
    create index idx_v2_rule_resolutions_unit on v2_rule_resolutions(unit_id,rule_name);

    create table v2_build_events(
      event_id integer primary key autoincrement,
      phase text not null,
      action text not null,
      result text not null check(result in ('PASS','FAIL','INFO')),
      metrics_json text not null check(json_valid(metrics_json)),
      created_at text not null
    );
    """


def source_counts(con: sqlite3.Connection) -> dict[str, int]:
    queries = {
        "entities": "select count(*) from src.stkg_entities",
        "assertions": "select count(*) from src.stkg_assertions",
        "provenance": "select count(*) from src.stkg_assertion_provenance",
        "event_entities": "select count(*) from src.stkg_entities where entity_type='Event'",
        "timed_assertions": "select count(*) from src.stkg_assertions where time_start is not null",
        "assertions_with_place": "select count(*) from src.stkg_assertion_place_links",
    }
    return {key: int(con.execute(sql).fetchone()[0]) for key, sql in queries.items()}


def validate_counts(actual: dict[str, int], expected: dict[str, object]) -> list[str]:
    return [
        f"{key}: expected {int(value)}, got {actual.get(key)}"
        for key, value in expected.items()
        if actual.get(key) != int(value)
    ]


def work_counts(con: sqlite3.Connection) -> dict[str, int]:
    return {
        "entities": int(con.execute("select count(*) from v2_entities").fetchone()[0]),
        "assertions": int(con.execute("select count(*) from v2_assertion_scopes").fetchone()[0]),
        "pending_entities": int(con.execute("select count(*) from v2_entities where semantic_status='pending'").fetchone()[0]),
        "pending_assertions": int(con.execute("select count(*) from v2_assertion_scopes where semantic_status='pending'").fetchone()[0]),
        "premature_final_entity_types": int(con.execute("select count(*) from v2_entities where semantic_entity_type is not null").fetchone()[0]),
        "premature_time_owners": int(con.execute("select count(*) from v2_assertion_scopes where time_owner_id is not null").fetchone()[0]),
        "premature_space_owners": int(con.execute("select count(*) from v2_assertion_scopes where space_owner_id is not null").fetchone()[0]),
    }


def write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.unlink(missing_ok=True)
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def initialize(source: Path, destination: Path, version: str, expected: dict[str, object]) -> dict:
    source = source.resolve()
    destination = destination.resolve()
    if source == destination:
        raise ValueError("V2 work database must differ from the immutable V1 source")
    if not source.is_file():
        raise FileNotFoundError(source)
    source_before = {
        "size_bytes": source.stat().st_size,
        "mtime_ns": source.stat().st_mtime_ns,
        "sha256": sha256(source),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(temporary) + suffix).unlink(missing_ok=True)

    con = sqlite3.connect(str(temporary), timeout=120)
    con.execute("pragma foreign_keys=on")
    con.execute("pragma journal_mode=delete")
    con.execute("pragma synchronous=full")
    try:
        con.execute("attach database ? as src", (f"file:{source.as_posix()}?mode=ro",))
        source_quick_check = str(con.execute("pragma src.quick_check").fetchone()[0])
        source_foreign_key_errors = len(con.execute("pragma src.foreign_key_check").fetchall())
        counts = source_counts(con)
        failures = validate_counts(counts, expected)
        if source_quick_check != "ok":
            failures.append(f"source_quick_check={source_quick_check}")
        if source_foreign_key_errors:
            failures.append(f"source_foreign_key_errors={source_foreign_key_errors}")
        if failures:
            raise RuntimeError("V2 source baseline failed: " + "; ".join(failures))

        con.executescript(schema_sql())
        captured_at = datetime.now().isoformat(timespec="seconds")
        con.execute("begin immediate")
        con.execute(
            "insert into v2_source_baseline values(1,?,?,?,?,?,?,?,?,?,?)",
            (
                str(source), source_before["sha256"], source_before["size_bytes"],
                counts["entities"], counts["assertions"], counts["provenance"],
                counts["event_entities"], counts["timed_assertions"],
                counts["assertions_with_place"], captured_at,
            ),
        )
        metadata = {
            "version": version,
            "source_database": str(source),
            "source_sha256": source_before["sha256"],
            "created_at": captured_at,
            "layer_contract": ["L0 SourceRecord", "L1 RawAssertion", "L2 CanonicalEntity", "L3 ScopedAssertion"],
            "source_mode": "read_only",
        }
        con.executemany(
            "insert into v2_metadata values(?,?)",
            [(key, json.dumps(value, ensure_ascii=False)) for key, value in metadata.items()],
        )
        con.execute(
            "insert into v2_entities(entity_id,canonical_name,source_entity_type,member_count,aliases_json) "
            "select entity_id,canonical_name,entity_type,member_count,aliases_json from src.stkg_entities"
        )
        con.execute(
            "insert into v2_assertion_scopes("
            "fact_id,subject_id,predicate,object_id,source_subject_type,source_object_type,"
            "time_raw,time_start,time_end,time_precision,place_raw,canonical_place_id) "
            "select a.fact_id,a.subject_id,a.predicate,a.object_id,s.entity_type,o.entity_type,"
            "a.time_raw,a.time_start,a.time_end,a.time_precision,a.place_raw,a.canonical_place_id "
            "from src.stkg_assertions a "
            "join src.stkg_entities s on s.entity_id=a.subject_id "
            "join src.stkg_entities o on o.entity_id=a.object_id"
        )
        staged_counts = work_counts(con)
        work_failures = []
        for key in ("entities", "assertions"):
            if staged_counts[key] != counts[key]:
                work_failures.append(f"work_{key}: expected {counts[key]}, got {staged_counts[key]}")
        for key in ("premature_final_entity_types", "premature_time_owners", "premature_space_owners"):
            if staged_counts[key] != 0:
                work_failures.append(f"{key}: expected 0, got {staged_counts[key]}")
        if work_failures:
            raise RuntimeError("V2 work ledger failed: " + "; ".join(work_failures))
        con.execute(
            "insert into v2_build_events(phase,action,result,metrics_json,created_at) values(?,?,?,?,?)",
            ("A", "initialize_v2_semantic_ledger", "PASS", json.dumps(staged_counts), captured_at),
        )
        con.commit()
        work_quick_check = str(con.execute("pragma quick_check").fetchone()[0])
        work_foreign_key_errors = len(con.execute("pragma foreign_key_check").fetchall())
        if work_quick_check != "ok" or work_foreign_key_errors:
            raise RuntimeError(
                f"V2 work database integrity failed: quick_check={work_quick_check}, "
                f"foreign_key_errors={work_foreign_key_errors}"
            )
    except Exception:
        con.rollback()
        con.close()
        temporary.unlink(missing_ok=True)
        raise
    else:
        con.close()

    source_after = {
        "size_bytes": source.stat().st_size,
        "mtime_ns": source.stat().st_mtime_ns,
        "sha256": sha256(source),
    }
    if source_after != source_before:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("immutable V1 source changed during V2 initialization")
    os.replace(temporary, destination)
    return {
        "source": source_before,
        "source_counts": counts,
        "source_quick_check": source_quick_check,
        "source_foreign_key_errors": source_foreign_key_errors,
        "work_counts": staged_counts,
        "work_quick_check": work_quick_check,
        "work_foreign_key_errors": work_foreign_key_errors,
        "work_sha256": sha256(destination),
        "work_size_bytes": destination.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args()
    config = load_config(args.config)
    if config.get("input", {}).get("mode") != "read_only":
        raise RuntimeError("V2 initialization requires read_only source mode")
    source = resolve_path(str(config["input"]["database"]))
    destination = resolve_path(str(config["outputs"]["semantic_work_database"]))
    report_path = resolve_path(str(config["outputs"]["baseline_report"]))
    expected_source_hash = str(config["input"]["sha256"])
    actual_source_hash = sha256(source)
    if actual_source_hash != expected_source_hash:
        raise RuntimeError(
            f"V1 source hash mismatch: expected {expected_source_hash}, got {actual_source_hash}"
        )
    result = initialize(source, destination, str(config["version"]), config["expected"])
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "result": "PASS",
        "version": str(config["version"]),
        "research_objective": str(config["research_objective"]),
        "input": {
            "database": str(source),
            "mode": "read_only",
            "sha256": result["source"]["sha256"],
            "size_bytes": result["source"]["size_bytes"],
        },
        "source_database_checks": {
            "quick_check": result["source_quick_check"],
            "foreign_key_errors": result["source_foreign_key_errors"],
            "counts": result["source_counts"],
        },
        "output": {
            "database": str(destination),
            "sha256": result["work_sha256"],
            "size_bytes": result["work_size_bytes"],
        },
        "work_database_checks": {
            "quick_check": result["work_quick_check"],
            "foreign_key_errors": result["work_foreign_key_errors"],
            "counts": result["work_counts"],
        },
        "guarantees": [
            "V1 source opened read-only and hash unchanged",
            "all V1 entities and assertions have V2 ledger rows",
            "no source type or adjacent date was accepted as final semantics during initialization",
            "unknown and pending are explicit valid states",
        ],
        "failures": [],
    }
    write_json_atomic(report_path, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
