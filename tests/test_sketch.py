"""Offline plan/drawer fixtures; native captures run only in the VM."""
import copy
import io
import json
import math
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from tests import scratch_dir
import atticus

ROOT = Path(__file__).resolve().parents[1]

def label(x, y, text, color='white'):
    return {'kind':'label','at':[x,y],'text':text,'color':color}

EXAMPLES = {
    'cell': [
        {'kind':'circle','rect':[120,55,350,260],'color':'blue','fill':True},
        {'kind':'circle','rect':[235,115,110,110],'color':'yellow','fill':True},
        {'kind':'circle','rect':[271,150,35,35],'color':'yellow','fill':True},
        {'kind':'circle','rect':[160,125,48,26],'color':'green','fill':True},
        {'kind':'circle','rect':[365,225,48,26],'color':'green','fill':True},
        {'kind':'path','points':[[167,138],[177,131],[185,145],[194,133],[202,139]],'color':'green'},
        {'kind':'path','points':[[372,238],[382,231],[390,245],[399,233],[407,239]],'color':'green'},
        {'kind':'line','points':[[295,115],[295,86]],'color':'yellow'},
        {'kind':'line','points':[[415,240],[510,240]],'color':'green'},
        {'kind':'line','points':[[171,277],[110,318]],'color':'blue'},
        label(295,70,'Nucleus','yellow'), label(510,262,'Mitochondria','green'),
        label(100,337,'Membrane','blue'), label(290,275,'Cytoplasm','blue')],
    'gear': [
        {'kind':'path','points':[[284,75],[316,75],[320,111],[280,111],[284,75]],'fill':True,'color':'blue','around':{'n':12,'center':[300,190]}},
        {'kind':'circle','rect':[210,100,180,180],'fill':True,'color':'blue'},
        {'kind':'line','points':[[300,155],[300,108]],'color':'green','around':{'n':6,'center':[300,190]}},
        {'kind':'circle','rect':[265,155,70,70],'color':'yellow','fill':True},
        {'kind':'line','points':[[364,80],[438,62]],'color':'blue'},
        {'kind':'line','points':[[335,190],[465,190]],'color':'yellow'},
        label(475,62,'12 teeth','blue'), label(490,190,'Hub','yellow'), label(300,333,'Evenly spaced spokes','green')],
    'flowchart': [
        {'kind':'rect','rect':[50,130,130,80],'fill':True,'color':'blue','repeat':{'n':3,'step':[185,0]}},
        {'kind':'arrow','points':[[190,170],[225,170]],'color':'white','repeat':{'n':2,'step':[185,0]}},
        label(115,170,'Input'),label(300,170,'Validate'),label(485,170,'Save'),
        {'kind':'path','points':[[300,220],[300,285],[115,285]],'color':'yellow'},
        {'kind':'arrow','points':[[115,285],[115,220]],'color':'yellow'},
        label(220,310,'Try again if invalid','yellow')]
}
PYTHAGORAS = [   # a stepped plan: the triangle, a square on each leg, the square on the long side
    {'kind':'path','points':[[250,230],[346,230],[250,158],[250,230]],'fill':True,'color':'blue','step':1},
    {'kind':'path','points':[[250,216],[264,216],[264,230]],'color':'white','step':1},
    {'kind':'line','points':[[250,230],[170,290]],'color':'white','step':1},
    label(130,305,'Right angle') | {'step':1},
    {'kind':'rect','rect':[178,158,72,72],'fill':True,'color':'green','step':2},
    {'kind':'rect','rect':[250,230,96,96],'fill':True,'color':'green','step':2},
    label(214,194,'a²','green') | {'step':2}, label(298,278,'b²','green') | {'step':2},
    {'kind':'path','points':[[250,158],[346,230],[418,134],[322,62],[250,158]],'fill':True,'color':'yellow','step':3},
    label(334,146,'c²','yellow') | {'step':3}, label(500,300,'a² + b² = c²','yellow') | {'step':3}]
PYTHAGORAS_PLAN = {'title':'Pythagorean theorem','draw':'Right triangle with a square on each side',
                   'steps':['A right triangle','A square on each leg','The big square equals both']}

class SketchTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch_dir(self)
        self.env = patch.dict(os.environ, {'ATTICUS_ASK':str(self.root), 'ATTICUS_UI':'1'})
        self.env.start(); self.addCleanup(self.env.stop)

    def test_plan_never_leaks_or_waits_for_a_caption(self):
        raw = '[EXPLAIN:{"title":"A cell","draw":"Cutaway, label nucleus."}] The cell stores instructions.'
        stream = atticus.InlineDrawing()
        for n in range(1,len(raw)):
            text, _ = stream.feed(raw[:n])
            self.assertNotIn('[',text)
        text, _ = stream.feed(raw,final=True)
        self.assertEqual(text.strip(),'The cell stores instructions.')
        self.assertEqual(stream.sketch_plan['title'],'A cell')
        quoted = '`'+raw.split(' The')[0]+'`'
        self.assertEqual(atticus.InlineDrawing().feed(quoted,True)[0],quoted)
        bad = atticus.InlineDrawing()
        self.assertEqual(bad.feed('[EXPLAIN:{"draw":3}] Hello.',True)[0], ' Hello.')
        self.assertIsNone(bad.sketch_plan)

    def test_stepped_plan_cues_its_steps_where_the_sentences_reach_them(self):
        raw = ('[EXPLAIN:'+json.dumps(PYTHAGORAS_PLAN)+'] Here is a right triangle. [EXPLAIN:{"step":2}]Put a square on each leg. '
               '[EXPLAIN:{"step":2}][EXPLAIN:{"step":9}][EXPLAIN:{"step":3}]The square on the long side holds as much as both.')
        stream, events = atticus.InlineDrawing(), []
        for n in range(1,len(raw)+1):
            text, drawn = stream.feed(raw[:n],n == len(raw))
            self.assertNotIn('[',text)
            events += drawn
        self.assertEqual(stream.sketch_plan,PYTHAGORAS_PLAN)
        self.assertEqual([p for _, p in events],[{'guide':stream.sketch_guide,'cue':1},{'guide':stream.sketch_guide,'cue':2}])   # a repeat or a step past the plan is ignored
        self.assertEqual(events[0][0].strip(),'Here is a right triangle.')
        self.assertTrue(events[1][0].strip().endswith('Put a square on each leg.'))
        self.assertTrue(text.strip().endswith('as much as both.'))
        one = atticus.InlineDrawing()
        self.assertEqual(one.feed('[EXPLAIN:{"title":"A cell","draw":"A cell","steps":["Only one"]}] A cell. [EXPLAIN:{"step":2}]Done.',True),(' A cell. Done.',[]))
        self.assertEqual(one.sketch_plan,{'title':'A cell','draw':'A cell'})   # bad steps keep the one-shot card

    def test_stepped_sketch_splits_its_parts_by_step(self):
        def payload(plan, parts):
            with patch.object(atticus,'screens',return_value=[('Fixture',0,0,1024,768,True)]):
                return atticus.SketchDrawing(plan,'g-sketch').payload(copy.deepcopy(parts))
        full = payload(PYTHAGORAS_PLAN,PYTHAGORAS)
        self.assertEqual([s['say'] for s in full['steps']],PYTHAGORAS_PLAN['steps'])
        self.assertEqual([len(s['shapes']) for s in full['steps']],[4,4,3])
        self.assertEqual(full['guide'],'g-sketch')
        self.assertFalse(any('step' in shape for s in full['steps'] for shape in s['shapes']))
        flat = lambda p: [shape for s in p['steps'] for shape in s['shapes']]
        partial = payload(PYTHAGORAS_PLAN,PYTHAGORAS[:5])
        self.assertEqual([len(s['shapes']) for s in partial['steps']],[4,1,0])   # every caption from the start, ink as it comes
        self.assertEqual(flat(full)[:5],flat(partial))
        late = payload(PYTHAGORAS_PLAN,PYTHAGORAS[:5]+[PYTHAGORAS[3]])
        self.assertEqual([len(s['shapes']) for s in late['steps']],[4,2,0])   # a part that goes back a step stays later: earlier ink is a prefix
        past = payload(PYTHAGORAS_PLAN,[p | {'step':6} if p['step'] == 3 else p for p in PYTHAGORAS])
        self.assertEqual([len(s['shapes']) for s in past['steps']],[4,4,3])
        one = payload({'title':'A cell','draw':'A cell'},EXAMPLES['cell'])
        self.assertEqual([(s['say'],len(s['shapes'])) for s in one['steps']],[('A cell',len(EXAMPLES['cell']))])
        self.assertEqual(payload({'title':'A cell','draw':'A cell'},PYTHAGORAS)['steps'][0]['shapes'],flat(full))   # steps without captions: one card

    def test_whole_parts_only_and_copy_geometry(self):
        for parts in EXAMPLES.values():
            raw = json.dumps({'parts':parts})
            self.assertEqual(atticus.sketch_parts(raw),parts)
            for n in range(len(raw)):
                partial = atticus.sketch_parts(raw[:n])
                self.assertEqual(partial,parts[:len(partial)])
            self.assertLessEqual(len(atticus.sketch_shapes(parts)),160)
        row = atticus.sketch_shapes(EXAMPLES['flowchart'][:1])
        self.assertEqual([p['rect'][0] for p in row],[50,235,420])
        ring = atticus.sketch_shapes([{'kind':'line','points':[[300,100],[300,150]],'around':{'n':4,'center':[300,190]}}])
        self.assertEqual(len(ring),4)
        self.assertAlmostEqual(ring[1]['points'][0][0],390)
        self.assertAlmostEqual(ring[1]['points'][0][1],190)

    def test_leaders_end_on_their_part(self):
        gear = atticus.sketch_shapes(EXAMPLES['gear'])
        leader = next(s for s in gear if s['kind'] == 'line' and s['points'][1] == [438,62])
        teeth = gear[:12]
        self.assertTrue(any(min(math.dist(leader['points'][0], p) for p in self.dense(t)) < 1 for t in teeth))
        self.assertEqual(leader['points'][1],[438,62])
        spokes = [s for s in gear if s['color'] == 'green' and s['kind'] == 'line']
        self.assertEqual(spokes, [s for s in atticus.sketch_shapes(EXAMPLES['gear'][:3])[13:]])   # spokes start inside the body: untouched
        cell = atticus.sketch_shapes(EXAMPLES['cell'])
        self.assertEqual([s['points'] for s in cell if s['kind'] == 'line'], [s['points'] for s in EXAMPLES['cell'] if s['kind'] == 'line'])
        far = atticus.sketch_shapes([{'kind':'circle','rect':[100,100,50,50]},{'kind':'line','points':[[400,300],[500,300]]}])
        self.assertEqual(far[1]['points'],[[400,300],[500,300]])   # a line nowhere near any part is not a leader
        streamed = atticus.sketch_shapes(EXAMPLES['gear'][:5])
        self.assertEqual(streamed, gear[:len(streamed)])   # a later part never moves an earlier leader

    def dense(self, shape):
        line, _ = atticus.sketch_outline(shape)
        return [[a[0]+(b[0]-a[0])*k/50, a[1]+(b[1]-a[1])*k/50] for a, b in zip(line, line[1:]) for k in range(51)]

    def test_rejects_invalid_and_unbounded_geometry(self):
        cases = [[], [{'kind':'scene'}], [label(20,20,'x') | {'repeat':{'n':2,'step':[1,1]}}],
                 [{'kind':'circle','rect':[1,1,2,2],'repeat':{'n':True,'step':[1,1]}}],
                 [{'kind':'circle','rect':[1,1,2,2],'repeat':{'n':32,'step':[1,1]},'around':{'n':36,'center':[300,190]}}],
                 [{'kind':'line','points':[[float('nan'),1],[1,1]]}],
                 [{'kind':'circle','rect':[590,370,50,50]}]]
        for parts in cases:
            with self.subTest(parts=parts), self.assertRaises(ValueError): atticus.sketch_shapes(parts)
        good = EXAMPLES['flowchart'][2]
        self.assertEqual(atticus.sketch_shapes([cases[-1][0], good, {'kind':'scene'}]), atticus.sketch_shapes([good]))   # one slip never costs the picture

    def test_fenced_reply_still_streams(self):
        raw = '```json\n' + json.dumps({'parts':EXAMPLES['cell']}) + '\n```'
        self.assertEqual(atticus.sketch_parts(raw), EXAMPLES['cell'])

    def fake_draw(self, parts, *, hold=None):
        raw = json.dumps({'parts':parts})
        class Process:
            stdin = io.StringIO()
            errors = io.StringIO()
            def wait(self, **kw): return 0
        p = Process()
        def lines():
            yield json.dumps({'type':'stream_event','event':{'delta':{'type':'text_delta','text':raw[:raw.index('},',raw.index('},')+2)+2]}}})
            if hold: hold.wait(3)
            yield json.dumps({'type':'result','result':raw,'total_cost_usd':0.001})
        p.stdout = lines()
        return p

    def test_fake_model_progress_and_voice_independence(self):
        gate, output = threading.Event(), []
        worker = atticus.SketchDrawing({'title':'Cell','draw':'A cell cutaway'})
        p = self.fake_draw(EXAMPLES['cell'],hold=gate)
        # Accelerate only the progress clock: the model is still genuinely blocked on the fixture gate.
        clock = iter(range(1000))
        with patch.object(atticus,'start_claude',return_value=p) as start, patch.object(atticus,'stop_claude'), \
             patch.object(atticus,'screens',return_value=[('Fixture',0,0,1024,768,True)]), \
             patch.object(atticus.time,'monotonic',side_effect=lambda:next(clock)), patch.object(atticus,'say',side_effect=lambda *x:output.append(x)):
            worker.start()
            for _ in range(100):
                if output: break
                threading.Event().wait(.01)
            self.assertTrue(output,'no partial picture while the model is still streaming')
            self.assertTrue(worker.thread.is_alive())
            atticus.say('♬','The nucleus stores instructions.')
            self.assertEqual(output[-1][0],'♬')
            gate.set(); worker.thread.join(3)
            self.assertFalse(worker.thread.is_alive())
        start.assert_called_once_with('haiku',sketch=True)
        pictures = [json.loads(x[1]) for x in output if x[0]=='✎']
        self.assertLess(len(pictures[0]['steps'][0]['shapes']),len(pictures[-1]['steps'][0]['shapes']))
        self.assertEqual(pictures[0]['sketch'],pictures[-1]['sketch'])

    def test_cancelled_worker_cannot_reopen_picture(self):
        worker = atticus.SketchDrawing({'title':'Cell','draw':'A cell'})
        (self.root/'guide-cancelled').touch()
        with patch.object(atticus,'start_claude') as start:
            worker.draw()
        start.assert_not_called()


