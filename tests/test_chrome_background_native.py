"""Opt-in Chrome integration: only uniquely titled pages in a fresh --user-data-dir."""
import json
import os
import plistlib
import re
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import functools
import http.server
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import atticus

CHROME = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')


@unittest.skipUnless(os.environ.get('ATTICUS_VM') == '1' and sys.platform == 'darwin' and CHROME.exists(),
                     'Isolated Chrome profile requires ATTICUS_VM=1 and macOS Chrome')
class ChromeBackgroundTests(unittest.TestCase):
    def test_automation_preflight_only_skips_denial_or_consent(self):
        for code in (0, -1743, -1744, -600, -10000):
            with self.subTest(code=code), patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, str(code), '')), \
                 patch.object(time, 'monotonic', side_effect=[0, 6]):
                if code in (-1743, -1744):
                    with self.assertRaises(unittest.SkipTest): self.require_automation('fixture')
                elif code:
                    with self.assertRaises(AssertionError): self.require_automation('fixture')
                else:
                    self.require_automation('fixture')
        with patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired('osascript', 3)):
            with self.assertRaises(subprocess.TimeoutExpired): self.require_automation('fixture')
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'unrelated error')):
            with self.assertRaises(AssertionError): self.require_automation('fixture')

    def require_automation(self, bundle):
        script = '''ObjC.import('Foundation');ObjC.import('Carbon');
ObjC.bindFunction('AEDeterminePermissionToAutomateTarget',['int',['void *','unsigned int','unsigned int','bool']]);
const target=$.NSAppleEventDescriptor.descriptorWithBundleIdentifier(''' + json.dumps(bundle) + ''');
$.AEDeterminePermissionToAutomateTarget(target.aeDesc,0x2a2a2a2a,0x2a2a2a2a,false);'''
        deadline = time.monotonic() + 5
        while True:
            probe = subprocess.run(['osascript', '-l', 'JavaScript', '-e', script], capture_output=True, text=True, timeout=3)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            code = int(probe.stdout.strip())
            if code != -600 or time.monotonic() >= deadline: break   # the scratch app must finish launching before this API can check it
            time.sleep(.05)
        if code in (-1743, -1744): self.skipTest(f'VM Automation permission for {bundle} is denied or requires user consent ({code}); no prompt requested')
        self.assertEqual(code, 0, f'Automation probe for {bundle} failed: {code}')

    def test_native_fullscreen_placement_repeats_without_toggling(self):
        subprocess.run(['open', '-g', '-b', 'com.apple.systemevents'], check=True, capture_output=True)
        self.require_automation('com.apple.systemevents')
        with tempfile.TemporaryDirectory(prefix='atticus-place-') as tmp:
            root=Path(tmp); marker='Atticus placement '+root.name
            page=root/'page.html';page.write_text('<title>'+marker+'</title><p>Scratch placement</p>')
            with (root/'chrome.log').open('w') as log:
                process=subprocess.Popen([str(CHROME),f'--user-data-dir={root / "profile"}','--no-first-run','--no-default-browser-check','--disable-sync',page.as_uri()],stdout=log,stderr=log,start_new_session=True)
                try:
                    selector=f'tell application "System Events" to tell process "Google Chrome" to get value of attribute "AXFullScreen" of (first window whose name contains "{marker}")'
                    deadline=time.monotonic()+15
                    probe=None
                    while time.monotonic()<deadline:
                        probe=subprocess.run(['osascript','-e',selector],capture_output=True,text=True,timeout=3)
                        if probe.stdout.strip() in ('true','false'): break
                        if 'not allowed' in probe.stderr.lower() or 'not authorized' in probe.stderr.lower() or '(-1743)' in probe.stderr: self.skipTest(probe.stderr.strip())
                        time.sleep(.2)
                    else: self.fail('Scratch Chrome window not accessible: '+(probe.stderr if probe else '')+(root/'chrome.log').read_text()[-1000:])
                    with patch.object(atticus,'preview_app'),patch.object(atticus,'free_focus'):
                        screen=atticus.screens()[0][0]
                        reply=atticus.place('Google Chrome','fullscreen',screen,marker)
                        self.assertNotIn('NOT DONE',reply);self.assertNotIn('could not check',reply)
                        self.assertEqual(atticus.osa(selector),'true',reply)
                        # Use the actual screen name so the already-in-place path applies on the VM's virtual display.
                        again=atticus.place('Google Chrome','fullscreen',screen,marker)
                        self.assertIn('already full screen',again)
                        self.assertEqual(atticus.osa(selector),'true',again)
                finally:
                    os.killpg(process.pid,signal.SIGTERM)
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: os.killpg(process.pid,signal.SIGKILL);process.wait()

    def test_left_and_right_from_full_screen_fill_their_halves(self):
        """Saarth's Nov 21 case: both windows start in native full screen; after --place A left + B right each fills its half, no overlap.
        The guest refuses Apple events to System Events, so its window reads and writes go to the same AX attributes directly."""
        with tempfile.TemporaryDirectory(prefix='atticus-halves-') as tmp:
            root = Path(tmp); left, right = 'Atticus left ' + root.name, 'Atticus right ' + root.name
            (root / 'ax.swift').write_text('''import Cocoa
// ax <pid> <title words> get | fs true|false | min true|false | size w h | pos x y: one window, as System Events reads and sets it
let a = CommandLine.arguments, app = AXUIElementCreateApplication(pid_t(a[1])!)
func attr(_ e: AXUIElement, _ k: String) -> CFTypeRef? { var v: CFTypeRef?; AXUIElementCopyAttributeValue(e, k as CFString, &v); return v }
guard let w = (attr(app, kAXWindowsAttribute) as? [AXUIElement] ?? []).first(where: { (attr($0, kAXTitleAttribute) as? String ?? "").contains(a[2]) }) else { exit(1) }
var p = CGPoint.zero, s = CGSize.zero
switch a[3] {
case "get":
    guard let pv = attr(w, kAXPositionAttribute), let sv = attr(w, kAXSizeAttribute) else { exit(1) }
    AXValueGetValue(pv as! AXValue, .cgPoint, &p); AXValueGetValue(sv as! AXValue, .cgSize, &s)
    print("\\(attr(w, "AXFullScreen") as? Bool ?? false), \\(attr(w, kAXMinimizedAttribute) as? Bool ?? false), \\(Int(p.x)), \\(Int(p.y)), \\(Int(s.width)), \\(Int(s.height))")
case "fs", "min": exit(AXUIElementSetAttributeValue(w, (a[3] == "fs" ? "AXFullScreen" : kAXMinimizedAttribute) as CFString, (a[4] == "true" ? kCFBooleanTrue : kCFBooleanFalse)!) == .success ? 0 : 2)
case "size": s = CGSize(width: Double(a[4])!, height: Double(a[5])!); exit(AXUIElementSetAttributeValue(w, kAXSizeAttribute as CFString, AXValueCreate(.cgSize, &s)!) == .success ? 0 : 2)
default: p = CGPoint(x: Double(a[4])!, y: Double(a[5])!); exit(AXUIElementSetAttributeValue(w, kAXPositionAttribute as CFString, AXValueCreate(.cgPoint, &p)!) == .success ? 0 : 2)
}
''')
            ax_bin = root / 'ax'
            subprocess.run(['swiftc', str(root / 'ax.swift'), '-o', str(ax_bin)], check=True, capture_output=True)
            (root / 'page.html').write_text(f'<title>{left}</title><p>Scratch left</p>')
            (root / f'{right}.txt').write_text('Scratch right')
            log = (root / 'chrome.log').open('w')
            chrome = subprocess.Popen([str(CHROME), f'--user-data-dir={root / "profile"}', '--no-first-run', '--no-default-browser-check', '--disable-sync',
                                       '--use-mock-keychain', (root / 'page.html').as_uri()], stdout=log, stderr=log, start_new_session=True)
            subprocess.run(['open', '-a', 'TextEdit', str(root / f'{right}.txt')], check=True, capture_output=True)
            pids = {'Google Chrome': chrome.pid}
            ax = lambda proc, name, *cmd: subprocess.run([str(ax_bin), str(pids[proc]), name, *cmd], capture_output=True, text=True, timeout=5)
            trace, t0 = [], time.monotonic()
            def osa(script, *args, timeout=60):
                out = send(script)
                trace.append(f'{time.monotonic() - t0:.1f} {threading.current_thread().name[-1]} {re.sub(r".*tell process ", "", script)[:90]} => {out}')
                return out
            def send(script):   # the System Events scripts place() sends
                if m := re.search(r'exists process "([^"]+)"', script): return 'true' if m[1] in pids else 'false'
                m = re.search(r'tell process "([^"]+)" to .*first window whose name is "([^"]+)"', script)
                if not m or m[1] not in pids: return ''
                if 'AXMinimized", position, size}' in script: return ax(m[1], m[2], 'get').stdout.strip()
                if 'return {position, size}' in script: return ', '.join(ax(m[1], m[2], 'get').stdout.strip().split(', ')[2:])
                if 'get value of attribute "AXFullScreen"' in script: return ax(m[1], m[2], 'get').stdout.split(',')[0]
                if s := re.search(r'set value of attribute "AX(FullScreen|Minimized)" of .+ to (true|false)', script): ax(m[1], m[2], {'FullScreen': 'fs', 'Minimized': 'min'}[s[1]], s[2])
                elif s := re.search(r'set (size|position) of .+ to \{(-?\d+), (-?\d+)\}', script): ax(m[1], m[2], {'size': 'size', 'position': 'pos'}[s[1]], s[2], s[3])
                return ''
            state = lambda proc, name: ax(proc, name, 'get').stdout.strip()
            def wait(proc, name, full):
                deadline, last, now = time.monotonic() + 60, None, ''
                while time.monotonic() < deadline:
                    now = state(proc, name)
                    if now.startswith(full) and now == last: return now
                    last = now; time.sleep(.3)
                self.fail(f'{proc} scratch window never reached full screen={full}: {now!r} ' + (root / 'chrome.log').read_text()[-1000:])
            try:
                for _ in range(50):
                    if (found := subprocess.run(['pgrep', '-x', 'TextEdit'], capture_output=True, text=True).stdout.split()): pids['TextEdit'] = int(found[0]); break
                    time.sleep(.2)
                if 'kAXErrorAPIDisabled' in ax('Google Chrome', left, 'get').stderr: self.skipTest('Temporary binary lacks Accessibility permission')
                windows = (('Google Chrome', left), ('TextEdit', right))
                usable = json.loads(subprocess.run(['osascript', '-l', 'JavaScript', '-e', 'ObjC.import("AppKit");var s=$.NSScreen.screens.js[0],v=s.visibleFrame;'
                                                    'JSON.stringify([v.origin.x,s.frame.size.height-v.origin.y-v.size.height,v.size.width,v.size.height])'], capture_output=True, text=True).stdout)
                x, y, w, h = map(int, usable)
                for fulls in ((True, True), (False, True)):   # both in their own full screen Spaces; or only the right one, the left a normal window across the screen
                    with self.subTest(full_screen=fulls):
                        trace.clear()
                        for (proc, name), full in zip(windows, fulls):   # each comes forward first: the one before it holds the display in its own Space
                            subprocess.run(['osascript', '-l', 'JavaScript', '-e', f'ObjC.import("AppKit");$.NSRunningApplication.runningApplicationWithProcessIdentifier({pids[proc]}).activateWithOptions(1)'], capture_output=True)
                            wait(proc, name, ('true', 'false'))
                            if full:
                                ax(proc, name, 'fs', 'true'); wait(proc, name, 'true')
                            else:
                                ax(proc, name, 'pos', str(x), str(y)); ax(proc, name, 'size', str(w), str(h)); wait(proc, name, 'false')
                        before = {p: state(p, n) or 'not visible (another Space)' for p, n in windows}
                        screen = atticus.screens()[0][0]
                        with patch.object(atticus, 'osa', side_effect=osa), patch.object(atticus, 'placement_window', side_effect=lambda proc, title: (title, None)), \
                             patch.object(atticus, 'preview_app'), patch.object(atticus, 'free_focus'), patch.dict(os.environ, {'ATTICUS_SCREEN': screen}):
                            started = t0 = time.monotonic()
                            reply = atticus.place_many(['Google Chrome', 'left', screen, left, '+', 'TextEdit', 'right', screen, right])
                            took = round(time.monotonic() - started, 1)
                        time.sleep(2)   # anything still animating has landed
                        after = {p: state(p, n) for p, n in windows}
                        print(f'PLACE HALVES {fulls}: ' + json.dumps({'before': before, 'after': after, 'reply': reply, 'secs': took}), flush=True)
                        if atticus.place_failed(reply): print('\n'.join(trace), flush=True)
                        frames, landed = [tuple(map(int, after[p].split(', ')[2:])) if after[p] else None for p, _ in windows], False
                        if None not in frames:   # a wrong frame must never carry a success receipt
                            (cl, ct, cw, ch), (tl, tt, tw, th) = frames
                            landed = cl + cw <= tl and all(abs(a - b) <= 4 for got, want in zip(frames, ((x, y, w // 2, h), (x + w // 2, y, w - w // 2, h))) for a, b in zip(got, want))
                            self.assertTrue(landed or atticus.place_failed(reply), f'success reported for {after}')
                        self.assertFalse(atticus.place_failed(reply), reply)
                        self.assertTrue(landed, f'the windows are not on their halves: {after}')
            finally:
                if chrome.poll() is None: os.killpg(chrome.pid, signal.SIGTERM)
                try: chrome.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(chrome.pid, signal.SIGKILL); chrome.wait()
                subprocess.run(['pkill', '-x', 'TextEdit'], capture_output=True)
                log.close()

    def test_pinned_background_window_javascript_and_ax(self):
        with tempfile.TemporaryDirectory(prefix='atticus-chrome-') as tmp:
            root = Path(tmp); profile = root / 'profile'; (profile / 'Default').mkdir(parents=True)
            prefs = {'browser':{'allow_javascript_apple_events':True}}
            (profile / 'Default/Preferences').write_text(json.dumps(prefs)); (profile / 'Local State').write_text(json.dumps(prefs))
            marker = 'ATTICUS SCRATCH ' + root.name
            page = root / 'page.html'
            page.write_text(f'<title>{marker}</title><button onclick="document.getElementById(\'result\').textContent=\'Clicked in background\'">Change text</button><input aria-label="Name"><p id="result">Untouched</p>')
            env = {**os.environ,'ATTICUS_DIR':tmp}
            log = open(root / 'chrome.log','w')
            process = subprocess.Popen([str(CHROME),f'--user-data-dir={profile}','--no-first-run','--no-default-browser-check','--disable-sync','--disable-background-networking',page.as_uri()],env=env,stdout=log,stderr=log,start_new_session=True)
            foreground = None
            def osa(script):
                result = subprocess.run(['osascript','-e',script],env=env,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                return result.stdout.strip()
            try:
                # Only request IDs for our unique fixture title, even if AppleScript chose another Chrome instance.
                self.require_automation('com.google.Chrome')
                selector = f'tell application "Google Chrome"\nset ws to every window whose name contains "{marker}"\nif (count ws) is 0 then return ""\nset w to item 1 of ws\nreturn (id of w as text) & (ASCII character 9) & (id of active tab of w as text)\nend tell'
                ids = ''
                for _ in range(40):
                    time.sleep(.3)
                    probe = subprocess.run(['osascript','-e',selector],env=env,capture_output=True,text=True,timeout=3)
                    ids = probe.stdout.strip() if not probe.returncode else ''
                    if ids: break
                self.assertTrue(ids, 'Scratch Chrome did not expose its uniquely titled fixture: ' + probe.stderr)
                window, tab = map(int,ids.split('\t'))
                tell = f'tell application "Google Chrome" to execute (first tab of window id {window} whose id is {tab}) javascript '
                webjs = Path(atticus.WEB_JS).read_text()
                read = osa(tell + json.dumps(f'({webjs})("read", "", "")'))
                self.assertIn(marker,read); self.assertIn('1 button: Change text',read)
                (root / 'web.json').write_text(json.dumps({'app':'Google Chrome','window':window,'tab':tab}))
                # Another scratch Chrome window becomes browser window 1; the mapped page must remain the action target.
                other = root / 'other.html'; other.write_text('<title>ATTICUS scratch cover</title><p>Second fixture window</p>')
                osa(f'tell application "Google Chrome"\nset w to make new window\nset URL of active tab of w to "{other.as_uri()}"\nend tell')
                time.sleep(.5)
                self.assertNotEqual(int(osa('tell application "Google Chrome" to get id of window 1')),window)
                # A separate native fixture, rather than a personal app, takes OS focus.
                source = root / 'cover.swift'
                source.write_text('''import Cocoa
let app=NSApplication.shared; app.setActivationPolicy(.regular)
let previous=NSWorkspace.shared.frontmostApplication
let w=NSWindow(contentRect:NSRect(x:40,y:40,width:800,height:600),styleMask:[.titled],backing:.buffered,defer:false)
w.title="Atticus scratch foreground"; w.orderFrontRegardless()
DispatchQueue.main.asyncAfter(deadline:.now()+0.2) { app.activate(ignoringOtherApps:true); w.makeKeyAndOrderFront(nil) }
DispatchQueue.main.asyncAfter(deadline:.now()+0.6) { print(ProcessInfo.processInfo.processIdentifier); fflush(stdout) }
NSWorkspace.shared.notificationCenter.addObserver(forName:NSWorkspace.didActivateApplicationNotification,object:nil,queue:.main) { n in
 if let a=n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication, a.processIdentifier != ProcessInfo.processInfo.processIdentifier { print("FOCUS LOST: \\(a.processIdentifier)"); fflush(stdout) }
}
signal(SIGTERM) { _ in DispatchQueue.main.async { previous?.activate(); exit(0) } }; app.run()
''')
                cover = root / 'ForegroundFixture.app/Contents/MacOS/cover'; cover.parent.mkdir(parents=True)
                with open(cover.parent.parent / 'Info.plist','wb') as f:
                    plistlib.dump({'CFBundleIdentifier':'com.atticus.foreground.fixture','CFBundleExecutable':'cover','CFBundleName':'Foreground Fixture','CFBundlePackageType':'APPL'},f)
                subprocess.run(['swiftc',str(source),'-o',str(cover)],env=env,check=True,capture_output=True)
                foreground = subprocess.Popen([str(cover)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                pid = int(foreground.stdout.readline()); time.sleep(.4)
                front = lambda: int(osa('tell application "System Events" to get unix id of first application process whose frontmost is true'))
                self.assertEqual(front(),pid)
                osa(tell + json.dumps('document.title'))
                before = front(); self.assertNotEqual(before,process.pid)
                with patch.object(atticus,'DIR',tmp), patch.dict(os.environ,{'ATTICUS_FRONT':'Google Chrome','ATTICUS_DIR':tmp},clear=False):
                    self.assertIn('Filled',atticus.web('fill','2','Background name'))
                    self.assertIn('Clicked 1',atticus.web('click','1'))
                self.assertEqual(front(),before,'JavaScript must leave the current foreground app focused')
                result = osa(tell + json.dumps('document.getElementById("result").textContent + "/" + document.querySelector("input").value'))
                self.assertEqual(result,'Clicked in background/Background name')
                print('CHROME BACKGROUND: JS fill/click changed the pinned non-front window; another app retained focus',flush=True)
                # System Events already has AX access; probe only the scratch PID/window, without changing permissions.
                osa(tell + json.dumps('document.getElementById("result").textContent="AX pending"'))
                script = f'''tell application "System Events" to tell (first application process whose unix id is {process.pid})
try
set value of attribute "AXManualAccessibility" to true
end try
set w to first window whose name contains "{marker}"
repeat with e in entire contents of w
try
if role of e is "AXButton" and (name of e is "Change text" or description of e is "Change text") then
perform action "AXPress" of e
return "AXPress"
end if
end try
end repeat
return "No background AX button"
end tell'''
                ax = subprocess.run(['osascript','-e',script],env=env,capture_output=True,text=True,timeout=10)
                if ax.returncode == 0 and ax.stdout.strip() == 'AXPress':
                    self.assertEqual(osa(tell + json.dumps('document.getElementById("result").textContent')),'Clicked in background')
                    print('CHROME AX: AXPress on the background page button worked without activating Chrome (System Events)',flush=True)
                else:
                    print('CHROME AX: not verified: ' + (ax.stderr.strip() or ax.stdout.strip()),flush=True)
                self.assertEqual(front(),before)
                # Exercise actual URL creation, navigation, parallel reads and --window continuations.
                handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=tmp)
                server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
                origin = f'http://127.0.0.1:{server.server_port}'
                browser_before = osa('tell application "Google Chrome" to return {id of window 1, id of active tab of window 1, count windows}')
                scratch = root / 'agent'; scratch.mkdir()
                (scratch / 'settings.json').write_text(json.dumps({'workIn':'back'}))
                # Keep production window-target/AX workers confined to a fake executable.
                worker = root / 'fake-app'
                worker.write_text('#!/bin/sh\nif [ "$1" = "--target-app" ]; then echo "Google Chrome"; fi\n')
                worker.chmod(0o700)
                agent_env = {**env, 'ATTICUS_DIR':str(scratch), 'ATTICUS_ASK':str(scratch), 'ATTICUS_AGENT':'fixture', 'ATTICUS_FRONT':'Google Chrome', 'ATTICUS_APP':str(worker)}
                # URL selects the explicitly named browser; the CLI normally resolves the default handler.
                code = 'import atticus; print(atticus.web("read", __import__("sys").argv[1], app="Google Chrome"))'
                readers = [subprocess.Popen([sys.executable, '-c', code, origin+'/page.html?read='+str(i)], env=agent_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(3)]
                for reader in readers:
                    output, error = reader.communicate(timeout=30)
                    self.assertEqual(reader.returncode,0,error); self.assertIn(marker,output,output)
                shown = subprocess.run([sys.executable, '-c', 'import atticus,sys;print(atticus.show(sys.argv[1]))', origin+'/page.html?show'],
                                       env=agent_env, capture_output=True, text=True, timeout=30)
                self.assertEqual(shown.returncode,0,shown.stderr); self.assertIn(marker,shown.stdout,shown.stdout)
                (scratch/'window-summary.json').write_text(json.dumps({'app':'Google Chrome','web':True}))
                window = subprocess.run([sys.executable, '-c', 'import atticus;print(atticus.window_text("Google Chrome"))'],
                                        env=agent_env, capture_output=True, text=True, timeout=30)
                self.assertEqual(window.returncode,0,window.stderr); self.assertIn(marker,window.stdout,window.stdout)
                self.assertEqual(osa('tell application "Google Chrome" to return {id of window 1, id of active tab of window 1, count windows}'), browser_before, 'Background reads selected a tab/window or created a window')
                self.assertEqual(front(),before)
                foreground.terminate(); focus_events, _ = foreground.communicate(timeout=5); foreground = None
                self.assertNotIn('FOCUS LOST',focus_events,'Even transient focus theft is a failure')
                # Background work must also leave the selected page alone when the browser itself is frontmost.
                osa('tell application "Google Chrome" to activate')
                browser_before = osa('tell application "Google Chrome" to return {id of window 1, id of active tab of window 1, count windows}')
                read = subprocess.run([sys.executable, '-c', code, origin+'/page.html?browser-front'], env=agent_env,
                                      capture_output=True, text=True, timeout=30)
                self.assertEqual(read.returncode,0,read.stderr); self.assertIn(marker,read.stdout,read.stdout)
                self.assertEqual(osa('tell application "Google Chrome" to return {id of window 1, id of active tab of window 1, count windows}'),browser_before)
                print('CHROME BACKGROUND: three actual URL reads retained foreground, selected tab and window order',flush=True)
            finally:
                if foreground:
                    foreground.terminate(); foreground.communicate(timeout=5)
                if process.poll() is None: os.killpg(process.pid,signal.SIGTERM)
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(process.pid,signal.SIGKILL); process.wait()
                log.close()

    def test_point_click_reaches_a_canvas_in_a_background_window(self):
        """--hands click "x,y" on a canvas in a Chrome window that is neither front nor Chrome's focused window: the page gets a
        trusted pointerdown at that spot, nothing comes forward, and the reply says the spot changed (or that nothing did)."""
        # No Apple events: in the guest they wait on an Automation prompt nobody can click. The pages report to a local
        # server, Chrome flags place the window, and the foreground fixture answers which app is front and Chrome's window order.
        root_dir = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='atticus-canvas-') as tmp:
            root = Path(tmp); profile = root / 'profile'; profile.mkdir()
            say = 'const say=(p,d)=>fetch(p,{method:"POST",body:JSON.stringify(d),keepalive:true});'
            (root / 'canvas.html').write_text(f'''<title>ATTICUS CANVAS {root.name}</title><body style="margin:0"><canvas id=c aria-label="Board" role=img width=440 height=300 style="display:block;background:#fff"></canvas>
<img alt="Blank" width=440 height=120 style="display:block" src="data:image/gif;base64,R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw=="><script>{say}const c=document.getElementById('c'),g=c.getContext('2d');
for(const t of ['pointerdown','mousedown','click'])c.addEventListener(t,e=>{{say('/hit',[e.type,e.offsetX,e.offsetY,e.isTrusted]);if(t=='pointerdown'){{g.fillStyle='#000';g.fillRect(e.offsetX-20,e.offsetY-15,40,30)}}}});
for(const t of ['pointermove','mousemove','pointerdown','mouseup'])addEventListener(t,e=>say('/ev',[e.type,e.clientX,e.clientY,e.isTrusted,document.hasFocus(),document.visibilityState]),true);
const info=()=>say('/info',{{w:'canvas',x:screenX,y:screenY,bar:outerHeight-innerHeight,focus:document.hasFocus(),vis:document.visibilityState}});info();setInterval(info,300);
window.open('/other.html','other','left=10,top=60,width=490,height=460');</script>''')
            # --window-position places every new window, so the popup moves itself beside the canvas window, not over it
            (root / 'other.html').write_text(f'<title>ATTICUS canvas other</title><p>Other window</p><script>{say}moveTo(10,60);resizeTo(490,460);setInterval(()=>say("/info",{{w:"other",x:screenX}}),300)</script>')
            seen, hits, events = {}, [], []
            class Pages(http.server.SimpleHTTPRequestHandler):
                def log_message(self, *a): pass
                def do_POST(self):
                    data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    if self.path == '/hit': hits.append(data)
                    elif self.path == '/ev': events.append(data)
                    else: seen[data['w']] = data
                    self.send_response(204); self.end_headers()
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Pages, directory=tmp))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
            binary = root / 'Atticus'
            compiled = subprocess.run(['swiftc', str(root_dir / 'Atticus.swift'), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            env = {**os.environ, 'ATTICUS_DIR':tmp, 'ATTICUS_RESOURCES_DIR':str(root_dir), 'ATTICUS_HANDS_STATE':str(root / 'hands.json')}
            env.pop('ATTICUS_AX_ONLY', None); env.pop('ATTICUS_HANDS_WINDOW', None)
            def hands(*args):
                label = subprocess.run([str(binary), '--hands', 'label', *args], env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(label.returncode, 0, label.stdout + label.stderr)
                r = subprocess.run([str(binary), '--hands', *args], input=label.stdout, env={**env, 'ATTICUS_HANDS_RECEIPT':'1'}, capture_output=True, text=True, timeout=15)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr); return r.stdout
            if 'Allow Atticus' in subprocess.run([str(binary), '--hands', 'see', '2147483647'], env=env, capture_output=True, text=True).stdout:
                self.skipTest('Temporary binary lacks Accessibility permission; no permission changes made')
            source = root / 'cover.swift'
            source.write_text('''import Cocoa
let app=NSApplication.shared; app.setActivationPolicy(.regular)
let w=NSWindow(contentRect:NSRect(x:20,y:20,width:300,height:100),styleMask:[.titled],backing:.buffered,defer:false)
w.title="Atticus scratch foreground"; w.orderFrontRegardless()
DispatchQueue.main.asyncAfter(deadline:.now()+0.2) { app.activate(ignoringOtherApps:true); w.makeKeyAndOrderFront(nil) }
DispatchQueue.main.asyncAfter(deadline:.now()+0.6) { print(ProcessInfo.processInfo.processIdentifier); fflush(stdout) }
NSWorkspace.shared.notificationCenter.addObserver(forName:NSWorkspace.didActivateApplicationNotification,object:nil,queue:.main) { n in
 if let a=n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication, a.processIdentifier != ProcessInfo.processInfo.processIdentifier { print("FOCUS LOST: \\(a.processIdentifier)"); fflush(stdout) }
}
DispatchQueue.global().async { while let line=readLine() { DispatchQueue.main.async {   // "front", or "order <pid>": that app's windows front to back as number@x
 if line=="front" { print("FRONT \\(NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0)") }
 else if line=="key" { print("KEY \\(w.isKeyWindow) \\(app.isActive)") }
 else { let pid=Int(line.dropFirst(6)) ?? 0, list=CGWindowListCopyWindowInfo([.optionOnScreenOnly,.excludeDesktopElements],kCGNullWindowID) as? [[String:Any]] ?? []
  let me=Int(ProcessInfo.processInfo.processIdentifier)   // this fixture's window shows as "self", so the order covers the user's window too
  print("ORDER "+list.filter{[pid,me].contains($0[kCGWindowOwnerPID as String] as? Int ?? -1) && ($0[kCGWindowLayer as String] as? Int)==0}.map{($0[kCGWindowOwnerPID as String] as? Int)==me ? "self" : "\\($0[kCGWindowNumber as String] as? Int ?? 0)@\\(((($0[kCGWindowBounds as String] as? [String:Any])?["X"]) as? NSNumber)?.intValue ?? 0)"}.joined(separator:" ")) }
 fflush(stdout) } } }
signal(SIGTERM) { _ in exit(0) }; app.run()
''')
            cover = root / 'ForegroundFixture.app/Contents/MacOS/cover'; cover.parent.mkdir(parents=True)
            with open(cover.parent.parent / 'Info.plist', 'wb') as f:
                plistlib.dump({'CFBundleIdentifier':'com.atticus.canvas.foreground', 'CFBundleExecutable':'cover', 'CFBundleName':'Canvas Foreground', 'CFBundlePackageType':'APPL'}, f)
            subprocess.run(['swiftc', str(source), '-o', str(cover)], env=env, check=True, capture_output=True)
            log = open(root / 'chrome.log', 'w')
            origin = f'http://127.0.0.1:{server.server_port}'
            process = subprocess.Popen([str(CHROME), f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check', '--disable-sync',
                                        '--disable-background-networking', '--use-mock-keychain', '--disable-popup-blocking',
                                        '--window-position=520,60', '--window-size=480,460', origin + '/canvas.html'],
                                       env=env, stdout=log, stderr=log, start_new_session=True)
            foreground, lost = None, []
            try:
                deadline = time.time() + 90   # a cold first start of a fresh profile in the guest
                while not ({'canvas', 'other'} <= seen.keys() and seen['other']['x'] + 490 <= seen['canvas']['x']):
                    if process.poll() is not None or time.time() > deadline:
                        self.fail(f'Scratch Chrome did not show both fixture windows side by side: {seen} ' + (root / 'chrome.log').read_text()[-3000:])
                    time.sleep(.3)
                time.sleep(1)
                foreground = subprocess.Popen([str(cover)], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                pid = int(foreground.stdout.readline())
                def ask(line, prefix):
                    foreground.stdin.write(line + '\n'); foreground.stdin.flush()
                    while (out := foreground.stdout.readline()):
                        if out.startswith(prefix + ' '): return out[len(prefix) + 1:].strip()
                        lost.append(out)
                    self.fail('The foreground fixture quit')
                front = lambda: int(ask('front', 'FRONT'))
                order = lambda: ask(f'order {process.pid}', 'ORDER')
                deadline = time.time() + 5
                while front() != pid and time.time() < deadline: time.sleep(.2)
                self.assertEqual(front(), pid)
                lost.clear()   # Chrome's own start may still activate it once before the fixture is front
                windows = order().split(); chrome = [w for w in windows if w != 'self']
                self.assertGreaterEqual(len(chrome), 2, windows)
                self.assertLess(int(chrome[0].split('@')[1]), seen['canvas']['x'], windows)   # Chrome's focused window is the other one
                at = seen['canvas']
                spot = lambda x, y: f"{at['x'] + x},{at['y'] + at['bar'] + y}"
                # As in a main ask with no see: the map is the user's front app; the point is in Chrome's canvas window, not Chrome's focused one.
                mapped = subprocess.run([str(binary), '--hands', 'see', str(pid)], env=env, capture_output=True, text=True, timeout=15)   # see makes the map: label needs one
                self.assertIn('Window: Atticus scratch foreground', mapped.stdout, mapped.stdout + mapped.stderr)
                key = lambda: ask('key', 'KEY')
                self.assertEqual(key(), 'true true')
                out = hands('click', spot(120, 90))
                deadline = time.time() + 3
                while len(hits) < 3 and time.time() < deadline: time.sleep(.1)
                down = [h for h in hits if h[0] == 'pointerdown']
                self.assertEqual(len(down), 1, (out, hits, events, seen['canvas']))
                self.assertTrue(abs(down[0][1] - 120) <= 3 and abs(down[0][2] - 90) <= 3 and down[0][3], (out, hits))   # the spot, not the canvas center
                self.assertNotIn('Nothing changed', out)   # it landed: the reply names a change (pixels at the spot, or the AX lines Chrome redrew), never the false "Nothing changed… add front"
                self.assertEqual(front(), pid); self.assertEqual(order().split(), windows)
                self.assertEqual(key(), 'true true', "the user's window keeps the keyboard")
                print('CANVAS BACKGROUND CLICK: ' + json.dumps({'hits': hits, 'window events': events, 'page': seen['canvas'], 'order': windows, 'reply': out.splitlines()[0]}), flush=True)
                count = len(hits)
                out = hands('click', spot(120, 360))   # an inert image below the canvas: no change, and the reply says so
                time.sleep(.5)
                self.assertIn('Nothing changed', out); self.assertEqual(len(hits), count)
                refused = subprocess.run([str(binary), '--hands', 'label', 'click', '110,200'], env=env, capture_output=True, text=True, timeout=15)
                self.assertIn("the user's other", refused.stdout)   # Chrome's other window was open beside the task's: it stays the user's
                self.assertEqual(front(), pid)
                foreground.terminate(); rest, _ = foreground.communicate(timeout=5); foreground = None
                self.assertNotIn('FOCUS LOST', ''.join(lost) + rest, 'Even transient focus theft is a failure')
            finally:
                if foreground:
                    foreground.terminate(); foreground.communicate(timeout=5)
                if process.poll() is None: os.killpg(process.pid, signal.SIGTERM)
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL); process.wait()
                log.close()

    def test_point_click_confirms_a_landed_click_in_a_fullscreen_window(self):
        """Saarth's Oct 21 case: a canvas in a cross-origin iframe in a native-full-screen Chrome window, Chrome inactive while an
        accessory app (as Atticus is) is front. The click lands, and the reply must confirm the change, not say 'Nothing changed'
        (a full-screen window's own capture returns a stale frame; the real screen at the spot shows the change)."""
        root_dir = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='atticus-fs-') as tmp:
            root = Path(tmp); profile = root / 'profile'; profile.mkdir()
            seen, hits = {}, []
            class Pages(http.server.SimpleHTTPRequestHandler):
                def log_message(self, *a): pass
                def do_POST(self):
                    data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    if self.path == '/hit': hits.append(data)
                    else: seen[data['w']] = data
                    self.send_response(204); self.end_headers()
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Pages, directory=tmp))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
            port = server.server_port
            say = 'const say=(p,d)=>fetch(p,{method:"POST",body:JSON.stringify(d),keepalive:true});'
            # localhost vs 127.0.0.1 is a cross-origin iframe: the canvas is in a different-origin document, as Google Minesweeper is.
            (root / 'top.html').write_text(f'''<title>ATTICUS FS {root.name}</title><body style="margin:0;background:#888"><iframe src="http://localhost:{port}/game.html" width=440 height=420 style="border:0;display:block"></iframe><script>{say}
const info=()=>say('/info',{{w:'full',x:screenX,y:screenY,bar:outerHeight-innerHeight,ow:outerWidth,sw:screen.width,focus:document.hasFocus()}});info();setInterval(info,300);</script>''')
            # Keep AX focus stable: this fixture must exercise the pixel receipt, not first-click web-area focus.
            (root / 'game.html').write_text(f'''<body style="margin:0"><canvas id=c tabindex=0 width=440 height=300 style="display:block;background:#fff"></canvas><script>{say}const c=document.getElementById('c'),g=c.getContext('2d');c.focus();
for(const t of ['pointerdown','mousedown','click'])c.addEventListener(t,e=>{{say('/hit',[e.type,e.offsetX,e.offsetY,e.isTrusted]);if(t=='pointerdown'){{g.fillStyle='#000';g.fillRect(e.offsetX-20,e.offsetY-15,40,30)}}}});</script>''')
            binary = root / 'Atticus'
            compiled = subprocess.run(['swiftc', str(root_dir / 'Atticus.swift'), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            env = {**os.environ, 'ATTICUS_DIR': tmp, 'ATTICUS_RESOURCES_DIR': str(root_dir), 'ATTICUS_HANDS_STATE': str(root / 'hands.json')}
            env.pop('ATTICUS_AX_ONLY', None); env.pop('ATTICUS_HANDS_WINDOW', None)
            if 'Allow Atticus' in subprocess.run([str(binary), '--hands', 'see', '2147483647'], env=env, capture_output=True, text=True).stdout:
                self.skipTest('Temporary binary lacks Accessibility permission; no permission changes made')
            def hands(*args):
                label = subprocess.run([str(binary), '--hands', 'label', *args], env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(label.returncode, 0, label.stdout + label.stderr)
                r = subprocess.run([str(binary), '--hands', *args], input=label.stdout, env={**env, 'ATTICUS_HANDS_RECEIPT': '1'}, capture_output=True, text=True, timeout=20)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr); return r.stdout
            source = root / 'cover.swift'   # an accessory app, as Atticus is: it floats over Chrome's full-screen Space without switching away from it
            source.write_text('''import Cocoa
let app=NSApplication.shared; app.setActivationPolicy(.accessory)
let w=NSWindow(contentRect:NSRect(x:0,y:0,width:300,height:120),styleMask:[.titled],backing:.buffered,defer:false)
w.collectionBehavior=[.canJoinAllSpaces,.fullScreenAuxiliary]
w.title="Atticus scratch foreground"; w.setFrameTopLeftPoint(NSPoint(x:700,y:(NSScreen.screens.first?.frame.height ?? 800)-200)); w.orderFrontRegardless()
DispatchQueue.main.asyncAfter(deadline:.now()+0.2) { app.activate(ignoringOtherApps:true); w.makeKeyAndOrderFront(nil) }
DispatchQueue.main.asyncAfter(deadline:.now()+0.6) { print(ProcessInfo.processInfo.processIdentifier); fflush(stdout) }
NSWorkspace.shared.notificationCenter.addObserver(forName:NSWorkspace.didActivateApplicationNotification,object:nil,queue:.main) { n in
 if let a=n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication, a.processIdentifier != ProcessInfo.processInfo.processIdentifier { print("FOCUS LOST: \\(a.processIdentifier)"); fflush(stdout) }
}
DispatchQueue.global().async { while let line=readLine() { DispatchQueue.main.async {
 if line=="front" { print("FRONT \\(NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0)") }
 else if line=="key" { print("KEY \\(w.isKeyWindow) \\(app.isActive)") }
 fflush(stdout) } } }
signal(SIGTERM) { _ in exit(0) }; app.run()
''')
            cover = root / 'ForegroundFixture.app/Contents/MacOS/cover'; cover.parent.mkdir(parents=True)
            with open(cover.parent.parent / 'Info.plist', 'wb') as f:
                plistlib.dump({'CFBundleIdentifier': 'com.atticus.fs.foreground', 'CFBundleExecutable': 'cover', 'CFBundleName': 'FS Foreground', 'CFBundlePackageType': 'APPL'}, f)
            subprocess.run(['swiftc', str(source), '-o', str(cover)], env=env, check=True, capture_output=True)
            log = open(root / 'chrome.log', 'w')
            origin = f'http://127.0.0.1:{port}'
            process = subprocess.Popen([str(CHROME), f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check', '--disable-sync',
                                        '--disable-background-networking', '--use-mock-keychain', '--disable-popup-blocking', '--start-fullscreen', origin + '/top.html'],
                                       env=env, stdout=log, stderr=log, start_new_session=True)
            foreground, lost = None, []
            try:
                deadline = time.time() + 90
                while not ('full' in seen and seen['full']['ow'] >= seen['full']['sw'] - 2) and time.time() < deadline:
                    if process.poll() is not None or time.time() > deadline:
                        self.fail('Scratch Chrome did not reach full screen: ' + json.dumps(seen) + (root / 'chrome.log').read_text()[-2000:])
                    time.sleep(.3)
                time.sleep(2)
                foreground = subprocess.Popen([str(cover)], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                pid = int(foreground.stdout.readline())
                def ask(line, prefix):
                    foreground.stdin.write(line + '\n'); foreground.stdin.flush()
                    while (out := foreground.stdout.readline()):
                        if out.startswith(prefix + ' '): return out[len(prefix) + 1:].strip()
                        lost.append(out)
                    self.fail('The foreground fixture quit')
                front = lambda: int(ask('front', 'FRONT'))
                deadline = time.time() + 5
                while front() != pid and time.time() < deadline: time.sleep(.2)
                self.assertEqual(front(), pid); lost.clear()
                at = seen['full']
                self.assertGreaterEqual(at['ow'], at['sw'] - 2, 'Chrome is not full screen')
                mapped = subprocess.run([str(binary), '--hands', 'see', str(pid)], env=env, capture_output=True, text=True, timeout=15)
                self.assertIn('Window: Atticus scratch foreground', mapped.stdout, mapped.stdout + mapped.stderr)
                before = len(hits)
                out = hands('click', f"{at['x'] + 120},{at['y'] + at['bar'] + 90}")
                deadline = time.time() + 3
                while len(hits) < before + 3 and time.time() < deadline: time.sleep(.1)
                down = [h for h in hits[before:] if h[0] == 'pointerdown']
                self.assertEqual(len(down), 1, (out, hits[before:]))   # the click reached the cross-origin iframe canvas in the full-screen window
                self.assertTrue(abs(down[0][1] - 120) <= 3 and abs(down[0][2] - 90) <= 3 and down[0][3], (out, hits[before:]))
                self.assertNotIn('Nothing changed', out)   # the fix: a landed click on a full-screen window is confirmed from the real screen, not falsely denied
                self.assertIn('changed at that spot', out, out)
                self.assertEqual(front(), pid); self.assertEqual(ask('key', 'KEY'), 'true true', "the user's window keeps the keyboard")
                print('CANVAS FULLSCREEN CLICK: ' + json.dumps({'hits': hits[before:], 'page': at, 'reply': out.splitlines()[0]}), flush=True)
                foreground.terminate(); rest, _ = foreground.communicate(timeout=5); foreground = None
                self.assertNotIn('FOCUS LOST', ''.join(lost) + rest, 'Even transient focus theft is a failure')
            finally:
                if foreground:
                    foreground.terminate(); foreground.communicate(timeout=5)
                if process.poll() is None: os.killpg(process.pid, signal.SIGTERM)
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL); process.wait()
                log.close()

if __name__ == '__main__': unittest.main()
