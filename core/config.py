# -*- coding: utf-8 -*-
"""全局配置 + 启动器设置持久化"""

import json
import sys
from pathlib import Path

# 基目录：打包后用 exe 所在目录，开发时用项目根目录
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

# 游戏根目录（启动器同目录下的 .minecraft，后续可在设置页修改）
GAME_DIR = BASE_DIR / ".minecraft"

# 当前启动器版本（发版时更新；与 GitHub Release tag 一致）
APP_VERSION = "v1.1"

_SETTINGS_PATH = GAME_DIR / "launcher_settings.json"

_DEFAULTS = {
    "memory_mb": 2048,        # 最大内存（MB）
    "width": 854,             # 窗口分辨率
    "height": 480,
    "jvm_args": "",           # 追加 JVM 参数（如 -XX:+UseG1GC）
    "java_path": "",          # 全局自定义 java.exe，留空自动检测
    "per_version_java": {},   # {版本id: java.exe 路径}，优先于全局
    "isolation": False,       # 版本隔离：游戏数据（存档/模组/配置）放进版本目录
    "per_version_isolation": {},  # {版本id: True/False}，覆盖全局隔离设置
}


class Settings:
    """启动器设置：读写在 .minecraft/launcher_settings.json"""

    def __init__(self, game_dir=None):
        self._path = Path(game_dir) / "launcher_settings.json" if game_dir else _SETTINGS_PATH
        self.data = dict(_DEFAULTS)
        self.load()

    def load(self):
        try:
            saved = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                self.data.update(saved)
        except Exception:
            pass  # 文件缺失/损坏时用默认值
        # 保证嵌套 dict 类型正确
        if not isinstance(self.data.get("per_version_java"), dict):
            self.data["per_version_java"] = {}
        if not isinstance(self.data.get("per_version_isolation"), dict):
            self.data["per_version_isolation"] = {}

    def save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def __getattr__(self, name):
        try:
            return self.data[name]
        except KeyError:
            raise AttributeError(name)

    def java_for(self, vid):
        """某版本实际生效的 Java 路径：版本专属 > 全局 > None（自动）"""
        return self.data["per_version_java"].get(vid) or self.data.get("java_path") or None

    def set_java_for(self, vid, path):
        """设置/清除版本专属 Java（path 为空字符串表示清除）"""
        pv = self.data["per_version_java"]
        if path:
            pv[vid] = path
        else:
            pv.pop(vid, None)
        self.save()

    def isolation_for(self, vid):
        """某版本是否启用版本隔离：版本专属覆盖 > 全局开关"""
        override = self.data["per_version_isolation"].get(vid)
        if override is not None:
            return bool(override)
        return bool(self.data.get("isolation"))

    def set_isolation_for(self, vid, state):
        """设置版本专属隔离：state=None 跟随全局，True/False 强制开/关"""
        pv = self.data["per_version_isolation"]
        if state is None:
            pv.pop(vid, None)
        else:
            pv[vid] = bool(state)
        self.save()
