# -*- coding: utf-8 -*-
"""启动器自动更新：检查 GitHub Release → 下载新 exe → 脚本替换并重启"""

import os
import subprocess
import sys
from pathlib import Path

import requests
from PyQt5.QtCore import QThread, pyqtSignal

_REPO = "ya-coder2024/mclauncher"
_API = f"https://api.github.com/repos/{_REPO}/releases/latest"
_HEADERS = {"User-Agent": "PCL-MinecraftLauncher", "Accept": "application/vnd.github+json"}
_TIMEOUT = 15


def parse_ver(tag):
    """'v1.2' -> (1, 2)；非数字段忽略"""
    parts = []
    for p in str(tag).lstrip("v").split("."):
        num = "".join(c for c in p if c.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts)


def is_newer(latest, current):
    """latest 版本号是否比 current 新（按段比较数字大小）"""
    a, b = parse_ver(latest), parse_ver(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


class CheckUpdateThread(QThread):
    """后台查询最新 Release。有新版本时 found(tag, url, notes)，否则无信号"""
    found = pyqtSignal(str, str, str)
    failed = pyqtSignal(str)

    def __init__(self, current_version):
        super().__init__()
        self._current = current_version

    def run(self):
        try:
            r = requests.get(_API, headers=_HEADERS, timeout=_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            tag = data.get("tag_name", "")
            if not tag or not is_newer(tag, self._current):
                return
            url = ""
            for a in data.get("assets", []):
                if a.get("name") == "PCLLauncher.exe":
                    url = a.get("browser_download_url", "")
                    break
            if not url:
                return
            notes = data.get("body", "") or ""
            self.found.emit(tag, url, notes)
        except Exception as e:
            self.failed.emit(str(e))


class DownloadUpdateThread(QThread):
    """流式下载新 exe，progress(已下载字节, 总字节)"""
    progress = pyqtSignal(int, int)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url, dest):
        super().__init__()
        self._url = url
        self._dest = Path(dest)
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            self._dest.parent.mkdir(parents=True, exist_ok=True)
            with requests.get(self._url, stream=True, timeout=30,
                              headers={"User-Agent": "PCL-MinecraftLauncher"}) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                got = 0
                with open(self._dest, "wb") as f:
                    for chunk in r.iter_content(256 * 1024):
                        if self._stop:
                            self._dest.unlink(missing_ok=True)
                            return
                        if chunk:
                            f.write(chunk)
                            got += len(chunk)
                            self.progress.emit(got, total)
            self.done.emit(str(self._dest))
        except Exception as e:
            self._dest.unlink(missing_ok=True)
            self.failed.emit(str(e))


def write_updater_bat(old_exe, new_exe):
    """生成替换脚本内容并写入 %TEMP%，返回 bat 路径。

    bat 以 GBK 编码写入（cmd 默认代码页），兼容中文路径。
    """
    bat = Path(os.environ.get("TEMP", str(Path.home()))) / "pcl_updater.bat"
    content = (
        "@echo off\r\n"
        f"set TARGET_PID={os.getpid()}\r\n"
        ":waitloop\r\n"
        'tasklist /fi "PID eq %TARGET_PID%" | find "%TARGET_PID%" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "    ping 127.0.0.1 -n 2 >nul\r\n"
        "    goto waitloop\r\n"
        ")\r\n"
        f'copy /y "{new_exe}" "{old_exe}" >nul\r\n'
        "if errorlevel 1 (\r\n"
        "    echo Update failed. Press any key to exit.\r\n"
        "    pause >nul\r\n"
        "    exit /b 1\r\n"
        ")\r\n"
        f'start "" "{old_exe}"\r\n'
        f'del "{new_exe}"\r\n'
        '(goto) 2>nul & del "%~f0"\r\n'
    )
    bat.write_text(content, encoding="gbk")
    return bat


def launch_updater(old_exe, new_exe):
    """写替换脚本并启动：等待本进程退出 → 覆盖 exe → 重启 → 自清理"""
    bat = write_updater_bat(old_exe, new_exe)
    # CREATE_NO_WINDOW：不弹黑框
    subprocess.Popen(["cmd", "/c", str(bat)], close_fds=True,
                     creationflags=0x08000000)


def is_packaged():
    """是否为打包后的 exe（仅打包环境启用自动更新）"""
    return bool(getattr(sys, "frozen", False))
