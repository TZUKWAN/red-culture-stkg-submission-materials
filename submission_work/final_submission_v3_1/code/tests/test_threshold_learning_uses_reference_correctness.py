# -*- coding: utf-8 -*-
"""test_threshold_learning_uses_reference_correctness.py — P0-A 回归测试。

背景：run_selective_semantic.main() 曾在 fill_correct 之前调用 learn_threshold，
阈值学习的 utility 全程用 correct=0 计算，优化目标退化为"最小化接受数"，
DEV 阈值学习完全失效。本测试固化修复后的契约：

1. learn_threshold 的结果必须依赖参考标签（翻转标签 ⇒ 阈值改变）；
2. 当高分类样本可分离时，学到的阈值必须接受高正确区而非全弃权；
3. run_selective_semantic.main 的阈值学习路径使用回填后的 correct
   （通过源代码顺序断言 + learn_threshold 单元行为双重保障）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiment_pipelines"))

from run_selective_semantic import learn_threshold  # noqa: E402


def _rows(pairs: list[tuple[float, int]]) -> list[dict[str, object]]:
    return [
        {"sample_id": f"s{i}", "prediction": "Person", "score": s,
         "accepted": 0, "correct": c, "gate_violation": 0, "gate_reason": ""}
        for i, (s, c) in enumerate(pairs)
    ]


def test_learned_threshold_depends_on_reference_labels():
    high = [(0.9, 1), (0.85, 1), (0.8, 1), (0.75, 1)]
    low = [(0.4, 0), (0.35, 0)]
    rows_good = _rows(high + low)
    rows_flipped = _rows([(s, 1 - c) for s, c in high + low])
    t_good = learn_threshold(rows_good)
    t_flip = learn_threshold(rows_flipped)
    # 标签翻转后（同样的分数分布），最优阈值必须不同——否则 correctness 没有参与优化
    assert t_good != t_flip


def test_learned_threshold_accepts_separable_correct_region():
    # 8 条高分全对 + 2 条低分全错：满足 coverage floor 的同时，
    # 阈值应落在 0.7-0.9 之间（接受高分正确区、弃权低分错误区）。
    pairs = [(0.9 - i * 0.01, 1) for i in range(8)] + [(0.5, 0), (0.4, 0)]
    rows = _rows(pairs)
    t = learn_threshold(rows)
    accepted = [s for s, _ in pairs if s >= t]
    assert len(accepted) == 8
    assert t > 0.5  # 两条错样本被弃权


def test_all_wrong_prefers_minimum_acceptance():
    # 全错时 utility 单调随接受数下降 → 最优解是满足 coverage floor(0.30) 的最少接受。
    # 4 行 × 0.30 = 1.2 → 至少接受 2 条。
    pairs = [(0.9, 0), (0.85, 0), (0.8, 0), (0.3, 0)]
    rows = _rows(pairs)
    t = learn_threshold(rows)
    accepted = [s for s, _ in pairs if s >= t]
    assert len(accepted) == 2  # floor 允许的最小接受集


def test_main_learns_threshold_after_fill_correct():
    # 源代码顺序守卫：main() 中 fill_correct 必须先于 learn_threshold 出现
    src = Path(__file__).resolve().parent.parent / "experiment_pipelines" / "run_selective_semantic.py"
    text = src.read_text(encoding="utf-8")
    main_start = text.index("def main(")
    body = text[main_start:]
    fill_pos = body.index("fill_correct(variants, reference)")
    learn_pos = body.index("learn_threshold(dev_controller)")
    assert fill_pos < learn_pos, "P0-A 回归：main() 中阈值学习发生在 correct 回填之前"
