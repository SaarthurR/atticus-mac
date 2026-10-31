"""Turn phases with fake clocks, scratch logs and no app/window access."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import atticus


class TurnTimingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = 100.0
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(atticus, DIR=self.tmp.name, TURN={}))
        self.stack.enter_context(patch.object(atticus.time, 'monotonic', side_effect=lambda: self.clock))
        self.wall = self.stack.enter_context(patch.object(atticus.time, 'time', side_effect=lambda: 900 + self.clock))
        self.sent = self.stack.enter_context(patch.object(atticus, 'posthog'))
        self.stack.enter_context(patch.object(atticus, 'main_model', return_value='haiku'))
        self.stack.enter_context(patch.object(atticus.replay, 'ran', [], create=True))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))

    def rows(self):
        return atticus.read_rows(str(Path(self.tmp.name) / 'log.jsonl'))

    def test_first_answer_once_after_confirmation_and_monotonic_finish(self):
        atticus.begin_turn('Fixture request')
        self.clock = 102
        atticus.say('▸', 'Progress')
        atticus.say('…', '')
        self.assertNotIn('first_answer_secs', atticus.TURN)
        self.clock = 105  # includes transcript confirmation and overlapping helper work
        atticus.say('…', 'Visible fixture answer')
        self.clock = 107
        atticus.say('…', 'Visible fixture answer continued')
        self.wall.side_effect = None
        self.wall.return_value = -500  # wall clock adjustments cannot change elapsed phases
        self.clock = 109
        atticus.log_turn('Fixture request', 'Fixture answer', 1000)
        atticus.say('✓', 'Fixture answer')
        row = self.rows()[0]
        self.assertIn('first_answer_secs', row)
        self.assertEqual(row['first_answer_secs'], 5)
        self.assertEqual(row['done_secs'], 9)
        self.assertEqual(row['secs'], 9)
        self.assertEqual(row['outcome'], 'done')
        self.assertEqual(self.sent.call_count, 1)
        props = self.sent.call_args.args[1]
        self.assertEqual(props['first_answer_secs'], 5)
        self.assertNotIn('Fixture', json.dumps(props))

    def test_stream_ignores_unconfirmed_text_then_records_emission(self):
        commit = Path(self.tmp.name) / 'commit'
        os.environ.update(ATTICUS_UI='1', ATTICUS_COMMIT=str(commit))
        atticus.begin_turn('Fixture request')
        text = 'A fixture answer with enough characters to pass the existing streaming threshold. ' * 3
        worker = Mock(ask='', returncode=0, stdin=io.StringIO(), errors=io.StringIO())
        def stream():
            yield json.dumps({'type': 'stream_event', 'event': {'type': 'message_start'}})
            for at in (102, 106):
                self.clock = at
                if at == 106: commit.touch()
                yield json.dumps({'type': 'stream_event', 'event': {'delta': {'type': 'text_delta', 'text': text}}})
                if at == 102: self.assertNotIn('first_answer_secs', atticus.TURN)
            self.clock = 108
            yield json.dumps({'type': 'result', 'result': text, 'is_error': False})
        worker.stdout = stream()
        with patch.object(atticus, 'client', return_value='claude'), patch.object(atticus.threading, 'Timer'), \
             patch.object(atticus, 'pref', side_effect=lambda key, default=None: default):
            reply, _, _ = atticus.run('Fixture request', worker, main_only=True)
        atticus.log_turn('Fixture request', reply, 1000)
        self.assertEqual(self.rows()[0]['first_answer_secs'], 6)
        self.assertEqual(self.rows()[0]['done_secs'], 8)

    def test_clock_discontinuity_omits_worker_duration_but_keeps_result(self):
        atticus.begin_turn('Fixture request')
        brief = {'title': 'Fixture', 'brief': 'Fixture'}
        atticus.persist_handoff(brief, 0)
        atticus.log_turn('Fixture request', 'Transferred', 1000)
        self.clock = 110
        self.wall.side_effect = None
        self.wall.return_value = 2000
        atticus.log_handoff_result({**brief, 'status': 'stopped'})
        self.assertEqual(self.rows()[0]['outcome'], 'cancelled')
        self.assertNotIn('done_secs', self.rows()[0])

    def test_telemetry_rejects_text_in_duration_fields(self):
        atticus.ask_done({'status': 'completed', 'first_answer_secs': 'Fixture secret', 'done_secs': float('nan')})
        self.assertNotIn('Fixture', json.dumps(self.sent.call_args.args[1]))
        self.assertNotIn('done_secs', self.sent.call_args.args[1])

    def test_cancellation_has_no_invented_answer_and_keeps_exact_duration(self):
        atticus.begin_turn('Fixture request')
        self.clock = 103.25
        atticus.end_turn()
        row = self.rows()[0]
        self.assertEqual(row['done_secs'], 3.25)
        self.assertEqual(row['outcome'], 'cancelled')
        self.assertNotIn('first_answer_secs', row)

    def test_handoffs_join_all_workers_without_claiming_dispatch_is_done(self):
        atticus.begin_turn('Fixture request')
        self.clock = 104
        briefs = [{'title': 'Fixture', 'brief': 'Fixture'}, {'title': 'Fixture', 'brief': 'Fixture'}]
        for brief in briefs:
            atticus.persist_handoff(brief, 0)
        atticus.log_turn('Fixture request', 'Transferred', 1000)
        row = self.rows()[0]
        self.assertEqual(row['handoff_secs'], 4)
        self.assertEqual(row['outcome'], 'unverified')
        self.assertNotIn('done_secs', row)
        # The supervisor receives these same briefs; no worker or real app is launched.
        self.clock = 112
        atticus.log_handoff_result({**briefs[0], 'status': 'done'})
        self.assertNotIn('done_secs', self.rows()[0])
        self.clock = 115
        atticus.log_handoff_result({**briefs[1], 'status': 'failed'})
        row = self.rows()[0]
        self.assertEqual(row['done_secs'], 15)
        self.assertEqual(row['outcome'], 'not_done')
        self.assertEqual(len(row['handoff_results']), 2)
        self.assertNotIn('Fixture', json.dumps(self.sent.call_args_list, default=str))

    def test_supervisor_preserves_links_when_another_turn_steers_same_worker(self):
        manager = atticus.Agents.__new__(atticus.Agents)
        manager.lock, manager.rows, manager.offers = threading.RLock(), {}, set()
        manager.idle, manager.processes = None, {}
        manager.emit = lambda event: None
        manager.running = lambda: 3  # queued scratch agent; no process is launched
        briefs = []
        for at in (100, 102):
            self.clock = at
            atticus.begin_turn('Fixture request')
            brief = {'title': 'Fixture', 'brief': 'Fixture'}
            if briefs: brief['steer'] = row['id']
            atticus.persist_handoff(brief, 0)
            atticus.log_turn('Fixture request', 'Transferred', 1000)
            if briefs:
                with patch.object(manager, 'steer', return_value=row): manager.prepare(brief)
            else: row = manager.prepare(brief)
            briefs.append(brief)
        self.clock = 110
        row.update(status='stopped', ended=1010)
        manager.save(row)
        rows = self.rows()
        self.assertEqual([r['done_secs'] for r in rows], [10, 8])
        self.assertTrue(all(r['outcome'] == 'cancelled' for r in rows))
        before = (Path(self.tmp.name) / 'log.jsonl').read_text()
        manager.save(row)  # later saves cannot replace the recorded worker result
        self.assertEqual((Path(self.tmp.name) / 'log.jsonl').read_text(), before)

    def test_continuation_replaces_attempt_terminal_time_with_turn_finish(self):
        atticus.begin_turn('Fixture request')
        self.clock = 103
        atticus.end_turn('timed_out', emit=False)
        self.clock = 105
        atticus.checkpoint(status='running')
        self.clock = 111
        atticus.log_turn('Fixture request', 'Fixture answer', 1000)
        atticus.say('✓', 'Fixture answer')
        self.assertEqual(self.rows()[0]['done_secs'], 11)
        self.assertEqual(self.rows()[0]['outcome'], 'done')

    def test_failed_answer_telemetry_includes_first_emission(self):
        atticus.begin_turn('Fixture request')
        self.clock = 103
        atticus.end_turn('failed', emit=False)
        atticus.log_turn('Fixture request', 'Fixture failure', 1000)
        self.clock = 104
        atticus.say('!', 'Fixture failure')
        self.assertEqual(self.sent.call_count, 1)
        self.assertEqual(self.sent.call_args.args[1]['first_answer_secs'], 4)

    def test_failed_handoff_persistence_does_not_mark_turn_transferred(self):
        atticus.begin_turn('Fixture request')
        with patch.object(atticus, 'private_json', side_effect=OSError):
            with self.assertRaises(OSError):
                atticus.persist_handoff({'title': 'Fixture', 'brief': 'Fixture'}, 0)
        self.assertNotIn('handoff_ids', atticus.TURN)
        self.clock = 106
        atticus.log_turn('Fixture request', 'Fixture answer', 1000)
        self.assertEqual(self.rows()[0]['done_secs'], 6)
        self.assertEqual(self.rows()[0]['outcome'], 'done')

    def test_missing_monotonic_origin_stays_missing(self):
        atticus.log_handoff_result({'handoffId': 'fixture', 'status': 'done'})
        self.assertFalse((Path(self.tmp.name) / 'log.jsonl').exists())

    def test_action_completion_is_unverified_without_goal_receipt(self):
        atticus.begin_turn('Fixture request')
        self.clock = 102
        atticus.log_turn('Fixture request', 'Fixture answer', 1000, ran=['fixture-command'])
        self.assertEqual(self.rows()[0]['outcome'], 'unverified')
