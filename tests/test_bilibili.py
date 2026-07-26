import io
import json
import sys
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import search_bilibili as module
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


def video_fixture(bvid="BV1tFge6qEAA", description=None, season_id=123):
    return {
        "bvid": bvid,
        "title": "测试视频",
        "desc": description or f"### lvge 卡德加法\n{STANDARD_CODE}",
        "pubdate": 1_780_000_000,
        "owner": {"mid": 42, "name": "上传者"},
        "stat": {"view": 1234},
        "ugc_season": {
            "id": season_id,
            "mid": 42,
            "title": "测试合集",
            "sections": [
                {
                    "episodes": [
                        {
                            "bvid": bvid,
                            "title": "测试视频",
                            "arc": {"pubdate": 1_780_000_000},
                        }
                    ]
                }
            ],
        },
    }


class FakeClient:
    def __init__(self, videos):
        self.videos = videos

    def video(self, bvid):
        return self.videos[bvid]


class ExtractionTests(unittest.TestCase):
    def test_heading_name_is_preserved(self):
        deck = module.extract_decks(f"### lvge 卡德加法\n{STANDARD_CODE}")[0]
        self.assertEqual(deck["deck_name_hint"], "lvge 卡德加法")
        self.assertEqual(deck["deck_name_source"], "description_heading")
        self.assertTrue(deck["deck_code_valid"])

    def test_inline_heading_is_supported(self):
        deck = module.extract_decks(f"### lvge 卡德加法 {STANDARD_CODE}")[0]
        self.assertEqual(deck["deck_name_hint"], "lvge 卡德加法")

    def test_metadata_line_does_not_replace_explicit_heading(self):
        deck = module.extract_decks(f"### 正确名称\n作者：某某\n{STANDARD_CODE}")[0]
        self.assertEqual(deck["deck_name_hint"], "正确名称")

    def test_missing_name_stays_missing(self):
        deck = module.extract_decks(f"视频每期卡组都会更新\n{STANDARD_CODE}")[0]
        self.assertIsNone(deck["deck_name_hint"])

    def test_keyword_is_scoped_per_deck(self):
        first = {
            "deck_name_hint": "控制牧",
            "description_excerpt": "控制牧",
        }
        second = {
            "deck_name_hint": "任务法",
            "description_excerpt": "任务法",
        }
        self.assertTrue(module.deck_matches_keyword(first, "两套卡组", "控制牧", 2))
        self.assertFalse(module.deck_matches_keyword(second, "两套卡组含控制牧", "控制牧", 2))


class SourceTests(unittest.TestCase):
    def test_embedded_collection_uses_seed_bvid(self):
        source = {
            "id": "test",
            "kind": "video_collection",
            "entry_url": "https://space.bilibili.com/42/lists/123?type=season",
            "seed_bvid": "BV1tFge6qEAA",
            "creator_name": "测试",
        }
        resolved, archives = module.resolve_collection(
            FakeClient({"BV1tFge6qEAA": video_fixture()}), source
        )
        self.assertEqual(resolved["resolution"], "embedded_ugc_season")
        self.assertEqual(archives[0]["bvid"], "BV1tFge6qEAA")

    def test_seed_must_match_configured_season(self):
        source = {
            "id": "test",
            "kind": "video_collection",
            "entry_url": "https://space.bilibili.com/42/lists/999?type=season",
            "seed_bvid": "BV1tFge6qEAA",
            "creator_name": "测试",
        }
        with self.assertRaisesRegex(ValueError, "season mismatch"):
            module.resolve_collection(FakeClient({"BV1tFge6qEAA": video_fixture()}), source)

    def test_single_video_does_not_expand_collection(self):
        source = {
            "id": "one",
            "kind": "single_video",
            "entry_url": "https://www.bilibili.com/video/BV1tFge6qEAA/",
            "creator_name": "测试",
        }
        metadata, archives = module.fetch_single_video(
            FakeClient({"BV1tFge6qEAA": video_fixture()}), source, None
        )
        self.assertEqual(metadata["resolution"], "single_video")
        self.assertEqual(len(archives), 1)


class ClientTests(unittest.TestCase):
    def make_client(self, attempts=4, max_requests=10):
        return module.BilibiliClient(
            timeout=1,
            attempts=attempts,
            backoff=[0],
            max_requests=max_requests,
            request_delay=0,
        )

    def test_transient_api_code_is_retried(self):
        responses = [
            FakeResponse({"code": -500, "message": "busy"}),
            FakeResponse({"code": 0, "data": {"ok": True}}),
        ]
        with mock.patch.object(module.urllib.request, "urlopen", side_effect=responses):
            result = self.make_client().get_json("/test", {})
        self.assertEqual(result, {"ok": True})

    def test_risk_control_stops_immediately(self):
        response = FakeResponse({"code": -352, "message": "-352"})
        with mock.patch.object(module.urllib.request, "urlopen", return_value=response) as request:
            with self.assertRaises(module.BilibiliApiError):
                self.make_client().get_json("/test", {})
        self.assertEqual(request.call_count, 1)

    def test_http_429_is_retried(self):
        error = urllib.error.HTTPError("https://example.test", 429, "rate", {}, None)
        response = FakeResponse({"code": 0, "data": {"ok": True}})
        with mock.patch.object(module.urllib.request, "urlopen", side_effect=[error, response]):
            result = self.make_client().get_json("/test", {})
        self.assertTrue(result["ok"])

    def test_request_budget_is_enforced(self):
        response = FakeResponse({"code": 0, "data": {}})
        client = self.make_client(attempts=1, max_requests=1)
        with mock.patch.object(module.urllib.request, "urlopen", return_value=response):
            client.get_json("/one", {})
            with self.assertRaises(module.RequestBudgetExceeded):
                client.get_json("/two", {})


class CliTests(unittest.TestCase):
    def test_negative_days_is_rejected(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            module.build_parser().parse_args(["--days", "-1"])

    def test_zero_limit_is_rejected(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            module.build_parser().parse_args(["--limit", "0"])

    def test_all_source_failures_return_nonzero(self):
        config = {
            "default_days": 30,
            "request_timeout_seconds": 1,
            "retry_max_attempts": 1,
            "retry_backoff_seconds": [0],
            "max_api_requests": 2,
            "request_delay_seconds": 0,
            "sources": [
                {
                    "id": "broken",
                    "platform": "bilibili",
                    "kind": "single_video",
                    "entry_url": "https://www.bilibili.com/video/BV1tFge6qEAA/",
                    "creator_name": "测试",
                    "enabled": True,
                }
            ],
        }
        with (
            mock.patch.object(module, "load_config", return_value=config),
            mock.patch.object(module.BilibiliClient, "video", side_effect=RuntimeError("offline")),
            mock.patch.object(sys, "argv", ["search_bilibili.py"]),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(module.main(), 2)


if __name__ == "__main__":
    unittest.main()
