"""Build tiered CultureStates and explicit evolution transitions for STKG V2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from stkg_contract import RELATIONS  # noqa: E402


INPUT = ROOT / "derived" / "red_culture_stkg_event_culture_v2.sqlite"
OUTPUT = ROOT / "derived" / "red_culture_stkg_evolution_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_evolution.json"
RULES = ROOT / "stkg" / "schema" / "evolution_rules_v1.yaml"
BUILD_VERSION = "red-culture-stkg-evolution-v2-1"

TIER_RANK = {"relation_context": 1, "asserted_event_spacetime": 2, "trusted_event_spacetime": 3}


SCHEMA_SQL = r"""
create table research_event_spatiotemporal_cells(
  cell_id text primary key,
  event_id text not null references research_entities(entity_id),
  event_name text not null,
  stage_code text not null references research_historical_stages(stage_code),
  stage_label_zh text not null,
  stage_order integer not null,
  region_id text not null references research_study_regions(region_id),
  province_name text not null,
  basin_section_id text not null references research_basin_sections(basin_section_id),
  observation_tier text not null check(observation_tier in ('trusted_event_spacetime','asserted_event_spacetime','relation_context')),
  time_evidence_count integer not null check(time_evidence_count>=0),
  place_evidence_count integer not null check(place_evidence_count>=0),
  context_evidence_count integer not null check(context_evidence_count>=0),
  unique(event_id,stage_code,region_id)
) without rowid;

create table research_event_cell_support(
  cell_id text not null references research_event_spatiotemporal_cells(cell_id),
  fact_id text not null references research_assertions(fact_id),
  support_role text not null check(support_role in ('event_time','event_place','relation_context')),
  primary key(cell_id,fact_id,support_role)
) without rowid;

create table research_culture_states(
  state_id text primary key,
  culture_subject_id text not null references research_entities(entity_id),
  culture_subject_name text not null,
  culture_subject_type text not null,
  culture_form_code text not null references research_culture_forms(culture_form_code),
  stage_code text not null references research_historical_stages(stage_code),
  stage_label_zh text not null,
  stage_order integer not null,
  region_id text not null references research_study_regions(region_id),
  province_name text not null,
  basin_section_id text not null references research_basin_sections(basin_section_id),
  observation_tier text not null check(observation_tier in ('trusted_event_spacetime','asserted_event_spacetime','relation_context')),
  supporting_fact_count integer not null check(supporting_fact_count>=1),
  supporting_event_count integer not null check(supporting_event_count>=1),
  source_member_count integer not null check(source_member_count>=supporting_fact_count),
  has_controlled_explicit_support integer not null check(has_controlled_explicit_support in (0,1)),
  state_status text not null check(state_status in ('stable_multi_event','explicit_single_event','context_candidate')),
  state_key text not null unique
) without rowid;

create table research_culture_state_support(
  state_id text not null references research_culture_states(state_id),
  fact_id text not null references research_assertions(fact_id),
  support_role text not null check(support_role in ('event_time','event_place','relation_context','culture_relation')),
  primary key(state_id,fact_id,support_role)
) without rowid;

create table research_culture_state_events(
  state_id text not null references research_culture_states(state_id),
  event_id text not null references research_entities(entity_id),
  event_name text not null,
  cell_id text not null references research_event_spatiotemporal_cells(cell_id),
  primary key(state_id,event_id,cell_id)
) without rowid;

create table research_culture_state_roles(
  state_id text not null references research_culture_states(state_id),
  culture_role text not null,
  primary key(state_id,culture_role)
) without rowid;

create table research_culture_state_actors(
  state_id text not null references research_culture_states(state_id),
  actor_id text not null references research_entities(entity_id),
  actor_name text not null,
  event_role_code text not null,
  event_id text not null references research_entities(entity_id),
  fact_id text not null references research_assertions(fact_id),
  primary key(state_id,actor_id,event_role_code,event_id,fact_id)
) without rowid;

create table research_culture_state_semantic_members(
  state_id text not null references research_culture_states(state_id),
  semantic_entity_id text not null references research_entities(entity_id),
  semantic_entity_name text not null,
  semantic_entity_type text not null check(semantic_entity_type in ('Spirit','ValueFacet')),
  event_id text not null references research_entities(entity_id),
  fact_id text not null references research_assertions(fact_id),
  primary key(state_id,semantic_entity_id,event_id,fact_id)
) without rowid;

create table research_first_observed_states(
  state_id text primary key references research_culture_states(state_id),
  culture_subject_id text not null references research_entities(entity_id),
  culture_form_code text not null references research_culture_forms(culture_form_code),
  stage_order integer not null,
  observation_status text not null check(observation_status='first_observed_in_dataset_not_historical_origin')
) without rowid;

create table research_transition_types(
  transition_type text primary key
) without rowid;

