# -*- coding: utf-8 -*-
"""模组页（双标签）：
- 下载模组：从 Modrinth 搜索任意模组 → 选择版本 → 下载到 mods 目录
- 已安装：查看、启用/禁用（.jar.disabled）、删除本地模组
"""

import re
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QProgressBar, QComboBox, QDialog,
    QTabWidget, QMessageBox,
)

from ui import theme
from core.config import GAME_DIR
from core import mod_repo
from core import launcher as launcher_core
from core.downloader import download_file

_LOADER_TABS = [("全部", None), ("Fabric", "fabric"), ("Forge", "forge"),
                ("Quilt", "quilt"), ("NeoForge", "neoforge")]
PAGE_SIZE = 20


def _fmt_count(n):
    if n >= 100000000:
        return f"{n / 100000000:.1f}亿"
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)


def _base_mc_version(folder):
    """26.2-Fabric 0.19.5 -> 26.2"""
    return re.sub(r"(?i)[\s\-_]+(fabric|forge|neoforge|quilt)[\s\w.\-]*$", "", folder).strip()


# ---------------- 后台线程 ----------------
class SearchThread(QThread):
    done = pyqtSignal(list, int)
    failed = pyqtSignal(str)

    def __init__(self, query, mc_version, loader, offset):
        super().__init__()
        self._args = (query, mc_version, loader, offset)

    def run(self):
        try:
            hits, total = mod_repo.search_mods(*self._args, limit=PAGE_SIZE)
            self.done.emit(hits, total)
        except Exception as e:
            self.failed.emit(str(e))


class VersionLoadThread(QThread):
    done = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, project_id, mc_version, loader):
        super().__init__()
        self._args = (project_id, mc_version, loader)

    def run(self):
        try:
            vs = mod_repo.list_versions(*self._args)
            self.done.emit(vs)
        except Exception as e:
            self.failed.emit(str(e))


class ModInstallWorker(QThread):
    status = pyqtSignal(str)
    progress = pyqtSignal(int)
    failed = pyqtSignal(str)
    installed = pyqtSignal(list)

    def __init__(self, version):
        super().__init__()
        self._version = version
        self._mods_dir = Path(GAME_DIR) / "mods"

    def run(self):
        try:
            self.status.emit("正在解析模组与必需依赖…")
            tasks = mod_repo.resolve_install_files(self._version)
            if not tasks:
                self.failed.emit("该版本没有可下载的文件")
                return
            self._mods_dir.mkdir(parents=True, exist_ok=True)

            n = len(tasks)
            saved = []
            for i, t in enumerate(tasks):
                dest = self._mods_dir / t["filename"]
                if dest.is_file():
                    self.status.emit(f"已存在，跳过（{i + 1}/{n}）：{t['title']}")
                    self.progress.emit(int((i + 1) / n * 100))
                    continue

                self.status.emit(f"正在下载（{i + 1}/{n}）：{t['title']}")

                def cb(done, total, idx=i):
                    frac = done / total if total else 0.0
                    self.progress.emit(int(min(100, (idx + frac) / n * 100)))

                download_file(t["url"], dest, sha1=t["sha1"],
                              progress_cb=cb, retries=3, timeout=60)
                saved.append(t["title"])
            self.progress.emit(100)
            self.installed.emit(saved)
        except Exception as e:
            self.failed.emit(str(e))


# ---------------- 版本选择弹窗 ----------------
class VersionPickDialog(QDialog):
    def __init__(self, versions, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择要安装的版本")
        self.setMinimumWidth(460)
        self._versions = versions

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        tip = QLabel("该模组有多个兼容版本，请选择：", objectName="cardDesc")
        layout.addWidget(tip)

        self.list = QListWidget(objectName="versionList")
        for v in versions:
            gv = ", ".join(v.get("game_versions", [])[:4])
            ld = "/".join(LOADER for LOADER in v.get("loaders", []))
            item = QListWidgetItem(
                f"  {v.get('version_number', '-')}    [{ld}]    支持 {gv}"
            )
            self.list.addItem(item)
        self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list, 1)

        row = QHBoxLayout()
        row.addStretch()
        btn_cancel = QPushButton("取消", objectName="small")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("安装", objectName="small")
        btn_ok.clicked.connect(self.accept)
        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        layout.addLayout(row)

    def selected(self):
        r = self.list.currentRow()
        return self._versions[r] if r >= 0 else None


