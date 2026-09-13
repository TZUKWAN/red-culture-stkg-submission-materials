# -*- coding: utf-8 -*-
"""build_final_tiering.py — 全库逐条 MEASURED 重分层（统计估计 → 确定计数）。

把 EVIDENCE_GATE（5,000 条分层抽样统计估计，new strict ≈ 35,226）升级为
112,158 条 strict 断言的逐条重分层 final_tier ∈ {STRICT, CONTEXTUAL, UNRESOLVED}，
按指令 §5.3 冻结 policy 应用。五个阶段（均只读既有资产 + 只新建 FINAL_TIERING_*）：

    features  确定性特征抽取（无 LLM；只读 DB 组装证据文本，算双名命中/谓词线索）
    learn     DEV 安全规则学习：5,000 条验证数据按 fixed-seed 切 3/4 学 1/4 验，
              支持率 ≥95% 且 Wilson 下界 ≥90% 的确定性特征组合才可"免 LLM 直接判定"
    policy    冻结 FINAL_TIERING_POLICY.json（predicate PARTIAL 表 + 安全规则 + §5.3 映射）
    queue     LLM 队列（prompt/证据组装/五档判定 = run_evidence_semantic_gate.py 同款，
              生产模型 = lmstudio_provider.DEFAULT_MODEL（最终口径 qwen3.5-4b，
              reasoning=off；DEV 阶段历史判定 gpt-oss-20b 已按模型过滤），
              workers≤6，checkpoint 每 500 条，断点续跑）；
              优先级：mismatch 全量 → recovery_B 全量 → recovery_A 全量 →
                      aligned 固定 seed 抽样补验 → aligned 余量 → recovery_C
    finalize  逐条落 FINAL_TIERING.csv（112,158 行）+ FINAL_TIERING_SUMMARY.json
              （MEASURED 确定计数 + 与统计估计 35,226 对照 + 三概念分离 A/B/C）
              + audit/method_final/FINAL_EVIDENCE_REPORT.md
    stats     仅打印当前队列进度（不写任何文件）

确定性快路径（无 LLM）：
    bucket=no_evidence 且 recovery_class=D → 直接 UNRESOLVED（指令 §5.3 NO_EVIDENCE 档）；
    可定位证据且命中已验证安全规则（双名命中+谓词线索等）→ STRICT（免 LLM）；
    其余全部进 LLM 队列；队列未清空的行保守持留 CONTEXTUAL（gate_method=none、
    semantic_support=NOT_EVALUATED，单独计数，绝不混入 MEASURED）。

三概念分离（指令 §6 的 A/B/C 三个数，全部实测确定数）：
    A lineage completeness        有原生溯源指针（provenance evidence_ids≥1）的占比；
    B evidence localization rate  证据文本可定位（direct 或恢复 A/B/C，非 D）的占比；
    C semantic support rate       实测语义支持（FULLY/安全规则/PARTIAL-strict-predicate）
                                  在已测可定位断言中的占比。

硬约束：数据库只读（mode=ro）；不建新库；无人工；seed 写死；checkpoint+resume；
LLM 队列真实执行；不修改任何既有文件，只新建 FINAL_TIERING_* 产物与最终报告。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

V3_1 = Path(__file__).resolve().parents[2]
V3 = V3_1.parent / "final_submission_v3"
for _p in (str(V3_1 / "code" / "independent_eval"),
           str(V3 / "code" / "independent_eval"),
           str(V3_1 / "code" / "experiment_pipelines")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _common import attach_integration, connect_final, sha256_file  # noqa: E402
import run_evidence_semantic_gate as gate  # noqa: E402  （prompt/证据组装/判定复用同款）
from lmstudio_provider import DEFAULT_BASE, DEFAULT_MODEL  # noqa: E402

OUT_DIR = V3_1 / "experiments" / "07_provenance_semantic_gate"
ALIGN_CSV = OUT_DIR / "STRICT_ALIGNMENT.csv"
RECOV_CSV = OUT_DIR / "EVIDENCE_RECOVERY.csv"
DEV_VERDICTS = OUT_DIR / "EVIDENCE_GATE_VERDICTS.jsonl"
DEV_SUMMARY = OUT_DIR / "EVIDENCE_GATE_SUMMARY.json"

OUT_FEATURES = OUT_DIR / "FINAL_TIERING_FEATURES.csv"
OUT_FEATURES_META = OUT_DIR / "FINAL_TIERING_FEATURES_META.json"
OUT_RULES = OUT_DIR / "FINAL_TIERING_RULES.json"
OUT_POLICY = OUT_DIR / "FINAL_TIERING_POLICY.json"
OUT_CKPT = OUT_DIR / "FINAL_TIERING_CHECKPOINT.jsonl"
OUT_TIERING = OUT_DIR / "FINAL_TIERING.csv"
OUT_SUMMARY = OUT_DIR / "FINAL_TIERING_SUMMARY.json"
OUT_REPORT = V3_1 / "audit" / "method_final" / "FINAL_EVIDENCE_REPORT.md"
OUT_QUEUE_LOG = OUT_DIR / "FINAL_TIERING_QUEUE_RUN.log"
OUT_QUEUE_PID = OUT_DIR / "FINAL_TIERING_QUEUE_PID.json"
OUT_QUEUE_DONE = OUT_DIR / "FINAL_TIERING_QUEUE_DONE.txt"
QUEUE_STALL_KILL_S = 3600     # checkpoint 心跳停滞超过 1h 视为挂死，看门狗重启
QUEUE_MAX_SPAWNS = 60         # 看门狗最多自动拉起次数（防崩溃风暴）
QUEUE_WORKERS_SPAWN = 4       # 看门狗拉起队列用的并发（6 并发在本机 LM Studio 上
                              # 会持续返回空 content——16:09 实测故障，4 为 DEV 验证稳定档）

METHOD_VERSION = "final-tiering-v1"
CN_TZ = timezone(timedelta(hours=8))
SEED_RULES = 20260910            # 规则学习 3/4-1/4 切分 seed（写死）
SEED_ALIGN_SAMPLE = 20260910     # aligned 抽样补验 seed（写死）
TRAIN_FRAC = 0.75

# 安全规则接受阈值（任务 §2）：经验支持率 ≥95% 且 Wilson 95% 下界 ≥90%
RULE_MIN_N_TRAIN = 30
RULE_MIN_N_TEST = 15
RULE_SUPPORT_MIN = 0.95
RULE_WILSON_LB_MIN = 0.90

# predicate PARTIAL policy 表（指令 §5.3）：FULL 占比 ≥70% 的 predicate，PARTIAL 可 strict
PRED_FULL_SHARE_MIN = 0.70
PRED_TABLE_MIN_N = 10

WORKERS = 6                      # 本地并发上限（约束 workers≤6）
CKPT_FLUSH_EVERY = 500           # checkpoint 每 500 条落盘
CHUNK = 1000                     # 队列分块组装证据（内存受控）
ALIGN_SUPPLEMENT_N = 3000        # aligned 固定 seed 抽样补验规模
REG_CACHE_MAX = 400_000          # 证据登记表缓存上限（超限清空，控内存）

LABELS = gate.LABELS
SUPPORTED = {"FULLY_SUPPORTED", "PARTIALLY_SUPPORTED"}

# 谓词 → 中文线索词（确定性特征，无外部知识；规则是否安全由 DEV 数据验证决定）
PRED_CUES: dict[str, list[str]] = {
    "participated_in": ["参加", "参与", "投身", "投入"],
    "led": ["领导", "率领", "带领", "指挥", "主持", "带队"],
    "active_at": ["活动", "工作", "任职", "任教", "开展", "驻"],
    "occurred_at": ["发生", "爆发", "打响", "战役", "战斗", "起义", "事变"],
    "organized": ["组织", "组建", "创办", "发起", "成立", "建立"],
    "member_of": ["加入", "成员", "党员", "团员", "入党", "入团"],
    "influenced": ["影响", "启发", "鼓舞", "推动"],
    "held_position_in": ["担任", "就任", "任职", "当选", "任县", "任区", "任省", "任市",
                         "任乡", "任军", "任师", "任团", "任政委", "任书记", "任司令",
                         "任部长", "任主任", "任主席", "任校长", "任委员"],
    "commanded": ["指挥", "命令", "下令", "督战"],
    "supported": ["支持", "声援", "援助", "资助", "支援"],
    "guided": ["指导", "引导", "指引", "辅导"],
    "fought_at": ["作战", "战斗", "抗击", "激战", "迎击", "交火", "参战",
                  "反扫荡", "反围剿"],
    "stationed_at": ["驻扎", "进驻", "驻防", "驻守", "移驻"],
    "has_value_facet": ["精神", "品格", "风范", "价值"],
    "carried_out": ["进行", "开展", "实施", "发动"],
    "worked_at": ["工作", "供职", "从业"],
    "mentioned_in": ["提及", "提到", "记载", "记述", "写道"],
    "contacted": ["联络", "联系", "接头", "会见"],
    "opposed": ["反对", "驳斥", "抵制", "对抗"],
    "governed": ["执政", "主政", "管辖", "治理"],
    "created": ["创建", "创办", "创立", "缔造"],
    "collaborated_with": ["合作", "共同", "并肩", "联合"],
    "traveled_to": ["抵达", "到达", "前往", "赴", "途经", "转移", "路过"],
    "dispatched": ["派遣", "抽调", "调往", "派往", "委派"],
    "captured": ["攻占", "占领", "夺取", "收复", "攻克"],
    "responsible_for": ["负责", "主管"],
    "died_at": ["牺牲", "殉难", "就义", "逝世", "去世", "遇难", "阵亡"],
    "liberated": ["解放"],
    "located_in": ["位于", "地处", "坐落在", "隶属"],
    "killed": ["击毙", "杀害", "打死", "处决"],
    "introduced": ["介绍", "引进", "传播", "宣传"],
    "imprisoned_at": ["关押", "囚禁", "入狱", "监禁", "坐牢"],
    "arrested_at": ["逮捕", "被捕", "拘捕", "被俘"],
    "recruited": ["招募", "动员", "吸收", "扩充"],
    "colleague_of": ["同事", "同僚", "共事"],
    "appointed": ["任命", "委任", "指派"],
    "reported_to": ["汇报", "请示"],
    "born_at": ["出生", "诞生"],
    "met_with": ["会见", "会面", "会晤", "相见", "接见"],
    "trained": ["训练", "培训", "操练"],
}

# 候选安全规则（按保守程度排序；首个命中的已接受规则生效）
RULE_CANDIDATES: list[dict] = [
    {"name": "R1_gap40_cue_between_len3",
     "requires": {"both_hit": True, "both_hit_close": True, "pred_cue_between": True,
                  "min_name_len_min": 3, "max_gap": 40}},
    {"name": "R2_gap80_cue_between_len3",
     "requires": {"both_hit": True, "both_hit_close": True, "pred_cue_between": True,
                  "min_name_len_min": 3, "max_gap": 80}},
    {"name": "R3_gap80_cue_any_len3",
     "requires": {"both_hit": True, "both_hit_close": True, "pred_cue": True,
                  "min_name_len_min": 3, "max_gap": 80}},
    {"name": "R4_gap80_cue_between_len2",
     "requires": {"both_hit": True, "both_hit_close": True, "pred_cue_between": True,
                  "min_name_len_min": 2, "max_gap": 80}},
    {"name": "R5_both_hit_cue_any_len3",
     "requires": {"both_hit": True, "pred_cue": True, "min_name_len_min": 3}},
    {"name": "R6_aligned_gap80_cue_between_len3",
     "requires": {"both_hit": True, "both_hit_close": True, "pred_cue_between": True,
                  "min_name_len_min": 3, "max_gap": 80,
                  "stratum_family_in": ["aligned"]}},
    {"name": "R7_recoveryB_gap80_cue_between_len3",
     "requires": {"both_hit": True, "both_hit_close": True, "pred_cue_between": True,
                  "min_name_len_min": 3, "max_gap": 80,
                  "stratum_family_in": ["recovery_B"]}},
    {"name": "R8_aligned_or_recB_gap80_cue_any_len3",
     "requires": {"both_hit": True, "both_hit_close": True, "pred_cue": True,
                  "min_name_len_min": 3, "max_gap": 80,
                  "stratum_family_in": ["aligned", "recovery_B"]}},
]

TIERING_COLUMNS = ["fact_id", "old_tier", "bucket", "recovery_class",
                   "evidence_localizable", "gate_method", "semantic_support",
                   "final_tier"]

# §5.3 冻结 policy 的 decision→tier 主干映射（PARTIAL 走 predicate 表）
TIER_OF_DECISION = {
    "FULLY_SUPPORTED": "STRICT",
    "UNSUPPORTED": "UNRESOLVED",
    "CONTRADICTED": "UNRESOLVED",
    "INSUFFICIENT": "CONTEXTUAL",
    "NO_EVIDENCE": "UNRESOLVED",
    "SAFE_RULE_FULL": "STRICT",
    "NOT_EVALUATED": "CONTEXTUAL",   # 队列未及：保守持留，不进 MEASURED
}


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def clean_text(t) -> str:
    return " ".join(str(t or "").split())


def wilson_ci(k: int, n: int, confidence: float = 0.95):
    if n <= 0:
        return (0.0, 0.0)
    z = 1.959963984540054 if confidence == 0.95 else 2.5758293035489004
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


# ---------------------------------------------------------------------------
# 输入装载（全部只读）
# ---------------------------------------------------------------------------

def load_alignment() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with open(ALIGN_CSV, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["fact_id"]] = row
    return out


def load_recovery() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with open(RECOV_CSV, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            out[row["fact_id"]] = row
    return out


def load_features() -> dict[str, dict]:
    feats: dict[str, dict] = {}
    with open(OUT_FEATURES, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            for key in ("subj_hit", "obj_hit", "both_hit", "both_hit_close",
                        "pred_cue", "pred_cue_between", "evidence_empty"):
                row[key] = row[key] == "1"
            for key in ("both_gap", "min_name_len", "n_evidence_ids", "evidence_len"):
                row[key] = int(row[key]) if row[key] != "" else -1
            feats[row["fact_id"]] = row
    return feats


def load_dev_verdicts() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not DEV_VERDICTS.exists():
        return out
    with open(DEV_VERDICTS, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("fact_id"):
                out[obj["fact_id"]] = obj
    return out


def load_queue_checkpoint() -> dict[str, dict]:
    done: dict[str, dict] = {}
    if not OUT_CKPT.exists():
        return done
    with open(OUT_CKPT, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                break  # 尾部半行（崩溃残留）——丢弃
            if obj.get("fact_id"):
                # 生产最终口径只接受当前固定模型；旧模型记录保留在原始
                # checkpoint 中用于审计，但不得阻止 qwen3.5-4b 重跑，也不得混入 finalize。
                if obj.get("model") != DEFAULT_MODEL:
                    continue
                done[obj["fact_id"]] = obj   # 后写覆盖先写（重试以最新为准）
    return done


def stratum_of(align_row: dict, recov_row: dict | None) -> str:
    b = align_row["bucket"]
    if b in ("aligned", "mismatch_with_evidence"):
        return b
    cls = (recov_row or {}).get("recovery_class", "")
    return f"recovery_{cls}" if cls else b


# ---------------------------------------------------------------------------
# 特征抽取（确定性快路径的地基，无 LLM）
# ---------------------------------------------------------------------------

def compute_row_features(align_row: dict, evidence_text: str,
                         n_evidence_ids: int) -> dict:
    subj = clean_text(align_row.get("subject_name"))
    obj = clean_text(align_row.get("object_name"))
    pred = clean_text(align_row.get("predicate"))
    text = evidence_text or ""
    p_s = text.find(subj) if subj and len(subj) >= 2 else -1
    p_o = text.find(obj) if obj and len(obj) >= 2 else -1
    subj_hit, obj_hit = p_s >= 0, p_o >= 0
    both_hit = subj_hit and obj_hit
    gap = abs(p_s - p_o) if both_hit else -1
    cues = PRED_CUES.get(pred, [])
    cue_hit = any(c in text for c in cues)
    cue_between = False
    if both_hit and cue_hit:
        lo, hi = min(p_s, p_o), max(p_s, p_o)
        for cue in cues:
            idx = text.find(cue)
            while idx >= 0:
                if lo <= idx <= hi:
                    cue_between = True
                    break
                idx = text.find(cue, idx + 1)
            if cue_between:
                break
    lens = [len(n) for n in (subj, obj) if n]
    return {
        "subj_hit": int(subj_hit), "obj_hit": int(obj_hit), "both_hit": int(both_hit),
        "both_hit_close": int(both_hit and gap <= 80),
        "both_gap": gap,
        "pred_cue": int(cue_hit), "pred_cue_between": int(cue_between),
        "min_name_len": min(lens) if lens else 0,
        "n_evidence_ids": n_evidence_ids,
        "evidence_len": len(text),
        "evidence_empty": int(not text.strip()),
    }


FEATURE_FIELDS = ["fact_id", "bucket", "recovery_class", "stratum_family", "match_mode",
                  "match_strength", "subj_hit", "obj_hit", "both_hit", "both_hit_close",
                  "both_gap", "pred_cue", "pred_cue_between", "min_name_len",
                  "n_evidence_ids", "evidence_len", "evidence_empty"]


def run_features() -> None:
    align = load_alignment()
    recov = load_recovery()
    print(f"[feat] alignment={len(align):,} rows, recovery={len(recov):,} rows")
    resolver = gate.EvidenceResolver(connect_final())
    attach_integration(resolver.con)
    rows_out: list[dict] = []
    t0 = time.time()
    for i, (fid, a) in enumerate(align.items(), 1):
        r = recov.get(fid)
        st = stratum_of(a, r)
        ev = resolver.assemble(st, fid, a, r)
        f = compute_row_features(a, ev["evidence_text"], ev["n_evidence_ids"])
        rows_out.append({
            "fact_id": fid, "bucket": a["bucket"],
            "recovery_class": (r or {}).get("recovery_class", ""),
            "stratum_family": st,
            "match_mode": (r or {}).get("match_mode", ""),
            "match_strength": (r or {}).get("match_strength", ""),
            **f,
        })
        if i % 10000 == 0:
            if len(resolver._by_eid) > REG_CACHE_MAX:
                resolver._by_eid.clear()
            print(f"[feat] {i:,}/{len(align):,} rows, {time.time()-t0:.0f}s", flush=True)
    with open(OUT_FEATURES, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FEATURE_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows_out)
    meta = {
        "method_version": METHOD_VERSION, "generated_at": now_iso(),
        "n_rows": len(rows_out),
        "inputs": {
            "strict_alignment_sha256": sha256_file(ALIGN_CSV),
            "evidence_recovery_sha256": sha256_file(RECOV_CSV),
        },
        "predicate_cues": PRED_CUES,
        "feature_defs": {
            "subj_hit/obj_hit/both_hit": "实体名（≥2 字）在组装证据文本中的子串命中",
            "both_hit_close": "双名命中且位置差 ≤80 字",
            "both_gap": "双名首现位置差（-1=未双命中）",
            "pred_cue": "谓词中文线索词出现（PRED_CUES 表，确定性）",
            "pred_cue_between": "线索词出现在双名位置之间",
            "min_name_len": "双名长度的较小值",
            "evidence_text": "与 LLM 判定完全同一组装（gate.EvidenceResolver）",
        },
    }
    OUT_FEATURES_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print(f"[feat] wrote {OUT_FEATURES.name} ({len(rows_out):,} rows) in "
          f"{(time.time()-t0)/60:.1f} min")


# ---------------------------------------------------------------------------
# 规则学习（3/4 学、1/4 验，fixed seed）
# ---------------------------------------------------------------------------

def rule_matches(feat: dict, requires: dict) -> bool:
    for key, val in requires.items():
        if key == "min_name_len_min":
            if feat.get("min_name_len", 0) < val:
                return False
        elif key == "max_gap":
            g = feat.get("both_gap", -1)
            if g < 0 or g > val:
                return False
        elif key == "stratum_family_in":
            if feat.get("stratum_family") not in val:
                return False
        elif bool(feat.get(key)) != bool(val):
            return False
    return True


def eval_rule(rows: list[dict], requires: dict) -> dict:
    hit = [r for r in rows if rule_matches(r["feat"], requires)]
    n = len(hit)
    k = sum(1 for r in hit if r["decision"] in SUPPORTED)
    kf = sum(1 for r in hit if r["decision"] == "FULLY_SUPPORTED")
    lo, hi = wilson_ci(k, n)
    return {"n": n, "n_support": k,
            "support_rate": round(k / n, 4) if n else None,
            "wilson_lb": round(lo, 4) if n else None,
            "wilson_ub": round(hi, 4) if n else None,
            "n_fully": kf, "fully_rate": round(kf / n, 4) if n else None}


def run_learn() -> None:
    feats = load_features()
    dev = load_dev_verdicts()
    joined: dict[str, dict] = {}
    for fid, v in dev.items():
        if fid not in feats or v.get("decision") not in LABELS:
            continue
        joined[fid] = {"feat": feats[fid], "decision": v["decision"],
                       "dev_stratum": v.get("stratum", ""),
                       "predicate": clean_text(v.get("predicate"))}
    ids = sorted(joined)
    rng = random.Random(SEED_RULES)
    rng.shuffle(ids)
    cut = int(len(ids) * TRAIN_FRAC)
    train = [joined[f] for f in ids[:cut]]
    test = [joined[f] for f in ids[cut:]]
    print(f"[learn] joined={len(ids)} (train={len(train)}, test={len(test)}, "
          f"seed={SEED_RULES})")

    results, accepted_rules = [], []
    for cand in RULE_CANDIDATES:
        tr = eval_rule(train, cand["requires"])
        te = eval_rule(test, cand["requires"])
        acc_train = (tr["n"] >= RULE_MIN_N_TRAIN
                     and (tr["support_rate"] or 0.0) >= RULE_SUPPORT_MIN
                     and (tr["wilson_lb"] or 0.0) >= RULE_WILSON_LB_MIN)
        acc_test = (te["n"] >= RULE_MIN_N_TEST
                    and (te["support_rate"] or 0.0) >= RULE_SUPPORT_MIN
                    and (te["wilson_lb"] or 0.0) >= RULE_WILSON_LB_MIN)
        accepted = bool(acc_train and acc_test)
        results.append({"name": cand["name"], "requires": cand["requires"],
                        "train": tr, "test": te,
                        "accepted_train": acc_train, "accepted_test": acc_test,
                        "accepted": accepted})
        if accepted:
            accepted_rules.append({"name": cand["name"], "requires": cand["requires"]})
        print(f"[learn] {cand['name']}: train n={tr['n']} supp={tr['support_rate']} "
              f"lb={tr['wilson_lb']} | test n={te['n']} supp={te['support_rate']} "
              f"lb={te['wilson_lb']} -> {'ACCEPT' if accepted else 'reject'}")

    def joint(rows_, subset):
        hit = [r for r in rows_ if any(rule_matches(r["feat"], a["requires"])
                                       for a in subset)]
        n = len(hit)
        k = sum(1 for r in hit if r["decision"] in SUPPORTED)
        lo, hi = wilson_ci(k, n)
        return {"n": n, "coverage": round(n / len(rows_), 4) if rows_ else None,
                "support_rate": round(k / n, 4) if n else None,
                "wilson_ci": [round(lo, 4), round(hi, 4)] if n else None}

    joint_train = joint(train, accepted_rules)
    joint_test = joint(test, accepted_rules)
    print(f"[learn] joint: train {joint_train} | test {joint_test}")

    payload = {
        "method_version": METHOD_VERSION, "generated_at": now_iso(),
        "seed": SEED_RULES, "train_frac": TRAIN_FRAC,
        "thresholds": {"min_n_train": RULE_MIN_N_TRAIN, "min_n_test": RULE_MIN_N_TEST,
                       "support_min": RULE_SUPPORT_MIN,
                       "wilson_lb_min": RULE_WILSON_LB_MIN},
        "n_joined": len(ids), "n_train": len(train), "n_test": len(test),
        "candidates": results,
        "accepted_rules": accepted_rules,
        "joint": {"train": joint_train, "test": joint_test},
        "inputs": {"dev_verdicts_sha256": sha256_file(DEV_VERDICTS),
                   "features_sha256": sha256_file(OUT_FEATURES)},
    }
    OUT_RULES.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(f"[learn] wrote {OUT_RULES.name}（accepted {len(accepted_rules)} rules）")


# ---------------------------------------------------------------------------
# 冻结 policy（先冻结成 JSON，再被 queue/finalize 应用）
# ---------------------------------------------------------------------------

def build_predicate_policy(dev: dict[str, dict]) -> dict[str, dict]:
    by_pred: dict[str, Counter] = defaultdict(Counter)
    for v in dev.values():
        d = v.get("decision")
        if d in ("FULLY_SUPPORTED", "PARTIALLY_SUPPORTED"):
            by_pred[clean_text(v.get("predicate")) or "(none)"][d] += 1
    table = {}
    for pred, c in sorted(by_pred.items(),
                          key=lambda kv: -(kv[1]["FULLY_SUPPORTED"] +
                                           kv[1]["PARTIALLY_SUPPORTED"])):
        nf, np_ = c["FULLY_SUPPORTED"], c["PARTIALLY_SUPPORTED"]
        n = nf + np_
        share = nf / n if n else 0.0
        strict = n >= PRED_TABLE_MIN_N and share >= PRED_FULL_SHARE_MIN
        table[pred] = {"n_full": nf, "n_partial": np_, "n_full_partial": n,
                       "full_share": round(share, 4),
                       "partial_map_to": "strict" if strict else "contextual"}
    return table


def run_policy() -> None:
    if not OUT_RULES.exists():
        raise SystemExit("[policy] 缺少 FINAL_TIERING_RULES.json，请先运行 learn")
    rules = json.loads(OUT_RULES.read_text(encoding="utf-8"))
    dev = load_dev_verdicts()
    pred_table = build_predicate_policy(dev)
    policy = {
        "method_version": METHOD_VERSION,
        "frozen_at": now_iso(),
        "note": "冻结 policy：先写盘再应用；queue/finalize 只读本文件，不现场改规则。",
        "seeds": {"rules_split": SEED_RULES, "aligned_supplement": SEED_ALIGN_SAMPLE},
        "tier_mapping_5_3": {
            "FULLY_SUPPORTED": "STRICT",
            "PARTIALLY_SUPPORTED": "predicate 表（full_share>=0.70 → STRICT，否则 CONTEXTUAL）",
            "UNSUPPORTED": "UNRESOLVED", "CONTRADICTED": "UNRESOLVED",
            "INSUFFICIENT": "CONTEXTUAL", "NO_EVIDENCE(recovery_D)": "UNRESOLVED",
            "SAFE_RULE_FULL(免LLM安全规则)": "STRICT",
            "NOT_EVALUATED(队列未及)": "CONTEXTUAL 保守持留（不计入 MEASURED）",
        },
        "predicate_policy_table": pred_table,
        "partial_strict_preds": sorted(p for p, v in pred_table.items()
                                       if v["partial_map_to"] == "strict"),
        "safe_rules": rules["accepted_rules"],
        "safe_rule_evidence": {"joint": rules["joint"],
                               "candidates": rules["candidates"],
                               "thresholds": rules["thresholds"]},
        "deterministic_fast_path": {
            "recovery_D": "直接 UNRESOLVED（无证据可定位，§5.3 NO_EVIDENCE 档）",
            "safe_rule": "免 LLM 判 SAFE_RULE_FULL→STRICT（仅当 DEV train/test 双验证通过）",
        },
        "inputs": {
            "strict_alignment_sha256": sha256_file(ALIGN_CSV),
            "evidence_recovery_sha256": sha256_file(RECOV_CSV),
            "dev_verdicts_sha256": sha256_file(DEV_VERDICTS),
            "rules_sha256": sha256_file(OUT_RULES),
        },
        "model": {"provider": "lmstudio_provider.chat_json (local LM Studio only)",
                  "model_id": DEFAULT_MODEL, "base_url": DEFAULT_BASE,
                  "temperature": 0.0, "max_tokens": 500, "workers_max": WORKERS},
    }
    OUT_POLICY.write_text(json.dumps(policy, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"[policy] froze {OUT_POLICY.name}: {len(policy['safe_rules'])} safe rules, "
          f"{len(policy['partial_strict_preds'])} partial-strict predicates")


def load_policy() -> dict:
    if not OUT_POLICY.exists():
        raise SystemExit("[tier] 缺少 FINAL_TIERING_POLICY.json，请先运行 policy")
    return json.loads(OUT_POLICY.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# LLM 队列（真实执行；优先级排序；checkpoint 每 500 条；断点续跑）
# ---------------------------------------------------------------------------

def build_queue_plan(align: dict, recov: dict, feats: dict, policy: dict,
                     dev: dict, supplement_n: int) -> tuple[list, dict]:
    """按优先级排序的 (stratum, fact_id) 队列 + 计划统计。"""
    safe_rules = policy.get("safe_rules", [])
    plan = {"rule_D": 0, "rule_safe": 0, "dev_done": 0}
    by_stratum: dict[str, list[str]] = defaultdict(list)
    for fid, a in align.items():
        st = stratum_of(a, recov.get(fid))
        if st == "recovery_D":
            plan["rule_D"] += 1
        elif any(rule_matches(feats.get(fid, {}), rr["requires"])
                 for rr in safe_rules):
            plan["rule_safe"] += 1
        elif fid in dev:
            # dev 覆盖只认有效五档判定；dev 阶段的 CALL_FAILED/UNPARSEABLE
            # 必须由生产队列重测，不得当作已测跳过（否则 finalize 只能持留）。
            if dev[fid].get("decision") in LABELS:
                plan["dev_done"] += 1
            else:
                plan["dev_redo"] = plan.get("dev_redo", 0) + 1
                by_stratum[st].append(fid)
        else:
            by_stratum[st].append(fid)
    for st in by_stratum:
        by_stratum[st].sort()

    rng = random.Random(SEED_ALIGN_SAMPLE)
    aligned_all = by_stratum.get("aligned", [])
    supp = set(rng.sample(aligned_all, min(supplement_n, len(aligned_all)))) \
        if aligned_all else set()

    todo: list[tuple[str, str]] = []
    todo += [("mismatch_with_evidence", f)
             for f in by_stratum.get("mismatch_with_evidence", [])]
    todo += [("recovery_B", f) for f in by_stratum.get("recovery_B", [])]
    todo += [("recovery_A", f) for f in by_stratum.get("recovery_A", [])]
    todo += [("aligned", f) for f in sorted(supp)]
    todo += [("aligned", f) for f in aligned_all if f not in supp]
    todo += [("recovery_C", f) for f in by_stratum.get("recovery_C", [])]
    plan["queue"] = {st: sum(1 for s, _f in todo if s == st)
                     for st in ("mismatch_with_evidence", "recovery_B", "recovery_A",
                                "aligned", "recovery_C")}
    plan["aligned_supplement_n"] = len(supp)
    plan["queue_total"] = len(todo)
    return todo, plan


def make_item(stratum: str, fid: str, align: dict, recov: dict,
              resolver) -> dict:
    a = align[fid]
    r = recov.get(fid)
    ev = resolver.assemble(stratum, fid, a, r)
    return {
        "fact_id": fid, "stratum": stratum, "bucket": a["bucket"],
        "recovery_class": (r or {}).get("recovery_class", ""),
        "match_mode": (r or {}).get("match_mode", ""),
        "predicate": clean_text(a.get("predicate")),
        "subject_name": clean_text(a.get("subject_name")),
        "subject_type": clean_text(a.get("subject_type")),
        "object_name": clean_text(a.get("object_name")),
        "object_type": clean_text(a.get("object_type")),
        "time_raw": clean_text(a.get("time_raw")),
        "place_raw": clean_text(a.get("place_raw")),
        "assertion": gate.assertion_text(a),
        **ev,
    }


def run_queue(workers: int, limit: int, only: str, supplement_n: int) -> None:
    policy = load_policy()
    align = load_alignment()
    recov = load_recovery()
    feats = load_features()
    dev = load_dev_verdicts()
    todo, plan = build_queue_plan(align, recov, feats, policy, dev, supplement_n)
    if only:
        keep = set(only.split(","))
        todo = [(s, f) for s, f in todo if s in keep]
    if limit:
        todo = todo[:limit]
    done = load_queue_checkpoint()
    retryable = {f for f, r in done.items()
                 if r.get("decision") in ("CALL_FAILED", "UNPARSEABLE")}
    pending = [(s, f) for s, f in todo if f not in done or f in retryable]
    print(f"[queue] plan={json.dumps(plan, ensure_ascii=False)}")
    print(f"[queue] todo={len(todo):,}, already_done={len(todo)-len(pending):,}, "
          f"pending={len(pending):,}, workers={workers}, ckpt_flush={CKPT_FLUSH_EVERY}")
    if not pending:
        print("[queue] nothing to do")
        if not limit and not only:
            # 只有全量跑且确实清空了队列，才允许写 DONE 标记
            OUT_QUEUE_DONE.write_text(f"all pending cleared at {now_iso()}\n",
                                      encoding="utf-8")
        return
    # 注册 pid（供 watchdog 守护）；spawns 计数继承，避免看门狗重复拉起时清零
    prev = {}
    if OUT_QUEUE_PID.exists():
        try:
            prev = json.loads(OUT_QUEUE_PID.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
    OUT_QUEUE_PID.write_text(json.dumps(
        {"pid": os.getpid(), "spawns": int(prev.get("spawns", 1)),
         "self_registered": True, "ts": now_iso()}, ensure_ascii=False),
        encoding="utf-8")

    resolver = gate.EvidenceResolver(connect_final())
    attach_integration(resolver.con)
    log = open(OUT_QUEUE_LOG, "a", encoding="utf-8")

    def logln(msg: str):
        line = f"{now_iso()} {msg}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    logln(f"queue start pending={len(pending)} workers={workers} model={DEFAULT_MODEL}")

    t0 = time.time()
    n_done = 0
    n_failed = 0
    since_flush = 0
    ckpt = open(OUT_CKPT, "a", encoding="utf-8")
    for cs in range(0, len(pending), CHUNK):
        chunk = pending[cs:cs + CHUNK]
        # 证据组装在主线程（SQLite 连接非线程安全；与 gate 同款 resolver）
        assembled = [make_item(s, f, align, recov, resolver) for s, f in chunk]
        if len(resolver._by_eid) > REG_CACHE_MAX:
            resolver._by_eid.clear()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(gate.judge_one, it) for it in assembled]
            for fut in as_completed(futs):
                out = fut.result()
                ckpt.write(json.dumps(out, ensure_ascii=False) + "\n")
                n_done += 1
                since_flush += 1
                if out.get("decision") in ("CALL_FAILED", "UNPARSEABLE"):
                    n_failed += 1
                if since_flush >= CKPT_FLUSH_EVERY:
                    ckpt.flush()
                    os.fsync(ckpt.fileno())
                    since_flush = 0
                    Path(OUT_QUEUE_LOG).parent.joinpath(
                        "FINAL_TIERING_QUEUE_HEARTBEAT.txt"
                    ).write_text(f"{now_iso()} {n_done}\n", encoding="utf-8")
                    logln(f"checkpoint {n_done}/{len(pending)} flushed "
                          f"(failed={n_failed})")
        rate = n_done / max(time.time() - t0, 1e-9)
        eta = (len(pending) - n_done) / max(rate, 1e-9) / 3600.0
        logln(f"chunk done: {n_done}/{len(pending)}, {rate:.2f} it/s, "
              f"ETA {eta:.1f} h, failed={n_failed}")
    ckpt.flush()
    os.fsync(ckpt.fileno())
    ckpt.close()
    OUT_QUEUE_PID.unlink(missing_ok=True)
    logln(f"queue loop exit: executed={n_done}, failed={n_failed}, "
          f"elapsed={(time.time()-t0)/3600:.2f} h")
    log.close()


def run_queue_guarded(workers: int, limit: int, only: str, supplement_n: int) -> None:
    """崩溃可观测包装：任何未捕获异常写入 RUN 日志（计划任务场景无 stderr 可看）。"""
    try:
        run_queue(workers, limit, only, supplement_n)
    except BaseException:
        import traceback
        try:
            with open(OUT_QUEUE_LOG, "a", encoding="utf-8") as log:
                log.write(f"{now_iso()} QUEUE CRASH:\n")
                log.write(traceback.format_exc())
                log.write("\n")
        except Exception:
            pass
        raise


def print_stats() -> None:
    if not OUT_CKPT.exists():
        print("[stats] no checkpoint yet")
        return
    done = load_queue_checkpoint()
    by_st: dict[str, Counter] = defaultdict(Counter)
    for r in done.values():
        by_st[r.get("stratum", "?")][r.get("decision", "?")] += 1
    total = sum(sum(c.values()) for c in by_st.values())
    print(f"[stats] checkpoint records={total:,}")
    for st, c in sorted(by_st.items()):
        n = sum(c.values())
        if not n:
            continue
        sup = c["FULLY_SUPPORTED"] + c["PARTIALLY_SUPPORTED"]
        print(f"  {st:24s} n={n:6,} FULLY={c['FULLY_SUPPORTED']:6,} "
              f"PARTIAL={c['PARTIALLY_SUPPORTED']:6,} UNSUP={c['UNSUPPORTED']:6,} "
              f"CONTRA={c['CONTRADICTED']:5,} INSUF={c['INSUFFICIENT']:6,} "
              f"FAILED={c['CALL_FAILED'] + c['UNPARSEABLE']:4,} "
              f"supp={sup/n:.1%}")


# ---------------------------------------------------------------------------
# finalize：逐条重分层 + 三产物
# ---------------------------------------------------------------------------

def dev_tier(decision: str, predicate: str, policy: dict) -> str:
    """§5.3 冻结映射（PARTIAL 走 predicate 表；其余走主干）。"""
    if decision == "PARTIALLY_SUPPORTED":
        cell = policy.get("predicate_policy_table", {}).get(predicate)
        if cell and cell.get("partial_map_to") == "strict":
            return "STRICT"
        return "CONTEXTUAL"
    return TIER_OF_DECISION.get(decision, "CONTEXTUAL")


def assign_all(align: dict, recov: dict, feats: dict, policy: dict,
               dev: dict, queue: dict) -> dict[str, dict]:
    safe_rules = policy.get("safe_rules", [])
    out: dict[str, dict] = {}
    for fid, a in align.items():
        r = recov.get(fid)
        st = stratum_of(a, r)
        localizable = "False" if st == "recovery_D" else "True"
        if st == "recovery_D":
            rec = {"gate_method": "rule", "semantic_support": "NO_EVIDENCE",
                   "final_tier": "UNRESOLVED", "stratum": st}
        else:
            frow = feats.get(fid, {})
            hit = next((rn for rn in safe_rules
                        if rule_matches(frow, rn["requires"])), None)
            if hit is not None:
                rec = {"gate_method": "rule", "semantic_support": "SAFE_RULE_FULL",
                       "final_tier": "STRICT", "stratum": st}
            elif fid in dev and dev[fid].get("decision") in LABELS:
                d = dev[fid]["decision"]
                rec = {"gate_method": "llm", "semantic_support": d,
                       "final_tier": dev_tier(d, clean_text(a.get("predicate")), policy),
                       "stratum": st}
            elif fid in queue and queue[fid].get("decision") in LABELS:
                d = queue[fid]["decision"]
                rec = {"gate_method": "llm", "semantic_support": d,
                       "final_tier": dev_tier(d, clean_text(a.get("predicate")), policy),
                       "stratum": st}
            else:
                rec = {"gate_method": "none", "semantic_support": "NOT_EVALUATED",
                       "final_tier": "CONTEXTUAL", "stratum": st}
        rec.update({"fact_id": fid, "old_tier": a.get("risk_tier", ""),
                    "bucket": a["bucket"],
                    "recovery_class": (r or {}).get("recovery_class", ""),
                    "evidence_localizable": localizable})
        out[fid] = rec
    return out


def build_report(S: dict, assigned: dict, policy: dict) -> str:
    tc = S["three_concepts"]
    m = S["measured"]
    ph = S["pending_hold"]
    fc = S["final_counts_full_csv"]
    cmp_ = S["comparison_with_estimate"]
    llm = S["llm"]
    n_total = S["universe"]["n_strict_assertions"]
    delta_txt = (f"{cmp_['delta']:,}" if cmp_["delta"] is not None else "n/a")
    hold_note = ("**注意：LLM 队列在报告时点未清空，下列 MEASURED 为已完成口径的确定数"
                 "（下界），持留行见 §5。**" if ph["n"] else
                 "LLM 队列已清空，MEASURED 即全库确定数。")
    lines = f"""# FINAL EVIDENCE REPORT — 全库逐条 MEASURED 重分层（三概念分离）