create table research_transition_rules(
  rule_id text primary key,
  rule_kind text not null check(rule_kind in ('direct_shared_fact','spatial_explicit_predicate')),
  predicate text not null,
  transition_type text not null references research_transition_types(transition_type),
  rule_json text not null check(json_valid(rule_json))
) without rowid;

create table research_evolution_transition_candidates(
  candidate_id text primary key,
  rule_id text not null references research_transition_rules(rule_id),
  transition_type text not null references research_transition_types(transition_type),
  from_state_id text not null references research_culture_states(state_id),
  to_state_id text not null references research_culture_states(state_id),
  supporting_fact_id text not null references research_assertions(fact_id),
  derivation_kind text not null check(derivation_kind in ('direct_shared_fact','spatial_explicit_predicate')),
  review_status text not null check(review_status in ('structurally_validated_explicit','requires_review_spatial_source')),
  confidence real not null check(confidence between 0 and 1),
  publication_eligible integer not null check(publication_eligible in (0,1)),
  publication_gate_reason text not null check(publication_gate_reason in ('unique_explicit_spatiotemporal_match','unique_trusted_state_pair','ambiguous_spatiotemporal_expansion','nontrusted_state','spatial_review_required')),
  unique(rule_id,from_state_id,to_state_id,supporting_fact_id)
) without rowid;

create table research_evolution_transitions(
  transition_id text primary key,
  transition_type text not null references research_transition_types(transition_type),
  from_state_id text not null references research_culture_states(state_id),
  to_state_id text not null references research_culture_states(state_id),
  derivation_rule text not null references research_transition_rules(rule_id),
  review_status text not null check(review_status='published_structural_explicit'),
  confidence real not null check(confidence between 0 and 1),
  supporting_fact_count integer not null check(supporting_fact_count>=1),
  unique(transition_type,from_state_id,to_state_id)
) without rowid;

create table research_evolution_transition_support(
  transition_id text not null references research_evolution_transitions(transition_id),
  candidate_id text not null references research_evolution_transition_candidates(candidate_id),
  supporting_fact_id text not null references research_assertions(fact_id),
  primary key(transition_id,candidate_id)
) without rowid;

create table research_stage_region_culture_metrics(
  stage_code text not null references research_historical_stages(stage_code),
  region_id text not null references research_study_regions(region_id),
  culture_form_code text not null references research_culture_forms(culture_form_code),
  observation_tier text not null,
  state_count integer not null,
  entity_count integer not null,
  event_count integer not null,
  supporting_fact_count integer not null,
  primary key(stage_code,region_id,culture_form_code,observation_tier)
) without rowid;

create index idx_research_cell_event on research_event_spatiotemporal_cells(event_id,stage_code,region_id);
create index idx_research_cell_stage_region on research_event_spatiotemporal_cells(stage_code,region_id,observation_tier);
create index idx_research_state_subject on research_culture_states(culture_subject_id,culture_form_code);
create index idx_research_state_stage_region on research_culture_states(stage_code,region_id,culture_form_code);
create index idx_research_state_tier on research_culture_states(observation_tier,state_status);
create index idx_research_state_support_fact on research_culture_state_support(fact_id,state_id);
create index idx_research_state_event on research_culture_state_events(event_id,state_id);
create index idx_research_state_actor on research_culture_state_actors(actor_id,state_id);
create index idx_research_transition_from on research_evolution_transitions(from_state_id,transition_type);
create index idx_research_transition_to on research_evolution_transitions(to_state_id,transition_type);
create index idx_research_transition_support_fact on research_evolution_transition_support(supporting_fact_id,transition_id);

create view v_research_trusted_culture_states as
select * from research_culture_states where observation_tier='trusted_event_spacetime';

create view v_research_contextual_culture_states as
select * from research_culture_states where observation_tier<>'trusted_event_spacetime';

create view v_research_culture_state_trajectory as
select s.*,f.label_zh culture_form_label_zh,b.basin_section_name
from research_culture_states s join research_culture_forms f on f.culture_form_code=s.culture_form_code
join research_basin_sections b on b.basin_section_id=s.basin_section_id;

create view v_research_stage_culture_metrics as
select stage_code,culture_form_code,observation_tier,sum(state_count) state_count,
       sum(entity_count) regional_entity_count,sum(event_count) regional_event_count,
       sum(supporting_fact_count) supporting_fact_count
from research_stage_region_culture_metrics
group by stage_code,culture_form_code,observation_tier;

create view v_research_published_evolution as
select t.transition_id,t.transition_type,fs.culture_subject_name from_subject,
       ts.culture_subject_name to_subject,fs.stage_label_zh,fs.province_name,
       t.supporting_fact_count,t.confidence
