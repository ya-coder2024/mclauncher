# -*- coding: utf-8 -*-
"""设置页：Java 选择（全局/按版本）、内存分配、分辨率、JVM 参数，持久化到 launcher_settings.json"""

from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QComboBox, QSlider, QSpinBox, QLineEdit, QFileDialog, QScrollArea,
    QCheckBox,
)

from core.config import GAME_DIR, Settings
from core.java_finder import find_javas
from core.safe_thread import start_worker


class JavaScanThread(QThread):
    """后台扫描系统 Java（probe 每个 java.exe 较慢，避免卡界面）"""
    found = pyqtSignal(list)  # [(路径, 主版本号), ...]

    def run(self):
        try:
            self.found.emit(find_javas())
        except Exception:
            self.found.emit([])


class SettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self._javas = []        # 扫描结果 [(path, major)]
        self._scan_thread = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)

        page = QVBoxLayout(content)
        page.setContentsMargins(28, 24, 28, 24)
        page.setSpacing(16)

        page.addWidget(QLabel("设置", objectName="pageTitle"))

        page.addWidget(self._make_java_card())
        page.addWidget(self._make_version_java_card())
        page.addWidget(self._make_memory_card())
        page.addWidget(self._make_resolution_card())
        page.addWidget(self._make_jvm_card())
        page.addWidget(self._make_isolation_card())

        # 保存
        save_row = QHBoxLayout()
        save_row.addStretch()
        self.save_hint = QLabel("", objectName="cardDesc")
        save_row.addWidget(self.save_hint)
        btn_save = QPushButton("保存设置", objectName="small")
        btn_save.clicked.connect(self._save)
        save_row.addWidget(btn_save)
        page.addLayout(save_row)

        page.addStretch()
        self._start_scan()

    # ---------- 卡片构建 ----------
    def _card(self, title, desc):
        card = QFrame(objectName="card")
        v = QVBoxLayout(card)
        v.setContentsMargins(20, 14, 20, 16)
        v.setSpacing(10)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(QLabel(title, objectName="cardTitle"))
        if desc:
            head.addWidget(QLabel(desc, objectName="cardDesc"))
        v.addLayout(head)
        return card, v

    def _make_java_card(self):
        card, v = self._card("全局 Java", "留空则自动选择（本地运行时 → 系统 Java → 自动下载）")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.java_combo = QComboBox()
        self.java_combo.setMinimumWidth(360)
        self.java_combo.addItem("自动检测", "")
        row.addWidget(self.java_combo, 1)
        btn_browse = QPushButton("浏览…", objectName="small")
        btn_browse.clicked.connect(lambda: self._browse_java(self.java_combo))
        row.addWidget(btn_browse)
        self.btn_rescan = QPushButton("重新扫描", objectName="small")
        self.btn_rescan.clicked.connect(self._start_scan)
        row.addWidget(self.btn_rescan)
        v.addLayout(row)
        self.java_status = QLabel("正在扫描系统中的 Java…", objectName="cardDesc")
        v.addWidget(self.java_status)
        return card

    def _make_version_java_card(self):
        card, v = self._card("按版本指定 Java（可选）",
                             "为某个版本单独指定 Java，优先于全局设置")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("版本：", objectName="cardDesc"))
        self.ver_combo = QComboBox()
        self.ver_combo.setFixedWidth(220)
        self._refresh_local_versions()
        row.addWidget(self.ver_combo)
        row.addWidget(QLabel("Java：", objectName="cardDesc"))
        self.ver_java_combo = QComboBox()
        self.ver_java_combo.setMinimumWidth(280)
        row.addWidget(self.ver_java_combo, 1)
        btn_browse = QPushButton("浏览…", objectName="small")
        btn_browse.clicked.connect(lambda: self._browse_java(self.ver_java_combo))
        row.addWidget(btn_browse)
        v.addLayout(row)
        self.ver_combo.currentTextChanged.connect(self._sync_version_java_combo)
        self.ver_java_combo.currentIndexChanged.connect(self._on_version_java_changed)
        self._sync_version_java_combo(self.ver_combo.currentText())
        return card

    def _make_memory_card(self):
        card, v = self._card("内存分配", "拖动滑块调整最大内存（-Xmx），大型整合包建议 6G 以上")
        row = QHBoxLayout()
        row.setSpacing(12)
        self.mem_slider = QSlider(Qt.Horizontal)
        self.mem_slider.setRange(512, 32768)
        self.mem_slider.setSingleStep(256)
        self.mem_slider.setPageStep(1024)
        self.mem_slider.setValue(self.settings.memory_mb)
        row.addWidget(self.mem_slider, 1)
        self.mem_spin = QSpinBox()
        self.mem_spin.setRange(512, 32768)
        self.mem_spin.setSingleStep(256)
        self.mem_spin.setSuffix(" MB")
        self.mem_spin.setValue(self.settings.memory_mb)
        row.addWidget(self.mem_spin)
        self.mem_slider.valueChanged.connect(self.mem_spin.setValue)
        self.mem_spin.valueChanged.connect(self.mem_slider.setValue)
        v.addLayout(row)
        return card

    def _make_resolution_card(self):
        card, v = self._card("窗口分辨率", "游戏窗口的初始宽高（像素）")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("宽：", objectName="cardDesc"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(320, 7680)
        self.width_spin.setValue(self.settings.width)
        row.addWidget(self.width_spin)
        row.addWidget(QLabel("高：", objectName="cardDesc"))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(240, 4320)
        self.height_spin.setValue(self.settings.height)
        row.addWidget(self.height_spin)
        row.addStretch()
        v.addLayout(row)
        return card

    def _make_jvm_card(self):
        card, v = self._card("额外 JVM 参数",
                             "追加在启动命令中（空格分隔），如 -XX:+UseG1GC -Dfile.encoding=UTF-8；不懂请留空")
        self.jvm_edit = QLineEdit(self.settings.jvm_args)
        self.jvm_edit.setPlaceholderText("留空则不追加任何参数")
        v.addWidget(self.jvm_edit)
        return card

    def _make_isolation_card(self):
        card, v = self._card(
            "版本隔离",
            "开启后每个版本使用独立的 存档/模组/配置 目录（versions/<版本>/ 下），"
            "多版本、多整合包互不干扰；资源与库文件仍全局共享")
        self.iso_check = QCheckBox("默认对所有版本开启版本隔离")
        self.iso_check.setChecked(bool(self.settings.data.get("isolation")))
        v.addWidget(self.iso_check)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("按版本覆盖：", objectName="cardDesc"))
        self.iso_ver_combo = QComboBox()
        self.iso_ver_combo.setFixedWidth(240)
        row.addWidget(self.iso_ver_combo)
        self.iso_state_combo = QComboBox()
        self.iso_state_combo.addItem("跟随全局设置", None)
        self.iso_state_combo.addItem("强制开启", True)
        self.iso_state_combo.addItem("强制关闭", False)
        row.addWidget(self.iso_state_combo)
        self.iso_state_combo.currentIndexChanged.connect(self._on_version_iso_changed)
        v.addLayout(row)

        self.iso_ver_combo.currentTextChanged.connect(self._sync_iso_state)
        self._refresh_iso_versions()
        return card

    def _refresh_iso_versions(self):
        vroot = Path(GAME_DIR) / "versions"
        ids = []
        if vroot.is_dir():
            ids = sorted((d.name for d in vroot.iterdir()
                          if (d / f"{d.name}.json").is_file()), reverse=True)
        self.iso_ver_combo.blockSignals(True)
        self.iso_ver_combo.clear()
        self.iso_ver_combo.addItems(ids)
        self.iso_ver_combo.blockSignals(False)
        self._sync_iso_state(self.iso_ver_combo.currentText())

    def _sync_iso_state(self, vid):
        if not vid:
            return
        current = self.settings.data["per_version_isolation"].get(vid)
        combo = self.iso_state_combo
        combo.blockSignals(True)
        idx = 0
        for i in range(combo.count()):
            if combo.itemData(i) is not None and bool(combo.itemData(i)) == bool(current):
                idx = i
                break
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _on_version_iso_changed(self, _idx):
        vid = self.iso_ver_combo.currentText()
        if vid:
            self.settings.set_isolation_for(vid, self.iso_state_combo.currentData())
            state = {None: "跟随全局", True: "强制开启", False: "强制关闭"}[
                self.iso_state_combo.currentData()]
            self.save_hint.setText(f"{vid} 的隔离设置：{state}")

    # ---------- Java 扫描 ----------
    def _start_scan(self):
        if self._scan_thread is not None:
            return
        self.java_status.setText("正在扫描系统中的 Java…")
        self.btn_rescan.setEnabled(False)
        self._scan_thread = JavaScanThread()
        self._scan_thread.found.connect(self._on_java_found)
        start_worker(self._scan_thread, parent=self)

    def _on_java_found(self, javas):
        self._scan_thread = None
        self.btn_rescan.setEnabled(True)
        self._javas = javas
        self._fill_java_combo(self.java_combo, self.settings.java_path,
                              auto_label="自动检测")
        self._fill_version_java_combo()
        if javas:
            self.java_status.setText(
                f"检测到 {len(javas)} 个 Java：" +
                "、".join(f"Java {m}" for _p, m in javas[:5]))
        else:
            self.java_status.setText("未检测到系统 Java，启动时将自动下载官方运行时")

    def _fill_java_combo(self, combo, current, auto_label):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(auto_label, "")
        for path, major in self._javas:
            combo.addItem(f"Java {major} — {path}", path)
        if current:
            idx = combo.findData(current)
            if idx < 0:
                combo.addItem(current, current)  # 已保存但本次未扫描到
                idx = combo.count() - 1
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    # ---------- 按版本 Java ----------
    def _refresh_local_versions(self):
        vroot = Path(GAME_DIR) / "versions"
        ids = []
        if vroot.is_dir():
            ids = sorted((d.name for d in vroot.iterdir()
                          if (d / f"{d.name}.json").is_file()), reverse=True)
        self.ver_combo.clear()
        self.ver_combo.addItems(ids)

    def _fill_version_java_combo(self):
        combo = self.ver_java_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("跟随全局设置", "")
        for path, major in self._javas:
            combo.addItem(f"Java {major} — {path}", path)
        combo.blockSignals(False)
        self._sync_version_java_combo(self.ver_combo.currentText())

    def _sync_version_java_combo(self, vid):
        if not vid:
            return
        current = self.settings.per_version_java.get(vid, "")
        combo = self.ver_java_combo
        combo.blockSignals(True)
        idx = combo.findData(current)
        if idx < 0:
            if current:
                combo.addItem(current, current)
                idx = combo.count() - 1
            else:
                idx = 0
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _on_version_java_changed(self, _idx):
        vid = self.ver_combo.currentText()
        if vid:
            self.settings.set_java_for(vid, self.ver_java_combo.currentData())
            self.save_hint.setText(f"已记住 {vid} 的 Java 选择")

    def _browse_java(self, combo):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 java.exe", "", "Java (java.exe);;所有文件 (*)")
        if not path:
            return
        combo.blockSignals(True)
        idx = combo.findData(path)
        if idx < 0:
            combo.addItem(path, path)
            idx = combo.count() - 1
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        if combo is self.ver_java_combo:
            self._on_version_java_changed(0)

    # ---------- 保存 ----------
    def _save(self):
        s = self.settings
        s.data["java_path"] = self.java_combo.currentData() or ""
        s.data["memory_mb"] = self.mem_spin.value()
        s.data["width"] = self.width_spin.value()
        s.data["height"] = self.height_spin.value()
        s.data["jvm_args"] = self.jvm_edit.text().strip()
        s.data["isolation"] = self.iso_check.isChecked()
        s.save()
        self.save_hint.setText("已保存 ✓")

    def showEvent(self, e):
        super().showEvent(e)
        self.settings.load()
        self.mem_spin.setValue(self.settings.memory_mb)
        self.width_spin.setValue(self.settings.width)
        self.height_spin.setValue(self.settings.height)
        self.jvm_edit.setText(self.settings.jvm_args)
        self.iso_check.setChecked(bool(self.settings.data.get("isolation")))
        self._fill_java_combo(self.java_combo, self.settings.java_path,
                              auto_label="自动检测")
        self._refresh_local_versions()
        self._fill_version_java_combo()
        self._refresh_iso_versions()
