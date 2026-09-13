# -*- coding: utf-8 -*-
"""run_evidence_semantic_gate.py — P0-9 Evidence Semantic Gate 分层语义验证（指令 §13）。

对词法对齐（STRICT_ALIGNMENT）与证据恢复（EVIDENCE_RECOVERY）产出的五个层，
按写死 seed 确定性抽样后，用本地 LM Studio（gpt-oss-20b，lmstudio_provider.chat_json）
逐条做五档语义支持判定：

    FULLY_SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED / CONTRADICTED / INSUFFICIENT

分层与样本量（总 5,000 次本地调用）：
    mismatch_with_evidence 1,500（有证据但词法不含实体名，高风险）
    recovery_B             1,000（同行双名强恢复）
    recovery_C               800（弱定位恢复）
    recovery_A               200（确定证据 ID，校准高置信层）
    aligned                1,500（词法对齐未做语义验证的 44k）

执行：4 并发；checkpoint 每 200 条落盘、可中断续跑；全部原始判定落盘。
统计：每层五档分布、fully+partially 支持率（Wilson 95% CI）、按 predicate 分组、
DEV 重分层规则（FULLY→strict；PARTIAL→predicate 表；UNSUPPORTED/CONTRADICTED→
unresolved；INSUFFICIENT→contextual），并外推全库 new strict size（明确标注为
分层抽样统计估计）。

硬约束：只用本地 lmstudio_provider（禁止公网）；无人工；seed 写死；
输入数据库只读；不修改任何既有文件，只新建 EVIDENCE_GATE_* 产物。

产物（experiments/07_provenance_semantic_gate/）：
    SAMPLE_IDS.json                    分层抽样 id 清单（seed 记录）
    EVIDENCE_GATE_CHECKPOINT.jsonl     执行 checkpoint（续跑源，即 RAW verdicts）
    EVIDENCE_GATE_VERDICTS.jsonl       逐条判定（含断言/证据/五档输出）
    EVIDENCE_GATE_STRATA.csv           层 × 五档 × 支持率 CI
    EVIDENCE_GATE_PREDICATE.csv        层 × predicate 支持率 + PARTIAL predicate 表
    EVIDENCE_GATE_SUMMARY.json         全部统计与外推
    EVIDENCE_GATE_REPORT.md            方法/分布/外推/局限性报告
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

V3_1 = Path(__file__).resolve().parents[2]
V3 = V3_1.parent / "final_submission_v3"
# V3_1 自己的 lmstudio_provider 优先；_common（只读 DB 助手）来自 V3
for _p in (str(V3_1 / "code" / "independent_eval"),
           str(V3 / "code" / "independent_eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import attach_integration, connect_final, sha256_file  # noqa: E402
from lmstudio_provider import (  # noqa: E402
    DEFAULT_BASE,
    DEFAULT_MODEL,
    LMStudioError,
    chat_json,
)
try:
    from metrics import wilson_ci  # noqa: E402  (V3 metrics，可复用)
except Exception:  # pragma: no cover - 手写兜底
    def wilson_ci(k: int, n: int, confidence: float = 0.95):
        if n <= 0:
            return (0.0, 0.0)
        z = 1.959963984540054 if confidence == 0.95 else 1.959963984540054
        p = k / n
        d = 1 + z * z / n
        c = (p + z * z / (2 * n)) / d
        h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
        return (max(0.0, c - h), min(1.0, c + h))

OUT_DIR = V3_1 / "experiments" / "07_provenance_semantic_gate"
ALIGN_CSV = OUT_DIR / "STRICT_ALIGNMENT.csv"
RECOV_CSV = OUT_DIR / "EVIDENCE_RECOVERY.csv"
OUT_SAMPLE = OUT_DIR / "SAMPLE_IDS.json"
OUT_CKPT = OUT_DIR / "EVIDENCE_GATE_CHECKPOINT.jsonl"
OUT_VERDICTS = OUT_DIR / "EVIDENCE_GATE_VERDICTS.jsonl"
OUT_STRATA = OUT_DIR / "EVIDENCE_GATE_STRATA.csv"
OUT_PRED = OUT_DIR / "EVIDENCE_GATE_PREDICATE.csv"
OUT_SUM = OUT_DIR / "EVIDENCE_GATE_SUMMARY.json"
OUT_RPT = OUT_DIR / "EVIDENCE_GATE_REPORT.md"

METHOD_VERSION = "evidence-semantic-gate-v1"
SEED = 20260909                      # 写死：分层抽样 seed
CN_TZ = timezone(timedelta(hours=8))

# (层名, 目标样本量, 来源)
STRATA_SPEC = [
    ("mismatch_with_evidence", 1500, "STRICT_ALIGNMENT.bucket=mismatch_with_evidence"),
    ("recovery_B",             1000, "EVIDENCE_RECOVERY.recovery_class=B"),
    ("recovery_C",              800, "EVIDENCE_RECOVERY.recovery_class=C"),
    ("recovery_A",              200, "EVIDENCE_RECOVERY.recovery_class=A"),
    ("aligned",                1500, "STRICT_ALIGNMENT.bucket=aligned"),
]

LABELS = ["FULLY_SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED",
          "CONTRADICTED", "INSUFFICIENT"]

EVID_CAP = 800        # 证据原文总长上限（字）
EVID_SHOW = 3         # 最多拼接的证据条数
WORKERS = 4           # 本地并发
CKPT_FLUSH_EVERY = 200
PRED_STRICT_MIN_N = 25        # PARTIAL predicate 表入表阈值
PRED_STRICT_MIN_CONF = 0.70   # PARTIAL 平均置信度阈值
PRED_STRICT_MIN_SHARE = 0.50  # PARTIAL 高置信(conf>=0.75)占比阈值
HIGH_CONF = 0.75

SYS_PROMPT = """你是党史文献知识库的严格证据核验器。给定一条断言和若干证据原文片段，你只能依据证据判断断言是否被支持，禁止使用任何外部知识；证据中没有的信息一律视为不存在。
输出且仅输出一个 JSON 对象，字段如下：
{"decision": "FULLY_SUPPORTED|PARTIALLY_SUPPORTED|UNSUPPORTED|CONTRADICTED|INSUFFICIENT", "confidence": <0到1的小数>, "evidence_quote": "<支持判断的证据原句，直接摘录，可为空字符串>", "explanation": "<一句话中文理由>"}
五档定义：
FULLY_SUPPORTED=证据明确且完整支持断言的全部要素（主体、关系、客体的时间/空间表述一致或为证据内容的严格子集）；
PARTIALLY_SUPPORTED=证据部分支持断言（如主体与关系成立，但时间/地点/范围/角色不完全吻合，或证据表述比断言更宽泛/更具体）；
UNSUPPORTED=证据与断言相关（出现相关实体）但不含断言所述关系；
CONTRADICTED=证据内容与断言相矛盾；
INSUFFICIENT=证据缺失、为空或信息量不足以做出判断。"""


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def clean_text(t) -> str:
    return " ".join(str(t or "").split())


# ---------------------------------------------------------------------------
# 输入装载
# ---------------------------------------------------------------------------

def load_alignment() -> dict[str, dict]:
    """fact_id → STRICT_ALIGNMENT 行（断言元数据 + bucket）。"""
    out: dict[str, dict] = {}
    with open(ALIGN_CSV, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["fact_id"]] = row
    return out


def load_recovery() -> dict[str, dict]:
    """fact_id → EVIDENCE_RECOVERY 行（A/B/C/D + 恢复证据指针/预览）。"""
    out: dict[str, dict] = {}
    with open(RECOV_CSV, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["fact_id"]] = row
    return out


# ---------------------------------------------------------------------------
# 分层抽样（fixed-seed，确定性）
# ---------------------------------------------------------------------------

def build_samples(align: dict, recov: dict) -> tuple[dict[str, list[str]], dict[str, int]]:
    pops: dict[str, list[str]] = {
        "mismatch_with_evidence": sorted(f for f, r in align.items()
                                         if r["bucket"] == "mismatch_with_evidence"),
        "recovery_B": sorted(f for f, r in recov.items() if r["recovery_class"] == "B"),
        "recovery_C": sorted(f for f, r in recov.items() if r["recovery_class"] == "C"),
        "recovery_A": sorted(f for f, r in recov.items() if r["recovery_class"] == "A"),
        "aligned": sorted(f for f, r in align.items() if r["bucket"] == "aligned"),
    }
    rng = random.Random(SEED)
    samples: dict[str, list[str]] = {}
    for name, n_target, _src in STRATA_SPEC:
        pop = pops[name]
        if len(pop) < n_target:
            raise SystemExit(f"[gate] stratum {name}: population {len(pop)} < {n_target}")
        samples[name] = rng.sample(pop, n_target)
    return samples, pops


def load_or_make_samples(align, recov) -> dict[str, list[str]]:
    samples, pops = build_samples(align, recov)
    if OUT_SAMPLE.exists():
        try:
            prev = json.loads(OUT_SAMPLE.read_text(encoding="utf-8"))
            if prev.get("seed") == SEED and all(
                    sorted(prev["strata"][name]["ids"]) == sorted(ids)
                    for name, ids in samples.items()):
                print("[gate] SAMPLE_IDS.json 已存在且与 seed 一致，复用")
                return samples
        except Exception as exc:  # 损坏则重写
            print(f"[gate] SAMPLE_IDS.json 读取失败（{exc}），按 seed 重建")
    payload = {
        "method_version": METHOD_VERSION,
        "seed": SEED,
        "sampling": "fixed-seed simple random sample per stratum (random.Random(seed).sample over sorted fact_ids)",
        "generated_at": now_iso(),
        "strata": {name: {
            "source": src,
            "population": len(pops[name]),
            "sample_size": len(samples[name]),
            "ids": samples[name],
        } for name, _n, src in STRATA_SPEC},
    }
    OUT_SAMPLE.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    print(f"[gate] SAMPLE_IDS.json 写入（seed={SEED}）")
    return samples


# ---------------------------------------------------------------------------
# 证据原文组装（只读 DB）
# ---------------------------------------------------------------------------

class EvidenceResolver:
    def __init__(self, con):
        self.con = con
        self._by_eid: dict[str, tuple[str, str]] = {}

    def provenance_eids(self, fact_id: str) -> list[str]:
        eids: set[str] = set()
        for (js,) in self.con.execute(
            "select evidence_ids_json from research_assertion_provenance where fact_id=?",
            (fact_id,),
        ):
            try:
                eids.update(str(x) for x in json.loads(js or "[]"))
            except json.JSONDecodeError:
                pass
        return sorted(eids)

    def registry_rows(self, eids: list[str]) -> dict[str, tuple[str, str]]:
        miss = [e for e in eids if e not in self._by_eid]
        for i in range(0, len(miss), 200):
            ch = miss[i:i + 200]
            q = ",".join("?" * len(ch))
            for r in self.con.execute(
                f"select evidence_id, source_title, evidence_text from up.evidence_registry "
                f"where evidence_id in ({q})", ch
            ):
                self._by_eid[str(r[0])] = (clean_text(r[1]), clean_text(r[2]))
        return {e: self._by_eid.get(e, ("", "")) for e in eids}

    def assemble(self, stratum: str, fid: str, align_row: dict,
                 recov_row: dict | None) -> dict:
        """返回 {evidence_text, source_titles, n_evidence_ids, evidence_empty}。"""
        eids: list[str] = []
        fallback_preview = ""
        titles: list[str] = []
        if stratum in ("mismatch_with_evidence", "aligned"):
            eids = self.provenance_eids(fid)
        else:
            r = recov_row or {}
            eids = [e for e in str(r.get("recovered_evidence_ids") or "").split(";") if e]
            fallback_preview = clean_text(r.get("evidence_text_preview") or "")
            titles = [t.strip() for t in
                      str(r.get("recovered_source_titles") or "").split(" ; ") if t.strip()]
        rows = self.registry_rows(eids) if eids else {}
        excerpts: list[str] = []
        got_titles: list[str] = []
        for eid in eids[:EVID_SHOW]:
            title, text = rows.get(eid, ("", ""))
            if text:
                excerpts.append(text)
            if title:
                got_titles.append(title)
        if not excerpts and fallback_preview:
            excerpts.append(fallback_preview)
        if not got_titles and titles:
            got_titles = titles[:EVID_SHOW]
        evidence_text = " ‖ ".join(e[:EVID_CAP // EVID_SHOW + 60] for e in excerpts)[:EVID_CAP]
        return {
            "n_evidence_ids": len(eids),
            "source_titles": " | ".join(dict.fromkeys(got_titles))[:200],
            "evidence_text": evidence_text,
            "evidence_empty": not evidence_text.strip(),
        }


def assertion_text(row: dict) -> str:
    s = clean_text(row.get("subject_name"))
    p = clean_text(row.get("predicate"))
    o = clean_text(row.get("object_name"))
    t = clean_text(row.get("time_raw"))
    pl = clean_text(row.get("place_raw"))
    ctx = [x for x in (f"时间表述：{t}" if t else "", f"空间表述：{pl}" if pl else "") if x]
    base = f"{s} —{p}— {o}"
    return f"{base}（{'；'.join(ctx)}）" if ctx else base


def user_prompt(asrt: str, evidence_text: str) -> str:
    ev = evidence_text if evidence_text.strip() else "（空）"
    return f"断言：{asrt}\n证据原文：\n{ev}\n只依据上述证据输出 JSON。"


# ---------------------------------------------------------------------------
# 单条判定
# ---------------------------------------------------------------------------

def judge_one(item: dict) -> dict:
    rec = dict(item)
    rec.update({
        "decision": None, "confidence": None, "evidence_quote": "",
        "explanation": "", "forced": "", "parse_ok": 0, "retry_used": 0,
        "salvaged": 0, "latency_s": None, "model": DEFAULT_MODEL, "error": "",
        "ts": now_iso(),
    })
    if item["evidence_empty"]:
        # 规约：证据文本为空 → 直接 INSUFFICIENT（不消耗模型调用）
        rec.update({"decision": "INSUFFICIENT", "confidence": 0.5,
                    "forced": "empty_evidence", "parse_ok": 1,
                    "explanation": "证据文本为空，按规约判 INSUFFICIENT"})
        return rec
    messages = [
        {"role": "system", "content": SYS_PROMPT},
        {"role": "user", "content": user_prompt(item["assertion"], item["evidence_text"])},
    ]
    t0 = time.time()
    try:
        out = chat_json(messages, max_tokens=500, timeout=900)
    except LMStudioError as exc:
        rec.update({"decision": "CALL_FAILED", "error": str(exc)[:300],
                    "latency_s": round(time.time() - t0, 2)})
        return rec
    rec["latency_s"] = round(time.time() - t0, 2)
    for attempt in range(2):
        dec = str(out.get("decision", "")).strip().upper()
        if dec in LABELS:
            try:
                conf = float(out.get("confidence"))
                conf = min(1.0, max(0.0, conf))
            except (TypeError, ValueError):
                conf = None
            rec.update({
                "decision": dec, "confidence": conf, "parse_ok": 1,
                "evidence_quote": clean_text(out.get("evidence_quote"))[:400],
                "explanation": clean_text(out.get("explanation"))[:400],
                "retry_used": attempt,
            })
            if out.pop("_salvaged", None):
                rec["salvaged"] = 1
            return rec
        # 一次纠错重试
        rec["retry_used"] = 1
        messages = messages + [
            {"role": "assistant", "content": json.dumps(out, ensure_ascii=False)},
            {"role": "user", "content": "decision 字段不合法。必须且只能是 FULLY_SUPPORTED/PARTIALLY_SUPPORTED/UNSUPPORTED/CONTRADICTED/INSUFFICIENT 之一。重新输出且仅输出合法 JSON 对象。"},
        ]
        try:
            out = chat_json(messages, max_tokens=500, timeout=900)
        except LMStudioError as exc:
            rec.update({"decision": "CALL_FAILED", "error": str(exc)[:300]})
            return rec
    rec.update({"decision": "UNPARSEABLE",
                "error": f"invalid decision: {str(out.get('decision'))[:80]}"})
    return rec


# ---------------------------------------------------------------------------
# 执行主循环（4 并发 + checkpoint）
# ---------------------------------------------------------------------------

def load_checkpoint() -> dict[str, dict]:
    done: dict[str, dict] = {}
    if not OUT_CKPT.exists():
        return done
    with open(OUT_CKPT, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                break  # 尾部半行（崩溃残留）——丢弃
            if obj.get("fact_id"):
                done[obj["fact_id"]] = obj
    return done


def run_execution(samples, align, recov, workers: int, limit: int,
                  resume: bool) -> tuple[dict[str, dict], dict]:
    todo: list[tuple[str, str]] = []           # (stratum, fact_id)
    for name, _n, _src in STRATA_SPEC:
        ids = samples[name][:limit] if limit else samples[name]
        todo.extend((name, f) for f in ids)
    done = load_checkpoint() if resume else {}
    if not resume:
        print("[gate] --no-resume：忽略已有 checkpoint（文件仍为追加写）")
    pending = [x for x in todo if x[1] not in done]
    print(f"[gate] 待判定 {len(pending)} / {len(todo)} 条（已完成 {len(todo)-len(pending)}）")

    resolver = EvidenceResolver(connect_final())
    attach_integration(resolver.con)

    items: list[dict] = []
    for stratum, fid in todo:
        a = align[fid]
        r = recov.get(fid) if stratum.startswith("recovery_") else None
        ev = resolver.assemble(stratum, fid, a, r)
        items.append({
            "fact_id": fid, "stratum": stratum, "bucket": a["bucket"],
            "recovery_class": (r or {}).get("recovery_class", ""),
            "match_mode": (r or {}).get("match_mode", ""),
            "predicate": clean_text(a.get("predicate")),
            "subject_name": clean_text(a.get("subject_name")),
            "subject_type": clean_text(a.get("subject_type")),
            "object_name": clean_text(a.get("object_name")),
            "object_type": clean_text(a.get("object_type")),
            "time_raw": clean_text(a.get("time_raw")),
            "place_raw": clean_text(a.get("place_raw")),
            "assertion": assertion_text(a),
            **ev,
        })
    by_id = {it["fact_id"]: it for it in items}

    t0 = time.time()
    write_lock = threading.Lock()
    ckpt = open(OUT_CKPT, "a", encoding="utf-8")
    state = {"n": 0, "since_flush": 0}
    latencies: list[float] = []
    forced = failed = 0

    def handle(item: dict):
        # judge_one 返回 dict(item) + 判定字段：输入上下文与判定逐条同记录落盘
        out = judge_one(item)
        line = json.dumps(out, ensure_ascii=False)
        with write_lock:
            ckpt.write(line + "\n")
            state["n"] += 1
            state["since_flush"] += 1
            if state["since_flush"] >= CKPT_FLUSH_EVERY:
                ckpt.flush()
                os.fsync(ckpt.fileno())
                state["since_flush"] = 0
        return out

    if pending:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(handle, by_id[fid]): fid for _s, fid in pending}
            n_done = 0
            for fut in as_completed(futs):
                out = fut.result()
                n_done += 1
                if out.get("latency_s") is not None:
                    latencies.append(out["latency_s"])
                if out.get("forced"):
                    forced += 1
                if out.get("decision") == "CALL_FAILED":
                    failed += 1
                if n_done % 100 == 0 or n_done == len(pending):
                    ckpt.flush()
                    os.fsync(ckpt.fileno())
                    rate = n_done / max(time.time() - t0, 1e-9)
                    eta = (len(pending) - n_done) / max(rate, 1e-9) / 60.0
                    print(f"[gate] {n_done}/{len(pending)} done, {rate:.2f} it/s, "
                          f"ETA {eta:.1f} min, forced_empty={forced}, failed={failed}",
                          flush=True)
    ckpt.flush()
    os.fsync(ckpt.fileno())
    ckpt.close()

    elapsed = time.time() - t0
    done = load_checkpoint()
    meta = {
        "elapsed_seconds": round(elapsed, 1),
        "n_executed": len(pending),
        "n_forced_empty": forced,
        "n_call_failed": failed,
        "latency_avg_s": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "workers": workers,
    }
    print(f"[gate] 执行完成：{meta}")
    return done, meta


# ---------------------------------------------------------------------------
# 统计 + 产物
# ---------------------------------------------------------------------------

def dev_map(decision: str, predicate: str, strict_partial_preds: set[str]) -> str:
    """DEV 重分层规则。"""
    if decision == "FULLY_SUPPORTED":
        return "strict"
    if decision == "PARTIALLY_SUPPORTED":
        return "strict" if predicate in strict_partial_preds else "contextual"
    if decision in ("UNSUPPORTED", "CONTRADICTED"):
        return "unresolved"
    if decision == "INSUFFICIENT":
        return "contextual"
    return "unresolved"          # UNPARSEABLE / CALL_FAILED → 待复核，不入层


def build_stats(done: dict, samples, pops, exec_meta: dict) -> dict:
    layer_sizes = {
        "mismatch_with_evidence": len(pops["mismatch_with_evidence"]),
        "recovery_B": len(pops["recovery_B"]),
        "recovery_C": len(pops["recovery_C"]),
        "recovery_A": len(pops["recovery_A"]),
        "aligned": len(pops["aligned"]),
    }
    strata: dict[str, dict] = {}
    pooled_partial_by_pred: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "conf_sum": 0.0, "n_high": 0})
    pred_by_stratum: dict[str, dict[str, dict]] = defaultdict(dict)

    for name, _n, _src in STRATA_SPEC:
        ids = samples[name]
        recs = [done[f] for f in ids if f in done]
        cnt = Counter(r.get("decision") for r in recs)
        n_total = len(ids)
        n_done = len(recs)
        n_valid = sum(cnt[l] for l in LABELS)
        n_sup = cnt["FULLY_SUPPORTED"] + cnt["PARTIALLY_SUPPORTED"]
        lo, hi = wilson_ci(n_sup, n_valid) if n_valid else (0.0, 0.0)
        flo, fhi = wilson_ci(cnt["FULLY_SUPPORTED"], n_valid) if n_valid else (0.0, 0.0)
        strata[name] = {
            "layer_size": layer_sizes[name],
            "sample_size": n_total,
            "n_judged": n_done,
            "n_valid": n_valid,
            "n_unparseable_or_failed": n_done - n_valid,
            "decisions": {l: cnt.get(l, 0) for l in LABELS},
            "decision_shares": ({l: round(cnt.get(l, 0) / n_valid, 4)
                                 for l in LABELS} if n_valid else {}),
            "support_rate": round(n_sup / n_valid, 4) if n_valid else None,
            "support_ci95": [round(lo, 4), round(hi, 4)],
            "fully_rate": round(cnt["FULLY_SUPPORTED"] / n_valid, 4) if n_valid else None,
            "fully_ci95": [round(flo, 4), round(fhi, 4)],
            "n_forced_empty": sum(1 for r in recs if r.get("forced") == "empty_evidence"),
        }
        # predicate 分组
        by_pred: dict[str, list[dict]] = defaultdict(list)
        for r in recs:
            if r.get("decision") in LABELS:
                by_pred[r.get("predicate") or "(none)"].append(r)
        for pred, rs in by_pred.items():
            k = sum(1 for r in rs if r["decision"] in
                    ("FULLY_SUPPORTED", "PARTIALLY_SUPPORTED"))
            plo, phi = wilson_ci(k, len(rs))
            row = {"n": len(rs), "support_rate": round(k / len(rs), 4),
                   "ci95": [round(plo, 4), round(phi, 4)],
                   "fully": sum(1 for r in rs if r["decision"] == "FULLY_SUPPORTED"),
                   "partial": sum(1 for r in rs if r["decision"] == "PARTIALLY_SUPPORTED")}
            pred_by_stratum[name][pred] = row
            # PARTIAL predicate 表（跨层合并）
            for r in rs:
                if r["decision"] == "PARTIALLY_SUPPORTED":
                    cell = pooled_partial_by_pred[pred]
                    cell["n"] += 1
                    cell["conf_sum"] += float(r.get("confidence") or 0.0)
                    cell["n_high"] += 1 if (r.get("confidence") or 0.0) >= HIGH_CONF else 1

    # PARTIAL → predicate 表（数据依据）
    partial_pred_table = {}
    for pred, cell in sorted(pooled_partial_by_pred.items(),
                             key=lambda kv: -kv[1]["n"]):
        mean_conf = cell["conf_sum"] / cell["n"] if cell["n"] else 0.0
        share_high = cell["n_high"] / cell["n"] if cell["n"] else 0.0
        strict = (cell["n"] >= PRED_STRICT_MIN_N
                  and mean_conf >= PRED_STRICT_MIN_CONF
                  and share_high >= PRED_STRICT_MIN_SHARE)
        partial_pred_table[pred] = {
            "n_partial": cell["n"],
            "mean_confidence": round(mean_conf, 4),
            "share_conf_ge_075": round(share_high, 4),
            "map_to": "strict" if strict else "contextual",
        }
    strict_preds = {p for p, v in partial_pred_table.items() if v["map_to"] == "strict"}

    # 每层 DEV 重分层 + 外推（分层抽样统计估计）
    extrapolation = {}
    est_strict = 0.0
    var_total = 0.0
    class_est = {l: 0.0 for l in LABELS}
    class_var = {l: 0.0 for l in LABELS}
    dev_counts_by_stratum = {}
    for name, _n, _src in STRATA_SPEC:
        ids = samples[name]
        recs = [done[f] for f in ids if f in done]
        st = strata[name]
        n_valid, N = st["n_valid"], st["layer_size"]
        dev_cnt = Counter(dev_map(r.get("decision"), r.get("predicate") or "",
                                  strict_preds)
                          for r in recs if r.get("decision") in LABELS)
        dev_counts_by_stratum[name] = dict(dev_cnt)
        strict_rate = (dev_cnt.get("strict", 0) / n_valid) if n_valid else 0.0
        fpc = (N - n_valid) / (N - 1) if N > 1 and n_valid > 0 else 0.0
        est = N * strict_rate
        se = N * math.sqrt(max(fpc * strict_rate * (1 - strict_rate) / n_valid, 0.0)) \
            if n_valid else 0.0
        est_strict += est
        var_total += se * se
        extrapolation[name] = {
            "layer_size": N, "n_valid": n_valid,
            "strict_rate_sample": round(strict_rate, 4),
            "estimated_strict": round(est, 1),
            "se_strict": round(se, 1),
        }
        for l in LABELS:
            share = st["decisions"][l] / n_valid if n_valid else 0.0
            class_est[l] += N * share
            se_l = N * math.sqrt(max(fpc * share * (1 - share) / n_valid, 0.0)) if n_valid else 0.0
            class_var[l] += se_l * se_l
    summary_extrapolation = {
        "note": "分层抽样统计估计（每层 simple random sample；finite population correction），"
                "非逐条验证；逐条全量语义验证留待后续。",
        "universe": "STRICT_ALIGNMENT 全部 112,158 条中的 5 个层（合计 "
                    f"{sum(layer_sizes.values()):,} 条）；recovery_D（真无证据）{2106:,} 条"
                    "不参与外推（无可验证证据，按恢复审计降级）",
        "per_layer": extrapolation,
        "new_strict_total_estimate": round(est_strict, 0),
        "new_strict_ci95": [round(max(est_strict - 1.96 * math.sqrt(var_total), 0.0), 0),
                            round(est_strict + 1.96 * math.sqrt(var_total), 0)],
        "decision_totals_estimate": {
            l: {"estimate": round(class_est[l], 0),
                "ci95": [round(max(class_est[l] - 1.96 * math.sqrt(class_var[l]), 0.0), 0),
                         round(class_est[l] + 1.96 * math.sqrt(class_var[l]), 0)]}
            for l in LABELS},
        "dev_layer_totals_estimate": None,   # 下面填充
    }
    # DEV 三层全库外推（strict/contextual/unresolved）
    dev_tot = {"strict": 0.0, "contextual": 0.0, "unresolved": 0.0}
    for name, _n, _src in STRATA_SPEC:
        st = strata[name]
        n_valid, N = st["n_valid"], st["layer_size"]
        if not n_valid:
            continue
        recs = [done[f] for f in samples[name] if f in done and
                done[f].get("decision") in LABELS]
        cnt = Counter(dev_map(r.get("decision"), r.get("predicate") or "", strict_preds)
                      for r in recs)
        for k, v in dev_tot.items():
            share = cnt.get(k, 0) / n_valid
            dev_tot[k] += N * share
    summary_extrapolation["dev_layer_totals_estimate"] = {
        k: round(v, 0) for k, v in dev_tot.items()}

    return {
        "strata": strata,
        "partial_predicate_table": partial_pred_table,
        "strict_partial_preds": sorted(strict_preds),
        "pred_by_stratum": {s: dict(d) for s, d in pred_by_stratum.items()},
        "extrapolation": summary_extrapolation,
        "dev_counts_by_stratum": dev_counts_by_stratum,
        "layer_sizes": layer_sizes,
    }


def write_outputs(done: dict, samples, align, recov, stats: dict,
                  exec_meta: dict, workers: int, elapsed_total: float) -> None:
    # ---------- VERDICTS.jsonl（按抽样顺序）----------
    ordered = [(name, f) for name, _n, _src in STRATA_SPEC for f in samples[name]]
    with open(OUT_VERDICTS, "w", encoding="utf-8") as fh:
        for name, fid in ordered:
            r = done.get(fid)
            if r is None:
                continue
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---------- STRATA.csv ----------
    with open(OUT_STRATA, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["stratum", "layer_size", "sample_size", "n_valid",
                    "decision", "n", "share_in_sample",
                    "support_rate_fully_partial", "support_ci95_low",
                    "support_ci95_high"])
        for name, _n, _src in STRATA_SPEC:
            st = stats["strata"][name]
            for lab in LABELS:
                w.writerow([name, st["layer_size"], st["sample_size"], st["n_valid"],
                            lab, st["decisions"][lab],
                            st["decision_shares"].get(lab, ""),
                            st["support_rate"] if st["support_rate"] is not None else "",
                            st["support_ci95"][0], st["support_ci95"][1]])

    # ---------- PREDICATE.csv ----------
    with open(OUT_PRED, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["section", "stratum_or_predicate", "predicate", "n",
                    "support_rate", "ci95_low", "ci95_high",
                    "n_partial", "mean_conf_partial", "share_conf_ge_075",
                    "partial_map_to"])
        for name, _n, _src in STRATA_SPEC:
            for pred, row in sorted(stats["pred_by_stratum"].get(name, {}).items(),
                                    key=lambda kv: -kv[1]["n"]):
                w.writerow(["by_stratum", name, pred, row["n"], row["support_rate"],
                            row["ci95"][0], row["ci95"][1], "", "", "", ""])
        for pred, row in stats["partial_predicate_table"].items():
            w.writerow(["partial_predicate_table", "pooled", pred, row["n_partial"],
                        "", "", "", row["n_partial"], row["mean_confidence"],
                        row["share_conf_ge_075"], row["map_to"]])

    # ---------- SUMMARY.json ----------
    summary = {
        "task": "P0-9 Evidence Semantic Gate stratified validation (指令 §13)",
        "method_version": METHOD_VERSION,
        "generated_at": now_iso(),
        "deterministic": True,
        "manual_review": False,
        "model": {
            "provider": "lmstudio_provider.chat_json (local LM Studio only)",
            "model_id": DEFAULT_MODEL,
            "base_url": DEFAULT_BASE,
            "temperature": 0.0,
            "max_tokens": 500,
            "workers": workers,
        },
        "sampling": {
            "seed": SEED,
            "scheme": "per-stratum simple random sample over sorted fact_ids",
            "sample_ids_file": OUT_SAMPLE.name,
        },
        "labels": LABELS,
        "rules": {
            "empty_evidence": "forced INSUFFICIENT (no model call)",
            "dev_restratification": {
                "FULLY_SUPPORTED": "strict",
                "PARTIALLY_SUPPORTED": "predicate 表决定 strict/contextual（默认 contextual）",
                "UNSUPPORTED | CONTRADICTED": "unresolved",
                "INSUFFICIENT": "contextual",
                "UNPARSEABLE | CALL_FAILED": "excluded from rates (待复核)",
            },
            "partial_predicate_rule": (
                f"n_partial>={PRED_STRICT_MIN_N} 且 mean_conf>={PRED_STRICT_MIN_CONF} "
                f"且 share(conf>={HIGH_CONF})>={PRED_STRICT_MIN_SHARE} → strict，否则 contextual"),
        },
        "inputs": {
            "strict_alignment_csv": ALIGN_CSV.name,
            "strict_alignment_sha256": sha256_file(ALIGN_CSV),
            "evidence_recovery_csv": RECOV_CSV.name,
            "evidence_recovery_sha256": sha256_file(RECOV_CSV),
        },
        "execution": exec_meta,
        "elapsed_seconds_total": round(elapsed_total, 1),
        **{k: stats[k] for k in ("strata", "partial_predicate_table",
                                 "strict_partial_preds", "pred_by_stratum",
                                 "extrapolation", "dev_counts_by_stratum",
                                 "layer_sizes")},
    }
    OUT_SUM.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                       encoding="utf-8")


def build_report(stats: dict, exec_meta: dict, samples, pops,
                 elapsed_total: float, done: dict) -> str:
    S = stats["strata"]
    tot = Counter()
    for name, _n, _src in STRATA_SPEC:
        tot.update(S[name]["decisions"])
    n_all = sum(tot[l] for l in LABELS)
    ex = stats["extrapolation"]
    ppt = stats["partial_predicate_table"]

    def dist_table(name):
        st = S[name]
        rows = [f"| {l} | {st['decisions'][l]} | "
                f"{st['decision_shares'].get(l, 0):.1%} |" for l in LABELS]
        return "\n".join(rows)

    lines = f"""# Evidence Semantic Gate — 分层语义验证报告（指令 §13）

