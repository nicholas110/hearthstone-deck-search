# Hearthstone Deck Search

[简体中文](README.md)

A local AI skill for real-time Hearthstone deck discovery. It searches a maintained registry of Bilibili creator collections, extracts deck names and complete deck codes from public video metadata, and queries structured sources for constructed deck rankings, official ladder rankings, Arena statistics, and Battlegrounds compositions.

It runs entirely on the user's machine. No hosted workflow, background service, database, or local result cache is required.

## Features

- Search maintained Bilibili collections by creator alias or deck keyword.
- Distinguish standalone video URLs from videos that belong to a Bilibili UGC collection.
- Expand collection pages and inspect recent video titles and descriptions in real time.
- Extract and structurally validate complete Hearthstone deck codes while preserving names already present in video descriptions.
- Return one copyable Markdown code block per deck.
- Search Standard and Wild archetype rankings with representative deck builds.
- Search official Chinese Hearthstone player rankings.
- Search Arena class and card rankings.
- Search Battlegrounds composition tiers and optional strategy details.
- Retry transient network failures, timeouts, rate limits, and supported server errors.
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

### Codex

Windows PowerShell:

```powershell
git clone https://github.com/nicholas110/hearthstone-deck-search.git "$env:USERPROFILE\.codex\skills\hearthstone-deck-search"
```

macOS or Linux:

```bash
git clone https://github.com/nicholas110/hearthstone-deck-search.git ~/.codex/skills/hearthstone-deck-search
```

## Example prompts

```text
What decks has Lvge played recently?
Search Bilibili for recent Control Priest decks.
Show me the top five Standard deck archetypes.
Who are the top ten players on the official Standard ladder?
Rank Arena classes by win rate.
Show Tier 1 Battlegrounds compositions.
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

Search a configured Bilibili creator:

```bash
python scripts/search_bilibili.py --creator "驴鸽" --days 30 --limit 10 --format markdown
```

Search all configured Bilibili collections for a deck:

```bash
python scripts/search_bilibili.py --keyword "偷牌牧" --days 30 --limit 10 --format markdown
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

## Add a Bilibili collection

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

## Data semantics

- Bilibili results indicate that a creator recently played or showcased a deck.
- Video views are not Hearthstone game samples.
- Archetype statistics and representative deck builds are separate records.
- Official ladder rankings contain player positions, not deck codes.
- Arena and Battlegrounds data must not be described as constructed-deck rankings.
- A structurally valid deck code is not guaranteed to be legal in the current game patch.

## Privacy and storage

- The skill sends real-time requests only when invoked.
- It does not create a local result cache.
- It does not download or host Bilibili videos.
- It does not require a user account or collect user credentials.

## Copyright and takedown requests

This project indexes configured public data sources for search and research purposes. It does not host or redistribute the referenced videos.

If you are a rights holder and believe that a configured source infringes your rights, please [open a GitHub issue](https://github.com/nicholas110/hearthstone-deck-search/issues) and identify the relevant source, URL, and basis for the request. After verification, the maintainer will remove or disable the corresponding data source.

## Project structure

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

## Disclaimer

This is an unofficial community project and is not affiliated with, endorsed by, or sponsored by Blizzard Entertainment or Bilibili. Hearthstone and Blizzard are trademarks or registered trademarks of Blizzard Entertainment, Inc. Bilibili is a trademark of its respective owner. Public endpoint behavior and third-party data availability may change without notice.
