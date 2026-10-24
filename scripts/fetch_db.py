#!/usr/bin/env python3
"""
下载 Flashpoint 权威元数据库 (flashpoint.sqlite)。

这个 453 MiB 的 SQLite 库是全部 URL 清单的来源 —— 它含 game_data 表,
里面有每个 GameZip 的 gameId / dateAdded / sha256 / size。

用法:
    python fetch_db.py                     # 下载到 ./flashpoint.sqlite
    python fetch_db.py --out fp14.sqlite   # 指定路径
    python fetch_db.py --version 13        # 换版本 (默认 14)
"""
import argparse
import os
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) flashpoint-gamedata-downloader"
BASES = [
    "https://download.unstable.life/archive/databases",
    "https://download.flashpointarchive.org/archive/databases",
]


def human(n):
    for u in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PiB"


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        t0 = time.time()
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    pct = got * 100 / total
                    spd = got / max(time.time() - t0, 1e-6)
                    eta = (total - got) / spd if spd else 0
                    print(f"\r  {pct:5.1f}%  {human(got)}/{human(total)}  "
                          f"{human(spd)}/s  ETA {eta:4.0f}s", end="", file=sys.stderr)
        print(file=sys.stderr)
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="flashpoint.sqlite", help="输出路径")
    ap.add_argument("--version", default="14", help="数据库版本 (默认 14)")
    args = ap.parse_args()

    if os.path.exists(args.out):
        sz = os.path.getsize(args.out)
        print(f"已存在 {args.out} ({human(sz)}), 跳过下载。")
        print("如需重新下载请先删除该文件。")
        return

    last_err = None
    for base in BASES:
        url = f"{base}/{args.version}/flashpoint.sqlite"
        print(f">> 下载 {url}", file=sys.stderr)
        try:
            n = download(url, args.out)
            print(f">> 完成: {args.out} ({human(n)})")
            return
        except Exception as e:
            last_err = e
            print(f"   失败: {e}", file=sys.stderr)
            if os.path.exists(args.out):
                os.remove(args.out)
    sys.exit(f"所有镜像均失败: {last_err}")


if __name__ == "__main__":
    main()
