# Hearthstone Deck Search

[简体中文](README.md)

A local AI skill for real-time Hearthstone deck discovery. It searches the public NetEase Dashen deck square, maintained Bilibili creator collections, structured IYingDi tournament lineups, constructed deck rankings, official ladder rankings, Arena statistics, and Battlegrounds compositions.

It runs entirely on the user's machine. No hosted workflow, background service, database, or local result cache is required.

## Features

- Search maintained Bilibili collections and single videos by creator alias or deck keyword.
- Search NetEase Dashen's public deck square by title, archetype, class, format, and date.
- Dispatch `single_video` and `video_collection` sources explicitly.
- Expand collection pages and inspect recent video titles and descriptions in real time.
- Extract and structurally validate complete Hearthstone deck codes while preserving names already present in video descriptions.
- Search recent IYingDi events and structured tournament lineups.
- Filter tournament decks by event, player, class, format, or deck keyword.
- Return one copyable Markdown code block per deck.
- Search Standard and Wild archetype rankings with representative deck builds.
- Search official Chinese Hearthstone player rankings.
- Search Arena class and card rankings.
- Search Battlegrounds composition tiers and optional strategy details.
- Apply no hard Bilibili request-count cap; use paced sequential scans and result-based early stopping to reduce risk-control triggers.
- Retry transient failures and stop further requests immediately when Bilibili risk control is detected.
- Continue through NetEase Dashen, Bilibili, IYingDi, and constructed rankings when a general deck search returns no result or a source fails.
- Query every selected source for explicit cross-source research while preserving source semantics and warnings.
- Warn when a data source appears stale.
- Never cache fetched results.

## Requirements

- Python 3.10 or newer
- Internet access to the configured public data sources
- An AI client that supports local skills and shell execution, such as Claude Code or Codex

The bundled Python scripts use only the Python standard library.

## Install

### Claude Code

Windows PowerShell:

```powershell
git clone https://github.com/nicholas110/hearthstone-deck-search.git "$env:USERPROFILE\.claude\skills\hearthstone-deck-search"
```

macOS or Linux:

```bash
git clone https://github.com/nicholas110/hearthstone-deck-search.git ~/.claude/skills/hearthstone-deck-search
```

Start a new Claude Code session after installation.

Update:

```powershell
git -C "$env:USERPROFILE\.claude\skills\hearthstone-deck-search" pull --ff-only
```

### Codex

Windows PowerShell:

```powershell
git clone https://github.com/nicholas110/hearthstone-deck-search.git "$env:USERPROFILE\.codex\skills\hearthstone-deck-search"
```

macOS or Linux:

```bash
git clone https://github.com/nicholas110/hearthstone-deck-search.git ~/.codex/skills/hearthstone-deck-search
```

Update an installed skill:

```bash
git -C ~/.codex/skills/hearthstone-deck-search pull --ff-only
```

## Example prompts

```text
What decks has Lvge played recently?
Search Bilibili for recent Control Priest decks.
Show me the top five Standard deck archetypes.
Who are the top ten players on the official Standard ladder?
Rank Arena classes by win rate.
Show Tier 1 Battlegrounds compositions.
Show recent IYingDi tournament deck lists.
What decks appeared in the Changsha Gold tournament top eight?
Which decks did a player use in the Summer qualifier?
Find Control Priest on NetEase Dashen.
Research recent Control Priest decks across every source.
```

The AI should render every valid deck as a separate fenced code block:

````markdown
```text
###Control Priest
AAECAa0GBsugBKiWB/ypB4CqB4SqB4O/BwzwnwSg+wbD/waFhgedrQeFvwebvweixAeyxQevyQew3weW/AcAAA==
```
````

Compatible interfaces display a copy button in the upper-right corner of each block.

## Direct script usage

Run commands from the repository root.

Search the public NetEase Dashen deck square:

```bash
python scripts/search_netease_dashen.py --keyword "控制牧" --mode standard --days 30 --limit 10 --format markdown
```

Continue after an empty result or source failure:

```bash
python scripts/search_decks.py --keyword "控制牧" --days 30 --limit 10 --format markdown
```

Research every selected source:

```bash
python scripts/search_decks.py --keyword "控制牧" --strategy all --sources netease,bilibili,iyingdi,rankings --format markdown
```

Search a configured Bilibili creator:

```bash
python scripts/search_bilibili.py --creator "驴鸽" --days 30 --limit 10 --format markdown
```

Search all configured Bilibili collections for a deck:

```bash
python scripts/search_bilibili.py --keyword "偷牌牧" --days 30 --limit 10 --format markdown
```

Search a configured single-video source:

```bash
python scripts/search_bilibili.py --source "one-video-source" --days 0 --format markdown
```

List recent IYingDi tournament collections:

```bash
python scripts/search_iyingdi.py --list-events --days 30 --format markdown
```

Search by event, player, class, or deck keyword:

```bash
python scripts/search_iyingdi.py --event "黄金赛长沙站" --limit 10 --format markdown
python scripts/search_iyingdi.py --event "夏季预选赛" --player "九千羽" --format markdown
python scripts/search_iyingdi.py --event "夏季预选赛" --class "牧师" --mode standard --format markdown
python scripts/search_iyingdi.py --keyword "控制牧" --days 30 --limit 10 --format markdown
```

Search constructed deck rankings:

```bash
python scripts/search_rankings.py deck --mode standard --limit 5 --format markdown
```

Search official player rankings:

```bash
python scripts/search_rankings.py official --mode standard --limit 10
```

Other ranking routes:

```bash
python scripts/search_rankings.py arena-classes
python scripts/search_rankings.py arena-cards --class "死亡骑士" --limit 10
python scripts/search_rankings.py battlegrounds --tier 1 --details --limit 5
```

