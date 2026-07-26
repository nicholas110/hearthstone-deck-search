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
import urllib.request
from pathlib import Path
from typing import Any

from deckstrings import validate_deck_code
from search_bilibili import load_config, nonnegative_int, positive_int


SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_DIR / "references" / "sources.yaml"
CHINA_TZ = dt.timezone(dt.timedelta(hours=8))
RETRY_HTTP_CODES = {408, 429, 500, 502, 503, 504}
DEFAULT_DATA_URL = "https://lushi-app.gameyw.netease.com/gzdata/lushicarddata.json"
DEFAULT_HOMEPAGE = "https://act.ds.163.com/8fba8a12d9708e3c/"

JOB_CLASSES = {
    "01": ("warrior", "战士"),
    "02": ("shaman", "萨满"),
    "03": ("rogue", "潜行者"),
    "04": ("paladin", "圣骑士"),
    "05": ("hunter", "猎人"),
    "06": ("druid", "德鲁伊"),
    "07": ("warlock", "术士"),
    "08": ("mage", "法师"),
    "09": ("priest", "牧师"),
    "10": ("demonhunter", "恶魔猎手"),
    "11": ("deathknight", "死亡骑士"),
}
CLASS_ALIASES = {
    "warrior": "01",
    "战士": "01",
    "战": "01",
    "shaman": "02",
    "萨满": "02",
    "萨": "02",
    "rogue": "03",
    "潜行者": "03",
    "盗贼": "03",
    "贼": "03",
    "paladin": "04",
    "圣骑士": "04",
    "圣骑": "04",
    "骑": "04",
    "hunter": "05",
    "猎人": "05",
    "猎": "05",
    "druid": "06",
    "德鲁伊": "06",
    "德": "06",
    "warlock": "07",
    "术士": "07",
    "术": "07",
    "mage": "08",
    "法师": "08",
    "法": "08",
    "priest": "09",
    "牧师": "09",
    "牧": "09",
    "demonhunter": "10",
    "dh": "10",
    "恶魔猎手": "10",
    "瞎": "10",
    "deathknight": "11",
    "death knight": "11",
    "dk": "11",
    "死亡骑士": "11",
}
MODE_MAP = {"standard": "标准", "wild": "狂野"}
GENERIC_NAME_RE = re.compile(
    r"^(?:\d+|卡组|套牌|新卡组|自定义(?:卡组|套牌)?|默认(?:卡组|套牌)?)$",
    re.IGNORECASE,
)


def normalized(value: Any) -> str:
    return re.sub(r"[\s·丶_\-—=（）()【】\[\]：:！!]+", "", str(value or "")).casefold()


def normalize_class(value: str | None) -> str | None:
    if not value:
        return None
    key = re.sub(r"[\s_\-]+", " ", value.strip()).casefold()
    job = CLASS_ALIASES.get(key) or CLASS_ALIASES.get(normalized(value))
    if not job:
        raise ValueError(f"Unsupported Hearthstone class: {value}")
    return job


def parse_time(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CHINA_TZ)
    except ValueError:
        return None


def generic_name(value: str) -> bool:
    name = normalized(value)
    if GENERIC_NAME_RE.fullmatch(name):
        return True
    class_names = {normalized(class_zh) for _, class_zh in JOB_CLASSES.values()}
    return any(
        name == f"{prefix}{class_name}"
        for prefix in ("自定义", "默认")
        for class_name in class_names
    )


def source_name(item: dict[str, Any]) -> tuple[str, str]:
    title = str(item.get("title") or "").strip()
    archetype = str((item.get("deckString") or {}).get("liupai") or "").strip()
    if title and not generic_name(title):
        return title, "netease_title"
    if archetype:
        return archetype, "netease_archetype"
    return "未命名卡组", "fallback_unnamed"


