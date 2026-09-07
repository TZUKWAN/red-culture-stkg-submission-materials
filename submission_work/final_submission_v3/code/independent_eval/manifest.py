"""Experiment manifest construction (GOAL.md section 21, reproducibility).

Every IMCR experiment run emits a manifest with:

    experiment_id, database_sha256, schema_sha256,
    sample_manifest_sha256, prompt_sha256, model_ids, seed,
    code_commit, timestamp

``code_commit`` comes from ``git rev-parse HEAD`` and falls back to the
literal string ``"UNKNOWN"`` when git is unavailable or the directory is
not a repository.  File digests are computed with a streaming sha256 so
multi-GB databases never need to fit in memory.

Pure standard library.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

__all__ = [
    "sha256_file",
    "sha256_text",
    "git_code_commit",
    "build_manifest",
    "write_manifest",
    "MANIFEST_FIELDS",
    "UNKNOWN_COMMIT",
]

UNKNOWN_COMMIT = "UNKNOWN"

#: Required manifest fields, in canonical order (GOAL 21).
MANIFEST_FIELDS: tuple[str, ...] = (
    "experiment_id",
    "database_sha256",
    "schema_sha256",
    "sample_manifest_sha256",
    "prompt_sha256",
    "model_ids",
    "seed",
    "code_commit",
    "timestamp",
)

_CHUNK = 1024 * 1024  # 1 MiB streaming chunks


def sha256_file(path: str | Path) -> str:
    """Streaming sha256 of a file (hex digest)."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    """sha256 of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_code_commit(cwd: str | Path | None = None) -> str:
    """``git rev-parse HEAD`` of ``cwd``; ``UNKNOWN`` on any failure."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN_COMMIT
    commit = proc.stdout.strip()
    if proc.returncode != 0 or not commit:
        return UNKNOWN_COMMIT
    return commit


def build_manifest(
    experiment_id: str,
    *,
    database_path: str | Path | None = None,
    schema_path: str | Path | None = None,
    sample_manifest_path: str | Path | None = None,
    prompt_sha256: str | None = None,
    model_ids: Sequence[str] = (),
    seed: int | str | None = None,
    code_commit: str | None = None,
    repo_dir: str | Path | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the experiment manifest dict.

    Paths are hashed with :func:`sha256_file` when given; pass pre-computed
    digests through ``extra``-style fields only if the file is unavailable
    (in that case use the literal ``"UNAVAILABLE"`` rather than inventing a
    digest).
    """
    manifest: dict[str, Any] = {
        "experiment_id": experiment_id,
        "database_sha256": (
            sha256_file(database_path) if database_path is not None else "UNAVAILABLE"
        ),
        "schema_sha256": (
            sha256_file(schema_path) if schema_path is not None else "UNAVAILABLE"
        ),
        "sample_manifest_sha256": (
            sha256_file(sample_manifest_path)
            if sample_manifest_path is not None
            else "UNAVAILABLE"
        ),
        "prompt_sha256": prompt_sha256 if prompt_sha256 is not None else "UNAVAILABLE",
        "model_ids": list(model_ids),
        "seed": seed,
        "code_commit": (
            code_commit if code_commit is not None else git_code_commit(repo_dir)
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        manifest.update(extra)
    return manifest


def write_manifest(manifest: Mapping[str, Any], path: str | Path) -> str:
    """Write a manifest JSON; validates that all GOAL-21 fields exist."""
    missing = [f for f in MANIFEST_FIELDS if f not in manifest]
    if missing:
        raise ValueError(f"manifest missing required fields: {missing}")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(dict(manifest), fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return str(path)
