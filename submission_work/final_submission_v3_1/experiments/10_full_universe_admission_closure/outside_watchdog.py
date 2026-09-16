# -*- coding: utf-8 -*-
"""outside_watchdog.py — 门外审计 A→B 全程守护（速率退化即重载模型）。"""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

V31 = Path(__file__).resolve().parents[2]
OUT = V31 / "experiments" / "10_full_universe_admission_closure"
LMS = r"C:\Users\lauze\.lmstudio\bin\lms.exe"
RUNNER = V31 / "experiments" / "10_full_universe_admission_closure" / "run_outside_audit.py"
CN_TZ = timezone(timedelta(hours=8))

TOTAL = 5000
WINDOW_S = 180
MIN_RATE = 40

JUDGES = [
    {"key": "A", "model_id": "gpt-oss-20b", "load_key": "openai/gpt-oss-20b",
     "file": "JUDGE_gpt_oss_20b_VERDICTS.jsonl",
     "log": "JUDGE_A_OUTSIDE_RUN.log", "workers": 10,
     "load": ["--context-length", "24576", "--parallel", "6"]},
    {"key": "B", "model_id": "qwen/qwen3-8b", "load_key": "qwen/qwen3-8b",
     "file": "JUDGE_qwen_qwen3_8b_VERDICTS.jsonl",
     "log": "JUDGE_B_OUTSIDE_RUN.log", "workers": 8,
     "load": ["--context-length", "24576", "--parallel", "8"]},
]


def log(msg: str) -> None:
    print(f"{datetime.now(CN_TZ).isoformat()[11:19]} {msg}", flush=True)


def count_lines(p: Path) -> int:
    if not p.exists():
        return 0
    with p.open("rb") as fh:
        return sum(1 for _ in fh)


def kill_clients() -> None:
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' "
          "-and $_.CommandLine -like '*run_outside_audit.py*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=120)
    time.sleep(2)


def unload_all() -> None:
    subprocess.run([LMS, "unload", "gpt-oss-20b"], capture_output=True, timeout=300)
    subprocess.run([LMS, "unload", "qwen/qwen3-8b"], capture_output=True, timeout=300)


def load_model(j: dict) -> None:
    subprocess.run([LMS, "load", j["load_key"], "--gpu", "max", *j["load"],
                    "--identifier", j["model_id"], "-y"],
                   capture_output=True, timeout=900)
    log(f"model loaded: {j['model_id']}")
    time.sleep(3)


def start_client(j: dict) -> None:
    subprocess.Popen(
        [sys.executable, str(RUNNER), "--judge", j["model_id"],
         "--workers", str(j["workers"])],
        cwd=str(RUNNER.parent),
        stdout=open(OUT / j["log"], "ab"), stderr=subprocess.STDOUT)
    log(f"client started: judge {j['key']}")


def main() -> int:
    log("outside watchdog online")
    for j in JUDGES:
        f = OUT / j["file"]
        kill_clients()
        unload_all()
        load_model(j)
        start_client(j)
        time.sleep(60)
        while True:
            n0 = count_lines(f)
            time.sleep(WINDOW_S)
            n1 = count_lines(f)
            rate = n1 - n0
            log(f"judge {j['key']}: {n1}/{TOTAL} (+{rate} in {WINDOW_S}s)")
            if n1 >= TOTAL:
                log(f"judge {j['key']} COMPLETE")
                kill_clients()
                break
            if rate < MIN_RATE:
                log(f"degradation (rate={rate}) -> kill+reload+restart")
                kill_clients()
                unload_all()
                load_model(j)
                start_client(j)
            else:
                chk = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq "
                     "'python.exe' -and $_.CommandLine -like '*run_outside_audit.py*' } "
                     "| Measure-Object).Count"],
                    capture_output=True, text=True, timeout=120)
                if chk.stdout.strip().startswith("0"):
                    log("client dead -> restart")
                    start_client(j)
    log("ALL OUTSIDE JUDGES COMPLETE — run score_outside_audit.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
