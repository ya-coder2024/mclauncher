# -*- coding: utf-8 -*-
"""抓取指定版本的 json 并打印关键字段结构，用于编写启动器解析代码

用法: python scripts/inspect_version.py [版本id]
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

from core.version_manifest import fetch_manifest

MIRROR = "https://bmclapi2.bangbang93.com"
_OFFICIAL = (
    "https://piston-meta.mojang.com",
    "https://piston-data.mojang.com",
    "https://launchermeta.mojang.com",
)


def to_mirror(url):
    for h in _OFFICIAL:
        if url.startswith(h):
            return MIRROR + url[len(h):]
    return url


def main(vid):
    source, versions = fetch_manifest()
    print(f"清单来源: {source}, 版本数: {len(versions)}")
    target = next((v for v in versions if v["id"] == vid), None)
    if not target:
        print(f"清单中未找到 {vid}！前 20 个 id: {[v['id'] for v in versions[:20]]}")
        return
    print(f"找到 {vid}: type={target.get('type')} url={target.get('url')}")

    data = requests.get(to_mirror(target["url"]), timeout=15).json()

    out = Path(__file__).parent / f"_inspect_{vid}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完整 json 已存: {out}")

    print("\n== 顶层字段 ==")
    print(sorted(data.keys()))
    print("\n== javaVersion ==")
    print(data.get("javaVersion"))
    print("\n== mainClass ==")
    print(data.get("mainClass"))
    print("\n== assets / assetIndex ==")
    print("assets 名:", data.get("assets"))
    ai = data.get("assetIndex", {})
    print({k: ai.get(k) for k in ("id", "url", "sha1", "size", "totalSize")})
    print("\n== downloads.client ==")
    c = data.get("downloads", {}).get("client", {})
    print({k: c.get(k) for k in ("size", "sha1")})

    args = data.get("arguments")
    if args:
        jvm = args.get("jvm", [])
        game = args.get("game", [])
        print(f"\n== arguments 新格式: jvm {len(jvm)} 项 / game {len(game)} 项 ==")
        print("-- jvm 全部条目 --")
        for e in jvm:
            print(json.dumps(e, ensure_ascii=False)[:180])
        print("-- game 前 15 项 --")
        for e in game[:15]:
            print(json.dumps(e, ensure_ascii=False)[:120])
        dictify = lambda items: sum(1 for e in items if isinstance(e, dict))
        print(f"jvm 带规则条目: {dictify(jvm)}, game 带规则条目: {dictify(game)}")
    else:
        print("\n== 老格式 minecraftArguments ==")
        print(data.get("minecraftArguments"))

    libs = data.get("libraries", [])
    print(f"\n== libraries 共 {len(libs)} 个 ==")
    os_counter = Counter()
    for lib in libs:
        for r in lib.get("rules", []):
            os_counter[r.get("os", {}).get("name") or "*"] += 1
    print("rules os 统计:", dict(os_counter))
    natives = [l["name"] for l in libs
               if "natives-windows" in json.dumps(l.get("downloads", {}))]
    print(f"含 natives-windows 的库: {len(natives)}")
    for n in natives[:6]:
        print("  ", n)
    print("-- 第一个库完整结构 --")
    print(json.dumps(libs[0], ensure_ascii=False)[:500])
    if natives:
        print("-- 一个 natives 库完整结构 --")
        for l in libs:
            if l["name"] in natives:
                print(json.dumps(l, ensure_ascii=False)[:900])
                break

    log = data.get("logging")
    if log:
        f = log.get("client", {}).get("file", {})
        print("\n== logging.client.file ==")
        print({k: f.get(k) for k in ("id", "url", "sha1", "size")})


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "26.2")
