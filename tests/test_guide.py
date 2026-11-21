"""Bounded guided walkthroughs: fake model streams, fake screen changes, real VM WebKit."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import atticus
from tests.test_stream import message

ROOT = Path(__file__).resolve().parents[1]
TARGET = {'pid': 123, 'windowID': '17', 'windowFrame': [0, 0, 800, 600]}
PLAN = ['Open workspace', 'Pick terminal']
FIRST = '[STEPS:2][PLAN: Open workspace | Pick terminal][STEP:1][DRAW:box 20,20 60,60:Workspace] Open the workspace.'
SECOND = '[STEP:2][DRAW:dot 80,80:Terminal] Pick its terminal.'
LAST = 'Your terminal is ready. [DONE]'


class GuideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.joinpath('settings.json').write_text(json.dumps({'speak': True}))
        self.root.joinpath('draw-screens.json').write_text(json.dumps({'target': TARGET, 'screens': {
            '1': {'frame': [0, 0, 800, 600], 'pixels': [800, 600], 'name': 'Fixture'}}}))
        for p in (patch.multiple(atticus, DIR=str(self.root), PREFS=str(self.root/'settings.json')),
                  patch.dict(os.environ, ATTICUS_UI='1', ATTICUS_COMMIT='', ATTICUS_ASK=str(self.root)),
                  patch.object(atticus.threading, 'Thread'), patch.object(atticus.threading, 'Timer')):
            p.start(); self.addCleanup(p.stop)

    def fake(self, text):
        p = Mock(); p.stdin = io.StringIO(); p.ask = ''; p.returncode = 0
        p.stdout = map(json.dumps, message(text) + [{'type': 'result', 'result': text, 'total_cost_usd': .001}])
        return p

    def start(self):
        reply, _, _ = atticus.run('Context: fixture', self.fake(FIRST), request='teach me how to use Orca')
        return reply

    def test_teach_stream_change_checkin_second_step_done(self):
        with patch.object(atticus, 'start_ai', side_effect=[self.fake('[STEPS:2][PLAN:New | Plan]' + SECOND), self.fake(LAST)]) as start, \
             patch.object(atticus, 'look', return_value=[('fixture.jpg', 'Screen 1')]) as look, \
             patch.object(atticus.subprocess, 'run', return_value=Mock(returncode=0, stdout='changed')) as watch, \
             contextlib.redirect_stdout(io.StringIO()) as out:
            reply = self.start()
            final, costs, steps = atticus.follow_walkthrough('teach me how to use Orca', reply, 'opus')
        self.assertEqual(final, 'Your terminal is ready.')
        self.assertEqual(costs, [.001, .001]); self.assertEqual(steps, [])
        self.assertEqual(start.call_args_list, [unittest.mock.call('opus', walkthrough=True), unittest.mock.call('opus', walkthrough=True)])
        self.assertEqual(look.call_count, 2); self.assertEqual(watch.call_count, 2)
        lines = out.getvalue().splitlines()
        events = [json.loads(l[2:]) for l in lines if l.startswith('☷ ')]
        self.assertEqual([(e['index'], e['phase']) for e in events], [(0,'starting'),(0,'waiting'),(0,'checking'),(1,'waiting'),(1,'checking'),(2,'done')])
        self.assertTrue(all(e['plan'] == PLAN for e in events))
        marks = [json.loads(l[2:]) for l in lines if l.startswith('✎ ')]
        self.assertEqual([m['steps'][0]['shapes'][0]['kind'] for m in marks], ['rect', 'pointer'])
        self.assertTrue(all(m['cancelFile'] == str(self.root/'guide-cancelled') for m in marks))
        self.assertFalse(any('[PLAN' in l or '[STEP' in l or '[DONE' in l for l in lines))
        self.assertLess(next(i for i,l in enumerate(lines) if l.startswith('☷ ')), next(i for i,l in enumerate(lines) if l.startswith('✎ ')))
        self.assertEqual(atticus.run.ran, [])
        checkin = atticus.guide_followup(1, 2, PLAN)
        self.assertIn('"Open workspace"', checkin); self.assertIn('"Pick terminal"', checkin)

    def test_timeout_and_dismissal_never_make_another_ask(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel), patch.object(atticus, 'start_ai') as start, \
                 patch.object(atticus, 'look') as look, patch.object(atticus.subprocess, 'run', return_value=Mock(returncode=0,stdout='stopped')), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                reply = self.start()
                if cancel: self.root.joinpath('guide-cancelled').touch()
                atticus.follow_walkthrough('teach me how to use Orca', reply, 'sonnet')
            start.assert_not_called(); look.assert_not_called()
            self.assertIn('"phase": "stopped"', out.getvalue())

    def test_missing_done_is_bounded(self):
        for total in (2, 8):
            with self.subTest(total=total), patch.object(atticus, 'start_ai', side_effect=lambda *a, **k: self.fake(SECOND)) as start, \
                 patch.object(atticus, 'look', return_value=[('fixture.jpg','Screen 1')]) as look, \
                 patch.object(atticus.subprocess, 'run', return_value=Mock(returncode=0,stdout='changed')) as watch, \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                first = f'[STEPS:{total}][PLAN:' + '|'.join(f'Step {i}' for i in range(total)) + ']' + SECOND
                reply, _, _ = atticus.run('Context: fixture', self.fake(first), request='teach me how to use Orca')
                atticus.follow_walkthrough('teach me how to use Orca',reply,'sonnet')
            self.assertEqual(start.call_count,min(total+2,10)-1)
            self.assertEqual(look.call_count,start.call_count); self.assertEqual(watch.call_count,start.call_count)
            self.assertIn('"phase": "stopped"',out.getvalue())

    def test_split_controls_and_malformed_plan(self):
        for size in (1, 7, 40):
            stream = atticus.InlineDrawing()
            for end in range(size, len(FIRST), size):
                text, _ = stream.feed(FIRST[:end])
                self.assertNotIn('[', text)
            text, _ = stream.feed(FIRST, True)
            self.assertEqual(text, ' Open the workspace.' if text.startswith(' ') else 'Open the workspace.')
            self.assertEqual(stream.walkthrough['plan'], PLAN)
        for raw in ('[STEPS:99][PLAN: one | two] text', '[STEPS:2][PLAN: only one] text'):
            stream = atticus.InlineDrawing(); stream.feed(raw, True)
            atticus.run.guide = stream.walkthrough
            with patch.object(atticus.subprocess, 'run') as watch:
                if stream.walkthrough: atticus.follow_walkthrough('teach me', 'text', 'sonnet')
            watch.assert_not_called()

    def test_quick_and_single_action_asks_pay_no_loop(self):
        with contextlib.redirect_stdout(io.StringIO()):
            reply, _, _ = atticus.run('fixture', self.fake('Open Notes from the Dock.'), request='How do I open Notes?')
        self.assertIsNone(atticus.run.guide)
        self.assertEqual(reply, 'Open Notes from the Dock.')

    def test_quoted_protocol_stays_text_in_the_answer(self):
        for text in ('Example:\n```text\n' + FIRST + '\n[DONE]\n```\nThat is the protocol.',
                     'Example:\n~~~text\n' + FIRST + '\n[DONE]\n~~~\nThat is the protocol.',
                     'Example:\n````text\n```\n' + FIRST + '\n[DONE]\n````\nThat is the protocol.',
                     'Use `[DONE]` when finished, or `[DRAW:dot 80,80]` to point.',
                     'Use `` `[DONE]` `` as a literal example.'):
            with self.subTest(text=text), contextlib.redirect_stdout(io.StringIO()) as out:
                reply, _, _ = atticus.run('Context: fixture', self.fake(text), request='Explain this protocol')
            self.assertEqual(reply, text)
            self.assertIsNone(atticus.run.guide)
            self.assertFalse(any(l.startswith(('✎ ', '☷ ')) for l in out.getvalue().splitlines()))
            stream = atticus.InlineDrawing()
            for end in range(1, len(text) + 1):
                _, marks = stream.feed(text[:end])
                self.assertEqual(marks, [])
                self.assertIsNone(stream.walkthrough)
            stream.feed(text + '\n' + FIRST, final=True)
            self.assertEqual(stream.walkthrough['plan'], PLAN, 'real controls after a code example still work')

    def test_protocol_does_not_depend_on_request_language(self):
        for request in ('Enséñame a usar Orca', 'Orcaの使い方を教えて', 'Show me Orca'):
            with self.subTest(request=request), contextlib.redirect_stdout(io.StringIO()):
                raw = FIRST.replace('Open workspace', 'ワークスペースを開く').replace('Pick terminal', 'ターミナルを選ぶ').replace('Open the workspace.', 'ワークスペースを開いてください。')
                atticus.run('Context: fixture', self.fake(raw), request=request)
            self.assertEqual(atticus.run.guide['plan'], ['ワークスペースを開く', 'ターミナルを選ぶ'])

    def test_split_done_stops_and_hides_following_marks(self):
        raw = '完了しました。[DONE][DRAW:dot 80,80] ignored'
        for end in range(1, len(raw) + 1):
            stream = atticus.InlineDrawing()
            text, marks = stream.feed(raw[:end], final=end == len(raw))
            self.assertNotIn('[', text)
            self.assertEqual(marks, [])
        self.assertEqual(text, '完了しました。')
        self.assertTrue(stream.walkthrough['done'])

    def test_checkins_have_no_tools(self):
        with patch.object(atticus.shutil, 'which', return_value='/fixture/claude'), \
             patch.object(atticus.subprocess, 'Popen') as launch, \
             patch.object(atticus.signal, 'signal'), patch.object(atticus.atexit, 'register'):
            process = atticus.start_ai('sonnet', walkthrough=True)
            process.errors.close()
        args = launch.call_args.args[0]
        self.assertEqual(args[args.index('--tools') + 1], '')

    def test_final_only_plan_activates_escape_before_drawing(self):
        process = self.fake(FIRST)
        process.stdout = map(json.dumps,[{'type':'result','result':FIRST,'total_cost_usd':.001}])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            atticus.run('Context: fixture',process,request='Show me Orca')
        lines = out.getvalue().splitlines()
        self.assertLess(next(i for i,l in enumerate(lines) if l.startswith('☷ ')),next(i for i,l in enumerate(lines) if l.startswith('✎ ')))
        self.assertEqual(atticus.run.guide['plan'],PLAN)

    def test_abandoned_streamed_plan_clears_early_escape_state(self):
        process = self.fake('A plain final answer.')
        process.stdout = map(json.dumps, message(FIRST, tool=('read','echo fixture')) +
                            message('A plain final answer.') + [{'type':'result','result':'A plain final answer.','total_cost_usd':.001}])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            atticus.run('Context: fixture', process, request='Show me Orca')
        events = [json.loads(l[2:]) for l in out.getvalue().splitlines() if l.startswith('☷ ')]
        self.assertEqual([e['phase'] for e in events], ['starting','stopped'])
        self.assertIsNone(atticus.run.guide)

    def test_recovery_and_missing_progress_do_not_complete_plan_rows(self):
        recovery = '[STEP:1] The workspace is not open yet; click Workspace.'
        for progress in ('', '[STEP:8]'):
            with self.subTest(progress=progress), patch.object(atticus, 'start_ai', side_effect=[self.fake(recovery),self.fake(progress+'Try Workspace again.'),self.fake(LAST)]) as start, \
                 patch.object(atticus, 'look', return_value=[('fixture.jpg','Screen 1')]), \
                 patch.object(atticus.subprocess, 'run', return_value=Mock(returncode=0,stdout='changed')), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                atticus.follow_walkthrough('teach me how to use Orca',self.start(),'sonnet')
            events = [json.loads(l[2:]) for l in out.getvalue().splitlines() if l.startswith('☷ ')]
            self.assertTrue(all(e['index']==0 for e in events if e['phase'] in ('waiting','checking')))
            self.assertEqual(start.call_count,3)

    def test_dismissal_during_fresh_look_does_not_start_model(self):
        def capture():
            self.root.joinpath('guide-cancelled').touch()
            return [('fixture.jpg', 'Screen 1')]
        with patch.object(atticus, 'look', side_effect=capture), patch.object(atticus, 'start_ai') as start, \
             patch.object(atticus.subprocess, 'run', return_value=Mock(returncode=0, stdout='changed')), \
             contextlib.redirect_stdout(io.StringIO()):
            reply = self.start()
            atticus.follow_walkthrough('teach me how to use Orca', reply, 'sonnet')
        start.assert_not_called()

    def test_screen_never_disables_automatic_watcher_and_checkins(self):
        self.root.joinpath('settings.json').write_text(json.dumps({'screen': 'never'}))
        with patch.object(atticus, 'look') as look, patch.object(atticus.subprocess, 'run') as watch, \
             contextlib.redirect_stdout(io.StringIO()):
            reply = self.start()
            atticus.follow_walkthrough('teach me how to use Orca', reply, 'sonnet')
        look.assert_not_called(); watch.assert_not_called()

    def test_checkin_cannot_make_a_second_call_to_retry_handoff(self):
        handoff = '[agent {"title":"Research Orca","brief":"Read the Orca documentation and summarize it."}]'
        with patch.object(atticus, 'start_ai', return_value=self.fake(handoff)) as start, \
             patch.object(atticus, 'start_claude') as retry, patch.object(atticus, 'stop_claude'), \
             patch.object(atticus, 'look', return_value=[('fixture.jpg','Screen 1')]), \
             patch.object(atticus.subprocess, 'run', return_value=Mock(returncode=0,stdout='changed')), \
             contextlib.redirect_stdout(io.StringIO()):
            atticus.follow_walkthrough('teach me how to use Orca',self.start(),'sonnet')
        self.assertEqual(start.call_count,1); retry.assert_not_called()
        self.assertFalse(atticus.run.ok)

    def test_checkin_broken_input_does_not_restart_with_tools(self):
        process = self.fake('')
        process.stdin = Mock(); process.stdin.write.side_effect = BrokenPipeError
        with patch.object(atticus, 'start_claude') as retry, contextlib.redirect_stdout(io.StringIO()):
            atticus.run('fixture', process, main_only=True, walkthrough=True)
        retry.assert_not_called(); self.assertFalse(atticus.run.ok)

    def test_checkin_rejects_effectful_final_answer_controls(self):
        for control in ('[insert]Changed text', '[replace]Changed text', '[draft]Changed text',
                        '[shortcut fixture]', '[workflow fixture|Do work]', '[replay echo fixture]', '[unlearn]'):
            for result_only in (False, True):
                with self.subTest(control=control, result_only=result_only), contextlib.redirect_stdout(io.StringIO()):
                    process = self.fake(control + ' [DONE]')
                    process.errors = io.StringIO()
                    if result_only:
                        process.stdout = iter([json.dumps({'type':'result','result':control+' [DONE]','total_cost_usd':.001})])
                    reply, _, _ = atticus.run('fixture', process, main_only=True, walkthrough=True)
                self.assertFalse(atticus.run.ok)
                self.assertFalse(atticus.replacement_reply(reply, True)[0])
                self.assertNotIn(control, reply)

    def test_checkin_cannot_steer_agents_or_change_profiles(self):
        for directive in ('[steer {"id":"fixture","text":"Do more work"}]', '[agent-profile {"action":"list"}]'):
            with self.subTest(directive=directive), patch.object(atticus, 'named_agent_action') as action, \
                 patch.object(atticus, 'persist_handoff') as handoff, patch.object(atticus, 'start_claude') as retry, \
                 patch.object(atticus, 'stop_claude'), contextlib.redirect_stdout(io.StringIO()):
                atticus.run('fixture', self.fake(directive), main_only=True, walkthrough=True)
            action.assert_not_called(); handoff.assert_not_called(); retry.assert_not_called()
            self.assertFalse(atticus.run.ok)

    def test_checkin_image_rejection_stops_instead_of_retrying_blind(self):
        process = self.fake('')
        process.errors = io.StringIO()
        process.stdout = map(json.dumps,[{'type':'result','is_error':True,'result':'Multimodal input is not supported.','total_cost_usd':0}])
        shot = self.root/'fixture.jpg'; shot.write_bytes(b'fixture')
        with patch.object(atticus, 'server', return_value={'ANTHROPIC_BASE_URL':'fixture'}), \
             patch.object(atticus, 'models', return_value=[]), \
             patch.object(atticus, 'start_claude') as retry, contextlib.redirect_stdout(io.StringIO()):
            atticus.run('Walkthrough request: fixture',process,[(str(shot),'Screen 1')],main_only=True,walkthrough=True)
        retry.assert_not_called(); self.assertFalse(atticus.run.ok)

    def test_prompt_budget_against_base(self):
        baseline = {'cheapest': 'c59b4f952d7f3dfe8e0b20341f4fa75be79299bcebfdfa09d412d75e845dcbcf',
                    'balanced': '7587c7ad353b11d698f49e44e4e3afbb0ee923972d946bf6174cca2b9f25e90a'}
        # the one charts line; the rest is the a3e1175 prompt with one same-length handoff phrase: "unwatched look-act loops" (Nov 18),
        # and the helper path named once, its flags bare after it (Nov 20)
        graphs = next(l for l in atticus.SYSTEM.splitlines() if l.startswith('Graphs: ')) + '\n'
        for mode, model in [('cheapest','haiku'), ('balanced','haiku'), ('capable','sonnet')]:
            with patch.object(atticus, 'pref', side_effect=lambda k,d:d), patch.object(atticus, 'routing_mode', return_value=mode):
                system = atticus.system_prompt(atticus.ASK_FIRST, model).replace(atticus.ME, '/fixture/atticus.py')
                content = atticus.user_content('Context: fixture' + (atticus.MODEL_OFFER if mode == 'balanced' else ''), request='what time is it')
            self.assertTrue(system.endswith(atticus.READ_ALOUD)); system = system[:-len(atticus.READ_ALOUD)]   # read aloud is on by default (Nov 17, 2026); the base had it off
            if mode in baseline:
                self.assertEqual(system.count(graphs), 1)
                self.assertEqual(hashlib.sha256((system.replace(graphs, '')+json.dumps(content,ensure_ascii=False)).encode()).hexdigest(),baseline[mode])
            else:
                self.assertIn(atticus.WALKTHROUGH,system)
                self.assertLessEqual(len(system)-10025,600)  # b1418a9 with the same helper path and default prefs
            installed = str(Path.home()/'Applications/Atticus.app/Contents/Resources/atticus.py')
            print('PROMPT-FINAL', mode, 'system_utf8_bytes', len(system.encode()),
                  'user_utf8_bytes', len(json.dumps(content, ensure_ascii=False).encode()),
                  'installed_system_utf8_bytes', len(system.replace('/fixture/atticus.py', installed).encode()),
                  'walkthrough_chars', len(atticus.WALKTHROUGH), 'walkthrough_utf8_bytes', len(atticus.WALKTHROUGH.encode()))
        self.assertLessEqual(len(atticus.WALKTHROUGH),600)


@unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'VM only')
class GuideWebKitTests(unittest.TestCase):
    def test_native_change_settle_timeout_and_cancel(self):
        source = (ROOT/'Atticus.swift').read_text()
        watch = source[source.index('    static func guideWatch('):source.index('    // The foreground route:')]
        pixels = source[source.index('    static func pixelsChanged('):source.index('    // Plip ScreenWatcher:')]
        fixture = r'''import Foundation
import Darwin
struct DrawingWindow { let pid:Int32,windowID:String,windowFrame:[Double] }
struct Hands {
    struct Map { let pid:Int32,app:String,window:String,windowFrame:[Double],nodes:[Int],texts:[String],page:String,focused:String,scroll:[Double],windowID:String }
    static var frames:[[UInt8]] = [], samples = 0
    static func fingerprint(_ map:Map,screen:Bool) -> [UInt8] { samples += 1; return frames.count > 1 ? frames.removeFirst() : frames[0] }
__PIXELS__
__WATCH__
}
let target = DrawingWindow(pid:1,windowID:"1",windowFrame:[0,0,800,600])
let cancel = NSTemporaryDirectory()+UUID().uuidString
Hands.frames = [[0,0],[8,8],[8,8]]
precondition(Hands.guideWatch(target,cancel:cancel,timeout:3))
precondition(Hands.samples == 3)
Hands.frames = [[0,0]]; Hands.samples = 0
precondition(!Hands.guideWatch(target,cancel:cancel,timeout:0.01))
precondition(Hands.samples == 1)
try! "cancelled".write(toFile:cancel,atomically:true,encoding:.utf8)
Hands.samples = 0
precondition(!Hands.guideWatch(target,cancel:cancel,timeout:3))
precondition(Hands.samples == 0)
try! FileManager.default.removeItem(atPath:cancel)
Hands.frames = [[0,0],[8,8],[8,8]]; Hands.samples = 0
DispatchQueue.global().asyncAfter(deadline:.now()+0.1) { try! "cancelled".write(toFile:cancel,atomically:true,encoding:.utf8) }
precondition(!Hands.guideWatch(target,cancel:cancel,timeout:3))
precondition(Hands.samples == 1, "captured after cancellation during the sampling delay")
try! FileManager.default.removeItem(atPath:cancel)
Hands.frames = [[]]
precondition(!Hands.guideWatch(target,cancel:cancel,timeout:3))
let dir = NSTemporaryDirectory()+UUID().uuidString; try! FileManager.default.createDirectory(atPath:dir,withIntermediateDirectories:true)
try! "clicked".write(toFile:dir+"/guide-clicked",atomically:true,encoding:.utf8)
Hands.frames = [[0,0]]; Hands.samples = 0
precondition(Hands.guideWatch(target,cancel:dir+"/guide-cancelled",timeout:3),"A click on the waiting mark did not count as the change")
precondition(Hands.samples == 3 && !FileManager.default.fileExists(atPath:dir+"/guide-clicked"),"The click was not consumed once the screen settled")
try! FileManager.default.removeItem(atPath:dir)
print("change, settle, timeout, cancel, unavailable, click: OK")
'''.replace('__PIXELS__',pixels).replace('__WATCH__',watch)
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'main.swift'; binary=Path(tmp)/'fixture'; src.write_text(fixture)
            built=subprocess.run(['swiftc',str(src),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_reply_during_the_wait_ends_the_wait_not_the_run_and_esc_still_cancels(self):
        source = (ROOT/'Atticus.swift').read_text()
        release = source[source.index('    func releaseWalkthrough()'):source.index('    func cancel() {')]
        start = source[source.index('    func start(dictate: Bool'):source.index('        dictating = dictate   // hush invalidates')]
        self.assertLess(start.index('releaseWalkthrough()'), start.index('hush(keepReply: true)'))
        escape = source[source.index('    func escape() {'):source.index('    func hush() {')]
        self.assertIn('walkthroughActive = false; cancel()', escape)
        fixture = r'''import Foundation
final class Proc { var stopped = false; func terminate() { stopped = true } }
struct Request { let cancelFile: String? }
final class Drawing { var request: Request? }
final class Box {
    var walkthroughWaiting = false, busy = true, proc: Proc? = Proc()
    let drawing = Drawing()
__RELEASE__
    func hush() { proc?.terminate(); proc = nil }
}
let dir = NSTemporaryDirectory()+UUID().uuidString; try! FileManager.default.createDirectory(atPath:dir,withIntermediateDirectories:true)
let file = dir+"/guide-cancelled"
let waiting = Box(); waiting.walkthroughWaiting = true; waiting.drawing.request = Request(cancelFile:file); let run = waiting.proc!
waiting.releaseWalkthrough(); waiting.hush()
precondition(!run.stopped && !waiting.busy && FileManager.default.fileExists(atPath:file), "a reply during the wait killed the run")
try! FileManager.default.removeItem(atPath:file)
let working = Box(); working.drawing.request = Request(cancelFile:file); let busyRun = working.proc!
working.releaseWalkthrough(); working.hush()
precondition(busyRun.stopped && !FileManager.default.fileExists(atPath:file), "a reply outside the wait left the run going")
print("OK")
'''.replace('__RELEASE__', release)
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'main.swift'; binary=Path(tmp)/'fixture'; src.write_text(fixture)
            built=subprocess.run(['swiftc',str(src),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_checklist_in_existing_box_and_screenshot(self):
        from tests.test_shelf_page import HARNESS
        harness = HARNESS.replace('cfg.userContentController.add(h, name: "agents")', 'cfg.userContentController.add(h, name: "c"); cfg.userContentController.add(h, name: "h")')
        harness = harness.replace('?["action"] as? String == "ready"', '?["ready"] != nil')
        harness = harness.replace('print(String(data: out, encoding: .utf8)!); exit(0)', '''
                self.web.takeSnapshot(with:nil) { image, error in
                    guard let image, let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data:tiff), let png = bitmap.representation(using:.png,properties:[:]) else { print("snapshot failed"); exit(1) }
                    print("GUIDE_SHOT " + png.base64EncodedString())
                    print(String(data:out,encoding:.utf8)!); exit(0)
                }''')
        script = r'''
ui.listen(true); ui.words('Teach me how to use Orca'); ui.think();
ui.walkthrough({plan:['Open workspace','Pick terminal'],index:0,phase:'starting'});
const starting=document.querySelectorAll('.steps .step').length;
ui.line('✓ Open the workspace.');
ui.walkthrough({plan:['Open workspace','Pick terminal'],index:0,phase:'waiting'});
const first=[...document.querySelectorAll('.steps .step')].map(e=>[e.textContent,e.className]);
ui.walkthrough({plan:['Open workspace','Pick terminal'],index:0,phase:'checking'});
const checking=[...document.querySelectorAll('.steps .step')].map(e=>[e.textContent,e.className]);
ui.line('… Pick its terminal.'); ui.line('✓ Pick its terminal.');
ui.walkthrough({plan:['Open workspace','Pick terminal'],index:1,phase:'waiting'});
const second=[...document.querySelectorAll('.steps .step')].map(e=>[e.textContent,e.className]);
ui.walkthrough({plan:['Open workspace','Pick terminal'],index:2,phase:'done'});
const cleared=document.querySelectorAll('.steps .step').length===0;
ui.walkthrough({plan:['Open workspace','Pick terminal'],index:1,phase:'waiting'});
for(const a of document.getAnimations())if(a.effect.getTiming().iterations!==Infinity)a.finish();
return {starting,first,checking,second,cleared,clocks:document.querySelectorAll('.elapsed').length,answer:document.querySelector('.a').textContent};
'''
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); page=root/'ui.html'; src=root/'main.swift'; binary=root/'fixture'
            page.write_text((ROOT/'ui/ui.html').read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/',(ROOT/'ui/orbs.js').read_text()))
            src.write_text(harness)
            built=subprocess.run(['swiftc',str(src),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            got=subprocess.run([str(binary),str(page),script],capture_output=True,text=True,timeout=30)
        self.assertEqual(got.returncode,0,got.stdout[-1000:]+got.stderr)
        rows=got.stdout.splitlines(); value=json.loads(rows[-1])['result']
        self.assertEqual(value['first'],[['Open workspace','step live'],['Pick terminal','step']])
        self.assertEqual(value['starting'],2)
        self.assertEqual(value['checking'],value['first'])
        self.assertEqual(value['second'],[['Open workspace','step done'],['Pick terminal','step live']])
        self.assertTrue(value['cleared']); self.assertEqual(value['clocks'],1); self.assertIn('terminal',value['answer'])
        print(next(row for row in rows if row.startswith('GUIDE_SHOT ')),flush=True)


if __name__ == '__main__': unittest.main()
