"""Dense-window alignment measurements and native evidence; VM only."""
import json
import os
from pathlib import Path
import unittest
from tests import run_swift, swift_motion
from tests.test_drawing_math_page import MATH_STUB
from tests.test_guidecard import dismiss_vm_consent

ROOT = Path(__file__).resolve().parents[1]

class DrawAlignmentTests(unittest.TestCase):
    def test_dense_window(self):
        dismiss_vm_consent(self)
        source = (ROOT / 'Atticus.swift').read_text()
        drawing = source[source.index('// Screen drawings use Quartz'):source.index('// The box can take typing')]
        # STUB: math typesetting and capture sharing; coordinate conversion and native mark rendering are real.
        out = run_swift(self, 'import Cocoa\nimport ScreenCaptureKit\n' + MATH_STUB + swift_motion(source) + '\nfunc applySharing(_ w: NSWindow) {}\n' + drawing + r'''
let diagnostics = NSTemporaryDirectory()+"drawalign-"+UUID().uuidString
try! FileManager.default.createDirectory(atPath:diagnostics,withIntermediateDirectories:true)
setenv("ATTICUS_DIR",diagnostics,1)
defer { try? FileManager.default.removeItem(atPath:diagnostics) }
let app = NSApplication.shared
app.setActivationPolicy(.regular)
let screen = NSScreen.screens[0], area = ScreenDrawing.visibleArea(screen)
let window = NSWindow(contentRect:screen.frame,styleMask:.borderless,backing:.buffered,defer:false)
window.isReleasedWhenClosed = false; window.level = .floating
let view = NSView(frame:CGRect(origin:.zero,size:screen.frame.size)); window.contentView = view
let top = screen.frame.maxY
let targets: [(String,CGRect)] = [
 ("projects",CGRect(x:area.minX+20,y:area.minY+160,width:150,height:32)),
 ("worktree",CGRect(x:area.minX+20,y:area.minY+260,width:150,height:54)),
 ("sidebar",CGRect(x:area.minX+4,y:area.minY+4,width:24,height:24)),
 ("search",CGRect(x:area.minX+20,y:area.minY+60,width:150,height:28)),
 ("tasks",CGRect(x:area.minX+20,y:area.minY+105,width:150,height:30)),
 ("tabs",CGRect(x:area.minX+220,y:area.minY+4,width:area.width-240,height:28)),
 ("prompt",CGRect(x:area.minX+220,y:area.maxY-90,width:area.width-240,height:40)),
 ("status",CGRect(x:area.minX+220,y:area.maxY-24,width:area.width-240,height:20))]
for style in ["light","dark"] {
 view.subviews.forEach { $0.removeFromSuperview() }
 window.appearance = NSAppearance(named:style == "dark" ? .darkAqua : .aqua)
 window.backgroundColor = style == "dark" ? NSColor(calibratedWhite:0.12,alpha:1) : .white
 for i in 0..<18 {
  let line = NSTextField(labelWithString:i % 3 == 0 ? "> inspect workspace and run checks" : "  terminal output: processing module \(i+1)  ·  ready")
  line.font = .monospacedSystemFont(ofSize:12,weight:.regular)
  line.frame = CGRect(x:area.minX+230,y:top-area.minY-110-Double(i)*23,width:area.width-250,height:20)
  view.addSubview(line)
 }
 for i in 0..<10 {
  let line = NSTextField(labelWithString:"  project-\(i+1) / worktree")
  line.font = .systemFont(ofSize:11)
  line.frame = CGRect(x:area.minX+20,y:top-area.minY-360-Double(i)*23,width:180,height:20)
  view.addSubview(line)
 }
 for (name,r) in targets {
  let label = NSTextField(labelWithString:name)
  label.frame = CGRect(x:r.minX,y:top-r.maxY,width:r.width,height:r.height)
  label.wantsLayer = true; label.layer!.backgroundColor = NSColor.systemGray.withAlphaComponent(0.25).cgColor
  view.addSubview(label)
 }
 window.makeKeyAndOrderFront(nil); app.activate()
 RunLoop.current.run(until:Date().addingTimeInterval(0.2))
 let info = (CGWindowListCopyWindowInfo(.optionIncludingWindow,CGWindowID(window.windowNumber)) as! [[String:Any]])[0]
 let bounds = CGRect(dictionaryRepresentation:info[kCGWindowBounds as String] as! CFDictionary)!
 let target: [String:Any] = ["pid":ProcessInfo.processInfo.processIdentifier,"windowID":String(window.windowNumber),"windowFrame":[bounds.minX,bounds.minY,bounds.width,bounds.height]]
 let captureDone = DispatchSemaphore(value:0)
 var pixels = [Int]()
 Task {
  defer { captureDone.signal() }
  let all = try! await SCShareableContent.excludingDesktopWindows(false,onScreenWindowsOnly:true)
  let id = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as! CGDirectDisplayID
  let display = all.displays.first { $0.displayID == id }!
  let cfg = SCStreamConfiguration(); cfg.width = 1280; cfg.height = Int(1280*Double(display.height)/Double(display.width))
  let image = try! await SCScreenshotManager.captureImage(contentFilter:SCContentFilter(display:display,excludingWindows:[]),configuration:cfg)
  pixels = [image.width,image.height]
 }
 captureDone.wait()
 precondition(screen.backingScaleFactor != 1 && Double(pixels[0]) != screen.frame.width,"Fixture needs non-1x scale")
 let frame = [0.0,0.0,screen.frame.width,screen.frame.height]
 let raw = targets.map { t -> [String:Any] in
  let r = t.1
  return ["kind":"rect","rect":[r.minX*Double(pixels[0])/frame[2],r.minY*Double(pixels[1])/frame[3],r.width*Double(pixels[0])/frame[2],r.height*Double(pixels[1])/frame[3]],"color":"blue"]
 }
 let input = try! JSONSerialization.data(withJSONObject:["steps":[["screen":1,"say":"fixture","shapes":raw]]])
 let convert = Process(), stdin = Pipe(), stdout = Pipe()
 convert.executableURL = URL(fileURLWithPath:"/opt/homebrew/bin/python3")
 convert.arguments = ["-c","import atticus,json,sys; print(json.dumps(atticus.drawing(json.load(sys.stdin), {'1':{'frame':\(frame),'pixels':\(pixels)}}, trace=True)['steps']))"]
 convert.standardInput = stdin; convert.standardOutput = stdout
 try! convert.run(); stdin.fileHandleForWriting.write(input); try! stdin.fileHandleForWriting.close()
 let converted = stdout.fileHandleForReading.readDataToEndOfFile(); convert.waitUntilExit()
 precondition(convert.terminationStatus == 0)
 let traced = try! JSONDecoder().decode([DrawingStep].self,from:converted)[0].shapes
 print("DRAWALIGN_DISPLAY points=\(screen.frame) backingScale=\(screen.backingScaleFactor) pixels=\(pixels) pixelToPoint=\(frame[2]/Double(pixels[0]))")
 for (i,t) in targets.enumerated() {
  let placed = ScreenDrawing.placed(traced[i],in:area).rect!
  print("DRAWALIGN_ERROR \(t.0) \(hypot(placed[0]-t.1.minX,placed[1]-t.1.minY)) \(placed)")
 }
 let steps: [[String:Any]] = traced.enumerated().map { i, mark in
  ["say":"Locate the \(targets[i].0).", "shapes":[try! JSONSerialization.jsonObject(with:JSONEncoder().encode(mark))]]
 }
 let payload = try! JSONSerialization.data(withJSONObject:["steps":steps,"teaching":true,"target":target,"state":"fixture"])
 let guide = ScreenDrawing(); precondition(guide.receive(payload))
 precondition(!String(describing:guide.summary!).contains("geometry"),"Local diagnostics leaked into model context")
 for i in traced.indices {
  guide.index = i; guide.showStep(forward:false)
  precondition(guide.calloutPanel?.isVisible == true,"Dense guide lost its step card")
  RunLoop.current.run(until:Date().addingTimeInterval(0.2))
  let name = style+"-"+targets[i].0, file = NSTemporaryDirectory()+"drawalign-"+name+".png"
  let p = Process(); p.executableURL = URL(fileURLWithPath:"/usr/sbin/screencapture"); p.arguments = ["-x",file]; try! p.run(); p.waitUntilExit()
  print("DRAWALIGN_PNG \(name) \((try! Data(contentsOf:URL(fileURLWithPath:file))).base64EncodedString())")
 }
 guide.clear()
 let text = DrawingShape(kind:"text",at:[400,200],text:"private screen text",geometry:"{\"raw\":{\"at\":[500,250]}}")
 let textSteps: [[String:Any]] = [["say":"Repeated text","shapes":[text,text].map { try! JSONSerialization.jsonObject(with:JSONEncoder().encode($0)) }]]
 let textPayload = try! JSONSerialization.data(withJSONObject:["steps":textSteps,"teaching":true,"target":target,"state":"fixture"])
 precondition(guide.receive(textPayload) && guide.board != nil,"Repeated text lost its board")
 guide.clear()
}
let logPath = ProcessInfo.processInfo.environment["ATTICUS_DIR"]!+"/draw-geometry.jsonl"
let rows = try! String(contentsOfFile:logPath,encoding:.utf8).split(separator:"\n").map { try! JSONSerialization.jsonObject(with:Data($0.utf8)) as! [String:Any] }
precondition(rows.count >= 16 && rows.allSatisfy { $0["screenRect"] != nil && $0["raw"] != nil && $0["quartz"] != nil },"Incomplete geometry diagnostics")
for row in rows where row["kind"] as? String == "rect" {
 let raw = row["raw"] as! [String:Any], rect = raw["rect"] as! [Double]
 let scale = row["scale"] as! [Double]
 let target = CGRect(x:rect[0]*scale[0],y:rect[1]*scale[1],width:rect[2]*scale[0],height:rect[3]*scale[1])
 let expected = ScreenDrawing.ring(target,circle:false).insetBy(dx:-3,dy:-3).intersection(CGRect(origin:.zero,size:screen.frame.size))
 let actual = row["screenRect"] as! [Double]   // a ring is drawn by hand: each edge wanders up to Hand.reach, never past the gap onto its target
 let drift = zip([actual[0],actual[1],actual[0]+actual[2],actual[1]+actual[3]],[expected.minX,expected.minY,expected.maxX,expected.maxY]).map { abs($0-$1) }
 precondition(drift.allSatisfy { $0 <= ScreenDrawing.Hand.reach } && ScreenDrawing.Hand.reach < ScreenDrawing.gap,"Rendered ink drifted from target: \(drift)")
}
let textRows = rows.filter { $0["kind"] as? String == "text" }
precondition(textRows.count == 4 && textRows.allSatisfy { $0["screenRect"] is [Double] },"Repeated text lost its diagnostic footprints")
for i in stride(from:0,to:textRows.count,by:2) {
 let a = textRows[i]["screenRect"] as! [Double], b = textRows[i+1]["screenRect"] as! [Double]
 precondition(a[1] != b[1],"Repeated text shared one diagnostic footprint")
}
precondition(!String(describing:rows).contains("private screen text"),"Text board leaked into diagnostics")
precondition(!String(describing:rows).contains("Locate the"),"Geometry log retained screen text")
let attributes = try! FileManager.default.attributesOfItem(atPath:logPath)
precondition((attributes[.posixPermissions] as! NSNumber).intValue == 0o600,"Geometry log is not private")
let probe = DrawingView(frame:CGRect(origin:.zero,size:screen.frame.size)); probe.visibleArea = area
let key = "{\"raw\":{\"at\":[400,400],\"text\":\"private screen text\"},\"text\":\"private screen text\"}"
let probes = [DrawingShape(kind:"pointer",at:[500,500],geometry:key),
              DrawingShape(kind:"arrow",points:[[300,300],[400,400]],geometry:key),
              DrawingShape(kind:"label",at:[area.midX,area.midY],text:"private screen text",geometry:key),
              DrawingShape(kind:"text",at:[600,150],text:"private screen text",geometry:key)]
probe.render(probes,animate:false,previous:nil)
probes.last!.logGeometry(ink:CGRect(x:600,y:150,width:150,height:40),step:0,backingScale:screen.backingScaleFactor)
let latest = try! String(contentsOfFile:logPath,encoding:.utf8).split(separator:"\n").suffix(4)
precondition(latest.count == 4 && latest.allSatisfy { !$0.contains("private screen text") },"Diagnostics retained text")
for line in latest {
 let row = try! JSONSerialization.jsonObject(with:Data(line.utf8)) as! [String:Any]
 precondition(row["screenRect"] is [Double],"Missing rendered footprint for \(row["kind"]!)")
}
window.close()
''', timeout=30)
        print(out, flush=True)
        errors = [float(line.split()[2]) for line in out.splitlines() if line.startswith('DRAWALIGN_ERROR ')]
        self.assertEqual(len(errors), 16)
        self.assertTrue(all(error < 1e-9 for error in errors), errors)

    def test_hand_drawn_box_strays_by_its_own_size(self):
        # Nov 19: a 39x24 pt ring bent by the hand's fixed corner and a wide row's long sides bowed past a tenth of its height
        source = (ROOT / 'Atticus.swift').read_text()
        hand = source[source.index('    struct Hand {'):source.index('    static func addDrawn(')]
        out = run_swift(self, 'import CoreGraphics\nimport Foundation\nenum ScreenDrawing {\n' + hand + '}\n' + r'''
for (w,h) in [(39.0,24.0),(300.0,20.0),(200.0,120.0)] {
    var worst: CGFloat = 0
    for seed in 0..<200 {
        let r = CGRect(x:Double(seed*13 % 500),y:Double(seed*7 % 300),width:w,height:h)
        var hand = ScreenDrawing.Hand([CGPoint(x:r.minX+Double(seed),y:r.minY),CGPoint(x:r.maxX,y:r.maxY)])
        for p in hand.box(r).flatMap({ $0 }) {
            let dx = max(r.minX-p.x,p.x-r.maxX,0), dy = max(r.minY-p.y,p.y-r.maxY,0)
            let inside = min(abs(p.x-r.minX),abs(p.x-r.maxX),abs(p.y-r.minY),abs(p.y-r.maxY))
            worst = max(worst,dx > 0 || dy > 0 ? hypot(dx,dy) : inside)
        }
    }
    print("STRAY \(w) \(h) \(worst) \(worst/min(w,h))")
}
''')
        rows = [line.split() for line in out.splitlines() if line.startswith('STRAY ')]
        self.assertEqual(len(rows), 3, out)
        for _, w, h, worst, share in rows:
            self.assertLess(float(share), 0.04, out)   # a small mark reads straight
        self.assertGreater(float(rows[2][3]), 1.0, out)   # a large one still looks drawn

    def test_coordinate_diagnostics(self):
        import atticus
        from unittest.mock import patch
        raw = {'kind':'rect','rect':[-1,20,50,30],'text':'private screen text'}
        shape = {k:v for k,v in raw.items() if k != 'text'}
        mapping = {'2':{'frame':[-1440,-100,1440,900],'pixels':[1280,800]}}
        with patch.dict(os.environ, {'ATTICUS_ASK':'/private/ask-123'}):
            value = atticus.drawing({'steps':[{'screen':2,'say':'private caption','shapes':[atticus._in_picture(shape,[1280,800])]}]},
                                    mapping, trace=True, raw_shapes=[shape])
        mark = value['steps'][0]['shapes'][0]
        trace = json.loads(mark['geometry'])
        self.assertEqual(trace['raw'], {'rect':[-1,20,50,30]})
        self.assertEqual(trace['scale'], [1.125,1.125])
        self.assertEqual(trace['pixels'], [1280,800])
        self.assertEqual(trace['frame'], [-1440,-100,1440,900])
        self.assertEqual(mark['rect'], [-1440, -77.5, 55.125, 33.75])
        self.assertNotIn('private',mark['geometry'])
        self.assertEqual(trace['request'],'ask-123')
        quartz = atticus.drawing({'steps':[{'say':'private caption','shapes':[{'kind':'pointer','at':[-100,50]}]}]}, mapping, trace=True)
        trace = json.loads(quartz['steps'][0]['shapes'][0]['geometry'])
        self.assertEqual(trace['coordinateSpace'], 'quartz')
        self.assertEqual(trace['screens'], mapping)
        self.assertEqual(trace['raw'], {'at':[-100,50]})

    def test_inline_diagnostics_keep_model_points_before_edge_slack(self):
        import atticus
        from unittest.mock import patch
        stream = atticus.InlineDrawing()
        stream.snapshot = {'screens':{'1':{'frame':[0,0,1024,768],'pixels':[1280,960]}}}
        with patch.dict(os.environ, {'ATTICUS_SCREEN':''}):
            shapes = stream.shapes('[DRAW:box -1,20 50,60:private label]')
        trace = json.loads(shapes[0]['geometry'])
        self.assertEqual(trace['raw']['model_points'], [[-1,20],[50,60]])
        self.assertEqual(trace['raw']['rect'], [-1,20,51,40])
        self.assertNotIn('private',shapes[0]['geometry'])
        self.assertEqual(shapes[0]['rect'], [0,16,40,32])

    def test_each_request_logs_the_drawing_words_it_got(self):
        # Nov 19: whether a step asked to wait for its click could not be told from the geometry rows alone
        import atticus, tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root, patch.object(atticus, 'DIR', root), patch.dict(os.environ, {'ATTICUS_ASK': root + '/atticus-ask-x', 'ATTICUS_SCREEN': ''}):
            stream = atticus.InlineDrawing()
            stream.snapshot = {'screens':{'1':{'frame':[0,0,1024,768],'pixels':[1280,960]}}}
            stream.shapes('[DRAW:box 10,20 50,60 click:Menu]'); stream.shapes('[DRAW:box 10,20 50,60 click:Menu]'); stream.shapes('[DRAW:dot 5,5]')
            rows = [json.loads(line) for line in Path(root, 'draw-geometry.jsonl').read_text().splitlines()]
        self.assertEqual([(r['request'], r['tag'], r['wait']) for r in rows],
                         [('atticus-ask-x', '[DRAW:box 10,20 50,60 click:Menu]', True), ('atticus-ask-x', '[DRAW:dot 5,5]', False)])
