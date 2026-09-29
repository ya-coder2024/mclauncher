# -*- coding: utf-8 -*-
"""端到端冒烟测试：版本清单 → 下载 1.16.5（json + jar + SHA1 校验）

用法：python scripts/smoke_download.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt5.QtCore import QCoreApplication

from core.config import GAME_DIR
from core.version_manifest import fetch_manifest
from core.download_manager import DownloadManager


def main():
    app = QCoreApplication([])

    src, versions = fetch_manifest()
    print(f"[1/2] 清单 OK：来源 {src}，共 {len(versions)} 个版本")

    v = next(x for x in versions if x["id"] == "1.16.5")
    print(f"[2/2] 下载 {v['id']} …")

    m = DownloadManager(v["id"], v["url"], GAME_DIR)
    m.status.connect(lambda s: print("  状态:", s))
    last = []

    def on_progress(p):
        if not last or p - last[0] >= 10:
            last.clear()
            last.append(p)
            print(f"  进度: {p}%")

    m.progress.connect(on_progress)
    m.failed.connect(lambda e: (print("  失败:", e), sys.exit(1)))
    m.finished_ok.connect(lambda vid: None)
    m.run()  # 测试直接同步执行；GUI 里用 start()

    vdir = GAME_DIR / "versions" / v["id"]
    files = sorted(p.name for p in vdir.iterdir())
    sizes = {p.name: f"{p.stat().st_size / 1048576:.1f} MB" for p in vdir.iterdir()}
    print("完成。产物:", files, sizes)
    print("冒烟测试通过")


if __name__ == "__main__":
    main()
