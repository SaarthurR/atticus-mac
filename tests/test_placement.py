"""Window placement: one exact target window, and only a checked receipt counts as done. All window access is stubbed."""
import json
import re
import subprocess
import unittest
from unittest.mock import patch

import atticus

UNCHECKED = 'Moved Fixture, but could not check where its window is. Look at the screen before saying it worked.'


class Windows:
    """A fake System Events: `first window whose name is/contains "…"` resolves like AppleScript, front window first."""
    def __init__(self, *names):
        self.windows = [(n, [100 + 50 * i, 100, 800, 600]) for i, n in enumerate(names)]
        self.writes = []

    @property
    def frames(self):
        return [(n, f[:]) for n, f in self.windows]

    def moved(self, before):
        return [n for (n, f), (_, old) in zip(self.windows, before) if f != old]

    def run(self, args, **kw):   # the read-only window lists; any other process (open -a, one-step bounds) is refused
        if args[:3] == ['osascript', '-l', 'JavaScript']:
            rows = [[n, 'AXStandardWindow'] for n, _ in self.windows] if args[-1] == 'windows' else []
            return subprocess.CompletedProcess(args, 0, json.dumps(rows), '')
        self.writes.append(args)
        return subprocess.CompletedProcess(args, 1, '', '')

    def osa(self, script, *args):
        m = re.search(r'first window whose name (is|contains) "((?:[^"\\]|\\.)*)"', script)
        frame = m and next((f for n, f in self.windows if (n == m[2] if m[1] == 'is' else m[2] in n)), None)
        if 'whose subrole is "AXStandardWindow"' in script: frame = self.windows[0][1]
        if not frame: return ''
        if re.search(r'\bset |AXRaise', script): self.writes.append(script)
        if size := re.search(r'set size of .+ to \{(-?\d+), (-?\d+)\}', script): frame[2:] = map(int, size.groups())
        if pos := re.search(r'set position of .+ to \{(-?\d+), (-?\d+)\}', script): frame[:2] = map(int, pos.groups())
        if 'value of attribute "AXFullScreen", value of attribute "AXMinimized"' in script: return 'false, false, ' + ', '.join(map(str, frame))
        if 'return {position, size}' in script: return ', '.join(map(str, frame))
        return ''

    def place(self, title, where='left'):
        with patch.object(atticus.subprocess, 'run', side_effect=self.run), patch.object(atticus, 'osa', side_effect=self.osa), \
             patch.object(atticus, 'free_focus') as focus, patch.object(atticus, 'preview_app'), patch.object(atticus.time, 'sleep'), \
             patch.object(atticus, 'screens', return_value=[('Laptop', 0, 0, 1000, 800, True)]):
            return atticus.place('Fixture', where, 'laptop', title), focus


class PlacementTargetTests(unittest.TestCase):
    def test_original_and_copy_each_move_alone(self):
        # The copy just opened, so it is the front window; both titles contain the original's.
        for asked, moved in [('Study Guide', 'Study-Guide.pdf'), ('Study-Guide', 'Study-Guide.pdf'),
                             ('Study Guide copy.pdf', 'Study-Guide copy.pdf'), ('study_guide copy', 'Study-Guide copy.pdf')]:
            with self.subTest(asked=asked):
                windows = Windows('Study-Guide copy.pdf', 'Study-Guide.pdf')
                before = windows.frames
                out, _ = windows.place(asked)
                self.assertFalse(atticus.place_failed(out), out)
                self.assertEqual(windows.moved(before), [moved])
                self.assertIn((moved, [0, 25, 500, 775]), windows.frames)

    def test_a_unique_partial_title_still_works(self):
        windows = Windows('Calendar', 'Inbox - Fixture Mail')
        before = windows.frames
        out, _ = windows.place('Inbox')
        self.assertFalse(atticus.place_failed(out), out)
        self.assertEqual(windows.moved(before), ['Inbox - Fixture Mail'])

    def test_ambiguous_title_touches_nothing(self):
        for names, asked in [(('Study-Guide copy.pdf', 'Study-Guide.pdf'), 'Guide'),
                             (('Study-Guide.pdf', 'Study_Guide.txt'), 'Study Guide'),   # a hidden extension makes both exact
                             (('Report', 'Report'), 'Report')]:
            with self.subTest(names=names):
                windows = Windows(*names)
                before = windows.frames
                out, focus = windows.place(asked)
                self.assertTrue(atticus.place_failed(out), out)
                self.assertEqual(windows.frames, before)
                self.assertEqual(windows.writes, [])
                focus.assert_not_called()

    def test_a_copy_opening_mid_move_is_left_alone(self):
        windows = Windows('Study-Guide.pdf')
        run = windows.run
        def opening(args, **kw):   # the copy appears in front just after the target was resolved
            if args[-1] != 'windows' and len(windows.windows) == 1: windows.windows.insert(0, ('Study-Guide copy.pdf', [300, 300, 800, 600]))
            return run(args, **kw)
        windows.run = opening
        out, _ = windows.place('')
        self.assertFalse(atticus.place_failed(out), out)
        self.assertEqual(windows.frames, [('Study-Guide copy.pdf', [300, 300, 800, 600]), ('Study-Guide.pdf', [0, 25, 500, 775])])

    def test_every_write_names_the_one_resolved_window(self):
        windows = Windows('Study-Guide copy.pdf', 'Study-Guide.pdf')
        windows.place('Study Guide', 'fullscreen')
        scripts = [w for w in windows.writes if isinstance(w, str)]
        self.assertTrue(scripts)
        self.assertTrue(all('first window whose name is "Study-Guide.pdf"' in s for s in scripts), scripts)


