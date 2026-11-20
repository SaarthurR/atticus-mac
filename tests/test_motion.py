"""The shared native motion on real windows (VM): fades that a reopen wins, and box heights that ease without lagging."""
from pathlib import Path
import unittest

from tests import run_swift, swift_motion

SOURCE = (Path(__file__).resolve().parents[1] / 'Atticus.swift').read_text()


class MotionTests(unittest.TestCase):
    def test_fade_out_is_known_and_any_reopen_wins(self):
        # Nov 15: mid-fade alphaValue is the value on screen, so "alpha 0 = fading out" never held; the shelf's tick
        # saw no fade, let it finish, and the shelf vanished before it faded back in
        out = run_swift(self, 'import Cocoa\n' + swift_motion(SOURCE) + r'''
let app = NSApplication.shared; app.setActivationPolicy(.accessory)
func win() -> NSWindow { let w = NSWindow(contentRect: NSRect(x:100,y:100,width:120,height:100), styleMask:[.borderless], backing:.buffered, defer:false); w.isReleasedWhenClosed = false; w.orderFrontRegardless(); return w }
func after(_ s: Double, _ f: @escaping () -> Void) { DispatchQueue.main.asyncAfter(deadline: .now() + s, execute: f) }
let gone = win(); Motion.fade(gone, in: false)
precondition(Motion.leaving(gone), "a fade out is not known at once")
let back = win(); Motion.fade(back, in: false)
after(0.08) { precondition(Motion.leaving(back) && back.alphaValue > 0, "mid fade"); Motion.fade(back, in: true) }
let direct = win(); Motion.fade(direct, in: false); after(0.08) { direct.alphaValue = 1; direct.orderFrontRegardless() }
let again = win(); Motion.fade(again, in: false); after(0.05) { Motion.fade(again, in: true) }; after(0.1) { Motion.fade(again, in: false) }
let ticked = win(); var fades = 0
for i in 0..<6 { after(Double(i) * 0.05) { if ticked.isVisible && !Motion.leaving(ticked) { fades += 1; Motion.fade(ticked, in: false) } } }
after(0.8) {
    precondition(!gone.isVisible && gone.alphaValue == 1 && !Motion.leaving(gone), "a faded window stays out, opaque for its next show")
    precondition(back.isVisible && back.alphaValue == 1 && !Motion.leaving(back), "a reopen mid fade-out was lost")
    precondition(direct.isVisible && direct.alphaValue == 1, "alpha set back mid fade-out was ordered out")
    precondition(!again.isVisible && !Motion.leaving(again), "a second fade out after a reopen left the window up")
    precondition(fades == 1 && !ticked.isVisible, "a tick faded the same window out again")
    print("motion fades ok"); exit(0)
}
app.run()
''', timeout=20)
        self.assertIn('motion fades ok', out)

    def test_box_height_eases_but_follows_the_page_frame_by_frame_and_a_drag_wins(self):
        # Nov 15: a 0.12 s ease restarted on every frame of the page's own follow() never moved the box until the frames
        # stopped, and an ease in flight took the frame back from a drag
        app = SOURCE[SOURCE.index('final class App: NSObject, WKScriptMessageHandler {'):]
        size = app[app.index('        let size = ((m.body as? [NSNumber])'):app.index('        if drawing.active && !stuck && !dragging { avoidDrawing() }   // grew onto')]
        settle = app[app.index('    var easing = NSRect.zero'):app.index('    var followTimer: Timer?')]
        if 'accessibilityDisplayShouldReduceMotion' not in size: self.fail('the box height ignores Reduce Motion')
        out = run_swift(self, 'import Cocoa\n' + swift_motion(SOURCE) + r'''
enum Prefs { static func str(_ k: String) -> String { "top-left" } }
struct Message { let body: Any }
final class Box {
    let panel = NSPanel(contentRect: NSRect(x:100,y:600,width:340,height:100), styleMask:[.borderless,.nonactivatingPanel], backing:.buffered, defer:false)
    var fromTop = false, pillOn = false, dragging = false
    func frame(_ f: NSRect, on: NSScreen? = nil, animate: Bool = false) { (animate ? panel.animator() : panel).setFrame(f, display: true) }
''' + settle + '''
    func post(_ m: Message) {
''' + size + r'''    }
}
let app = NSApplication.shared; app.setActivationPolicy(.accessory)
if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion { print("reduce motion on: frames change at once"); exit(0) }
func after(_ s: Double, _ f: @escaping () -> Void) { DispatchQueue.main.asyncAfter(deadline: .now() + s, execute: f) }
let box = Box(); box.panel.orderFrontRegardless(); let top = box.panel.frame.maxY
box.post(Message(body: NSNumber(value: 160)))
precondition(box.panel.frame.height < 160, "a new line's height did not ease")
after(0.3) {
    precondition(box.panel.frame.height == 160 && box.panel.frame.maxY == top, "the eased height did not land under a fixed top")
    var late = 0
    for i in 0..<14 { after(Double(i) * 0.016) { let h = 170 + i * 8; box.post(Message(body: NSNumber(value: h)))
        if i > 0 && box.panel.frame.height != CGFloat(h) { late += 1 } } }
    after(0.4) {
        precondition(late == 0, "the box lagged a page that sizes it every frame: \(late) frames")
        box.post(Message(body: NSNumber(value: 400)))
        after(0.03) {
            box.settle(); precondition(box.panel.frame.height == 400, "a drag did not land the ease in flight")
            var moved = box.panel.frame; moved.origin.x += 90; box.frame(moved)
            after(0.25) { precondition(box.panel.frame == moved, "an ease in flight undid the drag"); print("box heights ok"); exit(0) }
        }
    }
}
app.run()
''', timeout=20)
        self.assertIn('box heights ok', out)


if __name__ == '__main__':
    unittest.main()
