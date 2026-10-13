"""General goal/precondition regressions, with scratch config and fake Mac/model workers."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import atticus


class NightTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory(); self.addCleanup(root.cleanup)
        self.root = Path(root.name)
        for p in [patch.object(atticus, 'DIR', root.name),
                  *[patch.object(atticus, k, str(self.root / name)) for k, name in
                    [('SKILLS', 'skills.json'), ('LAST', 'last'), ('RECENT', 'recent.jsonl'),
                     ('ME_FILE', 'me.json'), ('WORKED', 'worked.json'), ('MEMORY', 'memory.md')]],
                  patch.object(atticus, 'pref', side_effect=lambda k, d: d),
                  patch.dict(os.environ, {'ATTICUS_DIR': root.name, 'ATTICUS_SCREEN': 'Request display'}, clear=True)]:
            p.start(); self.addCleanup(p.stop)

    def test_help_discovers_advertised_goal_subtree_and_readback_cached(self):
        root = ('Usage: fixturetool <command>\n' + 'padding\n' * 600 +
                '\nActions:\n  launch    Send hello using fixturetool\n  channel send    Deliver input\n  channel read    Read output\n')
        branch = 'Commands:\n  send    Send text\n  read    Read output\n'
        def help_(args, **kw):
            self.assertEqual(args[-1], '--help')
            path = args[1:-1]
            return subprocess.CompletedProcess(args, 0, root if not path else branch if path == ['channel'] else 'usage: ' + ' '.join(path) + ' --target <id> --text <value> --screen', '')
        with patch.object(atticus.shutil, 'which', side_effect=lambda w: '/fixturetool' if w == 'fixturetool' else '/usr/bin/env'), \
             patch.object(atticus.os.path, 'getmtime', return_value=1), patch.object(atticus.subprocess, 'run', side_effect=help_) as run:
            got = atticus.tool_help('send hello using fixturetool')
            self.assertIn('fixturetool channel send --help', got)
            self.assertIn('fixturetool channel read --help', got)
            self.assertNotIn('fixturetool launch --help', got)
            self.assertIn('--screen', got)
            before = run.call_count
            self.assertEqual(atticus.tool_help('send hello using fixturetool'), got)
            self.assertEqual(run.call_count, before)
            self.assertNotIn('env --help', atticus.tool_help('env'))

    def test_help_description_only_match_does_not_expand(self):
        root = 'Commands:\n  backup    Save chat history at a given time\n  status    Current state\n'
        with patch.object(atticus.shutil, 'which', side_effect=lambda w: '/fixturetool' if w == 'fixturetool' else None), \
             patch.object(atticus.os.path, 'getmtime', return_value=1), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, root)) as run:
            got = atticus.tool_help('ask fixturetool what time it is')
            self.assertIn('fixturetool --help', got)
            self.assertNotIn('fixturetool backup --help', got)
            run.assert_called_once_with(['/fixturetool', '--help'], capture_output=True, text=True, timeout=2, stdin=subprocess.DEVNULL)

    def test_help_caps_root_text_and_total_across_tools(self):
        root = 'Commands:\n  channel send    Deliver input\n' + 'root padding\n' * 500
        def help_(args, **kw):
            path = args[1:-1]
            text = root if not path else 'Commands:\n  send    Deliver input\n  read    Read output\n' if path == ['channel'] else 'subcommand padding\n' * 500
            return subprocess.CompletedProcess(args, 0, text)
        with patch.object(atticus.shutil, 'which', side_effect=lambda w: '/' + w if w in ('fixtureone', 'fixturetwo') else None), \
             patch.object(atticus.os.path, 'getmtime', return_value=1), patch.object(atticus.subprocess, 'run', side_effect=help_):
            roots = atticus.tool_help('fixtureone and fixturetwo')
            self.assertIn('fixtureone --help', roots)
            self.assertIn('fixturetwo --help', roots)
            self.assertEqual(roots.count('root padding'), 2 * root[:3000].count('root padding'))
            self.assertLessEqual(len(roots), 8000)
            expanded = atticus.tool_help('send using fixtureone and fixturetwo')
            self.assertEqual(len(expanded), 8000)

    def test_relationships_use_actual_contact_labels_and_never_guess(self):
        cards = [{'name': 'Pat Example', 'emails': ['pat@example.test']}, {'name': 'Robin Example', 'emails': ['robin@example.test']}]
        own = {'related': [{'label': 'guardian', 'value': 'Pat Example'}]}
        self.assertEqual(atticus.contact_matches('my guardian', cards, own), cards[:1])
        self.assertEqual(atticus.contact_matches('Robin Example', cards, own), cards[1:])
        self.assertEqual(atticus.contact_matches('my guardian', cards, {}), [])
        self.assertEqual(atticus.contact_matches('my supervisor', cards, own), [])
        cards[0]['nickname'] = 'P. Example'
        self.assertEqual(atticus.contact_matches('guardian', cards, {'related': [{'label': 'guardian', 'value': 'P. Example'}]}), cards[:1])
        self.assertEqual(len(atticus.contact_matches('Example', cards, own)), 2)
        self.assertIn('leaves it addressed, ready and unsent', atticus.SYSTEM)
        self.assertIn('--contacts', atticus.SYSTEM)
        with patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'permission denied')):
            self.assertIn('Contacts unavailable', atticus.contacts('guardian'))
        snapshot = {'own': own, 'cards': [{**c, 'index': i} for i, c in enumerate(cards)]}
        with patch.object(atticus.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 0, json.dumps(snapshot)),
                                                               subprocess.CompletedProcess([], 0, json.dumps(cards[:1]))]) as read:
            result = json.loads(atticus.contacts('guardian'))
            self.assertEqual(result['matches'], cards[:1])
            self.assertEqual(json.loads(read.call_args.args[0][-1]), [0])
        with patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(snapshot))):
            result = json.loads(atticus.contacts('unknown relationship'))
            self.assertEqual(result['matches'], [])
            self.assertEqual(result['ownCard'], own)   # the AI sees relationship facts even without an exact word match

    def test_teaching_simple_action_waits_for_confirmation_saves_and_shows_pill(self):
        with patch.object(atticus, 'app_named', side_effect=lambda s: 'Fixture' if s == 'fixture' else None), \
             patch.object(atticus, 'proc_of', side_effect=lambda s: s), patch.object(atticus, 'place', return_value='Fixture window -> left of Request display') as place, \
             patch.object(atticus.subprocess, 'run'), patch.object(atticus, 'cached_hands', return_value=None), \
             patch.dict(os.environ, {'ATTICUS_UI': '1'}), patch('sys.stdout', new_callable=io.StringIO) as out:
            with patch.dict(os.environ, {'ATTICUS_LIVE': '1'}):
                self.assertIsNone(atticus.fast('When I say quiet time, open fixture on the left'))
                place.assert_not_called()
                self.assertEqual(atticus.skills(), {})
            self.assertEqual(atticus.fast('When I say quiet time, open fixture on the left'), 'Fixture: left.')
            saved = atticus.skills()['quiet time']
            self.assertTrue(saved['mine'])
            self.assertIn('--place Fixture left current', ' '.join(saved['cmds']))
            self.assertIn('Learned: say “quiet time”', out.getvalue())

    def test_remaining_words_keep_fast_path_and_complete_context_for_fallback(self):
        request = {'front': 'Fixture', 'task': 'Fixture left, Other right', 'remaining': ', Other right', 'done': ['Fixture: left.']}
        brain = Mock(return_value=('Handled remainder.', 0, [])); brain.ok = True; brain.cmds = brain.ran = []
        with patch.multiple(atticus, start_ai=lambda: None, licensed=lambda: True, ping=lambda: None,
                            front=lambda: ('Fixture', ''), osa=lambda *a: '', screens=lambda: [], describe=lambda *a: '',
                            selection_context=lambda: '', me_line=lambda: '', relevant_rules=lambda _: '', workflows=lambda *a: '',
                            recent=lambda: [], screen_for=lambda *a: None, wait_commit=lambda: True, run=brain,
                            remember_turn=lambda *a: None, log_turn=lambda *a: None, restore_focus=lambda *a: None,
                            tip=lambda *a: None, remember_workflow=lambda t, r, *a: (r, False)), \
             patch.object(atticus.threading, 'Thread'), patch('sys.argv', ['atticus.py', '--wait']), \
             patch('sys.stdout', new_callable=io.StringIO) as out, patch.object(atticus, 'fast', return_value='Other: right.') as fast:
            with patch('sys.stdin', io.StringIO(json.dumps(request) + '\n')): atticus.main()
            fast.assert_called_once_with(', Other right')
            brain.assert_not_called()
            self.assertIn('Fixture: left. Other: right.', out.getvalue())
            fast.return_value = None
            with patch('sys.stdin', io.StringIO(json.dumps(request) + '\n')): atticus.main()
            prompt = brain.call_args.args[0]
            self.assertIn('Fixture left, Other right', prompt)
            self.assertIn('Already completed: Fixture: left.', prompt)
            self.assertIn('Request screen (default for unnamed moves): Request display', prompt)
            request['task'] += '\t"quoted"\nsecond line'
            with patch('sys.stdin', io.StringIO(json.dumps(request) + '\n')): atticus.main()
            self.assertIn(request['task'], brain.call_args.args[0])

    def test_parallel_moves_share_request_display_and_explicit_screen_wins(self):
        with patch.object(atticus, 'app_named', side_effect=lambda t: {'fixture': 'Fixture', 'other': 'Other'}.get(t)), \
             patch.object(atticus, 'proc_of', side_effect=lambda s: s), patch.object(atticus, 'place', return_value='Moved') as place:
            self.assertIsNotNone(atticus.fast('Fixture on the left, Other on the right'))
            self.assertEqual({c.args[2] for c in place.call_args_list}, {'Request display'})
            place.reset_mock()
            self.assertIsNotNone(atticus.fast('Fixture left laptop, Other right monitor'))
            self.assertEqual({c.args[2] for c in place.call_args_list}, {'laptop', 'monitor'})
            place.reset_mock()
            self.assertIsNotNone(atticus.fast(', Other on the right'))
            place.assert_called_once_with('Other', 'right', 'current')

    def test_continuation_punctuation_does_not_block_other_simple_actions(self):
        with patch.object(atticus, 'app_named', side_effect=lambda t: 'Fixture' if t == 'fixture' else None), \
             patch.object(atticus.subprocess, 'run') as open_:
            self.assertEqual(atticus.fast(', and open fixture'), 'Opened Fixture.')
            open_.assert_called_once_with(['open', '-a', 'Fixture'])
        self.assertEqual(atticus.plain('; then search example.test for reports'), 'search example.test for reports')

    def test_saved_moves_run_in_process_without_shell_or_duplicate_preview(self):
        atticus.save_skills({'quiet time': {'cmds': [atticus.PLACE + ' Fixture left current'], 'reply': 'Moved.', 'mine': True}})
        with patch.object(atticus, 'place', return_value='Fixture window -> left of Request display') as place, \
             patch.object(atticus.subprocess, 'run') as shell, patch.object(atticus, 'preview_commands') as preview:
            self.assertEqual(atticus.replay('quiet time'), 'Moved.')
            place.assert_called_once_with('Fixture', 'left', 'Request display')
            shell.assert_not_called(); preview.assert_not_called()

    def test_place_batches_state_and_verification_without_fixed_delays(self):
        calls = []
        def osa(script, *args):
            calls.append(script)
            return 'false, false, 0, 0, 800, 600' if 'AXFullScreen' in script else '0, 25, 500, 775'
        with patch.object(atticus, 'osa', side_effect=osa), patch.object(atticus, 'free_focus'), \
             patch.object(atticus, 'screens', return_value=[('Request display', 0, 0, 1000, 800, True)]), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(atticus, 'preview_app') as preview, patch.object(atticus.time, 'sleep') as sleep:
            self.assertIn('window -> left', atticus.place('Fixture', 'left'))
            sleep.assert_not_called()
            self.assertEqual(len(calls), 2)
            preview.assert_called_once()


if __name__ == '__main__': unittest.main()
