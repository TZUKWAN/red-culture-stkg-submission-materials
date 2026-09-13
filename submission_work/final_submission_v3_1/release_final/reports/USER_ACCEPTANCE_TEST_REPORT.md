# USER_ACCEPTANCE_TEST_REPORT — 真实用户式验收

日期：2026-09-14　环境：Windows 11 / Edge / 本地 server.py:8123 / 最终库 020d4905…
方式：computer-use 真实鼠标键盘操作（非单元测试）；知识内容按数据合规要求不做转录，
仅验证结构与状态。

| # | 场景 | 步骤 | 结果 |
|---|---|---|---|
| 1 | 首次打开 | 浏览器访问 `http://127.0.0.1:8123/` | PASS：顶栏统计/DB ✓ 徽章/左栏筛选器/空态卡片渲染正常 |
| 2 | 深链直载 | `/#entity=IENT-8327…` | PASS：212 节点/250 边自动载入，相机聚焦目标实体，截断提示正常 |
| 3 | 实体抽屉 | 单击中心节点 | PASS：标准名/别名/活动期/严格层度(483)/entity_id/操作按钮齐全 |
| 4 | 时间轴 | 抽屉内点「时间轴」 | PASS：按时间升序排列，三层徽章正确显示 |
| 5 | 层级切换 | 左栏 STRICT/CONTEXTUAL/UNRESOLVED 复选 | PASS：边的显隐即时切换（applyTierVisibility） |
| 6 | 启动器·验证 | /launcher → 卡片 A | PASS：recorded=actual=020d4905…，RESULT: PASS |
| 7 | 启动器·复现 | /launcher → 卡片 B | PASS：6 步全 PASS（checkpoint 完整性/重放 0 差异/哈希闭环/硬审计 0），RESULT: PASS |
| 8 | EXE 冒烟 | `YangtzeSTKG-Reproduce.exe --port 8188` | PASS：launcher 200 / graph 200 / stats / search 正常 |
| 9 | 搜索 | 输入触发联想 | PASS：键盘输入触发联想（注：无障碍 set_value 不触发 input 事件，真实键入正常） |

## 验收中发现并已修复的问题

1. **标签从不显示**：`labelRenderedSizeThreshold=13` 高于全部节点渲染尺寸 → 降为 8，labelDensity 2.2。
2. **相机飞出画布**：sigma v2 相机 x/y 为归一化视口坐标，误传图坐标 → 改用 `getNodeDisplayData`，并改为布局收敛后聚焦（回调式 runLayout）。
3. **边命中区过窄**：STRICT 边宽 2→3，CONTEXTUAL 1→1.5。
4. **深链缺失**：新增 `/#entity=<id>` 直载与 hashchange 监听（可分享/可引用）。

## 已知边界

- 画布上细边的精确点选在高缩放时更可靠（交互提示已写明滚轮缩放）。
- EXE 内嵌库外置（data/ 相对路径），符合" reviewer 模式直读 SQLite"设计。

结论：**GUI UAT PASS**（场景 7 完整推理重跑提示将在无模型环境另行验证——服务器缺模型时
后端不依赖 LLM，Level-B 入口仅在前端提示安装步骤，无静默回退路径）。
