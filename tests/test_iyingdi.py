import json
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import search_iyingdi as module
from test_deckstrings import STANDARD_CODE


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class ClientTests(unittest.TestCase):
    def make_client(self, attempts=3, max_requests=10):
        return module.IyingdiClient(
            api_base="https://api.example.test",
            timeout=1,
            attempts=attempts,
            backoff=[0],
            max_requests=max_requests,
            request_delay=0,
        )

    def test_event_list_uses_public_browser_headers(self):
        payload = {
            "success": True,
            "sets": [
                {
                    "set": {
                        "id": 123,
                        "name": "测试赛事",
                        "format": "标准",
                        "decks": 8,
                    }
                }
            ],
        }
        with mock.patch.object(
            module.urllib.request, "urlopen", return_value=FakeResponse(payload)
        ) as request:
            events = self.make_client().list_events(0, 20)
        sent = request.call_args.args[0]
        self.assertEqual(events[0]["name"], "测试赛事")
        self.assertEqual(sent.method, "POST")
        self.assertEqual(sent.headers["Origin"], "https://www.iyingdi.com")
        self.assertEqual(sent.headers["X-requested-with"], "XMLHttpRequest")
        self.assertIn(b"deck_size=1", sent.data)

    def test_event_decks_follow_pagination(self):
        first = {
            "success": True,
            "list": [
                {"deck": {"id": 1}},
                {"deck": {"id": 2}},
            ],
        }
        second = {"success": True, "list": [{"deck": {"id": 3}}]}
        with mock.patch.object(
            module.urllib.request,
            "urlopen",
            side_effect=[FakeResponse(first), FakeResponse(second)],
        ) as request:
            decks = self.make_client().event_decks(123, size=2)
        self.assertEqual([deck["id"] for deck in decks], [1, 2, 3])
        self.assertIn("page=1", request.call_args_list[1].args[0].full_url)

    def test_http_429_is_retried(self):
        error = urllib.error.HTTPError(
            "https://api.example.test", 429, "rate", {}, None
        )
        response = FakeResponse({"success": True, "sets": []})
        with mock.patch.object(
            module.urllib.request,
            "urlopen",
            side_effect=[error, response],
        ):
            result = self.make_client().list_events(0, 1)
        self.assertEqual(result, [])

    def test_request_budget_is_enforced(self):
        client = self.make_client(max_requests=1)
        response = FakeResponse({"success": True, "sets": []})
        with mock.patch.object(
            module.urllib.request, "urlopen", return_value=response
        ):
            client.list_events(0, 1)
            with self.assertRaises(module.RequestBudgetExceeded):
                client.list_events(1, 1)


class FilteringTests(unittest.TestCase):
    def test_event_filter_uses_name_mode_and_date(self):
        recent = {
            "id": 1,
            "name": "黄金赛长沙站标准组八强",
            "format": "标准",
            "begin": datetime.now(module.CHINA_TZ).strftime("%Y-%m-%d"),
        }
        cutoff = datetime.now(module.CHINA_TZ) - timedelta(days=30)
        self.assertTrue(
            module.event_matches(
                recent,
                event_query="长沙",
                mode="standard",
                cutoff=cutoff,
            )
        )
        self.assertFalse(
            module.event_matches(
                recent,
                event_query="夏季预选赛",
                mode="standard",
                cutoff=cutoff,
            )
        )

    def test_deck_filter_is_scoped_to_structured_fields(self):
        deck = {
            "name": "控制牧",
            "player": "测试选手",
            "setName": "黄金赛",
            "faction": "Priest",
            "format": "标准",
        }
        self.assertTrue(
            module.deck_matches(
                deck,
                player="测试",
                class_name="Priest",
                mode="standard",
                keyword="控制牧",
            )
        )
        self.assertFalse(
            module.deck_matches(
                deck,
                player="另一位",
                class_name="Priest",
                mode="standard",
                keyword=None,
            )
        )

    def test_structured_deck_name_and_code_are_preserved(self):
        event = {
            "id": 123,
            "name": "测试赛事",
            "format": "标准",
            "begin": "2026-07-22",
        }
        deck = {
            "id": 456,
            "name": "原始卡组名称",
            "player": "测试选手",
            "faction": "Priest",
            "format": "标准",
            "code": STANDARD_CODE,
        }
        result = module.slim_deck(deck, event)
        self.assertEqual(result["deck_name"], "原始卡组名称")
        self.assertEqual(result["deck_name_source"], "iyingdi_structured_field")
        self.assertTrue(result["deck_code_valid"])

    def test_invalid_deck_code_is_excluded(self):
        self.assertIsNone(
            module.slim_deck(
                {"id": 1, "code": "not-a-deck"},
                {"id": 2, "name": "测试"},
            )
        )

    def test_class_aliases(self):
        self.assertEqual(module.normalize_class("牧师"), "Priest")
        self.assertEqual(module.normalize_class("Death Knight"), "Deathknight")


if __name__ == "__main__":
    unittest.main()
