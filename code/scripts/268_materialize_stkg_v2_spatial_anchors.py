"""Materialize validated assertion-level spatial anchors for STKG V2."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_spatial_anchors.json"
RULE_VERSION = "stkg-v2-spatial-anchor-1"

SPATIAL_TYPES = {"Place", "AdministrativeRegion", "CulturalSite"}
PENDING_ENTITY_STATUSES = {"model_review", "manual_review", "pending"}
ARTIFACT_SITE_SUFFIXES = ("纪念碑", "纪念塔", "雕像", "墓碑")
COMPOUND_SEPARATORS = ("/", "／", ",", "，", ";", "；", ":", "：")


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def normalize_label(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", "", text)


def classify_anchor(
    place_raw: object,
    canonical_place_id: object,
    entity: sqlite3.Row | None,
) -> dict[str, object]:
    raw = normalize_label(place_raw)
    source_id = str(canonical_place_id or "").strip()
    if not source_id:
        if raw:
            return {
                "validated_anchor_id": None,
                "anchor_kind": "raw_only",
                "edge_type": None,
                "target_entity_type": None,
                "target_entity_status": None,
                "validation_status": "model_review",
                "reason_code": "raw_place_without_canonical_entity",
                "confidence": None,
                "conflict_type": "unresolved_canonical_place_target",
            }
        return {
            "validated_anchor_id": None,
            "anchor_kind": "none",
            "edge_type": None,
            "target_entity_type": None,
            "target_entity_status": None,
            "validation_status": "not_applicable",
            "reason_code": "no_spatial_claim",
            "confidence": 1.0,
            "conflict_type": None,
        }
    if entity is None:
        return {
            "validated_anchor_id": None,
            "anchor_kind": "missing_target",
            "edge_type": None,
            "target_entity_type": None,
            "target_entity_status": None,
            "validation_status": "rejected",
            "reason_code": "canonical_place_entity_missing",
            "confidence": 1.0,
            "conflict_type": "invalid_canonical_place_target",
        }

    effective_type = str(entity["semantic_entity_type"] or entity["source_entity_type"])
    entity_status = str(entity["semantic_status"])
    entity_name = normalize_label(entity["canonical_name"])
    exact_name = bool(raw and entity_name and raw == entity_name)
    atomic_name = not any(separator in entity_name for separator in COMPOUND_SEPARATORS)

    if entity_status in PENDING_ENTITY_STATUSES:
        return {
            "validated_anchor_id": None,
            "anchor_kind": "pending_entity_type",
            "edge_type": None,
            "target_entity_type": effective_type,
            "target_entity_status": entity_status,
            "validation_status": "model_review",
            "reason_code": "canonical_place_entity_type_unresolved",
            "confidence": None,
            "conflict_type": "unresolved_canonical_place_target",
        }
    if effective_type in SPATIAL_TYPES:
        return {
            "validated_anchor_id": source_id,
            "anchor_kind": "spatial_entity",
            "edge_type": "AT_PLACE",
            "target_entity_type": effective_type,
            "target_entity_status": entity_status,
            "validation_status": "accepted",
            "reason_code": "accepted_spatial_entity_type",
            "confidence": 0.99,
            "conflict_type": None,
        }
    if effective_type == "Institution" and exact_name and atomic_name:
        return {
            "validated_anchor_id": source_id,
            "anchor_kind": "named_site",
            "edge_type": "AT_NAMED_SITE",
            "target_entity_type": effective_type,
            "target_entity_status": entity_status,
            "validation_status": "qualified",
            "reason_code": "institution_used_as_named_site",
            "confidence": 0.90,
            "conflict_type": None,
        }
    if (
        effective_type == "Artifact"
        and exact_name
        and atomic_name
        and entity_name.endswith(ARTIFACT_SITE_SUFFIXES)
    ):
        return {
            "validated_anchor_id": source_id,
            "anchor_kind": "named_cultural_object_site",
            "edge_type": "AT_NAMED_SITE",
            "target_entity_type": effective_type,
            "target_entity_status": entity_status,
            "validation_status": "qualified",
            "reason_code": "fixed_memorial_artifact_used_as_named_site",
            "confidence": 0.85,
            "conflict_type": None,
        }
    return {
        "validated_anchor_id": None,
        "anchor_kind": "invalid_nonspatial",
        "edge_type": None,
        "target_entity_type": effective_type,
        "target_entity_status": entity_status,
        "validation_status": "rejected",
        "reason_code": "canonical_place_points_to_nonspatial_entity",
        "confidence": 1.0,
        "conflict_type": "invalid_canonical_place_target",
    }


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        create table if not exists v2_assertion_spatial_anchors(
          fact_id text primary key references v2_assertion_scopes(fact_id),
          source_canonical_place_id text,
          validated_anchor_id text references v2_entities(entity_id),
          anchor_kind text not null check(anchor_kind in (
            'none','raw_only','missing_target','pending_entity_type','spatial_entity',
            'named_site','named_cultural_object_site','invalid_nonspatial'
          )),
          edge_type text check(edge_type is null or edge_type in ('AT_PLACE','AT_NAMED_SITE')),
          target_entity_type text,
          target_entity_status text,
          validation_status text not null check(validation_status in (
            'not_applicable','accepted','qualified','model_review','rejected'
          )),
          reason_code text not null,
          confidence real check(confidence is null or confidence between 0 and 1),
          rule_version text not null,
          updated_at text not null
        ) without rowid;
        create index if not exists idx_v2_spatial_anchor_validated
          on v2_assertion_spatial_anchors(validated_anchor_id,edge_type);
        create index if not exists idx_v2_spatial_anchor_status
          on v2_assertion_spatial_anchors(validation_status,anchor_kind);
        create index if not exists idx_v2_spatial_anchor_source
          on v2_assertion_spatial_anchors(source_canonical_place_id,anchor_kind);
        """
    )


