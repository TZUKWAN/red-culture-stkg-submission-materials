# -*- coding: utf-8 -*-
"""apply_stkg_upgrades.py — 在 V2 发布库副本上实施 STKG 升级 U1-U8（12a 规格）。

只写副本，源库只读：
  源库   data/release_databases/red_culture_stkg_final_v2.sqlite        （只读，绝不修改）
  参考库 data/release_databases/red_culture_stkg_semantic_v2.sqlite     （ATTACH 只读参考）
  副本   submission_work/final_submission_v3_1/data/repaired_release/
         red_culture_stkg_final_v3_1.sqlite                             （V2 逐字节副本 + 升级）
  语料   data/source_data/master_data.csv                               （U8 只读扫描，记录 sha256）

升级项（对应 12a_STKG_UPGRADE_SPEC.md，SQL 按实际 schema 调整）：
  U1 event_frame_provenance           帧→断言→provenance 全链物化表
  U2 事实状态身份                     merged_into 标记 + 碰撞表 + 声明式唯一索引 + 身份视图
  U3 CultureState 时间区间            state_time_start/end/precision/source + 回填
  U4 event_frame_temporal             帧间时序（同主体候选限制，非因果）
  U5 assertion_temporal_relations     Allen 区间关系（同实体/同事件/同状态主体候选限制）
  U6 role-owner 选择性回填            只执行三票规则表（CLOSURE3_RULES.json）判 REWRITE 的类；
                                      禁止全局启发式——实际规则表全部 RETAIN/UNRESOLVED
                                      （unknown→event_occurrence p=0.108 不显著→UNRESOLVED），
                                      故 0 行回填，覆盖率如实报告不变
  U7 research_place_relations         最小空间层级（located_in/part_of/contains/within_basin）；
                                      child/parent 硬约束 = research_entities.entity_type ∈
                                      {Place,AdministrativeRegion,CulturalSite}，组织/人物/
                                      概念一律不得当空间父节点；来源=显式 strict/contextual
                                      located_in·part_of 断言 + province/city/county 字段链
                                      （city located_in province、county located_in city）；
                                      basin 段非实体→within_basin 0 行（如实报告，
                                      省→流域段仍由冻结表 research_region_hierarchy 承载）
  U8 research_place_versions          只对语料证据句（原名X/改称Y/时属Z 模式）可自动支持的
                                      历史地名建版本；无证据不创建；current 侧名必须唯一归属
                                      空间类型，另一侧名须为实体名或带政区/地名后缀；
                                      泛称（一区/专区等）、归属标记（划归/并入…）、
                                      枚举语境（顿号/右括号前）→ needs_review 降级

确定性规则（全部机械推导，无人工、无随机）：
  U2 合并键   = (subject_id, predicate, object_id, coalesce(time_start,'#'),
                 coalesce(time_end,'#'), coalesce(canonical_space_anchor_id,'#'))
               —— 即视图 v_assertion_state_identity 的 (s,p,o,τ,λ) 身份；
               canonical = 组内字典序最小 fact_id；其余打 merged_into，物理保留不删；
               文本五元组 (s,p,o,time_raw,place_raw) 相同但归一化 (τ,λ) 不同的组
               记 kept_distinct_source（归一化分歧，待 U9，不合并）。
  U3 优先级   = trusted 成员事件 > asserted 成员事件 > stage 区间（fallback 显式置 1，
               绝不把 stage 回退伪装成精确时间）。
  U4 候选     = 共享参与者（research_event_roles.counterpart_id）的带观测时间帧对
               （12a 建议的同主体候选限制，严禁 424k 笛卡尔积）；
               relation 由区间比较得出，confidence 由两帧 observed_time_status 决定
               （trusted/trusted=0.9, 混合=0.7, asserted/asserted=0.5），
               causality_status 硬约束 = 'not_inferred'。
  U5 候选     = 同 subject_id 实体 ∪ 同事件（research_event_assertion_links）∪
               同 CultureState 主体（research_culture_states.culture_subject_id）；
               仅对 canonical（merged_into IS NULL）断言建边；Allen 9 分支 CASE。
  U6 规则     = 唯一裁判为 CLOSURE3_RULES.json 的 type→action；只对 action='REWRITE'
               的类执行确定性 UPDATE（canonical 事实 only），其余 RETAIN/UNRESOLVED
               一律不动；候选计数照测、回填为 0 是 MEASURED 结论而非缺省。
  U7 类型约束 = 双端 entity_type ∈ 空间类型集合；名称解析要求唯一空间归属
               （同名含非空间类型→type_ambiguous 弃用）；显式断言优先于字段链；
               环上边 → rejected。
  U8 证据约束 = 每行必含语料证据 id（master_data.id，sha256 入台账）；
               current 侧名唯一空间归属 + 另一侧实体名或政区后缀 + 泛称降级 needs_review；
               年份取证据句窗口内首个 19xx/20xx 年，无则 NULL，绝不伪填。

幂等性：stkg_upgrade_log 台账记录已完成项；重复运行跳过（DDL 亦全部 IF NOT EXISTS）。
每个升级项一个事务；每步打印 MEASURED 计数；--verify-only 跑全量完整性自检。

用法：
  python apply_stkg_upgrades.py                 # 复制源库（如副本缺失）+ U1-U8 + 自检
  python apply_stkg_upgrades.py --only U7       # 只跑 U7（其余跳过；已应用则打印计数）
  python apply_stkg_upgrades.py --only U8 --force U8   # 强制重跑单项（仅建议在测试库上）
  python apply_stkg_upgrades.py --verify-only   # 只跑完整性自检
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径（与本仓库其它管线一致；源库/参考库一律 mode=ro）
# ---------------------------------------------------------------------------
V3_1 = Path(__file__).resolve().parents[2]                      # .../final_submission_v3_1
REPO_ROOT = V3_1.parents[1]                                     # 仓库根

SOURCE_DB = REPO_ROOT / "data" / "release_databases" / "red_culture_stkg_final_v2.sqlite"
SEMANTIC_DB = REPO_ROOT / "data" / "release_databases" / "red_culture_stkg_semantic_v2.sqlite"
TARGET_DB = V3_1 / "data" / "repaired_release" / "red_culture_stkg_final_v3_1.sqlite"

# U6 选择性规则（三票学习产物，只读）；U8 语料（只读扫描）
CLOSURE3_RULES_PATH = V3_1 / "experiments" / "05_scope_repair" / "v2_" / "CLOSURE3_RULES.json"
MASTER_DATA_CSV = REPO_ROOT / "data" / "source_data" / "master_data.csv"

# U7/U8 空间对象类型白名单（research_entities.entity_type）
SPATIAL_TYPES = ("Place", "AdministrativeRegion", "CulturalSite")

# 关系契约判定所需的两份只读参考定义（external_inputs，与 293_audit_stkg_v2_full.py 同源）
EXTERNAL_INPUTS = V3_1.parent / "final_submission_v3" / "data" / "external_inputs"

_CN_TZ = timezone(timedelta(hours=8))
RUN_STAMP = datetime.now(_CN_TZ).isoformat(timespec="seconds")

UPGRADES = ("U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8")


def ro_uri(path: Path) -> str:
    return "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()


def measured(label: str, value) -> None:
    print(f"MEASURED {label} = {value}")


def now_iso() -> str:
    return datetime.now(_CN_TZ).isoformat(timespec="seconds")


def q1(con: sqlite3.Connection, sql: str, args: tuple = ()):
    return con.execute(sql, args).fetchone()[0]


# ---------------------------------------------------------------------------
# 副本准备
# ---------------------------------------------------------------------------
def ensure_copy(source: Path, target: Path, rebuild: bool = False) -> dict:
    """把源库逐字节复制为副本（源库只读）。副本已存在且未 --rebuild 则复用。"""
    info = {"source": str(source), "target": str(target),
            "source_sha256": sha256_file(source)}
    if target.exists() and not rebuild:
        info["copied"] = False
        info["target_sha256_matches_source"] = sha256_file(target) == info["source_sha256"]
        print(f"[copy] target exists, reused (matches_source={info['target_sha256_matches_source']})")
        return info
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"[copy] {source} -> {target}")
    shutil.copy2(source, target)
    got = sha256_file(target)
    if got != info["source_sha256"]:
        raise RuntimeError("copy hash mismatch — aborting to protect source integrity")
    info["copied"] = True
    info["target_sha256"] = got
    print(f"[copy] done, sha256 verified: {got[:16]}…")
    return info


def connect(target: Path, semantic_db: Path | None) -> sqlite3.Connection:
    # 主连接以 URI 打开（mode=rw），ATTACH 的 file:...?mode=ro 才会被解析为 URI
    con = sqlite3.connect("file:" + str(target.resolve()).replace("\\", "/") + "?mode=rw",
                          uri=True)
    con.execute("PRAGMA foreign_keys=ON")
    con.row_factory = sqlite3.Row
    if semantic_db is not None and semantic_db.exists():
        con.execute(f"ATTACH DATABASE '{ro_uri(semantic_db)}' AS sem")  # 只读参考（mode=ro）
    return con


# ---------------------------------------------------------------------------
# 台账（幂等）
# ---------------------------------------------------------------------------
def ensure_ledger(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS stkg_upgrade_log (
            upgrade       TEXT PRIMARY KEY,
            applied_at    TEXT NOT NULL,
            measured_json TEXT NOT NULL CHECK(json_valid(measured_json))
        )""")


def applied(con: sqlite3.Connection, upgrade: str) -> dict | None:
    row = con.execute(
        "SELECT applied_at, measured_json FROM stkg_upgrade_log WHERE upgrade=?",
        (upgrade,)).fetchone()
    if row is None:
        return None
    return {"applied_at": row["applied_at"], "measured": json.loads(row["measured_json"])}


def record(con: sqlite3.Connection, upgrade: str, measured_dict: dict) -> None:
    con.execute(
        "INSERT INTO stkg_upgrade_log(upgrade, applied_at, measured_json) VALUES (?,?,?) "
        "ON CONFLICT(upgrade) DO UPDATE SET applied_at=excluded.applied_at, "
        "measured_json=excluded.measured_json",
        (upgrade, now_iso(), json.dumps(measured_dict, ensure_ascii=False, sort_keys=True)))


def column_exists(con: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in con.execute(f"PRAGMA table_info({table})"))


