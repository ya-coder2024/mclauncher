# -*- coding: utf-8 -*-
"""下载管理器：后台线程下载版本 json 与 client.jar，向 UI 发信号"""

import json as jsonlib
from pathlib import Path

import requests
from PyQt5.QtCore import QThread, pyqtSignal

from core.downloader import download_file, requests_get

# 启用镜像时，把官方域名替换为 BMCLAPI（路径保持一致）
_OFFICIAL_HOSTS = (
    "https://piston-meta.mojang.com",
    "https://piston-data.mojang.com",
    "https://launchermeta.mojang.com",
)
_MIRROR_BASE = "https://bmclapi2.bangbang93.com"


class DownloadManager(QThread):
    progress = pyqtSignal(int)     # 0-100
    status = pyqtSignal(str)       # 状态文字
    finished_ok = pyqtSignal(str)  # 完成，参数为版本 id
    failed = pyqtSignal(str)       # 失败原因

    def __init__(self, version_id, version_url, game_dir, use_mirror=True):
        super().__init__()
        self.version_id = version_id
        self.version_url = version_url
        self.game_dir = Path(game_dir)
        self.use_mirror = use_mirror
        self._stop = False

    def stop(self):
        self._stop = True

    def _url(self, url):
        if self.use_mirror:
            for host in _OFFICIAL_HOSTS:
                if url.startswith(host):
                    return _MIRROR_BASE + url[len(host):]
        return url

    def run(self):
        vid = self.version_id
        vdir = self.game_dir / "versions" / vid
        try:
            # 1. 拉取版本 json
            self.status.emit(f"正在获取 {vid} 版本信息…")
            r = requests_get(self._url(self.version_url), timeout=30, retries=3)
            r.raise_for_status()
            data = r.json()

            if self._stop:
                return

            vdir.mkdir(parents=True, exist_ok=True)
            (vdir / f"{vid}.json").write_text(r.text, encoding="utf-8")

            # 2. 下载 client.jar
            client = data.get("downloads", {}).get("client", {})
            url = client.get("url")
            if not url:
                self.failed.emit("版本信息中缺少客户端下载地址")
                return

            total_size = client.get("size", 0)
            self.status.emit(f"正在下载 {vid} 客户端…")

            def cb(done, t):
                t = t or total_size
                if t:
                    self.progress.emit(int(done / t * 100))

            download_file(
                self._url(url),
                vdir / f"{vid}.jar",
                sha1=client.get("sha1"),
                progress_cb=cb,
                cancel=lambda: self._stop,
                fallback_url=url if self.use_mirror else None,
            )
            if self._stop:
                self.status.emit("下载已取消")
                return

            self.finished_ok.emit(vid)
        except InterruptedError:
            self.status.emit("下载已取消")
        except Exception as e:
            self.failed.emit(str(e))
