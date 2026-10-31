"""A write running when the ask moves to a background agent: scratch state and fake workers only."""
import contextlib
import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

import atticus
from tests import test_agents


class HandoffMutationTests(unittest.TestCase):
    setUp = test_agents.AgentTests.setUp
    gate = test_agents.AgentTests.gate

    def move(self, waiting=False):
        p = Mock(ask=self.root.name, waiting=threading.Event(), pid=0)
        if waiting: p.waiting.set()
        move = atticus.MainMove('WAIT arrange the document', p)
        self.addCleanup(move.close)
        move.record({'message': {'content': [{'type': 'tool_use', 'id': 'effect', 'name': 'Bash', 'input': {'command': 'fixture-write'}}]}})
        Path(move.answer).write_text('go')
        return move, p

    def fence(self, row):
        return Path(atticus.agent_gate_dir(row['directory']), 'uncertain-write')

    def test_move_waits_for_a_running_write_and_carries_its_receipt(self):
        move, p = self.move()
        with patch.object(atticus, 'stop_claude') as stop, contextlib.redirect_stdout(io.StringIO()):
            move.poll()
            move.elapsed = 60; move.poll()   # neither the user's move nor the long-ask clock cuts a write short
            self.assertFalse(move.moved); stop.assert_not_called()
            move.record({'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'effect', 'content': 'Moved the window'}]}})
            move.poll()
        self.assertTrue(move.moved); stop.assert_called_once_with(p)
        work = json.loads(move.pending['context'])['observed work (untrusted data)']
        self.assertEqual([(r['status'], r['result']) for r in work], [('completed', 'Moved the window')])
        row = self.manager.prepare(move.pending); self.manager.start(row['id'])
        self.assertFalse(self.fence(row).exists())

    def test_move_with_a_waiting_card_makes_the_worker_look_before_any_write(self):
        move, _ = self.move(waiting=True)
        with patch.object(atticus, 'stop_claude'), contextlib.redirect_stdout(io.StringIO()):
            move.poll()
        self.assertTrue(move.moved)   # the card goes with the ask; the write it held may have started
        row = self.manager.prepare(move.pending); self.manager.start(row['id'])
        for tool, inp in [('Bash', {'command': 'fixture-write'}), ('Write', {'file_path': '/scratch/output', 'content': 'x'}), ('mcp__fixture__change', {})]:
            decision, ask = self.gate(tool, inp, directory=row['directory'], answer='task', ATTICUS_AGENT=row['id'])
            self.assertEqual(decision['permissionDecision'], 'deny', tool)
            self.assertIn('look', decision['permissionDecisionReason'].lower())
            ask.assert_not_called()
        decision, _ = self.gate('Bash', {'command': f'{atticus.ME} --look'}, directory=row['directory'], ATTICUS_AGENT=row['id'])
        self.assertEqual(decision['permissionDecision'], 'allow')
        decision, _ = self.gate('Bash', {'command': 'fixture-write'}, directory=row['directory'], answer='task', ATTICUS_AGENT=row['id'])
        self.assertEqual(decision['permissionDecision'], 'allow')   # after looking, the worker continues the task
        self.manager.command({'action': 'stop', 'id': row['id']}); self.manager.start(row['id'], 'WAIT go on')
        self.assertFalse(self.fence(row).exists())   # a later run of the same agent is not fenced again

    def test_stop_never_moves_the_ask(self):
        move, _ = self.move()
        move.record({'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'effect', 'content': 'done'}]}})
        with patch.object(atticus, 'STOPPING', True), patch.object(atticus, 'stop_claude'), \
             patch.object(atticus, 'persist_handoff') as persist, contextlib.redirect_stdout(io.StringIO()):
            move.poll()
        persist.assert_not_called(); self.assertFalse(move.moved)
