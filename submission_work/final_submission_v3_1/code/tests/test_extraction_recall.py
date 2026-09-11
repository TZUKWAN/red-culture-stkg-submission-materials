# -*- coding: utf-8 -*-
"""test_extraction_recall.py — 候选抽取召回基准（run_extraction_recall）逻辑冒烟测试。

只测确定性规则与纯函数，不触网、不依赖 LM Studio / SQLite / 真实数据：
  归一规则 N1–N6（名称/类型/别名/年份）、共识构建、等距抽样、召回/精确计算。

运行：python test_extraction_recall.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parent / "experiment_pipelines" / "run_extraction_recall.py"

spec = importlib.util.spec_from_file_location("run_extraction_recall", TARGET)
R = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(HERE))
spec.loader.exec_module(R)

PASS = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    if not cond:
        print(f"FAIL  {name}  {detail}")
        sys.exit(1)
    PASS += 1
    print(f"ok    {name}")


# ---------------------------------------------------------------------------
# N1 名称归一
# ---------------------------------------------------------------------------
check("norm: fullwidth->half", R.normalize_name("１９４９年") == "1949年")
check("norm: whitespace removed", R.normalize_name("毛 泽 东") == "毛泽东")
check("norm: lowercase", R.normalize_name("Mao Zedong") == "maozedong")
check("norm: punct removed",
      R.normalize_name("《中国共产党》（一）") == "中国共产党一")
check("norm: middle dot", R.normalize_name("毛·泽·东") == "毛泽东")

# ---------------------------------------------------------------------------
# N2 类型归一/相容
# ---------------------------------------------------------------------------
check("type: Institution->Organization",
      R.canon_type("Institution") == "Organization")
check("type: AdministrativeRegion->Place",
      R.canon_type("AdministrativeRegion") == "Place")
check("type: CreativeWork->Document", R.canon_type("CreativeWork") == "Document")
check("type: Spirit->Concept", R.canon_type("Spirit") == "Concept")
check("type: Title->Other", R.canon_type("Title") == "Other")
check("compat: same", R.types_compatible("Person", "Person"))
check("compat: Other wildcard", R.types_compatible("Title", "Person"))
check("compat: Person!=Organization",
      not R.types_compatible("Person", "Organization"))

# ---------------------------------------------------------------------------
# N3 实体匹配
# ---------------------------------------------------------------------------
check("name: exact", R.name_match("毛泽东", "毛泽东", "Person", "Person"))
check("name: width/space", R.name_match("毛 泽 东", "毛泽东", "Person", "Person"))
check("name: containment alias",
      R.name_match("中国工农红军第四军", "红军", "Organization", "Organization"))
check("name: alias table", R.name_match("中共", "中国共产党",
                                        "Organization", "Organization"))
check("name: type blocked", not R.name_match("红军", "红军", "Person", "Organization"))
check("name: short single char no containment",
      not R.name_match("军", "中国工农红军", "Organization", "Organization"))

# ---------------------------------------------------------------------------
# N5 时间归一
# ---------------------------------------------------------------------------
check("year: western", R.year_tokens("1949年10月1日") == {1949})
check("year: cn digits", R.year_tokens("一九四九年") == {1949})
check("year: cn with circle", R.year_tokens("二〇〇八年") == {2008})
check("year: minguo", R.year_tokens("民国三十八年") == {1949})
check("year: none", R.year_tokens("解放战争初期") == set())
check("time match: intersect",
      R.time_exprs_match("1949年秋", "一九四九"))
check("time match: exact string",
      R.time_exprs_match("解放战争初期", " 解放战争初期 "))
check("time match: disjoint", not R.time_exprs_match("1935年", "1949年"))

# ---------------------------------------------------------------------------
# 共识构建（≥2 票入 consensus；并集=votes≥1）
# ---------------------------------------------------------------------------
votes = [
    {"status": "ok", "parsed": {
        "entities": [{"name": "毛泽东", "type": "Person"},
                     {"name": "毛 泽 东", "type": "Person"},
                     {"name": "井冈山", "type": "Place"}],
        "relations": [{"subject": "毛泽东", "predicate": "领导", "object": "红军"}],
        "time_expressions": ["1927年8月1日"],
        "space_expressions": ["井冈山"]}},
    {"status": "ok", "parsed": {
        "entities": [{"name": "毛泽东", "type": "Person"},
                     {"name": "朱德", "type": "Person"},
                     {"name": "井冈山", "type": "Place"}],
        "relations": [{"subject": "毛泽东", "predicate": "率领", "object": "红军"}],
        "time_expressions": ["一九二七年"],
        "space_expressions": ["井冈山"]}},
    {"status": "ok", "parsed": {
        "entities": [{"name": "毛泽东", "type": "Person"},
                     {"name": "博古", "type": "Person"}],
        "relations": [],
        "time_expressions": ["1927年"],
        "space_expressions": []}},
]
cons = R.build_consensus(votes)
ent_by_norm = {e["norm"]: e for e in cons["entities"]}
check("consensus: mao merged 3 votes",
      ent_by_norm[R.normalize_name("毛泽东")]["votes"] == 3)
check("consensus: zhude 1 vote (union only)",
      ent_by_norm[R.normalize_name("朱德")]["votes"] == 1)
check("consensus: jinggangshan 2 votes",
      ent_by_norm[R.normalize_name("井冈山")]["votes"] == 2)
check("consensus: bogu absent (failed vote? no—1 vote present)",
      ent_by_norm[R.normalize_name("博古")]["votes"] == 1)
check("consensus: consensus set (>=2) size",
      sorted(e["display"] for e in cons["entities"] if e["votes"] >= 2)
      == ["井冈山", "毛泽东"])
check("consensus: relation voted on (S,O), predicate variance tolerated",
      len(cons["relations"]) == 1
      and cons["relations"][0]["votes"] == 2)
check("consensus: time 3 votes via year-expr distinct strings",
      {t["display"] for t in cons["times"]} == {"1927年8月1日", "一九二七年",
                                                "1927年"})

# failed vote 完全排除
cons2 = R.build_consensus([votes[0], {"status": "failed", "parsed": None},
                           votes[2]])
check("consensus: failed vote excluded",
      {e["display"] for e in cons2["entities"] if e["votes"] >= 2} == {"毛泽东"})

# ---------------------------------------------------------------------------
# 等距抽样（纯函数）：确定性、数量、每书 ≤5
# ---------------------------------------------------------------------------
fake_pages = [{"path": f"D:/root/book{i:02d}/p{j:03d}.txt", "book": f"book{i:02d}",
               "filename": f"p{j:03d}.txt"}
              for i in range(30) for j in range(20)]
a = R.select_pages(fake_pages, n=40, max_per_book=5, seed=20260910)
b = R.select_pages(fake_pages, n=40, max_per_book=5, seed=20260910)
check("sample: deterministic", [p["path"] for p in a] == [p["path"] for p in b])
check("sample: count", len(a) == 40)
from collections import Counter  # noqa: E402
bc = Counter(p["book"] for p in a)
check("sample: per-book cap", max(bc.values()) <= 5)
c2 = R.select_pages(fake_pages, n=40, max_per_book=5, seed=1)
check("sample: systematic order preserved",
      [p["path"] for p in a] == sorted((p["path"] for p in a)))

# 等距性：在均匀帧上抽样索引应近似等距（步长 ≈ N/n）
paths = [{"path": f"D:/root/book/p{i:05d}.txt", "book": "book",
          "filename": f"p{i:05d}.txt"} for i in range(1000)]
uni = R.select_pages(paths, n=10, max_per_book=5, seed=20260910)
idx = [int(p["filename"][1:6]) for p in uni]
gaps = [idx[k + 1] - idx[k] for k in range(len(idx) - 1)]
check("sample: roughly equidistant", min(gaps) >= 50 and max(gaps) <= 150,
      f"idx={idx}")

# ---------------------------------------------------------------------------
# 召回/精确计算
# ---------------------------------------------------------------------------
ai_ents = [{"name": "毛泽东", "type": "Person"},
           {"name": "井冈山", "type": "Place"},
           {"name": "秋收起义", "type": "Event"}]
prod_ents = {("毛泽东", "Person"), ("井冈山革命根据地", "Place")}
m, missed = R._match_count(ai_ents, prod_ents, "entity")
check("recall: matched 2/3", m == 2 and len(missed) == 1
      and missed[0]["name"] == "秋收起义")

ai_rels = [{"subject": "毛泽东", "predicate": "领导", "object": "红军"}]
prod_rels = {("毛泽东", "led", "中国工农红军")}
m2, _ = R._match_count(ai_rels, prod_rels, "relation")
check("relation recall: S/O match ignores predicate", m2 == 1)

ai_times = [{"name": "1927年9月"}]
prod_times = {"秋收起义一九二七年"}
m3, _ = R._match_count(ai_times, prod_times, "time")
check("time recall: year token intersect", m3 == 1)

ai_sp = [{"name": "井冈山"}]
prod_sp = {"井冈山市", "江西省"}
m4, _ = R._match_count(ai_sp, prod_sp, "space")
check("space recall: containment", m4 == 1)

sup = R._supported_count(prod_ents, ai_ents, "entity")
check("precision-like: 2/2 supported", sup == 2)
sup2 = R._supported_count({("毛泽东", "Person")}, [], "entity")
check("precision-like: empty union -> 0", sup2 == 0)

# parse_vote：噪声容忍 + 类型归一
pv = R.parse_vote('前置噪声 {"entities": [{"name": "毛泽东", "type": "人物"}], '
                  '"relations": [{"subject": "毛泽东", "predicate": "成立", '
                  '"object": "苏维埃政府"}], "time_expressions": ["1931年11月"], '
                  '"space_expressions": ["瑞金"]} 后置噪声')
check("parse: entity canon type", pv["entities"][0]["type"] == "Person")
check("parse: relation kept", pv["relations"][0]["object"] == "苏维埃政府")
check("parse: times", pv["time_expressions"] == ["1931年11月"])
pv_bad = R.parse_vote("完全不是 JSON")
check("parse: bad json flagged", bool(pv_bad.get("_error")))

# ---------------------------------------------------------------------------
# 文件枚举（临时目录）
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / "书A").mkdir()
    (root / "书B").mkdir()
    (root / "书A" / "1.txt").write_text("目录", encoding="utf-8")
    (root / "书A" / "2.txt").write_text("正文", encoding="utf-8")
    (root / "书B" / "1.txt").write_text("正文B", encoding="utf-8")
    (root / "loose.txt").write_text("根目录散文件不算页", encoding="utf-8")
    pages = R.enumerate_pages(root)
    check("enumerate: only book dirs", len(pages) == 3
          and all(p["book"] in ("书A", "书B") for p in pages))
    check("enumerate: text read", R.read_page_text(pages[0]["path"]) == "目录")

    # 帧过滤：正文 ≥500 字
    (root / "书B" / "big.txt").write_text("史" * 500, encoding="utf-8")
    (root / "书B" / "small.txt").write_text("短文", encoding="utf-8")
    allp = R.enumerate_pages(root)
    kept = R.frame_filter(allp, min_chars=500)
    check("frame filter: >=500 chars only",
          [p["filename"] for p in kept] == ["big.txt"], f"{[p['filename'] for p in kept]}")
    check("frame filter: pure fn deterministic", kept == R.frame_filter(allp))

# ---------------------------------------------------------------------------
# 页键归一（evidence 路径组件 vs 采样清单 (书名, 文件名) 模糊匹配键）
# ---------------------------------------------------------------------------
check("page key: case-insensitive",
      R.norm_page_key("Book One", "P1.TXT") == R.norm_page_key("book one", "p1.txt"))
check("page key: fullwidth normalized",
      R.norm_page_key("党史（一）", "页１.txt") == R.norm_page_key("党史(一)", "页1.txt"))
check("page key: tilde normalized",
      R.norm_page_key("史料～1", "x.txt") == R.norm_page_key("史料~1", "x.txt"))

# ---------------------------------------------------------------------------
# 复数键桶 → 单数 kind 键（load_consensus ↔ compute_all 适配）
# ---------------------------------------------------------------------------
bk = R._by_kind({"entities": [{"name": "毛泽东", "type": "Person"}],
                 "spaces": ["井冈山"]})
check("by_kind: plural->singular", bk["entity"] and bk["space"] == ["井冈山"]
      and bk["relation"] == [] and bk["time"] == [])
check("by_kind: empty bucket", R._by_kind(None)["entity"] == []
      and R._by_kind({})["relation"] == [])

print(f"\nALL {PASS} CHECKS PASSED")
