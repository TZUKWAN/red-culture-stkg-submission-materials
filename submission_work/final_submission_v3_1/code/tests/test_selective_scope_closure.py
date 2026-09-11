# -*- coding: utf-8 -*-
"""test_selective_scope_closure.py — Selective Scope Closure（指令 §12/14）自动测试。

覆盖：
* test_action_outcome_mapping          动作×裁判 → outcome/correct 的映射正确（含弃权与不可评）；
* test_rule_learning_thresholds        规则学习阈值判据（p<0.05、decided>=10、方向）；
* test_rule_mapping_deterministic      同输入同输出（纯函数 + 完整管线两次运行字节一致）；
* test_split_disjoint_and_atomic       held-out 划分与 learn 不重叠、并集=全量、分量原子、确定性；
* test_rules_learned_from_learn_only   规则统计可由 learn 任务复算（证明未用 held-out 调规则）；
* test_heldout_csv_consistency         HELDOUT CSV 逐行 outcome/correct 与动作×裁判映射一致；
* test_structural_safety_zero_violations  结构安全核验（role/owner 四字段之外零改写面）。

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

import run_selective_scope_closure as rsc  # noqa: E402

HAS_REAL_DATA = all(p.exists() for p in (rsc.IN_ERRORS, rsc.IN_META, rsc.IN_PAYLOADS))


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
    # 裁判未定（两票不一致/不足/双错/等价）→ 不可评，任何动作都一样
    for j in ("DISAGREE", "INSUFFICIENT", "BOTH_WRONG", "EQUIVALENT"):
        for act in ("REWRITE", "RETAIN", "UNRESOLVED"):
            out, ok = rsc.judge_outcome(act, j)
            assert out == "UNEVALUABLE" and ok is None


def test_rule_learning_thresholds():
    def row(tt, agg):
        return {"transformation_type": tt, "aggregated": agg}

    # AFTER 显著占优且 decided>=10 → REWRITE
    rows = [row("t_good", "AFTER_BETTER")] * 10 + [row("t_good", "BEFORE_BETTER")]
    rules = rsc.learn_rules(rows)
    r = rules["t_good"]
    assert r["action"] == "REWRITE"
    assert r["decided"] == 11 and r["after_better"] == 10 and r["before_better"] == 1
    # BEFORE 显著占优且 decided>=10 → RETAIN
    rows = [row("t_bad", "BEFORE_BETTER")] * 10 + [row("t_bad", "AFTER_BETTER")]
    rules = rsc.learn_rules(rows)
    assert rules["t_bad"]["action"] == "RETAIN"
    # decided < 10 → 即使 9:0 也保守 UNRESOLVED
    rows = [row("t_small", "AFTER_BETTER")] * 9
    rules = rsc.learn_rules(rows)
    assert rules["t_small"]["action"] == "UNRESOLVED"
    assert rules["t_small"]["binom_p_two_sided"] < rsc.P_THRESHOLD  # 显著但样本不足
    # decided>=10 但不显著 → UNRESOLVED
    rows = [row("t_flat", "AFTER_BETTER")] * 6 + [row("t_flat", "BEFORE_BETTER")] * 5
    rules = rsc.learn_rules(rows)
    assert rules["t_flat"]["action"] == "UNRESOLVED"
    # learn 内未见类型：apply 时默认 UNRESOLVED
    assert rsc.action_for(rules, "never_seen_type") == "UNRESOLVED"


def test_rule_mapping_deterministic():
    # 纯函数：同输入两次学习 → 完全一致
    rows = [
        {"transformation_type": "a→b", "aggregated": g}
        for g in ["AFTER_BETTER"] * 12 + ["BEFORE_BETTER"] * 2 + ["DISAGREE"] * 5
    ] + [
        {"transformation_type": "c→d", "aggregated": g}
        for g in ["BEFORE_BETTER"] * 12 + ["AFTER_BETTER"] * 1 + ["INSUFFICIENT"] * 2
    ]
    r1, r2 = rsc.learn_rules(rows), rsc.learn_rules(rows)
    assert r1 == r2
    assert r1["a→b"]["action"] == "REWRITE" and r1["c→d"]["action"] == "RETAIN"


# ------------------------------------------------------------ 真实数据测试
def test_split_disjoint_and_atomic():
    if not HAS_REAL_DATA:
        print("skip: real data missing")
        return
    rows, meta, payloads, _ = rsc.load_inputs()
    books_map, provenance = rsc.derive_task_books(rows, meta, payloads)
    assert len(books_map) == 208
    assert sum(provenance.values()) == 208

    s1, d1 = rsc.split_learn_heldout(books_map)
    s2, d2 = rsc.split_learn_heldout(books_map)
    assert s1 == s2 and d1 == d2  # 确定性：同输入同输出

    learn = {t for t, s in s1.items() if s == "learn"}
    held = {t for t, s in s1.items() if s == "heldout"}
    assert not (learn & held), "learn 与 held-out 必须不重叠"
    assert learn | held == set(books_map), "learn ∪ held-out = 全量 208"
    assert d1["learn_tasks"] == len(learn) and d1["heldout_tasks"] == len(held)

    # 分量原子：同一并查集分量的任务绝不跨侧
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


def test_rules_learned_from_learn_only():
    """规则统计必须能由 learn 任务逐一复算（证明规则未用 held-out 调整）。"""
    if not HAS_REAL_DATA:
        print("skip: real data missing")
        return
    with tempfile.TemporaryDirectory() as td:
        p = rsc.run_pipeline(out_dir=Path(td), now="2026-09-09T00:00:00+00:00")
    learn_ids = set(p["split"]["learn_task_ids"])
    held_ids = set(p["split"]["heldout_task_ids"])
    assert not (learn_ids & held_ids)
    assert len(learn_ids) + len(held_ids) == 208

    rows, _, _, _ = rsc.load_inputs()
    by_type: dict[str, Counter] = {}
    for r in rows:
        if r["task_id"] in learn_ids:  # 只允许 learn 参与
            by_type.setdefault(r["transformation_type"], Counter())[r["aggregated"]] += 1
    for tt, ru in p["rules"].items():
        cnt = by_type.get(tt, Counter())
        assert ru["n_learn"] == sum(cnt.values())
        assert ru["after_better"] == cnt["AFTER_BETTER"]
        assert ru["before_better"] == cnt["BEFORE_BETTER"]
        decided = cnt["AFTER_BETTER"] + cnt["BEFORE_BETTER"]
        assert ru["decided"] == decided
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


def test_heldout_csv_consistency():
    if not HAS_REAL_DATA:
        print("skip: real data missing")
        return
    with tempfile.TemporaryDirectory() as td:
        rsc.run_pipeline(out_dir=Path(td), now="2026-09-09T00:00:00+00:00")
        csv_path = Path(td) / "CLOSURE_OLD_NEW_HELDOUT.csv"
        rows = list(csv.DictReader(csv_path.read_text(encoding="utf-8-sig").splitlines()))
        rules = json.loads((Path(td) / "CLOSURE_RULES.json").read_text(encoding="utf-8"))["rules"]

    assert len(rows) == 208 - 125, f"held-out 应为 208-125=83 条，实得 {len(rows)}"
    assert all(r["split"] == "heldout" for r in rows)
    assert len({r["task_id"] for r in rows}) == len(rows), "task_id 不得重复"
    for r in rows:
        judge = r["judge_reference"]
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
        # 不可评任务不得计入任何 correct
        if judge not in rsc.DECIDED_SET:
            assert r["correct_old"] == "" and r["correct_new"] == ""


def test_structural_safety_zero_violations():
    if not HAS_REAL_DATA:
        print("skip: real data missing")
        return
    _, _, payloads, _ = rsc.load_inputs()
    safety = rsc.structural_safety_check(payloads)
    assert safety["payload_slots_checked"] == 208 * 2
    assert safety["slots_with_non_role_owner_fields"] == 0
    assert safety["structural_violations"] == 0


def test_pipeline_outputs_deterministic():
    """完整管线两次运行（固定时间戳）→ 四个输出文件字节一致（同输入同输出）。"""
    if not HAS_REAL_DATA:
        print("skip: real data missing")
        return
    names = ("CLOSURE_RULES.json", "CLOSURE_OLD_NEW_HELDOUT.csv",
             "CLOSURE_OLD_NEW_SUMMARY.json", "SCOPE_CLOSURE_REPORT.md")
    with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
        rsc.run_pipeline(out_dir=Path(td1), now="2026-09-09T00:00:00+00:00")
        rsc.run_pipeline(out_dir=Path(td2), now="2026-09-09T00:00:00+00:00")
        for name in names:
            b1 = (Path(td1) / name).read_bytes()
            b2 = (Path(td2) / name).read_bytes()
            assert b1 == b2, f"{name} 两次运行不一致"
        # 汇总一致性：learn/heldout 计数、结构安全、McNemar 字段齐全
        s = json.loads((Path(td1) / "CLOSURE_OLD_NEW_SUMMARY.json").read_text(encoding="utf-8"))
        assert s["split"]["learn_tasks"] + s["split"]["heldout_tasks"] == 208
        assert s["structural_safety"]["structural_violations"] == 0
        pair = s["heldout_evaluation"]["paired_actionable"]
        assert 0.0 <= pair["mcnemar_exact_p"] <= 1.0
        assert pair["n"] == s["heldout_evaluation"]["new"]["n_actionable"]


if __name__ == "__main__":
    test_action_outcome_mapping()
    test_rule_learning_thresholds()
    test_rule_mapping_deterministic()
    test_split_disjoint_and_atomic()
    test_rules_learned_from_learn_only()
    test_heldout_csv_consistency()
    test_structural_safety_zero_violations()
    test_pipeline_outputs_deterministic()
    print("all tests passed")
