"""Close V2 event-time adjudication and block label-derived pseudo-dates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_event_time_semantic_closure.json"
METHOD_VERSION = "stkg-v2-event-time-semantic-closure-1"
TASK_TYPE = "event_occurrence_time_adjudication"
EXPLICIT_YEAR = re.compile(r"(?:[12][0-9]{3}|[一二三四五六七八九〇零]{4})年?")


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def time_value_digest(con: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for row in con.execute(
        "select fact_id,time_raw,time_start,time_end,time_precision "
        "from v2_assertion_scopes order by fact_id"
    ):
        digest.update("\x1f".join(str(value or "") for value in row).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def latest_decision(con: sqlite3.Connection, task_id: str) -> sqlite3.Row | None:
    return con.execute(
        "select decision_id,decision_json,confidence,model,prompt_version "
        "from v2_model_decisions where task_id=? and validator_pass=1 "
        "order by created_at desc,decision_id desc limit 1",
        (task_id,),
    ).fetchone()


def event_time_units(con: sqlite3.Connection) -> list[dict]:
    units = []
    for task in con.execute(
        "select * from v2_model_tasks where task_type=? order by task_id",
        (TASK_TYPE,),
    ):
        decision = latest_decision(con, str(task["task_id"]))
        if not decision:
            raise RuntimeError(f"event time task has no validated decision: {task['task_id']}")
        parsed = json.loads(decision["decision_json"])
        accepted = [str(value) for value in parsed.get("accepted_fact_ids", [])]
        rejected = [str(value) for value in parsed.get("rejected_fact_ids", [])]
        unknown = [str(value) for value in parsed.get("unknown_fact_ids", [])]
        expected = {
            str(item["fact_id"])
            for item in json.loads(task["payload_json"]).get("candidates", [])
        }
        groups = (set(accepted), set(rejected), set(unknown))
        if (
            set().union(*groups) != expected
            or sum(len(group) for group in groups) != len(expected)
        ):
            raise RuntimeError(f"invalid event time partition: {task['task_id']}")
        overrides = []
        for fact_id in accepted:
            assertion = con.execute(
                "select fact_id,time_raw,time_precision,time_role,time_owner_id "
                "from v2_assertion_scopes where fact_id=?",
                (fact_id,),
            ).fetchone()
            if (
                assertion
                and str(assertion["time_precision"]) == "period"
                and not EXPLICIT_YEAR.search(str(assertion["time_raw"] or ""))
            ):
                overrides.append(
                    {
                        "fact_id": fact_id,
                        "time_raw": assertion["time_raw"],
                        "prior_role": assertion["time_role"],
                        "reason": "label_derived_period_without_explicit_year",
                    }
                )
        overridden_ids = {item["fact_id"] for item in overrides}
        units.append(
            {
                "task": task,
                "decision": decision,
                "parsed": parsed,
                "accepted": accepted,
                "rejected": rejected,
                "unknown": unknown,
                "overrides": overrides,
                "effective_occurrence": sorted(set(accepted) - overridden_ids),
                "effective_context": sorted(set(rejected) | overridden_ids),
            }
        )
    return units


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        create table if not exists v2_event_time_closures(
          task_id text primary key references v2_model_tasks(task_id),
          event_id text not null references v2_entities(entity_id),
          model_decision_id text not null references v2_model_decisions(decision_id),
          adjudication_status text not null
            check(adjudication_status in ('completed','accepted_unknown')),
          original_partition_json text not null check(json_valid(original_partition_json)),
          effective_partition_json text not null check(json_valid(effective_partition_json)),
          confidence real not null check(confidence between 0 and 1),
          method_version text not null,
          closed_at text not null
        );
        create table if not exists v2_event_time_guard_overrides(
          fact_id text primary key references v2_assertion_scopes(fact_id),
          task_id text not null references v2_model_tasks(task_id),
          event_id text not null references v2_entities(entity_id),
          time_raw text,
          prior_role text not null,
          final_role text not null check(final_role='context_time'),
          reason text not null,
          method_version text not null,
          created_at text not null
        );
        drop view if exists v2_time_display;
        create view v2_time_display as
        select fact_id,time_raw,time_start,time_end,time_precision,time_role,time_owner_id,
               case
                 when time_start is null then null
                 when time_precision='year' then
                   cast(substr(time_start,1,4) as integer) || '年'
                 when time_precision='month' then
                   cast(substr(time_start,1,4) as integer) || '年' ||
                   cast(substr(time_start,6,2) as integer) || '月'
                 when time_precision='period'
                      and substr(time_start,6,5)='01-01'
                      and substr(time_end,6,5)='12-31' then
                   cast(substr(time_start,1,4) as integer) || '年-' ||
                   cast(substr(time_end,1,4) as integer) || '年'
                 when time_precision='period' then
                   cast(substr(time_start,1,4) as integer) || '年' ||
                   cast(substr(time_start,6,2) as integer) || '月-' ||
                   cast(substr(time_end,1,4) as integer) || '年' ||
                   cast(substr(time_end,6,2) as integer) || '月'
                 else cast(substr(time_start,1,4) as integer) || '年'
               end as normalized_time_label,
               semantic_status,confidence,risk_tier
        from v2_assertion_scopes;
        """
    )


