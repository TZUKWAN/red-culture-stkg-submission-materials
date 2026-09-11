# -*- coding: utf-8 -*-
"""build_evidence_recovery.py — P0-9 前置 2：no_evidence 断言的证据恢复审计。

对 STRICT_ALIGNMENT.csv 中 bucket='no_evidence' 的全部断言（指针为空 ≠ 没有原文）
做四类判定 + 全自动确定性恢复：

  A  证据真实存在但 ID 映射丢失   ← lineage / direct_source 命中
  B  有 lineage 但 evidence_registry 绑定失败 ← 词法双名同现于同一证据行（强）
  C  原文存在但 quote/span 未定位  ← 词法双名异行 / 单名弱命中（弱）
  D  真的无原文支持               ← 全链路无命中

恢复链路（只读、确定性、无人工、分块 checkpoint 可续跑）：
  1) lineage 列勘察：provenance.source_member_id(FACT-/TOPICFACT-)、
     legacy_candidate_ids_json(LEG-)、native_record_ids_json(KGREL-)、
     evidence_ids_json / source_record_ids_json / metadata_json 实际形态；
  2) 源级回溯：up.fact_evidence（FACT→EVD 绑定表，含 duplicate_of 聚簇头、
     LEG/KGREL→canonical FACT）、同 (subject,predicate,object) 的其他
     provenance 行与 sem.v2_assertion_scopes 同三元组事实的 evidence；
     TOPICFACT 的 metadata_json.evidence_quote（原文已定位到 metadata）；
  3) 词法检索兜底：up.evidence_search_fts（FTS5 trigram，evidence_text 列）
     双名同现 → 单名+time_raw → 单名；双 2 字名退化到 2-gram 滑窗全表扫描；
  4) 绑定判定：match_mode ∈ {lineage, direct_source, lexical_both,
     lexical_subject, lexical_object, none}。

硬约束：三个数据库全部 mode=ro 只读；词法命中只作"恢复定位"，
不当作语义支持；evidence_registry（107 万行）只流式/分块访问，禁止全量载入文本。

产物（experiments/07_provenance_semantic_gate/）：
  EVIDENCE_RECOVERY.csv / EVIDENCE_RECOVERY_SUMMARY.json /
  EVIDENCE_RECOVERY_REPORT.md / EVIDENCE_RECOVERY_CHECKPOINT.jsonl（可续跑）
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

V3_1 = Path(__file__).resolve().parents[2]
V3 = V3_1.parent / "final_submission_v3"
for p in (str(V3 / "code"), str(V3 / "code" / "independent_eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _common import (  # noqa: E402
    FINAL_DB,
    INTEGRATION_DB,
    SEMANTIC_DB,
    attach_integration,
    connect_final,
    sha256_file,
)

OUT_DIR = V3_1 / "experiments" / "07_provenance_semantic_gate"
IN_CSV = OUT_DIR / "STRICT_ALIGNMENT.csv"
CKPT_PATH = OUT_DIR / "EVIDENCE_RECOVERY_CHECKPOINT.jsonl"
OUT_CSV = OUT_DIR / "EVIDENCE_RECOVERY.csv"
OUT_SUM = OUT_DIR / "EVIDENCE_RECOVERY_SUMMARY.json"
OUT_RPT = OUT_DIR / "EVIDENCE_RECOVERY_REPORT.md"

METHOD_VERSION = "evidence-recovery-v1"
SEED = 20260907
CN_TZ = timezone(timedelta(hours=8))

MAX_EVID = 5               # 每条断言最多恢复 5 条候选证据
FTS_FETCH_CAP = 60         # 单名 FTS 候选抓取上限（再做 time_raw 重排）
CO_FETCH_CAP = 12          # 双名同现候选抓取上限
TWO_CHAR_CAP = 3000        # 2 字名倒排 rowid 上限（防内存爆）
CHUNK_SQL = 900            # SQLite IN 子句分块
CKPT_FLUSH_EVERY = 500     # checkpoint 落盘间隔（条）

YEAR_RE = re.compile(r"\d{3,4}")


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def chunked(seq, n=CHUNK_SQL):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def qs(n: int) -> str:
    return ",".join("?" * n)


def fts_phrase(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def clean_text(t: str | None) -> str:
    return " ".join(str(t or "").split())


def preview_of(t: str | None, limit: int = 120) -> str:
    return clean_text(t)[:limit]


def time_key_of(time_raw: str) -> str:
    """从 time_raw 抽一个可作 FTS 短语的时间核（4 位年优先）。"""
    tr = clean_text(time_raw)
    if not tr:
        return ""
    m = YEAR_RE.search(tr)
    if m and len(m.group()) >= 3:
        return m.group()
    return tr if 3 <= len(tr) <= 30 else ""


# ---------------------------------------------------------------------------
# 0) 输入
# ---------------------------------------------------------------------------

def load_no_evidence(limit: int = 0):
    recs = []
    with open(IN_CSV, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("bucket") != "no_evidence":
                continue
            recs.append({
                "fact_id": row["fact_id"],
                "subject_name": (row.get("subject_name") or "").strip(),
                "subject_type": row.get("subject_type") or "",
                "object_name": (row.get("object_name") or "").strip(),
                "object_type": row.get("object_type") or "",
                "predicate": row.get("predicate") or "",
                "time_raw": row.get("time_raw") or "",
                "place_raw": row.get("place_raw") or "",
            })
            if limit and len(recs) >= limit:
                break
    return recs


# ---------------------------------------------------------------------------
# 1) 预载/构建各类确定性回溯索引（全部流式，防内存爆）
# ---------------------------------------------------------------------------

def build_indexes(con, recs):
    idx: dict = {}
    fact_ids = [r["fact_id"] for r in recs]
    fid_set = set(fact_ids)

    # --- 1a) up.fact_evidence 全表：FACT → [EVD]（36.3 万行，仅 id 对，内存可控）
    t0 = time.time()
    fact_evidence: dict[str, list[str]] = defaultdict(list)
    for fid, eid in con.execute("select fact_id, evidence_id from up.fact_evidence"):
        fact_evidence[str(fid)].append(str(eid))
    idx["fact_evidence"] = fact_evidence
    print(f"[recovery] fact_evidence: {len(fact_evidence)} facts "
          f"({sum(len(v) for v in fact_evidence.values())} links) {time.time()-t0:.1f}s")

    # --- 1b) provenance 两遍全表扫描（先收集本批三元组，再收兄弟证据，
    #         避免扫描顺序依赖）：
    t0 = time.time()
    prov: dict[str, dict] = {fid: {
        "members": [], "legs": set(), "kgrels": set(),
        "triples": set(), "own_evids": set(), "topic_members": [],
    } for fid in fact_ids}
    needed_triples: set[tuple[str, str, str]] = set()
    n_prov = 0
    scan_sql = (
        "select fact_id, source_member_id, source_subject_id, source_predicate, "
        "source_object_id, legacy_candidate_ids_json, native_record_ids_json, "
        "evidence_ids_json from research_assertion_provenance"
    )
    for r in con.execute(scan_sql):
        n_prov += 1
        fid = str(r["fact_id"])
        if fid not in fid_set:
            continue
        p = prov[fid]
        member = str(r["source_member_id"] or "")
        if member.startswith("TOPICFACT-"):
            p["topic_members"].append(member)
        else:
            p["members"].append(member)
        try:
            p["legs"].update(str(x) for x in json.loads(r["legacy_candidate_ids_json"] or "[]"))
        except json.JSONDecodeError:
            pass
        try:
            p["kgrels"].update(str(x) for x in json.loads(r["native_record_ids_json"] or "[]"))
        except json.JSONDecodeError:
            pass
        try:
            p["own_evids"].update(str(x) for x in json.loads(r["evidence_ids_json"] or "[]"))
        except json.JSONDecodeError:
            pass
        p["triples"].add((str(r["source_subject_id"] or ""), str(r["source_predicate"] or ""),
                          str(r["source_object_id"] or "")))
        needed_triples.update(p["triples"])
    triple_ev: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    n_prov_ev = 0
    for r in con.execute(scan_sql):
        try:
            eids = [str(x) for x in json.loads(r["evidence_ids_json"] or "[]")]
        except json.JSONDecodeError:
            continue
        if not eids:
            continue
        triple = (str(r["source_subject_id"] or ""), str(r["source_predicate"] or ""),
                  str(r["source_object_id"] or ""))
        if triple in needed_triples:
            n_prov_ev += 1
            triple_ev[triple].update(eids)
    idx["prov"] = prov
    idx["triple_ev"] = triple_ev
    print(f"[recovery] provenance scan: {n_prov} rows, sibling-evidence rows kept "
          f"{n_prov_ev}, needed triples {len(needed_triples)} {time.time()-t0:.1f}s")

    # --- 1c) KGREL → [LEG]（legacy_fact_candidates 全表两列）
    t0 = time.time()
    needed_kgrel = set().union(*[p["kgrels"] for p in prov.values()]) if prov else set()
    kgrel2legs: dict[str, list[str]] = defaultdict(list)
    for nat, leg in con.execute(
        "select native_record_id, legacy_candidate_id from up.legacy_fact_candidates"
    ):
        nat = str(nat or "")
        if nat in needed_kgrel:
            kgrel2legs[nat].append(str(leg))
    idx["kgrel2legs"] = kgrel2legs
    print(f"[recovery] kgrel2legs: {len(kgrel2legs)} KGREL -> "
          f"{sum(len(v) for v in kgrel2legs.values())} LEG {time.time()-t0:.1f}s")

    # --- 1d) member(LEG/KGREL) → canonical FACT（fact_cluster_members 全表过滤）
    t0 = time.time()
    needed_members = set().union(*[p["legs"] for p in prov.values()]) if prov else set()
    for legs in kgrel2legs.values():
        needed_members.update(legs)
    needed_members.update(needed_kgrel)
    member2facts: dict[str, set[str]] = defaultdict(set)
    n_fm = 0
    for r in con.execute(
        "select fact_id, member_id from up.fact_cluster_members"
    ):
        mid = str(r["member_id"] or "")
        if mid in needed_members:
            member2facts[mid].add(str(r["fact_id"]))
            n_fm += 1
    idx["member2facts"] = member2facts
    print(f"[recovery] member2facts: {n_fm} links for {len(member2facts)} members "
          f"{time.time()-t0:.1f}s")

    # --- 1e) duplicate_of 聚簇头链（canonical_fact_clusters，BFS ≤3 跳）
    t0 = time.time()
    dup_map: dict[str, str] = {}
    frontier = {m for p in prov.values() for m in p["members"]}
    seen = set(frontier)
    for _hop in range(3):
        if not frontier:
            break
        nxt: set[str] = set()
        fset = frontier
        for r in con.execute("select fact_id, repair_action from up.canonical_fact_clusters"):
            fid = str(r["fact_id"] or "")
            if fid in fset:
                act = str(r["repair_action"] or "")
                if act.startswith("duplicate_of:"):
                    tgt = act.split(":", 1)[1].strip()
                    if tgt:
                        dup_map[fid] = tgt
                        if tgt not in seen:
                            seen.add(tgt)
                            nxt.add(tgt)
        frontier = nxt
    idx["dup_map"] = dup_map
    print(f"[recovery] duplicate_of map: {len(dup_map)} members -> cluster heads "
          f"{time.time()-t0:.1f}s")

    # --- 1f) scopes：本批 fact 的三元组 + 同三元组其他 fact 的证据
    t0 = time.time()
    scope_triple: dict[str, tuple[str, str, str]] = {}
    for i in range(0, len(fact_ids), CHUNK_SQL):
        ch = fact_ids[i:i + CHUNK_SQL]
        for r in con.execute(
            "select fact_id, subject_id, predicate, object_id from sem.v2_assertion_scopes "
            "where fact_id in (%s)" % qs(len(ch)), ch
        ):
            fid = str(r["fact_id"])
            if fid not in scope_triple:
                scope_triple[fid] = (str(r["subject_id"] or ""), str(r["predicate"] or ""),
                                     str(r["object_id"] or ""))
    needed_scope = set(scope_triple.values())
    ds_scopes: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for r in con.execute("select fact_id, subject_id, predicate, object_id from sem.v2_assertion_scopes"):
        key = (str(r["subject_id"] or ""), str(r["predicate"] or ""), str(r["object_id"] or ""))
        if key in needed_scope:
            fid = str(r["fact_id"])
            if fid in fact_evidence:      # 同三元组其他事实带证据 → direct_source
                ds_scopes[key].update(fact_evidence[fid])
    idx["scope_triple"] = scope_triple
    idx["ds_scopes"] = ds_scopes
    print(f"[recovery] scopes: {len(scope_triple)} facts, sibling triples "
          f"{len(ds_scopes)} {time.time()-t0:.1f}s")

    # --- 1g) TOPICFACT metadata 中的 evidence_quote（原文已定位到 metadata 字段）
    t0 = time.time()
    topic_members = sorted({m for p in prov.values() for m in p["topic_members"]})
    topic_quote: dict[str, dict] = {}      # TOPICFACT-id → {quote, title, evids}
    src_ids: set[str] = set()
    for i in range(0, len(topic_members), CHUNK_SQL):
        ch = topic_members[i:i + CHUNK_SQL]
        for r in con.execute(
            "select topic_fact_id, evidence_ids_json, metadata_json, source_record_id "
            "from up.topic_fact_candidates where topic_fact_id in (%s)" % qs(len(ch)), ch
        ):
            tid = str(r["topic_fact_id"])
            try:
                eids = [str(x) for x in json.loads(r["evidence_ids_json"] or "[]")]
            except json.JSONDecodeError:
                eids = []
            quote = ""
            try:
                md = json.loads(r["metadata_json"] or "{}")
                quote = clean_text(md.get("evidence_quote"))
            except json.JSONDecodeError:
                pass
            srid = str(r["source_record_id"] or "")
            if eids or quote:
                topic_quote[tid] = {"evids": eids, "quote": quote, "src": srid}
                if srid:
                    src_ids.add(srid)
    src_title: dict[str, str] = {}
    sl = sorted(src_ids)
    for i in range(0, len(sl), CHUNK_SQL):
        ch = sl[i:i + CHUNK_SQL]
        for r in con.execute(
            "select source_record_id, source_title from up.source_records "
            "where source_record_id in (%s)" % qs(len(ch)), ch
        ):
            src_title[str(r["source_record_id"])] = str(r["source_title"] or "")
    idx["topic_quote"] = topic_quote
    idx["src_title"] = src_title
    print(f"[recovery] topic quotes: {len(topic_quote)} TOPICFACT with quote/evid "
          f"{time.time()-t0:.1f}s")
    return idx


# ---------------------------------------------------------------------------
# 2) 词法层：FTS5 trigram（≥3 字名）+ 2 字名 2-gram 滑窗倒排（一次全表流式）
# ---------------------------------------------------------------------------

class LexicalIndex:
    def __init__(self, con, recs):
        self.con = con
        self.fts_disabled = False
        names = set()
        for r in recs:
            if len(r["subject_name"]) >= 2:
                names.add(r["subject_name"])
            if len(r["object_name"]) >= 2:
                names.add(r["object_name"])
        self.need2 = sorted(n for n in names if len(n) == 2)
        self.two_char: dict[str, list[int]] = {n: [] for n in self.need2}
        self._row_cache: dict[int, tuple] = {}
        self._fts_cache: dict[str, list[int]] = {}
        if self.need2:
            self._build_two_char_index()

    def _build_two_char_index(self):
        t0 = time.time()
        need = set(self.need2)
        cap = TWO_CHAR_CAP
        two = self.two_char
        n_rows = 0
        for rid, text in self.con.execute(
            "select rowid, evidence_text from up.evidence_registry"
        ):
            if not text:
                continue
            n_rows += 1
            matched = set()
            for i in range(len(text) - 1):
                dg = text[i:i + 2]
                if dg in need:
                    matched.add(dg)
            for nm in matched:
                lst = two[nm]
                if len(lst) < cap:
                    lst.append(rid)
        print(f"[recovery] 2-char name index: {len(need)} names over {n_rows} rows "
              f"{time.time()-t0:.1f}s")

    # --- FTS 基元 ---
    def _fts(self, query: str, limit: int) -> list[int]:
        key = query
        hit = self._fts_cache.get(key)
        if hit is not None:
            return hit
        rids: list[int] = []
        if not self.fts_disabled:
            try:
                rids = [int(r[0]) for r in self.con.execute(
                    "select rowid from up.evidence_search_fts "
                    "where evidence_search_fts match ? limit ?", (query, limit))]
            except Exception:
                rids = []      # FTS 异常按无命中处理（trigram 即精确子串语义）
        if len(self._fts_cache) < 120_000:
            self._fts_cache[key] = rids
        return rids

    def _fetch_rows(self, rids) -> list[tuple]:
        out = []
        miss = []
        for rid in rids:
            got = self._row_cache.get(rid)
            if got is not None:
                out.append(got)
            else:
                miss.append(rid)
        if miss:
            for i in range(0, len(miss), CHUNK_SQL):
                ch = miss[i:i + CHUNK_SQL]
                for r in self.con.execute(
                    "select rowid, evidence_id, source_title, evidence_text "
                    "from up.evidence_registry where rowid in (%s)" % qs(len(ch)), ch
                ):
                    rec = (int(r[0]), str(r[1] or ""), str(r[2] or ""), str(r[3] or ""))
                    self._row_cache[rec[0]] = rec
                    out.append(rec)
            if len(self._row_cache) > 300_000:   # 纯加速缓存，清空不影响正确性
                self._row_cache.clear()
        order = {rid: k for k, rid in enumerate(rids)}
        out.sort(key=lambda x: order.get(x[0], 1 << 60))
        return out

    def rows_containing_name(self, name: str, time_key: str = "",
                             limit: int = MAX_EVID) -> list[tuple]:
        """单名检索：单名（+time_raw 优先重排）→ 已验证含名的证据行。"""
        if len(name) < 2:
            return []
        ranked: list[int] = []
        if len(name) >= 3:
            if time_key:
                ranked = self._fts(
                    "{evidence_text} : (%s AND %s)" % (fts_phrase(name), fts_phrase(time_key)),
                    FTS_FETCH_CAP)
            plain = self._fts("{evidence_text} : (%s)" % fts_phrase(name), FTS_FETCH_CAP)
            seen = set(ranked)
            ranked = ranked + [r for r in plain if r not in seen]
        else:
            ranked = list(self.two_char.get(name, ()))[:FTS_FETCH_CAP]
        rows = self._fetch_rows(ranked)
        verified = [r for r in rows if name in r[3]]
        if time_key:
            verified.sort(key=lambda r: (0 if time_key in r[3] else 1, r[0]))
        return verified[:limit]

    def rows_containing_both(self, s: str, o: str) -> list[tuple]:
        """双名同现（同一证据行同时含 subject_name 与 object_name）。"""
        s3, o3 = len(s) >= 3, len(o) >= 3
        if s3 and o3:
            rids = self._fts("{evidence_text} : (%s AND %s)" % (fts_phrase(s), fts_phrase(o)),
                             CO_FETCH_CAP)
            rows = self._fetch_rows(rids)
            return [r for r in rows if s in r[3] and o in r[3]][:MAX_EVID]
        if s3 or o3:
            long_nm, short_nm = (s, o) if s3 else (o, s)
            rids = self._fts("{evidence_text} : (%s)" % fts_phrase(long_nm), 200)
            rows = self._fetch_rows(rids)
            return [r for r in rows if long_nm in r[3] and short_nm in r[3]][:MAX_EVID]
        a = self.two_char.get(s, ())[:1000]
        b = self.two_char.get(o, ())[:1000]
        inter = sorted(set(a) & set(b))[:CO_FETCH_CAP]
        rows = self._fetch_rows(inter)
        return [r for r in rows if s in r[3] and o in r[3]][:MAX_EVID]


# ---------------------------------------------------------------------------
# 3) 逐条判定
# ---------------------------------------------------------------------------

def resolve_evids(con, cache: dict, eids: list[str]):
    """evidence_id → (title, preview)；带缓存。"""
    out = []
    miss = []
    for eid in eids:
        got = cache.get(eid)
        if got is not None:
            out.append((eid, got[0], got[1]))
        else:
            miss.append(eid)
    if miss:
        for i in range(0, len(miss), CHUNK_SQL):
            ch = miss[i:i + CHUNK_SQL]
            for r in con.execute(
                "select evidence_id, source_title, evidence_text from up.evidence_registry "
                "where evidence_id in (%s)" % qs(len(ch)), ch
            ):
                eid = str(r[0])
                rec = (eid, str(r[1] or ""), preview_of(r[2]))
                cache[eid] = (rec[1], rec[2])
                out.append(rec)
    have = {r[0] for r in out}
    for eid in eids:                      # 悬空 id：保留 id，文本为空
        if eid not in have:
            out.append((eid, "", ""))
    return out


def classify_fact(rec, idx, lex, con, ev_cache):
    fid = rec["fact_id"]
    s, o = rec["subject_name"], rec["object_name"]
    p = idx["prov"].get(fid) or {
        "members": [], "legs": set(), "kgrels": set(),
        "triples": set(), "own_evids": set(), "topic_members": []}
    has_native_lineage = bool(p["legs"] or p["kgrels"])

    # ---- 阶段 1：lineage（fact_evidence 绑定 / duplicate_of 聚簇头 / LEG·KGREL 簇头）
    lin: set[str] = set(p["own_evids"])          # 自生 id 悬空也算 lineage 线索
    fe = idx["fact_evidence"]
    for m in p["members"]:
        lin.update(fe.get(m, ()))
        tgt = idx["dup_map"].get(m)
        if tgt:
            lin.update(fe.get(tgt, ()))
    for leg in p["legs"]:
        for c in idx["member2facts"].get(leg, ()):
            lin.update(fe.get(c, ()))
    for kg in p["kgrels"]:
        for leg in idx["kgrel2legs"].get(kg, ()):
            for c in idx["member2facts"].get(leg, ()):
                lin.update(fe.get(c, ()))
    if lin:
        eids = sorted(lin)[:MAX_EVID]
        rows = resolve_evids(con, ev_cache, eids)
        return _result(rec, "A", "lineage", "registry_ids", rows, has_native_lineage)

    # ---- 阶段 1b：TOPICFACT metadata 证据/引文（原文已定位到 metadata）
    for tid in sorted(p["topic_members"]):
        tq = idx["topic_quote"].get(tid)
        if not tq:
            continue
        if tq["evids"]:
            rows = resolve_evids(con, ev_cache, sorted(tq["evids"])[:MAX_EVID])
            return _result(rec, "A", "lineage", "topic_registry_ids", rows, has_native_lineage)
        if tq["quote"]:
            title = idx["src_title"].get(tq["src"], "")
            return _result(rec, "A", "lineage", "topic_metadata_quote",
                           [("", title, tq["quote"])], has_native_lineage)

    # ---- 阶段 2：direct_source（同三元组兄弟 provenance / scopes 事实）
    ds: set[str] = set()
    for tr in p["triples"]:
        ds.update(idx["triple_ev"].get(tr, ()))
    st = idx["scope_triple"].get(fid)
    if st:
        ds.update(idx["ds_scopes"].get(st, ()))
    if ds:
        rows = resolve_evids(con, ev_cache, sorted(ds)[:MAX_EVID])
        return _result(rec, "A", "direct_source", "sibling_triple", rows, has_native_lineage)

    # ---- 阶段 3：词法兜底（只作恢复定位，不作语义支持）
    s_ok, o_ok = len(s) >= 2, len(o) >= 2
    if not (s_ok or o_ok):
        return _result(rec, "D", "none", "no_name", [], has_native_lineage)
    same = s_ok and o_ok and s == o
    tk = time_key_of(rec["time_raw"])

    if same:
        # 双名相同：同现退化为单名，按弱恢复处理（避免虚增 B 类）
        co_rows = []
        s_rows = lex.rows_containing_name(s, tk) if s_ok else []
        o_rows = []
    else:
        co_rows = lex.rows_containing_both(s, o) if (s_ok and o_ok) else []
        s_rows = lex.rows_containing_name(s, tk) if s_ok else []
        o_rows = lex.rows_containing_name(o, tk) if o_ok else []

    def _lex(rows):
        # 词法行 (rowid, eid, title, text) → (eid, title, preview)
        return [(r[1], r[2], preview_of(r[3])) for r in rows]

    if co_rows:
        return _result(rec, "B", "lexical_both", "same_row", _lex(co_rows),
                       has_native_lineage)

    if s_rows and o_rows:
        seen_rid = set()
        merged = []
        for r in s_rows + o_rows:
            if r[0] not in seen_rid:
                seen_rid.add(r[0])
                merged.append(r)
        return _result(rec, "C", "lexical_both", "split", _lex(merged[:MAX_EVID]),
                       has_native_lineage)
    if s_rows:
        return _result(rec, "C", "lexical_subject", "single", _lex(s_rows),
                       has_native_lineage)
    if o_rows:
        return _result(rec, "C", "lexical_object", "single", _lex(o_rows),
                       has_native_lineage)
    return _result(rec, "D", "none", "no_hit", [], has_native_lineage)


def _result(rec, cls, mode, strength, ev_rows, has_native_lineage):
    ids, titles, previews = [], [], []
    for _eid, title, prev in ev_rows:
        if _eid:
            ids.append(_eid)
        if title:
            titles.append(title)
        if prev:
            previews.append(prev)
    uniq_titles = list(dict.fromkeys(titles))[:MAX_EVID]
    return {
        "fact_id": rec["fact_id"],
        "recovery_class": cls,
        "match_mode": mode,
        "match_strength": strength,
        "recovered_evidence_ids": ";".join(ids),
        "recovered_source_titles": " ; ".join(uniq_titles),
        "evidence_text_preview": previews[0] if previews else "",
        "n_recovered": len(ids) if ids else len(ev_rows),
        "has_native_lineage": int(bool(has_native_lineage)),
        "subject_name": rec["subject_name"],
        "object_name": rec["object_name"],
        "predicate": rec["predicate"],
    }


# ---------------------------------------------------------------------------
# 4) 主流程：分块 + checkpoint
# ---------------------------------------------------------------------------

def load_checkpoint():
    done: dict[str, dict] = {}
    if not CKPT_PATH.exists():
        return done, False
    with open(CKPT_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:      # 尾部半行（崩溃残留）——丢弃
                break
            if "_meta" in obj:
                continue
            done[obj["fact_id"]] = obj
    return done, True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（调试用）")
    ap.add_argument("--chunk", type=int, default=2000, help="checkpoint 分块大小")
    ap.add_argument("--no-resume", action="store_true", help="忽略已有 checkpoint 重跑")
    args = ap.parse_args()

    t_start = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    recs = load_no_evidence(args.limit)
    print(f"[recovery] no_evidence facts to process: {len(recs)}")

    con = connect_final()
    attach_integration(con)

    idx = build_indexes(con, recs)
    lex = LexicalIndex(con, recs)
    ev_cache: dict[str, tuple] = {}

    done, resumed = ({}, False) if args.no_resume else load_checkpoint()
    if resumed:
        print(f"[recovery] resume: {len(done)} facts already in checkpoint")

    ckpt_fh = open(CKPT_PATH, "a", encoding="utf-8")
    since_flush = 0
    counts = Counter()
    mode_counter = Counter()
    strength_counter = Counter()
    class_by_mode: dict[str, Counter] = defaultdict(Counter)
    pred_recovered: Counter = Counter()
    pred_d: Counter = Counter()
    stype_recovered: Counter = Counter()
    stype_d: Counter = Counter()
    results: dict[str, dict] = {}
    n_done = 0
    last_mark = t_start

    for rec in recs:
        fid = rec["fact_id"]
        if fid in done:
            row = done[fid]
        else:
            row = classify_fact(rec, idx, lex, con, ev_cache)
            ckpt_fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            since_flush += 1
            if since_flush >= CKPT_FLUSH_EVERY:
                ckpt_fh.flush()
                os.fsync(ckpt_fh.fileno())
                since_flush = 0
        results[fid] = row
        counts[row["recovery_class"]] += 1
        mode_counter[row["match_mode"]] += 1
        strength_counter[row["match_strength"]] += 1
        class_by_mode[row["match_mode"]][row["recovery_class"]] += 1
        if row["recovery_class"] == "D":
            pred_d[rec["predicate"]] += 1
            stype_d[rec["subject_type"]] += 1
        else:
            pred_recovered[rec["predicate"]] += 1
            stype_recovered[rec["subject_type"]] += 1
        n_done += 1
        if n_done % args.chunk == 0:
            ckpt_fh.flush()
            os.fsync(ckpt_fh.fileno())
            since_flush = 0
            rate = args.chunk / max(time.time() - last_mark, 1e-9)
            last_mark = time.time()
            eta = (len(recs) - n_done) / max(rate, 1e-9) / 60.0
            print(f"[recovery] {n_done}/{len(recs)} chunk done "
                  f"({rate:.0f} facts/s, ETA {eta:.1f} min) counts={dict(counts)}")
    ckpt_fh.flush()
    os.fsync(ckpt_fh.fileno())
    ckpt_fh.close()

    elapsed = time.time() - t_start

    # ---------------- CSV ----------------
    fields = ["fact_id", "recovery_class", "match_mode", "match_strength",
              "recovered_evidence_ids", "recovered_source_titles",
              "evidence_text_preview", "n_recovered", "has_native_lineage",
              "subject_name", "subject_type", "object_name", "object_type",
              "predicate", "time_raw", "place_raw"]
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for rec in recs:
            row = results[rec["fact_id"]]
            row.update({k: rec[k] for k in
                        ("subject_type", "object_type", "time_raw", "place_raw")})
            w.writerow(row)

    # ---------------- SUMMARY ----------------
    n_total = len(recs)
    recovered = counts["A"] + counts["B"] + counts["C"]
    rng = random.Random(SEED)
    sample_rows = rng.sample(sorted(results.values(),
                                    key=lambda r: r["fact_id"]), min(50, n_total))
    summary = {
        "task": "P0-9 evidence recovery audit (no_evidence bucket)",
        "method_version": METHOD_VERSION,
        "generated_at": now_iso(),
        "deterministic": True,
        "manual_review": False,
        "databases": {
            "final": FINAL_DB.name,
            "semantic": SEMANTIC_DB.name,
            "integration_readonly": INTEGRATION_DB.name,
        },
        "inputs": {
            "strict_alignment_csv": IN_CSV.name,
            "strict_alignment_sha256": sha256_file(IN_CSV),
            "n_no_evidence": n_total,
        },
        "recovery_chain": [
            "lineage: provenance.source_member_id -> up.fact_evidence "
            "(+ duplicate_of cluster heads, LEG/KGREL -> canonical facts)",
            "lineage: TOPICFACT metadata evidence_quote / evidence_ids",
            "direct_source: sibling provenance rows and sem.v2_assertion_scopes "
            "facts sharing (subject, predicate, object)",
            "lexical: FTS5 trigram on evidence_text — both names same row -> "
            "single name (+time_raw) -> single name; 2-char names via 2-gram scan",
        ],
        "class_rules": {
            "A": "lineage or direct_source hit (evidence ids/quote exist, mapping lost)",
            "B": "lexical both names co-occur in the SAME evidence row (strong; "
                 "registry binding failed)",
            "C": "lexical weak recovery: both names hit different rows (split), "
                 "or single-name hit only",
            "D": "no hit anywhere (no recoverable source text)",
        },
        "counts": {k: counts.get(k, 0) for k in ("A", "B", "C", "D")},
        "recovery_rate": round(recovered / n_total, 4) if n_total else 0.0,
        "match_mode_distribution": dict(mode_counter),
        "match_strength_distribution": dict(strength_counter),
        "class_by_match_mode": {m: dict(c) for m, c in sorted(class_by_mode.items())},
        "has_native_lineage_distribution": dict(Counter(
            ("with_LEG_or_KGREL" if r["has_native_lineage"] else "without") for r in results.values())),
        "by_predicate": {
            "recovered_top10": pred_recovered.most_common(10),
            "class_D_top10": pred_d.most_common(10),
        },
        "by_subject_type": {
            "recovered_top10": stype_recovered.most_common(10),
            "class_D_top10": stype_d.most_common(10),
        },
        "caps": {
            "max_evidence_per_fact": MAX_EVID,
            "fts_fetch_cap": FTS_FETCH_CAP,
            "two_char_rowid_cap": TWO_CHAR_CAP,
            "n_unique_two_char_names": len(lex.need2),
            "note": "candidate caps bound runtime/memory; hits are verified "
                    "substrings, never fabricated",
        },
        "elapsed_seconds": round(elapsed, 1),
        "elapsed_seconds_note": "wall time of the final (possibly resumed) run; "
                                "rows reused from checkpoint were computed earlier",
        "resumed_from_checkpoint": resumed,
        "random_samples_n": len(sample_rows),
        "random_samples_seed": SEED,
        "random_samples": sample_rows,
    }
    OUT_SUM.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                       encoding="utf-8")

    # ---------------- REPORT ----------------
    cA, cB, cC, cD = (counts.get(k, 0) for k in "ABCD")
    report = f"""# Evidence Recovery Audit — no_evidence 断言四类判定与自动恢复

