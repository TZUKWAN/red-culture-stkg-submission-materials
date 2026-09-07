"""Materialize a clean V2 research base from frozen V1 facts and V2 semantics."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from stkg_contract import RELATIONS, relation_type_allowed  # noqa: E402
from stkg_v2_semantics import (  # noqa: E402
    TYPE_PARENT,
    classify_space_scope,
    classify_time_scope,
)

SOURCE_V1 = ROOT / "releases" / "red_culture_stkg_v1" / "databases" / "red_culture_stkg_evolution_v1.sqlite"
SEMANTIC_V2 = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
OUTPUT = ROOT / "derived" / "red_culture_stkg_research_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_research_base.json"
BUILD_VERSION = "red-culture-stkg-research-v2-base-3"


SCHEMA_SQL = r"""
create table research_build_metadata(
  key text primary key,
  value_json text not null check(json_valid(value_json))
) without rowid;

create table research_relation_contract(
  predicate text primary key,
  label_zh text not null,
  source_types_json text not null check(json_valid(source_types_json)),
  target_types_json text not null check(json_valid(target_types_json)),
  type_hierarchy_aware integer not null check(type_hierarchy_aware=1)
) without rowid;

create table research_entities(
  entity_id text primary key,
  canonical_name text not null,
  entity_type text not null,
  semantic_family text not null,
  aliases_json text not null check(json_valid(aliases_json)),
  integrated_member_count integer not null check(integrated_member_count>=1),
  source_entity_count integer not null check(source_entity_count>=1),
  type_validation_status text not null check(type_validation_status in ('validated','fallback_unresolved')),
  confidence real,
  method_version text not null,
  created_at text not null
) without rowid;

create table research_entity_members(
  source_entity_id text primary key,
  canonical_entity_id text not null references research_entities(entity_id),
  source_canonical_name text not null,
  source_entity_type text not null,
  semantic_entity_type text,
  source_semantic_status text not null,
  mapping_status text not null,
  mapping_reason text not null,
  source_aliases_json text not null check(json_valid(source_aliases_json))
) without rowid;

create table research_assertions(
  fact_id text primary key,
  source_subject_id text not null,
  subject_id text not null references research_entities(entity_id),
  subject_name text not null,
  subject_type text not null,
  source_object_id text not null,
  object_id text not null references research_entities(entity_id),
  object_name text not null,
  object_type text not null,
  predicate text not null,
  time_raw text,
  time_start text,
  time_end text,
  time_precision text not null,
  normalized_time_label text,
  time_role text not null,
  source_time_owner_id text,
  time_owner_id text references research_entities(entity_id),
  place_raw text,
  source_canonical_place_id text,
  canonical_space_anchor_id text references research_entities(entity_id),
  space_role text not null,
  source_space_owner_id text,
  space_owner_id text references research_entities(entity_id),
  province text,
  city text,
  county text,
  basin_section text,
  semantic_status text not null,
  confidence real,
  risk_tier text,
  research_tier text not null check(research_tier in ('strict_semantic','contextual','unresolved')),
  source_member_count integer not null check(source_member_count>=1),
  source_created_at text not null
) without rowid;

create table research_scope_adjustments(
  fact_id text primary key references research_assertions(fact_id),
  source_time_role text not null,
  source_time_owner_id text,
  source_time_owner_canonical_id text references research_entities(entity_id),
  final_time_role text not null,
  final_time_owner_id text references research_entities(entity_id),
  source_space_role text not null,
  source_space_owner_id text,
  source_space_owner_canonical_id text references research_entities(entity_id),
  final_space_role text not null,
  final_space_owner_id text references research_entities(entity_id),
  adjustment_reason text not null,
  method_version text not null
) without rowid;

create table research_assertion_provenance(
  provenance_id text primary key,
  fact_id text not null references research_assertions(fact_id),
  provenance_kind text not null,
  source_member_id text not null,
  topic_kind text,
  source_table text not null,
  source_record_id text not null,
  source_subject_id text,
  source_predicate text,
  source_object_id text,
  member_status text not null,
  legacy_candidate_ids_json text not null check(json_valid(legacy_candidate_ids_json)),
  native_record_ids_json text not null check(json_valid(native_record_ids_json)),
  evidence_ids_json text not null check(json_valid(evidence_ids_json)),
  source_record_ids_json text not null check(json_valid(source_record_ids_json)),
  metadata_json text not null check(json_valid(metadata_json))
) without rowid;

