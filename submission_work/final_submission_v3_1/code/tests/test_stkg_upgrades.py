# -*- coding: utf-8 -*-
"""test_stkg_upgrades.py — STKG 升级 U1-U8 的核心不变量测试（小型 fixture sqlite）。

不触碰真实发布库：fixture 在 tmp_path 中从零构建，逐项断言：
  U1  帧→断言→provenance 链路行数 / 有 provenance 帧数 / 可定位证据帧数；
  U2  同 (s,p,o,τ,λ) 合并保留唯一 canonical、merged_into 指向、物理保留、
      文本五元组相同但归一化键分歧的组 kept_distinct、provenance 多重性归并；
  U3  trusted > asserted > stage 三档回填与 fallback_to_stage 显式标注；
  U4  同主体（共享参与者）候选限制 + before/after/overlaps/during 手算用例 + 非因果约束；
  U5  Allen 9 种区间关系手算用例 + merged 事实不参与 + 精度取最粗已知；
  U6  规则表裁判的选择性回填：action=REWRITE 才回填（fixture 规则文件），
      生产规则表（RETAIN/UNRESOLVED）⇒ 0 行回填、覆盖率不变（无全局启发式）；
  U7  双端空间类型硬约束（组织当空间父节点被拒）、显式断言 status、
      province/city/county 字段链、unresolved 不收编、类型/悬挂/环不变量；
  U8  只建语料证据支持的历史地名版本：改称/原名/时属 手算用例 + 人名/组织名不建版本 +
      泛称 needs_review + 证据必填；
  幂等性：二次运行跳过已完成项且计数不变；
  完整性自检：quick_check/foreign_key/U2 残余重复/U4·U5 复算一致/U7·U8 类型约束全过。
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PIPELINE = _HERE.parent / "experiment_pipelines" / "apply_stkg_upgrades.py"

_spec = importlib.util.spec_from_file_location("apply_stkg_upgrades", _PIPELINE)
apply_stkg_upgrades = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apply_stkg_upgrades)


# ---------------------------------------------------------------------------
# fixture 数据库
# ---------------------------------------------------------------------------
def _build_fixture(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE research_entities (
            entity_id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL,
            entity_type TEXT NOT NULL);
        CREATE TABLE research_assertions (
            fact_id TEXT PRIMARY KEY,
            subject_id TEXT NOT NULL, predicate TEXT NOT NULL, object_id TEXT NOT NULL,
            subject_type TEXT, object_type TEXT,
            time_raw TEXT, place_raw TEXT,
            time_start TEXT, time_end TEXT, time_precision TEXT,
            canonical_space_anchor_id TEXT,
            province TEXT, city TEXT, county TEXT,
            time_role TEXT DEFAULT 'unknown', time_owner_id TEXT,
            space_role TEXT DEFAULT 'unknown', space_owner_id TEXT,
            research_tier TEXT NOT NULL, semantic_status TEXT NOT NULL);
        CREATE TABLE research_assertion_provenance (
            provenance_id TEXT PRIMARY KEY, fact_id TEXT NOT NULL,
            provenance_kind TEXT NOT NULL, evidence_ids_json TEXT NOT NULL);
        CREATE TABLE research_event_frames (
            event_id TEXT PRIMARY KEY, event_name TEXT NOT NULL,
            observed_time_start TEXT, observed_time_end TEXT,
            observed_time_status TEXT NOT NULL);
        CREATE TABLE research_event_assertion_links (
            event_id TEXT NOT NULL, fact_id TEXT NOT NULL, time_role TEXT NOT NULL,
            PRIMARY KEY (event_id, fact_id));
        CREATE TABLE research_event_roles (
            event_id TEXT NOT NULL, counterpart_id TEXT NOT NULL,
            PRIMARY KEY (event_id, counterpart_id));
        CREATE TABLE research_culture_states (
            state_id TEXT PRIMARY KEY, stage_code TEXT NOT NULL,
            culture_subject_id TEXT NOT NULL);
        CREATE TABLE research_culture_state_events (
            state_id TEXT NOT NULL, event_id TEXT NOT NULL,
            PRIMARY KEY (state_id, event_id));
        CREATE TABLE research_culture_state_support (
            state_id TEXT NOT NULL, fact_id TEXT NOT NULL, support_role TEXT,
            PRIMARY KEY (state_id, fact_id));
        CREATE TABLE research_historical_stages (
            stage_code TEXT PRIMARY KEY, time_start TEXT NOT NULL, time_end TEXT NOT NULL);
        CREATE TABLE research_event_relations (fact_id TEXT PRIMARY KEY);
        CREATE TABLE research_evolution_transitions (transition_id TEXT PRIMARY KEY);
    """)

    con.execute("INSERT INTO research_historical_stages VALUES "
                "('war_of_resistance','1937-07-07','1945-09-02')")

    ents = [("E-S1", "主体一", "Person"), ("E-S2", "主体二", "Person"),
            ("E-O1", "组织一", "Organization"), ("E-P1", "地点一", "Place"),
            ("E-P2", "地点二", "Place"),
            ("E-PRV", "测试省", "AdministrativeRegion"),
            ("E-CTY", "测试市", "AdministrativeRegion"),
            ("E-CNTY", "测试县", "AdministrativeRegion"),
            ("E-EV1", "事件实体一", "Event"),
            ("E-BJ", "北京", "Place"), ("E-BP", "北平", "Place"),
            ("E-LJZ", "临江镇", "Place"), ("E-LLX", "庐陵县", "AdministrativeRegion"),
            ("E-Q1", "一区", "AdministrativeRegion"), ("E-Q2", "二区", "AdministrativeRegion"),
            ("E-LISI", "李四", "Person"),
            ("E-NGH", "农救会", "Place")]   # 上游误标为 Place 的组织（名称后缀复核位用例）
    con.executemany("INSERT INTO research_entities VALUES (?,?,?)", ents)

    def fact(fid, s, p, o, ts=None, te=None, tp="unknown", traw=None, praw=None,
             anchor=None, tier="strict_semantic", stype="Person", otype="Organization",
             province=None, city=None, county=None,
             time_role="unknown", time_owner_id=None,
             space_role="unknown", space_owner_id=None):
        return (fid, s, p, o, stype, otype, traw, praw, ts, te, tp, anchor,
                province, city, county, time_role, time_owner_id,
                space_role, space_owner_id, tier, "auto_accepted")

    facts = []
    provs = []

    def add_fact(fid, s, p, o, ts, te, tp="unknown", anchor=None, evidence=None,
                 prov=1, tier="strict_semantic", traw=None, **kw):
        facts.append(fact(fid, s, p, o, ts, te, tp, traw=traw, anchor=anchor,
                          tier=tier, **kw))
        for k in range(prov):
            ev = json.dumps(evidence if evidence else [])
            provs.append((f"PROV-{fid}-{k}", fid, "integrated_fact_member", ev))

    # ---- U1：帧 F1（两个成员事实，一个带证据） / F5（成员事实无证据）
    add_fact("F-U1-A1", "E-S1", "member_of", "E-O1", "1938-01-01", "1938-12-31",
             evidence=["EV-1"])
    add_fact("F-U1-A2", "E-S1", "member_of", "E-O1", "1939-01-01", "1939-12-31",
             evidence=[])
    add_fact("F-U1-A3", "E-S2", "member_of", "E-O1", "1938-01-01", "1938-12-31",
             evidence=[])
    con.executemany("INSERT INTO research_event_frames VALUES (?,?,?,?,?)", [
        ("E-F1", "事件一", "1938-01-01", "1938-06-30", "trusted"),
        ("E-F2", "事件二", "1938-06-01", "1938-12-31", "trusted"),
        ("E-F3", "事件三", "1936-01-01", "1936-12-31", "asserted_candidate"),
        ("E-F4", "事件四", "1938-02-01", "1938-03-31", "asserted_candidate"),
        ("E-F5", "事件五", None, None, "none"),
        ("E-F6", "事件六", "1938-01-01", "1938-12-31", "trusted"),
    ])
    con.executemany("INSERT INTO research_event_assertion_links VALUES (?,?,?)", [
        ("E-F1", "F-U1-A1", "event_occurrence"), ("E-F1", "F-U1-A2", "member_of"),
        ("E-F5", "F-U1-A3", "member_of"),
        ("E-F1", "F-OCC-F1", "event_occurrence"), ("E-F2", "F-OCC-F2", "event_occurrence"),
        ("E-F3", "F-OCC-F3", "event_occurrence"), ("E-F4", "F-OCC-F4", "event_occurrence"),
        ("E-F6", "F-OCC-F6", "event_occurrence"),
    ])
    # 帧精度来源事实（occurrence）
    add_fact("F-OCC-F1", "E-F1", "occurred_during", "E-S1", "1938-01-01", "1938-06-30", tp="year")
    add_fact("F-OCC-F2", "E-F2", "occurred_during", "E-S1", "1938-06-01", "1938-12-31", tp="month")
    add_fact("F-OCC-F3", "E-F3", "occurred_during", "E-S1", "1936-01-01", "1936-12-31", tp="period")
    add_fact("F-OCC-F4", "E-F4", "occurred_during", "E-S1", "1938-02-01", "1938-03-31", tp="unknown")
    add_fact("F-OCC-F6", "E-F6", "occurred_during", "E-S1", "1938-01-01", "1938-12-31", tp="year")

    # U4 参与者：F1/F2/F3/F4 共享参与者 E-S1；F6 只与 F2 共享；F5 无
    con.executemany("INSERT INTO research_event_roles VALUES (?,?)", [
        ("E-F1", "E-S1"), ("E-F2", "E-S1"), ("E-F3", "E-S1"), ("E-F4", "E-S1"),
        ("E-F2", "E-S2"), ("E-F6", "E-S2"),
    ])

    # ---- U2：同 (s,p,o,τ,λ) 两条 → 合并；文本五元组同但 anchor 分歧 → kept_distinct
    add_fact("F-U2-A", "E-S2", "member_of", "E-O1", "1940-01-01", "1940-12-31",
             anchor="E-P1", prov=1, traw="1940")
    add_fact("F-U2-B", "E-S2", "member_of", "E-O1", "1940-01-01", "1940-12-31",
             anchor="E-P1", prov=2, traw="1940")   # 多重 provenance 归并到 canonical
    add_fact("F-U2-K1", "E-S2", "member_of", "E-O1", "1941-01-01", "1941-12-31",
             anchor="E-P1", traw="1941")
    add_fact("F-U2-K2", "E-S2", "member_of", "E-O1", "1941-01-01", "1941-12-31",
             anchor="E-P2", traw="1941")  # 文本同、归一化 λ 分歧 → 不合并

    # ---- U5：同主体 S1 的 Allen 手算用例（fact_id 字典序控制方向）
    add_fact("F-U5-00", "E-S1", "active_at", "E-P1", "1938-09-01", "1938-09-30", tp="period")
    add_fact("F-U5-01", "E-S1", "active_at", "E-P1", "1938-01-01", "1938-01-31", tp="month")
    add_fact("F-U5-02", "E-S1", "active_at", "E-P1", "1938-02-01", "1938-03-01", tp="year")
    add_fact("F-U5-03", "E-S1", "active_at", "E-P1", "1938-03-01", "1938-04-15")
    add_fact("F-U5-04", "E-S1", "active_at", "E-P1", "1938-03-15", "1938-06-30")
    add_fact("F-U5-05", "E-S1", "active_at", "E-P1", "1938-04-01", "1938-04-30")
    # equals 04（不同 anchor，避免 U2 身份合并吞掉 equals 用例）
    add_fact("F-U5-06", "E-S1", "active_at", "E-P2", "1938-03-15", "1938-06-30")
    add_fact("F-U5-07", "E-S1", "active_at", "E-P1", "1938-03-15", "1938-12-31")   # starts 04
    add_fact("F-U5-08", "E-S1", "active_at", "E-P1", "1938-01-01", "1938-06-30")   # ends 04
    add_fact("F-U5-09", "E-S1", "active_at", "E-P1", "1938-04-05", "1938-04-25")   # during (09,10)
    # 同 05 区间但不同 anchor（避免 U2 身份合并吞掉 during 用例）
    add_fact("F-U5-10", "E-S1", "active_at", "E-P2", "1938-04-01", "1938-04-30")
    add_fact("F-U5-11", "E-S1", "active_at", "E-P2", "1938-05-01", "1938-05-31")

    # ---- U5 merged 事实排除验证载体：U2 的合并事实主体是 S2，不产生同主体对

    # ---- U6：Event 主体的 time_role='unknown' 事实（回填与否由规则表裁判）
    add_fact("F-U6-EV", "E-EV1", "participated_in", "E-O1", "1938-01-01", "1938-12-31",
             stype="Event", otype="Organization")

    # ---- U7：显式 located_in 断言（strict/contextual/unresolved）+ 类型违例 + 字段链
    add_fact("F-U7-S1", "E-P2", "located_in", "E-P1", None, None,
             stype="Place", otype="Place")                       # strict，双端 Place → auto_typed
    add_fact("F-U7-BADPARENT", "E-P1", "located_in", "E-O1", None, None,
             stype="Place", otype="Organization")                # 组织当空间父节点 → 拒绝
    add_fact("F-U7-CTX", "E-P1", "located_in", "E-CTY", None, None,
             tier="contextual", stype="Place",
             otype="AdministrativeRegion")                       # contextual → needs_review
    add_fact("F-U7-UNRES", "E-P2", "located_in", "E-CTY", None, None,
             tier="unresolved", stype="Place",
             otype="AdministrativeRegion")                       # unresolved → 不收编
    add_fact("F-U7-ORGNAME", "E-P1", "located_in", "E-NGH", None, None,
             stype="Place", otype="Place")                       # 实体类型是 Place 但名字是组织
                                                                 # → needs_review 复核位
    add_fact("F-U7-CHAIN", "E-S1", "happened_at", "E-P1", None, None,
             province="测试省", city="测试市")                    # 字段链：市 located_in 省
    add_fact("F-U7-CHAIN2", "E-S1", "occurred_near", "E-P1", None, None,
             city="测试市", county="测试县")                      # 字段链：县 located_in 市

    con.executemany("INSERT INTO research_assertions VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", facts)
    con.executemany("INSERT INTO research_assertion_provenance VALUES (?,?,?,?)", provs)

    # ---- U3：三种状态
    con.executemany("INSERT INTO research_culture_states VALUES (?,?,?)", [
        ("ST1", "war_of_resistance", "E-S1"),
        ("ST2", "war_of_resistance", "E-S1"),
        ("ST3", "war_of_resistance", "E-S1"),
    ])
    con.executemany("INSERT INTO research_culture_state_events VALUES (?,?)", [
        ("ST1", "E-F1"),      # trusted 帧
        ("ST2", "E-F4"),      # asserted 帧
    ])
    con.executemany("INSERT INTO research_culture_state_support VALUES (?,?,?)", [
        ("ST3", "F-U1-A3", "support"),
    ])
    con.commit()
    con.close()


