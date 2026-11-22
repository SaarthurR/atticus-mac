"""The minimized box on the real page and the real native height code (VM): the panel hugs the folded row."""
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest

from tests import swift_motion

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'Atticus.swift').read_text()


def harness(source):
    app = source[source.index('final class App: NSObject, WKScriptMessageHandler {'):]
    size = app[app.index('        let size = ((m.body as? [NSNumber])'):app.index('        if drawing.active && !stuck && !dragging { avoidDrawing() }   // grew onto')]
    fold = app[app.index('            if let id = b["fold"] as? Int'):app.index('            if let h = b["comp"] as? NSNumber')]
    settle = app[app.index('    var easing = NSRect.zero'):app.index('    var followTimer: Timer?')]
    return 'import Cocoa\nimport WebKit\n' + swift_motion(source) + r'''
enum Prefs { static func str(_ k: String) -> String { "top-left" }; static func num(_ k: String) -> Double { 400 } }
func boxWidth(_ saved: Double, _ bounds: NSRect) -> CGFloat { CGFloat(saved) }
struct Drawing { var active = false }
final class KeyPanel: NSPanel { override var canBecomeKey: Bool { true } }
final class Box: NSObject, WKScriptMessageHandler {
    let panel = KeyPanel(contentRect: NSRect(x: 100, y: 500, width: 400, height: 76), styleMask: [.nonactivatingPanel, .borderless], backing: .buffered, defer: false)
    var web: WKWebView!
    var fromTop = false, pillOn = false, tiny = false, dragging = false, stuck = false, drawing = Drawing()
    func avoidDrawing() {}
    func glide(_ f: NSRect, done: (() -> Void)? = nil) { frame(f); done?() }
    func frame(_ f: NSRect, on: NSScreen? = nil, animate: Bool = false) { (animate ? panel.animator() : panel).setFrame(f, display: true) }
    func js(_ call: String, _ arg: Any? = nil) {
        let a = arg.flatMap { try? JSONSerialization.data(withJSONObject: [$0]) }.flatMap { String(data: $0, encoding: .utf8) } ?? "[]"
        web.evaluateJavaScript("ui.\(call)(...\(a))")
    }
''' + settle + r'''
    var ready: (() -> Void)?, asked = 0.0
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        if m.name == "c", let b = m.body as? [String: Any] {
            if b["ready"] != nil { ready?(); ready = nil }
            if b["fold"] != nil { asked = (b["h"] as? NSNumber)?.doubleValue ?? -1 }
            command(b); return
        }
        sized(m)
    }
    func command(_ b: [String: Any]) {
''' + fold + r'''    }
    func sized(_ m: WKScriptMessage) {
''' + size + r'''    }
    func click(_ x: Double, _ y: Double) {   // the box's mouse-up on a click: as App's local monitor does it
        settle(); dragging = true; dragging = false
        panel.makeKey(); panel.makeFirstResponder(web); js("tap", [x, y])
    }
}
NSApplication.shared.setActivationPolicy(.accessory)
let box = Box(), cfg = WKWebViewConfiguration()
cfg.userContentController.add(box, name: "c"); cfg.userContentController.add(box, name: "h")
box.web = WKWebView(frame: NSRect(x: 0, y: 0, width: 400, height: 76), configuration: cfg)
box.web.setValue(false, forKey: "drawsBackground"); box.web.autoresizingMask = [.width, .height]
NSApp.appearance = NSAppearance(named: CommandLine.arguments[3] == "light" ? .aqua : .darkAqua)
let bg = NSVisualEffectView(frame: box.web.frame)   // as the app's box: the panel's own background shows any height the page leaves empty
bg.material = .hudWindow; bg.state = .active; bg.wantsLayer = true; bg.autoresizingMask = [.width, .height]; bg.appearance = NSAppearance(named: .darkAqua)
bg.layer?.cornerRadius = 18; bg.layer?.masksToBounds = true
let tint = NSView(frame: box.web.frame); tint.wantsLayer = true; tint.autoresizingMask = [.width, .height]
tint.layer?.backgroundColor = NSColor(calibratedRed: 18/255, green: 18/255, blue: 20/255, alpha: 0.85).cgColor
bg.addSubview(tint); bg.addSubview(box.web); box.panel.contentView = bg
box.panel.isOpaque = false; box.panel.backgroundColor = .clear; box.panel.level = .statusBar; box.panel.orderFrontRegardless()
func wait(_ s: Double) { Thread.sleep(forTimeInterval: s) }
func main<T>(_ f: @escaping () -> T) -> T { var r: T?; DispatchQueue.main.sync { r = f() }; return r! }
func eval(_ j: String) -> Any? { var r: Any?; let d = DispatchSemaphore(value: 0); DispatchQueue.main.async { box.web.evaluateJavaScript(j) { a, _ in r = a; d.signal() } }; d.wait(); return r }
func card() -> Double { eval("document.getElementById('card').offsetHeight") as? Double ?? -1 }
func panelH() -> Double { main { Double(box.panel.frame.height) } }
let scenarios = (try! JSONSerialization.jsonObject(with: CommandLine.arguments[2].data(using: .utf8)!)) as! [String: String]
box.ready = { DispatchQueue.global().async {
    var out: [String: Any] = [:]
    for (name, setup) in scenarios.sorted(by: { $0.key < $1.key }) {
        _ = eval("ui.autoMinimize(false); ui.reset(); ui.visible(true); 1"); wait(0.3)
        _ = eval(setup + "; 1"); wait(0.6)
        main { box.js("hover", true) }; wait(0.4)
        let r = eval("(() => { const r = document.getElementById('fold').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2] })()") as! [Double]
        let before = [panelH(), card()]
        main { box.click(r[0], r[1]) }; wait(0.05); let asked = main { box.asked }
        var trace: [[Double]] = []
        for _ in 0..<40 { wait(0.025); trace.append([panelH(), card()]) }
        main { box.js("hover", false) }; wait(0.6)
        let shot = NSTemporaryDirectory() + UUID().uuidString + ".png", capture = Process()
        capture.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture"); capture.arguments = ["-x", "-o", "-l\(main { box.panel.windowNumber })", shot]
        try! capture.run(); capture.waitUntilExit()
        if let png = try? Data(contentsOf: URL(fileURLWithPath: shot)) { print("SHOT \(name) " + png.base64EncodedString()); try? FileManager.default.removeItem(atPath: shot) }
        out[name] = ["before": before, "folded": eval("document.body.classList.contains('folded')") as? Bool ?? false,
                     "panel": panelH(), "card": card(), "asked": asked, "trace": trace]
    }
    print(String(data: try! JSONSerialization.data(withJSONObject: out), encoding: .utf8)!); exit(0)
} }
box.web.loadHTMLString(try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8), baseURL: nil)
DispatchQueue.main.asyncAfter(deadline: .now() + 60) { print("timeout"); exit(1) }
NSApplication.shared.run()
'''


