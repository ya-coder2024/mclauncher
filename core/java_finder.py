# -*- coding: utf-8 -*-
"""系统 Java 检测：扫描 PATH / 环境变量 / 常见安装目录 / .minecraft runtime"""

import os
import re
import subprocess
from pathlib import Path

_VERSION_RE = re.compile(r'version "(\d+)(?:\.(\d+))?[."0-9]*')

_SCAN_DIRS = [
    r"C:\Program Files\Java",
    r"C:\Program Files\Eclipse Adoptium",
    r"C:\Program Files\Microsoft",
    r"C:\Program Files\Amazon Corretto",
    r"C:\Program Files\Zulu",
    r"C:\Program Files\BellSoft",
    r"C:\Program Files (x86)\Java",
    r"C:\Program Files (x86)\Eclipse Adoptium",
    r"D:\Java",
    r"D:\Program Files\Java",
    r"D:\Program Files\Eclipse Adoptium",
]


def probe_java(java_exe):
    """运行 java -version，返回主版本号，失败返回 None"""
    try:
        r = subprocess.run(
            [str(java_exe), "-version"],
            capture_output=True, timeout=15, creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        text = (r.stderr or "") + (r.stdout or "")
        m = _VERSION_RE.search(text)
        if not m:
            return None
        major = int(m.group(1))
        if major == 1 and m.group(2):  # 老式 "1.8.0_421" → 8
            major = int(m.group(2))
        return major
    except Exception:
        return None


def _collect_exes():
    exes, seen = [], set()

    def add(path):
        p = Path(path)
        if p.exists() and p not in seen:
            seen.add(p)
            exes.append(p)

    # PATH
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if d.strip():
            add(Path(d) / "java.exe")
    # JAVA_HOME
    jh = os.environ.get("JAVA_HOME")
    if jh:
        add(Path(jh) / "bin" / "java.exe")

    # 常见安装目录（根目录自身 + 其下一级子目录）
    roots = [Path(d) for d in _SCAN_DIRS]
    roots.append(Path.home() / "AppData" / "Local" / "Programs")
    roots.append(Path.home() / ".jdks")  # IDEA 下载的 JDK
    for root in roots:
        if not root.is_dir():
            continue
        add(root / "bin" / "java.exe")
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                add(child / "bin" / "java.exe")

    # 官方启动器 / PCL 下载的运行时（.minecraft/runtime 任意深度）
    base = Path.home() / "AppData" / "Roaming" / ".minecraft"
    if base.is_dir():
        try:
            for exe in base.rglob("java.exe"):
                add(exe)
        except OSError:
            pass
    return exes


def find_javas():
    """返回 [(路径, 主版本号), ...]，按版本号降序"""
    results = {}
    for exe in _collect_exes():
        major = probe_java(exe)
        if major:
            results[str(exe)] = major
    return sorted(results.items(), key=lambda kv: kv[1], reverse=True)


def pick_java(need_major=None, custom_path=None):
    """挑选最合适的 Java。优先：自定义路径 > 满足最低主版本（选刚好达标者）> 版本最高者"""
    javas = find_javas()
    if custom_path:
        p = Path(custom_path)
        exe = p if p.name.lower().endswith(".exe") else p / "bin" / "java.exe"
        if exe.exists():
            major = probe_java(exe)
            if major:
                return str(exe), major
    if need_major is not None:
        ok = [(p, m) for p, m in javas if m >= need_major]
        if ok:
            ok.sort(key=lambda kv: kv[1])
            return ok[0]
    if javas:
        return javas[0]
    return None, None


if __name__ == "__main__":
    found = find_javas()
    if not found:
        print("未检测到任何 Java")
    for p, m in found:
        print(f"Java {m}: {p}")
