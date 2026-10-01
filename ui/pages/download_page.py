# -*- coding: utf-8 -*-
"""下载页：版本清单列表（分类筛选 + 搜索）+ 版本核心文件下载"""

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QProgressBar, QFrame, QComboBox,
)

from core.config import GAME_DIR
from core.version_manifest import fetch_manifest
from core.download_manager import DownloadManager
from core import loader_install

_LOADER_CHOICES = [("Fabric（轻量，更新快）", "fabric"),
                   ("Quilt（Fabric 分支）", "quilt"),
                   ("Forge（老牌，模组多）", "forge"),
                   ("NeoForge（Forge 续作）", "neoforge")]

_TYPE_NAMES = {
    "release": "正式版",
    "snapshot": "快照",
    "old_beta": "古老",
    "old_alpha": "古老",
}
_TABS = [("全部", None), ("正式版", "release"), ("快照", "snapshot"), ("古老", "old")]


class ManifestLoader(QThread):
    """后台拉取版本清单，避免阻塞界面"""
    loaded = pyqtSignal(str, list)
    failed = pyqtSignal(str)

    def run(self):
        try:
            source, versions = fetch_manifest()
            self.loaded.emit(source, versions)
        except Exception as e:
            self.failed.emit(str(e))


class LoaderInstallThread(QThread):
    """后台一键安装模组加载器（Fabric/Quilt/Forge/NeoForge）"""
    status = pyqtSignal(str)
    installed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, kind, mc_version):
        super().__init__()
        self._kind = kind
        self._mc = mc_version

    def run(self):
        try:
            new_id = loader_install.install_loader(
                self._kind, GAME_DIR, self._mc, status_cb=self.status.emit)
            self.installed.emit(new_id)
        except loader_install.LoaderError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f"安装出错：{e}")


