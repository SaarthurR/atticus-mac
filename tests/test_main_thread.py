"""Main-thread regressions with fake capture/apps and temporary files only."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin', 'macOS Swift regression')
class MainThreadTests(unittest.TestCase):
    def swift(self, body):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'check.swift'
            binary = Path(root) / 'check'
            source.write_text(body)
            result = subprocess.run(['swiftc', str(source), '-o', str(binary)], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_permission_refresh_deduplicates_pending_probes(self):
        source = (ROOT / 'Atticus.swift').read_text()
        statuses = source[source.index('    static let probeLock'):source.index('    static func sync()')]
        self.swift('''import Foundation
typealias OSStatus = Int32
let noErr: OSStatus = 0, errAEEventNotPermitted: OSStatus = -1743
let gate = DispatchSemaphore(value: 0), started = DispatchSemaphore(value: 0)
let callsLock = NSLock()
var calls = 0
enum Apps {
 static var allowed = Set<String>()
 static func check(_ id: String, ask: Bool) -> OSStatus {
  callsLock.lock(); calls += 1; callsLock.unlock(); started.signal()
  gate.wait(); return noErr
 }
''' + statuses + '''
}
_ = Apps.statuses(["frozen", "frozen"])
precondition(started.wait(timeout: .now() + 1) == .success)
for _ in 0..<4 { _ = Apps.statuses(["frozen"]) }
callsLock.lock(); precondition(calls == 1, "refresh leaked another blocked probe"); callsLock.unlock()
gate.signal()
let deadline = Date().addingTimeInterval(2)
while Date() < deadline {
 Apps.probeLock.lock(); let empty = Apps.pendingProbes.isEmpty; Apps.probeLock.unlock()
 if empty { break }; Thread.sleep(forTimeInterval: 0.01)
}
gate.signal()
precondition(Apps.statuses(["frozen"])["frozen"] == "allowed", "completed probe prevented future refresh")
''')

    def test_activation_returns_without_waiting_and_times_out(self):
        source = (ROOT / 'Atticus.swift').read_text()
        activate = source[source.index('    static func activate(_ pid:'):source.index('    static var workInFront')]
        self.swift('''import Foundation
final class NSRunningApplication {
 init?(processIdentifier: Int32) {}
 func activate() -> Bool { true }
}
final class Process {
 static var launched: [Process] = []
 var executableURL: URL?, arguments: [String]?, standardOutput: Any?, standardError: Any?
 var terminationHandler: ((Process) -> Void)?
 var isRunning = false, terminated = false
 func run() throws { isRunning = true; Self.launched.append(self) }
 func terminate() { precondition(!Thread.isMainThread); terminated = true; isRunning = false; terminationHandler?(self) }
}
enum Apps { static var allowed: Set<String> = [] }
enum MiniScreen {
''' + activate + '''
}
MiniScreen.activate(41)
precondition(Process.launched.isEmpty, "refocusing asked for System Events Automation")
Apps.allowed = ["com.apple.systemevents"]
let began = Date()
MiniScreen.activate(42)
precondition(Date().timeIntervalSince(began) < 0.3, "activation blocked UI")
MiniScreen.activate(43)
let completed = Process.launched[1]
completed.isRunning = false; completed.terminationHandler?(completed)
RunLoop.current.run(until: Date().addingTimeInterval(2.3))
precondition(Process.launched[0].terminated, "stalled activation was not terminated")
precondition(!completed.terminated && completed.terminationHandler == nil, "completed activation retained its timeout")
''')

    def test_speech_timing_records_each_stage_once_across_audio_and_ui_queues(self):
        source = (ROOT / 'Atticus.swift').read_text()
        trace = source[source.index('final class SpeechTrace:'):source.index('// Opens only the chosen mic.')]
        heard = source[source.index('    func heard(_ now: String)'):source.index('    func pauseWait()')]
        self.assertNotIn('speechTrace', source[source.index('    func js(_ call: String'):source.index('    var pointerNext')])   # typed and demo words are not speech
        self.assertLess(heard.index('js("words", text)'), heard.index('trace.mark("ui_submitted")'))
        self.swift('import Foundation\n' + trace + r'''
let trace = SpeechTrace("fixture")
let lock = NSLock()
var first = 0
DispatchQueue.concurrentPerform(iterations: 100) { _ in
    if trace.mark("first_buffer") { lock.lock(); first += 1; lock.unlock() }
}
precondition(first == 1)
precondition(trace.mark("first_partial") && !trace.mark("first_partial"))
''')

    def test_mic_serializes_sessions_and_ignores_cancelled_starts(self):
        source = (ROOT / 'Atticus.swift').read_text()
        mic = source[source.index('final class SpeechTrace:'):source.index('    func captureOutput(', source.index('final class Mic:'))] + '}\n'
        self.swift('''import Foundation
protocol AVCaptureAudioDataOutputSampleBufferDelegate {}
final class AVAudioPCMBuffer {}
let AVFormatIDKey = "format", AVSampleRateKey = "rate", AVNumberOfChannelsKey = "channels"
let AVLinearPCMBitDepthKey = "bits", AVLinearPCMIsFloatKey = "float", AVLinearPCMIsNonInterleaved = "interleaved"
let kAudioFormatLinearPCM = 1
final class AVCaptureDevice { var localizedName = "Fake"; var fail = false }
final class AVCaptureDeviceInput {
 init(device: AVCaptureDevice) throws { precondition(!Thread.isMainThread); if device.fail { throw CocoaError(.fileReadUnknown) } }
}
final class AVCaptureAudioDataOutput {
 var audioSettings: [String: Any] = [:]
 func setSampleBufferDelegate(_ delegate: Any, queue: DispatchQueue) {}
}
final class AVCaptureSession {
 static let lock = NSLock()
 static var active = 0, starts = 0, stops = 0
 var isRunning = false
 func canAddInput(_ input: AVCaptureDeviceInput) -> Bool { true }
 func canAddOutput(_ output: AVCaptureAudioDataOutput) -> Bool { true }
 func addInput(_ input: AVCaptureDeviceInput) {}
 func addOutput(_ output: AVCaptureAudioDataOutput) {}
 func startRunning() {
  precondition(!Thread.isMainThread); Thread.sleep(forTimeInterval: 0.2)
  Self.lock.lock(); Self.active += 1; Self.starts += 1; precondition(Self.active == 1); Self.lock.unlock(); isRunning = true
 }
 func stopRunning() {
  precondition(!Thread.isMainThread); Thread.sleep(forTimeInterval: 0.1)
  Self.lock.lock(); Self.active -= 1; Self.stops += 1; Self.lock.unlock(); isRunning = false
 }
}
''' + mic + '''
let mic = Mic(), device = AVCaptureDevice()
var stale = 0, ready = 0, errors = 0, drained = 0
let began = Date()
mic.start(device, sampleRate: 16000, { _ in }) { _ in stale += 1 }
precondition(mic.isRunning)
mic.stop(); precondition(!mic.isRunning)
mic.start(device, sampleRate: 16000, { _ in }) { result in
 precondition(Thread.isMainThread); if case .success = result { ready += 1 }
 mic.stop { precondition(Thread.isMainThread); drained += 1 }
}
precondition(Date().timeIntervalSince(began) < 0.1, "mic start/stop blocked UI")
RunLoop.current.run(until: Date().addingTimeInterval(1))
precondition(stale == 0 && ready == 1 && drained == 1 && !mic.isRunning)
AVCaptureSession.lock.lock(); precondition(AVCaptureSession.starts == 2 && AVCaptureSession.stops == 2 && AVCaptureSession.active == 0); AVCaptureSession.lock.unlock()
device.fail = true
mic.start(device, sampleRate: 16000, { _ in }) { result in
 precondition(Thread.isMainThread && !mic.isRunning); if case .failure = result { errors += 1 }
}
RunLoop.current.run(until: Date().addingTimeInterval(0.3))
precondition(errors == 1)
''')
        start = source[source.index('        engine.start(device,'):source.index('    func heard(')]
        self.assertIn('listenID == listeningID', start)
        self.assertLess(start.index('if case .failure'), start.index('began = Date()'))

    def test_archive_serializes_batched_writes_off_main_and_reports_errors(self):
        source = (ROOT / 'Atticus.swift').read_text()
        archive = source[source.index('final class MeetingArchive'):source.index('final class MeetingAudio')]
        terminate = source[source.index('    func applicationShouldTerminate('):source.index('    func applicationShouldHandleReopen(')]
        self.swift('''import Foundation
import Darwin
enum Prefs { static let root = NSTemporaryDirectory() + UUID().uuidString; static let path = root + "/settings.json" }
let gate = DispatchSemaphore(value: 0)
final class FileHandle {
 let fd: Int32
 static var writes: [String] = [], syncs = 0, fail = false
 init(fileDescriptor: Int32, closeOnDealloc: Bool) { fd = fileDescriptor }
 func write(contentsOf data: Data) throws {
  precondition(!Thread.isMainThread, "archive write blocked UI")
  if Self.fail { throw CocoaError(.fileWriteOutOfSpace) }
  Self.writes.append(String(decoding: data, as: UTF8.self))
 }
 func synchronize() throws {
  precondition(!Thread.isMainThread, "archive sync blocked UI")
  Self.syncs += 1
  if Self.syncs == 1 || Self.syncs == 3 { precondition(gate.wait(timeout: .now() + 2) == .success) }
 }
 func close() throws { Darwin.close(fd) }
}
''' + archive + '''
defer { try? FileManager.default.removeItem(atPath: Prefs.root) }
let archive = try! MeetingArchive(title: "Fake", app: "Fake", started: Date())
var completed = 0, failed = 0
let began = Date()
archive.append([["kind": "partial"], ["kind": "checkpoint"]]) { error in
 precondition(Thread.isMainThread && error == nil); completed += 1
}
archive.append([["kind": "ended"]]) { error in
 precondition(Thread.isMainThread && error == nil); completed += 1
}
precondition(Date().timeIntervalSince(began) < 0.1, "append waited for disk")
gate.signal()
RunLoop.current.run(until: Date().addingTimeInterval(0.3))
precondition(completed == 2 && FileHandle.syncs == 2 && FileHandle.writes.count == 2)
let first = FileHandle.writes[0].split(separator: "\\n")
precondition(first.count == 2 && first[0].contains("partial") && first[1].contains("checkpoint"))
precondition(FileHandle.writes[1].contains("ended"), "archive events reordered")
FileHandle.fail = true
archive.append([["kind": "transcript"]]) { error in
 precondition(Thread.isMainThread && error != nil); failed += 1
}
RunLoop.current.run(until: Date().addingTimeInterval(0.3))
precondition(failed == 1 && FileHandle.writes.count == 2)
FileHandle.fail = false
final class NSApplication {
 enum TerminateReply { case terminateLater }
 var replied = false
 func reply(toApplicationShouldTerminate: Bool) { precondition(Thread.isMainThread); replied = toApplicationShouldTerminate }
}
final class FakeQuiet { func end(immediate: Bool) {} }
final class FakeDrawing { func clear() {} }
final class FakeApp { let quietAudio = FakeQuiet(), drawing = FakeDrawing(); func hush() {}; func shush() {} }
final class FakeMeeting {
 func discard() { archive.append([["kind": "ended"]]) { error in precondition(error == nil) } }
}
let meeting = FakeMeeting(), app = FakeApp()
final class Delegate {
''' + terminate + """
}
let application = NSApplication()
let reply = Delegate().applicationShouldTerminate(application)
precondition(reply == .terminateLater && !application.replied, "quit waited synchronously or exited before save")
gate.signal()
RunLoop.current.run(until: Date().addingTimeInterval(0.3))
precondition(application.replied && FileHandle.syncs == 3 && FileHandle.writes.count == 3, "quit lost pending archive writes")
""")
        finish = source[source.index('    func finishArchive('):source.index('    func savingChanged(')]
        self.assertLess(finish.index('archive.append('), finish.index('if error != nil'))
        self.assertLess(finish.index('if error != nil'), finish.index('let p = py('))
        save = source[source.index('    func saveEvents('):source.index('    func beginArchive(')]
        self.assertIn('self.archive === archive', save)