# ---------------------------------------------------------------------------
# U1 — event_frame_provenance（帧级证据链物化表）
# ---------------------------------------------------------------------------
def upgrade_u1(con: sqlite3.Connection) -> dict:
    # 帧成员关系（research_event_assertion_links，由 sem 事件帧成员关系物化而来）
    # × fact 级 provenance（research_assertion_provenance）→ 全链物化为新表。
    con.executescript("""
        CREATE TABLE IF NOT EXISTS event_frame_provenance (
            frame_id         TEXT NOT NULL REFERENCES research_event_frames(event_id),
            assertion_id     TEXT NOT NULL REFERENCES research_assertions(fact_id),
            provenance_id    TEXT NOT NULL REFERENCES research_assertion_provenance(provenance_id),
            provenance_kind  TEXT NOT NULL,
            evidence_ids_json TEXT NOT NULL,
            PRIMARY KEY (frame_id, assertion_id, provenance_id)
        ) WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS ix_efp_frame
            ON event_frame_provenance(frame_id);
        CREATE INDEX IF NOT EXISTS ix_efp_assertion
            ON event_frame_provenance(assertion_id);

        INSERT OR IGNORE INTO event_frame_provenance
            (frame_id, assertion_id, provenance_id, provenance_kind, evidence_ids_json)
        SELECT DISTINCT l.event_id, l.fact_id, p.provenance_id,
               p.provenance_kind, p.evidence_ids_json
        FROM research_event_assertion_links l
        JOIN research_assertion_provenance p ON p.fact_id = l.fact_id;
    """)

    m = {}
    m["rows_inserted_total"] = q1(con, "SELECT count(*) FROM event_frame_provenance")
    m["frames_total"] = q1(con, "SELECT count(*) FROM research_event_frames")
    m["frames_with_provenance"] = q1(con, """
        SELECT count(DISTINCT frame_id) FROM event_frame_provenance""")
    m["frames_with_locatable_evidence"] = q1(con, """
        SELECT count(DISTINCT frame_id) FROM event_frame_provenance
        WHERE json_array_length(evidence_ids_json) > 0""")
    m["frames_without_provenance"] = m["frames_total"] - m["frames_with_provenance"]
    m["coverage_with_provenance"] = round(
        m["frames_with_provenance"] / m["frames_total"], 6) if m["frames_total"] else 0.0
    m["coverage_locatable_evidence"] = round(
        m["frames_with_locatable_evidence"] / m["frames_total"], 6) if m["frames_total"] else 0.0
    m["distinct_assertions_covered"] = q1(con, """
        SELECT count(DISTINCT assertion_id) FROM event_frame_provenance""")
    m["evidence_rows_total"] = q1(con, """
        SELECT count(*) FROM event_frame_provenance, json_each(event_frame_provenance.evidence_ids_json)""")
    # sem 交叉参考：帧 id 在 sem Event 实体中的命中（只读参考，不写 sem）
    try:
        m["frames_matched_in_sem_event_entities"] = q1(con, """
            SELECT count(*) FROM research_event_frames f
            JOIN sem.v2_entities e ON e.entity_id = f.event_id""")
    except sqlite3.Error:
        m["frames_matched_in_sem_event_entities"] = None  # sem 未附加时跳过
    return m