- 生成时间：{S['generated_at']}｜方法版本：`{S['method_version']}`（全自动、无人工、seed 写死、checkpoint 可复现）
- 模型：`{llm['model_id']}`（LM Studio 本地，temperature=0，`lmstudio_provider.chat_json`，workers≤{WORKERS}）
- 冻结 policy：`{S['policy_file']}`（先冻结成 JSON 再应用；LLM prompt/证据组装 = `run_evidence_semantic_gate.py` 同款）
- 重分层对象：{n_total:,} 条 strict 断言（STRICT_ALIGNMENT 全量，数据库只读，不建新库）
- 上游统计估计（对照基线）：分层抽样 5,000 条 → new strict ≈ **35,226** [33,744–36,708]（外推，非逐条）

## 0. 结论速览

- MEASURED（gate_method = rule / llm，逐条确定计数）：**strict {m['strict']:,} ／ contextual {m['contextual']:,} ／ unresolved {m['unresolved']:,}**
- 保守持留（LLM 队列未及，CONTEXTUAL 持留、不计入 MEASURED）：**{ph['n']:,}**
- FINAL_TIERING.csv 全表三层计数：STRICT {fc.get('STRICT', 0):,} ／ CONTEXTUAL {fc.get('CONTEXTUAL', 0):,} ／ UNRESOLVED {fc.get('UNRESOLVED', 0):,}
- 与统计估计对照（同宇宙 {cmp_['estimate_universe']:,} 条，排除 recovery_D）：估计 35,226 vs 实测 **{cmp_['measured_strict_same_universe']:,}**（差 {delta_txt}）。{hold_note}

