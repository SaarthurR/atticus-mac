"""Silent talk releases reuse the box's hover-aware idle timeout."""
from pathlib import Path
import unittest

from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]


class TapTests(unittest.TestCase):
    def test_tap_mic_off_grace_hover_leave_and_real_hold(self):
        source = (ROOT / 'Atticus.swift').read_text()
        shortcut = source.split('    func shortcut(_ pressed: Bool) {', 1)[1]
        release = shortcut[shortcut.index('        if !pressed {'):shortcut.index('        guard !shortcutDown')]
        hide = source[source.index('    func hide(after s: Double)'):source.index('    func defaultKey(')]
        run_swift(self, '''import Foundation
enum Motion { static let fast = 0.12, base = 0.2, slow = 0.28; static func run(_ d: Double, _ f: () -> Void, done: (() -> Void)? = nil) { f(); done?() } }
final class Panel { var alphaValue = 1.0; func animator() -> Panel { self } }
final class Flag { var isRunning = false, holds = false, active = false, hasInput = false }
final class Harness {
    static var keysUp = Date()
    var shortcutDown = true, toggleTalk = false, clickTalk = false, text = "", offerText: String?, began = Date()
    var gen = 0, handsFree = false, busy = false, hovering = false, pinned = false, stuck = false, composing = false, pillOn = false, dictating = false, keysHeld = false
    let engine = Flag(), mini = Flag(), drawing = Flag(), panel = Panel()
    var ringGone: Int?, voice: Flag?, sent = false, visible = true
    func hush() { engine.isRunning = false; busy = false }
    func js(_ name: String, _ value: String) { precondition(name == "msg" && value.isEmpty) }
    func js(_ name: String, _ value: Bool) { preconditionFailure("a tap without held keys opened the typing box") }
    func stop() { sent = true }
    func pill(_ on: Bool) {}
    func gone() { visible = false }
    func shortcut(_ pressed: Bool) {
''' + release + '    }\n' + hide + '''}
func wait(_ seconds: Double) { RunLoop.main.run(until: Date().addingTimeInterval(seconds)) }
let tap = Harness(); tap.engine.isRunning = true; tap.shortcut(false)
precondition(!tap.engine.isRunning && !tap.sent && tap.visible, "tap did not settle idle")
wait(0.4); precondition(tap.visible && tap.panel.alphaValue == 1, "tap closed before pointer could arrive")
tap.hovering = true; wait(2.8)
precondition(tap.visible && tap.panel.alphaValue == 1, "hover did not keep box open")
tap.hovering = false; tap.hide(after: 3); wait(3.2)
precondition(!tap.visible, "leaving did not close idle box")
let untouched = Harness(); untouched.engine.isRunning = true; untouched.shortcut(false); wait(3.2)
precondition(!untouched.visible, "unhovered tap never closed")
let hold = Harness(); hold.began = .distantPast; hold.engine.isRunning = true; hold.shortcut(false)
precondition(hold.sent, "real hold did not finalize immediately")
''', timeout=15)

