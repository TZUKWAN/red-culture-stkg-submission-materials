# -*- coding: utf-8 -*-
"""临时校验脚本：核对 experiment_chapter_rewritten.md 的数字与 CSV 同源。校验后可删除。"""
import csv
from collections import Counter

BASE = r"D:\REDCULTUREDATA\投稿材料_代码数据整理包\submission_work\final_submission_v3"
import os
os.chdir(BASE)

def rows(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

ok = []
bad = []

def chk(name, cond, detail=""):
    (ok if cond else bad).append(f"{name} {detail}")

rel = rows("experiments/08_independent_reference/JUDGE_RELIABILITY_SUMMARY.csv")
R = {}
for r in rel:
    try:
        R[(r["task_type"], r["metric"])] = float(r["value"])
    except ValueError:
        pass
for t, k in [("entity_type", 0.780), ("scope_adjustment", 0.449), ("identity_pair", 0.431),
             ("provenance_support", 0.421), ("relation_contract", 0.037)]:
    chk(f"kappa {t}", abs(R[(t, "fleiss_kappa")] - k) < 5e-4, f"csv={R[(t,'fleiss_kappa')]:.4f}")
for t, v in [("entity_type", 276), ("scope_adjustment", 111), ("identity_pair", 399),
             ("provenance_support", 394), ("relation_contract", 66)]:
    chk(f"strong {t}", R[(t, "n_strong_consensus")] == v)
A14 = rows("experiments/14_statistical_tests/JUDGE_AGREEMENT_SUMMARY.csv")
RA = {}
for r in A14:
    if r["kind"] == "reliability" and r["task_type"] == "ALL":
        try:
            RA[r["metric"]] = float(r["value"])
        except ValueError:
            pass
chk("strong total", RA.get("n_strong_consensus") == 1246)
chk("weak total", RA.get("n_weak_consensus") == 1347)
chk("unresolved total", RA.get("n_unresolved") == 237)
chk("n_tasks total", RA.get("n_tasks") == 2830)
chk("ALL kappa 0.424", abs(RA.get("fleiss_kappa", 0) - 0.4236) < 5e-4)
chk("ALL pairwise 0.631", abs(RA.get("mean_pairwise_agreement", 0) - 0.6310) < 5e-4)

G = {(r["method_id"], r["task_type"]): r for r in rows(
    "experiments/13_selective_inference_independent/imcr_strong/imcr_strong_SELECTIVE_GOAL13_METRICS.csv")}

def g(m, t, k):
    # B12 与 B11 在无数值置信任务（scope/identity）共用同一操作点；CSV 仅在 B11 下落盘
    key = (m, t)
    if key not in G and m == "B12_full_framework" and t in ("scope_adjustment", "identity_pair"):
        key = ("B11_structural_gate_no_abstention", t)
    return float(G[key][k])

checks = [
    ("B12 entity cov", g("B12_full_framework", "entity_type", "coverage"), 0.1486),
    ("B12 entity acc", g("B12_full_framework", "entity_type", "selective_accuracy"), 0.9268),
    ("B3 entity cov", g("B3_blind_llm", "entity_type", "coverage"), 0.9058),
    ("B3 entity acc", g("B3_blind_llm", "entity_type", "selective_accuracy"), 0.9880),
    ("B3 relation acc", g("B3_blind_llm", "relation_contract", "selective_accuracy"), 0.9394),
    ("B3 scope acc", g("B3_blind_llm", "scope_adjustment", "selective_accuracy"), 0.8108),
    ("B3 identity acc", g("B3_blind_llm", "identity_pair", "selective_accuracy"), 0.9524),
    ("B3 provenance acc", g("B3_blind_llm", "provenance_support", "selective_accuracy"), 0.9365),
    ("B12 relation acc", g("B12_full_framework", "relation_contract", "selective_accuracy"), 0.0238),
    ("B12 scope acc", g("B12_full_framework", "scope_adjustment", "selective_accuracy"), 0.4595),
    ("B12 provenance acc", g("B12_full_framework", "provenance_support", "selective_accuracy"), 0.3046),
    ("B11 relation cov", g("B11_structural_gate_no_abstention", "relation_contract", "coverage"), 0.6364),
    ("B10 relation cov", g("B10_selective_no_structural_gate", "relation_contract", "coverage"), 1.0),
    ("B10 relation acc", g("B10_selective_no_structural_gate", "relation_contract", "selective_accuracy"), 0.1061),
    ("B12 entity aurc", g("B12_full_framework", "entity_type", "aurc"), 0.006701),
    ("B11 entity aurc", g("B11_structural_gate_no_abstention", "entity_type", "aurc"), 0.005435),
    ("B12 prov aurc", g("B12_full_framework", "provenance_support", "aurc"), 0.393648),
    ("B11 prov aurc", g("B11_structural_gate_no_abstention", "provenance_support", "aurc"), 0.347716),
    ("B10 rel aurc", g("B10_selective_no_structural_gate", "relation_contract", "aurc"), 0.508575),
    ("B11 rel aurc", g("B11_structural_gate_no_abstention", "relation_contract", "aurc"), 0.310606),
    ("B12 rel aurc", g("B12_full_framework", "relation_contract", "aurc"), 0.360865),
    ("B1 entity cov", g("B1_rule_only", "entity_type", "coverage"), 0.25),
    ("B1 entity acc", g("B1_rule_only", "entity_type", "selective_accuracy"), 0.5362),
    ("B1 rel acc", g("B1_rule_only", "relation_contract", "selective_accuracy"), 0.0),
]
for name, got, want in checks:
    chk(name, abs(got - want) < 5e-4, f"csv={got:.4f} cited={want}")

W = {(r["method_id"], r["task_type"], r["metric"]): r for r in rows(
    "experiments/14_statistical_tests/WILSON_CI_TABLE.csv")}

def w(m, t, k, lo, hi):
    r = W[(m, t, k)]
    chk(f"CI {m}/{t}/{k}", abs(float(r["ci95_low"]) - lo) < 5e-4 and abs(float(r["ci95_high"]) - hi) < 5e-4,
        f"csv=[{float(r['ci95_low']):.4f},{float(r['ci95_high']):.4f}]")

w("B12_full_framework", "entity_type", "selective_accuracy", 0.8057, 0.9748)
w("B3_blind_llm", "entity_type", "selective_accuracy", 0.9653, 0.9959)
w("B12_full_framework", "scope_adjustment", "selective_accuracy", 0.3697, 0.5520)
w("B12_full_framework", "identity_pair", "selective_accuracy", 0.5985, 0.6919)
w("B12_full_framework", "provenance_support", "selective_accuracy", 0.2612, 0.3517)
w("B2_frozen_classifier", "entity_type", "selective_accuracy", 0.2808, 0.4862)
w("B9_rule_model_agreement", "entity_type", "selective_accuracy", 0.2759, 0.5306)
w("B4_rule_plus_classifier", "entity_type", "selective_accuracy", 0.3989, 0.5651)
w("B5_rule_plus_blind_llm", "entity_type", "selective_accuracy", 0.8093, 0.8963)

M = {(r["task_type"], r["baseline_method_id"]): r for r in rows(
    "experiments/14_statistical_tests/MCNEMAR_TESTS.csv")}

def mc(t, m, win, loss, p):
    r = M[(t, m)]
    chk(f"McNemar {t}/{m}", r["full_wins"] == str(win) and r["full_losses"] == str(loss)
        and abs(float(r["p_value"]) - p) / p < 0.05,
        f"csv={r['full_wins']}:{r['full_losses']} p={float(r['p_value']):.3g}")

mc("entity_type", "B1_rule_only", 90, 0, 1.616e-27)
mc("entity_type", "B3_blind_llm", 2, 141, 1.847e-39)
mc("entity_type", "B4_rule_plus_classifier", 61, 45, 0.1448)
mc("entity_type", "B8_entropy_threshold", 93, 48, 1.882e-4)
mc("identity_pair", "B1_rule_only", 258, 0, 4.318e-78)
mc("identity_pair", "B3_blind_llm", 10, 132, 2.575e-28)
mc("provenance_support", "B3_blind_llm", 8, 257, 1.887e-65)
mc("scope_adjustment", "B3_blind_llm", 7, 46, 4.003e-8)
mc("relation_contract", "B3_blind_llm", 1, 56, 8.049e-16)

P = rows("experiments/14_statistical_tests/PAIRED_BOOTSTRAP_DELTAS.csv")
pb = [r for r in P if r["status"] == "applicable"]
chk("bootstrap applicable pairs == 2 (provenance/B3)", len(pb) == 2 and all(
    r["task_type"] == "provenance_support" and r["baseline_method_id"] == "B3_blind_llm" for r in pb))
for r in pb:
    if r["metric"] == "aurc":
        chk("dAURC", abs(float(r["estimate"]) - 0.3752) < 5e-4 and abs(float(r["ci95_low"]) - 0.3426) < 5e-4
            and abs(float(r["ci95_high"]) - 0.4073) < 5e-4,
            f"{float(r['estimate']):.4f} [{float(r['ci95_low']):.4f},{float(r['ci95_high']):.4f}]")
    else:
        chk("dAUGRC", abs(float(r["estimate"]) - 0.3320) < 5e-4 and abs(float(r["ci95_low"]) - 0.3070) < 5e-4
            and abs(float(r["ci95_high"]) - 0.3583) < 5e-4)

L = {r["task_type"]: r for r in rows(
    "experiments/13_selective_inference_independent/leave_b_out/leave_b_out_SELECTIVE_GOAL13_METRICS.csv")
    if r["method_id"] == "B3_blind_llm"}
for t, v in [("entity_type", 0.9234), ("relation_contract", 0.2863), ("scope_adjustment", 0.6985),
             ("identity_pair", 0.8662), ("provenance_support", 0.7984)]:
    chk(f"leave-B-out B3 {t}", abs(float(L[t]["selective_accuracy"]) - v) < 5e-4,
        f"csv={float(L[t]['selective_accuracy']):.4f}")

S = rows("experiments/08_independent_reference/IMCR_REFERENCE_STRONG.csv")
lab = "imcr_label_decoded"
sc = Counter(r[lab] for r in S if r["task_type"] == "scope_adjustment")
chk("scope strong AFTER=51 BEFORE=58 INSUFF=2",
    sc["AFTER_BETTER"] == 51 and sc["BEFORE_BETTER"] == 58 and sc["INSUFFICIENT_EVIDENCE"] == 2, str(dict(sc)))
chk("scope 51/111=45.9% 58/111=52.3%", abs(51 / 111 - 0.4595) < 5e-4 and abs(58 / 111 - 0.5225) < 5e-4)
chk("scope diff ~6.3pp", abs((58 - 51) / 111 * 100 - 6.31) < 0.1)

idc = Counter(r[lab] for r in S if r["task_type"] == "identity_pair")
chk("identity strong same=356 diff=41 insuff=2",
    idc["same_entity"] == 356 and idc["different_entity"] == 41 and idc["insufficient_evidence"] == 2, str(dict(idc)))
chk("217+41=258; 258/399=0.6466", abs((217 + 41) / 399 - 0.6466) < 5e-4)

runs = rows("experiments/09_independent_baselines/IMCR_BASELINE_RUNS.csv")
refS = {(r["task_type"], r["sample_id"]): r for r in S}
imeta = {r["pair_id"]: r for r in rows("experiments/11_identity_validation/IDENTITY_PAIR_METADATA.csv")}
hn_decisive = Counter()
cat_same = Counter()
for r in runs:
    if r["method_id"] == "B12_full_framework" and r["task_type"] == "identity_pair":
        key = ("identity_pair", r["sample_id"])
        if key in refS:
            rl = refS[key][lab]
            if imeta[r["sample_id"]]["pair_kind"] == "hard_negative" and rl in ("same_entity", "different_entity"):
                hn_decisive[rl] += 1
                if rl == "same_entity":
                    cat_same[imeta[r["sample_id"]]["category"]] += 1
chk("hard neg decisive=180 same=139(77.2%)", sum(hn_decisive.values()) == 180 and hn_decisive["same_entity"] == 139,
    str(dict(hn_decisive)))
chk("org_vs_place 40/40 same", cat_same["org_vs_place_same_name"] == 40)

A = rows("experiments/08_independent_reference/IMCR_REFERENCE_ALL.csv")
smap = {r["sample_id"]: r["sample_role"] for r in rows("experiments/08_independent_reference/RELATION_CONTRACT_SAMPLE.csv")}
cc = Counter()
for r in A:
    if r["task_type"] == "relation_contract":
        cc[(smap[r["sample_id"]], r[lab])] += 1
chk("changed 265 = 113inv+80ctx+72ins+0val",
    cc[("changed", "invalid")] == 113 and cc[("changed", "context_only")] == 80
    and cc[("changed", "insufficient_evidence")] == 72 and cc[("changed", "valid")] == 0)
chk("control 287 = 76inv+95ctx+114ins+2val",
    cc[("control", "invalid")] == 76 and cc[("control", "context_only")] == 95
    and cc[("control", "insufficient_evidence")] == 114 and cc[("control", "valid")] == 2)
chk("113/265=42.6% 76/287=26.5%", abs(113 / 265 - 0.4264) < 5e-4 and abs(76 / 287 - 0.2648) < 5e-4)

pmd = {r["sample_id"]: r["research_tier"] for r in rows(
    "experiments/12_provenance_validation/PROVENANCE_SUPPORT_METADATA.csv")}
pc = Counter()
for r in S:
    if r["task_type"] == "provenance_support":
        pc[(pmd[r["sample_id"]], r[lab])] += 1

def tcount(t, l):
    return pc[(t, l)]

chk("strict n=178 fully78 part37 uns58 con2 ins3",
    sum(v for k, v in pc.items() if k[0] == "strict_semantic") == 178
    and tcount("strict_semantic", "fully_supported") == 78
    and tcount("strict_semantic", "partially_supported") == 37
    and tcount("strict_semantic", "unsupported") == 58
    and tcount("strict_semantic", "contradicted") == 2
    and tcount("strict_semantic", "insufficient_evidence") == 3)
chk("strict 115/178=64.6%", abs(115 / 178 - 0.6461) < 5e-4)
chk("ctx 67/117=57.3%", abs(67 / 117 - 0.5726) < 5e-4)
chk("unres 48/99=48.5%", abs(48 / 99 - 0.4848) < 5e-4)
chk("strict unsupported+contra 60/178=33.7%", abs(60 / 178 - 0.3371) < 5e-4)
chk("overall fully=134 (58+96+134?) fully+part=230/394=58.4%",
    tcount("strict_semantic", "fully_supported") + tcount("contextual", "fully_supported")
    + tcount("unresolved", "fully_supported") == 134 and abs(230 / 394 - 0.5838) < 5e-4)

print(f"PASS {len(ok)} checks")
for b in bad:
    print("FAIL:", b)
print("ALL OK" if not bad else f"{len(bad)} FAILURES")
