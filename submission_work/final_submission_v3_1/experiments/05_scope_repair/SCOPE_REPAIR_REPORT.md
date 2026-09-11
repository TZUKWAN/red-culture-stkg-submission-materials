# SCOPE 调整分类型盲评归因报告（SCOPE_REPAIR_REPORT）

- 生成时间：2026-09-09T18:41:42+00:00（全自动，无人工干预）
- **口径：两票盲评**。Judge A = Qwen3.6-35B-A3B，Judge B = gpt-5.6-luna，各 208/208 条、status 全 OK。
- Judge C 只覆盖少量样本且口径未定，**全程不采用**；本报告所有数字均为 A+B 两票口径。
- 判票方向解码：judge 输出的 A_BETTER/B_BETTER 指展示位，已按 `payloads/SCOPE_REVALIDATION_V2_AB_MAPPING.csv` 逐条解码回 before/after（未做任何方向猜测）；校验 judge 记录 `prompt_sha256` 与 payload 文件完全一致（208/208 通过），并把 payload 两个展示位的状态按映射方向与任务文件 before/after 状态逐条核对 role（0 处冲突），独立确认映射文件方向无误。
- 无效票单独计数：本批 A/B 均无 MODEL_OUTPUT_INVALID / 缺票 / 非法 decision（A: 0，B: 0），故 INVALID=0。
- 聚合规则：两票一致 → 该判定；两票不一致 → DISAGREE；任一票 INVALID → INVALID。

## 1. 总体两票口径结果

| 聚合判定 | 条数 | 占比 |
|---|---:|---:|
| BEFORE_BETTER | 72 | 34.6% |
| AFTER_BETTER | 38 | 18.3% |
| EQUIVALENT | 0 | 0.0% |
| BOTH_WRONG | 2 | 1.0% |
| INSUFFICIENT | 16 | 7.7% |
| DISAGREE | 80 | 38.5% |
| INVALID | 0 | 0.0% |

- 两票一致且分出胜负（decided）110 条：**BEFORE_BETTER 72 条 vs AFTER_BETTER 38 条，AFTER 胜率 34.5%**——与已知总体方向（改前约 52% vs 改后 46%，按单票池化）一致且更极端：两票一致时 BEFORE 以约 65.5% : 34.5% 压倒 AFTER。
- 单票池化（A+B 共 416 票）解码后：BEFORE_BETTER 193、AFTER_BETTER 132、INSUFFICIENT 64、BOTH_WRONG 27、INVALID 0；占全部票 46.4% / 31.7%，占分出胜负的票（325 票）59.4% / 40.6%——方向与已知总体口径（改前约 52% vs 改后 46%）一致：BEFORE 稳定高于 AFTER，且两票一致时差距进一步放大。
- 两票冲突（DISAGREE）80 条（38.5%），其中 BEFORE_BETTER↔AFTER_BETTER 硬冲突 27 条；所有任务 adjustment_reason 均为 `final_entity_type_scope_closure`（唯一值），故损害只能按变换类型归因。

## 2. 类型 × 判定矩阵

| transformation_type | n | AFTER | BEFORE | EQUIV | BOTH_WRONG | INSUF | DISAGREE | INVALID | decided | AFTER 胜率 | 二项 p(双侧) | 建议 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `unknown→event_occurrence` | 60 | 23 | 4 | 0 | 0 | 5 | 28 | 0 | 27 | 85.2% | 0.000 | **REWRITE** |
| `event_location→context_location` | 90 | 7 | 52 | 0 | 2 | 6 | 23 | 0 | 59 | 11.9% | 0.000 | **RETAIN** |
| `event_location→relation_location` | 5 | 0 | 1 | 0 | 0 | 1 | 3 | 0 | 1 | 0.0% | 1.000 | **UNRESOLVED** |
| `mixed` | 16 | 0 | 11 | 0 | 0 | 0 | 5 | 0 | 11 | 0.0% | 0.001 | **RETAIN** |
| `other` | 37 | 8 | 4 | 0 | 0 | 4 | 21 | 0 | 12 | 66.7% | 0.388 | **UNRESOLVED** |
| `time_owner_change` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | — | — | （本数据集 0 条） |
| `space_owner_change` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | — | — | （本数据集 0 条） |

注：`time_owner_change` / `space_owner_change` 在本数据集中为 **0 条**——208 条任务里 owner 变更从不单独出现（一旦 owner 变，role 必同步变），因此这两类无统计，也不进入排名。

## 3. 塌陷排名（AFTER 胜率从低到高）

1. `mixed`（n=16，decided=11，AFTER 0 : BEFORE 11，AFTER 胜率 0.0%）
2. `event_location→relation_location`（n=5，decided=1，AFTER 0 : BEFORE 1，AFTER 胜率 0.0%）
3. `event_location→context_location`（n=90，decided=59，AFTER 7 : BEFORE 52，AFTER 胜率 11.9%）
4. `other`（n=37，decided=12，AFTER 8 : BEFORE 4，AFTER 胜率 66.7%）
5. `unknown→event_occurrence`（n=60，decided=27，AFTER 23 : BEFORE 4，AFTER 胜率 85.2%）

