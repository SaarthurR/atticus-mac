"""Settings' "More info when minimized" preview: the row's hover messages and the real box's minimized shapes, VM only.

The box is the real page with the real fold handler (tests.test_minibox harness). App.foldPreview's show/hide is mirrored here
in a few lines (the whole App does not build in a fixture). Shots go to test-artifacts/fold-preview and print as "PNG <name> <base64>".
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.test_minibox import harness, SOURCE, ROOT
from tests.shoot_settings import PREFS, STATE

DRIVER = r'''
final class SettingsSink: NSObject, WKScriptMessageHandler {   // Settings' bridge: what SettingsWindow.handle does for these two messages
    var previews: [Bool] = [], previewing = false, overOpen = false
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        guard let b = m.body as? [String: Any] else { return }
        if b["do"] as? String == "foldPreview" {
            let on = b["on"] as? Bool == true; previews.append(on)
            if on { previewing = true; overOpen = box.panel.isVisible; box.web.evaluateJavaScript("ui.foldPreview(true)") { _, _ in if !self.overOpen { box.panel.orderFrontRegardless() } } }   // as App.foldPreview: an open box minimizes where it is
            else if previewing { previewing = false; if !overOpen { box.panel.orderOut(nil) }; box.js("foldPreview", false) }
        }
        if b["do"] as? String == "set", b["k"] as? String == "fullFold" { box.js("tiny", !(b["v"] as? Bool == true)) }
    }
}
let sink = SettingsSink(), scfg = WKWebViewConfiguration(); scfg.userContentController.add(sink, name: "st")
let screen = NSScreen.screens[0].visibleFrame
let sw = NSWindow(contentRect: NSRect(x: screen.minX + 200, y: screen.maxY - 620, width: 780, height: 560), styleMask: [.titled, .closable, .fullSizeContentView], backing: .buffered, defer: false)
sw.titlebarAppearsTransparent = true; sw.titleVisibility = .hidden
let sv = WKWebView(frame: NSRect(x: 0, y: 0, width: 780, height: 532), configuration: scfg); sv.setValue(false, forKey: "drawsBackground")
let sbg = NSVisualEffectView(frame: sw.contentRect(forFrameRect: sw.frame)); sbg.material = .underWindowBackground; sbg.blendingMode = .behindWindow; sbg.state = .active
sbg.addSubview(sv); sw.contentView = sbg
sv.loadHTMLString(try! String(contentsOfFile: CommandLine.arguments[4], encoding: .utf8), baseURL: nil)
box.panel.setFrameOrigin(NSPoint(x: screen.minX + 14, y: screen.maxY - 10 - box.panel.frame.height))   // App.show's top-left spot
func sjs(_ s: String) -> Any? { var r: Any?; let d = DispatchSemaphore(value: 0); DispatchQueue.main.async { sv.evaluateJavaScript(s + "; 1") { a, e in r = e == nil ? a : "\(e!)"; d.signal() } }; d.wait(); return r }
func shoot(_ name: String) {
    let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
    let top = NSScreen.screens[0].frame.maxY
    p.arguments = ["-x", "-R\(Int(screen.minX)),\(Int(top - screen.maxY)),1000,640", CommandLine.arguments[5] + "/" + name + ".png"]
    try! p.run(); p.waitUntilExit()
}
box.ready = { DispatchQueue.global().async {
    var out: [String: Any] = [:]
    func js(_ s: String) { _ = eval(s + "; 1") }
    func state() -> [String: Any] { ["w": main { Double(box.panel.frame.width) }, "h": panelH(), "card": card(), "shown": main { box.panel.isVisible },
        "folded": eval("document.body.classList.contains('folded')") as? Bool ?? false, "status": eval("document.getElementById('status').textContent") as? String ?? "",
        "x": main { Double(box.panel.frame.minX) }, "top": main { Double(box.panel.frame.maxY) }, "text": eval("document.getElementById('thread').textContent") as? String ?? "",
        "scroll": eval("document.getElementById('thread').scrollTop") as? Double ?? -1] }
    js("ui.autoMinimize(true); ui.visible(true); ui.tiny(true); ui.listen(); ui.words('Earlier question'); ui.think(); ui.line('✓ Earlier answer.'); ui.finished()"); wait(1.0)
    out["before"] = state()
    for _ in 0..<60 { if sjs("typeof st") as? String == "object" { break }; wait(0.5) }
    _ = sjs(#"st.load({prefs: PREFS_JSON, state: STATE_JSON, routines: []}); st.tab('box'); document.querySelector('main').scrollTop = 0"#)
    main { NSApp.activate(ignoringOtherApps: true); sw.makeKeyAndOrderFront(nil) }; wait(1.0)
    let row = "document.querySelector('[data-k=fullFold]').closest('.row')"
    out["open-before"] = state(); shoot("open-before")   // the answer box is open: the hover takes it over and gives it back
    _ = sjs("\(row).dispatchEvent(new MouseEvent('mouseenter'))"); wait(0.8)
    out["open-hover"] = state(); out["open-key"] = main { sw.isKeyWindow }; shoot("open-hover")
    _ = sjs("\(row).dispatchEvent(new MouseEvent('mouseleave'))"); wait(0.8)
    out["open-back"] = state(); shoot("open-back")
    main { box.panel.orderOut(nil) }
    _ = sjs("\(row).dispatchEvent(new MouseEvent('mouseenter'))"); wait(0.15)
    out["hidden-at-once"] = state()   // the fold message landed before the panel came up: no ease from the full box
    wait(0.6); out["circle"] = state(); out["circle-key"] = main { sw.isKeyWindow }; shoot("off-circle")
    _ = sjs("document.querySelector('[data-k=fullFold]').click()"); wait(0.8)
    out["bar"] = state(); shoot("on-bar")
    _ = sjs("\(row).dispatchEvent(new MouseEvent('mouseleave'))"); wait(0.6)
    out["after"] = state(); shoot("left")
    _ = sjs("\(row).dispatchEvent(new MouseEvent('mouseenter'))"); wait(0.6)
    main { sink.previewing = false; box.js("listen"); box.js("foldPreview", false) }; wait(0.6)   // the hotkey's ask: listen, then App.show ends the preview
    out["taken"] = state()
    _ = sjs("\(row).dispatchEvent(new MouseEvent('mouseleave'))"); wait(0.6)
    out["taken-left"] = state()
    out["previews"] = sink.previews
    print(String(data: try! JSONSerialization.data(withJSONObject: out), encoding: .utf8)!); exit(0)
} }
box.web.loadHTMLString(try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8), baseURL: nil)
DispatchQueue.main.asyncAfter(deadline: .now() + 60) { print("timeout"); exit(1) }
NSApplication.shared.run()
'''


@unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'real panel and Settings: VM only')
class FoldPreviewTests(unittest.TestCase):
    def test_hovered_row_shows_the_real_minimized_box_and_leaving_puts_it_back(self):
        out = ROOT / 'test-artifacts' / 'fold-preview'; out.mkdir(parents=True, exist_ok=True)
        page = lambda name: (ROOT / 'ui' / name).read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text())
        prefs = {**PREFS, 'fullFold': False, 'autoMinimize': True, 'followPointer': True, 'miniScreen': True, 'showAnswers': 'stream'}
        driver = DRIVER.replace('PREFS_JSON', json.dumps(prefs)).replace('STATE_JSON', json.dumps(STATE))
        with tempfile.TemporaryDirectory() as tmp:
            box, settings, src, binary = [Path(tmp) / n for n in ('ui.html', 'settings.html', 'preview.swift', 'preview')]
            box.write_text(page('ui.html')); settings.write_text(page('settings.html'))
            src.write_text(harness(SOURCE).split('box.ready = {')[0] + driver)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(box), '{}', 'dark', str(settings), str(out)], capture_output=True, text=True, timeout=90)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        for png in sorted(out.glob('*.png')): print('PNG', png.name, base64.b64encode(png.read_bytes()).decode(), flush=True)
        got = json.loads(run.stdout.strip().splitlines()[-1])
        print('PREVIEW_STATES', json.dumps(got), flush=True)
        self.assertEqual(got['previews'], [True, False, True, False, True, False], 'hover enter and leave, three times')
        ob, oh, back = got['open-before'], got['open-hover'], got['open-back']
        self.assertEqual((ob['shown'], ob['folded'], ob['w']), (True, False, 400), ob)
        self.assertIn('Earlier answer', ob['text'])
        self.assertEqual((oh['shown'], oh['folded'], oh['w'], oh['h'], oh['x'], oh['top'], oh['status']), (True, True, 36, 36, ob['x'], ob['top'], 'Thinking…'), oh)
        self.assertTrue(got['open-key'], 'the preview took key focus from Settings')
        for k in ('shown', 'folded', 'w', 'h', 'x', 'top', 'text', 'status', 'scroll'): self.assertEqual(back[k], ob[k], (k, back, ob))
        self.assertEqual((got['hidden-at-once']['w'], got['hidden-at-once']['h']), (36, 36), got['hidden-at-once'])
        c = got['circle']; self.assertEqual((c['w'], c['h'], c['folded'], c['shown']), (36, 36, True, True), c)
        self.assertTrue(got['circle-key'], 'the preview took key focus from Settings')
        b = got['bar']; self.assertEqual((b['w'], b['folded'], b['status']), (400, True, 'Thinking…'), b)
        self.assertAlmostEqual(b['h'], b['card'], delta=1, msg=b)
        a, before = got['after'], got['before']
        self.assertEqual((a['shown'], a['folded'], a['status'], a['w']), (False, before['folded'], before['status'], 400), a)
        self.assertAlmostEqual(a['h'], a['card'], delta=1, msg=a)
        for k in ('taken', 'taken-left'):   # an ask during the preview opens unfolded with its own status, and leaving the row leaves it
            t = got[k]; self.assertEqual((t['shown'], t['folded'], t['status'], t['w']), (True, False, 'Listening…', 400), (k, t))