## 1. 三概念分离（指令 §6 的 A/B/C 三个数，全部实测确定数）

| 概念 | 定义 | 分子 | 分母 | 数值 |
| --- | --- | --- | --- | --- |
| A. lineage completeness | 有原生溯源指针（provenance evidence_ids≥1，bucket ∈ aligned/mismatch_with_evidence）的 strict 断言占比 | {tc['A_lineage_completeness']['n']:,} | {n_total:,} | **{tc['A_lineage_completeness']['rate']:.2%}** |
| B. evidence localization rate | 证据文本可定位（direct 指针或恢复类 A/B/C；仅 recovery_D 不可定位）的占比 | {tc['B_evidence_localization_rate']['n']:,} | {n_total:,} | **{tc['B_evidence_localization_rate']['rate']:.2%}** |
| C. semantic support rate (measured) | 已测（rule/llm）且可定位断言中，证据在语义上支持（FULLY / 安全规则 / PARTIAL-strict-predicate）的占比 | {tc['C_semantic_support_rate_measured']['n_supported']:,} | {tc['C_semantic_support_rate_measured']['n_measured_localizable']:,} | **{tc['C_semantic_support_rate_measured']['rate']:.2%}** |

三者正交：A 说"有没有溯源链"，B 说"证据文本能否取回"，C 说"取回的证据是否真支持"。
A ≠ B：{n_total - tc['A_lineage_completeness']['n']:,} 条无原生指针，但其中
"""
    lines += f"""{tc['B_evidence_localization_rate']['n'] - tc['A_lineage_completeness']['n']:,} 条靠词法恢复（A/B/C）找回了证据文本。
