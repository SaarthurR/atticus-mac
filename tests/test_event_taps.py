"""Silent tap gates: extracted production policy with fake permissions and Mach ports, VM only."""
from pathlib import Path
import unittest
from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]


class EventTapTests(unittest.TestCase):
    def test_denied_granted_revoked_and_dead_taps(self):
        source = (ROOT / 'Atticus.swift').read_text()
        policy = source[source.index('    static func prepareTap('):source.index('    var nextTapCheck')]
        run_swift(self, '''
final class CFMachPort {
    var valid = true, enabled = false, canEnable = true
}
var accessibility = false, listening = false, enables = 0
func AXIsProcessTrusted() -> Bool { accessibility }
func CGPreflightListenEventAccess() -> Bool { listening }
func CFMachPortIsValid(_ tap: CFMachPort) -> Bool { tap.valid }
func CFMachPortInvalidate(_ tap: CFMachPort) { tap.valid = false }
enum CGEvent {
    static func tapEnable(tap: CFMachPort, enable: Bool) { enables += 1; tap.enabled = enable && tap.canEnable }
    static func tapIsEnabled(tap: CFMachPort) -> Bool { tap.enabled }
}
enum Pen {
''' + policy + '''
}
var tap: CFMachPort?
for ax in [false, true] {
    for listen in [false, true] {
        accessibility = ax; listening = listen
        precondition(Pen.prepareTap(&tap) == (ax && listen))
        precondition(tap == nil && enables == 0)
    }
}
let original = CFMachPort(); tap = original
precondition(Pen.prepareTap(&tap) && tap === original && original.enabled)
listening = false
precondition(!Pen.prepareTap(&tap) && tap == nil && !original.valid)
listening = true
precondition(Pen.prepareTap(&tap) && tap == nil, "grant must allow a fresh tap")
let dead = CFMachPort(); dead.valid = false; tap = dead
precondition(Pen.prepareTap(&tap) && tap == nil, "invalid tap must be replaced")
let disabled = CFMachPort(); disabled.canEnable = false; tap = disabled
precondition(Pen.prepareTap(&tap) && tap == nil && !disabled.valid, "unrecoverable tap must be replaced")
let revoked = CFMachPort(); tap = revoked; accessibility = false
precondition(!Pen.prepareTap(&tap) && tap == nil && !revoked.valid)
''')

    def test_both_creation_sites_are_gated_and_retried(self):
        source = (ROOT / 'Atticus.swift').read_text()
        pen = source[source.index('    func claimClicks()'):source.index('    static func resample(')]
        meeting = source[source.index('    func watchEnter('):source.index('    func watchEnter(') + 2000]
        self.assertLess(pen.index('guard Self.prepareTap(&tap)'), pen.index('CGEvent.tapCreate('))
        self.assertLess(meeting.index('guard TalkPen.prepareTap(&enterTap)'), meeting.index('CGEvent.tapCreate('))
        self.assertIn('if now >= nextTapCheck { claimClicks(); nextTapCheck = now + 1 }', source)
        self.assertIn('guard let self else { return }; watchEnter(running)', source)
        self.assertNotIn('CGRequestListenEventAccess', source)
        self.assertIn('event.flags.remove([.maskControl,.maskAlternate])', pen)
        self.assertIn('copilot.answerNow() }\n            return nil', meeting)
