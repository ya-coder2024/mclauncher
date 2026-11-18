# -*- coding: utf-8 -*-
"""authlib-injector 支持：外置登录（LittleSkin 等皮肤站）游戏内皮肤/正版验证必需。

原理：启动时给 JVM 挂 -javaagent:authlib-injector.jar=<apiRoot>，
由它把 Mojang 的 authlib 重定向到皮肤站，游戏内才能拉到皮肤、进正版验证服务器。
"""

import hashlib
import json
from pathlib import Path

import requests

# 官方分发点：latest.json 给出当前版本与直链
LATEST_JSON = "https://authlib-injector.yushi.moe/artifact/latest.json"
FALLBACK_URL = "https://authlib-injector.yushi.moe/artifact/56/authlib-injector-1.2.8.jar"
FALLBACK_SHA256 = "9c7f4343e6c82034958ffb48c14a2cb0c85928be7283103ce17da00c6d5a7b10"

CACHE_DIR_NAME = "launcher-lib"
JAR_PREFIX = "authlib-injector-"


class InjectorError(Exception):
    pass


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _cached(cache_dir):
    """已有下载过的 injector jar 直接复用（文件名带版本号）。"""
    if not cache_dir.is_dir():
        return None
    jars = sorted(cache_dir.glob(JAR_PREFIX + "*.jar"))
    for jar in reversed(jars):
        if jar.stat().st_size > 100_000:  # 排除下载中断的残包
            return jar
    return None


def _download(url, dest, expect_sha256=None, cancel=None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                if cancel and cancel():
                    tmp.unlink(missing_ok=True)
                    raise InjectorError("已取消")
                if chunk:
                    f.write(chunk)
    if expect_sha256:
        got = _sha256(tmp)
        if got.lower() != expect_sha256.lower():
            tmp.unlink(missing_ok=True)
            raise InjectorError("校验失败（文件可能被网络篡改）")
    tmp.replace(dest)
    return dest


def ensure_injector(game_dir, cancel=None, status_cb=None):
    """确保 authlib-injector jar 存在，返回 jar 路径。

    优先用本地缓存；否则拉 latest.json 取版本直链下载，
    全部失败则回退到固定版本链接。下载失败抛 InjectorError。
    """
    def say(m):
        if status_cb:
            status_cb(m)

    cache_dir = Path(game_dir) / CACHE_DIR_NAME
    hit = _cached(cache_dir)
    if hit:
        return hit

    say("正在准备外置登录组件（authlib-injector）…")
    targets = []
    try:
        meta = json.loads(requests.get(LATEST_JSON, timeout=15).text)
        ver = meta.get("version") or "latest"
        url = meta.get("download_url")
        sha = (meta.get("checksums") or {}).get("sha256")
        if url:
            targets.append((url, cache_dir / f"{JAR_PREFIX}{ver}.jar", sha))
    except Exception:
        pass  # 元数据拿不到就走固定链接

    targets.append((FALLBACK_URL, cache_dir / f"{JAR_PREFIX}1.2.8.jar", FALLBACK_SHA256))

    last_err = None
    for url, dest, sha in targets:
        try:
            return _download(url, dest, sha, cancel=cancel)
        except InjectorError:
            raise
        except Exception as e:
            last_err = e
    raise InjectorError(f"authlib-injector 下载失败：{last_err}")


def jvm_agent_args(jar_path, api_root):
    """生成注入用的 JVM 参数（每个元素是独立参数，交给 Popen 列表不会被空格截断）。"""
    return [
        f"-javaagent:{jar_path}={api_root}",
        "-Dauthlibinjector.side=client",
    ]