@pytest.fixture()
def fixture_db(tmp_path):
    db = tmp_path / "fixture.sqlite"
    _build_fixture(db)
    return db


def _write_corpus_file(path: Path) -> Path:
    """U8 语料 fixture：改称（带年份）/时属/人名原名/组织改称/泛称改称 各一例。"""
    rows = [
        ["id", "name", "layer", "content", "date", "source", "tags"],
        ["c0001", "n1", "document", "1928年北京改称北平。", "2026-03-09", "s", "t"],
        ["c0002", "n2", "document", "临江镇（时属庐陵县）。", "2026-03-09", "s", "t"],
        ["c0003", "n3", "document", "李四原名张三，后来参加革命。", "2026-03-09", "s", "t"],
        ["c0004", "n4", "document", "该游击队改称独立团。", "2026-03-09", "s", "t"],
        ["c0005", "n5", "document", "一区改为二区。", "2026-03-09", "s", "t"],
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    return path


def _run(fixture_db, extra=()):
    corpus = _write_corpus_file(fixture_db.parent / "corpus.csv")
    rc = apply_stkg_upgrades.main(
        ["--target", str(fixture_db), "--sem", str(fixture_db.parent / "no_sem.sqlite"),
         "--no-copy", "--corpus", str(corpus), *extra])
    assert rc == 0
    return rc


def _con(fixture_db):
    con = sqlite3.connect(str(fixture_db))
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------------------
# U1
# ---------------------------------------------------------------------------
def test_u1_frame_provenance_chain(fixture_db):
    _run(fixture_db)
    con = _con(fixture_db)
    assert con.execute("SELECT count(*) FROM event_frame_provenance").fetchone()[0] == 8
    frames_prov = con.execute(
        "SELECT count(DISTINCT frame_id) FROM event_frame_provenance").fetchone()[0]
    assert frames_prov == 6            # E-F1..E-F6（E-F5 亦有成员事实 provenance）
    locatable = con.execute(
        "SELECT count(DISTINCT frame_id) FROM event_frame_provenance "
        "WHERE json_array_length(evidence_ids_json) > 0").fetchone()[0]
    assert locatable == 1              # 只有 E-F1 经 F-U1-A1 携带证据
    # 物理表不视图； provenance 源行仍在
    assert con.execute(
        "SELECT count(*) FROM research_assertion_provenance").fetchone()[0] > 0
    con.close()


# ---------------------------------------------------------------------------
# U2
# ---------------------------------------------------------------------------
def test_u2_merges_identity_duplicates_and_keeps_rows(fixture_db):
    _run(fixture_db)
    con = _con(fixture_db)
    # canonical = 字典序最小 fact_id；其余 merged_into；物理保留
    row_b = con.execute(
        "SELECT merged_into, merge_rule FROM research_assertions WHERE fact_id='F-U2-B'"
    ).fetchone()
    assert row_b["merged_into"] == "F-U2-A"
    assert row_b["merge_rule"] == "state_identity_exact_v1"
    assert con.execute(
        "SELECT 1 FROM research_assertions WHERE fact_id='F-U2-B'").fetchone() is not None

    # 文本五元组同但归一化 λ 分歧 → kept_distinct_source，不合并
    res = con.execute(
        "SELECT resolution FROM research_assertion_identity_collisions "
        "WHERE subject_id='E-S2' AND time_raw='1941'").fetchone()
    assert res["resolution"] == "kept_distinct_source"
    assert con.execute(
        "SELECT merged_into FROM research_assertions WHERE fact_id='F-U2-K2'"
    ).fetchone()[0] is None
    # 归并组进入 merged 处置
    assert con.execute(
        "SELECT count(*) FROM research_assertion_identity_collisions "
        "WHERE resolution='merged'").fetchone()[0] == 1

    # 无残余重复五元组 canonical（fixture 范围内）
    n = con.execute("""
        SELECT count(*) FROM (
          SELECT 1 FROM research_assertions WHERE merged_into IS NULL
          GROUP BY subject_id, predicate, object_id,
                   coalesce(time_start,'#'), coalesce(time_end,'#'),
                   coalesce(canonical_space_anchor_id,'#')
          HAVING count(*)>1)""").fetchone()[0]
    assert n == 0

    # provenance 多重性归并：canonical 身份的 n_provenance_members = 1 + 2 = 3
    v = con.execute("""
        SELECT n_provenance_members FROM v_assertion_state_identity
        WHERE canonical_fact_id='F-U2-A'""").fetchone()
    assert v["n_provenance_members"] == 3

    # 部分唯一索引存在
    assert con.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='index' "
        "AND name='ux_assertions_state_identity'").fetchone()[0] == 1
    con.close()


