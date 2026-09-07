"""Independent Multi-model Consensus Reference (IMCR) evaluation toolkit.

Modules
-------
blind_payload
    Whitelist/blacklist blind payload construction + A/B randomisation.
judge_client
    OpenAI-compatible judge client with schema validation and bounded
    retry, environment-variable-only credentials, dry-run mode.
consensus
    GOAL 7.4 consensus aggregation + 7.5 reliability statistics.
metrics
    Selective-prediction metrics, CIs and paired tests.
manifest
    Experiment manifest + streaming sha256 utilities.
"""

__all__ = ["blind_payload", "judge_client", "consensus", "metrics", "manifest"]
__version__ = "1.0.0"
