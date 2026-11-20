"""Release-tail revisions must cancel only speculation, never the confirmed ask."""
from pathlib import Path
import sys
import unittest

from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'Swift request lifecycle fixture')
class StallTests(unittest.TestCase):
    def test_cancelled_partials_then_release_tail_still_sends_final_request(self):
        source = (ROOT / 'Atticus.swift').read_text()
        drop = source[source.index('    func dropAhead()'):source.index('    func stop()', source.index('    func dropAhead()'))]
        finish = source[source.index('    func finish() {', source.index('    func typed(')):source.index('    // atticus.py --wait,')]
        exited = next(line.strip() for line in source.splitlines() if 'if !self.ahead.isEmpty { self.proc = nil;' in line)
        result = run_swift(self, r'''import Foundation
func transcriptKey(_ t: String) -> String { t.lowercased() }
final class Worker { var isRunning = true; func terminate() { isRunning = false } }
final class Engine { var isRunning = true }
final class Drawing { func next() {} }
final class Panel { func makeKey() {}; func makeFirstResponder(_ x: Int) {} }
final class Harness {
    let engine = Engine(), drawing = Drawing(), panel = Panel(); let web = 0
    var proc: Worker?, ahead = "", busy = false, releasePending = false
    var text = "", offerText: String?, drawingReply = false, fastBusy = false, selectionPending = false
    var stops = 0, aheadItem: DispatchWorkItem?, liveRevised = false, talkMoved = false, pinned = false
    var did: [String] = [], commit = "", guardUntil = Date(), answer = "", followUp = false, handsFree = false, lastDone = Date()
    var speechSentences = 0, spokenSoFar = "", speechMuted = false
    var sent: [String] = [], statuses: [String] = []
    func js(_ name: String, _ value: Any? = nil) { if name == "line", let value = value as? String { statuses.append(value) } }
    func unwarm() {}; func settleTalkPointer() {}; func hush(keepReply: Bool = false, keepWarm: Bool = false) { busy = false }
    func typed(_ t: String, heard: Bool) {}; func cancel() { busy = false }
    func rest() -> String { text }; func hide(after: Double) {}; func linger(_ s: Double) -> Double { s }
    func deliver(_ s: String) {}; func cue(_ s: String) {}; func followUpSoon() {}
    func SpeechSentences() -> Int { 0 }
    // Fake client: records confirmed sends without AI or native app access.
    func run(_ t: String, remaining: String? = nil) { sent.append(t); proc = Worker(); busy = true }
''' + drop + finish + '    func speculativeExited() { ' + exited + ' }\n' + r'''}
let h = Harness()
// Nov 16: partial asks at :16, :17, :20; recognizer revisions cancel each.
for partial in ["Com is", "Community is where you work.", "Can you teach me"] {
    h.text = partial; h.ahead = partial; h.proc = Worker(); h.busy = true
    h.dropAhead(); precondition(h.ahead.isEmpty && !h.busy && h.sent.isEmpty)
}
// Key-up marks the ask busy while the microphone retains its 200 ms tail.
h.text = "Can you teach me"; h.ahead = h.text; h.proc = Worker(); h.busy = true
h.releasePending = true
h.text = "Can you teach me how to use orca"
h.dropAhead() // late speech revises the speculative words while the mic is still running
h.engine.isRunning = false
h.finish()
precondition(h.sent == ["Can you teach me how to use orca"], "release-tail cancellation abandoned the final request")
// A revision after the mic drains must also preserve the pending send.
let drained = Harness(); drained.engine.isRunning = false; drained.busy = true
drained.releasePending = true; drained.ahead = "partial"; drained.proc = Worker(); drained.text = "final words"
drained.dropAhead(); drained.finish(); precondition(drained.sent == ["final words"])
// First ask after idle: the warm spare has not received any final request yet.
for exited in [false, true] {
    let first = Harness(); first.text = "What's"; first.ahead = first.text; first.proc = Worker()
    first.busy = true; first.releasePending = true
    first.text = "What's on my screen right now?"
    if exited { first.speculativeExited() } else { first.dropAhead() }
    first.engine.isRunning = false; first.finish()
    precondition(first.sent == ["What's on my screen right now?"], "first ask after idle lost its final send")
}
// Exact speculation is confirmed once, without submitting a duplicate ask.
let exact = Harness(); exact.busy = true; exact.proc = Worker(); exact.text = "same words"; exact.ahead = exact.text
exact.commit = NSTemporaryDirectory() + UUID().uuidString
exact.finish(); precondition(exact.sent.isEmpty && exact.ahead.isEmpty)
precondition(try! String(contentsOfFile: exact.commit, encoding: .utf8) == "go")
precondition(exact.statuses.last == "· Waiting for the answer…")
try! FileManager.default.removeItem(atPath: exact.commit)
// The finish guard must still refuse an ask whose busy state was cleared.
let cancelled = Harness(); cancelled.text = "cancelled words"; cancelled.finish(); precondition(cancelled.sent.isEmpty)
for selected in [false, true] {
    let waiting = Harness(); waiting.busy = true; waiting.selectionPending = selected; waiting.fastBusy = !selected
    waiting.finish(); precondition(waiting.sent.isEmpty)
}
print("stall release-tail regressions ok")
''')
        self.assertIn('stall release-tail regressions ok', result)
