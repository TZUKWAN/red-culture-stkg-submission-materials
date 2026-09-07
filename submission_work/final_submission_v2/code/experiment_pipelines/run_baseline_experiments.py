#!/usr/bin/env python3
"""Run leakage-controlled Paper A baselines on the unchanged AI ensemble gold.

The harness deliberately separates three evidence classes:

* ``actual_run``: deterministic rules and a classical text classifier executed
  in this run on a fixed, stratified test split;
* ``deterministic_replay``: frozen V2 labels replayed without rerunning the
  historical construction pipeline;
* ``cached_model_output``: historical local-LLM predictions.  These predictions
  are a direct channel of the AI ensemble gold and are therefore never treated
  as an independent performance baseline.

No external AI or local LLM is invoked.  Release databases are opened read-only,
and every generated artifact is written below ``revision/02_baselines``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import scipy
import sklearn
from scipy.stats import beta
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression


SCRIPT = Path(__file__).resolve()
OUTDIR = SCRIPT.parent
ROOT = SCRIPT.parents[4]
RESULTS = ROOT / "dual_paper_project/paper_A_method/04_results"
GOLD_PATH = RESULTS / "AI_GOLD_LABELS.csv"
SAMPLES_PATH = RESULTS / "controlled_eval_samples.csv"
LLM_PATH = RESULTS / "llm_predictions.csv"
LEGACY_BASELINE_PATH = RESULTS / "BASELINE_ESTIMATES.csv"
FINAL_DB = ROOT / "releases/red_culture_stkg_v2/databases/red_culture_stkg_final_v2.sqlite"
SEMANTIC_DB = ROOT / "releases/red_culture_stkg_v2/databases/red_culture_stkg_semantic_v2.sqlite"
EVIDENCE_CONTRACT = (
    ROOT
    / "dual_paper_project/paper_A_method/revision/00_workspace_audit/EXPERIMENT_EVIDENCE_CONTRACT.md"
)
ROLE_OWNER_AUDIT = (
    ROOT / "dual_paper_project/paper_A_method/revision/04_role_owner/role_owner_audit.json"
)
SPLIT_SEED = "paper-a-baseline-stratified-v1-20260730"
RANDOM_STATE = 20260730
OWNER_PROXY_TASKS = {"time_owner", "space_owner"}

SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from stkg_contract import RELATIONS, strong_entity_type_hint  # noqa: E402
from stkg_v2_semantics import (  # noqa: E402
    TYPE_FAMILY,
    classify_space_scope,
    classify_time_scope,
    entity_model_contraindication,
    fuse_entity_type,
    refine_lexical_hint,
)


METHODS = [
    {
        "method_id": "M1_rule_only",
        "method_name": "Rule-only",
        "evidence_class": "actual_run",
        "comparison_tier": "shared-channel diagnostic",
        "overlap_status": "shared_gold_rule_channel",
        "primary_comparison_eligible": False,
        "availability": "available",
        "reason": "Production deterministic rules rerun on frozen test inputs; the AI gold shares a rule channel.",
    },
    {
        "method_id": "M2_classifier_only",
        "method_name": "Classifier-only",
        "evidence_class": "actual_run",
        "comparison_tier": "held-out supervised proxy benchmark",
        "overlap_status": "gold_supervised_disjoint_test",
        "primary_comparison_eligible": True,
        "availability": "available",
        "reason": "Task-specific classical TF-IDF logistic classifiers fitted on train/dev AI-gold rows and evaluated on disjoint test rows; this is a supervised proxy benchmark, not label-independent factual accuracy.",
    },
    {
        "method_id": "M3_live_llm_only",
        "method_name": "LLM-only (live)",
        "evidence_class": "not_available",
        "comparison_tier": "not available",
        "overlap_status": "none",
        "primary_comparison_eligible": False,
        "availability": "not_available",
        "reason": "No live LLM inference was authorized or executed in this run.",
    },
    {
        "method_id": "M3_cached_llm_replay",
        "method_name": "LLM-only (cached replay)",
        "evidence_class": "cached_model_output",
        "comparison_tier": "shared-channel diagnostic",
        "overlap_status": "shared_gold_llm_channel",
        "primary_comparison_eligible": False,
        "availability": "available",
        "reason": "Historical llm_predictions.csv is replayed; the same predictions contributed directly to AI gold admission.",
    },
    {
        "method_id": "M4_rule_plus_cached_llm",
        "method_name": "Rule + cached LLM agreement",
        "evidence_class": "cached_model_output",
        "comparison_tier": "shared-channel diagnostic",
        "overlap_status": "shared_gold_rule_and_llm_channels",
        "primary_comparison_eligible": False,
        "availability": "available",
        "reason": "Agreement-only replay uses the two channels that formed several AI-gold task labels; it is not independent accuracy evidence.",
    },
    {
        "method_id": "M5_no_global_closure",
        "method_name": "Rule + Classifier + LLM without global closure",
        "evidence_class": "not_available",
        "comparison_tier": "not available",
        "overlap_status": "none",
        "primary_comparison_eligible": False,
        "availability": "not_available",
        "reason": "No frozen per-sample outputs or runnable pre-closure harness exist for this configuration.",
    },
    {
        "method_id": "M6_full_v2_replay",
        "method_name": "Full V2 framework (frozen replay)",
        "evidence_class": "deterministic_replay",
        "comparison_tier": "frozen full-method replay",
        "overlap_status": "shared_system_signal",
        "primary_comparison_eligible": False,
        "availability": "available",
        "reason": "Frozen V2 sample labels and stored confidence are replayed; this is not a fresh end-to-end run.",
    },
]
METHOD_BY_ID = {row["method_id"]: row for row in METHODS}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def ro_connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def parse_context(sample: dict[str, str]) -> dict[str, Any]:
    value = json.loads(sample["context_json"])
    if not isinstance(value, dict):
        raise ValueError(f"context_json must be an object: {sample['sample_id']}")
    return value


def owner_side(gold_label: str, context: dict[str, Any]) -> str:
    candidates = list(context.get("candidates") or [])
    if len(candidates) < 2:
        return "__UNRESOLVED__"
    if str(candidates[0].get("name") or "") == gold_label:
        return "subject"
    if str(candidates[1].get("name") or "") == gold_label:
        return "object"
    return "__UNRESOLVED__"


def model_target(gold_row: dict[str, str], sample: dict[str, str]) -> str:
    if gold_row["task_type"] in {"time_owner", "space_owner"}:
        return owner_side(gold_row["ai_gold"], parse_context(sample))
    return gold_row["ai_gold"]


def stable_rank(sample_id: str) -> str:
    return hashlib.sha256(f"{SPLIT_SEED}|{sample_id}".encode("utf-8")).hexdigest()


def build_split_manifest(
    gold_rows: list[dict[str, str]], samples: dict[str, dict[str, str]]
) -> list[dict[str, str]]:
    """Create a deterministic label-stratified train/dev/test split.

    Singleton labels remain in training.  Every label admitted to test has at
    least one same-task training example, so unseen-class failures are not
    silently converted into abstentions.
    """

    strata: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    targets: dict[str, str] = {}
    for row in gold_rows:
        target = model_target(row, samples[row["sample_id"]])
        targets[row["sample_id"]] = target
        strata[(row["task_type"], target)].append(row)

    assignment: dict[str, str] = {}
    for _key, rows in sorted(strata.items()):
        ordered = sorted(rows, key=lambda row: stable_rank(row["sample_id"]))
        n = len(ordered)
        if n == 1:
            train_n, dev_n = 1, 0
        elif n == 2:
            train_n, dev_n = 1, 0
        else:
            test_n = max(1, int(round(n * 0.20)))
            dev_n = max(1, int(round(n * 0.20)))
            if test_n + dev_n >= n:
                dev_n = max(0, n - test_n - 1)
            train_n = n - test_n - dev_n
        for index, row in enumerate(ordered):
            split = "train" if index < train_n else ("dev" if index < train_n + dev_n else "test")
            assignment[row["sample_id"]] = split

    manifest = []
    for row in sorted(gold_rows, key=lambda value: value["sample_id"]):
        manifest.append(
            {
                "sample_id": row["sample_id"],
                "task_type": row["task_type"],
                "item_id": row["item_id"],
                "model_target": targets[row["sample_id"]],
                "split": assignment[row["sample_id"]],
                "split_seed": SPLIT_SEED,
            }
        )
    return manifest


def feature_text(sample: dict[str, str]) -> str:
    """Return classifier input without gold labels or frozen V2 outputs."""

    task = sample["task_type"]
    context = parse_context(sample)
    tokens = [f"task={task}"]
    if task == "entity_type":
        tokens.extend(
            [
                f"name={context.get('name', '')}",
                "aliases=" + "|".join(str(value) for value in context.get("aliases", [])),
            ]
        )
    elif task == "relation_semantic":
        tokens.extend(
            [
                f"subject={context.get('subject', '')}",
                f"subject_type={context.get('subject_type', '')}",
                f"object={context.get('object', '')}",
                f"object_type={context.get('object_type', '')}",
            ]
        )
    elif task in {"time_role", "space_role", "time_owner", "space_owner"}:
        tokens.extend(
            [
                f"predicate={context.get('predicate', '')}",
                f"subject_type={context.get('subject_type', '')}",
                f"object_type={context.get('object_type', '')}",
                f"raw={context.get('raw', '')}",
            ]
        )
    elif task == "event_role":
        tokens.extend(
            [
                f"predicate={context.get('predicate', '')}",
                f"counterpart_type={context.get('counterpart_type', '')}",
            ]
        )
    else:
        tokens.append("context=" + json.dumps(context, ensure_ascii=False, sort_keys=True))
    text = " ".join(tokens)
    forbidden = (sample.get("v2_label", ""),)
    if any(value and value in text and value not in sample["context_json"] for value in forbidden):
        raise AssertionError("classifier feature unexpectedly includes frozen V2 label")
    return text


def classifier_predictions(
    gold_rows: list[dict[str, str]],
    samples: dict[str, dict[str, str]],
    manifest: dict[str, dict[str, str]],
) -> tuple[dict[str, tuple[str | None, float | None, str]], dict[str, Any]]:
    outputs: dict[str, tuple[str | None, float | None, str]] = {}
    metadata: dict[str, Any] = {}
    by_task: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in gold_rows:
        by_task[row["task_type"]].append(row)

    for task, rows in sorted(by_task.items()):
        fit_rows = [row for row in rows if manifest[row["sample_id"]]["split"] in {"train", "dev"}]
        test_rows = [row for row in rows if manifest[row["sample_id"]]["split"] == "test"]
        x_fit = [feature_text(samples[row["sample_id"]]) for row in fit_rows]
        y_fit = [model_target(row, samples[row["sample_id"]]) for row in fit_rows]
        classes = sorted(set(y_fit))
        task_meta: dict[str, Any] = {
            "fit_count": len(fit_rows),
            "test_count": len(test_rows),
            "fit_class_count": len(classes),
            "fit_class_distribution": dict(sorted(Counter(y_fit).items())),
            "test_class_distribution": dict(
                sorted(Counter(model_target(row, samples[row["sample_id"]]) for row in test_rows).items())
            ),
            "random_state": RANDOM_STATE,
            "feature_policy": "task-specific context fields only; no ai_gold and no v2_label",
        }
        if not test_rows:
            task_meta["status"] = "not_available_no_test_rows"
            metadata[task] = task_meta
            continue
        if len(classes) < 2:
            task_meta["status"] = "not_available_single_training_class"
            for row in test_rows:
                outputs[row["sample_id"]] = (None, None, task_meta["status"])
            metadata[task] = task_meta
            continue
        unseen = sorted(
            set(model_target(row, samples[row["sample_id"]]) for row in test_rows) - set(classes)
        )
        if unseen:
            raise AssertionError(f"test labels absent from fit split for {task}: {unseen}")

        vectorizer = TfidfVectorizer(
            analyzer="char",
            ngram_range=(1, 4),
            min_df=1,
            max_features=30000,
            sublinear_tf=True,
            dtype=np.float64,
        )
        x_matrix = vectorizer.fit_transform(x_fit)
        classifier = LogisticRegression(
            C=2.0,
            class_weight="balanced",
            max_iter=2000,
            random_state=RANDOM_STATE,
            solver="lbfgs",
        )
        classifier.fit(x_matrix, np.asarray(y_fit))
        test_matrix = vectorizer.transform([feature_text(samples[row["sample_id"]]) for row in test_rows])
        probabilities = classifier.predict_proba(test_matrix)
        indices = np.argmax(probabilities, axis=1)
        predictions = classifier.classes_[indices]
        confidences = probabilities[np.arange(len(test_rows)), indices]
        for row, prediction, confidence in zip(test_rows, predictions, confidences):
            prediction = str(prediction)
            if task in {"time_owner", "space_owner"}:
                context = parse_context(samples[row["sample_id"]])
                candidates = list(context.get("candidates") or [])
                side_index = 0 if prediction == "subject" else (1 if prediction == "object" else -1)
                if side_index < 0 or side_index >= len(candidates):
                    outputs[row["sample_id"]] = (None, float(confidence), "actual_run_invalid_owner_side")
                    continue
                prediction = str(candidates[side_index].get("name") or "") or None
            outputs[row["sample_id"]] = (prediction, float(confidence), "actual_run")
        task_meta.update(
            {
                "status": "actual_run",
                "vocabulary_size": len(vectorizer.vocabulary_),
                "classes": [str(value) for value in classifier.classes_],
                "iterations": [int(value) for value in classifier.n_iter_],
            }
        )
        metadata[task] = task_meta
    return outputs, metadata


def build_rule_resources(gold_rows: list[dict[str, str]]) -> dict[str, Any]:
    entity_ids = {row["item_id"] for row in gold_rows if row["task_type"] == "entity_type"}
    with ro_connect(SEMANTIC_DB) as con:
        entities = {}
        name_source_types: dict[str, set[str]] = defaultdict(set)
        for row in con.execute(
            "select entity_id,canonical_name,source_entity_type,aliases_json from v2_entities"
        ):
            entity_id = str(row["entity_id"])
            name = str(row["canonical_name"])
            source_type = str(row["source_entity_type"])
            name_source_types[name].add(source_type)
            if entity_id in entity_ids:
                entities[entity_id] = {
                    "name": name,
                    "source_type": source_type,
                    "aliases_json": str(row["aliases_json"]),
                }
        schema_votes: dict[str, Counter[str]] = defaultdict(Counter)
        for subject_id, predicate, object_id in con.execute(
            "select subject_id,predicate,object_id from v2_assertion_scopes where predicate not like 'raw:%'"
        ):
            subject_id = str(subject_id)
            object_id = str(object_id)
            spec = RELATIONS.get(str(predicate))
            if spec is None:
                continue
            if subject_id in entity_ids and len(spec.source_types) == 1:
                schema_votes[subject_id][next(iter(spec.source_types))] += 1
            if object_id in entity_ids and len(spec.target_types) == 1:
                schema_votes[object_id][next(iter(spec.target_types))] += 1

        full_entity = {
            str(row["entity_id"]): {
                "status": str(row["semantic_status"]),
                "confidence": None if row["confidence"] is None else float(row["confidence"]),
                "risk_tier": str(row["risk_tier"] or ""),
                "risk_flags": json.loads(str(row["risk_flags_json"] or "[]")),
            }
            for row in con.execute(
                "select entity_id,semantic_status,confidence,risk_tier,risk_flags_json from v2_entities"
            )
            if str(row["entity_id"]) in entity_ids
        }
        assertion_ids = {row["item_id"] for row in gold_rows if row["task_type"] != "entity_type"}
        full_assertion = {
            str(row["fact_id"]): {
                "status": str(row["semantic_status"]),
                "confidence": None if row["confidence"] is None else float(row["confidence"]),
                "risk_tier": str(row["risk_tier"] or ""),
                "risk_flags": json.loads(str(row["risk_flags_json"] or "[]")),
            }
            for row in con.execute(
                "select fact_id,semantic_status,confidence,risk_tier,risk_flags_json from v2_assertion_scopes"
            )
            if str(row["fact_id"]) in assertion_ids
        }

    with ro_connect(FINAL_DB) as con:
        relation_contract = {
            str(row["predicate"]): {
                "source_types": set(json.loads(str(row["source_types_json"]))),
                "target_types": set(json.loads(str(row["target_types_json"]))),
            }
            for row in con.execute(
                "select predicate,source_types_json,target_types_json from research_relation_contract"
            )
        }
        event_role_catalog = {
            (str(row["predicate"]), str(row["event_endpoint"])): str(row["role_code"])
            for row in con.execute(
                "select predicate,event_endpoint,role_code from research_event_role_catalog"
            )
        }
    return {
        "entities": entities,
        "name_source_types": name_source_types,
        "schema_votes": schema_votes,
        "relation_contract": relation_contract,
        "event_role_catalog": event_role_catalog,
        "full_entity": full_entity,
        "full_assertion": full_assertion,
    }


def rule_prediction(sample: dict[str, str], resources: dict[str, Any]) -> tuple[str | None, float | None, str]:
    task = sample["task_type"]
    context = parse_context(sample)
    if task == "entity_type":
        entity = resources["entities"].get(sample["item_id"])
        if entity is None:
            return None, None, "missing_entity_source_record"
        lexical = refine_lexical_hint(
            entity["name"], entity["source_type"], strong_entity_type_hint(entity["name"])
        )
        fusion = fuse_entity_type(
            entity["source_type"],
            lexical,
            resources["schema_votes"].get(sample["item_id"], Counter()),
            len(resources["name_source_types"].get(entity["name"], set())) > 1,
        )
        return fusion.final_type, fusion.confidence, fusion.status

    predicate = str(context.get("predicate") or "")
    subject_type = str(context.get("subject_type") or "")
    object_type = str(context.get("object_type") or "")
    subject = str(context.get("subject") or "subject")
    obj = str(context.get("object") or "object")
    if task == "relation_semantic":
        contract = resources["relation_contract"].get(predicate)
        if contract and subject_type in contract["source_types"] and object_type in contract["target_types"]:
            return predicate, 0.99, "contract_accept"
        return None, None, "contract_abstain"
    if task in {"time_role", "time_owner"}:
        scope = classify_time_scope(predicate, "present", subject, subject_type, obj, object_type)
        if task == "time_role":
            return scope.role, scope.confidence, scope.rationale
        return scope.owner_id, scope.confidence, scope.rationale
    if task in {"space_role", "space_owner"}:
        scope = classify_space_scope(predicate, "present", subject, subject_type, obj, object_type)
        if task == "space_role":
            return scope.role, scope.confidence, scope.rationale
        return scope.owner_id, scope.confidence, scope.rationale
    if task == "event_role":
        prediction = resources["event_role_catalog"].get((predicate, "object")) or resources[
            "event_role_catalog"
        ].get((predicate, "subject"))
        return prediction, 0.99 if prediction else None, "event_role_catalog" if prediction else "catalog_abstain"
    return None, None, "unsupported_task"


def normalize_cached_llm(sample: dict[str, str], llm_row: dict[str, str] | None) -> tuple[str | None, str]:
    if not llm_row or str(llm_row.get("parse_ok", "")).lower() != "true":
        return None, "cached_prediction_missing_or_unparsed"
    task = sample["task_type"]
    raw = str(llm_row.get("llm_label") or "")
    if not raw:
        return None, "cached_prediction_empty"
    context = parse_context(sample)
    if task == "relation_semantic":
        if raw == "correct":
            return str(context.get("predicate") or "") or None, "cached_model_output"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None, "cached_relation_parse_failed"
        if isinstance(parsed, dict):
            return str(parsed.get("best") or "") or None, "cached_model_output"
        return None, "cached_relation_shape_invalid"
    if task in {"time_owner", "space_owner"}:
        candidates = list(context.get("candidates") or [])
        index = 0 if raw == "subject" else (1 if raw == "object" else -1)
        if index < 0 or index >= len(candidates):
            return None, "cached_owner_side_invalid"
        return str(candidates[index].get("name") or "") or None, "cached_model_output"
    return raw, "cached_model_output"


def hard_constraint_pass(
    sample: dict[str, str], prediction: str | None, resources: dict[str, Any]
) -> bool:
    if not prediction:
        return False
    task = sample["task_type"]
    context = parse_context(sample)
    predicate = str(context.get("predicate") or "")
    subject_type = str(context.get("subject_type") or "")
    object_type = str(context.get("object_type") or "")
    if task == "entity_type":
        if prediction not in TYPE_FAMILY:
            return False
        name = str(context.get("name") or "")
        source_type = str(context.get("source_entity_type") or "")
        return not entity_model_contraindication(name, source_type, prediction)
    if task == "relation_semantic":
        contract = resources["relation_contract"].get(prediction)
        return bool(
            contract
            and subject_type in contract["source_types"]
            and object_type in contract["target_types"]
        )
    if task == "time_role":
        if prediction == "event_occurrence":
            return "Event" in {subject_type, object_type}
        if prediction == "biographical":
            return "Person" in {subject_type, object_type}
        return prediction in {
            "context_time",
            "relation_validity",
            "creation_or_publication",
            "commemoration_or_reception",
            "source_document_time",
        }
    if task == "space_role":
        if prediction == "event_location":
            return "Event" in {subject_type, object_type}
        if prediction == "biographical_location":
            return "Person" in {subject_type, object_type}
        return prediction in {
            "context_location",
            "relation_location",
            "creation_or_publication_location",
            "commemoration_or_reception_location",
            "source_document_location",
        }
    if task in {"time_owner", "space_owner"}:
        names = {str(row.get("name") or "") for row in context.get("candidates", [])}
        return prediction in names
    if task == "event_role":
        allowed = {
            role
            for (catalog_predicate, _endpoint), role in resources["event_role_catalog"].items()
            if catalog_predicate == predicate
        }
        return prediction in allowed
    return False


def constraint_gate_source(task: str, method_id: str) -> str:
    gates = {
        "entity_type": "TYPE_FAMILY membership + entity_model_contraindication",
        "relation_semantic": "research_relation_contract domain/range",
        "time_role": "time-role vocabulary + endpoint type compatibility",
        "space_role": "space-role vocabulary + endpoint type compatibility",
        "time_owner": "owner must be one of the frozen endpoint candidates",
        "space_owner": "owner must be one of the frozen endpoint candidates",
        "event_role": "research_event_role_catalog predicate-role membership",
    }
    base = gates.get(task, "unsupported")
    if method_id == "M6_full_v2_replay":
        return base + " + frozen semantic_status=auto_accepted + risk_tier in {A,B}"
    return base


def full_replay_metadata(sample: dict[str, str], resources: dict[str, Any]) -> dict[str, Any]:
    store = resources["full_entity"] if sample["task_type"] == "entity_type" else resources["full_assertion"]
    return dict(store.get(sample["item_id"]) or {})


def macro_f1(rows: list[dict[str, Any]], include_abstention: bool) -> float | None:
    if not rows:
        return None
    pairs = []
    for row in rows:
        prediction = str(row["prediction"] or "__ABSTAIN__")
        if not include_abstention and not row["prediction"]:
            continue
        pairs.append((prediction, str(row["gold_label"])))
    if not pairs:
        return None
    labels = sorted({value for pair in pairs for value in pair if value != "__ABSTAIN__"})
    values = []
    for label in labels:
        tp = sum(pred == gold == label for pred, gold in pairs)
        fp = sum(pred == label and gold != label for pred, gold in pairs)
        fn = sum(pred != label and gold == label for pred, gold in pairs)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        values.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(values) / len(values) if values else None


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    low = float(beta.ppf(alpha / 2, k, n - k + 1)) if k else 0.0
    high = float(beta.ppf(1 - alpha / 2, k + 1, n - k)) if k < n else 1.0
    return low, high


def evaluation_eligibility(task: str) -> str:
    if task in OWNER_PROXY_TASKS:
        return "evaluation_ineligible_for_primary_owner_shared_proxy"
    if task == "__ALL_REFERENCE_TASKS__":
        return "audit_only_includes_owner_shared_proxy"
    if task == "__CORE_ELIGIBLE_TASKS__":
        return "core_eligible_excludes_owner_proxy"
    return "core_eligible_task"


def metric_row(method: dict[str, Any], task: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    available = [row for row in rows if row["availability_status"] != "not_available"]
    covered = [row for row in available if row["covered"]]
    correct = sum(int(row["correct"]) for row in covered)
    safe = sum(int(row["safe_correct"]) for row in covered)
    errors = len(covered) - correct
    low, high = clopper_pearson(correct, len(covered))
    n = len(rows)
    eligibility = evaluation_eligibility(task)
    primary_eligible = bool(
        method["primary_comparison_eligible"]
        and eligibility in {"core_eligible_task", "core_eligible_excludes_owner_proxy"}
    )
    return {
        "method_id": method["method_id"],
        "method_name": method["method_name"],
        "task_type": task,
        "evidence_class": method["evidence_class"],
        "comparison_tier": method["comparison_tier"],
        "overlap_status": method["overlap_status"],
        "primary_comparison_eligible": int(primary_eligible),
        "evaluation_eligibility": eligibility,
        "n_test": n,
        "n_method_available": len(available),
        "n_covered": len(covered),
        "n_correct": correct,
        "n_error": errors,
        "n_safe_correct": safe,
        "availability_rate": round(len(available) / n, 6) if n else None,
        "coverage": round(len(covered) / n, 6) if n else None,
        "accuracy_full_denominator": round(correct / n, 6) if n else None,
        "accuracy_on_covered": round(correct / len(covered), 6) if covered else None,
        "selective_risk": round(errors / len(covered), 6) if covered else None,
        "safe_coverage": round(safe / n, 6) if n else None,
        "macro_f1_full_denominator": (
            None if (value := macro_f1(rows, include_abstention=True)) is None else round(value, 6)
        ),
        "macro_f1_on_covered": (
            None if (value := macro_f1(covered, include_abstention=False)) is None else round(value, 6)
        ),
        "accuracy_on_covered_ci95_low": None if low is None else round(low, 6),
        "accuracy_on_covered_ci95_high": None if high is None else round(high, 6),
        "actual_llm_calls": 0,
    }


def build_runs(
    gold_rows: list[dict[str, str]],
    samples: dict[str, dict[str, str]],
    manifest: dict[str, dict[str, str]],
    classifier: dict[str, tuple[str | None, float | None, str]],
    resources: dict[str, Any],
    cached_llm: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    test_gold = [row for row in gold_rows if manifest[row["sample_id"]]["split"] == "test"]
    runs: list[dict[str, Any]] = []
    for gold in sorted(test_gold, key=lambda row: (row["task_type"], row["sample_id"])):
        sample = samples[gold["sample_id"]]
        rule_pred, rule_conf, rule_note = rule_prediction(sample, resources)
        classifier_pred, classifier_conf, classifier_note = classifier.get(
            gold["sample_id"], (None, None, "not_available_no_classifier_output")
        )
        cached_pred, cached_note = normalize_cached_llm(sample, cached_llm.get(gold["sample_id"]))
        agreement_pred = rule_pred if rule_pred and rule_pred == cached_pred else None
        full_meta = full_replay_metadata(sample, resources)
        candidates = {
            "M1_rule_only": (rule_pred, rule_conf, "available", rule_note, "production deterministic rules"),
            "M2_classifier_only": (
                classifier_pred,
                classifier_conf,
                "available" if classifier_note.startswith("actual_run") else "not_available",
                classifier_note,
                "current classical classifier run",
            ),
            "M3_live_llm_only": (None, None, "not_available", "no live LLM call", "none"),
            "M3_cached_llm_replay": (
                cached_pred,
                None,
                "available" if cached_note == "cached_model_output" else "not_available",
                cached_note,
                str(LLM_PATH),
            ),
            "M4_rule_plus_cached_llm": (
                agreement_pred,
                rule_conf if agreement_pred else None,
                "available" if cached_note == "cached_model_output" else "not_available",
                "rule/cache agreement" if agreement_pred else "rule/cache disagreement or abstention",
                f"production rules + {LLM_PATH}",
            ),
            "M5_no_global_closure": (
                None,
                None,
                "not_available",
                "no per-sample runnable pre-closure configuration",
                "none",
            ),
            "M6_full_v2_replay": (
                sample["v2_label"] or None,
                full_meta.get("confidence"),
                "available",
                f"status={full_meta.get('status','missing')};risk={full_meta.get('risk_tier','missing')}",
                str(SAMPLES_PATH),
            ),
        }
        for method_id, (prediction, confidence, availability, note, source) in candidates.items():
            method = METHOD_BY_ID[method_id]
            eligibility = evaluation_eligibility(gold["task_type"])
            row_primary_eligible = bool(
                method["primary_comparison_eligible"] and eligibility == "core_eligible_task"
            )
            constraint = hard_constraint_pass(sample, prediction, resources)
            if method_id == "M6_full_v2_replay":
                constraint = bool(
                    constraint
                    and full_meta.get("status") == "auto_accepted"
                    and full_meta.get("risk_tier") in {"A", "B"}
                )
            covered = bool(prediction) and availability != "not_available"
            correct = bool(covered and prediction == gold["ai_gold"])
            runs.append(
                {
                    "sample_id": gold["sample_id"],
                    "task_type": gold["task_type"],
                    "item_id": gold["item_id"],
                    "split": "test",
                    "method_id": method_id,
                    "method_name": method["method_name"],
                    "evidence_class": method["evidence_class"],
                    "comparison_tier": method["comparison_tier"],
                    "overlap_status": method["overlap_status"],
                    "primary_comparison_eligible": int(row_primary_eligible),
                    "evaluation_eligibility": eligibility,
                    "availability_status": availability,
                    "gold_label": gold["ai_gold"],
                    "prediction": prediction or "",
                    "confidence": "" if confidence is None else f"{float(confidence):.12f}",
                    "covered": int(covered),
                    "correct": int(correct),
                    "hard_constraint_pass": int(constraint),
                    "constraint_gate_source": constraint_gate_source(gold["task_type"], method_id),
                    "safe_correct": int(correct and constraint),
                    "actual_llm_calls": 0,
                    "source_artifact": source,
                    "note": note,
                }
            )
    return runs


def summarize_metrics(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics = []
    tasks = sorted({str(row["task_type"]) for row in runs})
    for method in METHODS:
        method_rows = [row for row in runs if row["method_id"] == method["method_id"]]
        for task in tasks:
            rows = [row for row in method_rows if row["task_type"] == task]
            if rows:
                metrics.append(metric_row(method, task, rows))
        prefixed = []
        for row in method_rows:
            copy = dict(row)
            copy["gold_label"] = f"{row['task_type']}::{row['gold_label']}"
            copy["prediction"] = (
                f"{row['task_type']}::{row['prediction']}" if row["prediction"] else ""
            )
            prefixed.append(copy)
        if prefixed:
            metrics.append(metric_row(method, "__ALL_REFERENCE_TASKS__", prefixed))
        core_rows = [row for row in prefixed if row["task_type"] not in OWNER_PROXY_TASKS]
        if core_rows:
            metrics.append(metric_row(method, "__CORE_ELIGIBLE_TASKS__", core_rows))
    return metrics


def validate_run_rows(runs: list[dict[str, Any]], test_sample_ids: set[str]) -> None:
    expected_methods = {row["method_id"] for row in METHODS}
    observed_methods = {str(row["method_id"]) for row in runs}
    if observed_methods != expected_methods:
        raise AssertionError("baseline run method registry mismatch")
    for method_id in sorted(expected_methods):
        method_rows = [row for row in runs if row["method_id"] == method_id]
        sample_ids = [str(row["sample_id"]) for row in method_rows]
        if len(sample_ids) != len(set(sample_ids)):
            raise AssertionError(f"duplicate sample rows for {method_id}")
        if set(sample_ids) != test_sample_ids:
            raise AssertionError(f"test denominator/sample alignment drift for {method_id}")
    forbidden = {str(GOLD_PATH.resolve()).lower(), GOLD_PATH.name.lower()}
    for row in runs:
        source = str(row.get("source_artifact") or "").lower()
        if any(value in source for value in forbidden):
            raise AssertionError("AI gold cannot be used as a prediction source artifact")


def rejects_run_canary(runs: list[dict[str, Any]], test_sample_ids: set[str], kind: str) -> bool:
    mutated = [dict(row) for row in runs]
    if kind == "sample_misalignment":
        mutated[0]["sample_id"] = "CANARY-MISALIGNED-SAMPLE"
    elif kind == "denominator_drift":
        mutated.pop(0)
    elif kind == "direct_gold_source":
        mutated[0]["source_artifact"] = str(GOLD_PATH.resolve())
    else:
        raise ValueError(kind)
    try:
        validate_run_rows(mutated, test_sample_ids)
    except AssertionError:
        return True
    return False


def output_record(path: Path, row_count: int | None = None) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "row_count": row_count,
    }


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    protected_inputs = [GOLD_PATH, FINAL_DB, SEMANTIC_DB]
    hashes_before = {str(path): sha256_file(path) for path in protected_inputs}
    with ro_connect(FINAL_DB) as con:
        final_quick_check = str(con.execute("pragma quick_check").fetchone()[0])
    with ro_connect(SEMANTIC_DB) as con:
        semantic_quick_check = str(con.execute("pragma quick_check").fetchone()[0])
    role_owner_audit = json.loads(ROLE_OWNER_AUDIT.read_text(encoding="utf-8"))
    if not role_owner_audit.get("ok") or not role_owner_audit.get("checks", {}).get(
        "paired_triple_marked_ineligible"
    ):
        raise AssertionError("role-owner audit must mark paired owner references evaluation-ineligible")

    gold_rows = read_csv(GOLD_PATH)
    sample_rows = read_csv(SAMPLES_PATH)
    samples = {row["sample_id"]: row for row in sample_rows}
    if len(gold_rows) != 712 or len({row["sample_id"] for row in gold_rows}) != 712:
        raise AssertionError("AI gold must remain 712 unique samples")
    missing_samples = sorted({row["sample_id"] for row in gold_rows} - set(samples))
    if missing_samples:
        raise AssertionError(f"gold rows missing controlled samples: {missing_samples[:5]}")

    manifest_rows = build_split_manifest(gold_rows, samples)
    manifest = {row["sample_id"]: row for row in manifest_rows}
    classifier, classifier_meta = classifier_predictions(gold_rows, samples, manifest)
    resources = build_rule_resources(gold_rows)
    cached_llm = {row["sample_id"]: row for row in read_csv(LLM_PATH)}
    runs = build_runs(gold_rows, samples, manifest, classifier, resources, cached_llm)
    test_sample_ids = {row["sample_id"] for row in manifest_rows if row["split"] == "test"}
    validate_run_rows(runs, test_sample_ids)
    metrics = summarize_metrics(runs)

    split_path = OUTDIR / "BASELINE_SPLIT_MANIFEST.csv"
    runs_path = OUTDIR / "BASELINE_RUNS.csv"
    metrics_path = OUTDIR / "BASELINE_METRICS.csv"
    actual_path = OUTDIR / "ACTUAL_RUN_BASELINE_METRICS.csv"
    replay_path = OUTDIR / "REPLAY_AND_CACHED_BASELINE_METRICS.csv"
    availability_path = OUTDIR / "BASELINE_AVAILABILITY.csv"
    summary_path = OUTDIR / "baseline_experiment_summary.json"
    audit_path = OUTDIR / "baseline_experiment_audit.json"
    report_path = OUTDIR / "BASELINE_EXPERIMENT_REPORT.md"

    split_fields = ["sample_id", "task_type", "item_id", "model_target", "split", "split_seed"]
    run_fields = [
        "sample_id",
        "task_type",
        "item_id",
        "split",
        "method_id",
        "method_name",
        "evidence_class",
        "comparison_tier",
        "overlap_status",
        "primary_comparison_eligible",
        "evaluation_eligibility",
        "availability_status",
        "gold_label",
        "prediction",
        "confidence",
        "covered",
        "correct",
        "hard_constraint_pass",
        "constraint_gate_source",
        "safe_correct",
        "actual_llm_calls",
        "source_artifact",
        "note",
    ]
    metric_fields = list(metrics[0].keys())
    availability_fields = [
        "method_id",
        "method_name",
        "availability",
        "evidence_class",
        "comparison_tier",
        "overlap_status",
        "primary_comparison_eligible",
        "reason",
    ]
    write_csv(split_path, manifest_rows, split_fields)
    write_csv(runs_path, runs, run_fields)
    write_csv(metrics_path, metrics, metric_fields)
    write_csv(actual_path, [row for row in metrics if row["evidence_class"] == "actual_run"], metric_fields)
    write_csv(
        replay_path,
        [row for row in metrics if row["evidence_class"] in {"deterministic_replay", "cached_model_output"}],
        metric_fields,
    )
    write_csv(availability_path, METHODS, availability_fields)

    split_counts = Counter((row["task_type"], row["split"]) for row in manifest_rows)
    test_counts = dict(sorted(Counter(row["task_type"] for row in manifest_rows if row["split"] == "test").items()))
    legacy_rows = read_csv(LEGACY_BASELINE_PATH)
    legacy_not_run = sum(row.get("value") == "NOT_RUN" for row in legacy_rows)
    existing_classifier_db = ROOT / "derived/stkg_v2_entity_classifier.sqlite"
    existing_overlap = {"validation": 0, "pending": 0}
    if existing_classifier_db.exists():
        entity_gold_ids = [row["item_id"] for row in gold_rows if row["task_type"] == "entity_type"]
        placeholders = ",".join("?" for _ in entity_gold_ids)
        with ro_connect(existing_classifier_db) as con:
            existing_overlap["validation"] = int(
                con.execute(
                    f"select count(*) from validation_predictions where entity_id in ({placeholders})",
                    entity_gold_ids,
                ).fetchone()[0]
            )
            existing_overlap["pending"] = int(
                con.execute(
                    f"select count(*) from entity_predictions where entity_id in ({placeholders})",
                    entity_gold_ids,
                ).fetchone()[0]
            )

    summary = {
        "generated_at": utc_now(),
        "result": "PASS",
        "scope": "fixed held-out evaluation of Rule-only and classical Classifier-only, plus separately labeled frozen/cached replays",
        "gold": {
            "path": str(GOLD_PATH),
            "sha256": hashes_before[str(GOLD_PATH)],
            "rows": len(gold_rows),
            "task_counts": dict(sorted(Counter(row["task_type"] for row in gold_rows).items())),
            "unchanged": True,
        },
        "split": {
            "seed": SPLIT_SEED,
            "policy": "label-stratified 60/20/20 where possible; singleton labels train-only; every test label appears in fit pool",
            "counts": {f"{task}:{split}": count for (task, split), count in sorted(split_counts.items())},
            "test_counts": test_counts,
            "test_total": sum(test_counts.values()),
        },
        "classifier": classifier_meta,
        "role_owner_applicability_dependency": {
            "path": str(ROLE_OWNER_AUDIT),
            "sha256": sha256_file(ROLE_OWNER_AUDIT),
            "paired_owner_reference_is_schema_incompatible": role_owner_audit["checks"][
                "paired_owner_reference_is_schema_incompatible"
            ],
            "paired_triple_marked_ineligible": role_owner_audit["checks"][
                "paired_triple_marked_ineligible"
            ],
        },
        "methods": METHODS,
        "metrics": metrics,
        "actual_llm_calls": 0,
        "interpretation_rules": [
            "M1 shares deterministic rule channels with the AI gold and is diagnostic only.",
            "M3 cached and M4 share historical LLM/rule channels with the AI gold and cannot support an independent ranking.",
            "M6 is a deterministic replay with shared system signals, not a new end-to-end run or a label-independent baseline.",
            "M2 is a held-out supervised proxy benchmark: test samples are disjoint, but the target remains the current AI gold.",
            "safe_correct requires both gold agreement and the task-specific structural gate recorded in constraint_gate_source.",
            "time_owner and space_owner remain shared-proxy diagnostics and are excluded from __CORE_ELIGIBLE_TASKS__.",
        ],
    }
    write_json(summary_path, summary)

    hashes_after = {str(path): sha256_file(path) for path in protected_inputs}
    output_records = {
        "split_manifest": output_record(split_path, len(manifest_rows)),
        "runs": output_record(runs_path, len(runs)),
        "metrics": output_record(metrics_path, len(metrics)),
        "actual_metrics": output_record(actual_path, sum(row["evidence_class"] == "actual_run" for row in metrics)),
        "replay_metrics": output_record(
            replay_path,
            sum(row["evidence_class"] in {"deterministic_replay", "cached_model_output"} for row in metrics),
        ),
        "availability": output_record(availability_path, len(METHODS)),
        "summary": output_record(summary_path),
    }
    metric_lookup = {(row["method_id"], row["task_type"]): row for row in metrics}
    core_denominators = {
        int(metric_lookup[(method["method_id"], "__CORE_ELIGIBLE_TASKS__")]["n_test"])
        for method in METHODS
    }
    reference_denominators = {
        int(metric_lookup[(method["method_id"], "__ALL_REFERENCE_TASKS__")]["n_test"])
        for method in METHODS
    }
    canaries = {
        "gold_row_count_712": len(gold_rows) == 712,
        "gold_unique_sample_ids_712": len({row["sample_id"] for row in gold_rows}) == 712,
        "all_gold_samples_joined": not missing_samples,
        "test_denominator_equal_per_method": len({sum(row["method_id"] == method["method_id"] for row in runs) for method in METHODS}) == 1,
        "classifier_features_exclude_v2_label_key": all(
            "v2_label=" not in feature_text(samples[row["sample_id"]]) for row in gold_rows
        ),
        "classifier_features_exclude_ai_gold_key": all(
            "ai_gold=" not in feature_text(samples[row["sample_id"]]) for row in gold_rows
        ),
        "entity_classifier_excludes_source_type_gold_channel": all(
            "source_type=" not in feature_text(samples[row["sample_id"]])
            for row in gold_rows
            if row["task_type"] == "entity_type"
        ),
        "relation_classifier_excludes_predicate_target_channel": all(
            "predicate=" not in feature_text(samples[row["sample_id"]])
            for row in gold_rows
            if row["task_type"] == "relation_semantic"
        ),
        "no_live_llm_calls": all(int(row["actual_llm_calls"]) == 0 for row in runs),
        "cached_llm_overlap_flagged": METHOD_BY_ID["M3_cached_llm_replay"]["overlap_status"] == "shared_gold_llm_channel",
        "rule_overlap_flagged": METHOD_BY_ID["M1_rule_only"]["overlap_status"] == "shared_gold_rule_channel",
        "full_replay_shared_system_signal_flagged": METHOD_BY_ID["M6_full_v2_replay"]["overlap_status"] == "shared_system_signal",
        "full_replay_not_primary_comparison_eligible": not METHOD_BY_ID["M6_full_v2_replay"]["primary_comparison_eligible"],
        "safe_correct_requires_constraint_gate": all(
            not int(row["safe_correct"]) or int(row["hard_constraint_pass"]) for row in runs
        ),
        "constraint_gate_source_recorded": all(bool(row["constraint_gate_source"]) for row in runs),
        "owner_rows_marked_primary_ineligible": all(
            row["evaluation_eligibility"]
            == "evaluation_ineligible_for_primary_owner_shared_proxy"
            and int(row["primary_comparison_eligible"]) == 0
            for row in runs
            if row["task_type"] in OWNER_PROXY_TASKS
        ),
        "core_summary_excludes_owner_proxy": core_denominators == {152},
        "all_reference_summary_retained_for_audit": reference_denominators == {159},
        "owner_metric_rows_marked_ineligible": all(
            row["evaluation_eligibility"]
            == "evaluation_ineligible_for_primary_owner_shared_proxy"
            and int(row["primary_comparison_eligible"]) == 0
            for row in metrics
            if row["task_type"] in OWNER_PROXY_TASKS
        ),
        "role_owner_audit_dependency_pass": bool(
            role_owner_audit.get("ok")
            and role_owner_audit["checks"]["paired_owner_reference_is_schema_incompatible"]
            and role_owner_audit["checks"]["paired_triple_marked_ineligible"]
        ),
        "negative_canary_rejects_sample_misalignment": rejects_run_canary(
            runs, test_sample_ids, "sample_misalignment"
        ),
        "negative_canary_rejects_denominator_drift": rejects_run_canary(
            runs, test_sample_ids, "denominator_drift"
        ),
        "negative_canary_rejects_direct_gold_source": rejects_run_canary(
            runs, test_sample_ids, "direct_gold_source"
        ),
        "not_run_scenarios_excluded_from_actual": legacy_not_run > 0,
        "protected_inputs_unchanged": hashes_before == hashes_after,
        "final_db_quick_check": final_quick_check == "ok",
        "semantic_db_quick_check": semantic_quick_check == "ok",
    }
    audit = {
        "generated_at": utc_now(),
        "result": "PASS" if all(canaries.values()) else "FAIL",
        "evidence_contract": str(EVIDENCE_CONTRACT),
        "protected_inputs": {
            str(path): {
                "sha256_before": hashes_before[str(path)],
                "sha256_after": hashes_after[str(path)],
                "unchanged": hashes_before[str(path)] == hashes_after[str(path)],
            }
            for path in protected_inputs
        },
        "database_quick_checks": {"final": final_quick_check, "semantic": semantic_quick_check},
        "existing_artifact_audit": {
            "saved_classifier_gold_overlap": existing_overlap,
            "saved_classifier_decision": "not used as the primary 203-row classifier test because only 36 gold entities are historical validation rows and 5 are historical pending predictions",
            "cached_llm_rows": len(cached_llm),
            "cached_llm_decision": "replayed only as cached_model_output/shared_gold_channel",
            "legacy_baseline_estimate_rows": len(legacy_rows),
            "legacy_NOT_RUN_rows": legacy_not_run,
            "legacy_decision": "excluded from actual-run metrics",
            "role_owner_audit_path": str(ROLE_OWNER_AUDIT),
            "role_owner_audit_sha256": sha256_file(ROLE_OWNER_AUDIT),
            "owner_applicability_decision": "time_owner and space_owner are shared-proxy diagnostics excluded from __CORE_ELIGIBLE_TASKS__",
        },
        "canaries": canaries,
        "outputs": output_records,
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "scikit_learn": sklearn.__version__,
            "random_state": RANDOM_STATE,
            "split_seed": SPLIT_SEED,
        },
        "not_available": [
            {"method_id": row["method_id"], "reason": row["reason"]}
            for row in METHODS
            if row["availability"] == "not_available"
        ],
    }
    write_json(audit_path, audit)
    if audit["result"] != "PASS":
        raise AssertionError(f"baseline audit failed: {canaries}")

    report_lines = [
        "# Paper A baseline experiment report",
        "",
        f"- Result: **{audit['result']}**",
        f"- Frozen AI ensemble gold: {len(gold_rows)} rows; SHA-256 `{hashes_before[str(GOLD_PATH)]}`",
        f"- Fixed test set: {sum(test_counts.values())} rows; split seed `{SPLIT_SEED}`",
        "- Core eligible aggregate: 152 rows; excludes 4 time-owner and 3 space-owner shared-proxy test rows.",
        "- All-reference audit aggregate: 159 rows; retained only for traceability.",
        "- Live LLM calls in this run: **0**",
        "- Protected database hashes before/after: unchanged",
        "",
        "## Evidence separation",
        "",
        "- `M1_rule_only`: current deterministic run, but it shares a rule channel with the AI gold; diagnostic only.",
        "- `M2_classifier_only`: held-out supervised proxy benchmark. Test samples do not enter fitting, but the target is still the current AI gold and is not label-independent factual evidence.",
        "- `M3_cached_llm_replay` and `M4_rule_plus_cached_llm`: cached shared-gold-channel diagnostics; not independent accuracy evidence.",
        "- `M6_full_v2_replay`: deterministic frozen-output replay with shared system signals; listed separately from actual runs.",
        "- `safe_correct`: counted only when the prediction matches gold and passes the recorded task-specific structural gate; Full replay additionally requires frozen `auto_accepted` status and risk tier A/B.",
        "- `time_owner` and `space_owner`: marked `evaluation_ineligible_for_primary_owner_shared_proxy` after the dedicated role-owner audit; excluded from `__CORE_ELIGIBLE_TASKS__`.",
        "- Live `LLM-only` and the no-global-closure configuration remain `not_available` because no valid per-sample run exists.",
        "",
        "## Existing evidence audit",
        "",
        f"- Saved entity-classifier overlap with the 203 gold entity rows: {existing_overlap['validation']} historical validation and {existing_overlap['pending']} historical pending predictions.",
        f"- Legacy baseline table contains {legacy_not_run} `NOT_RUN` rows; none was promoted to a measured baseline.",
        "",
        "## Output files",
        "",
        *[f"- `{record['path']}`" for record in output_records.values()],
    ]
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "result": audit["result"],
                "gold_rows": len(gold_rows),
                "test_rows": sum(test_counts.values()),
                "baseline_run_rows": len(runs),
                "metric_rows": len(metrics),
                "actual_llm_calls": 0,
                "protected_inputs_unchanged": hashes_before == hashes_after,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
