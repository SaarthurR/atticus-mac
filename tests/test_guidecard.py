"""Native guide card sizing, display edges and speech lifetime; VM only."""
from pathlib import Path
import json
import os
import unittest
from unittest.mock import patch

from tests import run_swift, scratch_dir, swift_motion
from tests.test_drawing_math_page import HIS_CARD, MATH_STUB
import atticus

ROOT = Path(__file__).resolve().parents[1]


def dismiss_vm_consent(test):
    if os.environ.get('ATTICUS_VM') != '1':
        test.skipTest('native guide captures run only in the VM')
    out = run_swift(test, r'''import Cocoa
func attribute(_ e: AXUIElement, _ key: String) -> CFTypeRef? {
    var value: CFTypeRef?
    return AXUIElementCopyAttributeValue(e,key as CFString,&value) == .success ? value : nil
}
func nodes(_ root: AXUIElement, depth: Int = 0) -> [AXUIElement] {
    guard depth < 12 else { return [] }
    let children = attribute(root,kAXChildrenAttribute) as? [AXUIElement] ?? []
    return [root] + children.prefix(100).flatMap { nodes($0,depth:depth+1) }
}
precondition(AXIsProcessTrusted(),"VM capture helper needs the guest's existing Accessibility access")
var dismissed = 0, remaining = 0
for _ in 0..<5 {
    remaining = 0
    let windows = CGWindowListCopyWindowInfo(.optionOnScreenOnly,kCGNullWindowID) as? [[String:Any]] ?? []
    let owners = Set(windows.compactMap { ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value })
    for pid in owners {
        let root = AXUIElementCreateApplication(pid)
        for window in attribute(root,kAXWindowsAttribute) as? [AXUIElement] ?? [] {
            let elements = nodes(window)
            let text = elements.flatMap { e in [kAXTitleAttribute,kAXValueAttribute,kAXDescriptionAttribute].compactMap { attribute(e,$0) as? String } }.joined(separator:" ")
            guard text.contains("tart-guest-agent") else { continue }
            let buttons = elements.filter { (attribute($0,kAXRoleAttribute) as? String) == kAXButtonRole }
            guard let deny = buttons.first(where: { e in
                [kAXTitleAttribute,kAXDescriptionAttribute].compactMap { attribute(e,$0) as? String }
                    .contains { $0.replacingOccurrences(of:"’",with:"'").lowercased() == "don't allow" }
            }) else { continue }
            remaining += 1
            if AXUIElementPerformAction(deny,kAXPressAction as CFString) == .success { dismissed += 1 }
        }
    }
    if remaining == 0 { break }
    RunLoop.current.run(until:Date().addingTimeInterval(0.2))
}
precondition(remaining == 0,"A Tart consent dialog still covers the VM capture")
print("VM Tart consent dialogs dismissed with native AX Don’t Allow: \(dismissed)")
''', timeout=15)
    print(out, flush=True)


