"""The box making room for a drawing, on a real panel, VM only (opt-in, not discovered: run this module by name).

run.sh ~/Projects/atticus tests.shoot_box_move  → the box's top-left corner every 1/120 s ("TRACE"), a summary ("MOVE ...")
and one screen recording ("MOV box-move <base64>"). The placement, glide, frame and page-resize code are the app's own.
"""
import base64
import os
import unittest
from pathlib import Path
from tests import run_swift, swift_motion

ROOT = Path(__file__).resolve().parents[1]


def box_move_source(source, scenario, reduced=False):
    """A box harness around Atticus.swift's own avoidDrawing, glide, frame and page-resize code, then `scenario`."""
    app = source[source.index('final class App: NSObject, WKScriptMessageHandler {'):]
    placement = app[app.index('    var boxHome:'):app.index('    func followPointerScreen()')]
    fold = app[app.index('            if let id = b["fold"] as? Int'):app.index('            if let h = b["comp"] as? NSNumber')]
    resize = app[app.index('    func frame(_ requested:'):app.index('    // Which edges the point')]
    settle = app[app.index('    var easing = NSRect.zero'):app.index('    var followTimer: Timer?')]
    size = app[app.index('        let size = ((m.body as? [NSNumber])'):app.index('    func js(_ call: String')]
    clamp = source[source.index('    static func clamp('):source.index('    // The same frame on another display')]
    search = source[source.index('    static func clearSpot('):source.index('    static func valid(')]
    body = ('import Cocoa\n' + swift_motion(source) + '''
var fixtureReduced = REDUCED
struct Prefs { static func num(_ k: String) -> Double { k == "boxH" ? 300 : 360 }; static func str(_ k: String) -> String { "top-left" } }
func boxWidth(_ width: Double, _ bounds: CGRect) -> CGFloat { 360 }
enum MeetingFrame {
''' + clamp + '''}
enum ScreenDrawing {
''' + search + '''}
final class Drawing { var active = false, occupied: [CGRect] = []; var layoutBounds: [CGRect] { occupied } }
struct Message { let body: Any }
final class Box {
    let panel = NSPanel(contentRect: NSRect(x:0,y:0,width:360,height:120), styleMask:[.borderless,.nonactivatingPanel], backing:.buffered, defer:false)
    let drawing = Drawing()
    var dragging = false, hovering = false, stuck = false, pillOn = false, tiny = false, fromTop = false, compH: CGFloat = 0
    func js(_ name: String, _ data: Any? = nil) {}
    func hide(after: Double) {}
''' + resize + settle + placement + '''
    func fold(_ h: Double) {
        let b: [String: Any] = ["fold": 1, "h": NSNumber(value:h)]
''' + fold + '''    }

    func post(_ m: Message) {
''' + size + '''}
''').replace('NSWorkspace.shared.accessibilityDisplayShouldReduceMotion', 'fixtureReduced').replace('REDUCED', 'true' if reduced else 'false')
    return body + '''
let nsapp = NSApplication.shared; nsapp.setActivationPolicy(.accessory)
func after(_ s: Double, _ f: @escaping () -> Void) { DispatchQueue.main.asyncAfter(deadline: .now() + s, execute: f) }
let screen = NSScreen.screens[0], top = screen.frame.maxY, vf = screen.visibleFrame
let box = Box()
box.panel.isOpaque = false; box.panel.backgroundColor = .clear; box.panel.hasShadow = true; box.panel.level = .floating
let glass = NSVisualEffectView(frame: NSRect(x:0,y:0,width:360,height:120)); glass.material = .hudWindow; glass.state = .active
glass.appearance = NSAppearance(named: .darkAqua); glass.wantsLayer = true; glass.layer?.cornerRadius = 18; glass.layer?.masksToBounds = true; glass.autoresizingMask = [.width, .height]
let label = NSTextField(labelWithString: "Atticus  ·  Thinking…"); label.textColor = .white; label.font = .systemFont(ofSize: 14, weight: .medium)
label.frame = NSRect(x: 20, y: 80, width: 300, height: 22); label.autoresizingMask = [.minYMargin]; glass.addSubview(label)
box.panel.contentView = glass
box.panel.setFrame(NSRect(x: vf.minX + 14, y: vf.maxY - 10 - 120, width: 360, height: 120), display: true); box.panel.orderFrontRegardless()
let home = box.panel.frame
// the drawing: marks over the box's corner of the screen (top-left points, as DrawingView reports them)
let marks = CGRect(x: home.minX + 40, y: top - home.maxY + 30, width: 520, height: 360)
let ink = NSWindow(contentRect: NSRect(x: marks.minX, y: top - marks.maxY, width: marks.width, height: marks.height), styleMask: [.borderless], backing: .buffered, defer: false)
ink.isOpaque = false; ink.backgroundColor = .clear; ink.level = .statusBar; ink.ignoresMouseEvents = true
let inkView = NSView(frame: NSRect(origin: .zero, size: marks.size)); inkView.wantsLayer = true
inkView.layer?.borderColor = NSColor.systemRed.cgColor; inkView.layer?.borderWidth = 5; inkView.layer?.cornerRadius = 14; ink.contentView = inkView
var trace: [(Double, CGFloat, CGFloat, CGFloat)] = [], t0 = 0.0
func sample() { let f = box.panel.frame; trace.append((ProcessInfo.processInfo.systemUptime - t0, f.minX, f.maxY, f.height)) }
func startDrawing() { ink.orderFrontRegardless(); box.drawing.active = true; box.drawing.occupied = [marks]; box.avoidDrawing() }
func endDrawing() { ink.orderOut(nil); box.drawing.active = false; box.drawing.occupied = []; box.avoidDrawing() }
func grow(_ h: CGFloat) { box.post(Message(body: [NSNumber(value: Double(h))])) }   // the app's handler calls avoidDrawing itself
''' + scenario + '''
nsapp.run()
'''


