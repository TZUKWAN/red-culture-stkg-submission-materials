"""Verify the shipped file snapshot without services or optional dependencies.

This checks repository organization and archive integrity. Historical study
reports are preserved evidence, not new experiment results from this verifier.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "metadata/SYNC_SNAPSHOT_20261107.json"
LATEST = "metadata/LATEST_MANUSCRIPT.json"
NEW_READMES = (
    "README.md",
    "documents/REPOSITORY_STATUS.md",
    "manuscript/revisions/README.md",
    "manuscript/revisions/20261015_round4/README.md",
    "submission_work/final_submission_v3_2/README.md",
    "submission_work/final_submission_v3_2/release_final_v3_2/README.md",
)


def inside_root(relative: str) -> Path:
    name = PurePosixPath(relative)
    if name.is_absolute() or ".." in name.parts or "\\" in relative:
        raise ValueError(f"unsafe manifest path: {relative}")
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise ValueError(f"path outside repository: {relative}")
    return path


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def archive_check(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC check failed")
        for member in archive.infolist():
            name = PurePosixPath(member.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("unsafe archive member")
        if path.suffix.lower() == ".docx":
            doc = ET.fromstring(archive.read("word/document.xml"))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            if not doc.findall(".//w:tbl", ns):
                raise ValueError("no editable Word tables found")
            rels = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
            for rel in rels:
                if rel.get("TargetMode") == "External":
                    continue
                target = rel.get("Target", "")
                if rel.get("Type", "").endswith(("/image", "/oleObject")):
                    resolved = str(PurePosixPath("word") / target)
                    if resolved not in archive.namelist():
                        raise ValueError(f"missing embedded object: {target}")


def verify_file(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix in {".docx", ".zip"}:
        archive_check(path)
    elif suffix == ".pdf":
        data = path.read_bytes()
        if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
            raise ValueError("invalid PDF header or trailer")
    elif suffix == ".json":
        read_json(path)
    elif suffix == ".csv":
        text = path.read_text(encoding="utf-8-sig")
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        if next(rows, None) is None:
            raise ValueError("empty CSV")
        for _ in rows:
            pass
    elif suffix == ".py":
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def relative_links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    targets = re.findall(r"\[[^\]]*\]\(([^)\s]+)\)", text)
    missing = []
    for target in targets:
        url = urlsplit(target)
        if url.scheme or target.startswith("#"):
            continue
        rel = unquote(url.path)
        candidate = (path.parent / rel).resolve()
        if not candidate.is_relative_to(ROOT.resolve()) or not candidate.exists():
            missing.append(target)
    return missing


def verify() -> dict:
    failures: list[dict] = []
    count = 0
    total = 0
    manifest = read_json(ROOT / MANIFEST)
    paths = [record["path"] for record in manifest["files"]]
    if len(paths) != len(set(paths)):
        failures.append({"check": "unique_paths", "detail": "duplicate manifest paths"})
    for record in manifest["files"]:
        try:
            path = inside_root(record["path"])
            data = path.read_bytes()
            if len(data) != record["bytes"]:
                raise ValueError("file size differs from source snapshot")
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError("SHA-256 differs from source snapshot")
            if len(data) >= 95 * 1024 * 1024:
                raise ValueError("new file exceeds repository sync size limit")
            verify_file(path)
            count += 1
            total += len(data)
        except (OSError, ValueError, SyntaxError, ET.ParseError, zipfile.BadZipFile, csv.Error) as exc:
            failures.append({"check": "file", "path": record["path"], "detail": str(exc)})
    latest = read_json(ROOT / LATEST)
    for field in ("directory", "docx", "pdf", "figures", "acceptance_report", "author_confirmation", "file_manifest"):
        if not inside_root(latest[field]).exists():
            failures.append({"check": "latest_entry", "field": field})
    if latest["status"] != "review_draft_with_recorded_open_items":
        failures.append({"check": "review_status", "detail": "review draft mislabeled"})
    release = read_json(ROOT / "metadata/CURRENT_RELEASE.json")
    if release["paper"]["manuscript_dir"] != latest["directory"]:
        failures.append({"check": "entry_consistency"})
    for source in release["paper"]["authoritative_results"]:
        if not inside_root(source).is_file():
            failures.append({"check": "data_entry", "path": source})
    for relative in NEW_READMES:
        missing = relative_links(ROOT / relative)
        if missing:
            failures.append({"check": "relative_links", "path": relative, "missing": missing})
    return {
        "scope": "repository_snapshot_integrity_only",
        "status": "PASS" if not failures else "FAIL",
        "verified_files": count,
        "manifest_files": len(manifest["files"]),
        "verified_bytes": total,
        "checked_readme_files": len(NEW_READMES),
        "new_model_calls": 0,
        "research_validation_rerun": False,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Optional output JSON path")
    args = parser.parse_args()
    result = verify()
    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
