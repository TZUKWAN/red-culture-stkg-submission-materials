# -*- coding: utf-8 -*-
"""
s01_数据提取_全量中间表.py
从权威数据库与实验产物中提取全部可视化中间表（CSV/JSON）到 11_数据中间表/。
数据源（全部只读）：
  DB  : submission_work/final_submission_v3_1/release_final/data/red_culture_stkg_final.sqlite  (sha256 020d4905…)
  DB2 : data/release_databases/red_culture_stkg_semantic_v2.sqlite （构建管线库：身份决议/名称聚类/标签投票）
  EXP : experiments/02_selective_semantic/budget_v2/  05_scope_repair/  09_cross_source_robustness/
        10_full_universe_admission_closure/  release_final/experiments/quality_audit/  manifests/
所有数字与 AUTHORITATIVE_RESULTS.md 一致；本脚本不修改任何源文件。
"""
import sqlite3, json, csv, os, shutil, collections, math

REPO = r"D:\REDCULTUREDATA\投稿材料_代码数据整理包"
V31 = os.path.join(REPO, "submission_work", "final_submission_v3_1")
DB = os.path.join(V31, "release_final", "data", "red_culture_stkg_final.sqlite")
DB2 = os.path.join(REPO, "data", "release_databases", "red_culture_stkg_semantic_v2.sqlite")
OUT = r"D:\REDCULTUREDATA\可视化输出\11_数据中间表"
os.makedirs(OUT, exist_ok=True)

def wcsv(name, header, rows):
    p = os.path.join(OUT, name)
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(header)
        for r in rows: w.writerow(r)
    print(f"  [OK] {name}  rows={len(rows)}")

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = con.cursor()
con2 = sqlite3.connect(f"file:{DB2}?mode=ro", uri=True)
cur2 = con2.cursor()

# ---------- T01 省域断言统计 ----------
rows = cur.execute("""
SELECT province, research_tier, COUNT(*) FROM research_assertions
WHERE province IS NOT NULL AND province != '' GROUP BY province, research_tier
""").fetchall()
agg = collections.defaultdict(lambda: collections.Counter())
for prov, tier, n in rows:
    agg[prov][tier or 'unknown'] += n
wcsv("T01_省域断言统计.csv", ["省份", "断言总数", "严格层", "上下文层", "未决层"],
     [[p, sum(c.values()), c.get('strict_semantic', 0), c.get('contextual', 0), c.get('unresolved', 0)]
      for p, c in sorted(agg.items(), key=lambda kv: -sum(kv[1].values()))])

# ---------- T02 实体类型分布 ----------
rows = cur.execute("SELECT entity_type, COUNT(*) FROM research_entities GROUP BY entity_type ORDER BY 2 DESC").fetchall()
tv = dict(cur.execute("SELECT entity_type, type_validation_status, COUNT(*) FROM research_entities GROUP BY 1,2").fetchall() and [])
tvv = collections.defaultdict(collections.Counter)
for t, s, n in cur.execute("SELECT entity_type, type_validation_status, COUNT(*) FROM research_entities GROUP BY 1,2"):
    tvv[t][s] += n
wcsv("T02_实体类型分布.csv", ["实体类型", "数量", "类型已验证", "类型未决"],
     [[t, n, tvv[t].get('validated', tvv[t].get('verified', 0)), sum(v for k, v in tvv[t].items() if k and 'pend' in str(k).lower())] for t, n in rows])

# ---------- T03 谓词分布（规范 vs raw） ----------
rows = cur.execute("SELECT predicate, COUNT(*) FROM research_assertions GROUP BY predicate ORDER BY 2 DESC").fetchall()
wcsv("T03_谓词分布.csv", ["谓词", "断言数", "是否原始形式(raw:)"],
     [[p, n, 1 if str(p).startswith('raw:') else 0] for p, n in rows])

# ---------- T04 谓词规范化映射（raw→canonical） ----------
rows = cur.execute("""
SELECT pr.source_predicate AS rawp, a.predicate AS canon, COUNT(*) AS n
FROM research_assertion_provenance pr JOIN research_assertions a ON pr.fact_id = a.fact_id
GROUP BY pr.source_predicate, a.predicate ORDER BY n DESC
""").fetchall()
wcsv("T04_谓词规范化映射.csv", ["原始谓词", "规范谓词", "断言数"], rows)

