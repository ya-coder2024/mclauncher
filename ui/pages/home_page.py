# -*- coding: utf-8 -*-
"""主页：PCL2 经典布局 —— 顶部四宫格卡片 + 启动大卡片（含启动逻辑接线）"""

import json
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel,
    QFrame, QPushButton, QComboBox, QProgressBar,
)

from ui import theme
from ui.account_dialog import AccountDialog
from core.config import GAME_DIR
from core.version_manifest import fetch_manifest
from core.download_manager import DownloadManager
from core.auth import AccountStore
from core.launcher import LaunchWorker, scan_mods

_TYPE_LABEL = {"offline": "离线", "yggdrasil": "外置", "microsoft": "正版"}

# 顶部卡片：图标 / 标题 / 描述
_TOP_CARDS = [
    ("info", "公告", "查看最新的启动器公告"),
    ("log", "更新日志", "了解每个版本的改动内容"),
    ("community", "社区", "加入社区，与其他玩家交流"),
    ("sponsor", "赞助", "支持开发者，助力项目更新"),
]


def _is_local(vid):
    return (Path(GAME_DIR) / "versions" / vid / f"{vid}.json").is_file()


class _ManifestLoader(QThread):
    loaded = pyqtSignal(str, list)
    failed = pyqtSignal(str)

    def run(self):
        try:
            source, versions = fetch_manifest()
            self.loaded.emit(source, versions)
        except Exception as e:
            self.failed.emit(str(e))