# ---------------- 下载模组 Tab ----------------
class DownloadTab(QWidget):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._loader = None
        self._offset = 0
        self._total = 0
        self._search_thread = None
        self._version_thread = None
        self._installer = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(12)

        # ---- 筛选行 ----
        row = QHBoxLayout()
        row.setSpacing(8)
        self._loader_btns = []
        for name, key in _LOADER_TABS:
            b = QPushButton(name, objectName="small")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self._set_loader(k))
            row.addWidget(b)
            self._loader_btns.append(b)
        self._loader_btns[0].setChecked(True)

        row.addSpacing(8)
        self.mc_box = QComboBox()
        self.mc_box.setFixedWidth(150)
        self.mc_box.currentIndexChanged.connect(self._do_search)
        row.addWidget(self.mc_box)

        row.addStretch()
        self.search_box = QLineEdit(placeholderText="搜索任意模组，如 钠、机械动力…")
        self.search_box.setFixedWidth(240)
        self.search_box.returnPressed.connect(self._do_search)
        row.addWidget(self.search_box)
        btn_search = QPushButton("搜索", objectName="small")
        btn_search.clicked.connect(self._do_search)
        row.addWidget(btn_search)
        root.addLayout(row)

        # ---- 结果列表 ----
        self.list = QListWidget(objectName="versionList")
        self.list.itemDoubleClicked.connect(self._start_install)
        root.addWidget(self.list, 1)

        # ---- 底部 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.btn_prev = QPushButton("上一页", objectName="small")
        self.btn_prev.clicked.connect(self._prev_page)
        self.btn_next = QPushButton("下一页", objectName="small")
        self.btn_next.clicked.connect(self._next_page)
        self.page_label = QLabel("", objectName="cardDesc")
        self.page_label.setFixedWidth(110)
        bottom.addWidget(self.btn_prev)
        bottom.addWidget(self.btn_next)
        bottom.addWidget(self.page_label)

        self.progress = QProgressBar(objectName="downloadProgress")
        self.progress.setFixedHeight(10)
        self.progress.setTextVisible(False)
        self.progress.hide()
        bottom.addWidget(self.progress, 1)

        self.status_label = QLabel("准备搜索…", objectName="cardDesc")
        bottom.addWidget(self.status_label)
        self.btn_install = QPushButton("安装所选模组", objectName="small")
        self.btn_install.clicked.connect(self._start_install)
        bottom.addWidget(self.btn_install)
        root.addLayout(bottom)

        self._fill_mc_versions()
        self._do_search()

    # ---------- 游戏版本下拉 ----------
    def _fill_mc_versions(self):
        vroot = Path(GAME_DIR) / "versions"
        bases = []
        if vroot.is_dir():
            for d in vroot.iterdir():
                if (d / f"{d.name}.json").is_file():
                    b = _base_mc_version(d.name)
                    if b and b not in bases:
                        bases.append(b)
        self.mc_box.blockSignals(True)
        self.mc_box.clear()
        self.mc_box.addItem("全部版本", None)
        for b in bases:
            self.mc_box.addItem(b, b)
        self.mc_box.blockSignals(False)

    # ---------- 搜索 ----------
    def _set_loader(self, key):
        for i, (_, k) in enumerate(_LOADER_TABS):
            self._loader_btns[i].setChecked(k == key)
        self._loader = key
        self._do_search()

    def _do_search(self):
        if self._search_thread is not None or self._installer is not None:
            return
        self._offset = 0
        self._run_search()

    def _next_page(self):
        if self._offset + PAGE_SIZE < self._total:
            self._offset += PAGE_SIZE
            self._run_search()

    def _prev_page(self):
        if self._offset >= PAGE_SIZE:
            self._offset -= PAGE_SIZE
            self._run_search()

    def _run_search(self):
        mc = self.mc_box.currentData()
        q = self.search_box.text().strip()
        self.status_label.setText("正在搜索…")
        self._search_thread = SearchThread(q, mc, self._loader, self._offset)
        self._search_thread.done.connect(self._on_results)
        self._search_thread.failed.connect(self._on_search_failed)
        self._search_thread.start()

    def _on_results(self, hits, total):
        self._search_thread = None
        self._total = total
        self.list.clear()
        for h in hits:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, h)
            row = self._make_row(h)
            item.setSizeHint(row.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, row)

        page_no = self._offset // PAGE_SIZE + 1
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_label.setText(f"第 {page_no}/{pages} 页 · {total} 个")
        self.btn_prev.setEnabled(self._offset > 0)
        self.btn_next.setEnabled(self._offset + PAGE_SIZE < total)
        self.status_label.setText("双击模组可直接安装" if hits else "没有找到模组，换个关键字或筛选试试")

    def _on_search_failed(self, err):
        self._search_thread = None
        self.status_label.setText(f"搜索失败：{err}")

    def _make_row(self, h):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(10)

        icon_label = QLabel()
        icon_label.setPixmap(theme.icon("mods", color=theme.COLORS["accent"]).pixmap(24, 24))
        lay.addWidget(icon_label)

        title = QLabel(h["title"], objectName="cardTitle")
        title.setFixedWidth(150)
        lay.addWidget(title)

        desc = h["description"]
        if len(desc) > 48:
            desc = desc[:48] + "…"
        d_label = QLabel(desc, objectName="cardDesc")
        lay.addWidget(d_label, 1)

        if h.get("author"):
            a = QLabel(f"作者：{h['author']}", objectName="cardDesc")
            lay.addWidget(a)
        dl = QLabel(f"下载 {_fmt_count(h['downloads'])}", objectName="cardDesc")
        dl.setFixedWidth(80)
        dl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(dl)
        return w

    # ---------- 安装 ----------
    def _start_install(self, _item=None):
        if self._installer is not None or self._version_thread is not None:
            return
        items = self.list.selectedItems()
        if not items:
            self.status_label.setText("请先在列表中选择一个模组")
            return
        hit = items[0].data(Qt.UserRole)
        self.status_label.setText(f"正在获取 {hit['title']} 的版本列表…")
        mc = self.mc_box.currentData()
        self._version_thread = VersionLoadThread(hit["project_id"], mc, self._loader)
        self._version_thread.done.connect(lambda vs, h=hit: self._on_versions(vs, h))
        self._version_thread.failed.connect(self._on_version_failed)
        self._version_thread.start()

    def _on_versions(self, versions, hit):
        self._version_thread = None
        if not versions:
            self.status_label.setText("当前筛选下无版本，正在尝试获取全部版本…")
            self._version_thread = VersionLoadThread(hit["project_id"], None, None)
            self._version_thread.done.connect(self._pick_or_warn)
            self._version_thread.failed.connect(self._on_version_failed)
            self._version_thread.start()
            return
        self._pick_or_warn(versions)

    def _pick_or_warn(self, versions):
        self._version_thread = None
        if not versions:
            self.status_label.setText("该模组没有可用版本")
            return
        version = versions[0]
        if len(versions) > 1:
            dlg = VersionPickDialog(versions, self)
            if dlg.exec_() != QDialog.Accepted:
                self.status_label.setText("已取消安装")
                return
            version = dlg.selected()
        self._run_install(version)

    def _on_version_failed(self, err):
        self._version_thread = None
        self.status_label.setText(f"获取版本失败：{err}")

    def _run_install(self, version):
        self.progress.show()
        self.progress.setValue(0)
        self.btn_install.setEnabled(False)
        self._installer = ModInstallWorker(version)
        self._installer.status.connect(self.status_label.setText)
        self._installer.progress.connect(self.progress.setValue)
        self._installer.failed.connect(self._on_install_failed)
        self._installer.installed.connect(self._on_installed)
        self._installer.start()

    def _on_installed(self, names):
        self._installer = None
        self.btn_install.setEnabled(True)
        if names:
            self.status_label.setText(f"安装完成：{'、'.join(names[:5])}"
                                      + (f" 等 {len(names)} 个" if len(names) > 5 else "")
                                      + "（已含必需依赖）")
        else:
            self.status_label.setText("所选文件此前已安装，无需重复下载")
        self.changed.emit()

    def _on_install_failed(self, err):
        self._installer = None
        self.btn_install.setEnabled(True)
        self.progress.hide()
        self.status_label.setText(f"安装失败：{err}")


