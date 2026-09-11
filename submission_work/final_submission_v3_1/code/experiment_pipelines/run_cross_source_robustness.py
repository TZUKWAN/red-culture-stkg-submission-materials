# -*- coding: utf-8 -*-
"""run_cross_source_robustness.py — 指令 §18：实体语义预测的三切分跨来源稳健性。

问题：生产实体语义预测器（M3_improved_predictor.joblib 底座 = nomic-embed + LR）
在随机切分上报出的指标是否高估了跨来源（跨书/跨省）泛化？

三种切分（seed=20260910，全部确定性 SHA-256 哈希分配，无人工）：
    R1  random          实体级 80/20 随机（忽略书来源）——基线口径；
    R2  book_grouped    实体—书二部图并查集分量，同书绝不跨 train/held-out。
                        结构性事实：572 个有书实体中 569 个属同一互引分量
                        （党史人物传系列+县市级资料密集互引），分量级 80/20
                        无法常规达成，故按 data/frozen_splits 的 R1 惯例将
                        最大分量**按构造归入 train**，其余分量按哈希补足
                        train 预算至 round(0.8N)；无书实体（638 个，证据链
                        不可达、无同书约束）单列 no-book 组按哈希分配；
    R3  province_holdout 留出一个完整省份的全部实体做 held-out（选实体关联数
                        中位数的省；并列取 province_order 小者），其余训练。

训练与评价（weak-label 口径，如实声明）：
    * 语料 = stkg_v2_entity_classifier.sqlite entity_predictions 全部
      class_gate_pass=1 行（~1210）；weak 标签 = predicted_type，
      文本 = canonical_name（与生产 M3 训练语料逐行一致）；
    * 嵌入 = 生产 M3 缓存向量谱系（experiments/02.../emb_cache 原值复制种子，
      缺失文本才走 lmstudio_provider.embed 在线补嵌；2026-09-11 实测在线后端
      漂移、cosine ~0.57 且不可拟合，故以生产缓存为准），批量 + npy 缓存
      checkpoint，**三切分共用同一份缓存**；
    * 每个切分用其 train 子集重训生产同款 LR 头（C=2, class_weight=balanced,
      max_iter=5000；超参取自 M3 joblib 内 clf 的 get_params，random_state
      换为本实验 seed），held-out 上评价；
    * 指标 = accuracy / macro-F1 / balanced accuracy / coverage(conf>=0.5) /
      selective risk（coverage 内错误率）/ AURC（selective_stats.rows_to_points
      阈值扫描 + 手写梯形积分）。

口径声明：held-out 上的 weak 标签仅用于与生产训练/评价口径对齐的比较；
IMCR 独立参考（strong labels）不进入本实验的任何训练或评价调用。
三切分间比较为同口径（weak-label）相对比较，结论只用于刻画"随机切分
相对 book-grouped / province holdout 的退化梯度"，不代表对人工强标签的
绝对精度。

实体→书/省溯源链（与 build_frozen_splits.py 同连接方式，只读）：
    entity_predictions.entity_id
      → research_entity_members.source_entity_id → canonical_entity_id
      → research_assertions（成员断言 subject_id/object_id）→ fact_id
      → research_assertion_provenance.evidence_ids_json
      → up.evidence_registry.source_title（书）
    省 = 成员断言 → research_assertion_regions → research_study_regions.province_name

运行：
    python run_cross_source_robustness.py
输出 → V3_1/experiments/09_cross_source_robustness/（emb_cache/、
CROSS_SOURCE_METRICS.csv、CROSS_SOURCE_PER_CLASS_F1.csv、
CROSS_SOURCE_PREDICTIONS.csv、CROSS_SOURCE_SPLITS.json、
CROSS_SOURCE_SUMMARY.json）
"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, recall_score

V3_1 = Path(__file__).resolve().parents[2]
REPO = V3_1.parent.parent
SQLITE_PATH = REPO / "data" / "source_data" / "stkg_v2_entity_classifier.sqlite"
FINAL_DB = REPO / "data" / "release_databases" / "red_culture_stkg_final_v2.sqlite"
INTEGRATION_DB = Path("D:/REDCULTUREDATA/final_stkg_pipeline/red_culture_semantic_integration_v1.sqlite")
M3_DIR = V3_1 / "experiments" / "02_selective_semantic" / "predictor_upgrade"
M3_JOBLIB = M3_DIR / "M3_improved_predictor.joblib"
OUT_DIR = V3_1 / "experiments" / "09_cross_source_robustness"
EMB_CACHE_NPY = OUT_DIR / "emb_cache" / "EMB_CACHE.npy"
EMB_CACHE_KEYS = OUT_DIR / "emb_cache" / "EMB_CACHE.keys.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "independent_eval"))
from selective_stats import rows_to_points  # noqa: E402  修复版风险-coverage 扫描

SEED = 20260910
TRAIN_RATIO = 0.8
COVERAGE_THRESHOLD = 0.5
EMBED_BATCH = 64
EMBED_CHECKPOINT_EVERY = 256
SPLITS = ("random", "book_grouped", "province_holdout")

PROTOCOL_DECLARATION = (
    "weak-label 口径：训练与 held-out 评价标签均为生产分类器分数表 predicted_type"
    "（class_gate_pass=1），与生产 M3 训练口径逐行一致；held-out weak 标签仅用于"
    "同口径下的切分间相对比较。IMCR 独立参考（strong labels）不进入本实验的任何"
    "训练或评价调用。"
)


# ---------------------------------------------------------------------------
# 小工具：确定性哈希（与 build_frozen_splits.assign 同风格）
# ---------------------------------------------------------------------------

def rank_hash(key: str, seed: int = SEED) -> float:
    """SHA-256(seed:key) → [0,1) 确定性均匀秩（跨平台可复现，无 RNG 状态）。"""
    h = hashlib.sha256(f"{seed}:{key}".encode("utf-8")).hexdigest()
    return int(h[:16], 16) / 2**64


def aurc_trapezoid(points: list[dict[str, float]]) -> float:
    """AURC = 风险-coverage 曲线的梯形积分（rows_to_points 阈值扫描点上）。

    points 由 selective_stats.rows_to_points 生成（coverage 0→1 单调）；
    AURC = Σ (Δcoverage)·(risk_i + risk_{i+1})/2，越低越好。
    """
    area = 0.0
    for a, b in zip(points, points[1:]):
        area += (b["coverage"] - a["coverage"]) * (a["selective_risk"] + b["selective_risk"]) / 2.0
    return float(area)


# ---------------------------------------------------------------------------
# 语料与溯源链（全部只读）
# ---------------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_corpus(sqlite_path: Path = SQLITE_PATH) -> tuple[list[str], list[str], list[str], list[float], dict[str, Any]]:
    """训练语料 = entity_predictions 全部 class_gate_pass=1 行（与 M3 逐行一致）。"""
    con = sqlite3.connect(str(sqlite_path))
    try:
        rows = con.execute(
            "select entity_id, canonical_name, predicted_type, confidence "
            "from entity_predictions where class_gate_pass=1 order by entity_id"
        ).fetchall()
        total = con.execute("select count(*) from entity_predictions").fetchone()[0]
    finally:
        con.close()
    ids = [str(r[0]) for r in rows]
    texts = [str(r[1]) for r in rows]
    labels = [str(r[2]) for r in rows]
    confs = [float(r[3]) for r in rows]
    manifest = {
        "source": str(sqlite_path),
        "sha256": sha256_of(sqlite_path),
        "table": "entity_predictions",
        "filter": "class_gate_pass=1",
        "weak_label_field": "predicted_type",
        "text_field": "canonical_name",
        "n_rows_total": int(total),
        "n_corpus": len(ids),
        "n_unique_texts": len(set(texts)),
        "class_distribution": dict(sorted(Counter(labels).items())),
    }
    return ids, texts, labels, confs, manifest


def _ro(path: Path) -> str:
    return "file:" + str(path).replace("\\", "/") + "?mode=ro"


def load_group_maps(
    entity_ids: list[str],
    final_db: Path = FINAL_DB,
    integration_db: Path = INTEGRATION_DB,
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, Any]]:
    """entity_id → (书集合, 省份集合)（成员断言级溯源，与 build_frozen_splits 同链路）。

    书 = 成员断言 evidence_ids_json → up.evidence_registry.source_title（非空白）；
    省 = 成员断言 → research_assertion_regions → research_study_regions.province_name。
    """
    fin = sqlite3.connect(_ro(final_db), uri=True)
    up = sqlite3.connect(_ro(integration_db), uri=True)
    try:
        canon = dict(fin.execute("select source_entity_id, canonical_entity_id from research_entity_members"))
        efacts: dict[str, set[str]] = {}
        for sid, oid, fid in fin.execute("select subject_id, object_id, fact_id from research_assertions"):
            if fid:
                efacts.setdefault(str(sid), set()).add(str(fid))
                efacts.setdefault(str(oid), set()).add(str(fid))
        prov: dict[str, list[str]] = {}
        for fid, ej in fin.execute("select fact_id, evidence_ids_json from research_assertion_provenance"):
            try:
                prov[str(fid)] = json.loads(str(ej or "[]"))
            except json.JSONDecodeError:
                prov[str(fid)] = []
        books_by_ev = {
            str(k): str(v)
            for k, v in up.execute("select evidence_id, source_title from evidence_registry")
            if v is not None and str(v).strip()
        }
        regions = dict(fin.execute("select region_id, province_name from research_study_regions"))
        province_order = {
            str(p): int(o) for p, o in fin.execute("select province_name, province_order from research_study_regions")
        }
        fact_regions: dict[str, set[str]] = {}
        for f, rid in fin.execute("select fact_id, region_id from research_assertion_regions"):
            fact_regions.setdefault(str(f), set()).add(str(rid))

        ent_books: dict[str, set[str]] = {}
        ent_provs: dict[str, set[str]] = {}
        n_no_assert = n_assert_no_prov = 0
        for e in entity_ids:
            c = canon.get(e, e)  # 已是规范实体的兜底
            facts = efacts.get(c, set())
            evs: set[str] = set()
            for f in facts:
                evs.update(prov.get(f, []))
            bs = {books_by_ev[x] for x in evs if x in books_by_ev}
            ps = {regions[r] for f in facts for r in fact_regions.get(f, ()) if r in regions}
            ent_books[e] = bs
            ent_provs[e] = ps
            if not facts:
                n_no_assert += 1
            elif not evs:
                n_assert_no_prov += 1
    finally:
        fin.close()
        up.close()
    stats = {
        "final_db": str(final_db),
        "final_db_sha256": sha256_of(final_db),
        "integration_db": str(integration_db),
        "integration_db_sha256": sha256_of(integration_db),
        "chain": "entity_predictions.entity_id → research_entity_members.source_entity_id"
                 " → canonical_entity_id → research_assertions(成员断言) →"
                 " research_assertion_provenance.evidence_ids_json → up.evidence_registry.source_title",
        "province_chain": "成员断言 fact_id → research_assertion_regions → research_study_regions.province_name",
        "n_entities_no_member_assertion": n_no_assert,
        "n_entities_assert_but_no_evidence": n_assert_no_prov,
        "n_entities_with_book": sum(1 for e in entity_ids if ent_books[e]),
        "n_entities_no_book": sum(1 for e in entity_ids if not ent_books[e]),
        "n_distinct_books": len(set().union(*ent_books.values())) if ent_books else 0,
        "n_entities_with_province": sum(1 for e in entity_ids if ent_provs[e]),
        "province_order": dict(sorted(province_order.items(), key=lambda kv: kv[1])),
    }
    return ent_books, ent_provs, stats


# ---------------------------------------------------------------------------
# 三种切分（确定性，seed 固定）
# ---------------------------------------------------------------------------

def union_find_components(entity_ids: list[str], ent_books: dict[str, set[str]]) -> dict[str, list[str]]:
    """实体—书二部图并查集分量（有书实体经共享书并组；无书实体自成单部分量）。"""
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

    for e in entity_ids:
        find(f"e:{e}")
        for b in ent_books.get(e, ()):
            union(f"e:{e}", f"b:{b}")
    comps: dict[str, list[str]] = {}
    for e in entity_ids:
        comps.setdefault(find(f"e:{e}"), []).append(e)
    return comps


def random_split(entity_ids: list[str], seed: int = SEED, ratio: float = TRAIN_RATIO) -> dict[str, str]:
    """R1 基线口径：忽略书来源，实体按 sha256(seed:random:eid) 秩取前 80% 为 train。"""
    n_train = round(ratio * len(entity_ids))
    ordered = sorted(entity_ids, key=lambda e: (rank_hash(f"random:{e}", seed), e))
    return {e: ("train" if i < n_train else "heldout") for i, e in enumerate(ordered)}


def book_grouped_split(
    entity_ids: list[str],
    ent_books: dict[str, set[str]],
    seed: int = SEED,
    ratio: float = TRAIN_RATIO,
) -> tuple[dict[str, str], dict[str, Any]]:
    """R2 同书完整性切分（并查集分量 + 预算规则，全部确定性）。

    规则（结构适配，向 data/frozen_splits R1 惯例看齐）：
      B1 实体—书并查集分量 = 同书不可拆组；
      B2 本语料互引核心：最大分量（有书实体的 ~99%）若参与哈希落位，80/20
         要么被其独占一边、要么把 train 压到不可用；故最大分量**按构造归入
         train**（调优池），与 frozen_splits R1 "largest -> dev by construction"
         同规则；该退化在 manifest/CROSS_SOURCE_SPLITS.json 如实披露；
      B3 其余分量按 sha256(seed:bg:cid) 升序逐个放入 train，直至补足
         round(0.8N) 预算（分量原子，放不下即整体归 held-out）；
      B4 无书实体（证据链不可达，无同书约束）单列 no-book 组，键
         nobook:{eid}，与 B3 同一哈希序与预算规则参与分配。
    """
    comps = union_find_components(entity_ids, ent_books)
    comp_items = sorted(comps.items())  # 确定性
    cid_of = {
        root: hashlib.sha256("|".join(sorted(f"e:{m}" for m in members)).encode("utf-8")).hexdigest()[:16]
        for root, members in comp_items
    }
    largest_root = max(comp_items, key=lambda kv: len(kv[1]))[0]
    n_train_target = round(ratio * len(entity_ids))

    assignment: dict[str, str] = {}
    placed_train = 0
    # B2 先行：最大分量按构造整体归 train（预算优先扣减）
    for m in sorted(comps[largest_root]):
        assignment[m] = "train"
        placed_train += 1
    # B3/B4：其余分量按哈希序补足 train 预算（分量原子，放不下整体归 held-out）
    order_rest = sorted(
        ((root, members) for root, members in comp_items if root != largest_root),
        key=lambda kv: (rank_hash(f"bg:{cid_of[kv[0]]}", seed), cid_of[kv[0]]),
    )
    for root, members in order_rest:
        if placed_train + len(members) <= n_train_target:
            side = "train"
            placed_train += len(members)
        else:
            side = "heldout"
        for m in members:
            assignment[m] = side

    info = {
        "rule": "B1 实体—书并查集分量；B2 最大分量按构造归 train（互引核心 569/572，"
                "分量级 80/20 结构性不可达，与 frozen_splits R1 同惯例）；B3 其余分量"
                "按 sha256(seed:bg:cid) 序补足 train 预算；B4 无书实体单列 nobook:{eid} 组同序分配",
        "seed": seed,
        "n_components": len(comps),
        "largest_component_size": len(comps[largest_root]),
        "largest_component_pinned_to": "train",
        "n_components_booked": sum(1 for ms in comps.values() if any(ent_books[m] for m in ms)),
        "n_entities_no_book": sum(1 for e in entity_ids if not ent_books.get(e)),
        "n_train": sum(1 for v in assignment.values() if v == "train"),
        "n_heldout": sum(1 for v in assignment.values() if v == "heldout"),
    }
    return assignment, info


def province_holdout_split(
    entity_ids: list[str],
    ent_provs: dict[str, set[str]],
    province_order: dict[str, int],
) -> tuple[dict[str, str], dict[str, Any]]:
    """R3 省份留出：held-out = 关联到所选省的全部实体（含跨省实体，保证省份完整）。

    选省规则：按实体关联数（任一成员断言落在该省即计入）取**中位数**的省；
    并列（本语料 51=湖北=江苏）取 province_order 小者；无省实体全部留在 train。
    """
    counts: dict[str, int] = {p: 0 for p in province_order}
    for e in entity_ids:
        for p in ent_provs.get(e, ()):
            counts[p] = counts.get(p, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (kv[1], province_order.get(kv[0], 10**9)))
    values = [c for _, c in ordered]
    median_count = values[len(values) // 2]  # 上中位（奇数个省即精确中位数，且必为实际值）
    candidates = [p for p in province_order if counts.get(p) == median_count]
    chosen = min(candidates, key=lambda p: province_order.get(p, 10**9))
    assignment = {
        e: ("heldout" if chosen in ent_provs.get(e, ()) else "train")
        for e in entity_ids
    }
    info = {
        "rule": "held-out = 关联该省的全部实体（跨省实体整体归 held-out 以保证省份完整）；"
                "选省 = 实体关联数中位数（并列取 province_order 小者）；无省实体留 train",
        "chosen_province": chosen,
        "chosen_province_order": province_order.get(chosen),
        "province_entity_counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "median_count": median_count,
        "tie_with": sorted(p for p, c in counts.items() if c == median_count and p != chosen),
        "n_train": sum(1 for v in assignment.values() if v == "train"),
        "n_heldout": sum(1 for v in assignment.values() if v == "heldout"),
    }
    return assignment, info


# ---------------------------------------------------------------------------
# 嵌入（三切分共用同一缓存）与生产同款 LR 头
# ---------------------------------------------------------------------------

def embed_all(
    texts: list[str],
    npy_path: Path = EMB_CACHE_NPY,
    keys_path: Path = EMB_CACHE_KEYS,
) -> tuple[np.ndarray, dict[str, Any]]:
    """三切分共用的嵌入缓存（生产向量谱系 + 断点续跑 checkpoint）。

    谱系规则（重要，2026-09-11 实测）：当前 LM Studio 在线重嵌入与生产 M3 缓存
    向量的同名文本 cosine 仅 ~0.57（后端漂移），且漂移向量上 LR 连训练集都拟合
    不动（train acc ~7%）。为忠实复用"生产底座"的特征空间，本实验缓存优先从
    生产 M3 缓存（experiments/02_selective_semantic/predictor_upgrade/emb_cache，
    只读）原值复制种子，仅对生产缓存缺失的文本走在线嵌入并显式记录混合计数。
    三个切分共享同一份缓存文件，切分间严格可比。
    """
    from run_predictor_upgrade import embed_cached  # 复用已验证的缓存/checkpoint 实现

    meta_path = npy_path.with_name("EMB_CACHE.meta.json")
    lineage_ok = False
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            lineage_ok = meta.get("lineage") == "production_m3_cache"
        except json.JSONDecodeError:
            lineage_ok = False
    seed_stats: dict[str, Any] = {
        "lineage": None,
        "seeded_from_production": 0,
        "m3_cache_sha256": None,
    }
    if not lineage_ok:
        m3_npy = M3_DIR / "emb_cache" / "EMB_CACHE.npy"
        m3_keys = M3_DIR / "emb_cache" / "EMB_CACHE.keys.json"
        if m3_npy.exists() and m3_keys.exists():
            vecs = np.load(m3_npy)
            m3_key_list = json.loads(m3_keys.read_text(encoding="utf-8"))
            m3_idx = {k: i for i, k in enumerate(m3_key_list)}
            seed_keys = [t for t in dict.fromkeys(texts) if t in m3_idx]
            if seed_keys:
                npy_path.parent.mkdir(parents=True, exist_ok=True)
                np.save(npy_path, np.stack([vecs[m3_idx[t]] for t in seed_keys]).astype(np.float32))
                keys_path.write_text(json.dumps(seed_keys, ensure_ascii=False), encoding="utf-8")
                seed_stats = {
                    "lineage": "production_m3_cache",
                    "seeded_from_production": len(seed_keys),
                    "m3_cache_sha256": sha256_of(m3_npy),
                }
                print(f"[cross_source] emb cache seeded from production M3 cache: {len(seed_keys)} vectors")
    meta_path.write_text(
        json.dumps({"lineage": "production_m3_cache", "seed": SEED}, ensure_ascii=False), encoding="utf-8"
    )

    mat, stats = embed_cached(
        texts, npy_path, keys_path,
        batch_size=EMBED_BATCH, checkpoint_every=EMBED_CHECKPOINT_EVERY,
    )
    # 混合谱系守卫：种子之后仍需在线补嵌的文本数（应 = 0；>0 意味着缓存混入漂移后端向量）
    seed_stats["n_live_embedded_after_seed"] = stats["n_new_embedded"]
    stats = {**stats, **seed_stats}
    return mat, stats


def build_production_head_params(joblib_path: Path = M3_JOBLIB) -> tuple[dict[str, Any], dict[str, Any]]:
    """加载生产 M3 工件（底座可加载性验证 + 复用其 LR 头超参）。"""
    model = joblib.load(joblib_path)
    params = dict(model.clf.get_params())
    meta_path = joblib_path.with_name(joblib_path.stem + ".metadata.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    head_params = dict(params)
    head_params["random_state"] = SEED  # 唯一偏离：random_state 换为本实验 seed（lbfgs 本身确定性）
    return head_params, {
        "joblib": str(joblib_path),
        "sha256": sha256_of(joblib_path),
        "route": meta.get("route"),
        "artifact_class": type(model).__name__,
        "classes": list(model.classes),
        "n_train_production": meta.get("n_train"),
        "clf_params_reused": head_params,
        "deviation": "random_state=20260910（本实验 seed）；其余超参逐项取自生产 clf.get_params()",
        "loadable": True,
    }


# ---------------------------------------------------------------------------
# 训练 + held-out 评价（accuracy / macro-F1 / balanced acc / coverage /
# selective risk / AURC / 逐类 F1 / 跨切分泄漏诊断）
# ---------------------------------------------------------------------------

def run_split_experiment(
    name: str,
    assignment: dict[str, str],
    emb: np.ndarray,
    labels: list[str],
    texts: list[str],
    ids: list[str],
    ent_books: dict[str, set[str]],
    head_params: dict[str, Any],
) -> dict[str, Any]:
    train_idx = np.array([i for i, e in enumerate(ids) if assignment[e] == "train"], dtype=int)
    held_idx = np.array([i for i, e in enumerate(ids) if assignment[e] == "heldout"], dtype=int)
    Xtr, ytr = emb[train_idx], [labels[i] for i in train_idx]
    Xte = emb[held_idx]
    yte = [labels[i] for i in held_idx]

    t0 = time.perf_counter()
    clf = LogisticRegression(**head_params).fit(Xtr, ytr)
    fit_s = time.perf_counter() - t0
    proba = clf.predict_proba(Xte)
    pred_idx = proba.argmax(axis=1)
    ypred = [clf.classes_[int(i)] for i in pred_idx]
    conf = proba.max(axis=1)
    correct = np.array([float(p == t) for p, t in zip(ypred, yte)], dtype=float)

    label_space = sorted(set(yte) | set(ypred))
    acc = float(np.mean(correct))
    macro_f1 = float(f1_score(yte, ypred, labels=label_space, average="macro", zero_division=0))
    bal_acc = float(recall_score(yte, ypred, labels=label_space, average="macro", zero_division=0))
    covered = conf >= COVERAGE_THRESHOLD
    coverage = float(covered.mean()) if len(conf) else 0.0
    selective_risk = float(1.0 - correct[covered].mean()) if covered.any() else None
    rows = [
        {
            "sample_id": ids[i],
            "accepted": 1,
            "correct": int(correct[k]),
            "score": float(conf[k]),
        }
        for k, i in enumerate(held_idx)
    ]
    points = rows_to_points(rows)
    aurc = aurc_trapezoid(points)
    per_class_f1 = {
        c: float(f1_score(yte, ypred, labels=[c], average="macro", zero_division=0))
        for c in label_space
    }
    per_class_support = {c: int(sum(1 for t in yte if t == c)) for c in label_space}

    # 泄漏诊断：held-out 与 train 的同名实体（完全同名字符串）与同书实体
    train_names = {texts[i] for i in train_idx}
    train_books: set[str] = set()
    for i in train_idx:
        train_books |= ent_books.get(ids[i], set())
    n_dup_name = int(sum(1 for k, i in enumerate(held_idx) if texts[i] in train_names))
    n_shared_book = int(sum(1 for i in held_idx if ent_books.get(ids[i], set()) & train_books))
    n_heldout_booked = int(sum(1 for i in held_idx if ent_books.get(ids[i], set())))

    return {
        "split": name,
        "n_train": int(len(train_idx)),
        "n_heldout": int(len(held_idx)),
        "fit_seconds": round(fit_s, 2),
        "accuracy": round(acc, 4),
        "macro_f1": round(macro_f1, 4),
        "balanced_accuracy": round(bal_acc, 4),
        "coverage": round(coverage, 4),
        "selective_risk": None if selective_risk is None else round(selective_risk, 4),
        "aurc_trapezoid": round(aurc, 4),
        "n_covered": int(covered.sum()),
        "per_class_f1": {c: round(v, 4) for c, v in sorted(per_class_f1.items())},
        "per_class_support": dict(sorted(per_class_support.items())),
        "leakage_diagnostic": {
            "heldout_dup_name_in_train": n_dup_name,
            "heldout_share_book_with_train": n_shared_book,
            "heldout_booked": n_heldout_booked,
        },
        "_raw": {
            "held_idx": held_idx.tolist(),
            "ypred": ypred,
            "conf": [round(float(c), 6) for c in conf],
            "correct": [int(c) for c in correct],
            "covered": [bool(b) for b in covered],
        },
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "emb_cache").mkdir(parents=True, exist_ok=True)
    t_all = time.perf_counter()

    # ---- 语料（weak labels）----
    ids, texts, labels, _confs, corpus_manifest = load_corpus()
    print(f"[cross_source] corpus rows (gate_pass=1): {len(ids)}; unique names={corpus_manifest['n_unique_texts']}")
    print(f"[cross_source] class distribution: {corpus_manifest['class_distribution']}")

    # ---- 溯源链：书 / 省 ----
    ent_books, ent_provs, provenance_stats = load_group_maps(ids)
    print(
        f"[cross_source] books: with_book={provenance_stats['n_entities_with_book']} "
        f"no_book={provenance_stats['n_entities_no_book']} distinct_books={provenance_stats['n_distinct_books']}"
    )

    # ---- 生产底座加载校验 + LR 头超参复用 ----
    head_params, m3_manifest = build_production_head_params()
    assert m3_manifest["classes"] == sorted(set(labels)), "M3 类空间与语料 weak 标签空间不一致"
    assert m3_manifest["n_train_production"] == len(ids)
    print(f"[cross_source] production base loaded: route={m3_manifest['route']}, classes={len(m3_manifest['classes'])}")

    # ---- 嵌入（一次缓存，三切分共用）----
    emb, emb_stats = embed_all(texts)
    print(
        f"[cross_source] embeddings: unique={emb_stats['n_unique']} new={emb_stats['n_new_embedded']} "
        f"dim={emb_stats['dim']} secs={emb_stats['seconds']}"
    )

    # ---- 三切分 ----
    assign_random = random_split(ids)
    assign_book, book_info = book_grouped_split(ids, ent_books)
    assign_prov, prov_info = province_holdout_split(ids, ent_provs, provenance_stats["province_order"])
    n_rand_tr = sum(1 for v in assign_random.values() if v == "train")
    print(
        f"[cross_source] splits: random {n_rand_tr}/{len(ids) - n_rand_tr} | "
        f"book {book_info['n_train']}/{book_info['n_heldout']} (largest comp {book_info['largest_component_size']} pinned to train) | "
        f"province {prov_info['chosen_province']} {prov_info['n_train']}/{prov_info['n_heldout']}"
    )

    results: dict[str, dict[str, Any]] = {}
    for name, assignment in (
        ("random", assign_random),
        ("book_grouped", assign_book),
        ("province_holdout", assign_prov),
    ):
        results[name] = run_split_experiment(name, assignment, emb, labels, texts, ids, ent_books, head_params)
        r = results[name]
        print(
            f"[cross_source] {name:<16} acc={r['accuracy']:.3f} mF1={r['macro_f1']:.3f} "
            f"bal={r['balanced_accuracy']:.3f} cov={r['coverage']:.3f} sRisk={r['selective_risk']} AURC={r['aurc_trapezoid']:.3f}"
        )

    # ---- 退化梯度与逐类 shift ----
    f1 = {s: results[s]["macro_f1"] for s in SPLITS}
    degradation = {
        "macro_f1": {s: f1[s] for s in SPLITS},
        "delta_book_minus_random": round(f1["book_grouped"] - f1["random"], 4),
        "delta_province_minus_random": round(f1["province_holdout"] - f1["random"], 4),
        "delta_province_minus_book": round(f1["province_holdout"] - f1["book_grouped"], 4),
        "random_overestimates": bool(
            f1["book_grouped"] < f1["random"] or f1["province_holdout"] < f1["random"]
        ),
        "note": "退化梯度 = random → book_grouped → province_holdout 的 macro-F1 下降；"
                "负值越大（绝对值）说明随机切分相对该口径高估越多",
    }
    all_classes = sorted(
        {c for s in SPLITS for c in results[s]["per_class_f1"]}
    )
    class_rows = []
    for c in all_classes:
        f1s = {s: results[s]["per_class_f1"].get(c) for s in SPLITS}
        sup = {s: results[s]["per_class_support"].get(c, 0) for s in SPLITS}
        class_rows.append({
            "class": c,
            "support_random": sup["random"],
            "support_book_grouped": sup["book_grouped"],
            "support_province_holdout": sup["province_holdout"],
            "f1_random": f1s["random"],
            "f1_book_grouped": f1s["book_grouped"],
            "f1_province_holdout": f1s["province_holdout"],
            "delta_book_minus_random": None if f1s["random"] is None or f1s["book_grouped"] is None
            else round(f1s["book_grouped"] - f1s["random"], 4),
            "delta_province_minus_random": None if f1s["random"] is None or f1s["province_holdout"] is None
            else round(f1s["province_holdout"] - f1s["random"], 4),
        })
    droppers = sorted(
        (r for r in class_rows if r["delta_province_minus_random"] is not None),
        key=lambda r: (r["delta_province_minus_random"], -(r["f1_random"] or 0.0)),
    )
    top3_drop = [
        {
            "rank": i + 1,
            "class": r["class"],
            "f1_random": r["f1_random"],
            "f1_book_grouped": r["f1_book_grouped"],
            "f1_province_holdout": r["f1_province_holdout"],
            "delta_province_minus_random": r["delta_province_minus_random"],
            "delta_book_minus_random": r["delta_book_minus_random"],
        }
        for i, r in enumerate(droppers[:3])
    ]

    # ---- 落盘 ----
    splits_payload = {
        "seed": SEED,
        "train_ratio": TRAIN_RATIO,
        "rules": {
            "random": "实体按 sha256(seed:random:eid) 升序取前 round(0.8N) 为 train（忽略书来源，基线口径）",
            "book_grouped": book_info["rule"],
            "province_holdout": prov_info["rule"],
        },
        "book_grouped_info": book_info,
        "province_holdout_info": prov_info,
        "assignment": {
            "random": assign_random,
            "book_grouped": assign_book,
            "province_holdout": assign_prov,
        },
    }
    (OUT_DIR / "CROSS_SOURCE_SPLITS.json").write_text(
        json.dumps(splits_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    metric_rows = []
    for s in SPLITS:
        r = results[s]
        for k in ("n_train", "n_heldout", "accuracy", "macro_f1", "balanced_accuracy",
                  "coverage", "n_covered", "selective_risk", "aurc_trapezoid", "fit_seconds"):
            metric_rows.append([s, k, r[k]])
        for k, v in r["leakage_diagnostic"].items():
            metric_rows.append([s, f"diag_{k}", v])
    with open(OUT_DIR / "CROSS_SOURCE_METRICS.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["split", "metric", "value"])
        w.writerows(metric_rows)

    with open(OUT_DIR / "CROSS_SOURCE_PER_CLASS_F1.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(class_rows[0].keys()))
        w.writeheader()
        w.writerows(class_rows)

    with open(OUT_DIR / "CROSS_SOURCE_PREDICTIONS.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["split", "entity_id", "canonical_name", "weak_label", "prediction",
                    "confidence", "covered(conf>=0.5)", "correct"])
        for s in SPLITS:
            raw = results[s]["_raw"]
            for k, i in enumerate(raw["held_idx"]):
                w.writerow([s, ids[i], texts[i], labels[i], raw["ypred"][k],
                            raw["conf"][k], int(raw["covered"][k]), raw["correct"][k]])

    timings = {"total_s": round(time.perf_counter() - t_all, 2)}
    summary = {
        "pipeline": "run_cross_source_robustness.py (指令 §18 三切分跨来源稳健性)",
        "seed": SEED,
        "protocol": PROTOCOL_DECLARATION,
        "imcr_reference_used": False,
        "versions": {
            "python": platform.python_version(),
            "sklearn": sklearn.__version__,
            "numpy": np.__version__,
        },
        "corpus_manifest": corpus_manifest,
        "provenance_stats": provenance_stats,
        "production_base": m3_manifest,
        "embed_stats": emb_stats,
        "split_info": {"book_grouped": book_info, "province_holdout": prov_info},
        "metrics": {s: {k: v for k, v in results[s].items() if k != "_raw"} for s in SPLITS},
        "degradation": degradation,
        "top3_class_drop": top3_drop,
        "timings": timings,
    }
    (OUT_DIR / "CROSS_SOURCE_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---- 控制台对比表 ----
    print("\n[cross_source] 三切分 held-out 指标（weak-label 口径，IMCR 不参与）")
    hdr = f"{'split':<18}{'n_ho':>6}{'acc':>7}{'mF1':>7}{'bal':>7}{'cov':>7}{'sRisk':>7}{'AURC':>7}"
    print(hdr)
    for s in SPLITS:
        r = results[s]
        print(
            f"{s:<18}{r['n_heldout']:>6}{r['accuracy']:>7.3f}{r['macro_f1']:>7.3f}"
            f"{r['balanced_accuracy']:>7.3f}{r['coverage']:>7.3f}{r['selective_risk']:>7.3f}{r['aurc_trapezoid']:>7.3f}"
        )
    print(f"[cross_source] degradation: {json.dumps(degradation, ensure_ascii=False)}")
    print(f"[cross_source] top3 class drop: {json.dumps(top3_drop, ensure_ascii=False)}")
    print(f"[cross_source] outputs -> {OUT_DIR} ({timings['total_s']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
