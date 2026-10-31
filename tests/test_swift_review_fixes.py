"""Regressions from the 1.3.1 Swift/UI review; source-only except for the shortcut matcher harness."""
from pathlib import Path
import shutil
import subprocess
import unittest

from tests import run_swift
from tests.test_drawing_math_page import MATH_STUB


ROOT = Path(__file__).resolve().parents[1]


class SwiftReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.swift = (ROOT / "Atticus.swift").read_text()
        self.agents = (ROOT / "ui/agents.html").read_text()
        self.overlay = (ROOT / "ui/ui.html").read_text()
        self.settings = (ROOT / "ui/settings.html").read_text()

    def test_hands_free_follow_up_keeps_answer_until_words(self):
        wake = self.swift.split('    func wakeTick()', 1)[1].split('    func enableWakeWord()', 1)[0]
        self.assertIn('clickMicrophone(quiet: true)', wake)
        self.assertIn('guard Date() >= wakeRetry else { return }', wake)   # a backoff once pushed the retry back every tick, forever
        self.assertIn('("sound", cueSound?.isPlaying == true || Date() < cueEnds)', wake)
        self.assertIn('("speaking", voice?.isRunning == true || drawing.voice?.isRunning == true)', wake)
        self.assertIn('s?.duration ?? 0', self.swift)
        self.assertIn('if !self.quietFollowUp, let selection = self.selection', self.swift)
        start = self.swift.split('    func start(dictate: Bool, quiet: Bool = false)', 1)[1].split('    func heard(', 1)[0]
        self.assertIn('if !quiet { cue("soundStart") }', start)
        self.assertIn('if quiet { js("quietListen", true) }\n        else {', start)
        self.assertIn('self?.quietFollowUp == false', start)
        self.assertIn('if quietFollowUp { hush(); fadeIdleHandsFree(); return }', start)
        heard = self.swift.split('    func heard(_ now: String)', 1)[1].split('    func scheduleDictateAhead()', 1)[0]
        self.assertLess(heard.index('guard !now.trimmingCharacters'), heard.index('js("listen")'))
        self.assertLess(heard.index('js("listen")'), heard.index('text = now'))
        self.assertLess(heard.index('text = now'), heard.index('js("words", text)'))
        for name, end in [('shortcut', 'prepareForInactiveSession'), ('dictateShortcut', 'dictateChord'), ('typed', 'finish')]:
            body = self.swift.split('    func ' + name + '(', 1)[1].split('    func ' + end + '(', 1)[0]
            if name == 'shortcut': body = body.split('shortcutDown = true', 1)[1]
            self.assertLess(body.index('if quietFollowUp { hush() }'), body.index('if engine.isRunning') if name != 'typed' else body.index('guard !busy, !engine.isRunning'))

    def test_fn_key_match_is_exact_and_modifier_prefixes_conflict(self):
        helpers = self.swift[self.swift.index("let atticusFnKey"):self.swift.index("func configuredHotkey")]
        matcher = self.swift[self.swift.index("func specialHotkey"):self.swift.index("func handleSpecialHotkeys")]
        self.assertIn("func hotkeysConflict", matcher)
        recorder = self.swift[self.swift.index("    func done("):self.swift.index("    func say(", self.swift.index("    func done("))]
        self.assertIn("hotkeysConflict(hotkey(),dictateHotkey())", recorder)
        harness = "import Cocoa\nimport Carbon\n" + helpers + "\nvar specialGlobalHotkeys: Any?, specialLocalHotkeys: Any?, specialMainDown = false, specialDictateDown = false\n" + matcher + r'''
let fnD = (code: 2, mods: atticusFnKey, flags: NSEvent.ModifierFlags.function)
let fnShiftD = (code: 2, mods: atticusFnKey | shiftKey, flags: NSEvent.ModifierFlags([.function, .shift]))
let fnOnly = (code: -2, mods: atticusFnKey, flags: NSEvent.ModifierFlags.function)
precondition(!hotkeysConflict(fnD, fnShiftD))
precondition(hotkeysConflict(fnOnly, fnD))
var down = false, fired: [Bool] = []
let extra = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [.function, .shift],
    timestamp: 0, windowNumber: 0, context: nil, characters: "d", charactersIgnoringModifiers: "d",
    isARepeat: false, keyCode: 2)!
updateSpecialHotkey(extra, fnD, &down) { fired.append($0) }
precondition(fired.isEmpty)
let exact = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: [.function],
    timestamp: 0, windowNumber: 0, context: nil, characters: "d", charactersIgnoringModifiers: "d",
    isARepeat: false, keyCode: 2)!
updateSpecialHotkey(exact, fnD, &down) { fired.append($0) }
precondition(fired == [true])
print("special shortcuts stay distinct")
'''
        self.assertIn("special shortcuts stay distinct", run_swift(self, harness))

    def test_special_shortcut_registration_is_reported_as_available(self):
        registration = self.swift[self.swift.index("var ref: EventHotKeyRef?"):self.swift.index("let settings = SettingsWindow()")]
        push = self.swift[self.swift.index("    func push()"):self.swift.index("    func refresh()")]
        self.assertIn("var hotkeyRegistered = false", registration)
        self.assertIn("var dictateHotkeyRegistered = false", registration)
        self.assertIn('"hotkeyTaken": !hotkeyRegistered', push)
        self.assertIn('"dictateHotkeyTaken": !Prefs.str("dictateHotkeyLabel").isEmpty && !dictateHotkeyRegistered', push)

    def test_long_step_callout_starts_at_its_first_words(self):
        callout = self.swift[self.swift.index("final class DrawingCalloutView"):self.swift.index("final class ScreenDrawing")]
        self.assertIn("NSScrollView", callout)
        self.assertNotIn("scrollToEndOfDocument", callout)   # one step per callout: read it from the top
        harness = "import Cocoa\n" + MATH_STUB + callout + r'''
let words = String(repeating: "A readable instruction needs enough words to wrap. ", count: 20)
let size = DrawingCalloutView.size(words, total: 12)
let view = DrawingCalloutView(frame: CGRect(x: 0, y: 0, width: size.width + 24, height: size.height + 24),
                              card: CGRect(x: 12, y: 12, width: size.width, height: size.height), side: nil, tip: 0, text: words, step: 12, total: 12)
RunLoop.current.run(until: Date().addingTimeInterval(0.05))
let scroll = view.subviews.compactMap { $0 as? NSScrollView }.first!
let body = scroll.documentView as! NSTextView
precondition(body.frame.height > scroll.contentSize.height)
precondition(scroll.documentVisibleRect.minY <= 1)
print("long step stays reachable")
'''
        self.assertIn("long step stays reachable", run_swift(self, harness))

    def test_agent_rename_cancel_feedback_and_delete_confirmation(self):
        rename = self.agents[self.agents.index("const saved="):self.agents.index(" const head=", self.agents.index("const saved="))]
        self.assertIn("e.stopPropagation()", rename)
        self.assertIn("deleting===r.name", rename)
        self.assertIn("namedReply", self.agents)
        named = self.swift[self.swift.index('        } else if kind == "named"'):self.swift.index("        if let row =", self.swift.index('        } else if kind == "named"'))]
        self.assertIn('js("view","namedReply"', named)

    def test_retry_voice_hint_only_names_visible_answers(self):
        respond = self.overlay[self.overlay.index("    respond(text)"):self.overlay.index("    ask([")]
        self.assertNotIn("Sonnet", respond)
        if not shutil.which("node"):
            self.skipTest("Node runs the retry-card behavior check")
        script = r'''
let heard = '', clicked = '';
const buttons = {n:{click(){clicked='n'}}, r:{click(){clicked='r'}}};
const d = {querySelector(s){const m=s.match(/data-answer="(.)"/);return m ? buttons[m[1]] || null : null;}};
const thread = {querySelector(s){return s.startsWith('.pk') ? null : d;}};
const ask = {value:''}, $ = id => id === 'thread' ? thread : ask, status = s => {heard=s};
const ui = {
''' + respond + r'''
};
if (!ui.respond('try sonnet') || clicked || heard !== 'Say “Retry” or “Not now”') process.exit(1);
console.log(heard);
'''
        result = subprocess.run(["node", "--input-type=module"], input=script, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_point_capture_failure_preserves_answer_and_guides_can_be_replaced(self):
        finish = self.swift[self.swift.index("    func finishPoint("):self.swift.index("    func pointThumb")]
        start = self.swift[self.swift.index("    func startPointing()"):self.swift.index("    func finishPointing()")]
        self.assertIn('js("notice","Couldn’t capture that mark.")', finish)
        self.assertNotIn('js("msg","Couldn’t capture that mark.")', finish)
        self.assertNotIn("drawing.clear()", start)   # pointing keeps a guide up: its marks can be clicked and asked about
        self.assertIn("notice(s)", self.overlay)

    def test_hidden_rewrite_keeps_its_target(self):
        close = self.swift[self.swift.index("    func close(clear: Bool)"):self.swift.index("    func shortcut(", self.swift.index("    func close(clear: Bool)"))]
        harness = r'''import Foundation
final class NSAnimationContext {
    var duration = 0.0
    static func runAnimationGroup(_ changes: (NSAnimationContext) -> Void, completionHandler: () -> Void) {
        changes(NSAnimationContext()); completionHandler()
    }
}
final class Panel { var alphaValue = 1.0; func animator() -> Panel { self } }
final class Drawing { func clear() {} }
func unpoint() {}
final class Harness {
    var replacement: String? = "draft", selection: Int? = 7, lastDone = Date()
    var handsFree = false, followUp = false
    func stopWake() {}
    var recent = "/missing", gen = 0
    let panel = Panel(), drawing = Drawing()
    func shush() {}
    func hush() { replacement = nil; selection = nil }
    func gone() {}
''' + close + r'''}
let hidden = Harness(); hidden.close(clear: false)
precondition(hidden.replacement == "draft" && hidden.selection == 7)
let ended = Harness(); ended.close(clear: true)
precondition(ended.replacement == nil && ended.selection == nil)
print("hidden rewrite target kept")
'''
        self.assertIn("hidden rewrite target kept", run_swift(self, harness))

    def test_pointer_respects_reduce_motion(self):
        pointer = self.swift[self.swift.index("func pointAt("):self.swift.index("// Restart Atticus", self.swift.index("func pointAt("))]
        self.assertIn("let still = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion\n    if !still {", pointer)
        self.assertLess(pointer.index("accessibilityDisplayShouldReduceMotion"), pointer.index("l.add(pulse"))
        self.assertIn("if let box, lead(from: box, to: w.frame.insetBy(dx: 8, dy: 8)) {", pointer)
        lead = pointer[pointer.index("func lead("):]   # Reduce Motion: a still leader line, no running head
        self.assertLess(lead.index("if !still {"), lead.index('line.add(head'))

    def test_new_ask_clears_a_held_ring_without_hiding_the_new_answer(self):
        start = self.swift[self.swift.index("    func start(dictate: Bool, quiet: Bool = false)"):self.swift.index("    func heard(")]
        run = self.swift[self.swift.index("    func run(_ t: String"):self.swift.index("\n}\n\n// MARK: - Agent panels")]
        unpoint = self.swift[self.swift.index("func unpoint("):self.swift.index("// A line from the box")]
        self.assertIn("unpoint(false)", start)
        self.assertIn("pointContext = nil; unpoint(false)", run)
        self.assertIn("if notify { gone?() }", unpoint)

    def test_released_dictation_drops_queued_level_updates(self):
        start = self.swift[self.swift.index("    func start(dictate: Bool, quiet: Bool = false)"):self.swift.index("    func heard(")]
        level = start[start.index('js("level", v)') - 160:start.index('js("level", v)') + 20]
        self.assertIn("listenID == listeningID, self?.engine.isRunning == true", level)

    def test_talking_about_a_drawing_shows_the_listening_orb(self):
        self.assertIn('if replying && !drawingReply { js(picking ? "pickHear" : "draft", "") } else { js("listen")', self.swift)
        self.assertIn('js(drawingReply ? "words" : picking ? "pickHear" : "draft", now)', self.swift)
        self.assertIn('typed(response, heard: true)', self.swift)

    def test_spoken_drawing_reply_keeps_the_done_card_agent(self):
        start = self.swift[self.swift.index("    func start(dictate: Bool, quiet: Bool = false)"):self.swift.index("    func heard(")]
        typed = self.swift[self.swift.index("    func typed("):self.swift.index("    func finish()", self.swift.index("    func typed("))]
        self.assertIn('replyAgent = dictate || (retryOffer && !askFile.isEmpty) ? "" : agentCard', start)
        self.assertIn('if !heard { replyAgent = agentCard }', typed)
        self.assertNotIn('replacement = nil; replyAgent = agentCard', typed)

    def test_voice_ask_that_heard_nothing_ends_quietly(self):
        # Oct 20, 2026: a tap, or clicking in to type after letting go, ended in "Didn't catch that." / an empty review.
        finish = self.swift[self.swift.index("    func finish() {"):self.swift.index("    // atticus.py --wait, started")]
        self.assertNotIn("Didn't catch that", finish)
        self.assertIn('if did.isEmpty { js("msg", ""); return hide(after: 0.2) }', finish)
        stop = self.swift[self.swift.index("    func stop() {", self.swift.index("final class App")):self.swift.index("    func applyReplacement()")]
        quiet = 'if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { hush(); js("msg", ""); return hide(after: 0.2) }'
        self.assertLess(stop.index(quiet), stop.index("review(\"Couldn’t confirm your words."))
        typing = self.swift[self.swift.index('if b["type"] != nil {'):self.swift.index('if let s = b["link"]')]
        self.assertIn('else if busy && proc == nil && offerText == nil && !dictating && text.isEmpty { hush(); js("msg", "") }', typing)
        start = self.swift[self.swift.index("    func start(dictate: Bool, quiet: Bool = false)"):self.swift.index("    func heard(")]
        self.assertLess(start.index("began = Date()   // key-down"), start.index("engine.start(device"))
        msg = self.overlay[self.overlay.index("    msg(s) {"):self.overlay.index("    stopped(s) {")]
        self.assertIn("document.body.classList.remove('hearing')", msg)   # a tap's quiet end comes straight from listening
        self.assertIn('if (part(\'q\')?.classList.contains(\'empty\')) { turn().remove(); status(s); }', msg)   # "" leaves no line

    def test_hidden_box_forgets_hover(self):
        gone = self.swift[self.swift.index("    func gone()"):self.swift.index("    func pill(")]
        self.assertIn("hovering = false", gone)   # else hide() waits on a mouse that left with the panel
        self.assertIn('js("hover", false)', gone)

    def test_unconfirmed_drawing_reply_does_not_leave_the_box_busy(self):
        stop = self.swift[self.swift.index("    func stop() {", self.swift.index("final class App")):self.swift.index("    func applyReplacement()")]
        branch = stop[stop.index("if let old = offerText"):stop.index("return }", stop.index("if let old = offerText"))]
        self.assertIn("busy = proc?.isRunning == true", branch)

    def test_agent_card_never_takes_return_from_typing_in_another_app(self):
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        monitor = panels[panels.index("keyMonitor ="):panels.index("timer =")]
        self.assertIn("app.defaultKey(false)", monitor)
        self.assertIn("kVK_Return", monitor)   # Return itself must still reach the card

    def test_a_finish_opens_its_own_chip_and_never_the_box(self):
        # Oct 21: "when the agents finish, the original Atticus box pops up ... just have the regular agent box pop up"
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        ping = panels[panels.index('} else if kind == "ping"'):panels.index('} else if kind == "steered"')]
        self.assertIn('row["status"] as? String == "done"', ping)
        self.assertIn("else { expand(id) }", ping)
        self.assertIn("if quiet { if row[\"notified\"] as? Bool != true { notify(row)", ping)   # sharing or a meeting: a notification, no chip
        self.assertNotIn("show(", ping)
        expand = panels[panels.index("    func expand("):panels.index("    // Near the shelf")]
        self.assertIn('js("shelf","expand",id)', expand)
        self.assertIn('app.sound("Hero"', expand)
        self.assertNotIn("app.", expand.replace('app.sound("Hero"', ''))   # the box is never shown, pinned or framed
        self.assertNotIn('"seen"', expand)   # seen only when the user opens or hides it
        ready = panels[panels.index('        case "ready":'):panels.index('        case "size":')]
        self.assertIn('if !expandOnReady.isEmpty { js(surface,"expand",expandOnReady); expandOnReady = "" }', ready)   # a shelf page still loading
        tick = panels[panels.index("    func tick()"):panels.index("    func open(_ id")]
        self.assertNotIn("show(", tick)
        for gone in ["pending", "doneFrame", "cardBesideShelf", "byShelf", "lastKey"]:
            self.assertNotIn(gone, panels)
        self.assertNotIn("cardBesideShelf", self.swift)
        self.assertIn("expand(id){", self.agents)

    def test_agent_handoff_drops_the_foreground_mini_screen_before_fading(self):
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        accept = panels[panels.index("    func accept("):panels.index("    func launch()")]
        self.assertLess(accept.index("if from != nil { app.mini.reset() }"), accept.index("app.hide(after:3.5)"))

    def test_interrupted_agent_card_releases_pin_and_return(self):
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        tick = panels[panels.index("    func tick()"):panels.index("    func open(_ id")]
        interrupted = tick[tick.index("if let id = ping"):]
        self.assertIn('app.agentCard = ""', interrupted)
        self.assertIn("app.pinned = false", interrupted)
        self.assertIn("app.defaultKey(false)", interrupted)
        self.assertIn('app.js("agentCancelled")', interrupted)

    def test_done_card_is_never_dropped_or_marked_seen_unseen(self):
        # Oct 21: a finished agent was marked seen 0.1 s after it ended, yet no card was in view: show() sent seen at once,
        # and the next click in any other app closed the box.
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        show = panels[panels.index("    func show(_ id:String"):panels.index("    func tick()")]
        self.assertNotIn('"seen","id":id]', show)
        self.assertIn('if let old = ping, old != id { send(["action":"seen","id":old]) }', show)   # a card it replaces was in view
        tick = panels[panels.index("    func tick()"):panels.index("    func open(_ id")]
        cancel = tick[tick.index("if let id = ping"):tick.index('app.js("agentCancelled")')]
        self.assertIn("!app.panel.isVisible || app.busy || app.engine.isRunning", cancel)   # only the user's close or ask ends it
        self.assertIn('send(["action":"seen","id":id])', cancel)
        self.assertIn("body.dictate :is(#thread,", self.overlay)

    def test_agent_show_brings_the_done_card_after_the_ask_ends(self):
        spawn = self.swift[self.swift.index("    func spawn()"):self.swift.index("    func unwarm()")]
        self.assertIn('if line.hasPrefix("▤ ") { self.showAgent = String(line.dropFirst(2)); continue }', spawn)
        ended = spawn[spawn.index("p.terminationHandler"):]
        self.assertLess(ended.index("self.busy = false"), ended.index("agentsUI.show(self.showAgent)"))   # tick() drops a card shown while busy
        self.assertLess(ended.index("agentsUI.show(self.showAgent)"), ended.index("self.hide(after:"))
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        show = panels[panels.index("    func show(_ id:String"):panels.index("    func tick()")]
        self.assertIn("openView(id)", show)
        self.assertIn('ping = id', show)
        self.assertIn('app.js("agentDone",row)', show)

    def test_moved_guide_explains_why_it_closed(self):
        drawing = self.swift[self.swift.index("final class ScreenDrawing"):self.swift.index("// The box can take typing")]
        tick = drawing[drawing.index("    func tick()"):]
        stale = tick[tick.index("guard Self.current(target)"):]
        self.assertLess(stale.index('status?("The screen changed. Ask again to continue.")'), stale.index("clear()"))

    def test_in_app_accessibility_calls_are_bounded(self):
        init = self.swift[self.swift.index("    override init() {\n        let cfg = WKWebViewConfiguration()"):self.swift.index("    func userContentController(_ c: WKUserContentController")]
        self.assertIn("AXUIElementSetMessagingTimeout(AXUIElementCreateSystemWide(), 0.5)", init)
        menu = self.swift[self.swift.index("    static func menuShortcut("):self.swift.index("    static func sendKeys(")]
        self.assertIn("AXUIElementSetMessagingTimeout(application, 0.15)", menu)
        web = self.swift[self.swift.index("    static func webFocused("):self.swift.index("    // An app sends keys")]
        self.assertIn("AXUIElementSetMessagingTimeout(application, 0.15)", web)

    def test_sleep_or_lock_releases_recording_and_shortcut_state(self):
        prepare = self.swift[self.swift.index("    func prepareForInactiveSession()"):self.swift.index("    func dictateShortcut(", self.swift.index("    func prepareForInactiveSession()"))]
        self.assertIn("shortcutDown = false; dictateShortcutDown = false", prepare)
        self.assertIn("quietAudio.end(immediate: true)", prepare)
        observers = self.swift[self.swift.index("var specialGlobalHotkeys"):self.swift.index("func specialHotkey(")]
        self.assertIn("NSWorkspace.willSleepNotification", observers)
        self.assertIn("NSWorkspace.didWakeNotification", observers)
        self.assertIn("NSWorkspace.sessionDidResignActiveNotification", observers)
        self.assertIn("specialMainDown = false; specialDictateDown = false", observers)
        state = self.swift.split('    var wakeSuspended: Bool ', 1)[1].split('\n', 1)[0]
        changes = observers[observers.index('        if name == NSWorkspace.willSleepNotification'):observers.index('        app.prepareForInactiveSession()')]
        swift = '''import Foundation
struct NSWorkspace {
    static let willSleepNotification = "sleep", didWakeNotification = "wake"
    static let sessionDidResignActiveNotification = "lock", sessionDidBecomeActiveNotification = "unlock"
}
final class State {
    var wakeSleeping = false, wakeInactive = false
    var wakeSuspended: Bool ''' + state + '''
}
let app = State()
func notify(_ name: String) {
''' + changes + '''}
notify("lock"); notify("sleep"); notify("wake")
precondition(app.wakeSuspended, "wake reopened microphone in an inactive session")
notify("unlock"); precondition(!app.wakeSuspended)
notify("sleep"); notify("unlock"); precondition(app.wakeSuspended)
notify("wake"); precondition(!app.wakeSuspended)
print("wake waits for active session")
'''
        self.assertIn("wake waits for active session", run_swift(self, swift))

    def test_display_changes_clear_stale_drawings_and_keep_agent_windows_reachable(self):
        app_init = self.swift[self.swift.index("    override init() {\n        let cfg = WKWebViewConfiguration()"):self.swift.index("    func userContentController(_ c: WKUserContentController")]
        screen = app_init[app_init.index("NSApplication.didChangeScreenParametersNotification"):]
        self.assertIn("drawing.clear()", screen)
        self.assertIn("The screen changed. Ask again to continue.", screen)
        self.assertIn("interrupted = hadDrawing && (engine.isRunning || dictating || busy)", screen)
        self.assertLess(screen.index("if interrupted { hush() }"), screen.index("drawing.clear()"))
        self.assertIn('js("stopped", message)', screen)
        self.assertIn('js("dictated", ["text": message, "ok": false])', screen)
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("    func js(_ surface:", self.swift.index("final class AgentPanels"))]
        self.assertIn("NSApplication.didChangeScreenParametersNotification", panels)
        self.assertGreaterEqual(panels.count("MeetingFrame.clamp"), 2)

    def test_visible_box_follows_the_pointer_display_without_interrupting_interaction(self):
        follow = self.swift[self.swift.index("    func followPointerScreen()"):self.swift.index("    func pointElement(")]
        self.assertIn("panel.isVisible, !dragging, !hovering, let f = pointerFollow(panel.frame)", follow)
        self.assertNotIn("composing", follow)   # the typing box follows too
        self.assertIn("frame(f)", follow)
        show = self.swift[self.swift.index("    func show()"):self.swift.index("    func hide(")]
        self.assertIn("startFollowingPointerScreen()", show)
        gone = self.swift[self.swift.index("    func gone()"):self.swift.index("    func pill(")]
        self.assertIn("followTimer?.invalidate()", gone)
        self.assertIn("if !dictate && !drawingReply { targetScreen = currentRequestScreen(panel) }", self.swift)
        self.assertIn("if !drawing.active { targetScreen = currentRequestScreen(panel) }", self.swift)
        self.assertIn("input,textarea,[contenteditable=true]", self.overlay)

    def test_speculative_voice_start_keeps_the_key_down_focus_snapshot(self):
        run = self.swift[self.swift.index("    func run(_ t: String"):self.swift.index("\n    }\n}", self.swift.index("    func run(_ t: String"))]
        self.assertIn("if !busy && !engine.isRunning { noteHidden() }", run)

    def test_shelf_follow_keeps_side_offsets(self):
        geometry = self.swift[self.swift.index("enum MeetingFrame {"):self.swift.index("final class MeetingWebView")]
        harness = "import Cocoa\n" + geometry + r'''
let a = NSRect(x: 0, y: 0, width: 1440, height: 875), b = NSRect(x: 1440, y: -200, width: 1920, height: 1055)
func go(_ f: NSRect) -> NSRect { MeetingFrame.clamp(MeetingFrame.follow(f, a, b, right: f.midX > a.midX, top: f.midY > a.midY), b) }
let shelf = NSRect(x: a.maxX - 272, y: a.maxY - 160, width: 260, height: 152)   // default: 12 from the right, 8 from the top
let moved = go(shelf)
precondition(b.maxX - moved.maxX == 12 && b.maxY - moved.maxY == 8 && moved.size == shelf.size)
let dragged = go(NSRect(x: 8, y: 8, width: 260, height: 52))   // dragged to the bottom-left
precondition(dragged.minX - b.minX == 8 && dragged.minY - b.minY == 8)
let small = NSRect(x: -800, y: 0, width: 800, height: 600)
let clamped = MeetingFrame.clamp(MeetingFrame.follow(shelf, a, small, right: true, top: true), small)
precondition(small.contains(clamped))
print("shelf follows")
'''
        self.assertIn("shelf follows", run_swift(self, harness))

    def test_shelf_follow_waits_for_drag_and_open_chip(self):
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        follow = panels[panels.index("    func follow()"):panels.index("    // The agent's orb lifts off")]
        for guard in ["drag == nil, flight == nil, !following", 'evaluateJavaScript("agents.expanded()")', "let f = pointerFollow(shelf.frame)"]:
            self.assertIn(guard, follow)
        tick = panels[panels.index("    func tick()"):panels.index("    func open(_ id")]
        self.assertIn("follow()", tick)
        self.assertIn("!(shelf.isVisible && shelf.screen == screen)", panels[panels.index("    func placeShelf("):])
        self.assertIn("expanded:()=>expanded", self.agents)

    def test_finished_agents_fold_into_the_shelf_and_a_chip_click_opens_the_agent_view(self):
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        dismiss = panels[panels.index("    func dismissPing("):panels.index("    func show(_ id:String")]
        self.assertIn('send(["action":"seen","id":id])', dismiss)   # Later/Open restart its 10 minutes
        self.assertNotIn('"leave"', dismiss); self.assertNotIn("dismissed.insert", dismiss)   # it folds, it does not leave the shelf
        self.assertNotIn('"leave"', panels); self.assertNotIn("leaveAt", self.agents)
        self.assertIn("var hasChips: Bool { lingering ||", panels)   # the pill alone keeps the shelf up; quiet still hides it first
        self.assertIn('case "view", "show": openView(id); if rows[id]?["status"] as? String == "done" { send(["action":"seen","id":id]) }', panels)   # opened: seen, its 10 minutes restart
        self.assertIn('case "lingering": lingering = body["value"] as? Bool ?? false', panels)
        show = panels[panels.index("    func show(_ id:String"):panels.index("    func expand(")]
        self.assertIn("app.agentCard = id", show)   # talking or typing in the box then steers this agent (replyAgent)
        self.assertIn("ensureShelf(preload:true)", panels[panels.index('if kind == "list"'):panels.index('} else if kind == "named"')])   # after a restart
        self.assertIn('max(r["ended"] as? Double ?? 0, r["seenAt"] as? Double ?? 0) < 600', panels)
        self.assertIn("LINGER=600", self.agents)   # the same 10 minutes on both sides
        typed = self.swift.split("    func typed(", 1)[1].split("    func finish()", 1)[0]
        self.assertIn("replyAgent = agentCard", typed)

    def test_agents_cleared_from_the_shelf_stay_cleared_over_a_restart(self):
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        self.assertIn('var dismissed = Set(Prefs.d["agentDismissed"] as? [String] ?? [])', panels)
        # every change is saved, only for agents that could still show: working, or finished/seen in the last 10 minutes
        self.assertIn('didSet { if dismissed != oldValue { Prefs.set("agentDismissed", dismissed.filter { rows[$0].map { Self.live.contains($0["status"] as? String ?? "") || Self.lingers($0) } ?? false }', panels)
        dismiss = panels[panels.index('        case "dismiss":'):panels.index('        case "stack":')]
        self.assertLess(dismiss.index('rows[id]?["seenAt"] = Date().timeIntervalSince1970'), dismiss.index("dismissed.insert(id)"))   # × restarts its 10 minutes, as atticus.py saves it
        self.assertIn('if row["status"] as? String == "needs-you" || finished { dismissed.remove(id) }', panels)   # a finish shows again, as on the page
        self.assertIn('let finished = Self.live.contains(rows[id]?["status"] as? String ?? "") && Self.lingers(row)', panels)
        self.assertIn('js(surface,"prefs",["dismissed":Array(dismissed)', panels)

    def test_shelf_hover_starts_on_the_mouse_event_not_a_poll_or_timer(self):
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        # a faded shelf ignores the mouse, so it came back only on the 0.1 s tick, then waited for another move
        self.assertIn('NSEvent.addGlobalMonitorForEvents(matching:.mouseMoved) { [weak self] _ in self?.fade() }', panels)
        self.assertIn('NSEvent.addLocalMonitorForEvents(matching:.mouseMoved) { [weak self] e in self?.fade(); return e }', panels)
        fade = panels[panels.index("    func fade()"):panels.index("    func tick()")]
        self.assertLess(fade.index("shelf.ignoresMouseEvents = fade"), fade.index("if inside { (shelf.contentView as? PointerView)?.here() }"))   # the pointer reaches the page in the same move
        self.assertIn("$0.duration = fade ? 0.2 : 0.08", fade)   # Oct 21: a faded shelf took 0.2 s to come back under the pointer, so the hover tint looked late
        tick = panels[panels.index("    func tick()"):panels.index("    func open(")]
        self.assertIn("fade()", tick)   # the 0.3 s dwell still fades it
        self.assertNotIn("ignoresMouseEvents", tick)
        self.assertIn("override func mouseExited(with e: NSEvent) { here() }", self.swift)
        hover = self.agents[self.agents.index("function hoverAt("):self.agents.index("const steered=")]
        self.assertNotIn("setTimeout", hover); self.assertNotIn("setExpanded", hover)   # hover tints, a click opens (Oct 21: hover-open was laggy)
        self.assertIn("expanded===r.id?command('view',r.id):setExpanded(r.id)", self.agents)
        self.assertIn('NSEvent.addGlobalMonitorForEvents(matching:.leftMouseDown) { [weak self] _ in self?.js("shelf","blur") }', panels)   # a click off the shelf closes it

    def test_hidden_shelf_costs_nothing_and_drops_its_hover(self):
        # Oct 21: a hidden shelf got visible(false) on every 0.1 s tick, kept .near, .hot and the hand cursor,
        # and the global move monitor woke the app on every mouse move all day with no shelf up
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        init = panels[panels.index("    override init()"):panels.index("    func js(")]
        self.assertNotIn("mouseMoved", init)
        tick = panels[panels.index("    func tick()"):panels.index("    func open(")]
        hidden = tick[tick.index("if hidden || !hasChips {"):tick.index("            else {")]
        self.assertIn('if shelf.isVisible { shelf.orderOut(nil); js("shelf","visible",false); pointerNext = []; flushPointer() }', hidden)
        self.assertIn("moves.forEach(NSEvent.removeMonitor); moves = []", hidden)
        shown = tick[tick.index("            else {"):tick.index("follow()")]
        self.assertLess(shown.index("if moves.isEmpty {"), shown.index("addGlobalMonitorForEvents(matching:.mouseMoved)"))
        ready = panels[panels.index('        case "ready":'):panels.index('        case "size":')]
        self.assertIn('js(surface,"visible",shelf?.isVisible == true)', ready)   # a preloaded shelf starts hidden

    def test_each_agent_from_one_ask_swims_to_its_own_orb(self):
        # Oct 21: one moveFrom was taken by the first offer, so later agents from the same ask landed with no swim;
        # and each slot was read before the next chip pushed it down, so the orbs all aimed at the top slot.
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        prepare = panels[panels.index("    func prepare("):panels.index("    var sorted:")]
        self.assertIn('moveFrom[brief["handoffId"] as? String ?? ""] = from ?? []', prepare)
        self.assertIn('accept(id, from:moveFrom.removeValue(forKey:row["handoffId"] as? String ?? ""))', panels)
        accept = panels[panels.index("    func accept("):panels.index("    func launch()")]
        self.assertLess(accept.index('js("shelf","state",row)'), accept.index("if moveFrom.isEmpty { launch() }"))   # the last offer of the ask launches every swim
        self.assertIn("asyncAfter(deadline:.now() + 0.4) { [weak self] in self?.launch() }", accept)   # an offer that never comes holds no swim
        launch = panels[panels.index("    func launch()"):panels.index("    func placeShelf(")]
        self.assertIn("moveFrom = [:]", launch)
        self.assertIn("agents.slot('\\(id)')", launch)
        fly = panels[panels.index("    func fly("):panels.index("    func makeWeb(")]
        self.assertNotIn("flight?.orderOut(nil)", fly)   # a second swim no longer cuts off the first

    def test_every_floating_surface_jumps_to_the_pointer_display_through_one_check(self):
        shared = self.swift[self.swift.index("func pointerFollow("):self.swift.index("// Freeze the display")]
        self.assertIn("NSEvent.pressedMouseButtons == 0", shared)   # never mid-drag or while a button is held
        self.assertIn("from != to", shared)
        # the same side-and-offset formula the shelf-follow harness proves
        self.assertIn("MeetingFrame.clamp(MeetingFrame.follow(f, from, to, right: f.midX > from.midX, top: f.midY > from.midY), to)", shared)
        box = self.swift[self.swift.index("    func followPointerScreen()"):self.swift.index("    func pointElement(")]
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("final class RoutineWake")]
        shelf = panels[panels.index("    func follow()"):panels.index("    // The agent's orb lifts off")]
        for body in [box, shelf]:   # box, typing box, answer, dictation pill; agent shelf and the done card beside it
            self.assertIn("pointerFollow(", body)
            for slide in ["animator()", "NSAnimationContext", "glide(", "animate: true", "MeetingFrame.follow("]:
                self.assertNotIn(slide, body)
        self.assertEqual(self.swift.count("pointerFollow("), 4)   # definition, box, shelf check and shelf move: no per-panel copies
        self.assertEqual(self.swift.count("MeetingFrame.follow("), 1)
        show = self.swift[self.swift.index("    func show()"):self.swift.index("    func hide(")]
        self.assertIn("startFollowingPointerScreen()", show)   # the dictation pill opens through show() too
        self.assertIn("pill(true); show()", self.swift)

    def test_agent_permission_poll_stops_after_one_grant(self):
        panels = self.swift[self.swift.index("final class AgentPanels"):self.swift.index("    func receive(_ event:", self.swift.index("final class AgentPanels"))]
        allow = panels[panels.index("    func allow("):]
        granted = allow[allow.index("if Onboarding.granted"):]
        self.assertLess(granted.index("t.invalidate()"), granted.index('self.send(["action":"granted"'))
        self.assertGreaterEqual(granted.count('["_a"] as? String == ask'), 1)

    def test_target_app_also_matches_the_app_bundle_name(self):
        lookup = self.swift[self.swift.index('["--window-target","--target-app"].contains'):]
        lookup = lookup[:lookup.index("exit(0)")]
        self.assertIn("bundleURL?.deletingPathExtension().lastPathComponent.localizedCaseInsensitiveCompare(name)", lookup)   # "Visual Studio Code.app" runs as "Code"

    def test_window_target_reports_a_visible_unfocused_window(self):
        # A game window on a second display, uncovered but not key: --front must see it as reachable and leave it in place.
        start = self.swift.index("    static func visible(_ r: CGRect")
        visible = self.swift[start:self.swift.index("\n    }\n", self.swift.index("    static func paintRect(", start)) + 6]
        lookup = self.swift[self.swift.index('["--window-target","--target-app"].contains'):]
        self.assertIn('target["visible"] = onScreen && target["minimized"] as? Bool != true &&', lookup[:lookup.index("\n    exit(0)\n}")])
        look = self.swift[self.swift.index('CommandLine.arguments[1] == "--look"'):self.swift.index('// `Atticus --text <app>')]
        self.assertIn("SCContentFilter(desktopIndependentWindow: w)", look)   # the window's own pixels: right even when covered
        self.assertIn("MiniScreen.paintRect(w.frame, display: d.frame, pictureHeight: img.height)", look)
        self.assertLess(look.index("c.draw(shot, in: spot)"), look.index('print("window")'))   # it says painted only after painting
        out = run_swift(self, "import CoreGraphics\nenum MiniScreen {\n" + visible + r'''}
// Monitor at x 1512, 2560x1440 points -> a 1280x720 picture (scale 0.5); the window's top-left at (1900, 200) is picture pixel (194, 100)
precondition(MiniScreen.paintRect(CGRect(x:1900,y:200,width:1100,height:800), display:CGRect(x:1512,y:0,width:2560,height:1440), pictureHeight:720) == CGRect(x:194,y:220,width:550,height:400))
let laptop = CGRect(x:0,y:0,width:1512,height:982), monitor = CGRect(x:1512,y:0,width:2560,height:1440), game = CGRect(x:1900,y:200,width:1100,height:800)
precondition(MiniScreen.visible(game, displays:[laptop, monitor], above:[CGRect(x:0,y:0,width:1512,height:982)]))   // the user's window is on the other display
precondition(MiniScreen.visible(game, displays:[laptop, monitor], above:[CGRect(x:1900,y:200,width:100,height:80)]))   // a small corner overlap
precondition(!MiniScreen.visible(game, displays:[laptop, monitor], above:[CGRect(x:2000,y:300,width:600,height:500)]))   // covered
precondition(!MiniScreen.visible(game, displays:[laptop], above:[]))   // its display is gone: off-screen
precondition(!MiniScreen.visible(CGRect(x:3800,y:200,width:800,height:600), displays:[laptop, monitor], above:[]))   // mostly past the edge
precondition(!MiniScreen.visible(.zero, displays:[monitor], above:[]))
print("visible ok")
''')
        self.assertIn("visible ok", out)

    def test_settings_describe_all_shortcuts_and_remove_dead_pointer_toggle(self):
        self.assertGreaterEqual(self.settings.count("a modifier on its own"), 2)
        self.assertNotIn('data-k="pointer"', self.settings)
        self.assertNotIn(">Show me where<", self.settings)


if __name__ == "__main__":
    unittest.main()
