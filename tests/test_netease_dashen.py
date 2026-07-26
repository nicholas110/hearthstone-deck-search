import json
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import search_netease_dashen as module
from test_deckstrings import STANDARD_CODE


class FakeHeaders:
    def get(self, name, default=None):
        return {"Last-Modified": "Sun, 26 Jul 2026 10:30:58 GMT"}.get(name, default)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.headers = FakeHeaders()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class ClientTests(unittest.TestCase):
    def test_fetches_public_dataset_without_authentication(self):
        payload = {"data": [{"title": "控制牧"}], "count": 1}
        with mock.patch.object(
            module.urllib.request, "urlopen", return_value=FakeResponse(payload)
        ) as request:
            rows, headers = module.NeteaseDashenClient(
                timeout=1, attempts=1, backoff=[0]
            ).fetch("https://example.test/decks.json")
        sent = request.call_args.args[0]
        self.assertEqual(rows[0]["title"], "控制牧")
        self.assertNotIn("Authorization", sent.headers)
        self.assertEqual(headers["last_modified"], "Sun, 26 Jul 2026 10:30:58 GMT")

    def test_http_429_is_retried(self):
        error = urllib.error.HTTPError(
            "https://example.test/decks.json", 429, "rate", {}, None
        )
        with mock.patch.object(
            module.urllib.request,
            "urlopen",
            side_effect=[error, FakeResponse({"data": [], "count": 0})],
        ):
            rows, _ = module.NeteaseDashenClient(
                timeout=1, attempts=2, backoff=[0]
            ).fetch("https://example.test/decks.json")
        self.assertEqual(rows, [])


class FilteringTests(unittest.TestCase):
    def make_item(self, **overrides):
        item = {
            "cipher": STANDARD_CODE,
            "deckString": {"liupai": "控制牧"},
            "osh": 10120,
            "title": "=控制牧3.0=",
            "hot": 0,
            "sl": 0.612,
            "game_mode": "标准",
            "md5key": "record-1",
            "time": datetime.now(module.CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S"),
            "job": "09",
            "strategy": "",
        }
        item.update(overrides)
        return item

    def test_matches_keyword_class_mode_and_date(self):
        cutoff = datetime.now(module.CHINA_TZ) - timedelta(days=7)
        self.assertTrue(
            module.item_matches(
                self.make_item(),
                keyword="控制牧",
                job="09",
                mode="standard",
                cutoff=cutoff,
            )
        )
        self.assertFalse(
            module.item_matches(
                self.make_item(),
                keyword="控制牧",
                job="08",
                mode="standard",
                cutoff=cutoff,
            )
        )

    def test_structured_names_are_used_without_model_invention(self):
        title_result = module.slim_deck(self.make_item())
        archetype_result = module.slim_deck(self.make_item(title="36"))
        custom_result = module.slim_deck(self.make_item(title="自定义 牧师"))
        unnamed_result = module.slim_deck(
            self.make_item(title="", deckString={"liupai": ""})
        )
        self.assertEqual(title_result["deck_name"], "=控制牧3.0=")
        self.assertEqual(title_result["deck_name_source"], "netease_title")
        self.assertEqual(archetype_result["deck_name"], "控制牧")
        self.assertEqual(archetype_result["deck_name_source"], "netease_archetype")
        self.assertEqual(custom_result["deck_name"], "控制牧")
        self.assertEqual(custom_result["deck_name_source"], "netease_archetype")
        self.assertEqual(unnamed_result["deck_name"], "未命名卡组")
        self.assertEqual(unnamed_result["deck_name_source"], "fallback_unnamed")

    def test_invalid_deck_code_is_excluded(self):
        self.assertIsNone(module.slim_deck(self.make_item(cipher="not-a-deck")))

    def test_winrate_placeholder_is_not_reported(self):
        self.assertIsNone(module.winrate_percent(0.00001))
        self.assertEqual(module.winrate_percent(0.612), 61.2)

    def test_missing_cost_sorts_last_in_both_directions(self):
        missing = {"dust": None}
        self.assertEqual(module.sort_key(missing, "cost-low"), float("inf"))
        self.assertEqual(module.sort_key(missing, "cost-high"), -1)


if __name__ == "__main__":
    unittest.main()
