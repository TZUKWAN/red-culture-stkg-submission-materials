#!/usr/bin/env python3
"""Benchmark the executable local Paper A pipeline at five frozen scales.

Each of 10/25/50/75/100 percent is measured five times in a deterministic
Latin-square order.  The timed deterministic path includes source reads,
rule/label execution, feature vectorization, the saved local non-LLM
classifier, identity projection, relation contract, role-owner closure,
provenance gate, admission, aggregation, and consistency checks.

Historical model-output replay is timed separately as ``cached_model_output``.
No online LLM is called; an explicit ``not_available`` record prevents cache
I/O from being described as model-inference latency.
"""

from __future__ import annotations

import gc
import hashlib
import json
import math
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import joblib
import numpy as np
import psutil
from scipy.sparse import hstack


HERE = Path(__file__).resolve().parent
ABLATION_DIR = HERE.parent / "05_ablation"
if str(ABLATION_DIR) not in sys.path:
    sys.path.insert(0, str(ABLATION_DIR))

from frozen_v2_replay import (  # noqa: E402
    CLASSIFIER_MODEL,
    FINAL_V2,
    RELATIONS,
    RESEARCH_BASE,
    SEMANTIC_V2,
    assert_hashes_unchanged,
    clean_token,
    connect_ro,
    fingerprint_ids,
    refine_lexical_hint,
    relation_token,
    sha256_file,
    source_hashes,
    strong_entity_type_hint,
    write_csv,
    write_json,
)


SCALES = (10, 25, 50, 75, 100)
REPEATS = 5
RUNS = HERE / "END_TO_END_RUNS.csv"
SUMMARY_CSV = HERE / "END_TO_END_SUMMARY.csv"
SUMMARY_JSON = HERE / "end_to_end_efficiency_summary.json"
AUDIT_JSON = HERE / "end_to_end_efficiency_audit.json"
FIGURE_DATA = HERE / "END_TO_END_FIGURE_DATA.csv"
SCALING_FITS = HERE / "SCALING_FITS.csv"
MANIFEST = HERE / "EFFICIENCY_SAMPLE_MANIFEST.json"


class AssertionInput(NamedTuple):
    fact_id: str
    source_subject_id: str
    source_object_id: str
    source_subject_type: str
    source_object_type: str
    predicate: str
    time_start: str | None
    canonical_anchor_id: str | None
    semantic_status: str
    risk_tier: str
    subject_id: str
    object_id: str
    subject_type: str
    object_type: str
    subject_validation: str
    object_validation: str
    provenance_count: int
    release_tier: str


class PeakMemoryMonitor:
    def __init__(self, interval: float = 0.01):
        self.interval = interval
        self.process = psutil.Process()
        self.peak = self.process.memory_info().rss
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self.stop_event.wait(self.interval):
            self.peak = max(self.peak, self.process.memory_info().rss)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop_event.set()
        self.thread.join(timeout=1)
        self.peak = max(self.peak, self.process.memory_info().rss)


def timed(callable_):
    started = time.perf_counter()
    value = callable_()
    return value, time.perf_counter() - started


def stable_digest(values) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(str(value).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def population_counts() -> tuple[int, int, int]:
    with connect_ro(SEMANTIC_V2) as con:
        assertions = int(con.execute("select count(*) from v2_assertion_scopes").fetchone()[0])
        entities = int(con.execute("select count(*) from v2_entities").fetchone()[0])
        decisions = int(con.execute("select count(*) from v2_model_decisions").fetchone()[0])
    return assertions, entities, decisions


def scale_count(total: int, percent: int) -> int:
    return max(1, int(total * percent / 100))


def build_sample_manifest(total_assertions: int, total_entities: int, total_decisions: int, hashes: dict) -> dict:
    scales = {}
    con = connect_ro(SEMANTIC_V2)
    try:
        for percent in SCALES:
            assertion_count = scale_count(total_assertions, percent)
            entity_count = scale_count(total_entities, percent)
            decision_count = scale_count(total_decisions, percent)
            assertion_ids = [
                str(row[0]) for row in con.execute(
                    "select fact_id from v2_assertion_scopes order by fact_id limit ?", (assertion_count,)
                )
            ]
            entity_ids = [
                str(row[0]) for row in con.execute(
                    "select entity_id from v2_entities order by entity_id limit ?", (entity_count,)
                )
            ]
            decision_ids = [
                str(row[0]) for row in con.execute(
                    "select decision_id from v2_model_decisions order by decision_id limit ?", (decision_count,)
                )
            ]
            scales[str(percent)] = {
                "assertions": assertion_count,
                "entities": entity_count,
                "cached_model_decisions": decision_count,
                "assertion_id_sha256": fingerprint_ids(assertion_ids),
                "entity_id_sha256": fingerprint_ids(entity_ids),
                "decision_id_sha256": fingerprint_ids(decision_ids),
                "sampling": "stable ID ascending prefix",
            }
    finally:
        con.close()
    schedule = {
        str(repeat + 1): [SCALES[(position + repeat) % len(SCALES)] for position in range(len(SCALES))]
        for repeat in range(REPEATS)
    }
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "protected_source_hashes": hashes,
        "population": {
            "assertions": total_assertions,
            "entities": total_entities,
            "cached_model_decisions": total_decisions,
        },
        "scales": scales,
        "repeats_per_scale": REPEATS,
        "execution_schedule_latin_square": schedule,
        "cache_condition": "warm process; operating-system cache not forcibly reset",
        "online_llm": "not executed",
    }