# ---------------------------------------------------------------------------
# U2 — 事实状态身份：merged_into 标记 + 碰撞表 + 声明式唯一索引 + 身份视图
# ---------------------------------------------------------------------------
def upgrade_u2(con: sqlite3.Connection) -> dict:
    # 1) schema：merged_into 标记列（物理保留，不删行）
    if not column_exists(con, "research_assertions", "merged_into"):
        con.execute("ALTER TABLE research_assertions ADD COLUMN merged_into TEXT "
                    "REFERENCES research_assertions(fact_id)")
    if not column_exists(con, "research_assertions", "merge_rule"):
        con.execute("ALTER TABLE research_assertions ADD COLUMN merge_rule TEXT")

    con.executescript("""
        CREATE TABLE IF NOT EXISTS research_assertion_identity_collisions (
            collision_group_id TEXT PRIMARY KEY,          -- sha256(s+p+o+time_raw+place_raw)
            subject_id  TEXT NOT NULL, predicate TEXT NOT NULL, object_id TEXT NOT NULL,
            time_raw TEXT, place_raw TEXT,
            member_fact_ids_json TEXT NOT NULL CHECK(json_valid(member_fact_ids_json)),
            member_count INTEGER NOT NULL,
            state_keys_distinct INTEGER NOT NULL,         -- 组内归一化 (τ,λ) 状态键个数
            resolution TEXT NOT NULL DEFAULT 'pending'
                CHECK(resolution IN ('pending','merged','kept_distinct_source')),
            resolved_at TEXT
        );

        CREATE VIEW IF NOT EXISTS v_assertion_state_identity AS
        SELECT
            s.subject_id, s.predicate, s.object_id,
            s.time_interval_key, s.space_anchor_key,
            s.canonical_fact_id, s.member_fact_count,
            (SELECT count(*) FROM research_assertion_provenance p
             JOIN research_assertions m ON m.fact_id = p.fact_id
             WHERE m.fact_id = s.canonical_fact_id OR m.merged_into = s.canonical_fact_id
            ) AS n_provenance_members
        FROM (
            SELECT subject_id, predicate, object_id,
                   coalesce(time_start,'#') || '/' || coalesce(time_end,'#') AS time_interval_key,
                   coalesce(canonical_space_anchor_id,'~')                   AS space_anchor_key,
                   min(fact_id)  AS canonical_fact_id,
                   count(*)      AS member_fact_count
            FROM research_assertions
            GROUP BY 1,2,3,4,5
        ) s;
    """)

    # 2) 文本五元组碰撞组（(s,p,o,time_raw,place_raw) 完全相同）——审计口径 655 组
    con.execute("CREATE TEMP TABLE IF NOT EXISTS _u2_raw_groups "
                "(subject_id TEXT, predicate TEXT, object_id TEXT, time_raw TEXT, place_raw TEXT)")
    con.execute("DELETE FROM _u2_raw_groups")
    con.execute("""
        INSERT INTO _u2_raw_groups
        SELECT subject_id, predicate, object_id, ifnull(time_raw,'~'), ifnull(place_raw,'~')
        FROM research_assertions
        GROUP BY 1,2,3,4,5 HAVING count(*)>1""")

    con.create_function("u_sha256", 1,
                        lambda b: hashlib.sha256(b.encode("utf-8")).hexdigest(),
                        deterministic=True)
    con.execute("""
        INSERT OR IGNORE INTO research_assertion_identity_collisions
            (collision_group_id, subject_id, predicate, object_id, time_raw, place_raw,
             member_fact_ids_json, member_count, state_keys_distinct, resolution, resolved_at)
        SELECT 'COLL-' || substr(u_sha256(
                   g.subject_id||'|'||g.predicate||'|'||g.object_id||'|'||g.time_raw||'|'||g.place_raw), 1, 32),
               g.subject_id, g.predicate, g.object_id,
               NULLIF(g.time_raw,'~'), NULLIF(g.place_raw,'~'),
               (SELECT json_group_array(fact_id) FROM (
                   SELECT fact_id FROM research_assertions a
                   WHERE a.subject_id=g.subject_id AND a.predicate=g.predicate
                     AND a.object_id=g.object_id
                     AND ifnull(a.time_raw,'~')=g.time_raw AND ifnull(a.place_raw,'~')=g.place_raw
                   ORDER BY fact_id)),
               (SELECT count(*) FROM research_assertions a
                WHERE a.subject_id=g.subject_id AND a.predicate=g.predicate
                  AND a.object_id=g.object_id
                  AND ifnull(a.time_raw,'~')=g.time_raw AND ifnull(a.place_raw,'~')=g.place_raw),
               (SELECT count(DISTINCT coalesce(time_start,'#')||'/'||coalesce(time_end,'#')||'/'
                              ||coalesce(canonical_space_anchor_id,'#'))
                FROM research_assertions a
                WHERE a.subject_id=g.subject_id AND a.predicate=g.predicate
                  AND a.object_id=g.object_id
                  AND ifnull(a.time_raw,'~')=g.time_raw AND ifnull(a.place_raw,'~')=g.place_raw),
               'pending', ?
        FROM _u2_raw_groups g
    """, (now_iso(),))

    # 3) 状态身份合并：同 (s,p,o,τ,λ) 组内 canonical=min(fact_id)，其余 merged_into
    con.execute("DROP TABLE IF EXISTS temp._u2_state_groups")
    con.execute("""
        CREATE TEMP TABLE _u2_state_groups AS
        SELECT subject_id, predicate, object_id,
               coalesce(time_start,'#')              AS tks,
               coalesce(time_end,'#')                AS tke,
               coalesce(canonical_space_anchor_id,'#') AS anch,
               min(fact_id) AS canonical_fact_id, count(*) AS n_members
        FROM research_assertions
        GROUP BY 1,2,3,4,5,6 HAVING count(*)>1""")
    con.execute("CREATE UNIQUE INDEX temp._u2sg_pk "
                "ON _u2_state_groups(subject_id,predicate,object_id,tks,tke,anch)")

    con.execute("""
        UPDATE research_assertions
        SET merged_into = (SELECT g.canonical_fact_id FROM temp._u2_state_groups g
                           WHERE g.subject_id = research_assertions.subject_id
                             AND g.predicate  = research_assertions.predicate
                             AND g.object_id  = research_assertions.object_id
                             AND g.tks = coalesce(research_assertions.time_start,'#')
                             AND g.tke = coalesce(research_assertions.time_end,'#')
                             AND g.anch = coalesce(research_assertions.canonical_space_anchor_id,'#')),
            merge_rule = 'state_identity_exact_v1'
        WHERE merged_into IS NULL
          AND EXISTS (SELECT 1 FROM temp._u2_state_groups g
                      WHERE g.subject_id = research_assertions.subject_id
                        AND g.predicate  = research_assertions.predicate
                        AND g.object_id  = research_assertions.object_id
                        AND g.tks = coalesce(research_assertions.time_start,'#')
                        AND g.tke = coalesce(research_assertions.time_end,'#')
                        AND g.anch = coalesce(research_assertions.canonical_space_anchor_id,'#'))
          AND fact_id <> (SELECT g.canonical_fact_id FROM temp._u2_state_groups g
                          WHERE g.subject_id = research_assertions.subject_id
                            AND g.predicate  = research_assertions.predicate
                            AND g.object_id  = research_assertions.object_id
                            AND g.tks = coalesce(research_assertions.time_start,'#')
                            AND g.tke = coalesce(research_assertions.time_end,'#')
                            AND g.anch = coalesce(research_assertions.canonical_space_anchor_id,'#'))
    """)

    # 4) 碰撞表处置结论回填：组内成员共享同一状态键 → merged；键分歧 → kept_distinct_source
    con.execute("""
        UPDATE research_assertion_identity_collisions SET resolution = 'merged', resolved_at = ?
        WHERE resolution='pending' AND state_keys_distinct = 1""", (now_iso(),))
    con.execute("""
        UPDATE research_assertion_identity_collisions SET resolution = 'kept_distinct_source',
               resolved_at = ?
        WHERE resolution='pending' AND state_keys_distinct > 1""", (now_iso(),))

    # 5) 声明式身份约束：对未合并行建立部分唯一索引；合并链查找索引
    con.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_assertions_state_identity
            ON research_assertions(subject_id, predicate, object_id,
                coalesce(time_start,'#'), coalesce(time_end,'#'),
                coalesce(canonical_space_anchor_id,'#'))
            WHERE merged_into IS NULL;

        CREATE INDEX IF NOT EXISTS ix_assertions_merged_into
            ON research_assertions(merged_into)
            WHERE merged_into IS NOT NULL;
    """)

    m = {}
    m["raw_quintet_collision_groups"] = q1(con,
        "SELECT count(*) FROM research_assertion_identity_collisions")
    m["raw_quintet_groups_merged"] = q1(con,
        "SELECT count(*) FROM research_assertion_identity_collisions WHERE resolution='merged'")
    m["raw_quintet_groups_kept_distinct"] = q1(con,
        "SELECT count(*) FROM research_assertion_identity_collisions WHERE resolution='kept_distinct_source'")
    m["state_identity_groups"] = q1(con, "SELECT count(*) FROM temp._u2_state_groups")
    m["state_identity_facts_in_groups"] = q1(con, "SELECT sum(n_members) FROM temp._u2_state_groups")
    m["facts_merged_total"] = q1(con,
        "SELECT count(*) FROM research_assertions WHERE merged_into IS NOT NULL")
    m["facts_merged_this_rule"] = q1(con,
        "SELECT count(*) FROM research_assertions WHERE merge_rule='state_identity_exact_v1'")
    m["canonical_fact_count"] = q1(con,
        "SELECT count(*) FROM research_assertions WHERE merged_into IS NULL")
    m["assertions_total_unchanged"] = q1(con, "SELECT count(*) FROM research_assertions")
    m["unique_index_created"] = q1(con, """
        SELECT count(*) FROM sqlite_master
        WHERE type='index' AND name='ux_assertions_state_identity'""")
    m["identity_view_groups"] = q1(con,
        "SELECT count(*) FROM v_assertion_state_identity")
    m["max_provenance_members_per_identity"] = q1(con,
        "SELECT max(n_provenance_members) FROM v_assertion_state_identity")
    m["merged_self_reference_violations"] = q1(con, """
        SELECT count(*) FROM research_assertions a
        WHERE a.merged_into = a.fact_id
           OR (a.merged_into IS NOT NULL AND NOT EXISTS
               (SELECT 1 FROM research_assertions c WHERE c.fact_id = a.merged_into
                  AND c.merged_into IS NULL))""")
    return m


# ---------------------------------------------------------------------------
# U3 — CultureState 时间区间（trusted > asserted > stage，回退显式标注）
# ---------------------------------------------------------------------------
def upgrade_u3(con: sqlite3.Connection) -> dict:
    for col, decl in (
        ("state_time_start", "TEXT"),
        ("state_time_end", "TEXT"),
        ("state_time_precision", "TEXT"),
        ("state_time_source", "TEXT CHECK(state_time_source IN "
                              "('member_events_trusted','member_events_asserted','stage_interval'))"),
        ("derived_from_events_json", "TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(derived_from_events_json))"),
        ("fallback_to_stage", "INTEGER NOT NULL DEFAULT 0 CHECK(fallback_to_stage IN (0,1))"),
    ):
        if not column_exists(con, "research_culture_states", col):
            con.execute(f"ALTER TABLE research_culture_states ADD COLUMN {col} {decl}")

    # P1：trusted 成员事件
    con.execute("""
        UPDATE research_culture_states SET
            state_time_start = (SELECT min(f.observed_time_start)
                                FROM research_culture_state_events se
                                JOIN research_event_frames f ON f.event_id = se.event_id
                                WHERE se.state_id = research_culture_states.state_id
                                  AND f.observed_time_status = 'trusted'
                                  AND f.observed_time_start IS NOT NULL),
            state_time_end   = (SELECT max(f.observed_time_end)
                                FROM research_culture_state_events se
                                JOIN research_event_frames f ON f.event_id = se.event_id
                                WHERE se.state_id = research_culture_states.state_id
                                  AND f.observed_time_status = 'trusted'
                                  AND f.observed_time_end IS NOT NULL),
            state_time_precision = (
                SELECT ep.precision FROM (
                    SELECT max(prec.rank_order) AS rk,
                           CASE max(prec.rank_order)
                               WHEN 1 THEN 'month' WHEN 2 THEN 'year'
                               WHEN 3 THEN 'period' ELSE 'unknown' END AS precision
                    FROM research_culture_state_events se
                    JOIN research_event_frames f ON f.event_id = se.event_id
                      AND f.observed_time_status = 'trusted'
                    JOIN research_event_assertion_links l
                      ON l.event_id = se.event_id AND l.time_role = 'event_occurrence'
                    JOIN research_assertions a ON a.fact_id = l.fact_id
                    CROSS JOIN (SELECT 0 AS rank_order UNION SELECT 1 UNION SELECT 2 UNION SELECT 3) prec
                    WHERE se.state_id = research_culture_states.state_id
                      AND prec.rank_order = CASE a.time_precision
                            WHEN 'month' THEN 1 WHEN 'year' THEN 2 WHEN 'period' THEN 3 ELSE 0 END
                ) ep),
            state_time_source = 'member_events_trusted',
            derived_from_events_json = (
                SELECT json_group_array(j.event_id) FROM (
                    SELECT se.event_id FROM research_culture_state_events se
                    JOIN research_event_frames f ON f.event_id = se.event_id
                    WHERE se.state_id = research_culture_states.state_id
                      AND f.observed_time_status = 'trusted'
                    ORDER BY se.event_id) j),
            fallback_to_stage = 0
        WHERE EXISTS (SELECT 1 FROM research_culture_state_events se
                      JOIN research_event_frames f ON f.event_id = se.event_id
                      WHERE se.state_id = research_culture_states.state_id
                        AND f.observed_time_status = 'trusted')
    """)

    # P2：无 trusted → asserted 成员事件
    con.execute("""
        UPDATE research_culture_states SET
            state_time_start = (SELECT min(f.observed_time_start)
                                FROM research_culture_state_events se
                                JOIN research_event_frames f ON f.event_id = se.event_id
                                WHERE se.state_id = research_culture_states.state_id
                                  AND f.observed_time_status = 'asserted_candidate'
                                  AND f.observed_time_start IS NOT NULL),
            state_time_end   = (SELECT max(f.observed_time_end)
                                FROM research_culture_state_events se
                                JOIN research_event_frames f ON f.event_id = se.event_id
                                WHERE se.state_id = research_culture_states.state_id
                                  AND f.observed_time_status = 'asserted_candidate'
                                  AND f.observed_time_end IS NOT NULL),
            state_time_precision = (
                SELECT CASE max(prec.rank_order)
                           WHEN 1 THEN 'month' WHEN 2 THEN 'year'
                           WHEN 3 THEN 'period' ELSE 'unknown' END
                FROM research_culture_state_events se
                JOIN research_event_frames f ON f.event_id = se.event_id
                  AND f.observed_time_status = 'asserted_candidate'
                JOIN research_event_assertion_links l
                  ON l.event_id = se.event_id AND l.time_role = 'event_occurrence'
                JOIN research_assertions a ON a.fact_id = l.fact_id
                CROSS JOIN (SELECT 0 AS rank_order UNION SELECT 1 UNION SELECT 2 UNION SELECT 3) prec
                WHERE se.state_id = research_culture_states.state_id
                  AND prec.rank_order = CASE a.time_precision
                        WHEN 'month' THEN 1 WHEN 'year' THEN 2 WHEN 'period' THEN 3 ELSE 0 END),
            state_time_source = 'member_events_asserted',
            derived_from_events_json = (
                SELECT json_group_array(j.event_id) FROM (
                    SELECT se.event_id FROM research_culture_state_events se
                    JOIN research_event_frames f ON f.event_id = se.event_id
                    WHERE se.state_id = research_culture_states.state_id
                      AND f.observed_time_status = 'asserted_candidate'
                    ORDER BY se.event_id) j),
            fallback_to_stage = 0
        WHERE state_time_source IS NULL
          AND EXISTS (SELECT 1 FROM research_culture_state_events se
                      JOIN research_event_frames f ON f.event_id = se.event_id
                      WHERE se.state_id = research_culture_states.state_id
                        AND f.observed_time_status = 'asserted_candidate')
    """)

    # P3：回退到历史阶段区间（显式 fallback_to_stage=1，不伪装成精确时间）
    con.execute("""
        UPDATE research_culture_states SET
            state_time_start = stg.time_start,
            state_time_end   = stg.time_end,
            state_time_precision = 'stage_interval',
            state_time_source = 'stage_interval',
            derived_from_events_json = '[]',
            fallback_to_stage = 1
        FROM research_historical_stages stg
        WHERE research_culture_states.stage_code = stg.stage_code
          AND research_culture_states.state_time_source IS NULL
    """)

    m = {}
    m["states_total"] = q1(con, "SELECT count(*) FROM research_culture_states")
    m["states_with_state_time"] = q1(con,
        "SELECT count(*) FROM research_culture_states WHERE state_time_start IS NOT NULL")
    for src in ("member_events_trusted", "member_events_asserted", "stage_interval"):
        m[f"states_source_{src}"] = q1(con,
            "SELECT count(*) FROM research_culture_states WHERE state_time_source=?", (src,))
    m["states_fallback_to_stage"] = q1(con,
        "SELECT count(*) FROM research_culture_states WHERE fallback_to_stage=1")
    m["precision_distribution_json"] = json.dumps({
        r[0]: r[1] for r in con.execute(
            "SELECT state_time_precision, count(*) FROM research_culture_states "
            "GROUP BY 1 ORDER BY 2 DESC")}, ensure_ascii=False)
    m["source_flag_consistency_violations"] = q1(con, """
        SELECT count(*) FROM research_culture_states
        WHERE (fallback_to_stage=1 AND state_time_source<>'stage_interval')
           OR (fallback_to_stage=0 AND state_time_source='stage_interval')
           OR (fallback_to_stage=1 AND (derived_from_events_json<>'[]'))""")
    return m


# ---------------------------------------------------------------------------
# U4 — event_frame_temporal（帧间时序，同主体候选限制，非因果）
# ---------------------------------------------------------------------------
def upgrade_u4(con: sqlite3.Connection) -> dict:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS event_frame_temporal (
            frame_a          TEXT NOT NULL REFERENCES research_event_frames(event_id),
            frame_b          TEXT NOT NULL REFERENCES research_event_frames(event_id),
            relation         TEXT NOT NULL CHECK(relation IN ('before','after','overlaps','during')),
            relation_basis   TEXT NOT NULL CHECK(relation_basis IN ('frame_observed_interval_compare')),
            time_precision   TEXT NOT NULL,
            confidence       REAL NOT NULL,
            causality_status TEXT NOT NULL DEFAULT 'not_inferred'
                             CHECK(causality_status = 'not_inferred'),
            PRIMARY KEY (frame_a, frame_b)
        ) WITHOUT ROWID;
    """)

    # 帧级时间精度：该帧 occurrence 事实的最粗已知精度（rank: month=1 < year=2 < period=3）
    con.execute("DROP TABLE IF EXISTS temp._u4_frame_precision")
    con.execute("""
        CREATE TEMP TABLE _u4_frame_precision AS
        SELECT f.event_id,
               max(CASE a.time_precision WHEN 'month' THEN 1 WHEN 'year' THEN 2
                   WHEN 'period' THEN 3 ELSE 0 END) AS rank_v,
               max(CASE f.observed_time_status WHEN 'trusted' THEN 1 ELSE 0 END) AS any_trusted,
               min(CASE f.observed_time_status WHEN 'trusted' THEN 1 ELSE 0 END) AS all_trusted
        FROM research_event_frames f
        LEFT JOIN research_event_assertion_links l
               ON l.event_id = f.event_id AND l.time_role = 'event_occurrence'
        LEFT JOIN research_assertions a ON a.fact_id = l.fact_id
        GROUP BY f.event_id""")

    cur = con.execute("""
        INSERT OR IGNORE INTO event_frame_temporal
            (frame_a, frame_b, relation, relation_basis, time_precision, confidence)
        SELECT a.event_id, b.event_id,
               CASE
                   WHEN a.observed_time_end < b.observed_time_start THEN 'before'
                   WHEN a.observed_time_start > b.observed_time_end THEN 'after'
                   WHEN a.observed_time_start >= b.observed_time_start
                        AND a.observed_time_end <= b.observed_time_end THEN 'during'
                   WHEN b.observed_time_start >= a.observed_time_start
                        AND b.observed_time_end <= a.observed_time_end THEN 'during'
                   ELSE 'overlaps'
               END,
               'frame_observed_interval_compare',
               CASE max(pa.rank_v, pb.rank_v)
                   WHEN 1 THEN 'month' WHEN 2 THEN 'year' WHEN 3 THEN 'period'
                   ELSE 'unknown' END,
               CASE WHEN pa.all_trusted=1 AND pb.all_trusted=1 THEN 0.9
                    WHEN pa.any_trusted=1 OR  pb.any_trusted=1 THEN 0.7
                    ELSE 0.5 END
        FROM research_event_frames a
        JOIN research_event_frames b
          ON a.event_id < b.event_id
         AND a.observed_time_start IS NOT NULL AND a.observed_time_end IS NOT NULL
         AND b.observed_time_start IS NOT NULL AND b.observed_time_end IS NOT NULL
        JOIN temp._u4_frame_precision pa ON pa.event_id = a.event_id
        JOIN temp._u4_frame_precision pb ON pb.event_id = b.event_id
        WHERE EXISTS (                                  -- 同主体候选限制：共享参与者
              SELECT 1 FROM research_event_roles ra
              JOIN research_event_roles rb ON rb.counterpart_id = ra.counterpart_id
              WHERE ra.event_id = a.event_id AND rb.event_id = b.event_id)
    """)
    inserted = cur.rowcount

    m = {}
    m["rows_total"] = q1(con, "SELECT count(*) FROM event_frame_temporal")
    m["rows_seen_in_this_run"] = inserted
    m["candidate_pairs_shared_counterpart"] = q1(con, """
        SELECT count(*) FROM (
            SELECT DISTINCT ra.event_id, rb.event_id
            FROM research_event_roles ra
            JOIN research_event_roles rb ON rb.counterpart_id = ra.counterpart_id
            JOIN research_event_frames fa ON fa.event_id = ra.event_id
               AND fa.observed_time_start IS NOT NULL AND fa.observed_time_end IS NOT NULL
            JOIN research_event_frames fb ON fb.event_id = rb.event_id
               AND fb.observed_time_start IS NOT NULL AND fb.observed_time_end IS NOT NULL
            WHERE ra.event_id < rb.event_id)""")
    m["timed_frames_total"] = q1(con, """
        SELECT count(*) FROM research_event_frames
        WHERE observed_time_start IS NOT NULL AND observed_time_end IS NOT NULL""")
    m["relation_distribution_json"] = json.dumps({
        r[0]: r[1] for r in con.execute(
            "SELECT relation, count(*) FROM event_frame_temporal GROUP BY 1 ORDER BY 2 DESC")},
        ensure_ascii=False)
    m["confidence_min_max"] = [q1(con, "SELECT min(confidence) FROM event_frame_temporal"),
                               q1(con, "SELECT max(confidence) FROM event_frame_temporal")]
    m["frames_involved"] = q1(con, """
        SELECT count(DISTINCT event_id) FROM (
            SELECT frame_a AS event_id FROM event_frame_temporal
            UNION SELECT frame_b FROM event_frame_temporal)""")
    m["rows_missing_basis"] = q1(con, """
        SELECT count(*) FROM event_frame_temporal
        WHERE relation_basis IS NULL OR relation_basis=''""")
    m["rows_not_inferred_violation"] = q1(con, """
        SELECT count(*) FROM event_frame_temporal WHERE causality_status <> 'not_inferred'""")
    return m


