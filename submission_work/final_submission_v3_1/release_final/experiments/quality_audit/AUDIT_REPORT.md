# FINAL QUALITY AUDIT REPORT（独立双裁判盲评）

- 生成：2026-09-14T06:40:59.920643+08:00
- 样本：4427 条（协议冻结 n）；两裁判共同有效判定：4427
- 裁判：Judge A = gpt-oss-20b，Judge B = qwen/qwen3-8b（均为本地、独立于生产模型 qwen3.5-4b）

## 主指标
| 指标 | 数值 |
|---|---|
| 裁判五档完全一致率 | 0.3598 |
| Cohen's kappa | 0.1838 |
| 弱共识率（粗分组一致） | 0.2593 |
| STRICT 支撑精度（强共识口径） | **0.9928** |
| FULLY 精度 | 0.8066 |
| STRICT 误报率（强共识判 UNSUP/CONTRA） | 0.0041 |
| CONTEXTUAL 升级机会 | 0.18 |
| UNRESOLVED 漏判机会 | 0.3173 |
| salvaged 强共识不一致数 | 0/1 |

## 协议决策：**PASS**

（详见 AUDIT_RESULTS.json；分层分解见 by_stratum。）
