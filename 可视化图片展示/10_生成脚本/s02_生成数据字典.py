# -*- coding: utf-8 -*-
"""s02_生成数据字典.py — 生成 02_可视化数据字典.xlsx/.csv
覆盖：最终库 53 表关键字段 + 全部中间表 + 实验产物文件。"""
import csv, os, glob, json
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

OUT = r"D:\REDCULTUREDATA\可视化输出"
MID = os.path.join(OUT, "11_数据中间表")

# --- 1. 核心库表字典（人工整理：字段、含义、单位、可视化用途）---
core = [
 # 表, 字段, 类型, 含义, 单位/取值, 缺失情况, 样本数, 可直接可视化, 派生指标, 关联字段, 对应章节, 质量备注
 ("research_entities","entity_id","TEXT","规范实体唯一标识","IENT-…","无","152,979","是(连接键)","-","research_assertions.subject_id/object_id","4/3.3","权威库"),
 ("research_entities","canonical_name","TEXT","规范实体名","中文名","无","152,979","是","高频榜/网络标签","-","4/3/6/7/17","-"),
 ("research_entities","entity_type","TEXT","实体类型(16类)","Person/Event/Place/Organization/Concept/…","无","152,979","是","类型分布/类型矩阵","-","6/7","与论文§4.3一致"),
 ("research_entities","type_validation_status","TEXT","类型验证状态","validated/pending","待定4762","152,979","是","类型未决占比","-","7","论文:148217验证/4762未决"),
 ("research_entities","aliases_json","TEXT","别名JSON","[]","多数空","152,979","是(解析后)","别名数量分布","-","7","-"),
 ("research_assertions","fact_id","TEXT","断言唯一标识","IFACT-…","无","424,150","是(连接键)","-","evidence_gate_tier/gate_verdict_details/provenance","4","权威库"),
 ("research_assertions","subject_id/subject_name/subject_type","TEXT","主体三元组","-","无","424,150","是","网络边/类型矩阵","-","6/7/16","-"),
 ("research_assertions","object_id/object_name/object_type","TEXT","客体三元组","-","无","424,150","是","网络边/类型矩阵","-","6/7/16","-"),
 ("research_assertions","predicate","TEXT","谓词(规范+raw:前缀)","raw:关联等","无","424,150","是","谓词长尾/规范化映射","provenance.source_predicate","8","raw:前缀=未归一"),
 ("research_assertions","time_start/time_end","TEXT","时间起止","YYYY-MM-DD","大量NULL","424,150","是(过滤)","年分布/时间轴","-","9","1853–2024"),
 ("research_assertions","time_role/space_role","TEXT","时间/空间语义角色","event_time/…","-","424,150","是","角色分布","scope_adjustments","9","-"),
 ("research_assertions","province/city/county","TEXT","省市县","中文","346,874空","424,150","是(注意覆盖)","省域分布","assertion_regions","5/9","非空77,276条"),
 ("research_assertions","research_tier","TEXT","最终知识状态","strict_semantic/contextual/unresolved","无","424,150","是","三层结构","-","12","31067/299329/93754"),
 ("research_assertions","confidence/risk_tier","REAL/TEXT","置信度/风险层","0-1/高中低","-","424,150","是","分布图","-","10","-"),
 ("research_assertions","source_member_count","INT","来源成员数","1-4+","无","424,150","是","来源密度分布","-","13","383025/40929/196"),
 ("evidence_gate_tier","final_tier","TEXT","证据门最终层","STRICT/CONTEXTUAL/UNRESOLVED","无","112,158","是","准入漏斗","-","12","31067/31282/49809"),
 ("evidence_gate_tier","gate_method","TEXT","判定方法","rule/llm","无","112,158","是","方法占比","-","12/13","rule=2106(recovery_D)"),
 ("gate_verdict_details","decision","TEXT","五档语义支持","FULLY_SUPPORTED/…","无","105,081","是","五档结构","-","13","22099/34922/3057/44976/27"),
 ("gate_verdict_details","confidence/evidence_quote/explanation/latency_s","REAL/TEXT","判定置信度/证据引文/理由/时延","-","部分空","105,081","是","案例图/时延分布","-","17","引文56,485条"),
 ("research_assertion_provenance","evidence_ids_json/native_record_ids_json","TEXT","证据/原生记录指针","JSON数组","127,080非空","466,312","是(解析后)","A谱系完整率","-","13","A=44.72%"),
 ("research_event_frames","event_name/strict_assertion_count/…","TEXT/INT","事件框架及统计","-","无","28,065","是","事件规模/时间分布","-","9/16/17","-"),
 ("research_event_spatiotemporal_cells","stage×province×evidence_counts","-","事件时空格","8阶段×13省","无","7,067","是","时空热力图","-","9","含观测层"),
 ("research_place_versions","historical_name/valid_from/valid_to","TEXT","地点历史版本","-","无","72","是","版本演化图","-","9","-"),
 ("research_relation_contract","predicate/domain/range","TEXT","关系契约","88谓词","无","88","是","契约矩阵","-","8","-"),
 ("research_scope_adjustments","source/final role+owner","TEXT","时空作用域调整","-","无","208","是","调整流向图","-","11","-"),
 ("research_culture_states","stage/province/form/tier","-","文化状态","-","无","11,532","是","状态分布","-","9","-"),
 ("research_study_regions","province_name/basin_segment","TEXT","13省域定义","-","无","13","是","地图/省域","-","5","-"),
 ("research_historical_stages","stage_label_zh/time","TEXT","8历史阶段","-","无","8","是","阶段轴","-","9","-"),
 ("assertion_temporal_relations","relation_code","TEXT","时序关系类型","before/after/…","无","5,636,370","是(聚合)","时序类型分布","-","9","9类"),
 ("research_assertion_identity_collisions","resolution/member_count","TEXT/INT","身份碰撞处置","merged/kept","无","655","是","碰撞处置","-","7","654合并/1保留"),
 ("v2_identity_resolutions","(全表)","-","身份决议明细","-","无","794","是","投影决议","-","7","论文:794决议"),
 ("v2_name_clusters","member_count","INT","名称聚类规模","-","无","3,094","是","聚类规模分布","-","7","-"),
 ("v2_label_votes","unit/dimension/label_function","-","标签投票","-","无","841,097","是(聚合)","投票来源","-","7","-"),
 ("v2_semantic_conflicts","conflict_type/severity","-","语义冲突","-","无","74,636","是","冲突类型","-","7/11","-"),
]
# --- 2. 实验产物文件 ---
exp_files = [
 ("E01_预算曲线.csv","预算曲线(0-100%九档,pooled/dev/val)","一致率/翻转/风险","budget_v2/CURVE_LOCAL.csv","§10 选择性预测"),
 ("E02_路由对比.csv","R0-R7路由×预算×指标","一致率","budget_v2/ROUTING_COMPARISON.csv","§10"),
 ("E03_路由bootstrap.json","R6 vs R1-R5 18项配对bootstrap","Δ/CI/p","budget_v2/ROUTING_BOOTSTRAP.json","§10"),
 ("E04_冻结测试三split.csv","DEV/VAL/TEST同口径对比","10指标","frozen_test/SUMMARY.json","§10"),
 ("E05_消融12变体TEST.csv","S0-S10消融","覆盖率/风险","FINAL_TEST_REPORT.md §2","§10"),
 ("E06_作用域闭包.json","208→187→83→62→28分流与McNemar","-","CLOSURE3_SUMMARY.json","§11"),
 ("E07_跨来源.json","random/book/province三切分","acc/mF1/risk","CROSS_SOURCE_SUMMARY.json","§15"),
 ("E08_门外审计.json","门外5000双裁判","9组CI","OUTSIDE_GATE_AUDIT_RESULTS.json","§14"),
 ("E09_门内审计.json","门内4427双裁判","精度/κ","AUDIT_RESULTS.json","§14"),
 ("E10_全库准入.json","424,150台账与replay","-","FULL_UNIVERSE_ADMISSION_SUMMARY.json","§12"),
 ("E11_权威数字31项.csv","31项权威指标","-","FINAL_NUMBERS.csv","全局"),
 ("E12_证据门摘要.json","六层桶/方法/分层","-","EVIDENCE_GATE_SUMMARY.json","§12/13"),
 ("E20-E24_论文表*.csv","论文表1-5转录","-","manuscript docx","§5/10/15"),
 ("E14/E15/E16_审计核心*.csv","审计核心指标(定版口径)","-","各JSON人工核对","§14"),
 ("T06_六层定位桶.csv","六层定位桶规模","-","FINAL_EVIDENCE_REPORT.md §2","§12/13"),
 ("T09_级联准入漏斗.csv","级联准入12节点","-","AUTHORITATIVE_RESULTS.md","§12"),
 ("T10_全库三层归因.csv","三层来源分解11路径","-","AUTHORITATIVE_RESULTS.md §二之四","§12"),
]
# --- 3. 中间表清单（文件级）---
mids = []
for p in sorted(glob.glob(os.path.join(MID, "*.csv"))) + sorted(glob.glob(os.path.join(MID, "*.json"))):
    n = os.path.basename(p)
    size = os.path.getsize(p)
    with open(p, encoding='utf-8-sig', errors='replace') as f:
        first = f.readline().strip()[:200]
    nrows = sum(1 for _ in open(p, encoding='utf-8-sig', errors='replace')) - 1 if n.endswith('.csv') else '-'
    mids.append((n, f"{size:,}B", nrows, first[:120]))