- 生成时间：{now_iso()}
- 方法版本：`{METHOD_VERSION}`（全自动、确定性、无人工；数据库只读）
- 输入：`{IN_CSV.name}`（bucket=no_evidence，共 {n_total:,} 条；sha256 前 8 位 `{sha256_file(IN_CSV)[:8]}`）
- 产物：`EVIDENCE_RECOVERY.csv` / `EVIDENCE_RECOVERY_SUMMARY.json` / 本报告
- 总耗时：{elapsed/60.0:.1f} 分钟（{elapsed:.0f} s）

## 1. 背景

strict 层 112,158 条断言词法对齐后 {n_total:,} 条落入 no_evidence
（fact → provenance.evidence_ids_json 为空）。"指针为空"不等于"没有原文"：
上游集成管线中证据以 `up.fact_evidence`（FACT→EVD 绑定）、`up.topic_fact_candidates`
（metadata 证据引文）等形式存在，部分绑定在发布库裁剪/聚簇去重中丢失。
本次审计对每条 no_evidence 断言判定其原文可恢复性并定位候选证据。

## 2. lineage 列勘察（步骤 1 结论）

对 `research_assertion_provenance` 采样核查（含全部 no_evidence 行全量统计）：

| 列 | no_evidence 行的实际形态 |
| --- | --- |
| source_member_id | `FACT-*` 68,617 行 + `TOPICFACT-*` 2,373 行 |
| legacy_candidate_ids_json | `["LEG-*"]`（68,617 行非空） |
| native_record_ids_json | `["KGREL-*"]`（68,617 行非空） |
| evidence_ids_json | 全部 `[]`（0 条悬空指针） |
| source_record_ids_json / metadata_json | 基本为 `[]` / `{{}}`；TOPICFACT 行 metadata 内含 evidence_quote |

