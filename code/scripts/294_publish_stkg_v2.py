"""Build and atomically publish the standalone STKG V2 release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / "releases"
DEFAULT_RELEASE = RELEASES / "red_culture_stkg_v2"
DEFAULT_TEST_LOG = ROOT / "audit_reports" / "stkg_v2_final_tests.log"
FULL_AUDIT = ROOT / "audit_reports" / "stkg_v2_full_audit.json"
V1_MANIFEST = ROOT / "releases" / "red_culture_stkg_v1" / "release_manifest.json"
REQUIRED_AUDITS = (
    "stkg_v2_research_base.json",
    "stkg_v2_event_culture.json",
    "stkg_v2_evolution.json",
    "stkg_v2_creative_media.json",
    "stkg_v2_final_materialization.json",
    "stkg_v2_competency_queries.json",
    "stkg_v2_graph_export.json",
    "stkg_v2_neo4j_import.json",
    "stkg_v2_neo4j_verification.json",
    "stkg_v2_full_audit.json",
    "stkg_v2_full_audit.md",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_remove_staging(path: Path) -> None:
    resolved = path.resolve()
    release_root = RELEASES.resolve()
    if release_root not in resolved.parents or not path.name.startswith(".red_culture_stkg_v2.staging"):
        raise RuntimeError(f"refusing to remove unsafe staging path: {resolved}")
    if path.exists():
        shutil.rmtree(path)


def add_tree(entries: list[tuple[Path, Path]], source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
            entries.append((path, destination / path.relative_to(source)))


def collect_sources(test_log: Path) -> list[tuple[Path, Path]]:
    entries: list[tuple[Path, Path]] = [
        (ROOT / "STKG_V2_README.md", Path("README.md")),
        (ROOT / "derived" / "red_culture_stkg_final_v2.sqlite", Path("databases/red_culture_stkg_final_v2.sqlite")),
        (ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite", Path("databases/red_culture_stkg_semantic_v2.sqlite")),
        (ROOT / "derived" / "stkg_v2_creative_media_enrichment.sqlite", Path("databases/stkg_v2_creative_media_enrichment.sqlite")),
        (ROOT / "graph_exports" / "stkg_v2" / "nodes.csv", Path("graph/nodes.csv")),
        (ROOT / "graph_exports" / "stkg_v2" / "relationships.csv", Path("graph/relationships.csv")),
        (ROOT / "graph_exports" / "stkg_v2" / "neo4j_import_args.txt", Path("graph/neo4j_import_args.txt")),
        (ROOT / "STKG_V2_FINAL_RESEARCH_REPORT.md", Path("documents/STKG_V2_FINAL_RESEARCH_REPORT.md")),
        (ROOT / "STKG_V2_DATA_DICTIONARY.md", Path("documents/STKG_V2_DATA_DICTIONARY.md")),
        (ROOT / "STKG_V2_SEMANTIC_REPAIR_RESEARCH_PLAN.md", Path("documents/STKG_V2_SEMANTIC_REPAIR_RESEARCH_PLAN.md")),
        (ROOT / "STKG_LITERATURE_ANALYSIS.md", Path("documents/STKG_LITERATURE_ANALYSIS.md")),
        (test_log, Path("audit/stkg_v2_final_tests.log")),
        (V1_MANIFEST, Path("provenance/red_culture_stkg_v1_release_manifest.json")),
    ]
    for name in REQUIRED_AUDITS:
        entries.append((ROOT / "audit_reports" / name, Path("audit") / name))
    for name in (
        "competency_query_contract_v2.yaml",
        "competency_questions_v2.md",
        "culture_form_mapping_v1.yaml",
        "event_role_mapping_v1.yaml",
        "evolution_rules_v1.yaml",
        "stkg_schema_v1.yaml",
    ):
        entries.append((ROOT / "stkg" / "schema" / name, Path("schema") / name))
    add_tree(entries, ROOT / "stkg" / "queries" / "cq_v2", Path("queries/cq_v2"))
    for path in sorted((ROOT / "scripts").glob("*.py")):
        match = re.match(r"^(\d{3})_", path.name)
        if match and 255 <= int(match.group(1)) <= 294:
            entries.append((path, Path("code/scripts") / path.name))
    for path in sorted((ROOT / "tests").glob("test_stkg_v2*.py")):
        entries.append((path, Path("code/tests") / path.name))
    add_tree(entries, ROOT / "stkg_ui_v2", Path("code/stkg_ui_v2"))
    destinations = [str(destination.as_posix()) for _, destination in entries]
    if len(destinations) != len(set(destinations)):
        raise RuntimeError("release plan contains duplicate destination paths")
    missing = [str(source) for source, _ in entries if not source.is_file()]
    if missing:
        raise FileNotFoundError(f"release inputs missing: {missing}")
    return entries


def verify_test_log(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.findall(r"Ran\s+(\d+)\s+tests?\s+in\s+([0-9.]+)s", text)
    passed = bool(match and re.search(r"(?m)^OK\s*$", text) and "FAILED" not in text)
    return {
        "passed": passed,
        "tests": int(match[-1][0]) if match else 0,
        "elapsed_seconds": float(match[-1][1]) if match else None,
        "sha256": sha256(path),
    }


def copy_and_hash(entries: list[tuple[Path, Path]], staging: Path) -> list[dict]:
    files = []
    for source, relative in entries:
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source_hash = sha256(source)
        shutil.copy2(source, target)
        target_hash = sha256(target)
        if source_hash != target_hash or source.stat().st_size != target.stat().st_size:
            raise RuntimeError(f"copy verification failed: {source} -> {target}")
        files.append({
            "path": relative.as_posix(),
            "size_bytes": target.stat().st_size,
            "sha256": target_hash,
        })
    return files


def verify_database(path: Path, final: bool) -> dict:
    con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro&immutable=1", uri=True)
    try:
        result = {
            "quick_check": str(con.execute("pragma quick_check").fetchone()[0]),
            "foreign_key_errors": len(con.execute("pragma foreign_key_check").fetchall()),
        }
        if final:
            result["counts"] = {
                "entities": int(con.execute("select count(*) from research_entities").fetchone()[0]),
                "assertions": int(con.execute("select count(*) from research_assertions").fetchone()[0]),
                "provenance": int(con.execute("select count(*) from research_assertion_provenance").fetchone()[0]),
                "event_frames": int(con.execute("select count(*) from research_event_frames").fetchone()[0]),
                "culture_states": int(con.execute("select count(*) from research_culture_states").fetchone()[0]),
                "published_transitions": int(con.execute("select count(*) from research_evolution_transitions").fetchone()[0]),
            }
    finally:
        con.close()
    result["pass"] = result["quick_check"] == "ok" and result["foreign_key_errors"] == 0
    return result


def verify_manifest(release: Path, manifest: dict) -> list[str]:
    failures = []
    listed = {entry["path"]: entry for entry in manifest["files"]}
    actual = {
        path.relative_to(release).as_posix(): path
        for path in release.rglob("*")
        if path.is_file() and path.name != "release_manifest.json"
    }
    if set(listed) != set(actual):
        return [f"manifest file set differs: missing={sorted(set(listed)-set(actual))}, extra={sorted(set(actual)-set(listed))}"]
    for relative, path in actual.items():
        expected = listed[relative]
        if path.stat().st_size != int(expected["size_bytes"]) or sha256(path) != expected["sha256"]:
            failures.append(f"manifest mismatch: {relative}")
    return failures


def publish(release: Path, test_log: Path) -> dict:
    release = release.resolve()
    if release.exists():
        raise FileExistsError(f"release already exists; refusing to overwrite: {release}")
    test_result = verify_test_log(test_log)
    if not test_result["passed"] or test_result["tests"] < 169:
        raise RuntimeError(f"final V2 test log is not a sufficient PASS: {test_result}")
    full_audit = json.loads(FULL_AUDIT.read_text(encoding="utf-8"))
    if full_audit.get("status") != "PASS" or full_audit.get("failures"):
        raise RuntimeError("full V2 audit is not a clean PASS")
    entries = collect_sources(test_log)
    staging = release.with_name(f".{release.name}.staging-{os.getpid()}")
    safe_remove_staging(staging)
    staging.mkdir(parents=True)
    try:
        files = copy_and_hash(entries, staging)
        final_database = staging / "databases" / "red_culture_stkg_final_v2.sqlite"
        semantic_database = staging / "databases" / "red_culture_stkg_semantic_v2.sqlite"
        final_check = verify_database(final_database, final=True)
        semantic_check = verify_database(semantic_database, final=False)
        if not final_check["pass"] or not semantic_check["pass"]:
            raise RuntimeError("released database integrity check failed")
        graph_report = json.loads((staging / "audit" / "stkg_v2_graph_export.json").read_text(encoding="utf-8"))
        for name in ("nodes.csv", "relationships.csv", "neo4j_import_args.txt"):
            if sha256(staging / "graph" / name) != graph_report["files"][name]["sha256"]:
                raise RuntimeError(f"released graph file differs from export report: {name}")
        manifest = {
            "release_version": "red-culture-stkg-v2-1",
            "research_objective": "长江流域红色文化如何演进",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source_v1_release_manifest": "provenance/red_culture_stkg_v1_release_manifest.json",
            "final_database": {
                "path": "databases/red_culture_stkg_final_v2.sqlite",
                "sha256": sha256(final_database),
                "counts": final_check["counts"],
            },
            "semantic_database": {
                "path": "databases/red_culture_stkg_semantic_v2.sqlite",
                "sha256": sha256(semantic_database),
            },
            "graph": {
                "nodes": graph_report["total_nodes"],
                "relationships": graph_report["total_relationships"],
            },
            "tests": test_result,
            "full_audit_sha256": sha256(staging / "audit" / "stkg_v2_full_audit.json"),
            "files": sorted(files, key=lambda item: item["path"]),
        }
        (staging / "release_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        failures = verify_manifest(staging, manifest)
        if failures:
            raise RuntimeError("staging manifest verification failed: " + "; ".join(failures))
        os.replace(staging, release)
        post_failures = verify_manifest(release, manifest)
        if post_failures:
            raise RuntimeError("published manifest verification failed: " + "; ".join(post_failures))
        return {
            "status": "PASS",
            "release": str(release),
            "manifest": str(release / "release_manifest.json"),
            "file_count": len(files),
            "total_size_bytes": sum(int(item["size_bytes"]) for item in files),
            "final_database": final_check,
            "semantic_database": semantic_check,
            "tests": test_result,
        }
    except Exception:
        safe_remove_staging(staging)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--test-log", type=Path, default=DEFAULT_TEST_LOG)
    args = parser.parse_args()
    result = publish(args.release, args.test_log)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
