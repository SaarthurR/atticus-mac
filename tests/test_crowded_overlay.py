"""Pure placement geometry; no application, display, preferences, or windows."""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import tests
from tests import run_swift
from tests.test_drawing_math_page import MATH_STUB


class CrowdedOverlayTests(unittest.TestCase):
    def test_dense_placement(self):
        source = (Path(__file__).resolve().parents[1] / 'Atticus.swift').read_text()
        helpers = source[source.index('    // Search obstacle edges'):source.index('    // The box\'s spot')]
        harness = '''import Cocoa
struct DrawingCalloutView { static let notch: CGFloat = 7 }
struct ScreenDrawing {
static let gap: CGFloat = 6
''' + helpers + '''}
let area = CGRect(x:-1000,y:0,width:1000,height:800)
let marks = CGRect(x:-600,y:250,width:200,height:200)
let occupied = [CGRect(x:-1000,y:0,width:400,height:800), CGRect(x:-400,y:0,width:400,height:800)]
let result = ScreenDrawing.calloutFrame(CGSize(width:240,height:120),marks:marks,avoid:occupied,in:area).card
precondition(result.isNull || !([marks]+occupied).contains { $0.intersects(result) }, "Crowded callout covered occupied content")
let label = ScreenDrawing.labelBox(CGSize(width:180,height:50),at:CGPoint(x:-500,y:300),keepOff:occupied+[marks],in:area)
precondition(label.isNull || !(occupied+[marks]).contains { $0.intersects(label) }, "Crowded label covered occupied content")
let free = CGRect(x:-1000,y:0,width:1000,height:800)
let band = CGRect(x:-1000,y:160,width:1000,height:640)
let paged = ScreenDrawing.calloutFrame(CGSize(width:240,height:320),marks:CGRect(x:-990,y:200,width:20,height:20),avoid:[band],in:free).card
precondition(!paged.isNull && paged.height >= 120 && paged.height < 320 && !paged.intersects(band), "Text did not use a smaller clear page")
precondition(ScreenDrawing.labelBox(CGSize(width:180,height:50),at:CGPoint(x:-500,y:300),keepOff:[area],in:area).isNull, "Fully occupied screen got a label")
let boundary = CGRect(x:-600,y:250,width:200,height:550)
let open = ScreenDrawing.labelBox(CGSize(width:180,height:50),at:CGPoint(x:-500,y:300),keepOff:occupied+[boundary],in:area)
precondition(!open.isNull && area.contains(open) && !(occupied+[boundary]).contains { $0.intersects(open) }, "Remote clear label spot was missed")
print("crowded geometry passed")
'''
        # Only this extracted arithmetic harness bypasses the host UI guard.
        with patch.object(subprocess.Popen, '__init__', tests._popen_init):
            self.assertIn('crowded geometry passed', run_swift(self, harness))

    def test_render_labels_avoid_later_marks(self):
        source = (Path(__file__).resolve().parents[1] / 'Atticus.swift').read_text()
        model = source[source.index('struct DrawingShape:'):source.index('struct DrawingStep:')]
        view = source[source.index('final class DrawingView:'):source.index('// One step')]
        helpers = source[source.index('    // Control-point bounds'):source.index("    // The box's spot")]
        harness = r'''import Cocoa
''' + MATH_STUB + model + r'''
struct ScreenDrawing {
struct BoardLine { let text: NSAttributedString, rect: CGRect, step: Int, shape: Int; var image: NSImage? = nil }
static let colors: [String:NSColor] = ["red":.systemRed]
''' + helpers + "}\nstruct DrawingCalloutView { static let notch: CGFloat = 7 }\n" + view + r'''
let view = DrawingView(frame:CGRect(x:0,y:0,width:1000,height:800))
let shapes = [DrawingShape(kind:"label",at:[100,100],text:"Caption"),
              DrawingShape(kind:"pointer",at:[130,80]),
              DrawingShape(kind:"path",points:[[200,100],[250,0],[350,200],[400,100]],fill:true,curve:true),
              DrawingShape(kind:"arrow",points:[[600,50],[600,500]])]
view.render(shapes,animate:false,previous:nil)
let labels = view.hits.filter { $0.shape == 0 }
precondition(labels.count == 1, "A clear label was dropped")
for label in labels {
    for mark in view.hits where mark.shape != 0 {
        precondition(!label.area.boundingBoxOfPath.intersects(mark.area.boundingBoxOfPath), "Label covered a later mark")
    }
}
let future = ScreenDrawing.markBounds([DrawingShape(kind:"arrow",points:[[80,20],[80,700]]),
                                       DrawingShape(kind:"path",points:[[90,30],[160,0],[180,300],[300,200]],fill:true,curve:true)])
let source = CGRect(x:0,y:0,width:400,height:250)
view.render([DrawingShape(kind:"label",at:[70,50],text:"Earlier caption")],animate:false,previous:nil,occupied:future+[source])
let label = view.hits.first!.area.boundingBoxOfPath
precondition(!(future+[source]).contains { $0.intersects(label) }, "Earlier label covered new geometry or source")
let leader = view.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.first { $0.lineWidth == 1.5 }!
precondition(leader.path!.boundingBoxOfPath.contains(CGPoint(x:70.5,y:50.5)) || leader.path!.boundingBoxOfPath.insetBy(dx:-10,dy:-10).contains(CGPoint(x:70,y:50)), "Displaced label lost its anchor")
print("render placement passed")
'''
        with patch.object(subprocess.Popen, '__init__', tests._popen_init):
            self.assertIn('render placement passed', run_swift(self, harness))

    def test_page_navigation_before_step_navigation(self):
        source = (Path(__file__).resolve().parents[1] / 'Atticus.swift').read_text()
        methods = source[source.index('    func advance() {'):source.index('    func clicked(_ point:')]
        harness = "import Foundation\n" + r'''
struct Request { var steps = [0,1]; let teaching = true }
final class Guide {
var request: Request? = Request(), index = 0, textPage = 0, textPageCount = 3, manual = false
var cleared = false
func clear() { cleared = true }
func showStep(forward: Bool = true) {}
''' + methods + r''' }
let guide = Guide()
guide.next(); precondition(guide.textPage == 1 && guide.index == 0 && guide.manual)
guide.back(); precondition(guide.textPage == 0 && guide.index == 0)
guide.advance(); guide.advance(); precondition(guide.textPage == 2 && guide.index == 0)
guide.next(); precondition(guide.textPage == 0 && guide.index == 1 && !guide.cleared)
guide.next(); guide.next(); guide.next(); precondition(guide.cleared)
print("page navigation passed")
'''
        with patch.object(subprocess.Popen, '__init__', tests._popen_init):
            self.assertIn('page navigation passed', run_swift(self, harness))

    def test_text_pages_preserve_words_and_fit(self):
        source = (Path(__file__).resolve().parents[1] / 'Atticus.swift').read_text()
        body = source[source.index('    static func body(_ text:'):source.index('    static func size(_ text:')]
        pages = source[source.index('    static func pages(_ text:'):source.index('    static func bubble(_ card:')]
        harness = "import Cocoa\n" + MATH_STUB + "struct Layout { static let font = NSFont.systemFont(ofSize:14,weight:.medium)\n" + body + pages + r''' }
let words = (0..<150).map { "token" + String($0) }
let text = words.joined(separator:" ")
let pages = Layout.pages(text,width:208,height:60)
precondition(pages.joined() == text, "Paging changed spacing")
let unbroken = String(repeating:"x",count:500) + "\nEquation = 4\nNext line"
let wrapped = Layout.pages(unbroken,width:208,height:60)
precondition(wrapped.joined() == unbroken && wrapped.allSatisfy { Layout.body($0,width:208).frame.height <= 60 }, "Long token or line breaks failed")
precondition(pages.count > 1)
precondition(pages.flatMap { $0.split(separator:" ").map(String.init) } == words, "Paging dropped or reordered text")
precondition(pages.allSatisfy { Layout.body($0,width:208).frame.height <= 60 }, "A text page exceeded its viewport")
precondition(Layout.pages("",width:208,height:60) == [""])
precondition(Layout.pages("$x^2$",width:208,height:1) == ["$x^2$"], "Math must scroll whole instead of splitting TeX")
print("text pages passed")
'''
        with patch.object(subprocess.Popen, '__init__', tests._popen_init):
            self.assertIn('text pages passed', run_swift(self, harness))
