# -*- coding: utf-8 -*-
"""批A_语料规模.py — 批次A：语料与基础数据 14 张（A01–A14）"""
import sys; sys.path.insert(0, r'D:\REDCULTUREDATA\可视化输出\10_生成脚本')
from style_lib import *
import pandas as pd, numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, LogNorm
from matplotlib.patches import Rectangle, FancyArrowPatch

MID_DIR = MID
def L(name):
    return pd.read_csv(os.path.join(MID_DIR, name), encoding='utf-8-sig')

cmap_blue = LinearSegmentedColormap.from_list('blue', BLUE_SEQ)
cmap_green = LinearSegmentedColormap.from_list('green', GREEN_SEQ)
cmap_sand = LinearSegmentedColormap.from_list('sand', SAND_SEQ)

# 十三省（T39 定义）
t39 = L('T39_十三省域定义.csv')
PROV13 = list(t39.sort_values('顺序')['省份'])
t01 = L('T01_省域断言统计.csv')
t01s = t01[t01['省份'].isin(PROV13)].copy()          # 单省 13 行
SRC1 = 'T01_省域断言统计.csv'

def foot(fig, txt):
    fig.text(0.01, 0.012, '数据源：' + txt, fontsize=8, color=FAINT)

# ================= A01 十三省域断言总量分布（矩形示意地图） =================
fig, ax = new_fig(7.6, 6.4)
vals = dict(zip(t01s['省份'], t01s['断言总数']))
vmax = max(vals.values()); vmin = min(vals.values())
norm = lambda v: ((v / vmax) ** 0.35)          # 幂律拉伸避免小值不可见
layout = [('上海市', 0, 0), ('江苏省', 1, 0), ('浙江省', 2, 0), ('安徽省', 3, 0),
          ('江西省', 0, 1), ('湖北省', 1, 1), ('湖南省', 2, 1), ('重庆市', 3, 1),
          ('四川省', 0, 2), ('贵州省', 1, 2), ('云南省', 2, 2), ('西藏自治区', 3, 2),
          ('青海省', 0, 3)]
for prov, cx, cy in layout:
    v = vals[prov]
    ax.add_patch(Rectangle((cx + .06, 3 - cy + .06), .88, .88,
                           facecolor=cmap_blue(0.12 + 0.88 * norm(v)), edgecolor='white', lw=2))
    ax.text(cx + .5, 3 - cy + .58, prov.replace('省', '').replace('市', '').replace('自治区', ''),
            ha='center', va='center', fontsize=13, color=INK, fontweight='bold')
    ax.text(cx + .5, 3 - cy + .32, f"{v:,}", ha='center', va='center', fontsize=10.5, color=INK)
sm = plt.cm.ScalarMappable(cmap=cmap_blue, norm=plt.Normalize(vmin, vmax))
cbar = fig.colorbar(sm, ax=ax, shrink=.62, pad=.02)
cbar.set_label('断言总数（色标经幂律拉伸）', fontsize=9.5)
cbar.ax.tick_params(labelsize=8.5); cbar.outline.set_visible(False)
ax.set_xlim(-.1, 4.1); ax.set_ylim(-.15, 4.05)
ax.axis('off')
ax.set_title('A01 十三省域断言总量分布', loc='left', pad=14)
ax.text(0, 3.98, '贵州、四川、云南构成第一梯队；下游沪苏断言密度集中于近现代史料',
        fontsize=10, color=FAINT)
foot(fig, 'T01_省域断言统计.csv（单省13行，跨省组合行已剔除）｜示意布局，非精确地理边界')
save_fig(fig, 'A01', '十三省域断言总量分布', '语料与基础', '批A_语料规模.py',
         [SRC1], '贵州省10,503条居首，青海（39）与西藏（25）为量级最小省域；跨省组合断言另计')

# ================= A02 省域断言数量排名（横向条形） =================
d = t01s.sort_values('断言总数')
fig, ax = new_fig(7.2, 4.9)
cols = [cmap_blue(0.25 + 0.7 * (v / t01s['断言总数'].max())) for v in d['断言总数']]
ax.barh([p.replace('省', '').replace('市', '').replace('自治区', '') for p in d['省份']],
        d['断言总数'], color=cols, height=.68, zorder=3)