# ---------------------------------------------------------------------------
# U3
# ---------------------------------------------------------------------------
def test_u3_state_time_priority_trusted_over_asserted_over_stage(fixture_db):
    _run(fixture_db)
    con = _con(fixture_db)
    st1 = con.execute("SELECT * FROM research_culture_states WHERE state_id='ST1'").fetchone()
    assert st1["state_time_source"] == "member_events_trusted"
    assert st1["state_time_start"] == "1938-01-01" and st1["state_time_end"] == "1938-06-30"
    assert st1["fallback_to_stage"] == 0
    assert json.loads(st1["derived_from_events_json"]) == ["E-F1"]
    assert st1["state_time_precision"] == "year"   # E-F1 occurrence 事实精度 year

    st2 = con.execute("SELECT * FROM research_culture_states WHERE state_id='ST2'").fetchone()
    assert st2["state_time_source"] == "member_events_asserted"
    assert st2["state_time_start"] == "1938-02-01" and st2["state_time_end"] == "1938-03-31"
    assert st2["fallback_to_stage"] == 0
    assert st2["state_time_precision"] == "unknown"

    st3 = con.execute("SELECT * FROM research_culture_states WHERE state_id='ST3'").fetchone()
    assert st3["state_time_source"] == "stage_interval"
    assert st3["state_time_start"] == "1937-07-07" and st3["state_time_end"] == "1945-09-02"
    assert st3["fallback_to_stage"] == 1
    assert st3["state_time_precision"] == "stage_interval"
    assert json.loads(st3["derived_from_events_json"]) == []
    con.close()


