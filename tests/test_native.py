"""Run the actual live-worker methods headlessly, with fake actions and scratch state."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]


def harness(root):
    source = (ROOT / 'Atticus.swift').read_text()
    methods = source[source.index('    func cancelFast()'):source.index('    func stop()', source.index('    func cancelFast()'))]
    key = source[source.index('func transcriptKey('):source.index('final class SpeechInputs')]
    worker = root / 'worker.py'
    worker.write_text('''import os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import atticus
if os.environ.get('BENCH') == '1':
    atticus.licensed = lambda: True
    atticus.ping = lambda: None
    atticus.start_claude = lambda: None
    atticus.look = lambda: []
    atticus.app_named = lambda _: 'Spotify'
    def action(*args, **kwargs):
        Path(os.environ['MARKER']).write_text(str(time.time()))
        return type('Result', (), {'returncode': 0})()
    atticus.subprocess.run = action
    sys.argv = ['atticus.py'] + sys.argv[2:]
    atticus.main()
else:
    time.sleep(float(os.environ.get('DELAY', '.1')))
    Path(os.environ['MARKER']).write_text('action')
    print('x' * int(os.environ.get('FLOOD', '0')))
    print('✓ ' + sys.argv[-1], flush=True)
''')
    swift = root / 'native.swift'
    swift.write_text('''import Foundation
var delay = "0.1", flood = "0", bench = false
let root = CommandLine.arguments[1], repo = CommandLine.arguments[2], python = CommandLine.arguments[3]
struct Prefs { static var live = true; static func bool(_ k: String) -> Bool { k != "live" || live } }
final class Engine { var isRunning = true }
final class DrawingStub { var hasInput = false }
func py(_ args: [String], _ extra: [String: String] = [:]) -> Process {
    let p = Process(); p.executableURL = URL(fileURLWithPath: python)
    p.arguments = [root + "/worker.py", repo] + args
    p.environment = ProcessInfo.processInfo.environment.merging(extra) { $1 }
    p.environment?["ATTICUS_DIR"] = root
    p.environment?["DELAY"] = delay; p.environment?["FLOOD"] = flood
    p.environment?["BENCH"] = bench ? "1" : "0"; p.environment?["MARKER"] = root + "/marker"
    return p
}
''' + key + '''
final class Harness {
    var consumed = 0, fastBusy = false, liveRevised = false, consumedText = "", targetScreen = "Fixture display", mine = "Notes", text = "open Spotify"
    var fastProc: Process?, proc: Process?, did: [String] = []
    var busy = false, ahead = ""
    let drawing = DrawingStub()
    let engine = Engine()
    func words() -> [Substring] { text.split(separator: " ") }
    func js(_ name: String, _ text: String) {}
''' + methods + '''}
func pump(_ seconds: Double) {
    let end = Date().addingTimeInterval(seconds)
    while Date() < end { RunLoop.current.run(until: Date().addingTimeInterval(0.005)) }
}
let marker = root + "/marker"
func clear() { try? FileManager.default.removeItem(atPath: marker) }
func waitAction() {
    let end = Date().addingTimeInterval(3)
    while !FileManager.default.fileExists(atPath: marker) && Date() < end { pump(0.005) }
    precondition(FileManager.default.fileExists(atPath: marker), "worker never acted")
}
func waitIdle(_ h: Harness) {
    let end = Date().addingTimeInterval(3)
    while h.fastBusy && Date() < end { pump(0.005) }
    precondition(!h.fastBusy, "worker never drained")
}
if CommandLine.arguments.contains("--benchmark") {
    bench = true
    var on: [Double] = [], off: [Double] = []
    for _ in 0..<20 {
        clear(); Prefs.live = true
        let h = Harness(); h.tryFast()
        pump(0.25) // phrase recognized 250 ms before release; no speech finalization delay
        let release = Date().timeIntervalSince1970
        waitAction(); on.append((Double(try! String(contentsOfFile: marker, encoding: .utf8))! - release) * 1000)
        pump(0.05)
        clear(); Prefs.live = false
        let p = py(["--wait"]), input = Pipe(), output = Pipe()
        p.standardInput = input; p.standardOutput = output
        let commit = root + "/commit"; try? FileManager.default.removeItem(atPath: commit)
        p.environment?["ATTICUS_COMMIT"] = commit
        try! p.run(); pump(0.25)
        let released = Date().timeIntervalSince1970
        try! "go".write(toFile: commit, atomically: true, encoding: .utf8)
        try! input.fileHandleForWriting.write(contentsOf: Data("Notes\\topen Spotify\\n".utf8))
        try! input.fileHandleForWriting.close()
        waitAction(); off.append((Double(try! String(contentsOfFile: marker, encoding: .utf8))! - released) * 1000)
        _ = output.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
    }
    func report(_ name: String, _ values: [Double]) {
        let s = values.sorted(); print("\\(name): n=\\(s.count), median=\\(s[10]) ms, p95=\\(s[18]) ms")
    }
    report("live on", on); report("live off", off)
} else {
    clear(); delay = "0.4"
    let h = Harness(); h.tryFast(); precondition(h.fastBusy)
    h.cancelFast(); h.text = "new request"; delay = "0.05"; h.tryFast(); waitIdle(h)
    precondition(h.did == ["new request"] && !h.fastBusy, "cancelled result contaminated new request")
    clear(); let cancelled = Harness(); cancelled.tryFast(); cancelled.cancelFast(); pump(0.2)
    precondition(!FileManager.default.fileExists(atPath: marker), "action survived cancellation")
    let revised = Harness(); revised.tryFast(); revised.text = "open Notes"; waitIdle(revised)
    precondition(revised.liveRevised, "revised transcript was consumed")
    let finalizing = Harness(); finalizing.busy = true; finalizing.ahead = "old words"; finalizing.engine.isRunning = false
    finalizing.dropAhead(); precondition(finalizing.busy && finalizing.ahead.isEmpty, "final transcript correction abandoned request")
    let disabled = Harness(); Prefs.live = false; disabled.tryFast(); precondition(disabled.fastProc == nil)
    Prefs.live = true; flood = "1000000"; let large = Harness(); large.tryFast(); waitIdle(large)
    precondition(!large.fastBusy, "full stdout blocked worker")
    print("native live-worker regressions ok")
}
''')
    binary = root / 'native'
    compiled = subprocess.run(['swiftc', '-O', str(swift), '-o', str(binary)], capture_output=True, text=True)
    if compiled.returncode:
        raise AssertionError(compiled.stderr)
    return [str(binary), str(root), str(ROOT), sys.executable]


@unittest.skipUnless(sys.platform == 'darwin', 'macOS Swift worker regression')
class NativeTests(unittest.TestCase):
    def test_memory_receipts_fall_through_when_drawing_parser_rejects_them(self):
        source = (ROOT/'Atticus.swift').read_text()
        branch = source.split('                    if line.hasPrefix("✎ ") {', 1)[1].split('                    if line.hasPrefix("@ ")', 1)[0]
        out = run_swift(self, '''import Cocoa
final class Prefs { static func bool(_ key: String) -> Bool { true } }
final class Drawing {
    var focus: CGRect?
    func receive(_ data: Data) -> Bool { String(decoding: data, as: UTF8.self).contains("steps") }
}
func lead(from: CGRect, to: CGRect) {}
final class Harness {
    let drawing = Drawing(), panel = NSPanel()
    func shush() { print("guide") }
    func js(_ call: String, _ value: String) { print(value) }
    func feed(_ lines: [String]) {
        var guided = false
        for line in lines {
            if line.hasPrefix("✎ ") {
''' + branch + '''
        }
        print(guided)
    }
}
Harness().feed(["✎ {\\"remembered\\":[\\"Use concise answers\\"]}", "✎ {\\"steps\\":[]}"])
''')
        self.assertEqual(out.splitlines(), ['✎ {"remembered":["Use concise answers"]}', 'guide', 'true'])

    def test_page_calls_skip_values_json_cannot_hold(self):
        source = (ROOT / 'Atticus.swift').read_text()
        bridge = source[source.index('// Call a page function'):source.index('// Load ui/')]
        out = run_swift(self, 'import Foundation\nclass WKWebView { func evaluateJavaScript(_ s: String) { print(s) } }\n' + bridge +
                        'let w = WKWebView()\ncallJS(w, "ui.a", [])\ncallJS(w, "ui.b", ["x/y"])\ncallJS(w, "ui.c", [NSValue(range: NSRange(location: 0, length: 1))])\n')
        self.assertEqual(out.splitlines(), ['ui.a(...[])', 'ui.b(...["x\\/y"])'])

    def test_voice_focus_becomes_the_background_guard_target(self):
        source = (ROOT / 'Atticus.swift').read_text()
        start = source.index('    static func focusGuardActive')
        policy = source[start:source.index('    let recent', start)]
        start = source.index('    static var workInFront:')
        work = source[start:source.index('    static func bounds(', start)]
        start = source.index('        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didActivateApplicationNotification')
        observer = source[source.index('            let now = Date()', start):source.index('        NSEvent.addGlobalMonitor', start)].rsplit('        }', 1)[0]
        swift = '''import Foundation
enum Prefs {
    static var mode = "back"
    static func str(_ key: String) -> String { mode }
}
final class Target: Equatable {
    let processIdentifier: Int32
    var localizedName: String? { String(processIdentifier) }
    var isTerminated = false, hidden = false
    init(_ pid: Int32) { processIdentifier = pid }
    func hide() { hidden = true }
    static func == (a: Target, b: Target) -> Bool { a.processIdentifier == b.processIdentifier }
}
enum MiniScreen {
    static var restored: Int32?
    static func activate(_ pid: Int32) { restored = pid }
''' + work + '''
}
typealias NSRunningApplication = Target
enum NSWorkspace { static var shared = Workspace() }
struct Workspace { var frontmostApplication: Target? = Target(1) }
struct DistributedNotificationCenter {
    static func `default`() -> Self { Self() }
    func postNotificationName(_ name: Notification.Name, object: Any?, deliverImmediately: Bool) {}
}
final class Harness {
    var busy = true, focusFree = false, allowUserApp = false
    var engine = (isRunning: false, unused: false), agentsUI = (hasLive: false, unused: false)
    var guardUntil = Date.distantPast, allowUntil = Date().addingTimeInterval(3), userSwitch = Date.distantPast
    var userApp: Target? = Target(1), mine = "1", hiddenAtStart: Set<Int32> = [5]
    static var switched = false
    static func userJustSwitched() -> Bool { switched }   // stands in for the hardware input check
''' + policy + '''
    func activated(_ a: Target) {
''' + observer + '''
    }
}
let h = Harness(), chosen = Target(2), temporary = Target(3)
h.allowUserApp = true   // an explicit voice focus request, not a physical click
h.activated(chosen)
precondition(h.userApp == chosen && h.mine == "2", "voice-selected app was not remembered")
h.allowUserApp = false
h.activated(temporary)
precondition(h.userApp == chosen, "temporary automation raise replaced the user's app")
h.allowUntil = .distantPast
h.activated(Target(1))   // a later background action in the previously used app
precondition(MiniScreen.restored == chosen.processIdentifier, "background action restored the stale app")
let unhid = Target(5), shown = Target(6)
h.activated(unhid); h.activated(shown)
precondition(unhid.hidden && !shown.hidden, "an app hidden before the task stayed visible after the guard sent it back")
MiniScreen.restored = nil
Harness.switched = true   // ⌘-Tab or a swipe: no click the global monitor sees, but real input
h.activated(Target(4))
precondition(MiniScreen.restored == nil && h.userApp == Target(4), "the guard pulled the user back after they switched apps")
Harness.switched = false
MiniScreen.work(temporary)
precondition(MiniScreen.restored == nil, "background mode raised a non-browser app")
setenv("ATTICUS_FOCUS_REQUESTED", "1", 1)
MiniScreen.work(temporary)
precondition(MiniScreen.restored == temporary.processIdentifier, "explicit focus in background mode was ignored")
unsetenv("ATTICUS_FOCUS_REQUESTED")
Prefs.mode = "front"
MiniScreen.work(temporary)
precondition(MiniScreen.restored == temporary.processIdentifier, "front mode did not raise a non-browser app")
MiniScreen.restored = nil
h.allowUntil = Date().addingTimeInterval(3)
h.activated(temporary)
precondition(MiniScreen.restored == nil && h.userApp == temporary, "front mode pushed the working app back")
Prefs.mode = "back"
h.allowUntil = .distantPast
h.busy = false
h.guardUntil = Date().addingTimeInterval(2)
h.activated(Target(7)); h.activated(Target(7))
precondition(MiniScreen.restored == temporary.processIdentifier && h.userApp == temporary, "repeated late activations replaced the return app")
h.focusFree = true
h.activated(Target(8))
precondition(h.userApp == Target(8), "an explicit focus request was not remembered")
h.focusFree = false
h.guardUntil = .distantPast
h.activated(Target(9))
precondition(h.userApp == Target(9), "idle app switching was blocked")
'''
        with tempfile.TemporaryDirectory() as path:
            file = Path(path) / 'focus.swift'; file.write_text(swift)
            binary = Path(path) / 'focus'
            compiled = subprocess.run(['swiftc', str(file), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            decisions = [line.split('Focus guard: ', 1)[1] for line in result.stderr.splitlines() if 'Focus guard: ' in line]
            self.assertEqual(len(decisions), 11)
            self.assertIn('app=2 target=1', decisions[0])   # log the target before remembering the activation
            self.assertTrue(decisions[0].endswith('result=remembered'))
            self.assertTrue(decisions[1].endswith('result=ignored'))
            self.assertIn('hardwareSwitch=true', decisions[5])
            self.assertTrue(decisions[5].endswith('result=remembered'))
            for line in decisions[7:9]:
                self.assertIn('app=7 target=3 busy=false recording=false tail=true', line)
                self.assertTrue(line.endswith('result=restore-requested'))   # a request, not proof of restored windows/Spaces
            self.assertIn('free=true', decisions[9])
            self.assertIn('tail=false', decisions[10])

    def test_focus_guard_covers_main_asks_and_fast_work(self):
        source = (ROOT / 'Atticus.swift').read_text()
        policy = source[source.index('    static func focusGuardActive'):source.index('    let recent', source.index('    static func focusGuardActive'))]
        swift = '''import Foundation
final class Harness {
''' + policy + '''
}
let now = Date()
precondition(!Harness.focusGuardActive(busy:false, recording:false, now:now, until:.distantPast, focusFree:false))
precondition(Harness.focusGuardActive(busy:true, recording:false, now:now, until:.distantPast, focusFree:false))
precondition(Harness.focusGuardActive(busy:false, recording:true, now:now, until:.distantPast, focusFree:false))
precondition(Harness.focusGuardActive(busy:false, recording:false, now:now, until:.distantFuture, focusFree:false))
precondition(!Harness.focusGuardActive(busy:true, recording:false, now:now, until:.distantPast, focusFree:true))
precondition(!Harness.focusGuardActive(busy:true, recording:false, now:now, until:.distantPast, focusFree:false, workInFront:true))   // In front: every app may come forward
precondition(!Harness.isUserApp(now:now, allowUntil:now.addingTimeInterval(3), userSwitch:.distantPast))   // hands raised Chrome
precondition(Harness.isUserApp(now:now, allowUntil:now.addingTimeInterval(3), userSwitch:now))   // the user clicked during the raise
precondition(Harness.isUserApp(now:now, allowUntil:.distantPast, userSwitch:.distantPast))
print("focus guard policy ok")
'''
        with tempfile.TemporaryDirectory() as path:
            file = Path(path) / 'focus.swift'; file.write_text(swift)
            binary = Path(path) / 'focus'
            compiled = subprocess.run(['swiftc', str(file), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_typing_requires_a_zero_length_caret(self):
        source = (ROOT / 'Atticus.swift').read_text()
        caret = source[source.index('    var caret: Bool'):source.index('    static func selectedRange',source.index('    var caret: Bool'))]
        swift = '''import Foundation
struct Harness { let text:String, range:CFRange?
''' + caret + '''
}
precondition(Harness(text:"",range:CFRange(location:2,length:0)).caret)
precondition(!Harness(text:" ",range:CFRange(location:2,length:1)).caret)
precondition(!Harness(text:"selected",range:CFRange(location:2,length:8)).caret)
print("caret safety ok")
'''
        with tempfile.TemporaryDirectory() as path:
            file = Path(path) / 'caret.swift'; file.write_text(swift)
            binary = Path(path) / 'caret'
            compiled = subprocess.run(['swiftc',str(file),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            result = subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_typed_box_prewarms_but_confirmation_stays_at_submit(self):
        source = (ROOT / 'Atticus.swift').read_text()
        branch = source[source.index('if !replying && Prefs.str("input") == "type"'):source.index('\n        toggleTalk', source.index('if !replying && Prefs.str("input") == "type"'))]
        self.assertIn('unwarm(); warm = spawn()', branch)
        run = source[source.index('    func run(_ t: String'):source.index('\n    }\n}', source.index('    func run(_ t: String'))]
        self.assertIn('try "go".write(toFile: commit', run)
        self.assertIn('var data = try JSONSerialization.data(withJSONObject:request)', run)
        self.assertLess(run.index('try "go".write(toFile: commit'), run.index('var data = try JSONSerialization.data(withJSONObject:request)'))

    def test_hidden_followups_keep_failed_and_successful_turns_for_five_minutes(self):
        source = (ROOT / 'Atticus.swift').read_text()
        start = source[source.index('    func start(dictate: Bool, quiet: Bool = false)'):source.index('    func heard(', source.index('    func start(dictate: Bool, quiet: Bool = false)'))]
        self.assertIn('Date().timeIntervalSince(lastDone) > 300', start)
        spawn = source.index('    func spawn()')
        completion = source[source.index('p.terminationHandler =', spawn):source.index('\n        do { try p.run()', spawn)]
        self.assertLess(completion.index('self.lastDone = Date()'), completion.index('if !self.answer.isEmpty'))

    def test_final_words_after_live_action_preserve_raw_remainder(self):
        source = (ROOT / 'Atticus.swift').read_text()
        finish = source[source.index('    func finish()', source.index('    func typed(')):source.index('    // atticus.py --wait, started')]
        swift = '''import Foundation
final class Engine { var isRunning = false }
final class Panel { func makeKey() {}; func makeFirstResponder(_ v: Int) {} }
final class DrawingStub { var active = false, advances = 0; func next() { advances += 1 } }
final class Harness {
    var quietFollowUp = false
    var handsFree = false, followUp = false
    var drawingReply = false; let drawing = DrawingStub()
    func typed(_ text: String, heard: Bool = false) { request = text }
    var busy = true, selectionPending = false, fastBusy = false, liveRevised = false, pinned = false, guardUntil = Date.distantPast
    var offerText: String?, text = "Fixture left, Other right", ahead = "", answer = ""
    var did = ["Fixture: left."], consumed = 2, stops = 0, web = 0
    var proc: Process?, aheadItem: DispatchWorkItem?, commit = "", lastDone = Date()
    let panel = Panel(), engine = Engine()
    var request = "", remaining: String?, delivered = ""
    func rest() -> String { text.split(separator:" ").dropFirst(consumed).joined(separator:" ") }
    func run(_ t: String, remaining: String? = nil) { request = t; self.remaining = remaining }
    func dropAhead() { ahead = "" }
    func unwarm() {}; func hush() {}; func hush(keepReply: Bool, keepWarm: Bool = false) {}; func cancel() {}; func hide(after: Double) {}
    func js(_ name: String, _ value: Any = "") {}; func cue(_ name: String) {}; func followUpSoon() {}
    func linger(_ n: Double) -> Double { n }
    func deliver(_ text: String) { delivered = text }
''' + finish + '''}
func transcriptKey(_ t: String) -> String { t.lowercased() }
let guide = Harness(); guide.offerText = "Original teaching request"; guide.text = "next"; guide.drawingReply = true; guide.finish()
precondition(guide.drawing.advances == 1 && guide.request.isEmpty && !guide.drawingReply,"Spoken next started another AI ask")
let changed = Harness(); changed.offerText = "Original teaching request"; changed.text = "Another question"; changed.drawingReply = true; changed.finish()
precondition(changed.request == "Another question","New ask was swallowed by the guide")
let partial = Harness(); partial.finish()
precondition(partial.request == partial.text && partial.remaining == "Other right")
let complete = Harness(); complete.consumed = 4; complete.finish()
precondition(complete.request.isEmpty && complete.delivered == "Fixture: left.")
let fresh = Harness(); fresh.did = []; fresh.consumed = 0; fresh.finish()
precondition(fresh.request == fresh.text && fresh.remaining == nil)
print("confirmed remainder regressions ok")
'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); file = root / 'finish.swift'; file.write_text(swift)
            binary = root / 'finish'
            compiled = subprocess.run(['swiftc', str(file), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
            self.assertIn('confirmed remainder regressions ok', result.stdout)

    def test_replace_checks_original_text_range_and_app(self):
        source = (ROOT / 'Atticus.swift').read_text()
        method = source[source.index('    var value: String?'):source.index('// Sees the mouse')]
        # Reuse the production method with fake AX writes; never address a real app.
        swift = """import Foundation
