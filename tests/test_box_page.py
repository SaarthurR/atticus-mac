"""ui/ui.html in a real WKWebView that is never put in a window: a streamed answer, the Learned pill and an agent's done card."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_shelf_page import HARNESS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = r'''
const a = () => document.querySelector('#thread .turn:last-child .a'), out = {};
ui.listen(); ui.words('what is it'); ui.think();
ui.line('… See [1] and a[0]\u2028- [ ] a task and'); out.brackets = [...a().querySelectorAll('p, li')].map(e => e.textContent.trim());
ui.line('… '); ui.line('… It [the link](https://x.co'); out.open = a().textContent.trim();
ui.line('… It [the link](https://x.co) and'); out.link = [a().querySelector('a')?.textContent, a().textContent.trim()];
ui.line('✓ It [the link](https://x.co) and more.'); out.final = [a().textContent, a().classList.contains('streaming')];
ui.listen(); ui.words('area'); ui.think(); out.math = [];
for (const s of ['the area is $', 'the area is $\\pi r', 'the area is $\\pi r^2', 'the area is $\\pi r^2$ cm', 'the area is $\\pi r^2$ cm and costs $5 today']) { ui.line('… ' + s); out.math.push(a().textContent.trim()); }
out.math.push(!!a().querySelector('math'));
ui.agentDone({id: 'x', title: 'Compare phones', status: 'done', result: 'Found **three** phones [1].', summary: ''});
const card = document.querySelector('.agent-card');
out.card = [card.querySelector('b').textContent, card.querySelector('.a').textContent.trim(), [...card.querySelectorAll('.agent-actions button')].map(b => b.textContent)];
const later = card.querySelector('.agent-actions button:not(.go)'), settle = () => document.getAnimations().filter(a => a.effect.getTiming().iterations !== Infinity).forEach(a => a.finish());   // no window: WebKit never advances motion
later.scrollIntoView(); const r = later.getBoundingClientRect(), rest = getComputedStyle(later).backgroundColor;
out.hot = [ui.pointer([r.x + r.width / 2, r.y + r.height / 2], false), later.classList.contains('hot'), card.classList.contains('hot')]; settle(); out.hot.push(rest !== getComputedStyle(later).backgroundColor);
out.off = [ui.pointer([]), document.querySelectorAll('.hot').length];
out.x = [ui.pointer([1, 1], true), document.getElementById('x').classList.contains('hot'), later.classList.contains('hot')]; ui.pointer([]);
ui.agentDone({id:'setup', title:'Set up focus time', summary:'Ready.', learned:'focus time'});
out.agentLearned = [document.querySelector('.agent-card .tip.learned')?.dataset.k, document.querySelector('.agent-card .tip.learned')?.textContent];
ui.agentDone({id:'other', title:'Other task', summary:'Done.'}); out.noStaleLearned = !document.querySelector('.agent-card .tip.learned');
const ack = () => document.querySelector('#thread .turn:last-child .agent-ack span').textContent;
ui.listen(); ui.agentSteered({id: 'b1', title: 'Ebikes', steer: {text: 'under $1500'}}); ui.agentStarted({id: 'c1', title: 'Bike locks', status: 'running'});
out.steerAndNew = ack();
ui.listen(); ui.agentStarted({id: 'c1', title: 'Ebikes', status: 'running'}); ui.agentStarted({id: 'd1', title: 'Helmets', status: 'queued'}); out.two = ack();
ui.listen(); ui.agentStarted({id: 'e1', title: 'Tents', status: 'queued'}); ui.agentStarted({id: 'f1', title: 'Stoves', status: 'running'}); ui.agentStarted({id: 'g1', title: 'Maps', status: 'running'}); out.mix = ack();
ui.reset(); out.turns = [];
const thread = document.getElementById('thread');
const inView = e => { const r=e.getBoundingClientRect(), t=thread.getBoundingClientRect(); return r.height>0 && r.top>=t.top && r.bottom<=t.bottom+1; };
out.dismissedDuringAsk = [];
for (const mode of ['typed', 'voice', 'approval']) {
  ui.agentDone({id: 'old', title: 'Earlier task', status: 'done', result: 'Finished.'});
  ui.listen(mode === 'typed'); ui.words('Explain the result');
  if(mode === 'voice')ui.line('▸ Reading the request'); else ui.think();
  const turn=thread.lastElementChild, timer=turn.querySelector('.elapsed');
  if(mode === 'approval')ui.ask(['Continue?', 'echo preview']);
  const status=document.getElementById('status').textContent;
  ui.agentCancelled();
  const keptStatus=document.getElementById('status').textContent===status;
  if(mode === 'approval')turn.querySelector('.ok .go').click();
  ui.think(); ui.line('▸ Explaining the result'); settle();
  out.dismissedDuringAsk.push([!document.querySelector('.agent-card'), keptStatus, turn.querySelectorAll('.elapsed').length, timer===turn.querySelector('.elapsed'), inView(timer)]);
  ui.stopped('Answer stopped');
}
ui.reset();
for (let i=0;i<10;i++) {
  ui.listen(true); ui.words(i===1?'Save it as a shortcut':'Change the setting'); if(i%2===0)ui.think();
  ui.line('▸ Working on the request'); ui.line('… Here is the answer so far and'); settle();
  const turn=thread.lastElementChild;
  out.turns.push([inView(turn.querySelector('.elapsed')), inView(turn.querySelector('.step.live')), !turn.querySelector('.elapsed span'), turn.querySelectorAll('.elapsed').length]);
  ui.line('✓ Finished the request.'); if(i===1)ui.line('i Learned: change the setting'); ui.finished(); settle();
}
ui.line('i Support: Atticus is free, leave a tip'); settle();
const support=document.querySelector('.tip.kofi'), link=support.querySelector('button:not(.off)');
link.scrollIntoView(); const lr=link.getBoundingClientRect(), bg=getComputedStyle(link).backgroundColor;
out.support=[link.tagName, ui.pointer([lr.x+lr.width/2,lr.y+lr.height/2]), getComputedStyle(link).cursor]; settle();
out.support.push(bg!==getComputedStyle(link).backgroundColor);
link.click(); out.support.push(!support.isConnected); ui.pointer([]);
ui.dictate(true); ui.learned('Atticus'); const dn = document.getElementById('dn');
out.learned = [dn.textContent, getComputedStyle(dn).display, dn.className];
return out;
'''


REAL_MOUSE = r"""import Cocoa
import WebKit
// The box page in a real panel, driven by real mouse and wheel events (VM only): WebKit ignores a drag or wheel it did not get from the system.
final class H: NSObject, WKScriptMessageHandler {
    var posts: [String] = [], ready: (() -> Void)?
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        posts.append("\(m.body)")
        if (m.body as? [String: Any])?["ready"] != nil { ready?(); ready = nil }
    }
}
final class P: NSPanel { override var canBecomeKey: Bool { true } }
NSApplication.shared.setActivationPolicy(.accessory)
let h = H(), cfg = WKWebViewConfiguration(); cfg.userContentController.add(h, name: "c"); cfg.userContentController.add(h, name: "h")
let web = WKWebView(frame: NSRect(x: 0, y: 0, width: 500, height: 500), configuration: cfg)
let win = P(contentRect: NSRect(x: 100, y: 100, width: 500, height: 500), styleMask: [.nonactivatingPanel], backing: .buffered, defer: false)
win.level = .statusBar; win.contentView = web; win.orderFrontRegardless(); win.makeKey(); win.makeFirstResponder(web)
func wait(_ s: Double) { Thread.sleep(forTimeInterval: s) }   // the driver runs off the main thread: the main one must keep handing out events
func eval(_ j: String) -> Any? { var r: Any?; let d = DispatchSemaphore(value: 0); DispatchQueue.main.async { web.evaluateJavaScript(j) { a, _ in r = a; d.signal() } }; d.wait(); return r }
let box = win.frame, top = NSScreen.screens[0].frame.height
func at(_ x: Double, _ y: Double) -> CGPoint { CGPoint(x: box.minX + x, y: top - box.maxY + y) }
func mouse(_ t: CGEventType, _ x: Double, _ y: Double) {
    let e = CGEvent(mouseEventSource: CGEventSource(stateID: .privateState), mouseType: t, mouseCursorPosition: at(x, y), mouseButton: .left)!
    let kind = t == .leftMouseDown ? "mousedown" : t == .leftMouseUp ? "mouseup" : "mousemove"
    let received = "window.fixtureMouse?.type === '\(kind)' && Math.abs(fixtureMouse.x-\(x))<1 && Math.abs(fixtureMouse.y-\(y))<1"
    _ = eval("window.fixtureMouse=null")
    e.setIntegerValueField(.mouseEventClickState, value: 1); e.post(tap: .cghidEventTap)
    let deadline = Date().addingTimeInterval(3)
    while eval(received) as? Bool != true && Date() < deadline { wait(0.01) }
    precondition(eval(received) as? Bool == true, "WebKit did not receive \(kind) at \(x),\(y)")
}
func wheel(_ dx: Int32, _ dy: Int32) { for _ in 0..<6 { CGEvent(scrollWheelEvent2Source: CGEventSource(stateID: .privateState), units: .pixel, wheelCount: 2, wheel1: dy, wheel2: dx, wheel3: 0)!.post(tap: .cghidEventTap); wait(0.05) }; wait(0.3) }
h.ready = { DispatchQueue.global().async {
    _ = eval("for(const type of ['mousedown','mousemove','mouseup'])document.addEventListener(type,e=>window.fixtureMouse={type:e.type,x:e.clientX,y:e.clientY},true)")
    _ = eval("ui.listen(true);ui.words('show code');ui.think();ui.line('✓ Here it is:\\n\\n```\\n'+'long_code_line_'.repeat(30)+'\\n```\\n\\nSome ordinary words after the code box, to select.');1")
    wait(1)
    let r = eval("(()=>{const p=document.querySelector('.a pre').getBoundingClientRect(),a=document.querySelector('.a').getBoundingClientRect();return [p.x+40,p.y+15,a.x+20,a.bottom-12]})()") as! [Double]
    var out: [String: Any] = [:]
    let left = "document.querySelector('.a pre').scrollLeft"
    mouse(.mouseMoved, r[0], r[1]); wait(0.3)
    wheel(-30, 0); out["sideways"] = eval(left); _ = eval(left + "=0"); wait(0.1)
    wheel(0, -30); out["plain"] = eval(left)
    h.posts = []
    mouse(.leftMouseDown, r[2], r[3]); for i in 1...6 { mouse(.leftMouseDragged, r[2] + Double(i * 25), r[3]) }; mouse(.leftMouseUp, r[2] + 150, r[3]); wait(0.3)
    out["selected"] = eval("getSelection().toString()"); out["dragCopied"] = h.posts.contains { $0.contains("copy") }
    mouse(.leftMouseDown, r[2], r[3]); mouse(.leftMouseUp, r[2], r[3]); wait(0.6)   // a click on a selection only clears it
    out["clearCopied"] = h.posts.contains { $0.contains("copy") }; h.posts = []
    mouse(.leftMouseDown, r[2], r[3]); mouse(.leftMouseUp, r[2], r[3]); wait(0.3)
    out["clickCopied"] = h.posts.contains { $0.contains("copy") }
    print(String(data: try! JSONSerialization.data(withJSONObject: out), encoding: .utf8)!); exit(0)
} }
web.loadHTMLString(try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8), baseURL: nil)
DispatchQueue.main.asyncAfter(deadline: .now() + 40) { print("timeout"); exit(1) }
NSApplication.shared.run()
"""

# A stand-in for the user's app, in its own process: a front window with a text field; it writes "1" while active, then the field's text.
USER_APP = r"""import Cocoa
let out = CommandLine.arguments[1]
NSApplication.shared.setActivationPolicy(.regular)
let win = NSWindow(contentRect: NSRect(x: 700, y: 300, width: 300, height: 80), styleMask: [.titled], backing: .buffered, defer: false)
let field = NSTextField(frame: NSRect(x: 10, y: 28, width: 280, height: 24)); win.contentView!.addSubview(field)
win.makeKeyAndOrderFront(nil); win.makeFirstResponder(field); NSApp.activate(ignoringOtherApps: true)
Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { _ in
    try? ((NSApp.isActive ? "1" : "0") + (field.currentEditor()?.string ?? field.stringValue)).write(toFile: out, atomically: true, encoding: .utf8)
}
NSApplication.shared.run()
"""

# The box in Atticus's own kind of panel, taking and returning the keyboard with the calls App.start and App.releaseKeys use (VM only).
REAL_KEYS = r"""import Cocoa
import WebKit
final class H: NSObject, WKScriptMessageHandler {
    var ready: (() -> Void)?
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) { if (m.body as? [String: Any])?["ready"] != nil { ready?(); ready = nil } }
}
final class P: NSPanel { var keyable = true; override var canBecomeKey: Bool { keyable } }
NSApplication.shared.setActivationPolicy(.accessory)
let h = H(), cfg = WKWebViewConfiguration(); cfg.userContentController.add(h, name: "c"); cfg.userContentController.add(h, name: "h")
let web = WKWebView(frame: NSRect(x: 0, y: 0, width: 500, height: 400), configuration: cfg)
let win = P(contentRect: NSRect(x: 100, y: 100, width: 500, height: 400), styleMask: [.nonactivatingPanel], backing: .buffered, defer: false)
win.level = .statusBar; win.contentView = web
let state = CommandLine.arguments[2], top = NSScreen.screens[0].frame.height
func wait(_ s: Double) { Thread.sleep(forTimeInterval: s) }
func main<T>(_ f: @escaping () -> T) -> T { var r: T!; DispatchQueue.main.sync { r = f() }; return r }
func eval(_ j: String) -> Any? { var r: Any?; let d = DispatchSemaphore(value: 0); DispatchQueue.main.async { web.evaluateJavaScript(j) { a, _ in r = a; d.signal() } }; d.wait(); return r }
func field() -> String { (try? String(contentsOfFile: state, encoding: .utf8)) ?? "" }
func key(_ code: CGKeyCode) {
    for down in [true, false] { CGEvent(keyboardEventSource: CGEventSource(stateID: .privateState), virtualKey: code, keyDown: down)!.post(tap: .cghidEventTap) }
    wait(0.4)
}
func click(_ x: Double, _ y: Double) {
    for t in [CGEventType.leftMouseDown, .leftMouseUp] { CGEvent(mouseEventSource: CGEventSource(stateID: .privateState), mouseType: t, mouseCursorPosition: CGPoint(x: x, y: top - y), mouseButton: .left)!.post(tap: .cghidEventTap) }
    wait(0.4)
}
let box = "[document.getElementById('ask').value, document.body.classList.contains('hearing'), document.getElementById('comp').classList.contains('open')]"
h.ready = { DispatchQueue.global().async {
    var out: [String: Any] = [:]
    let deadline = Date().addingTimeInterval(10)
    while !field().hasPrefix("1") && Date() < deadline { wait(0.1) }
    out["appFront"] = field().hasPrefix("1")
    main { win.orderFrontRegardless() }; _ = eval("ui.listen();1"); wait(0.3)
    key(0)   // a
    out["off"] = [field(), eval("document.getElementById('ask').value") as? String ?? "?"] as [Any]
    main { win.makeKey(); win.makeFirstResponder(web) }; _ = eval("ui.keys(true);1"); wait(0.3)
    key(11)   // b
    let typed = eval(box) as? [Any] ?? []
    out["on"] = [field(), typed.first ?? "?", typed.count > 1 ? typed[1] : "?", typed.count > 2 ? typed[2] : "?",
                 main { NSWorkspace.shared.frontmostApplication?.processIdentifier != ProcessInfo.processInfo.processIdentifier }] as [Any]
    _ = eval("document.getElementById('ask').value='';ui.listen();ui.keys(true);1"); wait(0.3)
    _ = eval("ui.words('open notes');ui.think();ui.keys(false);1")
    var blinked = false
    let watch = main { NotificationCenter.default.addObserver(forName: NSWindow.didChangeOcclusionStateNotification, object: win, queue: .main) { _ in if !win.occlusionState.contains(.visible) { blinked = true } } }
    main { win.keyable = false; win.resignKey(); DispatchQueue.main.async { win.keyable = true } }; wait(0.3)   // as App.releaseKeys
    key(8)   // c
    out["spoken"] = [field(), eval("document.getElementById('ask').value") as? String ?? "?", main { win.isVisible && !win.isKeyWindow }, main { blinked }] as [Any]
    NotificationCenter.default.removeObserver(watch)
    main { win.makeKey(); win.makeFirstResponder(web) }; _ = eval("ui.msg('');ui.compose(true);1"); wait(0.3)
    click(850, 340)   // the user's text field
    key(2)   // d
    out["clickAway"] = [field(), main { !win.isKeyWindow }] as [Any]
    print(String(data: try! JSONSerialization.data(withJSONObject: out), encoding: .utf8)!); exit(0)
} }
web.loadHTMLString(try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8), baseURL: nil)
DispatchQueue.main.asyncAfter(deadline: .now() + 50) { print("timeout"); exit(1) }
NSApplication.shared.run()
"""


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class BoxPageTests(unittest.TestCase):
    def test_update_news_uses_the_native_click_route(self):
        got = self.render(r'''
ui.listen(); ui.words('Hello'); ui.line('✓ Ready.'); ui.updated('1.6.1');
document.getAnimations().filter(a => a.effect.getTiming().iterations !== Infinity).forEach(a => a.finish());
const r = document.querySelector('#updated button').getBoundingClientRect();
ui.tap([r.x + r.width / 2, r.y + r.height / 2]);
return document.getElementById('ask') === document.activeElement;
''')
        self.assertFalse(got['result'], 'What’s new must not open the composer')
        self.assertEqual([p for p in got['posts'] if isinstance(p, dict) and p.get('updateNews')], [{'updateNews': True}])

    def test_one_click_on_the_drawn_x_closes(self):
        # Nov 15: the lit, hover-grown × reaches below native's 42 pt × corner; a click there opened the typing box instead
        got = self.render(r'''
ui.listen(); ui.words('Hello'); ui.line('✓ Ready.');
const settle = () => document.getAnimations().filter(a => a.effect.getTiming().iterations !== Infinity).forEach(a => a.finish());
settle(); let r = document.getElementById('x').getBoundingClientRect();
ui.pointer([r.x + r.width / 2, r.y + r.height / 2]); settle(); r = document.getElementById('x').getBoundingClientRect();
ui.tap([r.x + r.width / 2, r.bottom - 2]);
return [r.bottom - 2, document.getElementById('comp').classList.contains('open')];
''')
        self.assertGreater(got['result'][0], 42)   # outside native's corner, so only the page can see it
        self.assertFalse(got['result'][1])
        self.assertIn({'close': True}, got['posts'])
        self.assertIn('if b["close"] != nil { close(clear: true) }', (ROOT / 'Atticus.swift').read_text())

    def render(self, script):
        harness = HARNESS.replace('cfg.userContentController.add(h, name: "agents")', 'cfg.userContentController.add(h, name: "c"); cfg.userContentController.add(h, name: "h")')
        harness = harness.replace('?["action"] as? String == "ready"', '?["ready"] != nil')
        self.assertEqual(harness.count('name: "c"') + harness.count('["ready"] != nil'), 2)   # the shelf harness, pointed at the box's bridge
        with tempfile.TemporaryDirectory() as tmp:
            page, src, binary = Path(tmp) / 'ui.html', Path(tmp) / 'page.swift', Path(tmp) / 'page'
            page.write_text((ROOT / 'ui/ui.html').read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text()))
            src.write_text(harness)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(page), "ui.autoMinimize(false);" + script], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        got = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual([p for p in got['posts'] if isinstance(p, dict) and 'error' in p], [])
        return got

    @unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'real mouse events: VM only')
    def test_real_mouse_scrolls_code_selects_text_and_click_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            page, src, binary = Path(tmp) / 'ui.html', Path(tmp) / 'page.swift', Path(tmp) / 'page'
            page.write_text((ROOT / 'ui/ui.html').read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text()))
            src.write_text(REAL_MOUSE)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(page)], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        out = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertGreater(out['sideways'], 0)
        self.assertGreater(out['plain'], 0)
        self.assertTrue(out['selected'].strip())
        self.assertFalse(out['dragCopied'] or out['clearCopied'])
        self.assertTrue(out['clickCopied'])

    def test_silent_tap_idle_picker_and_typed_field(self):
        got = self.render(r'''
ui.models({list:['cheapest','balanced','capable'], pick:'balanced'});
ui.listen(); ui.msg(''); ui.hover(true);
await new Promise(r => setTimeout(r, 400));
const chip = document.getElementById('model'), comp = document.getElementById('comp');
const before = [document.body.classList.contains('hearing'), chip.hidden, getComputedStyle(comp).display !== 'none'];
chip.click();
const open = comp.classList.contains('pick');
document.querySelector('#models button[data-v="capable"]').click();
await new Promise(r => setTimeout(r, 250));
const ask = document.getElementById('ask'); ask.focus(); ask.value = 'A typed request'; ask.dispatchEvent(new Event('input', {bubbles:true}));
return {before, open, model:chip.textContent, typed:ask.value, hearing:document.body.classList.contains('hearing')};
''')
        self.assertEqual(got['result'], {'before':[False, False, True], 'open':True,
            'model':'Most capable', 'typed':'A typed request', 'hearing':False})
        self.assertTrue(any(isinstance(p, dict) and p.get('model') == 'capable' for p in got['posts']))
        self.assertFalse(any(isinstance(p, dict) and p.get('mic') for p in got['posts']))

    def test_mic_click_keeps_listening_until_typing(self):
        got = self.render(r"""
