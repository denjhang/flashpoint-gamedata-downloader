#!/usr/bin/env bash
# Flashpoint GameZip 并发下载器 (aria2c 封装)
#
# 用法:
#   bash download.sh <清单.tsv> <目标目录> [并发数] [每文件连接数]
#
# 例:
#   bash download.sh manifest_flash.tsv  /data/fp-flash  32 8    # Flash 类: 高并发
#   bash download.sh manifest_big.tsv    /data/fp-html5  10 16   # HTML5 大文件: 低并发多连接
#   bash download.sh manifest_small.tsv  /data/fp-html5  48 4    # HTML5 碎文件: 高并发
#
# 特性:
#   - 直连 CDN, 不走代理
#   - 断点续传 (中断后原样重跑即可, aria2 -c 自动跳过已完成)
#   - 跳过已存在的完整文件
#   - 单文件多连接 (由第 4 个参数控制)
#
# 依赖: aria2c  (https://github.com/aria2/aria2/releases)
#       Python 3 (仅用于把 tsv 转成 aria2 输入格式; 也可用 awk 版见下)

set -euo pipefail

MANIFEST="${1:?用法: bash download.sh <清单.tsv> <目标目录> [并发] [每文件连接数]}"
DEST="${2:?缺目标目录}"
JOBS="${3:-32}"
CONNS="${4:-8}"

ARIA="${ARIA2C:-aria2c}"
PY="${PYTHON:-python3}"
command -v "$ARIA" >/dev/null 2>&1 || { echo "找不到 aria2c, 请先安装或用 ARIA2C=/path/to/aria2c 指定"; exit 1; }

mkdir -p "$DEST"
LIST="$DEST/.aria_input.txt"

# 从 tsv 生成 aria2c 输入清单 (跳过表头)
"$PY" - "$MANIFEST" "$LIST" <<'PYEOF'
import csv, sys
man, out = sys.argv[1], sys.argv[2]
with open(man, encoding='utf-8') as f, open(out, 'w', encoding='utf-8') as o:
    r = csv.DictReader(f, delimiter='\t')
    n = 0
    for row in r:
        o.write(row['url'] + "\n  out=" + row['filename'] + "\n")
        n += 1
print(f"清单 {n} 条")
PYEOF

TOTAL=$(( $(wc -l < "$LIST") / 2 ))
echo ">> 目标: $DEST"
echo ">> 待下载 $TOTAL 个文件"
echo ">> 并发 $JOBS, 每文件 $CONNS 连接"
echo ">> 开始: $(date)"

"$ARIA" -i "$LIST" \
  -d "$DEST" \
  -j "$JOBS" \
  -x "$CONNS" -s "$CONNS" -k 1M \
  -c --file-allocation=none \
  --max-tries=10 --retry-wait=15 --timeout=60 --connect-timeout=30 \
  --auto-file-renaming=false --allow-overwrite=false \
  --console-log-level=warn --summary-interval=60 \
  --log-level=warn --log="$DEST/aria.log"

echo ">> 结束: $(date)"
echo ">> 已下载: $(ls -1 "$DEST" | wc -l) 个文件, $(du -sh "$DEST" | cut -f1)"
echo ">> 校验: python verify.py $DEST $MANIFEST"
