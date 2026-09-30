# -*- coding: utf-8 -*-
"""启动链路：校验/下载依赖 → 资源 → natives 解压 → 组装命令 → 拉起游戏"""

import hashlib
import json
import platform
import re
import subprocess
import uuid as uuidlib
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

import requests
from PyQt5.QtCore import QThread, pyqtSignal

from core.downloader import download_file, file_ok, mirror_url, requests_get
from core.java_finder import pick_java
from core.java_runtime import ensure_runtime, runtime_java

_WORKERS = 24


# ---------- 版本 json ----------

def load_version(game_dir, vid):
    p = Path(game_dir) / "versions" / vid / f"{vid}.json"
    return json.loads(p.read_text(encoding="utf-8"))


# ---------- 规则求值 ----------

def rules_allow(rules):
    """版本规则求值：最后一条匹配的规则生效；features 规则视为不匹配"""
    if not rules:
        return True
    machine = platform.machine()
    our_arch = "x86" if machine == "x86" else "x64"
    allowed = False
    for r in rules:
        os_rule = r.get("os") or {}
        if os_rule.get("name") and os_rule["name"] != "windows":
            continue
        if os_rule.get("arch") and os_rule["arch"] != our_arch:
            continue
        if os_rule.get("version") and not re.search(os_rule["version"], platform.version()):
            continue
        if r.get("features"):
            continue
        allowed = r.get("action") == "allow"
    return allowed


# ---------- 文件补全 ----------

def _fetch_missing(jobs, use_mirror, progress_cb, cancel):
    """并行下载缺失文件。jobs: [(dest, url, sha1, size), ...]"""
    todo = [j for j in jobs if not file_ok(j[0], j[2], j[3])]
    total = len(todo)
    if not total:
        return
    lock, done = Lock(), [0]

    def fetch(job):
        dest, url, sha1, _size = job[0], job[1], job[2], job[3]
        fb = job[4] if len(job) > 4 else None
        m_url = mirror_url(url) if use_mirror else url
        download_file(m_url, dest, sha1=sha1, timeout=30, cancel=cancel,
                      fallback_url=fb if use_mirror else None)
        with lock:
            done[0] += 1
            if progress_cb:
                progress_cb(done[0], total)

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        list(pool.map(fetch, todo))


def _maven_artifact(name):
    """从 Maven 坐标 name 构造 (相对路径, 文件名)。

    name 格式：groupId:artifactId:version[:classifier]
    """
    parts = name.split(":")
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) > 3 else None
    gpath = group.replace(".", "/")
    fname = f"{artifact}-{version}"
    if classifier:
        fname += f"-{classifier}"
    fname += ".jar"
    rel = f"{gpath}/{artifact}/{version}/{fname}"
    return rel, fname


def ensure_libraries(data, game_dir, use_mirror=True, progress_cb=None, cancel=None):
    """下载缺失库文件，返回 (classpath 列表, natives jar 列表)"""
    lib_root = Path(game_dir) / "libraries"
    classpath, natives, jobs = [], [], []

    for lib in data.get("libraries", []):
        if not rules_allow(lib.get("rules")):
            continue
        name = lib.get("name", "")
        d = lib.get("downloads") or {}
        art = d.get("artifact")
        if art:
            dest = lib_root / art["path"]
            classpath.append(str(dest))
            jobs.append((dest, art["url"], art.get("sha1"), art.get("size")))
        else:
            # 无 downloads 字段（如 fabric-loader、asm 等 Maven 库）：从坐标构造多源回退
            rel, _ = _maven_artifact(name)
            dest = lib_root / rel
            sources = [
                f"https://bmclapi2.bangbang93.com/maven/{rel}",
                f"https://maven.fabricmc.net/{rel}",
                f"https://repo1.maven.org/maven2/{rel}",
            ]
            classpath.append(str(dest))
            jobs.append((dest, sources[0], None, None, sources[1:]))
        # 老格式：natives 映射 + classifiers
        nat_name = (lib.get("natives") or {}).get("windows")
        if nat_name:
            cj = d.get("classifiers", {}).get(nat_name)
            if cj:
                dest = lib_root / cj["path"]
                natives.append(dest)
                jobs.append((dest, cj["url"], cj.get("sha1"), cj.get("size")))
        elif (art or not d) and ":natives-windows" in name:
            # 新格式（26.x）：分类器直接在库名里，natives jar 本身就是 artifact
            if art:
                natives.append(lib_root / art["path"])
            else:
                rel, _ = _maven_artifact(name)
                natives.append(lib_root / rel)

    _fetch_missing(jobs, use_mirror, progress_cb, cancel)
    return classpath, natives


