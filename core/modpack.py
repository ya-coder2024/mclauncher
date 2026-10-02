# -*- coding: utf-8 -*-
"""Modrinth 整合包（.mrpack）安装。

.mrpack 本质是 zip：
- modrinth.index.json：包元数据 + files 下载清单 + 锁定的依赖版本
- overrides/、client-overrides/：直接解压到游戏目录的配置/资源

安装流程：原版 json → 锁定版本的加载器 → files 并行下载 → overrides 解压。
"""

import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from core import loader_install
from core.downloader import download_file, file_ok

# mrpack dependencies 键 → 本启动器加载器类型
_DEP_TO_KIND = {
    "fabric-loader": "fabric",
    "quilt-loader": "quilt",
    "forge": "forge",
    "neoforge": "neoforge",
}

_WORKERS = 12


class ModpackError(Exception):
    """整合包安装失败（信息直接展示给用户）"""


def read_index(pack_path):
    """读取 mrpack 的 modrinth.index.json，返回 dict"""
    try:
        with zipfile.ZipFile(pack_path) as z:
            return json.loads(z.read("modrinth.index.json").decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
        raise ModpackError(f"整合包文件无效（不是合法的 .mrpack）：{e}")


def install_mrpack(pack_path, game_dir, status_cb=None, progress_cb=None,
                   cancel=None, paused=None):
    """安装 .mrpack 到 game_dir，返回实例版本 id。

    整合包实例自动开启版本隔离：files/overrides 解压到 versions/<实例>/ 下，
    存档、模组、配置与其它版本完全隔离。
    progress_cb(0-100)；cancel() 返回 True 时中断；paused() 返回 True 时暂停下载。
    """
    game_dir = Path(game_dir)

    def say(m):
        if status_cb:
            status_cb(m)

    def report(p):
        if progress_cb:
            progress_cb(p)

    def cancelled():
        return cancel() if cancel else False

    index = read_index(pack_path)
    name = index.get("name", "modpack")
    ver = index.get("versionId", "")
    deps = index.get("dependencies") or {}
    mc_version = deps.get("minecraft")
    if not mc_version:
        raise ModpackError("整合包缺少 minecraft 依赖声明，无法安装")
    say(f"整合包：{name} {ver}（Minecraft {mc_version}）")
    report(5)

    # ---- 1. 原版 json ----
    if cancelled():
        raise InterruptedError("已取消")
    say(f"正在准备原版 {mc_version} 版本信息…")
    loader_install.ensure_base_json(game_dir, mc_version)
    report(15)

    # ---- 2. 加载器（按整合包锁定版本；已装过则复用其版本目录） ----
    loader_note = "无（纯原版）"
    new_id = mc_version
    for dep_key, kind in _DEP_TO_KIND.items():
        lv = deps.get(dep_key)
        if not lv:
            continue
        label = loader_install.LOADER_LABELS[kind]
        try:
            new_id = loader_install.install_loader(
                kind, game_dir, mc_version, loader_version=lv,
                status_cb=say)
            loader_note = f"{label} {lv}（{new_id}）"
        except loader_install.AlreadyInstalledError as e:
            new_id = e.version_id
            loader_note = f"{label} {lv}（已存在，复用）"
            say(f"{label} {lv} 已安装，复用版本 {new_id}")
        except loader_install.LoaderError as e:
            if "已安装" in str(e):
                loader_note = f"{label} {lv}（已存在，跳过）"
                say(f"{label} {lv} 已安装，跳过")
            else:
                raise
        break  # 一个整合包只应有一种加载器
    report(45)

    # ---- 整合包实例目录：版本隔离（存档/模组/配置互不干扰） ----
    target = Path(game_dir) / "versions" / new_id
    from core.config import Settings
    settings = Settings(game_dir)
    settings.set_isolation_for(new_id, True)
    say(f"实例版本：{new_id}（已自动开启版本隔离，数据写入该版本目录）")

    # ---- 3. files 并行下载（进入实例目录） ----
    files = []
    for f in index.get("files", []):
        env = f.get("env") or {}
        if env.get("client") == "unsupported":
            continue  # 服务端专用文件不装
        rel = f.get("path", "")
        # 路径安全：不允许绝对路径和 ..
        parts = [p for p in rel.replace("\\", "/").split("/")
                 if p not in ("", ".", "..")]
        if not parts:
            continue
        urls = f.get("downloads") or []
        if not urls:
            continue
        files.append({
            "dest": target.joinpath(*parts),
            "urls": urls,
            "sha1": (f.get("hashes") or {}).get("sha1"),
            "size": f.get("fileSize"),
        })

    todo = [f for f in files if not file_ok(f["dest"], f["sha1"], f["size"])]
    total = len(todo)
    say(f"需要下载 {total}/{len(files)} 个文件…")
    lock, done = Lock(), [0]

    def fetch(item):
        if cancelled():
            raise InterruptedError("已取消")
        download_file(item["urls"][0], item["dest"], sha1=item["sha1"],
                      timeout=60, retries=3, cancel=cancel, paused=paused,
                      fallback_url=item["urls"][1:] or None)
        with lock:
            done[0] += 1
            report(45 + int(45 * done[0] / max(total, 1)))
            if done[0] % 10 == 0 or done[0] == total:
                say(f"整合包文件下载中 {done[0]}/{total}")

    if todo:
        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            list(pool.map(fetch, todo))

    # ---- 4. overrides 解压（进入实例目录） ----
    if cancelled():
        raise InterruptedError("已取消")
    say("正在解压 overrides（配置/资源）…")
    count = 0
    with zipfile.ZipFile(pack_path) as z:
        for zi in z.infolist():
            for prefix in ("overrides/", "client-overrides/"):
                if not zi.filename.startswith(prefix):
                    continue
                rel = zi.filename[len(prefix):]
                parts = [p for p in rel.replace("\\", "/").split("/")
                         if p not in ("", ".", "..")]
                if not parts:
                    break
                dest = target.joinpath(*parts)
                if zi.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(z.read(zi.filename))
                    count += 1
                break
    report(100)
    say(f"整合包安装完成：{name} {ver} → 版本 {new_id}"
        f"（{len(files)} 个文件，{count} 个 override，加载器：{loader_note}）")
    return new_id
