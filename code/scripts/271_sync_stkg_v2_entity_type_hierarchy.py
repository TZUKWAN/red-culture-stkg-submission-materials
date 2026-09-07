"""Synchronize derived entity family and type facets with the effective V2 entity type."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from stkg_v2_semantics import semantic_family, type_facets


DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_entity_type_hierarchy_sync.json"
RULE_NAME = "stkg-v2-entity-type-hierarchy-sync-1"


def expected_metadata(source_type: str, semantic_type: str | None) -> tuple[str, str]:
    effective_type = str(semantic_type or source_type)
    return (
        semantic_family(effective_type),
        json.dumps(type_facets(effective_type), ensure_ascii=False),
    )


def candidate_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = con.execute(
        "select entity_id,source_entity_type,semantic_entity_type,semantic_family,type_facets_json "
        "from v2_entities order by entity_id"
    ).fetchall()
    candidates = []
    for row in rows:
        expected_family, expected_facets = expected_metadata(
            str(row["source_entity_type"]), row["semantic_entity_type"]
        )
        if row["semantic_family"] != expected_family or row["type_facets_json"] != expected_facets:
            candidates.append(row)
    return candidates


def run(database: Path, report_path: Path, apply: bool) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        rows = candidate_rows(con)
        by_effective_type = Counter(
            str(row["semantic_entity_type"] or row["source_entity_type"]) for row in rows
        )
        by_stale_family = Counter(str(row["semantic_family"] or "<null>") for row in rows)
        updated = 0
        if apply:
            con.execute("begin immediate")
            for row in rows:
                family, facets_json = expected_metadata(
                    str(row["source_entity_type"]), row["semantic_entity_type"]
                )
                cursor = con.execute(
                    "update v2_entities set semantic_family=?,type_facets_json=?,updated_at=? "
                    "where entity_id=? and (semantic_family is not ? or type_facets_json<>?)",
                    (family, facets_json, now, row["entity_id"], family, facets_json),
                )
                updated += cursor.rowcount
            con.commit()
        remaining = len(candidate_rows(con)) if apply else len(rows)
        report = {
            "result": "PASS" if not apply or remaining == 0 else "FAIL",
            "apply": apply,
            "rule_name": RULE_NAME,
            "candidate_count": len(rows),
            "updated": updated,
            "remaining_mismatches": remaining,
            "by_effective_type": dict(sorted(by_effective_type.items())),
            "by_stale_family": dict(sorted(by_stale_family.items())),
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
