# -*- coding: utf-8 -*-
"""Modrinth 项目图标缓存：异步下载、本地缓存、QPixmap 直接可用"""

import hashlib
from pathlib import Path

import requests
from PyQt5.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt5.QtGui import QPixmap, QImage

from core.config import GAME_DIR

_CACHE_DIR = Path(GAME_DIR) / "launcher-cache" / "icons"
_cache = {}


def _key(url):
    return hashlib.md5(url.encode("utf-8")).hexdigest()


class IconSignals(QObject):
    loaded = pyqtSignal(str, QPixmap)  # url, pixmap


class _FetchThread(QThread):
    done = pyqtSignal(str, bytes)   # url, data
    failed = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self._url = url

    def run(self):
        try:
            r = requests.get(self._url, timeout=15)
            r.raise_for_status()
            self.done.emit(self._url, r.content)
        except Exception:
            self.failed.emit(self._url)


class IconManager(QObject):
    """全局单例：根据 url 取 QPixmap，未缓存则后台下载后发射 loaded 信号"""

    _inst = None
    loaded = pyqtSignal(str, QPixmap)

    def __init__(self):
        super().__init__()
        self._pending = {}
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def instance(cls):
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst

    def get(self, url, size=40):
        """同步获取已缓存图标；未缓存返回 None 并触发后台下载。
        下载完成后通过 IconManager.instance().loaded 信号广播。
        """
        if not url:
            return None
        k = _key(url)
        if k in _cache:
            return _cache[k]
        fp = _CACHE_DIR / f"{k}.img"
        if fp.is_file():
            pm = self._load(fp, size)
            if pm:
                _cache[k] = pm
                return pm
        self._fetch(url)
        return None

    def _load(self, path, size):
        img = QImage(str(path))
        if img.isNull():
            return None
        pm = QPixmap.fromImage(img).scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return pm

    def _fetch(self, url):
        if url in self._pending:
            return
        th = _FetchThread(url)
        self._pending[url] = th
        th.done.connect(self._on_done)
        th.failed.connect(self._on_failed)
        th.start()

    def _on_done(self, url, data):
        self._pending.pop(url, None)
        k = _key(url)
        try:
            (_CACHE_DIR / f"{k}.img").write_bytes(data)
        except OSError:
            pass
        img = QImage.fromData(data)
        if img.isNull():
            return
        pm = QPixmap.fromImage(img).scaled(40, 40, Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation)
        _cache[k] = pm
        self.loaded.emit(url, pm)

    def _on_failed(self, url):
        self._pending.pop(url, None)
