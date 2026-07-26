#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from deckstrings import validate_deck_code


def clean_name(value: Any) -> str:
    name = re.sub(r"^[#>*\-\s]+", "", str(value or "")).strip()
    name = re.sub(r"[\r\n`]+", " ", name).strip()
    return name if name else "未命名卡组"


def safe_text(value: Any) -> str:
    return re.sub(r"[\r\n]+", " ", str(value if value is not None else "")).strip()


def table_cell(value: Any) -> str:
    return safe_text(value).replace("|", "\\|") or "-"


def append_warnings(lines: list[str], payload: dict[str, Any]) -> None:
    warnings = payload.get("warnings") or []
    if warnings:
        if lines:
            lines.append("")
        lines.append("注意：")
        lines.extend(f"- {safe_text(item)}" for item in warnings)


def append_source(lines: list[str], payload: dict[str, Any]) -> None:
    source = payload.get("source")
    source_url = payload.get("source_url")
    if source or source_url:
        if lines:
            lines.append("")
        text = f"数据源：{safe_text(source)}" if source else "数据源"
        if source_url:
            text += f"（{safe_text(source_url)}）"
        lines.append(text)


def collect_decks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    decks: list[dict[str, Any]] = []
    route = payload.get("route")
    for item in payload.get("results") or []:
        if route == "deck_rankings":
            representative = item.get("representative_deck") or {}
            code = representative.get("deck_code")
            if not code or not validate_deck_code(str(code)):
                continue
            decks.append(
                {
                    "name": clean_name(
                        representative.get("zh_name") or item.get("zh_name") or representative.get("name")
                    ),
                    "code": str(code),
                    "summary": "，".join(
                        part
                        for part in [
                            f"环境胜率 {item.get('archetype_winrate')}%"
                            if item.get("archetype_winrate") is not None
                            else None,
                            f"环境样本 {item.get('popularity_games')} 场"
                            if item.get("popularity_games") is not None
                            else None,
                            f"代表构筑 {representative.get('games')} 场"
                            if representative.get("games") is not None
                            else None,
                        ]
                        if part
                    ),
                    "evidence": [payload.get("source_url")] if payload.get("source_url") else [],
                }
            )
        else:
            code = item.get("deck_code")
            if not code or not item.get("deck_code_valid", False) or not validate_deck_code(str(code)):
                continue
            details = [
                f"博主：{safe_text(item.get('creator_name'))}" if item.get("creator_name") else None,
                f"上传者：{safe_text(item.get('uploader'))}" if item.get("uploader") else None,
                f"日期：{safe_text(item.get('published_at'))[:10]}" if item.get("published_at") else None,
                f"合集：{safe_text(item.get('collection_name'))}" if item.get("collection_name") else None,
                f"播放：{item.get('views')}" if item.get("views") is not None else None,
            ]
            decks.append(
                {
                    "name": clean_name(item.get("deck_name_hint")),
                    "code": str(code),
                    "summary": "；".join(part for part in details if part),
                    "evidence": [item.get("video_url")] if item.get("video_url") else [],
                }
            )

    deduped: list[dict[str, Any]] = []
    by_code: dict[str, dict[str, Any]] = {}
    for deck in decks:
        existing = by_code.get(deck["code"])
        if existing:
            for url in deck["evidence"]:
                if url not in existing["evidence"]:
                    existing["evidence"].append(url)
            continue
        by_code[deck["code"]] = deck
        deduped.append(deck)
    return deduped


def render_decks(payload: dict[str, Any]) -> str:
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
        for url in deck["evidence"]:
            lines.append("")
            lines.append(f"来源：{url}")
    append_warnings(lines, payload)
    return "\n".join(lines)


def render_official(payload: dict[str, Any]) -> str:
    query = payload.get("query") or {}
    lines = [
        f"国服官方排行榜：{safe_text(query.get('season')) or safe_text(query.get('mode'))}",
        "",
        "| 名次 | 玩家 |",
        "| ---: | --- |",
    ]
    for item in payload.get("results") or []:
        lines.append(f"| {table_cell(item.get('position'))} | {table_cell(item.get('player'))} |")
    append_source(lines, payload)
    append_warnings(lines, payload)
    return "\n".join(lines)


def render_arena_classes(payload: dict[str, Any]) -> str:
    lines = ["竞技场职业排行", "", "| 名次 | 职业 | 胜率 |", "| ---: | --- | ---: |"]
    for item in payload.get("results") or []:
        winrate = f"{item.get('winrate')}%" if item.get("winrate") is not None else "-"
        lines.append(
            f"| {table_cell(item.get('position'))} | {table_cell(item.get('class_zh'))} | {table_cell(winrate)} |"
        )
    append_source(lines, payload)
    append_warnings(lines, payload)
    return "\n".join(lines)


def render_arena_cards(payload: dict[str, Any]) -> str:
    lines = [
        "竞技场卡牌排行",
        "",
        "| 名次 | 卡牌 | 选入胜率 | 打出胜率 | 选入率 | 更新时间 |",
        "| ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for item in payload.get("results") or []:
        lines.append(
            "| {position} | {name} | {included} | {played} | {popularity} | {updated} |".format(
                position=table_cell(item.get("position")),
                name=table_cell(item.get("name")),
                included=table_cell(item.get("included_winrate")),
                played=table_cell(item.get("winrate_when_played")),
                popularity=table_cell(item.get("included_popularity")),
                updated=table_cell(item.get("updated_at")),
            )
        )
    append_source(lines, payload)
    append_warnings(lines, payload)
    return "\n".join(lines)


def render_battlegrounds(payload: dict[str, Any]) -> str:
    lines = ["酒馆战棋流派排行"]
    for item in payload.get("results") or []:
        lines.extend(
            [
                "",
                f"{item.get('position')}. {safe_text(item.get('name'))}（Tier {safe_text(item.get('tier'))}）",
            ]
        )
        if item.get("summary"):
            lines.append(f"- 简介：{safe_text(item.get('summary'))}")
        if item.get("when_to_commit"):
            lines.append(f"- 成型条件：{safe_text(item.get('when_to_commit'))}")
        if item.get("how_to_play"):
            lines.append(f"- 玩法：{safe_text(item.get('how_to_play'))}")
        if item.get("last_updated"):
            lines.append(f"- 更新时间：{safe_text(item.get('last_updated'))}")
    append_source(lines, payload)
    append_warnings(lines, payload)
    return "\n".join(lines)


def render_markdown(payload: dict[str, Any]) -> str:
    route = payload.get("route")
    if route in {"bilibili_decks", "deck_rankings", None}:
        return render_decks(payload)
    if route == "official_player_rankings":
        return render_official(payload)
    if route == "arena_class_rankings":
        return render_arena_classes(payload)
    if route == "arena_card_rankings":
        return render_arena_cards(payload)
    if route == "battlegrounds_comp_rankings":
        return render_battlegrounds(payload)
    lines = [json.dumps(payload, ensure_ascii=False, indent=2)]
    append_warnings(lines, payload)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Hearthstone search JSON as Markdown.")
    parser.add_argument("input", nargs="?", type=Path, help="JSON file; omit to read stdin.")
    args = parser.parse_args()
    text = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
    payload = json.loads(text)
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