# The answer streams (the page eases each new line's height) while the drawing starts, as an explain answer does.
SCENARIO = r'''
let record = ProcessInfo.processInfo.environment["BOX_MOVE_MOV"] ?? ""
var cap: Process?
if !record.isEmpty { let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture"); p.arguments = ["-x","-v","-V","7",record]; try? p.run(); cap = p }
after(record.isEmpty ? 0.3 : 1.5) {
    t0 = ProcessInfo.processInfo.systemUptime
    let tick = Timer(timeInterval: 1.0/120, repeats: true) { _ in sample() }; RunLoop.main.add(tick, forMode: .common)
    for i in 0..<12 { after(0.4 + Double(i) * 0.09) { grow(CGFloat(120 + (i + 1) * 20)) } }
    after(0.8) { startDrawing() }
    after(3.0) { endDrawing() }
    after(4.6) {
        tick.invalidate()
        // a jump is one position change covering much of the move; speed between samples isn't: the animation ticks on its own clock
        // (about 30 Hz in a loaded VM), so two samples 4 ms apart can straddle one ordinary step
        var steps: [CGFloat] = [], turns = 0, last: CGVector? = nil
        for (a, b) in zip(trace, trace.dropFirst()) where b.0 > 0.75 && b.0 < 2.9 {
            let d = CGVector(dx: b.1 - a.1, dy: b.2 - a.2), len = hypot(d.dx, d.dy)
            if len > 0.5 { steps.append(len); if let l = last, l.dx * d.dx + l.dy * d.dy < 0 { turns += 1 }; last = d }
        }
        let path = max(steps.reduce(0, +), 1), leaps = steps.map { $0 / path }
        let moving = trace.filter { $0.0 > 0.75 && $0.0 < 2.9 }
        let firstMove = moving.first { $0.1 != home.minX || $0.2 != home.maxY }?.0 ?? -1
        let settled = moving.last { abs($0.1 - moving.last!.1) > 0.5 || abs($0.2 - moving.last!.2) > 0.5 }?.0 ?? firstMove
        let rest = box.panel.frame, restInk = CGRect(x: marks.minX, y: top - marks.maxY, width: marks.width, height: marks.height)
        let aside = moving.last.map { CGRect(x: $0.1, y: $0.2 - $0.3, width: 360, height: $0.3) } ?? .null
        print(String(format: "MOVE start %.3f settled %.3f took %.3f maxLeap %.2f jumps %d reversals %d spots %d asideClear %@ homeBack %@",
              firstMove, settled, settled - firstMove, leaps.max() ?? 0, leaps.filter { $0 > 1.0/3 }.count, turns, Set(moving.map { $0.1 }).count,
              !aside.intersects(restInk) ? "yes" : "no", rest.minX == home.minX && rest.maxY == home.maxY ? "yes" : "no"))
        for s in trace where s.0 > 0.7 && s.0 < 4.6 { print(String(format: "TRACE %.3f %.1f %.1f %.1f", s.0, s.1, s.2, s.3)) }
        cap?.waitUntilExit()
        print("box move ok"); exit(0)
    }
}
'''


class BoxMoveClip(unittest.TestCase):
    def test_clip(self):
        out = ROOT / 'test-artifacts' / 'box-move'; out.mkdir(parents=True, exist_ok=True)
        mov = out / 'box-move.mov'
        mov.unlink(missing_ok=True)
        os.environ['BOX_MOVE_MOV'] = str(mov)
        try:
            print(run_swift(self, box_move_source((ROOT / 'Atticus.swift').read_text(), SCENARIO), timeout=60), flush=True)
        finally:
            os.environ.pop('BOX_MOVE_MOV', None)
        if mov.exists(): print('MOV box-move', base64.b64encode(mov.read_bytes()).decode(), flush=True)
