"""A successful menu press must not be retried because optional AX metadata stalls afterward."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform=='darwin','macOS native replay')
class ReplayNativeTests(unittest.TestCase):
    def test_menu_success_has_no_post_press_accessibility_queries(self):
        source=(ROOT/'Atticus.swift').read_text()
        start=source.index('            if input[0] == "menu" {')
        branch=source[start:source.index('\n            }\n',start)+15]
        swift='''import Foundation
var presses=0
struct FixtureApp {}
enum WindowOption { case optionAll }
let kCGNullWindowID=0
func CGWindowListCopyWindowInfo(_ option:WindowOption,_ id:Int)->Any { precondition(presses==0);return [[String:Any]]() }
enum MiniScreen {
 static func windowTarget(_ app:FixtureApp,windows:[[String:Any]])->[String:Any]? { precondition(presses==0,"AX stopped responding after the accepted press");return ["app":"Fixture"] }
}
enum Prefs { static func bool(_ key:String)->Bool { true } }
enum Hands {
 struct Failure:Error { init(_ text:String) {} }
 static var claims=false,userWindowsFile:URL?=nil
 static func root(_ a:FixtureApp)throws->Int { 0 }
 static func app(_ name:String)throws->FixtureApp { FixtureApp() }
 static func menu(_ path:String,_ app:FixtureApp,act:Bool)throws->String { if act { presses+=1 };return "Start meeting" }
 static func riskyLabel(_ label:String)->Bool { false }
 static func systemUI()->[String:String] { precondition(presses==0); return [:] }
 static func openedSystemUI(_ before:[String:String])->String? { precondition(presses==1); return nil }
 static func quote(_ text:String)->String { text }
 static func call(_ input:[String])throws->Int32 {
''' + branch + '''
 return 1
 }
}
precondition(try! Hands.call(["menu","com.atticus.fixture","Fixture > Start meeting"])==0)
precondition(presses==1)
print("Accepted menu press completes once without post-action AX calls")
'''
        with tempfile.TemporaryDirectory(prefix='atticus-replay-native-') as tmp:
            root=Path(tmp);file=root/'replay.swift';file.write_text(swift);binary=root/'replay'
            result=subprocess.run(['swiftc',str(file),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