**解读**：损害高度集中——`event_location→context_location` 一类就占全部任务的 43.3%（90/208），并贡献了 52 条两票一致的 BEFORE 胜例（占总 BEFORE 胜例的 72.2%）；`mixed` 类虽只有 16 条，但 AFTER **0 胜**，是塌得最彻底的一类。唯一 AFTER 显著占优的是 `unknown→event_occurrence`。

## 4. 分类型细目与典型例

### 4.1 `unknown→event_occurrence`（n=60，建议=REWRITE）

- 判定分布：BEFORE_BETTER=4, AFTER_BETTER=23, INSUFFICIENT=5, DISAGREE=28
- AFTER 胜率（decided=27）：85.2%；未定率（DISAGREE+INSUF+BOTH_WRONG）55.0%
- 证据可得性：direct 12（20.0%）、lexical 47、none 1；DISAGREE 构成：{'AFTER_BETTER|BEFORE_BETTER': 13, 'BEFORE_BETTER|INSUFFICIENT': 8, 'AFTER_BETTER|INSUFFICIENT': 4, 'AFTER_BETTER|BOTH_WRONG': 2, 'BEFORE_BETTER|BOTH_WRONG': 1}
- adjustment_reason：{'final_entity_type_scope_closure': 60}
- judge reason_code（BEFORE 胜票 vs AFTER 胜票）：{'TIME_UNSUPPORTED': 11, 'TIME_MISMATCH': 4, 'TIME_NOT_SUPPORTED': 2, 'TEMPORAL_ROLE_UNSUPPORTED': 1, 'NO_EXPLICIT_TIME_EVIDENCE': 1, 'TIME_INVALID': 1, 'TIME_NOT_ESTABLISHED': 1, 'TIME_OCCURRENCE_UNSUPPORTED': 1, 'UNRELATED_CONTEXT': 1, 'NO_EVENT_TIME_EVIDENCE': 1, 'TEMPORAL_UNSUPPORTED': 1, 'TIME_UNSUPPORTED_OR_CONTRADICTED': 1, 'TIME_PERIOD_UNSUPPORTED': 1, 'TIME_CONTEXT_MISMATCH': 1, 'NO_TEMPORAL_EVIDENCE': 1, 'TIME_IS_SOURCE_DOCUMENT_NOT_EVENT': 1} vs {'TIME_ROLE_MATCH': 9, 'TIME_ROLE_CORRECT': 7, 'ROLE_MATCH': 4, 'TIME_ROLE_MISMATCH': 4, 'TIME_EVENT_OCCURRENCE': 3, 'A_BETTER_TIME_ROLE': 2, 'TIME_EVENT_SUPPORTED': 2, 'B_CORRECT_TIME_ROLE': 2, 'EVENT_TIME_SUPPORTED': 2, 'EVENT_TIME_EXPLICIT': 2, 'TIME_ROLE_EXPLICIT': 2, 'EXPLICIT_OCCURRENCE': 2, 'TIME_ROLE_OCCURRENCE': 1, 'EVENT_TIME_ROLE_SUPPORTED': 1, 'TIME_EXPLICITLY_SUPPORTED': 1, 'B_BETTER': 1, 'TIME_ROLE_EVENT_OCCURRENCE': 1, 'EVENT_TIME_CONTEXT': 1, 'TIME_ROLE_SUPPORTED': 1, 'STANDARD_EVENT_ROLES': 1, 'EVT_ROLE_MATCH': 1, 'EXPLICIT_TIME_PLACE': 1, 'EXPLICIT_EVENT_TIME': 1, 'event_time_explicit': 1, 'TIME_DIRECTLY_ASSOCIATED_WITH_EVENT': 1, 'ASSERTION_EXPLICIT_TIME': 1, 'TIME_SUPPORTED_EVENT': 1, 'EVENT_PERIOD_REFERENCE': 1, 'time_is_event_occurrence': 1, 'A_BETTER': 1, 'ASSERTION_STRUCTURE': 1, 'EVIDENCE_MATCHES_A': 1, 'TIME_EXPLICIT_EVENT': 1, 'TIME_ROLE_ALIGNMENT': 1, 'A_TIME_SUPPORTED': 1, 'TIME_EVENT_CONTEXT': 1}

#### SA-0057（unknown→event_occurrence，聚合=BEFORE_BETTER，证据=lexical）

**断言（payload 原文）**：

```
断言：垦丰暴动（Event） —occurred_at→ 岷山（Place）
时间：原始表述：红军；规范表述：1927年8月-1937年7月；区间：1927-08-01 至 1937-07-06；精度：period
空间：原始表述：江西区域
```

**payload 证据句**：「垦丰暴动队伍三十余人在林德去，赴建年同志的部署下，在九江地区休整两天后，转赴到岷山。」

- BEFORE 状态：time_role=unknown, time_owner=（无）; space_role=event_location, space_owner=垦丰暴动
- AFTER 状态：time_role=event_occurrence, time_owner=垦丰暴动; space_role=event_location, space_owner=垦丰暴动
- **Judge A（BEFORE_BETTER）**：断言中的时间区间为十年跨度，明显不符合单次暴动事件的发生时间，证据亦未支持其为事件发生时间，故b方案错误；a方案将时间标注为unknown更符合证据实际。
- **Judge B（BEFORE_BETTER）**：证据支持岷山是暴动队伍活动地点，但仅说明后续转赴岷山及十一月初会议，未明确垦丰暴动本身发生于所标时间区间，因此时间标注为unknown优于event_occurrence。

