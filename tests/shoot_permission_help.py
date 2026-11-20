"""Opt-in native permission-helper captures; fake Settings metadata, VM only."""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'native screenshots: VM only')
class PermissionHelpShots(unittest.TestCase):
    def test_drag_and_switch_helpers(self):
        source = (ROOT / 'Atticus.swift').read_text()
        help_source = source[source.index('final class PermissionIcon:'):source.index('// `Atticus --look')]
        help_source = help_source.replace('NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.systempreferences").first?.processIdentifier', 'Int32?(123)')
        help_source = help_source.replace('CGWindowListCopyWindowInfo(.optionOnScreenOnly, kCGNullWindowID) as? [[String: Any]] ?? []', '[[kCGWindowOwnerPID as String: NSNumber(value:123), kCGWindowLayer as String: 0]]')
        driver = r'''import Cocoa
func applySharing(_ w:NSWindow) {}
enum MiniScreen { static func bounds(_ value:[String:Any])->CGRect? {CGRect(x:200,y:80,width:600,height:340)} }
enum MeetingFrame {static func clamp(_ frame:NSRect,_ bounds:NSRect)->NSRect {frame}}
''' + help_source + r'''
NSApplication.shared.setActivationPolicy(.accessory)
let help=PermissionHelp()
func shot(_ drag:Bool) {
 help.show(drag:drag,target:"Atticus",granted:{false})
 DispatchQueue.main.asyncAfter(deadline:.now()+0.8) {
  guard let p=help.panel,let view=p.contentView else {fatalError("helper not shown")}
  let fields=view.subviews.compactMap {$0 as? NSTextField}
  let expected=drag ? "Drag the Atticus icon into the list above." : "Turn on Atticus in the list above."
  precondition(p.isVisible && fields.count==1 && fields[0].stringValue==expected)
  precondition((view.subviews.first {$0 is NSImageView} is PermissionIcon)==drag)
  precondition(fields[0].intrinsicContentSize.width <= fields[0].frame.width,"instruction clipped")
  let rep=view.bitmapImageRepForCachingDisplay(in:view.bounds)!
  view.cacheDisplay(in:view.bounds,to:rep)
  print("PERMISSION_HELP \(drag ? "drag" : "switch") " + rep.representation(using:.png,properties:[:])!.base64EncodedString())
  if drag {help.close();shot(false)} else {help.close();listed()}
 }
}
func listed() {   // already in the list: the line asks for the switch, the icon stays draggable (his rule, Nov 18)
 help.show(drag:true,target:"Atticus",granted:{false})
 DispatchQueue.main.asyncAfter(deadline:.now()+0.8) {
  help.listed()
  DispatchQueue.main.asyncAfter(deadline:.now()+0.8) {
   guard let p=help.panel,let view=p.contentView else {fatalError("helper closed when listed")}
   let fields=view.subviews.compactMap {$0 as? NSTextField}
   precondition(p.isVisible && fields.map(\.stringValue)==["Turn on Atticus in the list above."] && view.subviews.contains {$0 is PermissionIcon},"listed helper lost the icon to drag")
   let rep=view.bitmapImageRepForCachingDisplay(in:view.bounds)!
   view.cacheDisplay(in:view.bounds,to:rep)
   print("PERMISSION_HELP listed " + rep.representation(using:.png,properties:[:])!.base64EncodedString())
   help.close()
   help.show(drag:true,listed:true,target:"Atticus",granted:{false})   // macOS's own prompt listed it first
   DispatchQueue.main.asyncAfter(deadline:.now()+0.8) {
    guard let view=help.panel?.contentView else {fatalError("prompted helper not shown")}
    precondition(view.subviews.contains {$0 is PermissionIcon},"prompted helper has no icon to drag")
    help.close();print("permission helpers ok");exit(0)
   }
  }
 }
}
shot(true)
DispatchQueue.main.asyncAfter(deadline:.now()+10) {help.close();exit(1)}
NSApplication.shared.run()
'''
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / 'Atticus.app' / 'Contents'
            binary = app / 'MacOS' / 'Atticus'
            binary.parent.mkdir(parents=True)
            (app / 'Resources').mkdir()
            shutil.copy(ROOT / 'ui/AppIcon.icns', app / 'Resources/AppIcon.icns')
            (app / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'Atticus','CFBundleIdentifier':'local.atticus.permission-fixture','CFBundleName':'Atticus','CFBundleIconFile':'AppIcon'}))
            swift = Path(tmp) / 'helper.swift'; swift.write_text(driver)
            built = subprocess.run(['swiftc', str(swift), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn('permission helpers ok', run.stdout)
        for line in run.stdout.splitlines():
            if line.startswith('PERMISSION_HELP '): print(line, flush=True)
