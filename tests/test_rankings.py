import datetime as dt
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from search_rankings import build_deck_index, parse_timestamp, stale_warning
from test_deckstrings import STANDARD_CODE


class RankingTests(unittest.TestCase):
    def test_dot_timestamp_is_supported(self):
        parsed = parse_timestamp("2026.07.26 16:29:21")
        self.assertIsNotNone(parsed)
        self.assertIsNotNone(parsed.tzinfo)

    def test_stale_warning_uses_configured_age(self):
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).isoformat()
        self.assertIsNotNone(stale_warning([old], "test", 7))

    def test_invalid_deck_codes_are_not_indexed(self):
        index = build_deck_index(
            [
                {"name": "valid", "deckcode": STANDARD_CODE},
                {"name": "invalid", "deckcode": "not-a-deck-code"},
            ]
        )
        self.assertIn("valid", index)
        self.assertNotIn("invalid", index)


if __name__ == "__main__":
    unittest.main()
