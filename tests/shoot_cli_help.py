"""Opt-in VM WebKit screenshots: a running step names the user's own tool instead of "Working on it"."""
import json
import unittest
from unittest.mock import patch

import atticus
from tests import shoot_boxlook


class OpenBimLook(unittest.TestCase):
    def test_running_step_light_and_dark(self):
        with patch.object(atticus.shutil, 'which', side_effect=lambda w: '/Users/fixture/.local/bin/' + w if w == 'mathsite' else None):
            step = atticus.label('Bash', {'command': 'mathsite --help'})   # Nov 16: no description, the user's own CLI
        self.assertEqual(step, 'Running mathsite')
        old, old_swift = shoot_boxlook.SCENES, shoot_boxlook.SWIFT
        shoot_boxlook.SWIFT = old_swift.replace('panel.level = .floating', 'panel.level = .screenSaver')
        shoot_boxlook.SCENES = []
        for look in ('light', 'dark'):
            script = ("ui.listen();ui.words('open mathsite, my homework site in chrome');ui.think();ui.line('· Waiting for the answer…');"
                      f"ui.line({json.dumps('▸ ' + step)});")
            check = ("[...document.querySelectorAll('.step')].some(e => e.textContent === 'Running mathsite') && "
                     "!document.body.textContent.includes('Working on it') ? 'ok step names the tool' : 'bad step'")
            shoot_boxlook.SCENES.append(('clihelp-' + look, look, script, check))
        try:
            shoot_boxlook.BoxLook.run_box(self, 'shots', 'box shots ok')
        finally:
            shoot_boxlook.SCENES, shoot_boxlook.SWIFT = old, old_swift