# ---------- T05 时间年分布 ----------
rows = cur.execute("""
SELECT CAST(strftime('%Y', time_start) AS INT), research_tier, COUNT(*)
FROM research_assertions WHERE time_start IS NOT NULL AND time_start >= '1800-01-01' AND time_start <= '2026-12-31'
GROUP BY 1, 2
""").fetchall()
agg = collections.defaultdict(collections.Counter)
for y, tier, n in rows: agg[y][tier] += n
wcsv("T05_断言时间年分布.csv", ["年", "总数", "严格层", "上下文层", "未决层"],
     [[y, sum(c.values()), c.get('strict_semantic', 0), c.get('contextual', 0), c.get('unresolved', 0)] for y, c in sorted(agg.items())])

# ---------- T06/T07/T08 证据门 ----------
gv = collections.Counter(r[0] for r in cur.execute("SELECT decision FROM gate_verdict_details"))
wcsv("T07_证据门五档支持.csv", ["语义支持等级", "断言数"],
     [["完全支持(FULLY_SUPPORTED)", gv['FULLY_SUPPORTED']],
      ["部分支持(PARTIALLY_SUPPORTED)", gv['PARTIALLY_SUPPORTED']],
      ["证据不足(INSUFFICIENT)", gv['INSUFFICIENT']],
      ["无支持(UNSUPPORTED)", gv['UNSUPPORTED']],
      ["相矛盾(CONTRADICTED)", gv['CONTRADICTED']]])
rows = cur.execute("SELECT final_tier, gate_method, COUNT(*) FROM evidence_gate_tier GROUP BY 1,2").fetchall()
wcsv("T08_证据门分层方法.csv", ["最终层", "判定方法", "断言数"], rows)
# 五档 × 最终层 交叉（join）
rows = cur.execute("""
SELECT g.final_tier, v.decision, COUNT(*) FROM evidence_gate_tier g
JOIN gate_verdict_details v ON g.fact_id = v.fact_id GROUP BY 1,2
""").fetchall()
wcsv("T08b_五档与最终层交叉.csv", ["最终层", "语义支持等级", "断言数"], rows)

# ---------- T09/T10 级联准入总漏斗与归因（AUTHORITATIVE_RESULTS 定版） ----------
funnel = [
    ["全库断言入口", 424150], ["严格候选(进入证据门)", 112158], ["门外上下文(前置)", 268047], ["门外未决(前置)", 43945],
    ["证据门可定位", 110052], ["无可定位证据(recovery_D)", 2106],
    ["证据门STRICT", 31067], ["证据门CONTEXTUAL", 31282], ["证据门UNRESOLVED", 49809],
    ["全库STRICT", 31067], ["全库CONTEXTUAL", 299329], ["全库UNRESOLVED", 93754],
]
wcsv("T09_级联准入漏斗.csv", ["阶段", "断言数"], funnel)
attrib = [
    ["UNRESOLVED_前置_作用域冲突model_review", 27492], ["UNRESOLVED_前置_端点实体类型未决", 16393],
    ["UNRESOLVED_前置_人工遗留manual_review", 60], ["UNRESOLVED_核验_证据不支持", 47576],
    ["UNRESOLVED_核验_证据相矛盾", 127], ["UNRESOLVED_核验_无可定位证据", 2106],
    ["CONTEXTUAL_前置_谓词未完成规范化", 264635], ["CONTEXTUAL_前置_关系域约束违反", 3412],
    ["CONTEXTUAL_核验降级_PARTIAL非strict谓词", 27704], ["CONTEXTUAL_核验降级_证据不足INSUFFICIENT", 3578],
    ["STRICT_证据完全或安全部分支持", 31067],
]
wcsv("T10_全库三层归因.csv", ["归因路径", "断言数"], attrib)

# ---------- T11 来源成员数分布 ----------
rows = cur.execute("SELECT source_member_count, COUNT(*) FROM research_assertions GROUP BY 1 ORDER BY 1").fetchall()
wcsv("T11_来源成员数分布.csv", ["来源成员数", "断言数"], rows)

# ---------- T12/T13 实体度分布与高频实体 ----------
deg = collections.Counter()
name = {}; typ = {}
for eid, nm, tp in cur.execute("SELECT entity_id, canonical_name, entity_type FROM research_entities"):
    name[eid] = nm; typ[eid] = tp
