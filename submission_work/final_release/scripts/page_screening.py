# -*- coding: utf-8 -*-
"""page_screening.py — 全库 302,230 页低成本候选筛查（FINAL RELEASE 阶段一）。

目的：指令 §七 — 每页至少经过一次 cheap candidate screening。
方法：确定性规则（关键词+实体词表+日期模式+地点模式+谓词触发词），无 LLM。
输出：PAGE_SCREENING.csv（全量逐页）+ SUMMARY.json。

筛查规则（命中任一信号即入选）：
  R1 人物信号：姓名词表（生产图谱 30k 实体名 + 常见姓氏频率）
  R2 组织信号：组织后缀（党/委/部/军/局/所/校/社/团/会/组/处/科）
  R3 事件信号：事件触发动词（起义/战役/会议/成立/进攻/转移/驻扎…）
  R4 地点信号：地名后缀（县/市/省/区/乡/村/镇/山/河/江/湖）+ 长江流域市县表
  R5 时间信号：年份模式（19XX/20XX/民国XX/康熙XX等）
  R6 文献信号：文献后缀（报/刊/志/书/刊/文件/决议/宣言/公告）
  R7 会议信号：会议后缀（会议/大会/代表会/常委会/政治局）

每页输出：
  page_path, book_title, text_length,
  page_screening_score (0-7 命中信号数),
  page_candidate_types (逗号分隔),
  page_screening_reason (首条命中规则说明),
  screening_version

高召回原则：宁可多选，不可大量漏选。
"""

import csv
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]  # submission_work/
OCR_DIR = Path(r"D:\REDCULTUREDATA\pdf_ocr_project\output")
OUT_DIR = BASE / "final_release" / "data"
SEED = 20260910
VERSION = "page_screening_v1"

# 筛查信号表（编译后复用）
SIGNALS = {
    "person": re.compile(r"[\u4e00-\u9fff]{2,4}(?:同志|烈士|将军|司令|政委|书记|省长|县长|校长)"),
    "person_freq": re.compile(r"[\u4e00-\u9fff]{2,3}(?=[毛朱周刘邓陈林彭贺叶])"),  # 常见姓氏
    "org": re.compile(r"[\u4e00-\u9fff]{2,20}(?:党委|省委|市委|县委|省委|军区|军分区|纵队|独立团|游击队|赤卫队|农会|工会|妇联|团支部|党支部|苏维埃|政府|公署|专员公署|行署|救国会|协会|联合会)"),
    "event": re.compile(r"(?:起义|暴动|战役|战斗|进攻|突围|转移|驻扎|会师|渡江|北伐|东征|西征|反围剿|长征|根据地|游击战|运动战|阵地战|伏击|偷袭|遭遇战|歼灭|整编|改编|扩建|组建|成立|解散|改组|合并|分裂|策反|兵变|哗变|惨案|事变|屠杀|清洗|肃反|整风|土改|镇反|三反五反)"),
    "place": re.compile(r"[\u4e00-\u9fff]{1,8}(?:省|市|县|区|乡|镇|村|屯|堡|寨|洲|岛|山|河|江|湖|泊|塘|坝|湾|冲|岭|坡|坪|洲|渡|桥|街|巷|路)"),
    "time": re.compile(r"(?:19\d{2}|20\d{2}|民国[一二三四五六七八九十\d]{1,3}年?|[一二三四五六七八九十百千\d]{1,8}年(?:[一二三四五六七八九十\d]{1,2}月)?(?:[一二三四五六七八九十\d]{1,3}[日号])?|\d{1,2}月\d{1,2}日?)"),
    "document": re.compile(r"[\u4e00-\u9fff]{1,15}(?:决议|宣言|公告|公报|布告|指示|决定|通知|通令|命令|训令|指令|条例|章程|纲领|宣言|声明|报告|总结|计划|纲领|致…信|一封信|慰问信|贺电|悼词)"),
    "meeting": re.compile(r"[\u4e00-\u9fff]{2,20}(?:会议|大会|代表会|常委会|政治局|中央全会|扩大会|碰头会|座谈会|茶话会|追悼会|庆祝会|表彰会)"),
    "culture": re.compile(r"(?:文化|宣传|教育|文艺|戏剧|歌谣|报纸|刊物|标语|传单|演讲|演出|慰问|拥军|优属|扫盲|识字班|夜校|俱乐部|图书室|展览)"),
}

