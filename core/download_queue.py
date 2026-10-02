# -*- coding: utf-8 -*-
"""下载任务队列：统一管理版本下载/整合包安装任务，支持排队、暂停、继续、取消、速度显示"""

import json
import time
import uuid
from pathlib import Path

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from core.config import GAME_DIR
from core.downloader import download_file, mirror_url, requests_get
from core import mod_repo, modpack


class TaskState:
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


STATE_LABELS = {
    TaskState.QUEUED: "排队中",
    TaskState.RUNNING: "下载中",
    TaskState.PAUSED: "已暂停",
    TaskState.DONE: "已完成",
    TaskState.FAILED: "失败",
    TaskState.CANCELED: "已取消",
}

KIND_LABELS = {
    "version": "游戏版本",
    "pack": "整合包",
}


class DownloadTask(QObject):
    """单个下载任务。子类实现 _do_run()"""

    updated = pyqtSignal()    # 进度/状态/速度变化
    finished = pyqtSignal()   # 进入终态（done/failed/canceled）

    def __init__(self, kind, name):
        super().__init__()
        self.id = uuid.uuid4().hex[:8]
        self.kind = kind
        self.name = name
        self.state = TaskState.QUEUED
        self.progress = 0          # 0-100
        self.speed = 0.0           # 字节/秒
        self.error = ""
        self._paused = False
        self._canceled = False
        self._last_bytes = 0
        self._last_time = 0.0

    # ---------- 控制 ----------
    def pause(self):
        if self.state == TaskState.RUNNING:
            self._paused = True
            self.state = TaskState.PAUSED
            self.speed = 0.0
            self.updated.emit()

    def resume(self):
        if self.state == TaskState.PAUSED:
            self._paused = False
            self.state = TaskState.RUNNING
            self._last_time = time.monotonic()
            self.updated.emit()

    def cancel(self):
        self._canceled = True
        self._paused = False
        if self.state == TaskState.QUEUED:
            self.state = TaskState.CANCELED
            self.updated.emit()
            self.finished.emit()

    @property
    def is_terminal(self):
        return self.state in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELED)

    # ---------- 内部 ----------
    def _is_paused(self):
        return self._paused

    def _is_canceled(self):
        return self._canceled

    def _on_bytes(self, done, total):
        """progress_cb：累计字节 → 百分比 + 平滑速度"""
        if total:
            self.progress = int(done / total * 100)
        now = time.monotonic()
        dt = now - self._last_time
        if dt >= 0.5:
            self.speed = max(0.0, (done - self._last_bytes) / dt)
            self._last_bytes = done
            self._last_time = now
        self.updated.emit()

    def _mark(self, state, error=""):
        self.state = state
        self.error = error
        self.updated.emit()
        self.finished.emit()

    def run(self):
        if self._canceled:
            self._mark(TaskState.CANCELED)
            return
        self.state = TaskState.RUNNING
        self._last_time = time.monotonic()
        self.updated.emit()
        try:
            self._do_run()
            if self._canceled:
                self._mark(TaskState.CANCELED)
            else:
                self._mark(TaskState.DONE)
        except InterruptedError:
            self._mark(TaskState.CANCELED)
        except Exception as e:
            self._mark(TaskState.FAILED, str(e))

    def _do_run(self):
        raise NotImplementedError

    def speed_text(self):
        if self.speed >= 1024 * 1024:
            return f"{self.speed / 1024 / 1024:.1f} MB/s"
        if self.speed >= 1024:
            return f"{self.speed / 1024:.0f} KB/s"
        return f"{self.speed:.0f} B/s"


