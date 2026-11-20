"""Nov 16 "open mathsite, my homework site in chrome": a named CLI's --help ran its real work and the box sat on "Working on it"."""
import io
import json
import os
from pathlib import Path
import shlex
import time
import unittest
from unittest.mock import Mock, patch

import atticus
from tests import scratch_dir

# A personal script that treats --help as a command (it fell through to a web scrape) and leaves a child running.
BUSY = '#!/bin/sh\nsleep 30 &\necho $! > "$0.child"\nsleep 30\n'


class OpenNamedThingTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        self.bin = self.root / 'bin'; self.bin.mkdir()
        self.addCleanup(atticus.TURN.clear)

    def tool(self, name, body):
        path = self.bin / name
        path.write_text(body); path.chmod(0o755)
        return str(path)

    def test_help_that_starts_real_work_stops_with_its_children(self):
        for name in ('fixturecli', 'notes-sync'):   # any CLI, not one name
            with self.subTest(name=name):
                path = self.tool(name, BUSY)
                started = time.monotonic()
                self.assertEqual(atticus.cli_help(path), '')
                self.assertLess(time.monotonic() - started, 4)
                child = int(Path(path + '.child').read_text())
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    try: os.kill(child, 0)
                    except ProcessLookupError: break
                    time.sleep(.05)
                else: self.fail(f'{name} --help left its child running')

    def test_help_text_is_read_and_unknown_names_are_not_run(self):
        self.tool('fixturecli', '#!/bin/sh\necho "usage: fixturecli p <page>  open a page"\n')
        self.tool('silentcli', BUSY)
        with patch.dict(os.environ, {'PATH': f'{self.bin}:/usr/bin:/bin'}):
            got = atticus.installed_help(['fixturecli'])
            self.assertIn('usage: fixturecli p <page>', got)
            self.assertIn('untrusted data', got)
            self.assertEqual(atticus.installed_help(['silentcli']), '`silentcli --help` printed no help within 2 s.')
            self.assertEqual(atticus.installed_help(['nope-cli']), 'No installed CLI named nope-cli.')
            self.assertEqual(atticus.installed_help(['fixturecli', ';rm']), 'No installed CLI named fixturecli.')

    def test_unused_cli_is_advertised_through_the_bounded_reader(self):
        with patch.object(atticus.shutil, 'which', side_effect=lambda w: '/opt/fixture/' + w if w == 'mathsite' else None), \
             patch.object(atticus, 'ran_programs', return_value=set()), patch.object(atticus, 'cli_help') as read:
            got = atticus.tool_help('open mathsite, my homework site in chrome')
        read.assert_not_called()   # never run on a word alone
        self.assertIn(f'{atticus.CLI_HELP} <name> [subcommand]): mathsite', got)
        self.assertNotIn('run `<name> --help`', got)
        self.assertFalse(atticus.agent_read_command(f'{atticus.CLI_HELP} mathsite'))   # it runs their program: agents still ask first
        self.assertEqual(atticus.risky(f'{atticus.CLI_HELP} orca terminal send'), '')

    def test_step_says_what_it_runs(self):
        me = shlex.quote(atticus.ME)
        with patch.object(atticus.shutil, 'which', side_effect=lambda w: '/opt/fixture/' + os.path.basename(w) if 'fixturecli' in w else None):
            self.assertEqual(atticus.label('Bash', {'command': 'fixturecli --help'}), 'Running fixturecli')
            self.assertEqual(atticus.label('Bash', {'command': 'cd /tmp && LANG=C /opt/fixture/fixturecli sync'}), 'Running fixturecli')
            self.assertEqual(atticus.label('Bash', {'command': 'fixturecli sync', 'description': 'Sync the notes'}), 'Sync the notes')
            self.assertEqual(atticus.label('Bash', {'command': f'{atticus.CLI_HELP} fixturecli'}), 'Reading fixturecli’s help')
            self.assertEqual(atticus.label('Bash', {'command': f'{me} --me find "math site"'}), 'Working on it')
            self.assertEqual(atticus.label('Bash', {'command': 'for x in 1; do :; done'}), 'Working on it')
        self.assertEqual(atticus.label('Bash', {'command': 'sqlite3 History "select url from urls"'}), 'Working on it')   # /usr/bin: no shell jargon

    def test_fake_client_tool_step_names_the_program_while_it_runs(self):
        lines = [{'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {'command': 'fixturecli --help'}}]}},
                 {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 't1', 'content': 'usage'}]}},
                 {'type': 'result', 'result': 'Opened it.', 'total_cost_usd': 0}]
        p = Mock(ask='', returncode=0, stdin=io.StringIO(), errors=io.StringIO(), relay_thread=None)
        p.stdout = [json.dumps(line) for line in lines]
        atticus.begin_turn('open fixturecli, my homework site in chrome')
        with patch.object(atticus.shutil, 'which', side_effect=lambda w: '/opt/fixture/fixturecli' if w == 'fixturecli' else None), \
             patch.object(atticus, 'say') as say, patch.object(atticus, 'preview_commands'):
            reply, _, steps = atticus.run('Request: open fixturecli', p)
        self.assertEqual((reply, steps), ('Opened it.', ['Running fixturecli']))
        self.assertIn(('▸', 'Running fixturecli'), [c.args for c in say.call_args_list])
        self.assertEqual(atticus.TURN['step_times'][-1]['label'], 'Running fixturecli')

    def test_in_flight_rows_carry_the_routed_model(self):
        prefs = {'routing': 'balanced', 'model': 'sonnet'}
        seen = {}
        def brain(*a, **k):
            seen['model'] = atticus.TURN['model']
            seen['logged'] = [json.loads(l).get('model') for l in (self.root / 'log.jsonl').read_text().splitlines()]
            return 'Opened it.', 0, []
        brain = Mock(side_effect=brain); brain.ok = True; brain.cmds = brain.ran = []; brain.observed = []
        class NoThread:
            def __init__(self, *a, **kw): pass
            def start(self): pass
            def join(self, *a): pass
        with patch.object(atticus.threading, 'Thread', NoThread), patch('sys.argv', ['atticus.py', 'open mathsite, my homework site in chrome']), \
             patch.dict(os.environ, {'ATTICUS_ASK': str(self.root), 'ATTICUS_FRONT': 'Fixture'}), \
             patch.multiple(atticus, pref=lambda k, d: prefs.get(k, d), licensed=lambda: True, ping=lambda: None, fast=lambda _: None,
                            front=lambda: ('Fixture', 'Scratch'), osa=lambda *a: '', screens=lambda: [], describe=lambda *a: 'Scratch display',
                            selection_context=lambda: '', screen_for=lambda *a: None, tool_help=lambda *a, **k: '', run=brain,
                            start_ai=lambda *a, **k: None, wait_commit=lambda: True, restore_focus=lambda *a: None, say=Mock(),
                            tip=lambda *a: None, look=lambda *a, **k: [], hands_map=lambda *a: None):
            atticus.main()
        self.assertEqual(seen['model'], 'sonnet')
        self.assertEqual(seen['logged'][-1], 'sonnet')   # a cancelled ask's last row is this one


if __name__ == '__main__':
    unittest.main()