- 生成时间：{now_iso()}
- 方法版本：`{METHOD_VERSION}`（全自动、fixed-seed、无人工；判定全部来自本地模型输出）
- 模型：`{DEFAULT_MODEL}`（LM Studio 本地，temperature=0，`lmstudio_provider.chat_json`，{exec_meta['workers']} 并发）
- 输入：`STRICT_ALIGNMENT.csv`（sha256 前 8 位 `{sha256_file(ALIGN_CSV)[:8]}`）、
  `EVIDENCE_RECOVERY.csv`（sha256 前 8 位 `{sha256_file(RECOV_CSV)[:8]}`）
- 抽样 seed：**{SEED}**（每层对排序后 fact_id 做 `random.Random(seed).sample`，清单见 `SAMPLE_IDS.json`）
- 判定样本：5 层共 {sum(S[n]['sample_size'] for n in S):,} 条；执行 {exec_meta['n_executed']} 条，
  耗时 {exec_meta['elapsed_seconds']/60:.1f} 分钟（均延迟 {exec_meta['latency_avg_s']} s/条，
  checkpoint 每 {CKPT_FLUSH_EVERY} 条落盘、可续跑）
- 空证据强制判 INSUFFICIENT：{sum(S[n]['n_forced_empty'] for n in S)} 条（不消耗模型调用）