class DownloadPage(QWidget):
    def __init__(self):
        super().__init__()
        self._versions = []
        self._version_type = None
        self._downloader = None
        self._loader_worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        title = QLabel("下载", objectName="pageTitle")
        root.addWidget(title)

        # ---- 筛选行：分类 + 搜索 ----
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self._tab_buttons = []
        for name, tab in _TABS:
            b = QPushButton(name, objectName="small")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, t=tab: self._set_tab(t))
            filter_row.addWidget(b)
            self._tab_buttons.append(b)
        self._tab_buttons[0].setChecked(True)

        filter_row.addStretch()
        self.search_box = QLineEdit(placeholderText="搜索版本…")
        self.search_box.setFixedWidth(200)
        self.search_box.textChanged.connect(self._refresh_list)
        filter_row.addWidget(self.search_box)
        root.addLayout(filter_row)

        # ---- 版本列表 ----
        self.list = QListWidget(objectName="versionList")
        self.list.setSelectionMode(self.list.SingleSelection)
        root.addWidget(self.list, 1)

        # ---- 底部：进度条 + 状态 + 下载按钮 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.progress = QProgressBar(objectName="downloadProgress")
        self.progress.setFixedHeight(10)
        self.progress.setTextVisible(False)
        self.progress.hide()
        bottom.addWidget(self.progress, 1)
        self.status_label = QLabel("正在加载版本列表…", objectName="cardDesc")
        bottom.addWidget(self.status_label)
        self.btn_download = QPushButton("下载所选版本", objectName="small")
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self._start_download)
        bottom.addWidget(self.btn_download)

        self.loader_box = QComboBox()
        self.loader_box.setFixedWidth(190)
        for label, key in _LOADER_CHOICES:
            self.loader_box.addItem(label, key)
        bottom.addWidget(self.loader_box)
        self.btn_loader = QPushButton("安装加载器", objectName="small")
        self.btn_loader.setEnabled(False)
        self.btn_loader.clicked.connect(self._install_loader)
        bottom.addWidget(self.btn_loader)
        root.addLayout(bottom)

        self.list.itemSelectionChanged.connect(self._on_select)
        self._load_manifest()

    # ---------- 清单加载 ----------
    def _load_manifest(self):
        self.loader = ManifestLoader()
        self.loader.loaded.connect(self._on_manifest)
        self.loader.failed.connect(self._on_manifest_failed)
        self.loader.start()

    def _on_manifest(self, source, versions):
        self._versions = versions
        self.status_label.setText(f"下载源：{source} · 共 {len(versions)} 个版本")
        self._refresh_list()

    def _on_manifest_failed(self, err):
        self.status_label.setText(f"版本清单获取失败：{err}")

    # ---------- 筛选 ----------
    def _set_tab(self, tab):
        for i, b in enumerate(self._tab_buttons):
            b.setChecked(_TABS[i][1] == tab)
        self._version_type = tab
        self._refresh_list()

    def _filtered(self):
        kw = self.search_box.text().strip().lower()
        out = []
        for v in self._versions:
            if self._version_type and v.get("type") != self._version_type:
                continue
            if kw and kw not in v.get("id", "").lower():
                continue
            out.append(v)
        return out

    def _refresh_list(self):
        self.list.clear()
        for v in self._filtered():
            item = QListWidgetItem()
            item.setData(Qt.UserRole, v)
            row = self._make_row(v)
            item.setSizeHint(row.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, row)

    def _make_row(self, v):
        w = QFrame()
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 9, 12, 9)
        h.setSpacing(10)
        name = QLabel(v["id"], objectName="cardTitle")
        h.addWidget(name)
        tag = QLabel(_TYPE_NAMES.get(v.get("type"), ""), objectName="cardDesc")
        h.addWidget(tag)
        h.addStretch()
        date = QLabel(str(v.get("releaseTime", ""))[:10], objectName="cardDesc")
        h.addWidget(date)
        return w

    def _on_select(self):
        has = bool(self.list.selectedItems())
        self.btn_download.setEnabled(has)
        self.btn_loader.setEnabled(has and self._loader_worker is None)

    # ---------- 一键安装加载器 ----------
    def _install_loader(self):
        items = self.list.selectedItems()
        if not items or self._loader_worker is not None:
            return
        mc = items[0].data(Qt.UserRole)["id"]
        kind = self.loader_box.currentData()
        kind_label = loader_install.LOADER_LABELS[kind]
        self.btn_loader.setEnabled(False)
        self.status_label.setText(f"正在为 {mc} 安装 {kind_label}…")
        self._loader_worker = LoaderInstallThread(kind, mc)
        self._loader_worker.status.connect(self.status_label.setText)
        self._loader_worker.installed.connect(self._on_loader_done)
        self._loader_worker.failed.connect(self._on_loader_fail)
        self._loader_worker.start()

    def _on_loader_done(self, new_id):
        self._loader_worker = None
        self.status_label.setText(
            f"加载器安装完成：{new_id} —— 回主页即可选择该版本启动")
        self.btn_loader.setEnabled(True)

    def _on_loader_fail(self, err):
        self._loader_worker = None
        self.status_label.setText(f"加载器安装失败：{err}")
        self.btn_loader.setEnabled(True)

    # ---------- 下载 ----------
    def _start_download(self):
        items = self.list.selectedItems()
        if not items or self._downloader is not None:
            return
        v = items[0].data(Qt.UserRole)

        self._downloader = DownloadManager(v["id"], v["url"], GAME_DIR)
        self._downloader.progress.connect(self.progress.setValue)
        self._downloader.status.connect(self.status_label.setText)
        self._downloader.finished_ok.connect(self._on_done)
        self._downloader.failed.connect(self._on_fail)
        self.progress.show()
        self.progress.setValue(0)
        self.btn_download.setEnabled(False)
        self._downloader.start()

    def _on_done(self, vid):
        self.progress.setValue(100)
        self.status_label.setText(f"{vid} 下载完成 → {GAME_DIR / 'versions' / vid}")
        self._downloader = None
        self.btn_download.setEnabled(True)

    def _on_fail(self, err):
        self.status_label.setText(f"下载失败：{err}")
        self.progress.hide()
        self._downloader = None
        self.btn_download.setEnabled(True)
