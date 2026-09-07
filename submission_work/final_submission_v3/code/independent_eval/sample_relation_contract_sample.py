#!/usr/bin/env python3
"""任务2 抽样：从 3412 条关系契约变化集分层抽 ≥300 条困难样本，并从未变化记录抽取 ≥300 条匹配对照。

- 困难样本：按 stratum=(predicate, subject_type, object_type, stage_codes, risk_tier) 分层，
  最大余数法 proportional allocation，目标 320 条（为对照匹配留余量）。
- 对照：对每条已抽 changed 记录，在未变化断言池中按相同 stratum 无放回匹配；
  匹配不上时逐级放宽（L2 去 risk_tier → L3 去 stage → L4 去 object_type → L5 仅同 predicate），
  记录 match_level。对照池由同一确定性重放逻辑现场重建（Full vs w/o Relation Contract 状态相等者）。

种子：master=20260907；changed 抽样与对照匹配分别用
SHA-256('relation_contract_changed_sample|20260907') / SHA-256('relation_contract_control_match|20260907') 前 8 字节。

产出（experiments/08_independent_reference/）：
- RELATION_CONTRACT_SAMPLE.csv（sample_role=changed/control，含 pair_id、stratum、match_level、种子）
- RELATION_CONTRACT_SAMPLE_AUDIT.json（分层分布、匹配质量、148 条参考子集核实 notes）
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\REDCULTUREDATA\投稿材料_代码数据整理包")
FINAL_DB = ROOT / "data" / "release_databases" / "red_culture_stkg_final_v2.sqlite"
SEMANTIC_DB = ROOT / "data" / "release_databases" / "red_culture_stkg_semantic_v2.sqlite"
CODE_DIR = ROOT / "submission_work" / "final_submission_v3" / "code" / "independent_eval"
CHANGED_CSV = ROOT / "submission_work" / "final_submission_v3" / "experiments" / "10_structural_validation" / "RELATION_CONTRACT_CHANGED_SET.csv"
OUTDIR = ROOT / "submission_work" / "final_submission_v3" / "experiments" / "08_independent_reference"
OUTDIR.mkdir(parents=True, exist_ok=True)

MASTER_SEED = 20260907
FINAL_DB_SHA256 = "a199d736b9ec436b3d5f244e874718604b6c84955a505f31f90a3e28c51a9ee7"
SEMANTIC_DB_SHA256 = "fbfb6529335e1c838270c63eee53c92a568c2b075354f7ad5f9d5815b88bb377"
TARGET_CHANGED = 320
MIN_PAIRS = 300


def derive_seed(task_name: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{task_name}|{MASTER_SEED}".encode("utf-8")).digest()[:8], "big")


def load_replay_module():
    spec = importlib.util.spec_from_file_location(
        "extract_relation_contract_replay", CODE_DIR / "extract_relation_contract_replay.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_control_pool(replay):
    """重放 Full vs w/o Relation Contract，返回未变化记录池（仅分层所需字段）。"""
    rb = replay.load_research_base()
    con = sqlite3.connect(f"file:{SEMANTIC_DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("ATTACH DATABASE ? AS fin", (f"file:{FINAL_DB.as_posix()}?mode=ro",))
    query = (
        "with provenance as ("
        " select fact_id,count(*) provenance_count"
        " from fin.research_assertion_provenance group by fact_id) "
        "select a.fact_id,a.predicate,a.semantic_status,a.risk_tier,"
        "ms.canonical_entity_id subject_id,ms.canonical_entity_type subject_type,"
        "mo.canonical_entity_id object_id,mo.canonical_entity_type object_type,"
        "es.type_validation_status subject_validation,eo.type_validation_status object_validation,"
        "p.provenance_count,f.research_tier release_tier "
        "from v2_assertion_scopes a "
        "join v2_entity_identity_map ms on ms.source_entity_id=a.subject_id "
        "join v2_entity_identity_map mo on mo.source_entity_id=a.object_id "
        "join v2_entity_type_effective es on es.entity_id=a.subject_id "
        "join v2_entity_type_effective eo on eo.entity_id=a.object_id "
        "join fin.research_assertions f on f.fact_id=a.fact_id "
        "join provenance p on p.fact_id=a.fact_id order by a.fact_id"
    )
    pool = []
    for row in con.execute(query):
        subject_type = str(row["subject_type"])
        object_type = str(row["object_type"])
        actual_contract_pass = rb.relation_domain_range_pass_v2(row["predicate"], subject_type, object_type)
        route_pass = str(row["semantic_status"]) == "auto_accepted"
        base_ok = (
            route_pass
            and not str(row["predicate"]).startswith("raw:")
            and row["subject_validation"] == "validated"
            and row["object_validation"] == "validated"
            and bool(row["provenance_count"])
        )
        full_strict = base_ok and actual_contract_pass
        wo_strict = base_ok and True  # w/o Relation Contract: contract_pass=True
        full_tier = "strict_semantic" if full_strict else ("contextual" if route_pass else "unresolved")
        wo_tier = "strict_semantic" if wo_strict else ("contextual" if route_pass else "unresolved")
        if full_tier == wo_tier:  # 未变化
            pool.append(
                {
                    "fact_id": str(row["fact_id"]),
                    "predicate": str(row["predicate"]),
                    "subject_id": str(row["subject_id"]),
                    "subject_type": subject_type,
                    "object_id": str(row["object_id"]),
                    "object_type": object_type,
                    "risk_tier": str(row["risk_tier"]),
                    "semantic_status": str(row["semantic_status"]),
                    "release_tier": str(row["release_tier"]),
                }
            )
    con.close()
    return pool


def largest_remainder_allocation(counts: dict, budget: int) -> dict:
    total = sum(counts.values())
    quotas = {k: budget * v / total for k, v in counts.items()}
    alloc = {k: int(q) for k, q in quotas.items()}
    remainder = budget - sum(alloc.values())
    for k, _ in sorted(quotas.items(), key=lambda kv: (kv[1] - int(kv[1]), counts[kv[0]]), reverse=True):
        if remainder <= 0:
            break
        if alloc[k] < counts[k]:
            alloc[k] += 1
            remainder -= 1
    return {k: v for k, v in alloc.items() if v > 0}


def main() -> None:
    replay = load_replay_module()

    changed = list(csv.DictReader(open(CHANGED_CSV, encoding="utf-8-sig")))
    assert len(changed) == 3412

    stratum_key = lambda r: (
        r["predicate"], r["subject_type"], r["object_type"], r["stage_codes"], r["risk_tier"]
    )
    strata = defaultdict(list)
    for r in changed:
        strata[stratum_key(r)].append(r)

    seed_changed = derive_seed("relation_contract_changed_sample")
    rng = random.Random(seed_changed)
    alloc = largest_remainder_allocation({k: len(v) for k, v in strata.items()}, TARGET_CHANGED)
    selected_changed = []
    for key in sorted(alloc):
        pool = sorted(strata[key], key=lambda r: r["fact_id"])
        rng.shuffle(pool)
        selected_changed.extend(pool[: alloc[key]])

    # 对照池
    pool = build_control_pool(replay)
    changed_ids = {r["fact_id"] for r in changed}
    pool = [p for p in pool if p["fact_id"] not in changed_ids]

    # 阶段代码补充（对照池）
    con = sqlite3.connect(f"file:{FINAL_DB.as_posix()}?mode=ro", uri=True)
    stage_map = defaultdict(list)
    for s in con.execute("SELECT fact_id, stage_code FROM research_assertion_stage_memberships ORDER BY stage_code"):
        stage_map[s[0]].append(s[1])
    con.close()
    for p in pool:
        p["stage_codes"] = "|".join(stage_map.get(p["fact_id"], [])) or "no_stage"

    def pkey(p, level):
        if level == 1:
            return (p["predicate"], p["subject_type"], p["object_type"], p["stage_codes"], p["risk_tier"])
        if level == 2:
            return (p["predicate"], p["subject_type"], p["object_type"], p["stage_codes"])
        if level == 3:
            return (p["predicate"], p["subject_type"], p["object_type"])
        if level == 4:
            return (p["predicate"], p["subject_type"])
        return (p["predicate"],)

    index = {lvl: defaultdict(list) for lvl in range(1, 6)}
    for p in pool:
        for lvl in range(1, 6):
            index[lvl][pkey(p, lvl)].append(p)

    seed_control = derive_seed("relation_contract_control_match")
    rngc = random.Random(seed_control)
    for lvl in range(1, 6):
        for k in index[lvl]:
            index[lvl][k].sort(key=lambda p: p["fact_id"])
            rngc.shuffle(index[lvl][k])

    used_control_ids = set()
    pairs = []
    unmatched_changed = []

    def try_match(ch):
        for lvl in range(1, 6):
            cand_list = index[lvl].get(pkey(ch, lvl), [])
            while cand_list:
                cand = cand_list.pop()
                if cand["fact_id"] not in used_control_ids:
                    used_control_ids.add(cand["fact_id"])
                    return cand, lvl
        return None, None

    for ch in selected_changed:
        cand, lvl = try_match(ch)
        if cand is None:
            unmatched_changed.append(ch)
        else:
            pairs.append((ch, cand, lvl))

    # 若配对不足 300，从未抽中的 changed 中继续补
    if len(pairs) < MIN_PAIRS:
        remaining = [r for r in changed if r["fact_id"] not in {c["fact_id"] for c, _, _ in pairs} and r not in unmatched_changed]
        rng.shuffle(remaining)
        for ch in remaining:
            if len(pairs) >= MIN_PAIRS:
                break
            cand, lvl = try_match(ch)
            if cand is not None:
                pairs.append((ch, cand, lvl))

    # 名称补充（仅对照需要；changed 行已含名称）
    control_ids = [c["fact_id"] for _, c, _ in pairs]
    names = {}
    con = sqlite3.connect(f"file:{FINAL_DB.as_posix()}?mode=ro", uri=True)
    for i in range(0, len(control_ids), 500):
        chunk = control_ids[i : i + 500]
        q = ",".join("?" * len(chunk))
        for a in con.execute(
            f"SELECT fact_id, subject_name, object_name FROM research_assertions WHERE fact_id IN ({q})", chunk
        ):
            names[a[0]] = {"subject_name": a[1], "object_name": a[2]}
    con.close()

    out_csv = OUTDIR / "RELATION_CONTRACT_SAMPLE.csv"
    fields = [
        "sample_id", "pair_id", "sample_role", "fact_id",
        "subject_id", "subject_name", "subject_type", "predicate",
        "object_id", "object_name", "object_type",
        "stage_codes", "risk_tier", "semantic_status", "release_tier",
        "stratum_key", "match_level", "changed_set_full_tier", "changed_set_wo_tier",
        "seed_changed_sample", "seed_control_match",
    ]
    rows_out = []
    match_level_counts = Counter()
    for i, (ch, ct, lvl) in enumerate(pairs, 1):
        pair_id = f"RC-PAIR-{i:04d}"
        skey = "|".join(stratum_key(ch))
        match_level_counts[lvl] += 1
        rows_out.append(
            {
                "sample_id": f"RC-S-{i:04d}", "pair_id": pair_id, "sample_role": "changed",
                "fact_id": ch["fact_id"], "subject_id": ch["subject_id"],
                "subject_name": ch["subject_name"], "subject_type": ch["subject_type"],
                "predicate": ch["predicate"], "object_id": ch["object_id"],
                "object_name": ch["object_name"], "object_type": ch["object_type"],
                "stage_codes": ch["stage_codes"], "risk_tier": ch["risk_tier"],
                "semantic_status": ch["semantic_status"], "release_tier": ch["release_tier"],
                "stratum_key": skey, "match_level": "self",
                "changed_set_full_tier": ch["full_tier"], "changed_set_wo_tier": ch["wo_tier"],
                "seed_changed_sample": seed_changed, "seed_control_match": seed_control,
            }
        )
        rows_out.append(
            {
                "sample_id": f"RC-C-{i:04d}", "pair_id": pair_id, "sample_role": "control",
                "fact_id": ct["fact_id"], "subject_id": ct["subject_id"],
                "subject_name": names.get(ct["fact_id"], {}).get("subject_name"),
                "subject_type": ct["subject_type"], "predicate": ct["predicate"],
                "object_id": ct["object_id"],
                "object_name": names.get(ct["fact_id"], {}).get("object_name"),
                "object_type": ct["object_type"], "stage_codes": ct["stage_codes"],
                "risk_tier": ct["risk_tier"], "semantic_status": ct["semantic_status"],
                "release_tier": ct["release_tier"], "stratum_key": skey,
                "match_level": f"L{lvl}",
                "changed_set_full_tier": "", "changed_set_wo_tier": "",
                "seed_changed_sample": seed_changed, "seed_control_match": seed_control,
            }
        )
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows_out)

    def sha256_file(p: Path) -> str:
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    audit = {
        "audit_id": "RELATION_CONTRACT_SAMPLE_AUDIT",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment_id": "v3-08-independent-reference-relation-contract-sample",
        "master_seed": MASTER_SEED,
        "derived_seeds": {
            "relation_contract_changed_sample": seed_changed,
            "relation_contract_control_match": seed_control,
        },
        "seed_derivation": "int.from_bytes(SHA256('<task>|20260907')[:8],'big')",
        "inputs": {
            "changed_set": "submission_work/final_submission_v3/experiments/10_structural_validation/RELATION_CONTRACT_CHANGED_SET.csv (3412 行)",
            "control_pool": "现场确定性重放 Full vs w/o Relation Contract 状态相等且不在 3412 内的断言",
        },
        "databases": {
            "final": {"path": "data/release_databases/red_culture_stkg_final_v2.sqlite", "sha256": FINAL_DB_SHA256},
            "semantic": {"path": "data/release_databases/red_culture_stkg_semantic_v2.sqlite", "sha256": SEMANTIC_DB_SHA256},
        },
        "changed_set_strata": len(strata),
        "changed_target": TARGET_CHANGED,
        "changed_selected": len(selected_changed),
        "pairs_matched": len(pairs),
        "unmatched_changed": len(unmatched_changed),
        "match_level_counts": {f"L{k}": v for k, v in sorted(match_level_counts.items())},
        "match_level_legend": {
            "L1": "同 predicate+subject_type+object_type+stage_codes+risk_tier",
            "L2": "去 risk_tier",
            "L3": "去 stage_codes",
            "L4": "去 object_type",
            "L5": "仅同 predicate",
        },
        "changed_stratum_allocation_top10": sorted(alloc.items(), key=lambda kv: -kv[1])[:10],
        "changed_stratum_allocation_repr": {
            "allocations": len(alloc),
            "strata_covered_pct": round(100 * len(alloc) / len(strata), 2),
        },
        "reference_subset_148_verification": {
            "source_file": "submission_work/final_submission_v3/data/external_inputs/AI_GOLD_LABELS.csv（sha256 1190ed0d7a4ec16b34712293f47992d624788ba4734c2bfce4020d51de0a9c0f，712 行中 task_type=relation_semantic 为 148 行）",
            "saturation_evidence": "submission_work/final_submission_v2/experiments/05_ablation/ABLATION_PREDICTIONS.csv 中 component=Relation Contract 的 relation_semantic 共 296 行：variant='Full relation contract' correct=148/148，variant='w/o Relation Contract' correct=148/148，二者完全相同 → 该子集对关系契约组件区分力为 0（饱和），正是本抽样（从 3412 条全库变化记录重抽）的动机。",
        },
        "outputs": {
            "RELATION_CONTRACT_SAMPLE.csv": {"rows": len(rows_out), "sha256": sha256_file(out_csv)},
        },
        "notes": [
            "changed 样本全部满足 full_tier=contextual、wo_tier=strict_semantic（去掉契约后进入严格语义层），即论文所述 3412 条新增类型违例；judge 任务为盲评关系语义/类型相容性，不暴露该来源。",
            "对照与变化样本共享 stratum_key；match_level 标记放宽层级，L1 为完全同层匹配。",
            "L1 匹配数为 0 是结构性必然：契约通过与否由 (predicate, subject_type, object_type) 决定，与某 changed 记录完全同型组合且其余准入条件也相同的记录必然也违反契约、同样进入 3412 变化集；仅存的对照是 route/validation/provenance 等其他条件不同而未变化者。因此匹配实际锚定在 predicate+subject_type（L4 为主），object_type 与 changed 记录系统性不同，judge 分析与统计建模须控制该设计特征。",
        ],
    }
    audit_path = OUTDIR / "RELATION_CONTRACT_SAMPLE_AUDIT.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2, default=str)

    print("changed selected:", len(selected_changed), "pairs:", len(pairs), "unmatched:", len(unmatched_changed))
    print("match levels:", dict(match_level_counts))
    print("total output rows:", len(rows_out))


if __name__ == "__main__":
    main()
