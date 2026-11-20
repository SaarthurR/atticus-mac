"""Window commands replay against fake apps and placement, with no desktop actions.
Optional old/new replay: git show 8fe3da9:atticus.py > tests/_split_base.py.
"""
import os
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import atticus
from tests import scratch_dir


def receipt(proc, where, screen='current', title=''):
    return f'{proc} window -> {where} of Built-in'


class SplitTests(unittest.TestCase):
    def test_receipts_are_checked(self):
        self.assertFalse(atticus.place_failed(receipt('Fixture', 'left')))
        self.assertTrue(atticus.place_failed('placed'))
        self.assertTrue(atticus.place_failed(receipt('Fixture', 'left') + '\nplaced'))

    def test_review_replay(self):
        root = scratch_dir(self)
        apps = {'Google Chrome', 'Terminal', 'Safari', 'Notes', 'Mail', 'Obsidian', 'Focus', 'Tor Browser', 'Arc Browser', 'Tor'}
        sentences = [
            'Open the Chrome browser on the left and the terminal window on the right',
            'open the Safari browser on the right and the Notes app on the left',
            'work mode', 'full screen Chrome', 'put Notes on the right', "what's on my monitor",
            'open Chrome on the left', 'open Notes and Safari', 'open the Terminal window',
            'close the Safari browser', 'quit the Chrome browser',
            'open Tor Browser', 'quit Tor Browser', 'close Arc Browser',
            'put Tor Browser on the left', 'open Arc Browser on the right',
        ]
        for app in ('Chrome', 'Safari', 'Notes', 'Mail', 'Obsidian', 'Focus', 'Tor Browser', 'Arc Browser'):
            sentences += [f'open {app}', f'open {app} on the left', f'put {app} on the left',
                          f'open the {app} window', f'open {app} and Notes',
                          f'open {app} on the left and Terminal on the right',
                          f'what is in {app} on the left', f'read {app} on the right',
                          f'is {app} on the left and Terminal on the right',
                          f'{app} left, Terminal right']
        verbs = ('open', 'open up', 'launch', 'start', 'pull up', 'bring up', 'focus', 'focus on', 'switch to', 'go to')
        sentences += [f'{verb} the Mail app on the left and Terminal on the right' for verb in verbs]
        sentences = list(dict.fromkeys(sentences))
        modules = [atticus]
        base = Path(__file__).with_name('_split_base.py')
        if base.exists():
            spec = importlib.util.spec_from_file_location('split_base', base)
            old = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(old)
            modules.insert(0, old)
        results = []
        for module in modules:
            rows = {}
            with patch.dict(os.environ, {'ATTICUS_LIVE': '0'}), \
                 patch.multiple(module, LAST=str(root / 'last'), installed_apps=lambda: apps,
                                SHOW=atticus.SHOW, PLACE=atticus.PLACE,
                                skills=lambda: {}, fast_hands=lambda _: None, place=receipt,
                                place_many=lambda args: '\n'.join(receipt(*m.split('\0')) for m in '\0'.join(args).split('\0+\0')),
                                pref=lambda key, default=None: default, free_focus=lambda **k: None,
                                show=lambda *a, **k: 'opened fixture', osa=lambda *a, **k: '',
                                app_id=lambda app: 'fixture.' + app, quit_app=lambda bid: True), \
                 patch.object(module.subprocess, 'run', return_value=module.subprocess.CompletedProcess([], 0)) as shell:
                for sentence in sentences:
                    shell.reset_mock()
                    result = module.fast(sentence)
                    rows[sentence] = (result, module.fast.cmds[:], shell.call_args_list[:])
            results.append(rows)
        if len(results) == 2:
            for sentence in sentences:
                if results[0][sentence] != results[1][sentence]:
                    print(f'DELTA {sentence!r}: {results[0][sentence]!r} -> {results[1][sentence]!r}', flush=True)
                    self.assertTrue(sentence in sentences[:2] or sentence in ('close the Safari browser', 'quit the Chrome browser', 'Focus left, Terminal right')
                                    or sentence.endswith('on the left and Terminal on the right'), sentence)
            print(f'REVIEW compared {len(sentences)} sentences', flush=True)
        rows = results[-1]
        self.assertEqual(rows['open Tor Browser'][0], 'Opened Tor Browser.')
        self.assertEqual(rows['quit Tor Browser'][0], 'Closed Tor Browser.')
        self.assertIn('fixture.Tor Browser', rows['quit Tor Browser'][1][0])
        self.assertEqual(rows['close Arc Browser'][0], 'Closed Arc Browser.')
        self.assertEqual(rows['Focus left, Terminal right'][0], 'Focus: left; Terminal: right.')
        self.assertEqual(rows['put Focus on the left'][0], 'Focus: left.')
        self.assertEqual(rows['put Tor Browser on the left'][0], 'Tor Browser: left.')
        self.assertEqual(rows['close the Safari browser'][0], 'Closed Safari.')
        self.assertEqual(rows['quit the Chrome browser'][0], 'Closed Google Chrome.')
        self.assertEqual(rows['open Chrome on the left'][2][0].args[0], ['open', '-a', 'Google Chrome'])
        self.assertIsNone(rows['open Notes and Safari'][0])
        self.assertIsNone(rows['open the Terminal window'][0])
        for verb in verbs:
            self.assertEqual(rows[f'{verb} the Mail app on the left and Terminal on the right'][0], 'Mail: left; Terminal: right.')
        with patch.object(atticus, 'installed_apps', return_value={'Tor Browser', 'Arc Browser', 'Fixture Alpha Browser'}):
            self.assertEqual(atticus.app_named('the Tor Browser'), 'Tor Browser')
            self.assertEqual(atticus.app_named('the Arc Browser app'), 'Arc Browser')
            self.assertEqual(atticus.app_named('fa browser'), 'Fixture Alpha Browser')
            self.assertIsNone(atticus.app_named('browser'))
        with patch.object(atticus, 'installed_apps', return_value={'Fixture', 'Fixture Window'}):
            self.assertEqual(atticus.move_target('put fixture window on the left'), ('Fixture Window', 'left', 'current'))
        for sentence, (result, _, _) in rows.items():
            if sentence.startswith(('what ', 'read ', 'is ')):
                self.assertIsNone(result, sentence)

    def test_fast_replay(self):
        root = scratch_dir(self)
        cases = [
            ('Open the Chrome browser on the left and the terminal window on the right', 'Google Chrome: left; Terminal: right.'),
            ('open the Safari browser on the right and the Notes app on the left', 'Safari: right; Notes: left.'),
            ('Chrome left, Terminal right', 'Google Chrome: left; Terminal: right.'),
            ('work mode', None),
            ('full screen Chrome', 'Google Chrome: full screen.'),
            ('put Notes on the right', 'Notes: right.'),
            ("what's on my monitor", None),
            ('what is in the Chrome browser on the left', None),
            ('read the Notes window on the right', None),
            ('is Safari on the left and Notes on the right', None),
            ('open the Safari browser and read the Notes app on the left', None),
            ('the Chrome browser and the Terminal window', None),
        ]
        with patch.dict(os.environ, {'ATTICUS_LIVE': '0'}), \
             patch.multiple(atticus, LAST=str(root / 'last'),
                            installed_apps=lambda: {'Google Chrome', 'Terminal', 'Safari', 'Notes'},
                            skills=lambda: {}, fast_hands=lambda _: None, place=receipt,
                            place_many=lambda args: '\n'.join(receipt(*m.split('\0')) for m in '\0'.join(args).split('\0+\0')),
                            show=lambda *a, **k: 'opened fixture', osa=lambda *a, **k: ''), \
             patch.object(atticus.subprocess, 'run') as shell:
            for sentence, expected in cases:
                with self.subTest(sentence=sentence):
                    shell.reset_mock()
                    result = atticus.fast(sentence)
                    print(f'REPLAY {sentence!r} -> {result!r}; commands={atticus.fast.cmds!r}', flush=True)
                    self.assertEqual(result, expected)
                    self.assertFalse([c for c in shell.call_args_list if c.args and c.args[0][:1] == ['open']])
                    if expected is None:
                        self.assertEqual(atticus.fast.cmds, [])