for y, v in enumerate(d['断言总数']):
    ax.text(v + 130, y, f"{v:,}", va='center', fontsize=9, color=INK)
ax.set_xlim(0, t01s['断言总数'].max() * 1.16)
despine(ax); light_grid(ax, 'x')
ax.set_xlabel('断言总数（条）'); ax.set_title('A02 省域断言数量排名', loc='left')
foot(fig, SRC1 + '（单省13行）')
save_fig(fig, 'A02', '省域断言数量排名', '语料与基础', '批A_语料规模.py',
         [SRC1], '省域断言量呈上游>中游>下游的梯度，贵州至上海跨越两个数量级')

# ================= A03 省域三层知识状态构成（百分比堆叠横条） =================
d = t01s.copy()
d['tot'] = d['断言总数']
for c, k in [('严格层', 'STRICT'), ('上下文层', 'CONTEXTUAL'), ('未决层', 'UNRESOLVED')]:
    d[c + 'p'] = d[c] / d['tot'] * 100
d = d.sort_values('严格层p')
fig, ax = new_fig(7.6, 5.2)
names = [p.replace('省', '').replace('市', '').replace('自治区', '') for p in d['省份']]
left = np.zeros(len(d))
for c, k in [('严格层', 'STRICT'), ('上下文层', 'CONTEXTUAL'), ('未决层', 'UNRESOLVED')]:
    ax.barh(names, d[c + 'p'], left=left, color=TIER_C[k], height=.68,
            label=TIER_ZH[k] + f'（{k}）', zorder=3)
    for y, (v, l) in enumerate(zip(d[c + 'p'], left)):
        if v > 6.5:
            ax.text(l + v / 2, y, f"{v:.1f}", ha='center', va='center', fontsize=8,
                    color='white' if k != 'UNRESOLVED' else INK)
    left += d[c + 'p'].values
ax.set_xlim(0, 100); ax.set_xlabel('占该省断言比例（%）')
ax.legend(loc='lower right', ncol=3, fontsize=9)
despine(ax); light_grid(ax, 'x')
ax.set_title('A03 省域三层知识状态构成', loc='left')
foot(fig, SRC1 + '（单省13行）')
save_fig(fig, 'A03', '省域三层知识状态构成', '语料与基础', '批A_语料规模.py',
         [SRC1], '各省均以上下文层为主体（80%上下），严格层占比最高为江西省4.4%')

# ================= A04 资料系列收录规模（棒棒糖） =================
e20 = L('E20_论文表1_资料列表.csv').sort_values('册数')
fig, ax = new_fig(7.2, 4.4)
ax.hlines(e20['资料系列'], 0, e20['册数'], color=AXIS, lw=1.6, zorder=2)
ax.scatter(e20['册数'], e20['资料系列'], s=110, color=M['雾蓝'], zorder=3)
for y, (v, unit) in enumerate(zip(e20['册数'], e20['收录规模'])):
    ax.text(v + 1.1, y, f"{v}（{unit}）", va='center', fontsize=9, color=INK)
ax.set_xlim(0, e20['册数'].max() * 1.3)
despine(ax); light_grid(ax, 'x')
ax.set_xlabel('收录册（卷/期/辑）数')
ax.set_title('A04 资料系列收录规模', loc='left')
foot(fig, 'E20_论文表1_资料列表.csv')
save_fig(fig, 'A04', '资料系列收录规模', '语料与基础', '批A_语料规模.py',
         ['E20_论文表1_资料列表.csv'], '《中共党史人物传》51卷为最大资料系列，其余多为10册级地方专题资料')