# ---------------- 已安装 Tab ----------------
class _ScanThread(QThread):
    done = pyqtSignal(list)
    failed = pyqtSignal(str)

    def run(self):
        try:
            self.done.emit(launcher_core.scan_mods(GAME_DIR))
        except Exception as e:
            self.failed.emit(str(e))


class InstalledTab(QWidget):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._scan = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(10)

        tip = QLabel("管理 .minecraft/mods 中的模组。禁用后加载器不会加载该模组（重启游戏生效）。",
                     objectName="cardDesc")
        tip.setWordWrap(True)
        root.addWidget(tip)

        self.list = QListWidget(objectName="versionList")
        root.addWidget(self.list, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.status_label = QLabel("", objectName="cardDesc")
        bottom.addWidget(self.status_label, 1)

        self.btn_toggle = QPushButton("启用 / 禁用所选", objectName="small")
        self.btn_toggle.clicked.connect(self._toggle_selected)
        bottom.addWidget(self.btn_toggle)
        self.btn_delete = QPushButton("删除所选", objectName="small")
        self.btn_delete.clicked.connect(self._delete_selected)
        bottom.addWidget(self.btn_delete)
        self.btn_refresh = QPushButton("刷新", objectName="small")
        self.btn_refresh.clicked.connect(self.refresh)
        bottom.addWidget(self.btn_refresh)
        root.addLayout(bottom)

    def refresh(self):
        if self._scan is not None:
            return
        self.status_label.setText("正在扫描…")
        self._scan = _ScanThread()
        self._scan.done.connect(self._on_scanned)
        self._scan.failed.connect(self._on_scan_failed)
        self._scan.start()

    def _on_scanned(self, mods):
        self._scan = None
        self.list.clear()
        enabled_n = 0
        for m in mods:
            state = "已禁用" if m["disabled"] else "已启用"
            if not m["disabled"]:
                enabled_n += 1
            item = QListWidgetItem()
            item.setData(Qt.UserRole, m)
            row = self._make_row(m, state)
            item.setSizeHint(row.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
        self.status_label.setText(
            f"共 {len(mods)} 个模组（启用 {enabled_n}，禁用 {len(mods) - enabled_n}）"
            if mods else "mods 目录为空，去「下载模组」页安装吧")

    def _on_scan_failed(self, err):
        self._scan = None
        self.status_label.setText(f"扫描失败：{err}")

    def _make_row(self, m, state):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        icon_label = QLabel()
        color = theme.COLORS["text_dim"] if m["disabled"] else theme.COLORS["accent"]
        icon_label.setPixmap(theme.icon("mods", color=color).pixmap(22, 22))
        lay.addWidget(icon_label)

        name = QLabel(m["name"], objectName="cardTitle")
        name.setFixedWidth(200)
        lay.addWidget(name)

        ver = QLabel(f"版本 {m['version']}", objectName="cardDesc")
        ver.setMinimumWidth(180)
        lay.addWidget(ver)
        lay.addStretch()

        st = QLabel(state, objectName="cardDesc")
        st.setFixedWidth(70)
        st.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(st)
        return w

    def _selected_mod(self):
        items = self.list.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def _toggle_selected(self):
        m = self._selected_mod()
        if not m:
            self.status_label.setText("请先选择一个模组")
            return
        try:
            launcher_core.set_mod_enabled(GAME_DIR, m["file"], m["disabled"])
        except Exception as e:
            self.status_label.setText(f"操作失败：{e}")
            return
        self.status_label.setText(
            f"已启用 {m['name']}（重启游戏生效）" if m["disabled"]
            else f"已禁用 {m['name']}（重启游戏生效）")
        self.changed.emit()
        self.refresh()

    def _delete_selected(self):
        m = self._selected_mod()
        if not m:
            self.status_label.setText("请先选择一个模组")
            return
        ok = QMessageBox.question(
            self, "删除模组", f"确定删除「{m['name']}」吗？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ok != QMessageBox.Yes:
            return
        try:
            launcher_core.delete_mod(GAME_DIR, m["file"])
        except Exception as e:
            self.status_label.setText(f"删除失败：{e}")
            return
        self.status_label.setText(f"已删除 {m['name']}")
        self.changed.emit()
        self.refresh()


# ---------------- 模组页（外壳） ----------------
class ModsPage(QWidget):
    # 模组安装/删除/启停后发出（主页据此刷新版本与模组列表）
    installed_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        root.addWidget(QLabel("模组", objectName="pageTitle"))

        self.tabs = QTabWidget()
        self.tab_download = DownloadTab()
        self.tab_installed = InstalledTab()
        self.tabs.addTab(self.tab_download, "下载模组")
        self.tabs.addTab(self.tab_installed, "已安装")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        self.tab_download.changed.connect(self.installed_changed.emit)
        self.tab_installed.changed.connect(self.installed_changed.emit)

    def _on_tab_changed(self, idx):
        if self.tabs.widget(idx) is self.tab_installed:
            self.tab_installed.refresh()