await new Promise(r => setTimeout(r, 500));
const messages = [], bridge = webkit.messageHandlers.c.postMessage.bind(webkit.messageHandlers.c);
webkit.messageHandlers.c.postMessage = m => {
    messages.push(m); bridge(m);
    if (m.mic) ui.listen();
};
ui.compose(true); ui.hover(true);
const mic = document.getElementById('mic'), ask = document.getElementById('ask');
mic.dispatchEvent(new MouseEvent('mousedown', {bubbles:true})); mic.click();
ui.hover(true);
await new Promise(r => setTimeout(r, 350));
const afterClick = {mic: messages.filter(m => m.mic).length, type: messages.filter(m => m.type).length,
    hearing: document.body.classList.contains('hearing'), bubble: !!document.querySelector('.q.hear')};
ask.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
const afterMouse = document.body.classList.contains('hearing');
ui.listen(); ask.value = 'Fixture request'; ask.dispatchEvent(new Event('input', {bubbles:true}));
return {afterClick, afterMouse, afterInput: document.body.classList.contains('hearing'),
    interrupts: messages.filter(m => m.type).length};
""")['result']
        self.assertEqual(got['afterClick'], {'mic': 1, 'type': 0, 'hearing': True, 'bubble': True})
        self.assertFalse(got['afterMouse'])
        self.assertFalse(got['afterInput'])
        self.assertEqual(got['interrupts'], 2)

    def test_type_right_away_field_takes_keys_while_the_box_listens(self):
        got = self.render(r"""
