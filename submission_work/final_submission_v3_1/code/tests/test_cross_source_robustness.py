# -*- coding: utf-8 -*-
"""test_cross_source_robustness.py — §18 三切分跨来源稳健性冒烟测试（无网络、无数据库）。

覆盖 run_cross_source_robustness.py 的关键单元（合成数据）：
1. rank_hash 确定性与值域；
2. random_split：精确 80/20、互斥、可复现；
3. book_grouped_split：同书实体绝不跨 train/held-out；最大分量按构造归 train；
   无书实体按哈希分配；预算补足到 80%；
4. province_holdout_split：选中位省（并列取 province_order 小者）；held-out =
   关联该省的全部实体（含跨省）；无省实体留 train；
5. aurc_trapezoid：rows_to_points 阈值扫描上的梯形积分，手算值核对；
6. run_split_experiment 微型端到端：指标键齐全、coverage/risk 一致、
   同名/同书泄漏诊断计数正确（嵌入用合成矩阵，不连 LM Studio）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiment_pipelines"))

from run_cross_source_robustness import (  # noqa: E402
    SEED,
    aurc_trapezoid,
    book_grouped_split,
    province_holdout_split,
    random_split,
    rank_hash,
    run_split_experiment,
    union_find_components,
)
from selective_stats import rows_to_points  # noqa: E402


# ---------------------------------------------------------------------------
# 1. rank_hash
# ---------------------------------------------------------------------------

def test_rank_hash_deterministic_and_in_unit_interval():
    a = [rank_hash("x", SEED) for _ in range(3)]
    assert a[0] == a[1] == a[2]
    assert 0.0 <= a[0] < 1.0
    # 不同 key / 不同 seed 应给出不同秩（32 个样本至少 2 个不同值）
    vals = {rank_hash(f"k{i}", SEED) for i in range(32)}
    assert len(vals) > 20


# ---------------------------------------------------------------------------
# 2. random_split
# ---------------------------------------------------------------------------

def test_random_split_exact_ratio_disjoint_deterministic():
    ids = [f"e{i:03d}" for i in range(100)]
    a1 = random_split(ids, seed=SEED, ratio=0.8)
    a2 = random_split(ids, seed=SEED, ratio=0.8)
    assert a1 == a2  # 可复现（无 RNG 状态）
    tr = [e for e, v in a1.items() if v == "train"]
    ho = [e for e, v in a1.items() if v == "heldout"]
    assert len(tr) == 80 and len(ho) == 20  # round(0.8*100)
    assert not (set(tr) & set(ho))
    assert set(tr) | set(ho) == set(ids)
    # 换 seed 分布应变化（不强制，但 100 实体下 80 切口几乎必变）
    a3 = random_split(ids, seed=SEED + 1, ratio=0.8)
    assert a3 != a1


# ---------------------------------------------------------------------------
# 3. book_grouped_split
# ---------------------------------------------------------------------------

def _toy_books() -> tuple[list[str], dict[str, set[str]]]:
    ids = [f"e{i}" for i in range(20)]
    books = {
        "e0": {"B1"}, "e1": {"B1"}, "e2": {"B1", "B2"},  # B1 组
        "e3": {"B2"},                                     # 经 e2 与 B1 组连通 → 4 实体分量
        "e4": {"B3"}, "e5": {"B3"},                       # B3 组
        "e6": {"B4"},                                     # 单实体有书分量
        "e7": set(), "e8": set(), "e9": set(), "e10": set(), "e11": set(),
        "e12": set(), "e13": set(), "e14": set(), "e15": set(),
        "e16": set(), "e17": set(), "e18": set(), "e19": set(),
    }
    return ids, books


def test_union_find_groups_same_book_entities():
    ids, books = _toy_books()
    comps = union_find_components(ids, books)
    member_sets = {frozenset(v) for v in comps.values()}
    assert {"e0", "e1", "e2", "e3"} in member_sets  # 经共享书连通
    assert {"e4", "e5"} in member_sets
    assert {"e6"} in member_sets
    assert {"e7"} in member_sets  # 无书单部分量
    assert sum(len(v) for v in comps.values()) == len(ids)


def test_book_grouped_split_same_book_never_cross_and_ratio_reached():
    ids, books = _toy_books()
    a1, info = book_grouped_split(ids, books, seed=SEED, ratio=0.8)
    a2, info2 = book_grouped_split(ids, books, seed=SEED, ratio=0.8)
    assert a1 == a2 and info == info2  # 可复现
    tr = {e for e, v in a1.items() if v == "train"}
    ho = set(ids) - tr
    # 同书完整性：任一书的实体集合不得跨 train/held-out
    by_book: dict[str, set[str]] = {}
    for e in ids:
        for b in books[e]:
            by_book.setdefault(b, set()).add(e)
    for b, members in by_book.items():
        assert members <= tr or members <= ho, f"book {b} straddles split"
    # 最大分量（4 实体）按构造归 train
    assert {"e0", "e1", "e2", "e3"} <= tr
    assert info["largest_component_pinned_to"] == "train"
    assert info["n_train"] + info["n_heldout"] == len(ids)
    assert info["n_train"] == len(tr) == 16  # round(0.8*20)，预算由单部分量补足
    assert info["n_heldout"] == 4


# ---------------------------------------------------------------------------
# 4. province_holdout_split
# ---------------------------------------------------------------------------

def test_province_holdout_median_tiebreak_and_completeness():
    ids = ["a1", "a2", "a3", "b1", "b2", "c1", "c2", "c3", "c4", "c5", "d1"]
    provs = {
        "a1": {"湖北省"}, "a2": {"湖北省"}, "a3": {"湖北省", "江苏省"},  # 跨省实体
        "b1": {"江苏省"}, "b2": {"江苏省"},
        "c1": {"四川省"}, "c2": {"四川省"}, "c3": {"四川省"}, "c4": {"四川省"}, "c5": {"四川省"},
        "d1": set(),  # 无省
    }
    order = {"湖北省": 6, "江苏省": 10, "四川省": 2, "青海省": 0}
    a, info = province_holdout_split(ids, provs, order)
    # 计数：四川 5、湖北 3、江苏 3、（青海 0）→ 序 [0,3,3,5]，上中位 = 3，并列取 order 小者 → 湖北
    assert info["chosen_province"] == "湖北省"
    assert info["median_count"] == 3
    ho = {e for e, v in a.items() if v == "heldout"}
    assert ho == {"a1", "a2", "a3"}  # 含跨省 a3，省份完整
    tr = set(ids) - ho
    assert "b1" in tr and "d1" in tr  # 他省与无省实体留 train
    assert info["n_train"] + info["n_heldout"] == len(ids)


def test_province_holdout_even_count_uses_upper_median():
    ids = ["x1", "x2", "y1", "y2", "y3", "z1"]
    provs = {"x1": {"甲"}, "x2": {"甲"}, "y1": {"乙"}, "y2": {"乙"}, "y3": {"乙"}, "z1": {"丙"}}
    a, info = province_holdout_split(ids, provs, {"甲": 0, "乙": 1, "丙": 2})
    # 计数 [1,2,3] → 上中位 2 → 甲（2 个实体）
    assert info["chosen_province"] == "甲"
    assert {e for e, v in a.items() if v == "heldout"} == {"x1", "x2"}


# ---------------------------------------------------------------------------
# 5. AURC（手写梯形）
# ---------------------------------------------------------------------------

def test_aurc_zero_for_perfect_and_max_for_all_wrong():
    # 约定：rows_to_points 曲线含原点 (coverage=0, risk=0)；
    # 梯形积分下全错曲线 = 1 − 1/(2n)（首个梯形从 0 爬升到 1）。
    n = 10
    pts = rows_to_points([{"sample_id": i, "accepted": 1, "correct": 1, "score": 1 - i / n} for i in range(n)])
    assert abs(aurc_trapezoid(pts)) < 1e-12
    pts = rows_to_points([{"sample_id": i, "accepted": 1, "correct": 0, "score": 1 - i / n} for i in range(n)])
    assert abs(aurc_trapezoid(pts) - (1.0 - 0.5 / n)) < 1e-12


def test_aurc_matches_hand_computed_trapezoid():
    # 2 样本：score 降序 [0.9(错), 0.8(对)] → 点 (0,0) (0.5,1.0) (1.0,0.5)
    rows = [
        {"sample_id": "a", "accepted": 1, "correct": 0, "score": 0.9},
        {"sample_id": "b", "accepted": 1, "correct": 1, "score": 0.8},
    ]
    pts = rows_to_points(rows)
    assert abs(pts[1]["coverage"] - 0.5) < 1e-12 and abs(pts[1]["selective_risk"] - 1.0) < 1e-12
    assert abs(pts[2]["selective_risk"] - 0.5) < 1e-12
    # 梯形 = 0.5*(0+1)/2 + 0.5*(1+0.5)/2 = 0.625
    assert abs(aurc_trapezoid(pts) - 0.625) < 1e-12


# ---------------------------------------------------------------------------
# 6. run_split_experiment 微型端到端（合成嵌入）
# ---------------------------------------------------------------------------

def test_run_split_experiment_metrics_and_leakage_diagnostics():
    ids = [f"e{i}" for i in range(10)]
    texts = ["甲要义", "甲要义", "乙考", "丙志", "丁记", "戊略", "己闻", "庚录", "辛鉴", "壬谱"]
    labels = ["Place", "Place", "Place", "Event", "Event", "Org", "Org", "Org", "Person", "Person"]
    # 可分合成嵌入：3 维 one-hot 派生（类间线性可分）
    emb = np.zeros((10, 4))
    for i, lab in enumerate(labels):
        emb[i, {"Place": 0, "Event": 1, "Org": 2, "Person": 3}[lab]] = 1.0
    books = {e: set() for e in ids}
    books["e0"] = {"B1"}
    books["e1"] = {"B1", "B2"}
    books["e2"] = {"B2"}
    assignment = {e: "train" for e in ids}
    assignment["e1"] = "heldout"  # 与 train 同名（甲要义）且同书（B1/B2）
    assignment["e9"] = "heldout"  # 无书、名字独有

    res = run_split_experiment(
        "toy", assignment, emb, labels, texts, ids, books,
        {"C": 2.0, "class_weight": "balanced", "max_iter": 1000, "random_state": SEED},
    )
    assert res["n_train"] == 8 and res["n_heldout"] == 2
    for k in ("accuracy", "macro_f1", "balanced_accuracy", "coverage", "selective_risk", "aurc_trapezoid"):
        assert res[k] is not None
        if k not in ("selective_risk",):
            assert 0.0 <= res[k] <= 1.0
    assert res["accuracy"] == 1.0  # 线性可分玩具集应全对
    # coverage / selective risk 一致性：全对 ⇒ coverage 内错误率 0
    assert res["selective_risk"] == 0.0
    assert res["coverage"] == 1.0 or res["n_covered"] >= 1
    # 泄漏诊断：e1 同名 + 同书；e9 无书专名
    diag = res["leakage_diagnostic"]
    assert diag["heldout_dup_name_in_train"] == 1
    assert diag["heldout_share_book_with_train"] == 1
    assert diag["heldout_booked"] == 1
    # 逐类 F1 覆盖 held-out 出现过的类
    assert set(res["per_class_f1"]) == {"Place", "Person"}
    assert abs(res["per_class_f1"]["Place"] - 1.0) < 1e-9
    # AURC：全对曲线恒 0
    assert abs(res["aurc_trapezoid"]) < 1e-9