B ≠ C：可定位 ≠ 支持——recovery_C 层（40,345 条）定位成功但 DEV 抽样语义支持率仅约 14.8%。

## 2. 各层重分层结果（rule/llm 已测 vs 保守持留）

| 层 | 层规模 | 已测（rule+llm） | 已测 STRICT | 已测占比 |
| --- | --- | --- | --- | --- |
"""
    for st in ("aligned", "mismatch_with_evidence", "recovery_A", "recovery_B",
               "recovery_C", "recovery_D"):
        sub = [r for r in assigned.values() if r["stratum"] == st]
        if not sub:
            continue
        n = len(sub)
        done = sum(1 for r in sub if r["gate_method"] in ("rule", "llm"))
        strict = sum(1 for r in sub
                     if r["final_tier"] == "STRICT" and r["gate_method"] != "none")
        lines += f"| {st} | {n:,} | {done:,} | {strict:,} | {done / n:.1%} |\n"
    lines += f"""
按 gate_method：rule（确定性快路径 + 安全规则）= {json.dumps(m['by_gate_method'].get('rule', {}), ensure_ascii=False)}；
llm（{DEFAULT_MODEL} 五档判定）= {json.dumps(m['by_gate_method'].get('llm', {}), ensure_ascii=False)}。

LLM 五档合并分布（DEV 5,000 + 本队列 checkpoint {llm['n_records_queue_checkpoint']:,} 条）：
{json.dumps(llm['decision_distribution'], ensure_ascii=False)}

