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


SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_DIR / "references" / "sources.yaml"
VIDEO_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
LIST_RE = re.compile(r"space\.bilibili\.com/(\d+)/lists/(\d+)")
DECK_CODE_RE = re.compile(r"(?<![A-Za-z0-9+/=])(AA[A-Za-z0-9+/]{35,}={0,2})(?![A-Za-z0-9+/=])")
RETRY_HTTP_CODES = {408, 429, 500, 502, 503, 504}
RETRY_API_CODES = {-1, -2, -500, -503}
RISK_CONTROL_API_CODES = {-352, -412}
API_BASE = "https://api.bilibili.com"
CHINA_TZ = dt.timezone(dt.timedelta(hours=8))
GENERIC_HINT_RE = re.compile(
    r"(点点?关注|一键三连|觉得有用|视频每期|卡组都会更新|简介|交流群|谢谢大家|感谢支持)"
)
METADATA_HINT_RE = re.compile(
    r"^(作者|上传者|主播|来源|日期|时间|直播间|视频|链接|地址|QQ群|群号|微信|WX|QQ|备注)\s*[:：]",
    re.IGNORECASE,
)
EXPLICIT_NAME_RE = re.compile(
    r"^\s*(?:#{1,6}\s*|(?:卡组|套牌)(?:名称)?\s*[:：]\s*)(.+?)\s*$",
    re.IGNORECASE,
)


class BilibiliApiError(RuntimeError):
    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(f"Bilibili API code={code}: {message}")


class RequestBudgetExceeded(RuntimeError):
    pass


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith("[") or value.startswith('"'):
        return json.loads(value)
    if re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return float(value) if "." in value else int(value)
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

    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    if int(config.get("retry_max_attempts", 1)) < 1:
        raise ValueError("retry_max_attempts must be at least 1")
    if int(config.get("max_api_requests", 0)) < 0:
        raise ValueError("max_api_requests must be zero or greater")
    seen: set[str] = set()
    for source in config.get("sources") or []:
        missing = [
            key
            for key in ("id", "platform", "kind", "entry_url", "creator_name")
            if not source.get(key)
        ]
        if missing:
            raise ValueError(f"Source is missing required fields {missing}: {source.get('id', '<unknown>')}")
        if source["id"] in seen:
            raise ValueError(f"Duplicate source id: {source['id']}")
        seen.add(source["id"])
        if source["kind"] not in {"video_collection", "single_video"}:
            raise ValueError(f"Unsupported source kind for {source['id']}: {source['kind']}")
        if source["platform"] != "bilibili":
            raise ValueError(f"Unsupported platform for {source['id']}: {source['platform']}")


def normalized(value: str) -> str:
    return re.sub(r"[\s·丶_\-]+", "", value).casefold()


class BilibiliClient:
    def __init__(
        self,
        timeout: int,
        attempts: int,
        backoff: list[int],
        max_requests: int = 0,
        request_delay: float = 0.25,
    ):
        self.timeout = timeout
        self.attempts = max(1, attempts)
        self.backoff = backoff or [1, 2, 4]
        self.max_requests = max_requests if max_requests > 0 else None
        self.request_delay = max(0.0, request_delay)
        self.request_count = 0
        self.last_request_at: float | None = None
        self.risk_controlled = False
        self._video_cache: dict[str, dict[str, Any]] = {}

    def _pace(self) -> None:
        if self.risk_controlled:
            raise RequestBudgetExceeded("Bilibili risk control was triggered; stopped further requests")
        if self.max_requests is not None and self.request_count >= self.max_requests:
            raise RequestBudgetExceeded(f"Bilibili request budget exhausted ({self.max_requests})")
        if self.last_request_at is not None and self.request_delay:
            elapsed = time.monotonic() - self.last_request_at
            remaining = self.request_delay - elapsed
            if remaining > 0:
                time.sleep(remaining + random.uniform(0, min(0.1, self.request_delay)))
        self.request_count += 1
        self.last_request_at = time.monotonic()

    def get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = f"{API_BASE}{path}?{query}"
        last_error: Exception | None = None

        for attempt in range(self.attempts):
            self._pace()
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
                code = int(payload.get("code") or 0)
                if code == 0:
                    return payload["data"]
                error = BilibiliApiError(code, str(payload.get("message") or "unknown error"))
                last_error = error
                if code in RISK_CONTROL_API_CODES:
                    self.risk_controlled = True
                    raise error
                if code not in RETRY_API_CODES:
                    raise error
            except urllib.error.HTTPError as error:
                last_error = error
                if error.code == 412:
                    self.risk_controlled = True
                    raise
                if error.code not in RETRY_HTTP_CODES:
                    raise
            except (urllib.error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError) as error:
                last_error = error

            if attempt + 1 < self.attempts:
                delay = self.backoff[min(attempt, len(self.backoff) - 1)]
                time.sleep(delay)

        raise RuntimeError(f"Request failed after {self.attempts} attempts: {last_error}")

    def video(self, bvid: str) -> dict[str, Any]:
        if bvid not in self._video_cache:
            self._video_cache[bvid] = self.get_json("/x/web-interface/view", {"bvid": bvid})
        return self._video_cache[bvid]

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


