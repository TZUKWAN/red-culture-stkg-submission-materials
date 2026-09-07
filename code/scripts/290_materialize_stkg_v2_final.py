"""Materialize the final V2 research SQLite database with audited media metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "derived" / "red_culture_stkg_evolution_v2.sqlite"
MEDIA = ROOT / "derived" / "stkg_v2_creative_media_enrichment.sqlite"
MEDIA_REPORT = ROOT / "audit_reports" / "stkg_v2_creative_media.json"
OUTPUT = ROOT / "derived" / "red_culture_stkg_final_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_final_materialization.json"
BUILD_VERSION = "red-culture-stkg-final-v2-1"


SCHEMA = """
create table research_creative_media_types(
  media_type text primary key
) without rowid;

create table research_creative_work_media(
  entity_id text primary key references research_entities(entity_id),
  canonical_name text not null,
  media_type text not null references research_creative_media_types(media_type),
  classification_method text not null,
  task_status text not null check(task_status in ('completed','unknown')),
  confidence real not null check(confidence between 0 and 1),
  attempts integer not null check(attempts between 0 and 30),
  model text,
  prompt_version text,
  reason_code text not null,
  explanation text not null,
  source_members_json text not null check(json_valid(source_members_json)),
  source_media_json text not null check(json_valid(source_media_json)),
  context_json text not null check(json_valid(context_json)),
  raw_response text,
  updated_at text not null
) without rowid;

create table research_culture_state_value_facets(
  state_id text not null references research_culture_states(state_id),
  value_facet_id text not null references research_entities(entity_id),
  value_facet_name text not null,
  spirit_id text not null references research_entities(entity_id),
  spirit_name text not null,
  state_spirit_fact_id text not null references research_assertions(fact_id),
  spirit_value_fact_id text not null references research_assertions(fact_id),
  derivation_status text not null check(derivation_status='explicit_spirit_value_projection'),
  primary key(state_id,value_facet_id,spirit_id,state_spirit_fact_id,spirit_value_fact_id)
) without rowid;

create index idx_research_creative_media_type
  on research_creative_work_media(media_type,entity_id);
create index idx_research_creative_media_method
  on research_creative_work_media(classification_method,task_status);
create index idx_research_state_value_facet
  on research_culture_state_value_facets(value_facet_id,state_id);

create view v_research_creative_work_media as
select e.entity_id,e.canonical_name,e.aliases_json,m.media_type,m.classification_method,
       m.task_status,m.confidence,m.model,m.prompt_version,m.reason_code,m.explanation
from research_entities e join research_creative_work_media m using(entity_id)
where e.entity_type='CreativeWork';
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_media_rows(path: Path) -> tuple[list[str], list[tuple]]:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "select entity_id,canonical_name,media_type,classification_method,task_status,"
            "confidence,attempts,model,prompt_version,reason_code,explanation,source_members_json,"
            "source_media_json,context_json,raw_response,updated_at "
            "from v_creative_media_final order by entity_id"
        ).fetchall()
        media_types = sorted({str(row["media_type"]) for row in rows})
        return media_types, [tuple(row) for row in rows]
    finally:
        con.close()


def validate(con: sqlite3.Connection, expected_media_rows: int) -> tuple[dict, list[str]]:
    checks = {
        "quick_check": con.execute("pragma quick_check").fetchone()[0],
        "foreign_key_errors": len(con.execute("pragma foreign_key_check").fetchall()),
        "creative_work_count": con.execute(
            "select count(*) from research_entities where entity_type='CreativeWork'"
        ).fetchone()[0],
        "media_row_count": con.execute(
            "select count(*) from research_creative_work_media"
        ).fetchone()[0],
        "creative_works_without_media": con.execute(
            "select count(*) from research_entities e where e.entity_type='CreativeWork' and not exists("
            "select 1 from research_creative_work_media m where m.entity_id=e.entity_id)"
        ).fetchone()[0],
        "media_on_non_creative_work": con.execute(
            "select count(*) from research_creative_work_media m join research_entities e using(entity_id) "
            "where e.entity_type<>'CreativeWork'"
        ).fetchone()[0],
        "blank_media": con.execute(
            "select count(*) from research_creative_work_media where trim(media_type)=''"
        ).fetchone()[0],
        "unknown_media": con.execute(
            "select count(*) from research_creative_work_media where media_type='未知'"
        ).fetchone()[0],
        "qwen_media": con.execute(
            "select count(*) from research_creative_work_media where "
            "classification_method='qwen_v2_semantic_classification'"
        ).fetchone()[0],
        "state_value_facet_rows": con.execute(
            "select count(*) from research_culture_state_value_facets"
        ).fetchone()[0],
        "state_value_facet_states": con.execute(
            "select count(distinct state_id) from research_culture_state_value_facets"
        ).fetchone()[0],
        "state_value_facet_values": con.execute(
            "select count(distinct value_facet_id) from research_culture_state_value_facets"
        ).fetchone()[0],
        "invalid_state_value_types": con.execute(
            "select count(*) from research_culture_state_value_facets v "
            "join research_entities x on x.entity_id=v.value_facet_id "
            "join research_entities s on s.entity_id=v.spirit_id "
            "where x.entity_type<>'ValueFacet' or s.entity_type<>'Spirit'"
        ).fetchone()[0],
    }
    failures = []
    if checks["quick_check"] != "ok":
        failures.append(f"quick_check={checks['quick_check']}")
    if checks["foreign_key_errors"]:
        failures.append(f"foreign_key_errors={checks['foreign_key_errors']}")
    if checks["creative_work_count"] != expected_media_rows:
        failures.append(
            f"creative_work_count={checks['creative_work_count']} expected={expected_media_rows}"
        )
    if checks["media_row_count"] != expected_media_rows:
        failures.append(f"media_row_count={checks['media_row_count']} expected={expected_media_rows}")
    for key in (
        "creative_works_without_media", "media_on_non_creative_work", "blank_media",
        "invalid_state_value_types",
    ):
        if checks[key]:
            failures.append(f"{key}={checks[key]}")
    if checks["state_value_facet_rows"] == 0:
        failures.append("state_value_facet_rows=0")
    return checks, failures


