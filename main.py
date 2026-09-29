# -*- coding: utf-8 -*-
"""PCL 风格 MC 启动器入口"""
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from ui import theme
from ui.main_window import MainWindow


def main():
    # 高分屏适配（Windows 缩放 125%/150% 时界面不糊）
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.qss())  # 应用 PCL 风格全局样式

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
