"""Colours live in ui/tokens.css only: raw colour literals in ui/*.html may only go down."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = 39   # setup's coffee-cup SVG, its cursor arrow and one canvas stroke; lower it when you remove one
RAW = re.compile(r'(?<![&\w])#[0-9a-fA-F]{3,8}\b|\brgba?\(\s*[\d.]|\bhsla?\(')


class DesignRatchetTests(unittest.TestCase):
    def test_pages_use_colour_tokens(self):
        found = {p.name: len(RAW.findall(p.read_text())) for p in sorted((ROOT / 'ui').glob('*.html'))}
        self.assertLessEqual(sum(found.values()), BASELINE, f'{found}: use a token from ui/tokens.css')


if __name__ == '__main__':
    unittest.main()
