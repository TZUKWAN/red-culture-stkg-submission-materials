# -*- coding: utf-8 -*-
"""test_pipeline_independent_baselines.py — run_independent_baselines / run_blind_llm_baseline 离线测试。

覆盖（audit/04_BASELINE_DESIGN.md）：B12 五个任务型映射策略（§4.1–4.5）、B1 关系契约
三分支与成员聚合、B2 聚合与 not_available、B4 回退、B5→B3 回退、B9 一致信号、
B7/B8 置信信号、B10/B11 消融、合并去重（后写覆盖）、可用性矩阵完整性、
manifest/audit 落盘、B3 dry-run 全链路 + MODEL_OUTPUT_INVALID + resume 幂等。
全程离线：临时 sqlite fixture（mini final+sem 库）、临时冻结样本文件、假响应，
不连真实 release 库、不联网、不读取 08/raw_runs 任何 judge 输出。
"""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PIPELINE_DIR = Path(__file__).resolve().parent.parent / "experiment_pipelines"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

import imcr_task_defs as defs  # noqa: E402
import run_blind_llm_baseline as blind  # noqa: E402
import run_independent_baselines as base  # noqa: E402
from blind_payload import build_blind_payload  # noqa: E402
from judge_client import MODEL_OUTPUT_INVALID  # noqa: E402
from manifest import MANIFEST_FIELDS  # noqa: E402
from _common import derive_seed  # noqa: E402

C1 = "IENTREPAIR-canonical1"
C2 = "IENTREPAIR-canonical2"
C3 = "IENTREPAIR-canonical3"
M1, M2, M3, M4 = "IENT-member1", "IENT-member2", "IENT-member3", "IENT-member4"
N1, N2 = "IENT-neighbor1", "IENT-neighbor2"


