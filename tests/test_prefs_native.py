"""Native settings and usage regressions in a scratch ATTICUS_DIR."""
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin", "macOS Swift regression")
class PrefsNativeTests(unittest.TestCase):
    def test_auto_minimize_default_and_saved_choice_across_launches(self):
        source = (ROOT / "Atticus.swift").read_text()
        prefs = source[source.index("enum Prefs"):source.index("func applySharing(")]
        swift = "import Foundation\nlet controlKey = 1, optionKey = 2\n" + prefs + r'''
print(Prefs.bool("autoMinimize"))
if CommandLine.arguments.count > 1 { precondition(Prefs.set("autoMinimize", CommandLine.arguments[1] == "true")) }
'''
        with tempfile.TemporaryDirectory() as root:
            src, binary = Path(root)/'prefs.swift', Path(root)/'prefs'
            src.write_text(swift)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            for args, expected in [(['false'], 'true'), (['true'], 'false'), ([], 'true')]:
                run = subprocess.run([str(binary)] + args, capture_output=True, text=True,
                                     env={**os.environ, 'ATTICUS_DIR': root})
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(run.stdout.strip(), expected)

    def test_all_windows_follow_sharing_preference(self):
        source = (ROOT / "Atticus.swift").read_text()
        self.assertEqual(source.count(".sharingType ="), 1)
        classes = re.findall(r'^final class (\w+): NS(?:Panel|Window) \{', source, re.M)
        self.assertGreaterEqual(len(classes), 3)
        made = r'let (\w+) = (?:(NSWindow|NSPanel|%s)\(contentRect|(NSAlert|NSSavePanel|NSOpenPanel)\(\))' % '|'.join(classes)
        web = source[source.index('    func makeWeb('):source.index('loadPage(web, "agents.html")')]
        self.assertIn('applySharing(panel)', web)
        sites = list(re.finditer(made, source))
        self.assertGreaterEqual(len(sites), 19)
        for site in sites:   # every window Atticus makes or shows, built in or system, is given the sharing rule before its name is reused
            name = site.group(1)
            later = source[site.end():]
            reuse = re.search(r'\blet %s = ' % name, later)
            scope = later[:reuse.start() if reuse else len(later)]
            target = name + '.window' if site.group(3) == 'NSAlert' else name
            self.assertTrue(f'applySharing({target})' in scope or f'makeWeb({name},' in scope,
                            f'{site.group(0)} at line {source[:site.start()].count(chr(10)) + 1} skips applySharing')
        prefs = source[source.index("enum Prefs"):source.index("func profileName(")]
        live = next(line for line in source.splitlines() if 'if k == "hideWhenSharing"' in line)
        subclasses = ''.join(re.search(r'^final class %s: (?:[^\n]*\}|[^\n]*\{\n.*?\n\})\n' % c, source, re.M | re.S).group(0) for c in classes)
        swift = """import Cocoa
let controlKey = 1, optionKey = 2
""" + prefs + subclasses + """
let nsapp = NSApplication.shared
let windows: [NSWindow] = [NSWindow(), NSPanel(), NSAlert().window, NSSavePanel(), NSOpenPanel()] + [""" + ', '.join(f'{c}()' for c in classes) + """]
precondition(Prefs.bool("hideWhenSharing"), "sharing must be hidden by default")
windows.forEach(applySharing)
precondition(windows.allSatisfy { $0.sharingType == .none })
let k = "hideWhenSharing"
for enabled in [false, true, false] {
    Prefs.set(k, enabled)
""" + live + """
    precondition(windows.allSatisfy { $0.sharingType == (enabled ? .none : .readOnly) }, "live change missed a window")
    let later = NSPanel(); applySharing(later)
    precondition(later.sharingType == (enabled ? .none : .readOnly), "new window missed preference")
}
"""
        with tempfile.TemporaryDirectory() as root:
            path, binary = Path(root) / "sharing.swift", Path(root) / "sharing"
            path.write_text(swift)
            compiled = subprocess.run(["swiftc", str(path), "-o", str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True,
                                    env={**os.environ, "ATTICUS_DIR": root})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_old_long_asks_choices_are_not_read(self):
        source = (ROOT / "Atticus.swift").read_text()
        self.assertNotIn('"longAsks"', source)
        self.assertNotIn('agentsAuto', source)

    def test_retired_settings_keep_saved_values_without_rewriting_disk(self):
        source = (ROOT / "Atticus.swift").read_text()
        prefs = source[source.index("enum Prefs"):source.index("func applySharing(")]
        swift = """import Foundation
let controlKey = 1, optionKey = 2
""" + prefs + """
if CommandLine.arguments.contains("--saved") {
    precondition(Prefs.str("workIn") == "front" && !Prefs.bool("askMe") && Prefs.num("aheadDelay") == 1.2, "retired choices changed")
    precondition(Prefs.bool("quietAudio") && !Prefs.bool("selection") && !Prefs.bool("learn") && !Prefs.bool("dictateLearn"), "hidden choices changed")
    precondition(!Prefs.bool("tips") && Prefs.bool("speak") && Prefs.str("routing") == "capable", "visible choices changed")
} else {
    precondition(Prefs.str("workIn") == "back" && Prefs.bool("askMe") && Prefs.num("aheadDelay") == 0.7, "new user missed defaults")
    precondition(!Prefs.bool("quietAudio") && Prefs.bool("selection") && Prefs.bool("learn") && Prefs.bool("dictateLearn"), "new hidden defaults are wrong")
}
"""
        with tempfile.TemporaryDirectory() as root:
            path, binary = Path(root) / "retired.swift", Path(root) / "retired"
            path.write_text(swift)
            compiled = subprocess.run(["swiftc", str(path), "-o", str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            saved = '{"workIn":"front","askMe":false,"tips":false,"aheadDelay":1.2,"speak":true,"routing":"capable","quietAudio":true,"selection":false,"learn":false,"dictateLearn":false}'
            settings = Path(root) / "settings.json"
            settings.write_text(saved)
            result = subprocess.run([str(binary), "--saved"], capture_output=True, text=True, env={**os.environ, "ATTICUS_DIR": root})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(settings.read_text(), saved)
            fresh = Path(root) / "fresh"
            result = subprocess.run([str(binary)], capture_output=True, text=True, env={**os.environ, "ATTICUS_DIR": str(fresh)})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((fresh / "settings.json").exists())

    def test_dictation_shortcut_defaults_to_fn_but_keeps_any_choice(self):
        source = (ROOT / "Atticus.swift").read_text()
        prefs = source[source.index("enum Prefs"):source.index("func applySharing(")]
        swift = """import Foundation
let controlKey = 1, optionKey = 2
""" + prefs + """
print(Prefs.str("dictateHotkeyLabel") + "|" + String(Int(Prefs.num("dictateHotkeyCode"))) + "|" + String(Int(Prefs.num("dictateHotkeyMods"))))
"""
        with tempfile.TemporaryDirectory() as root:
            path, binary = Path(root) / "fn.swift", Path(root) / "fn"
            path.write_text(swift)
            compiled = subprocess.run(["swiftc", str(path), "-o", str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            fn = f"fn|-2|{1 << 20}"
            cases = [(None, fn),   # fresh install
                     ('{"dictateHotkeyLabel": "", "dictateHotkeyCode": -1, "dictateHotkeyMods": 0}', fn),   # an old build saved its empty default
                     ('{"dictateHotkeyLabel": "⌃⌥D", "dictateHotkeyCode": 2, "dictateHotkeyMods": 3}', "⌃⌥D|2|3"),   # recorded: kept
                     ('{"dictateHotkeyLabel": "", "dictateHotkeyCode": -1, "dictateHotkeyMods": 0, "dictateHotkeyOff": true}', "|-1|0"),   # cleared on purpose
                     (f'{{"hotkeyLabel": "fn", "hotkeyCode": -2, "hotkeyMods": {1 << 20}}}', "|-1|0")]   # the talk shortcut already holds fn
            for i, (before, want) in enumerate(cases):
                case = Path(root) / str(i); case.mkdir()
                if before: (case / "settings.json").write_text(before)
                result = subprocess.run([str(binary)], capture_output=True, text=True, env={**os.environ, "ATTICUS_DIR": str(case)})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.strip(), want, before)

    def test_settings_are_private_and_usage_counts_final_rows(self):
        source = (ROOT / "Atticus.swift").read_text()
        prefs = source[source.index("enum Prefs"):source.index("func audioProp")]
        today = source[source.index("    func today()"):source.index("    @objc func toggleMeeting")]
        today = today.replace('NSString(string: "~/.config/atticus/log.jsonl").expandingTildeInPath',
                              '(Prefs.path as NSString).deletingLastPathComponent + "/log.jsonl"')
        swift = """import Cocoa
let controlKey = 1, optionKey = 2
""" + prefs + "\nfinal class FixtureMenu {\n" + today + """
}
Prefs.set("apiKey", "fixture-secret")
let fm = FileManager.default
let mode = (try! fm.attributesOfItem(atPath: Prefs.path)[.posixPermissions] as! NSNumber).intValue
precondition(mode == 0o600, "settings were not private")
let me = (Prefs.path as NSString).deletingLastPathComponent + "/me.json"
try! "{\\"name\\":\\"Legacy Name\\"}".write(toFile: me, atomically: true, encoding: .utf8)
precondition(profileName(me) == "Legacy Name", "legacy profile name was lost")
try! "{\\"version\\":2,\\"facts\\":[{\\"category\\":\\"basics\\",\\"kind\\":\\"name\\",\\"value\\":\\"Imported Name\\",\\"source\\":\\"contacts\\"},{\\"category\\":\\"basics\\",\\"kind\\":\\"name\\",\\"value\\":\\"Chosen Name\\",\\"source\\":\\"you\\"}]}".write(toFile: me, atomically: true, encoding: .utf8)
precondition(profileName(me) == "Chosen Name", "categorized profile name priority failed")
let format = DateFormatter(); format.dateFormat = "yyyy-MM-dd"; let day = format.string(from: Date())
let log = "{\\"at\\":\\"\\(day) 10:00:00\\",\\"usd\\":9}\\n{\\"at\\":\\"\\(day) 10:00:01\\",\\"reply\\":\\"Done\\",\\"usd\\":0.01}\\n"
try! log.write(toFile: (Prefs.path as NSString).deletingLastPathComponent + "/log.jsonl", atomically: true, encoding: .utf8)
let agents = (Prefs.path as NSString).deletingLastPathComponent + "/agents/a"
try! fm.createDirectory(atPath: agents, withIntermediateDirectories: true)
try! "{\\"created\\":\\(Date().timeIntervalSince1970),\\"costDay\\":\\"\\(day)\\",\\"costToday\\":0.02}".write(toFile: agents + "/state.json", atomically: true, encoding: .utf8)
let usage = FixtureMenu().today()
precondition(usage == "Today: $0.03 · asks $0.01 · agents $0.02", "usage did not split asks from agents: \\(usage)")
"""
        with tempfile.TemporaryDirectory() as root:
            path, binary = Path(root) / "check.swift", Path(root) / "check"
            path.write_text(swift)
            compiled = subprocess.run(["swiftc", str(path), "-o", str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True,
                                    env={**os.environ, "ATTICUS_DIR": root})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unwritable_settings_keep_the_old_value(self):
        source = (ROOT / "Atticus.swift").read_text()
        prefs = source[source.index("enum Prefs"):source.index("func audioProp")]
        swift = """import Cocoa
let controlKey = 1, optionKey = 2
""" + prefs + """
precondition(!Prefs.set("speak", false), "a write to an unwritable folder reported success")
precondition(Prefs.bool("speak"), "the unsaved value stayed in memory")
"""
        with tempfile.TemporaryDirectory() as root:
            path, binary, blocked = Path(root) / "check.swift", Path(root) / "check", Path(root) / "not-a-folder"
            path.write_text(swift); blocked.write_text("")   # ATTICUS_DIR is a file, so settings.json can't be written
            compiled = subprocess.run(["swiftc", str(path), "-o", str(binary)], capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True,
                                    env={**os.environ, "ATTICUS_DIR": str(blocked)})
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
