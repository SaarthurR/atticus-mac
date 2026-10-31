"""Owned document edits against extracted production Swift and in-memory AX only."""
from pathlib import Path
import os
import tempfile
import subprocess
import unittest
from unittest.mock import patch
import tests
from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]


class OwnedEditTests(unittest.TestCase):
    def test_only_verified_inserted_span_can_be_repeated_or_corrected(self):
        source = Path(os.environ.get('OWNED_EDITS_SOURCE', ROOT / 'Atticus.swift')).read_text()
        methods = source[source.index('    static func ownedEdits(') if '    static func ownedEdits(' in source else source.index('    static func insertionTarget('):source.index('    static func fieldFocused(')]
        with tempfile.TemporaryDirectory() as root:
            swift = r'''import Cocoa
final class Field: NSObject {
 var text: String, title: String, role: String, range = CFRange(location:0,length:0)
 init(_ text: String, _ title: String = "", _ role: String = "AXTextArea") { self.text=text; self.title=title; self.role=role }
}
typealias AXUIElement = Field
struct NSRunningApplication { let processIdentifier: Int32 = 42 }
let field = Field("Unrelated heading 🧭\nWhy does a wheel turn?\nKeep this question.\nFooter"), window = Field("", "Worksheet", "AXWindow")
final class Clipboard {
 static let general = Clipboard(); var text = "", changeCount = 0
 var pasteboardItems: [NSPasteboardItem]? = []
 func clearContents() { text = ""; changeCount += 1 }
 func setString(_ s: String,forType: NSPasteboard.PasteboardType) -> Bool { text = s; return true }
 func writeObjects(_ items: [NSPasteboardItem]) {}
 func string(forType: NSPasteboard.PasteboardType) -> String? { text }
}
let label = Field("", "Why does a wheel turn?", "AXStaticText")
var separate = false
var focus = field, mutateOnCaret = false, stealFocus = false, refuse = false, writes = 0, keys: [String] = []
func AXUIElementSetAttributeValue(_ e: Field, _ key: CFString, _ value: CFTypeRef) -> AXError {
 switch key as String {
 case kAXFocusedAttribute: focus = stealFocus ? window : e
 case kAXSelectedTextRangeAttribute:
  var r = CFRange(); AXValueGetValue(value as! AXValue,.cfRange,&r); e.range = r
  if mutateOnCaret { e.text = "USER " + e.text; mutateOnCaret = false }
 case kAXSelectedTextAttribute:
  if refuse { return .cannotComplete }; writes += 1
  e.text = (e.text as NSString).replacingCharacters(in:NSRange(location:e.range.location,length:e.range.length),with:value as! String)
 default: break
 }; return .success
}
struct Hands {
 struct Failure: Error { init(_ s: String) {} }
 struct Insertion { let field: Field, anchor: Field, old: String, location: Int, label: String }
 struct OwnedEdit: Codable { let field: String, anchor: String, location: Int, length: Int, after: String }
 static let env = ["ATTICUS_HANDS_STATE": "ROOT/hands.json"]
 static func digest(_ s: [String]) -> String { s.joined(separator:"|") }
 static func root(_ a: NSRunningApplication) throws -> (Field,Field) { (window,window) }
 static func documentIdentity(_ a: NSRunningApplication,_ w: Field) -> String { "42:7" }
 static func attribute(_ e: Field,_ k: String) -> Any? { k == kAXRoleAttribute ? e.role : nil }
 static func children(_ e: Field) -> [Field] { e === window ? (separate ? [label,field] : [field]) : [] }
 static func name(_ e: Field) -> String { e.title }
 static func frame(_ e: Field) -> CGRect { CGRect(x:0,y:e === field ? 40 : 0,width:100,height:24) }
 static func visibleFrame(_ e: Field) -> CGRect { frame(e) }
 static func array(_ r: CGRect) -> [Double] { [r.origin.x,r.origin.y,r.width,r.height] }
 static func rank(_ s: String,_ t: String) -> Int { s == t ? 4 : 0 }
 static func stringValue(_ e: Field) -> String? { e.text }
 static func selectedRange(_ e: Field) -> CFRange? { e.range }
 static func fieldFocused(_ e: Field,_ a: NSRunningApplication,wait: TimeInterval = 0) -> Bool { e === focus }
 static func checkStopped() throws {}
 static func mask(_ s: String) -> String { s }; static func quote(_ s: String) -> String { s }
 static func lease(_ s: String) throws -> Int { 1 }; static func unlock(_ n: Int) {}
 static func sendKeys(_ s: String,pid: Int32) throws {
  keys.append(s); precondition(s == "cmd+v", "unbounded repair key")
  focus.text = (focus.text as NSString).replacingCharacters(in:NSRange(location:focus.range.location,length:focus.range.length),with:Clipboard.general.string(forType:.string) ?? "")
 }
''' + methods.replace('NSPasteboard.general', 'Clipboard.general') + r'''}
let app = NSRunningApplication(), anchor = "Why does a wheel turn?", original = field.text
_ = try Hands.insertAfter(anchor," Answer α.",app)
let filled = original.replacingOccurrences(of:anchor,with:anchor + " Answer α.")
precondition(field.text == filled)
_ = try Hands.insertAfter(anchor," Answer α.",app)
precondition(field.text == filled && writes == 1, "duplicate request duplicated the answer")
_ = try Hands.insertAfter(anchor," Corrected β.",app)
precondition(field.text == original.replacingOccurrences(of:anchor,with:anchor + " Corrected β."), "repair changed unowned text")
field.text += " User note."
let edited = field.text, count = writes
do { _ = try Hands.insertAfter(anchor," Replacement.",app); fatalError("stale receipt accepted") } catch {}
precondition(field.text == edited && writes == count)
// A receipt survives a helper restart; a new ask has no ownership of an old answer.
try? FileManager.default.removeItem(atPath:Hands.env["ATTICUS_HANDS_STATE"]! + ".edits")
field.text = original; mutateOnCaret = true
let before = writes
do { _ = try Hands.insertAfter(anchor," Answer.",app); fatalError("concurrent edit accepted") } catch {}
precondition(field.text == "USER " + original && writes == before)
field.text = original; stealFocus = true
do { _ = try Hands.insertAfter(anchor," Answer.",app); fatalError("wrong focus accepted") } catch {}
precondition(field.text == original && keys.isEmpty && writes == before)
stealFocus = false; refuse = true
_ = try Hands.insertAfter(anchor," Pasted.",app)
precondition(field.text == original.replacingOccurrences(of:anchor,with:anchor + " Pasted.") && keys == ["cmd+v"])
_ = try Hands.insertAfter(anchor," Pasted.",app)
precondition(keys == ["cmd+v"], "duplicate paste")
// Missing anchors fail without changing the document.
field.text = "Edited question\nUser content"; let missing = field.text
do { _ = try Hands.insertAfter(anchor," Answer.",app); fatalError("missing anchor accepted") } catch {}
precondition(field.text == missing && keys == ["cmd+v"])
try FileManager.default.removeItem(atPath:Hands.env["ATTICUS_HANDS_STATE"]! + ".edits")
separate = true; field.text = ""; refuse = false
_ = try Hands.insertAfter(anchor," Separate answer.",app)
_ = try Hands.insertAfter(anchor," Corrected answer.",app)
precondition(field.text == " Corrected answer." && label.title == anchor && window.title == "Worksheet", "labelled worksheet repair changed surrounding text")
let kept = field.text; label.title = "Changed question"
do { _ = try Hands.insertAfter(anchor," Answer.",app); fatalError("stale label accepted") } catch {}
precondition(field.text == kept)
print("owned edit safety ok")
'''
            # These stubs contain no app/window lookup or event APIs.
            with patch.object(subprocess.Popen, '__init__', getattr(tests, '_popen_init', subprocess.Popen.__init__)):
                self.assertIn('owned edit safety ok', run_swift(self, swift.replace('ROOT/', root + '/')))