def run(database: Path, report_path: Path, apply: bool) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        entities = {
            str(row["entity_id"]): row
            for row in con.execute(
                "select entity_id,canonical_name,source_entity_type,semantic_entity_type,"
                "semantic_status from v2_entities"
            )
        }
        rows = con.execute(
            "select fact_id,place_raw,canonical_place_id from v2_assertion_scopes "
            "order by fact_id"
        ).fetchall()
        decisions = []
        for row in rows:
            decision = classify_anchor(
                row["place_raw"], row["canonical_place_id"],
                entities.get(str(row["canonical_place_id"] or "")),
            )
            decisions.append((row, decision))

        by_kind = Counter(str(decision["anchor_kind"]) for _, decision in decisions)
        by_status = Counter(str(decision["validation_status"]) for _, decision in decisions)
        by_target_type = Counter(
            str(decision["target_entity_type"])
            for _, decision in decisions if decision["target_entity_type"]
        )
        changed_rows = 0
        inserted_conflicts = 0
        resolved_stale_conflicts = 0
        if apply:
            con.execute("begin immediate")
            ensure_schema(con)
            existing = {
                str(row["fact_id"]): tuple(row)
                for row in con.execute(
                    "select fact_id,source_canonical_place_id,validated_anchor_id,anchor_kind,"
                    "edge_type,target_entity_type,target_entity_status,validation_status,"
                    "reason_code,confidence,rule_version from v2_assertion_spatial_anchors"
                )
            }
            active_conflict_ids = set()
            for row, decision in decisions:
                values = (
                    str(row["fact_id"]), row["canonical_place_id"],
                    decision["validated_anchor_id"], decision["anchor_kind"],
                    decision["edge_type"], decision["target_entity_type"],
                    decision["target_entity_status"], decision["validation_status"],
                    decision["reason_code"], decision["confidence"], RULE_VERSION,
                )
                if existing.get(str(row["fact_id"])) != values:
                    con.execute(
                        "insert into v2_assertion_spatial_anchors values(?,?,?,?,?,?,?,?,?,?,?,?) "
                        "on conflict(fact_id) do update set "
                        "source_canonical_place_id=excluded.source_canonical_place_id,"
                        "validated_anchor_id=excluded.validated_anchor_id,"
                        "anchor_kind=excluded.anchor_kind,edge_type=excluded.edge_type,"
                        "target_entity_type=excluded.target_entity_type,"
                        "target_entity_status=excluded.target_entity_status,"
                        "validation_status=excluded.validation_status,"
                        "reason_code=excluded.reason_code,confidence=excluded.confidence,"
                        "rule_version=excluded.rule_version,updated_at=excluded.updated_at",
                        (*values, now),
                    )
                    changed_rows += 1
                if decision["conflict_type"]:
                    conflict_id = stable_id(
                        "V2CONFLICT", row["fact_id"], decision["conflict_type"], RULE_VERSION
                    )
                    active_conflict_ids.add(conflict_id)
                    cursor = con.execute(
                        "insert or ignore into v2_semantic_conflicts values(?,?,?,?,?,?,?,?,?,?)",
                        (
                            conflict_id, "assertion", row["fact_id"],
                            decision["conflict_type"], "error",
                            json.dumps({
                                "source_canonical_place_id": row["canonical_place_id"],
                                "place_raw": row["place_raw"],
                                "target_entity_type": decision["target_entity_type"],
                                "target_entity_status": decision["target_entity_status"],
                                "reason_code": decision["reason_code"],
                                "rule_version": RULE_VERSION,
                            }, ensure_ascii=False, sort_keys=True),
                            "open", None, now, None,
                        ),
                    )
                    inserted_conflicts += cursor.rowcount
            stale_rows = con.execute(
                "select conflict_id from v2_semantic_conflicts where unit_kind='assertion' "
                "and conflict_type in ('invalid_canonical_place_target',"
                "'unresolved_canonical_place_target') and status='open'"
            ).fetchall()
            stale_ids = [str(row[0]) for row in stale_rows if str(row[0]) not in active_conflict_ids]
            for conflict_id in stale_ids:
                con.execute(
                    "update v2_semantic_conflicts set status='resolved',resolved_at=? "
                    "where conflict_id=?", (now, conflict_id)
                )
            resolved_stale_conflicts = len(stale_ids)
            valid_fact_ids = {str(row["fact_id"]) for row in rows}
            stale_anchor_ids = set(existing) - valid_fact_ids
            for fact_id in stale_anchor_ids:
                con.execute("delete from v2_assertion_spatial_anchors where fact_id=?", (fact_id,))
            changed_rows += len(stale_anchor_ids)
            con.commit()

        table_exists = bool(con.execute(
            "select 1 from sqlite_master where type='table' "
            "and name='v2_assertion_spatial_anchors'"
        ).fetchone())
        materialized_count = con.execute(
            "select count(*) from v2_assertion_spatial_anchors"
        ).fetchone()[0] if table_exists else 0
        report = {
            "result": "PASS",
            "apply": apply,
            "rule_version": RULE_VERSION,
            "assertion_count": len(rows),
            "materialized_count": materialized_count,
            "changed_rows": changed_rows,
            "inserted_conflicts": inserted_conflicts,
            "resolved_stale_conflicts": resolved_stale_conflicts,
            "by_anchor_kind": dict(sorted(by_kind.items())),
            "by_validation_status": dict(sorted(by_status.items())),
            "by_target_entity_type": dict(sorted(by_target_type.items())),
            "validated_at_place": sum(
                1 for _, decision in decisions if decision["edge_type"] == "AT_PLACE"
            ),
            "validated_at_named_site": sum(
                1 for _, decision in decisions if decision["edge_type"] == "AT_NAMED_SITE"
            ),
            "open_spatial_conflicts": con.execute(
                "select count(*) from v2_semantic_conflicts where unit_kind='assertion' "
                "and conflict_type in ('invalid_canonical_place_target',"
                "'unresolved_canonical_place_target') and status='open'"
            ).fetchone()[0],
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
