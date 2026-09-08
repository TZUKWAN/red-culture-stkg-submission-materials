# Statistical analysis (experiment 14, GOAL section 18)

- Report mode: **FILLED**
- Correctness reference: **imcr_all**
- Primary per-sample input: `IMCR_BASELINE_RUNS.csv`
- Bootstrap replicates per comparison: **2000** (fixed seed, shared resample indices, every replicate saved to `PAIRED_BOOTSTRAP_REPLICATES.csv`)
- Generated at: 2026-09-08T00:52:52+00:00

## 1. Operating-point table: n / coverage / correct / error / estimate / 95% CI

GOAL 18 requires, for every method x task cell, the denominator `n`,
the coverage, the raw correct/error counts, the point estimate and a
95% interval.  Coverage (k = accepted, n = full frozen task set) and
post-accept selective accuracy (k = correct, n = accepted) are
reported as separate rows of `WILSON_CI_TABLE.csv` (`metric` column).

- `entity_type` / `B10_selective_no_structural_gate` (coverage): n=309, correct=48, error=261, estimate=0.1553398058252427, 95% Wilson CI=[0.11921031220678861, 0.1999336375659252]
- `entity_type` / `B10_selective_no_structural_gate` (selective_accuracy): n=48, correct=43, error=5, estimate=0.8958333333333334, 95% Wilson CI=[0.7783257830561368, 0.9546782809581869]
- `identity_pair` / `B10_selective_no_structural_gate` (coverage): n=456, correct=456, error=0, estimate=1.0, 95% Wilson CI=[0.9916461233605471, 1.0]
- `identity_pair` / `B10_selective_no_structural_gate` (selective_accuracy): n=456, correct=292, error=164, estimate=0.6403508771929824, 95% Wilson CI=[0.5953003209073597, 0.6830564856499868]
- `provenance_support` / `B10_selective_no_structural_gate` (coverage): n=491, correct=491, error=0, estimate=1.0, 95% Wilson CI=[0.9922369907528583, 1.0]
- `provenance_support` / `B10_selective_no_structural_gate` (selective_accuracy): n=491, correct=153, error=338, estimate=0.31160896130346233, 95% Wilson CI=[0.2722379664840594, 0.3539049188738249]
- `relation_contract` / `B10_selective_no_structural_gate` (coverage): n=248, correct=248, error=0, estimate=1.0, 95% Wilson CI=[0.9847465193432304, 1.0]
- `relation_contract` / `B10_selective_no_structural_gate` (selective_accuracy): n=248, correct=86, error=162, estimate=0.3467741935483871, 95% Wilson CI=[0.29028362664424495, 0.40793921420218465]
- `scope_adjustment` / `B10_selective_no_structural_gate` (coverage): n=136, correct=136, error=0, estimate=1.0, 95% Wilson CI=[0.9725299002664176, 1.0]
- `scope_adjustment` / `B10_selective_no_structural_gate` (selective_accuracy): n=136, correct=59, error=77, estimate=0.4338235294117647, 95% Wilson CI=[0.3534798001050565, 0.5178030072126235]
- `entity_type` / `B11_structural_gate_no_abstention` (coverage): n=309, correct=48, error=261, estimate=0.1553398058252427, 95% Wilson CI=[0.11921031220678861, 0.1999336375659252]
- `entity_type` / `B11_structural_gate_no_abstention` (selective_accuracy): n=48, correct=43, error=5, estimate=0.8958333333333334, 95% Wilson CI=[0.7783257830561368, 0.9546782809581869]
- `identity_pair` / `B11_structural_gate_no_abstention` (coverage): n=456, correct=456, error=0, estimate=1.0, 95% Wilson CI=[0.9916461233605471, 1.0]
- `identity_pair` / `B11_structural_gate_no_abstention` (selective_accuracy): n=456, correct=292, error=164, estimate=0.6403508771929824, 95% Wilson CI=[0.5953003209073597, 0.6830564856499868]
- `provenance_support` / `B11_structural_gate_no_abstention` (coverage): n=491, correct=491, error=0, estimate=1.0, 95% Wilson CI=[0.9922369907528583, 1.0]
- `provenance_support` / `B11_structural_gate_no_abstention` (selective_accuracy): n=491, correct=153, error=338, estimate=0.31160896130346233, 95% Wilson CI=[0.2722379664840594, 0.3539049188738249]
- `relation_contract` / `B11_structural_gate_no_abstention` (coverage): n=248, correct=186, error=62, estimate=0.75, 95% Wilson CI=[0.6925716187367369, 0.7998016409348784]
- `relation_contract` / `B11_structural_gate_no_abstention` (selective_accuracy): n=186, correct=80, error=106, estimate=0.43010752688172044, 95% Wilson CI=[0.3610808753727093, 0.501962739222788]
- `scope_adjustment` / `B11_structural_gate_no_abstention` (coverage): n=136, correct=136, error=0, estimate=1.0, 95% Wilson CI=[0.9725299002664176, 1.0]
- `scope_adjustment` / `B11_structural_gate_no_abstention` (selective_accuracy): n=136, correct=59, error=77, estimate=0.4338235294117647, 95% Wilson CI=[0.3534798001050565, 0.5178030072126235]
- `entity_type` / `B12_full_framework` (coverage): n=309, correct=48, error=261, estimate=0.1553398058252427, 95% Wilson CI=[0.11921031220678861, 0.1999336375659252]
- `entity_type` / `B12_full_framework` (selective_accuracy): n=48, correct=43, error=5, estimate=0.8958333333333334, 95% Wilson CI=[0.7783257830561368, 0.9546782809581869]
- `identity_pair` / `B12_full_framework` (coverage): n=456, correct=456, error=0, estimate=1.0, 95% Wilson CI=[0.9916461233605471, 1.0]
- `identity_pair` / `B12_full_framework` (selective_accuracy): n=456, correct=292, error=164, estimate=0.6403508771929824, 95% Wilson CI=[0.5953003209073597, 0.6830564856499868]
- `provenance_support` / `B12_full_framework` (coverage): n=491, correct=491, error=0, estimate=1.0, 95% Wilson CI=[0.9922369907528583, 1.0]
- `provenance_support` / `B12_full_framework` (selective_accuracy): n=491, correct=153, error=338, estimate=0.31160896130346233, 95% Wilson CI=[0.2722379664840594, 0.3539049188738249]
- `relation_contract` / `B12_full_framework` (coverage): n=248, correct=186, error=62, estimate=0.75, 95% Wilson CI=[0.6925716187367369, 0.7998016409348784]
- `relation_contract` / `B12_full_framework` (selective_accuracy): n=186, correct=80, error=106, estimate=0.43010752688172044, 95% Wilson CI=[0.3610808753727093, 0.501962739222788]
- `scope_adjustment` / `B12_full_framework` (coverage): n=136, correct=136, error=0, estimate=1.0, 95% Wilson CI=[0.9725299002664176, 1.0]
- `scope_adjustment` / `B12_full_framework` (selective_accuracy): n=136, correct=59, error=77, estimate=0.4338235294117647, 95% Wilson CI=[0.3534798001050565, 0.5178030072126235]
- `entity_type` / `B1_rule_only` (coverage): n=309, correct=78, error=231, estimate=0.2524271844660194, 95% Wilson CI=[0.20723410402125617, 0.3037002824352003]
- `entity_type` / `B1_rule_only` (selective_accuracy): n=78, correct=42, error=36, estimate=0.5384615384615384, 95% Wilson CI=[0.4286364394039756, 0.6446760367720094]
- `identity_pair` / `B1_rule_only` (coverage): n=456, correct=0, error=456, estimate=0.0, 95% Wilson CI=[0.0, 0.008353876639452869]
- `provenance_support` / `B1_rule_only` (coverage): n=491, correct=0, error=491, estimate=0.0, 95% Wilson CI=[0.0, 0.007763009247141676]
- `relation_contract` / `B1_rule_only` (coverage): n=248, correct=71, error=177, estimate=0.2862903225806452, 95% Wilson CI=[0.2336274937814452, 0.34547278424120653]
- `relation_contract` / `B1_rule_only` (selective_accuracy): n=71, correct=1, error=70, estimate=0.014084507042253521, 95% Wilson CI=[0.002490603270544213, 0.07556050520249005]
- `scope_adjustment` / `B1_rule_only` (coverage): n=136, correct=0, error=136, estimate=0.0, 95% Wilson CI=[0.0, 0.027470099733582408]
- `entity_type` / `B2_frozen_classifier` (coverage): n=309, correct=89, error=220, estimate=0.28802588996763756, 95% Wilson CI=[0.24038094849684602, 0.3408765980769828]
- `entity_type` / `B2_frozen_classifier` (selective_accuracy): n=89, correct=32, error=57, estimate=0.3595505617977528, 95% Wilson CI=[0.26757786703977027, 0.46314588162209835]
- `identity_pair` / `B2_frozen_classifier` (coverage): n=456, correct=0, error=456, estimate=0.0, 95% Wilson CI=[0.0, 0.008353876639452869]
- `provenance_support` / `B2_frozen_classifier` (coverage): n=491, correct=0, error=491, estimate=0.0, 95% Wilson CI=[0.0, 0.007763009247141676]
- `relation_contract` / `B2_frozen_classifier` (coverage): n=248, correct=0, error=248, estimate=0.0, 95% Wilson CI=[8.673617379884035e-19, 0.015253480656769718]
- `scope_adjustment` / `B2_frozen_classifier` (coverage): n=136, correct=0, error=136, estimate=0.0, 95% Wilson CI=[0.0, 0.027470099733582408]
- `entity_type` / `B3_blind_llm` (coverage): n=309, correct=274, error=35, estimate=0.8867313915857605, 95% Wilson CI=[0.8465444417965299, 0.9174207976603782]
- `entity_type` / `B3_blind_llm` (selective_accuracy): n=274, correct=253, error=21, estimate=0.9233576642335767, 95% Wilson CI=[0.8856811785502999, 0.9493273942693597]
- `identity_pair` / `B3_blind_llm` (coverage): n=456, correct=456, error=0, estimate=1.0, 95% Wilson CI=[0.9916461233605471, 1.0]
- `identity_pair` / `B3_blind_llm` (selective_accuracy): n=456, correct=395, error=61, estimate=0.8662280701754386, 95% Wilson CI=[0.831905532895539, 0.8944317592150369]
- `provenance_support` / `B3_blind_llm` (coverage): n=491, correct=491, error=0, estimate=1.0, 95% Wilson CI=[0.9922369907528583, 1.0]
- `provenance_support` / `B3_blind_llm` (selective_accuracy): n=491, correct=392, error=99, estimate=0.7983706720977597, 95% Wilson CI=[0.7606282269706253, 0.8314806086517526]
- `relation_contract` / `B3_blind_llm` (coverage): n=248, correct=248, error=0, estimate=1.0, 95% Wilson CI=[0.9847465193432304, 1.0]
- `relation_contract` / `B3_blind_llm` (selective_accuracy): n=248, correct=71, error=177, estimate=0.2862903225806452, 95% Wilson CI=[0.2336274937814452, 0.34547278424120653]
- `scope_adjustment` / `B3_blind_llm` (coverage): n=136, correct=136, error=0, estimate=1.0, 95% Wilson CI=[0.9725299002664176, 1.0]
- `scope_adjustment` / `B3_blind_llm` (selective_accuracy): n=136, correct=95, error=41, estimate=0.6985294117647058, 95% Wilson CI=[0.6168225109326528, 0.7693290671143069]
- `entity_type` / `B4_rule_plus_classifier` (coverage): n=309, correct=149, error=160, estimate=0.48220064724919093, 95% Wilson CI=[0.4270480056820821, 0.5377904142592318]
- `entity_type` / `B4_rule_plus_classifier` (selective_accuracy): n=149, correct=70, error=79, estimate=0.4697986577181208, 95% Wilson CI=[0.3914308933978212, 0.5496845600305686]
- `identity_pair` / `B4_rule_plus_classifier` (coverage): n=456, correct=0, error=456, estimate=0.0, 95% Wilson CI=[0.0, 0.008353876639452869]
- `provenance_support` / `B4_rule_plus_classifier` (coverage): n=491, correct=0, error=491, estimate=0.0, 95% Wilson CI=[0.0, 0.007763009247141676]
- `relation_contract` / `B4_rule_plus_classifier` (coverage): n=248, correct=0, error=248, estimate=0.0, 95% Wilson CI=[8.673617379884035e-19, 0.015253480656769718]
- `scope_adjustment` / `B4_rule_plus_classifier` (coverage): n=136, correct=0, error=136, estimate=0.0, 95% Wilson CI=[0.0, 0.027470099733582408]
- `entity_type` / `B5_rule_plus_blind_llm` (coverage): n=309, correct=271, error=38, estimate=0.8770226537216829, 95% Wilson CI=[0.8357079764792364, 0.9090782193092973]
- `entity_type` / `B5_rule_plus_blind_llm` (selective_accuracy): n=271, correct=222, error=49, estimate=0.8191881918819188, 95% Wilson CI=[0.7690086219304941, 0.8604451756963942]
- `identity_pair` / `B5_rule_plus_blind_llm` (coverage): n=456, correct=0, error=456, estimate=0.0, 95% Wilson CI=[0.0, 0.008353876639452869]
- `provenance_support` / `B5_rule_plus_blind_llm` (coverage): n=491, correct=0, error=491, estimate=0.0, 95% Wilson CI=[0.0, 0.007763009247141676]
- `relation_contract` / `B5_rule_plus_blind_llm` (coverage): n=248, correct=71, error=177, estimate=0.2862903225806452, 95% Wilson CI=[0.2336274937814452, 0.34547278424120653]
- `relation_contract` / `B5_rule_plus_blind_llm` (selective_accuracy): n=71, correct=1, error=70, estimate=0.014084507042253521, 95% Wilson CI=[0.002490603270544213, 0.07556050520249005]
- `scope_adjustment` / `B5_rule_plus_blind_llm` (coverage): n=136, correct=0, error=136, estimate=0.0, 95% Wilson CI=[0.0, 0.027470099733582408]
- `entity_type` / `B7_classifier_margin` (coverage): n=309, correct=89, error=220, estimate=0.28802588996763756, 95% Wilson CI=[0.24038094849684602, 0.3408765980769828]
- `entity_type` / `B7_classifier_margin` (selective_accuracy): n=89, correct=32, error=57, estimate=0.3595505617977528, 95% Wilson CI=[0.26757786703977027, 0.46314588162209835]
- `identity_pair` / `B7_classifier_margin` (coverage): n=456, correct=0, error=456, estimate=0.0, 95% Wilson CI=[0.0, 0.008353876639452869]
- `provenance_support` / `B7_classifier_margin` (coverage): n=491, correct=0, error=491, estimate=0.0, 95% Wilson CI=[0.0, 0.007763009247141676]
- `relation_contract` / `B7_classifier_margin` (coverage): n=248, correct=0, error=248, estimate=0.0, 95% Wilson CI=[8.673617379884035e-19, 0.015253480656769718]
- `scope_adjustment` / `B7_classifier_margin` (coverage): n=136, correct=0, error=136, estimate=0.0, 95% Wilson CI=[0.0, 0.027470099733582408]
- `entity_type` / `B8_entropy_threshold` (coverage): n=309, correct=89, error=220, estimate=0.28802588996763756, 95% Wilson CI=[0.24038094849684602, 0.3408765980769828]
- `entity_type` / `B8_entropy_threshold` (selective_accuracy): n=89, correct=32, error=57, estimate=0.3595505617977528, 95% Wilson CI=[0.26757786703977027, 0.46314588162209835]
- `identity_pair` / `B8_entropy_threshold` (coverage): n=456, correct=0, error=456, estimate=0.0, 95% Wilson CI=[0.0, 0.008353876639452869]
- `provenance_support` / `B8_entropy_threshold` (coverage): n=491, correct=0, error=491, estimate=0.0, 95% Wilson CI=[0.0, 0.007763009247141676]
- `relation_contract` / `B8_entropy_threshold` (coverage): n=248, correct=0, error=248, estimate=0.0, 95% Wilson CI=[8.673617379884035e-19, 0.015253480656769718]
- `scope_adjustment` / `B8_entropy_threshold` (coverage): n=136, correct=0, error=136, estimate=0.0, 95% Wilson CI=[0.0, 0.027470099733582408]
- `entity_type` / `B9_rule_model_agreement` (coverage): n=309, correct=58, error=251, estimate=0.18770226537216828, 95% Wilson CI=[0.14809830342328506, 0.2349757919106763]
- `entity_type` / `B9_rule_model_agreement` (selective_accuracy): n=58, correct=24, error=34, estimate=0.41379310344827586, 95% Wilson CI=[0.2962802637408331, 0.5420159182914434]
- `identity_pair` / `B9_rule_model_agreement` (coverage): n=456, correct=0, error=456, estimate=0.0, 95% Wilson CI=[0.0, 0.008353876639452869]
- `provenance_support` / `B9_rule_model_agreement` (coverage): n=491, correct=0, error=491, estimate=0.0, 95% Wilson CI=[0.0, 0.007763009247141676]
- `relation_contract` / `B9_rule_model_agreement` (coverage): n=248, correct=71, error=177, estimate=0.2862903225806452, 95% Wilson CI=[0.2336274937814452, 0.34547278424120653]
- `relation_contract` / `B9_rule_model_agreement` (selective_accuracy): n=71, correct=1, error=70, estimate=0.014084507042253521, 95% Wilson CI=[0.002490603270544213, 0.07556050520249005]
- `scope_adjustment` / `B9_rule_model_agreement` (coverage): n=136, correct=0, error=136, estimate=0.0, 95% Wilson CI=[0.0, 0.027470099733582408]

