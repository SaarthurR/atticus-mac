"""Chrome page permission checks stub osascript; never contact a real browser."""
import contextlib
import io
import subprocess
import sys
import unittest
from unittest.mock import patch

import atticus


class PageJSTests(unittest.TestCase):
    def worker(self, enabled=False, click_works=True, checked=False):
        self.enabled = enabled
        self.clicks = 0
        def run(args, **kwargs):
            if args[0] == 'open':
                return subprocess.CompletedProcess(args, 0, '', '')
            self.assertEqual(args[0], 'osascript')
            script = args[2]
            if 'execute' in script:
                self.assertIn('javascript "1"', script)
                self.assertIn('if (count windows) is 0 then set probeWindow to make new window', script)
                self.assertEqual(script.count('if probeWindow is not missing value then close probeWindow'), 2)
                return subprocess.CompletedProcess(args, 0 if self.enabled else 1, '1\n' if self.enabled else '', 'JavaScript disabilitato')
            # A translated menu cannot be found by English labels.
            self.assertNotIn('"View"', script)
            self.assertNotIn('"Developer"', script)
            self.assertNotIn('"Allow JavaScript from Apple Events"', script)
            self.assertIn('menu bar item 5', script)
            self.assertIn('if value of attribute "AXMenuItemMarkChar" of m is missing value then click m', script)
            if not checked:
                self.clicks += int(click_works)
                self.enabled = click_works
            return subprocess.CompletedProcess(args, 0, 'on\n' if checked or click_works else '', '')
        return run

    def test_already_enabled_needs_no_menu_access(self):
        with patch.object(atticus.subprocess, 'run', side_effect=self.worker(enabled=True)) as run, \
             patch.object(atticus, 'proc_of', return_value='Browser Fixture'):
            self.assertTrue(atticus.allow_page_js('Browser Fixture'))
        self.assertEqual(run.call_count, 1)

    def test_menu_enable_succeeds_unless_click_fails(self):
        for works in (True, False):
            with self.subTest(works=works), patch.object(atticus.subprocess, 'run', side_effect=self.worker(click_works=works)) as run, \
                 patch.object(atticus, 'proc_of', return_value='Browser Fixture'):
                self.assertEqual(atticus.allow_page_js('Browser Fixture'), works)
                self.assertEqual(run.call_count, 2)

    def test_checked_setting_succeeds_when_chrome_page_rejects_probe(self):
        with patch.object(atticus.subprocess, 'run', side_effect=self.worker(checked=True)) as run, \
             patch.object(atticus, 'proc_of', return_value='Browser Fixture'):
            self.assertTrue(atticus.allow_page_js('Browser Fixture'))
        self.assertEqual(run.call_count, 2)
        self.assertEqual(self.clicks, 0)

    def test_ask_still_requires_consent(self):
        with patch.dict(atticus.os.environ, {'ATTICUS_ASK': '/fixture'}), \
             patch.object(atticus, 'pref', return_value=False), patch.object(atticus, 'ask_user', return_value='n'), \
             patch.object(atticus.subprocess, 'run') as run:
            self.assertFalse(atticus.allow_page_js('Browser Fixture', ask=True))
        run.assert_not_called()

    def test_setup_cli_succeeds_with_already_enabled_translated_menu(self):
        with patch.object(sys, 'argv', ['atticus.py', '--allow-js']), \
             patch.object(atticus.subprocess, 'run', side_effect=self.worker(enabled=True)) as run, \
             contextlib.redirect_stdout(io.StringIO()) as out:
            atticus.main()
        self.assertEqual(out.getvalue(), 'on\n')
        self.assertEqual(run.call_count, 2)  # background launch, then the language-free probe
