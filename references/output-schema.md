# Output schema

The Bilibili search script returns one JSON object.

## Top-level fields

- `query`: normalized creator, keyword, days, and limit.
- `sources`: resolved collection metadata and scan counts.
- `results`: one row per extracted deck code.
- `warnings`: partial failures and configuration problems.
- `request_metrics`: request budget, API request count, candidate count, scan count, and risk-control state.

## Result fields

- `source_id`: maintained source identifier.
- `creator_name`: streamer represented by the collection.
- `uploader`: Bilibili uploader account.
- `collection_id` and `collection_name`: resolved UGC season.
- `bvid`, `video_url`, `title`, and `published_at`: video evidence.
- `deck_name_hint`: nearest description heading or label before the code. When present, this is the authoritative display name and must be preserved exactly.
- `deck_name_source`: `description_heading`, `description_label`, `description_inline`, or `description_line`; otherwise `null`.
- `deck_code`: complete extracted deck code.
- `deck_code_valid`: full Hearthstone Deckstring structural validation.
- `description_excerpt`: short local evidence around the code.
- `views`: current Bilibili view count when available.

Do not map `views` to Hearthstone games or sample size.

## User-facing deck format

When a valid code exists, output one independent fenced `text` block per deck:

````markdown
```text
###控制牧
AAECAa0GBsugBKiWB/ypB4CqB4SqB4O/BwzwnwSg+wbD/waFhgedrQeFvwebvweixAeyxQevyQew3weW/AcAAA==
```
````

This is a Markdown fenced code block. Compatible UIs show a copy button in its upper-right corner. A name table must not replace these blocks.

For Bilibili results, copy the `deck_name_hint` into the `###` line without translating, shortening, normalizing, or replacing it. If no hint exists, use `未命名卡组`; never infer a name from the title or model knowledge.

## Ranking routes

- `deck_rankings`: `results` contain archetype statistics plus an optional `representative_deck`.
- `official_player_rankings`: `results` contain player positions and never contain deck codes.
- `arena_class_rankings`: `results` contain class win rates.
- `arena_card_rankings`: `results` contain card inclusion and played win rates.
- `battlegrounds_comp_rankings`: `results` contain composition tiers and optional guides, not constructed deck codes.