#### SA-0014（unknown→event_occurrence，聚合=AFTER_BETTER，证据=direct）

**断言（payload 原文）**：

```
断言：反扫荡斗争（Event） —occurred_at→ 淮海区（Place）
时间：原始表述：抗战；规范表述：1937年7月-1945年8月；区间：1937-07-07 至 1945-08-15；精度：period
空间：原始表述：江苏区域
```

**payload 证据句**：「1943年2月24日，新四军四部一分为三路强攻日军据点洋河镇，经两小时激战，生俘伪官兵50余名，毙伤200余名，摧毁敌人碉堡20个。」；「泗阳、淮阴等地农民，配合淮北地委军事行动，全力以赴，开展反扫荡斗争，历时33天，取得了反扫荡斗争的伟大的胜利。」

- BEFORE 状态：time_role=unknown, time_owner=（无）; space_role=event_location, space_owner=反扫荡斗争
- AFTER 状态：time_role=event_occurrence, time_owner=反扫荡斗争; space_role=event_location, space_owner=反扫荡斗争
- **Judge A（AFTER_BETTER）**：证据明确记载了反扫荡斗争的具体起止时间与持续时长，属于事件发生时间，a的event_occurrence标注准确，b的unknown与原文不符。
- **Judge B（AFTER_BETTER）**：证据明确记载反扫荡斗争发生于1942年11月14日至12月6日并持续33天，因此将其时间标为事件发生时间比标为未知更符合原文。


### 4.2 `event_location→context_location`（n=90，建议=RETAIN）

- 判定分布：BEFORE_BETTER=52, AFTER_BETTER=7, BOTH_WRONG=2, INSUFFICIENT=6, DISAGREE=23
- AFTER 胜率（decided=59）：11.9%；未定率（DISAGREE+INSUF+BOTH_WRONG）34.4%
- 证据可得性：direct 0（0.0%）、lexical 88、none 2；DISAGREE 构成：{'AFTER_BETTER|BEFORE_BETTER': 11, 'AFTER_BETTER|INSUFFICIENT': 5, 'BEFORE_BETTER|BOTH_WRONG': 4, 'AFTER_BETTER|BOTH_WRONG': 2, 'BEFORE_BETTER|INSUFFICIENT': 1}
- adjustment_reason：{'final_entity_type_scope_closure': 90}
- judge reason_code（BEFORE 胜票 vs AFTER 胜票）：{'EVENT_LOC_MATCH': 19, 'EVENT_LOCATION_SUPPORTED': 15, 'SPACE_EVENT_SUPPORTED': 8, 'EVT_LOC_MATCH': 6, 'EVENT_LOCATION_EXPLICIT': 5, 'SPACE_EVENT_LOCATION': 4, 'DIRECT_EVENT_LOCATION': 4, 'EXPLICIT_EVENT_LOCATION': 4, 'SPACE_ROLE_ACCURATE': 3, 'SPACE_ROLE_MISMATCH': 3, 'SPACE_EVENT_LOCATION_SUPPORTED': 3, 'DIRECT_LOCATION_EVIDENCE': 2, 'EVENT_LOC_FIT': 2, 'B_BETTER': 2, 'SPACE_ROLE_BETTER': 2, 'EVENT_LOCATION': 2, 'EVENT_LOC_SUPPORTED': 2, 'EVENT_LOC_BETTER': 2, 'SPACE_ROLE_CORRECT': 2, 'SPACE_ROLE_EVENT': 2, 'EVENT_LOC': 1, 'event_activity_location': 1, 'A_BETTER_EVENT_LOC': 1, 'SPACE_EVENT_EXPLICIT': 1, 'EVT_LOC_SUPPORTED': 1, 'ROLE_EVENT': 1, 'event_location_supported': 1, 'SPACE_EVENT_LOC': 1, 'B_SPACE_BETTER': 1, 'ROLE_MATCH': 1, 'EVENT_LOC_DIRECT': 1, 'A_BETTER_SPACE_ROLE': 1, 'DIRECT_LOC': 1, 'A_SPACE_EVENT_LOCATION': 1, 'EVT_LOC_CORRECT': 1, 'EVENT_LOCATION_DIRECT': 1, 'EVT_LOC_BETTER': 1, 'EVENT_LOC_ACCURATE': 1, 'EVENT_LOC_DETERMINED': 1, 'RELATION_TYPE_MATCH': 1, 'direct_event_location': 1, 'EVIDENCE_SUPPORTS_EVENT_LOC': 1, 'assertion_verb_matches_event_loc': 1, 'SPACE_EVENT_VS_CONTEXT': 1, 'DIRECT_LOCATION': 1, 'A_BETTER': 1, 'explicit_event_location': 1, 'EVENT_LOCATION_MATCH': 1} vs {'SPACE_CONTEXT_NOT_EVENT': 4, 'CONTEXT_LOCATION_MATCH': 3, 'SPACE_NOT_EVENT_LOCATION': 3, 'CONTEXT_BETTER': 3, 'DESTINATION_NOT_EVENT_LOCATION': 1, 'CONTEXT_LOCATION_BETTER': 1, 'SPACE_DOCUMENT_NOT_EVENT': 1, 'CONTEXT_LOCATION_SUPPORTED': 1, 'ORG_LOC_MISMATCH': 1, 'LOC_MISMATCH': 1, 'BETTER_CONTEXT': 1, 'SPACE_IS_MEETING_CONTEXT': 1, 'CONTEXT_LOC_BETTER': 1, 'SPACE_ROLE_CONTEXT_NOT_EVENT': 1, 'SPACE_CONTEXT': 1, 'EVENT_LOCATION_UNSUPPORTED': 1, 'CONTEXT_NOT_EVENT': 1, 'EVENT_NOT_AT_SCHOOL': 1, 'LOC_UNSUBST': 1, 'ORG_NOT_EVENT_LOCATION': 1, 'LOC_NOT_SUPPORTED': 1, 'TIME_SPACE_MISMATCH': 1, 'SPACE_IS_RECEPTION_CONTEXT': 1}