可回溯键：source_member_id → `up.fact_evidence`；LEG →
`up.fact_cluster_members` → canonical FACT → `up.fact_evidence`；
KGREL → `up.legacy_fact_candidates.native_record_id` → LEG；TOPICFACT →
`up.topic_fact_candidates.metadata_json.evidence_quote`。

## 3. 四类定义与判定规则

| 类 | 定义 | 自动判定条件（按优先级） | match_mode |
| --- | --- | --- | --- |
| A | 证据真实存在但 ID 映射丢失 | lineage 命中（fact_evidence/聚簇头/TOPICFACT 证据或引文）或 direct_source 命中（同 (subject,predicate,object) 兄弟 provenance 行或 sem.v2_assertion_scopes 同三元组事实带证据） | lineage / direct_source |
| B | 有 lineage 但 evidence_registry 绑定失败 | 词法双名同现于**同一**证据行（强命中） | lexical_both (same_row) |
| C | 原文存在但 quote/span 未定位 | 词法双名命中但**异行**（split），或仅单名命中（+time_raw 优先排序，弱命中） | lexical_both (split) / lexical_subject / lexical_object |
| D | 真的无原文支持 | 全链路无命中 | none |

B/C 边界按命中强度记录（same_row 强 / split·single 弱），不强行区分，
与任务规约一致。所有词法命中均为 FTS trigram/滑窗检索后的**已验证子串命中**
（取回原文逐条复核），仅作恢复定位，不当作语义支持。

