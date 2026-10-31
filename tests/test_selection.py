"""Selection lifecycle with fake AX, focus, events and clipboard; no real apps."""
from pathlib import Path
import sys
import unittest

from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'macOS Swift regression')
class SelectionTests(unittest.TestCase):
    def test_paste_rechecks_target_cancellation_and_clipboard_ownership(self):
        source = (ROOT / 'Atticus.swift').read_text()
        apply = source[source.index('    func apply(_ draft:'):source.index('    func replace(_ draft:')]
        borrow = source[source.index('func borrowPasteboard'):source.index('struct TextSelection {')]
        swift = '''import Foundation
import CoreFoundation
func IsSecureEventInputEnabled() -> Bool { false }
let kAXFocusedUIElementAttribute = "focus", kAXSelectedTextAttribute = "text", kAXValueAttribute = "value"
var keys: [Int] = [], field = "old", deaf = false, hidEvents = 0
var focused = 1, selected = "old", currentRange = CFRange(location: 0, length: 3), events = 0, directWrites = 0, directOK = true, activations = 0
func AXUIElementCreateApplication(_ pid: Int) -> Int { pid }
func AXUIElementSetMessagingTimeout(_ element: Int, _ timeout: Double) {}
func axAttribute(_ e: Any, _ name: String) -> CFTypeRef? { name == "focus" ? NSNumber(value: focused) : name == "value" ? field as CFString : selected as CFString }
final class FakeApp: Equatable {
 var isTerminated = false, processIdentifier = 42
 func activate() { activations += 1; NSWorkspace.shared.frontmostApplication = self }
 static func == (a: FakeApp, b: FakeApp) -> Bool { a === b }
}
final class NSWorkspace { static let shared = NSWorkspace(); var frontmostApplication: FakeApp? }
enum PasteType: Hashable { case string, rich, transient; init(_ raw: String) { self = .transient } }
final class NSPasteboardItem {
 var data: [PasteType: Data] = [:]
 var types: [PasteType] { Array(data.keys) }
 func data(forType type: PasteType) -> Data? { data[type] }
 func setData(_ value: Data, forType type: PasteType) { data[type] = value }
}
final class NSPasteboard {
 typealias PasteboardType = PasteType
 static let general = NSPasteboard()
 var pasteboardItems: [NSPasteboardItem]? = [], changeCount = 0, failWrite = false, marked = 0
 func clearContents() { changeCount += 1; pasteboardItems = [] }
 func setString(_ text: String, forType type: PasteType) -> Bool {
  if failWrite { return false }
  let item = NSPasteboardItem(); item.setData(Data(text.utf8), forType: type)
  pasteboardItems = [item]; changeCount += 1; return true
 }
 func setData(_ value: Data, forType type: PasteType) { if type == .transient { marked += 1 }; pasteboardItems?.first?.setData(value, forType: type) }
 func writeObjects(_ items: [NSPasteboardItem]) -> Bool { pasteboardItems = items; changeCount += 1; return true }
}
var clipboardBusy = false, leases = 0, unlocks = 0
enum Hands {
 struct Busy: Error {}
 static func lease(_ name: String, wait: Bool) throws -> Int32 { precondition(name == "clipboard.lock" && !wait); if clipboardBusy { throw Busy() }; leases += 1; return 7 }
 static func unlock(_ fd: Int32) { precondition(fd == 7); unlocks += 1 }
}
''' + borrow + '''
enum CGEventTapLocation { case cghidEventTap }
final class FakeNSApp { var keyWindow: Int? }
let NSApp = FakeNSApp()
struct Flags: OptionSet { let rawValue: Int; static let maskCommand = Flags(rawValue: 1) }
final class CGEvent {
 var flags: Flags = []
 let key: Int
 init?(keyboardEventSource: Int?, virtualKey: Int, keyDown: Bool) { key = virtualKey }
 func postToPid(_ pid: Int) { events += 1; keys.append(key); precondition(pid == 42 && flags == (key == 51 ? [] : .maskCommand)); if !deaf { field = key == 51 ? "" : "draft" } }
 func post(tap: CGEventTapLocation) {
  hidEvents += 1; events += 1; keys.append(key)
  if !deaf { field = key == 51 ? "" : String(data: NSPasteboard.general.pasteboardItems!.first!.data(forType: .string)!, encoding: .utf8)! }
 }
}
struct Harness {
 let element: CFTypeRef = NSNumber(value: 1), focus: CFTypeRef = NSNumber(value: 1), app = FakeApp(), text = "old"
 var range: CFRange? = CFRange(location: 0, length: 3), keyboardOnly = false
 enum Delivery { case landed, unchanged, unknown }
 static let settle: TimeInterval = 0.05
 static func string(_ value: CFTypeRef?) -> String? { value as? String }
 var editable = false, pastable = true
 static func selectedRange(_ e: CFTypeRef) -> CFRange? { currentRange }
 func replace(_ text: String) -> Bool { if directOK { directWrites += 1; field = text }; return directOK }
''' + apply + '''}
func pump(_ seconds: Double, until done: () -> Bool = { false }) {   // a loaded machine runs the async steps late: stop at done, else the deadline
 let end = Date().addingTimeInterval(seconds)
 while Date() < end && !done() { RunLoop.current.run(until: Date().addingTimeInterval(0.005)) }
}
let h = Harness(), pb = NSPasteboard.general
let old = NSPasteboardItem(); old.setData(Data("rich original".utf8), forType: .rich)
func reset() { focused = 1; selected = "old"; field = "old"; deaf = false; currentRange = CFRange(location: 0, length: 3); h.app.isTerminated = false; pb.failWrite = false; pb.writeObjects([old]) }
for scenario in 0..<6 {
 reset(); let before = events; var result: Bool?, allowed = true
 h.apply(scenario == 4 ? "" : "draft", valid: { allowed }) { result = $0 }
 precondition(result == nil, "reported success before delivery")
 switch scenario {
 case 0: NSWorkspace.shared.frontmostApplication = FakeApp()
 case 1: focused = 2
 case 2: currentRange.location = 4
 case 3: selected = "different"
 case 4: h.app.isTerminated = true
 default: allowed = false
 }
 pump(2, until: { result != nil }); precondition(result == false && events == before, "stale/cancelled target received keys")
 precondition(pb.pasteboardItems?.first?.data(forType: .rich) == Data("rich original".utf8), "aborted paste touched clipboard")
}
reset(); var ok = false
h.apply("draft", valid: { true }) { ok = $0 }; pump(0.5); precondition(ok)
pb.clearContents(); _ = pb.setString("new copy", forType: .string); pump(0.45)
precondition(pb.pasteboardItems?.first?.data(forType: .string) == Data("new copy".utf8), "new clipboard copy clobbered")
reset(); let marks = pb.marked; h.apply("draft", valid: { true }) { ok = $0 }; pump(0.6)
precondition(ok && pb.pasteboardItems?.first?.data(forType: .rich) == Data("rich original".utf8), "rich clipboard not restored")
precondition(pb.marked == marks + 1 && pb.pasteboardItems?.first?.data(forType: .string) == nil, "the paste was not transient, or its text stayed")
reset(); let count = pb.changeCount; h.apply("", valid: { true }) { ok = $0 }; pump(0.5)
precondition(ok && pb.changeCount == count && Array(keys.suffix(2)) == [51, 51], "delete key/clipboard regressed")
reset(); pb.failWrite = true; h.apply("draft", valid: { true }) { ok = $0 }; pump(0.2)
precondition(!ok && pb.pasteboardItems?.first?.data(forType: .rich) != nil, "failed write lost clipboard")
reset(); var receipt = ""; deaf = true; ok = false; var answered = false; let hidBefore = hidEvents; h.apply("draft", receipt: { receipt = $0 }, valid: { true }) { ok = $0; answered = true }; pump(2, until: { answered })
precondition(receipt == "unverified", "stale readback was reported verified")
precondition(ok && hidEvents == hidBefore + 2 && pb.pasteboardItems?.first?.data(forType: .rich) == Data("rich original".utf8), "a sent paste whose field reads back stale was not counted, was retried, or kept the draft on the clipboard")
var readonly = h; readonly.pastable = false; let before = events
answered = false; readonly.apply("", valid: { true }) { ok = $0; answered = true }; pump(2, until: { answered }); precondition(!ok && events == before, "read-only delete posted")
var editable = h; editable.editable = true; editable.pastable = false
editable.apply("direct", valid: { true }) { ok = $0 }
 pump(0.1)
precondition(ok && directWrites == 1 && events == before, "editable custom role rejected")
reset(); editable.pastable = true; directOK = false
ok = false; answered = false; editable.apply("fallback", valid: { true }) { ok = $0; answered = true }; pump(2, until: { answered })
precondition(ok && events == before + 2, "failed AX write did not fall back to paste")
reset(); directOK = false; let other = FakeApp(); NSWorkspace.shared.frontmostApplication = other; let eventCount = events, activationCount = activations
answered = false; h.apply("private", preserveFocus: true, valid: { NSWorkspace.shared.frontmostApplication === h.app }) { ok = $0; answered = true }; pump(2, until: { answered })
precondition(!ok && events == eventCount && activations == activationCount && NSWorkspace.shared.frontmostApplication === other, "focus-preserving insert raised the old app or typed there")
reset(); clipboardBusy = true; ok = false; let busyEvents = events
h.apply("draft", valid: { true }) { ok = $0 }; pump(0.3)
precondition(!ok && events == busyEvents && pb.pasteboardItems?.first?.data(forType: .rich) != nil, "pasted while another Atticus process held the clipboard")
clipboardBusy = false; pump(2, until: { ok }); precondition(ok && leases == unlocks, "paste did not resume after the clipboard freed, or kept the lock")
reset(); NSApp.keyWindow = 1; ok = false; let hidKeyed = hidEvents, pidKeyed = events
answered = false; h.apply("draft", valid: { true }) { ok = $0; answered = true }; pump(2, until: { answered }); NSApp.keyWindow = nil
precondition(ok && hidEvents == hidKeyed && events == pidKeyed + 2, "with the box holding the keyboard, ⌘V went to the box instead of the target app")
reset(); var keyboard = h; keyboard.range = nil; keyboard.keyboardOnly = true; focused = 2
NSWorkspace.shared.frontmostApplication = keyboard.app; let keyboardEvents = events
answered = false; keyboard.apply("draft", preserveFocus: true, valid: { NSWorkspace.shared.frontmostApplication === keyboard.app }) { ok = $0; answered = true }; pump(2, until: { answered })
precondition(ok && events == keyboardEvents + 2, "frontmost keyboard fallback required a readable focused element")
reset(); keyboard = h; keyboard.range = nil; keyboard.keyboardOnly = true
NSWorkspace.shared.frontmostApplication = FakeApp(); let movedEvents = events
answered = false; keyboard.apply("private", preserveFocus: true, valid: { NSWorkspace.shared.frontmostApplication === keyboard.app }) { ok = $0; answered = true }; pump(2, until: { answered })
precondition(!ok && events == movedEvents, "keyboard fallback pasted after the front app changed")
print("paste safety ok")
'''
        import subprocess
        from unittest.mock import patch
        import tests
        # The extracted harness above has no app/window APIs; run its stubs on the host.
        with patch.object(subprocess.Popen, '__init__', getattr(tests, '_popen_init', subprocess.Popen.__init__)):
            self.assertIn('paste safety ok', run_swift(self, swift, timeout=20))

    def test_typing_capture_accepts_empty_fields_but_never_secure_fields(self):
        source = (ROOT / 'Atticus.swift').read_text()
        capture = source[source.index('    static func capture('):source.index('    static func selectedRange(')]
        pastable = source[source.index('    var pastable: Bool'):source.index('    func apply(')]
        typing_guard = next(line for line in source.splitlines() if 'guard let selected = TextSelection.capture(enabled: true' in line)
        swift = '''import Foundation
import CoreFoundation
let kAXFocusedUIElementAttribute = "focus", kAXSubroleAttribute = "subrole", kAXSelectedTextAttribute = "text", kAXValueAttribute = "value", kAXRoleAttribute = "role", kAXParentAttribute = "parent", kAXSecureTextFieldSubrole = "secure"
var selectedText = "", subrole = "field", canEdit = true, exposesSelectedText = true, useParent = false
var focusAvailable = true, wakeRevealsFocus = true, wakeWrites: [String] = []
struct Prefs { static func bool(_ key: String) -> Bool { true } }
final class NSRunningApplication: Equatable {
 static let current = NSRunningApplication()
 let processIdentifier = 1
 static func == (a: NSRunningApplication, b: NSRunningApplication) -> Bool { a === b }
}
final class NSWorkspace { static let shared = NSWorkspace(); var frontmostApplication: NSRunningApplication? = NSRunningApplication() }
typealias AXUIElement = Int
func AXIsProcessTrusted() -> Bool { true }
func AXUIElementCreateApplication(_ pid: Int) -> Int { pid }
func AXUIElementSetMessagingTimeout(_ e: Int, _ timeout: Double) {}
func AXUIElementSetAttributeValue(_ e: Int, _ name: CFString, _ value: CFTypeRef) -> Int32 {
 wakeWrites.append(name as String)
 if wakeRevealsFocus { focusAvailable = true }
 return 0
}
func axAttribute(_ e: Int, _ name: String) -> CFTypeRef? {
 if name == "focus" { return focusAvailable ? NSNumber(value: 1) : nil }
 if name == "AXManualAccessibility" || name == "AXEnhancedUserInterface" { return kCFBooleanFalse }
 if name == "parent" { return useParent && e == 1 ? NSNumber(value: 2) : nil }
 if name == "subrole" { return subrole as CFString }
 if name == "role" { return (e == 2 ? "AXWebArea" : "AXStaticText") as CFString }
 if e == 2 { return name == "value" ? NSAttributedString(string: "prefix old suffix") : nil }
 return name == "value" ? selectedText as CFString : exposesSelectedText ? selectedText as CFString : nil
}
struct TextSelection {
 let element: Int, focus: Int, app: NSRunningApplication, text: String, range: CFRange?
 var editable: Bool { canEdit }
 var keyboardOnly: Bool { false }
''' + pastable + '''
 static func string(_ value: Any?) -> String? { value as? String ?? (value as? NSAttributedString)?.string }
 static func parent(_ e: Int) -> Int? { axAttribute(e, kAXParentAttribute) as? Int }
 static func selectedRange(_ e: Int) -> CFRange? { useParent ? (e == 2 ? CFRange(location: 7, length: 3) : nil) : CFRange(location: 0, length: selectedText.count) }
''' + capture + '''}
func acceptsTyping() -> Bool {
''' + typing_guard + ''' return false }; return true
}
precondition(acceptsTyping(), "typing rejected an editable custom role")
canEdit = false; precondition(!acceptsTyping(), "typing accepted a read-only custom role"); canEdit = true
precondition(TextSelection.capture()?.caret == true, "a cursor in a text box was not kept for drafts")
canEdit = false; precondition(TextSelection.capture() == nil, "an empty read-only spot became a draft target"); canEdit = true
precondition(TextSelection.capture(enabled: true, allowEmpty: true)?.text == "", "typing rejected an empty field")
selectedText = "old"; precondition(TextSelection.capture()?.text == "old")
exposesSelectedText = false; precondition(TextSelection.capture(enabled: true, allowEmpty: true)?.text == "old", "field value did not recover a missing selected-text attribute")
selectedText = ""; exposesSelectedText = true; useParent = true
let rich = TextSelection.capture()
precondition(rich?.text == "old" && rich?.element == 2 && rich?.focus == 1 && rich?.pastable == true, "browser parent/attributed selection was not captured as replaceable")
useParent = false; selectedText = "old"
precondition(TextSelection.capture(enabled: false, allowEmpty: true) == nil)
NSWorkspace.shared.frontmostApplication = .current
precondition(TextSelection.capture(enabled: true, allowEmpty: true) == nil, "Atticus captured its own field")
NSWorkspace.shared.frontmostApplication = NSRunningApplication()
subrole = "secure"; precondition(TextSelection.capture(enabled: true, allowEmpty: true) == nil, "password field captured")
subrole = "field"; selectedText = String(repeating: "x", count: 6001)
precondition(TextSelection.capture() == nil, "AI selection budget exceeded")
precondition(TextSelection.capture(enabled: true, allowEmpty: true)?.text.count == 6001, "typing truncated selected text")
selectedText = ""; focusAvailable = false; wakeRevealsFocus = true; wakeWrites = []
precondition(TextSelection.capture(enabled: true, allowEmpty: true)?.range?.location == 0, "lazy accessibility was not re-queried")
precondition(wakeWrites == ["AXManualAccessibility"], "lazy accessibility was not enabled once")
focusAvailable = false; wakeRevealsFocus = false; wakeWrites = []
let keyboard = TextSelection.capture(enabled: true, allowEmpty: true, keyboardFallback: true)
precondition(keyboard?.range == nil && keyboard?.element == 1 && keyboard?.focus == 1, "frontmost app did not get a keyboard fallback")
NSWorkspace.shared.frontmostApplication = .current
precondition(TextSelection.capture(NSRunningApplication(), enabled: true, allowEmpty: true, keyboardFallback: true) == nil, "keyboard fallback ignored the frontmost app")
print("typing capture ok")
'''
        self.assertIn('typing capture ok', run_swift(self, swift))

    def test_capture_is_async_and_cancelled_or_stale_results_are_ignored(self):
        source = (ROOT / 'Atticus.swift').read_text().split('final class App: NSObject, WKScriptMessageHandler {',1)[1]
        capture = source[source.index('    func captureSelection()'):source.index('    func captureDictationSelection(')]
        finish = source[source.index('    func finish()'):source.index('        aheadItem?.cancel()', source.index('    func finish()'))] + '        finished += 1\n    }\n'
        swift = '''import Foundation
struct Prefs { static func bool(_ key: String) -> Bool { true } }
final class NSWorkspace { static let shared = NSWorkspace(); var frontmostApplication: String? = "Original" }
struct TextSelection {
 let text: String
 var caret: Bool { text.isEmpty }
 static func capture(_ app: String?, enabled: Bool) -> TextSelection? { Thread.sleep(forTimeInterval: 0.15); return TextSelection(text: app ?? "") }
}
final class DrawingStub { var active = false; func next() {} }
func transcriptKey(_ s: String) -> String { s.lowercased() }
final class Harness {
 var drawingReply = false; let drawing = DrawingStub(); var proc: Process?
 func cancel() {}; func hush() {}; func hush(keepReply: Bool, keepWarm: Bool = false) {}; func typed(_ s: String, heard: Bool = false) {}
 var quietFollowUp = false
 var selectionID = 0, selectionPending = false, selection: TextSelection?, messages: [String] = []
 var warm: Int? = 1, warmSel = "", respawns = 0
 var busy = true, fastBusy = false, stops = 0, finished = 0
 var offerText: String?, text = "Original request"
 func unwarm() { warm = nil }
 func spawn() -> Int? { respawns += 1; warmSel = selection?.text ?? ""; return 1 }
 func js(_ call: String, _ text: String) { messages.append(text) }
''' + capture + finish + '''}
func pump(_ seconds: Double, until done: () -> Bool = { false }) {   // a loaded machine runs the async steps late: stop at done, else the deadline
 let end = Date().addingTimeInterval(seconds)
 while Date() < end && !done() { RunLoop.current.run(until: Date().addingTimeInterval(0.005)) }
}
let h = Harness(), start = Date()
h.captureSelection(); h.finish(); precondition(h.finished == 0, "short key-up submitted before capture")
precondition(Date().timeIntervalSince(start) < 0.05 && h.selectionPending, "AX capture blocked shortcut")
NSWorkspace.shared.frontmostApplication = "Moved"; pump(2, until: { !h.selectionPending })
precondition(h.selection?.text == "Original" && !h.selectionPending, "captured wrong app")
pump(2, until: { h.finished == 1 }); precondition(h.finished == 1, "pending key-up did not resume")
precondition(h.respawns == 1 && h.warmSel == "Original", "warm worker did not refresh before request")
h.captureSelection(); h.selectionID += 1; h.selectionPending = false; h.selection = nil; pump(0.2)
precondition(h.selection == nil && h.messages == ["Original"], "cancelled capture returned")
h.captureSelection(); NSWorkspace.shared.frontmostApplication = "New"; h.captureSelection(); pump(2, until: { !h.selectionPending })
precondition(h.selection?.text == "New" && h.messages == ["Original", "New"], "stale capture contaminated new request")
let reply = Harness(); reply.offerText = "Original request"; reply.text = "retry"; reply.finish()
precondition(reply.text == "Original request" && reply.offerText == nil && reply.messages == ["retry"] && reply.finished == 0, "card reply became a new task or lost its original request")
print("capture safety ok")
'''
        self.assertIn('capture safety ok', run_swift(self, swift))
