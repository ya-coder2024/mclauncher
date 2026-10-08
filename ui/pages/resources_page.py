# -*- coding: utf-8 -*-
"""资源页：资源包 / 光影（搜索下载 + 本地管理）、存档管理"""

import os
import shutil
import subprocess
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTabWidget, QMessageBox, QLineEdit,
    QComboBox,
)

from core.config import GAME_DIR, Settings
from core import mod_repo
from core.downloader import download_file, file_ok
from core.icon_cache import IconManager
from core.safe_thread import start_worker
from ui import theme


def _open_folder(path):
    """用系统文件管理器打开目录"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(f'explorer "{p}"')


def _dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


# ---------------- 本地扫描 ----------------

class _ScanThread(QThread):
    done = pyqtSignal(list)  # [(名称, 完整路径, 描述)]

    def __init__(self, directory, kind):
        super().__init__()
        self._dir = Path(directory)
        self._kind = kind

    def run(self):
        items = []
        try:
            if not self._dir.is_dir():
                self.done.emit([])
                return
            for p in sorted(self._dir.iterdir(), key=lambda x: x.name.lower()):
                if self._kind == "saves":
                    if p.is_dir() and (p / "level.dat").is_file():
                        items.append((p.name, str(p), _fmt_size(_dir_size(p))))
                else:
                    # 资源包 / 光影：zip 文件或文件夹
                    if p.is_dir() or p.suffix.lower() == ".zip":
                        desc = "文件夹" if p.is_dir() else _fmt_size(p.stat().st_size)
                        items.append((p.name, str(p), desc))
        except OSError:
            pass
        self.done.emit(items)


class _ResourceTab(QWidget):
    """本地资源标签：列表 + 打开文件夹（+ 删除按钮仅存档用）"""

    def __init__(self, kind, allow_delete=False):
        super().__init__()
        self._kind = kind
        self._allow_delete = allow_delete
        self._scan = None
        self._base = Path(GAME_DIR)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(10)

        tip_text = {
            "resourcepacks": "资源包（纹理/音效等），放入后请在游戏内「选项 → 资源包」中启用。",
            "shaderpacks": "光影包（需安装 OptiFine 或 Iris 加载），放入后请在游戏内选择。",
            "saves": "世界存档。删除操作不可恢复，请谨慎！",
        }[kind]
        self.tip = QLabel(f"{tip_text}\n目录：{self._base / kind}", objectName="cardDesc")
        self.tip.setWordWrap(True)
        root.addWidget(self.tip)

        self.list = QListWidget(objectName="versionList")
        root.addWidget(self.list, 1)

        bottom = QHBoxLayout()
        self.status_label = QLabel("", objectName="cardDesc")
        bottom.addWidget(self.status_label, 1)

        btn_open = QPushButton("打开文件夹", objectName="small")
        btn_open.setFixedHeight(30)
        btn_open.clicked.connect(lambda: _open_folder(self._base / kind))
        bottom.addWidget(btn_open)

        btn_refresh = QPushButton("刷新", objectName="small")
        btn_refresh.setFixedHeight(30)
        btn_refresh.clicked.connect(self.refresh)
        bottom.addWidget(btn_refresh)

        if allow_delete:
            btn_delete = QPushButton("删除存档", objectName="small")
            btn_delete.setFixedHeight(30)
            btn_delete.clicked.connect(self._delete_selected)
            bottom.addWidget(btn_delete)

        root.addLayout(bottom)

    def set_target(self, base_dir):
        """切换管理位置（全局目录或版本隔离目录）"""
        new_base = Path(base_dir)
        if new_base == self._base:
            return
        self._base = new_base
        self.tip.setText(self.tip.text().split("\n")[0]
                         + f"\n目录：{self._base / self._kind}")
        self.refresh()

    def refresh(self):
        if self._scan is not None:
            return
        self.status_label.setText("正在扫描…")
        self._scan = _ScanThread(self._base / self._kind, self._kind)
        self._scan.done.connect(self._on_scanned)
        start_worker(self._scan, parent=self)

    def _on_scanned(self, items):
        self._scan = None
        self.list.clear()
        for name, path, desc in items:
            it = QListWidgetItem(f"{name}    （{desc}）")
            it.setData(Qt.UserRole, path)
            self.list.addItem(it)
        self.status_label.setText(f"共 {len(items)} 项" if items else "目录为空")

    def _delete_selected(self):
        it = self.list.currentItem()
        if not it:
            self.status_label.setText("请先在列表中选中一个存档")
            return
        path = it.data(Qt.UserRole)
        ret = QMessageBox.warning(
            self, "删除存档",
            f"确定要永久删除存档「{Path(path).name}」吗？\n此操作不可恢复！",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        try:
            shutil.rmtree(path)
        except OSError as e:
            self.status_label.setText(f"删除失败：{e}")
            return
        self.refresh()


# ---------------- 搜索下载 ----------------

class _SearchThread(QThread):
    found = pyqtSignal(list, int)
    failed = pyqtSignal(str)

    def __init__(self, kind, query):
        super().__init__()
        self._kind = kind
        self._query = query

    def run(self):
        try:
            fn = (mod_repo.search_resourcepacks if self._kind == "resourcepacks"
                  else mod_repo.search_shaders)
            hits, total = fn(self._query)
            self.found.emit(hits, total)
        except Exception as e:
            self.failed.emit(str(e))


class _DownloadThread(QThread):
    status = pyqtSignal(str)
    done = pyqtSignal(str)       # 保存路径
    failed = pyqtSignal(str)

    def __init__(self, project, dest_dir):
        super().__init__()
        self._project = project
        self._dest_dir = Path(dest_dir)

    def run(self):
        try:
            self.status.emit("正在获取版本列表…")
            versions = mod_repo.list_versions(self._project["project_id"])
            if not versions:
                self.failed.emit("该项目没有可下载的文件")
                return
            version = versions[0]
            files = version.get("files", [])
            pf = next((f for f in files if f.get("primary")), None)
            pf = pf or (files[0] if files else None)
            if not pf:
                self.failed.emit("版本中没有文件")
                return
            url = pf["url"]
            fname = pf.get("filename") or url.rsplit("/", 1)[-1]
            self._dest_dir.mkdir(parents=True, exist_ok=True)
            dest = self._dest_dir / fname
            hashes = pf.get("hashes") or {}
            if file_ok(dest, hashes.get("sha1"), pf.get("size")):
                self.status.emit("已存在，跳过下载")
                self.done.emit(str(dest))
                return
            self.status.emit(f"正在下载 {fname}…")
            download_file(url, dest, sha1=hashes.get("sha1"), timeout=120)
            self.done.emit(str(dest))
        except Exception as e:
            self.failed.emit(str(e))


class DownloadResourceTab(QWidget):
    """从 Modrinth 搜索并下载资源包/光影"""

    def __init__(self, kind):
        super().__init__()
        self._kind = kind
        self._searcher = None
        self._downloader = None
        self._base = Path(GAME_DIR)

        # 全局图标信号只连接一次（槽无状态地遍历当前行）
        IconManager.instance().loaded.connect(self._on_icon_loaded)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(10)

        bar = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索资源包名称，回车搜索")
        self.search_box.returnPressed.connect(self._do_search)
        bar.addWidget(self.search_box, 1)
        btn = QPushButton("搜索", objectName="small")
        btn.clicked.connect(self._do_search)
        bar.addWidget(btn)
        root.addLayout(bar)

        self.list = QListWidget(objectName="versionList")
        root.addWidget(self.list, 1)

        bottom = QHBoxLayout()
        self.status_label = QLabel("输入关键字开始搜索", objectName="cardDesc")
        bottom.addWidget(self.status_label, 1)
        self.btn_install = QPushButton("下载所选", objectName="small")
        self.btn_install.setEnabled(False)
        self.btn_install.clicked.connect(self._do_download)
        bottom.addWidget(self.btn_install)
        root.addLayout(bottom)

        self.list.itemSelectionChanged.connect(
            lambda: self.btn_install.setEnabled(bool(self.list.selectedItems())))
        self.list.itemDoubleClicked.connect(lambda _it: self._do_download())

    def set_target(self, base_dir):
        self._base = Path(base_dir)

    def _do_search(self):
        if self._searcher is not None:
            return
        q = self.search_box.text().strip()
        self.status_label.setText("正在搜索…")
        self._searcher = _SearchThread(self._kind, q)
        self._searcher.found.connect(self._on_found)
        self._searcher.failed.connect(self._on_search_failed)
        start_worker(self._searcher, parent=self)

    def _on_found(self, hits, total):
        self._searcher = None
        self.list.clear()
        for h in hits:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, h)
            it.setSizeHint(self._row_size(h))
            self.list.addItem(it)
            self.list.setItemWidget(it, self._make_row(h))
        self.status_label.setText(f"共 {total} 个结果，双击可直接下载"
                                  if hits else "没有找到相关资源")

    def _row_size(self, h):
        from PyQt5.QtCore import QSize
        return QSize(0, 50)

    def _make_row(self, h):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(10)

        icon_label = QLabel()
        icon_label.setFixedSize(32, 32)
        icon_label.setAlignment(Qt.AlignCenter)
        pm = IconManager.instance().get(h.get("icon_url"), 32)
        if pm:
            icon_label.setPixmap(pm)
        else:
            icon_label.setPixmap(
                theme.icon("resources", color=theme.COLORS["accent"]).pixmap(24, 24))
        icon_label.setProperty("icon_url", h.get("icon_url") or "")
        lay.addWidget(icon_label)

        title = QLabel(h["title"], objectName="cardTitle")
        title.setFixedWidth(180)
        lay.addWidget(title)

        desc = h["description"]
        if len(desc) > 50:
            desc = desc[:50] + "…"
        d = QLabel(desc, objectName="cardDesc")
        lay.addWidget(d, 1)
        dl = QLabel(f"下载 {_fmt_count(h['downloads'])}", objectName="cardDesc")
        dl.setFixedWidth(90)
        dl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(dl)
        return w

    def _on_icon_loaded(self, url, pixmap):
        for i in range(self.list.count()):
            it = self.list.item(i)
            w = self.list.itemWidget(it)
            if w:
                lbl = w.findChild(QLabel)
                if lbl and lbl.property("icon_url") == url:
                    lbl.setPixmap(pixmap)

    def _on_search_failed(self, err):
        self._searcher = None
        self.status_label.setText(f"搜索失败：{err}")

    def _do_download(self):
        if self._downloader is not None:
            return
        items = self.list.selectedItems()
        if not items:
            self.status_label.setText("请先选择一个资源")
            return
        project = items[0].data(Qt.UserRole)
        self.btn_install.setEnabled(False)
        self._downloader = _DownloadThread(project, self._base / self._kind)
        self._downloader.status.connect(self.status_label.setText)
        self._downloader.done.connect(self._on_downloaded)
        self._downloader.failed.connect(self._on_download_failed)
        start_worker(self._downloader, parent=self)

    def _on_downloaded(self, path):
        self._downloader = None
        self.btn_install.setEnabled(True)
        self.status_label.setText(f"下载完成：{Path(path).name}（游戏内启用）")

    def _on_download_failed(self, err):
        self._downloader = None
        self.btn_install.setEnabled(True)
        self.status_label.setText(f"下载失败：{err}")


def _fmt_count(n):
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return str(n)


# ---------------- 组合 ----------------

class _DownloadWrapper(QTabWidget):
    """资源包/光影：下载 + 已安装 两个子标签"""

    def __init__(self, kind):
        super().__init__()
        self.download_tab = DownloadResourceTab(kind)
        self.installed_tab = _ResourceTab(kind)
        self.addTab(self.download_tab, "下载")
        self.addTab(self.installed_tab, "已安装")
        self._kind = kind

    def set_target(self, base_dir):
        self.download_tab.set_target(base_dir)
        self.installed_tab.set_target(base_dir)

    def refresh(self):
        if self.currentWidget() is self.installed_tab:
            self.installed_tab.refresh()


class ResourcesPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        root.addWidget(QLabel("资源", objectName="pageTitle"))

        # ---- 管理位置：全局目录或版本隔离目录 ----
        loc = QHBoxLayout()
        loc.setSpacing(8)
        loc.addWidget(QLabel("管理位置：", objectName="cardDesc"))
        self.target_combo = QComboBox()
        self.target_combo.setFixedWidth(320)
        self.target_combo.currentIndexChanged.connect(self._apply_target)
        loc.addWidget(self.target_combo)
        loc.addStretch()
        root.addLayout(loc)

        self.tabs = QTabWidget()
        self.tab_rp = _DownloadWrapper("resourcepacks")
        self.tab_shader = _DownloadWrapper("shaderpacks")
        self.tab_saves = _ResourceTab("saves", allow_delete=True)
        self.tabs.addTab(self.tab_rp, "资源包")
        self.tabs.addTab(self.tab_shader, "光影")
        self.tabs.addTab(self.tab_saves, "存档")
        root.addWidget(self.tabs, 1)

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.refresh_targets()

    def refresh_targets(self):
        """刷新管理位置下拉：全局目录 + 各本地版本（隔离版本标注）"""
        s = Settings()
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        self.target_combo.addItem("全局目录（.minecraft）", "")
        vroot = Path(GAME_DIR) / "versions"
        if vroot.is_dir():
            for d in sorted(vroot.iterdir(), reverse=True):
                if (d / f"{d.name}.json").is_file():
                    tag = "  [隔离]" if s.isolation_for(d.name) else ""
                    self.target_combo.addItem(d.name + tag, d.name)
        self.target_combo.blockSignals(False)
        self._apply_target()

    def _apply_target(self):
        vid = self.target_combo.currentData() or ""
        base = (Path(GAME_DIR) / "versions" / vid) if vid else Path(GAME_DIR)
        self.tab_rp.set_target(base)
        self.tab_shader.set_target(base)
        self.tab_saves.set_target(base)

    def _on_tab_changed(self, idx):
        tab = self.tabs.widget(idx)
        if tab is not None:
            tab.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh_targets()