import CoreFoundation
let kAXSelectedTextAttribute = "selected"
let kAXValueAttribute = "value"
enum Status { case success, failure }
var currentText = "old", currentRange: CFRange? = CFRange(location: 3, length: 3), writes = 0
func axAttribute(_ element: Int, _ name: String) -> String? { currentText }
func AXUIElementSetAttributeValue(_ e: Int, _ name: CFString, _ text: CFString) -> Status { writes += 1; return .success }
final class FakeApp { var isTerminated = false }
struct Harness {
 let element = 1, app = FakeApp(), text = "old", range: CFRange? = CFRange(location: 3, length: 3)
 enum Delivery { case landed, unchanged, unknown }
 static func selectedRange(_ element: Int) -> CFRange? { currentRange }
 static func string(_ value: String?) -> String? { value }
""" + method + """
let h = Harness()
currentText = "abcdraftgh"
precondition(h.landed("draft","abcdefgh"))
currentText = "xxdraftxx"
precondition(!h.landed("draft","abcdefgh"))
currentText = "old"
precondition(h.replace("draft") && writes == 1)
currentText = "new"; precondition(!h.replace("draft") && writes == 1)
currentText = "old"; currentRange = CFRange(location: 4, length: 3)
precondition(!h.replace("draft") && writes == 1)
currentRange = nil; precondition(!h.replace("draft") && writes == 1)
currentRange = CFRange(location: 3, length: 3); h.app.isTerminated = true
precondition(!h.replace("draft") && writes == 1)
print("selection regressions ok")
"""
        with tempfile.TemporaryDirectory() as path:
            file = Path(path) / 'selection.swift'; file.write_text(swift)
            binary = Path(path) / 'selection'
            compiled = subprocess.run(['swiftc', str(file), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
            self.assertIn('selection regressions ok', result.stdout)

    def test_meeting_size_stays_on_small_and_secondary_displays(self):
        source = (ROOT / 'Atticus.swift').read_text()
        size = source[source.index('    func size(_ h: Double'):source.index('    func compact(', source.index('    func size(_ h: Double'))]
        swift = """import Cocoa
final class NSScreen {
 static var main: NSScreen? = NSScreen()
 var visibleFrame = NSRect(x: -800, y: 100, width: 600, height: 400)
}
final class NSWorkspace { static let shared = NSWorkspace(); var accessibilityDisplayShouldReduceMotion = true }
final class NSAnimationContext {
 var duration: Double = 0
 static var done: (() -> Void)?
 static func runAnimationGroup(_ changes: (NSAnimationContext) -> Void, completionHandler: @escaping () -> Void) { changes(NSAnimationContext()); done = completionHandler }
}
final class Panel {
 var screen = NSScreen.main, frame = NSRect(x: -552, y: 258, width: 340, height: 230)
 func setFrame(_ f: NSRect, display: Bool, animate: Bool) { frame = f }
 func setFrame(_ f: NSRect, display: Bool) { frame = f }
 func animator() -> Panel { self }
}
final class Harness { var panel: Panel? = Panel(); var running = true, generation = 0; var expanded = NSSize(width: 340, height: 650), minimized = false, resizing = false
 var reveals: [Int] = []; func js(_ name: String, _ value: Int) { if name == "settled" { reveals.append(value) } }
""" + size + """}
let h = Harness(), p = h.panel!
let top = p.frame.maxY
h.size(200); precondition(p.frame.maxY == top && p.frame.height == 200, "top edge moved")
h.size(200, reveal: 1); precondition(h.reveals == [1], "unchanged frame lost reveal")
h.size(210, reveal: 2); precondition(h.reveals == [1, 2], "Reduce Motion lost reveal")
NSWorkspace.shared.accessibilityDisplayShouldReduceMotion = false
h.size(220, reveal: 3); precondition(h.reveals == [1, 2], "text revealed during expansion")
NSAnimationContext.done!(); precondition(h.reveals == [1, 2, 3], "completion lost reveal")
h.size(230, reveal: 4); h.generation += 1; NSAnimationContext.done!(); precondition(h.reveals == [1, 2, 3], "cancelled animation revealed a new meeting")
NSWorkspace.shared.accessibilityDisplayShouldReduceMotion = true
h.size(0); precondition(p.frame.height == 376 && p.screen!.visibleFrame.contains(p.frame), "secondary display overflow")
h.resize(440, 500); precondition(p.frame.width == 440 && p.frame.height == 376, "resize ignored display limits")
h.minimized = true; h.size(44); precondition(p.frame.width == 116 && p.frame.height == 44, "compact size wrong")
h.minimized = false; h.size(0); precondition(p.frame.width == 440 && p.frame.height == 376, "restore forgot expanded size")
p.screen!.visibleFrame = NSRect(x: 0, y: 0, width: 300, height: 190)
h.size(200); precondition(p.frame.width == 276 && p.frame.height == 166 && p.screen!.visibleFrame.contains(p.frame), "small display overflow")
print("meeting size ok")
"""
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / 'size.swift'; file.write_text(swift)
            binary = Path(root) / 'size'
            compiled = subprocess.run(['swiftc', str(file), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_calendar_dismissal_and_updates_preserve_open_meeting(self):
        source = (ROOT / 'Atticus.swift').read_text()
        timer = source[source.index('    let g = meeting.generation', source.index('func checkCalendar()')):source.index('\n}', source.index('    let g = meeting.generation', source.index('func checkCalendar()')))]
        context = next(line for line in source.splitlines() if 'let context = [e.title' in line)
        idle = source[source.index('    static func restartWhenIdle()'):source.index('    static func schedule()')]
        swift = """import Foundation
final class Queue {
 var pending: [() -> Void] = []
 func asyncAfter(deadline: DispatchTime, execute work: @escaping () -> Void) { pending.append(work) }
}
enum DispatchQueue { static let main = Queue() }
final class Meeting {
 var generation = 1, running = false, nudge: Int? = 1, panel: Int? = 1, discards = 0
 func discard() { generation += 1; nudge = nil; panel = nil; discards += 1 }
}
let meeting = Meeting()
func scheduleNudge() {
""" + timer + """
}
struct Event { var title: String? = "Call", location: String? = "Room 2", url: URL? = URL(string: "https://meet.google.com/abc"), notes: String? }
let e = Event(), people = ["Dana"]
""" + context + """
precondition(context.contains("Room 2") && context.contains("https://meet.google.com/abc"), "calendar link/location lost")
scheduleNudge(); meeting.discard(); meeting.generation += 1; meeting.nudge = 2; meeting.panel = 2
DispatchQueue.main.pending.removeFirst()(); precondition(meeting.panel == 2, "old timer dismissed new nudge")
scheduleNudge(); DispatchQueue.main.pending.removeFirst()(); precondition(meeting.panel == nil, "current nudge did not dismiss")
final class Engine { var isRunning = false }
final class Voice { var isRunning = false }
final class App { var busy = false, engine = Engine(), voice: Voice? }
final class Window { var isKeyWindow = false }
final class Settings { var win: Window? }
struct Agents { var hasLive = false }
let app = App(), settings = Settings(), onboarding = Settings()
var agentsUI = Agents()
var restarts = 0
func relaunchSoon() { restarts += 1 }
enum Updater {
""" + idle + """}
meeting.panel = 1; Updater.restartWhenIdle(); precondition(restarts == 0, "update interrupted unsaved meeting")
meeting.panel = nil; DispatchQueue.main.pending.removeFirst()(); precondition(restarts == 1, "update never resumed")
agentsUI.hasLive = true; Updater.restartWhenIdle(); precondition(restarts == 1, "update interrupted a live agent")
agentsUI.hasLive = false; DispatchQueue.main.pending.removeFirst()(); precondition(restarts == 2, "update never resumed after agent")
print("calendar/update safety ok")
"""
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / 'calendar.swift'; file.write_text(swift)
            binary = Path(root) / 'calendar'
            compiled = subprocess.run(['swiftc', str(file), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_drawing_reply_preserves_click_start_through_reset(self):
        source = (ROOT / 'Atticus.swift').read_text()
        click = source[source.index('    func clickMicrophone('):source.index('    func wakeTick()')]
        start = source[source.index('    func start(dictate: Bool,'):source.index('        cancelFast(); noteHidden()', source.index('    func start(dictate: Bool,'))]
        reset = next(line for line in source.splitlines() if 'quietFollowUp = false; clickTalk = false;' in line)
        poll = next(line for line in source.splitlines() if 'if !toggleTalk && !clickTalk && !f.isEmpty' in line)
        typing = source[source.index('            if b["type"] != nil {'):source.index('            if let s = b["link"]')]
        run_swift(self, """import Foundation
struct Prefs { static func bool(_ key: String) -> Bool { false } }
func AXIsProcessTrusted() -> Bool { true }
func unpoint(_ notify: Bool) {}
struct NSEvent { static var modifierFlags: Set<Int> = [] }
final class Engine { var isRunning = false }
final class Drawing {
    var active = true, hasInput = false, holds = 0
    func clear() {}; func hold() { holds += 1 }
}
final class Mini { func reset() {} }
final class Harness {
    let drawing = Drawing(), engine = Engine(), mini = Mini()
    var handsFreeIdle = 0, drawingReply = false, retryOffer = false, askFile = "", replyAgent = "", agentCard = ""
    var focusFile = "/unused-fixture-focus", dictating = false, busy = false
    var quietFollowUp = false, clickTalk = false, toggleTalk = false, stops = 0
    var quiet: DispatchWorkItem?, offerText: String?, proc: Int?, text = ""
    var resets = 0, sends = 0
    func stopWake() {}; func pill(_ on: Bool) {}; func show() {}; func hide(after: Double) {}
    func js(_ name: String, _ value: Any? = nil) {}; func shush() {}
    func dismiss() { hush() }; func cancel() { hush() }
    func dictateShortcut(_ pressed: Bool) { stop() }
    func stopOfferInput() { hush() }
    func hush(keepReply: Bool = false) {
        resets += 1; engine.isRunning = false; busy = false
""" + reset + """
    }
""" + click + start + """
        engine.isRunning = true   // fake capture: no hardware, recognizer or workers
    }
    func poll() {
        let f: Set<Int> = [1]
        let t = Timer(timeInterval: 0.15, repeats: false) { _ in }
""" + poll + """
    }
    func stop() { sends += 1; engine.isRunning = false }
    func receive(_ b: [String: Int]) {
""" + typing + """
    }
}
let click = Harness(); click.clickMicrophone()
print("drawing reset=", click.resets, "clickTalk=", click.clickTalk); fflush(stdout)
click.poll()
precondition(click.clickTalk && click.engine.isRunning && click.sends == 0,
    "drawing reply lost clickTalk and key-state poll stopped fake capture")