for sid, oid in cur.execute("SELECT subject_id, object_id FROM research_assertions"):
    if sid: deg[sid] += 1
    if oid: deg[oid] += 1
hist = collections.Counter()
for d in deg.values():
    if d == 1: hist['1'] += 1
    elif d <= 2: hist['2'] += 1
    elif d <= 5: hist['3-5'] += 1
    elif d <= 10: hist['6-10'] += 1
    elif d <= 20: hist['11-20'] += 1
    elif d <= 50: hist['21-50'] += 1
    elif d <= 100: hist['51-100'] += 1
    else: hist['>100'] += 1
order = ['1', '2', '3-5', '6-10', '11-20', '21-50', '51-100', '>100']
wcsv("T12_实体度分布.csv", ["度区间", "实体数"], [[k, hist[k]] for k in order])
top = sorted(deg.items(), key=lambda kv: -kv[1])[:150]
wcsv("T13_高频实体Top150.csv", ["实体名", "类型", "度"],
     [[name.get(e, ''), typ.get(e, ''), d] for e, d in top])

# ---------- T14 实体类型×谓词矩阵（Top谓词） ----------
rows = cur.execute("""
SELECT subject_type, predicate, COUNT(*) FROM research_assertions
GROUP BY 1,2 HAVING COUNT(*) >= 200 ORDER BY 3 DESC
""").fetchall()
wcsv("T14_主语类型×谓词矩阵.csv", ["主语类型", "谓词", "断言数"], rows)
rows = cur.execute("""
SELECT object_type, predicate, COUNT(*) FROM research_assertions
GROUP BY 1,2 HAVING COUNT(*) >= 200 ORDER BY 3 DESC
""").fetchall()
wcsv("T14b_宾语类型×谓词矩阵.csv", ["宾语类型", "谓词", "断言数"], rows)

# ---------- T15 省域×实体类型矩阵 ----------
rows = cur.execute("""
SELECT province, subject_type, COUNT(*) FROM research_assertions
WHERE province IS NOT NULL AND province != '' GROUP BY 1,2
""").fetchall()
wcsv("T15_省域×主语类型矩阵.csv", ["省份", "主语类型", "断言数"], rows)

# ---------- T16 时空格（7,067） ----------
rows = cur.execute("""
SELECT stage_label_zh, stage_order, province_name, observation_tier,
       time_evidence_count, place_evidence_count, context_evidence_count
FROM research_event_spatiotemporal_cells
""").fetchall()
wcsv("T16_历史阶段×省域时空格.csv",
     ["历史阶段", "阶段序", "省份", "观测层", "时间证据数", "地点证据数", "语境证据数"], rows)

# ---------- T17 事件框架 ----------
rows = cur.execute("""
SELECT event_name, strict_assertion_count, all_assertion_count, controlled_role_count,
       region_count, observed_time_start, observed_time_end, frame_status
FROM research_event_frames
""").fetchall()
wcsv("T17_事件框架全表.csv", ["事件名", "严格断言数", "全部断言数", "受控角色数", "省域数", "观测起", "观测止", "状态"], rows)

# ---------- T18 地点版本 ----------
rows = cur.execute("SELECT historical_name, valid_from, valid_to, admin_level, derived_pattern, status FROM research_place_versions").fetchall()
wcsv("T18_地点版本演化.csv", ["历史名", "起", "止", "行政层级", "派生模式", "状态"], rows)
rows = cur.execute("SELECT source_event_name, relation_code, target_event_name, relation_strength, causality_status FROM research_event_relations").fetchall()
wcsv("T19_事件关系.csv", ["源事件", "关系", "目标事件", "强度", "因果状态"], rows)

# ---------- T20 作用域调整 ----------
rows = cur.execute("""
SELECT source_time_role, final_time_role, source_space_role, final_space_role, adjustment_reason, COUNT(*)
FROM research_scope_adjustments GROUP BY 1,2,3,4,5 ORDER BY 6 DESC
""").fetchall()
wcsv("T20_作用域调整汇总.csv", ["原时间角色", "新时间角色", "原空间角色", "新空间角色", "原因", "条数"], rows)

