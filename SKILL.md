---
name: hearthstone-deck-search
description: Real-time Hearthstone deck discovery from maintained Bilibili creator collections and structured ranking sources. Use when users ask which decks a configured streamer has played, ask to search Bilibili for a deck or creator, request recent video deck codes, or ask for deck, arena, Battlegrounds, or official player rankings.
---

# Hearthstone Deck Search

Route the request before fetching data. Never ask the user for a Bilibili URL; use the maintained source registry.

## Mandatory copyable output

When any result contains a valid deck code, always include every requested deck code in the same response. Never return only a name table and ask which code the user wants.

Render each deck as its own fenced `text` code block so the UI provides a separate copy button:

````markdown
```text
###控制牧
AAECAa0GBsugBKiWB/ypB4CqB4SqB4O/BwzwnwSg+wbD/waFhgedrQeFvwebvweixAeyxQevyQew3weW/AcAAA==
```
````

Follow these rules exactly:

- Put exactly two non-empty lines inside each block: `###卡组名称` and the complete deck code.
- Do not add a space between `###` and the deck name.
- Use one block per deck; never combine multiple decks into one block.
- Keep commentary, date, win rate, source, and video link outside the block.
- Deduplicate identical deck codes before responding.
- Prefer a concise `deck_name_hint` or `representative_deck.zh_name`. If unavailable, derive a conservative short name from the title; do not invent an archetype.
- Omit a code block only when no valid code exists. Explain that limitation directly.
- A table may summarize results, but it never replaces the required copyable blocks.

## Route requests

- For Bilibili, video, streamer, or configured creator requests, run `scripts/search_bilibili.py`.
- For deck/environment rankings, use statistical deck sources. Do not treat Bilibili views as game samples.
- For official ladder/player rankings, use official ranking sources. Do not claim that player rankings contain deck codes.
- For mixed questions, fetch each relevant source independently and label every claim with its source type.

## Search configured Bilibili collections

Read `references/sources.yaml` only when adding or diagnosing sources. Normal searches should let the script load it.

Run:

```bash
python scripts/search_bilibili.py --creator "驴鸽" --days 30 --limit 10 --format markdown
python scripts/search_bilibili.py --keyword "偷牌牧" --days 30 --limit 10 --format markdown
python scripts/search_bilibili.py --creator "奶粉" --keyword "战士" --days 14 --limit 5 --format markdown
python scripts/search_bilibili.py --list-sources
```

Resolve relative paths from this skill directory. Pass `--days 0` only when the user explicitly asks for all history; large collections can require many live requests.

The script:

1. Matches creator names and aliases against maintained sources.
2. Distinguishes an individual video from a video that belongs to a Bilibili UGC season.
3. Expands every section and page of the configured collection.
4. Filters archive dates before requesting individual video descriptions.
5. Retries transient network, timeout, rate-limit, and server errors.
6. Extracts plausible Hearthstone deck codes and nearby deck names.
7. Writes JSON to stdout only. It never creates a cache.

If a source configured as `video_collection` resolves to a standalone video, report the configuration error. Do not silently treat it as a single-video source.

## Search rankings

Run only the route needed by the request:

```bash
python scripts/search_rankings.py deck --mode standard --limit 5 --format markdown
python scripts/search_rankings.py deck --mode standard --class "法师" --sort winrate --limit 5 --format markdown
python scripts/search_rankings.py official --mode standard --limit 10
python scripts/search_rankings.py arena-classes
python scripts/search_rankings.py arena-cards --class "死亡骑士" --limit 10
python scripts/search_rankings.py battlegrounds --tier 1 --details --limit 5
```

Interpret “卡组榜、环境前几、主流卡组” as `deck`. Interpret “国服天梯玩家、玩家排名、谁是第一” as `official`. Interpret Arena and Battlegrounds wording as their dedicated commands.

For `deck`, distinguish:

- Archetype statistics: `archetype_winrate`, popularity, segment samples.
- Concrete build: `representative_deck`.
- Copyable code: only `representative_deck.deck_code`.

Never output an archetype as though it were a concrete 30-card build when `has_deck_code` is false.

Always surface every `warnings` entry. If a ranking source reports stale records, state the newest available record date and avoid describing it as the current patch.

## Interpret results

- Treat `deck_code_valid` as structural validation, not proof that the deck is legal in the current patch.
- Use `deck_name_hint` as evidence from the description. Improve awkward names from the title and description, but do not invent an archetype.
- State the video date, streamer, uploader, collection, and video URL.
- Keep multiple codes from one video as separate results.
- When no code is present, do not reconstruct a deck from gameplay or title alone.
- Explain partial source failures from the `warnings` array.

## Preserve source meanings

- Bilibili means recent creator gameplay or showcased builds.
- Deck rankings mean archetype statistics and representative builds.
- Official rankings mean players and ladder positions.
- Arena and Battlegrounds statistics are not constructed-deck rankings.

Use `references/output-schema.md` when integrating Bilibili results with other Hearthstone sources.
