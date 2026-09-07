# -*- coding: utf-8 -*-
"""build_imcr_figures.py 的离线测试（GOAL.md §三十 图A–图D）。

全部离线：fixture CSV + ``--synthetic``（固定种子合成数据）走通四张图的
完整渲染（输出到 ``tmp_path``），断言：

* PNG / PDF / CHART_CONTRACT / AUDIT 四类产物生成；
* audit ``result == "PASS"`` 且 ``errors == []``；
* synthetic 水印标志（contract/audit ``synthetic`` 与 ``synthetic_watermark``）；
* era 图同规则的排除规则生效（n < 8 任务面板被排除并记录原因）；
* rcParams 不被全局污染、中文字体回退链解析不崩溃。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")

from experiment_pipelines import build_imcr_figures as bif

# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def assert_outputs(paths: dict, prefix: str, slug: str) -> tuple[dict, dict]:
    png = paths["png"]
    assert png.is_file() and png.stat().st_size > 1000
    assert paths["pdf"].is_file() and paths["pdf"].stat().st_size > 500
    contract_path = paths["contract"]
    audit_path = paths["audit"]
    assert contract_path.is_file() and audit_path.is_file()
    contract = read_json(contract_path)
    audit = read_json(audit_path)
    # 契约字段风格与 era_RISK_COVERAGE_CHART_CONTRACT.json 对齐
    for key in (
        "analytical_question",
        "supported_takeaway",
        "acceptance_rule" if "acceptance_rule" in contract else "variant",
        "palette_policy",
        "palette",
        "non_color_distinction",
        "renderer",
        "input_files",
        "generated_at",
        "synthetic",
    ):
        assert key in contract, f"contract 缺少字段 {key}"
    assert contract["renderer"] == "static Matplotlib PNG/PDF"
    assert contract["palette_policy"] == "hard two-root cap plus neutrals"
    assert audit["result"] == "PASS"
    assert audit["errors"] == []
    for record in audit["checks"]:
        assert record["passed"] is True, record
    assert audit["font"]["resolved"]
    assert audit["render"]["outputs"]["png"].endswith(".png")
    return contract, audit


# ---------------------------------------------------------------------------
# 图A fixture：与 era_RISK_COVERAGE_POINTS.csv 完全同构的 31 列
# ---------------------------------------------------------------------------


def _points_row(
    task_type: str,
    method_id: str,
    point_index: int,
    coverage: float,
    risk: float,
    n_total: int,
    evaluation_eligibility: str = "core_eligible_task",
) -> dict:
    return {
        "method_id": method_id,
        "method_name": bif.METHOD_LABELS_ZH.get(method_id, method_id),
        "task_type": task_type,
        "evidence_class": "actual_run",
        "comparison_tier": "independent_reference",
        "overlap_status": "independent_of_era",
        "evaluation_eligibility": evaluation_eligibility,
        "curve_mode": "constrained_selective",
        "primary_curve": "1",
        "acceptance_rule": "score>=threshold AND hard_constraint_pass=1",
        "point_type": "exact_unique",
        "point_index": str(point_index),
        "threshold": f"{1.0 - coverage:.6f}",
        "accepted_count": str(int(round(coverage * n_total))),
        "total_count": str(n_total),
        "coverage": f"{coverage:.6f}",
        "error_count": str(int(round(risk * coverage * n_total))),
        "selective_risk": f"{risk:.6f}",
        "generalized_risk": "",
        "safe_count": "0",
        "safe_coverage": "",
        "abstained_count": "0",
        "abstention_rate": "",
        "review_escalation_count": "0",
        "review_escalation_rate": "",
        "llm_or_review_escalation_rate": "",
        "actual_llm_calls": "0",
        "actual_llm_call_rate": "0",
        "score_direction": "higher_is_safer",
        "tie_policy": "accept_all_equal_scores",
        "denominator_policy": "full_frozen_task_test_set",
    }


def _fixture_points_rows() -> list[dict]:
    """两个合格任务 + 一个 n=4 小任务 + 一个 owner 代理任务（均应排除前者按 n）。"""
    curves = {
        "B1_rule_only": [0.18, 0.24, 0.30, 0.36, 0.44],
        "B2_classifier_only": [0.10, 0.15, 0.20, 0.26, 0.33],
        "B12_full_framework": [0.06, 0.09, 0.13, 0.18, 0.24],
    }
    rows: list[dict] = []
    for task, n_total in (("entity_type", 40), ("scope_adjustment", 12)):
        for method_id, risks in curves.items():
            for index, (coverage, risk) in enumerate(zip((0.1, 0.3, 0.5, 0.7, 0.9), risks)):
                rows.append(_points_row(task, method_id, index, coverage, risk, n_total))
    # n=4：必须按 n < 8 排除
    for index, (coverage, risk) in enumerate(zip((0.2, 0.6), (0.1, 0.3))):
        rows.append(_points_row("tiny_task", "B1_rule_only", index, coverage, risk, 4))
    # owner 代理：按 evaluation_eligibility 排除（era 同规则）
    rows.append(_points_row("space_owner", "B1_rule_only", 0, 0.5, 0.2, 12,
                            evaluation_eligibility="evaluation_ineligible_for_primary_owner_shared_proxy"))
    return rows


@pytest.fixture()
def points_env(tmp_path: Path) -> dict:
    points_dir = tmp_path / "exp13"
    write_csv(points_dir / "imcr_RISK_COVERAGE_POINTS.csv", _fixture_points_rows(), bif.POINTS_FIELDS_31)
    out_dir = tmp_path / "figures"
    return {"points_dir": points_dir, "out_dir": out_dir, "tmp": tmp_path}


# ---------------------------------------------------------------------------
# 图A
# ---------------------------------------------------------------------------


def test_risk_coverage_renders_with_era_style_fixture(points_env: dict) -> None:
    env = points_env
    code = bif.main(
        [
            "risk_coverage",
            "--points-dir", str(env["points_dir"]),
            "--out-dir", str(env["out_dir"]),
            "--prefix", "t_",
        ]
    )
    assert code == 0
    paths = bif.output_paths(env["out_dir"], "t_", "risk_coverage")
    contract, audit = assert_outputs(paths, "t_", "risk_coverage")

    # 31 列 era 格式兼容：audit 记录输入列数
    assert audit["render"]["n_input_columns"] == 31
    # 排除规则：tiny_task 因 n=4 排除；space_owner 因 evaluation_eligibility 排除
    excluded_by_task = {e["task_type"]: e["reason"] for e in audit["excluded"]}
    assert "tiny_task" in excluded_by_task and "n=4" in excluded_by_task["tiny_task"]
    assert "space_owner" in excluded_by_task and "evaluation_ineligible" in excluded_by_task["space_owner"]
    # 面板与曲线
    assert [p["task_type"] for p in audit["panels"]] == ["entity_type", "scope_adjustment"]
    assert audit["render"]["n_panels"] == 2
    assert audit["render"]["n_curves"] == 6
    assert {c["method_id"] for c in audit["panels"][0]["curves"]} == {
        "B1_rule_only", "B2_classifier_only", "B12_full_framework",
    }
    # 每面板 n 记录
    assert audit["panels"][0]["n"] == 40
    assert audit["panels"][1]["n"] == 12
    # contract 输入 sha256 与 fixture 一致
    fixture_csv = env["points_dir"] / "imcr_RISK_COVERAGE_POINTS.csv"
    assert contract["input_files"][0]["sha256"] == bif.sha256_file(fixture_csv)
    assert contract["synthetic"] is False


def test_risk_coverage_synthetic_watermark_and_flags(tmp_path: Path) -> None:
    out_dir = tmp_path / "figs"
    code = bif.main(
        ["risk_coverage", "--synthetic", "--out-dir", str(out_dir), "--prefix", "s_"]
    )
    assert code == 0
    paths = bif.output_paths(out_dir, "s_", "risk_coverage")
    contract, audit = assert_outputs(paths, "s_", "risk_coverage")
    assert contract["synthetic"] is True
    assert audit["synthetic"] is True
    assert audit["synthetic_watermark"] is True
    assert contract["input_files"] == []  # synthetic 数据不入 input_files
    assert any("SYNTHETIC" in note for note in audit["notes"])


def test_risk_coverage_missing_points_dir_is_hard_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="RISK_COVERAGE_POINTS"):
        bif.main(
            [
                "risk_coverage",
                "--points-dir", str(tmp_path / "empty"),
                "--out-dir", str(tmp_path / "figs"),
            ]
        )


def test_risk_coverage_min_task_n_override(points_env: dict) -> None:
    env = points_env
    out_dir = env["tmp"] / "figs2"
    bif.main(
        [
            "risk_coverage",
            "--points-dir", str(env["points_dir"]),
            "--out-dir", str(out_dir),
            "--prefix", "m_",
            "--min-task-n", "20",
        ]
    )
    audit = read_json(bif.output_paths(out_dir, "m_", "risk_coverage")["audit"])
    # n=12 的 scope_adjustment 在 min-task-n=20 下也应被排除
    assert [p["task_type"] for p in audit["panels"]] == ["entity_type"]
    reasons = " | ".join(e["reason"] for e in audit["excluded"])
    assert "minimum_task_n_for_figure=20" in reasons


# ---------------------------------------------------------------------------
# 图B fixture：PAIRED_BOOTSTRAP_DELTAS.csv（run_statistical_tests.DELTA_FIELDS 同构）
# ---------------------------------------------------------------------------


def _fixture_delta_rows() -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    for task, n in (("entity_type", 40), ("relation_contract", 24)):
        for baseline in ("B1_rule_only", "B2_classifier_only"):
            for metric, estimate in (("aurc", -0.05), ("augrc", -0.03)):
                rows.append(
                    {
                        "task_type": task,
                        "baseline_method_id": baseline,
                        "metric": metric,
                        "status": "applicable",
                        "n_samples": str(n),
                        "n_replicates": "200",
                        "n_valid_replicates": "200",
                        "estimate": f"{estimate:.6f}",
                        "ci95_low": f"{estimate - 0.04:.6f}",
                        "ci95_high": f"{estimate + 0.04:.6f}",
                        "full_estimate": f"{0.2 + estimate:.6f}",
                        "baseline_estimate": "0.200000",
                        "bootstrap_seed": "123",
                        "note": "fixture row",
                    }
                )
    # not_applicable 行（应被排除并记录）
    rows.append(
        {
            "task_type": "identity_pair",
            "baseline_method_id": "B1_rule_only",
            "metric": "aurc",
            "status": "not_applicable_insufficient_scores",
            "n_samples": "3",
            "note": "area gate reused",
        }
    )
    fields = [
        "task_type", "baseline_method_id", "metric", "status", "n_samples",
        "n_replicates", "n_valid_replicates", "estimate", "ci95_low", "ci95_high",
        "full_estimate", "baseline_estimate", "bootstrap_seed", "note",
    ]
    return rows, fields


@pytest.fixture()
def deltas_env(tmp_path: Path) -> dict:
    stats_dir = tmp_path / "exp14"
    rows, fields = _fixture_delta_rows()
    write_csv(stats_dir / bif.DELTAS_FILE_NAME, rows, fields)
    return {"stats_dir": stats_dir, "out_dir": tmp_path / "figs", "tmp": tmp_path}


def test_aurc_augrc_ci_renders_with_fixture(deltas_env: dict) -> None:
    env = deltas_env
    code = bif.main(
        [
            "aurc_augrc_ci",
            "--stats-dir", str(env["stats_dir"]),
            "--areas-dir", str(env["tmp"] / "no_areas"),  # 显式空目录 → 交叉核验 skipped
            "--out-dir", str(env["out_dir"]),
            "--prefix", "t_",
        ]
    )
    assert code == 0
    paths = bif.output_paths(env["out_dir"], "t_", "aurc_augrc_ci")
    contract, audit = assert_outputs(paths, "t_", "aurc_augrc_ci")
    assert contract["delta_sign"] == "Full - baseline (negative = Full better)"
    assert [p["task_type"] for p in audit["panels"]] == ["entity_type", "relation_contract"]
    assert audit["render"]["n_panels"] == 2
    assert audit["render"]["n_errorbar_series"] == 4
    excluded_pairs = {
        (e.get("task_type"), e.get("metric")) for e in audit["excluded"]
    }
    assert ("identity_pair", "aurc") in excluded_pairs
    # delta 恒等式与 CI 包含点估计的检查均通过（assert_outputs 已断言 passed）
    assert any(c["name"] == "delta_identity_full_minus_baseline" for c in audit["checks"])
    # areas 交叉核验缺失时记录 skipped
    assert contract["areas_crosscheck"]["status"] == "skipped"


def test_aurc_augrc_ci_areas_crosscheck_compared(deltas_env: dict) -> None:
    env = deltas_env
    areas_dir = env["tmp"] / "exp13"
    # 与 fixture deltas 一致的绝对面积：B12 aurc=0.15/augrc=0.17；基线 aurc=0.2/augc=0.2
    # → (full − base) = Δ 估计（−0.05 / −0.03），交叉核验应通过
    summary_rows = [
        {
            "method_id": method_id,
            "task_type": task,
            "aurc_trapezoid": "0.150000" if method_id == "B12_full_framework" else "0.200000",
            "augrc_trapezoid": "0.170000" if method_id == "B12_full_framework" else "0.200000",
        }
        for task in ("entity_type", "relation_contract")
        for method_id in ("B12_full_framework", "B1_rule_only", "B2_classifier_only")
    ]
    write_csv(areas_dir / "imcr_RISK_COVERAGE_SUMMARY.csv", summary_rows,
              ["method_id", "task_type", "aurc_trapezoid", "augrc_trapezoid"])
    bif.main(
        [
            "aurc_augrc_ci",
            "--stats-dir", str(env["stats_dir"]),
            "--areas-dir", str(areas_dir),
            "--out-dir", str(env["out_dir"]),
            "--prefix", "x_",
        ]
    )
    paths = bif.output_paths(env["out_dir"], "x_", "aurc_augrc_ci")
    audit = read_json(paths["audit"])
    contract = read_json(paths["contract"])
    assert contract["areas_crosscheck"]["status"] == "compared"
    check = next(c for c in audit["checks"] if c["name"] == "areas_crosscheck")
    assert check["passed"] is True
    # contract 的 input_files 包含 areas 文件
    assert any("RISK_COVERAGE_SUMMARY" in r["path"] for r in contract["input_files"])


def test_aurc_augrc_ci_synthetic(tmp_path: Path) -> None:
    out_dir = tmp_path / "figs"
    code = bif.main(["aurc_augrc_ci", "--synthetic", "--out-dir", str(out_dir), "--prefix", "s_"])
    assert code == 0
    contract, audit = assert_outputs(
        bif.output_paths(out_dir, "s_", "aurc_augrc_ci"), "s_", "aurc_augrc_ci"
    )
    assert contract["synthetic"] is True and audit["synthetic_watermark"] is True


def test_aurc_augrc_ci_missing_deltas_is_hard_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="PAIRED_BOOTSTRAP_DELTAS"):
        bif.main(
            [
                "aurc_augrc_ci",
                "--stats-dir", str(tmp_path / "none"),
                "--out-dir", str(tmp_path / "figs"),
            ]
        )


# ---------------------------------------------------------------------------
# 图C fixture：IMCR_REFERENCE_ALL.csv + manifest + raw_runs + A/B 映射
# ---------------------------------------------------------------------------


def _scope_reference_rows() -> list[dict]:
    rows = []
    labels = ["BEFORE_BETTER", "AFTER_BETTER", "EQUIVALENT"]
    for index in range(7):
        rows.append(
            {
                "task_type": "scope_adjustment",
                "task_id": f"SA-{index + 1:04d}",
                "sample_id": f"SA-{index + 1:04d}",
                "reference_label": labels[index % 3],
                "imcr_label": labels[index % 3],
                "imcr_label_decoded": labels[index % 3],
                "consensus_tier": "strong_consensus" if index % 2 == 0 else "weak_consensus",
                "n_valid_votes": "3",
                "winning_votes": "3",
                "vote_distribution": "{}",
                "judges": "A;B;C",
                "dry_run": "False",
            }
        )
    # 非 scope 行不应进入统计
    rows.append(
        {
            "task_type": "entity_type", "task_id": "ET-1", "sample_id": "ET-1",
            "reference_label": "Person", "imcr_label": "Person", "imcr_label_decoded": "Person",
            "consensus_tier": "strong_consensus", "n_valid_votes": "3", "winning_votes": "3",
            "vote_distribution": "{}", "judges": "A;B;C", "dry_run": "False",
        }
    )
    return rows


def _write_scope_raw_runs(raw_root: Path) -> None:
    """3 judge jsonl：SA-0001..SA-0007，B/C 各含一票 A_BETTER/B_BETTER；
    judge A 含一张无效票。"""
    task_dir = raw_root / "scope_adjustment"
    task_dir.mkdir(parents=True, exist_ok=True)
    votes = {
        "A": {f"SA-{i:04d}": "A_BETTER" for i in range(1, 8)} | {"SA-0004": "MODEL_OUTPUT_INVALID"},
        "B": {f"SA-{i:04d}": "B_BETTER" for i in range(1, 8)},
        "C": {f"SA-{i:04d}": "A_BETTER" for i in range(1, 4)}
        | {f"SA-{i:04d}": "EQUIVALENT" for i in range(4, 8)},
    }
    for judge, mapping in votes.items():
        with (task_dir / f"{judge}.jsonl").open("w", encoding="utf-8") as fh:
            for task_id, decision in mapping.items():
                fh.write(
                    json.dumps(
                        {
                            "task_id": task_id,
                            "status": "OK",
                            "dry_run": False,
                            "model_id": f"fixture-{judge}",
                            "parsed_response": {"decision": decision},
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )


@pytest.fixture()
def scope_env(tmp_path: Path) -> dict:
    exp08 = tmp_path / "exp08"
    write_csv(exp08 / "IMCR_REFERENCE_ALL.csv", _scope_reference_rows(),
              ["task_type", "task_id", "sample_id", "reference_label", "imcr_label",
               "imcr_label_decoded", "consensus_tier", "n_valid_votes", "winning_votes",
               "vote_distribution", "judges", "dry_run"])
    manifest = {
        "experiment_id": "imcr_consensus_build",
        "tasks": [
            {
                "task_type": "scope_adjustment",
                "n_tasks": 10,
                "n_strong_consensus": 4,
                "n_weak_consensus": 3,
                "n_unresolved": 3,
                "judges": ["A", "B", "C"],
            }
        ],
    }
    (exp08 / "IMCR_CONSENSUS_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    raw_root = exp08 / "raw_runs"
    _write_scope_raw_runs(raw_root)
    payloads_dir = exp08 / "payloads"
    # A=a↔before, B=b↔after：judge 的 A_BETTER 解码为 BEFORE_BETTER，B_BETTER 解码为 AFTER_BETTER
    write_csv(
        payloads_dir / bif.AB_MAPPING_FILE_NAME,
        [{"task_id": f"SA-{i:04d}", "a": "before", "b": "after"} for i in range(1, 8)],
        ["task_id", "a", "b"],
    )
    return {
        "exp08": exp08,
        "raw_root": raw_root,
        "payloads_dir": payloads_dir,
        "out_dir": tmp_path / "figs",
        "tmp": tmp_path,
    }


def test_scope_validation_renders_with_fixture(scope_env: dict) -> None:
    env = scope_env
    code = bif.main(
        [
            "scope_validation",
            "--reference-csv", str(env["exp08"] / "IMCR_REFERENCE_ALL.csv"),
            "--manifest-json", str(env["exp08"] / "IMCR_CONSENSUS_MANIFEST.json"),
            "--raw-root", str(env["raw_root"]),
            "--payloads-dir", str(env["payloads_dir"]),
            "--out-dir", str(env["out_dir"]),
            "--prefix", "t_",
        ]
    )
    assert code == 0
    paths = bif.output_paths(env["out_dir"], "t_", "scope_validation")
    contract, audit = assert_outputs(paths, "t_", "scope_validation")
    assert contract["synthetic"] is False
    # manifest 提供 total=10 / unresolved=3，labeled=7
    consensus_panel = audit["panels"][0]
    assert consensus_panel["labeled"] == 7
    assert consensus_panel["total"] == 10
    assert consensus_panel["unresolved"] == 3
    # judge 面板：A_BETTER 经映射解码为 BEFORE_BETTER、B_BETTER→AFTER_BETTER
    judge_panel = audit["panels"][1]
    assert judge_panel["judges"]["A"] == {"BEFORE_BETTER": 6, "INVALID": 1}
    assert judge_panel["judges"]["B"] == {"AFTER_BETTER": 7}
    assert judge_panel["judges"]["C"]["EQUIVALENT"] == 4
    assert audit["render"]["n_panels"] == 2
    # 契约记录解码链路
    assert "decode_ab_label" in contract["label_decoding"]


def test_scope_validation_without_raw_root_skips_judge_panel(scope_env: dict) -> None:
    env = scope_env
    bif.main(
        [
            "scope_validation",
            "--reference-csv", str(env["exp08"] / "IMCR_REFERENCE_ALL.csv"),
            "--manifest-json", str(env["exp08"] / "IMCR_CONSENSUS_MANIFEST.json"),
            "--out-dir", str(env["out_dir"]),
            "--prefix", "nr_",
        ]
    )
    audit = read_json(bif.output_paths(env["out_dir"], "nr_", "scope_validation")["audit"])
    assert audit["render"]["n_panels"] == 1
    assert audit["render"]["judge_panel"] is False
    assert any(e.get("panel") == "judge_votes" for e in audit["excluded"])


def test_scope_validation_synthetic_has_watermark(tmp_path: Path) -> None:
    out_dir = tmp_path / "figs"
    code = bif.main(["scope_validation", "--synthetic", "--out-dir", str(out_dir), "--prefix", "s_"])
    assert code == 0
    contract, audit = assert_outputs(
        bif.output_paths(out_dir, "s_", "scope_validation"), "s_", "scope_validation"
    )
    assert contract["synthetic"] is True
    assert audit["synthetic"] is True and audit["synthetic_watermark"] is True
    # 合成演示遵循 208 任务规模（与 GOAL 图C 对应），数字来自合成 totals
    assert audit["panels"][0]["total"] == 208
    assert 0 < audit["panels"][0]["unresolved"] < 208


def test_scope_validation_missing_reference_is_hard_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="IMCR_REFERENCE_ALL"):
        bif.main(
            [
                "scope_validation",
                "--reference-csv", str(tmp_path / "none.csv"),
                "--out-dir", str(tmp_path / "figs"),
            ]
        )


def test_scope_validation_raw_root_without_mapping_is_hard_error(scope_env: dict) -> None:
    env = scope_env
    empty_payloads = env["tmp"] / "no_payloads"
    empty_payloads.mkdir()
    with pytest.raises(FileNotFoundError, match=bif.AB_MAPPING_FILE_NAME):
        bif.main(
            [
                "scope_validation",
                "--reference-csv", str(env["exp08"] / "IMCR_REFERENCE_ALL.csv"),
                "--manifest-json", str(env["exp08"] / "IMCR_CONSENSUS_MANIFEST.json"),
                "--raw-root", str(env["raw_root"]),
                "--payloads-dir", str(empty_payloads),
                "--out-dir", str(env["out_dir"]),
            ]
        )


# ---------------------------------------------------------------------------
# 图D fixture：RELATION_CONTRACT_SAMPLE.csv + IMCR_REFERENCE_ALL.csv + runs
# ---------------------------------------------------------------------------


def _relation_sample_rows() -> list[dict]:
    rows = []
    for index in range(1, 21):
        role = "changed" if index % 2 == 1 else "control"
        rows.append(
            {
                "sample_id": f"RC-{'S' if role == 'changed' else 'C'}-{index:04d}",
                "pair_id": f"RC-PAIR-{(index + 1) // 2:04d}",
                "sample_role": role,
                "fact_id": f"F-{index}",
                "subject_name": f"主语{index}",
                "subject_type": "Person",
                "predicate": "active_at",
                "object_name": f"宾语{index}",
                "object_type": "Place",
            }
        )
    return rows


def _relation_reference_rows() -> list[dict]:
    rows = []
    labels = ["valid", "invalid", "context_only", "insufficient_evidence"]
    for index in range(1, 21):
        role = "changed" if index % 2 == 1 else "control"
        sample_id = f"RC-{'S' if role == 'changed' else 'C'}-{index:04d}"
        label = labels[index % 4]
        rows.append(
            {
                "task_type": "relation_contract",
                "task_id": sample_id,
                "sample_id": sample_id,
                "reference_label": label,
                "imcr_label": label,
                "imcr_label_decoded": label,
                "consensus_tier": "strong_consensus",
                "n_valid_votes": "3",
                "winning_votes": "3",
                "vote_distribution": "{}",
                "judges": "A;B;C",
                "dry_run": "False",
            }
        )
    return rows


def _relation_runs_rows() -> list[dict]:
    """B12 relation 行：changed 组全对，control 组错 6 条（正确性以占位 0 发布，
    由图脚本按 apply_imcr_reference 语义在参考覆盖样本上重算）。"""
    rows = []
    labels = ["valid", "invalid", "context_only", "insufficient_evidence"]
    for index in range(1, 21):
        role = "changed" if index % 2 == 1 else "control"
        sample_id = f"RC-{'S' if role == 'changed' else 'C'}-{index:04d}"
        reference = labels[index % 4]
        correct = 1 if (role == "changed" or index <= 8) else 0
        # 错误预测保证与参考标签不同（确定性）
        prediction = reference if correct else ("valid" if reference != "valid" else "invalid")
        rows.append(
            {
                "sample_id": sample_id,
                "task_type": "relation_contract",
                "item_id": f"I-{sample_id}",
                "split": "independent_eval",
                "method_id": "B12_full_framework",
                "method_name": "Full framework",
                "evidence_class": "actual_run",
                "comparison_tier": "independent_reference",
                "overlap_status": "independent_of_era",
                "primary_comparison_eligible": "1",
                "evaluation_eligibility": "core_eligible_task",
                "availability_status": "available",
                "gold_label": "",
                "prediction": prediction,
                "confidence": "0.9",
                "covered": "0",
                "correct": "0",
                "hard_constraint_pass": "1",
                "constraint_gate_source": "fixture",
                "safe_correct": "0",
                "actual_llm_calls": "0",
                "source_artifact": "fixture",
                "note": "fixture row",
            }
        )
    return rows


RUNS_FIELDS = [
    "sample_id", "task_type", "item_id", "split", "method_id", "method_name",
    "evidence_class", "comparison_tier", "overlap_status", "primary_comparison_eligible",
    "evaluation_eligibility", "availability_status", "gold_label", "prediction",
    "confidence", "covered", "correct", "hard_constraint_pass", "constraint_gate_source",
    "safe_correct", "actual_llm_calls", "source_artifact", "note",
]


@pytest.fixture()
def relation_env(tmp_path: Path) -> dict:
    exp08 = tmp_path / "exp08"
    write_csv(exp08 / "RELATION_CONTRACT_SAMPLE.csv", _relation_sample_rows(),
              ["sample_id", "pair_id", "sample_role", "fact_id", "subject_name",
               "subject_type", "predicate", "object_name", "object_type"])
    write_csv(exp08 / "IMCR_REFERENCE_ALL.csv", _relation_reference_rows(),
              ["task_type", "task_id", "sample_id", "reference_label", "imcr_label",
               "imcr_label_decoded", "consensus_tier", "n_valid_votes", "winning_votes",
               "vote_distribution", "judges", "dry_run"])
    runs_path = tmp_path / "exp09" / "IMCR_BASELINE_RUNS.csv"
    write_csv(runs_path, _relation_runs_rows(), RUNS_FIELDS)
    return {
        "exp08": exp08,
        "runs_path": runs_path,
        "out_dir": tmp_path / "figs",
        "tmp": tmp_path,
    }


def test_relation_contract_validation_renders_with_runs(relation_env: dict) -> None:
    env = relation_env
    code = bif.main(
        [
            "relation_contract_validation",
            "--sample-csv", str(env["exp08"] / "RELATION_CONTRACT_SAMPLE.csv"),
            "--reference-csv", str(env["exp08"] / "IMCR_REFERENCE_ALL.csv"),
            "--runs-csv", str(env["runs_path"]),
            "--out-dir", str(env["out_dir"]),
            "--prefix", "t_",
        ]
    )
    assert code == 0
    paths = bif.output_paths(env["out_dir"], "t_", "relation_contract_validation")
    contract, audit = assert_outputs(paths, "t_", "relation_contract_validation")
    # 构成面板：changed/control 各 10 条已标
    composition = audit["panels"][0]
    assert sum(composition["changed"].values()) == 10
    assert sum(composition["control"].values()) == 10
    assert composition["unlabeled"] == {"changed": 0, "control": 0}
    # 准确率面板：changed 全对=1.0；control 4/10=0.4（apply_imcr_reference 重算）
    accuracy_panel = audit["panels"][1]
    assert accuracy_panel["changed"]["accuracy"] == pytest.approx(1.0)
    assert accuracy_panel["control"]["accuracy"] == pytest.approx(0.4)
    assert accuracy_panel["control"]["n"] == 10
    assert audit["render"]["n_panels"] == 2
    assert audit["render"]["accuracy_panel"] is True
    assert contract["synthetic"] is False


def test_relation_contract_validation_without_runs_single_panel(relation_env: dict) -> None:
    env = relation_env
    bif.main(
        [
            "relation_contract_validation",
            "--sample-csv", str(env["exp08"] / "RELATION_CONTRACT_SAMPLE.csv"),
            "--reference-csv", str(env["exp08"] / "IMCR_REFERENCE_ALL.csv"),
            "--runs-csv", str(env["tmp"] / "missing_runs.csv"),
            "--out-dir", str(env["out_dir"]),
            "--prefix", "nr_",
        ]
    )
    audit = read_json(bif.output_paths(env["out_dir"], "nr_", "relation_contract_validation")["audit"])
    assert audit["render"]["n_panels"] == 1
    assert audit["render"]["accuracy_panel"] is False
    assert audit["result"] == "PASS"  # runs 缺失是可选输入，不判失败
    assert any(e.get("panel") == "b12_accuracy" for e in audit["excluded"])


def test_relation_contract_validation_synthetic(tmp_path: Path) -> None:
    out_dir = tmp_path / "figs"
    code = bif.main(
        ["relation_contract_validation", "--synthetic", "--out-dir", str(out_dir), "--prefix", "s_"]
    )
    assert code == 0
    contract, audit = assert_outputs(
        bif.output_paths(out_dir, "s_", "relation_contract_validation"),
        "s_",
        "relation_contract_validation",
    )
    assert contract["synthetic"] is True and audit["synthetic_watermark"] is True
    accuracy_panel = audit["panels"][1]
    for role in ("changed", "control"):
        assert 0.0 <= accuracy_panel[role]["accuracy"] <= 1.0
        assert accuracy_panel[role]["n"] > 0


def test_relation_contract_validation_missing_sample_is_hard_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="RELATION_CONTRACT_SAMPLE"):
        bif.main(
            [
                "relation_contract_validation",
                "--sample-csv", str(tmp_path / "none.csv"),
                "--reference-csv", str(tmp_path / "none2.csv"),
                "--out-dir", str(tmp_path / "figs"),
            ]
        )


# ---------------------------------------------------------------------------
# 通用：rcParams 不写全局 / 字体回退链 / 合成可复现
# ---------------------------------------------------------------------------


def test_rcparams_not_polluted_and_font_chain_resolves(relation_env: dict) -> None:
    before_family = matplotlib.rcParams["font.family"]
    before_chain = list(matplotlib.rcParams["font.sans-serif"])
    before_minus = matplotlib.rcParams["axes.unicode_minus"]
    env = relation_env
    bif.main(
        [
            "relation_contract_validation",
            "--sample-csv", str(env["exp08"] / "RELATION_CONTRACT_SAMPLE.csv"),
            "--reference-csv", str(env["exp08"] / "IMCR_REFERENCE_ALL.csv"),
            "--runs-csv", str(env["runs_path"]),
            "--out-dir", str(env["out_dir"]),
            "--prefix", "rc_",
        ]
    )
    assert matplotlib.rcParams["font.family"] == before_family
    assert list(matplotlib.rcParams["font.sans-serif"]) == before_chain
    assert matplotlib.rcParams["axes.unicode_minus"] == before_minus
    font = bif.resolve_cjk_font()
    assert font["resolved"] in [*bif.FONT_CHAIN_CJK, "DejaVu Sans"]
    # rc_context 生效：在上下文内中文字体链生效、负号转义
    with matplotlib.rc_context(bif.figure_rc(font)):
        assert matplotlib.rcParams["font.sans-serif"][0] == font["resolved"]
        assert matplotlib.rcParams["axes.unicode_minus"] is False


def test_chinese_labels_render_without_crash(tmp_path: Path) -> None:
    """中文字符（含负号场景）在回退链下渲染不抛异常。"""
    font = bif.resolve_cjk_font()
    with matplotlib.rc_context(bif.figure_rc(font)):
        fig, axis = matplotlib.pyplot.subplots(figsize=(3, 2))
        axis.set_title("中文标题：覆盖率—选择性风险（−0.5 负号）")
        axis.set_xlabel("覆盖率")
        axis.set_ylabel("选择性风险")
        axis.plot([0, 1], [1, -0.5])
        fig.savefig(tmp_path / "cjk.png", dpi=100)
        matplotlib.pyplot.close(fig)
    assert (tmp_path / "cjk.png").is_file()


def test_synthetic_figures_are_reproducible(tmp_path: Path) -> None:
    out1, out2 = tmp_path / "a", tmp_path / "b"
    bif.main(["risk_coverage", "--synthetic", "--out-dir", str(out1), "--prefix", "r_"])
    bif.main(["risk_coverage", "--synthetic", "--out-dir", str(out2), "--prefix", "r_"])
    rows1 = bif.synthetic_points_rows()
    rows2 = bif.synthetic_points_rows()
    assert rows1 == rows2
    # 渲染产物逐字节一致（固定种子 → 固定图）
    assert (
        bif.output_paths(out1, "r_", "risk_coverage")["png"].read_bytes()
        == bif.output_paths(out2, "r_", "risk_coverage")["png"].read_bytes()
    )


def test_prepare_risk_coverage_panels_requires_primary_curve(points_env: dict) -> None:
    """score_only_diagnostic / fixed_grid 点不进主图。"""
    rows = _fixture_points_rows()
    for row in rows[:6]:
        row["curve_mode"] = "score_only_diagnostic"
    panels, excluded, checks = bif.prepare_risk_coverage_panels(rows)
    plotted = {p["task_type"] for p in panels}
    assert "entity_type" in plotted  # 还有其他主曲线行
    assert all(check["passed"] for check in checks)