#### SA-0010（event_location→context_location，聚合=BEFORE_BETTER，证据=lexical）

**断言（payload 原文）**：

```
断言：贵阳大西门中山公园（Place） —raw:发生于→ 林青（Person）
时间：原始表述：None；规范表述：None；区间：None 至 None；精度：unknown
空间：原始表述：贵州
```

**payload 证据句**：「随后，在第二天下午，根据天真同志约定的地点即贵阳大西门中山公园（现贵阳市委机关所在地）内会见了林青同志。」

- BEFORE 状态：time_role=unknown, time_owner=（无）; space_role=event_location, space_owner=林青
- AFTER 状态：time_role=unknown, time_owner=（无）; space_role=context_location, space_owner=（无）
- **Judge A（BEFORE_BETTER）**：证据明确指出会面事件实际发生在贵阳大西门中山公园内，属于事件发生地而非背景地点，故a的event_location标注更符合原文语义。
- **Judge B（BEFORE_BETTER）**：原文明确说明在贵阳大西门中山公园内会见林青，因此该地点属于事件发生地而非仅作背景地点。

#### SA-0006（event_location→context_location，聚合=AFTER_BETTER，证据=lexical）

**断言（payload 原文）**：

```
断言：潘星南（Person） —raw:发生于→ 苏北解放区（Place）
时间：原始表述：解放；规范表述：1945年8月-1949年9月；区间：1945-08-16 至 1949-09-30；精度：period
空间：原始表述：江苏区域
```

**payload 证据句**：「地下党组织决定，让潘星南转移阵地，准备去苏北解放区。」

- BEFORE 状态：time_role=biographical, time_owner=潘星南; space_role=event_location, space_owner=苏北解放区
- AFTER 状态：time_role=biographical, time_owner=潘星南; space_role=context_location, space_owner=（无）
- **Judge A（AFTER_BETTER）**：证据表明“准备去苏北解放区”仅为背景计划而非实际发生的事件，因此空间角色应标注为context_location而非event_location。
- **Judge B（AFTER_BETTER）**：证据表明苏北解放区是潘星南准备前往的目的地，并未明确说明断言事件发生于该地，因此标注为背景地点更符合原文。


### 4.3 `event_location→relation_location`（n=5，建议=UNRESOLVED）

- 判定分布：BEFORE_BETTER=1, INSUFFICIENT=1, DISAGREE=3
- AFTER 胜率（decided=1）：0.0%；未定率（DISAGREE+INSUF+BOTH_WRONG）80.0%
- 证据可得性：direct 2（40.0%）、lexical 3、none 0；DISAGREE 构成：{'AFTER_BETTER|BEFORE_BETTER': 2, 'BEFORE_BETTER|INSUFFICIENT': 1}
- adjustment_reason：{'final_entity_type_scope_closure': 5}
- judge reason_code（BEFORE 胜票 vs AFTER 胜票）：{'EVENT_LOC_MATCH': 2, 'BETTER_SPACE_ROLE': 1, 'EVENT_SITE_LOCATION_SUPPORTED': 1, 'OCCURRED_AT_EVENT_LOC': 1} vs {'SUBJECT_IS_SITE_NOT_EVENT': 1, 'SPACE_IS_RELATIONAL_SCOPE': 1}

#### SA-0100（event_location→relation_location，聚合=BEFORE_BETTER，证据=lexical）

**断言（payload 原文）**：

```
断言：芦花会议会址（CulturalSite） —occurred_at→ 黑水县（Place）
时间：原始表述：None；规范表述：None；区间：None 至 None；精度：unknown
空间：原始表述：四川
```

**payload 证据句**：「芦花会议会址，据调查，在离今县城二公里的中芦花名叫奎尼之地。」

