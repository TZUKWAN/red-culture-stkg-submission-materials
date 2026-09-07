"""Resolve pending V2 entity types supported by strict structure and accepted same-name types."""

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
REPORT = ROOT / "audit_reports" / "stkg_v2_strict_same_name_consensus.json"
RULE_NAME = "stkg-v2-strict-same-name-consensus-1"


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def append_json_value(raw: str, value: str) -> str:
    values = json.loads(raw or "[]")
    if value not in values:
        values.append(value)
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def choose_consensus_type(
    hint: str, accepted_types: set[str], source_type: str = ""
) -> tuple[str, str] | None:
    if source_type in {"CreativeWork", "Document"} and hint != source_type:
        return None
    if hint and accepted_types == {hint}:
        return hint, "strict_and_exact_same_name_type"
    if hint == "Place" and accepted_types == {"AdministrativeRegion"}:
        return "AdministrativeRegion", "strict_place_with_same_name_administrative_subtype"
    return None


def candidate_rows(con: sqlite3.Connection) -> list[dict]:
    accepted_by_name: dict[str, set[str]] = defaultdict(set)
    for row in con.execute(
        "select canonical_name,source_entity_type,semantic_entity_type from v2_entities "
        "where semantic_status='auto_accepted'"
    ):
        accepted_by_name[str(row[0])].add(str(row[2] or row[1]))
    rows = con.execute(
        "select e.*,t.task_id,t.status task_status from v2_entities e "
        "left join v2_model_tasks t on t.unit_kind='entity' and t.unit_id=e.entity_id "
        "and t.task_type='entity_type' where e.semantic_status in "
        "('model_review','manual_review','pending') order by e.entity_id"
    ).fetchall()
    candidates = []
    for row in rows:
        hint = strict_v2_entity_type_hint(
            str(row["canonical_name"]), str(row["source_entity_type"])
        )
        accepted_types = accepted_by_name.get(str(row["canonical_name"]), set())
        resolution = choose_consensus_type(hint, accepted_types, str(row["source_entity_type"]))
        if resolution:
            final_type, reason = resolution
            candidates.append({
                "row": row, "final_type": final_type, "reason": reason,
                "strict_hint": hint, "accepted_same_name_types": sorted(accepted_types),
            })
    return candidates


def run(database: Path, report_path: Path, apply: bool) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        candidates = candidate_rows(con)
        by_final_type = Counter(item["final_type"] for item in candidates)
        by_reason = Counter(item["reason"] for item in candidates)
        by_change = Counter(
            f"{item['row']['source_entity_type']}->{item['final_type']}" for item in candidates
        )
        inserted_resolutions = 0
        if apply:
            con.execute("begin immediate")
            for item in candidates:
                row = item["row"]
                final_type = item["final_type"]
                task_id = str(row["task_id"] or stable_id("V2RULETASK", row["entity_id"], RULE_NAME))
                resolution_id = stable_id("V2RULE", row["entity_id"], RULE_NAME)
                cursor = con.execute(
                    "insert or ignore into v2_rule_resolutions values(?,?,?,?,?,?,?)",
                    (
                        resolution_id, task_id, row["entity_id"], RULE_NAME,
                        json.dumps({
                            "source_entity_type": row["source_entity_type"],
                            "semantic_entity_type": row["semantic_entity_type"],
                            "semantic_status": row["semantic_status"],
                            "task_status": row["task_status"],
                        }, ensure_ascii=False, sort_keys=True),
                        json.dumps({
                            "semantic_entity_type": final_type,
                            "semantic_family": semantic_family(final_type),
                            "type_facets": list(type_facets(final_type)),
                            "strict_hint": item["strict_hint"],
                            "accepted_same_name_types": item["accepted_same_name_types"],
                            "reason": item["reason"],
                        }, ensure_ascii=False, sort_keys=True), now,
                    ),
                )
                inserted_resolutions += cursor.rowcount
                con.execute(
                    "update v2_entities set semantic_entity_type=?,semantic_status='auto_accepted',"
                    "confidence=0.99,risk_tier='A',semantic_family=?,type_facets_json=?,"
                    "decision_sources_json=?,risk_flags_json=?,method_version=?,updated_at=? "
                    "where entity_id=?",
                    (
                        final_type, semantic_family(final_type),
                        json.dumps(type_facets(final_type), ensure_ascii=False),
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
        remaining = len(candidate_rows(con)) if apply else len(candidates)
        report = {
            "result": "PASS" if not apply or remaining == 0 else "FAIL",
            "apply": apply,
            "rule_name": RULE_NAME,
            "candidate_count": len(candidates),
            "inserted_resolutions": inserted_resolutions,
            "remaining_candidates": remaining,
            "by_final_type": dict(sorted(by_final_type.items())),
            "by_reason": dict(sorted(by_reason.items())),
            "by_change": dict(sorted(by_change.items())),
            "sample": [
                {
                    "entity_id": item["row"]["entity_id"],
                    "canonical_name": item["row"]["canonical_name"],
                    "source_type": item["row"]["source_entity_type"],
                    "final_type": item["final_type"],
                    "reason": item["reason"],
                    "accepted_same_name_types": item["accepted_same_name_types"],
                }
                for item in candidates[:400]
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
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.db, args.report, args.apply), ensure_ascii=False))


if __name__ == "__main__":
    main()
