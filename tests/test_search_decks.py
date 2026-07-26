import argparse
import sys
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import search_decks as module


class ContinuousSearchTests(unittest.TestCase):
    def test_fallback_continues_after_empty_result(self):
        empty = (0, {"route": "netease_dashen_decks", "results": [], "warnings": []})
        found = (
            0,
            {
                "route": "bilibili_decks",
                "results": [{"deck_code": "code"}],
                "warnings": [],
            },
        )
        with mock.patch.object(module, "run_source", side_effect=[empty, found]) as run:
            with mock.patch("builtins.print"):
                exit_code = module.main(
                    [
                        "--keyword",
                        "测试卡组",
                        "--sources",
                        "netease,bilibili,iyingdi",
                    ]
                )
        self.assertEqual(exit_code, 0)
        self.assertEqual(run.call_count, 2)

    def test_fallback_continues_after_source_failure(self):
        failed = (2, {"route": "netease", "results": [], "warnings": ["failed"]})
        found = (0, {"route": "iyingdi_tournament_decks", "results": [{}], "warnings": []})
        with mock.patch.object(module, "run_source", side_effect=[failed, found]) as run:
            with mock.patch("builtins.print"):
                exit_code = module.main(
                    [
                        "--keyword",
                        "测试卡组",
                        "--sources",
                        "netease,iyingdi",
                    ]
                )
        self.assertEqual(exit_code, 0)
        self.assertEqual(run.call_count, 2)

    def test_all_queries_every_selected_source(self):
        response = (0, {"route": "test", "results": [{}], "warnings": []})
        with mock.patch.object(module, "run_source", return_value=response) as run:
            with mock.patch("builtins.print"):
                exit_code = module.main(
                    [
                        "--keyword",
                        "控制牧",
                        "--strategy",
                        "all",
                        "--sources",
                        "netease,bilibili,rankings",
                    ]
                )
        self.assertEqual(exit_code, 0)
        self.assertEqual(run.call_count, 3)

    def test_source_commands_preserve_semantic_filters(self):
        args = argparse.Namespace(
            keyword="控制牧",
            creator=None,
            class_name="牧师",
            mode="standard",
            days=30,
            limit=5,
        )
        self.assertIn("search_netease_dashen.py", module.source_command("netease", args))
        self.assertIn("--archetype", module.source_command("rankings", args))


if __name__ == "__main__":
    unittest.main()