def read_raw_inputs(assertion_count: int, entity_count: int):
    con = connect_ro(SEMANTIC_V2)
    try:
        entity_rows = [dict(row) for row in con.execute(
            "select entity_id,canonical_name,source_entity_type,aliases_json "
            "from v2_entities order by entity_id limit ?", (entity_count,)
        )]
        con.execute("create temp table selected_entities(entity_id text primary key) without rowid")
        con.executemany(
            "insert into selected_entities values(?)",
            [(str(row["entity_id"]),) for row in entity_rows],
        )
        edges = [
            (str(row[0]), str(row[1]), str(row[2]), str(row[3]))
            for row in con.execute(
                "select a.subject_id,'OUT',a.predicate,n.effective_entity_type "
                "from v2_assertion_scopes a join selected_entities s on s.entity_id=a.subject_id "
                "join v2_entity_type_effective n on n.entity_id=a.object_id "
                "union all "
                "select a.object_id,'IN',a.predicate,n.effective_entity_type "
                "from v2_assertion_scopes a join selected_entities s on s.entity_id=a.object_id "
                "join v2_entity_type_effective n on n.entity_id=a.subject_id"
            )
        ]
        assertion_rows = [dict(row) for row in con.execute(
            "select a.fact_id,a.subject_id source_subject_id,a.object_id source_object_id,"
            "es.effective_entity_type source_subject_type,eo.effective_entity_type source_object_type,"
            "a.predicate,a.time_start,sp.canonical_anchor_id,a.semantic_status,a.risk_tier,"
            "ms.canonical_entity_id subject_id,mo.canonical_entity_id object_id,"
            "ms.canonical_entity_type subject_type,mo.canonical_entity_type object_type,"
            "es.type_validation_status subject_validation,eo.type_validation_status object_validation "
            "from v2_assertion_scopes a "
            "join v2_entity_type_effective es on es.entity_id=a.subject_id "
            "join v2_entity_type_effective eo on eo.entity_id=a.object_id "
            "join v2_entity_identity_map ms on ms.source_entity_id=a.subject_id "
            "join v2_entity_identity_map mo on mo.source_entity_id=a.object_id "
            "join v2_spatial_projection sp on sp.fact_id=a.fact_id "
            "order by a.fact_id limit ?", (assertion_count,)
        )]
    finally:
        con.close()

    final = connect_ro(FINAL_V2)
    try:
        final.execute("create temp table selected_facts(fact_id text primary key) without rowid")
        final.executemany(
            "insert into selected_facts values(?)",
            [(str(row["fact_id"]),) for row in assertion_rows],
        )
        release = {
            str(row["fact_id"]): (int(row["provenance_count"]), str(row["research_tier"]))
            for row in final.execute(
                "select s.fact_id,count(p.provenance_id) provenance_count,r.research_tier "
                "from selected_facts s join research_assertions r on r.fact_id=s.fact_id "
                "left join research_assertion_provenance p on p.fact_id=s.fact_id "
                "group by s.fact_id,r.research_tier"
            )
        }
    finally:
        final.close()

    assertions = []
    for row in assertion_rows:
        fact_id = str(row["fact_id"])
        provenance_count, release_tier = release[fact_id]
        assertions.append(AssertionInput(
            fact_id=fact_id,
            source_subject_id=str(row["source_subject_id"]),
            source_object_id=str(row["source_object_id"]),
            source_subject_type=str(row["source_subject_type"]),
            source_object_type=str(row["source_object_type"]),
            predicate=str(row["predicate"]),
            time_start=row["time_start"],
            canonical_anchor_id=row["canonical_anchor_id"],
            semantic_status=str(row["semantic_status"]),
            risk_tier=str(row["risk_tier"]),
            subject_id=str(row["subject_id"]),
            object_id=str(row["object_id"]),
            subject_type=str(row["subject_type"]),
            object_type=str(row["object_type"]),
            subject_validation=str(row["subject_validation"]),
            object_validation=str(row["object_validation"]),
            provenance_count=provenance_count,
            release_tier=release_tier,
        ))
    return entity_rows, edges, assertions


