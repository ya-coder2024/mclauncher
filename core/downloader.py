# -*- coding: utf-8 -*-
"""流式下载 + SHA1 校验 + 进度回调"""

import hashlib
import time
from pathlib import Path

import requests

CHUNK = 256 * 1024


def requests_get(url, timeout=30, retries=3, stream=False, **kwargs):
    """requests.get 封装：网络抖动时自动重试（指数退避）"""
    last_err = None
    for i in range(retries):
        try:
            return requests.get(url, timeout=timeout, stream=stream, **kwargs)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout,
                requests.exceptions.ChunkedEncodingError) as e:
            last_err = e
            if i < retries - 1:
                time.sleep(1.5 * (i + 1))
    raise last_err

# 启用镜像时替换为 BMCLAPI 的官方域名
_OFFICIAL_HOSTS = (
    "https://piston-meta.mojang.com",
    "https://piston-data.mojang.com",
    "https://launchermeta.mojang.com",
    "https://launcher.mojang.com",
)
_MIRROR_BASE = "https://bmclapi2.bangbang93.com"


def mirror_url(url):
    """官方地址 → BMCLAPI 镜像（libraries / assets 走专用前缀）"""
    if url.startswith("https://libraries.minecraft.net/"):
        return _MIRROR_BASE + "/maven/" + url[len("https://libraries.minecraft.net/"):]
    if url.startswith("https://resources.download.minecraft.net/"):
        return _MIRROR_BASE + "/assets/" + url[len("https://resources.download.minecraft.net/"):]
    for host in _OFFICIAL_HOSTS:
        if url.startswith(host):
            return _MIRROR_BASE + url[len(host):]
    return url


def file_ok(dest, sha1=None, size=None):
    """文件存在且校验通过：有 SHA1 时校验 SHA1（最可靠），否则校验大小"""
    p = Path(dest)
    if not p.is_file():
        return False
    if size and p.stat().st_size != size:
        return False
    if sha1:
        h = hashlib.sha1()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(CHUNK), b""):
                h.update(chunk)
        return h.hexdigest() == sha1
    return True


def download_file(url, dest, sha1=None, progress_cb=None, timeout=60, cancel=None, retries=5, fallback_url=None):
    """下载单个文件，支持断点续传、中途断流重试、镜像失败回退官方源。

    progress_cb(received, total)：每块回调一次，total 可能为 0
    cancel()：返回 True 时中断，抛 InterruptedError
    fallback_url：主 url 全部重试失败后，改用该地址再试一次（用于 BMCLAPI → 官方）
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    last_err = None
    for attempt in range(retries):
        try:
            existing = dest.stat().st_size if dest.is_file() else 0
            headers = {"Range": f"bytes={existing}-"} if existing else None
            with requests_get(url, timeout=timeout, retries=1, stream=True, headers=headers) as r:
                # 206 = 服务器支持续传；200 = 不支持，从头开始
                resume = r.status_code == 206 and existing > 0
                if not resume and existing:
                    existing = 0
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", 0))
                if resume:
                    total += existing

                mode = "ab" if resume else "wb"
                done = existing
                with open(dest, mode) as f:
                    for chunk in r.iter_content(CHUNK):
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)
                        if progress_cb:
                            progress_cb(done, total)
                        if cancel and cancel():
                            raise InterruptedError("下载已取消")

                # 整文件校验
                if sha1:
                    h = hashlib.sha1()
                    with open(dest, "rb") as f:
                        for c in iter(lambda: f.read(CHUNK), b""):
                            h.update(c)
                    if h.hexdigest() != sha1:
                        dest.unlink(missing_ok=True)
                        raise ValueError(f"SHA1 校验失败：{dest.name}")
                return dest
        except InterruptedError:
            raise
        except (requests.exceptions.ConnectionError,
                requests.exceptions.ReadTimeout,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.HTTPError,
                ValueError) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            break

    # 主地址全部失败，回退到备用地址（支持单个 URL 或 URL 列表，依次尝试）
    if fallback_url:
        fallbacks = fallback_url if isinstance(fallback_url, list) else [fallback_url]
        for fb in fallbacks:
            if fb and fb != url:
                return download_file(fb, dest, sha1=sha1, progress_cb=progress_cb,
                                     timeout=timeout, cancel=cancel, retries=3,
                                     fallback_url=fallbacks[fallbacks.index(fb)+1:] or None)
    raise last_err
