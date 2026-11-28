"""[do …] action tags run in this process as their text streams in, through the gate: fake Claude streams, helpers stubbed."""
import contextlib
import io
import json
import os
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import atticus
from tests.test_stream import message


class Input(io.StringIO):
    def close(self): pass


class DoTagTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(); self.addCleanup(self.root.cleanup)
        self.ask = Path(self.root.name, 'ask'); self.ask.mkdir()
        patcher = patch.multiple(atticus, DIR=self.root.name, HOME=self.root.name, PREFS=str(Path(self.root.name) / 'settings.json'))
        patcher.start(); self.addCleanup(patcher.stop)
        self.calls, self.place_many = [], atticus.place_many
        for name, reply in (('show', 'opened Safari'), ('place_many', 'Safari window -> left of laptop'), ('hands', ('clicked', True))):
            stub = patch.object(atticus, name, side_effect=lambda *a, n=name, r=reply: self.calls.append((n, a)) or r)
            stub.start(); self.addCleanup(stub.stop)
        stub = patch.object(atticus, 'free_focus'); stub.start(); self.addCleanup(stub.stop)

    def run_turns(self, *turns):
        """turns: (reply text, final result text) per model turn."""
        rows = []
        for text, final in turns:
            rows += message(text) + [{'type': 'result', 'result': final, 'total_cost_usd': .001}]
        p = Mock(); p.stdin = Input(); p.ask = str(self.ask); p.returncode = 0; p.relaying = True; p.stdout = map(json.dumps, rows)
        with patch.dict(os.environ, {'ATTICUS_UI': '1', 'ATTICUS_COMMIT': '', 'ATTICUS_ASK': str(self.ask)}), \
             patch.object(atticus.threading, 'Timer'), patch.object(atticus, 'preview_commands'), patch.object(atticus, 'step_screen', return_value=None), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            reply, _, steps = atticus.run('Request: fixture', p)
        sent = [json.loads(line) for line in p.stdin.getvalue().splitlines()]
        return reply, steps, sent, out.getvalue()

    def test_tags_run_once_in_order_in_one_turn(self):
        text = 'Opening it. [do --show "Safari"] [do --place Safari left laptop] Safari is on the left. [done]'
        reply, steps, sent, out = self.run_turns((text, text))
        self.assertEqual(self.calls, [('show', ('Safari', True)), ('place_many', (['Safari', 'left', 'laptop'],))])
        self.assertEqual(len(sent), 1)   # one model turn: nothing went back
        self.assertEqual(reply, 'Opening it. Safari is on the left.')
        self.assertEqual(len(steps), 2)
        self.assertIn('▸ ', out)
        # booked as the Bash command it stands for: learnable and replayable like before
        self.assertEqual(atticus.run.cmds, [shlex.join([atticus.ME, '--show', 'Safari']), shlex.join([atticus.ME, '--place', 'Safari', 'left', 'laptop'])])
        self.assertTrue(atticus.run.ok)

    def test_sketch_and_do_tags_share_one_reply(self):
        text = '[EXPLAIN:{"title":"A gear","draw":"One gear with eight teeth"}] Opening it. [do --show "Safari"] A gear turns. [done]'
        with patch.object(atticus, 'SketchDrawing') as sketch:
            reply, _, sent, out = self.run_turns((text, text))
        self.assertEqual(self.calls, [('show', ('Safari', True))])
        sketch.assert_called_once(); self.assertEqual(sketch.call_args[0][0], {'title': 'A gear', 'draw': 'One gear with eight teeth'})
        self.assertEqual(len(sent), 1)
        self.assertEqual(reply, 'Opening it. A gear turns.')
        self.assertNotIn('[do', out); self.assertNotIn('EXPLAIN', out); self.assertNotIn('[done', out)

    def test_denied_tag_is_refused_and_the_rest_stop(self):
        text = '[do --hands label "Send"] [do --show Safari] Done. [done]'
        reply, _, sent, _ = self.run_turns((text, text), ('It was not allowed.', 'It was not allowed.'))
        self.assertEqual(self.calls, [])   # the gate refused the first; the second never ran
        self.assertEqual(len(sent), 2)
        back = sent[1]['message']['content'][0]['text']
        self.assertIn('--hands label "Send"] failed: Use atticus.py --hands', back)
        self.assertIn('--show Safari] failed: not run', back)
        self.assertEqual(reply, 'It was not allowed.')

    def test_video_promises_through_the_model_path(self):
        moved = []
        with patch.multiple(atticus, place_many=self.place_many, proc_of=lambda app: app, request_screen=lambda: 'current',
                            place=lambda app, where='full', screen='current', title='': moved.append((app, where)) or f'{app} window -> {where} of {screen}',
                            search=lambda q: f'1. result for {q}', window_text=lambda app, offset=0, ocr=False: 'Window text: fixture page'):
            text = '[do --place "Google Chrome" left current + Terminal right current] Chrome left, Terminal right. [done]'
            self.assertEqual(self.run_turns((text, text))[0], 'Chrome left, Terminal right.')
            self.assertEqual(moved, [('Google Chrome', 'left'), ('Terminal', 'right')])
            for tag, seen in (('--search "weather today"', 'result for weather today'), ('--window', 'fixture page')):
                first = f'[do {tag}]'
                reply, _, sent, _ = self.run_turns((first, first), ('Answer from it. [done]', 'Answer from it. [done]'))
                self.assertIn(seen, sent[1]['message']['content'][0]['text']); self.assertEqual(reply, 'Answer from it.')

    def test_unlisted_flag_never_runs(self):
        self.assertEqual(atticus.do_action(['--fast', 'open Safari']), ('--fast is not an action; use Bash.', True))

    def test_risky_tag_waits_for_the_allow_card(self):
        with patch.object(atticus, 'risky', return_value='Click this?'), patch.object(atticus, 'ask_user', return_value=None) as card, \
             patch.dict(os.environ, {'ATTICUS_ASK': str(self.ask), 'ATTICUS_COMMIT': ''}):
            out, failed = atticus.do_action(['--hands', 'click', 'Buy'])
        self.assertTrue(failed); self.assertIn('The user said no', out)
        self.assertEqual(card.call_args[0][0]['q'], 'Click this?')
        self.assertEqual(self.calls, [])

    def test_cancel_during_a_tag_ends_the_ask(self):
        def cancelled():
            atticus.STOPPING = True   # what stop_workers does on the app's SIGTERM, then sys.exit(0)
            raise SystemExit(0)
        with patch.object(atticus, 'STOPPING', False), patch.object(atticus, 'main', side_effect=cancelled), \
             patch.dict(os.environ, {'ATTICUS_ASK': str(self.ask), 'ATTICUS_COMMIT': ''}), self.assertRaises(SystemExit):
            atticus.do_action(['--show', 'Safari'])

    def test_box_events_from_a_tag_reach_the_relay_not_the_model(self):
        target = '▣ ' + json.dumps({'app': 'Safari', 'window': 'Start'})
        with patch.object(atticus, 'show', side_effect=lambda *a: atticus.emit([target]) or 'opened Safari'), \
             patch.dict(os.environ, {'ATTICUS_ASK': str(self.ask), 'ATTICUS_COMMIT': '', 'ATTICUS_RELAY_OWNER': str(os.getpid())}):
            out, failed = atticus.do_action(['--show', 'Safari'])
        self.assertEqual((out, failed), ('opened Safari', False))
        self.assertEqual([p.read_text() for p in self.ask.glob('hands-*')], [target])

    def test_a_job_that_needs_the_result_gets_its_second_turn(self):
        first = 'Checking. [do --hands click "Play"]'
        reply, _, sent, _ = self.run_turns((first, first), ('It is playing. [do --show Safari] [done]', 'It is playing. [do --show Safari] [done]'))
        self.assertEqual([c[0] for c in self.calls], ['hands', 'show'])
        self.assertEqual(len(sent), 2)
        self.assertIn('[do --hands click "Play"] ok: clicked', sent[1]['message']['content'][0]['text'])
        self.assertEqual(reply, 'It is playing.')


if __name__ == '__main__':
    unittest.main()
