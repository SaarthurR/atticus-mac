"""Replay actions use scratch storage and fake app workers, never paid calls or personal apps."""
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import atticus
from tests import scratch_dir


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.root=scratch_dir(self)
        for p in [patch.object(atticus,'SKILLS',str(self.root/'skills.json')),
                  patch.object(atticus,'RECENT',str(self.root/'recent.jsonl')),
                  patch.object(atticus,'WORKED',str(self.root/'worked.json')),patch.object(atticus,'ME_FILE',str(self.root/'me.json')),
                  patch.dict(os.environ,{'ATTICUS_ASK':str(self.root),'ATTICUS_FRONT':'Other Fixture','ATTICUS_FOCUS_GUARD':'1'},clear=True)]:
            p.start();self.addCleanup(p.stop)
        self.commands=['open -a Fixture','peekaboo menu click --app "com.atticus.fixture" --path "Fixture > Start meeting" --no-remote',
                       'osascript -e \'tell application "System Events" to get name of every window of process "Fixture"\'']

    def test_legacy_three_steps_upgrade_and_replay_native_actions_without_ai_or_reads(self):
        (self.root/'skills.json').write_text(json.dumps({'make a fixture meeting':{'cmds':self.commands,'reply':'Started.','mine':True}}))
        with patch.object(atticus,'show',return_value='opened Fixture in the background') as show,patch.object(atticus,'hands',return_value=('Clicked',True)) as hands,patch.object(atticus.subprocess,'run') as shell,patch.object(atticus,'start_claude') as ai:
            self.assertEqual(atticus.fast('Please start a new fixture meeting'),'Started.')
        show.assert_called_once_with('Fixture',True);hands.assert_called_once_with('menu','com.atticus.fixture','Fixture > Start meeting')
        shell.assert_not_called();ai.assert_not_called();self.assertEqual(len(atticus.skills()['make a fixture meeting']['cmds']),2)

    def test_internal_partial_request_keys_are_skipped_without_rewriting_storage(self):
        command = atticus.SHOW + ' Fixture'
        junk = 'open fixture\nAlready completed: first step\nRemaining words: second step'
        (self.root / 'skills.json').write_text(json.dumps({
            'open fixture': {'cmds': [command], 'reply': 'Opened.', 'mine': True},
            junk: {'cmds': [command], 'reply': 'Opened.', 'mine': True},
        }))
        self.assertEqual(set(atticus.skills()), {'open fixture'})
        self.assertEqual(set(json.loads((self.root / 'skills.json').read_text())), {'open fixture', junk})

    def test_automatic_open_learning_rejects_generic_references(self):
        document = self.root / 'Orchid-Report.pdf'
        document.write_text('%PDF-1.7\n')
        for task, target in [('open file path', str(document)),
                             ('reopen the file', str(document)),
                             ('settings', 'System Settings'), ('ur settings', 'Atticus'),
                             ('open this', 'VellumFox')]:
            command = f'{atticus.SHOW} {atticus.shlex.quote(target)}'
            with self.subTest(task=task), patch.object(atticus, 'cached_hands', return_value=None):
                self.assertIsNone(atticus.learn(task, [command], 'Opened.'))
                # The old format remains readable, but cannot replay an ungrounded binding.
                atticus.save_skills({task: {'cmds': [command], 'reply': 'Opened.', 'at': atticus._profile_date()}})
                before = (self.root / 'skills.json').read_bytes()
                with patch.object(atticus, 'show') as show:
                    self.assertIsNone(atticus.replay(task))
                show.assert_not_called()
                self.assertEqual(before, (self.root / 'skills.json').read_bytes())

    def test_resolved_spoken_names_learn_once_and_replay_without_ai(self):
        document = self.root / 'Chapter-B-Review.pdf'
        document.write_text('%PDF-1.7\n')
        downloads = self.root / 'Downloads'
        downloads.mkdir()
        cases = [('open velum lights', 'Vellum Lights'),
                 ('open velvet lights', 'Vellum Lights'),
                 ('open vel lights', 'Vellum Lights'),
                 ('open my chatter', 'ChatterBox'),
                 ('launch copper loom', 'CopperLoom'),
                 ('postbox', 'https://mail.example.test'),
                 ('postbox, open', 'https://mail.example.test'),
                 ('open classnest', 'https://classes.example.test/home'),
                 ('open my downloads folder', str(downloads)),
                 ('open my unit 3 chemistry study guide', str(document))]
        for task, target in cases:
            command = f'{atticus.SHOW} {atticus.shlex.quote(target)}'
            key = atticus.learning_key(task)
            with self.subTest(task=task), patch.object(atticus, 'cached_hands', return_value=None):
                atticus.save_skills({})
                self.assertTrue(atticus.learn('Like, can you ' + task, [command], 'Opened.'))
                self.assertEqual(set(atticus.skills()), {key})
                with patch.object(atticus, 'show', return_value='opened') as show, patch.object(atticus, 'start_claude') as ai:
                    self.assertEqual(atticus.fast(task), 'Opened.')
                    self.assertEqual(atticus.fast.shortcut['key'], key)
                show.assert_called_once_with(target, False)
                ai.assert_not_called()
                # Existing automatic bindings have neither mine nor asked metadata.
                atticus.save_skills({key: {'cmds': [command], 'reply': 'Opened.', 'at': atticus._profile_date()}})
                with patch.object(atticus, 'show', return_value='opened') as show, patch.object(atticus, 'start_claude') as ai:
                    self.assertEqual(atticus.fast(task), 'Opened.')
                    self.assertEqual(atticus.fast.shortcut['key'], key)
                show.assert_called_once_with(target, False)
                ai.assert_not_called()

    def test_say_it_once_for_unseen_apps_and_explicit_file_aliases(self):
        self.assertEqual(atticus.learning_key('new project'), 'new project')
        self.assertEqual(atticus.learning_key('Like, can you like open VellumFox?'), 'open vellumfox')
        for app in ('VellumFox', 'Quasar Finch', 'CopperLoom'):
            with patch.object(atticus, 'cached_hands', return_value=None):
                self.assertTrue(atticus.learn(f'Like, can you open {app}?', [f'{atticus.SHOW} "{app}"'], 'Opened.'))
            key = f'open {app.lower()}'
            self.assertIn(key, atticus.skills())
            with patch.object(atticus, 'show', return_value='opened') as show, patch.object(atticus, 'start_claude') as ai:
                self.assertEqual(atticus.fast(f'Can you open {app}?'), 'Opened.')
            show.assert_called_once_with(app, False)
            ai.assert_not_called()
        with patch.object(atticus, 'cached_hands', return_value=None):
            document = self.root / 'Orchid-Report.pdf'
            document.write_text('%PDF-1.7\n')
            command = 'open ' + atticus.shlex.quote(str(document))
            self.assertTrue(atticus.learn('orchid report', [command], 'Opened.'))
            self.assertTrue(atticus.learn('reading time', [command], 'Opened.',
                                          f'When I say reading time, open {document}'))
        atticus.unlearn('Like, can you open VellumFox?')
        self.assertNotIn('open vellumfox', atticus.skills())

    def test_new_shortcuts_drop_reads_and_keep_the_target_when_front_app_changes(self):
        with patch.object(atticus,'cached_hands',return_value=None): self.assertTrue(atticus.learn('make a fixture meeting',self.commands,'Started.'))
        commands=atticus.skills()['make a fixture meeting']['cmds']
        self.assertEqual(commands,[atticus.SHOW+' --bg Fixture',atticus.HANDS+" menu com.atticus.fixture 'Fixture > Start meeting'"])
        self.assertNotIn('Other Fixture',' '.join(commands))
        self.assertIsNone(atticus.shortcut_commands('export',['%s click "File > Export"'%atticus.HANDS]))

    def test_a_generalized_replay_learns_the_app_it_actually_used(self):
        atticus.save_skills({'put fixture alpha left':{'cmds':['open -a "Fixture Alpha"'],'reply':'Done.','mine':True}})
        resolve=lambda name:{'fixture alpha':'Fixture Alpha','fixture beta':'Fixture Beta'}.get(name.lower())
        with patch.object(atticus,'app_named',side_effect=resolve),patch.object(atticus,'show',return_value='opened'),patch.object(atticus,'tip'):
            self.assertEqual(atticus.fast('when I say layout mode, put fixture beta left'),'Done.')
        command=atticus.skills()['layout mode']['cmds'][0]
        self.assertIn('Fixture Beta',command);self.assertNotIn('Fixture Alpha',command)

    def test_explicit_open_remains_foreground_and_mutating_scripts_are_kept(self):
        script='osascript -e \'tell application "Fixture" to set name of window 1 to "Done"\''
        self.assertEqual(atticus.shortcut_commands('open Fixture',['open -a Fixture',script]),['open -a Fixture',script])
        self.assertEqual(atticus.shortcut_commands('check',['osascript -e \'get "click"\'']),[])
        found=f'{atticus.SHOW} --bg "/tmp/Guide.pdf" && ls /tmp'   # a file found by searching: only the open is replayed
        self.assertEqual(atticus.shortcut_commands('study guide',['mdfind -name guide 2>/dev/null | head -20; mdfind x | grep -i y',found]),[f'{atticus.SHOW} --bg /tmp/Guide.pdf'])
        with patch.object(atticus,'cached_hands',return_value=None): self.assertIsNone(atticus.learn('study guide',['ls /tmp > /tmp/out',found],'Opened.'))   # a write is not a lookup

    def test_act_then_sleep_then_state_read_learns_the_act_alone(self):
        play,state='osascript -e \'tell application "Fixture" to play\'','osascript -e \'tell application "Fixture" to player state as string\''
        track='osascript -e \'tell application "Fixture" to name of current track\''
        with patch.object(atticus,'cached_hands',return_value=None):
            self.assertTrue(atticus.learn('unpause fixture',[f'{play} && sleep 1 && {state}'],'Playing again.'))
            self.assertEqual(atticus.skills()['unpause fixture']['cmds'],[play])
            self.assertEqual(atticus.shortcut_commands('pause fixture',[f'{play.replace("play","pause")} && {track}']),[play.replace('play','pause')])
            self.assertIsNone(atticus.shortcut_commands('play fixture',[f'{state} && {play}']))   # a read before the act: replay would act blind
            self.assertIsNone(atticus.learn('play fixture',[f'{state} && sleep 1 && {play}'],'Playing.'))
            delete='osascript -e \'tell application "System Events" to tell process "Fixture" to click button "Delete" of window 1\''
            self.assertIsNone(atticus.learn('clear fixture',[f'{delete} && sleep 1 && {state}'],'Cleared.'))   # risky acts stay unlearned
        self.assertEqual(set(atticus.skills()),{'unpause fixture'})
        both='osascript -e \'tell application "Fixture" to pause\' -e \'tell application "Fixture" to get player state\''
        self.assertEqual(atticus.shortcut_commands('pause fixture',[both,state]),[both])   # an act with its own check in one script stays
        framed='osascript -e \'tell application "System Events"\' -e \'tell process "Fixture" to get name of every window\' -e \'end tell\''
        self.assertEqual(atticus.shortcut_commands('windows',[framed]),[])

    def test_replay_says_the_outcome_not_how_the_first_run_went(self):
        play='osascript -e \'tell application "Fixture" to play\''
        (self.root/'skills.json').write_text(json.dumps({'unpause fixture':{'cmds':[play],'reply':'Fixture is playing. The first check still showed it paused, but a second check confirmed it.'}}))
        with patch.object(atticus.subprocess,'run',return_value=atticus.subprocess.CompletedProcess([],0,'','')):
            self.assertEqual(atticus.fast('unpause fixture'),'Fixture is playing.')
        for whole in ['Done: focus mode.','Typed "Hi! See you." into Mail.','Opened 10 Bury Pl. Tell me the city.','Playing 1M. It runs in the background.','I typed your reply into the mail box. It isn’t sent yet.','Notes is open. Do not close it.']:
            self.assertEqual(atticus.outcome(whole),whole)

    def test_unsupported_peekaboo_falls_back_without_running(self):
        atticus.save_skills({'do fixture':{'cmds':['peekaboo click --id 12'],'reply':'Done.','mine':True}})
        with patch.object(atticus.subprocess,'run') as run:self.assertIsNone(atticus.replay('do fixture'));run.assert_not_called()
        self.assertIsNone(atticus.shortcut_commands('do fixture',[self.commands[-1]+' && open -a Fixture']))
        self.assertIsNone(atticus.shortcut_commands('do fixture',[atticus.ME+' ask again']))
        reply,saved=atticus.remember_workflow('nested fixture',f'Done. [workflow nested fixture | Use the native app.] [replay python3 {atticus.ME} ask again]',True,['open Fixture'])
        self.assertTrue(saved);self.assertNotIn('nested fixture',atticus.skills())

    def test_native_menu_bypasses_map_capture_but_waits_for_confirmation(self):
        args=('menu','com.atticus.fixture','Fixture > Start meeting')
        worker=unittest.mock.Mock(returncode=0,stdout='Clicked Start meeting\n',stderr='')
        with patch.object(atticus,'wait_commit',return_value=True),patch.object(atticus,'hands_call',return_value=worker) as call,patch.object(atticus,'hands_map') as mapping:
            self.assertTrue(atticus.hands(*args)[1]);call.assert_called_once_with(list(args),timeout=2);mapping.assert_not_called()
        with patch.object(atticus,'wait_commit',return_value=False),patch.object(atticus,'hands_call') as call:
            self.assertFalse(atticus.hands(*args)[1]);call.assert_not_called()

    def test_guarded_background_open_does_not_poll_or_sleep(self):
        with patch.object(atticus,'osa') as osa,patch.object(atticus.time,'sleep') as sleep,patch.object(atticus,'preview_app'),patch.object(atticus.subprocess,'run',return_value=unittest.mock.Mock(returncode=0,stdout='')):
            atticus.show('Fixture',bg=True);osa.assert_not_called();sleep.assert_not_called()

    def test_failed_direct_open_falls_back_instead_of_claiming_success(self):
        atticus.save_skills({'open fixture':{'cmds':[atticus.SHOW+' Fixture'],'reply':'Opened.','mine':True}})
        with patch.object(atticus,'show',return_value='no app or file called "Fixture"'):
            self.assertIsNone(atticus.replay('open fixture'))

    def test_recent_memory_creates_missing_scratch_directory(self):
        missing=self.root/'new';recent=missing/'recent.jsonl'
        with patch.object(atticus,'DIR',str(missing)),patch.object(atticus,'RECENT',str(recent)):
            atticus.remember_turn('Find fixture notes','Found them.');self.assertEqual(atticus.recent()[0]['q'],'Find fixture notes')
            self.assertEqual(recent.stat().st_mode&0o777,0o600)
            with patch.object(atticus.os,'replace',side_effect=OSError('disk full')):
                with self.assertRaises(OSError): atticus.remember_turn('Other ask','Other answer')
            self.assertEqual(atticus.recent()[0]['q'],'Find fixture notes')

    def test_first_ai_answer_saves_memory_and_log_in_a_fresh_directory(self):
        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        missing=self.root/'fresh';brain=unittest.mock.Mock(return_value=('Found them. [unlearn]',0,[]));brain.ok=True;brain.cmds=[];brain.ran=[];brain.observed=[]
        with patch.object(atticus,'DIR',str(missing)),patch.object(atticus,'RECENT',str(missing/'recent.jsonl')),patch.object(atticus,'MEMORY',str(missing/'memory.md')),patch.object(atticus.threading,'Thread',NoThread),patch('sys.argv',['atticus.py','Find fixture notes']),patch.multiple(atticus,licensed=lambda:True,ping=lambda:None,fast=lambda _:None,front=lambda:('Fixture','Scratch'),osa=lambda *a:'',screens=lambda:[],describe=lambda *a:'Scratch display',selection_context=lambda:'',screen_for=lambda *a:None,run=brain,wait_commit=lambda:True,restore_focus=lambda *a:None,say=lambda *a:None,tip=lambda *a:None,look=lambda:[],hands_map=lambda *a:None):
            atticus.main();self.assertEqual(atticus.recent()[0]['a'],'Found them.');self.assertTrue((missing/'log.jsonl').exists())
        brain.assert_called_once()

    def test_bare_running_check_is_dropped_and_a_new_shortcut_or_workflow_shows_the_learned_pill(self):
        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        quit,check='osascript -e \'tell application "Fixture" to quit\'','osascript -e \'application "Fixture" is running\''
        self.assertEqual(atticus.shortcut_commands('close fixture',[quit,check]),[quit])
        self.assertEqual(atticus.shortcut_commands('close fixture',[f'{quit} && sleep 1 && {check.replace("is","is not")}']),[quit])
        self.assertIsNone(atticus.shortcut_commands('close fixture',[f'{check} && {quit}']))   # a check before the act still refuses
        guarded='osascript -e \'tell application "Fixture"\' -e \'if player state is playing then pause\' -e \'end tell\''
        self.assertEqual(atticus.shortcut_commands('pause fixture',[guarded]),[guarded])
        def ask(task,reply,cmds):
            brain=unittest.mock.Mock(return_value=(reply,0,[]));brain.ok=True;brain.cmds=cmds;brain.ran=cmds;brain.observed=[]
            tip=unittest.mock.Mock()
            with patch.object(atticus,'DIR',str(self.root)),patch.object(atticus,'RECENT',str(self.root/'recent.jsonl')),patch.object(atticus,'MEMORY',str(self.root/'memory.md')),patch.object(atticus.threading,'Thread',NoThread),patch('sys.argv',['atticus.py',task]),patch.multiple(atticus,licensed=lambda:True,ping=lambda:None,fast=lambda _:None,front=lambda:('Fixture','Scratch'),osa=lambda *a:'',screens=lambda:[],describe=lambda *a:'Scratch display',selection_context=lambda:'',screen_for=lambda *a:None,run=brain,wait_commit=lambda:True,restore_focus=lambda *a:None,say=lambda *a:None,tip=tip,look=lambda:[],hands_map=lambda *a:None,cached_hands=lambda:None):
                with patch.object(atticus,'app_id',return_value='com.example.fixture'),patch.object(atticus,'app_running',return_value=False): atticus.main()
            return tip.call_args.args[1]
        self.assertEqual(ask('Close fixture','Fixture is closed.',[quit,check]),'Learned: Say “Close fixture” any time.')
        self.assertEqual(atticus.skills()['close fixture']['cmds'],[quit])
        self.assertEqual(atticus.recent()[-1]['shortcut']['key'],'close fixture')
        self.assertEqual(ask('Close fixture','Fixture is closed.',[quit,check]),'')   # already known: no pill
        self.assertEqual(ask('Tidy fixture','Tidied. [workflow tidy fixture | Use the View menu.]',[f'{atticus.HANDS} see Fixture']),'Learned: Procedure saved for next time.')

    def test_instant_quit_uses_bundle_id_verifies_and_beats_old_skill(self):
        old='osascript -e \'tell application "Fixture Display" to quit\''
        atticus.save_skills({'close fixture display':{'cmds':[old],'reply':'Old false success.','mine':True},
                             'end fixture':{'cmds':[old],'reply':'Ended.','mine':True}})
        resolve=lambda name: 'Fixture' if name == 'fixture display' else None
        with patch.object(atticus,'app_named',side_effect=resolve),patch.object(atticus,'app_id',return_value='com.example.fixture') as app_id, \
             patch.object(atticus,'quit_app',return_value=True) as quit_app,patch.object(atticus,'replay') as replay:
            self.assertEqual(atticus.fast('close fixture display'),'Closed Fixture.')
            app_id.assert_called_once_with('Fixture');quit_app.assert_called_once_with('com.example.fixture');replay.assert_not_called()
            self.assertIn('application id "com.example.fixture"',atticus.fast.cmds[0])
            self.assertIsNone(atticus.fast('close this tab'))
            self.assertIsNone(atticus.fast('close the window'))
        with patch.object(atticus,'app_named',side_effect=resolve),patch.object(atticus,'app_id',return_value='com.example.fixture'), \
             patch.object(atticus,'quit_app',return_value=False):
            self.assertEqual(atticus.fast('quit fixture display'),'Fixture is still open.')
            self.assertEqual(atticus.fast.cmds,[])
        with patch.object(atticus,'app_named',return_value='Fixture'),patch.object(atticus,'app_id',return_value='com.example.fixture') as app_id, \
             patch.object(atticus,'quit_app',return_value=True) as quit_app,patch.object(atticus.subprocess,'run') as shell:
            self.assertEqual(atticus.replay('end fixture'),'Ended.')
            app_id.assert_called_once_with('Fixture');quit_app.assert_called_once_with('com.example.fixture');shell.assert_not_called()
        with patch.object(atticus,'app_running',side_effect=[True,True,False]),patch.object(atticus,'osa') as osa,patch.object(atticus.time,'sleep'):
            self.assertTrue(atticus.quit_app('com.example.fixture'))
        osa.assert_called_once_with('tell application id "com.example.fixture" to quit',timeout=2)

    def test_user_reported_failure_unlearns_without_saving_the_correction(self):
        command='osascript -e \'tell application "Fixture" to set visible to false\''
        atticus.save_skills({'hide fixture':{'cmds':[command],'reply':'Fixture is hidden.','mine':True}})
        worker=unittest.mock.Mock(returncode=0,stdout='fixture became hidden\n',stderr='')
        with patch.object(atticus.subprocess,'run',return_value=worker),patch.object(atticus,'preview_commands'):
            answer=atticus.fast('hide fixture')
        self.assertEqual(answer,'Fixture is hidden.')
        atticus.remember_turn('hide fixture',answer,atticus.fast.shortcut)

        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        brain=unittest.mock.Mock(return_value=('Fixture is hidden now. [unlearn] [workflow hide fixture | Hide it, then check.]',0,[]))
        brain.ok=True;brain.cmds=brain.ran=[command];brain.observed=[{'action':command,'error':False,'result':'verified hidden'}]
        say=unittest.mock.Mock()
        with patch.object(atticus.threading,'Thread',NoThread),patch('sys.argv',['atticus.py','It is still visible']), \
             patch.multiple(atticus,licensed=lambda:True,ping=lambda:None,fast=lambda _:None,front=lambda:('Fixture','Scratch'),
                            osa=lambda *a:'',screens=lambda:[],describe=lambda *a:'Scratch display',selection_context=lambda:'',
                            screen_for=lambda *a:None,tool_help=lambda *a,**k:'',run=brain,wait_commit=lambda:True,
                            restore_focus=lambda *a:None,say=say,tip=lambda *a:None,look=lambda:[],hands_map=lambda *a:None):
            atticus.main()
        self.assertEqual(say.call_args.args[1],'Fixture is hidden now.')   # no control tag shows, and the redo saves nothing
        self.assertEqual(atticus.workflows(),{})
        prompt=brain.call_args.args[0]
        self.assertIn('Previous learned shortcut',prompt)
        self.assertIn('hide fixture',prompt)
        self.assertIn('fixture became hidden',prompt)
        self.assertEqual(brain.call_args.kwargs['request'],'It is still visible')
        self.assertNotIn('hide fixture',atticus.skills())

    def test_unrelated_ask_after_replay_keeps_the_shortcut(self):
        command='osascript -e \'tell application "Fixture" to set visible to false\''
        atticus.save_skills({'hide fixture':{'cmds':[command],'reply':'Fixture is hidden.','mine':True}})
        worker=unittest.mock.Mock(returncode=0,stdout='fixture became hidden\n',stderr='')
        with patch.object(atticus.subprocess,'run',return_value=worker),patch.object(atticus,'preview_commands'):
            answer=atticus.fast('hide fixture')
        atticus.remember_turn('hide fixture',answer,atticus.fast.shortcut)

        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        brain=unittest.mock.Mock(return_value=('The unrelated answer.',0,[]))
        brain.ok=True;brain.cmds=brain.ran=[];brain.observed=[]
        with patch.object(atticus.threading,'Thread',NoThread),patch('sys.argv',['atticus.py','Explain an unrelated topic']), \
             patch.multiple(atticus,licensed=lambda:True,ping=lambda:None,fast=lambda _:None,front=lambda:('Fixture','Scratch'),
                            osa=lambda *a:'',screens=lambda:[],describe=lambda *a:'Scratch display',selection_context=lambda:'',
                            screen_for=lambda *a:None,tool_help=lambda *a,**k:'',run=brain,wait_commit=lambda:True,
                            restore_focus=lambda *a:None,say=lambda *a:None,tip=lambda *a:None,look=lambda:[],hands_map=lambda *a:None):
            atticus.main()
        self.assertIn('Previous learned shortcut',brain.call_args.args[0])
        self.assertIn('hide fixture',atticus.skills())

    def test_stray_unlearn_control_is_never_shown(self):
        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        brain=unittest.mock.Mock(return_value=('Done. [unlearn]',0,[]))
        brain.ok=True;brain.cmds=brain.ran=[];brain.observed=[]
        say=unittest.mock.Mock()
        with patch.object(atticus.threading,'Thread',NoThread),patch('sys.argv',['atticus.py','Do the fixture task']), \
             patch.multiple(atticus,licensed=lambda:True,ping=lambda:None,fast=lambda _:None,front=lambda:('Fixture','Scratch'),
                            osa=lambda *a:'',screens=lambda:[],describe=lambda *a:'Scratch display',selection_context=lambda:'',
                            screen_for=lambda *a:None,tool_help=lambda *a,**k:'',run=brain,wait_commit=lambda:True,
                            restore_focus=lambda *a:None,say=say,tip=lambda *a:None,look=lambda:[],hands_map=lambda *a:None):
            atticus.main()
        self.assertEqual(say.call_args.args[1],'Done.')
        self.assertEqual(atticus.recent()[-1]['a'],'Done.')

    def test_failed_replay_is_redone_and_successful_recovery_replaces_it(self):
        quit='osascript -e \'tell application "Fixture" to quit\''
        atticus.save_skills({'bye fixture':{'cmds':[quit],'reply':'Fixture is closed.','mine':True}})
        stubs=dict(app_id=lambda *a:'com.example.fixture',osa=lambda *a,**k:'',app_named=lambda *a:None)
        with patch.multiple(atticus,**stubs),patch.object(atticus,'app_running',side_effect=[True,False]),patch.object(atticus.time,'sleep'),patch.object(atticus.subprocess,'run') as shell:
            self.assertEqual(atticus.fast('bye fixture'),'Fixture is closed.')   # verified: the same instant reply
            self.assertIsNone(atticus.fast.failed);shell.assert_not_called()
        with patch.object(atticus,'wants_focus',return_value=True),patch.multiple(atticus,**stubs),patch.object(atticus.time,'sleep'),patch.object(atticus,'preview_commands'), \
             patch.object(atticus.subprocess,'run',return_value=atticus.subprocess.CompletedProcess([],0,'','')):
            atticus.save_skills({**atticus.skills(),'show fixture':{'cmds':['open -a Fixture'],'reply':'Opened.','mine':True}})
            with patch.object(atticus,'app_running',return_value=False): self.assertIsNone(atticus.replay('show fixture'))
            self.assertEqual(atticus.replay.ran[-1],'Fixture => not running')
            with patch.object(atticus,'app_running',return_value=True): self.assertEqual(atticus.replay('show fixture'),'Opened.')

        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        replacement=atticus.HANDS+" menu com.example.fixture 'Fixture > Quit'"
        brain=unittest.mock.Mock(return_value=('Fixture is closed now; the shortcut had not quit it. [unlearn]',0,[]))
        brain.ok=True;brain.cmds=brain.ran=[replacement]
        brain.observed=[{'action':replacement,'error':False,'result':'Fixture closed'}]
        say,tip=unittest.mock.Mock(),unittest.mock.Mock()
        with patch.object(atticus.threading,'Thread',NoThread),patch('sys.argv',['atticus.py','bye fixture']),patch.object(atticus,'app_running',return_value=True),patch.object(atticus.time,'sleep'), \
             patch.multiple(atticus,**stubs,licensed=lambda:True,ping=lambda:None,front=lambda:('Fixture','Scratch'),screens=lambda:[],describe=lambda *a:'Scratch display',
                            selection_context=lambda:'',screen_for=lambda *a:None,tool_help=lambda *a,**k:'',run=brain,wait_commit=lambda:True,
                            restore_focus=lambda *a:None,say=say,tip=tip,look=lambda:[],hands_map=lambda *a:None,report=lambda *a:None,cached_hands=lambda:None):
            atticus.main()
        said=[c.args for c in say.call_args_list]
        self.assertIn(('▸','The shortcut did not work. Redoing it'),said)
        self.assertNotIn('Fixture is closed.',[s for _,s in said])   # never the learned success line
        self.assertEqual(said[-1][1],'Fixture is closed now; the shortcut had not quit it.')
        prompt=brain.call_args.args[0]
        self.assertIn('still open',prompt);self.assertIn('failed (see its output): redo the request',prompt)
        self.assertEqual(atticus.skills()['bye fixture']['cmds'],[replacement])
        self.assertEqual(tip.call_args.args[1],'Learned: Say “bye fixture” any time.')

    def test_a_quit_that_is_still_running_is_not_learned(self):
        command='osascript -e \'tell application id "com.example.fixture" to quit\''
        with patch.object(atticus,'cached_hands',return_value=None),patch.object(atticus,'app_running',return_value=True):
            self.assertIsNone(atticus.learn('close fixture',[command],'Fixture is closed.'))
        with patch.object(atticus,'shortcut_commands',return_value=['osascript -e "']):
            self.assertIsNone(atticus.learn('malformed fixture',[command],'Done.'))
        self.assertNotIn('close fixture',atticus.skills())

    def test_reference_ask_receives_recent_target_and_agent_history(self):
        class NoThread:
            def __init__(self,*a,**kw): pass
            def start(self): pass
            def join(self,*a): pass
        url='https://fixture.example/posts/42'
        agent=self.root/'agents'/('a'*32);agent.mkdir(parents=True)
        atticus.private_json(str(agent/'context.json'),{'id':'a'*32,'status':'done','created':time.time(),
                                                       'brief':'Find a useful post','links':[url]})
        (self.root/'worked.json').write_text(json.dumps({'app':'Reader Fixture','window':'Earlier post'}))
        brain=unittest.mock.Mock(return_value=('Opened the earlier post.',0,[]));brain.ok=True;brain.cmds=[];brain.ran=[];brain.observed=[]
        with patch.object(atticus,'RECENT',str(self.root/'recent.jsonl')),patch.object(atticus,'MEMORY',str(self.root/'memory.md')):
            atticus.remember_turn('Find a useful post','Opened '+url)
            with patch.object(atticus.threading,'Thread',NoThread),patch('sys.argv',['atticus.py','Open that post you opened']),patch.multiple(atticus,licensed=lambda:True,ping=lambda:None,fast=lambda _:None,front=lambda:('Fixture','Scratch'),osa=lambda *a:'',screens=lambda:[],describe=lambda *a:'Scratch display',selection_context=lambda:'',screen_for=lambda *a:None,run=brain,wait_commit=lambda:True,restore_focus=lambda *a:None,say=lambda *a:None,tip=lambda *a:None,look=lambda:[],hands_map=lambda *a:None):
                atticus.main()
        prompt=brain.call_args.args[0]
        self.assertIn('Earlier:\nQ: Find a useful post\nA: Opened '+url,prompt)
        self.assertIn('Last task worked in: Reader Fixture "Earlier post"',prompt)
        self.assertIn('Background tasks',prompt);self.assertIn('a'*32,prompt)
        self.assertEqual(brain.call_args.kwargs['request'],'Open that post you opened')
