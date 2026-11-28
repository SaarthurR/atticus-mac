"""Product memory regressions: fake model results, scratch storage, no Mac actions."""
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import atticus
from tests import scratch_dir


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(atticus, 'SKILLS', str(scratch_dir(self) / 'skills.json'))
        p.start()
        self.addCleanup(p.stop)

    def test_workflow_title_must_belong_to_this_request_and_tags_cannot_merge(self):
        for reply in (
            'Done. [workflow fetch channel video | Read the feed.]',
            'Done. [workflow fetch channel video | Read the feed.] [workflow split desk | Place windows.]',
        ):
            with self.subTest(reply=reply):
                _, saved = atticus.remember_workflow('split desk', reply, True, ['open -a VellumFox'])
                self.assertFalse(saved)
        self.assertEqual(atticus.workflows(), {})

    def test_replay_tag_cannot_bypass_shared_learning_target_guard(self):
        document = Path(atticus.DIR) / 'Orchid-Report.pdf'
        document.write_text('%PDF-1.7\n')
        command = 'open ' + atticus.shlex.quote(str(document))
        _, saved = atticus.remember_workflow('open file path',
            f'Opened. [workflow open file path | Locate the requested file and check it opens.] [replay {command}]',
            True, [command])
        self.assertTrue(saved)  # a procedure is guidance; the one-off path must not become an executable binding
        self.assertNotIn('open file path', atticus.skills())

    def test_automatically_saves_and_retrieves_verified_browser_procedure(self):
        p = unittest.mock.Mock()
        p.stdin = io.StringIO(); p.ask = ''; p.returncode = 0
        p.stdout = map(json.dumps, [
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Bash',
             'input': {'command': atticus.WEB + ' read'}}]}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'Saved successfully.'}]}},
            {'type': 'result', 'result': 'Created your calendar event. [workflow create calendar event | Read the calendar form, fill today\'s requested values, save, then check the event appears.]'}])
        with patch.object(atticus, 'say'):
            reply, _, _ = atticus.run('make a calendar event', p)
        reply, saved = atticus.remember_workflow('make a calendar event', reply, atticus.run.ok, atticus.run.cmds)
        self.assertTrue(saved)
        self.assertEqual(reply, 'Created your calendar event.')
        method = atticus.workflows('Can you make a new calendar event tomorrow?')
        self.assertIn('Read the calendar form', method)
        self.assertNotIn('workflow', reply)
        self.assertEqual(atticus.workflows('open calendar'), '')
        with patch.object(atticus.subprocess, 'run') as action:
            self.assertIn('saved', atticus.fast('And remember how to make a calendar event for the future'))
            action.assert_not_called()

    def test_never_saves_failed_incomplete_or_disabled_tasks(self):
        for reply, ok, cmds in [
                ('Done. [workflow start meeting | Use the menu; check meeting controls.]', False, ['open x']),
                ('Could not complete it. [workflow start meeting | Use the menu.]', True, ['open x']),
                ('Done. [workflow start meeting | Use the menu.]', True, []),
                ('[workflow start meeting | Use the menu.]', True, ['open x'])]:
            clean, saved = atticus.remember_workflow('start meeting', reply, ok, cmds)
            self.assertFalse(saved)
            self.assertNotIn('[workflow', clean)
        with patch.object(atticus, 'pref', return_value=False):
            _, saved = atticus.remember_workflow('start meeting', 'Done. [workflow start meeting | Check meeting controls.]', True, ['open x'])
        self.assertFalse(saved)
        self.assertFalse((Path(atticus.DIR) / 'workflows.json').exists())

    def test_unverified_history_cannot_be_claimed_as_remembered(self):
        with patch.object(atticus.subprocess, 'run') as action:
            reply = atticus.fast('remember how to create a meeting')
        self.assertIn('do not have a verified procedure', reply)
        action.assert_not_called()

    def test_learns_the_way_that_worked_without_the_ai_writing_a_tag(self):
        menu = atticus.HANDS + ' click "Zoom Workplace > Start meeting"'
        tool = lambda i, c: {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': i, 'name': 'Bash', 'input': {'command': c}}]}}
        result = lambda i, err, content='': {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': i, 'is_error': err, 'content': content}]}}
        p = unittest.mock.Mock()
        p.stdin = io.StringIO(); p.ask = ''; p.returncode = 0
        p.stdout = map(json.dumps, [tool('a', atticus.HANDS + ' see zoom.us'), result('a', False),
                                    tool('b', 'osascript -e "click New meeting"'), result('b', True),   # tried, failed, dropped
                                    tool('c', menu), result('c', False, 'Meeting controls are visible.'),
                                    {'type': 'result', 'result': 'Your Zoom meeting started.'}])
        with patch.object(atticus, 'say'):
            reply, _, _ = atticus.run('Um, make a new Zoom meeting', p)
        atticus.learn('Um, make a new Zoom meeting', atticus.run.cmds, reply)
        self.assertEqual(atticus.skills()['make a new zoom meeting']['cmds'], [atticus.HANDS+' menu zoom.us \'Zoom Workplace > Start meeting\''])
        with patch.object(atticus, 'hands', return_value=('Clicked Start meeting', True)):
            self.assertEqual(atticus.fast('start a zoom meeting'), 'Your Zoom meeting started.')
        atticus.learn('click new meeting', [atticus.HANDS + ' click 245,340'], 'Done.')   # a screen spot moves: never learned
        self.assertNotIn('click new meeting', atticus.skills())

    def test_learns_only_the_successful_retry_when_a_tool_reports_failure(self):
        first, retry = (f'{atticus.PLACE} Fixture fullscreen {screen}' for screen in ('monitor', 'laptop'))
        tool = lambda i, command: {'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': i, 'name': 'Bash', 'input': {'command': command}}]}}
        receipt = lambda i, output, error=False: {'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': i, 'is_error': error, 'content': output}]}}
        p = unittest.mock.Mock(stdin=io.StringIO(), ask='', returncode=0)
        p.stdout = map(json.dumps, [tool('first', first), receipt('first', 'NOT DONE: wrong display.', True),
                                    tool('retry', retry), receipt('retry', 'Fixture window -> fullscreen.'),
                                    {'type': 'result', 'is_error': False, 'result': 'Done.'}])
        with patch.object(atticus, 'say'):
            reply, _, _ = atticus.run('Arrange workspace', p)
        self.assertTrue(atticus.run.ok)
        self.assertEqual(atticus.run.cmds, [retry])
        with patch.object(atticus, 'cached_hands', return_value=None):
            self.assertTrue(atticus.learn('Arrange workspace', atticus.run.cmds, reply))
        self.assertEqual(atticus.skills()['arrange workspace']['cmds'], [retry])

    def test_failure_words_in_ordinary_read_output_are_untrusted_text(self):
        p = unittest.mock.Mock(stdin=io.StringIO(), ask='', returncode=0)
        p.stdout = map(json.dumps, [
            {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'id': 'read', 'name': 'Read', 'input': {'file_path': 'fixture.txt'}}]}},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'read', 'is_error': False,
                 'content': 'The page says the previous attempt failed and cannot continue.'}]}},
            {'type': 'result', 'is_error': False, 'result': 'I read the page.'}])
        with patch.object(atticus, 'say'):
            atticus.run('Read the fixture', p)
        self.assertTrue(atticus.run.ok)
        self.assertFalse(atticus.run.observed[0]['error'])

    def test_failed_or_unsafe_receipts_are_not_learned(self):
        tool = lambda command: {'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': 'action', 'name': 'Bash', 'input': {'command': command}}]}}
        receipt = lambda output, error: {'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': 'action', 'is_error': error, 'content': output}]}}
        for command, output, error, ok in [(f'{atticus.PLACE} Fixture fullscreen laptop', 'NOT DONE: no window found.', True, False),
                                           ('rm -rf /tmp/example', 'Done.', False, True)]:
            with self.subTest(command=command):
                p = unittest.mock.Mock(stdin=io.StringIO(), ask='', returncode=0)
                p.stdout = map(json.dumps, [tool(command), receipt(output, error),
                                            {'type': 'result', 'is_error': False, 'result': 'Done.'}])
                with patch.object(atticus, 'say'):
                    reply, _, _ = atticus.run('Arrange workspace', p)
                self.assertEqual(atticus.run.ok, ok)
                with patch.object(atticus, 'cached_hands', return_value=None):
                    self.assertIsNone(atticus.learn('Arrange workspace', atticus.run.cmds, reply))
        self.assertEqual(atticus.skills(), {})

    def test_replay_runs_instantly_for_any_wording_and_rejects_unsafe_commands(self):
        cmd = atticus.HANDS + ' menu us.zoom.xos "Zoom Workplace > Start meeting"'
        reply, saved = atticus.remember_workflow('Um, can you make a new Zoom meeting?',
            f'Your meeting started. [workflow start zoom meeting | Use the Zoom menu; check the meeting window.] [replay {cmd}]', True, [cmd])
        self.assertTrue(saved)
        self.assertEqual(reply, 'Your meeting started.')
        with patch.object(atticus, 'hands', return_value=('Clicked Start meeting', True)) as action:
            self.assertEqual(atticus.fast('Make a zoom meeting.'), 'Your meeting started.')
            self.assertIsNone(atticus.fast('make a zoom call'))   # different words that matter: the AI decides
        self.assertEqual(action.call_args_list[0].args, ('menu', 'us.zoom.xos', 'Zoom Workplace > Start meeting'))
        for bad in [atticus.HANDS + ' click 1,2', 'rm -rf ~/x', atticus.HANDS + ' see x']:
            atticus.remember_workflow('do thing', f'Done. [workflow do thing | a] [replay {bad}]', True, ['open x'])
            self.assertNotIn('do thing', atticus.skills())

    def test_method_can_contain_shell_brackets_but_malformed_metadata_is_not_saved(self):
        reply, saved = atticus.remember_workflow('check report ready',
            'Ready. [workflow check report ready | Run [ -f report.txt ] and inspect its contents.]', True, ['test -f report.txt'])
        self.assertTrue(saved)
        self.assertEqual(reply, 'Ready.')
        self.assertIn('[ -f report.txt ]', atticus.workflows('check report ready'))
        for tag in ['[workflow invalid]', '[workflow | missing task]', '[workflow missing method | ]']:
            _, saved = atticus.remember_workflow('bad task', 'Done. ' + tag, True, ['open x'])
            self.assertFalse(saved)

    def test_model_recipe_cannot_save_commands_that_were_not_run(self):
        actual=f'{atticus.PLACE} Editor full monitor'
        invented=f'{atticus.PLACE} Browser full laptop'
        _,saved=atticus.remember_workflow('arrange desk',f'Done. [workflow arrange desk | Move and check the windows.] [replay {invented}]',True,[actual])
        self.assertTrue(saved)   # historical guidance may be kept, but it is not an executable shortcut
        self.assertNotIn('arrange desk',atticus.skills())

    def test_ai_shortcut_helper_defers_saving_until_verification(self):
        command=f'{atticus.SHOW} Editor'
        with patch.dict(os.environ,{'ATTICUS_ASK':str(Path(atticus.DIR)/'agent')}), \
             patch.object(sys,'argv',['atticus.py','--shortcut','focus time',command]),patch('sys.stdout',new_callable=io.StringIO) as output:
            atticus.main()
        self.assertEqual(atticus.skills(),{})
        self.assertIn('successful tool results',output.getvalue())
        # A user's direct CLI definition remains available without running its actions.
        with patch.dict(os.environ,{k:v for k,v in os.environ.items() if k!='ATTICUS_ASK'},clear=True), \
             patch.object(sys,'argv',['atticus.py','--shortcut','focus time',command]),patch('sys.stdout',new_callable=io.StringIO):
            atticus.main()
        self.assertEqual(atticus.skills()['focus time']['cmds'],[command])

    def test_correction_removes_procedure_even_with_different_wording(self):
        atticus.workflows('create calendar event', 'Use calendar form; verify event exists.')
        atticus.unlearn('make a new calendar event')
        self.assertEqual(atticus.workflows('create calendar event'), '')

    def test_settings_can_inspect_and_delete_saved_procedure(self):
        atticus.workflows('create calendar event', 'Fill calendar form; verify event exists.')
        with patch('sys.argv', ['atticus.py', '--state']), patch.object(atticus, 'plan', return_value={}), \
             patch.object(atticus, 'me', return_value={}), patch.object(atticus, 'MEMORY', str(Path(atticus.DIR) / 'memory.md')), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.main()
        row = json.loads(out.getvalue())['skills'][0]
        self.assertEqual(row['say'], 'create calendar event')
        self.assertIn('verify event', row['reply'])
        with patch('sys.argv', ['atticus.py', '--unlearn', row['say']]):
            atticus.main()
        self.assertEqual(atticus.workflows(), {})

    def test_full_request_saves_then_reuses_procedure_without_extra_model_call(self):
        brain = unittest.mock.Mock(return_value=(
            'Created it. [workflow create calendar event | Read calendar, fill current values, save; verify event exists.]', .001, []))
        brain.ok = True
        brain.cmds = brain.ran = [atticus.WEB + ' read', atticus.WEB + ' fill 2 title']
        brain.observed = []
        with patch.multiple(atticus, licensed=lambda: True, ping=lambda: None, fast=lambda _: None,
                            front=lambda: ('Notes', ''), osa=lambda *a: '', screens=lambda: [],
                            describe=lambda *a: '', me_line=lambda: '', selection_context=lambda: '',
                            relevant_rules=lambda _: '', recent=lambda: [], screen_for=lambda *a: None,
                            wait_commit=lambda: True, run=brain, remember_turn=lambda *a: None,
                            log_turn=lambda *a, **k: None, restore_focus=lambda *a: None), \
             patch.object(atticus.threading, 'Thread'), patch('sys.stdout', io.StringIO()):
            with patch('sys.argv', ['atticus.py', 'make a calendar event']):
                atticus.main()
            self.assertEqual(brain.call_count, 1)
            brain.return_value = ('Created it.', .001, [])
            with patch('sys.argv', ['atticus.py', 'create a new calendar event tomorrow']):
                atticus.main()
        self.assertEqual(brain.call_count, 2)
        self.assertIn('Saved workflow (historical guidance)', brain.call_args.args[0])
        self.assertIn('verify event exists', brain.call_args.args[0])

    def test_only_matching_procedure_enters_prompt_and_remember_waits_for_confirmation(self):
        atticus.workflows('create calendar event', 'a' * 2000)
        atticus.workflows('play jazz playlist', 'Read playlists; choose jazz; verify playing.')
        self.assertEqual(len(atticus.workflows('create calendar event').split('Procedure: ')[1]), 800)
        self.assertNotIn('jazz', atticus.workflows('create calendar event'))
        with patch.dict(os.environ, {'ATTICUS_LIVE': '1'}):
            self.assertIsNone(atticus.fast('remember how to create calendar event'))
        full = atticus.SYSTEM + atticus.ASK_ME + atticus.POINTER + atticus.LEARN_ME + atticus.TEACH + atticus.ASK_FIRST + atticus.WORKFLOW
        self.assertLessEqual(len(full), 10000)
        installed = os.path.expanduser("~/Applications/Atticus.app/Contents/Resources/atticus.py")
        self.assertLessEqual(len(full.replace(atticus.ME, installed)), 10000)

    def test_interrupted_shortcut_save_preserves_private_previous_file(self):
        saved={'original':{'mine':True,'cmds':['echo ok'],'reply':'Done.'}}
        Path(atticus.SKILLS).write_text(json.dumps(saved))
        with patch.object(atticus.json,'dump',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): atticus.save_skills({'new':{'mine':True}})
        self.assertEqual(atticus.skills(),saved)
        self.assertEqual(list(Path(atticus.DIR).iterdir()),[Path(atticus.SKILLS)])
        atticus.save_skills(saved)
        self.assertEqual(Path(atticus.SKILLS).stat().st_mode & 0o777,0o600)


if __name__ == '__main__':
    unittest.main()
