# -*- coding: utf-8 -*-
"""Mojang 官方 Java 运行时下载安装（javaVersion.component → .minecraft/runtime/<component>/）"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

import platform
import requests

from core.downloader import download_file, file_ok, mirror_url
from core.java_finder import probe_java

# Mojang 运行时清单（hash 会随版本更新，需与官方保持一致）
_RUNTIME_PATH = "/v1/products/java-runtime/2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json"
_MANIFEST_URLS = (
    "https://bmclapi2.bangbang93.com" + _RUNTIME_PATH,
    "https://piston-meta.mojang.com" + _RUNTIME_PATH,
)

_WORKERS = 12


def platform_key():
    """Mojang 清单里的平台标识"""
    m = platform.machine()
    return {"AMD64": "windows-x64", "ARM64": "windows-arm64", "x86": "windows-x86"}.get(m, "windows-x64")


def runtime_java(game_dir, component):
    """已安装运行时的 java.exe 路径，未安装返回 None"""
    p = Path(game_dir) / "runtime" / component / "bin" / "java.exe"
    return p if p.exists() else None


def ensure_runtime(game_dir, component, use_mirror=True, progress_cb=None, cancel=None):
    """确保指定组件的官方运行时可用（已装则直接返回），返回 java.exe 路径"""
    exe = runtime_java(game_dir, component)
    if exe and probe_java(exe):
        return exe

    # 1. 获取运行时清单 all.json，结构：{<平台>: {<组件>: [{manifest: {url, sha1}}]}}
    sources = _MANIFEST_URLS if use_mirror else _MANIFEST_URLS[::-1]
    data, last_err = None, None
    for url in sources:
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:
            last_err = e
    if data is None:
        raise ConnectionError(f"Java 运行时清单获取失败：{last_err}")

    plat = data.get(platform_key(), {})
    entries = plat.get(component)
    if not entries:
        raise RuntimeError(f"运行时清单中没有 {component} / {platform_key()}")
    manifest_url = entries[0]["manifest"]["url"]
    if use_mirror:
        manifest_url = mirror_url(manifest_url)

    # 2. 获取组件 manifest.json，结构：{files: {<路径>: {type, downloads:{raw:{url,sha1,size}}}}}
    r = requests.get(manifest_url, timeout=30)
    r.raise_for_status()
    manifest = r.json()

    base = Path(game_dir) / "runtime" / component
    files = {p: f for p, f in manifest.get("files", {}).items() if f.get("type") == "file"}
    total = len(files)
    lock, done = Lock(), [0]

    def fetch(item):
        path, f = item
        raw = f["downloads"]["raw"]
        dest = base / path
        if not file_ok(dest, raw.get("sha1"), raw.get("size")):
            m_url = mirror_url(raw["url"]) if use_mirror else raw["url"]
            download_file(
                m_url, dest, sha1=raw.get("sha1"), timeout=120, cancel=cancel,
                fallback_url=raw["url"] if use_mirror else None,
            )
        with lock:
            done[0] += 1
            if progress_cb:
                progress_cb(done[0], total)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        list(pool.map(fetch, files.items()))

    exe = base / "bin" / "java.exe"
    if not probe_java(exe):
        raise RuntimeError(f"Java 运行时 {component} 安装后校验失败")
    return exe
