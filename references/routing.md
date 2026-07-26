# Request routing and bounded continuation

## Route table

| User intent | Primary tool | Allowed continuation |
| --- | --- | --- |
| 网易大神、大神套牌广场 | `search_netease_dashen.py` | Retry and broaden its filters only |
| B站、视频、主播、驴鸽等维护博主 | `search_bilibili.py` | Broaden Bilibili date window only |
| 赛事、比赛牌表、预选赛、某选手参赛卡组、旅法师营地 | `search_iyingdi.py` | Broaden event/date filters only |
| 环境前几、胜率榜、主流卡组 | `search_rankings.py deck` | Do not substitute community popularity |
| 国服天梯玩家、谁是第一 | `search_rankings.py official` | No deck-code fallback |
| 竞技场职业或卡牌 | `search_rankings.py arena-*` | No constructed-deck fallback |
| 酒馆战棋流派、Tier | `search_rankings.py battlegrounds` | No constructed-deck fallback |
| 未指定来源的卡组名或代码请求 | `search_decks.py --strategy fallback` | NetEase → Bilibili → IYingDi → rankings |
| 全面查、多个来源、交叉验证 | `search_decks.py --strategy all` | Query every selected source |

Explicit source wording overrides the generic fallback chain. Never use a semantically different source to fabricate a source-specific claim.

## Continuous-search protocol

1. Retry transient network failures inside the selected source script.
2. If a generic search returns zero results or fails, continue to the next source automatically.
3. If every source returns zero results, broaden once:
   - increase `--days` from the default to `90`;
   - preserve class and mode constraints;
   - remove only nonessential qualifiers such as “最新” or “高胜率” from the keyword.
4. If still empty, run once with `--days 0` when the source supports history.
5. Stop after these bounded passes. Report each attempted source, failure, warning, and filter broadening.

Do not loop indefinitely, bypass access controls, use cookies, or silently discard source failures.

## Source-specific broadening

- Creator question: Bilibili `30 days → 90 days → all history`; never fall back to a generic deck as evidence that the creator played it.
- Tournament question: IYingDi `30 days → 90 days → all history`, then relax the event-name filter only if the user did not specify an exact event.
- Ranking question: keep the ranking route and surface staleness or missing representative builds.
- General deck question: use the multi-source dispatcher before changing the query.

## Answer rules

- Label results as community deck, creator showcase, tournament lineup, environment statistic, or official player ranking.
- Distinguish `source failed` from `zero matches`.
- Preserve warnings from every attempted tool.
- A cross-source match is corroboration of the deck code or name, not proof that the sources share the same win-rate or popularity meaning.
