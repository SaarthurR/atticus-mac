import os, re, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPT = re.search(r'let r = sh\(#"""\n(.*?)"""#\)', (ROOT / 'Atticus.swift').read_text(), re.S).group(1)


@unittest.skipUnless(sys.platform == 'darwin', 'the app runs this updater with macOS /bin/zsh')
class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(); self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.git(self.root, 'init', '-q', '--bare', 'origin.git')
        self.git(self.root, 'clone', '-q', 'origin.git', 'src'); self.src = self.root / 'src'
        (self.src / 'build.sh').write_text('#!/bin/sh\n[ ! -e fail ] || exit 1\nprintf installed > built\n')
        (self.src / 'build.sh').chmod(0o755)
        (self.src / '.gitignore').write_text('built\nfail\n')
        self.git(self.src, 'add', '.'); self.git(self.src, 'commit', '-qm', 'one')
        self.git(self.src, 'push', '-qu', 'origin', 'HEAD')
        self.git(self.root, 'clone', '-q', 'origin.git', 'other'); self.other = self.root / 'other'

    def git(self, cwd, *args):
        return subprocess.check_output(['git', '-C', str(cwd), '-c', 'user.name=t', '-c', 'user.email=t@t', *args], stderr=subprocess.STDOUT).decode().strip()

    def push(self):
        (self.other / 'new').write_text('update')
        self.git(self.other, 'add', '.'); self.git(self.other, 'commit', '-qm', 'update'); self.git(self.other, 'push', '-q')

    def run_update(self):
        return subprocess.run(['/bin/zsh', '-c', SCRIPT, str(self.src)], capture_output=True).returncode

    def test_repeated_checks_do_not_start_overlapping_updates(self):
        source = (ROOT / 'Atticus.swift').read_text()
        updater = source.split('enum Updater {', 1)[1].split('// Opening Atticus again', 1)[0]
        self.assertIn('guard !checking else { done(); return }', updater)
        self.assertLess(updater.index('checking = true'), updater.index('status = "Checking…"'))
        self.assertIn('DispatchQueue.main.async {\n                checking = false', updater)

    def test_signing_failure_keeps_entire_installed_app(self):
        home = self.root / 'home'; app = home / 'Applications/Atticus.app/Contents'
        (app / 'MacOS').mkdir(parents=True); (app / 'Resources').mkdir()
        for name in ['Info.plist', 'MacOS/Atticus', 'Resources/atticus.py']:
            (app / name).write_text('old app')
        source = self.root / 'build-source'; source.mkdir(); (source / 'ui').mkdir()
        (source / 'build.sh').write_text((ROOT / 'build.sh').read_text())
        for name in ['Atticus.swift', 'atticus.py', 'ui/page.html', 'ui/page.js', 'ui/page.css', 'ui/AppIcon.icns']:
            (source / name).write_text('new app')
        (source / 'VERSION').write_text('1.6.1')
        commands = self.root / 'bin'; commands.mkdir()
        for name, script in {
            'swiftc': 'for arg do target="$arg"; done; printf new > "$target"',
            'security': 'echo 1\\) ABC Atticus Local Signing',
            'codesign': 'echo intentional-signing-failure >&2; exit 1',
        }.items():
            path = commands / name; path.write_text('#!/bin/sh\n' + script + '\n'); path.chmod(0o755)
        result = subprocess.run(['/bin/bash', str(source / 'build.sh')], env=dict(os.environ, HOME=str(home), PATH=str(commands) + ':' + os.environ['PATH'], ATTICUS_NO_RESTART='1'), capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'intentional-signing-failure', result.stderr)
        for name in ['Info.plist', 'MacOS/Atticus', 'Resources/atticus.py']:
            self.assertEqual((app / name).read_text(), 'old app', name + ' changed after failed signing')

    def test_restart_waits_for_each_activity(self):
        from tests import run_swift
        source = (ROOT / 'Atticus.swift').read_text()
        idle = source[source.index('    static func restartWhenIdle()'):source.index('    static func schedule()')]
        swift = """import Foundation
final class Queue {
 var pending: [() -> Void] = []
 func asyncAfter(deadline: DispatchTime, execute work: @escaping () -> Void) { pending.append(work) }
}
enum DispatchQueue { static let main = Queue() }
final class Engine { var isRunning = false }
final class Window { var isKeyWindow = false, isVisible = false }
final class Drawing { var active = false, hasInput = false, voice: Engine? = Engine() }
final class App {
 var busy = false, dictating = false, dictateSelectionPending = false, composing = false
 var engine = Engine(), voice: Engine? = Engine(), panel = Window(), drawing = Drawing()
}
final class Settings { var win: Window? }
final class Meeting { var running = false, panel: Int? }
final class Agents { var hasLive = false }
let app = App(), settings = Settings(), onboarding = Settings(), meeting = Meeting(), agentsUI = Agents()
var restarts = 0
func relaunchSoon() { restarts += 1 }
enum Updater {
""" + idle + r"""}
let gates: [(Bool) -> Void] = [
 { app.busy = $0 }, { app.dictating = $0 }, { app.dictateSelectionPending = $0 }, { app.composing = $0 },
 { app.engine.isRunning = $0 }, { app.voice?.isRunning = $0 }, { app.panel.isVisible = $0 },
 { app.drawing.active = $0 }, { app.drawing.hasInput = $0 }, { app.drawing.voice?.isRunning = $0 },
 { agentsUI.hasLive = $0 }, { meeting.running = $0 }, { meeting.panel = $0 ? 1 : nil },
 { settings.win = $0 ? Window() : nil; settings.win?.isKeyWindow = $0 }, { onboarding.win = $0 ? Window() : nil }
]
for (i, gate) in gates.enumerated() {
 gate(true); Updater.restartWhenIdle()
 precondition(restarts == i, "activity \(i) was interrupted")
 precondition(DispatchQueue.main.pending.count == 1, "idle retry was lost")
 gate(false); DispatchQueue.main.pending.removeFirst()()
 precondition(restarts == i + 1, "restart did not resume after activity \(i)")
}
print("15 idle gates defer and resume")
"""
        self.assertIn('15 idle gates', run_swift(self, swift))

    def test_launch_and_periodic_timers_respect_preference(self):
        from tests import run_swift
        source = (ROOT / 'Atticus.swift').read_text()
        schedule = source[source.index('    static func schedule()'):source.index('\n}\n', source.index('    static func schedule()'))]
        swift = """import Foundation
final class Queue {
 var delays: [(Double, () -> Void)] = []
 func asyncAfter(deadline: DispatchTime, execute work: @escaping () -> Void) { delays.append((Double(deadline.uptimeNanoseconds - DispatchTime.now().uptimeNanoseconds) / 1e9, work)) }
}
enum DispatchQueue { static let main = Queue() }
enum Timer {
 static var intervals: [(Double, (Int) -> Void)] = []
 static func scheduledTimer(withTimeInterval interval: Double, repeats: Bool, block: @escaping (Int) -> Void) { precondition(repeats); intervals.append((interval, block)) }
}
enum Prefs { static var enabled = false; static func bool(_ k: String) -> Bool { precondition(k == "autoUpdate"); return enabled } }
enum Updater {
 static var managedByNix = false, status = "", checks = 0
 static func check() { checks += 1 }
""" + schedule + """
}
Updater.schedule()
precondition(abs(DispatchQueue.main.delays[0].0 - 60) < 1)
precondition(Timer.intervals[0].0 == 6 * 3600)
DispatchQueue.main.delays[0].1(); Timer.intervals[0].1(0); precondition(Updater.checks == 0)
Prefs.enabled = true
DispatchQueue.main.delays[0].1(); Timer.intervals[0].1(0); precondition(Updater.checks == 2)
Updater.managedByNix = true; Updater.schedule()
precondition(DispatchQueue.main.delays.count == 1 && Timer.intervals.count == 1)
print("launch and six-hour timers respect preference and Nix")
"""
        self.assertIn('six-hour timers', run_swift(self, swift))

    def test_any_new_build_shows_updated_once_and_fresh_installs_never(self):
        source = (ROOT / 'Atticus.swift').read_text()
        notice = source[source.index('    static let commit ='):source.index('    static func check(')]
        swift = r'''import Foundation
let env = ProcessInfo.processInfo.environment, state = URL(fileURLWithPath: env["STATE"]!)
struct Bundle {
 static let main = Bundle()
 func object(forInfoDictionaryKey k: String) -> Any? { ["AtticusCommit": env["COMMIT"]!, "CFBundleShortVersionString": env["VERSION"]!][k] }
}
struct UserDefaults {
 static let standard = UserDefaults()
 static var values = (try? JSONSerialization.jsonObject(with: Data(contentsOf: state))) as? [String: Any] ?? [:]
 func string(forKey k: String) -> String? { Self.values[k] as? String }
 func bool(forKey k: String) -> Bool { Self.values[k] as? Bool ?? false }
 func set(_ v: Any, forKey k: String) { Self.values[k] = v }
 func removeObject(forKey k: String) { Self.values[k] = nil }
}
enum Updater {
 static let managedByNix = false
''' + notice + r'''}
Updater.noteLaunch()
if CommandLine.arguments.contains("open") { print("notice=" + Updater.takeNotice()) }
try! JSONSerialization.data(withJSONObject: UserDefaults.values).write(to: state)
'''
        path, binary, state = self.root / 'notice.swift', self.root / 'notice', self.root / 'defaults.json'
        path.write_text(swift)
        built = subprocess.run(['swiftc', str(path), '-o', str(binary)], capture_output=True, text=True)
        self.assertEqual(built.returncode, 0, built.stderr)

        def launch(version, commit, opens=True, preview=False):
            run_env = {k: v for k, v in os.environ.items() if k != 'ATTICUS_DIR'}
            run_env.update(STATE=str(state), VERSION=version, COMMIT=commit, **({'ATTICUS_DIR': str(self.root)} if preview else {}))
            out = subprocess.run([str(binary)] + (['open'] if opens else []), env=run_env, capture_output=True, text=True, check=True).stdout
            return out.strip().removeprefix('notice=') if opens else None

        def onboard():
            values = __import__('json').loads(state.read_text()); values['onboarded'] = True; state.write_text(__import__('json').dumps(values))

        self.assertEqual(launch('2.0.0', 'c2'), '', 'a fresh install said it was updated')
        onboard(); self.assertEqual(launch('2.0.0', 'c2'), '', 'finishing setup read as an update')
        state.write_text('{"onboarded": true, "askedAX": true}')   # what 1.6.0 leaves: setup done, no build recorded
        launch('2.0.0', 'c2', opens=False); launch('2.0.0', 'c2', opens=False)
        self.assertEqual(launch('2.0.0', 'c2'), '2.0.0', 'an upgrade from 1.6.0 lost its notice (it must survive relaunches until the box opens)')
        self.assertEqual(launch('2.0.0', 'c2'), '', 'the notice showed twice')
        self.assertEqual(launch('2.0.0', 'c2'), '', 'a failed build (same app relaunched) showed the notice')
        launch('2.0.1', 'c3', preview=True, opens=False)
        self.assertEqual(launch('2.0.0', 'c2'), '', 'a preview build changed what the installed app recorded')
        self.assertEqual(launch('2.0.0', 'c4'), '2.0.0', 'a new commit of the same version (updater or git pull && ./build.sh) lost its notice')
        launch('2.0.0', 'c5', opens=False)
        self.assertEqual(launch('2.0.0', 'c5', preview=True), '', 'a preview build took the installed app’s notice')
        self.assertEqual(launch('2.0.0', 'c5'), '2.0.0')

    def test_only_new_upstream_commits_rebuild(self):
        self.assertEqual(self.run_update(), 0)
        (self.src / 'local').write_text('local'); self.git(self.src, 'add', '.')
        self.git(self.src, 'commit', '-qm', 'unpushed')
        self.assertEqual(self.run_update(), 0); self.assertFalse((self.src / 'built').exists())
        self.push(); self.assertEqual(self.run_update(), 7)
        self.git(self.src, 'reset', '-q', '--hard', 'HEAD~1')
        self.assertEqual(self.run_update(), 10); self.assertTrue((self.src / 'built').exists())
        self.assertEqual(self.run_update(), 0)

    def test_failed_build_keeps_old_app_and_retries_same_commit(self):
        (self.src / 'built').write_text('old app'); (self.src / 'fail').touch(); self.push()
        self.assertEqual(self.run_update(), 6); self.assertEqual((self.src / 'built').read_text(), 'old app')
        self.assertEqual(self.run_update(), 6)
        (self.src / 'fail').unlink()
        self.assertEqual(self.run_update(), 10); self.assertEqual((self.src / 'built').read_text(), 'installed')
        self.assertEqual(self.run_update(), 0)

    def test_local_changes_skip_without_pulling(self):
        before = self.git(self.src, 'rev-parse', 'HEAD'); self.push()
        (self.src / 'local').write_text('keep me')
        self.assertEqual(self.run_update(), 5); self.assertEqual(self.git(self.src, 'rev-parse', 'HEAD'), before)
        self.assertFalse((self.src / 'built').exists())

    def test_failed_build_recovers_after_source_is_fast_forwarded(self):
        (self.src / 'fail').touch(); self.push()
        self.assertEqual(self.run_update(), 6)
        (self.other / 'new').write_text('repaired update')
        self.git(self.other, 'commit', '-qam', 'repair'); self.git(self.other, 'push', '-q')
        self.git(self.src, 'pull', '-q', '--ff-only')
        (self.src / 'fail').unlink()
        self.assertEqual(self.run_update(), 10)
        self.assertEqual((self.src / 'built').read_text(), 'installed')
        self.assertEqual(self.run_update(), 0)

    def test_source_folder_that_is_not_a_clone_is_not_offline(self):
        plain = self.root / 'download'; plain.mkdir(); (plain / 'build.sh').write_text('#!/bin/sh\nprintf installed > built\n')
        self.src = plain   # a downloaded copy without .git: no fetch can ever work, so retrying as "Offline" never ends
        self.assertEqual(self.run_update(), 3)
        self.assertFalse((plain / 'built').exists())

    def test_offline_retry(self):
        origin = self.root / 'origin.git'; origin.rename(self.root / 'offline')
        self.assertEqual(self.run_update(), 4)
        (self.root / 'offline').rename(origin); self.push()
        self.assertEqual(self.run_update(), 10)

    def test_force_push_preserves_running_source(self):
        self.push(); self.assertEqual(self.run_update(), 10)
        before = self.git(self.src, 'rev-parse', 'HEAD')
        self.git(self.other, 'checkout', '-q', '--orphan', 'replacement')
        self.git(self.other, 'commit', '-qm', 'replacement')
        self.git(self.other, 'push', '-q', '--force', 'origin', 'HEAD:' + self.git(self.src, 'branch', '--show-current'))
        self.assertEqual(self.run_update(), 7)
        self.assertEqual(self.git(self.src, 'rev-parse', 'HEAD'), before)
        self.assertEqual((self.src / 'built').read_text(), 'installed')


if __name__ == '__main__':
    unittest.main()
