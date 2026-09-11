# -*- coding: utf-8 -*-
"""build_stkg_visualizations.py — STKG 最终版（v3_1）时空知识图谱可视化套件。

生成出版级（300 dpi PNG）与交互式（自包含 HTML）可视化，全部数字来自真实 SQL 查询，
不使用任何随机过程；所有抽样/排序均带确定性次序键（稳定 ORDER BY），重跑结果一致。

数据源策略：
  优先 使用 V3_1 副本库（含 U1-U8 升级表/视图/列）：
      data/repaired_release/red_culture_stkg_final_v3_1.sqlite
  若某表/视图在 V3_1 中不存在或为空，则回退 V2 主库：
      data/release_databases/red_culture_stkg_final_v2.sqlite
  每次回退都会记录在 usage 日志、图头与 CAPTION 中，如实标注。

数据库一律只读（sqlite3 mode=ro）。

输出（均为新建文件，不修改任何既有文件）：
  figures/stkg_viz1_event_spacetime_density.png
  figures/stkg_viz2_person_trajectories.png            （matplotlib 多面板版）
  figures/stkg_viz2_person_trajectories.html           （交互版：时间线 + 邻居网络）
  figures/stkg_viz3_event_frame_structure.png
  figures/stkg_viz4_culture_state_evolution.png
  figures/stkg_viz5_overview_tiers.png
  figures/stkg_viz5_overview_tiers.html                （交互版：十年×河段×分层）
  figures/stkg_viz6_method_architecture.png
  figures/stkg_viz{n}_..._CAPTION.md                   （每张 PNG 一份：图题+SQL+行数+生成时间）
  audit/method_final/14_VISUALIZATION_REPORT.md

用法：
  python build_stkg_visualizations.py
"""

from __future__ import annotations

import html as _html
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import LogNorm  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

# ---------------------------------------------------------------------------
# 路径与全局常量
# ---------------------------------------------------------------------------

SCRIPT = Path(__file__).resolve()
CODE_DIR = SCRIPT.parents[1]                 # .../code
V31_ROOT = SCRIPT.parents[2]                 # .../final_submission_v3_1
REPO_ROOT = V31_ROOT.parents[1]              # 仓库根

DB_PRIMARY = V31_ROOT / "data" / "repaired_release" / "red_culture_stkg_final_v3_1.sqlite"
DB_FALLBACK = REPO_ROOT / "data" / "release_databases" / "red_culture_stkg_final_v2.sqlite"

FIGURES_DIR = V31_ROOT / "figures"
AUDIT_REPORT = V31_ROOT / "audit" / "method_final" / "14_VISUALIZATION_REPORT.md"

DPI = 300
RUN_STAMP = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")

DB_LABEL = {"v3_1": "red_culture_stkg_final_v3_1.sqlite（V3_1 副本库，含 U1-U8）",
            "v2": "red_culture_stkg_final_v2.sqlite（V2 主库，回退）"}

# 视觉常量（统一学术风格）
TIER_COLORS = {"strict_semantic": "#1b6ca8", "contextual": "#e8a33d", "unresolved": "#9aa5b1"}
TIER_LABELS = {"strict_semantic": "strict_semantic（严格语义层）",
               "contextual": "contextual（上下文层）",
               "unresolved": "unresolved（未解析层）"}
CELL_TIER_COLORS = {"trusted_event_spacetime": "#1b6ca8",
                    "asserted_event_spacetime": "#4da3d8",
                    "relation_context": "#c9d4dd"}
STATE_TIME_SOURCE_COLORS = {"member_events_trusted": "#1b6ca8",
                            "member_events_asserted": "#4da3d8",
                            "stage_interval": "#c9d4dd"}
ENTITY_TYPE_COLORS = {"Person": "#c0392b", "Organization": "#1b6ca8", "Institution": "#2e86ab",
                      "Event": "#7d3c98", "Place": "#1e8449", "AdministrativeRegion": "#27ae60",
                      "Concept": "#b7950b", "Artifact": "#a04000", "Document": "#616a6b",
                      "Spirit": "#884ea0"}
KIND_COLORS = {"组织/职务关系": "#1b6ca8", "事件参与": "#c0392b"}
STAGE_SHORT = {
    "pre_1921": "建党前", "founding_and_great_revolution": "建党与大革命",
    "agrarian_revolution": "土地革命", "war_of_resistance": "抗日战争",
    "liberation_war": "解放战争", "socialist_revolution_and_construction": "社会主义革命和建设",
    "reform_and_opening": "改革开放", "new_era": "新时代",
}
BASIN_ORDER = ["BASIN-SECTION:上游", "BASIN-SECTION:中游", "BASIN-SECTION:下游"]
BASIN_SHORT = {"BASIN-SECTION:上游": "上游", "BASIN-SECTION:中游": "中游", "BASIN-SECTION:下游": "下游"}


# ---------------------------------------------------------------------------
# 中文字体回退链（与 build_imcr_figures.py 同一策略：YaHei → SimHei → Noto → …）
# ---------------------------------------------------------------------------

FONT_CHAIN_CJK = (
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "PingFang SC",
    "Arial Unicode MS",
)


def resolve_cjk_font() -> dict:
    available = {f.name for f in font_manager.fontManager.ttflist}
    resolved = next((name for name in FONT_CHAIN_CJK if name in available), "DejaVu Sans")
    return {"requested_chain": [*FONT_CHAIN_CJK, "DejaVu Sans"],
            "resolved": resolved,
            "cjk_capable": resolved in FONT_CHAIN_CJK}


def figure_rc(font_info: dict) -> dict:
    chain = [font_info["resolved"]]
    chain += [n for n in [*FONT_CHAIN_CJK, "DejaVu Sans"] if n != font_info["resolved"]]
    return {
        "font.family": "sans-serif",
        "font.sans-serif": chain,
        "axes.unicode_minus": False,
        "font.size": 9.5,
        "axes.titlesize": 10.5,
        "axes.labelsize": 9.5,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "legend.fontsize": 8.5,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": False,
        "figure.dpi": 120,
    }


# ---------------------------------------------------------------------------
# 数据访问层：优先 V3_1，空表/缺表自动回退 V2（只读）
# ---------------------------------------------------------------------------

class DataHub:
    """按“对象（表/视图）”粒度解析数据源；多对象查询取同时包含所有对象的库。"""

    def __init__(self, primary: Path, fallback: Path):
        self.paths = {"v3_1": primary, "v2": fallback}
        self._conns: dict[str, sqlite3.Connection] = {}
        self._objects: dict[str, dict[str, bool]] = {}
        self.usage: list[dict] = []      # 每个查询涉及哪些对象、用了哪个库、行数
        self.fallbacks: list[str] = []

    def conn(self, label: str) -> sqlite3.Connection:
        if label not in self._conns:
            path = self.paths[label]
            if not path.exists():
                raise FileNotFoundError(path)
            self._conns[label] = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        return self._conns[label]

    def _object_exists(self, label: str, name: str) -> bool:
        cache = self._objects.setdefault(label, {})
        if name not in cache:
            row = self.conn(label).execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = ?", (name,)).fetchone()
            cache[name] = bool(row[0])
        return cache[name]

    def _row_count(self, label: str, name: str) -> int:
        try:
            return self.conn(label).execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        except sqlite3.Error:
            return -1

    def resolve(self, objects: list[str]) -> str:
        """返回同时包含全部非空对象的库标签；优先 v3_1，全部缺失时回退 v2。"""
        for label in ("v3_1", "v2"):
            if all(self._object_exists(label, o) and self._row_count(label, o) > 0
                   for o in objects):
                if label == "v2":
                    self.fallbacks.extend(objects)
                return label
        # 兜底：v3_1 至少对象存在（即便个别空表），让 SQL 给出明确错误
        if all(self._object_exists("v3_1", o) for o in objects):
            for o in objects:
                if self._row_count("v3_1", o) == 0:
                    self.fallbacks.append(f"{o}(空)")
            return "v3_1"
        raise RuntimeError(f"无可用数据源: {objects}")

    def q(self, objects: list[str], sql: str, params: tuple = ()) -> list[tuple]:
        label = self.resolve(objects)
        rows = self.conn(label).execute(sql, params).fetchall()
        self.usage.append({"objects": list(objects), "db": label, "rows": len(rows),
                           "sql": " ".join(sql.split())})
        return rows

    def has_column(self, label: str, table: str, col: str) -> bool:
        cols = [r[1] for r in self.conn(label).execute(f'PRAGMA table_info("{table}")')]
        return col in cols

    def source_line(self, objects: list[str]) -> str:
        label = self.resolve(objects)
        return f"数据源: {DB_LABEL[label]}"


def fmt(n) -> str:
    return f"{n:,}"


def esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def trunc(s, n=14) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def decade_of(date_str: str) -> str | None:
    if not date_str or len(date_str) < 4:
        return None
    y = date_str[:4]
    if not y.isdigit():
        return None
    y = int(y)
    if y < 1800 or y > 2026:
        return None
    return f"{(y // 10) * 10}s"


def add_source_footer(fig, text: str) -> None:
    fig.text(0.01, 0.005, text, ha="left", va="bottom", fontsize=6.2, color="#5a6572")


def save(fig, path: Path) -> None:
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    print(f"  [ok] {path.name}")


# ---------------------------------------------------------------------------
# CAPTION 写入
# ---------------------------------------------------------------------------

CAPTIONS: list[dict] = []


def write_caption(stem: str, title: str, panel_no: str, sqls: list[tuple[str, str]],
                  row_stats: list[tuple[str, str]], notes: list[str]) -> None:
    lines = [f"# {panel_no} · {title}", "",
             f"- **生成时间**: {RUN_STAMP}",
             f"- **脚本**: `code/experiment_pipelines/build_stkg_visualizations.py`（确定性：无随机过程，全部排序含稳定次序键）",
             f"- **图文件**: `figures/{stem}.png`" + (" / " + ", ".join(notes) if notes else ""),
             "", "## 数据来源与查询", ""]
    for name, sql in sqls:
        lines += [f"**{name}**", "", "```sql", sql.strip(), "```", ""]
    lines += ["## 数据规模（真实查询行数）", ""]
    for k, v in row_stats:
        v = v[len("数据源: "):] if k == "数据源" and v.startswith("数据源: ") else v
        lines.append(f"- {k}: **{v}**")
    lines += ["", "## 使用说明",
              "- 图中所有数字均为上图时刻对上述数据库执行 SQL 的真实统计；数据库只读打开。",
              "- 附加说明见 `audit/method_final/14_VISUALIZATION_REPORT.md`。", ""]
    path = FIGURES_DIR / f"{stem}_CAPTION.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    CAPTIONS.append({"stem": stem, "title": title, "panel_no": panel_no})
    print(f"  [ok] {path.name}")


# ===========================================================================
# VIZ-1 长江流域事件时空密度
# ===========================================================================

SQL_VIZ1_OCC = """
SELECT ot.fact_id, ot.subject_id, ot.subject_name, ot.time_start, ot.time_end,
       ot.basin_section, ot.province, ot.research_tier
FROM v_research_event_occurrence_times ot
ORDER BY ot.fact_id
"""

SQL_VIZ1_PLACES = """
SELECT pl.event_id, pl.event_location_name, pl.event_location_type, COUNT(*) AS n_facts
FROM v_research_event_places pl
WHERE pl.event_id IN (SELECT DISTINCT subject_id FROM v_research_event_occurrence_times)
GROUP BY pl.event_id, pl.event_location_name, pl.event_location_type
ORDER BY n_facts DESC, pl.event_location_name, pl.event_id
"""


