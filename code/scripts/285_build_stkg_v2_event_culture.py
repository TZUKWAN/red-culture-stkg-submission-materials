"""Build V2 EventFrames and red-culture forms from the validated research base."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from stkg_contract import RELATIONS, relation_type_allowed  # noqa: E402
from stkg_v2_semantics import TYPE_PARENT  # noqa: E402


INPUT = ROOT / "derived" / "red_culture_stkg_research_v2.sqlite"
SEMANTIC_V2 = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
OUTPUT = ROOT / "derived" / "red_culture_stkg_event_culture_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_event_culture.json"
EVENT_MAPPING = ROOT / "stkg" / "schema" / "event_role_mapping_v1.yaml"
CULTURE_MAPPING = ROOT / "stkg" / "schema" / "culture_form_mapping_v1.yaml"
BUILD_VERSION = "red-culture-stkg-event-culture-v2-1"


SCHEMA_SQL = r"""
create table research_event_role_catalog(
  mapping_id text primary key,
  predicate text not null,
  event_endpoint text not null check(event_endpoint in ('subject','object')),
  role_code text not null,
  role_category text not null,
  counterpart_types_json text not null check(json_valid(counterpart_types_json)),
  analysis_strength text not null check(analysis_strength in ('core','explicit_context')),
  unique(predicate,event_endpoint)
) without rowid;

create table research_event_assertion_links(
  event_id text not null references research_entities(entity_id),
  event_name text not null,
  fact_id text not null references research_assertions(fact_id),
  event_endpoint text not null check(event_endpoint in ('subject','object')),
  counterpart_id text not null references research_entities(entity_id),
  counterpart_name text not null,
  counterpart_type text not null,
  predicate text not null,
  research_tier text not null,
  semantic_route text not null check(semantic_route in ('strict_controlled','contextual','unresolved')),
  time_role text not null,
  time_owner_id text,
  occurrence_time_start text,
  occurrence_time_end text,
  occurrence_time_label text,
  occurrence_time_status text not null check(occurrence_time_status in ('none','model_adjudicated','source_consensus','asserted_candidate')),
  space_role text not null,
  space_owner_id text,
  event_location_id text references research_entities(entity_id),
  primary key(event_id,fact_id,event_endpoint)
) without rowid;

create table research_event_roles(
  event_id text not null,
  fact_id text not null,
  event_endpoint text not null,
  counterpart_id text not null references research_entities(entity_id),
  counterpart_name text not null,
  counterpart_type text not null,
  predicate text not null,
  role_code text not null,
  role_category text not null,
  analysis_strength text not null,
  mapping_id text not null references research_event_role_catalog(mapping_id),
  primary key(event_id,fact_id,event_endpoint),
  foreign key(event_id,fact_id,event_endpoint)
    references research_event_assertion_links(event_id,fact_id,event_endpoint)
) without rowid;

create table research_event_relations(
  fact_id text primary key references research_assertions(fact_id),
  source_event_id text not null references research_entities(entity_id),
  source_event_name text not null,
  target_event_id text not null references research_entities(entity_id),
  target_event_name text not null,
  relation_code text not null check(relation_code in ('part_of','influenced')),
  relation_strength text not null check(relation_strength in ('explicit_structure','explicit_context')),
  causality_status text not null check(causality_status='not_inferred')
) without rowid;

create table research_event_frames(
  event_id text primary key references research_entities(entity_id),
  event_name text not null,
  all_assertion_count integer not null,
  strict_assertion_count integer not null,
  controlled_role_count integer not null,
  occurrence_time_fact_count integer not null,
  trusted_time_fact_count integer not null,
  event_location_fact_count integer not null,
  stage_count integer not null,
  region_count integer not null,
  observed_time_start text,
  observed_time_end text,
  observed_time_status text not null check(observed_time_status in ('none','asserted_candidate','trusted')),
  frame_status text not null check(frame_status in ('strict_backbone','context_only','isolated'))
) without rowid;

create table research_culture_forms(
  culture_form_code text primary key,
  label_zh text not null unique
) without rowid;