# ---------- T21 关系契约 ----------
rows = cur.execute("SELECT predicate, label_zh, source_types_json, target_types_json FROM research_relation_contract").fetchall()
wcsv("T21_关系契约88谓词.csv", ["谓词", "中文标签", "定义域类型", "值域类型"], rows)

# ---------- T22 文化状态 ----------
rows = cur.execute("""
SELECT stage_label_zh, stage_order, province_name, culture_form_code, observation_tier, COUNT(*)
FROM research_culture_states GROUP BY 1,2,3,4,5
""").fetchall()
wcsv("T22_文化状态统计.csv", ["历史阶段", "阶段序", "省份", "文化形态", "观测层", "状态数"], rows)

# ---------- T23-T27 构建管线库（DB2） ----------
cols2 = [c[1] for c in cur2.execute("PRAGMA table_info(v2_identity_resolutions)")]
rows = cur2.execute("SELECT * FROM v2_identity_resolutions").fetchall()
wcsv("T23_身份决议794.csv", cols2, rows)
rows = cur2.execute("SELECT member_count, COUNT(*) FROM v2_name_clusters GROUP BY 1 ORDER BY 1").fetchall()
wcsv("T24_名称聚类规模.csv", ["成员数", "聚类数"], rows)
rows = cur2.execute("SELECT unit_kind, dimension, label_function, COUNT(*) FROM v2_label_votes GROUP BY 1,2,3 ORDER BY 4 DESC").fetchall()
wcsv("T25_标签投票来源.csv", ["单元类型", "维度", "标注函数", "票数"], rows)
rows = cur2.execute("SELECT model, validator_pass, COUNT(*) FROM v2_model_decisions GROUP BY 1,2").fetchall()
wcsv("T26_模型决策.csv", ["模型", "校验通过", "决策数"], rows)
try:
    rows = cur2.execute("SELECT conflict_type, COUNT(*) FROM v2_semantic_conflicts GROUP BY 1 ORDER BY 2 DESC").fetchall()
except Exception:
    cols = [c[1] for c in cur2.execute("PRAGMA table_info(v2_semantic_conflicts)")]
    rows = []
    print("  [i] v2_semantic_conflicts cols:", cols)
wcsv("T27_语义冲突类型.csv", ["冲突类型", "数量"], rows)

# ---------- T28 时序关系类型（5.6M 分组） ----------
try:
    rows = cur.execute("SELECT relation_code, COUNT(*) FROM assertion_temporal_relations GROUP BY 1 ORDER BY 2 DESC").fetchall()
except Exception:
    rows = []
wcsv("T28_时序关系类型.csv", ["时序关系类型", "数量"], rows)

# ---------- T29 身份碰撞 ----------
try:
    rows = cur.execute("SELECT resolution, COUNT(*), ROUND(AVG(member_count),2) FROM research_assertion_identity_collisions GROUP BY 1").fetchall()
except Exception:
    rows = []
wcsv("T29_身份碰撞处置.csv", ["处置方式", "组数", "平均成员数"], rows)

# ---------- T31 主语类型×历史阶段 ----------
try:
    rows = cur.execute("""
    SELECT a.subject_type, s.stage_label_zh, COUNT(*) FROM research_assertions a
    JOIN research_assertion_stage_memberships m ON a.fact_id = m.fact_id
    JOIN research_historical_stages s ON m.stage_code = s.stage_code
    GROUP BY 1,2
    """).fetchall()
except Exception as ex:
    rows = []
    print("  [i] stage membership join failed:", ex)
wcsv("T31_主语类型×历史阶段.csv", ["主语类型", "历史阶段", "断言数"], rows)

# ---------- T32 人物活跃年份Top ----------
rows = cur.execute("""
SELECT a.subject_name, CAST(strftime('%Y', a.time_start) AS INT) y, COUNT(*) n
FROM research_assertions a WHERE a.subject_type='Person' AND a.time_start IS NOT NULL
  AND a.time_start >= '1900-01-01' AND a.time_start <= '1950-12-31'
GROUP BY 1,2 HAVING n >= 3 ORDER BY n DESC LIMIT 400
""").fetchall()
wcsv("T32_人物活跃年份.csv", ["人物", "年", "断言数"], rows)

