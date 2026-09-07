"""OpenAI-compatible chat-completions client for IMCR judge models.

Implements GOAL.md sections 7.3 (output format), 19 (API & run logging
requirements) and 20 (AI response validation):

* All API configuration is read from environment variables only:
  ``JUDGE_{NAME}_BASE_URL`` / ``JUDGE_{NAME}_API_KEY`` /
  ``JUDGE_{NAME}_MODEL``.  No key is ever hard-coded, logged, or written to
  any output file; the client actively scrubs key material from records.
* Every call is recorded with the 11 required fields: model exact ID,
  provider (base_url hostname), prompt_version, temperature, top_p, seed
  (when supported), timestamp, raw response, parsed response, retry_count,
  validation_error.
* JSON schema validation of judge output; invalid output triggers a bounded
  retry (default max 3); when the cap is reached the record is marked
  ``MODEL_OUTPUT_INVALID`` — answers are never hand-corrected.
* Offline ``dry_run`` mode returning deterministic fake responses so the
  full test-suite runs without any real API.

Pure standard library (urllib for HTTP).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "JudgeConfig",
    "JudgeCallRecord",
    "JudgeClient",
    "JudgeClientError",
    "MODEL_OUTPUT_INVALID",
    "REQUIRED_OUTPUT_KEYS",
    "validate_judge_output",
    "extract_json_object",
    "load_judge_config",
    "JUDGE_NAMES",
]

#: Marker written into records when a judge exhausts its retries with
#: invalid output (GOAL 20).  Never silently replaced by a hand label.
MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"

#: The 11 run-metadata fields required by GOAL section 19 (kept as the
#: column order for JSONL/CSV exports).
RECORD_FIELDS: tuple[str, ...] = (
    "model_id",
    "provider",
    "prompt_version",
    "temperature",
    "top_p",
    "seed",
    "timestamp",
    "raw_response",
    "parsed_response",
    "retry_count",
    "validation_error",
)

#: Required keys and expected types in the judge output JSON (GOAL 7.3).
REQUIRED_OUTPUT_KEYS: dict[str, type | tuple[type, ...]] = {
    "task_id": str,
    "decision": str,
    "confidence": (int, float),
    "evidence": list,
    "reason_code": str,
    "explanation": str,
    "insufficient_evidence": bool,
}

#: Judge slots defined by the experiment design (GOAL 7.2).
JUDGE_NAMES: tuple[str, ...] = ("A", "B", "C", "D", "E")


class JudgeClientError(RuntimeError):
    """Raised for configuration or transport-level client failures.

    ``status_code`` / ``retry_after`` are populated for HTTP failures so
    callers can apply bounded backoff (429 / 5xx) without ever seeing the
    Authorization header.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


#: HTTP status codes that justify a bounded transport retry (rate limits,
#: transient server-side faults). 4xx client errors other than these fail
#: immediately.
RETRYABLE_HTTP_STATUSES: frozenset[int] = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


# ---------------------------------------------------------------------------
# Configuration (environment variables only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeConfig:
    """Runtime configuration of one judge model.

    ``api_key`` is stored in memory only; :func:`JudgeConfig.to_safe_dict`
    and the client's call records never include it.
    """

    name: str
    base_url: str
    api_key: str
    model: str

    @property
    def provider(self) -> str:
        """Hostname of the API provider, parsed from ``base_url``."""
        return urllib.parse.urlparse(self.base_url).hostname or self.base_url

    def to_safe_dict(self) -> dict[str, str]:
        """Serializable view that never exposes the API key."""
        return {
            "name": self.name,
            "base_url": self.base_url,
            "provider": self.provider,
            "model": self.model,
        }

    def __repr__(self) -> str:  # keep the key out of tracebacks/logs
        return (
            f"JudgeConfig(name={self.name!r}, base_url={self.base_url!r}, "
            f"api_key=<redacted>, model={self.model!r})"
        )


def load_judge_config(name: str, env: Mapping[str, str] | None = None) -> JudgeConfig:
    """Load ``JUDGE_{NAME}_BASE_URL/_API_KEY/_MODEL`` from the environment.

    Raises :class:`JudgeClientError` when any variable is missing; the
    exception message names the missing *variable* but never a value.
    """
    environ = os.environ if env is None else env
    upper = name.upper()
    missing = [
        var
        for var in (
            f"JUDGE_{upper}_BASE_URL",
            f"JUDGE_{upper}_API_KEY",
            f"JUDGE_{upper}_MODEL",
        )
        if not environ.get(var)
    ]
    if missing:
        raise JudgeClientError(
            f"missing environment variables for judge {name}: "
            + ", ".join(sorted(missing))
        )
    return JudgeConfig(
        name=upper,
        base_url=environ[f"JUDGE_{upper}_BASE_URL"],
        api_key=environ[f"JUDGE_{upper}_API_KEY"],
        model=environ[f"JUDGE_{upper}_MODEL"],
    )