def winrate_percent(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0.0001:
        return None
    return round(number * 100 if number <= 1 else number, 2)


class NeteaseDashenClient:
    def __init__(self, *, timeout: int, attempts: int, backoff: list[int]):
        self.timeout = timeout
        self.attempts = max(1, attempts)
        self.backoff = backoff or [1, 2, 4]
        self.request_count = 0

    def fetch(self, url: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            self.request_count += 1
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": DEFAULT_HOMEPAGE,
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/138.0.0.0 Safari/537.36"
                    ),
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    headers = {
                        "last_modified": response.headers.get("Last-Modified") or "",
                        "etag": response.headers.get("ETag") or "",
                    }
                rows = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(rows, list):
                    raise ValueError("NetEase Dashen returned an unexpected JSON schema")
                return [row for row in rows if isinstance(row, dict)], headers
            except urllib.error.HTTPError as error:
                last_error = error
                if error.code not in RETRY_HTTP_CODES:
                    raise
            except (
                urllib.error.URLError,
                TimeoutError,
                socket.timeout,
                json.JSONDecodeError,
                ValueError,
            ) as error:
                last_error = error
            if attempt + 1 < self.attempts:
                time.sleep(
                    self.backoff[min(attempt, len(self.backoff) - 1)]
                    + random.uniform(0, 0.1)
                )
        raise RuntimeError(
            f"NetEase Dashen request failed after {self.attempts} attempts: {last_error}"
        )


def item_matches(
    item: dict[str, Any],
    *,
    keyword: str | None,
    job: str | None,
    mode: str | None,
    cutoff: dt.datetime | None,
) -> bool:
    if job and str(item.get("job") or "").zfill(2) != job:
        return False
    if mode and normalized(item.get("game_mode")) != normalized(MODE_MAP[mode]):
        return False
    published = parse_time(item.get("time"))
    if cutoff and published and published < cutoff:
        return False
    if keyword:
        class_zh = JOB_CLASSES.get(str(item.get("job") or "").zfill(2), ("", ""))[1]
        evidence = " ".join(
            [
                str(item.get("title") or ""),
                str((item.get("deckString") or {}).get("liupai") or ""),
                str(item.get("strategy") or ""),
                class_zh,
                str(item.get("game_mode") or ""),
            ]
        )
        if normalized(keyword) not in normalized(evidence):
            return False
    return True


def slim_deck(item: dict[str, Any]) -> dict[str, Any] | None:
    code = str(item.get("cipher") or "").strip()
    if not validate_deck_code(code):
        return None
    job = str(item.get("job") or "").zfill(2)
    class_name, class_zh = JOB_CLASSES.get(job, ("unknown", "未知职业"))
    name, name_source = source_name(item)
    published = parse_time(item.get("time"))
    try:
        dust = int(float(item.get("osh"))) if item.get("osh") is not None else None
    except (TypeError, ValueError):
        dust = None
    try:
        popularity = float(item.get("hot") or 0)
    except (TypeError, ValueError):
        popularity = 0.0
    return {
        "source_id": "netease-dashen-deck-square",
        "deck_name": name,
        "deck_name_source": name_source,
        "archetype_name": (item.get("deckString") or {}).get("liupai") or None,
        "class": class_name,
        "class_zh": class_zh,
        "format": item.get("game_mode"),
        "published_at": published.isoformat() if published else None,
        "dust": dust,
        "winrate": winrate_percent(item.get("sl")),
        "popularity": popularity,
        "deck_code": code,
        "deck_code_valid": True,
        "record_id": item.get("md5key"),
    }


def sort_key(row: dict[str, Any], sort: str) -> Any:
    if sort == "winrate":
        return row.get("winrate") if row.get("winrate") is not None else -1
    if sort == "popular":
        return row.get("popularity") or 0
    if sort == "cost-low":
        return row.get("dust") if row.get("dust") is not None else float("inf")
    if sort == "cost-high":
        return row.get("dust") if row.get("dust") is not None else -1
    return row.get("published_at") or ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search the public NetEase Dashen Hearthstone deck square in real time."
    )
    parser.add_argument("--keyword", help="Deck or archetype keyword.")
    parser.add_argument("--class", dest="class_name", help="Hearthstone class in Chinese or English.")
    parser.add_argument("--mode", choices=["standard", "wild"], help="Constructed format.")
    parser.add_argument("--days", type=nonnegative_int, default=30, help="Recent window; 0 means all.")
    parser.add_argument(
        "--sort",
        choices=["latest", "winrate", "popular", "cost-low", "cost-high"],
        default="latest",
    )
    parser.add_argument("--limit", type=positive_int, default=10)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        job = normalize_class(args.class_name)
        config = load_config(args.config)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))

    data_url = str(config.get("netease_dashen_data_url") or DEFAULT_DATA_URL)
    homepage = str(config.get("netease_dashen_source_homepage") or DEFAULT_HOMEPAGE)
    client = NeteaseDashenClient(
        timeout=int(config.get("request_timeout_seconds", 15)),
        attempts=int(config.get("retry_max_attempts", 4)),
        backoff=list(config.get("retry_backoff_seconds") or [1, 2, 4]),
    )
    output: dict[str, Any] = {
        "route": "netease_dashen_decks",
        "query": {
            "keyword": args.keyword,
            "class": JOB_CLASSES.get(job, (None, None))[0] if job else None,
            "mode": args.mode,
            "days": args.days,
            "sort": args.sort,
            "limit": args.limit,
        },
        "source": config.get("netease_dashen_source_name") or "网易大神套牌广场",
        "source_url": homepage,
        "source_data_url": data_url,
        "source_provenance": config.get("netease_dashen_source_provenance")
        or "网易大神公开社区套牌数据，非赛事成绩或官方环境统计",
        "results": [],
        "warnings": [],
        "request_metrics": {},
    }

    try:
        rows, headers = client.fetch(data_url)
    except Exception as error:
        output["warnings"].append(f"NetEase Dashen source request failed: {error}")
        output["request_metrics"] = {
            "api_requests": client.request_count,
            "records_received": 0,
            "records_matched": 0,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 2

    now = dt.datetime.now(CHINA_TZ)
    cutoff = now - dt.timedelta(days=args.days) if args.days else None
    matched: list[dict[str, Any]] = []
    invalid_count = 0
    for item in rows:
        if not item_matches(
            item,
            keyword=args.keyword,
            job=job,
            mode=args.mode,
            cutoff=cutoff,
        ):
            continue
        row = slim_deck(item)
        if row:
            matched.append(row)
        elif item.get("cipher"):
            invalid_count += 1

    reverse = args.sort != "cost-low"
    matched.sort(key=lambda row: sort_key(row, args.sort), reverse=reverse)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in matched:
        identity = str(row.get("record_id") or row["deck_code"])
        if identity in seen or row["deck_code"] in seen:
            continue
        seen.add(identity)
        seen.add(row["deck_code"])
        deduped.append(row)
        if len(deduped) >= args.limit:
            break
    output["results"] = deduped

    if invalid_count:
        output["warnings"].append(
            f"{invalid_count} matching records with invalid deck codes were excluded."
        )
    if args.sort == "popular" and matched and not any(row.get("popularity") for row in matched):
        output["warnings"].append(
            "NetEase Dashen currently reports zero popularity for all matching records; "
            "the popularity order is not meaningful."
        )
    if args.sort == "winrate" and matched and not any(
        row.get("winrate") is not None for row in matched
    ):
        output["warnings"].append(
            "NetEase Dashen did not provide meaningful win-rate values for these records."
        )
    output["request_metrics"] = {
        "api_requests": client.request_count,
        "records_received": len(rows),
        "records_matched": len(matched),
        "last_modified": headers.get("last_modified"),
        "etag": headers.get("etag"),
    }

    if args.format == "markdown":
        from format_decks import render_markdown

        print(render_markdown(output))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
