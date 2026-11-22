"""Ideas when I'm away: the once-a-day timing rule, its Settings switch and its anonymous count. No app, window or user settings."""
from pathlib import Path
import unittest
from unittest.mock import patch

import atticus
from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'Atticus.swift').read_text()


class IdeaTests(unittest.TestCase):
    def test_once_a_day_after_a_day_without_an_ask_and_never_when_off(self):
        rule = SOURCE[SOURCE.index('    static let ideas'):SOURCE.index('    func idea(_ i: Int)')]
        out = run_swift(self, 'import Foundation\nenum App {\n' + rule + '''}
let now = Date(), ago = { (h: Double) in now.addingTimeInterval(-h * 3600) }
precondition(App.ideaDue(now: now, lastAsk: ago(25), lastShown: .distantPast, on: true))       // a day idle, none shown yet
precondition(!App.ideaDue(now: now, lastAsk: ago(23), lastShown: .distantPast, on: true))      // asked within the day
precondition(!App.ideaDue(now: now, lastAsk: ago(48), lastShown: ago(23), on: true))           // already shown today
precondition(App.ideaDue(now: now, lastAsk: ago(48), lastShown: ago(24), on: true))            // the next day
precondition(!App.ideaDue(now: now, lastAsk: .distantPast, lastShown: .distantPast, on: false)) // the switch is off
precondition(App.ideas.count >= 10 && Set(App.ideas).count == App.ideas.count && App.ideas.allSatisfy { $0.count <= 45 })
print("ok")
''')
        self.assertIn('ok', out)
        check = SOURCE[SOURCE.index('func checkIdea()'):SOURCE.index('{ _ in checkIdea() }')]
        for need in ('on: Prefs.bool("comeBack")', 'Prefs.set("ideaAt"', 'n % App.ideas.count', '!app.panel.isVisible', '!app.busy',
                     'onboarding.win == nil', '!agentsUI.quiet', 'meeting.panel == nil', 'callAppsOnMic().isEmpty', '!fullScreen()', 'secondsSinceLastEventType'):
            self.assertIn(need, check)

    def test_setting_row_defaults_on_beside_tip_reminders(self):
        defaults = SOURCE[SOURCE.index('static let defaults'):SOURCE.index('static let retiredKeys')]
        self.assertIn('"comeBack": true', defaults)
        page = (ROOT / 'ui/settings.html').read_text()
        tips = page.index('data-k="support"')
        self.assertRegex(page[tips:tips + 300], r'<b>Ideas when I’m away</b>(<span>[^<]*</span>)?</div><label class="sw"><input type="checkbox" data-k="comeBack">')
        self.assertEqual(atticus.switches()['comeBack'], 'Ideas when I’m away')   # by voice too

    def test_telemetry_counts_the_index_never_the_text(self):
        for action, index in (('shown', 3), ('clicked', 0)):
            sent = []
            with patch('sys.argv', ['atticus.py', '--telemetry', 'idea', action, str(index)]), patch.object(atticus, 'posthog', lambda *a: sent.append(a)):
                atticus.main()
            self.assertEqual(sent, [('idea', {'action': action, 'index': index})])


if __name__ == '__main__':
    unittest.main()
