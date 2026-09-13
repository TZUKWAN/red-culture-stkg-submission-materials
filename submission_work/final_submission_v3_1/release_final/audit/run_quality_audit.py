# -*- coding: utf-8 -*-
"""run_quality_audit.py — PHASE 2.2：独立裁判盲评执行器。

用法：
    python run_quality_audit.py --judge gpt-oss-20b --workers 4
    python run_quality_audit.py --judge qwen/qwen3-8b --workers 4

- 只读 SAMPLE_AUDIT.json（盲样本，不含任何生产判定）；
- 断点续跑（JUDGE_<safe>_VERDICTS.jsonl 已有 fact_id 跳过）；
- 裁判与生产模型严格不同；判定合同与生产一致（同五档 JSON）。
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "independent_eval"))
from lmstudio_provider import LMStudioError, chat_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AUD = ROOT / "release_final" / "experiments" / "quality_audit"
CN_TZ = timezone(timedelta(hours=8))

LABELS = ["FULLY_SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED",
          "CONTRADICTED", "INSUFFICIENT"]

JUDGE_SYS = """你是党史文献知识库的独立证据核验裁判。给定一条断言和若干证据原文片段，你只能依据证据判断断言是否被支持，禁止使用任何外部知识；证据中没有的信息一律视为不存在。
输出且仅输出一个 JSON 对象，字段如下：
{"decision": "FULLY_SUPPORTED|PARTIALLY_SUPPORTED|UNSUPPORTED|CONTRADICTED|INSUFFICIENT", "confidence": <0到1的小数>, "evidence_quote": "<支持判断的证据原句，直接摘录，可为空字符串>", "explanation": "<一句话中文理由>"}
五档定义：
FULLY_SUPPORTED=证据明确且完整支持断言的全部要素（主体、关系、客体的时间/空间表述一致或为证据内容的严格子集）；
PARTIALLY_SUPPORTED=证据明确支持断言的核心要素，但时间/空间/范围等部分要素缺失、宽于或窄于断言表述；
UNSUPPORTED=证据存在但完全未提及断言所述内容；
CONTRADICTED=证据明确与断言矛盾；
INSUFFICIENT=证据过短或信息量不足，无法形成可靠判断。
只依据证据原文，不引入任何背景知识。"""


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat()


def judge_path(judge: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", judge).strip("_")
    return AUD / f"JUDGE_{safe}_VERDICTS.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    sample = json.loads((AUD / "SAMPLE_AUDIT.json").read_text(encoding="utf-8"))
    items = sample["items"]
    if args.limit:
        items = items[: args.limit]

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
    todo = [it for it in items if it["fact_id"] not in done]
    print(f"[judge:{args.judge}] total={len(items)} done={len(done)} todo={len(todo)}",
          flush=True)
    if not todo:
        print("[judge] nothing to do")
        return 0

    ckpt_lock = threading.Lock()
    ckpt = open(outp, "a", encoding="utf-8")
    n_ok = n_bad = 0
    t0 = time.time()

    def work(it: dict) -> dict:
        rec = {"fact_id": it["fact_id"], "model": args.judge,
               "decision": None, "confidence": None, "evidence_quote": "",
               "explanation": "", "parse_ok": 0, "salvaged": 0,
               "latency_s": None, "error": "", "ts": now_iso()}
        msgs = [{"role": "system", "content": JUDGE_SYS},
                {"role": "user",
                 "content": f"断言：{it['assertion']}\n证据原文：\n{it['evidence_text'] or '（空）'}\n只依据上述证据输出 JSON。"}]
        t1 = time.time()
        try:
            out = chat_json(msgs, model=args.judge, max_tokens=600, timeout=600,
                            retries=1)
        except LMStudioError as exc:
            rec["error"] = str(exc)[:300]
            rec["latency_s"] = round(time.time() - t1, 2)
            return rec
        rec["latency_s"] = round(time.time() - t1, 2)
        dec = str(out.get("decision", "")).strip().upper()
        if dec in LABELS:
            try:
                conf = min(1.0, max(0.0, float(out.get("confidence"))))
            except (TypeError, ValueError):
                conf = None
            rec.update({"decision": dec, "confidence": conf, "parse_ok": 1,
                        "evidence_quote": str(out.get("evidence_quote", ""))[:400],
                        "explanation": str(out.get("explanation", ""))[:400]})
            if out.get("_salvaged"):
                rec["salvaged"] = 1
        else:
            rec["error"] = f"invalid decision: {dec[:60]}"
        return rec

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, it): it for it in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            rec = fut.result()
            with ckpt_lock:
                ckpt.write(json.dumps(rec, ensure_ascii=False) + "\n")
                if i % 50 == 0:
                    ckpt.flush()
            if rec["parse_ok"]:
                n_ok += 1
            else:
                n_bad += 1
            if i % 200 == 0:
                rate = i / max(time.time() - t0, 1e-9)
                eta = (len(todo) - i) / max(rate, 1e-9) / 60
                print(f"[judge:{args.judge}] {i}/{len(todo)} ok={n_ok} bad={n_bad} "
                      f"{rate:.2f} it/s ETA {eta:.0f} min", flush=True)
    ckpt.flush()
    ckpt.close()
    print(f"[judge:{args.judge}] DONE ok={n_ok} bad={n_bad} "
          f"elapsed={(time.time()-t0)/60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
