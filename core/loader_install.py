# -*- coding: utf-8 -*-
"""一键安装模组加载器：Fabric（通过 Fabric Meta API）。

流程：
1. 查询某游戏版本可用的 Fabric Loader；
2. 下载 loader 的版本 profile（含 inheritsFrom + fabric 库 + KnotClient 主类）；
3. 与原版版本 json 合并（库去重、主类覆盖、参数合并），生成完整版本 json；
4. 现有 launch() 直接可用：Maven 库自动下载，client 走原版。
"""

import json
from pathlib import Path

import requests

from core.version_manifest import fetch_manifest

FABRIC_META = "https://meta.fabricmc.net"
TIMEOUT = 30


class LoaderError(Exception):
    """加载器安装失败（信息直接展示给用户）"""


def _get_json(url):
    try:
        r = requests.get(url, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise LoaderError(f"网络连接失败：{e}")
    if r.status_code != 200:
        raise LoaderError(f"请求失败（HTTP {r.status_code}）：{url}")
    return r.json()


# ---------------- 查询 ----------------

def list_fabric_loaders(mc_version):
    """返回 [(版本号, 是否稳定)]，最新在前"""
    data = _get_json(f"{FABRIC_META}/v2/versions/loader/{mc_version}")
    if not data:
        raise LoaderError(f"Fabric 暂不支持游戏版本 {mc_version}")
    out = []
    for item in data:
        ld = item.get("loader", {})
        out.append((ld.get("version", ""), bool(ld.get("stable"))))
    return [(v, s) for v, s in out if v]


def latest_stable_loader(mc_version):
    for v, stable in list_fabric_loaders(mc_version):
        if stable:
            return v
    return list_fabric_loaders(mc_version)[0][0]


def installed_ids(game_dir):
    """本地已安装版本 id 列表"""
    vroot = Path(game_dir) / "versions"
    if not vroot.is_dir():
        return []
    return [d.name for d in vroot.iterdir()
            if (d / f"{d.name}.json").is_file()]


# ---------------- 原版 json 获取 ----------------

def _ensure_base_json(game_dir, mc_version):
    """确保原版 json 存在，返回其内容（dict）"""
    vdir = Path(game_dir) / "versions" / mc_version
    jp = vdir / f"{mc_version}.json"
    if jp.is_file():
        return json.loads(jp.read_text(encoding="utf-8"))

    # 本地没有：从版本清单取 url 下载 json（仅 json，不下载游戏文件）
    _, versions = fetch_manifest()
    v = next((v for v in versions if v["id"] == mc_version), None)
    if not v:
        raise LoaderError(f"版本清单中找不到 {mc_version}")
    data = _get_json(v["url"])
    vdir.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                  encoding="utf-8")
    return data


# ---------------- 合并 ----------------

def _lib_name(lib):
    """libraries 条目去重键：优先 name（Maven 坐标）"""
    return lib.get("name", "")


def _merge_profile(base, loader_profile, new_id):
    """合并原版 json 与 loader profile，返回完整版本 json"""
    merged = dict(base)
    merged["id"] = new_id

    # 库：loader 的在前，原版补后，按 Maven 坐标去重
    seen, libs = set(), []
    for lib in loader_profile.get("libraries", []) + base.get("libraries", []):
        key = _lib_name(lib)
        if key and key in seen:
            continue
        seen.add(key)
        libs.append(lib)
    merged["libraries"] = libs

    # 主类：loader 覆盖
    if loader_profile.get("mainClass"):
        merged["mainClass"] = loader_profile["mainClass"]

    # 参数合并（现代版本结构）
    b_args = base.get("arguments", {})
    l_args = loader_profile.get("arguments", {})
    if b_args or l_args:
        merged["arguments"] = {
            "game": list(l_args.get("game", [])) + list(b_args.get("game", [])),
            "jvm": list(l_args.get("jvm", [])) + list(b_args.get("jvm", [])),
        }

    merged["type"] = "modified"
    return merged


# ---------------- 安装 ----------------

def install_fabric(game_dir, mc_version, loader_version=None,
                   status_cb=None):
    """安装 Fabric，返回新版本 id。status_cb(msg) 可选。"""
    def say(m):
        if status_cb:
            status_cb(m)

    if loader_version is None:
        say(f"正在查询 {mc_version} 的 Fabric Loader…")
        loader_version = latest_stable_loader(mc_version)

    new_id = f"{mc_version}-Fabric {loader_version}"
    if new_id in installed_ids(game_dir):
        raise LoaderError(f"版本 {new_id} 已安装，无需重复安装")

    say(f"正在下载 Fabric Loader {loader_version} 的版本信息…")
    profile = _get_json(
        f"{FABRIC_META}/v2/versions/loader/{mc_version}/"
        f"{loader_version}/profile/json"
    )

    say(f"正在获取原版 {mc_version} 的版本信息…")
    base = _ensure_base_json(game_dir, mc_version)

    say("正在合并版本配置…")
    merged = _merge_profile(base, profile, new_id)

    vdir = Path(game_dir) / "versions" / new_id
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / f"{new_id}.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    say(f"安装完成：{new_id}")
    return new_id
