"""Daily capture stays anonymous and retries failed sends, without network access."""
import json
import os
import platform
import re
from pathlib import Path
import subprocess
import tempfile
import io
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import atticus
from tests import run_swift


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        test_dir = os.environ.pop('ATTICUS_DIR', None)
        self.addCleanup(lambda: os.environ.__setitem__('ATTICUS_DIR', test_dir) if test_dir is not None else os.environ.pop('ATTICUS_DIR', None))

    def test_success_is_daily_and_failure_can_retry(self):
        with tempfile.TemporaryDirectory(prefix='atticus telemetry ') as root:
            root = Path(root)
            curl = root / 'curl'
            curl.write_text('#!/bin/sh\nexit "${FAKE_CURL_STATUS:-0}"\n')
            curl.chmod(0o700)
            spawn = subprocess.Popen

            def fake_send(args, **kwargs):
                payload = json.loads(args[4])
                self.assertEqual(payload['event'], 'used')
                self.assertEqual(payload['api_key'], 'fixture-token')
                self.assertEqual(payload['properties'], {'$process_person_profile': False, 'version': atticus.APP_VERSION, 'commit': atticus.APP_COMMIT,
                                                                  'macos': platform.mac_ver()[0], 'client': 'claude'})
                self.assertEqual(set(payload), {'api_key', 'event', 'distinct_id', 'properties'})
                worker = spawn(args, **kwargs)
                worker.wait(timeout=5)
                return worker

            with patch.object(atticus, 'DIR', str(root)), patch.object(atticus, 'POSTHOG_KEY', 'fixture-token'), \
                 patch.object(atticus, 'pref', return_value=True), patch.object(atticus.subprocess, 'Popen', side_effect=fake_send) as send, \
                 patch.dict(os.environ, {'PATH': str(root), 'FAKE_CURL_STATUS': '22'}):
                atticus.ping()
                self.assertFalse((root / 'pinged').exists())
                identity = (root / 'id').read_text()
                os.environ['FAKE_CURL_STATUS'] = '0'
                atticus.ping()
                self.assertTrue((root / 'pinged').exists())
                atticus.ping()
                self.assertEqual(send.call_count, 2)
                self.assertEqual((root / 'id').read_text(), identity)

    def test_failure_and_used_events_include_the_same_app_version_field(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root), \
             patch.object(atticus, 'POSTHOG_KEY', 'fixture-token'), \
             patch.object(atticus, 'pref', side_effect=lambda k, d: {'improve': True}.get(k, d)), \
             patch.object(atticus.subprocess, 'Popen') as send:
            atticus.report('Open the fixture', 'Could not open it', (), 1, 'error')
        payload = json.loads(send.call_args.args[0][4])
        self.assertEqual(payload['event'], 'task_failed')
        self.assertEqual(payload['properties']['version'], atticus.APP_VERSION)
        self.assertEqual(set(payload['properties']), {'$process_person_profile', 'version', 'commit', 'task', 'reply', 'steps', 'why', 'secs', 'model', 'client', 'macos'})

    def test_failure_reports_drop_text_applescript_types_or_writes(self):
        steps = ['osascript -e \'tell application "System Events" to keystroke "hunter2"\'',
                 'osascript -e \'tell application "Notes" to make new note with properties {name:"Diary", body:"private words"}\'',
                 'osascript -e \'tell application "Notes" to set body of note 1 to "private words"\'']
        cleaned = ' '.join(map(atticus.clean, steps))
        self.assertFalse(any(word in cleaned for word in ('hunter2', 'Diary', 'private')))
        self.assertIn('tell application "Notes"', cleaned)

    def test_ask_done_has_counts_and_command_classes_but_no_ask_text(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root), \
             patch.object(atticus, 'POSTHOG_KEY', 'fixture-token'), patch.object(atticus, 'pref', return_value=True), \
             patch.object(atticus.subprocess, 'Popen') as send:
            atticus.ask_done({'task': 'Private request', 'reply': 'Private answer', 'path': 'shortcut', 'model': 'instant',
                              'secs': 1.26, 'steps': ['one', 'two'], 'ran': [f'{atticus.PLACE} Notes left', f'{atticus.WEB} read secret'],
                              'status': 'completed', 'escalated': False})
        payload = json.loads(send.call_args.args[0][4])
        self.assertEqual(payload['event'], 'ask_done')
        self.assertEqual(payload['properties']['tools'], ['place', 'web'])
        self.assertEqual(payload['properties']['status'], 'ok')
        self.assertEqual(set(payload['properties']), {'$process_person_profile', 'version', 'commit', 'path', 'model', 'secs', 'steps',
                                                      'tools', 'status', 'escalated', 'outcome', 'macos', 'client'})
        self.assertNotIn('Private', json.dumps(payload))

    def test_ask_done_maps_terminal_states(self):
        with patch.object(atticus, 'posthog') as send:
            for state in ('completed', 'failed', 'cancelled'):
                atticus.ask_done({'status': state})
        self.assertEqual([call.args[1]['status'] for call in send.call_args_list], ['ok', 'failed', 'cancelled'])

    def test_error_shapes_never_include_exception_messages_or_shortcut_words(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root), \
             patch.object(atticus, 'POSTHOG_KEY', 'fixture-token'), patch.object(atticus, 'pref', return_value=True), \
             patch.object(atticus.subprocess, 'Popen') as send:
            try:
                raise RuntimeError('private crash detail')
            except RuntimeError as error:
                atticus.exception_error(type(error), error.__traceback__)
            atticus.report_error('replay', shortcut='0123456789abcdef', failed_at=2)
        crash, replay = [json.loads(call.args[0][4]) for call in send.call_args_list]
        self.assertEqual(set(crash['properties']), {'$process_person_profile', 'version', 'commit', 'kind', 'macos', 'client',
                                                    'exception', 'file', 'line', 'function', 'at_line', 'at_function'})
        self.assertEqual(crash['properties']['exception'], 'RuntimeError')
        self.assertNotIn('private crash detail', json.dumps(crash))
        self.assertEqual(replay['properties']['kind'], 'replay')
        self.assertEqual(replay['properties']['shortcut'], '0123456789abcdef')
        self.assertEqual(replay['properties']['failed_at'], 2)

    def test_a_crash_inside_the_standard_library_names_the_atticus_line_and_errno(self):
        code = {}
        exec(compile('import subprocess\ndef go():\n    subprocess.Popen(["/no/such/tool"])\n', atticus.ME, 'exec'), code)   # a frame that counts as atticus.py
        with patch.object(atticus, 'report_error') as sent:
            try:
                code['go']()
            except OSError as error:
                atticus.exception_error(type(error), error.__traceback__, error)
        props = sent.call_args.kwargs
        self.assertEqual((props['at_function'], props['at_line'], props['errno']), ('go', 3, 2))
        self.assertEqual(props['exception'], 'FileNotFoundError')
        self.assertNotEqual(props['file'], 'atticus.py')

    def test_setup_problems_are_separate_from_real_worker_failures(self):
        cases = [('HTTP 404: model llama3 may not exist', True, 'server_rejected'),
                 ('400: model does not support tools', True, 'server_rejected'),
                 ('422: incompatible request', True, 'server_rejected'),
                 ('OAuth session expired', False, 'signed_out'),
                 ('HTTP 429', False, 'rate_limited'), ('Rate limit reached for requests', False, 'rate_limited'),
                 ('You’ve hit your weekly limit · resets 3pm', False, 'plan_limit'), ('Context window limit reached', False, 'too_long'),
                 ('network connection failed', False, 'offline'),
                 ("There's an issue with the selected model (qwen3). It may not exist", True, 'model_missing'),
                 ('[claude-code:unrecognized_model] {"model":"qwen3:4b"}', True, 'model_missing'), ('Error: Login canceled', False, 'signed_out')]
        with patch.object(atticus, 'report_error') as sent:
            for detail, custom, why in cases:
                self.assertEqual(atticus.failure_why(detail, custom), why)
                atticus.report_worker_failure('claude', 'private-model-name', why)
            for why in ('setup_needed', 'provider_needed', 'model_missing'):
                atticus.report_worker_failure('pi', 'haiku', why)
        self.assertTrue(all(call.args == ('setup',) for call in sent.call_args_list))
        self.assertNotIn('private', str(sent.call_args_list))
        with patch.object(atticus, 'report_error') as sent:
            atticus.report_worker_failure('claude', 'haiku', atticus.failure_why('Unknown process failure'))
        sent.assert_called_once_with('worker_exit', worker='claude', model='haiku', why='stopped')
        self.assertEqual(atticus.failure_why('Credit balance is too low'), 'billing')
        with patch.object(atticus, 'report_error') as sent:
            atticus.report_worker_failure('claude', 'haiku', 'stopped', 'my secret note at ~/x: SyntaxError near line 3')
            atticus.report_worker_failure('pi', 'haiku', 'tool_failed', 'my terror, Exit code 1')
            atticus.report_worker_failure('pi', 'haiku', 'tool_failed', 'plain words only')
        self.assertEqual([c.kwargs.get('hint') for c in sent.call_args_list], ['SyntaxError', 'Exit code 1', None])

    def test_cancellation_has_no_error_event(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root), patch.object(atticus, 'TURN', {}), \
             patch.object(atticus, 'posthog') as sent:
            atticus.begin_turn('Private request')
            atticus.end_turn()
            atticus.report_worker_failure('claude', 'haiku', 'cancelled')
        self.assertEqual([call.args[0] for call in sent.call_args_list], ['ask_done'])
        self.assertEqual(sent.call_args.args[1]['status'], 'cancelled')

    def test_allow_decisions_share_denial_without_matching_reply_text(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root), \
             patch.dict(os.environ, {'ATTICUS_ASK': root}):
            marker = Path(root, 'declined')
            for question, answer, declined in [({'q': 'Send?', 'cmd': 'fixture'}, 'n', True),
                                                ({'q': 'Send?', 'cmd': 'fixture'}, 'y', False),
                                                ({'q': 'Send?', 'cmd': 'fixture'}, 'task', False),
                                                ({'pick': 'Which?', 'options': []}, '', False),
                                                ({'q': 'Retry?', 'retry': True}, 'n', False),
                                                ({'q': 'Permission?', 'need': 'screen'}, 'n', False)]:
                marker.unlink(missing_ok=True)
                def respond(path, data): Path(data['_a']).write_text(answer)
                with patch.object(atticus, 'private_json', side_effect=respond):
                    self.assertEqual(atticus.ask_user(question, 1), answer)
                self.assertEqual(marker.exists(), declined)
            atticus.ask_user({'q': 'Send?', 'cmd': 'fixture'}, 0)
            self.assertTrue(marker.exists())
            with patch.object(Path, 'touch', side_effect=FileNotFoundError):
                self.assertIsNone(atticus.ask_user({'q': 'Send?', 'cmd': 'fixture'}, 0))

    def test_question_after_ask_cleanup_is_cancelled_without_publishing_a_card(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root), \
             patch.dict(os.environ, {'ATTICUS_ASK': str(Path(root, 'removed-ask'))}), \
             patch.object(atticus, 'private_json') as publish:
            directory = Path(root, 'removed-ask')
            directory.mkdir()
            open_lock = os.open
            def cancelled_before_lock(path, flags, mode):
                directory.rmdir()
                return open_lock(path, flags, mode)
            with patch.object(atticus.os, 'open', side_effect=cancelled_before_lock):
                self.assertIsNone(atticus.ask_user({'q': 'Send?', 'cmd': 'fixture'}, 60))
            self.assertIsNone(atticus.ask_user({'q': 'Send?', 'cmd': 'fixture'}, 60))
            publish.assert_not_called()
            self.assertFalse(Path(root, 'removed-ask').exists())

    def test_main_crash_is_reported_once_with_the_handled_exit_status(self):
        with patch.object(atticus, 'main', side_effect=RuntimeError('private detail')), \
             patch.object(atticus, 'end_turn') as end, patch.object(atticus, 'telemetry_enabled', return_value=True), \
             patch.object(atticus, 'posthog') as sent, patch('sys.stderr', io.StringIO()):
            with self.assertRaises(SystemExit) as stopped: atticus.run_main()
        self.assertEqual(stopped.exception.code, 70)
        end.assert_called_once_with('crashed')
        sent.assert_called_once()
        self.assertEqual((sent.call_args.args[0], sent.call_args.args[1]['kind'], sent.call_args.args[1]['worker']), ('error', 'worker_exit', 'python'))
        self.assertNotIn('private detail', str(sent.call_args))

    def test_normal_exits_and_a_closed_output_pipe_do_not_report_crashes(self):
        with patch.object(atticus, 'report_error') as sent, patch.object(atticus, 'end_turn') as end:
            with patch.object(atticus, 'main', side_effect=SystemExit(0)):
                with self.assertRaises(SystemExit): atticus.run_main()
            reader, writer = os.pipe(); os.close(reader)
            with os.fdopen(writer, 'w') as output, patch.object(atticus, 'main', side_effect=BrokenPipeError), \
                 patch.object(atticus, 'stop_workers') as stop, patch('sys.stdout', output):
                atticus.run_main()
                sys.stdout.close()   # run_main replaced it with devnull
            stop.assert_called_once()
        sent.assert_not_called(); end.assert_not_called()

    def test_a_failed_crash_checkpoint_cannot_duplicate_or_hide_the_crash(self):
        with patch.object(atticus, 'main', side_effect=ValueError('private detail')), \
             patch.object(atticus, 'end_turn', side_effect=OSError('unwritable log')), \
             patch.object(atticus, 'report_error') as sent, patch('sys.stderr', io.StringIO()):
            with self.assertRaises(SystemExit) as stopped: atticus.run_main()
        self.assertEqual(stopped.exception.code, 70)
        sent.assert_called_once()
        self.assertEqual(sent.call_args.args, ('worker_exit',))
        self.assertEqual(sent.call_args.kwargs['exception'], 'ValueError')

    def test_thread_exit_is_normal_and_a_closed_relay_pipe_cancels_the_process(self):
        reader, writer = os.pipe(); os.close(reader)
        with os.fdopen(writer, 'w') as output, patch.object(sys, 'excepthook'), patch.object(threading, 'excepthook'), \
             patch.object(atticus, 'report_error') as sent, patch.object(atticus, 'stop_workers') as stop, patch('sys.stdout', output):
            atticus.install_exception_hooks()
            for error in (SystemExit(0), BrokenPipeError()):
                threading.excepthook(SimpleNamespace(exc_type=type(error), exc_value=error, exc_traceback=None))
            sys.stdout.close()
        stop.assert_called_once(); sent.assert_not_called()

    def test_a_daemon_thread_failing_during_shutdown_is_not_a_crash(self):
        with patch.object(sys, 'excepthook'), patch.object(threading, 'excepthook') as previous, \
             patch.object(atticus, 'report_error') as sent:
            atticus.install_exception_hooks()
            with patch.object(threading, 'main_thread', return_value=SimpleNamespace(is_alive=lambda: False)):
                threading.excepthook(SimpleNamespace(exc_type=ValueError, exc_value=ValueError(), exc_traceback=None))
            error = RuntimeError('cannot schedule new futures after interpreter shutdown')
            threading.excepthook(SimpleNamespace(exc_type=type(error), exc_value=error, exc_traceback=None))
            sent.assert_not_called(); previous.assert_not_called()
            for detail in ('real worker failure', 'cannot schedule new futures after shutdown'):
                error = RuntimeError(detail)
                threading.excepthook(SimpleNamespace(exc_type=type(error), exc_value=error, exc_traceback=None))
        self.assertEqual(sent.call_count, 2); self.assertEqual(previous.call_count, 2)

    def test_a_backend_broken_pipe_with_live_output_is_a_real_failure(self):
        with patch.object(atticus, 'main', side_effect=BrokenPipeError), patch.object(atticus, 'end_turn'), \
             patch.object(atticus, 'report_error') as sent, patch('sys.stdout', io.StringIO()), patch('sys.stderr', io.StringIO()):
            with self.assertRaises(SystemExit) as stopped: atticus.run_main()
        self.assertEqual(stopped.exception.code, 70)
        self.assertEqual(sent.call_args.args, ('worker_exit',))

    def test_swift_reports_only_unreported_process_deaths(self):
        source = Path(atticus.ME).with_name('Atticus.swift').read_text()
        rule = next(line.strip() for line in source.splitlines() if 'if p.terminationReason == .uncaughtSignal' in line)
        run_swift(self, '''import Foundation
struct Worker { var terminationReason: Process.TerminationReason; var terminationStatus: Int32 }
var sent = 0
func telemetry(_ args: [String]) { sent += 1 }
for (p, expected) in [(Worker(terminationReason: .exit, terminationStatus: 0), 0),
                      (Worker(terminationReason: .exit, terminationStatus: 70), 0),
                      (Worker(terminationReason: .exit, terminationStatus: 1), 1),
                      (Worker(terminationReason: .uncaughtSignal, terminationStatus: 15), 1),
                      (Worker(terminationReason: .uncaughtSignal, terminationStatus: 70), 1)] {
    sent = 0
    ''' + rule + '''
    precondition(sent == expected)
}
''')

    def test_dictation_has_only_mode_counts_timing_and_outcome(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root), \
             patch.object(atticus, 'POSTHOG_KEY', 'fixture-token'), patch.object(atticus, 'pref', return_value=True), \
             patch.object(atticus.subprocess, 'Popen') as send:
            atticus.dictation_event('cleanup', 1.23456, True, False, False, 'no box')
        payload = json.loads(send.call_args.args[0][4])
        self.assertEqual(payload['event'], 'dictation')
        self.assertEqual(payload['properties']['secs'], 1.235)
        self.assertEqual(set(payload['properties']), {'$process_person_profile', 'version', 'commit', 'macos', 'client', 'mode', 'secs',
                                                      'cleanup_used', 'fell_back', 'timed_out', 'insert'})

    def test_the_ask_log_and_its_folder_are_private_even_on_older_installs(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root):
            os.chmod(root, 0o755); log = Path(root, 'log.jsonl'); log.write_text(''); log.chmod(0o644)
            atticus.append_log({'task': 'Summarize my inbox'})
            self.assertEqual((os.stat(root).st_mode & 0o777, log.stat().st_mode & 0o777), (0o700, 0o600))

    def test_page_errors_reach_native_as_code_locations_only(self):
        source = Path(atticus.ME).with_name('Atticus.swift').read_text()
        shared = source[source.index('// Call a page function with JSON arguments'):source.index('// The system arrow as window.obCursor')]
        out = json.loads(run_swift(self, r'''import Cocoa
import WebKit
let dir = "''' + str(Path(atticus.ME).parent) + r'''"
enum Prefs { static let uiLanguage = "en"; static func resolveUILanguage(_ s: String) -> String { "en" } }
var reports: [[String]] = [], works: [String: Any] = [:], webs: [WKWebView] = []
func telemetry(_ args: [String]) { reports.append(args) }
''' + shared + r'''
final class Sink: NSObject, WKScriptMessageHandler { func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {} }
let sink = Sink()
let pages = [("ui.html", "typeof ui === 'object' && !!document.getElementById('card')", "ui.noSuchCall"),
             ("drawing-math.html", "drawingMath('**Step one** then $x^2$', 22, 'white', 300).height > 0", "drawingMath.noSuchCall")]
let boom = "const s = document.createElement('script'); s.textContent = \"const boom = () => { throw new TypeError('private words') }; setTimeout(boom); setTimeout(boom); Promise.reject(new RangeError('private words'))\"; document.body.append(s); 0"
func open(_ i: Int) {
    guard i < pages.count else { print(String(data: try! JSONSerialization.data(withJSONObject: ["works": works, "reports": reports]), encoding: .utf8)!); exit(0) }
    let cfg = WKWebViewConfiguration()
    for n in ["h", "c", "drawingMath", "agents"] { cfg.userContentController.add(sink, name: n) }
    let web = WKWebView(frame: NSRect(x: 0, y: 0, width: 400, height: 600), configuration: cfg); webs.append(web)
    loadPage(web, pages[i].0); loadPage(web, pages[i].0)   // a reload adds no second handler
    func ready() {
        web.evaluateJavaScript("document.readyState") { state, _ in
            guard state as? String == "complete" else { return DispatchQueue.main.asyncAfter(deadline: .now() + 0.2, execute: ready) }
            web.evaluateJavaScript(pages[i].1) { r, e in
                works[pages[i].0] = r ?? String(describing: e)
                callJS(web, pages[i].2, ["private words"]); callJS(web, pages[i].2, ["private words"])
                web.evaluateJavaScript(boom) { _, _ in DispatchQueue.main.asyncAfter(deadline: .now() + 1) { open(i + 1) } }
            }
        }
    }
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5, execute: ready)
}
NSApplication.shared.setActivationPolicy(.prohibited)
open(0)
DispatchQueue.main.asyncAfter(deadline: .now() + 50) { print("timeout"); exit(1) }
NSApplication.shared.run()
''', timeout=60).strip().splitlines()[-1])
        self.assertEqual(out['works'], {'ui.html': True, 'drawing-math.html': True})
        # one per signature and no load errors; window errors in these opaque-origin pages arrive muted, calls from Swift name their class and line
        self.assertEqual(sorted((r[2], r[3], r[4]) for r in out['reports']),
                         [('drawing-math', 'RangeError', 'about:blank'), ('drawing-math', 'muted', ''), ('drawingMath', 'TypeError', 'eval'),
                          ('ui', 'RangeError', 'about:blank'), ('ui', 'TypeError', 'eval'), ('ui', 'muted', '')], out['reports'])
        self.assertTrue(all(r[:2] == ['error', 'js'] and len(r) == 7 and r[5].isdigit() for r in out['reports']), out['reports'])
        self.assertTrue(all(int(r[5]) > 0 for r in out['reports'] if r[3] != 'muted'), out['reports'])
        self.assertNotIn('private', json.dumps(out))

    def test_calls_made_while_a_page_loads_wait_for_it(self):
        source = Path(atticus.ME).with_name('Atticus.swift').read_text()
        shared = source[source.index('// Call a page function with JSON arguments'):source.index('// The system arrow as window.obCursor')]
        click = source[source.index('// The box can take typing'):source.index('final class KeyPanel')]
        out = json.loads(run_swift(self, r'''import Cocoa
import WebKit
let dir = "''' + str(Path(atticus.ME).parent) + r'''"
enum Prefs { static let uiLanguage = "en"; static func resolveUILanguage(_ s: String) -> String { "en" } }
var reports: [[String]] = [], clean: [[String]] = [], seen: [String: Any] = [:], webs: [WKWebView] = []
func telemetry(_ args: [String]) { reports.append(args) }
''' + shared + click + r'''
final class Sink: NSObject, WKScriptMessageHandler { func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {} }
let sink = Sink()
let runs: [(String, String, String, String)] = [("click", "onboarding.html", "ob", "keys"), ("click", "ui.html", "ui", "hover"), ("plain", "onboarding.html", "ob", "keys")]
func open(_ i: Int) {
    guard i < runs.count else { print(String(data: try! JSONSerialization.data(withJSONObject: ["seen": seen, "clean": clean, "reports": reports]), encoding: .utf8)!); exit(0) }
    let (kind, page, object, call) = runs[i], cfg = WKWebViewConfiguration()
    if kind == "plain" { clean = reports }
    for n in ["ob", "h", "c"] { cfg.userContentController.add(sink, name: n) }
    let frame = NSRect(x: 0, y: 0, width: 640, height: 600)
    let web = kind == "click" ? ClickWebView(frame: frame, configuration: cfg) : WKWebView(frame: frame, configuration: cfg); webs.append(web)
    loadPage(web, page)
    callJS(web, object + "." + call, [true])
    web.evaluateJavaScript(object == "ob" ? "ob.mode(true)" : "ui.size(200)")
    web.evaluateJavaScript("window." + object + " ? 'object' : 'undefined'") { r, _ in seen[kind + " " + page] = r ?? "nil" }
    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { open(i + 1) }
}
NSApplication.shared.setActivationPolicy(.prohibited)
open(0)
DispatchQueue.main.asyncAfter(deadline: .now() + 30) { print("timeout"); exit(1) }
NSApplication.shared.run()
''', timeout=60).strip().splitlines()[-1])
        self.assertEqual(out['seen'], {'click onboarding.html': 'object', 'click ui.html': 'object', 'plain onboarding.html': 'undefined'})
        self.assertEqual(out['clean'], [])   # no ReferenceError, and no "muted" window echo of one
        # the same calls on a plain web view fail the way PostHog saw it: ReferenceError at 1:3, from an evaluateJavaScript string
        self.assertIn(['error', 'js', 'ob', 'ReferenceError', 'eval', '1', '3'], out['reports'])

    def test_page_error_bridge_sends_only_names_and_numbers(self):
        with patch.object(atticus, 'report_error') as sent:
            for fields in (['ui', 'TypeError', 'about:blank', '12', '7'], ['ui', 'my private words', 'x y', 'twelve', '-1']):
                with patch.object(sys, 'argv', ['atticus.py', '--telemetry', 'error', 'js', *fields]): atticus.main()
        self.assertEqual(sent.call_args_list[0].kwargs, {'page': 'ui', 'exception': 'TypeError', 'file': 'about:blank', 'line': 12, 'column': 7})
        self.assertEqual(sent.call_args_list[1].kwargs, {'page': 'ui', 'exception': 'other', 'file': 'other', 'line': 0, 'column': 0})
        self.assertNotIn('private', str(sent.call_args_list))

    def test_native_crashes_are_reported_once_with_type_signal_and_atticus_frame(self):
        with tempfile.TemporaryDirectory() as root:
            logs = Path(root, 'Library/Logs/DiagnosticReports'); logs.mkdir(parents=True)
            head = {'app_name': 'Atticus', 'app_version': '2.0.0', 'bug_type': '309'}
            body = {'exception': {'type': 'EXC_BREAKPOINT', 'signal': 'SIGTRAP', 'subtype': 'private words'}, 'procPath': '/Users/someone/Atticus.app',
                    'usedImages': [{'name': 'libswiftCore.dylib', 'path': '/usr/lib/x'}, {'name': 'Atticus', 'path': '/Users/someone/Atticus.app'}],
                    'threads': [{'frames': [{'imageIndex': 1, 'symbol': 'idle'}]},
                                {'triggered': True, 'frames': [{'imageIndex': 0, 'symbol': 'swift_fatal'}, {'imageIndex': 1, 'symbol': 'App.run(_:)', 'imageOffset': 4096}]}]}
            Path(logs, 'Atticus-2026-01-01-000000.ips').write_text(json.dumps(head) + '\n' + json.dumps(body))
            Path(logs, 'Atticus-2026-01-01-000001.ips').write_text(json.dumps({**head, 'bug_type': '298'}) + '\n{}')   # a hang, not a crash
            Path(logs, 'Other-2026-01-01-000000.ips').write_text(json.dumps(head) + '\n' + json.dumps(body))
            with patch.object(atticus, 'HOME', root), patch.object(atticus, 'DIR', str(Path(root, 'data'))), patch.object(atticus, 'report_error') as sent:
                atticus.report_crashes()
                atticus.report_crashes()   # the stamp: each crash once
        sent.assert_called_once_with('native_crash', exception='EXC_BREAKPOINT', signal='SIGTRAP', symbol='App.run(_:)', offset=4096, crashed='2.0.0')

    def test_a_failed_tool_names_the_tool_helper_and_exit_code_only(self):
        detail = atticus.failed_tool('Bash', '"$ATTICUS" --look "private words" ~/private/file', 'Exit code 2\nprivate output')
        self.assertEqual(detail, {'tool': 'Bash', 'helper': 'look', 'exit': 2})
        self.assertEqual(atticus.failed_tool('Read', '<Read>', 'private'), {'tool': 'Read'})
        self.assertEqual(atticus.failed_tool('private words here', ''), {'tool': 'other'})
        with patch.object(atticus, 'report_error') as sent:
            atticus.report_worker_failure('claude', 'haiku', 'tool_failed', 'private output', detail)
            atticus.report_worker_failure('claude', 'haiku', 'signed_out', '', {'exit': 1})
        self.assertEqual(sent.call_args_list[0].kwargs, {'worker': 'claude', 'model': 'haiku', 'why': 'tool_failed', 'tool': 'Bash', 'helper': 'look', 'exit': 2})
        self.assertNotIn('exit', sent.call_args_list[1].kwargs)
        self.assertNotIn('private', str(sent.call_args_list))

    def test_handled_feature_failures_send_stage_enums_only(self):
        source = Path(atticus.ME).with_name('Atticus.swift').read_text()
        stages = re.findall(r'telemetry\(\["error", "native", "([^"\\]*)', source)
        self.assertGreaterEqual(len(stages), 5)
        with patch.object(atticus, 'report_error') as sent:
            for stage in stages:
                with patch.object(sys, 'argv', ['atticus.py', '--telemetry', 'error', 'native', stage]): atticus.main()
            with patch.object(sys, 'argv', ['atticus.py', '--telemetry', 'error', 'native', 'my private words']), \
                 patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit): atticus.main()
        self.assertEqual([c.kwargs['stage'] for c in sent.call_args_list], stages)   # every Swift stage passes, text does not
        with patch.object(atticus, 'spotify_item', return_value=('spotify:track:fixture', 'Fixture song')), patch.object(atticus, 'osa', return_value=''), \
             patch.object(atticus.subprocess, 'run', side_effect=subprocess.TimeoutExpired('osascript', 30)), patch.object(atticus, 'report_error') as sent:
            self.assertIn('timed out', atticus.play('Fixture song'))
        sent.assert_called_once_with('play', stage='timed_out')

    def test_disabled_does_not_send(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root), \
             patch.object(atticus.subprocess, 'Popen') as send:
            with patch.object(atticus, 'POSTHOG_KEY', ''):
                atticus.ping()
            with patch.object(atticus, 'POSTHOG_KEY', 'fixture-token'), \
                 patch.object(atticus, 'pref', side_effect=lambda key, default: True if key == 'improve' else False):
                atticus.ping()
                atticus.ask_done({'status': 'completed'})
                atticus.report_error('stopped')
                atticus.dictation_event('verbatim', 1, False, False, False, 'ok')
                atticus.report('Private request', 'Private reply', (), 1, 'error')
            send.assert_not_called()
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_new_users_are_counted_by_default(self):
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root), \
             patch.object(atticus, 'PREFS', str(Path(root) / 'settings.json')), \
             patch.object(atticus, 'POSTHOG_KEY', 'fixture-token'), patch.object(atticus.subprocess, 'Popen') as send:
            atticus.ping()
        send.assert_called_once()


if __name__ == '__main__':
    unittest.main()