create table research_historical_stages(
  stage_code text primary key,
  stage_order integer not null unique,
  stage_label_zh text not null,
  time_start text not null,
  time_end text not null,
  source_mapping_version text not null,
  snapshot_version text not null,
  source_created_at text not null
) without rowid;

create table research_assertion_stage_memberships(
  fact_id text not null references research_assertions(fact_id),
  stage_code text not null references research_historical_stages(stage_code),
  overlap_start text not null,
  overlap_end text not null,
  membership_status text not null,
  assignment_method text not null,
  source_created_at text not null,
  primary key(fact_id,stage_code)
) without rowid;

create table research_study_regions(
  region_id text primary key,
  province_name text not null unique,
  basin_segment text not null,
  province_order integer not null unique,
  definition_version text not null,
  source_created_at text not null
) without rowid;

create table research_basin_sections(
  basin_section_id text primary key,
  basin_section_name text not null unique,
  section_order integer not null unique
) without rowid;

create table research_assertion_regions(
  fact_id text not null references research_assertions(fact_id),
  region_id text not null references research_study_regions(region_id),
  membership_order integer not null,
  study_area_status text not null,
  derivation_method text not null,
  primary key(fact_id,region_id)
) without rowid;

create table research_assertion_basins(
  fact_id text not null references research_assertions(fact_id),
  basin_section_id text not null references research_basin_sections(basin_section_id),
  membership_order integer not null,
  study_area_status text not null,
  derivation_method text not null,
  primary key(fact_id,basin_section_id)
) without rowid;

create table research_region_hierarchy(
  region_id text primary key references research_study_regions(region_id),
  basin_section_id text not null references research_basin_sections(basin_section_id),
  relation_code text not null,
  derivation_method text not null
) without rowid;

create table research_region_geometries(
  region_id text primary key references research_study_regions(region_id),
  boundary_id text not null,
  adcode text not null,
  geometry_type text not null,
  geometry_json text not null check(json_valid(geometry_json)),
  coordinate_system text not null,
  spatial_precision text not null,
  source_id text not null,
  source_feature_name text not null,
  display_center_lon real,
  display_center_lat real,
  center_usage text not null
) without rowid;

create index idx_research_entity_type on research_entities(entity_type,canonical_name);
create index idx_research_member_canonical on research_entity_members(canonical_entity_id);
create index idx_research_assertion_subject on research_assertions(subject_id,predicate);
create index idx_research_assertion_object on research_assertions(object_id,predicate);
create index idx_research_assertion_tier on research_assertions(research_tier,predicate);
create index idx_research_assertion_time on research_assertions(time_role,time_start);
create index idx_research_assertion_space on research_assertions(space_role,canonical_space_anchor_id);
create index idx_research_scope_adjustment_time on research_scope_adjustments(source_time_role,final_time_role);
create index idx_research_scope_adjustment_space on research_scope_adjustments(source_space_role,final_space_role);
create index idx_research_provenance_fact on research_assertion_provenance(fact_id);
create index idx_research_stage on research_assertion_stage_memberships(stage_code,fact_id);
create index idx_research_region on research_assertion_regions(region_id,fact_id);
create index idx_research_basin on research_assertion_basins(basin_section_id,fact_id);

create view v_research_strict_assertions as
select * from research_assertions where research_tier='strict_semantic';

create view v_research_contextual_assertions as
select * from research_assertions where research_tier='contextual';

create view v_research_unresolved_assertions as
select * from research_assertions where research_tier='unresolved';

create view v_research_event_backbone_assertions as
select * from research_assertions
where research_tier='strict_semantic' and (subject_type='Event' or object_type='Event');

create view v_research_event_occurrence_times as
select * from research_assertions
where semantic_status='auto_accepted' and time_role='event_occurrence'
  and time_owner_id is not null;

create view v_research_valid_spatial_assertions as
select * from research_assertions where canonical_space_anchor_id is not null;
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def semantic_family(entity_type: str) -> str:
    if entity_type in {"Place", "AdministrativeRegion", "CulturalSite", "BasinSection"}:
        return "SpatialEntity"
    if entity_type in {"Organization", "Institution", "SocialGroup"}:
        return "CollectiveEntity"
    if entity_type in {"Spirit", "ValueFacet", "Position", "Concept"}:
        return "ConceptualEntity"
    if entity_type in {"Document", "CreativeWork"}:
        return "InformationObject"
    return entity_type