def run_rule_label(entity_rows: list[dict], edges: list[tuple], assertions: list[AssertionInput]):
    contexts: dict[str, Counter[str]] = defaultdict(Counter)
    schema_votes: dict[str, Counter[str]] = defaultdict(Counter)
    for entity_id, direction, predicate, neighbor_type in edges:
        contexts[entity_id][relation_token(direction, predicate, neighbor_type)] += 1
        relation = RELATIONS.get(predicate)
        if relation is None or predicate.startswith("raw:"):
            continue
        allowed = relation.source_types if direction == "OUT" else relation.target_types
        if len(allowed) == 1:
            schema_votes[entity_id][next(iter(allowed))] += 1
    model_inputs = []
    for row in entity_rows:
        entity_id = str(row["entity_id"])
        name = str(row["canonical_name"])
        source_type = str(row["source_entity_type"])
        aliases = [str(value) for value in json.loads(row["aliases_json"] or "[]") if str(value).strip()]
        lexical = refine_lexical_hint(name, source_type, strong_entity_type_hint(name)) or None
        votes = schema_votes.get(entity_id, Counter())
        model_inputs.append({
            "entity_id": entity_id,
            "name_text": " ".join([name, *aliases]),
            "context_text": " ".join(token for token, _ in contexts.get(entity_id, Counter()).most_common(80)),
            "lexical_hint": lexical,
            "schema_top_type": votes.most_common(1)[0][0] if votes else None,
        })
    scopes = []
    for row in assertions:
        time_label = RESEARCH_BASE.classify_time_scope(
            row.predicate, row.time_start, row.source_subject_id, row.source_subject_type,
            row.source_object_id, row.source_object_type,
        )
        space_label = RESEARCH_BASE.classify_space_scope(
            row.predicate, row.canonical_anchor_id, row.source_subject_id, row.source_subject_type,
            row.source_object_id, row.source_object_type,
        )
        scopes.append((time_label.role, time_label.owner_id, space_label.role, space_label.owner_id))
    digest = stable_digest(
        f"{row['entity_id']}|{row['lexical_hint']}|{row['schema_top_type']}" for row in model_inputs
    )
    return model_inputs, scopes, digest


def vectorize(bundle: dict, model_inputs: list[dict]):
    names = bundle["name_vectorizer"].transform([row["name_text"] for row in model_inputs])
    contexts = bundle["context_vectorizer"].transform([row["context_text"] for row in model_inputs])
    return hstack([names, contexts], format="csr", dtype=np.float32)


def infer(bundle: dict, features):
    probabilities = bundle["classifier"].predict_proba(features)
    indices = np.argmax(probabilities, axis=1)
    predictions = bundle["classifier"].classes_[indices]
    confidence = probabilities[np.arange(len(indices)), indices]
    digest = stable_digest(f"{pred}|{float(conf):.9f}" for pred, conf in zip(predictions, confidence))
    return predictions, confidence, digest


def project_identity(assertions: list[AssertionInput], scopes: list[tuple]):
    projected = []
    for row, scope in zip(assertions, scopes):
        time_role, source_time_owner, space_role, source_space_owner = scope
        time_owner = (
            row.subject_id if source_time_owner == row.source_subject_id
            else row.object_id if source_time_owner == row.source_object_id
            else None
        )
        space_owner = (
            row.subject_id if source_space_owner == row.source_subject_id
            else row.object_id if source_space_owner == row.source_object_id
            else None
        )
        projected.append((
            row.subject_id, row.object_id, row.subject_type, row.object_type,
            time_role, time_owner, space_role, space_owner,
        ))
    return projected, stable_digest(
        f"{row.fact_id}|{state[0]}|{state[1]}" for row, state in zip(assertions, projected)
    )


def contract_stage(assertions: list[AssertionInput], projected: list[tuple]):
    passes = [
        RESEARCH_BASE.relation_domain_range_pass_v2(row.predicate, state[2], state[3])
        for row, state in zip(assertions, projected)
    ]
    return passes, stable_digest(int(value) for value in passes)


def role_owner_stage(assertions: list[AssertionInput], projected: list[tuple]):
    closed = []
    for row, state in zip(assertions, projected):
        subject_id, object_id, subject_type, object_type, time_role, time_owner, space_role, space_owner = state
        final_time = RESEARCH_BASE.close_time_scope_after_identity(
            time_role, time_owner, row.predicate, row.time_start,
            subject_id, subject_type, object_id, object_type,
        )
        final_space = RESEARCH_BASE.close_space_scope_after_identity(
            space_role, space_owner, row.predicate, row.canonical_anchor_id,
            subject_id, subject_type, object_id, object_type,
        )
        closed.append((final_time[0], final_time[1], final_space[0], final_space[1]))
    return closed, stable_digest(
        f"{row.fact_id}|{scope[0]}|{scope[1]}|{scope[2]}|{scope[3]}"
        for row, scope in zip(assertions, closed)
    )


def provenance_stage(assertions: list[AssertionInput]):
    passes = [row.provenance_count > 0 for row in assertions]
    return passes, stable_digest(int(value) for value in passes)


def admission_stage(assertions: list[AssertionInput], contract: list[bool], provenance: list[bool]):
    tiers = []
    for row, contract_pass, provenance_pass in zip(assertions, contract, provenance):
        route_pass = row.semantic_status == "auto_accepted"
        strict = (
            route_pass
            and not row.predicate.startswith("raw:")
            and row.subject_validation == "validated"
            and row.object_validation == "validated"
            and contract_pass
            and provenance_pass
        )
        tiers.append("strict_semantic" if strict else ("contextual" if route_pass else "unresolved"))
    return tiers, stable_digest(tiers)


