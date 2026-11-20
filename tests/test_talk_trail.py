"""Native trail measurements; every executable runs only in the Tart VM."""
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from tests import run_swift, swift_motion


class TalkTrailTests(unittest.TestCase):
    def test_real_rate_circle(self):
        self.measure_circle()

    def measure_circle(self):
        source = (Path(__file__).parents[1] / 'Atticus.swift').read_text()
        pen = source[source.index('final class TalkPen:'):source.index('func boxWidth(')]
        pen = pen.replace('guard let p = CGEvent(source:nil)?.location else { return }', 'let p = inputLock.withLock { inputPoint }')
        hook = 'override func draw(_ dirty: NSRect) {' if 'override func draw(' in pen else 'func render(_ now: Double) {'
        pen = pen.replace('v.needsDisplay = true', 'v.needsDisplay = true; v.displayIfNeeded()')
        pen = pen.replace(hook, hook + '''
        let began = ProcessInfo.processInfo.systemUptime
        defer { frameTimes.append(began); workTimes.append(ProcessInfo.processInfo.systemUptime-began) }
''')
        pen = pen.replace('func sample() {', 'func sample() {\nlet tickBegan = ProcessInfo.processInfo.systemUptime\ndefer { tickTimes.append(ProcessInfo.processInfo.systemUptime-tickBegan) }')
        pen = pen.replace('points = Self.resample(points,step:max(3,length/120))',
                          'points = Self.resample(points,step:max(3,length/120)); geometryCounts.append(points.count)')
        result = run_swift(self, 'import AppKit\nfunc applySharing(_ w: NSWindow) {}\n' + swift_motion(source) +
                           source[source.index('final class DrawingPanel:'):source.index('struct DrawingShape:')] + '''
var geometryCounts: [Int] = []
let inputLock = NSLock()
var inputPoint = CGPoint(x:680,y:400)
var frameTimes: [Double] = [], workTimes: [Double] = [], inputTimes: [Double] = [], tickTimes: [Double] = []
''' + pen + '''
_ = NSApplication.shared
let pen = TalkPen(), began = ProcessInfo.processInfo.systemUptime
let driver = DispatchSource.makeTimerSource(flags:.strict,queue:DispatchQueue(label:"syntheticCursor",qos:.userInteractive))
driver.schedule(deadline:.now(),repeating:.nanoseconds(8_333_333),leeway:.nanoseconds(0))
driver.setEventHandler {
    let t = ProcessInfo.processInfo.systemUptime-began
    inputLock.withLock {
        inputTimes.append(t)
        inputPoint = CGPoint(x:500+180*cos(t*2*Double.pi),y:400+180*sin(t*2*Double.pi))
    }
}
driver.resume()
pen.start()
RunLoop.current.run(until:Date().addingTimeInterval(3))
driver.cancel(); pen.stop()
let inputCount = inputLock.withLock { inputTimes.count }
let gaps = zip(frameTimes,frameTimes.dropFirst()).map { ($1-$0)*1000 }.sorted()
let work = workTimes.map { $0*1000 }.sorted()
let ticks = tickTimes.map { $0*1000 }.sorted()
precondition(frameTimes.count >= 90 && inputCount >= 150,"trail missed its real-rate input")
precondition((geometryCounts.max() ?? 0) <= 123,"unbounded stroke geometry")
let samples = pen.samples
var angles: [Double] = []
for i in 2..<samples.count {
    let a = samples[i-2], b = samples[i-1], c = samples[i]
    let u = CGPoint(x:b[1]-a[1],y:b[2]-a[2]), v = CGPoint(x:c[1]-b[1],y:c[2]-b[2])
    let lengths = hypot(u.x,u.y)*hypot(v.x,v.y)
    if lengths > 0 { angles.append(acos(Double(min(1,max(-1,(u.x*v.x+u.y*v.y)/lengths))))*180/Double.pi) }
}
let metrics: [String:Double] = [
    "path_points_max":Double(geometryCounts.max() ?? 0),"screen_hz":Double(NSScreen.main!.maximumFramesPerSecond),"input_hz":Double(inputCount)/3,"samples":Double(samples.count),"frames":Double(frameTimes.count),
    "frame_gap_p95_ms":gaps[Int(Double(gaps.count-1)*0.95)],"frame_gap_max_ms":gaps.last!,
    "sample_work_p95_ms":ticks[Int(Double(ticks.count-1)*0.95)],"sample_work_max_ms":ticks.last!,
    "work_p95_ms":work[Int(Double(work.count-1)*0.95)],"work_max_ms":work.last!,
    "sample_segment_angle_max_deg":angles.max() ?? 0
]
let data = try! JSONSerialization.data(withJSONObject:metrics,options:[.sortedKeys])
print("TRAIL_METRICS " + String(data:data,encoding:.utf8)!)
''', timeout=15)
        print(result, flush=True)

    def test_hold_claims_its_clicks(self):
        source = (Path(__file__).parents[1] / 'Atticus.swift').read_text()
        claims = source[source.index('    static func claims('):source.index('    func claimClicks()')]
        run_swift(self, 'import AppKit\nenum Pen {\n' + claims + '''}
var held = Set<Int64>()
precondition(Pen.claims(.leftMouseDown, button:0, holding:true, ours:false, claimed:&held),"a click while held kept the shortcut's ⌃ (a context menu)")
precondition(Pen.claims(.leftMouseDragged, button:0, holding:false, ours:false, claimed:&held),"a circle drag kept ⌃")
precondition(Pen.claims(.leftMouseUp, button:0, holding:false, ours:false, claimed:&held) && held.isEmpty,"the click's release kept ⌃")
precondition(!Pen.claims(.leftMouseDown, button:0, holding:false, ours:false, claimed:&held),"a click after release lost its own ⌃")
precondition(!Pen.claims(.leftMouseUp, button:0, holding:true, ours:false, claimed:&held),"a release of a click from before the hold was changed")
precondition(!Pen.claims(.leftMouseDown, button:0, holding:true, ours:true, claimed:&held) && held.isEmpty,"Atticus's own mark click was changed")
precondition(Pen.claims(.rightMouseDown, button:1, holding:true, ours:false, claimed:&held) && !Pen.claims(.leftMouseUp, button:0, holding:true, ours:false, claimed:&held))
''')

    def test_plip_smoothing_and_persistent_layers(self):
        source = (Path(__file__).parents[1] / 'Atticus.swift').read_text()
        pen = source[source.index('final class TalkPen:'):source.index('func boxWidth(')]
        pen = pen.replace('NSWorkspace.shared.accessibilityDisplayShouldReduceMotion', 'reduceMotion')
        run_swift(self, 'import AppKit\nfunc applySharing(_ w: NSWindow) {}\n' + swift_motion(source) +
                  source[source.index('final class DrawingPanel:'):source.index('struct DrawingShape:')] + 'var reduceMotion = false\n' + pen + '''
_ = NSApplication.shared
let samples = (0..<121).map { i -> [Double] in
    let t = Double(i)/120
    return [t,200+80*cos(t*2*Double.pi)+sin(Double(i)*2)*3,200+80*sin(t*2*Double.pi)]
}
let smoothed = TalkPen.smooth(samples)
for (i,s) in samples.enumerated() {
    let near = samples.filter { $0[0] >= s[0]-0.025 && $0[0] <= s[0]+0.025 }
    let x = near.map { $0[1] }.reduce(0,+)/Double(near.count)
    let y = near.map { $0[2] }.reduce(0,+)/Double(near.count)
    precondition(hypot(smoothed[i].x-x,smoothed[i].y-y) < 1e-8)
}
precondition(TalkPen.smooth([]).isEmpty)
precondition(TalkPen.smooth([[0,2,3]]) == [CGPoint(x:2,y:3)])
precondition(TalkPen.smooth([[0,2,3],[1,5,6]]) == [CGPoint(x:2,y:3),CGPoint(x:5,y:6)])
let points = TalkPen.resample(smoothed,step:3)
precondition(points.first == smoothed.first && points.last == smoothed.last)
for (a,b) in zip(points,points.dropFirst()) { precondition(hypot(a.x-b.x,a.y-b.y) <= 3.000001) }
let pen = TalkPen(); pen.start()
precondition(pen.timer?.preferredFrameRateRange.preferred == 60,"gesture capture exceeded its sample budget")
precondition(pen.windows.isEmpty,"stationary press drew a mark")
let p = CGEvent(source:nil)!.location, now = ProcessInfo.processInfo.systemUptime
pen.samples = [[now-0.1,p.x-10,p.y]]; pen.sample()
precondition(pen.windows.isEmpty,"trackpad jitter drew a mark")
pen.samples = [[now-0.5,p.x-100,p.y-100]]; pen.sample()
let view = pen.windows.first!.contentView as! TalkPen
let bands = view.bands, edges = view.edges
precondition(bands.count == 8 && edges.count == 8)
view.render(now+0.01)
precondition(zip(bands,view.bands).allSatisfy { $0 === $1 })
precondition(zip(edges,view.edges).allSatisfy { $0 === $1 })
precondition(view.layer!.animationKeys() == nil,"implicit frame animations")
for line in view.bands + view.edges { precondition(line.animationKeys() == nil) }
view.samples = [[now-1,p.x-100,p.y-100]] + (0..<60).map { [now-0.5+Double($0)/120,p.x,p.y] }
view.render(now)
precondition(view.bands.allSatisfy { $0.path == nil },"stopped tail did not draw back")
precondition(view.resting && view.glow.opacity == 1)
precondition(view.glow.animation(forKey:"grow") != nil && view.ripple.animation(forKey:"ripple") != nil)
view.render(now+0.01)
precondition(view.ripple.animationKeys()?.count ?? 0 <= 1,"rest added repeated ripples")
reduceMotion = true
view.resting = false; view.glow.removeAllAnimations(); view.ripple.removeAllAnimations()
view.render(now+0.02)
precondition(view.glow.opacity == 1 && view.glow.animation(forKey:"bloom") != nil)
precondition(view.glow.animation(forKey:"grow") == nil && view.ripple.animation(forKey:"ripple") == nil,
             "Reduce Motion still scaled or rippled")
pen.stop()
precondition(pen.timer == nil && pen.windows.isEmpty)
let stoppedCount = pen.samples.count
RunLoop.current.run(until:Date().addingTimeInterval(0.05))
precondition(pen.samples.count == stoppedCount,"sampling continued after release")
''')

    def test_trail_follows_sharing_preference(self):
        source = (Path(__file__).parents[1] / 'Atticus.swift').read_text()
        prefs = source[source.index('enum Prefs'):source.index('func profileName(')]
        live = next(line for line in source.splitlines() if 'if k == "hideWhenSharing"' in line)
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, ATTICUS_DIR=root):
            run_swift(self, 'import AppKit\nlet controlKey = 1, optionKey = 2\n' + prefs + swift_motion(source) +
                      source[source.index('final class DrawingPanel:'):source.index('struct DrawingShape:')] +
                      source[source.index('final class TalkPen:'):source.index('func boxWidth(')] + '''
_ = NSApplication.shared
let k = "hideWhenSharing"
func trail() -> [NSWindow] {
    let pen = TalkPen(), p = CGEvent(source:nil)!.location, now = ProcessInfo.processInfo.systemUptime
    pen.samples = [[now-0.5,p.x-100,p.y-100]]; pen.sample()
    precondition(!pen.windows.isEmpty)
    return pen.windows
}
precondition(trail().allSatisfy { $0.sharingType == .none },"trail ignored the default")
let shown = trail()
for enabled in [false, true, false] {
    Prefs.set(k, enabled)
''' + live + '''
    precondition(shown.allSatisfy { $0.sharingType == (enabled ? .none : .readOnly) },"live change missed the trail")
    precondition(trail().allSatisfy { $0.sharingType == (enabled ? .none : .readOnly) },"new trail missed the preference")
}
''')