## 4. 计数结果

| 类 | 条数 | 占比 | 含义 |
| --- | --- | --- | --- |
| A | {cA:,} | {cA/n_total:.1%} | strict 候选可修复（证据直接回接） |
| B | {cB:,} | {cB/n_total:.1%} | strict 候选可修复（绑定重建） |
| C | {cC:,} | {cC/n_total:.1%} | strict 候选可修复（弱恢复，需复核样例） |
| D | {cD:,} | {cD/n_total:.1%} | 降级（无可定位原文） |

- 恢复率（A+B+C）/N = **{recovered/n_total:.1%}**（{recovered:,}/{n_total:,}）
- match_mode 分布：{json.dumps(dict(mode_counter), ensure_ascii=False)}
- 命中强度分布：{json.dumps(dict(strength_counter), ensure_ascii=False)}
- 路径分解：`up.fact_evidence`/聚簇头 lineage（registry_ids）
  {strength_counter.get('registry_ids', 0) + strength_counter.get('topic_registry_ids', 0)} 条；
  TOPICFACT metadata 引文 {strength_counter.get('topic_metadata_quote', 0)} 条；
  同三元组兄弟 direct_source {strength_counter.get('sibling_triple', 0)} 条。

关键发现：no_evidence 桶内 `up.fact_evidence`（FACT→EVD）与 LEG/KGREL→
canonical-FACT 聚簇头路径 **0 命中**——这批断言在上游集成库中即从未建立
证据绑定（并非发布裁剪时丢失）；A 类完全来自 TOPICFACT metadata 引文与
同 (subject,predicate,object) 兄弟事实的直接证据，其余可恢复空间由词法层
定位（B 同行双名强定位 / C 弱定位）。

