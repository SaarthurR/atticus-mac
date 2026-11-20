"""VM only: Atticus never sees itself. A page app sits under a window that has Atticus's own bundle id (an agent, setup or Settings
in front); every way of reading the screen or the current app must return the page, never that window."""
import json
import os
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = 'com.atticus.selftest'
FIXTURE = r'''import Cocoa
let page = CommandLine.arguments[1] == "page"
NSApplication.shared.setActivationPolicy(.regular)
let w = NSWindow(contentRect: page ? NSRect(x: 200, y: 200, width: 600, height: 400) : NSRect(x: 250, y: 220, width: 500, height: 360), styleMask: [.titled], backing: .buffered, defer: false)
w.title = page ? "SELF PAGE TAG" : "SELF COVER TAG"
let v = NSView(); v.wantsLayer = true
v.layer?.backgroundColor = (page ? NSColor(srgbRed: 0, green: 0.78, blue: 1, alpha: 1) : NSColor(srgbRed: 1, green: 0, blue: 1, alpha: 1)).cgColor
if page { let b = NSButton(title: "Page button TAG", target: nil, action: nil); b.frame = NSRect(x: 200, y: 150, width: 200, height: 100); v.addSubview(b) }
w.contentView = v
if !page { w.level = .floating; w.sharingType = .readOnly }   // shown to screen shares, as the trail is: only the bundle id keeps it out
w.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
let s = NSScreen.screens[0].frame; print(Int(s.width), Int(s.height)); fflush(stdout)
NSApp.run()
'''
SHOT = r'''import Cocoa
import ScreenCaptureKit
_ = NSApplication.shared
enum MiniScreen {
FUNC
}
let a = CommandLine.arguments
let mine = (CGWindowListCopyWindowInfo(.optionOnScreenOnly, kCGNullWindowID) as? [[String:Any]] ?? []).filter {
    ($0[kCGWindowOwnerPID as String] as? NSNumber).flatMap { NSRunningApplication(processIdentifier: $0.int32Value) }?.bundleIdentifier == Bundle.main.bundleIdentifier
}.compactMap { ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value }
print(MiniScreen.shot(CGRect(x: Double(a[1])!, y: Double(a[2])!, width: 40, height: 40), keep: a.count > 4 ? Set(mine) : [], to: a[3]) ? "ok" : "fail")
'''