# ---------------------------------------------------------------------------
# U5 — assertion_temporal_relations（Allen 区间关系，同实体/同事件/同状态主体候选限制）
# ---------------------------------------------------------------------------
def upgrade_u5(con: sqlite3.Connection) -> dict:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS assertion_temporal_relations (
            left_fact_id     TEXT NOT NULL REFERENCES research_assertions(fact_id),
            right_fact_id    TEXT NOT NULL REFERENCES research_assertions(fact_id),
            relation_code    TEXT NOT NULL CHECK(relation_code IN
                ('before','after','meets','overlaps','during','contains','starts','ends','equals')),
            relation_basis   TEXT NOT NULL CHECK(relation_basis IN ('assertion_interval_compare')),
            time_precision   TEXT NOT NULL,
            causality_status TEXT NOT NULL DEFAULT 'not_inferred'
                             CHECK(causality_status = 'not_inferred'),
            computed_at      TEXT NOT NULL,
            PRIMARY KEY (left_fact_id, right_fact_id)
        ) WITHOUT ROWID;

        CREATE INDEX IF NOT EXISTS ix_atr_left  ON assertion_temporal_relations(left_fact_id);
        CREATE INDEX IF NOT EXISTS ix_atr_right ON assertion_temporal_relations(right_fact_id);
    """)

    # Allen 9 分支（方向约定：left = fact_id 字典序较小的一方，relation 描述 left 相对 right）
    _ALLEN = """
        CASE
            WHEN a.time_end < b.time_start THEN 'before'
            WHEN a.time_start > b.time_end THEN 'after'
            WHEN a.time_end = b.time_start THEN 'meets'
            WHEN a.time_start = b.time_start AND a.time_end = b.time_end THEN 'equals'
            WHEN a.time_start = b.time_start AND a.time_end < b.time_end THEN 'starts'
            WHEN a.time_end = b.time_end AND a.time_start > b.time_start THEN 'ends'
            WHEN a.time_start >= b.time_start AND a.time_end <= b.time_end THEN 'during'
            WHEN a.time_start <= b.time_start AND a.time_end >= b.time_end THEN 'contains'
            ELSE 'overlaps'
        END
    """
    _PRECS = """
        CASE max(CASE a.time_precision WHEN 'month' THEN 1 WHEN 'year' THEN 2
                  WHEN 'period' THEN 3 ELSE 0 END,
                 CASE b.time_precision WHEN 'month' THEN 1 WHEN 'year' THEN 2
                  WHEN 'period' THEN 3 ELSE 0 END)
             WHEN 1 THEN 'month' WHEN 2 THEN 'year' WHEN 3 THEN 'period' ELSE 'unknown' END
    """
    _GUARD = ("a.time_start IS NOT NULL AND a.time_end IS NOT NULL "
              "AND b.time_start IS NOT NULL AND b.time_end IS NOT NULL")

    stamp = now_iso()
    base_cols = (f"SELECT a.fact_id, b.fact_id, {_ALLEN}, 'assertion_interval_compare', "
                 f"{_PRECS}, 'not_inferred', ? ")

    # F1 同实体（同 subject_id）——12a 同主体候选限制
    try:
        before = q1(con, "SELECT count(*) FROM assertion_temporal_relations")
    except sqlite3.Error:
        before = 0
    con.execute(f"""
        INSERT OR IGNORE INTO assertion_temporal_relations
            (left_fact_id, right_fact_id, relation_code, relation_basis,
             time_precision, causality_status, computed_at)
        {base_cols}
        FROM research_assertions a
        JOIN research_assertions b
          ON a.subject_id = b.subject_id AND a.fact_id < b.fact_id
         AND a.merged_into IS NULL AND b.merged_into IS NULL
        WHERE {_GUARD}
    """, (stamp,))
    after_f1 = q1(con, "SELECT count(*) FROM assertion_temporal_relations")

    # F2 同事件（research_event_assertion_links）
    con.execute(f"""
        INSERT OR IGNORE INTO assertion_temporal_relations
            (left_fact_id, right_fact_id, relation_code, relation_basis,
             time_precision, causality_status, computed_at)
        {base_cols}
        FROM (SELECT DISTINCT la.fact_id AS fa, lb.fact_id AS fb
              FROM research_event_assertion_links la
              JOIN research_event_assertion_links lb
                ON lb.event_id = la.event_id AND lb.fact_id > la.fact_id) p
        JOIN research_assertions a ON a.fact_id = p.fa AND a.merged_into IS NULL
        JOIN research_assertions b ON b.fact_id = p.fb AND b.merged_into IS NULL
        WHERE {_GUARD}
    """, (stamp,))
    after_f2 = q1(con, "SELECT count(*) FROM assertion_temporal_relations")

    # F3 同 CultureState 主体（states 共享 culture_subject_id，取其支撑事实对）
    con.execute(f"""
        INSERT OR IGNORE INTO assertion_temporal_relations
            (left_fact_id, right_fact_id, relation_code, relation_basis,
             time_precision, causality_status, computed_at)
        {base_cols}
        FROM (SELECT DISTINCT xa.fact_id AS fa, xb.fact_id AS fb
              FROM research_culture_state_support xa
              JOIN research_culture_states sa ON sa.state_id = xa.state_id
              JOIN research_culture_states sb
                ON sb.culture_subject_id = sa.culture_subject_id AND sb.state_id <> sa.state_id
              JOIN research_culture_state_support xb ON xb.state_id = sb.state_id
             WHERE xb.fact_id > xa.fact_id) p
        JOIN research_assertions a ON a.fact_id = p.fa AND a.merged_into IS NULL
        JOIN research_assertions b ON b.fact_id = p.fb AND b.merged_into IS NULL
        WHERE {_GUARD}
    """, (stamp,))
    after_f3 = q1(con, "SELECT count(*) FROM assertion_temporal_relations")

    m = {}
    m["rows_total"] = after_f3
    m["rows_family_same_entity"] = after_f1 - before
    m["rows_family_same_event"] = after_f2 - after_f1
    m["rows_family_same_state_subject"] = after_f3 - after_f2
    m["relation_distribution_json"] = json.dumps({
        r[0]: r[1] for r in con.execute(
            "SELECT relation_code, count(*) FROM assertion_temporal_relations "
            "GROUP BY 1 ORDER BY 2 DESC")}, ensure_ascii=False)
    m["precision_distribution_json"] = json.dumps({
        r[0]: r[1] for r in con.execute(
            "SELECT time_precision, count(*) FROM assertion_temporal_relations "
            "GROUP BY 1 ORDER BY 2 DESC")}, ensure_ascii=False)
    m["left_facts"] = q1(con, "SELECT count(DISTINCT left_fact_id) FROM assertion_temporal_relations")
    m["rows_missing_basis"] = q1(con, """
        SELECT count(*) FROM assertion_temporal_relations
        WHERE relation_basis IS NULL OR relation_basis=''""")
    m["rows_not_inferred_violation"] = q1(con, """
        SELECT count(*) FROM assertion_temporal_relations
        WHERE causality_status <> 'not_inferred'""")
    m["rows_involving_merged_fact"] = q1(con, """
        SELECT count(*) FROM assertion_temporal_relations r
        WHERE EXISTS (SELECT 1 FROM research_assertions x
                      WHERE x.fact_id = r.left_fact_id AND x.merged_into IS NOT NULL)
           OR EXISTS (SELECT 1 FROM research_assertions x
                      WHERE x.fact_id = r.right_fact_id AND x.merged_into IS NOT NULL)""")
    return m


# ---------------------------------------------------------------------------
# U6 — role-owner 选择性回填（唯一裁判 = CLOSURE3_RULES.json 的 type→action）
# ---------------------------------------------------------------------------
def _register_sha256_fn(con: sqlite3.Connection) -> None:
    con.create_function("u_sha256", 1,
                        lambda b: hashlib.sha256(b.encode("utf-8")).hexdigest(),
                        deterministic=True)


def load_closure3_rules(rules_path: Path) -> dict:
    """只读加载三票规则表；REWRITE 类为空集时 U6 不回填任何行（MEASURED 结论）。"""
    doc = json.loads(rules_path.read_text(encoding="utf-8"))
    actions = {str(k): str(v.get("action", "UNRESOLVED")).upper()
               for k, v in doc.get("rules", {}).items()}
    return {"path": str(rules_path), "sha256_16": sha256_file(rules_path)[:16],
            "actions": actions,
            "unseen_type_default": str(doc.get("unseen_type_default", "UNRESOLVED")).upper()}


def _role_coverage(con: sqlite3.Connection) -> dict:
    total = q1(con, "SELECT count(*) FROM research_assertions")
    if not total:
        return {k: 0.0 for k in ("time_owner_cov", "space_owner_cov",
                                 "time_role_unknown_rate", "space_role_unknown_rate")}
    return {
        "time_owner_cov": round(q1(con, """
            SELECT count(*) FROM research_assertions
            WHERE time_owner_id IS NOT NULL""") / total, 6),
        "space_owner_cov": round(q1(con, """
            SELECT count(*) FROM research_assertions
            WHERE space_owner_id IS NOT NULL""") / total, 6),
        "time_role_unknown_rate": round(q1(con, """
            SELECT count(*) FROM research_assertions
            WHERE time_role='unknown'""") / total, 6),
        "space_role_unknown_rate": round(q1(con, """
            SELECT count(*) FROM research_assertions
            WHERE space_role='unknown'""") / total, 6),
    }


# REWRITE 处置器（仅当规则表把某类判为 REWRITE 时才执行；全部只动 canonical 事实）
_U6_REWRITE_HANDLERS = {
    "unknown→event_occurrence": """
        UPDATE research_assertions
        SET time_owner_id = subject_id, time_role = 'event_occurrence'
        WHERE subject_type = 'Event' AND time_role = 'unknown'
          AND time_owner_id IS NULL AND merged_into IS NULL""",
    "event_location→context_location": """
        UPDATE research_assertions
        SET space_role = 'context_location'
        WHERE space_role = 'event_location' AND merged_into IS NULL""",
    "event_location→relation_location": """
        UPDATE research_assertions
        SET space_role = 'relation_location'
        WHERE space_role = 'event_location' AND merged_into IS NULL""",
}

# 候选计数器：无论 action 如何都 MEASURED（回填与否由规则表决定）
_U6_CANDIDATE_COUNTERS = {
    "unknown→event_occurrence": """
        SELECT count(*) FROM research_assertions
        WHERE subject_type='Event' AND time_role='unknown'
          AND time_owner_id IS NULL AND merged_into IS NULL""",
    "event_location→context_location": """
        SELECT count(*) FROM research_assertions
        WHERE space_role='event_location' AND merged_into IS NULL""",
    "event_location→relation_location": """
        SELECT count(*) FROM research_assertions
        WHERE space_role='event_location' AND merged_into IS NULL""",
    "mixed": None,   # 无机械候选口径：计数恒为 0（记录规则、不回填）
    "other": None,
}


def upgrade_u6(con: sqlite3.Connection, rules_path: Path) -> dict:
    spec = load_closure3_rules(rules_path)
    rewrite_classes = sorted(k for k, v in spec["actions"].items() if v == "REWRITE")
    unknown = sorted(k for k in spec["actions"]
                     if k not in _U6_REWRITE_HANDLERS and spec["actions"][k] == "REWRITE")
    if unknown:  # 规则表出现未登记的 REWRITE 类 → 拒绝静默处理
        raise RuntimeError(f"U6: unregistered REWRITE classes in rules file: {unknown}")

    before_cov = _role_coverage(con)
    candidates = {k: (q1(con, sql) if sql else 0)
                  for k, sql in _U6_CANDIDATE_COUNTERS.items()
                  if k in spec["actions"]}

    rows_backfilled = 0
    per_class = {}
    for cls in rewrite_classes:                     # 实际规则表：空集 → 本循环不执行
        cur = con.execute(_U6_REWRITE_HANDLERS[cls])
        per_class[cls] = max(cur.rowcount, 0)
        rows_backfilled += max(cur.rowcount, 0)
    after_cov = _role_coverage(con)

    m = {}
    m["rules_path"] = spec["path"]
    m["rules_sha256_16"] = spec["sha256_16"]
    m["rule_actions_json"] = json.dumps(spec["actions"], ensure_ascii=False, sort_keys=True)
    m["unseen_type_default"] = spec["unseen_type_default"]
    m["rewrite_classes_json"] = json.dumps(rewrite_classes, ensure_ascii=False)
    m["candidates_json"] = json.dumps(candidates, ensure_ascii=False, sort_keys=True)
    m["rows_backfilled"] = rows_backfilled
    m["rows_backfilled_by_class_json"] = json.dumps(per_class, ensure_ascii=False)
    for k, v in before_cov.items():
        m[f"before_{k}"] = v
    for k, v in after_cov.items():
        m[f"after_{k}"] = v
    m["global_heuristic_used"] = False
    return m


# ---------------------------------------------------------------------------
# U7 — research_place_relations（最小空间层级，双端硬约束为空间类型）
# ---------------------------------------------------------------------------
# 配套清洗（12a U7 建议，规则化）：父节点名带组织后缀 → needs_review 复核位
# （上游把 农救会/被服厂 等组织误标为 Place；entity_type 硬约束无法拦截，此处降级复核）
_U7_ORG_SUFFIX_RE = re.compile(r"(?:会|局|部|处|署|所|军|队|校|厂|社|馆|委|厅|司|团|党)$")


def _load_spatial_names(con: sqlite3.Connection) -> tuple[dict, dict]:
    """空间类型实体名索引：name -> (sorted entity_ids, all_types_set)。

    eligible（唯一空间归属）= 存在空间实体 且 该名下不含任何非空间类型实体。
    """
    ids: dict[str, list] = {}
    types: dict[str, set] = {}
    for r in con.execute(
            "SELECT entity_id, canonical_name, entity_type FROM research_entities "
            "WHERE canonical_name IS NOT NULL AND canonical_name<>''"):
        types.setdefault(r["canonical_name"], set()).add(r["entity_type"])
        if r["entity_type"] in SPATIAL_TYPES:
            ids.setdefault(r["canonical_name"], []).append(r["entity_id"])
    for v in ids.values():
        v.sort()
    return ids, types


def upgrade_u7(con: sqlite3.Connection, rebuild: bool = False) -> dict:
    _register_sha256_fn(con)
    if rebuild:  # --force U7：派生表全量重建（内容完全由断言+字段+实体类型决定）
        con.execute("DELETE FROM research_place_relations")
    con.executescript(f"""
        CREATE TABLE IF NOT EXISTS research_place_relations (
            place_relation_id TEXT PRIMARY KEY,
            child_place_id    TEXT NOT NULL REFERENCES research_entities(entity_id),
            parent_place_id   TEXT NOT NULL REFERENCES research_entities(entity_id),
            relation          TEXT NOT NULL CHECK(relation IN
                                  ('located_in','part_of','contains','within_basin')),
            evidence_id       TEXT,
            status            TEXT NOT NULL CHECK(status IN
                                  ('auto_typed','needs_review','rejected')),
            UNIQUE(child_place_id, parent_place_id, relation)
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS ix_prel_child ON research_place_relations(child_place_id);
        CREATE INDEX IF NOT EXISTS ix_prel_parent ON research_place_relations(parent_place_id);
    """)
    sp = tuple(SPATIAL_TYPES)

    # S1 显式断言收编（strict→auto_typed；contextual→needs_review；unresolved 不收）
    cur = con.execute(f"""
        INSERT OR IGNORE INTO research_place_relations
            (place_relation_id, child_place_id, parent_place_id, relation,
             evidence_id, status)
        SELECT 'PLREL-' || substr(u_sha256(s.entity_id||'|'||o.entity_id||'|'||a.predicate), 1, 16),
               s.entity_id, o.entity_id, a.predicate, a.fact_id,
               CASE WHEN a.research_tier='strict_semantic' THEN 'auto_typed'
                    ELSE 'needs_review' END
        FROM research_assertions a
        JOIN research_entities s ON s.entity_id = a.subject_id
        JOIN research_entities o ON o.entity_id = a.object_id
        WHERE a.predicate IN ('located_in','part_of')
          AND a.research_tier IN ('strict_semantic','contextual')
          AND s.entity_type IN {sp} AND o.entity_type IN {sp}
    """)
    s1_inserted = max(cur.rowcount, 0)

    # S2 province/city/county 字段链（名称须唯一空间归属；双端为实体才建边）
    ids, types = _load_spatial_names(con)

    def resolve_unique(name: str):
        """返回实体 id 列表（唯一空间归属时恰 1 个）；不合规格返回 (None, 原因)。"""
        spat = ids.get(name) or []
        if not spat:
            return None, "no_spatial_entity"
        if not (types.get(name) or set()) <= set(SPATIAL_TYPES):
            return None, "type_ambiguous"
        if len(spat) > 1:
            return None, "multi_spatial"
        return spat[0], None

    s2_inserted = 0
    s2_pairs_seen = 0
    s2_skipped: dict[str, int] = {}
    chain_sql = """
        INSERT OR IGNORE INTO research_place_relations
            (place_relation_id, child_place_id, parent_place_id, relation,
             evidence_id, status)
        VALUES (?, ?, ?, 'located_in', ?, 'auto_typed')
    """
    for hi_col, lo_col in (("province", "city"), ("city", "county")):
        for r in con.execute(f"""
                SELECT min(fact_id) AS fid, {hi_col} AS hin, {lo_col} AS lon
                FROM research_assertions
                WHERE {hi_col} IS NOT NULL AND {hi_col}<>''
                  AND {lo_col} IS NOT NULL AND {lo_col}<>'' AND {lo_col}<>{hi_col}
                GROUP BY {hi_col}, {lo_col}"""):
            s2_pairs_seen += 1
            pid, e1 = resolve_unique(r["hin"])
            cid, e2 = resolve_unique(r["lon"])
            if not pid or not cid:
                key = f"{hi_col}>{lo_col}:" + (e1 or e2 or "unresolved")
                s2_skipped[key] = s2_skipped.get(key, 0) + 1
                continue
            rid = "PLREL-" + hashlib.sha256(
                f"{cid}|{pid}|located_in".encode("utf-8")).hexdigest()[:16]
            cur = con.execute(chain_sql, (rid, cid, pid, r["fid"]))
            s2_inserted += max(cur.rowcount, 0)

    # S3 within_basin：父节点必须是空间实体；basin 段（research_basin_sections）并非
    # research_entities 中的实体 → 本库内可建 within_basin 边为 0（如实测量）。
    s3_pairs_seen = 0
    s3_inserted = 0
    has_basin_tables = (
        _q_table_exists(con, "research_region_hierarchy")
        and _q_table_exists(con, "research_basin_sections"))
    if has_basin_tables:
        for r in con.execute("""
                SELECT h.region_id, h.basin_section_id, b.basin_section_name
                FROM research_region_hierarchy h
                JOIN research_basin_sections b ON b.basin_section_id = h.basin_section_id"""):
            s3_pairs_seen += 1
            # basin_section_name（上游/中游/下游）非实体 → 严格按类型约束跳过
            pid, reason = resolve_unique(r["basin_section_name"])
            if not pid:
                s3_skipped_key = f"within_basin:{reason}"
                s2_skipped[s3_skipped_key] = s2_skipped.get(s3_skipped_key, 0) + 1
                continue
            raise RuntimeError("U7: unexpected basin entity — extend type guard first")

    # 环检测（确定性 DFS，只对生效边）：环上边 → rejected
    edges = [(r[0], r[1], r[2]) for r in con.execute("""
        SELECT child_place_id, parent_place_id, place_relation_id
        FROM research_place_relations WHERE status<>'rejected'""")]
    adj: dict[str, set] = {}
    for c, p, _ in edges:
        adj.setdefault(c, set()).add(p)
    cycle_ids: set[str] = set()
    for c, p, rid in edges:
        seen: set[str] = set()
        stack = list(adj.get(p, ()))
        while stack:
            n = stack.pop()
            if n == c:
                cycle_ids.add(rid)
                break
            if n in seen:
                continue
            seen.add(n)
            stack.extend(adj.get(n, ()))
    if cycle_ids:
        con.executemany("UPDATE research_place_relations SET status='rejected' "
                        "WHERE place_relation_id=?",
                        [(r,) for r in sorted(cycle_ids)])

    # 配套清洗：父节点名为组织（名称后缀规则）→ auto_typed 降级 needs_review
    org_flagged = []
    for pid, name in con.execute("""
            SELECT DISTINCT r.parent_place_id, p.canonical_name
            FROM research_place_relations r
            JOIN research_entities p ON p.entity_id = r.parent_place_id
            WHERE r.status='auto_typed'"""):
        if _U7_ORG_SUFFIX_RE.search(name or ""):
            org_flagged.append((pid, name))
    if org_flagged:
        con.executemany("""
            UPDATE research_place_relations SET status='needs_review'
            WHERE status='auto_typed' AND parent_place_id=?""",
            [(pid,) for pid, _ in sorted(org_flagged)])

    m = {}
    m["org_parent_flagged"] = len(org_flagged)
    m["org_parent_flagged_names_json"] = json.dumps(
        sorted({n for _, n in org_flagged}), ensure_ascii=False)
    m["rows_total"] = q1(con, "SELECT count(*) FROM research_place_relations")
    m["s1_explicit_inserted_this_run"] = s1_inserted
    m["s2_chain_pairs_seen"] = s2_pairs_seen
    m["s2_chain_inserted_this_run"] = s2_inserted
    m["s2_skipped_json"] = json.dumps(s2_skipped, ensure_ascii=False, sort_keys=True)
    m["s3_within_basin_pairs_seen"] = s3_pairs_seen
    m["s3_within_basin_inserted"] = s3_inserted
    m["relation_distribution_json"] = json.dumps({
        r[0]: r[1] for r in con.execute(
            "SELECT relation, count(*) FROM research_place_relations GROUP BY 1 ORDER BY 2 DESC")},
        ensure_ascii=False)
    m["status_distribution_json"] = json.dumps({
        r[0]: r[1] for r in con.execute(
            "SELECT status, count(*) FROM research_place_relations GROUP BY 1 ORDER BY 2 DESC")},
        ensure_ascii=False)
    m["non_spatial_endpoint_rows"] = q1(con, f"""
        SELECT count(*) FROM research_place_relations r
        JOIN research_entities c ON c.entity_id = r.child_place_id
        JOIN research_entities p ON p.entity_id = r.parent_place_id
        WHERE c.entity_type NOT IN {sp} OR p.entity_type NOT IN {sp}""")
    m["rows_on_cycle"] = len(cycle_ids)
    m["places_with_parent"] = q1(con, """
        SELECT count(DISTINCT child_place_id) FROM research_place_relations""")
    return m


# ---------------------------------------------------------------------------
# U8 — research_place_versions（只建语料证据可自动支持的历史地名版本）
# ---------------------------------------------------------------------------
_PLACE_SUFFIX_RE = re.compile(
    r"(?:省|市|县|区|乡|镇|村|州|屯|寨|堡|场|铺|街|巷|河|湖|江|山|城|关|岛|岭|集|埠|驿|港|"
    r"湾|池|滩|桥|站|旗|盟|道|里|庄|洼|淀|沟|坪|坝|坊|厅|郡|府|京|洲|潭|泉|洞|岩|塘|营|圩|"
    r"垸|嘴|碑|界|口|门|所|哨|卡|盆地|流域|专区|特区|矿区|苏区|边区|解放区|管理局|专署|地区)$")
_GENERIC_PLACE_RE = re.compile(r"^[一二三四五六七八九十０-９0-9]{1,3}(?:区|分区|专区)$")
_GENERIC_PLACE_SET = {"专区", "专署", "地区", "苏区", "边区", "游击区", "管理局",
                      "解放区", "特区", "根据地"}
_U8_KEYWORDS_RE = re.compile(r"原名|原称|改名为|改名|改称|改为|当时属|时属")
_U8_YEAR_RE = re.compile(r"(19[0-9]{2}|20[0-9]{2})年")
_U8_CJK_RE = re.compile(r"[一-鿿]+")


def _is_generic_place(name: str) -> bool:
    return bool(_GENERIC_PLACE_RE.match(name)) or name in _GENERIC_PLACE_SET


def _admin_level_of(entity_type: str, name: str) -> str:
    if entity_type != "AdministrativeRegion":
        return "site"
    for suffix, level in (("专区", "prefecture"), ("地区", "prefecture"),
                          ("省", "province"), ("市", "city"), ("县", "county"),
                          ("区", "district"), ("乡", "township"), ("镇", "town"),
                          ("村", "village"), ("盟", "league"), ("旗", "banner")):
        if name.endswith(suffix):
            return level
    return "admin_region"


def _u8_longest_name_ending_at(text: str, end: int, name_ids: dict, max_len: int = 16):
    """关键词前最长实体名及其起点；允许跳过紧邻的开括号/引号（如「临江镇（时属庐陵县）」）。"""
    while end > 0 and text[end - 1] in "（(《\"“「【〔":
        end -= 1
    for ln in range(min(max_len, end), 1, -1):
        cand = text[end - ln:end]
        if cand in name_ids:
            return cand, end - ln
    return None, end


# 确定性降级哨兵：命中则该行降级 needs_review（保留证据位供复核，不入 auto 子集）
_U8_PARENT_MARKERS = ("划归", "并入", "拨归", "划入", "归属")
_U8_ENUM_BEFORE = "、）)；，；："


def _u8_review_reasons(content: str, kw_start: int, cur_start: int) -> list:
    reasons = []
    if any(m in content[max(0, kw_start - 20):kw_start] for m in _U8_PARENT_MARKERS):
        reasons.append("parent_marker_before_keyword")   # 「划归X改为Y」：X 是归属而非旧名
    if cur_start > 0 and content[cur_start - 1] in _U8_ENUM_BEFORE:
        reasons.append("enumeration_context")            # 「、X（原名Y）」枚举语境，主语未必是地名
    return reasons


def upgrade_u8(con: sqlite3.Connection, corpus_path: Path, rebuild: bool = False) -> dict:
    _register_sha256_fn(con)
    if rebuild:  # --force U8：派生表全量重建（内容完全由语料+实体集决定）
        con.execute("DELETE FROM research_place_versions")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS research_place_versions (
            place_version_id   TEXT PRIMARY KEY,
            canonical_place_id TEXT NOT NULL REFERENCES research_entities(entity_id),
            historical_name    TEXT NOT NULL,
            valid_from         TEXT,
            valid_to           TEXT,
            admin_level        TEXT,
            parent_place_id    TEXT REFERENCES research_entities(entity_id),
            evidence_id        TEXT NOT NULL,
            status             TEXT NOT NULL CHECK(status IN ('auto_evidence','needs_review')),
            derived_pattern    TEXT NOT NULL CHECK(derived_pattern IN
                                   ('former_name','renamed_to','same_period_parent'))
        ) WITHOUT ROWID;

        CREATE UNIQUE INDEX IF NOT EXISTS ux_place_versions_natural
            ON research_place_versions(canonical_place_id, historical_name,
                ifnull(parent_place_id,''), ifnull(valid_from,''));
        CREATE INDEX IF NOT EXISTS ix_pver_place
            ON research_place_versions(canonical_place_id);
    """)

    ids, types = _load_spatial_names(con)
    ent_type: dict[str, str] = {}
    ent_name: dict[str, str] = {}
    for r in con.execute("SELECT entity_id, canonical_name, entity_type FROM research_entities"):
        ent_type[r["entity_id"]] = r["entity_type"]
        ent_name[r["entity_id"]] = r["canonical_name"]

    def eligible(name: str) -> bool:
        return bool(ids.get(name)) and (types.get(name) or set()) <= set(SPATIAL_TYPES)

    def other_side_ok(name: str) -> bool:
        return 2 <= len(name) <= 14 and (eligible(name) or bool(_PLACE_SUFFIX_RE.search(name)))

    # (place_id, historical_name, parent_id|None, valid_from|None) -> 聚合
    rows: dict[tuple, dict] = {}
    kw_hits: dict[str, int] = {}
    rejects = {"cur_side_not_eligible": 0, "other_side_rejected": 0}

    with open(corpus_path, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        header = next(rd, None)
        corpus_rows = 0
        for row in rd:
            corpus_rows += 1
            rid = row[0] if row else ""
            content = row[3] if len(row) > 3 else ""
            if not rid or not content:
                continue
            for mt in _U8_KEYWORDS_RE.finditer(content):
                kw = mt.group(0)
                kw_hits[kw] = kw_hits.get(kw, 0) + 1
                s, e = mt.span()
                year_m = _U8_YEAR_RE.search(content[max(0, s - 40):e + 40])
                year = year_m.group(1) if year_m else None
                if kw in ("原名", "原称"):                      # CUR原名HIST
                    cur, cur_start = _u8_longest_name_ending_at(content, s, ids)
                    run = _U8_CJK_RE.match(content, e)
                    hist = run.group(0) if run else ""
                    if not cur or not eligible(cur):
                        rejects["cur_side_not_eligible"] += 1
                        continue
                    if not other_side_ok(hist):
                        rejects["other_side_rejected"] += 1
                        continue
                    generic = _is_generic_place(cur) or _is_generic_place(hist)
                    review = set(_u8_review_reasons(content, s, cur_start))
                    for eid in ids[cur]:
                        key = (eid, hist, None, year)
                        rec = rows.setdefault(key, {"evidence": set(), "pattern": "former_name",
                                                    "generic": generic, "review": set()})
                        rec["evidence"].add(rid)
                        rec["review"] |= review
                elif kw in ("改名为", "改名", "改称", "改为"):     # OLD改名NEW
                    old, cur_start = _u8_longest_name_ending_at(content, s, ids)
                    old = old or ""
                    run = _U8_CJK_RE.match(content, e)
                    new = run.group(0) if run else ""
                    if not new or not eligible(new):
                        rejects["cur_side_not_eligible"] += 1
                        continue
                    if not other_side_ok(old):
                        rejects["other_side_rejected"] += 1
                        continue
                    generic = _is_generic_place(new) or _is_generic_place(old)
                    review = set(_u8_review_reasons(content, s, cur_start))
                    for eid in ids[new]:
                        key = (eid, old, None, year)
                        rec = rows.setdefault(key, {"evidence": set(), "pattern": "renamed_to",
                                                    "generic": generic, "review": set()})
                        rec["evidence"].add(rid)
                        rec["review"] |= review
                else:                                             # PL(当时)属PAR
                    pl, cur_start = _u8_longest_name_ending_at(content, s, ids)
                    run = _U8_CJK_RE.match(content, e)
                    rest = run.group(0) if run else ""
                    if rest.startswith("于"):
                        rest = rest[1:]
                    if not pl or not eligible(pl):
                        rejects["cur_side_not_eligible"] += 1
                        continue
                    if not eligible(rest):                        # 父名必须全串精确命中实体
                        rejects["other_side_rejected"] += 1
                        continue
                    generic = _is_generic_place(pl) or _is_generic_place(rest)
                    for eid in ids[pl]:
                        key = (eid, ent_name.get(eid, pl), ids[rest][0], year)
                        rec = rows.setdefault(key, {"evidence": set(),
                                                    "pattern": "same_period_parent",
                                                    "generic": generic, "review": set()})
                        rec["evidence"].add(rid)

    payload = []
    downgrade_counts: dict[str, int] = {}
    for (eid, hist, par, year), rec in sorted(
            rows.items(),
            key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or "", kv[0][3] or "")):
        pvid = "PVER-" + hashlib.sha256(
            f"{eid}|{hist}|{par or ''}|{year or ''}".encode("utf-8")).hexdigest()[:16]
        needs_review = bool(rec["generic"]) or bool(rec["review"])
        for reason in rec["review"]:
            downgrade_counts[reason] = downgrade_counts.get(reason, 0) + 1
        payload.append((pvid, eid, hist, year, None,
                        _admin_level_of(ent_type.get(eid, ""), ent_name.get(eid, "")),
                        par, min(rec["evidence"]),
                        "needs_review" if needs_review else "auto_evidence",
                        rec["pattern"]))
    before = q1(con, "SELECT count(*) FROM research_place_versions")
    con.executemany("""
        INSERT OR IGNORE INTO research_place_versions
            (place_version_id, canonical_place_id, historical_name, valid_from, valid_to,
             admin_level, parent_place_id, evidence_id, status, derived_pattern)
        VALUES (?,?,?,?,?,?,?,?,?,?)""", payload)
    after = q1(con, "SELECT count(*) FROM research_place_versions")

    spatial_total = q1(con,
        f"SELECT count(*) FROM research_entities WHERE entity_type IN {tuple(SPATIAL_TYPES)}")
    m = {}
    m["corpus_path"] = str(corpus_path)
    m["corpus_sha256_16"] = sha256_file(corpus_path)[:16] if corpus_path.exists() else None
    m["corpus_rows_scanned"] = corpus_rows
    m["keyword_hits_json"] = json.dumps(kw_hits, ensure_ascii=False, sort_keys=True)
    m["candidate_keys"] = len(rows)
    m["rows_total"] = after
    m["rows_inserted_this_run"] = after - before
    m["rows_auto_evidence"] = q1(con, """SELECT count(*) FROM research_place_versions
                                         WHERE status='auto_evidence'""")
    m["rows_needs_review"] = q1(con, """SELECT count(*) FROM research_place_versions
                                        WHERE status='needs_review'""")
    m["rows_with_valid_from"] = q1(con, """SELECT count(*) FROM research_place_versions
                                           WHERE valid_from IS NOT NULL""")
    m["pattern_distribution_json"] = json.dumps({
        r[0]: r[1] for r in con.execute(
            "SELECT derived_pattern, count(*) FROM research_place_versions GROUP BY 1")},
        ensure_ascii=False)
    m["spatial_entities_total"] = spatial_total
    m["spatial_entities_with_version"] = q1(con, """
        SELECT count(DISTINCT canonical_place_id) FROM research_place_versions""")
    m["coverage_of_spatial_entities"] = round(
        m["spatial_entities_with_version"] / spatial_total, 6) if spatial_total else 0.0
    m["reject_counters_json"] = json.dumps(rejects, ensure_ascii=False)
    m["downgrade_counters_json"] = json.dumps(downgrade_counts, ensure_ascii=False)
    return m