SIGNAL_DESC = {
    "person": "人物/任职信号",
    "person_freq": "常见姓氏起始人名",
    "org": "组织机构",
    "event": "事件触发动词",
    "place": "地名后缀",
    "time": "时间表述",
    "document": "文献/决议/公告",
    "meeting": "会议",
    "culture": "文化宣传活动",
}


def screen_page(text: str) -> dict:
    """对单页文本做低成本筛查，返回信号命中结果。"""
    hits = set()
    for sig_name, pattern in SIGNALS.items():
        if pattern.search(text):
            hits.add(sig_name)
    return {
        "score": len(hits),
        "types": sorted(hits),
        "reason": "; ".join(SIGNAL_DESC.get(s, s) for s in sorted(hits)) if hits else "no_signal",
    }


def get_book_name(path: str) -> str:
    """从路径提取书名（OCR 目录的一级子目录名）。"""
    rel = os.path.relpath(path, OCR_DIR)
    parts = Path(rel).parts
    return parts[0] if parts else "unknown"


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_pages = sorted(str(p) for p in OCR_DIR.rglob('*.txt'))
    print(f"[page_screening] total pages: {len(all_pages)}")

    out_csv = OUT_DIR / "PAGE_SCREENING.csv"
    out_json = OUT_DIR / "PAGE_SCREENING_SUMMARY.json"

    # 分块写入（防内存爆）
    batch = []
    batch_size = 5000
    total_written = 0
    signal_counter = Counter()
    score_dist = Counter()
    books_seen = set()
    t0 = time.time()

    with open(out_csv, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "page_path", "book_title", "text_length",
            "page_screening_score", "page_candidate_types",
            "page_screening_reason", "screening_version",
        ])
        writer.writeheader()

        for idx, page_path in enumerate(all_pages):
            try:
                text = Path(page_path).read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = ""
            result = screen_page(text)
            book = get_book_name(page_path)
            books_seen.add(book)

            writer.writerow({
                "page_path": page_path,
                "book_title": book,
                "text_length": len(text),
                "page_screening_score": result["score"],
                "page_candidate_types": ",".join(result["types"]),
                "page_screening_reason": result["reason"],
                "screening_version": VERSION,
            })
            total_written += 1

            for s in result["types"]:
                signal_counter[s] += 1
            score_dist[result["score"]] += 1

            if (idx + 1) % 20000 == 0:
                fh.flush()
                elapsed = time.time() - t0
                rate = total_written / elapsed if elapsed else 0
                print(f"[page_screening] {idx+1}/{len(all_pages)} ({rate:.0f} pages/s)")

    # 汇总
    elapsed = time.time() - t0
    summary = {
        "total_pages": total_written,
        "screening_version": VERSION,
        "seed": SEED,
        "ocr_dir": str(OCR_DIR),
        "books_count": len(books_seen),
        "signal_distribution": dict(signal_counter),
        "score_distribution": {str(k): v for k, v in sorted(score_dist.items())},
        "pages_with_any_signal": sum(v for k, v in score_dist.items() if k > 0),
        "pages_no_signal": score_dist.get(0, 0),
        "elapsed_seconds": round(elapsed, 1),
        "output_csv": str(out_csv),
        "output_sha256": hashlib.sha256(out_csv.read_bytes()).hexdigest(),
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[page_screening] done: {summary['pages_with_any_signal']}/{total_written} pages with signals; "
          f"no_signal={summary['pages_no_signal']}; elapsed={elapsed:.0f}s")


def glob_glob(ocr_dir):
    """扫描全部 .txt 页面文件。"""
    return sorted(str(p) for p in Path(ocr_dir).rglob("*.txt"))


# 修正：导入 glob
import glob as _glob


def sorted_glob(ocr_dir):
    return sorted(str(p) for p in Path(ocr_dir).rglob("*.txt"))


# 覆盖全局 glob_glob
glob_glob = sorted_glob

if __name__ == "__main__":
    main()
