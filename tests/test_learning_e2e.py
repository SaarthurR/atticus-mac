"""Say -> act -> learned -> say again -> instant replay, and opening apps and sites, through main() with a fake model and fake actions.
Never real apps, windows or paid calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import atticus
from tests import scratch_dir

PLACE_MANY, THREAD = atticus.place_many, threading.Thread
URL = 'https://board.example'
APPS = {'Safari', 'Obsidian', 'Mail', 'Fixture Board', 'Other Fixture'}


class NoThread:
    def __init__(self, *a, **kw): pass
    def start(self): pass
    def join(self, *a): pass


class Ask(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        self.show = Mock(side_effect=lambda target, bg=False: f'opened {target} ' + ('in the background' if bg else 'in front'))
        self.place = Mock(side_effect=lambda args: ' '.join(args) + ' window -> full of Laptop')
        self.shell = Mock(return_value=subprocess.CompletedProcess([], 0, '', ''))
        for p in [patch.object(atticus, 'SKILLS', str(self.root / 'skills.json')), patch.object(atticus, 'RECENT', str(self.root / 'recent.jsonl')),
                  patch.object(atticus, 'WORKED', str(self.root / 'worked.json')), patch.object(atticus, 'ME_FILE', str(self.root / 'me.json')),
                  patch.object(atticus, 'MEMORY', str(self.root / 'memory.md')), patch.object(atticus, 'LAST', str(self.root / 'last_app')),
                  patch.dict(os.environ, {'ATTICUS_ASK': str(self.root), 'ATTICUS_FRONT': 'Other Fixture', 'ATTICUS_FOCUS_GUARD': '1'}, clear=True),
                  patch.object(atticus.threading, 'Thread', NoThread), patch.object(atticus.subprocess, 'run', self.shell),
                  patch.multiple(atticus, show=self.show, place_many=self.place, place=lambda *a: 'Fixture window -> full of Laptop', installed_apps=lambda: set(APPS), proc_of=lambda a: a,
                                 app_id=lambda a: 'com.example.' + str(a).lower().replace(' ', ''), app_running=lambda bid: True,
                                 free_focus=lambda *a, **k: None, preview_commands=lambda *a, **k: None, preview_app=lambda *a, **k: None,
                                 licensed=lambda: True, ping=lambda: None, front=lambda: ('Other Fixture', 'Scratch'), osa=lambda *a, **k: '',
                                 screens=lambda: [], describe=lambda *a: 'Scratch display', selection_context=lambda: '', screen_for=lambda *a: None,
                                 tool_help=lambda *a, **k: '', wait_commit=lambda: True, restore_focus=lambda *a: None, look=lambda *a, **k: [],
                                 hands_map=lambda *a, **k: None, report=lambda *a: None, cached_hands=lambda: None, ask_user=lambda *a: '')]:
            p.start(); self.addCleanup(p.stop)

    def ask(self, words, reply='', cmds=(), ok=True):
        """One spoken ask. The fake model answers only if the instant path did not; returns (shown answer, Learned pill, model used)."""
        brain = Mock(return_value=(reply, 0, []))
        brain.ok, brain.modes, brain.cmds, brain.ran = ok, {'text'}, list(cmds), list(cmds)
        brain.observed = [{'action': c, 'error': False, 'result': 'done'} for c in cmds]
        say, tip = Mock(), Mock()
        with patch('sys.argv', ['atticus.py', words]), patch.multiple(atticus, run=brain, say=say, tip=tip):
            atticus.main()
        pills = [c.args[1] for c in tip.call_args_list if c.args[1]]
        return say.call_args.args[1], (pills[-1] if pills else ''), brain.called


class LearningEndToEndTests(Ask):
    def test_said_and_done_is_learned_and_close_wordings_replay_instantly(self):
        said, pill, model = self.ask('Open the fixture board site', 'Opened the fixture board.', [f'{atticus.SHOW} "{URL}"'])
        self.assertTrue(model)
        self.assertEqual(pill, 'Learned: Say “Open the fixture board site” any time.')
        for words in ('open the fixture board site', 'Hey Atticus, can you open the fixture board site please?', 'open fixture board site'):
            self.show.reset_mock()
            said, pill, model = self.ask(words)
            self.assertFalse(model, words)   # instant: no model
            self.assertEqual(said, 'Opened the fixture board.')
            self.show.assert_called_once_with(URL, False)

    def test_unpunctuated_when_i_say_saves_the_trigger_words_and_replays_them(self):
        # Oct 22: "when I say deep work full screen Chrome …" had no comma, so the whole sentence was saved and "deep work" never replayed
        cmds = [f'{atticus.SHOW} "{URL}"', f'{atticus.PLACE} "Fixture Board" left current']
        said, pill, model = self.ask('When I say board time open the fixture board site and put fixture board on the left', 'Done. [shortcut board time]', cmds)
        self.assertEqual(said, 'Done.')   # the tag is never shown
        self.assertEqual(set(atticus.skills()), {'board time'})   # never the teaching sentence itself
        self.assertTrue(atticus.skills()['board time']['mine'])
        self.assertEqual(pill, 'Learned: Say “board time” any time.')
        said, pill, model = self.ask('Board time.')
        self.assertFalse(model)
        self.assertEqual(said, 'Done.')
        self.show.assert_called_with(URL, False)
        self.place.assert_called_with(['Fixture Board', 'left', 'current'])

    def test_remember_wording_teaches_only_the_users_own_words(self):
        self.ask('Remember that when I say board time, open the fixture board site', 'Opened it. [shortcut board time]', [f'{atticus.SHOW} "{URL}"'])
        self.assertIn('board time', atticus.skills())
        self.assertFalse(self.ask('board time')[2])
        atticus.save_skills({})
        said, pill, model = self.ask('Open the fixture board site', 'Opened it. [shortcut study time]', [f'{atticus.SHOW} "{URL}"'])
        self.assertEqual(said, 'Opened it.')
        self.assertEqual(set(atticus.skills()), {'open the fixture board site'})   # "study time" was never said: not a trigger

    def test_named_shortcut_on_the_instant_path_replays_in_front(self):
        said, pill, model = self.ask('When I say browse time, open Safari')
        self.assertFalse(model)
        self.assertEqual(said, 'Opened Safari.')
        self.shell.assert_called_with(['open', '-a', 'Safari'])
        said, pill, model = self.ask('browse time')
        self.assertFalse(model)
        self.show.assert_called_once_with('Safari', False)   # in front, as asked; "browse time" itself says nothing about focus

    def test_failed_replay_unlearns_and_its_redo_is_learned_even_without_the_unlearn_tag(self):
        atticus.save_skills({'open the fixture board site': {'cmds': [f'{atticus.SHOW} "{URL}"'], 'reply': 'Opened.', 'mine': True}})
        self.show.side_effect = lambda target, bg=False: 'could not open ' + target
        fixed = f'{atticus.SHOW} "https://board.example/home"'
        said, pill, model = self.ask('Open fixture board site', 'Opened the board home.', [fixed])   # matched by its gist, not its exact key
        self.assertTrue(model)
        self.assertEqual(said, 'Opened the board home.')
        self.assertEqual(atticus.skills()['open the fixture board site']['cmds'], [fixed])
        self.assertEqual(pill, 'Learned: Say “open the fixture board site” any time.')
        self.show.side_effect = lambda target, bg=False: f'opened {target}'
        self.show.reset_mock()
        self.assertFalse(self.ask('open the fixture board site')[2])
        self.show.assert_called_once_with('https://board.example/home', False)

    def test_a_failed_replay_whose_redo_also_fails_is_never_replayed_again(self):
        atticus.save_skills({'open the fixture board site': {'cmds': [f'{atticus.SHOW} "{URL}"'], 'reply': 'Opened.', 'mine': True}})
        self.show.side_effect = lambda target, bg=False: 'could not open ' + target
        self.ask('open the fixture board site', 'I could not open it.', [], ok=False)
        self.assertEqual(atticus.skills(), {})
        self.show.reset_mock()
        self.assertTrue(self.ask('open the fixture board site', 'Still not.', [], ok=False)[2])   # the model again, no blind replay
        self.show.assert_not_called()

    def test_failure_after_the_first_step_does_not_save_only_the_redo(self):
        first, second = 'https://board.example/first', 'https://board.example/second'
        atticus.save_skills({'board setup': {'cmds': [f'{atticus.SHOW} "{first}"', f'{atticus.SHOW} "{second}"'],
                                              'reply': 'Board setup ready.', 'mine': True}})
        self.show.side_effect = lambda target, bg=False: ('could not open ' if target == second else 'opened ') + target
        redo = f'{atticus.SHOW} "https://board.example/recovered"'
        self.ask('board setup', 'Recovered the remaining step.', [redo])
        self.assertEqual(atticus.skills()['board setup']['cmds'], [f'{atticus.SHOW} "{first}"', f'{atticus.SHOW} "{second}"'])   # the user's own shortcut stays whole
        row = json.loads((self.root / 'log.jsonl').read_text().splitlines()[-1])
        self.assertTrue(any(first in step for step in row['ran']))
        self.assertTrue(any(second in step for step in row['ran']))
        self.assertIn(redo, row['ran'])

    def test_nothing_wrong_is_ever_replayed(self):
        # names the instant mover can't resolve, so the model arranged them and the layout was learned
        self.ask('alpha pane on the left and beta pane on the right', 'Arranged.', [f'{atticus.PLACE} "Alpha" left current + "Beta" right current'])
        self.assertIn('alpha pane on the left and beta pane on the right', atticus.skills())
        self.place.reset_mock()
        said, pill, model = self.ask('beta pane on the left and alpha pane on the right', 'Arranged the other way.')
        self.assertTrue(model)   # the same words in another order are another layout: never the learned one
        self.place.assert_not_called()
        self.assertFalse(self.ask('on the right beta pane and on the left alpha pane')[2])   # back to front, each pane keeps its side
        self.place.assert_called_once_with(['Alpha', 'left', 'current', '+', 'Beta', 'right', 'current'])
        mode = "osascript -e 'tell application \"System Events\" to tell appearance preferences to set dark mode to true'"
        self.ask('switch on dark mode', 'Dark mode is on.', [mode])
        self.assertFalse(self.ask('dark mode switch on')[2])   # only a word the commands never use moved: still instant
        before = atticus.skills()
        self.ask('Close this', 'Closed.', ["osascript -e 'tell application \"Other Fixture\" to close window 1'"])   # "this" depends on the moment
        self.ask('Hide fixture board', 'I could not hide it.', ["osascript -e 'tell application \"Fixture Board\" to set visible to false'"])
        self.ask('Hide other fixture', 'Hidden.', ["osascript -e 'tell application \"Other Fixture\" to set visible to false'"], ok=False)
        self.assertEqual(atticus.skills(), before)


class WorkModeTests(Ask):
    """Teach a two-display full screen layout by name, replay it with no model, re-teach it: the real place_many, fake windows."""
    def setUp(self):
        super().setUp()
        self.calls, self.active, self.most, self.fail = [], 0, 0, False
        lock, both = threading.Lock(), threading.Barrier(2, timeout=2)
        def place(app, where, screen, title=''):
            if where != 'fullscreen':
                if screen == 'current': both.wait()   # plain moves run at once: one alone would wait out the barrier
                self.calls.append((app, where, screen)); return f'{app} window -> {where} of {screen}'
            with lock: self.active += 1; self.most = max(self.most, self.active)
            time.sleep(.02)   # a Space animation; another one started meanwhile would overlap it
            with lock: self.active -= 1; self.calls.append((app, where, screen))
            return f'NOT DONE: {app} entered full screen on the wrong display.' if self.fail else f'{app} window -> fullscreen of {screen}'
        for p in (patch.multiple(atticus, place_many=PLACE_MANY, place=place),):
            p.start(); self.addCleanup(p.stop)

    def test_teach_replay_and_reteach_work_mode(self):
        (self.root / 'memory.md').write_text('- Work mode: Other Fixture full screen on the laptop, Fixture Board on the monitor.\n- Keep replies short.\n')
        stale = 'when i say work mode full screen other fixture on my laptop and fixture board on my monitor'
        atticus.save_skills({stale: {'cmds': [f'{atticus.PLACE} "Other Fixture" fullscreen laptop'], 'reply': 'Done.', 'at': '2099-01-01'}})
        said, pill, model = self.ask('No, when I say work mode, full screen Fixture Board on my laptop and full screen Other Fixture on my monitor.')
        self.assertFalse(model)
        self.assertEqual(said, 'Fixture Board: full screen on laptop; Other Fixture: full screen on monitor.')
        self.assertEqual(pill, 'Learned: Say “work mode” any time.')
        self.assertEqual(set(atticus.skills()), {'work mode'})   # the stale whole-sentence version is gone
        self.assertTrue(atticus.skills()['work mode']['mine'])
        self.assertEqual(atticus.memory_rules(), ['Keep replies short.'])   # so is the rule that described the old layout
        # each window reaches its display first, then they enter full screen one at a time
        self.assertEqual(self.calls, [('Fixture Board', 'full', 'laptop'), ('Other Fixture', 'full', 'monitor'),
                                      ('Fixture Board', 'fullscreen', 'laptop'), ('Other Fixture', 'fullscreen', 'monitor')])
        self.assertEqual(self.most, 1)
        self.calls.clear()
        said, pill, model = self.ask('Work mode.')
        self.assertFalse(model)
        self.assertEqual(said, 'Fixture Board: full screen on laptop; Other Fixture: full screen on monitor.')
        self.assertEqual(self.calls[2:], [('Fixture Board', 'fullscreen', 'laptop'), ('Other Fixture', 'fullscreen', 'monitor')])
        self.assertEqual(self.most, 1)
        self.ask('When I say work mode, full screen Other Fixture on my laptop and full screen Fixture Board on my monitor')
        self.calls.clear()
        self.ask('work mode')
        self.assertEqual(self.calls[2:], [('Other Fixture', 'fullscreen', 'laptop'), ('Fixture Board', 'fullscreen', 'monitor')])

    def test_plain_moves_stay_parallel(self):
        with patch.object(threading, 'Thread', THREAD): self.assertEqual(atticus.fast('Fixture Board left, Other Fixture right'), 'Fixture Board: left; Other Fixture: right.')

    def test_a_failed_replay_keeps_the_users_shortcut_when_the_redo_works(self):
        self.ask('When I say work mode, full screen Fixture Board on my laptop and full screen Other Fixture on my monitor')
        taught = atticus.skills()['work mode']
        self.fail = True
        checks = "osascript -e 'tell application \"System Events\" to get value of attribute \"AXFullScreen\" of window 1' 2>&1; echo ---"
        said, pill, model = self.ask('Work mode.', 'Both are full screen now.', [f'{atticus.PLACE} "Fixture Board" fullscreen laptop', checks])
        self.assertTrue(model)
        self.assertEqual(atticus.skills()['work mode']['cmds'], taught['cmds'])   # the redo could not be learned: what the user taught stays


class OpenAppsAndSitesTests(Ask):
    """Opening is instant where the words are a plain open; anything else goes to the model, which must really open it."""
    def test_open_apps_and_sites_instantly(self):
        for words, app in (('open Safari', 'Safari'), ('Open Obsidian.', 'Obsidian'), ('open Ascidian', 'Obsidian'), ('open the obsidion app', 'Obsidian')):
            self.shell.reset_mock()
            said, pill, model = self.ask(words)
            self.assertFalse(model, words)
            self.assertEqual(said, f'Opened {app}.')
            self.shell.assert_called_once_with(['open', '-a', app])
        self.shell.reset_mock()
        said, pill, model = self.ask('Open nike.com.')
        self.assertFalse(model)
        self.assertEqual(said, 'Opened nike.com.')
        self.shell.assert_called_once_with(['open', 'https://nike.com'])

    def test_a_near_name_that_is_not_an_app_goes_to_the_model(self):
        said, pill, model = self.ask('open gmail', 'Opened Gmail.', [f'{atticus.SHOW} "https://mail.google.com"'])
        self.assertTrue(model)   # one letter from Mail, but another first sound: never opens Mail
        self.assertNotIn(['open', '-a', 'Mail'], [c.args[0] for c in self.shell.call_args_list])
        self.assertIsNone(atticus.app_heard('open my homework folder now'))

    def test_non_english_open_goes_to_the_model_then_replays_instantly_in_front(self):
        words = 'Kannst du bitte einmal Safari öffnen'
        said, pill, model = self.ask(words, 'Safari ist offen.', [f'{atticus.SHOW} "Safari"'])
        self.assertTrue(model)
        self.assertEqual(said, 'Safari ist offen.')
        self.show.reset_mock()
        said, pill, model = self.ask(words)
        self.assertFalse(model)
        self.assertEqual(said, 'Safari ist offen.')
        self.show.assert_called_once_with('Safari', False)   # front, as the model opened it; the focus words are English-only


if __name__ == '__main__':
    unittest.main()