def _q_table_exists(con: sqlite3.Connection, name: str) -> bool:
    return q1(con, "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?",
              (name,)) > 0



def _load_contract_defs():
    """加载关系契约参考定义（只读 import，不改任何文件）。失败则降级为 None。"""
    try:
        sys.path.insert(0, str(EXTERNAL_INPUTS))
        from stkg_contract import RELATIONS  # noqa: E402
        from stkg_v2_semantics import TYPE_PARENT  # noqa: E402
        return RELATIONS, TYPE_PARENT
    except Exception:
        return None, None


def _contract_check_factory():
    """复刻 293_audit_stkg_v2_full.py 的 hierarchy-aware 契约判定（只读逻辑）。"""
    RELATIONS, TYPE_PARENT = _load_contract_defs()
    if RELATIONS is None:
        return None

    def relation_type_allowed(actual, allowed):
        return actual in allowed or (actual == "SocialGroup" and "Organization" in allowed)

    def hierarchy_allowed(actual, allowed):
        current = str(actual or "").strip()
        seen = set()
        while current and current not in seen:
            if relation_type_allowed(current, allowed):
                return True
            seen.add(current)
            current = TYPE_PARENT.get(current, "")
        return False

    def compatible(predicate, source_type, target_type):
        rel = RELATIONS.get(str(predicate or "").strip())
        return bool(rel and hierarchy_allowed(source_type, rel.source_types)
                    and hierarchy_allowed(target_type, rel.target_types))
    return compatible


