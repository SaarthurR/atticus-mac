"""Opt-in live run of setup's Mac access rows in the real app, VM only: a fresh build and bundle ID, setup clicked top to
bottom as a person would (Accessibility, Microphone, Speech Recognition, Screen Recording), macOS's own dialogs answered
with real clicks, System Settings left open between rows. run.sh <repo> tests.shoot_setup_real"""
import base64
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]

DRIVE = r'''import Cocoa
// drive windows | ax <pid> | click <x> <y> | front | move <pid> <x> <y> | trusted   (top-left screen points, JSON out)
let a = CommandLine.arguments
func out(_ v: Any) { print(String(data: try! JSONSerialization.data(withJSONObject: v), encoding: .utf8)!) }
func attr(_ e: AXUIElement, _ k: String) -> AnyObject? { var v: AnyObject?; return AXUIElementCopyAttributeValue(e, k as CFString, &v) == .success ? v : nil }
func frame(_ e: AXUIElement) -> [Double] {
    var p = CGPoint.zero, s = CGSize.zero
    if let v = attr(e, kAXPositionAttribute) { AXValueGetValue(v as! AXValue, .cgPoint, &p) }
    if let v = attr(e, kAXSizeAttribute) { AXValueGetValue(v as! AXValue, .cgSize, &s) }
    return [p.x, p.y, s.width, s.height].map { Double($0) }
}
switch a[1] {
case "trusted": out(["trusted": AXIsProcessTrusted()])
case "front": let f = NSWorkspace.shared.frontmostApplication; out(["name": f?.localizedName ?? "", "bundle": f?.bundleIdentifier ?? "", "pid": Int(f?.processIdentifier ?? 0)])
case "windows":
    let ws = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
    out(ws.compactMap { w -> [String: Any]? in
        guard let b = (w[kCGWindowBounds as String] as? NSDictionary).flatMap({ CGRect(dictionaryRepresentation: $0) }) else { return nil }
        return ["owner": w[kCGWindowOwnerName as String] as? String ?? "", "pid": (w[kCGWindowOwnerPID as String] as? NSNumber)?.intValue ?? 0,
                "layer": w[kCGWindowLayer as String] as? Int ?? 0, "name": w[kCGWindowName as String] as? String ?? "",
                "frame": [b.minX, b.minY, b.width, b.height].map { Double($0) }]
    })
case "ax":
    var rows: [[String: Any]] = []
    func walk(_ e: AXUIElement, _ depth: Int) {
        guard rows.count < 4000, depth < 40 else { return }
        let role = attr(e, kAXRoleAttribute) as? String ?? ""
        rows.append(["role": role, "title": attr(e, kAXTitleAttribute) as? String ?? "", "desc": attr(e, kAXDescriptionAttribute) as? String ?? "",
                     "value": attr(e, kAXValueAttribute) as? String ?? "", "frame": frame(e)])
        for c in attr(e, kAXChildrenAttribute) as? [AXUIElement] ?? [] { walk(c, depth + 1) }
    }
    let app = AXUIElementCreateApplication(pid_t(a[2])!)
    for w in attr(app, kAXWindowsAttribute) as? [AXUIElement] ?? [] { walk(w, 0) }
    out(rows)
case "move":
    let app = AXUIElementCreateApplication(pid_t(a[2])!)
    let ws = (attr(app, kAXWindowsAttribute) as? [AXUIElement] ?? []).sorted { frame($0)[2] * frame($0)[3] > frame($1)[2] * frame($1)[3] }
    var p = CGPoint(x: Double(a[3])!, y: Double(a[4])!)
    if let w = ws.first, let v = AXValueCreate(.cgPoint, &p) { out(["moved": AXUIElementSetAttributeValue(w, kAXPositionAttribute as CFString, v) == .success]) } else { out(["moved": false]) }
case "click":
    let at = CGPoint(x: Double(a[2])!, y: Double(a[3])!)
    CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: at, mouseButton: .left)?.post(tap: .cghidEventTap); usleep(120_000)
    for t in [CGEventType.leftMouseDown, .leftMouseUp] { CGEvent(mouseEventSource: nil, mouseType: t, mouseCursorPosition: at, mouseButton: .left)?.post(tap: .cghidEventTap); usleep(90_000) }
    out(["clicked": [at.x, at.y]])
default: exit(2)
}
'''