from research_evolution_transitions t
join research_culture_states fs on fs.state_id=t.from_state_id
join research_culture_states ts on ts.state_id=t.to_state_id;
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


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def evidence_tier(time_status: str | None, explicit_space: bool) -> str:
    if explicit_space and time_status in {"model_adjudicated", "source_consensus"}:
        return "trusted_event_spacetime"
    if explicit_space and time_status == "asserted_candidate":
        return "asserted_event_spacetime"
    return "relation_context"


def select_unique_candidate_ids(rows: list[dict], explicit_regions: set[str], explicit_stages: set[str]) -> set[str]:
    remaining = list(rows)
    if explicit_regions:
        remaining = [row for row in remaining if row["region_id"] in explicit_regions]
    if explicit_stages:
        remaining = [row for row in remaining if row["stage_code"] in explicit_stages]
    return {str(remaining[0]["candidate_id"])} if len(remaining) == 1 else set()


def validate_rules(contract: dict, culture_forms: set[str]) -> list[str]:
    failures = []
    flags = contract.get("rules") or {}
    for flag in (
        "sequence_alone_never_creates_transition", "cooccurrence_never_creates_transition",
        "direct_transition_requires_shared_supporting_fact", "spatial_spread_requires_explicit_spread_predicate",
        "first_observed_is_not_historical_origin", "candidate_and_published_transition_are_separate",
    ):
        if flags.get(flag) is not True:
            failures.append(f"evolution rule is not true: {flag}")
    transition_types = set(contract.get("transition_types") or [])
    if len(transition_types) != 13:
        failures.append("transition type catalog must contain 13 unique values")
    seen = set()
    for rule in (contract.get("direct_rules") or []) + (contract.get("spatial_spread_rules") or []):
        if rule.get("rule_id") in seen:
            failures.append(f"duplicate transition rule: {rule.get('rule_id')}")
        seen.add(rule.get("rule_id"))
        if rule.get("predicate") not in RELATIONS or rule.get("transition_type") not in transition_types:
            failures.append(f"invalid transition rule: {rule.get('rule_id')}")
    for rule in contract.get("direct_rules") or []:
        if not set(rule.get("from_forms") or []) <= culture_forms or not set(rule.get("to_forms") or []) <= culture_forms:
            failures.append(f"unknown culture form in transition rule: {rule.get('rule_id')}")
    return failures


def collect_event_cells(con: sqlite3.Connection) -> tuple[list[tuple], list[tuple]]:
    cells: dict[tuple[str, str, str], dict] = {}
    explicit_sql = """
    select t.event_id,t.event_name,sm.stage_code,h.stage_label_zh,h.stage_order,
           rm.region_id,r.province_name,rh.basin_section_id,t.fact_id,p.fact_id,t.occurrence_time_status
    from research_event_assertion_links t
    join research_assertion_stage_memberships sm on sm.fact_id=t.fact_id
    join research_historical_stages h on h.stage_code=sm.stage_code
    join research_event_assertion_links p on p.event_id=t.event_id and p.event_location_id is not null
    join research_assertion_regions rm on rm.fact_id=p.fact_id
    join research_study_regions r on r.region_id=rm.region_id
    join research_region_hierarchy rh on rh.region_id=rm.region_id
    where t.occurrence_time_start is not null
    """
    for row in con.execute(explicit_sql):
        event_id, event_name, stage, stage_label, stage_order, region, province, basin, time_fact, place_fact, status = row
        tier = evidence_tier(str(status), True)
        key = (str(event_id), str(stage), str(region))
        item = cells.setdefault(key, {
            "event_name": event_name, "stage_label": stage_label, "stage_order": stage_order,
            "province": province, "basin": basin, "tier": tier,
            "time": set(), "place": set(), "context": set(),
        })
        if TIER_RANK[tier] > TIER_RANK[item["tier"]]:
            item["tier"] = tier
        item["time"].add(str(time_fact))
        item["place"].add(str(place_fact))
    context_sql = """
    select l.event_id,l.event_name,sm.stage_code,h.stage_label_zh,h.stage_order,
           rm.region_id,r.province_name,rh.basin_section_id,l.fact_id
    from research_event_assertion_links l
    join research_assertion_stage_memberships sm on sm.fact_id=l.fact_id
    join research_historical_stages h on h.stage_code=sm.stage_code
    join research_assertion_regions rm on rm.fact_id=l.fact_id
    join research_study_regions r on r.region_id=rm.region_id
    join research_region_hierarchy rh on rh.region_id=rm.region_id
    where l.research_tier='strict_semantic'
    """
    for row in con.execute(context_sql):
        event_id, event_name, stage, stage_label, stage_order, region, province, basin, fact_id = row
        key = (str(event_id), str(stage), str(region))
        item = cells.setdefault(key, {
            "event_name": event_name, "stage_label": stage_label, "stage_order": stage_order,
            "province": province, "basin": basin, "tier": "relation_context",
            "time": set(), "place": set(), "context": set(),
        })
        item["context"].add(str(fact_id))
    cell_rows = []
    support_rows = []
    for (event_id, stage, region), item in sorted(cells.items()):
        cell_id = stable_id("CELL", event_id, stage, region)
        cell_rows.append((
            cell_id, event_id, item["event_name"], stage, item["stage_label"], item["stage_order"],
            region, item["province"], item["basin"], item["tier"],
            len(item["time"]), len(item["place"]), len(item["context"]),
        ))
        support_rows.extend((cell_id, fact, "event_time") for fact in sorted(item["time"]))
        support_rows.extend((cell_id, fact, "event_place") for fact in sorted(item["place"]))
        support_rows.extend((cell_id, fact, "relation_context") for fact in sorted(item["context"]))
    return cell_rows, support_rows


