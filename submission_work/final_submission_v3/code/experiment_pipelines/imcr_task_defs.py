# -*- coding: utf-8 -*-
"""IMCR 任务定义：5 类任务的盲化白名单、allowed labels 与 prompt 模板。

本模块是 build_judge_payloads.py / run_judges.py / build_imcr_consensus.py
三个管线脚本的共享定义层。所有 judge 决策标签严格遵循 GOAL.md 第八至十一节：

* entity_type        : 16 个实际存在类型 + OTHER（GOAL 8.1）
* relation_contract  : valid / invalid / context_only / insufficient_evidence（GOAL 8.2）
* scope_adjustment   : A_BETTER / B_BETTER / EQUIVALENT / BOTH_WRONG /
                       INSUFFICIENT_EVIDENCE（GOAL 第九节 A/B 盲化比较；
                       A/B 与 before/after 的对应关系只存于独立映射文件）
* identity_pair      : same_entity / different_entity / insufficient_evidence（GOAL 10.3）
* provenance_support : fully_supported / partially_supported / unsupported /
                       contradicted / insufficient_evidence（GOAL 11.3）

标签命名约定：scope_adjustment 的 judge 只看到匿名的 a/b 两个状态，
因此其标签用 A_/B_ 前缀；共识聚合后由 build_imcr_consensus.py 依据
A/B 映射文件解码回 BEFORE_/AFTER_ 语义。

只依赖标准库 + independent_eval 包（复用 TaskSpec / build_blind_payload，
不重写任何指标或盲化逻辑）。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# 路径引导：使本模块可被 experiment_pipelines 下的脚本与 code/tests 下的
# pytest 直接 import（不修改任何已有文件，只在内存中调整 sys.path）。
# ---------------------------------------------------------------------------
CODE_DIR = Path(__file__).resolve().parents[1]
for _p in (str(CODE_DIR), str(CODE_DIR / "independent_eval")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from blind_payload import TaskSpec  # noqa: E402  (路径引导之后)
from _common import MASTER_SEED, V3_ROOT, derive_seed  # noqa: E402

PROMPT_VERSION = "imcr.v3.1"

EXP08 = V3_ROOT / "experiments" / "08_independent_reference"
EXP10 = V3_ROOT / "experiments" / "10_structural_validation"
EXP11 = V3_ROOT / "experiments" / "11_identity_validation"
EXP12 = V3_ROOT / "experiments" / "12_provenance_validation"

# ---------------------------------------------------------------------------
# allowed labels（GOAL 第八至十一节）
# ---------------------------------------------------------------------------

ENTITY_TYPE_LABELS: tuple[str, ...] = (
    "Person",
    "Event",
    "Place",
    "Organization",
    "Institution",
    "Concept",
    "Document",
    "Artifact",
    "CreativeWork",
    "Spirit",
    "ValueFacet",
    "AdministrativeRegion",
    "CulturalSite",
    "SocialGroup",
    "Position",
    "TimePeriod",
    "OTHER",
)

RELATION_CONTRACT_LABELS: tuple[str, ...] = (
    "valid",
    "invalid",
    "context_only",
    "insufficient_evidence",
)

SCOPE_ADJUSTMENT_LABELS: tuple[str, ...] = (
    "A_BETTER",
    "B_BETTER",
    "EQUIVALENT",
    "BOTH_WRONG",
    "INSUFFICIENT_EVIDENCE",
)

IDENTITY_PAIR_LABELS: tuple[str, ...] = (
    "same_entity",
    "different_entity",
    "insufficient_evidence",
)

PROVENANCE_SUPPORT_LABELS: tuple[str, ...] = (
    "fully_supported",
    "partially_supported",
    "unsupported",
    "contradicted",
    "insufficient_evidence",
)

# ---------------------------------------------------------------------------
# 类型 / role 定义（随 payload 提供给 judge 的冻结 Schema 说明，GOAL 7.1 第 4/5 条）
# ---------------------------------------------------------------------------

ENTITY_TYPE_DEFINITIONS: dict[str, str] = {
    "Person": "人物：历史个体人物。",
    "Event": "事件：具有明确时间与/或空间 anchoring 的历史事件、战役、会议、行动等。",
    "Place": "地点：具体地名、地址、场所（非正式行政区划实体）。",
    "Organization": "组织：党派、军队、团体、机关等组织实体。",
    "Institution": "机构：学校、报社、书店、医院等制度性机构。",
    "Concept": "概念：抽象思想、方针、口号、主义等概念性实体。",
    "Document": "文献：文件、宣言、指示信、报刊文章、书籍等文本载体。",
    "Artifact": "实物：武器、票证、器物等可移动文物/实物。",
    "CreativeWork": "创作作品：诗歌、戏剧、歌曲、美术作品等创作成果。",
    "Spirit": "精神：被命名的革命精神、传统（如“长征精神”）。",
    "ValueFacet": "价值面向：价值观念的一个面向或维度。",
    "AdministrativeRegion": "行政区划：正式建制行政区（省、县、区等）。",
    "CulturalSite": "文化遗址：遗址、纪念地、旧址等不可移动文化场所。",
    "SocialGroup": "社会群体：阶层、群体、集体身份（如“贫农”“知识青年”）。",
    "Position": "职务：职位、身份角色（如“县委书记”）。",
    "TimePeriod": "时期：被命名的历史时间段（如“抗战时期”）。",
    "OTHER": "以上类型均不适用，或证据不足以归入任何一类。",
}

TIME_ROLE_DEFINITIONS: dict[str, str] = {
    "event_occurrence": "事件发生时间：该时间是事件本身发生的时间。",
    "relation_validity": "关系有效时间：该时间是主客体之间关系成立/有效的时间。",
    "biographical": "人物生平时间：该时间属于人物的生卒、任职等生平信息。",
    "creation_or_publication": "创作或发表时间：该时间是文献/作品的创作或发表时间。",
    "commemoration_or_reception": "纪念或接受时间：该时间是后世纪念、评价、接受活动的时间。",
    "source_document_time": "来源文献时间：该时间只是来源文献自身的时间。",
    "context_time": "背景时间：该时间仅提供历史背景，不属于该断言。",
    "unknown": "无法判断。",
}

SPACE_ROLE_DEFINITIONS: dict[str, str] = {
    "event_location": "事件发生地：该空间是事件本身发生的地点。",
    "relation_location": "关系所在地：该空间是主客体关系成立的空间范围。",
    "biographical_location": "人物籍贯/生平地：该空间属于人物生平信息。",
    "creation_or_publication_location": "创作或发表地：该空间是文献/作品的创作或发表地点。",
    "commemoration_or_reception_location": "纪念或接受地：该空间是后世纪念/接受活动的地点。",
    "context_location": "背景地点：该空间仅提供背景，不属于该断言。",
    "unknown": "无法判断。",
}

# ---------------------------------------------------------------------------
# TaskSpec（白名单）。allowed_fields 之外的所有字段一律不进入 payload；
# before/after 经 build_blind_payload 匿名化为 a/b。
# ---------------------------------------------------------------------------

PIPELINE_TASK_SPECS: dict[str, TaskSpec] = {
    "entity_type": TaskSpec(
        task_type="entity_type",
        allowed_fields=(
            "task_id",
            "entity_name",
            "aliases",
            "context_assertions",
            "source_excerpt",
            "candidate_types",
            "type_definitions",
        ),
        allowed_labels=ENTITY_TYPE_LABELS,
        blind_source_type=True,
        prompt_version=PROMPT_VERSION,
    ),
    "relation_contract": TaskSpec(
        task_type="relation_contract",
        allowed_fields=(
            "task_id",
            "subject_text",
            "subject_type",
            "relation_text",
            "object_text",
            "object_type",
            "evidence_excerpts",
            "schema_definitions",
        ),
        allowed_labels=RELATION_CONTRACT_LABELS,
        blind_source_type=True,
        prompt_version=PROMPT_VERSION,
    ),
    "scope_adjustment": TaskSpec(
        task_type="scope_adjustment",
        allowed_fields=(
            "task_id",
            "assertion_text",
            "evidence_excerpts",
            "evidence_availability_note",
            "local_relation_context",
            "schema_definitions",
            "before",
            "after",
        ),
        allowed_labels=SCOPE_ADJUSTMENT_LABELS,
        ab_fields=("before", "after"),
        blind_source_type=True,
        prompt_version=PROMPT_VERSION,
    ),
    "identity_pair": TaskSpec(
        task_type="identity_pair",
        allowed_fields=(
            "task_id",
            "name_a",
            "name_b",
            "aliases_a",
            "aliases_b",
            "relation_context_a",
            "relation_context_b",
            "time_info_a",
            "time_info_b",
            "space_info_a",
            "space_info_b",
            "evidence_a",
            "evidence_b",
        ),
        allowed_labels=IDENTITY_PAIR_LABELS,
        blind_source_type=True,
        prompt_version=PROMPT_VERSION,
    ),
    "provenance_support": TaskSpec(
        task_type="provenance_support",
        allowed_fields=(
            "task_id",
            "assertion_text",
            "evidence_excerpts",
            "citation_metadata",
        ),
        allowed_labels=PROVENANCE_SUPPORT_LABELS,
        blind_source_type=True,
        prompt_version=PROMPT_VERSION,
    ),
}

# ---------------------------------------------------------------------------
# Prompt 模板（GOAL 7.3 输出 schema 固定；每任务单独说明与 allowed labels）
# ---------------------------------------------------------------------------

_OUTPUT_SCHEMA_ZH = """\
输出要求（严格遵守）：
只输出一个 JSON 对象，不要输出任何其他文字、不要使用 markdown 代码块。字段：
{
  "task_id": "<原样回填输入中的 task_id>",
  "decision": "<允许标签之一>",
  "confidence": <0 到 1 之间的小数，表示你对该判断的把握>,
  "evidence": [<支撑该判断的证据摘录或要点字符串数组>],
  "reason_code": "<简短机器可读原因码，如 CLEAR_MATCH / TYPE_MISMATCH / NO_EVIDENCE>",
  "explanation": "<中文简要说明>",
  "insufficient_evidence": <true/false，证据不足时为 true>
}"""

PROMPT_TEMPLATES: dict[str, str] = {
    "entity_type": f"""\
