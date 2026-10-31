"""General goal/precondition regressions, with scratch config and fake Mac/model workers."""
import io
import json
import os
import re
import subprocess
import unittest
from unittest.mock import Mock, patch

import atticus
from tests import scratch_dir

RAN_PROGRAMS = atticus.ran_programs


class NightTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        for p in [*[patch.object(atticus, k, str(self.root / name)) for k, name in
                    [('SKILLS', 'skills.json'), ('LAST', 'last'), ('RECENT', 'recent.jsonl'),
                     ('ME_FILE', 'me.json'), ('WORKED', 'worked.json'), ('MEMORY', 'memory.md')]],
                  patch.dict(os.environ, {'ATTICUS_DIR': str(self.root), 'ATTICUS_SCREEN': 'Request display'}, clear=True)]:
            p.start(); self.addCleanup(p.stop)
        p = patch.object(atticus, 'ran_programs', return_value={'fixturetool', 'fixtureone', 'fixturetwo', 'orca'}); p.start(); self.addCleanup(p.stop)

    def test_help_only_for_clis_ran_before(self):
        rows = [{'task': 'a', 'ran': ['cd /tmp && /opt/bin/fixtureone send x  => ok (0.1s)', 'osascript -e \'tell app "x" to fixturetwo\'']}]
        (self.root / 'log.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        with patch.object(atticus, 'ran_programs', RAN_PROGRAMS):   # the real log reader, not the setUp stub
            self.assertEqual(atticus.ran_programs() & {'fixtureone', 'fixturetwo'}, {'fixtureone'})   # a quoted word was never run
            with patch.object(atticus.shutil, 'which', side_effect=lambda w: '/' + w if w in ('fixtureone', 'fixturetwo') else None), \
                 patch.object(atticus.os.path, 'getmtime', return_value=1), \
                 patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'usage: tool')) as run:
                got = atticus.tool_help('fixtureone and fixturetwo')
        run.assert_called_once_with(['/fixtureone', '--help'], capture_output=True, text=True, timeout=2, stdin=subprocess.DEVNULL)
        self.assertIn('`fixtureone --help`', got)
        self.assertIn('not used before (run `<name> --help` if one is meant): fixturetwo', got)

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

    def test_prompt_send_receipts_are_confirmation_not_a_reason_to_retry(self):
        root = 'Terminals:\n  terminal read    Read output\n  terminal send    Send input\n'
        branch = 'Commands:\n  read    Read output\n  send    Send input\n'
        send = 'Options:\n  --enter    Append Enter\n  --json    Machine-readable receipt\n  --wait-submit    Observe without resending\n'
        def help_(args, **kw):
            path = args[1:-1]
            return subprocess.CompletedProcess(args, 0, root if not path else branch if path == ['terminal'] else send, '')
        with patch.object(atticus.shutil, 'which', side_effect=lambda word: '/orca' if word == 'orca' else None), \
             patch.object(atticus.os.path, 'getmtime', return_value=1), \
             patch.object(atticus.subprocess, 'run', side_effect=help_):
            got = atticus.tool_help('send that prompt to the agent in the orca terminal')
        self.assertIn('orca terminal send --help', got)
        self.assertIn('--wait-submit', got)
        self.assertIn('accepted/queued + Enter means sent', atticus.SYSTEM)
        self.assertIn('Confirm in one short line', atticus.SYSTEM)

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
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), patch.object(atticus, 'cached_hands', return_value=None), \
             patch.dict(os.environ, {'ATTICUS_UI': '1'}), patch('sys.stdout', new_callable=io.StringIO) as out:
            with patch.dict(os.environ, {'ATTICUS_LIVE': '1'}):
                self.assertIsNone(atticus.fast('When I say quiet time, open fixture on the left'))
                place.assert_not_called()
                self.assertEqual(atticus.skills(), {})
            self.assertEqual(atticus.fast('When I say quiet time, open fixture on the left'), 'Fixture: left.')
            saved = atticus.skills()['quiet time']
            self.assertTrue(saved['mine'])
            self.assertIn('--place Fixture left current', ' '.join(saved['cmds']))
            self.assertIn('Learned: Say “quiet time”', out.getvalue())

    def test_remaining_words_keep_fast_path_and_complete_context_for_fallback(self):
        request = {'front': 'Fixture', 'task': 'Fixture left, Other right', 'remaining': ', Other right', 'done': ['Fixture: left.']}
        brain = Mock(return_value=('Handled remainder.', 0, [])); brain.ok = True; brain.cmds = brain.ran = []; brain.observed = []
        with patch.multiple(atticus, start_ai=lambda: None, licensed=lambda: True, ping=lambda: None,
                            front=lambda: ('Fixture', ''), osa=lambda *a: '', screens=lambda: [], describe=lambda *a: '',
                            selection_context=lambda: '', me_line=lambda: '', relevant_rules=lambda _: '', workflows=lambda *a: '',
                            recent=lambda: [], screen_for=lambda *a: None, wait_commit=lambda: True, run=brain,
                            remember_turn=lambda *a: None, log_turn=lambda *a, **k: None, restore_focus=lambda *a: None,
                            tip=lambda *a: None, remember_workflow=lambda t, r, *a: (r, False)), \
             patch.object(atticus.threading, 'Thread'), patch('sys.argv', ['atticus.py', '--wait']), \
             patch('sys.stdout', new_callable=io.StringIO) as out, patch.object(atticus, 'fast', return_value='Other: right.') as fast:
            with patch('sys.stdin', io.StringIO(json.dumps(request) + '\n')): atticus.main()
            fast.assert_called_once_with(', Other right')
            brain.assert_not_called()
            self.assertIn('Fixture: left. Other: right.', out.getvalue())
            fast.return_value = None
            with patch('sys.stdin', io.StringIO(json.dumps(request) + '\n')), patch.object(atticus, 'learn') as learn: atticus.main()
            learn.assert_not_called()   # its commands did only the rest: never a shortcut, and never under the "Already completed" words
            prompt = brain.call_args.args[0]
            self.assertIn('Fixture left, Other right', prompt)
            self.assertIn('Already completed: Fixture: left.', prompt)
            self.assertIn('Request screen (default for unnamed moves and drawings): Request display', prompt)
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
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as open_:
            self.assertEqual(atticus.fast(', and open fixture'), 'Opened Fixture.')
            open_.assert_called_once_with(['open', '-a', 'Fixture'])
        self.assertEqual(atticus.plain('; then search example.test for reports'), 'search example.test for reports')

    def test_spoken_fillers_anywhere_only_change_whole_words(self):
        for said, expected in [
            ('open, uh, my terminal', 'open my terminal'),
            ('um, hey atticus, open spotify', 'open spotify'),
            ('open,uh,my terminal', 'open my terminal'),
            ('umbrella', 'umbrella'), ('drum', 'drum'),
            ('summer thermal humming permanent', 'summer thermal humming permanent'),
            ('open  example.test please', 'open example.test'),
        ]:
            with self.subTest(said=said): self.assertEqual(atticus.plain(said), expected)
        for filler in ('uh', 'um', 'erm', 'hmm', 'uhh', 'ummm', 'errrmmm', 'hmmmm', 'UHH'):
            with self.subTest(filler=filler):
                self.assertEqual(atticus.plain(f'{filler}, open, {filler}, terminal, {filler}'), 'open terminal')
                self.assertEqual(atticus.plain(filler), '')

    def test_spoken_fillers_in_matching_keys_and_split_parts(self):
        text = 'open zen and then, um, terminal'
        parts = [atticus.plain(p) for p in re.split(r'\s*(?:[,;]|\band then\b|\band\b|\bthen\b)\s*', text) if atticus.plain(p)]
        self.assertEqual(parts, ['open zen', 'terminal'])
        with patch.object(atticus, 'skills', return_value={'quiet time': {}}), \
             patch.object(atticus, 'fast_hands', return_value=None), \
             patch.object(atticus, 'replay', return_value='Done.') as replay:
            replay.commands = []; replay.ran = ['Done.']
            self.assertEqual(atticus.fast('quiet, ummm, time'), 'Done.')
            replay.assert_called_once_with('quiet time', None)

    def test_spoken_fillers_preserve_type_and_dictation_payloads(self):
        text = 'Um, open, uh, my umbrella and drum, hmm.'
        with patch('sys.argv', [atticus.ME, '--type', text]), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'Typed.')) as run, \
             patch('sys.stdout', new_callable=io.StringIO):
            atticus.main()
        run.assert_called_once_with([atticus.APP, '--type'], input=text, capture_output=True, text=True)
        self.assertEqual(atticus.dictate_request(text, corrections=''), '<dictation>\n' + json.dumps(text) + '\n</dictation>')

    def test_saved_moves_run_in_process_without_shell_or_duplicate_preview(self):
        atticus.save_skills({'quiet time': {'cmds': [atticus.PLACE + ' Fixture left current'], 'reply': 'Moved.', 'mine': True}})
        with patch.object(atticus, 'place', return_value='Fixture window -> left of Request display') as place, \
             patch.object(atticus.subprocess, 'run') as shell, patch.object(atticus, 'preview_commands') as preview:
            self.assertEqual(atticus.replay('quiet time'), 'Moved.')
            place.assert_called_once_with('Fixture', 'left', 'Request display')
            shell.assert_not_called(); preview.assert_not_called()

    def test_shortcuts_canonicalize_helpers_before_learning_and_replay(self):
        for helper in ('./atticus.py', 'python3 ./atticus.py', f'python3 {atticus.ME}'):
            with self.subTest(helper=helper):
                command=helper+' --place Fixture fullscreen monitor'
                self.assertIsNotNone(atticus.learn('quiet time',[command],'Placed.'))
                # Old explicit shortcuts also need repair when loaded, independent of cwd.
                atticus.save_skills({'quiet time':{'cmds':[command],'reply':'Placed.','mine':True}})
                with patch.object(atticus,'place_many',return_value='Fixture window -> fullscreen of Monitor') as place,patch.object(atticus.subprocess,'run') as shell:
                    self.assertEqual(atticus.fast('Quiet time.'),'Placed.')
                    place.assert_called_once_with(['Fixture','fullscreen','monitor']);shell.assert_not_called()
        self.assertIsNone(atticus.learn('other setup',['python3 /tmp/atticus.py --place Fixture full laptop'],'Placed.'))

    def test_named_shortcuts_allow_spoken_prefixes_but_not_other_instructions(self):
        for request in ('Okay, when I say quiet time, open fixture on the left', 'Um, can you, when I say quiet time, open fixture on the left'):
            with patch.object(atticus,'app_named',side_effect=lambda s:'Fixture' if s=='fixture' else None),patch.object(atticus,'proc_of',side_effect=lambda s:s), \
                 patch.object(atticus,'place',return_value='Fixture window -> left of Laptop'),patch.object(atticus.subprocess,'run',return_value=subprocess.CompletedProcess([],0)),patch.object(atticus,'cached_hands',return_value=None):
                self.assertEqual(atticus.fast(request),'Fixture: left.')
                self.assertIn('quiet time',atticus.skills())
        self.assertIsNone(atticus.named_shortcut('Do not save when I say quiet time, open fixture'))

    def test_helper_aliases_and_resource_directory_do_not_leak_into_replay(self):
        command=f'{atticus.PLACE} Fixture fullscreen monitor'
        for wrapped in (f'TASK_HELPER={atticus.ME}; "$TASK_HELPER" --place Fixture fullscreen monitor',
                        f'P={atticus.ME}; python3 "${{P}}" --place Fixture fullscreen monitor',
                        f'cd {os.path.dirname(atticus.ME)} && ./atticus.py --place Fixture fullscreen monitor'):
            with self.subTest(wrapped=wrapped): self.assertEqual(atticus.shortcut_commands('quiet time',[wrapped]),[command])
        self.assertIsNone(atticus.shortcut_commands('quiet time',[f'P=/tmp/atticus.py; "$P" --place Fixture full monitor']))
        self.assertIsNone(atticus.shortcut_commands('quiet time',[f'cd {os.path.dirname(atticus.ME)} && {atticus.SHOW} relative.txt']))

    def test_fullscreen_and_maximize_teach_their_distinct_native_actions(self):
        with patch.object(atticus,'app_named',side_effect=lambda s:'Fixture' if s=='fixture' else None),patch.object(atticus,'proc_of',side_effect=lambda s:s), \
             patch.object(atticus,'place',return_value='Fixture window -> full of Monitor') as place,patch.object(atticus,'cached_hands',return_value=None):
            self.assertEqual(atticus.fast('Okay, when I say quiet time, full screen fixture on my monitor'),'Fixture: full screen on monitor.')
            place.assert_called_with('Fixture','fullscreen','monitor')
            self.assertEqual(atticus.skills()['quiet time']['cmds'],[atticus.PLACE+' Fixture fullscreen monitor'])
            self.assertEqual(atticus.fast('maximize fixture'),'Fixture: full.')
            place.assert_called_with('Fixture','full','current')

    def test_native_fullscreen_targets_standard_window_and_checks_success(self):
        for entered in ('true','false'):
            with self.subTest(entered=entered):
                calls=[]
                def osa(script,*args):
                    calls.append(script)
                    if 'return {value of attribute' in script: return 'false, false, 0, 25, 1000, 775'
                    if 'return {position, size}' in script: return '0, 25, 1000, 775'
                    if 'get value of attribute "AXFullScreen"' in script: return entered
                    return ''
                with patch.object(atticus,'placement_window',return_value=('Fixture',None)),patch.object(atticus,'osa',side_effect=osa),patch.object(atticus,'free_focus'),patch.object(atticus,'preview_app'), \
                     patch.object(atticus,'screens',return_value=[('Request display',0,0,1000,800,True)]),patch.object(atticus.time,'sleep'),patch.object(atticus.subprocess,'run') as shell:
                    reply=atticus.place('Fixture','fullscreen','laptop')
                self.assertEqual(reply.startswith('NOT DONE'),entered=='false')
                self.assertTrue(any('set value of attribute "AXFullScreen"' in s for s in calls))
                self.assertTrue(all('window 1' not in s for s in calls));shell.assert_not_called()

    def test_native_fullscreen_rejects_a_successful_entry_on_the_wrong_display(self):
        checks = iter(('0, 25, 1000, 775', '1200, 25, 1000, 775', '1200, 25, 1000, 775'))   # moved, then full screen settles elsewhere
        def osa(script, *args):
            if 'return {value of attribute' in script: return 'false, false, 0, 25, 1000, 775'
            if 'return {position, size}' in script: return next(checks)
            if 'get value of attribute "AXFullScreen"' in script: return 'true'
            return ''
        displays = [('Built in', 0, 0, 1000, 800, True), ('External', 1000, 0, 1000, 800, False)]
        with patch.object(atticus,'placement_window',return_value=('Fixture',None)),patch.object(atticus,'osa',side_effect=osa),patch.object(atticus,'free_focus'),patch.object(atticus,'preview_app'), \
             patch.object(atticus,'screens',return_value=displays),patch.object(atticus.time,'sleep'),patch.object(atticus.subprocess,'run'):
            self.assertEqual(atticus.place('Fixture','fullscreen','laptop'), 'NOT DONE: Fixture entered full screen on the wrong display.')

    def test_native_fullscreen_asks_again_when_macos_drops_the_request(self):
        asked = []
        def osa(script, *args):
            if 'set value of attribute "AXFullScreen"' in script: asked.append(script)
            if 'return {value of attribute' in script: return 'false, false, 0, 25, 1000, 775'
            if 'return {position, size}' in script: return '0, 0, 1000, 800'
            if 'get value of attribute "AXFullScreen"' in script: return 'true' if len(asked) > 1 else 'false'   # the first one came mid-animation
            return ''
        with patch.object(atticus,'placement_window',return_value=('Fixture',None)),patch.object(atticus,'osa',side_effect=osa),patch.object(atticus,'free_focus'),patch.object(atticus,'preview_app'), \
             patch.object(atticus,'screens',return_value=[('Laptop',0,0,1000,800,True)]),patch.object(atticus.time,'sleep'),patch.object(atticus.subprocess,'run'):
            self.assertEqual(atticus.place('Fixture','fullscreen','laptop'), 'Fixture window -> fullscreen of Laptop')
        self.assertEqual(len(asked), 2)

    def test_place_cli_status_fails_everything_but_a_checked_receipt(self):
        for output in ('NOT DONE: wrong display.', 'no window found for "Fixture"', 'where must be left, right, full, fullscreen or center',
                       'Moved Fixture, but could not check where its window is. Look at the screen before saying it worked.'):
            with self.subTest(output=output), patch('sys.argv',['atticus.py','--place','Fixture']), \
                 patch.object(atticus,'place_many',return_value=output),patch('builtins.print'):
                with self.assertRaises(SystemExit) as stopped:
                    atticus.main()
                self.assertEqual(stopped.exception.code,1)
        for output in ('Fixture window -> full of Laptop',):
            with self.subTest(output=output), patch('sys.argv',['atticus.py','--place','Fixture']), \
                 patch.object(atticus,'place_many',return_value=output),patch('builtins.print'):
                self.assertIsNone(atticus.main())
        with patch('sys.argv',['atticus.py','--place']), patch('builtins.print'):
            with self.assertRaises(SystemExit) as stopped:
                atticus.main()
        self.assertEqual(stopped.exception.code,1)

    def test_fullscreen_position_check_retries_during_the_animation(self):
        reads = iter(('0, 25, 1000, 775', '', '', '0, 25, 1000, 775', '0, 25, 1000, 775'))
        def osa(script, *args):
            if 'return {value of attribute' in script: return 'false, false, 0, 25, 1000, 775'
            if 'return {position, size}' in script: return next(reads)
            if 'get value of attribute "AXFullScreen"' in script: return 'true'
            return ''
        with patch.object(atticus,'placement_window',return_value=('Fixture',None)),patch.object(atticus,'osa',side_effect=osa),patch.object(atticus,'free_focus'),patch.object(atticus,'preview_app'), \
             patch.object(atticus,'screens',return_value=[('Laptop',0,0,1000,800,True)]), \
             patch.object(atticus.time,'sleep') as sleep,patch.object(atticus.subprocess,'run'):
            self.assertEqual(atticus.place('Fixture','fullscreen','laptop'), 'Fixture window -> fullscreen of Laptop')
        self.assertEqual(sleep.call_count, 3)   # two unreadable frames, then one wait to see it hold still

    def test_place_batches_state_and_verification_without_fixed_delays(self):
        calls = []
        def osa(script, *args):
            calls.append(script)
            return 'false, false, 0, 0, 800, 600' if 'AXFullScreen' in script else '0, 25, 500, 775'
        with patch.object(atticus, 'placement_window', return_value=('Fixture', None)), patch.object(atticus, 'osa', side_effect=osa), patch.object(atticus, 'free_focus'), \
             patch.object(atticus, 'screens', return_value=[('Request display', 0, 0, 1000, 800, True)]), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(atticus, 'preview_app') as preview, patch.object(atticus.time, 'sleep') as sleep:
            self.assertIn('window -> left', atticus.place('Fixture', 'left'))
            sleep.assert_not_called()
            self.assertEqual(len(calls), 2)
            preview.assert_called_once()


if __name__ == '__main__': unittest.main()