## 3. 确定性快路径与安全规则学习（DEV 3/4 学、1/4 验）

- 快路径（无 LLM）：recovery_D → UNRESOLVED（§5.3 NO_EVIDENCE 档）；命中安全规则 → STRICT（免 LLM）。
- 安全规则接受标准：在 DEV train（3/4，seed={SEED_RULES}）上经验支持率 ≥{RULE_SUPPORT_MIN:.0%}
  且 Wilson 95% 下界 ≥{RULE_WILSON_LB_MIN:.0%}（n≥{RULE_MIN_N_TRAIN}），并必须在 DEV test（1/4）
  上同样达标（n≥{RULE_MIN_N_TEST}）——双验证通过才可免 LLM。
- 全部候选规则的 train/test 支持率、覆盖率与接受结论见 `FINAL_TIERING_RULES.json`；
  本回合应用的安全规则：
"""
    if policy.get("safe_rules"):
        lines += "\n| 规则 | 特征约束 |\n| --- | --- |\n"
        for r in policy["safe_rules"]:
            lines += (f"| `{r['name']}` | "
                      f"`{json.dumps(r['requires'], ensure_ascii=False)}` |\n")
        jt = policy.get("safe_rule_evidence", {}).get("joint", {})
        lines += (f"\n联合口径（DEV 5,000 条）：train {json.dumps(jt.get('train'), ensure_ascii=False)}"
                  f"｜test {json.dumps(jt.get('test'), ensure_ascii=False)}\n")
    else:
        lines += ("\n（本回合无规则同时通过 train/test 安全标准——没有免 LLM 的 STRICT 判定，"
                  "除 recovery_D 规约外全部走 LLM。）\n")

    lines += f"""