create table research_culture_form_rules(
  rule_id text primary key,
  rule_kind text not null check(rule_kind in ('direct_type','controlled_relation')),
  entity_types_json text not null check(json_valid(entity_types_json)),
  predicate text,
  entity_endpoint text check(entity_endpoint in ('subject','object') or entity_endpoint is null),
  culture_form_code text not null references research_culture_forms(culture_form_code),
  culture_role text not null,
  support_strength text not null check(support_strength in ('typed_context','controlled_explicit'))
) without rowid;

create table research_culture_form_support(
  entity_id text not null references research_entities(entity_id),
  culture_form_code text not null references research_culture_forms(culture_form_code),
  fact_id text not null references research_assertions(fact_id),
  rule_id text not null references research_culture_form_rules(rule_id),
  culture_role text not null,
  support_strength text not null check(support_strength in ('typed_context','controlled_explicit')),
  research_tier text not null check(research_tier in ('strict_semantic','contextual')),
  primary key(entity_id,culture_form_code,fact_id,rule_id)
) without rowid;

create table research_entity_culture_forms(
  entity_id text not null references research_entities(entity_id),
  entity_name text not null,
  entity_type text not null,
  culture_form_code text not null references research_culture_forms(culture_form_code),
  culture_role text not null,
  assignment_status text not null check(assignment_status in ('typed_context_supported','controlled_explicit')),
  supporting_fact_count integer not null check(supporting_fact_count>=1),
  strict_supporting_fact_count integer not null check(strict_supporting_fact_count>=0),
  primary key(entity_id,culture_form_code,culture_role)
) without rowid;

create table research_spirit_value_links(
  fact_id text primary key references research_assertions(fact_id),
  spirit_id text not null references research_entities(entity_id),
  spirit_name text not null,
  value_facet_id text not null references research_entities(entity_id),
  value_facet_name text not null,
  relation_code text not null check(relation_code='has_value_facet')
) without rowid;

create index idx_research_event_link_fact on research_event_assertion_links(fact_id,event_id);
create index idx_research_event_link_counterpart on research_event_assertion_links(counterpart_id,counterpart_type);
create index idx_research_event_link_time on research_event_assertion_links(event_id,occurrence_time_start);
create index idx_research_event_link_place on research_event_assertion_links(event_id,event_location_id);
create index idx_research_event_role_code on research_event_roles(role_code,event_id);
create index idx_research_event_relation_source on research_event_relations(source_event_id,relation_code);
create index idx_research_event_relation_target on research_event_relations(target_event_id,relation_code);
create index idx_research_event_frame_status on research_event_frames(frame_status,event_id);
create index idx_research_culture_support_fact on research_culture_form_support(fact_id,entity_id);
create index idx_research_culture_support_form on research_culture_form_support(culture_form_code,entity_id);
create index idx_research_entity_culture_form on research_entity_culture_forms(culture_form_code,entity_id);

create view v_research_event_backbone_frames as
select * from research_event_frames where frame_status='strict_backbone';

create view v_research_event_actor_roles as
select * from research_event_roles where role_category='actor';

create view v_research_event_culture_roles as
select * from research_event_roles
where role_category in ('culture_semantics','cultural_object','memory_transmission','documentary');

create view v_research_event_times as
select event_id,event_name,fact_id,occurrence_time_start,occurrence_time_end,occurrence_time_label
from research_event_assertion_links where occurrence_time_start is not null;

create view v_research_event_places as
select l.event_id,l.event_name,l.fact_id,l.event_location_id,e.canonical_name event_location_name,
       e.entity_type event_location_type
from research_event_assertion_links l join research_entities e on e.entity_id=l.event_location_id
where l.event_location_id is not null;