def aggregate_stage(predictions, tiers: list[str], closed: list[tuple]):
    payload = {
        "predicted_types": dict(sorted(Counter(str(value) for value in predictions).items())),
        "tiers": dict(sorted(Counter(tiers).items())),
        "time_roles": dict(sorted(Counter(value[0] for value in closed).items())),
        "space_roles": dict(sorted(Counter(value[2] for value in closed).items())),
    }
    return payload, hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def required_owner_valid(role: str, owner_id: str | None, row: AssertionInput, kind: str) -> bool:
    required = {
        "time": {
            "event_occurrence": {"Event"},
            "biographical": {"Person"},
            "creation_or_publication": {"CreativeWork", "Document", "Artifact"},
            "source_document_time": {"Document"},
        },
        "space": {
            "event_location": {"Event"},
            "biographical_location": {"Person"},
            "creation_or_publication_location": {"CreativeWork", "Document", "Artifact"},
        },
    }[kind]
    allowed = required.get(role)
    if allowed is None:
        return not (role == "unknown" and owner_id is not None)
    owner_type = row.subject_type if owner_id == row.subject_id else row.object_type if owner_id == row.object_id else None
    return owner_type in allowed


def consistency_stage(
    assertions: list[AssertionInput], contract: list[bool], provenance: list[bool],
    tiers: list[str], closed: list[tuple],
):
    checks = Counter()
    for row, contract_pass, provenance_pass, tier, scope in zip(assertions, contract, provenance, tiers, closed):
        checks["release_tier_mismatch"] += int(tier != row.release_tier)
        checks["strict_contract_violation"] += int(tier == "strict_semantic" and not contract_pass)
        checks["admitted_without_provenance"] += int(tier != "unresolved" and not provenance_pass)
        checks["invalid_time_owner_type"] += int(not required_owner_valid(scope[0], scope[1], row, "time"))
        checks["invalid_space_owner_type"] += int(not required_owner_valid(scope[2], scope[3], row, "space"))
    payload = dict(sorted(checks.items()))
    return payload, hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def cached_model_replay(decision_count: int):
    con = connect_ro(SEMANTIC_V2)
    try:
        parsed = []
        valid = 0
        for row in con.execute(
            "select decision_id,decision_json,validator_pass from v2_model_decisions "
            "order by decision_id limit ?", (decision_count,)
        ):
            decision = json.loads(str(row["decision_json"]))
            parsed.append(f"{row['decision_id']}|{sorted(decision)}|{row['validator_pass']}")
            valid += int(bool(row["validator_pass"]))
    finally:
        con.close()
    return {
        "records": len(parsed),
        "validator_pass": valid,
        "digest": stable_digest(parsed),
    }


