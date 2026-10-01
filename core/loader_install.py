# -*- coding: utf-8 -*-
"""一键安装模组加载器：Fabric / Quilt / Forge / NeoForge。

- Fabric、Quilt：Meta API 取 loader profile（inheritsFrom + 库 + KnotClient），
  与原版 json 合并为完整版本 json，现有 launch() 直接可用。
- Forge、NeoForge：BMCLAPI 查询版本 → 下载官方安装器 → 用 Java 静默执行
  （--installClient / --client），安装器自动生成版本 json 并下载所需库。
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import requests

from core.version_manifest import fetch_manifest
from core.java_finder import pick_java
from core.java_runtime import runtime_java, ensure_runtime
from core.downloader import download_file
from core.launcher import merge_libraries

TIMEOUT = 30
BMCLAPI = "https://bmclapi2.bangbang93.com"

# Meta 类加载器：(meta 根地址, api 版本)
_META_SOURCES = {
    "fabric": ("https://meta.fabricmc.net", "v2"),
    "quilt": ("https://meta.quiltmc.org", "v3"),
}

LOADER_LABELS = {
    "fabric": "Fabric",
    "quilt": "Quilt",
    "forge": "Forge",
    "neoforge": "NeoForge",
}


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


def installed_ids(game_dir):
    """本地已安装版本 id 列表"""
    vroot = Path(game_dir) / "versions"
    if not vroot.is_dir():
        return []
    return [d.name for d in vroot.iterdir()
            if (d / f"{d.name}.json").is_file()]


# ============================================================
# 原版 json
# ============================================================

def ensure_base_json(game_dir, mc_version, status_cb=None):
    """确保原版 json 存在，返回其内容（dict）。仅 json，不含游戏文件。"""
    vdir = Path(game_dir) / "versions" / mc_version
    jp = vdir / f"{mc_version}.json"
    if jp.is_file():
        return json.loads(jp.read_text(encoding="utf-8"))

    _, versions = fetch_manifest()
    v = next((v for v in versions if v["id"] == mc_version), None)
    if not v:
        raise LoaderError(f"版本清单中找不到 {mc_version}")
    data = _get_json(v["url"])
    vdir.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                  encoding="utf-8")
    return data


# ============================================================
# Fabric / Quilt（Meta profile 合并）
# ============================================================

def list_meta_loaders(kind, mc_version):
    """返回 [(版本号, 是否稳定)]，最新在前"""
    base, api = _META_SOURCES[kind]
    data = _get_json(f"{base}/{api}/versions/loader/{mc_version}")
    if not data:
        raise LoaderError(f"{LOADER_LABELS[kind]} 暂不支持游戏版本 {mc_version}")
    out = []
    for item in data:
        ld = item.get("loader", {})
        # fabric 用 stable；quilt loader 无 stable 字段（beta 版居多）
        stable = ld.get("stable", not ld.get("version", "").find("beta") >= 0)
        out.append((ld.get("version", ""), bool(stable)))
    return [(v, s) for v, s in out if v]


def _latest_stable(kind, mc_version):
    vs = list_meta_loaders(kind, mc_version)
    for v, stable in vs:
        if stable:
            return v
    return vs[0][0]


def _lib_name(lib):
    return lib.get("name", "")


def _merge_profile(base, loader_profile, new_id):
    """合并原版 json 与 loader profile，返回完整版本 json"""
    merged = dict(base)
    merged["id"] = new_id

    # 库：loader 与原版合并（同名库合并字段）
    merged["libraries"] = merge_libraries(loader_profile.get("libraries", []),
                                          base.get("libraries", []))

    if loader_profile.get("mainClass"):
        merged["mainClass"] = loader_profile["mainClass"]

    b_args = base.get("arguments", {})
    l_args = loader_profile.get("arguments", {})
    if b_args or l_args:
        merged["arguments"] = {
            "game": list(l_args.get("game", [])) + list(b_args.get("game", [])),
            "jvm": list(l_args.get("jvm", [])) + list(b_args.get("jvm", [])),
        }

    merged["type"] = "modified"
    return merged


def install_meta(kind, game_dir, mc_version, loader_version=None,
                 status_cb=None):
    """安装 Fabric/Quilt，返回新版本 id"""
    def say(m):
        if status_cb:
            status_cb(m)

    label = LOADER_LABELS[kind]
    if loader_version is None:
        say(f"正在查询 {mc_version} 的 {label} Loader…")
        loader_version = _latest_stable(kind, mc_version)

    new_id = f"{mc_version}-{label} {loader_version}"
    if new_id in installed_ids(game_dir):
        raise LoaderError(f"版本 {new_id} 已安装，无需重复安装")

    say(f"正在下载 {label} Loader {loader_version} 的版本信息…")
    base_url, api = _META_SOURCES[kind]
    profile = _get_json(
        f"{base_url}/{api}/versions/loader/{mc_version}/"
        f"{loader_version}/profile/json"
    )

    say(f"正在获取原版 {mc_version} 的版本信息…")
    base = ensure_base_json(game_dir, mc_version, status_cb)

    say("正在合并版本配置…")
    merged = _merge_profile(base, profile, new_id)

    vdir = Path(game_dir) / "versions" / new_id
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / f"{new_id}.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    say(f"安装完成：{new_id}")
    return new_id


# ============================================================
# Forge / NeoForge（官方安装器静默执行）
# ============================================================

def list_forge_loaders(mc_version):
    """返回 [(forge版本, branch)],推荐正式版在前（BMCLAPI 原顺序为旧→新，反转）"""
    data = _get_json(f"{BMCLAPI}/forge/minecraft/{mc_version}")
    if not data:
        raise LoaderError(f"Forge 暂不支持游戏版本 {mc_version}")
    out = []
    for item in reversed(data):
        ver = item.get("version")
        if not ver:
            continue
        files = item.get("files", [])
        if not any(f.get("category") == "installer" and f.get("format") == "jar"
                   for f in files):
            continue  # 没有安装器的极老版本跳过
        out.append((ver, item.get("branch")))
    if not out:
        raise LoaderError(f"{mc_version} 没有可用的 Forge 安装器")
    # 正式版（branch 为空）优先
    out.sort(key=lambda x: x[1] is not None)
    return out


def list_neoforge_loaders(mc_version):
    """返回 [(version, installer_path)]，新→旧"""
    data = _get_json(f"{BMCLAPI}/neoforge/list/{mc_version}")
    if not data:
        raise LoaderError(f"NeoForge 暂不支持游戏版本 {mc_version}")
    out = []
    for item in reversed(data):
        ip = item.get("installerPath")
        ver = item.get("version")
        if ip and ver:
            out.append((ver, ip))
    if not out:
        raise LoaderError(f"{mc_version} 没有可用的 NeoForge 安装器")
    return out


def _required_java_major(base_json):
    try:
        return int(base_json.get("javaVersion", {}).get("majorVersion", 0))
    except (TypeError, ValueError):
        return 0


def _resolve_java(game_dir, base_json, say):
    """找到与游戏版本匹配的 Java：官方 runtime > 精确版本的系统 Java >
    自动下载官方 runtime。返回 java.exe 路径（Path）"""
    jv_info = base_json.get("javaVersion", {})
    component = jv_info.get("component")
    need = _required_java_major(base_json) or 8

    # 1. 对应组件的官方 runtime（版本总是精确匹配）
    if component:
        exe = runtime_java(game_dir, component)
        if exe:
            return exe

    # 2. 系统 Java：要求主版本号精确匹配（Forge 安装器拒绝高版本 Java）
    p, major = pick_java(need_major=need)
    if p and major == need:
        return Path(p)

    # 3. 自动下载官方运行时
    if component:
        say(f"未检测到 Java {need}，正在自动下载官方运行时 {component}…")

        def rt_cb(done, total):
            if total and done % 15 == 0:
                say(f"运行时文件下载中 {done}/{total}")

        exe = ensure_runtime(game_dir, component, use_mirror=True,
                             progress_cb=rt_cb)
        return exe
    raise LoaderError(
        f"安装需要 Java {need}，未检测到；请先在设置中安装或配置 Java")


def _ensure_launcher_profiles(game_dir):
    """Forge 安装器要求 .minecraft 下存在 launcher_profiles.json（旧官方
    启动器配置），不存在则写入最小内容"""
    p = Path(game_dir) / "launcher_profiles.json"
    if not p.is_file():
        p.write_text('{"profiles":{},"settings":{},"version":3}',
                     encoding="utf-8")


def _ascii_target(game_dir):
    """Java 8 版 Forge 安装器无法处理中文路径。路径含非 ASCII 字符时，
    在系统临时目录建一个全 ASCII 的 junction 指向游戏目录。

    返回 (目标路径, junction路径或None)。junction 仅移除链接本身，
    不影响真实目录（用 os.rmdir，绝不能用 shutil.rmtree）。"""
    target = str(Path(game_dir).resolve())
    try:
        target.encode("ascii")
        return target, None
    except UnicodeEncodeError:
        pass

    import uuid
    link = os.path.join(tempfile.gettempdir(), "mcl_" + uuid.uuid4().hex[:10])
    ps = "New-Item -ItemType Junction -Path $env:TPLINK -Target $env:TPTARGET | Out-Null"
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            env={**os.environ, "TPLINK": link, "TPTARGET": target},
            capture_output=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        raise LoaderError(f"创建临时链接失败：{e}")
    if r.returncode != 0 or not os.path.isdir(link):
        raise LoaderError("创建临时链接失败，安装器无法处理中文游戏路径")
    return link, link


def _remove_ascii_target(link):
    if link:
        try:
            os.rmdir(link)
        except OSError:
            pass


def _run_installer(java_exe, installer, args, say):
    """静默执行安装器，实时转发输出。args 为参数列表。"""
    cmd = [str(java_exe), "-jar", str(installer)] + args
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=creationflags,
        )
    except OSError as e:
        raise LoaderError(f"无法启动 Java 安装器：{e}")

    for line in proc.stdout:
        s = line.strip()
        if s:
            say(s)
    proc.wait()
    if proc.returncode != 0:
        raise LoaderError(f"安装器异常退出（代码 {proc.returncode}），详见上方日志")


def install_forge(game_dir, mc_version, loader_version=None, status_cb=None):
    """安装 Forge，返回新版本 id"""
    def say(m):
        if status_cb:
            status_cb(m)

    say(f"正在获取原版 {mc_version} 的版本信息…")
    base_json = ensure_base_json(game_dir, mc_version, status_cb)

    if loader_version is None:
        say(f"正在查询 {mc_version} 的 Forge 版本…")
        loader_version = list_forge_loaders(mc_version)[0][0]

    new_id = f"{mc_version}-forge-{loader_version}"
    if new_id in installed_ids(game_dir):
        raise LoaderError(f"版本 {new_id} 已安装，无需重复安装")

    # 安装器下载多源：BMCLAPI maven 直链 → BMCLAPI download 端点 → Forge 官方 maven
    maven_rel = f"net/minecraftforge/forge/{mc_version}-{loader_version}"
    installer_name = f"forge-{mc_version}-{loader_version}-installer.jar"
    urls = [
        f"{BMCLAPI}/maven/{maven_rel}/{installer_name}",
        f"{BMCLAPI}/forge/download?mcversion={mc_version}"
        f"&version={loader_version}&category=installer&format=jar",
        f"https://files.minecraftforge.net/maven/{maven_rel}/{installer_name}",
    ]
    say(f"正在下载 Forge {loader_version} 安装器…")
    with tempfile.TemporaryDirectory(prefix="forge_inst_") as td:
        installer = Path(td) / "forge-installer.jar"
        try:
            download_file(urls[0], installer, retries=2, timeout=60,
                          fallback_url=urls[1:])
        except Exception as e:
            raise LoaderError(f"安装器下载失败：{e}")

        _ensure_launcher_profiles(game_dir)
        target, link = _ascii_target(game_dir)
        java_exe = _resolve_java(game_dir, base_json, say)
        say("正在静默安装（安装器需下载较多文件，请耐心等待）…")
        before = set(installed_ids(game_dir))
        try:
            _run_installer(java_exe, installer,
                           ["--installClient", target], say)
        finally:
            _remove_ascii_target(link)

    found = _find_new_version(game_dir, before, "forge")
    say(f"Forge 安装完成：{found}")
    return found


def install_neoforge(game_dir, mc_version, loader_version=None, status_cb=None):
    """安装 NeoForge，返回新版本 id"""
    def say(m):
        if status_cb:
            status_cb(m)

    say(f"正在获取原版 {mc_version} 的版本信息…")
    base_json = ensure_base_json(game_dir, mc_version, status_cb)

    entries = list_neoforge_loaders(mc_version)
    if loader_version is None:
        say(f"正在查询 {mc_version} 的 NeoForge 版本…")
        loader_version, installer_path = entries[0]
    else:
        hit = next((e for e in entries if e[0] == loader_version), None)
        if not hit:
            raise LoaderError(f"找不到 NeoForge 版本 {loader_version}")
        loader_version, installer_path = hit

    new_id = f"neoforge-{loader_version}"
    if new_id in installed_ids(game_dir):
        raise LoaderError(f"版本 {new_id} 已安装，无需重复安装")

    # 多源：BMCLAPI → NeoForge 官方 maven（installerPath 形如
    # /maven/net/neoforged/neoforge/x/y-installer.jar）
    rel = installerPath[len("/maven/"):] if installerPath.startswith("/maven/") else installerPath
    urls = [
        BMCLAPI + installer_path,
        f"https://maven.neoforged.net/releases/{rel}",
    ]
    say(f"正在下载 NeoForge {loader_version} 安装器…")
    with tempfile.TemporaryDirectory(prefix="neoforge_inst_") as td:
        installer = Path(td) / "neoforge-installer.jar"
        try:
            download_file(urls[0], installer, retries=2, timeout=60,
                          fallback_url=urls[1:])
        except Exception as e:
            raise LoaderError(f"安装器下载失败：{e}")

        target, link = _ascii_target(game_dir)
        java_exe = _resolve_java(game_dir, base_json, say)
        say("正在静默安装（安装器需下载较多文件，请耐心等待）…")
        before = set(installed_ids(game_dir))
        try:
            _run_installer(java_exe, installer, ["--client", target], say)
        finally:
            _remove_ascii_target(link)

    found = _find_new_version(game_dir, before, "neoforge")
    say(f"NeoForge 安装完成：{found}")
    return found


def _find_new_version(game_dir, before, keyword):
    """安装后在 versions 中找新增版本；找不到则取最近修改的含关键字版本"""
    after = installed_ids(game_dir)
    new = [v for v in after if v not in before]
    if len(new) == 1:
        return new[0]
    if new:
        return sorted(new, key=lambda v: (Path(game_dir) / "versions" / v
                                          / f"{v}.json").stat().st_mtime)[-1]
    vroot = Path(game_dir) / "versions"
    cands = [d for d in vroot.iterdir()
             if keyword in d.name.lower() and (d / f"{d.name}.json").is_file()]
    if cands:
        return sorted(cands, key=lambda d: (d / f"{d.name}.json").stat().st_mtime)[-1].name
    raise LoaderError("安装器已结束，但未在 versions 中找到新版本，可能安装失败")


# ============================================================
# 统一入口
# ============================================================

def list_loader_versions(kind, mc_version):
    """查询某加载器对某游戏版本的可用 loader 版本，返回 [版本号]"""
    if kind in _META_SOURCES:
        return [v for v, _ in list_meta_loaders(kind, mc_version)]
    if kind == "forge":
        return [v for v, _ in list_forge_loaders(mc_version)]
    if kind == "neoforge":
        return [v for v, _ in list_neoforge_loaders(mc_version)]
    raise LoaderError(f"未知加载器：{kind}")


def install_loader(kind, game_dir, mc_version, loader_version=None,
                   status_cb=None):
    """统一安装入口，返回新版本 id"""
    if kind in _META_SOURCES:
        return install_meta(kind, game_dir, mc_version, loader_version, status_cb)
    if kind == "forge":
        return install_forge(game_dir, mc_version, loader_version, status_cb)
    if kind == "neoforge":
        return install_neoforge(game_dir, mc_version, loader_version, status_cb)
    raise LoaderError(f"未知加载器：{kind}")


# -------- 向后兼容旧调用 --------
def list_fabric_loaders(mc_version):
    return list_meta_loaders("fabric", mc_version)


def install_fabric(game_dir, mc_version, loader_version=None, status_cb=None):
    return install_meta("fabric", game_dir, mc_version, loader_version, status_cb)