你是知识图谱实体类型审校专家。给定一个实体名称、其别名、它在语料中参与的关系上下文，
以及（如有）原始文献节选，请判断该实体最合理的类型。
只允许从 candidate_types 列出的类型中选择一个；type_definitions 给出各类型的定义。
不要臆测输入之外的信息；证据不足或不属于任何候选类型时选择 OTHER。
{_OUTPUT_SCHEMA_ZH}""",
    "relation_contract": f"""\
你是知识图谱关系语义审校专家。给定主语实体（名称与类型）、关系谓词、宾语实体（名称与类型），
以及（如有）原始证据文本，请判断该关系断言的语义状态：
- valid：关系语义成立，且与主客体类型相容，可以进入严格语义层；
- invalid：关系语义不成立，或与主客体类型明显不相容；
- context_only：关系可能真实但证据或语义强度不足，只应作为上下文信息保留；
- insufficient_evidence：信息不足，无法判断。
schema_definitions 字段给出类型相容性约定的摘要。
{_OUTPUT_SCHEMA_ZH}""",
    "scope_adjustment": f"""\
你是历史文献时空语义审校专家。给定一条知识断言（主语—谓词—宾语及其时间、空间表述）与
（如有）证据文本，并给出该断言时空归属的两种候选状态 a 与 b（每种状态给出 time_role /
time_owner / space_role / space_owner；owner 为 null 表示该时间/空间不归属于任何单一实体，
仅作为关系层面的有效范围或背景）。
schema_definitions 给出各 role 的定义。你不知道 a、b 各对应系统的哪个版本，请仅依据语义
与证据独立判断：
- A_BETTER：状态 a 的时空归属更合理；
- B_BETTER：状态 b 更合理；
- EQUIVALENT：两者同样合理；
- BOTH_WRONG：两者都不合理；
- INSUFFICIENT_EVIDENCE：证据不足，无法比较。
{_OUTPUT_SCHEMA_ZH}""",
    "identity_pair": f"""\
