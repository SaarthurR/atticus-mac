"""Fill/submit policy and helper gates; all browser actions are stubbed."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import atticus


class SubmitContractTests(unittest.TestCase):
    def test_shared_form_instructions_require_explicit_submit_intent(self):
        forms = next(line for line in atticus.SYSTEM.splitlines() if line.startswith('Forms/worksheets:'))
        self.assertIn('Filling never authorizes submission.', forms)
        self.assertIn('Submit/send only if explicitly asked', forms)
        self.assertNotIn('Then click Submit', forms)

    def exercise_web(self, adapter, action, answer='y', safe=True):
        actions = []
        control = {'what': 'Go', 'short': 'Go', 'url': 'https://fixture.invalid/', 'submit': True}

        def worker(args, **kwargs):
            cmd, n, text = json.loads('[' + args[-1].rsplit(')(', 1)[1][:-1] + ']')
            actions.append(cmd)
            if cmd == 'click':
                self.assertIn('name', actions)
                ask.assert_called_once()
                self.assertEqual(answer, 'y', 'submission cannot precede Allow')
            output = {'name': json.dumps(control), 'fill': 'Filled 1: Answer',
                      'click': 'Clicked 2: Go', 'state': '{"value":"Fixture answer"}'}[cmd]
            return subprocess.CompletedProcess(args, 0, output, '')

        page = {'app': 'Browser Fixture', 'adapter': adapter, 'window': 10, 'tab': 2, 'target': {'windowID': '10'}}
        with tempfile.TemporaryDirectory() as scratch, \
             patch.dict(os.environ, {'ATTICUS_ASK': scratch}, clear=True), \
             patch.object(atticus, 'DIR', scratch), \
             patch.object(atticus, 'browser_adapter', return_value=adapter), \
             patch.object(atticus, 'pref', side_effect=lambda key, default=None: safe if key == 'safe' else default), \
             patch.object(atticus, 'task_allowed', return_value=False), \
             patch.object(atticus, 'managed_agent', return_value=False), \
             patch.object(atticus, 'emit'), \
             patch.object(atticus, 'page_ready', return_value=True), \
             patch.object(atticus.subprocess, 'run', side_effect=worker), \
             patch.object(atticus, 'ask_user', return_value=answer) as ask:
            result = atticus.web(action, '1' if action == 'fill' else '2',
                                 'Submit this answer' if action == 'fill' else '', app=page['app'], page=page)
        return result, actions, ask

    def test_fill_only_never_clicks_or_asks_for_allow(self):
        for adapter in ('chromium', 'webkit'):
            with self.subTest(adapter=adapter):
                result, actions, ask = self.exercise_web(adapter, 'fill')
                self.assertIn('Filled 1', result)
                self.assertIn('Fixture answer', result)
                self.assertEqual(actions, ['fill', 'state'])
                ask.assert_not_called()

    def test_explicit_submit_follows_allow_even_with_full_access(self):
        for adapter in ('chromium', 'webkit'):
            for safe in (True, False):
                for answer in ('y', 'n'):
                    with self.subTest(adapter=adapter, safe=safe, answer=answer):
                        result, actions, ask = self.exercise_web(adapter, 'click', answer, safe)
                        ask.assert_called_once()
                        self.assertEqual(ask.call_args.args[1], 60)
                        self.assertEqual(actions, ['name', 'name', 'click', 'state'] if answer == 'y' else ['name'])
                        self.assertIn('Clicked 2' if answer == 'y' else 'user said no', result)