# ---------- T34 严格层网络边表 ----------
rows = cur.execute("""
SELECT a.subject_id, a.subject_name, a.subject_type, a.predicate,
       a.object_id, a.object_name, a.object_type, a.province, a.time_start
FROM research_assertions a WHERE a.research_tier='strict_semantic'
""").fetchall()
wcsv("T34_严格层边表31067.csv",
     ["主体ID", "主体名", "主体类型", "谓词", "客体ID", "客体名", "客体类型", "省份", "时间"], rows)

# ---------- T35 案例事件（论文点名事件，含模糊匹配最大事件） ----------
cases = [('南昌起义', ['%南昌起义%', '%南昌占领%']), ('八七会议', ['%八七会议%']),
         ('秋收起义', ['%秋收暴动%', '%秋收起义%']), ('遵义会议', ['%遵义会议%'])]
for ev, pats in cases:
    eids = []
    for pat in pats:
        eids += [x[0] for x in cur.execute(
            "SELECT event_id FROM research_event_frames WHERE event_name LIKE ? ORDER BY strict_assertion_count DESC LIMIT 3",
            (pat,)).fetchall()]
    rows = []
    for eid in eids[:3]:
        for row in cur.execute("""
        SELECT er.event_id, ef.event_name, er.counterpart_name, er.counterpart_type, er.predicate, er.role_code, er.role_category
        FROM research_event_roles er JOIN research_event_frames ef ON er.event_id = ef.event_id
        WHERE er.event_id = ?""", (eid,)):
            rows.append(row)
    wcsv(f"T35_案例_{ev}.csv", ["事件ID", "事件名", "关联对象", "对象类型", "谓词", "角色码", "角色类别"], rows)

# 案例证据引文（gate_verdict_details evidence_quote）——选取四事件相关 STRICT 断言
q = cur.execute("SELECT COUNT(*) FROM gate_verdict_details WHERE evidence_quote IS NOT NULL AND evidence_quote != ''").fetchone()
print("  [i] evidence quotes:", q)

# ---------- T36 严格层大事件Top30（按严格断言数） ----------
rows = cur.execute("""
SELECT event_name, strict_assertion_count, controlled_role_count, region_count, observed_time_start
FROM research_event_frames ORDER BY strict_assertion_count DESC LIMIT 30
""").fetchall()
wcsv("T36_大事件Top30.csv", ["事件名", "严格断言数", "受控角色数", "省域数", "观测起"], rows)

# ---------- T37 断言风险与置信度分布 ----------
rows = cur.execute("SELECT risk_tier, COUNT(*) FROM research_assertions GROUP BY 1").fetchall()
wcsv("T37_风险层分布.csv", ["风险层", "断言数"], rows)
rows = cur.execute("""
SELECT ROUND(confidence, 2), COUNT(*) FROM research_assertions
WHERE confidence IS NOT NULL GROUP BY 1 ORDER BY 1
""").fetchall()
wcsv("T37b_置信度分布.csv", ["置信度", "断言数"], rows)

# ---------- T38 洲/流域分段 ----------
rows = cur.execute("SELECT basin_section_id, COUNT(*) FROM research_assertion_basins GROUP BY 1").fetchall()
wcsv("T38_流域分段统计.csv", ["流域分段", "断言数"], rows)
rows = cur.execute("SELECT region_id, province_name, basin_segment, province_order FROM research_study_regions ORDER BY province_order").fetchall()
wcsv("T39_十三省域定义.csv", ["区域ID", "省份", "流域段", "顺序"], rows)

con.close(); con2.close()

# ---------- 实验产物复制与解析 ----------
def copyf(src, name):
    p = os.path.join(V31, src)
    if os.path.exists(p):
        shutil.copy(p, os.path.join(OUT, name)); print(f"  [OK] {name}")
    else:
        print(f"  [MISS] {src}")

