#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from deckstrings import validate_deck_code
from search_bilibili import DEFAULT_CONFIG, load_config, positive_int


CHINA_TZ = dt.timezone(dt.timedelta(hours=8))
RETRY_HTTP_CODES = {408, 429, 500, 502, 503, 504}
RETRY_API_CODES = {-1, -2, -500, -503}
RANK_ZH = {
    "top_legend": "传说前列",
    "top_5k": "传说前5000",
    "diamond_to_legend": "钻石到传说",
    "diamond_4to1": "钻石4至1级",
}
RANK_WEIGHT = {
    "top_legend": 4,
    "top_5k": 3,
    "diamond_to_legend": 2,
    "diamond_4to1": 1,
}
CLASS_ZH = {
    "deathknight": "死亡骑士",
    "demonhunter": "恶魔猎手",
    "druid": "德鲁伊",
    "hunter": "猎人",
    "mage": "法师",
    "paladin": "圣骑士",
    "priest": "牧师",
    "rogue": "潜行者",
    "shaman": "萨满祭司",
    "warlock": "术士",
    "warrior": "战士",
}
CLASS_ALIASES = {
    "死亡骑士": "deathknight",
    "死骑": "deathknight",
    "dk": "deathknight",
    "恶魔猎手": "demonhunter",
    "瞎子": "demonhunter",
    "德鲁伊": "druid",
    "小德": "druid",
    "猎人": "hunter",
    "法师": "mage",
    "圣骑士": "paladin",
    "圣骑": "paladin",
    "骑士": "paladin",
    "牧师": "priest",
    "潜行者": "rogue",
    "盗贼": "rogue",
    "贼": "rogue",
    "萨满祭司": "shaman",
    "萨满": "shaman",
    "术士": "warlock",
    "战士": "warrior",
}
ARENA_CLASS_ALIASES = {
    **{key: value.upper() for key, value in CLASS_ALIASES.items()},
    **{key: key.upper() for key in CLASS_ZH},
}
ARCHETYPE_ALIASES = {
    "拉法姆术": "Rafaamlock",
    "弃牌术": "Discolock",
    "弃牌园": "Discolock",
    "任务法": "Quest Mage",
    "任务术": "Seedlock",
    "40任务术": "XL Seedlock",
}


def normalized(value: Any) -> str:
    return re.sub(r"[\s·丶_\-/]+", "", str(value or "")).casefold()


def normalize_class(value: str | None) -> str | None:
    if not value:
        return None
    key = normalized(value)
    for alias, class_key in CLASS_ALIASES.items():
        if normalized(alias) == key:
            return class_key
    if key in CLASS_ZH:
        return key
    raise ValueError(f"Unsupported Hearthstone class: {value}")


def normalize_arena_class(value: str) -> str:
    key = normalized(value)
    for alias, class_key in ARENA_CLASS_ALIASES.items():
        if normalized(alias) == key:
            return class_key
    raise ValueError(f"Unsupported arena class: {value}")


def iso_now() -> str:
    return dt.datetime.now(CHINA_TZ).isoformat()


def parse_timestamp(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for parser in (
        lambda: dt.datetime.fromisoformat(text.replace("Z", "+00:00")),
        lambda: dt.datetime.strptime(text, "%Y.%m.%d %H:%M:%S").replace(tzinfo=CHINA_TZ),
        lambda: dt.datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CHINA_TZ),
    ):
        try:
            return parser()
        except ValueError:
            continue
    return None


def stale_warning(values: list[Any], label: str, max_age_days: int = 90) -> str | None:
    parsed: list[dt.datetime] = []
    for value in values:
        parsed_value = parse_timestamp(value)
        if parsed_value:
            parsed.append(parsed_value)
    if not parsed:
        return None
    newest = max(parsed)
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=dt.timezone.utc)
    age = dt.datetime.now(dt.timezone.utc) - newest.astimezone(dt.timezone.utc)
    if age.days > max_age_days:
        return f"{label} newest record is {age.days} days old ({newest.date().isoformat()}); treat it as potentially stale."
    return None


class RetryJsonClient:
    def __init__(self, timeout: int, attempts: int, backoff: list[int]):
        self.timeout = timeout
        self.attempts = attempts
        self.backoff = backoff or [1, 2, 4]

    def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 HearthstoneDeckSearch/1.0",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if isinstance(payload, dict) and "code" in payload:
                    if payload.get("code") != 0:
                        error = RuntimeError(
                            f"API code={payload.get('code')}: {payload.get('message', 'unknown error')}"
                        )
                        last_error = error
                        if int(payload.get("code") or 0) not in RETRY_API_CODES:
                            raise error
                    else:
                        return payload.get("data")
                else:
                    return payload
            except urllib.error.HTTPError as error:
                last_error = error
                if error.code not in RETRY_HTTP_CODES:
                    raise
            except (urllib.error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError) as error:
                last_error = error
            if attempt + 1 < self.attempts:
                time.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])
        raise RuntimeError(f"Request failed after {self.attempts} attempts: {last_error}")


