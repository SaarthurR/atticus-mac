"""Design shots of screen drawings (a graph beside a worked problem, a labeled diagram), VM only (opt-in, not discovered).

run.sh <repo> tests.shoot_drawing  → PNGs printed as base64 lines ("DRAWING_PNG <name> <data>").
"""
import unittest
from tests.test_drawing_math_page import MATH_STUB
from tests.test_screen_draw import ROOT

SCENE = r'''
NSApplication.shared.setActivationPolicy(.prohibited)
func s(_ kind: String, _ data: [String:Any]) -> DrawingShape {
    try! JSONDecoder().decode(DrawingShape.self,from:JSONSerialization.data(withJSONObject:data.merging(["kind":kind]) { a, _ in a }))
}
let page = CGRect(x:0,y:0,width:1280,height:800)
// A homework page: rows of dark "text" on white, the right half left blank.
func paint(_ context: CGContext) {
    context.setFillColor(NSColor.white.cgColor); context.fill(page)
    context.setFillColor(NSColor(calibratedWhite:0.25,alpha:1).cgColor)
    for row in 0..<16 { context.fill(CGRect(x:60,y:60+Double(row)*42,width:row % 3 == 2 ? 300 : 520,height:12)) }
}
let parabola = (0...12).map { i -> [Double] in let x = Double(i)/2 - 3; return [960 + x*60, 400 - (x*x - 1)*30] }
let scenes: [(String,[DrawingShape],[DrawingStep])] = [
    ("graph", [s("line",["points":[[780,400],[1180,400]],"color":"white"]), s("line",["points":[[960,110],[960,480]],"color":"white"]),
               s("label",["at":[1180,400],"text":"x","color":"white"]), s("label",["at":[960,110],"text":"y","color":"white"]),
               s("path",["points":parabola,"smooth":true,"color":"blue"]), s("label",["at":parabola.last!,"text":"y = x² − 1","color":"blue"]),
               s("pointer",["at":[960,430],"color":"red"]), s("label",["at":[960,430],"text":"vertex","color":"red"])],
              [DrawingStep(id:nil,say:"Set y to zero.",target:nil,shapes:[s("text",["at":[640,560],"text":"x² − 1 = 0"]),s("text",["text":"x = ±1"])],wait:nil,hit:nil,timeout:nil)]),
    ("diagram", [s("path",["points":[[700,620],[1100,620],[700,320],[700,620]],"color":"white"]),
                 s("rect",["rect":[700,590,30,30],"color":"white"]),
                 s("circle",["rect":[860,430,80,80],"color":"green"]), s("label",["at":[940,470],"text":"hypotenuse c","color":"green"]),
                 s("arrow",["points":[[1180,250],[1110,600]],"color":"yellow"]), s("label",["at":[1180,250],"text":"b = 4","color":"yellow"]),
                 s("rect",["rect":[56,138,528,22],"fill":true,"color":"yellow"]), s("label",["at":[584,149],"text":"given","color":"yellow"]),
                 s("label",["at":[680,470],"text":"a = 3","color":"blue"])], []),
]
for (name, shapes, steps) in scenes {
    let view = DrawingView(frame:page)
    view.render(shapes,animate:false,previous:nil)
    if let board = ScreenDrawing.board(steps,near:CGRect(x:640,y:540,width:1,height:1)) { view.renderBoard(board.frame,board.lines,current:0,animate:false) }
    let image = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:2560,pixelsHigh:1600,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    let context = NSGraphicsContext(bitmapImageRep:image)!.cgContext
    context.scaleBy(x:2,y:2); context.translateBy(x:0,y:800); context.scaleBy(x:1,y:-1)
    paint(context); view.layer!.render(in:context)
    print("DRAWING_PNG \(name) \(image.representation(using:.png,properties:[:])!.base64EncodedString())")
}
// Streamed diagrams on a blank page, shown at their last step like showStep: earlier steps dimmed, the step card off every mark.
// Inline tags become what parse_draw sends: a box or circle names itself at its right edge, an arrow at its tail.
func box(_ r: [Double], _ name: String, _ k: Double, circle: Bool = false) -> [DrawingShape] {
    [s(circle ? "circle" : "rect",["rect":r.map { $0*k },"color":"blue"]), s("label",["at":[(r[0]+r[2])*k,(r[1]+r[3]/2)*k],"text":name,"color":"blue"])]
}
func flow(_ p: [[Double]], _ name: String, _ k: Double) -> [DrawingShape] {
    let q = p.map { $0.map { $0*k } }
    return (q.count > 2 ? [s("path",["points":Array(q.dropLast()),"color":"blue"])] : []) + [s("arrow",["points":Array(q.suffix(2)),"color":"blue"]), s("label",["at":q[0],"text":name,"color":"blue"])]
}
let guides: [(String,CGSize,[[DrawingShape]])] = [
    ("heatpump-live", CGSize(width:1470,height:956), {   // the Nov 18 21:23 answer's own geometry (1280x832 picture, 1.148 pt per pixel)
        let k = 1470.0/1280
        return [box([100,200,260,220],"Outdoor coil",k), flow([[230,420],[230,610]],"gas",k), box([580,580,120,120],"Compressor",k,circle:true),
                flow([[710,640],[1050,640]],"hot gas",k), box([920,200,260,220],"Indoor coil",k), flow([[1050,200],[1050,140]],"liquid",k),
                box([580,100,120,60],"Expansion valve",k), flow([[580,130],[240,130],[230,190]],"cold liquid",k)]
    }()),
    ("heatpump-loop", CGSize(width:1280,height:800), {   // an earlier answer to the same ask, at another size
        let k = 1280.0/1280
        return [box([150,250,250,150],"Outdoor coil",k), flow([[405,300],[595,205]],"gas",k), box([595,155,90,90],"Compressor",k,circle:true),
                flow([[690,205],[875,300]],"hot gas",k), box([880,250,250,150],"Indoor coil",k), flow([[1005,405],[1005,600],[640,600]],"liquid",k),
                box([608,568,64,64],"Valve",k,circle:true), flow([[605,600],[275,600],[275,405]],"cold liquid",k)]
    }()),
    ("bill-law", CGSize(width:1920,height:1080), {
        let k = 1.5
        return [box([80,160,220,110],"House",k), flow([[300,215],[480,215]],"passes",k), box([480,160,220,110],"Senate",k),
                flow([[590,270],[590,420]],"both agree",k), box([530,420,120,120],"President",k,circle:true),
                flow([[650,480],[860,480]],"signs",k), box([860,425,220,110],"Law",k), flow([[590,540],[590,640],[190,640],[190,270]],"veto override",k)]
    }()),
]
for (name, size, steps) in guides {
    let frame = CGRect(origin:.zero,size:size), view = DrawingView(frame:frame), parts = steps.flatMap { $0 }
    let obstacles = ScreenDrawing.markBounds(steps.flatMap { $0 })
    let earlier = steps.dropLast().enumerated().map { view.render($0.element,animate:false,previous:nil,append:true,parts:parts,occupied:obstacles,dim:true,step:$0.offset) }
    let marks = view.render(steps.last!,animate:false,previous:nil,append:true,parts:parts,occupied:obstacles,step:steps.count-1)
    let card = ScreenDrawing.calloutFrame(DrawingCalloutView.size("The cold liquid returns to the start and the loop begins again.",total:steps.count),
                                          marks:marks,avoid:earlier+view.hitBounds,in:frame.insetBy(dx:12,dy:12)).card
    precondition(!card.isNull && !(earlier+view.hitBounds+[marks]).contains { $0.intersects(card) },"\(name): the step card covers a mark")
    precondition(view.layer!.sublayers!.compactMap { $0 as? CATextLayer }.allSatisfy { $0.opacity == 1 },"\(name): a dimmed name is not readable")
    let image = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:Int(size.width)*2,pixelsHigh:Int(size.height)*2,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    let context = NSGraphicsContext(bitmapImageRep:image)!.cgContext
    context.scaleBy(x:2,y:2); context.translateBy(x:0,y:size.height); context.scaleBy(x:1,y:-1)
    context.setFillColor(NSColor.white.cgColor); context.fill(frame); view.layer!.render(in:context)
    context.setFillColor(NSColor(calibratedWhite:0.12,alpha:0.96).cgColor); context.addPath(CGPath(roundedRect:card,cornerWidth:12,cornerHeight:12,transform:nil)); context.fillPath()
    print("DRAWING_PNG \(name) \(image.representation(using:.png,properties:[:])!.base64EncodedString())")
}
print("drawing shots ok")
'''


class DrawingShots(unittest.TestCase):
    def test_graph_and_diagram(self):
        from tests import run_swift, swift_motion
        source = (ROOT/'Atticus.swift').read_text()
        drawing = MATH_STUB + swift_motion(source) + source[source.index('// Screen drawings use Quartz'):source.index('// The box can take typing')]
        out = run_swift(self, 'import Cocoa\nfunc applySharing(_ window: NSWindow) {}\n' + drawing + SCENE, timeout=30)
        self.assertIn('drawing shots ok', out)
        print(out, flush=True)


if __name__ == '__main__':
    unittest.main()