def verify_integrity(con: sqlite3.Connection, baseline_counts: dict | None) -> dict:
    res: dict[str, object] = {}

    res["quick_check"] = str(q1(con, "PRAGMA quick_check"))
    res["foreign_key_errors"] = len(con.execute("PRAGMA foreign_key_check").fetchall())

    counts = {
        "entities": "select count(*) from research_entities",
        "assertions": "select count(*) from research_assertions",
        "provenance": "select count(*) from research_assertion_provenance",
        "event_frames": "select count(*) from research_event_frames",
        "event_assertion_links": "select count(*) from research_event_assertion_links",
        "culture_states": "select count(*) from research_culture_states",
        "assertions_strict": "select count(*) from research_assertions where research_tier='strict_semantic'",
        "assertions_contextual": "select count(*) from research_assertions where research_tier='contextual'",
        "assertions_unresolved": "select count(*) from research_assertions where research_tier='unresolved'",
        "event_relations": "select count(*) from research_event_relations",
        "evolution_transitions": "select count(*) from research_evolution_transitions",
    }
    got = {k: q1(con, s) for k, s in counts.items()}
    res["counts"] = got
    if baseline_counts:
        res["counts_match_source"] = {k: (got.get(k) == v) for k, v in baseline_counts.items()}
        res["counts_all_match_source"] = all(res["counts_match_source"].values())

    # —— V2 发布自检同款检查（293_audit_stkg_v2_full.py 口径）
    compat = _contract_check_factory()
    if compat is not None:
        violations = 0
        for pred, st, ot in con.execute("""
                SELECT predicate, subject_type, object_type FROM research_assertions
                WHERE research_tier='strict_semantic'"""):
            if not compat(pred, st, ot):
                violations += 1
        res["strict_relation_contract_violations"] = violations
    else:
        res["strict_relation_contract_violations"] = None  # 参考定义不可用

    res["all_assertions_have_provenance_violations"] = q1(con, """
        SELECT count(*) FROM research_assertions a
        LEFT JOIN research_assertion_provenance p ON p.fact_id = a.fact_id
        WHERE p.fact_id IS NULL""")
    res["tier_conservation_violations"] = q1(con, """
        SELECT count(*) FROM research_assertions
        WHERE research_tier NOT IN ('strict_semantic','contextual','unresolved')""")
    res["eight_historical_stages"] = q1(con, "SELECT count(*) FROM research_historical_stages")

    # —— owner/anchor 引用有效性（invalid owner 必须 = 0）
    res["invalid_time_owner_refs"] = q1(con, """
        SELECT count(*) FROM research_assertions a
        WHERE a.time_owner_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM research_entities e
                          WHERE e.entity_id = a.time_owner_id)""")
    res["invalid_space_owner_refs"] = q1(con, """
        SELECT count(*) FROM research_assertions a
        WHERE a.space_owner_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM research_entities e
                          WHERE e.entity_id = a.space_owner_id)""")
    res["invalid_space_anchor_refs"] = q1(con, """
        SELECT count(*) FROM research_assertions a
        WHERE a.canonical_space_anchor_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM research_entities e
                          WHERE e.entity_id = a.canonical_space_anchor_id)""")
    res["invalid_state_subject_refs"] = q1(con, """
        SELECT count(*) FROM research_culture_states s
        WHERE NOT EXISTS (SELECT 1 FROM research_entities e
                          WHERE e.entity_id = s.culture_subject_id)""")

    # —— U1 不变量
    res["u1_orphan_rows"] = q1(con, """
        SELECT count(*) FROM event_frame_provenance r
        WHERE NOT EXISTS (SELECT 1 FROM research_event_frames f WHERE f.event_id=r.frame_id)
           OR NOT EXISTS (SELECT 1 FROM research_assertions a WHERE a.fact_id=r.assertion_id)
           OR NOT EXISTS (SELECT 1 FROM research_assertion_provenance p
                          WHERE p.provenance_id=r.provenance_id)""")
    res["u1_frames_total"] = q1(con, "SELECT count(*) FROM research_event_frames")
    res["u1_frames_with_provenance"] = q1(con,
        "SELECT count(DISTINCT frame_id) FROM event_frame_provenance")
    res["u1_frames_with_locatable_evidence"] = q1(con, """
        SELECT count(DISTINCT frame_id) FROM event_frame_provenance
        WHERE json_array_length(evidence_ids_json) > 0""")

    # —— U2 不变量
    res["u2_residual_state_duplicate_canonical_groups"] = q1(con, """
        SELECT count(*) FROM (
            SELECT 1 FROM research_assertions
            WHERE merged_into IS NULL
            GROUP BY subject_id, predicate, object_id,
                     coalesce(time_start,'#'), coalesce(time_end,'#'),
                     coalesce(canonical_space_anchor_id,'#')
            HAVING count(*)>1)""")
    res["u2_residual_text_quintet_duplicate_canonical_groups"] = q1(con, """
        SELECT count(*) FROM (
            SELECT 1 FROM research_assertions
            WHERE merged_into IS NULL
            GROUP BY subject_id, predicate, object_id, ifnull(time_raw,'~'), ifnull(place_raw,'~')
            HAVING count(*)>1)""")
    res["u2_merged_identity_mismatch"] = q1(con, """
        SELECT count(*) FROM research_assertions m
        JOIN research_assertions c ON c.fact_id = m.merged_into
        WHERE m.merged_into IS NOT NULL
          AND (m.subject_id<>c.subject_id OR m.predicate<>c.predicate
               OR m.object_id<>c.object_id
               OR ifnull(m.time_start,'#')<>ifnull(c.time_start,'#')
               OR ifnull(m.time_end,'#')<>ifnull(c.time_end,'#')
               OR ifnull(m.canonical_space_anchor_id,'#')<>ifnull(c.canonical_space_anchor_id,'#'))""")
    res["u2_merged_canonical_not_canonical"] = q1(con, """
        SELECT count(*) FROM research_assertions m
        JOIN research_assertions c ON c.fact_id = m.merged_into
        WHERE m.merged_into IS NOT NULL AND c.merged_into IS NOT NULL""")
    res["u2_pending_collision_groups"] = q1(con, """
        SELECT count(*) FROM research_assertion_identity_collisions WHERE resolution='pending'""")
    res["u2_unique_index_present"] = q1(con, """
        SELECT count(*) FROM sqlite_master
        WHERE type='index' AND name='ux_assertions_state_identity'""")
    res["u2_view_rows"] = q1(con, "SELECT count(*) FROM v_assertion_state_identity")
    res["u2_view_zero_provenance_rows"] = q1(con, """
        SELECT count(*) FROM v_assertion_state_identity WHERE n_provenance_members < 1""")

    # —— U3 不变量
    res["u3_source_flag_consistency_violations"] = q1(con, """
        SELECT count(*) FROM research_culture_states
        WHERE (fallback_to_stage=1 AND state_time_source<>'stage_interval')
           OR (fallback_to_stage=0 AND state_time_source='stage_interval')""")
    res["u3_states_without_time"] = q1(con,
        "SELECT count(*) FROM research_culture_states WHERE state_time_start IS NULL "
        "OR state_time_end IS NULL")
    res["u3_fallback_masked_as_precise"] = q1(con, """
        SELECT count(*) FROM research_culture_states
        WHERE fallback_to_stage=1 AND state_time_precision <> 'stage_interval'""")

    # —— U4 不变量：basis 齐备、非因果、关系可复算
    res["u4_missing_basis"] = q1(con, """
        SELECT count(*) FROM event_frame_temporal
        WHERE relation_basis IS NULL OR relation_basis=''""")
    res["u4_not_inferred_violations"] = q1(con, """
        SELECT count(*) FROM event_frame_temporal WHERE causality_status<>'not_inferred'""")
    res["u4_recompute_mismatch"] = q1(con, """
        SELECT count(*) FROM event_frame_temporal t
        JOIN research_event_frames a ON a.event_id = t.frame_a
        JOIN research_event_frames b ON b.event_id = t.frame_b
        WHERE t.relation <> CASE
            WHEN a.observed_time_end < b.observed_time_start THEN 'before'
            WHEN a.observed_time_start > b.observed_time_end THEN 'after'
            WHEN a.observed_time_start >= b.observed_time_start
                 AND a.observed_time_end <= b.observed_time_end THEN 'during'
            WHEN b.observed_time_start >= a.observed_time_start
                 AND b.observed_time_end <= a.observed_time_end THEN 'during'
            ELSE 'overlaps' END""")
    res["u4_rows_without_shared_counterpart"] = q1(con, """
        SELECT count(*) FROM event_frame_temporal t
        WHERE NOT EXISTS (SELECT 1 FROM research_event_roles ra
                          JOIN research_event_roles rb ON rb.counterpart_id=ra.counterpart_id
                          WHERE ra.event_id=t.frame_a AND rb.event_id=t.frame_b)""")

    # —— U5 不变量：Allen 判定可复算（全量）
    _ALLEN = """
        CASE
            WHEN a.time_end < b.time_start THEN 'before'
            WHEN a.time_start > b.time_end THEN 'after'
            WHEN a.time_end = b.time_start THEN 'meets'
            WHEN a.time_start = b.time_start AND a.time_end = b.time_end THEN 'equals'
            WHEN a.time_start = b.time_start AND a.time_end < b.time_end THEN 'starts'
            WHEN a.time_end = b.time_end AND a.time_start > b.time_start THEN 'ends'
            WHEN a.time_start >= b.time_start AND a.time_end <= b.time_end THEN 'during'
            WHEN a.time_start <= b.time_start AND a.time_end >= b.time_end THEN 'contains'
            ELSE 'overlaps' END
    """
    res["u5_recompute_mismatch"] = q1(con, f"""
        SELECT count(*) FROM assertion_temporal_relations r
        JOIN research_assertions a ON a.fact_id = r.left_fact_id
        JOIN research_assertions b ON b.fact_id = r.right_fact_id
        WHERE r.relation_code <> {_ALLEN}""")
    res["u5_not_inferred_violations"] = q1(con, """
        SELECT count(*) FROM assertion_temporal_relations
        WHERE causality_status<>'not_inferred'""")
    res["u5_missing_basis"] = q1(con, """
        SELECT count(*) FROM assertion_temporal_relations
        WHERE relation_basis IS NULL OR relation_basis=''""")
    res["u5_self_pairs"] = q1(con, """
        SELECT count(*) FROM assertion_temporal_relations WHERE left_fact_id=right_fact_id""")

    # —— U6 不变量：台账对照（REWRITE 类为空 ⇒ 0 回填 ⇒ 角色覆盖率与 after 值一致）
    if _q_table_exists(con, "stkg_upgrade_log") and applied(con, "U6") is not None:
        led6 = applied(con, "U6")["measured"]
        res["u6_ledger_rows_backfilled"] = led6.get("rows_backfilled")
        res["u6_ledger_rewrite_classes"] = led6.get("rewrite_classes_json")
        if "after_time_owner_cov" in led6:
            cur_cov = _role_coverage(con)
            res["u6_role_coverage_matches_ledger_after"] = all(
                abs(cur_cov[k] - led6[f"after_{k}"]) < 1e-9 for k in cur_cov)
        else:
            res["u6_role_coverage_matches_ledger_after"] = None
    else:
        res["u6_ledger_rows_backfilled"] = None
        res["u6_ledger_rewrite_classes"] = None
        res["u6_role_coverage_matches_ledger_after"] = None

    # —— U7 不变量：类型约束（组织/人物/概念不得为空间端点）、悬挂、自环、重复、环
    if _q_table_exists(con, "research_place_relations"):
        sp = tuple(SPATIAL_TYPES)
        res["u7_rows_total"] = q1(con, "SELECT count(*) FROM research_place_relations")
        res["u7_non_spatial_endpoint_rows"] = q1(con, f"""
            SELECT count(*) FROM research_place_relations r
            JOIN research_entities c ON c.entity_id = r.child_place_id
            JOIN research_entities p ON p.entity_id = r.parent_place_id
            WHERE c.entity_type NOT IN {sp} OR p.entity_type NOT IN {sp}""")
        res["u7_dangling_rows"] = q1(con, """
            SELECT count(*) FROM research_place_relations r
            WHERE NOT EXISTS (SELECT 1 FROM research_entities e
                              WHERE e.entity_id = r.child_place_id)
               OR NOT EXISTS (SELECT 1 FROM research_entities e
                              WHERE e.entity_id = r.parent_place_id)""")
        res["u7_self_loop_rows"] = q1(con, """
            SELECT count(*) FROM research_place_relations
            WHERE child_place_id = parent_place_id AND status<>'rejected'""")
        res["u7_duplicate_pair_rows"] = q1(con, """
            SELECT count(*) FROM (
              SELECT 1 FROM research_place_relations
              GROUP BY child_place_id, parent_place_id, relation HAVING count(*)>1)""")
        res["u7_auto_typed_rows_with_org_parent_name"] = sum(
            1 for (n,) in con.execute("""
                SELECT p.canonical_name FROM research_place_relations r
                JOIN research_entities p ON p.entity_id = r.parent_place_id
                WHERE r.status='auto_typed'""")
            if _U7_ORG_SUFFIX_RE.search(n or ""))
        res["u7_status_distribution_json"] = json.dumps({
            r[0]: r[1] for r in con.execute(
                "SELECT status, count(*) FROM research_place_relations GROUP BY 1")},
            ensure_ascii=False)
        cycle_edges = [(r[0], r[1]) for r in con.execute("""
            SELECT child_place_id, parent_place_id FROM research_place_relations
            WHERE status<>'rejected'""")]
        adj: dict[str, set] = {}
        for c, p in cycle_edges:
            adj.setdefault(c, set()).add(p)
        n_cycle = 0
        for c, p in cycle_edges:
            seen: set[str] = set()
            stack = list(adj.get(p, ()))
            hit = False
            while stack:
                n = stack.pop()
                if n == c:
                    hit = True
                    break
                if n in seen:
                    continue
                seen.add(n)
                stack.extend(adj.get(n, ()))
            n_cycle += int(hit)
        res["u7_active_rows_on_cycle"] = n_cycle
    else:
        res["u7_rows_total"] = None

    # —— U8 不变量：地点/父地点必须为空间类型、证据必填、自然键唯一、模式合法
    if _q_table_exists(con, "research_place_versions"):
        sp = tuple(SPATIAL_TYPES)
        res["u8_rows_total"] = q1(con, "SELECT count(*) FROM research_place_versions")
        res["u8_non_spatial_place_rows"] = q1(con, f"""
            SELECT count(*) FROM research_place_versions v
            JOIN research_entities e ON e.entity_id = v.canonical_place_id
            WHERE e.entity_type NOT IN {sp}""")
        res["u8_non_spatial_parent_rows"] = q1(con, f"""
            SELECT count(*) FROM research_place_versions v
            JOIN research_entities e ON e.entity_id = v.parent_place_id
            WHERE e.entity_type NOT IN {sp}""")
        res["u8_dangling_rows"] = q1(con, """
            SELECT count(*) FROM research_place_versions v
            WHERE NOT EXISTS (SELECT 1 FROM research_entities e
                              WHERE e.entity_id = v.canonical_place_id)
               OR (v.parent_place_id IS NOT NULL AND NOT EXISTS
                   (SELECT 1 FROM research_entities e
                    WHERE e.entity_id = v.parent_place_id))""")
        res["u8_missing_evidence_rows"] = q1(con, """
            SELECT count(*) FROM research_place_versions
            WHERE evidence_id IS NULL OR evidence_id=''""")
        res["u8_duplicate_natural_key_rows"] = q1(con, """
            SELECT count(*) FROM (
              SELECT 1 FROM research_place_versions
              GROUP BY canonical_place_id, historical_name,
                       ifnull(parent_place_id,''), ifnull(valid_from,'')
              HAVING count(*)>1)""")
        res["u8_status_distribution_json"] = json.dumps({
            r[0]: r[1] for r in con.execute(
                "SELECT status, count(*) FROM research_place_versions GROUP BY 1")},
            ensure_ascii=False)
    else:
        res["u8_rows_total"] = None
    return res


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="STKG U1-U8 upgrades on a private copy of the V2 release DB")
    ap.add_argument("--source", type=Path, default=SOURCE_DB)
    ap.add_argument("--sem", type=Path, default=SEMANTIC_DB)
    ap.add_argument("--target", type=Path, default=TARGET_DB)
    ap.add_argument("--rules", type=Path, default=CLOSURE3_RULES_PATH,
                    help="U6 三票选择性规则表（CLOSURE3_RULES.json，只读）")
    ap.add_argument("--corpus", type=Path, default=MASTER_DATA_CSV,
                    help="U8 语料（master_data.csv，只读扫描，sha256 入台账）")
    ap.add_argument("--rebuild-copy", action="store_true",
                    help="强制重新复制源库（源库仍只读）")
    ap.add_argument("--force", nargs="*", choices=UPGRADES, default=[],
                    help="强制重跑指定升级项（默认跳过台账中已完成项）")
    ap.add_argument("--only", nargs="*", choices=UPGRADES, default=None,
                    help="只运行指定升级项（其余跳过；单项重跑用，如 --only U7）")
    ap.add_argument("--verify-only", action="store_true", help="只跑完整性自检")
    ap.add_argument("--no-copy", action="store_true", help="不检查/不创建副本（目标已存在时用）")
    args = ap.parse_args(argv)

    if not args.no_copy and not args.verify_only:
        copy_info = ensure_copy(args.source, args.target, rebuild=args.rebuild_copy)
        measured("copy.source_sha256", copy_info["source_sha256"][:16] + "…")
        measured("copy.reused_existing", not copy_info["copied"])
    if not args.target.exists():
        raise SystemExit(f"target DB missing: {args.target}")

    con = connect(args.target, args.sem)
    ensure_ledger(con)

    # 基线计数：仅在副本尚无 BASELINE 台账时记录（=升级前状态），供自检对照
    if applied(con, "BASELINE") is None:
        baseline_counts = {
            "entities": q1(con, "SELECT count(*) FROM research_entities"),
            "assertions": q1(con, "SELECT count(*) FROM research_assertions"),
            "provenance": q1(con, "SELECT count(*) FROM research_assertion_provenance"),
            "event_frames": q1(con, "SELECT count(*) FROM research_event_frames"),
            "event_assertion_links": q1(con, "SELECT count(*) FROM research_event_assertion_links"),
            "culture_states": q1(con, "SELECT count(*) FROM research_culture_states"),
            "event_relations": q1(con, "SELECT count(*) FROM research_event_relations"),
            "evolution_transitions": q1(con, "SELECT count(*) FROM research_evolution_transitions"),
            "assertions_strict": q1(con,
                "SELECT count(*) FROM research_assertions WHERE research_tier='strict_semantic'"),
            "assertions_contextual": q1(con,
                "SELECT count(*) FROM research_assertions WHERE research_tier='contextual'"),
            "assertions_unresolved": q1(con,
                "SELECT count(*) FROM research_assertions WHERE research_tier='unresolved'"),
        }
        con.execute("BEGIN IMMEDIATE")
        record(con, "BASELINE", baseline_counts)
        con.commit()
    else:
        baseline_counts = applied(con, "BASELINE")["measured"]
        measured("baseline.loaded_from_ledger", json.dumps(baseline_counts, sort_keys=True))

    if not args.verify_only:
        runners = {"U1": upgrade_u1, "U2": upgrade_u2, "U3": upgrade_u3,
                   "U4": upgrade_u4, "U5": upgrade_u5,
                   "U6": lambda c: upgrade_u6(c, args.rules),
                   "U7": lambda c: upgrade_u7(c, rebuild="U7" in args.force),
                   "U8": lambda c: upgrade_u8(c, args.corpus, rebuild="U8" in args.force)}
        run_order = [k for k in UPGRADES if args.only is None or k in args.only]
        for key in run_order:
            prior = applied(con, key)
            if prior and key not in args.force:
                print(f"[{key}] SKIP (already applied at {prior['applied_at']}); "
                      f"current measured counts follow")
                current = {k: v for k, v in prior["measured"].items()}
                for k, v in current.items():
                    measured(f"{key}.{k}", v)
                continue
            print(f"[{key}] applying …")
            con.execute("BEGIN IMMEDIATE")
            try:
                m = runners[key](con)
                con.commit()
            except Exception:
                con.rollback()
                raise
            record(con, key, m)
            con.commit()
            for k, v in m.items():
                measured(f"{key}.{k}", v)

    print("[integrity] running full self-check …")
    con.execute("BEGIN")
    try:
        integ = verify_integrity(con, baseline_counts)
    finally:
        con.rollback()  # 自检只读
    flat = {"integrity." + k: v for k, v in integ.items()}
    for k, v in flat.items():
        measured(k, v)
    con.close()
    print("[done]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