def run_one(percent: int, repeat: int, order_position: int, totals: tuple[int, int, int]):
    total_assertions, total_entities, total_decisions = totals
    assertion_count = scale_count(total_assertions, percent)
    entity_count = scale_count(total_entities, percent)
    decision_count = scale_count(total_decisions, percent)
    stage_rows = []
    warm_times = []
    cold_times = []

    def record(
        stage: str,
        elapsed: float | None,
        records: int,
        evidence: str,
        included_warm: bool,
        included_cold: bool,
        digest: str,
        note: str,
    ):
        stage_rows.append({
            "scale_percent": percent,
            "repeat": repeat,
            "order_position": order_position,
            "stage": stage,
            "elapsed_seconds": "" if elapsed is None else f"{elapsed:.9f}",
            "record_count": records,
            "assertion_count": assertion_count,
            "entity_count": entity_count,
            "peak_rss_mb": "",
            "evidence_class": evidence,
            "included_in_warm_total": int(included_warm),
            "included_in_cold_total": int(included_cold),
            "output_digest": digest,
            "note": note,
        })
        if included_warm and elapsed is not None:
            warm_times.append(elapsed)
        if included_cold and elapsed is not None:
            cold_times.append(elapsed)

    with PeakMemoryMonitor() as monitor:
        bundle, elapsed = timed(lambda: joblib.load(CLASSIFIER_MODEL))
        record(
            "model_bundle_load", elapsed, 1, "actual_run", False, True,
            f"{bundle.get('version')}|{sha256_file(CLASSIFIER_MODEL)}",
            "actual per-run model artifact load; excluded from warm-process total and included in cold-start total",
        )

        (entity_rows, edges, assertions), elapsed = timed(lambda: read_raw_inputs(assertion_count, entity_count))
        record(
            "source_read", elapsed, len(entity_rows) + len(edges) + len(assertions), "actual_run", True, True,
            stable_digest([len(entity_rows), len(edges), len(assertions), assertions[0].fact_id, assertions[-1].fact_id]),
            "SQLite mode=ro; includes entity/context/assertion/provenance reads",
        )

        (model_inputs, scopes, digest), elapsed = timed(lambda: run_rule_label(entity_rows, edges, assertions))
        record("rule_label", elapsed, len(assertions) + len(model_inputs), "actual_run", True, True, digest,
               "executes lexical/schema signals and time/space scope rules")

        features, elapsed = timed(lambda: vectorize(bundle, model_inputs))
        record("feature_vectorization", elapsed, features.shape[0], "actual_run", True, True,
               f"shape={features.shape};nnz={features.nnz}", "TF-IDF char and relation-context features")

        (predictions, confidence, digest), elapsed = timed(lambda: infer(bundle, features))
        record("local_classifier_inference", elapsed, len(predictions), "actual_run", True, True, digest,
               "saved local SGD classifier; this is not an LLM")

        (projected, digest), elapsed = timed(lambda: project_identity(assertions, scopes))
        record("identity_projection", elapsed, len(projected), "actual_run", True, True, digest,
               "executes frozen source-to-canonical mapping")

        (contract, digest), elapsed = timed(lambda: contract_stage(assertions, projected))
        record("relation_contract", elapsed, len(contract), "actual_run", True, True, digest,
               "executes hierarchy-aware domain/range contract")

        (closed, digest), elapsed = timed(lambda: role_owner_stage(assertions, projected))
        record("role_owner_closure", elapsed, len(closed), "actual_run", True, True, digest,
               "executes owner revalidation after identity projection")

        (provenance, digest), elapsed = timed(lambda: provenance_stage(assertions))
        record("provenance_gate", elapsed, len(provenance), "actual_run", True, True, digest,
               "checks actual frozen lineage presence")

        (tiers, digest), elapsed = timed(lambda: admission_stage(assertions, contract, provenance))
        record("admission", elapsed, len(tiers), "actual_run", True, True, digest,
               "assigns strict/contextual/unresolved tiers")

        (aggregates, digest), elapsed = timed(lambda: aggregate_stage(predictions, tiers, closed))
        record("aggregation", elapsed, len(tiers), "actual_run", True, True, digest,
               json.dumps(aggregates["tiers"], ensure_ascii=False, sort_keys=True))

        (checks, digest), elapsed = timed(lambda: consistency_stage(assertions, contract, provenance, tiers, closed))
        record("consistency", elapsed, len(tiers), "actual_run", True, True, digest,
               json.dumps(checks, ensure_ascii=False, sort_keys=True))

        cached, elapsed = timed(lambda: cached_model_replay(decision_count))
        record("cached_model_output_replay", elapsed, cached["records"], "cached_model_output", False, False,
               cached["digest"], "historical decision JSON parse only; excluded from deterministic total")

        record("online_llm_inference", None, 0, "not_available", False, False, "",
               "not executed by experiment constraint; no latency reported")

    warm_total = sum(warm_times)
    cold_total = sum(cold_times)
    warm_digest = stable_digest(
        row["output_digest"] for row in stage_rows if row["included_in_warm_total"]
    )
    cold_digest = stable_digest(
        row["output_digest"] for row in stage_rows if row["included_in_cold_total"]
    )
    stage_rows.append({
        "scale_percent": percent,
        "repeat": repeat,
        "order_position": order_position,
        "stage": "warm_process_deterministic_total",
        "elapsed_seconds": f"{warm_total:.9f}",
        "record_count": assertion_count + entity_count,
        "assertion_count": assertion_count,
        "entity_count": entity_count,
        "peak_rss_mb": f"{monitor.peak / 1e6:.3f}",
        "evidence_class": "actual_run",
        "included_in_warm_total": 0,
        "included_in_cold_total": 0,
        "output_digest": warm_digest,
        "note": "sum of actual deterministic stages; cached outputs and online LLM excluded",
    })
    stage_rows.append({
        "scale_percent": percent,
        "repeat": repeat,
        "order_position": order_position,
        "stage": "cold_start_deterministic_total",
        "elapsed_seconds": f"{cold_total:.9f}",
        "record_count": assertion_count + entity_count,
        "assertion_count": assertion_count,
        "entity_count": entity_count,
        "peak_rss_mb": f"{monitor.peak / 1e6:.3f}",
        "evidence_class": "actual_run",
        "included_in_warm_total": 0,
        "included_in_cold_total": 0,
        "output_digest": cold_digest,
        "note": "warm-process deterministic stages plus actual per-run model bundle load; cached outputs and online LLM excluded",
    })

    del entity_rows, edges, assertions, model_inputs, scopes, features, predictions, confidence
    del projected, contract, closed, provenance, tiers, aggregates, checks, cached, bundle
    gc.collect()
    return stage_rows


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), q))


