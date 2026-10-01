# -*- coding: utf-8 -*-
"""主窗口：无边框窗口 + 自绘标题栏 + PCL 风格侧边栏 + 页面堆叠"""

from PyQt5.QtCore import QSize, Qt, QPoint
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QFrame, QStackedWidget, QSizeGrip,
)

from ui import theme
from ui.pages.home_page import HomePage
from ui.pages.download_page import DownloadPage
from ui.pages.mods_page import ModsPage
from ui.pages.packs_page import PacksPage
from ui.pages.tasks_page import TasksPage
from ui.pages.settings_page import SettingsPage


class TitleBar(QFrame):
    """自绘标题栏：左侧 Logo，右侧 最小化/最大化/关闭"""

    def __init__(self, window):
        super().__init__(objectName="titlebar")
        self.window = window
        self._drag_pos = None
        self.setFixedHeight(44)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 0, 0)
        layout.setSpacing(10)

        # Logo：圆角徽标 + 名称
        badge = QLabel("MC", objectName="logoBadge")
        badge.setFixedSize(26, 26)
        badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(badge)

        layout.addWidget(QLabel("我的世界启动器", objectName="logoText"))
        layout.addStretch()

        # 窗口控制按钮（Segoe MDL2 Assets 符号字体）
        self.btn_min = QPushButton("\uE921", objectName="btnMin")
        self.btn_max = QPushButton("\uE922", objectName="btnMax")
        self.btn_close = QPushButton("\uE8BB", objectName="btnClose")
        for b in (self.btn_min, self.btn_max, self.btn_close):
            b.setFixedSize(44, 44)
            b.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(window.close)
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_max.clicked.connect(self._toggle_max)
        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_max)
        layout.addWidget(self.btn_close)

    def _toggle_max(self):
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    # ---- 拖动 / 双击最大化 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.window.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and e.buttons() & Qt.LeftButton:
            # 最大化状态下拖动 = 还原并跟随
            if self.window.isMaximized():
                self.window.showNormal()
                self._drag_pos = QPoint(
                    self.window.width() // 2, 22
                )
            self.window.move(e.globalPos() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, e):
        self._toggle_max()


class SidebarButton(QPushButton):
    """侧边栏导航按钮：图标 + 文字，可选中"""

    def __init__(self, text, icon_name):
        super().__init__(f"  {text}", objectName="nav")
        self.setProperty("class", "nav")
        self.setCheckable(True)
        self.setIcon(theme.icon(icon_name, color="#B9C0D0"))
        self.setIconSize(QSize(20, 20))
        self.setCursor(Qt.PointingHandCursor)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("我的世界启动器")
        self.resize(1060, 680)
        self.setMinimumSize(900, 620)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)

        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = TitleBar(self)
        root.addWidget(self.titlebar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        # ---- 侧边栏 ----
        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(210)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 14, 12, 10)
        side_layout.setSpacing(4)

        tip = QLabel("导航", objectName="sidebarTitle")
        side_layout.addWidget(tip)
        side_layout.addSpacing(4)

        # 导航按钮组（互斥选中）
        self.pages = QStackedWidget()
        self.nav_buttons = []
        nav_defs = [
            ("主页", "home", HomePage),
            ("下载", "download", DownloadPage),
            ("模组", "mods", ModsPage),
            ("整合包", "packs", PacksPage),
            ("任务", "tasks", TasksPage),
            ("设置", "settings", SettingsPage),
        ]
        for i, (text, icon_name, page_cls) in enumerate(nav_defs):
            btn = SidebarButton(text, icon_name)
            btn.clicked.connect(lambda _=False, idx=i: self.switch_page(idx))
            side_layout.addWidget(btn)
            self.nav_buttons.append(btn)
            self.pages.addWidget(page_cls())

        side_layout.addStretch()

        # 模组安装后自动刷新主页的模组列表
        home_page = next(self.pages.widget(i) for i in range(self.pages.count())
                         if isinstance(self.pages.widget(i), HomePage))
        mods_page = next(self.pages.widget(i) for i in range(self.pages.count())
                         if isinstance(self.pages.widget(i), ModsPage))
        mods_page.installed_changed.connect(home_page.refresh_versions)
        packs_page = next(self.pages.widget(i) for i in range(self.pages.count())
                          if isinstance(self.pages.widget(i), PacksPage))
        packs_page.installed_changed.connect(home_page.refresh_versions)

        # 侧边栏底部版本号
        ver = QLabel("PCL 风格 v0.6", objectName="versionTag")
        ver.setAlignment(Qt.AlignCenter)
        side_layout.addWidget(ver)

        body.addWidget(sidebar)

        # ---- 内容区 ----
        body.addWidget(self.pages, 1)

        # 右下角窗口拉伸把手（无边框窗口需要）
        grip = QSizeGrip(central)
        grip.setFixedSize(14, 14)
        side_layout.addWidget(grip)

        self.nav_buttons[0].setChecked(True)

    def switch_page(self, index):
        """切换页面并同步导航按钮选中态"""
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
        self.pages.setCurrentIndex(index)
