#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import datetime as dt
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_DIR / "references" / "sources.yaml"
VIDEO_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
LIST_RE = re.compile(r"space\.bilibili\.com/(\d+)/lists/(\d+)")
DECK_CODE_RE = re.compile(r"(?<![A-Za-z0-9+/=])(AA[A-Za-z0-9+/]{35,}={0,2})(?![A-Za-z0-9+/=])")
RETRY_HTTP_CODES = {408, 429, 500, 502, 503, 504}
API_BASE = "https://api.bilibili.com"
CHINA_TZ = dt.timezone(dt.timedelta(hours=8))
GENERIC_HINT_RE = re.compile(
    r"(点点?关注|一键三连|觉得有用|视频每期|卡组都会更新|简介|交流群|谢谢大家|感谢支持)"
)


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith("[") or value.startswith('"'):
        return json.loads(value)
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def load_config(path: Path) -> dict[str, Any]:
    config: dict[str, Any] = {"sources": []}
    current: dict[str, Any] | None = None
    in_sources = False

    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        text = raw.strip()
        if text == "sources:":
            in_sources = True
            continue
        if in_sources and indent == 2 and text.startswith("- "):
            current = {}
            config["sources"].append(current)
            text = text[2:]
        if ":" not in text:
            raise ValueError(f"Unsupported YAML at line {line_number}: {raw}")
        key, value = text.split(":", 1)
        target = current if in_sources and current is not None else config
        target[key.strip()] = parse_scalar(value)

    return config


def normalized(value: str) -> str:
    return re.sub(r"[\s·丶_\-]+", "", value).casefold()


class BilibiliClient:
    def __init__(self, timeout: int, attempts: int, backoff: list[int]):
        self.timeout = timeout
        self.attempts = attempts
        self.backoff = backoff or [1, 2, 4]

    def get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = f"{API_BASE}{path}?{query}"
        last_error: Exception | None = None

        for attempt in range(self.attempts):
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "Referer": "https://www.bilibili.com/",
                    "User-Agent": "Mozilla/5.0 HearthstoneDeckSearch/1.0",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("code") != 0:
                    raise RuntimeError(
                        f"Bilibili API code={payload.get('code')}: {payload.get('message', 'unknown error')}"
                    )
                return payload["data"]
            except urllib.error.HTTPError as error:
                last_error = error
                if error.code not in RETRY_HTTP_CODES:
                    raise
            except (urllib.error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError) as error:
                last_error = error

            if attempt + 1 < self.attempts:
                delay = self.backoff[min(attempt, len(self.backoff) - 1)]
                time.sleep(delay)

        raise RuntimeError(f"Request failed after {self.attempts} attempts: {last_error}")

    def video(self, bvid: str) -> dict[str, Any]:
        return self.get_json("/x/web-interface/view", {"bvid": bvid})

    def collection_page(self, mid: int, season_id: int, page: int) -> dict[str, Any]:
        return self.get_json(
            "/x/polymer/web-space/seasons_archives_list",
            {
                "mid": mid,
                "season_id": season_id,
                "sort_reverse": "false",
                "page_num": page,
                "page_size": 30,
            },
        )


def resolve_collection(client: BilibiliClient, source: dict[str, Any]) -> dict[str, Any]:
    url = source["entry_url"]
    list_match = LIST_RE.search(url)
    if list_match:
        mid, season_id = map(int, list_match.groups())
        return {"mid": mid, "season_id": season_id}

    video_match = VIDEO_RE.search(url)
    if not video_match:
        raise ValueError("entry_url is neither a Bilibili video nor a space collection URL")
    video = client.video(video_match.group(1))
    season = video.get("ugc_season")
    if not season:
        raise ValueError("configured_as_collection_but_video_is_standalone")
    return {
        "mid": int(season.get("mid") or video["owner"]["mid"]),
        "season_id": int(season["id"]),
        "collection_name": season.get("title"),
    }