- BEFORE 状态：time_role=unknown, time_owner=（无）; space_role=event_location, space_owner=芦花会议会址
- AFTER 状态：time_role=unknown, time_owner=（无）; space_role=relation_location, space_owner=（无）
- **Judge A（BEFORE_BETTER）**：证据明确指出了芦花会议会址的具体地理位置，符合事件发生地的定义，因此方案a的空间角色标注更准确。
- **Judge B（BEFORE_BETTER）**：证据明确说明芦花会议会址的具体地点，支持将该会址作为事件发生地点，而非仅标注为关系所在地。

#### SA-0040（event_location→relation_location，聚合=DISAGREE，证据=lexical）

**断言（payload 原文）**：

```
断言：遵义会议会址（CulturalSite） —occurred_at→ 遵义县（Place）
时间：原始表述：纪念；规范表述：1949年10月-1978年12月；区间：1949-10-01 至 1978-12-31；精度：period
空间：原始表述：遵义
```

**payload 证据句**：「黄毛军德，送交了遵义文化机关，后来就陈列在遵义会议会址革命军事文物展览馆了。」；「当你走进“遵义会议会址”的革命文物陈列室，便会看见一床草绿色军用毛毯及其简短的说明文字。」；「1951年新学年向全国发的“遵义会议会址”全景照片就是由彭千里、彭一杭拍摄后，由市里送至京经毛泽东主席审定后发到的。」

- BEFORE 状态：time_role=context_time, time_owner=（无）; space_role=event_location, space_owner=遵义会议会址
- AFTER 状态：time_role=context_time, time_owner=（无）; space_role=relation_location, space_owner=（无）
- **Judge A（BEFORE_BETTER）**：会议会址的空间属性明确指向历史事件发生地（event_location），时间标注为纪念期符合context_time定义，故b方案更契合原文语义与事实。
- **Judge B（AFTER_BETTER）**：证据将遵义会议会址作为文化遗址、陈列和照片所指的地点，支持其与遵义县的空间关系而非将其作为事件发生地。


### 4.4 `mixed`（n=16，建议=RETAIN）

- 判定分布：BEFORE_BETTER=11, DISAGREE=5
- AFTER 胜率（decided=11）：0.0%；未定率（DISAGREE+INSUF+BOTH_WRONG）31.2%
- 证据可得性：direct 3（18.8%）、lexical 13、none 0；DISAGREE 构成：{'BEFORE_BETTER|INSUFFICIENT': 3, 'BOTH_WRONG|INSUFFICIENT': 2}
- adjustment_reason：{'final_entity_type_scope_closure': 16}
- judge reason_code（BEFORE 胜票 vs AFTER 胜票）：{'EVENT_NATURE': 3, 'EVENT_LOCATION_AND_OCCURRENCE': 3, 'EVENT_ROLE_MATCH': 3, 'EVENT_MATCH': 2, 'EVENT_LOCATION_OCCURRENCE': 2, 'EVENT_ROLES_MATCH': 1, 'EVENT_OCCURRENCE_AND_LOCATION': 1, 'EVENT_LOC_TIME': 1, 'EVENT_TIME_LOCATION_EXPLICIT': 1, 'EVENT_OCCURRENCE': 1, 'EVENT_OCCURRENCE_LOCATION': 1, 'EVENT_TIME_LOCATION': 1, 'occurred_at_implies_event': 1, 'EVENT_TIME_SPACE': 1, 'ORG_ACTIVITY_EVENT': 1, 'OCCURRED_AT_EVENT': 1, 'EVENT_PREDICATE': 1} vs （无）

#### SA-0016（mixed，聚合=BEFORE_BETTER，证据=lexical）

**断言（payload 原文）**：

```
断言：中国人民解放军（Organization） —occurred_at→ 南京（AdministrativeRegion）
时间：原始表述：渡江战役；规范表述：1945年8月-1949年9月；区间：1945-08-16 至 1949-09-30；精度：period
空间：原始表述：安徽区域
```

**payload 证据句**：「第二编（1921—1949）  党派、各阶层代表人士热烈响应。  1948年9月至1949年1月，中国人民解放军同国民党军主力进行战略决战，连续取得辽沈、淮海、平津三大战役的胜利。  1948年12月，中国人民银行成立并发行人民币。  1948年12月30日，毛泽东为新华社撰写《将革命进行到底》的新年献词。  1949年1月31日，北平和平解放。  1949年3月，中共七届二中全会在西柏坡召开。全会决定党在全国胜利后在政治、经济、外交方面应当采取的基本政策，毛泽东在全会上提出“两个务必”思想。  1949年4月，毛泽东、朱德发布《向全国进军的命令》。人民解放军发起渡江战役，解放南京，推翻国民党在中国大陆的统治。  1949年5月，上海解放。  1949年6月，新政治协商会议筹备会在北平开幕。  1949年6月，毛泽东发表《论人民民主专政》。  1949年9月，中国人民政治协商会议第一届全体会议在北平举行，会议通过了《中国人民政治协商会议共同纲领》等文件。毛泽东在开幕词中向全世界宣告：“占人类总数四分之一的中国人从此站立起来了。”」

