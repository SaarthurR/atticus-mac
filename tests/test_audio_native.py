"""Audio policy regressions with fake devices and volume; never touches VM audio hardware."""
from pathlib import Path
import sys
import unittest

from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin", "macOS Swift audio regression")
class AudioNativeTests(unittest.TestCase):
    def test_read_aloud_never_overwrites_system_voice_or_trusts_siri_probe(self):
        source = (ROOT / "Atticus.swift").read_text()
        self.assertNotIn("CFPreferencesSetAppValue", source)
        self.assertNotIn("siriVoice", source)
        deliver = source[source.index("    func deliver("):source.index("    func linger(")]
        self.assertIn("readAloudArguments(spoken(a))", deliver)
        drawing = source[source.index("final class ScreenDrawing"):source.index("// The box can take typing")]
        self.assertIn("p.arguments = sayArguments(words)", drawing)

    def test_best_installed_english_voice_prefers_quality_then_region(self):
        source = (ROOT / "Atticus.swift").read_text()
        policy = source[source.index("struct ReadAloudVoice"):source.index("func sayVoiceNames")]
        run_swift(self, """import Foundation
import AVFoundation
""" + policy + """
let fixture = [
    ReadAloudVoice(name: "US Enhanced", language: "en-US", quality: .enhanced),
    ReadAloudVoice(name: "UK Premium", language: "en-GB", quality: .premium),
    ReadAloudVoice(name: "US Premium", language: "en-US", quality: .premium),
    ReadAloudVoice(name: "French Premium", language: "fr-FR", quality: .premium)]
precondition(bestEnglishVoice(fixture, region: "US")?.name == "US Premium")
precondition(bestEnglishVoice(Array(fixture.prefix(2)), region: "US")?.name == "UK Premium")
precondition(bestEnglishVoice([fixture.last!], region: "US") == nil)
let compact = [ReadAloudVoice(name: "Albert", language: "en-US", quality: .default),
               ReadAloudVoice(name: "Samantha", language: "en-US", quality: .default)]
precondition(bestEnglishVoice(compact, region: "US") == nil)
let installed = AVSpeechSynthesisVoice.speechVoices().map {
    ReadAloudVoice(name: $0.name, language: $0.language, quality: $0.quality)
}
if installed.contains(where: { $0.language.lowercased().hasPrefix("en") && ($0.quality == .premium || $0.quality == .enhanced) }) {
    let picked = bestEnglishVoice(installed, region: Locale.current.region?.identifier)
    precondition(picked?.quality == .premium || picked?.quality == .enhanced)
}
print("read-aloud voice policy ok")
""")

    def test_say_voice_is_validated_and_compact_tip_is_once(self):
        source = (ROOT / "Atticus.swift").read_text()
        voice = source[source.index("let installedSayVoices"):source.index("// The talk shortcut")]
        self.assertIn('p.arguments = ["-v", "?"]', voice)
        self.assertNotIn('"-v", "?"', voice[voice.index("func usableReadAloudVoice"):])   # listed once, not per read
        self.assertIn("preferredReadAloudVoice(selections", voice)
        self.assertIn("if voice == nil { compactTip() }", voice)
        tip = source[source.index("    func voiceQualityTip()"):source.index("    @discardableResult func shush()")]
        self.assertIn('bool(forKey: "voiceQualityTip")', tip)
        self.assertIn('set(true, forKey: "voiceQualityTip")', tip)
        self.assertIn("Manage Voices", tip)

    def test_say_voice_list_parser_handles_spaces_and_rejects_unknown_names(self):
        source = (ROOT / "Atticus.swift").read_text()
        parser = source[source.index("func sayVoiceNames"):source.index("func preferredReadAloudVoice")]
        run_swift(self, "import Foundation\n" + parser + """
let names = sayVoiceNames("Bad News            en_US    # Hello\\nDaniel (English (UK)) en_GB    # Hello\\n")
precondition(names == ["Bad News", "Daniel (English (UK))"])
precondition(sayVoiceName("Ava", names: ["Ava", "Ava (Premium)"]) == "Ava")
precondition(sayVoiceName("Ava", names: ["Ava (Enhanced)", "Ava (Premium)"]) == "Ava (Premium)")
precondition(sayVoiceName("Ava", names: ["Ava (Enhanced)"]) == "Ava (Enhanced)")
precondition(sayVoiceName("Daniel", names: names) == "Daniel (English (UK))")
precondition(sayVoiceName("Voice 2", names: names) == nil)
print("say voice list parser ok")
""")

    def test_saved_voice_and_unavailable_voice_fallback(self):
        source = (ROOT / "Atticus.swift").read_text()
        policy = source[source.index("struct ReadAloudVoice"):source.index("let installedSayVoices")]
        arguments = source[source.index("func readAloudArguments"):source.index("// The talk shortcut")]
        self.assertIn('language: NLLanguageRecognizer.dominantLanguage(for: words)', source[source.index("func usableReadAloudVoice"):source.index("func readAloudArguments")])
        run_swift(self, "import Foundation\nimport AVFoundation\nfunc usableReadAloudVoice(_ words: String) -> String? { nil }\n" + policy + arguments + """
let voices = [
    ReadAloudVoice(name: "Unavailable", language: "en-US", quality: .premium, identifier: "missing-say"),
    ReadAloudVoice(name: "Tessa", language: "en-ZA", quality: .enhanced, identifier: "tessa"),
    ReadAloudVoice(name: "US Premium", language: "en-US", quality: .premium, identifier: "premium"),
    ReadAloudVoice(name: "Monica", language: "es-ES", quality: .enhanced, identifier: "monica")]
let names: Set<String> = ["Tessa", "Tessa (Enhanced)", "US Premium", "Samantha", "Monica (Enhanced)"]
func pick(_ saved: [Any], selected: String = "", os: Int = 27, installed: [ReadAloudVoice] = voices, language: String = "en") -> String? {
    preferredReadAloudVoice(saved, voices: installed, names: names, selected: selected, region: "US", majorVersion: os, language: language)
}
func say(_ voice: String?) -> ([String], Bool) {
    var tipped = false
    return (readAloudArguments("hi", pick: { _ in voice }) { tipped = true }, tipped)
}
let bilingual: [Any] = ["es", ["voiceId": "monica"], "en-US", ["voiceId": "tessa"]]
precondition(pick(bilingual) == "Tessa (Enhanced)", "an English answer used the saved Spanish voice")
precondition(pick(bilingual, language: "es") == "Monica (Enhanced)", "a Spanish answer skipped the saved Spanish voice")
precondition(pick(["es", ["voiceId": "monica"]], language: "fr") == "US Premium", "a French answer used the saved Spanish voice")
precondition(pick(["es", ["voiceId": "unlisted-system-voice"]], os: 26) == "US Premium", "another language's unlisted voice took over English")
let unknown: [Any] = ["en", ["voiceId": "unlisted-system-voice"]]
for os in [26, 27] {
    precondition(pick(["en", ["voiceId": "tessa"]], os: os) == "Tessa (Enhanced)", "saved voice ignored on \\(os)")
    precondition(pick(unknown, selected: "Samantha", os: os) == "Samantha")
}
precondition(say(pick(unknown, os: 26)) == (["--", "hi"], false), "macOS 26 lost the unlisted system voice or showed the tip")
precondition(say(pick(unknown, os: 26, installed: [])) == (["--", "hi"], false))
precondition(say(pick(unknown, os: 27)) == (["-v", "US Premium", "--", "hi"], false), "macOS 27 skipped the installed natural voice")
precondition(say(pick(unknown, os: 27, installed: [])) == (["--", "hi"], true))
let siri: [Any] = ["de", ["voiceId": "com.apple.siri.natural.de-DE-C"], "en", ["voiceId": "tessa"]]
for os in [26, 27] {
    precondition(say(pick(siri, os: os, language: "de")) == (["--", "hi"], false), "a German answer lost the saved Siri voice on \\(os)")
}
precondition(pick(siri, language: "en") == "Tessa (Enhanced)", "an English answer used the German Siri voice")
precondition(pick(["de", ["voiceId": "com.apple.siri.natural.de-DE-C"]], language: "fr") == "US Premium", "a French answer used the German Siri voice")
precondition(pick(["unexpected schema"], os: 26) == "US Premium")
precondition(pick([], selected: "deleted voice", os: 26) == "US Premium")
precondition(pick(["unexpected schema"]) == "US Premium")
precondition(pick([], selected: "Samantha") == "Samantha")
precondition(pick([], selected: "deleted voice") == "US Premium")
precondition(pick([]) == "US Premium", "unusable top-ranked voice blocked fallback")
precondition(preferredReadAloudVoice([], voices: voices, names: [], selected: "", region: "US", majorVersion: 27) == nil)
print("saved voice and fallback ok")
""")

    def test_device_choice_falls_back_without_opening_bluetooth(self):
        source = (ROOT / "Atticus.swift").read_text()
        policy = source[source.index("struct MicrophoneDevice"):source.index("func listenMic()")]
        run_swift(self, 
            """import Foundation
import CoreAudio
func audioProp<T>(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector, _ zero: T) -> [T] { [] }
func audioString(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector) -> String? { nil }
"""
            + policy
            + """
let builtIn = MicrophoneDevice(id: 1, uid: "built-in", name: "MacBook Microphone", transport: kAudioDeviceTransportTypeBuiltIn)
let bluetooth = MicrophoneDevice(id: 2, uid: "bluetooth", name: "Headphones", transport: kAudioDeviceTransportTypeBluetooth)
let usb = MicrophoneDevice(id: 3, uid: "usb", name: "Studio Mic", transport: kAudioDeviceTransportTypeUSB)
let devices = [builtIn, bluetooth, usb]
precondition(chooseMic("usb", devices, 2)?.id == 3, "remembered UID was ignored")
precondition(chooseMic("gone", devices, 2)?.id == 1, "missing choice did not use Automatic")
precondition(chooseMic("automatic", devices, 2)?.id == 1, "Automatic selected the Bluetooth input")
precondition(chooseMic("automatic", devices, 3)?.id == 3, "Automatic ignored a non-Bluetooth default")
precondition(chooseMic("automatic", [bluetooth], 2)?.id == 2, "Automatic lost the only available input")
print("microphone policy ok")
"""
        )
        start = source[source.index("    func start()", source.index("final class App")):source.index("    func heard(", source.index("final class App"))]
        self.assertIn("AVCaptureDevice(uniqueID: $0.uid)", start)   # opens only the chosen mic
        self.assertNotIn("AVAudioEngine()", source)   # its input node opens the default (Bluetooth) mic first
        self.assertIn("cfg.microphoneCaptureDeviceID = microphoneID", source)
        self.assertIn("microphoneID: demo ? nil : listenMic()?.uid", source)

    def test_quiet_audio_restores_release_and_cancel(self):
        source = (ROOT / "Atticus.swift").read_text()
        model = source[source.index("struct AudioVolumeSnapshot"):source.index("struct CoreAudioVolume")]
        quiet = source[source.index("final class AudioQuiet"):source.index("enum AudioRecovery")]
        run_swift(self, 
            """import Foundation
"""
            + model
            + quiet
            + """
final class FakeAudio: AudioVolumeLayer {
    var volume: Float32 = 0.8, reads = 0, writes: [Float32] = [], mediaPaused = true, failAt: Int?
    func snapshot() -> AudioVolumeSnapshot? {
        reads += 1
        return AudioVolumeSnapshot(uid: "fixture", selector: 1, volume: volume, owner: 1)
    }
    func set(_ snapshot: AudioVolumeSnapshot, volume: Float32) -> Bool {
        writes.append(volume)
        if writes.count == failAt { return false }
        self.volume = volume; return true
    }
}
let now: (TimeInterval, @escaping () -> Void) -> Void = { _, work in work() }
let offLayer = FakeAudio(), off = AudioQuiet(layer: offLayer, later: now)
off.begin(false)
precondition(offLayer.reads == 0 && offLayer.writes.isEmpty && offLayer.mediaPaused, "setting off changed audio or playback")

let layer = FakeAudio()
var marker: AudioVolumeSnapshot?
let quiet = AudioQuiet(layer: layer, changed: { marker = $0 }, later: now)
quiet.begin(true)
precondition(abs(layer.volume - 0.144) < 0.001 && layer.mediaPaused, "listening did not quiet audio or started paused media")
quiet.end()
precondition(layer.volume == 0.8 && marker == nil, "release did not restore the exact volume")

quiet.begin(true); quiet.end()
precondition(layer.volume == 0.8, "cancel did not restore the exact volume")

quiet.begin(true); layer.failAt = layer.writes.count + 6; quiet.end()
precondition(layer.volume == 0.8 && marker == nil, "a missing output device did not retry the restore")
print("quiet audio policy ok")
"""
        )


if __name__ == "__main__":
    unittest.main()
