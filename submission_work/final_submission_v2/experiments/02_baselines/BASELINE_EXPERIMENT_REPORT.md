# Paper A baseline experiment report

- Result: **PASS**
- Frozen AI ensemble gold: 712 rows; SHA-256 `1190ed0d7a4ec16b34712293f47992d624788ba4734c2bfce4020d51de0a9c0f`
- Fixed test set: 159 rows; split seed `paper-a-baseline-stratified-v1-20260730`
- Core eligible aggregate: 152 rows; excludes 4 time-owner and 3 space-owner shared-proxy test rows.
- All-reference audit aggregate: 159 rows; retained only for traceability.
- Live LLM calls in this run: **0**
- Protected database hashes before/after: unchanged

## Evidence separation

- `M1_rule_only`: current deterministic run, but it shares a rule channel with the AI gold; diagnostic only.
- `M2_classifier_only`: held-out supervised proxy benchmark. Test samples do not enter fitting, but the target is still the current AI gold and is not label-independent factual evidence.
- `M3_cached_llm_replay` and `M4_rule_plus_cached_llm`: cached shared-gold-channel diagnostics; not independent accuracy evidence.
- `M6_full_v2_replay`: deterministic frozen-output replay with shared system signals; listed separately from actual runs.
- `safe_correct`: counted only when the prediction matches gold and passes the recorded task-specific structural gate; Full replay additionally requires frozen `auto_accepted` status and risk tier A/B.
- `time_owner` and `space_owner`: marked `evaluation_ineligible_for_primary_owner_shared_proxy` after the dedicated role-owner audit; excluded from `__CORE_ELIGIBLE_TASKS__`.
- Live `LLM-only` and the no-global-closure configuration remain `not_available` because no valid per-sample run exists.

## Existing evidence audit

- Saved entity-classifier overlap with the 203 gold entity rows: 36 historical validation and 5 historical pending predictions.
- Legacy baseline table contains 5 `NOT_RUN` rows; none was promoted to a measured baseline.

## Output files

- `D:\REDCULTUREDATA\dual_paper_project\paper_A_method\revision\02_baselines\BASELINE_SPLIT_MANIFEST.csv`
- `D:\REDCULTUREDATA\dual_paper_project\paper_A_method\revision\02_baselines\BASELINE_RUNS.csv`
- `D:\REDCULTUREDATA\dual_paper_project\paper_A_method\revision\02_baselines\BASELINE_METRICS.csv`
- `D:\REDCULTUREDATA\dual_paper_project\paper_A_method\revision\02_baselines\ACTUAL_RUN_BASELINE_METRICS.csv`
- `D:\REDCULTUREDATA\dual_paper_project\paper_A_method\revision\02_baselines\REPLAY_AND_CACHED_BASELINE_METRICS.csv`
- `D:\REDCULTUREDATA\dual_paper_project\paper_A_method\revision\02_baselines\BASELINE_AVAILABILITY.csv`
- `D:\REDCULTUREDATA\dual_paper_project\paper_A_method\revision\02_baselines\baseline_experiment_summary.json`
