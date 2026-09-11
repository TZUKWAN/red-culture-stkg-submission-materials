# -*- coding: utf-8 -*-
"""lmstudio_provider.py — 本地 LM Studio 统一 provider（生产链唯一大模型入口）。

配置（环境变量，缺省用本地默认）：
    LMSTUDIO_BASE_URL  默认 http://127.0.0.1:1234/v1
    LMSTUDIO_MODEL     默认 openai/gpt-oss-20b（升级裁决/生产主模型）
    LMSTUDIO_MODEL_FALLBACK 默认 qwen/qwen3-8b
    LMSTUDIO_EMBED_MODEL    默认 text-embedding-nomic-embed-text-v1.5
    LMSTUDIO_API_KEY   可选（LM Studio 默认不校验）

模型清单（2026-09-10 实测，见 method_final/03_LOCAL_LMSTUDIO_REPORT.md）：
    openai/gpt-oss-20b      热身后 ~4s/条，structured JSON 稳定（升级/生产主模型）
    qwen/qwen3-8b           ~12s/条，JSON 稳定（备用）
    text-embedding-nomic-embed-text-v1.5  嵌入（语义特征/检索）
    qwen/qwen3-vl-4b        （视觉，暂不用于生产链）
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any

DEFAULT_BASE = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
DEFAULT_MODEL = os.environ.get("LMSTUDIO_MODEL", "openai/gpt-oss-20b")
DEFAULT_FALLBACK = os.environ.get("LMSTUDIO_MODEL_FALLBACK", "qwen/qwen3-8b")
DEFAULT_EMBED = os.environ.get("LMSTUDIO_EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5")
API_KEY = os.environ.get("LMSTUDIO_API_KEY", "lm-studio")


class LMStudioError(RuntimeError):
    pass


def _post(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def chat(messages: list[dict[str, str]], model: str = DEFAULT_MODEL, *,
         temperature: float = 0.0, top_p: float = 1.0, max_tokens: int = 900,
         timeout: float = 300.0, retries: int = 2) -> str:
    """单轮 chat，返回 content 文本。失败时回退备用模型一次。"""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        use_model = model if attempt < retries else (DEFAULT_FALLBACK if model != DEFAULT_FALLBACK else model)
        try:
            d = _post(
                f"{DEFAULT_BASE.rstrip('/')}/chat/completions",
                {"model": use_model, "messages": messages, "temperature": temperature,
                 "top_p": top_p, "max_tokens": max_tokens},
                timeout,
            )
            return str(d["choices"][0]["message"].get("content") or "")
        except Exception as exc:  # 本地服务：网络类失败短暂退避后重试
            last_err = exc
            time.sleep(min(2 ** attempt, 8))
    raise LMStudioError(f"LM Studio chat failed after retries: {last_err}")


def extract_json(text: str) -> dict[str, Any]:
    """从模型输出中提取第一个 JSON 对象（容忍 ```json 包裹/前后噪声）。"""
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
    start = s.find("{")
    if start < 0:
        raise LMStudioError(f"no JSON object in output: {text[:120]!r}")
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start : i + 1])
    raise LMStudioError("unbalanced JSON in model output")


def chat_json(messages: list[dict[str, str]], *, model: str = DEFAULT_MODEL,
              temperature: float = 0.0, max_tokens: int = 900,
              timeout: float = 300.0, retries: int = 2) -> dict[str, Any]:
    """chat + JSON 提取，一次到位。"""
    return extract_json(chat(messages, model=model, temperature=temperature,
                             max_tokens=max_tokens, timeout=timeout, retries=retries))


def embed(texts: list[str], model: str = DEFAULT_EMBED, timeout: float = 120.0) -> list[list[float]]:
    """批量嵌入（nomic-embed），返回向量列表。"""
    d = _post(f"{DEFAULT_BASE.rstrip('/')}/embeddings",
              {"model": model, "input": texts}, timeout)
    data = sorted(d["data"], key=lambda x: x.get("index", 0))
    return [item["embedding"] for item in data]


def probe(n: int = 10, model: str = DEFAULT_MODEL) -> dict[str, Any]:
    """连续 n 次结构化 JSON 探针，返回稳定性统计（写入 model manifest）。"""
    oks = lats = 0
    latencies: list[float] = []
    for i in range(n):
        t0 = time.time()
        try:
            out = chat_json(
                [{"role": "system", "content": '输出且仅输出一个 JSON 对象 {"ok": true, "i": <int>}'},
                 {"role": "user", "content": f"i={i}"}],
                model=model, max_tokens=60, timeout=120,
            )
            if out.get("ok") is True and out.get("i") == i:
                oks += 1
            latencies.append(time.time() - t0)
        except Exception:
            latencies.append(time.time() - t0)
    return {"model": model, "n": n, "json_ok": oks,
            "latency_avg_s": (sum(latencies) / len(latencies)) if latencies else None,
            "latency_max_s": max(latencies) if latencies else None}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", type=int, default=10)
    args = ap.parse_args()
    print(json.dumps(probe(args.probe), ensure_ascii=False, indent=2))