## 2. Wilson score intervals

- Interval type: Wilson score interval (no continuity correction),
  `independent_eval/metrics.py::wilson_ci`; endpoints clipped to [0, 1].
- Chosen for binomial proportions at small n; bootstrap intervals are
  reserved for the curve-area differences below (GOAL 18: choose by
  metric type).
- Cross-check vs experiment-13 outputs: **passed** over 26 cells, max |diff| = 5.551115123125783e-17.

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

- `provenance_support` vs `B3_blind_llm` (aurc): Δ=0.322372508570535, 95% CI=[0.2883463823669296, 0.35476048089775597], n=491, valid replicates=2000
- `provenance_support` vs `B3_blind_llm` (augrc): Δ=0.2896142790182552, 95% CI=[0.261877180283805, 0.3158031947768592], n=491, valid replicates=2000
- `relation_contract` vs `B3_blind_llm` (aurc): Δ=-0.38761056770159347, 95% CI=[-0.48710316436469453, -0.28638987404388766], n=248, valid replicates=2000
- `relation_contract` vs `B3_blind_llm` (augrc): Δ=-0.2079702133194589, 95% CI=[-0.25644084124609784, -0.1558628300598335], n=248, valid replicates=2000
- Not applicable (explicit status): entity_type/B1_rule_only=not_applicable_incomplete_score_coverage, entity_type/B3_blind_llm=not_applicable_incomplete_score_coverage, entity_type/B4_rule_plus_classifier=not_applicable_incomplete_score_coverage, entity_type/B5_rule_plus_blind_llm=not_applicable_incomplete_score_coverage, entity_type/B8_entropy_threshold=not_applicable_incomplete_score_coverage, identity_pair/B1_rule_only=not_applicable_no_numeric_confidence, identity_pair/B3_blind_llm=not_applicable_no_numeric_confidence, identity_pair/B4_rule_plus_classifier=not_applicable_no_numeric_confidence, identity_pair/B5_rule_plus_blind_llm=not_applicable_no_numeric_confidence, identity_pair/B8_entropy_threshold=not_applicable_no_numeric_confidence, provenance_support/B1_rule_only=not_applicable_no_numeric_confidence, provenance_support/B4_rule_plus_classifier=not_applicable_no_numeric_confidence, provenance_support/B5_rule_plus_blind_llm=not_applicable_no_numeric_confidence, provenance_support/B8_entropy_threshold=not_applicable_no_numeric_confidence, relation_contract/B1_rule_only=not_applicable_insufficient_discrete_points, relation_contract/B4_rule_plus_classifier=not_applicable_no_numeric_confidence, relation_contract/B5_rule_plus_blind_llm=not_applicable_insufficient_discrete_points, relation_contract/B8_entropy_threshold=not_applicable_no_numeric_confidence, scope_adjustment/B1_rule_only=not_applicable_no_numeric_confidence, scope_adjustment/B3_blind_llm=not_applicable_no_numeric_confidence, scope_adjustment/B4_rule_plus_classifier=not_applicable_no_numeric_confidence, scope_adjustment/B5_rule_plus_blind_llm=not_applicable_no_numeric_confidence, scope_adjustment/B8_entropy_threshold=not_applicable_no_numeric_confidence

