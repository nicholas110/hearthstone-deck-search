# 炉石卡组检索 Skill

[English](README.en.md)

一个完全本地运行的炉石传说卡组检索 Skill。它可以从维护好的 B站博主视频合集里实时查找卡组，提取卡组名称和完整代码，也可以查询构筑卡组环境排行、国服官方玩家排行榜、竞技场数据以及酒馆战棋流派。

项目不依赖云端工作流、常驻服务器、数据库或本地结果缓存，所有操作均由用户自己的 AI 客户端在本机按需执行。

## 主要功能

- 按博主名称、别名或卡组关键词检索已维护的 B站合集。
- 区分独立视频与属于 B站 UGC 合集的视频。
- 实时展开合集分页，读取近期视频标题和简介。
- 提取并结构化校验完整炉石卡组代码。
- 每套卡组单独输出一个带复制按钮的 Markdown 代码块。
- 查询标准和狂野模式的卡组原型排行及代表构筑。
- 查询炉石国服官方玩家排行榜。
- 查询竞技场职业和卡牌排行。
- 查询酒馆战棋流派梯队及可选玩法说明。
- 网络波动、超时、限流和部分服务端错误自动重试。
- 数据可能过期时主动输出警告。
- 不保存查询结果缓存。

## 运行条件

- Python 3.10 或更高版本
- 能够访问配置中的公开数据源
- 支持本地 Skill 和命令执行的 AI 客户端，例如 Claude Code 或 Codex

项目脚本只使用 Python 标准库，无需安装额外依赖。

## 安装

### Claude Code

Windows PowerShell：

```powershell
git clone https://github.com/nicholas110/hearthstone-deck-search.git "$env:USERPROFILE\.claude\skills\hearthstone-deck-search"
```

macOS 或 Linux：

```bash
git clone https://github.com/nicholas110/hearthstone-deck-search.git ~/.claude/skills/hearthstone-deck-search
```

安装后请新开一个 Claude Code 会话。

### Codex

Windows PowerShell：

```powershell
git clone https://github.com/nicholas110/hearthstone-deck-search.git "$env:USERPROFILE\.codex\skills\hearthstone-deck-search"
```

macOS 或 Linux：

```bash
git clone https://github.com/nicholas110/hearthstone-deck-search.git ~/.codex/skills/hearthstone-deck-search
```

## 提问示例

```text
驴哥最近有什么卡组？
在B站找一下最近的控制牧。
标准模式环境前五的卡组是什么？
国服标准天梯前十名是谁？
竞技场哪个职业胜率最高？
酒馆战棋一线流派有哪些？
```

只要结果中存在有效代码，AI 就必须为每套卡组输出独立的可复制代码块：

````markdown
```text
###控制牧
AAECAa0GBsugBKiWB/ypB4CqB4SqB4O/BwzwnwSg+wbD/waFhgedrQeFvwebvweixAeyxQevyQew3weW/AcAAA==
```
````

兼容的界面会在代码块右上角自动显示复制按钮。

## 直接运行脚本

以下命令均在仓库根目录执行。

查询指定 B站博主：

```bash
python scripts/search_bilibili.py --creator "驴鸽" --days 30 --limit 10 --format markdown
```

从全部已配置合集检索某个卡组：

```bash
python scripts/search_bilibili.py --keyword "偷牌牧" --days 30 --limit 10 --format markdown
```

查询构筑卡组环境排行：

```bash
python scripts/search_rankings.py deck --mode standard --limit 5 --format markdown
```

查询官方玩家排行榜：

```bash
python scripts/search_rankings.py official --mode standard --limit 10
```

其他排行：

```bash
python scripts/search_rankings.py arena-classes
python scripts/search_rankings.py arena-cards --class "死亡骑士" --limit 10
python scripts/search_rankings.py battlegrounds --tier 1 --details --limit 5
```

## 添加 B站视频合集

编辑 [`references/sources.yaml`](references/sources.yaml)，增加一个固定结构的数据源：

```yaml
- id: "creator-collection-id"
  platform: "bilibili"
  kind: "video_collection"
  entry_url: "https://www.bilibili.com/video/BVxxxxxxxxxx/"
  creator_name: "博主名称"
  creator_aliases: ["常用别名1", "常用别名2"]
  enabled: true
  tags: ["炉石传说", "直播切片"]
```

`entry_url` 支持两种形式：

- B站视频合集内任意一个仍然有效的视频地址；
- `https://space.bilibili.com/{mid}/lists/{season_id}?type=season` 形式的合集地址。

当 `kind` 设置为 `video_collection` 时，如果入口实际是独立视频，脚本会将其报告为配置错误，不会悄悄当作单视频处理。

## 数据含义

- B站结果只能说明某位博主近期玩过或展示过该卡组。
- 视频播放量不能当作炉石对局样本量。
- 卡组原型统计与具体代表构筑是两类不同数据。
- 官方天梯排行榜只有玩家名称和名次，不包含卡组代码。
- 竞技场和酒馆战棋数据不能描述成构筑卡组排行。
- 卡组代码通过结构校验，不代表它一定适用于当前游戏版本。

## 隐私与存储

- 只有用户发起查询时才会实时访问数据源。
- 不创建本地查询结果缓存。
- 不下载、托管或重新分发 B站视频。
- 不要求用户登录，也不收集用户账号或凭据。

## 版权与数据源下架请求

本项目仅为检索和研究目的索引已配置的公开数据源，不托管或重新分发相关视频。

如果你是相关内容的权利人，并认为某个已配置数据源涉及侵权，请通过 [GitHub Issues](https://github.com/nicholas110/hearthstone-deck-search/issues) 联系作者，并提供对应数据源、链接和请求理由。核实后，维护者会删除或停用相应数据源。

## 项目结构

```text
hearthstone-deck-search/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── output-schema.md
│   └── sources.yaml
└── scripts/
    ├── format_decks.py
    ├── search_bilibili.py
    └── search_rankings.py
```

## 免责声明

本项目是非官方社区项目，与暴雪娱乐及哔哩哔哩不存在隶属、授权、认可或赞助关系。Hearthstone、炉石传说及 Blizzard 为暴雪娱乐公司相关商标；哔哩哔哩及 Bilibili 为其权利人相关商标。公开接口行为和第三方数据可用性可能随时发生变化。
