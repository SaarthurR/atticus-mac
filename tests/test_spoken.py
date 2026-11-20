"""Real-looking answer fixtures; Swift execution stays in the Tart VM."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import atticus
from tests import run_swift

FIXTURES = [
    ('See this:\n```graph\n{"type":"bar","secret":42}\n```\nThen continue.', 'See this: Graph on screen. Then continue.'),
    ('```graph\n{"type":', 'Graph on screen.'),
    ("## Result\n1. **First**, subtract two.\n- Then divide.", "Result First, subtract two. Then divide."),
    ("For x^2 ≤ 9, use √x × 2.", "For x squared less than or equal to 9, use square root of x times 2."),
    ("Multiply 6 * 7, or a*b.", "Multiply 6 times 7, or a times b."),
    ("*Note. More.*", "Note. More."),
    (r"The ratio is $\frac{a}{b}$ and $\sqrt{x}$.", "The ratio is a over b and square root of x."),
    (r"Use $\alpha$ and keep AT&T and snake_case.", "Use alpha and keep AT&T and snake_case."),
    ("Use a/b, then x^3 and x^4.", "Use a over b, then x cubed and x to the power of 4."),
    ("Keep x < 5 and y > 2.", "Keep x less than 5 and y greater than 2."),
    ("**Note. This more.**", "Note. This more."),
    ("Check if x < 5", "Check if x less than 5"),
    ("Use x<5, y>2 and z ≥ 3.", "Use x less than 5, y greater than 2 and z greater than or equal to 3."),
    ("<b>Result</b><br/>x<sub>2</sub> is two.", "Result x 2 is two."),
    ("Try this:\n```python\nprint('secret.')\n```\nIt prints a greeting.", "Try this: It prints a greeting."),
    ("Try this:\n```python\nprint('secret.", "Try this:"),
    ("Run `secret()` after checking.", "Run after checking."),
    ("Read [the guide](https://example.com/a). Visit https://example.com/private?q=1 next.", "Read the guide. Visit next."),
    ("Pay $5 or $10, e.g. by card. The API is ready.", "Pay $5 or $10, e.g. by card. The API is ready."),
    ("See ![diagram](https://example.com/image) or <https://example.com> next.", "See diagram or next."),
    ("Open file:///tmp/private or www.example.com next.", "Open or next."),
    ("Keep and/or and https://example.com/code out.", "Keep and/or and out."),
    ("The value is \\(x^{2}\\) or \\[x \\leq 4\\].", "The value is x squared or x less than or equal to 4."),
]

class SpokenTests(unittest.TestCase):
    def test_answer_fixtures(self):
        source = (Path(__file__).resolve().parents[1] / 'Atticus.swift').read_text()
        helpers = source[source.index('func spoken('):source.index('// Read-aloud uses')]
        checks = '\n'.join(
            f'precondition(readAloudText({json.dumps(text, ensure_ascii=False)}).components(separatedBy: .whitespacesAndNewlines).filter {{ !$0.isEmpty }}.joined(separator: " ") == {json.dumps(expected, ensure_ascii=False)}, {json.dumps(text, ensure_ascii=False)})'
            for text, expected in FIXTURES)
        checks += '\n' + '\n'.join(
            'do { let text = ' + json.dumps(text, ensure_ascii=False) + '; var q = SpeechSentences(); var heard: [String] = []; '
            + 'for end in text.indices.dropFirst() { heard += q.take(readAloudText(String(text[..<end]))) }; '
            + 'heard += q.take(readAloudText(text), final: true); precondition(heard.joined(separator: " ") == '
            + json.dumps(expected, ensure_ascii=False) + ', heard.joined(separator: " ")) }'
            for text, expected in FIXTURES)
        checks += '\nvar lines = SpeechSentences(); precondition(lines.take(readAloudText("First line\\n")) == ["First line"]); precondition(lines.take(readAloudText("First line\\nSecond line"), final: true) == ["Second line"])'
        print(run_swift(self, 'import Foundation\n' + helpers + checks + '\nprint("spoken fixtures: OK")').strip())

    def test_prompt_is_voice_only(self):
        with patch.object(atticus, 'pref', side_effect=lambda key, default: False if key == 'speak' else default):
            quiet = atticus.system_prompt(atticus.NEVER)
        with patch.object(atticus, 'pref', side_effect=lambda key, default: True if key == 'speak' else default):
            aloud = atticus.system_prompt(atticus.NEVER)
        self.assertEqual(aloud, quiet + atticus.READ_ALOUD)
        self.assertLessEqual(len(aloud), 10000)

    def test_toggle_discards_the_warm_prompt_and_only_off_stops_speech(self):
        source = (Path(__file__).resolve().parents[1] / 'Atticus.swift').read_text()
        toggle = next(line for line in source.splitlines() if 'if k == "speak"' in line)
        run_swift(self, 'import Foundation\n' + '\n'.join([
            'class FakeApp { var warmStops = 0, speechStops = 0; func unwarm() { warmStops += 1 }; func shush() { speechStops += 1 } }',
            'let app = FakeApp(), k = "speak"',
            'for value in [true, false] { let v: Any = value', toggle, '}',
            'precondition(app.warmStops == 2 && app.speechStops == 1)',
        ]))
