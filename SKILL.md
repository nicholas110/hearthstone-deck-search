---
name: hearthstone-deck-search
description: Real-time Hearthstone deck discovery from maintained Bilibili creator collections, IYingDi tournament collections, and structured ranking sources. Use when users ask which decks a configured streamer has played, ask to search Bilibili for a deck or creator, request recent video deck codes, ask for tournament, event, player, or IYingDi deck lists, or ask for deck, arena, Battlegrounds, or official player rankings.
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
- Deduplicate identical deck codes before responding, except that IYingDi tournament entries from different players or events remain separate evidence records.
- Prefer `deck_name_hint`, `deck_name`, or `representative_deck.zh_name`. For Bilibili, use `未命名卡组` when the description provides no name; never derive one from the title.
- Omit a code block only when no valid code exists. Explain that limitation directly.
- A table may summarize results, but it never replaces the required copyable blocks.

## Route requests

- For Bilibili, video, streamer, or configured creator requests, run `scripts/search_bilibili.py`.
- For tournaments, events, competition lineups, player tournament decks, or IYingDi requests, run `scripts/search_iyingdi.py`.
- For deck/environment rankings, use statistical deck sources. Do not treat Bilibili views as game samples.
- For official ladder/player rankings, use official ranking sources. Do not claim that player rankings contain deck codes.
- For mixed questions, fetch each relevant source independently and label every claim with its source type.

## Search configured Bilibili collections

Read `references/sources.yaml` and `references/data-sources.md` only when adding, diagnosing, or explaining sources. Normal searches should let the scripts load the registry.

Run:

```bash
python scripts/search_bilibili.py --creator "驴鸽" --days 30 --limit 10 --format markdown
python scripts/search_bilibili.py --keyword "偷牌牧" --days 30 --limit 10 --format markdown
python scripts/search_bilibili.py --creator "奶粉" --keyword "战士" --days 14 --limit 5 --format markdown
python scripts/search_bilibili.py --source "one-video-source" --days 0 --format markdown
python scripts/search_bilibili.py --list-sources
```

Resolve relative paths from this skill directory. Pass `--days 0` only when the user explicitly asks for all history; large collections can require many live requests.

The script:

1. Matches creator names and aliases against maintained sources.
2. Dispatches `single_video` and `video_collection` sources explicitly.
3. Prefers collection episodes embedded in a seed video's public metadata and uses collection pagination only as a fallback.
4. Filters and orders archive dates before requesting individual video descriptions.
5. Stops after reaching the requested result limit or the configured request budget.
6. Paces requests, retries transient failures, and stops immediately when Bilibili risk control is detected.
7. Fully parses Deckstrings and extracts names from explicit description headings or labels.
8. Writes to stdout only. It never creates a persistent cache.

If a source configured as `video_collection` resolves to a standalone video, report the configuration error. Do not silently treat it as a single-video source.

Treat request-budget exhaustion and Bilibili `-352` or HTTP `412` responses as partial source failures. Do not bypass risk control or ask the user for account cookies.

## Search IYingDi tournaments

Use the structured tournament collections instead of extracting deck names from tournament articles:

```bash
python scripts/search_iyingdi.py --list-events --days 30 --format markdown
python scripts/search_iyingdi.py --event "黄金赛长沙站" --limit 10 --format markdown
python scripts/search_iyingdi.py --event "夏季预选赛" --player "九千羽" --format markdown
python scripts/search_iyingdi.py --event "夏季预选赛" --class "牧师" --mode standard --format markdown
python scripts/search_iyingdi.py --keyword "控制牧" --days 30 --limit 10 --format markdown
python scripts/search_iyingdi.py --event-id 1647084 --limit 10 --format markdown
```

Interpret “赛事卡组、比赛牌表、黄金赛、预选赛、季后赛、某选手比赛卡组、旅法师营地赛事” as this route.

The script reads public collection and deck-detail endpoints with the same browser request headers used by the public page. It sends an empty token, never uses account cookies, enforces a finite request budget, paces requests, retries transient failures, and creates no persistent cache.

Preserve the structured `deck_name`, `player`, `event_name`, `class_zh`, and `format` fields. Do not ask the model to rename a deck. Do not collapse the same code across different players or events; the player-event combination is meaningful tournament evidence. Treat `pageviews` only as IYingDi page views, never as games, wins, or popularity samples.

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
- Treat a non-empty `deck_name_hint` as the authoritative name copied from the video description. Preserve it exactly; do not translate, shorten, normalize, embellish, or replace it with an archetype inferred from the title or card knowledge.
- Treat IYingDi `deck_name` as an authoritative structured source field. Preserve it exactly and keep the player and event beside the code block.
- If `deck_name_hint` is empty, use `未命名卡组`. Do not invent a name from the video title, gameplay, class, cards, or model knowledge.
- For user-facing Bilibili deck results, prefer `scripts/search_bilibili.py ... --format markdown` and reproduce its fenced deck blocks verbatim. Never manually rewrite the `###` name line.
- State the video date, streamer, uploader, collection, and video URL.
- Keep multiple codes from one video as separate results.
- When no code is present, do not reconstruct a deck from gameplay or title alone.
- Explain partial source failures from the `warnings` array.
- Treat a nonzero script exit as a source failure, not as “no matching deck.”

## Preserve source meanings

- Bilibili means recent creator gameplay or showcased builds.
- IYingDi tournament collections mean submitted or curated event lineups grouped by event and player; page views are not match samples.
- Deck rankings mean archetype statistics and representative builds.
- Official rankings mean players and ladder positions.
- Arena and Battlegrounds statistics are not constructed-deck rankings.

Use `references/output-schema.md` when integrating Bilibili results with other Hearthstone sources.