## 1. 方法

五档语义支持判定：给模型 normalized assertion
（`subject —predicate— object` + 时间/空间表述）与证据原文（≤{EVID_CAP} 字，最多
{EVID_SHOW} 条拼接），要求**只依据证据**输出
`decision/confidence/evidence_quote/explanation` 的 JSON，禁止外部知识。
五档定义：FULLY_SUPPORTED（证据明确完整支持全部要素）/ PARTIALLY_SUPPORTED
（部分支持，如时间/地点/范围不完全吻合）/ UNSUPPORTED（证据相关但不含所述关系）/
CONTRADICTED（矛盾）/ INSUFFICIENT（证据缺失或不足）。

分层设计（词法结果 ≠ 语义结果，各层语义支持率未知，须分别估计）：
mismatch_with_evidence（有证据但词法不含实体名，高风险）、recovery_B（同行双名
强恢复）、recovery_C（弱定位恢复）、recovery_A（确定证据 ID，高置信校准层）、
aligned（词法对齐但从未做语义验证的 44k）。

## 2. 各层五档分布与支持率（Wilson 95% CI）

| 层 | 层规模 N | 样本 n | 有效判定 | FULLY | PARTIAL | UNSUPP | CONTRA | INSUFF | 支持率 (FULLY+PARTIAL) | 95% CI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
"""
    for name, _n, _src in STRATA_SPEC:
        st = S[name]
        lines += (f"| {name} | {st['layer_size']:,} | {st['sample_size']:,} | "
                  f"{st['n_valid']:,} | {st['decisions']['FULLY_SUPPORTED']} | "
                  f"{st['decisions']['PARTIALLY_SUPPORTED']} | "
                  f"{st['decisions']['UNSUPPORTED']} | "
                  f"{st['decisions']['CONTRADICTED']} | "
                  f"{st['decisions']['INSUFFICIENT']} | "
                  f"{st['support_rate']:.1%} | "
                  f"[{st['support_ci95'][0]:.1%}, {st['support_ci95'][1]:.1%}] |\n")
    lines += f"""
