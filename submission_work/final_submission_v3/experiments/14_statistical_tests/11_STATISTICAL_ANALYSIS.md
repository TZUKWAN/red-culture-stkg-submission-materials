# Statistical analysis (experiment 14, GOAL section 18)

- Report mode: **FILLED**
- Correctness reference: **imcr_strong**
- Primary per-sample input: `IMCR_BASELINE_RUNS.csv`
- Bootstrap replicates per comparison: **2000** (fixed seed, shared resample indices, every replicate saved to `PAIRED_BOOTSTRAP_REPLICATES.csv`)
- Generated at: 2026-09-08T00:52:48+00:00

## 1. Operating-point table: n / coverage / correct / error / estimate / 95% CI

GOAL 18 requires, for every method x task cell, the denominator `n`,
the coverage, the raw correct/error counts, the point estimate and a
95% interval.  Coverage (k = accepted, n = full frozen task set) and
post-accept selective accuracy (k = correct, n = accepted) are
reported as separate rows of `WILSON_CI_TABLE.csv` (`metric` column).

- `entity_type` / `B10_selective_no_structural_gate` (coverage): n=276, correct=41, error=235, estimate=0.14855072463768115, 95% Wilson CI=[0.11142820996381964, 0.19532211639041885]
- `entity_type` / `B10_selective_no_structural_gate` (selective_accuracy): n=41, correct=38, error=3, estimate=0.926829268292683, 95% Wilson CI=[0.8057255146228096, 0.9748021693660901]
- `identity_pair` / `B10_selective_no_structural_gate` (coverage): n=399, correct=399, error=0, estimate=1.0, 95% Wilson CI=[0.9904640926682675, 1.0]
- `identity_pair` / `B10_selective_no_structural_gate` (selective_accuracy): n=399, correct=258, error=141, estimate=0.6466165413533834, 95% Wilson CI=[0.5985178435694403, 0.6919189956340366]
- `provenance_support` / `B10_selective_no_structural_gate` (coverage): n=394, correct=394, error=0, estimate=1.0, 95% Wilson CI=[0.9903442470976223, 1.0]
- `provenance_support` / `B10_selective_no_structural_gate` (selective_accuracy): n=394, correct=120, error=274, estimate=0.30456852791878175, 95% Wilson CI=[0.2611928602690694, 0.3517182715760224]
- `relation_contract` / `B10_selective_no_structural_gate` (coverage): n=66, correct=66, error=0, estimate=1.0, 95% Wilson CI=[0.9449974429864586, 0.9999999999999999]
- `relation_contract` / `B10_selective_no_structural_gate` (selective_accuracy): n=66, correct=7, error=59, estimate=0.10606060606060606, 95% Wilson CI=[0.05233347255479488, 0.20312308751648012]
- `scope_adjustment` / `B10_selective_no_structural_gate` (coverage): n=111, correct=111, error=0, estimate=1.0, 95% Wilson CI=[0.9665498953066078, 1.0]
- `scope_adjustment` / `B10_selective_no_structural_gate` (selective_accuracy): n=111, correct=51, error=60, estimate=0.4594594594594595, 95% Wilson CI=[0.36965969632385665, 0.5519713932458781]
- `entity_type` / `B11_structural_gate_no_abstention` (coverage): n=276, correct=41, error=235, estimate=0.14855072463768115, 95% Wilson CI=[0.11142820996381964, 0.19532211639041885]
- `entity_type` / `B11_structural_gate_no_abstention` (selective_accuracy): n=41, correct=38, error=3, estimate=0.926829268292683, 95% Wilson CI=[0.8057255146228096, 0.9748021693660901]
- `identity_pair` / `B11_structural_gate_no_abstention` (coverage): n=399, correct=399, error=0, estimate=1.0, 95% Wilson CI=[0.9904640926682675, 1.0]
- `identity_pair` / `B11_structural_gate_no_abstention` (selective_accuracy): n=399, correct=258, error=141, estimate=0.6466165413533834, 95% Wilson CI=[0.5985178435694403, 0.6919189956340366]
- `provenance_support` / `B11_structural_gate_no_abstention` (coverage): n=394, correct=394, error=0, estimate=1.0, 95% Wilson CI=[0.9903442470976223, 1.0]
- `provenance_support` / `B11_structural_gate_no_abstention` (selective_accuracy): n=394, correct=120, error=274, estimate=0.30456852791878175, 95% Wilson CI=[0.2611928602690694, 0.3517182715760224]
- `relation_contract` / `B11_structural_gate_no_abstention` (coverage): n=66, correct=42, error=24, estimate=0.6363636363636364, 95% Wilson CI=[0.5157964063076522, 0.7419301690522909]
- `relation_contract` / `B11_structural_gate_no_abstention` (selective_accuracy): n=42, correct=1, error=41, estimate=0.023809523809523808, 95% Wilson CI=[0.004215404134432499, 0.12321201573766646]
- `scope_adjustment` / `B11_structural_gate_no_abstention` (coverage): n=111, correct=111, error=0, estimate=1.0, 95% Wilson CI=[0.9665498953066078, 1.0]
- `scope_adjustment` / `B11_structural_gate_no_abstention` (selective_accuracy): n=111, correct=51, error=60, estimate=0.4594594594594595, 95% Wilson CI=[0.36965969632385665, 0.5519713932458781]
- `entity_type` / `B12_full_framework` (coverage): n=276, correct=41, error=235, estimate=0.14855072463768115, 95% Wilson CI=[0.11142820996381964, 0.19532211639041885]
- `entity_type` / `B12_full_framework` (selective_accuracy): n=41, correct=38, error=3, estimate=0.926829268292683, 95% Wilson CI=[0.8057255146228096, 0.9748021693660901]
- `identity_pair` / `B12_full_framework` (coverage): n=399, correct=399, error=0, estimate=1.0, 95% Wilson CI=[0.9904640926682675, 1.0]
- `identity_pair` / `B12_full_framework` (selective_accuracy): n=399, correct=258, error=141, estimate=0.6466165413533834, 95% Wilson CI=[0.5985178435694403, 0.6919189956340366]
- `provenance_support` / `B12_full_framework` (coverage): n=394, correct=394, error=0, estimate=1.0, 95% Wilson CI=[0.9903442470976223, 1.0]
- `provenance_support` / `B12_full_framework` (selective_accuracy): n=394, correct=120, error=274, estimate=0.30456852791878175, 95% Wilson CI=[0.2611928602690694, 0.3517182715760224]
- `relation_contract` / `B12_full_framework` (coverage): n=66, correct=42, error=24, estimate=0.6363636363636364, 95% Wilson CI=[0.5157964063076522, 0.7419301690522909]
- `relation_contract` / `B12_full_framework` (selective_accuracy): n=42, correct=1, error=41, estimate=0.023809523809523808, 95% Wilson CI=[0.004215404134432499, 0.12321201573766646]
- `scope_adjustment` / `B12_full_framework` (coverage): n=111, correct=111, error=0, estimate=1.0, 95% Wilson CI=[0.9665498953066078, 1.0]
- `scope_adjustment` / `B12_full_framework` (selective_accuracy): n=111, correct=51, error=60, estimate=0.4594594594594595, 95% Wilson CI=[0.36965969632385665, 0.5519713932458781]
- `entity_type` / `B1_rule_only` (coverage): n=276, correct=69, error=207, estimate=0.25, 95% Wilson CI=[0.20258262637754718, 0.3042810078331998]
- `entity_type` / `B1_rule_only` (selective_accuracy): n=69, correct=37, error=32, estimate=0.5362318840579711, 95% Wilson CI=[0.4197840683642111, 0.648858159303249]
- `identity_pair` / `B1_rule_only` (coverage): n=399, correct=0, error=399, estimate=0.0, 95% Wilson CI=[0.0, 0.00953590733173263]
- `provenance_support` / `B1_rule_only` (coverage): n=394, correct=0, error=394, estimate=0.0, 95% Wilson CI=[0.0, 0.009655752902377775]
- `relation_contract` / `B1_rule_only` (coverage): n=66, correct=16, error=50, estimate=0.24242424242424243, 95% Wilson CI=[0.15509184941772042, 0.35809128601349777]
- `relation_contract` / `B1_rule_only` (selective_accuracy): n=16, correct=0, error=16, estimate=0.0, 95% Wilson CI=[0.0, 0.1936076805344365]
- `scope_adjustment` / `B1_rule_only` (coverage): n=111, correct=0, error=111, estimate=0.0, 95% Wilson CI=[0.0, 0.03345010469339236]
- `entity_type` / `B2_frozen_classifier` (coverage): n=276, correct=82, error=194, estimate=0.2971014492753623, 95% Wilson CI=[0.2462727672559363, 0.35350061703104674]
- `entity_type` / `B2_frozen_classifier` (selective_accuracy): n=82, correct=31, error=51, estimate=0.3780487804878049, 95% Wilson CI=[0.28078371592811896, 0.48622863131336896]
- `identity_pair` / `B2_frozen_classifier` (coverage): n=399, correct=0, error=399, estimate=0.0, 95% Wilson CI=[0.0, 0.00953590733173263]
- `provenance_support` / `B2_frozen_classifier` (coverage): n=394, correct=0, error=394, estimate=0.0, 95% Wilson CI=[0.0, 0.009655752902377775]
- `relation_contract` / `B2_frozen_classifier` (coverage): n=66, correct=0, error=66, estimate=0.0, 95% Wilson CI=[0.0, 0.05500255701354129]
- `scope_adjustment` / `B2_frozen_classifier` (coverage): n=111, correct=0, error=111, estimate=0.0, 95% Wilson CI=[0.0, 0.03345010469339236]
- `entity_type` / `B3_blind_llm` (coverage): n=276, correct=250, error=26, estimate=0.9057971014492754, 95% Wilson CI=[0.8655515461201069, 0.9349016853059269]
- `entity_type` / `B3_blind_llm` (selective_accuracy): n=250, correct=247, error=3, estimate=0.988, 95% Wilson CI=[0.9653192195729803, 0.9959106801194657]
- `identity_pair` / `B3_blind_llm` (coverage): n=399, correct=399, error=0, estimate=1.0, 95% Wilson CI=[0.9904640926682675, 1.0]
- `identity_pair` / `B3_blind_llm` (selective_accuracy): n=399, correct=380, error=19, estimate=0.9523809523809523, 95% Wilson CI=[0.9268285193132626, 0.9693056597675507]
- `provenance_support` / `B3_blind_llm` (coverage): n=394, correct=394, error=0, estimate=1.0, 95% Wilson CI=[0.9903442470976223, 1.0]
- `provenance_support` / `B3_blind_llm` (selective_accuracy): n=394, correct=369, error=25, estimate=0.9365482233502538, 95% Wilson CI=[0.9080108648905528, 0.9566551782606706]
- `relation_contract` / `B3_blind_llm` (coverage): n=66, correct=66, error=0, estimate=1.0, 95% Wilson CI=[0.9449974429864586, 0.9999999999999999]
- `relation_contract` / `B3_blind_llm` (selective_accuracy): n=66, correct=62, error=4, estimate=0.9393939393939394, 95% Wilson CI=[0.8542709132143579, 0.9761813851676816]
- `scope_adjustment` / `B3_blind_llm` (coverage): n=111, correct=111, error=0, estimate=1.0, 95% Wilson CI=[0.9665498953066078, 1.0]
- `scope_adjustment` / `B3_blind_llm` (selective_accuracy): n=111, correct=90, error=21, estimate=0.8108108108108109, 95% Wilson CI=[0.7280316720176518, 0.8727966412810504]
- `entity_type` / `B4_rule_plus_classifier` (coverage): n=276, correct=135, error=141, estimate=0.4891304347826087, 95% Wilson CI=[0.4307115852896667, 0.5478477031542788]
- `entity_type` / `B4_rule_plus_classifier` (selective_accuracy): n=135, correct=65, error=70, estimate=0.48148148148148145, 95% Wilson CI=[0.3988809024947728, 0.5651067994318021]
- `identity_pair` / `B4_rule_plus_classifier` (coverage): n=399, correct=0, error=399, estimate=0.0, 95% Wilson CI=[0.0, 0.00953590733173263]
- `provenance_support` / `B4_rule_plus_classifier` (coverage): n=394, correct=0, error=394, estimate=0.0, 95% Wilson CI=[0.0, 0.009655752902377775]
- `relation_contract` / `B4_rule_plus_classifier` (coverage): n=66, correct=0, error=66, estimate=0.0, 95% Wilson CI=[0.0, 0.05500255701354129]
- `scope_adjustment` / `B4_rule_plus_classifier` (coverage): n=111, correct=0, error=111, estimate=0.0, 95% Wilson CI=[0.0, 0.03345010469339236]
- `entity_type` / `B5_rule_plus_blind_llm` (coverage): n=276, correct=247, error=29, estimate=0.894927536231884, 95% Wilson CI=[0.8531717577243365, 0.9258407621456428]
- `entity_type` / `B5_rule_plus_blind_llm` (selective_accuracy): n=247, correct=212, error=35, estimate=0.8582995951417004, 95% Wilson CI=[0.8093078514117512, 0.8963171311256158]
- `identity_pair` / `B5_rule_plus_blind_llm` (coverage): n=399, correct=0, error=399, estimate=0.0, 95% Wilson CI=[0.0, 0.00953590733173263]
- `provenance_support` / `B5_rule_plus_blind_llm` (coverage): n=394, correct=0, error=394, estimate=0.0, 95% Wilson CI=[0.0, 0.009655752902377775]
- `relation_contract` / `B5_rule_plus_blind_llm` (coverage): n=66, correct=16, error=50, estimate=0.24242424242424243, 95% Wilson CI=[0.15509184941772042, 0.35809128601349777]
- `relation_contract` / `B5_rule_plus_blind_llm` (selective_accuracy): n=16, correct=0, error=16, estimate=0.0, 95% Wilson CI=[0.0, 0.1936076805344365]
- `scope_adjustment` / `B5_rule_plus_blind_llm` (coverage): n=111, correct=0, error=111, estimate=0.0, 95% Wilson CI=[0.0, 0.03345010469339236]
- `entity_type` / `B7_classifier_margin` (coverage): n=276, correct=82, error=194, estimate=0.2971014492753623, 95% Wilson CI=[0.2462727672559363, 0.35350061703104674]
- `entity_type` / `B7_classifier_margin` (selective_accuracy): n=82, correct=31, error=51, estimate=0.3780487804878049, 95% Wilson CI=[0.28078371592811896, 0.48622863131336896]
- `identity_pair` / `B7_classifier_margin` (coverage): n=399, correct=0, error=399, estimate=0.0, 95% Wilson CI=[0.0, 0.00953590733173263]
- `provenance_support` / `B7_classifier_margin` (coverage): n=394, correct=0, error=394, estimate=0.0, 95% Wilson CI=[0.0, 0.009655752902377775]
- `relation_contract` / `B7_classifier_margin` (coverage): n=66, correct=0, error=66, estimate=0.0, 95% Wilson CI=[0.0, 0.05500255701354129]
- `scope_adjustment` / `B7_classifier_margin` (coverage): n=111, correct=0, error=111, estimate=0.0, 95% Wilson CI=[0.0, 0.03345010469339236]
- `entity_type` / `B8_entropy_threshold` (coverage): n=276, correct=82, error=194, estimate=0.2971014492753623, 95% Wilson CI=[0.2462727672559363, 0.35350061703104674]
- `entity_type` / `B8_entropy_threshold` (selective_accuracy): n=82, correct=31, error=51, estimate=0.3780487804878049, 95% Wilson CI=[0.28078371592811896, 0.48622863131336896]
- `identity_pair` / `B8_entropy_threshold` (coverage): n=399, correct=0, error=399, estimate=0.0, 95% Wilson CI=[0.0, 0.00953590733173263]
- `provenance_support` / `B8_entropy_threshold` (coverage): n=394, correct=0, error=394, estimate=0.0, 95% Wilson CI=[0.0, 0.009655752902377775]
- `relation_contract` / `B8_entropy_threshold` (coverage): n=66, correct=0, error=66, estimate=0.0, 95% Wilson CI=[0.0, 0.05500255701354129]
- `scope_adjustment` / `B8_entropy_threshold` (coverage): n=111, correct=0, error=111, estimate=0.0, 95% Wilson CI=[0.0, 0.03345010469339236]
- `entity_type` / `B9_rule_model_agreement` (coverage): n=276, correct=53, error=223, estimate=0.19202898550724637, 95% Wilson CI=[0.14991318101892026, 0.2425999915595361]
- `entity_type` / `B9_rule_model_agreement` (selective_accuracy): n=53, correct=21, error=32, estimate=0.39622641509433965, 95% Wilson CI=[0.27589406738001676, 0.5305852132679447]
- `identity_pair` / `B9_rule_model_agreement` (coverage): n=399, correct=0, error=399, estimate=0.0, 95% Wilson CI=[0.0, 0.00953590733173263]
- `provenance_support` / `B9_rule_model_agreement` (coverage): n=394, correct=0, error=394, estimate=0.0, 95% Wilson CI=[0.0, 0.009655752902377775]
- `relation_contract` / `B9_rule_model_agreement` (coverage): n=66, correct=16, error=50, estimate=0.24242424242424243, 95% Wilson CI=[0.15509184941772042, 0.35809128601349777]
- `relation_contract` / `B9_rule_model_agreement` (selective_accuracy): n=16, correct=0, error=16, estimate=0.0, 95% Wilson CI=[0.0, 0.1936076805344365]
- `scope_adjustment` / `B9_rule_model_agreement` (coverage): n=111, correct=0, error=111, estimate=0.0, 95% Wilson CI=[0.0, 0.03345010469339236]