class PlacementReceiptTests(unittest.TestCase):
    def test_only_a_checked_receipt_is_done(self):
        for out in ('', UNCHECKED, 'something unexpected', 'Fixture window -> full of Laptop\nunexpected'):
            with self.subTest(out=out):
                self.assertTrue(atticus.place_failed(out))
        self.assertFalse(atticus.place_failed('Fixture window -> left of Laptop\nOther is already full screen on Monitor; brought it into view'))

    def test_unchecked_prestage_is_not_followed_by_full_screen(self):
        with patch.object(atticus, 'request_screen', return_value='laptop'), patch.object(atticus, 'place', return_value=UNCHECKED) as place:
            atticus.place_many(['Fixture', 'fullscreen', 'laptop', '+', 'Other', 'fullscreen', 'monitor'])
        self.assertEqual([c.args[1] for c in place.call_args_list], ['full', 'full'])

    def test_replay_stops_at_an_unchecked_move_and_never_says_its_saved_reply(self):
        skill = {'cmds': [atticus.PLACE + ' Fixture full laptop', atticus.PLACE + ' Other left laptop'], 'reply': 'All set.'}
        with patch.object(atticus, 'skills', return_value={'fixture time': skill}), patch.object(atticus, 'save_skills'), \
             patch.object(atticus, 'wants_focus', return_value=True), patch.object(atticus, 'place_many', return_value=UNCHECKED) as place:
            out = atticus.fast('fixture time')
        place.assert_called_once()
        self.assertNotIn('All set', out or '')
        self.assertIn('could not check', out or '')
        self.assertTrue(atticus.failed_action_reply(out, bool(atticus.fast.cmds)))   # logged as not done
        self.assertIsNone(atticus.fast.shortcut)

    def test_instant_move_reports_unchecked_as_not_done(self):
        with patch.object(atticus, 'move_target', return_value=('Fixture', 'left', 'laptop')), patch.object(atticus, 'proc_of', return_value='Fixture'), \
             patch.object(atticus, 'skills', return_value={}), patch.object(atticus, 'fast_hands', return_value=None), \
             patch.object(atticus, 'place', return_value=UNCHECKED) as place:
            out = atticus.fast('put fixture left')
        place.assert_called_once()
        self.assertIn('could not check', out)
        self.assertTrue(atticus.failed_action_reply(out, bool(atticus.fast.cmds)))

    def test_show_never_claims_an_unchecked_display(self):
        with patch.object(atticus, 'app_named', return_value='Fixture'), patch.object(atticus, 'app_id', return_value=''), \
             patch.object(atticus, 'front', return_value=('Other', '')), patch.object(atticus, 'wants_focus', return_value=True), \
             patch.object(atticus, 'screens', return_value=[('Laptop', 0, 0, 1000, 800, True), ('Monitor', 1000, 0, 1000, 800, False)]), \
             patch.object(atticus, 'osa', return_value='1'), patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(atticus, 'pref', side_effect=lambda k, d=None: 'other' if k == 'openOn' else d), \
             patch.object(atticus, 'place', return_value=UNCHECKED) as place:
            self.assertNotIn('Monitor', atticus.show('Fixture'))
        place.assert_called_once()

    def test_cli_exits_nonzero_unless_checked(self):
        for out, code in ((UNCHECKED, 1), ('unexpected', 1), ('Fixture window -> full of Laptop', None)):
            with self.subTest(out=out), patch('sys.argv', ['atticus.py', '--place', 'Fixture']), \
                 patch.object(atticus, 'place_many', return_value=out), patch('builtins.print'):
                try: got = atticus.main()
                except SystemExit as stop: got = stop.code
                self.assertEqual(got, code)


if __name__ == '__main__':
    unittest.main()
