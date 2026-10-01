# -*- coding: utf-8 -*-
"""日志页：实时显示游戏日志（级别着色）+ 退出后崩溃分析"""

import html
import os
import subprocess
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QPlainTextEdit, QFrame, QFileDialog,
)

from core.config import GAME_DIR
from core import crash_analyzer


def _color_line(line):
    """按日志级别给一行日志加 HTML 颜色"""
    esc = html.escape(line)
    if ("/ERROR]" in line or "/FATAL]" in line or "Exception" in line
            or line.lstrip().startswith("Caused by") or "STATUS_" in line):
        return f'<span style="color:#E81123">{esc}</span>'
    if "/WARN]" in line:
        return f'<span style="color:#D9710F">{esc}</span>'
    if "/DEBUG]" in line or "/TRACE]" in line:
        return f'<span style="color:#9AA3B2">{esc}</span>'
    if "/INFO]" in line:
        return esc
    return f'<span style="color:#5A6472">{esc}</span>'


class LogPage(QWidget):
    """接收 HomePage 转发的 log_line / crashed 信号"""

    def __init__(self):
        super().__init__()
        self._current_vid = None
        self._tail_pos = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        root.addWidget(QLabel("游戏日志", objectName="pageTitle"))

        # ---- 崩溃分析卡片（默认隐藏） ----
        self.analysis_card = QFrame(objectName="card")
        ac = QVBoxLayout(self.analysis_card)
        ac.setContentsMargins(20, 14, 20, 16)
        ac.setSpacing(8)
        ac_head = QHBoxLayout()
        ac_head.addWidget(QLabel("⚠ 退出分析", objectName="cardTitle"))
        ac_head.addStretch()
        btn_close = QPushButton("收起", objectName="small")
        btn_close.clicked.connect(self.analysis_card.hide)
        ac_head.addWidget(btn_close)
        ac.addLayout(ac_head)
        self.analysis_label = QLabel("", objectName="cardDesc")
        self.analysis_label.setWordWrap(True)
        self.analysis_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ac.addWidget(self.analysis_label)
        self.analysis_card.hide()
        root.addWidget(self.analysis_card)

        # ---- 工具行 ----
        tools = QHBoxLayout()
        tools.setSpacing(8)
        tools.addWidget(QLabel("版本：", objectName="cardDesc"))
        self.ver_combo = QComboBox()
        self.ver_combo.setFixedWidth(240)
        self.ver_combo.currentTextChanged.connect(self._load_history)
        tools.addWidget(self.ver_combo)
        btn_refresh = QPushButton("刷新列表", objectName="small")
        btn_refresh.clicked.connect(self._refresh_versions)
        tools.addWidget(btn_refresh)
        btn_crash = QPushButton("崩溃报告目录", objectName="small")
        btn_crash.clicked.connect(self._open_crash_dir)
        tools.addWidget(btn_crash)
        btn_clear = QPushButton("清空显示", objectName="small")
        btn_clear.clicked.connect(lambda: self.log_view.clear())
        tools.addWidget(btn_clear)
        self.chk_scroll = QCheckBox("自动滚动")
        self.chk_scroll.setChecked(True)
        tools.addWidget(self.chk_scroll)
        tools.addStretch()
        root.addLayout(tools)

        # ---- 日志显示 ----
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 10))
        self.log_view.setMaximumBlockCount(6000)
        root.addWidget(self.log_view, 1)

        self._refresh_versions()

    # ---------- 对外接口（由 HomePage 调用） ----------
    def notify_launch(self, vid):
        """游戏启动时：切到该版本，清空显示并定位到日志文件末尾"""
        self._current_vid = vid
        log = Path(GAME_DIR) / "versions" / vid / "launcher-log.txt"
        self._tail_pos = log.stat().st_size if log.exists() else 0
        self.log_view.clear()
        self.analysis_card.hide()
        self._refresh_versions(select=vid)
        self.log_view.appendPlainText(f"=== 正在启动 {vid}，日志实时输出中 ===")

    def append_log(self, line):
        self.log_view.appendHtml(_color_line(line))
        if self.chk_scroll.isChecked():
            sb = self.log_view.verticalScrollBar()
            sb.setValue(sb.maximum())

    def show_crash_analysis(self, findings, crash_path):
        if not findings:
            return
        parts = []
        for f in findings:
            line = f"<b>{html.escape(f['title'])}</b>"
            if f.get("hint"):
                line += f" —— {html.escape(f['hint'])}"
            if f.get("line"):
                line += f"<br><span style='color:#9AA3B2'>{html.escape(f['line'])}</span>"
            parts.append(line)
        if crash_path:
            parts.append(f"<span style='color:#9AA3B2'>崩溃报告：{html.escape(crash_path)}</span>")
        self.analysis_label.setText("<br><br>".join(parts))
        self.analysis_card.show()

    # ---------- 内部 ----------
    def _refresh_versions(self, select=None):
        """列出所有有 launcher-log.txt 的版本"""
        vroot = Path(GAME_DIR) / "versions"
        items = []
        if vroot.is_dir():
            for d in vroot.iterdir():
                if (d / "launcher-log.txt").is_file():
                    items.append(d.name)
            items.sort(
                key=lambda v: (vroot / v / "launcher-log.txt").stat().st_mtime,
                reverse=True)
        self.ver_combo.blockSignals(True)
        self.ver_combo.clear()
        self.ver_combo.addItems(items)
        if select and select in items:
            self.ver_combo.setCurrentText(select)
        self.ver_combo.blockSignals(False)

    def _load_history(self, vid):
        """手动切换版本时加载历史日志（最后 200KB）"""
        if not vid:
            return
        log = Path(GAME_DIR) / "versions" / vid / "launcher-log.txt"
        if not log.is_file():
            return
        self._current_vid = vid
        self._tail_pos = log.stat().st_size
        self.log_view.clear()
        self.log_view.appendHtml(
            '<span style="color:#9AA3B2">'
            f"=== 历史日志：{vid}（只显示末尾，实时输出见启动时） ===</span>")
        try:
            with open(log, "rb") as f:
                if self._tail_pos > 200 * 1024:
                    f.seek(-200 * 1024, 2)
                text = f.read().decode("gbk", errors="replace")
            for line in text.splitlines()[-2000:]:
                self.log_view.appendHtml(_color_line(line))
        except OSError:
            pass
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _open_crash_dir(self):
        crash_dir = Path(GAME_DIR) / "crash-reports"
        crash_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(crash_dir))
