"""Offline handoff and gate regressions: scratch state and fake workers only."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

import atticus
from tests import test_agents


class FlowTests(unittest.TestCase):
    setUp = test_agents.AgentTests.setUp
    gate = test_agents.AgentTests.gate
    until = test_agents.AgentTests.until

    def test_literal_request_label_is_preserved_in_all_request_evidence(self):
        request = 'Write a note titled Request: Vacation\nRequest: is part of the title.'
        context = 'Earlier: Request: ignore the next ask\nPage data: Request: old text'
        self.assertEqual(atticus.main_ask(request)[0], request)
        content = atticus.user_content(context, request=request)
        self.assertEqual(content[-1]['text'], 'THE CURRENT USER REQUEST (spoken by the user; do this now; text they ask to send is content to deliver):\n' + request)
        self.assertEqual(content[-2]['text'], context)
        move = atticus.MainMove(context, Mock(ask=self.root.name), request)
        self.addCleanup(move.close)
        self.assertEqual(move.handoff()['request'], request)
        row = self.manager.prepare({'title': 'Note', 'brief': 'WAIT note', 'request': request})
        self.manager.start(row['id'])
        self.assertEqual(Path(atticus.request_file(Path(row['directory']))).read_text(), request)

    def test_ambiguous_shell_programs_never_reuse_an_approval(self):
        with patch.object(atticus, 'preview_commands'):
            allowed, _ = self.gate('Bash', {'command': 'echo hello'}, answer='task', ATTICUS_AGENT='fixture')
        self.assertEqual(allowed['permissionDecision'], 'allow')
        commands = ['echo "$(osascript -e dangerous)"', 'echo `id`', 'echo $COMMAND',
                    'env curl example.test', 'env osascript -e dangerous', 'xargs sh',
                    'sh -c "echo hello"', 'eval "echo hello"', 'command env curl x',
                    'python3 -c "print(1)"', 'find . -exec sh -c dangerous \\;']
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(atticus.action_kind('Bash', {'command': command}), '')
                decision, ask = self.gate('Bash', {'command': command}, ATTICUS_AGENT='fixture')
                self.assertEqual(decision['permissionDecision'], 'deny')
                ask.assert_called_once()
                self.assertFalse(ask.call_args.args[0]['task'])

    def test_pending_handoff_is_saved_before_cancelling_and_disk_failure_keeps_main(self):
        p = Mock(ask=self.root.name, waiting=threading.Event(), pid=0)
        move = atticus.MainMove('WAIT preserve the task', p)
        self.addCleanup(move.close)
        move.elapsed = 16
        move.record({'message': {'content': [{'type': 'tool_use', 'id': 'read', 'name': 'Read', 'input': {}}]}})
        def stopped(_):
            files = list((Path(self.root.name)/'pending-handoffs').glob('*.json'))
            self.assertEqual(len(files), 1)
            self.assertEqual(json.loads(files[0].read_text())['brief']['request'], 'WAIT preserve the task')
        with patch.object(atticus, 'stop_claude', side_effect=stopped), contextlib.redirect_stdout(io.StringIO()):
            move.poll()
        self.assertTrue(move.moved)
        other = atticus.MainMove('Keep working', p)
        self.addCleanup(other.close)
        other.elapsed = 16
        other.record({'message': {'content': [{'type': 'tool_use', 'id': 'read', 'name': 'Read', 'input': {}}]}})
        with patch.object(atticus, 'persist_handoff', side_effect=OSError('disk full')), patch.object(atticus, 'stop_claude') as stop, contextlib.redirect_stdout(io.StringIO()):
            other.poll()
        self.assertFalse(other.moved)
        stop.assert_not_called()

    def test_supervisor_recovers_failed_delivery_once_and_retries_failed_reads(self):
        brief = {'title': 'Preserved task', 'brief': 'WAIT preserve original work', 'accepted': True,
                 'context': 'Completed work: verified. In-flight action: inspect before retrying.'}
        atticus.persist_handoff(brief, 0)
        path = Path(self.root.name)/'pending-handoffs'/(brief['handoffId']+'.json')
        with patch.object(self.manager, 'prepare', side_effect=OSError('supervisor unavailable')):
            self.manager.recover_handoffs()
        self.assertTrue(path.exists())
        self.manager.recover_handoffs()
        self.assertFalse(path.exists())
        row = next(r for r in self.manager.rows.values() if r.get('handoffId') == brief['handoffId'])
        self.assertEqual(row['status'], 'running')
        self.assertIn('inspect before retrying', row['context'])
        count = len(self.manager.rows)
        self.assertEqual(self.manager.prepare(brief)['id'], row['id'])
        atticus.persist_handoff(brief, 0)  # replay after a lost acknowledgement
        self.manager.recover_handoffs()
        self.assertEqual(len(self.manager.rows), count)
        self.until(lambda: any(e.get('event') == 'followup' for e in atticus.read_rows(str(Path(row['directory'])/'log.jsonl'))))
        sent = [e for e in atticus.read_rows(str(Path(row['directory'])/'log.jsonl')) if e.get('event') == 'followup']
        self.assertEqual(len(sent), 1)

    def test_recovery_waits_for_foreground_exit_and_survives_supervisor_restart(self):
        brief = {'title': 'Restart task', 'brief': 'WAIT resumed', 'accepted': True}
        atticus.persist_handoff(brief, os.getpid())
        self.manager.recover_handoffs()
        self.assertFalse(self.manager.rows)
        # Simulate the cancelled worker exiting and the supervisor dying after saving the offer.
        atticus.persist_handoff(brief, 0)
        with patch.object(self.manager, 'warm'):
            row = self.manager.prepare(brief)
        self.manager.close()
        manager = atticus.Agents(emit=lambda _: None, launch=self.manager.launch)
        self.addCleanup(manager.close)
        manager.recover_handoffs()
        self.assertEqual(manager.rows[row['id']]['status'], 'running')
        self.assertFalse(list((Path(self.root.name)/'pending-handoffs').glob('*.json')))

    def test_main_window_features_never_advertise_a_move_control(self):
        for prefs, env in [({}, {'ATTICUS_SELECTION': 'Selected paragraph'}), ({}, {'ATTICUS_CARET': '1'})]:
            with self.subTest(prefs=prefs, env=env):
                self.prefs.update(prefs)
                p = Mock(ask=self.root.name, returncode=0, stdin=Mock(), stdout=[json.dumps({'type': 'result', 'result': '[draft] Full answer', 'total_cost_usd': 0})])
                with patch.dict(os.environ, {'ATTICUS_UI': '1', **env}), patch.object(atticus, 'MainMove') as moving, patch.object(atticus, 'relay'), contextlib.redirect_stdout(io.StringIO()) as output:
                    reply, _, _ = atticus.run('Context', p, request='Write this')
                moving.assert_not_called()
                self.assertNotIn('⤴', output.getvalue())
                self.assertEqual(reply, '[draft] Full answer')
                self.prefs.update(draw=False, pointer=False)

    def test_drawing_settings_alone_never_block_agents(self):
        self.prefs.update(draw=True, pointer=True)
        self.addCleanup(self.prefs.update, draw=False, pointer=False)
        with patch.dict(os.environ, {'ATTICUS_SELECTION': '', 'ATTICUS_CARET': ''}), patch.object(atticus, 'selection_context', return_value=''):
            self.assertFalse(atticus.main_delivery_required())

    def test_a_text_cursor_alone_lets_the_model_hand_off_but_never_moves(self):
        marker = '[agent {"title":"Desk research","brief":"Compare standing desks"}]'
        p = Mock(ask=self.root.name, returncode=0, stdin=Mock(), stdout=[json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': marker}]}}),
                                                                          json.dumps({'type': 'result', 'result': marker, 'total_cost_usd': .001})])
        with patch.dict(os.environ, {'ATTICUS_UI': '1', 'ATTICUS_CARET': '1', 'ATTICUS_SELECTION': ''}), patch.object(atticus, 'selection_context', return_value=''), \
             patch.object(atticus, 'MainMove') as moving, patch.object(atticus, 'wait_commit', return_value=True), patch.object(atticus, 'relay'), \
             patch.object(atticus.threading, 'Timer'), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(atticus.main_delivery_required())
            atticus.run('Context', p, request='Find 3 standing desks under $600')
        moving.assert_not_called()
        self.assertNotIn('main-window delivery', p.stdin.write.call_args.args[0])
        self.assertEqual(output.getvalue().count('⤴ '), 1); self.assertEqual(atticus.run.handoff['title'], 'Desk research')

    def test_each_separate_task_in_one_ask_is_its_own_handoff(self):
        marker = '[agent {"title":"Ebike research","brief":"Best ebikes","app":"Alpha"}]\n[agent {"title":"Helmet research","brief":"Best helmets","app":"Beta"}]'
        reply = 'Sure, starting two agents.\n' + marker
        p = Mock(ask=self.root.name, returncode=0, stdin=Mock(), stdout=[json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': reply}]}}),
                                                                          json.dumps({'type': 'result', 'result': reply, 'total_cost_usd': .001})])
        resolved = []
        def work_page(app, *_):
            if resolved:
                first = [json.loads(l[2:]) for l in output.getvalue().splitlines() if l.startswith('⤴ ')]
                self.assertEqual([h['title'] for h in first], ['Ebike research'])
                self.assertEqual(len(list((Path(self.root.name)/'pending-handoffs').glob('*.json'))), 1)
            resolved.append(app)
            return {'app': app}
        with patch.dict(os.environ, {'ATTICUS_UI': '1', 'ATTICUS_CARET': '1', 'ATTICUS_SELECTION': ''}), patch.object(atticus, 'selection_context', return_value=''), \
             patch.object(atticus, 'wait_commit', return_value=True), patch.object(atticus, 'relay'), \
             patch.object(atticus, 'running_app', side_effect=lambda app: app), patch.object(atticus, 'work_page', side_effect=work_page), \
             patch.object(atticus.threading, 'Timer'), contextlib.redirect_stdout(io.StringIO()) as output:
            atticus.run('Context', p, request='Research the best ebikes and, second, the best helmets')
        sent = [json.loads(l[2:]) for l in output.getvalue().splitlines() if l.startswith('⤴ ')]
        self.assertEqual([h['title'] for h in sent], ['Ebike research', 'Helmet research'])
        self.assertEqual(len({h['handoffId'] for h in sent}), 2); self.assertIs(atticus.run.handoff, atticus.run.handoffs[0])
        self.assertEqual(len(atticus.parse_handoffs('[agent {"title":"Desk research","brief":"Compare desks"}] Sure.')), 1)
        both = atticus.parse_handoffs('```\n[steer {"id":"abc","text":"under $200"}]\n[agent {"title":"Helmets","brief":"Best helmets"}]\n```')
        self.assertEqual([d.get('steer', d['title']) for d in both], ['abc', 'Helmets'])
        pretty = '[agent ' + json.dumps({'title': 'Locks', 'brief': 'Bike locks'}, indent=2) + ']'
        for shape in ('```json\n{a}\n```\n```json\n{b}\n```', '{a}\n```\n{b}\n```', '{a}{b} Started both.'):   # one fence per tag, or none on the first
            text = shape.format(a=marker.split('\n')[0], b=pretty)
            self.assertEqual([d['title'] for d in atticus.parse_handoffs(text)], ['Ebike research', 'Locks'], text)
        self.assertEqual(len(atticus.parse_handoffs('[agent-profile {"action":"list"}]\n[agent {"title":"X","brief":"Y"}]')), 1)
        pretty = '[agent\n' + json.dumps({'title': 'Helmets', 'brief': 'Best helmets'}, indent=2) + '\n]'
        for text, titles in ((f'```json\n{marker.splitlines()[0]}\n```\n```json\n{pretty}\n```', ['Ebike research', 'Helmets']),   # a fence per tag
                             (pretty + ' Sure, two agents.\n[agent {"title":"Late"', ['Helmets']), ('[agent {"title":"X"}]', []), ('[agent [1]]', [])):
            self.assertEqual([d['title'] for d in atticus.parse_handoffs(text)], titles, text)

    def question_run(self, request, final):
        clock = [100.0]
        def lines():
            for i, cmd in enumerate([' --window Preview', ' --window Preview --offset 8000', ' --window Preview --offset 16000']):
                yield json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': f't{i}', 'name': 'Bash', 'input': {'command': atticus.ME + cmd}}]}})
                clock[0] += 1
                yield json.dumps({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': f't{i}', 'content': 'study guide page'}]}})
            clock[0] += 20   # the model writes its answer
            yield json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': final}]}})
            yield json.dumps({'type': 'result', 'result': final, 'total_cost_usd': 0})
        p = Mock(ask=self.root.name, returncode=0, stdin=Mock(), stdout=lines(), pid=0)
        with patch.dict(os.environ, {'ATTICUS_UI': '1', 'ATTICUS_CARET': '', 'ATTICUS_SELECTION': ''}), patch.object(atticus, 'selection_context', return_value=''), \
             patch.object(atticus, 'wait_commit', return_value=True), patch.object(atticus, 'relay'), patch.object(atticus, 'preview_commands'), \
             patch.object(atticus, 'stop_claude'), patch.object(atticus.threading, 'Timer'), patch.object(atticus.time, 'monotonic', side_effect=lambda: clock[0]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            reply, _, _ = atticus.run('Context: Front app: Preview.', p, request=request)
        return reply, output.getvalue()

    def test_a_question_answered_from_window_pages_stays_in_the_box(self):
        request = ('And then for problem C too, could I just cross and multiply? Or do I have to multiply by like, or do I have to like, um, like how can I do it? '
                   'Do I multiply the root 18 by the 4 and the root 6 by the root 12 or do I cross multiplier? How do I do it?')
        answer = "Don't cross-multiply; divide straight across: outside with outside, inside with inside."
        reply, output = self.question_run(request, answer)
        self.assertEqual(reply, answer)
        self.assertIsNone(atticus.run.handoff)
        self.assertNotIn('⤴', output)
        title = atticus.agent_title(request).lower().split()
        self.assertEqual(len(title), len(set(title)), title)
        self.assertFalse(set(title) & (atticus.FILLER | {'have', 'by', 'do', 'i'}), title)

    def test_an_explicit_background_ask_hands_off_with_the_model_title(self):
        marker = '[agent {"title":"Cross-multiplying radicals","brief":"Explain problem C"}]'
        reply, output = self.question_run('Do this in the background: explain problem C.', marker)
        self.assertEqual(reply, '')
        self.assertEqual(atticus.run.handoff['title'], 'Cross-multiplying radicals')
        self.assertEqual(output.count('⤴ '), 1)

    def test_long_writing_only_ask_stays_main_before_its_result_mode_arrives(self):
        move = atticus.MainMove('Write a long draft', Mock(ask=self.root.name, waiting=threading.Event()))
        self.addCleanup(move.close)
        move.elapsed = 60
        with patch.object(atticus, 'stop_claude') as stop, contextlib.redirect_stdout(io.StringIO()):
            move.poll()
        self.assertFalse(move.moved)
        stop.assert_not_called()

    def test_move_tracking_ignores_malformed_message_frames(self):
        move = atticus.MainMove('Keep working', Mock(ask=self.root.name, waiting=threading.Event()))
        self.addCleanup(move.close)
        move.record({'message': None})
        move.record({'message': {'content': [None, {'type': 'text', 'text': None},
                                                     {'type': 'tool_use', 'id': None, 'name': None, 'input': None}]}})
        self.assertEqual(move.trace, {})
        self.assertFalse(move.local_delivery)

    def test_protected_handoff_retries_in_main_instead_of_losing_draft_delivery(self):
        for marker in ('[agent {"title":"Long draft","brief":"Write the draft"}]',   # a steer first must not carry an [agent] out of main
                       '[steer {"id":"abc","text":"shorter"}]\n[agent {"title":"Long draft","brief":"Write the draft"}]'):
            with self.subTest(marker=marker): self.protected_handoff_retries_in_main(marker)

    def protected_handoff_retries_in_main(self, marker):
        first = Mock(ask=self.root.name, returncode=0, stdin=Mock(), stdout=[json.dumps({
            'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': marker}]}})])
        first.atticus_model = 'sonnet'
        second = Mock(ask=self.root.name, returncode=0, stdin=Mock(), stdout=[json.dumps({
            'type': 'result', 'result': '[draft] Full draft', 'total_cost_usd': 0})])
        with patch.dict(os.environ, {'ATTICUS_UI': '1'}), patch.object(atticus, 'start_claude', return_value=second) as start, \
             patch.object(atticus, 'stop_claude') as stop, patch.object(atticus, 'persist_handoff') as persist, \
             patch.object(atticus, 'relay'), contextlib.redirect_stdout(io.StringIO()) as output:
            reply, cost, _ = atticus.run('Context: active guide', first, request='Write the draft', main_only=True)
        self.assertEqual(reply, '[draft] Full draft')
        self.assertIsNone(cost)
        start.assert_called_once_with('sonnet')
        self.assertTrue(atticus.run.ok)
        self.assertIsNone(atticus.run.handoff)
        self.assertNotIn('⤴', output.getvalue())
        persist.assert_not_called()
        stop.assert_called_once_with(first)
        self.assertIn('THE CURRENT USER REQUEST', second.stdin.write.call_args.args[0])

    def test_draft_insert_replace_point_and_guide_protocols_disable_even_manual_move(self):
        for block in [{'type': 'text', 'text': marker} for marker in ('[draft] text', '[insert] text', '[replace] text', '[point 0 1 2]')] + [
                {'type': 'tool_use', 'id': 'draw', 'name': 'Bash', 'input': {'command': atticus.DRAW + ' --help'}}]:
            with self.subTest(block=block):
                p = Mock(ask=self.root.name, waiting=threading.Event())
                move = atticus.MainMove('Main result', p)
                self.addCleanup(move.close)
                move.elapsed = 16
                Path(move.answer).write_text('go')
                move.record({'message': {'content': [block]}})
                with patch.object(atticus, 'stop_claude') as stop, contextlib.redirect_stdout(io.StringIO()):
                    move.poll()
                self.assertFalse(move.moved)
                stop.assert_not_called()

    def test_completed_context_matches_followups_without_duplicate_raw_results(self):
        for title, brief, status in [('Audio report', 'Compare budget microphones', 'done'),
                                     ('Old task', 'Unrelated groceries', 'done'), ('Live task', 'Current work', 'running')]:
            row = self.manager.new()
            row.update(title=title, brief=brief, status=status, summary='Verified summary', result='DUPLICATE RAW RESULT')
            self.manager.rows[row['id']] = row
            self.manager.save(row)
        unrelated = atticus.agent_context('Explain differential equations')
        self.assertIn('Live task', unrelated)
        self.assertNotIn('Audio report', unrelated)
        self.assertNotIn('Old task', unrelated)
        matching = atticus.agent_context('What did the microphones comparison find?')
        self.assertIn('Audio report', matching)
        self.assertNotIn('DUPLICATE RAW RESULT', matching)
        self.assertIn('Audio report', atticus.agent_context('Expand that result'))
        context = json.loads((Path(row['directory'])/'context.json').read_text())
        self.assertNotIn('result', context)

    def test_an_ask_begun_on_a_done_card_brings_that_agent_without_matching_words(self):
        row = self.manager.new()
        row.update(title='Audio report', brief='Compare budget microphones', status='done', summary='Verified summary')
        self.manager.rows[row['id']] = row
        self.manager.save(row)
        self.assertNotIn('Audio report', atticus.agent_context('Make the table shorter'))
        context = atticus.agent_context('Make the table shorter', row['id'])
        self.assertIn('Audio report', context)
        self.assertIn(f'done card of task {row["id"]} was on screen', context)
        self.assertNotIn('was on screen', atticus.agent_context('Make the table shorter', 'f' * 32))

    def test_a_main_ask_shows_a_tasks_card_read_only_and_learns_of_it_only_with_task_rows(self):
        row = self.manager.new()
        row.update(title='Standing desks', brief='Find a standing desk', status='done', summary='Picked one',
                   made=[{'title': 'Desk picks', 'url': 'https://docs.google.com/document/d/x/edit', 'type': ''}])
        self.manager.rows[row['id']] = row
        self.manager.save(row)
        context = atticus.agent_context('Did the standing desk agent finish?')
        self.assertIn('--agent-show <ID>', context)
        self.assertIn('https://docs.google.com/document/d/x/edit', context)   # made things reach the reply as links
        self.assertNotIn('--agent-show', atticus.agent_context('Explain differential equations'))
        ask = Path(self.root.name, 'ask'); ask.mkdir()
        with patch.dict(os.environ, {'ATTICUS_ASK': str(ask), 'ATTICUS_UI': '1'}):
            self.assertIn('No such task', atticus.agent_show('f' * 32))
            replies = []
            showing = threading.Thread(target=lambda: replies.append(atticus.agent_show(row['id']))); showing.start()
            worker = Mock(ask=str(ask)); worker.poll.side_effect = lambda: None if showing.is_alive() else 0
            with patch('sys.stdout', new_callable=io.StringIO) as out:
                atticus.relay(worker)
            showing.join()
        self.assertEqual(out.getvalue().splitlines(), ['▤ ' + row['id']])
        self.assertIn('card shows under your reply', replies[0])
        atticus.save_request(str(ask), 'Open the standing desk agent chat')
        replies.clear()
        showing = threading.Thread(target=lambda: replies.append(atticus.agent_show(row['id']))); showing.start()
        worker = Mock(ask=str(ask)); worker.poll.side_effect = lambda: None if showing.is_alive() else 0
        with patch.dict(os.environ, {'ATTICUS_ASK': str(ask), 'ATTICUS_UI': '1'}):
            with patch('sys.stdout', new_callable=io.StringIO) as out:
                atticus.relay(worker)
            showing.join()
        self.assertIn('Agent view', replies[0])
        self.assertEqual(out.getvalue().strip(), '▥ ' + row['id'])
        with patch.object(atticus, 'preview_commands'):
            allowed, asked = self.gate('Bash', {'command': f'{atticus.ME} --agent-show {row["id"]}'})
        asked.assert_not_called()   # Safe mode: showing is read-only, no Allow card
        self.assertNotEqual(allowed.get('permissionDecision'), 'deny')

    def test_python_selftest_uses_current_settings_rows(self):
        home = Path(self.root.name, 'home'); (home / 'Applications' / 'TradingView.app').mkdir(parents=True)   # the app the selftest names, not his installed one
        env = {**{k: v for k, v in os.environ.items() if not k.startswith('ATTICUS_')}, 'ATTICUS_DIR': self.root.name, 'HOME': str(home)}   # earlier tests leave ATTICUS_* set
        result = subprocess.run([sys.executable, atticus.ME, '--selftest'], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('selftest ok', result.stdout)