## 4. Predicate PARTIAL policy 表（§5.3，冻结于 policy JSON 后应用）

FULL 占比 ≥{PRED_FULL_SHARE_MIN:.0%} 的 predicate，PARTIAL 判定可入 STRICT，否则 CONTEXTUAL
（full+partial n<{PRED_TABLE_MIN_N} 默认 CONTEXTUAL）。入 STRICT 的 predicate：
**{'、'.join(policy.get('partial_strict_preds', [])) or '（无）'}**
（完整表：`FINAL_TIERING_POLICY.json.predicate_policy_table`。）

## 5. LLM 队列执行情况（如实报告）

- 优先级（错放风险高的层先跑）：mismatch 全量 → recovery_B 全量 → recovery_A 全量 →
  aligned 固定 seed 补验（n={ALIGN_SUPPLEMENT_N}，seed={SEED_ALIGN_SAMPLE}）→ aligned 余量 → recovery_C；
- checkpoint：`FINAL_TIERING_CHECKPOINT.jsonl` 每 {CKPT_FLUSH_EVERY} 条 fsync，断点续跑；
  CALL_FAILED/UNPARSEABLE 记录保留并在续跑时自动重试；
- 完成度：
"""
    for st, d in llm.get("completion_by_stratum", {}).items():
        tot = d["total"]
        lines += (f"  - {st}: {d['done']:,} / {tot:,}"
                  f"（{d['done'] / tot:.1%}）\n" if tot else
                  f"  - {st}: {d['done']:,} / 0\n")
    lines += """
