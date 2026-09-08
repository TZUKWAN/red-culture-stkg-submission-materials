# -*- coding: utf-8 -*-
"""build_v31_payloads.py — P0-6/P0-7/P0-8：带真实证据的 v4 盲评 payload 重建。

三个任务族（互不混标签）：
* relation_semantic_v2 (P0-6)：从 3412 changed set 中抽有真实原文证据的 changed，
  按 stratum 确定性匹配同样有证据的 matched control；目标 ≥400+400。
  judge 输出语义支持五档（SUPPORTED/CONTEXTUAL_ONLY/UNSUPPORTED/CONTRADICTED/
  INSUFFICIENT_EVIDENCE），不可见 contract 决策 / release tier / changed-control 角色。
* scope_revalidation_v2 (P0-7)：全部 208 条 role-owner 调整，payload 增加真实原文
  证据句与上下文；A/B 展示位重新随机化（新 seed），映射文件单独落盘。
* identity_revalidation_v2 (P0-8)：300 正 + 300 硬负，judge 可见双方实体类型
  （消歧合法语义输入），仍不可见 canonical id / merge 结果 / mapping status。

盲化黑名单沿用 V3 blind_payload 的键/值扫描（import 复用，不修改 V3 文件）。
所有 payload 写 v3_1/experiments/01_reference_rebuild/payloads/；每个任务族一个
jsonl + metadata sidecar（含 books，供 book-grouped split 使用）。
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

V3_1 = Path(__file__).resolve().parents[2]
V3 = V3_1.parent / "final_submission_v3"
for p in (str(V3 / "code"), str(V3 / "code" / "independent_eval"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from _common import connect_final, attach_integration, sha256_file, derive_seed, MASTER_SEED  # noqa: E402

OUT = V3_1 / "experiments" / "01_reference_rebuild" / "payloads"
SEED = 20260908
PROMPT_VERSION = "imcr.v4"
MAX_EVIDENCE_CHARS = 1200
MAX_EVIDENCE_BLOCKS = 3

RELATION_LABELS = ["SUPPORTED", "CONTEXTUAL_ONLY", "UNSUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"]

_V3_ROOT = V3
_SCOPE_SCHEMA_DEFS = json.loads(
    (_V3_ROOT / "experiments" / "08_independent_reference" / "payloads" / "SCOPE_ADJUSTMENT_PAYLOADS.jsonl")
    .read_text(encoding="utf-8").splitlines()[0]
)["payload"]["schema_definitions"]
SCOPE_LABELS = ["A_BETTER", "B_BETTER", "EQUIVALENT", "BOTH_WRONG", "INSUFFICIENT_EVIDENCE"]
IDENTITY_LABELS = ["same_entity", "different_entity", "insufficient_evidence"]


# ---------------------------------------------------------------------------
# DB 证据抽取
# ---------------------------------------------------------------------------

def build_fact_evidence(con, cap: int = MAX_EVIDENCE_BLOCKS) -> dict[str, list[dict[str, str]]]:
    """fact_id → 证据块列表（evidence_text + context + source_title），确定性排序。"""
    fact_eids: dict[str, list[str]] = defaultdict(list)
    for fid, ej in con.execute("select fact_id, evidence_ids_json from research_assertion_provenance"):
        try:
            ids = json.loads(str(ej or "[]"))
        except json.JSONDecodeError:
            continue
        if ids:
            fact_eids[str(fid)].extend(str(i) for i in ids)
    out: dict[str, list[dict[str, str]]] = {}
    for fid, eids in fact_eids.items():
        blocks = []
        seen_titles: set[str] = set()
        for eid in sorted(set(eids)):  # 去重后字典序 → 确定性
            r = con.execute(
                "select evidence_text, context_before, context_after, source_title from up.evidence_registry where evidence_id=?",
                (eid,),
            ).fetchone()
            if r is None or not r["evidence_text"]:
                continue
            title = str(r["source_title"] or "")
            blocks.append(
                {
                    "evidence_text": str(r["evidence_text"]),
                    "context_before": str(r["context_before"] or ""),
                    "context_after": str(r["context_after"] or ""),
                    "source_title": title,
                }
            )
            seen_titles.add(title)
            if len(blocks) >= cap:
                break
        if blocks:
            blocks[-1]["books"] = sorted(seen_titles)
            out[fid] = blocks
    return out


def evidence_chars(blocks: list[dict[str, str]]) -> int:
    return sum(len(b["evidence_text"]) + len(b["context_before"]) + len(b["context_after"]) for b in blocks)


def trim_blocks(blocks: list[dict[str, str]]) -> list[dict[str, str]]:
    out = []
    used = 0
    for b in blocks:
        n = evidence_chars([b])
        if used + n > MAX_EVIDENCE_CHARS and out:
            break
        out.append(b)
        used += n
    return out


# ---------------------------------------------------------------------------
# relation_semantic_v2 (P0-6)
# ---------------------------------------------------------------------------

def build_relation_payloads(con) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    changed = list(csv.DictReader(open(V3 / "experiments" / "10_structural_validation" / "RELATION_CONTRACT_CHANGED_SET.csv", encoding="utf-8-sig")))
    ev = build_fact_evidence(con)
    # 排除同时属于 208 scope 调整的（任务族分离）
    changed_pool = [r for r in changed if r["in_scope_adjustments_208"] == "0" and r["fact_id"] in ev]
    # stratum 确定性抽样：目标 400 changed（组内按 hash 排序轮转）
    strata: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in changed_pool:
        key = (r["predicate"], r["subject_type"], r["object_type"])
        strata[key].append(r)
    picked: list[dict[str, Any]] = []
    TARGET_CHANGED = 400
    for round_i in range(50):
        added = False
        for key in sorted(strata):
            rows = sorted(strata[key], key=lambda r: hashlib.sha256(f"{SEED}:{r['fact_id']}".encode()).hexdigest())
            if round_i < len(rows) and len(picked) < TARGET_CHANGED:
                picked.append(rows[round_i])
                added = True
                if len(picked) >= TARGET_CHANGED:
                    break
        if len(picked) >= TARGET_CHANGED or not added:
            break
    picked_ids = {r["fact_id"] for r in picked}

    # control 池：单次 JOIN 构建同 stratum、有证据、不在 changed set 的未变断言池
    changed_all = {r["fact_id"] for r in changed}
    ctrl_rows = con.execute(
        "select a.fact_id, a.subject_name, a.object_name, a.predicate, a.subject_type, a.object_type "
        "from research_assertion_provenance p join research_assertions a on a.fact_id = p.fact_id "
        "where p.evidence_ids_json is not null and p.evidence_ids_json not in ('', '[]')"
    ).fetchall()
    ctrl_strata3: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    ctrl_strata2: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    ctrl_strata1: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    seen_facts: set[str] = set()
    for r in ctrl_rows:
        fid = str(r["fact_id"])
        if fid in changed_all or fid not in ev or fid in seen_facts:
            continue
        seen_facts.add(fid)
        rec = {
            "fact_id": fid,
            "subject_name": str(r["subject_name"] or ""),
            "object_name": str(r["object_name"] or ""),
            "predicate": str(r["predicate"]),
            "subject_type": str(r["subject_type"]),
            "object_type": str(r["object_type"]),
        }
        key3 = (rec["predicate"], rec["subject_type"], rec["object_type"])
        key2 = (rec["predicate"], rec["subject_type"])
        key1 = (rec["predicate"],)
        ctrl_strata3[key3].append(rec)
        ctrl_strata2[key2].append(rec)
        ctrl_strata1[key1].append(rec)

    def hash_of(fid: str, salt: str) -> str:
        return hashlib.sha256(f"{SEED}:{salt}:{fid}".encode()).hexdigest()

    controls: list[dict[str, Any]] = []
    used_ctrl: set[str] = set()
    for r in sorted(picked, key=lambda x: hash_of(x["fact_id"], "c")):
        key3 = (r["predicate"], r["subject_type"], r["object_type"])
        key2 = (r["predicate"], r["subject_type"])
        cand = [c for c in sorted(ctrl_strata3.get(key3, []), key=lambda c: hash_of(c["fact_id"], "o")) if c["fact_id"] not in used_ctrl]
        if not cand:
            cand = [c for c in sorted(ctrl_strata1.get((r["predicate"],), []), key=lambda c: hash_of(c["fact_id"], "o")) if c["fact_id"] not in used_ctrl]
        if cand:
            c = cand[0]
            used_ctrl.add(c["fact_id"])
            controls.append({**c, "matched_to": r["fact_id"], "match_level": "exact" if c in ctrl_strata3.get(key3, []) else "relaxed"})
        if len(controls) >= len(picked):
            break

    def payload_row(idx: int, fact_id: str, role: str, r: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        blocks = trim_blocks(ev[fact_id])
        books = sorted({b for blk in blocks for b in blk.get("books", [])})
        first = blocks[0]
        p = {
            "subject_text": str(r.get("subject_name") or ""),
            "subject_type": str(r["subject_type"]),
            "predicate": str(r["predicate"]),
            "object_text": str(r.get("object_name") or ""),
            "object_type": str(r["object_type"]),
            "evidence_excerpts": [
                {"text": b["evidence_text"], "context_before": b["context_before"], "context_after": b["context_after"], "source_title": b["source_title"]}
                for b in blocks
            ],
        }
        tid = f"RSEM-{idx:04d}"
        row = {
            "task_id": tid,
            "allowed_labels": RELATION_LABELS,
            "prompt_version": PROMPT_VERSION,
            "payload": p,
        }
        row["prompt_sha256"] = hashlib.sha256(
            json.dumps({"tid": tid, "labels": RELATION_LABELS, "payload": p, "pv": PROMPT_VERSION}, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        meta = {
            "task_id": tid,
            "fact_id": fact_id,
            "sample_role": role,
            "matched_to": r.get("matched_to", ""),
            "books": books,
            "n_evidence_blocks": len(blocks),
            "evidence_sha": hashlib.sha256(json.dumps(blocks, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16],
            "first_source": first["source_title"],
        }
        return row, meta

    rows: list[dict[str, Any]] = []
    metas: list[dict[str, Any]] = []
    idx = 1
    order = sorted(picked + controls, key=lambda r: hashlib.sha256(f"{SEED}:order:{r['fact_id']}".encode()).hexdigest())
    for r in order:
        role = "changed" if r["fact_id"] in picked_ids else "control"
        row, meta = payload_row(idx, r["fact_id"], role, r)
        rows.append(row)
        metas.append(meta)
        idx += 1
    return rows, metas


# ---------------------------------------------------------------------------
# scope_revalidation_v2 (P0-7)：208 全量 + 原文证据 + 新 A/B 随机化
# ---------------------------------------------------------------------------

def ent_name_and_type(con, eid: str) -> tuple[str, str]:
    """实体 id → (规范名, 类型)；IENTREPAIR/ITOPIC 在 research_entities，IENT 在 sem.v2_entities。"""
    r = con.execute("select canonical_name, entity_type from research_entities where entity_id=?", (eid,)).fetchone()
    if r is not None:
        return str(r["canonical_name"] or ""), str(r["entity_type"] or "")
    r2 = con.execute("select canonical_name, source_entity_type from sem.v2_entities where entity_id=?", (eid,)).fetchone()
    if r2 is not None:
        return str(r2["canonical_name"] or ""), str(r2["source_entity_type"] or "")
    return "", "UNKNOWN"


def lexical_evidence(con, subject: str, obj: str, time_token: str = "", limit: int = 3) -> list[dict[str, str]]:
    """词法检索证据句，渐进退化：双名同现 → 名+时间 → 单名。

    自动、确定性（按 source_title, evidence_id 排序）、无人工。
    """
    subject = (subject or "").strip()
    obj = (obj or "").strip()
    tt = (time_token or "").strip()

    def run(likes: list[str]) -> list[dict[str, str]]:
        conds = ["evidence_text like ?"] * len(likes)
        rows = con.execute(
            "select evidence_text, context_before, context_after, source_title, evidence_id from up.evidence_registry "
            f"where {' and '.join(conds)} order by source_title, evidence_id limit {limit * 4}",
            likes,
        ).fetchall()
        out, seen = [], set()
        for r in rows:
            key = str(r["evidence_id"])
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "evidence_text": str(r["evidence_text"]),
                    "context_before": str(r["context_before"] or ""),
                    "context_after": str(r["context_after"] or ""),
                    "source_title": str(r["source_title"] or ""),
                }
            )
            if len(out) >= limit:
                break
        return out

    has_s, has_o = len(subject) >= 2, len(obj) >= 2
    tt_like = f"%{tt}%" if len(tt) >= 4 else None
    attempts: list[list[str]] = []
    if has_s and has_o:
        attempts.append([f"%{subject}%", f"%{obj}%"])
    if has_s and tt_like:
        attempts.append([f"%{subject}%", tt_like])
    if has_o and tt_like:
        attempts.append([f"%{obj}%", tt_like])
    if has_s:
        attempts.append([f"%{subject}%"])
    if has_o:
        attempts.append([f"%{obj}%"])
    for likes in attempts:
        hits = run(likes)
        if hits:
            return hits
    return []


def build_scope_payloads(con) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    tasks = [json.loads(l) for l in (V3 / "experiments" / "10_structural_validation" / "SCOPE_ADJUSTMENT_TASKS.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    ev = build_fact_evidence(con)
    ab_seed = derive_seed("scope_revalidation_v2_ab", MASTER_SEED)
    rows: list[dict[str, Any]] = []
    metas: list[dict[str, Any]] = []
    mapping: list[dict[str, str]] = []
    retrieval_stats = {"direct": 0, "lexical": 0, "none": 0}
    for r in sorted(tasks, key=lambda x: x["task_id"]):
        fid = str(r["fact_id"])
        blocks = trim_blocks(ev.get(fid, []))
        source = "direct" if blocks else "none"
        ctx = r.get("assertion_context", {})
        subj_id = str(ctx.get("subject_id", ""))
        obj_id = str(ctx.get("object_id", ""))
        subj_name, subj_type = ent_name_and_type(con, subj_id)
        obj_name, obj_type = ent_name_and_type(con, obj_id)
        subj_name_fallback, obj_name_fallback = subj_id, obj_id
        subj_name = str(ctx.get("subject_name") or "") or subj_name
        obj_name = str(ctx.get("object_name") or "") or obj_name
        if not blocks:
            blocks = trim_blocks(lexical_evidence(con, subj_name or obj_id, obj_name or obj_id, str(ctx.get("time_raw", ""))))
            source = "lexical" if blocks else "none"
        retrieval_stats[source] += 1
        books = sorted({b for blk in blocks for b in blk.get("books", [])})
        adj = r.get("adjustment", {})
        h = hashlib.sha256(f"{ab_seed}:{r['task_id']}".encode()).digest()
        a_is_before = (h[0] & 1) == 0  # 偶数：a=before
        before = {
            "time_role": adj.get("source_time_role", ""),
            "time_owner": adj.get("source_time_owner_id", ""),
            "space_role": adj.get("source_space_role", ""),
            "space_owner": adj.get("source_space_owner_id", ""),
        }
        after = {
            "time_role": adj.get("final_time_role", ""),
            "time_owner": adj.get("final_time_owner_id", ""),
            "space_role": adj.get("final_space_role", ""),
            "space_owner": adj.get("final_space_owner_id", ""),
        }
        state_a, state_b = (before, after) if a_is_before else (after, before)

        def owner_disp(oid: str) -> str | None:
            oid = str(oid or "")
            if not oid or oid == "unknown":
                return None
            name, typ = ent_name_and_type(con, oid)
            if not name:
                name = oid
            return f"{name}（{typ}）" if typ else name

        disp_a = {k: owner_disp(v) if k.endswith("owner") else v for k, v in state_a.items()}
        disp_b = {k: owner_disp(v) if k.endswith("owner") else v for k, v in state_b.items()}
        subj_name = str(ctx.get("subject_name") or "") or subj_name_fallback
        obj_name = str(ctx.get("object_name") or "") or obj_name_fallback
        subj_type = str(ctx.get("subject_type") or "")
        obj_type = str(ctx.get("object_type") or "")
        assertion_text = (
            f"断言：{subj_name}（{subj_type}） —{ctx.get('predicate', '')}→ {obj_name}（{obj_type}）\n"
            f"时间：原始表述：{ctx.get('time_raw', '')}；规范表述：{ctx.get('normalized_time_label', '')}；"
            f"区间：{ctx.get('time_start', '')} 至 {ctx.get('time_end', '')}；精度：{ctx.get('time_precision', '')}\n"
            f"空间：原始表述：{ctx.get('place_raw', '')}"
        )
        p = {
            "assertion_text": assertion_text,
            "a": disp_a,
            "b": disp_b,
            "schema_definitions": _SCOPE_SCHEMA_DEFS,
            "evidence_excerpts": [
                {"text": b["evidence_text"], "context_before": b["context_before"], "context_after": b["context_after"], "source_title": b["source_title"]}
                for b in blocks
            ],
        }
        row = {
            "task_id": r["task_id"],
            "allowed_labels": SCOPE_LABELS,
            "prompt_version": PROMPT_VERSION,
            "payload": p,
        }
        row["prompt_sha256"] = hashlib.sha256(
            json.dumps({"tid": r["task_id"], "labels": SCOPE_LABELS, "payload": p, "pv": PROMPT_VERSION}, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        rows.append(row)
        metas.append(
            {
                "task_id": r["task_id"],
                "fact_id": fid,
                "books": books,
                "n_evidence_blocks": len(blocks),
                "evidence_source": source,
                "has_evidence": bool(blocks),
            }
        )
        mapping.append(
            {
                "task_id": r["task_id"],
                "a": "before" if a_is_before else "after",
                "b": "after" if a_is_before else "before",
                "seed": str(ab_seed),
            }
        )
    print(f"[build_v31_payloads] scope evidence retrieval: {retrieval_stats}")
    return rows, metas, mapping


# ---------------------------------------------------------------------------
# identity_revalidation_v2 (P0-8)：同 600 对，类型可见
# ---------------------------------------------------------------------------

def build_identity_payloads(con) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tasks = [json.loads(l) for l in (V3 / "experiments" / "11_identity_validation" / "IDENTITY_PAIR_TASKS.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    meta_rows = {r["pair_id"]: r for r in csv.DictReader(open(V3 / "experiments" / "11_identity_validation" / "IDENTITY_PAIR_METADATA.csv", encoding="utf-8-sig"))}

    def ent_type(eid: str) -> str:
        return ent_name_and_type(con, eid)[1]

    books_of: dict[str, set[str]] = defaultdict(set)
    for r in meta_rows.values():
        for eid_key in ("entity_a_id", "entity_b_id"):
            pass  # books 由证据链（P0-6 的 fact_books 逻辑）成本高；identity 的 split 用 R2 无书规则
    rows: list[dict[str, Any]] = []
    metas: list[dict[str, Any]] = []
    for r in sorted(tasks, key=lambda x: x["pair_id"]):
        m = meta_rows.get(r["pair_id"], {})
        p = dict(r)
        p["entity_type_a"] = ent_type(str(m.get("entity_a_id", "")))
        p["entity_type_b"] = ent_type(str(m.get("entity_b_id", "")))
        row = {
            "task_id": r["pair_id"],
            "allowed_labels": IDENTITY_LABELS,
            "prompt_version": PROMPT_VERSION,
            "payload": p,
        }
        row["prompt_sha256"] = hashlib.sha256(
            json.dumps({"tid": r["pair_id"], "labels": IDENTITY_LABELS, "payload": p, "pv": PROMPT_VERSION}, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        rows.append(row)
        metas.append(
            {
                "pair_id": r["pair_id"],
                "pair_kind": str(m.get("pair_kind", "")),
                "category": str(m.get("category", "")),
                "entity_type_a": p["entity_type_a"],
                "entity_type_b": p["entity_type_b"],
            }
        )
    return rows, metas


# ---------------------------------------------------------------------------

def write_task(name: str, rows: list[dict[str, Any]], metas: list[dict[str, Any]], extra: dict[str, Any] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pf = OUT / f"{name.upper()}_PAYLOADS.jsonl"
    with open(pf, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    mf = OUT / f"{name.upper()}_METADATA.csv"
    keys = list(metas[0].keys()) if metas else []
    with open(mf, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(metas)
    manifest = {
        "experiment_id": f"v31_payload_{name}",
        "prompt_version": PROMPT_VERSION,
        "seed": SEED,
        "n_payloads": len(rows),
        "payload_file": pf.name,
        "payload_sha256": sha256_file(pf),
        "metadata_file": mf.name,
        "metadata_sha256": sha256_file(mf),
        **(extra or {}),
    }
    (OUT / f"{name.upper()}_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build_v31_payloads] {name}: n={len(rows)} -> {pf.name}")


def main() -> int:
    con = connect_final()
    attach_integration(con)
    rel_rows, rel_meta = build_relation_payloads(con)
    write_task("relation_semantic_v2", rel_rows, rel_meta, {"labels": RELATION_LABELS, "note": "changed sampled with evidence; controls matched on (predicate,subject_type[,object_type]) with evidence"})
    scope_rows, scope_meta, scope_map = build_scope_payloads(con)
    write_task("scope_revalidation_v2", scope_rows, scope_meta, {"labels": SCOPE_LABELS, "ab_seed": str(derive_seed("scope_revalidation_v2_ab", MASTER_SEED))})
    (OUT / "SCOPE_REVALIDATION_V2_AB_MAPPING.csv").write_text(
        "task_id,a,b,seed\n" + "".join(f"{m['task_id']},{m['a']},{m['b']},{m['seed']}\n" for m in scope_map),
        encoding="utf-8",
    )
    id_rows, id_meta = build_identity_payloads(con)
    write_task("identity_revalidation_v2", id_rows, id_meta, {"labels": IDENTITY_LABELS, "note": "entity types visible; merge decisions hidden"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