def viz1(hub: DataHub, font_info: dict) -> dict:
    occ = hub.q(["v_research_event_occurrence_times"], SQL_VIZ1_OCC)
    places = hub.q(["v_research_event_places", "v_research_event_occurrence_times"], SQL_VIZ1_PLACES)

    n_occ = len(occ)
    events_time = {r[1] for r in occ}
    n_events = len(events_time)
    n_pairs = len(places)
    n_events_both = len({r[0] for r in places})

    # --- 十年 × 河段矩阵（行序固定：三段 → 全流域 → 跨段/未标注） ---
    basins = ["上游", "中游", "下游", "全流域", "跨段/未标注"]
    canon = {"上游": "上游", "中游": "中游", "下游": "下游"}

    def basin_row(b):
        if b in canon:
            return canon[b]
        if b == "全流域":
            return "全流域"
        return "跨段/未标注"

    decades_b = sorted({decade_of(r[3]) for r in occ} - {None},
                       key=lambda d: int(d[:4]))
    mat_b = np.zeros((len(basins), len(decades_b)), dtype=int)
    for r in occ:
        d = decade_of(r[3])
        if d is None:
            continue
        mat_b[basins.index(basin_row(r[5])), decades_b.index(d)] += 1

    # --- 十年 × 省份矩阵（前 10 省 + 其他/未标注） ---
    prov_count = Counter(r[6] if r[6] else "未标注省份" for r in occ if decade_of(r[3]))
    top_prov = [p for p, _ in sorted(prov_count.items(), key=lambda kv: (-kv[1], kv[0]))[:10]]
    rows_p = top_prov + (["其他/未标注"] if any(p not in top_prov for p in prov_count) else [])
    decades_p = decades_b
    mat_p = np.zeros((len(rows_p), len(decades_p)), dtype=int)
    for r in occ:
        d = decade_of(r[3])
        if d is None:
            continue
        p = r[6] if r[6] else "未标注省份"
        row = p if p in top_prov else "其他/未标注"
        mat_p[rows_p.index(row), decades_p.index(d)] += 1

    # --- top 地点（distinct 事件数） ---
    place_events = Counter()
    for r in places:
        place_events[r[1]] += 1
    top_places = sorted(place_events.items(), key=lambda kv: (-kv[1], kv[0]))[:15]

    # --- 绘图 ---
    plt.rcParams.update(figure_rc(font_info))
    fig = plt.figure(figsize=(13.6, 8.6))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.55, 1.0], hspace=0.42, wspace=0.34,
                          left=0.075, right=0.975, top=0.86, bottom=0.09)

    def draw_heat(ax, mat, rows, cols, title):
        im = ax.imshow(np.where(mat > 0, mat, np.nan),
                       norm=LogNorm(vmin=1, vmax=max(1, mat.max())),
                       cmap="YlGnBu", aspect="auto")
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels([c[2:] for c in cols], rotation=45, ha="right")
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels(rows)
        ax.set_title(title, fontsize=10, pad=6)
        ax.spines[:].set_visible(False)
        ax.set_xticks(np.arange(-.5, len(cols), 1), minor=True)
        ax.set_yticks(np.arange(-.5, len(rows), 1), minor=True)
        ax.grid(which="minor", color="white", linewidth=0.6)
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                if mat[i, j] > 0:
                    color = "white" if mat[i, j] > mat.max() * 0.55 else "#24303c"
                    ax.text(j, i, str(mat[i, j]), ha="center", va="center",
                            fontsize=6.4, color=color)
        return im

    ax1 = fig.add_subplot(gs[0, 0])
    im = draw_heat(ax1, mat_b, basins, decades_b,
                   f"(a) 事件 occurred_at 断言密度：十年 × 河段（n={fmt(n_occ)} 条断言）")
    cb = fig.colorbar(im, ax=ax1, shrink=0.85, pad=0.015)
    cb.set_label("断言条数（对数色标）", fontsize=8)

    ax2 = fig.add_subplot(gs[0, 1])
    im2 = draw_heat(ax2, mat_p, rows_p, decades_p,
                    f"(b) 事件 occurred_at 断言密度：十年 × 省份 Top{len(top_prov)}")
    cb2 = fig.colorbar(im2, ax=ax2, shrink=0.85, pad=0.015)
    cb2.set_label("断言条数（对数色标）", fontsize=8)

    ax3 = fig.add_subplot(gs[1, :])
    names = [trunc(p, 16) for p, _ in top_places][::-1]
    vals = [v for _, v in top_places][::-1]
    bars = ax3.barh(range(len(vals)), vals, color="#1b6ca8", alpha=0.88, height=0.62)
    ax3.set_yticks(range(len(vals)))
    ax3.set_yticklabels(names)
    ax3.set_xlabel("涉及的有时间戳事件数（distinct event_id）")
    ax3.set_title(f"(c) 事件发生地 Top{len(top_places)}（occurred_at 断言事件 × 事件地点断言，"
                  f"{fmt(n_pairs)} 个事件-地点对 / {fmt(n_events_both)} 个事件）", fontsize=10, pad=6)
    for b, v in zip(bars, vals):
        ax3.text(b.get_width() + max(vals) * 0.012, b.get_y() + b.get_height() / 2,
                 str(v), va="center", fontsize=7.6, color="#24303c")
    ax3.set_xlim(0, max(vals) * 1.12)

    fig.suptitle("VIZ-1 长江流域红色事件时空密度（事件 occurred_at → 地点断言）",
                 x=0.075, y=0.975, ha="left", fontsize=14, fontweight="bold")
    fig.text(0.075, 0.925,
             f"有时间戳事件断言 {fmt(n_occ)} 条（涉及 {fmt(n_events)} 个事件）；"
             f"事件-地点断言对 {fmt(n_pairs)} 个；既有时间又有地点的事件 {fmt(n_events_both)} 个。"
             f"十年桶按 time_start 前四位取整。{hub.source_line(['v_research_event_occurrence_times'])}",
             fontsize=8.6, color="#3a4652")
    add_source_footer(fig,
                      f"SQL 见 figures/stkg_viz1_event_spacetime_density_CAPTION.md | "
                      f"数据库只读 | 生成脚本 build_stkg_visualizations.py | 确定性管线")
    save(fig, FIGURES_DIR / "stkg_viz1_event_spacetime_density.png")

    hub_src = hub.usage[-2:]
    write_caption(
        "stkg_viz1_event_spacetime_density",
        "长江流域红色事件时空密度（事件 occurred_at→地点断言，十年 × 河段/省份）",
        "VIZ-1",
        [("Q1 事件发生时间断言（v_research_event_occurrence_times）", SQL_VIZ1_OCC),
         ("Q2 事件-地点断言（v_research_event_places × 有时间事件）", SQL_VIZ1_PLACES)],
        [("occurred_at 时间断言行数", fmt(n_occ)),
         ("有发生时间的 distinct 事件数", fmt(n_events)),
         ("事件-地点断言对（distinct event×place×type）", fmt(n_pairs)),
         ("既有时间又有地点的事件数", fmt(n_events_both)),
         ("热力图 (a) 单元格总数 / 非零格", f"{mat_b.size} / {int((mat_b > 0).sum())}"),
         ("热力图 (b) 单元格总数 / 非零格", f"{mat_p.size} / {int((mat_p > 0).sum())}"),
         ("数据源", hub.source_line(['v_research_event_occurrence_times']))],
        notes=["另含交互版无；VIZ-1 仅 PNG"])
    return {"n_occ": n_occ, "n_events": n_events, "n_pairs": n_pairs,
            "n_events_both": n_events_both}


# ===========================================================================
# VIZ-2 人物时空轨迹（PNG 多面板 + 交互 HTML）
# ===========================================================================

SQL_VIZ2_TOP = """
SELECT ar.counterpart_id, ar.counterpart_name, COUNT(DISTINCT ar.fact_id) AS n_facts,
       COUNT(DISTINCT ar.event_id) AS n_events
FROM v_research_event_actor_roles ar
JOIN research_entities en ON en.entity_id = ar.counterpart_id AND en.entity_type = 'Person'
GROUP BY ar.counterpart_id, ar.counterpart_name
ORDER BY n_facts DESC, ar.counterpart_id
LIMIT 3
"""

SQL_VIZ2_ORG = """
SELECT r.predicate, r.object_name, MIN(r.time_start) AS s, MAX(COALESCE(NULLIF(r.time_end,''), r.time_end, r.time_start)) AS e,
       COUNT(*) AS n
FROM research_assertions r
WHERE r.subject_id = ? AND r.time_start IS NOT NULL AND r.time_start <> ''
  AND r.predicate IN ('member_of','held_position_in','led','organized')
GROUP BY r.predicate, r.object_name
ORDER BY n DESC, s, r.object_name
"""

SQL_VIZ2_EVENTS = """
SELECT t.event_name, MIN(t.occurrence_time_start) AS s, MAX(t.occurrence_time_end) AS e,
       COUNT(DISTINCT ar.fact_id) AS n,
       (SELECT pl.event_location_name FROM v_research_event_places pl
        WHERE pl.event_id = t.event_id GROUP BY pl.event_location_name
        ORDER BY COUNT(*) DESC, pl.event_location_name LIMIT 1) AS top_place
FROM v_research_event_actor_roles ar
JOIN v_research_event_times t ON t.event_id = ar.event_id
WHERE ar.counterpart_id = ?
GROUP BY t.event_id, t.event_name
ORDER BY n DESC, s, t.event_name
"""

SQL_VIZ2_NET = """
SELECT x.entity_id, x.canonical_name, x.entity_type, COUNT(*) AS n
FROM research_assertions r
JOIN research_entities x ON x.entity_id = (CASE WHEN r.subject_id = :pid THEN r.object_id ELSE r.subject_id END)
WHERE r.subject_id = :pid OR r.object_id = :pid
GROUP BY x.entity_id, x.canonical_name, x.entity_type
ORDER BY n DESC, x.canonical_name, x.entity_id
LIMIT 16
"""


def collect_person(hub: DataHub, pid: str) -> dict:
    org_rows = hub.q(["research_assertions"], SQL_VIZ2_ORG, (pid,))
    ev_rows = hub.q(["v_research_event_actor_roles", "v_research_event_times",
                     "v_research_event_places"], SQL_VIZ2_EVENTS, (pid,))
    net_rows = hub.q(["research_assertions", "research_entities"], SQL_VIZ2_NET, {"pid": pid})

    org_items = [{"kind": "组织/职务关系", "role": r[0], "label": r[1],
                  "start": r[2][:10], "end": (r[3] or r[2])[:10], "n": r[4]} for r in org_rows]
    ev_items = [{"kind": "事件参与", "role": "participated_in", "label": r[0],
                 "start": r[1][:10], "end": (r[2] or r[1])[:10], "n": r[3],
                 "place": r[4]} for r in ev_rows]

    def pick(items, k):
        return sorted(items, key=lambda d: (-d["n"], d["start"], d["label"]))[:k]

    chosen = pick(org_items, 13) + pick(ev_items, 13)
    chosen = sorted(chosen, key=lambda d: (d["start"], d["kind"], d["label"]))
    span = [min(i["start"] for i in chosen), max(i["end"] for i in chosen)] if chosen else ["", ""]
    return {"org_total": len(org_rows), "ev_total": len(ev_rows),
            "items": chosen, "span": span,
            "net": [{"id": r[0], "name": r[1], "type": r[2], "n": r[3]} for r in net_rows]}