# ================= A05 断言时间覆盖年分布（面积图） =================
t05 = L('T05_断言时间年分布.csv').sort_values('年')
yrs, tot = t05['年'].values.astype(int), t05['总数'].values
ma = pd.Series(tot).rolling(7, center=True, min_periods=3).mean()
fig, ax = new_fig(10.5, 5.0)
ax.fill_between(yrs, tot, color=M['雾蓝'], alpha=.28, zorder=2, label='年度断言数')
ax.plot(yrs, ma, color=TIER_C['STRICT'], lw=2.0, zorder=4, label='7年滑动平均')
for yr, lab in [(1927, '大革命失败'), (1935, '遵义会议'), (1949, '新中国成立')]:
    ax.axvline(yr, color=M['陶砂'], lw=1.1, ls='--', alpha=.8, zorder=3)
    ax.text(yr, ax.get_ylim()[1] * .97, f'{yr}\n{lab}', ha='center', va='top',
            fontsize=8.5, color=M['陶砂'])
ax.set_xlim(1850, 2026)
ax.set_ylim(0, max(tot) * 1.12)
ax.set_ylabel('断言数（条）'); ax.set_xlabel('年份')
ax.legend(loc='upper right', fontsize=9)
despine(ax); light_grid(ax)
ax.set_title('A05 断言时间覆盖年分布', loc='left')
foot(fig, 'T05_断言时间年分布.csv')
save_fig(fig, 'A05', '断言时间覆盖年分布', '语料与基础', '批A_语料规模.py',
         ['T05_断言时间年分布.csv'], '断言集中于1900–1950年，1927年为峰值年（23,197条），三个历史节点均对应局部高峰')

# ================= A06 历史阶段断言分布（分组条形） =================
t31 = L('T31_主语类型×历史阶段.csv')
top6 = t31.groupby('主语类型')['断言数'].sum().nlargest(6).index.tolist()
pv = t31.pivot_table(index='历史阶段', columns='主语类型', values='断言数', aggfunc='sum').fillna(0)
stage_ord = L('T16_历史阶段×省域时空格.csv')[['历史阶段', '阶段序']].drop_duplicates().set_index('历史阶段')['阶段序']
st_order = [s for s in stage_ord.sort_values().index.tolist() if s in pv.index]
st_order += [s for s in pv.index if s not in st_order]   # 保险：追加未登记阶段
pv = pv.loc[st_order]
others = pv.drop(columns=[c for c in top6 if c in pv.columns]).sum(axis=1)
plot_cols = [c for c in top6 if c in pv.columns]
fig, ax = new_fig(10.5, 5.2)
x = np.arange(len(pv)); w = .78 / (len(plot_cols) + 1)
for i, c in enumerate(plot_cols):
    ax.bar(x + i * w - .39 + w / 2, pv[c] + 1, width=w, color=SEQ10[i], label=ez(c), zorder=3)
ax.bar(x + len(plot_cols) * w - .39 + w / 2, others + 1, width=w, color='#C9C4BC',
       label='其他类型合计', zorder=3)
ax.set_yscale('log'); ax.set_ylim(1, pv[plot_cols].values.max() * 4)
ax.set_xticks(x); ax.set_xticklabels([wrap_zh(s, 6) for s in pv.index], fontsize=9)
for ytl in ax.get_yticklabels(which='both'):
    ytl.set_visible(True)
ax.set_ylabel('断言数（对数轴）')
ax.legend(ncol=4, fontsize=9)
despine(ax); light_grid(ax)
ax.set_title('A06 历史阶段断言分布', loc='left')
foot(fig, 'T31_主语类型×历史阶段.csv（Top6主语类型+其他）')
save_fig(fig, 'A06', '历史阶段断言分布', '语料与基础', '批A_语料规模.py',
         ['T31_主语类型×历史阶段.csv'], '人物类断言在土地革命战争与解放战争两个阶段占绝对主导，阶段间量级差达数十倍')

# ================= A07 来源成员数分布 =================
t11 = L('T11_来源成员数分布.csv')
fig, ax = new_fig(7.2, 4.3)
ax.bar(t11['来源成员数'], t11['断言数'], width=.72, color=M['青灰'], zorder=3)
for m, v in zip(t11['来源成员数'], t11['断言数']):
    ax.text(m, v * 1.18, f"{v:,}", ha='center', fontsize=8.6, color=INK)
