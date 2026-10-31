"""Source-only regressions for release repository wiring."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.evals import fake_mac
from tests.evals.scenarios import by_id, initial_state

ROOT = Path(__file__).resolve().parents[1]


class RepoFixTests(unittest.TestCase):
    def test_long_dry_eval_is_opt_in(self):
        source = (ROOT / 'tests/evals/test_dry.py').read_text()
        self.assertIn("ATTICUS_RUN_DRY_EVALS') == '1'", source)

    def test_chrome_native_test_keeps_host_and_vm_guards(self):
        source = (ROOT / 'tests/test_chrome_background_native.py').read_text()
        self.assertIn("os.environ.get('ATTICUS_VM') == '1' and sys.platform == 'darwin' and CHROME.exists()", source)

    def test_worksheet_effects_come_from_fixture_actions(self):
        state = initial_state(by_id('worksheet_browser'))
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'state.json'
            path.write_text(json.dumps(state))
            with patch.dict(os.environ, {'ATTICUS_EVAL_STATE': str(path)}):
                fake_mac._web_reply('click', '6', '', state)
                fake_mac._web_reply('fill', '5', '2', state)
            saved = json.loads(path.read_text())
        self.assertEqual(saved['pages']['p2']['controls'][4]['value'], '2')
        self.assertEqual(saved['effects'], ['read_page2', 'filled_q10'])

    def test_release_metadata_has_one_version_source(self):
        version = (ROOT / 'VERSION').read_text().strip()
        self.assertEqual(version, '1.5.5')
        major, minor, patch_version = map(int, version.split('.'))
        self.assertEqual(major * 1_000_000 + minor * 1_000 + patch_version, 1_005_005)
        build = (ROOT / 'build.sh').read_text()
        self.assertIn('VERSION=$(tr -d', build)
        self.assertIn('<string>$BUILD</string>', build)
        self.assertIn('<string>$VERSION</string>', build)
        self.assertIn('command -v python3', build)
        self.assertIn('Could not add Atticus to Login Items; opening it directly instead.', build)
        self.assertIn('open "$APP"', build)

    def test_nix_installs_its_packaged_source(self):
        source = (ROOT / 'flake.nix').read_text()
        self.assertIn('builtins.readFile ./VERSION', source)
        self.assertIn('exec bash "$src/build.sh"', source)
        self.assertNotIn('exec bash "$src/install.sh"', source)

    def test_nix_install_does_not_offer_the_git_updater(self):
        swift = (ROOT / 'Atticus.swift').read_text()
        settings = (ROOT / 'ui/settings.html').read_text()
        readme = (ROOT / 'README.md').read_text()
        self.assertIn('static let managedByNix = src.hasPrefix("/nix/store/")', swift)
        self.assertIn('if managedByNix { status = "Run nix profile upgrade or nix run again."; return }', swift)
        self.assertIn('CFBundleShortVersionString', swift[swift.index('static let version: String'):swift.index('static func check')])
        self.assertIn("'Updates are managed by Nix'", settings)
        self.assertIn("$('autoUpdateRow').hidden = $('checkUpdate').hidden = !!d.managedUpdates", settings)
        self.assertIn('Nix installations show this update path in Settings', readme)
        self.assertNotIn('keeps the writable clone Atticus uses for updates', readme)

    def test_onboarding_fixture_waits_for_state(self):
        source = (ROOT / 'tests/onboarding.html').read_text()
        self.assertIn('transition:none!important', source)
        self.assertEqual(source.count('await wait('), 1)  # only the polling helper yields

    def test_settings_shots_cover_current_pages_only(self):
        from tests.shoot_settings import PREFS, SCENES
        pages = {'dictation', 'general', 'intelligence', 'memory', 'meetings', 'usage', 'account', 'about', 'apps', 'feedback'}
        names = [name.split('-')[1] for name, _ in SCENES]
        self.assertTrue(set(names) <= pages, set(names) - pages)   # no removed page
        self.assertTrue(pages - {'apps', 'feedback'} <= set(names))   # every current page is shot
        self.assertFalse(set(PREFS) & {'longAsks', 'quietAudio', 'workIn', 'ahead', 'draftInsert'})

    def test_calendar_example_is_not_duplicated(self):
        readme = (ROOT / 'README.md').read_text()
        self.assertEqual(readme.count('Move my dentist appointment to 4.'), 1)
        self.assertIn('Adding is immediate; moving or deleting asks first.', readme)

    def test_meeting_bridge_has_one_worker_fixture(self):
        source = (ROOT / 'tests/test_meeting_bridge.py').read_text()
        self.assertEqual(source.count("(root / 'worker.py').write_text("), 1)


if __name__ == '__main__':
    unittest.main()
