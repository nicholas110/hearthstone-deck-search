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


if __name__ == "__main__":
    unittest.main()
