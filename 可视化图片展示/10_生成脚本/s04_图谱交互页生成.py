# -*- coding: utf-8 -*-
"""s04_图谱交互页生成.py — 从真实图谱数据生成交互式可视化 HTML（供浏览器真实截图）。
数据源：最终库（严格层断言、事件框架、来源追溯、place/relation 契约）。只读。"""
import sqlite3, os, json, collections
import numpy as np
import pandas as pd
from pyvis.network import Network
import sys
sys.path.insert(0, r"D:\REDCULTUREDATA\可视化输出_生成脚本")
from style_lib import pz, SUP_C, TIER_C

MID = r"D:\REDCULTUREDATA\可视化输出\11_数据中间表"
HTMLDIR = r"D:\REDCULTUREDATA\可视化输出\13_预览总览\图谱交互页"
os.makedirs(HTMLDIR, exist_ok=True)
DB = r"D:\REDCULTUREDATA\投稿材料_代码数据整理包\submission_work\final_submission_v3_1\release_final\data\red_culture_stkg_final.sqlite"

TYPE_COLOR = {"Person": "#6E8CA0", "Event": "#C2A08B", "Place": "#7FA3A0", "Organization": "#8FA586",
              "Concept": "#A08BA0", "Document": "#8B93A8", "Institution": "#AD9E8C", "Artifact": "#A68080",
              "TimePeriod": "#B5989A", "AdministrativeRegion": "#7D8B99"}
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

def base_net(title, height="820px"):
    net = Network(height=height, width="100%", bgcolor="#ffffff", font_color="#2B2B2B", select_menu=False, filter_menu=False)
    net.force_atlas_2based(gravity=-32, central_gravity=0.012, spring_length=120, spring_strength=0.045, damping=0.42)
    net.set_options(json.dumps({
        "interaction": {"hover": True, "tooltipDelay": 80, "navigationButtons": False, "keyboard": False},
        "physics": {"stabilization": {"iterations": 420, "fit": True}},
        "nodes": {"font": {"size": 13, "face": "SimSun"}, "borderWidth": 1.2, "shape": "dot"},
        "edges": {"font": {"size": 10, "face": "SimSun"}, "smooth": {"type": "continuous"}},
    }))
    net.title = title
    return net

