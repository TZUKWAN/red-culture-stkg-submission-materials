# -*- coding: utf-8 -*-
"""run_risk_routing.py — Risk Estimator + 三路路由 + 质量预算 Pareto（指令 §五/六/七/八/九）。

评价对象：entity_type 382 规范实体的"生产预测是否错误"风险估计与选择性升级。

流程（全部只在 DEV/VAL 上进行，TEST 显式过滤并断言）：
  1. 特征工程：复用 run_selective_semantic.build_signal_frame() 的信号帧
     （B1 规则 / B2 分类器 / B7 margin / B3=gpt-5.6-luna 盲 LLM），构造
     clf_conf/clf_margin/entropy(margin 近似)/rule_conf/rule_clf_agreement/rule_hit/
     lexical_contradiction(stkg_v2_semantics.entity_model_contraindication)/
     TYPE_FAMILY_membership/pred_class_onehot/source_multiplicity/validated 特征；
  2. Risk Estimator：r_hat = P(clf_pred wrong | features)。标签只来自
     IMCR_REFERENCE_STRONG 独立参考（pred != reference = wrong），只允许 DEV 拟合；
     候选 LogisticRegression / CalibratedLR(sigmoid) / DecisionTree(max_depth=4)，
     用 VAL AUPRC 选型、偏好最简单；**禁止用 weak auto_accepted 标签做 risk 真值**；
  3. 三路路由：r_hat<=tau_accept → AUTO_ACCEPT；tau_accept<r<=tau_escalate →
     ESCALATE（gpt-oss-20b 本地真实调用替换预测）；r>tau_escalate → ABSTAIN。
     每个预算点的 tau_* 只在 VAL 上学习；
  4. 质量预算 Pareto：b ∈ {0,5,10,20,30,40,50,75,100}%。预算 b 把 r_hat 最高的
     round-half-up(b*n) 个样本送升级（其余按 tau_accept accept/abstain）。
     b=100% 用 B3 既有全量行（IMCR_BLIND_LLM_RUNS.csv 的 gpt 记录）做真实
     every-item 对照；其余预算点的升级调用对 DEV+VAL 样本真实执行
     （总数 ~241 次 < 400），结果以 JSONL 落盘并可断点续跑；
  5. 输出：RISK_MODEL_CARD.json / ROUTING_RUNS_{dev,val}.csv /
     QUALITY_BUDGET_CURVE.csv / SUMMARY.json / ESCALATION_CALLS.jsonl。

泄漏防护：
  - TEST split 样本不进入训练/选阈值/打分/升级调用（assert_no_test_samples）；
  - escalation prompt 只给 name/aliases/context/source_excerpt/candidate_types/
    type_definitions（与 V3_1 run_judges_v31.py identity 模板同风格），禁止任何
    生产标签/参考信息/正确性信号；
  - risk 标签只来自独立参考，不使用任何 weak auto_accepted 标签。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np  # noqa: E402

V3_1 = Path(__file__).resolve().parents[2]
V3 = V3_1.parent / "final_submission_v3"
for _p in (
    str(V3 / "code"),
    str(V3 / "code" / "independent_eval"),
    str(V3 / "code" / "experiment_pipelines"),
    str(V3 / "data" / "external_inputs"),
    str(Path(__file__).resolve().parent.parent / "independent_eval"),
    str(Path(__file__).resolve().parent),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import average_precision_score, roc_auc_score  # noqa: E402
from sklearn.model_selection import StratifiedKFold  # noqa: E402
from sklearn.pipeline import make_pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402
from sklearn.tree import DecisionTreeClassifier  # noqa: E402

# 复用 P0-2 链 A 的信号帧 / 参考 / 切分（import 使用，不修改 run_selective_semantic.py）
from run_selective_semantic import (  # noqa: E402
    build_signal_frame,
    contra,
    load_reference,
    load_split,
    sem,
)
from imcr_task_defs import ENTITY_TYPE_DEFINITIONS, ENTITY_TYPE_LABELS  # noqa: E402
from lmstudio_provider import DEFAULT_MODEL, chat_json  # noqa: E402
from selective_stats import rows_to_points  # noqa: E402

V3_RUNS = V3 / "experiments" / "09_independent_baselines" / "IMCR_BASELINE_RUNS.csv"
V3_REF_STRONG = V3 / "experiments" / "08_independent_reference" / "IMCR_REFERENCE_STRONG.csv"
V3_BLIND = V3 / "experiments" / "09_independent_baselines" / "IMCR_BLIND_LLM_RUNS.csv"
SAMPLE = V3 / "experiments" / "08_independent_reference" / "ENTITY_TYPE_SAMPLE.csv"
SIDECAR = V3 / "experiments" / "08_independent_reference" / "ENTITY_TYPE_SAMPLE.sampling_metadata.csv"
SPLIT_MANIFEST = V3_1 / "data" / "frozen_splits" / "SPLIT_MANIFEST.json"
OUT_DIR = V3_1 / "experiments" / "02_selective_semantic" / "risk_routing"
ESCALATION_LOG = OUT_DIR / "ESCALATION_CALLS.jsonl"

SEED = 20260908
BUDGETS = [0.0, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.75, 1.0]
COVERAGE_FLOOR = 0.30
LAMBDA_RISK = 1.0
LAMBDA_VIOLATION = 2.0
AUPRC_TOLERANCE = 0.01  # 选型偏好最简单：AUPRC 落后最佳 <= 容差即选最简单
KNEE_TOL = 1e-12

# 升级 system prompt：与 run_judges_v31.py 的 identity 模板同风格。
# 只允许模型看到 name/aliases/context/source_excerpt/candidate_types/type_definitions；
# 禁止出现任何生产标签、参考标签或正确性信息。
ESCALATION_SYSTEM_PROMPT = (
    "你是独立的历史知识图谱实体类型评审。给定一个实体的名称、别名、它在语料中参与的"
    "关系上下文与文献节选，以及候选类型集合 candidate_types 和各类型定义 type_definitions。"
    "你的唯一任务：依据给出的信息判断该实体最合理的类型。\n"
    "约束：只允许从 candidate_types 列出的类型中选择一个；证据不足或不属于任何候选类型时"
    "选择 OTHER；不得臆测输入之外的信息；输入中不含任何系统标签或参考答案，也不要猜测其存在。\n"
    "输出且仅输出一个 JSON 对象：{\"task_id\":..., \"decision\":..., \"confidence\":0-1, "
    "\"evidence\":[引用证据关键句], \"reason_code\":简短代码, \"explanation\":一句话理由, "
    "\"insufficient_evidence\":bool}"
)

VALID_LABELS = set(ENTITY_TYPE_LABELS)


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def assert_no_test_samples(sample_ids: list[str], split_map: dict[str, str], where: str) -> None:
    """硬约束：任何训练/选阈值/打分/升级路径都不得包含 TEST 样本。"""
    leaked = [s for s in sample_ids if split_map.get(f"entity_type:{s}") == "test"]
    if leaked:
        raise AssertionError(f"[TEST-leakage] {where}: test samples present: {leaked[:5]} ({len(leaked)})")


def budget_to_tag(b: float) -> str:
    return f"b{round(b * 100):03d}"


def exact_budget_count(n: int, b: float) -> int:
    """预算 b 的精确升级条数：round-half-up(b*n)，0<=k<=n。"""
    k = int(math.floor(n * b + 0.5))
    return max(0, min(n, k))


# ---------------------------------------------------------------------------
# 特征工程
# ---------------------------------------------------------------------------

# 连续/二值特征（pred_class_onehot 之外的清单，进入模型卡）
BASE_FEATURE_NAMES = [
    "clf_conf",
    "clf_margin",
    "entropy_margin_approx",
    "rule_conf",
    "rule_clf_agreement",
    "rule_hit",
    "lexical_contradiction",
    "type_family_member",
    "validated",
    "source_multiplicity",
]

ONEHOT_CLASSES = sorted(set(sem.TYPE_FAMILY.keys())) + ["OTHER"]
FEATURE_NAMES = BASE_FEATURE_NAMES + [f"pred_{c}" for c in ONEHOT_CLASSES]

FEATURE_DESCRIPTIONS = {
    "clf_conf": "B2 冻结分类器置信（缺失→0，配 no_clf_pred 政策处理）",
    "clf_margin": "B7 分类器 top1-top2 概率间隔",
    "entropy_margin_approx": "由 margin 近似的归一化熵：H2(0.5+clip(margin,0,1)/2)（margin∈[0,1]，单调反转）",
    "rule_conf": "B1 规则置信（缺失→0）",
    "rule_clf_agreement": "rule_pred == clf_pred（两者都存在）",
    "rule_hit": "规则给出候选（rule_pred 非空）",
    "lexical_contradiction": "entity_model_contraindication(name, primary_source_type, clf_pred) 非空",
    "type_family_member": "clf_pred ∈ TYPE_FAMILY",
    "validated": "ENTITY_TYPE_SAMPLE.sampling_metadata.type_validation_status == validated",
    "source_multiplicity": "integrated_member_count（成员数）",
    "pred_*": "clf_pred 类别 onehot（类别域 = TYPE_FAMILY 键 + OTHER）",
}


def binary_entropy(p: float) -> float:
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -(p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p))


def feature_vector(signals: dict[str, Any]) -> dict[str, float]:
    """从信号字典构造特征向量（纯函数，测试可直接用合成信号）。

    必需键：clf_pred/clf_conf/clf_margin/rule_pred/rule_conf/validated/
    source_multiplicity/lexical_contradiction（已由调用方按 contra 重算）。
    """
    clf_pred = signals.get("clf_pred") or ""
    clf_conf = float(signals.get("clf_conf") or 0.0)
    margin = float(signals.get("clf_margin") or 0.0)
    rule_pred = signals.get("rule_pred") or ""
    rule_conf = float(signals.get("rule_conf") or 0.0)
    vec: dict[str, float] = {
        "clf_conf": clf_conf,
        "clf_margin": margin,
        "entropy_margin_approx": binary_entropy(0.5 + min(max(margin, 0.0), 1.0) / 2.0),
        "rule_conf": rule_conf,
        "rule_clf_agreement": float(bool(rule_pred) and bool(clf_pred) and rule_pred == clf_pred),
        "rule_hit": float(bool(rule_pred)),
        "lexical_contradiction": float(bool(signals.get("lexical_contradiction"))),
        "type_family_member": float(clf_pred in sem.TYPE_FAMILY),
        "validated": float(bool(signals.get("validated"))),
        "source_multiplicity": float(signals.get("source_multiplicity") or 0),
    }
    for c in ONEHOT_CLASSES:
        vec[f"pred_{c}"] = 1.0 if clf_pred == c else 0.0
    if clf_pred == "":
        vec["pred_OTHER"] = 1.0
    return vec


def build_feature_rows(frame: dict[str, Any]) -> dict[str, dict[str, float]]:
    """全样本特征（按需重算 contra，缓存在 frame 的 contra_cache 中）。"""
    out: dict[str, dict[str, float]] = {}
    for sid, f in frame.items():
        contra_flag = False
        if f["clf_pred"]:
            try:
                contra_flag = contra(frame, sid, f["clf_pred"])
            except Exception:
                contra_flag = False
        out[sid] = feature_vector({
            "clf_pred": f["clf_pred"],
            "clf_conf": f["clf_conf"],
            "clf_margin": f["clf_margin"],
            "rule_pred": f["rule_pred"],
            "rule_conf": f["rule_conf"],
            "validated": f["validated"],
            "source_multiplicity": f["meta"].get("integrated_member_count"),
            "lexical_contradiction": contra_flag,
        })
    return out


def to_matrix(rows: dict[str, dict[str, float]]) -> tuple[list[str], list[list[float]]]:
    ids = sorted(rows)
    return ids, [[rows[i][name] for name in FEATURE_NAMES] for i in ids]


# ---------------------------------------------------------------------------
# Risk Estimator（标签只来自独立参考；只允许 DEV 拟合）
# ---------------------------------------------------------------------------

def _logit(p: Any, eps: float = 1e-6) -> Any:
    p = np.clip(np.asarray(p, dtype=float), eps, 1.0 - eps)
    return np.log(p / (1.0 - p))


class EnsemblePlattLR:
    """CalibratedLR(sigmoid) 的显式实现：LR 集成 + 每 folds 一个 Platt sigmoid。

    与 CalibratedClassifierCV(ensemble=True, method='sigmoid') 语义一致：
    5 折各拟合 LR，折叠外概率上拟合两参数 Platt sigmoid；预测时对 5 个校准后
    概率取均值。

    工程注记（为何不用 sklearn.calibration.CalibratedClassifierCV）：在
    sklearn 1.8.0、本数据配置（29 维特征/166 训练行/二值 wrong 标签）下，
    CalibratedClassifierCV 的 predict_proba 路径经 _get_response_values 优先取
    decision_function，产生与底层 LR 概率**完全反序**的输出（spearman=-1.000，
    训练集低风险区正确率 0.102 < 随机），干净合成数据上则行为正常——库内部
    响应方法选择与本配置不相容。为保证候选模型行为可审计，按 Platt (1999)
    原义显式实现；正确性由测试 test_risk_routing.py 固化（与 LR 秩相关为正）。
    """

    def __init__(self, seed: int = SEED, cv: int = 5):
        self.seed = seed
        self.cv = cv
        self.models_: list[Any] = []
        self.ab_: list[tuple[float, float]] = []

    def fit(self, X: Any, y: Any) -> "EnsemblePlattLR":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y)
        skf = StratifiedKFold(n_splits=self.cv, shuffle=True, random_state=self.seed)
        for tr, te in skf.split(X, y):
            m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=5000, C=1.0, random_state=self.seed))
            m.fit(X[tr], y[tr])
            # Platt sigmoid 只在折叠外（held-out）预测上拟合，避免折叠内过拟合
            p = m.predict_proba(X[te])[:, 1]
            platt = LogisticRegression(C=1e6, max_iter=1000, random_state=self.seed)
            platt.fit(_logit(p).reshape(-1, 1), y[te])
            self.models_.append(m)
            self.ab_.append((float(platt.coef_[0][0]), float(platt.intercept_[0])))
        return self

    def predict_proba(self, X: Any) -> Any:
        X = np.asarray(X, dtype=float)
        outs = []
        for m, (a, b) in zip(self.models_, self.ab_):
            p = m.predict_proba(X)[:, 1]
            outs.append(1.0 / (1.0 + np.exp(-(a * _logit(p) + b))))
        avg = np.mean(outs, axis=0)
        return np.column_stack([1.0 - avg, avg])


def make_risk_candidates(seed: int = SEED) -> dict[str, Any]:
    """三个候选模型：LogisticRegression / CalibratedLR(sigmoid) / DecisionTree(depth=4)。

    简单性偏好序（选型规则按此序取第一个 AUPRC >= best - AUPRC_TOLERANCE 的模型）：
    LogisticRegression（最简单） > DecisionTree(max_depth=4) > CalibratedLR(sigmoid)。
    """
    lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=5000, C=1.0, random_state=seed))
    dt = DecisionTreeClassifier(max_depth=4, random_state=seed)
    cal = EnsemblePlattLR(seed=seed, cv=5)
    return {"LogisticRegression": lr, "DecisionTree_max_depth4": dt, "CalibratedLR_sigmoid": cal}


SIMPLICITY_ORDER = ["LogisticRegression", "DecisionTree_max_depth4", "CalibratedLR_sigmoid"]


def train_risk_models(
    train_rows: dict[str, dict[str, float]],
    y: dict[str, int],
    seed: int = SEED,
) -> dict[str, Any]:
    """在 DEV 上拟合全部候选（特征矩阵行序固定为 sorted ids，保证可复现）。"""
    ids, X = to_matrix(train_rows)
    target = [int(y[i]) for i in ids]
    models = {}
    for name, est in make_risk_candidates(seed).items():
        est.fit(X, target)
        models[name] = est
    return {"models": models, "train_ids": ids}


def predict_risk(fitted: dict[str, Any], model_name: str, rows: dict[str, dict[str, float]]) -> dict[str, float]:
    ids, X = to_matrix(rows)
    proba = fitted["models"][model_name].predict_proba(X)[:, 1]
    return dict(zip(ids, (float(p) for p in proba)))


def select_risk_model(
    fitted: dict[str, Any],
    train_rows: dict[str, dict[str, float]],
    dev_y: dict[str, int],
    val_rows: dict[str, dict[str, float]],
    val_y: dict[str, int],
) -> dict[str, Any]:
    """VAL AUPRC 选型，偏好最简单（SIMPLICITY_ORDER 中第一个达到 best-tol 的候选）。"""
    report: dict[str, Any] = {}
    for name in SIMPLICITY_ORDER:
        p_dev = predict_risk(fitted, name, train_rows)
        p_val = predict_risk(fitted, name, val_rows)
        dev_ids = sorted(p_dev)
        val_ids = sorted(p_val)
        dev_ap = average_precision_score([dev_y[i] for i in dev_ids], [p_dev[i] for i in dev_ids])
        val_ap = average_precision_score([val_y[i] for i in val_ids], [p_val[i] for i in val_ids])
        val_auc = roc_auc_score([val_y[i] for i in val_ids], [p_val[i] for i in val_ids]) if len(set(val_y[i] for i in val_ids)) > 1 else None
        report[name] = {
            "dev_auprc": float(dev_ap),
            "val_auprc": float(val_ap),
            "val_auroc": (float(val_auc) if val_auc is not None else None),
            "n_train": len(fitted["train_ids"]),
            "n_val_scored": len(val_ids),
        }
    best = max(report[name]["val_auprc"] for name in SIMPLICITY_ORDER)
    chosen = next(
        name for name in SIMPLICITY_ORDER
        if report[name]["val_auprc"] >= best - AUPRC_TOLERANCE
    )
    return {"chosen": chosen, "selection": report, "rule": (
        f"VAL AUPRC 选型；SIMPLICITY_ORDER={SIMPLICITY_ORDER} 中取第一个 "
        f"val_auprc >= best - {AUPRC_TOLERANCE} 的候选（偏好最简单）"
    )}


# ---------------------------------------------------------------------------
# 三路路由与预算分配（纯函数，供测试）
# ---------------------------------------------------------------------------

def route_three_way(r_hat: float, tau_accept: float, tau_escalate: float, has_prediction: bool = True) -> str:
    """规范三路语义：r<=tau_accept → AUTO_ACCEPT；tau_accept<r<=tau_escalate → ESCALATE；
    r>tau_escalate → ABSTAIN。无基础预测（clf_pred 缺失）的样本永不 AUTO_ACCEPT。"""
    if has_prediction and r_hat <= tau_accept:
        return "AUTO_ACCEPT"
    if r_hat <= tau_escalate:
        return "ESCALATE"
    return "ABSTAIN"


def assign_budget_topk(scored: list[tuple[str, float]], n: int, b: float) -> set[str]:
    """预算 b：把 r_hat 最高的 k=exact_budget_count(n,b) 个样本送升级。

    确定性并列打破：(-r_hat, sample_id) 字典序。返回升级样本 id 集合。
    """
    k = exact_budget_count(n, b)
    if k == 0:
        return set()
    ranked = sorted(scored, key=lambda t: (-t[1], t[0]))
    return {sid for sid, _ in ranked[:k]}


def learn_tau_accept(
    rows: list[dict[str, Any]],
    coverage_floor: float = COVERAGE_FLOOR,
    lam_risk: float = LAMBDA_RISK,
    lam_viol: float = LAMBDA_VIOLATION,
) -> tuple[float, dict[str, Any]]:
    """在 VAL 上为给定预算点学习 tau_accept（接受低风险非升级样本）。

    行字段：r_hat/correct(0|1)/violation(0|1)。接受规则 r_hat<=tau；
    网格 = 各行 r_hat 值 ∪ {0.0}（升序）；目标 = 最大化
    utility=(safe - lam_risk*errors - lam_viol*violations)/n（与
    run_selective_semantic.learn_threshold 的效用同构），约束 coverage>=floor；
    无可行解时回退 coverage 最大的 tau。平局取最小 tau（更保守）。
    """
    n = len(rows)
    if n == 0:
        return 0.0, {"note": "no remaining labeled rows; tau_accept=0 (accept nothing)"}
    taus = sorted({0.0} | {float(r["r_hat"]) for r in rows})
    best_tau, best_u = None, -math.inf
    floor_tau, floor_cov = 0.0, -1.0
    for tau in taus:
        accepted = [r for r in rows if r["r_hat"] <= tau + KNEE_TOL]
        cov = len(accepted) / n
        errors = sum(1 for r in accepted if r["correct"] == 0)
        violations = sum(1 for r in accepted if r["violation"] == 1)
        safe = len(accepted) - errors - violations
        u = (safe - lam_risk * errors - lam_viol * violations) / n
        if cov >= coverage_floor and u > best_u + KNEE_TOL:
            best_u, best_tau = u, tau
        if cov > floor_cov + KNEE_TOL:
            floor_cov, floor_tau = cov, tau
    if best_tau is None:
        return float(floor_tau), {"note": f"no tau meets coverage floor {coverage_floor}; fallback max coverage tau"}
    return float(best_tau), {"utility": float(best_u), "coverage_floor": coverage_floor}


# ---------------------------------------------------------------------------
# Pareto knee（由数据决定，不预设）
# ---------------------------------------------------------------------------

def pareto_knee(points: list[dict[str, float]]) -> dict[str, Any]:
    """质量-预算曲线的 knee：risk(b) 相对首末点连线的最大垂直落差处。

    points 按 budget 升序，字段 {budget, selective_risk}。垂直落差 =
    chord_y(b) - risk(b)（chord 连接第一个与最后一个点）。平局取最小预算。
    """
    if len(points) < 2:
        return {"budget": points[0]["budget"] if points else None, "gap": None}
    x0, y0 = points[0]["budget"], points[0]["selective_risk"]
    x1, y1 = points[-1]["budget"], points[-1]["selective_risk"]
    best = {"budget": None, "gap": -math.inf}
    for p in points:
        x, y = p["budget"], p["selective_risk"]
        if x1 == x0:
            chord = y0
        else:
            chord = y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        gap = chord - y
        if gap > best["gap"] + KNEE_TOL:
            best = {"budget": x, "gap": gap}
    best["chord"] = {"from": {"budget": x0, "selective_risk": y0}, "to": {"budget": x1, "selective_risk": y1}}
    best["rule"] = "knee = argmax_b [chord(0%→100%) - selective_risk(b)]（数据决定，平局取最小预算）"
    return best


# ---------------------------------------------------------------------------
# 升级调用（本地 LM Studio gpt-oss-20b；JSONL 断点续跑）
# ---------------------------------------------------------------------------

def parse_aliases(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def escalation_payload(frame: dict[str, Any], sid: str) -> dict[str, Any]:
    """盲化升级 payload：只含 name/aliases/context/source_excerpt/candidate_types/
    type_definitions。禁止任何生产标签 / 参考标签 / 正确性信息。"""
    m = frame[sid]["meta"]
    return {
        "task_id": sid,
        "entity_name": m.get("canonical_name") or frame[sid]["name"],
        "aliases": parse_aliases(m.get("aliases_json")),
        "context_assertions": m.get("context_assertions") or "",
        "source_excerpt": m.get("source_excerpt") or "",
        "candidate_types": list(ENTITY_TYPE_LABELS),
        "type_definitions": dict(ENTITY_TYPE_DEFINITIONS),
    }


def load_escalation_cache(path: Path) -> dict[str, dict[str, Any]]:
    done: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        # status=OK 一律视为已完成（decision 无效时下游回退基础预测；
        # 仅 ERROR 会在续跑时重试），避免对同类样本反复浪费调用。
        if rec.get("status") == "OK":
            done[str(rec.get("sample_id"))] = rec
    return done


class EscalationRunner:
    def __init__(self, frame: dict[str, Any], split_map: dict[str, str], log_path: Path, workers: int = 2):
        self.frame = frame
        self.split_map = split_map
        self.log_path = log_path
        self.workers = max(1, workers)
        self.lock = threading.Lock()
        self.cache = load_escalation_cache(log_path)
        self.calls_made = 0
        self.records: dict[str, dict[str, Any]] = dict(self.cache)
        self.prompt_sha = sha256_text(ESCALATION_SYSTEM_PROMPT)

    def _append(self, rec: dict[str, Any]) -> None:
        with self.lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")

    def _call(self, sid: str) -> dict[str, Any]:
        payload = escalation_payload(self.frame, sid)
        payload_sha = sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        rec: dict[str, Any] = {
            "sample_id": sid,
            "split": self.split_map.get(f"entity_type:{sid}", "unknown"),
            "model": DEFAULT_MODEL,
            "prompt_version": "risk_routing.escalation.v1",
            "prompt_sha256": self.prompt_sha,
            "payload_sha256": payload_sha,
            "started_utc": now_iso(),
        }
        if rec["split"] == "test":
            rec.update({"status": "BLOCKED_TEST_SPLIT", "decision": None, "decision_valid": False})
            self._append(rec)
            raise AssertionError(f"escalation attempted on TEST sample {sid}")
        t0 = time.time()
        try:
            out = chat_json(
                [
                    {"role": "system", "content": ESCALATION_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
                ],
                model=DEFAULT_MODEL,
                temperature=0.0,
                max_tokens=900,
                timeout=300.0,
                retries=2,
            )
            rec["latency_s"] = round(time.time() - t0, 3)
            decision = str(out.get("decision") or "").strip()
            conf = out.get("confidence")
            rec.update({
                "status": "OK",
                "decision": decision,
                "decision_valid": decision in VALID_LABELS,
                "confidence": float(conf) if isinstance(conf, (int, float)) else None,
                "reason_code": out.get("reason_code"),
                "insufficient_evidence": bool(out.get("insufficient_evidence")),
            })
        except Exception as exc:
            rec.update({"status": "ERROR", "error": str(exc)[:300], "decision_valid": False,
                        "latency_s": round(time.time() - t0, 3)})
        self._append(rec)
        return rec

    def ensure(self, sample_ids: list[str]) -> dict[str, dict[str, Any]]:
        assert_no_test_samples(sample_ids, self.split_map, "escalation.ensure")
        pending = [s for s in sample_ids if s not in self.cache]
        fresh: dict[str, dict[str, Any]] = {}
        if pending:
            if self.workers <= 1:
                for sid in pending:
                    rec = self._call(sid)
                    fresh[sid] = rec
                    print(f"  [escalation] {sid} status={rec['status']} decision={rec.get('decision')}", flush=True)
            else:
                with ThreadPoolExecutor(max_workers=self.workers) as pool:
                    futs = {pool.submit(self._call, sid): sid for sid in pending}
                    for fut in as_completed(futs):
                        sid = futs[fut]
                        rec = fut.result()
                        fresh[sid] = rec
                        print(f"  [escalation] {sid} status={rec['status']} decision={rec.get('decision')}", flush=True)
        self.calls_made += len(fresh)
        for sid, rec in fresh.items():
            if rec.get("status") == "OK":
                self.records[sid] = rec
        for sid, rec in self.cache.items():
            self.records.setdefault(sid, rec)
        return self.records


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------

def finalize_prediction(
    base_pred: str | None,
    esc_rec: dict[str, Any] | None,
    escalation_source: str,
) -> tuple[str, str, int]:
    """返回 (final_prediction, final_source, escalation_valid)。升级无效时回退基础预测。"""
    if esc_rec is None:
        return (base_pred or ""), ("base_prediction" if base_pred else "none"), 0
    decision = esc_rec.get("decision") or ""
    if esc_rec.get("status") == "OK" and esc_rec.get("decision_valid") and decision in VALID_LABELS:
        return decision, escalation_source, 1
    return (base_pred or ""), ("base_prediction_fallback" if base_pred else "none"), 0


def budget_metrics(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """逐预算指标。rows 字段：
    sample_id/in_reference/route/final_prediction/final_correct/violation/r_hat。
    质量指标只在有独立参考的样本（in_reference）上计算；路由/调用量统计在全样本上。
    """
    n_all = len(rows)
    labeled = [r for r in rows if r["in_reference"]]
    n_eval = len(labeled)
    published = [r for r in labeled if r["route"] in ("AUTO_ACCEPT", "ESCALATE")]
    correct_pub = sum(r["final_correct"] for r in published)
    escalated_all = [r for r in rows if r["route"] == "ESCALATE"]
    accepts = [r for r in rows if r["route"] == "AUTO_ACCEPT"]
    cov = len(published) / n_eval if n_eval else None
    sel_acc = correct_pub / len(published) if published else None
    sel_risk = (1.0 - sel_acc) if sel_acc is not None else None
    gen_risk = (len(published) - correct_pub) / n_eval if n_eval else None
    pts_rows = [
        {
            "sample_id": r["sample_id"],
            "accepted": int(r["route"] in ("AUTO_ACCEPT", "ESCALATE")),
            "correct": r["final_correct"],
            "score": (-r["r_hat"]) if r["route"] in ("AUTO_ACCEPT", "ESCALATE") else None,
        }
        for r in labeled
    ]
    pts = rows_to_points(pts_rows)
    aurc = None
    if len(pts) >= 2:
        xs = [p["coverage"] for p in pts]
        ys = [p["selective_risk"] or 0.0 for p in pts]
        aurc = sum((xs[i + 1] - xs[i]) * (ys[i + 1] + ys[i]) / 2 for i in range(len(xs) - 1))
    return {
        "n_all": n_all,
        "n_eval_labeled": n_eval,
        "n_auto_accept": len(accepts),
        "n_escalate": len(escalated_all),
        "n_abstain": sum(1 for r in rows if r["route"] == "ABSTAIN"),
        "llm_call_rate": len(escalated_all) / n_all if n_all else 0.0,
        "coverage": cov,
        "semantic_agreement": sel_acc,
        "selective_accuracy": sel_acc,
        "selective_risk": sel_risk,
        "generalized_risk": gen_risk,
        "aurc": aurc,
        "n_correct_published": correct_pub,
        "eval_wrong_prevalence": (sum(1 for r in labeled if r.get("base_correct") == 0) / n_eval) if n_eval else None,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def load_b3_predictions() -> dict[str, dict[str, Any]]:
    """B3 既有全量盲 LLM 行（gpt 记录）——仅用于 b=100% every-item 对照。"""
    out: dict[str, dict[str, Any]] = {}
    for r in csv.DictReader(open(V3_BLIND, encoding="utf-8-sig")):
        if (
            r.get("task_type") == "entity_type"
            and r.get("method_id") == "B3_blind_llm"
            and r.get("availability_status") == "available"
            and r.get("prediction")
        ):
            out.setdefault(r["sample_id"], {
                "prediction": r["prediction"],
                "confidence": float(r["confidence"]) if r.get("confidence") else None,
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2, help="升级并发数（本地 LM Studio 建议 1-2）")
    ap.add_argument("--limit-escalation", type=int, default=None, help="最多真实调用条数（冒烟用，缓存优先）")
    ap.add_argument("--skip-escalation", action="store_true", help="只用缓存，不发新调用")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    # ---- 数据与切分 ----
    frame = build_signal_frame()
    reference = load_reference("strong")
    split_map = load_split()
    all_ids = sorted(frame)
    test_ids = [s for s in all_ids if split_map.get(f"entity_type:{s}") == "test"]
    work_ids = [s for s in all_ids if split_map.get(f"entity_type:{s}") in ("dev", "val")]
    dev_ids = [s for s in work_ids if split_map[f"entity_type:{s}"] == "dev"]
    val_ids = [s for s in work_ids if split_map[f"entity_type:{s}"] == "val"]
    assert_no_test_samples(work_ids, split_map, "main:train/score/escalate")
    print(f"[risk_routing] frame={len(frame)} dev={len(dev_ids)} val={len(val_ids)} test(excluded)={len(test_ids)}")

    # ---- 特征 ----
    feat_rows = build_feature_rows(frame)

    # ---- risk 标签（只来自独立参考；不用 weak auto_accepted 标签） ----
    train_ids = [s for s in dev_ids if reference.get(s) and frame[s]["clf_pred"]]
    dev_y = {s: int(frame[s]["clf_pred"] != reference[s]) for s in train_ids}
    val_score_ids = [s for s in val_ids if reference.get(s) and frame[s]["clf_pred"]]
    val_y = {s: int(frame[s]["clf_pred"] != reference[s]) for s in val_score_ids}
    print(f"[risk_routing] train(dev, labeled+clf)={len(train_ids)} wrong_prev={sum(dev_y.values())/len(dev_y):.3f}; "
          f"val scored={len(val_score_ids)} wrong_prev={sum(val_y.values())/len(val_y):.3f}")

    # ---- 拟合 + VAL AUPRC 选型 ----
    fitted = train_risk_models({s: feat_rows[s] for s in train_ids}, dev_y)
    selection = select_risk_model(fitted, {s: feat_rows[s] for s in train_ids}, dev_y,
                                  {s: feat_rows[s] for s in val_score_ids}, val_y)
    chosen = selection["chosen"]
    print(f"[risk_routing] model selection: chosen={chosen}; " +
          "; ".join(f"{k}: val_auprc={v['val_auprc']:.3f}" for k, v in selection["selection"].items()))

    # ---- 全 dev/val 打分（无 clf_pred 的样本按政策 r_hat=1.0，永不 AUTO_ACCEPT） ----
    r_hat: dict[str, float] = {}
    scored_pool = {s: feat_rows[s] for s in work_ids if frame[s]["clf_pred"]}
    r_hat.update(predict_risk(fitted, chosen, scored_pool))
    for s in work_ids:
        if s not in r_hat:
            r_hat[s] = 1.0
    val_r = [r_hat[s] for s in val_ids]
    dev_r = [r_hat[s] for s in dev_ids]
    print(f"[risk_routing] r_hat val min/med/max = {min(val_r):.3f}/{sorted(val_r)[len(val_r)//2]:.3f}/{max(val_r):.3f}; "
          f"dev max={max(dev_r):.3f}")

    # ---- 升级集合（各预算点并集，只在 dev/val 上） ----
    scored = [(s, r_hat[s]) for s in work_ids]
    esc_union: set[str] = set()
    per_split_k: dict[str, dict[float, int]] = {"dev": {}, "val": {}}
    split_ids = {"dev": dev_ids, "val": val_ids}
    for sp, ids in split_ids.items():
        sub = [(s, r_hat[s]) for s in ids]
        for b in BUDGETS:
            k = exact_budget_count(len(ids), b)
            per_split_k[sp][b] = k
            if 0.0 < b < 1.0:
                esc_union |= assign_budget_topk(sub, len(ids), b)
    fresh_ids = sorted(esc_union)
    print(f"[risk_routing] escalation union(dev+val, 5%~75%)={len(fresh_ids)} calls; cached={len(load_escalation_cache(ESCALATION_LOG))}")

    # ---- 真实升级调用（gpt-oss-20b；断点续跑；TEST 硬禁止） ----
    if args.skip_escalation:
        runner_calls = 0
        esc_records = dict(load_escalation_cache(ESCALATION_LOG))
    else:
        if args.limit_escalation is not None:
            todo = [s for s in fresh_ids if s not in load_escalation_cache(ESCALATION_LOG)][: args.limit_escalation]
            runner = EscalationRunner(frame, split_map, ESCALATION_LOG, workers=args.workers)
            runner.ensure(todo)
            runner_calls, esc_records = runner.calls_made, runner.records
        else:
            runner = EscalationRunner(frame, split_map, ESCALATION_LOG, workers=args.workers)
            runner.ensure(fresh_ids)
            runner_calls, esc_records = runner.calls_made, runner.records
    ok_calls = [r for r in esc_records.values() if r.get("status") == "OK"]
    lat = [r["latency_s"] for r in ok_calls if isinstance(r.get("latency_s"), (int, float))]
    print(f"[risk_routing] escalation: fresh_calls={runner_calls} ok_total={len(ok_calls)} "
          f"valid={sum(1 for r in ok_calls if r.get('decision_valid'))} "
          f"avg_latency={sum(lat)/len(lat):.2f}s" if lat else "[risk_routing] escalation: no OK calls")

    b3 = load_b3_predictions()

    # ---- 每个预算点：VAL 学 tau_accept / DEV+VAL 路由 / 指标 ----
    # 预算约束下的路由语义（与指令步骤4逐字一致）：
    #   ESCALATE  = 该 split 内 r_hat 最高的前 k(b)=round-half-up(b*n) 个样本（top-k，
    #               并列按 (-r_hat, sample_id) 打破）；tau_escalate := 升级集内的最小 r_hat，
    #               即升级带的下边界；
    #   AUTO_ACCEPT = 非升级样本中 r_hat <= tau_accept(b)（tau_accept 只在 VAL 上按
    #               效用+coverage floor 学习）；
    #   ABSTAIN  = 其余（风险偏高但预算不足以升级的样本）。
    # route_three_way() 保留指令步骤3的规范边界语义供单元测试与参照。
    curve_rows: list[dict[str, Any]] = []
    routes_at: dict[str, dict[str, dict[float, str]]] = {"dev": {s: {} for s in dev_ids},
                                                         "val": {s: {} for s in val_ids}}
    finals_at: dict[str, dict[str, dict[float, tuple[str, str, int, int]]]] = {
        "dev": {s: {} for s in dev_ids}, "val": {s: {} for s in val_ids}}
    tau_accept_at: dict[float, dict[str, float]] = {}
    tau_escalate_at: dict[float, dict[str, float]] = {}
    for b in BUDGETS:
        llm_source = ("none" if b == 0.0 else ("B3_existing_blind_llm" if b == 1.0 else "gpt-oss-20b_fresh"))
        # tau_accept 只在 VAL 上学习（指令：VAL 用于选模型/选阈值），再同时应用于 DEV/VAL
        val_esc_set = assign_budget_topk([(s, r_hat[s]) for s in val_ids], len(val_ids), b)
        tau_learn_rows = [
            {"r_hat": r_hat[s],
             "correct": int(frame[s]["clf_pred"] == reference[s]),
             "violation": int(feat_rows[s]["lexical_contradiction"])}
            for s in val_ids
            if s not in val_esc_set and reference.get(s) and frame[s]["clf_pred"]
        ]
        tau_accept, tau_note = learn_tau_accept(tau_learn_rows)
        for sp, ids in split_ids.items():
            esc_set = assign_budget_topk([(s, r_hat[s]) for s in ids], len(ids), b)
            remaining = [s for s in ids if s not in esc_set]
            tau_escalate = min((r_hat[s] for s in esc_set), default=math.inf)
            tau_accept_at.setdefault(b, {})[sp] = tau_accept
            tau_escalate_at.setdefault(b, {})[sp] = tau_escalate
            for s in ids:
                in_esc = s in esc_set
                if in_esc:
                    route = "ESCALATE"
                elif frame[s]["clf_pred"] and r_hat[s] <= tau_accept:
                    route = "AUTO_ACCEPT"
                else:
                    route = "ABSTAIN"
                if b == 1.0:
                    final, fsrc, eval_ok = finalize_prediction(
                        frame[s]["clf_pred"],
                        {"status": "OK", "decision": b3[s]["prediction"], "decision_valid": b3[s]["prediction"] in VALID_LABELS} if s in b3 else None,
                        "B3_existing_blind_llm",
                    )
                elif route == "ESCALATE":
                    final, fsrc, eval_ok = finalize_prediction(frame[s]["clf_pred"], esc_records.get(s), "gpt-oss-20b_fresh")
                else:
                    final, fsrc, eval_ok = finalize_prediction(frame[s]["clf_pred"], None, "none")
                ref = reference.get(s)
                routes_at[sp][s][b] = route
                finals_at[sp][s][b] = (
                    final,
                    fsrc,
                    eval_ok,
                    int(bool(final) and final == ref) if ref else 0,
                )
            rows = [
                {"sample_id": s, "in_reference": bool(reference.get(s)), "route": routes_at[sp][s][b],
                 "final_prediction": finals_at[sp][s][b][0], "final_correct": finals_at[sp][s][b][3],
                 "violation": int(feat_rows[s]["lexical_contradiction"]), "r_hat": r_hat[s],
                 "base_correct": int(frame[s]["clf_pred"] == reference[s]) if reference.get(s) and frame[s]["clf_pred"] else None}
                for s in ids
            ]
            m = budget_metrics(rows)
            m.update({"split": sp, "budget": b, "llm_source": llm_source,
                      "tau_accept": tau_accept,
                      "tau_escalate": (tau_escalate if math.isfinite(tau_escalate) else None),
                      "tau_note": tau_note.get("note")})
            curve_rows.append(m)
        val_row_b = next(r for r in curve_rows if r["split"] == "val" and r["budget"] == b)
        print(f"[risk_routing] b={b:.0%} val: cov={val_row_b['coverage']} agr={val_row_b['semantic_agreement']} "
              f"risk={val_row_b['selective_risk']} tau_acc={val_row_b['tau_accept']:.3f}")

    curve_rows.sort(key=lambda r: (r["split"], r["budget"]))

    # ---- Pareto knee（VAL 主判读；DEV 对照；另给 b<=75% 单模型段诊断） ----
    knees: dict[str, Any] = {}
    for sp in ("dev", "val"):
        pts = [{"budget": r["budget"], "selective_risk": r["selective_risk"]}
               for r in curve_rows if r["split"] == sp and r["selective_risk"] is not None]
        knees[sp] = pareto_knee(pts)
        # b<=75% 段内升级模型同为 gpt-oss-20b（b=100% 切换为 B3 既有全量行），
        # 段内 knee 排除模型切换的影响，作为次要判读。
        pts75 = [p for p in pts if p["budget"] <= 0.75 + KNEE_TOL]
        knees[sp]["knee_b_le_75"] = pareto_knee(pts75)
    op_budget = float(knees["val"]["budget"])
    print(f"[risk_routing] knee: val@{op_budget:.0%} (gap={knees['val']['gap']:.4f}); "
          f"dev@{knees['dev']['budget']:.0%} (gap={knees['dev']['gap']:.4f}); "
          f"segment(b<=75%): val@{knees['val']['knee_b_le_75']['budget']:.0%} "
          f"(gap={knees['val']['knee_b_le_75']['gap']:.4f}), "
          f"dev@{knees['dev']['knee_b_le_75']['budget']:.0%} "
          f"(gap={knees['dev']['knee_b_le_75']['gap']:.4f})")

    # ---- ROUTING_RUNS_{split}.csv（操作点 = VAL knee 预算；含全预算路由列） ----
    runs_paths: dict[str, Path] = {}
    for sp, ids in split_ids.items():
        path = OUT_DIR / f"ROUTING_RUNS_{sp}.csv"
        fields = [
            "sample_id", "split", "has_clf_pred", "base_prediction", "base_pred_source",
            "r_hat", "rule_pred", "rule_conf", "clf_conf", "clf_margin",
            "llm_pred_b3", "llm_conf_b3", "production_type", "validated", "source_multiplicity",
            "lexical_contradiction", "reference_label", "in_reference",
            "base_correct", "tau_accept", "tau_escalate", "route", "final_prediction",
            "final_source", "escalation_valid", "final_correct", "operating_budget",
            "escalation_decision", "escalation_confidence",
        ] + [f"route@{budget_to_tag(b)}" for b in BUDGETS]
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for s in ids:
                f = frame[s]
                fin = finals_at[sp][s][op_budget]
                w.writerow({
                    "sample_id": s,
                    "split": sp,
                    "has_clf_pred": int(bool(f["clf_pred"])),
                    "base_prediction": f["clf_pred"] or "",
                    "base_pred_source": "B2_frozen_classifier" if f["clf_pred"] else "none",
                    "r_hat": round(r_hat[s], 6),
                    "rule_pred": f["rule_pred"] or "",
                    "rule_conf": f["rule_conf"] if f["rule_conf"] is not None else "",
                    "clf_conf": f["clf_conf"] if f["clf_conf"] is not None else "",
                    "clf_margin": f["clf_margin"] if f["clf_margin"] is not None else "",
                    "llm_pred_b3": f["llm_pred"] or "",
                    "llm_conf_b3": f["llm_conf"] if f["llm_conf"] is not None else "",
                    "production_type": f["production_type"],
                    "validated": int(f["validated"]),
                    "source_multiplicity": f["meta"].get("integrated_member_count", ""),
                    "lexical_contradiction": int(feat_rows[s]["lexical_contradiction"]),
                    "reference_label": reference.get(s, ""),
                    "in_reference": int(bool(reference.get(s))),
                    "base_correct": int(f["clf_pred"] == reference[s]) if reference.get(s) and f["clf_pred"] else "",
                    "tau_accept": round(tau_accept_at[op_budget][sp], 6),
                    "tau_escalate": (round(tau_escalate_at[op_budget][sp], 6)
                                     if math.isfinite(tau_escalate_at[op_budget][sp]) else ""),
                    "route": routes_at[sp][s][op_budget],
                    "final_prediction": fin[0],
                    "final_source": fin[1],
                    "escalation_valid": fin[2],
                    "final_correct": fin[3],
                    "operating_budget": op_budget,
                    "escalation_decision": (esc_records.get(s, {}) or {}).get("decision", ""),
                    "escalation_confidence": (esc_records.get(s, {}) or {}).get("confidence", ""),
                    **{f"route@{budget_to_tag(b)}": routes_at[sp][s][b] for b in BUDGETS},
                })
        runs_paths[sp] = path

    # ---- QUALITY_BUDGET_CURVE.csv ----
    curve_path = OUT_DIR / "QUALITY_BUDGET_CURVE.csv"
    cfields = [
        "split", "budget", "llm_source", "n_all", "n_eval_labeled", "n_auto_accept", "n_escalate",
        "n_abstain", "llm_call_rate", "coverage", "semantic_agreement", "selective_accuracy",
        "selective_risk", "generalized_risk", "aurc", "n_correct_published", "eval_wrong_prevalence",
        "tau_accept", "tau_escalate", "tau_note",
    ]
    with open(curve_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cfields)
        w.writeheader()
        for m in curve_rows:
            w.writerow({k: (round(m[k], 6) if isinstance(m[k], float) else m[k]) for k in cfields})

    # ---- RISK_MODEL_CARD.json ----
    model_card = build_model_card(chosen, fitted, selection, train_ids, dev_y, val_y,
                                  val_score_ids, r_hat, feat_rows, frame, split_map)
    card_path = OUT_DIR / "RISK_MODEL_CARD.json"
    card_path.write_text(json.dumps(model_card, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- SUMMARY.json ----
    lat_list = lat
    summary = {
        "created_utc": now_iso(),
        "seed": SEED,
        "wall_seconds": round(time.time() - t_start, 1),
        "inputs_sha256": {str(p): sha256_file(p) for p in (V3_RUNS, V3_REF_STRONG, V3_BLIND, SAMPLE, SIDECAR, SPLIT_MANIFEST)},
        "population": {
            "n_frame": len(frame), "n_dev": len(dev_ids), "n_val": len(val_ids),
            "n_test_excluded": len(test_ids),
            "n_reference_labeled": {sp: sum(1 for s in split_ids[sp] if reference.get(s)) for sp in split_ids},
            "n_no_clf_pred": {sp: sum(1 for s in split_ids[sp] if not frame[s]["clf_pred"]) for sp in split_ids},
        },
        "risk_model": {
            "chosen": chosen,
            "selection_rule": selection["rule"],
            "selection": selection["selection"],
            "features": FEATURE_NAMES,
            "feature_descriptions": FEATURE_DESCRIPTIONS,
            "labels": "IMCR_REFERENCE_STRONG entity_type rows; wrong = clf_pred != reference_label; DEV only",
            "forbidden_labels": "weak auto_accepted 标签禁止用作 risk 真值（未使用）",
            "no_clf_policy": "clf_pred 缺失的样本 r_hat=1.0（无候选信号，永不 AUTO_ACCEPT）",
        },
        "budgets": BUDGETS,
        "per_split_budget_counts": {sp: {budget_to_tag(b): per_split_k[sp][b] for b in BUDGETS} for sp in split_ids},
        "tau_accept_by_budget": {budget_to_tag(b): tau_accept_at[b] for b in BUDGETS},
        "tau_escalate_by_budget": {budget_to_tag(b): tau_escalate_at[b] for b in BUDGETS},
        "operating_point": {"budget": op_budget, "basis": "VAL Pareto knee", "knees": knees},
        "curve": curve_rows,
        "escalation": {
            "model": DEFAULT_MODEL,
            "prompt_version": "risk_routing.escalation.v1",
            "prompt_system": ESCALATION_SYSTEM_PROMPT,
            "prompt_sha256": sha256_text(ESCALATION_SYSTEM_PROMPT),
            "payload_fields": ["task_id", "entity_name", "aliases", "context_assertions",
                               "source_excerpt", "candidate_types", "type_definitions"],
            "leakage_guards": "payload 不含生产标签/参考标签/正确性信息；TEST split 调用被显式阻断",
            "fresh_calls_made": runner_calls,
            "cached_records_total": len(esc_records),
            "ok_records": len(ok_calls),
            "valid_decisions": sum(1 for r in ok_calls if r.get("decision_valid")),
            "invalid_decisions": sum(1 for r in ok_calls if r.get("status") == "OK" and not r.get("decision_valid")),
            "errors": sum(1 for r in esc_records.values() if r.get("status") == "ERROR"),
            "escalation_failures": sorted(s for s in fresh_ids if s not in esc_records),
            "escalation_failure_note": (
                "状态 ERROR 的样本（JSONL 中留有完整错误记录；temperature=0 下输出为确定性"
                "畸形 JSON，重试同败）路由上回退基础预测（final_source=base_prediction_fallback）。"
            ),
            "jsonl_records_total": len(ESCALATION_LOG.read_text(encoding="utf-8").splitlines()) if ESCALATION_LOG.exists() else 0,
            "latency_avg_s": (sum(lat_list) / len(lat_list)) if lat_list else None,
            "latency_max_s": (max(lat_list) if lat_list else None),
            "b100_source": "IMCR_BLIND_LLM_RUNS.csv B3_blind_llm（gpt-5.6-luna 既有全量 382 行，真实 every-item 对照）",
        },
        "guards": {
            "test_split_excluded": True,
            "test_ids_excluded_n": len(test_ids),
            "risk_labels_only_from_independent_reference": True,
            "weak_auto_accepted_labels_used": False,
        },
        "outputs": {
            "model_card": str(card_path),
            "runs": {sp: str(runs_paths[sp]) for sp in split_ids},
            "curve": str(curve_path),
            "escalation_log": str(ESCALATION_LOG),
        },
    }
    (OUT_DIR / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[risk_routing] DONE in {summary['wall_seconds']}s; outputs -> {OUT_DIR}")
    return 0


def build_model_card(
    chosen: str,
    fitted: dict[str, Any],
    selection: dict[str, Any],
    train_ids: list[str],
    dev_y: dict[str, int],
    val_y: dict[str, int],
    val_score_ids: list[str],
    r_hat: dict[str, float],
    feat_rows: dict[str, dict[str, float]],
    frame: dict[str, Any],
    split_map: dict[str, str],
) -> dict[str, Any]:
    card: dict[str, Any] = {
        "created_utc": now_iso(),
        "seed": SEED,
        "task": "r_hat = P(clf_pred wrong | features), entity_type 382 canonical entities",
        "base_prediction": "B2_frozen_classifier prediction（生产机制：预测源恒为分类器）",
        "feature_names": FEATURE_NAMES,
        "feature_descriptions": FEATURE_DESCRIPTIONS,
        "onehot_classes": ONEHOT_CLASSES,
        "train": {
            "split": "dev",
            "n": len(train_ids),
            "wrong_prevalence": sum(dev_y.values()) / len(dev_y) if dev_y else None,
            "labels_source": "IMCR_REFERENCE_STRONG.csv entity_type (strong consensus)",
            "label_rule": "wrong = 1 iff clf_pred != reference_label",
            "excluded": "无参考标签样本、clf_pred 缺失样本、全部 TEST 样本",
        },
        "selection": selection,
        "policies": {
            "no_clf_pred": "r_hat=1.0，路由上永不 AUTO_ACCEPT",
            "threshold_learning": "tau_accept/tau_escalate 仅在 VAL 上按预算约束学习，DEV 只作观察",
            "test_guard": "assert_no_test_samples 显式过滤 + 断言（训练/打分/升级全部路径）",
            "weak_labels": "禁止使用 weak auto_accepted 标签做 risk 真值（未使用）",
        },
        "val_scoring": {
            "n": len(val_score_ids),
            "wrong_prevalence": sum(val_y.values()) / len(val_y) if val_y else None,
        },
        "candidates": SIMPLICITY_ORDER,
        "simplicity_preference": SIMPLICITY_ORDER,
        "auprc_tolerance": AUPRC_TOLERANCE,
    }
    est = fitted["models"][chosen]
    if chosen == "CalibratedLR_sigmoid":
        # EnsemblePlattLR：导出各折 Platt (A,B) 与各折基础 LR 的标准化系数均值
        card["calibration"] = {
            "implementation": "EnsemblePlattLR (explicit Platt, 5-fold ensemble)",
            "engineering_note": (
                "sklearn 1.8.0 CalibratedClassifierCV 在本数据配置下 predict_proba 与底层 LR "
                "概率完全反序（spearman=-1.000，_get_response_values 优先 decision_function "
                "与校准器拟合尺度不相容）；按 Platt (1999) 原义显式实现并经测试固化。"
            ),
            "folds": [
                {"A": a, "B": b, "base_lr_coef_standardized": {
                    name: round(float(c), 6) for name, c in zip(FEATURE_NAMES, m.steps[-1][1].coef_[0])}}
                for m, (a, b) in zip(est.models_, est.ab_)
            ],
        }
        mean_coefs = np.mean([m.steps[-1][1].coef_[0] for m in est.models_], axis=0)
        card["coefficients_standardized_mean_over_folds"] = {
            name: round(float(c), 6) for name, c in zip(FEATURE_NAMES, mean_coefs)
        }
        ranked = sorted(card["coefficients_standardized_mean_over_folds"].items(), key=lambda kv: -abs(kv[1]))
        card["feature_importance_ranked_abs_coef"] = ranked
        card["feature_importance_top5"] = ranked[:5]
    elif chosen == "DecisionTree_max_depth4":
        imp = est.feature_importances_
        ranked = sorted(zip(FEATURE_NAMES, (round(float(v), 6) for v in imp)), key=lambda kv: -kv[1])
        card["feature_importance_tree"] = dict(ranked)
        card["feature_importance_top5"] = ranked[:5]
    else:
        lr = est.steps[-1][1]
        scaler = est.steps[0][1]
        coefs = lr.coef_[0]
        card["coefficients_standardized"] = {
            name: round(float(c), 6) for name, c in zip(FEATURE_NAMES, coefs)
        }
        card["intercept"] = round(float(lr.intercept_[0]), 6)
        card["scaler_mean_std"] = {
            name: {"mean": round(float(m), 6), "std": round(float(s), 6)}
            for name, m, s in zip(FEATURE_NAMES, scaler.mean_, scaler.scale_)
        }
        ranked = sorted(card["coefficients_standardized"].items(), key=lambda kv: -abs(kv[1]))
        card["feature_importance_ranked_abs_coef"] = ranked
        card["feature_importance_top5"] = ranked[:5]
    dist: dict[str, Any] = {}
    for sp in ("dev", "val"):
        ids_sp = [s for s in r_hat if split_map.get(f"entity_type:{s}") == sp]
        dist[sp] = (
            {"min": round(min(r_hat[s] for s in ids_sp), 6), "max": round(max(r_hat[s] for s in ids_sp), 6)}
            if ids_sp else None
        )
    card["r_hat_distribution"] = dist
    return card


if __name__ == "__main__":
    raise SystemExit(main())