## 4. McNemar test (binary paired outcomes)

- Exact binomial McNemar on the correct/wrong outcome over the shared
  sample set (`metrics.mcnemar_test`, exact binomial tails via scipy).
- `scope_adjustment` uses the strict AFTER_BETTER binarisation
  (design §4.3); win/tie/loss counts are reported alongside b/c.

- `entity_type` vs `B1_rule_only`: b=98, c=0, n=309, statistic=0.0, p=6.310887241768095e-30, win/tie/loss=98/211/0
- `entity_type` vs `B3_blind_llm`: b=13, c=143, n=309, statistic=13.0, p=7.48584943954279e-29, win/tie/loss=13/153/143
- `entity_type` vs `B4_rule_plus_classifier`: b=65, c=47, n=309, statistic=47.0, p=0.10778227965475419, win/tie/loss=65/197/47
- `entity_type` vs `B5_rule_plus_blind_llm`: b=10, c=110, n=309, statistic=10.0, p=1.917329051435738e-22, win/tie/loss=10/189/110
- `entity_type` vs `B8_entropy_threshold`: b=104, c=50, n=309, statistic=50.0, p=1.6140444476738558e-05, win/tie/loss=104/155/50
- `identity_pair` vs `B1_rule_only`: b=292, c=0, n=456, statistic=0.0, p=2.513455854232436e-88, win/tie/loss=292/164/0
- `identity_pair` vs `B3_blind_llm`: b=33, c=136, n=456, statistic=33.0, p=4.713603440235691e-16, win/tie/loss=33/287/136
- `identity_pair` vs `B4_rule_plus_classifier`: b=292, c=0, n=456, statistic=0.0, p=2.513455854232436e-88, win/tie/loss=292/164/0
- `identity_pair` vs `B5_rule_plus_blind_llm`: b=292, c=0, n=456, statistic=0.0, p=2.513455854232436e-88, win/tie/loss=292/164/0
- `identity_pair` vs `B8_entropy_threshold`: b=292, c=0, n=456, statistic=0.0, p=2.513455854232436e-88, win/tie/loss=292/164/0
- `provenance_support` vs `B1_rule_only`: b=153, c=0, n=491, statistic=0.0, p=1.7516230804060213e-46, win/tie/loss=153/338/0
- `provenance_support` vs `B3_blind_llm`: b=33, c=272, n=491, statistic=33.0, p=6.393146709501642e-48, win/tie/loss=33/186/272
- `provenance_support` vs `B4_rule_plus_classifier`: b=153, c=0, n=491, statistic=0.0, p=1.7516230804060213e-46, win/tie/loss=153/338/0
- `provenance_support` vs `B5_rule_plus_blind_llm`: b=153, c=0, n=491, statistic=0.0, p=1.7516230804060213e-46, win/tie/loss=153/338/0
- `provenance_support` vs `B8_entropy_threshold`: b=153, c=0, n=491, statistic=0.0, p=1.7516230804060213e-46, win/tie/loss=153/338/0
- `relation_contract` vs `B1_rule_only`: b=85, c=40, n=248, statistic=40.0, p=7.028919966641749e-05, win/tie/loss=85/123/40
- `relation_contract` vs `B3_blind_llm`: b=79, c=64, n=248, statistic=64.0, p=0.24160419524510135, win/tie/loss=79/105/64
- `relation_contract` vs `B4_rule_plus_classifier`: b=86, c=0, n=248, statistic=0.0, p=2.5849394142282115e-26, win/tie/loss=86/162/0
- `relation_contract` vs `B5_rule_plus_blind_llm`: b=85, c=40, n=248, statistic=40.0, p=7.028919966641749e-05, win/tie/loss=85/123/40
- `relation_contract` vs `B8_entropy_threshold`: b=86, c=0, n=248, statistic=0.0, p=2.5849394142282115e-26, win/tie/loss=86/162/0
- `scope_adjustment` vs `B1_rule_only`: b=59, c=0, n=136, statistic=0.0, p=3.469446951953614e-18, win/tie/loss=59/77/0
- `scope_adjustment` vs `B3_blind_llm`: b=13, c=49, n=136, statistic=13.0, p=4.8175233992660445e-06, win/tie/loss=13/74/49
- `scope_adjustment` vs `B4_rule_plus_classifier`: b=59, c=0, n=136, statistic=0.0, p=3.469446951953614e-18, win/tie/loss=59/77/0
- `scope_adjustment` vs `B5_rule_plus_blind_llm`: b=59, c=0, n=136, statistic=0.0, p=3.469446951953614e-18, win/tie/loss=59/77/0
- `scope_adjustment` vs `B8_entropy_threshold`: b=59, c=0, n=136, statistic=0.0, p=3.469446951953614e-18, win/tie/loss=59/77/0

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