const ask = document.getElementById('ask'), comp = document.getElementById('comp'), out = {};
const look = () => [document.activeElement === ask, comp.classList.contains('open'), comp.inert, document.body.classList.contains('hearing')];
ui.listen(); ui.keys(true); out.armed = look();
ui.hover(true); ui.hover(false); out.hovered = look();   // the mouse passing over keeps today's look and the keys
ask.value = 'w'; ask.dispatchEvent(new Event('input', {bubbles:true})); out.typed = [...look(), ask.value, !!document.querySelector('.q.hear')];
ask.value = ''; ask.blur(); ui.listen(); ui.keys(true); ui.words('open notes'); ui.think(); ui.keys(false); out.spoken = look();
ui.listen(); ui.keys(true); ui.msg(''); ui.compose(true); out.tapped = [...look(), !!document.querySelector('.q.hear')];
ui.compose(false); out.closed = look();
return out;
""")
        r = got['result']
        self.assertEqual(r['armed'], [True, False, False, True])   # keys reach the field; the box still shows Listening
        self.assertEqual(r['hovered'], [True, False, False, True])
        self.assertEqual(r['typed'], [True, True, False, False, 'w', False])   # the first key opens the typing box and stops listening
        self.assertEqual(r['spoken'], [False, False, True, False])   # a spoken ask gives the field up
        self.assertEqual(r['tapped'], [True, True, False, False, False])   # a tap: the typing box, ready
        self.assertEqual(r['closed'], [False, False, True, False])
        self.assertEqual(len([p for p in got['posts'] if isinstance(p, dict) and p.get('type')]), 1)

    @unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'real keystrokes and a second app: VM only')
    def test_type_right_away_keys_reach_the_box_not_the_users_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            page, field = Path(tmp) / 'ui.html', Path(tmp) / 'field.txt'
            page.write_text((ROOT / 'ui/ui.html').read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text()))
            binaries = {}
            for name, code in [('app', USER_APP), ('box', REAL_KEYS)]:
                src, binaries[name] = Path(tmp) / f'{name}.swift', Path(tmp) / name
                src.write_text(code)
                built = subprocess.run(['swiftc', str(src), '-o', str(binaries[name])], capture_output=True, text=True)
                self.assertEqual(built.returncode, 0, built.stderr)
            user = subprocess.Popen([str(binaries['app']), str(field)])
            try:
                run = subprocess.run([str(binaries['box']), str(page), str(field)], capture_output=True, text=True, timeout=60)
            finally:
                user.terminate(); user.wait(5)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        out = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertTrue(out['appFront'])
        self.assertEqual(out['off'], ['1a', ''])   # the box shown without the keyboard (setting off): keys stay in the user's app
        self.assertEqual(out['on'], ['1a', 'b', False, True, True])   # keys reach the box; the user's app stays in front; first key ends listening
        self.assertEqual(out['spoken'], ['1ac', '', True, False])   # after a spoken ask the keys go back while the box stays up, with no blink
        self.assertEqual(out['clickAway'], ['1acd', True])   # a click in the user's app takes the keys back from a ready box

    def test_quiet_follow_up_only_changes_status(self):
        got = self.render(r"""
