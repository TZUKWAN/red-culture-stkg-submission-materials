# -*- coding: utf-8 -*-
"""launch_stkg.py — YangtzeSTKG 一键入口（PyInstaller 打包目标）。

双击即启动本地服务并打开启动器页（验证 / 复现 / 浏览 / 数据）。
冻结模式下包根 = EXE 所在目录；源码模式下为 release_final/。
"""
import sys

if "--page" not in sys.argv:
    sys.argv += ["--page", "/launcher"]

import server  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(server.main())
