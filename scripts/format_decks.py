#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def clean_name(value: Any) -> str:
    name = re.sub(r"^[#>*\-\s]+", "", str(value or "")).strip()
    name = re.sub(r"[\r\n`]+", " ", name).strip()
    return name if name else "未命名卡组"


def collect_decks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    decks: list[dict[str, Any]] = []
    route = payload.get("route")
    for item in payload.get("results") or []:
        if route == "deck_rankings":
            representative = item.get("representative_deck") or {}
            code = representative.get("deck_code")
            if not code:
                continue
            decks.append(
                {
                    "name": clean_name(
                        representative.get("zh_name") or item.get("zh_name") or representative.get("name")
                    ),
                    "code": code,
                    "summary": "，".join(
                        part
                        for part in [
                            f"环境胜率 {item.get('archetype_winrate')}%"
                            if item.get("archetype_winrate") is not None
                            else None,
                            f"代表构筑 {representative.get('games')} 场"
                            if representative.get("games") is not None
                            else None,
                        ]
                        if part
                    ),
                    "source": payload.get("source"),
                    "url": None,
                }
            )
        else:
            code = item.get("deck_code")
            if not code or not item.get("deck_code_valid", True):
                continue
            decks.append(
                {
                    # The description heading is source evidence. Preserve it verbatim
                    # instead of asking the model or the video title to rename the deck.
                    "name": clean_name(item.get("deck_name_hint")),
                    "code": code,
                    "summary": "，".join(
                        part
                        for part in [
                            item.get("creator_name"),
                            item.get("published_at", "")[:10] or None,
                            f"{item.get('views')} 播放" if item.get("views") is not None else None,
                        ]
                        if part
                    ),
                    "source": item.get("collection_name"),
                    "url": item.get("video_url"),
                }
            )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for deck in decks:
        if deck["code"] in seen:
            continue
        seen.add(deck["code"])
        deduped.append(deck)
    return deduped


def render_markdown(payload: dict[str, Any]) -> str:
    decks = collect_decks(payload)
    lines: list[str] = []
    if not decks:
        lines.append("没有找到可复制的有效卡组代码。")
    for index, deck in enumerate(decks):
        if index:
            lines.append("")
        if deck["summary"]:
            lines.append(f"{deck['name']}（{deck['summary']}）")
            lines.append("")
        lines.extend(
            [
                "```text",
                f"###{deck['name']}",
                deck["code"],
                "```",
            ]
        )
        if deck["url"]:
            lines.append("")
            lines.append(f"来源：{deck['url']}")
    warnings = payload.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("注意：" + "；".join(str(item) for item in warnings))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Hearthstone search JSON as copyable Markdown.")
    parser.add_argument("input", nargs="?", type=Path, help="JSON file; omit to read stdin.")
    args = parser.parse_args()
    text = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
    payload = json.loads(text)
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
