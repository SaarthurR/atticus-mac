"""Real panel/WebKit automatic fold lifecycle, isolated in the VM."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.test_minibox import harness, SOURCE, ROOT

DRIVER = r'''
box.ready = { DispatchQueue.global().async {
    var out: [String: Any] = [:]
    func js(_ s: String) { _ = eval(s + "; 1") }
    func state() -> [String: Any] { ["panel": panelH(), "card": card(), "folded": eval("document.body.classList.contains('folded')") as? Bool ?? false, "status": eval("document.getElementById('status').textContent") as? String ?? ""] }
    js("ui.autoMinimize(true); ui.visible(true)"); wait(0.6)
    for gap in [0.0, 0.05, 0.35] {
        js("ui.reset(); ui.listen(); ui.words('First question'); ui.think()"); wait(0.5)
        js("ui.line('… First answer arrives and'); ui.line('✓ First answer.'); ui.finished()"); wait(gap)
        js("ui.listen(); ui.words('Second question'); ui.think()"); wait(0.5)
        out["working-\(gap)"] = state()
        js("ui.line('… Second answer arrives and'); ui.line('✓ Second answer.'); ui.finished()"); wait(0.7)
        out["answer-\(gap)"] = state()
    }
    js("ui.listen(); ui.words('First streaming question'); ui.think(); ui.line('… First answer is still arriving and')"); wait(0.1)
    js("ui.listen(); ui.words('Interrupt with a second question'); ui.think()"); wait(0.5)
    js("ui.line('✓ Second answer after interruption.'); ui.finished()"); wait(0.7)
    out["interrupted-stream"] = state()
    js("ui.listen(); ui.words('Draw'); ui.think(); ui.drawing(true); ui.line('✓ On screen.'); ui.finished()"); wait(0.5)
    js("ui.listen(); ui.words('Explain that'); ui.think()"); wait(0.5)
    js("ui.line('… An explanation arrives and'); ui.line('✓ An explanation.'); ui.finished()"); wait(0.7)
    out["retained-drawing"] = state()
    js("ui.listen(); ui.words('Draw again'); ui.think(); ui.drawing(true); ui.line('✓ On screen.'); ui.finished()"); wait(0.5)
    js("ui.upgradeStarted('retained'); ui.line('✓ A stronger text explanation.'); ui.finished()"); wait(0.7)
    out["retained-drawing-retry"] = state()
    js("ui.drawing(false)")
    js("ui.upgrade('retry'); ui.upgradeStarted('retry'); ui.line('… Stronger answer arrives and'); ui.line('✓ Stronger answer.'); ui.finished()"); wait(0.7)
    out["retry"] = state()
    js("ui.listen(); ui.words('Motion sample'); ui.line('✓ ' + 'A visible answer with several words. '.repeat(8)); ui.finished()"); wait(1.6)   // every word in, so it is an earlier turn at rest
    // Recorded where the motion happens (a main-thread timer for the panel, animation frames for the page), never by
    // round trips from this thread: on a loaded guest one round trip can outlast the whole 0.2 s move.
    // Frames come from a second fold and unfold: drawing a frame holds the main thread, which would stall the move being measured.
    final class Rec { var rows: [[Double]] = [] }
    for (shoot, phase) in [(false, "fold"), (false, "unfold"), (true, "fold"), (true, "unfold")] {
        let rec = Rec(), began = Date()
        let timer: Timer = main {
            let t = Timer(timeInterval: 0.008, repeats: true) { _ in rec.rows.append([Date().timeIntervalSince(began), Double(box.panel.frame.height)]) }
            RunLoop.main.add(t, forMode: .common); return t
        }
        js("window.rec = []; { const c = document.getElementById('card'), t0 = performance.now(); const f = () => { rec.push([(performance.now() - t0) / 1000, parseFloat(getComputedStyle(c).paddingTop)]); if (performance.now() - t0 < 700) requestAnimationFrame(f) }; f() }; " +
           (phase == "fold" ? "ui.listen(); ui.words('Motion sample'); ui.think()" : "ui.line('✓ ' + 'A visible answer with several words. '.repeat(8)); ui.finished()"))
        if shoot && phase == "unfold" {   // turns long done: their words fade in once, not again on every unfold
            out["replayed"] = eval("[...document.querySelectorAll('#thread .turn:nth-last-child(n+3), #thread .turn:nth-last-child(n+3) *')].some(e => e.getAnimations().some(a => a.playState === 'running' && isFinite(a.effect.getComputedTiming().iterations)))") as? Bool ?? true        }
        for (i, at) in [(0, 0.0), (2, 0.05), (5, 0.125), (11, 0.275)] where shoot {
            wait(max(0, at - Date().timeIntervalSince(began)))
            let png: Data? = main {
                let view = box.panel.contentView!, rect = box.panel.contentView!.bounds
                guard let rep = view.bitmapImageRepForCachingDisplay(in: rect) else { return nil }
                view.cacheDisplay(in: rect, to: rep)
                return rep.representation(using: .png, properties: [:])
            }
            if let png { print("FOLD_FRAME \(phase)-\(i) " + png.base64EncodedString()) }
        }
        wait(0.8)
        let panel: [[Double]] = main { timer.invalidate(); return rec.rows }
        if !shoot { out[phase] = ["panel": panel, "page": eval("rec") as? [[Double]] ?? [], "end": state()] }
    }
    print(String(data: try! JSONSerialization.data(withJSONObject: out), encoding: .utf8)!); exit(0)
} }
box.web.loadHTMLString(try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8), baseURL: nil)
DispatchQueue.main.asyncAfter(deadline: .now() + 45) { print("timeout"); exit(1) }
NSApplication.shared.run()
'''


TINY = r'''
box.ready = { DispatchQueue.global().async {
    var out: [String: Any] = [:]
    func js(_ s: String) { _ = eval(s + "; 1") }
    func state() -> [String: Any] { ["w": main { Double(box.panel.frame.width) }, "h": panelH(), "card": card(), "folded": eval("document.body.classList.contains('folded')") as? Bool ?? false] }
    js("ui.autoMinimize(true); ui.visible(true); ui.tiny(true)"); wait(0.6)
    js("ui.listen(); ui.words('First question'); ui.think(); ui.line('✓ First answer.'); ui.finished()"); wait(0.7)
    js("ui.listen(); ui.words('Second question'); ui.think()"); wait(0.7)
    out["tiny"] = state()
    js("ui.tiny(false)"); wait(0.7); out["off"] = state()
    js("ui.tiny(true)"); wait(0.7); out["on"] = state()
    js("ui.line('✓ Second answer.'); ui.finished()"); wait(0.8); out["open"] = state()
    print(String(data: try! JSONSerialization.data(withJSONObject: out), encoding: .utf8)!); exit(0)
} }
box.web.loadHTMLString(try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8), baseURL: nil)
DispatchQueue.main.asyncAfter(deadline: .now() + 45) { print("timeout"); exit(1) }
NSApplication.shared.run()
'''


@unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'real panel: VM only')
class FoldLifecycleTests(unittest.TestCase):
    def test_tiny_switch_reshapes_a_minimized_box_now(self):
        # Nov 21, 2026: turning Tiny off while minimized left a 36 px window with the orb low in it until the next ask
        got = self.render(driver=TINY)
        self.assertEqual((got['tiny']['w'], got['tiny']['h'], got['tiny']['folded']), (36, 36, True), got['tiny'])
        self.assertEqual(got['off']['w'], 400, got['off']); self.assertTrue(got['off']['folded'])
        self.assertAlmostEqual(got['off']['h'], got['off']['card'], delta=1, msg=got['off'])
        self.assertEqual((got['on']['w'], got['on']['h'], got['on']['folded']), (36, 36, True), got['on'])
        self.assertEqual(got['open']['w'], 400, got['open']); self.assertFalse(got['open']['folded'])
        self.assertAlmostEqual(got['open']['h'], got['open']['card'], delta=1, msg=got['open'])

    def render(self, reduced=False, driver=DRIVER):
        with tempfile.TemporaryDirectory() as tmp:
            page, src, binary = [Path(tmp) / name for name in ('ui.html', 'fold.swift', 'fold')]
            html = (ROOT / 'ui/ui.html').read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text())
            native = harness(SOURCE).split('box.ready = {')[0]
            if reduced:
                html = html.replace("matchMedia('(prefers-reduced-motion: reduce)')", "({matches:true,addEventListener(){}})")
                native = native.replace('NSWorkspace.shared.accessibilityDisplayShouldReduceMotion', 'true')
            page.write_text(html)
            src.write_text(native + driver)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(page), '{}', 'dark'], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        for line in run.stdout.splitlines():
            if not reduced and line.startswith('FOLD_FRAME '):
                print(line, flush=True)
        got = json.loads(run.stdout.strip().splitlines()[-1])
        if driver is TINY: return got
        print('FOLD_STATES', json.dumps(got), flush=True)
        for name, state in got.items():
            if name in ('fold', 'unfold', 'replayed'):
                continue
            self.assertEqual(state['folded'], name.startswith('working'), name)
            self.assertAlmostEqual(state['panel'], state['card'], delta=1, msg=name)
        return got

    @staticmethod
    def between(rows):
        """Samples strictly between the first and last value: the frames of a move, empty for a jump."""
        return [r for r in rows if r[1] not in (rows[0][1], rows[-1][1])] if rows else []

    def test_two_native_answers_and_motion(self):
        got = self.render()
        for phase in ('fold', 'unfold'):
            for part, what in (('panel', 'resize'), ('page', 'header padding')):
                moving = self.between(got[phase][part])
                self.assertGreaterEqual(len(moving), 3, f'{phase}: {what} jumped without intermediate frames')
                self.assertGreaterEqual(moving[-1][0] - moving[0][0], 0.08, f'{phase}: {what} moved in one blink, not over the shared timing')
        self.assertTrue(got['fold']['end']['folded'])
        self.assertFalse(got['unfold']['end']['folded'])
        self.assertFalse(got['replayed'], 'unfold replayed the entrances of earlier turns')

    def test_reduce_motion_changes_the_frame_without_a_resize_animation(self):
        got = self.render(reduced=True)
        for phase in ('fold', 'unfold'):
            self.assertEqual(self.between(got[phase]['panel']), [], phase)
            self.assertEqual(self.between(got[phase]['page']), [], phase)
        self.assertTrue(got['fold']['end']['folded'])
        self.assertFalse(got['unfold']['end']['folded'])
