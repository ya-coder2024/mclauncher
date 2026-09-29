# -*- coding: utf-8 -*-
"""全局配置"""

import sys
from pathlib import Path

# 基目录：打包后用 exe 所在目录，开发时用项目根目录
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

# 游戏根目录（启动器同目录下的 .minecraft，后续可在设置页修改）
GAME_DIR = BASE_DIR / ".minecraft"