def relation_type_allowed_v2(actual_type: object, allowed_types: frozenset[str]) -> bool:
    """Apply the frozen relation contract after V2 subtype refinement."""
    current = str(actual_type or "").strip()
    seen = set()
    while current and current not in seen:
        if relation_type_allowed(current, allowed_types):
            return True
        seen.add(current)
        current = TYPE_PARENT.get(current, "")
    return False


def relation_domain_range_pass_v2(predicate: object, source_type: object, target_type: object) -> bool:
    relation = RELATIONS.get(str(predicate or "").strip())
    return bool(
        relation
        and relation_type_allowed_v2(source_type, relation.source_types)
        and relation_type_allowed_v2(target_type, relation.target_types)
    )


def _endpoint_type(
    owner_id: str | None,
    subject_id: str,
    subject_type: str,
    object_id: str,
    object_type: str,
) -> str | None:
    if not owner_id:
        return None
    matches = []
    if owner_id == subject_id:
        matches.append(subject_type)
    if owner_id == object_id:
        matches.append(object_type)
    return matches[0] if len(set(matches)) == 1 else None


def _fallback_time_role(predicate: str) -> tuple[str, None]:
    return ("context_time" if predicate.startswith("raw:") else "relation_validity", None)


def _fallback_space_role(predicate: str) -> tuple[str, None]:
    return ("context_location" if predicate.startswith("raw:") else "relation_location", None)


@lru_cache(maxsize=8192)
def close_time_scope_after_identity(
    source_role: str,
    source_owner_id: str | None,
    predicate: str,
    time_start: str | None,
    subject_id: str,
    subject_type: str,
    object_id: str,
    object_type: str,
) -> tuple[str, str | None]:
    """Preserve valid adjudication and close only roles invalidated by identity fusion."""
    if not time_start:
        return "unknown", None
    required_owner_types = {
        "event_occurrence": {"Event"},
        "biographical": {"Person"},
        "creation_or_publication": {"CreativeWork", "Document", "Artifact"},
        "source_document_time": {"Document"},
    }
    if source_role == "unknown":
        label = classify_time_scope(
            predicate, time_start, subject_id, subject_type, object_id, object_type
        )
        source_role, source_owner_id = label.role, label.owner_id
    allowed_types = required_owner_types.get(source_role)
    owner_type = _endpoint_type(
        source_owner_id, subject_id, subject_type, object_id, object_type
    )
    if allowed_types is not None and owner_type not in allowed_types:
        return _fallback_time_role(predicate)
    if source_role == "unknown":
        return _fallback_time_role(predicate)
    if source_role in {"context_time", "relation_validity"}:
        return source_role, None
    return source_role, source_owner_id


@lru_cache(maxsize=8192)
def close_space_scope_after_identity(
    source_role: str,
    source_owner_id: str | None,
    predicate: str,
    canonical_space_anchor_id: str | None,
    subject_id: str,
    subject_type: str,
    object_id: str,
    object_type: str,
) -> tuple[str, str | None]:
    """Preserve valid spatial adjudication and close structurally stale ownership."""
    if not canonical_space_anchor_id:
        return "unknown", None
    if source_role == "unknown":
        return "unknown", None
    required_owner_types = {
        "event_location": {"Event"},
        "biographical_location": {"Person"},
        "creation_or_publication_location": {"CreativeWork", "Document", "Artifact"},
    }
    allowed_types = required_owner_types.get(source_role)
    owner_type = _endpoint_type(
        source_owner_id, subject_id, subject_type, object_id, object_type
    )
    if allowed_types is not None and owner_type not in allowed_types:
        return _fallback_space_role(predicate)
    if source_role in {"context_location", "relation_location"}:
        return source_role, None
    return source_role, source_owner_id