# ---------------------------------------------------------------------------
# Output validation (GOAL 7.3 + 20)
# ---------------------------------------------------------------------------


def extract_json_object(text: str) -> str:
    """Extract the first JSON object from raw model text.

    Tolerates markdown code fences and surrounding prose by locating the
    first ``{`` and its matching closing ``}``.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # strip a single wrapping code fence
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("no JSON object found in model output")
    depth = 0
    in_str = False
    escape = False
    for idx in range(start, len(cleaned)):
        ch = cleaned[idx]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start : idx + 1]
    raise ValueError("unbalanced braces in model output")


def validate_judge_output(
    raw_text: str,
    task_id: str,
    allowed_labels: Sequence[str],
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate one raw judge response against the GOAL 7.3 schema.

    Returns ``(parsed, None)`` on success or ``(None, error_message)`` on
    any failure.  A valid response must:

    * be parseable JSON (code fences tolerated);
    * contain exactly the required keys with the right types;
    * echo the expected ``task_id``;
    * have ``decision`` inside the task-level ``allowed_labels``;
    * have ``confidence`` within [0, 1];
    * have ``insufficient_evidence`` as a real boolean (not 0/1).
    """
    try:
        obj_text = extract_json_object(raw_text)
    except ValueError as exc:
        return None, f"json_extraction_failed: {exc}"
    try:
        obj = json.loads(obj_text)
    except json.JSONDecodeError as exc:
        return None, f"json_parse_failed: {exc}"
    if not isinstance(obj, dict):
        return None, "schema_error: top-level value is not an object"

    for key, expected in REQUIRED_OUTPUT_KEYS.items():
        if key not in obj:
            return None, f"schema_error: missing key '{key}'"
        value = obj[key]
        if expected is bool or expected == bool:  # pragma: no cover - defensive
            pass
        # bool must be checked before int/float because bool is a subclass
        if key == "insufficient_evidence":
            if not isinstance(value, bool):
                return None, "schema_error: 'insufficient_evidence' is not a boolean"
        elif key == "confidence":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None, "schema_error: 'confidence' is not numeric"
        elif not isinstance(value, expected):
            return None, f"schema_error: '{key}' has wrong type"

    if obj["task_id"] != task_id:
        return None, (
            f"schema_error: task_id mismatch (expected {task_id!r}, "
            f"got {obj['task_id']!r})"
        )
    confidence = float(obj["confidence"])
    if not 0.0 <= confidence <= 1.0:
        return None, f"schema_error: confidence {confidence} out of range [0, 1]"
    if obj["decision"] not in allowed_labels:
        return None, (
            f"schema_error: decision {obj['decision']!r} not in allowed labels "
            f"{list(allowed_labels)!r}"
        )
    if not all(isinstance(item, str) for item in obj["evidence"]):
        return None, "schema_error: 'evidence' entries must be strings"

    parsed = {
        "task_id": obj["task_id"],
        "decision": obj["decision"],
        "confidence": confidence,
        "evidence": list(obj["evidence"]),
        "reason_code": obj["reason_code"],
        "explanation": obj["explanation"],
        "insufficient_evidence": obj["insufficient_evidence"],
    }
    return parsed, None


# ---------------------------------------------------------------------------
# Call record (GOAL 19)
# ---------------------------------------------------------------------------


@dataclass
class JudgeCallRecord:
    """One judge call, with the 11 GOAL-19 metadata fields."""

    task_id: str
    judge_name: str
    model_id: str
    provider: str
    prompt_version: str
    temperature: float
    top_p: float
    seed: int | None
    timestamp: str
    raw_response: str | None
    parsed_response: dict[str, Any] | None
    retry_count: int
    validation_error: str | None
    status: str = "OK"  # "OK" | MODEL_OUTPUT_INVALID | "TRANSPORT_ERROR"
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "judge_name": self.judge_name,
            "model_id": self.model_id,
            "provider": self.provider,
            "prompt_version": self.prompt_version,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "seed": self.seed,
            "timestamp": self.timestamp,
            "raw_response": self.raw_response,
            "parsed_response": self.parsed_response,
            "retry_count": self.retry_count,
            "validation_error": self.validation_error,
            "status": self.status,
            "dry_run": self.dry_run,
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_FakeResponder = Callable[[str, Sequence[str]], Mapping[str, Any] | str]