- `entity_type` / `B10_selective_no_structural_gate`: macro-F1 on accepted = 0.6566666666666666, macro-F1 on full denominator = 0.24140451052215758
- `provenance_support` / `B10_selective_no_structural_gate`: macro-F1 on accepted = 0.18995092416016993, macro-F1 on full denominator = 0.18995092416016993
- `relation_contract` / `B10_selective_no_structural_gate`: macro-F1 on accepted = 0.17529940158158933, macro-F1 on full denominator = 0.17529940158158933
- `entity_type` / `B11_structural_gate_no_abstention`: macro-F1 on accepted = 0.6566666666666666, macro-F1 on full denominator = 0.24140451052215758
- `identity_pair` / `B11_structural_gate_no_abstention`: macro-F1 on accepted = 0.39013950332119696, macro-F1 on full denominator = 0.39013950332119696
- `provenance_support` / `B11_structural_gate_no_abstention`: macro-F1 on accepted = 0.18995092416016993, macro-F1 on full denominator = 0.18995092416016993
- `relation_contract` / `B11_structural_gate_no_abstention`: macro-F1 on accepted = 0.1644127714494136, macro-F1 on full denominator = 0.14372045421316826
- `scope_adjustment` / `B11_structural_gate_no_abstention`: macro-F1 on accepted = 0.2017094017094017, macro-F1 on full denominator = 0.2017094017094017
- `entity_type` / `B12_full_framework`: macro-F1 on accepted = 0.6566666666666666, macro-F1 on full denominator = 0.24140451052215758
- `provenance_support` / `B12_full_framework`: macro-F1 on accepted = 0.18995092416016993, macro-F1 on full denominator = 0.18995092416016993
- `relation_contract` / `B12_full_framework`: macro-F1 on accepted = 0.1644127714494136, macro-F1 on full denominator = 0.14372045421316826
- `entity_type` / `B1_rule_only`: macro-F1 on accepted = 0.30256410256410254, macro-F1 on full denominator = 0.18746413545175156
- `relation_contract` / `B1_rule_only`: macro-F1 on accepted = 0.006944444444444445, macro-F1 on full denominator = 0.006944444444444445
- `entity_type` / `B2_frozen_classifier`: macro-F1 on accepted = 0.22858573717948716, macro-F1 on full denominator = 0.10670617634468899
- `entity_type` / `B3_blind_llm`: macro-F1 on accepted = 0.8698061129409156, macro-F1 on full denominator = 0.7781096680280046
- `identity_pair` / `B3_blind_llm`: macro-F1 on accepted = 0.5747871835099249, macro-F1 on full denominator = 0.5747871835099249
- `provenance_support` / `B3_blind_llm`: macro-F1 on accepted = 0.7829393523244454, macro-F1 on full denominator = 0.7829393523244454
- `relation_contract` / `B3_blind_llm`: macro-F1 on accepted = 0.2307235751309607, macro-F1 on full denominator = 0.2307235751309607
- `scope_adjustment` / `B3_blind_llm`: macro-F1 on accepted = 0.5941842669115397, macro-F1 on full denominator = 0.5941842669115397
- `entity_type` / `B4_rule_plus_classifier`: macro-F1 on accepted = 0.3527833696093622, macro-F1 on full denominator = 0.25688605413116095
- `entity_type` / `B5_rule_plus_blind_llm`: macro-F1 on accepted = 0.6951728527781176, macro-F1 on full denominator = 0.6642394939494685
- `relation_contract` / `B5_rule_plus_blind_llm`: macro-F1 on accepted = 0.006944444444444445, macro-F1 on full denominator = 0.006944444444444445
- `entity_type` / `B7_classifier_margin`: macro-F1 on accepted = 0.22858573717948716, macro-F1 on full denominator = 0.10670617634468899
- `entity_type` / `B8_entropy_threshold`: macro-F1 on accepted = 0.22858573717948716, macro-F1 on full denominator = 0.10670617634468899
- `entity_type` / `B9_rule_model_agreement`: macro-F1 on accepted = 0.17013888888888887, macro-F1 on full denominator = 0.06920040743570155
- `relation_contract` / `B9_rule_model_agreement`: macro-F1 on accepted = 0.006944444444444445, macro-F1 on full denominator = 0.006944444444444445

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
