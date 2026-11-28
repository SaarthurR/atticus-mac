"""Meeting detection and audio routing with fake events and synthetic samples."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'macOS meeting components')
class MeetingNativeTests(unittest.TestCase):
    def test_native_journal_append_and_private_atomic_export(self):
        source = (ROOT / 'Atticus.swift').read_text()
        archive = source[source.index('final class MeetingArchive'):source.index('final class MeetingAudio')]
        self.check_swift('''import Cocoa
enum Prefs { static let root = NSTemporaryDirectory() + UUID().uuidString; static let path = root + "/settings.json" }
''' + archive + '''
let fm = FileManager.default
defer { try? fm.removeItem(atPath: Prefs.root) }
let archive = try! MeetingArchive(title: "Pilot", app: "Zoom", started: Date())
func append(_ event: [String: Any]) {
 var finished = false
 archive.append([event]) { error in precondition(error == nil); finished = true }
 while !finished { RunLoop.current.run(until: Date().addingTimeInterval(0.01)) }
}
append(["kind":"transcript","text":"First"])
let other = try! FileHandle(forWritingTo: URL(fileURLWithPath: archive.folder + "/events.jsonl"))
try! other.seekToEnd(); try! other.write(contentsOf: Data("{\\"kind\\":\\"summary\\",\\"text\\":\\"Recap\\"}\\n".utf8)); try! other.close()
append(["kind":"transcript","text":"Resumed"])
let text = try! String(contentsOfFile: archive.folder + "/events.jsonl", encoding: .utf8)
precondition(text.contains("First") && text.contains("Recap") && text.contains("Resumed"), "append overwrote summary")
for path in [archive.folder, Prefs.root + "/meetings"] {
 precondition((try! fm.attributesOfItem(atPath: path)[.posixPermissions] as! NSNumber).intValue == 0o700)
}
for name in ["metadata.json", "events.jsonl"] {
 precondition((try! fm.attributesOfItem(atPath: archive.folder + "/" + name)[.posixPermissions] as! NSNumber).intValue == 0o600)
}
let export = URL(fileURLWithPath: Prefs.root + "/meeting.md")
try! MeetingArchive.export("Transcript", to: export); try! MeetingArchive.export("Updated", to: export)
precondition(try! String(contentsOf: export, encoding:.utf8) == "Updated")
precondition((try! fm.attributesOfItem(atPath: export.path)[.posixPermissions] as! NSNumber).intValue == 0o600)
print("private append-only archive and atomic export")
''')

    def test_saved_frames_restore_clamp_and_fallback(self):
        source = (ROOT / 'Atticus.swift').read_text()
        geometry = source[source.index('enum MeetingFrame'):source.index('final class MeetingWebView')]
        self.check_swift('import Cocoa\n' + geometry + '''
let primary = NSRect(x: 0, y: 28, width: 1440, height: 872), secondary = NSRect(x: -1000, y: 100, width: 1000, height: 700)
let saved: [Double] = [-900, 300, 340, 470]
precondition(MeetingFrame.initial(saved, secondary) == NSRect(x: -900, y: 300, width: 340, height: 470))
let nudge: [Double] = [-900, 700, 52, 52]
precondition(MeetingFrame.initial(nudge, secondary).minX == -900, "nudge anchor was discarded")
let restored = MeetingFrame.initial(saved, primary)
precondition(restored.minX == 12 && restored.maxY == primary.maxY - 12, "missing display did not use default")
for bad in [[Double.nan, 2, 3, 4], [0, 0, 340, 470], [4000, 800, 340, 470], [1, 2]] {
 precondition(MeetingFrame.initial(bad, primary) == MeetingFrame.initial(nil, primary))
}
for bounds in [primary, secondary, NSRect(x: 20, y: 100, width: 200, height: 160)] {
 let frame = MeetingFrame.clamp(NSRect(x: -4000, y: 9999, width: 340, height: 650), bounds)
 precondition(bounds.contains(frame), "frame escaped visible screen")
}
print("saved meeting frames restore and clamp")
''')

    def check_swift(self, swift):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'check.swift'; source.write_text(swift)
            binary = Path(root) / 'check'
            compiled = subprocess.run(['swiftc', str(source), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_call_debounce_and_calendar_priority(self):
        source = (ROOT / 'Atticus.swift').read_text()
        mic = source[source.index('func checkMic()'):source.index('\nTimer.scheduledTimer', source.index('func checkMic()'))]
        calendar = source[source.index('func checkCalendar()'):source.index('\nfunc showNudge', source.index('func checkCalendar()'))]
        self.check_swift('''import Foundation
struct Prefs {
 static var enabled = true
 static func bool(_ k: String) -> Bool { k == "paused" ? false : enabled }
}
final class Meeting { var running = false, panel: Int?, callApp = "Call", stops = 0; func stop() { stops += 1; running = false } }
let callApps = ["us.zoom.xos": "Zoom", "com.microsoft.teams": "Teams"]
let meeting = Meeting()
var onMicSince: [String: Date] = [:], callNudged = Set<String>(), callSeen = false, callGone: Date?, current = Set<String>(), nudges: [[String: Any]] = []
func callAppsOnMic() -> Set<String> { current }
func showNudge(_ data: [String: Any]) { nudges.append(data) }
''' + mic + '''
// hang-up ends the meeting, but only after the call app was seen on the mic and stayed off for the grace period
meeting.running = true; meeting.callApp = "Zoom"; current = []; checkMic(); checkMic(); precondition(meeting.stops == 0)
current = ["Zoom"]; checkMic(); current = []; checkMic(); precondition(meeting.stops == 0 && callGone != nil)
callGone = Date().addingTimeInterval(-3); checkMic(); precondition(meeting.stops == 1 && !meeting.running)
// before setup finishes, a call on the mic gets no card (it would ask to listen before setup asks for the mic)
current = ["Zoom"]; onMicSince["Zoom"] = Date().addingTimeInterval(-4); checkMic(); precondition(nudges.isEmpty && onMicSince.isEmpty, "call card during setup")
UserDefaults.standard.register(defaults: ["onboarded": true])
current = []; callNudged = []; onMicSince = [:]
current = ["Zoom"]; checkMic(); precondition(nudges.isEmpty)
onMicSince["Zoom"] = Date().addingTimeInterval(-2); checkMic(); precondition(nudges.isEmpty)
onMicSince["Zoom"] = Date().addingTimeInterval(-4); checkMic(); precondition(nudges.count == 1 && nudges[0]["go"] == nil)
checkMic(); precondition(nudges.count == 1)
current = []; checkMic(); current = ["Zoom"]; checkMic(); onMicSince["Zoom"] = Date().addingTimeInterval(-4); checkMic(); precondition(nudges.count == 2)
meeting.panel = 1; current = ["Teams"]; onMicSince["Teams"] = Date().addingTimeInterval(-4); checkMic(); precondition(nudges.count == 2)
meeting.panel = nil; Prefs.enabled = false; checkMic(); precondition(onMicSince.isEmpty); Prefs.enabled = true

enum Authorization { case fullAccess, denied }
enum Entity { case event }
enum EKEventStore { static var access = Authorization.fullAccess; static func authorizationStatus(for: Entity) -> Authorization { access } }
enum EventStatus { case confirmed, canceled }
enum ParticipantStatus { case accepted, declined }
struct Person { var isCurrentUser = false, name: String? = "Dana", participantStatus = ParticipantStatus.accepted }
struct Event {
 var title: String? = "Call", startDate = Date(), isAllDay = false, status = EventStatus.confirmed
 var eventIdentifier: String? = UUID().uuidString, attendees: [Person]? = [Person()], hasAttendees = true
 var url: URL?, location: String?, notes: String?
}
final class Calendar {
 var rows: [Event] = []
 func predicateForEvents(withStart start: Date, end: Date, calendars: [Int]?) -> Int { precondition(abs(end.timeIntervalSince(start) - 240) < 0.01); return 0 }
 func events(matching: Int) -> [Event] { rows }
}
let calendar = Calendar(); var nudged = Set<String>()
''' + calendar + '''
var later = Event(); later.title = "Later"; later.startDate = Date().addingTimeInterval(90)
var soon = Event(); soon.title = "Soon"; soon.startDate = Date().addingTimeInterval(30); soon.url = URL(string:"https://zoom.us/j/123")
var canceled = Event(); canceled.status = .canceled
var declined = Event(); declined.attendees = [Person(isCurrentUser: true, participantStatus: .declined)]
calendar.rows = [later, canceled, declined, soon]; checkCalendar()
precondition(nudges.last?["title"] as? String == "Soon" && (nudges.last?["context"] as? String ?? "").contains("zoom.us/j/123"))
checkCalendar(); precondition(nudges.last?["title"] as? String == "Later")
let count = nudges.count; checkCalendar(); precondition(nudges.count == count)
EKEventStore.access = .denied; nudged = []; checkCalendar(); precondition(nudges.count == count)
print("meeting detection/calendar ok")
''')

    def test_system_and_microphone_samples_use_separate_feeds(self):
        source = (ROOT / 'Atticus.swift').read_text()
        audio = source[source.index('final class MeetingAudio'):source.index('final class MeetingWebView')]
        # Exercise the delegate body without constructing a capture stream or asking for permissions.
        audio = audio.replace('func stream(_ stream: SCStream, didOutputSampleBuffer sample:', 'func samples(_ sample:')
        self.check_swift('''import Cocoa
import AVFoundation
import Speech
import ScreenCaptureKit
''' + audio + '''
let audio = MeetingAudio()
let (calls, callFeed) = AsyncStream<AnalyzerInput>.makeStream()
let (mic, micFeed) = AsyncStream<AnalyzerInput>.makeStream()
audio.feed = callFeed; audio.micFeed = micFeed
var observed: Float = -1; audio.onLevel = { observed = $0 }
let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48000, channels: 1, interleaved: true)!
audio.format = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: false)!
var block: CMBlockBuffer?
precondition(CMBlockBufferCreateWithMemoryBlock(allocator: nil, memoryBlock: nil, blockLength: 640, blockAllocator: nil, customBlockSource: nil, offsetToData: 0, dataLength: 640, flags: kCMBlockBufferAssureMemoryNowFlag, blockBufferOut: &block) == noErr)
precondition(CMBlockBufferFillDataBytes(with: 0, blockBuffer: block!, offsetIntoDestination: 0, dataLength: 640) == noErr)
var loud: Float = 0.25
withUnsafeBytes(of: &loud) { precondition(CMBlockBufferReplaceDataBytes(with: $0.baseAddress!, blockBuffer: block!, offsetIntoDestination: 0, dataLength: 4) == noErr) }
var sample: CMSampleBuffer?
precondition(CMAudioSampleBufferCreateReadyWithPacketDescriptions(allocator: nil, dataBuffer: block!, formatDescription: format.formatDescription, sampleCount: 160, presentationTimeStamp: .zero, packetDescriptions: nil, sampleBufferOut: &sample) == noErr)
audio.samples(sample!, of: .audio)
audio.samples(sample!, of: .microphone)
precondition(observed >= 0.25, "waveform did not receive audio levels")
callFeed.finish(); micFeed.finish()
Task {
 var callCount = 0, micCount = 0
 for await _ in calls { callCount += 1 }
 for await _ in mic { micCount += 1 }
 precondition(callCount == 1 && micCount == 1, "audio streams were mixed or dropped")
 await audio.stop(); precondition(audio.feed == nil && audio.micFeed == nil)
 print("separate audio feeds ok"); exit(0)
}
RunLoop.main.run()
''')