class VersionDownloadTask(DownloadTask):
    """下载游戏版本 json + client.jar"""

    def __init__(self, version_id, version_url):
        super().__init__("version", version_id)
        self.version_id = version_id
        self.version_url = version_url

    def _do_run(self):
        vid = self.version_id
        vdir = Path(GAME_DIR) / "versions" / vid
        vdir.mkdir(parents=True, exist_ok=True)

        # json
        r = requests_get(mirror_url(self.version_url), timeout=30, retries=3)
        r.raise_for_status()
        (vdir / f"{vid}.json").write_text(r.text, encoding="utf-8")
        data = json.loads(r.text)
        if self._canceled:
            raise InterruptedError("已取消")

        # client.jar
        client = data.get("downloads", {}).get("client", {})
        url = client.get("url")
        if not url:
            raise RuntimeError("版本信息中缺少客户端下载地址")
        download_file(mirror_url(url), vdir / f"{vid}.jar",
                      sha1=client.get("sha1"),
                      progress_cb=self._on_bytes,
                      paused=self._is_paused, cancel=self._is_canceled,
                      fallback_url=url)


class PackInstallTask(DownloadTask):
    """下载并安装 Modrinth 整合包。version 为空时自动选最新正式版"""

    def __init__(self, project, version=None):
        name = project["title"]
        if version:
            name += f" {version.get('version_number', '')}"
        super().__init__("pack", name)
        self.project = project
        self.version = version
        self.instance = None

    def _do_run(self):
        import tempfile
        # 选版本：未指定时优先最新正式版
        version = self.version
        if version is None:
            versions = mod_repo.list_versions(self.project["project_id"])
            if not versions:
                raise RuntimeError("该整合包没有可用版本")
            version = next((v for v in versions
                            if v.get("version_type") == "release"), versions[0])
        # 下载 mrpack
        mr = next((f for f in version.get("files", [])
                   if f.get("filename", "").endswith(".mrpack")), None)
        if not mr:
            raise RuntimeError("该版本没有 .mrpack 文件")
        pack_path = Path(tempfile.mkdtemp(prefix="mrpack_")) / mr["filename"]
        download_file(mr["url"], pack_path,
                      sha1=(mr.get("hashes") or {}).get("sha1"),
                      progress_cb=self._on_bytes,
                      paused=self._is_paused, cancel=self._is_canceled)
        if self._canceled:
            raise InterruptedError("已取消")

        # 安装（文件下载阶段同样支持暂停/取消）
        self._status = "安装中"
        self.instance = modpack.install_mrpack(
            pack_path, GAME_DIR,
            progress_cb=lambda p: (setattr(self, "progress", p), self.updated.emit()),
            cancel=self._is_canceled,
            paused=self._is_paused,
        )


class _QueueWorker(QThread):
    """顺序执行队列中的任务（一次一个，避免抢带宽）"""

    def __init__(self, queue):
        super().__init__()
        self._queue = queue

    def run(self):
        while True:
            task = next((t for t in self._queue.tasks
                         if t.state == TaskState.QUEUED), None)
            if task is None:
                time.sleep(0.3)
                continue
            task.run()


class DownloadQueue(QObject):
    """全局单例下载队列"""

    tasks_changed = pyqtSignal()   # 任务增删
    any_updated = pyqtSignal()     # 任一任务进度/状态变化

    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = DownloadQueue()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.tasks = []
        self._worker = _QueueWorker(self)
        self._worker.start()

    def add(self, task):
        self.tasks.append(task)
        task.updated.connect(self.any_updated)
        task.finished.connect(self.any_updated)
        self.tasks_changed.emit()
        return task

    def remove(self, task_id):
        t = next((x for x in self.tasks if x.id == task_id), None)
        if t is None:
            return
        if not t.is_terminal:
            t.cancel()
        self.tasks.remove(t)
        self.tasks_changed.emit()

    def clear_finished(self):
        self.tasks = [t for t in self.tasks if not t.is_terminal]
        self.tasks_changed.emit()

    def active_count(self):
        return sum(1 for t in self.tasks
                   if t.state in (TaskState.QUEUED, TaskState.RUNNING, TaskState.PAUSED))
