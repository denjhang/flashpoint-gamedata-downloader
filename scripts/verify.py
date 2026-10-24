#!/usr/bin/env python3
"""
校验已下载的 Flashpoint GameZip: 比对大小 + SHA-256。

用法:
    python verify.py <下载目录> <清单.tsv> [--workers 8]

输出:
    - 终端统计 (OK / 缺失 / 大小不符 / 哈希不符)
    - _verify_bad.json   坏件详情
    - _redownload.txt    可直接喂给 aria2c -i 的补下清单

注意: 约 0.2% 的条目在数据库里仍是 Playable, 但 CDN 上已无文件 (游戏下架),
      它们会被列为 "missing"。这是正常现象, 不是下载失败。
"""
import argparse
import csv
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor


def sha256_file(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest().upper()


def check_one(args):
    dest, row = args
    fn = row["filename"]
    path = os.path.join(dest, fn)
    if not os.path.exists(path):
        return ("missing", fn, row["url"])
    exp_size = int(row["size_bytes"])
    got_size = os.path.getsize(path)
    if exp_size and got_size != exp_size:
        return ("size", fn, f"{got_size} != {exp_size}")
    exp_sha = (row.get("sha256") or "").upper()
    if exp_sha:
        got_sha = sha256_file(path)
        if got_sha != exp_sha:
            return ("hash", fn, f"{got_sha[:16]}... != {exp_sha[:16]}...")
    return ("ok", fn, "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dest", help="下载目录")
    ap.add_argument("manifest", help="清单 tsv")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    with open(args.manifest, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    print(f"清单 {len(rows)} 条, 目录 {args.dest}")

    stats = {"ok": 0, "missing": 0, "size": 0, "hash": 0}
    bad = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (st, fn, info) in enumerate(ex.map(check_one, ((args.dest, r) for r in rows))):
            stats[st] += 1
            if st != "ok":
                bad.append({"status": st, "filename": fn, "info": info})
            if (i + 1) % 5000 == 0:
                print(f"  ...{i+1}  ok={stats['ok']} missing={stats['missing']} "
                      f"size={stats['size']} hash={stats['hash']}")

    total = len(rows)
    print("\n=== 结果 ===")
    for k in ("ok", "missing", "size", "hash"):
        pct = stats[k] * 100 / total if total else 0
        print(f"  {k:<8} {stats[k]:>8}  ({pct:5.1f}%)")

    bad_path = os.path.join(args.dest, "_verify_bad.json")
    with open(bad_path, "w", encoding="utf-8") as f:
        json.dump(bad, f, indent=1, ensure_ascii=False)

    urlmap = {r["filename"]: r["url"] for r in rows}
    rd_path = os.path.join(args.dest, "_redownload.txt")
    with open(rd_path, "w", encoding="utf-8") as f:
        for b in bad:
            if b["filename"] in urlmap:
                f.write(urlmap[b["filename"]] + "\n  out=" + b["filename"] + "\n")

    print(f"\n坏件 {len(bad)} 个:")
    print(f"  {bad_path}")
    print(f"  {rd_path}   <- 补下: aria2c -i {rd_path} -d {args.dest} -c")
    if stats["missing"]:
        print(f"\n提示: {stats['missing']} 个 missing 中大部分是 CDN 已下架条目 (正常现象)。")
    return 0 if (stats["size"] == 0 and stats["hash"] == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
