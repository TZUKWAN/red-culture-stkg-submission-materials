"""Full structural and stratified audit for the STKG V2 research release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from stkg_contract import RELATIONS, relation_type_allowed  # noqa: E402
from stkg_v2_semantics import TYPE_PARENT  # noqa: E402


DEFAULT_DATABASE = ROOT / "derived" / "red_culture_stkg_final_v2.sqlite"
DEFAULT_JSON = ROOT / "audit_reports" / "stkg_v2_full_audit.json"
DEFAULT_MARKDOWN = ROOT / "audit_reports" / "stkg_v2_full_audit.md"
PROTECTED_V1 = ROOT / "releases" / "red_culture_stkg_v1" / "databases" / "red_culture_stkg_evolution_v1.sqlite"
PROTECTED_V1_SHA256 = "416578c5d3ae7d14193982d9d35f26c8b6e8665cd9b6399d47b67361ab1c48bd"
SEMANTIC_V2 = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REQUIRED_REPORTS = (
    "stkg_v2_research_base.json",
    "stkg_v2_event_culture.json",
    "stkg_v2_evolution.json",
    "stkg_v2_creative_media.json",
    "stkg_v2_final_materialization.json",
    "stkg_v2_competency_queries.json",
    "stkg_v2_graph_export.json",
    "stkg_v2_neo4j_import.json",
    "stkg_v2_neo4j_verification.json",
)
TIME_LABEL = re.compile(r"^\d{4}年(?:\d{1,2}月)?(?:-\d{4}年(?:\d{1,2}月)?)?$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def hierarchy_allowed(actual_type: object, allowed_types: frozenset[str]) -> bool:
    current = str(actual_type or "").strip()
    seen = set()
    while current and current not in seen:
        if relation_type_allowed(current, allowed_types):
            return True
        seen.add(current)
        current = TYPE_PARENT.get(current, "")
    return False


def relation_compatible(predicate: object, source_type: object, target_type: object) -> bool:
    relation = RELATIONS.get(str(predicate or "").strip())
    return bool(
        relation
        and hierarchy_allowed(source_type, relation.source_types)
        and hierarchy_allowed(target_type, relation.target_types)
    )


def canonical_time_label(label: str | None) -> bool:
    if label is None or not TIME_LABEL.fullmatch(label):
        return False
    if "日" in label or re.search(r"[〇零一二三四五六七八九十百千万两]", label):
        return False
    months = [int(value) for value in re.findall(r"(\d{1,2})月", label)]
    return all(1 <= month <= 12 for month in months)


def rows(con: sqlite3.Connection, sql: str) -> list[dict]:
    return [dict(row) for row in con.execute(sql)]


def stratified_samples(con: sqlite3.Connection) -> dict[str, list[dict]]:
    return {
        "entity_type": rows(con, """
            with ranked as (
              select entity_type stratum,entity_id,canonical_name,semantic_family,
                     row_number() over(partition by entity_type order by entity_id) rn
              from research_entities
            ) select stratum,entity_id,canonical_name,semantic_family from ranked where rn<=3 order by stratum,rn
        """),
        "research_tier": rows(con, """
            with ranked as (
              select research_tier stratum,fact_id,subject_name,predicate,object_name,
                     normalized_time_label,province,
                     row_number() over(partition by research_tier order by fact_id) rn
              from research_assertions
            ) select stratum,fact_id,subject_name,predicate,object_name,normalized_time_label,province
              from ranked where rn<=5 order by stratum,rn
        """),
        "time_role": rows(con, """
            with ranked as (
              select time_role stratum,fact_id,subject_name,predicate,object_name,normalized_time_label,
                     row_number() over(partition by time_role order by fact_id) rn
              from research_assertions
            ) select stratum,fact_id,subject_name,predicate,object_name,normalized_time_label
              from ranked where rn<=3 order by stratum,rn
        """),
        "space_role": rows(con, """
            with ranked as (
              select space_role stratum,fact_id,subject_name,predicate,object_name,place_raw,province,
                     row_number() over(partition by space_role order by fact_id) rn
              from research_assertions
            ) select stratum,fact_id,subject_name,predicate,object_name,place_raw,province
              from ranked where rn<=3 order by stratum,rn
        """),
        "historical_stage": rows(con, """
            with ranked as (
              select m.stage_code stratum,a.fact_id,a.subject_name,a.predicate,a.object_name,a.normalized_time_label,
                     row_number() over(partition by m.stage_code order by a.fact_id) rn
              from research_assertion_stage_memberships m join research_assertions a on a.fact_id=m.fact_id
            ) select stratum,fact_id,subject_name,predicate,object_name,normalized_time_label
              from ranked where rn<=3 order by stratum,rn
        """),
        "study_region": rows(con, """
            with ranked as (
              select r.province_name stratum,a.fact_id,a.subject_name,a.predicate,a.object_name,
                     row_number() over(partition by r.province_name order by a.fact_id) rn
              from research_assertion_regions m join research_study_regions r on r.region_id=m.region_id
              join research_assertions a on a.fact_id=m.fact_id
            ) select stratum,fact_id,subject_name,predicate,object_name
              from ranked where rn<=3 order by stratum,rn
        """),
        "culture_form": rows(con, """
            with ranked as (
              select c.culture_form_code stratum,e.entity_id,e.canonical_name,e.entity_type,c.culture_role,
                     row_number() over(partition by c.culture_form_code order by e.entity_id) rn
              from research_entity_culture_forms c join research_entities e on e.entity_id=c.entity_id
            ) select stratum,entity_id,canonical_name,entity_type,culture_role
              from ranked where rn<=3 order by stratum,rn
        """),
        "state_tier": rows(con, """
            with ranked as (
              select observation_tier stratum,state_id,stage_code,region_id,culture_form_code,supporting_event_count,
                     row_number() over(partition by observation_tier order by state_id) rn
              from research_culture_states
            ) select stratum,state_id,stage_code,region_id,culture_form_code,supporting_event_count
              from ranked where rn<=5 order by stratum,rn
        """),
        "creative_media": rows(con, """
            with ranked as (
              select m.media_type stratum,e.entity_id,e.canonical_name,m.classification_method,m.task_status,
                     row_number() over(partition by m.media_type order by e.entity_id) rn
              from research_creative_work_media m join research_entities e on e.entity_id=m.entity_id
            ) select stratum,entity_id,canonical_name,classification_method,task_status
              from ranked where rn<=2 order by stratum,rn
        """),
    }


def report_chain() -> tuple[dict, list[str]]:
    failures = []
    reports = {}
    for name in REQUIRED_REPORTS:
        path = ROOT / "audit_reports" / name
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append(f"cannot read {name}: {exc}")
            continue
        reports[name] = {"status": value.get("status"), "sha256": sha256(path)}
        if value.get("status") != "PASS":
            failures.append(f"required report is not PASS: {name}")
    final_path = DEFAULT_DATABASE
    if all((ROOT / "audit_reports" / name).is_file() for name in REQUIRED_REPORTS):
        research = json.loads((ROOT / "audit_reports" / "stkg_v2_research_base.json").read_text(encoding="utf-8"))
        event = json.loads((ROOT / "audit_reports" / "stkg_v2_event_culture.json").read_text(encoding="utf-8"))
        evolution = json.loads((ROOT / "audit_reports" / "stkg_v2_evolution.json").read_text(encoding="utf-8"))
        final = json.loads((ROOT / "audit_reports" / "stkg_v2_final_materialization.json").read_text(encoding="utf-8"))
        competency = json.loads((ROOT / "audit_reports" / "stkg_v2_competency_queries.json").read_text(encoding="utf-8"))
        graph = json.loads((ROOT / "audit_reports" / "stkg_v2_graph_export.json").read_text(encoding="utf-8"))
        neo4j = json.loads((ROOT / "audit_reports" / "stkg_v2_neo4j_verification.json").read_text(encoding="utf-8"))
        actual = {
            "research": sha256(ROOT / "derived" / "red_culture_stkg_research_v2.sqlite"),
            "event": sha256(ROOT / "derived" / "red_culture_stkg_event_culture_v2.sqlite"),
            "evolution": sha256(ROOT / "derived" / "red_culture_stkg_evolution_v2.sqlite"),
            "final": sha256(final_path),
            "semantic": sha256(SEMANTIC_V2),
        }
        expectations = {
            "research": research["output"]["sha256"],
            "event": event["output"]["sha256"],
            "evolution": evolution["output"]["sha256"],
            "final": final["output"]["sha256"],
            "semantic": research["semantic_v2"]["sha256"],
        }
        for key in actual:
            if actual[key] != expectations[key]:
                failures.append(f"artifact hash mismatch: {key}")
        if event["input"]["sha256"] != actual["research"]:
            failures.append("event layer does not consume current research layer")
        if evolution["input"]["sha256"] != actual["event"]:
            failures.append("evolution layer does not consume current event layer")
        if final["sources"]["evolution_v2"]["sha256"] != actual["evolution"]:
            failures.append("final layer does not consume current evolution layer")
        if competency["database_before"]["sha256"] != actual["final"] or competency["database_after"]["sha256"] != actual["final"]:
            failures.append("competency query report does not match immutable final database")
        if graph["input"]["sha256"] != actual["final"]:
            failures.append("graph export does not consume current final database")
        for name, metadata in graph["files"].items():
            if sha256(Path(metadata["path"])) != metadata["sha256"]:
                failures.append(f"graph export hash mismatch: {name}")
        if not all(value is True for value in neo4j.get("checks", {}).values()):
            failures.append("Neo4j/UI verification contains a failed check")
        reports["artifact_chain"] = {"actual": actual, "expected": expectations}
    return reports, failures


def audit(database: Path) -> dict:
    database = database.resolve()
    failures = []
    chain, chain_failures = report_chain()
    failures.extend(chain_failures)
    if sha256(PROTECTED_V1) != PROTECTED_V1_SHA256:
        failures.append("protected V1 hash changed")
    before_hash = sha256(database)
    con = sqlite3.connect(f"file:{database.as_posix()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    con.create_function("v2_relation_compatible", 3, relation_compatible, deterministic=True)
    try:
        quick_check = str(con.execute("pragma quick_check").fetchone()[0])
        foreign_key_errors = len(con.execute("pragma foreign_key_check").fetchall())
        counts = {
            name: int(con.execute(sql).fetchone()[0])
            for name, sql in {
                "entities": "select count(*) from research_entities",
                "assertions": "select count(*) from research_assertions",
                "provenance": "select count(*) from research_assertion_provenance",
                "scope_adjustments": "select count(*) from research_scope_adjustments",
                "event_frames": "select count(*) from research_event_frames",
                "event_cells": "select count(*) from research_event_spatiotemporal_cells",
                "culture_states": "select count(*) from research_culture_states",
                "trusted_culture_states": "select count(*) from research_culture_states where observation_tier='trusted_event_spacetime'",
                "transition_candidates": "select count(*) from research_evolution_transition_candidates",
                "published_transitions": "select count(*) from research_evolution_transitions",
                "creative_works": "select count(*) from research_entities where entity_type='CreativeWork'",
                "creative_media": "select count(*) from research_creative_work_media",
                "state_value_facets": "select count(*) from research_culture_state_value_facets",
            }.items()
        }
        normalized_labels = [row[0] for row in con.execute(
            "select normalized_time_label from research_assertions where time_start is not null"
        )]
        invalid_time_labels = sum(not canonical_time_label(label) for label in normalized_labels)
        checks = {
            "quick_check": quick_check == "ok",
            "foreign_keys": foreign_key_errors == 0,
            "entity_names_nonblank": con.execute("select count(*) from research_entities where trim(canonical_name)='' or trim(entity_id)=''").fetchone()[0] == 0,
            "assertion_endpoints_complete": con.execute("select count(*) from research_assertions where subject_id is null or object_id is null").fetchone()[0] == 0,
            "tier_conservation": con.execute("select count(*) from research_assertions where research_tier not in ('strict_semantic','contextual','unresolved')").fetchone()[0] == 0,
            "strict_relation_contracts": con.execute("select count(*) from research_assertions where research_tier='strict_semantic' and v2_relation_compatible(predicate,subject_type,object_type)=0").fetchone()[0] == 0,
            "all_assertions_have_provenance": con.execute("select count(*) from research_assertions a left join research_assertion_provenance p on p.fact_id=a.fact_id where p.fact_id is null").fetchone()[0] == 0,
            "canonical_time_labels": invalid_time_labels == 0,
            "unknown_time_has_no_label": con.execute("select count(*) from research_assertions where time_start is null and normalized_time_label is not null").fetchone()[0] == 0,
            "known_time_has_closed_role": con.execute("select count(*) from research_assertions where time_start is not null and time_role='unknown'").fetchone()[0] == 0,
            "untimed_has_unknown_role": con.execute("select count(*) from research_assertions where time_start is null and time_role<>'unknown'").fetchone()[0] == 0,
            "event_time_owner_type": con.execute("select count(*) from research_assertions a left join research_entities e on e.entity_id=a.time_owner_id where a.time_role='event_occurrence' and coalesce(e.entity_type,'')<>'Event'").fetchone()[0] == 0,
            "biographical_time_owner_type": con.execute("select count(*) from research_assertions a left join research_entities e on e.entity_id=a.time_owner_id where a.time_role='biographical' and coalesce(e.entity_type,'')<>'Person'").fetchone()[0] == 0,
            "event_space_owner_type": con.execute("select count(*) from research_assertions a left join research_entities e on e.entity_id=a.space_owner_id where a.space_role='event_location' and coalesce(e.entity_type,'')<>'Event'").fetchone()[0] == 0,
            "biographical_space_owner_type": con.execute("select count(*) from research_assertions a left join research_entities e on e.entity_id=a.space_owner_id where a.space_role='biographical_location' and coalesce(e.entity_type,'')<>'Person'").fetchone()[0] == 0,
            "no_context_role_promotion": con.execute("select count(*) from research_scope_adjustments where (source_time_role='context_time' and final_time_role not in ('context_time','unknown')) or (source_space_role='context_location' and final_space_role not in ('context_location','unknown'))").fetchone()[0] == 0,
            "all_states_have_support": con.execute("select count(*) from research_culture_states s left join research_culture_state_support x on x.state_id=s.state_id where x.state_id is null").fetchone()[0] == 0,
            "all_states_have_events": con.execute("select count(*) from research_culture_states s left join research_culture_state_events x on x.state_id=s.state_id where x.state_id is null").fetchone()[0] == 0,
            "trusted_transition_endpoints": con.execute("select count(*) from research_evolution_transitions t join research_culture_states f on f.state_id=t.from_state_id join research_culture_states x on x.state_id=t.to_state_id where f.observation_tier<>'trusted_event_spacetime' or x.observation_tier<>'trusted_event_spacetime'").fetchone()[0] == 0,
            "creative_media_complete": counts["creative_works"] == counts["creative_media"],
            "state_value_types_valid": con.execute("select count(*) from research_culture_state_value_facets x join research_entities s on s.entity_id=x.spirit_id join research_entities v on v.entity_id=x.value_facet_id where s.entity_type<>'Spirit' or v.entity_type<>'ValueFacet'").fetchone()[0] == 0,
            "eight_historical_stages": con.execute("select count(*) from research_historical_stages").fetchone()[0] == 8,
            "thirteen_study_regions": con.execute("select count(*) from research_study_regions").fetchone()[0] == 13,
            "three_basin_sections": con.execute("select count(*) from research_basin_sections").fetchone()[0] == 3,
        }
        samples = stratified_samples(con)
    finally:
        con.close()
    after_hash = sha256(database)
    checks["database_unchanged_during_audit"] = before_hash == after_hash
    checks["required_reports_and_hash_chain"] = not chain_failures
    failures.extend(name for name, passed in checks.items() if not passed)
    return {
        "status": "PASS" if not failures else "FAIL",
        "build_version": "red-culture-stkg-v2-full-audit-1",
        "database": {"path": str(database), "sha256": after_hash, "size_bytes": database.stat().st_size},
        "protected_v1": {"path": str(PROTECTED_V1), "sha256": sha256(PROTECTED_V1), "unchanged": sha256(PROTECTED_V1) == PROTECTED_V1_SHA256},
        "counts": counts,
        "integrity": {"quick_check": quick_check, "foreign_key_errors": foreign_key_errors, "invalid_time_labels": invalid_time_labels},
        "checks": checks,
        "report_chain": chain,
        "stratified_samples": samples,
        "failures": failures,
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def markdown(report: dict) -> str:
    lines = [
        "# 长江流域红色文化时空知识图谱 V2 全量审计",
        "",
        f"- 结果：**{report['status']}**",
        f"- 最终数据库：`{report['database']['path']}`",
        f"- SHA-256：`{report['database']['sha256']}`",
        "",
        "## 核心规模",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in report["counts"].items())
    lines.extend(["", "## 全量检查", ""])
    lines.extend(f"- {'PASS' if value else 'FAIL'}：{key}" for key, value in report["checks"].items())
    lines.extend(["", "## 分层抽样", ""])
    lines.extend(f"- {key}: {len(value)} 条" for key, value in report["stratified_samples"].items())
    if report["failures"]:
        lines.extend(["", "## 失败项", ""])
        lines.extend(f"- {value}" for value in report["failures"])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    report = audit(args.database)
    atomic_json(args.json, report)
    atomic_text(args.markdown, markdown(report))
    print(json.dumps({"status": report["status"], "counts": report["counts"], "failures": report["failures"]}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