## 2. Wilson score intervals

- Interval type: Wilson score interval (no continuity correction),
  `independent_eval/metrics.py::wilson_ci`; endpoints clipped to [0, 1].
- Chosen for binomial proportions at small n; bootstrap intervals are
  reserved for the curve-area differences below (GOAL 18: choose by
  metric type).
- Cross-check vs experiment-13 outputs: **passed** over 26 cells, max |diff| = 1.1102230246251565e-16.

## 3. Paired bootstrap ΔAURC / ΔAUGRC (Full − baseline)

- Paired system comparison: both systems are re-evaluated on the
  **same resample index array** in every replicate
  (`metrics.paired_bootstrap_diff_ci` is a shared-index
  implementation); AURC and AUGRC use the identical index stream.
- 2000 fixed-seed replicates; seed =
  `derive_seed("paired_bootstrap::{task_type}::{baseline}")`.
- ΔAURC/ΔAUGRC = Full − baseline; negative deltas mean Full has the
  smaller area (better).  Percentile 95% CIs over the finite replicates.
- Per-replicate values: `PAIRED_BOOTSTRAP_REPLICATES.csv` (GOAL 13.2:
  replicates are saved, not summary-only).
- Pairs failing the experiment-13 area gate are listed with an
  explicit `not_applicable_*` status instead of being dropped.