# ---------------------------------------------------------------------------
# U4
# ---------------------------------------------------------------------------
def test_u4_frame_temporal_relations_and_candidate_limit(fixture_db):
    _run(fixture_db)
    con = _con(fixture_db)

    def rel(a, b):
        r = con.execute("SELECT relation, relation_basis, time_precision, confidence, "
                        "causality_status FROM event_frame_temporal "
                        "WHERE frame_a=? AND frame_b=?", (a, b)).fetchone()
        return r

    # 手算：E-F1(01-01~06-30) vs E-F2(06-01~12-31) → overlaps；双 trusted → 0.9；year>month → year
    r = rel("E-F1", "E-F2")
    assert r["relation"] == "overlaps"
    assert r["relation_basis"] == "frame_observed_interval_compare"
    assert r["time_precision"] == "year"
    assert abs(r["confidence"] - 0.9) < 1e-9
    assert r["causality_status"] == "not_inferred"

    # E-F1 vs E-F3(1936 全年) → after；混合 trusted/asserted → 0.7；period 最粗
    r = rel("E-F1", "E-F3")
    assert r["relation"] == "after"
    assert abs(r["confidence"] - 0.7) < 1e-9
    assert r["time_precision"] == "period"

    # E-F1 vs E-F4(02-01~03-31) → during（b 完全落在 a 内）
    r = rel("E-F1", "E-F4")
    assert r["relation"] == "during"
    assert abs(r["confidence"] - 0.7) < 1e-9

    # E-F3(1936) vs E-F4(1938) → before
    r = rel("E-F3", "E-F4")
    assert r["relation"] == "before"

    # 候选限制：E-F1 与 E-F6 无共享参与者 → 不入场（严禁笛卡尔积）
    assert con.execute(
        "SELECT count(*) FROM event_frame_temporal "
        "WHERE (frame_a='E-F1' AND frame_b='E-F6') OR (frame_a='E-F6' AND frame_b='E-F1')"
    ).fetchone()[0] == 0
    # 无时间帧不参与
    assert con.execute(
        "SELECT count(*) FROM event_frame_temporal "
        "WHERE frame_a='E-F5' OR frame_b='E-F5'").fetchone()[0] == 0
    con.close()


