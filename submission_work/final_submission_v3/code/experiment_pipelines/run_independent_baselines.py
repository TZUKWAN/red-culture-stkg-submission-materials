# -*- coding: utf-8 -*-
"""run_independent_baselines.py — 在 IMCR 五个任务集上产出独立基线 B1–B12（B3 除外）。

设计规范：audit/04_BASELINE_DESIGN.md（实现逐条遵守；偏离须先改该文件）。

用法：

    # 全量（对冻结样本/冻结 sidecar/只读 release 库）
    python run_independent_baselines.py

    # 合并 B3 盲 LLM 行（run_blind_llm_baseline.py 产物）后写最终 runs
    python run_independent_baselines.py \
        --append-runs experiments/09_independent_baselines/IMCR_BLIND_LLM_RUNS.csv

    # 小样本冒烟（每任务型最多 N 条）
    python run_independent_baselines.py --limit 5 --out-dir <tmp>

行为契约：
* 任务集：entity_type(382) / relation_contract(640) / scope_adjustment(208) /
  identity_pair(600) / provenance_support(1000)，样本与 sidecar 元数据一律读
  冻结文件（08/10/11/12 号实验目录），生产置信等 sidecar 缺失字段按
  fact_id/entity_id 只读直查 release 库（sidecar 优先）。
* 方法：B1 规则、B2 冻结分类器、B4 规则+分类器、B5 规则+盲 LLM、B7 margin、
  B8 归一化熵、B9 一致门、B10/B11 消融、B12 生产映射；B6 不另发行（≡B2 扫描）；
  B3 由 run_blind_llm_baseline.py 单独产出并经 --append-runs 合并。
* 23 列 schema 与 v2 BASELINE_RUNS.csv 完全同构；固定取值见 §2：
  split=independent_eval、evidence_class=actual_run、covered=correct=safe_correct=0
  （由 run_selective_inference.py 按参考标签重算）、gold_label 空。
* 方法×任务网格完整：设计矩阵 N/A 的单元格同样逐样本落盘
  availability_status=not_available（prediction/confidence 空，note 注明原因）。
* 泄漏红线：绝不读取 experiments/08_independent_reference/raw_runs/ 下任何
  judge 输出；绝不使用 RELATION_CONTRACT_SAMPLE.csv 的
  changed_set_*_tier/seed_* 列作为特征或预测。
* 输出（experiments/09_independent_baselines/）：
  - IMCR_BASELINE_RUNS.csv      23 列预测行（--append-runs 键去重合并，后写覆盖）
  - BASELINE_AVAILABILITY_MATRIX.csv   方法×任务 状态/行数/原因
  - INDEPENDENT_BASELINE_AUDIT.json    result=PASS 门（网格完整等）
  - INDEPENDENT_BASELINE_MANIFEST.json GOAL-21 manifest（NOT_AVAILABLE 注册表、
    映射策略版本、DB SHA-256）
* 全程幂等：同输入重跑产出一致文件；合并去重（sample_id+task_type+method_id，
  后写覆盖）。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

CODE_DIR = Path(__file__).resolve().parents[1]
_EXTERNAL = CODE_DIR.parent / "data" / "external_inputs"
for _p in (
    str(CODE_DIR),
    str(CODE_DIR / "independent_eval"),
    str(Path(__file__).resolve().parent),
    str(_EXTERNAL),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import (  # noqa: E402  (路径引导之后)
    MASTER_SEED,
    REPO_ROOT,
    V3_ROOT,
    connect_final,
    now_iso,
    write_csv,
)
import imcr_task_defs as defs  # noqa: E402
from manifest import build_manifest, sha256_file, sha256_text  # noqa: E402
from manifest import write_manifest as write_manifest_json  # noqa: E402
from stkg_contract import RELATIONS, strong_entity_type_hint  # noqa: E402
from stkg_v2_semantics import (  # noqa: E402
    TYPE_FAMILY,
    entity_model_contraindication,
    fuse_entity_type,
    refine_lexical_hint,
)

EXP09 = V3_ROOT / "experiments" / "09_independent_baselines"
EXP08 = defs.EXP08
EXP10 = defs.EXP10
EXP11 = defs.EXP11
EXP12 = defs.EXP12

CLASSIFIER_DB = REPO_ROOT / "data" / "source_data" / "stkg_v2_entity_classifier.sqlite"
CLASSIFIER_MODEL = REPO_ROOT / "data" / "source_data" / "stkg_v2_entity_classifier.joblib"

RUNS_NAME = "IMCR_BASELINE_RUNS.csv"
MATRIX_NAME = "BASELINE_AVAILABILITY_MATRIX.csv"
AUDIT_NAME = "INDEPENDENT_BASELINE_AUDIT.json"
MANIFEST_NAME = "INDEPENDENT_BASELINE_MANIFEST.json"
BLIND_RUNS_NAME = "IMCR_BLIND_LLM_RUNS.csv"
BLIND_LOG_DIR = "blind_llm_runs"

#: 23 列 schema（§2，与 v2 BASELINE_RUNS.csv 完全同构）
RUNS_FIELDS: tuple[str, ...] = (
    "sample_id", "task_type", "item_id", "split", "method_id", "method_name",
    "evidence_class", "comparison_tier", "overlap_status",
    "primary_comparison_eligible", "evaluation_eligibility",
    "availability_status", "gold_label", "prediction", "confidence",
    "covered", "correct", "hard_constraint_pass", "constraint_gate_source",
    "safe_correct", "actual_llm_calls", "source_artifact", "note",
)

ALL_TASKS: tuple[str, ...] = defs.ALL_TASK_TYPES

#: 方法注册表：本管线产出预测行的 11 个方法及其任务型支持（§3 可用性矩阵）。
#: B3 由独立脚本产出、B6 ≡ B2 置信扫描不另发行——二者只出现在可用性矩阵。
METHODS: dict[str, dict[str, Any]] = {
    "B1_rule_only": {
        "name": "Rule-only",
        "tasks": frozenset({"entity_type", "relation_contract"}),
    },
    "B2_frozen_classifier": {
        "name": "Frozen classifier",
        "tasks": frozenset({"entity_type"}),
    },
    "B4_rule_plus_classifier": {
        "name": "Rule+classifier",
        "tasks": frozenset({"entity_type"}),
    },
    "B5_rule_plus_blind_llm": {
        "name": "Rule+blind LLM",
        "tasks": frozenset({"entity_type", "relation_contract"}),
    },
    "B7_classifier_margin": {
        "name": "Classifier margin",
        "tasks": frozenset({"entity_type"}),
    },
    "B8_entropy_threshold": {
        "name": "Entropy threshold",
        "tasks": frozenset({"entity_type"}),
    },
    "B9_rule_model_agreement": {
        "name": "Rule-model agreement gate",
        "tasks": frozenset({"entity_type", "relation_contract"}),
    },
    "B10_selective_no_structural_gate": {
        "name": "Selective, no structural gate",
        "tasks": frozenset(ALL_TASKS),
    },
    "B11_structural_gate_no_abstention": {
        "name": "Structural gate, no abstention",
        "tasks": frozenset(ALL_TASKS),
    },
    "B12_full_framework": {
        "name": "Full framework",
        "tasks": frozenset(ALL_TASKS),
    },
}
METHOD_ORDER: tuple[str, ...] = tuple(METHODS)

#: 矩阵里只报告、不由本管线发行的方法
MATRIX_ONLY_METHODS: dict[str, dict[str, str]] = {
    "B3_blind_llm": {
        "name": "Blind LLM (fresh)",
        "pending_reason": (
            "fresh blind LLM run pending; produce via run_blind_llm_baseline.py "
            "and merge via --append-runs"
        ),
    },
    "B6_classifier_conf_threshold": {
        "name": "Classifier confidence threshold",
        "pending_reason": (
            "B6 is the B2 confidence-threshold sweep (no separate rows by design)"
        ),
    },
}

#: 生产字段映射策略版本（§4；改动任何映射规则必须升版本并更新设计文档）
MAPPING_STRATEGY_VERSION = "imcr-baseline-mapping.v1"
MAPPING_SPEC: dict[str, Any] = {
    "entity_type": "prediction=research_entities.entity_type; "
    "confidence=research_entities.confidence; "
    "gate=type_validation_status=='validated'",
    "relation_contract": "release_tier mapping: strict_semantic->valid, "
    "contextual->context_only, unresolved->insufficient_evidence; "
    "invalid never predicted; confidence=research_assertions.confidence; "
    "gate=semantic_status=='auto_accepted' AND risk_tier in {A,B}",
    "scope_adjustment": "prediction=constant AFTER_BETTER (post-closure state "
    "is the system claim); confidence withheld (no graded confidence field); gate=1",
    "identity_pair": "prediction=research_entity_members co-membership: same "
    "canonical_entity_id -> same_entity else different_entity; confidence "
    "withheld; gate=1",
    "provenance_support": "research_tier mapping: strict_semantic->fully_supported, "
    "contextual->partially_supported, unresolved->insufficient_evidence; "
    "unsupported/contradicted never predicted; confidence=research_assertions."
    "confidence (frozen sidecar); gate=n_provenance_rows>0",
}
MAPPING_SPEC_SHA256 = sha256_text(
    json.dumps(MAPPING_SPEC, ensure_ascii=False, sort_keys=True)
)

RELEASE_TIER_TO_IMCR: dict[str, str] = {
    "strict_semantic": "valid",
    "contextual": "context_only",
    "unresolved": "insufficient_evidence",
}
RESEARCH_TIER_TO_IMCR: dict[str, str] = {
    "strict_semantic": "fully_supported",
    "contextual": "partially_supported",
    "unresolved": "insufficient_evidence",
}

GATE_ENTITY_RULE = "TYPE_FAMILY membership + entity_model_contraindication"
GATE_RELATION_RULE = "research_relation_contract domain/range (prediction=='valid')"
GATE_CLASSIFIER = "frozen production class gate (entity_predictions.class_gate_pass)"
GATE_B12_ENTITY = "production type_validation_status=='validated'"
GATE_B12_RELATION = "production semantic_status=='auto_accepted' AND risk_tier in {A,B}"
GATE_B12_SCOPE = "production closure invariant (adjustment applied = part of release)"
GATE_B12_IDENTITY = "production canonical membership invariant (research_entity_members)"
GATE_B12_PROVENANCE = "release safety invariant n_provenance_rows>0"
GATE_B3_ENTITY = "TYPE_FAMILY membership + entity_model_contraindication (blind name)"
GATE_B3_RELATION = (
    "valid-claim requires research_relation_contract domain/range compatibility"
)
GATE_ABLATION_B10 = "ablation: structural gate disabled (hard_constraint_pass forced 1)"

SRC_B12 = "production_release_fields"
SRC_B1_ENTITY = "v2 rule engine (stkg_v2_semantics.fuse_entity_type + schema votes)"
SRC_B1_RELATION = "research_relation_contract"
SRC_B2 = "data/source_data/stkg_v2_entity_classifier.sqlite::entity_predictions"
SRC_B7 = SRC_B2 + " (margin column)"
SRC_B8 = "data/source_data/stkg_v2_entity_classifier.joblib (reloaded proba)"
SRC_B3 = "blind LLM fresh call on frozen IMCR payloads"
SRC_B12_IDENTITY = "research_entity_members"


# ---------------------------------------------------------------------------
# 输入路径（冻结产物；测试用 tmp fixture 替换）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InputPaths:
    """本管线全部输入文件路径（默认全部指向冻结产物）。"""

    entity_type_sample: Path = EXP08 / "ENTITY_TYPE_SAMPLE.csv"
    entity_type_metadata: Path = EXP08 / "ENTITY_TYPE_SAMPLE.sampling_metadata.csv"
    relation_contract_sample: Path = EXP08 / "RELATION_CONTRACT_SAMPLE.csv"
    scope_adjustment_tasks: Path = EXP10 / "SCOPE_ADJUSTMENT_TASKS.jsonl"
    identity_pair_tasks: Path = EXP11 / "IDENTITY_PAIR_TASKS.jsonl"
    identity_pair_metadata: Path = EXP11 / "IDENTITY_PAIR_METADATA.csv"
    provenance_sample: Path = EXP12 / "PROVENANCE_SUPPORT_SAMPLE.csv"
    provenance_metadata: Path = EXP12 / "PROVENANCE_SUPPORT_METADATA.csv"
    classifier_db: Path = CLASSIFIER_DB
    classifier_model: Path = CLASSIFIER_MODEL


def default_input_paths() -> InputPaths:
    return InputPaths()


# ---------------------------------------------------------------------------
# 任务样本装载
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskSample:
    """一个 IMCR 评价样本（23 列行键 + 各任务型的预测所需字段）。"""

    sample_id: str
    task_type: str
    item_id: str
    fields: Mapping[str, Any]


def load_samples(inputs: InputPaths, limit: int | None) -> dict[str, list[TaskSample]]:
    """按任务型装载冻结样本（§1 命名空间）；limit 只用于冒烟。"""

    def _cap(rows: list[TaskSample]) -> list[TaskSample]:
        return rows[:limit] if limit is not None else rows

    samples: dict[str, list[TaskSample]] = {}

    # entity_type：样本 + sidecar（production_entity_type/type_validation_status）
    meta_et = {r["sample_id"]: r for r in defs.read_csv_rows(inputs.entity_type_metadata)}
    rows: list[TaskSample] = []
    for r in defs.read_csv_rows(inputs.entity_type_sample):
        m = meta_et.get(r["sample_id"], {})
        rows.append(
            TaskSample(
                r["sample_id"],
                "entity_type",
                r["entity_id"],
                {
                    "production_entity_type": m.get("production_entity_type", ""),
                    "type_validation_status": m.get("type_validation_status", ""),
                },
            )
        )
    samples["entity_type"] = _cap(rows)

    # relation_contract：release_tier/semantic_status/risk_tier 来自冻结样本；
    # changed_set_*/seed_* 列一律不读（泄漏红线）。
    rows = []
    for r in defs.read_csv_rows(inputs.relation_contract_sample):
        rows.append(
            TaskSample(
                r["sample_id"],
                "relation_contract",
                r["fact_id"],
                {
                    "predicate": r["predicate"],
                    "subject_type": r["subject_type"],
                    "object_type": r["object_type"],
                    "release_tier": r["release_tier"],
                    "semantic_status": r["semantic_status"],
                    "risk_tier": r["risk_tier"],
                },
            )
        )
    samples["relation_contract"] = _cap(rows)

    # scope_adjustment：prediction 恒 AFTER_BETTER，只需 task_id/fact_id
    rows = []
    for r in defs.read_jsonl(inputs.scope_adjustment_tasks):
        rows.append(TaskSample(r["task_id"], "scope_adjustment", r["fact_id"], {}))
    samples["scope_adjustment"] = _cap(rows)

    # identity_pair：entity_a_id/entity_b_id 来自冻结 metadata sidecar
    meta_idp = {r["pair_id"]: r for r in defs.read_csv_rows(inputs.identity_pair_metadata)}
    rows = []
    for r in defs.read_jsonl(inputs.identity_pair_tasks):
        m = meta_idp.get(r["pair_id"], {})
        rows.append(
            TaskSample(
                r["pair_id"],
                "identity_pair",
                r["pair_id"],
                {
                    "entity_a_id": m.get("entity_a_id", ""),
                    "entity_b_id": m.get("entity_b_id", ""),
                },
            )
        )
    samples["identity_pair"] = _cap(rows)

    # provenance_support：research_tier/confidence/n_provenance_rows 来自冻结 sidecar
    meta_prv = {r["sample_id"]: r for r in defs.read_csv_rows(inputs.provenance_metadata)}
    rows = []
    for r in defs.read_csv_rows(inputs.provenance_sample):
        m = meta_prv.get(r["sample_id"], {})
        rows.append(
            TaskSample(
                r["sample_id"],
                "provenance_support",
                r["fact_id"],
                {
                    "research_tier": m.get("research_tier", ""),
                    "confidence": m.get("confidence", ""),
                    "n_provenance_rows": m.get("n_provenance_rows", ""),
                },
            )
        )
    samples["provenance_support"] = _cap(rows)
    return samples


# ---------------------------------------------------------------------------
# 只读资源装载（release 库 / 冻结分类器表）
# ---------------------------------------------------------------------------


def _attached_db_paths(con) -> dict[str, str]:
    """连接的数据库文件路径（供 manifest 记 SHA；main=final 库，sem=语义库）。"""
    return {str(name): str(path) for _seq, name, path in con.execute("pragma database_list")}


def load_release_entities(con, entity_ids: set[str]) -> dict[str, dict[str, Any]]:
    """research_entities 的发布类型与置信（§4.1；sidecar 缺置信字段故直查）。"""
    out: dict[str, dict[str, Any]] = {}
    for eid in entity_ids:
        row = con.execute(
            "select entity_type, confidence from research_entities where entity_id=?",
            (eid,),
        ).fetchone()
        if row is not None:
            out[eid] = {
                "entity_type": row["entity_type"],
                "confidence": None if row["confidence"] is None else float(row["confidence"]),
            }
    return out


def load_member_map(con, canonical_ids: set[str]) -> dict[str, list[dict[str, str]]]:
    """规范实体 → 源级成员（含 mapping_status=self 行）。

    已核实列名：research_entity_members(source_entity_id, canonical_entity_id,
    source_canonical_name, source_entity_type, semantic_entity_type,
    source_semantic_status, mapping_status, mapping_reason, source_aliases_json)
    —— 该表没有 confidence 列；成员生产置信取自 sem.v2_entities.confidence。
    """
    out: dict[str, list[dict[str, str]]] = {cid: [] for cid in canonical_ids}
    for cid in canonical_ids:
        for row in con.execute(
            "select source_entity_id, source_canonical_name, source_entity_type,"
            " mapping_status from research_entity_members where canonical_entity_id=?",
            (cid,),
        ):
            out[cid].append(
                {
                    "source_entity_id": str(row["source_entity_id"]),
                    "source_canonical_name": str(row["source_canonical_name"]),
                    "source_entity_type": str(row["source_entity_type"]),
                    "mapping_status": str(row["mapping_status"]),
                }
            )
    return out


def load_v2_entities(con, entity_ids: set[str]) -> dict[str, dict[str, Any]]:
    """sem.v2_entities 行（源级规则输入与 B8 文本重建）。"""
    out: dict[str, dict[str, Any]] = {}
    for eid in entity_ids:
        row = con.execute(
            "select entity_id, canonical_name, source_entity_type, semantic_entity_type,"
            " aliases_json, confidence from sem.v2_entities where entity_id=?",
            (eid,),
        ).fetchone()
        if row is not None:
            out[str(row["entity_id"])] = {
                "canonical_name": str(row["canonical_name"]),
                "source_entity_type": str(row["source_entity_type"]),
                "semantic_entity_type": str(row["semantic_entity_type"] or ""),
                "aliases_json": str(row["aliases_json"] or "[]"),
                "confidence": None if row["confidence"] is None else float(row["confidence"]),
            }
    return out


def load_name_source_types(con) -> dict[str, set[str]]:
    """全库同名实体的 source_type 集合（v2 cross_type_name 信号，同 build_rule_resources）。"""
    out: dict[str, set[str]] = defaultdict(set)
    for row in con.execute("select canonical_name, source_entity_type from sem.v2_entities"):
        out[str(row["canonical_name"])].add(str(row["source_entity_type"]))
    return dict(out)


def load_schema_votes(con, member_ids: set[str]) -> dict[str, Counter]:
    """v2_assertion_scopes schema votes（全库统计，不限于样本断言；v2 同法）。

    与 v2 build_rule_resources 一致：谓词存在且 source/target 类型唯一时给
    subject/object 实体投该类型一票。
    """
    votes: dict[str, Counter] = defaultdict(Counter)
    for subject_id, predicate, object_id in con.execute(
        "select subject_id,predicate,object_id from sem.v2_assertion_scopes"
        " where predicate not like 'raw:%'"
    ):
        spec = RELATIONS.get(str(predicate))
        if spec is None:
            continue
        subject_id = str(subject_id)
        object_id = str(object_id)
        if subject_id in member_ids and len(spec.source_types) == 1:
            votes[subject_id][next(iter(spec.source_types))] += 1
        if object_id in member_ids and len(spec.target_types) == 1:
            votes[object_id][next(iter(spec.target_types))] += 1
    return dict(votes)


def load_relation_contract(con) -> dict[str, dict[str, frozenset[str]]]:
    """research_relation_contract：predicate → source/target 类型集。"""
    out: dict[str, dict[str, frozenset[str]]] = {}
    for row in con.execute(
        "select predicate, source_types_json, target_types_json from research_relation_contract"
    ):
        out[str(row["predicate"])] = {
            "source_types": frozenset(json.loads(str(row["source_types_json"]))),
            "target_types": frozenset(json.loads(str(row["target_types_json"]))),
        }
    return out


def load_assertion_confidence(con, fact_ids: set[str]) -> dict[str, float | None]:
    """research_assertions.confidence（§4.2）。"""
    out: dict[str, float | None] = {}
    for fid in fact_ids:
        row = con.execute(
            "select confidence from research_assertions where fact_id=?", (fid,)
        ).fetchone()
        out[fid] = None if row is None or row["confidence"] is None else float(row["confidence"])
    return out


def load_identity_membership(con) -> dict[str, str]:
    """source_entity_id → canonical_entity_id（§4.4 共属查询；全表一次装载）。"""
    return {
        str(row["source_entity_id"]): str(row["canonical_entity_id"])
        for row in con.execute(
            "select source_entity_id, canonical_entity_id from research_entity_members"
        )
    }


def load_classifier_scores(
    path: Path, entity_ids: set[str]
) -> tuple[dict[str, dict[str, Any]], str | None]:
    """冻结生产分类器分数表 entity_predictions（源级键；§5.2）。

    返回 ({entity_id: row}, error)；error 非 None 表示整表不可用。
    已核实列名：entity_id, canonical_name, source_type, predicted_type,
    confidence, margin, lexical_hint, schema_top_type,
    independent_signal_agreement, class_gate_threshold, class_gate_pass,
    eligible_rule_candidate。
    """
    import sqlite3

    if not path.exists():
        return {}, f"classifier score table missing: {path}"
    try:
        con = sqlite3.connect(f"file:{str(path).replace(chr(92), '/')}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return {}, f"classifier score table unreadable: {exc}"
    try:
        out: dict[str, dict[str, Any]] = {}
        for eid in entity_ids:
            row = con.execute(
                "select predicted_type, confidence, margin, class_gate_pass"
                " from entity_predictions where entity_id=?",
                (eid,),
            ).fetchone()
            if row is not None:
                out[eid] = {
                    "predicted_type": str(row["predicted_type"]),
                    "confidence": float(row["confidence"]),
                    "margin": float(row["margin"]),
                    "class_gate_pass": bool(row["class_gate_pass"]),
                }
        return out, None
    finally:
        con.close()


# ---------------------------------------------------------------------------
# B8：joblib 重载 + 归一化熵（§5.2）
# ---------------------------------------------------------------------------


def load_proba_bundle(path: Path):
    """加载冻结分类器 joblib；不可用或无 predict_proba 时返回 (None, 原因)。"""
    if not path.exists():
        return None, f"joblib model missing: {path}"
    try:
        import joblib
    except ImportError as exc:  # pragma: no cover - 环境缺失
        return None, f"joblib unavailable: {exc}"
    try:
        obj = joblib.load(path)
    except Exception as exc:  # noqa: BLE001 - 反序列化失败按不可用处理
        return None, f"joblib load failed: {type(exc).__name__}: {exc}"
    required = ("name_vectorizer", "context_vectorizer", "classifier")
    if not isinstance(obj, dict) or any(k not in obj for k in required):
        return None, "joblib bundle lacks name/context vectorizer + classifier"
    if not hasattr(obj["classifier"], "predict_proba"):
        return None, "joblib classifier provides no predict_proba"
    return obj, None


def member_feature_text(
    v2_entity: Mapping[str, Any],
    token_counter: Mapping[str, int],
) -> tuple[str, str]:
    """按冻结训练脚本（260_train_evaluate_stkg_v2_entity_classifier.py）重建
    name_text/context_text：name=canonical_name+aliases 空格连接；
    context=出现频次降序的前 80 个 OUT/IN::谓词::邻居类型 记号。"""
    import json as _json

    try:
        aliases = [str(a) for a in _json.loads(str(v2_entity.get("aliases_json") or "[]"))]
    except _json.JSONDecodeError:
        aliases = []
    name_text = " ".join([str(v2_entity.get("canonical_name") or ""), *aliases]).strip()
    ordered = sorted(token_counter.items(), key=lambda kv: (-kv[1], kv[0]))[:80]
    context_text = " ".join(token for token, _ in ordered)
    return name_text, context_text


def proba_normalized_entropy(proba_row: Sequence[float]) -> float:
    """归一化熵置信 1−H/Hmax（Hmax=ln K；越大越尖）。"""
    values = [float(p) for p in proba_row if float(p) > 0.0]
    n_classes = len(proba_row)
    if n_classes <= 1 or not values:
        return 0.0
    entropy = -sum(p * math.log(p) for p in values)
    return 1.0 - entropy / math.log(n_classes)


def member_context_tokens(con, entity_ids: set[str]) -> dict[str, Counter]:
    """v2_assertion_scopes 全库一遍，收集指定实体（源级）的 OUT/IN 关系记号。

    与冻结训练脚本同法：OUT::谓词::邻居 semantic 类型 / IN::谓词::邻居类型；
    邻居有效类型 = semantic_entity_type or source_entity_type。
    """
    effective = {
        str(row["entity_id"]): str(row["semantic_entity_type"] or row["source_entity_type"])
        for row in con.execute(
            "select entity_id, source_entity_type, semantic_entity_type from sem.v2_entities"
        )
    }
    tokens: dict[str, Counter] = {eid: Counter() for eid in entity_ids}

    def clean(value: str) -> str:
        return str(value).strip().replace(" ", "_")[:120]

    for subject_id, predicate, object_id in con.execute(
        "select subject_id,predicate,object_id from sem.v2_assertion_scopes"
    ):
        subject_id = str(subject_id)
        object_id = str(object_id)
        predicate = clean(predicate)
        if subject_id in tokens:
            tokens[subject_id][f"OUT::{predicate}::{clean(effective.get(object_id, ''))}"] += 1
        if object_id in tokens:
            tokens[object_id][f"IN::{predicate}::{clean(effective.get(subject_id, ''))}"] += 1
    return tokens


def bundle_proba(bundle, name_text: str, context_text: str):
    """与训练脚本一致的 transform（name char-tfidf ⊕ context word-tfidf）后
    predict_proba；特征维度不匹配等异常向上抛，由调用方按逐行不可用处理。"""
    import numpy as np
    from scipy.sparse import hstack

    names = bundle["name_vectorizer"].transform([name_text])
    contexts = bundle["context_vectorizer"].transform([context_text])
    features = hstack([names, contexts], format="csr", dtype=np.float32)
    return bundle["classifier"].predict_proba(features)[0]


# ---------------------------------------------------------------------------
# 规则基线（B1，§5.1）与共享聚合
# ---------------------------------------------------------------------------


def rule_member_prediction(
    name: str,
    source_type: str,
    votes: Counter,
    cross_type_name: bool,
):
    """单个源级成员的 v2 规则融合预测 → (final_type|None, confidence|None, status)。"""
    lexical = refine_lexical_hint(name, source_type, strong_entity_type_hint(name))
    fusion = fuse_entity_type(source_type, lexical, votes, cross_type_name)
    return fusion.final_type, fusion.confidence, fusion.status


def select_best_member(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """成员聚合（§5.1/§5.2）：置信最高成员；并列取成员间多数类型，再并列取
    类型字典序。rows 元素需含 prediction 与 confidence 键。"""
    candidates = [dict(r) for r in rows if r.get("prediction") and r.get("confidence") is not None]
    if not candidates:
        return None
    top_conf = max(float(r["confidence"]) for r in candidates)
    tied = [r for r in candidates if float(r["confidence"]) == top_conf]
    type_counts = Counter(str(r["prediction"]) for r in tied)
    best_count = max(type_counts.values())
    lexicographic = sorted(t for t, c in type_counts.items() if c == best_count)
    chosen_type = lexicographic[0]
    for row in tied:
        if str(row["prediction"]) == chosen_type:
            return row
    return None  # pragma: no cover - 防御


def entity_rule_gate(
    name: str,
    source_type: str,
    prediction: str | None,
    cluster_source_types: Sequence[str] = (),
) -> bool:
    """实体型硬约束门：TYPE_FAMILY 成员 + entity_model_contraindication 通过。"""
    if not prediction or prediction not in TYPE_FAMILY:
        return False
    return not entity_model_contraindication(name, source_type, prediction, cluster_source_types)


def relation_rule_prediction(
    contract: Mapping[str, Mapping[str, frozenset[str]]],
    predicate: str,
    subject_type: str,
    object_type: str,
) -> tuple[str | None, float | None, str]:
    """B1 关系契约三分支（§5.1）：兼容→valid/0.99；不兼容→invalid/0.90；
    谓词未知→弃权。"""
    spec = contract.get(predicate)
    if spec is None:
        return None, None, "predicate_unknown_abstain"
    if subject_type in spec["source_types"] and object_type in spec["target_types"]:
        return "valid", 0.99, "contract_accept"
    return "invalid", 0.90, "contract_type_mismatch"


# ---------------------------------------------------------------------------
# 23 列行工厂（§2 固定取值）
# ---------------------------------------------------------------------------


def fmt_conf(value: Any) -> str:
    if value is None or value == "":
        return ""
    return f"{float(value):.12f}"


def make_row(
    sample: TaskSample,
    method_id: str,
    *,
    prediction: str | None,
    confidence: Any,
    availability: str,
    gate: bool | None,
    gate_source: str,
    source_artifact: str,
    note: str,
    actual_llm_calls: int = 0,
) -> dict[str, Any]:
    return {
        "sample_id": sample.sample_id,
        "task_type": sample.task_type,
        "item_id": sample.item_id,
        "split": "independent_eval",
        "method_id": method_id,
        "method_name": METHODS[method_id]["name"],
        "evidence_class": "actual_run",
        "comparison_tier": "independent_reference",
        "overlap_status": "independent_of_era",
        "primary_comparison_eligible": 1,
        "evaluation_eligibility": "core_eligible_task",
        "availability_status": availability,
        "gold_label": "",
        "prediction": prediction or "",
        "confidence": confidence if isinstance(confidence, str) else fmt_conf(confidence),
        "covered": 0,
        "correct": 0,
        "hard_constraint_pass": int(bool(gate)) if gate is not None else 0,
        "constraint_gate_source": gate_source,
        "safe_correct": 0,
        "actual_llm_calls": actual_llm_calls,
        "source_artifact": source_artifact,
        "note": note,
    }


def not_available_payload(reason: str) -> dict[str, Any]:
    """§3：N/A 的内部 payload（prediction/confidence 空，note 注明原因）。"""
    return {
        "prediction": None,
        "confidence": None,
        "available": False,
        "gate": False,
        "gate_source": "not_available",
        "source_artifact": "none",
        "note": f"NOT_AVAILABLE: {reason}",
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# 各方法行生成（内部 payload dict；由 build_all_rows 统一转为 23 列行）
# ---------------------------------------------------------------------------


def b12_rows_for_sample(sample: TaskSample, resources: Mapping[str, Any]) -> dict[str, Any]:
    """B12 生产映射（§4.1–4.5）。"""
    task = sample.task_type
    f = sample.fields
    if task == "entity_type":
        eid = sample.item_id
        pred = str(f.get("production_entity_type") or "")
        status = str(f.get("type_validation_status") or "")
        release = resources["release_entities"].get(eid)
        confidence = release["confidence"] if release else None
        if not pred:
            return not_available_payload(
                "production release field missing (production_entity_type empty)"
            )
        return {
            "prediction": pred,
            "confidence": confidence,
            "available": True,
            "gate": status == "validated",
            "gate_source": GATE_B12_ENTITY,
            "source_artifact": SRC_B12,
            "note": (
                f"mapping[{MAPPING_STRATEGY_VERSION}]=production release fields: "
                f"entity_type+type_validation_status (entity_type={pred}, "
                f"type_validation_status={status or 'NA'}); gate=validated"
            ),
            "reason": "",
        }
    if task == "relation_contract":
        tier = str(f.get("release_tier") or "")
        semantic_status = str(f.get("semantic_status") or "")
        risk_tier = str(f.get("risk_tier") or "")
        pred = RELEASE_TIER_TO_IMCR.get(tier)
        confidence = resources["assertion_confidence"].get(sample.item_id)
        gate = semantic_status == "auto_accepted" and risk_tier in {"A", "B"}
        return {
            "prediction": pred,
            "confidence": confidence,
            "available": True,
            "gate": gate,
            "gate_source": GATE_B12_RELATION,
            "source_artifact": SRC_B12,
            "note": (
                f"mapping[{MAPPING_STRATEGY_VERSION}]=release_tier→IMCR: "
                f"strict_semantic→valid, contextual→context_only, "
                f"unresolved→insufficient_evidence; invalid never predicted "
                f"(release_tier={tier or 'NA'}); gate=semantic_status=='auto_accepted' "
                f"AND risk_tier∈{{A,B}} (semantic_status={semantic_status or 'NA'}, "
                f"risk_tier={risk_tier or 'NA'})"
            ),
            "reason": "",
        }
    if task == "scope_adjustment":
        return {
            "prediction": "AFTER_BETTER",
            "confidence": None,
            "available": True,
            "gate": True,
            "gate_source": GATE_B12_SCOPE,
            "source_artifact": SRC_B12,
            "note": (
                f"mapping[{MAPPING_STRATEGY_VERSION}]=constant AFTER_BETTER "
                "(post-closure state is the system claim; IMCR label space); "
                "confidence withheld (research_scope_adjustments has no graded "
                "confidence field); gate=1"
            ),
            "reason": "",
        }
    if task == "identity_pair":
        membership = resources["identity_membership"]
        canon_a = membership.get(str(f.get("entity_a_id") or ""))
        canon_b = membership.get(str(f.get("entity_b_id") or ""))
        if not canon_a or not canon_b:
            return not_available_payload("endpoint(s) absent from research_entity_members")
        pred = "same_entity" if canon_a == canon_b else "different_entity"
        return {
            "prediction": pred,
            "confidence": None,
            "available": True,
            "gate": True,
            "gate_source": GATE_B12_IDENTITY,
            "source_artifact": SRC_B12_IDENTITY,
            "note": (
                f"mapping[{MAPPING_STRATEGY_VERSION}]=research_entity_members "
                "co-membership: same canonical_entity_id→same_entity else "
                "different_entity; confidence withheld (production identity merge "
                "has no per-pair graded confidence); gate=1"
            ),
            "reason": "",
        }
    if task == "provenance_support":
        tier = str(f.get("research_tier") or "")
        pred = RESEARCH_TIER_TO_IMCR.get(tier)
        try:
            n_rows = int(float(str(f.get("n_provenance_rows") or 0)))
        except ValueError:
            n_rows = 0
        raw_conf = str(f.get("confidence") or "")
        confidence = float(raw_conf) if raw_conf else None
        return {
            "prediction": pred,
            "confidence": confidence,
            "available": True,
            "gate": n_rows > 0,
            "gate_source": GATE_B12_PROVENANCE,
            "source_artifact": SRC_B12,
            "note": (
                f"mapping[{MAPPING_STRATEGY_VERSION}]=research_tier→IMCR: "
                "strict_semantic→fully_supported, contextual→partially_supported, "
                "unresolved→insufficient_evidence; unsupported/contradicted never "
                f"predicted (research_tier={tier or 'NA'}); confidence=frozen "
                f"sidecar research_assertions.confidence; gate=n_provenance_rows>0 "
                f"(n={n_rows})"
            ),
            "reason": "",
        }
    raise ValueError(f"unsupported task_type: {task}")  # pragma: no cover


def b1_rows_for_sample(sample: TaskSample, resources: Mapping[str, Any]) -> dict[str, Any]:
    """B1 规则基线（§5.1）。"""
    task = sample.task_type
    if task == "entity_type":
        members = resources["member_map"].get(sample.item_id, [])
        v2 = resources["v2_entities"]
        votes = resources["schema_votes"]
        name_types = resources["name_source_types"]
        scored: list[dict[str, Any]] = []
        for m in members:
            mid = m["source_entity_id"]
            ent = v2.get(mid)
            if ent is None:
                continue
            pred, conf, _status = rule_member_prediction(
                ent["canonical_name"],
                ent["source_entity_type"],
                votes.get(mid, Counter()),
                len(name_types.get(ent["canonical_name"], set())) > 1,
            )
            scored.append(
                {
                    "prediction": pred,
                    "confidence": conf,
                    "member_id": mid,
                    "name": ent["canonical_name"],
                    "source_type": ent["source_entity_type"],
                }
            )
        selected = select_best_member(scored)
        if selected is None:
            return {
                "prediction": None,
                "confidence": None,
                "available": True,
                "gate": False,
                "gate_source": GATE_ENTITY_RULE,
                "source_artifact": SRC_B1_ENTITY,
                "note": (
                    "mapping=abstain: no member produced a confident v2 rule fusion "
                    "(aggregation=highest-confidence member, ties→member majority "
                    "type→lexicographic)"
                ),
                "reason": "",
            }
        gate = entity_rule_gate(selected["name"], selected["source_type"], selected["prediction"])
        return {
            "prediction": selected["prediction"],
            "confidence": selected["confidence"],
            "available": True,
            "gate": gate,
            "gate_source": GATE_ENTITY_RULE,
            "source_artifact": SRC_B1_ENTITY,
            "note": (
                "mapping=v2 rule engine fuse_entity_type per member (strict lexical "
                "hint + schema votes + source-type prior); aggregation=highest-"
                "confidence member, ties→member majority type→lexicographic; "
                f"selected member={selected['member_id']}; gate=contraindication on "
                "selected prediction"
            ),
            "reason": "",
        }
    if task == "relation_contract":
        f = sample.fields
        pred, conf, branch = relation_rule_prediction(
            resources["relation_contract"],
            str(f.get("predicate") or ""),
            str(f.get("subject_type") or ""),
            str(f.get("object_type") or ""),
        )
        return {
            "prediction": pred,
            "confidence": conf,
            "available": True,
            "gate": pred == "valid",
            "gate_source": GATE_RELATION_RULE,
            "source_artifact": SRC_B1_RELATION,
            "note": (
                "mapping=research_relation_contract: predicate known & "
                "domain/range compatible→valid(0.99); known & incompatible→"
                "invalid(0.90); unknown predicate→abstain (empty prediction); "
                f"branch={branch}; gate=prediction=='valid'"
            ),
            "reason": "",
        }
    return not_available_payload(f"no rule component for {task} (design §3 N/A)")


def b2_selection_for_sample(
    sample: TaskSample, resources: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, str]:
    """B2 冻结分类器成员选择（§5.2）。返回 (选择结果|None, 原因)。"""
    members = resources["member_map"].get(sample.item_id, [])
    scores = resources["classifier_scores"]
    rows = []
    for m in members:
        row = scores.get(m["source_entity_id"])
        if row is not None:
            rows.append(
                {**row, "prediction": row["predicted_type"], "member_id": m["source_entity_id"]}
            )
    selected = select_best_member(rows)
    if selected is None:
        reason = "no member has a row in the frozen classifier score table"
        if resources.get("classifier_error"):
            reason = resources["classifier_error"]
        return None, reason
    return selected, ""


def b3_predictions_by_key(path: Path | None) -> dict[tuple[str, str], dict[str, str]]:
    """从 B3 runs CSV（23 列）读取 (sample_id, task_type) → 行。"""
    if path is None or not path.exists():
        return {}
    out: dict[tuple[str, str], dict[str, str]] = {}
    for row in defs.read_csv_rows(path):
        if str(row.get("method_id")) != "B3_blind_llm":
            continue
        key = (str(row.get("sample_id")), str(row.get("task_type")))
        out[key] = row
    return out


def _payload_view(payload: Mapping[str, Any]) -> dict[str, str] | None:
    """把内部预测 dict 转成 combined/b9 消费的 23 列视图。"""
    if not payload:
        return None
    return {
        "prediction": "" if payload.get("prediction") is None else str(payload["prediction"]),
        "confidence": "" if payload.get("confidence") is None else str(payload["confidence"]),
        "availability_status": "available" if payload.get("available") else "not_available",
        "hard_constraint_pass": "1" if payload.get("gate") else "0",
        "constraint_gate_source": str(payload.get("gate_source") or ""),
    }


def b4_b5_rows_for_sample(
    sample: TaskSample,
    kind: str,
    rule: Mapping[str, Any],
    model_pred: Mapping[str, str] | None,
) -> dict[str, Any]:
    """B4/B5 组合规则（§5.3）：规则有预测用规则（置信、门随规则），否则用模型
    预测（B4→B2 冻结分类器、B5→B3 盲 LLM）。"""
    label = "B2 frozen classifier" if kind == "B4" else "B3 blind LLM"
    if rule.get("available") and rule.get("prediction"):
        out = dict(rule)
        out["note"] = (
            rule["note"]
            + f"; combined mapping=rule prediction first (confidence+gate follow rule); "
            f"provider=rule (fallback {label} unused)"
        )
        return out
    model_decision = str((model_pred or {}).get("prediction") or "")
    model_ok = model_pred is not None and model_decision and (
        str(model_pred.get("availability_status")) != "not_available"
    )
    if model_ok:
        assert model_pred is not None
        conf_raw = str(model_pred.get("confidence") or "")
        confidence: Any = float(conf_raw) if conf_raw else None
        gate = str(model_pred.get("hard_constraint_pass") or "0") == "1"
        return {
            "prediction": model_decision,
            "confidence": confidence,
            "available": True,
            "gate": gate,
            "gate_source": GATE_CLASSIFIER if kind == "B4" else str(
                model_pred.get("constraint_gate_source") or ""
            ),
            "source_artifact": SRC_B2 if kind == "B4" else SRC_B3,
            "note": (
                f"mapping=rule abstained → {label} prediction (confidence+gate follow "
                f"the {label} row); provider=model"
            ),
            "reason": "",
        }
    return not_available_payload(f"rule abstained and no usable {label} prediction")


def b9_rows_for_sample(
    sample: TaskSample,
    rule: Mapping[str, Any],
    model_pred: Mapping[str, str] | None,
    model_label: str,
) -> dict[str, Any]:
    """B9 一致门（§5.3）：prediction=规则预测（规则弃权则空）；
    confidence=规则与模型一致 ? 1.0 : 0.0（两档信号，面积指标不适用）。"""
    rule_ok = bool(rule.get("available"))
    if rule_ok and rule.get("prediction") is None:
        # 规则弃权：prediction 留空，一致信号无从谈起（设计：规则弃权则空）。
        return {
            "prediction": None,
            "confidence": None,
            "available": True,
            "gate": False,
            "gate_source": str(rule.get("gate_source") or ""),
            "source_artifact": f"rule + {model_label}",
            "note": (
                "mapping=prediction=rule prediction; rule abstained → empty "
                f"prediction and empty agreement signal; model={model_label}"
            ),
            "reason": "",
        }
    model_decision = str((model_pred or {}).get("prediction") or "")
    model_ok = model_pred is not None and model_decision and (
        str(model_pred.get("availability_status")) != "not_available"
    )
    if not (rule_ok and rule.get("prediction") and model_ok):
        return not_available_payload(
            f"agreement signal unavailable: rule or {model_label} prediction missing"
        )
    agree = model_decision == str(rule["prediction"])
    return {
        "prediction": rule.get("prediction"),
        "confidence": "1.0" if agree else "0.0",
        "available": True,
        "gate": bool(rule.get("gate")),
        "gate_source": str(rule.get("gate_source") or ""),
        "source_artifact": (
            f"{SRC_B1_ENTITY if sample.task_type == 'entity_type' else SRC_B1_RELATION}"
            f" + {model_label}"
        ),
        "note": (
            "mapping=prediction=rule prediction; confidence=1.0 if rule==model "
            f"else 0.0; model={model_label}; agreement="
            f"{'agree' if agree else 'disagree'}; gate=rule gate"
        ),
        "reason": "",
    }


def derive_b10_b11(sample: TaskSample, b12: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """B10/B11（§7）：共用 B12 prediction；B10 结构门禁用（gate 恒 1）；
    B11 无弃权（confidence 恒 1.0）。"""
    if b12.get("available"):
        b10 = {
            "prediction": b12.get("prediction"),
            "confidence": b12.get("confidence"),
            "available": True,
            "gate": True,
            "gate_source": GATE_ABLATION_B10,
            "source_artifact": "B12 full framework (ablation)",
            "note": (
                "ablation of B12: structural gate disabled (hard_constraint_pass "
                "forced 1; constrained curve degenerates to pure score curve); "
                "prediction identical to B12"
            ),
            "reason": "",
        }
        b11 = {
            "prediction": b12.get("prediction"),
            "confidence": "1.0",
            "available": True,
            "gate": bool(b12.get("gate")),
            "gate_source": str(b12.get("gate_source") or ""),
            "source_artifact": "B12 full framework (ablation)",
            "note": (
                "ablation of B12: no abstention (confidence forced 1.0; curve is a "
                "single point at coverage=1); prediction identical to B12"
            ),
            "reason": "",
        }
        return b10, b11
    na = not_available_payload(f"B12 row not available ({b12.get('reason') or 'see B12 row'})")
    return dict(na), dict(na)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def build_resources(
    con, samples: Mapping[str, Sequence[TaskSample]], inputs: InputPaths
) -> dict[str, Any]:
    entity_ids = {s.item_id for s in samples["entity_type"]}
    facts_rc = {s.item_id for s in samples["relation_contract"]}
    member_map = load_member_map(con, entity_ids)
    member_ids = {m["source_entity_id"] for members in member_map.values() for m in members}
    scores, err = load_classifier_scores(inputs.classifier_db, member_ids)
    return {
        "member_map": member_map,
        "member_ids": member_ids,
        "v2_entities": load_v2_entities(con, member_ids),
        "name_source_types": load_name_source_types(con),
        "schema_votes": load_schema_votes(con, member_ids),
        "relation_contract": load_relation_contract(con),
        "release_entities": load_release_entities(con, entity_ids),
        "assertion_confidence": load_assertion_confidence(con, facts_rc),
        "identity_membership": load_identity_membership(con),
        "classifier_scores": scores,
        "classifier_error": err,
    }


def _b8_payload(
    b2_note: str,
    selected: Mapping[str, Any],
    resources: Mapping[str, Any],
    proba_bundle,
    proba_error: str | None,
    context_tokens: Mapping[str, Counter],
) -> dict[str, Any]:
    """B8 行 payload：同行预测，confidence=所选成员文本的归一化熵（§5.2）。"""
    base = {
        "prediction": selected["prediction"],
        "confidence": None,
        "available": True,
        "gate": bool(selected["class_gate_pass"]),
        "gate_source": GATE_CLASSIFIER,
        "source_artifact": SRC_B8,
        "note": "",
        "reason": "",
    }
    if proba_bundle is None:
        reason = proba_error or "joblib proba unavailable"
        out = not_available_payload(f"B8 all-grid not available: {reason}")
        out["source_artifact"] = SRC_B8
        return out
    member = resources["v2_entities"].get(str(selected["member_id"]))
    tokens = context_tokens.get(str(selected["member_id"]), Counter())
    if member is None:
        return not_available_payload("selected member missing from sem.v2_entities")
    name_text, context_text = member_feature_text(member, tokens)
    try:
        proba = bundle_proba(proba_bundle, name_text, context_text)
        entropy = proba_normalized_entropy(proba)
    except Exception as exc:  # noqa: BLE001 - 维度不匹配等按逐行不可用
        return not_available_payload(f"proba computation failed: {type(exc).__name__}: {exc}")
    base["confidence"] = entropy
    base["note"] = (
        b2_note
        + "; confidence=normalized entropy 1−H/Hmax of reloaded joblib proba on the "
        "selected member text (B8 signal)"
    )
    return base


def build_all_rows(
    samples: Mapping[str, Sequence[TaskSample]],
    resources: Mapping[str, Any],
    b3_pred: Mapping[tuple[str, str], Mapping[str, str]] | None = None,
    proba_bundle=None,
    proba_error: str | None = None,
    context_tokens: Mapping[str, Counter] | None = None,
) -> list[dict[str, Any]]:
    """按任务型 × 样本 × 方法展开 23 列行（含 N/A 单元格行，保证网格完整）。"""
    b3_pred = b3_pred or {}
    context_tokens = context_tokens or {}
    rows: list[dict[str, Any]] = []
    for task in ALL_TASKS:
        for sample in samples[task]:
            computed: dict[str, dict[str, Any]] = {}

            b12 = b12_rows_for_sample(sample, resources)
            computed["B12_full_framework"] = b12
            b10, b11 = derive_b10_b11(sample, b12)
            computed["B10_selective_no_structural_gate"] = b10
            computed["B11_structural_gate_no_abstention"] = b11

            rule = b1_rows_for_sample(sample, resources)
            computed["B1_rule_only"] = rule

            b3_row = b3_pred.get((sample.sample_id, task))

            if task == "entity_type":
                selected, b2_reason = b2_selection_for_sample(sample, resources)
                if selected is not None:
                    b2 = {
                        "prediction": selected["prediction"],
                        "confidence": selected["confidence"],
                        "available": True,
                        "gate": bool(selected["class_gate_pass"]),
                        "gate_source": GATE_CLASSIFIER,
                        "source_artifact": SRC_B2,
                        "note": (
                            "mapping=frozen production classifier score table "
                            "(entity_predictions); aggregation=highest-confidence "
                            "member, ties→member majority predicted_type→lexicographic; "
                            f"selected member={selected['member_id']}; "
                            "gate=selected member class_gate_pass"
                        ),
                        "reason": "",
                    }
                    b7 = dict(b2)
                    b7["confidence"] = selected["margin"]
                    b7["source_artifact"] = SRC_B7
                    b7["note"] = b2["note"] + "; confidence=selected member margin (B7 signal)"
                    computed["B2_frozen_classifier"] = b2
                    computed["B7_classifier_margin"] = b7
                    computed["B8_entropy_threshold"] = _b8_payload(
                        b2["note"], selected, resources, proba_bundle, proba_error, context_tokens
                    )
                    computed["B4_rule_plus_classifier"] = b4_b5_rows_for_sample(
                        sample, "B4", rule, _payload_view(b2)
                    )
                    computed["B9_rule_model_agreement"] = b9_rows_for_sample(
                        sample, rule, _payload_view(b2), "B2 frozen classifier"
                    )
                else:
                    reason = b2_reason or "B2 selection failed"
                    for mid in ("B2_frozen_classifier", "B7_classifier_margin"):
                        computed[mid] = not_available_payload(reason)
                    b8_reason = reason
                    if proba_bundle is None and proba_error:
                        b8_reason = f"{reason}; B8 all-grid: {proba_error}"
                    computed["B8_entropy_threshold"] = not_available_payload(b8_reason)
                    computed["B4_rule_plus_classifier"] = b4_b5_rows_for_sample(
                        sample, "B4", rule, None
                    )
                    computed["B9_rule_model_agreement"] = b9_rows_for_sample(
                        sample, rule, None, "B2 frozen classifier"
                    )
                computed["B5_rule_plus_blind_llm"] = b4_b5_rows_for_sample(
                    sample, "B5", rule, b3_row
                )
            elif task == "relation_contract":
                computed["B5_rule_plus_blind_llm"] = b4_b5_rows_for_sample(
                    sample, "B5", rule, b3_row
                )
                computed["B9_rule_model_agreement"] = b9_rows_for_sample(
                    sample, rule, b3_row, "B3 blind LLM"
                )

            for mid in METHOD_ORDER:
                payload = computed.get(mid)
                if payload is None:
                    payload = not_available_payload(
                        f"method×task cell is N/A by design (§3): {mid} on {task}"
                    )
                if payload["available"]:
                    rows.append(
                        make_row(
                            sample,
                            mid,
                            prediction=payload["prediction"],
                            confidence=payload.get("confidence"),
                            availability="available",
                            gate=payload.get("gate"),
                            gate_source=payload["gate_source"],
                            source_artifact=payload["source_artifact"],
                            note=payload["note"],
                        )
                    )
                else:
                    rows.append(not_available_row_from_payload(sample, mid, payload))
    return rows


def not_available_row_from_payload(
    sample: TaskSample, method_id: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    return make_row(
        sample,
        method_id,
        prediction=None,
        confidence=None,
        availability="not_available",
        gate=False,
        gate_source="not_available",
        source_artifact="none",
        note=f"NOT_AVAILABLE: {payload['reason']}",
    )


def merge_run_rows(
    base_rows: Sequence[Mapping[str, Any]],
    append_paths: Sequence[Path],
) -> list[dict[str, Any]]:
    """--append-runs 合并：键 (sample_id, task_type, method_id) 去重、后写覆盖；
    输出按 (task_type, sample_id, method_id) 稳定排序，全程幂等。"""
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in base_rows:
        key = (str(row["sample_id"]), str(row["task_type"]), str(row["method_id"]))
        merged[key] = dict(row)
    for path in append_paths:
        if not path.exists():
            raise FileNotFoundError(f"--append-runs 文件不存在：{path}")
        for row in defs.read_csv_rows(path):
            key = (
                str(row.get("sample_id")),
                str(row.get("task_type")),
                str(row.get("method_id")),
            )
            if not all(key):
                continue
            merged[key] = {field: row.get(field, "") for field in RUNS_FIELDS}
    return [merged[key] for key in sorted(merged, key=lambda k: (k[1], k[0], k[2]))]


def build_availability_matrix(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """方法×任务 状态矩阵（available/not_available/行数/原因）。"""
    cells: dict[tuple[str, str], dict[str, int]] = {}
    notes: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for row in rows:
        key = (str(row["method_id"]), str(row["task_type"]))
        cell = cells.setdefault(key, {"n_rows": 0, "n_available": 0, "n_not_available": 0})
        cell["n_rows"] += 1
        if str(row["availability_status"]) == "not_available":
            cell["n_not_available"] += 1
            reason = str(row["note"] or "").replace("NOT_AVAILABLE: ", "")
            notes[key][reason] += 1
        else:
            cell["n_available"] += 1

    matrix: list[dict[str, Any]] = []
    registry: list[tuple[str, str, frozenset[str] | None]] = [
        (mid, str(METHODS[mid]["name"]), METHODS[mid]["tasks"]) for mid in METHOD_ORDER
    ]
    for mid, meta in MATRIX_ONLY_METHODS.items():
        registry.append((mid, meta["name"], None))
    for mid, name, _supported in registry:
        for task in ALL_TASKS:
            cell = cells.get((mid, task))
            if cell is not None:
                available = cell["n_available"] > 0
                top_reasons = "; ".join(
                    f"{r} x{n}" for r, n in notes[(mid, task)].most_common(3)
                )
                if available and cell["n_not_available"]:
                    reason = (
                        f"partial: {cell['n_available']}/{cell['n_rows']} rows available; "
                        "top reasons: " + top_reasons
                    )
                elif available:
                    reason = "available"
                else:
                    reason = top_reasons
                matrix.append(
                    {
                        "method_id": mid,
                        "method_name": name,
                        "task_type": task,
                        "availability_status": "available" if available else "not_available",
                        "n_rows": cell["n_rows"],
                        "n_available": cell["n_available"],
                        "n_not_available": cell["n_not_available"],
                        "reason": reason,
                    }
                )
            else:
                matrix.append(
                    {
                        "method_id": mid,
                        "method_name": name,
                        "task_type": task,
                        "availability_status": "not_available",
                        "n_rows": 0,
                        "n_available": 0,
                        "n_not_available": 0,
                        "reason": MATRIX_ONLY_METHODS[mid]["pending_reason"],
                    }
                )
    return matrix


def summarize_b3_logs(out_dir: Path) -> dict[str, Any] | None:
    """best-effort：从 blind_llm_runs/*.jsonl 汇总 B3 model_id/调用统计进 manifest。

    只读 B3 自身调用日志（与 judge raw_runs 无关，无泄漏）。
    """
    log_dir = out_dir / BLIND_LOG_DIR
    if not log_dir.is_dir():
        return None
    per_task: dict[str, dict[str, int]] = {}
    model_ids: set[str] = set()
    for path in sorted(log_dir.glob("*.jsonl")):
        counts: dict[str, int] = {"OK": 0, "MODEL_OUTPUT_INVALID": 0, "TRANSPORT_ERROR": 0}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            status = str(rec.get("status"))
            counts[status] = counts.get(status, 0) + 1
            if rec.get("model_id"):
                model_ids.add(str(rec["model_id"]))
        per_task[path.stem] = counts
    if not per_task:
        return None
    return {"model_ids": sorted(model_ids), "calls_per_task": per_task}


def audit_rows(
    rows: Sequence[Mapping[str, str]],
    samples: Mapping[str, Sequence[TaskSample]],
) -> dict[str, Any]:
    """§8 审计门等价物：网格完整、无 NOT_AVAILABLE 行携带预测、映射策略校验和、
    固定列一致性。"""
    expected = {
        (mid, task): len(samples[task]) for mid in METHOD_ORDER for task in ALL_TASKS
    }
    observed: Counter = Counter((str(r["method_id"]), str(r["task_type"])) for r in rows)
    missing = sorted(k for k, n in expected.items() if observed.get(k, 0) != n)
    bad_na = [
        str(r["sample_id"])
        for r in rows
        if str(r["availability_status"]) == "not_available" and str(r["prediction"])
    ]
    fixed_ok = all(
        str(r["split"]) == "independent_eval"
        and str(r["evidence_class"]) == "actual_run"
        and str(r["comparison_tier"]) == "independent_reference"
        and str(r["overlap_status"]) == "independent_of_era"
        and str(r["primary_comparison_eligible"]) == "1"
        and str(r["covered"]) == "0"
        and str(r["correct"]) == "0"
        and str(r["safe_correct"]) == "0"
        and str(r["gold_label"]) == ""
        for r in rows
    )
    checks = {
        "grid_complete_method_x_task": not missing,
        "no_not_available_row_carries_prediction": not bad_na,
        "fixed_schema_columns_uniform": fixed_ok,
        "mapping_strategy_checksum_consistent": MAPPING_SPEC_SHA256
        == sha256_text(json.dumps(MAPPING_SPEC, ensure_ascii=False, sort_keys=True)),
    }
    return {
        "checks": checks,
        "result": "PASS" if all(checks.values()) else "FAIL",
        "missing_grid_cells": [f"{m}/{t}" for m, t in missing][:50],
        "n_bad_not_available_rows": len(bad_na),
        "mapping_strategy_version": MAPPING_STRATEGY_VERSION,
        "mapping_spec_sha256": MAPPING_SPEC_SHA256,
    }


def run(
    out_dir: Path,
    *,
    conn=None,
    inputs: InputPaths | None = None,
    append_runs: Sequence[Path] = (),
    b3_runs: Path | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """主流程：装载 → 预测 → 合并 → 矩阵/审计/manifest 落盘。返回摘要 dict。

    conn 缺省时对冻结 release 库建立只读连接；测试可注入临时 sqlite 连接。
    """
    inputs = inputs or default_input_paths()
    out_dir = Path(out_dir)
    owned = conn is None
    con = connect_final() if owned else conn
    try:
        samples = load_samples(inputs, limit)
        resources = build_resources(con, samples, inputs)

        # B8 模型与上下文记号（仅在 entity_type 样本存在时需要）
        proba_bundle, proba_error = (None, None)
        context_tokens: dict[str, Counter] = {}
        if samples["entity_type"]:
            proba_bundle, proba_error = load_proba_bundle(inputs.classifier_model)
            if proba_bundle is not None:
                context_tokens = member_context_tokens(con, resources["member_ids"])

        b3_index = b3_predictions_by_key(b3_runs)
        base_rows = build_all_rows(
            samples,
            resources,
            b3_pred=b3_index,
            proba_bundle=proba_bundle,
            proba_error=proba_error,
            context_tokens=context_tokens,
        )
        rows = merge_run_rows(base_rows, list(append_runs))
        matrix = build_availability_matrix(rows)
        audit = audit_rows(rows, samples)

        n_available = sum(1 for r in rows if r["availability_status"] == "available")
        task_counts = {t: len(v) for t, v in samples.items()}
        print(
            f"[run_independent_baselines] rows={len(rows)} "
            f"(available={n_available}, not_available={len(rows) - n_available}); "
            f"tasks={task_counts}; audit={audit['result']}"
        )
        for cell in matrix:
            if cell["availability_status"] == "not_available":
                print(
                    f"  [matrix] {cell['method_id']}×{cell['task_type']}: "
                    f"not_available (n_rows={cell['n_rows']}) {cell['reason'][:120]}"
                )

        not_available_registry = [
            {
                "method_id": c["method_id"],
                "task_type": c["task_type"],
                "n_rows": c["n_rows"],
                "n_not_available": c["n_not_available"],
                "reason": c["reason"],
            }
            for c in matrix
            if c["availability_status"] == "not_available"
        ]

        write_csv(out_dir / RUNS_NAME, RUNS_FIELDS, rows)
        write_csv(
            out_dir / MATRIX_NAME,
            [
                "method_id", "method_name", "task_type", "availability_status",
                "n_rows", "n_available", "n_not_available", "reason",
            ],
            matrix,
        )
        audit_payload = {
            "generated_at": now_iso(),
            **audit,
            "n_runs_rows": len(rows),
            "n_available_rows": n_available,
            "task_sample_counts": task_counts,
        }
        with open(out_dir / AUDIT_NAME, "w", encoding="utf-8") as fh:
            json.dump(audit_payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

        db_paths = _attached_db_paths(con) if con is not None else {}
        db_manifest: dict[str, str] = {}
        for name, label in (("main", "final"), ("sem", "semantic")):
            path = db_paths.get(name)
            if path and Path(path).exists():
                db_manifest[f"{label}_db_path"] = path
                db_manifest[f"{label}_db_sha256"] = sha256_file(path)
        b3_stats = summarize_b3_logs(out_dir)
        manifest = build_manifest(
            "independent_baselines",
            database_path=db_manifest.get("final_db_path"),
            prompt_sha256=MAPPING_SPEC_SHA256,
            model_ids=(b3_stats or {}).get("model_ids", []),
            seed=MASTER_SEED,
            repo_dir=CODE_DIR.parent,
            extra={
                "description": (
                    "IMCR 独立基线 B1–B12（B3 除外；B3 经 --append-runs 合并）"
                    "预测行清单（audit/04_BASELINE_DESIGN.md §8）"
                ),
                "db_manifest": db_manifest,
                "not_available_registry": not_available_registry,
                "mapping_strategy_version": MAPPING_STRATEGY_VERSION,
                "mapping_spec": MAPPING_SPEC,
                "mapping_spec_sha256": MAPPING_SPEC_SHA256,
                "audit_result": audit["result"],
                "grid_complete": audit["checks"]["grid_complete_method_x_task"],
                "b3_stats": b3_stats,
                "output_files": {
                    RUNS_NAME: sha256_file(out_dir / RUNS_NAME),
                    MATRIX_NAME: sha256_file(out_dir / MATRIX_NAME),
                },
                "inputs": {k: str(v) for k, v in vars(inputs).items()},
            },
        )
        manifest_path = write_manifest_json(manifest, out_dir / MANIFEST_NAME)
        print(f"[run_independent_baselines] manifest: {manifest_path}")
        return {
            "n_rows": len(rows),
            "n_available": n_available,
            "matrix": matrix,
            "audit": audit,
            "manifest": str(manifest_path),
        }
    finally:
        if owned and con is not None:
            con.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", type=Path, default=EXP09, help="输出目录（默认 09_independent_baselines）"
    )
    parser.add_argument(
        "--append-runs",
        nargs="*",
        type=Path,
        default=(),
        help="合并的额外 runs CSV（如 IMCR_BLIND_LLM_RUNS.csv）；键 sample_id+task_type+method_id 去重、后写覆盖",
    )
    parser.add_argument(
        "--b3-runs",
        type=Path,
        default=None,
        help="B3 预测 CSV 路径（供 B5 fallback / B9 关系一致信号）；默认自动探测 <out-dir>/IMCR_BLIND_LLM_RUNS.csv",
    )
    parser.add_argument("--limit", type=int, default=None, help="每任务型最多处理条数（冒烟用）")
    args = parser.parse_args(argv)

    b3_runs = args.b3_runs
    if b3_runs is None:
        candidate = args.out_dir / BLIND_RUNS_NAME
        b3_runs = candidate if candidate.exists() else None
    summary = run(
        args.out_dir,
        append_runs=list(args.append_runs),
        b3_runs=b3_runs,
        limit=args.limit,
    )
    print(f"[run_independent_baselines] audit result: {summary['audit']['result']}")
    return 0 if summary["audit"]["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
