#!/usr/bin/env python3
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass


SUPPORTED_VERSION = 1
SUPPORTED_FORMATS = {1, 2, 3, 4}
MAX_SECTION_ENTRIES = 200


class DeckstringError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedDeckstring:
    version: int
    format_type: int
    heroes: tuple[int, ...]
    cards: tuple[tuple[int, int], ...]
    sideboards: tuple[tuple[int, int, int], ...]


class VarintReader:
    def __init__(self, data: bytes):
        self.data = data
        self.position = 0

    def read_byte(self) -> int:
        if self.position >= len(self.data):
            raise DeckstringError("unexpected end of deckstring")
        value = self.data[self.position]
        self.position += 1
        return value

    def read_varint(self) -> int:
        result = 0
        shift = 0
        for _ in range(10):
            value = self.read_byte()
            result |= (value & 0x7F) << shift
            if not value & 0x80:
                return result
            shift += 7
        raise DeckstringError("varint is too long")

    def read_count(self, label: str) -> int:
        value = self.read_varint()
        if value > MAX_SECTION_ENTRIES:
            raise DeckstringError(f"{label} count is unreasonable: {value}")
        return value

    @property
    def remaining(self) -> int:
        return len(self.data) - self.position


def _positive_id(reader: VarintReader, label: str) -> int:
    value = reader.read_varint()
    if value <= 0:
        raise DeckstringError(f"{label} must be positive")
    return value


def parse_deckstring(code: str) -> ParsedDeckstring:
    if not isinstance(code, str) or not code.strip():
        raise DeckstringError("deckstring is empty")
    code = code.strip()
    try:
        padded = code + "=" * (-len(code) % 4)
        decoded = base64.b64decode(padded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise DeckstringError("deckstring is not valid Base64") from error

    reader = VarintReader(decoded)
    if reader.read_byte() != 0:
        raise DeckstringError("reserved header byte is not zero")
    version = reader.read_varint()
    if version != SUPPORTED_VERSION:
        raise DeckstringError(f"unsupported deckstring version: {version}")
    format_type = reader.read_varint()
    if format_type not in SUPPORTED_FORMATS:
        raise DeckstringError(f"unsupported format type: {format_type}")

    hero_count = reader.read_count("hero")
    if hero_count != 1:
        raise DeckstringError(f"expected exactly one hero, got {hero_count}")
    heroes = tuple(_positive_id(reader, "hero DBF ID") for _ in range(hero_count))

    cards: list[tuple[int, int]] = []
    for copies in (1, 2):
        count = reader.read_count(f"{copies}-copy card")
        for _ in range(count):
            cards.append((_positive_id(reader, "card DBF ID"), copies))

    extra_count = reader.read_count("multi-copy card")
    for _ in range(extra_count):
        card_id = _positive_id(reader, "card DBF ID")
        copies = reader.read_varint()
        if copies < 3 or copies > 99:
            raise DeckstringError(f"invalid card count: {copies}")
        cards.append((card_id, copies))

    if not cards:
        raise DeckstringError("deckstring contains no cards")
    if len(cards) > MAX_SECTION_ENTRIES or sum(count for _, count in cards) > 100:
        raise DeckstringError("deck card count is unreasonable")

    sideboards: list[tuple[int, int, int]] = []
    if reader.remaining:
        marker = reader.read_byte()
        if marker not in {0, 1}:
            raise DeckstringError(f"invalid sideboard marker: {marker}")
        if marker == 1:
            for copies in (1, 2):
                count = reader.read_count(f"{copies}-copy sideboard")
                for _ in range(count):
                    card_id = _positive_id(reader, "sideboard card DBF ID")
                    owner_id = _positive_id(reader, "sideboard owner DBF ID")
                    sideboards.append((card_id, copies, owner_id))
            extra_count = reader.read_count("multi-copy sideboard")
            for _ in range(extra_count):
                card_id = _positive_id(reader, "sideboard card DBF ID")
                copies = reader.read_varint()
                owner_id = _positive_id(reader, "sideboard owner DBF ID")
                if copies < 3 or copies > 99:
                    raise DeckstringError(f"invalid sideboard count: {copies}")
                sideboards.append((card_id, copies, owner_id))

    if reader.remaining:
        raise DeckstringError(f"unexpected trailing bytes: {reader.remaining}")

    return ParsedDeckstring(
        version=version,
        format_type=format_type,
        heroes=heroes,
        cards=tuple(cards),
        sideboards=tuple(sideboards),
    )


def validate_deck_code(code: str) -> bool:
    try:
        parse_deckstring(code)
        return True
    except (DeckstringError, TypeError):
        return False