class GuideCardTests(unittest.TestCase):
    def setUp(self):
        dismiss_vm_consent(self)

    def test_filtered_display_marks_keep_their_original_shape_index(self):
        source = (ROOT / 'Atticus.swift').read_text()
        drawing = source[source.index('// Screen drawings use Quartz'):source.index('// The box can take typing')]
        out = run_swift(self, 'import Cocoa\n' + MATH_STUB + swift_motion(source) + '\nfunc applySharing(_ w: NSWindow) {}\n' + drawing + r'''
let view = DrawingView(frame:CGRect(x:0,y:0,width:400,height:400))
view.origin = CGPoint(x:1000,y:0); view.visibleArea = CGRect(x:1000,y:0,width:400,height:400)
let shapes = [DrawingShape(kind:"circle",rect:[50,50,60,60],text:"First"), DrawingShape(kind:"circle",rect:[1050,50,60,60],text:"Second")]
view.render(shapes,animate:false,previous:nil)
guard let area = view.hits.first?.area.boundingBoxOfPath else { fatalError("second display mark missing") }
guard let hit = view.mark(at:CGPoint(x:view.origin.x+area.midX,y:view.origin.y+area.minY+1)) else { fatalError("visible stroke not selectable") }
precondition(hit.shape == 1,"display filtering changed original shape 1 to \(hit.shape)")
print("display mark identity ok")
''')
        self.assertIn('display mark identity ok', out)

    def test_ring_by_the_menu_bar_draws_whole_and_its_target_takes_the_click(self):
        source = (ROOT / 'Atticus.swift').read_text()
        drawing = source[source.index('// Screen drawings use Quartz'):source.index('// The box can take typing')]
        out = run_swift(self, 'import Cocoa\n' + MATH_STUB + swift_motion(source) + '\nfunc applySharing(_ w: NSWindow) {}\n' + drawing + r'''
func strokePoint(_ view: DrawingView, _ target: CGRect) -> CGPoint {   // the drawn ring's ink straight above the target
    let ring = view.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.last { $0.lineWidth == 3 }!.path!.copy(strokingWithWidth:3,lineCap:.round,lineJoin:.round,miterLimit:2)
    let x = target.midX-view.origin.x
    let y = stride(from:target.minY-view.origin.y,to:-40,by:-0.5).first { ring.contains(CGPoint(x:x,y:$0)) }!
    return CGPoint(x:x+view.origin.x,y:y+view.origin.y)
}
// A display with a 30-point menu bar: a target just under it, and one whose ring would pass the display's own top.
let view = DrawingView(frame:CGRect(x:0,y:0,width:1440,height:900)); view.visibleArea = CGRect(x:0,y:30,width:1440,height:870)
for target in [CGRect(x:600,y:30,width:80,height:24),CGRect(x:900,y:14,width:66,height:66)] {
    view.render([DrawingShape(kind:"circle",rect:[target.minX,target.minY,target.width,target.height]),DrawingShape(kind:"label",at:[target.maxX,target.midY],text:"Insert")],animate:false,previous:nil)
    let ink = view.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.first { $0.lineWidth == 3 }!.path!.boundingBoxOfPath
    precondition(ink.minY < 30 && ink.insetBy(dx:-1.5,dy:-1.5).minY >= 0 && ink.contains(target),"A ring by the menu bar was cut or left its target: \(ink)")
    let full = ScreenDrawing.ring(target,circle:true)
    if full.minY > 10 { precondition(abs(ink.minY-full.minY) < 4,"A ring with room was flattened: \(ink) vs \(full)") }
    precondition(view.mark(at:CGPoint(x:target.midX,y:target.midY)) == nil,"A ring took the click meant for its target")
    precondition(view.mark(at:strokePoint(view,target))?.shape == 0,"A ring's stroke takes no click")
    precondition(view.hits.filter { $0.shape == 1 }.allSatisfy { view.visibleArea!.contains($0.area.boundingBoxOfPath) },"A name went under the menu bar")
}
// A guide's click step on the real display: the click inside the ring reaches the app and counts; the stroke still picks.
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let screen = NSScreen.screens[0], area = ScreenDrawing.visibleArea(screen)
let window = NSWindow(contentRect:CGRect(x:screen.visibleFrame.minX+40,y:screen.visibleFrame.minY+40,width:500,height:300),styleMask:.titled,backing:.buffered,defer:false)
window.isReleasedWhenClosed = false; window.ignoresMouseEvents = true; window.makeKeyAndOrderFront(nil); app.activate()
var info: [[String:Any]] = []
let deadline = Date().addingTimeInterval(2)
repeat {
    RunLoop.current.run(until:Date().addingTimeInterval(0.05))
    info = CGWindowListCopyWindowInfo(.optionIncludingWindow,CGWindowID(window.windowNumber)) as? [[String:Any]] ?? []
} while info.isEmpty && Date() < deadline
let bounds = CGRect(dictionaryRepresentation:info[0][kCGWindowBounds as String] as! CFDictionary)!
let target = CGRect(x:area.midX-40,y:area.minY,width:80,height:24)
let rect = [target.minX,target.minY,target.width,target.height]
let payload = try! JSONSerialization.data(withJSONObject:["teaching":true,"state":"fixture",
    "target":["pid":ProcessInfo.processInfo.processIdentifier,"windowID":String(window.windowNumber),"windowFrame":[bounds.minX,bounds.minY,bounds.width,bounds.height]],
    "steps":[["say":"Click it.","wait":true,"hit":rect,"shapes":[["kind":"circle","rect":rect]]],
             ["say":"Then this.","shapes":[["kind":"circle","rect":[bounds.minX+100,bounds.minY+150,60,30]]]]]])
let d = ScreenDrawing()
precondition(d.receive(payload) && d.waiting,"The click step did not show and wait")
let panel = d.panels.first { ($0.contentView as! DrawingView).display.contains(target) }!, guide = panel.contentView as! DrawingView
let ink = guide.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.first { $0.lineWidth == 3 }!.path!.boundingBoxOfPath.offsetBy(dx:guide.origin.x,dy:guide.origin.y)
if area.minY-guide.display.minY >= 20 { precondition(ink.minY < area.minY && ink.contains(target),"The ring stopped at the menu bar: \(ink)") }
func hover(_ p: CGPoint) { CGWarpMouseCursorPosition(p); RunLoop.current.run(until:Date().addingTimeInterval(0.1)); d.hoverMarks() }
let inside = CGPoint(x:target.midX,y:target.midY), stroke = strokePoint(guide,target)
hover(inside); precondition(d.panels.allSatisfy { $0.ignoresMouseEvents },"The ring's panel took the click on its target")
hover(stroke); precondition(!panel.ignoresMouseEvents,"The ring's stroke did not take the click")
hover(inside); d.ready = .distantPast; d.clicked(inside)
precondition(d.index == 1 && !d.waiting,"A click inside the ring did not do the step")
d.back(); d.pick(stroke)
precondition(d.selected.map { $0.step == 0 && $0.shape == 0 } == true,"Picking the ring's stroke did not select it")
d.clear(); window.close()
print("ring by the menu bar: whole, target clickable, stroke picks")
''', timeout=30)
        self.assertIn('ring by the menu bar: whole, target clickable, stroke picks', out)

    def test_real_click_in_a_live_inline_guide_ring_does_the_step(self):
        # The user's app owns a main window and a toolbar window of its own stacked over its top (as a browser does).
        # The guide comes from the model's pixel tags through the real mapping, at his two scales; clicks are real CGEvents.
        frame = json.loads(run_swift(self, 'import Cocoa\nlet b = CGDisplayBounds(CGMainDisplayID())\nprint("[\\(b.minX),\\(b.minY),\\(b.width),\\(b.height)]")'))
        x0, y0 = frame[0] + 120, frame[1] + 120   # the main window's Quartz top-left; its toolbar window covers its top 110 points
        guides = []
        for scale, ring, box in ((1.5, (x0 + 200, y0 + 70), (x0 + 350, y0 + 250)), (frame[2] / 1280, (x0 + 150, y0 + 250), (x0 + 350, y0 + 150))):
            pixels = [round(frame[2] / scale), round(frame[3] / scale)]
            px = lambda x, y: f'{round((x - frame[0]) * pixels[0] / frame[2])},{round((y - frame[1]) * pixels[1] / frame[3])}'
            root = scratch_dir(self)
            (root / 'draw-screens.json').write_text(json.dumps({'screens': {'1': {'frame': frame, 'pixels': pixels}},
                                                                'target': {'pid': 1, 'windowID': '1', 'windowFrame': [x0, y0, 640, 420]}}))
            reply = (f'[DRAW:circle {px(*ring)} 20 yellow click:Button] Click the button. '
                     f'[DRAW:box {px(*box)} {px(box[0] + 150, box[1] + 80)} blue:Area] Then look here.')
            with patch.dict(os.environ, {'ATTICUS_ASK': str(root)}):
                _, events = atticus.InlineDrawing().feed(reply, final=True)
            payload = events[-1][1]
            self.assertEqual([s.get('wait') for s in payload['steps']], [True, None])
            guides.append(payload)
        source = (ROOT / 'Atticus.swift').read_text()
        drawing = source[source.index('// Screen drawings use Quartz'):source.index('// The box can take typing')]
        out = run_swift(self, 'import Cocoa\n' + MATH_STUB + swift_motion(source) + '\nfunc applySharing(_ w: NSWindow) {}\n' + drawing + r'''
let args = CommandLine.arguments, top = NSScreen.screens[0].frame.maxY
func cocoa(_ q: CGRect) -> CGRect { CGRect(x:q.minX,y:top-q.maxY,width:q.width,height:q.height) }
final class Counter: NSView {
    static var file = "", clicks = 0
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func mouseDown(with event: NSEvent) { Self.clicks += 1; try? String(Self.clicks).write(toFile:Self.file,atomically:true,encoding:.utf8) }
}
if args.count == 4 {   // another process: the user's app (main window + its own toolbar window), or another app's window over it
    let app = NSApplication.shared; app.setActivationPolicy(.regular)
    let q = (try! JSONSerialization.jsonObject(with:Data(args[2].utf8)) as! [Double]); Counter.file = args[3]
    func window(_ r: CGRect, _ style: NSWindow.StyleMask) -> NSWindow {
        let w = NSWindow(contentRect:cocoa(r),styleMask:style,backing:.buffered,defer:false)
        w.setFrame(cocoa(r),display:true); w.contentView = Counter(); w.isReleasedWhenClosed = false; return w
    }
    let main = window(CGRect(x:q[0],y:q[1],width:q[2],height:q[3]),[.titled])
    main.makeKeyAndOrderFront(nil)
    if args[1] == "app" { let bar = window(CGRect(x:q[0],y:q[1],width:q[2],height:110),[.borderless]); main.addChildWindow(bar,ordered:.above) }
    Timer.scheduledTimer(withTimeInterval:0.3,repeats:true) { _ in if getppid() == 1 { exit(0) } }   // never outlives the test
    app.activate(ignoringOtherApps:true); app.run()
}
let app = NSApplication.shared; app.setActivationPolicy(.accessory); app.finishLaunching()
func pump(_ s: Double, until done: () -> Bool = { false }) {
    let end = Date().addingTimeInterval(s)
    while Date() < end && !done() { if let e = app.nextEvent(matching:.any,until:Date().addingTimeInterval(0.02),inMode:.default,dequeue:true) { app.sendEvent(e) } }
}
func spawn(_ kind: String, _ q: CGRect, _ file: String) -> (Foundation.Process, [[String:Any]]) {
    let p = Foundation.Process(); p.executableURL = URL(fileURLWithPath:args[0]); p.arguments = [kind,"[\(q.minX),\(q.minY),\(q.width),\(q.height)]",file]
    try! p.run()
    var mine: [[String:Any]] = []
    pump(5) {
        mine = (CGWindowListCopyWindowInfo(.optionOnScreenOnly,kCGNullWindowID) as? [[String:Any]] ?? []).filter { ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == p.processIdentifier && ($0[kCGWindowLayer as String] as? Int) == 0 }
        return mine.count == (kind == "app" ? 2 : 1)
    }
    pump(0.3)
    return (p, mine)
}
func bounds(_ w: [String:Any]) -> CGRect { CGRect(dictionaryRepresentation:w[kCGWindowBounds as String] as! CFDictionary)! }
func click(_ p: CGPoint) {
    CGEvent(mouseEventSource:nil,mouseType:.mouseMoved,mouseCursorPosition:p,mouseButton:.left)!.post(tap:.cghidEventTap)
    pump(0.35)   // the guide's own tick sees where the pointer is first, as a person's pointer arrives before the click
    for type in [CGEventType.leftMouseDown,.leftMouseUp] {
        let e = CGEvent(mouseEventSource:CGEventSource(stateID:.hidSystemState),mouseType:type,mouseCursorPosition:p,mouseButton:.left)!
        e.setIntegerValueField(.mouseEventClickState,value:1); e.post(tap:.cghidEventTap); pump(0.05)
    }
}
func clicks(_ file: String) -> Int { Int((try? String(contentsOfFile:file,encoding:.utf8)) ?? "0") ?? 0 }
let tmp = NSTemporaryDirectory() + UUID().uuidString
try! FileManager.default.createDirectory(atPath:tmp,withIntermediateDirectories:true)
let appClicks = tmp + "/app", coverClicks = tmp + "/cover"
let mainRect = CGRect(x:__X0__,y:__Y0__,width:640,height:420)
let (user, windows) = spawn("app", mainRect, appClicks)
let main = windows.max { bounds($0).height < bounds($1).height }!, bar = windows.min { bounds($0).height < bounds($1).height }!
let order = (CGWindowListCopyWindowInfo(.optionOnScreenOnly,kCGNullWindowID) as! [[String:Any]]).compactMap { $0[kCGWindowNumber as String] as? NSNumber }
precondition(order.firstIndex(of:bar[kCGWindowNumber as String] as! NSNumber)! < order.firstIndex(of:main[kCGWindowNumber as String] as! NSNumber)!,"The app's toolbar window is not in front of its main window")
func live(_ w: [String:Any]) -> CGRect { bounds((CGWindowListCopyWindowInfo(.optionIncludingWindow,CGWindowID((w[kCGWindowNumber as String] as! NSNumber).uint32Value)) as! [[String:Any]])[0]) }
let guides = try! JSONSerialization.jsonObject(with:Data(#"__GUIDES__"#.utf8)) as! [[String:Any]]
for (n, guide) in guides.enumerated() {
    let f = live(main)
    var object = guide; object["cancelFile"] = tmp + "/guide-cancelled"
    object["target"] = ["pid":user.processIdentifier,"windowID":(main[kCGWindowNumber as String] as! NSNumber).stringValue,"windowFrame":[f.minX,f.minY,f.width,f.height]]
    try? FileManager.default.removeItem(atPath:tmp + "/guide-clicked")
    let d = ScreenDrawing(); d.speechEnabled = { false }
    var held = 0; d.waited = { held += 1 }
    let data = try! JSONSerialization.data(withJSONObject:object)
    let request = Result { try JSONDecoder().decode(DrawingRequest.self,from:data) }
    let why = (try? request.get()).map { "valid \(ScreenDrawing.valid($0)), displays \(ScreenDrawing.onDisplays($0)), current \(ScreenDrawing.current($0.target)), now \(live(main)) bar \(live(bar))" } ?? "\(request)"
    precondition(d.receive(data) && d.waiting,"Guide \(n) did not show and wait: \(why)")
    let hit = ScreenDrawing.rect((guide["steps"] as! [[String:Any]])[0]["hit"] as! [Double])
    let ring = ScreenDrawing.rect(((guide["steps"] as! [[String:Any]])[0]["shapes"] as! [[String:Any]])[0]["rect"] as! [Double])
    let inside = CGPoint(x:ring.midX,y:ring.midY)
    precondition(live(main).contains(inside) && hit.contains(inside),"Guide \(n): the ring is not over the app")
    print("guide \(n): ring \(ring) hit \(hit) over the toolbar window \(live(bar).contains(inside))")
    pump(0.5)
    // A click in the app away from the mark reaches the app and does not do the step.
    let m = live(main), card = d.calloutPanel.map { cocoa($0.frame).insetBy(dx:-10,dy:-10) } ?? .null
    let away = [CGPoint(x:m.maxX-30,y:m.maxY-30),CGPoint(x:m.minX+30,y:m.maxY-30),CGPoint(x:m.maxX-30,y:m.minY+140),CGPoint(x:m.minX+30,y:m.minY+140)]
        .first { p in !card.contains(p) && !hit.contains(p) && !d.occupied.contains { $0.insetBy(dx:-10,dy:-10).contains(p) } }!
    let before = clicks(appClicks)
    click(away)
    pump(0.3)
    precondition(clicks(appClicks) == before+1,"Guide \(n): the click away from the mark did not reach the app")
    precondition(d.index == 0 && d.waiting && held == 0,"Guide \(n): a click away from the mark did the step")
    // Another app's window over the mark takes the click: the step is not done.
    let (cover, _) = spawn("cover", CGRect(x:ring.minX-30,y:ring.minY-30,width:ring.width+60,height:ring.height+60), coverClicks)
    click(inside); pump(0.3)
    precondition(clicks(coverClicks) >= 1,"Guide \(n): the covering window did not get the click")
    precondition(d.index == 0 && d.waiting && held == 0,"Guide \(n): a click on another app's window over the mark did the step")
    cover.terminate(); cover.waitUntilExit(); pump(0.5)
    // The real click inside the ring reaches the app and does the step, with its voice going on.
    let reached = clicks(appClicks)
    click(inside)
    pump(2) { d.index == 1 }
    precondition(clicks(appClicks) == reached+1,"Guide \(n): the click inside the ring did not reach the app")
    precondition(d.index == 1 && !d.waiting && held == 1,"Guide \(n): a real click inside the ring did not do the step (index \(d.index), held \(held))")
    precondition(FileManager.default.fileExists(atPath:tmp + "/guide-clicked"),"Guide \(n): the walkthrough was not told of the click")
    d.back(); precondition(d.index == 0,"Guide \(n): Back after the click did not return")
    d.next(); precondition(d.index == 1,"Guide \(n): Next did not move on")
    d.clear()
}
user.terminate()
print("real clicks in a live inline guide: inside the ring advances, elsewhere does not")
'''.replace('__X0__', str(x0)).replace('__Y0__', str(y0)).replace('__GUIDES__', json.dumps(guides)), timeout=90)
        print(out, flush=True)
        self.assertIn('real clicks in a live inline guide: inside the ring advances, elsewhere does not', out)

    def test_edges_and_voice_navigation(self):
        source = (ROOT / 'Atticus.swift').read_text()
        drawing = source[source.index('// Screen drawings use Quartz'):source.index('// The box can take typing')]
        out = run_swift(self, 'import Cocoa\n' + MATH_STUB + swift_motion(source) + r'''
func applySharing(_ w: NSWindow) {}
final class Process {
    var executableURL: URL?, arguments: [String]?, isRunning = false
    static var spoken: [String] = [], fail = false
    func run() throws { if Self.fail { throw NSError(domain:"fixture",code:1) }; isRunning = true; Self.spoken.append(arguments!.last!) }
    func terminate() { isRunning = false }
}
''' + drawing + r'''
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let window = NSWindow(contentRect:CGRect(x:100,y:100,width:700,height:500),styleMask:.titled,backing:.buffered,defer:false)
window.isReleasedWhenClosed = false; window.level = .statusBar; window.makeKeyAndOrderFront(nil); app.activate()
var fixtureWindows: [[String:Any]] = []
let windowDeadline = Date().addingTimeInterval(2)
repeat {
    RunLoop.current.run(until:Date().addingTimeInterval(0.02))
    fixtureWindows = CGWindowListCopyWindowInfo(.optionIncludingWindow,CGWindowID(window.windowNumber)) as? [[String:Any]] ?? []
} while fixtureWindows.isEmpty && Date() < windowDeadline
guard let info = fixtureWindows.first else { preconditionFailure("Fixture window did not reach WindowServer") }
let bounds = CGRect(dictionaryRepresentation:info[kCGWindowBounds as String] as! CFDictionary)!
let target = DrawingWindow(pid:ProcessInfo.processInfo.processIdentifier,windowID:String(window.windowNumber),windowFrame:[bounds.minX,bounds.minY,bounds.width,bounds.height])
let steps = (0..<3).map { i in DrawingStep(id:nil,say:"Step \(i).",target:nil,shapes:[DrawingShape(kind:"circle",rect:[bounds.minX+100+Double(i)*90,bounds.minY+100,40,40])],wait:nil,hit:nil,timeout:nil) }
let request = DrawingRequest(steps:steps,teaching:true,target:target,state:"fixture",receipt:nil)
let data = try! JSONEncoder().encode(request.steps)
let payload = try! JSONSerialization.data(withJSONObject:["steps":try! JSONSerialization.jsonObject(with:data),"teaching":true,"target":["pid":target.pid,"windowID":target.windowID,"windowFrame":target.windowFrame],"state":"fixture"])
func fresh(_ data: Data) -> Data {
    window.makeKeyAndOrderFront(nil); app.activate()
    RunLoop.current.run(until:Date().addingTimeInterval(0.1))
    let info = (CGWindowListCopyWindowInfo(.optionIncludingWindow,CGWindowID(window.windowNumber)) as! [[String:Any]])[0]
    let rect = CGRect(dictionaryRepresentation:info[kCGWindowBounds as String] as! CFDictionary)!
    var object = try! JSONSerialization.jsonObject(with:data) as! [String:Any]
    var target = object["target"] as! [String:Any]
    target["windowFrame"] = [rect.minX,rect.minY,rect.width,rect.height]
    object["target"] = target
    return try! JSONSerialization.data(withJSONObject:object)
}
let d = ScreenDrawing()
var stops: [Bool] = []
d.navigated = { stops.append($0) }
var spoken = false
d.speechEnabled = { spoken }
precondition(d.receive(fresh(payload)))
let ink = d.panels.flatMap { $0.contentView?.layer?.sublayers ?? [] }.map(ObjectIdentifier.init)
for _ in 0..<20 { d.tick() }
precondition(d.index == 0 && d.active && d.calloutPanel!.isVisible)
precondition(ink == d.panels.flatMap { $0.contentView?.layer?.sublayers ?? [] }.map(ObjectIdentifier.init),"Silent marks expired")
let previousCard = d.calloutPanel!
d.next(); precondition(d.index == 1 && !previousCard.isVisible,"The old card covered the next step while fading")
let built = d.panels.compactMap { $0.contentView as? DrawingView }
precondition(Set(built.flatMap { $0.hits }.map { $0.step }) == [0,1],"Next dropped the previous step marks")
let builtLayers: [CALayer] = built.flatMap { $0.layer?.sublayers ?? [] }
let strokes: [CAShapeLayer] = builtLayers.compactMap { $0 as? CAShapeLayer }.filter { $0.lineWidth == 3 }
precondition(strokes.contains { $0.opacity == 0.5 } && strokes.contains { $0.opacity == 0.85 },"Earlier marks are not dimmed under the current step's full ink")
let dimmed: [CALayer] = builtLayers.filter { $0.opacity == 0.5 }
precondition(dimmed.allSatisfy { $0.animationKeys() == nil },"Earlier marks were drawn in again")
window.setFrameOrigin(CGPoint(x:window.frame.minX+20,y:window.frame.minY))
d.back(); precondition(d.index == 0 && d.active && stops.count >= 2 && stops.last == false,"Step buttons did not stop queued narration: index \(d.index), callbacks \(stops), active \(d.active)")
precondition(d.panels.compactMap { $0.contentView as? DrawingView }.flatMap { $0.hits }.allSatisfy { $0.step == 0 },"Back did not redraw earlier marks")
d.shownAt = .distantPast; d.tick(); precondition(d.index == 0,"Auto steps fought the user's Back")
spoken = true; Process.fail = true; precondition(d.receive(fresh(payload)))
d.tick(); precondition(d.index == 0 && d.voice == nil,"A failed speech process advanced the step")
d.shownAt = .distantPast; d.tick(); precondition(d.index == 1,"A step without a voice did not keep its reading time")
Process.fail = false; precondition(d.receive(fresh(payload)) && Process.spoken.last == "Step 0.")
d.shownAt = .distantPast; d.tick(); precondition(d.index == 0,"A step moved on over its own sentence")
d.voice!.isRunning = false; d.tick()
precondition(d.index == 1 && Process.spoken.last == "Step 1.","Voice did not drive the same step index")
d.back(); precondition(d.index == 0 && d.manual && Process.spoken.last == "Step 0.")
d.voice!.isRunning = false; d.tick(); precondition(d.index == 0,"Narration stepped on after the user took over")
d.next(); precondition(d.index == 1 && Process.spoken.last == "Step 1.")
d.next(); precondition(d.index == 2 && Process.spoken.last == "Step 2.")
d.voice!.isRunning = false; d.tick(); precondition(d.index == 2 && d.active,"Last spoken step vanished")
d.next(); precondition(!d.active && d.voice == nil && stops.last == true,"Done left narration running")
func cardClear(_ d: ScreenDrawing) -> Bool {
    guard let panel = d.calloutPanel else { return false }
    let top = NSScreen.screens[0].frame.maxY, f = panel.frame
    let frame = CGRect(x:f.minX,y:top-f.maxY,width:f.width,height:f.height)
    return NSScreen.screens.contains { $0.visibleFrame.contains(f) } && !d.panels.flatMap { ($0.contentView as? DrawingView)?.hitBounds ?? [] }.contains { $0.intersects(frame) }
}
window.setFrameOrigin(CGPoint(x:window.frame.minX-20,y:window.frame.minY))
RunLoop.current.run(until:Date().addingTimeInterval(0.1))
window.makeKeyAndOrderFront(nil); app.activate()
RunLoop.current.run(until:Date().addingTimeInterval(0.3))
let controlInfo = (CGWindowListCopyWindowInfo(.optionIncludingWindow,CGWindowID(window.windowNumber)) as! [[String:Any]])[0]
let controlBounds = CGRect(dictionaryRepresentation:controlInfo[kCGWindowBounds as String] as! CFDictionary)!
var howTo = try! JSONSerialization.jsonObject(with:payload) as! [String:Any]
var controlTarget = howTo["target"] as! [String:Any]
controlTarget["windowFrame"] = [controlBounds.minX,controlBounds.minY,controlBounds.width,controlBounds.height]
howTo["target"] = controlTarget
howTo["teaching"] = false
howTo["steps"] = (0..<3).map { i -> [String:Any] in
    let x = controlBounds.minX+100+Double(i)*90, y = controlBounds.minY+100
    return ["say":"Control \(i).","wait":true,"hit":[x,y,40,40],"shapes":[["kind":"circle","rect":[x,y,40,40]]]]
}
let controlData = try! JSONSerialization.data(withJSONObject:howTo)
let controlRequest = try! JSONDecoder().decode(DrawingRequest.self,from:controlData)
precondition(d.receive(controlData),"Control fixture refused: valid \(ScreenDrawing.valid(controlRequest)), display \(ScreenDrawing.onDisplays(controlRequest)), current \(ScreenDrawing.current(controlRequest.target))")
d.ready = .distantPast; d.clicked(CGPoint(x:controlBounds.minX+600,y:controlBounds.minY+400))
precondition(d.index == 0,"An unrelated click advanced a how-to step")
d.clicked(CGPoint(x:controlBounds.minX+120,y:controlBounds.minY+120))
precondition(d.index == 1 && Process.spoken.last == "Control 1." && cardClear(d),"Target click did not synchronize card, voice and marks")
d.back(); precondition(d.index == 0 && Process.spoken.last == "Control 0." && cardClear(d),"Back after target click lost the earlier ring")
d.clear(); spoken = false
precondition(d.receive(fresh(payload))); d.ready = .distantPast
d.clicked(CGPoint(x:bounds.minX+120,y:bounds.minY+120)); precondition(d.index == 0,"An explanation advanced from a screen click")
d.shownAt = .distantPast; d.tick(); d.shownAt = .distantPast; d.tick()
precondition(d.index == 2 && Set(d.panels.compactMap { $0.contentView as? DrawingView }.flatMap { $0.hits }.map { $0.step }) == [0,1,2] && cardClear(d),"Silent steps did not build the drawing up by themselves")
d.shownAt = .distantPast; d.tick(); precondition(d.index == 2 && d.active,"The last silent step did not stay")
(d.calloutPanel!.contentView as! DrawingCalloutView).closeGuide()
precondition(!d.active && d.panels.isEmpty,"The card X left drawings behind")
// One label is measured first and its connector meets the pill edge, independent of shape order.
let connected = DrawingView(frame:CGRect(x:0,y:0,width:900,height:600))
let targetRect = CGRect(x:450,y:220,width:80,height:40)
connected.render([DrawingShape(kind:"circle",rect:[450,220,80,40]),DrawingShape(kind:"arrow",points:[[240,240],[490,240]],color:"blue"),DrawingShape(kind:"label",at:[240,240],text:"Search",color:"blue")],animate:false,previous:nil)
let pill = connected.hits.first { $0.shape == 2 }!.area.boundingBoxOfPath
let arrow = connected.layer!.sublayers!.compactMap { $0 as? CAShapeLayer }.first { $0.lineWidth == 3 && $0.path!.boundingBoxOfPath.width > 100 && $0.path!.boundingBoxOfPath.height < 30 }!
precondition(abs(arrow.path!.boundingBoxOfPath.minX-pill.maxX) < 0.01,"Arrow tail does not touch its label")
precondition(abs(arrow.path!.boundingBoxOfPath.maxX-ScreenDrawing.ring(targetRect,circle:true).minX) < 0.01,"Arrow tip does not touch its target ring")
precondition(!pill.intersects(ScreenDrawing.ring(targetRect,circle:true)))
let ellipse = ScreenDrawing.ring(targetRect,circle:true)
let tip = ScreenDrawing.inkTip(from:.zero,to:CGPoint(x:ellipse.midX,y:ellipse.midY),targets:[CGPath(ellipseIn:ellipse,transform:nil)])
let dx = (tip.x-ellipse.midX)/(ellipse.width/2), dy = (tip.y-ellipse.midY)/(ellipse.height/2)
precondition(abs(dx*dx+dy*dy-1) < 0.0001,"Diagonal arrow stopped at the ellipse bounding box instead of its ink")
let caption = connected.layer!.sublayers!.compactMap { $0 as? CATextLayer }.first!
precondition((caption.string as? NSAttributedString)?.string == "Search","Color style leaked into label text")
for area in [CGRect(x:0,y:32,width:1440,height:800),CGRect(x:-1920,y:-180,width:1920,height:1000)] {
    for x in [area.minX,area.midX,area.maxX] {
        for y in [area.minY,area.midY,area.maxY] {
            let shapes = [DrawingShape(kind:"circle",rect:[x-15,y-15,30,30]),DrawingShape(kind:"pointer",at:[x,y]),DrawingShape(kind:"arrow",points:[[x-20,y-20],[x+20,y+20]])]
            for shape in shapes {
                let placed = ScreenDrawing.placed(shape,in:area)
                precondition(placed.rect == shape.rect && placed.at == shape.at && placed.points == shape.points,"Edge fitting moved target coordinates")
            }
            let view = DrawingView(frame:CGRect(origin:.zero,size:CGSize(width:area.width+80,height:area.height+80)))
            view.origin = CGPoint(x:area.minX-40,y:area.minY-40); view.visibleArea = area
            let drawn = view.render(shapes + [DrawingShape(kind:"label",at:[x,y],text:"Entry")],animate:false,previous:nil)
            precondition(view.display.contains(drawn) && view.hitBounds.allSatisfy(view.display.contains),"Rendered mark escaped its display")
            precondition(view.hits.contains { $0.shape == 3 },"An edge label disappeared")
            precondition(view.hits.filter { $0.shape == 3 }.allSatisfy { area.contains($0.area.boundingBoxOfPath.offsetBy(dx:view.origin.x,dy:view.origin.y)) },"An edge label left the work area")
            let card = ScreenDrawing.fitted(CGRect(x:x,y:y,width:400,height:450),in:area.insetBy(dx:12,dy:12)).insetBy(dx:-12,dy:-12)
            precondition(area.contains(card),"Card margin escaped visibleFrame")
            let mark = ScreenDrawing.markBounds([ScreenDrawing.placed(shapes[0],in:area)]).first!
            let placed = ScreenDrawing.calloutFrame(CGSize(width:400,height:200),marks:mark,avoid:[],in:area.insetBy(dx:12,dy:12)).card
            precondition(!placed.isNull && area.contains(placed.insetBy(dx:-12,dy:-12)) && !placed.insetBy(dx:-12,dy:-12).intersects(mark),"Edge card covered its marks")
            let label = ScreenDrawing.labelBox(CGSize(width:180,height:30),at:CGPoint(x:x,y:y),keepOff:[],in:area.insetBy(dx:6,dy:6))
            precondition(area.contains(label),"Label escaped visibleFrame")
        }
    }
    let outside = CGRect(x:area.maxX+40,y:area.maxY+40,width:400,height:200)
    let spot = ScreenDrawing.clearSpot(outside,avoiding:[],in:[area])!
    precondition(area.contains(CGRect(origin:spot,size:outside.size)),"A clear offscreen card was not clamped")
    let pane = DrawingView(frame:CGRect(origin:.zero,size:area.size)); pane.origin = area.origin; pane.visibleArea = area
    let boundary = pane.render([DrawingShape(kind:"pointer",at:[area.maxX,area.maxY])],animate:false,previous:nil)
    precondition(!boundary.isNull && area.contains(boundary),"A point exactly at the screen boundary was dropped")
    let oversized = DrawingShape(kind:"rect",rect:[area.minX+10,area.minY+50,area.width*3,50])
    let fitted = pane.render([oversized],animate:false,previous:nil)
    precondition(!fitted.isNull && area.contains(fitted),"A mark spanning displays was dropped or escaped its display")
}
let boardArea = ScreenDrawing.visibleArea(NSScreen.screens[0]).insetBy(dx:12,dy:12)
let boardStep = DrawingStep(id:nil,say:"Read.",target:nil,shapes:(0..<20).map { _ in DrawingShape(kind:"text",text:String(repeating:"Read this entry. ",count:10)) },wait:nil,hit:nil,timeout:nil)
let board = ScreenDrawing.board([boardStep],near:boardArea,at:boardArea.origin)!
precondition(boardArea.contains(board.frame),"A growing board returned its unbounded content size")
let boardPage = ScreenDrawing.boardPage(board,through:0)!
precondition(boardPage.lines.allSatisfy { boardArea.contains($0.rect) },"Board line escaped visible area")
for text in ["Click Next.",String(repeating:"Read the table and compare each entry. ",count:20)] {
    let size = DrawingCalloutView.size(text,total:12)
    let pages = DrawingCalloutView.pages(text,width:DrawingCalloutView.textWidth(size.width),height:DrawingCalloutView.bodyHeight(size.height,header:true))
    precondition(pages.count <= 2 && pages.joined() == text)
    let card = DrawingCalloutView(frame:CGRect(origin:.zero,size:size),card:CGRect(origin:.zero,size:size),side:nil,tip:0,text:pages[0],step:12,total:12,page:12,pages:12)
    let header = card.subviews.compactMap { $0 as? NSTextField }.first!
    precondition(header.intrinsicContentSize.width <= header.frame.width,"Progress truncated")
}
spoken = false
let screen = NSScreen.screens[0], area = ScreenDrawing.visibleArea(screen)
for (style,appearance) in [("light",NSAppearance.Name.aqua),("dark",.darkAqua)] {
    let backdrop = DrawingPanel(contentRect:screen.visibleFrame,styleMask:[.borderless,.nonactivatingPanel],backing:.buffered,defer:false)
    backdrop.isReleasedWhenClosed = false; backdrop.level = NSWindow.Level(rawValue:NSWindow.Level.statusBar.rawValue-1)
    backdrop.backgroundColor = style == "light" ? .white : NSColor(calibratedWhite:0.14,alpha:1)
    backdrop.orderFrontRegardless()
    window.appearance = NSAppearance(named:appearance)
    window.backgroundColor = style == "light" ? .white : NSColor(calibratedWhite:0.14,alpha:1)
    for (name,point) in [("right",CGPoint(x:area.maxX-25,y:area.midY)),("bottom",CGPoint(x:area.midX,y:area.maxY-25))] {
        var object = try! JSONSerialization.jsonObject(with:payload) as! [String:Any]
        object["steps"] = [["say":"Compare this entry with the previous row before continuing.","shapes":[["kind":"circle","rect":[point.x-15,point.y-15,30,30]]]]]
        precondition(d.receive(fresh(try! JSONSerialization.data(withJSONObject:object))))
        RunLoop.current.run(until:Date().addingTimeInterval(0.5))
        precondition(screen.visibleFrame.contains(d.calloutPanel!.frame),"Edge callout escaped display")
        let file = NSTemporaryDirectory()+UUID().uuidString+".png"
        let capture = Foundation.Process(); capture.executableURL = URL(fileURLWithPath:"/usr/sbin/screencapture"); capture.arguments = ["-x",file]
        try! capture.run(); capture.waitUntilExit(); precondition(capture.terminationStatus == 0)
        print("GUIDECARD_PNG after-\(style)-edge-\(name) \((try! Data(contentsOf:URL(fileURLWithPath:file))).base64EncodedString())")
        try! FileManager.default.removeItem(atPath:file)
        d.clear()
    }
    for i in 0..<3 {
        var example = try! JSONSerialization.jsonObject(with:payload) as! [String:Any]
        example["steps"] = (0..<3).map { step -> [String:Any] in
            let x = bounds.minX+100+Double(step)*130, y = bounds.minY+130+Double(step)*70
            return ["say":["Use search to find a page.","Compare the suggested results.","Keep the useful page in your library."][step],"shapes":[
                ["kind":"circle","rect":[x,y,80,36],"color":"blue"],
                ["kind":"arrow","points":[[x-60,y-70],[x+40,y+18]],"color":"blue"],
                ["kind":"label","at":[x-60,y-70],"text":["Search","Suggestions","Library"][step],"color":"blue"]]]
        }
        precondition(d.receive(fresh(try! JSONSerialization.data(withJSONObject:example))))
        for _ in 0..<i { d.next() }
        d.showStep(forward:false,mathOnly:true)   // capture the settled ink, not an intermediate animation frame
        RunLoop.current.run(until:Date().addingTimeInterval(0.3))
        precondition(d.index == i && cardClear(d),"Page explanation card covered its current drawings")
        let file = NSTemporaryDirectory()+UUID().uuidString+".png"
        let capture = Foundation.Process(); capture.executableURL = URL(fileURLWithPath:"/usr/sbin/screencapture"); capture.arguments = ["-x",file]
        try! capture.run(); capture.waitUntilExit(); precondition(capture.terminationStatus == 0)
        print("GUIDECARD_PNG after-\(style)-page-step-\(i+1) \((try! Data(contentsOf:URL(fileURLWithPath:file))).base64EncodedString())")
        try! FileManager.default.removeItem(atPath:file); d.clear()
    }
    backdrop.close()
}
print("guide card edges, two display coordinates, silent lifetime, speech and navigation: OK")
''', timeout=60)
        print(out)

    def test_real_native_and_webkit_renders(self):
        source = (ROOT / 'Atticus.swift').read_text()
        math = source[source.index('final class DrawingMath:'):source.index('// Screen drawings use Quartz')]
        card = source[source.index('final class DrawingCalloutView:'):source.index('final class ScreenDrawing {')]
        phase = 'after'
        out = run_swift(self, 'import Cocoa\nimport WebKit\n' + r'''
func loadPage(_ web: WKWebView, _ name: String) {
    let root = URL(fileURLWithPath:FileManager.default.currentDirectoryPath).appendingPathComponent("ui")
    let html = try! String(contentsOf:root.appendingPathComponent(name),encoding:.utf8)
        .replacingOccurrences(of:"/*TOKENS*/",with:try! String(contentsOf:root.appendingPathComponent("tokens.css"),encoding:.utf8))
        .replacingOccurrences(of:"/*ORBS*/",with:try! String(contentsOf:root.appendingPathComponent("orbs.js"),encoding:.utf8))
    web.loadHTMLString(html,baseURL:root)
}
final class PageErrors { static let shared = PageErrors(); func evaluated(_ call: String, _ error: Error?) {} }
''' + math + card + r'''
let app = NSApplication.shared; app.setActivationPolicy(.accessory)
let short = "Click the table to compare the two entries."
let long = String(repeating:"Read each table entry, compare the values, then explain the difference. ",count:8)
let maximum = String(String(repeating:"Compare the entries and check the result before moving to the next row. ",count:20).prefix(1000))
let listed = ''' + json.dumps(HIS_CARD, ensure_ascii=False) + r'''
precondition(DrawingMath.formatted(listed) && !DrawingMath.formatted(short) && !DrawingMath.formatted(long),"Card text took the wrong path")
for (appearance,style) in [("light",NSAppearance.Name.aqua),("dark",.darkAqua)] {
    let window = NSWindow(contentRect:CGRect(x:30,y:70,width:950,height:650),styleMask:.borderless,backing:.buffered,defer:false)
    window.isReleasedWhenClosed = false; window.appearance = NSAppearance(named:style)
    window.backgroundColor = appearance == "light" ? .white : NSColor(calibratedWhite:0.14,alpha:1)
    window.orderFrontRegardless()
    for (name,text) in [("short",short),("long",long),("maximum-fixture",maximum),("right-bottom",long),("math","Check $x^2 + 6x + 9 = (x+3)^2$ before continuing."),("markdown",listed)] {
        window.contentView!.subviews.forEach { $0.removeFromSuperview() }
        if DrawingMath.formatted(text) {
            _ = DrawingCalloutView.body(text,width:DrawingCalloutView.textWidth(400))
            let ready = Date().addingTimeInterval(15)
            while DrawingMath.jobs.values.contains(where: { $0.image == nil }) && Date() < ready { RunLoop.current.run(until:Date().addingTimeInterval(0.05)) }
            precondition(DrawingMath.jobs.values.contains { $0.font == DrawingCalloutView.font.pointSize && $0.image != nil },"Math caption did not use the card's body font")
        }
        let size = DrawingCalloutView.size(text,total:12)
        let pages = DrawingCalloutView.pages(text,width:DrawingCalloutView.textWidth(size.width),height:max(1,size.height-90))
        let card = CGRect(x:12,y:12,width:size.width,height:size.height)
        let view = DrawingCalloutView(frame:CGRect(x:name == "right-bottom" ? 950-size.width-24 : 40,y:30,width:size.width+24,height:size.height+24),card:card,side:.maxX,tip:40,text:pages[0],step:12,total:12,page:1,pages:pages.count)
        view.appearance = NSAppearance(named:.darkAqua); window.contentView!.addSubview(view)
        let scroll = view.subviews.compactMap { $0 as? NSScrollView }.first!
        let body = scroll.documentView as! NSTextView
        precondition(body.frame.width <= scroll.contentSize.width && body.frame.height <= scroll.contentSize.height,"Caption exceeds its measured viewport")
        if DrawingMath.formatted(text) { precondition(body.textStorage!.attribute(.attachment,at:0,effectiveRange:nil) is NSTextAttachment && pages == [text],"Caption showed raw markup") }
        RunLoop.current.run(until:Date().addingTimeInterval(0.2))
        let file = NSTemporaryDirectory()+UUID().uuidString+".png"
        let p = Process(); p.executableURL = URL(fileURLWithPath:"/usr/sbin/screencapture"); p.arguments = ["-x","-o","-l",String(window.windowNumber),file]
        try! p.run(); p.waitUntilExit(); precondition(p.terminationStatus == 0)
        print("GUIDECARD_PNG __PHASE__-\(appearance)-\(name) \((try! Data(contentsOf:URL(fileURLWithPath:file))).base64EncodedString())")
        print("GUIDECARD_SIZE __PHASE__ \(name) \(size) pages=\(pages.count)")
        try! FileManager.default.removeItem(atPath:file)
    }
    // Force the real offscreen WebKit math pixel path and export its result too.
    let rich = NSAttributedString(string:"Check $x^2 + 6x + 9 = (x+3)^2$",attributes:[.font:NSFont.systemFont(ofSize:22),.foregroundColor:NSColor.white])
    _ = DrawingMath.image(rich,width:368)
    let deadline = Date().addingTimeInterval(15)
    while DrawingMath.jobs.values.first(where: { $0.text == rich.string })?.image == nil && Date() < deadline { RunLoop.current.run(until:Date().addingTimeInterval(0.05)) }
    precondition(DrawingMath.jobs.values.first(where: { $0.text == rich.string })?.image != nil,"Real WebKit math did not render")
    let image = DrawingMath.jobs.values.first(where: { $0.text == rich.string })!.image!
    let png = NSBitmapImageRep(data:image.tiffRepresentation!)!.representation(using:.png,properties:[:])!
    print("GUIDECARD_PNG __PHASE__-\(appearance)-webkit \(png.base64EncodedString())")
    DrawingMath.reset(); window.close()
}
print("native card and real WebKit renders: OK")
'''.replace('__PHASE__', phase), timeout=60)
        print(out, flush=True)
