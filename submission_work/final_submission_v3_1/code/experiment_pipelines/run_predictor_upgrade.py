# -*- coding: utf-8 -*-
"""run_predictor_upgrade.py — M3：entity_type 语义预测器三路线升级对比。

指令 §五：在独立参考（IMCR strong，只做评价）上对比三条预测器路线——

    A  baseline_char_tfidf   复现生产基线：TF-IDF(char 3-5) + SGDClassifier
                             （loss=log_loss，关键超参对齐生产 260 脚本 /
                             stkg_v2_entity_classifier.joblib，不追求逐字节复刻）
    B  embed_lr              nomic-embed 嵌入（本地 LM Studio provider，
                             批量 + npy 缓存断点续跑）+ LogisticRegression(C=2,
                             class_weight=balanced)
    C  fused_char_embed      B 的嵌入（L2 归一）⊕ A 的 char TF-IDF 稀疏拼接
                             + LogisticRegression(C=2, class_weight=balanced)

训练集 = data/source_data/stkg_v2_entity_classifier.sqlite 表 entity_predictions
中全部 class_gate_pass=1 的行（weak 标签 = predicted_type，文本 = canonical_name；
该表无 aliases 列）。评价集 = IMCR_REFERENCE_STRONG.csv 的 entity_type 行
（sample_id → reference_label），样本实体名取自 run_selective_semantic
.build_signal_frame()（只读复用），只在 DEV/VAL 上评价，TEST 不碰。

判定：嵌入路线（B/C）在 DEV 上 macro-F1 高于 A 且差 >2 个百分点才算显著升级；
优胜路线落盘为 experiments/02_selective_semantic/predictor_upgrade/
M3_improved_predictor.joblib。

泄漏声明：weak 标签来自生产分类器分数表（与 IMCR 独立评审零重叠），
IMCR 参考标签仅出现在评价路径，绝不进入任何训练/拟合调用。

运行：
    python run_predictor_upgrade.py            # 全量（DEV/VAL 评价 + 落盘）
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np
import scipy.sparse as sp
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import Normalizer

V3_1 = Path(__file__).resolve().parents[2]
REPO = V3_1.parent.parent
SQLITE_PATH = REPO / "data" / "source_data" / "stkg_v2_entity_classifier.sqlite"
V3 = V3_1.parent / "final_submission_v3"
IMCR_STRONG = V3 / "experiments" / "08_independent_reference" / "IMCR_REFERENCE_STRONG.csv"
OUT_DIR = V3_1 / "experiments" / "02_selective_semantic" / "predictor_upgrade"
EMB_CACHE_NPY = OUT_DIR / "emb_cache" / "EMB_CACHE.npy"
EMB_CACHE_KEYS = OUT_DIR / "emb_cache" / "EMB_CACHE.keys.json"

SEED = 20260908  # 与 run_selective_semantic.GLOBAL_SEED 一致
EMBED_BATCH = 64
EMBED_CHECKPOINT_EVERY = 500  # 每 500 条新嵌入落盘一次（断点续跑）
N_ECE_BINS = 10
SIGNIFICANT_DELTA = 0.02  # macro-F1 差 >2 个百分点
ROUTES = ("A_char_tfidf_sgd", "B_embed_lr", "C_fused_char_embed")

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "independent_eval"))


# ---------------------------------------------------------------------------
# 训练集（weak labels）与评价集（独立参考，只读）
# ---------------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_training_data(sqlite_path: Path = SQLITE_PATH) -> tuple[list[str], list[str], dict[str, Any]]:
    """训练集 = entity_predictions 全部 class_gate_pass=1 行。

    weak 标签 = predicted_type（生产分类器分数表自带），文本 = canonical_name
    （表结构无 aliases 列）。confidence/margin 仅入 manifest，不用作样本权重。
    """
    con = sqlite3.connect(str(sqlite_path))
    try:
        rows = con.execute(
            "select entity_id, canonical_name, predicted_type, confidence, margin "
            "from entity_predictions where class_gate_pass=1 order by entity_id"
        ).fetchall()
        total = con.execute("select count(*) from entity_predictions").fetchone()[0]
    finally:
        con.close()
    texts = [str(r[1]) for r in rows]
    labels = [str(r[2]) for r in rows]
    from collections import Counter

    manifest = {
        "source": str(sqlite_path),
        "sha256": sha256_of(sqlite_path),
        "table": "entity_predictions",
        "filter": "class_gate_pass=1",
        "weak_label_field": "predicted_type",
        "text_field": "canonical_name (表无 aliases 列)",
        "n_rows_total": int(total),
        "n_train": len(texts),
        "class_distribution": dict(sorted(Counter(labels).items())),
        "confidence_stats": {
            "min": float(min(r[3] for r in rows)),
            "mean": float(np.mean([r[3] for r in rows])),
            "max": float(max(r[3] for r in rows)),
        },
        "leakage_statement": (
            "weak 标签来自生产分类器（260 冻结模型）分数表；IMCR strong 独立参考"
            "仅用于 DEV/VAL 评价，不进入任何训练/拟合调用。"
        ),
    }
    return texts, labels, manifest


def load_eval_sets() -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, str]]:
    """返回 ({"dev": sids, "val": sids}, {"dev": texts, "val": texts}, {"dev": labels, ...})。

    复用 run_selective_semantic.build_signal_frame()（只读）取样本实体名；
    参考标签取 IMCR_REFERENCE_STRONG 的 entity_type 行；切分用冻结
    SPLIT_MANIFEST（entity_type 前缀键）。TEST 一律排除。
    """
    import run_selective_semantic as rss

    frame = rss.build_signal_frame()
    reference = rss.load_reference("strong")
    split = rss.load_split()
    out_ids: dict[str, list[str]] = {}
    out_texts: dict[str, list[str]] = {}
    out_labels: dict[str, list[str]] = {}
    for name in ("dev", "val"):  # TEST 不碰：仅构造 dev/val
        sids = [sid for sid in frame if split.get(f"entity_type:{sid}") == name and sid in reference]
        out_ids[name] = sids
        out_texts[name] = [str(frame[sid]["name"]) for sid in sids]
        out_labels[name] = [reference[sid] for sid in sids]
    return out_ids, out_texts, out_labels


# ---------------------------------------------------------------------------
# 嵌入（本地 LM Studio provider，批量 + npy 缓存 + 断点续跑）
# ---------------------------------------------------------------------------

def default_embed_fn() -> Callable[[list[str]], list[list[float]]]:
    """延迟导入本地 provider（禁止公网：base URL 默认 127.0.0.1）。"""
    from lmstudio_provider import embed

    return embed


def _load_cache(npy_path: Path, keys_path: Path) -> dict[str, np.ndarray]:
    if not (npy_path.exists() and keys_path.exists()):
        return {}
    try:
        vectors = np.load(npy_path)
        keys = json.loads(keys_path.read_text(encoding="utf-8"))
        if len(keys) != vectors.shape[0]:
            raise ValueError("cache keys/vectors 长度不一致")
        return {k: vectors[i] for i, k in enumerate(keys)}
    except Exception as exc:  # 缓存损坏则重建
        print(f"[predictor_upgrade] warn: 嵌入缓存不可读（{exc}），重建缓存")
        return {}


def embed_cached(
    texts: list[str],
    npy_path: Path = EMB_CACHE_NPY,
    keys_path: Path = EMB_CACHE_KEYS,
    *,
    batch_size: int = EMBED_BATCH,
    checkpoint_every: int = EMBED_CHECKPOINT_EVERY,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """批量嵌入 + npy 缓存 + 每 checkpoint_every 条落盘（断点续跑）。

    返回 (Nxdim 矩阵, 统计信息)。重复文本天然去重（缓存按文本键）。
    """
    embed = embed_fn or default_embed_fn()
    npy_path.parent.mkdir(parents=True, exist_ok=True)
    cache = _load_cache(npy_path, keys_path)
    unique = list(dict.fromkeys(texts))
    missing = [t for t in unique if t not in cache]
    t0 = time.perf_counter()
    new_since_save = 0

    def _save() -> None:
        keys = list(cache.keys())
        np.save(npy_path, np.stack([cache[k] for k in keys]))
        keys_path.write_text(json.dumps(keys, ensure_ascii=False), encoding="utf-8")

    try:
        for i in range(0, len(missing), batch_size):
            batch = missing[i : i + batch_size]
            vecs = embed(batch)
            for t, v in zip(batch, vecs):
                cache[t] = np.asarray(v, dtype=np.float32)
            new_since_save += len(batch)
            if new_since_save >= checkpoint_every:  # 每 500 条落盘
                _save()
                new_since_save = 0
                print(f"[predictor_upgrade] emb checkpoint: {len(cache)}/{len(unique)} cached")
    finally:  # 中断也不丢已算好的批次
        if new_since_save:
            _save()
    elapsed = time.perf_counter() - t0
    dim = len(next(iter(cache.values()))) if cache else 0
    stats = {
        "n_requested": len(texts),
        "n_unique": len(unique),
        "n_new_embedded": len(missing),
        "dim": dim,
        "seconds": round(elapsed, 2),
        "batch_size": batch_size,
        "checkpoint_every": checkpoint_every,
        "cache": str(npy_path),
        "backend": "lmstudio text-embedding-nomic-embed-text-v1.5 (本地 127.0.0.1)",
    }
    mat = np.stack([cache[t] for t in unique]).astype(np.float64) if unique else np.zeros((0, dim))
    index = {t: i for i, t in enumerate(unique)}
    order = np.array([index[t] for t in texts]) if texts else np.zeros(0, dtype=int)
    return mat[order], stats


# ---------------------------------------------------------------------------
# 指标：accuracy / macro-F1 / balanced accuracy / ECE(10) / Brier
# ---------------------------------------------------------------------------

def ece_score(conf: np.ndarray, correct: np.ndarray, n_bins: int = N_ECE_BINS) -> float:
    """期望校准误差（等宽 n_bins 箱，按 max-prob 置信分箱）。"""
    conf = np.asarray(conf, dtype=float)
    correct = np.asarray(correct, dtype=float)
    if len(conf) == 0:
        return 0.0
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.minimum(np.digitize(conf, edges[1:-1], right=False), n_bins - 1)
    n = len(conf)
    total = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.any():
            total += (m.sum() / n) * abs(correct[m].mean() - conf[m].mean())
    return float(total)


def multiclass_brier(proba: np.ndarray, model_classes: list[str], y_true: list[str]) -> float:
    """多类 Brier = mean_t Σ_c (p_tc − o_tc)²，类空间取模型类 ∪ 真标签。"""
    union = sorted(set(model_classes) | set(y_true))
    idx = {c: i for i, c in enumerate(union)}
    P = np.zeros((len(y_true), len(union)))
    for j, c in enumerate(model_classes):
        if c in idx:
            P[:, idx[c]] = proba[:, j]
    Y = np.zeros_like(P)
    for i, t in enumerate(y_true):
        Y[i, idx[t]] = 1.0
    return float(np.mean(np.sum((P - Y) ** 2, axis=1)))


def evaluate_split(
    y_true: list[str],
    proba: np.ndarray,
    model_classes: list[str],
    train_classes: set[str],
) -> dict[str, Any]:
    """独立参考上的点预测指标（模型可输出类 = 训练 weak 标签空间）。"""
    y_pred = [model_classes[int(i)] for i in proba.argmax(axis=1)]
    conf = proba.max(axis=1)
    correct = np.array([float(p == t) for p, t in zip(y_pred, y_true)])
    labels = sorted(set(y_true))  # 参考中出现的类（模型预测不到的类按 0 计）
    covered = [c for c in labels if c in train_classes]  # weak 标签空间可覆盖子集
    return {
        "n": len(y_true),
        "n_ref_classes": len(labels),
        "n_ref_classes_covered_by_train": len(covered),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "macro_f1": round(float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)), 4),
        "macro_f1_covered_only": round(
            float(f1_score(y_true, y_pred, labels=covered, average="macro", zero_division=0)), 4
        )
        if covered
        else None,
        "balanced_accuracy": round(
            float(recall_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)), 4
        ),
        "ece_10bins": round(ece_score(conf, correct), 4),
        "brier_multiclass": round(multiclass_brier(proba, model_classes, y_true), 4),
    }


# ---------------------------------------------------------------------------
# 三条路线
# ---------------------------------------------------------------------------

def build_char_tfidf() -> TfidfVectorizer:
    """生产同款 char TF-IDF 块（路线 A 与路线 C 共用）。"""
    return TfidfVectorizer(
        analyzer="char",
        ngram_range=(3, 5),
        min_df=2,
        max_df=1.0,
        sublinear_tf=True,
        lowercase=True,
        norm="l2",
        use_idf=True,
    )


def build_route_a() -> Pipeline:
    """A 复现基线：char TF-IDF(3-5) + SGD(log_loss)。

    关键超参对齐生产 260 脚本（stkg_v2_entity_classifier.joblib 实测：
    loss=log_loss, alpha=2e-6, max_iter=40, elasticnet, optimal, balanced，
    sublinear_tf=True, min_df=2）；ngram 按指令用 (3,5)。
    """
    return Pipeline(
        [
            ("tfidf", build_char_tfidf()),
            (
                "clf",
                SGDClassifier(
                    loss="log_loss",
                    alpha=2e-6,
                    max_iter=40,
                    class_weight="balanced",
                    penalty="elasticnet",
                    learning_rate="optimal",
                    eta0=0.01,
                    tol=1e-4,
                    early_stopping=False,
                    random_state=SEED,
                ),
            ),
        ]
    )


class EmbedTextClassifier:
    """路线 B 工件：nomic-embed 嵌入 + 线性分类头。

    predict 需本地 LM Studio embeddings 服务（127.0.0.1:1234，禁止公网）。
    """

    def __init__(self, clf: LogisticRegression, classes: list[str]):
        self.clf = clf
        self.classes = list(classes)
        self.backend = "lmstudio text-embedding-nomic-embed-text-v1.5 (本地)"

    def transform(self, texts: list[str], embed_fn=None) -> np.ndarray:
        embed = embed_fn or default_embed_fn()
        return np.asarray(embed(list(texts)), dtype=np.float64)

    def predict_proba(self, texts: list[str], embed_fn=None) -> np.ndarray:
        return self.clf.predict_proba(self.transform(texts, embed_fn))

    def predict(self, texts: list[str], embed_fn=None) -> list[str]:
        return [self.classes[i] for i in self.predict_proba(texts, embed_fn).argmax(axis=1)]


class FusedCharEmbedClassifier:
    """路线 C 工件：char TF-IDF 稀疏块 ⊕ L2 归一嵌入块 拼接 + 线性分类头。"""

    def __init__(self, vectorizer: TfidfVectorizer, emb_scaler: Normalizer,
                 clf: LogisticRegression, classes: list[str]):
        self.vectorizer = vectorizer
        self.emb_scaler = emb_scaler
        self.clf = clf
        self.classes = list(classes)
        self.backend = "char tfidf ⊕ lmstudio nomic-embed (本地)"

    def transform(self, texts: list[str], embed_fn=None) -> sp.csr_matrix:
        texts = list(texts)
        Xs = self.vectorizer.transform(texts)
        embed = embed_fn or default_embed_fn()
        E = np.asarray(embed(texts), dtype=np.float64)
        return sp.hstack([Xs, sp.csr_matrix(self.emb_scaler.transform(E))], format="csr")

    def predict_proba(self, texts: list[str], embed_fn=None) -> np.ndarray:
        return self.clf.predict_proba(self.transform(texts, embed_fn))

    def predict(self, texts: list[str], embed_fn=None) -> list[str]:
        return [self.classes[i] for i in self.predict_proba(texts, embed_fn).argmax(axis=1)]


def build_lr() -> LogisticRegression:
    return LogisticRegression(C=2, class_weight="balanced", max_iter=5000, random_state=SEED)


# joblib 工件可移植性：B/C 工件类以规范模块名序列化（脚本直跑时 dump 前注册别名）。
_CANONICAL = "run_predictor_upgrade"
EmbedTextClassifier.__module__ = _CANONICAL
FusedCharEmbedClassifier.__module__ = _CANONICAL


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def decide_winner(metrics: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    """DEV macro-F1 定胜负；嵌入路线需领先 A >2 点才记为显著升级。"""
    dev_f1 = {r: metrics[r]["dev"]["macro_f1"] for r in ROUTES}
    val_f1 = {r: metrics[r]["val"]["macro_f1"] for r in ROUTES}
    winner = max(ROUTES, key=lambda r: (dev_f1[r], val_f1[r]))
    delta_dev = round(dev_f1[winner] - dev_f1["A_char_tfidf_sgd"], 4)
    delta_val = round(val_f1[winner] - val_f1["A_char_tfidf_sgd"], 4)
    return {
        "winner_route": winner,
        "is_embedding_route": winner in ("B_embed_lr", "C_fused_char_embed"),
        "macro_f1_delta_vs_A_dev": delta_dev,
        "macro_f1_delta_vs_A_val": delta_val,
        "significant_upgrade": bool(
            winner in ("B_embed_lr", "C_fused_char_embed") and delta_dev > SIGNIFICANT_DELTA
        ),
        "rule": f"DEV macro-F1 最高者胜出；嵌入路线须领先 A >{SIGNIFICANT_DELTA:.2f} 才算显著升级",
        "decision_split": "dev (val 仅观察)",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-save-model", action="store_true", help="只评价，不落盘 winner 模型")
    args = ap.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t_all = time.perf_counter()

    # ---- 数据 ----
    train_texts, train_labels, train_manifest = load_training_data()
    print(f"[predictor_upgrade] train rows (gate_pass=1): {len(train_texts)}")
    eval_ids, eval_texts, eval_labels = load_eval_sets()
    print(
        "[predictor_upgrade] eval with IMCR strong reference: "
        f"dev={len(eval_ids['dev'])} val={len(eval_ids['val'])} (test 不碰)"
    )

    # ---- 嵌入（训练 + DEV/VAL 文本统一走缓存）----
    all_eval_names = eval_texts["dev"] + eval_texts["val"]
    emb_train, emb_stats_tr = embed_cached(train_texts)
    emb_eval_dev, _ = embed_cached(eval_texts["dev"])
    emb_eval_val, emb_stats_ev = embed_cached(eval_texts["dev"] + eval_texts["val"])
    emb_eval_val = emb_eval_val[len(eval_texts["dev"]):]
    emb_stats = {**emb_stats_tr, "eval_extra_seconds": emb_stats_ev["seconds"]}
    print(
        f"[predictor_upgrade] embeddings: unique_new={emb_stats['n_new_embedded']} "
        f"dim={emb_stats['dim']} secs={emb_stats['seconds']}"
    )

    train_classes = sorted(set(train_labels))
    timings: dict[str, float] = {}
    probs: dict[str, dict[str, np.ndarray]] = {r: {} for r in ROUTES}
    models: dict[str, Any] = {}

    # ---- 路线 A ----
    t0 = time.perf_counter()
    pipe_a = build_route_a().fit(train_texts, train_labels)
    timings["A_char_tfidf_sgd_fit_s"] = round(time.perf_counter() - t0, 2)
    models["A_char_tfidf_sgd"] = pipe_a
    probs["A_char_tfidf_sgd"]["dev"] = pipe_a.predict_proba(eval_texts["dev"])
    probs["A_char_tfidf_sgd"]["val"] = pipe_a.predict_proba(eval_texts["val"])

    # ---- 路线 B ----
    t0 = time.perf_counter()
    lr_b = build_lr().fit(emb_train, train_labels)
    timings["B_embed_lr_fit_s"] = round(time.perf_counter() - t0, 2)
    model_b = EmbedTextClassifier(lr_b, train_classes)
    models["B_embed_lr"] = model_b
    probs["B_embed_lr"]["dev"] = lr_b.predict_proba(emb_eval_dev)
    probs["B_embed_lr"]["val"] = lr_b.predict_proba(emb_eval_val)

    # ---- 路线 C（char TFIDF ⊕ L2(嵌入) 拼接）----
    t0 = time.perf_counter()
    vec_c = build_char_tfidf().fit(train_texts)
    scaler_c = Normalizer(norm="l2").fit(emb_train)
    Xc_train = sp.hstack([vec_c.transform(train_texts), sp.csr_matrix(scaler_c.transform(emb_train))], format="csr")
    lr_c = build_lr().fit(Xc_train, train_labels)
    timings["C_fused_char_embed_fit_s"] = round(time.perf_counter() - t0, 2)
    model_c = FusedCharEmbedClassifier(vec_c, scaler_c, lr_c, train_classes)
    models["C_fused_char_embed"] = model_c
    for split, emb_ev in (("dev", emb_eval_dev), ("val", emb_eval_val)):
        Xc = sp.hstack([vec_c.transform(eval_texts[split]), sp.csr_matrix(scaler_c.transform(emb_ev))], format="csr")
        probs["C_fused_char_embed"][split] = lr_c.predict_proba(Xc)

    # ---- 评价（DEV/VAL，IMCR strong 参考）----
    metrics: dict[str, dict[str, dict[str, Any]]] = {}
    for route in ROUTES:
        classes = train_classes  # 三条路线输出类空间一致（weak 标签空间）
        metrics[route] = {
            split: evaluate_split(eval_labels[split], probs[route][split], classes, set(train_classes))
            for split in ("dev", "val")
        }

    decision = decide_winner(metrics)

    # ---- 落盘 ----
    runs_path = OUT_DIR / "PREDICTOR_UPGRADE_RUNS.csv"
    with open(runs_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["route", "split", "sample_id", "name", "reference_label", "prediction", "confidence", "correct"])
        for route in ROUTES:
            for split in ("dev", "val"):
                p = probs[route][split]
                for i, sid in enumerate(eval_ids[split]):
                    pred = train_classes[int(p[i].argmax())]
                    w.writerow([
                        route, split, sid, eval_texts[split][i], eval_labels[split][i],
                        pred, round(float(p[i].max()), 6), int(pred == eval_labels[split][i]),
                    ])

    metrics_path = OUT_DIR / "PREDICTOR_UPGRADE_METRICS.csv"
    with open(metrics_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["route", "split", "metric", "value"])
        for route in ROUTES:
            for split in ("dev", "val"):
                for k, v in metrics[route][split].items():
                    w.writerow([route, split, k, v])
        for r in ROUTES:
            w.writerow([r, "delta_vs_A", "macro_f1_dev", round(metrics[r]["dev"]["macro_f1"] - metrics["A_char_tfidf_sgd"]["dev"]["macro_f1"], 4)])
            w.writerow([r, "delta_vs_A", "macro_f1_val", round(metrics[r]["val"]["macro_f1"] - metrics["A_char_tfidf_sgd"]["val"]["macro_f1"], 4)])

    timings["total_s"] = round(time.perf_counter() - t_all, 2)
    summary = {
        "pipeline": "run_predictor_upgrade.py (M3 semantic predictor upgrade)",
        "seed": SEED,
        "versions": {
            "python": platform.python_version(),
            "sklearn": sklearn.__version__,
            "numpy": np.__version__,
        },
        "train_manifest": train_manifest,
        "eval_manifest": {
            "reference": "IMCR_REFERENCE_STRONG.csv (entity_type 行；仅评价)",
            "names_source": "run_selective_semantic.build_signal_frame() 只读复用",
            "splits": "V3_1/data/frozen_splits/SPLIT_MANIFEST.json (entity_type 前缀键)",
            "n_dev": len(eval_ids["dev"]),
            "n_val": len(eval_ids["val"]),
            "test_used": False,
        },
        "embed_stats": emb_stats,
        "timings": timings,
        "routes": {
            "A_char_tfidf_sgd": "TF-IDF(char 3-5, min_df=2, sublinear_tf) + SGDClassifier(log_loss, alpha=2e-6, max_iter=40, elasticnet, optimal, balanced) — 关键超参对齐生产 260",
            "B_embed_lr": "nomic-embed(768d, 本地 LM Studio, npy 缓存) + LogisticRegression(C=2, balanced)",
            "C_fused_char_embed": "char TF-IDF ⊕ L2 归一嵌入 拼接 + LogisticRegression(C=2, balanced)",
        },
        "metrics": metrics,
        "decision": decision,
    }
    (OUT_DIR / "PREDICTOR_UPGRADE_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "TRAIN_MANIFEST.json").write_text(
        json.dumps(train_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---- winner 落盘 ----
    if not args.no_save_model:
        winner = decision["winner_route"]
        sys.modules.setdefault(_CANONICAL, sys.modules[__name__])  # 脚本直跑时注册规范模块名
        joblib.dump(models[winner], OUT_DIR / "M3_improved_predictor.joblib")
        (OUT_DIR / "M3_improved_predictor.metadata.json").write_text(
            json.dumps(
                {
                    "artifact": "M3_improved_predictor.joblib",
                    "route": winner,
                    "class": type(models[winner]).__name__,
                    "classes": train_classes,
                    "trained_on": train_manifest["source"],
                    "n_train": train_manifest["n_train"],
                    "significant_upgrade": decision["significant_upgrade"],
                    "metrics": metrics[winner],
                    "load_hint": (
                        "sys.path 需含 code/experiment_pipelines（import run_predictor_upgrade）；"
                        "sklearn Pipeline 路线直接 predict_proba(texts)；B/C 工件 "
                        "predict_proba(texts) 需本地 LM Studio embeddings 在线（127.0.0.1:1234）"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    # ---- 控制台报告 ----
    print("\n[predictor_upgrade] metrics (IMCR strong reference, test untouched)")
    header = f"{'route':<22}{'split':<6}{'acc':>7}{'mF1':>7}{'bal':>7}{'ECE':>7}{'Brier':>8}{'ΔmF1_vs_A':>11}"
    print(header)
    for route in ROUTES:
        for split in ("dev", "val"):
            m = metrics[route][split]
            d = m["macro_f1"] - metrics["A_char_tfidf_sgd"][split]["macro_f1"]
            print(
                f"{route:<22}{split:<6}{m['accuracy']:>7.3f}{m['macro_f1']:>7.3f}"
                f"{m['balanced_accuracy']:>7.3f}{m['ece_10bins']:>7.3f}{m['brier_multiclass']:>8.3f}{d:>+11.3f}"
            )
    print(f"[predictor_upgrade] decision: {json.dumps(decision, ensure_ascii=False)}")
    print(f"[predictor_upgrade] timings: {json.dumps(timings, ensure_ascii=False)}")
    print(f"[predictor_upgrade] outputs -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