# ---------------------------------------------------------------------------
# U5
# ---------------------------------------------------------------------------
def test_u5_allen_relations_hand_computed(fixture_db):
    _run(fixture_db)
    con = _con(fixture_db)

    def rel(a, b):
        r = con.execute("SELECT relation_code, relation_basis, time_precision, "
                        "causality_status FROM assertion_temporal_relations "
                        "WHERE left_fact_id=? AND right_fact_id=?", (a, b)).fetchone()
        assert r is not None, f"missing pair {a}->{b}"
        return r

    expect = [
        ("F-U5-00", "F-U5-01", "after"),     # 09-01~09-30 vs 01-01~01-31
        ("F-U5-01", "F-U5-02", "before"),    # 01-31 < 02-01
        ("F-U5-02", "F-U5-03", "meets"),     # 03-01 == 03-01
        ("F-U5-03", "F-U5-04", "overlaps"),  # 部分重叠
        ("F-U5-04", "F-U5-05", "contains"),  # 04 包含 05
        ("F-U5-04", "F-U5-06", "equals"),
        ("F-U5-04", "F-U5-07", "starts"),
        ("F-U5-04", "F-U5-08", "ends"),
        ("F-U5-09", "F-U5-10", "during"),    # 09 落在 10 内
        ("F-U5-10", "F-U5-09", None),        # 方向固定：左=字典序小者，反向不入表
        ("F-U5-01", "F-U5-02", "before"),
    ]
    for a, b, code in expect:
        if code is None:
            assert con.execute(
                "SELECT count(*) FROM assertion_temporal_relations "
                "WHERE left_fact_id=? AND right_fact_id=?", (a, b)).fetchone()[0] == 0
        else:
            r = rel(a, b)
            assert r["relation_code"] == code, f"{a}->{b}: {r['relation_code']} != {code}"
            assert r["relation_basis"] == "assertion_interval_compare"
            assert r["causality_status"] == "not_inferred"

    # 精度 = 两断言中最粗已知精度：00=period(3), 01=month(1) → period；01=month, 02=year → year
    assert rel("F-U5-00", "F-U5-01")["time_precision"] == "period"
    assert rel("F-U5-01", "F-U5-02")["time_precision"] == "year"

    # merged 事实（F-U2-B）不参与；其 canonical（F-U2-A）正常参与
    n = con.execute("""
        SELECT count(*) FROM assertion_temporal_relations
        WHERE left_fact_id = 'F-U2-B' OR right_fact_id = 'F-U2-B'""").fetchone()[0]
    assert n == 0
    assert con.execute("""
        SELECT count(*) FROM assertion_temporal_relations r
        JOIN research_assertions a ON a.fact_id = r.left_fact_id
        JOIN research_assertions b ON b.fact_id = r.right_fact_id
        WHERE a.merged_into IS NOT NULL OR b.merged_into IS NOT NULL""").fetchone()[0] == 0

    # 同事件/同状态主体候选族存在表结构支撑（fixture 内同主体族已覆盖全部行）
    total = con.execute("SELECT count(*) FROM assertion_temporal_relations").fetchone()[0]
    assert total > 0
    con.close()