# ---------------------------------------------------------------------------
# fixture 构造
# ---------------------------------------------------------------------------


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _build_db(tmp_path: Path) -> sqlite3.Connection:
    """mini final 库（main）+ mini 语义库（sem ATTACH），列名为已核实的真实列名。"""
    final_path = tmp_path / "final.sqlite"
    sem_path = tmp_path / "sem.sqlite"
    con = sqlite3.connect(final_path)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        create table research_entities(entity_id text primary key, canonical_name text,
            entity_type text, confidence real, type_validation_status text);
        create table research_entity_members(source_entity_id text, canonical_entity_id text,
            source_canonical_name text, source_entity_type text, mapping_status text);
        create table research_relation_contract(predicate text primary key,
            source_types_json text, target_types_json text);
        create table research_assertions(fact_id text primary key, confidence real);
        """
    )
    con.execute(
        "insert into research_entities values (?,?,?,?,?)",
        (C1, "梅溪", "Place", 0.98, "validated"),
    )
    con.execute(
        "insert into research_entities values (?,?,?,?,?)",
        (C2, "起义", "Event", 0.90, "fallback_unresolved"),
    )
    con.execute(
        "insert into research_entities values (?,?,?,?,?)",
        (C3, "共用名", "Person", 0.80, "validated"),
    )
    members = [
        (M1, C1, "梅溪镇", "Place", "self"),
        (M2, C1, "梅溪书院", "Institution", "canonicalized"),
        (M3, C2, "起义事件", "Event", "self"),
        (M4, C3, "共用名", "Person", "self"),
    ]
    con.executemany("insert into research_entity_members values (?,?,?,?,?)", members)
    con.execute(
        "insert into research_relation_contract values (?,?,?)",
        ("active_at", '["Person", "Organization"]', '["Place"]'),
    )
    assertions = [
        ("IFACT-RC1", 0.95),
        ("IFACT-RC2", 0.90),
        ("IFACT-RC3", None),
        ("IFACT-SA1", 0.70),
        ("IFACT-SA2", 0.70),
    ]
    con.executemany("insert into research_assertions values (?,?)", assertions)
    con.commit()

    sem = sqlite3.connect(sem_path)
    sem.executescript(
        """
        create table v2_entities(entity_id text primary key, canonical_name text,
            source_entity_type text, semantic_entity_type text, aliases_json text,
            confidence real);
        create table v2_assertion_scopes(subject_id text, predicate text, object_id text);
        """
    )
    v2_rows = [
        (M1, "梅溪镇", "Place", "Place", '["梅溪"]', 0.97),
        (M2, "梅溪书院", "Institution", "Institution", "[]", 0.88),
        (M3, "起义事件", "Event", "Event", "[]", 0.95),
        (M4, "共用名", "Person", "Person", "[]", 0.60),
        (N1, "夜袭战斗", "Event", "Event", "[]", 0.9),
        (N2, "梅溪县城", "Place", "Place", "[]", 0.9),
        ("IENT-other", "共用名", "Event", "Event", "[]", 0.6),
    ]
    sem.executemany("insert into v2_entities values (?,?,?,?,?,?)", v2_rows)
    # occurred_at 的 target 类型唯一（Place）→ 给 M1 投 Place 一票；
    # located_in 的 source 类型不唯一 → 不投票。
    scopes = [(N1, "occurred_at", M1), (M2, "located_in", N2)]
    sem.executemany("insert into v2_assertion_scopes values (?,?,?)", scopes)
    sem.commit()
    sem.close()

    con.execute("ATTACH DATABASE ? AS sem", (str(sem_path),))
    return con


def _build_inputs(tmp_path: Path) -> base.InputPaths:
    exp = tmp_path / "frozen"
    # entity_type 样本 + sidecar
    _write_csv(
        exp / "ENTITY_TYPE_SAMPLE.csv",
        ["sample_id", "entity_id", "canonical_name"],
        [
            {"sample_id": "ETV3-T1", "entity_id": C1, "canonical_name": "梅溪"},
            {"sample_id": "ETV3-T2", "entity_id": C2, "canonical_name": "起义"},
            {"sample_id": "ETV3-T3", "entity_id": C3, "canonical_name": "共用名"},
        ],
    )
    _write_csv(
        exp / "ENTITY_TYPE_SAMPLE.sampling_metadata.csv",
        ["sample_id", "entity_id", "production_entity_type", "type_validation_status"],
        [
            {"sample_id": "ETV3-T1", "entity_id": C1, "production_entity_type": "Place", "type_validation_status": "validated"},
            {"sample_id": "ETV3-T2", "entity_id": C2, "production_entity_type": "Event", "type_validation_status": "fallback_unresolved"},
            {"sample_id": "ETV3-T3", "entity_id": C3, "production_entity_type": "Person", "type_validation_status": "validated"},
        ],
    )
    # relation_contract 样本（刻意不含 changed_set_*/seed_* 泄漏列）
    _write_csv(
        exp / "RELATION_CONTRACT_SAMPLE.csv",
        ["sample_id", "fact_id", "predicate", "subject_type", "object_type",
         "release_tier", "semantic_status", "risk_tier"],
        [
            {"sample_id": "RC-T1", "fact_id": "IFACT-RC1", "predicate": "active_at",
             "subject_type": "Organization", "object_type": "Place",
             "release_tier": "contextual", "semantic_status": "auto_accepted", "risk_tier": "A"},
            {"sample_id": "RC-T2", "fact_id": "IFACT-RC2", "predicate": "active_at",
             "subject_type": "Event", "object_type": "Place",
             "release_tier": "strict_semantic", "semantic_status": "auto_accepted", "risk_tier": "A"},
            {"sample_id": "RC-T3", "fact_id": "IFACT-RC3", "predicate": "mystery_pred",
             "subject_type": "Person", "object_type": "Place",
             "release_tier": "unresolved", "semantic_status": "model_review", "risk_tier": "C"},
        ],
    )
    _write_jsonl(
        exp / "SCOPE_ADJUSTMENT_TASKS.jsonl",
        [
            {"task_id": "SA-T1", "fact_id": "IFACT-SA1"},
            {"task_id": "SA-T2", "fact_id": "IFACT-SA2"},
        ],
    )
    _write_jsonl(
        exp / "IDENTITY_PAIR_TASKS.jsonl",
        [{"pair_id": "IDP3-T1"}, {"pair_id": "IDP3-T2"}],
    )
    _write_csv(
        exp / "IDENTITY_PAIR_METADATA.csv",
        ["pair_id", "entity_a_id", "entity_b_id", "true_merge_status"],
        [
            {"pair_id": "IDP3-T1", "entity_a_id": M1, "entity_b_id": M2, "true_merge_status": "merged_same_canonical"},
            {"pair_id": "IDP3-T2", "entity_a_id": M1, "entity_b_id": M3, "true_merge_status": "distinct_canonical"},
        ],
    )
    _write_csv(
        exp / "PROVENANCE_SUPPORT_SAMPLE.csv",
        ["sample_id", "fact_id"],
        [
            {"sample_id": "PRV3-T1", "fact_id": "IFACT-P1"},
            {"sample_id": "PRV3-T2", "fact_id": "IFACT-P2"},
            {"sample_id": "PRV3-T3", "fact_id": "IFACT-P3"},
            {"sample_id": "PRV3-T4", "fact_id": "IFACT-P4"},
        ],
    )
    _write_csv(
        exp / "PROVENANCE_SUPPORT_METADATA.csv",
        ["sample_id", "fact_id", "research_tier", "confidence", "n_provenance_rows"],
        [
            {"sample_id": "PRV3-T1", "fact_id": "IFACT-P1", "research_tier": "strict_semantic", "confidence": "0.95", "n_provenance_rows": "2"},
            {"sample_id": "PRV3-T2", "fact_id": "IFACT-P2", "research_tier": "contextual", "confidence": "0.80", "n_provenance_rows": "1"},
            {"sample_id": "PRV3-T3", "fact_id": "IFACT-P3", "research_tier": "unresolved", "confidence": "0.60", "n_provenance_rows": "1"},
            {"sample_id": "PRV3-T4", "fact_id": "IFACT-P4", "research_tier": "unsupported", "confidence": "0.50", "n_provenance_rows": "0"},
        ],
    )
    # 冻结分类器分数表（mini sqlite）
    cls_path = exp / "classifier.sqlite"
    cls = sqlite3.connect(cls_path)
    cls.executescript(
        """
        create table entity_predictions(entity_id text primary key, canonical_name text,
            source_type text, predicted_type text, confidence real, margin real,
            class_gate_pass integer);
        """
    )
    cls.executemany(
        "insert into entity_predictions values (?,?,?,?,?,?,?)",
        [
            (M1, "梅溪镇", "Place", "Place", 0.90, 0.50, 1),
            (M2, "梅溪书院", "Institution", "Institution", 0.70, 0.20, 0),
            (M4, "共用名", "Person", "Person", 0.60, 0.10, 0),
        ],
    )
    cls.commit()
    cls.close()
    return base.InputPaths(
        entity_type_sample=exp / "ENTITY_TYPE_SAMPLE.csv",
        entity_type_metadata=exp / "ENTITY_TYPE_SAMPLE.sampling_metadata.csv",
        relation_contract_sample=exp / "RELATION_CONTRACT_SAMPLE.csv",
        scope_adjustment_tasks=exp / "SCOPE_ADJUSTMENT_TASKS.jsonl",
        identity_pair_tasks=exp / "IDENTITY_PAIR_TASKS.jsonl",
        identity_pair_metadata=exp / "IDENTITY_PAIR_METADATA.csv",
        provenance_sample=exp / "PROVENANCE_SUPPORT_SAMPLE.csv",
        provenance_metadata=exp / "PROVENANCE_SUPPORT_METADATA.csv",
        classifier_db=cls_path,
        classifier_model=exp / "missing_model.joblib",  # 默认无 joblib → B8 全网格 N/A
    )


@pytest.fixture()
def mini(tmp_path):
    conn = _build_db(tmp_path)
    inputs = _build_inputs(tmp_path)
    yield SimpleNamespace(tmp_path=tmp_path, conn=conn, inputs=inputs, out=tmp_path / "out09")
    conn.close()


def _rows_by_key(runs_csv: Path) -> dict[tuple[str, str], dict[str, str]]:
    with open(runs_csv, encoding="utf-8-sig", newline="") as fh:
        return {
            (r["sample_id"], r["method_id"]): r for r in csv.DictReader(fh)
        }


def _rows_by_sample(runs_csv: Path) -> dict[str, dict[str, str]]:
    """单方法 CSV（B3 runs）按 sample_id 索引。"""
    with open(runs_csv, encoding="utf-8-sig", newline="") as fh:
        return {r["sample_id"]: r for r in csv.DictReader(fh)}


def _default_run(mini) -> dict:
    return base.run(mini.out, conn=mini.conn, inputs=mini.inputs)


# ---------------------------------------------------------------------------
# B12 映射策略（§4.1–4.5）
# ---------------------------------------------------------------------------


def test_b12_entity_type_mapping(mini):
    _default_run(mini)
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    r1 = rows[("ETV3-T1", "B12_full_framework")]
    assert r1["item_id"] == C1
    assert r1["prediction"] == "Place"  # §4.1 research_entities.entity_type
    assert r1["confidence"] == f"{0.98:.12f}"  # §4.1 research_entities.confidence
    assert r1["hard_constraint_pass"] == "1"  # type_validation_status=='validated'
    assert r1["source_artifact"] == "production_release_fields"
    assert "entity_type+type_validation_status" in r1["note"]
    r2 = rows[("ETV3-T2", "B12_full_framework")]
    assert r2["hard_constraint_pass"] == "0"  # fallback_unresolved → 门不过
    assert r2["prediction"] == "Event"


def test_b12_relation_contract_mapping(mini):
    _default_run(mini)
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    # §4.2 release_tier → IMCR 四标签
    assert rows[("RC-T1", "B12_full_framework")]["prediction"] == "context_only"
    assert rows[("RC-T2", "B12_full_framework")]["prediction"] == "valid"
    assert rows[("RC-T3", "B12_full_framework")]["prediction"] == "insufficient_evidence"
    # confidence = research_assertions.confidence（sidecar 无该字段，直查库）
    assert rows[("RC-T1", "B12_full_framework")]["confidence"] == f"{0.95:.12f}"
    # gate = semantic_status=='auto_accepted' AND risk_tier∈{A,B}
    assert rows[("RC-T1", "B12_full_framework")]["hard_constraint_pass"] == "1"
    assert rows[("RC-T3", "B12_full_framework")]["hard_constraint_pass"] == "0"
    assert "invalid never predicted" in rows[("RC-T2", "B12_full_framework")]["note"]


def test_b12_scope_adjustment_mapping(mini):
    _default_run(mini)
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    for sid in ("SA-T1", "SA-T2"):
        r = rows[(sid, "B12_full_framework")]
        assert r["prediction"] == "AFTER_BETTER"  # §4.3 恒定
        assert r["confidence"] == ""  # 不虚构代理分数
        assert r["hard_constraint_pass"] == "1"
    assert rows[("SA-T1", "B12_full_framework")]["item_id"] == "IFACT-SA1"


def test_b12_identity_pair_mapping(mini):
    _default_run(mini)
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    # §4.4 共属查询：m1/m2 同属 C1 → same_entity；m1(C1)/m3(C2) → different_entity
    assert rows[("IDP3-T1", "B12_full_framework")]["prediction"] == "same_entity"
    assert rows[("IDP3-T2", "B12_full_framework")]["prediction"] == "different_entity"
    for sid in ("IDP3-T1", "IDP3-T2"):
        r = rows[(sid, "B12_full_framework")]
        assert r["confidence"] == ""
        assert r["hard_constraint_pass"] == "1"


def test_b12_provenance_mapping(mini):
    _default_run(mini)
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    expect = {
        "PRV3-T1": ("fully_supported", "1"),
        "PRV3-T2": ("partially_supported", "1"),
        "PRV3-T3": ("insufficient_evidence", "1"),
        "PRV3-T4": ("", "0"),  # unsupported 恒不预测；n_provenance_rows=0 → 门不过
    }
    for sid, (pred, gate) in expect.items():
        r = rows[(sid, "B12_full_framework")]
        assert r["prediction"] == pred, sid
        assert r["hard_constraint_pass"] == gate, sid
    assert rows[("PRV3-T1", "B12_full_framework")]["confidence"] == f"{0.95:.12f}"


# ---------------------------------------------------------------------------
# B1 规则基线（§5.1）
# ---------------------------------------------------------------------------


def test_b1_relation_contract_three_branches(mini):
    _default_run(mini)
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    # 分支 1：谓词存在且 domain/range 相容 → valid / 0.99 / gate=1
    b1 = rows[("RC-T1", "B1_rule_only")]
    assert b1["prediction"] == "valid"
    assert b1["confidence"] == f"{0.99:.12f}"
    assert b1["hard_constraint_pass"] == "1"
    # 分支 2：谓词存在但类型不兼容 → invalid / 0.90 / gate=0
    b2 = rows[("RC-T2", "B1_rule_only")]
    assert b2["prediction"] == "invalid"
    assert b2["confidence"] == f"{0.90:.12f}"
    assert b2["hard_constraint_pass"] == "0"
    # 分支 3：谓词未知 → 弃权（prediction 空，行 available，covered=0）
    b3 = rows[("RC-T3", "B1_rule_only")]
    assert b3["prediction"] == ""
    assert b3["availability_status"] == "available"
    assert b3["covered"] == "0"


def test_b1_entity_member_aggregation_and_abstain(mini):
    _default_run(mini)
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    # C1：M1(Place, 0.98) vs M2(Institution, 0.92) → 取置信最高成员 M1
    r = rows[("ETV3-T1", "B1_rule_only")]
    assert r["prediction"] == "Place"
    assert r["confidence"] == f"{0.98:.12f}"
    assert r["hard_constraint_pass"] == "1"
    assert "selected member=IENT-member1" in r["note"]
    # C3：跨类型同名成员规则弃权（model_review）→ prediction 空
    r3 = rows[("ETV3-T3", "B1_rule_only")]
    assert r3["prediction"] == ""
    assert r3["availability_status"] == "available"


def test_select_best_member_tie_rules():
    # 并列取成员间多数类型，再并列取类型字典序（§5.1 聚合规则）
    rows = [
        {"prediction": "Place", "confidence": 0.9},
        {"prediction": "Institution", "confidence": 0.9},
    ]
    assert base.select_best_member(rows)["prediction"] == "Institution"  # 字典序
    rows = [
        {"prediction": "Institution", "confidence": 0.9},
        {"prediction": "Place", "confidence": 0.9},
        {"prediction": "Place", "confidence": 0.9},
    ]
    assert base.select_best_member(rows)["prediction"] == "Place"  # 多数类型
    assert base.select_best_member([{"prediction": None, "confidence": None}]) is None


# ---------------------------------------------------------------------------
# B2 / B7 / B8（§5.2）
# ---------------------------------------------------------------------------


def test_b2_aggregation_and_not_available(mini):
    _default_run(mini)
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    # C1：M1 conf 0.90 > M2 conf 0.70 → 选 M1（Place）；gate=class_gate_pass
    r = rows[("ETV3-T1", "B2_frozen_classifier")]
    assert r["prediction"] == "Place"
    assert r["confidence"] == f"{0.90:.12f}"
    assert r["hard_constraint_pass"] == "1"
    # C2：成员无分数行 → not_available（prediction 空）
    r2 = rows[("ETV3-T2", "B2_frozen_classifier")]
    assert r2["availability_status"] == "not_available"
    assert r2["prediction"] == ""
    assert "frozen classifier score table" in r2["note"]
    # B7 同行预测，confidence = 所选成员 margin
    r7 = rows[("ETV3-T1", "B7_classifier_margin")]
    assert r7["prediction"] == "Place"
    assert r7["confidence"] == f"{0.50:.12f}"


def test_b8_entropy_with_joblib(mini, tmp_path):
    model_path = _build_tiny_joblib(tmp_path)
    inputs = base.InputPaths(**{**vars(mini.inputs), "classifier_model": model_path})
    base.run(mini.out, conn=mini.conn, inputs=inputs)
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    r = rows[("ETV3-T1", "B8_entropy_threshold")]
    assert r["availability_status"] == "available"
    assert r["prediction"] == "Place"  # 与 B2 同行预测
    conf = float(r["confidence"])
    assert 0.0 <= conf <= 1.0
    assert "normalized entropy" in r["note"]


def test_b8_all_grid_not_available_without_joblib(mini):
    summary = _default_run(mini)  # classifier_model 指向不存在的文件
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    for sid in ("ETV3-T1", "ETV3-T2", "ETV3-T3"):
        r = rows[(sid, "B8_entropy_threshold")]
        assert r["availability_status"] == "not_available"
        assert r["prediction"] == ""
        assert "joblib model missing" in r["note"]
    cell = [
        c
        for c in summary["matrix"]
        if c["method_id"] == "B8_entropy_threshold" and c["task_type"] == "entity_type"
    ][0]
    assert cell["availability_status"] == "not_available"
    assert "joblib" in cell["reason"]


def _build_tiny_joblib(tmp_path: Path) -> Path:
    """构造与冻结 bundle 同构（name/context vectorizer + log_loss SGD）的小模型。"""
    import joblib
    import numpy as np
    from scipy.sparse import hstack
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import SGDClassifier

    data = [
        ("梅溪镇", "IN::occurred_at::Event", "Place"),
        ("梅溪镇", "OUT::active_at::Place", "Place"),
        ("梅溪书院", "OUT::located_in::Place", "Institution"),
        ("梅溪书院", "IN::located_in::Event", "Institution"),
        ("起义事件", "OUT::occurred_at::Event", "Event"),
        ("起义事件", "OUT::active_at::Place", "Event"),
    ]
    nv = TfidfVectorizer(analyzer="char", ngram_range=(1, 2), min_df=1)
    cv = TfidfVectorizer(analyzer="word", token_pattern=r"[^ ]+", min_df=1)
    x = hstack(
        [nv.fit_transform([d[0] for d in data]), cv.fit_transform([d[1] for d in data])],
        format="csr",
        dtype=np.float32,
    )
    clf = SGDClassifier(loss="log_loss", random_state=0, max_iter=100, tol=1e-3)
    clf.fit(x, [d[2] for d in data])
    assert hasattr(clf, "predict_proba")
    path = tmp_path / "tiny_classifier.joblib"
    joblib.dump(
        {
            "version": "test-only",
            "name_vectorizer": nv,
            "context_vectorizer": cv,
            "classifier": clf,
        },
        path,
    )
    return path


def test_entropy_and_feature_text():
    assert base.proba_normalized_entropy([0.5, 0.5]) == pytest.approx(0.0)
    assert base.proba_normalized_entropy([1.0, 0.0]) == pytest.approx(1.0)
    assert base.proba_normalized_entropy([0.25] * 4) == pytest.approx(0.0)
    assert 0.0 < base.proba_normalized_entropy([0.7, 0.2, 0.1]) < 1.0
    name, ctx = base.member_feature_text(
        {"canonical_name": "梅溪镇", "aliases_json": '["梅溪"]'},
        {"OUT::a::B": 2, "IN::c::D": 5},
    )
    assert name == "梅溪镇 梅溪"
    assert ctx == "IN::c::D OUT::a::B"  # 按出现频次降序


# ---------------------------------------------------------------------------
# B4 / B5 / B9（§5.3）
# ---------------------------------------------------------------------------


def _write_fake_b3_csv(path: Path) -> None:
    rows = []
    for sid, pred, conf in (
        ("RC-T1", "invalid", "0.66"),
        ("RC-T2", "invalid", "0.70"),
        ("RC-T3", "context_only", "0.77"),
    ):
        rows.append(
            {
                "sample_id": sid,
                "task_type": "relation_contract",
                "item_id": "",
                "split": "independent_eval",
                "method_id": "B3_blind_llm",
                "method_name": "Blind LLM (fresh)",
                "evidence_class": "actual_run",
                "comparison_tier": "independent_reference",
                "overlap_status": "independent_of_era",
                "primary_comparison_eligible": "1",
                "evaluation_eligibility": "core_eligible_task",
                "availability_status": "available",
                "gold_label": "",
                "prediction": pred,
                "confidence": conf,
                "covered": "0",
                "correct": "0",
                "hard_constraint_pass": "1",
                "constraint_gate_source": "test-gate",
                "safe_correct": "0",
                "actual_llm_calls": "1",
                "source_artifact": "test",
                "note": "test",
            }
        )
    _write_csv(path, list(base.RUNS_FIELDS), rows)


def test_b4_rule_first_then_classifier_fallback(mini):
    _default_run(mini)
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    # 规则有预测 → 用规则（置信、门随规则）
    r = rows[("ETV3-T1", "B4_rule_plus_classifier")]
    assert r["prediction"] == "Place"
    assert r["confidence"] == f"{0.98:.12f}"
    assert "provider=rule" in r["note"]
    # 规则弃权（C3 model_review）→ 回退 B2 冻结分类器（门=class_gate_pass=0）
    r3 = rows[("ETV3-T3", "B4_rule_plus_classifier")]
    assert r3["prediction"] == "Person"
    assert r3["confidence"] == f"{0.60:.12f}"
    assert r3["hard_constraint_pass"] == "0"
    assert "provider=model" in r3["note"]


def test_b5_falls_back_to_b3_on_rule_abstain(mini, tmp_path):
    b3_csv = tmp_path / "b3.csv"
    _write_fake_b3_csv(b3_csv)
    base.run(mini.out, conn=mini.conn, inputs=mini.inputs, b3_runs=b3_csv)
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    # 规则弃权（RC-T3 未知谓词）→ 用 B3 盲 LLM 预测
    r = rows[("RC-T3", "B5_rule_plus_blind_llm")]
    assert r["prediction"] == "context_only"
    assert r["confidence"] == f"{0.77:.12f}"
    assert "provider=model" in r["note"]
    # 规则有预测 → 不用 B3
    assert rows[("RC-T1", "B5_rule_plus_blind_llm")]["prediction"] == "valid"
    assert "provider=rule" in rows[("RC-T1", "B5_rule_plus_blind_llm")]["note"]


def test_b5_without_b3_and_rule_abstain_not_available(mini):
    _default_run(mini)  # 无 B3 输入
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    r = rows[("RC-T3", "B5_rule_plus_blind_llm")]
    assert r["availability_status"] == "not_available"
    assert r["prediction"] == ""


def test_b9_agreement_signal(mini, tmp_path):
    b3_csv = tmp_path / "b3.csv"
    _write_fake_b3_csv(b3_csv)
    base.run(mini.out, conn=mini.conn, inputs=mini.inputs, b3_runs=b3_csv)
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    # entity_type（model=B2）：规则 Place == B2 Place → 1.0
    r = rows[("ETV3-T1", "B9_rule_model_agreement")]
    assert r["prediction"] == "Place"
    assert r["confidence"] == "1.0"
    # relation_contract（model=B3）：规则 valid != B3 invalid → 0.0；一致 → 1.0
    assert rows[("RC-T1", "B9_rule_model_agreement")]["confidence"] == "0.0"
    assert rows[("RC-T2", "B9_rule_model_agreement")]["confidence"] == "1.0"
    # 规则弃权 → prediction 空、行 available
    r3 = rows[("RC-T3", "B9_rule_model_agreement")]
    assert r3["prediction"] == ""
    assert r3["availability_status"] == "available"


def test_b9_not_available_when_model_signal_missing(mini):
    _default_run(mini)
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    # C2 无 B2 分数行 → 一致信号缺失 → not_available
    r = rows[("ETV3-T2", "B9_rule_model_agreement")]
    assert r["availability_status"] == "not_available"
    assert r["prediction"] == ""


# ---------------------------------------------------------------------------
# B10 / B11 消融（§7）
# ---------------------------------------------------------------------------


def test_b10_b11_differ_from_b12(mini):
    _default_run(mini)
    rows = _rows_by_key(mini.out / base.RUNS_NAME)
    # ETV3-T2 的 B12 门不过（fallback_unresolved）
    b12 = rows[("ETV3-T2", "B12_full_framework")]
    b10 = rows[("ETV3-T2", "B10_selective_no_structural_gate")]
    b11 = rows[("ETV3-T2", "B11_structural_gate_no_abstention")]
    assert b12["hard_constraint_pass"] == "0"
    # B10：结构门禁用 → gate 恒 1，prediction/confidence 与 B12 一致
    assert b10["hard_constraint_pass"] == "1"
    assert b10["prediction"] == b12["prediction"] == "Event"
    assert b10["confidence"] == b12["confidence"]
    # B11：无弃权 → confidence 恒 1.0，prediction/gate 与 B12 一致
    assert b11["confidence"] == "1.0"
    assert b11["prediction"] == b12["prediction"]
    assert b11["hard_constraint_pass"] == b12["hard_constraint_pass"]
    assert "ablation" in b10["note"] and "ablation" in b11["note"]
    # B10/B11 对全部五个任务型都有行（作用于 B12 预测）
    for task_sids in (("SA-T1",), ("IDP3-T1",), ("PRV3-T1",)):
        for sid in task_sids:
            assert rows[(sid, "B10_selective_no_structural_gate")]["prediction"]
            assert rows[(sid, "B11_structural_gate_no_abstention")]["prediction"]


# ---------------------------------------------------------------------------
# 23 列 schema 固定值
# ---------------------------------------------------------------------------


def test_schema_fixed_values(mini):
    _default_run(mini)
    with open(mini.out / base.RUNS_NAME, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        assert tuple(reader.fieldnames) == base.RUNS_FIELDS
        rows = list(reader)
    assert rows, "runs csv 必须非空"
    for r in rows:
        assert r["split"] == "independent_eval"
        assert r["evidence_class"] == "actual_run"
        assert r["comparison_tier"] == "independent_reference"
        assert r["overlap_status"] == "independent_of_era"
        assert r["primary_comparison_eligible"] == "1"
        assert r["covered"] == "0" and r["correct"] == "0" and r["safe_correct"] == "0"
        assert r["gold_label"] == ""
        if r["availability_status"] == "not_available":
            assert r["prediction"] == ""
            assert r["note"].startswith("NOT_AVAILABLE:")
        else:
            assert r["note"], "available 行必须写明映射规则"


# ---------------------------------------------------------------------------
# 合并去重 / 可用性矩阵 / manifest / audit / 幂等
# ---------------------------------------------------------------------------


def test_merge_append_runs_dedup_later_wins(mini, tmp_path):
    _default_run(mini)
    runs_csv = mini.out / base.RUNS_NAME
    before = _rows_by_key(runs_csv)
    n_before = len(before)

    append = tmp_path / "append.csv"
    override = dict(before[("ETV3-T1", "B12_full_framework")])
    override["prediction"] = "OverriddenType"
    b3_row = {k: "" for k in base.RUNS_FIELDS}
    b3_row.update(
        {
            "sample_id": "RC-T1",
            "task_type": "relation_contract",
            "method_id": "B3_blind_llm",
            "method_name": "Blind LLM (fresh)",
            "availability_status": "available",
            "prediction": "context_only",
            "confidence": "0.810000000000",
        }
    )
    _write_csv(append, list(base.RUNS_FIELDS), [override, b3_row])
    base.run(mini.out, conn=mini.conn, inputs=mini.inputs, append_runs=[append])

    after = _rows_by_key(runs_csv)
    assert len(after) == n_before + 1  # B12 行被覆盖（不重复），B3 行新增
    assert after[("ETV3-T1", "B12_full_framework")]["prediction"] == "OverriddenType"
    assert after[("RC-T1", "B3_blind_llm")]["prediction"] == "context_only"


def test_availability_matrix_completeness(mini, tmp_path):
    b3_csv = tmp_path / "b3.csv"
    _write_fake_b3_csv(b3_csv)
    # b3_runs 供 B5/B9 一致信号；append_runs 把 B3 行合并进最终 runs（矩阵由此统计）
    base.run(
        mini.out, conn=mini.conn, inputs=mini.inputs,
        b3_runs=b3_csv, append_runs=[b3_csv],
    )
    with open(mini.out / base.MATRIX_NAME, encoding="utf-8-sig", newline="") as fh:
        cells = {(r["method_id"], r["task_type"]): r for r in csv.DictReader(fh)}
    all_methods = set(base.METHODS) | set(base.MATRIX_ONLY_METHODS)
    assert len(cells) == len(all_methods) * len(base.ALL_TASKS)  # 12 方法 × 5 任务
    for method in all_methods:
        for task in base.ALL_TASKS:
            assert (method, task) in cells, (method, task)
    # B6 无独立行（≡B2 扫描）
    for task in base.ALL_TASKS:
        cell = cells[("B6_classifier_conf_threshold", task)]
        assert cell["availability_status"] == "not_available"
        assert "no separate rows" in cell["reason"]
    # B3 合并后 relation 单元格 available，行数与 fake CSV 一致
    b3_cell = cells[("B3_blind_llm", "relation_contract")]
    assert b3_cell["availability_status"] == "available"
    assert b3_cell["n_available"] == "3"
    # B2 在 relation_contract 上是设计 N/A 单元格（仍有逐样本 not_available 行）
    b2_cell = cells[("B2_frozen_classifier", "relation_contract")]
    assert b2_cell["availability_status"] == "not_available"
    assert int(b2_cell["n_rows"]) == 3  # 逐样本 N/A 行落盘，网格完整可审计


def test_manifest_and_audit(mini):
    summary = _default_run(mini)
    assert summary["audit"]["result"] == "PASS"
    manifest = json.loads((mini.out / base.MANIFEST_NAME).read_text(encoding="utf-8"))
    for field in MANIFEST_FIELDS:
        assert field in manifest
    assert manifest["mapping_strategy_version"] == base.MAPPING_STRATEGY_VERSION
    registry = manifest["not_available_registry"]
    assert isinstance(registry, list) and registry
    assert any(e["method_id"] == "B3_blind_llm" for e in registry)
    assert set(manifest["db_manifest"]) == {
        "final_db_path", "final_db_sha256", "semantic_db_path", "semantic_db_sha256",
    }
    assert len(manifest["db_manifest"]["final_db_sha256"]) == 64
    assert manifest["audit_result"] == "PASS"
    audit = json.loads((mini.out / base.AUDIT_NAME).read_text(encoding="utf-8"))
    assert audit["result"] == "PASS"
    assert all(audit["checks"].values())
    # audit 门真的会抓网格缺口：临时删一种方法的行后必须 FAIL
    rows = list(csv.DictReader(open(mini.out / base.RUNS_NAME, encoding="utf-8-sig", newline="")))
    broken = [r for r in rows if r["method_id"] != "B1_rule_only"]
    _write_csv(mini.out / "broken.csv", list(base.RUNS_FIELDS), broken)
    broken_samples = base.load_samples(mini.inputs, None)
    result = base.audit_rows(broken, broken_samples)
    assert result["result"] == "FAIL"
    assert not result["checks"]["grid_complete_method_x_task"]


def test_idempotent_rerun(mini, tmp_path):
    append = tmp_path / "append.csv"
    row = {k: "" for k in base.RUNS_FIELDS}
    row.update(
        {
            "sample_id": "RC-T1",
            "task_type": "relation_contract",
            "method_id": "B3_blind_llm",
            "prediction": "context_only",
            "availability_status": "available",
        }
    )
    _write_csv(append, list(base.RUNS_FIELDS), [row])
    base.run(mini.out, conn=mini.conn, inputs=mini.inputs, append_runs=[append])
    first_runs = (mini.out / base.RUNS_NAME).read_bytes()
    first_matrix = (mini.out / base.MATRIX_NAME).read_bytes()
    base.run(mini.out, conn=mini.conn, inputs=mini.inputs, append_runs=[append])
    assert (mini.out / base.RUNS_NAME).read_bytes() == first_runs
    assert (mini.out / base.MATRIX_NAME).read_bytes() == first_matrix


def test_limit_smoke(mini):
    summary = base.run(mini.out, conn=mini.conn, inputs=mini.inputs, limit=1)
    assert summary["audit"]["result"] == "PASS"
    assert summary["n_rows"] == len(base.METHOD_ORDER) * 5  # 每任务 1 样本 × 11 方法
    with open(mini.out / base.RUNS_NAME, encoding="utf-8-sig", newline="") as fh:
        tasks = {r["task_type"] for r in csv.DictReader(fh)}
    assert tasks == set(base.ALL_TASKS)


# ---------------------------------------------------------------------------
# B3 盲 LLM（run_blind_llm_baseline.py，dry-run 全链路）
# ---------------------------------------------------------------------------

GOAL_11_FIELDS = (
    "model_id", "provider", "prompt_version", "temperature", "top_p", "seed",
    "timestamp", "raw_response", "parsed_response", "retry_count", "validation_error",
)


def _append_payload(payloads_dir: Path, task_type: str, record: dict) -> dict:
    spec = defs.PIPELINE_TASK_SPECS[task_type]
    payload, meta = build_blind_payload(
        record, spec, seed=7, prompt_template=defs.PROMPT_TEMPLATES[task_type]
    )
    path = payloads_dir / defs.TASK_REGISTRY[task_type]["output"]
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {
        "task_id": meta["task_id"],
        "task_type": task_type,
        "prompt_version": meta["prompt_version"],
        "allowed_labels": meta["allowed_labels"],
        "prompt_sha256": meta["prompt_sha256"],
        "payload": payload,
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return meta


def _make_blind_fixture(tmp_path: Path):
    """payloads（4 个任务型）+ 最小 inputs/conn（门与 item_id 映射所需）。"""
    payloads_dir = tmp_path / "payloads"
    metas: dict[str, dict] = {}
    metas["entity_type"] = [
        _append_payload(
            payloads_dir,
            "entity_type",
            {
                "task_id": tid,
                "entity_name": name,
                "aliases": [],
                "context_assertions": "",
                "source_excerpt": "",
                "candidate_types": list(defs.ENTITY_TYPE_LABELS),
                "type_definitions": {},
            },
        )
        for tid, name in (("ETV3-B1", "梅溪镇"), ("ETV3-B2", "红军战士"))
    ]
    for tid, stype, otype in (
        ("RC-B1", "Organization", "Place"),
        ("RC-B2", "Event", "Place"),
    ):
        metas.setdefault("relation_contract", []).append(
            _append_payload(
                payloads_dir,
                "relation_contract",
                {
                    "task_id": tid,
                    "subject_text": "某部",
                    "subject_type": stype,
                    "relation_text": "active_at",
                    "object_text": "梅溪",
                    "object_type": otype,
                    "evidence_excerpts": [],
                    "schema_definitions": "",
                },
            )
        )
    metas["scope_adjustment"] = [
        _append_payload(
            payloads_dir,
            "scope_adjustment",
            {
                "task_id": "SA-B1",
                "assertion_text": "断言",
                "evidence_excerpts": [],
                "evidence_availability_note": "",
                "local_relation_context": {},
                "schema_definitions": {},
                "before": {"time_role": "event_occurrence"},
                "after": {"time_role": "relation_validity"},
            },
        )
    ]
    metas["provenance_support"] = [
        _append_payload(
            payloads_dir,
            "provenance_support",
            {
                "task_id": "PRV3-B1",
                "assertion_text": "断言",
                "evidence_excerpts": ["证据"],
                "citation_metadata": {"source_titles": "文献"},
            },
        )
    ]
    # scope A/B 映射 CSV（与 build_blind_payload 的实际 a/b 指派一致）
    scope_meta = metas["scope_adjustment"][0]
    mapping = scope_meta["ab_mapping"]  # {"a": "before"/"after", ...}
    _write_csv(
        payloads_dir / "SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING.csv",
        ["task_id", "a", "b"],
        [{"task_id": "SA-B1", "a": mapping["a"], "b": mapping["b"]}],
    )
    inputs = _build_inputs(tmp_path)
    # 追加 blind fixture 需要的样本行（item_id 映射 + entity 门资源）
    _append_entity_rows(inputs)
    blind_db_dir = tmp_path / "blinddb"
    blind_db_dir.mkdir()
    conn = _build_db(blind_db_dir)
    return payloads_dir, inputs, conn


def _append_entity_rows(inputs: base.InputPaths) -> None:
    """在 fixture 样本文件后追加 blind 测试的样本行。"""
    with open(inputs.entity_type_sample, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ETV3-B1", C1, "梅溪镇"])
        w.writerow(["ETV3-B2", C3, "红军战士"])
    with open(inputs.relation_contract_sample, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["RC-B1", "IFACT-B1", "active_at", "Organization", "Place",
                    "contextual", "auto_accepted", "A"])
        w.writerow(["RC-B2", "IFACT-B2", "active_at", "Event", "Place",
                    "strict_semantic", "auto_accepted", "A"])
    with open(inputs.scope_adjustment_tasks, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"task_id": "SA-B1", "fact_id": "IFACT-B3"}, ensure_ascii=False) + "\n")
    with open(inputs.provenance_sample, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["PRV3-B1", "IFACT-B4"])


def _fixed_responder(decisions: dict[str, str], invalid: frozenset[str] = frozenset()):
    def responder(task_id: str, allowed_labels):
        if task_id in invalid:
            return "MODEL OUTPUT IS NOT JSON AT ALL"
        return {
            "task_id": task_id,
            "decision": decisions[task_id],
            "confidence": 0.8,
            "evidence": ["dry evidence"],
            "reason_code": "FIXED",
            "explanation": "固定假响应",
            "insufficient_evidence": False,
        }

    return responder


def test_blind_dry_run_end_to_end(tmp_path):
    payloads_dir, inputs, conn = _make_blind_fixture(tmp_path)
    decisions = {
        "ETV3-B1": "Place", "ETV3-B2": "Person",
        "RC-B1": "valid", "RC-B2": "context_only",
        "SA-B1": "A_BETTER", "PRV3-B1": "fully_supported",
    }
    tasks = ["entity_type", "relation_contract", "scope_adjustment", "provenance_support"]
    summary = blind.run(
        payloads_dir,
        tmp_path / "out",
        dry_run=True, limit=None, resume=False, overwrite=False,
        tasks=tasks, conn=conn, inputs=inputs,
        fake_responder=_fixed_responder(decisions),
    )
    assert summary["model"]["model"] == "dry-run-blind-llm"
    out = tmp_path / "out"
    # 调用日志：字段与 judge raw_runs 同构 + blind_baseline
    for task in tasks:
        log = out / "blind_llm_runs" / f"{task}.jsonl"
        records = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
        assert records
        for rec in records:
            for field in GOAL_11_FIELDS:
                assert field in rec
            assert rec["blind_baseline"] is True
            assert rec["task_type"] == task
            assert rec["status"] == "OK"
            assert rec["dry_run"] is True
            assert rec["temperature"] == 0.0
            assert rec["top_p"] == 1.0
            assert rec["seed"] == derive_seed("blind_llm_baseline")
    # CSV：23 列、method_id=B3_blind_llm、scope A/B 解码
    with open(out / blind.BLIND_RUNS_NAME, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        assert tuple(reader.fieldnames) == base.RUNS_FIELDS
        rows = {(r["sample_id"]): r for r in reader}
    assert set(rows) == {"ETV3-B1", "ETV3-B2", "RC-B1", "RC-B2", "SA-B1", "PRV3-B1"}
    assert rows["ETV3-B1"]["method_id"] == "B3_blind_llm"
    assert rows["ETV3-B1"]["prediction"] == "Place"
    assert rows["ETV3-B1"]["hard_constraint_pass"] == "1"  # 梅溪镇→Place 过 contraindication
    assert rows["ETV3-B2"]["prediction"] == "Person"
    assert rows["ETV3-B2"]["hard_constraint_pass"] == "0"  # 泛指集体名不能为具体 Person
    assert rows["RC-B1"]["prediction"] == "valid"
    assert rows["RC-B1"]["hard_constraint_pass"] == "1"  # 契约相容 → valid 主张过门
    assert rows["RC-B2"]["hard_constraint_pass"] == "1"  # 非 valid 标签不主张严格语义
    sa = rows["SA-B1"]
    # A_BETTER 依 AB 映射文件解码（映射 a=before → BEFORE_BETTER）
    with open(payloads_dir / "SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING.csv", encoding="utf-8-sig") as fh:
        ab = next(csv.DictReader(fh))
    expected_sa = "BEFORE_BETTER" if ab["a"] == "before" else "AFTER_BETTER"
    assert sa["prediction"] == expected_sa
    assert sa["hard_constraint_pass"] == "1"  # scope gate=1
    assert "decode_ab_label" in sa["note"]
    assert rows["PRV3-B1"]["prediction"] == "fully_supported"
    assert rows["PRV3-B1"]["hard_constraint_pass"] == "1"  # 其余任务型 gate=1
    for r in rows.values():
        assert r["confidence"] == f"{0.8:.12f}"
        assert r["actual_llm_calls"] == "1"
        assert r["gold_label"] == "" and r["covered"] == "0"
    blob = "\n".join(
        p.read_text(encoding="utf-8") for p in out.rglob("*") if p.is_file()
    )
    assert "dry-run-placeholder" not in blob  # API key 占位符绝不落盘


def test_blind_scope_decode_direction(tmp_path):
    """A_BETTER 按 AB 映射解码：a=before → BEFORE_BETTER；a=after → AFTER_BETTER。"""
    payloads_dir, inputs, conn = _make_blind_fixture(tmp_path)
    # 改写映射为 a=after（与 build_blind_payload meta 相反），解码方向必须跟随文件
    _write_csv(
        payloads_dir / "SCOPE_ADJUSTMENT_PAYLOAD_AB_MAPPING.csv",
        ["task_id", "a", "b"],
        [{"task_id": "SA-B1", "a": "after", "b": "before"}],
    )
    blind.run(
        payloads_dir, tmp_path / "out",
        dry_run=True, limit=None, resume=False, overwrite=False,
        tasks=["scope_adjustment"], conn=conn, inputs=inputs,
        fake_responder=_fixed_responder({"SA-B1": "A_BETTER"}),
    )
    rows = _rows_by_sample(tmp_path / "out" / blind.BLIND_RUNS_NAME)
    assert rows["SA-B1"]["prediction"] == "AFTER_BETTER"


def test_blind_model_output_invalid_landed(tmp_path):
    payloads_dir, inputs, conn = _make_blind_fixture(tmp_path)
    blind.run(
        payloads_dir, tmp_path / "out",
        dry_run=True, limit=None, resume=False, overwrite=False,
        tasks=["entity_type"], conn=conn, inputs=inputs,
        fake_responder=_fixed_responder({"ETV3-B1": "Place", "ETV3-B2": "Place"},
                                        invalid=frozenset({"ETV3-B2"})),
    )
    out = tmp_path / "out"
    rows = _rows_by_sample(out / blind.BLIND_RUNS_NAME)
    bad = rows["ETV3-B2"]
    assert bad["availability_status"] == "not_available"
    assert bad["prediction"] == ""
    assert MODEL_OUTPUT_INVALID in bad["note"]
    assert bad["actual_llm_calls"] == "4"  # 1 次初始 + 3 次有界重试
    good = rows["ETV3-B1"]
    assert good["availability_status"] == "available"
    # 原始无效记录保留在 jsonl（每 task 一条最终记录；绝不手工改答案）
    records = [
        json.loads(l)
        for l in (out / "blind_llm_runs" / "entity_type.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    invalid = [r for r in records if r["task_id"] == "ETV3-B2"]
    assert len(invalid) == 1
    assert invalid[0]["status"] == MODEL_OUTPUT_INVALID
    assert invalid[0]["retry_count"] == 3  # 1 次初始 + 3 次有界重试
    assert invalid[0]["validation_error"]
    assert invalid[0]["parsed_response"] is None


def test_blind_resume_idempotent(tmp_path):
    payloads_dir, inputs, conn = _make_blind_fixture(tmp_path)
    out = tmp_path / "out"
    kwargs = dict(
        dry_run=True, limit=None, overwrite=False, tasks=["entity_type"],
        conn=conn, inputs=inputs,
        fake_responder=_fixed_responder({"ETV3-B1": "Place", "ETV3-B2": "Place"}),
    )
    first = blind.run(payloads_dir, out, resume=False, **kwargs)
    assert first["tasks"]["entity_type"]["OK"] == 2
    csv_first = (out / blind.BLIND_RUNS_NAME).read_bytes()
    log_lines = len(
        (out / "blind_llm_runs" / "entity_type.jsonl").read_text(encoding="utf-8").splitlines()
    )
    second = blind.run(payloads_dir, out, resume=True, **kwargs)
    assert second["tasks"]["entity_type"]["SKIPPED"] == 2
    assert second["tasks"]["entity_type"]["OK"] == 0
    log_after = (out / "blind_llm_runs" / "entity_type.jsonl").read_text(encoding="utf-8")
    assert len(log_after.splitlines()) == log_lines  # 日志未翻倍
    # CSV 重建后逐字节一致（无时间戳列；决策/置信确定）
    assert (out / blind.BLIND_RUNS_NAME).read_bytes() == csv_first
    # 已有输出且未给 --resume/--overwrite：拒绝运行（保护真实记录）
    with pytest.raises(FileExistsError):
        blind.run(payloads_dir, out, resume=False, **kwargs)


def test_blind_missing_env_error(monkeypatch):
    for var in ("BLIND_LLM_BASE_URL", "BLIND_LLM_API_KEY", "BLIND_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(blind.JudgeClientError) as excinfo:
        blind.discover_blind_config(dry_run=False, env={})
    assert "BLIND_LLM_BASE_URL" in str(excinfo.value)


def test_blind_limit(tmp_path):
    payloads_dir, inputs, conn = _make_blind_fixture(tmp_path)
    summary = blind.run(
        payloads_dir, tmp_path / "out",
        dry_run=True, limit=1, resume=False, overwrite=False,
        tasks=["entity_type"], conn=conn, inputs=inputs,
        fake_responder=_fixed_responder({"ETV3-B1": "Place"}),
    )
    assert summary["tasks"]["entity_type"]["OK"] == 1
    rows = _rows_by_sample(tmp_path / "out" / blind.BLIND_RUNS_NAME)
    assert set(rows) == {"ETV3-B1"}