ui.listen(); ui.words('First ask'); ui.think(); ui.line('✓ An answer to read.'); ui.finished();
const thread = document.getElementById('thread'), before = thread.innerHTML;
const orb = document.getElementById('orb').getAttribute('style');
ui.quietListen(true);
const quiet = [document.querySelector('.elapsed .hf')?.textContent, document.getElementById('status').textContent,
    document.body.classList.contains('hearing'), document.getElementById('orb').getAttribute('style') === orb];
ui.quietListen(false); const timeout = [thread.innerHTML === before, document.querySelectorAll('.hf').length];
ui.quietListen(true); ui.listen(); ui.words('And these words');
return {quiet, timeout, gone: document.querySelectorAll('.hf').length, words: thread.lastElementChild.querySelector('.q').textContent};
""")['result']
        self.assertEqual(got['quiet'], ['Listening...', '', False, True])
        self.assertEqual(got['timeout'], [True, 0])
        self.assertEqual(got['gone'], 0)
        self.assertEqual(got['words'], 'And these words')

    def test_first_partial_renders_while_still_listening(self):
        got = self.render(r"""
ui.listen();
document.getAnimations().filter(a => a.effect.getTiming().iterations !== Infinity).forEach(a => a.finish());
const start = performance.now(); ui.words('Please');
const q = document.querySelector('#thread .turn:last-child .q'), rect = q.getBoundingClientRect();
return {text:q.textContent, listening:q.classList.contains('hear'), empty:q.classList.contains('empty'),
        visible:rect.width > 0 && rect.height > 0 && getComputedStyle(q).display !== 'none' && Number(getComputedStyle(q.closest('.turn')).opacity) > .99, ms:performance.now()-start};