ax.set_yscale('log'); ax.set_ylim(1, 830000)
ax.set_xticks(t11['来源成员数'])
ax.set_xlabel('来源成员数（同一断言被收录的资料来源数）'); ax.set_ylabel('断言数（对数轴）')
despine(ax); light_grid(ax)
ax.set_title('A07 来源成员数分布', loc='left')
foot(fig, 'T11_来源成员数分布.csv')
save_fig(fig, 'A07', '来源成员数分布', '语料与基础', '批A_语料规模.py',
         ['T11_来源成员数分布.csv'], '90.3%断言仅单一来源支撑，多源交叉验证（≥2来源）占9.7%')

# ================= A08 流域分段知识产出（packed circles） =================
t38 = L('T38_流域分段统计.csv').sort_values('断言数', ascending=False).reset_index(drop=True)
fig, ax = new_fig(7.2, 4.6)
r = np.sqrt(t38['断言数'].values.astype(float)); r = r / r.max() * 1.62
fill = [BLUE_SEQ[-2], BLUE_SEQ[4], BLUE_SEQ[2]]   # 面积大→深色
centers, cur = [], 0.0
for i, ri in enumerate(r):
    if i > 0:
        cur += r[i - 1] + .18
    centers.append((cur + ri, 0.0))
    cur += ri
for i, (cx, cy) in enumerate(centers):
    big = i == 0
    ax.add_patch(plt.Circle((cx, cy), r[i], facecolor=fill[i], alpha=.88,
                            edgecolor='white', lw=2.2))
    ax.text(cx, cy + .16, t38.loc[i, '流域分段'].replace('BASIN-SECTION:', ''),
            ha='center', fontsize=13.5, color='white' if big else INK, fontweight='bold')
    ax.text(cx, cy - .30, f"{int(t38.loc[i, '断言数']):,}", ha='center', fontsize=10.5,
            color='white' if big else INK)
ax.set_xlim(-r[0] - .4, centers[-1][0] + r[-1] + .4)
ax.set_ylim(-2.15, 2.15); ax.axis('off'); ax.set_aspect('equal')
ax.set_title('A08 流域分段知识产出', loc='left')
foot(fig, 'T38_流域分段统计.csv（圆面积∝断言数）')
save_fig(fig, 'A08', '流域分段知识产出', '语料与基础', '批A_语料规模.py',
         ['T38_流域分段统计.csv'], '上游段（52,665条）>中游段（44,482）>下游段（36,938），上游资料密度最高')

# ================= A09 省域×实体类型矩阵（热力图） =================
t15 = L('T15_省域×主语类型矩阵.csv')
t15 = t15[t15['省份'].isin(PROV13)]
pv = t15.pivot_table(index='主语类型', columns='省份', values='断言数', aggfunc='sum').fillna(0)
pv = pv[PROV13]
pv = pv.loc[pv.sum(axis=1).sort_values(ascending=False).index]
fig, ax = new_fig(9.8, 6.2)
vmax = np.log10(pv.values.max())
im = ax.imshow(np.log10(pv.values + 1), cmap=cmap_blue, aspect='auto',
               vmin=0, vmax=vmax)
ax.set_xticks(range(len(pv.columns)))
ax.set_xticklabels([c.replace('省', '').replace('市', '').replace('自治区', '') for c in pv.columns],
                   rotation=45, ha='right', fontsize=9)
ax.set_yticks(range(len(pv.index))); ax.set_yticklabels([ez(t) for t in pv.index], fontsize=9)
for i in range(pv.shape[0]):
    for j in range(pv.shape[1]):
        v = pv.values[i, j]
        if v > 0:
            ax.text(j, i, f"{int(v):,}", ha='center', va='center', fontsize=6.8,
                    color='white' if np.log10(v + 1) > vmax * .62 else INK)
