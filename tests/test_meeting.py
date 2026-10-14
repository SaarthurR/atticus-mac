"""Meeting workers: offline, fake Claude, scratch transcripts only."""
import json
import os
import signal
import sys
import time
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import atticus


class MeetingTests(unittest.TestCase):
    def test_question_rule_and_first_name_boundaries(self):
        for text in ['Budget?', 'What is the date', 'why now', 'How much', 'When is it', 'Where next', 'Who pays', 'Which pilot', 'Can we go', 'Could it work', 'Should we wait', 'Would it help', 'Do we agree', 'Does it fit', 'Did it ship', 'Is it ready', 'Are we done', 'Will it work', 'Saarth, your thoughts.']:
            with self.subTest(text=text):
                self.assertTrue(atticus.meeting_question(text, 'Saarth Ranka'))
        for text in ['', 'Thanks everyone.', 'The pilot starts soon.', 'Whatever works.', 'Saarthi is joining.', 'I know Ranka.']:
            with self.subTest(text=text):
                self.assertFalse(atticus.meeting_question(text, 'Saarth Ranka'))
        self.assertFalse(atticus.meeting_question('Thanks', ''))
        for text in ['Hey, how are you doing today?', 'How are you, Saarth?', 'Can you hear me?', 'We ship Friday, right?', 'How have you been']:
            self.assertFalse(atticus.meeting_question(text, 'Saarth Ranka'), text)
        for text in ['How are you thinking about pricing?', 'How was your experience at Google?']:
            self.assertTrue(atticus.meeting_question(text, 'Saarth Ranka'), text)
        self.assertTrue(atticus.meeting_question('A.J., can you help.', 'A.J. Jones'))

    def test_skip_unsure_and_three_line_answer(self):
        for kind in ['SKIP', 'UNSURE']:
            self.assertEqual(atticus.meeting_parse(' \n' + kind + '\n'), {'kind': kind, 'lines': []})
        self.assertEqual(atticus.meeting_parse('**November 12.**\nThe brief says so.\nApproved.\nExtra.'),
                         {'kind': 'answer', 'lines': ['November 12.', 'The brief says so.', 'Approved.']})
        self.assertEqual(atticus.meeting_parse('UNSURE\nThe launch date has not been shared.'),
                         {'kind': 'UNSURE', 'lines': [], 'reason': 'The launch date has not been shared.'})
        self.assertEqual(atticus.meeting_parse('GENERAL\nParis is the capital of France.'),
                         {'kind': 'answer', 'lines': ['Paris is the capital of France.'], 'general': True})
        with self.assertRaises(ValueError):
            atticus.meeting_parse(' \n')

    def test_prompt_budget_recent_window_and_stable_prefix(self):
        rows = [{'at': 100, 'text': 'old secret'}, {'at': 900, 'text': 'x' * 20000}, {'at': 1000, 'text': 'current', 'mic': True}, {'at': 1001, 'text': 'future'}]
        data = {'brief': 'b' * 20000, 'transcript': rows, 'now': 1000, 'question': 'q' * 20000}
        system, prompt = atticus.meeting_prompt(data)
        self.assertLess(len(system) + len(prompt), 10000)
        self.assertNotIn('old secret', prompt)
        self.assertNotIn('future', prompt)
        self.assertIn('You: current', prompt)
        self.assertEqual(system, atticus.meeting_prompt({**data, 'question': 'Other?', 'best': True})[0])
        manual = atticus.meeting_prompt({**data, 'question': 'Other?', 'best': True})[1]
        self.assertIn('Manual ask:', manual)
        self.assertIn('never return SKIP or UNSURE', system)
        self.assertNotIn('Meeting Copilot', atticus.SYSTEM)
        timed = atticus.meeting_prompt({'question': 'What was said in the last 2 minutes?', 'now': 1000, 'transcript': [{'at': 850, 'text': 'too old'}, {'at': 910, 'text': 'recent'}]})[1]
        self.assertNotIn('too old', timed)
        self.assertIn('[90s ago] recent', timed)

    def test_save_and_delete_use_only_scratch_dir(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root):
            self.assertEqual(atticus.meeting_save({'save': False, 'text': 'private'}), '')
            self.assertEqual(list(Path(root).iterdir()), [])
            saved = Path(atticus.meeting_save({'save': True, 'text': '00:12  Hello\n'}))
            self.assertEqual(saved.parent, Path(root) / 'meetings')
            self.assertEqual(saved.read_text(), '00:12  Hello\n')
            self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
            self.assertNotEqual(str(saved), atticus.meeting_save({'save': True, 'text': 'Other'}))
            self.assertEqual(atticus.meeting_save({'save': False}), '')
            self.assertEqual(saved.read_text(), '00:12  Hello\n')

    def test_claude_is_tool_free_and_receives_no_personal_settings(self):
        class Worker:
            pid = 12345
            returncode = 0
            def communicate(self, payload, timeout):
                self.payload = json.loads(payload)
                return json.dumps({'type': 'result', 'result': 'November 12.', 'total_cost_usd': .001}), ''
        worker = Worker()
        with patch.object(atticus.subprocess, 'Popen', return_value=worker) as start, patch.object(atticus, 'stop_claude'), patch.object(atticus.signal, 'signal'), patch.object(atticus.atexit, 'register'), patch.object(atticus, 'log_turn') as log:
            answer, metrics = atticus.meeting_call('Stable prefix', 'A question')
        args = start.call_args.args[0]
        self.assertEqual(args[args.index('--tools') + 1], '')
        self.assertEqual(args[args.index('--model') + 1], 'haiku')
        self.assertIn('--no-session-persistence', args)
        self.assertEqual(args[args.index('--setting-sources') + 1], '')
        self.assertEqual(json.loads(args[args.index('--settings') + 1]), {'disableAllHooks': True})
        self.assertEqual(log.call_args.args[:2], ('Meeting Copilot', ''))
        self.assertEqual(answer, 'November 12.')
        self.assertEqual(metrics['usd'], .001)
        self.assertTrue(start.call_args.kwargs['start_new_session'])

    def test_devin_meeting_stays_local(self):
        with patch.object(atticus, 'client', return_value='devin'), patch.object(atticus.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(RuntimeError, 'stays on this Mac'):
                atticus.meeting_call('Stable prefix', 'A question', 'private screenshot')
        start.assert_not_called()

    def test_stop_cancels_claude_group(self):
        class Worker:
            pid = 12345
            def communicate(self, *args, **kwargs):
                raise subprocess.TimeoutExpired('claude', 45)
        worker = Worker()
        with patch.object(atticus.subprocess, 'Popen', return_value=worker), patch.object(atticus, 'stop_claude') as stop, patch.object(atticus.signal, 'signal'), patch.object(atticus.atexit, 'register'):
            with self.assertRaises(subprocess.TimeoutExpired):
                atticus.meeting_call('prefix', 'question')
            stop.assert_called_once_with(worker)

    def test_sigterm_stops_actual_fake_answer_worker(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            child = root / 'fake_claude.py'
            child.write_text("import sys,time\nfrom pathlib import Path\nPath(sys.argv[1]).write_text('ready')\ntime.sleep(1)\nPath(sys.argv[2]).write_text('survived')\n")
            runner = root / 'run.py'
            runner.write_text("import atticus,subprocess,sys\nreal=atticus.subprocess.Popen\natticus.subprocess.Popen=lambda args,**kwargs: real([sys.executable,sys.argv[1],sys.argv[2],sys.argv[3]],**kwargs)\natticus.meeting_call('prefix','question')\n")
            ready, survived = root / 'ready', root / 'survived'
            p = subprocess.Popen([sys.executable, str(runner), str(child), str(ready), str(survived)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 env={**os.environ, 'ATTICUS_DIR': str(root), 'PYTHONPATH': str(Path(atticus.ME).parent)})
            self.addCleanup(lambda: p.poll() is None and p.kill())
            deadline = time.monotonic() + 3
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(ready.exists(), 'fake Claude never started')
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=3)
            time.sleep(1.1)
            self.assertFalse(survived.exists(), 'Claude child survived Stop')
