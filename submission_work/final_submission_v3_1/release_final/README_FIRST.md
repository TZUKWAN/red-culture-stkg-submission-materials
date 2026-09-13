# README_FIRST — 长江流域中共党史时空知识图谱（FINAL 发布包）

> 普通用户只需读本文件即可完成验证、复现与图谱浏览。

## 这是什么

一套以**证据语义门**为核心的时空知识图谱（STKG）研究发布物：

- **424,150** 条全库断言；其中 **112,158** 条旧 strict 宇宙经 qwen3.5-4b 证据语义门
  逐条判定，分入三层：**STRICT 31,067 / CONTEXTUAL 31,282 / UNRESOLVED 49,809**（零持留）。
- 三层是**机器形成的规范化映射结果的确定性分级**，不是史料可信度评级。
- 每条判定可回溯：断言 → 五档判定（含置信度/引文/模型原话）→ 溯源指针 → 文献页码。

## 三分钟上手

```bat
cd release_final
:: 1. 一键离线复现（无网络、无 LLM，约 10 秒）
python reproduce\replay_all.py

:: 2. 打开图谱浏览器（本地 Web UI，自动打开浏览器）
python app\server.py --port 8080
```

浏览器首页点「验证」按钮可核对最终数据库 SHA256 与 `manifests/FINAL_NUMBERS.json`
的记录是否一致。

## 目录速览

| 路径 | 内容 |
|---|---|
| `data/red_culture_stkg_final.sqlite` | 最终数据库（只读使用；SHA256 见 FINAL_NUMBERS.json） |
| `app/` | 图谱浏览器（纯标准库后端 + WebGL 前端） |
| `reproduce/replay_all.py` | Level-A 离线精确回放（审稿人一键复现） |
| `audit/` | 基线快照、checkpoint 完整性报告、重放对账、回放报告 |
| `manifests/` | UNIVERSE_LEDGER、FINAL_NUMBERS（论文数字唯一权威源）、FINAL_DB_MANIFEST |
| `configs/` | 冻结 policy、冻结 prompt、预注册质量审计协议 |
| `experiments/quality_audit/` | 独立双裁判盲评样本/判定/评分 |
| `docs/` | REPRODUCE / DATA_DICTIONARY / METHOD_MAP / MODEL_MANIFEST / AUDIT_TRAIL / KNOWN_LIMITATIONS |

## 论文数字从哪来

**一律引用 `manifests/FINAL_NUMBERS.json`**（每条带 universe/definition/SQL/状态）。
注意区分两个宇宙：

- 证据门宇宙 = 旧 strict 重分层宇宙 = **112,158**（三层 31,067/31,282/49,809）；
- 全库断言宇宙 = **424,150**（全库三层：strict_semantic 31,067 / contextual 299,329 /
  unresolved 93,754，后者包含未重分层的历史口径部分）。

禁止把 112,158 的三层结果直接说成"全库 424,150 的三层结果"。
