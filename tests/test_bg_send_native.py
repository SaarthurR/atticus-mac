"""Measured background-send checks. Native apps and key events run only in the test VM."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import atticus


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin", "macOS background-send fixture")
class BackgroundSendNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.binary = cls.root / "Atticus"
        build = subprocess.run(["swiftc", "-O", str(ROOT / "Atticus.swift"), "-o", str(cls.binary)], capture_output=True, text=True)
        if build.returncode:
            raise AssertionError(build.stderr)
        fixture_binary = cls.root / "background-send-fixture"
        build = subprocess.run(["swiftc", str(ROOT / "tests/background_send_fixture.swift"), "-o", str(fixture_binary)], capture_output=True, text=True)
        if build.returncode:
            raise AssertionError(build.stderr)
        typer_source = cls.root / "type-user.swift"
        typer_source.write_text("""import Cocoa
let count=Int(CommandLine.arguments[1])!
let source=CGEventSource(stateID:.privateState)!
for _ in 0..<count {
 for down in [true,false] {
  let event=CGEvent(keyboardEventSource:source,virtualKey:7,keyDown:down)!
  event.flags=[]; event.post(tap:.cghidEventTap)
 }
 usleep(8_000)
}
""")
        cls.typer = cls.root / "type-user"
        build = subprocess.run(["swiftc", str(typer_source), "-o", str(cls.typer)], capture_output=True, text=True)
        if build.returncode:
            raise AssertionError(build.stderr)
        cls.launchers = []
        cls.pids = {}
        cls.apps = {}
        cls.addClassCleanup(cls.stop_fixtures)
        for role in ("agent", "agent-ignore", "user"):
            app = cls.root / f"{role}.app"
            cls.apps[role] = app
            mac = app / "Contents/MacOS"
            mac.mkdir(parents=True)
            shutil.copy2(fixture_binary, mac / "fixture")
            with (app / "Contents/Info.plist").open("wb") as handle:
                plistlib.dump({
                    "CFBundleIdentifier": f"com.atticus.bg-send.{role}",
                    "CFBundleName": role,
                    "CFBundleExecutable": "fixture",
                    "CFBundlePackageType": "APPL",
                    "CFBundleVersion": "1",
                    "LSUIElement": role != "user",
                }, handle)
            launch = subprocess.Popen(["open", "-W", "-g", "-n", str(app), "--args", str(cls.root), role],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            cls.launchers.append(launch)
            ready = cls.root / f"{role}-ready"
            deadline = time.monotonic() + 8
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            if not ready.exists():
                raise AssertionError(f"{role} fixture did not start")
            cls.pids[role] = int(ready.read_text())
        subprocess.run(["open", "-a", str(cls.apps["user"])], check=True)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if cls.status("user").get("front") == cls.pids["user"]:
                break
            time.sleep(.01)
        if cls.status("user").get("front") != cls.pids["user"]:
            raise AssertionError("User fixture did not become frontmost")
        reset = cls.root / "user-reset-focus"
        reset.write_text("")
        deadline = time.monotonic() + 1
        while reset.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        if reset.exists() or cls.status("user").get("longestFocusLoss") != 0:
            raise AssertionError("User fixture focus measurement did not reset")
        (cls.root / "settings.json").write_text('{"safe":false}')
        cls.env = {**os.environ, "ATTICUS_DIR": str(cls.root), "ATTICUS_RESOURCES_DIR": str(ROOT),
                   "ATTICUS_AX_ONLY": "1", "ATTICUS_HANDS_STATE": str(cls.root / "hands.json")}
        probe = subprocess.run([str(cls.binary), "--hands", "see", str(cls.pids["agent"])],
                               env=cls.env, capture_output=True, text=True)
        if probe.returncode:
            raise unittest.SkipTest(probe.stdout.strip() or "Temporary binary lacks Accessibility permission")

    @classmethod
    def stop_fixtures(cls):
        for pid in getattr(cls, "pids", {}).values():
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for launch in getattr(cls, "launchers", []):
            try:
                launch.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                launch.kill()
                launch.communicate()

    @classmethod
    def tearDownClass(cls):
        cls.stop_fixtures()
        super().tearDownClass()

    @classmethod
    def status(cls, role):
        try:
            return json.loads((cls.root / f"{role}-status").read_text())
        except (OSError, ValueError):
            return {}

    def user_types_during(self, action, count=60):
        before = self.status("user")["value"]
        typer = subprocess.Popen([str(self.typer), str(count)])
        deadline = time.monotonic() + 1
        while self.status("user").get("value") == before and time.monotonic() < deadline:
            time.sleep(.002)
        self.assertNotEqual(self.status("user").get("value"), before, "User typing did not start")
        started = time.perf_counter()
        result = action()
        elapsed = (time.perf_counter() - started) * 1000
        typer.wait(timeout=3)
        deadline = time.monotonic() + 2
        expected = before + "x" * count
        while self.status("user").get("value") != expected and time.monotonic() < deadline:
            time.sleep(.01)
        status = self.status("user")
        self.assertEqual(status["value"], expected, "A user keystroke was lost or reached the agent")
        self.assertTrue(status["focused"])
        self.assertEqual(status["caret"], len(expected))
        self.assertEqual(status["front"], self.pids["user"])
        self.assertLess(status["longestFocusLoss"], .2)
        return result, elapsed

    def hands_receipt(self, role, *args):
        seen = subprocess.run([str(self.binary), "--hands", "see", str(self.pids[role])],
                              env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(seen.returncode, 0, seen.stdout + seen.stderr)
        label = subprocess.run([str(self.binary), "--hands", "label", *args],
                               env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(label.returncode, 0, label.stdout + label.stderr)
        return label.stdout

    def hands_action(self, receipt, *args):
        return subprocess.run([str(self.binary), "--hands", *args], input=receipt,
                              env={**self.env, "ATTICUS_HANDS_RECEIPT": "1"},
                              capture_output=True, text=True, timeout=5)

    def test_native_chat_send_keeps_user_focus_routes_keys_and_verifies_return(self):
        prompt = "also run the fixture tests"
        receipt = self.hands_receipt("agent", "type", "Prompt", prompt, "submit")
        result, elapsed = self.user_types_during(lambda: self.hands_action(receipt, "type", "Prompt", prompt, "submit"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.root / "agent-submitted").read_text(), prompt)
        self.assertTrue(result.stdout.startswith('verified: Submitted from "Prompt".'), result.stdout)
        print(f"BACKGROUND SEND native chat: {elapsed:.1f} ms, focus loss {self.status('user')['longestFocusLoss'] * 1000:.1f} ms", flush=True)

    def test_native_chat_does_not_claim_an_unobserved_background_return(self):
        prompt = "safe unsubmitted prompt"
        receipt = self.hands_receipt("agent-ignore", "type", "Prompt", prompt, "submit")
        result, _ = self.user_types_during(lambda: self.hands_action(receipt, "type", "Prompt", prompt, "submit"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith('unverified: Return dispatched'), result.stdout)
        self.assertNotIn('verified: Submitted', result.stdout)
        self.assertEqual(self.status("agent-ignore")["value"], prompt)
        self.assertFalse((self.root / "agent-ignore-submitted").exists())

    def test_atticus_agent_steer_uses_stdin_without_touching_the_user_app(self):
        worker = self.root / "steer-worker.py"
        received = self.root / "steer-received.jsonl"
        worker.write_text("""import json,sys,time