- `provenance_support` vs `B3_blind_llm` (aurc): Δ=0.37517285201011213, 95% CI=[0.34260854818886693, 0.4073135173765715], n=394, valid replicates=2000
- `provenance_support` vs `B3_blind_llm` (augrc): Δ=0.3319526398515808, 95% CI=[0.3070497500579763, 0.3582680563786751], n=394, valid replicates=2000
- Not applicable (explicit status): entity_type/B1_rule_only=not_applicable_incomplete_score_coverage, entity_type/B3_blind_llm=not_applicable_incomplete_score_coverage, entity_type/B4_rule_plus_classifier=not_applicable_incomplete_score_coverage, entity_type/B5_rule_plus_blind_llm=not_applicable_incomplete_score_coverage, entity_type/B8_entropy_threshold=not_applicable_incomplete_score_coverage, identity_pair/B1_rule_only=not_applicable_no_numeric_confidence, identity_pair/B3_blind_llm=not_applicable_no_numeric_confidence, identity_pair/B4_rule_plus_classifier=not_applicable_no_numeric_confidence, identity_pair/B5_rule_plus_blind_llm=not_applicable_no_numeric_confidence, identity_pair/B8_entropy_threshold=not_applicable_no_numeric_confidence, provenance_support/B1_rule_only=not_applicable_no_numeric_confidence, provenance_support/B4_rule_plus_classifier=not_applicable_no_numeric_confidence, provenance_support/B5_rule_plus_blind_llm=not_applicable_no_numeric_confidence, provenance_support/B8_entropy_threshold=not_applicable_no_numeric_confidence, relation_contract/B1_rule_only=not_applicable_insufficient_discrete_points, relation_contract/B3_blind_llm=not_applicable_insufficient_discrete_points, relation_contract/B4_rule_plus_classifier=not_applicable_no_numeric_confidence, relation_contract/B5_rule_plus_blind_llm=not_applicable_insufficient_discrete_points, relation_contract/B8_entropy_threshold=not_applicable_no_numeric_confidence, scope_adjustment/B1_rule_only=not_applicable_no_numeric_confidence, scope_adjustment/B3_blind_llm=not_applicable_no_numeric_confidence, scope_adjustment/B4_rule_plus_classifier=not_applicable_no_numeric_confidence, scope_adjustment/B5_rule_plus_blind_llm=not_applicable_no_numeric_confidence, scope_adjustment/B8_entropy_threshold=not_applicable_no_numeric_confidence

