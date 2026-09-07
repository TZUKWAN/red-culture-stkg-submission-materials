"""Build a conservative canonical identity map and close V2 spatial conflicts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from stkg_v2_semantics import classify_space_scope


DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
SPATIAL_DATABASE = ROOT / "derived" / "red_culture_stkg_spatial_v1.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_canonical_identity_spatial_closure.json"
METHOD_VERSION = "stkg-v2-canonical-identity-spatial-closure-1"
SPATIAL_TYPES = {"Place", "AdministrativeRegion"}
NAMED_SITE_SUFFIXES = (
    "大学", "学院", "学校", "中学", "小学", "师范", "女中", "书院",
    "图书馆", "博物馆", "纪念馆", "医院", "书店", "工厂", "厂", "矿",
    "监狱", "会址", "旧址", "故居", "遗址", "陵园",
)
FIXED_ARTIFACT_SUFFIXES = ("纪念碑", "纪念塔", "墓碑", "雕像")
COMPOUND_SEPARATORS = ("/", "／", ",", "，", ";", "；", ":", "：", "、")
REGION_SUFFIXES = (
    "壮族自治区", "回族自治区", "维吾尔自治区", "自治区",
    "特别行政区", "自治州", "地区", "省", "市", "县",
)


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_label(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", "", text)


def short_region_label(value: object) -> str:
    text = normalize_label(value)
    for suffix in REGION_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(
        con.execute(
            "select 1 from sqlite_master where type='table' and name=?", (name,)
        ).fetchone()
    )


def source_spatial_digest(con: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for row in con.execute(
        "select fact_id,place_raw,canonical_place_id from v2_assertion_scopes order by fact_id"
    ):
        digest.update("\x1f".join(str(value or "") for value in row).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def aliases_digest(con: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for row in con.execute("select entity_id,aliases_json from v2_entities order by entity_id"):
        digest.update(f"{row[0]}\x1f{row[1]}\n".encode("utf-8"))
    return digest.hexdigest()


def authority_labels(spatial_database: Path) -> dict[str, dict]:
    con = sqlite3.connect(f"file:{spatial_database.resolve().as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        regions: dict[str, dict] = {}
        for row in con.execute("select region_id,province_name from stkg_study_regions"):
            value = {
                "authority_kind": "study_region",
                "authority_id": str(row["region_id"]),
                "authority_name": str(row["province_name"]),
            }
            for label in {
                normalize_label(row["province_name"]),
                short_region_label(row["province_name"]),
            }:
                regions[label] = value
        admin: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for row in con.execute(
            "select unit_name,parent_region_id from stkg_administrative_units"
        ):
            value = (str(row["parent_region_id"]), normalize_label(row["unit_name"]))
            for label in {
                normalize_label(row["unit_name"]),
                short_region_label(row["unit_name"]),
            }:
                admin[label].add(value)
        result = dict(regions)
        for label, values in admin.items():
            if label in result or len(values) != 1:
                continue
            parent_region_id, unit_name = next(iter(values))
            result[label] = {
                "authority_kind": "administrative_unit",
                "authority_id": f"{parent_region_id}:{unit_name}",
                "authority_name": unit_name,
            }
        return result
    finally:
        con.close()


def effective_type(row: sqlite3.Row) -> str:
    return str(row["semantic_entity_type"] or row["source_entity_type"])


def representative(
    rows: list[sqlite3.Row],
    references: Counter,
    prefer_administrative: bool,
) -> sqlite3.Row:
    def key(row: sqlite3.Row) -> tuple:
        entity_id = str(row["entity_id"])
        entity_type = effective_type(row)
        return (
            0 if prefer_administrative and entity_type == "AdministrativeRegion" else 1,
            -int(row["member_count"] or 0),
            0 if entity_id.startswith("IENT-") else 1,
            -int(references[entity_id]),
            entity_id,
        )

    return sorted(rows, key=key)[0]


def build_identity_plan(
    con: sqlite3.Connection, authorities: dict[str, dict]
) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    entities = con.execute("select * from v2_entities order by entity_id").fetchall()
    references = Counter(
        str(row[0])
        for row in con.execute(
            "select canonical_place_id from v2_assertion_scopes "
            "where canonical_place_id is not null"
        )
    )
    spatial_by_name: dict[str, list[sqlite3.Row]] = defaultdict(list)
    sites_by_name: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in entities:
        if str(row["semantic_status"]) != "auto_accepted":
            continue
        name = normalize_label(row["canonical_name"])
        entity_type = effective_type(row)
        if entity_type in SPATIAL_TYPES:
            spatial_by_name[name].append(row)
        if (
            len(name) >= 4
            and not any(separator in name for separator in COMPOUND_SEPARATORS)
            and (
                (entity_type in {"Institution", "CulturalSite"} and name.endswith(NAMED_SITE_SUFFIXES))
                or (entity_type == "Artifact" and name.endswith(FIXED_ARTIFACT_SUFFIXES))
            )
        ):
            sites_by_name[name].append(row)

    admin_targets: dict[str, dict] = {}
    site_targets: dict[str, dict] = {}
    overrides: dict[str, dict] = {}
    for name, authority in authorities.items():
        rows = spatial_by_name.get(name, [])
        if not rows:
            continue
        target = representative(rows, references, prefer_administrative=True)
        canonical_type = effective_type(target)
        admin_targets[name] = {
            "row": target,
            "canonical_type": canonical_type,
            **authority,
        }
        for row in rows:
            if str(row["entity_id"]) != str(target["entity_id"]):
                overrides[str(row["entity_id"])] = {
                    "target": target,
                    "canonical_type": canonical_type,
                    "reason": "authoritative_administrative_exact_name",
                    "authority": authority,
                }

    for name, rows in sites_by_name.items():
        target = representative(rows, references, prefer_administrative=False)
        canonical_type = effective_type(target)
        site_targets[name] = {
            "row": target,
            "canonical_type": canonical_type,
            "authority_kind": "strict_named_site",
            "authority_id": name,
            "authority_name": str(target["canonical_name"]),
        }
        for row in rows:
            if str(row["entity_id"]) != str(target["entity_id"]):
                overrides[str(row["entity_id"])] = {
                    "target": target,
                    "canonical_type": canonical_type,
                    "reason": "strict_named_site_exact_name",
                    "authority": site_targets[name],
                }

    identity_map: dict[str, dict] = {}
    for row in entities:
        source_id = str(row["entity_id"])
        override = overrides.get(source_id)
        if override:
            target = override["target"]
            identity_map[source_id] = {
                "canonical_entity_id": str(target["entity_id"]),
                "canonical_name": str(target["canonical_name"]),
                "canonical_entity_type": override["canonical_type"],
                "mapping_status": "canonicalized",
                "mapping_reason": override["reason"],
                "confidence": 0.99,
                "authority_kind": override["authority"]["authority_kind"],
                "authority_id": override["authority"]["authority_id"],
            }
        else:
            identity_map[source_id] = {
                "canonical_entity_id": source_id,
                "canonical_name": str(row["canonical_name"]),
                "canonical_entity_type": effective_type(row),
                "mapping_status": "self",
                "mapping_reason": "no_safe_identity_merge",
                "confidence": 1.0,
                "authority_kind": None,
                "authority_id": None,
            }
    return identity_map, admin_targets, site_targets


def spatial_conflict_plan(
    con: sqlite3.Connection,
    admin_targets: dict[str, dict],
    site_targets: dict[str, dict],
) -> list[dict]:
    rows = con.execute(
        "select c.conflict_id,c.conflict_type,c.unit_id fact_id,a.*,s.place_raw "
        "from v2_semantic_conflicts c join v2_assertion_spatial_anchors a "
        "on a.fact_id=c.unit_id join v2_assertion_scopes s on s.fact_id=c.unit_id "
        "where c.unit_kind='assertion' and c.status='open' and c.conflict_type in "
        "('invalid_canonical_place_target','unresolved_canonical_place_target') "
        "order by c.conflict_id"
    ).fetchall()
    plan = []
    for row in rows:
        label = normalize_label(row["place_raw"])
        target = admin_targets.get(label) or site_targets.get(label)
        if target:
            entity_type = target["canonical_type"]
            if entity_type in {"Place", "AdministrativeRegion", "CulturalSite"}:
                anchor_kind, edge_type = "spatial_entity", "AT_PLACE"
            elif entity_type == "Artifact":
                anchor_kind, edge_type = "named_cultural_object_site", "AT_NAMED_SITE"
            else:
                anchor_kind, edge_type = "named_site", "AT_NAMED_SITE"
            outcome = "resolved_canonical"
        elif str(row["conflict_type"]) == "invalid_canonical_place_target":
            anchor_kind, edge_type, outcome = "invalid_nonspatial", None, "excluded_invalid_target"
        else:
            anchor_kind, edge_type, outcome = str(row["anchor_kind"]), None, "accepted_raw_only"
        plan.append(
            {
                "row": row,
                "target": target,
                "anchor_kind": anchor_kind,
                "edge_type": edge_type,
                "outcome": outcome,
            }
        )
    return plan


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        create table if not exists v2_entity_identity_map(
          source_entity_id text primary key references v2_entities(entity_id),
          canonical_entity_id text not null references v2_entities(entity_id),
          canonical_name text not null,
          canonical_entity_type text not null,
          mapping_status text not null check(mapping_status in ('self','canonicalized')),
          mapping_reason text not null,
          confidence real not null check(confidence between 0 and 1),
          authority_kind text,
          authority_id text,
          method_version text not null,
          created_at text not null
        );
        create index if not exists idx_v2_identity_map_canonical
          on v2_entity_identity_map(canonical_entity_id,mapping_status);
        create table if not exists v2_spatial_conflict_closures(
          conflict_id text primary key references v2_semantic_conflicts(conflict_id),
          fact_id text not null references v2_assertion_scopes(fact_id),
          outcome text not null check(outcome in (
            'resolved_canonical','accepted_raw_only','excluded_invalid_target'
          )),
          validated_anchor_id text references v2_entities(entity_id),
          place_raw text,
          reason text not null,
          method_version text not null,
          closed_at text not null
        );
        drop view if exists v2_spatial_projection;
        create view v2_spatial_projection as
        select a.fact_id,a.source_canonical_place_id,
               coalesce(m.canonical_entity_id,a.validated_anchor_id) canonical_anchor_id,
               a.anchor_kind,a.edge_type,a.validation_status,a.reason_code,a.confidence,
               s.place_raw,s.space_role,s.space_owner_id,
               c.outcome closure_outcome
        from v2_assertion_spatial_anchors a
        join v2_assertion_scopes s on s.fact_id=a.fact_id
        left join v2_entity_identity_map m on m.source_entity_id=a.validated_anchor_id
        left join v2_spatial_conflict_closures c on c.fact_id=a.fact_id;
        """
    )


