# Provenance Gate 压力测试（synthetic fault-injection stress test）

> ⚠ **实验性质声明**：本实验是 **synthetic failure-injection stress test**
> （故障注入 / fault injection / negative-control），与真实语料实验**严格区分**。
> 其结果只证明 Provenance Gate 机制本身有效，**不构成**「该门在当前真实数据上
> 显著提高性能」的声明。

## 1. 背景与定位（实事求是）

全库确定性消融（experiments/10_structural_validation 确定性重放，逐行对齐 v2
`run_component_ablations.py`）显示：

- **w/o Provenance Gate 的 `changed_vs_full = 0`**。
- 原因：当前发布数据本身**没有无 provenance 的断言**——所有 112 158 条
  `strict_semantic` 断言均带有至少一条 `research_assertion_provenance` 记录
  （该表共 466 312 行）。

因此，Provenance Gate 在论文中的正确表述是：**它是一个发布安全不变量**
（release safety invariant），而不是在当前语料上产生可观察增益的组件。
为检验该不变量机制是否真正有效，特设计本 negative-control 压力测试。

## 2. 方法

1. **只读基线重放**：以只读模式（`file:...?mode=ro`）打开发布库，逐行复用
   `extract_relation_contract_replay.py` 的连接与查询方式，重放 Full framework
   三层分层，基线计数与发布值核对（strict_semantic / contextual / unresolved
   = 112 158 / 268 047 / 43 945，总 424 150）：**一致**。
2. **故障注入（仅内存，绝不写回数据库）**：对 `strict_semantic` 层按三档比例
   **1% / 5% / 20%** 随机抽取断言，程序化地将其全部 provenance 关联视为已删除
   （`provenance_count := 0`）。基础种子 **20260907**，每档由
   `sha256('20260907|provenance_gate_fault_injection|ratio=<r>')` 派生独立种子，
   注入清单落盘 `PROVENANCE_GATE_FAULT_INJECTION.csv`（含 fact 标识、注入类型、
   注入前后 provenance 计数、派生种子）。
3. **Gate 重放**：按 v2 原始判定 `provenance_pass = provenance_count > 0` 重放
   Provenance Gate，检验被注入断言是否被移出 strict layer。

## 3. 结果

| 注入比例 | 注入数 | 拦截数 | 拦截率 | 对照组误伤数 |
|---|---|---|---|---|
| 1% | 1122 | 1122 | 1.0000 | 0 |
| 5% | 5608 | 5608 | 1.0000 | 0 |
| 20% | 22432 | 22432 | 1.0000 | 0 |

- **三档拦截率均为 100%**：所有被注入故障的断言均被 gate 从 `strict_semantic`
  降级为 `contextual`（`route_pass` 仍为真），无一滞留 strict layer。
- **对照组零变化**：每个比例档下，对全量 424 150 条断言中**未被注入**的部分
  逐条断言级验证 `state_after == state_before`（脚本内 `assert`），误伤数为 0。
  逐条记录见 `PROVENANCE_GATE_STRESS_TEST.csv`（覆盖全部 strict 层断言的
  `injected / gate_blocked / state_before / state_after`）。

## 4. 结论

Provenance Gate 作为**发布安全不变量**机制有效：一旦断言失去全部 provenance
支撑，gate 能 100% 阻止其进入/滞留 strict layer，且不误伤正常断言。
结合真实数据上 `changed_vs_full = 0` 的事实，该门的价值在于**防御未来数据
回归**（任何无来源断言不得进入 strict 发布层），而非提升当前语料指标。

## 5. 可复现性

- 脚本：`code/independent_eval/run_provenance_gate_stress.py`
- 基础种子：20260907（逐档派生见 `PROVENANCE_GATE_STRESS_SUMMARY.json`）
- 数据库：`data/release_databases/red_culture_stkg_final_v2.sqlite`（只读）+
  `red_culture_stkg_semantic_v2.sqlite`（只读 ATTACH），sha256 见 manifest。
- 配套 manifest：`PROVENANCE_GATE_STRESS_MANIFEST.json`（experiment_id、
  database_sha256、种子、timestamp、全部输出 sha256）。