## 4. McNemar test (binary paired outcomes)

- Exact binomial McNemar on the correct/wrong outcome over the shared
  sample set (`metrics.mcnemar_test`, exact binomial tails via scipy).
- `scope_adjustment` uses the strict AFTER_BETTER binarisation
  (design §4.3); win/tie/loss counts are reported alongside b/c.

- `entity_type` vs `B1_rule_only`: b=90, c=0, n=276, statistic=0.0, p=1.6155871338926322e-27, win/tie/loss=90/186/0
- `entity_type` vs `B3_blind_llm`: b=2, c=141, n=276, statistic=2.0, p=1.846933796755538e-39, win/tie/loss=2/133/141
- `entity_type` vs `B4_rule_plus_classifier`: b=61, c=45, n=276, statistic=45.0, p=0.14478233933005036, win/tie/loss=61/170/45
- `entity_type` vs `B5_rule_plus_blind_llm`: b=5, c=108, n=276, statistic=5.0, p=2.8319615385298505e-26, win/tie/loss=5/163/108
- `entity_type` vs `B8_entropy_threshold`: b=93, c=48, n=276, statistic=48.0, p=0.0001881808393573049, win/tie/loss=93/135/48
- `identity_pair` vs `B1_rule_only`: b=258, c=0, n=399, statistic=0.0, p=4.3180842775472223e-78, win/tie/loss=258/141/0
- `identity_pair` vs `B3_blind_llm`: b=10, c=132, n=399, statistic=10.0, p=2.574736689877734e-28, win/tie/loss=10/257/132
- `identity_pair` vs `B4_rule_plus_classifier`: b=258, c=0, n=399, statistic=0.0, p=4.3180842775472223e-78, win/tie/loss=258/141/0
- `identity_pair` vs `B5_rule_plus_blind_llm`: b=258, c=0, n=399, statistic=0.0, p=4.3180842775472223e-78, win/tie/loss=258/141/0
- `identity_pair` vs `B8_entropy_threshold`: b=258, c=0, n=399, statistic=0.0, p=4.3180842775472223e-78, win/tie/loss=258/141/0
- `provenance_support` vs `B1_rule_only`: b=120, c=0, n=394, statistic=0.0, p=1.504632769052528e-36, win/tie/loss=120/274/0
- `provenance_support` vs `B3_blind_llm`: b=8, c=257, n=394, statistic=8.0, p=1.8872258900287898e-65, win/tie/loss=8/129/257
- `provenance_support` vs `B4_rule_plus_classifier`: b=120, c=0, n=394, statistic=0.0, p=1.504632769052528e-36, win/tie/loss=120/274/0
- `provenance_support` vs `B5_rule_plus_blind_llm`: b=120, c=0, n=394, statistic=0.0, p=1.504632769052528e-36, win/tie/loss=120/274/0
- `provenance_support` vs `B8_entropy_threshold`: b=120, c=0, n=394, statistic=0.0, p=1.504632769052528e-36, win/tie/loss=120/274/0
- `relation_contract` vs `B1_rule_only`: b=7, c=36, n=66, statistic=7.0, p=8.963039363152348e-06, win/tie/loss=7/23/36
- `relation_contract` vs `B3_blind_llm`: b=1, c=56, n=66, statistic=1.0, p=8.049116928532385e-16, win/tie/loss=1/9/56
- `relation_contract` vs `B4_rule_plus_classifier`: b=7, c=0, n=66, statistic=0.0, p=0.015625, win/tie/loss=7/59/0
- `relation_contract` vs `B5_rule_plus_blind_llm`: b=7, c=36, n=66, statistic=7.0, p=8.963039363152348e-06, win/tie/loss=7/23/36
- `relation_contract` vs `B8_entropy_threshold`: b=7, c=0, n=66, statistic=0.0, p=0.015625, win/tie/loss=7/59/0
- `scope_adjustment` vs `B1_rule_only`: b=51, c=0, n=111, statistic=0.0, p=8.881784197001252e-16, win/tie/loss=51/60/0
- `scope_adjustment` vs `B3_blind_llm`: b=7, c=46, n=111, statistic=7.0, p=4.003196174551249e-08, win/tie/loss=7/58/46
- `scope_adjustment` vs `B4_rule_plus_classifier`: b=51, c=0, n=111, statistic=0.0, p=8.881784197001252e-16, win/tie/loss=51/60/0
- `scope_adjustment` vs `B5_rule_plus_blind_llm`: b=51, c=0, n=111, statistic=0.0, p=8.881784197001252e-16, win/tie/loss=51/60/0
- `scope_adjustment` vs `B8_entropy_threshold`: b=51, c=0, n=111, statistic=0.0, p=8.881784197001252e-16, win/tie/loss=51/60/0

