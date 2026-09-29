# -*- coding: utf-8 -*-
"""版本清单获取：BMCLAPI 镜像优先，官方源回退"""

import requests

SOURCES = [
    ("BMCLAPI", "https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json"),
    ("官方", "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"),
]


def fetch_manifest(timeout=10):
    """返回 (来源名, 版本列表)；全部来源失败时抛 ConnectionError"""
    last_err = None
    for name, url in SOURCES:
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return name, r.json().get("versions", [])
        except Exception as e:
            last_err = e
    raise ConnectionError(f"所有下载源均不可用：{last_err}")