# ---------------------------------------------------------------------------
# U6
# ---------------------------------------------------------------------------
def test_u6_rewrite_only_when_rules_table_says_rewrite(fixture_db, tmp_path):
    # fixture 规则表把 unknown→event_occurrence 判为 REWRITE → 才允许回填
    rules = tmp_path / "rules_rewrite.json"
    rules.write_text(json.dumps({
        "rules": {"unknown→event_occurrence": {"action": "REWRITE",
                                               "reason": "fixture: significant"}},
        "unseen_type_default": "UNRESOLVED"}, ensure_ascii=False), encoding="utf-8")
    _run(fixture_db, extra=["--rules", str(rules)])
    con = _con(fixture_db)
    row = con.execute("""
        SELECT time_role, time_owner_id FROM research_assertions
        WHERE fact_id='F-U6-EV'""").fetchone()
    assert row["time_role"] == "event_occurrence"
    assert row["time_owner_id"] == "E-EV1"
    led = json.loads(con.execute(
        "SELECT measured_json FROM stkg_upgrade_log WHERE upgrade='U6'").fetchone()[0])
    assert led["rows_backfilled"] == 1
    assert json.loads(led["rewrite_classes_json"]) == ["unknown→event_occurrence"]
    assert led["global_heuristic_used"] is False
    # Person 主体的 unknown 事实不在该 REWRITE 类的处置范围内
    person_row = con.execute("""
        SELECT time_role, time_owner_id FROM research_assertions
        WHERE fact_id='F-U1-A1'""").fetchone()
    assert person_row["time_owner_id"] is None
    con.close()


def test_u6_production_rules_mean_zero_backfill(fixture_db):
    # 生产规则表（三票学习）：全部 RETAIN/UNRESOLVED ⇒ 0 行回填，覆盖率不变
    _run(fixture_db)   # 默认 --rules 指向仓库内 CLOSURE3_RULES.json（只读）
    con = _con(fixture_db)
    row = con.execute("""
        SELECT time_role, time_owner_id FROM research_assertions
        WHERE fact_id='F-U6-EV'""").fetchone()
    assert row["time_role"] == "unknown"
    assert row["time_owner_id"] is None
    led = json.loads(con.execute(
        "SELECT measured_json FROM stkg_upgrade_log WHERE upgrade='U6'").fetchone()[0])
    assert led["rows_backfilled"] == 0
    assert json.loads(led["rewrite_classes_json"]) == []
    assert led["before_time_owner_cov"] == led["after_time_owner_cov"]
    assert led["after_space_owner_cov"] == 0.0 or led["after_space_owner_cov"] >= 0.0
    assert led["unseen_type_default"] == "UNRESOLVED"
    con.close()


