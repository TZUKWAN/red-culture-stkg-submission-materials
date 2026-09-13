# -*- coding: utf-8 -*-
"""monitor_tiering.py — FINAL TIERING 队列命令行监控面板。

用法：
    python monitor_tiering.py             # 常驻刷新（默认每 10 秒）
    python monitor_tiering.py -i 30       # 每 30 秒刷新
    python monitor_tiering.py --once      # 单次快照（适合脚本/管道）

只读监控：不改任何队列产物；数据源为 checkpoint 增量读取 + RUN 日志 + PID/心跳文件。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from collections import Counter, deque
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "experiments" / "07_provenance_semantic_gate"
CKPT = GATE / "FINAL_TIERING_CHECKPOINT.jsonl"
RUN = GATE / "FINAL_TIERING_QUEUE_RUN.log"
STDOUT_LOG = GATE / "FINAL_TIERING_QUEUE_STDOUT.log"
PIDF = GATE / "FINAL_TIERING_QUEUE_PID.json"
BEAT = GATE / "FINAL_TIERING_QUEUE_HEARTBEAT.txt"
DONE = GATE / "FINAL_TIERING_QUEUE_DONE.txt"

MODEL = "qwen3.5-4b"
VALID = {"FULLY_SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED",
         "CONTRADICTED", "INSUFFICIENT"}
FAILED = {"CALL_FAILED", "UNPARSEABLE"}
STRATA = ["mismatch_with_evidence", "recovery_B", "recovery_A",
          "aligned", "recovery_C"]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        k = ctypes.windll.kernel32
        # 64 位下必须显式声明 HANDLE 返回类型，否则句柄被截断成 32 位 c_int，
        # 可能误判存活进程为 DEAD。
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        h = k.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        try:
            ec = ctypes.c_ulong()
            if k.GetExitCodeProcess(h, ctypes.byref(ec)):
                return ec.value == 259
            return False
        finally:
            k.CloseHandle(h)
    except Exception:
        return False


class Scan:
    """checkpoint 增量扫描：按字节偏移只读新增行，维护 unique fact 计数。"""

    def __init__(self) -> None:
        self.offset = 0
        self.size = -1
        self.seen: dict[str, str] = {}          # fact_id -> 最新 decision
        self.decisions: Counter = Counter()
        self.strata: Counter = Counter()        # unique 口径
        self.total_lines = 0
        self.legacy_lines = 0                   # 非 qwen 历史记录
        self.qwen_records = 0
        self.last_ts = ""
        self.last_latency = None
        self.recent = deque(maxlen=60)          # (decision, latency)
        self.recent_errors = deque(maxlen=5)

    def rescan(self) -> None:
        self.offset = 0
        self.size = -1
        self.seen.clear()
        self.decisions.clear()
        self.strata.clear()
        self.total_lines = 0
        self.legacy_lines = 0
        self.qwen_records = 0
        self.last_ts = ""
        self.last_latency = None
        self.recent.clear()
        self.recent_errors.clear()

    def _apply(self, obj: dict) -> None:
        self.total_lines += 1
        fid = obj.get("fact_id")
        if obj.get("model") != MODEL:
            self.legacy_lines += 1
            return
        self.qwen_records += 1
        ts = str(obj.get("ts") or "")
        if ts > self.last_ts:
            self.last_ts = ts
        self.last_latency = obj.get("latency_s")
        dec = obj.get("decision")
        if dec in FAILED and obj.get("error"):
            self.recent_errors.append(str(obj["error"])[:110])
        if fid is None:
            return
        old = self.seen.get(fid)
        if old in VALID:
            self.decisions[old] -= 1
            if self.decisions[old] <= 0:
                del self.decisions[old]
        elif old in FAILED and self.seen.get(fid) != dec:
            pass
        self.seen[fid] = dec
        if dec in VALID:
            self.decisions[dec] += 1
            st = str(obj.get("stratum") or "?")
            self.strata[st] += 1
            self.recent.append((dec, obj.get("latency_s")))

    def update(self) -> None:
        if not CKPT.exists():
            return
        size = CKPT.stat().st_size
        if size < self.offset:
            self.rescan()
        with open(CKPT, "rb") as f:
            f.seek(self.offset)
            chunk = f.read()
        cut = chunk.rfind(b"\n")
        if cut < 0:
            return
        self.offset += cut + 1
        for line in chunk[:cut + 1].splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                self._apply(json.loads(line))
            except Exception:
                continue


def parse_run_log(scan: Scan) -> dict:
    out = {"pending": None, "workers": None, "model": None,
           "rate": None, "rate_src": "", "last_ckpt": None,
           "last_ckpt_age": None, "chunk_eta_h": None,
           "start_ts": None, "done_age_min": None}
    if not RUN.exists():
        return out
    try:
        lines = RUN.read_text(encoding="utf-8", errors="replace") \
                    .splitlines()[-400:]
    except Exception:
        return out
    ck_events: list[tuple[datetime, int]] = []
    for ln in lines:
        ts_str = ln[:19]
        try:
            ts = datetime.fromisoformat(ts_str)
        except Exception:
            continue
        if " queue start pending=" in ln:
            try:
                seg = ln.split(" queue start pending=")[1]
                out["pending"] = int(seg.split(" ")[0])
                for tok in seg.split(" "):
                    if tok.startswith("workers="):
                        out["workers"] = int(tok.split("=")[1])
                    if tok.startswith("model="):
                        out["model"] = tok.split("=")[1]
                out["start_ts"] = ts
                ck_events = []
            except Exception:
                pass
        elif " checkpoint " in ln and " flushed" in ln:
            try:
                n = int(ln.split(" checkpoint ")[1].split("/")[0])
                ck_events.append((ts, n))
            except Exception:
                pass
        elif " chunk done:" in ln and " ETA " in ln:
            try:
                out["chunk_eta_h"] = float(
                    ln.split(" ETA ")[1].split(" h")[0])
            except Exception:
                pass
    if ck_events:
        t_last, n_last = ck_events[-1]
        out["last_ckpt"] = t_last
        out["last_ckpt_age"] = (datetime.now(t_last.tzinfo) - t_last).total_seconds()
        if len(ck_events) >= 2:
            t_prev, n_prev = ck_events[-2]
            dt = (t_last - t_prev).total_seconds()
            dn = n_last - n_prev
            if dt > 0 and dn > 0:
                out["rate"] = dn / dt * 60.0
                out["rate_src"] = "checkpoint Δ"
        elif out["start_ts"] is not None:
            dt = (t_last - out["start_ts"]).total_seconds()
            if dt > 0 and n_last > 0:
                out["rate"] = n_last / dt * 60.0
                out["rate_src"] = "since start"
    return out


def _tail_lines(path: Path, nbytes: int = 200_000) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-nbytes:] \
                   .splitlines()
    except Exception:
        return []


def parse_plan_total() -> int | None:
    total = None
    for ln in _tail_lines(STDOUT_LOG):
        if "[queue] plan=" in ln and "queue_total" in ln:
            try:
                total = int(json.loads(ln.split("[queue] plan=")[1])["queue_total"])
            except Exception:
                pass
    return total


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def bar(frac: float, w: int = 34) -> str:
    frac = max(0.0, min(1.0, frac))
    f = int(round(frac * w))
    return "#" * f + "." * (w - f)


def fmt_eta(seconds: float) -> str:
    if seconds != seconds or seconds in (float("inf"),):
        return "n/a"
    h = seconds / 3600.0
    if h >= 48:
        return f"{h/24:.1f} d"
    return f"{h:.1f} h"


C = {"g": "\x1b[32m", "y": "\x1b[33m", "r": "\x1b[31m",
     "c": "\x1b[36m", "b": "\x1b[1m", "0": "\x1b[0m"}


def render(scan: Scan, log: dict, total: int | None, interval: int) -> str:
    now = datetime.now().astimezone()
    valid_n = sum(scan.decisions.values())
    failed_unique = sum(1 for d in scan.seen.values() if d in FAILED)
    todo = total if total is not None else 0
    done = valid_n
    pending = max(todo - done, 0) if todo else None
    frac = done / todo if todo else 0.0

    pid_state = read_json(PIDF)
    pid = int(pid_state.get("pid", 0) or 0)
    alive = pid_alive(pid)
    spawns = pid_state.get("spawns", "?")
    done_marker = DONE.exists()

    rate = log.get("rate")
    eta_s = (pending / rate * 60.0) if (rate and pending is not None) else None
    eta_at = (now + timedelta(seconds=eta_s)).strftime("%m-%d %H:%M") \
        if eta_s else "n/a"

    beat = ""
    if BEAT.exists():
        try:
            beat = BEAT.read_text(encoding="utf-8").strip().replace("\n", " | ")
        except Exception:
            beat = ""

    lat = scan.last_latency
    lat_s = f"{lat:.1f}s" if isinstance(lat, (int, float)) else "n/a"

    def col(v, good, bad=None):
        if bad is not None and v == bad:
            return C["r"]
        return C["g"] if v == good else C["y"]

    L = []
    L.append(f"{C['b']}FINAL TIERING QUEUE MONITOR{C['0']}"
             f"{'':>28}{now.strftime('%Y-%m-%d %H:%M:%S')}")
    L.append("─" * 78)
    mcol = C["g"] if log.get("model") == MODEL else C["r"]
    pcol = C["g"] if alive else C["r"]
    L.append(f" model   : {mcol}{log.get('model') or '?'}{C['0']} (target {MODEL})"
             f"   workers : {log.get('workers') or '?'}"
             f"   PID : {pcol}{pid or '-'} {'ALIVE' if alive else 'DEAD'}{C['0']}"
             f"   watchdog spawns: {spawns}")
    L.append(f" progress: {done:,} / {todo:,} ({frac:6.2%})  [{C['c']}{bar(frac)}{C['0']}]")
    pend_s = f"{pending:,}" if pending is not None else "n/a"
    dcol = C["g"] if not done_marker else C["y"]
    L.append(f" pending : {pend_s}    failed(retry): {failed_unique:,}"
             f"    legacy rows: {scan.legacy_lines:,}    DONE marker: {dcol}{done_marker}{C['0']}")
    rs = f"{rate:.1f}/min ({log.get('rate_src')})" if rate else "measuring..."
    L.append(f" rate    : {rs}")
    L.append(f" ETA     : {fmt_eta(eta_s) if eta_s else 'n/a'}"
             f"{f'  (→ {eta_at})' if eta_s else ''}     last latency: {lat_s}")
    stale = log.get("last_ckpt_age")
    scol = C["g"] if (stale is not None and stale < 1800) else C["y"] \
        if stale is not None else C["y"]
    last_ck = log["last_ckpt"].strftime("%H:%M:%S") if log.get("last_ckpt") else "n/a"
    L.append(f" last ckpt flush: {last_ck}"
             f"{f' ({stale/60:.0f} min ago)' if stale is not None else ''}"
             f"   heartbeat: {beat}")
    if scan.last_ts:
        lt = datetime.fromisoformat(scan.last_ts)
        age = (now - lt).total_seconds() / 60.0
        L.append(f" last qwen record: {lt.strftime('%H:%M:%S')} ({age:.1f} min ago)")
    L.append("")
    L.append(f"{C['b']}stratum completion (unique qwen valid / plan total){C['0']}")
    for st in STRATA:
        d = scan.strata.get(st, 0)
        t = read_plan_totals().get(st, 0)
        fr = d / t if t else 0.0
        L.append(f"   {st:<24} {d:>7,} / {t:>7,}  {bar(fr, 24)} {fr:6.2%}")
    L.append("")
    L.append(f"{C['b']}decision distribution (unique){C['0']}")
    for k in ("FULLY_SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED",
              "CONTRADICTED", "INSUFFICIENT"):
        v = scan.decisions.get(k, 0)
        L.append(f"   {k:<24} {v:>7,}")
    L.append("")
    if scan.recent_errors:
        L.append(f"{C['y']}recent errors (retryable){C['0']}")
        for e in list(scan.recent_errors)[-3:]:
            L.append(f"   ! {e}")
    if done_marker:
        L.append(f"{C['g']}QUEUE DONE — 运行 build_final_tiering.py stats / finalize 落定 MEASURED 计数{C['0']}")
    L.append("")
    L.append(f" refresh: {interval}s   Ctrl+C 退出   (--once 单次快照)")
    return "\n".join(L)


_PLAN_TOTALS: dict[str, int] = {}


def read_plan_totals() -> dict[str, int]:
    global _PLAN_TOTALS
    if _PLAN_TOTALS:
        return _PLAN_TOTALS
    for ln in reversed(_tail_lines(STDOUT_LOG)):
        if "[queue] plan=" in ln:
            try:
                j = json.loads(ln.split("[queue] plan=")[1])
                _PLAN_TOTALS = {k: int(v) for k, v in j["queue"].items()}
                break
            except Exception:
                pass
    return _PLAN_TOTALS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--interval", type=int, default=10)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    os.system("")  # enable ANSI on legacy console
    scan = Scan()
    scan.update()  # 首次全量扫描（一次）

    while True:
        scan.update()
        log = parse_run_log(scan)
        total = parse_plan_total()
        frame = render(scan, log, total, args.interval)
        if args.once:
            print(frame)
            return 0
        sys.stdout.write("\x1b[2J\x1b[H" + frame + "\n")
        sys.stdout.flush()
        time.sleep(max(args.interval, 2))


if __name__ == "__main__":
    raise SystemExit(main())
