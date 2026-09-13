# -*- coding: utf-8 -*-
"""judge_watchdog.py — PHASE 2 裁判执行守护器（自动处理 LM Studio 半响应退化）。

逻辑：
  循环监测当前裁判 verdict 文件 3 分钟窗口增量；低于阈值即执行
  杀客户端 → lms unload/load → 重启客户端（断点续跑）。
  当前裁判达到 4427 后切换下一裁判，全部完成后退出（评分由人工/后续步骤触发）。

用法：python judge_watchdog.py
"""
from __future__ import annotations

import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUD = ROOT / "release_final" / "experiments" / "quality_audit"
LMS = r"C:\Users\lauze\.lmstudio\bin\lms.exe"
CN_TZ = timezone(timedelta(hours=8))

TOTAL = 4427
WINDOW_S = 180
MIN_RATE = 30            # 3 分钟内至少新增 30 条（≈0.17 it/s），低于即重载
CLIENT_WORKERS = 6

JUDGES = [
    {"key": "A", "model_id": "gpt-oss-20b", "load_key": "openai/gpt-oss-20b",
     "file": "JUDGE_gpt_oss_20b_VERDICTS.jsonl",
     "load": ["--context-length", "24576", "--parallel", "6"]},
    {"key": "B", "model_id": "qwen/qwen3-8b", "load_key": "qwen/qwen3-8b",
     "file": "JUDGE_qwen_qwen3_8b_VERDICTS.jsonl",
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
          "-and $_.CommandLine -like '*run_quality_audit.py*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=120)
    time.sleep(2)


def reload_model(j: dict) -> None:
    subprocess.run([LMS, "unload", j["model_id"]], capture_output=True, timeout=300)
    r = subprocess.run([LMS, "load", j["load_key"], "--gpu", "max", *j["load"],
                        "--identifier", j["model_id"], "-y"],
                       capture_output=True, timeout=900)
    ok = b"successfully" in r.stdout or b"loaded" in r.stdout.lower()
    log(f"model {j['model_id']} reloaded (ok={ok})")
    time.sleep(3)


def start_client(j: dict) -> None:
    subprocess.Popen(
        [sys_executable(), str(ROOT / "release_final" / "audit" / "run_quality_audit.py"),
         "--judge", j["model_id"], "--workers", str(CLIENT_WORKERS)],
        cwd=str(ROOT / "release_final" / "audit"),
        stdout=open(AUD / f"JUDGE_{j['key']}_RUN.log", "ab"),
        stderr=subprocess.STDOUT)
    log(f"client started for judge {j['key']} ({j['model_id']})")


def sys_executable() -> str:
    import sys
    return sys.executable


def main() -> int:
    log("judge watchdog online")
    for j in JUDGES:
        f = AUD / j["file"]
        start_client(j)
        time.sleep(20)
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
                log(f"degradation detected (rate={rate}/{WINDOW_S}s) -> reload cycle")
                kill_clients()
                reload_model(j)
                start_client(j)
            elif n1 < TOTAL:
                # 客户端意外死亡（零产出且进程不在）→ 直接重启
                chk = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq "
                     "'python.exe' -and $_.CommandLine -like '*run_quality_audit.py*' } "
                     "| Measure-Object).Count"],
                    capture_output=True, text=True, timeout=120)
                if chk.stdout.strip().startswith("0"):
                    log("client dead -> restart")
                    start_client(j)
    log("ALL JUDGES COMPLETE — run score_quality_audit.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
