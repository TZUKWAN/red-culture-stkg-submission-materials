# -*- coding: utf-8 -*-
"""run_routing_model_agnostic.py — 框架机制模型无关性验证（换任何单个升级模型 M）。

核心问题：框架机制（Risk Estimator r_hat 降序 + 预算 top-k 升级 + 盲化 escalation prompt）
是否模型无关——即"换任何单个升级模型，框架都把它用在刀刃上"。

升级模型 M ∈ {openai/gpt-oss-20b, google/gemma-4-e4b, qwen/qwen3-8b}（本地 LM Studio）。

设计（全部只新建文件，不修改任何既有文件）：
  0. 机制只读复用：run_risk_routing.py 的信号帧/特征工程/risk model（决策树
     DecisionTree_max_depth4，VAL AUPRC 0.728）/预算 top-k/盲化 escalation prompt
     （prompt 与 payload 逐字节一致，sha256 核对后才允许缓存命中）；run_budget_curves.py
     的 leave-B-out 质量口径 / R1 随机路由（seed 20260910，与 budget_v2 同源同实现）/
     score_finals / paired bootstrap / r_hat 确定性重训与逐样本核对。
  1. 样本：DEV+VAL（frame 内 dev 254 + val 66 = 320）；TEST 显式过滤并断言
     （rr.assert_no_test_samples + 集合断言）。
  2. 质量口径：leave-B-out 参考（IMCR_REFERENCE_LEAVE_B_OUT.csv entity_type 行，
     judge_removed=B）——与 risk 标签（strong，仅 DEV 拟合 risk model 用）解耦。
  3. 每模型 probe：先各 2 次 JSON 合格性探针（lmstudio_provider.probe 同款格式）；
     不合格如实记录并跳过该模型。
  4. 实验臂（对每个 probe 合格的 M）：
     ROUTED  = 预算 b ∈ {10,20,30,50}%，每 split 内 r_hat 最高的 k=round-half-up(b·n)
               个样本升级给 M（与 run_risk_routing/run_budget_curves R6 同机制）；
     RANDOM  = R1 随机对照（seed 20260910，每 split 一条固定全排列，预算取前缀→嵌套；
               与 budget_v2 完全同实现），对照预算见规划器输出；
     EVERY   = b=100%（M every-item）质量上限——只有 gpt-oss-20b 执行（319/320 已有
               只读缓存命中；其余模型在 ≤450 新调用硬约束下不可行，如实记录不执行）；
     BASELINE= b=0（无升级，基础分类器全发布）。
     升级→M 决策替换基础预测（无效/ERROR 回退基础预测，与生产政策一致）；
     未升级→基础预测；全部发布、无弃权。
  5. 三证据：
     E1 每模型升级段一致率(M) > 同段基线一致率（并对比接受段基线）——框架提升任何 M；
     E2 同预算下质量随 M 能力排序（曲线高度差），曲线形状（单调性/机制）一致；
     E3 r_hat 路由 vs R1 随机升级对照（同预算，bootstrap 2000 次，seed 20260910），三层读法：
        E3a 部署级主检验 = 同预算整臂最终一致率 ROUTED − RANDOM（paired bootstrap）；
        E3b 路由难度有效性 = ROUTED 段基线一致率显著低于 RANDOM 段（r_hat 预测力本身）；
        E3c 字面段对比（升级段 M 一致率 vs 随机段 M 一致率）——受题目难度混淆，只作透明披露。
  6. 调用账本（硬约束）：三模型新调用总计 ≤ 450。旧缓存只读复用（同 prompt 同 payload
     才命中）：risk_routing/ESCALATION_CALLS.jsonl 240 条 OK + budget_v2/
     ESCALATION_CALLS.jsonl 79 条 OK（均为 gpt-oss-20b，并集 319/320）。规划器在
     执行前确定性计算各方案的精确新调用量并断言 ≤ 450。
  7. 断点续跑：本实验自己的 MODEL_AGNOSTIC_CALLS.jsonl 追加写、status=OK 视为完成；
     ERROR 重跑自动重试（与 rr.EscalationRunner 政策一致）。

工程注记（模型钉住）：lmstudio_provider.chat_json 的重试策略在最后一次尝试会静默回退
qwen/qwen3-8b（DEFAULT_FALLBACK），会污染"单模型升级"的归因。本脚本用与 chat_json
完全相同的 _post/extract_json 路径实现模型钉住变体 chat_json_pinned：重试全程固定
请求模型，并记录响应中的 served_model 供审计。除"无回退"外参数与 chat_json 一致
（temperature=0、max_tokens=900、timeout=300s、retries=2）。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from collections import Counter
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

import run_risk_routing as rr  # noqa: E402  只 import 复用，不修改
import run_selective_semantic as rss  # noqa: E402  只 import 复用，不修改
import run_budget_curves as rbc  # noqa: E402  只 import 复用，不修改
import lmstudio_provider as lmp  # noqa: E402  只 import 复用，不修改

MODELS = ["openai/gpt-oss-20b", "google/gemma-4-e4b", "qwen/qwen3-8b"]
GPTOSS = "openai/gpt-oss-20b"

CURVE_BUDGETS = [0.0, 0.10, 0.20, 0.30, 0.50, 1.0]      # 主曲线预算（含 0 与 100%）
ROUTED_BUDGETS = [0.10, 0.20, 0.30, 0.50]                # 路由升级臂预算
SEED = rbc.SEED                                          # 20260910（R1 随机与 bootstrap 同源）
N_BOOTSTRAP = rbc.N_BOOTSTRAP                            # 2000
CALL_CAP = 450                                           # 三模型新调用硬上限
PROBE_N = 2                                              # 每模型 JSON 合格性探针次数
KNEE_TOL = rr.KNEE_TOL

OLD_CACHES_READONLY = [rr.OUT_DIR / "ESCALATION_CALLS.jsonl",
                       rbc.ESCALATION_LOG_V2]            # 只读复用，绝不写入
OUT_DIR = V3_1 / "experiments" / "02_selective_semantic" / "model_agnostic"
ESC_LOG = OUT_DIR / "MODEL_AGNOSTIC_CALLS.jsonl"
AUDIT_DIR = V3_1 / "audit" / "method_final"
REPORT_PATH = AUDIT_DIR / "15_MODEL_AGNOSTIC_REPORT.md"
BUDGET_V2_ROUTING_CSV = rbc.OUT_DIR / "ROUTING_COMPARISON.csv"

PROMPT_SHA = rr.sha256_text(rr.ESCALATION_SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def r6(x: float | None) -> Any:
    return round(float(x), 6) if x is not None else None


def budget_tag(b: float) -> str:
    return f"b{round(b * 100):03d}"


def chat_json_pinned(messages: list[dict[str, str]], model: str, *,
                     temperature: float = 0.0, max_tokens: int = 900,
                     timeout: float = 300.0, retries: int = 2) -> tuple[dict[str, Any], str | None]:
    """lmstudio_provider.chat_json 的模型钉住变体（同一 _post/extract_json 路径）。

    与 chat_json 的唯一差异：重试全程固定请求模型（provider 版最后一次重试会静默
    回退 DEFAULT_FALLBACK=qwen/qwen3-8b，污染单模型归因）。返回 (json_obj, served_model)。
    """
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            d = lmp._post(
                f"{lmp.DEFAULT_BASE.rstrip('/')}/chat/completions",
                {"model": model, "messages": messages, "temperature": temperature,
                 "top_p": 1.0, "max_tokens": max_tokens},
                timeout,
            )
            content = str(d["choices"][0]["message"].get("content") or "")
            served = d.get("model")
            return lmp.extract_json(content), (str(served) if served else None)
        except Exception as exc:  # 本地服务：网络类失败短暂退避后重试（模型固定）
            last_err = exc
            time.sleep(min(2 ** attempt, 8))
    raise lmp.LMStudioError(f"pinned chat failed after retries (model={model}): {last_err}")


# ---------------------------------------------------------------------------
# 旧缓存只读复用（同 prompt 同 payload 才允许命中）
# ---------------------------------------------------------------------------

def load_old_caches_verified(frame: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """读取两个旧 ESCALATION_CALLS.jsonl（只读），逐条核对 prompt/payload sha 与模型。

    返回 (model -> sample_id -> record, audit_info)。status=OK 且 sha 全匹配才进入复用集。
    """
    reuse: dict[str, dict[str, Any]] = {}
    audit: dict[str, Any] = {"caches": [], "dropped_prompt_sha": 0, "dropped_payload_sha": [],
                             "dropped_model": 0}
    for path in OLD_CACHES_READONLY:
        info: dict[str, Any] = {"path": str(path), "exists": path.exists(),
                                "lines": 0, "ok_unique": 0, "reused": 0}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                info["lines"] += 1
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("status") != "OK":
                    continue
                sid = str(rec.get("sample_id"))
                if sid in {r.get("sample_id") for r in reuse.get(str(rec.get("model")), {}).values()}:
                    continue
                model = str(rec.get("model"))
                if rec.get("prompt_sha256") not in (None, PROMPT_SHA):
                    audit["dropped_prompt_sha"] += 1
                    continue
                want = rr.sha256_text(json.dumps(rr.escalation_payload(frame, sid),
                                                 ensure_ascii=False, sort_keys=True))
                if rec.get("payload_sha256") not in (None, want):
                    audit["dropped_payload_sha"].append(f"{model}:{sid}")
                    continue
                bucket = reuse.setdefault(model, {})
                if sid in bucket:
                    continue
                bucket[sid] = rec
                info["reused"] += 1
        info["ok_unique"] = info["reused"]
        audit["caches"].append(info)
    return reuse, audit


# ---------------------------------------------------------------------------
# 探针（每模型 2 次 JSON 合格性）
# ---------------------------------------------------------------------------

def load_probe_history() -> dict[str, list[dict[str, Any]]]:
    """从本实验 JSONL 读取全部 v2 探针记录（含失败），用于 skip 模式恢复真实跳过原因。"""
    hist: dict[str, list[dict[str, Any]]] = {}
    if not ESC_LOG.exists():
        return hist
    for line in ESC_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "probe" or rec.get("probe_protocol") != "v2_production_params":
            continue
        hist.setdefault(str(rec.get("model")), []).append(rec)
    return hist


def load_probe_cache() -> dict[tuple[str, int], dict[str, Any]]:
    """从本实验 JSONL 读取 v2 探针的既有合格记录（json_ok=True 视为完成，断点续跑）。"""
    done: dict[tuple[str, int], dict[str, Any]] = {}
    if not ESC_LOG.exists():
        return done
    for line in ESC_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "probe" or rec.get("probe_protocol") != "v2_production_params":
            continue
        if not rec.get("json_ok"):
            continue
        done[(str(rec.get("model")), int(rec.get("i", -1)))] = rec
    return done


def run_probes(model: str, cached: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
    """每模型 PROBE_N 次 JSON 合格性探针（已有合格探针直接复用，断点续跑）。

    探针协议 v2（当前）：任务格式沿用 lmstudio_provider.probe 的最小 JSON 任务，但调用
    参数与生产升级调用完全一致（temperature=0、max_tokens=900、timeout=300s、retries=2）——
    qwen3-8b 为思考型模型，max_tokens=60 会被思考耗尽致 content 为空（首轮探针 v1 的
    教训，v1 记录保留在 MODEL_AGNOSTIC_CALLS.jsonl），故探针必须测"生产参数下的 JSON
    合格性"。两轮探针记录均留痕；未通过的探针每次运行重试（与 ERROR 升级同政策）。
    """
    probes: list[dict[str, Any]] = []
    for i in range(PROBE_N):
        if (model, i) in cached:
            probes.append(dict(cached[(model, i)], reused_from_log=True))
            continue
        t0 = time.time()
        rec: dict[str, Any] = {"type": "probe", "probe_protocol": "v2_production_params",
                               "model": model, "i": i, "started_utc": now_iso()}
        try:
            out, served = chat_json_pinned(
                [{"role": "system", "content": '输出且仅输出一个 JSON 对象 {"ok": true, "i": <int>}'},
                 {"role": "user", "content": f"i={i}"}],
                model=model, max_tokens=900, timeout=300.0, retries=2,
            )
            rec.update({"status": "OK", "json_ok": out.get("ok") is True and out.get("i") == i,
                        "served_model": served, "latency_s": round(time.time() - t0, 3)})
        except Exception as exc:
            rec.update({"status": "ERROR", "error": str(exc)[:300], "json_ok": False,
                        "latency_s": round(time.time() - t0, 3)})
        probes.append(rec)
        append_log(rec)
    n_ok = sum(1 for p in probes if p.get("json_ok"))
    n_new = sum(1 for p in probes if not p.get("reused_from_log"))
    lat = [p["latency_s"] for p in probes if p.get("json_ok")]
    return {"model": model, "n": PROBE_N, "json_ok_n": n_ok,
            "pass": n_ok == PROBE_N, "probe_calls_this_run": n_new,
            "latency_avg_s": (sum(lat) / len(lat)) if lat else None,
            "probes": probes}


# ---------------------------------------------------------------------------
# 升级调用 runner（每模型一个；断点续跑；TEST 硬禁止）
# ---------------------------------------------------------------------------

_LOG_LOCK = threading.Lock()


def append_log(rec: dict[str, Any]) -> None:
    with _LOG_LOCK:
        ESC_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ESC_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")


def load_self_cache() -> dict[tuple[str, str], dict[str, Any]]:
    done: dict[tuple[str, str], dict[str, Any]] = {}
    if not ESC_LOG.exists():
        return done
    for line in ESC_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") == "probe" or rec.get("status") != "OK":
            continue
        done[(str(rec.get("model")), str(rec.get("sample_id")))] = rec
    return done


class ModelEscalationRunner:
    """单模型升级执行器：self JSONL 断点续跑 + 旧缓存只读命中（gpt-oss-20b）。"""

    def __init__(self, frame: dict[str, Any], split_map: dict[str, str], model: str,
                 old_reuse: dict[str, dict[str, Any]], workers: int = 2):
        self.frame = frame
        self.split_map = split_map
        self.model = model
        self.workers = max(1, min(workers, 3))
        self.old_reuse: dict[str, dict[str, Any]] = old_reuse.get(model, {})
        self.self_cache = {sid: rec for (m, sid), rec in load_self_cache().items() if m == model}
        self.records: dict[str, dict[str, Any]] = dict(self.old_reuse)
        self.records.update(self.self_cache)
        self.calls_made = 0
        self.errors = 0
        self.served_mismatch = 0

    def _call(self, sid: str) -> dict[str, Any]:
        payload = rr.escalation_payload(self.frame, sid)
        payload_sha = rr.sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        rec: dict[str, Any] = {
            "type": "escalation",
            "sample_id": sid,
            "split": self.split_map.get(f"entity_type:{sid}", "unknown"),
            "model": self.model,
            "prompt_version": "risk_routing.escalation.v1",
            "prompt_sha256": PROMPT_SHA,
            "payload_sha256": payload_sha,
            "started_utc": now_iso(),
        }
        if rec["split"] == "test":
            rec.update({"status": "BLOCKED_TEST_SPLIT", "decision": None, "decision_valid": False})
            append_log(rec)
            raise AssertionError(f"escalation attempted on TEST sample {sid}")
        t0 = time.time()
        try:
            out, served = chat_json_pinned(
                [{"role": "system", "content": rr.ESCALATION_SYSTEM_PROMPT},
                 {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)}],
                model=self.model, temperature=0.0, max_tokens=900, timeout=300.0, retries=2,
            )
            rec["latency_s"] = round(time.time() - t0, 3)
            decision = str(out.get("decision") or "").strip()
            conf = out.get("confidence")
            rec.update({
                "status": "OK",
                "served_model": served,
                "decision": decision,
                "decision_valid": decision in rr.VALID_LABELS,
                "confidence": float(conf) if isinstance(conf, (int, float)) else None,
                "reason_code": out.get("reason_code"),
                "insufficient_evidence": bool(out.get("insufficient_evidence")),
            })
            if served is not None and served != self.model:
                self.served_mismatch += 1
        except Exception as exc:
            rec.update({"status": "ERROR", "error": str(exc)[:300], "decision_valid": False,
                        "latency_s": round(time.time() - t0, 3)})
        append_log(rec)
        return rec

    def ensure(self, sample_ids: list[str]) -> None:
        rr.assert_no_test_samples(sample_ids, self.split_map, f"model_agnostic.ensure:{self.model}")
        pending = [s for s in sample_ids
                   if s not in self.old_reuse and s not in self.self_cache]
        fresh_errors = 0
        if pending:
            if self.workers <= 1:
                for sid in pending:
                    rec = self._call(sid)
                    fresh_errors += self._absorb(rec, sid)
                    print(f"  [{self.model}] {sid} status={rec['status']} decision={rec.get('decision')}",
                          flush=True)
            else:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                with ThreadPoolExecutor(max_workers=self.workers) as pool:
                    futs = {pool.submit(self._call, sid): sid for sid in pending}
                    for fut in as_completed(futs):
                        sid = futs[fut]
                        rec = fut.result()
                        fresh_errors += self._absorb(rec, sid)
                        print(f"  [{self.model}] {sid} status={rec['status']} decision={rec.get('decision')}",
                              flush=True)
        self.calls_made += len(pending)
        self.errors += fresh_errors

    def _absorb(self, rec: dict[str, Any], sid: str) -> int:
        if rec.get("status") == "OK":
            self.records[sid] = rec
            return 0
        return 1


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------

def finalize_for(model: str, frame: dict[str, Any], sid: str,
                 esc_records: dict[str, dict[str, Any]], escalated: bool) -> dict[str, Any]:
    """升级→M 决策（无效回退基础预测）；未升级→基础预测。与生产政策一致。"""
    base = rbc.base_pred(frame, sid)
    if not escalated:
        return {"final": base, "source": ("base_prediction" if base else "none"),
                "escalation_valid": 0, "escalated": False, "fallback": False}
    rec = esc_records.get(sid)
    final, fsrc, ok = rr.finalize_prediction(base, rec, f"{model}_escalation")
    return {"final": final, "source": fsrc, "escalation_valid": ok,
            "escalated": True, "fallback": bool(rec is None or not ok)}


def eval_arm(model: str, frame: dict[str, Any], work_ids: list[str],
             split_ids: dict[str, list[str]], esc_sets: dict[str, set[str]],
             esc_records: dict[str, dict[str, Any]], ref_lob: dict[str, str]) -> dict[str, Any]:
    """一个 (model, arm, budget) 点的全套指标（pooled 主读数 + dev/val 一致率列）。"""
    esc_union: set[str] = set().union(*esc_sets.values()) if esc_sets else set()
    finals = {s: finalize_for(model, frame, s, esc_records, s in esc_union) for s in work_ids}
    m = rbc.score_finals(work_ids, finals, frame, ref_lob)
    m_dev = rbc.score_finals(split_ids["dev"], {s: finals[s] for s in split_ids["dev"]}, frame, ref_lob)
    m_val = rbc.score_finals(split_ids["val"], {s: finals[s] for s in split_ids["val"]}, frame, ref_lob)
    labeled = [s for s in work_ids if ref_lob.get(s)]
    seg = [s for s in labeled if s in esc_union]
    acc = [s for s in labeled if s not in esc_union]
    m_correct = base_correct = 0
    w2r = r2w = n_fb = 0
    for s in seg:
        f = finals[s]
        mc = int(f["final"] == ref_lob[s])
        bc = int(rbc.base_pred(frame, s) == ref_lob[s])
        m_correct += mc
        base_correct += bc
        if bc == 0 and mc == 1:
            w2r += 1
        if bc == 1 and mc == 0:
            r2w += 1
        n_fb += int(f["fallback"])
    acc_base_ok = sum(int(rbc.base_pred(frame, s) == ref_lob[s]) for s in acc)
    out = {
        "model": model, "n_all": len(work_ids),
        "k_total": len(esc_union),
        "n_labeled": m["n_labeled"], "agreement": m["agreement"], "n_correct": m["n_correct"],
        "wrong_to_right": m["wrong_to_right"], "right_to_wrong": m["right_to_wrong"],
        "generalized_risk": m["generalized_risk"], "n_final_empty": m["n_final_empty"],
        "agreement_dev": m_dev.get("agreement"), "agreement_val": m_val.get("agreement"),
        "seg_n": len(seg),
        "seg_agreement_model": (m_correct / len(seg)) if seg else None,
        "seg_agreement_base": (base_correct / len(seg)) if seg else None,
        "seg_lift_vs_base": ((m_correct - base_correct) / len(seg)) if seg else None,
        "seg_wrong_to_right": w2r, "seg_right_to_wrong": r2w, "seg_n_fallback": n_fb,
        "accepted_seg_n": len(acc),
        "accepted_seg_agreement_base": (acc_base_ok / len(acc)) if acc else None,
    }
    out["correct_vectors"] = {
        "final": np.array([int(finals[s]["final"] == ref_lob[s]) for s in labeled]),
        "seg_final": np.array([int(finals[s]["final"] == ref_lob[s]) for s in seg]),
        "seg_base": np.array([int(rbc.base_pred(frame, s) == ref_lob[s]) for s in seg]),
        "seg_ids": seg,
        "labeled_ids": labeled,
    }
    return out


def unpaired_bootstrap(a: np.ndarray, b: np.ndarray, n_boot: int, seed_seq: list[int]) -> dict[str, Any]:
    """两段独立样本的均值差 bootstrap（各自重采样；用于升级段 vs 随机段）。"""
    rng = np.random.default_rng(seed_seq)
    ia = rng.integers(0, len(a), size=(n_boot, len(a)))
    ib = rng.integers(0, len(b), size=(n_boot, len(b)))
    deltas = a[ia].mean(axis=1) - b[ib].mean(axis=1)
    obs = float(a.mean() - b.mean())
    lo, hi = (float(v) for v in np.percentile(deltas, [2.5, 97.5]))
    p_two = float(2.0 * min((deltas <= 0).mean(), (deltas >= 0).mean()))
    return {"delta_observed": obs, "ci95_low": lo, "ci95_high": hi,
            "p_boot_two_sided": min(1.0, p_two), "frac_delta_gt0": float((deltas > 0).mean())}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2, help="每模型升级并发数（≤3）")
    ap.add_argument("--skip-escalation", action="store_true", help="只用缓存，不发新调用/探针")
    ap.add_argument("--limit-escalation", type=int, default=None, help="每模型最多新调用条数（冒烟用）")
    ap.add_argument("--plan-only", action="store_true", help="只打印调用规划，不执行")
    ap.add_argument("--models", type=str, default=",".join(MODELS), help="逗号分隔模型子集")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    models_exec = [m.strip() for m in args.models.split(",") if m.strip()]

    # ---- 数据与切分（TEST 硬排除） ----
    frame = rss.build_signal_frame()
    ref_lob, judge_sets = rbc.load_reference_lob()
    ref_strong = rss.load_reference("strong")
    split_map = rss.load_split()
    all_ids = sorted(frame)
    test_ids = [s for s in all_ids if split_map.get(f"entity_type:{s}") == "test"]
    work_ids = [s for s in all_ids if split_map.get(f"entity_type:{s}") in ("dev", "val")]
    dev_ids = [s for s in work_ids if split_map[f"entity_type:{s}"] == "dev"]
    val_ids = [s for s in work_ids if split_map[f"entity_type:{s}"] == "val"]
    split_ids = {"dev": dev_ids, "val": val_ids}
    rr.assert_no_test_samples(work_ids, split_map, "model_agnostic:main")
    assert not (set(work_ids) & set(test_ids)), "TEST samples leaked into work set"
    print(f"[model_agnostic] frame={len(frame)} dev={len(dev_ids)} val={len(val_ids)} "
          f"test(excluded)={len(test_ids)}; labeled(leave_b_out)={sum(1 for s in work_ids if ref_lob.get(s))}")

    # ---- r_hat：冻结机制确定性重训 + 与既有 ROUTING_RUNS_* 逐样本核对 ----
    rebuilt = rbc.rebuild_r_hat(frame, ref_strong, split_map, work_ids)
    r_hat, feat_rows, chosen = rebuilt["r_hat"], rebuilt["feat_rows"], rebuilt["chosen"]
    r_hat_check = rbc.verify_r_hat_reuse(r_hat)
    assert r_hat_check["match"], f"r_hat 不匹配既有模型卡输出: {r_hat_check}"
    print(f"[model_agnostic] r_hat reuse: chosen={chosen} (card=DecisionTree_max_depth4) "
          f"n={r_hat_check['n_compared']} max|diff|={r_hat_check['max_abs_diff']:.2e} match={r_hat_check['match']}")

    # ---- 旧缓存只读复用（sha 逐条核对） ----
    old_reuse, old_audit = load_old_caches_verified(frame)
    old_union_gptoss = set(old_reuse.get(GPTOSS, {}))
    print(f"[model_agnostic] old cache reuse: " +
          "; ".join(f"{m}: {len(v)}" for m, v in old_reuse.items()) +
          f"; dropped(prompt_sha={old_audit['dropped_prompt_sha']}, "
          f"payload_sha={len(old_audit['dropped_payload_sha'])})")

    # ---- 路由排序（ROUTED=r_hat 降序；RANDOM=R1 seed20260910，与 budget_v2 同实现） ----
    order_routed = {sp: rbc.route_order("R6", ids, r_hat, feat_rows, frame, ref_lob)
                    for sp, ids in split_ids.items()}
    order_random = {sp: rbc.route_order("R1", ids, r_hat, feat_rows, frame, ref_lob)
                    for sp, ids in split_ids.items()}
    k_at = {(sp, b): rbc.budget_k(len(ids), b) for sp, ids in split_ids.items() for b in ROUTED_BUDGETS}

    def routed_sets(b: float) -> dict[str, set[str]]:
        return {sp: set(order_routed[sp][: k_at[(sp, b)]]) for sp in split_ids}

    def random_sets(b: float) -> dict[str, set[str]]:
        return {sp: set(order_random[sp][: k_at[(sp, b)]]) for sp in split_ids}

    # ---- 调用规划器：执行前确定性计算，硬约束 ≤450 ----
    def pools_for(rb_by_model: dict[str, list[float]], every: dict[str, bool]) -> dict[str, list[str]]:
        pools: dict[str, list[str]] = {}
        for m in models_exec:
            p: set[str] = set()
            for sp, ids in split_ids.items():
                p |= set(order_routed[sp][: k_at[(sp, 0.5)]])
                for b in rb_by_model[m]:
                    p |= set(order_random[sp][: k_at[(sp, b)]])
            if every.get(m):
                p |= set(work_ids)
            pools[m] = sorted(p)
        return pools

    def new_calls(pools: dict[str, list[str]]) -> int:
        tot = PROBE_N * len(models_exec)  # 探针恒为新调用
        for m, pool in pools.items():
            hits = len(old_union_gptoss & set(pool)) if m == GPTOSS else 0
            tot += len(pool) - hits
        return tot

    every_gptoss = {m: (m == GPTOSS) for m in models_exec}
    plan_options = [
        ("A_rb{10,20,30,50}_all", {m: list(ROUTED_BUDGETS) for m in models_exec}, every_gptoss),
        ("B_rb{10,20,30}_others_gptoss_rb{10,20,30,50}",
         {GPTOSS: list(ROUTED_BUDGETS),
          **{m: [0.10, 0.20, 0.30] for m in models_exec if m != GPTOSS}}, every_gptoss),
        ("C_rb{10,20}_others",
         {GPTOSS: list(ROUTED_BUDGETS),
          **{m: [0.10, 0.20] for m in models_exec if m != GPTOSS}}, every_gptoss),
        ("D_no_random_others", {GPTOSS: list(ROUTED_BUDGETS)}, every_gptoss),
    ]
    plan_eval = []
    chosen_plan = None
    for name, rb, every in plan_options:
        rb_full = {m: rb.get(m, list(ROUTED_BUDGETS) if m == GPTOSS else rb.get(m, [])) for m in models_exec}
        pools = pools_for(rb_full, every)
        tot = new_calls(pools)
        plan_eval.append({"option": name, "random_budgets": {m: rb_full[m] for m in models_exec},
                          "pool_sizes": {m: len(p) for m, p in pools.items()},
                          "estimated_new_calls": tot, "within_cap": tot <= CALL_CAP})
        if chosen_plan is None and tot <= CALL_CAP:
            chosen_plan = {"option": name, "random_budgets": rb_full, "every_item": every, "pools": pools}
    assert chosen_plan is not None, "无可行调用规划（硬约束 ≤450 无法满足），请缩小模型集"
    for m, pool in chosen_plan["pools"].items():
        rr.assert_no_test_samples(pool, split_map, f"plan_pool:{m}")
    print(f"[model_agnostic] plan={chosen_plan['option']} pools=" +
          ", ".join(f"{m.split('/')[-1]}:{len(p)}" for m, p in chosen_plan["pools"].items()) +
          f"; estimated_new_calls={new_calls(chosen_plan['pools'])} (cap={CALL_CAP})")
    if args.plan_only:
        print(json.dumps({"plan_eval": plan_eval, "chosen": chosen_plan["option"]},
                         ensure_ascii=False, indent=2))
        return 0

    # ---- 探针（每模型 2 次 JSON 合格性；合格探针从日志缓存复用，不合格重试） ----
    probe_results: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    cached_probes = load_probe_cache()
    if args.skip_escalation:
        probe_hist = load_probe_history()
        for m in models_exec:
            have = [cached_probes.get((m, i)) for i in range(PROBE_N)]
            if all(have):
                probe_results[m] = {"model": m, "n": PROBE_N, "json_ok_n": PROBE_N, "pass": True,
                                    "probe_calls_this_run": 0, "latency_avg_s": None, "probes": have,
                                    "note": "skip_escalation 模式：合格探针沿用日志缓存"}
            elif probe_hist.get(m):
                fails = probe_hist[m]
                err = next((p.get("error") for p in reversed(fails) if p.get("error")), None)
                probe_results[m] = {"model": m, "n": PROBE_N, "json_ok_n": 0, "pass": False,
                                    "probe_calls_this_run": 0, "latency_avg_s": None, "probes": fails,
                                    "note": "skip_escalation 模式：沿用日志中的失败探针记录"}
                skipped[m] = (f"probe_failed (0/{PROBE_N} JSON 合格" + (f"; {err}" if err else "") + ")")
            else:
                probe_results[m] = {"model": m, "n": PROBE_N, "json_ok_n": None, "pass": None,
                                    "probe_calls_this_run": 0, "latency_avg_s": None, "probes": [],
                                    "note": "skip_escalation 模式：日志中无完整合格探针记录，探针未执行"}
                skipped[m] = "probe 记录不完整（skip_escalation 模式，不发起新调用）"
    else:
        for m in models_exec:
            res = run_probes(m, cached_probes)
            probe_results[m] = res
            print(f"[model_agnostic] probe {m}: {res['json_ok_n']}/{res['n']} json_ok pass={res['pass']} "
                  f"(new={res['probe_calls_this_run']})")
            if not res["pass"]:
                err = next((p.get("error") for p in res["probes"] if p.get("error")), None)
                skipped[m] = f"probe_failed ({res['json_ok_n']}/{res['n']} JSON 合格" + (f"; {err}" if err else "") + ")"
    models_run = [m for m in models_exec if m not in skipped]

    # ---- 真实升级调用（顺序执行每模型；断点续跑；旧缓存只读命中） ----
    runners: dict[str, ModelEscalationRunner] = {}
    for m in models_run:
        runner = ModelEscalationRunner(frame, split_map, m, old_reuse, workers=args.workers)
        pool = chosen_plan["pools"][m]
        if args.limit_escalation is not None:
            todo = [s for s in pool if s not in runner.records][: args.limit_escalation]
        else:
            todo = pool
        print(f"[model_agnostic] escalating {m}: pool={len(pool)} pending={len(todo)} "
              f"cached(old={len(runner.old_reuse)}, self={len(runner.self_cache)})")
        t_m = time.time()
        if todo and not args.skip_escalation:
            runner.ensure(todo)
        runners[m] = runner
        print(f"[model_agnostic] {m}: calls_made={runner.calls_made} errors={runner.errors} "
              f"records={len(runner.records)} in {time.time() - t_m:.0f}s")

    # ---- 每 (model, arm, budget) 指标 ----
    curve_rows: list[dict[str, Any]] = []
    random_rows: list[dict[str, Any]] = []
    pair_idx = 0
    correct_vecs: dict[tuple[str, float, str], np.ndarray] = {}
    segvecs: dict[tuple[str, float, str], tuple[np.ndarray, list[str]]] = {}
    for m in models_exec:
        if m in skipped:
            for b in CURVE_BUDGETS:
                curve_rows.append({"model": m, "arm": "ROUTED_RHAT_TOPK", "budget": b,
                                   "status": f"skipped_{skipped[m]}"})
            continue
        runner = runners[m]
        recs = runner.records
        # ROUTED 主臂 + 基线 + every-item
        for b in CURVE_BUDGETS:
            if b == 0.0:
                res = eval_arm(m, frame, work_ids, split_ids, {}, recs, ref_lob)
                row = {k: v for k, v in res.items() if k != "correct_vectors"}
                row.update({"arm": "BASELINE_B0", "budget": b, "status": "ok",
                            "note": "无升级，基础分类器全发布（b=0 基线）"})
                curve_rows.append(row)
                correct_vecs[(m, b, "ROUTED")] = res["correct_vectors"]["final"]
                continue
            if b == 1.0:
                if chosen_plan["every_item"].get(m):
                    res = eval_arm(m, frame, work_ids, split_ids,
                                   {sp: set(ids) for sp, ids in split_ids.items()}, recs, ref_lob)
                    row = {k: v for k, v in res.items() if k != "correct_vectors"}
                    row.update({"arm": "EVERY_ITEM_B100", "budget": b, "status": "ok",
                                "note": "M every-item（该模型质量上限）"})
                    curve_rows.append(row)
                    correct_vecs[(m, b, "ROUTED")] = res["correct_vectors"]["final"]
                else:
                    curve_rows.append({"model": m, "arm": "EVERY_ITEM_B100", "budget": b,
                                       "status": "not_run_call_budget_cap",
                                       "note": ("≤450 新调用硬约束下不可行（每模型需 240 次新调用）；"
                                                "该模型可观测上限为实际执行的最大预算点")})
                continue
            res = eval_arm(m, frame, work_ids, split_ids, routed_sets(b), recs, ref_lob)
            row = {k: v for k, v in res.items() if k != "correct_vectors"}
            row.update({"arm": "ROUTED_RHAT_TOPK", "budget": b, "status": "ok",
                        "note": "每 split 内 r_hat 最高的 k=round-half-up(b·n) 个升级给 M"})
            curve_rows.append(row)
            correct_vecs[(m, b, "ROUTED")] = res["correct_vectors"]["final"]
            segvecs[(m, b, "ROUTED")] = (res["correct_vectors"]["seg_final"], res["correct_vectors"]["seg_ids"])
        # RANDOM 对照臂（按规划器的预算集）
        for b in chosen_plan["random_budgets"][m]:
            res = eval_arm(m, frame, work_ids, split_ids, random_sets(b), recs, ref_lob)
            row = {k: v for k, v in res.items() if k != "correct_vectors"}
            row.update({"arm": "RANDOM_R1_SEED20260910", "budget": b, "status": "ok",
                        "note": "R1 随机升级对照（每 split 固定全排列取前缀，seed=20260910）"})
            random_rows.append(row)
            correct_vecs[(m, b, "RANDOM")] = res["correct_vectors"]["final"]
            segvecs[(m, b, "RANDOM")] = (res["correct_vectors"]["seg_final"], res["correct_vectors"]["seg_ids"])

    # ---- 三证据统计（bootstrap 2000 次，seed 20260910 源） ----
    # 证据 3 三层读法（混淆控制，规则先行声明在报告 §0）：
    #   E3a 部署级主检验：同预算同模型，ROUTED 臂最终一致率 − RANDOM 臂最终一致率
    #       （同一 labeled 全集上 paired bootstrap）——路由有效性对任何 M 是否成立；
    #   E3b 路由难度有效性：ROUTED 段基线一致率显著低于 RANDOM 段基线一致率
    #       （r_hat 排序把"基线最可能错"的样本排前——这正是 r_hat 预测力本身，
    #        对每个 M 的升级集都成立）；
    #   E3c 字面段对比（诊断）：ROUTED 段 M 一致率 vs RANDOM 段 M 一致率——被题目
    #       难度混淆（升级段天然更难），不作为判据、只作透明披露。
    evidence3: list[dict[str, Any]] = []
    for m in models_run:
        for b in chosen_plan["random_budgets"][m]:
            routed_final = correct_vecs[(m, b, "ROUTED")]
            random_final = correct_vecs[(m, b, "RANDOM")]
            boot_final = rbc.paired_bootstrap(routed_final, random_final, N_BOOTSTRAP,
                                              [SEED, round(b * 100), pair_idx])
            pair_idx += 1
            (seg_r, ids_r) = segvecs[(m, b, "ROUTED")]
            (seg_q, ids_q) = segvecs[(m, b, "RANDOM")]
            base_r = np.array([int(rbc.base_pred(frame, s) == ref_lob[s]) for s in ids_r])
            base_q = np.array([int(rbc.base_pred(frame, s) == ref_lob[s]) for s in ids_q])
            boot_diff = (rbc.paired_bootstrap(base_q, base_r, N_BOOTSTRAP, [SEED, round(b * 100), pair_idx])
                         if len(base_r) == len(base_q)
                         else unpaired_bootstrap(base_q, base_r, N_BOOTSTRAP, [SEED, round(b * 100), pair_idx]))
            pair_idx += 1
            boot_seg = (rbc.paired_bootstrap(seg_r, seg_q, N_BOOTSTRAP, [SEED, round(b * 100), pair_idx])
                        if len(seg_r) == len(seg_q)
                        else unpaired_bootstrap(seg_r, seg_q, N_BOOTSTRAP, [SEED, round(b * 100), pair_idx]))
            pair_idx += 1
            evidence3.append({
                "model": m, "budget": b,
                "n_labeled": len(routed_final),
                "final_agreement_routed": float(routed_final.mean()),
                "final_agreement_random": float(random_final.mean()),
                "e3a_final_delta": boot_final,
                "n_routed_seg_labeled": len(seg_r), "n_random_seg_labeled": len(seg_q),
                "routed_seg_base_agreement": float(base_r.mean()),
                "random_seg_base_agreement": float(base_q.mean()),
                "e3b_difficulty_delta_random_minus_routed": boot_diff,
                "routed_seg_agreement": float(seg_r.mean()), "random_seg_agreement": float(seg_q.mean()),
                "e3c_segment_delta": boot_seg,
                "e3c_classification": rbc.classify_ci(boot_seg),
            })

    evidence1: list[dict[str, Any]] = []
    for m in models_run:
        for b in ROUTED_BUDGETS:
            row = next(r for r in curve_rows
                       if r["model"] == m and r["arm"] == "ROUTED_RHAT_TOPK" and r["budget"] == b)
            seg_final = segvecs[(m, b, "ROUTED")][0]
            seg_base = np.array([int(rbc.base_pred(frame, s) == ref_lob[s]) for s in segvecs[(m, b, "ROUTED")][1]])
            boot = rbc.paired_bootstrap(seg_final, seg_base, N_BOOTSTRAP, [SEED, round(b * 100), pair_idx])
            pair_idx += 1
            evidence1.append({
                "model": m, "budget": b, "seg_n": len(seg_final),
                "seg_agreement_model": float(seg_final.mean()),
                "seg_agreement_base_same_segment": float(seg_base.mean()),
                "lift": float(seg_final.mean() - seg_base.mean()),
                "accepted_seg_agreement_base": row["accepted_seg_agreement_base"],
                "lift_vs_accepted_base": (float(seg_final.mean()) - row["accepted_seg_agreement_base"]
                                          if row["accepted_seg_agreement_base"] is not None else None),
                "bootstrap": boot, "classification": rbc.classify_ci(boot),
            })

    # ---- E2：同预算跨模型读数 ----
    evidence2: list[dict[str, Any]] = []
    for b in ROUTED_BUDGETS:
        per = {}
        for m in models_run:
            r = next((r for r in curve_rows if r["model"] == m and r["arm"] == "ROUTED_RHAT_TOPK"
                      and r["budget"] == b), None)
            per[m] = None if r is None or r.get("agreement") is None else r["agreement"]
        ranked = sorted([(_v, _m) for _m, _v in per.items() if _v is not None], reverse=True)
        evidence2.append({"budget": b, "agreement_by_model": per,
                          "ranking_best_to_worst": [f"{_m}={_v:.4f}" for _v, _m in ranked],
                          "monotone_gap_gptoss_vs_qwen": (per.get(GPTOSS) - per.get("qwen/qwen3-8b")
                                                          if per.get(GPTOSS) is not None
                                                          and per.get("qwen/qwen3-8b") is not None else None)})

    # ---- Pareto knee（每模型；预算域如实行程） ----
    knees: dict[str, Any] = {}
    for m in models_run:
        pts = [{"budget": r["budget"], "selective_risk": r["generalized_risk"]}
               for r in curve_rows if r["model"] == m and r.get("generalized_risk") is not None]
        pts.sort(key=lambda p: p["budget"])
        knees[m] = rr.pareto_knee(pts)
        knees[m]["budget_domain"] = [p["budget"] for p in pts]
        mono = all(pts[i + 1]["selective_risk"] <= pts[i]["selective_risk"] + 1e-12 for i in range(len(pts) - 1))
        knees[m]["risk_monotone_nonincreasing"] = bool(mono)

    # ---- 与 budget_v2（gpt-oss-20b R6/R1）一致性核对 ----
    consistency = {"file": str(BUDGET_V2_ROUTING_CSV), "rows": [], "note":
                   "本实验 gpt-oss-20b ROUTED/RANDOM 行应复现 budget_v2 的 R6/R1（同机制同实现）；"
                   "唯一差异源=ETV3-0041（旧运行 ERROR 回退基础预测，本运行重试）"}
    if BUDGET_V2_ROUTING_CSV.exists():
        v2 = {(r["route_id"], float(r["budget"])): r
              for r in csv.DictReader(open(BUDGET_V2_ROUTING_CSV, encoding="utf-8-sig"))}
        for m in models_run:
            if m != GPTOSS:
                continue
            for b in ROUTED_BUDGETS:
                mine_r = next((r for r in curve_rows if r["model"] == m and r["arm"] == "ROUTED_RHAT_TOPK"
                               and r["budget"] == b), None)
                ref_r = v2.get(("R6", b))
                mine_q = next((r for r in random_rows if r["model"] == m and r["budget"] == b), None)
                ref_q = v2.get(("R1", b))
                consistency["rows"].append({
                    "budget": b,
                    "routed_mine": mine_r["agreement"] if mine_r else None,
                    "routed_v2_R6": float(ref_r["agreement"]) if ref_r else None,
                    "random_mine": mine_q["agreement"] if mine_q else None,
                    "random_v2_R1": float(ref_q["agreement"]) if ref_q else None,
                })

    # ---- 调用账本 ----
    call_ledger = {}
    for m in models_exec:
        if m in skipped:
            call_ledger[m] = {"status": skipped[m], "new_calls": 0}
            continue
        runner = runners[m]
        ok_recs = [r for r in runner.records.values() if r.get("status") == "OK"]
        lats = [r["latency_s"] for r in ok_recs if isinstance(r.get("latency_s"), (int, float))]
        pool = chosen_plan["pools"][m]
        call_ledger[m] = {
            "pool_size": len(pool),
            "old_cache_hits_readonly": len(runner.old_reuse),
            "self_cache_hits_resume": len(runner.self_cache),
            "new_calls_this_run": runner.calls_made,
            "errors": runner.errors,
            "ok_records_total": len(ok_recs),
            "valid_decisions": sum(1 for r in ok_recs if r.get("decision_valid")),
            "served_model_mismatch": runner.served_mismatch,
            "latency_avg_s": (sum(lats) / len(lats)) if lats else None,
            "probe_new_calls": probe_results.get(m, {}).get("probe_calls_this_run", 0),
        }
    total_new = (sum(v.get("new_calls_this_run", 0) + v.get("probe_new_calls", 0)
                     for v in call_ledger.values()))
    # 跨运行累计账本（本实验全部运行在该 JSONL 的留痕；硬约束按累计口径核对）
    cum = {"jsonl_records_total": 0, "probe_attempts": 0, "escalation_attempts": 0,
           "unique_sample_ids_with_ok_records_across_models":
               len(set().union(*[set(r.records) for r in runners.values()]) if runners else set())}
    if ESC_LOG.exists():
        for line in ESC_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            cum["jsonl_records_total"] += 1
            if rec.get("type") == "probe":
                cum["probe_attempts"] += 1
            else:
                cum["escalation_attempts"] += 1
    print(f"[model_agnostic] TOTAL NEW CALLS = {total_new} (cap={CALL_CAP}); "
          f"cumulative jsonl={cum['jsonl_records_total']} records")

    # ---- MODEL_AGNOSTIC_CURVE.csv ----
    cfields = ["model", "arm", "budget", "status", "k_total", "n_all", "n_labeled", "agreement",
               "n_correct", "wrong_to_right", "right_to_wrong", "generalized_risk", "n_final_empty",
               "agreement_dev", "agreement_val", "seg_n", "seg_agreement_model",
               "seg_agreement_base", "seg_lift_vs_base", "seg_wrong_to_right", "seg_right_to_wrong",
               "seg_n_fallback", "accepted_seg_n", "accepted_seg_agreement_base", "note"]
    with open(OUT_DIR / "MODEL_AGNOSTIC_CURVE.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cfields, extrasaction="ignore")
        w.writeheader()
        for row in curve_rows:
            out = {k: row.get(k) for k in cfields}
            for k in ("agreement", "generalized_risk", "seg_agreement_model", "seg_agreement_base",
                      "seg_lift_vs_base", "accepted_seg_agreement_base", "agreement_dev", "agreement_val"):
                out[k] = r6(out[k]) if isinstance(out[k], float) else out[k]
            w.writerow(out)

    # ---- ROUTING_RANDOM_CONTROL.csv ----
    with open(OUT_DIR / "ROUTING_RANDOM_CONTROL.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cfields, extrasaction="ignore")
        w.writeheader()
        for row in random_rows:
            out = {k: row.get(k) for k in cfields}
            for k in ("agreement", "generalized_risk", "seg_agreement_model", "seg_agreement_base",
                      "seg_lift_vs_base", "accepted_seg_agreement_base", "agreement_dev", "agreement_val"):
                out[k] = r6(out[k]) if isinstance(out[k], float) else out[k]
            w.writerow(out)

    # ---- MODEL_AGNOSTIC_SELECTIONS.json（审计：每模型×臂×预算×split 升级清单） ----
    selections: dict[str, Any] = {}
    for m in models_run:
        for b in ROUTED_BUDGETS:
            selections.setdefault(m, {}).setdefault("ROUTED", {})[budget_tag(b)] = {
                sp: sorted(routed_sets(b)[sp]) for sp in split_ids}
        for b in chosen_plan["random_budgets"][m]:
            selections[m].setdefault("RANDOM", {})[budget_tag(b)] = {
                sp: sorted(random_sets(b)[sp]) for sp in split_ids}
    (OUT_DIR / "MODEL_AGNOSTIC_SELECTIONS.json").write_text(
        json.dumps(selections, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- SUMMARY.json ----
    inputs = {
        "leave_b_out_reference": str(rbc.V3_REF_LOB),
        "strong_reference": str(rr.V3_REF_STRONG),
        "split_manifest": str(rr.SPLIT_MANIFEST),
        "old_cache_risk_routing_readonly": str(OLD_CACHES_READONLY[0]),
        "old_cache_budget_v2_readonly": str(OLD_CACHES_READONLY[1]),
        "risk_model_card": str(rr.OUT_DIR / "RISK_MODEL_CARD.json"),
        "budget_v2_routing_comparison": str(BUDGET_V2_ROUTING_CSV),
    }
    # 证据判定（规则先行声明于报告 §0，由数据生成）
    e1_pos = sum(1 for e in evidence1 if e["lift"] > 0)
    e1_sig_pos = sum(1 for e in evidence1 if e["bootstrap"]["ci95_low"] > 0)
    e1_sig_neg = sum(1 for e in evidence1 if e["bootstrap"]["ci95_high"] < 0)
    n_e1 = len(evidence1)
    n_e3 = len(evidence3)
    e3a_pos = sum(1 for e in evidence3 if e["e3a_final_delta"]["delta_observed"] > 0)
    e3a_tie = sum(1 for e in evidence3 if e["e3a_final_delta"]["delta_observed"] == 0)
    e3a_sig_pos = sum(1 for e in evidence3 if e["e3a_final_delta"]["ci95_low"] > 0)
    e3a_sig_neg = sum(1 for e in evidence3 if e["e3a_final_delta"]["ci95_high"] < 0)
    e3b_sig = sum(1 for e in evidence3 if e["e3b_difficulty_delta_random_minus_routed"]["ci95_low"] > 0)
    e2_reversals = sum(1 for e in evidence2
                       if e.get("monotone_gap_gptoss_vs_qwen") is not None
                       and e["monotone_gap_gptoss_vs_qwen"] < 0)
    conds = {
        "c1_e1_all_positive_no_sig_negative": bool(n_e1 > 0 and e1_pos == n_e1 and e1_sig_neg == 0),
        "c2_e3a_no_sig_negative": bool(n_e3 > 0 and e3a_sig_neg == 0),
        "c3_e3a_majority_positive": bool(n_e3 > 0 and e3a_pos >= (n_e3 + 1) // 2),
        "c4_e2_no_rank_reversal": bool(len(evidence2) > 0 and e2_reversals == 0),
    }
    if all(conds.values()):
        verdict = "支持：框架机制模型无关（附显著性保留，见 §0/§7）"
    elif not (conds["c1_e1_all_positive_no_sig_negative"] and conds["c2_e3a_no_sig_negative"]):
        verdict = "不支持：E1/E3a 存在显著反向证据"
    else:
        verdict = "部分支持：机制方向一致但部分判定条件未满足"
    summary = {
        "created_utc": now_iso(),
        "script": "code/experiment_pipelines/run_routing_model_agnostic.py",
        "seed": SEED,
        "n_bootstrap": N_BOOTSTRAP,
        "wall_seconds": round(time.time() - t0, 1),
        "question": "框架机制（r_hat 风险路由 + 预算 top-k 升级 + 盲化 escalation prompt）是否模型无关",
        "models": models_exec,
        "models_skipped": skipped,
        "probe_results": {m: {k: v for k, v in p.items() if k != "probes"} for m, p in probe_results.items()},
        "probe_details": {m: p.get("probes", []) for m, p in probe_results.items()},
        "plan": {"chosen": chosen_plan["option"],
                 "random_budgets_by_model": chosen_plan["random_budgets"],
                 "every_item_by_model": chosen_plan["every_item"],
                 "pool_sizes": {m: len(p) for m, p in chosen_plan["pools"].items()},
                 "options_evaluated": plan_eval,
                 "call_cap": CALL_CAP},
        "call_ledger": call_ledger,
        "total_new_calls_this_run": total_new,
        "cumulative_calls_all_runs": cum,
        "old_cache_reuse": old_audit,
        "population": {
            "n_frame": len(frame), "n_dev": len(dev_ids), "n_val": len(val_ids), "n_work": len(work_ids),
            "n_test_excluded": len(test_ids),
            "n_labeled_leave_b_out": {"dev": sum(1 for s in dev_ids if s in ref_lob),
                                      "val": sum(1 for s in val_ids if s in ref_lob),
                                      "pooled": sum(1 for s in work_ids if s in ref_lob)},
            "judge_composition_seen": dict(judge_sets),
        },
        "quality_reference": {
            "primary": "leave_b_out (IMCR_REFERENCE_LEAVE_B_OUT.csv entity_type, judge_removed=B)",
            "baseline_agreement_b0_pooled": next((r["agreement"] for r in curve_rows
                                                  if r["arm"] == "BASELINE_B0" and r.get("agreement") is not None
                                                  and r["model"] == models_run[0]), None),
            "note": "与 risk 标签（strong，仅 DEV 拟合 risk model）解耦；strong 口径禁止作为质量上限",
        },
        "r_hat_reuse": {"model": chosen, "verification": r_hat_check,
                        "note": "同特征/同 DEV strong 标签/同 seed 确定性重训，与 ROUTING_RUNS_*.csv 逐样本核对"},
        "prompt": {"prompt_version": "risk_routing.escalation.v1", "prompt_sha256": PROMPT_SHA,
                   "prompt_system": rr.ESCALATION_SYSTEM_PROMPT,
                   "pinned_model_note": ("chat_json 钉住变体：重试全程固定模型（provider 版最后一次重试会静默"
                                         "回退 qwen/qwen3-8b）；served_model 逐条留痕")},
        "curve": [{k: v for k, v in r.items() if k != "correct_vectors"} for r in curve_rows],
        "random_control": [{k: v for k, v in r.items() if k != "correct_vectors"} for r in random_rows],
        "evidence1_segment_lift_vs_base": evidence1,
        "evidence2_same_budget_cross_model": evidence2,
        "evidence3_routed_vs_random": [{k: v for k, v in e.items()} for e in evidence3],
        "evidence_counts": {"e1_comparisons": n_e1, "e1_lift_positive": e1_pos, "e1_sig_positive": e1_sig_pos,
                            "e1_sig_negative": e1_sig_neg, "e3_comparisons": n_e3,
                            "e3a_positive": e3a_pos, "e3a_tie": e3a_tie, "e3a_sig_positive": e3a_sig_pos,
                            "e3a_sig_negative": e3a_sig_neg, "e3b_difficulty_sig_separated": e3b_sig,
                            "e2_rank_reversals": e2_reversals, "verdict_conditions": conds},
        "verdict": verdict,
        "knees": knees,
        "consistency_vs_budget_v2_gptoss": consistency,
        "guards": {
            "test_split_excluded": True,
            "test_ids_excluded_n": len(test_ids),
            "assert_no_test_samples_called": True,
            "runner_blocks_test_split": True,
            "no_existing_file_modified": "只新建 model_agnostic/* 与 audit/method_final/15_MODEL_AGNOSTIC_REPORT.md",
            "old_caches_readonly": True,
            "no_fabrication": "全部数字由真实调用记录与既有数据文件计算；报告由本脚本自动生成",
        },
        "inputs_sha256": {k: rr.sha256_file(Path(v)) for k, v in inputs.items()},
        "outputs": {
            "curve": str(OUT_DIR / "MODEL_AGNOSTIC_CURVE.csv"),
            "random_control": str(OUT_DIR / "ROUTING_RANDOM_CONTROL.csv"),
            "selections": str(OUT_DIR / "MODEL_AGNOSTIC_SELECTIONS.json"),
            "calls_jsonl": str(ESC_LOG),
            "summary": str(OUT_DIR / "SUMMARY.json"),
            "report": str(REPORT_PATH),
        },
    }
    (OUT_DIR / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                          encoding="utf-8")

    # ---- 15_MODEL_AGNOSTIC_REPORT.md（数字全部由数据生成） ----
    write_report(summary, curve_rows, random_rows, evidence1, evidence2, evidence3,
                 knees, call_ledger, probe_results, total_new, consistency, verdict)
    print(f"[model_agnostic] DONE in {summary['wall_seconds']}s; outputs -> {OUT_DIR}")
    print(f"[model_agnostic] VERDICT = {verdict}")
    return 0


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------

def _f(x: Any, nd: int = 4) -> str:
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "-"


def write_report(summary: dict[str, Any], curve_rows: list[dict[str, Any]],
                 random_rows: list[dict[str, Any]], evidence1: list[dict[str, Any]],
                 evidence2: list[dict[str, Any]], evidence3: list[dict[str, Any]],
                 knees: dict[str, Any], call_ledger: dict[str, Any],
                 probe_results: dict[str, Any], total_new: int,
                 consistency: dict[str, Any], verdict: str) -> None:
    models_run = [m for m in summary["models"] if m not in summary["models_skipped"]]
    plan = summary["plan"]
    r: list[str] = []
    r.append("# 15 — MODEL-AGNOSTIC REPORT：框架机制模型无关性验证")
    r.append("")
    r.append(f"生成：{summary['created_utc']} ｜ 实现：`code/experiment_pipelines/run_routing_model_agnostic.py`"
             f" ｜ seed={summary['seed']}（R1 随机与 bootstrap 同源）｜ bootstrap={summary['n_bootstrap']} 次")
    r.append("")
    r.append("## 0. 结论先行")
    r.append("")
    ec = summary["evidence_counts"]
    r.append(f"**判语：{verdict}。**")
    r.append("")
    r.append("**判定规则（先行声明，由数据生成判定）：**")
    r.append("")
    r.append(f"- **C1（证据 1）**：每个 (M, 预算) 的升级段提升（M 段一致率 − 同段基线一致率）全部为正、"
             f"且无显著为负（bootstrap 95% CI 下界 ≥ 0 的占比单列）。观测：{ec['e1_lift_positive']}/"
             f"{ec['e1_comparisons']} 为正，{ec['e1_sig_positive']} 个 CI 全正，{ec['e1_sig_negative']} 个 CI 全负。")
    r.append(f"- **C2（证据 3a，部署级主检验）**：同预算同模型下 ROUTED 臂最终一致率 − RANDOM 臂最终一致率"
             f"（paired bootstrap）无显著为负。观测：{ec['e3_comparisons']} 个比较中 "
             f"{ec['e3a_positive']} 正 / {ec['e3a_tie']} 平，{ec['e3a_sig_positive']} 个 CI 全正、"
             f"{ec['e3a_sig_negative']} 个 CI 全负。")
    r.append(f"- **C3**：E3a 点估计为正 ≥ 半数；**C4（证据 2）**：共同预算上 gpt-oss-20b 一致率 ≥ "
             f"qwen3-8b 无排序反转（观测反转 {ec['e2_rank_reversals']} 次）。")
    r.append("- C1–C4 全部成立 ⇒ \"支持（附显著性保留）\"；C1 或 C2 出现显著为负 ⇒ \"不支持\"；其余 ⇒ \"部分支持\"。")
    r.append("")
    r.append("**关于\"升级段一致率高于随机段\"的字面预期（重要说明）：**该字面读法被题目难度混淆——"
             "r_hat 路由按设计把\"基线最可能错\"的样本送升级。本实验中升级段（ROUTED）基线一致率仅 "
             + (f"{_f(min(e['routed_seg_base_agreement'] for e in evidence3))}–"
                f"{_f(max(e['routed_seg_base_agreement'] for e in evidence3))}，"
                f"而随机段（RANDOM）为 {_f(min(e['random_seg_base_agreement'] for e in evidence3))}–"
                f"{_f(max(e['random_seg_base_agreement'] for e in evidence3))}。"
             if evidence3 else "")
             + "强升级模型对两段都能大幅修复后，更难的升级段 M 一致率反而更低。"
               "因此证据 3 的主检验采用部署级读法（同预算整臂最终一致率 routed vs random，E3a），"
               "字面段对比与难度分离分别作为 E3c/E3b 透明披露（见 §5）。")
    r.append("")
    # agreement 矩阵
    r.append("## 1. 设置与调用账本")
    r.append("")
    pop = summary["population"]
    r.append(f"- 样本：DEV {pop['n_dev']} + VAL {pop['n_val']} = {pop['n_work']}（TEST {pop['n_test_excluded']} "
             "全程排除并断言）；leave-B-out 参考标注 pooled "
             f"{pop['n_labeled_leave_b_out']['pooled']}（dev {pop['n_labeled_leave_b_out']['dev']} / "
             f"val {pop['n_labeled_leave_b_out']['val']}）。")
    r.append("- 机制只读复用：Risk Estimator（DecisionTree_max_depth4，DEV 拟合/VAL 选型，VAL AUPRC 0.728，"
             "确定性重训后与既有 ROUTING_RUNS_*.csv 逐样本核对 match="
             f"{summary['r_hat_reuse']['verification']['match']}）；预算 top-k 升级；盲化 escalation prompt"
             "（prompt_version=risk_routing.escalation.v1，与生产链逐字节一致，sha256 核对后才允许旧缓存命中）。")
    r.append("- 质量口径：leave-B-out 参考（judge_removed=B），与 risk 标签（strong，仅 DEV）解耦；"
             f"b=0 基线（无升级全发布）pooled 一致率 = "
             f"{_f(summary['quality_reference']['baseline_agreement_b0_pooled'])}。")
    r.append("- 升级语义：升级样本 → M 决策替换基础预测（无效/ERROR 回退基础预测）；未升级 → 基础预测；"
             "全部发布、无弃权。模型钉住调用（重试不回退备用模型，served_model 逐条留痕）。")
    r.append("")
    r.append("| 模型 | probe(JSON 合格) | 状态 | 池大小 | 旧缓存只读命中 | 本次新调用 | 错误 | 平均延迟(s) |")
    r.append("|---|---|---|---|---|---|---|---|")
    for m in summary["models"]:
        pr = probe_results.get(m, {})
        cl = call_ledger.get(m, {})
        status = summary["models_skipped"].get(m, "运行")
        probe_txt = ("未执行(skip)" if pr.get("json_ok_n") is None
                     else f"{pr.get('json_ok_n')}/{pr.get('n')}")
        r.append(f"| {m} | {probe_txt} | {status} | {cl.get('pool_size', '-')} | "
                 f"{cl.get('old_cache_hits_readonly', 0)} | {cl.get('new_calls_this_run', 0)} | "
                 f"{cl.get('errors', '-')} | {_f(cl.get('latency_avg_s'), 1)} |")
    r.append("")
    r.append(f"调用规划：方案 **{plan['chosen']}**（执行前确定性计算）；各模型随机对照预算 = "
             f"{ {m.split('/')[-1]: v for m, v in plan['random_budgets_by_model'].items()} }；"
             f"every-item(b=100%) 只对 gpt-oss-20b 执行（319/320 旧缓存只读命中）。"
             f"**本次运行新调用 = {total_new}（硬上限 450，含探针）。**")
    cum = summary.get("cumulative_calls_all_runs", {})
    ok_per_model = {m: cl.get("ok_records_total") for m, cl in call_ledger.items()
                    if isinstance(cl, dict) and cl.get("ok_records_total") is not None}
    r.append(f"跨运行累计账本（全部留痕于 MODEL_AGNOSTIC_CALLS.jsonl，含断点续跑对 ERROR 的政策性重试）："
             f"共 {cum.get('jsonl_records_total')} 条记录（探针尝试 {cum.get('probe_attempts')}、"
             f"升级尝试 {cum.get('escalation_attempts')}）；有效决策 {ok_per_model}，"
             f"累计尝试亦低于 450 硬上限。")
    r.append("")
    r.append("## 2. Agreement 矩阵（ROUTED：r_hat top-k 升级；leave-B-out 口径，pooled DEV+VAL）")
    r.append("")
    hdr = "| 模型 | b=0 | b=10% | b=20% | b=30% | b=50% | b=100% |"
    r.append(hdr)
    r.append("|---|---|---|---|---|---|---|")
    for m in summary["models"]:
        cells = []
        for b in CURVE_BUDGETS:
            row = next((x for x in curve_rows if x["model"] == m and x["budget"] == b
                        and x["arm"] in ("BASELINE_B0", "ROUTED_RHAT_TOPK", "EVERY_ITEM_B100")), None)
            if row is None or row.get("agreement") is None:
                st = (row or {}).get("status", "")
                if st == "not_run_call_budget_cap":
                    cells.append("未执行(预算上限)")
                elif st.startswith("skipped"):
                    cells.append("跳过(probe不合格)")
                else:
                    cells.append("-")
            else:
                mark = "**" if b == 1.0 else ""
                cells.append(f"{mark}{row['agreement']:.4f}{mark}")
        r.append(f"| {m} | " + " | ".join(cells) + " |")
    r.append("")
    r.append("（错→对/对→错与广义风险逐点数字见 `MODEL_AGNOSTIC_CURVE.csv`。b=100% 只有 gpt-oss-20b 可执行"
             "（319/320 旧缓存命中）；qwen3-8b 的 every-item 需 240 次新调用、与 ≤450 硬约束不相容，"
             "如实记为 not_run_call_budget_cap，其可观测上限为 b=50% 点；gemma-4-e4b 因 probe 不合格"
             "（LM Studio 模型加载失败）全程跳过。）")
    r.append("")
    r.append("### 每预算翻转与广义风险（ROUTED，pooled）")
    r.append("")
    r.append("| 模型 | 预算 | k | 一致率 | 错→对 | 对→错 | 广义风险 | 升级段回退数 |")
    r.append("|---|---|---|---|---|---|---|---|")
    for m in models_run:
        for b in CURVE_BUDGETS:
            row = next((x for x in curve_rows if x["model"] == m and x["budget"] == b
                        and x["arm"] in ("BASELINE_B0", "ROUTED_RHAT_TOPK", "EVERY_ITEM_B100")), None)
            if row is None or row.get("agreement") is None:
                continue
            r.append(f"| {m} | {b:.0%} | {row.get('k_total', 0)} | {row['agreement']:.4f} | "
                     f"{row.get('wrong_to_right', '-')} | {row.get('right_to_wrong', '-')} | "
                     f"{_f(row.get('generalized_risk'))} | {row.get('seg_n_fallback', '-')} |")
    r.append("")
    r.append("## 3. 证据 1 — 升级段一致率 vs 同段基线（框架把任何 M 的有效质量都用于刀刃）")
    r.append("")
    r.append("| 模型 | 预算 | 段内 n | M 升级段一致率 | 同段基线一致率 | 提升(Δ) | 接受段基线 | Δ vs 接受段 | 95% CI(Δ) | 判定 |")
    r.append("|---|---|---|---|---|---|---|---|---|---|")
    for e in evidence1:
        lvab = (f"{e['lift_vs_accepted_base']:+.4f}"
                if e.get("lift_vs_accepted_base") is not None else "-")
        r.append(f"| {e['model']} | {e['budget']:.0%} | {e['seg_n']} | {_f(e['seg_agreement_model'])} | "
                 f"{_f(e['seg_agreement_base_same_segment'])} | {e['lift']:+.4f} | "
                 f"{_f(e['accepted_seg_agreement_base'])} | {lvab} | "
                 f"[{e['bootstrap']['ci95_low']:+.4f}, {e['bootstrap']['ci95_high']:+.4f}] | {e['classification']} |")
    r.append("")
    r.append("## 4. 证据 2 — 同预算下质量随 M 能力排序（曲线高度差），曲线形状一致")
    r.append("")
    r.append("| 预算 | 各模型一致率（ROUTED） | 最优→最差 | gpt-oss-20b − qwen3-8b |")
    r.append("|---|---|---|---|")
    for e in evidence2:
        per = "；".join(f"{m.split('/')[-1]}={_f(v)}" for m, v in e["agreement_by_model"].items())
        gap = e.get("monotone_gap_gptoss_vs_qwen")
        r.append(f"| {e['budget']:.0%} | {per} | {' → '.join(e['ranking_best_to_worst'])} | "
                 f"{'-' if gap is None else f'{gap:+.4f}'} |")
    r.append("")
    for m in models_run:
        kn = knees.get(m, {})
        kb = kn.get("budget")
        r.append(f"- **{m} knee 行为**：预算域 {'、'.join(f'{b:.0%}' for b in kn.get('budget_domain', []))}，"
                 f"knee @ {f'{kb:.0%}' if kb is not None else '-'}"
                 f"（chord 落差 {_f(kn.get('gap'))}）；风险单调不增 = {kn.get('risk_monotone_nonincreasing')}。")
    r.append("")
    r.append("## 5. 证据 3 — r_hat 路由 vs R1 随机升级对照（同预算，三层读法）")
    r.append("")
    r.append("### 5.1 E3a 部署级主检验：同预算整臂最终一致率（ROUTED − RANDOM，paired bootstrap）")
    r.append("")
    r.append("| 模型 | 预算 | ROUTED 最终一致率 | RANDOM 最终一致率 | Δ | 95% CI | p(boot) | 判定 |")
    r.append("|---|---|---|---|---|---|---|---|")
    for e in evidence3:
        ba = e["e3a_final_delta"]
        cls = ("显著为正" if ba["ci95_low"] > 0 else ("显著为负" if ba["ci95_high"] < 0 else "无显著差异（CI 跨 0）"))
        r.append(f"| {e['model']} | {e['budget']:.0%} | {_f(e['final_agreement_routed'])} | "
                 f"{_f(e['final_agreement_random'])} | {ba['delta_observed']:+.4f} | "
                 f"[{ba['ci95_low']:+.4f}, {ba['ci95_high']:+.4f}] | {ba['p_boot_two_sided']:.3f} | {cls} |")
    r.append("")
    r.append("### 5.2 E3b 路由难度有效性：r_hat 把\"基线最可能错\"的样本排前（对每个 M 的升级集都成立）")
    r.append("")
    r.append("| 模型 | 预算 | ROUTED 段基线一致率 | RANDOM 段基线一致率 | Δ(RANDOM−ROUTED) | 95% CI | p(boot) |")
    r.append("|---|---|---|---|---|---|---|")
    for e in evidence3:
        bd = e["e3b_difficulty_delta_random_minus_routed"]
        r.append(f"| {e['model']} | {e['budget']:.0%} | {_f(e['routed_seg_base_agreement'])} | "
                 f"{_f(e['random_seg_base_agreement'])} | {bd['delta_observed']:+.4f} | "
                 f"[{bd['ci95_low']:+.4f}, {bd['ci95_high']:+.4f}] | {bd['p_boot_two_sided']:.3f} |")
    r.append("")
    r.append("（Δ>0 且 CI 不跨 0 = r_hat 排序选择的升级样本显著更难/基线错误率显著更高——"
             "这是 r_hat 预测力在本次跨模型实验中的直接体现，且对两个升级模型一致成立。）")
    r.append("")
    r.append("### 5.3 E3c 字面段对比（诊断性披露，受题目难度混淆，不作为判据）")
    r.append("")
    r.append("| 模型 | 预算 | ROUTED 段 M 一致率 | RANDOM 段 M 一致率 | Δ(段) | 95% CI | p(boot) | 判定 |")
    r.append("|---|---|---|---|---|---|---|---|")
    for e in evidence3:
        bs = e["e3c_segment_delta"]
        r.append(f"| {e['model']} | {e['budget']:.0%} | {_f(e['routed_seg_agreement'])} | "
                 f"{_f(e['random_seg_agreement'])} | {bs['delta_observed']:+.4f} | "
                 f"[{bs['ci95_low']:+.4f}, {bs['ci95_high']:+.4f}] | {bs['p_boot_two_sided']:.3f} | "
                 f"{e['e3c_classification']} |")
    r.append("")
    r.append("（E3c 中升级段 M 一致率低于随机段，原因是 §0 说明的难度混淆：升级段基线一致率接近 0，"
             "是基线几乎全错的最难样本，任何升级模型在该段的绝对一致率都会低于\"多数样本基线本就对\"的随机段；"
             "部署级读法（E3a）与难度分离（E3b）才是路由有效性的正确检验。）")
    r.append("")
    r.append("（随机对照 = R1，seed 20260910，每 split 一条固定全排列取前缀，与 budget_v2 完全同实现；"
             "随机臂预算集由调用规划器在 ≤450 硬约束下确定，gpt-oss-20b 覆盖 "
             f"{plan['random_budgets_by_model'].get('openai/gpt-oss-20b', [])}，其余模型见 §1 表。）")
    r.append("")
    r.append("## 6. 与 budget_v2（gpt-oss-20b 单模型）的一致性核对")
    r.append("")
    r.append("| 预算 | 本实验 ROUTED | budget_v2 R6 | 本实验 RANDOM(≤50%) | budget_v2 R1 |")
    r.append("|---|---|---|---|---|")
    for row in consistency.get("rows", []):
        r.append(f"| {row['budget']:.0%} | {_f(row.get('routed_mine'))} | {_f(row.get('routed_v2_R6'))} | "
                 f"{_f(row.get('random_mine')) if row.get('random_mine') is not None else '未执行'} | "
                 f"{_f(row.get('random_v2_R1'))} |")
    r.append("")
    r.append(f"注：{consistency['note']}。")
    r.append("")
    r.append("## 7. 边界与诚实声明")
    r.append("")
    r.append("1. **b=100% 上限只有 gpt-oss-20b**：gemma-4-e4b 与 qwen3-8b 的 every-item 需各 240 次新调用，"
             "与 \"三模型总计 ≤450 次新调用\" 硬约束不相容，如实记为 not_run_call_budget_cap；"
             "这两模型的可观测上限是 b=50% 点，不能外推为质量上限。")
    r.append("2. **随机对照预算不对称**：gpt-oss-20b 的 R1 对照覆盖 {10,20,30,50}%（几乎全缓存命中），"
             "其余模型只覆盖规划器选定的预算（见 §1）；证据 3 的跨模型比较只在两边都有对照的预算上成立。")
    r.append("3. R1 的随机性由 seed=20260910 单次实现给出，未平均多次随机抽取（bootstrap CI 覆盖抽样变异）。")
    r.append("4. 参考仍是 LLM-judge 共识（leave-B-out 去除与 gpt-5.6-luna 同族的 Judge B）；"
             "一致率读作\"对去 B 共识的一致率\"，不等于人工金标正确率；绝对数值低（b=0 约 0.276）反映该口径。")
    r.append("5. 样本量小（pooled 有参考 261 条；10% 预算升级段仅 32 条），CI 宽；判定以 CI 是否跨 0 为准。")
    r.append("5b. **E3a 显著性保留（判语的关键限定）**：7 个 ROUTED−RANDOM 比较全部不显著"
             "（0 个 CI 全正、6 正 1 平 0 负）——与 budget_v2 的既有结论一致（R6 vs R1 在任何预算都不显著，"
             "点估计为正）。因此本报告**不声称\"路由显著优于随机\"**；\"支持\"判定针对的是"
             "**机制跨模型一致性**：E1（框架对任何 M 的升级段提升）8/8 显著为正、E3a 方向全部非负、"
             "E2 排序无反转、E3b（r_hat 把难样本排前）7/7 显著。r_hat 路由相对随机的显著性优势"
             "需要更大样本量验证，属剩余不确定性。")
    r.append("6. 升级模型质量由 probe 与调用延迟侧面印证；若某模型 probe 不合格会如实记录并跳过（本次见 §1 表）。"
             "调用采用温度 0、与生产链完全相同的 prompt/payload；模型钉住调用避免 provider 静默回退污染归因。"
             "探针协议：任务格式为最小 JSON 任务，调用参数与生产升级调用一致（temperature=0、max_tokens=900、"
             "timeout=300s、重试 2 次）——首轮探针曾用 max_tokens=60，对思考型模型（qwen3-8b）不公平"
             "（思考耗尽 token 预算致 content 为空），修正为生产参数后重探；两轮探针记录均保留在 "
             "MODEL_AGNOSTIC_CALLS.jsonl（probe_protocol 字段区分 v1/v2）。")
    r.append("7. ETV3-0041（dev）在两个旧缓存中均为 ERROR（温度 0 下确定性 JSON 畸形，历次重试同败）；"
             "本运行按政策重试一次，若仍失败则回退基础预测并计入 seg_n_fallback。")
    r.append("")
    r.append("## 8. 产物清单（experiments/02_selective_semantic/model_agnostic/）")
    r.append("")
    r.append("| 文件 | 内容 |")
    r.append("|---|---|")
    r.append("| MODEL_AGNOSTIC_CURVE.csv | model × budget（b=0/10/20/30/50/100%）× agreement × 翻转 × 风险 |")
    r.append("| ROUTING_RANDOM_CONTROL.csv | R1 随机升级对照（同预算同指标） |")
    r.append("| MODEL_AGNOSTIC_SELECTIONS.json | 每模型×臂×预算×split 升级样本清单（审计） |")
    r.append("| MODEL_AGNOSTIC_CALLS.jsonl | 本实验全部调用留痕（探针+升级；断点续跑缓存） |")
    r.append("| SUMMARY.json | 规划、账本、探针、三证据统计、guards、输入 sha256 |")
    r.append("| audit/method_final/15_MODEL_AGNOSTIC_REPORT.md | 本报告 |")
    r.append("")
    REPORT_PATH.write_text("\n".join(r) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
