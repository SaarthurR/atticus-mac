"""Typing receipts and composer identity with in-memory AX and keyboard stubs only."""
from pathlib import Path
import io
import json
import os
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

import atticus
import tests
from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]


class TypingReceiptTests(unittest.TestCase):
    def swift(self, source):
        # This executable contains only the stubs below; it cannot open an app or window.
        with patch.object(subprocess.Popen, '__init__', getattr(tests, '_popen_init', subprocess.Popen.__init__)):
            return run_swift(self, source)

    def test_missing_readback_is_not_a_send_receipt(self):
        source = (ROOT / 'Atticus.swift').read_text()
        method = source[source.index('    static func submitReceipt('):source.index('    static func validate(', source.index('    static func submitReceipt('))]
        self.swift('''import Foundation
struct Map { var texts: [String] = []; var page = "", windowID = "42" }
struct Hands {
''' + method + '''}
let before = Map()
precondition(!Hands.submitReceipt("draft", nil, "draft", before, before), "unreadable field was called sent")
precondition(Hands.submitReceipt("draft", "", "draft", before, before))
precondition(!Hands.submitReceipt("draft", "draft\\n", "draft", before, before))
var posted = before; posted.texts = ["draft"]
precondition(Hands.submitReceipt("draft", nil, "draft", before, posted))
''')

    def test_typing_refuses_a_different_focused_composer(self):
        source = (ROOT / 'Atticus.swift').read_text()
        start = source.index('    static func typeText(')
        method = source[start:source.index('    static func settle(', start)]
        # Include the shared focus check once added, keeping this fixture tied to production code.
        if '    static func fieldFocused(' in source:
            start = source.index('    static func fieldFocused(')
            method = source[start:source.index('    static func typeText(', start)] + method
        self.swift('''import Foundation
import CoreFoundation
func CFEqual(_ a: Int, _ b: Int) -> Bool { a == b }
typealias AXUIElement = Int
let kAXFocusedAttribute = "focused", kAXValueAttribute = "value", kAXFocusedUIElementAttribute = "focus", kAXSelectedTextRangeAttribute = "range"
enum AXError { case success, failure }
var values: [Int: String] = [1: "left", 2: "right"], focused = 2, keys = 0, writes = 0, deaf = false
func AXUIElementCreateApplication(_ pid: Int32) -> Int { 0 }
func AXUIElementSetAttributeValue(_ e: Int, _ key: CFString, _ value: CFTypeRef) -> AXError {
 if key as String == "value" { writes += 1; if !deaf { values[e] = value as? String } }
 return .success // an app can acknowledge focus without changing its focused composer
}
func AXValueCreate(_ type: Kind, _ range: inout CFRange) -> CFTypeRef? { nil }
enum Kind { case cfRange }
struct NSRunningApplication { let processIdentifier: Int32 = 42 }
struct Node { var role = "AXTextArea", secret = false }
final class Item { var types: [String] = []; func data(forType: String) -> Data? { nil }; func setData(_ d: Data, forType: String) {} }
final class NSPasteboard {
 static let general = NSPasteboard(); var pasteboardItems: [Item]? = []; var changeCount = 0
 func clearContents() {}; func setString(_ s: String, forType: String) -> Bool { true }; func writeObjects(_ a: [Item]) {}
}
typealias NSPasteboardItem = Item
extension String { static let string = "string" }
struct Hands {
 struct Failure: Error { let message: String; init(_ s: String) { message = s } }
 static func attribute(_ e: Int, _ key: String) -> Any? { key == "focus" ? focused : values[e] }
 static func element(_ e: Int, _ key: String) -> Int? { focused }
 static func selectedRange(_ e: Int) -> CFRange? { CFRange(location: 0, length: 0) }
 static func lease(_ s: String) throws -> Int { 1 }; static func unlock(_ n: Int) {}
 static func sendKeys(_ s: String, pid: Int32) throws { keys += 1; values[focused] = "WRONG" }
''' + method + '''}
let before = values
do { _ = try Hands.typeText("draft", Node(), 1, NSRunningApplication(), append: false); fatalError("stale focus accepted") }
catch { precondition(values == before && writes == 0 && keys == 0, "wrong composer changed") }
focused = 1
precondition(try! Hands.typeText("draft", Node(), 1, NSRunningApplication(), append: false) == "verified" && values[2] == "right" && keys == 0)
deaf = true; values[1] = "left"
do { _ = try Hands.typeText("draft", Node(), 1, NSRunningApplication(), append: false); fatalError("ignored write was reported typed") }
catch let f as Hands.Failure { precondition(f.message.hasPrefix("not_done") && keys == 0) }
values[1] = nil
precondition(try! Hands.typeText("draft", Node(), 1, NSRunningApplication(), append: false) == "unverified" && keys == 0, "unreadable field was pasted again")
''')

    def test_python_adapter_pins_observed_destination_and_preserves_uncertainty(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root, 'hands.json')
            state.write_text(json.dumps({'pid': 42, 'windowID': '7', 'focusIdentity': 'AXTextArea:[1]:[0,0,100,100]'}))
            with patch.object(atticus, 'DIR', root), patch.dict(os.environ, {'ATTICUS_HANDS_STATE': str(state)}, clear=True), \
                 patch.object(atticus.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'unverified: Do not repeat typing.')) as run, \
                 patch.object(sys, 'argv', ['atticus.py', '--type', 'draft']), patch.object(sys, 'stdout', new_callable=io.StringIO) as out:
                atticus.main()
                self.assertIn('unverified:', out.getvalue())
                run.assert_called_once()
                self.assertEqual(run.call_args.kwargs['env']['ATTICUS_HANDS_WINDOW'], '7')
                self.assertEqual(run.call_args.kwargs['env']['ATTICUS_HANDS_STATE'], str(state))
                # A replayed shortcut has no map in its ask: it still types at the focused caret, without a pin.
                state.unlink(); run.reset_mock(); out.truncate(0); out.seek(0)
                run.return_value = subprocess.CompletedProcess([], 0, 'verified: Typing dispatched.')
                atticus.main()
                run.assert_called_once_with([atticus.APP, '--type'], input='draft', capture_output=True, text=True)
                self.assertIn('verified:', out.getvalue())

    def test_cli_screenshot_survives_producer_exit_for_next_reader(self):
        # Real helper process, fake capture only. No screens, apps, or windows are accessed.
        script = r'''import os, sys
from pathlib import Path
from unittest.mock import patch
import atticus

def capture(args, **kwargs):
    Path(args[3]).write_bytes(b"fixture image")
    return type("Result", (), {"returncode": 0, "stdout": ""})()
with patch.object(atticus, "pref", return_value=False), patch.object(atticus, "screens", return_value=[("Fixture", 0, 0, 100, 100, True)]), patch.object(atticus.subprocess, "run", side_effect=capture):
    os.environ.pop("ATTICUS_ASK", None)
    sys.argv = ["atticus.py", "--look"]
    atticus.main()
'''
        with tempfile.TemporaryDirectory() as root:
            env = {**os.environ, 'ATTICUS_DIR': root}
            produced = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(produced.returncode, 0, produced.stderr)
            path = Path(produced.stdout.strip().rsplit(': ', 1)[1])
            self.addCleanup(path.unlink, missing_ok=True)
            reader = subprocess.run([sys.executable, '-c', 'import pathlib,sys; assert pathlib.Path(sys.argv[1]).read_bytes() == b"fixture image"', str(path)], env=env, capture_output=True, text=True)
            self.assertEqual(reader.returncode, 0, reader.stderr)

    def test_submit_dispatch_stops_on_uncertain_typing_or_lost_field_focus(self):
        source = (ROOT / 'Atticus.swift').read_text()
        start = source.index('            case "type":\n                let (n,e) = try resolve(')
        branch = source[start:source.index('            case "type-after":', start)]
        self.swift('''import Foundation
struct Node { var spot = 0, label = "Composer" }
struct Map {}
var scenario = 0, focus = true, sends = 0, types = 0, captures = 0
enum ReadError: Error { case unavailable }
struct Hands {
 struct Failure: Error { init(_ s: String) {} }
 static func stringValue(_ e: Int) -> String? { nil }
 static func mask(_ s: String) -> String { s }
 static func quote(_ s: String) -> String { s }
 static func sendKeys(_ s: String, pid: Int32) throws { sends += 1 }
 static func submitReceipt(_ t: String?, _ v: String?, _ s: String, _ b: Map, _ a: Map) -> Bool { false }
 struct App { var processIdentifier: Int32 = 42 }
 static func resolve(_ s: String, map: Map, a: App) throws -> (Node, Int?) { (Node(), 1) }
 static func typeText(_ s: String, _ n: Node, _ e: Int, _ a: App, append: Bool) throws -> String { types += 1; return scenario == 0 ? "unverified" : "verified" }
 static func fieldFocused(_ e: Int, _ a: App) -> Bool { focus }
 static func capture(_ a: App) throws -> Map { captures += 1; if scenario == 4 || scenario == 3 && captures > 1 { throw ReadError.unavailable }; if scenario == 1 { focus = false }; return Map() }
 static func run() throws -> Int {
  let input = ["type", "Composer", "draft", "submit"], before = Map(), a = App()
  var spot = 0, result = ""
  switch input[0] {
''' + branch + '''
  default: break
  }
  print(result); _ = spot; return 0
 }
}
for test in 0...4 {
 scenario = test; focus = true; sends = 0; types = 0; captures = 0
 _ = try Hands.run()
 precondition(types == 1 && sends == ([2,3].contains(test) ? 1 : 0), "typing or Return repeated, or Return reached an unconfirmed field")
}
''')

    def test_typing_destination_keeps_observed_window_and_composer(self):
        source = (ROOT / 'Atticus.swift').read_text()
        start = source.index('    func destinationMatches() -> Bool {')
        function = source[start:source.index('    guard mapped.map(', start)]
        self.swift('''import Foundation
struct Map { var windowID = "7", focusIdentity = "AXTextArea:[1]:[0,0,100,100]" }
var mapped: Map? = Map()
var current = mapped!
struct Selected { var app = 42 }
let selected = Selected()
struct Hands { static func capture(_ app: Int) throws -> Map { current } }
''' + function + '''
precondition(destinationMatches())
current.focusIdentity = "AXTextArea:[2]:[100,0,100,100]"
precondition(!destinationMatches(), "another composer in the same app was accepted")
current = mapped!; current.windowID = "8"
precondition(!destinationMatches(), "another window in the same app was accepted")
mapped = nil
precondition(destinationMatches(), "a replayed shortcut with no map was refused")
''')