def summarize(run_rows: list[dict]) -> tuple[list[dict], dict, list[dict]]:
    grouped: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for row in run_rows:
        if row["elapsed_seconds"] == "":
            continue
        grouped[(int(row["scale_percent"]), str(row["stage"]))].append(row)
    summary_rows = []
    nested = {}
    for (percent, stage), rows in sorted(grouped.items()):
        values = [float(row["elapsed_seconds"]) for row in rows]
        med = statistics.median(values)
        q1 = percentile(values, 25)
        q3 = percentile(values, 75)
        assertion_count = int(rows[0]["assertion_count"])
        entity_count = int(rows[0]["entity_count"])
        is_total = stage in {"warm_process_deterministic_total", "cold_start_deterministic_total"}
        throughput_assertions = assertion_count / med if med and is_total else None
        throughput_units = (assertion_count + entity_count) / med if med and is_total else None
        peaks = [float(row["peak_rss_mb"]) for row in rows if row["peak_rss_mb"]]
        item = {
            "scale_percent": percent,
            "stage": stage,
            "repeats": len(rows),
            "assertion_count": assertion_count,
            "entity_count": entity_count,
            "median_seconds": med,
            "q1_seconds": q1,
            "q3_seconds": q3,
            "iqr_seconds": q3 - q1,
            "min_seconds": min(values),
            "max_seconds": max(values),
            "mean_seconds": statistics.mean(values),
            "throughput_assertions_per_second": throughput_assertions,
            "throughput_total_units_per_second": throughput_units,
            "median_peak_rss_mb": statistics.median(peaks) if peaks else None,
            "max_peak_rss_mb": max(peaks) if peaks else None,
            "evidence_class": rows[0]["evidence_class"],
        }
        summary_rows.append({
            key: "" if value is None else f"{value:.9f}" if isinstance(value, float) else value
            for key, value in item.items()
        })
        nested.setdefault(str(percent), {})[stage] = item
    figure_rows = []
    for percent in SCALES:
        warm = nested[str(percent)]["warm_process_deterministic_total"]
        cold = nested[str(percent)]["cold_start_deterministic_total"]
        cached = nested[str(percent)]["cached_model_output_replay"]
        figure_rows.append({
            "scale_percent": percent,
            "assertion_count": warm["assertion_count"],
            "entity_count": warm["entity_count"],
            "warm_median_seconds": f"{warm['median_seconds']:.9f}",
            "warm_q1_seconds": f"{warm['q1_seconds']:.9f}",
            "warm_q3_seconds": f"{warm['q3_seconds']:.9f}",
            "cold_median_seconds": f"{cold['median_seconds']:.9f}",
            "cold_q1_seconds": f"{cold['q1_seconds']:.9f}",
            "cold_q3_seconds": f"{cold['q3_seconds']:.9f}",
            "warm_throughput_assertions_per_second": f"{warm['throughput_assertions_per_second']:.3f}",
            "cold_throughput_assertions_per_second": f"{cold['throughput_assertions_per_second']:.3f}",
            "warm_throughput_total_units_per_second": f"{warm['throughput_total_units_per_second']:.3f}",
            "cold_throughput_total_units_per_second": f"{cold['throughput_total_units_per_second']:.3f}",
            "median_peak_rss_mb": f"{cold['median_peak_rss_mb']:.3f}",
            "max_peak_rss_mb": f"{cold['max_peak_rss_mb']:.3f}",
            "median_cached_output_replay_seconds": f"{cached['median_seconds']:.9f}",
            "online_llm_seconds": "NOT_AVAILABLE",
            "repeats": REPEATS,
        })
    return summary_rows, nested, figure_rows


def scaling_fits(nested: dict) -> tuple[dict, list[dict]]:
    """Fit descriptive linear and power curves to five median scale points."""
    x = np.asarray([
        nested[str(percent)]["warm_process_deterministic_total"]["assertion_count"]
        for percent in SCALES
    ], dtype=float)
    outputs = {}
    rows = []
    for total_name in ("warm_process_deterministic_total", "cold_start_deterministic_total"):
        y = np.asarray([
            nested[str(percent)][total_name]["median_seconds"] for percent in SCALES
        ], dtype=float)
        linear_slope, linear_intercept = np.polyfit(x, y, 1)
        linear_pred = linear_intercept + linear_slope * x
        linear_residual = y - linear_pred
        linear_r2 = 1 - float(np.sum(linear_residual ** 2) / np.sum((y - y.mean()) ** 2))

        power_exponent, log_coefficient = np.polyfit(np.log(x), np.log(y), 1)
        power_coefficient = float(np.exp(log_coefficient))
        power_pred = power_coefficient * np.power(x, power_exponent)
        power_residual = y - power_pred
        power_r2_original = 1 - float(np.sum(power_residual ** 2) / np.sum((y - y.mean()) ** 2))
        log_y = np.log(y)
        log_pred = np.log(power_pred)
        power_r2_log = 1 - float(np.sum((log_y - log_pred) ** 2) / np.sum((log_y - log_y.mean()) ** 2))

        outputs[total_name] = {
            "linear": {
                "intercept_seconds": float(linear_intercept),
                "slope_seconds_per_assertion": float(linear_slope),
                "r_squared": linear_r2,
                "interpretation": "descriptive five-point median fit; not proof of asymptotic complexity",
            },
            "power": {
                "coefficient": power_coefficient,
                "exponent": float(power_exponent),
                "r_squared_original_space": power_r2_original,
                "r_squared_log_space": power_r2_log,
                "interpretation": "descriptive five-point median fit; fixed read overhead affects the exponent",
            },
        }
        for percent, observed, lp, lr, pp, pr in zip(
            SCALES, y, linear_pred, linear_residual, power_pred, power_residual
        ):
            rows.extend([
                {
                    "total_name": total_name,
                    "fit": "linear",
                    "scale_percent": percent,
                    "assertions": int(x[list(SCALES).index(percent)]),
                    "observed_median_seconds": f"{observed:.9f}",
                    "predicted_seconds": f"{lp:.9f}",
                    "residual_seconds": f"{lr:.9f}",
                    "r_squared": f"{linear_r2:.12f}",
                    "coefficient_or_intercept": f"{linear_intercept:.12g}",
                    "slope_or_exponent": f"{linear_slope:.12g}",
                },
                {
                    "total_name": total_name,
                    "fit": "power",
                    "scale_percent": percent,
                    "assertions": int(x[list(SCALES).index(percent)]),
                    "observed_median_seconds": f"{observed:.9f}",
                    "predicted_seconds": f"{pp:.9f}",
                    "residual_seconds": f"{pr:.9f}",
                    "r_squared": f"{power_r2_original:.12f}",
                    "coefficient_or_intercept": f"{power_coefficient:.12g}",
                    "slope_or_exponent": f"{power_exponent:.12g}",
                },
            ])
    return outputs, rows


