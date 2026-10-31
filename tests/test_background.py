"""Background tasks use fake workers; no user apps, windows, or configuration."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import atticus
from tests import scratch_dir


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        root = scratch_dir(self)
        for p in [patch.dict(os.environ, {'ATTICUS_ASK': str(root)}, clear=True),
                  patch.object(atticus, 'WORKED', str(root / 'worked.json')),
                  patch.object(atticus, 'wait_commit', return_value=True)]:
            p.start(); self.addCleanup(p.stop)
        self.target = {'pid': 123, 'windowID': '42', 'windowFrame': [0, 0, 300, 200], 'app': 'Notes', 'window': 'Fixture'}

    def gate(self, cmd):
        with patch('sys.stdin', io.StringIO(json.dumps({'tool_input': {'command': cmd}}))), patch('sys.stdout', new_callable=io.StringIO) as out, patch.object(atticus, 'preview_app'):
            atticus.gate()
        return json.loads(out.getvalue())['hookSpecificOutput']['permissionDecision'] if out.getvalue() else 'allow'

    def test_instant_open_tells_the_focus_guard_it_was_asked(self):
        calls = []
        run = lambda cmd, **_: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, '', '')
        with patch.object(atticus, 'LAST', os.path.join(os.environ['ATTICUS_ASK'], 'last')), \
             patch.object(atticus, 'app_named', return_value='Fixture'), patch.object(atticus, 'skills', return_value={}), \
             patch.object(atticus, 'pref', side_effect=lambda k, v=None: v), patch.object(atticus.subprocess, 'run', side_effect=run):
            for words in ('launch fixture', 'open fixture'):
                calls.clear()
                with self.subTest(words=words):
                    self.assertEqual(atticus.fast(words), 'Opened Fixture.')
                    self.assertEqual(calls[-1], ['open', '-a', 'Fixture'])
                    self.assertEqual(calls[:-1], [[atticus.APP, '--raise', 'user']] if words.startswith('launch') else [])   # "open" was freed by allow_focus already
            calls.clear()
            with patch.object(atticus, 'move_target', return_value=('Fixture', 'left', 'current')), \
                 patch.object(atticus, 'place', return_value='Fixture window -> left of Main'):
                self.assertEqual(atticus.fast('launch fixture on the left'), 'Fixture: left.')
            self.assertEqual(calls[:2], [[atticus.APP, '--raise', 'user'], ['open', '-a', 'Fixture']])   # the inner "open" must not hide that the user asked

    def test_settings_and_tool_hints_never_steer_to_focus(self):
        self.assertIn('System settings: shell, defaults or AppleScript first; else open the pane with --bg', atticus.system_prompt(atticus.ASK_FIRST))
        self.assertTrue(atticus.hands_valid(['click', 'Night Shift…', 'front']) and atticus.hands_valid(['click', 'Done', 'near', 'Sheet', 'double', 'front']))
        self.assertFalse(atticus.hands_valid(['click', 'Done', 'front', 'front']))
        swift = Path(atticus.ME).with_name('Atticus.swift').read_text()
        # --front grants focus for the rest of the ask; a tool reply suggesting it made System Settings stay in front for "is Night Shift on?"
        self.assertNotIn('--front', swift); self.assertNotIn('Bring the window forward', swift)
        self.assertIn('case "front": guard !front', swift)

    def test_recursive_ask_and_unrequested_activation_are_denied(self):
        self.assertEqual(self.gate(f'env -u ATTICUS_ASK -u CLAUDECODE python3 {atticus.ME} ask again'), 'deny')
        self.assertEqual(self.gate(f'python3 {atticus.ME} --wait'), 'deny')
        self.assertEqual(self.gate(f'env -u ATTICUS_ASK {atticus.ME} ask again'), 'deny')
        self.assertEqual(self.gate(f'cd {os.path.dirname(atticus.ME)} && env -u ATTICUS_ASK sh atticus.py ask again'), 'deny')   # the sh header makes sh a launcher
        self.assertEqual(self.gate(f'xargs {atticus.ME} ask again'), 'deny')
        self.assertEqual(self.gate(f'printf again | xargs {atticus.ME} ask'), 'deny')
        self.assertEqual(self.gate(f'echo ready && env {atticus.ME} ask again'), 'deny')
        self.assertEqual(self.gate(f'python3 {atticus.ME} --hands see Notes'), 'allow')
        self.assertEqual(self.gate(f'A={atticus.ME}; $A --front Fixture && $A --hands see Fixture'), 'allow')
        self.assertEqual(self.gate(f'A={atticus.ME}; $A ask again'), 'deny')
        self.assertEqual(self.gate('osascript -e \'tell application "Notes" to activate\''), 'deny')
        for separator in (';', '&&', '|', '\n', '\n\n'):
            with self.subTest(separator=separator):
                self.assertEqual(self.gate('true' + separator + 'open -a Fixture'), 'deny')
                self.assertEqual(self.gate('true' + separator + 'open -g -a Fixture'), 'allow')
        self.assertEqual(self.gate('open -a Notes'), 'deny')
        self.assertEqual(self.gate('env open -a Notes'), 'deny')
        self.assertEqual(self.gate('xargs open -a Notes'), 'deny')
        self.assertEqual(self.gate('printf Notes | xargs open -a'), 'deny')
        self.assertEqual(self.gate('xargs open -g -a Notes'), 'allow')
        self.assertEqual(self.gate('open -g -a Notes'), 'allow')
        self.assertEqual(self.gate('echo open'), 'allow')
        self.assertEqual(self.gate('printf open'), 'allow')
        self.assertEqual(self.gate(f'{atticus.HANDS} type Field activate'), 'allow')
        self.assertEqual(self.gate(f'{atticus.HANDS} type Field atticus.py'), 'allow')
        self.assertFalse(atticus.wants_focus('Do not show the window, just tell me whether it is open'))
        self.assertFalse(atticus.wants_focus('Do not open Notes; add a note'))
        self.assertFalse(atticus.wants_focus("Don't focus Notes"))
        self.assertFalse(atticus.wants_focus('Open Notes in the background'))
        atticus.save_request(os.environ['ATTICUS_ASK'], 'Show Notes')
        self.assertEqual(self.gate('osascript -e \'tell application "Notes" to activate\''), 'allow')
        self.assertEqual(self.gate('printf Notes | xargs open -a'), 'allow')

    def test_one_helper_targets_every_app_and_records_last_window(self):
        with patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(self.target))) as run:
            for app in ['Spotify', 'Notes', 'Reminders', 'Finder']:
                atticus.preview_commands(f'osascript -e \'tell application "{app}" to make new item\'')
                self.assertEqual(run.call_args.args[0], [atticus.APP, '--window-target', app, ''])
        self.assertEqual(json.loads(Path(atticus.WORKED).read_text())['window'], 'Fixture')
        self.assertEqual(len(list(Path(os.environ['ATTICUS_ASK']).glob('hands-*'))), 4)

    def test_background_open_handles_apps_files_and_schemes(self):
        with patch.object(atticus, 'front', return_value=('Editor', 'Work')), patch.object(atticus, 'osa', return_value='Editor'), patch.object(atticus, 'preview_app',return_value=None) as preview, patch.object(atticus.time, 'sleep'), patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'Notes.app')) as run:
            atticus.show('Notes', bg=True)
            self.assertEqual(run.call_args.args[0], ['open', '-g', '-a', 'Notes'])
            preview.assert_called_with('Notes', 'open')
            self.assertFalse(any('set frontmost' in str(c) for c in atticus.osa.call_args_list))   # Notes stayed behind: nothing to give back
            atticus.show('spotify:search:jazz', bg=True)
            self.assertEqual(run.call_args.args[0], ['open', '-g', 'spotify:search:jazz'])
            atticus.show(os.environ['ATTICUS_ASK'], bg=True)
            self.assertEqual(run.call_args.args[0], ['open', '-g', os.environ['ATTICUS_ASK']])

    def test_reopening_active_app_preserves_chosen_conversation_before_typing(self):
        for bg, open_on in ((False, 'here'), (True, 'here'), (False, 'other')):
            state = {'active': False, 'input': 'previous conversation'}
            def open_app(cmd, **kwargs):
                if cmd[0] == 'lsappinfo':
                    return subprocess.CompletedProcess(cmd, 0, '(in front)\n    pid = 123' if state['active'] else '')
                state.update(active=True, input='previous conversation')   # reopen restores the old input
                return subprocess.CompletedProcess(cmd, 0)
            def osa(script, **kwargs):
                return str(state['active']).lower() if 'get frontmost and' in script else 'Fixture'
            with self.subTest(bg=bg, open_on=open_on), patch.object(atticus, 'pref', side_effect=lambda k, d: open_on if k == 'openOn' else d), \
                 patch.object(atticus, 'front', return_value=('Editor', 'Work')), patch.object(atticus, 'osa', side_effect=osa), \
                 patch.object(atticus, 'free_focus'), patch.object(atticus, 'screens', return_value=[]), \
                 patch.object(atticus, 'preview_app'), patch.object(atticus, 'keep_behind'), \
                 patch.object(atticus.subprocess, 'run', side_effect=open_app) as run:
                atticus.show('Fixture', bg=bg)
                state['input'] = 'chosen conversation'   # choose sidebar item, Return, focus its input
                atticus.show('Fixture', bg=bg)
                sent = {state['input']: 'status request'}   # fake typing and destination-specific verification
                self.assertEqual(sent, {'chosen conversation': 'status request'})
                self.assertEqual(sum(c.args[0][0] == 'open' for c in run.call_args_list), 1)
                state['active'] = False   # inactive app or no window must still open
                atticus.show('Fixture', bg=bg)
                self.assertEqual(sum(c.args[0][0] == 'open' for c in run.call_args_list), 2)
        self.assertIn('focus its input before typing', atticus.SYSTEM)
        self.assertIn('Verify text there', atticus.SYSTEM)
        for rule in ("A click isn't success", 'Use returned state', 'Check destinations before retrying sends'):
            self.assertIn(rule, atticus.SYSTEM)

    def test_absent_and_background_apps_open_without_applescript_lookup(self):
        for info in ('', 'ASN:0x0-0x123:\n    pid = 123'):
            def run(cmd, **kwargs):
                return subprocess.CompletedProcess(cmd, 0, info if cmd[0] == 'lsappinfo' else '')
            with self.subTest(info=info), patch.object(atticus, 'pref', side_effect=lambda k, d: d), \
                 patch.object(atticus, 'front', return_value=('Editor', 'Work')), patch.object(atticus, 'free_focus'), \
                 patch.object(atticus, 'osa') as osa, patch.object(atticus.subprocess, 'run', side_effect=run) as call:
                self.assertEqual(atticus.show('Fixture'), 'opened Fixture in front')
                self.assertEqual([c.args[0] for c in call.call_args_list if c.args[0][0] == 'open'], [['open', '-a', 'Fixture']])
                osa.assert_not_called()

    def test_safari_web_emits_preview_without_raising(self):
        with patch.dict(os.environ, {'ATTICUS_FRONT': 'Safari'}), patch.object(atticus, 'browser_adapter',return_value='webkit'), patch.object(atticus, 'preview_app',return_value=None) as preview, patch.object(atticus,'hands_map',return_value=None), patch.object(atticus.subprocess, 'run', side_effect=lambda args,**kw:subprocess.CompletedProcess([], 0, '10\t2' if 'return (id of window' in args[2] else 'Fixture, 0, 0, 300, 200' if 'get {name, bounds}' in args[2] else 'page', '')) as run:
            self.assertEqual(atticus.web('read'), 'page')
            preview.assert_called_once_with('Safari', 'read', title='Fixture', frame=[0,0,300,200])
            self.assertNotIn('activate', run.call_args.args[0][2])

    def test_blocked_fetch_can_read_the_named_url_in_a_background_browser_with_preview(self):
        class Blocked(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(503);self.end_headers();self.wfile.write(b'Fetch blocked')
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Blocked);threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        url=f'http://127.0.0.1:{server.server_port}/requested-page'
        with self.assertRaises(urllib.error.HTTPError) as failure:atticus.get(url)
        self.assertEqual(failure.exception.code,503)
        def result(args,**kw):
            if 'make new tab' in args[2]:
                self.assertIn('set priorSelection to current tab of w',args[2])
                self.assertIn('set current tab of w to priorSelection',args[2])
            return subprocess.CompletedProcess([],0,'10\t2\t\n' if 'make new tab' in args[2] else 'Requested page, 0, 0, 300, 200' if 'get {name, bounds}' in args[2] else
                                               json.dumps({'signature':url+'|ready'}) if '"ready", ' in args[-1][-35:] else 'Actual requested page content', '')
        with patch.object(atticus,'browser_adapter',return_value='webkit'), patch.object(atticus,'page_ready',return_value=True), \
             patch.object(atticus,'preview_app',return_value=self.target),patch.object(atticus,'hands_map'),patch.object(atticus,'emit') as emit,patch.object(atticus.subprocess,'run',side_effect=result):
            self.assertIn('Actual requested page content',atticus.web('read',url,app='Fixture browser'))
            self.assertTrue(any(line.startswith('▣ ') for call in emit.call_args_list for line in call.args[0]))
        with patch.object(atticus,'show') as show:
            self.assertIn('without credentials',atticus.web('read','https://user:secret@fixture.example'))
            show.assert_not_called()
        with patch.object(atticus,'browser_adapter',return_value='webkit'),patch.object(atticus,'page_ready',return_value=False),patch.object(atticus.subprocess,'run',side_effect=result),patch.object(atticus,'preview_app'):
            self.assertIn('Requested page not ready',atticus.web('read',url,app='Fixture browser'))

    def test_restore_does_not_interrupt_a_new_unrelated_app(self):
        with patch.object(atticus, 'osa', return_value='Editor') as osa:
            atticus.restore_focus('Finder', 'make a note', ['tell application "Notes" to make new note'])
            self.assertEqual(osa.call_count, 1)

    def test_restore_ignores_a_window_an_earlier_task_worked_in(self):
        Path(atticus.WORKED).write_text(json.dumps({'app': 'Editor', 'window': 'Draft'}))
        started = os.path.getmtime(atticus.WORKED)
        for start, calls in ((started + 1, 1), (started, 2)):   # written before this ask began: the user switched there themselves
            with self.subTest(start=start), patch.dict(atticus.TURN, {'_started': start}), patch.object(atticus, 'osa', return_value='Editor') as osa:
                atticus.restore_focus('Finder', 'what time is it', [])
                self.assertEqual(osa.call_count, calls)

    def test_work_mode_covers_non_browser_apps(self):
        for mode in ('back', 'front'):
            with self.subTest(mode=mode), patch.object(atticus, 'pref', side_effect=lambda k, d: mode if k == 'workIn' else d), \
                 patch.object(atticus, 'osa', return_value='Editor') as osa, patch.object(atticus, 'preview_app', return_value={'app': 'Fixture'}), \
                 patch.object(atticus, 'keep_behind') as behind, patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                self.assertEqual(atticus.show('Fixture', bg=True), 'opened Fixture ' + ('in front' if mode == 'front' else 'in the background'))
                self.assertEqual(run.call_args.args[0], ['open'] + ([] if mode == 'front' else ['-g']) + ['-a', 'Fixture'])
                self.assertEqual(behind.call_count, int(mode == 'back'))
                osa.reset_mock()
                osa.return_value = 'Fixture'
                atticus.restore_focus('Editor', 'work in Fixture', ['tell application "Fixture" to work'])
                self.assertEqual(osa.call_count, 0 if mode == 'front' else 2)

    def test_preview_passes_explicit_focus_intent_to_native_apps(self):
        for requested in (False, True):
            with self.subTest(requested=requested), patch.object(atticus, 'wants_focus', return_value=requested), \
                 patch.object(atticus, 'emit'), patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(self.target))) as run:
                atticus.preview_app('Fixture')
                self.assertEqual(run.call_args.kwargs['env']['ATTICUS_FOCUS_REQUESTED'], '1' if requested else '0')

    def test_explicit_focus_is_not_undone_by_the_shared_fallback(self):
        with patch.dict(os.environ, {'ATTICUS_REQUEST': 'focus Fixture'}), patch.object(atticus, 'osa') as osa:
            atticus.keep_behind('Editor', 'Fixture')
            osa.assert_not_called()

    def test_agent_reads_reuse_one_own_window_and_close_it_at_task_end(self):
        scripts=[]; url=['']
        def result(args,**kw):
            if args[0]=='pgrep': return subprocess.CompletedProcess(args,0)
            self.assertEqual(args[0],'osascript'); script=args[2]; scripts.append(args)
            self.assertNotRegex(script,r'(?i)activate|AXRaise|frontmost|keystroke|key code')
            if 'make new tab' in script: return subprocess.CompletedProcess(args,0,'77\t'+str(len(scripts))+('\tnew' if args[-1]=='0' else '\t'),'')
            if 'get {name, bounds}' in script: out='Fixture, 0, 0, 300, 200'
            elif 'close window' in script: out=''
            else:
                self.assertIn('window id 77',script)
                out=json.dumps({'signature':url[0]+'|ready'}) if '"ready", ' in args[-1][-35:] else 'page text'
            return subprocess.CompletedProcess(args,0,out,'')
        with patch.dict(os.environ,{'ATTICUS_AGENT':'fixture'}),patch.object(atticus,'browser_adapter',return_value='chromium'),patch.object(atticus,'page_ready',return_value=True), \
             patch.object(atticus,'preview_app',return_value=None),patch.object(atticus,'hands_map'),patch.object(atticus,'osa',return_value='Editor'), \
             patch.object(atticus,'keep_behind') as behind,patch.object(atticus.subprocess,'run',side_effect=result):
            for i in range(2):
                url[0]='https://fixture.example/'+str(i)
                self.assertIn('page text',atticus.web('read',url[0],app='Fixture Browser'))
            first,second=[a for a in scripts if 'make new tab' in a[2]]
            self.assertEqual((first[-1],second[-1]),('0','77'))   # the second page reuses the task's window
            self.assertIn('make new window',first[2]);self.assertIn('set index of prior to 1',first[2])
            behind.assert_called_once_with('Editor','Fixture Browser',wait=.5)
            saved=Path(atticus.agent_gate_dir(os.environ['ATTICUS_ASK']),'browser-window.json')
            self.assertEqual(json.loads(saved.read_text()),{'app':'Fixture Browser','window':77});self.assertEqual(saved.stat().st_mode&0o777,0o600)
            atticus.close_agent_window(os.environ['ATTICUS_ASK'])
            self.assertIn('close window id 77',scripts[-1][2]);self.assertFalse(saved.exists())
            count=len(scripts);atticus.close_agent_window(os.environ['ATTICUS_ASK']);self.assertEqual(len(scripts),count)   # never a window it did not open

    def test_agent_site_placement_uses_main_open_path_only_when_requested(self):
        url = 'https://unseen.example/catalog'
        with patch.dict(os.environ, {'ATTICUS_AGENT': 'fixture'}), \
             patch.object(atticus, 'pref', side_effect=lambda k, d: 'front' if k == 'workIn' else d), \
             patch.object(atticus, 'show', return_value='opened ' + url + ' in front') as show, \
             patch.object(atticus, 'browser_adapter', return_value=''):
            atticus.web('read', url, app='Unseen Browser')
            show.assert_called_once_with(url, bg=True)
            self.assertTrue(atticus.wants_focus(sites=True))
            self.assertFalse(atticus.wants_focus('Show this browser'))
            atticus.save_request(os.environ['ATTICUS_ASK'], 'Research in the background')
            show.reset_mock()
            atticus.web('read', url, app='Unseen Browser')
            show.assert_not_called()

    def test_agent_show_in_front_does_not_reenter_url_reader(self):
        with patch.dict(os.environ, {'ATTICUS_AGENT': 'fixture'}), \
             patch.object(atticus, 'DIR', os.environ['ATTICUS_ASK']), \
             patch.object(atticus, 'pref', side_effect=lambda k, d: 'front' if k == 'workIn' else d), \
             patch.object(atticus, 'osa', return_value='Fixture Editor'), \
             patch.object(atticus, 'preview_app', return_value={'app': 'Unseen Browser'}), \
             patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run, \
             patch.object(atticus, 'web', return_value='Page ready.') as web:
            self.assertIn('in front', atticus.show('https://unseen.example', bg=True))
            self.assertIn(unittest.mock.call(['open', 'https://unseen.example']), run.call_args_list)
            web.assert_called_once_with('wait', text='https://unseen.example', app='Unseen Browser', fresh=True)

    def test_agent_background_show_and_window_reads_preserve_their_pin(self):
        Path(os.environ['ATTICUS_ASK'],'window-summary.json').write_text(json.dumps({'app':'Fixture Browser','web':True}))
        with patch.dict(os.environ,{'ATTICUS_AGENT':'fixture'}),patch.object(atticus,'web',return_value='Page\nControls:') as web:
            atticus.show('https://fixture.example')
            web.assert_called_with('read','https://fixture.example')
            atticus.window_text('Fixture Browser')
            web.assert_called_with('read',app='Fixture Browser',fresh=False)

    def test_agent_front_stays_background_and_show_respects_user_intent(self):
        with patch.dict(os.environ, {'ATTICUS_AGENT': 'fixture'}), patch.object(atticus, 'preview_app',return_value=None) as preview, patch.object(atticus, 'hands_map', return_value={'description': 'Notes map'}) as mapped, \
             patch.object(atticus, 'window_target', return_value=self.target), patch.object(atticus, 'look', return_value=[('/fake.jpg', 'Screen 1')]) as looked, \
             patch.object(atticus, 'osa') as osa, patch('sys.argv', ['atticus.py', '--front', 'Notes', '--asked']), patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.main()   # the model's --asked never brings an agent forward: only the user's words do
            osa.assert_not_called(); self.assertEqual(out.getvalue().strip(), 'Notes map\nScreen 1: /fake.jpg')
            preview.assert_called_once(); mapped.assert_called_once_with('Notes', target=self.target); looked.assert_called_once_with(cleanup=False, window=self.target)
        with patch.object(atticus, 'show') as show, patch('sys.stdout', new_callable=io.StringIO), patch('sys.argv', ['atticus.py', '--show', 'Notes']):
            atticus.main(); show.assert_called_with('Notes', True)
            atticus.save_request(os.environ['ATTICUS_ASK'], 'Open Notes')
            atticus.main(); show.assert_called_with('Notes', False)

    def test_agent_front_work_follows_only_the_users_words_and_uses_the_real_path(self):
        self.assertTrue(atticus.asks_front('fill the form in front of me') and atticus.asks_front('do it in the foreground'))
        self.assertFalse(atticus.asks_front('fill the form in the background'))
        agents = atticus.Agents(emit=lambda event: None)
        def started(words=None, brief='Open Keynote and show the deck', **extra):
            row = agents.new(); row.update(brief=brief, status='offered', **({'request': words} if words else {}), **extra); agents.rows[row['id']] = row
            agents.start(row['id'])
            return row, Path(atticus.agent_gate_dir(row['directory']), 'focus-requested')
        with patch.object(agents, 'warm'), patch.object(agents, 'send'), patch.object(agents, 'save'):
            self.assertFalse(started('Research flights to Lisbon')[1].exists())
            self.assertFalse(started()[1].exists())   # a model-written brief alone never brings an agent forward
            self.assertTrue(started('keep going', focus=True)[1].exists())   # a moved ask that already worked in front
            row, marker = started('Build the deck in Keynote and show it to me in front')
        self.assertTrue(marker.exists())
        with patch.dict(os.environ, {'ATTICUS_AGENT': row['id'], 'ATTICUS_ASK': row['directory']}):
            self.assertTrue(atticus.wants_focus())
            with patch.object(atticus, 'osa') as osa, patch.object(atticus, 'free_focus'), patch.object(atticus, 'look', return_value=[('/fake.jpg', 'Screen')]), \
                 patch.object(atticus.time, 'sleep'), patch('sys.stdout', new_callable=io.StringIO), patch('sys.argv', ['atticus.py', '--front', 'Keynote']):
                atticus.main()
                osa.assert_any_call('tell application "Keynote" to activate')
            marker.unlink(); Path(row['directory'], 'focus-requested').touch()   # the agent's own folder is writable by the agent: it does not count
            self.assertFalse(atticus.wants_focus())
        atticus.save_request(os.environ['ATTICUS_ASK'], 'open Keynote and build three slides')
        move = atticus.MainMove('Request: open Keynote and build three slides', type('Worker', (), {'ask': os.environ['ATTICUS_ASK']})())
        self.assertTrue(move.handoff()['focus'])

    def test_front_carries_model_intent_in_any_language(self):
        marker = Path(os.environ['ATTICUS_ASK'], 'focus-requested')
        with patch.object(atticus.shutil, 'which', return_value='/fake/claude'), \
             patch.object(atticus.subprocess, 'Popen') as popen, patch.object(atticus.signal, 'signal'), \
             patch.object(atticus.atexit, 'register'):
            worker = atticus.start_claude()
            self.assertEqual(worker.ask, os.environ['ATTICUS_ASK'])
            self.assertEqual(popen.call_args.kwargs['env']['ATTICUS_ASK'], worker.ask)
            worker.errors.close()
        for request in ('메모 앱 열어줘', '打开微信'):
            with self.subTest(request=request):
                marker.unlink(missing_ok=True)
                atticus.save_request(os.environ['ATTICUS_ASK'], request)
                self.assertFalse(atticus.wants_focus())
                with patch.object(atticus, 'osa') as osa, patch.object(atticus, 'free_focus') as free, patch.object(atticus, 'window_target', return_value=self.target), \
                     patch.object(atticus, 'look', return_value=[('/fake.jpg', 'Screen')]), \
                     patch.object(atticus.time, 'sleep'), patch('sys.stdout', new_callable=io.StringIO) as out, \
                     patch('sys.argv', ['atticus.py', '--front', 'Fixture']):
                    atticus.main()   # no focus words found (they are English-only): a picture in place, and how to say the user asked
                    osa.assert_not_called(); self.assertIn(f'{atticus.ME} --front Fixture --asked', out.getvalue())
                    with patch('sys.argv', ['atticus.py', '--front', 'Fixture', '--asked']): atticus.main()
                    osa.assert_called_once_with('tell application "Fixture" to activate')
                    free.assert_called_once_with(user=True)
                self.assertTrue(atticus.wants_focus(request))
                with patch.object(atticus, 'free_focus') as free, patch.object(atticus, 'osa') as osa:
                    atticus.allow_focus(request)
                    free.assert_called_once_with(user=True)
                    atticus.restore_focus('Editor', request, ['Fixture'])
                    osa.assert_not_called()
                with patch.object(atticus.subprocess, 'Popen') as popen:
                    popen.return_value.communicate.return_value = ('', '')
                    atticus.hands_call(['see'])
                    self.assertEqual(popen.call_args.kwargs['env']['ATTICUS_FOCUS_REQUESTED'], '1')
                marker.unlink(missing_ok=True)   # this fixture's agent gate folder is the ask folder itself
                with patch.dict(os.environ, {'ATTICUS_AGENT': 'fixture'}):
                    self.assertFalse(atticus.wants_focus())
                    self.assertTrue(atticus.wants_focus(sites=True))

    def test_front_works_on_a_window_in_any_state_without_raising_it(self):
        # Oct 21: a page on his second display, not key, was raised by --front although he kept working on the laptop. Any app, any state.
        marker = Path(os.environ['ATTICUS_ASK'], 'focus-requested')
        unfocused, covered, minimized = {**self.target, 'visible': True}, {**self.target, 'visible': False}, {**self.target, 'minimized': True}
        for request, target, extra, raised in (('play it', unfocused, [], False), ('play it', covered, [], False), ('keep going', minimized, [], True),
                                               ('play it', {}, [], True), ('show me it', unfocused, [], True), ('play it', unfocused, ['--asked'], True)):
            with self.subTest(request=request, target=target, extra=extra):
                atticus.save_request(os.environ['ATTICUS_ASK'], request); marker.unlink(missing_ok=True)
                with patch.object(atticus, 'window_target', return_value=target), patch.object(atticus, 'osa') as osa, \
                     patch.object(atticus, 'free_focus') as free, patch.object(atticus, 'look', return_value=[('/fake.jpg', 'Screen 2')]) as looked, \
                     patch.object(atticus.time, 'sleep'), patch('sys.stdout', new_callable=io.StringIO) as out, \
                     patch('sys.argv', ['atticus.py', '--front', 'Fixture App', 'Board', *extra]):
                    atticus.main()
                self.assertEqual(osa.called, raised); self.assertEqual(free.called, raised); self.assertEqual(marker.exists(), raised)
                self.assertIn('Screen 2: /fake.jpg', out.getvalue())
                if not raised:
                    looked.assert_called_once_with(cleanup=False, window=target)   # the window itself, painted where it sits
                    self.assertIn("--front 'Fixture App' Board --asked", out.getvalue())
        # Oct 30: tab words naming no window (an Orca tab) raised the app just to read it; the app's own window is pictured instead
        atticus.save_request(os.environ['ATTICUS_ASK'], 'what is it doing'); marker.unlink(missing_ok=True)
        with patch.object(atticus, 'window_target', side_effect=lambda app, title='': {} if title else covered), patch.object(atticus, 'osa') as osa, \
             patch.object(atticus, 'free_focus'), patch.object(atticus, 'look', return_value=[('/fake.jpg', 'Screen 2')]) as looked, \
             patch('sys.stdout', new_callable=io.StringIO), patch('sys.argv', ['atticus.py', '--front', 'Fixture App', 'Board']):
            atticus.main()
        osa.assert_not_called(); looked.assert_called_once_with(cleanup=False, window=covered)
        with patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(covered), '')) as run:
            self.assertEqual(atticus.window_target('Fixture App', 'Board'), covered)
            self.assertEqual(run.call_args.args[0], [atticus.APP, '--window-target', 'Fixture App', 'Board'])
            self.assertEqual(run.call_args.kwargs['env']['ATTICUS_FOCUS_REQUESTED'], '0')   # the lookup itself never activates
        for failure in (OSError(), subprocess.TimeoutExpired('x', 2)):
            with patch.object(atticus.subprocess, 'run', side_effect=failure): self.assertEqual(atticus.window_target('Fixture App'), {})
        with patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '[]', '')): self.assertEqual(atticus.window_target('Fixture App'), {})
        self.assertIn('pictures that window in place, even covered; raises only if asked.', atticus.system_prompt(atticus.ASK_FIRST))
        with patch.object(atticus, 'pref', side_effect=lambda k, d: 'front' if k == 'workIn' else d):
            self.assertNotIn('pictures that window in place', atticus.system_prompt(atticus.ASK_FIRST))

    def test_look_paints_the_target_window_on_its_own_display(self):
        calls = []
        def run(cmd, **_):
            calls.append(cmd)
            if cmd[:2] == [atticus.APP, '--look']: Path(cmd[3]).write_bytes(b'jpg')
            return subprocess.CompletedProcess(cmd, 0, 'window\n' if len(cmd) == 5 and painted[0] else '', '')
        painted = [True]
        displays = [('Built-in', 0, 0, 1512, 982, True), ('Monitor', 1512, 0, 2560, 1440, False)]
        window = {**self.target, 'app': 'Fixture App', 'window': 'Board', 'windowFrame': [1900, 200, 1100, 800], 'visible': False}
        with patch.object(atticus, 'screens', return_value=displays), patch.object(atticus.subprocess, 'run', side_effect=run), \
             patch.object(atticus, 'pref', side_effect=lambda k, d: False if k == 'draw' else d):
            shots = atticus.look(cleanup=False, window=window)
            self.assertEqual([c[:3] + c[4:] for c in calls], [[atticus.APP, '--look', '2', '42']])   # only its display, with its window id
            self.assertEqual(len(shots), 1)
            self.assertIn('Fixture App "Board" painted where it sits (hidden from the user); click spots as 2:x,y', shots[0][1])
            painted[0] = False; calls.clear()   # the window could not be captured: the label never claims it
            self.assertNotIn('painted', atticus.look(cleanup=False, window=window)[0][1])
            calls.clear()
            labels = [label for _, label in atticus.look(cleanup=False)]
            self.assertEqual(len(calls), 2); self.assertTrue(labels[0].endswith('click spots as 1:x,y in picture pixels)'))
        for path in Path(os.environ['ATTICUS_ASK']).glob('atticus-screen-*'): path.unlink()

    def test_learned_open_replays_in_front_when_the_user_asked_to_open(self):
        saved = {'cmds': [f"{atticus.ME} --show --bg https://www.netflix.com"], 'reply': 'Netflix is open in Chrome in the background.'}
        ask = 'Open Netflix.'
        with patch.object(atticus, 'skills', return_value={'open netflix': saved}), \
             patch.object(atticus, 'show', return_value='opened https://www.netflix.com in front') as show:
            with patch.dict(os.environ, {'ATTICUS_REQUEST': ask}):
                self.assertEqual(atticus.replay('open netflix'), saved['reply'].split('.')[0] + '.')
            show.assert_called_once_with('https://www.netflix.com', False)

    def test_old_foreground_shortcuts_upgrade_to_background_open(self):
        saved={'cmds':['open -a Notes'],'reply':'Done.'}
        with patch.object(atticus,'skills',return_value={'study':saved}),patch.object(atticus,'show',return_value='opened Notes in the background') as show:
            self.assertEqual(atticus.replay('study'),'Done.');show.assert_called_once_with('Notes',True)

    def test_open_preview_expands_shell_home_and_restore_uses_current_app(self):
        with patch.object(atticus,'preview_app') as preview:
            atticus.preview_commands('open -g ~/Documents/fixture.pdf')
            preview.assert_called_with(os.path.expanduser('~/Documents/fixture.pdf'),'open',directory=None)
        with patch.dict(os.environ,{'ATTICUS_FRONT':'Old Mail'}),patch.object(atticus,'osa',side_effect=['Editor','com.fixture.browser','Browser','Browser','']) as osa,patch.object(atticus,'preview_app',return_value={'app':'Browser'}),patch.object(atticus.time,'sleep'),patch.object(atticus.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
            atticus.show('https://fixture.invalid',bg=True)
            self.assertEqual(osa.call_args.args[1],'Editor')

    def test_browser_preview_stays_with_the_pinned_window_after_focus_changes(self):
        with patch.dict(os.environ,{'ATTICUS_FRONT':'Google Chrome'}),patch.object(atticus,'browser_adapter',return_value='chromium'),patch.object(atticus,'preview_app',return_value=self.target) as preview,patch.object(atticus,'page_ready',return_value=True),patch.object(atticus,'hands_map',return_value=None),patch.object(atticus,'emit') as emit,patch.object(atticus.subprocess,'run',side_effect=[subprocess.CompletedProcess([],0,'41\t73',''),subprocess.CompletedProcess([],0,'Fixture, 0, 0, 300, 200',''),subprocess.CompletedProcess([],0,'Page',''),subprocess.CompletedProcess([],0,'Filled',''),subprocess.CompletedProcess([],0,'Current field value',''),subprocess.CompletedProcess([],0,'Fixture, 10, 20, 410, 320',''),subprocess.CompletedProcess([],0,'Reread','')]) as run:
            atticus.web('read');atticus.web('fill','2','Text');atticus.web('read')
        self.assertIn('window id 41 whose id is 73',run.call_args.args[0][2])
        self.assertEqual(preview.call_args_list, [unittest.mock.call('Google Chrome','read',title='Fixture',frame=[0,0,300,200]),unittest.mock.call('Google Chrome','read',title='Fixture',frame=[10,20,400,300])])
        target=json.loads(emit.call_args.args[0][0][2:]);self.assertEqual(target['windowID'],'42');self.assertEqual(target['action'],'read')

    def test_applescript_ids_and_named_windows_use_the_same_target_helper(self):
        with patch.object(atticus,'preview_app') as preview:
            atticus.preview_commands('osascript -e \'tell application id "com.apple.Notes" to set name of window "Pilot" to "Pilot"\'')
            preview.assert_called_once_with('com.apple.Notes',title='Pilot',directory=None)
