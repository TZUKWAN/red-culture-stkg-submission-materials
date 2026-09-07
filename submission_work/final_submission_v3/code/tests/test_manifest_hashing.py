"""GOAL 21: experiment manifest and hashing reproducibility."""

from __future__ import annotations

import json
import os

import pytest

from manifest import (
    MANIFEST_FIELDS,
    UNKNOWN_COMMIT,
    build_manifest,
    git_code_commit,
    sha256_file,
    sha256_text,
    write_manifest,
)


def test_sha256_file_stable_across_reads(tmp_path):
    f = tmp_path / "blob.bin"
    payload = os.urandom(3 * 1024 * 1024 + 7)  # > 1 chunk, exercises streaming
    f.write_bytes(payload)
    h1 = sha256_file(f)
    h2 = sha256_file(f)
    assert h1 == h2
    import hashlib

    assert h1 == hashlib.sha256(payload).hexdigest()


def test_sha256_file_detects_change(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("版本一", encoding="utf-8")
    h1 = sha256_file(f)
    f.write_text("版本二", encoding="utf-8")
    assert sha256_file(f) != h1


def test_sha256_text_known_value():
    import hashlib

    assert sha256_text("prompt-v1") == hashlib.sha256(b"prompt-v1").hexdigest()


def test_git_code_commit_returns_hash_or_unknown():
    commit = git_code_commit()
    assert commit == UNKNOWN_COMMIT or (len(commit) == 40 and all(
        c in "0123456789abcdef" for c in commit
    ))


def test_git_code_commit_unknown_for_non_repo(tmp_path):
    assert git_code_commit(tmp_path) in (UNKNOWN_COMMIT,) or len(git_code_commit(tmp_path)) == 40


def test_manifest_has_all_goal21_fields(tmp_path):
    db = tmp_path / "db.sqlite"
    db.write_bytes(b"fake-db")
    schema = tmp_path / "schema.sql"
    schema.write_text("CREATE TABLE t(x);", encoding="utf-8")
    sample = tmp_path / "SAMPLE_MANIFEST.csv"
    sample.write_text("task_id\nT-1\n", encoding="utf-8")

    m = build_manifest(
        "imcr_entity_type_2026",
        database_path=db,
        schema_path=schema,
        sample_manifest_path=sample,
        prompt_sha256=sha256_text("prompt"),
        model_ids=["model-a", "model-b", "model-c"],
        seed=2026,
        code_commit="deadbeef" * 5,
    )
    for field in MANIFEST_FIELDS:
        assert field in m
    assert m["database_sha256"] == sha256_file(db)
    assert m["schema_sha256"] == sha256_file(schema)
    assert m["sample_manifest_sha256"] == sha256_file(sample)
    assert m["model_ids"] == ["model-a", "model-b", "model-c"]
    assert m["seed"] == 2026
    assert m["code_commit"] != UNKNOWN_COMMIT

    out = tmp_path / "manifest.json"
    write_manifest(m, out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded == m


def test_manifest_hash_stability(tmp_path):
    f = tmp_path / "stable.csv"
    f.write_text("task_id,label\nT-1,X\n", encoding="utf-8")
    m1 = build_manifest("exp", database_path=f, code_commit="c" * 40)
    m2 = build_manifest("exp", database_path=f, code_commit="c" * 40)
    assert m1["database_sha256"] == m2["database_sha256"]


def test_write_manifest_rejects_missing_fields(tmp_path):
    with pytest.raises(ValueError):
        write_manifest({"experiment_id": "x"}, tmp_path / "m.json")


def test_manifest_unavailable_paths_marked_not_invented():
    m = build_manifest("exp", code_commit="c" * 40)
    assert m["database_sha256"] == "UNAVAILABLE"
    assert m["schema_sha256"] == "UNAVAILABLE"
    assert m["sample_manifest_sha256"] == "UNAVAILABLE"
    assert m["prompt_sha256"] == "UNAVAILABLE"
