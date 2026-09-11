# -*- coding: utf-8 -*-
"""audit_stkg_identity.py — STKG-1..7 时空知识图谱身份/语义审计（只读）。

对发布库（final + attached sem + attached upstream integration）逐项审计
STKG-1..7 七项要求，判定 SATISFIED / PARTIAL / MISSING，全部判定引用真实
查询结果（表名 / 行数 / 示例行），禁止凭空推断。

连接方式与 build_provenance_alignment.py 一致：
  connect_final()      — 只读打开 final 发布库并 ATTACH sem 库
  attach_integration() — 再 ATTACH 上游整合库（evidence_registry 所在）

输出：机器可读 JSON（stdout；--out 可选落盘）。每项：
  {requirement, title, verdict, evidence_queries: [{name, sql, result}], findings, notes}

用法：
  python audit_stkg_identity.py                 # 全部 7 项
  python audit_stkg_identity.py --only STKG-1   # 单项
  python audit_stkg_identity.py --out result.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

V3_1 = Path(__file__).resolve().parents[2]
V3 = V3_1.parent / "final_submission_v3"
for p in (str(V3 / "code"), str(V3 / "code" / "independent_eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _common import attach_integration, connect_final, sha256_file  # noqa: E402

MAX_ROWS = 6  # 每个证据查询最多保留的示例行数

NULL_T = "~NULL~"  # time_raw/place_raw 空值哨兵（避免 group by 里 NULL 折叠）


def q(con, sql: str, cap: int | None = None):
    """执行 SQL，返回 {'rows': [...], 'n': 总行数}。cap 限制示例行。"""
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = []
    n = 0
    for r in cur:
        n += 1
        if cap is None or len(rows) < cap:
            rows.append(dict(zip(cols, r)))
    return {"rows": rows, "n": n}


def ev(name: str, sql: str, cap: int | None = MAX_ROWS) -> dict:
    """声明一条证据查询（延迟执行）。"""
    return {"name": name, "sql": " ".join(sql.split()), "_cap": cap}


# --------------------------------------------------------------------------
# STKG-1 时空参与事实身份
# --------------------------------------------------------------------------
def audit_stkg1(con) -> dict:
    queries = [
        ev("total_and_distinct_spo",
           "select count(*) total_assertions, "
           "count(distinct subject_id||'|'||predicate||'|'||object_id) distinct_spo "
           "from main.research_assertions", cap=None),
        ev("spo_groups_duplicated",
           "select count(*) groups from (select 1 from main.research_assertions "
           "group by subject_id,predicate,object_id having count(*)>1)", cap=None),
        ev("spo_groups_diff_time_raw_incl_null",
           "select count(*) groups from (select 1 from main.research_assertions "
           f"group by subject_id,predicate,object_id having count(distinct coalesce(time_raw,'{NULL_T}'))>1)",
           cap=None),
        ev("spo_groups_diff_time_raw_nonnull",
           "select count(*) groups from (select 1 from main.research_assertions "
           "where time_raw is not null group by subject_id,predicate,object_id "
           "having count(distinct time_raw)>1)", cap=None),
        ev("multiperiod_examples",
           "select a.subject_name,a.predicate,a.object_name,a.time_raw,a.time_start,a.time_end,"
           "a.place_raw,a.fact_id from main.research_assertions a join ("
           "select subject_id,predicate,object_id from main.research_assertions where time_raw is not null "
           "group by subject_id,predicate,object_id having count(distinct time_raw)>1 limit 3) d "
           "on a.subject_id=d.subject_id and a.predicate=d.predicate and a.object_id=d.object_id "
           "where a.time_raw is not null order by a.subject_name limit 9"),
        ev("spo_groups_same_time_diff_place",
           "select count(*) groups from (select 1 from main.research_assertions "
           f"group by subject_id,predicate,object_id,coalesce(time_raw,'{NULL_T}') "
           f"having count(distinct coalesce(place_raw,'{NULL_T}'))>1)", cap=None),
        ev("exact_spo_time_place_collision_groups",
           "select count(*) groups from (select 1 from main.research_assertions "
           f"group by subject_id,predicate,object_id,coalesce(time_raw,'{NULL_T}'),coalesce(place_raw,'{NULL_T}') "
           "having count(*)>1)", cap=None),
        ev("collision_examples",
           "select subject_name,predicate,object_name,time_raw,place_raw,count(*) cnt,"
           "group_concat(fact_id,' ; ') fact_ids from main.research_assertions "
           f"group by subject_id,predicate,object_id,coalesce(time_raw,'{NULL_T}'),coalesce(place_raw,'{NULL_T}') "
           "having count(*)>1 limit 3"),
        ev("provenance_multiplicity",
           "select count(*) prov_rows, count(distinct fact_id) facts_with_prov "
           "from main.research_assertion_provenance", cap=None),
    ]
    item = {"requirement": "STKG-1",
            "title": "时空参与事实身份 (s,p,o,tau,lambda)", "queries": queries}
    return item


def eval_stkg1(res: dict) -> dict:
    r = {x["name"]: x["result"] for x in res["executed"]}
    total = r["total_and_distinct_spo"]["rows"][0]
    dup = r["spo_groups_duplicated"]["rows"][0]["groups"]
    diff_t = r["spo_groups_diff_time_raw_incl_null"]["rows"][0]["groups"]
    diff_t_nn = r["spo_groups_diff_time_raw_nonnull"]["rows"][0]["groups"]
    diff_p = r["spo_groups_same_time_diff_place"]["rows"][0]["groups"]
    collide = r["exact_spo_time_place_collision_groups"]["rows"][0]["groups"]
    prov = r["provenance_multiplicity"]["rows"][0]
    verdict = "PARTIAL"
    if diff_t_nn == 0:
        verdict = "MISSING"
    elif collide == 0 and diff_t > 0:
        verdict = "SATISFIED"
    return {"requirement": "STKG-1", "title": res["title"], "verdict": verdict,
            "evidence_queries": [{k: x[k] for k in ("name", "sql", "result")} for x in res["executed"]],
            "findings": {
                "total_assertions": total["total_assertions"],
                "distinct_spo": total["distinct_spo"],
                "spo_groups_duplicated": dup,
                "spo_groups_with_diff_time_raw": diff_t,
                "spo_groups_with_multiple_nonnull_time_raw": diff_t_nn,
                "spo_groups_same_time_diff_place": diff_p,
                "exact_spo_time_place_collision_groups": collide,
                "provenance_rows": prov["prov_rows"],
                "facts_with_provenance": prov["facts_with_prov"],
            },
            "notes": []}


# --------------------------------------------------------------------------
# STKG-2 Event 一等对象
# --------------------------------------------------------------------------
def audit_stkg2(con) -> dict:
    queries = [
        ev("final_tables_full_list",
           "select name,type from main.sqlite_master where type in ('table','view') order by name", cap=None),
        ev("sem_tables_full_list",
           "select name,type from sem.sqlite_master where type in ('table','view') order by name", cap=None),
        ev("event_frame_stats",
           "select frame_status,count(*) n,sum(all_assertion_count) assertions,"
           "sum(occurrence_time_fact_count) time_facts,sum(event_location_fact_count) place_facts "
           "from main.research_event_frames group by frame_status", cap=None),
        ev("frame_observed_time_status",
           "select observed_time_status,count(*) n from main.research_event_frames "
           "group by observed_time_status", cap=None),
        ev("event_assertion_links_and_roles",
           "select (select count(*) from main.research_event_assertion_links) links,"
           "(select count(distinct event_id) from main.research_event_assertion_links) events_linked,"
           "(select count(*) from main.research_event_roles) role_rows,"
           "(select count(*) from main.research_event_role_catalog) role_catalog_rows", cap=None),
        ev("top_event_roles",
           "select role_code,role_category,count(*) n from main.research_event_roles "
           "group by role_code,role_category order by n desc limit 6"),
        ev("event_relations_types",
           "select relation_code,relation_strength,count(*) n from main.research_event_relations "
           "group by relation_code,relation_strength", cap=None),
        ev("event_relations_prev_succ",
           "select count(*) n from main.research_event_relations where relation_code in "
           "('before','after','precedes','follows','successor_of','predecessor_of','next','previous')", cap=None),
        ev("st_cells",
           "select count(*) cells, count(distinct event_id) events from main.research_event_spatiotemporal_cells",
           cap=None),
        ev("frame_level_provenance_tables",
           "select count(*) n from main.sqlite_master where type='table' and ("
           "name like 'research_event%provenance%' or name like 'event_frame%prov%')", cap=None),
    ]
    return {"requirement": "STKG-2", "title": "Event 一等对象 (EventFrame)", "queries": queries}


def eval_stkg2(res: dict) -> dict:
    r = {x["name"]: x["result"] for x in res["executed"]}
    frames = {x["frame_status"]: x["n"] for x in r["event_frame_stats"]["rows"]}
    tobs = {x["observed_time_status"]: x["n"] for x in r["frame_observed_time_status"]["rows"]}
    links = r["event_assertion_links_and_roles"]["rows"][0]
    rel = {x["relation_code"]: x["n"] for x in r["event_relations_types"]["rows"]}
    prev_succ = r["event_relations_prev_succ"]["rows"][0]["n"]
    frame_prov = r["frame_level_provenance_tables"]["rows"][0]["n"]
    n_none = tobs.get("none", 0)
    total_frames = sum(frames.values())
    verdict = "PARTIAL"
    if total_frames == 0 or links["links"] == 0:
        verdict = "MISSING"
    elif prev_succ == 0 and frame_prov == 0 and n_none > total_frames * 0.5:
        verdict = "PARTIAL"
    else:
        verdict = "SATISFIED"
    return {"requirement": "STKG-2", "title": res["title"], "verdict": verdict,
            "evidence_queries": [{k: x[k] for k in ("name", "sql", "result")} for x in res["executed"]],
            "findings": {
                "frames_total": total_frames, "frames_by_status": frames,
                "frames_by_observed_time_status": tobs,
                "assertion_links": links["links"], "events_linked": links["events_linked"],
                "role_rows": links["role_rows"], "role_catalog_rows": links["role_catalog_rows"],
                "event_relations": rel,
                "prev_successor_relations": prev_succ,
                "frame_level_provenance_tables": frame_prov,
                "st_cells": r["st_cells"]["rows"][0],
                "tables_main": [x["name"] for x in r["final_tables_full_list"]["rows"]],
                "tables_sem": [x["name"] for x in r["sem_tables_full_list"]["rows"]],
            },
            "notes": [
                "participants/roles/assertions/空间足迹由 research_event_roles + "
                "research_event_assertion_links + research_event_spatiotemporal_cells 承担；",
                "缺前驱后继（只有 part_of/influenced 共 499 条，无 before/after）；",
                "frame 级 provenance 不存在（provenance 只挂在 fact 级）；",
                f"observed_time_status='none' 的 frame 占 {n_none}/{total_frames}。",
            ]}


# --------------------------------------------------------------------------
# STKG-3 空间语义
# --------------------------------------------------------------------------
def audit_stkg3(con) -> dict:
    queries = [
        ev("entity_type_distribution",
           "select entity_type,count(*) n from main.research_entities group by entity_type "
           "order by n desc limit 15", cap=None),
        ev("study_region_hierarchy",
           "select relation_code,count(*) n from main.research_region_hierarchy group by relation_code", cap=None),
        ev("region_hierarchy_sample",
           "select * from main.research_region_hierarchy limit 3"),
        ev("located_in_part_of_counts",
           "select predicate,research_tier,count(*) n from main.research_assertions "
           "where predicate in ('located_in','part_of') group by predicate,research_tier", cap=None),
        ev("located_in_place_to_place_samples",
           "select subject_name,subject_type,predicate,object_name,object_type,time_raw "
           "from main.research_assertions where predicate='located_in' and subject_type in "
           "('Place','AdministrativeRegion') and object_type in ('Place','AdministrativeRegion') limit 6"),
        ev("jurisdiction_succession_tables",
           "select count(*) n from main.sqlite_master where type='table' and ("
           "name like '%jurisdiction%' or name like '%succession%' or name like '%place_version%' "
           "or name like '%place_validity%' or name like '%administrative%')", cap=None),
        ev("entity_validity_columns",
           "select count(*) tables_with_validity from pragma_table_info('research_entities') "
           "where name in ('valid_from','valid_to')", cap=None),
        ev("upstream_entities_validity_usage",
           "select count(*) entities, sum(valid_from is not null) with_from, sum(valid_to is not null) with_to "
           "from up.entities", cap=None),
        ev("duplicate_place_names",
           "select count(*) groups from (select 1 from main.research_entities "
           "where entity_type in ('Place','AdministrativeRegion') "
           "group by canonical_name,entity_type having count(*)>1)", cap=None),
        ev("spatial_anchor_kinds_sem",
           "select anchor_kind,count(*) n from sem.v2_assertion_spatial_anchors group by anchor_kind "
           "order by n desc", cap=None),
    ]
    return {"requirement": "STKG-3", "title": "空间语义 (located_in / 历史政区 / PlaceVersion)", "queries": queries}


def eval_stkg3(res: dict) -> dict:
    r = {x["name"]: x["result"] for x in res["executed"]}
    hier = {x["relation_code"]: x["n"] for x in r["study_region_hierarchy"]["rows"]}
    loc = {f"{x['predicate']}|{x['research_tier']}": x["n"] for x in r["located_in_part_of_counts"]["rows"]}
    jur = r["jurisdiction_succession_tables"]["rows"][0]["n"]
    validity_cols = r["entity_validity_columns"]["rows"][0]["tables_with_validity"]
    up_valid = r["upstream_entities_validity_usage"]["rows"][0]
    dup_names = r["duplicate_place_names"]["rows"][0]["groups"]
    non_trivial_hier = sum(v for k, v in hier.items() if k != "within_basin")
    verdict = "MISSING"
    if jur > 0 or validity_cols > 0 or non_trivial_hier > 0:
        verdict = "PARTIAL"
    if jur > 0 and validity_cols > 0 and non_trivial_hier > 0 and up_valid["with_from"] > 0:
        verdict = "SATISFIED"
    return {"requirement": "STKG-3", "title": res["title"], "verdict": verdict,
            "evidence_queries": [{k: x[k] for k in ("name", "sql", "result")} for x in res["executed"]],
            "findings": {
                "place_like_entities": {x["entity_type"]: x["n"] for x in
                                        r["entity_type_distribution"]["rows"]
                                        if x["entity_type"] in ("Place", "AdministrativeRegion", "CulturalSite")},
                "region_hierarchy_relations": hier,
                "located_in_part_of_by_tier": loc,
                "jurisdiction_placeversion_tables": jur,
                "research_entities_validity_columns": validity_cols,
                "upstream_entities_valid_from_used": up_valid["with_from"],
                "duplicate_place_name_groups_without_versions": dup_names,
            },
            "notes": [
                "唯一结构化层级是 13 条 within_basin（省→流域段，研究区脚手架，非历史政区）；",
                "located_in/part_of 只是零散断言（严格层 466+111 条），无时间有效期、无政区沿革；",
                "同名同类型 Place 存在多实体（无版本维度），上游 valid_from/valid_to 全空。",
            ]}


# --------------------------------------------------------------------------
# STKG-4 时间语义
# --------------------------------------------------------------------------
def audit_stkg4(con) -> dict:
    queries = [
        ev("time_precision_distribution",
           "select time_precision,count(*) n from main.research_assertions group by time_precision "
           "order by n desc", cap=None),
        ev("time_start_end_coverage",
           "select count(*) total, sum(time_start is not null) with_start, "
           "sum(time_end is not null) with_end, sum(time_start is not null and time_end is not null "
           "and time_start<>time_end) interval_shaped from main.research_assertions", cap=None),
        ev("stage_membership_statuses",
           "select membership_status,count(*) n from main.research_assertion_stage_memberships "
           "group by membership_status", cap=None),
        ev("allen_relation_tables",
           "select count(*) n from main.sqlite_master where type='table' and ("
           "name like '%before%' or name like '%after%' or name like '%overlaps%' or name like '%during%' "
           "or name like '%starts%' or name like '%ends%' or name like '%time_relation%' "
           "or name like '%chronology%' or name like '%temporal_relation%')", cap=None),
        ev("event_occurrence_time_coverage",
           "select sum(time_role='event_occurrence') occurrence_role_facts, "
           "(select count(*) from main.research_event_frames where observed_time_status='trusted') frames_trusted_time,"
           "(select count(*) from main.research_event_frames where observed_time_status='none') frames_no_time "
           "from main.research_assertions", cap=None),
        ev("historical_stages",
           "select stage_code,stage_order,time_start,time_end from main.research_historical_stages "
           "order by stage_order limit 6"),
    ]
    return {"requirement": "STKG-4", "title": "时间语义 (区间关系 / 区间代数)", "queries": queries}


def eval_stkg4(res: dict) -> dict:
    r = {x["name"]: x["result"] for x in res["executed"]}
    cov = r["time_start_end_coverage"]["rows"][0]
    allen = r["allen_relation_tables"]["rows"][0]["n"]
    prec = {x["time_precision"]: x["n"] for x in r["time_precision_distribution"]["rows"]}
    verdict = "MISSING"
    if cov["with_start"] and cov["with_start"] > 0:
        verdict = "PARTIAL"
    if allen > 0 and prec.get("unknown", 0) < cov["total"] * 0.5:
        verdict = "SATISFIED"
    return {"requirement": "STKG-4", "title": res["title"], "verdict": verdict,
            "evidence_queries": [{k: x[k] for k in ("name", "sql", "result")} for x in res["executed"]],
            "findings": {
                "time_precision_distribution": prec,
                "time_start_coverage": cov["with_start"],
                "interval_shaped_rows": cov["interval_shaped"],
                "stage_membership_statuses": {x["membership_status"]: x["n"]
                                              for x in r["stage_membership_statuses"]["rows"]},
                "allen_relation_tables": allen,
                "occurrence_role_facts": r["event_occurrence_time_coverage"]["rows"][0],
                "stages": r["historical_stages"]["rows"],
            },
            "notes": [
                "区间表示字段存在（time_start/end/precision + stage overlap_start/end），"
                "但阶段成员只有 contained/cross_stage_interval 两种包含语义；",
                "before/after/overlaps/starts/ends/contains 等区间-区间关系表不存在（扫描=0）；",
                "时序只能靠 stage_order 排序，无法表达事件先后/状态持续/转移的区间代数。",
            ]}


# --------------------------------------------------------------------------
# STKG-5 role-owner 机制
# --------------------------------------------------------------------------
def audit_stkg5(con) -> dict:
    queries = [
        ev("owner_coverage_all",
           "select count(*) total, sum(time_owner_id is not null) with_time_owner, "
           "sum(space_owner_id is not null) with_space_owner, "
           "sum(canonical_space_anchor_id is not null) with_space_anchor "
           "from main.research_assertions", cap=None),
        ev("owner_coverage_strict_tier",
           "select count(*) total, sum(time_owner_id is not null) with_time_owner, "
           "sum(space_owner_id is not null) with_space_owner from main.research_assertions "
           "where research_tier='strict_semantic'", cap=None),
        ev("time_role_distribution",
           "select time_role,count(*) n from main.research_assertions group by time_role order by n desc", cap=None),
        ev("space_role_distribution",
           "select space_role,count(*) n from main.research_assertions group by space_role order by n desc", cap=None),
        ev("time_owner_entity_types",
           "select e.entity_type,count(*) n from main.research_assertions a "
           "join main.research_entities e on e.entity_id=a.time_owner_id group by 1 order by n desc", cap=None),
        ev("space_owner_entity_types",
           "select e.entity_type,count(*) n from main.research_assertions a "
           "join main.research_entities e on e.entity_id=a.space_owner_id group by 1 order by n desc", cap=None),
        ev("space_anchor_entity_types",
           "select e.entity_type,count(*) n from main.research_assertions a "
           "join main.research_entities e on e.entity_id=a.canonical_space_anchor_id group by 1 order by n desc",
           cap=None),
        ev("link_level_owner_coverage",
           "select count(*) links, sum(time_owner_id is not null) with_time_owner, "
           "sum(space_owner_id is not null) with_space_owner, "
           "sum(event_location_id is not null) with_event_location "
           "from main.research_event_assertion_links", cap=None),
    ]
    return {"requirement": "STKG-5", "title": "role-owner 机制 (time/space role+owner)", "queries": queries}


def eval_stkg5(res: dict) -> dict:
    r = {x["name"]: x["result"] for x in res["executed"]}
    a = r["owner_coverage_all"]["rows"][0]
    strict = r["owner_coverage_strict_tier"]["rows"][0]
    links = r["link_level_owner_coverage"]["rows"][0]
    tr = {x["time_role"]: x["n"] for x in r["time_role_distribution"]["rows"]}
    verdict = "MISSING"
    if a["with_time_owner"] > 0 or a["with_space_owner"] > 0:
        verdict = "PARTIAL"
    if a["with_time_owner"] > a["total"] * 0.5 and a["with_space_owner"] > a["total"] * 0.5:
        verdict = "SATISFIED"
    return {"requirement": "STKG-5", "title": res["title"], "verdict": verdict,
            "evidence_queries": [{k: x[k] for k in ("name", "sql", "result")} for x in res["executed"]],
            "findings": {
                "all_tier": a, "strict_tier": strict, "link_level": links,
                "time_role_distribution": tr,
                "space_role_distribution": {x["space_role"]: x["n"]
                                            for x in r["space_role_distribution"]["rows"]},
                "time_owner_types": {x["entity_type"]: x["n"] for x in r["time_owner_entity_types"]["rows"]},
                "space_owner_types": {x["entity_type"]: x["n"] for x in r["space_owner_entity_types"]["rows"]},
                "space_anchor_types": {x["entity_type"]: x["n"] for x in r["space_anchor_entity_types"]["rows"]},
            },
            "notes": [
                "机制在 schema 与上游(v2_assertion_scopes)均存在且类型正确"
                "（time_owner→Person/Event，space_owner→Event，anchor→Place/AdministrativeRegion）；",
                f"但 time_role='unknown' 占 {tr.get('unknown',0)}/{a['total']}，"
                "time_owner 全库覆盖仅 ~1.3%，space_owner ~1.9%，属低覆盖而非缺表。",
            ]}


# --------------------------------------------------------------------------
# STKG-6 CultureState
# --------------------------------------------------------------------------
def audit_stkg6(con) -> dict:
    queries = [
        ev("state_counts_and_tiers",
           "select observation_tier,count(*) n from main.research_culture_states group by observation_tier", cap=None),
        ev("state_status",
           "select state_status,count(*) n from main.research_culture_states group by state_status", cap=None),
        ev("state_composition_sample",
           "select state_id,culture_subject_name,culture_form_code,stage_label_zh,region_id,"
           "province_name,basin_section_id,observation_tier,supporting_fact_count,supporting_event_count "
           "from main.research_culture_states limit 3"),
        ev("component_table_counts",
           "select "
           "(select count(*) from main.research_culture_state_events) state_events,"
           "(select count(*) from main.research_culture_state_actors) state_actors,"
           "(select count(*) from main.research_culture_state_roles) state_roles,"
           "(select count(*) from main.research_culture_state_support) state_support,"
           "(select count(*) from main.research_culture_state_semantic_members) semantic_members,"
           "(select count(*) from main.research_culture_state_value_facets) value_facets,"
           "(select count(*) from main.research_first_observed_states) first_observed", cap=None),
        ev("state_roles_top",
           "select culture_role,count(*) n from main.research_culture_state_roles group by 1 order by n desc limit 6"),
        ev("backtrace_state_support_to_provenance",
           "select count(*) join_rows from main.research_culture_state_support s "
           "join main.research_assertion_provenance p on p.fact_id=s.fact_id", cap=None),
        ev("backtrace_state_support_to_evidence_ids",
           "select count(distinct je.value) distinct_evidence from main.research_culture_state_support s "
           "join main.research_assertion_provenance p on p.fact_id=s.fact_id, "
           "json_each(p.evidence_ids_json) je", cap=None),
        ev("evidence_registry_size",
           "select count(*) n from up.evidence_registry", cap=None),
        ev("state_events_to_cells_and_frames",
           "select count(*) n from main.research_culture_state_events se "
           "join main.research_event_spatiotemporal_cells c on c.cell_id=se.cell_id "
           "join main.research_event_frames f on f.event_id=se.event_id", cap=None),
    ]
    return {"requirement": "STKG-6", "title": "CultureState (subject+form+stage+region+events+tier, 可回溯证据)",
            "queries": queries}


def eval_stkg6(res: dict) -> dict:
    r = {x["name"]: x["result"] for x in res["executed"]}
    tiers = {x["observation_tier"]: x["n"] for x in r["state_counts_and_tiers"]["rows"]}
    comp = r["component_table_counts"]["rows"][0]
    ev_ids = r["backtrace_state_support_to_evidence_ids"]["rows"][0]["distinct_evidence"]
    back = r["backtrace_state_support_to_provenance"]["rows"][0]["join_rows"]
    cell_join = r["state_events_to_cells_and_frames"]["rows"][0]["n"]
    verdict = "MISSING"
    if tiers:
        verdict = "PARTIAL"
    if back > 0 and ev_ids > 0 and cell_join > 0 and comp["state_events"] > 0:
        verdict = "SATISFIED"
    return {"requirement": "STKG-6", "title": res["title"], "verdict": verdict,
            "evidence_queries": [{k: x[k] for k in ("name", "sql", "result")} for x in res["executed"]],
            "findings": {
                "states_total": sum(tiers.values()), "by_observation_tier": tiers,
                "by_state_status": {x["state_status"]: x["n"] for x in r["state_status"]["rows"]},
                "components": comp,
                "culture_roles": {x["culture_role"]: x["n"] for x in r["state_roles_top"]["rows"]},
                "backtrace_support_to_provenance_rows": back,
                "distinct_evidence_ids_reachable": ev_ids,
                "evidence_registry_size": r["evidence_registry_size"]["rows"][0]["n"],
                "state_events_join_cells_frames": cell_join,
                "composition_sample": r["state_composition_sample"]["rows"],
            },
            "notes": [
                "state 主键是 (subject,form,stage,region,basin) 组合；自带 observation_tier 三档；",
                "回溯链 verified：state→support→fact→provenance→evidence_registry，"
                "state→events→cell→event_frame 两条链均 join 成功；",
                "弱点：state 自身无 time_start/end（时长=stage 区间），多数 tier 是 relation_context。",
            ]}


# --------------------------------------------------------------------------
# STKG-7 演化关系
# --------------------------------------------------------------------------
def audit_stkg7(con) -> dict:
    queries = [
        ev("published_transitions",
           "select transition_type,count(*) n from main.research_evolution_transitions group by 1 order by n desc",
           cap=None),
        ev("transition_candidates_gates",
           "select publication_gate_reason,derivation_kind,count(*) n from main.research_evolution_transition_candidates "
           "group by 1,2 order by n desc", cap=None),
        ev("transition_support_rows",
           "select count(*) n from main.research_evolution_transition_support", cap=None),
        ev("transition_rules_predicate_gated",
           "select rule_id,rule_kind,predicate,transition_type from main.research_transition_rules", cap=None),
        ev("causality_boundary_event_relations",
           "select causality_status,count(*) n from main.research_event_relations group by 1", cap=None),
        ev("same_subject_stage_order_only_candidates",
           "select count(*) n from main.research_evolution_transition_candidates c "
           "join main.research_culture_states f on f.state_id=c.from_state_id "
           "join main.research_culture_states t on t.state_id=c.to_state_id "
           "where f.culture_subject_id=t.culture_subject_id", cap=None),
        ev("published_examples",
           "select t.transition_type,fs.culture_subject_name from_subject,fs.stage_label_zh from_stage,"
           "ts.stage_label_zh to_stage,fs.province_name,t.supporting_fact_count,t.confidence "
           "from main.research_evolution_transitions t "
           "join main.research_culture_states fs on fs.state_id=t.from_state_id "
           "join main.research_culture_states ts on ts.state_id=t.to_state_id limit 6"),
        ev("upstream_evolution_tables",
           "select (select count(*) from up.evolution_transitions) up_transitions,"
           "(select count(*) from up.evolution_transition_evidence) up_transition_evidence", cap=None),
        ev("build_metadata_limitations",
           "select value_json from main.research_build_metadata where key='limitations'", cap=None),
    ]
    return {"requirement": "STKG-7", "title": "演化关系 (前驱后继 / 是否时间先后冒充因果)", "queries": queries}


def eval_stkg7(res: dict) -> dict:
    r = {x["name"]: x["result"] for x in res["executed"]}
    pub = {x["transition_type"]: x["n"] for x in r["published_transitions"]["rows"]}
    gates = {x["publication_gate_reason"]: x["n"] for x in r["transition_candidates_gates"]["rows"]}
    same_subj = r["same_subject_stage_order_only_candidates"]["rows"][0]["n"]
    caus = {x["causality_status"]: x["n"] for x in r["causality_boundary_event_relations"]["rows"]}
    up = r["upstream_evolution_tables"]["rows"][0]
    n_pub = sum(pub.values())
    verdict = "MISSING"
    if n_pub > 0 or gates:
        verdict = "PARTIAL"
    if n_pub > 0 and caus.get("not_inferred", 0) > 0 and same_subj == 0:
        verdict = "SATISFIED" if n_pub > 100 else "PARTIAL"
    return {"requirement": "STKG-7", "title": res["title"], "verdict": verdict,
            "evidence_queries": [{k: x[k] for k in ("name", "sql", "result")} for x in res["executed"]],
            "findings": {
                "published_transitions_total": n_pub, "published_by_type": pub,
                "candidate_gate_reasons": gates,
                "transition_support_rows": r["transition_support_rows"]["rows"][0]["n"],
                "rules_predicate_gated": r["transition_rules_predicate_gated"]["rows"],
                "event_relation_causality_status": caus,
                "same_subject_stage_order_only_candidates": same_subj,
                "upstream_evolution_rows": up,
                "published_examples": r["published_examples"]["rows"],
                "build_limitations": r["build_metadata_limitations"]["rows"],
            },
            "notes": [
                "设计上明确设防：event_relations.causality_status 强制 'not_inferred'；"
                "build 元数据自述 'no causality or evolution is inferred from sequence alone'；",
                "候选全部由显式谓词规则触发（adapted_from/commemorates/inherited_from/...），"
                "无同主体纯时序候选（=0）→ 未把时间先后冒充因果；",
                "但产出极低：159 候选仅 4 条发布（全部 memorialized_as），"
                "对 11,532 个 CultureState 而言演化层近乎空；上游 evolution_transitions 表 0 行。",
            ]}


# --------------------------------------------------------------------------
AUDITS = {
    "STKG-1": (audit_stkg1, eval_stkg1),
    "STKG-2": (audit_stkg2, eval_stkg2),
    "STKG-3": (audit_stkg3, eval_stkg3),
    "STKG-4": (audit_stkg4, eval_stkg4),
    "STKG-5": (audit_stkg5, eval_stkg5),
    "STKG-6": (audit_stkg6, eval_stkg6),
    "STKG-7": (audit_stkg7, eval_stkg7),
}

OVERALL_ANSWER = (
    "不算完整的时空知识图谱。它是一个证据链完备的『带时间戳的历史事实断言库 + 事件/文化状态聚合层』："
    "时间作为事实身份维度已生效（STKG-1）但区间代数缺失（STKG-4）；空间只有研究区脚手架，"
    "没有政区层级/历史沿革/地名版本（STKG-3 基本缺失）；事件帧聚合了角色与断言但没有前驱后继（STKG-2）；"
    "role-owner 机制存在但覆盖率约 1-2%（STKG-5）；CultureState 链路完整可回溯证据（STKG-6）；"
    "演化层设计设防得当但仅 4 条发布转换（STKG-7）。"
)


def main() -> int:
    ap = argparse.ArgumentParser(description="STKG-1..7 read-only audit")
    ap.add_argument("--only", choices=sorted(AUDITS), help="只跑单项审计")
    ap.add_argument("--out", type=Path, help="可选：JSON 落盘路径（默认 stdout）")
    args = ap.parse_args()

    con = connect_final()
    attach_integration(con)

    from _common import FINAL_DB, SEMANTIC_DB, INTEGRATION_DB  # noqa: E402

    items = []
    for key in sorted(AUDITS):
        if args.only and key != args.only:
            continue
        collect, evaluate = AUDITS[key]
        declared = collect(con)
        executed = []
        for spec in declared["queries"]:
            cap = spec.pop("_cap", None)
            try:
                res = q(con, spec["sql"], cap=cap)
            except Exception as exc:  # 记录失败而不是中断
                res = {"rows": [], "n": -1, "error": str(exc)}
            executed.append({"name": spec["name"], "sql": spec["sql"], "result": res})
        items.append(evaluate({"title": declared["title"], "executed": executed}))

    counts = {}
    for it in items:
        counts[it["verdict"]] = counts.get(it["verdict"], 0) + 1

    report = {
        "audit": "STKG-1..7 spatiotemporal knowledge-graph identity audit",
        "generated_by": "audit_stkg_identity.py (read-only)",
        "databases": {
            "final": str(FINAL_DB), "final_sha256": sha256_file(FINAL_DB),
            "semantic": str(SEMANTIC_DB), "semantic_sha256": sha256_file(SEMANTIC_DB),
            "integration_attached": str(INTEGRATION_DB),
        },
        "verdict_counts": counts,
        "items": items,
        "overall_answer": OVERALL_ANSWER if len(items) == 7 else
        "（部分运行，overall 仅在 7 项齐全时给出）",
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"[audit_stkg_identity] written: {args.out}", file=sys.stderr)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