## 5. Multi-judge agreement (Fleiss kappa, Krippendorff alpha, LOJO)

- Summarised by reference from the experiment-08 outputs
  (`JUDGE_RELIABILITY_SUMMARY.csv`: Fleiss kappa and nominal
  Krippendorff alpha; `JUDGE_PAIRWISE_AGREEMENT.csv`: pairwise
  agreement and Cohen's kappa; `LEAVE_ONE_JUDGE_OUT.csv`: stability).
- No agreement statistic is recomputed here; `task_type=ALL` rows are
  unweighted means (or sums for counts) of the published values.

- [pairwise] A_vs_B agreement = 0.6675789854342865 (n=2830)
- [pairwise] A_vs_B cohens_kappa = 0.49511855822832984 (n=2830)
- [pairwise] A_vs_C agreement = 0.6241283375602747 (n=2792)
- [pairwise] A_vs_C cohens_kappa = 0.4015612020896847 (n=2792)
- [pairwise] B_vs_C agreement = 0.601220914606713 (n=2792)
- [pairwise] B_vs_C cohens_kappa = 0.42428305070199873 (n=2792)
- [reliability] - fleiss_kappa = 0.4236298475554999
- [reliability] - judges = A;B;C
- [reliability] - krippendorff_alpha_nominal = 0.42368314023354614
- [reliability] - mean_leave_one_judge_out_stability = 0.6790894580864014
- [reliability] - mean_pairwise_agreement = 0.6309760792004248
- [reliability] - min_leave_one_judge_out_stability = 0.6309356877032821
- [reliability] - n_judges = 15.0
- [reliability] - n_strong_consensus = 1246.0
- [reliability] - n_tasks = 2830.0
- [reliability] - n_unresolved = 237.0
- [reliability] - n_weak_consensus = 1347.0
- [leave_one_judge_out] removed_A stability = 0.6441953562115694 (n=2830)
- [leave_one_judge_out] removed_B stability = 0.6706733050469071 (n=2830)
- [leave_one_judge_out] removed_C stability = 0.7223997130007277 (n=2830)

## 6. Class imbalance: macro-F1 and per-class precision / recall / F1

- Accuracy alone is not reported for imbalanced label spaces (GOAL 18).
- Macro-F1 on accepted and on the full denominator below come from
  `<prefix>SELECTIVE_GOAL13_METRICS.csv`
  (`metrics.macro_f1_on_accepted` / `macro_f1_on_full_denominator`).
- Per-class precision / recall / F1 accompany every accuracy-style
  claim in the paper tables (GOAL 18 requirement).

- `entity_type` / `B10_selective_no_structural_gate`: macro-F1 on accepted = 0.7306397306397306, macro-F1 on full denominator = 0.24698215552105496
- `provenance_support` / `B10_selective_no_structural_gate`: macro-F1 on accepted = 0.18604040142998665, macro-F1 on full denominator = 0.18604040142998665
- `relation_contract` / `B10_selective_no_structural_gate`: macro-F1 on accepted = 0.10353535353535354, macro-F1 on full denominator = 0.10353535353535354
- `entity_type` / `B11_structural_gate_no_abstention`: macro-F1 on accepted = 0.7306397306397306, macro-F1 on full denominator = 0.24698215552105496
- `identity_pair` / `B11_structural_gate_no_abstention`: macro-F1 on accepted = 0.37515564344832636, macro-F1 on full denominator = 0.37515564344832636
- `provenance_support` / `B11_structural_gate_no_abstention`: macro-F1 on accepted = 0.18604040142998665, macro-F1 on full denominator = 0.18604040142998665
- `relation_contract` / `B11_structural_gate_no_abstention`: macro-F1 on accepted = 0.020833333333333332, macro-F1 on full denominator = 0.020202020202020204
- `scope_adjustment` / `B11_structural_gate_no_abstention`: macro-F1 on accepted = 0.20987654320987656, macro-F1 on full denominator = 0.20987654320987656
- `entity_type` / `B12_full_framework`: macro-F1 on accepted = 0.7306397306397306, macro-F1 on full denominator = 0.24698215552105496
- `provenance_support` / `B12_full_framework`: macro-F1 on accepted = 0.18604040142998665, macro-F1 on full denominator = 0.18604040142998665
- `relation_contract` / `B12_full_framework`: macro-F1 on accepted = 0.020833333333333332, macro-F1 on full denominator = 0.020202020202020204
- `entity_type` / `B1_rule_only`: macro-F1 on accepted = 0.344774011299435, macro-F1 on full denominator = 0.1905722288915566
- `relation_contract` / `B1_rule_only`: macro-F1 on accepted = 0.0, macro-F1 on full denominator = 0.0
- `entity_type` / `B2_frozen_classifier`: macro-F1 on accepted = 0.18843919540905266, macro-F1 on full denominator = 0.10052243978723133
- `entity_type` / `B3_blind_llm`: macro-F1 on accepted = 0.9274155592469546, macro-F1 on full denominator = 0.845099699959035
- `identity_pair` / `B3_blind_llm`: macro-F1 on accepted = 0.6822713981924508, macro-F1 on full denominator = 0.6822713981924508
- `provenance_support` / `B3_blind_llm`: macro-F1 on accepted = 0.8821628862556661, macro-F1 on full denominator = 0.8821628862556661
- `relation_contract` / `B3_blind_llm`: macro-F1 on accepted = 0.9042016806722689, macro-F1 on full denominator = 0.9042016806722689
- `scope_adjustment` / `B3_blind_llm`: macro-F1 on accepted = 0.6672364672364672, macro-F1 on full denominator = 0.6672364672364672
- `entity_type` / `B4_rule_plus_classifier`: macro-F1 on accepted = 0.36984966533214364, macro-F1 on full denominator = 0.2692969426235118
- `entity_type` / `B5_rule_plus_blind_llm`: macro-F1 on accepted = 0.7366432683469138, macro-F1 on full denominator = 0.7079935463590925
- `relation_contract` / `B5_rule_plus_blind_llm`: macro-F1 on accepted = 0.0, macro-F1 on full denominator = 0.0
- `entity_type` / `B7_classifier_margin`: macro-F1 on accepted = 0.18843919540905266, macro-F1 on full denominator = 0.10052243978723133
- `entity_type` / `B8_entropy_threshold`: macro-F1 on accepted = 0.18843919540905266, macro-F1 on full denominator = 0.10052243978723133
- `entity_type` / `B9_rule_model_agreement`: macro-F1 on accepted = 0.16195856873822975, macro-F1 on full denominator = 0.0645591569961318
- `relation_contract` / `B9_rule_model_agreement`: macro-F1 on accepted = 0.0, macro-F1 on full denominator = 0.0

## 7. Reproducibility

- Master seed 20260907; per-comparison seeds derived with
  `derive_seed` (SHA-256 of the label and the master seed); the full
  seed table is in `STATISTICAL_ANALYSIS_MANIFEST.json`.
- Input SHA-256 digests are recorded in the manifest.
- Missing inputs are hard errors; no silent fallbacks exist.

## References

- Wilson, E. B. (1927). Probable inference, the law of succession, and
  statistical inference. JASA 22, 209–212.
- McNemar, Q. (1947). Note on the sampling error of the difference
  between correlated proportions or percentages. Psychometrika 12, 153–157.
- Fleiss, J. L. (1971). Measuring nominal scale agreement among many
  raters. Psychological Bulletin 76, 378–382.
- Krippendorff, K. Content Analysis: An Introduction to Its Methodology.
- Efron, B., & Tibshirani, R. (1993). An Introduction to the Bootstrap.