def _default_fake_response(task_id: str, allowed_labels: Sequence[str]) -> dict[str, Any]:
    """Deterministic offline response used by dry-run mode.

    The label is chosen by hashing the task_id so different tasks exercise
    different labels while remaining perfectly reproducible.
    """
    labels = list(allowed_labels)
    digest = hashlib.sha256(f"dry-run::{task_id}".encode("utf-8")).digest()
    label = labels[digest[0] % len(labels)]
    return {
        "task_id": task_id,
        "decision": label,
        "confidence": round(0.5 + (digest[1] % 50) / 100.0, 4),
        "evidence": [f"dry-run evidence for {task_id}"],
        "reason_code": "DRY_RUN",
        "explanation": "Deterministic offline placeholder response.",
        "insufficient_evidence": False,
    }


class JudgeClient:
    """OpenAI-compatible chat-completions client for one judge model.

    Parameters
    ----------
    config:
        A :class:`JudgeConfig`; may be ``None`` in ``dry_run`` mode.
    dry_run:
        When True no HTTP request is made; responses come from
        ``fake_responder`` (or the deterministic default).
    max_retries:
        Fixed cap on validation-triggered retries (GOAL 20; default 3,
        meaning at most 3 *additional* attempts after the first).
    timeout:
        HTTP timeout in seconds for real calls.
    max_transport_retries:
        Bounded cap on transport-level retries (429 / 5xx / network
        errors); backoff honours the provider's Retry-After header and
        otherwise grows exponentially.  Never a tight loop.
    """

    def __init__(
        self,
        config: JudgeConfig | None = None,
        *,
        dry_run: bool = False,
        fake_responder: _FakeResponder | None = None,
        max_retries: int = 3,
        timeout: float = 60.0,
        sleep_between_retries: float = 0.0,
        max_transport_retries: int = 4,
        transport_backoff_base: float = 2.0,
        transport_backoff_max: float = 120.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if not dry_run and config is None:
            raise JudgeClientError("a JudgeConfig is required unless dry_run=True")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if max_transport_retries < 0:
            raise ValueError("max_transport_retries must be >= 0")
        self.config = config
        self.dry_run = dry_run
        self.fake_responder = fake_responder
        self.max_retries = max_retries
        self.timeout = timeout
        self.sleep_between_retries = sleep_between_retries
        self.max_transport_retries = max_transport_retries
        self.transport_backoff_base = transport_backoff_base
        self.transport_backoff_max = transport_backoff_max
        self.sleep_fn = sleep_fn

    # -- construction ------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        name: str,
        env: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> "JudgeClient":
        """Build a client from ``JUDGE_{NAME}_*`` environment variables."""
        return cls(load_judge_config(name, env), **kwargs)

    # -- internals ----------------------------------------------------------

    @property
    def _model_id(self) -> str:
        return self.config.model if self.config else "dry-run-model"

    @property
    def _provider(self) -> str:
        return self.config.provider if self.config else "dry-run"

    @property
    def _judge_name(self) -> str:
        return self.config.name if self.config else "DRYRUN"

    def _redact(self, text: str | None) -> str | None:
        """Remove any occurrence of the API key from a string (defence in
        depth: keys must never land in logs or output files)."""
        if text is None or self.config is None:
            return text
        key = self.config.api_key
        return text.replace(key, "<redacted>") if key else text

    def _fake_raw(self, task_id: str, allowed_labels: Sequence[str], attempt: int) -> str:
        if self.fake_responder is not None:
            produced = self.fake_responder(task_id, allowed_labels)
            return produced if isinstance(produced, str) else json.dumps(produced, ensure_ascii=False)
        return json.dumps(_default_fake_response(task_id, allowed_labels), ensure_ascii=False)

    def _http_raw(
        self,
        messages: Sequence[Mapping[str, str]],
        temperature: float,
        top_p: float,
        seed: int | None,
    ) -> str:
        assert self.config is not None  # guaranteed unless dry_run
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": list(messages),
            "temperature": temperature,
            "top_p": top_p,
            "response_format": {"type": "json_object"},
        }
        if seed is not None:
            body["seed"] = seed
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                envelope = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Never include the Authorization header in the error text.
            retry_after: float | None = None
            raw_ra = exc.headers.get("Retry-After") if exc.headers else None
            if raw_ra:
                try:
                    retry_after = max(0.0, float(raw_ra))
                except ValueError:
                    retry_after = None
            raise JudgeClientError(
                f"HTTP {exc.code} from provider {self._provider}",
                status_code=exc.code,
                retry_after=retry_after,
            ) from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise JudgeClientError(
                f"transport error from provider {self._provider}: "
                f"{type(exc).__name__}"
            ) from None
        try:
            return str(envelope["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise JudgeClientError(
                f"malformed completion envelope from {self._provider}: "
                f"{type(exc).__name__}"
            ) from None

    def _http_raw_with_backoff(
        self,
        messages: Sequence[Mapping[str, str]],
        temperature: float,
        top_p: float,
        seed: int | None,
    ) -> str:
        """_http_raw with bounded transport retries and backoff.

        Retries only retryable failures (HTTP 408/409/425/429/5xx, network
        errors, timeouts, malformed envelopes).  The sleep before attempt
        ``k`` (1-based retry index) is the provider's Retry-After when
        given, else ``min(base * 2**(k-1), max)`` — never a tight loop.
        Non-retryable HTTP errors (e.g. 401/403) fail immediately.
        """
        attempt = 0
        while True:
            try:
                return self._http_raw(messages, temperature, top_p, seed)
            except JudgeClientError as exc:
                retryable = exc.status_code is None or (
                    exc.status_code in RETRYABLE_HTTP_STATUSES
                )
                if not retryable or attempt >= self.max_transport_retries:
                    raise
                attempt += 1
                delay = (
                    exc.retry_after
                    if exc.retry_after is not None
                    else min(
                        self.transport_backoff_base * (2 ** (attempt - 1)),
                        self.transport_backoff_max,
                    )
                )
                if delay > 0:
                    self.sleep_fn(delay)

    # -- public API ----------------------------------------------------------

    def judge(
        self,
        task_id: str,
        allowed_labels: Sequence[str],
        *,
        prompt_version: str,
        messages: Sequence[Mapping[str, str]] | None = None,
        payload: Mapping[str, Any] | None = None,
        temperature: float = 0.0,
        top_p: float = 1.0,
        seed: int | None = None,
    ) -> JudgeCallRecord:
        """Run one blind judging call with bounded validation retries.

        Exactly one of ``messages`` / ``payload`` may be supplied; a payload
        is wrapped into a minimal user message containing its canonical
        JSON.  Returns a :class:`JudgeCallRecord`; when validation fails
        ``max_retries`` additional times the record carries
        ``status == MODEL_OUTPUT_INVALID`` and ``parsed_response is None``.
        """
        if not allowed_labels:
            raise ValueError("allowed_labels must be a non-empty sequence")
        if messages is not None and payload is not None:
            raise ValueError("pass either messages or payload, not both")
        if messages is None:
            if payload is None:
                raise ValueError("messages or payload is required")
            messages = [
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                }
            ]

        retry_count = 0
        last_error: str | None = None
        raw: str | None = None
        while True:
            if self.dry_run:
                raw = self._fake_raw(task_id, allowed_labels, retry_count)
            else:
                try:
                    raw = self._http_raw_with_backoff(messages, temperature, top_p, seed)
                except JudgeClientError as exc:
                    return JudgeCallRecord(
                        task_id=task_id,
                        judge_name=self._judge_name,
                        model_id=self._model_id,
                        provider=self._provider,
                        prompt_version=prompt_version,
                        temperature=temperature,
                        top_p=top_p,
                        seed=seed,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        raw_response=None,
                        parsed_response=None,
                        retry_count=retry_count,
                        validation_error=self._redact(str(exc)),
                        status="TRANSPORT_ERROR",
                        dry_run=self.dry_run,
                    )
            parsed, error = validate_judge_output(raw, task_id, allowed_labels)
            if error is None:
                return JudgeCallRecord(
                    task_id=task_id,
                    judge_name=self._judge_name,
                    model_id=self._model_id,
                    provider=self._provider,
                    prompt_version=prompt_version,
                    temperature=temperature,
                    top_p=top_p,
                    seed=seed,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    raw_response=self._redact(raw),
                    parsed_response=parsed,
                    retry_count=retry_count,
                    validation_error=None,
                    status="OK",
                    dry_run=self.dry_run,
                )
            last_error = error
            if retry_count >= self.max_retries:
                return JudgeCallRecord(
                    task_id=task_id,
                    judge_name=self._judge_name,
                    model_id=self._model_id,
                    provider=self._provider,
                    prompt_version=prompt_version,
                    temperature=temperature,
                    top_p=top_p,
                    seed=seed,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    raw_response=self._redact(raw),
                    parsed_response=None,
                    retry_count=retry_count,
                    validation_error=last_error,
                    status=MODEL_OUTPUT_INVALID,
                    dry_run=self.dry_run,
                )
            retry_count += 1
            if self.sleep_between_retries > 0:
                time.sleep(self.sleep_between_retries)


def append_records_jsonl(records: Sequence[JudgeCallRecord], path: str) -> str:
    """Append call records to a JSONL log file (no API keys inside)."""
    with open(path, "a", encoding="utf-8") as fh:
        for record in records:
            fh.write(record.to_jsonl() + "\n")
    return path