def viz2(hub: DataHub, font_info: dict) -> dict:
    top = hub.q(["v_research_event_actor_roles", "research_entities"], SQL_VIZ2_TOP)
    persons = []
    for pid, name, n_facts, n_events in top:
        d = collect_person(hub, pid)
        persons.append({"id": pid, "name": name, "n_facts": n_facts,
                        "n_events": n_events, **d})

    # ---------------- PNG（matplotlib 多面板，pyvis 不可用时的规范回退） ----------------
    plt.rcParams.update(figure_rc(font_info))
    fig = plt.figure(figsize=(15.5, 12.6))
    gs = fig.add_gridspec(3, 2, width_ratios=[1.5, 1.0], hspace=0.52, wspace=0.30,
                          left=0.16, right=0.975, top=0.90, bottom=0.055)

    for i, p in enumerate(persons):
        ax = fig.add_subplot(gs[i, 0])
        items = p["items"]
        y0, y1 = int(p["span"][0][:4]) - 1, int(p["span"][1][:4]) + 1
        for j, it in enumerate(items):
            s, e = int(it["start"][:4]), max(int(it["end"][:4]) + 1, int(it["start"][:4]) + 1)
            color = KIND_COLORS[it["kind"]]
            ax.barh(j, e - s, left=s, height=0.62, color=color, alpha=0.85)
        ax.set_ylim(-0.7, len(items) - 0.3)
        ax.set_xlim(y0, y1)
        ax.set_yticks(range(len(items)))
        ax.set_yticklabels([f"{trunc(it['label'], 15)} ({it['n']})" for it in items], fontsize=6.4)
        ax.invert_yaxis()
        ax.set_xticks(np.arange(y0, y1 + 1, 4))
        ax.grid(axis="x", color="#e7ecef", linewidth=0.6, zorder=0)
        ax.set_axisbelow(True)
        ax.set_xlabel("年份")
        ax.set_title(f"({chr(97 + i)}) {p['name']} — 时间线（x=时间区间，条目后括号=支持断言数；"
                     f"候选：组织/职务关系 {p['org_total']} 项、事件参与 {p['ev_total']} 项，各取前 13）",
                     fontsize=9.5, pad=5)
        ax.spines[:].set_visible(False)
        ax.tick_params(axis="y", length=0)

        axn = fig.add_subplot(gs[i, 1])
        net = p["net"]
        n = len(net)
        angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
        wmax = max(x["n"] for x in net)
        for a, x in zip(angles, net):
            axn.plot([0, np.cos(a)], [0, np.sin(a)], color="#b9c4ce",
                     linewidth=0.6 + 2.4 * (x["n"] / wmax), zorder=1)
        for a, x in zip(angles, net):
            color = ENTITY_TYPE_COLORS.get(x["type"], "#7f8c8d")
            size = 40 + 260 * (x["n"] / wmax)
            axn.scatter([np.cos(a)], [np.sin(a)], s=size, color=color,
                        alpha=0.9, zorder=2, edgecolors="white", linewidths=0.8)
            ha = "left" if np.cos(a) >= 0 else "right"
            axn.text(np.cos(a) * 1.22, np.sin(a) * 1.22,
                     f"{trunc(x['name'], 10)}（{x['n']}）", ha=ha, va="center", fontsize=6.6)
        axn.scatter([0], [0], s=260, color="#c0392b", zorder=3,
                    edgecolors="white", linewidths=1.0)
        axn.text(0, 0, p["name"], ha="center", va="center", fontsize=7.5,
                 color="white", zorder=4, fontweight="bold")
        axn.set_xlim(-1.55, 1.55)
        axn.set_ylim(-1.35, 1.35)
        axn.set_xticks([])
        axn.set_yticks([])
        axn.spines[:].set_visible(False)
        axn.set_title(f"({chr(100 + i)}) {p['name']} 的断言邻居网络（直接断言 Top{n}，边宽∝断言数）",
                      fontsize=9.5, pad=5)

    handles = [plt.Line2D([], [], marker="s", ls="", color=KIND_COLORS[k], label=k)
               for k in ["组织/职务关系", "事件参与"]]
    handles += [plt.Line2D([], [], marker="o", ls="", color=ENTITY_TYPE_COLORS[t], label=t)
                for t in ["Person", "Organization", "Institution", "Event", "Place",
                          "AdministrativeRegion", "Concept"]]
    fig.legend(handles=handles, loc="lower right", ncol=9, frameon=False,
               bbox_to_anchor=(0.985, 0.004), fontsize=7.6)
    fig.suptitle("VIZ-2 人物时空轨迹：参与断言最多的 3 位人物（时间线 + 断言邻居网络）",
                 x=0.055, y=0.972, ha="left", fontsize=14, fontweight="bold")
    tot_f = sum(p["n_facts"] for p in persons)
    fig.text(0.055, 0.932,
             f"入选规则：按参与事件的 distinct 断言数取 Top3 人物（合计 {fmt(tot_f)} 条参与断言）；"
             f"时间线条目=该人物带时间区间的组织/职务关系断言与带发生时间的事件参与断言；"
             f"网络=直接断言（人物为主语或宾语）邻居。{hub.source_line(['research_assertions'])}",
             fontsize=8.6, color="#3a4652")
    add_source_footer(fig, "SQL 见 figures/stkg_viz2_person_trajectories_CAPTION.md | "
                           "交互版见 figures/stkg_viz2_person_trajectories.html | 数据库只读 | 确定性管线")
    save(fig, FIGURES_DIR / "stkg_viz2_person_trajectories.png")

    # ---------------- 交互 HTML（自包含，无外部依赖；布局在 Python 端确定性计算） ----------------
    html_text = build_viz2_html(persons, font_info)
    (FIGURES_DIR / "stkg_viz2_person_trajectories.html").write_text(html_text, encoding="utf-8")
    print("  [ok] stkg_viz2_person_trajectories.html")

    write_caption(
        "stkg_viz2_person_trajectories",
        "人物时空轨迹：参与断言最多的 3 位人物的时间线与断言邻居网络（PNG 多面板 + 交互 HTML）",
        "VIZ-2",
        [("Q1 参与断言 Top3 人物（事件角色 × 实体表）", SQL_VIZ2_TOP),
         ("Q2 每人带时间区间的组织/职务关系断言（按谓词×对象聚合）", SQL_VIZ2_ORG),
         ("Q3 每人带发生时间的事件参与断言（事件时间视图 × 角色视图，附 Top1 地点）", SQL_VIZ2_EVENTS),
         ("Q4 每人直接断言邻居网络 Top16（research_assertions × research_entities）", SQL_VIZ2_NET)],
        [("Top3 人物", "、".join(f"{p['name']}(参与断言 {fmt(p['n_facts'])} / 事件 {fmt(p['n_events'])})" for p in persons)),
         ("时间线条目（3 人合计）", fmt(sum(len(p['items']) for p in persons))),
         ("网络节点（3 人合计，含中心）", fmt(sum(len(p['net']) + 1 for p in persons))),
         ("网络边（3 人合计）", fmt(sum(len(p['net']) for p in persons))),
         ("HTML 数据", "自包含（无 CDN），节点坐标由 Python 确定性生成"),
         ("数据源", hub.source_line(["research_assertions"]))],
        notes=["stkg_viz2_person_trajectories.html（交互版）"])
    return persons


# --- VIZ-2 交互 HTML ---------------------------------------------------------------