## Add a Bilibili source

Edit [`references/sources.yaml`](references/sources.yaml) and add a source entry:

```yaml
- id: "creator-collection-id"
  platform: "bilibili"
  kind: "video_collection"
  entry_url: "https://www.bilibili.com/video/BVxxxxxxxxxx/"
  creator_name: "Creator name"
  creator_aliases: ["Alias 1", "Alias 2"]
  enabled: true
  tags: ["Hearthstone", "stream highlights"]
```

`entry_url` may be either:

- any valid video URL inside a Bilibili UGC collection; or
- a collection URL such as `https://space.bilibili.com/{mid}/lists/{season_id}?type=season`.

When `kind` is `video_collection`, a standalone video is treated as a configuration error instead of being silently accepted.

For a collection URL, also configure a verified video from that season as `seed_bvid`. The script prefers the public UGC Season metadata embedded in that video and avoids unnecessary pagination:

```yaml
- id: "creator-collection-id"
  platform: "bilibili"
  kind: "video_collection"
  entry_url: "https://space.bilibili.com/123/lists/456?type=season"
  seed_bvid: "BVxxxxxxxxxx"
  creator_name: "Creator name"
  creator_aliases: ["Alias"]
  enabled: true
  tags: ["Hearthstone"]
```

Use this structure for one video:

```yaml
- id: "one-video-source"
  platform: "bilibili"
  kind: "single_video"
  entry_url: "https://www.bilibili.com/video/BVxxxxxxxxxx/"
  creator_name: "Creator name"
  creator_aliases: ["Alias"]
  enabled: true
  tags: ["Hearthstone"]
```

`--days` rejects negative values and `--limit` must be positive. The default `max_api_requests: 0` means no Bilibili request-count cap; scanning still stops when enough results have been found or risk control is triggered.

## Sources and methodology

- NetEase Dashen: real-time read of the public deck-square JSON used by its Hearthstone tool; the login-bound personal-deck route is not accessed.
- Bilibili: user-triggered reads of public video and UGC Season metadata without downloading videos or using account cookies.
- IYingDi tournaments: public structured event and lineup endpoints with an empty token and no account cookie; event, player, and deck names come from source fields.
- Constructed, Arena, and Battlegrounds statistics: a third-party community source, not Blizzard.
- Chinese player ladder: the official Chinese Hearthstone leaderboard, containing players and positions only.
- Composite archetype ranking filters samples below `ranking_min_games` and returns the exact score formula in its output.
- Every copyable code must pass full Deckstring parsing, including header, version, format, hero, cards, and optional sideboards.

See [`references/data-sources.md`](references/data-sources.md) for details.

## Data semantics

- NetEase Dashen results are public community deck records, not tournament results, official rankings, or controlled environment samples.
- Bilibili results indicate that a creator recently played or showcased a deck.
- Video views are not Hearthstone game samples.
- IYingDi tournament lineups are event-and-player records, not environment win-rate statistics; page views are not match samples.
- Identical codes used by different players or in different events remain separate records.
- Archetype statistics and representative deck builds are separate records.
- Official ladder rankings contain player positions, not deck codes.
- Arena and Battlegrounds data must not be described as constructed-deck rankings.
- A structurally valid deck code is not guaranteed to be legal in the current game patch.
- Timestamp-free data is labeled as unverifiable, and stale timestamped data produces a warning.

## Privacy and storage

- The skill sends real-time requests only when invoked.
- It does not create a local result cache.
- It does not mirror the NetEase Dashen deck square; it returns only records needed for the active query.
- It does not download or host Bilibili videos.
- It does not mirror IYingDi tournament lineups; it returns only records needed for the active query.
- It does not require a user account or collect user credentials.

## Copyright and takedown requests

This project accesses public data sources for search and research purposes. It does not host or redistribute referenced videos or create a mirror of third-party tournament lineups.

If you are a rights holder and believe that a configured source infringes your rights, please [open a GitHub issue](https://github.com/nicholas110/hearthstone-deck-search/issues) and identify the relevant source, URL, and basis for the request. After verification, the maintainer will remove or disable the corresponding data source.

## Project structure

```text
hearthstone-deck-search/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   └── workflows/tests.yml
├── LICENSE
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── output-schema.md
│   ├── data-sources.md
│   ├── routing.md
│   └── sources.yaml
├── scripts/
    ├── deckstrings.py
    ├── format_decks.py
    ├── search_decks.py
    ├── search_bilibili.py
    ├── search_iyingdi.py
    ├── search_netease_dashen.py
    └── search_rankings.py
└── tests/
    ├── test_bilibili.py
    ├── test_deckstrings.py
    ├── test_formatters.py
    ├── test_iyingdi.py
    ├── test_netease_dashen.py
    ├── test_search_decks.py
    └── test_rankings.py
```

## Tests

```bash
python -m compileall -q scripts tests
python -m unittest discover -s tests -v
```

GitHub Actions runs the offline suite on Python 3.10 and 3.13. CI does not batch-query NetEase Dashen, Bilibili, or IYingDi.

## Disclaimer

This is an unofficial community project and is not affiliated with, endorsed by, or sponsored by Blizzard Entertainment, NetEase Dashen, Bilibili, or IYingDi. Hearthstone and Blizzard are trademarks or registered trademarks of Blizzard Entertainment, Inc. NetEase Dashen, Bilibili, and IYingDi are trademarks of their respective owners. Public endpoint behavior and third-party data availability may change without notice.

The project code is available under the [MIT License](LICENSE). That license does not grant rights to third-party videos, titles, descriptions, trademarks, or data.
