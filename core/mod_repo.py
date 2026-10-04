# -*- coding: utf-8 -*-
"""Modrinth 模组仓库对接：搜索 / 版本列表 / 必需依赖解析。

Modrinth API v2 完全开放，无需密钥。
文档：https://docs.modrinth.com/
"""

import json

import requests

API_BASE = "https://api.modrinth.com/v2"
_HEADERS = {"User-Agent": "PCL-MinecraftLauncher/0.1 (ya-coder2024)"}
TIMEOUT = 20

# 加载器标识：界面名称 -> Modrinth category
LOADERS = ["fabric", "forge", "quilt", "neoforge"]
LOADER_NAMES = {
    "fabric": "Fabric",
    "forge": "Forge",
    "quilt": "Quilt",
    "neoforge": "NeoForge",
}


def _get(path, params=None):
    r = requests.get(API_BASE + path, params=params, headers=_HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def search_mods(query="", mc_version=None, loader=None, offset=0, limit=20):
    """搜索模组。返回 (结果列表, 命中总数)。

    每个结果：{project_id, slug, title, description, author,
              downloads, categories, icon_url}
    """
    return _search("mod", query, mc_version, loader, offset, limit)


def search_modpacks(query="", mc_version=None, offset=0, limit=20):
    """搜索整合包（project_type=modpack），返回结构同 search_mods"""
    return _search("modpack", query, mc_version, None, offset, limit)


def search_resourcepacks(query="", mc_version=None, offset=0, limit=20):
    """搜索资源包（project_type=resourcepack），返回结构同 search_mods"""
    return _search("resourcepack", query, mc_version, None, offset, limit)


def search_shaders(query="", mc_version=None, offset=0, limit=20):
    """搜索光影（project_type=shader），返回结构同 search_mods"""
    return _search("shader", query, mc_version, None, offset, limit)


def _search(project_type, query, mc_version, loader, offset, limit):
    facets = [[f"project_type:{project_type}"]]
    if mc_version:
        facets.append([f"versions:{mc_version}"])
    if loader:
        facets.append([f"categories:{loader}"])

    data = _get("/search", {
        "query": query,
        "facets": json.dumps(facets, separators=(",", ":")),
        "limit": limit,
        "offset": offset,
        "index": "relevance",
    })
    hits = []
    for h in data.get("hits", []):
        hits.append({
            "project_id": h.get("project_id"),
            "slug": h.get("slug"),
            "title": h.get("title", ""),
            "description": h.get("description", ""),
            "author": h.get("author", ""),
            "downloads": h.get("downloads", 0),
            "categories": h.get("categories", []),
            "icon_url": h.get("icon_url"),
        })
    return hits, data.get("total_hits", 0)


def list_versions(project_id, mc_version=None, loader=None):
    """获取某模组的可用版本（新→旧），可按游戏版本/加载器过滤。"""
    params = {}
    if loader:
        params["loaders"] = json.dumps([loader])
    if mc_version:
        params["game_versions"] = json.dumps([mc_version])
    return _get(f"/project/{project_id}/version", params)


def get_version(version_id):
    """按 ID 获取单个版本（依赖解析用）。"""
    return _get(f"/version/{version_id}")


def _primary_file(version):
    files = version.get("files", [])
    if not files:
        return None
    for f in files:
        if f.get("primary"):
            return f
    return files[0]


def _pick_compatible(project_id, prefer_loaders, prefer_versions):
    """依赖只给了 project_id 时，挑一个最匹配的版本：
    优先正式版 + 加载器/游戏版本有交集。
    """
    candidates = list_versions(project_id)
    loaders = set(prefer_loaders or [])
    gvs = set(prefer_versions or [])

    def score(v):
        s = 0
        if loaders:
            s += 2 * len(loaders & set(v.get("loaders", [])))
        if gvs:
            s += 2 * len(gvs & set(v.get("game_versions", [])))
        if v.get("version_type") == "release":
            s += 1
        return s

    if candidates:
        best = max(candidates, key=score)
        if score(best) > 0:
            return best
        return candidates[0]
    return None


def resolve_install_files(version):
    """给定选中的版本，递归收集“主文件 + 全部必需依赖”的下载任务。

    返回 [{"url", "filename", "sha1", "title"}]，主模组在最前。
    已包含按 project_id / 文件名去重与循环引用保护。
    """
    tasks = []
    seen_projects = set()
    seen_files = set()

    def _add(v, title):
        pid = v.get("project_id")
        if pid and pid in seen_projects:
            return
        if pid:
            seen_projects.add(pid)

        f = _primary_file(v)
        if not f:
            return
        fn = f.get("filename")
        if not fn or fn in seen_files:
            return
        seen_files.add(fn)
        tasks.append({
            "url": f.get("url"),
            "filename": fn,
            "sha1": (f.get("hashes") or {}).get("sha1"),
            "title": title or v.get("name", fn),
        })

        for dep in v.get("dependencies", []):
            if dep.get("dependency_type") != "required":
                continue
            dv = None
            if dep.get("version_id"):
                dv = get_version(dep["version_id"])
            elif dep.get("project_id"):
                dv = _pick_compatible(
                    dep["project_id"],
                    v.get("loaders", []),
                    v.get("game_versions", []),
                )
            if dv:
                _add(dv, dep.get("file_name") or dv.get("name"))

    _add(version, None)
    return tasks