def fetch_collection(
    client: BilibiliClient, source: dict[str, Any], cutoff_timestamp: int | None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    resolved = resolve_collection(client, source)
    archives: list[dict[str, Any]] = []
    page = 1
    total = None
    metadata: dict[str, Any] = {}

    while total is None or len(archives) < total:
        data = client.collection_page(resolved["mid"], resolved["season_id"], page)
        meta = data.get("meta") or {}
        batch = data.get("archives") or []
        total = int(meta.get("total") or len(archives) + len(batch))
        metadata = {
            "source_id": source["id"],
            "creator_name": source["creator_name"],
            "collection_id": resolved["season_id"],
            "collection_name": meta.get("name") or resolved.get("collection_name"),
            "uploader_mid": resolved["mid"],
            "total_archives": total,
        }
        if not batch:
            break
        archives.extend(batch)
        page_dates = [int(item.get("pubdate") or 0) for item in batch]
        if (
            cutoff_timestamp is not None
            and page_dates
            and page_dates == sorted(page_dates, reverse=True)
            and page_dates[-1] < cutoff_timestamp
        ):
            break
        page += 1

    if cutoff_timestamp is not None:
        archives = [item for item in archives if int(item.get("pubdate") or 0) >= cutoff_timestamp]
    metadata["candidate_archives"] = len(archives)
    return metadata, archives


def validate_deck_code(code: str) -> bool:
    try:
        padded = code + "=" * (-len(code) % 4)
        decoded = base64.b64decode(padded, validate=True)
        return len(decoded) >= 10 and decoded[0] == 0
    except (ValueError, base64.binascii.Error):
        return False


def clean_name_hint(value: str) -> str | None:
    value = re.sub(r"^[#>*\-\s]+", "", value).strip()
    value = re.sub(r"^(卡组|套牌)(名称|代码)?[:：\s]*", "", value).strip()
    if not value or len(value) > 80 or DECK_CODE_RE.search(value) or GENERIC_HINT_RE.search(value):
        return None
    return value


def extract_decks(description: str) -> list[dict[str, Any]]:
    lines = description.splitlines()
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, line in enumerate(lines):
        for match in DECK_CODE_RE.finditer(line):
            code = match.group(1)
            if code in seen:
                continue
            seen.add(code)
            hint = None
            for previous in range(index - 1, max(-1, index - 4), -1):
                hint = clean_name_hint(lines[previous])
                if hint:
                    break
            excerpt = "\n".join(lines[max(0, index - 2) : min(len(lines), index + 2)]).strip()
            results.append(
                {
                    "deck_name_hint": hint,
                    "deck_name_source": "description" if hint else None,
                    "deck_code": code,
                    "deck_code_valid": validate_deck_code(code),
                    "description_excerpt": excerpt[:500],
                }
            )
    return results


def scan_video(
    client: BilibiliClient,
    source: dict[str, Any],
    collection: dict[str, Any],
    archive: dict[str, Any],
    keyword: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    bvid = archive.get("bvid")
    if not bvid:
        return [], "archive_without_bvid"
    try:
        video = client.video(str(bvid))
    except Exception as error:
        return [], f"{bvid}: {error}"

    title = str(video.get("title") or archive.get("title") or "")
    description = str(video.get("desc") or "")
    decks = extract_decks(description)
    if keyword:
        needle = normalized(keyword)
        haystack = normalized(f"{title}\n{description}")
        decks = [
            deck
            for deck in decks
            if needle in haystack or needle in normalized(str(deck.get("deck_name_hint") or ""))
        ]

    published = int(video.get("pubdate") or archive.get("pubdate") or 0)
    published_at = dt.datetime.fromtimestamp(published, tz=CHINA_TZ).isoformat() if published else None
    uploader = (video.get("owner") or {}).get("name")
    views = (video.get("stat") or {}).get("view")
    rows = []
    for deck in decks:
        rows.append(
            {
                "source_id": source["id"],
                "creator_name": source["creator_name"],
                "uploader": uploader,
                "collection_id": collection["collection_id"],
                "collection_name": collection["collection_name"],
                "bvid": bvid,
                "video_url": f"https://www.bilibili.com/video/{bvid}/",
                "title": title,
                "published_at": published_at,
                "published_timestamp": published,
                "views": views,
                **deck,
            }
        )
    return rows, None


def select_sources(config: dict[str, Any], creator: str | None, source_id: str | None) -> list[dict[str, Any]]:
    sources = [
        source
        for source in config["sources"]
        if source.get("enabled") and source.get("platform") == "bilibili"
    ]
    if source_id:
        sources = [source for source in sources if source["id"] == source_id]
    if creator:
        needle = normalized(creator)
        matched = []
        for source in sources:
            names = [source["creator_name"], *(source.get("creator_aliases") or [])]
            if any(needle in normalized(str(name)) or normalized(str(name)) in needle for name in names):
                matched.append(source)
        sources = matched
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Search maintained Bilibili Hearthstone collections in real time.")
    parser.add_argument("--creator", help="Configured streamer name or alias.")
    parser.add_argument("--keyword", help="Deck, class, or title keyword.")
    parser.add_argument("--days", type=int, help="Only scan videos published in the last N days; 0 means all history.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--source", help="Search one configured source id.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--list-sources", action="store_true")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args()

    config = load_config(args.config)
    sources = select_sources(config, args.creator, args.source)
    if args.list_sources:
        print(
            json.dumps(
                [
                    {
                        "id": source["id"],
                        "creator_name": source["creator_name"],
                        "aliases": source.get("creator_aliases") or [],
                        "entry_url": source["entry_url"],
                    }
                    for source in sources
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    days = config.get("default_days", 30) if args.days is None else args.days
    cutoff = None
    if days > 0:
        cutoff = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).timestamp())

    client = BilibiliClient(
        timeout=int(config.get("request_timeout_seconds", 15)),
        attempts=int(config.get("retry_max_attempts", 4)),
        backoff=[int(value) for value in config.get("retry_backoff_seconds", [1, 2, 4])],
    )
    output: dict[str, Any] = {
        "query": {
            "creator": args.creator,
            "keyword": args.keyword,
            "days": days,
            "limit": max(1, args.limit),
        },
        "sources": [],
        "results": [],
        "warnings": [],
    }

    if not sources:
        output["warnings"].append("No configured Bilibili source matched the requested creator or source id.")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 2

    for source in sources:
        try:
            collection, archives = fetch_collection(client, source, cutoff)
            output["sources"].append(collection)
        except Exception as error:
            output["warnings"].append(f"{source['id']}: {error}")
            continue

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=int(config.get("max_workers", 6))
        ) as executor:
            futures = [
                executor.submit(scan_video, client, source, collection, archive, args.keyword)
                for archive in archives
            ]
            for future in concurrent.futures.as_completed(futures):
                rows, warning = future.result()
                output["results"].extend(rows)
                if warning:
                    output["warnings"].append(f"{source['id']}: {warning}")

    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in output["results"]:
        deduped[(row["bvid"], row["deck_code"])] = row
    results = sorted(deduped.values(), key=lambda row: row["published_timestamp"], reverse=True)
    output["results"] = results[: max(1, args.limit)]
    for row in output["results"]:
        row.pop("published_timestamp", None)

    if args.format == "markdown":
        from format_decks import render_markdown

        print(render_markdown(output))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