def archive_from_episode(episode: dict[str, Any]) -> dict[str, Any]:
    archive = dict(episode.get("arc") or {})
    archive["bvid"] = episode.get("bvid") or archive.get("bvid")
    archive["title"] = episode.get("title") or archive.get("title")
    return archive


def embedded_collection(video: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    season = video.get("ugc_season") or {}
    if not season:
        raise ValueError("configured_as_collection_but_video_is_standalone")
    episodes = [
        archive_from_episode(episode)
        for section in season.get("sections") or []
        for episode in section.get("episodes") or []
    ]
    return season, episodes


def resolve_collection(
    client: BilibiliClient, source: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    url = str(source["entry_url"])
    list_match = LIST_RE.search(url)
    expected_season_id = int(list_match.group(2)) if list_match else None
    seed_bvid = source.get("seed_bvid")
    video_match = VIDEO_RE.search(url)
    bvid = str(seed_bvid or (video_match.group(1) if video_match else ""))

    if bvid:
        video = client.video(bvid)
        season, episodes = embedded_collection(video)
        season_id = int(season["id"])
        if expected_season_id is not None and season_id != expected_season_id:
            raise ValueError(
                f"seed_bvid season mismatch: expected {expected_season_id}, resolved {season_id}"
            )
        return (
            {
                "mid": int(season.get("mid") or (video.get("owner") or {})["mid"]),
                "season_id": season_id,
                "collection_name": season.get("title"),
                "resolution": "embedded_ugc_season",
            },
            episodes,
        )

    if list_match:
        mid, season_id = map(int, list_match.groups())
        return (
            {
                "mid": mid,
                "season_id": season_id,
                "collection_name": None,
                "resolution": "collection_api",
            },
            None,
        )
    raise ValueError("entry_url is neither a Bilibili video nor a space collection URL")


def filter_archives(
    archives: list[dict[str, Any]], cutoff_timestamp: int | None
) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for archive in archives:
        bvid = archive.get("bvid")
        if not bvid:
            continue
        published = int(archive.get("pubdate") or 0)
        if cutoff_timestamp is not None and published < cutoff_timestamp:
            continue
        deduped[str(bvid)] = archive
    return sorted(deduped.values(), key=lambda item: int(item.get("pubdate") or 0), reverse=True)


def fetch_collection(
    client: BilibiliClient, source: dict[str, Any], cutoff_timestamp: int | None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    resolved, embedded = resolve_collection(client, source)
    archives: list[dict[str, Any]] = []

    if embedded is not None:
        archives = embedded
        total = len(archives)
    else:
        page = 1
        total: int | None = None
        while total is None or len(archives) < total:
            data = client.collection_page(resolved["mid"], resolved["season_id"], page)
            meta = data.get("meta") or {}
            batch = data.get("archives") or []
            total = int(meta.get("total") or len(archives) + len(batch))
            resolved["collection_name"] = meta.get("name") or resolved.get("collection_name")
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

    candidates = filter_archives(archives, cutoff_timestamp)
    metadata = {
        "source_id": source["id"],
        "source_kind": source["kind"],
        "creator_name": source["creator_name"],
        "collection_id": resolved["season_id"],
        "collection_name": resolved.get("collection_name"),
        "uploader_mid": resolved["mid"],
        "resolution": resolved["resolution"],
        "total_archives": total,
        "candidate_archives": len(candidates),
        "scanned_videos": 0,
    }
    return metadata, candidates


def fetch_single_video(
    client: BilibiliClient, source: dict[str, Any], cutoff_timestamp: int | None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    match = VIDEO_RE.search(str(source["entry_url"]))
    if not match:
        raise ValueError("single_video entry_url does not contain a valid BV id")
    video = client.video(match.group(1))
    published = int(video.get("pubdate") or 0)
    candidates = [] if cutoff_timestamp is not None and published < cutoff_timestamp else [video]
    metadata = {
        "source_id": source["id"],
        "source_kind": source["kind"],
        "creator_name": source["creator_name"],
        "collection_id": None,
        "collection_name": None,
        "uploader_mid": (video.get("owner") or {}).get("mid"),
        "resolution": "single_video",
        "total_archives": 1,
        "candidate_archives": len(candidates),
        "scanned_videos": 0,
    }
    return metadata, candidates


def clean_name_hint(value: str, require_explicit: bool = False) -> tuple[str | None, str | None]:
    raw = value.strip()
    if not raw:
        return None, None
    match = EXPLICIT_NAME_RE.match(raw)
    if match:
        raw = match.group(1).strip()
        source = "description_heading" if raw and value.lstrip().startswith("#") else "description_label"
    elif require_explicit:
        return None, None
    else:
        source = "description_line"
    raw = re.sub(r"^(卡组|套牌)(名称|代码)?[:：\s]*", "", raw).strip()
    if (
        not raw
        or len(raw) > 80
        or DECK_CODE_RE.search(raw)
        or GENERIC_HINT_RE.search(raw)
        or METADATA_HINT_RE.search(raw)
        or raw.startswith(("http://", "https://"))
    ):
        return None, None
    return raw, source


def find_name_hint(
    lines: list[str], code_line_index: int, inline_prefix: str
) -> tuple[str | None, str | None]:
    if inline_prefix.strip():
        hint, source = clean_name_hint(inline_prefix)
        if hint:
            return hint, "description_inline" if source == "description_line" else source

    preceding = lines[max(0, code_line_index - 6) : code_line_index]
    for line in reversed(preceding):
        hint, source = clean_name_hint(line, require_explicit=True)
        if hint:
            return hint, source

    for line in reversed(preceding):
        if not line.strip():
            continue
        return clean_name_hint(line)
    return None, None


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
            hint, hint_source = find_name_hint(lines, index, line[: match.start()])
            excerpt = "\n".join(lines[max(0, index - 3) : min(len(lines), index + 2)]).strip()
            results.append(
                {
                    "deck_name_hint": hint,
                    "deck_name_source": hint_source,
                    "deck_code": code,
                    "deck_code_valid": validate_deck_code(code),
                    "description_excerpt": excerpt[:500],
                }
            )
    return results


def deck_matches_keyword(
    deck: dict[str, Any], title: str, keyword: str, deck_count: int
) -> bool:
    needle = normalized(keyword)
    local_evidence = normalized(
        f"{deck.get('deck_name_hint') or ''}\n{deck.get('description_excerpt') or ''}"
    )
    if needle in local_evidence:
        return True
    return deck_count == 1 and needle in normalized(title)


def scan_video(
    client: BilibiliClient,
    source: dict[str, Any],
    collection: dict[str, Any],
    archive: dict[str, Any],
    keyword: str | None,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    bvid = archive.get("bvid")
    if not bvid:
        return [], "archive_without_bvid", False
    try:
        video = client.video(str(bvid))
    except RequestBudgetExceeded:
        raise
    except Exception as error:
        return [], f"{bvid}: {error}", False

    title = str(video.get("title") or archive.get("title") or "")
    description = str(video.get("desc") or "")
    decks = extract_decks(description)
    if keyword:
        decks = [
            deck
            for deck in decks
            if deck_matches_keyword(deck, title, keyword, len(decks))
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
                "source_kind": source["kind"],
                "creator_name": source["creator_name"],
                "uploader": uploader,
                "collection_id": collection.get("collection_id"),
                "collection_name": collection.get("collection_name"),
                "bvid": bvid,
                "video_url": f"https://www.bilibili.com/video/{bvid}/",
                "title": title,
                "published_at": published_at,
                "published_timestamp": published,
                "views": views,
                **deck,
            }
        )
    return rows, None, True


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
        sources = [
            source
            for source in sources
            if any(
                needle in normalized(str(name)) or normalized(str(name)) in needle
                for name in [source["creator_name"], *(source.get("creator_aliases") or [])]
            )
        ]
    return sources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search maintained Bilibili Hearthstone sources in real time.")
    parser.add_argument("--creator", help="Configured streamer name or alias.")
    parser.add_argument("--keyword", help="Deck, class, or title keyword.")
    parser.add_argument(
        "--days",
        type=nonnegative_int,
        help="Only scan videos published in the last N days; 0 means all history.",
    )
    parser.add_argument("--limit", type=positive_int, default=10)
    parser.add_argument("--source", help="Search one configured source id.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--list-sources", action="store_true")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    sources = select_sources(config, args.creator, args.source)
    if args.list_sources:
        print(
            json.dumps(
                [
                    {
                        "id": source["id"],
                        "kind": source["kind"],
                        "creator_name": source["creator_name"],
                        "aliases": source.get("creator_aliases") or [],
                        "entry_url": source["entry_url"],
                        "seed_bvid": source.get("seed_bvid"),
                    }
                    for source in sources
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    days = int(config.get("default_days", 30) if args.days is None else args.days)
    cutoff = None
    if days > 0:
        cutoff = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).timestamp())

    client = BilibiliClient(
        timeout=int(config.get("request_timeout_seconds", 15)),
        attempts=int(config.get("retry_max_attempts", 4)),
        backoff=[int(value) for value in config.get("retry_backoff_seconds", [1, 2, 4])],
        max_requests=int(config.get("max_api_requests", 0)),
        request_delay=float(config.get("request_delay_seconds", 0.25)),
    )
    output: dict[str, Any] = {
        "route": "bilibili_decks",
        "query": {
            "creator": args.creator,
            "keyword": args.keyword,
            "days": days,
            "limit": args.limit,
            "request_budget": client.max_requests,
        },
        "sources": [],
        "results": [],
        "warnings": [],
        "request_metrics": {},
    }

    if not sources:
        output["warnings"].append("No configured Bilibili source matched the requested creator or source id.")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 2

    candidates: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    source_errors = 0
    for source in sources:
        try:
            if source["kind"] == "single_video":
                metadata, archives = fetch_single_video(client, source, cutoff)
            else:
                metadata, archives = fetch_collection(client, source, cutoff)
            output["sources"].append(metadata)
            candidates.extend((source, metadata, archive) for archive in archives)
        except Exception as error:
            source_errors += 1
            output["warnings"].append(f"{source['id']}: {error}")
            if isinstance(error, RequestBudgetExceeded):
                output["warnings"].append("Bilibili request budget exhausted; remaining sources were stopped.")
                break
            if client.risk_controlled:
                output["warnings"].append("Bilibili risk control triggered; remaining source requests were stopped.")
                break

    candidates.sort(
        key=lambda item: (
            bool(args.keyword and normalized(args.keyword) in normalized(str(item[2].get("title") or ""))),
            int(item[2].get("pubdate") or 0),
        ),
        reverse=True,
    )
    successful_scans = 0
    budget_stopped = False
    for source, metadata, archive in candidates:
        if len(output["results"]) >= args.limit:
            break
        try:
            rows, warning, success = scan_video(client, source, metadata, archive, args.keyword)
        except RequestBudgetExceeded as error:
            output["warnings"].append(str(error))
            budget_stopped = True
            break
        metadata["scanned_videos"] += 1
        if success:
            successful_scans += 1
        output["results"].extend(rows)
        if warning:
            output["warnings"].append(f"{source['id']}: {warning}")
        if client.risk_controlled:
            output["warnings"].append("Bilibili risk control triggered; remaining video requests were stopped.")
            break

    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in output["results"]:
        deduped[(row["bvid"], row["deck_code"])] = row
    results = sorted(deduped.values(), key=lambda row: row["published_timestamp"], reverse=True)
    output["results"] = results[: args.limit]
    for row in output["results"]:
        row.pop("published_timestamp", None)

    output["request_metrics"] = {
        "api_requests": client.request_count,
        "request_budget": client.max_requests,
        "candidate_videos": len(candidates),
        "scanned_videos": sum(item["scanned_videos"] for item in output["sources"]),
        "successful_scans": successful_scans,
        "stopped_by_budget": budget_stopped,
        "risk_controlled": client.risk_controlled,
    }

    if args.format == "markdown":
        from format_decks import render_markdown

        print(render_markdown(output))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))

    if not output["sources"] and source_errors:
        return 2
    if candidates and successful_scans == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