def postprocess_html(path, title):
    """注入标题栏 + 布局稳定后自动 fit 的脚本。"""
    with open(path, encoding="utf-8") as f:
        h = f.read()
    head = ('<div style="font-family:SimSun,serif;background:#ffffff;padding:10px 18px 4px 18px;">'
            f'<h2 style="margin:2px 0 6px 0;color:#2B2B2B;font-weight:bold;">{title}</h2>'
            '<div style="color:#6B6B6B;font-size:13px;">数据源：长江流域党史时空知识图谱最终库（sha256 020d4905…），'
            '交互式力导向布局，拖拽/滚轮可缩放</div></div>')
    inj = ("<script>setTimeout(function(){try{network.fit();}catch(e){}},6500);"
           "setTimeout(function(){try{network.fit();}catch(e){}},10000);"
           "setTimeout(function(){try{network.fit();}catch(e){}},14000);</script>")
    if "<body>" in h:
        h = h.replace("<body>", "<body>" + head, 1)
    h = h.replace("</body>", inj + "</body>", 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(h)

# ---------- 视图1：严格层核心实体网络（度 Top160） ----------
T34 = pd.read_csv(os.path.join(MID, "T34_严格层边表31067.csv"))
deg = collections.Counter()
for s in T34["主体ID"]: deg[s] += 1
for o in T34["客体ID"]: deg[o] += 1
name = dict(zip(T34["主体ID"], T34["主体名"]))
name.update(dict(zip(T34["客体ID"], T34["客体名"])))
typ = dict(zip(T34["主体ID"], T34["主体类型"]))
typ.update(dict(zip(T34["客体ID"], T34["客体Type"] if "客体Type" in T34 else T34["客体类型"])))
top = {e for e, _ in sorted(deg.items(), key=lambda kv: -kv[1])[:160]}
net = base_net("长江流域党史时空知识图谱 — 严格层核心实体网络（度 Top160，31,067 条严格断言诱导）")
for _, r in T34.iterrows():
    if r["主体ID"] in top and r["客体ID"] in top:
        net.add_node(r["主体ID"], label=str(r["主体名"])[:14], color=TYPE_COLOR.get(r["主体类型"], "#7D8B99"),
                     size=8 + 22 * np.log10(1 + deg[r["主体ID"]]), title=f"{r['主体名']}（{r['主体类型']}，度{deg[r['主体ID']]}）")
        net.add_node(r["客体ID"], label=str(r["客体名"])[:14], color=TYPE_COLOR.get(r["客体类型"], "#7D8B99"),
                     size=8 + 22 * np.log10(1 + deg[r["客体ID"]]), title=f"{r['客体名']}（{r['客体类型']}，度{deg[r['客体ID']]}）")
        net.add_edge(r["主体ID"], r["客体ID"], title=pz(str(r["谓词"])), color="#C9C4BC", width=0.6)
f1 = os.path.join(HTMLDIR, "截图1_严格层核心实体网络.html"); net.write_html(f1, notebook=False); postprocess_html(f1, net.title)
print("视图1 ok")

# ---------- 视图2：南昌起义事件中心 ----------
dfn = pd.read_csv(os.path.join(MID, "T35_案例_南昌起义.csv"))
evn = dfn["事件名"].value_counts().index[0]
dfe = dfn[dfn["事件名"] == evn].drop_duplicates(subset=["关联对象"])
cnt_all = dfe["关联对象"].value_counts().head(60)
dfe = dfe[dfe["关联对象"].isin(cnt_all.index)]
cnt = dfe["关联对象"].value_counts()
net = base_net(f"EventFrame 案例视图 —「{evn}」事件中心子图（严格层角色 {len(dfe)} 条）")
net.add_node("EV", label=evn, color="#3E5C6E", size=46, font={"size": 22, "color": "#FFFFFF", "bold": True}, title=f"中心事件：{evn}")
for _, r in dfe.iterrows():
    c = TYPE_COLOR.get(r["对象类型"], "#7D8B99")
    net.add_node(r["关联对象"], label=str(r["关联对象"])[:12], color=c, size=10 + 16 * np.log10(1 + cnt[r["关联对象"]]),
                 title=f"{r['关联对象']}（{r['对象类型']}｜角色：{r['角色类别']}）")
    net.add_edge("EV", r["关联对象"], title=str(r["谓词"]), color="#B9C2C9", width=0.8)
f2 = os.path.join(HTMLDIR, "截图2_南昌起义事件中心子图.html"); net.write_html(f2, notebook=False); postprocess_html(f2, net.title)
print("视图2 ok")

# ---------- 视图3：人物—组织二部网络 ----------
po = T34[(T34["主体类型"] == "Person") & (T34["客体类型"] == "Organization")]
ec = po.groupby(["主体名", "客体名"]).size().sort_values(ascending=False).head(90)
net = base_net("人物—组织关联网络（严格层，共现 Top90 边）")
for (s, o), w in ec.items():
    net.add_node("P:" + s, label=s[:12], color=TYPE_COLOR["Person"], size=9 + 9 * np.log10(1 + w), title=f"人物：{s}")
    net.add_node("O:" + o, label=o[:14], color=TYPE_COLOR["Organization"], size=8 + 9 * np.log10(1 + w), title=f"组织：{o}")
    net.add_edge("P:" + s, "O:" + o, title=f"关联 {w} 条", color="#C9C4BC", width=0.5 + 0.3 * w)
f3 = os.path.join(HTMLDIR, "截图3_人物组织二部网络.html"); net.write_html(f3, notebook=False); postprocess_html(f3, net.title)
print("视图3 ok")

# ---------- 视图4：来源追溯链（随机抽3条严格断言的 provenance 全链） ----------
net = base_net("来源追溯链示例 — 知识陈述 → 来源记录 → 原文证据（严格层抽样）")
rows = con.execute("""
SELECT a.fact_id, a.subject_name, a.predicate, a.object_name, p.provenance_id, p.evidence_ids_json
FROM research_assertions a JOIN research_assertion_provenance p ON a.fact_id = p.fact_id
WHERE a.research_tier='strict_semantic' AND p.evidence_ids_json IS NOT NULL
  AND LENGTH(p.evidence_ids_json) BETWEEN 8 AND 120 LIMIT 4
""").fetchall()
qid = 0
for fid, sub, pred, obj, pid, evj in rows:
    net.add_node("F" + fid, label=f"{str(sub)[:10]} —{str(pred)[:8]}— {str(obj)[:10]}", color="#3E5C6E",
                 size=22, title=f"断言 {fid}")
    net.add_node(pid, label="来源记录", color="#AD9E8C", size=14, title=pid)
    net.add_edge("F" + fid, pid, title="来源支持", color="#C9C4BC")
    try:
        evs = json.loads(evj)
        for e in list(evs)[:3]:
            qid += 1
            q = con.execute("SELECT evidence_text FROM evidence_registry WHERE evidence_id=?", (e,)).fetchone()
            txt = (q[0][:60] + "…") if q and q[0] else str(e)
            net.add_node(e, label=f"证据 {qid}", color="#8FA586", size=11, title=txt)
            net.add_edge(pid, e, title="定位到原文片段", color="#C9C4BC")
    except Exception:
        pass
f4 = os.path.join(HTMLDIR, "截图4_来源追溯链.html"); net.write_html(f4, notebook=False); postprocess_html(f4, net.title)
print("视图4 ok")

# ---------- 视图5：大事件—参与组织网络（Top10 事件框架） ----------
T36 = pd.read_csv(os.path.join(MID, "T36_大事件Top30.csv"))
top_ev = T36.head(10)["事件名"].tolist()
net = base_net("重大事件框架网络（Top10 事件 × 关联角色对象，严格层）")
added = set()
for ev in top_ev:
    d = pd.read_csv(os.path.join(MID, f"T35_案例_南昌起义.csv"))  # placeholder replaced below
    break
# 直接从库里取这10个事件的角色
for ev in top_ev:
    rows = con.execute("""
    SELECT er.counterpart_name, er.counterpart_type, COUNT(*) FROM research_event_roles er
    JOIN research_event_frames ef ON er.event_id = ef.event_id
    WHERE ef.event_name = ? GROUP BY 1,2 ORDER BY 3 DESC LIMIT 8
    """, (ev,)).fetchall()
    if ev not in added:
        net.add_node("E:" + ev, label=ev[:12], color="#C2A08B", size=26, font={"size": 15}, title=f"事件：{ev}")
        added.add(ev)
    for nm, tp, w in rows:
        key = f"X:{nm}"
        if key not in added:
            net.add_node(key, label=str(nm)[:10], color=TYPE_COLOR.get(tp, "#7D8B99"), size=7 + 5 * np.log10(1 + w),
                         title=f"{nm}（{tp}）")
            added.add(key)
        net.add_edge("E:" + ev, key, color="#CFC9C0", width=0.5)
f5 = os.path.join(HTMLDIR, "截图5_重大事件框架网络.html"); net.write_html(f5, notebook=False); postprocess_html(f5, net.title)
print("视图5 ok")

# ---------- 视图6：全库三层总览（分层采样，节点=类型聚合气泡+层带） ----------
net = Network(height="820px", width="100%", bgcolor="#ffffff", font_color="#2B2B2B")
net.force_atlas_2based(gravity=-18, spring_length=90)
net.set_options(json.dumps({
    "interaction": {"hover": True, "navigationButtons": True},
    "nodes": {"font": {"size": 12, "face": "SimSun"}},
    "physics": {"stabilization": {"iterations": 150}},
}))
tiers = [("STRICT 严格层", 31067, "#3E5C6E", ["人物", "组织", "事件", "地点"]),
         ("CONTEXTUAL 上下文层", 299329, "#93A692", ["叙事关联", "弱谓词", "背景陈述"]),
         ("UNRESOLVED 未决层", 93754, "#C8AE8E", ["作用域冲突", "端点未决", "证据不支持"])]
for tname, n, col, examples in tiers:
    net.add_node(tname, label=f"{tname}\n{n:,} 条", color=col, size=48, font={"size": 16}, shape="box")
    for ex in examples:
        net.add_node(tname + ex, label=ex, color=col, size=16, shape="box", title=f"{tname} 示例节点类型")
        net.add_edge(tname, tname + ex, color=col, width=1.2)
net.title = "全库三层知识状态总览（STRICT 严格层 / CONTEXTUAL 上下文层 / UNRESOLVED 未决层）"
net.add_edge("STRICT 严格层", "CONTEXTUAL 上下文层", title="证据核验降级 31,282", dashes=True, color="#8B93A8")
net.add_edge("CONTEXTUAL 上下文层", "UNRESOLVED 未决层", title="前置未决 / 证据不足", dashes=True, color="#8B93A8")
f6 = os.path.join(HTMLDIR, "截图6_全库三层总览.html"); net.write_html(f6, notebook=False); postprocess_html(f6, net.title)
print("视图6 ok")
con.close()
print("全部交互页生成完成 →", HTMLDIR)