precondition(click.resets == 1 && click.drawing.holds == 1 && click.drawingReply)
click.receive(["type": 1])
precondition(!click.engine.isRunning && !click.clickTalk, "typing did not interrupt click-started drawing reply")
let hold = Harness(); hold.start(dictate: false); hold.poll()
precondition(!hold.clickTalk && !hold.engine.isRunning && hold.sends == 1, "hold-to-talk no longer stops when keys are released")
let toggle = Harness(); toggle.start(dictate: false); toggle.toggleTalk = true; toggle.poll()
precondition(toggle.engine.isRunning && toggle.sends == 0, "key-state poll stopped toggle talk")
print("drawing reply input modes ok")
""")

    def test_shortcut_states_and_recording_limit(self):
        source = (ROOT / 'Atticus.swift').read_text()
        self.assertIn('"input": "voice", "talkMode": "hold"',source)
        self.assertIn('if !dictating && held > 60', source)
        start=source[source.index('    func start()',source.index('final class App')):source.index('        quietAudio.begin',source.index('    func start()',source.index('final class App')))]
        self.assertIn('if !replying && Prefs.str("input") == "type" && !clickTalk',start)
        self.assertIn('AVCaptureDevice.authorizationStatus(for: .audio) == .authorized',start)
        methods = source[source.index('    func shortcut('):source.index('    func review(')]
        methods += source[source.index('    func recordingLimit('):source.index('    func captureSelection()')]
        methods += source[source.index('    func stopOfferInput()'):source.index('    func dismiss()')]
        methods += source[source.index('    func escape()'):source.index('    func hush()')]
        at = source.index('    func stop()', source.index('final class App'))   # the App's stop, not the Mic class's
        stop = source[at:source.index('        let inputs = speechInputs', at)]
        swift = """import Foundation
