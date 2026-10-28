"""Dictation routing and delivery with fake model, focus, and selection targets."""
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]


class DictationCleanupTests(unittest.TestCase):
    def test_cleanup_chunks_without_truncating_and_uses_cheapest(self):
        sys.path.insert(0, str(ROOT))
        import atticus
        with patch.object(atticus, 'relevant_rules', return_value='Spell my name Saarth.'), \
             patch.object(atticus, 'meeting_call', return_value=('<cleaned>Clean text.</cleaned>', {})) as call:
            cleaned = atticus.dictate_cleanup('um Clean text. ' + 'x' * 7000)
        self.assertTrue(cleaned.startswith('Clean text. '))
        self.assertNotIn('\n', cleaned)
        self.assertTrue(cleaned.endswith('x' * 1000))
        self.assertEqual(call.call_count, 2)
        for args, kwargs in call.call_args_list:
            self.assertEqual(kwargs['model'], 'haiku')
            self.assertEqual(kwargs['label'], 'Dictation cleanup')
            self.assertIn('Spell my name Saarth.', args[1])
            self.assertLessEqual(len(args[1]), 7100)
        paragraph = 'a ' * 3000 + '\n\n' + 'b ' * 3000
        with patch.object(atticus, 'client', return_value='pi'):
            self.assertEqual(atticus.dictate_cleanup(paragraph), paragraph.replace(' \n\n', '\n\n').strip())
        with patch.object(atticus, 'meeting_call') as empty:
            self.assertEqual(atticus.dictate_cleanup('   '), '')
            empty.assert_not_called()

    def test_cleanup_failure_keeps_all_text_and_removes_fillers_locally(self):
        import atticus
        source = 'I um need this. ' + ('word ' * 1400) + 'Uh, final words.'
        with patch.object(atticus, 'client', return_value='claude'), \
             patch.object(atticus, 'relevant_rules', return_value=''), \
             patch.object(atticus, 'meeting_call', side_effect=RuntimeError('offline')):
            cleaned = atticus.dictate_cleanup(source)
        self.assertIn('final words.', cleaned)
        self.assertNotRegex(cleaned.lower(), r'\b(?:um|uh)\b')
        self.assertGreater(len(cleaned), 6000)

    def test_cleanup_accepts_small_grammar_and_saved_spelling_edits(self):
        import atticus
        self.assertEqual(atticus.dictate_result('he go to school', '<cleaned>He goes to school.</cleaned>'), 'He goes to school.')
        with patch.object(atticus, 'relevant_rules', return_value='Spell my name Saarth.'), \
             patch.object(atticus, 'meeting_call', return_value=('<cleaned>My name is Saarth.</cleaned>', {})):
            self.assertEqual(atticus.dictate_cleanup('My name is Sarth.'), 'My name is Saarth.')

    def test_hint_scan_is_bounded_at_the_largest_dictionary(self):
        import atticus
        words = ['s' + ''.join(chr(98 + i // 26 % 20) + chr(98 + i % 20) for _ in range(4)) for i in range(500)]
        text = ' '.join(f'sapphire{i}' for i in range(400))
        started = time.monotonic()
        atticus.dictate_hints(text, words)
        self.assertLess(time.monotonic() - started, .25)

    def test_cleanup_rejects_scattered_extracts_but_keeps_one_restart(self):
        import atticus
        source = 'We should send the complete release report to everyone on the team before lunch today.'
        extract = '<cleaned>Send the report to the team.</cleaned>'
        self.assertEqual(atticus.dictate_result(source, extract), source)
        self.assertEqual(atticus.dictate_result(source, '<cleaned>Send the report to the team today.</cleaned>'), source)
        retries = 'So, yeah, could you release it by this window? Um, Can you read you see by this Wednesday? We know, um, this Friday, actually. Um, and then we can get working on deployment.'
        fixed = 'Could you release it by this Friday? And then we can get working on deployment.'
        self.assertEqual(atticus.dictate_result(retries, f'<cleaned>{fixed}</cleaned>'), fixed)
        long = 'I tested the build this morning. It crashed twice when I opened settings, and the logs show a nil window. I want it fixed before Friday.'
        self.assertEqual(atticus.dictate_result(long, '<cleaned>I tested the build this morning. I want it fixed before Friday.</cleaned>'), long)
        restart = 'Book the table for six, scratch that, book it for eight.'
        self.assertEqual(atticus.dictate_result(restart, '<cleaned>Book the table for eight.</cleaned>'),
                         'Book the table for eight.')

    def test_warmed_cleanup_ignores_malformed_stream_frames(self):
        import atticus
        result = json.dumps({'type': 'result', 'result': '<cleaned>I need this.</cleaned>'})
        process = type('Process', (), {
            'stdin': io.StringIO(),
            'stdout': iter(['not json\n', '[]\n', '{"type":"stream_event","event":null}\n',
                            '{"type":"stream_event","event":{"type":"content_block_delta","delta":{"text":null}}}\n',
                            result + '\n'])
        })()
        self.assertEqual(atticus.dictate_warmed(process, 'I um need this.', ''), 'I need this.')

    def test_non_claude_cleanup_falls_back_without_starting_claude(self):
        import atticus
        with patch.object(atticus, 'client', return_value='pi'), patch.object(atticus, 'meeting_call') as call:
            self.assertEqual(atticus.dictate_cleanup('Um, keep every word.'), 'keep every word.')
        call.assert_not_called()
        with patch.object(atticus, 'client', return_value='pi'), patch.object(atticus, 'meeting_process') as process, \
             patch('sys.stdin', io.StringIO('Um, keep every word.')), patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.dictate_cleanup_wait()
        process.assert_not_called()
        self.assertEqual(out.getvalue(), 'keep every word.\n')

    def test_short_dictation_skips_ai_and_cursor_text_reaches_cleanup(self):
        import atticus
        with patch.object(atticus, 'client', return_value='claude'), patch.object(atticus, 'meeting_call') as call:
            self.assertEqual(atticus.dictate_cleanup('Um, okay'), 'okay')
        call.assert_not_called()
        with patch.object(atticus, 'client', return_value='claude'), patch.object(atticus, 'meeting_process'), \
             patch.object(atticus, 'stop_claude'), patch.object(atticus, 'dictate_warmed') as warmed, \
             patch('sys.stdin', io.StringIO('Notes from Saarth\0uh I')), patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.dictate_cleanup_wait()
        warmed.assert_not_called()
        self.assertEqual(out.getvalue(), 'I\n')
        with patch.object(atticus, 'client', return_value='claude'), patch.object(atticus, 'meeting_process'), \
             patch.object(atticus, 'stop_claude'), patch.object(atticus, 'relevant_rules', return_value=''), \
             patch.object(atticus, 'dictate_warmed', return_value='Tell Saarth hi.') as warmed, \
             patch('sys.stdin', io.StringIO('Notes from Saarth\0tell sarth hi')), patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.dictate_cleanup_wait()
        self.assertEqual(out.getvalue(), 'Tell Saarth hi.\n')
        _, text, corrections, hints = warmed.call_args.args
        self.assertEqual(text, 'tell sarth hi')
        self.assertIn('Text before the cursor: "Notes from Saarth"', corrections)
        self.assertEqual(hints, {})

    def test_cleanup_start_failure_still_returns_local_cleanup(self):
        import atticus
        with patch.object(atticus, 'client', return_value='claude'), \
             patch.object(atticus, 'meeting_process', side_effect=OSError('missing')), \
             patch('sys.stdin', io.StringIO('I um need uh every word.')), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.dictate_cleanup_wait()
        self.assertEqual(out.getvalue(), 'I need every word.\n')

    def test_warmed_cleanup_deadline_starts_before_hint_work(self):
        import atticus
        started = []
        class Timer:
            daemon = False
            def __init__(self, *args, **kwargs): pass
            def start(self): started.append(True)
            def cancel(self): pass
        def hints(*_):
            self.assertTrue(started)
            return {}
        with patch.object(atticus, 'client', return_value='claude'), patch.object(atticus, 'meeting_process'), \
             patch.object(atticus, 'stop_claude'), patch.object(atticus.threading, 'Timer', Timer), \
             patch.object(atticus, 'dictate_hints', side_effect=hints), patch.object(atticus, 'dictate_warmed', return_value='Keep every word.'), \
             patch('sys.stdin', io.StringIO('keep every word')), patch('sys.stdout', new_callable=io.StringIO) as out:
            atticus.dictate_cleanup_wait()
        self.assertEqual(out.getvalue(), 'Keep every word.\n')


@unittest.skipUnless(sys.platform == 'darwin', 'macOS Swift regression')
class DictationNativeTests(unittest.TestCase):
    def test_long_dictation_rollover_stitches_overlap_without_doubling(self):
        source = (ROOT / 'Atticus.swift').read_text()
        helper = source[source.index('func stitchTranscript'):source.index('final class SpeechInputs')]
        swift = 'import Foundation\n' + helper + r'''
precondition(stitchTranscript("We should ship the release today", "the release today before lunch") == "We should ship the release today before lunch")
precondition(stitchTranscript("Keep punctuation, please.", "Punctuation please, and spacing.") == "Keep punctuation, please. and spacing.")
precondition(stitchTranscript("No shared ending", "Start fresh") == "No shared ending Start fresh")
precondition(stitchTranscript("", "First words") == "First words")
print("dictation stitching ok")
'''
        self.assertIn('dictation stitching ok', run_swift(self, swift))
        timer = source[source.index('Timer.scheduledTimer(withTimeInterval: 0.15'):source.index('    func heard(')]
        self.assertIn('rolloverSpeech(listeningID: listeningID)', timer)
        self.assertIn('if !dictating && held > 60', timer)

    def test_verbatim_skips_ai_cleanup_uses_one_call_and_cancel_drops_result(self):
        source = (ROOT / 'Atticus.swift').read_text()
        start = source[source.index('    func start(dictate: Bool)'):source.index('    func heard(')]
        self.assertIn('if !dictate && (!replying || drawingReply) { unwarm(); warm = spawn() }', start)
        self.assertIn('if dictateCleanup { warmDictationCleanup() }', start)
        method = source[source.index('    func stopDictationCleanup()'):source.index('    func dictationDeliveryFailed(')]
        swift = r'''import Foundation
var processCalls = 0, hang = false, workers: [Process] = []
func py(_ args: [String], _ extra: [String: String] = [:]) -> Process {
    precondition(args == ["--dictate-cleanup-wait"])
    processCalls += 1
    let p = Process(); p.executableURL = URL(fileURLWithPath: "/bin/sh")
    p.arguments = ["-c", hang ? "sleep 30" : "tr '\\000' '\\n' | tail -n 1"]   // the transcript after the cursor text's NUL; or a cleanup that never answers
    workers.append(p)
    return p
}
func telemetry(_ args: [String]) {}
struct Selection { let text: String }
struct AppRef: Equatable {}
final class NSWorkspace { static let shared = NSWorkspace(); var frontmostApplication: AppRef? }
final class Harness {
    var dictateSelectionPending = false, dictateCleanup = false, busy = true, dictating = true
    var dictateID = 1, text = "Exact words.", inserted: [String] = [], dictateBefore = "Notes before the cursor."
    var dictateFellBack = false, dictateTimedOut = false, dictateSelectionRetried = false
    var dictationTargetApp: AppRef?
    var dictateSelection: Selection?, dictateProcess: Process?, dictateInput: FileHandle?, dictateOutput: FileHandle?
    func captureDictationSelection(retry: Bool = false) {}
    func insertDictation(_ value: String) { inserted.append(value); busy = false; dictating = false }
    func dictationDeliveryFailed(_ value: String, cleanup: Bool = false) { busy = false; dictating = false }
    func cue(_ value: String) {}
    func hide(after: Double) {}
''' + method + r'''}
func pump(_ seconds: Double) {
    let end = Date().addingTimeInterval(seconds)
    while Date() < end { RunLoop.current.run(until: Date().addingTimeInterval(0.005)) }
}
let verbatim = Harness()
verbatim.finishDictation()
precondition(verbatim.inserted == ["Exact words."] && processCalls == 0, "verbatim called AI or changed the transcript")
let clean = Harness(); clean.dictateCleanup = true; clean.dictateSelection = Selection(text: "um selected words")
clean.warmDictationCleanup(); clean.finishDictation(); pump(0.5)
precondition(clean.inserted == ["Exact words."] && processCalls == 1, "cleanup did not use exactly one call or threw away the speech")
let cancelled = Harness(); cancelled.dictateCleanup = true
cancelled.warmDictationCleanup(); cancelled.finishDictation(); cancelled.dictateID += 1; cancelled.dictateProcess?.terminate(); pump(0.5)
precondition(cancelled.inserted.isEmpty && processCalls == 2, "cancelled cleanup inserted late output")
let early = Harness(); early.dictateCleanup = true; early.text = "Ship it by Friday."
early.warmDictationCleanup(); early.startDictateAhead(early: true); pump(0.3)
early.text = "ship it, by Friday"; early.finishDictation(); pump(0.3)
precondition(early.inserted == ["Ship it by Friday."] && processCalls == 4 && early.dictateProcess == nil, "matching words did not reuse the early cleanup or left the spare running")
let changed = Harness(); changed.dictateCleanup = true; changed.text = "Ship it by Friday"
changed.warmDictationCleanup(); changed.startDictateAhead(early: true)
changed.text = "Ship it by Friday morning"; changed.finishDictation(); pump(0.5)
precondition(changed.inserted == ["Ship it by Friday morning"] && processCalls == 6, "changed words used the stale early cleanup")
let bounded = Harness(); bounded.dictateCleanup = true; bounded.text = "Write the release notes"
bounded.warmDictationCleanup(); bounded.startDictateAhead(early: true)
bounded.text = "Write the release notes with setup steps"; bounded.startDictateAhead(early: true)
bounded.text = "Write the release notes with setup steps and examples"; bounded.startDictateAhead(early: true)
precondition(bounded.dictateAheadRuns == 2 && processCalls == 9 && bounded.dictateRun?.key == "write the release notes with setup steps",
             "pause cleanup was not capped at two runs")
bounded.startDictateAhead()
precondition(bounded.dictateAheadRuns == 3 && processCalls == 10 && bounded.dictateRun?.key == "write the release notes with setup steps and examples",
             "key-up did not use the warm spare after the pause budget was spent")
bounded.stopDictationCleanup()
let revised = Harness(); revised.dictateCleanup = true; revised.text = "Send the release notes"
revised.warmDictationCleanup(); revised.startDictateAhead(early: true)
revised.text = "Send the release notes after review today"; revised.startDictateAhead()
revised.text += " please"; revised.finishDictation(); pump(0.5)
precondition(revised.inserted == ["Send the release notes after review today please"] && processCalls == 13,
             "final speech revision did not use the third and last cleanup worker")
hang = true
let hung = Harness(); hung.dictateCleanup = true; hung.text = "keep these heard words"
hung.warmDictationCleanup(); hung.finishDictation(); pump(1)
precondition(hung.inserted.isEmpty, "gave up on a cleanup still inside its time")
pump(7.5)
precondition(hung.inserted == ["keep these heard words"] && hung.dictateRun == nil, "a cleanup that never answered held the heard words back")
pump(0.2)
precondition(workers.allSatisfy { !$0.isRunning }, "a cleanup worker was left running")
print("dictation routing ok")
'''
        self.assertIn('dictation routing ok', run_swift(self, swift, timeout=30))   # the hung-cleanup case waits out the 8 s fallback

    def test_selection_is_replaced_only_while_original_app_stays_front(self):
        source = (ROOT / 'Atticus.swift').read_text()
        method = source[source.index('    func insertDictation('):source.index('    func typed(')]
        swift = r'''import Foundation
struct Prefs { static func bool(_ key: String) -> Bool { false } }
enum DictationData { static func fixed(_ text: String) -> String { text } }
final class AppRef: Equatable {
    let id: Int
    init(_ id: Int) { self.id = id }
    static func == (a: AppRef, b: AppRef) -> Bool { a.id == b.id }
}
final class NSWorkspace {
    static let shared = NSWorkspace()
    var frontmostApplication: AppRef?
}
final class Target {
    let app: AppRef
    var received: [String] = [], preserved = false, deferred = false
    var pending: (() -> Void)?
    init(_ app: AppRef) { self.app = app }
    func apply(_ draft: String, preserveFocus: Bool = false, valid: @escaping () -> Bool, done: @escaping (Bool) -> Void) {
        preserved = preserveFocus
        let work = { [self] in let ok = valid(); if ok { received.append(draft) }; done(ok) }
        if deferred { pending = work } else { work() }
    }
}
final class Harness {
    var dictateSelection: Target?, busy = true, dictating = true, dictateID = 1
    var failed: [String] = []
    func cue(_ value: String) {}
    func js(_ call: String, _ arg: Any? = nil) {}
    func hide(after: Double, shrink: Bool = false) {}
    func prepareDictation(_ value: String, target: Target) -> () -> Void { {} }
    func dictationDeliveryFailed(_ value: String) { failed.append(value); busy = false; dictating = false }
    func recordDictationEvent(_ insert: String) {}
''' + method + r'''}
let user = AppRef(1), other = AppRef(2), target = Target(user), h = Harness()
h.dictateSelection = target; NSWorkspace.shared.frontmostApplication = user
h.insertDictation("replacement")
precondition(target.received == ["replacement"] && target.preserved, "selected text was not replaced through the focus-preserving path")
let missing = Harness(); missing.insertDictation("copy me")
precondition(missing.failed == ["copy me"], "missing target lost the transcript")
let moved = Target(user), h2 = Harness(); h2.dictateSelection = moved; NSWorkspace.shared.frontmostApplication = other
h2.insertDictation("wrong")
precondition(moved.received.isEmpty && h2.failed == ["wrong"] && NSWorkspace.shared.frontmostApplication == other, "dictation stole focus, typed into the old app, or lost the transcript")
let late = Target(user), h3 = Harness(); late.deferred = true; h3.dictateSelection = late; NSWorkspace.shared.frontmostApplication = user
h3.insertDictation("late"); h3.dictateID += 1; h3.dictating = false; late.pending?()
precondition(late.received.isEmpty, "cancelled dictation replaced the selection")
print("dictation target safety ok")
'''
        self.assertIn('dictation target safety ok', run_swift(self, swift))

    def test_delivery_retries_only_a_proven_failure_and_keeps_failed_text(self):
        source = (ROOT / 'Atticus.swift').read_text()
        apply = source[source.index('    func apply(_ draft:'):source.index('    var value:', source.index('    func apply(_ draft:'))]
        insert = source[source.index('    func dictationDeliveryFailed('):source.index('    func typed(')]
        self.assertEqual(apply.count('.post(tap: .cghidEventTap)'), 1)
        self.assertEqual(apply.count('postToPid'), 1)   # one send, never both: per-process only while Atticus holds the keyboard
        self.assertIn('if NSApp.keyWindow == nil { e.post(tap: .cghidEventTap) } else { e.postToPid(', apply)
        self.assertIn('Saved to History', insert)
        self.assertNotIn('NSPasteboard', insert)   # dictation never leaves its words on the clipboard
        # Oct 21, 2026: a paste into an Electron chat box landed but its field read back unchanged, so Atticus said "Couldn't insert".
        swift = r'''import Foundation
func IsSecureEventInputEnabled() -> Bool { false }
struct AppRef: Equatable { let id: Int; var isTerminated: Bool { false }; var processIdentifier: Int32 { 1 }; func activate() {} }
final class NSWorkspace { static let shared = NSWorkspace(); var frontmostApplication: AppRef? }
enum NSApp { static var keyWindow: Int? { nil } }
enum CGEventTapLocation { case cghidEventTap }
struct CGEventFlags: OptionSet { let rawValue: Int; static let maskCommand = CGEventFlags(rawValue: 1) }
var posted = 0, writes = 0, restored = 0, focused = "box", editable = false, writeOK = true, readBack = TextSelection.Delivery.unchanged
final class CGEvent {
    var flags: CGEventFlags = []
    init?(keyboardEventSource: Any?, virtualKey: Int, keyDown: Bool) {}
    func post(tap: CGEventTapLocation) { posted += 1 }
    func postToPid(_ pid: Int32) { posted += 1 }
}
let kAXFocusedUIElementAttribute = "focused"
func AXUIElementCreateApplication(_ pid: Int32) -> String { "app" }
func AXUIElementSetMessagingTimeout(_ e: String, _ t: Double) {}
func axAttribute(_ e: String, _ k: String) -> String? { focused }
func CFEqual(_ a: String, _ b: String) -> Bool { a == b }
enum Hands { static func lease(_ n: String, wait: Bool) throws -> Int { 1 }; static func unlock(_ l: Int) {} }
func borrowPasteboard(_ s: String) -> (() -> Void)? { { restored += 1 } }
struct TextSelection {
    enum Delivery { case landed, unchanged, unknown }
    static let settle: TimeInterval = 0.05
    let focus = "box", app = AppRef(id: 1), range: CFRange? = CFRange(location: 0, length: 0)
    var keyboardOnly: Bool { false }
    var pastable: Bool { true }
    var value: String? { "" }
    func selectionMatches() -> Bool { true }
    func delivery(_ draft: String, _ before: String?) -> Delivery { readBack }
    func replace(_ draft: String) -> Bool { writes += 1; return writeOK }
''' + apply + r'''}
func deliver(write: Bool = false, _ read: TextSelection.Delivery, front: Int = 1, focus: String = "box") -> Bool? {
    posted = 0; writes = 0; restored = 0; editable = write; readBack = read; focused = focus
    NSWorkspace.shared.frontmostApplication = AppRef(id: front)
    var result: Bool?
    TextSelection().apply("hello", preserveFocus: true, valid: { NSWorkspace.shared.frontmostApplication == AppRef(id: 1) }) { result = $0 }
    let end = Date().addingTimeInterval(2)
    while result == nil && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.01)) }
    return result
}
precondition(deliver(.unchanged) == true && posted == 2 && restored == 1, "a posted paste whose field reads back unchanged was called a failure")
precondition(deliver(.unknown) == true && posted == 2 && restored == 1, "an unreadable field after a posted paste was called a failure")
precondition(deliver(.unchanged, front: 2) == false && posted == 0 && restored == 0, "pasted after the front app changed")
precondition(deliver(.unchanged, focus: "other") == false && posted == 0, "pasted after focus moved")
precondition(deliver(write: true, .landed) == true && writes == 1 && posted == 0, "a verified AX write was pasted too")
precondition(deliver(write: true, .unknown) == true && writes == 1 && posted == 0, "an unverifiable AX write was pasted again or called a failure")
precondition(deliver(write: true, .unchanged) == true && writes == 1 && posted == 2 && restored == 1, "a proven rejected AX write did not fall back to one paste")
print("single delivery fallback ok")
'''
        self.assertIn('single delivery fallback ok', run_swift(self, swift))

    def test_release_waits_for_final_words_on_the_accurate_model(self):
        # Oct 19, 2026: a 0.35 s dictation guard inserted volatile words ("I", "I saw some stuff like.") before the final result.
        source = (ROOT / 'Atticus.swift').read_text()
        at = source.index('    func stop()', source.index('final class App'))
        stop = source[at:source.index('    func applyReplacement(')]
        guard = stop[stop.index('Finalizing can hang'):]
        self.assertLess(stop.index('finalizeAndFinishThroughEndOfInput()'), stop.index('Finalizing can hang'))
        self.assertIn('DispatchQueue.main.asyncAfter(deadline: .now() + 2)', guard)
        self.assertNotIn('dictating ?', guard[:guard.index('once(false)')])
        module = source[source.index('    func speechModule('):source.index('    func prepareSpeech(')]
        self.assertIn('let tr = speechModule(dictate: dictating)', source)
        self.assertIn('SpeechTranscriber(locale: en, transcriptionOptions: [], reportingOptions: [.volatileResults]', module)
        self.assertIn('transcriptionOptions: [.punctuation], reportingOptions: [.volatileResults]', module)

    def test_whisper_feeds_raw_samples_and_skips_apple_speech(self):
        # Oct 28, 2026: AnalyzerInput traps inside Speech.framework on a plain 16 kHz Float32 buffer, so Whisper gets raw samples.
        source = (ROOT / 'Atticus.swift').read_text()
        start = source[source.index('    func start(dictate: Bool)'):source.index('    func heard(')]
        self.assertIn('guard whisper || dictate || SFSpeechRecognizer.authorizationStatus() == .authorized', start)
        self.assertLess(start.index('guard !whisper || Whisper.shared.ready'), start.index('listenID += 1'))
        self.assertIn('if whisper { pcm.append(out) } else { self?.speechInputs?.yield(AnalyzerInput(buffer: out)) }', start)
        self.assertIn('if whisper { pcm.append(buf) } else { self?.speechInputs?.yield(AnalyzerInput(buffer: buf)) }', start)
        self.assertIn('if whisper { whisperTick(listeningID) }', start)   # live words, and long segments close on a pause
        prepare = source[source.index('    func prepareSpeech()'):source.index('    var text =')]
        self.assertLess(prepare.index('Whisper.shared.warm(); return'), prepare.index('AssetInventory'))

    def test_whisper_results_from_an_old_listen_are_dropped(self):
        source = (ROOT / 'Atticus.swift').read_text()
        tick = source[source.index('    func whisperTick('):source.index('    func start(dictate: Bool)')]
        self.assertIn('guard let self, self.whisperAsk == ask else { return }', tick)
        self.assertIn('guard let self, self.listenID == listeningID else { return }', tick)
        self.assertIn('await prev?.value', tick)   # final passes stay in order
        stop = source[source.index('    func stop()', source.index('final class App')):source.index('    func applyReplacement(')]
        self.assertIn('engine.stop { inputs?.finishAll(); whisperFlush?() }', stop)
        self.assertIn('min(15, 4 + 0.15 * (whisperAudio.seconds + whisperQueued))', stop)
        self.assertLess(stop.index('if whisperListen'), stop.index('Finalizing can hang'))

    def test_whisper_settings_bridge(self):
        source = (ROOT / 'Atticus.swift').read_text()
        settings = source[source.index('final class SettingsWindow'):]
        for case in ['case "whisperDownload"', 'case "whisperCancel"', 'case "whisperDelete"', 'case "whisperInstall"']:
            self.assertIn(case, settings)
        self.assertIn('send("whisper", Whisper.shared.status())', settings[settings.index('    func push()'):])
        self.assertIn('brew install whisper.cpp', settings[settings.index('    func whisperInstall()'):])
        self.assertIn('if k == "whisperModel" { Whisper.shared.restart()', settings)

    def test_fn_and_modifier_only_shortcuts_use_flags_events(self):
        source = (ROOT / 'Atticus.swift').read_text()
        helpers = source[source.index('let atticusFnKey'):source.index('func configuredHotkey')]
        recorder = source[source.index('    // "Change shortcut"'):source.index('    func done(', source.index('    // "Change shortcut"'))]
        registration_start = source.index('var specialGlobalHotkeys')
        registration = source[registration_start:source.index('\nregisterHotkey()', registration_start)]
        self.assertIn('done((-2, shortcutModifiers(held)', recorder)
        self.assertIn('.function', recorder)
        self.assertIn('addGlobalMonitorForEvents', registration)
        self.assertIn('addLocalMonitorForEvents', registration)
        swift = 'import Cocoa\nimport Carbon\n' + helpers + r'''
let chord: NSEvent.ModifierFlags = [.function, .control]
precondition(shortcutModifiers(chord) & atticusFnKey != 0)
precondition(shortcutModifiers(chord) & controlKey != 0)
precondition(shortcutModifierLabel(chord) == "fn⌃")
print("fn modifier shortcut ok")
'''
        self.assertIn('fn modifier shortcut ok', run_swift(self, swift))

    def test_fn_alone_ignores_arrow_flags_and_yields_to_fn_key_chords(self):
        source = (ROOT / 'Atticus.swift').read_text()
        helpers = source[source.index('let atticusFnKey'):source.index('func configuredHotkey')]
        matcher = source[source.index('func specialHotkey'):source.index('func handleSpecialHotkeys')]
        swift = 'import Cocoa\nimport Carbon\n' + helpers + '\nvar specialGlobalHotkeys: Any?, specialLocalHotkeys: Any?, specialMainDown = false, specialDictateDown = false\n' + matcher + r'''
let fn = (code: -2, mods: atticusFnKey, flags: NSEvent.ModifierFlags.function)
func key(_ type: NSEvent.EventType, _ flags: NSEvent.ModifierFlags, _ code: UInt16) -> NSEvent {
    NSEvent.keyEvent(with: type, location: .zero, modifierFlags: flags, timestamp: 0, windowNumber: 0, context: nil,
                     characters: type == .flagsChanged ? "" : "x", charactersIgnoringModifiers: type == .flagsChanged ? "" : "x", isARepeat: false, keyCode: code)!
}
var down = false, fired: [Bool] = [], chords = 0
let arrow = key(.keyDown, [.function, .numericPad], 124), press = key(.flagsChanged, .function, 63), release = key(.flagsChanged, [], 63)
updateSpecialHotkey(arrow, fn, &down) { fired.append($0) }
updateSpecialHotkey(key(.keyUp, [.function, .numericPad], 124), fn, &down) { fired.append($0) }
precondition(fired.isEmpty && !down, "a plain arrow key (fn flag on its own event) started dictation")
updateSpecialHotkey(press, fn, &down) { fired.append($0) }
updateSpecialHotkey(key(.keyDown, .function, 51), fn, &down, chord: { chords += 1; return true }) { fired.append($0) }
updateSpecialHotkey(release, fn, &down) { fired.append($0) }
precondition(fired == [true] && chords == 1 && !down, "fn+Delete stayed a dictation press: \(fired)")
fired = []
updateSpecialHotkey(press, fn, &down) { fired.append($0) }
updateSpecialHotkey(key(.keyDown, .function, 51), fn, &down, chord: { false }) { fired.append($0) }
updateSpecialHotkey(release, fn, &down) { fired.append($0) }
precondition(fired == [true, false], "a press that already heard words lost its release: \(fired)")
print("fn alone ok")
'''
        self.assertIn('fn alone ok', run_swift(self, swift))
        chord = source[source.index('    func dictateChord()'):source.index('    func review(')]
        self.assertIn('text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty', chord)
        self.assertIn('!toggleTalk', chord)

    def test_paste_borrows_the_clipboard_and_restores_every_type(self):
        source = (ROOT / 'Atticus.swift').read_text()
        helper = source[source.index('func borrowPasteboard'):source.index('struct TextSelection {')]
        swift = 'import Cocoa\n' + helper + r'''
let pb = NSPasteboard(name: NSPasteboard.Name("atticus-test-" + UUID().uuidString)), custom = NSPasteboard.PasteboardType("com.example.private")
let transient = NSPasteboard.PasteboardType("org.nspasteboard.TransientType")
func snapshot() -> [[String: Data]] { (pb.pasteboardItems ?? []).map { i in Dictionary(uniqueKeysWithValues: i.types.compactMap { t in i.data(forType: t).map { (t.rawValue, $0) } }) } }
let a = NSPasteboardItem(); a.setString("user copy", forType: .string); a.setData(Data("{\\rtf1 user}".utf8), forType: .rtf); a.setData(Data([1, 2, 3]), forType: custom)
let b = NSPasteboardItem(); b.setString("second item", forType: .string)
pb.clearContents(); pb.writeObjects([a, b]); let before = snapshot()
let restore = borrowPasteboard("dictated words", pb)!
precondition(pb.string(forType: .string) == "dictated words" && pb.types?.contains(transient) == true, "the paste text was not on the clipboard, or not marked transient")
restore()
precondition(snapshot() == before, "the user's clipboard (every item and type) did not come back")
precondition(!snapshot().contains { $0.values.contains(Data("dictated words".utf8)) }, "dictated text stayed on the clipboard")
pb.clearContents(); let restoreEmpty = borrowPasteboard("dictated words", pb)!; restoreEmpty()
precondition((pb.pasteboardItems ?? []).isEmpty, "an empty clipboard kept the dictated text")
let c = NSPasteboardItem(); c.setString("user copy", forType: .string); pb.clearContents(); pb.writeObjects([c])
let late = borrowPasteboard("dictated words", pb)!
pb.clearContents(); pb.setString("copied meanwhile", forType: .string); late()
precondition(pb.string(forType: .string) == "copied meanwhile", "a newer copy was clobbered")
pb.releaseGlobally()
print("clipboard borrow ok")
'''
        self.assertIn('clipboard borrow ok', run_swift(self, swift))
        for name in ('    func apply(_ draft:',):
            body = source[source.index(name):source.index('    var value:', source.index(name))]
            self.assertIn('borrowPasteboard(draft)', body)
            self.assertNotIn('clearContents', body)

    def test_globe_key_conflict_only_for_fn_alone(self):
        source = (ROOT / 'Atticus.swift').read_text()
        check = source[source.index('func globeKeyTaken()'):source.index('func transcriptKey(')]
        self.assertIn('"AppleFnUsageType"', check)
        self.assertIn('h.code < 0, h.mods == atticusFnKey', check)
        self.assertIn('?? 1) != 0', check)   # unset is the system's own action, not Do Nothing
        self.assertIn('"globeTaken": globeKeyTaken()', source[source.index('    func push()', source.index('final class SettingsWindow')):])
        self.assertIn('case "globeKey"', source)

    def test_overlay_states_follow_release_done_fallback_fail_and_cancel(self):
        source = (ROOT / 'Atticus.swift').read_text()
        at = source.index('    func stop()', source.index('final class App'))
        release = next(l for l in source[at:source.index('    func applyReplacement(')].splitlines() if 'js("finishing"' in l)
        self.assertIn('cue("soundRelease")', release)   # a sound when the key lets go and cleanup starts
        level = next(l for l in source[source.index('        let onBuffer:'):at].splitlines() if 'js("level"' in l)
        self.assertIn('engine.isRunning == true', level)
        escape = source[source.index('    func escape()'):source.index('    func hush()')]
        self.assertLess(escape.index('if dictating { return cancel() }'), escape.index('if engine.isRunning'))
        delivery = source[source.index('    func dictationDeliveryFailed('):source.index('    func typed(')]
        cancel = source[source.index('    func cancel()'):source.index('    // ✕ also ends')]
        self.assertNotIn('NSPasteboard', delivery)
        swift = r'''import Foundation
struct Prefs { static var on: Set<String> = ["dictateHistory"]; static func bool(_ key: String) -> Bool { on.contains(key) } }
enum DictationData { static func fixed(_ text: String) -> String { text } }
final class AppRef: Equatable { static func == (a: AppRef, b: AppRef) -> Bool { a === b } }
final class NSWorkspace { static let shared = NSWorkspace(); var frontmostApplication: AppRef? }
var saves = true, saved: [String] = [], pasteHotkeyRegistered = true
final class Target {
    let app: AppRef; var received: [String] = [], deferred = false, pending: (() -> Void)?
    init(_ app: AppRef) { self.app = app }
    func apply(_ draft: String, preserveFocus: Bool = false, valid: @escaping () -> Bool, done: @escaping (Bool) -> Void) {
        let work = { [self] in let ok = valid(); if ok { received.append(draft) }; done(ok) }
        if deferred { pending = work } else { work() }
    }
}
final class Harness {
    var dictateSelection: Target?, busy = false, dictating = true, dictateID = 1, dictateCleanup = false
    var dictationAppName = "App", lastDictation: String?
    func saveDictation(_ value: String, appName: String) -> Bool { if saves { saved.append(value) }; return saves }
    var log: [String] = [], hides: [Double] = [], words: [String] = []
    func cue(_ value: String) {}
    func hide(after s: Double) { hides.append(s) }
    func js(_ call: String, _ arg: Any? = nil) {
        if let d = arg as? [String: Any] { log.append("\(call) \(d["text"]!) \(d["ok"]!)"); if let w = d["words"] as? String { words.append(w) } } else { log.append("\(call) \(arg as? String ?? "")") }
    }
    func prepareDictation(_ value: String, target: Target) -> () -> Void { {} }
    func recordDictationEvent(_ insert: String) {}
    func hush() { dictating = false; dictateID += 1; busy = false }
    func shush() {}
    func close(clear: Bool) { log.append("close"); hush() }
    func release() { busy = true
''' + release + '\n    }\n' + delivery + cancel + r'''}
let user = AppRef(); NSWorkspace.shared.frontmostApplication = user
let done = Harness(); done.dictateSelection = Target(user); done.release(); done.insertDictation("hi")
precondition(done.log == ["finishing ", "dictated  true"] && done.hides == [0.8], "success said something or did not hold its check: \(done.log)")
let clean = Harness(); clean.dictateCleanup = true; clean.release()
precondition(clean.log == ["finishing Cleaning up…"], "Clean up mode did not label its wait")
let fallback = Harness(); fallback.release(); fallback.insertDictation("keep me safe")
precondition(fallback.log == ["finishing ", "dictated No text field. Press ⌃⌘V to paste it. false"] && saved == ["keep me safe"] && fallback.hides == [6], "fallback: \(fallback.log)")
precondition(fallback.lastDictation == "keep me safe", "⌃⌘V would not paste the words that failed to insert")
let moved = Harness(); moved.dictateSelection = Target(user); moved.release(); NSWorkspace.shared.frontmostApplication = AppRef(); moved.insertDictation("switched away")
NSWorkspace.shared.frontmostApplication = user
precondition(moved.log == ["finishing ", "dictated Couldn’t insert. Press ⌃⌘V to paste it. false"], "a failed insert into a field said nothing was selected: \(moved.log)")
saves = false
let fail = Harness(); fail.release(); fail.insertDictation("keep me")
precondition(fail.log == ["finishing ", "dictated No text field. Press ⌃⌘V to paste it. false"] && fail.hides.isEmpty, "unsaved words faded away: \(fail.log)")
saves = true; Prefs.on = []; saved = []
let off = Harness(); off.release(); off.insertDictation("history off")
precondition(off.log == ["finishing ", "dictated No text field. Press ⌃⌘V to paste it. false"] && off.hides.isEmpty && saved.isEmpty, "History off: \(off.log)")
precondition(off.words == ["history off"] && fallback.words.isEmpty, "unsaved words cannot be copied from the pill")
Prefs.on = ["dictateHistory"]; pasteHotkeyRegistered = false   // another app (Willow Voice) holds ⌃⌘V
let taken = Harness(); taken.dictateSelection = Target(user); NSWorkspace.shared.frontmostApplication = AppRef(); taken.insertDictation("raw words")
NSWorkspace.shared.frontmostApplication = user
precondition(taken.log == ["dictated Couldn’t insert. Saved to History. false"] && saved == ["raw words"], "a shortcut Atticus does not own was offered: \(taken.log)")
pasteHotkeyRegistered = true
let late = Target(user); late.deferred = true
let cancelled = Harness(); cancelled.dictateSelection = late; cancelled.release(); cancelled.insertDictation("never"); cancelled.cancel(); late.pending?()
precondition(cancelled.log == ["finishing ", "close"] && late.received.isEmpty && cancelled.hides.isEmpty, "cancel: \(cancelled.log)")
print("dictation states ok")
'''
        self.assertIn('dictation states ok', run_swift(self, swift))


    def test_pill_over_a_box_that_must_stay_gives_the_box_back(self):
        # A pinned, placed or drawing-holding box blocked hide(), so the pill sat on its green check and hid the answer.
        source = (ROOT / 'Atticus.swift').read_text()
        hide = source[source.index('    func hide(after s: Double)'):source.index('    func defaultKey(')]
        swift = r'''import Foundation
final class Ctx { var duration = 0.0 }
enum NSAnimationContext { static func runAnimationGroup(_ a: (Ctx) -> Void, completionHandler: (() -> Void)?) { a(Ctx()); completionHandler?() } }
final class Panel { var alphaValue = 1.0; func animator() -> Panel { self } }
final class Flag { var active = false, hasInput = false, holds = false, isRunning = false }
final class Harness {
    var gen = 1, busy = false, hovering = false, pinned = false, stuck = false, composing = false, pillOn = true, dictating = false
    let engine = Flag(), mini = Flag(), drawing = Flag(), panel = Panel(); var ringGone: Int?, voice: Flag?
    var log: [String] = []
    func pill(_ on: Bool) { pillOn = on; log.append("pill \(on)") }
    func gone() { log.append("gone") }
''' + hide + r'''}
func settle() { RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
let pinned = Harness(); pinned.pinned = true; pinned.hide(after: 0); settle()
precondition(pinned.log == ["pill false"], "a pinned box kept the pill: \(pinned.log)")
let drawn = Harness(); drawn.drawing.active = true; drawn.hide(after: 0); settle()
precondition(drawn.log == ["pill false"], "a drawing kept the pill: \(drawn.log)")
let plain = Harness(); plain.hide(after: 0); settle()
precondition(plain.log == ["gone"], "a free pill did not fade: \(plain.log)")
let hover = Harness(); hover.pinned = true; hover.hovering = true; hover.hide(after: 0); settle()
precondition(hover.log.isEmpty, "a hovered pill changed: \(hover.log)")
let box = Harness(); box.pillOn = false; box.pinned = true; box.hide(after: 0); settle()
precondition(box.log.isEmpty, "a pinned box changed: \(box.log)")
print("pill gives the box back")
'''
        self.assertIn('pill gives the box back', run_swift(self, swift))


@unittest.skipUnless(shutil.which('node'), 'Node runs the overlay state check')
class DictationOverlayTests(unittest.TestCase):
    page = (ROOT / 'ui' / 'ui.html').read_text()

    def test_pill_goes_from_wave_to_working_orb_to_check_or_one_line(self):
        page = self.page
        helper = page[page.index('  const pill = '):page.index('\n  };\n', page.index('  const pill = ')) + 5]
        methods = page[page.index('    finishing(label)'):page.index('    learned(word)')]
        self.assertIn("if (document.body.classList.contains('dictate')) return window.ui.dictated({ text: s });", page)
        script = r'''
const classes = new Set(), body = { classList: { add: (...c) => c.forEach(x => classes.add(x)), remove: (...c) => c.forEach(x => classes.delete(x)), contains: c => classes.has(c) } };
const document = { body, createElement: () => ({}) }, dn = { className: '', textContent: '', kids: [], append(...a) { this.kids.push(...a); } };
let states = [], fits = 0, listening = true, boost = 2;
const $ = id => id === 'dn' ? dn : { style: {} }, setState = s => states.push(s), fit = () => { fits++; }, post = () => {};
''' + helper + 'const ui = {\n' + methods + r'''};
const fail = m => { console.error(m); process.exit(1); }, state = () => ['finishing', 'done', 'said'].filter(c => classes.has(c)).join();
classes.add('dictate', 'hearing', 'locked');
ui.finishing('Cleaning up…');
if (state() !== 'finishing' || classes.has('hearing') || classes.has('locked') || states.at(-1) !== 'solving' || dn.textContent !== 'Cleaning up…' || !fits) fail('release did not fold into the working orb: ' + state());
ui.dictated({ text: '', ok: true });
if (state() !== 'done' || states.at(-1) !== 'breathing' || dn.textContent !== 'Inserted') fail('landing did not end on the check: ' + state());
ui.dictated({ text: 'Nothing selected to insert — saved to History.', ok: false });
if (state() !== 'said' || dn.className !== 'dn' || dn.textContent !== 'Nothing selected to insert — saved to History.') fail('nothing to insert into was not one line');
ui.finishing('');
if (state() !== 'finishing' || dn.textContent) fail('a new release kept the last line');
'''
        result = subprocess.run(['node', '--input-type=module'], input=script, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dictation_leaves_the_boxs_last_answer_current(self):
        # Oct 20, 2026: a dictation's hidden turn marked the box's answer old (grey) though no new ask happened
        page = self.page
        helper = page[page.index('  const dictateMode ='):page.index('\n  };', page.index('  const dictateMode =')) + 5]
        methods = page[page.index('    dictate(on) {'):page.index('    locked(on)')] + page[page.index('    listen(mode) {'):page.index('    level(v) {')]
        script = r'''
const set = () => { const s = new Set(); return { add: (...c) => c.forEach(x => s.add(x)), remove: (...c) => c.forEach(x => s.delete(x)), toggle: (c, on) => on ? s.add(c) : s.delete(c), contains: c => s.has(c) }; };
const kids = [], thread = { children: kids, get firstElementChild() { return kids[0]; }, querySelectorAll: q => q === '.turn.dict' ? kids.filter(k => k.className.split(' ').includes('dict')) : [], append: d => kids.push(d) };
const node = () => { const n = { classList: set(), className: '', remove: () => kids.splice(kids.indexOf(n), 1), prepend() {}, firstChild: { classList: set() } }; return n; };
const document = { body: { classList: set() }, createElement: node }, card = { classList: set() };
const $ = id => id === 'thread' ? thread : id === 'card' ? card : { children: [], value: '' };
const miniClear = () => {}, clockStop = () => {}, comp = () => {}, markShot = () => '', setState = () => {}, status = () => {}, fit = () => {}, pill = () => {};
let hover, listening, working, boost, atBottom;
''' + helper + r'''
const ui = {
''' + methods + r'''};
const answer = node(); kids.push(answer);
ui.dictate(true); ui.listen('dict'); ui.dictate(false);
if (kids.length !== 1 || kids[0] !== answer) process.exit(console.error('the dictation turn stayed in the box') || 1);
if (answer.classList.contains('old')) process.exit(console.error('a dictation greyed out the last answer') || 1);
ui.listen();
if (!answer.classList.contains('old')) process.exit(console.error('a real ask no longer marks the last answer old') || 1);
'''
        result = subprocess.run(['node', '--input-type=module'], input=script, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pill_morphs_with_transform_and_opacity_and_cross_fades_under_reduce_motion(self):
        page, source = self.page, (ROOT / 'Atticus.swift').read_text()
        for name, props in (('morph', {'opacity', 'transform'}), ('fade', {'opacity'})):
            frames = re.search(r'@keyframes ' + name + r' \{(.*?)\}\s*\}?\n', page, re.S).group(1)
            self.assertEqual(set(re.findall(r'([a-z-]+):', frames)), props, name)
        reduce = page[page.index('@media (prefers-reduced-motion: reduce)'):page.index('</style>')]
        self.assertIn('animation: none !important', reduce)
        self.assertIn('body.dictate #orb { animation: fade', reduce)
        self.assertIn('body.dictate :is(#check, .dn) { animation: fade', reduce)
        sizing = source[source.index('let size = ((m.body as? [NSNumber])'):source.index('    func js(_ call: String')]
        self.assertIn('!NSWorkspace.shared.accessibilityDisplayShouldReduceMotion', sizing)   # Reduce Motion: the panel just takes its size

    def test_locked_pill_wears_a_ring_that_fades_and_respects_reduce_motion(self):
        page = self.page
        ring = re.search(r'body\.dictate::after \{(.*?)\}', page, re.S).group(1)
        self.assertIn('opacity: 0', ring)
        self.assertIn('transition: opacity', ring)
        self.assertIn('pointer-events: none', ring)
        self.assertIn('255,159,10', ring)   # the overlay's orange (Full access, attention)
        self.assertIn('body.dictate.locked::after { opacity: 1; }', page)
        self.assertIn("locked(on) { document.body.classList.toggle('locked', !!on); fit(false); }", page)   # the pill makes room for the lock
        reduce = page[page.index('@media (prefers-reduced-motion: reduce)'):page.index('</style>')]
        self.assertIn('transition: none !important', reduce)   # Reduce Motion: the ring just appears

    def test_pill_is_sized_by_the_page_and_shows_no_transcript_or_divider(self):
        # Oct 20, 2026: the pill had empty space between the wave and the lock, live words, and a line at finish
        # (the thread's .turn + .turn divider on a later dictation, and a shimmer swept across the words).
        page, source = self.page, (ROOT / 'Atticus.swift').read_text()
        self.assertIn("document.body.classList.contains('dictate') ? [card.offsetWidth, card.offsetHeight] : card.offsetHeight", page)
        card = re.search(r'body\.dictate #card \{(.*?)\}', page).group(1)
        self.assertIn('width: max-content', card)
        self.assertIn('body.dictate :is(#thread, #comp', page)   # no words, no turn dividers in the pill
        self.assertNotIn('.q.finishing', page)
        # Oct 21, 2026: the orb (in #head) was hidden while listening and on the check; only #head's other parts may go
        hidden = re.search(r'body\.dictate #head \{ height: auto; \} ([^{]*)\{ display: none; \}', page).group(1)
        self.assertTrue(all('#head >' in s for s in hidden.split(', ') if '#head' in s), hidden)
        sizing = source[source.index('let size = ((m.body as? [NSNumber])'):source.index('    func js(_ call: String')]
        self.assertIn('size.count == 2 && pillOn', sizing)   # a late pill size never narrows the box
        pill = source[source.index('    func pill(_ on: Bool)'):source.index('    func allow(_ ok: Bool)')]
        self.assertIn('pillOn = on', pill)
        self.assertNotIn('280', pill)
        heard = source[source.index('    func heard(_ now: String)'):]
        self.assertIn('if dictating { scheduleDictateAhead(); return }', heard)
        self.assertIn('self?.startDictateAhead(early: true)', heard)
        self.assertIn('!early || dictateAheadRuns < 2', heard)
        insert = source[source.index('    func insertDictation('):source.index('    func typed(')]
        self.assertIn('cue("soundDone"); js("dictated", ["text": "", "ok": true]); hide(after: 0.8)', insert)

if __name__ == '__main__':
    unittest.main()