def recompute_space_scope(
    con: sqlite3.Connection, fact_id: str, canonical_anchor_id: str
) -> tuple[str, str | None]:
    row = con.execute(
        "select a.predicate,a.subject_id,a.object_id,"
        "coalesce(s.semantic_entity_type,s.source_entity_type) subject_type,"
        "coalesce(o.semantic_entity_type,o.source_entity_type) object_type "
        "from v2_assertion_scopes a join v2_entities s on s.entity_id=a.subject_id "
        "join v2_entities o on o.entity_id=a.object_id where a.fact_id=?",
        (fact_id,),
    ).fetchone()
    label = classify_space_scope(
        str(row["predicate"]),
        canonical_anchor_id,
        str(row["subject_id"]),
        str(row["subject_type"]),
        str(row["object_id"]),
        str(row["object_type"]),
    )
    return label.role, label.owner_id


def apply_plan(
    con: sqlite3.Connection,
    identity_map: dict[str, dict],
    spatial_plan: list[dict],
    now: str,
) -> dict:
    ensure_schema(con)
    for source_id, item in identity_map.items():
        con.execute(
            "insert into v2_entity_identity_map values(?,?,?,?,?,?,?,?,?,?,?)",
            (
                source_id,
                item["canonical_entity_id"],
                item["canonical_name"],
                item["canonical_entity_type"],
                item["mapping_status"],
                item["mapping_reason"],
                item["confidence"],
                item["authority_kind"],
                item["authority_id"],
                METHOD_VERSION,
                now,
            ),
        )
    redirected_existing_anchors = con.execute(
        "update v2_assertion_spatial_anchors set validated_anchor_id=("
        "select canonical_entity_id from v2_entity_identity_map m "
        "where m.source_entity_id=v2_assertion_spatial_anchors.validated_anchor_id),"
        "rule_version=?,updated_at=? where validated_anchor_id in ("
        "select source_entity_id from v2_entity_identity_map "
        "where mapping_status='canonicalized')",
        (METHOD_VERSION, now),
    ).rowcount
    mapped = raw_only = invalid = 0
    for item in spatial_plan:
        row = item["row"]
        conflict_id = str(row["conflict_id"])
        fact_id = str(row["fact_id"])
        target = item["target"]
        if target:
            target_row = target["row"]
            target_id = str(target_row["entity_id"])
            con.execute(
                "update v2_assertion_spatial_anchors set validated_anchor_id=?,"
                "anchor_kind=?,edge_type=?,target_entity_type=?,target_entity_status='auto_accepted',"
                "validation_status=?,reason_code=?,confidence=?,rule_version=?,updated_at=? "
                "where fact_id=?",
                (
                    target_id,
                    item["anchor_kind"],
                    item["edge_type"],
                    target["canonical_type"],
                    "accepted" if item["edge_type"] == "AT_PLACE" else "qualified",
                    "authority_exact_place_match" if item["edge_type"] == "AT_PLACE" else "strict_exact_named_site_match",
                    0.99 if item["edge_type"] == "AT_PLACE" else 0.95,
                    METHOD_VERSION,
                    now,
                    fact_id,
                ),
            )
            role, owner = recompute_space_scope(con, fact_id, target_id)
            con.execute(
                "update v2_assertion_scopes set space_role=?,space_owner_id=?,updated_at=? "
                "where fact_id=?",
                (role, owner, now, fact_id),
            )
            conflict_status = "resolved"
            reason = "exact_authority_or_named_site_match"
            mapped += 1
        elif item["outcome"] == "excluded_invalid_target":
            target_id = None
            con.execute(
                "update v2_assertion_scopes set space_role='unknown',space_owner_id=null,"
                "updated_at=? where fact_id=?",
                (now, fact_id),
            )
            conflict_status = "excluded"
            reason = "nonspatial_target_rejected_raw_text_preserved"
            invalid += 1
        else:
            target_id = None
            conflict_status = "accepted_unknown"
            reason = "raw_place_preserved_without_safe_canonical_match"
            raw_only += 1
        resolution_id = stable_id("V2SPACECLOSE", conflict_id, METHOD_VERSION)
        con.execute(
            "insert into v2_spatial_conflict_closures values(?,?,?,?,?,?,?,?)",
            (
                conflict_id,
                fact_id,
                item["outcome"],
                target_id,
                row["place_raw"],
                reason,
                METHOD_VERSION,
                now,
            ),
        )
        con.execute(
            "update v2_semantic_conflicts set status=?,resolution_decision_id=?,resolved_at=? "
            "where conflict_id=? and status='open'",
            (conflict_status, resolution_id, now, conflict_id),
        )
    return {
        "identity_rows": len(identity_map),
        "canonicalized_entities": sum(
            item["mapping_status"] == "canonicalized" for item in identity_map.values()
        ),
        "redirected_existing_spatial_anchors": redirected_existing_anchors,
        "new_canonical_spatial_matches": mapped,
        "accepted_raw_only": raw_only,
        "excluded_invalid_targets": invalid,
    }