- BEFORE 状态：time_role=event_occurrence, time_owner=中国人民解放军; space_role=event_location, space_owner=中国人民解放军
- AFTER 状态：time_role=relation_validity, time_owner=（无）; space_role=relation_location, space_owner=（无）
- **Judge A（BEFORE_BETTER）**：证据明确指出人民解放军于1949年4月发起渡江战役并解放南京，属于具体的历史军事事件，因此时间与空间角色应标注为事件发生时间与地点（event_occurrence/event_location），a方案更符合原文语义。
- **Judge B（BEFORE_BETTER）**：证据明确将渡江战役表述为人民解放军发起的事件，并指出其解放南京，因此事件发生地和事件发生时间角色均比关系所在地与关系有效时间更符合原文。

#### SA-0001（mixed，聚合=DISAGREE，证据=lexical）

**断言（payload 原文）**：

```
断言：人民解放军（Organization） —occurred_at→ 西南民族地区（Place）
时间：原始表述：解放；规范表述：1945年8月-1949年9月；区间：1945-08-16 至 1949-09-30；精度：period
空间：原始表述：长江流域
```

**payload 证据句**：「印刷中央发布的中国人民解放军布告」；「雷春国协助人民解放军开展剿匪斗争。」

- BEFORE 状态：time_role=event_occurrence, time_owner=人民解放军; space_role=event_location, space_owner=人民解放军
- AFTER 状态：time_role=relation_validity, time_owner=（无）; space_role=relation_location, space_owner=（无）
- **Judge A（BEFORE_BETTER）**：证据明确提及人民解放军开展军事斗争，表明断言描述的是动态历史事件，故时间与空间应标注为事件发生时间与地点，方案b更符合原文语义。
- **Judge B（INSUFFICIENT）**：证据未明确说明人民解放军相关事件发生于长江流域或西南民族地区，也未明确证明1945年8月至1949年9月是事件发生时间还是关系有效时间。


### 4.5 `other`（n=37，建议=UNRESOLVED）

- 判定分布：BEFORE_BETTER=4, AFTER_BETTER=8, INSUFFICIENT=4, DISAGREE=21
- AFTER 胜率（decided=12）：66.7%；未定率（DISAGREE+INSUF+BOTH_WRONG）67.6%
- 证据可得性：direct 8（21.6%）、lexical 29、none 0；DISAGREE 构成：{'AFTER_BETTER|BOTH_WRONG': 10, 'AFTER_BETTER|INSUFFICIENT': 6, 'BEFORE_BETTER|BOTH_WRONG': 2, 'BEFORE_BETTER|INSUFFICIENT': 2, 'AFTER_BETTER|BEFORE_BETTER': 1}
- adjustment_reason：{'final_entity_type_scope_closure': 37}
- judge reason_code（BEFORE 胜票 vs AFTER 胜票）：{'SPACE_RELATION_LOCATION': 3, 'TIME_BIOGRAPHICAL': 1, 'BIO_TIME_BETTER': 1, 'TIME_ROLE_BETTER': 1, 'context_location_supported': 1, 'CONTEXTUAL_BASIS': 1, 'EVENT_OCCURRENCE_MATCH': 1, 'TIME_IS_EVENT_OCCURRENCE': 1, 'SPACE_ROLE_SUPPORTED': 1, 'SPACE_RELEVANT': 1, 'RELATION_LOCATION_MATCH': 1} vs {'TIME_NOT_BIOGRAPHICAL': 4, 'TIME_ROLE_MISMATCH': 3, 'TIME_CONTEXT_BETTER': 3, 'TIME_ROLE_CONTEXT': 2, 'TIME_CONTEXT_MISMATCH': 2, 'CONTEXT_TIME_BETTER': 2, 'SCHEMA_VIOLATION_CONTEXT_TIME': 1, 'TIME_ROLE_SCHEMA_MISMATCH': 1, 'TIME_ROLE_BETTER': 1, 'A_TIME_ROLE_MISMATCH': 1, 'ORG_NOT_BIOGRAPHICAL': 1, 'BIOGRAPHICAL_TIME_MISMATCH': 1, 'TIME_ROLE_INVALID_A': 1, 'TIME_OWNER_MISMATCH': 1, 'TIME_MISMATCH_CONTEXT': 1, 'CONTEXT_TIME_SPACE': 1, 'LOC_EVENT_MISMATCH': 1, 'TIME_MISMATCH_BIO_WRONG': 1, 'A_TIME_ROLE_UNSUPPORTED': 1, 'BIOGRAPHICAL_CONTEXT': 1, 'TIME_ROLE_CONTEXT_NOT_BIOGRAPHICAL': 1, 'CONTEXT_TIME_BETTER_FOR_ORG': 1, 'TIME_ROLE_NOT_BIOGRAPHICAL': 1}

#### SA-0025（other，聚合=BEFORE_BETTER，证据=direct）

**断言（payload 原文）**：

```
断言：陶、铸（Person） —led→ 汤池训练班（Organization）
时间：原始表述：None；规范表述：None；区间：None 至 None；精度：unknown
空间：原始表述：汤池
```

