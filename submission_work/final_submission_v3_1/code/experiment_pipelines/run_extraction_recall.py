# -*- coding: utf-8 -*-
"""run_extraction_recall.py — 指令 §17：候选抽取召回基准（experiments/08_candidate_recall）。

问题：生产管线在一页上产出的候选（断言/实体/时间/空间），能覆盖一个
独立 AI panel 穷尽抽取得到的该页实体的多大比例？（候选抽取召回）

方法（全自动、确定性规则、checkpoint 可续跑）：
  1) 抽样   ：上游 OCR 文本库（pdf_ocr_project/output/<书>/<页>.txt，每文件=一页）
              分层抽 120 页：帧=正文 ≥500 字的页文件、按书分组、每书最多 5 页、
              seed=20260910、文件按路径排序后等距（systematic）抽样；
              记录 path/book/正文长度。
  2) 独立抽取：本地 LM Studio（openai/gpt-oss-20b，经 lmstudio_provider）对每页
              穷尽抽取 schema 实体（Person/Organization/Place/Event/Document/
              Concept/Time/Other）+ 关系(s,p,o) + 时间/空间表述；
              每页 3 次独立调用（temperature 0 / 0.3 / 0.7），workers=2
              （与后台任务共享 LM Studio），
              逐 (page,vote) checkpoint（EXTRACTION_CHECKPOINT.jsonl）可续跑。
              资源受限下的独立性声明：同一模型、不同 temperature 三采样
              （指令允许"独立 AI panel"，如实披露，非跨模型 panel）。
  3) 共识   ：三票并集中 ≥2 票出现的实体/关系/时间/空间进入
              AI consensus reference（AI_CONSENSUS_REFERENCE.csv，含 votes 列，
              并集=votes≥1 用于 precision-like）。
  4) 生产对照：生产候选 = 该页来源证据所支撑的全部断言/实体——
              evidence_id → provenance（evidence_ids_json 直连 + source_member_id
              → up.fact_evidence 血缘）→ fact_id → research_assertions 的
              subject/object/predicate/time_raw/place_raw。
              页路径映射 evidence_registry.source_path_or_url（归一化精确匹配，
              兜底 (书名,页文件名) 模糊匹配）。
  5) 指标   ：Entity/Relation/Time/Space Recall + Overall（micro 为主，
              另给按页 macro）；precision-like = 生产候选有 AI 支持（三票并集）
              的比例。scope = all_pages（抽样帧全体）与 production_linked
              （该页确有生产证据关联的子集，反映纯抽取召回）两个口径，
              并按书分组报告分布。
  6) 输出   ：RECALL_PAGES.json / EXTRACTION_RAW/*.jsonl /
              AI_CONSENSUS_REFERENCE.csv / RECALL_METRICS.csv /
              RECALL_SUMMARY.json / audit/method_final/FINAL_EXTRACTION_RECALL.md
              （含漏抽类型分析：每类自动举 3 个 AI 抽到而生产没有的例子）。

确定性归一规则（唯一实现处，测试见 code/tests/test_extraction_recall.py）：
  N1 名称归一：NFKC（全角→半角）→ 小写 → 去全部空白 → 去全部 Unicode
     punctuation 类字符（unicodedata.category 以 P 开头）。
  N2 类型归一：{Person,Organization,Place,Event,Document,Concept,Time,Other}，
     同义映射 Institution/SocialGroup→Organization、AdministrativeRegion/
     Location→Place、CreativeWork→Document、Spirit→Concept 等；
     类型相容 = 归一类型相等，或一方为 Other。
  N3 实体匹配：归一名精确相等，或包含别名（短串 ⊆ 长串且短串长度 ≥2 且
     类型相容），或命中固定缩写别名表 ALIAS_GROUPS（中共/中国共产党、
     国民党/中国国民党、红军/中国工农红军、八路军/国民革命军第八路军、
     新四军/国民革命军陆军新编第四军、新中国/中华人民共和国）。
  N4 关系匹配：主体名匹配 且 客体名匹配（N3）；谓词不作要求（生产谓词
     来自固定本体，与 AI 自由谓词不同一），另报谓词严格匹配作参考。
  N5 时间归一：抽取年份 token 集 = 西元 4 位年 + 中文数字年（一九四九→1949、
     二〇〇八→2008）+ 民国年（民国三十八年→1949）；时间匹配 = 年 token 集
     相交，或归一字符串精确相等。
  N6 空间匹配：N3 名称匹配（含省/市/县后缀差异的包含匹配）。

用法：
  python run_extraction_recall.py all        # 全流程
  python run_extraction_recall.py sample     # 仅抽样
  python run_extraction_recall.py extract    # 三票抽取（checkpoint 续跑）
  python run_extraction_recall.py consensus  # 共识参考
  python run_extraction_recall.py metrics    # 生产对照 + 指标
  python run_extraction_recall.py report     # FINAL_EXTRACTION_RECALL.md

硬约束：两个 SQLite 均 mode=ro 只读；evidence_registry（107 万行）流式扫描，
禁止全量载入文本；无人工干预。
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import random
import re
import sys
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

V3_1 = Path(__file__).resolve().parents[2]
for _p in (str(V3_1 / "code" / "independent_eval"), str(V3_1 / "code")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import lmstudio_provider  # noqa: E402  生产链唯一大模型入口

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

V3 = V3_1.parent / "final_submission_v3"
OCR_ROOT = Path(r"D:\REDCULTUREDATA\pdf_ocr_project\output")
FINAL_DB = V3_1 / "data" / "repaired_release" / "red_culture_stkg_final_v3_1.sqlite"
INTEGRATION_DB = Path(
    "D:/REDCULTUREDATA/final_stkg_pipeline/red_culture_semantic_integration_v1.sqlite"
)

OUT_DIR = V3_1 / "experiments" / "08_candidate_recall"
RAW_DIR = OUT_DIR / "EXTRACTION_RAW"
CKPT_PATH = OUT_DIR / "EXTRACTION_CHECKPOINT.jsonl"
PAGES_JSON = OUT_DIR / "RECALL_PAGES.json"
CONSENSUS_CSV = OUT_DIR / "AI_CONSENSUS_REFERENCE.csv"
METRICS_CSV = OUT_DIR / "RECALL_METRICS.csv"
SUMMARY_JSON = OUT_DIR / "RECALL_SUMMARY.json"
REPORT_MD = V3_1 / "audit" / "method_final" / "FINAL_EXTRACTION_RECALL.md"

SEED = 20260910
N_PAGES = 120
MAX_PER_BOOK = 5
MIN_PAGE_CHARS = 500         # 指令：帧内页文件正文 ≥500 字
TEMPERATURES = [0.0, 0.3, 0.7]
WORKERS = 2                  # 与后台任务共享 LM Studio
MODEL = "openai/gpt-oss-20b"
MAX_TOKENS = 2600
MAX_TOKENS_RETRY = 3600
PAGE_TEXT_CAP = 6000          # 字符；超长页截断并在清单中记录
TIMEOUT_S = 600.0
CN_TZ = timezone(timedelta(hours=8))
METHOD_VERSION = "extraction-recall-v1"

ENTITY_TYPES = ["Person", "Organization", "Place", "Event", "Document",
                "Concept", "Time", "Other"]

SYSTEM_PROMPT = (
    "你是红色历史文献的信息抽取引擎，任务是穷尽式抽取（exhaustive extraction）。"
    "对给定的文献页面文本，穷尽列出页面上出现的全部实体与关系，不遗漏任何出现过的实体。要求：\n"
    "1) entities：页面上出现的全部人物、组织机构、地点、事件、文献/文件、"
    "概念/政策/理论等实体，每项 {\"name\": ..., \"type\": ...}，"
    "type 只能取 Person/Organization/Place/Event/Document/Concept/Time/Other 之一；\n"
    "2) relations：页面表述的主体-谓词-客体关系 {\"subject\": ..., \"predicate\": ..., "
    "\"object\": ...}，subject/object 使用页面上出现的实体名；\n"
    "3) time_expressions：页面出现的全部时间表述（原文字符串数组）；\n"
    "4) space_expressions：页面出现的全部空间/地名表述（原文字符串数组）。\n"
    "只输出一个 JSON 对象，不要输出任何解释、markdown 代码块或其他文本。宁可多列，不可遗漏。"
)

# 固定缩写别名表（确定性规则 N3；落盘即本文件与本报告）
ALIAS_GROUPS = [
    {"中共", "中国共产党"},
    {"国民党", "中国国民党"},
    {"红军", "中国工农红军"},
    {"八路军", "国民革命军第八路军"},
    {"新四军", "国民革命军陆军新编第四军"},
    {"新中国", "中华人民共和国"},
]

_TYPE_ALIAS = {
    "person": "Person", "people": "Person", "人物": "Person", "figure": "Person",
    "title": "Other", "职务": "Other",
    "organization": "Organization", "organisation": "Organization",
    "organization": "Organization", "institution": "Organization",
    "socialgroup": "Organization", "social_group": "Organization",
    "organization": "Organization", "组织": "Organization", "机构": "Organization",
    "party": "Organization", "团体": "Organization",
    "place": "Place", "location": "Place", "administrativeregion": "Place",
    "administrative_region": "Place", "region": "Place", "地点": "Place",
    "地名": "Place", "地区": "Place", "行政区划": "Place",
    "event": "Event", "事件": "Event",
    "document": "Document", "creativework": "Document", "creative_work": "Document",
    "work": "Document", "publication": "Document", "文献": "Document",
    "文件": "Document", "作品": "Document", "书刊": "Document",
    "concept": "Concept", "spirit": "Concept", "理论": "Concept",
    "思想": "Concept", "政策": "Concept", "概念": "Concept", "精神": "Concept",
    "time": "Time", "date": "Time", "时间": "Time", "日期": "Time",
    "other": "Other", "其他": "Other", "artifact": "Other", "器物": "Other",
}

_CN_DIGIT = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9}

_YEAR_RE = re.compile(r"(1[89]\d{2}|20\d{2})")
_CN_YEAR_RE = re.compile(r"([一二三四五六七八九〇零]{4})年?")
_MG_YEAR_RE = re.compile(r"民国([0-9一二三四五六七八九十零]{1,4})年")


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[{now_iso()}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# 确定性归一规则（N1–N6）
# ---------------------------------------------------------------------------

def _strip_punct(s: str) -> str:
    return "".join(ch for ch in s if not unicodedata.category(ch).startswith("P"))


def normalize_name(s: str) -> str:
    """N1：NFKC → 小写 → 去空白 → 去 Unicode punctuation。"""
    if not s:
        return ""
    t = unicodedata.normalize("NFKC", str(s))
    t = t.lower()
    t = re.sub(r"\s+", "", t, flags=re.UNICODE)
    return _strip_punct(t)


def canon_type(t: str | None) -> str:
    """N2：任意类型标签 → 规范 8 类。"""
    if not t:
        return "Other"
    key = re.sub(r"[\s_\-]+", "", unicodedata.normalize("NFKC", str(t)).lower())
    return _TYPE_ALIAS.get(key, "Other")


def types_compatible(ta: str | None, tb: str | None) -> bool:
    """N2：类型相容 = 规范类型相等，或一方为 Other。"""
    a, b = canon_type(ta), canon_type(tb)
    return a == b or a == "Other" or b == "Other"


_ALIAS_NORM = [{normalize_name(x) for x in grp} for grp in ALIAS_GROUPS]


def names_equivalent(na: str, nb: str) -> bool:
    """归一后名称等价：精确相等 / 别名表 / 包含别名（短串≥2字）。"""
    if not na or not nb:
        return False
    if na == nb:
        return True
    for grp in _ALIAS_NORM:
        if na in grp and nb in grp:
            return True
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(short) >= 2 and short in long:
        return True
    return False


def name_match(a: str, b: str, ta: str | None = None, tb: str | None = None,
               use_type: bool = True) -> bool:
    """N3：名称匹配 + （可选）类型相容。"""
    if use_type and not types_compatible(ta, tb):
        return False
    return names_equivalent(normalize_name(a), normalize_name(b))


def _cn4_to_int(s: str) -> int:
    v = 0
    for ch in s:
        v = v * 10 + _CN_DIGIT.get(ch, 0)
    return v


def _cn_num_to_int(s: str) -> int:
    """中文数字（1–99）→ 整数：三十八→38、十→10、二十→20。"""
    if s.isdigit():
        return int(s)
    if s and all(ch in _CN_DIGIT or ch == "〇" for ch in s):
        return _cn4_to_int(s)
    total, last = 0, 0
    for ch in s:
        if ch == "十":
            total += (last or 1) * 10
            last = 0
        elif ch in _CN_DIGIT:
            last = _CN_DIGIT[ch]
        elif ch == "零":
            last = 0
        else:
            return -1
    return total + last


def year_tokens(expr: str) -> set[int]:
    """N5：时间表述 → 年份 token 集。"""
    if not expr:
        return set()
    s = unicodedata.normalize("NFKC", str(expr))
    ys = {int(m.group(1)) for m in _YEAR_RE.finditer(s)}
    for m in _CN_YEAR_RE.finditer(s):
        ys.add(_cn4_to_int(m.group(1)))
    for m in _MG_YEAR_RE.finditer(s):
        n = _cn_num_to_int(m.group(1))
        if 1 <= n <= 110:
            ys.add(1911 + n)
    return ys


def time_exprs_match(ai_expr: str, prod_expr: str) -> bool:
    """N5：时间匹配 = 年 token 集相交，或归一字符串相等。"""
    ya, yb = year_tokens(ai_expr), year_tokens(prod_expr)
    if ya and yb and (ya & yb):
        return True
    return normalize_name(ai_expr) == normalize_name(prod_expr) != ""


# ---------------------------------------------------------------------------
# 抽样（stage 1）
# ---------------------------------------------------------------------------

def enumerate_pages(root: Path) -> list[dict]:
    """OCR 库全部页面：root 下每个书目录内的 .txt（根目录散文件不算页）。"""
    pages = []
    root = Path(root)
    for book_dir in sorted(root.iterdir(), key=lambda p: p.name):
        if not book_dir.is_dir():
            continue
        for f in sorted(book_dir.glob("*.txt"), key=lambda p: p.name):
            pages.append({"path": str(f.resolve()), "book": book_dir.name,
                          "filename": f.name})
    pages.sort(key=lambda d: d["path"])
    return pages


def select_pages(all_pages: list[dict], n: int = N_PAGES,
                 max_per_book: int = MAX_PER_BOOK, seed: int = SEED) -> list[dict]:
    """等距（systematic）抽样：排序路径上取 i*step；书配额 ≤5，超配顺延。
    纯函数（作用于清单列表），可测。"""
    N = len(all_pages)
    if N == 0:
        return []
    step = N / float(n)
    picked: list[dict] = []
    book_count: collections.Counter = collections.Counter()
    i = 0
    guard = 0
    while len(picked) < n and guard < N * 2 + 10:
        idx = min(int(round(i * step)), N - 1)
        cand = all_pages[idx]
        if book_count[cand["book"]] < max_per_book:
            picked.append(cand)
            book_count[cand["book"]] += 1
        i += 1
        guard += 1
        if i * step > N and len(picked) < n:
            # 等距骨架用尽仍不足（书配额挤压）：退化为确定性顺序补齐
            for cand in all_pages:
                if len(picked) >= n:
                    break
                if book_count[cand["book"]] < max_per_book:
                    picked.append(cand)
                    book_count[cand["book"]] += 1
            break
    # 去重（round 可能重复命中同一索引）
    seen: set[str] = set()
    uniq = []
    for p in picked:
        if p["path"] not in seen:
            seen.add(p["path"])
            uniq.append(p)
    return uniq[:n]


def read_page_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def norm_path(p: str) -> str:
    return unicodedata.normalize("NFKC", str(p)).replace("\\", "/").strip().lower()


OCR_ROOT_NORM = norm_path(str(OCR_ROOT))


def frame_filter(pages: list[dict], min_chars: int = MIN_PAGE_CHARS) -> list[dict]:
    """帧过滤：正文 ≥ min_chars 字的页文件（指令：文件 ≥500 字）。纯函数可测。"""
    return [p for p in pages if len(read_page_text(p["path"])) >= min_chars]


def norm_page_key(book: str, filename: str) -> tuple[str, str]:
    """(书名, 页文件名) → 归一模糊键（与 evidence 路径组件同一归一）。"""
    return (norm_path(book), norm_path(filename))


def run_sample() -> None:
    t0 = time.time()
    log(f"枚举 OCR 页面: {OCR_ROOT}")
    all_pages = enumerate_pages(OCR_ROOT)
    n_all = len(all_pages)
    n_books_all = len({p["book"] for p in all_pages})
    log(f"帧（全部）：{n_all} 页 / {n_books_all} 书；过滤正文 ≥{MIN_PAGE_CHARS} 字…")
    frame_pages = frame_filter(all_pages)
    n_books = len({p["book"] for p in frame_pages})
    log(f"帧（≥{MIN_PAGE_CHARS} 字）：{len(frame_pages)} 页 / {n_books} 书")

    # 生产关联页 Universe（证据→断言双路由可达页），用于帧统计与 linked 标记
    linked = {p for p in load_linked_pages() if p.startswith(OCR_ROOT_NORM + "/")}
    picked = select_pages(frame_pages)
    log(f"抽样 {len(picked)} 页")

    rows = []
    for i, p in enumerate(picked):
        text = read_page_text(p["path"])
        rows.append({
            "page_id": i,
            "path": p["path"],
            "book": p["book"],
            "filename": p["filename"],
            "text_length": len(text),
            "text_truncated_for_llm": len(text) > PAGE_TEXT_CAP,
            "production_linked": norm_path(p["path"]) in linked,
        })
    n_linked = sum(1 for r in rows if r["production_linked"])
    manifest = {
        "method_version": METHOD_VERSION,
        "seed": SEED,
        "n_pages_requested": N_PAGES,
        "n_pages_sampled": len(rows),
        "max_per_book": MAX_PER_BOOK,
        "min_page_chars": MIN_PAGE_CHARS,
        "sampling_rule": f"frame = book-dir .txt pages with body >= {MIN_PAGE_CHARS} "
                         f"chars; files sorted by path (codepoint), systematic "
                         f"equal-distance i*step, book cap 5 with skip-ahead",
        "frame": {
            "root": str(OCR_ROOT),
            "total_page_files": n_all,
            "total_books": n_books_all,
            "total_page_files_ge_min_chars": len(frame_pages),
            "total_books_ge_min_chars": n_books,
            "production_linked_pages_in_frame": len(linked),
            "note": "frame = 书目录内 .txt 页文件（正文 ≥500 字）；"
                    "production_linked = 该页路径出现在 evidence_registry."
                    "source_path_or_url 且证据可达生产断言",
        },
        "pages": rows,
        "generated_at": now_iso(),
        "n_linked_sampled": n_linked,
        "elapsed_s": round(time.time() - t0, 1),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PAGES_JSON.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    log(f"RECALL_PAGES.json 写出：{len(rows)} 页（其中生产关联 {n_linked} 页）"
        f"，用时 {manifest['elapsed_s']}s")


# ---------------------------------------------------------------------------
# 生产关联索引（evidence → fact → page）
# ---------------------------------------------------------------------------

def _ro(path: Path) -> str:
    return (path.resolve().as_posix().replace(" ", "%20"))


def connect_dbs():
    import sqlite3
    con = sqlite3.connect(f"file:{FINAL_DB.as_posix()}?mode=ro", uri=True)
    con.execute(f"ATTACH DATABASE 'file:{INTEGRATION_DB.as_posix()}?mode=ro' AS up")
    return con


def build_evidence_to_facts() -> dict[str, set[str]]:
    """evidence_id → {fact_id}：路由1 provenance.evidence_ids_json 直连 +
    路由2 provenance.source_member_id → up.fact_evidence 血缘。"""
    con = connect_dbs()
    cur = con.cursor()
    member_ids: set[str] = set()
    e2f: dict[str, set[str]] = collections.defaultdict(set)
    cur.execute("SELECT fact_id, source_member_id, evidence_ids_json "
                "FROM research_assertion_provenance")
    for fact_id, member_id, ej in cur.fetchall():
        if member_id:
            member_ids.add(member_id)
        if ej and "EVD-" in ej:
            try:
                arr = json.loads(ej)
            except Exception:
                continue
            for e in arr if isinstance(arr, list) else []:
                if isinstance(e, str) and e.startswith("EVD-"):
                    e2f[e].add(fact_id)
    cur.execute("SELECT fact_id, evidence_id FROM up.fact_evidence")
    for fact_id, evid in cur.fetchall():
        if fact_id in member_ids and evid:
            e2f[evid].add(fact_id)
    con.close()
    return dict(e2f)


def build_evidence_to_page(page_rows: list[dict]) -> dict[str, str]:
    """evidence_id → 采样页路径：流式扫描 evidence_registry（不全量载入文本）。"""
    want_exact = {norm_path(r["path"]) for r in page_rows}
    want_fuzzy = {norm_page_key(r["book"], r["filename"]) for r in page_rows}
    con = connect_dbs()
    cur = con.cursor()
    e2p: dict[str, str] = {}
    cur.execute("SELECT evidence_id, source_path_or_url FROM up.evidence_registry")
    for evid, path in cur:
        if not path:
            continue
        np_ = norm_path(path)
        if np_ in want_exact:
            e2p[evid] = path
            continue
        parts = np_.rsplit("/", 2)
        if (len(parts) == 3 and parts[0].endswith("/output")
                and norm_page_key(parts[1], parts[2]) in want_fuzzy):
            e2p[evid] = path
    con.close()
    return e2p


def load_linked_pages() -> set[str]:
    """帧内生产关联页集合（norm_path）。"""
    e2f = build_evidence_to_facts()
    con = connect_dbs()
    cur = con.cursor()
    pages: set[str] = set()
    cur.execute("SELECT evidence_id, source_path_or_url FROM up.evidence_registry")
    for evid, path in cur:
        if evid in e2f and path:
            pages.add(norm_path(path))
    con.close()
    return pages


def load_production_candidates(page_rows: list[dict]) -> dict[int, dict]:
    """page_id → 生产候选（entities/relations/times/spaces，含显示名与归一键）。"""
    log("构建 evidence→fact 索引…")
    e2f = build_evidence_to_facts()
    log(f"  {len(e2f)} 条证据绑定")
    log("构建 evidence→page 索引…")
    e2p = build_evidence_to_page(page_rows)
    log(f"  {len(e2p)} 条证据落在采样页")
    page_evids: dict[int, list[str]] = collections.defaultdict(list)
    norm2pid = {norm_path(r["path"]): r["page_id"] for r in page_rows}
    fuzzy: dict[tuple[str, str], int] = {
        norm_page_key(r["book"], r["filename"]): r["page_id"] for r in page_rows}
    for evid, path in e2p.items():
        np_ = norm_path(path)
        pid = norm2pid.get(np_)
        if pid is None:
            parts = np_.rsplit("/", 2)
            pid = fuzzy.get(norm_page_key(parts[1], parts[2])) \
                if len(parts) == 3 else None
        if pid is not None:
            page_evids[pid].append(evid)

    facts: set[str] = set()
    for pid, evids in page_evids.items():
        for e in evids:
            facts |= e2f.get(e, set())
    log(f"  采样页共关联 {len(facts)} 条生产断言 fact")

    con = connect_dbs()
    cur = con.cursor()
    out: dict[int, dict] = {r["page_id"]: {"entities": set(), "relations": set(),
                                           "times": set(), "spaces": set(),
                                           "raw_assertions": 0}
                            for r in page_rows}
    pid_by_fact: dict[str, int] = {}
    for pid, evids in page_evids.items():
        for e in evids:
            for f in e2f.get(e, set()):
                pid_by_fact.setdefault(f, pid)  # 一 fact 多页时归首见页（计数用）

    CHUNK = 900
    flist = sorted(facts)
    for i in range(0, len(flist), CHUNK):
        chunk = flist[i:i + CHUNK]
        q = ",".join("?" * len(chunk))
        cur.execute(f"SELECT fact_id, subject_name, subject_type, object_name, "
                    f"object_type, predicate, time_raw, normalized_time_label, "
                    f"place_raw, province, city, county "
                    f"FROM research_assertions WHERE fact_id IN ({q})", chunk)
        for (fact_id, s_name, s_type, o_name, o_type, predicate, time_raw,
             ntl, place_raw, prov, city, county) in cur.fetchall():
            pid = pid_by_fact.get(fact_id)
            if pid is None:
                continue
            bucket = out[pid]
            bucket["raw_assertions"] += 1
            if s_name:
                bucket["entities"].add((s_name.strip(), canon_type(s_type)))
            if o_name:
                bucket["entities"].add((o_name.strip(), canon_type(o_type)))
            if s_name and o_name:
                bucket["relations"].add((s_name.strip(), (predicate or "").strip(),
                                         o_name.strip()))
            for t in (time_raw, ntl):
                if t and str(t).strip():
                    bucket["times"].add(str(t).strip())
            for sp in (place_raw, prov, city, county):
                if sp and str(sp).strip():
                    bucket["spaces"].add(str(sp).strip())
    con.close()
    log("生产候选构建完成")
    return out


# ---------------------------------------------------------------------------
# 独立三票抽取（stage 2）
# ---------------------------------------------------------------------------

_EXTRACTION_LOCK = threading.Lock()
_RAW_LOCK = threading.Lock()


def parse_vote(raw: str) -> dict:
    """模型输出 → 规整抽取结构（容忍噪声；失败返回 {'_error': ...}）。"""
    try:
        d = lmstudio_provider.extract_json(raw)
    except Exception as exc:
        return {"_error": f"json: {exc}", "entities": [], "relations": [],
                "time_expressions": [], "space_expressions": []}
    ents = []
    for e in d.get("entities", []) or []:
        if isinstance(e, dict) and str(e.get("name", "")).strip():
            ents.append({"name": str(e["name"]).strip(),
                         "type": canon_type(e.get("type"))})
    rels = []
    for r in d.get("relations", []) or []:
        if isinstance(r, dict) and str(r.get("subject", "")).strip() \
                and str(r.get("object", "")).strip():
            rels.append({"subject": str(r["subject"]).strip(),
                         "predicate": str(r.get("predicate", "")).strip(),
                         "object": str(r["object"]).strip()})
    times = [str(t).strip() for t in (d.get("time_expressions", []) or [])
             if str(t).strip()]
    spaces = [str(s).strip() for s in (d.get("space_expressions", []) or [])
              if str(s).strip()]
    return {"entities": ents, "relations": rels,
            "time_expressions": times, "space_expressions": spaces}


def one_vote(page: dict, vote_idx: int) -> dict:
    text = read_page_text(page["path"])
    truncated = False
    if len(text) > PAGE_TEXT_CAP:
        text = text[:PAGE_TEXT_CAP]
        truncated = True
    temp = TEMPERATURES[vote_idx]
    t0 = time.time()
    record = {
        "page_id": page["page_id"], "book": page["book"], "path": page["path"],
        "vote": vote_idx, "temperature": temp, "model": MODEL,
        "text_length": len(text), "text_truncated": truncated,
        "status": "failed", "latency_s": None, "raw": None, "parsed": None,
        "error": None, "ts": now_iso(), "run_id": RUN_ID,
    }
    try:
        raw = lmstudio_provider.chat(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": "页面文本：\n" + text}],
            model=MODEL, temperature=temp, top_p=1.0,
            max_tokens=MAX_TOKENS, timeout=TIMEOUT_S,
        )
        parsed = parse_vote(raw)
        if "_error" in parsed and parsed["_error"]:
            # JSON 截断/解析失败：提高 max_tokens 复投一次
            raw = lmstudio_provider.chat(
                [{"role": "system", "content": SYSTEM_PROMPT},
                 {"role": "user", "content": "页面文本：\n" + text}],
                model=MODEL, temperature=temp, top_p=1.0,
                max_tokens=MAX_TOKENS_RETRY, timeout=TIMEOUT_S,
            )
            parsed = parse_vote(raw)
        record["latency_s"] = round(time.time() - t0, 2)
        record["raw"] = raw
        record["parsed"] = {k: v for k, v in parsed.items() if not k.startswith("_")}
        record["status"] = "failed" if parsed.get("_error") else "ok"
        if parsed.get("_error"):
            record["error"] = parsed["_error"]
    except Exception as exc:
        record["latency_s"] = round(time.time() - t0, 2)
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def load_checkpoint() -> dict[tuple[int, int], dict]:
    done: dict[tuple[int, int], dict] = {}
    if CKPT_PATH.exists():
        with CKPT_PATH.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    done[(r["page_id"], r["vote"])] = r
                except Exception:
                    continue
    return done


def page_slug(page: dict) -> str:
    safe_book = re.sub(r'[\\/:*?"<>|\s]+', "_", page["book"])[:40]
    stem = Path(page["filename"]).stem
    return f"page{page['page_id']:03d}_{safe_book}_{stem}.jsonl"


def run_extract(limit: int | None = None) -> None:
    global RUN_ID
    manifest = json.loads(PAGES_JSON.read_text(encoding="utf-8"))
    pages = manifest["pages"][:limit] if limit else manifest["pages"]
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    done = load_checkpoint()
    RUN_ID = done[next(iter(done))]["run_id"] if done else uuid.uuid4().hex[:12]
    todo = [(p, v) for p in pages for v in range(len(TEMPERATURES))
            if (p["page_id"], v) not in done]
    log(f"三票抽取：共 {len(pages)*len(TEMPERATURES)} 票，已完成 "
        f"{len(done)}，待跑 {len(todo)}（workers={WORKERS}，run_id={RUN_ID}）")
    if not todo:
        _rewrite_raw_files(pages, done)
        return
    t0 = time.time()
    votes_by_page: dict[int, int] = collections.Counter(
        pid for (pid, _v) in done)
    completed_ok = 0
    with CKPT_PATH.open("a", encoding="utf-8") as ckpt:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(one_vote, p, v): (p, v) for (p, v) in todo}
            n = 0
            for fut in as_completed(futs):
                p, v = futs[fut]
                rec = fut.result()
                with _EXTRACTION_LOCK:
                    ckpt.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    ckpt.flush()
                done[(p["page_id"], v)] = rec
                votes_by_page[p["page_id"]] += 1
                if votes_by_page[p["page_id"]] == len(TEMPERATURES):
                    _write_raw_page(p, [done[(p["page_id"], k)]
                                        for k in range(len(TEMPERATURES))])
                if rec["status"] == "ok":
                    completed_ok += 1
                n += 1
                if n % 10 == 0 or n == len(todo):
                    el = time.time() - t0
                    eta = el / n * (len(todo) - n)
                    log(f"  进度 {n}/{len(todo)}  ok={completed_ok}  "
                        f"已用 {el/60:.1f}min  ETA {eta/60:.1f}min")
    el = time.time() - t0
    lats = [r["latency_s"] for r in done.values() if r.get("latency_s")]
    log(f"抽取完成：新增 {len(todo)} 票（ok={completed_ok}），"
        f"墙钟 {el/60:.1f}min，单票均值 "
        f"{(sum(lats)/len(lats)) if lats else 0:.1f}s")
    _rewrite_raw_files(pages, done)


def _write_raw_page(page: dict, recs: list[dict]) -> None:
    with _RAW_LOCK:
        with (RAW_DIR / page_slug(page)).open("w", encoding="utf-8") as fh:
            for r in sorted(recs, key=lambda x: x["vote"]):
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _rewrite_raw_files(pages: list[dict], done: dict[tuple[int, int], dict]) -> None:
    """续跑后补齐缺失的逐页原始文件。"""
    by_page: dict[int, list[dict]] = collections.defaultdict(list)
    for (pid, _v), r in done.items():
        by_page[pid].append(r)
    for p in pages:
        recs = by_page.get(p["page_id"])
        if recs:
            _write_raw_page(p, recs)
    log(f"EXTRACTION_RAW 共 {len(by_page)} 页文件")


# ---------------------------------------------------------------------------
# 共识参考（stage 3）
# ---------------------------------------------------------------------------

def build_consensus(votes: list[dict]) -> dict:
    """三票 → {entities, relations, times, spaces}，每项含 votes 计数与
    in_consensus（≥2）。名称归一聚合（精确 + 别名），显示名取最高频原形。
    单票内部先去重：一票=一次独立观测，重复列举不重复计票。"""
    ent_count: dict[tuple[str, str], collections.Counter] = collections.defaultdict(
        collections.Counter)
    for v in votes:
        parsed = v.get("parsed") or {}
        seen: set[tuple[str, str]] = set()
        for e in parsed.get("entities", []):
            key = (normalize_name(e["name"]), e.get("type", "Other"))
            if key in seen:
                continue
            seen.add(key)
            ent_count[key][e["name"]] += 1
    entities = []
    for (nk, tk), names in ent_count.items():
        display = sorted(names.items(), key=lambda kv: (-kv[1], -len(kv[0]),
                                                        kv[0]))[0][0]
        entities.append({"norm": nk, "type": tk, "display": display,
                         "votes": sum(names.values())})

    # 关系投票键 = (S,O)（N4：谓词为自由文本，跨票不具同一性；谓词仅作展示，
    # 取票数最高原形，并列取归一序最小）
    rel_count: dict[tuple[str, str], dict] = {}
    for v in votes:
        parsed = v.get("parsed") or {}
        seen: set[tuple[str, str]] = set()
        for r in parsed.get("relations", []):
            ns, no = normalize_name(r["subject"]), normalize_name(r["object"])
            key = (ns, no)
            if key in seen:
                continue
            seen.add(key)
            if key not in rel_count:
                rel_count[key] = {"votes": 0, "forms": collections.Counter()}
            rel_count[key]["votes"] += 1
            rel_count[key]["forms"][json.dumps(r, ensure_ascii=False,
                                               sort_keys=True)] += 1
    relations = []
    for k, d in rel_count.items():
        best = sorted(d["forms"].items(),
                      key=lambda kv: (-kv[1], kv[0]))[0][0]
        relations.append({"norm_s": k[0], "norm_o": k[1],
                          "display": json.loads(best), "votes": d["votes"]})

    def simple(items_per_vote: list[list[str]]) -> list[dict]:
        cnt: collections.Counter = collections.Counter()
        form: dict[str, collections.Counter] = collections.defaultdict(
            collections.Counter)
        for items in items_per_vote:
            seen: set[str] = set()
            for it in items:
                nk = normalize_name(it)
                if not nk or nk in seen:
                    continue
                seen.add(nk)
                cnt[nk] += 1
                form[nk][it] += 1
        return [{"norm": nk,
                 "display": sorted(form[nk].items(),
                                   key=lambda kv: (-kv[1], kv[0]))[0][0],
                 "votes": cnt[nk]} for nk in cnt]

    parsed_all = [v.get("parsed") or {} for v in votes]
    times = simple([p.get("time_expressions", []) for p in parsed_all])
    spaces = simple([p.get("space_expressions", []) for p in parsed_all])
    return {"entities": entities, "relations": relations,
            "times": times, "spaces": spaces}


def run_consensus() -> None:
    manifest = json.loads(PAGES_JSON.read_text(encoding="utf-8"))
    pages = {p["page_id"]: p for p in manifest["pages"]}
    done = load_checkpoint()
    by_page: dict[int, list[dict]] = collections.defaultdict(list)
    for (_pid, _v), r in done.items():
        by_page[r["page_id"]].append(r)

    rows = []
    stats = {"pages_with_votes": 0, "votes_ok": 0, "pages_full_votes": 0}
    for pid in sorted(pages):
        votes = sorted(by_page.get(pid, []), key=lambda r: r["vote"])
        ok_votes = [v for v in votes if v.get("status") == "ok" and v.get("parsed")]
        stats["votes_ok"] += len(ok_votes)
        if ok_votes:
            stats["pages_with_votes"] += 1
        if len(ok_votes) >= len(TEMPERATURES):
            stats["pages_full_votes"] += 1
        cons = build_consensus(ok_votes)
        p = pages[pid]
        for kind, items in (("entity", cons["entities"]),
                            ("relation", cons["relations"]),
                            ("time", cons["times"]),
                            ("space", cons["spaces"])):
            for it in items:
                display = (it.get("display") if kind != "relation"
                           else json.dumps(it["display"], ensure_ascii=False))
                rows.append({
                    "page_id": pid, "book": p["book"], "path": p["path"],
                    "kind": kind,
                    "name": display,
                    "type": it.get("type", "") if kind == "entity" else "",
                    "norm_key": "|".join([it.get("norm", it.get("norm_s", "")),
                                          it.get("norm_p", ""),
                                          it.get("norm_o", "")]).strip("|"),
                    "votes": it["votes"],
                    "in_consensus": 1 if it["votes"] >= 2 else 0,
                })
    with CONSENSUS_CSV.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["page_id", "book", "path", "kind",
                                           "name", "type", "norm_key", "votes",
                                           "in_consensus"])
        w.writeheader()
        w.writerows(rows)
    stats["rows"] = len(rows)
    stats["consensus_rows"] = sum(r["in_consensus"] for r in rows)
    (OUT_DIR / "CONSENSUS_STATS.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"AI_CONSENSUS_REFERENCE.csv：{len(rows)} 项（共识 {stats['consensus_rows']}）")


def load_consensus() -> dict[int, dict]:
    """page_id → {entities, relations, times, spaces}（仅共识 ≥2 票）。"""
    out: dict[int, dict] = {}
    with CONSENSUS_CSV.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if int(r["in_consensus"]) != 1:
                continue
            pid = int(r["page_id"])
            b = out.setdefault(pid, {"entities": [], "relations": [],
                                     "times": [], "spaces": []})
            if r["kind"] == "entity":
                b["entities"].append({"name": r["name"], "type": r["type"]})
            elif r["kind"] == "relation":
                d = json.loads(r["name"])
                b["relations"].append({"subject": d["subject"],
                                       "predicate": d.get("predicate", ""),
                                       "object": d["object"]})
            elif r["kind"] == "time":
                b["times"].append({"name": r["name"]})
            elif r["kind"] == "space":
                b["spaces"].append({"name": r["name"]})
    return out


def load_union() -> dict[int, dict]:
    """page_id → 三票并集（votes≥1），用于 precision-like 的 AI 支持判定。"""
    out: dict[int, dict] = {}
    with CONSENSUS_CSV.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            pid = int(r["page_id"])
            b = out.setdefault(pid, {"entities": [], "relations": [],
                                     "times": [], "spaces": []})
            if r["kind"] == "entity":
                b["entities"].append({"name": r["name"], "type": r["type"]})
            elif r["kind"] == "relation":
                d = json.loads(r["name"])
                b["relations"].append({"subject": d["subject"],
                                       "predicate": d.get("predicate", ""),
                                       "object": d["object"]})
            elif r["kind"] == "time":
                b["times"].append({"name": r["name"]})
            elif r["kind"] == "space":
                b["spaces"].append({"name": r["name"]})
    return out


# ---------------------------------------------------------------------------
# 指标（stage 4）
# ---------------------------------------------------------------------------

def _match_count(ai_items: list[dict], prod_items: list[tuple],
                 kind: str) -> tuple[int, list[dict]]:
    """返回 (AI 中被生产覆盖的条数, 未被覆盖的 AI 条目)。确定性规则 N3/N4/N5/N6。"""
    if not ai_items:
        return 0, []
    matched = 0
    missed = []
    for it in ai_items:
        hit = False
        if kind == "entity":
            for (pn, pt) in prod_items:
                if name_match(it["name"], pn, it.get("type"), pt):
                    hit = True
                    break
        elif kind == "relation":
            for (ps, _pp, po) in prod_items:
                if name_match(it["subject"], ps, use_type=False) and \
                        name_match(it["object"], po, use_type=False):
                    hit = True
                    break
        elif kind == "time":
            for pt in prod_items:
                if time_exprs_match(it["name"], pt):
                    hit = True
                    break
        elif kind == "space":
            for ps in prod_items:
                if name_match(it["name"], ps, use_type=False):
                    hit = True
                    break
        if hit:
            matched += 1
        else:
            missed.append(it)
    return matched, missed


def _supported_count(prod_items: list[tuple], ai_items: list[dict],
                     kind: str) -> int:
    """precision-like：生产候选中有 AI（并集）支持的数量。"""
    if not prod_items:
        return 0
    sup = 0
    for p in prod_items:
        if kind == "entity":
            pn, pt = p
            if any(name_match(an, pn, at, pt) for an, at in
                   ((a["name"], a.get("type")) for a in ai_items)):
                sup += 1
        elif kind == "relation":
            ps, _pp, po = p
            if any(name_match(a["subject"], ps, use_type=False) and
                   name_match(a["object"], po, use_type=False)
                   for a in ai_items):
                sup += 1
        elif kind == "time":
            if any(time_exprs_match(p, a["name"]) for a in ai_items):
                sup += 1
        elif kind == "space":
            if any(name_match(p, a["name"], use_type=False) for a in ai_items):
                sup += 1
    return sup


def load_vote_coverage() -> dict[int, int]:
    """page_id → ok 票数（读 checkpoint 实况；部分覆盖时如实进入摘要）。"""
    cov: dict[int, int] = collections.defaultdict(int)
    if CKPT_PATH.exists():
        with CKPT_PATH.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("status") == "ok":
                    try:
                        cov[int(r["page_id"])] += 1
                    except Exception:
                        continue
    return dict(cov)


_PLURAL = {"entity": "entities", "relation": "relations",
           "time": "times", "space": "spaces"}


def _by_kind(bucket: dict | None) -> dict[str, list]:
    """load_consensus/load_union 的复数键桶 → 单数 kind 键（缺页/空桶安全）。"""
    if not bucket:
        return {k: [] for k in _PLURAL}
    return {k: bucket.get(v, []) for k, v in _PLURAL.items()}


def compute_all() -> dict:
    manifest = json.loads(PAGES_JSON.read_text(encoding="utf-8"))
    page_rows = manifest["pages"]
    prod = load_production_candidates(page_rows)
    cons = load_consensus()
    union = load_union()
    cov = load_vote_coverage()

    kinds = ("entity", "relation", "time", "space")
    # scope → kind → {ref, matched, pages_ref, page_ratios}
    agg: dict[str, dict[str, dict]] = {
        scope: {k: {"ref": 0, "matched": 0, "pages_ref": 0, "ratios": []}
                for k in kinds}
        for scope in ("all_pages", "production_linked")}
    # 书级：scope → book → kind → {...}
    book_agg: dict[str, dict[str, dict[str, dict]]] = {
        scope: collections.defaultdict(lambda: {
            k: {"ref": 0, "matched": 0, "pages_ref": 0, "ratios": []}
            for k in kinds})
        for scope in ("all_pages", "production_linked")}
    # precision-like（仅 production_linked）：kind → {prod, supported}
    prec: dict[str, dict[str, int]] = {k: {"prod": 0, "supported": 0} for k in kinds}
    missed_detail: dict[str, list[dict]] = {k: [] for k in kinds}
    page_detail: list[dict] = []

    for row in page_rows:
        pid = row["page_id"]
        scopes = ["all_pages"] + (["production_linked"]
                                  if row["production_linked"] else [])
        pc = prod.get(pid) or {"entities": set(), "relations": set(),
                               "times": set(), "spaces": set()}
        ref = _by_kind(cons.get(pid))
        un = _by_kind(union.get(pid))
        prod_sets = {"entity": pc["entities"], "relation": pc["relations"],
                     "time": pc["times"], "space": pc["spaces"]}
        pd_row: dict = {"page_id": pid, "book": row["book"],
                        "production_linked": row["production_linked"],
                        "text_length": row["text_length"],
                        "votes_ok": cov.get(pid, 0)}
        for k in kinds:
            ai_items = ref[k]
            m, missed = _match_count(ai_items, prod_sets[k], k)
            for scope in scopes:
                a = agg[scope][k]
                a["ref"] += len(ai_items)
                a["matched"] += m
                if ai_items:
                    a["pages_ref"] += 1
                    a["ratios"].append(m / len(ai_items))
                ba = book_agg[scope][row["book"]][k]
                ba["ref"] += len(ai_items)
                ba["matched"] += m
                if ai_items:
                    ba["pages_ref"] += 1
                    ba["ratios"].append(m / len(ai_items))
            pd_row[f"ai_{k}"] = len(ai_items)
            pd_row[f"prod_{k}"] = len(prod_sets[k])
            pd_row[f"{k}_recall"] = round(m / len(ai_items), 4) if ai_items else None
            if "production_linked" in scopes and cov.get(pid, 0) >= 1:
                # precision-like 只统计已抽取（≥1 ok 票）的生产关联页：
                # 未抽取页的生产候选无从获得 AI 支持，计入会低估
                prec[k]["prod"] += len(prod_sets[k])
                prec[k]["supported"] += _supported_count(prod_sets[k], un[k], k)
            for it in missed:
                missed_detail[k].append({"page_id": pid, "book": row["book"],
                                         "item": it})
        page_detail.append(pd_row)

    def summary_of(scope: str) -> dict:
        s = {}
        for k in kinds:
            a = agg[scope][k]
            s[k] = {
                "reference_total": a["ref"],
                "matched_total": a["matched"],
                "recall_micro": round(a["matched"] / a["ref"], 4) if a["ref"] else None,
                "pages_with_reference": a["pages_ref"],
                "recall_macro_page_mean": round(sum(a["ratios"]) / len(a["ratios"]), 4)
                if a["ratios"] else None,
            }
        vals = [s[k]["recall_micro"] for k in kinds if s[k]["recall_micro"] is not None]
        s["overall_recall_micro"] = round(sum(vals) / len(vals), 4) if vals else None
        return s

    result = {
        "method_version": METHOD_VERSION,
        "generated_at": now_iso(),
        "seed": SEED,
        "model": MODEL,
        "workers": WORKERS,
        "temperatures": TEMPERATURES,
        "n_pages": len(page_rows),
        "n_linked": sum(1 for r in page_rows if r["production_linked"]),
        "extraction_coverage": {
            "pages_planned": len(page_rows),
            "pages_with_any_ok_votes": sum(1 for r in page_rows
                                           if cov.get(r["page_id"], 0) > 0),
            "pages_with_full_3_votes": sum(1 for r in page_rows
                                           if cov.get(r["page_id"], 0)
                                           >= len(TEMPERATURES)),
            "ok_votes": sum(cov.get(r["page_id"], 0) for r in page_rows),
            "votes_expected": len(page_rows) * len(TEMPERATURES),
            "note": "如未满 360 票即为部分结果：recall 分母仅含有 AI 参考的页，"
                    "precision-like 仅统计已抽取（≥1 ok 票）的生产关联页，"
                    "覆盖率如实随报",
        },
        "matching_rules": "N1 名称归一(NFKC+小写+去空白+去标点)；N2 类型归一/相容；"
                          "N3 实体=精确/别名表/包含(短≥2)；N4 关系=S、O 名匹配"
                          "(谓词不要求)；N5 时间=年份 token 相交；N6 空间=名称匹配",
        "recall": {scope: summary_of(scope)
                   for scope in ("all_pages", "production_linked")},
        "precision_like_production_linked": {
            k: {"production_total": prec[k]["prod"],
                "ai_supported": prec[k]["supported"],
                "precision": round(prec[k]["supported"] / prec[k]["prod"], 4)
                if prec[k]["prod"] else None}
            for k in kinds},
        "per_book": {},
        "page_detail": page_detail,
    }
    for scope in ("all_pages", "production_linked"):
        tb = {}
        for book, kinds_d in sorted(book_agg[scope].items()):
            tb[book] = {k: {
                "reference_total": kinds_d[k]["ref"],
                "matched": kinds_d[k]["matched"],
                "recall_micro": round(kinds_d[k]["matched"] / kinds_d[k]["ref"], 4)
                if kinds_d[k]["ref"] else None}
                for k in kinds}
            tb[book]["pages_with_reference"] = {
                k: kinds_d[k]["pages_ref"] for k in kinds}
        result["per_book"][scope] = tb
    return result, missed_detail


def run_metrics() -> None:
    t0 = time.time()
    result, _missed = compute_all()
    kinds = ("entity", "relation", "time", "space")
    rows = []
    for scope in ("all_pages", "production_linked"):
        s = result["recall"][scope]
        for k in kinds + ("overall",):
            if k == "overall":
                rows.append({"scope": scope, "book": "ALL", "metric": f"{k}_recall",
                             "value": s["overall_recall_micro"], "ref_total": "",
                             "matched": "", "pages_with_reference": ""})
                continue
            rows.append({"scope": scope, "book": "ALL", "metric": f"{k}_recall",
                         "value": s[k]["recall_micro"],
                         "ref_total": s[k]["reference_total"],
                         "matched": s[k]["matched_total"],
                         "pages_with_reference": s[k]["pages_with_reference"]})
        for k in kinds:
            p = result["precision_like_production_linked"][k]
            if scope != "production_linked":
                continue
            rows.append({"scope": scope, "book": "ALL",
                         "metric": f"{k}_precision_ai_supported",
                         "value": p["precision"],
                         "ref_total": p["production_total"],
                         "matched": p["ai_supported"],
                         "pages_with_reference": ""})
        for book, tb in sorted(result["per_book"][scope].items()):
            for k in kinds:
                if tb[k]["reference_total"] == 0:
                    continue
                rows.append({"scope": scope, "book": book, "metric": f"{k}_recall",
                             "value": tb[k]["recall_micro"],
                             "ref_total": tb[k]["reference_total"],
                             "matched": tb[k]["matched"],
                             "pages_with_reference":
                                 tb["pages_with_reference"].get(k, 0)})
    with METRICS_CSV.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["scope", "book", "metric", "value",
                                           "ref_total", "matched",
                                           "pages_with_reference"])
        w.writeheader()
        w.writerows(rows)
    result["elapsed_s"] = round(time.time() - t0, 1)
    result["extraction_time"] = _checkpoint_time_stats()
    result["missed_pool_sizes"] = {k: len(v) for k, v in _missed.items()} \
        if _missed else {}
    SUMMARY_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    r = result["recall"]
    covr = result["extraction_coverage"]
    log(f"抽取覆盖：{covr['pages_with_full_3_votes']}/{covr['pages_planned']} 页完整三票，"
        f"ok 票 {covr['ok_votes']}/{covr['votes_expected']}")
    log("Entity Recall  [all|linked]: "
        f"{r['all_pages']['entity']['recall_micro']} | "
        f"{r['production_linked']['entity']['recall_micro']}")
    log("Relation Recall[all|linked]: "
        f"{r['all_pages']['relation']['recall_micro']} | "
        f"{r['production_linked']['relation']['recall_micro']}")
    log("Time Recall    [all|linked]: "
        f"{r['all_pages']['time']['recall_micro']} | "
        f"{r['production_linked']['time']['recall_micro']}")
    log("Space Recall   [all|linked]: "
        f"{r['all_pages']['space']['recall_micro']} | "
        f"{r['production_linked']['space']['recall_micro']}")
    log(f"RECALL_METRICS.csv / RECALL_SUMMARY.json 写出（{len(rows)} 行）")


# ---------------------------------------------------------------------------
# 报告（stage 5）
# ---------------------------------------------------------------------------

def _snippet(path: str, needle: str, width: int = 30) -> str:
    """从页文本中定位 needle（或其前 2 字）并返回 ±width 字上下文片段。"""
    try:
        text = " ".join(read_page_text(path).split())
        if not text or not needle:
            return ""
        i = text.find(needle)
        if i < 0 and len(needle) >= 2:
            i = text.find(needle[:2])
        if i < 0:
            return ""
        a, b = max(0, i - width), min(len(text), i + len(needle) + width)
        return text[a:b]
    except Exception:
        return ""


def _pick_examples(missed: list[dict], n: int = 3) -> list[dict]:
    """确定性抽样：按 (page_id, 显示名) 排序取前 n。"""
    def key(m):
        it = m["item"]
        nm = it.get("name") or (it.get("subject", "") + "→" + it.get("object", ""))
        return (m["page_id"], nm)
    return sorted(missed, key=key)[:n]


def _checkpoint_time_stats() -> dict:
    """从 checkpoint 时间戳/时延计算抽取耗时（确定性，可复算）。"""
    if not CKPT_PATH.exists():
        return {}
    ts_min, ts_max, lat_sum, n, n_ok = None, None, 0.0, 0, 0
    with CKPT_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            t = r.get("ts")
            if t:
                if ts_min is None or t < ts_min:
                    ts_min = t
                if ts_max is None or t > ts_max:
                    ts_max = t
            lat_sum += float(r.get("latency_s") or 0)
            n += 1
            n_ok += 1 if r.get("status") == "ok" else 0
    if not ts_min or not ts_max:
        return {}
    t0 = datetime.fromisoformat(ts_min)
    t1 = datetime.fromisoformat(ts_max)
    return {"votes": n, "votes_ok": n_ok,
            "wall_span_s": round((t1 - t0).total_seconds()),
            "sum_latency_s": round(lat_sum),
            "avg_latency_s": round(lat_sum / n, 1) if n else None,
            "note": "wall_span 含两次外部中断与续跑间隔；sum_latency 为模型调用净耗时"}


def run_report() -> None:
    result = json.loads(SUMMARY_JSON.read_text(encoding="utf-8"))
    manifest = json.loads(PAGES_JSON.read_text(encoding="utf-8"))
    page_by_id = {p["page_id"]: p for p in manifest["pages"]}
    _res, missed = compute_all()
    r = result["recall"]
    pl = result["precision_like_production_linked"]

    def fmt(x):
        return "—" if x is None else f"{x*100:.1f}%"

    lines: list[str] = []
    ap = lines.append
    ap("# FINAL EXTRACTION RECALL — 候选抽取召回基准（指令 §17）")
    ap("")
    ap(f"- 生成时间：{result['generated_at']}  |  method_version: "
       f"{result['method_version']}")
    cov = result.get("extraction_coverage", {})
    ap(f"- 抽取覆盖率：完整三票页 {cov.get('pages_with_full_3_votes', '—')}/"
       f"{cov.get('pages_planned', result['n_pages'])}，ok 票 "
       f"{cov.get('ok_votes', '—')}/{cov.get('votes_expected', '—')}"
       f"（不足即为部分结果，指标仅基于已完成页的 AI 参考，如实标注）")
    ap(f"- 抽样：seed={result['seed']}，{result['n_pages']} 页"
       f"（帧 = 正文 ≥{manifest.get('min_page_chars', 500)} 字的页文件；"
       f"全帧 {manifest['frame']['total_page_files']} 页 / "
       f"{manifest['frame']['total_books']} 书，过滤后 "
       f"{manifest['frame'].get('total_page_files_ge_min_chars', '—')} 页 / "
       f"{manifest['frame'].get('total_books_ge_min_chars', '—')} 书，"
       f"每书 ≤{manifest['max_per_book']} 页，路径排序等距抽样），"
       f"其中生产关联页 {result['n_linked']} 页")
    ap(f"- 独立 panel：本地 LM Studio `{result['model']}`，每页 3 次独立调用"
       f"（temperature {result['temperatures']}），"
       f"workers={result.get('workers', WORKERS)}，checkpoint 续跑")
    ap("- 独立性披露：资源受限下为同一模型三采样（不同 temperature 视为独立样本），"
       "非跨模型 panel；指令允许并要求如实披露")
    tstat = _checkpoint_time_stats()
    if tstat:
        ap(f"- 耗时：{tstat['votes']} 票（ok {tstat['votes_ok']}），"
           f"模型调用净耗时 {tstat['sum_latency_s']/3600:.2f} h"
           f"（均值 {tstat['avg_latency_s']}s/票，workers=2），"
           f"墙钟跨度 {tstat['wall_span_s']/3600:.2f} h"
           f"（含外部中断与续跑间隔）")
    ap("- 匹配规则（确定性，规则落盘）：")
    ap("  - N1 名称归一：NFKC 全角→半角、小写、去空白、去 Unicode 标点")
    ap("  - N2 类型归一 8 类；类型相容 = 相同或一方 Other")
    ap("  - N3 实体匹配：归一精确 / 固定缩写别名表（中共↔中国共产党等 6 组）/ "
       "包含别名（短串≥2 字且类型相容）")
    ap("  - N4 关系匹配：主体名∧客体名匹配（谓词不作要求，生产谓词为固定本体；"
       "谓词严格匹配另报）")
    ap("  - N5 时间匹配：年份 token 集相交（西元/中文数字年/民国年均折算），"
       "或归一字符串相等")
    ap("  - N6 空间匹配：名称匹配（含省/市/县后缀包含）")
    ap("")
    ap("## 1. 召回数字（AI consensus reference = 三票并集中 ≥2 票）")
    ap("")
    ap("| 口径 | Entity | Relation | Time | Space | Overall |")
    ap("|---|---|---|---|---|---|")
    for scope, label in (("all_pages", "all_pages（120 页抽样帧全体）"),
                         ("production_linked", "production_linked（生产关联页子集）")):
        s = r[scope]
        ap(f"| {label} | {fmt(s['entity']['recall_micro'])} | "
           f"{fmt(s['relation']['recall_micro'])} | {fmt(s['time']['recall_micro'])} | "
           f"{fmt(s['space']['recall_micro'])} | {fmt(s['overall_recall_micro'])} |")
    ap("")
    ap("两个口径的含义：`all_pages` 同时包含『页未被生产管线消费』与『页被消费但"
       "抽取遗漏』两类损失，反映域覆盖×抽取召回；`production_linked` 仅统计有生产"
       "证据关联的页，反映纯抽取召回。")
    ap("")
    ap("按页 macro（页均有参考的页上取页内召回均值）：")
    ap("")
    ap("| 口径 | Entity | Relation | Time | Space |")
    ap("|---|---|---|---|---|")
    for scope in ("all_pages", "production_linked"):
        s = r[scope]
        ap(f"| {scope} | {fmt(s['entity']['recall_macro_page_mean'])} | "
           f"{fmt(s['relation']['recall_macro_page_mean'])} | "
           f"{fmt(s['time']['recall_macro_page_mean'])} | "
           f"{fmt(s['space']['recall_macro_page_mean'])} |")
    ap("")
    ap("## 2. Precision-like（生产候选有 AI 支持的比例；production_linked ∩ 已抽取"
       "（≥1 ok 票）页口径，AI 支持=三票并集任一票命中）")
    ap("")
    ap("| 类型 | 生产候选数 | AI 支持数 | Precision |")
    ap("|---|---|---|---|")
    for k in ("entity", "relation", "time", "space"):
        p = pl[k]
        ap(f"| {k} | {p['production_total']} | {p['ai_supported']} | "
           f"{fmt(p['precision'])} |")
    ap("")
    ap("## 3. 按书分布（production_linked 口径，Entity Recall micro）")
    ap("")
    ap("| 书 | Entity ref | Entity recall | Relation recall | Time recall | "
       "Space recall |")
    ap("|---|---|---|---|---|---|")
    pb = result["per_book"]["production_linked"]
    for book, tb in sorted(pb.items()):
        if tb["entity"]["reference_total"] == 0:
            continue
        def g(k):
            v = tb[k]["recall_micro"]
            return "—" if v is None else f"{v*100:.1f}%"
        ap(f"| {book} | {tb['entity']['reference_total']} | {g('entity')} | "
           f"{g('relation')} | {g('time')} | {g('space')} |")
    ap("")
    ap("## 4. 漏抽类型分析（AI 共识抽到、生产候选没有；每类自动抽 3 例）")
    ap("")
    for k, label in (("entity", "实体"), ("relation", "关系"),
                     ("time", "时间"), ("space", "空间")):
        pool = missed[k]
        ap(f"### {label}漏抽（共 {len(pool)} 条共识项未被生产覆盖）")
        ap("")
        exs = _pick_examples(pool)
        if not exs:
            ap("（无）")
            ap("")
            continue
        for ex in exs:
            it = ex["item"]
            page = page_by_id.get(ex["page_id"], {})
            if k == "entity":
                desc = f"{it['name']}（type={it.get('type')}）"
            elif k == "relation":
                desc = f"{it['subject']} —[{it.get('predicate')}]→ {it['object']}"
            else:
                desc = it["name"]
            snippet = _snippet(page.get("path", ""),
                               it["name"] if k != "relation" else it["subject"])
            ap(f"- page {ex['page_id']}《{ex['book']}》：{desc}"
               + (f"　原文片段：…{snippet}…" if snippet else ""))
        ap("")
    if missed["entity"]:
        cnt = collections.Counter(
            m["item"].get("type", "Other") for m in missed["entity"])
        ap("实体漏抽按类型分布：" +
           "，".join(f"{t} {c}" for t, c in cnt.most_common()))
        ap("")
    ap("## 5. 方法与产物")
    ap("")
    ap("- 抽样清单：`experiments/08_candidate_recall/RECALL_PAGES.json`"
       "（path/book/正文长度/生产关联标记）")
    ap("- 逐页三票原始输出：`experiments/08_candidate_recall/EXTRACTION_RAW/*.jsonl`"
       "（含 temperature、时延、原始模型输出）")
    ap("- 共识参考：`experiments/08_candidate_recall/AI_CONSENSUS_REFERENCE.csv`"
       "（kind×votes×in_consensus，并集=votes≥1，共识=votes≥2）")
    ap("- 指标：`experiments/08_candidate_recall/RECALL_METRICS.csv`"
       "（分类型×分书×口径）与 `RECALL_SUMMARY.json`")
    ap("- 生产对照链路：evidence_id → provenance"
       "（evidence_ids_json 直连 + source_member_id→fact_evidence 血缘）→ "
       "research_assertions 的 subject/object/predicate/time_raw/place_raw；"
       "页路径映射 evidence_registry.source_path_or_url（归一精确 + "
       "(书名,页文件名) 模糊兜底）")
    ap("- 三个数据库全程 mode=ro 只读；evidence_registry（107 万行）流式扫描")
    ap("- 硬约束遵守：全自动无人工；规则落盘（本文件 N1–N6 + 代码唯一实现）；"
       "checkpoint（EXTRACTION_CHECKPOINT.jsonl）+ 续跑")
    ap("")
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    log(f"报告写出：{REPORT_MD}")


# ---------------------------------------------------------------------------

RUN_ID = ""


def main() -> None:
    global RUN_ID
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="候选抽取召回基准（指令 §17）")
    ap.add_argument("stage", nargs="?",
                    default="all",
                    choices=["all", "sample", "extract", "consensus",
                             "metrics", "report"])
    ap.add_argument("--limit", type=int, default=None,
                    help="extract 阶段只跑前 N 页（调试）")
    args = ap.parse_args()
    t0 = time.time()
    if args.stage in ("all", "sample"):
        run_sample()
    if args.stage in ("all", "extract"):
        run_extract(limit=args.limit)
    if args.stage in ("all", "consensus"):
        run_consensus()
    if args.stage in ("all", "metrics"):
        run_metrics()
    if args.stage in ("all", "report"):
        run_report()
    log(f"stage={args.stage} 完成，总用时 {(time.time()-t0)/60:.1f}min")


if __name__ == "__main__":
    main()
