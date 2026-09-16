# -*- coding: utf-8 -*-
"""run_outside_audit.py — 门外宇宙独立裁判盲评执行器。

用法：
    python run_outside_audit.py --judge gpt-oss-20b --workers 8
    python run_outside_audit.py --judge qwen/qwen3-8b --workers 8

- 输入：OUTSIDE_GATE_SAMPLE.jsonl（不含任何生产 tier/reason/path）；
  评审输入在运行时从源库组装（断言/实体/类型/时间/空间/证据原文）；
- 输出：JUDGE_<safe>_VERDICTS.jsonl，断点续跑；
- 输出 schema 见 OUTSIDE_GATE_AUDIT_PROTOCOL.json（多字段，严格 JSON）。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

V31 = Path(__file__).resolve().parents[2]
REPO = V31.parents[1]
OUT = V31 / "experiments" / "10_full_universe_admission_closure"
SRC_DB = V31 / "data" / "repaired_release" / "red_culture_stkg_final_v3_1.sqlite"
sys.path.insert(0, str(V31.parent / "final_submission_v3" / "code" / "independent_eval"))
sys.path.insert(0, str(V31 / "code" / "independent_eval"))
from lmstudio_provider import LMStudioError, chat_json  # noqa: E402
from _common import attach_integration  # noqa: E402

CN_TZ = timezone(timedelta(hours=8))
EVID_CAP = 800

JUDGE_SYS = """你是党史文献知识库的独立结构准入裁判。给定一条断言（主-谓-宾及类型）、时间/空间字段、以及证据原文片段，请分别判断：
1) evidence_support：证据对断言的支持程度，取值 FULLY_SUPPORTED/PARTIALLY_SUPPORTED/INSUFFICIENT/UNSUPPORTED/CONTRADICTED/NO_EVIDENCE（证据片段为空即 NO_EVIDENCE）；
2) identity_decidable：依据证据能否唯一确定主体与客体的同一性（YES/NO/UNCERTAIN）；
3) relation_semantically_supported：证据是否在语义上支持该关系本身（YES/NO/UNCERTAIN）；
4) scope_decidable：依据证据能否确定断言的时间/空间作用域（YES/NO/UNCERTAIN）；
5) strict_eligible：综合以上，该断言是否够格进入严格发布层（YES/NO/UNCERTAIN）；
6) recommended_state：建议状态 STRICT/CONTEXTUAL/UNRESOLVED；
7) reason：一句话中文理由。
只依据证据原文，禁止使用任何外部知识；证据中没有的信息一律视为不存在。
输出且仅输出一个 JSON 对象：
{"evidence_support": "...", "identity_decidable": "...", "relation_semantically_supported": "...", "scope_decidable": "...", "strict_eligible": "...", "recommended_state": "...", "reason": "..."}"""

SCHEMA = {
    "evidence_support": {"FULLY_SUPPORTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT",
                         "UNSUPPORTED", "CONTRADICTED", "NO_EVIDENCE"},
    "identity_decidable": {"YES", "NO", "UNCERTAIN"},
    "relation_semantically_supported": {"YES", "NO", "UNCERTAIN"},
    "scope_decidable": {"YES", "NO", "UNCERTAIN"},
    "strict_eligible": {"YES", "NO", "UNCERTAIN"},
    "recommended_state": {"STRICT", "CONTEXTUAL", "UNRESOLVED"},
}


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat()


def judge_path(judge: str) -> Path:
    return OUT / f"JUDGE_{re.sub(r'[^A-Za-z0-9]+', '_', judge).strip('_')}_VERDICTS.jsonl"


def assemble_inputs(con, fact_ids: list[str]) -> dict[str, dict]:
    """一次性组装全部样本的裁判输入（断言+类型+时空+证据文本）。"""
    out: dict[str, dict] = {}
    ev_map: dict[str, list[str]] = {}
    for fid, js in con.execute(
            "SELECT fact_id, evidence_ids_json FROM research_assertion_provenance "
            "ORDER BY fact_id, provenance_id"):
        try:
            ids = [str(x) for x in json.loads(js or "[]")]
        except json.JSONDecodeError:
            ids = []
        if ids:
            ev_map.setdefault(fid, [])
            for e in ids:
                if e not in ev_map[fid]:
                    ev_map[fid].append(e)
    texts: dict[str, tuple[str, str]] = {}
    all_eids = sorted({e for lst in ev_map.values() for e in lst})
    for i in range(0, len(all_eids), 500):
        ch = all_eids[i:i + 500]
        q = ",".join("?" * len(ch))
        for eid, title, txt in con.execute(
                f"SELECT evidence_id, source_title, evidence_text FROM up.evidence_registry "
                f"WHERE evidence_id IN ({q})", ch):
            texts[eid] = (str(title or ""), str(txt or ""))
    q_marks = ",".join("?" * len(fact_ids))
    for row in con.execute(
            f"SELECT fact_id, subject_name, subject_type, object_name, object_type, "
            f"predicate, time_raw, time_start, time_end, place_raw "
            f"FROM research_assertions WHERE fact_id IN ({q_marks})", fact_ids):
        fid, sn, st, on, ot, pred, tr, t0, t1, pr = row
        parts = []
        total = 0
        for e in ev_map.get(fid, [])[:6]:
            t = texts.get(e, ("", ""))[1]
            if not t:
                continue
            parts.append(t)
            total += len(t)
            if total >= EVID_CAP:
                break
        out[fid] = {
            "subject_name": sn, "subject_type": st,
            "object_name": on, "object_type": ot,
            "predicate": pred,
            "time": tr or (f"{t0}~{t1}" if (t0 or t1) else ""),
            "space": pr or "",
            "evidence_text": "\n‖\n".join(parts)[:EVID_CAP],
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    sample = [json.loads(l) for l in
              open(OUT / "OUTSIDE_GATE_SAMPLE.jsonl", encoding="utf-8") if l.strip()]
    fids = [it["fact_id"] for it in (sample[: args.limit] if args.limit else sample)]
    print(f"[outside:{args.judge}] assembling inputs for {len(fids)} items...",
          flush=True)
    con = sqlite3.connect(f"file:{SRC_DB}?mode=ro", uri=True)
    attach_integration(con)
    inputs = assemble_inputs(con, fids)
    con.close()
    print(f"[outside:{args.judge}] inputs assembled: {len(inputs)}", flush=True)

    outp = judge_path(args.judge)
    done: dict[str, dict] = {}
    if outp.exists():
        for line in outp.open(encoding="utf-8"):
            if line.strip():
                try:
                    r = json.loads(line)
                    done[r["fact_id"]] = r
                except json.JSONDecodeError:
                    pass
    todo = [f for f in fids if f not in done]
    print(f"[outside:{args.judge}] total={len(fids)} done={len(done)} todo={len(todo)}",
          flush=True)
    if not todo:
        print("[outside] nothing to do")
        return 0

    lock = threading.Lock()
    ckpt = open(outp, "a", encoding="utf-8")
    n_ok = n_bad = 0
    t0 = time.time()

    def work(fid: str) -> dict:
        inp = inputs.get(fid, {})
        rec = {"fact_id": fid, "model": args.judge, "parse_ok": 0,
               "verdict": None, "error": "", "ts": now_iso()}
        user = (f"断言：{inp.get('subject_name')}—{inp.get('predicate')}—{inp.get('object_name')}"
                f"（主体类型 {inp.get('subject_type')}；客体类型 {inp.get('object_type')}）\n"
                f"时间字段：{inp.get('time') or '（空）'}\n"
                f"空间字段：{inp.get('space') or '（空）'}\n"
                f"证据原文：\n{inp.get('evidence_text') or '（空）'}\n"
                f"按系统指令输出唯一 JSON。")
        msgs = [{"role": "system", "content": JUDGE_SYS},
                {"role": "user", "content": user}]
        t1 = time.time()
        try:
            obj = chat_json(msgs, model=args.judge, max_tokens=700, timeout=600,
                            retries=1)
        except LMStudioError as exc:
            rec["error"] = str(exc)[:300]
            return rec
        rec["latency_s"] = round(time.time() - t1, 2)
        clean = {k: str(obj.get(k, "")).strip().upper() for k in SCHEMA}
        clean["reason"] = str(obj.get("reason", ""))[:200]
        if (clean["evidence_support"] in SCHEMA["evidence_support"]
                and clean["recommended_state"] in SCHEMA["recommended_state"]
                and all(clean[k] in SCHEMA[k] for k in
                        ("identity_decidable", "relation_semantically_supported",
                         "scope_decidable", "strict_eligible"))):
            clean.pop("_salvaged", None)
            rec["verdict"] = clean
            rec["parse_ok"] = 1
            if obj.get("_salvaged"):
                rec["salvaged"] = 1
        else:
            rec["error"] = f"invalid fields: {clean}"
        return rec

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(work, f) for f in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            rec = fut.result()
            with lock:
                ckpt.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if i % 100 == 0:
                    ckpt.flush()
            if rec["parse_ok"]:
                n_ok += 1
            else:
                n_bad += 1
            if i % 250 == 0:
                rate = i / max(time.time() - t0, 1e-9)
                print(f"[outside:{args.judge}] {i}/{len(todo)} ok={n_ok} bad={n_bad} "
                      f"{rate:.2f} it/s ETA {(len(todo)-i)/max(rate,1e-9)/60:.0f}min",
                      flush=True)
    ckpt.flush()
    ckpt.close()
    print(f"[outside:{args.judge}] DONE ok={n_ok} bad={n_bad} "
          f"elapsed={(time.time()-t0)/60:.1f}min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
