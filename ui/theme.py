# -*- coding: utf-8 -*-
"""PCL 风格主题：配色常量、全局 QSS、SVG 线性图标"""

from PyQt5.QtCore import QByteArray, QSize, Qt
from PyQt5.QtGui import QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer

# ---------- 配色（PCL2 经典款：深色侧边栏 + 浅色内容区） ----------
COLORS = {
    # 侧边栏 / 标题栏（深色）
    "sidebar_bg": "#1B1F2B",
    "sidebar_hover": "#272D3D",
    "sidebar_selected": "#3B82F6",
    "sidebar_text": "#B9C0D0",
    "sidebar_text_active": "#FFFFFF",
    "titlebar_bg": "#1B1F2B",
    # 内容区（浅色）
    "content_bg": "#F4F5F7",
    "card_bg": "#FFFFFF",
    "card_border": "#E3E6EB",
    # 文字
    "text_primary": "#1F2937",
    "text_secondary": "#6B7280",
    # 主题色
    "accent": "#3B82F6",
    "accent_hover": "#2F6FE0",
    # 启动按钮渐变
    "launch_top": "#4A8DF8",
    "launch_bottom": "#2F6FE0",
    # 窗口控制按钮 hover
    "btn_close_hover": "#E81123",
    "btn_win_hover": "#333A4D",
}


