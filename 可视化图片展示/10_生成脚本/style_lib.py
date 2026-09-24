# -*- coding: utf-8 -*-
"""
style_lib.py — 长江流域党史 STKG 论文可视化统一样式库
规范（总任务清单 §19–§21）：
  字体：中文宋体(SimSun)，英文/数字 Times New Roman；
  配色：莫兰迪低饱和学术色系；禁用 matplotlib 默认蓝橙绿；
  排版：轻轴线、轻网格、留白充足、标签不重叠；
  输出：PNG(300dpi) + SVG + PDF 三格式，中文文件名；
  登记：每图写入 12_图件清单/生成登记.jsonl。
"""
import os, json, math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
import matplotlib.font_manager as fm

ROOT = r"D:\REDCULTUREDATA\可视化输出"
CAND = os.path.join(ROOT, "01_候选图总库")
MID = os.path.join(ROOT, "11_数据中间表")
REG = os.path.join(ROOT, "12_图件清单", "生成登记.jsonl")
os.makedirs(os.path.dirname(REG), exist_ok=True)

# ---------------- 字体 ----------------
def _font_ok(name):
    try:
        fm.findfont(fm.FontProperties(family=name), fallback_to_default=False)
        return True
    except Exception:
        return False

_CJK = "SimSun" if _font_ok("SimSun") else "Songti SC"
_LAT = "Times New Roman" if _font_ok("Times New Roman") else "STIXGeneral"
rcParams["font.family"] = [_LAT, _CJK]   # 列表顺序 = 逐字回退顺序：拉丁用 TNR，中文回退宋体
rcParams["axes.unicode_minus"] = False
rcParams["mathtext.fontset"] = "stix"

# ---------------- 莫兰迪配色 ----------------
M = {  # 主分类色板（低饱和，避免默认蓝橙绿）
    "雾蓝": "#6E8CA0", "橄榄": "#8FA586", "陶砂": "#C2A08B", "灰紫": "#A08BA0",
    "青灰": "#7FA3A0", "燕麦": "#B7A98F", "暮蓝": "#8B93A8", "绛陶": "#A68080",
    "苔绿": "#93A87F", "烟粉": "#B5989A", "石板": "#7D8B99", "驼灰": "#AD9E8C",
}
SEQ10 = [M["雾蓝"], M["橄榄"], M["陶砂"], M["灰紫"], M["青灰"], M["暮蓝"], M["绛陶"], M["苔绿"], M["烟粉"], M["驼灰"]]
# 三层知识状态（全项目统一）
TIER_C = {"STRICT": "#3E5C6E", "CONTEXTUAL": "#93A692", "UNRESOLVED": "#C8AE8E"}
TIER_ZH = {"STRICT": "严格层", "CONTEXTUAL": "上下文层", "UNRESOLVED": "未决层"}
TIER_C_ZH = {"严格层": "#3E5C6E", "上下文层": "#93A692", "未决层": "#C8AE8E"}
# 五档语义支持
SUP_C = {"FULLY_SUPPORTED": "#3E5C6E", "PARTIALLY_SUPPORTED": "#93A692",
         "INSUFFICIENT": "#CDBBA3", "UNSUPPORTED": "#B08A7E", "CONTRADICTED": "#8B5A5A", "NO_EVIDENCE": "#8E8B86"}
SUP_ZH = {"FULLY_SUPPORTED": "完全支持", "PARTIALLY_SUPPORTED": "部分支持", "INSUFFICIENT": "证据不足",
          "UNSUPPORTED": "无支持", "CONTRADICTED": "相矛盾", "NO_EVIDENCE": "无证据"}
# 单色渐变（热力等）
BLUE_SEQ = ["#F4F6F7", "#DCE4E8", "#C2D0D8", "#A4BBC5", "#86A7B4", "#688FA0", "#4F7690", "#3E5C6E"]
GREEN_SEQ = ["#F5F6F1", "#E4E9DC", "#D0DAC4", "#B4C4A9", "#98AF8F", "#7E9A75", "#66855E", "#4E6B48"]
SAND_SEQ = ["#F8F5EF", "#EDE4D4", "#DFD0B8", "#CDB995", "#BBA37B", "#A68C65", "#8E7550", "#74603F"]

INK = "#2B2B2B"       # 正文墨色
FAINT = "#6B6B6B"     # 辅助文字
AXIS = "#B9B4AC"      # 轴线
GRID = "#E7E4DE"      # 网格
PAPER = "#FFFFFF"