cb = fig.colorbar(im, ax=ax, shrink=.7, pad=.015)
cb.set_label('断言数（log₁₀色标）', fontsize=9)
cb.ax.tick_params(labelsize=8); cb.outline.set_visible(False)
ax.set_title('A09 省域×实体类型矩阵', loc='left')
despine(ax, keep=())
foot(fig, 'T15_省域×主语类型矩阵.csv（十三省单省行）')
save_fig(fig, 'A09', '省域×实体类型矩阵', '语料与基础', '批A_语料规模.py',
         ['T15_省域×主语类型矩阵.csv'], '人物/事件/组织三类在所有省域均为前三大主语类型，贵州、四川各行规模领先')

# ================= A10 省域知识产出密度（气泡散点） =================
d = t01s.copy(); d['sp'] = d['严格层'] / d['断言总数'] * 100
fig, ax = new_fig(7.8, 5.2)
sizes = d['断言总数'] / d['断言总数'].max() * 2400 + 80
ax.scatter(d['断言总数'], d['sp'], s=sizes, facecolor=M['雾蓝'], alpha=.55,
           edgecolor='white', lw=1.4, zorder=3)
from adjustText import adjust_text
texts = [ax.text(x, y, p.replace('省', '').replace('市', '').replace('自治区', ''),
                 fontsize=8.8, color=INK)
         for x, y, p in zip(d['断言总数'], d['sp'], d['省份'])]
adjust_text(texts, arrowprops=dict(arrowstyle='-', color=FAINT, lw=.6),
            expand=(1.5, 1.8))
ax.set_xlabel('断言总数（条）'); ax.set_ylabel('严格层占比（%）')
despine(ax); light_grid(ax)
ax.set_title('A10 省域知识产出密度', loc='left')
foot(fig, SRC1 + '（气泡大小∝断言总数）')
save_fig(fig, 'A10', '省域知识产出密度', '语料与基础', '批A_语料规模.py',
         [SRC1], '严格层占比与总量无正向关系：江西（4.4%）与云南（3.9%）密度最高，重庆最低（2.3%）')

