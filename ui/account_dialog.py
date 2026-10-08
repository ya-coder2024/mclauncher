# -*- coding: utf-8 -*-
"""账号登录对话框：离线 / 外置（LittleSkin 等皮肤站）/ 正版（微软）。"""

import webbrowser

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QTabWidget,
)

from core import auth
from core.safe_thread import start_worker

_TYPE_LABEL = {"offline": "离线", "yggdrasil": "外置", "microsoft": "正版"}


class _CallWorker(QThread):
    """在后台执行一个阻塞调用，返回结果或错误"""
    ok = pyqtSignal(object)
    fail = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs

    def run(self):
        try:
            self.ok.emit(self._fn(*self._args, **self._kwargs))
        except auth.AuthError as e:
            self.fail.emit(str(e))
        except Exception as e:
            self.fail.emit(f"发生错误：{e}")


class AccountDialog(QDialog):
    """登录成功后发出 logged_in（账号字典）"""

    logged_in = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("登录账号")
        self.setMinimumWidth(440)
        self._workers = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_offline(), "离线登录")
        self.tabs.addTab(self._tab_yggdrasil(), "外置登录")
        self.tabs.addTab(self._tab_microsoft(), "正版登录")
        root.addWidget(self.tabs)

        self.status = QLabel("", objectName="cardDesc")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(20)
        root.addWidget(self.status)

    # ---------------- 离线 ----------------
    def _tab_offline(self):
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(8, 16, 8, 8)

        self.off_name = QLineEdit()
        self.off_name.setPlaceholderText("3–16 位玩家昵称")
        self.off_name.returnPressed.connect(self._do_offline)
        form.addRow("玩家昵称：", self.off_name)

        btn = QPushButton("登录", objectName="small")
        btn.clicked.connect(self._do_offline)
        form.addRow("", btn)

        tip = QLabel("离线登录无需联网，但无法进入开启正版验证的服务器。",
                     objectName="cardDesc")
        tip.setWordWrap(True)
        form.addRow(tip)
        return w

    def _do_offline(self):
        try:
            account = auth.offline_login(self.off_name.text())
        except auth.AuthError as e:
            self.status.setText(str(e))
            return
        self._succeed(account)

    # ---------------- 外置 ----------------
    def _tab_yggdrasil(self):
        w = QWidget()
        form = QFormLayout(w)
        form.setContentsMargins(8, 16, 8, 8)

        self.yg_preset = QComboBox()
        for name, root_url in auth.SKIN_SITE_PRESETS:
            self.yg_preset.addItem(name, root_url)
        self.yg_preset.addItem("自定义…", "")
        self.yg_preset.currentIndexChanged.connect(self._on_preset)
        form.addRow("皮肤站：", self.yg_preset)

        self.yg_root = QLineEdit(auth.LITTLESKIN_API)
        form.addRow("服务地址：", self.yg_root)

        self.yg_user = QLineEdit()
        self.yg_user.setPlaceholderText("皮肤站邮箱或用户名")
        form.addRow("账号：", self.yg_user)

        self.yg_pass = QLineEdit()
        self.yg_pass.setEchoMode(QLineEdit.Password)
        self.yg_pass.returnPressed.connect(self._do_yggdrasil)
        form.addRow("密码：", self.yg_pass)

        btn = QPushButton("登录", objectName="small")
        btn.clicked.connect(self._do_yggdrasil)
        form.addRow("", btn)
        return w

    def _on_preset(self):
        url = self.yg_preset.currentData()
        if url:
            self.yg_root.setText(url)

    def _do_yggdrasil(self):
        self.status.setText("正在登录皮肤站…")
        worker = _CallWorker(auth.yggdrasil_login,
                             self.yg_root.text(),
                             self.yg_user.text(),
                             self.yg_pass.text())
        worker.ok.connect(lambda a: self._succeed(a))
        worker.fail.connect(self.status.setText)
        self._workers.append(worker)
        start_worker(worker, parent=self)

    # ---------------- 正版（微软设备码） ----------------
    def _tab_microsoft(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 16, 8, 8)
        v.setSpacing(10)

        tip = QLabel("使用微软账号登录 Minecraft：Java 版正版。",
                     objectName="cardDesc")
        tip.setWordWrap(True)
        v.addWidget(tip)

        self.ms_btn = QPushButton("获取登录代码", objectName="small")
        self.ms_btn.clicked.connect(self._do_ms_start)
        v.addWidget(self.ms_btn)

        # 设备码信息区（获取后显示）
        box = QWidget()
        box_form = QFormLayout(box)
        box_form.setContentsMargins(0, 0, 0, 0)
        self.ms_uri = QLineEdit()
        self.ms_uri.setReadOnly(True)
        btn_open = QPushButton("打开网页", objectName="small")
        btn_open.clicked.connect(lambda: webbrowser.open(self.ms_uri.text()))
        uri_row = QHBoxLayout()
        uri_row.setContentsMargins(0, 0, 0, 0)
        uri_row.addWidget(self.ms_uri)
        uri_row.addWidget(btn_open)
        box_form.addRow("验证网址：", self._wrap(uri_row))

        self.ms_code = QLineEdit()
        self.ms_code.setReadOnly(True)
        f = self.ms_code.font()
        f.setPointSize(14)
        f.setBold(True)
        self.ms_code.setFont(f)
        self.ms_code.setAlignment(Qt.AlignCenter)
        box_form.addRow("输入代码：", self.ms_code)
        box.setVisible(False)
        v.addWidget(box)
        self.ms_box = box

        v.addStretch()
        return w

    @staticmethod
    def _wrap(layout):
        w = QWidget()
        w.setLayout(layout)
        return w

    def _do_ms_start(self):
        self.status.setText("正在向微软请求设备码…")
        self.ms_btn.setEnabled(False)
        worker = _CallWorker(auth.microsoft_start)
        worker.ok.connect(self._on_ms_started)
        worker.fail.connect(self._ms_failed)
        self._workers.append(worker)
        start_worker(worker, parent=self)

    def _on_ms_started(self, device):
        self.ms_uri.setText(device["verification_uri"])
        self.ms_code.setText(device["user_code"])
        self.ms_box.setVisible(True)
        self.status.setText("请在打开的网页中登录微软账号并输入代码，启动器将自动等待…")
        webbrowser.open(device["verification_uri"])

        finisher = _CallWorker(auth.microsoft_finish, device)
        finisher.ok.connect(lambda a: self._succeed(a))
        finisher.fail.connect(self._ms_failed)
        self._workers.append(finisher)
        start_worker(finisher, parent=self)

    def _ms_failed(self, err):
        self.status.setText(err)
        self.ms_btn.setEnabled(True)

    # ---------------- 完成 ----------------
    def _succeed(self, account):
        label = _TYPE_LABEL.get(account["type"], account["type"])
        self.status.setText(f"登录成功：{account['name']}（{label}）")
        self.logged_in.emit(account)
        self.accept()
