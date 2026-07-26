#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from search_bilibili import nonnegative_int, positive_int


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCES = ("netease", "bilibili", "iyingdi", "rankings")
SOURCE_LABELS = {
    "netease": "网易大神套牌广场",
    "bilibili": "B站维护合集",
    "iyingdi": "旅法师营地赛事专题",
    "rankings": "构筑环境统计",
}


def parse_sources(value: str) -> list[str]:
    sources = [part.strip().casefold() for part in value.split(",") if part.strip()]
    unknown = [source for source in sources if source not in SOURCE_LABELS]
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown sources: {', '.join(unknown)}")
    if not sources:
        raise argparse.ArgumentTypeError("at least one source is required")
    return list(dict.fromkeys(sources))


def source_command(source: str, args: argparse.Namespace) -> list[str]:
    common = ["--keyword", args.keyword, "--limit", str(args.limit), "--format", "json"]
    if source == "netease":
        command = ["search_netease_dashen.py", *common, "--days", str(args.days)]
        if args.mode:
            command.extend(["--mode", args.mode])
        if args.class_name:
            command.extend(["--class", args.class_name])
        return command
    if source == "bilibili":
        command = ["search_bilibili.py", *common, "--days", str(args.days)]
        if args.creator:
            command.extend(["--creator", args.creator])
        return command
    if source == "iyingdi":
        command = ["search_iyingdi.py", *common, "--days", str(args.days)]
        if args.mode:
            command.extend(["--mode", args.mode])
        if args.class_name:
            command.extend(["--class", args.class_name])
        return command
    command = [
        "search_rankings.py",
        "deck",
        "--archetype",
        args.keyword,
        "--mode",
        args.mode or "standard",
        "--limit",
        str(args.limit),
        "--format",
        "json",
    ]
    if args.class_name:
        command.extend(["--class", args.class_name])
    return command


def run_source(source: str, args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    source_args = source_command(source, args)
    command = [sys.executable, str(SCRIPT_DIR / source_args[0]), *source_args[1:]]
    try:
        completed = subprocess.run(
            command,
            cwd=SCRIPT_DIR.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=args.source_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 2, {
            "route": source,
            "results": [],
            "warnings": [f"{SOURCE_LABELS[source]} timed out after {args.source_timeout} seconds."],
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        detail = (completed.stderr or completed.stdout or "no output").strip()
        return 2, {
            "route": source,
            "results": [],
            "warnings": [f"{SOURCE_LABELS[source]} returned invalid output: {detail[:300]}"],
        }
    return completed.returncode, payload


def result_count(payload: dict[str, Any]) -> int:
    return len(payload.get("results") or [])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Continuously search multiple Hearthstone deck sources. "
            "Use fallback to continue only after no result or failure; use all for cross-source research."
        )
    )
    parser.add_argument("--keyword", required=True, help="Deck or archetype keyword.")
    parser.add_argument("--creator", help="Restrict the Bilibili leg to one configured creator.")
    parser.add_argument("--class", dest="class_name")
    parser.add_argument("--mode", choices=["standard", "wild"])
    parser.add_argument("--days", type=nonnegative_int, default=30)
    parser.add_argument("--limit", type=positive_int, default=10)
    parser.add_argument(
        "--strategy",
        choices=["fallback", "all"],
        default="fallback",
        help="fallback stops at the first source with results; all queries every selected source.",
    )
    parser.add_argument(
        "--sources",
        type=parse_sources,
        default=list(DEFAULT_SOURCES),
        help="Comma-separated source order: netease,bilibili,iyingdi,rankings.",
    )
    parser.add_argument("--source-timeout", type=positive_int, default=90)
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.creator and "bilibili" not in args.sources:
        parser.error("--creator requires bilibili in --sources")

    output: dict[str, Any] = {
        "route": "multi_source_deck_search",
        "query": {
            "keyword": args.keyword,
            "creator": args.creator,
            "class": args.class_name,
            "mode": args.mode,
            "days": args.days,
            "limit": args.limit,
            "strategy": args.strategy,
            "sources": args.sources,
        },
        "attempts": [],
        "warnings": [],
    }

    for source in args.sources:
        returncode, payload = run_source(source, args)
        count = result_count(payload)
        output["attempts"].append(
            {
                "source": source,
                "source_label": SOURCE_LABELS[source],
                "status": "ok" if returncode == 0 else "failed",
                "result_count": count,
                "payload": payload,
            }
        )
        if returncode != 0:
            output["warnings"].append(
                f"{SOURCE_LABELS[source]} failed; continued to the next source."
            )
        elif count == 0:
            output["warnings"].append(
                f"{SOURCE_LABELS[source]} returned no matching deck; continued to the next source."
            )
        if args.strategy == "fallback" and count:
            break

    output["found"] = sum(item["result_count"] for item in output["attempts"])
    output["searched_sources"] = [item["source"] for item in output["attempts"]]

    if args.format == "markdown":
        from format_decks import render_markdown

        sections: list[str] = []
        for attempt in output["attempts"]:
            sections.append(f"## {attempt['source_label']}")
            sections.append("")
            sections.append(render_markdown(attempt["payload"]))
            sections.append("")
        if output["warnings"]:
            sections.append("连续查找记录：")
            sections.extend(f"- {warning}" for warning in output["warnings"])
        print("\n".join(sections).rstrip())
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["found"] else 1


if __name__ == "__main__":
    sys.exit(main())
