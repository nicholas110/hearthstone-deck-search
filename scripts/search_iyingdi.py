#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
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
from search_bilibili import load_config, nonnegative_int, positive_int


SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_DIR / "references" / "sources.yaml"
CHINA_TZ = dt.timezone(dt.timedelta(hours=8))
RETRY_HTTP_CODES = {408, 429, 500, 502, 503, 504}
MODE_MAP = {
    "standard": "标准",
    "wild": "狂野",
}
CLASS_ALIASES = {
    "deathknight": "Deathknight",
    "dk": "Deathknight",
    "死亡骑士": "Deathknight",
    "demonhunter": "Demonhunter",
    "dh": "Demonhunter",
    "恶魔猎手": "Demonhunter",
    "瞎": "Demonhunter",
    "druid": "Druid",
    "德鲁伊": "Druid",
    "德": "Druid",
    "hunter": "Hunter",
    "猎人": "Hunter",
    "猎": "Hunter",
    "mage": "Mage",
    "法师": "Mage",
    "法": "Mage",
    "paladin": "Paladin",
    "圣骑士": "Paladin",
    "圣骑": "Paladin",
    "骑": "Paladin",
    "priest": "Priest",
    "牧师": "Priest",
    "牧": "Priest",
    "rogue": "Rogue",
    "潜行者": "Rogue",
    "盗贼": "Rogue",
    "贼": "Rogue",
    "shaman": "Shaman",
    "萨满": "Shaman",
    "萨": "Shaman",
    "warlock": "Warlock",
    "术士": "Warlock",
    "术": "Warlock",
    "warrior": "Warrior",
    "战士": "Warrior",
    "战": "Warrior",
}
CLASS_ZH = {
    "Deathknight": "死亡骑士",
    "Demonhunter": "恶魔猎手",
    "Druid": "德鲁伊",
    "Hunter": "猎人",
    "Mage": "法师",
    "Paladin": "圣骑士",
    "Priest": "牧师",
    "Rogue": "潜行者",
    "Shaman": "萨满",
    "Warlock": "术士",
    "Warrior": "战士",
}


class RequestBudgetExceeded(RuntimeError):
    pass


class IyingdiApiError(RuntimeError):
    pass


def normalized(value: Any) -> str:
    return re.sub(r"[\s·丶_\-—（）()【】\[\]：:]+", "", str(value or "")).casefold()


def normalize_class(value: str | None) -> str | None:
    if not value:
        return None
    key = normalized(value)
    canonical = CLASS_ALIASES.get(key)
    if not canonical:
        raise ValueError(f"Unsupported Hearthstone class: {value}")
    return canonical


def iso_from_timestamp(value: Any) -> str | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return dt.datetime.fromtimestamp(timestamp, tz=CHINA_TZ).isoformat()


def event_date(event: dict[str, Any]) -> dt.datetime | None:
    begin = event.get("begin")
    if begin:
        try:
            return dt.datetime.strptime(str(begin), "%Y-%m-%d").replace(tzinfo=CHINA_TZ)
        except ValueError:
            pass
    for key in ("updated", "created"):
        value = iso_from_timestamp(event.get(key))
        if value:
            return dt.datetime.fromisoformat(value)
    return None


def event_url(event_id: Any) -> str:
    return (
        "https://www.iyingdi.com/web/tools/hearthstone/decks/"
        f"setdetail?btypes=home_allset&setid={event_id}"
    )


def deck_url(deck_id: Any, event_id: Any) -> str:
    return (
        "https://www.iyingdi.com/web/tools/hearthstone/decks/"
        f"deckdetail/{deck_id}?btypes=home_allset_setdetail&setid={event_id}"
    )


