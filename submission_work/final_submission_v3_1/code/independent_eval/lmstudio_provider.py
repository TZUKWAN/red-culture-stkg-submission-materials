# -*- coding: utf-8 -*-
"""lmstudio_provider.py — 本地 LM Studio 统一 provider（生产链唯一大模型入口）。

配置（环境变量，缺省用本地默认）：
    LMSTUDIO_BASE_URL  默认 http://127.0.0.1:1234/v1
    LMSTUDIO_MODEL     默认 qwen3.5-4b（最终生产语义门主模型）
    LMSTUDIO_MODEL_FALLBACK 默认不启用（生产链禁止静默换模）
    LMSTUDIO_EMBED_MODEL    默认 text-embedding-nomic-embed-text-v1.5
    LMSTUDIO_API_KEY   可选（LM Studio 默认不校验）

模型清单（2026-09-10 实测，见 method_final/03_LOCAL_LMSTUDIO_REPORT.md）：
    qwen3.5-4b              本地 LM Studio，最终生产语义门主模型
    其他模型                 不得作为生产链静默回退
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
DEFAULT_MODEL = os.environ.get("LMSTUDIO_MODEL", "qwen3.5-4b")
# 生产链默认不回退到其他模型；失败记录必须显式保留为 FAILED/UNRESOLVED。
DEFAULT_FALLBACK = os.environ.get("LMSTUDIO_MODEL_FALLBACK", "")
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
    """单轮 chat，返回最终答案文本；qwen3.5-4b 使用原生接口且关闭 reasoning。"""
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        # 生产链不允许静默换模；仅在显式提供非空 fallback 时才使用它。
        use_model = model
        if attempt >= retries and DEFAULT_FALLBACK and model != DEFAULT_FALLBACK:
            use_model = DEFAULT_FALLBACK
        try:
            if use_model == "qwen3.5-4b":
                # LM Studio 原生接口才支持 qwen3.5 的 reasoning="off"。
                # 将 system/user 消息保持顺序拼接，禁止模型进入思考通道。
                prompt = "\n\n".join(
                    f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
                    for m in messages
                )
                d = _post(
                    f"{DEFAULT_BASE.rstrip('/').rsplit('/v1', 1)[0]}/api/v1/chat",
                    {"model": use_model, "input": prompt,
                     "temperature": temperature,
                     "max_output_tokens": max_tokens, "reasoning": "off"},
                    timeout,
                )
                for item in d.get("output", []):
                    if item.get("type") == "message" and str(item.get("content") or "").strip():
                        return str(item["content"])
                return ""
            d = _post(
                f"{DEFAULT_BASE.rstrip('/')}/chat/completions",
                {"model": use_model, "messages": messages, "temperature": temperature,
                 "top_p": top_p, "max_tokens": max_tokens},
                timeout,
            )
            msg = d["choices"][0].get("message", {})
            return str(msg.get("content") or "")
        except Exception as exc:  # 本地服务：网络类失败短暂退避后重试
            last_err = exc
            time.sleep(min(2 ** attempt, 8))
    raise LMStudioError(f"LM Studio chat failed after retries: {last_err}")


_STRUCT_CHARS = set(",:}] \t\r\n")


def _repair_unescaped_quotes(s: str) -> str:
    """修复字符串值内部未转义的 ASCII 引号（qwen3.5-4b 偶发，如 其"led"（领导））。

    仅做转义规范化，不改动任何语义内容：处于字符串内遇到 `"` 时，若其后
    （跳过空白）不是 JSON 结构字符（, : } ] 或结尾），则视为字面引号并转义。
    """
    out: list[str] = []
    in_str = False
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if not in_str:
            if c == '"':
                in_str = True
            out.append(c)
            i += 1
            continue
        if c == "\\":  # 已转义序列原样保留
            out.append(s[i:i + 2])
            i += 2
            continue
        if c == '"':
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j >= n or s[j] in _STRUCT_CHARS:
                in_str = False      # 合法收尾引号
            else:
                out.append("\\\"")  # 字符串内部的字面引号
                i += 1
                continue
        elif c == "\n":
            out.append("\\n")
            i += 1
            continue
        elif c == "\r":
            out.append("\\r")
            i += 1
            continue
        elif c == "\t":
            out.append("\\t")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


_SALVAGE_LABELS = ("FULLY_SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED",
                   "CONTRADICTED", "INSUFFICIENT")


def _salvage_fields(text: str) -> dict[str, Any] | None:
    """schema 兜底提取：严格/修复解析都失败时，按已知字段模式直接提取。

    只信任显式出现的 `"decision": "<五档枚举>"`；decision 缺失或不在枚举内
    一律返回 None（上层记 CALL_FAILED 可重试），绝不猜测判定。
    """
    import re
    m = re.search(r'"decision"\s*:\s*"([A-Z_]+)"', text)
    if not m or m.group(1) not in _SALVAGE_LABELS:
        return None
    out: dict[str, Any] = {"decision": m.group(1)}
    mc = re.search(r'"confidence"\s*:\s*([0-9.]+)', text)
    if mc:
        try:
            out["confidence"] = max(0.0, min(1.0, float(mc.group(1))))
        except ValueError:
            pass

    def grab(key: str) -> str:
        mk = re.search(rf'"{key}"\s*:\s*"(.*)', text, re.S)
        if not mk:
            return ""
        val = mk.group(1)
        end = val.find('"')
        return val[:end] if end >= 0 else val

    out["evidence_quote"] = grab("evidence_quote")
    out["explanation"] = grab("explanation")
    out["_salvaged"] = True
    return out


def extract_json(text: str) -> dict[str, Any]:
    """从模型输出中提取第一个 JSON 对象（容忍 ```json 包裹/前后噪声/内部引号）。"""
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
                raw = s[start : i + 1]
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    pass
                try:
                    return json.loads(_repair_unescaped_quotes(raw))
                except json.JSONDecodeError:
                    salv = _salvage_fields(raw)
                    if salv is not None:
                        return salv
                    raise LMStudioError(
                        f"malformed JSON object in output: unparseable even after repair/salvage")
    # 右括号缺失（生成提前结束）——同样允许兜底提取，绝不静默丢判定。
    salv = _salvage_fields(s[start:])
    if salv is not None:
        return salv
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
