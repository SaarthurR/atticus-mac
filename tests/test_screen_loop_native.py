"""VM only: on-screen look-act work at the harness's real speed, in a scratch Chrome with a local grid game and form (no network).
The game is only a measuring stick: pictures must put every spot where a click lands, one look must drive several clicks, and a
window that moves or resizes after its picture must never take a click meant for another spot."""
import functools
import http.server
import json
import os
import plistlib
import signal
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
N, S, X0, Y0 = 9, 36, 20, 60                     # grid cells, cell size, canvas origin in the page
MARK = (370, 240, 24)                            # a magenta square on cyan, page x, y, side
MINES = [(0, 7), (1, 2), (2, 8), (3, 0), (5, 8), (6, 1), (7, 5), (8, 0), (8, 8), (2, 4)]
SAY = 'const say=(p,d)=>fetch(p,{method:"POST",body:JSON.stringify(d),keepalive:true});'
GAME = '''<title>ATTICUS GRID %(tag)s</title><body style="margin:0;background:#00c8ff">
<div style="position:absolute;left:%(mx)dpx;top:%(my)dpx;width:%(ms)dpx;height:%(ms)dpx;background:#ff00ff"></div>
<canvas id=c width=%(w)d height=%(w)d style="position:absolute;left:%(x0)dpx;top:%(y0)dpx"></canvas><script>%(say)s
const N=%(n)d,S=%(s)d,mines=new Set(%(mines)s.map(([r,c])=>r*N+c)),open=new Set(),c=document.getElementById('c'),g=c.getContext('2d');
const near=(r,k)=>{let n=0;for(let i=-1;i<2;i++)for(let j=-1;j<2;j++)if(mines.has((r+i)*N+k+j)&&r+i>=0&&r+i<N&&k+j>=0&&k+j<N)n++;return n};
function reveal(r,k){if(r<0||k<0||r>=N||k>=N||open.has(r*N+k))return;open.add(r*N+k);if(!near(r,k))for(let i=-1;i<2;i++)for(let j=-1;j<2;j++)reveal(r+i,k+j)}
function draw(){g.font='20px sans-serif';g.textAlign='center';for(let r=0;r<N;r++)for(let k=0;k<N;k++){const o=open.has(r*N+k);
 g.fillStyle=o?'#dddddd':'#2a7d2a';g.fillRect(k*S+1,r*S+1,S-2,S-2);if(o&&near(r,k)){g.fillStyle='#000';g.fillText(near(r,k),k*S+S/2,r*S+S/2+7)}}}
const state=()=>say('/state',{open:[...open]});
c.addEventListener('pointerdown',e=>{const r=Math.floor(e.offsetY/S),k=Math.floor(e.offsetX/S),i=r*N+k;
 const kind=open.has(i)?'noop':mines.has(i)?'mine':'reveal';if(kind=='reveal')reveal(r,k);draw();say('/hit',{r,k,kind,t:Date.now()/1000,trusted:e.isTrusted});state()});
draw();state();
const info=()=>say('/info',{w:'game',x:screenX,y:screenY,bar:outerHeight-innerHeight,ow:outerWidth,oh:outerHeight});info();setInterval(info,250);
setInterval(async()=>{const t=await (await fetch('/cmd')).text();if(!t)return;const[a,b,d]=t.split(' ');if(a=='move')moveBy(+b,+d);if(a=='resize')resizeBy(+b,+d);if(a=='reset'){open.clear();draw();state()}},150);
</script>'''
FORM = '''<title>ATTICUS FORM %(tag)s</title><body style="margin:20px;font:16px sans-serif">%(fields)s<script>%(say)s
for(const i of document.querySelectorAll('input'))i.addEventListener('input',()=>say('/form',{[i.id]:i.value}));
const info=()=>say('/info',{w:'form',x:screenX});info();setInterval(info,300);</script>'''
FIELDS = ['First name', 'Last name', 'Email', 'City', 'Team']


