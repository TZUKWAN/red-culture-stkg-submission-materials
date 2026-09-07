"""Flag entity labels that require context-aware identity resolution before graph release."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_identity_ambiguity.json"
RULE_VERSION = "stkg-v2-identity-ambiguity-1"

GENERIC_LABELS = {
    "党委", "省委", "市委", "县委", "地委", "区委", "工委", "党委会", "委员会",
    "支部", "党支部", "团支部", "党组织", "地下党组织", "基层党组织",
    "游击队", "武工队", "宣传队", "行动队", "工作队", "独立团", "独立营",
    "学校", "中学", "大学", "旧址", "遗址", "故居", "陵园", "根据地",
}
MILITARY_FRAGMENT = re.compile(
    r"^(?:红|新四军|解放军|人民解放军)?"
    r"(?:[一二三四五六七八九十百〇零两卅卌0-9]{1,5})"
    r"(?:军|师|旅|团|营|连|纵队|支队|大队)$"
)


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def identity_ambiguity_reason(name: str) -> str | None:
    value = re.sub(r"\s+", "", str(name or "").strip())
    if value in GENERIC_LABELS:
        return "generic_label"
    if MILITARY_FRAGMENT.fullmatch(value):
        return "incomplete_military_designation"
    return None


def append_json_value(raw: str, value: str) -> str:
    values = json.loads(raw or "[]")
    if value not in values:
        values.append(value)
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def run(database: Path, report_path: Path, apply: bool) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        candidates = []
        by_reason = Counter()
        by_type = Counter()
        for row in con.execute(
            "select entity_id,canonical_name,source_entity_type,semantic_entity_type,"
            "risk_flags_json from v2_entities order by entity_id"
        ):
            reason = identity_ambiguity_reason(row["canonical_name"])
            if not reason:
                continue
            candidates.append((row, reason))
            by_reason[reason] += 1
            by_type[str(row["semantic_entity_type"] or row["source_entity_type"])] += 1
        inserted_conflicts = 0
        updated_entities = 0
        if apply:
            con.execute("begin immediate")
            for row, reason in candidates:
                flag = f"identity_ambiguous:{reason}"
                updated_flags = append_json_value(row["risk_flags_json"], flag)
                if updated_flags != row["risk_flags_json"]:
                    con.execute(
                        "update v2_entities set risk_flags_json=?,updated_at=? where entity_id=?",
                        (updated_flags, now, row["entity_id"]),
                    )
                    updated_entities += 1
                conflict_id = stable_id(
                    "V2CONFLICT", "entity", row["entity_id"], "identity_ambiguity", RULE_VERSION
                )
                cursor = con.execute(
                    "insert or ignore into v2_semantic_conflicts(conflict_id,unit_kind,unit_id,"
                    "conflict_type,severity,details_json,status,detected_at) "
                    "values(?,'entity',?,'identity_ambiguity','warning',?,'open',?)",
                    (
                        conflict_id, row["entity_id"],
                        json.dumps({
                            "rule_version": RULE_VERSION,
                            "reason": reason,
                            "canonical_name": row["canonical_name"],
                            "required_context": ["time", "place", "affiliation", "relation_neighborhood"],
                        }, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                inserted_conflicts += cursor.rowcount
            con.commit()
        report = {
            "result": "PASS",
            "rule_version": RULE_VERSION,
            "apply": apply,
            "candidate_count": len(candidates),
            "updated_entities": updated_entities,
            "inserted_conflicts": inserted_conflicts,
            "by_reason": dict(sorted(by_reason.items())),
            "by_effective_type": dict(sorted(by_type.items())),
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