def qss():
    """全局样式表"""
    c = COLORS
    return f"""
    QMainWindow, QWidget#central {{ background: {c['content_bg']}; }}

    /* ---------- 标题栏 ---------- */
    QWidget#titlebar {{
        background: {c['titlebar_bg']};
    }}
    QLabel#logoText {{
        color: #FFFFFF; font-size: 15px; font-weight: bold;
    }}
    QLabel#logoBadge {{
        background: {c['accent']};
        color: white; font-size: 13px; font-weight: bold;
        border-radius: 6px;
    }}
    QPushButton#btnMin, QPushButton#btnMax, QPushButton#btnClose {{
        background: transparent; color: {c['sidebar_text']};
        border: none; border-radius: 0px;
        font-size: 14px; font-family: "Segoe MDL2 Assets";
    }}
    QPushButton#btnMin:hover, QPushButton#btnMax:hover {{ background: {c['btn_win_hover']}; color: white; }}
    QPushButton#btnClose:hover {{ background: {c['btn_close_hover']}; color: white; }}

    /* ---------- 侧边栏 ---------- */
    QWidget#sidebar {{ background: {c['sidebar_bg']}; }}
    QLabel#sidebarTitle {{
        color: {c['sidebar_text']}; font-size: 12px;
        padding: 6px 18px 2px 18px;
    }}
    QPushButton#nav {{
        background: transparent;
        color: {c['sidebar_text']};
        border: none; border-radius: 8px;
        padding: 0px 14px;
        text-align: left;
        font-size: 14px;
        min-height: 40px; max-height: 40px;
    }}
    QPushButton#nav:hover {{ background: {c['sidebar_hover']}; color: #FFFFFF; }}
    QPushButton#nav:checked {{
        background: {c['sidebar_selected']};
        color: {c['sidebar_text_active']};
        font-weight: bold;
    }}
    QLabel#versionTag {{ color: #5A6172; font-size: 11px; }}

    /* ---------- 内容区卡片 ---------- */
    QFrame#card {{
        background: {c['card_bg']};
        border: 1px solid {c['card_border']};
        border-radius: 10px;
    }}
    QLabel#pageTitle {{ color: {c['text_primary']}; font-size: 20px; font-weight: bold; }}
    QLabel#cardTitle {{ color: {c['text_primary']}; font-size: 14px; font-weight: bold; }}
    QLabel#cardDesc  {{ color: {c['text_secondary']}; font-size: 12px; }}

    /* ---------- 启动大按钮 ---------- */
    QPushButton#btnLaunch {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                     stop:0 {c['launch_top']}, stop:1 {c['launch_bottom']});
        color: white; font-size: 17px; font-weight: bold;
        border: none; border-radius: 10px;
        min-height: 52px;
    }}
    QPushButton#btnLaunch:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                     stop:0 #5B98F9, stop:1 {c['accent_hover']});
    }}
    QPushButton#btnLaunch:pressed {{ background: {c['accent_hover']}; }}

    /* ---------- 通用按钮 / 下拉框 ---------- */
    QPushButton#small {{
        background: {c['card_bg']};
        color: {c['text_primary']};
        border: 1px solid {c['card_border']};
        border-radius: 8px;
        padding: 7px 16px; font-size: 13px;
    }}
    QPushButton#small:hover {{
        border-color: {c['accent']}; color: {c['accent']};
    }}
    QComboBox {{
        background: {c['card_bg']};
        border: 1px solid {c['card_border']};
        border-radius: 8px;
        padding: 8px 14px; font-size: 13px;
        color: {c['text_primary']};
    }}
    QComboBox:hover {{ border-color: {c['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox QAbstractItemView {{
        background: white; color: {c['text_primary']};
        border: 1px solid {c['card_border']};
        selection-background-color: {c['accent']};
        selection-color: white;
        outline: none;
    }}

    /* ---------- 下载页 ---------- */
    QListWidget#versionList {{
        background: {c['card_bg']};
        border: 1px solid {c['card_border']};
        border-radius: 10px;
    }}
    QListWidget#versionList::item {{ border-bottom: 1px solid {c['card_border']}; }}
    QListWidget#versionList::item:selected {{ background: #EAF2FE; color: {c['text_primary']}; }}
    QListWidget#versionList::item:hover {{ background: #F5F8FD; }}
    QLineEdit {{
        background: {c['card_bg']};
        border: 1px solid {c['card_border']};
        border-radius: 8px;
        padding: 8px 12px; font-size: 13px;
        color: {c['text_primary']};
    }}
    QLineEdit:focus {{ border-color: {c['accent']}; }}
    QPushButton#small:checked {{
        background: {c['accent']}; color: white; border-color: {c['accent']};
    }}
    QProgressBar#downloadProgress {{
        background: {c['card_border']};
        border: none; border-radius: 5px;
    }}
    QProgressBar#downloadProgress::chunk {{
        background: {c['accent']}; border-radius: 5px;
    }}

    /* ---------- 滚动区 ---------- */
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{
        background: transparent; width: 8px; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: #C9CDD4; border-radius: 4px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: #AEB3BC; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


# ---------- SVG 图标（白色线性，24x24） ----------
_ICONS = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>',
    "download": '<path d="M12 3v12"/><path d="m7 11 5 5 5-5"/><path d="M4 21h16"/>',
    "mods": '<path d="M21 8l-9-5-9 5v8l9 5 9-5z"/><path d="M3 8l9 5 9-5"/><path d="M12 13v8"/>',
    "packs": '<rect x="3" y="8" width="13" height="13" rx="2"/><path d="M8 8V5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-3"/>',
    "resources": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "tasks": '<path d="M9 6h12M9 12h12M9 18h12"/><path d="M3 6l1.5 1.5L7 5"/><path d="M3 12l1.5 1.5L7 11"/><path d="M3 18l1.5 1.5L7 17"/>',
    "logs": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8M8 17h5"/>',
    "multiplayer": '<circle cx="9" cy="8" r="3.2"/><path d="M3.5 20c0-3.2 2.5-5.2 5.5-5.2s5.5 2 5.5 5.2"/><circle cx="17" cy="9" r="2.4"/><path d="M16.5 14.6c2.6.2 4.5 2 4.5 4.9"/>',
    "settings": '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.8v3M12 18.2v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2.8 12h3M18.2 12h3M4.9 19.1 7 17M17 7l2.1-2.1"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 8h.01"/><path d="M12 11.5V16"/>',
    "log": '<path d="M6 3h12v18H6z"/><path d="M9 8h6M9 12h6M9 16h4"/>',
    "community": '<circle cx="8" cy="9" r="2.8"/><circle cx="16" cy="9" r="2.8"/><path d="M2.8 19c0-2.9 2.3-4.7 5.2-4.7M21.2 19c0-2.9-2.3-4.7-5.2-4.7"/>',
    "sponsor": '<path d="M12 20.5S4 15 4 9.5A4.5 4.5 0 0 1 12 6a4.5 4.5 0 0 1 8 3.5c0 5.5-8 11-8 11Z"/>',
}


def icon(name: str, color: str = "#FFFFFF", size: int = 22) -> QIcon:
    """从 SVG 字符串渲染线性图标，避免外部资源文件"""
    path = _ICONS.get(name, _ICONS["info"])
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round">{path}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(QSize(size * 2, size * 2))  # 2x 渲染抗锯齿
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return QIcon(pm)