ROWS = ['Accessibility', 'Microphone', 'Speech Recognition', 'Screen & System Audio Recording']
ANSWERS = ['Open System Settings', 'Allow', 'OK']   # what a person clicks on macOS's own box to go on


@unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'real app and real System Settings: VM only')
class RealSetup(unittest.TestCase):
    def drive(self, *args):
        run = subprocess.run([str(self.tool), *map(str, args)], capture_output=True, text=True, timeout=30)
        return json.loads(run.stdout) if run.stdout.strip() else None

    def windows(self): return self.drive('windows') or []

    def setup_window(self):
        return next((w for w in self.windows() if w['pid'] == self.pid and w['layer'] == 0 and w['frame'][2] > 500), None)

    def state(self, label):   # what is in front, where setup and Settings sit, and what the helper shows
        ws, front = self.windows(), self.drive('front') or {}
        mine = [i for i, w in enumerate(ws) if w['pid'] == self.pid and w['layer'] == 0 and w['frame'][2] > 500]
        settings = [i for i, w in enumerate(ws) if w['owner'] == 'System Settings' and w['layer'] == 0 and w['frame'][2] > 100]
        helper = [w for w in ws if w['pid'] == self.pid and w['layer'] == 3]
        order = 'setup hidden' if not mine else 'no Settings window' if not settings else 'setup in front' if mine[0] < settings[0] else 'Settings in front'
        drag = None
        if helper:   # 390 wide with the draggable icon, 330 with the switch line only (PermissionHelp.fill)
            drag = helper[0]['frame'][2] > 360
        dialogs = sorted({w['owner'] for w in ws if w['owner'] in ('universalAccessAuthWarn', 'UserNotificationCenter', 'CoreServicesUIAgent')})
        line = f"STATE {label}: front={front.get('name')} {order} helper={'none' if not helper else 'drag icon' if drag else 'no drag icon'} dialogs={dialogs or '-'}"
        print(line, flush=True); self.lines.append(line)
        shot = self.out / f"{len(self.lines):02d}-{label.replace(' ', '-').replace('&', 'and').lower()}.png"
        subprocess.run(['screencapture', '-x', str(shot)])
        seen = {'label': label, 'front': front.get('name'), 'order': order, 'helper': drag, 'dialogs': dialogs}
        self.states.append(seen)
        return seen

    def ax(self, pid): return self.drive('ax', pid) or []

    def click_center(self, f): self.drive('click', f[0] + f[2] / 2, f[1] + f[3] / 2)

    def row_allow(self, name):   # the Allow button after the row's name, in document order
        seen = None
        for r in self.ax(self.pid):
            if r['role'] == 'AXStaticText' and r['value'] in ROWS: seen = r['value']
            if r['role'] == 'AXButton' and (r['title'] or r['desc'] or r['value']) in ('Allow', 'Waiting') and seen == name and r['frame'][2] > 0:
                return r['frame']
        return None

    def uncover(self, f):   # Settings left open over setup's button: a person moves it aside first
        x, y = f[0] + f[2] / 2, f[1] + f[3] / 2
        for w in self.windows():
            wx, wy, ww, wh = w['frame']
            if not (wx <= x <= wx + ww and wy <= y <= wy + wh): continue
            if w['pid'] == self.pid: return
            if w['owner'] == 'System Settings' and w['layer'] == 0:
                setup = self.setup_window()['frame']
                moved = self.drive('move', w['pid'], setup[0] + setup[2] + 10, wy)
                print(f'moved System Settings aside: {moved}', flush=True); time.sleep(1.0); return

    def answer_dialog(self, before):
        deadline = time.time() + 8
        while time.time() < deadline:
            new = [w for w in self.windows() if w['owner'] in ('universalAccessAuthWarn', 'UserNotificationCenter', 'CoreServicesUIAgent') and w['owner'] not in before]
            if new:
                time.sleep(1.0)
                self.state(f'{self.row} dialog up')
                pid = new[0]['pid']
                buttons = [r for r in self.ax(pid) if r['role'] == 'AXButton']
                titles = [b['title'] or b['desc'] for b in buttons]
                pick = next((b for want in ANSWERS for b in buttons if (b['title'] or b['desc']) == want), None)
                print(f"dialog {new[0]['owner']} buttons={titles} -> {pick and (pick['title'] or pick['desc'])}", flush=True)
                if pick: self.click_center(pick['frame']); return new[0]['owner']
                return None
            time.sleep(0.2)
        return None

    def test_his_order(self):
        self.out = ROOT / 'test-artifacts' / 'setup-real'; shutil.rmtree(self.out, ignore_errors=True); self.out.mkdir(parents=True)
        self.lines, self.states = [], []
        ident = f'local.atticus.perm2.{os.getpid()}'
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self.tool = tmp / 'drive'; (tmp / 'drive.swift').write_text(DRIVE)
            self.assertEqual(subprocess.run(['swiftc', str(tmp / 'drive.swift'), '-o', str(self.tool)]).returncode, 0)
            print('runner', self.drive('trusted'), 'macOS', subprocess.run(['sw_vers', '-productVersion'], capture_output=True, text=True).stdout.strip(),
                  'displays', len([w for w in self.windows() if w['owner'] == 'Window Server' and w['name'] == 'Menubar']), flush=True)
            app = tmp / 'Atticus.app' / 'Contents'
            (app / 'MacOS').mkdir(parents=True); (app / 'Resources' / 'ui').mkdir(parents=True)
            shutil.copy(ROOT / 'atticus.py', app / 'Resources')
            for f in list((ROOT / 'ui').glob('*.html')) + list((ROOT / 'ui').glob('*.js')) + list((ROOT / 'ui').glob('*.css')): shutil.copy(f, app / 'Resources' / 'ui')
            shutil.copy(ROOT / 'ui/AppIcon.icns', app / 'Resources')
            (app / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': ident, 'CFBundleName': 'Atticus', 'CFBundleExecutable': 'Atticus', 'CFBundlePackageType': 'APPL',
                'CFBundleIconFile': 'AppIcon', 'LSUIElement': True, 'CFBundleShortVersionString': '0.0.1', 'CFBundleVersion': '1',
                'NSMicrophoneUsageDescription': 'Atticus listens when you use its shortcut.', 'NSSpeechRecognitionUsageDescription': 'Atticus turns your words into text.'}))
            t = time.time()
            built = subprocess.run(['swiftc', '-target', f"{os.uname().machine}-apple-macos26.0", str(ROOT / 'Atticus.swift'), '-o', str(app / 'MacOS' / 'Atticus')], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr[-3000:])
            print(f'built in {time.time() - t:.0f} s', flush=True)
            subprocess.run(['codesign', '-s', '-', '--force', str(app.parent)], capture_output=True)
            subprocess.run(['/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister', '-f', str(app.parent)])
            subprocess.run(['killall', 'System Settings'], capture_output=True)
            data = tmp / 'data'; data.mkdir(); log = tmp / 'app.err'; log.touch()
            (data / 'settings.json').write_text('{"hideWhenSharing": false}')   # else setup and the helper are left out of the shots
            opened = subprocess.Popen(['open', '-W', '-n', '--env', f'ATTICUS_DIR={data}', '--stdout', str(log), '--stderr', str(log), str(app.parent)])
            try:
                deadline = time.time() + 40
                self.pid = None
                while time.time() < deadline and not self.pid:
                    found = subprocess.run(['pgrep', '-f', str(app / 'MacOS' / 'Atticus')], capture_output=True, text=True).stdout.split()
                    self.pid = int(found[0]) if found else None; time.sleep(0.5)
                self.assertTrue(self.pid, 'app did not start')
                while time.time() < deadline and not self.setup_window(): time.sleep(0.5)
                self.assertTrue(self.setup_window(), 'setup did not open')
                time.sleep(2.0)
                asked = {k: subprocess.run(['defaults', 'read', ident, k], capture_output=True, text=True).stdout.strip() or 'unset' for k in ('askedAX', 'askedScreen', 'onboarded')}
                print(f'prefs right after launch: {asked}', flush=True); self.lines.append(f'prefs right after launch: {asked}')
                self.drive('move', self.pid, 20, 60); time.sleep(0.5)
                for _ in range(2):   # welcome, the AI, then the Mac access rows
                    nxt, tries = None, 0
                    while not nxt and tries < 20:   # WebKit builds its accessibility tree on the first ask
                        rows = self.ax(self.pid); tries += 1
                        nxt = next((r for r in rows if r['role'] == 'AXButton' and (r['title'] or r['desc'] or r['value']) in ('Get Started', 'Continue', 'Skip for Now') and r['frame'][2] > 0), None)
                        if not nxt: time.sleep(0.5)
                    if not nxt: print('AX', [(r['role'], r['title'], r['desc'], r['value']) for r in rows][:120], flush=True)
                    self.assertTrue(nxt, 'no Continue button'); self.click_center(nxt['frame']); time.sleep(1.5)
                self.state('setup on Mac access')
                for self.row in ROWS:
                    f = self.row_allow(self.row)
                    if not f: print(f'{self.row}: no Allow button (already on?)', flush=True); continue
                    self.uncover(f); f = self.row_allow(self.row)
                    before = {w['owner'] for w in self.windows()}
                    self.click_center(f)
                    print(f'clicked {self.row} Allow', flush=True)
                    answered = self.answer_dialog(before)
                    if not answered: time.sleep(2.0); self.state(f'{self.row} no dialog'); continue
                    time.sleep(2.5); self.state(f'{self.row} answered')
                    time.sleep(2.5); self.state(f'{self.row} settled')
                asked = {k: subprocess.run(['defaults', 'read', ident, k], capture_output=True, text=True).stdout.strip() or 'unset' for k in ('askedAX', 'askedScreen')}
                print(f'prefs at end: {asked}', flush=True)
            finally:
                subprocess.run(['pkill', '-f', str(app / 'MacOS' / 'Atticus')], capture_output=True)
                try: opened.wait(timeout=10)
                except subprocess.TimeoutExpired: opened.kill()
                subprocess.run(['killall', 'System Settings'], capture_output=True)
                subprocess.run(['tccutil', 'reset', 'All', ident], capture_output=True)
                print('APP LOG\n' + '\n'.join(l for l in log.read_text(errors='replace').splitlines() if 'Setup:' in l or 'Focus guard' in l), flush=True)
        for png in sorted(self.out.glob('*.png')): print('PNG', png.name, base64.b64encode(png.read_bytes()).decode(), flush=True)
        print('SUMMARY\n' + '\n'.join(self.lines), flush=True)
        # His rule: Settings up for Accessibility or Screen Recording always comes with the icon to drag;
        # Microphone and Speech, answered on macOS's popup, leave setup in front.
        for s in self.states:
            row = next((r for r in ROWS if s['label'].startswith(r)), None)
            if s['label'].endswith(('answered', 'settled')) and row in ('Accessibility', 'Screen & System Audio Recording') and s['order'] != 'no Settings window':
                self.assertTrue(s['helper'], f"{s['label']}: Settings up without the icon to drag")
            if s['label'].endswith(('answered', 'settled')) and row in ('Microphone', 'Speech Recognition'):
                self.assertEqual(s['front'], 'Atticus', f"{s['label']}: {s['front']} came forward")
                self.assertNotEqual(s['order'], 'Settings in front', s['label'])


if __name__ == '__main__':
    unittest.main()