## 6. 局限性

1. 单一本地判定模型（{dm}，temperature=0），PARTIAL/UNSUPPORTED 边界存在模型主观性（同上游 gate）。
2. 证据拼接 ≤800 字/3 条，超长尾部截断，可能低估 FULLY_SUPPORTED。
3. 队列未清空时，MEASURED 为已完成口径的确定数（非估计）；未测行保守持留 CONTEXTUAL，
   不外推补齐；持留清单由 `gate_method=none` 精确给定，续跑后重放 finalize 即可更新。
4. 安全规则只授予 STRICT，不授予任何负判定；UNRESOLVED 全部来自 LLM 负档或 recovery_D 规约。
5. C（semantic support rate）以已测可定位集合为分母，逐条判定随队列推进单调更全，但每一条都是实测。

## 7. 可复现性

- seed 写死：rules_split={sr}，aligned_supplement={sa}；输入 sha256 见
  `FINAL_TIERING_SUMMARY.json` 与 `FINAL_TIERING_POLICY.json`；
- 数据库只读（mode=ro），不建新库；本阶段不物化新库（下一阶段）；
- 重放路径：`features → learn → policy → queue(可断点续跑) → finalize`；
- LLM 队列判定输入/输出逐条落盘（assertion / evidence_text / decision / confidence /
  evidence_quote / explanation / latency），可第三方逐步复查。
