# -*- coding: utf-8 -*-
"""打印本地版本 json 的精确结构（arguments / libraries 形态 / logging），供启动器编码参考

用法: python scripts/show_struct.py <版本id>
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_text(vid):
    p = ROOT / ".minecraft" / "versions" / vid / f"{vid}.json"
    if p.exists():
        return p.read_text(encoding="utf-8")
    p = ROOT / "scripts" / f"_inspect_{vid}.json"
    if p.exists():
        return p.read_text(encoding="utf-8")
    print(f"找不到 {vid} 的版本 json（.minecraft 与 scripts/_inspect_ 均无）")
    sys.exit(1)


def main(vid):
    data = json.loads(load_text(vid))
    print(f"===== {vid} =====")
    print("keys:", sorted(data.keys()))

    args = data.get("arguments")
    if args:
        print("\n----- arguments.jvm (完整) -----")
        print(json.dumps(args.get("jvm", []), ensure_ascii=False, indent=1))
        print("\n----- arguments.game (完整) -----")
        print(json.dumps(args.get("game", []), ensure_ascii=False, indent=1))
    else:
        print("\n----- minecraftArguments -----")
        print(data.get("minecraftArguments"))

    libs = data.get("libraries", [])
    shapes = {}
    for l in libs:
        shape = tuple(sorted(l.keys()))
        shapes[shape] = shapes.get(shape, 0) + 1
    print(f"\n----- libraries 形态统计 ({len(libs)} 个) -----")
    for s, n in shapes.items():
        print(n, "x", s)

    has_classifiers = [l["name"] for l in libs if "classifiers" in l.get("downloads", {})]
    print("含 classifiers 的库:", len(has_classifiers), has_classifiers[:5])
    natives_map = [l["name"] for l in libs if "natives" in l]
    print("含 natives 字段的库:", len(natives_map), natives_map[:5])
    win_classified = [l["name"] for l in libs if ":natives-windows" in l["name"]]
    print("名称含 :natives-windows 的库:", len(win_classified), win_classified[:8])

    for l in libs:
        if ":natives-windows" in l["name"]:
            print("\n----- 名称含 natives-windows 的示例 -----")
            print(json.dumps(l, ensure_ascii=False, indent=1))
            break
    for l in libs:
        if "classifiers" in l.get("downloads", {}):
            print("\n----- classifiers 形态示例 -----")
            print(json.dumps(l, ensure_ascii=False, indent=1)[:1500])
            break
    for l in libs:
        if "rules" in l and "downloads" not in l:
            print("\n----- 无 downloads 的库示例 -----")
            print(json.dumps(l, ensure_ascii=False, indent=1)[:800])
            break

    print("\n----- assetIndex -----")
    print(json.dumps(data.get("assetIndex", {}), ensure_ascii=False))
    print("assets:", data.get("assets"))
    print("\n----- javaVersion -----")
    print(json.dumps(data.get("javaVersion", {}), ensure_ascii=False))
    print("mainClass:", data.get("mainClass"))
    log = data.get("logging", {}).get("client", {})
    print("logging.client keys:", sorted(log.keys()))
    print("logging.client.file:", json.dumps(log.get("file", {}), ensure_ascii=False))
    print("\n----- downloads.client -----")
    print({k: data.get("downloads", {}).get("client", {}).get(k) for k in ("size", "sha1")})


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "26.2")
