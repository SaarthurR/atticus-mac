"""Adapted Plip gesture cases (MIT; LICENSE-Plip), stdlib-only fixtures; run in the Tart VM."""
import math
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import atticus


def stroke(points, step=1/60):
    return [[i*step, x, y] for i, (x, y) in enumerate(points)]


def circle(shaky=False):
    return stroke([(200+(80+(3*math.sin(i*2) if shaky else 0))*math.cos(i*2*math.pi/120),
                    200+(80+(3*math.cos(i*3) if shaky else 0))*math.sin(i*2*math.pi/120)) for i in range(121)])


class TalkPointerTests(unittest.TestCase):
    def test_plip_classifier_cases(self):
        for shaky in (False, True):
            self.assertEqual(atticus.read_gesture(circle(shaky)).kind, 'circle')
        self.assertEqual(atticus.read_gesture(stroke([(i*2, 100) for i in range(81)])).kind, 'line')
        rests = stroke([(0, 0)]*25+[(i*4, 0) for i in range(1, 26)]+[(100, 0)]*40+
                       [(100, i*4) for i in range(1, 26)]+[(100, 100)]*40)
        self.assertEqual(atticus.read_gesture(rests).kind, 'point')
        corners = [(0,0),(200,0),(200,20),(0,20),(0,40),(200,40),(200,60),(0,60),(0,80),(20,80)]
        area = stroke([(a[0]+(b[0]-a[0])*i/30,a[1]+(b[1]-a[1])*i/30) for a,b in zip(corners,corners[1:]) for i in range(30)], step=1/120)
        self.assertEqual(atticus.read_gesture(area).kind, 'area')
        jitter = stroke([(100+math.sin(i)*3, 100+math.cos(i)*3) for i in range(100)])
        self.assertEqual(atticus.read_gesture(jitter).kind, 'rest')
        self.assertIsNone(atticus.talk_pointer(jitter, 'weather tomorrow'))
        self.assertEqual(atticus.talk_pointer(jitter, 'what is this').kind, 'point')
        parked = stroke([(0,0)]*10+[(i*4,0) for i in range(26)]+[(100,0)]*60)
        self.assertIsNone(atticus.talk_pointer(parked, 'open Spotify'))
        self.assertEqual(atticus.talk_pointer(parked, 'snap this left').kind, 'point')

    def test_untrusted_samples(self):
        for samples in (None, [], [[1, 2]], [[0, True, 2]], [[0, float('nan'), 2]], [[0, 10**400, 2]],
                        [[2, 0, 0], [1, 0, 0]], [[0, 0, 0]]*2401):
            self.assertIsNone(atticus.talk_pointer(samples, 'this'))

    def test_projection_and_description(self):
        g = atticus.Gesture('point', spots=((-50,-150),(500,500)), moved=True)
        shots = [atticus.Screenshot(atticus.ScreenInfo(2, atticus.Rect(-100,-200,2560,1440)), b'',1280,720)]
        self.assertEqual(atticus.gesture_marks(g, shots[0])['spots'][0], [1,25,25])
        self.assertIn('25,25', atticus.describe_gesture(g, shots, lambda x,y: 'Save button'))
        self.assertIn('Save button', atticus.describe_gesture(g, shots, lambda x,y: 'Save button'))
        self.assertEqual(atticus.describe_gesture(atticus.Gesture('rest'), shots), '')

    def test_capture_receives_gesture_cursor_screen_first(self):
        calls = []
        def capture(args, **kwargs):
            calls.append(args)
            Path(args[3]).touch()
            return subprocess.CompletedProcess(args, 0, stdout='pointed\nunder:["AXButton: Save"]\n')
        g = atticus.Gesture('point', spots=((-50,-150),), moved=True)
        with tempfile.TemporaryDirectory() as root, patch.dict(atticus.os.environ, {'ATTICUS_ASK':root}), \
             patch.object(atticus,'pref',return_value=False), \
             patch.object(atticus,'screens',return_value=[['main',0,0,1280,720,True],['external',-100,-200,100,200,False]]), \
             patch.object(atticus.subprocess,'run',side_effect=capture):
            shots = atticus.look(pointer=g)
            self.assertIn('Screen 2:',shots[0][1])
            self.assertIn('primary focus',shots[0][1])
            self.assertNotIn('primary focus',shots[1][1])
            self.assertIn('pointed with the cursor',shots[0][1])
            self.assertIn('AXButton: Save',shots[0][1])
            pointed = next(c for c in calls if c[2]=='2')
            self.assertEqual(pointed[4], '')
            shots = atticus.look()
            self.assertNotIn('pointed with the cursor',shots[0][1])

    def test_silent_point_and_line_keep_plip_default(self):
        self.assertEqual(atticus.silent_ask(atticus.read_gesture(circle())), "what's this?")
        self.assertEqual(atticus.silent_ask(atticus.Gesture('area')), '')
        self.assertEqual(atticus.silent_ask(atticus.Gesture('rest')), '')

    def test_native_jitter_skips_classifier_but_pointing_words_do_not(self):
        from tests import run_swift
        source = (Path(atticus.__file__).parent/'Atticus.swift').read_text()
        settle = source[source.index('    func settleTalkPointer()'):source.index('    var pointContext:')]
        run_swift(self, 'import Cocoa\nimport Darwin\nfunc telemetry(_ args: [String]) {}\n' + '''
var launches = 0
func py(_ args: [String]) -> Process {
    launches += 1
    let p = Process(); p.executableURL = URL(fileURLWithPath:"/usr/bin/true"); return p
}
final class State {
    var talkPath: [[Double]] = [], text = ""
''' + settle + '''
}
let state = State()
for path in [[[0.0,100,100]], [[0.0,100,100],[1,102,101],[2,99,100]]] {
    state.talkPath = path; state.text = "weather tomorrow"; state.settleTalkPointer()
    precondition(state.talkPath.isEmpty && launches == 0,"jitter launched another Python process")
}
state.talkPath = [[0,100,100]]; state.text = "what is this?"; state.settleTalkPointer()
precondition(launches == 1,"stationary intentional pointing was discarded")
state.talkPath = [[0,100,100],[1,200,200]]; state.text = "weather tomorrow"; state.settleTalkPointer()
precondition(launches == 2,"movement bypassed Plip classification")
''')

    def test_failed_capture_never_falls_back_to_a_trail_inclusive_image(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(atticus.os.environ, {'ATTICUS_ASK':root}), \
             patch.object(atticus,'pref',return_value=False), \
             patch.object(atticus,'screens',return_value=[['main',0,0,1280,720,True]]):
            for pointer in (None, atticus.Gesture('point', spots=((100,100),))):
                calls = []
                def capture(args, **kwargs):
                    calls.append(args)
                    Path(args[3]).write_bytes(b'partial image')
                    return subprocess.CompletedProcess(args, 1, stdout='')
                with patch.object(atticus.subprocess,'run',side_effect=capture):
                    self.assertEqual(atticus.look(pointer=pointer), [])
                self.assertEqual(len(calls), 1)
                self.assertEqual(list(Path(root).iterdir()), [])

    def test_native_pen_is_click_through_and_gone_on_release(self):
        from tests import run_swift
        swift = (Path(atticus.__file__).parent/'Atticus.swift').read_text()
        pen = swift[swift.index('final class DrawingPanel:'):swift.index('struct DrawingShape:')] + swift[swift.index('final class TalkPen:'):swift.index('final class App:')]
        decision = swift[swift.index('    var talkMoved: Bool {'):swift.index('    func sampleTalkPointer()')]
        cancel = swift[swift.index('    func stopOfferInput()'):swift.index('        unwarm()', swift.index('    func stopOfferInput()'))]
        state = 'final class Engine { var stopped = false; func stop() { stopped = true } }\n' + \
                'final class State { var talkReleased = false, talkPath: [[Double]] = [], text = ""; let talkPen = TalkPen(), engine = Engine()\n' + decision + cancel + '}\n}\n'
        run_swift(self, 'import AppKit\nfunc applySharing(_ w: NSWindow) {}\n' + pen + state + '''
_ = NSApplication.shared
let pen = TalkPen()
let before = NSWorkspace.shared.frontmostApplication?.processIdentifier
let point = CGEvent(source:nil)!.location, now = ProcessInfo.processInfo.systemUptime
pen.samples = [[now-1,point.x-200,point.y-200],[now-0.5,point.x-100,point.y-100]]
pen.sample()
precondition(!pen.windows.isEmpty)
for w in pen.windows {
    precondition(w.ignoresMouseEvents && !w.canBecomeKey)
    w.contentView?.display()
}
precondition(NSWorkspace.shared.frontmostApplication?.processIdentifier == before)
precondition(pen.samples.last!.count == 3)
pen.stop()
precondition(pen.windows.isEmpty && pen.timer == nil)
pen.sample()
let fading = pen.windows
pen.stop(fade:true)
RunLoop.current.run(until:Date().addingTimeInterval(0.5))
precondition(pen.windows.isEmpty && pen.timer == nil && fading.allSatisfy { !$0.isVisible })
let state = State(); state.talkReleased = true
state.talkPath = [[0,35,0],[1,-35,0]]
precondition(state.talkMoved,"classified gesture reused a speculative ask")
state.talkPath = []; precondition(!state.talkMoved,"rest discarded a matching speculative ask")
state.talkPen.start(); state.talkPen.samples = pen.samples; state.talkPen.sample()
precondition(!state.talkPen.windows.isEmpty && state.talkPen.timer != nil)
state.stopOfferInput()
precondition(state.engine.stopped && state.talkPen.windows.isEmpty && state.talkPen.timer == nil,
             "cancelled offer left the cursor trail alive")
''')

    def test_native_pen_render_and_restart_during_fade(self):
        from tests import run_swift, swift_motion
        source = (Path(atticus.__file__).parent/'Atticus.swift').read_text()
        pen = swift_motion(source) + source[source.index('final class DrawingPanel:'):source.index('struct DrawingShape:')] + source[source.index('final class TalkPen:'):source.index('func boxWidth(')]
        out = run_swift(self, 'import AppKit\nfunc applySharing(_ w: NSWindow) {}\n' + pen + '''
_ = NSApplication.shared
let now = ProcessInfo.processInfo.systemUptime, top = NSScreen.screens.first!.frame.maxY
let window = DrawingPanel(contentRect:NSRect(x:0,y:top-330,width:480,height:330),styleMask:[.borderless,.nonactivatingPanel],backing:.buffered,defer:false)
window.backgroundColor = NSColor(calibratedWhite:0.12,alpha:1)
let view = TalkPen(frame:NSRect(x:0,y:0,width:480,height:330))
view.samples = (0..<31).map { i in
    let fraction = Double(i)/30
    let y = 165.0 + sin(fraction * Double.pi * 2) * 65
    return [now - 0.5 + Double(i)/60,80.0 + Double(i)*10,y]
}
window.contentView = view; window.orderFrontRegardless(); view.render(now)
let image = view.bitmapImageRepForCachingDisplay(in:view.bounds)!
view.cacheDisplay(in:view.bounds,to:image)
let scale = Double(image.pixelsHigh)/330, column = Int(305*scale)
let ink = (0..<image.pixelsHigh).max { (image.colorAt(x:column,y:$0)?.brightnessComponent ?? 0) < (image.colorAt(x:column,y:$1)?.brightnessComponent ?? 0) }!
precondition(abs(Double(ink)/scale-(100-(top-window.frame.maxY))) < 12,"trail drawn away from its samples (flipped?)")
print("GESTURE_REVIEW_PNG " + image.representation(using:.png,properties:[:])!.base64EncodedString())
window.close()
let pen = TalkPen(); pen.start()
let p = CGEvent(source:nil)!.location
pen.samples = [[now-0.5,p.x-100,p.y-100]]; pen.sample()
let fading = pen.windows; precondition(!fading.isEmpty)
pen.stop(fade:true); pen.start()
precondition(pen.timer != nil,"old fade stopped the new press")
RunLoop.current.run(until:Date().addingTimeInterval(0.4))
precondition(pen.timer != nil && fading.allSatisfy { !$0.isVisible },"restart leaked old panels or lost its timer")
pen.stop(); precondition(pen.timer == nil && pen.windows.isEmpty)
''')
        print(out, flush=True)  # export the VM render; the runner shuts the guest down

    def test_confirmed_gesture_reaches_model_with_screen_privacy(self):
        import io
        import json
        from tests import scratch_dir
        scratch_dir(self)
        for screen, explicit in [('auto', False), ('never', False), ('auto', True)]:
            with self.subTest(screen=screen, explicit=explicit):
                request = json.dumps(dict(front='Fixture', task='snap this left', pointerPath=circle(), point={} if explicit else None))
                with patch.multiple(atticus, licensed=lambda:True, ping=lambda:None, allow_focus=lambda _:None,
                                    front=lambda:('Fixture','Scratch'), osa=lambda *a:'', screens=lambda:[],
                                    selection_context=lambda:'', relevant_rules=lambda _:'', recent=lambda:[],
                                    workflows=lambda *a:'', tool_help=lambda *a,**k:'', profile_context=lambda *a:'',
                                    system_ui_context=lambda:'', start_ai=lambda *a:None,
                                    pref=lambda k,d=None: screen if k=='screen' else d), \
                     patch.object(atticus,'point_context',return_value=('explicit mark' if explicit else '',[])), \
                     patch.object(atticus,'look',return_value=[('fake.jpg','Screen 1')]) as look, \
                     patch.object(atticus,'fast') as fast, \
                     patch.object(atticus,'run',side_effect=RuntimeError('model boundary')) as run, \
                     patch.object(atticus.threading,'Thread'), patch.object(atticus.os,'setpgrp'), \
                     patch.object(atticus.signal,'signal'), patch('sys.argv',['atticus.py','--wait']), \
                     patch('sys.stdin',io.StringIO(request+'\n')), patch.dict(atticus.os.environ, {'ATTICUS_COMMIT':'','ATTICUS_ASK':atticus.DIR}):
                    with self.assertRaisesRegex(RuntimeError, 'model boundary'):
                        atticus.main()
                    fast.assert_not_called()
                    if screen=='never' or explicit:
                        look.assert_not_called()
                    else:
                        self.assertEqual(look.call_args.kwargs['pointer'].kind,'circle')
                    self.assertEqual(bool(run.call_args.args[2]), screen!='never' and not explicit)

    def test_native_annotation_stays_light_for_each_shape(self):
        from tests import run_swift
        swift = (Path(atticus.__file__).parent/'Atticus.swift').read_text()
        start = swift.index('        if a.count > 5, let data = a[5].data(using:.utf8),')
        paint = swift[start:swift.index('            // Reuse Atticus AX naming', start)]
        run_swift(self, 'import AppKit\n' + '''
func annotate(_ kind: String) -> NSBitmapImageRep {
    let mark: [String:Any] = ["kind":kind,"scale":1.0,"numbered":false,
        "path":kind == "circle" ? [[32.0,32.0],[96.0,32.0],[96.0,96.0],[32.0,96.0]] : kind == "line" || kind == "area" ? [[32.0,64.0],[96.0,64.0]] : [],
        "box":kind == "area" ? [32.0,32.0,96.0,96.0] : [],
        "spots":kind == "point" ? [[1.0,64.0,64.0]] : []]
    let a = ["","","","","",String(data:try! JSONSerialization.data(withJSONObject:mark),encoding:.utf8)!]
    let base = CGContext(data:nil,width:128,height:128,bitsPerComponent:8,bytesPerRow:0,space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.premultipliedLast.rawValue)!
    base.setFillColor(NSColor.white.cgColor); base.fill(CGRect(x:0,y:0,width:128,height:128))
    var img = base.makeImage()!
''' + paint + '''
        img = c.makeImage()!
    }
    return NSBitmapImageRep(cgImage:img)
}
for kind in ["circle","point","line","area"] {
    let image = annotate(kind)
    var changed = 0
    for x in 0..<128 { for y in 0..<128 { if image.colorAt(x:x,y:y)!.blueComponent < 0.99 { changed += 1 } } }
    precondition(changed > 0,"missing mark: "+kind)
    precondition(image.colorAt(x:0,y:0)!.blueComponent > 0.99)
    let center = image.colorAt(x:64,y:64)!.blueComponent
    if kind == "area" { precondition(center > 0.8 && center < 0.99) }
    if kind == "circle" || kind == "point" { precondition(center > 0.99,"mark obscures content") }
}
''')

    def test_no_gesture_keeps_instant_path_without_images(self):
        import io
        import json
        from tests import scratch_dir
        scratch_dir(self)
        request = json.dumps(dict(front='Notes', task='open Notes', pointerPath=stroke([(100,100),(102,101),(101,100)])))
        with patch.multiple(atticus, **{name:unittest.mock.DEFAULT for name in
                            ['start_ai','licensed','ping','fast','remember_turn','say','front','stop_claude','allow_focus']}) as mocks, \
             patch.object(atticus,'look') as look, patch.object(atticus.threading,'Thread'), \
             patch.object(atticus.os,'setpgrp'), patch.object(atticus.signal,'signal'), \
             patch('sys.argv',['atticus.py','--wait']), patch('sys.stdin',io.StringIO(request+'\n')), \
             patch.dict(atticus.os.environ, {'ATTICUS_COMMIT':''}):
            mocks['start_ai'].return_value = None
            mocks['licensed'].return_value = True
            mocks['fast'].return_value = 'Opened Notes.'
            atticus.main()
            mocks['fast'].assert_called_once_with('open Notes')
            mocks['front'].assert_not_called()
            look.assert_not_called()
            mocks['say'].assert_called_once_with('✓','Opened Notes.')
