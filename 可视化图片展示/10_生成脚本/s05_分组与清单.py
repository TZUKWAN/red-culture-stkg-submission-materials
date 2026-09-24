# -*- coding: utf-8 -*-
"""s05_分组与清单.py — 阶段5-8：精选/正文/附录分组、总清单、预览图库、章节建议。"""
import os, json, shutil, glob
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

ROOT = r"D:\REDCULTUREDATA\可视化输出"
CAND = os.path.join(ROOT, "01_候选图总库")
BOARD = os.path.join(ROOT, "05_组合图板")
NET = os.path.join(ROOT, "07_网络图")
REG = os.path.join(ROOT, "12_图件清单", "生成登记.jsonl")

# ---------- 1. 登记 8 张图谱真实截图 ----------
shots = [
 ("GJ1", "图谱截图1_严格层核心实体网络", "浏览器真实截图：严格层核心实体网络交互视图（度Top160诱导子图，力导向布局）", "s04+pyvis+浏览器截图"),
 ("GJ2", "图谱截图2_南昌起义事件中心子图", "浏览器真实截图：南昌起义 EventFrame 事件中心子图（60个真实角色节点）", "s04+pyvis+浏览器截图"),
 ("GJ3", "图谱截图3_人物组织二部网络", "浏览器真实截图：人物—组织二部网络（严格层共现 Top90 边）", "s04+pyvis+浏览器截图"),
 ("GJ4", "图谱截图4_来源追溯链", "浏览器真实截图：知识陈述→来源记录→原文证据的追溯链示例", "s04+pyvis+浏览器截图"),
 ("GJ5", "图谱截图5_重大事件框架网络", "浏览器真实截图：Top10 重大事件框架与关联角色对象网络", "s04+pyvis+浏览器截图"),
 ("GJ6", "图谱截图6_全库三层总览", "浏览器真实截图：全库三层知识状态结构总览（STRICT/CONTEXTUAL/UNRESOLVED）", "s04+pyvis+浏览器截图"),
 ("GJ7", "图谱截图7_人物时空轨迹_项目原生", "项目原生可视化页面截图：人物时空轨迹（figures/stkg_viz2，2026-09-11 产物）", "浏览器截图"),
 ("GJ8", "图谱截图8_全库分层总览_项目原生", "项目原生可视化页面截图：十年×河段断言密度+research_tier（figures/stkg_viz5）", "浏览器截图"),
]
with open(REG, "a", encoding="utf-8") as f:
    have = set()
    for l in open(REG, encoding="utf-8"):
        have.add(json.loads(l)["图号"])
    for gid, name, note, src in shots:
        if gid not in have:
            f.write(json.dumps({"图号": gid, "图名": name.replace("图谱截图", ""), "文件名": name,
                                "类别": "图谱真实截图", "脚本": src,
                                "数据源": ["最终库 strict 层 / figures/*.html（项目原生）"],
                                "说明": note, "格式": ["png"]}, ensure_ascii=False) + "\n")
print("[1] 截图登记完成")

# ---------- 2. 分组复制 ----------
def cp(prefix_glob, destdir):
    os.makedirs(destdir, exist_ok=True)
    n = 0
    files = []
    for pat in prefix_glob:
        for p in glob.glob(os.path.join(CAND, pat + "*.png")):
            base = os.path.basename(p)[:-4]
            for ext in (".png", ".svg", ".pdf"):
                src = os.path.join(CAND, base + ext)
                if os.path.exists(src):
                    shutil.copy(src, os.path.join(destdir, base + ext))
            files.append(base); n += 1
    return sorted(set(files))

MAIN = ["H01", "H03", "H06", "H07", "H09", "H18", "F04", "F06", "F16", "G01", "G05", "G08",
        "J01", "J04", "J12", "A01", "A03", "B10", "E01", "E13"]  # 正文主图 20
APPX = ["A02", "A04", "A05", "A07", "A09", "A11", "A14", "B01", "B03", "B04", "B05", "B07", "B09",
        "B14", "B16", "C01", "C05", "C07", "D01", "D02", "D05", "D08", "E04", "E06", "E08", "E10",
        "E15", "F03", "F08", "F09", "G02", "G07", "H05", "H11", "H16", "I03", "I06", "I07", "J02",
        "J05", "J06", "J07", "J14", "K01", "K06", "K09", "L05"]  # 附录 47
SELECTED = MAIN + APPX + ["H02", "H04", "H10", "H17", "F01", "F11", "G06", "I10", "J03", "J09", "K03", "K10", "L01", "L09", "L10", "C10"]  # 精选 63

main_files = cp(MAIN, os.path.join(ROOT, "03_正文主图"))
appx_files = cp(APPX, os.path.join(ROOT, "04_附录图"))
sel_files = cp(SELECTED, os.path.join(ROOT, "02_精选图"))

# 板与专题目录
for pat, dest in [("板", os.path.join(ROOT, "05_组合图板"))]:
    pass  # 板已在原位
case_files = cp(["L0", "L1", "I10", "E05"], os.path.join(ROOT, "06_案例图"))
net_files = cp(["B10", "B11", "B12", "B13", "L07", "L08", "L15", "L16"], NET)
st_files = cp(["E0", "E1"], os.path.join(ROOT, "08_时空图"))
audit_files = cp(["I0", "J0", "J1"], os.path.join(ROOT, "09_审计与证据图"))
print(f"[2] 分组完成：正文主图 {len(main_files)} / 附录 {len(appx_files)} / 精选 {len(sel_files)} / 案例 {len(case_files)} / 时空 {len(st_files)} / 审计证据 {len(audit_files)}")