class HomePage(QWidget):
    # 点击启动按钮时发出（携带所选版本）
    start_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._manifest = None          # 远端版本清单缓存
        self._manifest_loader = None
        self._downloader = None        # 下载线程
        self._worker = None            # 启动线程
        self._local_versions = []
        self.account_store = AccountStore(GAME_DIR)

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

        # ---- 顶部四宫格卡片 ----
        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        for icon_name, title, desc in _TOP_CARDS:
            top_row.addWidget(self._make_small_card(icon_name, title, desc))
        page.addLayout(top_row)

        # ---- 启动大卡片 ----
        page.addWidget(self._make_launch_card())
        page.addStretch()

        self.refresh_versions()
        self._refresh_account_label()

    # ---------- 构建小卡片 ----------
    def _make_small_card(self, icon_name, title, desc):
        card = QFrame(objectName="card")
        card.setCursor(Qt.PointingHandCursor)
        card.setFixedHeight(92)

        v = QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(10)
        icon_label = QLabel()
        icon_label.setPixmap(theme.icon(icon_name, color=theme.COLORS["accent"]).pixmap(24, 24))
        head.addWidget(icon_label)
        title_label = QLabel(title, objectName="cardTitle")
        head.addWidget(title_label)
        head.addStretch()
        v.addLayout(head)

        desc_label = QLabel(desc, objectName="cardDesc")
        desc_label.setWordWrap(True)
        v.addWidget(desc_label)
        return card

    # ---------- 构建启动大卡片 ----------
    def _make_launch_card(self):
        card = QFrame(objectName="card")
        card.setMinimumHeight(220)

        h = QHBoxLayout(card)
        h.setContentsMargins(24, 24, 24, 24)
        h.setSpacing(24)

        # 左侧：账号 + 版本选择 + 状态 + 启动按钮
        left = QVBoxLayout()
        left.setSpacing(10)

        # 账号行
        left.addWidget(QLabel("游戏账号", objectName="cardTitle"))
        acct_row = QHBoxLayout()
        acct_row.setSpacing(8)
        self.account_label = QLabel("未登录（默认离线）", objectName="cardDesc")
        acct_row.addWidget(self.account_label, 1)
        self.btn_account = QPushButton("添加 / 切换", objectName="small")
        self.btn_account.clicked.connect(self._open_account_dialog)
        acct_row.addWidget(self.btn_account)
        left.addLayout(acct_row)

        left.addWidget(QLabel("选择版本", objectName="cardTitle"))

        self.version_box = QComboBox()
        self.version_box.setFixedWidth(240)
        self.version_box.currentTextChanged.connect(self._update_desc)
        left.addWidget(self.version_box)

        self.launch_status = QLabel("就绪", objectName="cardDesc")
        self.launch_status.setWordWrap(True)
        left.addWidget(self.launch_status)

        self.launch_progress = QProgressBar()
        self.launch_progress.setFixedHeight(8)
        self.launch_progress.setTextVisible(False)
        self.launch_progress.hide()
        left.addWidget(self.launch_progress)

        left.addStretch()

        self.btn_launch = QPushButton("启动游戏", objectName="btnLaunch")
        self.btn_launch.setFixedWidth(240)
        self.btn_launch.clicked.connect(self._on_launch)
        left.addWidget(self.btn_launch)

        h.addLayout(left, 1)

        # 右侧：所选版本说明
        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(QLabel("当前选中版本", objectName="cardTitle"))
        self.version_desc = QLabel("—", objectName="cardDesc")
        self.version_desc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.version_desc.setWordWrap(True)
        right.addWidget(self.version_desc)
        right.addStretch()
        h.addLayout(right, 1)
        return card

    # ---------- 版本列表 ----------
    def refresh_versions(self):
        """扫描本地版本目录；为空时自动列出在线版本"""
        vroot = Path(GAME_DIR) / "versions"
        items = []
        if vroot.is_dir():
            for d in vroot.iterdir():
                if (d / f"{d.name}.json").is_file():
                    items.append(d.name)
        items.sort(reverse=True)
        self._local_versions = items

        keep = self.version_box.currentText()
        self.version_box.blockSignals(True)
        self.version_box.clear()
        if items:
            self.version_box.addItems(items)
            if keep in items:
                self.version_box.setCurrentText(keep)
            self.version_box.blockSignals(False)
            self.btn_launch.setEnabled(True)
            self._update_desc(self.version_box.currentText())
            return
        self.version_box.blockSignals(False)
        self.btn_launch.setEnabled(False)
        self.version_box.addItem("（正在获取在线版本…）")
        if self._manifest_loader is None:
            self.launch_status.setText("本地暂无版本，正在获取在线版本列表…")
            self._manifest_loader = _ManifestLoader()
            self._manifest_loader.loaded.connect(self._fill_remote)
            self._manifest_loader.failed.connect(self._on_manifest_failed)
            self._manifest_loader.start()

    def _fill_remote(self, source, versions):
        self._manifest = versions
        if self._local_versions:
            return
        ids = [v["id"] for v in versions if v.get("type") == "release"][:60]
        self.version_box.clear()
        self.version_box.addItems(ids)
        self.btn_launch.setEnabled(bool(ids))
        self.launch_status.setText(
            f"本地暂无版本，已列出在线版本（{source}）——选中后点击启动将自动下载并进入游戏"
        )
        self._update_desc(self.version_box.currentText())

    def _on_manifest_failed(self, err):
        self.version_box.clear()
        self.version_box.addItem("（版本清单获取失败）")
        self.launch_status.setText(f"版本清单获取失败：{err}")

    # ---------- 版本说明 ----------
    def _update_desc(self, text):
        if not text or text.startswith("（"):
            self.version_desc.setText("—")
            return
        jp = Path(GAME_DIR) / "versions" / text / f"{text}.json"
        if jp.is_file():
            try:
                data = json.loads(jp.read_text(encoding="utf-8"))
                jv = data.get("javaVersion", {})
                mods = scan_mods(GAME_DIR, include_disabled=False)
                mod_line = ""
                if mods:
                    names = "、".join(m["name"] for m in mods[:6])
                    more = f" 等{len(mods)}个" if len(mods) > 6 else ""
                    mod_line = f"\n已安装模组：{names}{more}"
                else:
                    mod_line = "\n已安装模组：无（mods 目录为空）"
                self.version_desc.setText(
                    f"{text}\n\n类型：{data.get('type', '-')}\n"
                    f"Java：{jv.get('majorVersion', '-')}（{jv.get('component', '-')}）\n"
                    f"发布时间：{str(data.get('releaseTime', ''))[:10]}"
                    f"{mod_line}"
                )
                return
            except Exception:
                pass
        self.version_desc.setText(
            f"{text}\n\n该版本尚未下载。\n点击启动将自动完成下载、\n依赖补全与 Java 运行时安装。"
        )

    # ---------- 账号 ----------
    def _open_account_dialog(self):
        dlg = AccountDialog(self)
        dlg.logged_in.connect(self._on_account_logged_in)
        dlg.exec_()

    def _on_account_logged_in(self, account):
        self.account_store.add(account)
        self._refresh_account_label()

    def _refresh_account_label(self):
        a = self.account_store.current()
        if a:
            self.account_label.setText(
                f"{a['name']}（{_TYPE_LABEL.get(a['type'], a['type'])}）"
            )
        else:
            self.account_label.setText("未登录（默认离线）")

    # ---------- 启动流程 ----------
    def _on_launch(self):
        vid = self.version_box.currentText()
        if not vid or vid.startswith("（"):
            return
        if self._worker is not None or self._downloader is not None:
            return
        if _is_local(vid):
            self._start_launch(vid)
        else:
            self._download_then_launch(vid)

    def _start_launch(self, vid):
        if self._worker is not None:
            return
        self.btn_launch.setEnabled(False)
        self.launch_status.setText(f"正在准备启动 {vid}…")
        self.launch_progress.show()
        self.launch_progress.setValue(0)
        self._worker = LaunchWorker(GAME_DIR, vid,
                                    account=self.account_store.current())
        self._worker.status.connect(self.launch_status.setText)
        self._worker.progress.connect(self.launch_progress.setValue)
        self._worker.launched.connect(self._on_launched)
        self._worker.failed.connect(self._on_launch_failed)
        self._worker.start()

    def _on_launched(self, pid):
        self.launch_status.setText(
            f"游戏已启动（PID {pid}）。游戏窗口稍后弹出，日志见 versions/{self.version_box.currentText()}/launcher-log.txt"
        )
        self.launch_progress.hide()
        self.btn_launch.setEnabled(True)
        self._worker = None
        self.start_requested.emit(self.version_box.currentText())

    def _on_launch_failed(self, err):
        self.launch_status.setText(f"启动失败：{err}")
        self.launch_progress.hide()
        self.btn_launch.setEnabled(True)
        self._worker = None

    # ---------- 未下载版本：先下载再启动 ----------
    def _download_then_launch(self, vid):
        if not self._manifest:
            self.launch_status.setText("正在获取版本清单…")
            self.launch_progress.show()
            self._pending_vid = vid
            if self._manifest_loader is None:
                self._manifest_loader = _ManifestLoader()
                self._manifest_loader.loaded.connect(self._on_manifest_retry)
                self._manifest_loader.failed.connect(self._on_download_failed)
                self._manifest_loader.start()
            return
        url = next((v["url"] for v in self._manifest if v["id"] == vid), None)
        if not url:
            self.launch_status.setText(f"版本清单中找不到 {vid}")
            return
        self.launch_status.setText(f"{vid} 尚未下载，正在自动下载（json + 客户端）…")
        self.launch_progress.show()
        self.launch_progress.setValue(0)
        self._downloader = DownloadManager(vid, url, GAME_DIR)
        self._downloader.progress.connect(self.launch_progress.setValue)
        self._downloader.finished_ok.connect(self._on_downloaded)
        self._downloader.failed.connect(self._on_download_failed)
        self._downloader.start()

    def _on_manifest_retry(self, source, versions):
        self._manifest = versions
        vid = getattr(self, "_pending_vid", None)
        if vid:
            self._download_then_launch(vid)

    def _on_downloaded(self, vid):
        self._downloader = None
        self.refresh_versions()
        self._start_launch(vid)

    def _on_download_failed(self, err):
        self.launch_status.setText(f"下载失败：{err}")
        self.launch_progress.hide()
        self._downloader = None

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh_versions()
