# -*- coding: utf-8 -*-
"""test_selective_scope_closure_v2.py — 三票共识重建 Selective Scope Closure（指令 §4）自动测试。

覆盖（指令要求的规则确定性 / 切分不重叠 / 动作映射正确，另加三票参考完整性与无回流）：
* test_action_outcome_mapping          动作×三票裁判 → outcome/correct 映射正确（含弃权与不可评）；
* test_rule_learning_thresholds        规则学习阈值判据（p<0.05 双侧、decided>=10、方向、未见类型）；
* test_books_column_parsing            books 列容错解析（严格 JSON / 单引号字面量 / 空值）；
* test_rule_mapping_deterministic      同输入同输出（纯函数级确定性）；
* test_split_disjoint_and_atomic       learn/held-out 不重叠、并集=全量 208、并查集分量原子、确定性；
* test_rules_learned_from_learn_only   规则统计可由 learn ∩ 参考复算（证明零回流）；
* test_three_vote_reference_integrity  参考=187（110 strong+77 weak）、21 条 unresolved 不入参考不评分；
* test_heldout_csv_consistency         HELDOUT CSV 逐行与动作×裁判映射一致、仅 held-out、无重复；
* test_structural_safety_zero_violations  结构安全核验（role/owner 四字段之外零改写面）；
* test_pipeline_outputs_deterministic  完整管线两次运行输出字节一致；
* test_v1_comparison_block             汇总含 v1 两票（96.6%）对比块。

真实数据文件缺失时（环境不完整）相应测试自动跳过。
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TEST_DIR.parent / "experiment_pipelines"))

import run_selective_scope_closure_v2 as rsc  # noqa: E402

HAS_REAL_DATA = all(p.exists() for p in
                    (rsc.IN_REFERENCE, rsc.IN_CONSENSUS, rsc.IN_ERRORS, rsc.IN_META,
                     rsc.IN_PAYLOADS, rsc.IN_V1_SUMMARY))


# ------------------------------------------------------------ 纯函数测试
def test_action_outcome_mapping():
    # REWRITE：裁判 AFTER_BETTER → 正确（old 错过 / new 正确）
    assert rsc.judge_outcome("REWRITE", "AFTER_BETTER") == ("REWRITE_CORRECT", 1)
    # REWRITE：裁判 BEFORE_BETTER → 错误改写
    assert rsc.judge_outcome("REWRITE", "BEFORE_BETTER") == ("REWRITE_WRONG", 0)
    # RETAIN：裁判 BEFORE_BETTER → 正确保留（old 错误改写 / new 正确）
    assert rsc.judge_outcome("RETAIN", "BEFORE_BETTER") == ("RETAIN_CORRECT", 1)
    # RETAIN：裁判 AFTER_BETTER → 错误保留
    assert rsc.judge_outcome("RETAIN", "AFTER_BETTER") == ("RETAIN_WRONG", 0)
    # UNRESOLVED：裁判已分胜负 → 弃权（不计正确/错误）
    for j in ("AFTER_BETTER", "BEFORE_BETTER"):
        out, ok = rsc.judge_outcome("UNRESOLVED", j)
        assert out == "ABSTAIN_UNRESOLVED" and ok is None
    # 裁判未分胜负（三票口径：BOTH_WRONG/INSUFFICIENT_EVIDENCE/EQUIVALENT）→ 不可评
    for j in ("BOTH_WRONG", "INSUFFICIENT_EVIDENCE", "EQUIVALENT"):
        for act in ("REWRITE", "RETAIN", "UNRESOLVED"):
            out, ok = rsc.judge_outcome(act, j)
            assert out == "UNEVALUABLE" and ok is None
    # 不入参考（21 条 unresolved 任务）→ 不可评
    for act in ("REWRITE", "RETAIN", "UNRESOLVED"):
        out, ok = rsc.judge_outcome(act, rsc.NOT_IN_REFERENCE)
        assert out == "UNEVALUABLE" and ok is None
    # 非法裁判值必须报错（静默当不可评会污染分母）
    try:
        rsc.judge_outcome("REWRITE", "DISAGREE")  # 两票口径的值在三票口径非法
        raise AssertionError("DISAGREE 应为非法裁判值")
    except ValueError:
        pass


def test_rule_learning_thresholds():
    def row(tt, label, in_ref=True):
        return {"transformation_type": tt, "reference_label": label, "in_reference": in_ref}

    # AFTER 显著占优且 decided>=10 → REWRITE
    rows = [row("t_good", "AFTER_BETTER")] * 10 + [row("t_good", "BEFORE_BETTER")]
    rules = rsc.learn_rules(rows)
    r = rules["t_good"]
    assert r["action"] == "REWRITE"
    assert r["decided"] == 11 and r["after_better"] == 10 and r["before_better"] == 1
    # BEFORE 显著占优且 decided>=10 → RETAIN
    rows = [row("t_bad", "BEFORE_BETTER")] * 10 + [row("t_bad", "AFTER_BETTER")]
    assert rsc.learn_rules(rows)["t_bad"]["action"] == "RETAIN"
    # decided < 10 → 即使 9:0 也保守 UNRESOLVED
    rules = rsc.learn_rules([row("t_small", "AFTER_BETTER")] * 9)
    assert rules["t_small"]["action"] == "UNRESOLVED"
    assert rules["t_small"]["binom_p_two_sided"] < rsc.P_THRESHOLD  # 显著但样本不足
    # decided>=10 但不显著 → UNRESOLVED
    rows = [row("t_flat", "AFTER_BETTER")] * 6 + [row("t_flat", "BEFORE_BETTER")] * 5
    assert rsc.learn_rules(rows)["t_flat"]["action"] == "UNRESOLVED"
    # 未分胜负 / 不入参考的任务不得计入 decided
    rows = ([row("t_noise", "AFTER_BETTER")] * 7 + [row("t_noise", "BEFORE_BETTER")] * 4
            + [row("t_noise", "BOTH_WRONG")] * 3 + [row("t_noise", "INSUFFICIENT_EVIDENCE")] * 2
            + [row("t_noise", "EQUIVALENT")] * 1
            + [row("t_noise", "AFTER_BETTER", in_ref=False)] * 5)
    r = rsc.learn_rules(rows)["t_noise"]
    assert r["decided"] == 11 and r["after_better"] == 7 and r["before_better"] == 4
    assert r["n_learn"] == 22 and r["n_learn_in_reference"] == 17
    assert r["n_learn_not_in_reference"] == 5
    # learn 内未见类型：apply 时默认 UNRESOLVED
    assert rsc.action_for(rules, "never_seen_type") == "UNRESOLVED"


def test_books_column_parsing():
    assert rsc.parse_books_column("") == []
    assert rsc.parse_books_column("[]") == []
    # 数据实际形态：Python 字面量单引号风格（非严格 JSON）
    raw = "['中共党史人物传  第19卷', '中共党史人物传第39卷']"
    assert rsc.parse_books_column(raw) == ["中共党史人物传  第19卷", "中共党史人物传第39卷"]
    # 严格 JSON 也能解析
    assert rsc.parse_books_column('["A", "B"]') == ["A", "B"]
    # 去重 + 去空白
    assert rsc.parse_books_column("['X', 'X', ' ']") == ["X"]
    # 非法值必须显式失败
    try:
        rsc.parse_books_column("[broken")
        raise AssertionError("非法 books 值应失败")
    except SystemExit:
        pass


def test_rule_mapping_deterministic():
    rows = [
        {"transformation_type": "a→b", "reference_label": g, "in_reference": True}
        for g in ["AFTER_BETTER"] * 12 + ["BEFORE_BETTER"] * 2 + ["INSUFFICIENT_EVIDENCE"] * 5
    ] + [
        {"transformation_type": "c→d", "reference_label": g, "in_reference": True}
        for g in ["BEFORE_BETTER"] * 12 + ["AFTER_BETTER"] * 1 + ["BOTH_WRONG"] * 2
    ]
    r1, r2 = rsc.learn_rules(rows), rsc.learn_rules(rows)
    assert r1 == r2
    assert r1["a→b"]["action"] == "REWRITE" and r1["c→d"]["action"] == "RETAIN"


# ------------------------------------------------------------ 真实数据测试
def test_split_disjoint_and_atomic():
    if not HAS_REAL_DATA:
        print("skip: real data missing")
        return
    rows, meta, payloads, ref_by_id, _ = rsc.load_inputs()
    tasks = rsc.attach_reference(rows, ref_by_id)
    books_map, provenance = rsc.derive_task_books(tasks, meta)
    assert len(books_map) == 208
    assert sum(provenance.values()) == 208
    # book 键只来自 metadata books 列（指令口径）
    assert set(provenance) <= {"metadata_books_column", "nobook_single_task_component"}

    s1, d1 = rsc.split_learn_heldout(books_map)
    s2, d2 = rsc.split_learn_heldout(books_map)
    assert s1 == s2 and d1 == d2  # 确定性：同输入同输出

    learn = {t for t, s in s1.items() if s == "learn"}
    held = {t for t, s in s1.items() if s == "heldout"}
    assert not (learn & held), "learn 与 held-out 必须不重叠"
    assert learn | held == set(books_map), "learn ∪ held-out = 全量 208"
    assert d1["learn_tasks"] == len(learn) and d1["heldout_tasks"] == len(held)

    # 分量原子：同一并查集分量的任务绝不跨侧（含 unresolved 任务）
    comps = rsc.build_components(books_map)
    assert sum(len(m) for m in comps.values()) == 208
    for members in comps.values():
        sides = {s1[m] for m in members}
        assert len(sides) == 1, f"分量跨侧: {members} -> {sides}"

    # 60% 预算（分量原子下允许 <= 预算的取整偏差）
    budget = round(rsc.LEARN_RATIO * 208)
    assert d1["budget_tasks"] == budget
    assert len(learn) <= budget
    assert abs(len(learn) / 208 - 0.60) < 0.05, f"learn 占比偏离 60% 过多: {len(learn)/208:.3f}"
    # 种子与 frozen_splits 一致
    assert d1["seed"] == 20260908


def test_rules_learned_from_learn_only():
    """规则统计必须能由 learn ∩ 三票参考任务逐一复算（证明未用 held-out 调规则）。"""
    if not HAS_REAL_DATA:
        print("skip: real data missing")
        return
    with tempfile.TemporaryDirectory() as td:
        p = rsc.run_pipeline(out_dir=Path(td), report_path=None, now="2026-09-10T00:00:00+00:00")
    learn_ids = set(p["split"]["learn_task_ids"])
    held_ids = set(p["split"]["heldout_task_ids"])
    assert not (learn_ids & held_ids)
    assert len(learn_ids) + len(held_ids) == 208

    rows, _, _, ref_by_id, _ = rsc.load_inputs()
    by_type: dict[str, Counter] = {}
    for r in rows:
        if r["task_id"] in learn_ids and r["task_id"] in ref_by_id:  # 只允许 learn ∩ 参考 参与
            by_type.setdefault(r["transformation_type"], Counter())[ref_by_id[r["task_id"]]["reference_label"]] += 1
    for tt, ru in p["rules"].items():
        cnt = by_type.get(tt, Counter())
        assert ru["after_better"] == cnt["AFTER_BETTER"]
        assert ru["before_better"] == cnt["BEFORE_BETTER"]
        decided = cnt["AFTER_BETTER"] + cnt["BEFORE_BETTER"]
        assert ru["decided"] == decided
        assert ru["n_learn_in_reference"] == sum(cnt.values())
        expect_p = rsc.binom_two_sided(min(cnt["AFTER_BETTER"], cnt["BEFORE_BETTER"]), decided) if decided else 1.0
        assert abs(ru["binom_p_two_sided"] - expect_p) < 1e-12
        expect_action = (
            ("REWRITE" if cnt["AFTER_BETTER"] > cnt["BEFORE_BETTER"] else "RETAIN")
            if decided >= rsc.MIN_DECIDED and expect_p < rsc.P_THRESHOLD
            else "UNRESOLVED"
        )
        assert ru["action"] == expect_action, f"{tt}: {ru['action']} != {expect_action}"
    # held-out 上不得出现 learn 规则之外的 action 取值
    for tt, pt in p["heldout_evaluation"]["per_type"].items():
        assert pt["action_new"] == p["rules"].get(tt, {"action": "UNRESOLVED"})["action"]


def test_three_vote_reference_integrity():
    if not HAS_REAL_DATA:
        print("skip: real data missing")
        return
    with tempfile.TemporaryDirectory() as td:
        p = rsc.run_pipeline(out_dir=Path(td), report_path=None, now="2026-09-10T00:00:00+00:00")
    ref = p["three_vote_reference"]
    # 参考 = 187（110 strong + 77 weak），21 条 unresolved 不入参考
    assert p["meta"]["n_tasks_total"] == 208
    assert p["meta"]["n_reference"] == 187
    assert p["meta"]["n_unresolved_not_in_reference"] == 21
    assert ref["tiers_in_reference"] == {"strong_consensus": 110, "weak_consensus": 77}
    assert len(ref["unresolved_task_ids"]) == 21
    # 标签分布与参考文件逐标签一致
    rows, _, _, ref_by_id, _ = rsc.load_inputs()
    total = Counter(ref_by_id[r["task_id"]]["reference_label"] for r in rows if r["task_id"] in ref_by_id)
    total[rsc.NOT_IN_REFERENCE] = 208 - 187
    assert ref["label_distribution_total"] == dict(sorted(total.items()))
    # 21 条 unresolved：不参与规则学习（不占 decided），held-out 上不进入任何 correct 分母
    unresolved = set(ref["unresolved_task_ids"])
    assert p["split"]["learn_tasks"] + p["split"]["heldout_tasks"] == 208
    he = p["heldout_evaluation"]
    # agreement 分母 = decided（AFTER/BEFORE），未分胜负与不入参考都被排除
    assert he["n_evaluable_decided"] <= he["n_heldout_in_reference"] <= he["n_heldout"]
    assert he["n_heldout_not_in_reference"] == len(unresolved & set(p["split"]["heldout_task_ids"]))
    assert he["n_evaluable_decided"] == he["old"]["n"]
    assert he["new"]["n_actionable"] + he["new"]["n_abstained_unresolved"] == he["n_evaluable_decided"]
    # 弃权率 + 覆盖率互补（decided 口径）
    assert abs(he["abstention_rate"]["on_decided"] + he["actionable_coverage"]["on_decided"] - 1.0) < 1e-12


def test_heldout_csv_consistency():
    if not HAS_REAL_DATA:
        print("skip: real data missing")
        return
    with tempfile.TemporaryDirectory() as td:
        rsc.run_pipeline(out_dir=Path(td), report_path=None, now="2026-09-10T00:00:00+00:00")
        csv_path = Path(td) / "CLOSURE3_OLD_NEW_HELDOUT.csv"
        rows = list(csv.DictReader(csv_path.read_text(encoding="utf-8-sig").splitlines()))
        rules = json.loads((Path(td) / "CLOSURE3_RULES.json").read_text(encoding="utf-8"))["rules"]
        s = json.loads((Path(td) / "CLOSURE3_SUMMARY.json").read_text(encoding="utf-8"))
    held_ids = set(s["split"]["heldout_task_ids"])
    assert len(rows) == s["split"]["heldout_tasks"], "CSV 行数 = held-out 任务数"
    assert all(r["split"] == "heldout" for r in rows)
    assert {r["task_id"] for r in rows} == held_ids, "CSV 必须恰好覆盖 held-out 且无 learn 任务"
    assert len({r["task_id"] for r in rows}) == len(rows), "task_id 不得重复"
    for r in rows:
        judge = r["reference_label"]
        # action_new 必须来自规则（未覆盖类型 → UNRESOLVED）
        expect_action = rules.get(r["type"], {"action": "UNRESOLVED"})["action"]
        assert r["action_new"] == expect_action
        # old closure = 全部 REWRITE（生产现状）
        assert r["old_outcome"] == rsc.judge_outcome("REWRITE", judge)[0]
        # new outcome 与 correct 列必须与纯映射一致
        exp_out, exp_ok = rsc.judge_outcome(expect_action, judge)
        assert r["new_outcome"] == exp_out
        assert r["correct_old"] == ("" if rsc.judge_outcome("REWRITE", judge)[1] is None
                                    else str(rsc.judge_outcome("REWRITE", judge)[1]))
        assert r["correct_new"] == ("" if exp_ok is None else str(exp_ok))
        # 不可评任务（未分胜负 / 不入参考）不得计入任何 correct
        if judge not in rsc.DECIDED_SET:
            assert r["correct_old"] == "" and r["correct_new"] == ""


def test_structural_safety_zero_violations():
    if not HAS_REAL_DATA:
        print("skip: real data missing")
        return
    _, _, payloads, _, _ = rsc.load_inputs()
    safety = rsc.structural_safety_check(payloads)
    assert safety["payload_slots_checked"] == 208 * 2
    assert safety["slots_with_non_role_owner_fields"] == 0
    assert safety["structural_violations"] == 0


def test_pipeline_outputs_deterministic():
    """完整管线两次运行（固定时间戳）→ 输出文件字节一致（同输入同输出）。"""
    if not HAS_REAL_DATA:
        print("skip: real data missing")
        return
    names = ("CLOSURE3_RULES.json", "CLOSURE3_OLD_NEW_HELDOUT.csv", "CLOSURE3_SUMMARY.json")
    with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
        for td in (td1, td2):
            rsc.run_pipeline(out_dir=Path(td), report_path=Path(td) / "report.md",
                             now="2026-09-10T00:00:00+00:00")
        for name in names:
            b1 = (Path(td1) / name).read_bytes()
            b2 = (Path(td2) / name).read_bytes()
            assert b1 == b2, f"{name} 两次运行不一致"
        # 报告本身也必须确定（去掉真实 v1 对比后仍在两目录一致）
        assert (Path(td1) / "report.md").read_bytes() == (Path(td2) / "report.md").read_bytes()
        # 汇总一致性：learn/heldout 计数、结构安全、McNemar 字段齐全
        s = json.loads((Path(td1) / "CLOSURE3_SUMMARY.json").read_text(encoding="utf-8"))
        assert s["split"]["learn_tasks"] + s["split"]["heldout_tasks"] == 208
        assert s["structural_safety"]["structural_violations"] == 0
        pair = s["heldout_evaluation"]["paired_actionable"]
        assert 0.0 <= pair["mcnemar_exact_p"] <= 1.0
        assert pair["n"] == s["heldout_evaluation"]["new"]["n_actionable"]


def test_v1_comparison_block():
    """汇总与报告必须包含 v1 两票（96.6%）对比块，且 v1 侧数值只读自旧文件。"""
    if not HAS_REAL_DATA:
        print("skip: real data missing")
        return
    with tempfile.TemporaryDirectory() as td:
        rsc.run_pipeline(out_dir=Path(td), report_path=Path(td) / "report.md",
                         now="2026-09-10T00:00:00+00:00")
        s = json.loads((Path(td) / "CLOSURE3_SUMMARY.json").read_text(encoding="utf-8"))
        report = (Path(td) / "report.md").read_text(encoding="utf-8")
    cmp = s["v1_vs_v2_comparison"]
    v1 = json.loads(rsc.IN_V1_SUMMARY.read_text(encoding="utf-8"))["heldout_evaluation"]
    assert abs(cmp["v1"]["new_agreement_actionable"] - v1["new"]["agreement_actionable"]) < 1e-12
    assert abs(cmp["v1"]["new_agreement_actionable"] - 0.9655172413793104) < 1e-12  # 旧 96.6%
    assert set(cmp["v2"]) >= {"old_agreement", "new_agreement_actionable",
                              "agreement_conservative", "mcnemar_exact_p"}
    # v2 侧数值与 heldout_evaluation 一致
    he = s["heldout_evaluation"]
    assert cmp["v2"]["new_agreement_actionable"] == he["new"]["agreement_actionable"]
    assert cmp["v2"]["old_agreement"] == he["old"]["agreement"]
    # 报告含对比表与口径差异章节
    assert "v1（两票 A+B，作废）" in report and "96.6%" in report
    assert "两票 vs 三票口径差异说明" in report
    assert len(s["caliber_diff_two_vs_three_votes"]) >= 5


if __name__ == "__main__":
    test_action_outcome_mapping()
    test_rule_learning_thresholds()
    test_books_column_parsing()
    test_rule_mapping_deterministic()
    test_split_disjoint_and_atomic()
    test_rules_learned_from_learn_only()
    test_three_vote_reference_integrity()
    test_heldout_csv_consistency()
    test_structural_safety_zero_violations()
    test_pipeline_outputs_deterministic()
    test_v1_comparison_block()
    print("all tests passed")