copyf(r"experiments\02_selective_semantic\budget_v2\CURVE_LOCAL.csv", "E01_预算曲线.csv")
copyf(r"experiments\02_selective_semantic\budget_v2\ROUTING_COMPARISON.csv", "E02_路由对比.csv")
copyf(r"experiments\02_selective_semantic\budget_v2\ROUTING_BOOTSTRAP.json", "E03_路由bootstrap.json")
copyf(r"experiments\10_full_universe_admission_closure\OUTSIDE_GATE_AUDIT_RESULTS.json", "E08_门外审计.json")
copyf(r"release_final\experiments\quality_audit\AUDIT_RESULTS.json", "E09_门内审计.json")
copyf(r"experiments\10_full_universe_admission_closure\FULL_UNIVERSE_ADMISSION_SUMMARY.json", "E10_全库准入.json")
copyf(r"release_final\manifests\FINAL_NUMBERS.csv", "E11_权威数字31项.csv")
copyf(r"experiments\07_provenance_semantic_gate\EVIDENCE_GATE_SUMMARY.json", "E12_证据门摘要.json")
copyf(r"experiments\07_provenance_semantic_gate\FINAL_TIERING_POLICY.json", "E13_分层政策.json")
copyf(r"experiments\05_scope_repair\v2_\CLOSURE3_SUMMARY.json", "E06_作用域闭包.json")
copyf(r"experiments\09_cross_source_robustness\CROSS_SOURCE_SUMMARY.json", "E07_跨来源.json")

# 论文表格（来自 manuscript docx，人工核对自稿件）
paper_tables = {
 "E20_论文表1_资料列表.csv": [
   ["资料系列", "收录规模", "册数", "特征"],
   ["中共党史人物传", "51卷", 51, "全国性人物资料"],
   ["中华人民共和国史长编", "9卷", 9, "长时段综合性国史资料"],
   ["阿坝州党史研究资料", "12期", 12, "红军长征区域专题"],
   ["毕节地区党史资料丛书", "22册", 22, "类型丰富地方资料"],
   ["蚌埠党史资料", "9辑", 9, "地方连续性党史资料"],
   ["高淳史志资料", "9辑", 9, "地方史志型资料"],
   ["曲靖党史资料", "5辑", 5, "区域革命斗争资料"],
   ["执政条件下党的建设", "10册", 10, "专题性多卷资料"],
 ],
 "E21_论文表2A_选择性语义判定.csv": [
   ["方法", "接受覆盖率", "接受样本一致率", "选择性风险", "安全覆盖率", "MacroF1"],
   ["规则方法", 0.9934, 0.8742, 0.1258, 0.8618, 0.8967],
   ["本地分类器", 1.0000, 0.6250, 0.3750, 0.6184, 0.4333],
   ["Qwen-3.5-122B-A10B", 0.9934, 0.8808, 0.1192, 0.8553, 0.9203],
   ["规则—Qwen一致性选择", 0.7632, 0.9914, 0.0086, 0.7500, 0.9726],
 ],
 "E22_论文表3_组件消融.csv": [
   ["变体", "覆盖率", "接受样本一致率", "选择性风险", "错误暴露率", "安全覆盖率"],
   ["完整选择性分类器", 0.3547, 0.9444, 0.0556, 0.0197, 0.3350],
   ["去类别门禁", 0.3596, 0.9452, 0.0548, 0.0197, 0.3399],
   ["去独立信号一致", 0.6502, 0.9167, 0.0833, 0.0542, 0.5961],
   ["去弃权", 1.0000, 0.8818, 0.1182, 0.1182, 0.8818],
 ],
 "E23_论文表4_结构消融.csv": [
   ["消融设置", "影响对象", "变化量", "新增违例"],
   ["去风险路由", "发布状态", 43945, 0], ["去身份投影", "实体端点", 24005, 0],
   ["去关系契约", "严格语义层", 0, 3412], ["去时空归属约束", "强时空单元", 208, 156],
   ["去来源门禁", "知识陈述", 0, 0],
 ],
 "E24_论文表5_效率实验.csv": [
   ["规模", "陈述数", "热启动中位s", "含加载中位s", "热启动吞吐", "峰值RSS_MB"],
   ["10%", 42415, 16.675, 17.192, 2543.682, 430.027],
   ["25%", 106037, 21.433, 21.927, 4947.455, 540.115],
   ["50%", 212075, 32.530, 33.033, 6519.291, 845.173],
   ["75%", 318112, 41.195, 41.911, 7722.055, 1147.044],
   ["100%", 424150, 45.900, 46.749, 9240.761, 1428.836],
 ],
}
for name, tbl in paper_tables.items():
    with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(tbl)
    print(f"  [OK] {name}")

