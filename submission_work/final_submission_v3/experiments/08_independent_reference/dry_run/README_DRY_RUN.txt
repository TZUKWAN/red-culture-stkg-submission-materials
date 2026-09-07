DRY_RUN 演练输出目录
====================

本目录下所有文件均由 `run_judges.py --dry-run` 产生：
- judge 响应是确定性假响应（哈希生成），不来自任何真实模型；
- 每条 raw 记录带 `"dry_run": true`，`reason_code` 为 `DRY_RUN`；
- 共识 CSV 与 manifest 均带 `dry_run: true` 标记。

用途：验证 payload → judge → consensus → IMCR CSV 全链路可运行、输出可解析。

严禁将本目录任何数字用于论文或正式实验报告。
正式 IMCR 结果必须来自真实 judge 运行（配置 JUDGE_{A..E}_* 环境变量后
去掉 --dry-run），输出位于上级目录 experiments/08_independent_reference/。