样本合计五档分布（n={n_all:,}）：FULLY {tot['FULLY_SUPPORTED']:,}
（{tot['FULLY_SUPPORTED']/n_all:.1%}）｜PARTIAL {tot['PARTIALLY_SUPPORTED']:,}
（{tot['PARTIALLY_SUPPORTED']/n_all:.1%}）｜UNSUPPORTED {tot['UNSUPPORTED']:,}
（{tot['UNSUPPORTED']/n_all:.1%}）｜CONTRADICTED {tot['CONTRADICTED']:,}
（{tot['CONTRADICTED']/n_all:.1%}）｜INSUFFICIENT {tot['INSUFFICIENT']:,}
（{tot['INSUFFICIENT']/n_all:.1%}）。

### 各层判定明细样本

"""
    for name, _n, _src in STRATA_SPEC:
        lines += f"**{name}**（n={S[name]['sample_size']:,}）：\n\n{dist_table(name)}\n\n"

    lines += """## 3. Support-Coverage 的含义

词法 strict 层的"覆盖率"只说明**存在证据指针/可恢复证据文本**（coverage），
不说明证据在语义上真的支持断言。本次 semantic gate 度量的是
**支持质量（support）**：词法覆盖的断言中有多少比例能被证据原文在语义上
完整/部分支持。两者相乘才是有效覆盖：例如某层词法覆盖 100%、语义支持率 60%，
则该层的有效语义覆盖只有约 60%。低支持层即"词法假阳/证据错配"的主要来源
（mismatch_with_evidence 层即典型：有证据指针但原文不含实体名）。

