# -*- coding: utf-8 -*-
"""build_frozen_splits.py — P0-5：DEV/VAL/TEST 按 book-group 冻结切分。

设计（GOAL v3_1 指令 第五节）：
* 每个任务（五任务集）解析到其证据来源书集合（source_title 集合）；
* 任务—书二部图的连通分量 = 不可拆分组（同书任务不得跨 split）；
* 分量以 SHA-256(seed:component_id) 确定性分配到 DEV 60% / VAL 20% / TEST 20%；
* manifest 固化 task_id→split、每任务的 book 列表、输入 SHA-256、seed；
* 切分一经生成本脚本拒绝覆盖（--overwrite 显式重置，须在迭代日志记录理由）。

用法：
    python build_frozen_splits.py            # 生成 data/frozen_splits/*.json + manifest
    python build_frozen_splits.py --check    # 校验已有切分与任务集一致（不重算分配）
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

V3_1 = Path(__file__).resolve().parents[2]
V3 = V3_1.parent / "final_submission_v3"
for p in (str(V3 / "code"), str(V3 / "code" / "independent_eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _common import connect_final, attach_integration, sha256_file, V3_ROOT  # noqa: E402

SEED = 20260908
SPLIT_RATIOS = {"dev": 0.60, "val": 0.20, "test": 0.20}
OUT_DIR = V3_1 / "data" / "frozen_splits"

TASK_SAMPLE_FILES = {
    "entity_type": V3_ROOT / "experiments" / "08_independent_reference" / "ENTITY_TYPE_SAMPLE.csv",
    "relation_contract": V3_ROOT / "experiments" / "08_independent_reference" / "RELATION_CONTRACT_SAMPLE.csv",
    "scope_adjustment": V3_ROOT / "experiments" / "10_structural_validation" / "SCOPE_ADJUSTMENT_TASKS.jsonl",
    "identity_pair": V3_ROOT / "experiments" / "11_identity_validation" / "IDENTITY_PAIR_TASKS.jsonl",
    "provenance_support": V3_ROOT / "experiments" / "12_provenance_validation" / "PROVENANCE_SUPPORT_SAMPLE.csv",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_task_ids() -> dict[str, list[str]]:
    """各任务集的 task_id 顺序（与 V3 冻结样本一致）。"""
    out: dict[str, list[str]] = {}
    et = list(csv.DictReader(open(TASK_SAMPLE_FILES["entity_type"], encoding="utf-8-sig")))
    out["entity_type"] = [r["sample_id"] for r in et]
    rc = list(csv.DictReader(open(TASK_SAMPLE_FILES["relation_contract"], encoding="utf-8-sig")))
    out["relation_contract"] = [r["sample_id"] for r in rc]
    out["scope_adjustment"] = [r["task_id"] for r in load_jsonl(TASK_SAMPLE_FILES["scope_adjustment"])]
    out["identity_pair"] = [r["pair_id"] for r in load_jsonl(TASK_SAMPLE_FILES["identity_pair"])]
    pv = list(csv.DictReader(open(TASK_SAMPLE_FILES["provenance_support"], encoding="utf-8-sig")))
    out["provenance_support"] = [r["sample_id"] for r in pv]
    return out


def fact_books(con) -> dict[str, set[str]]:
    """fact_id -> 证据来源书标题集合（research_assertion_provenance.evidence_ids_json → evidence_registry）。"""
    books: dict[str, set[str]] = defaultdict(set)
    for fact_id, ej in con.execute("select fact_id, evidence_ids_json from research_assertion_provenance"):
        try:
            eids = json.loads(str(ej or "[]"))
        except json.JSONDecodeError:
            continue
        for eid in eids:
            r = con.execute(
                "select source_title from up.evidence_registry where evidence_id=?", (str(eid),)
            ).fetchone()
            if r is not None and r["source_title"]:
                books[str(fact_id)].add(str(r["source_title"]))
    return books


def entity_books(con, fact_books_map: dict[str, set[str]]) -> dict[str, set[str]]:
    """canonical entity -> 成员断言的证据书集合。"""
    ent_facts: dict[str, set[str]] = defaultdict(set)
    for sid, oid, fid in con.execute(
        "select subject_id, object_id, fact_id from research_assertions"
    ):
        if fid:
            ent_facts[str(sid)].add(str(fid))
            ent_facts[str(oid)].add(str(fid))
    ent_books: dict[str, set[str]] = defaultdict(set)
    for canon, src in con.execute(
        "select canonical_entity_id, source_entity_id from research_entity_members"
    ):
        for fid in ent_facts.get(str(src), ()):  # 成员断言的书
            ent_books[str(canon)].update(fact_books_map.get(fid, set()))
    return ent_books


def task_book_map(con) -> dict[tuple[str, str], set[str]]:
    """(task_type, task_id) -> 书集合。"""
    fb = fact_books(con)
    eb = entity_books(con, fb)
    mapping: dict[tuple[str, str], set[str]] = {}

    for sid, r in zip(
        load_task_ids()["entity_type"],
        csv.DictReader(open(TASK_SAMPLE_FILES["entity_type"], encoding="utf-8-sig")),
    ):
        mapping[("entity_type", sid)] = set(eb.get(str(r["entity_id"]), set()))

    rc_rows = list(csv.DictReader(open(TASK_SAMPLE_FILES["relation_contract"], encoding="utf-8-sig")))
    for sid, r in zip(load_task_ids()["relation_contract"], rc_rows):
        mapping[("relation_contract", sid)] = set(fb.get(str(r["fact_id"]), set()))

    for r in load_jsonl(TASK_SAMPLE_FILES["scope_adjustment"]):
        mapping[("scope_adjustment", r["task_id"])] = set(fb.get(str(r["fact_id"]), set()))

    for r in load_jsonl(TASK_SAMPLE_FILES["identity_pair"]):
        books: set[str] = set()
        for fid in json.loads(str(r.get("context_fact_ids_a") or "[]")) + json.loads(
            str(r.get("context_fact_ids_b") or "[]")
        ):
            books.update(fb.get(str(fid), set()))
        mapping[("identity_pair", r["pair_id"])] = books

    pv_rows = list(csv.DictReader(open(TASK_SAMPLE_FILES["provenance_support"], encoding="utf-8-sig")))
    for sid, r in zip(load_task_ids()["provenance_support"], pv_rows):
        mapping[("provenance_support", sid)] = set(fb.get(str(r["fact_id"]), set()))
    return mapping


def assign(component: str) -> str:
    h = hashlib.sha256(f"{SEED}:{component}".encode()).hexdigest()
    v = int(h[:16], 16) / 2**64
    acc = 0.0
    for split, ratio in SPLIT_RATIOS.items():
        acc += ratio
        if v < acc:
            return split
    return "test"


def assign_balanced(component: str) -> str:
    """有书小分量：val/test 各 50%（dev 由最大分量按构造承担）。"""
    h = hashlib.sha256(f"{SEED}:bal:{component}".encode()).hexdigest()
    return "val" if int(h[:16], 16) / 2**64 < 0.5 else "test"


def assign_no_book(key: str) -> str:
    """无书任务：60/20/20 哈希分配。"""
    h = hashlib.sha256(f"{SEED}:nob:{key}".encode()).hexdigest()
    v = int(h[:16], 16) / 2**64
    if v < 0.60:
        return "dev"
    return "val" if v < 0.80 else "test"


def build() -> dict[str, Any]:
    con = connect_final()
    attach_integration(con)
    tb = task_book_map(con)

    # 并查集：任务—书连通分量
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for (tt, tid), books in tb.items():
        node = f"task:{tt}:{tid}"
        find(node)
        for b in books:
            union(node, f"book:{b}")

    components: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for (tt, tid), _ in tb.items():
        components[find(f"task:{tt}:{tid}")].append((tt, tid))

    comp_split: dict[str, str] = {}
    root_cid: dict[str, str] = {}
    # 分配规则（固化于 manifest 的 assignment_rules）：
    # R1 有书分量中最大者按构造归 dev（调优池）；其余有书分量 50/50 → val/test。
    #    巨型互引核心若靠随机落位会使比例靠运气，故按构造固定。
    # R2 无书任务（证据链不可达，无同书泄漏约束）按 60/20/20 哈希分配，
    #    保证 dev 含全部任务型的调优数据；残余跨书内容重叠风险在 manifest 披露。
    if not components:
        raise ValueError("no components")
    largest_root = max(components, key=lambda r: len(components[r]))
    for root, members in components.items():
        cid = hashlib.sha256(("|".join(sorted(f"{t}:{i}" for t, i in members))).encode()).hexdigest()[:16]
        comp_split[cid] = "dev" if root == largest_root else assign_balanced(cid)
        root_cid[root] = cid
    assignment: dict[str, str] = {}
    no_book_split: dict[str, str] = {}
    for (tt, tid), books in tb.items():
        key = f"{tt}:{tid}"
        if books:
            assignment[key] = comp_split[root_cid[find(f"task:{tt}:{tid}")]]
        else:
            s = assign_no_book(key)
            no_book_split[key] = s
            assignment[key] = s
    counts: dict[str, int] = {"dev": 0, "val": 0, "test": 0}
    for v in assignment.values():
        counts[v] += 1
    payload = {
        "seed": SEED,
        "ratios": SPLIT_RATIOS,
        "assignment_rules": {
            "R1": "booked components: largest -> dev by construction; others -> val/test 50/50 (hash)",
            "R2": "no-book tasks (evidence chain unreachable; no same-book constraint): dev/val/test 60/20/20 (hash)",
            "residual_risk": "no-book tasks may share latent sources across splits; documented, accepted",
        },
        "no_book_split": no_book_split,
        "assignment": assignment,
        "component_split": comp_split,
        "task_books": {f"{tt}:{tid}": sorted(b) for (tt, tid), b in tb.items()},
        "counts": counts,
        "inputs_sha256": {str(p): sha256_file(p) for p in TASK_SAMPLE_FILES.values()},
    }
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "SPLIT_MANIFEST.json"
    if out_path.exists() and not args.overwrite:
        print(f"[build_frozen_splits] 已存在：{out_path}（--check 校验 / --overwrite 重置）")
        if args.check:
            old = json.loads(out_path.read_text(encoding="utf-8"))
            new = build()
            same = old["assignment"] == new["assignment"]
            print(f"[build_frozen_splits] check: {'CONSISTENT' if same else 'DRIFT'}; counts={new['counts']}")
            return 0 if same else 1
        return 0
    payload = build()
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for s in SPLIT_RATIOS:
        (OUT_DIR / f"{s}.txt").write_text(
            "\n".join(sorted(k for k, v in payload["assignment"].items() if v == s)),
            encoding="utf-8",
        )
    print(f"[build_frozen_splits] written: {out_path}; counts={payload['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
