"""Train a local weak-supervision entity classifier without mutating the V2 database."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from stkg_contract import strong_entity_type_hint
from stkg_v2_semantics import refine_lexical_hint


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
OUTPUT_DATABASE = ROOT / "derived" / "stkg_v2_entity_classifier.sqlite"
MODEL_PATH = ROOT / "models" / "stkg_v2_entity_classifier.joblib"
REPORT_PATH = ROOT / "audit_reports" / "stkg_v2_entity_classifier.json"
MODEL_VERSION = "stkg-v2-local-entity-classifier-1"
THRESHOLDS = (0.90, 0.95, 0.98, 0.99, 0.995)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_validation_split(name: str, modulus: int = 5) -> bool:
    value = int(hashlib.sha256(name.encode("utf-8")).hexdigest()[:16], 16)
    return value % modulus == 0


def wilson_lower_bound(correct: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    p = correct / total
    denominator = 1.0 + z * z / total
    centre = p + z * z / (2.0 * total)
    spread = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total)
    return max(0.0, (centre - spread) / denominator)


def choose_class_gate(rows: list[tuple[float, bool]], min_support: int = 50) -> dict | None:
    candidates = []
    for threshold in THRESHOLDS:
        selected = [is_correct for confidence, is_correct in rows if confidence >= threshold]
        correct = sum(selected)
        support = len(selected)
        precision = correct / support if support else 0.0
        lower = wilson_lower_bound(correct, support)
        candidates.append({
            "threshold": threshold,
            "support": support,
            "precision": precision,
            "wilson_lower_95": lower,
        })
    eligible = [
        item for item in candidates
        if item["support"] >= min_support
        and item["precision"] >= 0.98
        and item["wilson_lower_95"] >= 0.95
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda item: item["threshold"])


def clean_token(value: str) -> str:
    return re.sub(r"\s+", "_", str(value).strip())[:120]


def relation_token(direction: str, predicate: str, neighbor_type: str) -> str:
    return f"{direction}::{clean_token(predicate)}::{clean_token(neighbor_type)}"


def build_contexts(con: sqlite3.Connection, effective_types: dict[str, str]) -> dict[str, Counter[str]]:
    contexts: dict[str, Counter[str]] = defaultdict(Counter)
    for subject_id, predicate, object_id in con.execute(
        "select subject_id,predicate,object_id from v2_assertion_scopes"
    ):
        subject_id = str(subject_id)
        object_id = str(object_id)
        predicate = str(predicate)
        contexts[subject_id][relation_token("OUT", predicate, effective_types[object_id])] += 1
        contexts[object_id][relation_token("IN", predicate, effective_types[subject_id])] += 1
    return contexts


def context_text(counter: Counter[str], limit: int = 80) -> str:
    return " ".join(token for token, _ in counter.most_common(limit))


def atomic_replace(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)


def write_prediction_database(
    path: Path,
    metadata: dict,
    predictions: list[dict],
    validation_rows: list[dict],
) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    if temp.exists():
        temp.unlink()
    con = sqlite3.connect(temp)
    try:
        con.executescript(
            """
            create table classifier_metadata(key text primary key,value_json text not null check(json_valid(value_json)));
            create table entity_predictions(
              entity_id text primary key, canonical_name text not null, source_type text not null,
              predicted_type text not null, confidence real not null, margin real not null,
              lexical_hint text, schema_top_type text, independent_signal_agreement integer not null,
              class_gate_threshold real, class_gate_pass integer not null,
              eligible_rule_candidate integer not null
            ) without rowid;
            create index idx_entity_predictions_gate on entity_predictions(eligible_rule_candidate,predicted_type,confidence);
            create table validation_predictions(
              entity_id text primary key, canonical_name text not null, true_type text not null,
              predicted_type text not null, confidence real not null, margin real not null,
              correct integer not null
            ) without rowid;
            """
        )
        con.executemany(
            "insert into classifier_metadata values(?,?)",
            [(key, json.dumps(value, ensure_ascii=False, sort_keys=True)) for key, value in metadata.items()],
        )
        con.executemany(
            "insert into entity_predictions values(?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    row["entity_id"], row["canonical_name"], row["source_type"],
                    row["predicted_type"], row["confidence"], row["margin"],
                    row["lexical_hint"], row["schema_top_type"],
                    int(row["independent_signal_agreement"]), row["class_gate_threshold"],
                    int(row["class_gate_pass"]), int(row["eligible_rule_candidate"]),
                )
                for row in predictions
            ],
        )
        con.executemany(
            "insert into validation_predictions values(?,?,?,?,?,?,?)",
            [
                (
                    row["entity_id"], row["canonical_name"], row["true_type"],
                    row["predicted_type"], row["confidence"], row["margin"], int(row["correct"]),
                )
                for row in validation_rows
            ],
        )
        con.commit()
        if con.execute("pragma quick_check").fetchone()[0] != "ok":
            raise RuntimeError("classifier prediction database quick_check failed")
    finally:
        con.close()
    atomic_replace(temp, path)


def run(database: Path, output_database: Path, model_path: Path, report_path: Path) -> dict:
    database = database.resolve()
    source_hash_before = sha256_file(database)
    started = datetime.now()
    con = sqlite3.connect(database, timeout=120)
    con.row_factory = sqlite3.Row
    try:
        entities = [dict(row) for row in con.execute(
            "select entity_id,canonical_name,source_entity_type,semantic_entity_type,aliases_json,"
            "semantic_status,risk_tier from v2_entities order by entity_id"
        )]
        effective_types = {
            str(row["entity_id"]): str(row["semantic_entity_type"] or row["source_entity_type"])
            for row in entities
        }
        contexts = build_contexts(con, effective_types)
        task_payloads = {
            str(row["unit_id"]): json.loads(row["payload_json"])
            for row in con.execute(
                "select unit_id,payload_json from v2_model_tasks "
                "where task_type='entity_type' and status='pending'"
            )
        }
    finally:
        con.close()

    records = []
    for row in entities:
        aliases = [str(value) for value in json.loads(row["aliases_json"]) if str(value).strip()]
        records.append({
            "entity_id": str(row["entity_id"]),
            "canonical_name": str(row["canonical_name"]),
            "source_type": str(row["source_entity_type"]),
            "label": str(row["semantic_entity_type"] or ""),
            "status": str(row["semantic_status"]),
            "name_text": " ".join([str(row["canonical_name"]), *aliases]),
            "context_text": context_text(contexts.get(str(row["entity_id"]), Counter())),
        })
    trainable = [row for row in records if row["status"] == "auto_accepted" and row["label"]]
    train_rows = [row for row in trainable if not stable_validation_split(row["canonical_name"])]
    validation = [row for row in trainable if stable_validation_split(row["canonical_name"])]
    pending = [row for row in records if row["entity_id"] in task_payloads]
    if not train_rows or not validation or not pending:
        raise RuntimeError("classifier requires non-empty train, validation, and pending partitions")

    name_vectorizer = TfidfVectorizer(
        analyzer="char", ngram_range=(1, 4), min_df=2, max_features=180000,
        sublinear_tf=True, dtype=np.float32,
    )
    context_vectorizer = TfidfVectorizer(
        analyzer="word", token_pattern=r"[^ ]+", min_df=2, max_features=120000,
        sublinear_tf=True, dtype=np.float32,
    )
    train_name = name_vectorizer.fit_transform([row["name_text"] for row in train_rows])
    train_context = context_vectorizer.fit_transform([row["context_text"] for row in train_rows])
    x_train = hstack([train_name, train_context], format="csr", dtype=np.float32)
    y_train = np.asarray([row["label"] for row in train_rows])
    classifier = SGDClassifier(
        loss="log_loss", penalty="elasticnet", alpha=2e-6, l1_ratio=0.05,
        max_iter=40, tol=1e-4, class_weight="balanced", random_state=20260714,
        n_jobs=-1, average=True,
    )
    classifier.fit(x_train, y_train)

    def transform(rows: list[dict]):
        names = name_vectorizer.transform([row["name_text"] for row in rows])
        relations = context_vectorizer.transform([row["context_text"] for row in rows])
        return hstack([names, relations], format="csr", dtype=np.float32)

    validation_probabilities = classifier.predict_proba(transform(validation))
    validation_indices = np.argmax(validation_probabilities, axis=1)
    validation_predictions = classifier.classes_[validation_indices]
    validation_confidence = validation_probabilities[np.arange(len(validation)), validation_indices]
    validation_sorted = np.sort(validation_probabilities, axis=1)
    validation_margin = validation_sorted[:, -1] - validation_sorted[:, -2]
    y_validation = np.asarray([row["label"] for row in validation])

    per_class_rows: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    validation_output = []
    for row, predicted, confidence, margin, truth in zip(
        validation, validation_predictions, validation_confidence, validation_margin, y_validation
    ):
        correct = str(predicted) == str(truth)
        per_class_rows[str(predicted)].append((float(confidence), correct))
        validation_output.append({
            "entity_id": row["entity_id"], "canonical_name": row["canonical_name"],
            "true_type": str(truth), "predicted_type": str(predicted),
            "confidence": float(confidence), "margin": float(margin), "correct": correct,
        })
    gates = {label: choose_class_gate(rows) for label, rows in sorted(per_class_rows.items())}

    pending_probabilities = classifier.predict_proba(transform(pending))
    pending_indices = np.argmax(pending_probabilities, axis=1)
    pending_predictions = classifier.classes_[pending_indices]
    pending_confidence = pending_probabilities[np.arange(len(pending)), pending_indices]
    pending_sorted = np.sort(pending_probabilities, axis=1)
    pending_margin = pending_sorted[:, -1] - pending_sorted[:, -2]
    prediction_output = []
    for row, predicted, confidence, margin in zip(
        pending, pending_predictions, pending_confidence, pending_margin
    ):
        payload = task_payloads[row["entity_id"]]
        lexical = refine_lexical_hint(
            row["canonical_name"], row["source_type"],
            strong_entity_type_hint(row["canonical_name"]),
        ) or None
        schema_votes = Counter({str(k): int(v) for k, v in payload.get("schema_votes", {}).items()})
        schema_top = schema_votes.most_common(1)[0][0] if schema_votes else None
        predicted = str(predicted)
        agreement = predicted in {value for value in (lexical, schema_top) if value}
        strict_signal_not_contradicted = not lexical or lexical == predicted
        gate = gates.get(predicted)
        gate_threshold = float(gate["threshold"]) if gate else None
        gate_pass = bool(gate and float(confidence) >= gate_threshold)
        prediction_output.append({
            "entity_id": row["entity_id"], "canonical_name": row["canonical_name"],
            "source_type": row["source_type"], "predicted_type": predicted,
            "confidence": float(confidence), "margin": float(margin),
            "lexical_hint": lexical, "schema_top_type": schema_top,
            "independent_signal_agreement": agreement,
            "class_gate_threshold": gate_threshold, "class_gate_pass": gate_pass,
            "eligible_rule_candidate": gate_pass and agreement and strict_signal_not_contradicted,
        })

    report_dict = classification_report(
        y_validation, validation_predictions, output_dict=True, zero_division=0
    )
    labels = sorted(set(y_validation) | set(validation_predictions))
    matrix = confusion_matrix(y_validation, validation_predictions, labels=labels).tolist()
    eligible = [row for row in prediction_output if row["eligible_rule_candidate"]]
    eligible_changes = [row for row in eligible if row["predicted_type"] != row["source_type"]]
    metadata = {
        "model_version": MODEL_VERSION,
        "source_database": str(database),
        "source_sha256": source_hash_before,
        "train_count": len(train_rows),
        "validation_count": len(validation),
        "pending_count": len(pending),
        "classes": classifier.classes_.tolist(),
        "class_gates": gates,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_prediction_database(output_database, metadata, prediction_output, validation_output)
    model_temp = model_path.with_suffix(model_path.suffix + ".tmp")
    model_temp.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "version": MODEL_VERSION, "name_vectorizer": name_vectorizer,
            "context_vectorizer": context_vectorizer, "classifier": classifier,
            "class_gates": gates,
        },
        model_temp,
        compress=3,
    )
    atomic_replace(model_temp, model_path)
    source_hash_after = sha256_file(database)
    report = {
        "result": "PASS" if source_hash_before == source_hash_after else "FAIL",
        "model_version": MODEL_VERSION,
        "source_database_sha256_before": source_hash_before,
        "source_database_sha256_after": source_hash_after,
        "source_database_unchanged": source_hash_before == source_hash_after,
        "train_count": len(train_rows),
        "validation_count": len(validation),
        "pending_count": len(pending),
        "name_vocabulary_size": len(name_vectorizer.vocabulary_),
        "context_vocabulary_size": len(context_vectorizer.vocabulary_),
        "accuracy": float(accuracy_score(y_validation, validation_predictions)),
        "macro_f1": float(f1_score(y_validation, validation_predictions, average="macro")),
        "weighted_f1": float(f1_score(y_validation, validation_predictions, average="weighted")),
        "classification_report": report_dict,
        "confusion_matrix_labels": labels,
        "confusion_matrix": matrix,
        "class_gates": gates,
        "eligible_rule_candidates": len(eligible),
        "eligible_rule_changes": len(eligible_changes),
        "eligible_by_prediction": dict(sorted(Counter(row["predicted_type"] for row in eligible).items())),
        "prediction_database": str(output_database.resolve()),
        "prediction_database_sha256": sha256_file(output_database),
        "model_path": str(model_path.resolve()),
        "model_sha256": sha256_file(model_path),
        "elapsed_seconds": (datetime.now() - started).total_seconds(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DATABASE)
    parser.add_argument("--output-db", type=Path, default=OUTPUT_DATABASE)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = run(args.db, args.output_db, args.model, args.report)
    print(json.dumps({
        key: report[key] for key in (
            "result", "train_count", "validation_count", "pending_count", "accuracy",
            "macro_f1", "weighted_f1", "eligible_rule_candidates", "eligible_rule_changes",
            "elapsed_seconds",
        )
    }, ensure_ascii=False))
    if report["result"] != "PASS":
        raise RuntimeError("V2 source database changed during read-only classifier training")


if __name__ == "__main__":
    main()