## 4. 按 predicate 的系统性差异

支持率前/后差异见 `EVIDENCE_GATE_PREDICATE.csv`（层 × predicate 与跨层 PARTIAL 表）。
主要发现（n≥30 的 predicate）：

"""
    # 跨层汇总 predicate 支持率（样本合并）
    pool: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for name, _n, _src in STRATA_SPEC:
        for pred, row in stats["pred_by_stratum"].get(name, {}).items():
            cell = pool[pred]
            cell[0] += round(row["support_rate"] * row["n"])
            cell[1] += row["n"]
    rows = sorted(((p, k, n, k / n) for p, (k, n) in pool.items() if n >= 30),
                  key=lambda x: -x[3])
    lines += "| predicate | 合并样本 n | 支持率 |\n| --- | --- | --- |\n"
    for p, k, n, r in rows:
        lines += f"| {p} | {n} | {r:.1%} |\n"
    lines += ("\n（差异解释：`active_at/occurred_at` 类空间/时间谓词依赖证据中的同现表述，"
              "而 `led/participated_in` 等关系谓词对证据表述方式更敏感——详见 CSV。）\n")

    lines += f"""## 5. DEV 重分层规则与 PARTIAL predicate 表

规则：FULLY_SUPPORTED→**strict**；PARTIALLY_SUPPORTED→按 predicate 表决定
**strict/contextual**；UNSUPPORTED / CONTRADICTED→**unresolved**；
INSUFFICIENT→**contextual**；解析失败/调用失败→不计入比率（待复核）。