def main() -> None:
    before = source_hashes()
    totals = population_counts()
    manifest = build_sample_manifest(*totals, before)
    write_json(MANIFEST, manifest)

    setup_model_started = time.perf_counter()
    setup_bundle = joblib.load(CLASSIFIER_MODEL)
    setup_model_load_seconds = time.perf_counter() - setup_model_started

    # A small unreported warmup initializes sparse-matrix and classifier code
    # paths without consuming any model service or changing the frozen inputs.
    warm_entities, warm_edges, warm_assertions = read_raw_inputs(
        min(500, totals[0]), min(200, totals[1])
    )
    warm_inputs, _, _ = run_rule_label(warm_entities, warm_edges, warm_assertions)
    warm_features = vectorize(setup_bundle, warm_inputs)
    _ = infer(setup_bundle, warm_features)
    del warm_entities, warm_edges, warm_assertions, warm_inputs, warm_features, _
    del setup_bundle
    gc.collect()

    run_rows = []
    for repeat in range(1, REPEATS + 1):
        order = manifest["execution_schedule_latin_square"][str(repeat)]
        for position, percent in enumerate(order, start=1):
            print(json.dumps({"repeat": repeat, "position": position, "scale_percent": percent}), flush=True)
            run_rows.extend(run_one(percent, repeat, position, totals))

    fieldnames = [
        "scale_percent", "repeat", "order_position", "stage", "elapsed_seconds", "record_count",
        "assertion_count", "entity_count", "peak_rss_mb", "evidence_class",
        "included_in_warm_total", "included_in_cold_total", "output_digest", "note",
    ]
    write_csv(RUNS, run_rows, fieldnames)
    summary_rows, nested, figure_rows = summarize(run_rows)
    fits, fit_rows = scaling_fits(nested)
    write_csv(SUMMARY_CSV, summary_rows)
    write_csv(FIGURE_DATA, figure_rows)
    write_csv(SCALING_FITS, fit_rows)

    after = assert_hashes_unchanged(before)
    run_groups = Counter(
        (int(row["scale_percent"]), int(row["repeat"]))
        for row in run_rows if row["stage"] == "warm_process_deterministic_total"
    )
    per_scale_repeats = Counter(
        int(row["scale_percent"])
        for row in run_rows if row["stage"] == "warm_process_deterministic_total"
    )
    required_stages = {
        "model_bundle_load", "source_read", "rule_label", "feature_vectorization", "local_classifier_inference",
        "identity_projection", "relation_contract", "role_owner_closure", "provenance_gate",
        "admission", "aggregation", "consistency", "cached_model_output_replay",
        "online_llm_inference", "warm_process_deterministic_total", "cold_start_deterministic_total",
    }
    stages_by_run: dict[tuple[int, int], set[str]] = defaultdict(set)
    for row in run_rows:
        stages_by_run[(int(row["scale_percent"]), int(row["repeat"]))].add(str(row["stage"]))

    consistency_ok = True
    warm_sum_ok = True
    cold_sum_ok = True
    for key in stages_by_run:
        subset = [
            row for row in run_rows
            if (int(row["scale_percent"]), int(row["repeat"])) == key
        ]
        consistency_rows = [row for row in subset if row["stage"] == "consistency"]
        consistency_ok &= len(consistency_rows) == 1 and all(
            f'"{name}": 0' in consistency_rows[0]["note"]
            for name in (
                "admitted_without_provenance", "invalid_space_owner_type", "invalid_time_owner_type",
                "release_tier_mismatch", "strict_contract_violation",
            )
        )
        warm_component_sum = sum(
            float(row["elapsed_seconds"])
            for row in subset
            if row["included_in_warm_total"] == 1
        )
        cold_component_sum = sum(
            float(row["elapsed_seconds"])
            for row in subset
            if row["included_in_cold_total"] == 1
        )
        warm_total_value = float(next(
            row["elapsed_seconds"] for row in subset if row["stage"] == "warm_process_deterministic_total"
        ))
        cold_total_value = float(next(
            row["elapsed_seconds"] for row in subset if row["stage"] == "cold_start_deterministic_total"
        ))
        warm_sum_ok &= math.isclose(warm_component_sum, warm_total_value, rel_tol=0, abs_tol=2e-8)
        cold_sum_ok &= math.isclose(cold_component_sum, cold_total_value, rel_tol=0, abs_tol=2e-8)

    checks = {
        "protected_sources_unchanged": before == after,
        "five_scales_present": set(per_scale_repeats) == set(SCALES),
        "five_repeats_per_scale": all(per_scale_repeats[percent] == REPEATS for percent in SCALES),
        "twenty_five_unique_runs": len(run_groups) == len(SCALES) * REPEATS and all(value == 1 for value in run_groups.values()),
        "all_required_stages_each_run": all(stages == required_stages for stages in stages_by_run.values()),
        "warm_total_equals_component_sum": warm_sum_ok,
        "cold_total_equals_component_sum": cold_sum_ok,
        "consistency_checks_zero": consistency_ok,
        "cached_replay_separate": all(
            row["evidence_class"] == "cached_model_output"
            and row["included_in_warm_total"] == 0
            and row["included_in_cold_total"] == 0
            for row in run_rows if row["stage"] == "cached_model_output_replay"
        ),
        "online_llm_not_executed": all(
            row["evidence_class"] == "not_available"
            and row["elapsed_seconds"] == ""
            and row["included_in_warm_total"] == 0
            and row["included_in_cold_total"] == 0
            for row in run_rows if row["stage"] == "online_llm_inference"
        ),
        "model_load_measured_per_run_and_only_in_cold_total": all(
            row["elapsed_seconds"]
            and row["included_in_warm_total"] == 0
            and row["included_in_cold_total"] == 1
            for row in run_rows if row["stage"] == "model_bundle_load"
        ),
        "all_actual_stage_digests_nonempty": all(
            bool(row["output_digest"])
            for row in run_rows
            if row["evidence_class"] == "actual_run"
        ),
        "scale_counts_strictly_increase": all(
            int(manifest["scales"][str(left)]["assertions"])
            < int(manifest["scales"][str(right)]["assertions"])
            for left, right in zip(SCALES, SCALES[1:])
        ),
    }
    audit = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "source_hashes_before": before,
        "source_hashes_after": after,
        "measurement": {
            "scales": list(SCALES),
            "repeats_per_scale": REPEATS,
            "schedule": manifest["execution_schedule_latin_square"],
            "setup_warmup_model_load_seconds_outside_runs": setup_model_load_seconds,
            "per_run_model_bundle_load": "actual_run; included only in cold-start total",
            "memory": "10 ms process RSS sampler; per-run peak",
            "cache_condition": manifest["cache_condition"],
            "warm_process_total_excludes": ["model_bundle_load", "cached_model_output_replay", "online_llm_inference"],
            "cold_start_total_excludes": ["cached_model_output_replay", "online_llm_inference"],
        },
        "truthfulness_notes": [
            "local classifier is TF-IDF plus SGD and is not a local LLM",
            "cached model decisions are historical outputs and are never called online in this benchmark",
            "online LLM latency is not available because no online LLM was invoked",
            "classifier inference is timed on the scale-matched entity prefix; frozen final entity types remain authoritative for assertion closure",
            "linear and power fits use only five scale-point medians and are descriptive, not asymptotic-complexity proofs",
        ],
        "output_hashes": {
            path.name: sha256_file(path) for path in (RUNS, SUMMARY_CSV, FIGURE_DATA, SCALING_FITS, MANIFEST)
        },
    }
    write_json(AUDIT_JSON, audit)

    payload = {
        "status": audit["status"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "population": manifest["population"],
        "scales": nested,
        "scaling_fits": fits,
        "measurement": audit["measurement"],
        "outputs": {
            "runs_csv": str(RUNS),
            "summary_csv": str(SUMMARY_CSV),
            "figure_data_csv": str(FIGURE_DATA),
            "scaling_fits_csv": str(SCALING_FITS),
            "manifest_json": str(MANIFEST),
            "audit_json": str(AUDIT_JSON),
        },
    }
    write_json(SUMMARY_JSON, payload)
    audit["output_hashes"][SUMMARY_JSON.name] = sha256_file(SUMMARY_JSON)
    write_json(AUDIT_JSON, audit)
    if audit["status"] != "PASS":
        raise RuntimeError(f"end-to-end efficiency audit failed: {checks}")
    print(json.dumps({
        "status": audit["status"],
        "runs": len(run_groups),
        "scales": {
            str(percent): {
                "warm_median_seconds": nested[str(percent)]["warm_process_deterministic_total"]["median_seconds"],
                "cold_median_seconds": nested[str(percent)]["cold_start_deterministic_total"]["median_seconds"],
                "warm_throughput_assertions_per_second": nested[str(percent)]["warm_process_deterministic_total"]["throughput_assertions_per_second"],
                "cold_throughput_assertions_per_second": nested[str(percent)]["cold_start_deterministic_total"]["throughput_assertions_per_second"],
                "median_peak_rss_mb": nested[str(percent)]["cold_start_deterministic_total"]["median_peak_rss_mb"],
            }
            for percent in SCALES
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
