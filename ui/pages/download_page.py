# -*- coding: utf-8 -*-
"""下载页：版本清单列表（分类筛选 + 搜索）+ 版本核心文件下载"""

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QProgressBar, QFrame, QComboBox,
    QMessageBox,
)
from pathlib import Path
import json
import shutil

from core.config import GAME_DIR
from core.version_manifest import fetch_manifest
from core.download_queue import DownloadQueue, VersionDownloadTask, TaskState
from core import loader_install
from core.safe_thread import start_worker

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

_TAB_INSTALLED = "__installed__"
_TABS = [("全部", None), ("正式版", "release"), ("快照", "snapshot"),
         ("古老", "old"), ("已装", _TAB_INSTALLED)]


def _dir_size(path):
    """递归统计目录大小（字节），出错按 0 处理"""
    total = 0
    for p in Path(path).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def _fmt_size(n):
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024:.0f} KB"


class LocalScanThread(QThread):
    """扫描已装版本目录 + 磁盘占用，避免卡界面"""
    loaded = pyqtSignal(list)

    def run(self):
        vroot = Path(GAME_DIR) / "versions"
        items = []
        if vroot.is_dir():
            for d in sorted(vroot.iterdir(), key=lambda x: x.name.lower()):
                if not d.is_dir() or not (d / f"{d.name}.json").is_file():
                    continue
                size = _dir_size(d)
                # 是否为整合包实例（隔离目录内有 mods/saves 等游戏数据）
                has_data = any((d / s).exists() for s in ("mods", "saves", "config"))
                parent = ""
                try:
                    data = json.loads((d / f"{d.name}.json").read_text(encoding="utf-8"))
                    parent = data.get("inheritsFrom", "")
                except (OSError, ValueError):
                    pass
                items.append({"id": d.name, "size": size,
                              "instance": has_data, "inherits": parent})
        self.loaded.emit(items)


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
        self._loader_worker = None
        self._local_items = []
        self._scan_worker = None

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
        self.btn_delete = QPushButton("删除所选版本", objectName="small")
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self._delete_version)
        self.btn_delete.hide()
        bottom.addWidget(self.btn_delete)
        root.addLayout(bottom)

        self.list.itemSelectionChanged.connect(self._on_select)
        self._load_manifest()

    # ---------- 清单加载 ----------
    def _load_manifest(self):
        self.loader = ManifestLoader()
        self.loader.loaded.connect(self._on_manifest)
        self.loader.failed.connect(self._on_manifest_failed)
        start_worker(self.loader, parent=self)

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
        installed = tab == _TAB_INSTALLED
        # 已装模式：隐藏下载相关控件，显示删除
        for w in (self.btn_download, self.loader_box, self.btn_loader):
            w.setVisible(not installed)
        self.btn_delete.setVisible(installed)
        self.search_box.setVisible(not installed)
        if installed:
            self._scan_local()
        else:
            self._refresh_list()

    def _scan_local(self):
        if self._scan_worker is not None:
            return
        self.status_label.setText("正在扫描已装版本…")
        self.list.clear()
        self._scan_worker = LocalScanThread()
        self._scan_worker.loaded.connect(self._on_local_scanned)
        start_worker(self._scan_worker, parent=self)

    def _on_local_scanned(self, items):
        self._scan_worker = None
        self._local_items = items
        total = sum(i["size"] for i in items)
        self.status_label.setText(
            f"共 {len(items)} 个已装版本，合计 {_fmt_size(total)}（依赖库/资源为全局共享，未计入）")
        if self._version_type == _TAB_INSTALLED:
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
        if self._version_type == _TAB_INSTALLED:
            rows = self._local_items
        else:
            rows = self._filtered()
        for v in rows:
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
        if self._version_type == _TAB_INSTALLED:
            if v.get("instance"):
                tag = QLabel("整合包实例", objectName="cardDesc")
                h.addWidget(tag)
            h.addStretch()
            size = QLabel(_fmt_size(v.get("size", 0)), objectName="cardDesc")
            h.addWidget(size)
        else:
            tag = QLabel(_TYPE_NAMES.get(v.get("type"), ""), objectName="cardDesc")
            h.addWidget(tag)
            h.addStretch()
            date = QLabel(str(v.get("releaseTime", ""))[:10], objectName="cardDesc")
            h.addWidget(date)
        return w

    def _on_select(self):
        has = bool(self.list.selectedItems())
        installed = self._version_type == _TAB_INSTALLED
        self.btn_download.setEnabled(has and not installed)
        self.btn_loader.setEnabled(has and not installed
                                   and self._loader_worker is None)
        self.btn_delete.setEnabled(has and installed)

    # ---------- 删除已装版本 ----------
    def _delete_version(self):
        items = self.list.selectedItems()
        if not items or self._version_type != _TAB_INSTALLED:
            return
        v = items[0].data(Qt.UserRole)
        vid = v["id"]
        # 继承检查：有子版本依赖此版本时给出强警告
        children = [i["id"] for i in self._local_items
                    if i.get("inherits") == vid]
        msg = f"确定删除版本 {vid} 吗？"
        if children:
            msg = (f"{vid} 被以下加载器版本继承：\n{', '.join(children)}\n"
                   f"删除后这些版本将无法启动！\n\n仍要删除吗？")
        if v.get("instance"):
            head = (f"{vid} 是整合包实例，删除会连同其中的\n"
                    f"存档、模组、配置一起删除！\n\n")
            msg = head + (msg if children else f"确定删除吗？")
        if QMessageBox.question(self, "删除版本", msg,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) != QMessageBox.Yes:
            return
        target = Path(GAME_DIR) / "versions" / vid
        self.btn_delete.setEnabled(False)
        try:
            shutil.rmtree(target)
            self.status_label.setText(f"已删除 {vid}（释放 {_fmt_size(v.get('size', 0))}）")
        except OSError as e:
            self.status_label.setText(f"删除失败：{e}（游戏运行中或文件被占用？）")
        self._scan_local()

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
        start_worker(self._loader_worker, parent=self)

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
        if not items:
            return
        v = items[0].data(Qt.UserRole)
        # 加入全局下载队列（任务页可暂停/继续/取消）
        task = DownloadQueue.instance().add(
            VersionDownloadTask(v["id"], v["url"]))
        self.status_label.setText(f"{v['id']} 已加入下载队列，任务页可管理")
        task.updated.connect(lambda t=task: self._on_task_update(t))
        task.finished.connect(lambda t=task: self._on_task_finished(t))
        self.progress.show()
        self.progress.setValue(0)

    def _on_task_update(self, task):
        self.progress.setValue(task.progress)
        if task.state == TaskState.RUNNING:
            self.status_label.setText(f"{task.name} 下载中… {task.speed_text()}")
        elif task.state == TaskState.PAUSED:
            self.status_label.setText(f"{task.name} 已暂停")

    def _on_task_finished(self, task):
        if task.state == TaskState.DONE:
            self.progress.setValue(100)
            self.status_label.setText(
                f"{task.name} 下载完成 → {GAME_DIR / 'versions' / task.name}")
        elif task.state == TaskState.FAILED:
            self.status_label.setText(f"下载失败：{task.error}")
            self.progress.hide()
        else:
            self.status_label.setText(f"{task.name} 已取消")
            self.progress.hide()