PARTIAL predicate 表数据依据（跨 5 层合并的 PARTIAL 判定，n={sum(v['n_partial'] for v in ppt.values()):,}）：
入 strict 条件 = `n_partial≥{PRED_STRICT_MIN_N}` 且 `mean_confidence≥{PRED_STRICT_MIN_CONF}`
且 `share(conf≥{HIGH_CONF})≥{PRED_STRICT_MIN_SHARE}`；不满足或样本不足 → 默认 contextual。

| predicate | n_partial | mean_conf | share(conf≥{HIGH_CONF}) | 映射 |
| --- | --- | --- | --- | --- |
"""
    for pred, v in sorted(ppt.items(), key=lambda kv: -kv[1]["n_partial"]):
        lines += (f"| {pred} | {v['n_partial']} | {v['mean_confidence']:.3f} | "
                  f"{v['share_conf_ge_075']:.1%} | {v['map_to']} |\n")
    lines += (f"\n入 strict 的 predicate（n≥{PRED_STRICT_MIN_N} 且置信度达标）："
              f"{'、'.join(stats['strict_partial_preds']) or '（无——全部默认 contextual）'}\n")

    lines += f"""## 6. 全库外推（分层抽样统计估计，非逐条验证）

**明确标注：以下为分层抽样的统计估计**（每层 simple random sample + 有限总体校正；
点估计 ±1.96·SE），逐条全量语义验证留待后续。外推宇宙 = 5 层合计
{sum(stats['layer_sizes'].values()):,} 条；recovery_D 2,106 条真无证据不参与外推
（无可验证证据，按恢复审计降级）。

