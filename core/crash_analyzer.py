# -*- coding: utf-8 -*-
"""游戏日志 / 崩溃报告分析：模式匹配给出可读结论与修复建议"""

import re
from pathlib import Path

# (正则, 结论, 建议)
LOG_PATTERNS = [
    (r"OutOfMemoryError|java\.lang\.OutOfMemoryError", "内存溢出（OOM）",
     "到「设置」把内存调大；大型整合包建议 6144 MB 以上"),
    (r"STATUS_HEAP_CORRUPTION", "堆损坏（多为下载文件损坏）",
     "删除对应版本的 jar/库文件后重新启动，让启动器重新下载"),
    (r"UnsupportedClassVersionError", "Java 版本过低",
     "到「设置」为该版本指定更高版本 Java"),
    (r"ClassNotFoundException.*KnotClient", "Fabric 加载器未正确安装",
     "到「下载」页重新为此版本安装 Fabric"),
    (r"ModResolutionException", "模组依赖缺失或版本不符",
     "看日志中 requires 后面的模组名，到「模组」页搜索安装对应依赖"),
    (r"Incompatible mods|conflicting mods", "模组冲突",
     "到「模组」页禁用冲突模组后重试"),
    (r"GLFW error 65542|WGL: The driver|Failed to create window", "显卡驱动不支持所需 OpenGL",
     "更新显卡驱动；笔记本注意切换到独显/核显正确设备"),
    (r"Invalid session|Failed to verify username|Failed to log in", "登录状态失效",
     "回「主页」重新登录账号（正版/外置令牌过期）"),
    (r"Connection (?:refused|timed out)", "网络连接失败",
     "检查网络；下载慢可在加速后再试"),
    (r"Access is denied|STATUS_ACCESS_VIOLATION", "文件访问异常",
     "关闭占用游戏目录的程序（杀毒/同步盘）后重试"),
    (r"Mixin apply failed|MixinApplyError", "Mixin 注入失败（模组不兼容当前版本）",
     "更新或移除日志中提到的模组"),
    (r"Shader compilation|Failed to load shader", "光影加载失败",
     "移除不兼容的光影包"),
]

# 进程退出码 → 说明（Windows 常见 NTSTATUS）
EXIT_CODE_HINTS = {
    1: "游戏内部错误（看日志中的 Exception）",
    -1073741819: "访问冲突 0xC0000005（多为显卡驱动或 natives 问题）",
    -1073740791: "栈缓冲区溢出 0xC0000409（多为文件损坏）",
    -1073740940: "堆损坏 0xC0000374（多为下载文件损坏，删掉重下）",
    -805306369: "Java 堆/内存配置异常",
}


def _read_tail(path, max_kb=512):
    """读文件尾部（中文环境按 GBK 解码，容错）"""
    p = Path(path)
    size = p.stat().st_size
    with open(p, "rb") as f:
        if size > max_kb * 1024:
            f.seek(-max_kb * 1024, 2)
        data = f.read()
    return data.decode("gbk", errors="replace")


def analyze_log(path):
    """分析运行日志尾部，返回 [{title, hint, line}]，无命中返回 []"""
    try:
        text = _read_tail(path)
    except OSError:
        return []
    findings = []
    for pattern, title, hint in LOG_PATTERNS:
        m = re.search(pattern, text)
        if m:
            line = next((ln.strip() for ln in text.splitlines() if re.search(pattern, ln)), "")
            findings.append({"title": title, "hint": hint, "line": line[:150]})
    return findings


def analyze_exit_code(code):
    """退出码 → 可读说明，未知返回 None"""
    if code in EXIT_CODE_HINTS:
        return EXIT_CODE_HINTS[code]
    if code != 0:
        return f"退出码 {code}（0x{code & 0xFFFFFFFF:08X}）"
    return None


def analyze_crash_report(path):
    """解析 crash-report 文件，返回 {description, exception, mods, findings}"""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"error": str(e)}

    result = {"findings": []}
    m = re.search(r"^Description:\s*(.+)$", text, re.M)
    if m:
        result["description"] = m.group(1).strip()
    m = re.search(r"^((?:[\w.$]+)?(?:Exception|Error)[\w.$]*(?::\s*.+)?)$", text, re.M)
    if m:
        result["exception"] = m.group(1).strip()
    m = re.search(r"Suspected Mods:\s*(.+?)(?:\n\s*\n|\Z)", text, re.S)
    if m:
        mods = [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]
        result["mods"] = mods[:8]

    for pattern, title, hint in LOG_PATTERNS:
        if re.search(pattern, text):
            result["findings"].append({"title": title, "hint": hint})
    return result
