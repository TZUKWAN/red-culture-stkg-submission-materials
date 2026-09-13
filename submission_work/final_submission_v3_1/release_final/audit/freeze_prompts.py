# -*- coding: utf-8 -*-
"""freeze_prompts.py — 冻结生产/裁判 prompt 至 configs/PROMPTS.txt（含 SHA256）。"""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code" / "experiment_pipelines"))
from run_evidence_semantic_gate import SYS_PROMPT  # noqa: E402

judge_src = (ROOT / "release_final" / "audit" / "run_quality_audit.py").read_text(encoding="utf-8")
jstart = judge_src.find('JUDGE_SYS = """')
jend = judge_src.find('"""', jstart + 20)
judge_prompt = judge_src[jstart + len('JUDGE_SYS = """'):jend].strip()


def h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


out = [
    "# PROMPTS — 冻结提示词（含 SHA256，任何改动即哈希失配）", "",
    "## production_gate_prompt（qwen3.5-4b 证据语义门）", "",
    "sha256: " + h(SYS_PROMPT.strip()), "", "```text", SYS_PROMPT.strip(), "```", "",
    "## judge_audit_prompt（独立裁判盲评）", "",
    "sha256: " + h(judge_prompt), "", "```text", judge_prompt, "```", "",
    "## 解析层（判定合同的一部分，代码承载）", "",
    "- strict JSON parse → 未转义引号修复（_repair_unescaped_quotes）→ schema 兜底提取（_salvage_fields，decision 枚举校验，缺失即 CALL_FAILED，绝不猜测）",
    "- 代码：code/independent_eval/lmstudio_provider.py",
]
dst = ROOT / "release_final" / "configs" / "PROMPTS.txt"
dst.write_text("\n".join(out), encoding="utf-8")
print("PROMPTS.txt written:", dst, "gate sha:", h(SYS_PROMPT.strip())[:16])