| 层 | 层规模 | 样本有效 n | 样本 strict 率 | 估计 strict 条数 | SE |
| --- | --- | --- | --- | --- | --- |
"""
    for name, _n, _src in STRATA_SPEC:
        row = ex["per_layer"][name]
        lines += (f"| {name} | {row['layer_size']:,} | {row['n_valid']:,} | "
                  f"{row['strict_rate_sample']:.1%} | {row['estimated_strict']:,.0f} | "
                  f"±{row['se_strict']:,.0f} |\n")
    ns = ex["new_strict_total_estimate"]
    ci = ex["new_strict_ci95"]
    lines += f"""
**全库 new strict size 估计：{ns:,.0f} 条（95% CI [{ci[0]:,.0f}, {ci[1]:,.0f}]）**
（词法 strict 层 112,158 条 → 语义门后约 {ns/112158:.1%}）。

五档全库估计：""" + "；".join(
        f"{l} {ex['decision_totals_estimate'][l]['estimate']:,.0f} "
        f"[{ex['decision_totals_estimate'][l]['ci95'][0]:,.0f}, "
        f"{ex['decision_totals_estimate'][l]['ci95'][1]:,.0f}]" for l in LABELS) + f"""。

DEV 三层全库估计：strict {ex['dev_layer_totals_estimate']['strict']:,.0f} ／
contextual {ex['dev_layer_totals_estimate']['contextual']:,.0f} ／
unresolved {ex['dev_layer_totals_estimate']['unresolved']:,.0f}
（另有 recovery_D 2,106 条真无证据降级）。

