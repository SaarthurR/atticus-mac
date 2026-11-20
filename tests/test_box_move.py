"""The box making room for a drawing on a real panel (VM): one calm glide clear of the marks and back, or none with Reduce Motion."""
import os
import re
import subprocess
import unittest
from pathlib import Path

from tests import run_swift
from tests.shoot_box_move import SCENARIO, box_move_source

SOURCE = (Path(__file__).resolve().parents[1] / 'Atticus.swift').read_text()


def move(test, reduced, load=False):
    os.environ.pop('BOX_MOVE_MOV', None)
    if load:
        burn = [subprocess.Popen(['/usr/bin/yes'], stdout=subprocess.DEVNULL) for _ in range(2 * os.cpu_count())]
        test.addCleanup(lambda: [p.kill() for p in burn])
    out = run_swift(test, box_move_source(SOURCE, SCENARIO, reduced=reduced), timeout=30)
    line = re.search(r'^MOVE .*$', out, re.M).group(0)
    words = line.split()[1:]
    return dict(zip(words[::2], words[1::2])), line


class BoxMoveTests(unittest.TestCase):
    def check_glide(self, load):
        m, line = move(self, False, load)
        self.assertEqual(m['asideClear'], 'yes', line)
        self.assertEqual(m['homeBack'], 'yes', line)
        self.assertEqual(m['jumps'], '0', line)
        self.assertEqual(m['reversals'], '0', line)
        self.assertGreater(float(m['took']), .2, line)
        self.assertLess(float(m['took']), .8, line)

    def test_box_glides_clear_of_a_drawing_while_the_answer_grows_and_back(self):
        # Nov 16: the box jumped 592 pt in one frame, then the page's height ease in flight took it back onto the drawing;
        # home was its bottom-left at a shorter height, so it came back past the top and snapped down
        self.check_glide(False)

    def test_a_busy_mac_still_reads_the_glide_as_one_calm_move(self):
        # Nov 16: in the full suite the glide ticked at ~30 Hz and two samples 4 ms apart straddled one step: "maxStep 73.2 jumps 1"
        self.check_glide(True)

    def test_later_streamed_marks_recheck_the_reserved_spot(self):
        scenario = r"""
after(0.2) {
    box.drawing.active = true
    box.drawing.occupied = [CGRect(x: vf.maxX-60,y:top-vf.maxY,width:40,height:40)]
    box.avoidDrawing()
    after(0.7) {
        let f = box.panel.frame
        box.drawing.occupied.append(CGRect(x:f.minX,y:top-f.maxY,width:f.width,height:f.height))
        box.avoidDrawing()
        after(1.0) {
            let rest = box.panel.frame
            let keep = box.drawing.occupied.map { CGRect(x:$0.minX,y:top-$0.maxY,width:$0.width,height:$0.height).insetBy(dx:-32,dy:-32) }
            precondition(!keep.contains { $0.intersects(rest) }, "later streamed marks cover the box")
            print("STREAMED clear"); exit(0)
        }
    }
}
"""
        out = run_swift(self, box_move_source(SOURCE, scenario), timeout=30)
        self.assertIn('STREAMED clear', out)

    def test_folded_row_uses_clear_space_too_short_for_a_full_answer(self):
        scenario = r"""
after(0.2) {
    box.panel.setFrame(NSRect(x:vf.minX+14,y:vf.midY,width:360,height:56),display:true)
    box.drawing.active = true
    box.drawing.occupied = [CGRect(x:vf.minX,y:top-vf.maxY+160,width:vf.width,height:vf.height-160)]
    box.avoidDrawing()
    after(1.0) {
        let m = box.drawing.occupied[0]
        precondition(!CGRect(x:m.minX,y:top-m.maxY,width:m.width,height:m.height).insetBy(dx:-32,dy:-32).intersects(box.panel.frame))
        print("COMPACT clear"); exit(0)
    }
}
"""
        out = run_swift(self, box_move_source(SOURCE, scenario), timeout=30)
        self.assertIn('COMPACT clear', out)

    def test_folding_during_a_glide_still_lands_clear(self):
        scenario = r"""
after(0.2) {
    startDrawing()
    after(0.08) { box.fold(56) }
    after(1.2) {
        let keep = CGRect(x:marks.minX,y:top-marks.maxY,width:marks.width,height:marks.height).insetBy(dx:-32,dy:-32)
        precondition(!keep.intersects(box.panel.frame), "fold interrupted the glide on top of a drawing")
        precondition(abs(box.panel.frame.height-56)<1, "glide restored the unfolded height")
        print("FOLD GLIDE clear"); exit(0)
    }
}
"""
        out = run_swift(self, box_move_source(SOURCE, scenario), timeout=30)
        self.assertIn('FOLD GLIDE clear', out)

    def test_reduce_motion_moves_the_box_without_a_slide(self):
        m, line = move(self, True)
        self.assertEqual(m['asideClear'], 'yes', line)
        self.assertEqual(m['homeBack'], 'yes', line)
        self.assertEqual(m['spots'], '2', line)   # home and the clear spot, nothing between


if __name__ == '__main__':
    unittest.main()