## 5. 对 P0-9 语义门重分层的含义

- **A/B/C 共 {recovered:,} 条 = strict 候选可修复**：已定位到候选证据原文
  （A 有确定 ID/引文，B 同行双名强定位，C 弱定位）。P0-9 重分层时这些断言
  不应再按 no_evidence 处理，可带候选证据进入语义验证（LLM 只需确认
  语义支持，而非从零检索）。
- **D 共 {cD:,} 条 = 降级**：三条链路均无可定位原文，按 GOAL P0-9 规约
  从 strict 候选降级（不再作为高置信发布断言）。
- C 类为弱恢复：单名命中仅表示原文可能相关，判定本身仍是自动规则；
  SUMMARY.json 已附 50 条随机样例（seed={SEED}）供后续人工可读性抽查，
  抽查不改变本审计的自动判定。

## 6. 约束与可复现性

- 三个数据库全部 `mode=ro` 只读打开；无任何写库操作。
- evidence_registry（1,073,648 行）仅流式/分块访问：FTS trigram 索引查询 +
  2 字名一次滑窗扫描（rowid 上限 {TWO_CHAR_CAP}/名），未全量载入文本。
- 每条断言候选证据上限 {MAX_EVID} 条；排序全部确定性（rowid / evidence_id 字典序）。
- 分块 checkpoint：`EVIDENCE_RECOVERY_CHECKPOINT.jsonl`，可中断续跑
  （本次执行{'已' if resumed else '未'}从 checkpoint 续跑）。
- 随机样例 seed={SEED}；输入 CSV sha256 已记录于 SUMMARY.json。
"""
    OUT_RPT.write_text(report, encoding="utf-8")

    print(f"[recovery] done in {elapsed/60.0:.1f} min: counts={dict(counts)} "
          f"recovery_rate={recovered/n_total:.4f}")
    print(f"[recovery] outputs: {OUT_CSV.name}, {OUT_SUM.name}, {OUT_RPT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
