# Data sources and methodology

## Bilibili

- Purpose: discover decks shown by creators in maintained public video sources.
- Access: user-triggered reads of public video and UGC-season metadata.
- Storage: no persistent result cache, video download, account cookie, or credential storage.
- Request controls: finite per-run request budget, paced sequential detail requests, transient retry, and immediate stop on risk-control responses.
- Meaning: a result shows that a creator's maintained source published or showcased the deck. Views are not game samples.

Each source in `sources.yaml` must declare `kind` as either:

- `video_collection`: resolve a UGC season. Prefer a verified `seed_bvid` from that season.
- `single_video`: inspect only the configured BV video.

## IYingDi tournament collections

- Purpose: search structured Hearthstone tournament, qualifier, playoff, and event lineups.
- Access: user-triggered reads of the public set list and set deck endpoints used by the public IYingDi deck page.
- Authentication: empty token; no account cookie or credential.
- Storage: no persistent result cache.
- Request controls: browser-compatible public-page headers, finite request budget, pacing, pagination, and transient retry.
- Meaning: each record belongs to an event and player. It is not an environment win-rate statistic.
- Validation: exclude every code that fails full Deckstring parsing.
- Deduplication: use deck code, player, and event together; the same code used by different players remains separate evidence.
- Freshness: compare the newest matching event date with `iyingdi_stale_days`.

The endpoints are not formally versioned public API documentation and may change. Surface failures instead of bypassing access controls or requesting user credentials.

## Community deck statistics

- Display name: `deck_source_name` in `sources.yaml`.
- Endpoint and homepage: `deck_api_base` and `deck_source_homepage`.
- Provenance: third-party community statistics, not an official Blizzard source.
- Ranking: filter archetype segments below `ranking_min_games`, then sort by the requested raw metric or the documented composite score.
- Composite score: `winrate + log10(popularity_games + 10) * 0.9 + climbing_speed * 0.15 + rank_segment_weight * 1.5`.
- Concrete deck: attach only a structurally valid Deckstring from a representative build.

## Official Chinese ladder

- Display name: `official_source_name` in `sources.yaml`.
- Endpoint and homepage: `official_rank_api_base` and `official_source_homepage`.
- Meaning: player names and ladder positions for a selected season. It does not provide deck codes.

## Freshness

- Constructed rankings: compare the source's last-update value with `ranking_stale_days`.
- Arena cards: compare record timestamps with `arena_stale_days`.
- Battlegrounds compositions: compare record timestamps with `battlegrounds_stale_days`.
- Arena classes: the current endpoint exposes no timestamp, so every response states that freshness cannot be verified.

Always surface `warnings`. Do not describe stale or timestamp-free data as current without qualification.
