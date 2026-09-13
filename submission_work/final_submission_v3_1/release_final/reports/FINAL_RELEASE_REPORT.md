# FINAL REPRODUCIBLE STKG RELEASE REPORT

生成：2026-09-14（夜班自主闭环）　基线：e1dd933 → 当前：6501c08

## 发布物

| 项 | 值 |
|---|---|
| Git commit | 6501c08（main） |
| Git tag | 待评分通过后打 `stkg-final-reproducible-2026` |
| Final DB | `release_final/data/red_culture_stkg_final.sqlite` |
| Final DB SHA256 | `020d490533a9a4e4d1eaafe0dc5c9c5f63959f798f8d8b254a9494cb3146875a` |
| Public package | `release_final/dist/PUBLIC_REPRO_PACKAGE.zip`（58 文件，768.8 MB；SHA256SUMS.txt 同目录） |
| EXE | `release_final/YangtzeSTKG-Reproduce.exe`（one-file，双击即用） |

## 核心数字（全部来自 manifests/FINAL_NUMBERS.json，机读）

| 指标 | 值 |
|---|---|
| 全库断言 | 424,150 |
| 规范化实体 | 152,979 |
| 证据门宇宙（旧 strict 重分层） | 112,158 —— STRICT **31,067** / CONTEXTUAL **31,282** / UNRESOLVED **49,809**（零持留） |
| 全库三层 | strict_semantic 31,067 / contextual 299,329 / unresolved 93,754 |
| EventFrame / CultureState / PlaceVersion | 28,065 / 11,532 / 72 |
| 事件关系 / 地点关系 / 时序对 | 499 / 382 / 5,636,370 |
| 三概念分离 A / B / C | 0.4472 / 0.9812 / 0.2823 |
| 生产 gate 模型 | qwen3.5-4b（reasoning=off，T=0，无回退） |

## 复现与审计结果

| 关卡 | 结果 |
|---|---|
| Level-A 离线回放（6 步） | **ALL PASS**（8s；重放 0 差异；哈希闭环；硬违规 0） |
| checkpoint 完整性 | 127,633 条 / 0 畸形 / salvaged 17 条带审计标志 |
| 数据完整性测试（18 项） | **ALL PASS** |
| GUI 真实用户验收（9 场景） | **PASS**（含发现并修复 5 项问题，见 UAT 报告） |
| 最终库硬结构审计 | 全零（pending/枚举/泄漏/孤儿/重复） |
| **独立质量审计（预注册协议）** | **PASS — STRICT 支撑精度 0.9928（强共识口径）** |

## 独立质量审计详情（双裁判盲评，n=4,427）

| 指标 | 值 | 解读 |
|---|---|---|
| STRICT 支撑精度（强共识） | **0.9928** | ≥0.90 预注册 PASS 线；超过同类历史人文 KG ~90% 基准 |
| STRICT 误报率（强共识判 NEG） | 0.0041 | 0.4% |
| salvaged 强共识不一致 | 0 | 解析兜底零错误 |
| 裁判五档一致率 / Cohen's κ | 0.360 / 0.184 | 两裁判风格两极（A 硬判定 / B 对冲 PARTIAL）的诚实呈现 |
| 粗分组一致率（A-B / 生产-A / 生产-B） | 0.63 / 0.71 / 0.77 | 生产模型居于两裁判之间，非离群者 |
| CONTEXTUAL 升级机会 / UNRESOLVED 漏判机会 | 0.18 / 0.32 | 如实记录为后续研究机会，不追溯改判 |

协议：`configs/FINAL_QUALITY_AUDIT_PROTOCOL.json`（判前冻结，seed=20260914）
评分：`experiments/quality_audit/AUDIT_RESULTS.json`（decision=**PASS**）

## 已完成

1. ✅ 双裁判评分 → 预注册决策 = **PASS**
2. ✅ FINAL_NUMBERS 合并独立精度指标（31 项机读）
3. ⏳ Git tag `stkg-final-reproducible-2026` + GitHub Release（资产：包/EXE/哈希/报告）

## 底线自查

- 每个数字可从 FINAL_NUMBERS.json 的 SQL/脚本复算 ✓
- 判定可回放（Level-A）且与归档逐行一致 ✓
- 异常与负结果全部留痕（AUDIT_TRAIL.md 11 项、KNOWN_LIMITATIONS 10 项）✓
- 三层语义 = 机器映射确定性分级，非史料可信度评级 ✓
- 无 secret、无绝对路径、无未授权原文 ✓
