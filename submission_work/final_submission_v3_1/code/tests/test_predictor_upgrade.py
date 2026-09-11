# -*- coding: utf-8 -*-
"""test_predictor_upgrade.py — M3 预测器升级管线冒烟测试（无网络依赖）。

覆盖 run_predictor_upgrade.py 的关键单元：
1. ECE / 多类 Brier 指标的解析性质（完美预测 → 0，失准 → 增大）；
2. 嵌入缓存：批量 + 落盘 + 断点续跑（二次调用零重算）；
3. 路线 A / B / C 在微型数据上可拟合可预测（嵌入用注入桩，不连 LM Studio）；
4. 胜者判定规则：嵌入路线须在 DEV 上领先 A >2 个百分点才记显著升级。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import Normalizer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiment_pipelines"))

from run_predictor_upgrade import (  # noqa: E402
    ROUTES,
    EmbedTextClassifier,
    FusedCharEmbedClassifier,
    build_char_tfidf,
    build_route_a,
    decide_winner,
    ece_score,
    embed_cached,
    multiclass_brier,
)


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------

def test_ece_zero_for_perfect_confident_predictions():
    conf = np.array([1.0, 1.0, 1.0, 1.0])
    correct = np.array([1.0, 1.0, 1.0, 1.0])
    assert ece_score(conf, correct) == 0.0


def test_ece_increases_with_miscalibration():
    conf = np.array([0.9] * 10)
    correct_all_right = np.array([1.0] * 10)
    correct_half = np.array([1.0, 0.0] * 5)
    e_good = ece_score(conf, correct_all_right)
    e_bad = ece_score(conf, correct_half)
    assert e_good < e_bad  # 同样置信、正确率下降 ⇒ ECE 变大
    assert 0.0 <= e_good <= 1.0


def test_multiclass_brier_bounds():
    classes = ["a", "b"]
    perfect = np.array([[1.0, 0.0], [0.0, 1.0]])
    uniform = np.array([[0.5, 0.5], [0.5, 0.5]])
    assert multiclass_brier(perfect, classes, ["a", "b"]) == 0.0
    assert abs(multiclass_brier(uniform, classes, ["a", "b"]) - 0.5) < 1e-9
    # 真标签在模型类空间之外：该维 p=0、o=1，整行罚 1 分（标签空间失配被惩罚）
    assert abs(multiclass_brier(perfect, classes, ["a", "z"]) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# 嵌入缓存（批量 + checkpoint 落盘 + 断点续跑）
# ---------------------------------------------------------------------------

def test_embed_cache_roundtrip_and_resume(tmp_path):
    calls = {"n": 0}

    def fake_embed(texts):
        calls["n"] += len(texts)
        return [[float(len(t)), 1.0] for t in texts]

    texts = ["长城", "故宫", "兵马俑", "敦煌莫高窟"]
    npy = tmp_path / "EMB_CACHE.npy"
    keys = tmp_path / "EMB_CACHE.keys.json"
    m1, s1 = embed_cached(texts, npy, keys, batch_size=2, checkpoint_every=3, embed_fn=fake_embed)
    assert m1.shape == (4, 2)
    assert s1["n_new_embedded"] == 4
    assert np.allclose(m1[0], [2.0, 1.0])  # 顺序保持：第一行对应"长城"
    n_first = calls["n"]

    m2, s2 = embed_cached(texts, npy, keys, batch_size=2, checkpoint_every=3, embed_fn=fake_embed)
    assert calls["n"] == n_first  # 断点续跑：全部命中缓存，零重算
    assert s2["n_new_embedded"] == 0
    assert np.allclose(m1, m2)

    # 增量：新文本只补算缺失部分
    m3, s3 = embed_cached(texts + ["云冈石窟"], npy, keys, batch_size=2,
                          checkpoint_every=3, embed_fn=fake_embed)
    assert m3.shape == (5, 2)
    assert s3["n_new_embedded"] == 1


# ---------------------------------------------------------------------------
# 三条路线（微型数据，嵌入走注入桩）
# ---------------------------------------------------------------------------

_TEXTS = ["长城遗址", "长城遗址", "故宫博物院", "故宫博物院", "清华同学会", "清华同学会", "红军长征", "红军长征"]
_LABELS = ["Place", "Place", "Place", "Place", "Institution", "Institution", "Event", "Event"]


def _stub_embed(texts):
    # 词袋式确定性桩：出现"长/故/清"首字的 one-hot 偏置
    out = []
    for t in texts:
        base = [0.0, 0.0, 0.0]
        base["长城".find(t[0]) % 3 if t[0] in "长故清" else 0] += 1.0
        out.append(base)
    return out


def test_route_a_fit_predict_smoke():
    pipe = build_route_a().fit(_TEXTS, _LABELS)
    proba = pipe.predict_proba(["长城遗址", "清华同学会"])
    assert proba.shape == (2, 3)
    assert np.allclose(proba.sum(axis=1), 1.0)
    assert list(pipe.classes_) == ["Event", "Institution", "Place"]


def test_route_b_artifact_uses_injected_embed_fn():
    X = np.asarray(_stub_embed(_TEXTS), dtype=float)
    lr = LogisticRegression(C=2, class_weight="balanced", max_iter=1000).fit(X, _LABELS)
    model = EmbedTextClassifier(lr, sorted(set(_LABELS)))
    proba = model.predict_proba(["长城遗址", "清华同学会"], embed_fn=_stub_embed)
    assert proba.shape == (2, 3)
    assert model.predict(["长城遗址"], embed_fn=_stub_embed)[0] in ("Place", "Institution", "Event")


def test_route_c_fused_artifact_smoke():
    vec = build_char_tfidf().fit(_TEXTS)
    E = np.asarray(_stub_embed(_TEXTS), dtype=float)
    scaler = Normalizer(norm="l2").fit(E)
    X = sp.hstack([vec.transform(_TEXTS), sp.csr_matrix(scaler.transform(E))], format="csr")
    clf = LogisticRegression(C=2, class_weight="balanced", max_iter=1000).fit(X, _LABELS)
    model = FusedCharEmbedClassifier(vec, scaler, clf, sorted(set(_LABELS)))
    proba = model.predict_proba(["长城遗址"], embed_fn=_stub_embed)
    assert proba.shape == (1, 3)
    assert np.isclose(proba.sum(), 1.0)


# ---------------------------------------------------------------------------
# 胜者判定
# ---------------------------------------------------------------------------

def _fake_metrics(dev: dict, val: dict) -> dict:
    return {
        r: {"dev": {"macro_f1": dev[r]}, "val": {"macro_f1": val[r]}}
        for r in ROUTES
    }


def test_embedding_route_wins_only_when_margin_exceeds_2_points():
    # B 领先 A 3 个点（DEV）→ 显著升级
    d = decide_winner(_fake_metrics(
        dev={"A_char_tfidf_sgd": 0.50, "B_embed_lr": 0.53, "C_fused_char_embed": 0.51},
        val={"A_char_tfidf_sgd": 0.48, "B_embed_lr": 0.49, "C_fused_char_embed": 0.47},
    ))
    assert d["winner_route"] == "B_embed_lr"
    assert d["significant_upgrade"] is True

    # B 仅领先 1 个点 → 胜者仍是 B 但不构成显著升级
    d2 = decide_winner(_fake_metrics(
        dev={"A_char_tfidf_sgd": 0.50, "B_embed_lr": 0.51, "C_fused_char_embed": 0.49},
        val={"A_char_tfidf_sgd": 0.48, "B_embed_lr": 0.48, "C_fused_char_embed": 0.47},
    ))
    assert d2["winner_route"] == "B_embed_lr"
    assert d2["significant_upgrade"] is False

    # A 自身最优 → 无嵌入升级
    d3 = decide_winner(_fake_metrics(
        dev={"A_char_tfidf_sgd": 0.55, "B_embed_lr": 0.53, "C_fused_char_embed": 0.52},
        val={"A_char_tfidf_sgd": 0.50, "B_embed_lr": 0.49, "C_fused_char_embed": 0.48},
    ))
    assert d3["winner_route"] == "A_char_tfidf_sgd"
    assert d3["significant_upgrade"] is False