def bmp_pixel(jpg, x, y):
    """(r, g, b) at picture pixel x, y, through sips (no PIL in the guest)."""
    out = Path(str(jpg) + '.bmp')
    subprocess.run(['sips', '-s', 'format', 'bmp', str(jpg), '--out', str(out)], check=True, capture_output=True)
    data = out.read_bytes()
    offset, = struct.unpack_from('<I', data, 10); width, height = struct.unpack_from('<ii', data, 18); bpp, = struct.unpack_from('<H', data, 28)
    row = (width * bpp // 8 + 3) & ~3
    top_down = height < 0
    line = int(y) if top_down else abs(height) - 1 - int(y)
    b, g, r = data[offset + line * row + int(x) * (bpp // 8):][:3]
    return r, g, b


@unittest.skipUnless(os.environ.get('ATTICUS_VM') == '1' and sys.platform == 'darwin' and CHROME.exists(),
                     'Scratch Chrome game fixture requires ATTICUS_VM=1 and macOS Chrome')
class ScreenLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='atticus-loop-'); cls.root = root = Path(cls.tmp.name)
        cls.binary = root / 'Atticus'
        compiled = subprocess.run(['swiftc', str(ROOT / 'Atticus.swift'), '-o', str(cls.binary)], capture_output=True, text=True)
        if compiled.returncode: raise AssertionError(compiled.stderr)
        tag = root.name
        cls.tag = tag
        (root / 'game.html').write_text(GAME % dict(tag=tag, mx=MARK[0], my=MARK[1], ms=MARK[2], w=N * S, x0=X0, y0=Y0, n=N, s=S, mines=json.dumps(MINES), say=SAY))
        (root / 'form.html').write_text(FORM % dict(tag=tag, say=SAY, fields=''.join(
            f'<p><label for=f{i}>{name}</label> <input id=f{i} aria-label="{name}"></p>' for i, name in enumerate(FIELDS))))
        (root / 'index.html').write_text('<title>launcher</title><script>window.open("/game.html","game","left=40,top=80,width=440,height=520");'
                                         'window.open("/form.html","form","left=520,top=80,width=420,height=420")</script>')
        cls.seen, cls.hits, cls.form, cls.cmds, cls.open = {}, [], {}, [], []
        test = cls
        class Pages(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                if self.path != '/cmd': return super().do_GET()
                body = (test.cmds.pop(0) if test.cmds else '').encode()
                self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path == '/hit': test.hits.append(data)
                elif self.path == '/state': test.open = data['open']
                elif self.path == '/form': test.form.update(data)
                else: test.seen[data['w']] = data
                self.send_response(204); self.end_headers()
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Pages, directory=str(root)))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.dir = root / 'config'; cls.dir.mkdir(); (cls.dir / 'settings.json').write_text(json.dumps({'safe': False}))
        cls.ask = root / 'ask'; cls.ask.mkdir()
        cls.env = {k: v for k, v in os.environ.items() if not k.startswith('ATTICUS_') or k == 'ATTICUS_VM'}
        cls.env.update(ATTICUS_DIR=str(cls.dir), ATTICUS_APP=str(cls.binary), ATTICUS_RESOURCES_DIR=str(ROOT), ATTICUS_ASK=str(cls.ask),
                       ATTICUS_REQUEST='play the grid game in that window for me', ATTICUS_POSTHOG_KEY='')
        if 'Allow Atticus' in subprocess.run([str(cls.binary), '--hands', 'see', '2147483647'], env=cls.env, capture_output=True, text=True).stdout:
            raise unittest.SkipTest('Temporary binary lacks Accessibility permission; no permission changes made')
        (root / 'window.swift').write_text('''import Cocoa
// window <pid> <title words> full|raise: native full screen (its own Space, as the green button does), or that window front
let pid = pid_t(CommandLine.arguments[1])!, want = CommandLine.arguments[2], app = AXUIElementCreateApplication(pid)
for _ in 0..<100 {
    var value: CFTypeRef?; AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString, &value)
    for w in value as? [AXUIElement] ?? [] {
        var title: CFTypeRef?; AXUIElementCopyAttributeValue(w, kAXTitleAttribute as CFString, &title)
        guard (title as? String ?? "").contains(want) else { continue }
        print(CommandLine.arguments[3] == "full" ? AXUIElementSetAttributeValue(w, "AXFullScreen" as CFString, kCFBooleanTrue).rawValue
              : AXUIElementPerformAction(w, kAXRaiseAction as CFString).rawValue); exit(0)
    }
    usleep(100_000)
}
print("no window"); exit(1)
''')
        subprocess.run(['swiftc', str(root / 'window.swift'), '-o', str(root / 'window')], check=True, capture_output=True)
        # --window-target names an app only when one process has that name; the guest may reopen a Chrome at login.
        subprocess.run(['osascript', '-l', 'JavaScript', '-e', 'ObjC.import("AppKit");for(const a of $.NSWorkspace.sharedWorkspace.runningApplications.js)'
                        'if(a.bundleIdentifier.js=="com.google.Chrome"){a.terminate;delay(3);a.forceTerminate}'], capture_output=True, timeout=30)
        cls.chrome = cls.start_chrome('main', f'http://127.0.0.1:{cls.server.server_port}/index.html')
        deadline = time.time() + 90
        while not {'game', 'form'} <= cls.seen.keys():
            if time.time() > deadline: raise AssertionError('Scratch Chrome did not open the fixture windows: ' + json.dumps(cls.seen))
            time.sleep(.3)
        time.sleep(1.5)
    @classmethod
    def start_chrome(cls, name, url, *extra):
        profile = cls.root / f'profile-{name}'; profile.mkdir()
        log = open(cls.root / f'chrome-{name}.log', 'w')
        return subprocess.Popen([str(CHROME), f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check', '--disable-sync',
                                 '--disable-background-networking', '--use-mock-keychain', '--disable-popup-blocking', '--force-renderer-accessibility',
                                 *extra, url], env=cls.env, stdout=log, stderr=log, start_new_session=True)

    @classmethod
    def tearDownClass(cls):
        for p in (getattr(cls, 'chrome', None),):
            if p and p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
                try: p.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(p.pid, signal.SIGKILL)
        cls.server.shutdown(); cls.server.server_close(); cls.tmp.cleanup()

    # -- helpers -----------------------------------------------------------------------------------------------------------
    def helper(self, *args, agent=False):
        env = {**self.env, 'PYTHONFAULTHANDLER': '1', **({'ATTICUS_AGENT': 'f' * 32, 'ATTICUS_HANDS_STATE': str(self.ask / 'hands.json')} if agent else {})}
        began = time.monotonic()
        p = subprocess.Popen([sys.executable, str(ROOT / 'atticus.py'), *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try: out, err = p.communicate(timeout=45)
        except subprocess.TimeoutExpired:
            p.send_signal(signal.SIGABRT); out, err = p.communicate()   # faulthandler prints where every thread waits
            self.fail(f'{args} hung:\n{out}\n{err[-4000:]}')
        return out + err, time.monotonic() - began

    def display(self):
        out = subprocess.run(['osascript', '-l', 'JavaScript', '-e', 'ObjC.import("AppKit");var s=$.NSScreen.screens.js[0].frame;JSON.stringify([s.size.width,s.size.height])'],
                             capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def picture(self, page_x, page_y, at=None):
        """A page point of the game window as a screen-1 picture spot, from where the page says its window is."""
        at = at or self.seen['game']; width, _ = self.display()
        return round((at['x'] + page_x) * 1280 / width), round((at['y'] + at['bar'] + page_y) * 1280 / width)

    def cell(self, r, k, at=None):
        x, y = self.picture(X0 + k * S + S / 2, Y0 + r * S + S / 2, at)
        return f'1:{x},{y}'

    def watch(self, title):
        """The window the user is looking at: Chrome in front, that window on top (a main ask's look-act loop)."""
        subprocess.run(['open', '-a', str(CHROME.parents[2])], check=True, timeout=30)
        raised = subprocess.run([str(self.root / 'window'), str(self.chrome.pid), f'{title} {self.tag}', 'raise'], capture_output=True, text=True, timeout=30)
        self.assertEqual(raised.stdout.strip(), '0', raised.stdout + raised.stderr); time.sleep(1)

    def front(self, agent=False):
        out, secs = self.helper('--front', 'Google Chrome', f'ATTICUS GRID {self.tag}', agent=agent)
        path = next((line.rsplit(': ', 1)[1].strip() for line in out.splitlines() if line.startswith('Screen ') and line.strip().endswith('.jpg')), None)
        self.assertTrue(path and Path(path).exists(), out)
        return path, out, secs

    def frontier(self):
        """Every safe unopened cell next to an opened one: what one picture of the board settles (the model's part, scripted)."""
        opened, mines = set(self.open), {r * N + k for r, k in MINES}
        return [(i // N, i % N) for i in range(N * N) if i not in opened and i not in mines and
                any((i // N + a) * N + i % N + b in opened for a in (-1, 0, 1) for b in (-1, 0, 1)
                    if 0 <= i // N + a < N and 0 <= i % N + b < N)]

    def settle_window(self, before):
        deadline = time.time() + 5
        while self.seen['game'] == before and time.time() < deadline: time.sleep(.1)
        time.sleep(.6)

    # -- correctness -------------------------------------------------------------------------------------------------------
    def test_a_picture_puts_a_covered_window_where_clicks_land(self):
        source = self.root / 'cover.swift'   # the user's own window, over the game's mark
        at = self.seen['game']; x, y = at['x'] + MARK[0] - 60, at['y'] + at['bar'] + MARK[1] - 60
        source.write_text(f'''import Cocoa
let app=NSApplication.shared; app.setActivationPolicy(.regular)
let h=NSScreen.screens[0].frame.height
let w=NSWindow(contentRect:NSRect(x:{x},y:h-{y}-160,width:160,height:160),styleMask:[.titled],backing:.buffered,defer:false)
w.title="Atticus scratch cover"; w.backgroundColor = .yellow; w.orderFrontRegardless()
DispatchQueue.main.asyncAfter(deadline:.now()+0.2) {{ app.activate(ignoringOtherApps:true); w.makeKeyAndOrderFront(nil); print("up"); fflush(stdout) }}
signal(SIGTERM) {{ _ in exit(0) }}; app.run()
''')
        cover = self.root / 'Cover.app/Contents/MacOS/cover'; cover.parent.mkdir(parents=True)
        with open(cover.parent.parent / 'Info.plist', 'wb') as f:
            plistlib.dump({'CFBundleIdentifier': 'com.atticus.loop.cover', 'CFBundleExecutable': 'cover', 'CFBundleName': 'Loop Cover', 'CFBundlePackageType': 'APPL'}, f)
        subprocess.run(['swiftc', str(source), '-o', str(cover)], check=True, capture_output=True)
        p = subprocess.Popen([str(cover)], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(), 'up'); time.sleep(1)
            path, out, _ = self.front()
            mx, my = self.picture(MARK[0] + MARK[2] / 2, MARK[1] + MARK[2] / 2)
            r, g, b = bmp_pixel(path, mx, my)
            print(f'COVERED MARK {(mx, my)} = {(r, g, b)}', flush=True)
            self.assertTrue(r > 200 and g < 80 and b > 200, f'the covered window\'s mark is not where it sits: {(r, g, b)} at {(mx, my)}\n{out}')
        finally:
            p.terminate(); p.wait(timeout=5)

    def test_b_several_spots_from_one_look_land_in_order(self):
        self.watch('ATTICUS GRID')
        self.helper('--front', 'Google Chrome', f'ATTICUS GRID {self.tag}')
        first, _ = self.helper('--hands', 'click', self.cell(4, 4))   # the first click opens the middle
        deadline = time.time() + 3
        while not self.hits and time.time() < deadline: time.sleep(.1)
        safe = self.frontier()[:4]
        self.assertEqual(len(safe), 4, (first, self.open))
        count = len(self.hits)
        out, secs = self.helper('--hands', 'click', *[self.cell(r, k) for r, k in safe])
        deadline = time.time() + 3
        while len(self.hits) < count + 4 and time.time() < deadline: time.sleep(.1)
        landed = [(h['r'], h['k']) for h in self.hits[count:]]
        print(f'SEVERAL SPOTS {secs:.2f}s: {out.splitlines()[:1]} landed {landed}', flush=True)
        self.assertEqual(landed, safe, out)
        self.assertIn('Clicked 4 spots', out)

    def test_c_spots_follow_a_moved_window_and_a_resize_takes_no_click(self):
        self.watch('ATTICUS GRID')
        if not self.open: self.helper('--hands', 'click', self.cell(4, 4)); time.sleep(1)
        path, out, _ = self.front()
        target = next((r, k) for r, k in self.frontier())
        spot = self.cell(*target)
        before = dict(self.seen['game']); self.cmds.append('move 60 40'); self.settle_window(before)
        count = len(self.hits)
        moved, _ = self.helper('--hands', 'click', spot)
        deadline = time.time() + 3
        while len(self.hits) == count and time.time() < deadline: time.sleep(.1)
        landed = [(h['r'], h['k']) for h in self.hits[count:]]
        print(f'MOVED WINDOW: aimed {target}, landed {landed}: {moved.splitlines()[:1]}', flush=True)
        self.assertEqual(landed, [target], moved)
        self.front()
        target = next((r, k) for r, k in self.frontier())
        spot = self.cell(*target)
        before = dict(self.seen['game']); self.cmds.append('resize 80 60'); self.settle_window(before)
        count = len(self.hits)
        resized, _ = self.helper('--hands', 'click', spot)
        time.sleep(1)
        print(f'RESIZED WINDOW: aimed {target}, landed {[(h["r"], h["k"]) for h in self.hits[count:]]}: {resized.splitlines()[:1]}', flush=True)
        self.assertEqual(self.hits[count:], [], resized)
        self.assertIn('changed size after that picture', resized)

    # -- speed -------------------------------------------------------------------------------------------------------------
    def test_d_speed_of_a_look_act_loop_and_a_form(self):
        """Prints what the report's before/after table uses; asserts only that the fixture played."""
        several = 'static func spots(' in (ROOT / 'Atticus.swift').read_text()   # this build takes several spots per call
        self.cmds.append('resize -80 -60'); time.sleep(1)
        self.watch('ATTICUS GRID')
        fronts = {mode: [self.front(agent=mode == 'agent')[2] for _ in range(3)] for mode in ('main', 'agent')}
        singles = []
        for _ in range(3):
            target = next(iter(self.frontier()), (4, 4))
            self.front(); singles.append(self.helper('--hands', 'click', self.cell(*target))[1])
        self.cmds.append('reset'); deadline = time.time() + 3   # the same game from the same empty board, before and after
        while self.open and time.time() < deadline: time.sleep(.1)
        start, wall, clicks, calls, rounds, seen = time.monotonic(), time.time(), 0, 0, 0, len(self.hits)
        while time.monotonic() - start < 60 and (safe := self.frontier() if self.open else [(4, 4)]):
            self.front(); rounds += 1; calls += 1
            spots = [self.cell(r, k) for r, k in safe]
            for chunk in ([spots] if several else [[s] for s in spots]):
                self.helper('--hands', 'click', *chunk); calls += 1; clicks += len(chunk)
            deadline = time.time() + 2
            while len(self.hits) < seen + clicks and time.time() < deadline: time.sleep(.05)
        elapsed = time.monotonic() - start
        played = self.hits[seen:]
        first = played[0]['t'] - wall if played else None
        gate = []
        for _ in range(3):
            began = time.monotonic()
            subprocess.run([sys.executable, str(ROOT / 'atticus.py'), '--gate'], input=json.dumps({'tool_name': 'Bash', 'tool_input': {'command': f'{ROOT / "atticus.py"} --hands click 1:10,10'}}),
                           env=self.env, capture_output=True, text=True, timeout=30)
            gate.append(time.monotonic() - began)
        form, typed = [], 0
        self.watch('ATTICUS FORM')
        began = time.monotonic()
        _, secs = self.helper('--front', 'Google Chrome', f'ATTICUS FORM {self.tag}', agent=True); form.append(secs)
        for i, name in enumerate(FIELDS):
            out, secs = self.helper('--hands', 'type', name, f'value {i}', agent=True)
            form.append(secs)
            if i == 0: print('FORM FIRST FIELD: ' + out.splitlines()[0] if out else '', flush=True)
        form_total = time.monotonic() - began; time.sleep(1)
        typed = sum(f'value {i}' == self.form.get(f'f{i}') for i in range(len(FIELDS)))
        print('SCREEN LOOP BENCH ' + json.dumps({
            'several_spots_per_call': several, 'front_secs': {k: [round(s, 2) for s in v] for k, v in fronts.items()},
            'single_click_secs': [round(s, 2) for s in singles], 'first_click_secs': round(first, 2) if first is not None else None, 'loop_secs': round(elapsed, 1),
            'clicks': clicks, 'rounds': rounds, 'tool_calls': calls, 'clicks_per_min_harness': round(clicks * 60 / elapsed, 1),
            'wrong_squares': sum(h['kind'] != 'reveal' for h in played), 'won': not self.frontier(), 'gate_secs': [round(s, 2) for s in gate],
            'form_secs': [round(s, 2) for s in form], 'form_total_secs': round(form_total, 1), 'form_fields_landed': typed}), flush=True)
        self.assertGreater(len(played), 0)

    def test_e_a_full_screen_window_is_pictured_as_the_screen_shows_it(self):
        # Nov 17: a full-screen Chrome's own capture was a stale frame of another size, pasted over the real screen: every
        # picture spot sat about a row away from the square it showed, so clicks opened the wrong squares and then a mine.
        (self.root / 'full.html').write_text(f'''<title>ATTICUS FULL {self.tag}</title><body style="margin:0;background:#00c8ff">
<div style="position:absolute;left:{MARK[0]}px;top:{MARK[1]}px;width:{MARK[2]}px;height:{MARK[2]}px;background:#ff00ff"></div><script>{SAY}
const info=()=>say('/info',{{w:'full',x:screenX,y:screenY,bar:outerHeight-innerHeight,ow:outerWidth,sw:screen.width}});info();setInterval(info,250);</script>''')
        subprocess.Popen([str(CHROME), f'--user-data-dir={self.root / "profile-main"}', '--new-window', f'http://127.0.0.1:{self.server.server_port}/full.html'],
                         env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait(timeout=30)
        made = subprocess.run([str(self.root / 'window'), str(self.chrome.pid), f'ATTICUS FULL {self.tag}', 'full'], capture_output=True, text=True, timeout=30)
        self.assertEqual(made.stdout.strip(), '0', made.stdout + made.stderr)
        deadline = time.time() + 30
        while not ('full' in self.seen and self.seen['full']['ow'] >= self.seen['full']['sw'] - 2):
            if time.time() > deadline: self.fail('Scratch Chrome did not reach full screen: ' + json.dumps(self.seen))
            time.sleep(.3)
        time.sleep(2)
        out, _ = self.helper('--front', 'Google Chrome', f'ATTICUS FULL {self.tag}')
        path = next((line.rsplit(': ', 1)[1].strip() for line in out.splitlines() if line.startswith('Screen ') and line.strip().endswith('.jpg')), None)
        self.assertTrue(path and Path(path).exists(), out)
        mx, my = self.picture(MARK[0] + MARK[2] / 2, MARK[1] + MARK[2] / 2, self.seen['full'])
        r, g, b = bmp_pixel(path, mx, my)
        print(f'FULL SCREEN MARK {(mx, my)} = {(r, g, b)}', flush=True)
        self.assertTrue(r > 200 and g < 80 and b > 200, f'the full-screen window\'s mark is not where it shows: {(r, g, b)} at {(mx, my)}\n{out}')


if __name__ == '__main__':
    unittest.main()