# ================= A11 断言十年段构成 =================
t05y = L('T05_断言时间年分布.csv')
t05y['dec'] = (t05y['年'] // 10) * 10
g = t05y.groupby('dec')['总数'].sum()
tot_all = g.sum()
fig, ax = new_fig(10.5, 4.4)
xs = range(len(g))
cols = [cmap_sand(.15 + .85 * (v / g.max())) for v in g]
ax.bar(xs, g / tot_all * 100, color=cols, width=.72, zorder=3)
for i, v in enumerate(g):
    ax.text(i, g.iloc[i] / tot_all * 100 + .8, f"{v / tot_all * 100:.1f}%",
            ha='center', fontsize=8.4, color=INK)
ax.set_xticks(list(xs))
ax.set_xticklabels([f"{int(d)}s" if int(d) < 2000 else f"{int(d)}年代" for d in g.index],
                   rotation=45, ha='right')
ax.set_ylabel('占1853–2024全部断言比例（%）')
despine(ax); light_grid(ax)
ax.set_title('A11 断言十年段构成', loc='left')
foot(fig, 'T05_断言时间年分布.csv（十年段汇总）')
save_fig(fig, 'A11', '断言十年段构成', '语料与基础', '批A_语料规模.py',
         ['T05_断言时间年分布.csv'], '1920s–1940s三个十年段合计承载约七成断言，呈现显著革命时期聚集')

# ================= A12 断言置信度分布 =================
t37b = L('T37b_置信度分布.csv')
fig, ax = new_fig(7.6, 4.4)
ax.bar(t37b['置信度'].astype(float), t37b['断言数'], width=.012, color=M['雾蓝'], zorder=3)
for x, v in zip(t37b['置信度'].astype(float), t37b['断言数']):
    ax.text(x, v * 1.22, f"{v:,}", ha='center', fontsize=8, color=INK)
ax.set_yscale('log'); ax.set_ylim(1, 1.6e6)
ax.set_xlabel('判定置信度'); ax.set_ylabel('断言数（对数轴）')
ax.set_xticks([0, .2, .4, .6, .8, .9, 1.0])
despine(ax); light_grid(ax)
ax.set_title('A12 断言置信度分布', loc='left')
foot(fig, 'T37b_置信度分布.csv')
save_fig(fig, 'A12', '断言置信度分布', '语料与基础', '批A_语料规模.py',
         ['T37b_置信度分布.csv'], '置信度呈双峰：1.00（70.5%）与0.85–0.99（27.2%），低置信区间断言极少')

# ================= A13 断言风险层构成（水平堆叠单条） =================
t37 = L('T37_风险层分布.csv')
fig, ax = new_fig(9.2, 3.0)
tot = t37['断言数'].sum(); left = 0.0
risk_lab = {'A': 'A（最低风险）', 'B': 'B', 'C': 'C', 'D': 'D（最高风险）'}
rc = [BLUE_SEQ[6], BLUE_SEQ[4], BLUE_SEQ[2], '#8B5A5A']
for i, (r, v) in enumerate(zip(t37['风险层'], t37['断言数'])):
    p = v / tot * 100
    ax.barh([0], [p], left=left, color=rc[i], height=.5, zorder=3,
            label=f"{risk_lab[r]}：{v:,}（{p:.1f}%）")
    if p > 8:
        ax.text(left + p / 2, 0, f"{p:.1f}%", ha='center', va='center',
                fontsize=10, color='white')
    left += p
ax.annotate('D层仅60条（0.01%）', xy=(99.9, .32), xytext=(86, 1.05),
            fontsize=8.6, color='#8B5A5A',
            arrowprops=dict(arrowstyle='-', color='#8B5A5A', lw=.7))
ax.set_xlim(0, 100); ax.set_ylim(-.6, 1.4)
ax.set_yticks([]); ax.set_xlabel('占全库断言比例（%）')
ax.legend(loc='upper center', bbox_to_anchor=(.5, -.22), ncol=2, fontsize=9)
despine(ax, keep=('bottom',))
ax.set_title('A13 断言风险层构成', loc='left')
foot(fig, 'T37_风险层分布.csv')
save_fig(fig, 'A13', '断言风险层构成', '语料与基础', '批A_语料规模.py',
         ['T37_风险层分布.csv'], 'A层（最低风险）占69.6%，高风险C+D合计仅10.4%，风险结构整体可控')

# ================= A14 图谱核心对象规模对比（对数点图） =================
e11 = L('E11_权威数字31项.csv').set_index('metric')['value']
t21 = L('T21_关系契约88谓词.csv')
items = [('断言时序关系对', float(e11['assertion_temporal_pairs'])),
         ('断言总数', float(e11['total_assertions'])),
         ('规范实体', float(e11['total_entities'])),
         ('事件框架', float(e11['event_frames'])),
         ('文化状态', float(e11['culture_states'])),
         ('关系契约谓词', float(len(t21))),
         ('地点版本', float(e11['place_versions']))]
items = items[::-1]     # 自下而上由小到大
fig, ax = new_fig(8.0, 4.6)
names = [i[0] for i in items]; vs = [i[1] for i in items]
cols = [cmap_blue(.3 + .7 * (v / max(vs))) for v in vs]
ax.scatter(vs, range(len(items)), s=190, color=cols, zorder=3, edgecolor='white', lw=1.2)
for i, v in enumerate(vs):
    ax.text(v * 1.25, i, f"{int(v):,}", va='center', fontsize=9.5, color=INK)
ax.set_xscale('log'); ax.set_xlim(30, 2.4e7)
ax.set_yticks(range(len(items))); ax.set_yticklabels(names)
ax.set_xlabel('对象数量（对数轴）')
ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}"))
despine(ax); light_grid(ax, 'x')
ax.set_title('A14 图谱核心对象规模对比', loc='left')
foot(fig, 'E11_权威数字31项.csv、T21_关系契约88谓词.csv（行数）')
save_fig(fig, 'A14', '图谱核心对象规模对比', '语料与基础', '批A_语料规模.py',
         ['E11_权威数字31项.csv', 'T21_关系契约88谓词.csv'],
         '七类核心对象跨越5个数量级：563万时序关系对→424k断言→153k实体→72地点版本（注：原计划"来源关联466312"未见于任何中间表，改用E11实测的时序关系对）')

print('批A_语料规模.py 全部完成：A01–A14')
