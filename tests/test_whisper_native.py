"""Whisper engine (Atticus.swift `// MARK: Whisper` section) compiled alone against a scratch ATTICUS_DIR."""
import functools
import hashlib
import http.server
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]
TURBO = Path(os.environ.get("ATTICUS_WHISPER_TURBO", "~/Library/Application Support/whisper-models/ggml-large-v3-turbo-q5_0.bin")).expanduser()


def engine():
    source = (ROOT / "Atticus.swift").read_text()
    prefs = source[source.index("enum Prefs"):source.index("func applySharing(")]
    whisper = source[source.index("// MARK: Whisper"):source.index("// MARK: end Whisper")]
    return "import Cocoa\nimport AVFoundation\nimport CryptoKit\nlet controlKey = 1, optionKey = 2\n" + prefs + whisper


@unittest.skipUnless(sys.platform == "darwin", "macOS Swift regression")
class WhisperNativeTests(unittest.TestCase):
    def scratch(self):
        root = tempfile.mkdtemp(prefix="atticus-whisper-"); self.addCleanup(shutil.rmtree, root, True)
        p = patch.dict(os.environ, {"ATTICUS_DIR": root}); p.start(); self.addCleanup(p.stop)
        return Path(root)

    def test_wav_audio_and_catalog(self):
        self.scratch()
        run_swift(self, engine() + """
let w = Whisper.wav([0, 1, -1, 0.5])
precondition(w.count == 44 + 8)
precondition(String(decoding: w.prefix(4), as: UTF8.self) == "RIFF" && String(decoding: w[8..<16], as: UTF8.self) == "WAVEfmt ")
precondition(Array(w[4..<8]) == [44, 0, 0, 0])               // 36 + data bytes
precondition(Array(w[22..<28]) == [1, 0, 0x80, 0x3e, 0, 0])   // mono, 16000 Hz
precondition(Array(w[34..<36]) == [16, 0] && String(decoding: w[36..<40], as: UTF8.self) == "data" && Array(w[40..<44]) == [8, 0, 0, 0])
precondition(Array(w[44...]) == [0, 0, 0xff, 0x7f, 0x01, 0x80, 0xff, 0x3f])
precondition(Whisper.models.map(\\.id) == ["turbo", "large", "small"])
precondition(Whisper.model("large").file == "ggml-large-v3-q5_0.bin" && Whisper.model("nope").id == "turbo" && Whisper.model("").id == "turbo")
precondition(Whisper.dir.hasSuffix("/whisper") && Whisper.freePort()! > 1024 && Whisper.threads >= 1)
let a = WhisperAudio(), f = AVAudioFormat(standardFormatWithSampleRate: 16000, channels: 1)!
let b = AVAudioPCMBuffer(pcmFormat: f, frameCapacity: 8000)!; b.frameLength = 8000
a.append(b); a.append(b)
precondition(a.seconds == 1 && a.snapshot().count == 16000 && a.take().count == 16000 && a.seconds == 0)
let sem = DispatchSemaphore(value: 0)
Task {
    let quiet = try await Whisper.shared.transcribe([Float](repeating: 0.004, count: 32000), prompt: "")   // silence: no server
    let tap = try await Whisper.shared.transcribe([0.5, -0.5], prompt: "")
    precondition(quiet == "" && tap == "")
    sem.signal()
}
sem.wait()
print("ok")
""")

    def test_status_and_sha(self):
        root = self.scratch()
        (root / "whisper").mkdir()
        (root / "whisper" / "ggml-large-v3-q5_0.bin").write_bytes(b"x")
        blob = root / "blob"; blob.write_bytes(os.urandom(5_000_000))
        out = run_swift(self, engine() + f"""
precondition(Whisper.sha256("{blob}") == "{hashlib.sha256(blob.read_bytes()).hexdigest()}")
precondition(Whisper.sha256("/nonexistent") == nil)
precondition(!Whisper.shared.ready)   // turbo (the default) is missing
Prefs.set("whisperModel", "large")
precondition(Whisper.shared.ready == (Whisper.serverPath() != nil))
let s = Whisper.shared.status()
precondition(JSONSerialization.isValidJSONObject(s))
print(String(decoding: try! JSONSerialization.data(withJSONObject: s, options: .sortedKeys), as: UTF8.self))
""")
        import json
        s = json.loads(out)
        self.assertEqual(set(s), {"server", "model", "running", "error", "models"})
        self.assertEqual((s["model"], s["running"], s["error"]), ("large", False, None))
        self.assertEqual(s["server"], shutil.which("whisper-server") is not None or os.path.exists("/opt/homebrew/bin/whisper-server"))
        self.assertEqual([(m["id"], m["have"], m["progress"]) for m in s["models"]], [("turbo", False, None), ("large", True, None), ("small", False, None)])
        self.assertEqual(s["models"][0]["size"], "574 MB")
        self.assertEqual(s["models"][1]["name"], "Large v3")

    def test_download_verifies_sha_and_never_leaves_a_bad_file(self):
        root = self.scratch()
        site = root / "site"; site.mkdir()
        data = os.urandom(3_000_000); (site / "good.bin").write_bytes(data); (site / "bad.bin").write_bytes(data)
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a): pass
        handler = functools.partial(Quiet, directory=str(site))
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start(); self.addCleanup(httpd.shutdown)
        sha = hashlib.sha256(data).hexdigest()
        run_swift(self, engine() + f"""
Whisper.base = "http://127.0.0.1:{httpd.server_address[1]}/"
Whisper.models = [Whisper.Model(id: "good", name: "Good", file: "good.bin", sha256: "{sha}", bytes: {len(data)}),
                  Whisper.Model(id: "bad", name: "Bad", file: "bad.bin", sha256: "{'0' * 64}", bytes: {len(data)}),
                  Whisper.Model(id: "gone", name: "Gone", file: "missing.bin", sha256: "{sha}", bytes: 1)]
let w = Whisper.shared, sem = DispatchSemaphore(value: 0)
func fetch(_ id: String) -> [String: Any] {{
    w.download(id) {{ sem.signal() }}
    w.download(id) {{ preconditionFailure("second download of one id") }}
    var model: [String: Any] = [:]
    for _ in 0..<200 {{
        _ = sem.wait(timeout: .now() + 0.1)
        model = (w.status()["models"] as! [[String: Any]]).first {{ $0["id"] as? String == id }}!
        if model["progress"] is NSNull {{ return model }}
    }}
    preconditionFailure("download of \\(id) never finished")
}}
let fm = FileManager.default
precondition(fetch("good")["have"] as? Bool == true && w.status()["error"] is NSNull)
precondition(fm.contents(atPath: Whisper.dir + "/good.bin")?.count == {len(data)} && !fm.fileExists(atPath: Whisper.dir + "/good.bin.part"))
precondition(fetch("bad")["have"] as? Bool == false && w.status()["error"] as? String == "The download didn’t match. Try again.")
precondition(!fm.fileExists(atPath: Whisper.dir + "/bad.bin") && !fm.fileExists(atPath: Whisper.dir + "/bad.bin.part"))
precondition(fetch("gone")["have"] as? Bool == false && w.status()["error"] as? String == Whisper.offline)
w.delete("good"); w.delete("nope")
precondition(!fm.fileExists(atPath: Whisper.dir + "/good.bin") && w.status()["error"] is NSNull)
w.download("good") {{}}; w.cancel("good")
precondition(((w.status()["models"] as! [[String: Any]])[0]["progress"]) is NSNull)
print("ok")
""", timeout=60)

    def test_live_transcription(self):
        if not TURBO.exists() or not shutil.which("afconvert") or not os.path.exists("/opt/homebrew/bin/whisper-server") and not shutil.which("whisper-server"):
            self.skipTest("needs whisper-server, afconvert and the turbo model")
        root = self.scratch()
        (root / "whisper").mkdir(); (root / "whisper" / TURBO.name).symlink_to(TURBO)
        aiff, wav = root / "a.aiff", root / "a.wav"
        subprocess.run(["say", "-o", str(aiff), "The quick brown fox jumps over the lazy dog."], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEF32@16000", "-c", "1", str(aiff), str(wav)], check=True)
        out = run_swift(self, engine() + f"""
let file = try! AVAudioFile(forReading: URL(fileURLWithPath: "{wav}"))
let buf = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(file.length))!
try! file.read(into: buf)
precondition(file.processingFormat.sampleRate == 16000)
let audio = WhisperAudio(); audio.append(buf)
precondition(Whisper.shared.ready)
let sem = DispatchSemaphore(value: 0)
Task {{
    Whisper.shared.warm()
    print(try await Whisper.shared.transcribe(audio.take(), prompt: ""))
    precondition(Whisper.shared.status()["running"] as? Bool == true)
    Whisper.shared.stop(); sem.signal()
}}
sem.wait()
""", timeout=90)
        self.assertIn("fox", out.lower())


if __name__ == "__main__":
    unittest.main()