def pixel(jpg, x, y):
    out = Path(str(jpg) + '.bmp')
    subprocess.run(['sips', '-s', 'format', 'bmp', str(jpg), '--out', str(out)], check=True, capture_output=True)
    data = out.read_bytes()
    offset, = struct.unpack_from('<I', data, 10); width, height = struct.unpack_from('<ii', data, 18); bpp, = struct.unpack_from('<H', data, 28)
    row = (width * bpp // 8 + 3) & ~3
    line = int(y) if height < 0 else abs(height) - 1 - int(y)
    b, g, r = data[offset + line * row + int(x) * (bpp // 8):][:3]
    return r, g, b


def magenta(rgb): return rgb[0] > 200 and rgb[1] < 80 and rgb[2] > 200
def cyan(rgb): return rgb[0] < 80 and rgb[1] > 150 and rgb[2] > 200


@unittest.skipUnless(os.environ.get('ATTICUS_VM') == '1' and sys.platform == 'darwin', 'real windows and screen capture: VM only')
class SelfInvisibleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='atticus-self-'); root = cls.root = Path(cls.tmp.name)
        def build(name, source, ident):
            src = root / f'{name}.swift'; src.write_text(source)
            app = root / f'{name}.app' / 'Contents'; (app / 'MacOS').mkdir(parents=True)
            r = subprocess.run(['swiftc', str(src), '-o', str(app / 'MacOS' / name)], capture_output=True, text=True)
            if r.returncode: raise AssertionError(r.stderr)
            with open(app / 'Info.plist', 'wb') as f:
                plistlib.dump({'CFBundleIdentifier': ident, 'CFBundleName': name, 'CFBundleExecutable': name, 'CFBundlePackageType': 'APPL'}, f)
            return str(app / 'MacOS' / name)
        cls.binary = build('Atticus', (ROOT / 'Atticus.swift').read_text(), ID)
        func = re.search(r'    static func shot\(.*?\n    \}\n', (ROOT / 'Atticus.swift').read_text(), re.S)
        cls.shot = build('Shot', SHOT.replace('FUNC', func.group(0) if func else ''), ID)
        cls.cover_bin = build('Cover', FIXTURE, ID)
        page_bin = build('FixturePage', FIXTURE, 'com.atticus.fixture-page')
        cls.env = {k: v for k, v in os.environ.items() if not k.startswith('ATTICUS_') or k == 'ATTICUS_VM'}
        (root / 'config').mkdir()
        cls.env.update(ATTICUS_DIR=str(root / 'config'), ATTICUS_APP=cls.binary, ATTICUS_RESOURCES_DIR=str(ROOT), ATTICUS_POSTHOG_KEY='')
        cls.page = subprocess.Popen([page_bin, 'page'], stdout=subprocess.PIPE, text=True)
        cls.page.stdout.readline(); time.sleep(1)
        cls.cover = subprocess.Popen([cls.cover_bin, 'cover'], stdout=subprocess.PIPE, text=True)
        cls.width, cls.height = map(int, cls.cover.stdout.readline().split()); time.sleep(1.5)
        if 'Allow Atticus' in cls.run_app('--hands', 'see', '2147483647'):
            raise unittest.SkipTest('Temporary binary lacks Accessibility permission; no permission changes made')

    @classmethod
    def tearDownClass(cls):
        for p in (cls.cover, cls.page):
            p.terminate(); p.wait(timeout=5)
        cls.tmp.cleanup()

    @classmethod
    def run_app(cls, *args, binary=None):
        r = subprocess.run([binary or cls.binary, *args], env=cls.env, capture_output=True, text=True, timeout=30)
        return r.stdout + r.stderr

    def top(self, x, y):   # Cocoa bottom-left point -> top-left screen point
        return x, self.height - y

    def setUp(self):
        front = subprocess.run(['osascript', '-l', 'JavaScript', '-e', 'ObjC.import("AppKit");$.NSWorkspace.sharedWorkspace.frontmostApplication.bundleIdentifier.js'],
                               capture_output=True, text=True).stdout.strip()
        self.assertEqual(front, ID, 'the Atticus-owned cover window must be the front app for this check')

    def test_current_app_is_the_one_under_atticus(self):
        self.assertEqual(self.run_app('--user-app').strip(), 'FixturePage')
        seen = self.run_app('--hands', 'see')
        self.assertIn('Page button TAG', seen); self.assertNotIn('COVER', seen)
        target = json.loads(next((l for l in self.run_app('--draw-target').splitlines() if l.startswith('{')), '{}'))
        self.assertEqual(target.get('app'), 'FixturePage')
        r = subprocess.run([sys.executable, '-c', 'import atticus; atticus.osa = lambda *a, **k: ""; print(atticus.front()[0])'], cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stdout.strip(), 'FixturePage', r.stderr[-2000:])

    def test_pictures_leave_out_atticus_windows(self):
        out = self.root / 'look.jpg'
        x, y = self.top(300, 260)   # under the cover, on the page's background
        bx, by = self.top(500, 400)   # the page's button, under the cover
        scale = 1280 / self.width
        gesture = {'kind': 'point', 'path': [[bx * scale, by * scale]], 'spots': [[1, bx * scale, by * scale]], 'box': [], 'scale': 1}
        said = self.run_app('--look', '1', str(out), '', json.dumps(gesture))
        self.assertTrue(out.exists(), said)
        self.assertTrue(cyan(pixel(out, x * scale, y * scale)), pixel(out, x * scale, y * scale))
        self.assertIn('Page button TAG', said, 'the control under a gesture is the page\'s, not the Atticus window over it')

        crop = self.root / 'crop.jpg'
        self.assertEqual(self.run_app(str(x - 20), str(y - 20), str(crop), binary=self.shot).strip(), 'ok')
        self.assertTrue(cyan(pixel(crop, 20, 20)), 'a marked region leaves out Atticus windows')
        kept = self.root / 'kept.jpg'
        self.assertEqual(self.run_app(str(x - 20), str(y - 20), str(kept), 'keep', binary=self.shot).strip(), 'ok')
        self.assertTrue(magenta(pixel(kept, 20, 20)), 'the user\'s marks (kept windows) stay in the crop')


if __name__ == '__main__':
    unittest.main()