path=sys.argv[1]
for line in sys.stdin:
 with open(path,'a') as out: out.write(line)
 time.sleep(.1)
""")
        events = []
        with patch.object(atticus, "DIR", str(self.root / "agents-state")), \
             patch.object(atticus, "pref", side_effect=lambda key, default: default):
            manager = atticus.Agents(emit=lambda event: events.append(event))
            self.addCleanup(manager.close)
            row = manager.new()
            row.update(status="running", title="Fixture agent", brief="Original task")
            manager.rows[row["id"]] = row
            process = subprocess.Popen([sys.executable, str(worker), str(received)], stdin=subprocess.PIPE,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, start_new_session=True)
            manager.processes[row["id"]] = process
            manager.inputs[row["id"]] = threading.Lock()
            words = "also run the tests"
            _, elapsed = self.user_types_during(lambda: manager.steer({
                "steer": row["id"], "brief": words, "context": words, "ack": "Sent: also run the tests"
            }))
            deadline = time.monotonic() + 2
            while (not received.exists() or not received.read_text()) and time.monotonic() < deadline:
                time.sleep(.01)
            sent = json.loads(received.read_text().splitlines()[-1])
            self.assertEqual(sent["message"]["content"], words)
            ack = next(event["agent"]["steer"]["ack"] for event in reversed(events) if event["event"] == "steered")
            self.assertEqual(ack, "Sent: also run the tests")
            self.assertNotIn("\n", ack)
            print(f"BACKGROUND SEND Atticus steer: {elapsed:.1f} ms, focus loss {self.status('user')['longestFocusLoss'] * 1000:.1f} ms", flush=True)

    def test_orca_cli_receipt_needs_no_window_and_does_not_touch_user_input(self):
        fake = self.root / "orca"
        record = self.root / "orca-send.json"
        fake.write_text("""#!/usr/bin/env python3
import json,sys,time
args=sys.argv[1:]
with open(sys.argv[sys.argv.index('--record')+1],'w') as f: json.dump(args,f)
time.sleep(.25)
print(json.dumps({'ok':True,'inputAccepted':True,'enterSent':True,'submission':'input-accepted'}))
""")
        fake.chmod(0o755)
        prompt = "run the fixture tests too"
        command = [str(fake), "terminal", "send", "--terminal", "term_fixture", "--text", prompt,
                   "--enter", "--json", "--record", str(record)]
        result, elapsed = self.user_types_during(lambda: subprocess.run(command, capture_output=True, text=True, timeout=3))
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt["inputAccepted"] and receipt["enterSent"])
        self.assertEqual(json.loads(record.read_text())[5], prompt)
        self.assertTrue(any(rule.startswith("orca terminal send ") for rule in atticus.SAFE_OUT))
        print(f"BACKGROUND SEND Orca CLI: {elapsed:.1f} ms, focus loss {self.status('user')['longestFocusLoss'] * 1000:.1f} ms", flush=True)


if __name__ == "__main__":
    unittest.main()
