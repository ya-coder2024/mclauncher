# -*- coding: utf-8 -*-
"""启动链路端到端冒烟测试（不依赖 Qt 事件循环，直接同步执行）

用法: python scripts/smoke_launch.py [版本id] [玩家名]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import GAME_DIR
from core.launcher import launch


def main():
    vid = sys.argv[1] if len(sys.argv) > 1 else "26.2"
    name = sys.argv[2] if len(sys.argv) > 2 else "Steve"
    print(f"游戏目录: {GAME_DIR}")
    print(f"目标版本: {vid}\n")

    proc = launch(
        GAME_DIR, vid,
        username=name,
        status_cb=lambda s: print(f"[*] {s}", flush=True),
        progress_cb=lambda p: print(f"\r    进度 {p:3d}%", end="", flush=True),
    )
    print(f"\n\n游戏进程已启动 PID={proc.pid}")
    print("若游戏窗口未出现，请查看错误:")
    log = Path(GAME_DIR) / "versions" / vid / "launcher-log.txt"
    if log.exists():
        print(f"日志文件: {log}")


if __name__ == "__main__":
    main()