# 写 xlsx
wb = Workbook()
ws = wb.active; ws.title = "核心数据字典"
ws.append(["数据表/文件","字段","类型","含义","单位/取值","缺失情况","样本数","可直接可视化","可计算派生指标","可关联字段","对应论文章节","质量备注"])
for r in core: ws.append(list(r))
ws2 = wb.create_sheet("实验产物")
ws2.append(["文件","内容","关键指标","原始来源","适用章节"])
for r in exp_files: ws2.append(list(r))
ws3 = wb.create_sheet("中间表清单")
ws3.append(["文件","大小","行数","字段预览"])
for r in mids: ws3.append(list(r))
for w, widths in [(ws,[24,34,10,30,22,12,12,14,20,26,14,20]),(ws2,[28,40,20,40,16]),(ws3,[36,12,10,80])]:
    for i, wd in enumerate(widths,1): w.column_dimensions[chr(64+i)].width = wd
    for c in w[1]:
        c.font = Font(bold=True, color="FFFFFF", name="宋体")
        c.fill = PatternFill("solid", fgColor="7A8B99")
hdr_fill = PatternFill("solid", fgColor="7A8B99")
wb.save(os.path.join(OUT, "00_项目盘点", "02_可视化数据字典.xlsx"))
# 同步CSV
with open(os.path.join(OUT, "00_项目盘点", "02_可视化数据字典.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["数据表/文件","字段","类型","含义","单位/取值","缺失情况","样本数","可直接可视化","派生指标","关联字段","章节","备注"])
    for r in core: w.writerow(list(r))
    w.writerow([]); w.writerow(["== 实验产物 =="]); 
    for r in exp_files: w.writerow(list(r))
    w.writerow([]); w.writerow(["== 中间表 =="]); 
    for r in mids: w.writerow(list(r))
print("数据字典完成：核心", len(core), "条 / 实验产物", len(exp_files), "条 / 中间表", len(mids), "个")