SCENARIOS = {
    'thinking': "ui.listen(); ui.words('Explain how photosynthesis works'); ui.think()",
    'streaming': "ui.listen(); ui.words('Explain it'); ui.think(); ui.line('… ' + 'Plants turn light into sugar. '.repeat(20))",
    'done': "ui.listen(); ui.words('Explain it'); ui.think(); ui.line('✓ ' + 'Plants turn light into sugar. '.repeat(20)); ui.finished()",
}


@unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'a real panel: VM only')
class MinimizedBoxTests(unittest.TestCase):
    def test_minimized_panel_hugs_the_folded_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            page, src, binary = Path(tmp) / 'ui.html', Path(tmp) / 'box.swift', Path(tmp) / 'box'
            page.write_text((ROOT / 'ui/ui.html').read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text()))
            src.write_text(harness(SOURCE))
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            runs = {look: subprocess.run([str(binary), str(page), json.dumps(SCENARIOS), look], capture_output=True, text=True, timeout=90) for look in ('dark', 'light')}
        for look, run in runs.items():
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            for line in run.stdout.splitlines():
                if line.startswith('SHOT '): print(f'MINIBOX_SHOT {look} ' + line[5:], flush=True)
            out = json.loads(run.stdout.strip().splitlines()[-1])
            print('MINIBOX', look, json.dumps({k: {**v, 'trace': v['trace'][:4]} for k, v in out.items()}))
            for name, got in out.items():
                with self.subTest(f'{look} {name}'):
                    self.assertTrue(got['folded'])
                    self.assertEqual(got['asked'], got['card'], f'{name}: the fold asked for a height other than the folded row')
                    self.assertEqual(got['panel'], got['card'], f'{name}: the minimized panel does not hug the folded row')


if __name__ == '__main__':
    unittest.main()
