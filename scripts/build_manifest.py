#!/usr/bin/env python3
"""
生成 Flashpoint GameZip 的 URL 清单。

直链规则:
    https://download.flashpointarchive.org/gib-roms/Games/{gameId}-{timestamp_ms}.zip
    其中 timestamp_ms 来自 game_data.dateAdded (注意: 不是 game.date_added!)

用法:
    # 从本地数据库生成 (需先跑 fetch_db.py)
    python build_manifest.py --out manifest.tsv

    # 只要 Flash 平台
    python build_manifest.py --platform Flash --out flash.tsv

    # 多平台 + 只要街机库
    python build_manifest.py --platform Flash,Shockwave --library arcade --out sel.tsv

    # 只要大于 1GiB 的
    python build_manifest.py --min-size 1G --out big.tsv

    # 按体积分片 (用于两阶段下载)
    python build_manifest.py --platform HTML5 --split-by 100M --outdir .

    # 完全不用数据库, 直接走 API (慢, 但免下载 453MiB)
    python build_manifest.py --from-api --platform Flash --out flash.tsv
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

CDN_BASE = "https://download.flashpointarchive.org/gib-roms/Games/"
DB_URL = "https://download.unstable.life/archive/databases/14/flashpoint.sqlite"
API_BASE = "https://fpfss.flashpointarchive.org"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) flashpoint-gamedata-downloader"

COLUMNS = [
    "url", "filename", "game_id", "title", "library", "platform",
    "developer", "publisher", "status", "size_bytes", "sha256",
    "date_added", "archive_state", "source",
]


def parse_size(s):
    """'1G' -> 1073741824, '100M' -> 104857600, '1024' -> 1024"""
    if s is None:
        return None
    if isinstance(s, int):
        return s
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMGT]?)B?\s*", s, re.I)
    if not m:
        raise ValueError(f"无法解析大小: {s!r}")
    val = float(m.group(1))
    unit = m.group(2).upper()
    mult = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}[unit]
    return int(val * mult)


def gamezip_filename(game_id, date_added):
    """
    复刻 launcher 的 getGameDataFilename():
        const cleanDate = dateAdded.includes('T') ? dateAdded : `${dateAdded} +0000 UTC`;
        return `${gameId}-${new Date(cleanDate).getTime()}.zip`;
    """
    d = date_added
    if "T" not in d:
        d = d + " +0000 UTC"
    dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return f"{game_id}-{int(dt.timestamp() * 1000)}.zip"


def url_for(game_id, date_added):
    return CDN_BASE + gamezip_filename(game_id, date_added)


# ---------------------------------------------------------------- 数据源


def load_from_db(db_path):
    if not os.path.exists(db_path):
        sys.exit(f"数据库不存在: {db_path}\n先运行: python fetch_db.py")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("""
        SELECT gd.gameId, gd.dateAdded, gd.size, gd.sha256,
               g.title, g.library, g.platformName, g.developer, g.publisher,
               g.status, g.archiveState, g.source
        FROM game_data gd
        LEFT JOIN game g ON g.id = gd.gameId
    """)
    for row in cur.fetchall():
        yield row
    con.close()


def load_from_api(platform_filter=None, page_sleep=0.0):
    """走 fpfss API 分页拉取。每页 2500 条。"""
    after_id = ""
    seen = 0
    while True:
        url = (f"{API_BASE}/api/games?after=1970-01-01&before=2030-01-01"
               f"&broad=true&afterId={after_id}")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    data = json.loads(r.read().decode("utf-8"))
                break
            except Exception as e:
                if attempt == 4:
                    raise
                print(f"  重试 ({attempt+1}/5): {e}", file=sys.stderr)
                time.sleep(5)
        games = data.get("games") or []
        if not games:
            break
        gmap = {g["id"]: g for g in games}
        gd_list = data.get("game_data") or []
        if not gd_list:
            # 有些分页只回 games, 没有 game_data -> 该页无法推文件名, 跳过
            after_id = games[-1]["id"]
            if len(games) < 2500:
                break
            continue
        for gd in gd_list:
            g = gmap.get(gd["game_id"], {})
            if platform_filter and g.get("platform_name") not in platform_filter:
                continue
            seen += 1
            yield (
                gd["game_id"], gd["date_added"], gd.get("size", 0),
                gd.get("sha_256", ""), g.get("title", ""), g.get("library", ""),
                g.get("platform_name", ""), g.get("developer", ""),
                g.get("publisher", ""), g.get("status", ""),
                g.get("archive_state", ""), g.get("source", ""),
            )
        after_id = games[-1]["id"]
        print(f"  API: 累计 {seen} 条 (afterId={after_id[:8]}...)", file=sys.stderr)
        if len(games) < 2500:
            break
        if page_sleep:
            time.sleep(page_sleep)


# ---------------------------------------------------------------- 主流程


def build_rows(source, platforms=None, libraries=None, min_size=None,
               max_size=None, include_legacy=True):
    for (gid, date_added, size, sha, title, lib, plat, dev, pub,
         status, astate, src) in source:
        if platforms and (plat or "") not in platforms:
            continue
        if libraries and (lib or "") not in libraries:
            continue
        size = size or 0
        if min_size is not None and size < min_size:
            continue
        if max_size is not None and size > max_size:
            continue
        # archiveState=1 是 Legacy 格式, 素材不在 GameZip 里
        if not include_legacy and astate == 1:
            continue
        yield {
            "url": url_for(gid, date_added),
            "filename": gamezip_filename(gid, date_added),
            "game_id": gid,
            "title": title or "",
            "library": lib or "",
            "platform": plat or "",
            "developer": dev or "",
            "publisher": pub or "",
            "status": status or "",
            "size_bytes": size,
            "sha256": (sha or "").upper(),
            "date_added": date_added,
            "archive_state": astate,
            "source": src or "",
        }


def write_tsv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, delimiter="\t")
        w.writeheader()
        n = 0
        total = 0
        for r in rows:
            w.writerow(r)
            n += 1
            total += r["size_bytes"]
    return n, total


def write_aria(path, rows):
    """aria2c -i 输入格式"""
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(r["url"] + "\n  out=" + r["filename"] + "\n")


def write_urls(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(r["url"] + "\n")


def human(n):
    for u in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PiB"


def main():
    ap = argparse.ArgumentParser(
        description="生成 Flashpoint GameZip URL 清单",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--db", default="flashpoint.sqlite", help="元数据库路径 (默认 flashpoint.sqlite)")
    ap.add_argument("--from-api", action="store_true", help="改用 REST API 而非本地数据库")
    ap.add_argument("--platform", help="平台过滤, 逗号分隔, 如 Flash,Shockwave")
    ap.add_argument("--library", help="库过滤, 逗号分隔, 如 arcade,theatre")
    ap.add_argument("--min-size", help="最小体积, 如 1G")
    ap.add_argument("--max-size", help="最大体积")
    ap.add_argument("--exclude-legacy", action="store_true",
                    help="排除 archiveState=1 的 Legacy 条目 (其素材不在 GameZip 里)")
    ap.add_argument("--sort", choices=["none", "size-asc", "size-desc", "title"],
                    default="none", help="排序方式 (size-desc 用于大文件优先)")
    ap.add_argument("--split-by", help="按体积分片, 如 100M -> 产出 manifest_big.tsv / manifest_small.tsv")
    ap.add_argument("--outdir", default=".", help="分片输出目录")
    ap.add_argument("--out", default="manifest.tsv", help="输出 tsv 路径")
    ap.add_argument("--aria-out", help="额外输出 aria2c 输入清单")
    ap.add_argument("--urls-out", help="额外输出纯 URL 列表")
    ap.add_argument("--limit", type=int, help="只取前 N 条 (调试用)")
    args = ap.parse_args()

    platforms = set(p.strip() for p in args.platform.split(",")) if args.platform else None
    libraries = set(l.strip() for l in args.library.split(",")) if args.library else None
    min_size = parse_size(args.min_size)
    max_size = parse_size(args.max_size)

    print(">> 读取元数据 ...", file=sys.stderr)
    if args.from_api:
        source = load_from_api(platform_filter=platforms)
    else:
        source = load_from_db(args.db)

    rows = list(build_rows(
        source, platforms=platforms, libraries=libraries,
        min_size=min_size, max_size=max_size,
        include_legacy=not args.exclude_legacy,
    ))
    if args.limit:
        rows = rows[: args.limit]

    if args.sort == "size-asc":
        rows.sort(key=lambda r: r["size_bytes"])
    elif args.sort == "size-desc":
        rows.sort(key=lambda r: r["size_bytes"], reverse=True)
    elif args.sort == "title":
        rows.sort(key=lambda r: r["title"].lower())

    if args.split_by:
        thr = parse_size(args.split_by)
        big = [r for r in rows if r["size_bytes"] >= thr]
        small = [r for r in rows if r["size_bytes"] < thr]
        big.sort(key=lambda r: r["size_bytes"], reverse=True)
        small.sort(key=lambda r: r["size_bytes"], reverse=True)
        os.makedirs(args.outdir, exist_ok=True)
        for name, group in (("big", big), ("small", small)):
            p = os.path.join(args.outdir, f"manifest_{name}.tsv")
            n, t = write_tsv(p, group)
            write_aria(os.path.join(args.outdir, f"aria_{name}.txt"), group)
            print(f">> {p}: {n} 个, {human(t)}")
        return

    n, total = write_tsv(args.out, rows)
    print(f">> {args.out}: {n} 个, {human(total)}")

    if args.aria_out:
        write_aria(args.aria_out, rows)
        print(f">> {args.aria_out}")
    if args.urls_out:
        write_urls(args.urls_out, rows)
        print(f">> {args.urls_out}")


if __name__ == "__main__":
    main()
