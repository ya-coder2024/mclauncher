# -*- coding: utf-8 -*-
"""整合包页：Modrinth 搜索 → 加入下载队列自动安装"""

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QProgressBar, QFrame,
)

from core import mod_repo
from core.download_queue import DownloadQueue, PackInstallTask, TaskState


class SearchThread(QThread):
    """后台搜索整合包"""
    found = pyqtSignal(list, int)   # (结果列表, 总命中数)
    failed = pyqtSignal(str)

    def __init__(self, query):
        super().__init__()
        self.query = query

    def run(self):
        try:
            hits, total = mod_repo.search_modpacks(self.query)
            self.found.emit(hits, total)
        except Exception as e:
            self.failed.emit(str(e))


class PacksPage(QWidget):
    installed_changed = pyqtSignal()  # 安装完成后通知主页刷新

    def __init__(self):
        super().__init__()
        self._results = []
        self._searcher = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        root.addWidget(QLabel("整合包", objectName="pageTitle"))

        # ---- 搜索行 ----
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search_box = QLineEdit(placeholderText="搜索 Modrinth 整合包，如 Fabulously Optimized…")
        self.search_box.returnPressed.connect(self._search)
        search_row.addWidget(self.search_box, 1)
        self.btn_search = QPushButton("搜索", objectName="small")
        self.btn_search.clicked.connect(self._search)
        search_row.addWidget(self.btn_search)
        root.addLayout(search_row)

        # ---- 结果列表 ----
        self.list = QListWidget(objectName="versionList")
        self.list.setSelectionMode(self.list.SingleSelection)
        root.addWidget(self.list, 1)

        # ---- 底部：进度 + 状态 + 安装 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.progress = QProgressBar(objectName="downloadProgress")
        self.progress.setFixedHeight(10)
        self.progress.setTextVisible(False)
        self.progress.hide()
        bottom.addWidget(self.progress, 1)
        self.status_label = QLabel("输入关键词搜索整合包", objectName="cardDesc")
        bottom.addWidget(self.status_label)
        self.btn_install = QPushButton("安装所选整合包", objectName="small")
        self.btn_install.setEnabled(False)
        self.btn_install.clicked.connect(self._install_selected)
        bottom.addWidget(self.btn_install)
        root.addLayout(bottom)

        self.list.itemSelectionChanged.connect(self._on_select)

        # 启动时展示热门整合包
        self._search()

    # ---------- 搜索 ----------
    def _search(self):
        if self._searcher is not None:
            return
        self.btn_search.setEnabled(False)
        self.status_label.setText("正在搜索…")
        self._searcher = SearchThread(self.search_box.text().strip())
        self._searcher.found.connect(self._on_found)
        self._searcher.failed.connect(self._on_search_failed)
        self._searcher.start()

    def _on_found(self, hits, total):
        self._searcher = None
        self.btn_search.setEnabled(True)
        self._results = hits
        self.list.clear()
        for p in hits:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, p)
            row = self._make_row(p)
            item.setSizeHint(row.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
        self.status_label.setText(f"共 {total} 个结果，显示前 {len(hits)} 个")

    def _on_search_failed(self, err):
        self._searcher = None
        self.btn_search.setEnabled(True)
        self.status_label.setText(f"搜索失败：{err}")

    def _make_row(self, p):
        w = QFrame()
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 9, 12, 9)
        v.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(QLabel(p["title"], objectName="cardTitle"))
        head.addWidget(QLabel(f"by {p['author']}", objectName="cardDesc"))
        head.addStretch()
        dl = p["downloads"]
        dl_text = f"{dl/10000:.1f} 万下载" if dl >= 10000 else f"{dl} 下载"
        head.addWidget(QLabel(dl_text, objectName="cardDesc"))
        v.addLayout(head)
        v.addWidget(QLabel(p["description"], objectName="cardDesc"))
        return w

    def _on_select(self):
        self.btn_install.setEnabled(bool(self.list.selectedItems()))

    # ---------- 安装（走全局下载队列，任务页可暂停/取消） ----------
    def _install_selected(self):
        items = self.list.selectedItems()
        if not items:
            return
        project = items[0].data(Qt.UserRole)
        task = DownloadQueue.instance().add(PackInstallTask(project))
        self.status_label.setText(f"{project['title']} 已加入下载队列，任务页可管理")
        self.progress.show()
        self.progress.setValue(0)
        task.updated.connect(lambda t=task: self.progress.setValue(t.progress))
        task.finished.connect(lambda t=task: self._on_task_finished(t))

    def _on_task_finished(self, task):
        if task.state == TaskState.DONE:
            self.progress.setValue(100)
            self.status_label.setText(
                f"整合包 {task.instance or task.name} 安装完成，回主页选择对应版本启动")
            self.installed_changed.emit()
        elif task.state == TaskState.FAILED:
            self.progress.hide()
            self.status_label.setText(f"安装失败：{task.error}")
        else:
            self.progress.hide()
            self.status_label.setText(f"{task.name} 已取消")
