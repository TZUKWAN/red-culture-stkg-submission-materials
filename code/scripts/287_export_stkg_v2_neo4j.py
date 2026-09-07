"""Export the complete STKG V2 graph with Chinese research-facing captions."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "derived" / "red_culture_stkg_final_v2.sqlite"
OUTPUT_DIR = ROOT / "graph_exports" / "stkg_v2"
REPORT = ROOT / "audit_reports" / "stkg_v2_graph_export.json"
BUILD_VERSION = "red-culture-stkg-neo4j-export-v2-2"

NODE_HEADER = [
    "graph_id:ID(STKGV2)", "stable_id:string", "name:string", "caption:string", "node_kind:string",
    "entity_type:string", "semantic_family:string", "media_type:string", "media_method:string",
    "media_status:string", "media_confidence:double", "predicate:string", "relation_label_zh:string",
    "time_label:string", "time_status:string", "stage_code:string", "stage_label_zh:string",
    "region_id:string", "province_name:string", "basin_section_id:string", "basin_section_name:string",
    "culture_form_code:string", "culture_form_label_zh:string", "observation_tier:string",
    "research_tier:string", "status:string", "confidence:double", "member_count:int", "fact_count:int",
    "supporting_fact_count:int", "properties_json:string", ":LABEL",
]

REL_HEADER = [
    ":START_ID(STKGV2)", ":END_ID(STKGV2)", "relationship_id:string", "fact_id:string",
    "predicate:string", "relation_label_zh:string", "role_code:string", "stage_code:string",
    "region_id:string", "culture_form_code:string", "observation_tier:string", "status:string",
    "confidence:double", "properties_json:string", ":TYPE",
]

KIND_PREFIX = {
    "Entity": "entity", "Assertion": "assertion", "SourceRecord": "source",
    "HistoricalStage": "stage", "StudyRegion": "region", "BasinSection": "basin",
    "CultureForm": "form", "EventCell": "cell", "CultureState": "state",
    "TransitionCandidate": "candidate", "EvolutionTransition": "transition",
    "TransitionType": "transition-type",
}

TRANSITION_LABELS = {
    "emerged": "产生", "developed_into": "发展为", "spread_to": "传播至", "shifted_to": "转向",
    "diverged_into": "分化为", "merged_into": "融合为", "inherited_from": "继承自",
    "transformed_into": "转化为", "institutionalized_as": "制度化为", "memorialized_as": "纪念化为",
    "adapted_as": "改编为", "digitized_as": "数字化为", "reactivated_in": "再激活于",
}

ROLE_LABELS = {
    "participant": "参与者", "leader": "领导者", "organizer": "组织者", "commander": "指挥者",
    "executor": "执行者", "supporter": "支持者", "guide": "指导者", "opponent": "反对者",
    "responsible_actor": "责任主体", "dispatcher": "派遣者", "protector": "保护者",
    "occurrence_place": "发生地点", "occurrence_period": "发生时期", "liberated_place": "解放地点",
    "manifested_spirit": "体现精神", "originated_spirit": "产生精神", "depicting_work": "描绘作品",
    "used_artifact": "使用物品", "memorial_carrier": "纪念载体", "documenting_source": "记录文献",
    "source_document": "来源文献", "parent_event": "上位事件", "component_event": "组成事件",
    "influenced_target": "影响对象", "influencing_entity": "影响来源",
}

LABEL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())


def canonical_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def graph_id(kind: str, stable_id: object) -> str:
    key = clean_text(stable_id)
    if kind not in KIND_PREFIX or not key:
        raise ValueError(f"invalid graph identity: {kind!r}, {stable_id!r}")
    return f"{KIND_PREFIX[kind]}:{key}"


def relationship_id(relationship_type: str, *parts: object) -> str:
    payload = "\x1f".join([relationship_type, *(str(part) for part in parts)])
    return f"REL-{relationship_type}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def readable_assertion_name(subject: object, label: object, predicate: object, target: object) -> str:
    relation = clean_text(label) or clean_text(predicate).removeprefix("raw:") or "关联"
    return clean_text(f"{subject}｜{relation}｜{target}")


def make_node_row(kind: str, stable_id: object, name: object, labels: list[str], **values) -> list:
    caption = clean_text(name) or f"{kind}：{clean_text(stable_id)}"
    if any(not LABEL_PATTERN.fullmatch(label) for label in labels):
        raise ValueError(f"invalid Neo4j labels: {labels}")
    return [
        graph_id(kind, stable_id), clean_text(stable_id), caption, caption, kind,
        values.get("entity_type", ""), values.get("semantic_family", ""), values.get("media_type", ""),
        values.get("media_method", ""), values.get("media_status", ""), values.get("media_confidence", ""),
        values.get("predicate", ""),
        values.get("relation_label_zh", ""), values.get("time_label", ""), values.get("time_status", ""),
        values.get("stage_code", ""), values.get("stage_label_zh", ""), values.get("region_id", ""),
        values.get("province_name", ""), values.get("basin_section_id", ""),
        values.get("basin_section_name", ""), values.get("culture_form_code", ""),
        values.get("culture_form_label_zh", ""), values.get("observation_tier", ""),
        values.get("research_tier", ""), values.get("status", ""), values.get("confidence", ""),
        values.get("member_count", ""), values.get("fact_count", ""),
        values.get("supporting_fact_count", ""), canonical_json(values.get("properties") or {}),
        ";".join(labels),
    ]


def make_rel_row(rel_type: str, start: str, end: str, identity: tuple, **values) -> list:
    if not LABEL_PATTERN.fullmatch(rel_type):
        raise ValueError(f"invalid Neo4j relationship type: {rel_type}")
    return [
        start, end, relationship_id(rel_type, *identity), values.get("fact_id", ""),
        values.get("predicate", ""), values.get("relation_label_zh", ""), values.get("role_code", ""),
        values.get("stage_code", ""), values.get("region_id", ""), values.get("culture_form_code", ""),
        values.get("observation_tier", ""), values.get("status", ""), values.get("confidence", ""),
        canonical_json(values.get("properties") or {}), rel_type,
    ]


def write_nodes(con: sqlite3.Connection, path: Path) -> tuple[Counter, int]:
    counts = Counter()
    seen = set()
    blank_captions = 0
    relation_labels = {str(row[0]): str(row[1]) for row in con.execute(
        "select predicate,label_zh from research_relation_contract"
    )}
    form_labels = {str(row[0]): str(row[1]) for row in con.execute(
        "select culture_form_code,label_zh from research_culture_forms"
    )}
    basin_labels = {str(row[0]): str(row[1]) for row in con.execute(
        "select basin_section_id,basin_section_name from research_basin_sections"
    )}

    def emit(writer, kind, stable_id, name, labels, **values):
        nonlocal blank_captions
        row = make_node_row(kind, stable_id, name, labels, **values)
        if row[0] in seen:
            raise RuntimeError(f"duplicate graph node ID: {row[0]}")
        seen.add(row[0])
        if not row[2]:
            blank_captions += 1
        writer.writerow(row)
        counts[kind] += 1

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(NODE_HEADER)
        for row in con.execute(
            "select e.*,f.all_assertion_count,f.strict_assertion_count,f.controlled_role_count,"
            "f.occurrence_time_fact_count,f.trusted_time_fact_count,f.event_location_fact_count,"
            "f.observed_time_start,f.observed_time_end,f.observed_time_status,f.frame_status,"
            "m.media_type,m.classification_method media_method,m.task_status media_status,"
            "m.confidence media_confidence,m.model media_model,m.prompt_version media_prompt_version,"
            "m.reason_code media_reason_code,m.explanation media_explanation "
            "from research_entities e left join research_event_frames f on f.event_id=e.entity_id "
            "left join research_creative_work_media m on m.entity_id=e.entity_id order by e.entity_id"
        ):
            labels = ["Entity", "ResearchFacing", str(row["entity_type"])]
            if row["entity_type"] == "Event":
                labels.append("EventFrame")
            emit(writer, "Entity", row["entity_id"], row["canonical_name"], labels,
                 entity_type=row["entity_type"], semantic_family=row["semantic_family"],
                 media_type=row["media_type"] or "", media_method=row["media_method"] or "",
                 media_status=row["media_status"] or "", media_confidence=row["media_confidence"] or "",
                 member_count=row["integrated_member_count"], confidence=row["confidence"] or "",
                 time_status=row["observed_time_status"] or "", status=row["type_validation_status"],
                 properties={"aliases": json.loads(row["aliases_json"]), "source_entity_count": row["source_entity_count"],
                             "all_assertion_count": row["all_assertion_count"], "strict_assertion_count": row["strict_assertion_count"],
                             "controlled_role_count": row["controlled_role_count"],
                             "occurrence_time_fact_count": row["occurrence_time_fact_count"],
                             "trusted_time_fact_count": row["trusted_time_fact_count"],
                             "event_location_fact_count": row["event_location_fact_count"],
                             "observed_time_start": row["observed_time_start"], "observed_time_end": row["observed_time_end"],
                             "frame_status": row["frame_status"], "media_model": row["media_model"],
                             "media_prompt_version": row["media_prompt_version"],
                             "media_reason_code": row["media_reason_code"],
                             "media_explanation": row["media_explanation"]})
        for row in con.execute("select * from research_assertions order by fact_id"):
            label = relation_labels.get(str(row["predicate"]), str(row["predicate"]).removeprefix("raw:"))
            name = readable_assertion_name(row["subject_name"], label, row["predicate"], row["object_name"])
            emit(writer, "Assertion", row["fact_id"], name, ["Assertion", "TechnicalNode"],
                 predicate=row["predicate"], relation_label_zh=label, time_label=row["normalized_time_label"] or "",
                 time_status=row["time_role"], research_tier=row["research_tier"], status=row["semantic_status"],
                 confidence=row["confidence"] or "", member_count=row["source_member_count"],
                 properties={"subject_id": row["subject_id"], "object_id": row["object_id"],
                             "subject_name": row["subject_name"], "object_name": row["object_name"],
                             "time_raw": row["time_raw"], "time_start": row["time_start"], "time_end": row["time_end"],
                             "time_precision": row["time_precision"], "time_owner_id": row["time_owner_id"],
                             "place_raw": row["place_raw"], "space_role": row["space_role"],
                             "space_owner_id": row["space_owner_id"], "canonical_space_anchor_id": row["canonical_space_anchor_id"],
                             "province": row["province"], "city": row["city"], "county": row["county"]})
        for row in con.execute("select * from research_assertion_provenance order by provenance_id"):
            emit(writer, "SourceRecord", row["provenance_id"],
                 f"{row['source_table']}：{row['source_record_id']}", ["SourceRecord", "TechnicalNode"],
                 status=row["member_status"], properties={"fact_id": row["fact_id"],
                     "provenance_kind": row["provenance_kind"], "source_member_id": row["source_member_id"],
                     "topic_kind": row["topic_kind"], "source_subject_id": row["source_subject_id"],
                     "source_predicate": row["source_predicate"], "source_object_id": row["source_object_id"],
                     "legacy_candidate_ids": json.loads(row["legacy_candidate_ids_json"]),
                     "native_record_ids": json.loads(row["native_record_ids_json"]),
                     "evidence_ids": json.loads(row["evidence_ids_json"]),
                     "source_record_ids": json.loads(row["source_record_ids_json"]),
                     "metadata": json.loads(row["metadata_json"])})
        for row in con.execute("select * from research_historical_stages order by stage_order"):
            emit(writer, "HistoricalStage", row["stage_code"], row["stage_label_zh"],
                 ["HistoricalStage", "ResearchFacing"], stage_code=row["stage_code"], stage_label_zh=row["stage_label_zh"],
                 properties={"stage_order": row["stage_order"], "time_start": row["time_start"], "time_end": row["time_end"]})
        for row in con.execute("select * from research_study_regions order by province_order"):
            emit(writer, "StudyRegion", row["region_id"], row["province_name"], ["StudyRegion", "ResearchFacing"],
                 region_id=row["region_id"], province_name=row["province_name"],
                 properties={"basin_segment": row["basin_segment"], "province_order": row["province_order"]})
        for row in con.execute("select * from research_basin_sections order by section_order"):
            emit(writer, "BasinSection", row["basin_section_id"], row["basin_section_name"],
                 ["BasinSection", "ResearchFacing"], basin_section_id=row["basin_section_id"],
                 basin_section_name=row["basin_section_name"], properties={"section_order": row["section_order"]})
        for row in con.execute("select * from research_culture_forms order by culture_form_code"):
            emit(writer, "CultureForm", row["culture_form_code"], row["label_zh"], ["CultureForm", "ResearchFacing"],
                 culture_form_code=row["culture_form_code"], culture_form_label_zh=row["label_zh"])
        for row in con.execute("select * from research_event_spatiotemporal_cells order by cell_id"):
            name = f"{row['event_name']}｜{row['stage_label_zh']}｜{row['province_name']}"
            emit(writer, "EventCell", row["cell_id"], name, ["EventCell", "TechnicalNode"],
                 stage_code=row["stage_code"], stage_label_zh=row["stage_label_zh"], region_id=row["region_id"],
                 province_name=row["province_name"], basin_section_id=row["basin_section_id"],
                 basin_section_name=basin_labels[row["basin_section_id"]], observation_tier=row["observation_tier"],
                 status=row["observation_tier"], properties={"event_id": row["event_id"],
                     "time_evidence_count": row["time_evidence_count"], "place_evidence_count": row["place_evidence_count"],
                     "context_evidence_count": row["context_evidence_count"]})
        for row in con.execute("select * from research_culture_states order by state_id"):
            form_label = form_labels[row["culture_form_code"]]
            name = f"{row['culture_subject_name']}｜{form_label}｜{row['stage_label_zh']}｜{row['province_name']}"
            emit(writer, "CultureState", row["state_id"], name, ["CultureState", "TechnicalNode"],
                 entity_type=row["culture_subject_type"], stage_code=row["stage_code"], stage_label_zh=row["stage_label_zh"],
                 region_id=row["region_id"], province_name=row["province_name"], basin_section_id=row["basin_section_id"],
                 basin_section_name=basin_labels[row["basin_section_id"]], culture_form_code=row["culture_form_code"],
                 culture_form_label_zh=form_label, observation_tier=row["observation_tier"], status=row["state_status"],
                 fact_count=row["supporting_fact_count"], member_count=row["source_member_count"],
                 properties={"culture_subject_id": row["culture_subject_id"],
                             "supporting_event_count": row["supporting_event_count"],
                             "has_controlled_explicit_support": row["has_controlled_explicit_support"]})
        for row in con.execute(
            "select c.*,f.culture_subject_name from_name,t.culture_subject_name to_name "
            "from research_evolution_transition_candidates c join research_culture_states f on f.state_id=c.from_state_id "
            "join research_culture_states t on t.state_id=c.to_state_id order by c.candidate_id"
        ):
            transition_label = TRANSITION_LABELS.get(row["transition_type"], row["transition_type"])
            emit(writer, "TransitionCandidate", row["candidate_id"],
                 f"{row['from_name']}｜{transition_label}｜{row['to_name']}", ["TransitionCandidate", "TechnicalNode"],
                 status=row["publication_gate_reason"], confidence=row["confidence"],
                 properties={"rule_id": row["rule_id"], "transition_type": row["transition_type"],
                             "review_status": row["review_status"], "publication_eligible": row["publication_eligible"],
                             "supporting_fact_id": row["supporting_fact_id"]})
        for row in con.execute(
            "select t.*,f.culture_subject_name from_name,x.culture_subject_name to_name "
            "from research_evolution_transitions t join research_culture_states f on f.state_id=t.from_state_id "
            "join research_culture_states x on x.state_id=t.to_state_id order by t.transition_id"
        ):
            transition_label = TRANSITION_LABELS.get(row["transition_type"], row["transition_type"])
            emit(writer, "EvolutionTransition", row["transition_id"],
                 f"{row['from_name']}｜{transition_label}｜{row['to_name']}",
                 ["EvolutionTransition", "ResearchFacing"], status=row["review_status"], confidence=row["confidence"],
                 supporting_fact_count=row["supporting_fact_count"],
                 properties={"transition_type": row["transition_type"], "derivation_rule": row["derivation_rule"]})
        for row in con.execute("select transition_type from research_transition_types order by transition_type"):
            code = str(row["transition_type"])
            emit(writer, "TransitionType", code, TRANSITION_LABELS.get(code, code),
                 ["TransitionType", "ResearchFacing"], status=code)
    return counts, blank_captions


def write_relationships(con: sqlite3.Connection, path: Path) -> Counter:
    counts = Counter()
    relation_labels = {str(row[0]): str(row[1]) for row in con.execute(
        "select predicate,label_zh from research_relation_contract"
    )}
    form_labels = {str(row[0]): str(row[1]) for row in con.execute(
        "select culture_form_code,label_zh from research_culture_forms"
    )}
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(REL_HEADER)

        def emit(rel_type, start, end, identity, **values):
            writer.writerow(make_rel_row(rel_type, start, end, identity, **values))
            counts[rel_type] += 1

        for row in con.execute("select fact_id,subject_id,object_id,predicate,research_tier,confidence from research_assertions order by fact_id"):
            assertion = graph_id("Assertion", row["fact_id"])
            label = relation_labels.get(str(row["predicate"]), str(row["predicate"]).removeprefix("raw:"))
            emit("SUBJECT_OF", graph_id("Entity", row["subject_id"]), assertion, (row["fact_id"], "subject"), fact_id=row["fact_id"])
            emit("OBJECT", assertion, graph_id("Entity", row["object_id"]), (row["fact_id"], "object"), fact_id=row["fact_id"])
            if row["research_tier"] != "unresolved":
                emit("SEMANTIC_RELATION", graph_id("Entity", row["subject_id"]), graph_id("Entity", row["object_id"]),
                     (row["fact_id"],), fact_id=row["fact_id"], predicate=row["predicate"], relation_label_zh=label,
                     status=row["research_tier"], confidence=row["confidence"] or "")
        for row in con.execute("select provenance_id,fact_id from research_assertion_provenance order by provenance_id"):
            emit("SUPPORTED_BY", graph_id("Assertion", row["fact_id"]), graph_id("SourceRecord", row["provenance_id"]),
                 (row["provenance_id"],), fact_id=row["fact_id"])
        for row in con.execute("select fact_id,stage_code,membership_status from research_assertion_stage_memberships order by fact_id,stage_code"):
            emit("DURING_STAGE", graph_id("Assertion", row["fact_id"]), graph_id("HistoricalStage", row["stage_code"]),
                 (row["fact_id"], row["stage_code"]), fact_id=row["fact_id"], stage_code=row["stage_code"], status=row["membership_status"])
        for row in con.execute("select fact_id,region_id,study_area_status from research_assertion_regions order by fact_id,region_id"):
            emit("IN_STUDY_REGION", graph_id("Assertion", row["fact_id"]), graph_id("StudyRegion", row["region_id"]),
                 (row["fact_id"], row["region_id"]), fact_id=row["fact_id"], region_id=row["region_id"], status=row["study_area_status"])
        for row in con.execute("select fact_id,basin_section_id,study_area_status from research_assertion_basins order by fact_id,basin_section_id"):
            emit("IN_BASIN_SECTION", graph_id("Assertion", row["fact_id"]), graph_id("BasinSection", row["basin_section_id"]),
                 (row["fact_id"], row["basin_section_id"]), fact_id=row["fact_id"], status=row["study_area_status"])
        for row in con.execute("select fact_id,canonical_space_anchor_id,space_role from research_assertions where canonical_space_anchor_id is not null order by fact_id"):
            emit("AT_PLACE", graph_id("Assertion", row["fact_id"]), graph_id("Entity", row["canonical_space_anchor_id"]),
                 (row["fact_id"], row["canonical_space_anchor_id"]), fact_id=row["fact_id"], role_code=row["space_role"])
        for row in con.execute("select * from research_event_roles order by event_id,fact_id,event_endpoint"):
            emit("EVENT_ROLE", graph_id("Entity", row["event_id"]), graph_id("Entity", row["counterpart_id"]),
                 (row["event_id"], row["fact_id"], row["event_endpoint"]), fact_id=row["fact_id"],
                 predicate=row["predicate"], relation_label_zh=ROLE_LABELS.get(row["role_code"], row["role_code"]),
                 role_code=row["role_code"], status=row["analysis_strength"])
        for row in con.execute("select * from research_event_relations order by fact_id"):
            emit("EVENT_RELATION", graph_id("Entity", row["source_event_id"]), graph_id("Entity", row["target_event_id"]),
                 (row["fact_id"],), fact_id=row["fact_id"], predicate=row["relation_code"],
                 relation_label_zh=relation_labels.get(row["relation_code"], row["relation_code"]), status=row["relation_strength"])
        for row in con.execute("select * from research_entity_culture_forms order by entity_id,culture_form_code,culture_role"):
            emit("HAS_CULTURE_FORM", graph_id("Entity", row["entity_id"]), graph_id("CultureForm", row["culture_form_code"]),
                 (row["entity_id"], row["culture_form_code"], row["culture_role"]), role_code=row["culture_role"],
                 culture_form_code=row["culture_form_code"], relation_label_zh=form_labels[row["culture_form_code"]],
                 status=row["assignment_status"], properties={"supporting_fact_count": row["supporting_fact_count"],
                 "strict_supporting_fact_count": row["strict_supporting_fact_count"]})
        for row in con.execute("select * from research_region_hierarchy order by region_id"):
            emit("WITHIN_BASIN", graph_id("StudyRegion", row["region_id"]), graph_id("BasinSection", row["basin_section_id"]),
                 (row["region_id"], row["basin_section_id"]), status=row["relation_code"])
        for row in con.execute("select * from research_event_spatiotemporal_cells order by cell_id"):
            cell = graph_id("EventCell", row["cell_id"])
            emit("HAS_SPATIOTEMPORAL_CELL", graph_id("Entity", row["event_id"]), cell, (row["cell_id"], "event"),
                 stage_code=row["stage_code"], region_id=row["region_id"], observation_tier=row["observation_tier"])
            emit("DURING_STAGE", cell, graph_id("HistoricalStage", row["stage_code"]), (row["cell_id"], "stage"), stage_code=row["stage_code"])
            emit("IN_STUDY_REGION", cell, graph_id("StudyRegion", row["region_id"]), (row["cell_id"], "region"), region_id=row["region_id"])
            emit("IN_BASIN_SECTION", cell, graph_id("BasinSection", row["basin_section_id"]), (row["cell_id"], "basin"))
        for row in con.execute("select * from research_culture_states order by state_id"):
            state = graph_id("CultureState", row["state_id"])
            common = {"stage_code": row["stage_code"], "region_id": row["region_id"],
                      "culture_form_code": row["culture_form_code"], "observation_tier": row["observation_tier"]}
            emit("STATE_OF", state, graph_id("Entity", row["culture_subject_id"]), (row["state_id"], "entity"), **common)
            emit("STATE_DURING", state, graph_id("HistoricalStage", row["stage_code"]), (row["state_id"], "stage"), **common)
            emit("STATE_IN_REGION", state, graph_id("StudyRegion", row["region_id"]), (row["state_id"], "region"), **common)
            emit("STATE_IN_BASIN", state, graph_id("BasinSection", row["basin_section_id"]), (row["state_id"], "basin"), **common)
            emit("STATE_HAS_FORM", state, graph_id("CultureForm", row["culture_form_code"]), (row["state_id"], "form"), **common)
        for row in con.execute("select * from research_culture_state_events order by state_id,event_id,cell_id"):
            emit("STATE_EVENT", graph_id("CultureState", row["state_id"]), graph_id("Entity", row["event_id"]),
                 (row["state_id"], row["event_id"], row["cell_id"]), properties={"cell_id": row["cell_id"]})
        for row in con.execute("select * from research_culture_state_actors order by state_id,actor_id,event_role_code,event_id,fact_id"):
            emit("STATE_ACTOR", graph_id("CultureState", row["state_id"]), graph_id("Entity", row["actor_id"]),
                 (row["state_id"], row["actor_id"], row["event_role_code"], row["event_id"], row["fact_id"]),
                 fact_id=row["fact_id"], role_code=row["event_role_code"],
                 relation_label_zh=ROLE_LABELS.get(row["event_role_code"], row["event_role_code"]),
                 properties={"event_id": row["event_id"]})
        for row in con.execute("select * from research_culture_state_semantic_members order by state_id,semantic_entity_id,event_id,fact_id"):
            emit("STATE_SEMANTIC_MEMBER", graph_id("CultureState", row["state_id"]), graph_id("Entity", row["semantic_entity_id"]),
                 (row["state_id"], row["semantic_entity_id"], row["event_id"], row["fact_id"]), fact_id=row["fact_id"],
                 properties={"event_id": row["event_id"], "semantic_entity_type": row["semantic_entity_type"]})
        for row in con.execute(
            "select * from research_culture_state_value_facets "
            "order by state_id,value_facet_id,spirit_id,state_spirit_fact_id,spirit_value_fact_id"
        ):
            emit(
                "STATE_VALUE_FACET", graph_id("CultureState", row["state_id"]),
                graph_id("Entity", row["value_facet_id"]),
                (
                    row["state_id"], row["value_facet_id"], row["spirit_id"],
                    row["state_spirit_fact_id"], row["spirit_value_fact_id"],
                ),
                fact_id=row["spirit_value_fact_id"], relation_label_zh="价值内涵",
                status=row["derivation_status"],
                properties={
                    "spirit_id": row["spirit_id"], "spirit_name": row["spirit_name"],
                    "state_spirit_fact_id": row["state_spirit_fact_id"],
                    "spirit_value_fact_id": row["spirit_value_fact_id"],
                },
            )
        for row in con.execute("select * from research_evolution_transition_candidates order by candidate_id"):
            candidate = graph_id("TransitionCandidate", row["candidate_id"])
            emit("CANDIDATE_FROM_STATE", candidate, graph_id("CultureState", row["from_state_id"]), (row["candidate_id"], "from"))
            emit("CANDIDATE_TO_STATE", candidate, graph_id("CultureState", row["to_state_id"]), (row["candidate_id"], "to"))
            emit("CANDIDATE_SUPPORTED_BY", candidate, graph_id("Assertion", row["supporting_fact_id"]),
                 (row["candidate_id"], row["supporting_fact_id"]), fact_id=row["supporting_fact_id"])
            emit("CANDIDATE_HAS_TYPE", candidate, graph_id("TransitionType", row["transition_type"]),
                 (row["candidate_id"], row["transition_type"]), status=row["publication_gate_reason"])
        for row in con.execute("select * from research_evolution_transitions order by transition_id"):
            transition = graph_id("EvolutionTransition", row["transition_id"])
            emit("TRANSITION_FROM_STATE", transition, graph_id("CultureState", row["from_state_id"]), (row["transition_id"], "from"))
            emit("TRANSITION_TO_STATE", transition, graph_id("CultureState", row["to_state_id"]), (row["transition_id"], "to"))
            emit("TRANSITION_HAS_TYPE", transition, graph_id("TransitionType", row["transition_type"]),
                 (row["transition_id"], row["transition_type"]), confidence=row["confidence"])
        for row in con.execute("select * from research_evolution_transition_support order by transition_id,candidate_id"):
            emit("TRANSITION_SUPPORTED_BY", graph_id("EvolutionTransition", row["transition_id"]),
                 graph_id("Assertion", row["supporting_fact_id"]), (row["transition_id"], row["candidate_id"]),
                 fact_id=row["supporting_fact_id"], properties={"candidate_id": row["candidate_id"]})
    return counts


def export(input_path: Path, output_dir: Path, report_path: Path) -> dict:
    input_path = input_path.resolve()
    output_dir = output_dir.resolve()
    report_path = report_path.resolve()
    input_hash = sha256(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    nodes_tmp = output_dir / ".nodes.csv.tmp"
    rels_tmp = output_dir / ".relationships.csv.tmp"
    nodes_path = output_dir / "nodes.csv"
    rels_path = output_dir / "relationships.csv"
    for path in (nodes_tmp, rels_tmp):
        path.unlink(missing_ok=True)
    con = sqlite3.connect(f"file:{input_path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("pragma query_only=on")
    try:
        quick_check = str(con.execute("pragma quick_check").fetchone()[0])
        if quick_check != "ok":
            raise RuntimeError(f"input quick_check failed: {quick_check}")
        creative_media = {
            "creative_work_nodes": int(con.execute(
                "select count(*) from research_entities where entity_type='CreativeWork'"
            ).fetchone()[0]),
            "media_populated": int(con.execute(
                "select count(*) from research_creative_work_media"
            ).fetchone()[0]),
            "media_unknown": int(con.execute(
                "select count(*) from research_creative_work_media where media_type='未知'"
            ).fetchone()[0]),
            "media_qwen_v2": int(con.execute(
                "select count(*) from research_creative_work_media where "
                "classification_method='qwen_v2_semantic_classification'"
            ).fetchone()[0]),
            "non_creative_media_populated": int(con.execute(
                "select count(*) from research_creative_work_media m join research_entities e using(entity_id) "
                "where e.entity_type<>'CreativeWork'"
            ).fetchone()[0]),
        }
        if creative_media["creative_work_nodes"] != creative_media["media_populated"]:
            raise RuntimeError(f"incomplete CreativeWork media coverage: {creative_media}")
        if creative_media["non_creative_media_populated"]:
            raise RuntimeError(f"media metadata attached to non-CreativeWork entities: {creative_media}")
        node_counts, blank_captions = write_nodes(con, nodes_tmp)
        relationship_counts = write_relationships(con, rels_tmp)
    except Exception:
        nodes_tmp.unlink(missing_ok=True)
        rels_tmp.unlink(missing_ok=True)
        raise
    finally:
        con.close()
    if sha256(input_path) != input_hash:
        nodes_tmp.unlink(missing_ok=True)
        rels_tmp.unlink(missing_ok=True)
        raise RuntimeError("V2 evolution input changed during graph export")
    if blank_captions:
        nodes_tmp.unlink(missing_ok=True)
        rels_tmp.unlink(missing_ok=True)
        raise RuntimeError(f"blank Chinese/research captions: {blank_captions}")
    os.replace(nodes_tmp, nodes_path)
    os.replace(rels_tmp, rels_path)
    args_path = output_dir / "neo4j_import_args.txt"
    args_path.write_text(
        "neo4j\n--id-type=string\n--nodes=/import/nodes.csv\n--relationships=/import/relationships.csv\n"
        "--bad-tolerance=0\n--skip-duplicate-nodes=false\n--skip-bad-relationships=false\n"
        "--ignore-extra-columns=false\n--trim-strings=false\n",
        encoding="utf-8",
    )
    payload = {
        "status": "PASS", "build_version": BUILD_VERSION,
        "input": {"path": str(input_path), "sha256": input_hash, "unchanged": True},
        "node_counts": dict(sorted(node_counts.items())), "relationship_counts": dict(sorted(relationship_counts.items())),
        "total_nodes": sum(node_counts.values()), "total_relationships": sum(relationship_counts.values()),
        "blank_captions": blank_captions, "creative_media": creative_media,
        "files": {
            "nodes.csv": {"path": str(nodes_path), "size_bytes": nodes_path.stat().st_size, "sha256": sha256(nodes_path)},
            "relationships.csv": {"path": str(rels_path), "size_bytes": rels_path.stat().st_size, "sha256": sha256(rels_path)},
            "neo4j_import_args.txt": {"path": str(args_path), "size_bytes": args_path.stat().st_size, "sha256": sha256(args_path)},
        },
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_tmp = report_path.with_name(f".{report_path.name}.tmp")
    report_tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(report_tmp, report_path)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    print(json.dumps(export(args.input, args.output_dir, args.report), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
