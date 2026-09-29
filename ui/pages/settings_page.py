# -*- coding: utf-8 -*-
"""设置页：占位框架（后续接入 Java 路径、内存等设置项）"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QHBoxLayout, QPushButton,
)


class SettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        title = QLabel("设置", objectName="pageTitle")
        root.addWidget(title)

        # Java 路径卡片
        java_card = QFrame(objectName="card")
        java_h = QHBoxLayout(java_card)
        java_h.setContentsMargins(20, 16, 20, 16)
        java_h.setSpacing(12)
        java_text = QVBoxLayout()
        java_text.addWidget(QLabel("Java 路径", objectName="cardTitle"))
        java_text.addWidget(
            QLabel("留空则自动检测系统中的 Java", objectName="cardDesc")
        )
        java_h.addLayout(java_text, 1)
        java_btn = QPushButton("浏览", objectName="small")
        java_h.addWidget(java_btn)
        root.addWidget(java_card)

        # 内存卡片
        mem_card = QFrame(objectName="card")
        mem_h = QHBoxLayout(mem_card)
        mem_h.setContentsMargins(20, 16, 20, 16)
        mem_h.setSpacing(12)
        mem_text = QVBoxLayout()
        mem_text.addWidget(QLabel("内存分配", objectName="cardTitle"))
        mem_text.addWidget(QLabel("为游戏分配的最大内存（MB）", objectName="cardDesc"))
        mem_h.addLayout(mem_text, 1)
        root.addWidget(mem_card)

        root.addStretch()