你是实体消歧审校专家。给定两个名称（及各自别名、独立的关系上下文、时间信息、空间信息、
以及如有来源证据），判断它们是否指向同一个现实世界实体：
- same_entity：同一名称实体的不同提及/变体，应合并；
- different_entity：虽然名称相同或相似，但指向不同实体（如同名人物、机构与地名同名）；
- insufficient_evidence：信息不足，无法判断。
注意：同名不等于同实体；请依据上下文、时间、空间与证据综合判断。
{_OUTPUT_SCHEMA_ZH}""",
    "provenance_support": f"""\
你是知识断言来源支持度审校专家。给定一条知识断言（主语—谓词—宾语，以及时间、空间表述）
和其声明的来源文献原文摘录，请判断来源文本对该断言的支持程度：
- fully_supported：来源文本完整支持该断言的全部要素（主语、谓词、宾语及时间/空间，如有）；
- partially_supported：来源文本只支持断言的部分要素；
- unsupported：来源文本与该断言无关，不能支持它；
- contradicted：来源文本与该断言相矛盾；
- insufficient_evidence：未提供来源文本或文本过短，无法判断。
{_OUTPUT_SCHEMA_ZH}""",
}

# ---------------------------------------------------------------------------
# 原始样本 → 盲化 record 的转换器
# ---------------------------------------------------------------------------


def _none_if_empty(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _parse_json_list(value: Any) -> list[Any]:
    """容忍 CSV 中以 JSON 字符串存储的列表；失败时返回空列表。"""
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def entity_type_record(row: Mapping[str, str]) -> dict[str, Any]:
    """ENTITY_TYPE_SAMPLE.csv 一行 → 盲化 record。"""
    return {
        "task_id": row["sample_id"],
        "entity_name": row["canonical_name"],
        "aliases": _parse_json_list(row.get("aliases_json")),
        "context_assertions": row.get("context_assertions") or "",
        "source_excerpt": row.get("source_excerpt") or "",
        "candidate_types": list(ENTITY_TYPE_LABELS),
        "type_definitions": ENTITY_TYPE_DEFINITIONS,
    }


def relation_contract_record(
    row: Mapping[str, str],
    evidence_by_fact: Mapping[str, list[str]] | None = None,
) -> dict[str, Any]:
    """RELATION_CONTRACT_SAMPLE.csv 一行 → 盲化 record。

    绝不转发 risk_tier / semantic_status / release_tier / changed_set_*_tier /
    sample_role 等生产标签；evidence_excerpts 仅当该 fact_id 在来源支持样本中
    存在真实证据文本时附带（否则为空列表，judge 可判 insufficient_evidence）。
    """
    evidence: list[str] = []
    if evidence_by_fact:
        evidence = list(evidence_by_fact.get(row["fact_id"], []))
    schema_note = (
        "严格语义层准入约定摘要：关系须语义成立且与主客体类型相容；"
        "时空角色归属类谓词（如 active_at/occurred_at）要求时间与空间归属于"
        "类型允许的 owner；证据或语义强度不足的关系只应作为上下文保留。"
    )
    return {
        "task_id": row["sample_id"],
        "subject_text": row["subject_name"],
        "subject_type": row["subject_type"],
        "relation_text": row["predicate"],
        "object_text": row["object_name"],
        "object_type": row["object_type"],
        "evidence_excerpts": evidence,
        "schema_definitions": schema_note,
    }


def _format_owner(owner: Any) -> str | None:
    if not owner:
        return None
    if isinstance(owner, Mapping):
        name = owner.get("name")
        otype = owner.get("type")
        if name and otype:
            return f"{name}（{otype}）"
        return name
    return str(owner)


def _format_scope_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """把 state_a/state_b 转成 judge 可读的匿名状态（去掉实体内部 ID）。"""
    return {
        "time_role": state.get("time_role"),
        "time_owner": _format_owner(state.get("time_owner")),
        "space_role": state.get("space_role"),
        "space_owner": _format_owner(state.get("space_owner")),
    }


def scope_adjustment_record(
    task: Mapping[str, Any],
    ab_mapping: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    """SCOPE_ADJUSTMENT_TASKS.jsonl 一条 → 盲化 record。

    state_a/state_b 先依据既有 SCOPE_ADJUSTMENT_AB_MAPPING.csv 解析为
    before/after 语义，再交给 build_blind_payload 以 v3 种子重新随机化为
    a/b 展示顺序；payload 中不出现 before/after 字样。
    """
    task_id = task["task_id"]
    mapping = ab_mapping[task_id]
    states = {"state_a": task["state_a"], "state_b": task["state_b"]}
    before_state = (
        states["state_a"]
        if mapping["state_a_corresponds_to"] == "before"
        else states["state_b"]
    )
    after_state = states["state_b"] if mapping["state_b_corresponds_to"] == "after" else states["state_a"]

    ctx = task["assertion_context"]
    parts = [
        f"断言：{ctx.get('subject_name')}（{ctx.get('subject_type')}）"
        f" —{ctx.get('predicate')}→ {ctx.get('object_name')}（{ctx.get('object_type')}）"
    ]
    time_bits = [
        bit
        for bit in (
            f"规范表述：{ctx.get('normalized_time_label')}" if ctx.get("normalized_time_label") else None,
            f"原始表述：{ctx.get('time_raw')}" if ctx.get("time_raw") else None,
            (
                f"区间：{ctx.get('time_start')} 至 {ctx.get('time_end')}"
                if ctx.get("time_start") or ctx.get("time_end")
                else None
            ),
            f"精度：{ctx.get('time_precision')}" if ctx.get("time_precision") else None,
        )
        if bit
    ]
    if time_bits:
        parts.append("时间：" + "；".join(time_bits))
    space_bits = [
        bit
        for bit in (
            f"原始表述：{ctx.get('place_raw')}" if ctx.get("place_raw") else None,
            f"省：{ctx.get('province')}" if ctx.get("province") else None,
            f"市：{ctx.get('city')}" if ctx.get("city") else None,
            f"县：{ctx.get('county')}" if ctx.get('county') else None,
        )
        if bit
    ]
    if space_bits:
        parts.append("空间：" + "；".join(space_bits))

    prov = task.get("provenance") or {}
    local_ctx = {
        "source_predicates": prov.get("source_predicates") or [],
        "record_count": prov.get("record_count"),
    }
    evidence_text = task.get("source_evidence_text")
    return {
        "task_id": task_id,
        "assertion_text": "\n".join(parts),
        "evidence_excerpts": [evidence_text] if evidence_text else [],
        "evidence_availability_note": task.get("source_evidence_text_note") or "",
        "local_relation_context": local_ctx,
        "schema_definitions": {
            "time_role": TIME_ROLE_DEFINITIONS,
            "space_role": SPACE_ROLE_DEFINITIONS,
        },
        "before": _format_scope_state(before_state),
        "after": _format_scope_state(after_state),
    }


def identity_pair_record(task: Mapping[str, Any]) -> dict[str, Any]:
    """IDENTITY_PAIR_TASKS.jsonl 一条 → 盲化 record。"""
    return {
        "task_id": task["pair_id"],
        "name_a": task.get("name_a"),
        "name_b": task.get("name_b"),
        "aliases_a": _parse_json_list(task.get("aliases_a")),
        "aliases_b": _parse_json_list(task.get("aliases_b")),
        "relation_context_a": task.get("relation_context_a") or [],
        "relation_context_b": task.get("relation_context_b") or [],
        "time_info_a": task.get("time_info_a") or [],
        "time_info_b": task.get("time_info_b") or [],
        "space_info_a": task.get("space_info_a") or "",
        "space_info_b": task.get("space_info_b") or "",
        "evidence_a": task.get("evidence_a") or "",
        "evidence_b": task.get("evidence_b") or "",
    }


def provenance_support_record(row: Mapping[str, str]) -> dict[str, Any]:
    """PROVENANCE_SUPPORT_SAMPLE.csv 一行 → 盲化 record。"""
    predicate_zh = row.get("predicate_label_zh") or row.get("predicate")
    assertion = (
        f"{row['subject_name']} —{row['predicate']}（{predicate_zh}）→ {row['object_name']}"
    )
    extras = []
    if row.get("time_label") or row.get("time_raw"):
        extras.append(f"时间：{row.get('time_label') or row.get('time_raw')}")
    if row.get("place_text"):
        extras.append(f"空间：{row['place_text']}")
    if extras:
        assertion += "\n" + "；".join(extras)
    evidence_texts = [
        chunk.strip()
        for chunk in (row.get("evidence_texts") or "").split("\n---\n")
        if chunk.strip()
    ]
    return {
        "task_id": row["sample_id"],
        "assertion_text": assertion,
        "evidence_excerpts": evidence_texts,
        "citation_metadata": {"source_titles": row.get("source_titles") or ""},
    }


# ---------------------------------------------------------------------------
# 任务注册表：输入文件、转换器、输出文件名
# ---------------------------------------------------------------------------

TASK_REGISTRY: dict[str, dict[str, Any]] = {
    "entity_type": {
        "input": EXP08 / "ENTITY_TYPE_SAMPLE.csv",
        "output": "ENTITY_TYPE_PAYLOADS.jsonl",
        "kind": "csv",
    },
    "relation_contract": {
        "input": EXP08 / "RELATION_CONTRACT_SAMPLE.csv",
        "output": "RELATION_CONTRACT_PAYLOADS.jsonl",
        "kind": "csv",
    },
    "scope_adjustment": {
        "input": EXP10 / "SCOPE_ADJUSTMENT_TASKS.jsonl",
        "ab_mapping_input": EXP10 / "SCOPE_ADJUSTMENT_AB_MAPPING.csv",
        "output": "SCOPE_ADJUSTMENT_PAYLOADS.jsonl",
        "ab_mapping_output": "SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING.csv",
        "kind": "jsonl",
    },
    "identity_pair": {
        "input": EXP11 / "IDENTITY_PAIR_TASKS.jsonl",
        "output": "IDENTITY_PAIR_PAYLOADS.jsonl",
        "kind": "jsonl",
    },
    "provenance_support": {
        "input": EXP12 / "PROVENANCE_SUPPORT_SAMPLE.csv",
        "output": "PROVENANCE_SUPPORT_PAYLOADS.jsonl",
        "kind": "csv",
    },
}

ALL_TASK_TYPES: tuple[str, ...] = tuple(TASK_REGISTRY.keys())


def task_seed(task_type: str) -> int:
    """每任务类型的 A/B 随机化种子（派生自 v3 主种子 20260907）。"""
    return derive_seed(f"imcr_payload_{task_type}", MASTER_SEED)


def load_evidence_by_fact(path: Path | None = None) -> dict[str, list[str]]:
    """fact_id → 真实证据文本列表（来自 PROVENANCE_SUPPORT_SAMPLE.csv）。

    供 relation_contract 任务在 fact_id 命中时附带真实证据；未命中不附带。
    """
    path = path or (EXP12 / "PROVENANCE_SUPPORT_SAMPLE.csv")
    out: dict[str, list[str]] = {}
    if not path.exists():
        return out
    for row in read_csv_rows(path):
        texts = [
            chunk.strip()
            for chunk in (row.get("evidence_texts") or "").split("\n---\n")
            if chunk.strip()
        ]
        if texts:
            out[row["fact_id"]] = texts
    return out