def collect_counts(con: sqlite3.Connection) -> dict[str, int]:
    queries = {
        "event_spatiotemporal_cells": "select count(*) from research_event_spatiotemporal_cells",
        "trusted_event_cells": "select count(*) from research_event_spatiotemporal_cells where observation_tier='trusted_event_spacetime'",
        "asserted_event_cells": "select count(*) from research_event_spatiotemporal_cells where observation_tier='asserted_event_spacetime'",
        "context_event_cells": "select count(*) from research_event_spatiotemporal_cells where observation_tier='relation_context'",
        "culture_states": "select count(*) from research_culture_states",
        "trusted_culture_states": "select count(*) from v_research_trusted_culture_states",
        "contextual_culture_states": "select count(*) from v_research_contextual_culture_states",
        "state_support_rows": "select count(*) from research_culture_state_support",
        "state_event_rows": "select count(*) from research_culture_state_events",
        "state_actor_rows": "select count(*) from research_culture_state_actors",
        "state_semantic_rows": "select count(*) from research_culture_state_semantic_members",
        "first_observed_states": "select count(*) from research_first_observed_states",
        "transition_types": "select count(*) from research_transition_types",
        "transition_rules": "select count(*) from research_transition_rules",
        "transition_candidates": "select count(*) from research_evolution_transition_candidates",
        "published_transitions": "select count(*) from research_evolution_transitions",
        "stage_region_metric_rows": "select count(*) from research_stage_region_culture_metrics",
    }
    return {key: int(con.execute(sql).fetchone()[0]) for key, sql in queries.items()}


def validate_database(con: sqlite3.Connection, input_path: Path, input_hash: str) -> dict:
    counts = collect_counts(con)
    checks = {
        "quick_check": str(con.execute("pragma quick_check").fetchone()[0]),
        "foreign_key_errors": len(con.execute("pragma foreign_key_check").fetchall()),
        "cells_without_support": int(con.execute(
            "select count(*) from research_event_spatiotemporal_cells c where not exists("
            "select 1 from research_event_cell_support s where s.cell_id=c.cell_id)"
        ).fetchone()[0]),
        "states_without_events": int(con.execute(
            "select count(*) from research_culture_states s where not exists("
            "select 1 from research_culture_state_events e where e.state_id=s.state_id)"
        ).fetchone()[0]),
        "states_without_support": int(con.execute(
            "select count(*) from research_culture_states s where not exists("
            "select 1 from research_culture_state_support x where x.state_id=s.state_id)"
        ).fetchone()[0]),
        "trusted_states_without_trusted_cell": int(con.execute(
            "select count(*) from research_culture_states s where s.observation_tier='trusted_event_spacetime' "
            "and not exists(select 1 from research_culture_state_events e join research_event_spatiotemporal_cells c "
            "on c.cell_id=e.cell_id where e.state_id=s.state_id and c.observation_tier='trusted_event_spacetime')"
        ).fetchone()[0]),
        "unsupported_transition_candidates": int(con.execute(
            "select count(*) from research_evolution_transition_candidates c join research_transition_rules r on r.rule_id=c.rule_id "
            "join research_assertions a on a.fact_id=c.supporting_fact_id where a.predicate<>r.predicate"
        ).fetchone()[0]),
        "sequence_or_cooccurrence_candidates": int(con.execute(
            "select count(*) from research_evolution_transition_candidates where derivation_kind not in "
            "('direct_shared_fact','spatial_explicit_predicate')"
        ).fetchone()[0]),
        "published_ineligible_candidates": int(con.execute(
            "select count(*) from research_evolution_transition_support x join research_evolution_transition_candidates c "
            "on c.candidate_id=x.candidate_id where c.publication_eligible<>1"
        ).fetchone()[0]),
        "published_nontrusted_states": int(con.execute(
            "select count(*) from research_evolution_transitions t join research_culture_states f on f.state_id=t.from_state_id "
            "join research_culture_states x on x.state_id=t.to_state_id "
            "where f.observation_tier<>'trusted_event_spacetime' or x.observation_tier<>'trusted_event_spacetime'"
        ).fetchone()[0]),
        "published_ambiguous_candidates": int(con.execute(
            "select count(*) from research_evolution_transition_support x join research_evolution_transition_candidates c "
            "on c.candidate_id=x.candidate_id where c.publication_gate_reason not in "
            "('unique_explicit_spatiotemporal_match','unique_trusted_state_pair')"
        ).fetchone()[0]),
        "published_transition_count_mismatches": int(con.execute(
            "select count(*) from research_evolution_transitions t where t.supporting_fact_count<>("
            "select count(distinct x.supporting_fact_id) from research_evolution_transition_support x "
            "where x.transition_id=t.transition_id)"
        ).fetchone()[0]),
        "source_hash_unchanged": sha256(input_path) == input_hash,
    }
    passed = (
        checks["quick_check"] == "ok" and checks["foreign_key_errors"] == 0
        and all(checks[key] == 0 for key in checks if key not in {"quick_check", "foreign_key_errors", "source_hash_unchanged"})
        and checks["source_hash_unchanged"] and counts["transition_types"] == 13
    )
    return {"counts": counts, "checks": checks, "pass": passed}


