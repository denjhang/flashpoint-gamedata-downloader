# 直链规则与推导过程

本文记录 Flashpoint GameZip 直链的**完整还原过程**，每一步都可复现。

## 最终规则

```
https://download.flashpointarchive.org/gib-roms/Games/{gameId}-{timestamp_ms}.zip
```

- `gameId` — 游戏 UUID
- `timestamp_ms` — `game_data.dateAdded` 的 Unix 毫秒时间戳

### 最容易踩的坑

数据库里有**两张表**都有时间字段，很容易搞混：

| 表 | 字段 | 用途 |
|---|---|---|
| `game` | `date_added` | 游戏条目加入数据库的时间 ❌ **不是文件名用的** |
| `game_data` | `dateAdded` | **GameZip 文件的时间戳来源** ✅ |

实例（游戏 `Infra`）：

```
game.date_added        = 2022-01-29T11:56:49.755Z  -> 1643457409755  ❌ 404
game_data.dateAdded    = 2022-01-29T12:23:47.670Z  -> 1643459027670  ✅ 200
实际 CDN 文件名         000096cf-5161-4e7e-a1ca-f3cbafac7de4-1643459027670.zip
```

## 推导链路

### ① 下载页指向 CDN

`https://flashpointarchive.org/downloads` 页面里的链接指向 `download.unstable.life`。

### ② 安装器源码暴露 URL 拼接方式

仓库 `FlashpointProject/FlashpointComponentTools`，文件
`FlashpointInstaller/src/Common.cs`：

```csharp
XmlNode rootElement = node.OwnerDocument.GetElementsByTagName("list")[0];
if (rootElement.Attributes != null && rootElement.Attributes["url"] != null)
{
    URL = rootElement.Attributes["url"].Value + ID + ".zip";
}
```

即：**组件下载地址 = 清单里的根 URL + 组件 ID + ".zip"**。

### ③ 拿到组件清单

```
https://nexus-dev.flashpointarchive.org/repository/stable/components.xml
```

开头：

```xml
<list url="https://nexus-dev.unstable.life/repository/stable/">
```

里面列出所有组件（`launcher`、`configuration`、`gamezip`、`legacy` …）。
组件 ID 是**层级拼接**的，例如 `<category id="core"><category id="server">` 下的
`<component id="gamezip">` 完整 ID 是 `core-server-gamezip`。

### ④ 配置文件里有真实数据源 ★ 关键一步

下载 `core-configuration.zip`（从 `components-stable` 仓库），解开得到
`.preferences.defaults.json`：

```json
{
  "gameDataSources": [{
    "type": "raw",
    "name": "Flashpoint Project",
    "arguments": ["https://download.flashpointarchive.org/gib-roms/Games/"]
  }],
  "gameMetadataSources": [{
    "name": "Flashpoint Archive",
    "baseUrl": "https://fpfss.flashpointarchive.org",
    ...
  }],
  "onDemandBaseUrl": "https://infinity.flashpointarchive.org/images/",
  "dataPacksFolderPath": "Data/Games"
}
```

**`gameDataSources[0].arguments[0]` 就是 GameZip 的根地址。**

### ⑤ 启动器源码给出文件名规则

仓库 `FlashpointProject/launcher`，`src/shared/utils/misc.ts:55`：

```typescript
export function getGameDataFilename(data: GameData) {
  const cleanDate = data.dateAdded.includes('T') ? data.dateAdded : `${data.dateAdded} +0000 UTC`;
  return `${data.gameId}-${(new Date(cleanDate)).getTime()}.zip`;
}
```

### ⑥ 拼接逻辑

`src/back/download.ts:22`：

```typescript
const filename = getGameDataFilename(gameData);
const fullUrl = new URL(filename, source.arguments[0]).href;
```

### ⑦ 元数据 API

`.preferences.defaults.json` 里的 `gameMetadataSources[0].baseUrl` =
`https://fpfss.flashpointarchive.org`，其 API：

```
GET /api/games?after=<ISO>&before=<ISO>&broad=true&afterId=<uuid>
GET /api/games/deleted
GET /api/tags?after=<ISO>
GET /api/platforms?after=<ISO>
GET /api/game-redirects
GET /api/min-launcher
```

每页返回 2500 条，含 `games[]` / `game_data[]` / `tag_relations[]` / `platform_relations[]`。

## 验证

### 目录清单交叉验证

抓 CDN 目录 `gib-roms/Games/` 首页（10000 条上限），与数据库推导的文件名求交集：

```
实际目录: 10000 个文件
数据库推导: 204,131 个
交集: 9943 (99.43%)
差异 57 个 = 数据库快照比 CDN 目录新的部分（新游戏）
```

### 随机抽样

```
样本 492 个随机 URL
200: 491
404: 1  (游戏 SkibidiToilet.io 已下架)
缺失率: ≈0.2%
```

### 内容验证

下载 `Infra` 的 GameZip（1.78 MB）并解包：

```
content.json
content/3dvr.nl/voorbeelden/infra/player.dcr     <- Shockwave 源文件
content/3dvr.nl/voorbeelden/infra/voorbeeld.w3d
```

下载 20 个 Flash 游戏，解包得到 23 个真实 `.swf` 文件。

## CDN 结构

```
https://download.unstable.life/            (与 download.flashpointarchive.org 同一份内容)
├── gib-roms/
│   ├── Games/          现代 GameZip, 204k 个, 2.15 TiB   ← 主力
│   └── Nga/            Newgrounds Auditorium, ~20 GiB
├── htdocs_zips/        Legacy 素材, Htdocs_1..6.zip, 289.5 GiB
├── ultimate-direct/14_packed/   Ultimate 分片, 51 个文件, 2.28 TiB
├── archive/databases/14/flashpoint.sqlite   元数据库, 453 MiB
├── ult-index/          Ultimate 索引 sqlite
└── FlashpointUltimate14.torrent   BT 种子
```

## 关于 CDN 目录不可爬

CDN 目录列表由 Caddy 提供，**固定返回前 10000 条**，且：

- 不支持 `?page=` / `?offset=` / `?start=` / `?limit=`
- 换 `?sort=name|size|time&order=asc|desc` 只改变这 10000 条的排序，不改变数量

所以**必须**通过数据库或 API 枚举，这也是本项目存在的原因。
