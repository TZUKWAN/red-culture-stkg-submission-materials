"""Blind payload construction for the Independent Multi-model Consensus
Reference (IMCR) judges.

Implements GOAL.md section 7.1 / 7.3 / 22:

* Whitelist mechanism: each task type explicitly declares the fields a judge
  is allowed to see.  Nothing else is forwarded.
* Blacklist mechanism: production-label fields (ERA label, predictions,
  risk tiers, review status, ...) must never reach a judge, neither as dict
  keys (at any nesting depth) nor embedded in string values.  Any hit raises
  :class:`LeakageError`.
* before/after A/B randomization: the a/b presentation order is derived
  deterministically from ``(seed, task_id)``; the mapping is returned (and
  meant to be written) separately so that the payload itself never contains
  the strings ``before`` / ``after``.
* Prompt version + prompt template sha256 bookkeeping.

Pure standard library.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "LeakageError",
    "BLACKLIST_KEYS",
    "BLACKLIST_VALUE_TOKENS",
    "TaskSpec",
    "TASK_SPECS",
    "prompt_sha256",
    "canonical_json",
    "scan_for_leakage",
    "assert_no_leakage",
    "ab_assignment",
    "build_blind_payload",
    "write_ab_mapping",
    "DEFAULT_PROMPT_VERSION",
]

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LeakageError(RuntimeError):
    """Raised when a production-label / blinded field would reach a judge."""


# ---------------------------------------------------------------------------
# Blacklist (GOAL.md 7.1 and section 22)
# ---------------------------------------------------------------------------

#: Field names that must never appear in a judge payload.  Matching is done
#: after key normalisation (lowercase, non-alphanumeric runs -> "_").
BLACKLIST_KEYS: frozenset[str] = frozenset(
    {
        "era",  # ERA reference annotation itself
        "era_label",
        "gold_label",
        "gold",
        "prediction",
        "predicted_label",
        "final_label",
        "risk_tier",
        "semantic_status",
        "auto_accepted",
        "review_status",
        "lexical_hint",
        "schema_votes",
        "cached_llm_prediction",
        "cached_qwen_prediction",
        "classifier_prediction",
        "rule_prediction",
        "model_confidence",
        "historical_model_confidence",
        "correctness_flag",
        "correct",  # frozen correctness flag on evaluation rows
        "canonical_entity_id",
        "merge_status",
        "majority_label",
        "consensus_label",
        "reference_label",
        "human_label",
    }
)

#: ``source_type`` is only blinded when it is itself a signal under
#: evaluation (GOAL 7.1: "source_type (如果source_type本身就是待评价信号)").
OPTIONAL_BLACKLIST_KEYS: frozenset[str] = frozenset({"source_type"})

#: Tokens that must not appear inside *string values* of a payload either
#: (e.g. a text field that literally embeds "risk_tier: high").
BLACKLIST_VALUE_TOKENS: frozenset[str] = frozenset(
    {
        "era_label",
        "gold_label",
        "prediction",
        "final_label",
        "risk_tier",
        "semantic_status",
        "auto_accepted",
        "review_status",
        "lexical_hint",
        "schema_votes",
        "cached_llm_prediction",
        "cached_qwen_prediction",
        "classifier_prediction",
        "rule_prediction",
        "model_confidence",
        "correctness_flag",
        "canonical_entity_id",
        "merge_status",
    }
)

# Regex used to detect blacklist tokens inside free-text values.
_VALUE_TOKEN_RE = re.compile(
    "|".join(
        r"(?<![a-z0-9_])" + re.escape(tok) + r"(?![a-z0-9_])"
        for tok in sorted(BLACKLIST_VALUE_TOKENS, key=len, reverse=True)
    ),
    re.IGNORECASE,
)

_KEY_NORMALISE_RE = re.compile(r"[^a-z0-9]+")


def _normalise_key(key: Any) -> str:
    """Normalise a mapping key for blacklist comparison.

    ``"ERA Label"``, ``"era-label"`` and ``"era_label"`` all normalise to
    ``"era_label"`` so that cosmetic variations cannot bypass the filter.
    """
    return _KEY_NORMALISE_RE.sub("_", str(key).strip().lower()).strip("_")


# ---------------------------------------------------------------------------
# Task specifications (whitelist)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskSpec:
    """Declaration of what a judge may see for one IMCR task type.

    Attributes
    ----------
    task_type:
        Identifier of the IMCR task (e.g. ``"entity_type"``).
    allowed_fields:
        Whitelist of record fields forwarded into the payload.
    allowed_labels:
        Label set the judge's ``decision`` must belong to (GOAL 7.3).
    ab_fields:
        Optional pair of field names holding the "before" and "after"
        versions of an object.  When set, the two are presented to the judge
        as anonymised ``a`` / ``b`` in a seed-dependent random order.
    blind_source_type:
        When True, ``source_type`` is additionally blacklisted for this
        task (GOAL 7.1 conditional rule).
    prompt_version:
        Version tag recorded with every judge call (GOAL 19).
    """

    task_type: str
    allowed_fields: tuple[str, ...]
    allowed_labels: tuple[str, ...]
    ab_fields: tuple[str, str] | None = None
    blind_source_type: bool = False
    prompt_version: str = "v1"

    def blacklist(self) -> frozenset[str]:
        bl = set(BLACKLIST_KEYS)
        if self.blind_source_type:
            bl |= OPTIONAL_BLACKLIST_KEYS
        return frozenset(bl)


DEFAULT_PROMPT_VERSION = "v1"

#: Built-in task specifications following the GOAL-defined IMCR task schema.
#: Field lists are whitelists; anything not listed is dropped, and the
#: whitelist itself is re-scanned against the blacklist as a safety net.
TASK_SPECS: dict[str, TaskSpec] = {
    "entity_type": TaskSpec(
        task_type="entity_type",
        allowed_fields=(
            "task_id",
            "entity_name",
            "entity_text",
            "source_context",
            "candidate_types",
            "type_definitions",
        ),
        allowed_labels=("Person", "Event", "Organization", "Place", "Document", "OTHER"),
        blind_source_type=True,
    ),
    "identity_pair": TaskSpec(
        task_type="identity_pair",
        allowed_fields=(
            "task_id",
            "mention_a",
            "mention_b",
            "context_a",
            "context_b",
            "attribute_table_a",
            "attribute_table_b",
        ),
        allowed_labels=("SAME", "DIFFERENT", "UNCERTAIN"),
        blind_source_type=True,
    ),
    "temporal_spatial_fix": TaskSpec(
        task_type="temporal_spatial_fix",
        allowed_fields=(
            "task_id",
            "assertion_text",
            "evidence_excerpts",
            "local_relation_context",
            "schema_definitions",
            "before",
            "after",
        ),
        allowed_labels=("BEFORE_BETTER", "AFTER_BETTER", "EQUIVALENT", "BOTH_WRONG"),
        ab_fields=("before", "after"),
        blind_source_type=True,
    ),
    "relation_contract_diff": TaskSpec(
        task_type="relation_contract_diff",
        allowed_fields=(
            "task_id",
            "subject_text",
            "object_text",
            "relation_text",
            "evidence_excerpts",
            "schema_definitions",
            "before",
            "after",
        ),
        allowed_labels=("BEFORE_BETTER", "AFTER_BETTER", "EQUIVALENT", "BOTH_WRONG"),
        ab_fields=("before", "after"),
        blind_source_type=True,
    ),
    "provenance_support": TaskSpec(
        task_type="provenance_support",
        allowed_fields=(
            "task_id",
            "assertion_text",
            "evidence_excerpts",
            "citation_metadata",
        ),
        allowed_labels=("SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED"),
        blind_source_type=True,
    ),
}


# ---------------------------------------------------------------------------
# Hashing / serialisation helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Deterministic JSON serialisation (sorted keys, compact separators)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def prompt_sha256(prompt_template: str) -> str:
    """sha256 of a prompt template string (GOAL 21: prompt_sha256)."""
    return hashlib.sha256(prompt_template.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Deep leakage scan
# ---------------------------------------------------------------------------


def _iter_items(obj: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    """Yield ``(path, value)`` for every node of a nested structure."""
    if isinstance(obj, Mapping):
        for key, val in obj.items():
            child = f"{path}.{key}" if path else str(key)
            yield child, key
            yield from _iter_items(val, child)
    elif isinstance(obj, (list, tuple)):
        for idx, val in enumerate(obj):
            child = f"{path}[{idx}]"
            yield from _iter_items(val, child)
    else:
        yield path, obj


def scan_for_leakage(
    payload: Any,
    blacklist_keys: Iterable[str] | None = None,
    scan_values: bool = True,
) -> list[str]:
    """Deep-scan ``payload`` for blacklisted keys or values.

    Returns a list of human-readable violation descriptions; empty list
    means the payload is clean.  Scans:

    * every mapping key at any nesting depth (after normalisation);
    * every string *value* for embedded blacklist tokens (e.g. a context
      string that literally contains ``"risk_tier=high"``).
    """
    keys = frozenset(_normalise_key(k) for k in (blacklist_keys or BLACKLIST_KEYS))
    violations: list[str] = []
    for path, node in _iter_items(payload):
        if isinstance(node, Mapping):
            continue  # mappings themselves are not leaf values
        # ``_iter_items`` yields both keys (as values of the parent) and leaf
        # values; distinguish them by whether the node is a known key string.
        if isinstance(node, str):
            norm = _normalise_key(node)
            if norm in keys:
                violations.append(f"blacklisted key at '{path}'")
            elif scan_values and _VALUE_TOKEN_RE.search(node):
                violations.append(f"blacklisted token inside string value at '{path}'")
    return violations


def assert_no_leakage(
    payload: Any,
    blacklist_keys: Iterable[str] | None = None,
    scan_values: bool = True,
) -> None:
    """Raise :class:`LeakageError` if the payload contains any leakage."""
    violations = scan_for_leakage(payload, blacklist_keys, scan_values)
    if violations:
        raise LeakageError(
            "blind payload leakage detected: " + "; ".join(sorted(violations))
        )


# ---------------------------------------------------------------------------
# A/B randomisation
# ---------------------------------------------------------------------------


def ab_assignment(task_id: str, seed: int | str) -> dict[str, str]:
    """Deterministic anonymised order for a before/after pair.

    Returns a mapping ``{"a": "before", "b": "after"}`` or
    ``{"a": "after", "b": "before"}`` chosen from the sha256 of
    ``f"{seed}::{task_id}"``.  The mapping is invertible and must be stored
    in a *separate* mapping file; the payload itself only carries ``a``/``b``.
    """
    digest = hashlib.sha256(f"{seed}::{task_id}".encode("utf-8")).digest()
    if digest[0] % 2 == 0:
        return {"a": "before", "b": "after"}
    return {"a": "after", "b": "before"}


def invert_ab_assignment(mapping: Mapping[str, str]) -> dict[str, str]:
    """Invert an a/b mapping: ``{"before": "a", "after": "b"}`` etc."""
    return {v: k for k, v in mapping.items()}


def write_ab_mapping(records: Sequence[Mapping[str, Any]], path: str) -> str:
    """Write the separate a/b mapping file (JSON lines)."""
    import csv

    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["task_id", "a", "b", "seed"])
        writer.writeheader()
        for rec in records:
            writer.writerow(
                {
                    "task_id": rec["task_id"],
                    "a": rec["a"],
                    "b": rec["b"],
                    "seed": rec["seed"],
                }
            )
    return path


# ---------------------------------------------------------------------------
# Payload construction
# ---------------------------------------------------------------------------


def build_blind_payload(
    record: Mapping[str, Any],
    spec: TaskSpec,
    seed: int | str,
    task_id: str | None = None,
    prompt_template: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a blinded judge payload from a raw record.

    Parameters
    ----------
    record:
        Raw task record.  May contain arbitrary production fields; only the
        whitelist in ``spec.allowed_fields`` is forwarded.
    spec:
        The :class:`TaskSpec` for this task type.
    seed:
        Experiment-level seed driving the a/b randomisation.
    task_id:
        Task identifier; defaults to ``record["task_id"]``.
    prompt_template:
        Optional prompt template; when given, ``prompt_sha256`` is included
        in the returned metadata.

    Returns
    -------
    (payload, meta)
        ``payload`` contains only whitelisted, leakage-scanned fields (with
        before/after anonymised to a/b when the spec declares ``ab_fields``).
        ``meta`` carries ``task_id``, ``task_type``, ``prompt_version``,
        ``prompt_sha256``, and — for A/B tasks — the ``ab_mapping`` which
        MUST be stored separately from the payload.
    """
    tid = str(task_id if task_id is not None else record.get("task_id", ""))
    if not tid:
        raise ValueError("task_id is required (argument or record['task_id'])")

    blacklist = spec.blacklist()
    payload: dict[str, Any] = {"task_id": tid}

    ab_fields = spec.ab_fields
    whitelisted: dict[str, Any] = {}
    for name in spec.allowed_fields:
        if name == "task_id" or name in payload:
            continue
        if ab_fields and name in ab_fields:
            continue  # handled below
        if name in record:
            whitelisted[name] = record[name]

    # Re-scan the whitelist output itself: a whitelisted field's *content*
    # may still embed blacklisted sub-keys or tokens at depth.
    assert_no_leakage(whitelisted, blacklist)

    payload.update(whitelisted)

    ab_mapping: dict[str, str] | None = None
    if ab_fields is not None:
        before_key, after_key = ab_fields
        if before_key not in record or after_key not in record:
            raise ValueError(
                f"record is missing A/B fields {ab_fields!r} required by "
                f"task spec '{spec.task_type}'"
            )
        before_val, after_val = record[before_key], record[after_key]
        # The before/after values themselves must be leakage-free.
        assert_no_leakage({"before": before_val, "after": after_val}, blacklist)
        ab_mapping = ab_assignment(tid, seed)
        payload["a"] = before_val if ab_mapping["a"] == "before" else after_val
        payload["b"] = before_val if ab_mapping["b"] == "before" else after_val

    # Final belt-and-braces scan of the complete payload (keys + values).
    assert_no_leakage(payload, blacklist)

    meta: dict[str, Any] = {
        "task_id": tid,
        "task_type": spec.task_type,
        "prompt_version": spec.prompt_version,
        "allowed_labels": list(spec.allowed_labels),
    }
    if ab_mapping is not None:
        meta["ab_mapping"] = ab_mapping
        meta["seed"] = seed
    if prompt_template is not None:
        meta["prompt_sha256"] = prompt_sha256(prompt_template)
    return payload, meta
