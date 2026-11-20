"""Task guards through the real hooks with fake tools; executed only in the Tart VM."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import atticus


class StepBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for p in (patch.object(atticus, 'DIR', self.tmp.name), patch.object(atticus, 'PREFS', str(self.root/'settings.json')),
                  patch.dict(atticus.TURN, {}, clear=True),
                  patch.dict(os.environ, ATTICUS_ASK=self.tmp.name, ATTICUS_AGENT='', ATTICUS_CLIENT='claude')):
            p.start(); self.addCleanup(p.stop)

    def event(self, command='echo example', response='same', failed=False):
        return {'tool_name': 'Bash', 'tool_input': {'command': command}, 'tool_response': response, 'is_error': failed}

    def test_failed_action_repeated_three_times_pauses_before_fourth_and_stays_stopped(self):
        event = self.event(failed=True)
        with patch.object(atticus, 'ask_user', return_value='1') as ask, patch.object(atticus, 'step_screen') as screen:
            for _ in range(3):
                self.assertEqual(atticus.step_guard(event), '')
                atticus.step_guard(event, after=True)
            self.assertIn('paused', atticus.step_guard(event))
            self.assertIn('paused', atticus.step_guard(self.event('a different command')))
        ask.assert_called_once(); screen.assert_not_called()
        self.assertEqual(ask.call_args.args[0]['options'], ['Keep going', 'Stop'])

    def test_successful_repeats_need_three_unchanged_screens(self):
        event = self.event()
        with patch.object(atticus, 'ask_user', return_value='1') as ask, patch.object(atticus, 'step_screen', return_value=[10, 20, 30]):
            for _ in range(5):
                self.assertEqual(atticus.step_guard(event), '')
                atticus.step_guard(event, after=True)
            self.assertIn('paused', atticus.step_guard(event))
        ask.assert_called_once()

    def test_progress_extends_in_fives_without_cutting_task(self):
        with patch.object(atticus, 'ask_user', side_effect=AssertionError('progress must not pause')), \
             patch.object(atticus, 'step_screen', side_effect=AssertionError('novel results need no capture')):
            for i in range(60):
                event = self.event(response=f'Observed result {i}')
                self.assertEqual(atticus.step_guard(event), '')
                atticus.step_guard(event, after=True)
        state = json.loads(Path(atticus.step_state_path(self.tmp.name)).read_text())
        self.assertEqual(state['steps'], 60); self.assertEqual(state['limit'], 60)

    def test_repeated_scroll_receipts_with_moving_pixels_keep_running(self):
        with patch.object(atticus, 'ask_user', side_effect=AssertionError('screen is moving')), \
             patch.object(atticus, 'step_screen', side_effect=([i * 10 % 256] * 3 for i in range(60))):
            for _ in range(45):
                self.assertEqual(atticus.step_guard(self.event()), '')
                atticus.step_guard(self.event(), after=True)

    def test_no_progress_cap_stops_without_screen_permission_and_yes_resumes_same_session(self):
        for _ in range(25): self.assertEqual(atticus.step_guard(self.event()), '')
        atticus.sent_image(b'already sent')
        with patch.object(atticus, 'step_screen', return_value=None), patch.object(atticus, 'ask_user', return_value='0') as ask:
            self.assertEqual(atticus.step_guard(self.event()), '')
        ask.assert_called_once()
        self.assertTrue(atticus.sent_image(b'already sent'), 'resume must retain image dedupe')
        state = json.loads(Path(atticus.step_state_path(self.tmp.name)).read_text())
        self.assertEqual(state['steps'], 1)

    def test_alternating_failed_actions_are_circling_too(self):
        with patch.object(atticus, 'ask_user', return_value=None):
            for i in range(5):
                event = self.event(command=str(i % 2), failed=True)
                self.assertEqual(atticus.step_guard(event), '')
                atticus.step_guard(event, after=True)
            self.assertIn('paused', atticus.step_guard(self.event()))

    def test_initial_images_are_deduped_by_bytes_across_paths_and_asks_are_isolated(self):
        first, second = self.root/'one.jpg', self.root/'two.jpg'
        first.write_bytes(b'image'); second.write_bytes(b'image')
        content = atticus.user_content('hello', [(str(first), 'Screen 1'), (str(second), 'Screen 2')])
        self.assertEqual(sum(b['type'] == 'image' for b in content), 1)
        self.assertEqual(sum(b['type'] == 'image' for b in atticus.user_content('hello', [(str(first), 'Screen 1')])), 0)
        first.write_bytes(b'changed')
        self.assertEqual(sum(b['type'] == 'image' for b in atticus.user_content('hello', [(str(first), 'Screen 1')])), 1)
        with tempfile.TemporaryDirectory() as another, patch.dict(os.environ, ATTICUS_ASK=another):
            self.assertFalse(atticus.sent_image(b'image'))

    def test_read_hook_blocks_image_already_sent_in_initial_message(self):
        image = self.root/'atticus-screen-1.jpg'; image.write_bytes(b'pixels')
        atticus.user_content('look', [(str(image), 'Screen 1')])
        event = {'tool_name': 'Read', 'tool_input': {'file_path': str(image)}}
        with patch.object(atticus.sys, 'stdin', io.StringIO(json.dumps(event))), patch.object(atticus, 'wait_commit', return_value=True), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            atticus.gate()
        decision = json.loads(out.getvalue())['hookSpecificOutput']
        self.assertEqual(decision['permissionDecision'], 'deny')
        self.assertIn('already sent', decision['permissionDecisionReason'])

    def test_paused_run_does_not_claim_success_or_offer_model_retry(self):
        from tests.test_stream import message, result
        path = Path(atticus.step_state_path(self.tmp.name))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'stopped': True, 'summary': 'Paused after 5 steps; last: Reading.'}))
        p = Mock(); p.ask = self.tmp.name; p.stdin = io.StringIO(); p.errors = io.StringIO(); p.returncode = 0
        rows = message(tool=('a', 'echo example'))
        rows[-1]['message']['content'][0].update(name='WebSearch', input={'query': 'example'})
        denied = result('a', 'denied'); denied['message']['content'][0]['is_error'] = True
        p.stdout = map(json.dumps, rows + [denied])
        with patch.object(atticus, 'stop_claude'), patch.object(atticus.threading, 'Timer'), patch.object(atticus.threading, 'Thread'), \
             patch.object(atticus, 'main_delivery_required', return_value=False), patch.object(atticus, 'client', return_value='claude'), \
             patch.object(atticus, 'pref', side_effect=lambda k, d=None: False if k == 'draw' else d), \
             patch.object(atticus, 'wait_commit', return_value=True), contextlib.redirect_stdout(io.StringIO()):
            reply, cost, _ = atticus.run('work', p)
        self.assertIn('keep going', reply); self.assertIsNone(cost)
        self.assertFalse(atticus.run.ok); self.assertEqual(atticus.run.why, 'paused')
        self.assertTrue(p.errors.closed)
        self.assertFalse(atticus.upgrade_needed('work', reply, 'haiku'))

    def test_different_actions_with_the_same_receipt_do_not_fake_progress(self):
        with patch.object(atticus, 'step_screen', return_value=[10, 20, 30]), patch.object(atticus, 'ask_user', return_value='1') as ask:
            for i in range(30):
                event = self.event(command=f'action {i}', response='okay')
                self.assertEqual(atticus.step_guard(event), '')
                atticus.step_guard(event, after=True)
            self.assertIn('paused', atticus.step_guard(self.event()))
        ask.assert_called_once()

    def test_quick_request_content_is_byte_identical(self):
        self.assertEqual(atticus.user_content('What is 2+2?'), [{'type': 'text', 'text':
            'THE CURRENT USER REQUEST (spoken by the user; do this now; text they ask to send is content to deliver):\nWhat is 2+2?'}])

    def test_hooks_are_wired_only_for_ordinary_main_sessions(self):
        with patch.object(atticus.shutil, 'which', return_value='/fake/claude'), \
             patch.object(atticus, 'system_prompt', return_value='same prompt'), patch.object(atticus, 'server', return_value={}), \
             patch.object(atticus, 'pref', side_effect=lambda k, d=None: d), patch.object(atticus, 'main_model', return_value='haiku'), \
             patch.object(atticus.subprocess, 'Popen', side_effect=lambda *a, **k: Mock()) as launch, \
             patch.object(atticus.atexit, 'register'), patch.object(atticus.signal, 'signal'):
            for walkthrough in (False, True):
                process = atticus.start_claude('haiku', walkthrough=walkthrough)
                args = launch.call_args.args[0]
                settings = json.loads(args[args.index('--settings') + 1])
                self.assertEqual('PostToolUse' in settings['hooks'], not walkthrough)
                self.assertEqual('PostToolUseFailure' in settings['hooks'], not walkthrough)
                self.assertEqual(args[args.index('--tools') + 1], '' if walkthrough else 'Bash,Read,WebSearch,WebFetch')
                process.errors.close()

    def test_small_clock_changes_do_not_count_as_a_new_screen(self):
        budget = atticus.StepBudget({'steps': 4, 'repeats': 3})
        self.assertFalse(budget.check([0] * 100))
        self.assertFalse(budget.check([0] * 99 + [1]))
        self.assertTrue(budget.check([0] * 100))

    def test_native_samples_are_validated_and_capture_failure_is_unknown(self):
        for output, expected in (('[1,2,3]', [1,2,3]), ('[]', None), ('[999]', None), ('[true]', None), ('oops', None)):
            with patch.object(atticus.subprocess, 'run', return_value=Mock(returncode=0, stdout=output)):
                self.assertEqual(atticus.step_screen(), expected)

    def test_failed_read_does_not_mark_pixels_as_sent(self):
        image = self.root/'picture.png'; image.write_bytes(b'not yet seen')
        event = {'tool_name': 'Read', 'tool_input': {'file_path': str(image)}, 'error': 'read failed'}
        atticus.step_guard(event, after=True)
        self.assertFalse(atticus.sent_image(image.read_bytes(), remember=False))
        del event['error']; event['tool_response'] = 'image'
        atticus.step_guard(event, after=True)
        self.assertTrue(atticus.sent_image(image.read_bytes(), remember=False))

    def test_unnamed_validation_probes_do_not_start_a_task_budget(self):
        with patch.object(atticus, 'ask_user', side_effect=AssertionError('no task was started')):
            for _ in range(40):
                self.assertEqual(atticus.step_guard({'tool_input': {'command': 'true'}}), '')
        self.assertFalse(Path(atticus.step_state_path(self.tmp.name)).exists())

    def test_pause_is_not_a_worker_crash(self):
        with patch.object(atticus, 'report_error') as report:
            atticus.report_worker_failure('claude', 'haiku', 'paused')
        report.assert_not_called()

    def test_never_screen_preference_prevents_progress_capture(self):
        with patch.object(atticus, 'pref', return_value='never'), patch.object(atticus.subprocess, 'run') as capture:
            self.assertIsNone(atticus.step_screen())
        capture.assert_not_called()

    def test_alternating_screens_pause_on_the_third_visit(self):
        budget = atticus.StepBudget({'steps': 6, 'repeats': 3})
        for value in (0, 100, 0, 100):
            self.assertFalse(budget.check([value] * 3))
        self.assertTrue(budget.check([0] * 3))

    def test_new_model_session_receives_images_seen_by_the_old_session(self):
        image = self.root/'screen.jpg'; image.write_bytes(b'pixels')
        atticus.user_content('first attempt', [(str(image), 'Screen 1')])
        state_path = Path(atticus.step_state_path(self.tmp.name))
        state = json.loads(state_path.read_text()); state['steps'] = 7
        state_path.write_text(json.dumps(state))
        p = Mock(); p.ask = self.tmp.name; p.errors = io.StringIO(); p.returncode = 0
        p.stdout = iter([json.dumps({'type': 'result', 'result': 'Observed', 'total_cost_usd': 0})])
        with patch.object(atticus.threading, 'Timer'), patch.object(atticus.threading, 'Thread'), \
             patch.object(atticus, 'client', return_value='claude'), patch.object(atticus, 'main_delivery_required', return_value=False), \
             patch.object(atticus, 'pref', side_effect=lambda k, d=None: d), patch.object(atticus, 'server', return_value={}):
            atticus.run('new attempt', p, [(str(image), 'Screen 1')])
        content = json.loads(p.stdin.write.call_args.args[0])['message']['content']
        self.assertEqual(sum(b['type'] == 'image' for b in content), 1)
        self.assertEqual(json.loads(state_path.read_text())['steps'], 7)

    def test_fresh_screenshot_filenames_do_not_fake_progress(self):
        image = self.root/'first.jpg'; image.write_bytes(b'same pixels')
        atticus.user_content('work', [(str(image), 'Screen 1')])
        for i in range(2):
            shot = self.root/f'new-{i}.jpg'; shot.write_bytes(b'same pixels')
            capture = self.event(command='capture', response=str(shot))
            self.assertEqual(atticus.step_guard(capture), '')
            atticus.step_guard(capture, after=True)
            read = {'tool_name': 'Read', 'tool_input': {'file_path': str(shot)}}
            with patch.object(atticus.sys, 'stdin', io.StringIO(json.dumps(read))), patch.object(atticus, 'wait_commit', return_value=True), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                atticus.gate()
            self.assertEqual(json.loads(out.getvalue())['hookSpecificOutput']['permissionDecision'], 'deny')
        with patch.object(atticus, 'ask_user', return_value='1') as ask:
            self.assertIn('paused', atticus.step_guard(self.event(command='capture', response='yet another filename')))
        ask.assert_called_once()