def collect_entity_rows(semantic_database: Path, created_at: str) -> tuple[list[tuple], list[tuple]]:
    con = sqlite3.connect(f"file:{semantic_database.resolve().as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        groups: dict[str, dict] = {}
        members = []
        rows = con.execute(
            "select e.*,m.canonical_entity_id,m.canonical_name mapped_name,"
            "m.canonical_entity_type,m.mapping_status,m.mapping_reason "
            "from v2_entities e join v2_entity_identity_map m "
            "on m.source_entity_id=e.entity_id order by e.entity_id"
        )
        for row in rows:
            canonical_id = str(row["canonical_entity_id"])
            item = groups.setdefault(
                canonical_id,
                {
                    "name": str(row["mapped_name"]),
                    "type": str(row["canonical_entity_type"]),
                    "aliases": set(),
                    "member_count": 0,
                    "source_count": 0,
                    "validated": True,
                    "confidences": [],
                },
            )
            source_name = str(row["canonical_name"])
            if source_name != item["name"]:
                item["aliases"].add(source_name)
            item["aliases"].update(str(value) for value in json.loads(row["aliases_json"] or "[]") if str(value).strip())
            item["aliases"].discard(item["name"])
            item["member_count"] += int(row["member_count"] or 1)
            item["source_count"] += 1
            item["validated"] = item["validated"] and row["semantic_entity_type"] is not None
            if row["confidence"] is not None:
                item["confidences"].append(float(row["confidence"]))
            members.append(
                (
                    row["entity_id"], canonical_id, source_name, row["source_entity_type"],
                    row["semantic_entity_type"], row["semantic_status"], row["mapping_status"],
                    row["mapping_reason"], row["aliases_json"],
                )
            )
        entities = []
        for entity_id, item in sorted(groups.items()):
            entities.append(
                (
                    entity_id, item["name"], item["type"], semantic_family(item["type"]),
                    json.dumps(sorted(item["aliases"]), ensure_ascii=False),
                    item["member_count"], item["source_count"],
                    "validated" if item["validated"] else "fallback_unresolved",
                    min(item["confidences"]) if item["confidences"] else None,
                    BUILD_VERSION, created_at,
                )
            )
        return entities, members
    finally:
        con.close()


def collect_counts(con: sqlite3.Connection) -> dict[str, int]:
    queries = {
        "entities": "select count(*) from research_entities",
        "relation_contracts": "select count(*) from research_relation_contract",
        "entity_members": "select count(*) from research_entity_members",
        "assertions": "select count(*) from research_assertions",
        "scope_adjustments": "select count(*) from research_scope_adjustments",
        "provenance": "select count(*) from research_assertion_provenance",
        "stages": "select count(*) from research_historical_stages",
        "stage_memberships": "select count(*) from research_assertion_stage_memberships",
        "regions": "select count(*) from research_study_regions",
        "basins": "select count(*) from research_basin_sections",
        "region_memberships": "select count(*) from research_assertion_regions",
        "basin_memberships": "select count(*) from research_assertion_basins",
        "strict_assertions": "select count(*) from v_research_strict_assertions",
        "contextual_assertions": "select count(*) from v_research_contextual_assertions",
        "unresolved_assertions": "select count(*) from v_research_unresolved_assertions",
        "event_backbone_assertions": "select count(*) from v_research_event_backbone_assertions",
        "event_occurrence_time_assertions": "select count(*) from v_research_event_occurrence_times",
        "valid_spatial_assertions": "select count(*) from v_research_valid_spatial_assertions",
    }
    return {name: int(con.execute(sql).fetchone()[0]) for name, sql in queries.items()}


def validate_database(con: sqlite3.Connection, expected_entities: int) -> dict:
    counts = collect_counts(con)
    quick_check = str(con.execute("pragma quick_check").fetchone()[0])
    foreign_key_errors = len(con.execute("pragma foreign_key_check").fetchall())
    tier_conservation = (
        counts["strict_assertions"] + counts["contextual_assertions"] + counts["unresolved_assertions"]
        == counts["assertions"]
    )
    missing_endpoints = int(
        con.execute(
            "select count(*) from research_assertions a left join research_entities s on s.entity_id=a.subject_id "
            "left join research_entities o on o.entity_id=a.object_id "
            "where s.entity_id is null or o.entity_id is null"
        ).fetchone()[0]
    )
    invalid_time_labels = int(
        con.execute(
            "select count(*) from research_assertions where time_start is not null and "
            "(normalized_time_label is null or normalized_time_label glob '*日*' "
            "or normalized_time_label glob '*一九*' or normalized_time_label glob '*〇*')"
        ).fetchone()[0]
    )
    owner_errors = int(
        con.execute(
            "select count(*) from research_assertions where "
            "(time_owner_id is not null and time_role='unknown') or "
            "(space_owner_id is not null and space_role='unknown')"
        ).fetchone()[0]
    )
    timed_unknown_roles = int(
        con.execute(
            "select count(*) from research_assertions where time_start is not null and time_role='unknown'"
        ).fetchone()[0]
    )
    untimed_known_roles = int(
        con.execute(
            "select count(*) from research_assertions where time_start is null and time_role<>'unknown'"
        ).fetchone()[0]
    )
    invalid_time_owner_types = int(
        con.execute(
            "select count(*) from research_assertions a left join research_entities e on e.entity_id=a.time_owner_id "
            "where (a.time_role='event_occurrence' and coalesce(e.entity_type,'')<>'Event') "
            "or (a.time_role='biographical' and coalesce(e.entity_type,'')<>'Person') "
            "or (a.time_role='creation_or_publication' and coalesce(e.entity_type,'') not in ('CreativeWork','Document','Artifact')) "
            "or (a.time_role='source_document_time' and coalesce(e.entity_type,'')<>'Document')"
        ).fetchone()[0]
    )
    invalid_space_owner_types = int(
        con.execute(
            "select count(*) from research_assertions a left join research_entities e on e.entity_id=a.space_owner_id "
            "where (a.space_role='event_location' and coalesce(e.entity_type,'')<>'Event') "
            "or (a.space_role='biographical_location' and coalesce(e.entity_type,'')<>'Person') "
            "or (a.space_role='creation_or_publication_location' and coalesce(e.entity_type,'') not in ('CreativeWork','Document','Artifact'))"
        ).fetchone()[0]
    )
    strict_domain_range_errors = int(
        con.execute(
            "select count(*) from research_assertions where research_tier='strict_semantic' "
            "and v2_relation_compatible(predicate,subject_type,object_type)=0"
        ).fetchone()[0]
    )
    passed = all(
        (
            quick_check == "ok",
            foreign_key_errors == 0,
            counts["entities"] == expected_entities,
            counts["relation_contracts"] == len(RELATIONS),
            counts["entity_members"] == 154150,
            counts["assertions"] == 424150,
            counts["provenance"] == 466312,
            counts["stages"] == 8,
            counts["regions"] == 13,
            counts["basins"] == 3,
            tier_conservation,
            missing_endpoints == 0,
            invalid_time_labels == 0,
            owner_errors == 0,
            timed_unknown_roles == 0,
            untimed_known_roles == 0,
            invalid_time_owner_types == 0,
            invalid_space_owner_types == 0,
            strict_domain_range_errors == 0,
        )
    )
    return {
        "counts": counts,
        "quick_check": quick_check,
        "foreign_key_errors": foreign_key_errors,
        "tier_conservation": tier_conservation,
        "missing_canonical_endpoints": missing_endpoints,
        "invalid_time_labels": invalid_time_labels,
        "owner_role_errors": owner_errors,
        "timed_unknown_roles": timed_unknown_roles,
        "untimed_known_roles": untimed_known_roles,
        "invalid_time_owner_types": invalid_time_owner_types,
        "invalid_space_owner_types": invalid_space_owner_types,
        "strict_domain_range_errors": strict_domain_range_errors,
        "pass": passed,
    }


def materialize(source_v1: Path, semantic_v2: Path, output: Path, report: Path) -> dict:
    source_v1 = source_v1.resolve()
    semantic_v2 = semantic_v2.resolve()
    output = output.resolve()
    report = report.resolve()
    v1_hash = sha256(source_v1)
    v2_hash = sha256(semantic_v2)
    created_at = datetime.now().isoformat(timespec="seconds")
    entities, members = collect_entity_rows(semantic_v2, created_at)
    temporary = output.with_name(f".{output.name}.tmp")
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(temporary) + suffix).unlink(missing_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(temporary, timeout=120)
    con.create_function("v2_relation_compatible", 3, relation_domain_range_pass_v2, deterministic=True)
    con.create_function(
        "v2_final_time_role", 8,
        lambda *args: close_time_scope_after_identity(*args)[0], deterministic=True,
    )
    con.create_function(
        "v2_final_time_owner", 8,
        lambda *args: close_time_scope_after_identity(*args)[1], deterministic=True,
    )
    con.create_function(
        "v2_final_space_role", 8,
        lambda *args: close_space_scope_after_identity(*args)[0], deterministic=True,
    )
    con.create_function(
        "v2_final_space_owner", 8,
        lambda *args: close_space_scope_after_identity(*args)[1], deterministic=True,
    )
    con.execute("pragma foreign_keys=on")
    con.execute("pragma journal_mode=delete")
    con.execute("pragma synchronous=full")
    con.execute("pragma temp_store=memory")
    con.execute("attach database ? as src", (f"file:{source_v1.as_posix()}?mode=ro",))
    con.execute("attach database ? as sem", (f"file:{semantic_v2.as_posix()}?mode=ro",))
    try:
        con.executescript(SCHEMA_SQL)
        con.execute("begin immediate")
        con.executemany(
            "insert into research_relation_contract values(?,?,?,?,1)",
            [
                (
                    code,
                    relation.label,
                    json.dumps(sorted(relation.source_types), ensure_ascii=False),
                    json.dumps(sorted(relation.target_types), ensure_ascii=False),
                )
                for code, relation in sorted(RELATIONS.items())
            ],
        )
        con.executemany("insert into research_entities values(?,?,?,?,?,?,?,?,?,?,?)", entities)
        con.executemany("insert into research_entity_members values(?,?,?,?,?,?,?,?,?)", members)
        con.execute(
            "create temp table finalized_scopes as "
            "select a.fact_id,a.time_role source_time_role,a.time_owner_id source_time_owner_id,"
            "mto.canonical_entity_id source_time_owner_canonical_id,"
            "v2_final_time_role(a.time_role,mto.canonical_entity_id,a.predicate,a.time_start,"
            "ms.canonical_entity_id,ms.canonical_entity_type,"
            "mo.canonical_entity_id,mo.canonical_entity_type) final_time_role,"
            "v2_final_time_owner(a.time_role,mto.canonical_entity_id,a.predicate,a.time_start,"
            "ms.canonical_entity_id,ms.canonical_entity_type,"
            "mo.canonical_entity_id,mo.canonical_entity_type) final_time_owner_id,"
            "a.space_role source_space_role,a.space_owner_id source_space_owner_id,"
            "mso.canonical_entity_id source_space_owner_canonical_id,"
            "v2_final_space_role(a.space_role,mso.canonical_entity_id,a.predicate,sp.canonical_anchor_id,"
            "ms.canonical_entity_id,ms.canonical_entity_type,"
            "mo.canonical_entity_id,mo.canonical_entity_type) final_space_role,"
            "v2_final_space_owner(a.space_role,mso.canonical_entity_id,a.predicate,sp.canonical_anchor_id,"
            "ms.canonical_entity_id,ms.canonical_entity_type,"
            "mo.canonical_entity_id,mo.canonical_entity_type) final_space_owner_id "
            "from sem.v2_assertion_scopes a "
            "join sem.v2_entity_identity_map ms on ms.source_entity_id=a.subject_id "
            "join sem.v2_entity_identity_map mo on mo.source_entity_id=a.object_id "
            "join sem.v2_spatial_projection sp on sp.fact_id=a.fact_id "
            "left join sem.v2_entity_identity_map mto on mto.source_entity_id=a.time_owner_id "
            "left join sem.v2_entity_identity_map mso on mso.source_entity_id=a.space_owner_id"
        )
        con.execute("create unique index temp.idx_finalized_scopes_fact on finalized_scopes(fact_id)")
        con.execute(
            "insert into research_assertions "
            "select a.fact_id,a.subject_id,ms.canonical_entity_id,ms.canonical_name,ms.canonical_entity_type,"
            "a.object_id,mo.canonical_entity_id,mo.canonical_name,mo.canonical_entity_type,a.predicate,"
            "a.time_raw,a.time_start,a.time_end,a.time_precision,td.normalized_time_label,fs.final_time_role,"
            "a.time_owner_id,fs.final_time_owner_id,a.place_raw,a.canonical_place_id,sp.canonical_anchor_id,"
            "fs.final_space_role,a.space_owner_id,fs.final_space_owner_id,v.province,v.city,v.county,v.basin_section,"
            "a.semantic_status,a.confidence,a.risk_tier,"
            "case when a.semantic_status='auto_accepted' and a.predicate not like 'raw:%' "
            "and es.type_validation_status='validated' and eo.type_validation_status='validated' "
            "and v2_relation_compatible(a.predicate,ms.canonical_entity_type,mo.canonical_entity_type)=1 "
            "then 'strict_semantic' when a.semantic_status='auto_accepted' then 'contextual' else 'unresolved' end,"
            "v.member_count,v.source_created_at "
            "from sem.v2_assertion_scopes a "
            "join sem.v2_entity_identity_map ms on ms.source_entity_id=a.subject_id "
            "join sem.v2_entity_identity_map mo on mo.source_entity_id=a.object_id "
            "join sem.v2_entity_type_effective es on es.entity_id=a.subject_id "
            "join sem.v2_entity_type_effective eo on eo.entity_id=a.object_id "
            "join sem.v2_time_display td on td.fact_id=a.fact_id "
            "join sem.v2_spatial_projection sp on sp.fact_id=a.fact_id "
            "join finalized_scopes fs on fs.fact_id=a.fact_id "
            "join src.stkg_assertions v on v.fact_id=a.fact_id "
            ""
        )
        con.execute(
            "insert into research_scope_adjustments "
            "select fact_id,source_time_role,source_time_owner_id,source_time_owner_canonical_id,"
            "final_time_role,final_time_owner_id,source_space_role,source_space_owner_id,"
            "source_space_owner_canonical_id,final_space_role,final_space_owner_id,"
            "'final_entity_type_scope_closure',? from finalized_scopes "
            "where source_time_role is not final_time_role "
            "or source_time_owner_canonical_id is not final_time_owner_id "
            "or source_space_role is not final_space_role "
            "or source_space_owner_canonical_id is not final_space_owner_id",
            (BUILD_VERSION,),
        )
        con.execute(
            "insert into research_assertion_provenance select * from src.stkg_assertion_provenance"
        )
        con.execute(
            "insert into research_historical_stages select * from src.stkg_historical_stages"
        )
        con.execute(
            "insert into research_assertion_stage_memberships select * from src.stkg_assertion_stage_memberships"
        )
        con.execute("insert into research_study_regions select * from src.stkg_study_regions")
        con.execute("insert into research_basin_sections select * from src.stkg_basin_sections")
        con.execute(
            "insert into research_assertion_regions select * from src.stkg_assertion_region_memberships"
        )
        con.execute(
            "insert into research_assertion_basins select * from src.stkg_assertion_basin_memberships"
        )
        con.execute("insert into research_region_hierarchy select * from src.stkg_region_hierarchy")
        con.execute("insert into research_region_geometries select * from src.stkg_region_geometries")
        metadata = {
            "build_version": BUILD_VERSION,
            "research_objective": "长江流域红色文化如何演进",
            "source_v1": str(source_v1),
            "source_v1_sha256": v1_hash,
            "semantic_v2": str(semantic_v2),
            "semantic_v2_sha256": v2_hash,
            "created_at": created_at,
            "limitations": [
                "raw predicates are contextual",
                "fallback unresolved entity types are excluded from strict semantic assertions",
                "no causality or evolution is inferred from sequence alone",
            ],
        }
        con.executemany(
            "insert into research_build_metadata values(?,?)",
            [(key, json.dumps(value, ensure_ascii=False)) for key, value in metadata.items()],
        )
        con.commit()
        validation = validate_database(con, len(entities))
        if not validation["pass"]:
            raise RuntimeError("V2 research base validation failed")
        con.execute("detach database sem")
        con.execute("detach database src")
    except Exception:
        con.rollback()
        con.close()
        temporary.unlink(missing_ok=True)
        raise
    con.close()
    if sha256(source_v1) != v1_hash or sha256(semantic_v2) != v2_hash:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("protected source changed during V2 research materialization")
    os.replace(temporary, output)
    payload = {
        "status": "PASS",
        "build_version": BUILD_VERSION,
        "source_v1": {"path": str(source_v1), "sha256": v1_hash, "unchanged": True},
        "semantic_v2": {"path": str(semantic_v2), "sha256": v2_hash, "unchanged": True},
        "output": {"path": str(output), "sha256": sha256(output), "size_bytes": output.stat().st_size},
        "validation": validation,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-v1", type=Path, default=SOURCE_V1)
    parser.add_argument("--semantic-v2", type=Path, default=SEMANTIC_V2)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    print(json.dumps(materialize(args.source_v1, args.semantic_v2, args.output, args.report), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