def validate(
    con: sqlite3.Connection,
    expected_entities: int,
    expected_conflicts: int,
    expected_source_digest: str,
    expected_alias_digest: str,
) -> dict:
    quick_check = str(con.execute("pragma quick_check").fetchone()[0])
    foreign_key_errors = len(con.execute("pragma foreign_key_check").fetchall())
    map_rows = int(con.execute("select count(*) from v2_entity_identity_map").fetchone()[0])
    closure_rows = int(con.execute("select count(*) from v2_spatial_conflict_closures").fetchone()[0])
    open_conflicts = int(
        con.execute(
            "select count(*) from v2_semantic_conflicts where status='open' and conflict_type in "
            "('invalid_canonical_place_target','unresolved_canonical_place_target')"
        ).fetchone()[0]
    )
    chain_errors = int(
        con.execute(
            "select count(*) from v2_entity_identity_map a join v2_entity_identity_map b "
            "on b.source_entity_id=a.canonical_entity_id "
            "where b.canonical_entity_id<>b.source_entity_id"
        ).fetchone()[0]
    )
    person_redirects = int(
        con.execute(
            "select count(*) from v2_entity_identity_map m join v2_entities e "
            "on e.entity_id=m.source_entity_id where m.mapping_status='canonicalized' "
            "and coalesce(e.semantic_entity_type,e.source_entity_type)='Person'"
        ).fetchone()[0]
    )
    invalid_edges = int(
        con.execute(
            "select count(*) from v2_spatial_conflict_closures c "
            "join v2_assertion_spatial_anchors a on a.fact_id=c.fact_id "
            "where c.outcome='excluded_invalid_target' and a.validated_anchor_id is not null"
        ).fetchone()[0]
    )
    anchor_count_mismatch = int(
        con.execute("select count(*) from v2_assertion_scopes").fetchone()[0]
    ) - int(con.execute("select count(*) from v2_assertion_spatial_anchors").fetchone()[0])
    source_preserved = source_spatial_digest(con) == expected_source_digest
    aliases_preserved = aliases_digest(con) == expected_alias_digest
    passed = all(
        (
            quick_check == "ok",
            foreign_key_errors == 0,
            map_rows == expected_entities,
            closure_rows == expected_conflicts,
            open_conflicts == 0,
            chain_errors == 0,
            person_redirects == 0,
            invalid_edges == 0,
            anchor_count_mismatch == 0,
            source_preserved,
            aliases_preserved,
        )
    )
    return {
        "quick_check": quick_check,
        "foreign_key_errors": foreign_key_errors,
        "identity_map_rows": map_rows,
        "expected_identity_map_rows": expected_entities,
        "spatial_closure_rows": closure_rows,
        "expected_spatial_closure_rows": expected_conflicts,
        "open_spatial_conflicts": open_conflicts,
        "identity_chain_errors": chain_errors,
        "person_redirects": person_redirects,
        "invalid_targets_with_edges": invalid_edges,
        "assertion_anchor_count_delta": anchor_count_mismatch,
        "source_spatial_fields_preserved": source_preserved,
        "aliases_preserved": aliases_preserved,
        "pass": passed,
    }