@unittest.skipUnless(os.environ.get('ATTICUS_VM') == '1', 'native drawings run only in the VM')
class NativeSketchTests(unittest.TestCase):
    def test_three_fake_model_sketches_and_progressive_ink(self):
        from tests import run_swift, swift_motion
        from tests.test_drawing_math_page import MATH_STUB
        source = (ROOT/'Atticus.swift').read_text()
        drawing = MATH_STUB + swift_motion(source) + source[source.index('// Screen drawings use Quartz'):source.index('// The box can take typing')]
        fixtures = {name:atticus.sketch_shapes(atticus.sketch_parts(json.dumps({'parts':parts}))) for name,parts in EXAMPLES.items()}
        encoded = json.dumps(json.dumps(fixtures))
        out = run_swift(self, 'import Cocoa\nfunc applySharing(_ window: NSWindow) {}\n'+drawing+'''
NSApplication.shared.setActivationPolicy(.prohibited)
let examples = try! JSONDecoder().decode([String:[DrawingShape]].self,from:Data('''+encoded+'''.utf8))
func shot(_ name: String, _ view: DrawingView) {
    let image = NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:1200,pixelsHigh:760,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    let context = NSGraphicsContext(bitmapImageRep:image)!.cgContext
    context.setFillColor(NSColor(calibratedWhite:0.22,alpha:1).cgColor); context.fill(CGRect(x:0,y:0,width:1200,height:760))
    context.scaleBy(x:2,y:2); context.translateBy(x:0,y:380); context.scaleBy(x:1,y:-1)
    view.layer!.render(in:context)
    print("SKETCH_PNG \\(name) \\(image.representation(using:.png,properties:[:])!.base64EncodedString())")
}
for name in examples.keys.sorted() {
    let shapes = examples[name]!, frame = CGRect(x:0,y:0,width:600,height:380)
    let before = DrawingView(frame:frame)
    before.render(shapes,animate:false,previous:nil)
    shot(name+"-before",before)
    let view = DrawingView(frame:frame)
    view.renderSketch(Array(shapes.prefix(2)),frame:frame,animate:false)
    let original = view.layer!.sublayers!
    shot(name+"-partial",view)
    view.renderSketch(shapes,frame:frame,previous:2,animate:false)
    precondition(zip(original,view.layer!.sublayers!).allSatisfy { $0 === $1 },"progress redrew old ink")
    precondition(view.deferredLabels.isEmpty,"labels clipped")
    precondition(view.hits.count == shapes.count,"a primitive or copy vanished")
    precondition(view.hits.last!.shape == shapes.count-1,"progress lost original shape indices")
    shot(name+"-after",view)
}
print("three native sketches verified")
''',timeout=30)
        self.assertIn('three native sketches verified',out)
        self.assertEqual(out.count('SKETCH_PNG '),9)
        print(out,flush=True)

    def test_stepped_card_follows_the_voice_and_one_shot_has_no_steps(self):
        from tests import run_swift, swift_motion
        from tests.test_drawing_math_page import MATH_STUB
        from tests.test_guidecard import dismiss_vm_consent
        dismiss_vm_consent(self)
        source = (ROOT/'Atticus.swift').read_text()
        drawing = MATH_STUB + swift_motion(source) + source[source.index('// Screen drawings use Quartz'):source.index('// The box can take typing')]
        one = {'title':'Pythagorean theorem','draw':PYTHAGORAS_PLAN['draw']}
        def payload(plan, parts, guide):
            with patch.dict(os.environ,{'ATTICUS_ASK':str(scratch_dir(self))}), patch.object(atticus,'screens',return_value=[('Fixture',0,0,1024,768,True)]):
                return atticus.SketchDrawing(plan,guide).payload(copy.deepcopy(parts))
        payloads = {'before':payload(one,PYTHAGORAS,'before-sketch'), 'partial':payload(PYTHAGORAS_PLAN,PYTHAGORAS[:4],'g-sketch'),
                    'full':payload(PYTHAGORAS_PLAN,PYTHAGORAS,'g-sketch'), 'late-partial':payload(PYTHAGORAS_PLAN,PYTHAGORAS[:5],'late-sketch'),
                    'late':payload(PYTHAGORAS_PLAN,PYTHAGORAS,'late-sketch'), 'cell':payload({'title':'A cell','draw':'A cell'},EXAMPLES['cell'],'cell-sketch')}
        frame = payloads['full']['sketch']
        out = run_swift(self, 'import Cocoa\nfunc applySharing(_ window: NSWindow) {}\n'+drawing+'''
let app = NSApplication.shared; app.setActivationPolicy(.accessory)
let payloads = try! JSONSerialization.jsonObject(with:Data('''+json.dumps(json.dumps(payloads))+'''.utf8)) as! [String:Any]
func data(_ key: String) -> Data { try! JSONSerialization.data(withJSONObject:payloads[key]!) }
func pump(_ seconds: Double) { RunLoop.current.run(until:Date().addingTimeInterval(seconds)) }
func shot(_ name: String) {
    pump(7)   // one pen draws the parts in turn: wait for the last
    let file = NSTemporaryDirectory()+name+".png", p = Process(); p.executableURL = URL(fileURLWithPath:"/usr/sbin/screencapture"); p.arguments = ["-x",file]
    try! p.run(); p.waitUntilExit()
    print("SKETCH_SHOT \\(name) \\(try! Data(contentsOf:URL(fileURLWithPath:file)).base64EncodedString())")
}
let drawing = ScreenDrawing()
func card() -> [NSView] { drawing.calloutPanel?.contentView?.subviews ?? [] }
func texts() -> [String] { card().compactMap { ($0 as? NSTextField)?.stringValue } }
func buttons() -> [String] { card().compactMap { ($0 as? NSButton)?.title }.filter { ["Back","Next","Done"].contains($0) } }
func view() -> DrawingView { drawing.panels.compactMap { $0.contentView as? DrawingView }.first { $0.sketchFrame != nil }! }
func ink() -> [ObjectIdentifier] { (view().layer?.sublayers ?? []).map(ObjectIdentifier.init) }
drawing.driven = true
precondition(drawing.update(data("before")) && view().sketchShown == 11 && texts().isEmpty && buttons() == ["Done"],"today's card changed: \\(texts()) \\(buttons())")
shot("pythagoras-before")
drawing.clear(); drawing.driven = true
precondition(drawing.update(data("partial")) && drawing.index == 0 && view().sketchShown == 4,"the first step did not show")
precondition(texts() == ["Step 1 of 3"] && Set(buttons()) == ["Next","Back"],"step controls: \\(texts()) \\(buttons())")
precondition(drawing.update(data("full")) && drawing.index == 0 && view().sketchShown == 4,"a later step's ink showed before the voice reached it")
let first = ink()
shot("pythagoras-step1")
drawing.reveal(1,guide:"g-sketch")
precondition(drawing.index == 1 && view().sketchShown == 8 && texts() == ["Step 2 of 3"],"the voice did not bring in step 2")
precondition(Array(ink().prefix(first.count)) == first,"a step on redrew the earlier steps")
shot("pythagoras-step2")
drawing.reveal(2,guide:"g-sketch")
precondition(drawing.index == 2 && view().sketchShown == 11 && texts() == ["Step 3 of 3"] && Set(buttons()) == ["Done","Back"],"step 3: \\(texts()) \\(buttons())")
shot("pythagoras-step3")
drawing.back(); precondition(drawing.index == 1 && drawing.manual && view().sketchShown == 8 && texts() == ["Step 2 of 3"],"Back did not take the last step off")
shot("pythagoras-back")
drawing.reveal(2,guide:"g-sketch"); precondition(drawing.index == 1,"the voice stepped on after Back")
drawing.next(); precondition(drawing.index == 2 && view().sketchShown == 11,"Next did not bring the step back")
var picked = ""; drawing.picked = { _, words in picked = words }
let k = '''+str(frame[2]/600)+''', origin = CGPoint(x:'''+str(frame[0])+''',y:'''+str(frame[1])+''')
drawing.pick(CGPoint(x:origin.x+186*k,y:origin.y+166*k))
precondition(picked.hasPrefix("rect in step 2 of 3: A square on each leg"),"a click named the wrong part: \\(picked)")
drawing.picked = nil; drawing.next(); precondition(!drawing.active,"Done did not close the card")
drawing.reveal(1,guide:"late-sketch"); drawing.driven = true
precondition(drawing.update(data("late-partial")) && drawing.index == 1 && view().sketchShown == 5,"a card the voice was ahead of did not open at its step")
precondition(drawing.update(data("late")) && drawing.index == 1 && view().sketchShown == 8,"the shown step's late ink did not draw")
drawing.clear(); drawing.reveal(2,guide:"late-sketch")
precondition(drawing.replay() && drawing.index == 0,"show again opened at a step an earlier cue reached")
drawing.clear(); drawing.driven = true
precondition(drawing.update(data("cell")) && texts().isEmpty && buttons() == ["Done"],"a one-shot card got step controls: \\(texts()) \\(buttons())")
shot("cell-oneshot")
drawing.clear()
print("stepped sketch verified")
''',timeout=60)
        self.assertIn('stepped sketch verified',out)
        self.assertEqual(out.count('SKETCH_SHOT '),6)
        print(out,flush=True)
