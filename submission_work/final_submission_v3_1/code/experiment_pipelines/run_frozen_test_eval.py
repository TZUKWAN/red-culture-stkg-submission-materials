# -*- coding: utf-8 -*-
"""run_frozen_test_eval.py — 方法冻结后唯一一次 TEST 正式评价（指令 §25）。

方法已冻结（不得再根据本运行结果修改任何组件）：
  - 消融配置 config_hash = 929c6a51430b85e3（S0_production_faithful + DEV 学到的
    theta_c/theta/校准；见 experiments/02_selective_semantic/ABLATION_SUMMARY_strong_test.json）；
  - Risk Estimator = DecisionTree_max_depth4（DEV strong 标签拟合，n=166，seed 20260908，
    VAL AUPRC 0.728；见 risk_routing/RISK_MODEL_CARD.json）；
  - 三路路由（预算约束语义，与 run_risk_routing.py 各预算点逐字一致）：
      ESCALATE    = 该 split 内 r_hat 最高的前 k=round-half-up(b*n) 个样本
                    （并列按 (-r_hat, sample_id) 字典序打破；无 clf_pred → r_hat=1.0，
                    自然落入最高风险带）；
      AUTO_ACCEPT = 非升级样本中 clf_pred 存在且 r_hat <= tau_accept；
      ABSTAIN     = 其余。
    tau_accept 取冻结阈值表 risk_routing/SUMMARY.json 的 tau_accept_by_budget
    ["b030"]["val"]（VAL 上学习，0.6666666666666666）；操作预算 b=30%
    （指令 §25：升级预算 b=30% 内）。
  - 升级模型 = 本地 LM Studio openai/gpt-oss-20b（prompt risk_routing.escalation.v1，
    system prompt 与 payload 与 run_risk_routing.py 逐字一致，import 复用）。

本脚本与此前全部运行的区别（唯一性声明）：
  - TEST 至今未参与任何训练/调参/阈值学习/升级调用（此前各脚本的
    assert_no_test_samples 断言与 EscalationRunner 的 BLOCKED_TEST_SPLIT 守门）；
  - 本脚本是唯一一次允许对 TEST 样本打分与升级的正式评价；运行之后不得再根据
    其结果修改任何方法组件。

评价参考 = leave-B-out（V3 IMCR_REFERENCE_LEAVE_B_OUT.csv，judge_removed=B，
entity_type 行；主口径，与 FINAL_RISK_ROUTING_REPORT 口径更正一致）。
DEV/VAL 的同口径数字在完全相同的语义（b=30% 三路路由 + LOB 参考）下重算，
其升级决策全部只读复用既有缓存（risk_routing/ESCALATION_CALLS.jsonl 与
budget_v2/ESCALATION_CALLS.jsonl，status=OK 视为完成），不发任何新调用；
新调用只允许发生在 TEST 升级段（预计 ~19 条 <= b=30% 预算）。

输出（全部落盘于 experiments/02_selective_semantic/frozen_test/，只新建文件）：
  ESCALATION_CALLS_TEST.jsonl   TEST 升级真实调用留痕（断点续跑）
  ROUTING_RUNS_TEST.csv         TEST 逐样本路由与终判（LOB/strong 双正确列）
  ROUTING_RUNS_DEVVAL_REEVAL.csv DEV/VAL 同口径逐样本行（审计用）
  SUMMARY.json                  冻结声明、核验、三列对比表、单次运行声明
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
from lmstudio_provider import DEFAULT_MODEL, chat_json  # noqa: E402

SEL_DIR = V3_1 / "experiments" / "02_selective_semantic"
RR_SUMMARY = SEL_DIR / "risk_routing" / "SUMMARY.json"
RR_CARD = SEL_DIR / "risk_routing" / "RISK_MODEL_CARD.json"
OLD_ESC_LOG = SEL_DIR / "risk_routing" / "ESCALATION_CALLS.jsonl"      # 只读
BUDGET_V2_ESC_LOG = SEL_DIR / "budget_v2" / "ESCALATION_CALLS.jsonl"   # 只读
ABLATION_SUMMARY = SEL_DIR / "ABLATION_SUMMARY_strong_test.json"
OUT_DIR = SEL_DIR / "frozen_test"
TEST_ESC_LOG = OUT_DIR / "ESCALATION_CALLS_TEST.jsonl"

V3_REF_LOB = V3 / "experiments" / "08_independent_reference" / "IMCR_REFERENCE_LEAVE_B_OUT.csv"

# 冻结操作预算（指令 §25：升级调用预算 b=30% 内）
OP_BUDGET = 0.30
FROZEN_PROMPT_SHA = "2c67d6cd7cc629d3ec2ce43131f111b56c5367ef110c37f410d6ff4cda6ba804"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def r6(x: float | None) -> Any:
    return round(float(x), 6) if x is not None else None


def load_reference_lob() -> dict[str, str]:
    ref: dict[str, str] = {}
    for row in csv.DictReader(open(V3_REF_LOB, encoding="utf-8-sig")):
        if row["task_type"] == "entity_type" and row["reference_label"]:
            ref[row["sample_id"]] = row["reference_label"]
    return ref


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def build_readonly_cache() -> dict[str, dict[str, Any]]:
    """合并只读缓存（旧 risk_routing + budget_v2）：status=OK 优先，ERROR 仅兜底。"""
    ok: dict[str, dict[str, Any]] = {}
    err: dict[str, dict[str, Any]] = {}
    for path in (OLD_ESC_LOG, BUDGET_V2_ESC_LOG):
        for rec in load_jsonl(path):
            sid = str(rec.get("sample_id"))
            if rec.get("status") == "OK":
                ok.setdefault(sid, rec)
            elif rec.get("status") == "ERROR":
                err.setdefault(sid, rec)
    combined = dict(err)
    combined.update(ok)
    return combined


class TestEscalationRunner:
    """TEST 升级段真实调用（本脚本是唯一授权点）。

    与 rr.EscalationRunner 逐字段同构（payload/system prompt/参数/记录字段全部
    import 复用），唯一区别：这里只允许 TEST split（dev/val 的新调用被显式禁止，
    其升级决策必须来自只读缓存）。
    """

    def __init__(self, frame: dict[str, Any], log_path: Path, workers: int = 2):
        self.frame = frame
        self.log_path = log_path
        self.workers = max(1, workers)
        self.lock = threading.Lock()
        self.cache = {
            str(r.get("sample_id")): r
            for r in load_jsonl(log_path)
            if r.get("status") == "OK"
        }
        self.calls_made = 0
        self.records: dict[str, dict[str, Any]] = dict(self.cache)
        assert rr.sha256_text(rr.ESCALATION_SYSTEM_PROMPT) == FROZEN_PROMPT_SHA, (
            "escalation prompt drifted from frozen sha256"
        )

    def _append(self, rec: dict[str, Any]) -> None:
        with self.lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")

    def _call(self, sid: str, split: str) -> dict[str, Any]:
        payload = rr.escalation_payload(self.frame, sid)
        rec: dict[str, Any] = {
            "sample_id": sid,
            "split": split,
            "model": DEFAULT_MODEL,
            "prompt_version": "risk_routing.escalation.v1",
            "prompt_sha256": FROZEN_PROMPT_SHA,
            "payload_sha256": rr.sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            "started_utc": now_iso(),
            "authorization": "single frozen TEST evaluation (instruction 25)",
        }
        if split != "test":
            rec.update({"status": "BLOCKED_NON_TEST_SPLIT", "decision": None, "decision_valid": False})
            self._append(rec)
            raise AssertionError(f"fresh calls only allowed for TEST in this script; got {sid}/{split}")
        t0 = time.time()
        try:
            out = chat_json(
                [
                    {"role": "system", "content": rr.ESCALATION_SYSTEM_PROMPT},
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
                "decision_valid": decision in rr.VALID_LABELS,
                "confidence": float(conf) if isinstance(conf, (int, float)) else None,
                "reason_code": out.get("reason_code"),
                "insufficient_evidence": bool(out.get("insufficient_evidence")),
            })
        except Exception as exc:
            rec.update({"status": "ERROR", "error": str(exc)[:300], "decision_valid": False,
                        "latency_s": round(time.time() - t0, 3)})
        self._append(rec)
        return rec

    def ensure(self, todo: list[str]) -> dict[str, dict[str, Any]]:
        pending = [s for s in todo if s not in self.cache]
        if pending:
            if self.workers <= 1:
                for sid in pending:
                    rec = self._call(sid, "test")
                    self.records[sid] = rec
                    print(f"  [test-escalation] {sid} status={rec['status']} decision={rec.get('decision')}", flush=True)
            else:
                with ThreadPoolExecutor(max_workers=self.workers) as pool:
                    futs = {pool.submit(self._call, sid, "test"): sid for sid in pending}
                    for fut in as_completed(futs):
                        sid = futs[fut]
                        rec = fut.result()
                        self.records[sid] = rec
                        print(f"  [test-escalation] {sid} status={rec['status']} decision={rec.get('decision')}", flush=True)
        self.calls_made += len(pending)
        for sid in todo:
            if sid not in self.records:
                raise AssertionError(f"missing escalation record for TEST sample {sid}")
        return self.records


def route_split(
    ids: list[str],
    r_hat: dict[str, float],
    frame: dict[str, Any],
    tau_accept: float,
    budget: float,
) -> tuple[dict[str, str], set[str], float]:
    """冻结三路路由（预算约束语义，与 run_risk_routing.py 各预算点逐字一致）。

    返回 (routes, escalate_set, tau_escalate_derived)。tau_escalate =
    升级集内最小 r_hat（升级带下边界，诊断量）。
    """
    esc_set = rr.assign_budget_topk([(s, r_hat[s]) for s in ids], len(ids), budget)
    tau_escalate = min((r_hat[s] for s in esc_set), default=math.inf)
    routes: dict[str, str] = {}
    for s in ids:
        if s in esc_set:
            routes[s] = "ESCALATE"
        elif frame[s]["clf_pred"] and r_hat[s] <= tau_accept:
            routes[s] = "AUTO_ACCEPT"
        else:
            routes[s] = "ABSTAIN"
    return routes, esc_set, tau_escalate


def evaluate_split(
    ids: list[str],
    routes: dict[str, str],
    finals: dict[str, tuple[str, str, int]],
    base_correct: dict[str, int | None],
    reference: dict[str, str],
    r_hat: dict[str, float],
    feat_rows: dict[str, dict[str, float]],
    frame: dict[str, Any],
) -> dict[str, Any]:
    """同口径指标：LOB 主参考；coverage/selective accuracy/risk + 升级段 + 翻转。"""
    rows = []
    for s in ids:
        ref = reference.get(s)
        final, fsrc, _eok = finals[s]
        bc = base_correct.get(s)
        rows.append({
            "sample_id": s,
            "in_reference": bool(ref),
            "route": routes[s],
            "final_prediction": final,
            "final_correct": int(bool(final) and ref is not None and final == ref),
            "violation": int(feat_rows[s]["lexical_contradiction"]),
            "r_hat": r_hat[s],
            "base_correct": bc,
        })
    m = rr.budget_metrics(rows)
    labeled = [r for r in rows if r["in_reference"]]
    esc_lab = [r for r in labeled if r["route"] == "ESCALATE"]
    w2r = sum(1 for r in esc_lab if r["base_correct"] == 0 and r["final_correct"] == 1)
    r2w = sum(1 for r in esc_lab if r["base_correct"] == 1 and r["final_correct"] == 0)
    esc_agree = (sum(r["final_correct"] for r in esc_lab) / len(esc_lab)) if esc_lab else None
    acc_lab = [r for r in labeled if r["route"] == "AUTO_ACCEPT"]
    m.update({
        "n_escalated_labeled": len(esc_lab),
        "escalation_segment_agreement": esc_agree,
        "wrong_to_right_escalated": w2r,
        "right_to_wrong_escalated": r2w,
        "accept_segment_agreement": (
            (sum(r["final_correct"] for r in acc_lab) / len(acc_lab)) if acc_lab else None
        ),
        "n_escalated_with_base_pred": sum(1 for r in esc_lab if r["base_correct"] is not None),
    })
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2, help="TEST 升级并发数（本地 LM Studio 建议 1-2）")
    ap.add_argument("--limit-escalation", type=int, default=None, help="最多真实调用条数（冒烟用，缓存优先）")
    ap.add_argument("--skip-escalation", action="store_true", help="只用既有缓存，不发新调用（冒烟用）")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    # ---- 冻结工件读取 ----
    rr_summary = json.loads(RR_SUMMARY.read_text(encoding="utf-8"))
    card = json.loads(RR_CARD.read_text(encoding="utf-8"))
    ablation = json.loads(ABLATION_SUMMARY.read_text(encoding="utf-8"))
    tau_accept = float(rr_summary["tau_accept_by_budget"][rr.budget_to_tag(OP_BUDGET)]["val"])
    tau_escalate_frozen = rr_summary["tau_escalate_by_budget"][rr.budget_to_tag(OP_BUDGET)]["val"]
    frozen_seed = int(card["seed"])
    assert frozen_seed == rr.SEED, "seed drift between card and pipeline"
    assert rr_summary["guards"]["test_split_excluded"] is True, "frozen run must have excluded TEST"
    assert rr.budget_to_tag(OP_BUDGET) in rr_summary["tau_accept_by_budget"], "operating budget not in frozen table"

    # ---- 数据与切分 ----
    frame = rss.build_signal_frame()
    reference_strong = rss.load_reference("strong")
    reference_lob = load_reference_lob()
    split_map = rss.load_split()
    all_ids = sorted(frame)
    dev_ids = [s for s in all_ids if split_map.get(f"entity_type:{s}") == "dev"]
    val_ids = [s for s in all_ids if split_map.get(f"entity_type:{s}") == "val"]
    test_ids = [s for s in all_ids if split_map.get(f"entity_type:{s}") == "test"]
    work_ids = dev_ids + val_ids
    rr.assert_no_test_samples(train_guard_ids := dev_ids + val_ids, split_map, "fit/score path")  # 拟合路径无 TEST
    print(f"[frozen_test] frame={len(frame)} dev={len(dev_ids)} val={len(val_ids)} test={len(test_ids)}")
    print(f"[frozen_test] LOB labeled: dev={sum(1 for s in dev_ids if s in reference_lob)} "
          f"val={sum(1 for s in val_ids if s in reference_lob)} test={sum(1 for s in test_ids if s in reference_lob)}")

    # ---- 特征 + risk 模型（确定性重训，只用 DEV strong 标签） ----
    feat_rows = rr.build_feature_rows(frame)
    train_ids = [s for s in dev_ids if reference_strong.get(s) and frame[s]["clf_pred"]]
    dev_y = {s: int(frame[s]["clf_pred"] != reference_strong[s]) for s in train_ids}
    val_score_ids = [s for s in val_ids if reference_strong.get(s) and frame[s]["clf_pred"]]
    val_y = {s: int(frame[s]["clf_pred"] != reference_strong[s]) for s in val_score_ids}
    fitted = rr.train_risk_models({s: feat_rows[s] for s in train_ids}, dev_y, seed=frozen_seed)
    selection = rr.select_risk_model(fitted, {s: feat_rows[s] for s in train_ids}, dev_y,
                                     {s: feat_rows[s] for s in val_score_ids}, val_y)
    chosen = selection["chosen"]
    assert chosen == card["selection"]["chosen"] == "DecisionTree_max_depth4", "risk model drift vs frozen card"
    val_ap_new = selection["selection"][chosen]["val_auprc"]
    val_ap_card = card["selection"]["selection"][chosen]["val_auprc"]
    assert abs(val_ap_new - val_ap_card) < 1e-9, f"VAL AUPRC drift: {val_ap_new} vs card {val_ap_card}"
    assert rr.FEATURE_NAMES == card["feature_names"], "feature list drift vs frozen card"
    print(f"[frozen_test] risk model = {chosen}; VAL AUPRC = {val_ap_new:.6f} (matches card)")

    # ---- r_hat：dev/val/test 全量打分（无 clf_pred → 1.0）----
    r_hat: dict[str, float] = {}
    r_hat.update(rr.predict_risk(fitted, chosen, {s: feat_rows[s] for s in all_ids if frame[s]["clf_pred"]}))
    for s in all_ids:
        r_hat.setdefault(s, 1.0)

    # 与既有 ROUTING_RUNS_{dev,val}.csv 的 r_hat 列逐样本核对（冻结复用核验）
    ver = {"checked_files": [], "n_compared": 0, "max_abs_diff": 0.0, "match": False}
    for sp in ("dev", "val"):
        path = SEL_DIR / "risk_routing" / f"ROUTING_RUNS_{sp}.csv"
        n = 0
        for row in csv.DictReader(open(path, encoding="utf-8-sig")):
            sid = row["sample_id"]
            if sid in r_hat and row.get("r_hat"):
                ver["max_abs_diff"] = max(ver["max_abs_diff"], abs(float(row["r_hat"]) - r_hat[sid]))
                n += 1
        ver["n_compared"] += n
        ver["checked_files"].append({"path": str(path), "n_compared": n})
    ver["match"] = ver["n_compared"] > 0 and ver["max_abs_diff"] <= 1e-6
    assert ver["match"], f"r_hat reuse verification failed: {ver}"
    print(f"[frozen_test] r_hat reuse verified vs ROUTING_RUNS dev/val: n={ver['n_compared']} "
          f"max|d|={ver['max_abs_diff']:.2e}")

    # ---- 三路路由（冻结 tau_accept；操作预算 b=30%）----
    split_ids = {"dev": dev_ids, "val": val_ids, "test": test_ids}
    routes_at: dict[str, dict[str, str]] = {}
    esc_sets: dict[str, set[str]] = {}
    tau_esc_derived: dict[str, float] = {}
    for sp, ids in split_ids.items():
        routes_at[sp], esc_sets[sp], tau_esc_derived[sp] = route_split(
            ids, r_hat, frame, tau_accept, OP_BUDGET)
        print(f"[frozen_test] {sp}: n={len(ids)} k_escalate={len(esc_sets[sp])} "
              f"accept={sum(1 for v in routes_at[sp].values() if v == 'AUTO_ACCEPT')} "
              f"abstain={sum(1 for v in routes_at[sp].values() if v == 'ABSTAIN')} "
              f"tau_accept={tau_accept:.6f} tau_escalate(derived)={tau_esc_derived[sp]:.6f}")
    test_esc_ids = sorted(esc_sets["test"])
    print(f"[frozen_test] TEST escalation band: {len(test_esc_ids)} calls (budget {OP_BUDGET:.0%} "
          f"= {rr.exact_budget_count(len(test_ids), OP_BUDGET)}); LOB-labeled among them: "
          f"{sum(1 for s in test_esc_ids if s in reference_lob)}")

    # ---- 升级决策：dev/val 只读缓存；TEST 真实调用 ----
    readonly = build_readonly_cache()
    devval_needed = sorted(esc_sets["dev"] | esc_sets["val"])
    missing_devval = [s for s in devval_needed if s not in readonly]
    assert not missing_devval, f"DEV/VAL escalations missing from readonly cache: {missing_devval[:5]}"
    print(f"[frozen_test] dev/val escalations from readonly cache: {len(devval_needed)} "
          f"(OK={sum(1 for s in devval_needed if readonly[s].get('status') == 'OK')})")

    if args.skip_escalation:
        esc_records = dict(readonly)
        for s in test_esc_ids:
            if s not in esc_records:
                raise AssertionError(f"--skip-escalation but TEST {s} has no cached record")
        fresh_calls = 0
    else:
        runner = TestEscalationRunner(frame, TEST_ESC_LOG, workers=args.workers)
        todo = test_esc_ids if args.limit_escalation is None else test_esc_ids[: args.limit_escalation]
        runner.ensure(todo)
        fresh_calls = runner.calls_made
        esc_records = dict(readonly)
        esc_records.update(runner.records)
    ok_test = [esc_records[s] for s in test_esc_ids if esc_records[s].get("status") == "OK"]
    print(f"[frozen_test] fresh TEST calls={fresh_calls}; OK={len(ok_test)} "
          f"valid={sum(1 for r in ok_test if r.get('decision_valid'))}")

    # ---- 终判 + 同口径指标（LOB 主参考）----
    base_correct_strong: dict[str, int | None] = {}
    finals_at: dict[str, dict[str, tuple[str, str, int]]] = {}
    for sp, ids in split_ids.items():
        finals_at[sp] = {}
        for s in ids:
            f = frame[s]
            ref_s = reference_strong.get(s)
            base_correct_strong[s] = (
                int(f["clf_pred"] == ref_s) if (ref_s and f["clf_pred"]) else None
            )
            if routes_at[sp][s] == "ESCALATE":
                final, fsrc, eok = rr.finalize_prediction(f["clf_pred"], esc_records.get(s), "gpt-oss-20b_frozen_test")
            else:
                final, fsrc, eok = rr.finalize_prediction(f["clf_pred"], None, "none")
            finals_at[sp][s] = (final, fsrc, eok)

    metrics_lob: dict[str, dict[str, Any]] = {}
    metrics_strong_sens: dict[str, dict[str, Any]] = {}
    for sp, ids in split_ids.items():
        metrics_lob[sp] = evaluate_split(ids, routes_at[sp], finals_at[sp],
                                         {s: (int(frame[s]["clf_pred"] == reference_lob[s])
                                              if (reference_lob.get(s) and frame[s]["clf_pred"]) else None)
                                          for s in ids},
                                         reference_lob, r_hat, feat_rows, frame)
        metrics_strong_sens[sp] = evaluate_split(ids, routes_at[sp], finals_at[sp],
                                                 base_correct_strong, reference_strong,
                                                 r_hat, feat_rows, frame)

    # ---- 落盘 ----
    # ROUTING_RUNS_TEST.csv（逐样本全字段）
    test_fields = [
        "sample_id", "split", "has_clf_pred", "base_prediction", "base_pred_source",
        "r_hat", "rule_pred", "rule_conf", "clf_conf", "clf_margin",
        "production_type", "validated", "source_multiplicity", "lexical_contradiction",
        "reference_label_lob", "in_reference_lob", "base_correct_lob",
        "reference_label_strong", "in_reference_strong", "base_correct_strong",
        "tau_accept", "tau_escalate_derived", "route", "final_prediction",
        "final_source", "escalation_valid", "final_correct_lob", "final_correct_strong",
        "operating_budget", "escalation_decision", "escalation_confidence",
        "escalation_status",
    ]
    with open(OUT_DIR / "ROUTING_RUNS_TEST.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=test_fields)
        w.writeheader()
        for s in test_ids:
            f = frame[s]
            fin = finals_at["test"][s]
            erec = esc_records.get(s, {}) or {}
            ref_lob = reference_lob.get(s, "")
            ref_s = reference_strong.get(s, "")
            w.writerow({
                "sample_id": s,
                "split": "test",
                "has_clf_pred": int(bool(f["clf_pred"])),
                "base_prediction": f["clf_pred"] or "",
                "base_pred_source": "B2_frozen_classifier" if f["clf_pred"] else "none",
                "r_hat": round(r_hat[s], 6),
                "rule_pred": f["rule_pred"] or "",
                "rule_conf": f["rule_conf"] if f["rule_conf"] is not None else "",
                "clf_conf": f["clf_conf"] if f["clf_conf"] is not None else "",
                "clf_margin": f["clf_margin"] if f["clf_margin"] is not None else "",
                "production_type": f["production_type"],
                "validated": int(f["validated"]),
                "source_multiplicity": f["meta"].get("integrated_member_count", ""),
                "lexical_contradiction": int(feat_rows[s]["lexical_contradiction"]),
                "reference_label_lob": ref_lob,
                "in_reference_lob": int(bool(ref_lob)),
                "base_correct_lob": (int(f["clf_pred"] == reference_lob[s]) if ref_lob and f["clf_pred"] else ""),
                "reference_label_strong": ref_s,
                "in_reference_strong": int(bool(ref_s)),
                "base_correct_strong": base_correct_strong[s] if base_correct_strong[s] is not None else "",
                "tau_accept": round(tau_accept, 6),
                "tau_escalate_derived": round(tau_esc_derived["test"], 6),
                "route": routes_at["test"][s],
                "final_prediction": fin[0],
                "final_source": fin[1],
                "escalation_valid": fin[2],
                "final_correct_lob": int(bool(fin[0]) and ref_lob != "" and fin[0] == ref_lob),
                "final_correct_strong": int(bool(fin[0]) and ref_s != "" and fin[0] == ref_s),
                "operating_budget": OP_BUDGET,
                "escalation_decision": erec.get("decision", ""),
                "escalation_confidence": erec.get("confidence", ""),
                "escalation_status": erec.get("status", ""),
            })

    # ROUTING_RUNS_DEVVAL_REEVAL.csv（同口径审计行）
    with open(OUT_DIR / "ROUTING_RUNS_DEVVAL_REEVAL.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "sample_id", "split", "r_hat", "route", "final_prediction", "final_source",
            "escalation_valid", "reference_label_lob", "final_correct_lob",
            "escalation_record_source",
        ])
        w.writeheader()
        for sp in ("dev", "val"):
            for s in split_ids[sp]:
                fin = finals_at[sp][s]
                w.writerow({
                    "sample_id": s,
                    "split": sp,
                    "r_hat": round(r_hat[s], 6),
                    "route": routes_at[sp][s],
                    "final_prediction": fin[0],
                    "final_source": fin[1],
                    "escalation_valid": fin[2],
                    "reference_label_lob": reference_lob.get(s, ""),
                    "final_correct_lob": int(bool(fin[0]) and reference_lob.get(s, "") != "" and fin[0] == reference_lob.get(s, "")),
                    "escalation_record_source": ("readonly_cache" if s in readonly else ""),
                })

    # SUMMARY.json
    def clean(x: Any) -> Any:
        if isinstance(x, float):
            return r6(x)
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [clean(v) for v in x]
        return x

    summary = {
        "created_utc": now_iso(),
        "script": "code/experiment_pipelines/run_frozen_test_eval.py",
        "purpose": "方法冻结后唯一一次 TEST 正式评价（指令 §25）",
        "single_run_declaration": (
            "本表为方法冻结后唯一一次 TEST 评价，此前 TEST 未参与任何训练或调参；"
            "本运行之后不得再根据其结果修改任何方法组件。"
        ),
        "frozen_components": {
            "ablation_config_hash": ablation["config_hash"],
            "ablation_summary_file": str(ABLATION_SUMMARY),
            "risk_model": {
                "chosen": chosen,
                "val_auprc": val_ap_card,
                "train": "DEV strong labels, n=166, seed=20260908",
                "card": str(RR_CARD),
            },
            "tau_accept": tau_accept,
            "tau_accept_source": f"risk_routing/SUMMARY.json tau_accept_by_budget[{rr.budget_to_tag(OP_BUDGET)}][val]（VAL 学习，冻结）",
            "tau_escalate_frozen_val": tau_escalate_frozen,
            "operating_budget": OP_BUDGET,
            "routing_semantics": (
                "ESCALATE = split 内 r_hat 最高前 k=round-half-up(b*n)（并列 (-r_hat, sample_id)）；"
                "AUTO_ACCEPT = 非升级且 clf_pred 存在且 r_hat<=tau_accept；ABSTAIN = 其余；"
                "clf_pred 缺失 → r_hat=1.0，永不 AUTO_ACCEPT"
            ),
            "escalation_model": DEFAULT_MODEL,
            "escalation_prompt_version": "risk_routing.escalation.v1",
            "escalation_prompt_sha256": FROZEN_PROMPT_SHA,
            "split_manifest_sha256": sha256_file(rr.SPLIT_MANIFEST),
        },
        "verification": {
            "risk_model_matches_card": True,
            "val_auprc_matches_card": True,
            "r_hat_reuse_vs_routing_runs": ver,
            "devval_escalations_all_from_readonly_cache": True,
            "n_devval_readonly": len(devval_needed),
            "prompt_sha_matches_frozen": True,
        },
        "population": {
            "n_frame": len(frame),
            "n_dev": len(dev_ids), "n_val": len(val_ids), "n_test": len(test_ids),
            "n_lob_labeled": {sp: sum(1 for s in split_ids[sp] if s in reference_lob) for sp in split_ids},
            "n_strong_labeled": {sp: sum(1 for s in split_ids[sp] if s in reference_strong) for sp in split_ids},
            "n_no_clf_pred": {sp: sum(1 for s in split_ids[sp] if not frame[s]["clf_pred"]) for sp in split_ids},
        },
        "routing_counts": {
            sp: {
                "k_escalate": len(esc_sets[sp]),
                "auto_accept": sum(1 for v in routes_at[sp].values() if v == "AUTO_ACCEPT"),
                "abstain": sum(1 for v in routes_at[sp].values() if v == "ABSTAIN"),
                "tau_escalate_derived": r6(tau_esc_derived[sp]),
            } for sp in split_ids
        },
        "test_escalation_calls": {
            "fresh_calls_made": fresh_calls,
            "ok": len(ok_test),
            "valid_decisions": sum(1 for r in ok_test if r.get("decision_valid")),
            "invalid_decisions": sum(1 for r in ok_test if r.get("status") == "OK" and not r.get("decision_valid")),
            "errors": sum(1 for s in test_esc_ids if (esc_records.get(s) or {}).get("status") == "ERROR"),
            "log": str(TEST_ESC_LOG),
            "budget_cap": rr.exact_budget_count(len(test_ids), OP_BUDGET),
        },
        "metrics_primary_lob": clean(metrics_lob),
        "metrics_strong_sensitivity": clean(metrics_strong_sens),
        "comparison_table_lob": {
            "columns": ["metric", "dev", "val", "test"],
            "note": "同口径：b=30% 三路路由 + leave-B-out 参考；DEV/VAL 升级决策只读复用既有缓存",
            "rows": {
                k: [clean(metrics_lob["dev"][k]), clean(metrics_lob["val"][k]), clean(metrics_lob["test"][k])]
                for k in [
                    "n_all", "n_eval_labeled", "n_auto_accept", "n_escalate", "n_abstain",
                    "llm_call_rate", "coverage", "selective_accuracy", "selective_risk",
                    "generalized_risk", "aurc", "n_escalated_labeled",
                    "escalation_segment_agreement", "wrong_to_right_escalated",
                    "right_to_wrong_escalated", "accept_segment_agreement",
                ]
            },
        },
        "guards": {
            "fit_path_excludes_test": True,
            "devval_no_fresh_calls": True,
            "fresh_calls_only_test_escalation_band": True,
            "quality_reference_primary": "leave_b_out (judge_removed=B)",
            "strong_reference_role": "sensitivity only（含 Judge B，禁止作为质量上限）",
            "no_method_change_after_this_run": True,
        },
        "inputs_sha256": {
            str(p): sha256_file(p) for p in (
                RR_SUMMARY, RR_CARD, ABLATION_SUMMARY, rr.SPLIT_MANIFEST,
                V3_REF_LOB, rr.V3_REF_STRONG, rr.V3_RUNS, rr.SAMPLE, rr.SIDECAR,
                OLD_ESC_LOG, BUDGET_V2_ESC_LOG,
            )
        },
        "outputs": {
            "runs_test": str(OUT_DIR / "ROUTING_RUNS_TEST.csv"),
            "runs_devval_reeval": str(OUT_DIR / "ROUTING_RUNS_DEVVAL_REEVAL.csv"),
            "test_escalation_log": str(TEST_ESC_LOG),
            "summary": str(OUT_DIR / "SUMMARY.json"),
        },
        "wall_seconds": round(time.time() - t_start, 1),
    }
    (OUT_DIR / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # 控制台三列对比
    print("\n[frozen_test] ===== DEV / VAL / TEST same-caliber (b=30%, leave-B-out) =====")
    hdr = f"{'metric':<34}{'DEV':>12}{'VAL':>12}{'TEST':>12}"
    print(hdr)
    for k in summary["comparison_table_lob"]["rows"]:
        vals = summary["comparison_table_lob"]["rows"][k]
        fmt = lambda v: (f"{v:.4f}" if isinstance(v, float) else str(v))
        print(f"{k:<34}{fmt(vals[0]):>12}{fmt(vals[1]):>12}{fmt(vals[2]):>12}")
    print(f"\n[frozen_test] DONE in {summary['wall_seconds']}s; outputs -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