def ensure_assets(data, game_dir, use_mirror=True, progress_cb=None, cancel=None):
    """下载资源索引与缺失的资源文件"""
    ai = data["assetIndex"]
    root = Path(game_dir) / "assets"
    idx_path = root / "indexes" / f"{ai['id']}.json"
    if not file_ok(idx_path, ai.get("sha1"), ai.get("size")):
        m_url = mirror_url(ai["url"]) if use_mirror else ai["url"]
        download_file(m_url, idx_path, sha1=ai.get("sha1"), timeout=120, cancel=cancel,
                      fallback_url=ai["url"] if use_mirror else None)

    objects = json.loads(idx_path.read_text(encoding="utf-8")).get("objects", {})
    jobs = []
    for o in objects.values():
        h = o["hash"]
        dest = root / "objects" / h[:2] / h
        if not file_ok(dest, h, o.get("size")):
            jobs.append((dest, f"https://resources.download.minecraft.net/{h[:2]}/{h}", h, o.get("size")))
    # 资源对象走官方 CDN（BMCLAPI 资源节点限速严重，官方并发吞吐更高）
    _fetch_missing(jobs, False, progress_cb, cancel)


def ensure_client(data, game_dir, vid, use_mirror=True, cancel=None):
    """确保 client.jar 存在且完整"""
    client = data.get("downloads", {}).get("client", {})
    dest = Path(game_dir) / "versions" / vid / f"{vid}.jar"
    if client and not file_ok(dest, client.get("sha1"), client.get("size")):
        m_url = mirror_url(client["url"]) if use_mirror else client["url"]
        download_file(m_url, dest, sha1=client.get("sha1"), timeout=120, cancel=cancel,
                      fallback_url=client["url"] if use_mirror else None)
    return dest


def scan_mods(game_dir):
    """扫描 .minecraft/mods 目录，返回模组信息列表。

    每个元素：{"name": 模组名, "version": 版本, "file": 文件名}
    优先解析 fabric.mod.json（Fabric），其次 mcmod.info（旧 Forge），
    再其次 META-INF/mods.toml（新 Forge）；解析不到则用文件名。
    """
    mods_dir = Path(game_dir) / "mods"
    result = []
    if not mods_dir.is_dir():
        return result
    for jar in sorted(mods_dir.glob("*.jar")):
        info = {"name": jar.stem, "version": "?", "file": jar.name}
        try:
            with zipfile.ZipFile(jar) as z:
                names = z.namelist()
                if "fabric.mod.json" in names:
                    try:
                        m = json.loads(z.read("fabric.mod.json").decode("utf-8"))
                        info["name"] = m.get("name") or info["name"]
                        info["version"] = m.get("version") or "?"
                    except Exception:
                        pass
                elif "mcmod.info" in names:
                    try:
                        raw = z.read("mcmod.info").decode("utf-8").strip()
                        if raw.startswith("["):
                            m = json.loads(raw)[0]
                        else:
                            m = json.loads(raw)
                        info["name"] = m.get("name") or info["name"]
                        info["version"] = m.get("version") or "?"
                    except Exception:
                        pass
                else:
                    for n in names:
                        if n.endswith("mods.toml"):
                            try:
                                txt = z.read(n).decode("utf-8")
                                for line in txt.splitlines():
                                    if line.strip().startswith('modId=') or line.strip().startswith('modId ='):
                                        info["name"] = line.split('=', 1)[1].strip().strip('"')
                                    elif line.strip().startswith('version=') or line.strip().startswith('version ='):
                                        info["version"] = line.split('=', 1)[1].strip().strip('"')
                            except Exception:
                                pass
                            break
        except Exception:
            pass  # 损坏的 jar 直接用文件名
        result.append(info)
    return result


def ensure_mods_dir(game_dir):
    """确保 .minecraft/mods 目录存在"""
    (Path(game_dir) / "mods").mkdir(parents=True, exist_ok=True)


