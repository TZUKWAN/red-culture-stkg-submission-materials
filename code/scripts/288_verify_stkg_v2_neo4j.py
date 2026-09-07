"""Verify the isolated STKG V2 Neo4j database without mutating it."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import urllib.request
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPORT_REPORT = ROOT / "audit_reports" / "stkg_v2_graph_export.json"
DEFAULT_SQLITE = ROOT / "derived" / "red_culture_stkg_final_v2.sqlite"
DEFAULT_PASSWORD_FILE = ROOT / ".codex" / "runtime" / "neo4j_stkg_v2_password.txt"
DEFAULT_OUTPUT = ROOT / "audit_reports" / "stkg_v2_neo4j_verification.json"
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def safe_identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe Neo4j identifier: {value!r}")
    return value


def all_true(checks: dict[str, bool]) -> bool:
    return bool(checks) and all(value is True for value in checks.values())


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_sqlite_expectations(path: Path) -> dict:
    resolved = path.resolve()
    con = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    try:
        return {
            "assertion_tiers": {
                str(tier): int(value)
                for tier, value in con.execute(
                    "select research_tier,count(*) from research_assertions group by research_tier"
                )
            },
            "trusted_culture_states": int(con.execute(
                "select count(*) from research_culture_states "
                "where observation_tier='trusted_event_spacetime'"
            ).fetchone()[0]),
            "published_transitions": int(con.execute(
                "select count(*) from research_evolution_transitions"
            ).fetchone()[0]),
            "published_transition_supports": int(con.execute(
                "select count(*) from research_evolution_transition_support"
            ).fetchone()[0]),
        }
    finally:
        con.close()


def verify_ui(url: str) -> dict:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/api/health", timeout=20) as response:
            payload = json.load(response)
        return {"reachable": payload.get("status") == "ok", "counts": payload.get("counts", {})}
    except Exception as exc:  # The report must preserve the concrete connectivity failure.
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default="bolt://127.0.0.1:7690")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password-file", type=Path, default=DEFAULT_PASSWORD_FILE)
    parser.add_argument("--export-report", type=Path, default=DEFAULT_EXPORT_REPORT)
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ui-url", default="http://127.0.0.1:8787")
    args = parser.parse_args()

    export = read_json(args.export_report)
    sqlite_expected = read_sqlite_expectations(args.sqlite)
    password = args.password_file.read_text(encoding="utf-8").strip()
    expected_nodes = {str(k): int(v) for k, v in export["node_counts"].items()}
    expected_relationships = {str(k): int(v) for k, v in export["relationship_counts"].items()}

    with GraphDatabase.driver(args.uri, auth=(args.user, password)) as driver:
        driver.verify_connectivity()
        with driver.session(database="neo4j") as session:
            actual_nodes = {
                label: int(session.run(
                    f"MATCH (n:{safe_identifier(label)}) RETURN count(n) AS value"
                ).single(strict=True)["value"])
                for label in expected_nodes
            }
            actual_relationships = {
                rel_type: int(session.run(
                    f"MATCH ()-[r:{safe_identifier(rel_type)}]->() RETURN count(r) AS value"
                ).single(strict=True)["value"])
                for rel_type in expected_relationships
            }
            total_nodes = int(session.run("MATCH (n) RETURN count(n) AS value").single(strict=True)["value"])
            total_relationships = int(
                session.run("MATCH ()-[r]->() RETURN count(r) AS value").single(strict=True)["value"]
            )
            blank_titles = int(session.run(
                "MATCH (n) WHERE n.name IS NULL OR trim(toString(n.name))='' "
                "OR n.caption IS NULL OR trim(toString(n.caption))='' RETURN count(n) AS value"
            ).single(strict=True)["value"])
            missing_ids = int(session.run(
                "MATCH (n) WHERE n.stable_id IS NULL OR trim(toString(n.stable_id))='' RETURN count(n) AS value"
            ).single(strict=True)["value"])
            duplicate = dict(session.run(
                "MATCH (n) WITH n.stable_id AS stable_id,count(*) AS copies "
                "WHERE stable_id IS NOT NULL AND copies>1 "
                "RETURN count(*) AS duplicate_keys,coalesce(sum(copies-1),0) AS extra_nodes"
            ).single(strict=True))
            constraints = [dict(row) for row in session.run(
                "SHOW CONSTRAINTS YIELD name,type,labelsOrTypes,properties "
                "RETURN name,type,labelsOrTypes,properties ORDER BY name"
            )]
            indexes = [dict(row) for row in session.run(
                "SHOW INDEXES YIELD name,state,type,labelsOrTypes,properties "
                "RETURN name,state,type,labelsOrTypes,properties ORDER BY name"
            )]
            tier_counts = {
                str(row["tier"]): int(row["value"])
                for row in session.run(
                    "MATCH (a:Assertion) RETURN a.research_tier AS tier,count(*) AS value ORDER BY tier"
                )
            }
            identities = {}
            for canonical, alias in (("蔡和森", "林彬"), ("毛泽东", "毛润之"), ("邓小平", "邓希贤")):
                row = session.run(
                    "MATCH (e:Entity {name:$canonical}) "
                    "RETURN count(e) AS count,collect(e.entity_type) AS types,"
                    "any(x IN collect(coalesce(e.properties_json,'')) WHERE x CONTAINS $alias) AS alias_present",
                    canonical=canonical,
                    alias=alias,
                ).single(strict=True)
                identities[f"{canonical}/{alias}"] = {
                    "canonical_count": int(row["count"]),
                    "types": list(row["types"]),
                    "alias_present": bool(row["alias_present"]),
                }
            capability = {
                "trusted_culture_states": int(session.run(
                    "MATCH (n:CultureState {observation_tier:'trusted_event_spacetime'}) RETURN count(n) AS value"
                ).single(strict=True)["value"]),
                "published_transitions": int(session.run(
                    "MATCH (n:EvolutionTransition) RETURN count(n) AS value"
                ).single(strict=True)["value"]),
                "published_transition_supports": int(session.run(
                    "MATCH (:EvolutionTransition)-[r:TRANSITION_SUPPORTED_BY]->() RETURN count(r) AS value"
                ).single(strict=True)["value"]),
                "published_nontrusted_state_endpoints": int(session.run(
                    "MATCH (t:EvolutionTransition)-[:TRANSITION_FROM_STATE|TRANSITION_TO_STATE]->(s:CultureState) "
                    "WHERE s.observation_tier<>'trusted_event_spacetime' RETURN count(*) AS value"
                ).single(strict=True)["value"]),
            }
            creative_media = dict(session.run(
                "MATCH (n:CreativeWork) RETURN count(n) AS creative_work_nodes,"
                "count(n.media_type) AS media_populated,"
                "sum(CASE WHEN n.media_type='未知' THEN 1 ELSE 0 END) AS media_unknown,"
                "sum(CASE WHEN n.media_method='qwen_v2_semantic_classification' THEN 1 ELSE 0 END) AS media_qwen_v2"
            ).single(strict=True))
            creative_media["non_creative_media_populated"] = int(session.run(
                "MATCH (n:Entity) WHERE NOT n:CreativeWork AND n.media_type IS NOT NULL "
                "RETURN count(n) AS value"
            ).single(strict=True)["value"])

    constraint_labels = {
        str(row["labelsOrTypes"][0])
        for row in constraints
        if row["type"] == "UNIQUENESS" and row["properties"] == ["stable_id"] and row["labelsOrTypes"]
    }
    required_indexes = {"entity_name_fulltext_v2", "entity_name_v2", "entity_type_v2", "creative_work_media_v2",
                        "state_stage_v2", "state_region_v2", "state_form_v2", "state_tier_v2"}
    online_indexes = {str(row["name"]) for row in indexes if row["state"] == "ONLINE"}
    checks = {
        "export_report_pass": export.get("status") == "PASS",
        "node_counts_match": actual_nodes == expected_nodes,
        "relationship_counts_match": actual_relationships == expected_relationships,
        "total_nodes_match": total_nodes == int(export["total_nodes"]),
        "total_relationships_match": total_relationships == int(export["total_relationships"]),
        "no_blank_chinese_titles": blank_titles == 0,
        "no_missing_stable_ids": missing_ids == 0,
        "no_duplicate_stable_ids": int(duplicate["duplicate_keys"]) == 0,
        "all_uniqueness_constraints_present": set(expected_nodes) <= constraint_labels,
        "required_indexes_online": required_indexes <= online_indexes,
        "assertion_tiers_complete": tier_counts == sqlite_expected["assertion_tiers"],
        "identity_aliases_resolved": all(
            item["canonical_count"] == 1 and item["types"] == ["Person"] and item["alias_present"]
            for item in identities.values()
        ),
        "trusted_state_count": capability["trusted_culture_states"] == sqlite_expected["trusted_culture_states"],
        "published_transition_count": capability["published_transitions"] == sqlite_expected["published_transitions"],
        "published_transition_support_count": capability["published_transition_supports"] == sqlite_expected["published_transition_supports"],
        "published_transitions_use_trusted_states": capability["published_nontrusted_state_endpoints"] == 0,
        "creative_media_complete": {
            key: int(creative_media[key]) for key in export["creative_media"]
        } == export["creative_media"],
    }
    ui = verify_ui(args.ui_url)
    checks["research_ui_reachable"] = bool(ui["reachable"])
    report = {
        "status": "PASS" if all_true(checks) else "FAIL",
        "build_version": "red-culture-stkg-neo4j-verification-v2-1",
        "neo4j_uri": args.uri,
        "export_report": str(args.export_report.resolve()),
        "expected": {
            "node_counts": expected_nodes,
            "relationship_counts": expected_relationships,
            "sqlite_capability": sqlite_expected,
        },
        "actual": {
            "node_counts": actual_nodes,
            "relationship_counts": actual_relationships,
            "total_nodes": total_nodes,
            "total_relationships": total_relationships,
            "blank_titles": blank_titles,
            "missing_stable_ids": missing_ids,
            "duplicate_stable_ids": duplicate,
            "assertion_tiers": tier_counts,
        },
        "schema": {"constraints": constraints, "indexes": indexes},
        "identity_cases": identities,
        "capability": capability,
        "creative_media": creative_media,
        "ui": ui,
        "checks": checks,
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
