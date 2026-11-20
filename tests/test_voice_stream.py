"""Offline sentence ordering, cap and markup regression; no voice or microphone."""
from pathlib import Path
import unittest
from tests import run_swift


class VoiceStreamTests(unittest.TestCase):
    def test_sentences_are_ordered_once_capped_and_resettable(self):
        source = (Path(__file__).resolve().parents[1] / 'Atticus.swift').read_text()
        policy = source[source.index('struct SpeechSentences'):source.index('// Read-aloud uses')]
        spoken = source[source.index('func spoken('):source.index('// Cumulative, filtered')]
        run_swift(self, 'import Foundation\n' + spoken + policy + r'''
var q = SpeechSentences()
precondition(q.take("First.").isEmpty)
precondition(q.take("First. Second") == ["First."])
precondition(q.take("First. Second sentence! Third") == ["Second sentence!"])
precondition(q.take("First. Second sentence! Third", final: true) == ["Third"])
precondition(q.take("First. Second sentence! Third", final: true).isEmpty)
q = SpeechSentences()
precondition(q.take("First. ") == ["First."])
precondition(q.take("First. " + String(repeating: "x", count: 900), final: true) == ["The rest is on screen."])
precondition(q.take("No more.", final: true).isEmpty)
q = SpeechSentences()
precondition(q.take("New answer.", final: true) == ["New answer."])
precondition(readAloudText("**Hello.** `secret()` <tag> ```code.``` End.") == "Hello. End.")
q = SpeechSentences()
precondition(q.take("Options:\nApples\nBananas") == ["Options:", "Apples"])
q = SpeechSentences()
precondition(q.take("你好。今天") == ["你好。"])
q = SpeechSentences()
let list = q.take((0..<40).map { "Item \($0) " + String(repeating: "x", count: 30) }.joined(separator: "\n"), final: true)
precondition(list.first!.hasPrefix("Item 0 ") && list.count > 20 && list.last == "The rest is on screen.")
print("sentence order, final flush, cap, reset, markup, lines and CJK: OK")
''')

    def test_shush_mutes_only_what_it_stopped_and_one_voice_reads_an_answer(self):
        source = (Path(__file__).resolve().parents[1] / 'Atticus.swift').read_text()
        spoken = source[source.index('func spoken('):source.index('// Read-aloud uses')]
        speech = source[source.index('    var voice: Process?'):source.index('    func deliver(_ a: String')]
        along = source[source.index('    func drawAlong('):source.index('    func leadToDrawing(')]
        policy = next(line.strip() for line in source.splitlines() if 'drawing.speechEnabled =' in line)
        navigation = source[source.index('        drawing.navigated ='):source.index('        drawing.status =')]
        run_swift(self, 'import Foundation\n' + spoken + r'''
enum Prefs { static var speak = true; static func bool(_ key: String) -> Bool { key == "speak" ? speak : true } }
func telemetry(_ args: [String]) {}
var picks = 0
func readAloudArguments(_ words: String, compactTip: () -> Void) -> [String] { picks += 1; return ["-v", "Voice\(picks)", "--", words] }
final class Process {
    static var started: [Process] = []
    var executableURL: URL?, arguments: [String]?, terminationHandler: ((Process) -> Void)?, isRunning = false
    func run() throws { isRunning = true; Process.started.append(self) }
    func terminate() { isRunning = false }
    func finish() { isRunning = false; terminationHandler?(self); RunLoop.main.run(until: Date().addingTimeInterval(0.05)) }
}
struct Guide { let guide: String }
final class Drawing {
    var manual = false, waiting = false, index = 0   // ScreenDrawing: a step waiting for the user's click holds the next sentence
    var navigated: ((Bool) -> Void)?
    var driven = false, shown: [Int] = [], guides: [String] = [], request: Guide?, voice: Process?
    var speechEnabled: () -> Bool = { false }
    func stopVoice() { voice?.terminate(); voice = nil }
    func update(_ data: Data) -> Bool { let guide = String(decoding:data,as:UTF8.self); request = Guide(guide:guide); guides.append(guide); shown.append(0); return true }
    func reveal(_ step: Int) { shown.append(step) }
}
final class Speaker {
    var cueEnds = Date.distantPast
    let drawing = Drawing()
    func stopWake() {}; func show() {}; func js(_ name: String, _ value: Any? = nil) {}; func hide(after s: Double) {}; func leadToDrawing() {}
''' + '    init() { ' + policy + '\n' + navigation + ' }\n' + speech + along + r'''
}
let c = Speaker()
c.spokenSoFar = "Intro. "; c.streamSpeech(c.spokenSoFar)
c.drawAlong(Data("g1".utf8), guide:"g1", steps:1)
precondition(c.drawing.guides == ["g1"] && c.drawing.driven && c.voice?.arguments?.last == "Intro.", "the first scene waited behind words that caption no step")
c.drawAlong(Data("g1".utf8), guide:"g1", steps:1)
c.spokenSoFar = "Intro. One. "; c.streamSpeech(c.spokenSoFar)
c.drawAlong(Data("g2".utf8), guide:"g2", steps:1)
precondition(c.drawing.guides == ["g1", "g1"], "a scene after a clear jumped ahead of the last scene's sentence")
Process.started.last!.finish()
precondition(c.drawing.guides.first == "g1", "A clear arriving ahead of speech replaced the queued first scene")
Process.started.last!.finish()
precondition(c.drawing.guides == ["g1", "g1", "g2"], "A scene was lost or drawn twice")   // the shown scene's second tag only grows it
_ = c.shush(); Process.started.removeAll(); picks = 0
let muted = Speaker()
muted.spokenSoFar = "Intro. "; muted.streamSpeech(muted.spokenSoFar)
muted.drawAlong(Data("g1".utf8), guide:"g1", steps:1)
muted.drawAlong(Data("g2".utf8), guide:"g2", steps:1)
precondition(muted.shush() && muted.drawing.guides == ["g1", "g2"] && !muted.drawing.driven && muted.pendingDrawings.isEmpty && !muted.drawing.speechEnabled(),
             "Shush did not hand the latest scene back to ordinary steps")
Process.started.removeAll(); picks = 0
let fallback = Speaker()
_ = fallback.drawing.update(Data("inline".utf8))
let narration = Process(); try! narration.run(); fallback.drawing.voice = narration
precondition(fallback.shush() && !narration.isRunning && !fallback.drawing.speechEnabled(), "Shush left the guide's fallback voice running")
let legacy = Speaker(); legacy.speechMuted = true
precondition(legacy.drawing.speechEnabled(), "Inline shush changed ordinary tool-guide narration")
Process.started.removeAll(); picks = 0
let d = Speaker()   // a streamed drawing's steps show between the sentences that name them
d.pendingDrawings["g"] = Data("g".utf8); d.speechQueue = ["Intro.", "\u{1}g:0", "Axes.", "\u{1}g:1", "Curve."]; d.speakNext()
precondition(d.drawing.shown.isEmpty && Process.started.last!.arguments!.last == "Intro.")
Process.started.last!.finish(); precondition(d.drawing.shown == [0, 0] && d.drawing.driven && Process.started.last!.arguments!.last == "Axes.")
Process.started.last!.finish(); precondition(d.drawing.shown == [0, 0, 1])
Process.started.last!.finish(); _ = d.shush(); precondition(!d.drawing.driven, "a shushed guide did not step on by itself")
Process.started.removeAll(); picks = 0
let s = Speaker()
precondition(!s.shush() && !s.speechMuted)   // a toggle's second press: nothing playing, its answer still speaks
s.streamSpeech("Hola. Two? Three", final: true)
Process.started.last!.finish(); Process.started.last!.finish()
precondition(Process.started.map { $0.arguments! } == [["-v", "Voice1", "--", "Hola."], ["-v", "Voice1", "--", "Two?"], ["-v", "Voice1", "--", "Three"]])
Process.started.last!.finish()
precondition(!s.shush() && !s.speechMuted)
s.streamSpeech("Next answer. More. ")
precondition(s.shush() && s.speechMuted)   // stopped mid-answer: the rest of it stays quiet
s.streamSpeech("Next answer. More. Later.", final: true)
precondition(Process.started.count == 4 && Process.started.last!.arguments! == ["-v", "Voice2", "--", "Next answer."] && !Process.started.last!.isRunning)
let jumped = Speaker()
jumped.drawAlong(Data("jump".utf8),guide:"jump",steps:2)
jumped.streamSpeech("Old step. Next sentence. ")
let obsolete = jumped.voice
jumped.drawing.manual = true; jumped.drawing.navigated?(false)
precondition(jumped.voice == nil && jumped.speechQueue.isEmpty && jumped.pendingDrawings.isEmpty && !jumped.speechMuted)
obsolete?.finish()
jumped.streamSpeech("Old step. Next sentence. Late text.",final:true)
precondition(jumped.voice == nil && jumped.speechQueue.isEmpty,"Late stream restarted old narration after navigation")
jumped.drawAlong(Data("jump".utf8),guide:"jump",steps:3)
precondition(jumped.speechQueue.isEmpty && !jumped.drawing.driven,"Late drawing cue overrode navigation")
_ = jumped.shush(); jumped.speechMuted = false
jumped.streamSpeech("Preview.",final:true,preview:true)
precondition(jumped.voice?.arguments?.last == "Preview.","Guide navigation blocked an explicit voice preview")
_ = jumped.shush(); jumped.speechMuted = false; jumped.drawQueued = ("",0)
jumped.streamSpeech("Follow up.",final:true)
precondition(jumped.voice?.arguments?.last == "Follow up.","An old guide blocked the next answer's narration")
_ = jumped.shush(); Process.started.removeAll(); Prefs.speak = false
let silent = Speaker()   // read-aloud off: the guide's own reading time steps it, never a sentence
silent.spokenSoFar = "Intro. "; silent.streamSpeech(silent.spokenSoFar)
silent.drawAlong(Data("quiet".utf8),guide:"quiet",steps:1)
silent.drawAlong(Data("quiet".utf8),guide:"quiet",steps:2)
precondition(silent.drawing.guides == ["quiet","quiet"] && !silent.drawing.driven && silent.speechQueue.isEmpty && silent.pendingDrawings.isEmpty
             && Process.started.isEmpty && !silent.drawing.speechEnabled(),"A silent guide waited on narration")
Prefs.speak = true
print("shush and per-answer voice: OK")
''')

    def test_apple_release_schedules_200ms_tail(self):
        source = (Path(__file__).resolve().parents[1] / 'Atticus.swift').read_text()
        start = source.index('        whisperReleasing = whisperListen && !clickTalk && !toggleTalk', source.index('    func dropAhead()'))
        schedule = source[start:source.index('        quietAudio.end()', start)]
        output = run_swift(self, 'import Foundation\n' + r'''
let whisperListen = false, clickTalk = false, toggleTalk = false
var whisperReleasing = false
var samples: [Double] = []
for _ in 0..<5 {
    let began = Date()
    var elapsed: Double? = nil
    let stopMic = { elapsed = Date().timeIntervalSince(began) }
''' + schedule + r'''
    while elapsed == nil { RunLoop.current.run(until: Date().addingTimeInterval(0.002)) }
    precondition(elapsed! >= 0.19 && elapsed! < 1)
    samples.append(elapsed! * 1000)
}
print("Apple release callback ms: " + samples.map { String(format: "%.2f", $0) }.joined(separator: ", "))
''')
        print(output.strip())