def build(input_path: Path, media_path: Path, media_report_path: Path, output: Path, report_path: Path) -> dict:
    for path in (input_path, media_path, media_report_path):
        if not path.exists():
            raise FileNotFoundError(path)
    input_hash = sha256(input_path)
    media_hash = sha256(media_path)
    media_report = json.loads(media_report_path.read_text(encoding="utf-8"))
    if media_report.get("status") != "PASS":
        raise RuntimeError("creative media report is not PASS")
    if media_report.get("output", {}).get("sha256") != media_hash:
        raise RuntimeError("creative media database hash differs from its PASS report")
    media_types, media_rows = load_media_rows(media_path)
    temporary = output.with_name(f".{output.name}.tmp")
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(str(temporary) + suffix).unlink(missing_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(input_path, temporary)
    con = sqlite3.connect(temporary, timeout=120)
    con.execute("pragma foreign_keys=on")
    con.execute("pragma journal_mode=delete")
    con.execute("pragma synchronous=full")
    try:
        con.executescript(SCHEMA)
        con.execute("begin immediate")
        con.executemany(
            "insert into research_creative_media_types(media_type) values(?)",
            [(value,) for value in media_types],
        )
        con.executemany(
            "insert into research_creative_work_media values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            media_rows,
        )
        con.execute(
            """
            insert into research_culture_state_value_facets
            select m.state_id,l.value_facet_id,l.value_facet_name,m.semantic_entity_id,m.semantic_entity_name,
                   m.fact_id,l.fact_id,'explicit_spirit_value_projection'
            from research_culture_state_semantic_members m
            join research_spirit_value_links l on l.spirit_id=m.semantic_entity_id
            where m.semantic_entity_type='Spirit'
            """
        )
        con.execute(
            "insert or replace into research_build_metadata(key,value_json) values(?,?)",
            (
                "final_v2_materialization",
                json.dumps(
                    {
                        "build_version": BUILD_VERSION,
                        "media_database_sha256": media_hash,
                        "media_report_sha256": sha256(media_report_path),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        con.commit()
        checks, failures = validate(con, len(media_rows))
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    source_unchanged = sha256(input_path) == input_hash and sha256(media_path) == media_hash
    if not source_unchanged:
        failures.append("source database changed during materialization")
    if failures:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("final V2 materialization failed: " + "; ".join(failures))
    temporary.replace(output)
    report = {
        "status": "PASS",
        "build_version": BUILD_VERSION,
        "sources": {
            "evolution_v2": {"path": str(input_path.resolve()), "sha256": input_hash},
            "creative_media_v2": {"path": str(media_path.resolve()), "sha256": media_hash},
            "creative_media_report": {
                "path": str(media_report_path.resolve()), "sha256": sha256(media_report_path)
            },
            "unchanged": source_unchanged,
        },
        "output": {
            "path": str(output.resolve()), "size_bytes": output.stat().st_size,
            "sha256": sha256(output),
        },
        "checks": checks,
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    atomic_write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--media", type=Path, default=MEDIA)
    parser.add_argument("--media-report", type=Path, default=MEDIA_REPORT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    report = build(
        args.input.resolve(), args.media.resolve(), args.media_report.resolve(),
        args.output.resolve(), args.report.resolve(),
    )
    print(json.dumps(
        {"status": report["status"], "output": report["output"], "checks": report["checks"]},
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
