# -*- coding: utf-8 -*-
"""资源页：资源包 / 光影 / 存档管理（浏览目录、打开文件夹、删除存档）"""

import os
import shutil
import subprocess
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTabWidget, QMessageBox,
)

from core.config import GAME_DIR, Settings


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
                        if p.is_dir():
                            desc = "文件夹"
                        else:
                            desc = _fmt_size(p.stat().st_size)
                        items.append((p.name, str(p), desc))
        except OSError:
            pass
        self.done.emit(items)


class _ResourceTab(QWidget):
    """单个资源标签页：列表 + 打开文件夹（+ 删除按钮仅存档用）"""

    def __init__(self, title, kind, allow_delete=False):
        super().__init__()
        self._kind = kind
        self._allow_delete = allow_delete
        self._scan = None
        self._dir = Path(GAME_DIR) / kind

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 12, 0, 0)
        root.setSpacing(10)

        tip_text = {
            "resourcepacks": "资源包（纹理/音效等），放入后请在游戏内「选项 → 资源包」中启用。",
            "shaderpacks": "光影包（需安装 OptiFine 或 Iris 加载），放入后请在游戏内选择。",
            "saves": "世界存档。删除操作不可恢复，请谨慎！",
        }[kind]
        self.tip = QLabel(f"{tip_text}\n目录：{self._dir}", objectName="cardDesc")
        self.tip.setWordWrap(True)
        root.addWidget(self.tip)

        self.list = QListWidget(objectName="versionList")
        root.addWidget(self.list, 1)

        bottom = QHBoxLayout()
        self.status_label = QLabel("", objectName="cardDesc")
        bottom.addWidget(self.status_label, 1)

        btn_open = QPushButton("打开文件夹", objectName="small")
        btn_open.setFixedHeight(30)
        btn_open.clicked.connect(lambda: _open_folder(self._dir))
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
        new_dir = Path(base_dir) / self._kind
        if new_dir == self._dir:
            return
        self._dir = new_dir
        self.tip.setText(self.tip.text().split("\n")[0] + f"\n目录：{self._dir}")
        self.refresh()

    def refresh(self):
        if self._scan is not None:
            return
        self.status_label.setText("正在扫描…")
        self._scan = _ScanThread(self._dir, self._kind)
        self._scan.done.connect(self._on_scanned)
        self._scan.start()

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
        from PyQt5.QtWidgets import QComboBox
        self.target_combo = QComboBox()
        self.target_combo.setFixedWidth(320)
        self.target_combo.currentIndexChanged.connect(self._apply_target)
        loc.addWidget(self.target_combo)
        loc.addStretch()
        root.addLayout(loc)

        self.tabs = QTabWidget()
        self.tab_rp = _ResourceTab("资源包", "resourcepacks")
        self.tab_shader = _ResourceTab("光影", "shaderpacks")
        self.tab_saves = _ResourceTab("存档", "saves", allow_delete=True)
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
