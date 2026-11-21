"""Offline stronger-model retry and real VM WebKit card checks."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import atticus
from tests.test_shelf_page import HARNESS, ROOT


class ModelUpgradeTests(unittest.TestCase):
    def test_retry_telemetry_finishes_once_after_the_user_choice(self):
        from tests import scratch_dir
        from unittest.mock import Mock
        root = scratch_dir(self)
        for choice in ('r', 'n'):
            events, pending = [], []
            def attempt(*args, **kwargs):
                brain.ok = brain.call_count > 1
                brain.ran = ['observed fixture'] * brain.call_count
                return ('Better answer.' if brain.ok else 'First answer.', .01, ['Read'])
            brain = Mock(side_effect=attempt)
            brain.ok = False; brain.ran = brain.cmds = brain.observed = []
            brain.handoff = brain.guide = None; brain.handoffs = []; brain.work = False; brain.why = ''
            def choose(*args):
                pending.append(list(events))
                return choice
            with patch.dict(atticus.TURN, {}, clear=True), \
                 patch.multiple(atticus, licensed=lambda:True,ping=lambda:None,fast=lambda _:None,
                    front=lambda:('Fixture','Scratch'),osa=lambda *a:'',screens=lambda:[],
                    describe=lambda *a:'',me_line=lambda:'',selection_context=lambda:'',
                    relevant_rules=lambda _:'',recent=lambda:[],workflows=lambda *a:'',
                    screen_for=lambda *a:None,wait_commit=lambda:True,run=brain,start_ai=lambda *a:None,
                    remember_turn=lambda *a,**k:None,restore_focus=lambda *a:None,
                    remember_workflow=lambda task,reply,*a:(reply,False),learn=lambda *a:False,tip=lambda *a:None,
                    main_model=lambda:'haiku',upgrade_needed=lambda *a,**k:True,upgrade_available=lambda *a:True,
                    ask_user=choose,posthog=lambda name,data: events.append(data) if name=='ask_done' else None), \
                 patch.object(atticus.threading,'Thread'), \
                 patch.dict(os.environ,{'ATTICUS_UI':'1','ATTICUS_ASK':str(root),'ATTICUS_COMMIT':''}), \
                 patch('sys.argv',['atticus.py','Explain the fixture']), contextlib.redirect_stdout(io.StringIO()):
                atticus.main()
                self.assertEqual(pending, [[]], 'provisional answer finalized telemetry while retry was still offered')
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]['model'], 'opus' if choice=='r' else 'sonnet')
                self.assertEqual(events[0]['status'], 'ok' if choice=='r' else 'failed')
                self.assertEqual(events[0]['escalated'], choice=='r')
                self.assertEqual(events[0]['steps'], 2 if choice=='r' else 1)

    def test_general_signals_and_independent_preference(self):
        with patch.dict(os.environ, {'ATTICUS_UI': '1'}), patch.object(atticus, 'client', return_value='claude'), \
             patch.object(atticus, 'server', return_value={}), patch.object(atticus, 'pref', side_effect=lambda k, d: False if k == 'tips' else d), \
             patch.dict(atticus.TURN, {}, clear=True), patch.object(atticus.run, 'ok', True, create=True), \
             patch.object(atticus.run, 'why', '', create=True), \
             patch.object(atticus.run, 'work', False, create=True), patch.object(atticus.run, 'ran', [], create=True), \
             patch.object(atticus.run, 'observed', [], create=True):
            self.assertFalse(atticus.upgrade_needed('Explain division', 'Here is how.', 'haiku'))
            with patch.object(atticus, 'upgrade_available', side_effect=AssertionError('no preference reads for a successful answer')), \
                 patch.object(atticus, 'plain', side_effect=AssertionError('no normalization without a previous ask')):
                self.assertFalse(atticus.upgrade_needed('Explain division', 'Here is how.', 'haiku'))
            self.assertTrue(atticus.upgrade_needed('Explain division', 'I cannot finish this.', 'haiku'))
            with patch.object(atticus.run, 'ok', False):
                self.assertTrue(atticus.upgrade_needed('Explain division', 'No result', 'haiku'))
                self.assertFalse(atticus.upgrade_needed('Explain division', 'No result', 'opus'))
                with patch.object(atticus.run, 'why', 'rate_limited'):
                    self.assertFalse(atticus.upgrade_needed('Explain division', 'No result', 'haiku'))
            with patch.dict(atticus.TURN, {'outcome': 'unverified'}):
                self.assertTrue(atticus.upgrade_needed('Explain division', 'Here is how.', 'sonnet'))
            with patch.object(atticus.run, 'observed', [{'error': True, 'result': 'tool error'}]):
                self.assertTrue(atticus.upgrade_needed('Explain division', 'Here is how.', 'haiku'))
            turns = [{'q': 'Explain synthetic division', 't': time.time()}]
            self.assertTrue(atticus.upgrade_needed('Explain synthetic division again', 'Here.', 'haiku', turns))
            self.assertFalse(atticus.upgrade_needed('Open Calendar', 'Here.', 'haiku', turns))
            self.assertTrue(atticus.upgrade_needed('No, on my screen', 'Here.', 'haiku', turns, correction=True))
            # Read-only replay: Nov 13 17:36:44 -> 17:37:13, the saved 29-second correction.
            previous = [{'q': 'can you show me how you did or how to do problem 36 using synthetic division', 't': time.time()-29}]
            self.assertTrue(atticus.upgrade_needed('no can you show me on my screen', 'Steps are on screen.', 'haiku', previous, correction=True))
            turns[0]['t'] -= 100
            self.assertFalse(atticus.upgrade_needed('Explain synthetic division', 'Here.', 'haiku', turns))
            with patch.object(atticus, 'pref', return_value=False):
                self.assertFalse(atticus.upgrade_available('haiku'))
            with patch.object(atticus, 'server', return_value={'ANTHROPIC_BASE_URL': 'local'}):
                self.assertFalse(atticus.upgrade_available('haiku'))

    def test_final_turn_replaces_provisional_history(self):
        from tests import scratch_dir
        root = scratch_dir(self)
        with patch.object(atticus, 'RECENT', str(root/'recent.jsonl')):
            first = atticus.remember_turn('Same ask', 'First answer')
            atticus.remember_turn('Same ask', 'Opus answer', replacing=first['t'])
            self.assertEqual([r['a'] for r in atticus.recent()], ['Opus answer'])

    def test_retry_preserves_request_images_and_receipts_without_saving_preferences(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'ATTICUS_ASK': root}), \
             patch.object(atticus, 'run', return_value=('Better answer', .2, ['Read'])) as run, \
             patch.object(atticus, 'ask_user', return_value='r'), patch.object(atticus, 'say') as say, \
             patch.object(atticus, 'checkpoint') as checkpoint, patch.object(atticus, 'start_ai', return_value='opus-worker') as start, \
             patch.object(atticus, 'save_pref') as save:
            run.ok, run.ran, run.observed = True, ['--type hello'], [{'action': '--type hello', 'result': 'unverified'}]
            pictures = [('same.jpg', 'same screen')]
            result = atticus.retry_capable('same context', 'same ask', 'First answer', pictures, True)
            self.assertEqual(result, ('Better answer', .2, ['Read']))
            checkpoint.assert_called_once_with(status='running', outcome=None, model='opus', escalated=True, escalate_why='user')
            say.assert_any_call('♧', 'retry')
            start.assert_called_once_with('opus')
            args, kwargs = run.call_args
            self.assertEqual(args[1:], ('opus-worker', pictures))
            self.assertEqual(kwargs, {'request': 'same ask', 'main_only': True})
            self.assertIn('same context', args[0])
            self.assertIn('check effects before repeating', args[0])
            self.assertEqual(json.loads(Path(root, 'prior-work.json').read_text())['observations'], run.observed)
            save.assert_not_called()
            run.reset_mock(); start.reset_mock()
            with patch.object(atticus, 'ask_user', return_value='n'):
                self.assertIsNone(atticus.retry_capable('context', 'ask', 'Answer', [], False))
            run.assert_not_called(); start.assert_not_called()


@unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'VM WebKit only')
class ModelUpgradePageTests(unittest.TestCase):
    def test_native_bridge_binds_the_ask_and_suppresses_meetings(self):
        from tests import run_swift
        source = (ROOT/'Atticus.swift').read_text()
        start = source.index('            if let choice = b["upgrade"]')
        action = source[start:source.index('            if let t = b["send"]', start)]
        start = source.index('                    if line == "♧ retry"')
        offer = source[start:source.index('                    if line.hasPrefix("▣ ")', start)]
        start = source.index('    func dismissUpgrade()')
        dismiss = source[start:source.index('    func run(_ t:', start)]
        swift = r'''import Foundation
final class Meeting { var running = false }; let meeting = Meeting()
enum Prefs { static var enabled = true; static func bool(_ k:String)->Bool { enabled } }
final class Settings {
    var changed:[String:String] = [:]
    func apply(_ key:String,_ value:Any) { changed[key] = String(describing:value) }
    func push() {}
}
enum Atticus { static let settings = Settings() }
final class Worker { var isRunning = true }
struct SpeechSentences { var consumed = 0 }
final class Harness {
    var upgradeFile = "", upgradeKeep = "", busy = false, speechMuted = true, lastDone = Date(), guided = true
    var speechSentences = SpeechSentences(consumed: 40), spokenSoFar = "First answer."
    var proc:Worker? = Worker(), calls:[String] = []
    func js(_ name:String,_ value:Any? = nil) { calls.append(name) }
    func shush() {}
    func linger(_ n:Double)->Double { n }
    func hide(after:Double) {}
    func receive(_ b:[String:Any]) {
''' + action + '''
    }
    func line(_ line:String) { for _ in 0..<1 {
''' + offer + '''
    } }
''' + dismiss + r'''}
let root = URL(fileURLWithPath:NSTemporaryDirectory()).appendingPathComponent(UUID().uuidString)
try! FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
defer { try? FileManager.default.removeItem(at:root) }
func path(_ name:String)->String { root.appendingPathComponent(name).path }
func message(_ id:String,_ action:String)->[String:Any] { ["upgrade":["id":id,"action":action]] }
let h=Harness(), one=path("one")
h.line("♧ retry"); precondition(!h.guided)
h.line("♧ " + String(data:try! JSONSerialization.data(withJSONObject:["id":one]),encoding:.utf8)!)
precondition(h.upgradeFile==one && h.calls.contains("upgrade"))
h.receive(message(one,"try"))
precondition(try! String(contentsOfFile:one,encoding:.utf8)=="r")
precondition(h.busy && !h.speechMuted && h.upgradeKeep==one && h.calls.last=="upgradeStarted")
precondition(h.speechSentences.consumed==0 && h.spokenSoFar.isEmpty)   // the stronger answer is read from its start
try! "unchanged".write(toFile:one,atomically:true,encoding:.utf8)
h.receive(message(one,"try"))
precondition(try! String(contentsOfFile:one,encoding:.utf8)=="unchanged")
precondition(Atticus.settings.changed.isEmpty)
h.receive(message(one,"keep"))
precondition(Atticus.settings.changed==["model":"opus","routing":"capable"])
Atticus.settings.changed=[:]; h.calls=[]; meeting.running=true
let two=path("meeting")
h.line("♧ " + String(data:try! JSONSerialization.data(withJSONObject:["id":two]),encoding:.utf8)!)
precondition(!h.calls.contains("upgrade") && h.upgradeFile.isEmpty)
precondition(try! String(contentsOfFile:two,encoding:.utf8)=="n")
h.upgradeFile=path("meeting-click"); h.receive(message(h.upgradeFile,"try"))
precondition(Atticus.settings.changed.isEmpty && !h.calls.contains("upgradeStarted"))
meeting.running=false; let off=path("off"); h.upgradeFile=off
h.receive(message(off,"off"))
precondition(Atticus.settings.changed==["modelSuggestions":"false"])
precondition(try! String(contentsOfFile:off,encoding:.utf8)=="n")
let stale=path("stale"); h.upgradeFile=stale; h.proc?.isRunning=false
h.receive(message(stale,"try"))
precondition(!FileManager.default.fileExists(atPath:stale))
print("Native upgrade bridge: same ask, once only, one-time default, opt-out, meeting and stale-worker guards passed")
'''
        run_swift(self, swift)

    def test_card_clicks_once_keep_once_and_remind_off(self):
        script = r'''
ui.listen(true); ui.words('Show problem 36'); ui.think(); ui.line('✓ I tried, but could not verify the result.'); ui.finished();
ui.upgrade('ask-one'); ui.upgrade('ask-one');
const count=document.querySelectorAll('.upgrade').length;
document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity).forEach(a=>a.finish());
const button=document.querySelector('.upgrade button'), hit=button.getBoundingClientRect(); ui.tap([hit.x+hit.width/2,hit.y+hit.height/2]);
ui.upgradeStarted('ask-one'); ui.think(); ui.line('… A stronger streamed answer is arriving now ');
const streaming=!!document.querySelector('.a.streaming'), askedEarly=document.querySelectorAll('.upgrade').length;
ui.line('✓ A stronger answer.'); ui.finished();
const clocks=document.querySelector('#thread .turn:last-child').querySelectorAll('.elapsed').length;
document.querySelector('.upgrade button').click();
ui.listen(true); ui.words('Another ask'); ui.line('✓ An answer'); ui.upgrade('ask-two');
document.querySelectorAll('.upgrade button')[1].click();
ui.listen(true); ui.words('One more ask'); ui.line('✓ An answer'); ui.upgradeStarted('ask-three'); ui.finished();
document.querySelectorAll('.upgrade button')[1].click();
ui.upgradeClear(); ui.listen(true); ui.words('Show problem 36'); ui.line('✓ I tried, but could not verify the result.'); ui.upgrade('shot');
document.body.style.background='#242426';
document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity).forEach(a=>a.finish());
await new Promise(r=>setTimeout(r,200));
const d=document.querySelector('.upgrade'), r=d.getBoundingClientRect();
return {count,streaming,askedEarly,clocks,text:d.textContent,fits:r.left>=0&&r.right<=innerWidth};
'''
        with tempfile.TemporaryDirectory() as tmp:
            src, binary, html = [Path(tmp, p) for p in ('page.swift', 'page', 'page.html')]
            html.write_text((ROOT/'ui/ui.html').read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/', (ROOT/'ui/orbs.js').read_text()))
            harness = HARNESS.replace('width: 260, height: 400', 'width: 420, height: 600')
            harness = harness.replace('cfg.userContentController.add(h, name: "agents")', 'cfg.userContentController.add(h, name: "c"); cfg.userContentController.add(h, name: "h")')
            harness = harness.replace('?["action"] as? String == "ready"', '?["ready"] != nil')
            harness = harness.replace('h.web.loadHTMLString', 'h.web.appearance = NSAppearance(named: CommandLine.arguments.count > 3 && CommandLine.arguments[3] == "light" ? .aqua : .darkAqua)\nh.web.loadHTMLString')
            harness = harness.replace('h.web.loadHTMLString', 'let window = NSWindow(contentRect: h.web.frame, styleMask: .borderless, backing: .buffered, defer: false)\nwindow.contentView = h.web; window.orderFront(nil)\nh.web.loadHTMLString')
            harness = harness.replace('print(String(data: out, encoding: .utf8)!); exit(0)', '''
                DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
                    let path = NSTemporaryDirectory() + UUID().uuidString + ".png", capture = Process()
                    capture.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
                    capture.arguments = ["-x", "-o", "-l\\(self.web.window!.windowNumber)", path]
                    try! capture.run(); capture.waitUntilExit(); precondition(capture.terminationStatus == 0)
                    let png = try! Data(contentsOf: URL(fileURLWithPath: path)); try! FileManager.default.removeItem(atPath: path)
                    print("SHOT " + png.base64EncodedString())
                    print(String(data: out, encoding: .utf8)!); exit(0)
                }''')
            src.write_text(harness)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(binary), str(html), "ui.autoMinimize(false);" + script], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            lines = result.stdout.strip().splitlines()
            shot = next(s[5:] for s in lines if s.startswith('SHOT '))
            self.assertTrue(base64.b64decode(shot).startswith(b'\x89PNG'))
            print('UPGRADE_SHOT '+shot, flush=True)
            got = json.loads(lines[-1])
            self.assertEqual(got['result']['count'], 1)
            self.assertTrue(got['result']['streaming'], got)
            self.assertEqual(got['result']['askedEarly'], 0)   # Nov 15: Keep using it sat under the pointer that had just clicked Try
            self.assertEqual(got['result']['clocks'], 1)   # one answer, one time line, the retry included
            self.assertTrue(got['result']['fits'], got)
            actions = [p['upgrade'] for p in got['posts'] if isinstance(p, dict) and 'upgrade' in p]
            self.assertEqual(actions, [{'id':'ask-one','action':'try'}, {'id':'ask-one','action':'keep'}, {'id':'ask-two','action':'off'}])
            self.assertFalse([p for p in got['posts'] if isinstance(p, dict) and 'error' in p], got)
            started = r'''
ui.listen(true); ui.words('Show problem 36'); ui.line('✓ I tried, but could not verify the result.'); ui.upgradeStarted('shot'); ui.finished();
document.body.style.background='#242426';
document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity).forEach(a=>a.finish());
await new Promise(r=>setTimeout(r,200));
const d=document.querySelector('.upgrade'), r=d.getBoundingClientRect();
return {text:d.textContent,fits:r.left>=0&&r.right<=innerWidth};
'''
            result = subprocess.run([str(binary), str(html), started], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            lines = result.stdout.strip().splitlines()
            print('UPGRADE_KEEP_SHOT '+next(s[5:] for s in lines if s.startswith('SHOT ')), flush=True)
            got = json.loads(lines[-1])['result']
            self.assertEqual(got['text'], 'Opus uses more of your plan.Keep using itJust this once')
            self.assertTrue(got['fits'], got)
            for appearance in ('light', 'dark'):
                for off in (False, True):
                    state = 'off' if off else 'card'
                    check = """
ui.listen(true); ui.words('Explain the result'); ui.line('✓ I tried, but could not verify the result.'); ui.upgrade('review');
""" + ("document.querySelectorAll('.upgrade button')[1].click();" if off else '') + """
document.body.style.background='#242426';
document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity).forEach(a=>a.finish());
await new Promise(r=>setTimeout(r,200));
document.getAnimations().filter(a=>a.effect.getTiming().iterations!==Infinity).forEach(a=>a.finish());
await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
await new Promise(r=>setTimeout(r,100));
return {cards:document.querySelectorAll('.upgrade').length,light:matchMedia('(prefers-color-scheme: light)').matches};
"""
                    result = subprocess.run([str(binary), str(html), check, appearance], capture_output=True, text=True, timeout=60)
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                    lines = result.stdout.strip().splitlines()
                    print(f'UPGRADE_REVIEW_{appearance.upper()}_{state.upper()}_SHOT '+next(s[5:] for s in lines if s.startswith('SHOT ')), flush=True)
                    got = json.loads(lines[-1])
                    self.assertEqual(got['result'], {'cards': 0 if off else 1, 'light':appearance == 'light'})
                    if off: self.assertIn({'upgrade':{'id':'review','action':'off'}}, got['posts'])