def apply_units(con: sqlite3.Connection, units: list[dict], now: str) -> dict:
    ensure_schema(con)
    override_count = 0
    unknown_count = 0
    accepted_unknown_tasks = 0
    for unit in units:
        task = unit["task"]
        task_id = str(task["task_id"])
        event_id = str(task["unit_id"])
        closure_id = stable_id("V2TIMECLOSE", task_id, METHOD_VERSION)
        for override in unit["overrides"]:
            con.execute(
                "insert into v2_event_time_guard_overrides values(?,?,?,?,?,?,?,?,?)",
                (
                    override["fact_id"],
                    task_id,
                    event_id,
                    override["time_raw"],
                    override["prior_role"],
                    "context_time",
                    override["reason"],
                    METHOD_VERSION,
                    now,
                ),
            )
            con.execute(
                "update v2_assertion_scopes set time_role='context_time',time_owner_id=null,"
                "decision_sources_json=json_insert(decision_sources_json,'$[#]',?),updated_at=? "
                "where fact_id=?",
                (f"deterministic_guard:{METHOD_VERSION}", now, override["fact_id"]),
            )
            override_count += 1
        for fact_id in unit["unknown"]:
            con.execute(
                "update v2_assertion_scopes set time_role='unknown',time_owner_id=null,"
                "semantic_status='manual_review',risk_tier='D',updated_at=? where fact_id=?",
                (now, fact_id),
            )
            unknown_count += 1
        closure_status = "accepted_unknown" if unit["unknown"] else "completed"
        accepted_unknown_tasks += int(closure_status == "accepted_unknown")
        con.execute(
            "insert into v2_event_time_closures values(?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                event_id,
                unit["decision"]["decision_id"],
                closure_status,
                json.dumps(
                    {
                        "accepted_fact_ids": unit["accepted"],
                        "rejected_fact_ids": unit["rejected"],
                        "unknown_fact_ids": unit["unknown"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "event_occurrence_fact_ids": unit["effective_occurrence"],
                        "context_time_fact_ids": unit["effective_context"],
                        "unknown_fact_ids": unit["unknown"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                float(unit["decision"]["confidence"] or 0.0),
                METHOD_VERSION,
                now,
            ),
        )
        if unit["unknown"]:
            con.execute(
                "update v2_semantic_conflicts set status='accepted_unknown',"
                "resolution_decision_id=?,resolved_at=? where unit_kind='entity' "
                "and unit_id=? and conflict_type in "
                "('controlled_event_time_year_conflict','raw_event_time_requires_review') "
                "and status='open'",
                (closure_id, now, event_id),
            )
    return {
        "closed_tasks": len(units),
        "accepted_unknown_tasks": accepted_unknown_tasks,
        "guard_overrides": override_count,
        "unknown_candidates_neutralized": unknown_count,
    }


def validate(
    con: sqlite3.Connection,
    units: list[dict],
    expected_time_digest: str,
) -> dict:
    quick_check = str(con.execute("pragma quick_check").fetchone()[0])
    foreign_key_errors = len(con.execute("pragma foreign_key_check").fetchall())
    nonterminal_tasks = int(
        con.execute(
            "select count(*) from v2_model_tasks where task_type=? "
            "and status in ('pending','processing','retryable_error')",
            (TASK_TYPE,),
        ).fetchone()[0]
    )
    closure_count = int(con.execute("select count(*) from v2_event_time_closures").fetchone()[0])
    open_time_conflicts = int(
        con.execute(
            "select count(*) from v2_semantic_conflicts where conflict_type in "
            "('controlled_event_time_year_conflict','raw_event_time_requires_review') "
            "and status='open'"
        ).fetchone()[0]
    )
    unsafe_occurrences = int(
        con.execute(
            "select count(*) from v2_assertion_scopes where time_role='event_occurrence' "
            "and time_precision='period' and fact_id in "
            "(select fact_id from v2_event_time_guard_overrides)"
        ).fetchone()[0]
    )
    unknown_role_errors = int(
        con.execute(
            "select count(*) from v2_event_time_closures c,json_each(c.effective_partition_json,'$.unknown_fact_ids') j "
            "join v2_assertion_scopes a on a.fact_id=j.value "
            "where a.time_role<>'unknown' or a.time_owner_id is not null "
            "or a.semantic_status<>'manual_review'"
        ).fetchone()[0]
    )
    display_format_errors = int(
        con.execute(
            "select count(*) from v2_time_display where time_start is not null "
            "and (normalized_time_label is null or normalized_time_label glob '*日*' "
            "or normalized_time_label glob '*〇*' or normalized_time_label glob '*一九*')"
        ).fetchone()[0]
    )
    time_values_preserved = time_value_digest(con) == expected_time_digest
    passed = all(
        (
            quick_check == "ok",
            foreign_key_errors == 0,
            nonterminal_tasks == 0,
            closure_count == len(units),
            open_time_conflicts == 0,
            unsafe_occurrences == 0,
            unknown_role_errors == 0,
            display_format_errors == 0,
            time_values_preserved,
        )
    )
    return {
        "quick_check": quick_check,
        "foreign_key_errors": foreign_key_errors,
        "nonterminal_event_time_tasks": nonterminal_tasks,
        "expected_closures": len(units),
        "verified_closures": closure_count,
        "open_event_time_conflicts": open_time_conflicts,
        "guarded_periods_still_marked_occurrence": unsafe_occurrences,
        "unknown_role_errors": unknown_role_errors,
        "display_format_errors": display_format_errors,
        "time_values_preserved": time_values_preserved,
        "pass": passed,
    }


def run(database: Path, report: Path, apply: bool) -> dict:
    database = database.resolve()
    report = report.resolve()
    before_hash = sha256(database)
    source = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    units = event_time_units(source)
    time_digest = time_value_digest(source)
    source.close()
    override_rows = [item for unit in units for item in unit["overrides"]]
    payload = {
        "status": "DRY_RUN" if not apply else "PENDING",
        "database": str(database),
        "method_version": METHOD_VERSION,
        "before_sha256": before_hash,
        "event_time_task_count": len(units),
        "manual_review_task_count": sum(bool(unit["unknown"]) for unit in units),
        "unknown_candidate_count": sum(len(unit["unknown"]) for unit in units),
        "guard_override_count": len(override_rows),
        "override_time_raw_counts": dict(
            sorted(Counter(str(item["time_raw"] or "") for item in override_rows).items())
        ),
        "guard_policy": "period_without_explicit_year_is_context_time",
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    if not apply:
        report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    temporary = database.with_name(f".{database.name}.event-time-closure.tmp")
    temporary.unlink(missing_ok=True)
    shutil.copy2(database, temporary)
    con = sqlite3.connect(temporary, timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        now = datetime.now().isoformat(timespec="seconds")
        con.execute("begin immediate")
        changes = apply_units(con, units, now)
        con.commit()
        validation = validate(con, units, time_digest)
        if not validation["pass"]:
            raise RuntimeError("event time semantic closure validation failed")
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
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.db, args.report, args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