**payload 证据句**：「七一五以后，李维汉参与了政治局常委决策的三件大事：一，决定举行南昌起义，由周恩来、李立三、恽代英、彭湃四人组成起义前敌委员会；」；「陶铸在主持汤池训练班时，就暗中布置在国民党地方政府中任职的共产党员尽量抓住地方武装中的枪杆子，同时指示从汤池合作社的资金中拿出了600元，由八路军武汉办事处从香港买到24支德国造驳壳枪，成立了汤池手枪队。」；「省委决定通过石璞的关系，以培训“农村合作训练班”干部事业的名义，由李范一出面，在湖北应城县汤池和京山、皂市等地举办农村合作事业干部训练班，招收从东北、华北流亡到武汉的大学生和华中、中南地区的大学生，进行短期的政治教育，毕业后分派到湖北各县农村发动群众，准备开展敌后游击战争，并决定派陶铸去具体领导汤池训练班的工作。」

- BEFORE 状态：time_role=unknown, time_owner=（无）; space_role=relation_location, space_owner=（无）
- AFTER 状态：time_role=unknown, time_owner=（无）; space_role=unknown, space_owner=（无）
- **Judge A（BEFORE_BETTER）**：证据明确指出汤池训练班在湖北应城县汤池举办，且陶铸被派往该地具体领导该组织，因此“汤池”是主客体领导关系成立的空间范围，符合relation_location定义。
- **Judge B（BEFORE_BETTER）**：证据明确表述陶铸具体领导并主持汤池训练班，因此“汤池”是该领导关系成立的地点；时间信息缺失，双方均标注为unknown。

#### SA-0012（other，聚合=AFTER_BETTER，证据=lexical）

**断言（payload 原文）**：

```
断言：四〇八团（Organization） —raw:发生于→ 田心铺（Place）
时间：原始表述：解放战争；规范表述：1945年8月-1949年9月；区间：1945-08-16 至 1949-09-30；精度：period
空间：原始表述：湖南区域
```

**payload 证据句**：「7日早晨，我师侦察参谋宋文忠同志率十名侦察员和一名司号员共12人，由火田渡去田心铺联络四〇八团。」

- BEFORE 状态：time_role=biographical, time_owner=四〇八团; space_role=context_location, space_owner=（无）
- AFTER 状态：time_role=context_time, time_owner=（无）; space_role=context_location, space_owner=（无）
- **Judge A（AFTER_BETTER）**：证据表明田心铺仅为联络目的地而非事件发生地，属背景地点；“解放战争”为宽泛历史时期，属背景时间而非人物生平时间，故a方案更符合原文语义。
- **Judge B（AFTER_BETTER）**：证据描述的是部队在田心铺开展联络行动的历史情境，未涉及四〇八团的生平信息，因此时间标注为背景时间比生平时间更符合原文。

## 5. 生产规则把什么改坏了（基于证据句的模式）

`final_entity_type_scope_closure`（实体类型 scope 收口）在 208 条上只做了三类机械动作，其中两类在 judge 可见的原文证据面前被系统性判负：

1. **`event_location→context_location`（最大损害源：n=90，占全部任务 43.3%）**：把“事件发生地”降格为“背景地点”，且 90/90 全部把 space owner 移除。判 BEFORE 更好的票理由几乎全是事件定位类（EVENT_LOC_MATCH×19、EVENT_LOCATION_SUPPORTED×15、SPACE_EVENT_SUPPORTED×8）；证据句是事件叙事（如 SA-0010 中「随后，在第二天下午，根据天真同志约定的地点即贵阳大西门中山公园（现贵阳市委机关所在地）内会见了林青同志。」），地点显然属于事件本身，规则却把它改判为“仅提供背景”，judge 直接引证据句反驳。AFTER 仅 7:52，p<0.001。
2. **`mixed`（塌得最彻底：AFTER 0 : BEFORE 11，p=0.002）**：time 与 space 同时改写（event_occurrence+event_location → relation_validity+relation_location），且 16/16 双 owner 全部移除。BEFORE 胜票理由全部是事件性质类（EVENT_NATURE×3、EVENT_LOCATION_AND_OCCURRENCE×3、EVENT_ROLE_MATCH×3）——证据句（如 SA-0016 中「第二编（1921—1949）  党派、各阶层代表人士热烈响应。  1948年9月至1949年1月，中国人民解放军同国民党军主力进行战略决战，连续取得辽沈、淮海、平津三大战役的胜利。  1948年12月，中国人民银行成立并……」）描述的是具体历史事件，judge 视双重改写为把动态事件降格成抽象关系，无一例接受 AFTER。
3. **`unknown→event_occurrence`（唯一正收益：AFTER 23 : BEFORE 4，p<0.001）**：规则把原本“无法判断”的时间补判为事件发生时间，并把主体实体指派为 time owner（60/60 assigned），方向与证据一致；AFTER 胜票理由为 TIME_ROLE_MATCH×9、TIME_ROLE_CORRECT×7 等，judge 认可这是修复。
4. **`other`（主要为 biographical→context_time，25/37）**：把人物生平时间改判为背景时间（time owner removed 27/37）。方向上偏 AFTER（8:4）但无共识：DISAGREE 21/37，其中 AFTER|BOTH_WRONG 10、AFTER|INSUFFICIENT 6——Judge A 偏 AFTER 时 Judge B 常判两案皆错/证据不足，不足以定论。`event_location→relation_location`（n=5）方向与第 1 类相同但样本过小（decided=1）。

