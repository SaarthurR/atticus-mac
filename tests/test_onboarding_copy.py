"""Setup (ui/onboarding.html) shows the app as it is today. Source checks only: no window, app or WebKit."""
from pathlib import Path
import re
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OnboardingMatchesAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / 'ui/onboarding.html').read_text()

    def test_skip_setup_jumps_to_the_optional_pages(self):
        self.assertIn('id="skip">Skip Setup</button>', self.page)
        self.assertIn("['improve', 'tip', 'done'].includes(cur) ? post({ do: 'done' }) : go('improve')", self.page)   # improve, tip and done still show; done says what is missing
        self.assertIn("$('skip').hidden = false;", self.page)
        self.assertIn("cur === 'done' ? post({ do: 'done' })", self.page)
        swift = (ROOT / 'Atticus.swift').read_text()
        self.assertIn('if b["do"] == "done" { return finish() }', swift)
        finish = swift.split('    func finish() {', 1)[1].split('    func windowWillClose', 1)[0]
        self.assertIn('set(true, forKey: "onboarded")', finish)
        self.assertIn('win?.close()', finish)
        self.assertIn('if relaunch { relaunchSoon() }', finish)

    def test_setup_order_and_optional_consent(self):
        self.assertEqual(re.findall(r'<section class="page" id="(\w+)"', self.page), ['welcome', 'ai', 'model', 'perms', 'try', 'dictate', 'show', 'improve', 'tip', 'done'])
        self.assertIn("const pages = ['welcome', 'ai', 'model', 'perms', 'try', 'dictate', 'show', 'improve', 'tip', 'done'];", self.page)
        self.assertNotIn('data-k="improve"', self.page)
        self.assertIn("post({ do: 'set', k: 'improve', v: String(value) })", self.page)
        self.assertIn('"dictateHotkeyLabel": Prefs.str("dictateHotkeyLabel")', (ROOT / 'Atticus.swift').read_text())
        handler = (ROOT / 'Atticus.swift').read_text().split('if b["do"] == "set" {', 1)[1].split('            return\n        }', 1)[0]
        self.assertIn('if b["k"] == "improve" { Atticus.settings.apply("improve", b["v"] == "true")', handler)   # setup sets only failure reports and the work model
        self.assertIn('if b["k"] == "model", let v = b["v"], ["sonnet", "opus"].contains(v) { Atticus.settings.apply("model", v)', handler)
        self.assertEqual(handler.count('Atticus.settings.apply('), 2)

    def test_welcome_uses_original_shortcut_gesture_and_only_system_events_is_asked_in_setup(self):
        self.assertIn('id="welcome-talk">Hold the shortcut, speak, release to send.', self.page)
        self.assertIn('id="welkeys"', self.page)
        self.assertIn('id="start">Get Started', self.page)
        self.assertIn("['auto', 'System Events', 'Controls your apps for you.'", self.page)   # System Events is asked here; other apps when first used
        self.assertIn('"auto": "automation"][b["id"] ?? ""]', (ROOT / 'Atticus.swift').read_text())
        self.assertIn('request(need, app: need == "automation" ? "System Events" : "", settingsOnRefusal: true,', (ROOT / 'Atticus.swift').read_text())
        self.assertIn('P.every(([k]) => last[k])', self.page)
        swift = (ROOT / 'Atticus.swift').read_text()
        self.assertIn('AEDeterminePermissionToAutomateTarget(&d, typeWildCard, typeWildCard, ask)', swift)
        self.assertIn('check(id, ask: true)', swift)
        self.assertIn('Apps.allow([id]) { _, s in granted = s == "allowed" }', swift)   # opens a closed app hidden so macOS can ask

    def test_restored_copy_is_translated_in_every_language(self):
        source = (ROOT / 'ui/i18n.js').read_text()
        maps = json.loads(source.split('  const maps = ')[1].split(';\n  let language')[0])
        strings = ['Get Started', 'Optional', 'Help make Atticus better', 'Only what failed', 'Anonymous', 'Cleaned first',
                   'Not Now', 'Help Improve', 'Atticus is free and open source', 'Leave a Tip', 'Next',
                   'Set up Mac access', 'Screen & System Audio Recording', 'Mac access is ready.',
                   'Dictation practice', 'Try dictating here', 'Automatically minimize the box',
                   'Go use Atticus.', 'Be great.', 'Start Using Atticus', 'Report feedback ↗',
                   'Hold the shortcut anywhere.', 'Press the shortcut anywhere.', 'AI is ready',
                   'Press the shortcut, speak, press again to send. Your Mac does the rest.', '“Convert this JPEG to PNG”',
                   'Allow Atticus to hear you, see your screen and control your Mac.', 'Hears you while you hold the shortcut.', 'Turns your words into text.', 'Controls your apps for you.',
                   'Try', '“Hey Atticus, what’s up?”', 'Show me how', 'Hold the shortcut, circle something with your mouse, and ask.', 'What is this?', 'A flat white, with a latte-art heart on top.',
                   'When a task fails, Atticus can tell its maker what went wrong, so the next version gets it right.', 'You can change this anytime.',
                   'What you asked, the steps Atticus took, and why it didn’t work.', 'A random ID. Never your name, your screen, your files or passwords.',
                   'Emails, numbers, file paths and anything typed for you are removed before it leaves your Mac.',
                   'Pick a work model', 'Atticus uses it for bigger asks.', 'Asked', '“Teach me the Pythagorean theorem.”',
                   'Quick, clear answers.', 'More detail, more steps.', 'Lighter on your plan', 'About 2× more of your plan',
                   'The two small squares add up to the big one.', '✎ Draws the triangle', '✎ Draws all three squares',
                   '9 + 16 = 25: the squares on the short sides fill the one on the long side.']
        for language, translations in maps.items():
            for text in strings:
                self.assertTrue(translations.get(text), f'{language}: {text}')

    def test_show_me_how_is_built_from_the_real_box_and_trail(self):
        box, swift = (ROOT / 'ui/ui.html').read_text(), (ROOT / 'Atticus.swift').read_text()
        for value in ('padding: 14px 20px 18px', 'height: 44px', 'font-size: 12.5px; line-height: 22px', 'padding: 9px 14px; border-radius: 16px 16px 5px 16px',
                      'font-size: 13.5px; line-height: 1.45', 'font-size: 15px; line-height: 1.6', 'opacity: 0; transform: translateY(5px)'):
            self.assertIn(value, box); self.assertIn(value, self.page)   # the loop's box keeps the box's own sizes
        self.assertIn('NSColor(calibratedRed:18/255,green:18/255,blue:20/255,alpha:0.85)', swift); self.assertIn('background: rgba(var(--gray-7-rgb),.85)', self.page)
        self.assertIn('--gray-7-rgb: 18,18,20;', (ROOT / 'ui/tokens.css').read_text())
        self.assertIn('cornerRadius = 18', swift); self.assertIn('width: 340px; border-radius: 18px', self.page)
        self.assertIn('edges = strokes(.black,contrast ? 0.6 : 0.3,contrast ? 8.5 : 7.5)\n        bands = strokes(.white,0.95,6)', swift)
        self.assertIn("[['0,0,0', .3, 7.5], ['255,255,255', .95, 6]]", self.page)   # TalkPen's edge and ink
        self.assertIn('tail = 0.9*(1-settled*settled*(3-2*settled))', swift); self.assertIn('tail = .9 * (1 - settled * settled * (3 - 2 * settled))', self.page)
        self.assertIn('if let arrow = arrowCursorScript() { cfg.userContentController.addUserScript(arrow) }', swift)   # the system arrow, not a drawing of one

    def test_read_aloud_defaults_on_and_preserves_saved_choices(self):
        from tests import run_swift
        source = (ROOT / 'Atticus.swift').read_text()
        prefs = source[source.index('enum Prefs {'):source.index('// Only an explicit language choice')]
        for choice in (None, False, True):
            with tempfile.TemporaryDirectory() as folder:
                if choice is not None:
                    Path(folder, 'settings.json').write_text(json.dumps({'speak': choice}))
                prefix = 'import Cocoa\nimport Carbon\nsetenv("ATTICUS_DIR", ' + json.dumps(folder) + ', 1)\n'
                run_swift(self, prefix + prefs + '\nprecondition(Prefs.bool("speak") == ' + str(choice is not False).lower() + ')')

    def test_automation_denial_points_the_ask_at_the_permission_card(self):
        import atticus
        from unittest.mock import patch
        denied = 'execution error: Not authorized to send Apple events to Spotify. (-1743)'
        with patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', denied)) as run, \
             patch.object(atticus.sys, 'stderr', new_callable=io.StringIO) as err:
            self.assertEqual(atticus.osa('fixture script'), '')
        run.assert_called_once()   # a refused, possibly changing Apple event is never replayed
        self.assertIn('Apple events to Spotify', err.getvalue())   # the tool output names the app for the hook
        with patch.dict(os.environ):
            os.environ.pop('ATTICUS_ASK', None)
            hint = atticus.automation_hint({'hook_event_name': 'PostToolUse', 'tool_response': {'stdout': '', 'stderr': denied}})
            self.assertIn('--need automation', hint)
            self.assertIn('--need automation "To control Spotify for this task." Spotify and', hint)
            self.assertIn(' Spotify and', atticus.automation_hint({'tool_response': 'Could not control Spotify: macOS denied Automation permission.'}))
            self.assertEqual(atticus.automation_hint({'tool_response': {'stdout': 'Opened Notes.'}}), '')
        out = subprocess.run(['/bin/sh', str(ROOT / 'atticus.py'), '--step-result'], input=json.dumps({'hook_event_name': 'PostToolUseFailure', 'tool_name': 'Bash',
                             'tool_input': {'command': 'osascript -e x'}, 'error': denied}), capture_output=True, text=True, timeout=30,
                             env={k: v for k, v in os.environ.items() if k != 'ATTICUS_ASK'})
        self.assertEqual(json.loads(out.stdout)['hookSpecificOutput']['hookEventName'], 'PostToolUseFailure', out.stderr)
        with tempfile.TemporaryDirectory() as ask, patch.dict(os.environ, {'ATTICUS_ASK': ask}):
            event = {'tool_response': {'stderr': denied}}
            self.assertIn('--need automation', atticus.automation_hint(event))
            again = atticus.automation_hint(event)   # after "Not now", the next refusal in the same ask
            self.assertNotIn('--need', again)
            self.assertIn('Do not ask again', again)
            self.assertIn('--need automation', atticus.automation_hint({'tool_response': {'stderr': denied.replace('Spotify', 'Notes')}}))

    def test_setup_chrome_row_shows_a_refused_automation_switch(self):
        chrome = (ROOT / 'Atticus.swift').read_text().split('case "chrome":   // verifies page scripting')[1].split('default: break')[0]
        self.assertIn('Apps.check($0.0, ask: false) == OSStatus(errAEEventNotPermitted)', chrome)
        self.assertIn('self.settings("Automation", point: app)', chrome)

    def test_try_it_follows_the_box(self):
        swift = (ROOT / 'Atticus.swift').read_text()
        js = swift.split('    func js(_ call: String, _ arg: Any? = nil) {', 1)[1].split('\n    }', 1)[0]
        self.assertIn('callJS(web, "ui." + call', js)
        self.assertIn('if onboarding.win != nil { callJS(onboarding.web, "ob.app", [call]', js)   # only while setup is open
        app = self.page.split('    app(call, v) {', 1)[1].split('\n    },', 1)[0]
        for call in ("'listen'", "'words'", "'think'", "'line'", "'finished'", "'msg'", "'stopped'"):
            self.assertIn(call, app)
        self.assertIn("if (cur !== 'try') return;", app)
        self.assertIn('onboarding.tried()', swift)   # the shortcut itself still turns the keys green

    def test_steps_move_on_only_when_finished_here(self):
        ahead = self.page.split('  const autoAhead = ', 1)[1].split('\n  };', 1)[0]
        self.assertIn('arrivedReady', ahead)   # already done on arrival: no jump
        self.assertIn("autoAhead('perms', 1300)", self.page)
        self.assertIn("autoAhead('ai', 1600)", self.page)
        self.assertIn("arrivedReady === null) arrivedReady = ready(id);", ahead)   # a status that lands after you is how you found it

    def test_privacy_help_drags_a_bundle_and_cleans_up(self):
        swift = (ROOT / 'Atticus.swift').read_text()
        helper = swift.split('final class PermissionIcon:', 1)[1].split('// `Atticus --look', 1)[0]
        self.assertIn('NSDraggingItem(pasteboardWriter: Bundle.main.bundleURL as NSURL)', helper)
        self.assertIn('beginDraggingSession(with: [item], event: event, source: self)', helper)
        self.assertIn('if self.panel === w, allowed { self.close("permission on") }', helper)
        self.assertIn('if seen { close("System Settings quit") }', helper)
        self.assertNotIn('timeIntervalSince', helper)   # a slow Settings launch or consent prompt must not lose the helper
        self.assertLess(helper.index('let allowed = granted()'), helper.index('guard let frame'))
        self.assertIn('timer?.invalidate(); timer = nil; panel = nil\n    }', helper)
        self.assertIn('styleMask: [.titled, .closable, .nonactivatingPanel]', helper)
        # Nov 18, his rule: Accessibility and Screen Recording always offer the icon, even when Atticus is already listed
        self.assertIn('drag: ["Accessibility", "ScreenCapture"].contains(p), listed: prompted.contains(p)', swift)
        self.assertNotIn('fill(w, drag: false)', helper)
        for pane in ('Accessibility', 'ScreenCapture', 'Microphone', 'SpeechRecognition', 'Calendars', 'Automation'):
            self.assertIn('"' + pane + '": ', swift)
        self.assertIn('case "automation": onboarding.settings("Automation")', swift)

    def test_setup_is_a_regular_app_while_open(self):
        # Nov 18: after Allow on the Microphone and Speech popups, macOS gave focus to System Settings, the last regular app
        swift = (ROOT / 'Atticus.swift').read_text()
        onboarding = swift.split('final class Onboarding:', 1)[1].split('final class PermissionIcon:', 1)[0]
        opened = onboarding[onboarding.index('win = w; web = v'):]
        self.assertLess(opened.index('NSApp.setActivationPolicy(.regular)'), opened.index('NSApp.activate(ignoringOtherApps: true)'))
        closing = onboarding[onboarding.index('    func windowWillClose(_ n: Notification) {'):]
        self.assertIn('NSApp.setActivationPolicy(.accessory)', closing[:closing.index('\n    }\n')])

    @unittest.skipUnless(shutil.which('node'), 'node runs the keycap split')
    def test_talk_keys_follow_the_configured_shortcut(self):
        caps = re.search(r'  const capsOf = .*\n', self.page).group(0)
        script = caps + '''
const want = {'⌃⌥Space': ['⌃', '⌥', 'Space'], 'fn': ['fn'], 'fn⌃': ['fn', '⌃'], '⌘⇧A': ['⌘', '⇧', 'A'], 'F5': ['F5']};
for (const [label, keys] of Object.entries(want)) if (JSON.stringify(capsOf(label)) !== JSON.stringify(keys)) { console.error(label, capsOf(label)); process.exit(1); }'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        swift = (ROOT / 'Atticus.swift').read_text()
        self.assertIn('"hotkeyLabel": Prefs.str("hotkeyLabel")', swift)   # setup draws the keys the user set
        self.assertIn('call("ob.keys", held)', swift)
        self.assertIn('CGEventSource.keyState(.combinedSessionState', swift)   # the main key lights as well as modifiers
        self.assertNotIn('id="t1"', self.page)

    def test_provider_row_names_no_client_before_the_check(self):
        self.assertIn('<div class="txt"><b>AI Provider</b><span>Checking…</span></div>', self.page)   # Devin, Pi and server users never read "Claude" first
        self.assertNotIn('Checking your Claude sign-in', self.page)

    def test_failed_asks_only_open_setup_automatically_once_per_launch(self):
        swift = (ROOT / 'Atticus.swift').read_text()
        opening = swift.split('    func open(automatic: Bool = false) {', 1)[1].split('        screenInitiallyGranted', 1)[0]
        self.assertIn('if automatic && setupShown { return }', opening)
        self.assertLess(opening.index('if automatic && setupShown'), opening.index('setupShown = true'))
        self.assertLess(opening.index('setupShown = true'), opening.index('guard win == nil'))
        self.assertIn('setupShown = false', swift)
        self.assertEqual(swift.count('setupShown = true'), 1)
        self.assertIn('if line == "! setup" { onboarding.open(automatic: true); continue }', swift)
        self.assertIn('case "setup": onboarding.open()', swift)   # explicit setup stays available after dismissal
        self.assertIn('if !UserDefaults.standard.bool(forKey: "onboarded") || UserDefaults.standard.string(forKey: "setupPage") != nil { DispatchQueue.main.async { onboarding.open() } }', swift)
        self.assertIn('else { Onboarding.plan { c in if c["ok"] as? Bool != true { onboarding.open(automatic: true) } } }', swift)
        self.assertIn('UserDefaults.standard.string(forKey: "setupPage") ?? (automatic ? "ai" : nil)', swift.split('    func open(automatic: Bool = false) {', 1)[1].split('loadPage(v', 1)[0])   # the page he was on, else a sign-in problem opens at the AI step

    @unittest.skipUnless(shutil.which('node'), 'node runs the start page choice')
    def test_saved_setup_page_that_is_not_a_page_starts_at_welcome(self):
        pages = re.search(r'  const pages = .*\n', self.page).group(0)
        start = re.search(r'paintProv\(\); go\((.*)\);\n', self.page).group(1)
        script = pages + f'const pick = obStart => {{ const window = {{ obStart }}; return {start}; }};\n' + '''