# ---------------------------------------------------------------------------
# U7
# ---------------------------------------------------------------------------
def test_u7_place_relations_type_constraint_chains_and_status(fixture_db):
    _run(fixture_db)
    con = _con(fixture_db)

    # 显式 strict located_in（双端 Place）→ auto_typed + evidence= fact_id
    r = con.execute("""
        SELECT relation, status, evidence_id FROM research_place_relations
        WHERE child_place_id='E-P2' AND parent_place_id='E-P1'""").fetchone()
    assert r is not None
    assert r["relation"] == "located_in"
    assert r["status"] == "auto_typed"
    assert r["evidence_id"] == "F-U7-S1"

    # 硬约束：组织不得当空间父节点（F-U7-BADPARENT 不入场）
    assert con.execute("""
        SELECT count(*) FROM research_place_relations
        WHERE parent_place_id='E-O1'""").fetchone()[0] == 0

    # 名为组织但上游误标 Place 的父节点（农救会）→ 降级 needs_review 复核位
    assert con.execute("""
        SELECT status FROM research_place_relations
        WHERE child_place_id='E-P1' AND parent_place_id='E-NGH'""").fetchone()[0] \
        == "needs_review"
    assert con.execute("""
        SELECT count(*) FROM research_place_relations r
        JOIN research_entities p ON p.entity_id=r.parent_place_id
        WHERE r.status='auto_typed'
          AND (p.canonical_name LIKE '%会' OR p.canonical_name LIKE '%局'
               OR p.canonical_name LIKE '%厂' OR p.canonical_name LIKE '%校')
    """).fetchone()[0] == 0

    # contextual → needs_review；unresolved → 不收编
    assert con.execute("""
        SELECT status FROM research_place_relations
        WHERE child_place_id='E-P1' AND parent_place_id='E-CTY'""").fetchone()[0] \
        == "needs_review"
    assert con.execute("""
        SELECT count(*) FROM research_place_relations
        WHERE evidence_id='F-U7-UNRES'""").fetchone()[0] == 0

    # province/city/county 字段链：市 located_in 省、县 located_in 市
    assert con.execute("""
        SELECT count(*) FROM research_place_relations
        WHERE child_place_id='E-CTY' AND parent_place_id='E-PRV'
          AND relation='located_in'""").fetchone()[0] == 1
    assert con.execute("""
        SELECT count(*) FROM research_place_relations
        WHERE child_place_id='E-CNTY' AND parent_place_id='E-CTY'""").fetchone()[0] == 1

    # 全表不变量：无非空间端点、无悬挂、无自环、无重复对
    assert con.execute("""
        SELECT count(*) FROM research_place_relations r
        JOIN research_entities c ON c.entity_id=r.child_place_id
        JOIN research_entities p ON p.entity_id=r.parent_place_id
        WHERE c.entity_type NOT IN ('Place','AdministrativeRegion','CulturalSite')
           OR p.entity_type NOT IN ('Place','AdministrativeRegion','CulturalSite')
    """).fetchone()[0] == 0
    assert con.execute("""
        SELECT count(*) FROM (
          SELECT 1 FROM research_place_relations
          GROUP BY child_place_id, parent_place_id, relation HAVING count(*)>1)
    """).fetchone()[0] == 0
    con.close()


# ---------------------------------------------------------------------------
# U8
# ---------------------------------------------------------------------------
def test_u8_place_versions_evidence_only(fixture_db):
    _run(fixture_db)
    con = _con(fixture_db)

    # 改称（带年份）：北平 <- 北京，valid_from=1928，auto_evidence
    v = con.execute("""
        SELECT historical_name, valid_from, valid_to, admin_level, status,
               derived_pattern, evidence_id
        FROM research_place_versions WHERE canonical_place_id='E-BP'""").fetchone()
    assert v is not None
    assert v["historical_name"] == "北京"
    assert v["valid_from"] == "1928" and v["valid_to"] is None
    assert v["status"] == "auto_evidence"
    assert v["derived_pattern"] == "renamed_to"
    assert v["evidence_id"] == "c0001"

    # 时属：临江镇 的时期版本挂父节点 庐陵县（名称未变，historical_name=本名）
    v2 = con.execute("""
        SELECT historical_name, parent_place_id, derived_pattern, status
        FROM research_place_versions WHERE canonical_place_id='E-LJZ'""").fetchone()
    assert v2 is not None
    assert v2["historical_name"] == "临江镇"
    assert v2["parent_place_id"] == "E-LLX"
    assert v2["derived_pattern"] == "same_period_parent"

    # 泛称（一区/二区）→ needs_review 降级
    v3 = con.execute("""
        SELECT status, historical_name FROM research_place_versions
        WHERE canonical_place_id='E-Q2'""").fetchone()
    assert v3 is not None
    assert v3["status"] == "needs_review"
    assert v3["historical_name"] == "一区"

    # 人名（李四原名张三）/组织（游击队改称独立团）不建版本；总数=3
    assert con.execute("SELECT count(*) FROM research_place_versions").fetchone()[0] == 3
    assert con.execute("""
        SELECT count(*) FROM research_place_versions v
        JOIN research_entities e ON e.entity_id=v.canonical_place_id
        WHERE e.entity_type NOT IN ('Place','AdministrativeRegion','CulturalSite')
    """).fetchone()[0] == 0
    assert con.execute("""
        SELECT count(*) FROM research_place_versions
        WHERE evidence_id IS NULL OR evidence_id=''""").fetchone()[0] == 0
    con.close()


