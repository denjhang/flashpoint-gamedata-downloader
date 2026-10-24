# Flashpoint GameData Downloader

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**直接下载 Flashpoint Archive 的全部原始游戏素材（SWF / DCR / HTML5 / Unity …），无需安装 Flashpoint 客户端。**

本项目通过逆向 Flashpoint 官方安装器与启动器源码，还原出 GameZip 直链的**确切规则**，并提供全量清单生成 + 并发下载 + SHA-256 校验的完整工具链。

> 本项目只做「地址推导 + 下载调度」，**不托管、不分发任何游戏内容**。所有文件均来自 Flashpoint Archive 的公开 CDN。

---

## 目录

- [核心结论：直链规则](#核心结论直链规则)
- [这个项目解决什么问题](#这个项目解决什么问题)
- [快速开始](#快速开始)
- [数据来源与规模](#数据来源与规模)
- [按平台/库筛选](#按平台库筛选)
- [下载策略（重要）](#下载策略重要)
- [校验](#校验)
- [Legacy 与 Ultimate](#legacy-与-ultimate)
- [地址是怎么推导出来的](#地址是怎么推导出来的)
- [常见问题](#常见问题)
- [免责声明](#免责声明)

---

## 核心结论：直链规则

Flashpoint 每个游戏的真实素材是一个 **GameZip**（一个 zip，内含 SWF/DCR/HTML/资源文件），直链规则如下：

```
https://download.flashpointarchive.org/gib-roms/Games/{gameId}-{timestamp_ms}.zip
```

- `gameId` — 游戏 UUID，例如 `000096cf-5161-4e7e-a1ca-f3cbafac7de4`
- `timestamp_ms` — **`game_data.dateAdded` 的 Unix 毫秒时间戳**

> ⚠️ **最大的坑**：时间戳取自数据库 `game_data` 表的 `dateAdded`，
> **不是** `game` 表的 `date_added`。两者是不同的值，用错了会全部 404。

举例：

| | 值 |
|---|---|
| 游戏 | `Infra`（Shockwave） |
| gameId | `000096cf-5161-4e7e-a1ca-f3cbafac7de4` |
| `game_data.dateAdded` | `2022-01-29T12:23:47.670Z` |
| 时间戳 | `1643459027670` |
| **最终 URL** | `https://download.flashpointarchive.org/gib-roms/Games/000096cf-5161-4e7e-a1ca-f3cbafac7de4-1643459027670.zip` |

CDN 是 **Cloudflare**，支持 Range 请求与断点续传，**中国大陆直连可用**（实测 0.7–2.9 MB/s 单连接，多连接聚合可达 70+ MiB/s），**不需要代理**。

---

## 这个项目解决什么问题

想批量拿到 Flashpoint 里的 SWF（做研究、做数据、做存档），有两条常规路，都不好用：

1. **装 Flashpoint 客户端再逐个下载** —— 只能手动点，20 万条目不可能。
2. **爬 CDN 目录** —— 目录列表在 10000 条处封顶且不支持分页，拿不全。

本项目的做法：**从官方安装器和启动器源码里还原出直链规则**，然后直接用权威数据库枚举全部 URL。

推导链路（每一步都有源码/文件证据，详见 [地址是怎么推导出来的](#地址是怎么推导出来的)）：

```
下载页 → 安装器源码 (URL = root + ID + ".zip")
       → components.xml → core-configuration.zip
       → .preferences.defaults.json  ← 真实数据源在这里
       → launcher 源码 getGameDataFilename()  ← 文件名规则在这里
       → 得到完整直链公式
```

---

## 快速开始

### 依赖

- **Python 3.8+**（仅标准库，无第三方依赖）
- **aria2c**（下载用；[下载地址](https://github.com/aria2/aria2/releases)）
- 磁盘空间：全量 **2.15 TiB**，仅 Flash **794 GiB**，仅 HTML5 **1.31 TiB**

### 三步走

```bash
# 1) 下载权威元数据库（453 MiB）
python scripts/fetch_db.py

# 2) 生成全量 URL 清单
python scripts/build_manifest.py --platform Flash --out manifest_flash.tsv

# 3) 下载 + 校验
bash scripts/download.sh manifest_flash.tsv /path/to/output 32
python scripts/verify.py /path/to/output manifest_flash.tsv
```

也可以完全不用数据库，直接调 API：

```bash
python scripts/build_manifest.py --from-api --platform Flash --out manifest_flash.tsv
```

---

## 数据来源与规模

### 元数据（两条路，任选）

**A. 权威数据库（推荐，一次拿全）**

```
https://download.unstable.life/archive/databases/14/flashpoint.sqlite   # 453 MiB
```

关键表：

| 表 | 行数 | 用途 |
|---|---|---|
| `game_data` | 204,131 | **文件名来源**：`gameId` + `dateAdded` + `sha256` + `size` |
| `game` | 219,394 | 标题、库、平台、开发商、状态、`archiveState` |

**B. REST API（适合增量更新）**

```
https://fpfss.flashpointarchive.org/api/games?after=1970-01-01&before=2030-01-01&broad=true&afterId=
```

每页返回 2500 条，含 `games[]` 与 `game_data[]`（后者带 `sha_256`、`size`）。
总量：`/api/games/updates?after=1970-01-01` → `{"total": 221289}`

### 规模

| 范围 | 条目数 | 体积 |
|---|---|---|
| **全量** | **204,131** | **2.15 TiB** |
| 仅 Flash | 158,772 | 794.4 GiB |
| 仅 HTML5 | 26,374 | 1311.2 GiB |
| 仅 Unity | 2,876 | 51.3 GiB |
| 仅 Shockwave | 6,945 | 13.5 GiB |
| 仅 Silverlight | 399 | 7.0 GiB |

> **只要 SWF 的话，794 GiB 就够了**（Flash 平台）。
> HTML5 条目体积巨大（单个最大 33 GiB，含视频/音频资源），是全量的主要体积来源。

---

## 按平台/库筛选

`build_manifest.py` 支持按平台与库过滤：

```bash
# 只要 Flash
python scripts/build_manifest.py --platform Flash --out flash.tsv

# 多个平台
python scripts/build_manifest.py --platform Flash,Shockwave,Unity --out multi.tsv

# 按库（arcade 街机 / theatre 剧场）
python scripts/build_manifest.py --library arcade --out arcade.tsv

# 组合
python scripts/build_manifest.py --platform Flash --library arcade --out flash_arcade.tsv

# 只要大于 1GiB 的
python scripts/build_manifest.py --min-size 1G --out big.tsv
```

平台分布（TOP）：

| 平台 | 条目数 | 体积 |
|---|---|---|
| Flash | 158,772 | 794.4 GiB |
| HTML5 | 26,374 | 1311.2 GiB |
| Shockwave | 6,945 | 13.5 GiB |
| Unity | 2,876 | 51.3 GiB |
| Java | 2,419 | 5.5 GiB |
| Vitalize | 913 | 0.9 GiB |
| EVA | 724 | 0.0 GiB |
| VRML | 543 | 3.7 GiB |
| Silverlight | 399 | 7.0 GiB |

---

## 下载策略（重要）

**不同平台的体积分布差别极大，排序策略直接决定快慢。** 这是实测踩出来的经验：

### Flash 类（文件碎、单个小）

平均 5 MiB/个，直接高并发：

```bash
bash scripts/download.sh manifest_flash.tsv /mnt/fp-flash 32
```

实测：32 并发 → 16–22 MiB/s。

### HTML5 类（体积极度倾斜）— 必须分两阶段

| 分组 | 数量 | 体积 |
|---|---|---|
| ≥100 MiB | 1,288 (4.9%) | **1042.7 GiB (80%)** |
| <100 MiB | 21,320 (80.8%) | 267.9 GiB (20%) |

如果按体积**升序**下（先小后大），前 2,300 个下完才 0.17 GiB（平均 77 KB/个），
带宽全耗在 HTTP 请求开销上 —— **实测只有 0.99 MiB/s**。

改成**大文件优先**后 —— **实测 71.25 MiB/s（71 倍提升）**。

```bash
# 阶段1：大文件（低并发 + 每文件多连接）
python scripts/build_manifest.py --platform HTML5 --split-by 100M --outdir .
bash scripts/download.sh manifest_big.tsv   /p/fp-html5 10 16   # 1288 个 / 1042 GiB
# 阶段2：碎文件（高并发 + 每文件少连接）
bash scripts/download.sh manifest_small.tsv /p/fp-html5 48 4    # 21320 个 / 268 GiB
```

`download.sh` 参数：`<清单> <目录> [并发] [每文件连接数]`

### 断点续传

aria2c 的 `-c` 会自动跳过已完整的文件，中断后**原样重跑**即可续传。

---

## 校验

官方数据库里每个 GameZip 都带 `sha256`，下完直接比对：

```bash
python scripts/verify.py /path/to/output manifest.tsv
```

输出 OK / 缺失 / 大小不符 / 哈希不符统计，并生成：

- `_verify_bad.json` — 坏件详情
- `_redownload.txt` — aria2c 可直接用的补下清单

实测 200 个样本 **200/200 通过**。

> **关于 404**：约 **0.2%** 的条目在数据库里仍标记 `Playable`，但 CDN 上已无文件（游戏下架）。
> 这是正常现象，aria2c 会跳过，`verify.py` 会把它们列出来。

---

## Legacy 与 Ultimate

### Legacy 格式（老格式，1,688 个）

`archiveState = 1` 的游戏素材**不在 GameZip 里**，而在 6 个分片 zip 中（共 289.5 GiB）：

```
https://download.unstable.life/htdocs_zips/Htdocs_1.zip   # 50 GiB
https://download.unstable.life/htdocs_zips/Htdocs_2.zip   # 50 GiB
...  Htdocs_5.zip (81 GiB), Htdocs_6.zip (8.5 GiB)
```

解压后结构：`Legacy/htdocs/<域名>/<路径>`，例如
`Legacy/htdocs/zetaflow.skylogic.ca/backend/levels/3827.txt`

这些 zip 是 **store 模式（无压缩）**，为了快速解压。

`archiveState = 2`（217,706 个）才是现代 GameZip 格式。

### Ultimate（完整归档，2.28 TiB）

如果你要的是「完整归档」而不是「按需素材」，有现成的大分片和 BT 种子：

```
目录: https://download.unstable.life/ultimate-direct/14_packed/
种子: https://download.unstable.life/FlashpointUltimate14.torrent
```

51 个分片（`Base_1.zip`、`GameData_1..38.zip`、`Htdocs_1..6.zip`、`Images_1..2.zip`、`Extras_1.zip`），
配合 `fp-index.json`（194 MiB，含每个 zip 内每个文件的字节偏移与长度）可以做随机访问。

### CDN 目录总览

| 路径 | 内容 | 体积 |
|---|---|---|
| `gib-roms/Games/` | **现代 GameZip（主力）** | 2.15 TiB |
| `gib-roms/Nga/` | Newgrounds Auditorium 素材 | ~20 GiB |
| `htdocs_zips/` | Legacy 素材 | 289.5 GiB |
| `ultimate-direct/14_packed/` | Ultimate 分片 | 2.28 TiB |
| `archive/databases/14/` | 元数据库 | 453 MiB |

---

## 地址是怎么推导出来的

完整证据链，每一步都可复现：

| 步骤 | 来源 | 得到什么 |
|---|---|---|
| ① | `flashpointarchive.org/downloads` | 指向 CDN `download.unstable.life` |
| ② | 安装器源码 `FlashpointComponentTools/FlashpointInstaller/src/Common.cs:32` | `URL = rootElement["url"] + ID + ".zip"` |
| ③ | `nexus-dev.flashpointarchive.org/repository/stable/components.xml` | 组件清单 + 根 URL |
| ④ | 组件 `core-configuration.zip` → `.preferences.defaults.json` | **`gameDataSources[0].arguments[0]`** = 真实数据源 |
| ⑤ | 启动器源码 `launcher/src/shared/utils/misc.ts:55` `getGameDataFilename()` | 文件名 = `` `${gameId}-${new Date(dateAdded).getTime()}.zip` `` |
| ⑥ | 启动器源码 `launcher/src/back/download.ts:22` | `new URL(filename, source.arguments[0]).href` |
| ⑦ | `.preferences.defaults.json` → `gameMetadataSources[0].baseUrl` | 元数据 API = `fpfss.flashpointarchive.org` |

关键文件（第 ④ 步的解出物）：

```json
{
  "gameDataSources": [{
    "type": "raw",
    "name": "Flashpoint Project",
    "arguments": ["https://download.flashpointarchive.org/gib-roms/Games/"]
  }],
  "gameMetadataSources": [{
    "name": "Flashpoint Archive",
    "baseUrl": "https://fpfss.flashpointarchive.org"
  }]
}
```

### 验证结果

- 文件名公式 vs 真实 CDN 目录：**10000 条中 9943 条精确匹配（99.43%）**，
  差异 57 条是数据库快照时间差（新游戏）
- 随机抽样 492 个 URL：仅 1 个真实 404 → 缺失率 **≈0.2%**
- 实下 20 个 Flash 游戏 → 全部成功，解包得到 23 个真实 `.swf`

---

## 常见问题

**Q: 需要代理吗？**
不需要。CDN 是 Cloudflare，直连可用。实测单连接 0.7–2.9 MB/s，多连接聚合 70+ MiB/s。

**Q: 为什么我的 URL 全部 404？**
几乎肯定是用了 `game.date_added` 而不是 `game_data.dateAdded`。两者是不同的时间戳。

**Q: 目录能直接爬吗？**
不能。CDN 目录列表在 **10000 条处封顶**且不支持 `?page=`/`?offset=` 分页。
必须走数据库或 API 枚举。

**Q: 下载后怎么提取 SWF？**
GameZip 就是普通 zip：

```bash
unzip -j game.zip '*.swf' -d out/
# 或批量
python -c "
import zipfile,glob,os
for p in glob.glob('games/*.zip'):
    with zipfile.ZipFile(p) as z:
        for n in z.namelist():
            if n.lower().endswith('.swf'):
                z.extract(n, 'swf_out')
"
```

**Q: 下载的文件名和游戏名对不上？**
文件名是 `{UUID}-{时间戳}.zip`。用 `manifest.tsv` 里的 `title` 列对照即可。

**Q: 数据会过期吗？**
会。数据库快照有日期（见 `archive/databases/` 下的版本号）。
增量更新用 API 的 `?after=<上次时间>` 参数。

---

## 项目结构

```
.
├── README.md
├── LICENSE
├── scripts/
│   ├── fetch_db.py          # 下载权威元数据库
│   ├── build_manifest.py    # 生成 URL 清单（支持筛选/分片）
│   ├── download.sh          # aria2c 并发下载器
│   └── verify.py            # SHA-256 校验 + 补下清单
└── docs/
    ├── PROTOCOL.md          # 直链规则与推导过程详解
    └── STRATEGY.md          # 下载策略与实测数据
```

---

## 免责声明

- 本项目**不包含、不托管、不分发任何游戏内容**，仅提供公开 CDN 的地址推导与下载调度工具。
- 所有游戏素材版权归各自权利人所有。下载内容请仅用于**个人存档、学术研究**等合法用途。
- Flashpoint Archive 是独立的非营利保存项目，本项目与官方**无隶属关系**。
  请支持官方：<https://flashpointarchive.org/>
- 请遵守目标站点的服务条款，控制并发、避免滥用。

## License

MIT