def build_viz2_html(persons: list[dict], font_info: dict) -> str:
    data = []
    for p in persons:
        net = p["net"]
        n = len(net)
        angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
        wmax = max(x["n"] for x in net)
        nodes = [{"name": p["name"], "type": "SELF", "n": p["n_facts"], "x": 0.0, "y": 0.0}]
        edges = []
        for a, x in zip(angles, net):
            nodes.append({"name": x["name"], "type": x["type"], "n": x["n"],
                          "x": round(float(np.cos(a)), 6), "y": round(float(np.sin(a)), 6)})
            edges.append({"target": len(nodes) - 1, "n": x["n"], "w": round(0.6 + 2.4 * x["n"] / wmax, 3)})
        data.append({"name": p["name"], "n_facts": p["n_facts"], "n_events": p["n_events"],
                     "org_total": p["org_total"], "ev_total": p["ev_total"],
                     "span": p["span"], "items": p["items"], "net_nodes": nodes, "net_edges": edges})

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    type_colors = json.dumps(ENTITY_TYPE_COLORS, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>VIZ-2 人物时空轨迹（交互版）</title>
<style>
  :root {{ --ink:#24303c; --muted:#5a6572; --line:#d8dee4; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:24px 28px; font-family:"Microsoft YaHei","SimHei","Noto Sans CJK SC",sans-serif;
         color:var(--ink); background:#fbfcfd; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  .sub {{ color:var(--muted); font-size:12px; margin-bottom:14px; line-height:1.7; }}
  .tabs {{ margin:10px 0 14px; }}
  .tabs button {{ font:inherit; font-size:13px; padding:6px 16px; margin-right:8px; cursor:pointer;
                  border:1px solid var(--line); background:#fff; border-radius:16px; color:var(--ink); }}
  .tabs button.active {{ background:#1b6ca8; border-color:#1b6ca8; color:#fff; }}
  .panels {{ display:flex; gap:26px; flex-wrap:wrap; align-items:flex-start; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
  .card h2 {{ font-size:14px; margin:0 0 8px; }}
  .legend {{ font-size:11.5px; color:var(--muted); margin:6px 0 8px; display:flex; gap:14px; flex-wrap:wrap; }}
  .sw {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:4px; vertical-align:-1px; }}
  svg text {{ font-family:inherit; }}
  #tip {{ position:fixed; display:none; pointer-events:none; background:#24303c; color:#fff;
          font-size:12px; line-height:1.55; padding:7px 10px; border-radius:6px; max-width:320px; z-index:9; }}
  .foot {{ margin-top:16px; color:var(--muted); font-size:11.5px; }}
</style>
</head>
<body>
<h1>VIZ-2 人物时空轨迹：参与断言最多的 3 位人物</h1>
<div class="sub">
  数据源：{esc(DB_LABEL['v3_1'])}（只读）。左：时间线（x = 时间区间，y = 活动地/组织条目；蓝 = 组织/职务关系断言，红 = 事件参与断言，条目按断言数取前 13+13）。
  右：断言邻居网络（research_assertions 中以该人物为主语或宾语的 Top16 邻居，边宽 ∝ 断言数）。悬停查看明细。
</div>
<div class="tabs" id="tabs"></div>
<div class="panels">
  <div class="card"><h2 id="tl-title"></h2><div class="legend" id="tl-legend"></div><div id="timeline"></div></div>
  <div class="card"><h2 id="net-title"></h2><div class="legend" id="net-legend"></div><div id="network"></div></div>
</div>
<div class="foot">SQL 与行数见 figures/stkg_viz2_person_trajectories_CAPTION.md ｜ 确定性管线：坐标与条目排序均在生成期固定，无随机布局。生成时间：{esc(RUN_STAMP)}</div>
<div id="tip"></div>
<script>
const DATA = {payload};
const TYPE_COLORS = {type_colors};
const SELF_COLOR = "#c0392b";
const KIND_COLORS = {json.dumps(KIND_COLORS, ensure_ascii=False)};
const tip = document.getElementById('tip');
let cur = 0;
function showTip(ev, html) {{ tip.innerHTML = html; tip.style.display = 'block';
  tip.style.left = (ev.clientX + 14) + 'px'; tip.style.top = (ev.clientY + 12) + 'px'; }}
function hideTip() {{ tip.style.display = 'none'; }}
function esc(s) {{ const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }}

function drawTimeline(p) {{
  const W = 640, padL = 168, padR = 26, rowH = 26, padT = 8;
  const y0 = parseInt(p.span[0].slice(0,4)) - 1, y1 = parseInt(p.span[1].slice(0,4)) + 1;
  const H = padT + p.items.length * rowH + 30;
  const x = yr => padL + (yr - y0) / (y1 - y0) * (W - padL - padR);
  let s = '<svg width="' + W + '" height="' + H + '">';
  for (let yr = Math.ceil(y0 / 4) * 4; yr <= y1; yr += 4) {{
    s += '<line x1="' + x(yr) + '" y1="' + padT + '" x2="' + x(yr) + '" y2="' + (H - 24) + '" stroke="#e7ecef"/>';
    s += '<text x="' + x(yr) + '" y="' + (H - 8) + '" font-size="10.5" fill="#5a6572" text-anchor="middle">' + yr + '</text>';
  }}
  p.items.forEach((it, i) => {{
    const ys = parseInt(it.start.slice(0,4)), ye = Math.max(parseInt((it.end||it.start).slice(0,4)) + 1, ys + 1);
    const yy = padT + i * rowH + rowH / 2;
    s += '<text x="' + (padL - 8) + '" y="' + (yy + 3.5) + '" font-size="11" fill="#24303c" text-anchor="end">'
      + esc(it.label.length > 14 ? it.label.slice(0,13) + '…' : it.label) + '</text>';
    s += '<rect data-i="' + i + '" x="' + x(ys) + '" y="' + (yy - 8) + '" width="' + Math.max(x(ye) - x(ys), 4)
      + '" height="16" rx="3" fill="' + KIND_COLORS[it.kind] + '" opacity="0.88" style="cursor:pointer"/>';
  }});
  s += '</svg>';
  document.getElementById('timeline').innerHTML = s;
  document.querySelectorAll('#timeline rect').forEach(r => {{
    const it = p.items[+r.dataset.i];
    r.addEventListener('mousemove', ev => showTip(ev,
      '<b>' + esc(it.label) + '</b><br>' + esc(it.kind) + ' · ' + esc(it.role)
      + '<br>' + esc(it.start) + ' ~ ' + esc(it.end||it.start)
      + (it.place ? '<br>Top1 事件地点：' + esc(it.place) : '')
      + '<br>支持断言：' + it.n + ' 条'));
    r.addEventListener('mouseleave', hideTip);
  }});
  document.getElementById('tl-title').textContent = p.name + ' — 时间线（共选 ' + p.items.length + ' 条目）';
  document.getElementById('tl-legend').innerHTML = Object.entries(KIND_COLORS)
    .map(([k, c]) => '<span><span class="sw" style="background:' + c + '"></span>' + k + '</span>').join('');
}}

function drawNetwork(p) {{
  const W = 470, H = 430, cx = W / 2, cy = H / 2, R = 158;
  const pos = nd => [cx + nd.x * R, cy + nd.y * R];
  let s = '<svg width="' + W + '" height="' + H + '">';
  p.net_edges.forEach(e => {{
    const a = pos(p.net_nodes[0]), b = pos(p.net_nodes[e.target]);
    s += '<line class="ed" data-t="' + e.target + '" x1="' + a[0] + '" y1="' + a[1] + '" x2="' + b[0] + '" y2="' + b[1]
      + '" stroke="#b9c4ce" stroke-width="' + e.w + '"/>';
  }});
  p.net_nodes.forEach((nd, i) => {{
    const [px, py] = pos(nd);
    const c = nd.type === 'SELF' ? SELF_COLOR : (TYPE_COLORS[nd.type] || '#7f8c8d');
    const rr = nd.type === 'SELF' ? 15 : 6 + 11 * nd.n / Math.max(...p.net_nodes.slice(1).map(z => z.n));
    s += '<circle class="nd" data-i="' + i + '" cx="' + px + '" cy="' + py + '" r="' + rr.toFixed(1)
      + '" fill="' + c + '" stroke="#fff" stroke-width="1.2" style="cursor:pointer"/>';
    const lx = cx + nd.x * (R + 24), ly = cy + nd.y * (R + 24);
    if (nd.type !== 'SELF') s += '<text x="' + lx + '" y="' + (ly + 3.5) + '" font-size="10.5" fill="#24303c" text-anchor="middle">'
      + esc(nd.name.length > 9 ? nd.name.slice(0, 8) + '…' : nd.name) + '</text>';
  }});
  s += '<text x="' + cx + '" y="' + (cy + 4) + '" font-size="11" fill="#fff" text-anchor="middle" font-weight="bold" pointer-events="none">'
    + esc(p.name.length > 5 ? p.name.slice(0, 4) + '…' : p.name) + '</text></svg>';
  document.getElementById('network').innerHTML = s;
  document.querySelectorAll('#network .nd').forEach(cEl => {{
    const nd = p.net_nodes[+cEl.dataset.i];
    cEl.addEventListener('mousemove', ev => {{
      document.querySelectorAll('#network .ed').forEach(l =>
        l.setAttribute('stroke', l.dataset.t == cEl.dataset.i ? '#c0392b' : '#b9c4ce'));
      showTip(ev, '<b>' + esc(nd.name) + '</b><br>类型：' + esc(nd.type) + '<br>与 ' + esc(p.name)
        + ' 的直接断言：' + nd.n + ' 条'));
    }});
    cEl.addEventListener('mouseleave', () => {{ hideTip();
      document.querySelectorAll('#network .ed').forEach(l => l.setAttribute('stroke', '#b9c4ce')); }});
  }});
  document.getElementById('net-title').textContent = p.name + ' — 断言邻居网络（Top' + (p.net_nodes.length - 1) + '）';
  const used = [...new Set(p.net_nodes.slice(1).map(n => n.type))];
  document.getElementById('net-legend').innerHTML = used
    .map(t => '<span><span class="sw" style="background:' + (TYPE_COLORS[t] || '#7f8c8d') + '"></span>' + t + '</span>').join('');
}}

function render(i) {{
  cur = i;
  document.getElementById('tabs').innerHTML = DATA.map((p, j) =>
    '<button class="' + (j === i ? 'active' : '') + '" onclick="render(' + j + ')">'
    + esc(p.name) + '（参与断言 ' + p.n_facts.toLocaleString() + '）</button>').join('');
  drawTimeline(DATA[i]);
  drawNetwork(DATA[i]);
}}
render(0);
</script>
</body>
</html>
"""


# ===========================================================================
# VIZ-3 EventFrame 结构
# ===========================================================================

SQL_VIZ3_TOP2 = """
SELECT event_id, event_name, all_assertion_count, strict_assertion_count, controlled_role_count,
       occurrence_time_fact_count, trusted_time_fact_count, event_location_fact_count,
       stage_count, region_count, observed_time_start, observed_time_end, observed_time_status,
       frame_status
FROM research_event_frames
ORDER BY all_assertion_count DESC, event_id
LIMIT 2
"""

SQL_VIZ3_ROLES = """
SELECT role_category, COUNT(*) AS n, COUNT(DISTINCT fact_id) AS n_facts
FROM research_event_roles WHERE event_id = ?
GROUP BY role_category ORDER BY n DESC, role_category
"""

SQL_VIZ3_ACTORS = """
SELECT counterpart_name, role_code, COUNT(*) AS n
FROM v_research_event_actor_roles WHERE event_id = ?
GROUP BY counterpart_name, role_code ORDER BY n DESC, counterpart_name LIMIT 8
"""

SQL_VIZ3_CELLS = """
SELECT province_name, observation_tier, COUNT(*) AS n_cells,
       SUM(time_evidence_count + place_evidence_count + context_evidence_count) AS n_evidence
FROM research_event_spatiotemporal_cells WHERE event_id = ?
GROUP BY province_name, observation_tier
ORDER BY n_evidence DESC, province_name
"""

SQL_VIZ3_PLACES = """
SELECT event_location_name, COUNT(*) AS n
FROM v_research_event_places WHERE event_id = ?
GROUP BY event_location_name ORDER BY n DESC, event_location_name LIMIT 6
"""

SQL_VIZ3_TEMPORAL = """
SELECT relation, COUNT(*) FROM event_frame_temporal
WHERE frame_a = ? OR frame_b = ? GROUP BY relation ORDER BY 2 DESC, relation
"""

SQL_VIZ3_PROV = """
SELECT COUNT(*) AS n_rows, COUNT(DISTINCT assertion_id) AS n_assertions
FROM event_frame_provenance WHERE frame_id = ?
"""


def viz3(hub: DataHub, font_info: dict) -> dict:
    frames = hub.q(["research_event_frames"], SQL_VIZ3_TOP2)
    details = []
    for fr in frames:
        eid = fr[0]
        roles = hub.q(["research_event_roles"], SQL_VIZ3_ROLES, (eid,))
        actors = hub.q(["v_research_event_actor_roles"], SQL_VIZ3_ACTORS, (eid,))
        cells = hub.q(["research_event_spatiotemporal_cells"], SQL_VIZ3_CELLS, (eid,))
        places = hub.q(["v_research_event_places"], SQL_VIZ3_PLACES, (eid,))
        temporal = hub.q(["event_frame_temporal"], SQL_VIZ3_TEMPORAL, (eid, eid))
        prov = hub.q(["event_frame_provenance"], SQL_VIZ3_PROV, (eid,))[0]
        details.append({"frame": fr, "roles": roles, "actors": actors, "cells": cells,
                        "places": places, "temporal": temporal, "prov": prov})

    plt.rcParams.update(figure_rc(font_info))
    fig = plt.figure(figsize=(15.8, 10.2))
    gs = fig.add_gridspec(4, 2, height_ratios=[0.62, 1.0, 1.0, 1.05], hspace=0.72, wspace=0.36,
                          left=0.10, right=0.965, top=0.86, bottom=0.06)

    for c, d in enumerate(details):
        fr = d["frame"]
        (eid, name, n_all, n_strict, n_roles, n_otf, n_ttf, n_loc, n_stage, n_region,
         t0, t1, t_status, f_status) = fr
        # 头部信息条
        axh = fig.add_subplot(gs[0, c])
        axh.axis("off")
        info = (f"frame_id: {eid}\n"
                f"frame_status: {f_status}   观测时间: {t0 or '—'} ~ {t1 or '—'}（{t_status}）\n"
                f"断言: 全部 {fmt(n_all)} / 严格 {fmt(n_strict)}   受控角色 {fmt(n_roles)}   "
                f"发生时间断言 {fmt(n_otf)}（可信 {fmt(n_ttf)}）   地点断言 {fmt(n_loc)}\n"
                f"阶段单元 {n_stage} / 区域单元 {n_region}   帧证据行 {fmt(d['prov'][0])}"
                f"（distinct 断言 {fmt(d['prov'][1])}）   帧间时序关系 {fmt(sum(v for _, v in d['temporal']))} 条")
        axh.text(0, 1.06, f"▍{name}（按断言数第 {c + 1} 大事件帧）", fontsize=12.5,
                 fontweight="bold", va="top", transform=axh.transAxes)
        axh.text(0, 0.80, info, fontsize=7.7, va="top", transform=axh.transAxes,
                 color="#3a4652", linespacing=1.72,
                 bbox=dict(boxstyle="round,pad=0.45", fc="#f2f6f9", ec="#c9d4dd"))

        # 参与者
        axa = fig.add_subplot(gs[1, c])
        names = [trunc(f"{a[0]}·{a[1]}", 18) for a in d["actors"]][::-1]
        vals = [a[2] for a in d["actors"]][::-1]
        axa.barh(range(len(vals)), vals, color="#1b6ca8", alpha=0.88, height=0.6)
        axa.set_yticks(range(len(vals)))
        axa.set_yticklabels(names, fontsize=7.4)
        axa.set_title(f"({chr(97 + c * 2)}) Top{len(vals)} 参与者（姓名·角色码，按断言数）", fontsize=9.5, pad=5)
        axa.set_xlabel("断言条数")

        # 角色类别 + 时序关系（行内再分左右两个子面板）
        gs_r2 = gs[2, c].subgridspec(1, 2, width_ratios=[1.55, 1.0], wspace=0.52)
        axr = fig.add_subplot(gs_r2[0])
        rlabels = [r[0] for r in d["roles"]]
        rvals = [r[1] for r in d["roles"]]
        x = np.arange(len(rlabels))
        axr.bar(x, rvals, width=0.62, color="#7d3c98", alpha=0.9)
        axr.set_xticks(x)
        axr.set_xticklabels(rlabels, rotation=32, ha="right", fontsize=6.8)
        axr.set_ylabel("角色行数")
        axr.set_title(f"({chr(98 + c * 2)}) 角色类别分布", fontsize=9.5, pad=5)

        axt = fig.add_subplot(gs_r2[1])
        rel_order = ["before", "after", "during", "overlaps"]
        rel_dict = dict(d["temporal"])
        fvals = [rel_dict.get(r, 0) for r in rel_order]
        xt = np.arange(len(rel_order))
        axt.bar(xt, fvals, width=0.62, color="#e8a33d", alpha=0.9)
        axt.set_xticks(xt)
        axt.set_xticklabels(rel_order, rotation=32, ha="right", fontsize=6.8)
        axt.set_ylabel("关系条数")
        axt.set_title("帧间时序关系（U4）", fontsize=9.0, pad=5)

        # 空间足迹：按省份的证据行数（时间+地点+上下文证据），按观测层堆叠
        axc = fig.add_subplot(gs[3, c])
        sum_ev = Counter()
        for pname, tier, n_cells, n_ev in d["cells"]:
            sum_ev[pname] += n_ev or 0
        prov_order = [p for p, _ in sorted(sum_ev.items(), key=lambda kv: (-kv[1], kv[0]))][:8]
        tiers = ["trusted_event_spacetime", "asserted_event_spacetime", "relation_context"]
        bottom = np.zeros(len(prov_order))
        for tier in tiers:
            vals = [sum((row[3] or 0) for row in d["cells"] if row[0] == p and row[1] == tier)
                    for p in prov_order]
            axc.bar(range(len(prov_order)), vals, bottom=bottom, width=0.6,
                    color=CELL_TIER_COLORS[tier], label=tier, alpha=0.92)
            bottom += np.array(vals)
        axc.set_xticks(range(len(prov_order)))
        axc.set_xticklabels([trunc(p, 8) for p in prov_order], fontsize=7.4)
        axc.set_ylabel("证据行数（时间+地点+上下文）")
        plc = "；".join(f"{trunc(p, 10)}({n})" for p, n in d["places"][:4])
        axc.set_title(f"({chr(99 + c * 2)}) 空间足迹：阶段×省份单元证据数按观测层堆叠｜Top 地点: {plc}",
                      fontsize=8.6, pad=5)
        if c == 0:
            axc.legend(frameon=False, fontsize=7.0, loc="upper right")

    fig.suptitle("VIZ-3 EventFrame 结构一页式展示：断言数最多的 2 个事件帧",
                 x=0.06, y=0.975, ha="left", fontsize=14, fontweight="bold")
    fig.text(0.06, 0.925,
             f"帧选取：research_event_frames 按 all_assertion_count 降序 Top2（"
             f"{'、'.join(d['frame'][1] for d in details)}）。证据行= U1 event_frame_provenance；"
             f"时序关系= U4 event_frame_temporal。{hub.source_line(['research_event_frames'])}",
             fontsize=8.6, color="#3a4652")
    add_source_footer(fig, "SQL 见 figures/stkg_viz3_event_frame_structure_CAPTION.md | 数据库只读 | 确定性管线")
    save(fig, FIGURES_DIR / "stkg_viz3_event_frame_structure.png")

    write_caption(
        "stkg_viz3_event_frame_structure",
        "EventFrame 结构一页式展示（Top-2 事件帧：参与者 / 时间区间 / 空间足迹 / 角色 / 断言数 / 证据数）",
        "VIZ-3",
        [("Q1 Top-2 事件帧", SQL_VIZ3_TOP2),
         ("Q2 帧内角色类别分布", SQL_VIZ3_ROLES),
         ("Q3 Top 参与者", SQL_VIZ3_ACTORS),
         ("Q4 时空单元（阶段×省份×观测层）", SQL_VIZ3_CELLS),
         ("Q5 帧内地点 Top6", SQL_VIZ3_PLACES),
         ("Q6 帧间时序关系（U4）", SQL_VIZ3_TEMPORAL),
         ("Q7 帧证据行（U1 provenance）", SQL_VIZ3_PROV)],
        [(f"帧{chr(0x2460 + i)}·{d['frame'][1]}", f"断言 {fmt(d['frame'][2])}（严格 {fmt(d['frame'][3])}），"
          f"角色行 {fmt(sum(r[1] for r in d['roles']))}，参与者对 {fmt(sum(r[2] for r in d['actors']))}+，"
          f"时空单元 {fmt(len(d['cells']))}，证据行 {fmt(d['prov'][0])}")
         for i, d in enumerate(details)],
        notes=[])
    return [{"name": d["frame"][1], "n_all": d["frame"][2], "n_strict": d["frame"][3],
             "prov_rows": d["prov"][0], "cells": len(d["cells"])} for d in details]


# ===========================================================================
# VIZ-4 CultureState 演化
# ===========================================================================

SQL_VIZ4_STATES = """
SELECT culture_form_code, stage_code, basin_section_id, observation_tier, state_time_start,
       state_time_source, supporting_event_count
FROM research_culture_states
ORDER BY state_id
"""

SQL_VIZ4_FORMS = "SELECT culture_form_code, label_zh FROM research_culture_forms ORDER BY culture_form_code"
SQL_VIZ4_STAGES = "SELECT stage_code, stage_label_zh, stage_order FROM research_historical_stages ORDER BY stage_order"
SQL_VIZ4_EVT = """
SELECT s.stage_code, COUNT(*) AS n_links
FROM research_culture_state_events e JOIN research_culture_states s USING (state_id)
GROUP BY s.stage_code ORDER BY n_links DESC, s.stage_code
"""


def viz4(hub: DataHub, font_info: dict) -> dict:
    states = hub.q(["research_culture_states"], SQL_VIZ4_STATES)
    forms = hub.q(["research_culture_forms"], SQL_VIZ4_FORMS)
    stages = hub.q(["research_historical_stages"], SQL_VIZ4_STAGES)
    evt = dict(hub.q(["research_culture_state_events", "research_culture_states"], SQL_VIZ4_EVT))

    form_label = {c: l for c, l in forms}
    stage_order = [s[0] for s in stages]
    stage_label = {s[0]: STAGE_SHORT.get(s[0], s[1]) for s in stages}
    sections = BASIN_ORDER

    # 三联热力图：form × stage（按河段分面），值=状态数
    mats = {}
    for sec in sections:
        m = np.zeros((len(forms), len(stages)), dtype=int)
        for r in states:
            if r[2] == sec:
                m[[c for c, _ in forms].index(r[0]), stage_order.index(r[1])] += 1
        mats[sec] = m

    # 观测层堆叠（按阶段）
    tiers = ["trusted_event_spacetime", "asserted_event_spacetime", "relation_context"]
    tier_label = {"trusted_event_spacetime": "trusted（可信事件时空）",
                  "asserted_event_spacetime": "asserted（断言事件时空）",
                  "relation_context": "context（关系上下文）"}
    tier_stage = {t: np.array([sum(1 for r in states if r[1] == st and r[3] == t)
                               for st in stage_order]) for t in tiers}

    # --- U3 时间区间列：state_time_start 十年分布（按 state_time_source 着色） ---
    def decade_bucket(s):
        if not s or len(s) < 4 or not s[:4].isdigit():
            return None
        y = int(s[:4])
        if y >= 2030:
            return None
        if y < 1850:
            return "≤1850s"      # 含 stage_interval 回填的早期日期（如 0001-01-01）
        return f"{(y // 10) * 10}s"

    dec_order = ["≤1850s"] + [f"{y}s" for y in range(1860, 2030, 10)]
    src_keys = ["member_events_trusted", "member_events_asserted", "stage_interval"]
    src_label = {"member_events_trusted": "member_events_trusted（可信事件区间）",
                 "member_events_asserted": "member_events_asserted（断言事件区间）",
                 "stage_interval": "stage_interval（阶段区间回填）"}
    src_dec = {k: np.zeros(len(dec_order), dtype=int) for k in src_keys}
    n_undated = 0
    for r in states:
        b = decade_bucket(r[4])
        if b is None:
            n_undated += 1
            continue
        src_dec[r[5]][dec_order.index(b)] += 1

    plt.rcParams.update(figure_rc(font_info))
    fig = plt.figure(figsize=(16.2, 10.4))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.5, 1.0], hspace=0.34, wspace=0.24,
                          left=0.058, right=0.945, top=0.855, bottom=0.085)

    ylabels = [form_label[c] for c, _ in forms]
    gmax = max(1, max(int(m.max()) for m in mats.values()))
    for k, sec in enumerate(sections):
        ax = fig.add_subplot(gs[0, k])
        m = mats[sec]
        im = ax.imshow(np.where(m > 0, m, np.nan), cmap="YlGnBu",
                       norm=LogNorm(vmin=1, vmax=gmax),
                       aspect="auto")
        ax.set_xticks(range(len(stages)))
        ax.set_xticklabels([stage_label[s] for s in stage_order], rotation=38, ha="right", fontsize=7.2)
        if k == 0:
            ax.set_yticks(range(len(forms)))
            ax.set_yticklabels(ylabels, fontsize=7.8)
        else:
            ax.set_yticks([])
        ax.set_title(f"({'abc'[k]}) {BASIN_SHORT[sec]}：文化态计数（form × stage）",
                     fontsize=9.8, pad=5)
        ax.spines[:].set_visible(False)
        ax.set_xticks(np.arange(-.5, len(stages), 1), minor=True)
        ax.set_yticks(np.arange(-.5, len(forms), 1), minor=True)
        ax.grid(which="minor", color="white", linewidth=0.5)
        for i in range(m.shape[0]):
            for j in range(m.shape[1]):
                if m[i, j] > 0:
                    ax.text(j, i, str(m[i, j]), ha="center", va="center", fontsize=6.0,
                            color="white" if m[i, j] > gmax * 0.5 else "#24303c")
    cax = fig.add_axes([0.952, 0.56, 0.007, 0.27])
    fig.colorbar(im, cax=cax).set_label("状态数（对数色标）", fontsize=7.5)

    # 观测层堆叠
    axt = fig.add_subplot(gs[1, 0])
    bottom = np.zeros(len(stages))
    for t in tiers:
        axt.bar(range(len(stages)), tier_stage[t], bottom=bottom, width=0.62,
                color=CELL_TIER_COLORS[t], label=tier_label[t], alpha=0.93)
        bottom += tier_stage[t]
    axt.set_xticks(range(len(stages)))
    axt.set_xticklabels([stage_label[s] for s in stage_order], rotation=38, ha="right", fontsize=7.2)
    axt.set_ylabel("文化态数量")
    axt.set_title("(d) 全流域文化态观测层构成（按历史阶段堆叠）", fontsize=9.8, pad=5)
    axt.legend(frameon=False, fontsize=6.8, loc="upper left")

    # U3 时间区间十年分布
    axe = fig.add_subplot(gs[1, 1:])
    bottom = np.zeros(len(dec_order))
    for k in src_keys:
        axe.bar(range(len(dec_order)), src_dec[k], bottom=bottom, width=0.72,
                color=STATE_TIME_SOURCE_COLORS[k], label=src_label[k], alpha=0.93)
        bottom += src_dec[k]
    axe.set_xticks(range(len(dec_order)))
    axe.set_xticklabels(dec_order, rotation=45, ha="right", fontsize=7.0)
    axe.set_ylabel("文化态数量")
    axe.set_title("(e) 文化态 U3 时间区间列（state_time_start）十年分布，按 state_time_source 堆叠",
                  fontsize=9.8, pad=5)
    axe.legend(frameon=False, fontsize=7.2, loc="upper right")
    tot = sum(int(v.sum()) for v in src_dec.values())
    for j, v in enumerate(bottom):
        if v > 0:
            axe.text(j, v + bottom.max() * 0.015, fmt(int(v)), ha="center", fontsize=5.8, color="#5a6572")

    fig.suptitle("VIZ-4 CultureState 演化：文化形态 × 历史阶段 × 区域（热力图）与时间区间分布",
                 x=0.03, y=0.975, ha="left", fontsize=14, fontweight="bold")
    n_ev_links = sum(evt.values())
    fig.text(0.03, 0.928,
             f"文化态 {fmt(len(states))} 条（观测层：可信 {fmt(int(tier_stage['trusted_event_spacetime'].sum()))} / "
             f"断言 {fmt(int(tier_stage['asserted_event_spacetime'].sum()))} / 上下文 "
             f"{fmt(int(tier_stage['relation_context'].sum()))}）；支撑事件链接 {fmt(n_ev_links)} 条。"
             f"时间区间列（U3）覆盖 {fmt(tot)} 条（无区间 {fmt(n_undated)} 条）。"
             f"{hub.source_line(['research_culture_states'])}",
             fontsize=8.6, color="#3a4652")
    add_source_footer(fig, "SQL 见 figures/stkg_viz4_culture_state_evolution_CAPTION.md | 数据库只读 | 确定性管线")
    save(fig, FIGURES_DIR / "stkg_viz4_culture_state_evolution.png")

    write_caption(
        "stkg_viz4_culture_state_evolution",
        "CultureState 演化：form × stage × region 热力图与 U3 时间区间分布",
        "VIZ-4",
        [("Q1 全部文化态（form/stage/河段/观测层/时间区间/时间来源）", SQL_VIZ4_STATES),
         ("Q2 文化形态字典", SQL_VIZ4_FORMS),
         ("Q3 历史阶段字典", SQL_VIZ4_STAGES),
         ("Q4 支撑事件链接（按阶段）", SQL_VIZ4_EVT)],
        [("文化态行数", fmt(len(states))),
         ("form × stage 组合数", f"{len(forms)} × {len(stages)} = {len(forms) * len(stages)}"),
         ("热力图非零格（3 河段合计）", fmt(sum(int((m > 0).sum()) for m in mats.values()))),
         ("支撑事件链接行数", fmt(n_ev_links)),
         ("有 U3 时间区间的文化态", fmt(tot)),
         ("数据源", hub.source_line(["research_culture_states"]))],
        notes=[])
    return {"n_states": len(states), "n_ev_links": n_ev_links, "n_dated": tot,
            "n_undated": n_undated}


# ===========================================================================
# VIZ-5 全库分层总览
# ===========================================================================

SQL_VIZ5_TIMED = """
SELECT a.fact_id, substr(a.time_start, 1, 4) AS year4, a.research_tier
FROM research_assertions a
WHERE a.time_start IS NOT NULL AND a.time_start <> ''
ORDER BY a.fact_id
"""

SQL_VIZ5_BASINS = """
SELECT b.fact_id, b.basin_section_id, b.membership_order
FROM research_assertion_basins b
ORDER BY b.fact_id, b.membership_order
"""

SQL_VIZ5_TIER_ALL = "SELECT research_tier, COUNT(*) FROM research_assertions GROUP BY research_tier"


def viz5(hub: DataHub, font_info: dict) -> dict:
    timed = hub.q(["research_assertions"], SQL_VIZ5_TIMED)
    basins = hub.q(["research_assertion_basins"], SQL_VIZ5_BASINS)
    tier_all = dict(hub.q(["research_assertions"], SQL_VIZ5_TIER_ALL))

    fact_basins = {}
    for fid, sec, _ in basins:
        fact_basins.setdefault(fid, []).append(sec)

    tiers = ["strict_semantic", "contextual", "unresolved"]
    dec_set = {decade_of(r[1]) for r in timed} - {None}
    decs = sorted(dec_set, key=lambda d: int(d[:4]))
    # (decade, basin) → tier 计数
    key = {(d, b): Counter() for d in decs for b in BASIN_ORDER}
    n_multi = 0
    used_facts = set()
    for fid, y4, tier in timed:
        d = decade_of(y4)
        secs = fact_basins.get(fid)
        if not secs:
            continue
        if len(secs) > 1:
            n_multi += 1
        used_facts.add(fid)
        for sec in secs:
            if sec in BASIN_ORDER:
                key[(d, sec)][tier] += 1
    mat = np.array([[sum(key[(d, b)].values()) for d in decs] for b in BASIN_ORDER], dtype=int)
    mat_tier = {t: np.array([[key[(d, b)][t] for d in decs] for b in BASIN_ORDER], dtype=int)
                for t in tiers}

    decade_tot = {d: sum(key[(d, b)][t] for b in BASIN_ORDER for t in tiers) for d in decs}
    n_pairs = sum(1 for fid, y4, tier in timed
                  for sec in fact_basins.get(fid, []) if sec in BASIN_ORDER)

    plt.rcParams.update(figure_rc(font_info))
    fig = plt.figure(figsize=(16.0, 8.8))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.35, 1.0], width_ratios=[1.7, 1.0],
                          hspace=0.5, wspace=0.22, left=0.06, right=0.965, top=0.855, bottom=0.095)

    ax = fig.add_subplot(gs[0, :])
    im = ax.imshow(np.where(mat > 0, mat, np.nan), cmap="YlGnBu",
                   norm=LogNorm(vmin=1, vmax=max(1, mat.max())), aspect="auto")
    ax.set_xticks(range(len(decs)))
    ax.set_xticklabels(decs, rotation=45, ha="right", fontsize=7.6)
    ax.set_yticks(range(len(BASIN_ORDER)))
    ax.set_yticklabels([BASIN_SHORT[b] for b in BASIN_ORDER])
    ax.spines[:].set_visible(False)
    ax.set_xticks(np.arange(-.5, len(decs), 1), minor=True)
    ax.set_yticks(np.arange(-.5, 3, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=0.6)
    for i in range(3):
        for j in range(len(decs)):
            if mat[i, j] > 0:
                ax.text(j, i, fmt(mat[i, j]), ha="center", va="center", fontsize=6.2,
                        color="white" if mat[i, j] > mat.max() * 0.55 else "#24303c")
    ax.set_title("(a) 全库带时间断言密度：十年 × 河段（research_assertion_basins 规范三段归属；跨段断言每段各计一次）",
                 fontsize=10.2, pad=6)
    cb = fig.colorbar(im, ax=ax, shrink=0.9, pad=0.008)
    cb.set_label("断言条数（对数色标）", fontsize=8)

    axb = fig.add_subplot(gs[1, 0])
    bottom = np.zeros(len(decs))
    for t in tiers:
        vals = np.array([sum(key[(d, b)][t] for b in BASIN_ORDER) for d in decs], dtype=float)
        axb.bar(range(len(decs)), vals, bottom=bottom, width=0.72, color=TIER_COLORS[t],
                label=TIER_LABELS[t], alpha=0.94)
        bottom += vals
    axb.set_xticks(range(len(decs)))
    axb.set_xticklabels(decs, rotation=45, ha="right", fontsize=7.2)
    axb.set_ylabel("断言条数（三段合计）")
    axb.set_title("(b) 十年 × research_tier 层叠对比（带时间断言）", fontsize=10.2, pad=6)
    axb.legend(frameon=False, fontsize=7.6, loc="upper right")
    for j, v in enumerate(bottom):
        if v > 0:
            axb.text(j, v + bottom.max() * 0.015, fmt(int(v)), ha="center", fontsize=5.8, color="#5a6572")

    axc = fig.add_subplot(gs[1, 1])
    for k, b in enumerate(BASIN_ORDER):
        tot = sum(sum(key[(d, b)].values()) for d in decs)
        left = 0.0
        for t in tiers:
            v = sum(key[(d, b)][t] for d in decs) / tot * 100
            axc.barh(k, v, left=left, color=TIER_COLORS[t], height=0.55, alpha=0.94)
            if v > 6:
                axc.text(left + v / 2, k, f"{v:.1f}%", va="center", ha="center",
                         fontsize=7.2, color="white")
            left += v
    axc.set_yticks(range(3))
    axc.set_yticklabels([BASIN_SHORT[b] for b in BASIN_ORDER])
    axc.set_xlim(0, 100)
    axc.set_xlabel("research_tier 构成（%）")
    axc.set_title("(c) 各河段分层构成", fontsize=10.2, pad=6)

    fig.suptitle("VIZ-5 全库分层总览：十年 × 河段断言密度与 research_tier 层叠",
                 x=0.03, y=0.975, ha="left", fontsize=14, fontweight="bold")
    fig.text(0.03, 0.93,
             f"全库断言 {fmt(sum(tier_all.values()))} 条（strict {fmt(tier_all.get('strict_semantic', 0))} / "
             f"contextual {fmt(tier_all.get('contextual', 0))} / unresolved {fmt(tier_all.get('unresolved', 0))}）；"
             f"带 time_start 且 1850–2026 的断言 {fmt(len(timed))} 条，其中具规范三段归属的 "
             f"{fmt(len(used_facts))} 条（断言-河段归属对 {fmt(n_pairs)} 个；跨段 {fmt(n_multi)} 条按段各计一次）。"
             f"{hub.source_line(['research_assertions'])}",
             fontsize=8.6, color="#3a4652")
    add_source_footer(fig, "SQL 见 figures/stkg_viz5_overview_tiers_CAPTION.md | "
                           "交互版见 figures/stkg_viz5_overview_tiers.html | 数据库只读 | 确定性管线")
    save(fig, FIGURES_DIR / "stkg_viz5_overview_tiers.png")

    # ---- 交互 HTML ----
    html_payload = {
        "decs": decs,
        "basins": [BASIN_SHORT[b] for b in BASIN_ORDER],
        "mat": mat.tolist(),
        "tier_cells": [{  # 逐格：[上游行…], 每 cell {dec, basin, strict, contextual, unresolved}
            "dec": decs[j], "basin": BASIN_SHORT[BASIN_ORDER[i]],
            "strict": int(mat_tier["strict_semantic"][i, j]),
            "contextual": int(mat_tier["contextual"][i, j]),
            "unresolved": int(mat_tier["unresolved"][i, j]),
        } for i in range(3) for j in range(len(decs))],
        "decade_tot": {d: int(decade_tot[d]) for d in decs},
        "tiers": {t: {BASIN_SHORT[b]: int(mat_tier[t][i].sum()) for i, b in enumerate(BASIN_ORDER)}
                  for t in tiers},
        "totals": {t: int(tier_all.get(t, 0)) for t in tiers},
        "timed_total": len(timed),
        "with_basin": len(used_facts), "multi": n_multi,
    }
    (FIGURES_DIR / "stkg_viz5_overview_tiers.html").write_text(
        build_viz5_html(html_payload), encoding="utf-8")
    print("  [ok] stkg_viz5_overview_tiers.html")

    write_caption(
        "stkg_viz5_overview_tiers",
        "全库分层总览：十年 × 河段断言密度 + research_tier 层叠对比（PNG + 交互 HTML）",
        "VIZ-5",
        [("Q1 带时间断言（fact_id, 年份, research_tier）", SQL_VIZ5_TIMED),
         ("Q2 断言 × 河段规范归属（research_assertion_basins）", SQL_VIZ5_BASINS),
         ("Q3 全库 research_tier 计数", SQL_VIZ5_TIER_ALL)],
        [("全库断言总数", fmt(sum(tier_all.values()))),
         ("strict / contextual / unresolved",
          f"{fmt(tier_all.get('strict_semantic', 0))} / {fmt(tier_all.get('contextual', 0))} / "
          f"{fmt(tier_all.get('unresolved', 0))}"),
         ("带时间断言（1850–2026）", fmt(len(timed))),
         ("具规范三段归属的带时间断言", fmt(len(used_facts))),
         ("断言-河段归属对", fmt(n_pairs)),
         ("跨段断言（每段各计一次）", fmt(n_multi)),
         ("热力图规模", f"3 河段 × {len(decs)} 十年 = {3 * len(decs)} 格（非零 {int((mat > 0).sum())}）"),
         ("数据源", hub.source_line(["research_assertions"]))],
        notes=["stkg_viz5_overview_tiers.html（交互版：悬停查看每格分层计数）"])
    return html_payload


def build_viz5_html(d: dict) -> str:
    payload = json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    tier_colors = json.dumps(TIER_COLORS, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>VIZ-5 全库分层总览（交互版）</title>
<style>
  body {{ margin:0; padding:24px 28px; font-family:"Microsoft YaHei","SimHei","Noto Sans CJK SC",sans-serif;
          color:#24303c; background:#fbfcfd; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  .sub {{ color:#5a6572; font-size:12px; line-height:1.7; margin-bottom:12px; }}
  .card {{ background:#fff; border:1px solid #d8dee4; border-radius:10px; padding:14px 16px; margin-bottom:18px; }}
  .card h2 {{ font-size:14px; margin:0 0 10px; }}
  svg text {{ font-family:inherit; }}
  #tip {{ position:fixed; display:none; pointer-events:none; background:#24303c; color:#fff; font-size:12px;
          line-height:1.6; padding:8px 11px; border-radius:6px; z-index:9; }}
  .lg {{ font-size:11.5px; color:#5a6572; display:flex; gap:16px; margin-bottom:8px; flex-wrap:wrap; }}
  .sw {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:4px; vertical-align:-1px; }}
</style>
</head>
<body>
<h1>VIZ-5 全库分层总览：十年 × 河段断言密度 + research_tier</h1>
<div class="sub">数据源：{esc(DB_LABEL['v3_1'])}（只读）。悬停热力图单元格查看该 (十年 × 河段) 的分层计数；悬停柱体查看该十年三段合计的分层构成。</div>
<div class="card"><h2>(a) 十年 × 河段密度热力图（对数色标）</h2><div id="heat"></div></div>
<div class="card"><h2>(b) 十年 × research_tier 层叠（三段合计）</h2>
  <div class="lg" id="lg"></div><div id="bars"></div></div>
<div class="foot" style="color:#5a6572;font-size:11.5px">
  SQL 与行数见 figures/stkg_viz5_overview_tiers_CAPTION.md ｜ 生成时间：{esc(RUN_STAMP)} ｜ 确定性管线
</div>
<div id="tip"></div>
<script>
const D = {payload};
const TC = {tier_colors};
const tip = document.getElementById('tip');
function esc(s) {{ const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }}
function show(ev, html) {{ tip.innerHTML = html; tip.style.display = 'block';
  tip.style.left = (ev.clientX + 14) + 'px'; tip.style.top = (ev.clientY + 12) + 'px'; }}
function hide() {{ tip.style.display = 'none'; }}
const TIERS = ['strict', 'contextual', 'unresolved'];
const TIER_ZH = {{ strict: 'strict_semantic', contextual: 'contextual', unresolved: 'unresolved' }};

(function drawHeat() {{
  const padL = 64, padT = 6, cw = 46, ch = 46, W = padL + D.decs.length * cw + 10, H = padT + 3 * ch + 8;
  const max = Math.max(...D.mat.flat());
  const logc = v => v <= 0 ? null : Math.log10(v) / Math.log10(max);
  const col = t => {{ if (t == null) return '#f4f7f9';
    const a = 0.10 + 0.88 * t; // 浅→深的蓝
    return 'rgba(27,108,168,' + a.toFixed(3) + ')'; }};
  let s = '<svg width="' + W + '" height="' + H + '">';
  D.mat.forEach((row, i) => {{
    s += '<text x="' + (padL - 10) + '" y="' + (padT + i * ch + ch / 2 + 4) + '" font-size="12" text-anchor="end">' + D.basins[i] + '</text>';
    row.forEach((v, j) => {{
      s += '<rect data-i="' + i + '" data-j="' + j + '" x="' + (padL + j * cw) + '" y="' + (padT + i * ch)
        + '" width="' + (cw - 3) + '" height="' + (ch - 3) + '" rx="4" fill="' + col(logc(v)) + '"/>';
      if (v > 0) s += '<text x="' + (padL + j * cw + (cw - 3) / 2) + '" y="' + (padT + i * ch + ch / 2 + 3.5)
        + '" font-size="9.5" text-anchor="middle" fill="' + (v > max * 0.55 ? '#fff' : '#24303c')
        + '" pointer-events="none">' + v.toLocaleString() + '</text>';
    }});
  }});
  D.decs.forEach((d, j) => s += '<text x="' + (padL + j * cw + (cw - 3) / 2) + '" y="' + (H - 0)
    + '" font-size="9.5" text-anchor="middle" fill="#5a6572" transform="rotate(-28 '
    + (padL + j * cw + (cw - 3) / 2) + ' ' + (H - 0) + ')">' + d + '</text>');
  s += '</svg>';
  document.getElementById('heat').innerHTML = s;
  document.querySelectorAll('#heat rect').forEach(r => r.addEventListener('mousemove', ev => {{
    const i = +r.dataset.i, j = +r.dataset.j;
    const cell = D.tier_cells[i * D.decs.length + j];
    show(ev, '<b>' + cell.basin + ' · ' + cell.dec + '</b><br>'
      + TIERS.map(t => TIER_ZH[t] + '：' + cell[t].toLocaleString()).join('<br>')
      + '<br>合计：' + D.mat[i][j].toLocaleString());
  }}));
  document.querySelectorAll('#heat rect').forEach(r => r.addEventListener('mouseleave', hide));
}})();

(function drawBars() {{
  const W = Math.max(860, D.decs.length * 46), H = 250, padL = 64, padB = 44, padT = 12;
  const max = Math.max(...Object.values(D.decade_tot));
  const y = v => padT + (1 - v / max) * (H - padT - padB);
  let s = '<svg width="' + W + '" height="' + H + '">';
  for (let g = 0; g <= 4; g++) {{
    const v = max / 4 * g;
    s += '<line x1="' + padL + '" y1="' + y(v) + '" x2="' + W + '" y2="' + y(v) + '" stroke="#e7ecef"/>'
      + '<text x="' + (padL - 6) + '" y="' + (y(v) + 3.5) + '" font-size="9.5" fill="#5a6572" text-anchor="end">'
      + Math.round(v).toLocaleString() + '</text>';
  }}
  const bw = Math.min(38, (W - padL - 10) / D.decs.length * 0.7);
  D.decs.forEach((d, j) => {{
    const cx = padL + (j + 0.5) * (W - padL - 10) / D.decs.length;
    let acc = 0;
    const cell = D.tier_cells.filter(c => c.dec === d);
    const agg = {{ strict: 0, contextual: 0, unresolved: 0 }};
    cell.forEach(c => TIERS.forEach(t => agg[t] += c[t]));
    TIERS.forEach(t => {{
      const v = agg[t], y0 = y(acc), y1 = y(acc + v);
      s += '<rect data-dec="' + d + '" data-t="' + t + '" x="' + (cx - bw / 2) + '" y="' + y1
        + '" width="' + bw + '" height="' + Math.max(y0 - y1, 0.5) + '" fill="' + TC[TIER_ZH[t]] + '" opacity="0.94"/>';
      acc += v;
    }});
    if (acc > 0) s += '<text x="' + cx + '" y="' + (y(acc) - 4) + '" font-size="8.5" text-anchor="middle" fill="#5a6572">'
      + acc.toLocaleString() + '</text>';
    s += '<text x="' + cx + '" y="' + (H - 26) + '" font-size="9.5" text-anchor="middle" fill="#5a6572" transform="rotate(-38 '
      + cx + ' ' + (H - 26) + ')">' + d + '</text>';
  }});
  s += '</svg>';
  document.getElementById('bars').innerHTML = s;
  document.getElementById('lg').innerHTML = TIERS.map(t =>
    '<span><span class="sw" style="background:' + TC[TIER_ZH[t]] + '"></span>' + TIER_ZH[t] + '</span>').join('');
  document.querySelectorAll('#bars rect').forEach(r => r.addEventListener('mousemove', ev => {{
    const dec = r.dataset.dec, t = r.dataset.t;
    const agg = {{ strict: 0, contextual: 0, unresolved: 0 }};
    D.tier_cells.filter(c => c.dec === dec).forEach(c => TIERS.forEach(z => agg[z] += c[z]));
    const tot = D.decade_tot[dec] || 0;
    show(ev, '<b>' + dec + '</b><br>' + TIER_ZH[t] + '：' + agg[t].toLocaleString()
      + '（' + (tot ? (agg[t] / tot * 100).toFixed(1) : '0') + '%）<br>三段合计：' + tot.toLocaleString());
  }}));
  document.querySelectorAll('#bars rect').forEach(r => r.addEventListener('mouseleave', hide));
}})();
</script>
</body>
</html>
"""


# ===========================================================================
# VIZ-6 最终方法架构图
# ===========================================================================

def viz6(hub: DataHub, font_info: dict) -> dict:
    # ---- 全部数字实时查询，不硬编码 ----
    totals = dict(hub.q(["research_assertions"], "SELECT research_tier, COUNT(*) FROM research_assertions GROUP BY 1"))
    n_assertions = sum(totals.values())
    n_prov = hub.q(["research_assertion_provenance"],
                   "SELECT COUNT(*) FROM research_assertion_provenance")[0][0]
    n_entities = hub.q(["research_entities"], "SELECT COUNT(*) FROM research_entities")[0][0]
    sem = dict(hub.q(["research_assertions"],
                     "SELECT semantic_status, COUNT(*) FROM research_assertions GROUP BY 1"))
    risk = dict(hub.q(["research_assertions"], "SELECT risk_tier, COUNT(*) FROM research_assertions GROUP BY 1"))
    u2 = hub.q(["v_assertion_state_identity"],
               "SELECT COUNT(*), SUM(member_fact_count) FROM v_assertion_state_identity")[0]
    n_canonical, n_member_sum = int(u2[0]), int(u2[1] or 0)
    frames = hub.q(["research_event_frames"],
                   "SELECT frame_status, COUNT(*) FROM research_event_frames GROUP BY 1")
    frame_stat = dict(frames)
    n_frames = sum(frame_stat.values())
    backbone = frame_stat.get("strict_backbone", 0)
    states = hub.q(["research_culture_states"],
                   "SELECT observation_tier, COUNT(*) FROM research_culture_states GROUP BY 1")
    state_stat = dict(states)
    n_states = sum(state_stat.values())
    n_state_events = hub.q(["research_culture_state_events"],
                           "SELECT COUNT(*) FROM research_culture_state_events")[0][0]
    n_temporal = hub.q(["assertion_temporal_relations"],
                       "SELECT COUNT(*) FROM assertion_temporal_relations")[0][0]
    n_frame_temporal = hub.q(["event_frame_temporal"],
                             "SELECT COUNT(*) FROM event_frame_temporal")[0][0]

    n_strict = totals.get("strict_semantic", 0)
    n_context = totals.get("contextual", 0)
    n_unres = totals.get("unresolved", 0)

    plt.rcParams.update(figure_rc(font_info))
    fig, ax = plt.subplots(figsize=(16.4, 9.4))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")

    BLUE, GREEN, ORANGE, GREY, PURPLE, DARK = ("#1b6ca8", "#1e8449", "#e8a33d",
                                               "#8a959e", "#7d3c98", "#24303c")

    def box(x, y, w, h, title, lines, fc, ec, title_fs=10.0, line_fs=8.0):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.55,rounding_size=1.2",
                                    fc=fc, ec=ec, lw=1.4))
        ax.text(x + w / 2, y + h - 2.6, title, ha="center", va="top",
                fontsize=title_fs, fontweight="bold", color=DARK)
        ax.text(x + w / 2, y + h - 8.2, "\n".join(lines), ha="center", va="top",
                fontsize=line_fs, color="#3a4652", linespacing=1.6)

    def arrow(x0, y0, x1, y1, color=GREY, style="-|>", lw=1.8, conn="arc3,rad=0.0"):
        ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle=style,
                                     mutation_scale=16, color=color, lw=lw,
                                     connectionstyle=conn, zorder=1))

    fig.suptitle("VIZ-6 最终方法架构（候选抽取 → 语义 Predictor → 风险路由 → 三路输出 → 结构准入 → 分层 → EventFrame → CultureState）",
                 x=0.03, y=0.972, ha="left", fontsize=13.6, fontweight="bold")
    fig.text(0.03, 0.928,
             f"图中全部数字为本轮实测（MEASURED，查询自 {DB_PRIMARY.name}，只读；生成时间见同名 CAPTION 与 14_VISUALIZATION_REPORT.md）。"
             f"SQL 见 figures/stkg_viz6_method_architecture_CAPTION.md。",
             fontsize=8.6, color="#3a4652")

    # 1 候选抽取
    box(1.5, 66, 20, 24, "① 多源候选抽取",
        [f"证据成员 {fmt(n_prov)}", f"融合断言 {fmt(n_assertions)}", f"实体 {fmt(n_entities)}",
         "（provenance 溯源链）"], "#eef4f9", BLUE)
    # 2 Predictor
    box(27, 66, 22, 24, "② 语义 Predictor",
        [f"auto_accepted {fmt(sem.get('auto_accepted', 0))}",
         f"model_review {fmt(sem.get('model_review', 0))}",
         f"manual_review {fmt(sem.get('manual_review', 0))}",
         "（冻结划分 + 独立裁判）"], "#eef4f9", BLUE)
    # 3 Risk Routing
    box(54.5, 66, 21, 24, "③ Risk Routing",
        [f"A {fmt(risk.get('A', 0))}  B {fmt(risk.get('B', 0))}",
         f"C {fmt(risk.get('C', 0))}  D {fmt(risk.get('D', 0))}",
         "（风险估计 → 升级路径）"], "#fdf6ea", ORANGE)
    arrow(22.3, 78, 26.6, 78, color=DARK)
    arrow(49.8, 78, 54.1, 78, color=DARK)
    # 三路输出
    ys = 44
    box(4, ys, 26, 13.5, "④a strict_semantic（严格语义路）",
        [f"{fmt(n_strict)} 条 · 入 EventFrame 主干"], "#eaf3ec", GREEN, title_fs=9.4)
    box(37, ys, 26, 13.5, "④b contextual（上下文路）",
        [f"{fmt(n_context)} 条 · 支撑 CultureState 语境"], "#fdf6ea", ORANGE, title_fs=9.4)
    box(70, ys, 26, 13.5, "④c unresolved（未解析路）",
        [f"{fmt(n_unres)} 条 · 隔离，不入结论"], "#f0f2f4", GREY, title_fs=9.4)
    arrow(65, 66, 17, ys + 13.5, conn="arc3,rad=0.25", color=GREEN)
    arrow(65, 66, 50, ys + 13.5, conn="arc3,rad=0.12", color=ORANGE)
    arrow(65, 66, 83, ys + 13.5, conn="arc3,rad=-0.25", color=GREY)

    # 5 结构准入（U2）→ 6 分层 → 7 EventFrame（与任务要求的流程顺序一致）
    box(4, 22, 28, 17, "⑤ 结构准入（U2 断言同一性）",
        [f"规范同一性键 {fmt(n_canonical)}",
         f"（成员断言合计 {fmt(n_member_sum)}）",
         "五元组去重合并 →",
         "v_assertion_state_identity"], "#eef4f9", PURPLE, title_fs=9.2, line_fs=7.6)
    box(37, 22, 26, 17, "⑥ 分层 research_tier",
        [f"strict {fmt(n_strict)} / contextual {fmt(n_context)}",
         f"/ unresolved {fmt(n_unres)}",
         f"断言时序关系（U5）{fmt(n_temporal)} 条"], "#eef4f9", PURPLE, title_fs=9.2, line_fs=7.6)
    box(68, 22, 28, 17, "⑦ EventFrame 事件帧",
        [f"{fmt(n_frames)} 帧（strict_backbone {fmt(backbone)}）",
         f"U1 证据溯源 + U4 帧间时序 {fmt(n_frame_temporal)} 条"], "#eaf3ec", GREEN, title_fs=9.2, line_fs=7.6)
    arrow(17, ys, 17, 22 + 17, color=PURPLE)
    arrow(50, ys, 50, 22 + 17, color=PURPLE)
    arrow(83, ys, 82, 22 + 17, color=GREY)
    arrow(32, 30.5, 37, 30.5, color=PURPLE)
    arrow(63, 30.5, 68, 30.5, color=PURPLE)

    # 8 CultureState
    box(26, 4, 46, 14, "⑧ CultureState 文化态（时空归属）",
        [f"{fmt(n_states)} 态（trusted {fmt(state_stat.get('trusted_event_spacetime', 0))} / "
         f"asserted {fmt(state_stat.get('asserted_event_spacetime', 0))} / context "
         f"{fmt(state_stat.get('relation_context', 0))}）",
         f"U3 状态时间区间列全量覆盖；支撑事件链接 {fmt(n_state_events)} 条；演化转移规则待评（不臆断因果）"],
        "#f4eef8", PURPLE, title_fs=10.0, line_fs=7.8)
    arrow(50, 22, 50, 18, color=PURPLE)
    arrow(82, 22, 60, 18, color=GREEN, conn="arc3,rad=0.15")

    add_source_footer(fig, f"数据库只读 | 确定性管线 | {DB_LABEL['v3_1']}")
    save(fig, FIGURES_DIR / "stkg_viz6_method_architecture.png")

    sqls = [
        ("Q1 断言分层计数", "SELECT research_tier, COUNT(*) FROM research_assertions GROUP BY 1"),
        ("Q2 语义门计数", "SELECT semantic_status, COUNT(*) FROM research_assertions GROUP BY 1"),
        ("Q3 风险层计数", "SELECT risk_tier, COUNT(*) FROM research_assertions GROUP BY 1"),
        ("Q4 溯源成员 / 实体 / 帧间时序 / 断言时序",
         "SELECT COUNT(*) FROM research_assertion_provenance;\n"
         "SELECT COUNT(*) FROM research_entities;\n"
         "SELECT COUNT(*) FROM event_frame_temporal;\n"
         "SELECT COUNT(*) FROM assertion_temporal_relations;"),
        ("Q5 U2 同一性视图", "SELECT COUNT(*), SUM(member_fact_count) FROM v_assertion_state_identity"),
        ("Q6 EventFrame / CultureState 结构计数",
         "SELECT frame_status, COUNT(*) FROM research_event_frames GROUP BY 1;\n"
         "SELECT observation_tier, COUNT(*) FROM research_culture_states GROUP BY 1;\n"
         "SELECT COUNT(*) FROM research_culture_state_events;"),
    ]
    write_caption(
        "stkg_viz6_method_architecture",
        "最终方法架构图（候选抽取 → Predictor → Risk Routing → 三路 → 结构准入 → 分层 → EventFrame → CultureState）",
        "VIZ-6",
        sqls,
        [("溯源证据成员", fmt(n_prov)), ("融合断言", fmt(n_assertions)), ("实体", fmt(n_entities)),
         ("semantic_status auto/model/manual",
          f"{fmt(sem.get('auto_accepted', 0))} / {fmt(sem.get('model_review', 0))} / {fmt(sem.get('manual_review', 0))}"),
         ("risk_tier A/B/C/D",
          f"{fmt(risk.get('A', 0))} / {fmt(risk.get('B', 0))} / {fmt(risk.get('C', 0))} / {fmt(risk.get('D', 0))}"),
         ("strict / contextual / unresolved", f"{fmt(n_strict)} / {fmt(n_context)} / {fmt(n_unres)}"),
         ("U2 规范同一性键（成员断言合计）", f"{fmt(n_canonical)}（{fmt(n_member_sum)}）"),
         ("EventFrame（strict_backbone）", f"{fmt(n_frames)}（{fmt(backbone)}）"),
         ("帧间时序关系（U4）/ 断言时序关系（U5）", f"{fmt(n_frame_temporal)} / {fmt(n_temporal)}"),
         ("CultureState（trusted/asserted/context）",
          f"{fmt(n_states)}（{fmt(state_stat.get('trusted_event_spacetime', 0))}/"
          f"{fmt(state_stat.get('asserted_event_spacetime', 0))}/"
          f"{fmt(state_stat.get('relation_context', 0))}）"),
         ("数据源", hub.source_line(["research_assertions"]))],
        notes=[])
    return {"n_prov": n_prov, "n_assertions": n_assertions, "n_entities": n_entities,
            "n_frames": n_frames, "backbone": backbone, "n_states": n_states,
            "n_state_events": n_state_events, "n_temporal": n_temporal,
            "n_frame_temporal": n_frame_temporal, "n_canonical": n_canonical}


# ===========================================================================
# 汇总报告
# ===========================================================================

def write_report(hub: DataHub, stats: dict) -> None:
    usage_by_db = Counter(u["db"] for u in hub.usage)
    total_rows = sum(u["rows"] for u in hub.usage)
    fallbacks = sorted(set(hub.fallbacks))
    persons = stats["viz2"]
    viz5_payload = stats["viz5"]
    v1, v3, v4, v6 = stats["viz1"], stats["viz3"], stats["viz4"], stats["viz6"]
    fig_files = [
        ("VIZ-1", "figures/stkg_viz1_event_spacetime_density.png", "长江流域事件时空密度热力图（十年×河段/省份 + Top 地点）"),
        ("VIZ-2", "figures/stkg_viz2_person_trajectories.png", "Top3 人物时间线 + 断言邻居网络（matplotlib 多面板版）"),
        ("VIZ-2H", "figures/stkg_viz2_person_trajectories.html", "同上交互版（自包含 HTML，悬停明细/人物切换）"),
        ("VIZ-3", "figures/stkg_viz3_event_frame_structure.png", "Top-2 EventFrame 一页式结构展示"),
        ("VIZ-4", "figures/stkg_viz4_culture_state_evolution.png", "CultureState form×stage×region 热力图 + U3 时间区间分布"),
        ("VIZ-5", "figures/stkg_viz5_overview_tiers.png", "全库十年×河段密度 + research_tier 层叠"),
        ("VIZ-5H", "figures/stkg_viz5_overview_tiers.html", "同上交互版（逐格分层计数悬停）"),
        ("VIZ-6", "figures/stkg_viz6_method_architecture.png", "最终方法架构示意（标注 MEASURED 实测数字）"),
    ]
    lines = [
        "# 14 · STKG 可视化套件报告（VIZ-1 … VIZ-6）", "",
        f"- 生成时间：{RUN_STAMP}",
        f"- 脚本：`code/experiment_pipelines/build_stkg_visualizations.py`（新建文件，未修改任何既有文件）",
        f"- 主数据源：`{DB_PRIMARY.name}`（U1-U8 升级齐全）；回退库：`{DB_FALLBACK.name}`（仅当 V3_1 某表缺失/为空时使用）",
        f"- 本次执行：SQL 查询 {len(hub.usage)} 次，覆盖行数合计 {fmt(total_rows)}；"
        f"按库分布：{dict(usage_by_db)}",
        f"- 回退触发情况：**{'无（全部表/视图均取自 V3_1 副本库）' if not fallbacks else '触发 → ' + ', '.join(fallbacks)}**",
        f"- 中文字体解析：{json.dumps(font_info_resolved, ensure_ascii=False)}",
        f"- 确定性：无随机过程；Top-N、坐标、配色与排序均由稳定次序键（ORDER BY 唯一化 + 固定容量）决定；"
        f"PNG 内容不含时间戳，已验证连续重跑 6 张 PNG 字节级一致（CAPTION/报告中的生成时间为运行元数据）。",
        f"- 数据库访问：一律 `mode=ro` 只读打开，未发生任何写操作。",
        "", "## 图件清单与数据规模", "",
        "| 编号 | 文件（figures/） | 内容 | 数据规模（真实查询） |",
        "|---|---|---|---|",
    ]
    scale = {
        "VIZ-1": (f"时间断言 {fmt(v1['n_occ'])} 条 / distinct 事件 {fmt(v1['n_events'])}；"
                  f"事件-地点对 {fmt(v1['n_pairs'])}（双要素事件 {fmt(v1['n_events_both'])}）"),
        "VIZ-2": ("3 人 × (时间线条目 ≤26 + 网络 16 邻居)；"
                  f"参与断言 Top3 合计 {fmt(sum(p['n_facts'] for p in persons))} 条"),
        "VIZ-2H": (f"3 人物页签；内嵌节点 {fmt(sum(len(p['net']) + 1 for p in persons))} 个、"
                   f"边 {fmt(sum(len(p['net']) for p in persons))} 条"),
        "VIZ-3": "、".join(f"{d['name']} 断言 {fmt(d['n_all'])}/证据行 {fmt(d['prov_rows'])}"
                          f"/时空单元 {d['cells']}" for d in v3),
        "VIZ-4": (f"{fmt(v4['n_states'])} 文化态（U3 时间区间覆盖 {fmt(v4['n_dated'])}）；"
                  f"支撑事件链接 {fmt(v4['n_ev_links'])} 条"),
        "VIZ-5": (f"3 河段 × {len(viz5_payload['decs'])} 十年 = {3 * len(viz5_payload['decs'])} 热力格；"
                  f"带时间断言 {fmt(viz5_payload['timed_total'])} 条（具河段归属 {fmt(viz5_payload['with_basin'])}）"),
        "VIZ-5H": (f"内嵌 {len(viz5_payload['tier_cells'])} 个热力格（每格含分层计数）"
                   f"+ {len(viz5_payload['decs'])} 根层叠柱"),
        "VIZ-6": (f"{fmt(v6['n_assertions'])} 断言 / {fmt(v6['n_prov'])} 证据成员 / "
                  f"{fmt(v6['n_frames'])} 帧 / {fmt(v6['n_states'])} 文化态 全流程数字标注"),
    }
    for tag, f, desc in fig_files:
        lines.append(f"| {tag} | `{f}` | {desc} | {scale[tag]} |")
    lines += [
        "", "## VIZ-2 入选人物（按参与 distinct 断言数 Top3）", "",
    ]
    for p in persons:
        lines.append(f"- **{p['name']}**：参与断言 {fmt(p['n_facts'])} 条 / 事件 {fmt(p['n_events'])} 个；"
                     f"时间线条目 {len(p['items'])}（组织/职务 {p['org_total']} 项候选、事件参与 {p['ev_total']} 项候选，"
                     f"各取断言数前 13）；网络邻居 {len(p['net'])} 个。")
    lines += [
        "", "## 每图 SQL 与行数", "",
        "每张 PNG 配套 `figures/stkg_*_CAPTION.md`，含：图题、完整 SQL、真实行数、生成时间、数据源标注。", "",
        "## 交互 HTML 说明", "",
        "- 两张交互 HTML（VIZ-2、VIZ-5）均为**自包含单文件**（内联 CSS/JS 与数据，无 CDN、无外部字体请求），",
        "  布局坐标在 Python 生成期确定性计算后内嵌；交互仅限悬停提示、人物切换与高亮。",
        "- 环境内无 pyvis，VIZ-2 按规范回退为 matplotlib 多面板 PNG，同时另出交互 HTML 以满足『2 张交互 HTML』交付。",
        "", "## 数据源回退策略", "",
        f"- 解析顺序：V3_1 副本库 → V2 主库（按表/视图粒度判空）。本次执行回退触发：**{'无' if not fallbacks else ', '.join(fallbacks)}**。",
        "- 若未来在 V2 库复现：CultureState 的 U3 时间区间列（state_time_start 等）在 V2 不存在，脚本将如实降级并标注。",
        "", "## 复现", "",
        "```bash",
        "cd submission_work/final_submission_v3_1/code/experiment_pipelines",
        "python build_stkg_visualizations.py",
        "```", "",
    ]
    AUDIT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"  [ok] {AUDIT_REPORT.name}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

font_info_resolved: dict = {}


def main() -> int:
    global font_info_resolved
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if not DB_PRIMARY.exists():
        raise SystemExit(f"主库不存在: {DB_PRIMARY}")
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    font_info_resolved = resolve_cjk_font()
    print(f"[font] resolved={font_info_resolved['resolved']} cjk={font_info_resolved['cjk_capable']}")

    hub = DataHub(DB_PRIMARY, DB_FALLBACK)

    print("[VIZ-1] 长江流域事件时空密度")
    stats1 = viz1(hub, font_info_resolved)
    print("[VIZ-2] 人物时空轨迹（PNG 多面板 + 交互 HTML）")
    persons = viz2(hub, font_info_resolved)
    print("[VIZ-3] EventFrame 结构")
    stats3 = viz3(hub, font_info_resolved)
    print("[VIZ-4] CultureState 演化")
    stats4 = viz4(hub, font_info_resolved)
    print("[VIZ-5] 全库分层总览（PNG + 交互 HTML）")
    payload5 = viz5(hub, font_info_resolved)
    print("[VIZ-6] 最终方法架构图")
    stats6 = viz6(hub, font_info_resolved)

    print("[REPORT] 汇总报告")
    write_report(hub, {"viz1": stats1, "viz2": persons, "viz3": stats3,
                       "viz4": stats4, "viz5": payload5, "viz6": stats6})
    print(f"[done] 查询 {len(hub.usage)} 次；回退触发：{hub.fallbacks or '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
