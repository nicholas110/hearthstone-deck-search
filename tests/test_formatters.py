import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from format_decks import render_markdown
from test_deckstrings import STANDARD_CODE


class FormatterTests(unittest.TestCase):
    def test_bilibili_name_and_source_details_are_preserved(self):
        output = render_markdown(
            {
                "route": "bilibili_decks",
                "results": [
                    {
                        "deck_name_hint": "lvge 卡德加法",
                        "deck_code": STANDARD_CODE,
                        "deck_code_valid": True,
                        "creator_name": "驴鸽",
                        "uploader": "五香雷奥丶",
                        "published_at": "2026-07-24T00:00:00+08:00",
                        "collection_name": "驴鸽直播切片",
                        "views": 100,
                        "video_url": "https://www.bilibili.com/video/BV1tFge6qEAA/",
                    }
                ],
                "warnings": [],
            }
        )
        self.assertIn("###lvge 卡德加法", output)
        self.assertIn("上传者：五香雷奥丶", output)
        self.assertIn("合集：驴鸽直播切片", output)

    def test_invalid_ranking_code_is_not_rendered(self):
        output = render_markdown(
            {
                "route": "deck_rankings",
                "results": [
                    {
                        "zh_name": "测试",
                        "representative_deck": {
                            "zh_name": "测试",
                            "deck_code": "not-a-deck-code",
                        },
                    }
                ],
            }
        )
        self.assertNotIn("not-a-deck-code", output)

    def test_official_markdown(self):
        output = render_markdown(
            {
                "route": "official_player_rankings",
                "query": {"season": "测试赛季"},
                "results": [{"position": 1, "player": "玩家"}],
            }
        )
        self.assertIn("| 1 | 玩家 |", output)

    def test_arena_and_battlegrounds_markdown(self):
        arena = render_markdown(
            {
                "route": "arena_class_rankings",
                "results": [{"position": 1, "class_zh": "法师", "winrate": 52.3}],
            }
        )
        battlegrounds = render_markdown(
            {
                "route": "battlegrounds_comp_rankings",
                "results": [{"position": 1, "name": "机械", "tier": 1}],
            }
        )
        self.assertIn("法师", arena)
        self.assertIn("机械", battlegrounds)

    def test_iyingdi_tournament_players_are_not_collapsed_by_code(self):
        base = {
            "deck_name": "控制牧",
            "deck_code": STANDARD_CODE,
            "deck_code_valid": True,
            "event_id": 123,
            "event_name": "测试赛事",
            "event_url": "https://example.test/event",
            "class_zh": "牧师",
            "format": "标准",
        }
        output = render_markdown(
            {
                "route": "iyingdi_tournament_decks",
                "results": [
                    {**base, "player": "选手甲", "deck_id": 1},
                    {**base, "player": "选手乙", "deck_id": 2},
                ],
            }
        )
        self.assertEqual(output.count("###控制牧"), 2)
        self.assertIn("选手：选手甲", output)
        self.assertIn("选手：选手乙", output)

    def test_iyingdi_event_list_markdown(self):
        output = render_markdown(
            {
                "route": "iyingdi_events",
                "events": [
                    {
                        "begin": "2026-07-22",
                        "event_name": "夏季预选赛",
                        "event_url": "https://example.test/event",
                        "format": "标准",
                        "deck_count": 64,
                    }
                ],
            }
        )
        self.assertIn("夏季预选赛", output)
        self.assertIn("| 2026-07-22 |", output)

    def test_netease_dashen_deck_is_copyable(self):
        output = render_markdown(
            {
                "route": "netease_dashen_decks",
                "source_url": "https://example.test/decks",
                "results": [
                    {
                        "deck_name": "控制牧",
                        "deck_code": STANDARD_CODE,
                        "deck_code_valid": True,
                        "class_zh": "牧师",
                        "format": "标准",
                        "published_at": "2026-07-26T12:00:00+08:00",
                        "dust": 10120,
                        "winrate": 61.2,
                    }
                ],
            }
        )
        self.assertIn("###控制牧", output)
        self.assertIn("胜率：61.2%", output)
        self.assertIn("https://example.test/decks", output)


if __name__ == "__main__":
    unittest.main()
