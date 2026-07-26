import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from deckstrings import DeckstringError, parse_deckstring, validate_deck_code


STANDARD_CODE = (
    "AAECAanlBwbNngbDgweRxgek2QeR2wf/3wcMs4cH8ZEH+psH9aUHi7EH+cMHhsQHksQHk9oHrdoH+d4HhuAHAAA="
)
SIDEBOARD_CODE = (
    "AAEBAf0GDOfLAvjQAo+CA52pA5PkA4T7A4+fBOWwBI21BJfvBP3EBcSiBg7cCvLQAvr+ApXNA9fOA8HRA876BcSe"
    "BqOgBsO4BsnkBtGCB4SZB6WtBwABA78W/cQF+7AD/cQFk+QD/cQFAAA="
)


class DeckstringTests(unittest.TestCase):
    def test_parses_current_standard_code(self):
        parsed = parse_deckstring(STANDARD_CODE)
        self.assertEqual(parsed.version, 1)
        self.assertEqual(parsed.format_type, 2)
        self.assertEqual(len(parsed.heroes), 1)
        self.assertGreater(len(parsed.cards), 0)

    def test_parses_sideboards(self):
        parsed = parse_deckstring(SIDEBOARD_CODE)
        self.assertEqual(len(parsed.sideboards), 3)

    def test_rejects_base64_that_is_not_a_deckstring(self):
        self.assertFalse(validate_deck_code("bm90LWEtZGVja3N0cmluZw=="))

    def test_rejects_truncated_code(self):
        with self.assertRaises(DeckstringError):
            parse_deckstring(STANDARD_CODE[:-12])

    def test_rejects_empty_code(self):
        self.assertFalse(validate_deck_code(""))


if __name__ == "__main__":
    unittest.main()
