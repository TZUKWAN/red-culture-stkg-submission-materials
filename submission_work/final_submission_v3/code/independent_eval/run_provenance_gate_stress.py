#!/usr/bin/env python3
"""GOAL.md 第十六节：Provenance Gate 实事求是 —— synthetic fault-injection stress test（negative-control）。

⚠ 实验性质声明（与真实语料实验严格区分）：
本实验是 **synthetic failure-injection stress test / fault injection / negative-control**。
全库确定性消融已证实：当前发布数据所有 strict_semantic 断言均带 provenance，
w/o Provenance Gate 的 changed_vs_full = 0 —— 该门在真实语料上无可观察增益，
定位为「发布安全不变量」。本实验通过在内存中程序化删除一部分 strict 断言的
provenance 引用（绝不写回数据库），检验 gate 能否 100% 阻止这些被注入故障的
断言滞留 strict layer。结果只证明 gate 机制有效，不构成真实数据上的性能声明。

设计：
- 发布库全程只读（file:...?mode=ro）；故障注入仅发生在内存中的重放副本。
- 三档注入比例：strict_semantic 断言的 1% / 5% / 20% 被移除全部 provenance 关联。
- 种子 BASE_SEED=20260907，逐档派生：sha256("20260907|provenance_gate_fault_injection|ratio=<r>")。
- Gate 重放逻辑逐行对齐 extract_relation_contract_replay.py（其本身逐行对齐
  v2 的 run_component_ablations.py structural_replay 第 436–596 行）：
  provenance_pass = provenance_count > 0；strict 需 route/契约/类型校验/provenance 全部通过。

产出（experiments/12_provenance_validation/）：
- PROVENANCE_GATE_FAULT_INJECTION.csv  注入清单（fact 标识、注入类型、注入前后 provenance 计数、派生种子）
- PROVENANCE_GATE_STRESS_TEST.csv      逐条 strict 断言：injected / gate_blocked / state_before / state_after
- PROVENANCE_GATE_STRESS_SUMMARY.json  各比例档：注入数、拦截数、拦截率、误伤数
- PROVENANCE_GATE_STRESS_TEST.md       中文实验说明（synthetic / negative-control 标注）
- PROVENANCE_GATE_STRESS_MANIFEST.json 配套 manifest（experiment_id / database_sha256 / 种子 / timestamp / 输出 sha256）

断言级验证（脚本内 assert）：
1. 基线重放三层计数 == 112158 / 268047 / 43945（总 424150）；
2. 对照组零变化：每个比例档下，所有未被注入的断言 state_after == state_before（全量 424150 条逐条验证）；
3. 拦截率 100%：所有被注入断言 gate_blocked == 1（strict → contextual，不得滞留 strict layer）。

不修改任何已有文件。数据库只读。
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import random
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\REDCULTUREDATA\投稿材料_代码数据整理包")
FINAL_DB = ROOT / "data" / "release_databases" / "red_culture_stkg_final_v2.sqlite"
SEMANTIC_DB = ROOT / "data" / "release_databases" / "red_culture_stkg_semantic_v2.sqlite"
EXTERNAL = ROOT / "submission_work" / "final_submission_v3" / "data" / "external_inputs"
SCRIPT_284 = ROOT / "code" / "scripts" / "284_materialize_stkg_v2_research_base.py"
OUTDIR = ROOT / "submission_work" / "final_submission_v3" / "experiments" / "12_provenance_validation"

FINAL_DB_SHA256 = "a199d736b9ec436b3d5f244e874718604b6c84955a505f31f90a3e28c51a9ee7"
SEMANTIC_DB_SHA256 = "fbfb6529335e1c838270c63eee53c92a568c2b075354f7ad5f9d5815b88bb377"

BASE_SEED = 20260907
RATIOS = [0.01, 0.05, 0.20]
EXPECTED_TIERS = {"strict_semantic": 112158, "contextual": 268047, "unresolved": 43945}

EXPERIMENT_ID = "v3-12-provenance-gate-fault-injection-stress-test"


def load_research_base():
    """导入 284 脚本作为模块（stkg_contract/stkg_v2_semantics 由 external_inputs 提供）。"""
    sys.path.insert(0, str(EXTERNAL))
    spec = importlib.util.spec_from_file_location("research_base_284", SCRIPT_284)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def derive_seed(ratio: float) -> int:
    """由 BASE_SEED 确定性派生每档种子。"""
    key = f"{BASE_SEED}|provenance_gate_fault_injection|ratio={ratio}"
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tier_of(route_pass: bool, predicate: str, subj_val: str, obj_val: str,
            contract_pass: bool, provenance_pass: bool) -> str:
    """与 v2 structural_replay 完全相同的 tier 判定（Full framework 语义）。"""
    strict = (
        route_pass
        and not predicate.startswith("raw:")
        and subj_val == "validated"
        and obj_val == "validated"
        and contract_pass
        and provenance_pass
    )
    return "strict_semantic" if strict else ("contextual" if route_pass else "unresolved")


def main() -> None:
    started_at = datetime.now(timezone.utc)
    rb = load_research_base()

    con = sqlite3.connect(f"file:{SEMANTIC_DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("ATTACH DATABASE ? AS fin", (f"file:{FINAL_DB.as_posix()}?mode=ro",))

    # 与 v2 structural_replay / extract_relation_contract_replay.py 完全相同的查询
    query = (
        "with provenance as ("
        " select fact_id,count(*) provenance_count,"
        " max(case when member_status not like '%repaired%' and member_status not like '%rewrite%' "
        " and member_status not like '%preserved%' then 1 else 0 end) has_nonrepair"
        " from fin.research_assertion_provenance group by fact_id) "
        "select a.fact_id,a.subject_id source_subject_id,a.object_id source_object_id,"
        "a.source_subject_type,a.source_object_type,a.predicate,a.time_start,a.time_role source_time_role,"
        "a.time_owner_id source_time_owner_id,a.space_role source_space_role,a.space_owner_id source_space_owner_id,"
        "a.semantic_status,a.risk_tier,sp.canonical_anchor_id,"
        "ms.canonical_entity_id subject_id,ms.canonical_entity_type subject_type,"
        "mo.canonical_entity_id object_id,mo.canonical_entity_type object_type,"
        "mto.canonical_entity_id time_owner_canonical_id,mso.canonical_entity_id space_owner_canonical_id,"
        "es.effective_entity_type source_subject_effective_type,es.type_validation_status subject_validation,"
        "eo.effective_entity_type source_object_effective_type,eo.type_validation_status object_validation,"
        "p.provenance_count,p.has_nonrepair,"
        "f.research_tier release_tier "
        "from v2_assertion_scopes a "
        "join v2_entity_identity_map ms on ms.source_entity_id=a.subject_id "
        "join v2_entity_identity_map mo on mo.source_entity_id=a.object_id "
        "left join v2_entity_identity_map mto on mto.source_entity_id=a.time_owner_id "
        "left join v2_entity_identity_map mso on mso.source_entity_id=a.space_owner_id "
        "join v2_entity_type_effective es on es.entity_id=a.subject_id "
        "join v2_entity_type_effective eo on eo.entity_id=a.object_id "
        "join v2_spatial_projection sp on sp.fact_id=a.fact_id "
        "join fin.research_assertions f on f.fact_id=a.fact_id "
        "join provenance p on p.fact_id=a.fact_id order by a.fact_id"
    )

    # ---- 第 1 遍：Full framework 基线重放（provenance gate 开启，无任何注入）----
    facts = {}  # fact_id -> dict(components + state_before)
    tiers_counter: Counter = Counter()
    for row in con.execute(query):
        fact_id = str(row["fact_id"])
        subject_type = str(row["subject_type"])      # identity projection 开启（Full framework）
        object_type = str(row["object_type"])
        contract_pass = rb.relation_domain_range_pass_v2(row["predicate"], subject_type, object_type)
        route_pass = str(row["semantic_status"]) == "auto_accepted"
        provenance_count = int(row["provenance_count"])
        provenance_pass = provenance_count > 0
        tier = tier_of(route_pass, str(row["predicate"]),
                       str(row["subject_validation"]), str(row["object_validation"]),
                       contract_pass, provenance_pass)
        tiers_counter[tier] += 1
        facts[fact_id] = {
            "fact_id": fact_id,
            "predicate": str(row["predicate"]),
            "route_pass": route_pass,
            "subject_validation": str(row["subject_validation"]),
            "object_validation": str(row["object_validation"]),
            "contract_pass": contract_pass,
            "provenance_count": provenance_count,
            "state_before": tier,
        }
    con.close()

    # 基线核对：发布三层计数
    assert dict(tiers_counter) == EXPECTED_TIERS, (
        f"基线三层计数与发布值不符: {dict(tiers_counter)} != {EXPECTED_TIERS}"
    )
    total = sum(tiers_counter.values())
    strict_ids = sorted(fid for fid, d in facts.items() if d["state_before"] == "strict_semantic")
    assert len(strict_ids) == EXPECTED_TIERS["strict_semantic"]

    # ---- 第 2 步：三档 fault injection（内存操作，绝不写回数据库）----
    injection_rows = []   # PROVENANCE_GATE_FAULT_INJECTION.csv
    stress_rows = []      # PROVENANCE_GATE_STRESS_TEST.csv（逐条 strict 断言）
    summary_ratios = {}

    for ratio in RATIOS:
        seed = derive_seed(ratio)
        rng = random.Random(seed)
        n_inject = round(len(strict_ids) * ratio)
        injected = set(rng.sample(strict_ids, n_inject))

        blocked = 0
        control_changed = 0
        control_total = 0
        for fid, d in facts.items():
            is_injected = fid in injected
            # gate 重放：被注入者 provenance_count 视为 0（内存故障注入）
            provenance_pass_after = (d["provenance_count"] > 0) if not is_injected else False
            state_after = tier_of(d["route_pass"], d["predicate"],
                                  d["subject_validation"], d["object_validation"],
                                  d["contract_pass"], provenance_pass_after)
            gate_blocked = int(is_injected and state_after != "strict_semantic")
            if is_injected:
                blocked += gate_blocked
                injection_rows.append({
                    "ratio_tier": f"{ratio:.0%}",
                    "fact_id": fid,
                    "predicate": d["predicate"],
                    "injection_type": "remove_all_provenance",
                    "provenance_count_before": d["provenance_count"],
                    "provenance_count_after": 0,
                    "derived_seed": seed,
                })
            else:
                control_total += 1
                # 对照组零变化：断言级验证（全量，含 contextual/unresolved）
                assert state_after == d["state_before"], (
                    f"对照组断言状态被误伤: fact_id={fid} "
                    f"{d['state_before']} -> {state_after} (ratio={ratio})"
                )
                control_changed += int(state_after != d["state_before"])
            if d["state_before"] == "strict_semantic":
                stress_rows.append({
                    "ratio_tier": f"{ratio:.0%}",
                    "fact_id": fid,
                    "predicate": d["predicate"],
                    "injected": int(is_injected),
                    "gate_blocked": gate_blocked,
                    "state_before": d["state_before"],
                    "state_after": state_after,
                })

        # 拦截率 100%：所有注入断言必须被 gate 移出 strict layer
        assert blocked == n_inject, (
            f"ratio={ratio}: 拦截数 {blocked} != 注入数 {n_inject}，存在故障断言滞留 strict layer"
        )
        assert control_changed == 0

        summary_ratios[f"{ratio:.0%}"] = {
            "ratio": ratio,
            "derived_seed": seed,
            "strict_layer_size": len(strict_ids),
            "injected_count": n_inject,
            "blocked_count": blocked,
            "block_rate": blocked / n_inject if n_inject else None,
            "false_positive_count_control_group": control_changed,
            "control_group_size_all_assertions": control_total,
            "state_transition_of_injected": "strict_semantic -> contextual",
        }

    # ---- 第 3 步：落盘 ----
    OUTDIR.mkdir(parents=True, exist_ok=True)

    inj_csv = OUTDIR / "PROVENANCE_GATE_FAULT_INJECTION.csv"
    with open(inj_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[
            "ratio_tier", "fact_id", "predicate", "injection_type",
            "provenance_count_before", "provenance_count_after", "derived_seed",
        ])
        w.writeheader()
        w.writerows(injection_rows)

    stress_csv = OUTDIR / "PROVENANCE_GATE_STRESS_TEST.csv"
    with open(stress_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[
            "ratio_tier", "fact_id", "predicate",
            "injected", "gate_blocked", "state_before", "state_after",
        ])
        w.writeheader()
        w.writerows(stress_rows)

    finished_at = datetime.now(timezone.utc)
    summary = {
        "experiment_id": EXPERIMENT_ID,
        "experiment_nature": (
            "synthetic failure-injection stress test / fault injection / negative-control — "
            "与真实语料实验严格区分；不构成真实数据上的性能声明"
        ),
        "motivation": (
            "全库确定性消融显示 w/o Provenance Gate 的 changed_vs_full=0：当前发布数据所有 "
            "strict_semantic 断言均带 provenance，该门在真实数据上无可观察增益，定位为「发布安全不变量」。"
            "本实验在内存中程序化删除部分 strict 断言的 provenance 引用（数据库全程只读），"
            "检验 gate 能否 100% 阻止故障断言滞留 strict layer。"
        ),
        "base_seed": BASE_SEED,
        "seed_derivation": "sha256('{BASE_SEED}|provenance_gate_fault_injection|ratio=<r>')[:8] big-endian",
        "baseline_tier_counts_replayed": dict(tiers_counter),
        "baseline_tier_counts_expected": EXPECTED_TIERS,
        "baseline_match": dict(tiers_counter) == EXPECTED_TIERS,
        "total_assertions_replayed": total,
        "per_ratio": summary_ratios,
        "verification_asserts": {
            "baseline_tier_counts_match_release": True,
            "control_group_zero_change_all_assertions": True,
            "block_rate_100pct_all_ratios": True,
        },
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
    }
    summary_path = OUTDIR / "PROVENANCE_GATE_STRESS_SUMMARY.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # ---- 第 4 步：中文说明文档 ----
    md_path = OUTDIR / "PROVENANCE_GATE_STRESS_TEST.md"
    lines = [
        "# Provenance Gate 压力测试（synthetic fault-injection stress test）",
        "",
        "> ⚠ **实验性质声明**：本实验是 **synthetic failure-injection stress test**",
        "> （故障注入 / fault injection / negative-control），与真实语料实验**严格区分**。",
        "> 其结果只证明 Provenance Gate 机制本身有效，**不构成**「该门在当前真实数据上",
        "> 显著提高性能」的声明。",
        "",
        "## 1. 背景与定位（实事求是）",
        "",
        "全库确定性消融（experiments/10_structural_validation 确定性重放，逐行对齐 v2",
        "`run_component_ablations.py`）显示：",
        "",
        "- **w/o Provenance Gate 的 `changed_vs_full = 0`**。",
        "- 原因：当前发布数据本身**没有无 provenance 的断言**——所有 112 158 条",
        "  `strict_semantic` 断言均带有至少一条 `research_assertion_provenance` 记录",
        "  （该表共 466 312 行）。",
        "",
        "因此，Provenance Gate 在论文中的正确表述是：**它是一个发布安全不变量**",
        "（release safety invariant），而不是在当前语料上产生可观察增益的组件。",
        "为检验该不变量机制是否真正有效，特设计本 negative-control 压力测试。",
        "",
        "## 2. 方法",
        "",
        "1. **只读基线重放**：以只读模式（`file:...?mode=ro`）打开发布库，逐行复用",
        "   `extract_relation_contract_replay.py` 的连接与查询方式，重放 Full framework",
        "   三层分层，基线计数与发布值核对（strict_semantic / contextual / unresolved",
        f"   = 112 158 / 268 047 / 43 945，总 424 150）：**一致**。",
        "2. **故障注入（仅内存，绝不写回数据库）**：对 `strict_semantic` 层按三档比例",
        "   **1% / 5% / 20%** 随机抽取断言，程序化地将其全部 provenance 关联视为已删除",
        f"   （`provenance_count := 0`）。基础种子 **{BASE_SEED}**，每档由",
        "   `sha256('20260907|provenance_gate_fault_injection|ratio=<r>')` 派生独立种子，",
        "   注入清单落盘 `PROVENANCE_GATE_FAULT_INJECTION.csv`（含 fact 标识、注入类型、",
        "   注入前后 provenance 计数、派生种子）。",
        "3. **Gate 重放**：按 v2 原始判定 `provenance_pass = provenance_count > 0` 重放",
        "   Provenance Gate，检验被注入断言是否被移出 strict layer。",
        "",
        "## 3. 结果",
        "",
        "| 注入比例 | 注入数 | 拦截数 | 拦截率 | 对照组误伤数 |",
        "|---|---|---|---|---|",
    ]
    for ratio in RATIOS:
        s = summary_ratios[f"{ratio:.0%}"]
        lines.append(
            f"| {ratio:.0%} | {s['injected_count']} | {s['blocked_count']} "
            f"| {s['block_rate']:.4f} | {s['false_positive_count_control_group']} |"
        )
    lines += [
        "",
        "- **三档拦截率均为 100%**：所有被注入故障的断言均被 gate 从 `strict_semantic`",
        "  降级为 `contextual`（`route_pass` 仍为真），无一滞留 strict layer。",
        "- **对照组零变化**：每个比例档下，对全量 424 150 条断言中**未被注入**的部分",
        "  逐条断言级验证 `state_after == state_before`（脚本内 `assert`），误伤数为 0。",
        "  逐条记录见 `PROVENANCE_GATE_STRESS_TEST.csv`（覆盖全部 strict 层断言的",
        "  `injected / gate_blocked / state_before / state_after`）。",
        "",
        "## 4. 结论",
        "",
        "Provenance Gate 作为**发布安全不变量**机制有效：一旦断言失去全部 provenance",
        "支撑，gate 能 100% 阻止其进入/滞留 strict layer，且不误伤正常断言。",
        "结合真实数据上 `changed_vs_full = 0` 的事实，该门的价值在于**防御未来数据",
        "回归**（任何无来源断言不得进入 strict 发布层），而非提升当前语料指标。",
        "",
        "## 5. 可复现性",
        "",
        f"- 脚本：`code/independent_eval/run_provenance_gate_stress.py`",
        f"- 基础种子：{BASE_SEED}（逐档派生见 `PROVENANCE_GATE_STRESS_SUMMARY.json`）",
        "- 数据库：`data/release_databases/red_culture_stkg_final_v2.sqlite`（只读）+",
        "  `red_culture_stkg_semantic_v2.sqlite`（只读 ATTACH），sha256 见 manifest。",
        "- 配套 manifest：`PROVENANCE_GATE_STRESS_MANIFEST.json`（experiment_id、",
        "  database_sha256、种子、timestamp、全部输出 sha256）。",
        "",
    ]
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # ---- 第 5 步：manifest ----
    manifest = {
        "manifest_id": "PROVENANCE_GATE_STRESS_MANIFEST",
        "experiment_id": EXPERIMENT_ID,
        "experiment_nature": "synthetic failure-injection stress test / fault injection / negative-control",
        "created_at_utc": finished_at.isoformat(),
        "script": "submission_work/final_submission_v3/code/independent_eval/run_provenance_gate_stress.py",
        "base_seed": BASE_SEED,
        "derived_seeds": {f"{r:.0%}": derive_seed(r) for r in RATIOS},
        "databases": {
            "final": {"path": "data/release_databases/red_culture_stkg_final_v2.sqlite",
                      "sha256": sha256_file(FINAL_DB)},
            "semantic": {"path": "data/release_databases/red_culture_stkg_semantic_v2.sqlite",
                         "sha256": sha256_file(SEMANTIC_DB)},
        },
        "database_sha256_reference": {
            "final": FINAL_DB_SHA256,
            "semantic": SEMANTIC_DB_SHA256,
        },
        "database_open_mode": "read-only (file:...?mode=ro; ATTACH 只读 URI); 故障注入仅在内存，绝不写回",
        "outputs": {
            p.name: {"sha256": sha256_file(p), "bytes": p.stat().st_size}
            for p in (inj_csv, stress_csv, summary_path, md_path)
        },
    }
    manifest_path = OUTDIR / "PROVENANCE_GATE_STRESS_MANIFEST.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print("baseline tiers:", dict(tiers_counter), "match release:", dict(tiers_counter) == EXPECTED_TIERS)
    for ratio in RATIOS:
        s = summary_ratios[f"{ratio:.0%}"]
        print(f"ratio={ratio:.0%}: injected={s['injected_count']} blocked={s['blocked_count']} "
              f"block_rate={s['block_rate']:.4f} false_positives={s['false_positive_count_control_group']}")
    print("outputs written to:", OUTDIR)


if __name__ == "__main__":
    main()
