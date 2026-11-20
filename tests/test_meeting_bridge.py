"""Real native/WebKit handshake with delayed JavaScript and fake meeting workers."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests import swift_motion

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'macOS native meeting bridge')
class MeetingBridgeTests(unittest.TestCase):
    def test_pending_javascript_keeps_the_stage_deadline(self):
        source = Path(__file__).read_text().rsplit('    def test_prep_queue_edits_and_stop_with_fake_workers(self):', 1)[1]
        start = source.index('Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { _ in')
        checks = source[start:source.index(' switch stage {', start)].split('\n', 1)[1].replace('\\\\', '\\')
        swift = '''import Foundation
struct Meeting { let gathering = false, running = false; let process: Int? = nil }
let meeting = Meeting(), begun = Date()
var stage = 0, timedStage = 0, tries = 0, stageStarts: [String] = []
var stageBegan = Date().addingTimeInterval(CommandLine.arguments[1] == "expired" ? -13 : 0)
let evaluating = true
func fail(_ message: String) -> Never { print(message); exit(1) }
func tick() {
''' + checks + '''
 preconditionFailure("Pending JavaScript advanced the stage")
}
tick()
print("pending")
'''
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / 'deadline.swift'; file.write_text(swift)
            binary = Path(root) / 'deadline'
            compiled = subprocess.run(['swiftc', str(file), '-o', str(binary)], text=True, capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            pending = subprocess.run([str(binary), 'pending'], text=True, capture_output=True, timeout=5)
            self.assertEqual(pending.returncode, 0, pending.stdout + pending.stderr)
            expired = subprocess.run([str(binary), 'expired'], text=True, capture_output=True, timeout=5)
            self.assertEqual(expired.returncode, 1, expired.stdout + expired.stderr)
            self.assertIn('Bridge test timed out at stage 0', expired.stdout)

    def test_prep_queue_edits_and_stop_with_fake_workers(self):
        source = (ROOT / 'Atticus.swift').read_text()
        classes = source[source.index('// Meeting audio'):source.index('// MARK: - Hands')]
        # Keep the actual start guards and state transition; replace hardware work with no-op capture.
        begin = classes.index('        let g = generation', classes.index('    func start(_ context: String)'))
        end = classes.index('    func speech(', begin)
        classes = classes[:begin] + '        Prefs.set("meetingPrep", "")\n    }\n' + classes[end:]
        # The guest's own Calendar permission must not decide the flow: denied posts allowCalendar (System Settings), unasked prompts.
        classes = classes.replace('EKEventStore.authorizationStatus(for: .event)', 'fixtureCalendar').replace('EKEventStore.authorizationStatus(for:.event)', 'fixtureCalendar')
        prefs = source[source.index('enum Prefs'):source.index('// Read-aloud uses')] + source[source.index('func callJS('):source.index('func currentRequestScreen(')] + 'func telemetry(_ args: [String]) {}\n'
        prefs += swift_motion(source)
        swift = '''import Cocoa
import Carbon
import AVFoundation
import Speech
import WebKit
import ScreenCaptureKit
import PDFKit
import QuickLookThumbnailing
import UniformTypeIdentifiers
import EventKit
let dir = CommandLine.arguments[1]
''' + prefs + '''
let calendar = EKEventStore(), fixtureCalendar = EKAuthorizationStatus.notDetermined   // Fill in for me offered; no real calendar read
final class KeyPanel: NSPanel { override var canBecomeKey: Bool { true } }
final class AppStub {
 var shortcutDown = false, pinned = false, voicePermissionPending = false, voicePermissionID = 0
 var voicePermissionAction: (() -> Void)?
 func close(clear: Bool) {}; func dismissUpgrade() {}
 func pill(_ on: Bool) {}; func show() {}; func js(_ call: String, _ value: Any?) {}
 func missingVoicePermission(_ need: String, retry: @escaping () -> Void) {}
}
final class Onboarding {
 static func permissionState(_ need: String) -> Int { 1 }
 func request(_ need: String, settingsOnRefusal: Bool, current: @escaping () -> Bool, done: @escaping (Bool) -> Void) { if current() { done(true) } }
}
let onboarding = Onboarding()
final class BarStub { func paint() {} }
let app = AppStub(), bar = BarStub()
final class SettingsStub {
 func open(tab: String) {}
 func meetings(_ data: [String: Any], _ done: (([String: Any]) -> Void)? = nil) { done?([:]) }
}
let settings = SettingsStub()
func callAppsOnMic() -> Set<String> { ["Zoom"] }
func py(_ args: [String]) -> Process {
 let p = Process(); p.executableURL = URL(fileURLWithPath: CommandLine.arguments[2])
 p.arguments = [dir + "/worker.py"] + args; return p
}
''' + source[source.index('final class Tracker'):source.index('// The box can take typing')] + classes + '''
let meeting = MeetingCopilot()
meeting.calendarContext = { done in done(["title":"Pilot review","time":"Today at 4:00 PM","attendees":["Dana <dana@example.com>"],"notes":"Agenda"], nil) }
let nsapp = NSApplication.shared
nsapp.setActivationPolicy(.accessory)
var stage = 0, timedStage = 0, stageStarts: [String] = [], savedFrame = NSRect.zero, latencyReady = Date.distantPast, stageBegan = Date()
var cancelledFinishes: [Process] = []
var evaluating = false
func fail(_ message: String) -> Never { print(message); meeting.discard(); exit(1) }
func evaluate(_ script: String, _ done: @escaping (Any?) -> Void) {
 guard !evaluating else { return }; evaluating = true
 meeting.web?.evaluateJavaScript(script) { value, error in
  evaluating = false
  if let error { fail("Stage \\(stage), script \\(script): \\(error)") }; done(value)
 }
}
meeting.open(demo: true)
let begun = Date()
Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { _ in
 if stage != timedStage { timedStage = stage; stageBegan = Date(); stageStarts.append("\\(stage)@\\(String(format: "%.1f", Date().timeIntervalSince(begun)))s") }   // each stage keeps its 12 s even while JavaScript is pending
 if Date().timeIntervalSince(stageBegan) > 12 { fail("Bridge test timed out at stage \\(stage) after \\(stageStarts.joined(separator: " ")) (gathering \\(meeting.gathering), helper \\(meeting.process != nil), running \\(meeting.running))") }
 guard !evaluating else { return }
 switch stage {
 case 0:
  evaluate("!!window.meeting && !document.getElementById('start').disabled") { value in
   guard value as? Bool == true else { return }
   guard !meeting.running else { fail("Demo started before prep / JavaScript ready") }
   stage = 1
   evaluate("document.getElementById('context').value") { value in
    guard (value as? String ?? "").contains("18,000") else { fail("Demo context was not loaded before prep") }
    evaluate("document.getElementById('start').click()") { _ in }
   }
  }
 case 1:
  guard meeting.running else { return }
  stage = 2
  evaluate("document.getElementById('prep').hidden && !document.getElementById('askbar').hidden") { value in
   guard value as? Bool == true else { fail("Start began capture without updating panel") }
   guard meeting.brief.contains("18,000") else { fail("Demo lost its built-in context") }
   meeting.discard(); meeting.open()
  }
 case 2:
  evaluate("!!window.meeting && !document.getElementById('start').disabled") { value in
   guard value as? Bool == true else { return }
   guard !meeting.running else { fail("Normal prep started capture") }
   stage = 21
   FileManager.default.createFile(atPath: dir + "/hold-gather", contents: nil)   // the helper stays running until stage 22 cancels it; a 0.3 s one can finish between polls
   evaluate("document.getElementById('context').value='Pilot notes';document.getElementById('gather').click()") { _ in }
  }
 case 21:
  guard meeting.gathering, let gatherer = meeting.process else { return }
  meeting.showAgentPrep(["preparedBrief":"Agent brief","meetingEvent":["title":"Pilot review"]])   // a second helper waits; it never replaces the running one
  guard meeting.prepWaiting, meeting.process === gatherer, gatherer.isRunning else { fail("Agent prep orphaned the running gather") }
  meeting.prepWaiting = false; meeting.agentPrep = nil
  stage = 22
  evaluate("document.getElementById('gather').click()") { _ in }
 case 22:
  guard !meeting.gathering, meeting.process == nil else { return }
  stage = 23
  try? FileManager.default.removeItem(atPath: dir + "/hold-gather")
  evaluate("document.getElementById('gather').click()") { _ in }
 case 23:
  guard !meeting.gathering, meeting.process == nil else { return }
  let payload = (try? Data(contentsOf: URL(fileURLWithPath: dir + "/gather.json"))).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
  guard (payload?["event"] as? [String: Any])?["title"] as? String == "Pilot review",
        (payload?["text"] as? String) == "Pilot notes" else { fail("Gather lost fake calendar or typed context") }
  evaluate("document.getElementById('context').value") { value in
   guard value as? String == "[Calendar] Pilot review\\n[Email] Decision" else { return }
   stage = 3
   evaluate("document.getElementById('style').value='Persuasive';document.getElementById('context').value='Pilot notes';document.getElementById('start').click()") { _ in }
  }
 case 3:
  guard meeting.running else { return }
  guard meeting.brief == "Pilot notes" else { fail("Short context was not used as-is") }
  if latencyReady == .distantPast { latencyReady = Date(); return }
  guard Date().timeIntervalSince(latencyReady) > 0.3 else { return }
  meeting.speech("Tell me the budget?", final: true)
  stage = 31
 case 31:
  guard meeting.answering == nil, FileManager.default.fileExists(atPath: dir + "/answer.json") else { return }
  try? FileManager.default.removeItem(atPath: dir + "/answer.json")
  let saved = (try? Data(contentsOf: URL(fileURLWithPath: Prefs.path))).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
  guard saved?["meetingStyle"] as? String == "Persuasive", meeting.style.hasPrefix("Speak to feelings first") else { fail("Picked answer style was not saved as the default") }
  guard !FileManager.default.fileExists(atPath: dir + "/meetings") else { fail("Saving switch off wrote a meeting") }
  Prefs.set("meetingSave", true); meeting.savingChanged(true)
  guard meeting.archive != nil else { fail("Saving switch on did not start the journal") }
  stage = 4
  evaluate("document.getElementById('brief').value='Edited brief';document.getElementById('brief').dispatchEvent(new Event('input'))") { _ in }
 case 4:
  guard meeting.brief == "Edited brief" else { return }
  stage = 5; meeting.discard(); meeting.open()
 case 5:
  evaluate("!!window.meeting && !document.getElementById('start').disabled && document.getElementById('style').value") { value in
   guard let value = value as? String, !value.isEmpty else { return }
   guard value == "Persuasive" else { fail("Next prep did not restore the default answer style") }; stage = 6
   evaluate("document.getElementById('context').value='x'.repeat(7000);document.getElementById('start').click()") { _ in }
  }
 case 6:
  guard meeting.running, meeting.process != nil else { return }
  meeting.speech("Should you answer me?", final: true, mic: true)
  guard meeting.micPartialQuestion == nil, meeting.queue.isEmpty, meeting.answering == nil else { fail("Own microphone triggered an automatic answer") }
  meeting.speech("What is the budget?", final: false)
  guard meeting.partialQuestion != nil else { fail("Clear partial question waited for final speech") }
  meeting.speech("What is the budget?", final: true)
  stage = 9
 case 9:
  guard meeting.brief == "Boiled down", meeting.process == nil else { return }
  let payload = (try? Data(contentsOf: URL(fileURLWithPath: dir + "/answer.json"))).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
  guard payload?["brief"] as? String == "Boiled down" else { fail("Queued answer used context from before prep") }
  guard (payload?["style"] as? String ?? "").hasPrefix("Speak to feelings first") else { fail("Answer worker did not get the picked style") }
  stage = 10; meeting.discard(); meeting.open()
 case 10:
  evaluate("!!window.meeting && !document.getElementById('start').disabled") { value in
   guard value as? Bool == true else { return }; stage = 11
   evaluate("document.getElementById('context').value='x'.repeat(7000);document.getElementById('start').click()") { _ in }
  }
 case 11:
  guard meeting.running, meeting.process != nil else { return }; stage = 12
  evaluate("document.getElementById('brief').value='Keep my edit';document.getElementById('brief').dispatchEvent(new Event('input'));document.getElementById('ask').focus()") { _ in }
 case 12:
  guard meeting.process == nil else { return }
  guard meeting.brief == "Keep my edit" else { fail("Prep overwrote edited native context") }; stage = 13
  evaluate("document.getElementById('brief').value") { value in
   guard value as? String == "Keep my edit" else { fail("Prep overwrote edited page context") }
   stage = 7; meeting.discard(); meeting.open()
  }
 case 7:
  evaluate("!!window.meeting && !document.getElementById('start').disabled") { value in
   guard value as? Bool == true else { return }; stage = 8
   evaluate("const s=document.getElementById('style');s.value='Custom…';s.dispatchEvent(new Event('change'));document.getElementById('custom').value='  Tell a short story first ';document.getElementById('start').click()") { _ in }
  }
 case 8:
  guard meeting.running else { return }
  guard meeting.brief.isEmpty else { fail("Empty start retained old context") }
  guard meeting.style == "Tell a short story first", Prefs.str("meetingCustom") == "Tell a short story first" else { fail("Custom answer style was not used or remembered") }
  meeting.speech("Earlier partial", final: false); meeting.speech("Earlier final. ", final: true)
  meeting.speech("Unfinished question", final: false); meeting.stop()
  guard meeting.transcript.count == 2, meeting.transcript.last?["text"] as? String == "Unfinished question",
        meeting.partial.isEmpty, meeting.queue.isEmpty, meeting.process == nil else { fail("Stop lost partial speech or left work queued") }
  MeetingArchive.writes.wait()   // archive writes are queued; quitting waits on the same group
  guard let archive = meeting.archive,
        let journal = try? String(contentsOfFile: archive.folder + "/events.jsonl", encoding: .utf8), journal.contains("Unfinished question"), journal.contains("Zoom") else { fail("Stop did not durably save speaker transcript") }
  for file in ["metadata.json", "events.jsonl"] {
   guard let permissions = try? FileManager.default.attributesOfItem(atPath: archive.folder + "/" + file)[.posixPermissions] as? NSNumber,
         permissions.intValue == 0o600 else { fail("Transcript file was not private") }
  }
  meeting.speech("Late result", final: true)
  guard meeting.transcript.count == 2 else { fail("Late speech survived Stop") }
  stage = 14; meeting.start(meeting.brief)
 case 14:
  guard meeting.running else { return }
  guard meeting.transcript.count == 2 else { fail("Resume discarded transcript") }
  stage = 16; meeting.material([dir + "/notes.txt"])
 case 16:
  guard meeting.brief == "Boiled down", meeting.process == nil else { return }
  let prep = (try? Data(contentsOf: URL(fileURLWithPath: dir + "/prep.json"))).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
  guard (prep?["text"] as? String ?? "").contains("Live notes") else { fail("Live file did not reach context preparation") }
  meeting.speech("My own words", final: false, mic: true)
  meeting.speech("The other side", final: false)
  meeting.stop(paused: true)
  guard meeting.transcript.count == 4, meeting.transcript.last?["mic"] as? Bool == true,
        meeting.micPartial.isEmpty, meeting.partial.isEmpty else { fail("Pause lost simultaneous mic and call speech") }
  stage = 15
 case 15:
  evaluate("document.getElementById('h1').textContent==='Call paused' && !document.getElementById('resume').disabled") { value in
   guard value as? Bool == true else { return }
   guard let panel = meeting.panel, let screen = panel.screen else { fail("No meeting display") }
   savedFrame = NSRect(x: screen.visibleFrame.minX + 70, y: screen.visibleFrame.maxY - 580, width: 340, height: 500)
   panel.setFrame(savedFrame, display: false); meeting.rememberFrame()
   let key = MeetingFrame.key(screen)
   guard (Prefs.d["meetingFrames"] as? [String: [Double]])?[key] == [savedFrame.minX, savedFrame.minY, 340, 500] else { fail("Frame not saved per display") }
   stage = 17; meeting.discard(); meeting.open()
  }
 case 17:
  guard meeting.loaded, let panel = meeting.panel else { return }
  guard abs(panel.frame.minX - savedFrame.minX) < 1, abs(panel.frame.maxY - savedFrame.maxY) < 1 else { fail("Next open did not restore the saved anchor") }
  meeting.resetFrame()
  guard abs(panel.frame.minX - panel.screen!.visibleFrame.minX - 12) < 1 else { fail("Reset did not use the default spot") }
  meeting.start("Resume lifecycle fixture");meeting.pending="A durable line";meeting.flush(answer:false);meeting.stop();stage=24
 case 24:   // the recap starts once the queued End write lands
  guard let first=meeting.finishing else { return }
  guard first.isRunning else { fail("Summary worker was not tracked") };cancelledFinishes.append(first)
  meeting.start("Resumed");guard meeting.finishing == nil else { fail("Resume kept stale summary work") }
  meeting.pending="Resumed line";meeting.flush(answer:false);meeting.stop();stage=25
 case 25:
  guard let second=meeting.finishing else { return }
  guard second.isRunning else { fail("Resumed summary worker was not tracked") };cancelledFinishes.append(second)
  let folder=meeting.archive!.folder;meeting.discard()
  guard FileManager.default.fileExists(atPath:folder+"/events.jsonl") else { fail("Close deleted durable transcript") }
  stage=18
 case 18:
  guard cancelledFinishes.allSatisfy({ !$0.isRunning }) else { return }
  guard meeting.finishing == nil && meeting.panel == nil else { fail("Close kept worker or panel") }
  meeting.open();stage=19
 case 19:
  guard meeting.loaded else { return }
  meeting.start("Failed journal fixture");try! meeting.archive!.handle.close();meeting.stop();stage=26
 case 26:   // the failed End write reports back on the main queue
  guard meeting.archive == nil else { return }
  guard !meeting.archiveEnded && meeting.finishing == nil else { fail("Failed End pretended to save or started a recap") }
  stage=20
 case 20:
  evaluate("document.getElementById('toast').textContent") { value in
   guard (value as? String ?? "").contains("Transcript could not save") else { return }
   print("native meeting bridge: readiness, context, durable saves, Stop, Resume, Pause, frame restore, recap cancellation and failed End")
   meeting.discard();exit(0)
  }
 default: break
 }
}
nsapp.run()
'''
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / 'settings.json').write_text(json.dumps({'meeting': True, 'meetingSave': False}))
            (root / 'notes.txt').write_text('Live notes: budget is $21,000.')
            (root / 'ui').mkdir()
            html = (ROOT / 'ui/meeting.html').read_text().replace('<script type="module">', '<script type="module">\nawait new Promise(resolve => setTimeout(resolve, 350));')
            (root / 'ui/meeting.html').write_text(html)
            (root / 'ui/orbs.js').write_text((ROOT / 'ui/orbs.js').read_text())
            (root / 'worker.py').write_text("import json,sys,time\nfrom pathlib import Path\nif sys.argv[1]=='--meeting-demo-brief':\n print(json.dumps({'brief':'Demo pilot budget: $18,000.'}))\nelif sys.argv[1]=='--meetings':\n time.sleep(30); print('{}')\nelse:\n data=json.load(sys.stdin)\n if sys.argv[1]=='--meeting-gather':\n  Path(sys.argv[0]).with_name('gather.json').write_text(json.dumps(data)); hold=Path(sys.argv[0]).with_name('hold-gather'); end=time.time()+10\n  while hold.exists() and time.time()<end: time.sleep(.05)\n  time.sleep(.3); print(json.dumps({'brief':'[Calendar] Pilot review\\n[Email] Decision'}))\n elif sys.argv[1]=='--meeting-prep':\n  Path(sys.argv[0]).with_name('prep.json').write_text(json.dumps(data)); time.sleep(.7); print(json.dumps({'brief':'Boiled down'}))\n else:\n  Path(sys.argv[0]).with_name('answer.json').write_text(json.dumps(data)); time.sleep(.12); print(json.dumps({'event':'text','text':'Answer','at':time.time()}),flush=True); time.sleep(.38); print(json.dumps({'event':'result','result':{'kind':'answer','lines':['Answer'],'secs':.5,'first_secs':.12}}),flush=True)\n")
            file = root / 'bridge.swift'; file.write_text(swift)
            binary = root / 'bridge'
            compiled = subprocess.run(['swiftc', str(file), '-o', str(binary)], text=True, capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary), str(root), sys.executable], env={**os.environ, 'ATTICUS_DIR': str(root)}, text=True, capture_output=True, timeout=300)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            timings = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{') and 'meeting-answer-latency' in line]
            self.assertTrue(timings, result.stdout)
            measured = timings[0]
            self.assertLess(measured['detectedToModelMs'], 50)
            self.assertGreaterEqual(measured['modelToFirstMs'], 100)
            self.assertLess(measured['modelToFirstMs'], 350)
            self.assertLess(abs(measured['firstToShownMs']), 200)
            print('fake transcript latency:', json.dumps(measured, sort_keys=True))
