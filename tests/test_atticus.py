"""Offline regressions: no Claude calls, Mac actions, or user settings."""
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import atticus


class BrainTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()   # never the user's real log, chat or rules (and CI has no ~/.config/atticus)
        self.addCleanup(root.cleanup)
        p = patch.object(atticus, 'DIR', root.name)
        p.start()
        self.addCleanup(p.stop)
        self.prefs = patch.object(atticus, 'pref', side_effect=lambda k, d: d)
        self.prefs.start()
        self.addCleanup(self.prefs.stop)

    def test_failure_retry_uses_current_model_once_and_sonnet_remains_explicit(self):
        for answer, model, offer, expected in [('r', 'haiku', True, 'haiku'), ('try again', 'haiku', False, 'haiku'),
                                                ('retry', 'sonnet', True, 'sonnet'), ('y', 'haiku', True, 'sonnet'),
                                                ('n', 'haiku', True, None)]:
            with self.subTest(answer=answer, model=model, offer=offer):
                def attempt(prompt, *args):
                    attempt.ok = brain.call_count > 1
                    attempt.cmds = attempt.ran = []
                    return ('Finished.' if attempt.ok else 'Fixture failed.'), .001, ['fixture step']
                brain = unittest.mock.Mock(side_effect=attempt)
                # main reads the status from run itself, just as the real streaming run does.
                def status_attempt(*args):
                    result = attempt(*args); brain.ok = attempt.ok; brain.ran = ['second action'] if attempt.ok else ['first attempted action']; return result
                brain.side_effect = status_attempt
                brain.cmds = brain.ran = []
                with patch.multiple(atticus, licensed=lambda: True, ping=lambda: None, fast=lambda _: None,
                                    front=lambda: ('Fixture', 'Scratch'), osa=lambda *a: '', screens=lambda: [],
                                    describe=lambda *a: '', me_line=lambda: '', selection_context=lambda: '',
                                    relevant_rules=lambda _: '', recent=lambda: [], workflows=lambda *a: '',
                                    screen_for=lambda *a: None, wait_commit=lambda: True, run=brain,
                                    remember_turn=lambda *a: None, restore_focus=lambda *a: None,
                                    remember_workflow=lambda task, reply, *a: (reply, False), learn=lambda *a: False, tip=lambda *a: None), \
                     patch.object(atticus, 'pref', side_effect=lambda k, d: {'model': model, 'escalate': offer}.get(k, d)), \
                     patch.object(atticus, 'ask_user', return_value=answer) as ask, \
                     patch.object(atticus, 'start_ai', return_value=object()) as start, \
                     patch.object(atticus, 'log_turn') as log, patch.object(atticus.threading, 'Thread') as threads, \
                     patch.dict(os.environ, {'ATTICUS_UI': '1'}), patch('sys.argv', ['atticus.py', 'Do fixture']), patch('sys.stdout', io.StringIO()):
                    atticus.main()
                self.assertEqual(brain.call_count, 2 if expected else 1)
                ask.assert_called_once(); self.assertTrue(ask.call_args.args[0]['retry'])
                self.assertEqual(sum(c.kwargs.get('target') is atticus.relay for c in threads.call_args_list), 1, 'standalone failure must not start a competing question relay')
                self.assertEqual(bool(ask.call_args.args[0]['off']), offer and model == 'haiku')
                if expected:
                    start.assert_called_once_with(expected)
                    self.assertEqual(brain.call_args.args[0], brain.call_args_list[0].args[0] + '\nA previous try failed: Fixture failed.\nPrior attempted actions (check their effects before repeating):\nfirst attempted action')
                    self.assertEqual(log.call_args.args[3:5], (.002, ['fixture step', 'fixture step']))
                    self.assertEqual(log.call_args.args[5], ['first attempted action', 'second action'])
                else:
                    start.assert_not_called()

    def test_all_rules_go_while_they_fit_then_word_matches_beyond_five(self):
        mem = Path(atticus.DIR) / 'memory.md'
        with patch.object(atticus, 'MEMORY', str(mem)):
            mem.write_text('When I say dad, use the contact Papa.\n' + 'Keep replies short and friendly please.\n' * 40)   # ~1600 chars, no shared word
            self.assertIn('dad', atticus.relevant_rules('email Papa'))
            mem.write_text(''.join(f'Rule {i}: email signs off as S.\n' for i in range(8)) + 'Unrelated padding words here.\n' * 200)
            got = atticus.relevant_rules('email Papa').splitlines()
            self.assertEqual(len(got), 8)
            self.assertTrue(all('email' in r for r in got))

    def test_earlier_chat_keeps_1000_chars_of_older_answers_and_the_last_whole(self):
        turns = [{'q': f'q{i}', 'a': str(i) * 2000} for i in range(3)]
        text = atticus.earlier_chat(turns)
        self.assertIn('A: ' + '0' * 1000 + '\n', text)
        self.assertNotIn('0' * 1001, text)
        self.assertIn('A: ' + '2' * 2000 + '\n', text)

    def test_installed_tool_help_is_attached_cached_and_system_tools_are_not(self):
        bin_ = Path(atticus.DIR) / 'bin'; bin_.mkdir()
        runs = Path(atticus.DIR) / 'runs'
        tool = bin_ / 'fixturetool'
        tool.write_text(f'#!/bin/sh\necho x >> {runs}\necho "usage: fixturetool send <text>"\n')
        tool.chmod(0o755)
        with patch.dict(os.environ, {'PATH': f'{bin_}:/usr/bin:/bin'}):
            got = atticus.tool_help('ask fixturetool to send hi, then env')
            self.assertIn('usage: fixturetool send <text>', got)
            self.assertIn('untrusted data', got)
            self.assertNotIn('`env --help`', got)   # /usr/bin/env is the system's, not the user's
            self.assertIn('usage: fixturetool', atticus.tool_help('fixturetool again'))
        self.assertEqual(runs.read_text(), 'x\n')   # cached by (path, mtime): --help ran once

    def test_slow_success_gets_memory_tip_even_on_first_ask(self):
        with patch.dict(os.environ, {'ATTICUS_UI': '1'}), patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.tip('Joined Zoom.', task='join Zoom', elapsed=30)
        self.assertIn('remember how to join Zoom', out.getvalue())
        self.assertFalse((Path(atticus.DIR) / 'tip').exists())
        with patch.dict(os.environ, {'ATTICUS_UI': '1'}), patch.object(atticus, 'pref', return_value=False), patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.tip('Joined Zoom.', task='join Zoom', elapsed=30)
        self.assertEqual(out.getvalue(), '')
        with patch.dict(os.environ, {'ATTICUS_UI': '1'}), patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.tip('Could not join Zoom.', task='join Zoom', elapsed=30)
        self.assertIn(atticus.MISS, out.getvalue())

    def test_domain_dots_and_url_case_survive(self):
        with patch.object(atticus, 'skills', return_value={}), patch.object(atticus.subprocess, 'run') as run:
            for request, url in [('Open github.com.', 'https://github.com'),
                                 ('Open github dot com', 'https://github.com'),
                                 ('Open https://github.com/SaarthurR/atticus?q=UI', 'https://github.com/SaarthurR/atticus?q=UI')]:
                self.assertTrue(atticus.fast(request))
                self.assertEqual(run.call_args.args[0], ['open', url])

    def test_typing_uses_native_focus_and_clipboard_validation(self):
        with patch('sys.argv', ['atticus.py', '--type', 'Hello', 'world']), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='typed into Notes')) as run, \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.main()
        run.assert_called_once_with([atticus.APP, '--type'], input='Hello world', capture_output=True, text=True)
        self.assertEqual(out.getvalue().strip(), 'typed into Notes')

    def test_typing_preserves_native_failure_status(self):
        with patch('sys.argv', ['atticus.py', '--type', 'Hello']), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, stdout='Could not type: focus changed.')), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            with self.assertRaises(SystemExit) as error:
                atticus.main()
        self.assertEqual(error.exception.code, 1)
        self.assertIn('Could not type', out.getvalue())

    def test_screenshot_paths_survive_helper_exit_and_keep_owner_cleanup(self):
        script = '''import json, os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import atticus
tempfile.tempdir = sys.argv[2]
atticus.screens = lambda: [('Laptop', 0, 0, 1400, 900, True)]
def capture(args, **kwargs):
    Path(args[-1]).write_bytes(b'fake image')
    return subprocess.CompletedProcess(args, 0)
atticus.subprocess.run = capture
print(json.dumps(atticus.look(cleanup=sys.argv[3] != 'standalone')))
'''
        with tempfile.TemporaryDirectory() as root:
            for mode in ('request', 'standalone', 'in-process'):
                env = {**os.environ, 'ATTICUS_DIR': root}
                env.pop('ATTICUS_ASK', None)
                if mode == 'request':
                    env['ATTICUS_ASK'] = root
                result = subprocess.run([sys.executable, '-c', script, str(Path(atticus.ME).parent), root, mode],
                                        env=env, capture_output=True, text=True, check=True)
                path = Path(json.loads(result.stdout)[0][0])
                self.assertEqual(path.exists(), mode != 'in-process', mode)
                self.assertEqual(path.parent, Path(root))

    def test_close_and_quit_do_not_restore_focus(self):
        with patch.object(atticus, 'osa') as osa:
            for task in ['Close Spotify', 'quit Spotify', 'exit Spotify', 'close this window']:
                atticus.restore_focus('Spotify', task, [])
            osa.assert_not_called()

    def test_focus_restore_only_addresses_existing_process(self):
        with patch.object(atticus, 'osa') as osa:
            osa.side_effect = ['Notes', '']
            atticus.restore_focus('Spotify', 'make a note', ['osascript -e tell application "Notes" to make new note'])
            script, app = osa.call_args.args
            self.assertEqual(app, 'Spotify')
            self.assertIn('if exists process (item 1 of argv) then', script)
            self.assertIn('set frontmost of process', script)
            self.assertNotIn('activate', script)
            self.assertNotIn('tell application "Spotify"', script)

    def test_explicit_focus_and_front_commands_keep_their_destination(self):
        with patch.object(atticus, 'osa') as osa:
            atticus.restore_focus('Notes', 'switch to Spotify', [])
            atticus.restore_focus('Notes', 'show me Spotify', [atticus.FRONT + ' Spotify'])
            atticus.restore_focus('Notes', 'open Spotify', [atticus.SHOW + ' Spotify'])
            osa.assert_not_called()

    def test_screen_requests_include_every_display(self):
        snap = unittest.mock.Mock()
        snap.shots = [('laptop.jpg', 'Screen 1: built-in laptop screen'), ('monitor.jpg', 'Screen 2: external monitor')]
        for task in ['read this screen', 'follow the instructions in Claude in Chrome', 'open the View menu', 'read my monitor']:
            with self.subTest(task=task):
                self.assertEqual(atticus.screen_for(task, snap), snap.shots)
        self.assertIsNone(atticus.screen_for('open notes', snap))

    def test_screen_disabled_and_missing_captures(self):
        snap = unittest.mock.Mock()
        snap.shots = []
        self.assertEqual(atticus.screen_for('read this screen', snap), [])
        snap.join.reset_mock()
        with patch.object(atticus, 'pref', return_value='never'):
            self.assertIsNone(atticus.screen_for('read both screens', snap))
        snap.join.assert_not_called()

    def test_front_display_accounts_for_vertical_position(self):
        displays = [('Laptop', 0, 0, 1400, 900, True), ('Monitor', 0, -1000, 1900, 1000, False)]
        described = atticus.describe(displays, 50, -500).split(';')
        self.assertNotIn('the front window is here', described[0])
        self.assertIn('the front window is here', described[1])
        self.assertIn('above main', described[1])

    def test_commit_waits_for_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            path = str(Path(root) / 'commit')
            timer = threading.Timer(0.15, lambda: Path(path).write_text('go'))
            with patch.dict(os.environ, {'ATTICUS_COMMIT': path}):
                timer.start()
                try:
                    started = time.monotonic()
                    self.assertTrue(atticus.wait_commit())
                    self.assertGreaterEqual(time.monotonic() - started, 0.15)
                finally:
                    timer.join()

    def test_gate_denies_unconfirmed_request(self):
        with patch.object(atticus, 'wait_commit', return_value=False), \
             patch('sys.stdin', io.StringIO(json.dumps({'tool_input': {'command': 'open -a Notes'}}))), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.gate()
            self.assertEqual(json.loads(out.getvalue())['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_claude_payload_with_tool_name_uses_claude_gate(self):
        event = {'tool_name': 'Bash', 'tool_input': {'command': 'echo hi'}}
        with patch.dict(os.environ, {'ATTICUS_CLIENT': 'claude'}), patch.object(atticus, 'preview_commands'), \
             patch('sys.stdin', io.StringIO(json.dumps(event))), patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.gate()
        self.assertEqual(out.getvalue(), '')

    def test_devin_gate_blocks_before_confirmation_and_records_confirmed_steps(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'ATTICUS_ASK': root, 'ATTICUS_CLIENT': 'devin'}):
            event = {'tool_name': 'exec', 'tool_input': {'command': 'open -a Notes'}}
            with patch.object(atticus, 'wait_commit', return_value=False), \
                 patch('sys.stdin', io.StringIO(json.dumps(event))), patch('sys.stdout', new_callable=io.StringIO) as out:
                atticus.gate()
            self.assertEqual(json.loads(out.getvalue())['decision'], 'block')
            self.assertFalse(Path(root, 'devin-tools.jsonl').exists())
            with patch.object(atticus, 'wait_commit', return_value=True), patch.object(atticus, 'pref', return_value=False), patch.object(atticus, 'preview_commands'), \
                 patch('sys.stdin', io.StringIO(json.dumps(event))), patch('sys.stdout', new_callable=io.StringIO):
                atticus.gate()
            row = json.loads(Path(root, 'devin-tools.jsonl').read_text())
            self.assertEqual(row['input']['command'], 'open -a Notes')
            self.assertTrue(any(p.name.startswith('hands-devin-') for p in Path(root).iterdir()))
            blocked = {'tool_name': 'write', 'tool_input': {'path': '/tmp/file'}}
            with patch.object(atticus, 'wait_commit', return_value=True), \
                 patch('sys.stdin', io.StringIO(json.dumps(blocked))), patch('sys.stdout', new_callable=io.StringIO) as out:
                atticus.gate()
            self.assertEqual(json.loads(out.getvalue())['decision'], 'block')

    def test_devin_does_not_start_before_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            fake, marker = Path(root, 'devin'), Path(root, 'started')
            fake.write_text(f'#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n')
            fake.chmod(0o755)
            with patch.dict(os.environ, {'PATH': root + os.pathsep + os.environ['PATH']}), \
                 patch.object(atticus, 'wait_commit', return_value=False):
                reply, _, _ = atticus.run_devin('unconfirmed')
            self.assertIn('cancelled', reply)
            self.assertFalse(marker.exists())

    def test_devin_uses_normal_mode_gate_and_deny_rules(self):
        with tempfile.TemporaryDirectory() as root:
            fake, log, removed = Path(root, 'devin'), Path(root, 'launch.json'), Path(root, 'removed')
            fake.write_text(f'''#!{sys.executable}
import json, os, sys
from pathlib import Path
if sys.argv[1:3] == ['auth', 'status']: raise SystemExit(0)
if sys.argv[1:3] == ['list', '--format']:
    print(json.dumps([{{'id': 'fixture-session', 'cwd': os.getcwd()}}])); raise SystemExit(0)
if sys.argv[1:2] == ['rm']:
    Path(os.environ['DEVIN_REMOVED']).write_text(' '.join(sys.argv[1:])); raise SystemExit(0)
Path(os.environ['DEVIN_LOG']).write_text(json.dumps(sys.argv[1:]))
print('Ready.')
''')
            fake.chmod(0o755)
            previous = signal.getsignal(signal.SIGTERM)
            try:
                with patch.dict(os.environ, {'PATH': root + os.pathsep + os.environ['PATH'], 'DEVIN_LOG': str(log), 'DEVIN_REMOVED': str(removed)}), \
                     patch.object(atticus, 'pref', side_effect=lambda k, d: 'devin' if k == 'client' else False if k == 'safe' else d):
                    self.assertEqual(atticus.run_devin('test')[0], 'Ready.')
            finally:
                signal.signal(signal.SIGTERM, previous)
            args = json.loads(log.read_text())
            self.assertNotIn('dangerous', args)
            self.assertEqual(args[args.index('--permission-mode') + 1], 'normal')
            config = json.loads(Path(args[args.index('--config') + 1]).read_text())
            self.assertIn('PreToolUse', config['hooks'])
            self.assertIn('exec', config['permissions']['allow'])
            self.assertIn('Fetch(*)', config['permissions']['allow'])
            self.assertTrue(all(f'Exec({cmd})' in config['permissions']['deny'] for cmd in atticus.DENIED))
            self.assertIn('mcp__*', config['permissions']['deny'])
            self.assertIn('ATTICUS_CLIENT=devin', config['hooks']['PreToolUse'][0]['hooks'][0]['command'])
            self.assertIn('|| exit 2', config['hooks']['PreToolUse'][0]['hooks'][0]['command'])
            self.assertEqual(removed.read_text(), 'rm fixture-session --force')

    def test_devin_hook_failure_exits_two(self):
        with tempfile.TemporaryDirectory() as root:
            command = json.loads(Path(atticus.devin_config(root)).read_text())['hooks']['PreToolUse'][0]['hooks'][0]['command']
            result = subprocess.run(command, shell=True, input='{', text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)

    def test_failed_devin_output_is_not_success(self):
        with tempfile.TemporaryDirectory() as root:
            fake = Path(root, 'devin')
            fake.write_text(f'''#!{sys.executable}
import json, sys
if sys.argv[1:3] == ['auth', 'status']: raise SystemExit(0)
if sys.argv[1:3] == ['list', '--format']: print(json.dumps([])); raise SystemExit(0)
print('Claimed success.')
print('fixture failure', file=sys.stderr)
raise SystemExit(4)
''')
            fake.chmod(0o755)
            previous = signal.getsignal(signal.SIGTERM)
            try:
                with patch.dict(os.environ, {'PATH': root + os.pathsep + os.environ['PATH']}), \
                     patch.object(atticus, 'pref', side_effect=lambda k, d: 'devin' if k == 'client' else False if k == 'safe' else d):
                    reply, _, _ = atticus.run_devin('test')
            finally:
                signal.signal(signal.SIGTERM, previous)
            self.assertIn('Devin failed: fixture failure', reply)
            self.assertFalse(atticus.run.ok)

    def test_devin_auth_uses_status_exit_code(self):
        ok = subprocess.CompletedProcess([], 0, stdout='localized output')
        bad = subprocess.CompletedProcess([], 1, stdout='Logged in')
        with patch.object(atticus.shutil, 'which', return_value='/fake/devin'), patch.object(atticus.subprocess, 'run', side_effect=[ok, bad]):
            self.assertTrue(atticus.devin_plan()['ok'])
            self.assertFalse(atticus.devin_plan()['ok'])

    def test_cancelled_parent_cannot_use_leftover_commit(self):
        with patch.dict(os.environ, {'ATTICUS_COMMIT': '/fake/commit'}), \
             patch.object(atticus.os, 'getppid', side_effect=[100, 101]), \
             patch.object(atticus.os.path, 'exists', return_value=True):
            self.assertFalse(atticus.wait_commit())

    def test_live_does_not_replay_learned_shell(self):
        with patch.dict(os.environ, {'ATTICUS_LIVE': '1'}), \
             patch.object(atticus, 'skills', return_value={k: {'cmds': ['echo private'], 'reply': 'Done'} for k in ['daily mode', 'open spotify']}), \
             patch.object(atticus.subprocess, 'run') as run:
            self.assertIsNone(atticus.fast('daily mode'))
            self.assertIsNone(atticus.fast('open Spotify'))
            run.assert_not_called()

    def test_risky_saved_shortcut_defers_to_safe_gate(self):
        with patch.object(atticus, 'skills', return_value={'send mail': {'cmds': ['osascript -e \'tell application "Mail" to send outgoing message 1\''], 'reply': 'Sent'}}), \
             patch.object(atticus.subprocess, 'run') as run:
            self.assertIsNone(atticus.replay('send mail'))
            run.assert_not_called()

    def test_fast_action_is_logged_once_at_zero_cost(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root), \
             patch.multiple(atticus, licensed=lambda: True, ping=lambda: None,
                            fast=lambda _: 'Opened Spotify.', remember_turn=lambda *_: None), \
             patch.object(atticus.os, 'setpgrp'), patch.object(atticus.signal, 'signal'), \
             patch('sys.argv', ['atticus.py', '--fast', 'open Spotify']), \
             patch('sys.stdout', io.StringIO()), patch.dict(os.environ, {'ATTICUS_LIVE': '1'}):
            atticus.main()
            rows = atticus.read_rows(str(Path(root) / 'log.jsonl'))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['usd'], 0)
            self.assertTrue(rows[0]['live'])

    def test_confirmed_instant_command_skips_context_work(self):
        with patch.multiple(atticus, **{name: unittest.mock.DEFAULT for name in
                            ['start_ai', 'licensed', 'ping', 'fast', 'remember_turn', 'say', 'front', 'stop_claude']}) as mocks, \
             patch.object(atticus.threading, 'Thread'), patch.object(atticus.os, 'setpgrp'), \
             patch.object(atticus.signal, 'signal'), patch('sys.argv', ['atticus.py', '--wait']), \
             patch('sys.stdin', io.StringIO('Notes\topen Notes\n')), patch.dict(os.environ, {'ATTICUS_COMMIT': ''}):
            # Even without a CLI, --wait must read the request instead of treating its flag as a question.
            mocks['start_ai'].return_value = None
            mocks['licensed'].return_value = True
            mocks['fast'].return_value = 'Opened Notes.'
            atticus.main()
            mocks['fast'].assert_called_once_with('open Notes')
            mocks['front'].assert_not_called()
            mocks['say'].assert_called_once_with('✓', 'Opened Notes.')

    def test_stream_requires_a_real_terminal_answer(self):
        for stream, expected in [([], 'No answer came back. Please try again.'),
                                 ([{'type': 'result', 'result': ''}], 'No answer came back. Please try again.'),
                                 ([{'type': 'result', 'result': 'Found it.', 'total_cost_usd': .001}], 'Found it.')]:
            p = unittest.mock.Mock()
            p.stdin = io.StringIO()
            p.stdout = [json.dumps(row) + '\n' for row in stream]
            p.ask = ''; p.returncode = 0
            reply, _, _ = atticus.run('test', p)
            self.assertEqual(reply, expected)
            self.assertEqual(atticus.run.cmds, [])
            self.assertEqual(atticus.run.ok, expected == 'Found it.')

    def test_truncated_history_preserves_valid_turns(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'recent.jsonl'
            turn = {'t': time.time(), 'q': 'Hi', 'a': 'Hello'}
            path.write_text(json.dumps(turn) + '\nnull\n{"q":"cut off\n{}\n')
            with patch.object(atticus, 'RECENT', str(path)):
                self.assertEqual(atticus.recent(), [turn])

    def test_error_result_is_not_learned(self):
        p = unittest.mock.Mock()
        p.stdin = io.StringIO(); p.ask = ''; p.returncode = 0
        p.stdout = map(json.dumps, [
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'open -a Notes'}}]}},
            {'type': 'result', 'is_error': True, 'result': 'Could not finish.'}])
        with patch.object(atticus, 'say'):
            atticus.run('test', p)
        self.assertEqual(atticus.run.cmds, [])
        self.assertEqual(atticus.run.ran, ['open -a Notes'])
        self.assertFalse(atticus.run.ok)

    def test_recovered_tool_error_keeps_success_but_is_not_learned(self):
        p = unittest.mock.Mock()
        p.stdin = io.StringIO(); p.ask = ''; p.returncode = 0
        p.stdout = map(json.dumps, [
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'is_error': True}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'is_error': False, 'content': 'Verified.'}]}},
            {'type': 'result', 'result': 'Recovered.'}])
        atticus.run('test', p)
        self.assertTrue(atticus.run.ok)
        self.assertEqual(atticus.run.cmds, [])

    def test_failed_final_tool_cannot_be_reported_as_done(self):
        p = unittest.mock.Mock()
        p.stdin = io.StringIO(); p.ask = ''; p.returncode = 0
        p.stdout = map(json.dumps, [
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'is_error': True, 'content': 'Image not found'}]}},
            {'type': 'result', 'result': 'I sent the message.'}])
        reply, _, _ = atticus.run('send the question', p)
        self.assertFalse(atticus.run.ok)
        self.assertIn('could not verify', reply)
        self.assertNotIn('I sent', reply)

    def test_cancellation_stops_descendant(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / 'child-survived'
            ready = Path(root) / 'ready'
            child = f'import time; from pathlib import Path; Path({str(ready)!r}).touch(); time.sleep(0.5); Path({str(marker)!r}).touch()'
            parent = f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",{child!r}]); time.sleep(30)'
            p = subprocess.Popen([sys.executable, '-c', parent], start_new_session=True)
            try:
                deadline = time.monotonic() + 3
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(ready.exists())
                atticus.stop_claude(p)
                p.wait(timeout=3)
                time.sleep(.6)
                self.assertFalse(marker.exists())
            finally:
                atticus.stop_claude(p)
                p.wait(timeout=3)

    def test_devin_sigterm_stops_its_descendant(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            ready, survived = root / 'ready', root / 'survived'
            child = f'import time; from pathlib import Path; Path({str(ready)!r}).touch(); time.sleep(.6); Path({str(survived)!r}).touch()'
            fake = root / 'devin'
            fake.write_text(f'''#!{sys.executable}
import json, subprocess, sys, time
if sys.argv[1:3] == ['auth', 'status']: raise SystemExit(0)
if sys.argv[1:3] == ['list', '--format']: print(json.dumps([])); raise SystemExit(0)
subprocess.Popen([sys.executable, '-c', {child!r}])
time.sleep(30)
''')
            fake.chmod(0o755)
            runner = root / 'run.py'
            runner.write_text("import atticus\natticus.pref=lambda k,d: 'devin' if k=='client' else False if k=='safe' else d\natticus.run_devin('test')\n")
            p = subprocess.Popen([sys.executable, str(runner)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 env={**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                                      'ATTICUS_DIR': str(root), 'PYTHONPATH': str(Path(atticus.ME).parent)})
            try:
                deadline = time.monotonic() + 3
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(ready.exists(), 'fake Devin never started')
                p.send_signal(signal.SIGTERM)
                p.wait(timeout=3)
                time.sleep(.7)
                self.assertFalse(survived.exists(), 'Devin child survived Stop')
            finally:
                if p.poll() is None:
                    p.kill(); p.wait(timeout=3)

    def test_fast_worker_sigterm_stops_its_action_group(self):
        with tempfile.TemporaryDirectory() as root:
            marker, ready = Path(root) / 'action', Path(root) / 'ready'
            action = f'import time; from pathlib import Path; Path({str(ready)!r}).touch(); time.sleep(.5); Path({str(marker)!r}).touch()'
            script = f'''import atticus, subprocess, sys, time
atticus.ping = lambda: None
atticus.licensed = lambda: True
def fast(_):
    subprocess.Popen([sys.executable, '-c', {action!r}])
    time.sleep(30)
atticus.fast = fast
sys.argv = ['atticus.py', '--fast', 'test']
atticus.main()
'''
            p = subprocess.Popen([sys.executable, '-c', script], env={**os.environ, 'ATTICUS_DIR': root})
            try:
                deadline = time.monotonic() + 3
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(ready.exists())
                p.terminate(); p.wait(timeout=3); time.sleep(.6)
                self.assertFalse(marker.exists())
            finally:
                if p.poll() is None:
                    p.terminate(); p.wait(timeout=3)

    def test_cli_stderr_cannot_block_the_stream(self):
        with tempfile.TemporaryDirectory() as root:
            fake = Path(root) / 'claude'
            fake.write_text(f'#!{sys.executable}\nimport sys\nsys.stderr.write("x" * 1000000)\nprint(\'{json.dumps({"type": "result", "result": "Ready."})}\')\n')
            fake.chmod(0o755)
            previous_handler = signal.getsignal(signal.SIGTERM)
            try:
                with patch.object(atticus.shutil, 'which', return_value=str(fake)), \
                     patch.dict(os.environ, {'PATH': root + os.pathsep + os.environ['PATH'], 'ATTICUS_COMMIT': ''}), \
                     patch.object(atticus, 'pref', side_effect=lambda k, d: False if k == 'safe' else d):
                    p = atticus.start_claude()
                    timer = threading.Timer(3, atticus.stop_claude, args=(p,))
                    timer.start()
                    try:
                        self.assertEqual(atticus.run('test', p)[0], 'Ready.')
                    finally:
                        timer.cancel(); timer.join(); atticus.stop_claude(p); p.errors.close()
            finally:
                signal.signal(signal.SIGTERM, previous_handler)


class WatchAndBudgetTests(unittest.TestCase):
    def setUp(self):
        self.notes = []
        for p in (patch.object(atticus.time, 'sleep'), patch.object(atticus, 'notify', side_effect=self.notes.append)):
            p.start()
            self.addCleanup(p.stop)

    def fake_app(self, out, code=0):
        f = tempfile.NamedTemporaryFile('w', suffix='.sh', delete=False)
        f.write(f'#!/bin/sh\nprintf %s "{out}"\nexit {code}\n')
        f.close()
        os.chmod(f.name, 0o755)
        self.addCleanup(os.remove, f.name)
        return patch.object(atticus, 'APP', f.name)

    def test_cmd_watch_fires_after_two_passing_checks(self):
        atticus.watch('true', '')
        self.assertEqual(len(self.notes), 1)
        self.assertIn('done', self.notes[0])

    def test_phrase_gone_fires_and_present_waits(self):
        with self.fake_app('All set. Ready for the next task'):
            atticus.watch('', '', 'Orca', '', 'gone', 'esc to  interrupt')
        self.assertIn('Orca: done.', self.notes[-1])
        with self.fake_app('Working (12s - esc to interrupt)'), patch.object(atticus.time, 'time', side_effect=[0, 0, 1, 2, 1e9]):
            atticus.watch('', '', 'Orca', '', 'gone', 'esc to interrupt')
        self.assertIn('3 hours', self.notes[-1])

    def test_unreadable_window_stops_with_a_reason(self):
        with self.fake_app('', 1):
            atticus.watch('', '', 'Orca', '', 'shows', 'done')
        self.assertIn("can't read its window", self.notes[-1])

    def test_title_words_that_name_a_tab_fall_back_to_the_main_window(self):
        f = tempfile.NamedTemporaryFile('w', suffix='.sh', delete=False)   # no window has that title; the main one reads fine
        f.write('#!/bin/sh\n[ -n "$3" ] && exit 1\nprintf %s "All set"\n')
        f.close()
        os.chmod(f.name, 0o755)
        self.addCleanup(os.remove, f.name)
        with patch.object(atticus, 'APP', f.name):
            atticus.watch('', '', 'Orca', 'Atticus meeting mode spec', 'gone', 'esc to interrupt')
        self.assertIn('Orca: done.', self.notes[-1])

    def test_settled_waits_while_text_changes_then_fires(self):
        reads = iter(['Sprouting (3s)', 'Incubating (8s)', 'Done.', 'Done.', 'Done.', 'Done.', 'Done.'])
        def run(cmd, **kw):
            r = unittest.mock.Mock(returncode=0, stdout=next(reads))
            return r
        with patch.object(atticus.subprocess, 'run', side_effect=run):
            atticus.watch('', '', 'Orca', '', 'settled', '')
        self.assertIn('Orca: done.', self.notes[-1])
        self.assertEqual(next(reads, 'used up'), 'used up')   # it needed all 5 matching reads: 4 unchanged in a row

    def test_settled_requires_nonempty_continuous_successful_reads(self):
        reads = iter([(0, ''), (0, ''), (0, 'Done'), (0, 'Done'), (1, 'Done'),
                      (0, 'Done'), (0, 'Done'), (0, 'Done'), (0, 'Done'), (0, 'Done')])
        def run(*args, **kwargs):
            code, text = next(reads)
            return subprocess.CompletedProcess(args, code, stdout=text)
        with patch.object(atticus.subprocess, 'run', side_effect=run):
            atticus.watch('', '', 'Orca', '', 'settled', '')
        self.assertEqual(next(reads, None), None)
        self.assertIn('Orca: done.', self.notes[-1])

    def test_title_fallback_retries_original_title_on_each_poll(self):
        calls = []
        def run(cmd, **kwargs):
            calls.append(cmd[-1])
            return subprocess.CompletedProcess(cmd, bool(cmd[-1]), stdout='Done')
        with patch.object(atticus.subprocess, 'run', side_effect=run):
            atticus.watch('', '', 'Orca', 'Tab', 'gone', 'busy')
        self.assertEqual(calls, ['Tab', '', 'Tab', ''])

    def test_pointer_without_displays_strips_tag_without_coordinates(self):
        with patch.object(atticus, 'screens', return_value=[]), patch.object(atticus, 'say') as say:
            self.assertEqual(atticus.point('Here. [point 1 20 30]'), 'Here.')
            say.assert_not_called()

    def test_pick_prints_the_choice_the_box_sends_back(self):
        for answer, printed in [('1', 'b.pdf'), ('', 'None of these'), ('=the 2 one from yesterday', 'None of these. The user typed their own answer instead: "the 2 one from yesterday"'), (None, 'The user did not pick')]:   # None: no answer in time
            with patch.dict(os.environ, {'ATTICUS_ASK': '/fake'}), patch.object(atticus, 'ask_user', return_value=answer) as ask, \
                 patch('sys.stdout', new_callable=io.StringIO) as out:
                atticus.pick('Which one?', ['a.pdf', 'b.pdf'])
            self.assertEqual(ask.call_args.args[0]['options'], ['a.pdf', 'b.pdf'])
            self.assertTrue(out.getvalue().startswith(printed))
        self.assertEqual(atticus.label('Bash', {'command': f'{atticus.PICK} "Which?" "a" "b"'}), 'Asking you which one')
        self.assertFalse(atticus.risky(f'{atticus.PICK} "Which file?" "~/delete-me.txt" "~/send.pdf"'))

    def test_place_by_title_never_falls_back_to_the_front_window(self):
        calls = []
        def osa(script, *args):   # System Events can't see it, so the app's own window list answers
            calls.append(script)
            return '0, 0, 800, 600' if 'get bounds' in script else ''
        with patch.object(atticus, 'osa', side_effect=osa), patch.object(atticus.subprocess, 'run') as run, patch.object(atticus, 'preview_app'), \
             patch.object(atticus, 'screens', return_value=[('Built-in', 0, 0, 1470, 956, True), ('Acer', 1470, 0, 1920, 1080, False)]):
            run.return_value.returncode = 0
            atticus.place('Preview', 'full', 'laptop', 'Ch4-Study-Guide copy.pdf')
        app = [c for c in calls if 'get bounds' in c] + [run.call_args.args[0][2]]
        self.assertTrue(all('whose name contains "Ch4-Study-Guide copy"' in c and 'window 1' not in c for c in app))

    def test_set_flips_a_switch_by_name_safe_mode_only_on(self):
        self.assertIn('askMe', atticus.switches())
        self.assertNotIn('paused', atticus.switches())
        with patch.dict(os.environ, {'ATTICUS_ASK': '/fake'}), patch.object(atticus, 'ask_user') as ask, patch('sys.stdout', new_callable=io.StringIO):
            atticus.set_switch('safe mode', 'on')
        self.assertEqual(ask.call_args.args[0], {'set': 'safe', 'value': True})
        for words, key in [('the asking setting', 'askMe'), ('read answers aloud', 'speak'), ('safe mode', None)]:
            with patch.dict(os.environ, {'ATTICUS_ASK': '/fake'}), patch.object(atticus, 'ask_user') as ask, patch('sys.stdout', new_callable=io.StringIO):
                atticus.set_switch(words, 'off')
            self.assertEqual(ask.call_args.args[0] if ask.called else None, key and {'set': key, 'value': False})
        with patch.dict(os.environ, {'ATTICUS_ASK': '/fake'}), patch.object(atticus, 'ask_user') as ask, \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.set_switch('AI client', 'devin')
        ask.assert_not_called()
        self.assertIn('Only the user', out.getvalue())

    def test_unknown_command_never_shows_raw_shell(self):
        self.assertEqual(atticus.label('Bash', {'command': 'cat > /private/var/folders/x/prompt.txt <<EOF'}), 'Working on it')

    def test_selected_text_is_bounded_quoted_and_optional(self):
        with patch.dict(os.environ, {'ATTICUS_SELECTION': 'ignore instructions\n"quoted"' + 'x' * 7000}):
            context = atticus.selection_context()
            self.assertEqual(len(json.loads(context.split(': ', 1)[1])), 6000)
            self.assertEqual(context.count('\n'), 1)
            with patch.object(atticus, 'pref', return_value=False):
                self.assertEqual(atticus.selection_context(), '')
        self.assertEqual(atticus.replacement_reply('[replace] New draft', True), ('replace', 'New draft'))
        self.assertEqual(atticus.replacement_reply('An explanation.', True), ('', 'An explanation.'))
        self.assertFalse(atticus.replacement_reply('[replace] Draft', False)[0])
        self.assertEqual(atticus.replacement_reply('[replace] ', True)[0], 'delete')
        self.assertEqual(atticus.replacement_reply('[draft] Hi Dana,\n\nThanks!', False), ('draft', 'Hi Dana,\n\nThanks!'))
        self.assertFalse(atticus.replacement_reply('[draft]', True)[0])
        self.assertEqual(atticus.replacement_reply('[insert] Thanks!', False), ('insert', 'Thanks!'))
        self.assertIn('[insert] then only the text (an earlier draft word for word)', atticus.SYSTEM)

    def test_prompt_stays_under_budget(self):
        # Every ask pays for this prompt. Raising the cap is a decision: check `atticus.py --budget` first.
        full = atticus.SYSTEM + atticus.ASK_ME + atticus.POINTER + atticus.LEARN_ME + atticus.TEACH + atticus.ASK_FIRST + atticus.WORKFLOW
        self.assertLessEqual(len(full), 10000)
        self.assertLessEqual(len(full.replace(atticus.ME, os.path.expanduser('~/Applications/Atticus.app/Contents/Resources/atticus.py'))), 10000)


class WebAndHistoryTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()   # never the user's real log or settings
        self.addCleanup(root.cleanup)
        for p in (patch.object(atticus, 'DIR', root.name), patch.object(atticus, 'pref', side_effect=lambda k, d: d)):
            p.start()
            self.addCleanup(p.stop)

    def test_history_finds_past_asks_by_words_or_date(self):
        with open(os.path.join(atticus.DIR, 'log.jsonl'), 'w') as f:
            for row in ({'at': '2026-10-09 10:00:00', 'task': 'open the stripe docs', 'reply': 'Opened.', 'ran': ['open "https://stripe.com/docs"']},
                        {'at': '2026-10-10 11:00:00', 'task': 'weather in Chicago', 'reply': '72F'},
                        {'at': '2026-10-10 12:00:00', 'task': 'Meeting Copilot', 'reply': ''}):
                f.write(json.dumps(row) + '\n')
            f.write('{broken\n')
        self.assertIn('stripe.com/docs', atticus.history('that stripe link'))
        self.assertNotIn('weather', atticus.history('that stripe link'))
        self.assertIn('weather', atticus.history('2026-10-10'))
        self.assertNotIn('Meeting Copilot', atticus.history(''))   # no reply = nothing to recall
        self.assertEqual(atticus.history('zebra'), 'Nothing matches.')

    def test_web_tools_label_and_skip_the_word_gate(self):
        self.assertEqual(atticus.label('Bash', {'command': f'{atticus.WEB} read'}), 'Reading the page')
        self.assertEqual(atticus.label('Bash', {'command': f'{atticus.WEB}'}), 'Using the page')
        self.assertFalse(atticus.risky(f'{atticus.WEB} fill 3 "please send the delete form"'))   # typed words are not actions

    def test_chrome_pins_ids_across_background_actions_and_refreshes_on_read(self):
        calls = []
        def run(cmd, **kw):
            calls.append(cmd)
            out = '41\t73' if 'count windows' in cmd[-1] else 'Fixture, 0, 0, 300, 200' if 'get {name, bounds}' in cmd[-1] else json.dumps({'what':'Toggle','short':'Toggle','url':'https://fixture.test'}) if '"name"' in cmd[-1] else 'Page read'
            return subprocess.CompletedProcess(cmd,0,out,'')
        with patch.dict(os.environ,{'ATTICUS_FRONT':'Google Chrome'},clear=True), patch.object(atticus,'hands_map',return_value=None), patch.object(atticus.subprocess,'run',side_effect=run), patch.object(atticus,'page_ready',return_value=True):
            atticus.web('read'); atticus.web('click','1'); atticus.web('fill','2','Name')
            self.assertEqual(sum('count windows' in c[-1] for c in calls),1)
            scripts = [c[2] for c in calls if c[1] == '-e' and 'count windows' not in c[-1]]
            self.assertTrue(all(('window id 41 whose id is 73' in c or 'get {name, bounds} of window id 41' in c) and 'front window' not in c for c in scripts))
            atticus.web('read')
            self.assertEqual(sum('count windows' in c[-1] for c in calls),2)
        with patch.dict(os.environ,{'ATTICUS_FRONT':'Google Chrome'},clear=True), patch.object(atticus.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','No windows')):
            self.assertIn('--hands see',atticus.web('read'))

    def test_web_rechecks_control_after_permission(self):
        name = {'what':'Confirm','short':'Confirm','url':'https://fixture.test'}
        calls = []
        def run(cmd, **kw):
            calls.append(cmd[-1])
            if 'count windows' in cmd[-1]: out = '41\t73'
            elif 'get {name, bounds}' in cmd[-1]: out = 'Fixture, 0, 0, 300, 200'
            else: out = json.dumps(name if sum('"name"' in c for c in calls) == 1 else {**name,'what':'Delete'})
            return subprocess.CompletedProcess(cmd,0,out,'')
        with patch.dict(os.environ,{'ATTICUS_FRONT':'Google Chrome','ATTICUS_ASK':atticus.DIR},clear=True), patch.object(atticus.subprocess,'run',side_effect=run), patch.object(atticus,'ask_user',return_value='y'):
            self.assertIn('control changed',atticus.web('click','1'))
            self.assertFalse(any('"click"' in c for c in calls))

    def test_risky_web_click_asks_first(self):
        calls = []
        def run(cmd, **kw):
            calls.append(cmd[-1])
            if 'count windows' in cmd[-1]: return subprocess.CompletedProcess(cmd, 0, '41\t73', '')
            if 'get {name, bounds}' in cmd[-1]: return subprocess.CompletedProcess(cmd, 0, 'Fixture, 0, 0, 300, 200', '')
            out = json.dumps({'what': 'Confirm', 'short': 'Confirm', 'url': 'https://shop.test/cart'}) if '"name"' in cmd[-1] else 'Clicked 4: Confirm'
            return subprocess.CompletedProcess(cmd, 0, out, '')
        with patch.dict(os.environ, {'ATTICUS_FRONT': 'Google Chrome', 'ATTICUS_ASK': atticus.DIR}), \
                patch.object(atticus.subprocess, 'run', side_effect=run), patch.object(atticus, 'ask_user', return_value='n') as ask:
            self.assertIn('said no', atticus.web('click', '4'))
            self.assertEqual(ask.call_args[0][0]['q'], 'Click "Confirm"?')   # a hidden buy/send asks too
            self.assertFalse(any('"click"' in c for c in calls))
        with patch.dict(os.environ, {'ATTICUS_FRONT': 'Google Chrome', 'ATTICUS_ASK': atticus.DIR}), \
                patch.object(atticus.subprocess, 'run', side_effect=run), patch.object(atticus, 'ask_user', return_value='y'), \
                patch.object(atticus,'page_ready',return_value=True):
            self.assertTrue(atticus.web('click', '4').startswith('Clicked 4'))
            self.assertIn('https://shop.test/cart', calls[-2])   # the click is bound to the checked tab
        with patch.dict(os.environ, {'ATTICUS_FRONT': 'Google Chrome'}), patch.dict(os.environ, {}, clear=False), \
                patch.object(atticus.subprocess, 'run', side_effect=run), patch.object(atticus, 'ask_user') as ask:
            os.environ.pop('ATTICUS_ASK', None)
            self.assertIn('needs the user', atticus.web('click', '4'))   # no Allow card (a shortcut): never click blind
            ask.assert_not_called()


if __name__ == '__main__':
    unittest.main()