rcParams.update({
    "figure.facecolor": PAPER, "axes.facecolor": PAPER, "savefig.facecolor": PAPER,
    "axes.edgecolor": AXIS, "axes.linewidth": 0.8, "axes.labelcolor": INK,
    "axes.titlesize": 13.5, "axes.titleweight": "bold", "axes.titlecolor": INK,
    "axes.labelsize": 11, "xtick.labelsize": 10, "ytick.labelsize": 10,
    "xtick.color": FAINT, "ytick.color": FAINT,
    "xtick.direction": "out", "ytick.direction": "out",
    "legend.frameon": False, "legend.fontsize": 10,
    "grid.color": GRID, "grid.linewidth": 0.6, "grid.alpha": 0.9,
    "lines.linewidth": 1.8, "lines.markersize": 5,
    "figure.dpi": 110, "savefig.dpi": 300,
    "svg.fonttype": "none", "pdf.fonttype": 42,
    "axes.prop_cycle": matplotlib.cycler(color=SEQ10),
    "hatch.linewidth": 0.5,
})

# ---------------- 通用术语翻译（全项目统一） ----------------
ETYPE_ZH = {"Person": "人物", "Event": "事件", "Place": "地点", "Organization": "组织",
            "Concept": "概念", "Artifact": "文物", "Institution": "机构", "Document": "文献",
            "AdministrativeRegion": "行政区划", "Spirit": "精神", "CreativeWork": "作品",
            "ValueFacet": "价值面向", "Position": "职位", "TimePeriod": "时期",
            "CulturalSite": "文化遗址", "SocialGroup": "社会群体"}
PRED_ZH = {"participated_in": "参与", "led": "领导", "occurred_at": "发生于", "active_at": "活动于",
           "member_of": "隶属", "organized": "组织", "influenced": "影响", "held_position_in": "任职于",
           "created": "创作", "supported": "支持", "opposed": "反对", "collaborated_with": "协作",
           "contacted": "联络", "died_at": "卒于", "captured": "被俘于", "dispatched": "派往",
           "fought_at": "战斗于", "guided": "指导", "worked_at": "工作于", "responsible_for": "负责",
           "located_at": "位于", "born_at": "生于", "关联": "关联", "发生于": "发生于"}
def pz(p):
    s = str(p)
    if s.startswith("raw:"):
        return "原始·" + PRED_ZH.get(s[4:], s[4:])
    return PRED_ZH.get(s, s)
def ez(t):
    return ETYPE_ZH.get(str(t), str(t))

def wrap_zh(s, n=10):
    """长中文标签换行"""
    s = str(s)
    if len(s) <= n: return s
    return "\n".join(s[i:i+n] for i in range(0, len(s), n))

def despine(ax, keep=("left", "bottom")):
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(side in keep)

def light_grid(ax, axis="y"):
    ax.grid(axis=axis, zorder=0)
    ax.set_axisbelow(True)

# ---------------- 保存与登记 ----------------
def save_fig(fig, fig_id, zh_name, category, script, data_sources, note="",
             outdirs=None, close=True, extra_png_dpi=300):
    """三格式保存 + 元数据登记。fig_id 如 'A01'；zh_name 全中文。"""
    fn = f"{fig_id}_{zh_name}"
    dirs = outdirs or [CAND]
    paths = {}
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        fig.savefig(os.path.join(d, fn + ".png"), dpi=extra_png_dpi, bbox_inches="tight", facecolor=PAPER)
        fig.savefig(os.path.join(d, fn + ".svg"), bbox_inches="tight", facecolor=PAPER)
        fig.savefig(os.path.join(d, fn + ".pdf"), bbox_inches="tight", facecolor=PAPER)
    rec = {"图号": fig_id, "图名": zh_name, "文件名": fn, "类别": category,
           "脚本": script, "数据源": data_sources if isinstance(data_sources, list) else [data_sources],
           "说明": note, "格式": ["png", "svg", "pdf"]}
    with open(REG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if close:
        plt.close(fig)
    print(f"[saved] {fn}")

def fmt_k(x):
    if x >= 10000: return f"{x/10000:.1f}万"
    if x >= 1000: return f"{x/1000:.1f}千"
    return f"{x:.0f}"

def new_fig(w=7.2, h=4.6, nrows=1, ncols=1, **kw):
    fig, ax = plt.subplots(nrows, ncols, figsize=(w, h), **kw)
    return fig, ax