""".format(sr=SEED_RULES, sa=SEED_ALIGN_SAMPLE, dm=DEFAULT_MODEL)
    return lines


def run_finalize() -> None:
    policy = load_policy()
    align = load_alignment()
    recov = load_recovery()
    feats = load_features()
    dev = load_dev_verdicts()
    queue = load_queue_checkpoint()
    assigned = assign_all(align, recov, feats, policy, dev, queue)

    # ---- FINAL_TIERING.csv（112,158 行，固定列序）----
    with open(OUT_TIERING, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(TIERING_COLUMNS)
        for fid in align:
            r = assigned[fid]
            w.writerow([r["fact_id"], r["old_tier"], r["bucket"], r["recovery_class"],
                        r["evidence_localizable"], r["gate_method"],
                        r["semantic_support"], r["final_tier"]])

    # ---- 统计 ----
    measured: Counter = Counter()
    measured_by_method: dict[str, Counter] = defaultdict(Counter)
    tier_all: Counter = Counter()
    pending_hold = 0
    hold_by_stratum: Counter = Counter()
    for r in assigned.values():
        tier_all[r["final_tier"]] += 1
        if r["gate_method"] in ("rule", "llm"):
            measured[r["final_tier"]] += 1
            measured_by_method[r["gate_method"]][r["final_tier"]] += 1
        else:
            pending_hold += 1
            hold_by_stratum[r["stratum"]] += 1

    llm_decisions: Counter = Counter()
    llm_by_stratum: dict[str, Counter] = defaultdict(Counter)
    for src in (dev, queue):
        for fid, v in src.items():
            if fid in assigned and v.get("decision") in LABELS:
                llm_decisions[v["decision"]] += 1
                llm_by_stratum[assigned[fid]["stratum"]][v["decision"]] += 1

    # 三概念分离（A/B/C，全库确定数）
    n_total = len(align)
    n_lineage = sum(1 for a in align.values()
                    if a["bucket"] in ("aligned", "mismatch_with_evidence"))
    n_localizable = sum(1 for r in assigned.values()
                        if r["evidence_localizable"] == "True")
    measured_localizable = sum(1 for r in assigned.values()
                               if r["evidence_localizable"] == "True"
                               and r["gate_method"] in ("rule", "llm"))
    supported_measured = measured["STRICT"]   # STRICT ⊆ 语义支持（FULLY/安全规则/PARTIAL-strict）
    support_rate = (supported_measured / measured_localizable
                    if measured_localizable else None)

    # 与统计估计对照（同宇宙 = 5 层 110,052 条，排除 recovery_D）
    dev_summary = (json.loads(DEV_SUMMARY.read_text(encoding="utf-8"))
                   if DEV_SUMMARY.exists() else {})
    est = dev_summary.get("extrapolation", {}).get("dev_layer_totals_estimate", {})
    est_strict = est.get("strict")
    universe5 = sum(1 for r in assigned.values() if r["stratum"] != "recovery_D")
    strict_universe5 = sum(1 for r in assigned.values()
                           if r["stratum"] != "recovery_D" and r["final_tier"] == "STRICT")

    strata_all = ("aligned", "mismatch_with_evidence", "recovery_A",
                  "recovery_B", "recovery_C", "recovery_D")
    completion = {}
    for st in strata_all:
        tot = sum(1 for r in assigned.values() if r["stratum"] == st)
        done = sum(1 for r in assigned.values()
                   if r["stratum"] == st and r["gate_method"] in ("rule", "llm"))
        completion[st] = {"done": done, "total": tot}

    summary = {
        "task": "全库逐条 MEASURED 重分层（统计估计 35,226 → 确定计数）",
        "method_version": METHOD_VERSION, "generated_at": now_iso(),
        "deterministic": True, "manual_review": False,
        "policy_file": OUT_POLICY.name,
        "universe": {
            "n_strict_assertions": n_total,
            "buckets": dict(Counter(a["bucket"] for a in align.values())),
            "recovery_classes": dict(Counter(
                r["recovery_class"] for r in assigned.values() if r["recovery_class"])),
        },
        "final_counts_full_csv": dict(tier_all),
        "measured": {
            "n_measured": sum(measured.values()),
            "strict": measured["STRICT"], "contextual": measured["CONTEXTUAL"],
            "unresolved": measured["UNRESOLVED"],
            "by_gate_method": {k: dict(v) for k, v in measured_by_method.items()},
            "note": "MEASURED = gate_method ∈ {rule, llm} 的确定计数；NOT_EVALUATED "
                    "保守持留 CONTEXTUAL，单列 pending_hold，不混入 MEASURED。",
        },
        "pending_hold": {"n": pending_hold, "tier": "CONTEXTUAL",
                         "by_stratum": dict(hold_by_stratum)},
        "comparison_with_estimate": {
            "estimated_strict_from_sampling": est_strict,
            "estimate_universe": universe5,
            "measured_strict_same_universe": strict_universe5,
            "delta": (strict_universe5 - est_strict
                      if est_strict is not None else None),
            "note": "统计估计=分层抽样外推（±CI）；本文件为逐条 MEASURED 确定数；"
                    "若队列未清空，measured_strict 为当前已完成口径（下界）。",
        },
        "three_concepts": {
            "A_lineage_completeness": {
                "definition": "strict 断言中有原生溯源指针（provenance evidence_ids≥1，"
                              "bucket ∈ aligned/mismatch_with_evidence）的占比",
                "n": n_lineage, "rate": round(n_lineage / n_total, 4)},
            "B_evidence_localization_rate": {
                "definition": "证据文本可定位（direct 指针或恢复类 A/B/C；仅 recovery_D "
                              "不可定位）的占比",
                "n": n_localizable, "rate": round(n_localizable / n_total, 4)},
            "C_semantic_support_rate_measured": {
                "definition": "已测（rule/llm）且可定位断言中，证据在语义上支持"
                              "（STRICT = FULLY / 安全规则 / PARTIAL-strict-predicate）的占比",
                "n_measured_localizable": measured_localizable,
                "n_supported": supported_measured,
                "rate": round(support_rate, 4) if support_rate is not None else None},
        },
        "llm": {
            "model_id": DEFAULT_MODEL, "base_url": DEFAULT_BASE,
            "decision_distribution": dict(llm_decisions),
            "by_stratum": {st: dict(c) for st, c in sorted(llm_by_stratum.items())},
            "n_records_queue_checkpoint": len(queue),
            "completion_by_stratum": completion,
        },
        "safe_rules_applied": policy.get("safe_rules", []),
        "predicate_policy_table": policy.get("predicate_policy_table", {}),
        "inputs": {
            "strict_alignment_sha256": sha256_file(ALIGN_CSV),
            "evidence_recovery_sha256": sha256_file(RECOV_CSV),
            "policy_sha256": sha256_file(OUT_POLICY),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    report = build_report(summary, assigned, policy)
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.write_text(report, encoding="utf-8")

    print(f"[tier] FINAL_TIERING.csv rows={len(assigned):,}")
    print(f"[tier] MEASURED strict={measured['STRICT']:,} "
          f"contextual={measured['CONTEXTUAL']:,} "
          f"unresolved={measured['UNRESOLVED']:,} pending_hold={pending_hold:,}")
    print(f"[tier] A={summary['three_concepts']['A_lineage_completeness']['rate']:.4f} "
          f"B={summary['three_concepts']['B_evidence_localization_rate']['rate']:.4f} "
          f"C={summary['three_concepts']['C_semantic_support_rate_measured']['rate']}")
    print(f"[tier] wrote {OUT_SUMMARY.name} and {OUT_REPORT}")


# ---------------------------------------------------------------------------
# watchdog：单发 guard（供 Windows 计划任务每 5 分钟调用）
#   - pidfile 记录队列进程 pid；pid 消失 → 重新拉起（计数上限防风暴）；
#   - pid 存活但 checkpoint 心跳停滞 >QUEUE_STALL_KILL_S → 终止并重启；
#   - 队列正常清空时写 DONE 标记，guard 不再拉起。
# ---------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            ec = ctypes.c_ulong()
            if k.GetExitCodeProcess(h, ctypes.byref(ec)):
                return ec.value == 259          # STILL_ACTIVE
            return False
        finally:
            k.CloseHandle(h)
    except Exception:
        return False


def _kill_pid(pid: int) -> None:
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x0001, False, pid)   # PROCESS_TERMINATE
        if h:
            k.TerminateProcess(h, 1)
            k.CloseHandle(h)
    except Exception:
        pass


def run_watchdog() -> int:
    if not OUT_POLICY.exists():
        print("[watchdog] no policy yet; skip")
        return 0
    if OUT_QUEUE_DONE.exists():
        print("[watchdog] queue done marker present; nothing to do")
        return 0
    state = {}
    if OUT_QUEUE_PID.exists():
        try:
            state = json.loads(OUT_QUEUE_PID.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    pid = int(state.get("pid", 0))
    spawns = int(state.get("spawns", 0))
    if pid and _pid_alive(pid):
        # 心跳检查：以 max(checkpoint mtime, 队列启动时刻) 起算——新队列在首次
        # flush（每 500 条，约 30-40 分钟）之前 ckpt mtime 陈旧是正常的，
        # 不能作为挂死依据（22:42 修 bug：此前按绝对 mtime 误杀新队列）。
        try:
            ckpt_age = time.time() - OUT_CKPT.stat().st_mtime
        except OSError:
            ckpt_age = 0.0
        try:
            started = datetime.fromisoformat(state.get("ts")).timestamp()
        except Exception:
            started = time.time() - OUT_QUEUE_PID.stat().st_mtime
        effective_stale = max(0.0, min(ckpt_age, time.time() - started))
        if effective_stale > QUEUE_STALL_KILL_S:
            print(f"[watchdog] pid={pid} stalled {effective_stale/60:.0f} min "
                  f"-> kill & respawn")
            _kill_pid(pid)
            OUT_QUEUE_PID.unlink(missing_ok=True)
            # LM Studio 长时间运行会进入半响应态（连接被接受但推理不返回，
            # 22:24 实测）：重启模型引擎清除；失败不阻塞 guard。
            try:
                lms = r"C:\Users\lauze\.lmstudio\bin\lms.exe"
                subprocess.run([lms, "unload", DEFAULT_MODEL],
                               capture_output=True, timeout=300)
                subprocess.run([lms, "load", DEFAULT_MODEL],
                               capture_output=True, timeout=600)
                print("[watchdog] lmstudio model reloaded")
            except Exception as exc:
                print(f"[watchdog] lms reload skipped: {exc}")
        else:
            print(f"[watchdog] pid={pid} alive, effective stale "
                  f"{effective_stale/60:.1f} min (ckpt age {ckpt_age/60:.1f}); ok")
            return 0
    else:
        OUT_QUEUE_PID.unlink(missing_ok=True)
    if spawns >= QUEUE_MAX_SPAWNS:
        print(f"[watchdog] spawn limit reached ({spawns}); giving up")
        return 1
    # 拉起队列：不直接 Popen（guard 的子进程会被计划任务 Job 整树回收），
    # 而是启动独立的计划任务 FinalTieringQueue（无时间上限 + IgnoreNew 防重）。
    subprocess.run(["schtasks", "/run", "/tn", "FinalTieringQueue"],
                   capture_output=True, timeout=120)
    state = {"pid": int(state.get("pid", 0)), "spawns": spawns + 1,
             "ts": now_iso(), "spawn_via": "schtasks",
             "note": "pid 由 queue 进程自注册后更新"}
    OUT_QUEUE_PID.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"[watchdog] triggered FinalTieringQueue task (spawn #{state['spawns']})")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["features", "learn", "policy", "queue",
                                      "finalize", "stats", "watchdog"])
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--limit", type=int, default=0, help="队列只取前 N 条（冒烟）")
    ap.add_argument("--only", type=str, default="", help="只跑这些 stratum（逗号分隔）")
    ap.add_argument("--align-sample", type=int, default=0,
                    help="覆盖 aligned 抽样补验规模")
    args = ap.parse_args()
    if args.workers > WORKERS:
        raise SystemExit(f"workers 硬上限 {WORKERS}")
    t0 = time.time()
    if args.phase == "features":
        run_features()
    elif args.phase == "learn":
        run_learn()
    elif args.phase == "policy":
        run_policy()
    elif args.phase == "queue":
        run_queue_guarded(args.workers, args.limit, args.only,
                          args.align_sample or ALIGN_SUPPLEMENT_N)
    elif args.phase == "finalize":
        run_finalize()
    elif args.phase == "stats":
        print_stats()
    elif args.phase == "watchdog":
        sys.exit(run_watchdog())
    print(f"[tier] phase={args.phase} done in {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