def build(input_path: Path, output_path: Path, report_path: Path, rules_path: Path) -> dict:
    input_path = input_path.resolve()
    output_path = output_path.resolve()
    report_path = report_path.resolve()
    rules_path = rules_path.resolve()
    input_hash = sha256(input_path)
    contract = load_yaml(rules_path)
    source = sqlite3.connect(f"file:{input_path.as_posix()}?mode=ro", uri=True)
    try:
        culture_forms = {str(row[0]) for row in source.execute("select culture_form_code from research_culture_forms")}
    finally:
        source.close()
    failures = validate_rules(contract, culture_forms)
    if failures:
        raise RuntimeError("evolution rule validation failed: " + "; ".join(failures))
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(temporary) + suffix).unlink(missing_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(input_path, temporary)
    con = sqlite3.connect(temporary, timeout=120)
    con.execute("pragma foreign_keys=on")
    con.execute("pragma journal_mode=delete")
    con.execute("pragma synchronous=full")
    try:
        con.executescript(SCHEMA_SQL)
        con.execute("begin immediate")
        con.execute("pragma defer_foreign_keys=on")
        cell_rows, cell_support = collect_event_cells(con)
        con.executemany("insert into research_event_spatiotemporal_cells values(?,?,?,?,?,?,?,?,?,?,?,?,?)", cell_rows)
        con.executemany("insert into research_event_cell_support values(?,?,?)", cell_support)
        con.executescript("""
        create temp table temp_state_observation(
          entity_id text not null,culture_form_code text not null,stage_code text not null,
          region_id text not null,basin_section_id text not null,event_id text not null,
          cell_id text not null,culture_role text not null,role_fact_id text,
          explicit_support integer not null,tier_rank integer not null
        );
        insert into temp_state_observation
        select c.event_id,'HistoricalPractice',c.stage_code,c.region_id,c.basin_section_id,c.event_id,c.cell_id,
               'culture_subject',null,0,
               case c.observation_tier when 'trusted_event_spacetime' then 3 when 'asserted_event_spacetime' then 2 else 1 end
        from research_event_spatiotemporal_cells c
        join research_entity_culture_forms f on f.entity_id=c.event_id and f.culture_form_code='HistoricalPractice';
        insert into temp_state_observation
        select f.entity_id,f.culture_form_code,c.stage_code,c.region_id,c.basin_section_id,c.event_id,c.cell_id,
               f.culture_role,r.fact_id,(f.assignment_status='controlled_explicit'),
               case c.observation_tier when 'trusted_event_spacetime' then 3 when 'asserted_event_spacetime' then 2 else 1 end
        from research_event_spatiotemporal_cells c
        join research_event_roles r on r.event_id=c.event_id
        join research_entity_culture_forms f on f.entity_id=r.counterpart_id
        where r.counterpart_type<>'Event';
        create index temp.idx_state_observation on temp_state_observation(entity_id,culture_form_code,stage_code,region_id);
        """)
        state_groups = list(con.execute(
            "select o.entity_id,e.canonical_name,e.entity_type,o.culture_form_code,o.stage_code,h.stage_label_zh,h.stage_order,"
            "o.region_id,r.province_name,o.basin_section_id,max(o.tier_rank),count(distinct o.event_id),max(o.explicit_support) "
            "from temp_state_observation o join research_entities e on e.entity_id=o.entity_id "
            "join research_historical_stages h on h.stage_code=o.stage_code "
            "join research_study_regions r on r.region_id=o.region_id "
            "group by o.entity_id,o.culture_form_code,o.stage_code,o.region_id,o.basin_section_id"
        ))
        state_map = {}
        preliminary = []
        for row in state_groups:
            entity, name, typ, form, stage, stage_label, stage_order, region, province, basin, tier_rank, event_count, explicit = row
            state_id = stable_id("STATE", entity, form, stage, region)
            state_map[(entity, form, stage, region)] = state_id
            tier = {1: "relation_context", 2: "asserted_event_spacetime", 3: "trusted_event_spacetime"}[int(tier_rank)]
            status = "stable_multi_event" if int(event_count) >= 2 else "explicit_single_event" if int(tier_rank) >= 2 else "context_candidate"
            preliminary.append((state_id, entity, name, typ, form, stage, stage_label, stage_order, region, province,
                                basin, tier, int(event_count), int(explicit), status))
        con.execute("create temp table temp_state_id(entity_id text,culture_form_code text,stage_code text,region_id text,state_id text primary key)")
        con.executemany(
            "insert into temp_state_id values(?,?,?,?,?)",
            [(key[0], key[1], key[2], key[3], state_id) for key, state_id in state_map.items()],
        )
        initial_state_rows = []
        for row in preliminary:
            state_id, entity, name, typ, form, stage, stage_label, stage_order, region, province, basin, tier, event_count, explicit, status = row
            initial_state_rows.append((state_id,entity,name,typ,form,stage,stage_label,stage_order,region,province,basin,tier,
                                       1,event_count,1,explicit,status,f"{entity}|{form}|{stage}|{region}"))
        con.executemany("insert into research_culture_states values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", initial_state_rows)
        con.execute(
            "insert into research_culture_state_events "
            "select distinct i.state_id,o.event_id,c.event_name,o.cell_id from temp_state_observation o "
            "join temp_state_id i on i.entity_id=o.entity_id and i.culture_form_code=o.culture_form_code "
            "and i.stage_code=o.stage_code and i.region_id=o.region_id "
            "join research_event_spatiotemporal_cells c on c.cell_id=o.cell_id"
        )
        con.execute(
            "insert into research_culture_state_roles "
            "select distinct i.state_id,o.culture_role from temp_state_observation o join temp_state_id i "
            "on i.entity_id=o.entity_id and i.culture_form_code=o.culture_form_code "
            "and i.stage_code=o.stage_code and i.region_id=o.region_id"
        )
        con.execute(
            "insert or ignore into research_culture_state_support "
            "select distinct i.state_id,s.fact_id,s.support_role from temp_state_observation o "
            "join temp_state_id i on i.entity_id=o.entity_id and i.culture_form_code=o.culture_form_code "
            "and i.stage_code=o.stage_code and i.region_id=o.region_id "
            "join research_event_cell_support s on s.cell_id=o.cell_id"
        )
        con.execute(
            "insert or ignore into research_culture_state_support "
            "select distinct i.state_id,o.role_fact_id,'culture_relation' from temp_state_observation o "
            "join temp_state_id i on i.entity_id=o.entity_id and i.culture_form_code=o.culture_form_code "
            "and i.stage_code=o.stage_code and i.region_id=o.region_id where o.role_fact_id is not null"
        )
        con.execute(
            "insert or ignore into research_culture_state_support "
            "select distinct i.state_id,r.fact_id,'culture_relation' from temp_state_observation o "
            "join temp_state_id i on i.entity_id=o.entity_id and i.culture_form_code=o.culture_form_code "
            "and i.stage_code=o.stage_code and i.region_id=o.region_id "
            "join research_event_roles r on r.event_id=o.event_id "
            "where o.entity_id=o.event_id and o.culture_form_code='HistoricalPractice'"
        )
        for row in preliminary:
            state_id, entity, name, typ, form, stage, stage_label, stage_order, region, province, basin, tier, event_count, explicit, status = row
            fact_count, member_count = con.execute(
                "select count(distinct s.fact_id),sum(a.source_member_count) from ("
                "select distinct fact_id from research_culture_state_support where state_id=?) s "
                "join research_assertions a on a.fact_id=s.fact_id", (state_id,)
            ).fetchone()
            con.execute(
                "update research_culture_states set supporting_fact_count=?,source_member_count=? where state_id=?",
                (int(fact_count), int(member_count or fact_count), state_id),
            )
        con.execute(
            "insert into research_culture_state_actors "
            "select distinct se.state_id,r.counterpart_id,r.counterpart_name,r.role_code,se.event_id,r.fact_id "
            "from research_culture_state_events se join research_event_roles r on r.event_id=se.event_id "
            "where r.role_category='actor'"
        )
        con.execute(
            "insert into research_culture_state_semantic_members "
            "select distinct se.state_id,r.counterpart_id,r.counterpart_name,r.counterpart_type,se.event_id,r.fact_id "
            "from research_culture_state_events se join research_event_roles r on r.event_id=se.event_id "
            "where r.counterpart_type in ('Spirit','ValueFacet')"
        )
        con.execute(
            "insert into research_first_observed_states "
            "with ranked as (select s.*,min(stage_order) over(partition by culture_subject_id,culture_form_code) first_order "
            "from research_culture_states s) select state_id,culture_subject_id,culture_form_code,stage_order,"
            "'first_observed_in_dataset_not_historical_origin' from ranked where stage_order=first_order"
        )
        con.executemany("insert into research_transition_types values(?)", [(item,) for item in contract["transition_types"]])
        for rule in contract["direct_rules"]:
            con.execute("insert into research_transition_rules values(?,?,?,?,?)", (
                rule["rule_id"], "direct_shared_fact", rule["predicate"], rule["transition_type"],
                json.dumps(rule, ensure_ascii=False),
            ))
        for rule in contract["spatial_spread_rules"]:
            con.execute("insert into research_transition_rules values(?,?,?,?,?)", (
                rule["rule_id"], "spatial_explicit_predicate", rule["predicate"], rule["transition_type"],
                json.dumps(rule, ensure_ascii=False),
            ))
        candidates = set()
        for rule in contract["direct_rules"]:
            from_col = "subject_id" if rule["from_endpoint"] == "subject" else "object_id"
            to_col = "subject_id" if rule["to_endpoint"] == "subject" else "object_id"
            from_marks = ",".join("?" for _ in rule["from_forms"])
            to_marks = ",".join("?" for _ in rule["to_forms"])
            sql = (
                f"select distinct fs.state_id,fs.observation_tier,ts.state_id,ts.observation_tier,a.fact_id "
                f"from research_assertions a join research_culture_states fs on fs.culture_subject_id=a.{from_col} "
                f"join research_culture_states ts on ts.culture_subject_id=a.{to_col} "
                "where a.research_tier='strict_semantic' and a.predicate=? "
                f"and fs.culture_form_code in ({from_marks}) and ts.culture_form_code in ({to_marks}) "
                "and fs.stage_code=ts.stage_code and fs.region_id=ts.region_id and fs.state_id<>ts.state_id "
                "and exists(select 1 from research_culture_state_support x where x.state_id=fs.state_id and x.fact_id=a.fact_id) "
                "and exists(select 1 from research_culture_state_support x where x.state_id=ts.state_id and x.fact_id=a.fact_id)"
            )
            for from_id, from_tier, to_id, to_tier, fact_id in con.execute(
                sql, (rule["predicate"], *rule["from_forms"], *rule["to_forms"])
            ):
                eligible = int(from_tier == "trusted_event_spacetime" and to_tier == "trusted_event_spacetime")
                candidate_id = stable_id("TRANS-CAND", rule["rule_id"], from_id, to_id, fact_id)
                candidates.add((candidate_id,rule["rule_id"],rule["transition_type"],from_id,to_id,fact_id,
                                "direct_shared_fact","structurally_validated_explicit",0.95,eligible,"nontrusted_state"))
        for rule in contract["spatial_spread_rules"]:
            subject_col = "subject_id" if rule["culture_subject_endpoint"] == "subject" else "object_id"
            marks = ",".join("?" for _ in rule["culture_subject_types"])
            sql = (
                f"select distinct fs.state_id,ts.state_id,a.fact_id from research_assertions a "
                f"join research_entities e on e.entity_id=a.{subject_col} and e.entity_type in ({marks}) "
                f"join research_culture_states ts on ts.culture_subject_id=a.{subject_col} and ts.culture_form_code=? "
                "join research_culture_states fs on fs.culture_subject_id=ts.culture_subject_id "
                "and fs.culture_form_code=ts.culture_form_code and fs.region_id<>ts.region_id and fs.stage_order<ts.stage_order "
                "where a.research_tier='strict_semantic' and a.predicate=? "
                "and exists(select 1 from research_culture_state_support x where x.state_id=ts.state_id and x.fact_id=a.fact_id)"
            )
            for from_id, to_id, fact_id in con.execute(
                sql, (*rule["culture_subject_types"], rule["culture_form"], rule["predicate"])
            ):
                candidate_id = stable_id("TRANS-CAND", rule["rule_id"], from_id, to_id, fact_id)
                candidates.add((candidate_id,rule["rule_id"],rule["transition_type"],from_id,to_id,fact_id,
                                "spatial_explicit_predicate","requires_review_spatial_source",0.75,0,"spatial_review_required"))
        raw_candidates = sorted(candidates)
        state_dims = {
            str(row[0]): {"stage_code": str(row[1]), "region_id": str(row[2])}
            for row in con.execute("select state_id,stage_code,region_id from research_culture_states")
        }
        trusted_by_fact: dict[str, list[dict]] = defaultdict(list)
        for candidate in raw_candidates:
            if candidate[6] == "direct_shared_fact" and candidate[9] == 1:
                dims = state_dims[str(candidate[3])]
                trusted_by_fact[str(candidate[5])].append({
                    "candidate_id": str(candidate[0]), "stage_code": dims["stage_code"],
                    "region_id": dims["region_id"],
                })
        selected: dict[str, str] = {}
        for fact_id, rows in trusted_by_fact.items():
            regions = {str(row[0]) for row in con.execute(
                "select region_id from research_assertion_regions where fact_id=?", (fact_id,)
            )}
            stages = {str(row[0]) for row in con.execute(
                "select stage_code from research_assertion_stage_memberships where fact_id=?", (fact_id,)
            )}
            chosen = select_unique_candidate_ids(rows, regions, stages)
            reason = "unique_explicit_spatiotemporal_match" if chosen and (regions or stages) else "unique_trusted_state_pair"
            for candidate_id in chosen:
                selected[candidate_id] = reason
        candidate_rows = []
        for candidate in raw_candidates:
            values = list(candidate)
            candidate_id, kind, prior_eligible = str(values[0]), str(values[6]), int(values[9])
            if kind == "spatial_explicit_predicate":
                values[9], values[10] = 0, "spatial_review_required"
            elif not prior_eligible:
                values[9], values[10] = 0, "nontrusted_state"
            elif candidate_id in selected:
                values[9], values[10] = 1, selected[candidate_id]
            else:
                values[9], values[10] = 0, "ambiguous_spatiotemporal_expansion"
            candidate_rows.append(tuple(values))
        con.executemany("insert into research_evolution_transition_candidates values(?,?,?,?,?,?,?,?,?,?,?)", candidate_rows)
        published_groups: dict[tuple[str, str, str, str], list[tuple]] = defaultdict(list)
        for candidate in candidate_rows:
            candidate_id, rule_id, transition_type, from_id, to_id, fact_id, kind, _review, confidence, eligible, _gate = candidate
            if eligible and kind == "direct_shared_fact":
                published_groups[(transition_type,from_id,to_id,rule_id)].append(candidate)
        published = []
        transition_support = []
        for (transition_type, from_id, to_id, rule_id), rows in sorted(published_groups.items()):
            transition_id = stable_id("TRANS", transition_type, from_id, to_id)
            facts = {str(row[5]) for row in rows}
            published.append((transition_id,transition_type,from_id,to_id,rule_id,
                              "published_structural_explicit",max(float(row[8]) for row in rows),len(facts)))
            transition_support.extend((transition_id,str(row[0]),str(row[5])) for row in rows)
        con.executemany("insert into research_evolution_transitions values(?,?,?,?,?,?,?,?)", published)
        con.executemany("insert into research_evolution_transition_support values(?,?,?)", transition_support)
        con.execute(
            "insert into research_stage_region_culture_metrics "
            "select s.stage_code,s.region_id,s.culture_form_code,s.observation_tier,count(distinct s.state_id),"
            "count(distinct s.culture_subject_id),count(distinct e.event_id),count(distinct x.fact_id) "
            "from research_culture_states s join research_culture_state_events e on e.state_id=s.state_id "
            "join research_culture_state_support x on x.state_id=s.state_id "
            "group by s.stage_code,s.region_id,s.culture_form_code,s.observation_tier"
        )
        con.commit()
        validation = validate_database(con, input_path, input_hash)
        if not validation["pass"]:
            raise RuntimeError("V2 evolution validation failed: " + json.dumps(validation, ensure_ascii=False))
    except Exception:
        con.rollback()
        con.close()
        temporary.unlink(missing_ok=True)
        raise
    con.close()
    if sha256(input_path) != input_hash:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("event/culture input changed during V2 evolution build")
    os.replace(temporary, output_path)
    payload = {
        "status": "PASS", "build_version": BUILD_VERSION,
        "input": {"path": str(input_path), "sha256": input_hash, "unchanged": True},
        "rules": {"path": str(rules_path), "sha256": sha256(rules_path)},
        "output": {"path": str(output_path), "sha256": sha256(output_path), "size_bytes": output_path.stat().st_size},
        "validation": validation,
        "limitations": [
            "first observed in this dataset is not a claim of historical origin",
            "sequence and cooccurrence never create evolution transitions",
            "asserted candidate time and relation context remain visible but are excluded from published transitions",
            "spatial spread remains a review candidate unless an explicit source region is present",
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
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--rules", type=Path, default=RULES)
    args = parser.parse_args()
    print(json.dumps(build(args.input, args.output, args.report, args.rules), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
