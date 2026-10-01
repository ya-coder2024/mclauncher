# -*- coding: utf-8 -*-
"""下载任务页：队列列表（进度、速度、暂停/继续/取消）+ 清除已完成"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QProgressBar,
)

from core.download_queue import DownloadQueue, TaskState, STATE_LABELS, KIND_LABELS


class TaskRow(QFrame):
    """单个任务卡片行"""

    def __init__(self, task):
        super().__init__(objectName="card")
        self.task = task
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 10, 16, 10)
        h.setSpacing(12)

        # 左侧：名称 + 状态
        left = QVBoxLayout()
        left.setSpacing(4)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(QLabel(task.name, objectName="cardTitle"))
        name_row.addWidget(QLabel(KIND_LABELS.get(task.kind, task.kind),
                                  objectName="cardDesc"))
        name_row.addStretch()
        left.addLayout(name_row)
        self.status_label = QLabel("", objectName="cardDesc")
        left.addWidget(self.status_label)
        h.addLayout(left, 1)

        # 中间：进度条 + 速度
        mid = QVBoxLayout()
        mid.setSpacing(4)
        self.bar = QProgressBar(objectName="downloadProgress")
        self.bar.setFixedWidth(220)
        self.bar.setFixedHeight(10)
        self.bar.setTextVisible(False)
        mid.addWidget(self.bar)
        self.speed_label = QLabel("", objectName="cardDesc")
        mid.addWidget(self.speed_label)
        h.addLayout(mid)

        # 右侧：按钮
        self.btn_pause = QPushButton("暂停", objectName="small")
        self.btn_pause.setFixedWidth(64)
        self.btn_pause.clicked.connect(self._toggle_pause)
        h.addWidget(self.btn_pause)
        self.btn_cancel = QPushButton("取消", objectName="small")
        self.btn_cancel.setFixedWidth(64)
        self.btn_cancel.clicked.connect(self._cancel)
        h.addWidget(self.btn_cancel)

        self.refresh()

    def _toggle_pause(self):
        if self.task.state == TaskState.RUNNING:
            self.task.pause()
        elif self.task.state == TaskState.PAUSED:
            self.task.resume()

    def _cancel(self):
        self.task.cancel()

    def refresh(self):
        t = self.task
        self.bar.setValue(t.progress)
        label = STATE_LABELS.get(t.state, t.state)
        if t.state == TaskState.FAILED and t.error:
            label += f"：{t.error[:40]}"
        self.status_label.setText(label)
        if t.state == TaskState.RUNNING:
            self.speed_label.setText(t.speed_text())
        else:
            self.speed_label.setText("")
        # 按钮可用性
        self.btn_pause.setEnabled(t.state in (TaskState.RUNNING, TaskState.PAUSED))
        self.btn_pause.setText("继续" if t.state == TaskState.PAUSED else "暂停")
        self.btn_cancel.setEnabled(not t.is_terminal)


class TasksPage(QWidget):
    def __init__(self):
        super().__init__()
        self.queue = DownloadQueue.instance()
        self._rows = {}   # task_id -> TaskRow

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(QLabel("下载任务", objectName="pageTitle"))
        head.addStretch()
        self.count_label = QLabel("", objectName="cardDesc")
        head.addWidget(self.count_label)
        btn_clear = QPushButton("清除已完成", objectName="small")
        btn_clear.clicked.connect(self._clear_finished)
        head.addWidget(btn_clear)
        root.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root.addWidget(scroll, 1)
        self._container = QWidget()
        scroll.setWidget(self._container)
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)
        self._list_layout.addStretch()

        self.empty_label = QLabel("暂无下载任务", objectName="cardDesc")
        self.empty_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.empty_label)

        self.queue.tasks_changed.connect(self._rebuild)
        self.queue.any_updated.connect(self._refresh_rows)
        self._rebuild()

    def _rebuild(self):
        # 移除不存在的任务行
        ids = {t.id for t in self.queue.tasks}
        for tid in list(self._rows):
            if tid not in ids:
                self._rows[tid].setParent(None)
                self._rows[tid].deleteLater()
                del self._rows[tid]
        # 新任务加行（倒序：最新在前）
        for task in reversed(self.queue.tasks):
            if task.id not in self._rows:
                row = TaskRow(task)
                self._rows[task.id] = row
                self._list_layout.insertWidget(0, row)
        self._refresh_rows()

    def _refresh_rows(self):
        for row in self._rows.values():
            row.refresh()
        n = self.queue.active_count()
        self.count_label.setText(f"{n} 个进行中" if n else "")
        self.empty_label.setVisible(not self.queue.tasks)

    def _clear_finished(self):
        self.queue.clear_finished()