create view v_research_creative_works as
select e.*,f.culture_role,f.assignment_status,f.supporting_fact_count
from research_entities e join research_entity_culture_forms f on f.entity_id=e.entity_id
where f.culture_form_code='CreativeNarrative';
"""


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relation_type_allowed_v2(actual_type: object, allowed_types: frozenset[str]) -> bool:
    current = str(actual_type or "").strip()
    seen = set()
    while current and current not in seen:
        if relation_type_allowed(current, allowed_types):
            return True
        seen.add(current)
        current = TYPE_PARENT.get(current, "")
    return False


def counterpart_allowed(actual_type: object, allowed_types_json: object) -> bool:
    try:
        allowed = frozenset(json.loads(str(allowed_types_json)))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return relation_type_allowed_v2(actual_type, allowed)


def direct_support_eligible(entity_type: str, research_tier: str) -> bool:
    if research_tier == "unresolved":
        return False
    return entity_type != "Event" or research_tier == "strict_semantic"


def occurrence_time_is_trusted(status: str) -> bool:
    return status in {"model_adjudicated", "source_consensus"}


def validate_mappings(event_mapping: dict, culture_mapping: dict) -> list[str]:
    failures = []
    event_flags = event_mapping.get("rules") or {}
    for flag in (
        "raw_predicates_are_context_only", "controlled_unmapped_predicates_fail",
        "event_sequence_is_not_causality", "event_entity_is_not_duplicated",
    ):
        if event_flags.get(flag) is not True:
            failures.append(f"event mapping rule is not true: {flag}")
    seen = set()
    for item in event_mapping.get("mappings") or []:
        key = (item.get("predicate"), item.get("event_endpoint"))
        if key in seen:
            failures.append(f"duplicate event role mapping: {key}")
        seen.add(key)
        if item.get("predicate") not in RELATIONS or item.get("event_endpoint") not in {"subject", "object"}:
            failures.append(f"invalid event role mapping: {key}")
    culture_flags = culture_mapping.get("rules") or {}
    for flag in (
        "every_assignment_requires_fact_support", "raw_predicates_cannot_trigger_relation_rules",
        "person_place_organization_are_not_automatic_carriers", "event_is_subject_not_carrier",
        "spirit_is_optional_not_mandatory",
    ):
        if culture_flags.get(flag) is not True:
            failures.append(f"culture mapping rule is not true: {flag}")
    forms = {item.get("code") for item in culture_mapping.get("culture_forms") or []}
    if len(forms) != 7:
        failures.append(f"expected seven culture forms, got {len(forms)}")
    for item in culture_mapping.get("relation_rules") or []:
        if item.get("predicate") not in RELATIONS or item.get("culture_form") not in forms:
            failures.append(f"invalid culture relation rule: {item.get('rule_id')}")
    return failures


def collect_counts(con: sqlite3.Connection) -> dict[str, int]:
    queries = {
        "event_role_mappings": "select count(*) from research_event_role_catalog",
        "event_frames": "select count(*) from research_event_frames",
        "event_assertion_links": "select count(*) from research_event_assertion_links",
        "controlled_event_roles": "select count(*) from research_event_roles",
        "event_relations": "select count(*) from research_event_relations",
        "strict_backbone_frames": "select count(*) from research_event_frames where frame_status='strict_backbone'",
        "context_only_frames": "select count(*) from research_event_frames where frame_status='context_only'",
        "isolated_frames": "select count(*) from research_event_frames where frame_status='isolated'",
        "events_with_observed_time": "select count(*) from research_event_frames where occurrence_time_fact_count>0",
        "events_with_trusted_time": "select count(*) from research_event_frames where trusted_time_fact_count>0",
        "events_with_observed_place": "select count(*) from research_event_frames where event_location_fact_count>0",
        "culture_forms": "select count(*) from research_culture_forms",
        "culture_form_rules": "select count(*) from research_culture_form_rules",
        "culture_form_support_rows": "select count(*) from research_culture_form_support",
        "entity_culture_form_assignments": "select count(*) from research_entity_culture_forms",
        "assigned_culture_entities": "select count(distinct entity_id) from research_entity_culture_forms",
        "spirit_value_links": "select count(*) from research_spirit_value_links",
    }
    return {key: int(con.execute(sql).fetchone()[0]) for key, sql in queries.items()}


def validate_database(con: sqlite3.Connection, input_hash: str, input_path: Path) -> dict:
    counts = collect_counts(con)
    checks = {
        "quick_check": str(con.execute("pragma quick_check").fetchone()[0]),
        "foreign_key_errors": len(con.execute("pragma foreign_key_check").fetchall()),
        "event_frame_count_mismatch": int(con.execute(
            "select abs((select count(*) from research_event_frames)-"
            "(select count(*) from research_entities where entity_type='Event'))"
        ).fetchone()[0]),
        "event_time_owner_errors": int(con.execute(
            "select count(*) from research_event_assertion_links where occurrence_time_start is not null "
            "and (time_role<>'event_occurrence' or time_owner_id<>event_id)"
        ).fetchone()[0]),
        "model_time_status_errors": int(con.execute(
            "select count(*) from research_event_assertion_links l where l.occurrence_time_status='model_adjudicated' "
            "and not exists(select 1 from sem.v2_event_time_closures c,"
            "json_each(c.effective_partition_json,'$.event_occurrence_fact_ids') j where j.value=l.fact_id)"
        ).fetchone()[0]),
        "source_consensus_status_errors": int(con.execute(
            "select count(*) from research_event_assertion_links l where l.occurrence_time_status='source_consensus' "
            "and l.event_id not in (select event_id from research_event_assertion_links "
            "where occurrence_time_start is not null group by event_id "
            "having count(distinct fact_id)>=2 and count(distinct substr(occurrence_time_start,1,4))=1)"
        ).fetchone()[0]),
        "event_place_owner_errors": int(con.execute(
            "select count(*) from research_event_assertion_links where event_location_id is not null "
            "and (space_role<>'event_location' or space_owner_id<>event_id)"
        ).fetchone()[0]),
        "non_strict_event_roles": int(con.execute(
            "select count(*) from research_event_roles r join research_assertions a on a.fact_id=r.fact_id "
            "where a.research_tier<>'strict_semantic'"
        ).fetchone()[0]),
        "non_strict_event_relations": int(con.execute(
            "select count(*) from research_event_relations r join research_assertions a on a.fact_id=r.fact_id "
            "where a.research_tier<>'strict_semantic'"
        ).fetchone()[0]),
        "assignments_without_support": int(con.execute(
            "select count(*) from research_entity_culture_forms f where not exists("
            "select 1 from research_culture_form_support s where s.entity_id=f.entity_id "
            "and s.culture_form_code=f.culture_form_code and s.culture_role=f.culture_role)"
        ).fetchone()[0]),
        "controlled_support_outside_strict": int(con.execute(
            "select count(*) from research_culture_form_support "
            "where support_strength='controlled_explicit' and research_tier<>'strict_semantic'"
        ).fetchone()[0]),
        "automatic_actor_or_place_carriers": int(con.execute(
            "select count(*) from research_culture_form_support s join research_culture_form_rules r on r.rule_id=s.rule_id "
            "join research_entities e on e.entity_id=s.entity_id where r.rule_kind='direct_type' "
            "and e.entity_type in ('Person','Place','AdministrativeRegion','CulturalSite','Organization','Institution','SocialGroup')"
        ).fetchone()[0]),
        "event_carrier_assignments": int(con.execute(
            "select count(*) from research_entity_culture_forms f join research_entities e on e.entity_id=f.entity_id "
            "where e.entity_type='Event' and f.culture_role like '%carrier%'"
        ).fetchone()[0]),
        "source_hash_unchanged": sha256(input_path) == input_hash,
    }
    passed = (
        checks["quick_check"] == "ok"
        and checks["foreign_key_errors"] == 0
        and all(checks[key] == 0 for key in checks if key not in {"quick_check", "foreign_key_errors", "source_hash_unchanged"})
        and checks["source_hash_unchanged"]
        and counts["culture_forms"] == 7
    )
    return {"counts": counts, "checks": checks, "pass": passed}


def build(input_path: Path, semantic_path: Path, output_path: Path, report_path: Path) -> dict:
    input_path = input_path.resolve()
    semantic_path = semantic_path.resolve()
    output_path = output_path.resolve()
    report_path = report_path.resolve()
    input_hash = sha256(input_path)
    semantic_hash = sha256(semantic_path)
    event_mapping = load_yaml(EVENT_MAPPING)
    culture_mapping = load_yaml(CULTURE_MAPPING)
    mapping_failures = validate_mappings(event_mapping, culture_mapping)
    if mapping_failures:
        raise RuntimeError("mapping validation failed: " + "; ".join(mapping_failures))
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(temporary) + suffix).unlink(missing_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(input_path, temporary)
    con = sqlite3.connect(temporary, timeout=120)
    con.execute("pragma foreign_keys=on")
    con.execute("pragma journal_mode=delete")
    con.execute("pragma synchronous=full")
    con.create_function("v2_counterpart_allowed", 2, counterpart_allowed, deterministic=True)
    con.execute("attach database ? as sem", (f"file:{semantic_path.as_posix()}?mode=ro",))
    try:
        con.executescript(SCHEMA_SQL)
        con.execute("begin immediate")
        con.executemany(
            "insert into research_event_role_catalog values(?,?,?,?,?,?,?)",
            [(
                f"EVENT-ROLE:{item['predicate']}:{item['event_endpoint']}", item["predicate"],
                item["event_endpoint"], item["role_code"], item["role_category"],
                json.dumps(item["counterpart_types"], ensure_ascii=False), item["analysis_strength"],
            ) for item in event_mapping["mappings"]],
        )
        con.execute(
            "insert into research_event_assertion_links "
            "select a.subject_id,a.subject_name,a.fact_id,'subject',a.object_id,a.object_name,a.object_type,a.predicate,a.research_tier,"
            "case a.research_tier when 'strict_semantic' then 'strict_controlled' when 'contextual' then 'contextual' else 'unresolved' end,"
            "a.time_role,a.time_owner_id,"
            "case when a.time_role='event_occurrence' and a.time_owner_id=a.subject_id then a.time_start end,"
            "case when a.time_role='event_occurrence' and a.time_owner_id=a.subject_id then a.time_end end,"
            "case when a.time_role='event_occurrence' and a.time_owner_id=a.subject_id then a.normalized_time_label end,"
            "case when a.time_role='event_occurrence' and a.time_owner_id=a.subject_id then 'asserted_candidate' else 'none' end,"
            "a.space_role,a.space_owner_id,"
            "case when a.space_role='event_location' and a.space_owner_id=a.subject_id then a.canonical_space_anchor_id end "
            "from research_assertions a where a.subject_type='Event' "
            "union all "
            "select a.object_id,a.object_name,a.fact_id,'object',a.subject_id,a.subject_name,a.subject_type,a.predicate,a.research_tier,"
            "case a.research_tier when 'strict_semantic' then 'strict_controlled' when 'contextual' then 'contextual' else 'unresolved' end,"
            "a.time_role,a.time_owner_id,"
            "case when a.time_role='event_occurrence' and a.time_owner_id=a.object_id then a.time_start end,"
            "case when a.time_role='event_occurrence' and a.time_owner_id=a.object_id then a.time_end end,"
            "case when a.time_role='event_occurrence' and a.time_owner_id=a.object_id then a.normalized_time_label end,"
            "case when a.time_role='event_occurrence' and a.time_owner_id=a.object_id then 'asserted_candidate' else 'none' end,"
            "a.space_role,a.space_owner_id,"
            "case when a.space_role='event_location' and a.space_owner_id=a.object_id then a.canonical_space_anchor_id end "
            "from research_assertions a where a.object_type='Event'"
        )
        con.execute(
            "update research_event_assertion_links set occurrence_time_status='model_adjudicated' "
            "where occurrence_time_start is not null and fact_id in ("
            "select j.value from sem.v2_event_time_closures c,"
            "json_each(c.effective_partition_json,'$.event_occurrence_fact_ids') j)"
        )
        con.execute(
            "with consensus as (select event_id from research_event_assertion_links "
            "where occurrence_time_start is not null group by event_id "
            "having count(distinct fact_id)>=2 and count(distinct substr(occurrence_time_start,1,4))=1) "
            "update research_event_assertion_links set occurrence_time_status='source_consensus' "
            "where occurrence_time_status='asserted_candidate' and event_id in (select event_id from consensus)"
        )
        con.execute(
            "insert into research_event_roles "
            "select l.event_id,l.fact_id,l.event_endpoint,l.counterpart_id,l.counterpart_name,l.counterpart_type,l.predicate,"
            "c.role_code,c.role_category,c.analysis_strength,c.mapping_id "
            "from research_event_assertion_links l join research_event_role_catalog c "
            "on c.predicate=l.predicate and c.event_endpoint=l.event_endpoint "
            "where l.research_tier='strict_semantic' "
            "and v2_counterpart_allowed(l.counterpart_type,c.counterpart_types_json)=1"
        )
        con.execute(
            "insert into research_event_relations "
            "select fact_id,subject_id,subject_name,object_id,object_name,predicate,"
            "case predicate when 'part_of' then 'explicit_structure' else 'explicit_context' end,'not_inferred' "
            "from research_assertions where research_tier='strict_semantic' "
            "and subject_type='Event' and object_type='Event' and predicate in ('part_of','influenced')"
        )
        con.execute(
            "insert into research_event_frames "
            "with ls as (select event_id,count(distinct fact_id) all_n,"
            "count(distinct case when research_tier='strict_semantic' then fact_id end) strict_n,"
            "count(distinct case when occurrence_time_start is not null then fact_id end) time_n,"
            "count(distinct case when occurrence_time_status in ('model_adjudicated','source_consensus') then fact_id end) trusted_time_n,"
            "count(distinct case when event_location_id is not null then fact_id end) place_n,"
            "min(occurrence_time_start) t0,max(occurrence_time_end) t1 from research_event_assertion_links group by event_id),"
            "rs as (select event_id,count(*) role_n from research_event_roles group by event_id),"
            "ss as (select l.event_id,count(distinct m.stage_code) stage_n from research_event_assertion_links l "
            "join research_assertion_stage_memberships m on m.fact_id=l.fact_id where l.occurrence_time_start is not null group by l.event_id),"
            "gs as (select l.event_id,count(distinct m.region_id) region_n from research_event_assertion_links l "
            "join research_assertion_regions m on m.fact_id=l.fact_id where l.event_location_id is not null group by l.event_id) "
            "select e.entity_id,e.canonical_name,coalesce(ls.all_n,0),coalesce(ls.strict_n,0),coalesce(rs.role_n,0),"
            "coalesce(ls.time_n,0),coalesce(ls.trusted_time_n,0),coalesce(ls.place_n,0),coalesce(ss.stage_n,0),coalesce(gs.region_n,0),ls.t0,ls.t1,"
            "case when coalesce(ls.trusted_time_n,0)>0 then 'trusted' when coalesce(ls.time_n,0)>0 then 'asserted_candidate' else 'none' end,"
            "case when coalesce(ls.strict_n,0)>0 then 'strict_backbone' when coalesce(ls.all_n,0)>0 then 'context_only' else 'isolated' end "
            "from research_entities e left join ls on ls.event_id=e.entity_id left join rs on rs.event_id=e.entity_id "
            "left join ss on ss.event_id=e.entity_id left join gs on gs.event_id=e.entity_id where e.entity_type='Event'"
        )
        con.executemany(
            "insert into research_culture_forms values(?,?)",
            [(item["code"], item["label_zh"]) for item in culture_mapping["culture_forms"]],
        )
        for rule in culture_mapping["direct_type_rules"]:
            con.execute(
                "insert into research_culture_form_rules values(?,?,?,?,?,?,?,?)",
                (rule["rule_id"], "direct_type", json.dumps([rule["entity_type"]], ensure_ascii=False),
                 None, None, rule["culture_form"], rule["culture_role"], rule["support_strength"]),
            )
            tier_clause = "='strict_semantic'" if rule["entity_type"] == "Event" else "<>'unresolved'"
            con.execute(
                "insert or ignore into research_culture_form_support "
                f"select subject_id,?,fact_id,?,?,?,research_tier from research_assertions where subject_type=? and research_tier{tier_clause}",
                (rule["culture_form"], rule["rule_id"], rule["culture_role"], rule["support_strength"], rule["entity_type"]),
            )
            con.execute(
                "insert or ignore into research_culture_form_support "
                f"select object_id,?,fact_id,?,?,?,research_tier from research_assertions where object_type=? and research_tier{tier_clause}",
                (rule["culture_form"], rule["rule_id"], rule["culture_role"], rule["support_strength"], rule["entity_type"]),
            )
        for rule in culture_mapping["relation_rules"]:
            con.execute(
                "insert into research_culture_form_rules values(?,?,?,?,?,?,?,?)",
                (rule["rule_id"], "controlled_relation", json.dumps(rule["entity_types"], ensure_ascii=False),
                 rule["predicate"], rule["entity_endpoint"], rule["culture_form"], rule["culture_role"],
                 rule["support_strength"]),
            )
            entity_id = "subject_id" if rule["entity_endpoint"] == "subject" else "object_id"
            entity_type = "subject_type" if rule["entity_endpoint"] == "subject" else "object_type"
            placeholders = ",".join("?" for _ in rule["entity_types"])
            con.execute(
                "insert or ignore into research_culture_form_support "
                f"select {entity_id},?,fact_id,?,?,?,research_tier from research_assertions "
                f"where research_tier='strict_semantic' and predicate=? and {entity_type} in ({placeholders})",
                (rule["culture_form"], rule["rule_id"], rule["culture_role"], rule["support_strength"],
                 rule["predicate"], *rule["entity_types"]),
            )
        con.execute(
            "insert into research_entity_culture_forms "
            "select s.entity_id,e.canonical_name,e.entity_type,s.culture_form_code,s.culture_role,"
            "case when max(s.support_strength='controlled_explicit')=1 then 'controlled_explicit' else 'typed_context_supported' end,"
            "count(distinct s.fact_id),count(distinct case when s.research_tier='strict_semantic' then s.fact_id end) "
            "from research_culture_form_support s join research_entities e on e.entity_id=s.entity_id "
            "group by s.entity_id,s.culture_form_code,s.culture_role"
        )
        con.execute(
            "insert into research_spirit_value_links "
            "select fact_id,subject_id,subject_name,object_id,object_name,'has_value_facet' "
            "from research_assertions where research_tier='strict_semantic' and predicate='has_value_facet' "
            "and subject_type='Spirit' and object_type='ValueFacet'"
        )
        con.commit()
        validation = validate_database(con, input_hash, input_path)
        if not validation["pass"]:
            raise RuntimeError("V2 event/culture validation failed: " + json.dumps(validation, ensure_ascii=False))
    except Exception:
        con.rollback()
        con.close()
        temporary.unlink(missing_ok=True)
        raise
    con.close()
    if sha256(input_path) != input_hash:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("research base changed during event/culture build")
    if sha256(semantic_path) != semantic_hash:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("semantic V2 changed during event/culture build")
    os.replace(temporary, output_path)
    payload = {
        "status": "PASS", "build_version": BUILD_VERSION,
        "input": {"path": str(input_path), "sha256": input_hash, "unchanged": True},
        "semantic_v2": {"path": str(semantic_path), "sha256": semantic_hash, "unchanged": True},
        "mappings": {"event": str(EVENT_MAPPING), "culture": str(CULTURE_MAPPING)},
        "output": {"path": str(output_path), "sha256": sha256(output_path), "size_bytes": output_path.stat().st_size},
        "validation": validation,
        "limitations": [
            "event sequence alone never creates causality or evolution",
            "event time and place require assertion-level ownership",
            "person, place, organization, institution and cultural site are not automatic culture carriers",
            "spirit is an optional analytical clue rather than a mandatory graph hub",
        ],
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_report = report_path.with_name(f".{report_path.name}.tmp")
    temporary_report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary_report, report_path)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--semantic-v2", type=Path, default=SEMANTIC_V2)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    print(json.dumps(build(args.input, args.semantic_v2, args.output, args.report), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