# 冻结测试三split（来自 frozen_test/SUMMARY.json 的 3.2 表）
wcsv("E04_冻结测试三split.csv", ["指标", "DEV", "VAL", "TEST"], [
    ["有参考样本数", 207, 54, 48],
    ["接受/升级/弃权", "160/76/18", "41/20/5", "41/19/2"],
    ["覆盖率", 0.9372, 0.9259, 0.9792],
    ["选择准确率", 0.5103, 0.4600, 0.6170],
    ["选择性风险", 0.4897, 0.5400, 0.3830],
    ["广义风险", 0.4589, 0.5000, 0.3750],
    ["升级段一致率", 0.7778, 0.7333, 0.8000],
    ["接受段一致率", 0.3817, 0.3429, 0.5313],
    ["错→对(升级)", 28, 4, 9], ["对→错(升级)", 1, 0, 1],
])
# 消融12变体（FINAL_TEST_REPORT §2）
wcsv("E05_消融12变体TEST.csv", ["变体", "覆盖率", "选择准确率", "选择性风险"], [
    ["S0生产保真(冻结)", 0.0645, 0.2500, 0.7500], ["S0规则优先对照", 0.6452, 0.5000, 0.5000],
    ["S1去类别门禁", 0.0323, 0.0000, 1.0000], ["S2去独立信号", 0.4839, 0.4000, 0.6000],
    ["S3去反证守卫", 0.0645, 0.2500, 0.7500], ["S4去显式弃权", 0.0645, 0.2500, 0.7500],
    ["S5去结构准入", 0.0645, 0.2500, 0.7500], ["S6仅规则", 0.2742, 0.5294, 0.4706],
    ["S7仅分类器", 0.9516, 0.3220, 0.6780], ["S8仅盲LLM", 1.0000, 0.7097, 0.2903],
    ["S9规则+分类器", 1.0000, 0.4355, 0.5645], ["S10规则+盲LLM", 1.0000, 0.6452, 0.3548],
])
# 门外审计核心（OUTSIDE_GATE_AUDIT_RESULTS.json 定版数字）
wcsv("E14_门外审计核心指标.csv", ["指标", "点估计", "CI下界", "CI上界", "分子", "分母"], [
    ["五档完全一致率", 0.8126, 0.8015, 0.8232, 4028, 4957],
    ["Cohen κ", 0.5136, None, None, None, None],
    ["强共识STRICT机会率(样本)", 0.0063, 0.0044, 0.0089, 31, 4957],
    ["加权总体STRICT机会率", 0.0066, 0.0040, 0.0097, None, None],
    ["推荐状态一致率", 0.8899, 0.8808, 0.8983, 4411, 4957],
    ["严格资格一致率", 0.9352, 0.9280, 0.9418, 4636, 4957],
    ["裁判A机会率", 0.0583, 0.0521, 0.0652, 289, 4957],
    ["裁判B机会率", 0.0115, 0.0089, 0.0149, 57, 4957],
    ["门外三层精确一致", 0.4303, 0.4166, 0.4441, 2133, 4957],
])
# 门内审计核心
wcsv("E15_门内审计核心指标.csv", ["指标", "值", "CI下界", "CI上界"], [
    ["双裁判五档完全一致率", 0.3598, None, None],
    ["Cohen κ", 0.1838, None, None],
    ["STRICT强共识支持精度", 0.9928, 0.9852, 0.9965],
    ["强共识误报率", 0.0041, 0.0016, 0.0105],
    ["完全支持精度(仅FULLY)", 0.8066, 0.7806, 0.8302],
    ["弱共识率", 0.2593, None, None], ["无共识率", 0.3808, None, None],
])
# 三概念分离
wcsv("E16_三概念分离ABC.csv", ["概念", "分子", "分母", "比率"], [
    ["A谱系完整率", 50161, 112158, 0.4472],
    ["B证据定位率", 110052, 112158, 0.9812],
    ["C语义支持率", 31067, 110052, 0.2823],
])
# 六层定位桶
wcsv("T06_六层定位桶.csv", ["定位桶", "规模", "已测STRICT"], [
    ["aligned", 44025, 18597], ["mismatch_with_evidence", 6136, 71],
    ["recovery_A", 2841, 1444], ["recovery_B", 16705, 7182],
    ["recovery_C", 40345, 3773], ["recovery_D", 2106, 0],
])
print("\n全部中间表提取完成。")