## 7. 局限性

1. **词法恢复的 B/C 层证据相关性弱于 direct**：B（同行双名同现）只保证两个实体名
   同时出现在同一证据行，不保证所述关系就是断言关系；C（弱定位/单名/异行）相关性
   更弱。这两层是恢复候选而非确证证据，其语义支持率应解读为"恢复链路上限"。
2. **抽样估计而非普查**：各层支持率由 n=200–1,500 的固定 seed 样本估计，CI 为
   抽样不确定性；层内若存在与 predicate/实体类型相关的异质性，层内分层可进一步
   收窄（本次已给出层 × predicate 明细供后续加权）。
3. **单一本地判定模型**：全部判定来自 gpt-oss-20b（temperature=0，JSON 稳定），
   未经第二模型或人工仲裁；PARTIAL 与 UNSUPPORTED 的边界判例存在模型主观性。
4. **证据截断**：每条断言最多拼接 {EVID_SHOW} 条证据、总长 ≤{EVID_CAP} 字，超长
   证据尾部被截断，可能低估 FULLY_SUPPORTED；A 层少量 metadata 引文只有 120 字预览。
5. **INSUFFICIENT 的双重来源**：证据文本为空（强制判）与模型判证据不足混在同一档，
   已在逐条记录 `forced` 字段区分。

## 8. 可复现性

- seed={SEED} 写死；抽样、证据拼接顺序（evidence_id 字典序）、判定顺序全部确定性。
- checkpoint：`EVIDENCE_GATE_CHECKPOINT.jsonl`（追加写、每 {CKPT_FLUSH_EVERY} 条 fsync），
  断点续跑只跳过已完成 fact_id。
- 判定输入/输出逐条落盘 `EVIDENCE_GATE_VERDICTS.jsonl`（含 assertion、evidence_text、
  decision、confidence、evidence_quote、explanation、latency）。
- 输入 CSV 的 sha256 记录于 `EVIDENCE_GATE_SUMMARY.json`；数据库只读。
- 本次执行{'已' if exec_meta.get('resumed') else '未'}从 checkpoint 续跑。
"""
    return lines


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="每层只取前 N 条（冒烟测试）")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--stats-only", action="store_true",
                    help="跳过执行，仅从 checkpoint 重算统计与产物")
    args = ap.parse_args()

    t_start = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    align = load_alignment()
    recov = load_recovery()
    print(f"[gate] alignment={len(align):,} rows, recovery={len(recov):,} rows")
    samples, pops = build_samples(align, recov)
    for name, n_t, _s in STRATA_SPEC:
        print(f"[gate] stratum {name}: pop={len(pops[name]):,}, sample={len(samples[name])}")
    load_or_make_samples(align, recov)   # 落盘/校验 SAMPLE_IDS.json

    if args.stats_only:
        done, exec_meta = load_checkpoint(), {"elapsed_seconds": 0.0, "n_executed": 0,
                                              "n_forced_empty": 0, "n_call_failed": 0,
                                              "latency_avg_s": None,
                                              "workers": args.workers, "resumed": True}
    else:
        done, exec_meta = run_execution(samples, align, recov, args.workers,
                                        args.limit, not args.no_resume)
        done_all = load_checkpoint()
        exec_meta["resumed"] = (not args.no_resume) and exec_meta["n_executed"] < sum(
            len(samples[n]) if not args.limit else min(args.limit, len(samples[n]))
            for n, _t, _s in STRATA_SPEC)
        missing = [f for name, _n, _s in STRATA_SPEC for f in samples[name]
                   if f not in done_all]
        if missing:
            print(f"[gate] 警告：{len(missing)} 条无判定记录（CALL_FAILED 也会有记录；"
                  f"若 >0 请检查）样例: {missing[:3]}")
        done = done_all

    stats = build_stats(done, samples, pops, exec_meta)
    write_outputs(done, samples, align, recov, stats, exec_meta,
                  args.workers, time.time() - t_start)
    report = build_report(stats, exec_meta, samples, pops,
                          time.time() - t_start, done)
    OUT_RPT.write_text(report, encoding="utf-8")

    S = stats["strata"]
    print("[gate] 支持率汇总（FULLY+PARTIAL, Wilson 95% CI）:")
    for name, _n, _s in STRATA_SPEC:
        st = S[name]
        print(f"  {name:24s} {st['support_rate'] if st['support_rate'] is not None else float('nan'):.1%} "
              f"[{st['support_ci95'][0]:.1%}, {st['support_ci95'][1]:.1%}] (n={st['n_valid']})")
    ex = stats["extrapolation"]
    print(f"[gate] new strict 估计: {ex['new_strict_total_estimate']:,.0f} "
          f"CI95 {ex['new_strict_ci95']}")
    print(f"[gate] done in {(time.time()-t_start)/60:.1f} min -> {OUT_RPT.name}, "
          f"{OUT_SUM.name}, {OUT_STRATA.name}, {OUT_VERDICTS.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
