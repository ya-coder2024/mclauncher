# -*- coding: utf-8 -*-
"""Modrinth 整合包（.mrpack）安装。

.mrpack 本质是 zip：
- modrinth.index.json：包元数据 + files 下载清单 + 锁定的依赖版本
- overrides/、client-overrides/：直接解压到游戏目录的配置/资源

安装流程：原版 json → 锁定版本的加载器 → files 并行下载 → overrides 解压。
"""

import json
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from urllib.parse import quote, unquote

import requests

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


# ==================== CurseForge 整合包（.zip + manifest.json） ====================

# CurseForge 下载方案（官方接口已被 Cloudflare 保护，无法直连）：
# 1. api.cfwidget.com/<projectID> → 项目文件列表（fileID → 文件名）
# 2. edge.forgecdn.net/files/{fid//1000}/{fid%1000}/{文件名} → CDN 直链
_UA = {"User-Agent": "MC-Launcher/1.0 (modpack installer)"}


class _CFIndex:
    """cfwidget 文件名索引：fileID → edge CDN 直链（结果缓存到磁盘，重装免解析）

    cfwidget 只保留各项目最近的一批文件，较老的 fileID 可能查不到
    （实测 221 个文件可解析 ~97%）。查不到的文件由调用方降级处理。
    """

    def __init__(self, pids, say, cache_file=None):
        self._map = {}          # fid → filename（仅未命中缓存的合并进来）
        self.titles = {}        # pid → 项目名（用于缺文件时的提示）
        self._cache_file = Path(cache_file) if cache_file else None
        cache = self._load_cache()
        todo = []
        for pid in sorted(set(pids)):
            cached = cache.get(str(pid))
            if cached:
                self._map.update({int(k): v for k, v in cached["files"].items()})
                self.titles[pid] = cached.get("title", f"项目 {pid}")
            else:
                todo.append(pid)
        failed = []
        for i, pid in enumerate(todo):
            if say:
                say(f"解析 CurseForge 项目 {i + 1}/{len(todo)}…")
            data = self._fetch_project(pid)
            if data is None:
                failed.append(pid)
            else:
                cache[str(pid)] = data
                self._map.update({int(k): v for k, v in data["files"].items()})
                self.titles[pid] = data.get("title", f"项目 {pid}")
                if len(cache) % 10 == 0:
                    self._save_cache(cache)
            time.sleep(0.3)  # 轻微限速，避免触发限流
        self._save_cache(cache)
        self.failed_pids = failed

    def _fetch_project(self, pid):
        """单个项目的 {title, files:{fid:name}}，失败返回 None"""
        for attempt in range(3):
            try:
                r = requests.get(f"https://api.cfwidget.com/{pid}",
                                 timeout=30, headers=_UA)
            except requests.RequestException:
                time.sleep(1.5)
                continue
            if r.status_code == 200:
                d = r.json()
                files = {f["id"]: f["name"]
                         for f in d.get("files", [])
                         if f.get("id") and f.get("name")}
                return {"title": d.get("title", f"项目 {pid}"), "files": files}
            if r.status_code == 429:  # 社区接口限流，排队重试
                time.sleep(2.5)
                continue
            break  # 404 等：项目不可查
        return None

    def _load_cache(self):
        if self._cache_file and self._cache_file.is_file():
            try:
                return json.loads(self._cache_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def _save_cache(self, cache):
        if not self._cache_file:
            return
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            self._cache_file.write_text(
                json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def url_of(self, fid):
        """fileID → edge 直链；查不到文件名返回 None"""
        name = self._map.get(fid)
        if not name:
            return None
        return (f"https://edge.forgecdn.net/files/{fid // 1000}/{fid % 1000}/"
                + quote(name))

    def label_of(self, pid, fid, fname):
        """缺文件时的可读标识：优先项目名，其次文件名"""
        title = self.titles.get(pid, f"项目 {pid}")
        if fname and not fname.startswith("curseforge-"):
            return f"{title}（{fname}）"
        return title


# modLoaders id 前缀 → 本启动器加载器类型
_CF_LOADER_PREFIX = {
    "forge-": "forge",
    "neoforge-": "neoforge",
    "fabric-": "fabric",
    "quilt-": "quilt",
}


def sniff_zip_type(pack_path):
    """识别 zip 类型：'mrpack' | 'curseforge' | 'mod' | 'unknown'"""
    try:
        with zipfile.ZipFile(pack_path) as z:
            names = z.namelist()
    except (zipfile.BadZipFile, OSError):
        return "unknown"
    if "modrinth.index.json" in names:
        return "mrpack"
    if "manifest.json" in names:
        return "curseforge"
    for n in names:
        if (n.endswith("fabric.mod.json") or n.endswith("quilt.mod.json")
                or n.endswith("META-INF/mods.toml") or n == "mcmod.info"
                or n.endswith("mods.toml")):
            return "mod"
    return "unknown"


def read_meta(pack_path):
    """读取整合包元数据（两种格式统一），返回确认框所需的 dict。

    结构：{name, version, mc, loader_label, files_count}
    非整合包 / 文件损坏时抛 ModpackError。
    """
    kind = sniff_zip_type(pack_path)
    if kind == "mod":
        raise ModpackError("这是单个模组文件，不是整合包。请到「模组」页拖入安装")
    if kind == "unknown":
        raise ModpackError("无法识别的压缩包：既不是 .mrpack，也不含 manifest.json")
    if kind == "mrpack":
        index = read_index(pack_path)
        deps = index.get("dependencies") or {}
        loader = next((f"{loader_install.LOADER_LABELS[k]} {deps[key]}"
                       for key, k in _DEP_TO_KIND.items() if deps.get(key)), "无（纯原版）")
        return {
            "name": index.get("name", "?"),
            "version": index.get("versionId", ""),
            "mc": deps.get("minecraft", "?"),
            "loader_label": loader,
            "files_count": len(index.get("files", [])),
        }
    manifest = read_cf_manifest(pack_path)
    mc_info = manifest.get("minecraft") or {}
    loader = "无（纯原版）"
    for ml in mc_info.get("modLoaders") or []:
        kind2, ver2 = _parse_cf_loader(ml.get("id", ""))
        if kind2:
            loader = f"{loader_install.LOADER_LABELS[kind2]} {ver2}"
            break
    return {
        "name": manifest.get("name", "?"),
        "version": manifest.get("version", ""),
        "mc": mc_info.get("version", "?"),
        "loader_label": loader,
        "files_count": len(manifest.get("files") or []),
    }


def read_cf_manifest(pack_path):
    """读取 CurseForge 整合包的 manifest.json，返回 dict"""
    try:
        with zipfile.ZipFile(pack_path) as z:
            return json.loads(z.read("manifest.json").decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
        raise ModpackError(f"整合包文件无效（不是合法的 CurseForge 整合包）：{e}")


def _parse_cf_loader(ml_id):
    """'forge-47.2.0' → ('forge', '47.2.0')；无法识别 → (None, None)"""
    for prefix, kind in _CF_LOADER_PREFIX.items():
        if ml_id.startswith(prefix):
            return kind, ml_id[len(prefix):]
    return None, None


def install_cf_zip(pack_path, game_dir, status_cb=None, progress_cb=None,
                   cancel=None, paused=None):
    """安装 CurseForge 整合包 zip 到 game_dir，返回实例版本 id。

    流程与 install_mrpack 一致：原版 json → 加载器 → 文件并行下载 → overrides 解压。
    CurseForge manifest 只有项目 ID，文件通过公开接口解析直链下载。
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

    manifest = read_cf_manifest(pack_path)
    name = manifest.get("name", "modpack")
    ver = manifest.get("version", "")
    mc_info = manifest.get("minecraft") or {}
    mc_version = mc_info.get("version")
    if not mc_version:
        raise ModpackError("整合包缺少 Minecraft 版本声明，无法安装")
    say(f"整合包：{name} {ver}（Minecraft {mc_version}）")
    report(5)

    # ---- 1. 原版 json ----
    if cancelled():
        raise InterruptedError("已取消")
    say(f"正在准备原版 {mc_version} 版本信息…")
    loader_install.ensure_base_json(game_dir, mc_version)
    report(15)

    # ---- 2. 加载器 ----
    loader_note = "无（纯原版）"
    new_id = mc_version
    for ml in mc_info.get("modLoaders") or []:
        kind, lv = _parse_cf_loader(ml.get("id", ""))
        if not kind:
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
        break
    report(45)

    # ---- 整合包实例目录：版本隔离 ----
    target = Path(game_dir) / "versions" / new_id
    from core.config import Settings
    settings = Settings(game_dir)
    settings.set_isolation_for(new_id, True)
    say(f"实例版本：{new_id}（已自动开启版本隔离，数据写入该版本目录）")

    # ---- 3. 文件并行下载（CurseForge：cfwidget 解析文件名 → edge CDN 直链） ----
    todo = []
    for f in manifest.get("files") or []:
        pid, fid = f.get("projectID"), f.get("fileID")
        if pid and fid:
            todo.append((pid, fid, bool(f.get("required", True))))
    total = len(todo)
    say(f"共 {total} 个文件，正在解析 CurseForge 下载地址…")
    cache_file = Path(game_dir) / "launcher-cache" / "cfwidget.json"
    index = _CFIndex([pid for pid, _, _ in todo], say, cache_file=cache_file)
    if index.failed_pids:
        say(f"提示：{len(index.failed_pids)} 个项目信息解析失败，"
            "其中必需文件会在下一步报错")
    say(f"开始下载 {total} 个文件…")
    report(45)
    lock, done = Lock(), [0]
    failed_required, failed_optional = [], []

    def fetch(item):
        pid, fid, required = item
        if cancelled():
            raise InterruptedError("已取消")
        fname = f"curseforge-{pid}-{fid}"
        try:
            url = index.url_of(fid)
            if not url:
                raise ModpackError("无法解析该文件的下载地址（cfwidget 无此文件）")
            fname = unquote(url.rsplit("/", 1)[-1])
            # CurseForge manifest 不含相对路径，其文件列表按约定全部为模组
            dest = target / "mods" / fname
            if not file_ok(dest):
                download_file(url, dest, timeout=60, retries=3,
                              cancel=cancel, paused=paused)
        except InterruptedError:
            raise
        except Exception as e:
            (failed_required if required else failed_optional).append(
                f"{index.label_of(pid, fid, fname)}: {e}")
        with lock:
            done[0] += 1
            report(45 + int(45 * done[0] / max(total, 1)))
            if done[0] % 5 == 0 or done[0] == total:
                say(f"整合包文件下载中 {done[0]}/{total}")

    if todo:
        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            list(pool.map(fetch, todo))

    # ---- 4. overrides 解压（即使部分文件下载失败也要执行，配置优先） ----
    if cancelled():
        raise InterruptedError("已取消")
    say("正在解压 overrides（配置/资源）…")
    override_dir = (manifest.get("overrides") or "overrides").strip("/") + "/"
    count = 0
    with zipfile.ZipFile(pack_path) as z:
        for zi in z.infolist():
            if not zi.filename.startswith(override_dir):
                continue
            rel = zi.filename[len(override_dir):]
            parts = [p for p in rel.replace("\\", "/").split("/")
                     if p not in ("", ".", "..")]
            if not parts:
                continue
            dest = target.joinpath(*parts)
            if zi.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(zi.filename))
                count += 1
    report(100)

    missing = failed_required + failed_optional
    if missing:
        say(f"警告：{len(missing)} 个整合包文件未能下载（cfwidget 未收录其旧版本，"
            "详见任务错误信息）。缺失的模组可在游戏报错后手动补装")
    warn = f"，{len(missing)} 个文件缺失" if missing else ""
    say(f"整合包安装完成：{name} {ver} → 版本 {new_id}"
        f"（{total - len(missing)}/{total} 个文件，{count} 个 override，"
        f"加载器：{loader_note}{warn}）")
    if missing:
        raise ModpackError(
            f"安装基本完成，但 {len(missing)} 个文件未能下载：\n"
            + "\n".join(missing[:6])
            + ("\n…" if len(missing) > 6 else "")
            + "\n\n已装好的部分可以启动游戏试用；缺失的模组按名字手动下载放"
            "入实例的 mods 目录即可。也可以稍后重新安装本整合包（已下载的"
            "文件会跳过）")
    return new_id