""")['result']
        self.assertEqual(got['text'], 'Please')
        self.assertTrue(got['listening'] and got['visible'])
        self.assertFalse(got['empty'])
        print('TRANSCRIBE WebKit first-partial DOM/layout ms:', got['ms'])

    def test_box_on_real_webkit(self):
        got = self.render(SCRIPT)
        out = got['result']
        self.assertEqual(out['brackets'], ['See [1] and a[0]', '[ ] a task'])   # a bracket that is no link shows at once
        self.assertEqual(out['open'], 'It')   # a link still arriving waits
        self.assertEqual(out['link'], ['the link', 'It the link'])
        self.assertEqual(out['final'], ['It the link and more.', False])
        self.assertEqual(out['card'][:2], ['Compare phones', 'Found three phones [1].'])
        self.assertIn('Later', ' '.join(out['card'][2]))
        self.assertEqual(out['hot'], [True, True, True, True])   # the box never activates: the native pointer tints a card button and asks for the hand
        self.assertEqual(out['off'], [False, 0])   # off the box: arrow, no tint
        self.assertEqual(out['x'], [True, True, False])   # native's × corner lights the ×
        self.assertEqual(out['agentLearned'], ['Learned', 'Say “focus time” any time.'])
        self.assertTrue(out['noStaleLearned'])
        self.assertEqual(out['steerAndNew'], 'Told the Ebikes agent: under $1500. I started an agent on “Bike locks”. I’ll ping you when it’s done.')   # one ask, both parts
        self.assertEqual(out['math'][:3], ['the area is', 'the area is', 'the area is'])   # math still arriving waits, never a raw $
        self.assertNotIn('$', out['math'][3]); self.assertTrue(out['math'][3].startswith('the area is π'))
        self.assertTrue(out['math'][4].endswith('and costs $5'))   # a price shows at once
        self.assertTrue(out['math'][5])
        self.assertEqual(out['two'], 'I started an agent on “Ebikes”. I’ll ping you when it’s done. Queued an agent for “Helmets”. It starts when another one finishes.')   # the queued one is not called started
        self.assertEqual(out['mix'], 'Queued an agent for “Tents”. It starts when another one finishes. I started agents on “Stoves” and “Maps”. I’ll ping you when they’re done.')
        self.assertEqual(out['turns'], [[True, True, True, 1]] * 10)
        self.assertEqual(out['dismissedDuringAsk'], [[True, True, 1, True, True]] * 3)
        self.assertEqual(out['support'], ['BUTTON', True, 'pointer', True, True])
        self.assertTrue(any(isinstance(p, dict) and p.get('kofi') for p in got['posts']))
        self.assertEqual(out['learned'], ['Learned “Atticus” Undo', 'flex', 'dn tick'])

    def test_minimize_keeps_live_work_and_restores_scroll(self):
        got = self.render(r'''
const tick = ms => new Promise(r => setTimeout(r, ms));
const settle = () => document.getAnimations().filter(a => a.effect.getTiming().iterations !== Infinity).forEach(a => a.finish());
ui.listen(true); ui.words('Explain'); ui.think(); ui.mode(false);
ui.line('✓ ' + 'A long answer. '.repeat(300));
const thread = document.getElementById('thread'), fold = document.getElementById('fold');
const shown = id => getComputedStyle(document.getElementById(id)).display !== 'none';
thread.dispatchEvent(new WheelEvent('wheel', {deltaY: -1})); thread.scrollTop = 45;
const scroll = thread.scrollTop, height = document.getElementById('card').offsetHeight;
fold.click();
await tick(350); settle();
const out = {compact: [document.body.classList.contains('folded'), document.getElementById('card').offsetHeight < height,
  ...['orb', 'status', 'x'].map(shown), ...['thread', 'comp', 'mode', 'agents-pill', 'grip'].map(shown), fold.getAttribute('aria-expanded')]};
ui.line('▸ Reading the document'); out.step = document.getElementById('status').textContent;
ui.hover(true); out.hover = [document.body.classList.contains('folded'), shown('comp')];
ui.pointer([10, 10]); out.affordance = getComputedStyle(fold).opacity; ui.pointer([]);
const r = fold.getBoundingClientRect(); ui.pointer([r.x + r.width / 2, r.y + r.height / 2]); ui.tap([r.x + r.width / 2, r.y + r.height / 2]); await tick(350); settle(); out.restored = [thread.scrollTop === scroll, shown('mode'), fold.getAttribute('aria-expanded')];
fold.click(); await tick(350); settle();
ui.finished(); await tick(350); settle();
out.done = [document.body.classList.contains('folded'), shown('thread'), thread.scrollHeight - thread.scrollTop - thread.clientHeight < 2];
fold.click(); await tick(350); settle(); ui.listen(); out.next = [document.body.classList.contains('folded'), shown('thread')];
fold.click(); await tick(350); settle(); ui.compose(true); out.typing = !document.body.classList.contains('folded');
return out;
''')
        self.assertEqual(got['result'], {
            'compact': [True, True, True, True, True, False, False, False, False, False, 'false'],
            'step': 'Reading the document', 'hover': [True, False], 'affordance': '1',
            'done': [False, True, True], 'restored': [True, True, 'true'],
            'next': [False, True], 'typing': True,
        })
        self.assertIn(56, got['posts'])  # the native height bridge shrinks the actual panel

    def test_two_answers_reopen_after_back_to_back_asks_and_retry(self):
        got = self.render(r'''
const tick = () => new Promise(r => setTimeout(r, 350));
const folded = () => document.body.classList.contains('folded');
const out = [];
ui.autoMinimize(true);
for (const delay of [0, 50, 350]) {
  ui.reset(); ui.listen(); ui.words('First question'); ui.think(); await tick();
  ui.line('… First answer is arriving and'); ui.line('✓ First answer.'); ui.finished();
  await new Promise(r => setTimeout(r, delay));
  ui.listen(); ui.words('Second question'); ui.think(); await tick();
  const working = folded();
  ui.line('… Second answer is arriving and'); ui.line('✓ Second answer.'); ui.finished(); await tick();
  out.push([delay, working, folded(), document.querySelector('#thread .turn:last-child .a').textContent]);
}
ui.listen(); ui.words('First streaming question'); ui.think(); ui.line('… First answer is still arriving and');
ui.listen(); ui.words('Interrupt with a second question'); ui.think(); await tick();
ui.line('✓ Second answer after interruption.'); ui.finished(); await tick(); out.push(['stream', folded()]);
ui.upgrade('retry'); ui.upgradeStarted('retry'); ui.line('… Stronger answer is arriving and');
ui.line('✓ Stronger answer.'); ui.finished(); await tick(); out.push(['retry', folded()]);
return out;
''')
        self.assertEqual(got['result'], [[delay, True, False, 'Second answer.'] for delay in [0, 50, 350]] + [['stream', False], ['retry', False]])
        self.assertEqual([p for p in got['posts'] if isinstance(p, dict) and 'autoMinimize' in p], [])

    def test_retained_drawing_does_not_keep_the_next_plain_answer_folded(self):
        got = self.render(r'''
const tick = () => new Promise(r => setTimeout(r, 350));
const folded = () => document.body.classList.contains('folded');
ui.autoMinimize(true); ui.listen(); ui.words('Show the first item'); ui.think(); ui.drawing(true);
ui.line('✓ It is on screen.'); ui.finished(); await tick(); const first = folded();
ui.listen(); ui.words('Explain that in words'); ui.think(); await tick(); const working = folded();
ui.line('… Here is the explanation and'); ui.line('✓ Here is the explanation.'); ui.finished(); await tick();
const second = folded();
ui.listen(); ui.think(); ui.drawing(true); ui.line('✓ Another drawing.'); ui.finished(); await tick();
ui.upgradeStarted('retained'); ui.line('✓ A stronger text explanation.'); ui.finished(); await tick();
return [first, working, second, folded()];
''')
        self.assertEqual(got['result'], [True, True, False, False])

    def test_final_graph_replaces_a_streamed_curve_with_the_same_labels(self):
        got = self.render(r'''
const first = {type:'function',title:'Graph',x:[-5,5],y:[-5,5],curves:[{fn:'x',label:'Trend'}]};
const second = {...first,curves:[{fn:'-x',label:'Trend'}]};
ui.listen(); ui.words('Graph'); ui.think();
ui.line('… ```graph\n'+JSON.stringify(first)+'\n```\nReady and');
const before = document.querySelector('.turn:last-child .graph');
const path = before.querySelector('svg path[stroke="#368de8"]').getAttribute('d');
ui.line('✓ ```graph\n'+JSON.stringify(second)+'\n```\nReady.');
const after = document.querySelector('.turn:last-child .graph');
return [after.dataset.spec === JSON.stringify(second), before !== after,
        after.querySelector('svg path[stroke="#368de8"]').getAttribute('d') !== path];
''')
        self.assertEqual(got['result'], [True, True, True])

    def test_automatic_fold_lifecycle_and_manual_preference(self):
        got = self.render(r'''
const tick = () => new Promise(r => setTimeout(r, 350));
const folded = () => document.body.classList.contains('folded');
const out = {};
ui.autoMinimize(true); ui.listen(); ui.words('Explain plants'); await tick(); out.talking = folded();
ui.think(); await tick(); out.working = [folded(), document.getElementById('card').offsetHeight];
ui.tap([30,20]); await tick(); out.opened = folded();
ui.listen(); ui.words('Again'); ui.think(); await tick(); out.savedOff = folded();
document.getElementById('fold').click(); await tick();
ui.listen(); ui.words('Again'); ui.think(); await tick(); out.savedOn = folded();
ui.line('… Plants capture sunlight and'); await tick(); out.streaming = folded();
ui.listen(); ui.think(); ui.line('… Immediate answer and'); await tick(); out.fast = folded();
ui.listen(); ui.think(); ui.listen(); await tick(); out.interrupt = folded();
ui.listen(); ui.think(); ui.drawing(true); await tick();
ui.line('… Here are the marks and'); ui.line('✓ Done'); ui.finished(); await tick(); out.drawing = folded();
ui.ask(['Continue?', 'echo preview']); await tick(); out.confirm = folded();
document.querySelector('.ok .go').click(); ui.line('✓ Approved'); ui.finished(); await tick(); await tick(); await tick(); out.confirmFinish = folded();
ui.listen(); ui.think(); await tick(); ui.ask(['First?', 'echo first']); await tick();
document.querySelector('.ok:not(.gone) .go').click(); await tick();
ui.pick({q:'Second?', options:[{label:'Blue'}]}); await tick(); await tick(); await tick(); out.nextCard = folded();
document.querySelector('.pk:not(.gone) .c').click(); ui.line('✓ Picked'); ui.finished(); await tick(); await tick(); await tick();
ui.drawing(false); ui.listen(); ui.think(); await tick(); ui.msg('Could not finish'); await tick(); out.error = folded();
ui.listen(); ui.think(); await tick(); ui.finished(); await tick(); out.empty = [folded(), document.getElementById('status').textContent];
ui.listen(); ui.think(); await tick(); ui.pick({q:'Which?',options:[{label:'Blue'}]}); await tick(); out.pick = folded();
ui.listen('dict'); ui.think(); await tick(); out.dictation = [folded(),document.body.classList.contains('dictate')];
return out;
''')
        self.assertEqual(got['result'], dict(talking=False, working=[True,56], opened=False,
            savedOff=False, savedOn=True, streaming=False, fast=False, interrupt=False, drawing=True,
            confirm=False, confirmFinish=False, nextCard=False, error=False, empty=[False,'Done'], pick=False, dictation=[False,True]))
        self.assertEqual([p['autoMinimize'] for p in got['posts'] if isinstance(p,dict) and 'autoMinimize' in p], [False,True])

    def test_picker_renders_answers_and_accepts_spoken_other(self):
        got = self.render(r'''
ui.listen(); ui.words('choose'); ui.think();
ui.pick({q: '**Which** $x^2$?', options: [{label: '**Answer** $\\frac{1}{2}$ <img src=x onerror=alert(1)>', sub: ''}]});
const card = document.querySelector('.pk'), title = card.querySelector('b'), label = card.querySelector('.n');
const out = {rich: [title.querySelector('strong')?.textContent, title.querySelectorAll('math').length, label.querySelector('strong')?.textContent, label.querySelectorAll('math').length], safe: !label.querySelector('img,script') && label.textContent.includes('<img'), margins: [getComputedStyle(title.firstChild).marginTop, getComputedStyle(label.firstChild).marginBottom]};
out.responded = ui.respond('use a different answer'); out.gone = card.classList.contains('gone');
return out;
''')
        self.assertEqual(got['result'], {'rich': ['Which', 1, 'Answer', 1], 'safe': True,
                                        'margins': ['0px', '0px'], 'responded': True, 'gone': True})
        self.assertEqual([p['pick'] for p in got['posts'] if isinstance(p, dict) and 'pick' in p],
                         ['=use a different answer'])

    def test_talking_over_a_picker_hides_it_and_cancel_brings_it_back(self):
        got = self.render(r'''
ui.listen(); ui.words('choose'); ui.think();
ui.pick({q: 'Which?', options: [{label: 'Blue', sub: ''}, {label: 'Red', sub: ''}]});
const card = document.querySelector('.pk'), reply = () => document.querySelector('.q.reply'), status = () => document.getElementById('status').textContent;
ui.pickHear(''); ui.pickHear('the red');
const out = {hidden: card.hidden, said: reply()?.textContent, status: status(), box: document.getElementById('ask').value};
ui.pickHear(); out.back = [card.hidden, !!reply(), status(), card.querySelectorAll('.c').length];
ui.pickHear(''); ui.pickHear('the red one'); out.responded = ui.respond('the red one'); out.gone = card.classList.contains('gone') && !reply();
return out;
''')
        self.assertEqual(got['result'], {'hidden': True, 'said': 'the red', 'status': 'Listening…', 'box': '',
                                         'back': [False, False, 'Waiting for you', 2], 'responded': True, 'gone': True})
        self.assertEqual([p['pick'] for p in got['posts'] if isinstance(p, dict) and 'pick' in p], ['=the red one'])


if __name__ == '__main__':
    unittest.main()
