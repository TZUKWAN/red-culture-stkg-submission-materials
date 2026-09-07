"""Import the final STKG V2 export into an isolated Neo4j volume and swap safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase


ROOT = Path(__file__).resolve().parents[1]
EXPORT_REPORT = ROOT / "audit_reports" / "stkg_v2_graph_export.json"
PASSWORD_FILE = ROOT / ".codex" / "runtime" / "neo4j_stkg_v2_password.txt"
OUTPUT = ROOT / "audit_reports" / "stkg_v2_neo4j_import.json"
IMPORT_LOG = ROOT / "run_logs" / "neo4j_stkg_v2_final_import.log"
IMAGE = "neo4j:5.15.0"
MAIN_CONTAINER = "redculture-stkg-neo4j-v2"
TEMP_HTTP_PORT = 17477
TEMP_BOLT_PORT = 17690
FINAL_HTTP_PORT = 7477
FINAL_BOLT_PORT = 7690
BUILD_VERSION = "red-culture-stkg-neo4j-import-v2-2"


UNIQUE_LABELS = (
    "Entity", "Assertion", "SourceRecord", "HistoricalStage", "StudyRegion", "BasinSection",
    "CultureForm", "EventCell", "CultureState", "TransitionCandidate", "EvolutionTransition",
    "TransitionType",
)


SCHEMA_QUERIES = [
    *[
        f"CREATE CONSTRAINT {label.lower()}_stable_id_v2 IF NOT EXISTS "
        f"FOR (n:{label}) REQUIRE n.stable_id IS UNIQUE"
        for label in UNIQUE_LABELS
    ],
    "CREATE INDEX entity_name_v2 IF NOT EXISTS FOR (n:Entity) ON (n.name)",
    "CREATE INDEX entity_type_v2 IF NOT EXISTS FOR (n:Entity) ON (n.entity_type)",
    "CREATE INDEX creative_work_media_v2 IF NOT EXISTS FOR (n:CreativeWork) ON (n.media_type)",
    "CREATE INDEX state_stage_v2 IF NOT EXISTS FOR (n:CultureState) ON (n.stage_code)",
    "CREATE INDEX state_region_v2 IF NOT EXISTS FOR (n:CultureState) ON (n.region_id)",
    "CREATE INDEX state_form_v2 IF NOT EXISTS FOR (n:CultureState) ON (n.culture_form_code)",
    "CREATE INDEX state_tier_v2 IF NOT EXISTS FOR (n:CultureState) ON (n.observation_tier)",
    "CREATE FULLTEXT INDEX entity_name_fulltext_v2 IF NOT EXISTS "
    "FOR (n:Entity) ON EACH [n.name,n.caption]",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=check, capture_output=True, text=True, encoding="utf-8")


def docker_names(kind: str) -> set[str]:
    result = run(["docker", kind, "ls", "--format", "{{.Name}}"])
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def container_names(all_containers: bool = True) -> set[str]:
    command = ["docker", "ps"]
    if all_containers:
        command.append("-a")
    command.extend(["--format", "{{.Names}}"])
    result = run(command)
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def wait_for_neo4j(http_port: int, bolt_port: int, password: str, timeout: int = 300) -> None:
    deadline = time.monotonic() + timeout
    last_error = "not attempted"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{http_port}/", timeout=5) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP status {response.status}")
            with GraphDatabase.driver(
                f"bolt://127.0.0.1:{bolt_port}", auth=("neo4j", password)
            ) as driver:
                driver.verify_connectivity()
            return
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(2)
    raise TimeoutError(f"Neo4j did not become ready: {last_error}")


def apply_schema(bolt_port: int, password: str) -> None:
    with GraphDatabase.driver(
        f"bolt://127.0.0.1:{bolt_port}", auth=("neo4j", password)
    ) as driver:
        with driver.session(database="neo4j") as session:
            for query in SCHEMA_QUERIES:
                session.run(query).consume()
            session.run("CALL db.awaitIndexes(300)").consume()


def verify_graph(bolt_port: int, password: str, export: dict) -> dict:
    expected_nodes = {str(key): int(value) for key, value in export["node_counts"].items()}
    expected_relationships = {
        str(key): int(value) for key, value in export["relationship_counts"].items()
    }
    with GraphDatabase.driver(
        f"bolt://127.0.0.1:{bolt_port}", auth=("neo4j", password)
    ) as driver:
        with driver.session(database="neo4j") as session:
            total_nodes = int(session.run("MATCH (n) RETURN count(n) AS value").single()["value"])
            total_relationships = int(
                session.run("MATCH ()-[r]->() RETURN count(r) AS value").single()["value"]
            )
            node_counts = {
                label: int(session.run(f"MATCH (n:{label}) RETURN count(n) AS value").single()["value"])
                for label in expected_nodes
            }
            relationship_counts = {
                rel_type: int(
                    session.run(f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS value").single()["value"]
                )
                for rel_type in expected_relationships
            }
            media = dict(session.run(
                "MATCH (n:CreativeWork) RETURN count(n) AS creative_work_nodes,"
                "count(n.media_type) AS media_populated,"
                "sum(CASE WHEN n.media_type='未知' THEN 1 ELSE 0 END) AS media_unknown,"
                "sum(CASE WHEN n.media_method='qwen_v2_semantic_classification' THEN 1 ELSE 0 END) AS media_qwen_v2"
            ).single())
            media["non_creative_media_populated"] = int(session.run(
                "MATCH (n:Entity) WHERE NOT n:CreativeWork AND n.media_type IS NOT NULL "
                "RETURN count(n) AS value"
            ).single()["value"])
            indexes = [dict(row) for row in session.run(
                "SHOW INDEXES YIELD name,state RETURN name,state ORDER BY name"
            )]
            constraints = [dict(row) for row in session.run(
                "SHOW CONSTRAINTS YIELD name,type,labelsOrTypes,properties "
                "RETURN name,type,labelsOrTypes,properties ORDER BY name"
            )]
    required_indexes = {
        "entity_name_v2", "entity_type_v2", "creative_work_media_v2", "state_stage_v2",
        "state_region_v2", "state_form_v2", "state_tier_v2", "entity_name_fulltext_v2",
    }
    online_indexes = {str(row["name"]) for row in indexes if row["state"] == "ONLINE"}
    constrained_labels = {
        str(row["labelsOrTypes"][0])
        for row in constraints
        if row["type"] == "UNIQUENESS" and row["properties"] == ["stable_id"]
    }
    expected_media = export["creative_media"]
    checks = {
        "total_nodes": total_nodes == int(export["total_nodes"]),
        "total_relationships": total_relationships == int(export["total_relationships"]),
        "node_counts": node_counts == expected_nodes,
        "relationship_counts": relationship_counts == expected_relationships,
        "creative_media": {key: int(media[key]) for key in expected_media} == expected_media,
        "required_indexes_online": required_indexes <= online_indexes,
        "unique_constraints": set(UNIQUE_LABELS) <= constrained_labels,
    }
    return {
        "pass": all(checks.values()), "checks": checks, "node_counts": node_counts,
        "relationship_counts": relationship_counts, "total_nodes": total_nodes,
        "total_relationships": total_relationships, "creative_media": media,
        "indexes": indexes, "constraints": constraints,
    }


def start_container(name: str, volume: str, http_port: int, bolt_port: int, password: str) -> None:
    run([
        "docker", "run", "-d", "--name", name,
        "-p", f"127.0.0.1:{http_port}:7474",
        "-p", f"127.0.0.1:{bolt_port}:7687",
        "-v", f"{volume}:/data",
        "-e", f"NEO4J_AUTH=neo4j/{password}",
        "-e", "NEO4J_server_memory_heap_initial__size=1G",
        "-e", "NEO4J_server_memory_heap_max__size=3G",
        IMAGE,
    ])


def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def import_and_swap(
    export_report: Path,
    password_file: Path,
    output: Path,
    import_log: Path,
    reuse_imported_volume: bool = False,
) -> dict:
    export = json.loads(export_report.read_text(encoding="utf-8"))
    if export.get("status") != "PASS":
        raise RuntimeError("graph export report is not PASS")
    for metadata in export["files"].values():
        path = Path(metadata["path"])
        if not path.exists() or sha256(path) != metadata["sha256"]:
            raise RuntimeError(f"graph export file hash mismatch: {path}")
    password = password_file.read_text(encoding="utf-8").strip()
    if not password:
        raise RuntimeError("Neo4j password file is empty")
    export_dir = Path(export["files"]["nodes.csv"]["path"]).parent.resolve()
    token = hashlib.sha256(
        (export["files"]["nodes.csv"]["sha256"] + export["files"]["relationships.csv"]["sha256"])
        .encode("ascii")
    ).hexdigest()[:12]
    volume = f"redculture-stkg-neo4j-v2-{token}-data"
    candidate = f"redculture-stkg-neo4j-v2-candidate-{token}"
    existing_volumes = docker_names("volume")
    existing_containers = container_names()
    if candidate in existing_containers:
        raise RuntimeError(f"candidate Docker container already exists: {candidate}")
    if reuse_imported_volume:
        if volume not in existing_volumes:
            raise RuntimeError(f"requested imported candidate volume is absent: {volume}")
    else:
        if volume in existing_volumes:
            raise RuntimeError(f"candidate Docker volume already exists: {volume}")
        run(["docker", "volume", "create", volume])
    import_log.parent.mkdir(parents=True, exist_ok=True)
    import_command = [
        "docker", "run", "--rm", "-v", f"{volume}:/data",
        "-v", f"{export_dir}:/import:ro", IMAGE,
        "neo4j-admin", "database", "import", "full", "neo4j",
        "--id-type=string", "--nodes=/import/nodes.csv",
        "--relationships=/import/relationships.csv", "--overwrite-destination=true",
        "--bad-tolerance=0", "--skip-duplicate-nodes=false",
        "--skip-bad-relationships=false", "--ignore-extra-columns=false", "--trim-strings=false",
    ]
    if not reuse_imported_volume:
        with import_log.open("w", encoding="utf-8") as handle:
            completed = subprocess.run(import_command, stdout=handle, stderr=subprocess.STDOUT, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"Neo4j import failed with code {completed.returncode}; see {import_log}")
    elif not import_log.exists():
        raise RuntimeError(f"cannot reuse imported volume without its import log: {import_log}")
    start_container(candidate, volume, TEMP_HTTP_PORT, TEMP_BOLT_PORT, password)
    backup_name = None
    try:
        wait_for_neo4j(TEMP_HTTP_PORT, TEMP_BOLT_PORT, password)
        apply_schema(TEMP_BOLT_PORT, password)
        candidate_verification = verify_graph(TEMP_BOLT_PORT, password, export)
        if not candidate_verification["pass"]:
            raise RuntimeError(f"candidate Neo4j verification failed: {candidate_verification['checks']}")
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_name = f"{MAIN_CONTAINER}-previous-{timestamp}"
        if MAIN_CONTAINER not in container_names():
            raise RuntimeError(f"current V2 container is missing: {MAIN_CONTAINER}")
        run(["docker", "stop", MAIN_CONTAINER])
        run(["docker", "rename", MAIN_CONTAINER, backup_name])
        run(["docker", "stop", candidate])
        run(["docker", "rm", candidate])
        start_container(MAIN_CONTAINER, volume, FINAL_HTTP_PORT, FINAL_BOLT_PORT, password)
        try:
            wait_for_neo4j(FINAL_HTTP_PORT, FINAL_BOLT_PORT, password)
            final_verification = verify_graph(FINAL_BOLT_PORT, password, export)
            if not final_verification["pass"]:
                raise RuntimeError(f"final Neo4j verification failed: {final_verification['checks']}")
        except Exception:
            if MAIN_CONTAINER in container_names():
                run(["docker", "rm", "-f", MAIN_CONTAINER], check=False)
            run(["docker", "rename", backup_name, MAIN_CONTAINER])
            run(["docker", "start", MAIN_CONTAINER])
            raise
    except Exception:
        if candidate in container_names():
            run(["docker", "rm", "-f", candidate], check=False)
        raise
    report = {
        "status": "PASS", "build_version": BUILD_VERSION,
        "export_report": {"path": str(export_report.resolve()), "sha256": sha256(export_report)},
        "import_log": {"path": str(import_log.resolve()), "sha256": sha256(import_log)},
        "new_volume": volume, "active_container": MAIN_CONTAINER,
        "rollback_container": backup_name,
        "reused_imported_volume": reuse_imported_volume,
        "ports": {"http": FINAL_HTTP_PORT, "bolt": FINAL_BOLT_PORT},
        "candidate_verification": candidate_verification,
        "final_verification": final_verification,
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    atomic_write_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-report", type=Path, default=EXPORT_REPORT)
    parser.add_argument("--password-file", type=Path, default=PASSWORD_FILE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--import-log", type=Path, default=IMPORT_LOG)
    parser.add_argument("--reuse-imported-volume", action="store_true")
    args = parser.parse_args()
    report = import_and_swap(
        args.export_report.resolve(), args.password_file.resolve(),
        args.output.resolve(), args.import_log.resolve(), args.reuse_imported_volume,
    )
    print(json.dumps({
        "status": report["status"], "active_container": report["active_container"],
        "rollback_container": report["rollback_container"], "new_volume": report["new_volume"],
        "final_checks": report["final_verification"]["checks"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
