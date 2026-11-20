"""Feedback privacy and instant routing; no browser or AI calls."""
import io
import json
import os
import subprocess
import sys
import unittest
import urllib.parse
from unittest.mock import patch
import atticus
from tests import scratch_dir


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        for p in [patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'Mac14,5\n')),
                  patch.object(atticus.platform, 'mac_ver', return_value=('26.0', (), ''))]:
            p.start(); self.addCleanup(p.stop)
        (self.root / 'log.jsonl').write_text(json.dumps({'task': 'Private ask /Users/person/name', 'reply': 'PRIVATE ANSWER', 'ran': ['PRIVATE COMMAND'], 'steps': ['Searching the web: PRIVATE QUERY']})+'\n'+json.dumps({'task': 'report feedback'})+'\n')

    def test_default_contains_only_template_and_whitelisted_environment(self):
        report = atticus.feedback({'version': '9429210'})
        self.assertFalse(report['include'])
        self.assertIn('Mac model: Mac14,5', report['body'])
        self.assertIn('Version / commit: 9429210', report['body'])
        self.assertIn('Version: ' + atticus.APP_VERSION, report['body']); self.assertIn('Routing: ', report['body'])
        self.assertNotIn('Install ID', report['body'])   # the issue is public: never link it to the anonymous stats
        for secret in ['Private ask', '/Users', 'PRIVATE ANSWER', 'PRIVATE COMMAND', str(self.root)]:
            self.assertNotIn(secret, report['body']); self.assertNotIn(urllib.parse.quote(secret), report['url'])
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(report['url']).query)
        self.assertEqual(query['body'], [report['body']])
        self.assertIn('What happened', report['body']); self.assertIn('What you expected', report['body'])

    def test_other_clients_report_their_own_cli_model(self):
        # issue #30: a Pi report said "Model: haiku", which Pi never uses
        with patch.object(atticus, 'pref', side_effect=lambda k, d: {'client': 'pi', 'model': 'haiku'}.get(k, d)):
            body = atticus.feedback({})['body']
        self.assertIn('AI client: pi\nModel: set in the Pi CLI\n', body)
        self.assertNotIn('haiku', body); self.assertNotIn('Routing: ', body)

    def test_opt_in_shows_exact_previous_ask_only(self):
        report = atticus.feedback({'include': True})
        self.assertIn('Private ask /Users/person/name', report['body'])
        self.assertNotIn('PRIVATE QUERY', report['body'])   # step names quote screen content and searches
        self.assertNotIn('PRIVATE ANSWER', report['body']); self.assertNotIn('PRIVATE COMMAND', report['body'])
        self.assertNotIn('report feedback', report['body'])
        self.assertTrue(report['include'])

    def test_feedback_always_waits_for_confirmation_and_skips_ai(self):
        for request in ('report feedback', 'report a bug'):
            with patch('sys.argv', ['atticus.py', request]), patch.object(atticus, 'start_claude') as ai, patch.object(atticus, 'licensed') as license, patch.object(atticus, 'wait_commit', return_value=True) as gate, patch('sys.stdout', new_callable=io.StringIO) as out, patch.object(atticus, 'look', return_value=[]), patch.object(atticus, 'hands_map', return_value=None):
                atticus.main()
                ai.assert_not_called(); license.assert_not_called(); gate.assert_called_once()
                self.assertIn('! feedback', out.getvalue())
                self.assertIn('Review your feedback', out.getvalue())
            with patch.dict(os.environ, {'ATTICUS_LIVE': '1'}, clear=True), patch('sys.stdout', new_callable=io.StringIO) as out:
                self.assertIsNone(atticus.fast(request)); self.assertEqual(out.getvalue(), '')