struct Prefs { static var paused = false, toggle = false; static func bool(_ k: String) -> Bool { paused } }
final class MeetingStub { var running = false, focuses = 0; func focus() { focuses += 1 } }
let meeting = MeetingStub()
final class Engine { var isRunning = false, stopped = false; func stop() {isRunning=false; stopped=true} }
final class Input { var cancelled=false; func finish() {cancelled=true}; func cancel() {cancelled=true} }
final class Analyzer { func cancelAndFinishNow() async {} }
final class SpeechInputs { var finished=false; func finishAll() {finished=true} }
final class QuietAudio { func end(immediate: Bool = false) {} }
final class Panel { var isVisible = true; func makeKey() {}; func makeFirstResponder(_ value: Int) {} }
final class DrawingStub { var active = false, hasInput = false; func clear() { hasInput = false }; func clearInput() { hasInput = false } }
final class Harness {
    static var keysUp = Date(); func gone() {}; func unwarm() {}
    var quietFollowUp = false
    var handsFree = false, followUp = false
    func stopWake() {}
    var drawingReply = false; let drawing = DrawingStub()
    let engine = Engine(), panel = Panel(), quietAudio = QuietAudio()
    var askNeed: [String:Any] = [:]
""" + source[source.index('    var picking:'):source.index('\n', source.index('    var picking:'))] + """
    var retryOffer=false,offerText:String?,askFile="fixture-answer",agentCard="",listenID=0,stops=0
    var feed:Input?,reading:Input?,quiet:Input?,analyzer:Analyzer?,speechInputs:SpeechInputs?=SpeechInputs()
    var nextFeed:Input?,nextReading:Input?,nextAnalyzer:Analyzer?,nextSpeechInputID:Int?,nextSpeechSegment=0
    var shortcutDown = false, toggleTalk = false, clickTalk = false, busy = false, speaking = false
    var dictateShortcutDown = false, dictating = false, dictatePressed = Date.distantPast, dictateTap: DispatchWorkItem?
    var events: [String] = [], text = "hello", began = Date(), wasUp = false, web = 0
    func start() { events.append("start"); engine.isRunning = true; toggleTalk = Prefs.toggle }
    func startDictation() { events.append("dictate"); engine.isRunning = true; dictating = true; toggleTalk = false }
    func dictationDeliveryFailed(_ value: String) { events.append("copied"); busy = false }
    func cancel() { events.append("cancel"); hush(); shush() }
    func dismiss() { events.append("dismiss"); hush() }
    func shush() -> Bool { let was = speaking; speaking = false; if was { events.append("quiet") }; return was }
    func hush() { events.append("hush"); engine.isRunning = false; busy = false; toggleTalk = false; listenID += 1 }
    func close(clear: Bool) { events.append("close"); hush() }
    func review(_ text: String) { events.append("review"); hush() }
    func cue(_ text: String) {}
    func followUpSoon() {}
    func js(_ f: String, _ text: Any? = nil) { if ["agentEscape", "locked", "pickHear", "draft"].contains(f) { events.append(f) } }
    func hide(after: Double) {}
    var pausedNotice = Date.distantPast; func show() {}
""" + methods + stop + '        events.append("send"); engine.isRunning = false; busy = true; toggleTalk = false\n    }\n' + """}
meeting.running = true
let meetingShortcut = Harness(); meetingShortcut.shortcut(true); meetingShortcut.shortcut(false)
precondition(!meetingShortcut.engine.isRunning && meeting.focuses == 1 && meetingShortcut.events.isEmpty, "meeting shortcut started the microphone")
meeting.running = false
Prefs.toggle = true
let toggle = Harness(); toggle.shortcut(true); toggle.shortcut(true)
precondition(toggle.events == ["start"], "key repeat toggled twice")
toggle.shortcut(false); precondition(toggle.engine.isRunning && toggle.events == ["start"], "release sent a toggle request")
toggle.shortcut(true); precondition(toggle.events == ["start", "send"], "second press did not send")
toggle.shortcut(false); toggle.shortcut(true); precondition(toggle.events.contains("cancel"), "working shortcut did not cancel")
let empty = Harness(); empty.text = ""; empty.shortcut(true); empty.shortcut(false); empty.shortcut(true); precondition(empty.events == ["start", "send"] && !empty.clickTalk && !empty.engine.isRunning, "empty toggle failed to finalize late speech or reopened typing")
Prefs.toggle = false
let tap = Harness(); tap.text = ""; tap.began = Date(); tap.shortcut(true); tap.shortcut(false); precondition(tap.events == ["start", "hush"] && !tap.clickTalk && !tap.engine.isRunning, "quick voice tap kept listening, sent, or opened typing")
let silent = Harness(); silent.text = ""; silent.began = .distantPast; silent.shortcut(true); silent.shortcut(false); precondition(silent.events == ["start", "send"], "a real hold must still wait for late final words")
let hand = Harness(); hand.handsFree = true; hand.shortcut(true); hand.shortcut(false)
precondition(hand.handsFree, "a voice shortcut ended the hands-free chat")
let handEscape = Harness(); handEscape.handsFree = true; handEscape.escape()
precondition(handEscape.events == ["close", "hush"], "Esc did not end hands-free chat")
let hold = Harness(); hold.shortcut(true); hold.shortcut(false); precondition(hold.events == ["start", "send"], "hold release regressed")
let voice = Harness(); voice.speaking = true; voice.busy = true; voice.shortcut(true); precondition(voice.events == ["quiet"] && !voice.engine.isRunning && voice.busy, "stopping voice started the mic")
let click = Harness(); click.engine.isRunning = true; click.clickTalk = true; click.shortcut(false); precondition(click.events.isEmpty, "release sent click-to-talk")
Prefs.paused = true; let paused = Harness(); paused.shortcut(true); paused.shortcut(false); precondition(paused.events.isEmpty)
Prefs.paused = false; Prefs.toggle = true
let escape = Harness(); escape.shortcut(true); escape.escape(); precondition(!escape.events.contains("send") && !escape.engine.isRunning, "Esc submitted instead of cancelling")
let limit = Harness(); limit.shortcut(true); limit.recordingLimit(); precondition(limit.events.contains("review") && !limit.events.contains("send"), "timeout submitted toggle request")
let reply=Harness()
let j: [String:Any] = ["a":"fixture-answer"]
""" + source[source.index('                        self.retryOffer = true; self.askNeed'):source.index('self.show(); self.js("pick", j); continue')].replace("self.", "reply.") + """
precondition(reply.retryOffer && reply.askFile=="fixture-answer", "choices card did not enable spoken replies")
reply.busy=true;reply.offerText="Original task";reply.text="retry";reply.engine.isRunning=true;reply.feed=Input();reply.reading=Input()
reply.stopOfferInput()
precondition(reply.engine.stopped, "reply mic stayed open")
let failedStart=Harness();failedStart.retryOffer=true;failedStart.busy=true;failedStart.stopOfferInput();precondition(failedStart.engine.stopped && failedStart.busy && failedStart.askFile=="fixture-answer", "failed engine start left its tap or lost its worker")
precondition(!reply.engine.isRunning && reply.text=="Original task" && reply.offerText==nil && reply.busy && reply.retryOffer && reply.askFile=="fixture-answer", "stopping reply input lost the waiting task")
precondition(reply.speechInputs!.finished && reply.reading!.cancelled, "reply input stayed alive")
reply.shortcut(true);precondition(reply.events==["pickHear","start"], "card reply shortcut cancelled its worker")
let speakingReply=Harness();speakingReply.retryOffer=true;speakingReply.engine.isRunning=true;speakingReply.escape();precondition(speakingReply.events.contains("hush") && !speakingReply.engine.isRunning, "Esc did not stop card dictation")
let working=Harness();working.busy=true;working.shortcut(true);precondition(working.events.contains("cancel") && !working.engine.isRunning, "hotkey without a card stopped cancelling")
let waiting=Harness();waiting.busy=true;waiting.retryOffer=true;waiting.escape();precondition(waiting.events.contains("cancel"), "Esc did not cancel a waiting card")
let pickEsc=Harness();pickEsc.retryOffer=true;pickEsc.askNeed=["pick":true];pickEsc.busy=true;pickEsc.offerText="Original task";pickEsc.engine.isRunning=true;pickEsc.escape()
precondition(pickEsc.events==["pickHear"] && !pickEsc.engine.isRunning && pickEsc.busy && pickEsc.askFile=="fixture-answer" && pickEsc.text=="Original task", "Esc while answering a choices card lost the card or its task")
let pickLimit=Harness();pickLimit.retryOffer=true;pickLimit.askNeed=["pick":true];pickLimit.busy=true;pickLimit.offerText="Original task";pickLimit.engine.isRunning=true;pickLimit.recordingLimit()
precondition(pickLimit.events==["pickHear"] && pickLimit.busy && pickLimit.text=="Original task", "a choices card reply put its words in the text box")
reply.offerText="Original task";reply.text="partial retry";reply.recordingLimit()
precondition(reply.busy && reply.askFile=="fixture-answer" && reply.text=="Original task" && !reply.events.contains("send"), "reply recording limit sent or cancelled the request")
Prefs.toggle = true   // the main shortcut's toggle setting must not change dictation
let pump = { (s: Double) in RunLoop.main.run(until: Date().addingTimeInterval(s)) }
let locked = Harness(); locked.dictateShortcut(true); locked.dictateShortcut(true)
precondition(locked.events == ["dictate"], "dictation repeated on held key")
locked.dictateShortcut(false); precondition(locked.engine.isRunning && locked.events == ["dictate"], "a quick tap sent at once instead of waiting for a second tap")
locked.dictateShortcut(true); precondition(locked.toggleTalk && locked.engine.isRunning && locked.events == ["dictate", "locked"], "double tap did not lock")
locked.dictateShortcut(false); pump(0.4); precondition(locked.engine.isRunning, "releasing the second tap ended locked dictation")
locked.dictateShortcut(true); precondition(locked.events == ["dictate", "locked", "send"], "a press did not finish locked dictation")
let tapped = Harness(); tapped.dictateShortcut(true); tapped.dictateShortcut(false); pump(0.4)
precondition(tapped.events == ["dictate", "send"] && !tapped.engine.isRunning, "a single quick tap kept listening")
let dictatedHold = Harness(); dictatedHold.dictateShortcut(true); dictatedHold.dictatePressed = .distantPast; dictatedHold.dictateShortcut(false)
precondition(dictatedHold.events == ["dictate", "send"], "dictation hold release did not send at once")
let tapEscape = Harness(); tapEscape.dictateShortcut(true); tapEscape.dictateShortcut(false); tapEscape.escape(); pump(0.4)
precondition(!tapEscape.events.contains("send") && !tapEscape.engine.isRunning, "Esc during the double-tap wait still inserted")
let lockedEscape = Harness(); lockedEscape.dictateShortcut(true); lockedEscape.dictateShortcut(false); lockedEscape.dictateShortcut(true); lockedEscape.escape()
precondition(!lockedEscape.events.contains("send") && !lockedEscape.engine.isRunning, "Esc did not cancel locked dictation")
Prefs.toggle = false
print("shortcut regressions ok")
"""
        with tempfile.TemporaryDirectory() as path:
            file = Path(path) / 'shortcut.swift'; file.write_text(swift)
            binary = Path(path) / 'shortcut'
            compiled = subprocess.run(['swiftc', '-O', str(file), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
            self.assertIn('shortcut regressions ok', result.stdout)

    def test_live_worker_cancellation_revision_and_pipe_drain(self):
        with tempfile.TemporaryDirectory() as path:
            command = harness(Path(path))
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('regressions ok', result.stdout)


if __name__ == '__main__':
    if '--benchmark' in sys.argv:
        with tempfile.TemporaryDirectory() as path:
            subprocess.run(harness(Path(path)) + ['--benchmark'], check=True, timeout=30)
    else:
        unittest.main()
