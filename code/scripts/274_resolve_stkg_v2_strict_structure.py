"""Resolve pending V2 entity types with conservative, structure-only rules."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from stkg_v2_semantics import (
    SPECIALIZED_TYPES,
    V2_CULTURAL_SITE_SUFFIXES,
    V2_DOCUMENT_SUFFIXES,
    V2_FIXED_MEMORIAL_ARTIFACT_SUFFIXES,
    V2_HISTORICAL_ADMIN_SUFFIXES,
    V2_INSTITUTION_SUFFIXES,
    V2_KNOWN_RIVERS,
    V2_FORMATION_EVENT_RE,
    V2_NUMBERED_UNIT_RE,
    V2_ORGANIZATION_SUFFIXES,
    V2_POSITION_SUFFIXES,
    V2_STRICT_EVENT_SUFFIXES,
    V2_STRICT_PLACE_DESCRIPTOR_SUFFIXES,
    semantic_family,
    strict_v2_entity_type_hint,
    type_facets,
)


DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_strict_structure_resolution.json"
RULE_NAME = "stkg-v2-strict-structure-1"

SEPARATOR_RE = re.compile(r"[/／,，;；:：、]")
ACTION_LIKE_PREFIXES = (
    "担任", "任职", "办夜校", "抢修", "修筑", "修建", "建设", "重建",
    "保护", "传达", "听取", "讨论", "审议", "围攻", "接管",
)


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def append_json_value(raw: str, value: str) -> str:
    values = json.loads(raw or "[]")
    if value not in values:
        values.append(value)
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def unambiguous_place_structure(name: str) -> bool:
    text = str(name or "").strip()
    if not text or SEPARATOR_RE.search(text) or text.startswith(ACTION_LIKE_PREFIXES):
        return False
    if text in V2_KNOWN_RIVERS:
        return True
    if text.endswith(V2_STRICT_PLACE_DESCRIPTOR_SUFFIXES):
        return True
    return len(text) >= 3 and text.endswith(("铁路", "公路", "大道", "街"))


def choose_strict_structure_type(
    name: str, source_type: str, hint: str
) -> tuple[str, str] | None:
    """Return only structure decisions whose false-positive modes are explicitly blocked."""
    text = str(name or "").strip()
    source = str(source_type or "")
    if not text or not hint:
        return None

    if source in SPECIALIZED_TYPES and hint != source:
        return None

    if text.startswith(ACTION_LIKE_PREFIXES) and hint in {
        "Organization", "Institution", "Place", "Position", "Document"
    }:
        return None

    if source == hint:
        if hint == "Place" and not unambiguous_place_structure(text):
            return None
        return hint, "strict_structure_confirms_source_type"

    if SEPARATOR_RE.search(text) or text.startswith(ACTION_LIKE_PREFIXES):
        return None

    if hint == "Artifact" and (
        text.endswith(V2_FIXED_MEMORIAL_ARTIFACT_SUFFIXES) or text.endswith("文件包")
    ):
        return hint, "fixed_physical_artifact_structure"
    if hint == "Institution" and text.endswith(V2_INSTITUTION_SUFFIXES):
        return hint, "institution_suffix_structure"
    if hint == "Organization" and (
        text.endswith(V2_ORGANIZATION_SUFFIXES) or V2_NUMBERED_UNIT_RE.fullmatch(text)
    ):
        reason = (
            "numbered_unit_structure"
            if V2_NUMBERED_UNIT_RE.fullmatch(text)
            else "explicit_organization_suffix_structure"
        )
        return hint, reason
    if hint == "Document" and text.endswith(V2_DOCUMENT_SUFFIXES):
        return hint, "document_suffix_structure"
    if hint == "Event" and (
        text.endswith(V2_STRICT_EVENT_SUFFIXES) or V2_FORMATION_EVENT_RE.fullmatch(text)
    ):
        reason = (
            "formation_event_structure"
            if V2_FORMATION_EVENT_RE.fullmatch(text)
            else "event_suffix_structure"
        )
        return hint, reason
    if hint == "Position" and text.endswith(V2_POSITION_SUFFIXES):
        return hint, "position_suffix_structure"
    if hint == "Spirit" and text.endswith("精神"):
        return hint, "spirit_suffix_structure"
    if hint == "CulturalSite" and text.endswith(V2_CULTURAL_SITE_SUFFIXES):
        return hint, "cultural_site_suffix_structure"
    if hint == "AdministrativeRegion" and text.endswith(V2_HISTORICAL_ADMIN_SUFFIXES):
        return hint, "historical_admin_suffix_structure"
    if hint == "Place" and source == "Place" and unambiguous_place_structure(text):
        return hint, "unambiguous_place_structure"
    return None


def candidate_rows(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "select e.*,t.task_id,t.status task_status from v2_entities e "
        "join v2_model_tasks t on t.unit_kind='entity' and t.unit_id=e.entity_id "
        "and t.task_type='entity_type' where e.semantic_status='model_review' "
        "and e.semantic_entity_type is null and t.status='pending' order by e.entity_id"
    ).fetchall()
    candidates = []
    for row in rows:
        hint = strict_v2_entity_type_hint(
            str(row["canonical_name"]), str(row["source_entity_type"])
        )
        resolution = choose_strict_structure_type(
            str(row["canonical_name"]), str(row["source_entity_type"]), hint
        )
        if resolution:
            final_type, reason = resolution
            candidates.append({
                "row": row,
                "final_type": final_type,
                "reason": reason,
                "strict_hint": hint,
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
            f"{item['row']['source_entity_type']}->{item['final_type']}"
            for item in candidates
        )
        inserted_resolutions = 0
        if apply:
            con.execute("begin immediate")
            for item in candidates:
                row = item["row"]
                final_type = item["final_type"]
                resolution_id = stable_id("V2RULE", row["entity_id"], RULE_NAME)
                cursor = con.execute(
                    "insert or ignore into v2_rule_resolutions values(?,?,?,?,?,?,?)",
                    (
                        resolution_id,
                        row["task_id"],
                        row["entity_id"],
                        RULE_NAME,
                        json.dumps({
                            "source_entity_type": row["source_entity_type"],
                            "semantic_status": row["semantic_status"],
                            "task_status": row["task_status"],
                        }, ensure_ascii=False, sort_keys=True),
                        json.dumps({
                            "semantic_entity_type": final_type,
                            "semantic_family": semantic_family(final_type),
                            "type_facets": list(type_facets(final_type)),
                            "strict_hint": item["strict_hint"],
                            "reason": item["reason"],
                        }, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                inserted_resolutions += cursor.rowcount
                con.execute(
                    "update v2_entities set semantic_entity_type=?,semantic_status='auto_accepted',"
                    "confidence=0.99,risk_tier='A',semantic_family=?,type_facets_json=?,"
                    "decision_sources_json=?,risk_flags_json=?,method_version=?,updated_at=? "
                    "where entity_id=?",
                    (
                        final_type,
                        semantic_family(final_type),
                        json.dumps(type_facets(final_type), ensure_ascii=False),
                        append_json_value(
                            row["decision_sources_json"], f"deterministic_rule:{RULE_NAME}"
                        ),
                        append_json_value(row["risk_flags_json"], item["reason"]),
                        RULE_NAME,
                        now,
                        row["entity_id"],
                    ),
                )
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
                }
                for item in candidates[:300]
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
