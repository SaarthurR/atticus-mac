"""Opt-in live run of a real upgrade, VM only: public 1.6.0 installed by its own build.sh from a clone whose upstream is
a local bare repo, this tree published there as the next commit, then 1.6.0's own updater pulls, builds and restarts.
The box is opened with the real shortcut and shot. Needs tests/fixtures/atticus-1.6.0.bundle (git bundle of public main
at 5fcb891), which is not committed. The VM's installed app, prefs, config and login item are put back afterwards.
run.sh <repo> tests.shoot_update_real"""
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
BUNDLE = ROOT / 'tests' / 'fixtures' / 'atticus-1.6.0.bundle'
HOME = Path.home()
APP = HOME / 'Applications' / 'Atticus.app'
EXE = APP / 'Contents' / 'MacOS' / 'Atticus'
AGENT = HOME / 'Library' / 'LaunchAgents' / 'com.atticus.app.plist'
CONFIG = HOME / '.config' / 'atticus'
ENV = {k: v for k, v in os.environ.items() if k not in ('ATTICUS_DIR', 'ATTICUS_NO_RESTART')} | {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'}

DRIVE = r'''import Cocoa
// drive windows | ax <pid> | buttons <pid> | click <x> <y> | close <pid> | key <code> [ctrlopt]   (JSON out)
let a = CommandLine.arguments
func out(_ v: Any) { print(String(data: try! JSONSerialization.data(withJSONObject: v), encoding: .utf8)!) }
func attr(_ e: AXUIElement, _ k: String) -> AnyObject? { var v: AnyObject?; return AXUIElementCopyAttributeValue(e, k as CFString, &v) == .success ? v : nil }
func width(_ e: AXUIElement) -> Double { var s = CGSize.zero; if let v = attr(e, kAXSizeAttribute) { AXValueGetValue(v as! AXValue, .cgSize, &s) }; return Double(s.width) }
switch a[1] {
case "windows":
    let ws = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
    out(ws.map { w -> [String: Any] in
        let b = w[kCGWindowBounds as String] as? NSDictionary, n = { (k: String) in (b?[k] as? NSNumber)?.doubleValue ?? 0 }
        return ["owner": w[kCGWindowOwnerName as String] as? String ?? "", "pid": (w[kCGWindowOwnerPID as String] as? NSNumber)?.intValue ?? 0,
                "layer": w[kCGWindowLayer as String] as? Int ?? 0, "width": n("Width"), "frame": [n("X"), n("Y"), n("Width"), n("Height")],
                "alpha": (w[kCGWindowAlpha as String] as? NSNumber)?.doubleValue ?? 1, "sharing": (w[kCGWindowSharingState as String] as? NSNumber)?.intValue ?? -1] })
case "ax":
    var texts: [String] = []
    func walk(_ e: AXUIElement, _ depth: Int) {
        guard texts.count < 4000, depth < 40 else { return }
        for k in [kAXValueAttribute, kAXTitleAttribute, kAXDescriptionAttribute] { if let s = attr(e, k) as? String, !s.isEmpty { texts.append(s) } }
        for c in attr(e, kAXChildrenAttribute) as? [AXUIElement] ?? [] { walk(c, depth + 1) }
    }
    for w in attr(AXUIElementCreateApplication(pid_t(a[2])!), kAXWindowsAttribute) as? [AXUIElement] ?? [] { walk(w, 0) }
    out(texts)
case "buttons":
    var rows: [[String: Any]] = []
    func walk(_ e: AXUIElement, _ depth: Int) {
        guard rows.count < 400, depth < 40 else { return }
        if attr(e, kAXRoleAttribute) as? String == "AXButton", let p = attr(e, kAXPositionAttribute), let z = attr(e, kAXSizeAttribute) {
            var o = CGPoint.zero, s = CGSize.zero; AXValueGetValue(p as! AXValue, .cgPoint, &o); AXValueGetValue(z as! AXValue, .cgSize, &s)
            rows.append(["title": (attr(e, kAXTitleAttribute) as? String ?? "") + (attr(e, kAXDescriptionAttribute) as? String ?? ""), "x": o.x + s.width / 2, "y": o.y + s.height / 2, "w": s.width])
        }
        for c in attr(e, kAXChildrenAttribute) as? [AXUIElement] ?? [] { walk(c, depth + 1) }
    }
    for w in attr(AXUIElementCreateApplication(pid_t(a[2])!), kAXWindowsAttribute) as? [AXUIElement] ?? [] { walk(w, 0) }
    out(rows)
case "click":
    let at = CGPoint(x: Double(a[2])!, y: Double(a[3])!)
    CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: at, mouseButton: .left)?.post(tap: .cghidEventTap); usleep(120_000)
    for t in [CGEventType.leftMouseDown, .leftMouseUp] { CGEvent(mouseEventSource: nil, mouseType: t, mouseCursorPosition: at, mouseButton: .left)?.post(tap: .cghidEventTap); usleep(90_000) }
    out(["clicked": [at.x, at.y]])
case "close":   // setup's red button, as a person closes it
    var closed = 0
    for w in attr(AXUIElementCreateApplication(pid_t(a[2])!), kAXWindowsAttribute) as? [AXUIElement] ?? [] where width(w) >= 600 {
        if let b = attr(w, kAXCloseButtonAttribute) { if AXUIElementPerformAction(b as! AXUIElement, kAXPressAction as CFString) == .success { closed += 1 } }
    }
    out(["closed": closed])
case "key":   // ⌃⌥ held around the key, like fingers on the keyboard
    let mods: [(CGKeyCode, CGEventFlags)] = a.count > 3 && a[3] == "ctrlopt" ? [(59, .maskControl), (58, .maskAlternate)] : []
    var flags: CGEventFlags = []
    func post(_ code: CGKeyCode, _ down: Bool) { let e = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: down); e?.flags = flags; e?.post(tap: .cghidEventTap); usleep(60_000) }
    for (c, f) in mods { flags.insert(f); post(c, true) }
    post(CGKeyCode(a[2])!, true); usleep(150_000); post(CGKeyCode(a[2])!, false)
    for (c, f) in mods.reversed() { flags.remove(f); post(c, false) }
    out(["key": a[2]])
default: exit(2)
}
'''


def sh(*args, cwd=None, check=True, timeout=900):
    r = subprocess.run([str(a) for a in args], cwd=cwd, env=ENV, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode: raise AssertionError(f'{args} -> {r.returncode}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}')
    return r.stdout.strip()


def git(cwd, *args, check=True):
    return sh('git', '-C', cwd, '-c', 'user.name=Fixture Tester', '-c', 'user.email=fixture@example.com', *args, check=check)


def installed():
    try: return plistlib.loads((APP / 'Contents' / 'Info.plist').read_bytes())
    except (OSError, plistlib.InvalidFileException): return {}


def running():
    found = subprocess.run(['pgrep', '-fx', str(EXE)], capture_output=True, text=True).stdout.split()
    return int(found[0]) if found else None


WELCOME, MAC_ACCESS = 'Get Started', 'Allow Atticus to hear you'
DOTS = ('Meet Atticus', 'Pick an AI', 'Set up Mac access', 'Now try it', 'Dictation', 'Show me how', 'Help make Atticus better', 'Atticus is free and open source', 'Go use Atticus. Be great.')


def prefs_program(source, body):   # a build's own Prefs, compiled alone, against ~/.config/atticus/settings.json
    s = Path(source).read_text(); i = s.index('enum Prefs {')
    return 'import Cocoa\nimport Carbon\n' + s[i:s.index('\n}\n', i) + 3] + body


@unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'replaces the installed app: VM only')
class RealInstall(unittest.TestCase):
    def setUp(self):   # put the VM's own install aside: app, prefs, config, login item
        self.t0, self.lines, self.uid = time.time(), [], os.getuid()
        self.out = ROOT / 'test-artifacts' / self._testMethodName; shutil.rmtree(self.out, ignore_errors=True); self.out.mkdir(parents=True)
        self.tmp = Path(tempfile.mkdtemp()); self.keep = self.tmp / 'kept'; self.keep.mkdir()
        self.tool = self.tmp / 'drive'; (self.tmp / 'drive.swift').write_text(DRIVE)
        self.assertEqual(subprocess.run(['swiftc', str(self.tmp / 'drive.swift'), '-o', str(self.tool)]).returncode, 0)
        self.stop()
        stale = sorted({w['owner'] for w in self.drive('windows') or [] if w['owner'] in ('UserNotificationCenter', 'universalAccessAuthWarn')})
        if stale:   # a permission prompt left up by an earlier run's throwaway app
            self.note(f'closing stale permission prompts: {stale}'); [subprocess.run(['killall', o], capture_output=True) for o in stale]
        if AGENT.exists():   # the VM keeps its login item off (com.atticus.app.plist.off); a live one is left over from a run
            self.note(f'found {AGENT.name}, written {time.ctime(AGENT.stat().st_mtime)}, runs {plistlib.loads(AGENT.read_bytes()).get("ProgramArguments")}')
            if AGENT.with_name(AGENT.name + '.off').exists(): AGENT.unlink()
        self.had = {'app': APP.exists(), 'config': CONFIG.exists(), 'agent': AGENT.exists(),
                    'defaults': subprocess.run(['defaults', 'export', 'com.atticus.app', str(self.keep / 'defaults.plist')], capture_output=True).returncode == 0}
        if self.had['app']: shutil.move(APP, self.keep / 'Atticus.app')
        if self.had['config']: shutil.move(CONFIG, self.keep / 'config')
        if self.had['agent']: shutil.move(AGENT, self.keep / 'agent.plist')
        subprocess.run(['defaults', 'delete', 'com.atticus.app'], capture_output=True)
        self.note(f'VM install put aside: {self.had}')

    def tearDown(self):
        self.stop()
        shutil.rmtree(APP, ignore_errors=True); shutil.rmtree(CONFIG, ignore_errors=True); AGENT.unlink(missing_ok=True)
        subprocess.run(['defaults', 'delete', 'com.atticus.app'], capture_output=True)
        if self.had['app']: shutil.move(self.keep / 'Atticus.app', APP)
        if self.had['config']: shutil.move(self.keep / 'config', CONFIG)
        if self.had['agent']: shutil.move(self.keep / 'agent.plist', AGENT)
        if self.had['defaults']: subprocess.run(['defaults', 'import', 'com.atticus.app', str(self.keep / 'defaults.plist')], capture_output=True)
        subprocess.run(['/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister', '-f', str(APP)], capture_output=True)
        shutil.rmtree(self.tmp, ignore_errors=True)
        subprocess.run(['sync'])   # run.sh stops the VM right after; unflushed writes were lost and left this run's app installed
        print('VM install restored', flush=True)
        for png in sorted(self.out.glob('*.png')): print('PNG', f'{self._testMethodName}/{png.name}', base64.b64encode(png.read_bytes()).decode(), flush=True)
        print(f'SUMMARY {self._testMethodName}\n' + '\n'.join(self.lines), flush=True)

    def stop(self):
        subprocess.run(['launchctl', 'bootout', f'gui/{self.uid}/com.atticus.app'], capture_output=True)
        subprocess.run(['pkill', '-f', str(EXE)], capture_output=True); time.sleep(1)

    def drive(self, *args):
        r = subprocess.run([str(self.tool), *map(str, args)], capture_output=True, text=True, timeout=30)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def note(self, line):
        line = f'[{time.time() - self.t0:6.0f} s] {line}'; print(line, flush=True); self.lines.append(line)

    def shot(self, name):
        path = self.out / f'{len(list(self.out.glob("*.png"))) + 1:02d}-{name}.png'
        subprocess.run(['screencapture', '-x', str(path)]); self.note(f'shot {path.name}')

    def setup_open(self, pid):
        return bool(pid) and any(w['pid'] == pid and w['layer'] == 0 and w['width'] >= 600 for w in self.drive('windows') or [])

    def close_setup(self, pid):   # 1.6.0 opens setup when Claude is signed out (the VM's is); a person closes it
        if self.setup_open(pid): self.note(f'setup window open in pid {pid}: closing it {self.drive("close", pid)}')

    def texts(self, pid, want):
        for _ in range(10):   # WebKit builds its accessibility tree on the first ask
            found = [t for t in self.drive('ax', pid) or [] if want in t]
            if found: return found
            time.sleep(0.5)
        return []

    def press(self, pid, *titles):   # the first visible button with one of these names, clicked as a person would
        for _ in range(20):
            hit = next((b for b in self.drive('buttons', pid) or [] if b['title'] in titles and b['w'] > 0), None)
            if hit: self.drive('click', hit['x'], hit['y']); self.note(f'clicked {hit["title"]}'); return True
            time.sleep(0.5)
        return False

    def wait_running(self, other=None, seconds=40):
        deadline = time.time() + seconds
        while time.time() < deadline:
            pid = running()
            if pid and pid != other: return pid
            time.sleep(0.5)
        return None

    def signing(self):
        return {'identity': sh('security', 'find-identity', '-p', 'codesigning', check=False).count('Atticus Local Signing'),
                'requirement': subprocess.run(['codesign', '-d', '-r-', str(APP)], capture_output=True, text=True).stdout.strip()}

    def default(self, key): return sh('defaults', 'read', 'com.atticus.app', key, check=False) or 'unset'

    @unittest.skipUnless(BUNDLE.exists(), 'needs tests/fixtures/atticus-1.6.0.bundle')
    def test_160_updater_installs_this_tree_and_the_box_says_updated(self):
        tmp, src, version = self.tmp, self.tmp / 'Atticus', (ROOT / 'VERSION').read_text().strip()
        # Public 1.6.0, cloned from a bare upstream, as a person installs it.
        sh('git', 'clone', '-q', '--bare', BUNDLE, tmp / 'origin.git')
        sh('git', 'clone', '-q', tmp / 'origin.git', src)
        old = git(src, 'rev-parse', 'HEAD'); self.note(f'1.6.0 source at {old[:7]}, VERSION {(src / "VERSION").read_text().strip()}')
        self.assertTrue(old.startswith('5fcb891'))
        # His settings as 1.6.0 writes them: every 1.6.0 default saved along with the one he changed.
        (tmp / 'old.swift').write_text(prefs_program(src / 'Atticus.swift', '\nPrefs.set("hideWhenSharing", false)\n'))
        sh('swiftc', tmp / 'old.swift', '-o', tmp / 'old'); sh(tmp / 'old')
        saved = json.loads((CONFIG / 'settings.json').read_text())
        self.note(f'1.6.0 settings.json: {len(saved)} keys, speak={saved.get("speak")}, typeRight={saved.get("typeRight", "absent")}')
        sh('defaults', 'write', 'com.atticus.app', 'onboarded', '-bool', 'true')   # he finished setup on 1.6.0
        t = time.time(); sh('/bin/bash', src / 'build.sh', timeout=1500); self.note(f'1.6.0 build.sh done in {time.time() - t:.0f} s')
        self.note(f'installed {installed().get("CFBundleShortVersionString")} {installed().get("AtticusCommit", "")[:7]}; tree after build.sh: {git(src, "status", "--porcelain") or "clean"}')
        self.assertEqual(git(src, 'status', '--porcelain'), '', '1.6.0 build.sh left the tree dirty: its updater would skip (exit 5)')
        before = self.signing(); self.note(f'signing before: {before}')
        first = self.wait_running(); self.assertTrue(first, '1.6.0 did not start'); self.note(f'1.6.0 running, pid {first}')
        time.sleep(4); self.close_setup(first); self.shot('160-running')
        # Publish this tree upstream as the next commit.
        pub = tmp / 'publish'; sh('git', 'clone', '-q', tmp / 'origin.git', pub)
        git(pub, 'rm', '-rq', '.')
        for item in ROOT.iterdir():   # run.sh copied in this tree's tracked files, plus the uncommitted bundle
            if item.name in ('.git', 'test-artifacts', '__pycache__'): continue
            if item.is_dir(): shutil.copytree(item, pub / item.name, ignore=shutil.ignore_patterns('__pycache__', '*.bundle'))
            else: shutil.copy2(item, pub / item.name)
        git(pub, 'add', '-A'); git(pub, 'commit', '-qm', 'Atticus ' + version); git(pub, 'push', '-q')
        new = git(pub, 'rev-parse', 'HEAD'); self.note(f'published {new[:7]} on top of {old[:7]}')
        # 1.6.0's updater: a minute after launch it fetches, pulls, runs the new build.sh, then restarts once idle.
        deadline, built, second = time.time() + 1800, None, None
        while time.time() < deadline:
            self.close_setup(running())
            if not built and installed().get('AtticusCommit') == new: built = time.time(); self.note(f'new app installed: {installed().get("CFBundleShortVersionString")} {new[:7]}')
            pid = running()
            if built and pid and pid != first: second = pid; break
            time.sleep(3)
        self.assertTrue(built, '1.6.0 never installed the update')
        self.assertTrue(second, '1.6.0 installed the update but Atticus did not come back')
        self.note(f'restarted: pid {first} -> {second}, {time.time() - built:.0f} s after the new app landed')
        self.note(f'tree after the update: {git(src, "status", "--porcelain") or "clean"}, HEAD {git(src, "rev-parse", "HEAD")[:7]}')
        self.assertEqual(git(src, 'status', '--porcelain'), '', 'the update left the tree dirty: the next check would skip (exit 5)')
        after = self.signing(); self.note(f'signing after: {after}')
        time.sleep(5); self.close_setup(second)
        self.note('defaults after restart: ' + str({k: self.default(k) for k in ('lastBuild', 'updateNotice', 'installedUpdate')}))
        self.shot('200-running')
        self.drive('key', 49, 'ctrlopt'); time.sleep(2.0)
        first_open = self.texts(second, 'Updated to'); self.note(f'box opened: notice texts {first_open}')
        self.shot('box-first-open')
        self.drive('key', 53); time.sleep(1.5)
        self.drive('key', 49, 'ctrlopt'); time.sleep(2.0)
        second_open = self.texts(second, 'Updated to'); self.note(f'box opened again: notice texts {second_open}')
        self.shot('box-second-open')
        self.drive('key', 53); time.sleep(1)
        (tmp / 'new.swift').write_text(prefs_program(ROOT / 'Atticus.swift', '\nprint(["typeRight": Prefs.bool("typeRight"), "speak": Prefs.bool("speak"), "autoMinimize": Prefs.bool("autoMinimize"), "hideWhenSharing": Prefs.bool("hideWhenSharing")])\n'))
        sh('swiftc', tmp / 'new.swift', '-o', tmp / 'new'); self.note(f'{version} reads the 1.6.0 settings.json as {sh(tmp / "new")}')
        log = (CONFIG / 'app.err').read_text(errors='replace') if (CONFIG / 'app.err').exists() else ''
        self.note('app.err Launch lines: ' + ' | '.join(l[-90:] for l in log.splitlines() if 'Launch:' in l))
        tcc = subprocess.run(['sqlite3', str(HOME / 'Library/Application Support/com.apple.TCC/TCC.db'), "select service, auth_value from access where client='com.atticus.app'"], capture_output=True, text=True)
        self.note(f'TCC rows for com.atticus.app: {tcc.stdout.strip() or tcc.stderr.strip()[:200]}')
        self.assertEqual(before['requirement'], after['requirement'], 'the rebuild changed the signing requirement: macOS would ask for every permission again')
        self.assertTrue(any('Updated to ' + version in t for t in first_open), 'the first box after the update did not say Updated to')
        self.assertFalse(second_open, 'the notice showed twice')

    def test_setup_reopens_on_mac_access_after_quit_and_reopen(self):
        CONFIG.mkdir(parents=True); (CONFIG / 'settings.json').write_text('{"hideWhenSharing": false}')   # else setup is left out of the shots
        t = time.time(); sh('/bin/bash', ROOT / 'build.sh', timeout=1500); self.note(f'build.sh (fresh install) done in {time.time() - t:.0f} s')
        pid = self.wait_running(); self.assertTrue(pid, 'Atticus did not start')
        deadline = time.time() + 30
        while time.time() < deadline and not self.setup_open(pid): time.sleep(0.5)
        self.assertTrue(self.setup_open(pid), 'setup did not open on a fresh install')
        # Pages not shown are inert, so only the current one's own text is readable (the dots name every page).
        self.assertTrue(self.texts(pid, WELCOME), 'setup did not start on the welcome page'); self.shot('fresh-welcome')
        self.assertTrue(self.press(pid, 'Get Started')); time.sleep(1.5)
        self.assertTrue(self.press(pid, 'Continue', 'Skip for Now')); time.sleep(3)
        self.assertTrue(self.texts(pid, MAC_ACCESS), 'did not reach Mac access')
        self.note(f'on Mac access, setupPage={self.default("setupPage")}'); self.shot('mac-access-before-quit')
        # What macOS does after a permission switch: a Quit event, then LaunchServices opens the app again.
        quit_ = subprocess.run(['osascript', '-e', 'tell application id "com.atticus.app" to quit'], capture_output=True, text=True)
        deadline = time.time() + 15
        while time.time() < deadline and running() == pid: time.sleep(0.3)
        self.assertNotEqual(running(), pid, f'Atticus did not quit: {quit_.stderr}')
        self.note(f'quit by Apple event; setupPage={self.default("setupPage")}')
        sh('open', APP)   # this process carries the tests' scratch ATTICUS_DIR; LaunchServices must not hand it on
        again = self.wait_running(other=pid); self.assertTrue(again, 'Atticus did not reopen')
        self.note(f'reopened: pid {pid} -> {again}, ATTICUS_DIR in its environment: {"ATTICUS_DIR=" in sh("ps", "eww", "-o", "command=", "-p", again, check=False)}')
        deadline = time.time() + 30
        while time.time() < deadline and not self.setup_open(again): time.sleep(0.5)
        opened = time.time()
        for wait in (1, 3, 6):
            time.sleep(max(0, opened + wait - time.time()))
            self.note(f'+{wait} s after setup opened: windows {[{k: w[k] for k in ("layer", "frame", "alpha", "sharing")} for w in self.drive("windows") or [] if w["pid"] == again]}, front {sh("lsappinfo", "front", check=False)}')
            self.shot(f'after-reopen-{wait}s')
        on_perms, on_welcome = self.texts(again, MAC_ACCESS), self.texts(again, WELCOME)
        self.note(f'after reopen: Mac access={bool(on_perms)} welcome={bool(on_welcome)} buttons={[b["title"] for b in self.drive("buttons", again) or [] if b["w"] > 0 and not b["title"].startswith(DOTS)]}')
        self.assertTrue(on_perms and not on_welcome, 'setup restarted instead of reopening on Mac access')
        self.drive('close', again); time.sleep(1)
        self.note(f'closed setup; setupPage={self.default("setupPage")}')
        self.assertEqual(self.default('setupPage'), 'unset', 'closing setup must forget the page')


if __name__ == '__main__':
    unittest.main()