class IyingdiClient:
    def __init__(
        self,
        api_base: str,
        timeout: int,
        attempts: int,
        backoff: list[int],
        max_requests: int,
        request_delay: float,
    ):
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.attempts = max(1, attempts)
        self.backoff = backoff or [1, 2, 4]
        self.max_requests = max(1, max_requests)
        self.request_delay = max(0.0, request_delay)
        self.request_count = 0
        self.last_request_at: float | None = None

    def _pace(self) -> None:
        if self.request_count >= self.max_requests:
            raise RequestBudgetExceeded(
                f"IYingDi request budget exhausted ({self.max_requests})"
            )
        if self.last_request_at is not None and self.request_delay:
            remaining = self.request_delay - (time.monotonic() - self.last_request_at)
            if remaining > 0:
                time.sleep(
                    remaining + random.uniform(0, min(0.05, self.request_delay))
                )
        self.request_count += 1
        self.last_request_at = time.monotonic()

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://www.iyingdi.com",
            "Referer": "https://www.iyingdi.com/web/tools/hearthstone/decks",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
        }

    def request_json(
        self,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.api_base}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        body = urllib.parse.urlencode(form).encode("utf-8") if form is not None else None
        last_error: Exception | None = None

        for attempt in range(self.attempts):
            self._pace()
            request = urllib.request.Request(
                url,
                data=body,
                headers=self._headers(),
                method="POST" if form is not None else "GET",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise IyingdiApiError("IYingDi returned a non-object JSON response")
                if payload.get("success") is not True:
                    raise IyingdiApiError(
                        str(payload.get("message") or payload.get("error") or "API success=false")
                    )
                return payload
            except urllib.error.HTTPError as error:
                last_error = error
                if error.code not in RETRY_HTTP_CODES:
                    raise
            except (
                urllib.error.URLError,
                TimeoutError,
                socket.timeout,
                json.JSONDecodeError,
            ) as error:
                last_error = error
            except IyingdiApiError:
                raise

            if attempt + 1 < self.attempts:
                time.sleep(self.backoff[min(attempt, len(self.backoff) - 1)])

        raise RuntimeError(
            f"IYingDi request failed after {self.attempts} attempts: {last_error}"
        )

    def list_events(self, page: int, size: int) -> list[dict[str, Any]]:
        payload = self.request_json(
            "/hearthstone/set/list/web",
            form={
                "token": "",
                "page": page,
                "size": size,
                "deck_size": 1,
            },
        )
        events = []
        for wrapper in payload.get("sets") or []:
            if not isinstance(wrapper, dict):
                continue
            event = wrapper.get("set")
            if isinstance(event, dict) and event.get("id"):
                events.append(dict(event))
        return events

    def event_decks(self, event_id: int, size: int = 100) -> list[dict[str, Any]]:
        decks = []
        page = 0
        while True:
            payload = self.request_json(
                f"/hearthstone/set/{event_id}/decks",
                query={"token": "", "page": page, "size": size},
            )
            batch = payload.get("list") or []
            for wrapper in batch:
                if not isinstance(wrapper, dict):
                    continue
                deck = wrapper.get("deck")
                if isinstance(deck, dict):
                    decks.append(dict(deck))
            if len(batch) < size:
                break
            page += 1
        return decks


def slim_event(event: dict[str, Any]) -> dict[str, Any]:
    event_id = event.get("id") or event.get("setId")
    return {
        "event_id": event_id,
        "event_name": event.get("name") or event.get("setName"),
        "event_url": event_url(event_id),
        "begin": event.get("begin"),
        "format": event.get("format"),
        "deck_count": event.get("decks"),
        "updated_at": iso_from_timestamp(event.get("updated")),
    }


def event_matches(
    event: dict[str, Any],
    *,
    event_query: str | None,
    mode: str | None,
    cutoff: dt.datetime | None,
) -> bool:
    if event_query and normalized(event_query) not in normalized(event.get("name")):
        return False
    if mode and event.get("format") and normalized(event.get("format")) != normalized(MODE_MAP[mode]):
        return False
    dated = event_date(event)
    return not (cutoff and dated and dated < cutoff)


def deck_matches(
    deck: dict[str, Any],
    *,
    player: str | None,
    class_name: str | None,
    mode: str | None,
    keyword: str | None,
) -> bool:
    if player and normalized(player) not in normalized(deck.get("player")):
        return False
    if class_name and normalized(deck.get("faction")) != normalized(class_name):
        return False
    if mode and normalized(deck.get("format")) != normalized(MODE_MAP[mode]):
        return False
    if keyword:
        evidence = normalized(
            f"{deck.get('name') or ''} {deck.get('player') or ''} "
            f"{deck.get('setName') or ''} {deck.get('faction') or ''}"
        )
        if normalized(keyword) not in evidence:
            return False
    return True


def slim_deck(deck: dict[str, Any], event: dict[str, Any]) -> dict[str, Any] | None:
    code = str(deck.get("code") or "")
    if not validate_deck_code(code):
        return None
    event_id = event.get("id") or event.get("setId") or deck.get("setId")
    event_name = event.get("name") or event.get("setName") or deck.get("setName")
    faction = str(deck.get("faction") or "")
    return {
        "source_id": "iyingdi-tournaments",
        "event_id": event_id,
        "event_name": event_name,
        "event_url": event_url(event_id),
        "event_begin": event.get("begin"),
        "deck_id": deck.get("id"),
        "deck_url": deck_url(deck.get("id"), event_id),
        "deck_name": deck.get("name"),
        "deck_name_source": "iyingdi_structured_field",
        "player": deck.get("player"),
        "class": faction,
        "class_zh": CLASS_ZH.get(faction, faction),
        "format": deck.get("format") or event.get("format"),
        "dust": deck.get("price") or deck.get("build"),
        "pageviews": deck.get("pageview"),
        "updated_at": iso_from_timestamp(deck.get("updated")),
        "deck_code": code,
        "deck_code_valid": True,
    }


def derive_event(event_id: int, decks: list[dict[str, Any]]) -> dict[str, Any]:
    first = decks[0] if decks else {}
    return {
        "id": event_id,
        "name": first.get("setName") or f"赛事专题 {event_id}",
        "format": first.get("format"),
        "decks": len(decks),
        "updated": max(
            (int(deck.get("updated") or 0) for deck in decks),
            default=0,
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search IYingDi Hearthstone tournament deck collections in real time."
    )
    parser.add_argument("--event", help="Tournament or collection name keyword.")
    parser.add_argument("--event-id", type=positive_int, help="Fetch one known IYingDi set id.")
    parser.add_argument("--player", help="Player name keyword.")
    parser.add_argument("--class", dest="class_name", help="Hearthstone class in Chinese or English.")
    parser.add_argument("--mode", choices=["standard", "wild"], help="Constructed format.")
    parser.add_argument("--keyword", help="Deck, player, event, or class keyword.")
    parser.add_argument("--days", type=nonnegative_int, default=30, help="Recent event window; 0 means all.")
    parser.add_argument("--event-limit", type=positive_int, help="Number of recent events to inspect.")
    parser.add_argument("--limit", type=positive_int, default=10, help="Maximum result decks.")
    parser.add_argument("--list-events", action="store_true", help="List matching events without deck details.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        class_name = normalize_class(args.class_name)
        config = load_config(args.config)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))

    event_limit = args.event_limit or int(config.get("iyingdi_event_page_size", 20))
    client = IyingdiClient(
        api_base=str(config.get("iyingdi_api_base") or "https://api2.iyingdi.com"),
        timeout=int(config.get("request_timeout_seconds", 15)),
        attempts=int(config.get("retry_max_attempts", 4)),
        backoff=list(config.get("retry_backoff_seconds") or [1, 2, 4]),
        max_requests=int(config.get("iyingdi_max_api_requests", 8)),
        request_delay=float(config.get("iyingdi_request_delay_seconds", 0.25)),
    )
    now = dt.datetime.now(CHINA_TZ)
    cutoff = now - dt.timedelta(days=args.days) if args.days else None
    output: dict[str, Any] = {
        "route": "iyingdi_events" if args.list_events else "iyingdi_tournament_decks",
        "query": {
            "event": args.event,
            "event_id": args.event_id,
            "player": args.player,
            "class": class_name,
            "mode": args.mode,
            "keyword": args.keyword,
            "days": args.days,
            "event_limit": event_limit,
            "limit": args.limit,
        },
        "source": config.get("iyingdi_source_name"),
        "source_url": config.get("iyingdi_source_homepage"),
        "source_provenance": config.get("iyingdi_source_provenance"),
        "events": [],
        "results": [],
        "warnings": [],
        "request_metrics": {},
    }
    successful_details = 0
    stopped_by_budget = False

    try:
        if args.event_id:
            decks = client.event_decks(args.event_id)
            event = derive_event(args.event_id, decks)
            events = [event]
            prefetched = {args.event_id: decks}
        else:
            events = client.list_events(0, event_limit)
            prefetched = {}
    except Exception as error:
        output["warnings"].append(f"IYingDi source request failed: {error}")
        output["request_metrics"] = {
            "api_requests": client.request_count,
            "request_budget": client.max_requests,
            "events_discovered": 0,
            "events_scanned": 0,
            "stopped_by_budget": isinstance(error, RequestBudgetExceeded),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 2

    selected = [
        event
        for event in events
        if event_matches(
            event,
            event_query=args.event or (args.keyword if args.list_events else None),
            mode=args.mode,
            cutoff=cutoff,
        )
    ]
    selected.sort(
        key=lambda event: event_date(event) or dt.datetime.min.replace(tzinfo=CHINA_TZ),
        reverse=True,
    )
    output["events"] = [slim_event(event) for event in selected]

    if not args.list_events:
        for event in selected:
            event_id_value = int(event.get("id") or event.get("setId"))
            try:
                decks = prefetched.get(event_id_value)
                if decks is None:
                    decks = client.event_decks(event_id_value)
                successful_details += 1
            except RequestBudgetExceeded as error:
                output["warnings"].append(str(error))
                stopped_by_budget = True
                break
            except Exception as error:
                output["warnings"].append(
                    f"{event.get('name') or event_id_value}: {error}"
                )
                continue

            for deck in decks:
                if not deck_matches(
                    deck,
                    player=args.player,
                    class_name=class_name,
                    mode=args.mode,
                    keyword=args.keyword,
                ):
                    continue
                row = slim_deck(deck, event)
                if row:
                    output["results"].append(row)
                elif deck.get("code"):
                    output["warnings"].append(
                        f"Invalid deck code excluded: event={event_id_value}, deck={deck.get('id')}"
                    )

            if len(output["results"]) >= args.limit:
                break

        deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in output["results"]:
            key = (
                str(row["deck_code"]),
                normalized(row.get("player")),
                str(row.get("event_id")),
            )
            deduped[key] = row
        output["results"] = list(deduped.values())[: args.limit]

    stale_days = int(config.get("iyingdi_stale_days", 45))
    newest = max((event_date(event) for event in selected if event_date(event)), default=None)
    if newest and (now - newest).days > stale_days:
        output["warnings"].append(
            f"IYingDi tournament data is {(now - newest).days} days old "
            f"(threshold: {stale_days} days)."
        )
    output["request_metrics"] = {
        "api_requests": client.request_count,
        "request_budget": client.max_requests,
        "events_discovered": len(events),
        "events_matched": len(selected),
        "events_scanned": successful_details,
        "stopped_by_budget": stopped_by_budget,
    }

    if args.format == "markdown":
        from format_decks import render_markdown

        print(render_markdown(output))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))

    if args.list_events:
        return 0
    if selected and successful_details == 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