# ---------------------------------------------------------------------------
# 幂等 + 完整性自检
# ---------------------------------------------------------------------------
def test_idempotent_rerun_and_integrity(fixture_db):
    _run(fixture_db)
    con = _con(fixture_db)
    snapshot = {
        "efp": con.execute("SELECT count(*) FROM event_frame_provenance").fetchone()[0],
        "merged": con.execute(
            "SELECT count(*) FROM research_assertions WHERE merged_into IS NOT NULL").fetchone()[0],
        "u4": con.execute("SELECT count(*) FROM event_frame_temporal").fetchone()[0],
        "u5": con.execute("SELECT count(*) FROM assertion_temporal_relations").fetchone()[0],
        "u6_roles": con.execute("""
            SELECT count(*) FROM research_assertions
            WHERE time_role='event_occurrence'""").fetchone()[0],
        "u7": con.execute("SELECT count(*) FROM research_place_relations").fetchone()[0],
        "u8": con.execute("SELECT count(*) FROM research_place_versions").fetchone()[0],
    }
    log1 = con.execute("SELECT upgrade, applied_at FROM stkg_upgrade_log "
                       "ORDER BY upgrade").fetchall()
    con.close()

    _run(fixture_db)  # 第二次：跳过已完成项
    con = _con(fixture_db)
    snapshot2 = {
        "efp": con.execute("SELECT count(*) FROM event_frame_provenance").fetchone()[0],
        "merged": con.execute(
            "SELECT count(*) FROM research_assertions WHERE merged_into IS NOT NULL").fetchone()[0],
        "u4": con.execute("SELECT count(*) FROM event_frame_temporal").fetchone()[0],
        "u5": con.execute("SELECT count(*) FROM assertion_temporal_relations").fetchone()[0],
        "u6_roles": con.execute("""
            SELECT count(*) FROM research_assertions
            WHERE time_role='event_occurrence'""").fetchone()[0],
        "u7": con.execute("SELECT count(*) FROM research_place_relations").fetchone()[0],
        "u8": con.execute("SELECT count(*) FROM research_place_versions").fetchone()[0],
    }
    assert snapshot == snapshot2
    log2 = con.execute("SELECT upgrade, applied_at FROM stkg_upgrade_log "
                       "ORDER BY upgrade").fetchall()
    assert [(r["upgrade"], r["applied_at"]) for r in log1] == \
           [(r["upgrade"], r["applied_at"]) for r in log2]   # 台账未变 = 全部跳过
    assert {r["upgrade"] for r in log2} >= \
           {"BASELINE", "U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8"}
    con.close()

    # 完整性自检
    con = _con(fixture_db)
    baseline = json.loads(con.execute(
        "SELECT measured_json FROM stkg_upgrade_log WHERE upgrade='BASELINE'"
    ).fetchone()[0])
    res = apply_stkg_upgrades.verify_integrity(con, baseline)
    con.close()
    assert res["quick_check"] == "ok"
    assert res["foreign_key_errors"] == 0
    assert res["counts_all_match_source"] is True          # 基表行数与升级前一致
    assert res["u2_residual_state_duplicate_canonical_groups"] == 0
    assert res["u2_merged_identity_mismatch"] == 0
    assert res["u2_merged_canonical_not_canonical"] == 0
    assert res["u2_pending_collision_groups"] == 0
    assert res["u2_view_zero_provenance_rows"] == 0
    assert res["u3_source_flag_consistency_violations"] == 0
    assert res["u3_states_without_time"] == 0
    assert res["u3_fallback_masked_as_precise"] == 0
    assert res["u4_missing_basis"] == 0
    assert res["u4_not_inferred_violations"] == 0
    assert res["u4_recompute_mismatch"] == 0
    assert res["u4_rows_without_shared_counterpart"] == 0
    assert res["u5_recompute_mismatch"] == 0
    assert res["u5_not_inferred_violations"] == 0
    assert res["u5_missing_basis"] == 0
    assert res["u5_self_pairs"] == 0
    assert res["u1_orphan_rows"] == 0
    assert res["u6_ledger_rows_backfilled"] == 0           # 生产规则表 ⇒ 0 回填
    assert json.loads(res["u6_ledger_rewrite_classes"]) == []
    assert res["u6_role_coverage_matches_ledger_after"] is True
    assert res["u7_non_spatial_endpoint_rows"] == 0        # 类型约束（含组织父节点拒绝）
    assert res["u7_dangling_rows"] == 0
    assert res["u7_self_loop_rows"] == 0
    assert res["u7_duplicate_pair_rows"] == 0
    assert res["u7_active_rows_on_cycle"] == 0
    assert res["u7_auto_typed_rows_with_org_parent_name"] == 0
    assert res["u8_non_spatial_place_rows"] == 0
    assert res["u8_non_spatial_parent_rows"] == 0
    assert res["u8_dangling_rows"] == 0
    assert res["u8_missing_evidence_rows"] == 0
    assert res["u8_duplicate_natural_key_rows"] == 0


# ---------------------------------------------------------------------------
# --only 单项重跑
# ---------------------------------------------------------------------------
def test_only_flag_reruns_single_upgrade(fixture_db):
    _run(fixture_db)
    con = _con(fixture_db)
    u8_before = con.execute(
        "SELECT count(*) FROM research_place_versions").fetchone()[0]
    applied_at = con.execute(
        "SELECT applied_at FROM stkg_upgrade_log WHERE upgrade='U8'").fetchone()[0]
    con.close()

    _run(fixture_db, extra=["--only", "U8"])   # 单项重跑（已应用 → 跳过并打印计数）
    con = _con(fixture_db)
    assert con.execute(
        "SELECT count(*) FROM research_place_versions").fetchone()[0] == u8_before
    assert con.execute(
        "SELECT applied_at FROM stkg_upgrade_log WHERE upgrade='U8'").fetchone()[0] \
        == applied_at                            # 台账时间戳未变 = 跳过而非重复应用
    con.close()