const want = [['perms', 'perms'], ['try', 'try'], [undefined, 'welcome'], ['', 'welcome'], ['Nope', 'welcome'], ['constructor', 'welcome']];
for (const [saved, page] of want) if (pick(saved) !== page) { console.error(saved, pick(saved)); process.exit(1); }'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_setup_opens_settings_for_invalid_configuration_before_signin(self):
        swift = (ROOT / 'Atticus.swift').read_text()
        fix = swift.split('    func fixPlan() {', 1)[1].split('    func tried()', 1)[0]
        self.assertIn('if need.isEmpty, c["ok"] as? Bool == false { Atticus.settings.open(); return }', fix)
        self.assertLess(fix.index('if need.isEmpty'), fix.index('var cmd ='))

    def test_setup_checks_one_provider_process_at_a_time(self):
        swift = (ROOT / 'Atticus.swift').read_text()
        check = swift.split('    func checkPlan() {', 1)[1].split('\n    }', 1)[0]
        self.assertIn('guard !checkingPlan else { return }', check)
        self.assertLess(check.index('checkingPlan = true'), check.index('Onboarding.plan'))
        self.assertIn('self?.checkingPlan = false', check)

    @unittest.skipUnless(shutil.which('zsh'), 'runs the sign-in command in zsh, like the app')
    def test_signin_clears_failure_only_after_success(self):
        swift = (ROOT / 'Atticus.swift').read_text()
        fix = swift.split('    func fixPlan() {', 1)[1].split('    func tried()', 1)[0]
        self.assertIn('if !devin && !pi && !server {', fix)
        self.assertIn('replacingOccurrences(of: "\'", with: "\'\\\\\'\'")', fix)
        suffix = re.search(r'cmd \+= "([^"\n]+)"', fix).group(1)
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "fixture's state" / 'claude-signed-out'
            marker.parent.mkdir()
            command = suffix.replace('\\(marker)', str(marker).replace("'", "'\\''"))
            for result in (1, 0):
                marker.touch()
                subprocess.run(['zsh', '-c', f'(exit {result})' + command], check=False)
                self.assertEqual(marker.exists(), result != 0)

    def test_voice_asks_use_only_engine_supported_languages(self):
        swift = (ROOT / 'Atticus.swift').read_text()
        speech = swift.split('    func speechModule(', 1)[1].split('    func prepareSpeech()', 1)[0]
        self.assertIn('supportedSpeechLocale(speechLocales[Prefs.str("speechModel")] ?? [])', speech)
        self.assertNotIn('Locale.current', speech)   # SpeechTranscriber rejected the Mac's locale: every voice ask died in 1.5.0
        self.assertIn(': SpeechTranscriber(locale: locale, preset: .progressiveTranscription)', speech)
        start = swift.split('    func start(dictate: Bool, quiet: Bool = false)', 1)[1].split('    func heard(', 1)[0]
        self.assertIn('Onboarding.permissionState($0) != 1', start)
        self.assertIn('voicePermissions(needs, dictate: dictate, quiet: quiet)', start)
        prepare = swift.split('    func prepareSpeech()', 1)[1].split('    var text =', 1)[0]
        self.assertIn('guard !preparingSpeech else { return }', prepare)
        self.assertIn('await DictationTranscriber.supportedLocales', prepare)
        self.assertIn('await SpeechTranscriber.supportedLocales', prepare)


if __name__ == '__main__':
    unittest.main()