def extract_natives(natives_jars, natives_dir):
    """解压 natives jar：仅当前架构 DLL，扁平化到 natives/ 与 natives/java/。

    现代 LWJGL natives jar 内结构为 windows/<arch>/org/lwjgl/<module>/<dll>，
    而 java.library.path 指向 ${natives}/java，需扁平化使 System.loadLibrary 可直接找到。
    """
    import shutil
    natives_dir = Path(natives_dir)
    targets = [natives_dir, natives_dir / "java"]
    for t in targets:
        if t.exists():
            shutil.rmtree(t)
        t.mkdir(parents=True, exist_ok=True)

    # 当前架构前缀，如 windows/x64/
    m = platform.machine()
    arch = {"AMD64": "x64", "ARM64": "arm64", "x86": "x86"}.get(m, "x64")
    plat_prefix = f"windows/{arch}/"

    for jar in natives_jars:
        with zipfile.ZipFile(jar) as z:
            for name in z.namelist():
                if name.startswith("META-INF") or name.endswith("/"):
                    continue
                # 只取当前架构的文件，或根目录级文件（如 jtracy-jni-windows.dll）
                if name.startswith(plat_prefix):
                    inner = name[len(plat_prefix):]
                    target_name = Path(inner).name  # org/lwjgl/glfw.dll -> glfw.dll
                elif "/" not in name:
                    target_name = name
                else:
                    continue  # 跳过其他架构
                data = z.read(name)
                for t in targets:
                    (t / target_name).write_bytes(data)


# ---------- 离线账号 ----------

def offline_uuid(name):
    """离线模式 UUID：MD5("OfflinePlayer:" + name)，v3 格式"""
    b = bytearray(hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest())
    b[6] = (b[6] & 0x0F) | 0x30
    b[8] = (b[8] & 0x3F) | 0x80
    return str(uuidlib.UUID(bytes=bytes(b)))


# ---------- 命令组装 ----------

def build_command(data, game_dir, vid, java_exe, classpath, account=None, memory="2G"):
    """组装启动命令。account：来自 core.auth 的账号字典。"""
    account = account or {"type": "offline", "name": "Player",
                          "uuid": offline_uuid("Player"), "access_token": "0"}
    username = account["name"]
    player_uuid = account["uuid"]
    access_token = account["access_token"]
    # 现代版本统一用 msa；离线保持 legacy
    user_type = "legacy" if account["type"] == "offline" else "msa"

    natives_dir = Path(game_dir) / "versions" / vid / "natives"
    subs = {
        "auth_player_name": username,
        "auth_uuid": player_uuid,
        "auth_access_token": access_token,
        "auth_xuid": "0",
        "auth_session": f"token:{access_token}:{player_uuid}",
        "clientid": "0",
        "user_type": user_type,
        "user_properties": "{}",
        "version_name": vid,
        "version_type": data.get("type", "release"),
        "game_directory": str(game_dir),
        "launcher_name": "mclauncher",
        "launcher_version": "0.1",
        "assets_root": str(Path(game_dir) / "assets"),
        "assets_index_name": str(data.get("assets", "legacy")),
        "game_assets": str(Path(game_dir) / "assets" / "virtual" / "legacy"),
        "classpath": ";".join(classpath),
        "classpath_separator": ";",
        "library_directory": str(Path(game_dir) / "libraries"),
        "natives_directory": str(natives_dir),
        "path": "",
        "resolution_width": "854",
        "resolution_height": "480",
        "quickPlayPath": "",
        "quickPlaySingleplayer": "",
        "quickPlayMultiplayer": "",
        "quickPlayRealms": "",
    }

    def fill(s):
        for k, v in subs.items():
            s = s.replace("${" + k + "}", v)
        return s

    cmd = [java_exe, f"-Xmx{memory}", f"-Xms{memory}"]
    args = data.get("arguments")

    def extend(entries):
        for e in entries:
            if isinstance(e, dict):
                if not rules_allow(e.get("rules")):
                    continue
                v = e.get("value")
                vals = v if isinstance(v, list) else [v]
            else:
                vals = [e]
            cmd.extend(fill(s) for s in vals)

    if args:
        extend(args.get("jvm", []))
    else:
        cmd += ["-cp", subs["classpath"]]
    cmd.append(data["mainClass"])
    if args:
        extend(args.get("game", []))
    else:
        cmd += [fill(t) for t in data.get("minecraftArguments", "").split()]
    return cmd


# ---------- 一键启动 ----------

