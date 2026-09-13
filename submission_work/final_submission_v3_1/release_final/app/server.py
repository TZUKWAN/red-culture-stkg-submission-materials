# -*- coding: utf-8 -*-
"""server.py — FINAL STKG 图谱浏览器后端（Reviewer Mode）。

零第三方依赖（纯 Python 标准库），直接只读最终 SQLite：
    python server.py --port 8080
所有路径相对本包根（release_final/app），无绝对路径、无密钥、无外部服务。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sqlite3
import sys
import threading
from collections import deque
from pathlib import Path

# 冻结（PyInstaller onefile）时以 EXE 所在目录为包根；源码运行时以本文件定位。
if getattr(sys, "frozen", False):
    PKG = Path(sys.executable).resolve().parent      # release_final/
    APP = PKG / "app"
else:
    APP = Path(__file__).resolve().parent
    PKG = APP.parent
DB = PKG / "data" / "red_culture_stkg_final.sqlite"
STATIC = APP / "static"
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".json": "application/json",
        ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon"}


def rows_to_dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


class GraphStore:
    """只读存储 + 惰性 strict 邻接（最短路用）。"""

    def __init__(self, db_path: Path):
        self.con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True,
                                   check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self._adj = None
        self.db_path = db_path

    @property
    def adj(self) -> dict[str, list[tuple[str, str, str]]]:
        if self._adj is None:
            a: dict[str, list[tuple[str, str, str]]] = {}
            cur = self.con.execute(
                "SELECT fact_id, subject_id, object_id, predicate FROM research_assertions "
                "WHERE research_tier='strict_semantic' AND subject_id IS NOT NULL "
                "AND object_id IS NOT NULL")
            for fid, s, o, p in cur.fetchall():
                a.setdefault(s, []).append((o, fid, p))
                a.setdefault(o, []).append((s, fid, p))
            self._adj = a
        return self._adj

    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return rows_to_dicts(self.con.execute(sql, args))


STORE: GraphStore | None = None


# ---------------------------------------------------------------------------
# API handlers
# ---------------------------------------------------------------------------

def api_stats(req) -> dict:
    s = STORE.q("SELECT research_tier, COUNT(*) n FROM research_assertions "
                "GROUP BY research_tier")
    tiers = {r["research_tier"]: r["n"] for r in s}
    ent = STORE.q("SELECT COUNT(*) n FROM research_entities")[0]["n"]
    frames = STORE.q("SELECT COUNT(*) n FROM research_event_frames")[0]["n"]
    states = STORE.q("SELECT COUNT(*) n FROM research_culture_states")[0]["n"]
    gate = STORE.q("SELECT final_tier, COUNT(*) n FROM evidence_gate_tier GROUP BY final_tier")
    gate_tiers = {r["final_tier"]: r["n"] for r in gate}
    tmin = STORE.q("SELECT MIN(time_start) m FROM research_assertions "
                   "WHERE time_start IS NOT NULL AND time_start != ''")[0]["m"]
    tmax = STORE.q("SELECT MAX(time_start) m FROM research_assertions "
                   "WHERE time_start IS NOT NULL AND time_start != ''")[0]["m"]
    preds = STORE.q("SELECT predicate, COUNT(*) n FROM research_assertions "
                    "WHERE research_tier='strict_semantic' GROUP BY predicate "
                    "ORDER BY n DESC LIMIT 30")
    return {"entities": ent, "assertions": sum(tiers.values()),
            "tiers": tiers, "gate_universe": gate_tiers, "event_frames": frames,
            "culture_states": states, "time_min": tmin, "time_max": tmax,
            "predicates": preds}


def api_search(req) -> dict:
    qs = (req["params"].get("q") or "").strip()
    types = [t for t in (req["params"].get("types") or "").split(",") if t]
    limit = min(int(req["params"].get("limit") or 20), 50)
    if not qs:
        return {"results": []}
    like = f"%{qs}%"
    cond = "(canonical_name LIKE ? OR aliases_json LIKE ?)"
    args: list = [like, like]
    if types:
        cond += " AND entity_type IN (%s)" % ",".join("?" * len(types))
        args += types
    # 两段式：内层先截断候选（避免单字查询命中数万行 × 相关子查询），
    # 只对最终 limit 行计算 strict 度（索引探针，毫秒级）。
    inner = ("SELECT entity_id, canonical_name, entity_type, aliases_json, "
             "integrated_member_count AS mc FROM research_entities WHERE " + cond +
             " ORDER BY CASE WHEN canonical_name LIKE ? THEN 0 ELSE 1 END, "
             "integrated_member_count DESC, length(canonical_name) LIMIT 400")
    rows = STORE.q(
        "SELECT entity_id, canonical_name, entity_type, aliases_json FROM (" + inner + ") "
        "ORDER BY mc DESC, length(canonical_name) LIMIT ?",
        tuple(args + [qs + "%", limit]))
    if rows:
        ids = [r["entity_id"] for r in rows]
        deg_rows = STORE.q(
            "SELECT x.entity_id AS eid, COUNT(a.fact_id) AS d FROM "
            "(SELECT entity_id FROM research_entities WHERE entity_id IN (%s)) x "
            "LEFT JOIN research_assertions a ON a.research_tier='strict_semantic' "
            "AND (a.subject_id=x.entity_id OR a.object_id=x.entity_id) "
            "GROUP BY x.entity_id" % ",".join("?" * len(ids)), tuple(ids))
        deg = {r["eid"]: r["d"] for r in deg_rows}
    else:
        deg = {}
    for r in rows:
        r["degree"] = deg.get(r["entity_id"], 0)
    rows.sort(key=lambda r: (-r["degree"], len(r["canonical_name"])))
    return {"results": rows}


def api_entity(req) -> dict:
    eid = req["path"].split("/")[-1]
    ent = STORE.q("SELECT * FROM research_entities WHERE entity_id=?", (eid,))
    if not ent:
        return {"error": "not found"}, 404
    e = ent[0]
    deg = STORE.q(
        "SELECT COUNT(*) n FROM research_assertions WHERE research_tier='strict_semantic' "
        "AND (subject_id=? OR object_id=?)", (eid, eid))[0]["n"]
    times = STORE.q(
        "SELECT MIN(time_start) t0, MAX(time_end) t1 FROM research_assertions "
        "WHERE research_tier='strict_semantic' AND (subject_id=? OR object_id=?) "
        "AND COALESCE(time_start,'')!=''", (eid, eid))[0]
    return {"entity": e, "degree": deg, "active_from": times["t0"], "active_to": times["t1"]}


def api_neighbors(req) -> dict:
    eid = req["path"].split("/")[-1]
    p = req["params"]
    tiers = [t for t in (p.get("tiers") or "strict_semantic").split(",") if t]
    types = [t for t in (p.get("types") or "").split(",") if t]
    preds = [t for t in (p.get("preds") or "").split(",") if t]
    t0, t1 = p.get("t0") or "", p.get("t1") or ""
    limit = min(int(p.get("limit") or 250), 800)
    cond = "(a.subject_id=? OR a.object_id=?) AND a.research_tier IN (%s)" % \
        ",".join("?" * len(tiers))
    args: list = [eid, eid, *tiers]
    if types:
        cond += " AND se.entity_type IN (%s) AND oe.entity_type IN (%s)" % (
            ",".join("?" * len(types)), ",".join("?" * len(types)))
        args += types + types
    if preds:
        cond += " AND a.predicate IN (%s)" % ",".join("?" * len(preds))
        args += preds
    if t0:
        cond += " AND COALESCE(a.time_start, a.time_end, '') >= ?"
        args.append(t0)
    if t1:
        cond += " AND COALESCE(a.time_end, a.time_start, '') <= ?"
        args.append(t1)
    edges = STORE.q(
        "SELECT a.fact_id, a.subject_id, a.subject_name, a.subject_type, "
        "a.object_id, a.object_name, a.object_type, a.predicate, a.research_tier, "
        "a.time_start, a.time_end, a.place_raw "
        "FROM research_assertions a "
        "JOIN research_entities se ON se.entity_id=a.subject_id "
        "JOIN research_entities oe ON oe.entity_id=a.object_id "
        "WHERE " + cond + " LIMIT ?", tuple(args + [limit]))
    return {"edges": edges, "truncated": len(edges) >= limit}


def api_evidence(req) -> dict:
    fid = req["path"].split("/")[-1]
    a = STORE.q("SELECT * FROM research_assertions WHERE fact_id=?", (fid,))
    if not a:
        return {"error": "not found"}, 404
    prov = STORE.q("SELECT provenance_kind, source_table, source_record_id, "
                   "evidence_ids_json, native_record_ids_json "
                   "FROM research_assertion_provenance WHERE fact_id=? LIMIT 6", (fid,))
    v = STORE.q("SELECT * FROM gate_verdict_details WHERE fact_id=?", (fid,))
    gate = STORE.q("SELECT gate_method, semantic_support, final_tier "
                   "FROM evidence_gate_tier WHERE fact_id=?", (fid,))
    return {"assertion": a[0], "provenance": prov,
            "verdict": v[0] if v else None,
            "gate": gate[0] if gate else None}


def api_timeline(req) -> dict:
    eid = req["path"].split("/")[-1]
    p = req["params"]
    tier = p.get("tier") or "strict_semantic"
    rows = STORE.q(
        "SELECT fact_id, subject_id, subject_name, object_id, object_name, predicate, "
        "research_tier, time_start, time_end, time_raw, place_raw "
        "FROM research_assertions WHERE research_tier=? AND (subject_id=? OR object_id=?) "
        "AND COALESCE(time_start,time_end,'')!='' ORDER BY COALESCE(time_start,time_end) "
        "LIMIT 400", (tier, eid, eid))
    frames = STORE.q(
        "SELECT DISTINCT f.event_id, f.event_name, f.observed_time_start, "
        "f.observed_time_end, f.frame_status FROM research_event_frames f "
        "JOIN research_event_assertion_links l ON l.event_id=f.event_id "
        "WHERE (l.counterpart_id=? OR l.fact_id IN "
        "(SELECT fact_id FROM research_assertions WHERE subject_id=? OR object_id=?)) "
        "LIMIT 80", (eid, eid, eid))
    return {"items": rows, "frames": frames}


def api_path(req) -> dict:
    src, dst = req["params"].get("src"), req["params"].get("dst")
    if not src or not dst:
        return {"error": "src/dst required"}, 400
    adj = STORE.adj
    if src not in adj or dst not in adj:
        return {"path": [], "edges": []}
    prev: dict[str, tuple[str, str]] = {src: ("", "")}
    dq = deque([src])
    while dq:
        u = dq.popleft()
        if u == dst:
            break
        for v, fid, _p in adj.get(u, []):
            if v not in prev:
                prev[v] = (u, fid)
                dq.append(v)
    if dst not in prev:
        return {"path": [], "edges": [], "note": "no strict path"}
    seq, cur_n = [dst], dst
    while prev[cur_n][0]:
        seq.append(prev[cur_n][0])
        cur_n = prev[cur_n][0]
    seq.reverse()
    ents = STORE.q(
        "SELECT entity_id, canonical_name, entity_type FROM research_entities "
        "WHERE entity_id IN (%s)" % ",".join("?" * len(seq)), tuple(seq))
    names = {e["entity_id"]: e for e in ents}
    path_nodes = [{"entity_id": i, "name": names.get(i, {}).get("canonical_name", i),
                   "entity_type": names.get(i, {}).get("entity_type", "")} for i in seq]
    fids = [prev[b][1] for a, b in zip(seq, seq[1:]) if prev[b][1]]
    edges = STORE.q(
        "SELECT fact_id, subject_id, object_id, predicate, time_start FROM "
        "research_assertions WHERE fact_id IN (%s)" % ",".join("?" * len(fids)),
        tuple(fids)) if fids else []
    return {"path": path_nodes, "edges": edges, "hops": len(seq) - 1}


def api_verify(req) -> dict:
    """完整性自检：FINAL_NUMBERS 记录的 sha256 与当前库重算值比对。"""
    nums_path = PKG / "manifests" / "FINAL_NUMBERS.json"
    recorded = None
    if nums_path.exists():
        nums = json.loads(nums_path.read_text(encoding="utf-8"))
        recorded = nums.get("final_db_sha256")
    h = hashlib.sha256()
    with open(STORE.db_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    actual = h.hexdigest()
    return {"recorded_sha256": recorded, "actual_sha256": actual,
            "match": (recorded == actual) if recorded else None}


_REPLAY_LOCK = threading.Lock()
_REPLAY_STATE = {"running": False, "report": None}


def api_replay(req) -> dict:
    """Level-A 一键复现（进程内执行，串行锁防并发）。"""
    if _REPLAY_STATE["running"]:
        return {"running": True, "note": "replay already in progress"}
    with _REPLAY_LOCK:
        _REPLAY_STATE["running"] = True
        try:
            sys.path.insert(0, str(APP))
            import replay_core
            report = replay_core.run_all(PKG)
            _REPLAY_STATE["report"] = report
            return report
        except Exception as exc:  # noqa: BLE001
            return {"all_pass": False, "error": str(exc)[:300]}
        finally:
            _REPLAY_STATE["running"] = False


def api_reports(req) -> dict:
    """数据/报告入口：列出 manifest 与审计产物（文件名 + 字节数）。"""
    out = []
    for sub in ("manifests", "audit", "docs"):
        d = PKG / sub
        if not d.exists():
            continue
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix in (".json", ".md", ".csv", ".txt"):
                out.append({"path": f"{sub}/{p.name}", "bytes": p.stat().st_size})
    return {"files": out}


HANDLERS = {"stats": api_stats, "search": api_search, "entity": api_entity,
            "neighbors": api_neighbors, "evidence": api_evidence,
            "timeline": api_timeline, "path": api_path, "verify": api_verify,
            "replay": api_replay, "reports": api_reports}


# ---------------------------------------------------------------------------
# HTTP plumbing（stdlib）
# ---------------------------------------------------------------------------

def serve(req, resp):
    from urllib.parse import urlparse, parse_qs
    u = urlparse(req.path)
    parts = [p for p in u.path.split("/") if p]
    if u.path in ("/", "/index.html"):
        _static(resp, "index.html")
        return
    if parts and parts[0] == "api":
        name = parts[1] if len(parts) > 1 else ""
        handler = HANDLERS.get(name)
        if not handler:
            _json(resp, {"error": "unknown endpoint"}, 404)
            return
        out = handler({"path": u.path, "params": {k: v[0] for k, v in
                                                  parse_qs(u.query).items()}})
        if isinstance(out, tuple):
            _json(resp, out[0], out[1])
        else:
            _json(resp, out)
        return
    if u.path == "/launcher":
        _static(resp, "launcher.html")
        return
    rel = u.path.lstrip("/")
    if rel.startswith("static/"):
        _static(resp, rel[len("static/"):])
        return
    _static(resp, "index.html")


def _json(resp, obj: dict, code: int = 200):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    resp(code, [("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store")], body)


def _static(resp, name: str):
    p = (STATIC / name).resolve()
    if not str(p).startswith(str(STATIC.resolve())) or not p.exists():
        resp(404, [("Content-Type", "text/plain")], b"not found")
        return
    body = p.read_bytes()
    resp(200, [("Content-Type", MIME.get(p.suffix, "application/octet-stream")),
               ("Content-Length", str(len(body))),
               ("Cache-Control", "no-cache")], body)


def main() -> int:
    global STORE
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--page", default="/", choices=["/", "/launcher"])
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    if not DB.exists():
        print(f"[fatal] final DB not found: {DB}")
        return 1
    STORE = GraphStore(DB)
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            def resp(code, headers, body):
                self.send_response(code)
                for k, v in headers:
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)
            try:
                serve(self, resp)
            except Exception as exc:  # noqa: BLE001
                try:
                    _json(resp, {"error": str(exc)[:200]}, 500)
                except Exception:
                    pass

        def log_message(self, *a):  # 静默访问日志
            pass

    print(f"[ui] FINAL STKG → http://127.0.0.1:{args.port}{args.page}  (Ctrl+C 退出)")
    if not args.no_browser:
        import webbrowser, threading
        threading.Timer(1.2, lambda: webbrowser.open(
            f"http://127.0.0.1:{args.port}{args.page}")).start()
    # 线程池式服务器：单个慢查询不再阻塞整个 UI（搜索/验证可并发）
    from http.server import ThreadingHTTPServer

    class Srv(ThreadingHTTPServer):
        daemon_threads = True

    Srv(("127.0.0.1", args.port), H).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
