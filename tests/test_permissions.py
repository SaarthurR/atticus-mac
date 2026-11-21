"""Production permission flow against fake TCC states; no real permissions or AI."""
from pathlib import Path
import re
import sys
import unittest
from tests import run_swift

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'Atticus.swift').read_text()


def method(begin, end):
    return SOURCE[SOURCE.index(begin):SOURCE.index(end, SOURCE.index(begin))]


class PermissionTests(unittest.TestCase):
    def test_discarded_meeting_ignores_its_deferred_microphone_grant(self):
        start = method('    func start(_ context: String)', '        app.dismissUpgrade()')
        discard = method('    func discard() {', '    func material(')
        out = run_swift(self, r'''import Cocoa
import WebKit
enum Prefs { static func bool(_ k:String)->Bool { k == "meeting" } }
final class App {
 var voicePermissionID=0, voicePermissionPending=false, pinned=false
 var voicePermissionAction:(()->Void)?
 func pill(_ on:Bool) {}; func show() {}; func js(_ key:String,_ value:Any?) {}
 func missingVoicePermission(_ need:String,retry:@escaping()->Void) {voicePermissionAction=retry}
}
let app=App()
final class Onboarding {
 static var granted=false
 static func permissionState(_ k:String)->Int {granted ? 1 : 0}
 var callbacks:[()->Void]=[]
 func request(_ need:String,settingsOnRefusal:Bool,current:@escaping()->Bool,done:@escaping(Bool)->Void) {
  callbacks.append {if current() {Self.granted=true;done(true)}}
 }
}
let onboarding=Onboarding()
enum Motion {static func fade(_ w:NSWindow,in on:Bool) {}}
final class Meeting {
 var loaded=true,running=false,demo=false,generation=0,permissionID:Int?,starts:[String]=[]
 var panel:NSWindow?=NSWindow(),web:WKWebView?,archive:Int?,transcript:[String]=[]
 var brief="",pending="",partial="",nudge:Int?,moveMonitor:Any?,screenObserver:NSObjectProtocol?
 var dragOrigin:CGPoint?,mouseDown:CGPoint?
 func stop(paused:Bool) {running=false}; func finishArchive(summarize:Bool) {};func cancelWork() {}
''' + start + r'''
        running=true;starts.append(context)
    }
''' + discard + r'''
}
let meeting=Meeting();meeting.start("discarded context");precondition(app.voicePermissionPending)
let old=onboarding.callbacks.removeFirst();meeting.discard();old()
precondition(meeting.starts.isEmpty && !meeting.running,"discarded meeting started after permission")
precondition(!app.voicePermissionPending && app.voicePermissionAction == nil,"discard left the voice permission overlay pending")
Onboarding.granted=false;meeting.panel=NSWindow();meeting.start("old reopened context")
let stale=onboarding.callbacks.removeFirst();meeting.discard();meeting.panel=NSWindow();meeting.start("new context")
stale();precondition(meeting.starts.isEmpty,"old context started the reopened panel")
onboarding.callbacks.removeFirst()();precondition(meeting.starts == ["new context"])
print("discarded meeting permission ok")
''')
        self.assertIn('discarded meeting permission ok', out)

    def test_first_screen_request_keeps_the_drag_helper_with_a_callback(self):
        gate = method('    func request(_ need:', '    func allow(_ need:')
        out = run_swift(self, r'''import Foundation
final class Onboarding {
 var helped:[String]=[]
 static func permissionState(_ need:String,app:String)->Int {0}
 static func granted(_ need:String,app:String)->Bool {false}
 func help(_ pane:String) {helped.append(pane)}
 func allow(_ need:String,app:String,done:((Bool)->Void)?=nil) {DispatchQueue.main.asyncAfter(deadline:.now()+0.01) {done?(false)}}
''' + gate + r'''
}
let setup=Onboarding();var current=true
setup.request("screen",settingsOnRefusal:true,current:{current}) {_ in}
let until=Date().addingTimeInterval(2)
while setup.helped.isEmpty && Date()<until {RunLoop.current.run(until:Date().addingTimeInterval(0.01))}
precondition(setup.helped == ["ScreenCapture"],"callback path dropped the Screen Recording drag helper")
current=false
let stale=Onboarding();stale.request("screen",settingsOnRefusal:true,current:{false}) {_ in}
RunLoop.current.run(until:Date().addingTimeInterval(0.05))
precondition(stale.helped.isEmpty,"stale request opened the helper")
print("screen callback helper ok")
''')
        self.assertIn('screen callback helper ok', out)

    def test_shared_request_states_resume_refuse_cancel_and_timeout(self):
        gate = method('    func request(_ need:', '    func allow(_ need:')
        # Same branches with short deadlines, so timeout and stale callbacks are exercised.
        gate = gate.replace('withTimeInterval: 1', 'withTimeInterval: 0.01').replace('tries < 100', 'tries < 4')
        state = method('    static func permissionState(', '    // One on-use path:')
        granted = method('    static func granted(_ need:', '    // Enable All:')
        run_swift(self, r'''import Foundation
let noErr: Int32 = 0, errAEEventWouldRequireUserConsent: Int32 = -1744, procNotFound: Int32 = -600
func OSStatus(_ n: Int32) -> Int32 { n }
enum Status { case notDetermined, authorized, denied, restricted, fullAccess }
struct AVCaptureDevice {
    enum Kind { case audio }
    static var value = Status.notDetermined
    static func authorizationStatus(for: Kind) -> Status { value }
}
struct SFSpeechRecognizer {
    static var value = Status.notDetermined
    static func authorizationStatus() -> Status { value }
}
struct EKEventStore {
    enum Kind { case event }
    static var value = Status.notDetermined
    static func authorizationStatus(for: Kind) -> Status { value }
}
var ax = false, screen = false, screenCheckDelay = 0.0
func AXIsProcessTrusted() -> Bool { ax }
func CGPreflightScreenCaptureAccess() -> Bool { if screenCheckDelay > 0 { Thread.sleep(forTimeInterval: screenCheckDelay) }; return screen }
struct UserDefaults {
    static let standard = UserDefaults()
    static var askedScreen = false
    func bool(forKey: String) -> Bool { Self.askedScreen }
}
struct Apps {
    static var value = errAEEventWouldRequireUserConsent
    static func check(_ app: String, ask: Bool) -> Int32 { value }
}
func spin(_ seconds: Double = 0.12) {
    let end = Date().addingTimeInterval(seconds)
    while Date() < end { RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.005)) }
}
func until(_ ready: () -> Bool) {
    let end = Date().addingTimeInterval(2)
    while !ready() && Date() < end { spin(0.005) }
    precondition(ready(), "fake permission callback did not arrive")
}
final class Onboarding {
    static func bundle(_ app: String) -> String? { app == "missing" ? nil : app }
    func help(_ pane:String) {}
    var prompts = 0, settings = 0, accept = true, silent = false, duplicate = false
    var onPrompt: (() -> Void)?, onSettings: (() -> Void)?
    func allow(_ need: String, app: String, done: ((Bool) -> Void)? = nil) {
        if let done {
            prompts += 1; onPrompt?()
            if !silent { DispatchQueue.main.asyncAfter(deadline: .now() + 0.01) {
                done(self.accept); if self.duplicate { done(self.accept) }
            } }
        } else { settings += 1; onSettings?() }
    }
''' + granted + state + gate + r'''
}
func set(_ need: String, _ state: Int) {
    let status: Status = state == 0 ? .notDetermined : state == 1 ? .authorized : .denied
    AVCaptureDevice.value = status; SFSpeechRecognizer.value = status
    EKEventStore.value = state == 1 ? .fullAccess : status
    ax = state == 1; screen = state == 1; UserDefaults.askedScreen = state != 0
    Apps.value = state == 0 ? errAEEventWouldRequireUserConsent : state == 1 ? 0 : -1743
}
for need in ["microphone", "speech", "screen", "automation", "calendar", "accessibility"] {
    for state in [0, 1, -1] {
        set(need, state)
        let expected = need == "accessibility" && state == 0 ? -1 : state
        precondition(Onboarding.permissionState(need, app: "Fake") == expected)
        let gate = Onboarding(); var results: [Bool] = []
        gate.request(need, app: "Fake") { results.append($0) }; until { !results.isEmpty }
        precondition(results == [expected != -1], "state did not finish exactly once: \(need)/\(state)")
        precondition(gate.prompts == (expected == 0 ? 1 : 0) && gate.settings == 0)
    }
}
for need in ["microphone", "speech", "screen", "automation", "calendar", "accessibility"] {
    set(need, -1)
    let gate = Onboarding(); var results: [Bool] = []
    gate.onSettings = { set(need, 1) }
    gate.request(need, app: "Fake", settingsOnRefusal: true) { results.append($0) }
    until { !results.isEmpty }; precondition(gate.settings == 1 && results == [true], "Settings did not resume: \(need)")
}
set("microphone", 0)
let denied = Onboarding(); denied.accept = false
var deniedResults: [Bool] = []; denied.request("microphone") { deniedResults.append($0) }; until { !deniedResults.isEmpty }
precondition(deniedResults == [false])
let silent = Onboarding(); silent.silent = true
var timeout: [Bool] = []; silent.request("microphone") { timeout.append($0) }; until { !timeout.isEmpty }
precondition(timeout == [false], "invisible prompt hung forever")
let duplicate = Onboarding(); duplicate.duplicate = true
var once: [Bool] = []; duplicate.request("microphone") { once.append($0) }; until { !once.isEmpty }
precondition(once == [true], "callback resumed twice")
let stale = Onboarding(); var active = true, callbacks = 0
stale.onPrompt = { active = false }
stale.request("microphone", current: { active }) { _ in callbacks += 1 }
spin(); precondition(callbacks == 0, "cancelled prompt resumed")
set("screen", -1)
let settingsTimeout = Onboarding(); var expired: [Bool] = []
settingsTimeout.request("screen", settingsOnRefusal: true) { expired.append($0) }; until { !expired.isEmpty }
precondition(expired == [false])
// Screen's first native dialog can hand off to Settings without granting immediately.
set("screen", 0)
let screenHandoff = Onboarding(); screenHandoff.accept = false
var screenResume: [Bool] = []
screenHandoff.onPrompt = { DispatchQueue.main.asyncAfter(deadline: .now() + 0.02) { set("screen", 1) } }
screenHandoff.request("screen", settingsOnRefusal: true) { screenResume.append($0) }
until { !screenResume.isEmpty }; precondition(screenResume == [true] && screenHandoff.prompts == 1 && screenHandoff.settings == 0)
set("screen", -1)
let cancelledSettings = Onboarding(); active = true
cancelledSettings.onSettings = { active = false; set("screen", 1) }
cancelledSettings.request("screen", settingsOnRefusal: true, current: { active }) { _ in callbacks += 1 }
spin(); precondition(callbacks == 0, "cancelled Settings wait resumed")
// A check already in flight must not resume after the Settings deadline.
set("screen", -1)
let late = Onboarding(); var lateResults: [Bool] = []
late.onSettings = { screenCheckDelay = 0.06 }
late.request("screen", settingsOnRefusal: true) { lateResults.append($0) }
until { !lateResults.isEmpty }; screen = true
spin(0.15); screenCheckDelay = 0
precondition(lateResults == [false], "late check resumed after timeout")
AVCaptureDevice.value = .restricted; SFSpeechRecognizer.value = .restricted; EKEventStore.value = .restricted
for need in ["microphone", "speech", "calendar"] { precondition(Onboarding.permissionState(need) == -1) }
precondition(Onboarding.permissionState("automation", app: "missing") == -1)
Apps.value = procNotFound; precondition(Onboarding.permissionState("automation", app: "Fake") == 0, "a closed app was read as a refusal")
print("permission states and lifecycle ok")
''')

    def test_setup_page_survives_any_relaunch_until_setup_closes(self):
        branch = method('        if b["do"] == "page" {', '        if b["do"] == "kofi"')
        start = SOURCE.index('    func finish() {', SOURCE.index('final class Onboarding:'))
        finish = SOURCE[start:SOURCE.index('    // Quitting closes setup too', start)]
        forget = SOURCE[SOURCE.index('    func windowShouldClose(', start):].split('\n', 1)[0]
        run_swift(self, '''import Foundation
unsetenv("ATTICUS_DIR")   // the installed app, not a preview
struct UserDefaults {
 static let standard=UserDefaults();static var values:[String:Any]=[:]
 func set(_ value:Any?,forKey key:String){Self.values[key]=value}
 func removeObject(forKey key:String){Self.values[key]=nil}
}
typealias NSWindow = Setup
var launches=0
func relaunchSoon(){launches += 1}
final class Setup {
 var screenGrantedDuringSetup=false,win:Setup?,closed=false,hidden=false
 func close(){closed=true}   // what quitting does too: no windowShouldClose
 func performClose(){if windowShouldClose(self){close()}}   // his red button or Close Setup
 func orderOut(_ s:Any?){hidden=true}
'''+forget+'''
 func handle(_ b:[String:String]){
'''+branch+'''
 }
'''+finish+'''
}
let setup=Setup();setup.win=setup
for page in ["welcome","ai","perms"]{setup.handle(["do":"page","id":page])}
setup.close()
precondition(UserDefaults.values["setupPage"] as? String=="perms", "macOS's Quit & Reopen would restart setup from the welcome page")
setup.handle(["do":"page","id":"try"]);setup.handle(["do":"permissionsReady"])
precondition(launches==0 && !setup.hidden && UserDefaults.values["setupPage"] as? String=="try")
setup.screenGrantedDuringSetup=true;setup.handle(["do":"permissionsReady"])
precondition(launches==1 && setup.hidden && UserDefaults.values["setupPage"] as? String=="try", "the Screen Recording restart lost Try it")
precondition(UserDefaults.values["onboarded"]==nil, "restart completed setup before its final page")
setup.performClose()
precondition(UserDefaults.values["setupPage"]==nil, "closing setup must forget the page")
setup.handle(["do":"page","id":"done"]);setup.screenGrantedDuringSetup=false;setup.finish()
precondition(UserDefaults.values["onboarded"] as? Bool==true && launches==1 && UserDefaults.values["setupPage"]==nil, "finished setup would open again")
print("setup page survives relaunches")
''')

    def test_voice_grants_resume_released_keys_and_refusal_offers_only_missing_pane(self):
        voice = method('    var voicePermissionID =', '    func start(dictate: Bool')
        settings_click = method('            if b["permissionSettings"] != nil {', '            if b["learnedUndo"]')
        run_swift(self, r'''import Foundation
final class NSRunningApplication {
    static let current = NSRunningApplication()
    var isTerminated = false, processIdentifier = 7
    static func == (l: NSRunningApplication, r: NSRunningApplication) -> Bool { l === r }
    static func != (l: NSRunningApplication, r: NSRunningApplication) -> Bool { l !== r }
}
enum MiniScreen { static var activated: [Int] = []; static func activate(_ pid: Int) { activated.append(pid) } }
final class Engine { var isRunning = false }
final class Gate {
    var states: [String:Bool] = [:], requested: [String] = [], settings: [String] = []
    func request(_ need: String, app: String = "", settingsOnRefusal: Bool = false,
                 current: @escaping () -> Bool = { true }, done: @escaping (Bool) -> Void) {
        requested.append(need); if settingsOnRefusal { settings.append(need) }
        DispatchQueue.main.async { if current() { done(self.states[need] ?? false) } }
    }
}
final class Harness {
    let onboarding = Gate(), engine = Engine()
    var pinned = true, clickTalk = false, toggleTalk = false, starts = 0, lines: [String] = []
    func js(_ name: String, _ value: Any? = nil) { if let value = value as? String { lines.append(value) } }
    func pill(_ on: Bool) {}; func show() {}
    func start(dictate: Bool, quiet: Bool) { starts += 1; engine.isRunning = true }
''' + voice + '\n    func handle(_ b: [String:Bool]) {\n' + settings_click + '\n    }\n' + r'''
}
func spin() { RunLoop.current.run(until: Date().addingTimeInterval(0.05)) }
let voice = Harness(); voice.onboarding.states = ["microphone":true, "speech":true]
voice.voicePermissionTarget = NSRunningApplication()
voice.voicePermissions(["microphone", "speech"], dictate: false, quiet: false); spin()
precondition(voice.starts == 1 && voice.clickTalk && !voice.pinned && voice.voicePermissionTarget == nil && MiniScreen.activated == [7])
precondition(voice.onboarding.requested == ["microphone", "speech"])
let denied = Harness(); denied.onboarding.states = ["microphone":true, "speech":false]
denied.voicePermissions(["microphone", "speech"], dictate: false, quiet: false); spin()
precondition(denied.starts == 0 && denied.lines.last == "Allow Speech Recognition for Atticus to listen to you.")
denied.onboarding.states["speech"] = true; denied.handle(["permissionSettings":true]); denied.handle(["permissionSettings":true]); spin()
precondition(denied.starts == 1 && denied.onboarding.settings == ["speech"])
let dictate = Harness(); dictate.onboarding.states = ["accessibility":true, "microphone":true]
dictate.voicePermissions(["accessibility", "microphone"], dictate: true, quiet: false); spin()
precondition(dictate.starts == 1 && dictate.toggleTalk && !dictate.clickTalk)
let stale = Harness(); stale.onboarding.states = ["microphone":true]
stale.voicePermissions(["microphone"], dictate: false, quiet: false); stale.voicePermissionID += 1; spin()
precondition(stale.starts == 0)
''')

    def test_clicking_native_allow_or_settings_does_not_cancel_pending_voice(self):
        outside = method('        NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown])', '        var grab:')
        body = outside[outside.index('            guard let self,'):outside.rindex('        }')]
        run_swift(self, '''import Foundation
final class Panel { var isVisible = true }
final class Engine { var isRunning = false }
final class Drawing { var active = false, hasInput = false }
final class Harness {
 let panel = Panel(), engine = Engine(), drawing = Drawing()
 var handsFree = false, voicePermissionPending = true, busy = false, stuck = false, closed = 0
 func close(clear: Bool) { closed += 1 }
 func outsideClick() { let callback = { [weak self] in
''' + body + '''
 }; callback() }
}
let h = Harness(); h.outsideClick(); h.outsideClick()
precondition(h.closed == 0, "native prompt / Settings click cancelled pending request")
h.voicePermissionPending = false; h.outsideClick()
precondition(h.closed == 1, "normal click-away stopped closing the box")
''')

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
    def test_missing_permission_box_webkit_light_and_dark(self):
        from tests.shoot_permissions import PermissionShots
        PermissionShots.test_missing_line_light_dark(self)

    def test_setup_asks_mac_access_up_front_and_no_launch_requests(self):
        page = (ROOT / 'ui/onboarding.html').read_text()
        permissions = page.split('  const P = [', 1)[1].split('  ];', 1)[0]
        self.assertEqual(re.findall(r"\['(\w+)'", permissions), ['ax', 'mic', 'speech', 'screen', 'auto'])   # the first ask then has nothing left to prompt for
        launch = SOURCE[SOURCE.index('        drawing.autoSteps ='):SOURCE.index('    // The page reports its height;')]
        self.assertNotIn('requestAuthorization', launch)
        self.assertNotIn('requestAccess', launch)
        self.assertEqual(SOURCE.count('Timer.scheduledTimer(withTimeInterval:1, repeats:true)'), 0)
        self.assertIn('"question": ask', SOURCE)