def run(
    database: Path,
    spatial_database: Path,
    report: Path,
    apply: bool,
) -> dict:
    database = database.resolve()
    report = report.resolve()
    before_hash = sha256(database)
    authorities = authority_labels(spatial_database)
    source = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    already_applied = (
        table_exists(source, "v2_entity_identity_map")
        and int(source.execute("select count(*) from v2_entity_identity_map").fetchone()[0])
        == int(source.execute("select count(*) from v2_entities").fetchone()[0])
        and int(
            source.execute(
                "select count(*) from v2_semantic_conflicts where status='open' "
                "and conflict_type in ('invalid_canonical_place_target',"
                "'unresolved_canonical_place_target')"
            ).fetchone()[0]
        ) == 0
    )
    if already_applied:
        payload = {
            "status": "DRY_RUN" if not apply else "PASS",
            "database": str(database),
            "method_version": METHOD_VERSION,
            "before_sha256": before_hash,
            "already_applied": True,
            "canonicalized_entity_count": 0,
            "spatial_conflict_count": 0,
        }
        source.close()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
    identity_map, admin_targets, site_targets = build_identity_plan(source, authorities)
    spatial_plan = spatial_conflict_plan(source, admin_targets, site_targets)
    source_digest = source_spatial_digest(source)
    alias_hash = aliases_digest(source)
    entity_count = int(source.execute("select count(*) from v2_entities").fetchone()[0])
    source.close()
    payload = {
        "status": "DRY_RUN" if not apply else "PENDING",
        "database": str(database),
        "method_version": METHOD_VERSION,
        "before_sha256": before_hash,
        "already_applied": False,
        "authority_label_count": len(authorities),
        "canonicalized_entity_count": sum(
            item["mapping_status"] == "canonicalized" for item in identity_map.values()
        ),
        "spatial_conflict_count": len(spatial_plan),
        "spatial_outcomes": dict(sorted(Counter(item["outcome"] for item in spatial_plan).items())),
        "safety_policy": "authority_exact_admin_or_strict_exact_named_site;no_person_name_merge",
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    if not apply:
        report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    temporary = database.with_name(f".{database.name}.identity-space-closure.tmp")
    temporary.unlink(missing_ok=True)
    shutil.copy2(database, temporary)
    con = sqlite3.connect(temporary, timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        now = datetime.now().isoformat(timespec="seconds")
        con.execute("begin immediate")
        changes = apply_plan(con, identity_map, spatial_plan, now)
        con.commit()
        validation = validate(
            con, entity_count, len(spatial_plan), source_digest, alias_hash
        )
        if not validation["pass"]:
            raise RuntimeError("canonical identity and spatial closure validation failed")
    except Exception:
        con.rollback()
        con.close()
        temporary.unlink(missing_ok=True)
        raise
    con.close()
    if sha256(database) != before_hash:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("V2 database changed before atomic replacement")
    os.replace(temporary, database)
    payload.update(
        {
            "status": "PASS",
            "changes": changes,
            "validation": validation,
            "after_sha256": sha256(database),
            "completed_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DATABASE)
    parser.add_argument("--spatial-db", type=Path, default=SPATIAL_DATABASE)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.db, args.spatial_db, args.report, args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