共性模式：**规则把“事件性”scope 系统性降格（event_* → context/relation_*，并移除 owner），而语料证据句恰恰以事件叙事为主**；唯一被认可的改动方向是把 unknown 补判成事件时间。

## 6. Selective Scope Closure 数据驱动建议

规则（写死于脚本常量，可复现）：decided = 两票一致的 AFTER+BEFORE；双侧精确二项检验（H0: p=0.5），p<0.05 且 decided≥10 才允许下结论。

| 类别 | 建议 | 数据依据 |
|---|---|---|
| `unknown→event_occurrence` | **REWRITE** | AFTER 23 : BEFORE 4（胜率 85.2%，p=0.000，n=60） |
| `event_location→context_location` | **RETAIN** | AFTER 7 : BEFORE 52（胜率 11.9%，p=0.000，n=90） |
| `event_location→relation_location` | **UNRESOLVED** | AFTER 0 : BEFORE 1（胜率 0.0%，p=1.000，n=5） |
| `mixed` | **RETAIN** | AFTER 0 : BEFORE 11（胜率 0.0%，p=0.001，n=16） |
| `other` | **UNRESOLVED** | AFTER 8 : BEFORE 4（胜率 66.7%，p=0.388，n=37） |
| `time_owner_change` | （本数据集为 0 条） | owner 变更从不脱离 role 变更单独发生 |
| `space_owner_change` | （本数据集为 0 条） | owner 变更从不脱离 role 变更单独发生 |

落地含义：

- **RETAIN（维持 before，不再产出 after 改写）**：`event_location→context_location`（7:52，p<0.001）与 `mixed`（0:11，p=0.002）。这两类是 BEFORE 支持率高于 AFTER 的主要来源，继续改写只会继续丢分。
- **REWRITE（保留 after 改写）**：`unknown→event_occurrence`（23:4，p<0.001）。这是规则真正把“无法判断”修复成事件时间的一类，应保留并推广其模式。
- **UNRESOLVED（挂起，不进入自动改写）**：`event_location→relation_location`（n=5，decided=1）与 `other`（8:4 但 21/37 DISAGREE，其中 AFTER|BOTH_WRONG 10、AFTER|INSUFFICIENT 6——一票偏 AFTER 时另一票常判两案皆错/证据不足）。样本或共识不足，应送人工/更强证据通道，而非自动采纳任何方向。

## 附录 A：实际 role 组合全表（含 other 的展开）

| time: source→final | space: source→final | n | 归入类型 |
|---|---|---:|---|
| unknown→event_occurrence (owner changed) | event_location→event_location (owner same) | 52 | `unknown→event_occurrence` |
| context_time→context_time (owner same) | event_location→context_location (owner changed) | 47 | `event_location→context_location` |
| unknown→unknown (owner same) | event_location→context_location (owner changed) | 41 | `event_location→context_location` |
| biographical→context_time (owner changed) | context_location→context_location (owner same) | 20 | `other` |
| event_occurrence→relation_validity (owner changed) | event_location→relation_location (owner changed) | 16 | `mixed` |
| unknown→event_occurrence (owner changed) | unknown→unknown (owner same) | 8 | `unknown→event_occurrence` |
| biographical→context_time (owner changed) | unknown→unknown (owner same) | 5 | `other` |
| unknown→unknown (owner same) | context_location→unknown (owner same) | 4 | `other` |
| unknown→unknown (owner same) | event_location→relation_location (owner changed) | 4 | `event_location→relation_location` |
| biographical→biographical (owner same) | event_location→context_location (owner changed) | 2 | `event_location→context_location` |
| unknown→unknown (owner same) | relation_location→unknown (owner same) | 2 | `other` |
| event_occurrence→relation_validity (owner changed) | unknown→unknown (owner same) | 2 | `other` |
| relation_validity→relation_validity (owner same) | relation_location→unknown (owner same) | 2 | `other` |
| unknown→unknown (owner same) | biographical_location→relation_location (owner same) | 1 | `other` |
| context_time→context_time (owner same) | event_location→relation_location (owner changed) | 1 | `event_location→relation_location` |
| source_document_time→relation_validity (owner same) | relation_location→relation_location (owner same) | 1 | `other` |

## 附录 B：数据与脚本

- 判票：`experiments/01_reference_rebuild/raw_runs/scope_revalidation_v2/{A,B}.jsonl`
- 展示位映射：`experiments/01_reference_rebuild/payloads/SCOPE_REVALIDATION_V2_AB_MAPPING.csv`
- 证据可得性：`experiments/01_reference_rebuild/payloads/SCOPE_REVALIDATION_V2_METADATA.csv`（direct 25 / lexical 180 / none 3）
- 任务上下文：`final_submission_v3/experiments/10_structural_validation/SCOPE_ADJUSTMENT_TASKS.jsonl`
- 逐条明细：`SCOPE_BY_TYPE_ERRORS.csv`（208 行，含每票解码值与断言摘要）
- 机器可读汇总：`SCOPE_BY_TYPE_SUMMARY.json`
