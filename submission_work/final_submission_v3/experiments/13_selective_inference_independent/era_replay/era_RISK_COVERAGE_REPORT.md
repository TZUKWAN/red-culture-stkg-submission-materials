# Paper A selective-inference report (v3)

- Result: **PASS**
- Correctness reference: **era**
- Curve rows: 1750
- Curves with valid AURC/AUGRC: 20
- Primary constrained curves with valid areas: 10
- Maximum AUGRC closed-form cross-check difference: `5.551e-17`
- GOAL-13 metrics.py AURC/AUGRC cross-check difference: `5.551e-17`
- Bootstrap: 2000 fixed-seed replicates for each applicable curve; raw rows `40000`
- Live LLM calls: **0**

## Metric definitions

- Primary coverage accepts a row only when `score >= threshold` and `hard_constraint_pass = 1`; the denominator remains the full frozen task test set.
- Score-only curves are diagnostic and are never interpreted as method automatic-admission performance.
- Selective risk is the error proportion among accepted predictions.
- Generalized risk is accepted errors divided by the full test denominator.
- Safe coverage requires reference agreement and the task-specific hard-constraint gate already recorded in `BASELINE_RUNS.csv`.
- Rejected rows are counted as review escalation; this is not an LLM-call count.
- Primary AURC/AUGRC use trapezoidal integration over exact tie-grouped constrained points on the achievable `[0,max_coverage]` domain; normalized areas are also retained.
- AURC/AUGRC 95% intervals use fixed-seed percentile bootstrap; every replicate is retained in `era_RISK_COVERAGE_BOOTSTRAP.csv`.
- GOAL-13 point metrics (selective accuracy, error exposure, macro-F1 on accepted, macro-F1 on full denominator) are computed with `code/independent_eval/metrics.py` in `era_SELECTIVE_GOAL13_METRICS.csv`.

## Reference mode

- `--reference era`: correctness flags frozen in `BASELINE_RUNS.csv` (ERA integrated reference annotation) are used unchanged; this mode reproduces the v2 numbers.

## Evidence interpretation

- M2 is a held-out supervised proxy against the unchanged AI gold.
- M6 is a frozen deterministic replay with shared system signals.
- Cached LLM outputs have no numeric confidence and directly contributed to gold construction, so no cached-LLM area metric is produced.
- Owner reference tasks remain shared-proxy diagnostics and do not enter primary areas or the figure.

## References

- El-Yaniv and Wiener, risk–coverage foundations: https://jmlr.csail.mit.edu/papers/v11/el-yaniv10a.html
- Traub et al., generalized risk and AUGRC: https://proceedings.neurips.cc/paper_files/paper/2024/file/047c84ec50bd8ea29349b996fc64af4b-Paper-Conference.pdf