def archetype_score(item: dict[str, Any]) -> float:
    winrate = float(item.get("winrate") or 0)
    popularity = float(item.get("popularityNum") or 0)
    climb = float(item.get("climbingSpeed") or 0)
    segment = str(item.get("rank") or "")
    return winrate + math.log10(popularity + 10) * 0.9 + climb * 0.15 + RANK_WEIGHT.get(segment, 0) * 1.5


def deck_score(item: dict[str, Any]) -> float:
    return float(item.get("winrate") or 0) + math.log10(float(item.get("games") or 0) + 1) * 2


def archetype_keys(name: Any, zh_name: Any) -> set[str]:
    keys = {normalized(name), normalized(zh_name)}
    expanded = set(keys)
    for key in keys:
        mapped = ARCHETYPE_ALIASES.get(key)
        if mapped:
            expanded.add(normalized(mapped))
    return {key for key in expanded if key}


def build_deck_index(decks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for deck in decks:
        if not deck.get("deckcode") or not validate_deck_code(str(deck.get("deckcode"))):
            continue
        for key in archetype_keys(deck.get("name"), deck.get("zhName")):
            index.setdefault(key, []).append(deck)
    for values in index.values():
        values.sort(key=deck_score, reverse=True)
    return index


def flatten_decks(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("decks"), list):
        return [item for item in payload["decks"] if isinstance(item, dict)]
    rows: list[dict[str, Any]] = []
    for segment, items in payload.items():
        if not isinstance(items, list):
            continue
        for raw in items:
            if isinstance(raw, dict):
                item = dict(raw)
                item.setdefault("rank", segment)
                rows.append(item)
    return rows


def slim_deck(deck: dict[str, Any] | None) -> dict[str, Any] | None:
    if not deck:
        return None
    code = deck.get("deckcode")
    return {
        "deck_id": deck.get("deckId"),
        "name": deck.get("name"),
        "zh_name": deck.get("zhName"),
        "class": deck.get("class"),
        "class_zh": CLASS_ZH.get(normalized(deck.get("class")), deck.get("class")),
        "segment": deck.get("rank"),
        "segment_zh": RANK_ZH.get(str(deck.get("rank")), deck.get("rank")),
        "winrate": deck.get("winrate"),
        "games": deck.get("games"),
        "dust": deck.get("dust"),
        "deck_code": code,
        "deck_code_valid": bool(code and validate_deck_code(str(code))),
        "updated_at": deck.get("updatedAt") or deck.get("createdAt"),
    }


def choose_representative(
    archetype: dict[str, Any], deck_index: dict[str, list[dict[str, Any]]]
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in archetype_keys(archetype.get("name"), archetype.get("zhName")):
        for deck in deck_index.get(key, []):
            marker = str(deck.get("deckId") or deck.get("deckcode"))
            if marker not in seen:
                seen.add(marker)
                candidates.append(deck)
    if not candidates:
        return None
    segment = archetype.get("rank")
    candidates.sort(
        key=lambda deck: (deck.get("rank") == segment, deck_score(deck)),
        reverse=True,
    )
    return candidates[0]


def search_deck_rankings(args: argparse.Namespace, client: RetryJsonClient, config: dict[str, Any]) -> dict[str, Any]:
    base = config["deck_api_base"]
    class_key = normalize_class(args.class_name)
    minimum_games = int(config.get("ranking_min_games", 100))
    archetype_data = client.get(f"{base}/archetypes/getArchetypes", {"mode": args.mode}) or {}
    deck_data = client.get(
        f"{base}/decks/queryDecks",
        {"mode": args.mode, "page": 1, "pageSize": max(200, args.limit * 50)},
    ) or {}
    decks = flatten_decks(deck_data)
    deck_index = build_deck_index(decks)

    rows: list[dict[str, Any]] = []
    for segment, items in archetype_data.items():
        for raw in items or []:
            item = dict(raw)
            item.setdefault("rank", segment)
            if class_key and normalized(item.get("class")) != class_key:
                continue
            if float(item.get("popularityNum") or 0) < minimum_games:
                continue
            if args.archetype:
                needles = archetype_keys(args.archetype, args.archetype)
                if not needles.intersection(archetype_keys(item.get("name"), item.get("zhName"))):
                    continue
            item["_score"] = archetype_score(item)
            rows.append(item)

    best: dict[str, dict[str, Any]] = {}
    samples: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        key = normalized(item.get("name") or item.get("zhName"))
        samples.setdefault(key, []).append(
            {
                "segment": item.get("rank"),
                "segment_zh": RANK_ZH.get(str(item.get("rank")), item.get("rank")),
                "winrate": item.get("winrate"),
                "popularity_percent": item.get("popularityPercent"),
                "popularity_games": item.get("popularityNum"),
            }
        )
        if key not in best or item["_score"] > best[key]["_score"]:
            best[key] = item

    ranked = list(best.values())
    if args.sort == "winrate":
        ranked.sort(key=lambda item: float(item.get("winrate") or 0), reverse=True)
    elif args.sort == "popularity":
        ranked.sort(key=lambda item: float(item.get("popularityNum") or 0), reverse=True)
    else:
        ranked.sort(key=lambda item: item["_score"], reverse=True)

    results = []
    warnings = []
    for position, item in enumerate(ranked[: args.limit], start=1):
        key = normalized(item.get("name") or item.get("zhName"))
        representative = choose_representative(item, deck_index)
        if not representative:
            try:
                exact_payload = client.get(
                    f"{base}/decks/getDecks",
                    {"mode": args.mode, "archetype": item.get("name")},
                )
                exact_decks = [
                    deck
                    for deck in flatten_decks(exact_payload)
                    if deck.get("deckcode") and validate_deck_code(str(deck.get("deckcode")))
                ]
                exact_decks.sort(
                    key=lambda deck: (deck.get("rank") == item.get("rank"), deck_score(deck)),
                    reverse=True,
                )
                representative = exact_decks[0] if exact_decks else None
            except Exception as error:
                warnings.append(f"representative deck lookup for {item.get('name')}: {error}")
                representative = None
        representative_slim = slim_deck(representative)
        if representative_slim and representative_slim.get("deck_code") and not representative_slim["deck_code_valid"]:
            warnings.append(f"invalid representative deck code for {item.get('name')}")
            representative_slim = None
        results.append(
            {
                "position": position,
                "name": item.get("name"),
                "zh_name": item.get("zhName"),
                "class": item.get("class"),
                "class_zh": CLASS_ZH.get(normalized(item.get("class")), item.get("class")),
                "best_segment": item.get("rank"),
                "best_segment_zh": RANK_ZH.get(str(item.get("rank")), item.get("rank")),
                "archetype_winrate": item.get("winrate"),
                "popularity_percent": item.get("popularityPercent"),
                "popularity_games": item.get("popularityNum"),
                "climbing_speed": item.get("climbingSpeed"),
                "rank_samples": samples.get(key, []),
                "representative_deck": representative_slim,
                "has_deck_code": bool(representative_slim and representative_slim.get("deck_code_valid")),
            }
        )

    freshness = None
    try:
        freshness = client.get(f"{base}/config/last-update")
        warning = stale_warning(
            [(freshness or {}).get("lastUpdateTime") if isinstance(freshness, dict) else freshness],
            "Constructed deck rankings",
            int(config.get("ranking_stale_days", 7)),
        )
        if warning:
            warnings.append(warning)
    except Exception as error:
        warnings.append(f"freshness: {error}")
    return {
        "route": "deck_rankings",
        "query": {
            "mode": args.mode,
            "class": class_key,
            "archetype": args.archetype,
            "sort": args.sort,
            "limit": args.limit,
            "minimum_games": minimum_games,
        },
        "source": config.get("deck_source_name", "Community deck statistics"),
        "source_url": config.get("deck_source_homepage"),
        "source_provenance": config.get("deck_source_provenance"),
        "fetched_at": iso_now(),
        "freshness": freshness,
        "ranking_method": {
            "score_formula": "winrate + log10(popularity_games + 10) * 0.9 + climbing_speed * 0.15 + rank_segment_weight * 1.5",
            "minimum_games": minimum_games,
            "sort": args.sort,
        },
        "results": results,
        "deck_code_coverage": {
            "ranked_count": len(results),
            "with_representative_deck_code": sum(1 for item in results if item["has_deck_code"]),
        },
        "warnings": warnings,
    }


def search_official_rankings(args: argparse.Namespace, client: RetryJsonClient, config: dict[str, Any]) -> dict[str, Any]:
    base = config["official_rank_api_base"]
    modes = client.get(f"{base}/v2/game/mode") or {}
    seasons = (modes.get("season_map") or {}).get(args.mode) or []
    if not seasons:
        raise ValueError(f"No official seasons returned for mode={args.mode}")
    season_id = args.season_id or seasons[0]["season_id"]
    season_label = next(
        (item.get("season") for item in seasons if int(item.get("season_id")) == int(season_id)),
        f"赛季{season_id}",
    )
    data = client.get(
        f"{base}/game/ranks",
        {
            "page": max(1, args.page),
            "page_size": min(max(args.limit, 1), 100),
            "mode_name": args.mode,
            "season_id": season_id,
        },
    ) or {}
    rows = (data.get("list") or [])[: args.limit]
    return {
        "route": "official_player_rankings",
        "query": {
            "mode": args.mode,
            "season_id": season_id,
            "season": season_label,
            "page": max(1, args.page),
            "limit": args.limit,
        },
        "source": config.get("official_source_name", "炉石传说国服官方排行榜"),
        "source_url": config.get("official_source_homepage"),
        "fetched_at": iso_now(),
        "total": data.get("total"),
        "results": [
            {
                "position": item.get("position"),
                "player": item.get("battle_tag"),
            }
            for item in rows
        ],
        "contains_deck_codes": False,
        "warnings": [],
    }


def search_arena_classes(args: argparse.Namespace, client: RetryJsonClient, config: dict[str, Any]) -> dict[str, Any]:
    data = client.get(f"{config['deck_api_base']}/arena/class-rank") or []
    rows = sorted(data, key=lambda item: float(item.get("winRate") or 0), reverse=True)[: args.limit]
    return {
        "route": "arena_class_rankings",
        "query": {"limit": args.limit},
        "source": config.get("deck_source_name", "Community deck statistics"),
        "source_url": config.get("deck_source_homepage"),
        "source_provenance": config.get("deck_source_provenance"),
        "fetched_at": iso_now(),
        "results": [
            {
                "position": position,
                "class": normalized(item.get("class")),
                "class_zh": CLASS_ZH.get(normalized(item.get("class")), item.get("class")),
                "winrate": item.get("winRate"),
            }
            for position, item in enumerate(rows, start=1)
        ],
        "warnings": ["Arena class rankings do not expose record timestamps; freshness cannot be verified."],
    }


def search_arena_cards(args: argparse.Namespace, client: RetryJsonClient, config: dict[str, Any]) -> dict[str, Any]:
    class_key = normalize_arena_class(args.class_name)
    data = client.get(f"{config['deck_api_base']}/arena/card-rank", {"class": class_key}) or []
    sort_field = {
        "included-winrate": "includedWinrate",
        "played-winrate": "winrateWhenPlayed",
        "popularity": "includedPopularity",
    }[args.sort]
    rows = sorted(data, key=lambda item: float(item.get(sort_field) or 0), reverse=True)[: args.limit]
    warnings = []
    warning = stale_warning(
        [item.get("updatedAt") for item in data],
        "Arena card rankings",
        int(config.get("arena_stale_days", 90)),
    )
    if warning:
        warnings.append(warning)
    return {
        "route": "arena_card_rankings",
        "query": {"class": class_key, "sort": args.sort, "limit": args.limit},
        "source": config.get("deck_source_name", "Community deck statistics"),
        "source_url": config.get("deck_source_homepage"),
        "source_provenance": config.get("deck_source_provenance"),
        "fetched_at": iso_now(),
        "results": [
            {
                "position": position,
                "name": item.get("name"),
                "card_id": item.get("id"),
                "dbf_id": item.get("dbfId"),
                "cost": item.get("cost"),
                "rarity": item.get("rarity"),
                "included_winrate": item.get("includedWinrate"),
                "winrate_when_played": item.get("winrateWhenPlayed"),
                "included_popularity": item.get("includedPopularity"),
                "updated_at": item.get("updatedAt"),
            }
            for position, item in enumerate(rows, start=1)
        ],
        "warnings": warnings,
    }


def search_battlegrounds(args: argparse.Namespace, client: RetryJsonClient, config: dict[str, Any]) -> dict[str, Any]:
    data = client.get(f"{config['deck_api_base']}/battlegrounds/comp-list") or []
    rows = [
        item
        for item in data
        if not item.get("comp_hidden") and (args.tier is None or int(item.get("comp_tier") or 0) == args.tier)
    ]
    rows.sort(key=lambda item: (int(item.get("comp_tier") or 99), str(item.get("comp_name") or "")))
    results = []
    warnings = []
    warning = stale_warning(
        [item.get("comp_last_updated") for item in rows],
        "Battlegrounds compositions",
        int(config.get("battlegrounds_stale_days", 90)),
    )
    if warning:
        warnings.append(warning)
    for position, item in enumerate(rows[: args.limit], start=1):
        detail = None
        if args.details:
            try:
                detail = client.get(
                    f"{config['deck_api_base']}/battlegrounds/comp-detail",
                    {"compId": item.get("comp_id")},
                )
            except Exception as error:
                warnings.append(f"compId={item.get('comp_id')}: {error}")
        results.append(
            {
                "position": position,
                "comp_id": item.get("comp_id"),
                "name": item.get("comp_name"),
                "tier": item.get("comp_tier"),
                "previous_tier": item.get("comp_previous_tier"),
                "difficulty": item.get("comp_difficulty"),
                "last_updated": item.get("comp_last_updated"),
                "representative_card": item.get("comp_representative_card"),
                "core_cards": item.get("comp_core_cards"),
                "summary": (detail or {}).get("comp_summary"),
                "when_to_commit": (detail or {}).get("comp_when_to_commit"),
                "how_to_play": (detail or {}).get("comp_how_to_play"),
            }
        )
    return {
        "route": "battlegrounds_comp_rankings",
        "query": {"tier": args.tier, "limit": args.limit, "details": args.details},
        "source": config.get("deck_source_name", "Community deck statistics"),
        "source_url": config.get("deck_source_homepage"),
        "source_provenance": config.get("deck_source_provenance"),
        "fetched_at": iso_now(),
        "results": results,
        "contains_constructed_deck_codes": False,
        "warnings": warnings,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search Hearthstone rankings in real time.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)

    deck = subparsers.add_parser("deck", help="Rank constructed deck archetypes and attach representative builds.")
    deck.add_argument("--mode", choices=["standard", "wild"], default="standard")
    deck.add_argument("--class", dest="class_name")
    deck.add_argument("--archetype")
    deck.add_argument("--sort", choices=["score", "winrate", "popularity"], default="score")
    deck.add_argument("--limit", type=positive_int, default=5)
    deck.add_argument("--format", choices=["json", "markdown"], default="json")

    official = subparsers.add_parser("official", help="Read official player ladder rankings.")
    official.add_argument(
        "--mode",
        choices=["standard", "wild", "battlegrounds", "battlegroundsduo", "arena", "twist", "undergroundarena"],
        default="standard",
    )
    official.add_argument("--season-id", type=int)
    official.add_argument("--page", type=positive_int, default=1)
    official.add_argument("--limit", type=positive_int, default=10)
    official.add_argument("--format", choices=["json", "markdown"], default="json")

    arena_classes = subparsers.add_parser("arena-classes", help="Rank Arena classes.")
    arena_classes.add_argument("--limit", type=positive_int, default=11)
    arena_classes.add_argument("--format", choices=["json", "markdown"], default="json")

    arena_cards = subparsers.add_parser("arena-cards", help="Rank Arena cards for one class.")
    arena_cards.add_argument("--class", dest="class_name", required=True)
    arena_cards.add_argument(
        "--sort",
        choices=["included-winrate", "played-winrate", "popularity"],
        default="included-winrate",
    )
    arena_cards.add_argument("--limit", type=positive_int, default=10)
    arena_cards.add_argument("--format", choices=["json", "markdown"], default="json")

    battlegrounds = subparsers.add_parser("battlegrounds", help="Rank Battlegrounds compositions.")
    battlegrounds.add_argument("--tier", type=int, choices=[1, 2, 3, 4])
    battlegrounds.add_argument("--limit", type=positive_int, default=10)
    battlegrounds.add_argument("--details", action="store_true")
    battlegrounds.add_argument("--format", choices=["json", "markdown"], default="json")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if hasattr(args, "limit"):
        args.limit = min(args.limit, 100)
    config = load_config(args.config)
    client = RetryJsonClient(
        timeout=int(config.get("request_timeout_seconds", 15)),
        attempts=int(config.get("retry_max_attempts", 4)),
        backoff=[int(value) for value in config.get("retry_backoff_seconds", [1, 2, 4])],
    )
    handlers = {
        "deck": search_deck_rankings,
        "official": search_official_rankings,
        "arena-classes": search_arena_classes,
        "arena-cards": search_arena_cards,
        "battlegrounds": search_battlegrounds,
    }
    try:
        output = handlers[args.command](args, client, config)
    except Exception as error:
        output = {
            "route": args.command,
            "query": vars(args),
            "source": None,
            "fetched_at": iso_now(),
            "results": [],
            "warnings": [str(error)],
        }
        output["query"]["config"] = str(output["query"]["config"])
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 2
    if args.format == "markdown":
        from format_decks import render_markdown

        print(render_markdown(output))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