def launch(game_dir, vid, account=None, use_mirror=True, java_path=None,
           memory="2G", status_cb=None, progress_cb=None, cancel=None):
    """同步执行启动全流程，返回 Popen 进程对象。

    account：core.auth 的账号字典；为空时使用默认离线账号。
    progress_cb(percent)：0-100 整体进度
    """
    game_dir = Path(game_dir)
    vdir = game_dir / "versions" / vid

    def say(msg):
        if status_cb:
            status_cb(msg)

    def report(lo, hi):
        def cb(done, total):
            if total and progress_cb:
                progress_cb(int(lo + (hi - lo) * done / total))
        return cb

    # 账号：默认离线；正版/外置在此自动刷新令牌
    from core import auth as auth_mod
    if account is None:
        account = auth_mod.offline_login("Player")
    say(f"账号：{account['name']}（"
        + {"offline": "离线", "microsoft": "正版", "yggdrasil": "外置"}.get(account["type"], account["type"])
        + "）")
    if account["type"] != "offline":
        account = auth_mod.prepare_account(account)

    # 版本 json 缺失时自动从清单获取
    json_path = vdir / f"{vid}.json"
    if not json_path.is_file():
        say(f"本地缺少 {vid}，正在获取版本信息…")
        from core.version_manifest import fetch_manifest
        _, versions = fetch_manifest()
        v = next((v for v in versions if v["id"] == vid), None)
        if not v:
            raise RuntimeError(f"版本清单中找不到 {vid}")
        r = requests_get(mirror_url(v["url"]) if use_mirror else v["url"], timeout=30, retries=3)
        r.raise_for_status()
        vdir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(r.text, encoding="utf-8")

    data = json.loads(json_path.read_text(encoding="utf-8"))

    say("正在校验客户端文件…")
    client_jar = ensure_client(data, game_dir, vid, use_mirror, cancel)

    # Java：指定路径 > 本地运行时 > 系统扫描 > 官方运行时自动下载
    need = data.get("javaVersion", {}).get("majorVersion")
    component = data.get("javaVersion", {}).get("component")
    java_exe = java_path
    if not java_exe and component:
        exe = runtime_java(game_dir, component)
        if exe:
            java_exe = exe
    if not java_exe:
        say(f"正在检测系统 Java（需要 {need or 8}+）…")
        java_exe, ver = pick_java(need_major=need)
        if java_exe:
            say(f"使用 Java {ver}：{java_exe}")
    if not java_exe:
        if not component:
            raise RuntimeError("未检测到 Java，请先安装或设置 Java 路径")
        say(f"未找到可用 Java，正在下载官方运行时 {component}…")
        java_exe = ensure_runtime(game_dir, component, use_mirror,
                                  progress_cb=report(2, 28), cancel=cancel)

    say("正在校验依赖库…")
    cp, natives = ensure_libraries(data, game_dir, use_mirror, report(30, 55), cancel)
    cp.append(str(client_jar))  # client.jar 必须在 classpath 上（含主类）

    say("正在校验资源文件…")
    ensure_assets(data, game_dir, use_mirror, report(55, 95), cancel)

    say("正在解压本地库…")
    extract_natives(natives, vdir / "natives")

    ensure_mods_dir(game_dir)  # 确保 mods 目录存在，供 Fabric/Forge 加载器扫描

    cmd = build_command(data, game_dir, vid, java_exe, cp, account, memory)
    say("正在启动游戏…")
    log = open(vdir / "launcher-log.txt", "ab")
    proc = subprocess.Popen(cmd, cwd=str(game_dir), stdout=log, stderr=subprocess.STDOUT)
    say(f"游戏已启动（PID {proc.pid}），日志：versions/{vid}/launcher-log.txt")
    return proc


class LaunchWorker(QThread):
    """后台执行 launch()，向 UI 发信号"""

    status = pyqtSignal(str)
    progress = pyqtSignal(int)   # 0-100
    launched = pyqtSignal(int)   # 游戏进程 PID
    failed = pyqtSignal(str)

    def __init__(self, game_dir, vid, account=None, use_mirror=True,
                 java_path=None, memory="2G"):
        super().__init__()
        self.game_dir = game_dir
        self.vid = vid
        self.account = account
        self.use_mirror = use_mirror
        self.java_path = java_path
        self.memory = memory
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            proc = launch(
                self.game_dir, self.vid,
                account=self.account, use_mirror=self.use_mirror,
                java_path=self.java_path, memory=self.memory,
                status_cb=self.status.emit, progress_cb=self.progress.emit,
                cancel=lambda: self._stop,
            )
        except InterruptedError:
            self.status.emit("已取消")
        except Exception as e:
            self.failed.emit(str(e))
        else:
            self.launched.emit(proc.pid)