# ---------- 3. 05_图件总清单.xlsx ----------
recs = [json.loads(l) for l in open(REG, encoding="utf-8")]
seen = {}
for r in recs:
    seen[(r["图号"], r["图名"])] = r
rows = []
GROUP_MAP = {}
for f in main_files: GROUP_MAP[f] = "正文主图"
for f in appx_files: GROUP_MAP.setdefault(f, "附录图")
for f in sel_files: GROUP_MAP.setdefault(f, "精选图")
for f in case_files: GROUP_MAP.setdefault(f, "案例图")
for f in net_files: GROUP_MAP.setdefault(f, "网络图")
for f in st_files: GROUP_MAP.setdefault(f, "时空图")
for f in audit_files: GROUP_MAP.setdefault(f, "审计与证据图")
CAT2CH = {"正文主图": "正文优先", "附录图": "附录优先", "精选图": "备选图库", "案例图": "案例/补充",
          "网络图": "案例/补充", "时空图": "案例/补充", "审计与证据图": "案例/补充"}
for (gid, nm), r in seen.items():
    fn = r["文件名"]
    grp = GROUP_MAP.get(fn, "")
    rows.append([gid, nm, fn, r.get("类别", ""), r.get("脚本", ""), "；".join(r.get("数据源", [])),
                 r.get("说明", ""), grp, CAT2CH.get(grp, "候选图库"),
                 "已生成" if (os.path.exists(os.path.join(CAND, fn + ".png")) or os.path.exists(os.path.join(NET, fn + ".png"))
                              or os.path.exists(os.path.join(BOARD, fn + ".png"))) else "仅登记"])
wb = Workbook(); ws = wb.active; ws.title = "图件总清单"
ws.append(["图号", "中文图名", "文件名", "类别", "生成脚本", "数据源", "一句话结论/说明", "分组", "推荐层级", "状态"])
for r in sorted(rows, key=lambda x: x[0]):
    ws.append(r)
for c in ws[1]:
    c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="7A8B99")
for i, wd in enumerate([7, 26, 34, 14, 22, 40, 50, 10, 10, 8], 1):
    ws.column_dimensions[get_column_letter(i)].width = wd
ws.freeze_panes = "A2"
wb.save(os.path.join(ROOT, "12_图件清单", "05_图件总清单.xlsx"))
print(f"[3] 总清单完成：{len(rows)} 行")

# ---------- 4. 06_全部图件预览.html ----------
def find_png(fn):
    for d in [CAND, BOARD, NET, os.path.join(ROOT, "06_案例图")]:
        p = os.path.join(d, fn + ".png")
        if os.path.exists(p): return os.path.relpath(p, ROOT).replace("\\", "/")
    return None
html = ["<!DOCTYPE html><html><head><meta charset='utf-8'><title>全部图件预览</title>",
        "<style>body{font-family:SimSun,serif;background:#fafaf8;margin:20px;}",
        "h1{color:#2B2B2B;} h2{color:#3E5C6E;border-bottom:2px solid #D8D4CC;padding-bottom:4px;}",
        ".card{background:#fff;border:1px solid #e2ded6;border-radius:8px;padding:10px;margin:12px 0;}",
        ".card img{max-width:100%;height:auto;}",
        ".cap{color:#555;font-size:13px;margin-top:4px;}</style></head><body>",
        "<h1>长江流域党史时空知识图谱论文可视化 — 全部图件预览</h1>",
        "<p>候选图 155 · 组合图板 8 · 图谱真实截图 8（另见 07_网络图/图谱截图*.png）</p>"]
bycat = {}
for (gid, nm), r in sorted(seen.items()):
    fn = r["文件名"]; rel = find_png(fn)
    if rel is None: continue
    bycat.setdefault(r.get("类别", "其他"), []).append((gid, nm, fn, rel, r))
CATS = ["语料与基础", "图谱结构", "实体层", "谓词关系", "时空图", "时空作用域", "选择性预测", "级联准入",
        "证据核验", "审计评价", "跨来源稳健性", "构建效率", "案例网络", "案例路径", "案例图", "方法概念", "组合图板"]
for cat in CATS:
    if cat not in bycat: continue
    html.append(f"<h2>{cat}（{len(bycat[cat])}）</h2>")
    for gid, nm, fn, rel, r in bycat[cat]:
        html.append(f"<div class='card'><b>{gid} · {nm}</b><br><img loading='lazy' src='../{rel}'><div class='cap'>{r.get('说明','')}</div></div>")
html.append("</body></html>")
with open(os.path.join(ROOT, "13_预览总览", "06_全部图件预览.html"), "w", encoding="utf-8") as f:
    f.write("\n".join(html))
print("[4] HTML 预览图库完成")

# ---------- 5. 重命名设计清单 + 04 文档 ----------
old = os.path.join(ROOT, "00_项目盘点", "03_候选图设计清单.xlsx")
new = os.path.join(ROOT, "00_项目盘点", "03_120张候选图设计清单.xlsx")
if os.path.exists(old) and not os.path.exists(new):
    shutil.move(old, new)
print("[5] 设计清单已重命名")
print("全部分组与清单工作完成")
