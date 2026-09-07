"""Resolve pending entity types when a fact uses the entity as a place reference."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from stkg_v2_semantics import semantic_family, strict_v2_entity_type_hint, type_facets


DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
SPATIAL_DATABASE = ROOT / "derived" / "red_culture_stkg_spatial_v1.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_spatial_reference_entity_resolution.json"
RULE_NAME = "stkg-v2-spatial-reference-entity-resolution-1"
SPATIAL_TYPES = {"Place", "AdministrativeRegion", "CulturalSite"}
STRICT_NONSPATIAL_TYPES = {
    "Organization", "Institution", "Event", "Document", "Artifact", "CreativeWork",
    "Person", "Concept", "Spirit", "ValueFacet", "Position", "TimePeriod",
}


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def append_json_value(raw: str, value: str) -> str:
    values = json.loads(raw or "[]")
    if value not in values:
        values.append(value)
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def choose_resolution(
    lexical_hint: str,
    accepted_same_name_types: set[str],
    administrative_gazetteer_match: bool,
) -> tuple[str, str, float] | None:
    if lexical_hint in STRICT_NONSPATIAL_TYPES:
        return lexical_hint, "strict_structural_nonspatial_type", 0.99
    if accepted_same_name_types and accepted_same_name_types <= SPATIAL_TYPES:
        if "CulturalSite" in accepted_same_name_types:
            final_type = "CulturalSite"
        elif "AdministrativeRegion" in accepted_same_name_types:
            final_type = "AdministrativeRegion"
        else:
            final_type = "Place"
        return final_type, "same_name_spatial_family_consensus", 0.98
    if lexical_hint in {"AdministrativeRegion", "CulturalSite"}:
        return lexical_hint, "strict_structural_spatial_subtype", 0.99
    if administrative_gazetteer_match:
        return "AdministrativeRegion", "administrative_gazetteer_exact_match", 0.99
    if lexical_hint == "Place":
        return "Place", "strict_structural_place_type", 0.99
    return None


def load_admin_names(spatial_database: Path) -> set[str]:
    con = sqlite3.connect(f"file:{spatial_database.resolve()}?mode=ro", uri=True)
    try:
        names = {str(row[0]) for row in con.execute("select unit_name from stkg_administrative_units")}
        names.update(str(row[0]) for row in con.execute("select province_name from stkg_study_regions"))
        return names
    finally:
        con.close()


def candidate_rows(con: sqlite3.Connection, admin_names: set[str]) -> list[dict]:
    rows = con.execute(
        "select e.*,t.task_id,t.status task_status,count(s.fact_id) canonical_place_references "
        "from v2_entities e join v2_assertion_scopes s on s.canonical_place_id=e.entity_id "
        "left join v2_model_tasks t on t.unit_kind='entity' and t.unit_id=e.entity_id "
        "and t.task_type='entity_type' where e.semantic_status in "
        "('model_review','manual_review','pending') group by e.entity_id order by e.entity_id"
    ).fetchall()
    accepted_by_name: dict[str, set[str]] = defaultdict(set)
    pending_names = {str(row["canonical_name"]) for row in rows}
    placeholders = ",".join("?" for _ in pending_names)
    if pending_names:
        for name, source_type, semantic_type in con.execute(
            f"select canonical_name,source_entity_type,semantic_entity_type from v2_entities "
            f"where semantic_status='auto_accepted' and canonical_name in ({placeholders})",
            tuple(sorted(pending_names)),
        ):
            accepted_by_name[str(name)].add(str(semantic_type or source_type))
    candidates = []
    for row in rows:
        name = str(row["canonical_name"])
        hint = strict_v2_entity_type_hint(name, str(row["source_entity_type"]))
        accepted_types = accepted_by_name.get(name, set())
        resolution = choose_resolution(hint, accepted_types, name in admin_names)
        if resolution is None:
            continue
        final_type, reason, confidence = resolution
        candidates.append({
            "row": row,
            "final_type": final_type,
            "reason": reason,
            "confidence": confidence,
            "lexical_hint": hint,
            "accepted_same_name_types": sorted(accepted_types),
            "administrative_gazetteer_match": name in admin_names,
        })
    return candidates


def run(database: Path, spatial_database: Path, report_path: Path, apply: bool) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    admin_names = load_admin_names(spatial_database)
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        candidates = candidate_rows(con, admin_names)
        by_final_type = Counter(item["final_type"] for item in candidates)
        by_reason = Counter(item["reason"] for item in candidates)
        inserted_resolutions = 0
        if apply:
            con.execute("begin immediate")
            for item in candidates:
                row = item["row"]
                final_type = item["final_type"]
                task_id = str(row["task_id"] or stable_id("V2RULETASK", row["entity_id"], RULE_NAME))
                resolution_id = stable_id("V2RULE", row["entity_id"], RULE_NAME)
                before = {
                    "semantic_entity_type": row["semantic_entity_type"],
                    "semantic_status": row["semantic_status"],
                    "confidence": row["confidence"],
                    "risk_tier": row["risk_tier"],
                    "task_status": row["task_status"],
                }
                after = {
                    "semantic_entity_type": final_type,
                    "semantic_family": semantic_family(final_type),
                    "type_facets": list(type_facets(final_type)),
                    "confidence": item["confidence"],
                    "reason": item["reason"],
                    "lexical_hint": item["lexical_hint"],
                    "accepted_same_name_types": item["accepted_same_name_types"],
                    "administrative_gazetteer_match": item["administrative_gazetteer_match"],
                    "canonical_place_references": row["canonical_place_references"],
                }
                cursor = con.execute(
                    "insert or ignore into v2_rule_resolutions values(?,?,?,?,?,?,?)",
                    (
                        resolution_id, task_id, row["entity_id"], RULE_NAME,
                        json.dumps(before, ensure_ascii=False, sort_keys=True),
                        json.dumps(after, ensure_ascii=False, sort_keys=True), now,
                    ),
                )
                inserted_resolutions += cursor.rowcount
                con.execute(
                    "update v2_entities set semantic_entity_type=?,semantic_family=?,"
                    "type_facets_json=?,semantic_status='auto_accepted',confidence=?,risk_tier='A',"
                    "decision_sources_json=?,risk_flags_json=?,method_version=?,updated_at=? "
                    "where entity_id=?",
                    (
                        final_type, semantic_family(final_type),
                        json.dumps(type_facets(final_type), ensure_ascii=False), item["confidence"],
                        append_json_value(row["decision_sources_json"], f"deterministic_rule:{RULE_NAME}"),
                        append_json_value(row["risk_flags_json"], item["reason"]),
                        RULE_NAME, now, row["entity_id"],
                    ),
                )
                if row["task_id"]:
                    con.execute(
                        "update v2_model_tasks set status='completed',updated_at=? where task_id=?",
                        (now, row["task_id"]),
                    )
                con.execute(
                    "update v2_semantic_conflicts set status='resolved',resolution_decision_id=?,"
                    "resolved_at=? where unit_kind='entity' and unit_id=? and status='open' "
                    "and conflict_type<>'identity_ambiguity'",
                    (resolution_id, now, row["entity_id"]),
                )
            con.commit()
        remaining_candidates = len(candidate_rows(con, admin_names)) if apply else len(candidates)
        remaining_spatial_pending = con.execute(
            "select count(distinct e.entity_id) from v2_assertion_scopes s join v2_entities e "
            "on e.entity_id=s.canonical_place_id where e.semantic_status in "
            "('model_review','manual_review','pending')"
        ).fetchone()[0]
        report = {
            "result": "PASS" if not apply or remaining_candidates == 0 else "FAIL",
            "apply": apply,
            "rule_name": RULE_NAME,
            "candidate_count": len(candidates),
            "inserted_resolutions": inserted_resolutions,
            "remaining_candidates": remaining_candidates,
            "remaining_spatial_pending_entities": remaining_spatial_pending,
            "by_final_type": dict(sorted(by_final_type.items())),
            "by_reason": dict(sorted(by_reason.items())),
            "sample": [
                {
                    "entity_id": item["row"]["entity_id"],
                    "canonical_name": item["row"]["canonical_name"],
                    "source_type": item["row"]["source_entity_type"],
                    "final_type": item["final_type"],
                    "reason": item["reason"],
                    "lexical_hint": item["lexical_hint"],
                    "accepted_same_name_types": item["accepted_same_name_types"],
                    "administrative_gazetteer_match": item["administrative_gazetteer_match"],
                    "canonical_place_references": item["row"]["canonical_place_references"],
                }
                for item in candidates[:200]
            ],
            "quick_check": con.execute("pragma quick_check").fetchone()[0],
            "foreign_key_violations": len(con.execute("pragma foreign_key_check").fetchall()),
            "created_at": now,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DATABASE)
    parser.add_argument("--spatial-db", type=Path, default=SPATIAL_DATABASE)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.db, args.spatial_db, args.report, args.apply), ensure_ascii=False))


if __name__ == "__main__":
    main()
