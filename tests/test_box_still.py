"""Drawing-session box placement with fake windows, screen and capture state."""
from pathlib import Path
import unittest

from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]


class BoxStillTests(unittest.TestCase):
    def test_step_resize_drag_and_pointer_changes_do_not_relocate_box(self):
        source = (ROOT / 'Atticus.swift').read_text()
        placement = source[source.index('    var boxHome:'):source.index('    func glide(')]
        follow = source[source.index('    func followPointerScreen()'):source.index('    func startFollowingPointerScreen()')]
        resize = source[source.index('    func frame(_ requested:'):source.index('    // Which edges the point')]
        clamp = source[source.index('    static func clamp('):source.index('    // The same frame on another display')]
        search = source[source.index('    static func clearSpot('):source.index('    static func valid(')]
        run_swift(self, '''import Cocoa
struct NSScreen {
    var frame = CGRect(x:0,y:0,width:1600,height:1000)
    var visibleFrame: CGRect { frame }
    static var screens = [NSScreen()]
    static var main: NSScreen? { screens.first }
}
func pointerFollow(_ frame: CGRect) -> CGRect? { frame.offsetBy(dx:50,dy:0) }
struct Prefs { static func num(_ k: String) -> Double { 400 }; static func str(_ k: String) -> String { "top-left" } }
func boxWidth(_ width: Double, _ bounds: CGRect) -> CGFloat { 360 }
enum MeetingFrame {
''' + clamp + '''}
enum ScreenDrawing {
''' + search + '''}
final class Panel {
    var isVisible = true; var frame = CGRect(x:40,y:700,width:360,height:200)
    func animator() -> Panel { self }; func setFrame(_ f: CGRect, display: Bool) { frame = f }; func invalidateShadow() {}
}
final class Drawing {
    var active = true
    var occupied = [CGRect(x:40,y:100,width:360,height:200)]
    var layoutBounds: [CGRect] { occupied }
}
final class Harness {
    let panel = Panel(), drawing = Drawing()
    var dragging = false, hovering = false, stuck = false, pillOn = false, moves = 0
    var compH: CGFloat = 50
    func glide(_ frame: CGRect) { moves += 1; panel.frame = frame }
    func js(_ name: String, _ data: Any) {}
    func hide(after: Double) {}
''' + resize + placement + follow + '''}
let box = Harness(); box.avoidDrawing()
let initial = box.panel.frame, moves = box.moves
box.drawing.occupied = [CGRect(x:initial.minX,y:1000-initial.maxY,width:initial.width,height:initial.height)]
box.avoidDrawing()
precondition(box.panel.frame == initial && box.moves == moves,"step navigation relocated the box")
box.panel.frame.origin.y -= 80; box.panel.frame.size.height += 80
let grown = box.panel.frame
box.avoidDrawing()
precondition(box.panel.frame == grown && box.moves == moves,"composer resize relocated the box")
var tall = grown; tall.origin.y = tall.maxY-1200; tall.size.height = 1200
box.frame(tall)
precondition(box.panel.frame.maxY == grown.maxY && box.panel.frame.minX == grown.minX,"growing the composer moved its top-left anchor")
box.panel.frame = grown
box.followPointerScreen()
precondition(box.panel.frame == grown,"pointer following moved a drawing's box")
box.stuck = true; box.boxHome = nil; box.panel.frame.origin = CGPoint(x:900,y:500)
let dragged = box.panel.frame
box.avoidDrawing(); box.followPointerScreen()
precondition(box.panel.frame == dragged,"a step or pointer move overrode the user's drag")
box.drawing.active = false; box.avoidDrawing()
RunLoop.main.run(until:Date().addingTimeInterval(0.01))
precondition(box.panel.frame == dragged,"closing restored the box over the user's drag")
box.stuck = false; box.drawing.active = true
box.drawing.occupied = [CGRect(x:dragged.minX,y:1000-dragged.maxY,width:dragged.width,height:dragged.height)]
box.avoidDrawing()
precondition(box.panel.frame != dragged,"a new guide did not get a new placement")
print("stable box placement ok")
''')
