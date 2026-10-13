// Atticus overlay: hold to talk and release to send, or press to start and press again to send.
// A box in the top left (ui/ui.html, with the thinking-orbs orb) shows your words live (Apple on-device speech),
// then Atticus's notes and steps while `atticus.py` works, then the answer. It never takes focus.
// Build: ./build.sh. Kept running by ~/Library/LaunchAgents/com.atticus.app.plist
import Cocoa
import Carbon
import AVFoundation
import Speech
import WebKit
import ScreenCaptureKit
import Vision
import PDFKit
import QuickLookThumbnailing
import UniformTypeIdentifiers
import EventKit
import CoreAudio

let dir = ProcessInfo.processInfo.environment["ATTICUS_RESOURCES_DIR"] ?? Bundle.main.resourcePath!   // build.sh copies atticus.py and ui/ in here

// Settings, shared with atticus.py (model, screen, openOn, instant): ~/.config/atticus/settings.json
enum Prefs {
    static let path = (ProcessInfo.processInfo.environment["ATTICUS_DIR"] ?? NSString(string: "~/.config/atticus").expandingTildeInPath) + "/settings.json"
    static let defaults: [String: Any] = ["hotkeyCode": 49, "hotkeyMods": controlKey | optionKey, "hotkeyLabel": "⌃⌥Space", "login": true, "paused": false, "corner": "top-left", "linger": "normal",
        "soundStart": "Pop", "soundDone": "Glass", "soundStop": "Tink", "volume": 0.16, "model": "haiku", "instant": true,
        "selection": true, "ahead": true, "aheadDelay": 0.7, "live": true, "screen": "auto", "openOn": "here", "workIn": "back", "miniScreen": true, "pageJS": false,
        "speak": false, "autoCopy": false, "hideWhenSharing": true, "menuIcon": true, "autoUpdate": true,
        "learn": true, "safe": true, "pointer": false, "meeting": false, "meetingSave": true, "meetingAuto": "sure", "meetingNudge": false, "meetingDetect": true, "learnMe": true, "stats": true, "tips": true, "askMe": true, "escalate": true, "meetingSummary": true, "escalateAuto": false, "input": "voice", "talkMode": "hold", "speechModel": "speech", "improve": false, "improveAsked": false, "draftInsert": "ask", "boxW": 460, "boxH": 360]
    static var d: [String: Any] = defaults.merging(
        (try? JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: path)))) as? [String: Any] ?? [:]) { $1 }
    static func set(_ k: String, _ v: Any) {
        d[k] = v
        try? FileManager.default.createDirectory(atPath: (path as NSString).deletingLastPathComponent, withIntermediateDirectories: true)
        if let j = try? JSONSerialization.data(withJSONObject: d, options: [.prettyPrinted, .sortedKeys]) { try? j.write(to: URL(fileURLWithPath: path), options: .atomic) }
    }
    static func bool(_ k: String) -> Bool { d[k] as? Bool ?? false }
    static func str(_ k: String) -> String { d[k] as? String ?? "" }
    static func num(_ k: String) -> Double { (d[k] as? NSNumber)?.doubleValue ?? 0 }
}

// Read-aloud uses the Mac's Spoken Content voice, and most people never pick one: once, switch it to Siri's.
// A test line that fails (Siri voice not downloaded) puts the old voice back.
func siriVoice() {
    guard !UserDefaults.standard.bool(forKey: "siriVoice") else { return }
    UserDefaults.standard.set(true, forKey: "siriVoice")
    DispatchQueue.global().async {
        let key = "SpokenContentDefaultVoiceSelectionsByLanguage" as CFString, dom = "com.apple.Accessibility" as CFString
        let old = CFPreferencesCopyAppValue(key, dom)
        if (old as? [Any])?.contains(where: { (($0 as? [String: Any])?["voiceId"] as? String)?.hasPrefix("com.apple.siri.") == true }) == true { return }
        let siri: [Any] = ["en", ["_type": "Speech.VoiceSelection", "_version": 0, "boundLanguage": "en", "voiceId": "com.apple.siri.natural.en-US-F"]]
        CFPreferencesSetAppValue(key, siri as CFArray, dom); CFPreferencesAppSynchronize(dom)
        let out = NSTemporaryDirectory() + "atticus-voice.aiff", p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/say"); p.arguments = ["-o", out, "hi"]
        try? p.run(); p.waitUntilExit()
        let size = (try? FileManager.default.attributesOfItem(atPath: out)[.size] as? Int) ?? 0
        try? FileManager.default.removeItem(atPath: out)
        if p.terminationStatus != 0 || size < 1000 { CFPreferencesSetAppValue(key, old, dom); CFPreferencesAppSynchronize(dom) }
    }
}

// The talk shortcut, any key plus modifiers, recorded in Settings: Carbon modifiers to register, and the
// modifier keys whose release ends listening (none for a lone F-key: its own key-up ends it).
func hotkey() -> (code: Int, mods: Int, flags: NSEvent.ModifierFlags) {
    let m = Int(Prefs.num("hotkeyMods"))
    var f: NSEvent.ModifierFlags = []
    if m & cmdKey != 0 { f.insert(.command) }; if m & shiftKey != 0 { f.insert(.shift) }
    if m & optionKey != 0 { f.insert(.option) }; if m & controlKey != 0 { f.insert(.control) }
    return (Int(Prefs.num("hotkeyCode")), m, f)
}

func transcriptKey(_ s: String) -> String {
    s.lowercased().split(whereSeparator: { $0.isWhitespace }).joined(separator: " ").trimmingCharacters(in: CharacterSet(charactersIn: " .,!?:;"))
}

// atticus.py with whatever python3 this Mac has (Homebrew's first, else Apple's).
func py(_ args: [String], _ extra: [String: String] = [:]) -> Process {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    p.arguments = ["python3", dir + "/atticus.py"] + args
    var env = ProcessInfo.processInfo.environment
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + (env["PATH"] ?? "/usr/bin:/bin")
    env["ATTICUS_APP"] = Bundle.main.executablePath
    env.merge(extra) { $1 }
    p.environment = env
    return p
}

// Freeze the user's display before live actions can move or focus another window.
func currentRequestScreen() -> String {
    let pid = NSWorkspace.shared.frontmostApplication?.processIdentifier
    let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly,.excludeDesktopElements],kCGNullWindowID) as? [[String:Any]] ?? []
    let frame = windows.first(where: { ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid && ($0[kCGWindowLayer as String] as? Int) == 0 }).flatMap(MiniScreen.bounds)
    return (NSScreen.screens.first { screen in
        let id = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? CGMainDisplayID()
        return frame.map { CGDisplayBounds(id).contains(CGPoint(x:$0.midX,y:$0.midY)) } ?? screen.frame.contains(NSEvent.mouseLocation)
    } ?? NSScreen.main)?.localizedName ?? ""
}

func axAttribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    return AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success ? value : nil
}
// AX has no public window-number attribute ("AXWindowNumber" is always nil); this private call is the one Rectangle/yabai/AltTab use.
@_silgen_name("_AXUIElementGetWindow") func _AXUIElementGetWindow(_ element: AXUIElement, _ id: UnsafeMutablePointer<CGWindowID>) -> AXError
func axWindowNumber(_ element: AXUIElement) -> NSNumber? {
    var id: CGWindowID = 0
    return _AXUIElementGetWindow(element, &id) == .success && id > 0 ? NSNumber(value: id) : nil
}

struct TextSelection {
    let element: AXUIElement, app: NSRunningApplication, text: String, range: CFRange?
    static func capture(_ app: NSRunningApplication? = NSWorkspace.shared.frontmostApplication, enabled: Bool = Prefs.bool("selection"), allowEmpty: Bool = false) -> TextSelection? {
        guard enabled, AXIsProcessTrusted(), let app,
              app != .current else { return nil }
        let target = AXUIElementCreateApplication(app.processIdentifier)
        AXUIElementSetMessagingTimeout(target, 0.15)
        guard let focused = axAttribute(target, kAXFocusedUIElementAttribute) else { return nil }
        let element = focused as! AXUIElement
        AXUIElementSetMessagingTimeout(element, 0.15)
        guard axAttribute(element, kAXSubroleAttribute) as? String != kAXSecureTextFieldSubrole,
              let text = axAttribute(element, kAXSelectedTextAttribute) as? String,
              allowEmpty || text.count <= 6000 else { return nil }
        let s = TextSelection(element: element, app: app, text: text, range: selectedRange(element))
        // nothing highlighted: keep it only as a cursor in a text box, where a draft can go
        return allowEmpty || !s.caret || s.range != nil && (s.editable || s.pastable) ? s : nil
    }
    var caret: Bool { text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    static func selectedRange(_ element: AXUIElement) -> CFRange? {
        guard let value = axAttribute(element, kAXSelectedTextRangeAttribute), CFGetTypeID(value) == AXValueGetTypeID() else { return nil }
        var range = CFRange()
        return AXValueGetValue(value as! AXValue, .cfRange, &range) ? range : nil
    }
    var editable: Bool {
        var settable = DarwinBoolean(false)
        return range != nil && AXUIElementIsAttributeSettable(element, kAXSelectedTextAttribute as CFString, &settable) == .success && settable.boolValue
    }
    // Chrome, Electron and web editors often refuse an AX write; a text field there still takes a paste.
    var pastable: Bool { ["AXTextArea", "AXTextField", "AXComboBox", "AXSearchField"].contains(axAttribute(element, kAXRoleAttribute) as? String ?? "") }
    func apply(_ draft: String, valid: @escaping () -> Bool, done: @escaping (Bool) -> Void) {
        guard valid() else { done(false); return }
        let before = value
        if editable && replace(draft) && landed(draft, before) { done(true); return }   // web editors can accept the AX write and drop the text
        guard pastable, !app.isTerminated, range != nil else { done(false); return }
        app.activate()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
            let target = AXUIElementCreateApplication(app.processIdentifier)
            AXUIElementSetMessagingTimeout(target, 0.15)
            guard valid(), !app.isTerminated, NSWorkspace.shared.frontmostApplication == app,
                  let focused = axAttribute(target, kAXFocusedUIElementAttribute), CFEqual(focused, element),
                  let range, let current = Self.selectedRange(element),
                  current.location == range.location, current.length == range.length,
                  axAttribute(element, kAXSelectedTextAttribute) as? String == text,
                  pastable,
                  let finalFocus = axAttribute(target, kAXFocusedUIElementAttribute), CFEqual(finalFocus, element),
                  NSWorkspace.shared.frontmostApplication == app else { done(false); return }
            guard let down = CGEvent(keyboardEventSource: nil, virtualKey: draft.isEmpty ? 51 : 9, keyDown: true),
                  let up = CGEvent(keyboardEventSource: nil, virtualKey: draft.isEmpty ? 51 : 9, keyDown: false) else { done(false); return }
            let pb = NSPasteboard.general
            let saved = pb.pasteboardItems?.map { i in i.types.compactMap { t in i.data(forType: t).map { (t, $0) } } } ?? []
            if !draft.isEmpty {
                pb.clearContents()
                guard pb.setString(draft, forType: .string) else {
                    pb.writeObjects(saved.map { pairs in let i = NSPasteboardItem(); pairs.forEach { i.setData($1, forType: $0) }; return i })
                    done(false); return
                }
            }
            let changed = pb.changeCount
            let send = { (hid: Bool) in for e in [down, up] { e.flags = draft.isEmpty ? [] : .maskCommand; if hid { e.post(tap: .cghidEventTap) } else { e.postToPid(app.processIdentifier) } } }
            let finish = { (ok: Bool) in
                done(ok)
                guard !draft.isEmpty, pb.changeCount == changed else { return }
                pb.clearContents(); pb.writeObjects(saved.map { pairs in let i = NSPasteboardItem(); pairs.forEach { i.setData($1, forType: $0) }; return i })
            }
            send(false)
            // Success means the text is in the field, not that keys were sent; some apps ignore keys posted to them, so try the system keyboard once.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                if landed(draft, before) { return finish(true) }
                guard valid(), NSWorkspace.shared.frontmostApplication == app,
                      let f = axAttribute(target, kAXFocusedUIElementAttribute), CFEqual(f, element) else { return finish(false) }
                send(true)
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { finish(landed(draft, before)) }
            }
        }
    }
    var value: String? { axAttribute(element, kAXValueAttribute) as? String }
    // shortcut: a field that hides its text (nil value) counts as landed; there is nothing to check against
    func landed(_ draft: String, _ before: String?) -> Bool {
        guard let before, let now = value else { return true }
        let squash = { (s: String) in s.filter { !$0.isWhitespace } }
        return now != before && (draft.isEmpty || squash(now).contains(squash(draft)))
    }
    func replace(_ draft: String) -> Bool {
        guard !app.isTerminated, let range, let current = Self.selectedRange(element),
              current.location == range.location, current.length == range.length,
              axAttribute(element, kAXSelectedTextAttribute) as? String == text else { return false }
        // Set only the saved selection; never paste into whichever app happens to be focused.
        return AXUIElementSetAttributeValue(element, kAXSelectedTextAttribute as CFString, draft as CFString) == .success
    }
}

// Sees the mouse over the box without taking clicks or focus (clicks go to the monitors in App).
final class Tracker: NSView {
    var onMove: ((NSPoint) -> Void)?, onExit: (() -> Void)?
    override func hitTest(_ p: NSPoint) -> NSView? { nil }
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: .zero, options: [.activeAlways, .mouseMoved, .mouseEnteredAndExited, .inVisibleRect],
                                       owner: self))
    }
    override func mouseMoved(with e: NSEvent) { onMove?(convert(e.locationInWindow, from: nil)) }
    override func mouseEntered(with e: NSEvent) { onMove?(convert(e.locationInWindow, from: nil)) }
    override func mouseExited(with e: NSEvent) { onExit?() }
}

// The box can take typing (canBecomeKey) without pulling Atticus forward (nonactivating): the user's app stays in front.
final class KeyPanel: NSPanel { override var canBecomeKey: Bool { true } }

// Mini screen: local window-only buffers stay in a native layer, underneath the transparent web controls.
final class MiniScreen: NSObject, SCStreamOutput, SCStreamDelegate {
    let clip = NSView(), picture = AVSampleBufferDisplayLayer(), previous = AVSampleBufferDisplayLayer()
    var lastSample: CMSampleBuffer?, transitioning = false
    var stream: SCStream?, target: [String:Any]?, timer: Timer?, ending: DispatchWorkItem?
    var publish: (([String:Any]) -> Void)?, screen: (() -> NSScreen?)?
    var retry = Date.distantPast
    var generation = 0, shown = false, live = false, starting = false, failed = false, frames = 0
    override init() {
        super.init()
        clip.wantsLayer = true; clip.layer?.masksToBounds = true; clip.isHidden = true
        picture.videoGravity = .resizeAspect; picture.cornerRadius = 12; picture.masksToBounds = true
        picture.backgroundColor = NSColor.black.cgColor; clip.layer?.addSublayer(picture)
        previous.videoGravity = .resizeAspect; previous.cornerRadius = 12; previous.masksToBounds = true
        previous.backgroundColor = NSColor.black.cgColor; previous.opacity = 0; clip.layer?.addSublayer(previous)
    }
    static func activate(_ pid: Int32) {
        // System Events addresses the running process; cooperative AppKit activation can be refused from our background panel.
        let p = Process(); p.executableURL = URL(fileURLWithPath:"/usr/bin/osascript")
        p.arguments = ["-e", "tell application \"System Events\" to set frontmost of (first application process whose unix id is \(pid)) to true"]
        p.standardOutput = FileHandle.nullDevice; p.standardError = FileHandle.nullDevice
        guard (try? p.run()) != nil else { return }
        let deadline = Date().addingTimeInterval(2)   // runs on the main thread: a pending Automation prompt must not freeze the app
        while p.isRunning && Date() < deadline { usleep(10_000) }
        if p.isRunning { p.terminate() }
    }
    static func bounds(_ info: [String:Any]) -> CGRect? {
        (info[kCGWindowBounds as String] as? NSDictionary).flatMap { CGRect(dictionaryRepresentation:$0) }
    }
    static func windowTarget(_ app: NSRunningApplication, title: String = "", frame: [Double] = [], windows: [[String:Any]]) -> [String:Any]? {
        if !frame.isEmpty && (frame.count != 4 || !frame.allSatisfy(\.isFinite)) { return nil }
        let root = AXUIElementCreateApplication(app.processIdentifier)
        let elements = axAttribute(root, kAXWindowsAttribute) as? [AXUIElement] ?? []
        let preferred = axAttribute(root,kAXFocusedWindowAttribute).flatMap { CFGetTypeID($0) == AXUIElementGetTypeID() ? axWindowNumber($0 as! AXUIElement) : nil }
        let named = windows.map { info -> [String:Any] in
            var value = info
            if (info[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == app.processIdentifier,
               info[kCGWindowName as String] == nil, let number = info[kCGWindowNumber as String] as? NSNumber,
               let w = elements.first(where: { axWindowNumber($0) == number }) {
                value[kCGWindowName as String] = axAttribute(w,kAXTitleAttribute) as? String
            }
            return value
        }
        let candidates = named.filter {
            ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == app.processIdentifier &&
            ($0[kCGWindowLayer as String] as? Int) == 0 && bounds($0).map { $0.width > 1 && $0.height > 1 && ($0.height > 40 || $0.width < $0.height * 10) } == true &&
            (title.isEmpty || ($0[kCGWindowName as String] as? String ?? "").localizedCaseInsensitiveContains(title)) &&
            (frame.isEmpty || bounds($0).map { abs($0.minX-frame[0]) < 2 && abs($0.minY-frame[1]) < 2 && abs($0.width-frame[2]) < 2 && abs($0.height-frame[3]) < 2 } == true)
        }
        if !frame.isEmpty && candidates.count != 1 { return nil }   // indistinguishable windows are not a safe preview target
        let real = Set(elements.compactMap(axWindowNumber))   // apps own invisible full-width strips; AX lists only real windows
        let area = { (w: [String:Any]) in bounds(w).map { $0.width * $0.height } ?? 0 }
        guard let w = candidates.first(where: { ($0[kCGWindowNumber as String] as? NSNumber) == preferred })
                ?? candidates.first(where: { ($0[kCGWindowNumber as String] as? NSNumber).map(real.contains) == true })
                ?? candidates.max(by: { area($0) < area($1) }),   // no AX (other Space): the strips are always the smallest
              let frame = bounds(w), let number = w[kCGWindowNumber as String] as? NSNumber else { return nil }
        let minimized = elements.contains { axWindowNumber($0) == number && axAttribute($0,kAXMinimizedAttribute) as? Bool == true }
        return ["pid":app.processIdentifier,"windowID":number.stringValue,"windowFrame":[frame.minX,frame.minY,frame.width,frame.height],
                "window":w[kCGWindowName as String] as? String ?? app.localizedName ?? "Window","app":app.localizedName ?? "App","minimized":minimized]
    }
    var pid: Int32 { (target?["pid"] as? NSNumber)?.int32Value ?? 0 }
    var id: UInt32 { UInt32(target?["windowID"] as? String ?? "") ?? 0 }
    var holds: Bool { target != nil && shown && timer == nil }
    func receive(_ value: [String:Any]) {
        guard let p = value["pid"] as? NSNumber, p.int32Value > 0,
              let w = value["windowID"] as? String, UInt32(w).map({ $0 > 0 }) == true,
              let f = value["windowFrame"] as? [Double], f.count == 4, f.allSatisfy(\.isFinite), f[2] > 0, f[3] > 0 else { return }
        ending?.cancel(); ending = nil
        failed = false
        let icon = pid == p.int32Value ? target?["icon"] as? String : nil
        let changed = pid != p.int32Value || id != UInt32(w)!
        if changed {
            let old = lastSample; stopCapture(clear:true); failed = false; frames = 0
            if let old { previous.sampleBufferRenderer.enqueue(old); previous.opacity = 1; transitioning = true }
        }
        target = value
        if let icon { target?["icon"] = icon }
        else if let app = NSRunningApplication(processIdentifier:p.int32Value), let icon = app.icon,
           let data = icon.tiffRepresentation, let bitmap = NSBitmapImageRep(data:data), let png = bitmap.representation(using:.png,properties:[:]) {
            target?["icon"] = "data:image/png;base64," + png.base64EncodedString()
        }
        if timer == nil { timer = Timer.scheduledTimer(withTimeInterval:0.5,repeats:true) { [weak self] _ in self?.refresh() } }
        refresh(force:true)
    }
    // Only suppress a window on this display, frontmost, entirely on screen and unobscured by other windows.
    static func needsPreview(pid: Int32, id: UInt32, windows: [[String:Any]], front: Int32?, display: CGRect) -> Bool {
        guard front == pid, let index = windows.firstIndex(where: { ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value == id }),
              let frame = bounds(windows[index]), display.contains(frame) else { return true }
        return windows.prefix(index).contains {
            ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value != ProcessInfo.processInfo.processIdentifier &&
            ($0[kCGWindowAlpha as String] as? Double ?? 1) > 0 &&
            bounds($0).map { !$0.intersection(frame).isEmpty && $0.width > 1 && $0.height > 1 } == true
        }
    }
    func refresh(force: Bool = false) {
        guard target != nil, ending == nil else { return }
        let oldFrame = target?["windowFrame"] as? [Double]
        let oldMinimized = target?["minimized"] as? Bool ?? false
        let elements = axAttribute(AXUIElementCreateApplication(pid), kAXWindowsAttribute) as? [AXUIElement] ?? []
        if let w = elements.first(where: { axWindowNumber($0)?.uint32Value == id }) { target?["minimized"] = axAttribute(w,kAXMinimizedAttribute) as? Bool ?? false }
        let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly,.excludeDesktopElements],kCGNullWindowID) as? [[String:Any]] ?? []
        if let window = windows.first(where: { ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value == id && ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid }), let f = Self.bounds(window), f.width > 0, f.height > 0 {
            target?["windowFrame"] = [f.minX,f.minY,f.width,f.height].map(Double.init)
            if let oldFrame, oldFrame[2] != f.width || oldFrame[3] != f.height, let s = stream { Task { try? await s.updateConfiguration(Self.configuration(f)) } }
        }
        let display = screen?() ?? NSScreen.main
        let displayID = display?.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? CGMainDisplayID()
        let next = Self.needsPreview(pid:pid,id:id,windows:windows,front:NSWorkspace.shared.frontmostApplication?.processIdentifier,display:CGDisplayBounds(displayID))
        let changed = shown != next; shown = next
        if failed && Date() >= retry { failed = false }
        if !shown { stopCapture(clear:false) }
        else if target?["minimized"] as? Bool == true { stopCapture(clear:true) }
        else if stream == nil && !starting && !failed && CGPreflightScreenCaptureAccess() { startCapture() }
        if force || changed || oldFrame != target?["windowFrame"] as? [Double] || oldMinimized != (target?["minimized"] as? Bool ?? false) { send() }
    }
    func send() {
        guard var value = target else { return }; value["shown"] = shown; value["live"] = live || transitioning; publish?(value)
    }
    static func configuration(_ frame: CGRect) -> SCStreamConfiguration {
        let cfg = SCStreamConfiguration(), scale = min(600 / max(1,frame.width),375 / max(1,frame.height))
        cfg.width = max(1,Int((frame.width * scale).rounded())); cfg.height = max(1,Int((frame.height * scale).rounded()))
        cfg.minimumFrameInterval = CMTime(value:1,timescale:12); cfg.showsCursor = false
        cfg.ignoreShadowsSingleWindow = true; cfg.queueDepth = 3; cfg.scalesToFit = true; cfg.preservesAspectRatio = true
        return cfg   // matching the window aspect leaves letterboxing to the centered native layer
    }
    func startCapture() {
        generation += 1; let token = generation, windowID = id, processID = pid
        starting = true
        Task { @MainActor [weak self] in
            let all = try? await SCShareableContent.excludingDesktopWindows(true,onScreenWindowsOnly:false)
            guard let self, generation == token, shown else { return }
            guard let w = all?.windows.first(where: { $0.windowID == windowID && $0.owningApplication?.processID == processID }) else { starting = false; failed = true; retry = Date().addingTimeInterval(3); stopCapture(clear:true); send(); return }
            let cfg = Self.configuration(w.frame)
            let s = SCStream(filter:SCContentFilter(desktopIndependentWindow:w),configuration:cfg,delegate:self)
            do {
                try s.addStreamOutput(self,type:.screen,sampleHandlerQueue:.main); stream = s
                try await s.startCapture()
                if generation != token { try? await s.stopCapture() }
            } catch { if generation == token { failed = true; retry = Date().addingTimeInterval(3); stopCapture(clear:true); send() } }
        }
    }
    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer, of type: SCStreamOutputType) {
        guard self.stream === stream, type == .screen, sample.isValid,
              let attachments = CMSampleBufferGetSampleAttachmentsArray(sample,createIfNecessary:false) as? [[SCStreamFrameInfo:Any]],
              let status = attachments.first?[.status] as? Int, status == SCFrameStatus.complete.rawValue else { return }
        if picture.sampleBufferRenderer.status == .failed { picture.sampleBufferRenderer.flush(removingDisplayedImage:false) }
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(sample,createIfNecessary:true) as? [NSMutableDictionary], let info = attachments.first { info[kCMSampleAttachmentKey_DisplayImmediately] = true }
        picture.sampleBufferRenderer.enqueue(sample); lastSample = sample; frames += 1
        if transitioning {
            transitioning = false
            let fade = CABasicAnimation(keyPath:"opacity"); fade.fromValue = 1; fade.toValue = 0; fade.duration = 0.24
            previous.opacity = 0; previous.add(fade,forKey:"switch")
            let token = generation
            DispatchQueue.main.asyncAfter(deadline:.now() + 0.25) { [weak self] in if self?.generation == token { self?.previous.sampleBufferRenderer.flush(removingDisplayedImage:true) } }
        }
        if !live { live = true; starting = false; send() }
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        DispatchQueue.main.async { [weak self] in
            guard let self, self.stream === stream else { return }; failed = true; retry = Date().addingTimeInterval(3); stopCapture(clear:true); send()
        }
    }
    func stopCapture(clear: Bool) {
        generation += 1; starting = false
        if let s = stream { stream = nil; Task { try? await s.stopCapture() } }
        if clear { live = false; transitioning = false; lastSample = nil; picture.sampleBufferRenderer.flush(removingDisplayedImage:true); previous.removeAllAnimations(); previous.opacity = 0; previous.sampleBufferRenderer.flush(removingDisplayedImage:true); clip.isHidden = true }
    }
    func finish() {
        guard target != nil, ending == nil else { return }
        timer?.invalidate(); timer = nil; stopCapture(clear:false)   // freeze the last buffer; it stays until the next ask, typing, or a click on it (the page clears it)
    }
    func reset() {
        ending?.cancel(); ending = nil; timer?.invalidate(); timer = nil
        stopCapture(clear:true); target = nil; shown = false; failed = false
    }
    func layout(_ value: [String:Any]) {
        guard let r = value["rect"] as? [Double], r.count == 4, r.allSatisfy(\.isFinite),
              let c = value["clip"] as? [Double], c.count == 4, c.allSatisfy(\.isFinite), let height = clip.superview?.bounds.height else { clip.isHidden = true; return }
        CATransaction.begin(); CATransaction.setDisableActions(true)
        clip.frame = NSRect(x:c[0],y:height - c[1] - c[3],width:max(0,c[2]),height:max(0,c[3]))
        picture.frame = CGRect(x:r[0] - c[0],y:c[3] - (r[1] - c[1]) - r[3],width:max(0,r[2]),height:max(0,r[3]))
        previous.frame = picture.frame
        clip.layer?.opacity = Float(value["opacity"] as? Double ?? 1)
        clip.isHidden = !(live || transitioning) || r[2] <= 0 || r[3] <= 0
        CATransaction.commit()
    }
    func open() {
        guard (CGWindowListCopyWindowInfo(.optionAll,kCGNullWindowID) as? [[String:Any]] ?? []).contains(where: {
            ($0[kCGWindowNumber as String] as? NSNumber)?.uint32Value == id && ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == pid
        }) else { return }
        guard let a = NSRunningApplication(processIdentifier:pid), !a.isTerminated, let f = target?["windowFrame"] as? [Double], f.count == 4 else { return }
        let processID = pid, windowID = id
        let raise = {
            let windows = axAttribute(AXUIElementCreateApplication(processID),kAXWindowsAttribute) as? [AXUIElement] ?? []
            let direct = windows.filter { axWindowNumber($0)?.uint32Value == windowID }
            let matches = direct.isEmpty ? windows.filter {
                guard let p = axAttribute($0,kAXPositionAttribute), let s = axAttribute($0,kAXSizeAttribute), CFGetTypeID(p) == AXValueGetTypeID(), CFGetTypeID(s) == AXValueGetTypeID() else { return false }
                var origin = CGPoint.zero, size = CGSize.zero
                guard AXValueGetValue(p as! AXValue,.cgPoint,&origin), AXValueGetValue(s as! AXValue,.cgSize,&size) else { return false }
                return abs(origin.x - f[0]) < 2 && abs(origin.y - f[1]) < 2 && abs(size.width - f[2]) < 2 && abs(size.height - f[3]) < 2
            } : direct
            if matches.count == 1 {
                AXUIElementSetAttributeValue(matches[0],kAXMinimizedAttribute as CFString,kCFBooleanFalse)
                AXUIElementPerformAction(matches[0],kAXRaiseAction as CFString)
            }
        }
        Self.activate(processID); raise()
        DispatchQueue.main.asyncAfter(deadline:.now()+0.3) {   // AX windows on another Space can appear after activation returns
            if NSWorkspace.shared.frontmostApplication?.processIdentifier == processID { raise() }
        }
    }
}

final class App: NSObject, WKScriptMessageHandler {
    let mini = MiniScreen()
    let panel = KeyPanel(contentRect: NSRect(x: 0, y: 0, width: max(340, Prefs.num("boxW")), height: 76),
                        styleMask: [.nonactivatingPanel, .borderless], backing: .buffered, defer: false)
    let web: WKWebView
    let engine = AVAudioEngine()
    // Speech: Apple's SpeechAnalyzer (macOS 26+), on-device and free; punctuates and capitalizes.
    var feed: AsyncStream<AnalyzerInput>.Continuation?, analyzer: SpeechAnalyzer?, reading: Task<Void, Never>?
    var speechFormat: AVAudioFormat?   // what the model wants (found at launch and when the model changes)
    // Settings → Speech model: Apple's newer SpeechTranscriber, or the Dictation model the keyboard mic uses.
    func speechModule() -> any SpeechModule {
        let en = Locale(identifier: "en-US")
        return Prefs.str("speechModel") == "dictation" ? DictationTranscriber(locale: en, preset: .progressiveShortDictation)
            : SpeechTranscriber(locale: en, preset: .progressiveTranscription)
    }
    func prepareSpeech() {   // make sure the speech model is installed, and learn its audio format
        let m = speechModule()
        Task { [weak self] in
            if let r = try? await AssetInventory.assetInstallationRequest(supporting: [m]) { try? await r.downloadAndInstall() }
            let f = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [m])
            await MainActor.run { self?.speechFormat = f }
        }
    }
    var text = "", answer = "", busy = false, speechFailed = false, gen = 0
    var proc: Process?, escRef: EventHotKeyRef?, warm: (p: Process, input: FileHandle, commit: String)?
    var commit = "", listenID = 0
    var consumed = 0, fastBusy = false, did: [String] = [], pause: DispatchWorkItem?   // "Act while I'm talking": commands done mid-sentence
    var fastProc: Process?, consumedText = "", liveRevised = false, targetScreen = ""
    var ahead = "", aheadItem: DispatchWorkItem?   // words the AI already started on while the user was still holding the keys
    var stops = 0   // each key release; tells a late "words landed" from a current one
    var dragging = false, fromTop = false   // moving or resizing the box; fromTop: dragging the top edge, so the bottom stays put
    var began = Date()   // when recording began, for the recording limit
    var fresh = false   // an untouched input session
    var composing = false, compH: CGFloat = 0, clickTalk = false, quiet: DispatchWorkItem?   // typing box focused / its height from the bottom; mic button = talk without keys
    var toggleTalk = false, shortcutDown = false
    var askFile = ""   // safe mode: where the Allow / Don't Allow answer goes (atticus.py's gate waits on it)
    var retryOffer = false, offerText: String?   // answering a failure card preserves its original request
    var hovering = false, xHot = false, pinned = false, stuck = false, lastDone = Date.distantPast   // pinned: the user clicked the box, so only Esc / click-out / ✕ close it; stuck: the user dragged it, so only ✕
    var selection: TextSelection?, replacement: String?, mode = "replace", warmSel = ""   // mode: replace · delete · draft
    var selectionID = 0, selectionPending = false, replacing = false
    var mine = NSWorkspace.shared.frontmostApplication?.localizedName ?? ""   // the app the user's in, never Atticus itself
    var userApp = NSWorkspace.shared.frontmostApplication, guardUntil = Date.distantPast, allowUntil = Date.distantPast, userSwitch = Date.distantPast
    let focusFile = (Prefs.path as NSString).deletingLastPathComponent + "/focus"   // atticus.py touches it when the user asked to see an app
    var focusFree: Bool { (try? FileManager.default.attributesOfItem(atPath: focusFile)[.modificationDate] as? Date).map { Date().timeIntervalSince($0) < 60 } ?? false }
    let recent = (Prefs.path as NSString).deletingLastPathComponent + "/recent.jsonl"
    func frame(_ requested: NSRect) {   // keep the close button and composer reachable on every display
        let screen = NSScreen.screens.max { a, b in
            let x = a.visibleFrame.intersection(requested), y = b.visibleFrame.intersection(requested)
            return x.width * x.height < y.width * y.height
        } ?? NSScreen.main
        guard let screen else { return }
        let bounds = screen.visibleFrame.insetBy(dx: 8, dy: 8)
        var f = requested
        f.size.width = min(f.width, bounds.width); f.size.height = min(f.height, bounds.height)
        f.origin.x = min(max(f.minX, bounds.minX), bounds.maxX - f.width)
        f.origin.y = min(max(f.minY, bounds.minY), bounds.maxY - f.height)
        panel.setFrame(f, display: true); panel.invalidateShadow()
        js("limit", bounds.height)
    }
    // Which edges the point is on (window coordinates): 6 px edges, 14 px corners.
    func edges(_ p: NSPoint) -> (l: Bool, r: Bool, t: Bool, b: Bool)? {
        let w = panel.frame.width, h = panel.frame.height, c: CGFloat = 14
        let l = p.x < 6 || (p.x < c && (p.y < c || p.y > h - c)), r = p.x > w - 6 || (p.x > w - c && (p.y < c || p.y > h - c))
        let b = p.y < 6 || (p.y < c && (p.x < c || p.x > w - c)), t = p.y > h - 6 || (p.y > h - c && (p.x < c || p.x > w - c))
        return l || r || t || b ? (l, r, t, b) : nil
    }
    func overX(_ p: NSPoint) -> Bool { p.x > panel.frame.width - 42 && p.y > panel.frame.height - 42 }
    // Words the recognizer should expect: the user's app names plus a few of the user's own (free, on-device).
    var hints: [String] {
        let config = (Prefs.path as NSString).deletingLastPathComponent
        let shortcuts = (try? JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: config + "/skills.json")))) as? [String: Any] ?? [:]
        let user = (try? JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: config + "/me.json")))) as? [String: Any] ?? [:]
        var seen = Set<String>()
        return Array((["Atticus", "Chrome", "VS Code", "Peekaboo", "split screen", "study mode", user["name"] as? String ?? ""] + shortcuts.keys.sorted() +
        [NSHomeDirectory() + "/Applications", "/Applications", "/System/Applications", "/System/Applications/Utilities"].flatMap {
            ((try? FileManager.default.contentsOfDirectory(atPath: $0)) ?? []).filter { $0.hasSuffix(".app") }.map { String($0.dropLast(4)) }
        }).filter { !$0.isEmpty && seen.insert($0).inserted }.prefix(100))
    }
    func sound(_ name: String, _ v: Float) { let s = NSSound(named: name); s?.volume = v; s?.play() }
    func cue(_ k: String) { let n = Prefs.str(k); if n != "None" { sound(n, Float(Prefs.num("volume"))) } }   // soundStart / soundDone / soundStop
    var voice: Process?   // `say`: the Mac's system voice (a Siri voice if picked in Spoken Content); AVSpeechSynthesizer can't use Siri voices
    @discardableResult func shush() -> Bool {
        guard let v = voice else { return false }; voice = nil
        guard v.isRunning else { return false }; v.terminate(); return true
    }
    func deliver(_ a: String) {   // Settings: read answers aloud, copy them
        if Prefs.bool("autoCopy") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(a, forType: .string) }
        if Prefs.bool("speak") {
            shush(); let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/say"); p.arguments = ["--", a]
            p.terminationHandler = { [weak self] _ in DispatchQueue.main.async {
                guard let self, self.voice === p else { return }; self.voice = nil; self.hide(after: 2)
            } }
            try? p.run(); voice = p
        }
    }
    func linger(_ s: Double) -> Double { s * (["short": 0.5, "long": 2][Prefs.str("linger")] ?? 1) }

    override init() {
        let cfg = WKWebViewConfiguration()
        web = WKWebView(frame: NSRect(x: 0, y: 0, width: max(340, Prefs.num("boxW")), height: 76), configuration: cfg)
        super.init()
        cfg.userContentController.add(self, name: "h")
        cfg.userContentController.add(self, name: "c")
        web.setValue(false, forKey: "drawsBackground")
        web.autoresizingMask = [.width, .height]
        let bg = NSVisualEffectView(frame: web.frame)
        bg.material = .hudWindow; bg.state = .active; bg.wantsLayer = true; bg.autoresizingMask = [.width, .height]
        bg.appearance = NSAppearance(named: .darkAqua)   // stays dark over white pages, so the orb shows
        bg.layer?.cornerRadius = 18; bg.layer?.masksToBounds = true
        bg.maskImage = NSImage(size: NSSize(width: 37, height: 37), flipped: false) { NSColor.black.setFill(); NSBezierPath(roundedRect: $0, xRadius: 18, yRadius: 18).fill(); return true }
        bg.maskImage?.capInsets = NSEdgeInsets(top: 18, left: 18, bottom: 18, right: 18); bg.maskImage?.resizingMode = .stretch
        let tint = NSView(frame:web.frame); tint.wantsLayer = true; tint.autoresizingMask = [.width,.height]
        tint.layer?.backgroundColor = NSColor(calibratedRed:18/255,green:18/255,blue:20/255,alpha:0.5).cgColor
        bg.addSubview(tint); bg.addSubview(mini.clip)
        mini.publish = { [weak self] value in self?.js("mini",value) }
        mini.screen = { [weak self] in self?.panel.screen }
        bg.addSubview(web)
        let tracker = Tracker(frame: web.frame)
        tracker.autoresizingMask = [.width, .height]
        tracker.onMove = { [weak self] p in
            guard let self else { return }
            if !hovering { js("hover", true) }
            hovering = true
            if (overX(p) && edges(p) == nil) != xHot { xHot.toggle(); js("xhot", xHot); (xHot ? NSCursor.pointingHand : NSCursor.arrow).set() }
        }
        tracker.onExit = { [weak self] in
            guard let self else { return }
            hovering = false; js("hover", false)
            if xHot { xHot = false; js("xhot", false); NSCursor.arrow.set() }
            if !busy { hide(after: 3) }   // mouse gone for a few seconds = close
        }
        bg.addSubview(tracker)
        panel.acceptsMouseMovedEvents = true
        panel.contentView = bg
        panel.level = .statusBar; panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.sharingType = Prefs.bool("hideWhenSharing") ? .none : .readOnly   // Settings: others on a screen share don't see it
        let html = (try? String(contentsOfFile: dir + "/ui/ui.html", encoding: .utf8)) ?? "missing ui.html"
        let orbs = (try? String(contentsOfFile: dir + "/ui/orbs.js", encoding: .utf8)) ?? ""
        web.loadHTMLString(html.replacingOccurrences(of: "/*ORBS*/", with: orbs), baseURL: nil)
        // Click anywhere else closes the box once the answer is up; on the box: ✕ closes, elsewhere copies the answer.
        NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            guard let self, panel.isVisible, !busy, !engine.isRunning, !stuck else { return }
            close(clear: false)
        }
        var grab: (mouse: NSPoint, origin: NSPoint)?, moved = false
        var sizing: (mouse: NSPoint, frame: NSRect, e: (l: Bool, r: Bool, t: Bool, b: Bool))?   // dragging an edge or corner
        NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .leftMouseDragged, .leftMouseUp]) { [weak self] e in
            guard let self else { return e }
            switch e.type {
            case .leftMouseDown:
                guard e.window == panel else { return e }
                let p = e.locationInWindow
                if let ed = edges(p), !(overX(p) && !ed.r && !ed.t) { sizing = (NSEvent.mouseLocation, panel.frame, ed); fromTop = ed.t; pinned = true; dragging = true }
                else if overX(p) { close(clear: true) }
                else if p.y < compH { if !panel.isKeyWindow { selection = TextSelection.capture() }; pinned = true; panel.makeKey(); panel.makeFirstResponder(web); return e }   // the typing box: a normal click
                else { pinned = true; grab = (NSEvent.mouseLocation, panel.frame.origin); moved = false; dragging = true }
            case .leftMouseDragged:
                if let z = sizing {   // width from the side edges, height from the top/bottom; a corner does both
                    let m = NSEvent.mouseLocation, dx = m.x - z.mouse.x, dy = m.y - z.mouse.y
                    let w = min(900, max(340, z.frame.width + (z.e.r ? dx : z.e.l ? -dx : 0)))
                    var f = panel.frame; f.size.width = w; f.origin.x = z.e.l ? z.frame.maxX - w : z.frame.minX; frame(f)
                    Prefs.d["boxW"] = w
                    if z.e.t || z.e.b { js("hold", min(1000, max(120, z.frame.height + (z.e.b ? -dy : dy)))) }   // the page sets the height
                    return nil
                }
                guard let g = grab else { return e }
                let m = NSEvent.mouseLocation
                if abs(m.x - g.mouse.x) + abs(m.y - g.mouse.y) > 3 { moved = true; stuck = true }
                var f = panel.frame; f.origin = NSPoint(x: g.origin.x + m.x - g.mouse.x, y: g.origin.y + m.y - g.mouse.y); frame(f)
            default:
                dragging = false
                if sizing != nil { sizing = nil; DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in self?.fromTop = false }; Prefs.set("boxH", Prefs.num("boxH")); return nil }   // saves both
                guard grab != nil else { return e }
                grab = nil
                if !moved {   // a click, not a drag: the page decides (answer = copy, anywhere else = type)
                    panel.makeKey(); panel.makeFirstResponder(web)
                    js("tap", [e.locationInWindow.x, panel.frame.height - e.locationInWindow.y])
                }
            }
            return nil
        }
        NotificationCenter.default.addObserver(forName: NSWindow.didResignKeyNotification, object: panel, queue: .main) { [weak self] _ in
            guard let self else { return }
            composing = false   // the page may not get a blur; the box must still be able to fade
            if !hovering && !busy { hide(after: 3) }
        }
        // Focus guard: while a task runs (and 2 s after), an app that comes forward by itself (Spotify on play, open -a, a launch)
        // goes straight back behind the user's app. Not when the user asked to see it, switched apps themselves, or hands raise for a click.
        NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main) { [weak self] n in
            guard let self, let a = n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication, a != .current else { return }
            let now = Date()
            if busy || engine.isRunning || now < guardUntil, !focusFree, now > allowUntil, now.timeIntervalSince(userSwitch) > 0.6,
               let u = userApp, !u.isTerminated, u != a { MiniScreen.activate(u.processIdentifier); return }
            mine = a.localizedName ?? ""; userApp = a
        }
        NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown, .keyDown]) { [weak self] e in
            if e.type != .keyDown || e.modifierFlags.contains(.command) { self?.userSwitch = Date() }   // a click or ⌘-Tab: the user is choosing
        }
        DistributedNotificationCenter.default().addObserver(forName: .init("atticus.raise"), object: nil, queue: .main) { [weak self] _ in
            self?.allowUntil = Date().addingTimeInterval(3)   // hands raise an app for a mouse click, then put the user's app back
        }
        SFSpeechRecognizer.requestAuthorization { _ in }
        NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main) { [weak self] _ in
            guard let self else { return }; frame(panel.frame)
        }
        prepareSpeech()
        AVCaptureDevice.requestAccess(for: .audio) { _ in }
    }

    // The page reports its height; grow the box down from the top-left corner. "c": the typing box.
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        if m.name == "c", let b = m.body as? [String: Any] {
            if let value = b["miniRect"] as? [String:Any] { mini.layout(value) }
            // a click on the mini screen = the user wants to see it: the focus guard stands aside
            if b["miniOpen"] != nil { allowUntil = Date().addingTimeInterval(3); mini.open(); if !busy { mini.reset(); hide(after:3) } }
            if b["miniClear"] != nil { mini.reset() }
            if let h = b["comp"] as? NSNumber { compH = CGFloat(h.doubleValue) }
            if let h = b["boxH"] as? NSNumber { Prefs.d["boxH"] = h.doubleValue }   // saved when the drag ends
            if let f = b["focus"] as? Bool {
                composing = f
                if !f && !hovering && !busy { hide(after: 3) }
            }
            if b["type"] != nil { fresh = false; if engine.isRunning { if retryOffer { stopOfferInput() } else { hush() } } }   // typing wins; a pending failure card keeps its worker
            if let a = b["copy"] as? String, !a.isEmpty {
                NSPasteboard.general.clearContents(); NSPasteboard.general.setString(a, forType: .string); js("copied")
            }
            if b["replace"] != nil, !busy { applyReplacement() }
            if b["retry"] != nil, !busy, !engine.isRunning { typed(text, keep: true) }
            if let t = b["send"] as? String { typed(t, keep: true) }
            if b["mic"] != nil { fresh = false }
            if b["mic"] != nil && (!busy || retryOffer) && !engine.isRunning { clickTalk = true; start(); if !engine.isRunning { clickTalk = false } }
            if b["ready"] != nil { js("size", Prefs.num("boxH")) }
            if b["safe"] != nil { Prefs.set("safe", true); js("mode", true); Atticus.settings.push() }
            if let i = b["pick"] as? String, !askFile.isEmpty {
                if retryOffer {
                    stopOfferInput(); retryOffer = false
                }
                try? i.write(toFile: askFile, atomically: true, encoding: .utf8); askFile = ""
            }   // an index, or "" = none; failure cards also use r/y/n
            if let k = b["off"] as? String, ["escalate", "tips"].contains(k) { Prefs.set(k, false); Atticus.settings.push() }   // a card's own "Turn off"; never safe mode
            if let v = b["improve"] as? Bool { Atticus.settings.apply("improve", v); Atticus.settings.push() }
            if let ok = b["allow"] as? Bool, !askFile.isEmpty { try? (ok ? "y" : "n").write(toFile: askFile, atomically: true, encoding: .utf8); askFile = "" }
            return
        }
        guard let h = (m.body as? NSNumber).map({ CGFloat($0.doubleValue) }), h > 0 else { return }
        var f = panel.frame
        if !fromTop { f.origin.y = f.maxY - h }   // grows down from the top, unless the user is dragging the top edge
        f.size.height = h
        guard f != panel.frame else { return }
        frame(f)
    }

    func js(_ call: String, _ arg: Any? = nil) {
        var a = ""
        if let arg, let d = try? JSONSerialization.data(withJSONObject: [arg]), let s = String(data: d, encoding: .utf8) {
            a = "..." + s
        }
        web.evaluateJavaScript("ui.\(call)(\(a))")
    }

    func show() {
        gen += 1; js("visible", true); js("mode", Prefs.bool("safe"))
        if panel.isVisible {   // still up: stay where the user dragged it
            NSAnimationContext.runAnimationGroup { $0.duration = 0.18; panel.animator().alphaValue = 1 }
            return
        }
        let vf = (NSScreen.main ?? NSScreen.screens[0]).visibleFrame
        let x = Prefs.str("corner") == "top-right" ? vf.maxX - panel.frame.width - 14 : vf.minX + 14
        panel.setFrameOrigin(NSPoint(x: x, y: vf.maxY - panel.frame.height - 10))
        frame(panel.frame)
        panel.alphaValue = 0
        panel.orderFrontRegardless()
        if escRef == nil {
            RegisterEventHotKey(UInt32(kVK_Escape), 0, EventHotKeyID(signature: 0x41545443, id: 2), GetApplicationEventTarget(), 0, &escRef)
        }
        NSAnimationContext.runAnimationGroup { $0.duration = 0.18; panel.animator().alphaValue = 1 }
    }

    func hide(after s: Double) {
        let g = gen
        DispatchQueue.main.asyncAfter(deadline: .now() + s) { [self] in
            guard g == gen, !busy, !engine.isRunning, !hovering, !pinned, !composing, !mini.holds, voice?.isRunning != true else { return }
            NSAnimationContext.runAnimationGroup({ $0.duration = 0.3; panel.animator().alphaValue = 0 },
                                                 completionHandler: { [self] in if g == gen { gone() } })
        }
    }

    func gone() {
        mini.reset()
        panel.orderOut(nil); fresh = false; pinned = false; stuck = false; composing = false; js("compose", false); js("visible", false)
        if let r = escRef { UnregisterEventHotKey(r); escRef = nil }
    }

    // Esc: stop listening, stop the answer, or close the box.
    func escape() {
        if shush() { return }
        if engine.isRunning {
            hush(); cue("soundStop"); js("stopped", "Stopped listening"); hide(after: 1.5)
        } else if busy {
            cancel()
        } else if panel.isVisible {
            close(clear: false)
        }
    }

    func hush() {   // stop listening, drop what was heard, say nothing
        mini.reset()
        engine.stop(); engine.inputNode.removeTap(onBus: 0); feed?.finish(); reading?.cancel(); pause?.cancel(); unwarm()
        clickTalk = false; toggleTalk = false; quiet?.cancel(); stops += 1   // stops: a late "words landed" from this listen does nothing
        listenID += 1; selectionID += 1; selectionPending = false; replacing = false
        cancelFast()
        aheadItem?.cancel(); dropAhead()
        proc?.terminate(); proc = nil; askFile = ""; replacement = nil; retryOffer = false
        if let old = offerText { text = old }; offerText = nil
        let an = analyzer; Task { await an?.cancelAndFinishNow() }
        busy = false   // an early start dropped above never reports back (its exit handler sees proc changed)
    }

    func stopOfferInput() {
        if engine.isRunning { engine.stop() }; engine.inputNode.removeTap(onBus: 0)
        feed?.finish(); reading?.cancel(); quiet?.cancel(); clickTalk = false; toggleTalk = false; listenID += 1; stops += 1
        if let old = offerText { text = old }; offerText = nil
        let an = analyzer; Task { await an?.cancelAndFinishNow() }
    }

    func dismiss() {   // the shortcut again before anything happened: say so, then go
        if engine.isRunning { hush() }
        cue("soundStop"); js("stopped", "Answer stopped")
        let g = gen; DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [self] in if g == gen { close(clear: false) } }
    }

    func cancel() {
        hush(); shush()
        cue("soundStop"); js("stopped", "Answer stopped"); hide(after: 1.5)
    }

    // ✕ also ends the conversation; clicking away or timing out keeps it for 5 minutes.
    func close(clear: Bool) {
        shush(); hush()   // gone means quiet: no mic, no voice, no answer on the way
        if clear { try? FileManager.default.removeItem(atPath: recent); lastDone = .distantPast }
        gen += 1
        let g = gen
        NSAnimationContext.runAnimationGroup({ $0.duration = 0.2; panel.animator().alphaValue = 0 },
                                             completionHandler: { [self] in if g == gen { gone() } })
    }

    func shortcut(_ pressed: Bool) {
        if meeting.running { if pressed { meeting.focus() }; return }
        if !pressed {
            shortcutDown = false
            if engine.isRunning && !toggleTalk && !clickTalk { stop() }
            return
        }
        guard !shortcutDown else { return }   // one action per physical press, including key repeat
        shortcutDown = true
        guard !Prefs.bool("paused") else { return }
        if shush() { return }
        if engine.isRunning { return toggleTalk ? stop() : dismiss() }
        if busy && !retryOffer { return cancel() }
        start()
    }

    func review(_ message: String) {
        hush(); js("msg", message)
        pinned = true; panel.makeKey(); panel.makeFirstResponder(web); js("draft", text)
    }

    func recordingLimit() {
        if let old = offerText { let partial = text; stopOfferInput(); text = old; js("draft", partial); return }
        if toggleTalk { review("Recording paused after 60 seconds. Review your words and press Return to send.") }
        else { stop() }
    }

    func captureSelection() {
        selectionID += 1; let id = selectionID
        selection = nil; selectionPending = Prefs.bool("selection")
        guard selectionPending else { return }
        let front = NSWorkspace.shared.frontmostApplication
        DispatchQueue.global().async { [weak self] in
            let selected = TextSelection.capture(front, enabled: true)
            DispatchQueue.main.async { [weak self] in
                guard let self, self.selectionID == id else { return }
                self.selectionPending = false; self.selection = Prefs.bool("selection") ? selected : nil
                if let selection = self.selection { self.js("selected", selection.text) }
                if self.warm != nil && self.warmSel != self.selKey { self.unwarm(); self.warm = self.spawn() }
            }
        }
    }

    var selKey: String { Prefs.bool("selection") ? selection.map { $0.caret ? "\u{1}" : $0.text } ?? "" : "" }   // \u{1}: no highlight, the cursor sits in a text box

    func start() {
        let replying = retryOffer && !askFile.isEmpty
        if !replying { mini.reset(); try? FileManager.default.removeItem(atPath: focusFile) }   // a new ask: "show it" from the last one no longer counts
        guard !Prefs.bool("paused") else { return }
        shush()
        if engine.isRunning { return dismiss() }   // the shortcut stops click-to-talk
        if busy && !replying {   // pressed again while it works = cancel
            return cancel()
        }
        if fresh && panel.isVisible { return dismiss() }
        cancelFast()
        if replying { offerText = text } else { captureSelection(); replacement = nil }
        targetScreen = currentRequestScreen()
        text = ""; ahead = ""; speechFailed = false; consumed = 0; consumedText = ""; liveRevised = false; did = []
        if !panel.isVisible && Date().timeIntervalSince(lastDone) > 30 { js("reset"); try? FileManager.default.removeItem(atPath: recent) }
        if !replying && Prefs.str("input") == "type" && !clickTalk {   // Settings: the shortcut opens the box ready to type
            if composing && panel.isVisible { return dismiss() }   // pressed again = put it away
            onboarding.tried(); show()
            panel.makeKey(); panel.makeFirstResponder(web); js("compose", true)
            return
        }
        toggleTalk = !clickTalk && Prefs.str("talkMode") == "toggle"
        cue("soundStart")
        if !replying { unwarm(); warm = spawn() }
        onboarding.tried()
        hovering = false
        if replying { js("draft", "") } else { js("listen"); if let s = selection { js("selected", s.text) } }
        js("shortcut", toggleTalk ? "Press again to send" : clickTalk ? "" : "Release keys to send")
        show()
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            if replying { stopOfferInput() } else { hush() }; js("msg", "Allow Atticus in System Settings → Privacy & Security → Microphone."); hide(after: 6); return
        }
        listenID += 1; let listeningID = listenID
        let tr = speechModule()
        let (stream, cont) = AsyncStream<AnalyzerInput>.makeStream()
        let an = SpeechAnalyzer(modules: [tr])
        feed = cont; analyzer = an
        let ctx = AnalysisContext(); ctx.contextualStrings[.general] = hints
        Task { try? await an.setContext(ctx); try? await an.start(inputSequence: stream) }
        reading = Task { [weak self] in   // finished pieces add up; the live (volatile) piece is shown after them
            var done = ""
            func got(_ piece: String, _ final: Bool) async {
                if final { done += piece }
                let now = final ? done : done + piece
                await MainActor.run { if self?.listenID == listeningID { self?.heard(now) } }
            }
            do {
                if let d = tr as? DictationTranscriber { for try await r in d.results { await got(String(r.text.characters), r.isFinal) } }
                else if let t = tr as? SpeechTranscriber { for try await r in t.results { await got(String(r.text.characters), r.isFinal) } }
            } catch { await MainActor.run { if self?.listenID == listeningID { self?.speechFailed = true } } }
        }
        let input = engine.inputNode, natural = input.outputFormat(forBus: 0)
        guard natural.sampleRate > 0, natural.channelCount > 0 else {
            if replying { stopOfferInput() } else { hush() }; js("msg", "No microphone is available. Connect one and try again."); hide(after: 6); return
        }
        let want = speechFormat ?? natural
        let conv = want == natural ? nil : AVAudioConverter(from: natural, to: want)
        input.removeTap(onBus: 0)
        var n = 0
        input.installTap(onBus: 0, bufferSize: 1024, format: natural) { [weak self] buf, _ in
            if let conv, let out = AVAudioPCMBuffer(pcmFormat: want, frameCapacity: AVAudioFrameCount(Double(buf.frameLength) * want.sampleRate / natural.sampleRate) + 1) {
                var given = false
                conv.convert(to: out, error: nil) { _, status in
                    if given { status.pointee = .noDataNow; return nil }
                    given = true; status.pointee = .haveData; return buf
                }
                cont.yield(AnalyzerInput(buffer: out))
            } else {
                cont.yield(AnalyzerInput(buffer: buf))
            }
            n += 1
            guard n % 2 == 0, let ch = buf.floatChannelData?[0], buf.frameLength > 0 else { return }
            var sum: Float = 0
            for i in 0..<Int(buf.frameLength) { sum += ch[i] * ch[i] }
            let v = Double(min(1, sqrt(sum / Float(buf.frameLength)) * 14))
            DispatchQueue.main.async { if self?.listenID == listeningID { self?.js("level", v) } }
        }
        engine.prepare()
        do { try engine.start() } catch { if replying { stopOfferInput() } else { hush() }; js("msg", "Mic error: \(error.localizedDescription)"); hide(after: 3); return }
        began = Date()   // measure the limit from when the mic is ready
        Timer.scheduledTimer(withTimeInterval: 0.15, repeats: true) { [weak self] t in
            guard let self, engine.isRunning else { return t.invalidate() }
            let f = hotkey().flags, held = Date().timeIntervalSince(began)
            if clickTalk && text.isEmpty && held > 8 { t.invalidate(); if offerText != nil { stopOfferInput(); return }; hush(); js("stopped", ""); return hide(after: 3) }   // nothing said: stop the mic quietly
            if held > 60 { t.invalidate(); recordingLimit(); return }
            if !toggleTalk && !clickTalk && !f.isEmpty && !NSEvent.modifierFlags.isSuperset(of: f) { t.invalidate(); stop() }
        }
    }

    func heard(_ now: String) {
        guard engine.isRunning || busy else { return }
        text = now; if !now.trimmingCharacters(in: .whitespaces).isEmpty { fresh = false }
        if offerText != nil {
            js("draft", now)
            if clickTalk { quiet?.cancel(); let q = DispatchWorkItem { [weak self] in self?.stop() }; quiet = q; DispatchQueue.main.asyncAfter(deadline: .now() + 1.3, execute: q) }
            return   // card replies never enter live commands or early AI thinking
        }
        js("words", text)
        if consumed > 0 && transcriptKey(words().prefix(consumed).joined(separator: " ")) != consumedText { liveRevised = true }
        if Prefs.bool("live") {   // instant commands (open, move, search, play) run mid-sentence; the AI still waits for confirmed words
            pause?.cancel()   // only after a pause: "search amazon" mid-word is the start of "search amazon for e-bikes"
            let item = DispatchWorkItem { [weak self] in self?.tryFast() }
            pause = item
            DispatchQueue.main.asyncAfter(deadline: .now() + Prefs.num("aheadDelay"), execute: item)
        }
        if clickTalk {   // no keys to let go of: a 1.3 s pause ends it
            quiet?.cancel(); let q = DispatchWorkItem { [weak self] in self?.stop() }; quiet = q
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.3, execute: q)
        }
        if !ahead.isEmpty && transcriptKey(rest()) != transcriptKey(ahead) { dropAhead() }   // the user kept talking: that start was for half a sentence
        aheadItem?.cancel()   // a longer pause = the user is probably done: start the AI now, keys still held
        guard Prefs.bool("ahead") else { return }
        let go = DispatchWorkItem { [weak self] in self?.startAhead() }
        aheadItem = go
        DispatchQueue.main.asyncAfter(deadline: .now() + Prefs.num("aheadDelay"), execute: go)
    }

    func words() -> [Substring] { text.split(separator: " ") }
    func rest() -> String { let w = words(); return w.count > consumed ? w[consumed...].joined(separator: " ") : "" }

    func startAhead() {
        if engine.isRunning && selectionPending {
            let item = DispatchWorkItem { [weak self] in self?.startAhead() }; aheadItem = item
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05, execute: item); return
        }
        let r = rest()
        guard engine.isRunning, !selectionPending, !fastBusy, !liveRevised, !r.isEmpty, transcriptKey(r) != transcriptKey(ahead) else { return }
        let core = r.lowercased().replacingOccurrences(of: #"^(?:(?:hey|ok|okay|atticus|please|can you|could you|would you|also|and|now|then)[,\s]+)+"#, with: "", options: .regularExpression)
        if ["open", "launch", "start", "pull up", "bring up", "focus", "switch to", "go to", "snap", "move", "put", "throw", "send", "make", "play", "search", "google", "look up"].contains(where: { core.hasPrefix($0 + " ") }) || hints.contains(where: { transcriptKey($0) == transcriptKey(r) }) { return }
        dropAhead()
        ahead = r
        run(r, speculative: true)
        warm = spawn()   // ready again in case the user keeps talking
    }

    // Runs `atticus.py --fast` on the words not yet used; exit 0 means it was a simple command and it is done.
    func cancelFast() { fastProc?.terminate(); fastProc = nil; fastBusy = false }

    func tryFast() {
        let w = words()
        guard Prefs.bool("live"), Prefs.bool("instant"), engine.isRunning, !fastBusy, !liveRevised, w.count > consumed else { return }
        let seg = w[consumed...].joined(separator: " "), n = w.count, prefix = transcriptKey(w.joined(separator: " "))
        let p = py(["--fast", seg], ["ATTICUS_FRONT": mine, "ATTICUS_SCREEN": targetScreen, "ATTICUS_LIVE": "1", "ATTICUS_FOCUS_GUARD": "1"]), out = Pipe()
        p.standardOutput = out
        do { try p.run() } catch { return }
        fastProc = p
        fastBusy = true
        DispatchQueue.global().async { [weak self] in
            let line = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            p.waitUntilExit()
            DispatchQueue.main.async { [weak self] in
                guard let self, fastProc === p else { return }
                fastProc = nil; fastBusy = false
                if p.terminationStatus == 0 && line.hasPrefix("✓") {
                    consumed = n; consumedText = prefix
                    if transcriptKey(words().prefix(n).joined(separator: " ")) != prefix { liveRevised = true }
                    did.append(String(line.dropFirst(2)))
                    js("line", "▸ " + line.dropFirst(2))
                }
            }
        }
    }

    func dropAhead() {
        if !ahead.isEmpty { proc?.terminate(); proc = nil; ahead = ""; if engine.isRunning { busy = false } }
    }

    func stop() {
        guard engine.isRunning, !clickTalk || text.isEmpty == false else { return }
        engine.stop(); engine.inputNode.removeTap(onBus: 0); feed?.finish()
        clickTalk = false; toggleTalk = false; quiet?.cancel()
        busy = true
        if offerText == nil { js("think") }   // card replies keep the response clock paused
        let an = analyzer, rd = reading
        stops += 1
        let g = stops
        let once: (Bool) -> Void = { [weak self] confirmed in
            guard let self, g == stops else { return }
            stops += 1; listenID += 1; pause?.cancel()
            if confirmed { finish() }
            else {
                if let old = offerText { let partial = text; text = old; offerText = nil; js("draft", partial); return }
                review("Couldn’t confirm your words. Check them and press Return.")
            }
        }
        Task {   // let the model finish the last words, then act
            guard let an else { return await MainActor.run { once(false) } }
            do {
                try await an.finalizeAndFinishThroughEndOfInput()
                await rd?.value
                await MainActor.run { once(!speechFailed) }
            } catch { await MainActor.run { once(false) } }
        }
        // Finalizing can hang: offer the partial transcript for review instead of executing it.
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            guard let self, g == stops else { return }
            rd?.cancel(); Task { await an?.cancelAndFinishNow() }
            once(false)
        }
    }

    // Replace / Delete / Insert: the text goes to the saved selection, or for a draft to the saved cursor.
    func applyReplacement() {
        guard let draft = replacement, !replacing else { return }
        guard Prefs.bool("selection"), let selection, mode != "draft" || selection.caret else { js("replaced", false); return }
        replacing = true; let id = selectionID
        selection.apply(mode == "delete" ? "" : draft, valid: { [weak self] in
            self?.selectionID == id && self?.replacing == true && Prefs.bool("selection") && !Prefs.bool("paused")
        }) { [weak self] ok in
            guard let self, selectionID == id else { return }
            replacing = false
            if ok { replacement = nil; self.selection = nil }
            js("replaced", ok)
        }
    }

    func typed(_ t: String, keep: Bool = false) {   // the typing box (keep: it stays open for the next one)
        if retryOffer && !askFile.isEmpty { js("respond", t); return }
        guard !busy, !engine.isRunning else { return }
        if ["report feedback", "report a bug"].contains(transcriptKey(t)) { Atticus.settings.open(tab:"feedback"); return }
        if selectionPending {
            let id = selectionID
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { [weak self] in
                if self?.selectionID == id { self?.typed(t, keep: keep) }
            }
            return
        }
        if !panel.isKeyWindow { selection = TextSelection.capture() }
        if !Prefs.bool("selection") { selection = nil }
        if !panel.isKeyWindow || targetScreen.isEmpty { targetScreen = currentRequestScreen() }
        text = t; replacement = nil
        fresh = false; js("listen", keep); if let s = selection { js("selected", s.text) }; show(); js("words", t); run(t)
    }

    func finish() {
        guard busy else { return }   // cancelled while the last words landed
        if let old = offerText { let response = text; text = old; offerText = nil; js("respond", response); return }
        if fastBusy || selectionPending {
            let g = stops
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [self] in if g == stops { finish() } }; return
        }
        aheadItem?.cancel()
        if liveRevised {
            hush(); js("msg", "Words changed after an instant command. Review before sending another request.")
            pinned = true; panel.makeKey(); panel.makeFirstResponder(web); js("draft", text); return
        }
        let rest = rest()
        if did.isEmpty, !rest.isEmpty && transcriptKey(rest) == transcriptKey(ahead), proc?.isRunning == true {   // already started on exactly this while the user talked
            ahead = ""; unwarm()
            do { try "go".write(toFile: commit, atomically: true, encoding: .utf8) }
            catch { cancel(); js("msg", "Could not confirm the request. Please try again.") }
            return
        }
        dropAhead()
        // the rest keeps the whole sentence: "for e-bikes, open the cheapest" alone lost "on Amazon"
        if !rest.isEmpty { return run(did.isEmpty ? rest : text, remaining: did.isEmpty ? nil : rest) }
        busy = false; unwarm()   // nothing left for the AI
        if did.isEmpty { js("msg", "Didn't catch that."); return hide(after: 1.2) }
        answer = "✓ " + did.joined(separator: " ")
        deliver(did.joined(separator: " "))
        js("line", answer); lastDone = Date(); cue("soundDone"); hide(after: linger(5))
    }

    // atticus.py --wait, started at key-down so Claude is up by the time the user lets go; run() hands it the words.
    func spawn() -> (p: Process, input: FileHandle, commit: String)? {
        let commit = NSTemporaryDirectory() + "atticus-commit-" + UUID().uuidString
        warmSel = selKey
        let p = py(["--wait"], ["ATTICUS_UI": "1", "ATTICUS_FRONT": mine, "ATTICUS_SCREEN": targetScreen, "ATTICUS_COMMIT": commit, "ATTICUS_SELECTION": warmSel == "\u{1}" ? "" : warmSel, "ATTICUS_CARET": warmSel == "\u{1}" ? "1" : "", "ATTICUS_FOCUS_GUARD": "1"])
        let pipe = Pipe(), inp = Pipe(); p.standardOutput = pipe; p.standardInput = inp
        fcntl(inp.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)   // a worker can exit before we write; let the catch handle EPIPE
        var buffer = Data()
        let feed = { [weak self] (d: Data) in
            DispatchQueue.main.async {
                guard let self, self.proc === p else { return }   // buffered output from a cancelled request stays cancelled
                buffer += d
                while let i = buffer.firstIndex(of: 10) {
                    let line = String(decoding: buffer[..<i], as: UTF8.self); buffer.removeSubrange(...i)
                    if line == "! setup" { onboarding.open(); continue }   // Claude not installed, signed out or no plan
                    if line == "! feedback" { Atticus.settings.open(tab:"feedback"); continue }
                    if line == "! improve" { self.js("improve"); continue }   // the one-time "help make Atticus better?" card
                    if line.hasPrefix("▣ "), let value = try? JSONSerialization.jsonObject(with:Data(line.dropFirst(2).utf8)) as? [String:Any] { if Prefs.d["miniScreen"] as? Bool ?? true { self.mini.receive(value) }; continue }
                    if line.hasPrefix("@ ") { if self.mini.target != nil { self.js("line",line) } else { pointAt(line) }; continue }   // experimental "show me where"
                    if line.hasPrefix("? ") {   // safe mode: "? <question>\t<command>\t<answer file>"
                        let p = line.dropFirst(2).components(separatedBy: "\t")
                        guard (3...5).contains(p.count) else { continue }
                        self.retryOffer = p.count == 5 && p[4] == "retry"
                        self.askFile = p[2]; self.show(); self.js("ask", [p[0], p[1], p.count >= 4 ? p[3] : "", self.retryOffer ? "retry" : ""]); continue
                    }
                    if line.hasPrefix("⚙ ") {   // "⚙ <key> <true|false>": the AI flips one of Atticus's switches; never pause, and Safe mode only on
                        let p = line.split(separator: " ").map(String.init)
                        if p.count == 3, Prefs.defaults[p[1]] is Bool, p[1] != "paused", p[1] != "safe" || p[2] == "true" { Atticus.settings.apply(p[1], p[2] == "true"); Atticus.settings.push() }
                        else if p.count == 3, Prefs.defaults[p[1]] is String, !p[1].hasPrefix("hotkey") { Atticus.settings.apply(p[1], p[2]); Atticus.settings.push() }   // a choice setting ("workIn front")
                        continue
                    }
                    if line.hasPrefix("◇ "), let j = try? JSONSerialization.jsonObject(with: Data(line.dropFirst(2).utf8)) as? [String: Any] {   // "which one?": the choices card
                        self.askFile = j["a"] as? String ?? ""; self.show(); self.js("pick", j); continue
                    }
                    if line.hasPrefix("↺ ") {
                        guard let j = try? JSONSerialization.jsonObject(with: Data(line.dropFirst(2).utf8)) as? [String: Any], let draft = j["t"] as? String else { continue }
                        let now = j["mode"] as? String == "insert"   // the user asked to put it in: no Insert click needed
                        self.replacement = draft; self.mode = now ? "draft" : j["mode"] as? String ?? "replace"; self.pinned = true
                        let target = self.selection.map { ($0.editable || $0.pastable) && (self.mode != "draft" || $0.caret) } ?? false
                        self.js("rewrite", [draft, self.mode, target])
                        if self.mode == "draft" && target && (now || Prefs.str("draftInsert") == "auto") { self.applyReplacement() }
                        continue
                    }
                    if line.hasPrefix("✓") {
                        let result = self.replacement.flatMap { $0.isEmpty ? nil : $0 } ?? String(line.dropFirst(2))
                        self.mini.finish(); self.answer = "✓ " + result; self.deliver(result)
                        self.js("line", self.answer); continue
                    }
                    if line.hasPrefix("! ") { self.js("msg", String(line.dropFirst(2))) }
                    else { self.js("line", line) }
                }
            }
        }
        pipe.fileHandleForReading.readabilityHandler = { feed($0.availableData) }
        p.terminationHandler = { [weak self] _ in
            pipe.fileHandleForReading.readabilityHandler = nil
            feed(pipe.fileHandleForReading.readDataToEndOfFile())   // the answer may still be in the pipe
            DispatchQueue.main.async {
                try? FileManager.default.removeItem(atPath: commit)
                guard let self, self.proc === p else { return }   // a cancelled run ending late must not touch the next one
                if !self.ahead.isEmpty { self.proc = nil; self.ahead = ""; self.busy = !self.engine.isRunning; return }
                self.busy = false; self.guardUntil = Date().addingTimeInterval(2); self.proc = nil; self.mini.finish(); self.js("finished")   // Spotify jumps ~0.5 s after play returns
                if !self.answer.isEmpty { self.lastDone = Date(); self.cue("soundDone") }
                Apps.q.async { Apps.sync() }
                self.hide(after: self.linger(max(6, min(30, Double(self.answer.count) / 12))))   // longer answers stay longer
            }
        }
        do { try p.run() } catch { return nil }
        return (p, inp.fileHandleForWriting, commit)
    }

    func unwarm() { warm?.p.terminate(); warm = nil }

    func run(_ t: String, speculative: Bool = false, remaining: String? = nil) {
        mini.reset(); busy = true; answer = ""; try? FileManager.default.removeItem(atPath: focusFile)
        if !speculative { js("think") }
        if let w = warm, !w.p.isRunning { try? w.input.close(); warm = nil }
        if warm != nil && warmSel != selKey { unwarm() }   // spawned before the selection changed
        guard let w = warm ?? spawn() else { busy = false; js("msg", "Could not start atticus.py"); return hide(after: 3) }
        warm = nil; proc = w.p; commit = w.commit
        if !speculative {
            do { try "go".write(toFile: commit, atomically: true, encoding: .utf8) }
            catch { cancel(); js("msg", "Could not confirm the request. Please try again."); return }
        }
        do {
            var request: [String:Any] = ["front":mine, "task":t]
            if let remaining { request["remaining"] = remaining; request["done"] = did }
            var data = try JSONSerialization.data(withJSONObject:request); data.append(10)
            try w.input.write(contentsOf:data); try w.input.close()
        } catch { cancel(); js("msg", "The request worker stopped. Please try again.") }
    }
}

// First-run window (ui/onboarding.html): welcome, then each macOS permission with an Allow button, then how to use it.
// Shows until finished once; to see it again: defaults delete com.atticus.app onboarded, then restart the app.
final class Onboarding: NSObject, WKScriptMessageHandler, NSWindowDelegate {
    var win: NSWindow?, web: WKWebView?, timer: Timer?
    let pane = "x-apple.systempreferences:com.apple.preference.security?Privacy_"

    func open() {
        guard win == nil else { win?.makeKeyAndOrderFront(nil); return }
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 640, height: 640),
                         styleMask: [.titled, .closable, .fullSizeContentView], backing: .buffered, defer: false)
        w.titlebarAppearsTransparent = true; w.titleVisibility = .hidden; w.isMovableByWindowBackground = true
        w.isReleasedWhenClosed = false; w.delegate = self
        let bg = NSVisualEffectView(frame: w.contentRect(forFrameRect: w.frame))
        bg.material = .underWindowBackground; bg.blendingMode = .behindWindow; bg.state = .active
        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(self, name: "ob")
        let v = WKWebView(frame: NSRect(x: 0, y: 0, width: 640, height: 612), configuration: cfg)   // top 28 pt stays draggable
        v.setValue(false, forKey: "drawsBackground")
        let html = (try? String(contentsOfFile: dir + "/ui/onboarding.html", encoding: .utf8)) ?? "missing onboarding.html"
        let orbs = (try? String(contentsOfFile: dir + "/ui/orbs.js", encoding: .utf8)) ?? ""
        v.loadHTMLString(html.replacingOccurrences(of: "/*ORBS*/", with: orbs), baseURL: nil)
        bg.addSubview(v); w.contentView = bg
        win = w; web = v
        w.center(); NSApp.activate(ignoringOtherApps: true); w.makeKeyAndOrderFront(nil)
        var tick = 0
        timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in   // keys 20×/s, permissions 1×/s
            guard let self else { return }
            let f = NSEvent.modifierFlags
            web?.evaluateJavaScript("ob.keys(\(f.contains(.control)), \(f.contains(.option)))")
            tick += 1
            if tick % 20 == 1 { push() }
            if tick % 100 == 1 { checkPlan() }   // every 5 s: it starts Claude Code, too slow for every second
        }
    }

    // Which permissions are on, sent to the page every second (System Settings changes them behind our back).
    func push() {
        DispatchQueue.global().async { [weak self] in
            let s = Onboarding.perms()
            DispatchQueue.main.async {
                guard let d = try? JSONSerialization.data(withJSONObject: s), let j = String(data: d, encoding: .utf8) else { return }
                self?.web?.evaluateJavaScript("ob.set(\(j))")
                self?.web?.evaluateJavaScript("ob.mode(\(Prefs.str("talkMode") == "toggle"))")
                self?.web?.evaluateJavaScript("ob.prefs({meeting: \(Prefs.bool("meeting")), pointer: \(Prefs.bool("pointer"))})")
            }
        }
    }

    static func perms() -> [String: Bool] {
        ["mic": AVCaptureDevice.authorizationStatus(for: .audio) == .authorized, "speech": SFSpeechRecognizer.authorizationStatus() == .authorized,
         "ax": AXIsProcessTrusted(), "screen": CGPreflightScreenCaptureAccess(), "auto": Apps.statuses(["com.apple.systemevents"])["com.apple.systemevents"] == "allowed",
         "chrome": Prefs.bool("pageJS") || NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.google.Chrome") == nil]   // no Chrome: nothing to turn on   // a live check fails while System Events is quit, so fall back to what was granted
    }

    // Claude Code installed, signed in, on a paid plan? (atticus.py --check)
    static func plan(_ done: @escaping ([String: Any]) -> Void) {
        DispatchQueue.global().async {
            let p = py(["--check"]), out = Pipe(); p.standardOutput = out
            try? p.run(); p.waitUntilExit()
            let j = (try? JSONSerialization.jsonObject(with: out.fileHandleForReading.readDataToEndOfFile())) as? [String: Any]
            DispatchQueue.main.async { done(j ?? ["ok": false, "need": "install", "text": "Could not run Atticus’s helper (python3 missing?)."]) }
        }
    }

    func checkPlan() {
        Onboarding.plan { [weak self] c in
            guard let d = try? JSONSerialization.data(withJSONObject: c), let j = String(data: d, encoding: .utf8) else { return }
            self?.web?.evaluateJavaScript("ob.plan(\(j))")
        }
    }

    // The plan row's button: install the AI client, sign in, or upgrade, in a Terminal window the user can watch.
    func fixPlan() {
        Onboarding.plan { [weak self] c in
            let need = c["need"] as? String ?? ""
            let devin = (c["client"] as? String) == "devin"
            if need == "upgrade" { NSWorkspace.shared.open(URL(string: "https://claude.ai/upgrade")!); return }
            let cmd = need == "install"
                ? devin ? "curl -fsSL https://cli.devin.ai/install.sh | bash && devin auth login"
                        : "curl -fsSL https://claude.ai/install.sh | bash && ~/.local/bin/claude auth login"
                : devin ? "devin auth login" : "claude auth login"
            let f = NSTemporaryDirectory() + (devin ? "atticus-devin.command" : "atticus-claude.command")
            try? "#!/bin/zsh\nexport PATH=\"$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH\"\necho 'Atticus: setting up \(devin ? "Devin" : "Claude Code")'\n\(cmd)\necho; echo 'Done. You can close this window.'\n".write(toFile: f, atomically: true, encoding: .utf8)
            chmod(f, 0o755)
            NSWorkspace.shared.open(URL(fileURLWithPath: f))
            self?.checkPlan()
        }
    }

    func tried() { web?.evaluateJavaScript("ob.tried()") }

    func settings(_ p: String) { NSWorkspace.shared.open(URL(string: pane + p)!) }

    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        guard let b = m.body as? [String: String] else { return }
        if b["do"] == "done" { return finish() }
        if b["do"] == "set", let k = b["k"], ["meeting", "pointer", "improve"].contains(k) { Atticus.settings.apply(k, b["v"] == "true"); Atticus.settings.push(); return }   // the extras switches
        grant(b["id"] ?? "")
    }

    // A permission's Allow button, from setup or Settings. One click shows one thing: macOS's own box the first time
    // (its button lands on the right list), System Settings once macOS won't ask again. Both at once confused people.
    func grant(_ id: String) {
        switch id {
        case "mic":
            if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined { AVCaptureDevice.requestAccess(for: .audio) { _ in } }
            else { settings("Microphone") }
        case "speech":
            if SFSpeechRecognizer.authorizationStatus() == .notDetermined { SFSpeechRecognizer.requestAuthorization { _ in } }
            else { settings("SpeechRecognition") }
        case "ax":
            if UserDefaults.standard.bool(forKey: "askedAX") { if !AXIsProcessTrusted() { settings("Accessibility") } }
            else { UserDefaults.standard.set(true, forKey: "askedAX"); _ = AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue(): true] as CFDictionary) }
        case "claude":
            fixPlan()
        case "screen":
            // First click: only macOS's own prompt (its button lands on the right list). Opening Settings at the
            // same time put people in the wrong section; later clicks, when macOS won't prompt again, open Settings.
            if UserDefaults.standard.bool(forKey: "askedScreen") { if !CGPreflightScreenCaptureAccess() { settings("ScreenCapture") } }
            else { UserDefaults.standard.set(true, forKey: "askedScreen"); _ = CGRequestScreenCaptureAccess() }
        case "auto":
            Atticus.settings.open(tab: "apps")
        case "chrome":   // clicks Chrome's View > Developer > Allow JavaScript from Apple Events; Atticus keeps it on after this OK
            DispatchQueue.global().async {
                let p = py(["--allow-js"]); try? p.run(); p.waitUntilExit()
                if p.terminationStatus == 0 { DispatchQueue.main.async { Prefs.set("pageJS", true) } }
            }
        default: break
        }
    }

    // Screen Recording only takes effect after a relaunch; launchd (KeepAlive) starts us again right away.
    func finish() {
        UserDefaults.standard.set(true, forKey: "onboarded")
        let relaunch = !CGPreflightScreenCaptureAccess()
        win?.close()
        if relaunch { relaunchSoon() }
    }

    func windowWillClose(_ n: Notification) {
        timer?.invalidate(); timer = nil
        web?.configuration.userContentController.removeScriptMessageHandler(forName: "ob")
        web = nil; win = nil
    }
}

// `Atticus --look <screen #> <out.jpg>` (atticus.py --look): the screen without Atticus's own box on it, 1280 px wide.
if CommandLine.arguments.count == 4, CommandLine.arguments[1] == "--look" {
    let a = CommandLine.arguments, done = DispatchSemaphore(value: 0)
    let scr = NSScreen.screens[max(0, min((Int(a[2]) ?? 1) - 1, NSScreen.screens.count - 1))]
    let id = scr.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? CGMainDisplayID()
    Task {
        defer { done.signal() }
        guard let all = try? await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true),
              let d = all.displays.first(where: { $0.displayID == id }) ?? all.displays.first else { return }
        let me = all.applications.filter { $0.bundleIdentifier == Bundle.main.bundleIdentifier }
        let cfg = SCStreamConfiguration()
        cfg.width = 1280; cfg.height = Int(1280 * Double(d.height) / Double(d.width))
        guard let img = try? await SCScreenshotManager.captureImage(contentFilter: SCContentFilter(display: d, excludingApplications: me, exceptingWindows: []), configuration: cfg),
              let jpg = NSBitmapImageRep(cgImage: img).representation(using: .jpeg, properties: [.compressionFactor: 0.7]) else { return }
        try? jpg.write(to: URL(fileURLWithPath: a[3]))
    }
    done.wait()
    exit(FileManager.default.fileExists(atPath: a[3]) ? 0 : 1)
}

// `Atticus --text <app> [title words]` (atticus.py --watch): the text in that app's window, read on this Mac, even when covered.
if CommandLine.arguments.count >= 3, CommandLine.arguments[1] == "--text" {
    let a = CommandLine.arguments, words = a.count > 3 ? a[3].lowercased() : "", done = DispatchSemaphore(value: 0)
    var found = false
    _ = NSApplication.shared   // ScreenCaptureKit needs a window-server connection
    Task {
        defer { done.signal() }
        guard let all = try? await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: false) else { return }
        // apps keep hidden helper windows: real ones first (normal layer, on screen, biggest), next one if a capture reads nothing
        let ws = all.windows.filter { ($0.owningApplication?.applicationName ?? "").localizedCaseInsensitiveContains(a[2]) && $0.windowLayer == 0 &&
                (words.isEmpty || ($0.title ?? "").lowercased().contains(words)) && $0.frame.width > 200 && $0.frame.height > 150 }
            .sorted { ($0.isOnScreen ? 1 : 0, $0.frame.width * $0.frame.height) > ($1.isOnScreen ? 1 : 0, $1.frame.width * $1.frame.height) }
        for w in ws.prefix(4) {
            let cfg = SCStreamConfiguration()
            cfg.width = Int(w.frame.width * 2); cfg.height = Int(w.frame.height * 2)   // full detail: small terminal text must read right
            guard let img = try? await SCScreenshotManager.captureImage(contentFilter: SCContentFilter(desktopIndependentWindow: w), configuration: cfg) else { continue }
            let req = VNRecognizeTextRequest(); req.usesLanguageCorrection = false
            try? VNImageRequestHandler(cgImage: img).perform([req])
            let text = (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }
            if text.isEmpty { continue }
            print(text.joined(separator: "\n")); found = true; return
        }
    }
    done.wait()
    exit(found ? 0 : 1)
}

// "Show me where": a soft pulsing ring at a spot on screen for a few seconds. "@ x y" in top-left screen points.
var ring: NSPanel?
func pointAt(_ line: String) {
    let p = line.split(separator: " ").dropFirst().compactMap { Double($0) }
    guard p.count == 2, let main = NSScreen.screens.first else { return }
    let size: CGFloat = 64, c = NSPoint(x: p[0], y: main.frame.height - p[1])   // flip to Cocoa's bottom-left origin
    ring?.orderOut(nil)
    let w = NSPanel(contentRect: NSRect(x: c.x - size / 2, y: c.y - size / 2, width: size, height: size),
                    styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
    w.level = .screenSaver; w.isOpaque = false; w.backgroundColor = .clear; w.ignoresMouseEvents = true; w.hasShadow = false
    w.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
    let v = NSView(frame: NSRect(x: 0, y: 0, width: size, height: size)); v.wantsLayer = true
    let l = CAShapeLayer()
    l.path = CGPath(ellipseIn: CGRect(x: 8, y: 8, width: size - 16, height: size - 16), transform: nil)
    l.fillColor = NSColor.systemBlue.withAlphaComponent(0.18).cgColor; l.strokeColor = NSColor.systemBlue.cgColor; l.lineWidth = 3
    l.frame = v.bounds; v.layer?.addSublayer(l)
    let pulse = CABasicAnimation(keyPath: "transform.scale"); pulse.fromValue = 0.7; pulse.toValue = 1.1
    pulse.duration = 0.6; pulse.autoreverses = true; pulse.repeatCount = 6
    l.anchorPoint = CGPoint(x: 0.5, y: 0.5); l.position = CGPoint(x: size / 2, y: size / 2); l.bounds = v.bounds; l.add(pulse, forKey: "pulse")
    w.contentView = v; w.orderFrontRegardless(); ring = w
    DispatchQueue.main.asyncAfter(deadline: .now() + 6) { if ring === w { w.orderOut(nil); ring = nil } }
}

func jsonString(_ s: String) -> String { String(data: try! JSONSerialization.data(withJSONObject: [s]), encoding: .utf8)!.dropFirst().dropLast().description }

// Restart Atticus (Screen Recording only takes effect in a new process); works under launchd or when opened by hand.
func relaunchSoon() {
    let p = Process(); p.executableURL = URL(fileURLWithPath: "/bin/sh")
    p.arguments = ["-c", "sleep 1; launchctl bootout gui/\(getuid())/com.atticus.app >/dev/null 2>&1; sleep 1; launchctl bootstrap gui/\(getuid()) \"$1\" 2>/dev/null || open \"$0\"",
                   Bundle.main.bundlePath, NSHomeDirectory() + "/Library/LaunchAgents/com.atticus.app.plist"]
    try? p.run()
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { NSApp.terminate(nil) }
}

// Updates: build.sh records the source folder (a git clone); Atticus pulls and rebuilds itself from it, then
// restarts once idle. Local edits or a failed build leave the running version alone.
enum Updater {
    static let src = Bundle.main.object(forInfoDictionaryKey: "AtticusSource") as? String ?? ""
    static var status = ""
    static func sh(_ script: String) -> (code: Int32, out: String) {
        let p = Process(), o = Pipe()
        p.executableURL = URL(fileURLWithPath: "/bin/zsh"); p.arguments = ["-c", script, src]; p.standardOutput = o; p.standardError = o
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"; env["ATTICUS_NO_RESTART"] = "1"; p.environment = env
        try? p.run(); p.waitUntilExit()
        return (p.terminationStatus, String(data: o.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? "")
    }
    static let version: String = {
        sh(#"cd "$0" 2>/dev/null && git log -1 --format='%h · %cd' --date=format:'%b %-d, %Y'"#).out.trimmingCharacters(in: .whitespacesAndNewlines)
    }()
    static func check(_ done: @escaping () -> Void = {}) {
        status = "Checking…"; done()
        DispatchQueue.global().async {
            let r = sh(#"""
                cd "$0" 2>/dev/null || exit 3
                [ -z "$(git status --porcelain)" ] || exit 5
                git fetch -q 2>/dev/null || exit 4
                [ "$(git rev-parse HEAD)" = "$(git rev-parse '@{u}')" ] && exit 0
                git pull -q --ff-only 2>/dev/null || exit 5
                ./build.sh >/dev/null 2>&1 || exit 6
                exit 10
                """#)
            DispatchQueue.main.async {
                status = [0: "Up to date", 3: "Source folder not found (reinstall with build.sh)", 4: "Couldn’t reach GitHub",
                          5: "Skipped: the source folder has local changes", 6: "Update downloaded, but the build failed",
                          10: "Updated. Restarting when you’re not using it…"][r.code] ?? "Update failed"
                done()
                if r.code == 10 { restartWhenIdle() }
            }
        }
    }
    static func restartWhenIdle() {
        if app.busy || app.engine.isRunning || app.voice?.isRunning == true || meeting.panel != nil || settings.win?.isKeyWindow == true || onboarding.win != nil {
            DispatchQueue.main.asyncAfter(deadline: .now() + 30) { restartWhenIdle() }
        } else { relaunchSoon() }
    }
    static func schedule() {   // a minute after launch, then every 6 hours
        DispatchQueue.main.asyncAfter(deadline: .now() + 60) { if Prefs.bool("autoUpdate") { check() } }
        Timer.scheduledTimer(withTimeInterval: 6 * 3600, repeats: true) { _ in if Prefs.bool("autoUpdate") { check() } }
    }
}

// Opening Atticus again (Spotlight, Finder, Dock) while it runs: setup the first time, Settings after.
final class Delegate: NSObject, NSApplicationDelegate {
    func applicationWillTerminate(_ n: Notification) { meeting.discard(); app.hush(); app.shush() }
    func applicationShouldHandleReopen(_ s: NSApplication, hasVisibleWindows: Bool) -> Bool {
        UserDefaults.standard.bool(forKey: "onboarded") ? settings.open() : onboarding.open()
        return false
    }
}

// The menu bar icon: quick actions, today's usage.
final class MenuBar: NSObject, NSMenuDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    override init() {
        super.init()
        item.button?.image = NSImage(systemSymbolName: "waveform", accessibilityDescription: "Atticus")
        let m = NSMenu(); m.delegate = self; item.menu = m
        item.isVisible = Prefs.bool("menuIcon")
        paint()
    }
    func paint() { item.button?.appearsDisabled = Prefs.bool("paused"); item.button?.title = meeting.running ? " ·" : ""; item.length = meeting.running ? 38 : NSStatusItem.squareLength }
    func menuNeedsUpdate(_ m: NSMenu) {
        m.removeAllItems()
        let keys = Prefs.str("hotkeyLabel")
        let hint = Prefs.str("input") == "type" ? "Press \(keys) to type" : Prefs.str("talkMode") == "toggle" ? "Press \(keys) to talk · again to send" : "Hold \(keys) and talk"
        let head = NSMenuItem(title: Prefs.bool("paused") ? "Atticus is paused" : hint, action: nil, keyEquivalent: "")
        head.isEnabled = false; m.addItem(head)
        m.addItem(.separator())
        add(m, "Ask Atticus", #selector(ask), "")
        if Prefs.bool("meeting") { add(m, meeting.running ? "Stop Meeting Copilot" : "Start Meeting Copilot", #selector(toggleMeeting), "") }
        add(m, Prefs.bool("paused") ? "Resume Atticus" : "Pause Atticus", #selector(pause), "")
        m.addItem(.separator())
        let u = NSMenuItem(title: today(), action: nil, keyEquivalent: ""); u.isEnabled = false; m.addItem(u)
        m.addItem(.separator())
        add(m, "Settings…", #selector(openSettings), ",")
        add(m, "Setup & Permissions…", #selector(openSetup), "")
        add(m, "Report Feedback…", #selector(reportFeedback), "")
        m.addItem(.separator())
        add(m, "Quit Atticus", #selector(quit), "q")
    }
    func add(_ m: NSMenu, _ t: String, _ a: Selector, _ k: String) { let i = NSMenuItem(title: t, action: a, keyEquivalent: k); i.target = self; m.addItem(i) }
    func today() -> String {
        let day = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; return f.string(from: Date()) }()
        let log = (try? String(contentsOfFile: NSString(string: "~/.config/atticus/log.jsonl").expandingTildeInPath, encoding: .utf8)) ?? ""
        let rows = log.split(separator: "\n").compactMap { try? JSONSerialization.jsonObject(with: Data($0.utf8)) as? [String: Any] }
            .filter { ($0["at"] as? String ?? "").hasPrefix(day) }
        let usd = rows.reduce(0.0) { $0 + (($1["usd"] as? NSNumber)?.doubleValue ?? 0) }
        return "Today: \(rows.count) ask\(rows.count == 1 ? "" : "s") · " + (usd < 1 ? String(format: "%.2f¢", usd * 100) : String(format: "$%.2f", usd))
    }
    @objc func toggleMeeting() { meeting.running ? meeting.stop() : meeting.open() }
    @objc func ask() { if meeting.running { return meeting.focus() }; app.clickTalk = true; app.start(); if !app.engine.isRunning { app.clickTalk = false } }   // the same box as the shortcut, like its mic button
    @objc func pause() { Prefs.set("paused", !Prefs.bool("paused")); if Prefs.bool("paused") { meeting.stop(paused: true); app.close(clear: false) }; paint(); settings.push() }
    @objc func openSettings() { settings.open() }
    @objc func openSetup() { onboarding.open() }
    @objc func reportFeedback() { settings.open(tab:"feedback") }
    @objc func quit() { NSApp.terminate(nil) }
}

// Settings window (ui/settings.html): every setting lives in Prefs; atticus.py reads the same file.
// Apps Atticus may control. macOS asks once per app, only while that app runs, and has no "allow all". So Settings > Apps
// lists every installed app and asks for all the ticked ones in one go: start each hidden, ask, quit it again.
// macOS only answers "allowed?" for running apps, so what it said is kept in UserDefaults ("allowedApps").
enum Apps {
    static let suggested: Set<String> = ["com.apple.systemevents", "com.apple.finder", "com.apple.Safari", "com.google.Chrome",
        "company.thebrowser.Browser", "com.brave.Browser", "com.apple.Notes", "com.apple.reminders", "com.apple.iCal", "com.apple.Music",
        "com.spotify.client", "com.apple.Terminal", "com.googlecode.iterm2", "com.apple.mail", "com.apple.MobileSMS", "com.apple.Preview",
        "com.apple.TextEdit", "com.apple.systempreferences", "com.microsoft.VSCode", "com.apple.shortcuts", "com.apple.AddressBook",
        "com.apple.Photos", "com.apple.iWork.Pages", "com.apple.iWork.Keynote", "com.apple.iWork.Numbers", "com.microsoft.Word",
        "com.microsoft.Excel", "com.microsoft.Powerpoint", "com.tinyspeck.slackmacgap", "us.zoom.xos", "com.hnc.Discord", "notion.id"]
    static var icons: [String: String] = [:]   // bundle id -> data URL, made once per launch
    static var job = 0, current = 0   // each Allow click is a new job; Stop (or a newer click) ends the one running
    static var stopped: Bool { job != current }
    static let q = DispatchQueue(label: "apps")   // one job at a time: two at once corrupted icons and lost allowed apps (a crash)
    static func wait(_ s: DispatchSemaphore, _ secs: Double) -> Bool {   // true = done; gives up early on Stop
        for _ in 0..<Int(secs * 10) { if s.wait(timeout: .now() + 0.1) == .success { return true }; if stopped { return false } }
        return false
    }

    static var allowed: Set<String> {
        get { Set(UserDefaults.standard.stringArray(forKey: "allowedApps") ?? []) }
        set { UserDefaults.standard.set(Array(newValue), forKey: "allowedApps") }
    }
    static func check(_ id: String, ask: Bool) -> OSStatus {   // ask: show macOS's prompt if it never asked (blocks until answered)
        var d = AEAddressDesc()
        _ = id.withCString { AECreateDesc(typeApplicationBundleID, $0, id.utf8.count, &d) }
        defer { AEDisposeDesc(&d) }
        return AEDeterminePermissionToAutomateTarget(&d, typeWildCard, typeWildCard, ask)
    }
    // "allowed" | "blocked" | "new" per app, asked all at once: a busy or frozen app can stall macOS's answer forever,
    // so whatever isn't back in 1.5 s keeps what was saved before.
    @discardableResult static func statuses(_ ids: [String]) -> [String: String] {
        var codes = [String: OSStatus](); let lock = NSLock(), g = DispatchGroup()
        for id in ids {
            g.enter()
            DispatchQueue.global().async { let r = check(id, ask: false); lock.lock(); codes[id] = r; lock.unlock(); g.leave() }
        }
        _ = g.wait(timeout: .now() + 1.5)
        lock.lock(); let got = codes; lock.unlock()
        var a = allowed, out = [String: String]()
        for id in ids {
            if got[id] == noErr { a.insert(id) } else if got[id] == OSStatus(errAEEventNotPermitted) { a.remove(id) }
            out[id] = got[id] == OSStatus(errAEEventNotPermitted) ? "blocked" : a.contains(id) ? "allowed" : "new"
        }
        allowed = a
        return out
    }
    static func sync() {   // after an ask: an app allowed in the moment, at macOS's own prompt, joins the list
        statuses(NSWorkspace.shared.runningApplications.filter { $0.activationPolicy == .regular }.compactMap(\.bundleIdentifier))
    }
    static func png(_ img: NSImage) -> String {
        guard let r = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 64, pixelsHigh: 64, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                       isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return "" }
        NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: r)
        img.draw(in: NSRect(x: 0, y: 0, width: 64, height: 64)); NSGraphicsContext.restoreGraphicsState()
        return "data:image/png;base64," + (r.representation(using: .png, properties: [:])?.base64EncodedString() ?? "")
    }
    static func list() -> [[String: Any]] {
        let fm = FileManager.default
        let dirs = ["/Applications", "/Applications/Utilities", "/System/Applications", "/System/Applications/Utilities", NSHomeDirectory() + "/Applications"]
        let paths = dirs.flatMap { d in ((try? fm.contentsOfDirectory(atPath: d)) ?? []).filter { $0.hasSuffix(".app") }.map { d + "/" + $0 } }
            + ["/System/Library/CoreServices/Finder.app", "/System/Library/CoreServices/System Events.app"]
        var seen = Set<String>(), out: [[String: Any]] = []
        for p in paths {
            guard let id = Bundle(path: p)?.bundleIdentifier, id != Bundle.main.bundleIdentifier, seen.insert(id).inserted else { continue }
            if icons[id] == nil { icons[id] = png(NSWorkspace.shared.icon(forFile: p)) }
            var name = fm.displayName(atPath: p); if name.hasSuffix(".app") { name.removeLast(4) }
            out.append(["id": id, "name": name, "icon": icons[id]!, "suggested": suggested.contains(id)])
        }
        let st = statuses(out.map { $0["id"] as! String })
        for i in out.indices { out[i]["status"] = st[out[i]["id"] as! String] }
        return out.sorted { ($0["name"] as! String).localizedCaseInsensitiveCompare($1["name"] as! String) == .orderedAscending }
    }
    static func allow(_ ids: [String], _ progress: @escaping (String, String) -> Void) {   // on q
        for id in ids where !stopped {
            var started: NSRunningApplication?
            if NSRunningApplication.runningApplications(withBundleIdentifier: id).isEmpty, let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: id) {
                let c = NSWorkspace.OpenConfiguration(); c.activates = false; c.hides = true; c.addsToRecentItems = false
                let done = DispatchSemaphore(value: 0)
                NSWorkspace.shared.openApplication(at: url, configuration: c) { a, _ in started = a; done.signal() }
                _ = wait(done, 15)
            }
            progress(id, "asking")
            // An app that just opened can't be asked yet (procNotFound, and macOS shows nothing): try again for up to 5 s.
            // Some apps (Spotify) never answer: move on after 20 s.
            for _ in 0..<20 where !stopped {
                final class Box { var code = OSStatus(procNotFound) }
                let answered = DispatchSemaphore(value: 0), r = Box()
                DispatchQueue.global().async { r.code = check(id, ask: true); answered.signal() }
                guard wait(answered, 20), r.code == OSStatus(procNotFound) else { break }
                Thread.sleep(forTimeInterval: 0.25)
            }
            started?.terminate()   // only the ones Atticus started
            progress(id, statuses([id])[id]!)
        }
    }
}

final class SettingsWindow: NSObject, WKScriptMessageHandler, WKNavigationDelegate, NSWindowDelegate {
    var win: NSWindow?, web: WKWebView?
    var feedbackJob = 0, feedbackURL: URL?

    var tab = "", timer: Timer?   // tab: shown once the page loads

    func open(tab t: String = "") {
        NSApp.activate(ignoringOtherApps: true)
        if let w = win { w.makeKeyAndOrderFront(nil); refresh(); if !t.isEmpty { js("st.tab('\(t)')") }; return }
        tab = t
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 780, height: 560),
                         styleMask: [.titled, .closable, .miniaturizable, .fullSizeContentView], backing: .buffered, defer: false)
        w.titlebarAppearsTransparent = true; w.titleVisibility = .hidden; w.title = "Atticus Settings"
        w.appearance = NSAppearance(named:.darkAqua)
        w.isReleasedWhenClosed = false; w.delegate = self
        let bg = NSVisualEffectView(frame: w.contentRect(forFrameRect: w.frame))
        bg.material = .underWindowBackground; bg.blendingMode = .behindWindow; bg.state = .active
        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(self, name: "st")
        let v = WKWebView(frame: bg.bounds, configuration: cfg)
        v.autoresizingMask = [.width, .height]; v.setValue(false, forKey: "drawsBackground"); v.navigationDelegate = self
        v.loadHTMLString((try? String(contentsOfFile: dir + "/ui/settings.html", encoding: .utf8)) ?? "missing settings.html", baseURL: nil)
        bg.addSubview(v); w.contentView = bg
        win = w; web = v
        w.center(); w.makeKeyAndOrderFront(nil)
        timer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in   // System Settings changes them behind our back
            DispatchQueue.global().async { self?.send("perms", Onboarding.perms()) }
        }
    }

    func webView(_ v: WKWebView, didFinish n: WKNavigation!) { push(); refresh(); DispatchQueue.global().async { [weak self] in self?.send("perms", Onboarding.perms()) }; if !tab.isEmpty { js("st.tab('\(tab)')"); tab = "" } }

    func send(_ call: String, _ v: Any) {
        guard JSONSerialization.isValidJSONObject(v), let d = try? JSONSerialization.data(withJSONObject: v), let j = String(data: d, encoding: .utf8) else { return }
        DispatchQueue.main.async { [weak self] in self?.js("st.\(call)(\(j))") }
    }

    func push() {   // the settings, and the app icon for the sidebar
        js("st.motion(\(NSWorkspace.shared.accessibilityDisplayShouldReduceMotion))")
        var d: [String: Any] = ["prefs": Prefs.d, "version": Updater.version, "update": Updater.status]
        if let t = NSApp.applicationIconImage?.tiffRepresentation, let png = NSBitmapImageRep(data: t)?.representation(using: .png, properties: [:]) {
            d["icon"] = "data:image/png;base64," + png.base64EncodedString()
        }
        guard let j = try? JSONSerialization.data(withJSONObject: d), let s = String(data: j, encoding: .utf8) else { return }
        web?.evaluateJavaScript("st.load(\(s))")
    }

    func refresh() {   // usage, saved rules, Claude plan: atticus.py --state (it runs Claude Code, so off the main thread)
        DispatchQueue.global().async { [weak self] in
            let p = py(["--state"]), out = Pipe(); p.standardOutput = out
            try? p.run(); p.waitUntilExit()
            let s = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            guard s.hasPrefix("{") else { return }
            DispatchQueue.main.async { self?.web?.evaluateJavaScript("st.state(\(s))") }
        }
    }
    func feedbackPreview(_ include: Bool, _ text: String, _ revision: Int = 0) {
        feedbackJob += 1; let job = feedbackJob; feedbackURL = nil
        let version = Updater.version.isEmpty ? Bundle.main.object(forInfoDictionaryKey:"CFBundleShortVersionString") as? String ?? "unknown" : Updater.version
        DispatchQueue.global().async { [weak self] in
            let p = py(["--feedback"]), input = Pipe(), out = Pipe(); p.standardInput = input; p.standardOutput = out
            fcntl(input.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
            do { try p.run(); try input.fileHandleForWriting.write(contentsOf:JSONSerialization.data(withJSONObject:["include":include,"version":version,"text":text])); try input.fileHandleForWriting.close() }
            catch { if p.isRunning { p.terminate() }; DispatchQueue.main.async { if self?.feedbackJob == job { self?.send("feedback", ["error":"Could not prepare feedback. Try again.","revision":revision]) } }; return }
            let data = out.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
            var result = (try? JSONSerialization.jsonObject(with:data)) as? [String:Any]; result?["revision"] = revision
            DispatchQueue.main.async { [weak self] in
                guard let self, feedbackJob == job, web != nil else { return }
                guard let result, let text = result["url"] as? String, let url = URL(string:text), url.host == "github.com", url.path == "/SaarthurR/atticus-mac/issues/new" else { send("feedback", ["error":"Could not prepare feedback. Try again.","revision":revision]); return }
                feedbackURL = url; send("feedback", result)
            }
        }
    }

    // "Change shortcut": the next key pressed with modifiers (or a lone F-key) becomes the talk shortcut. Esc cancels.
    var monitor: Any?
    func record() {
        if monitor != nil { return }
        if let r = ref { UnregisterEventHotKey(r); ref = nil }   // so pressing the old one doesn't start listening
        let fkeys = [122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111, 105, 107, 113, 106, 64, 79, 80, 90]
        monitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .flagsChanged]) { [weak self] e in
            guard let self else { return e }
            let f = e.modifierFlags.intersection([.command, .shift, .option, .control])
            let mods = (f.contains(.control) ? "⌃" : "") + (f.contains(.option) ? "⌥" : "") + (f.contains(.shift) ? "⇧" : "") + (f.contains(.command) ? "⌘" : "")
            if e.type == .flagsChanged { js("st.rec(\(jsonString(mods)))"); return nil }
            if e.keyCode == 53 && f.isEmpty { done(nil); return nil }   // Esc
            let fn = fkeys.firstIndex(of: Int(e.keyCode))
            guard !f.isEmpty || fn != nil else { js("st.rec(\(jsonString("Add ⌃, ⌥, ⇧ or ⌘")))"); return nil }
            let names: [UInt16: String] = [49: "Space", 36: "Return", 48: "Tab", 51: "Delete", 123: "←", 124: "→", 125: "↓", 126: "↑"]
            let key = fn.map { "F\($0 + 1)" } ?? names[e.keyCode] ?? (e.charactersIgnoringModifiers ?? "?").uppercased()
            var c = 0
            if f.contains(.command) { c |= cmdKey }; if f.contains(.shift) { c |= shiftKey }
            if f.contains(.option) { c |= optionKey }; if f.contains(.control) { c |= controlKey }
            done((Int(e.keyCode), c, mods + key))
            return nil
        }
    }

    func done(_ new: (code: Int, mods: Int, label: String)?) {
        if let m = monitor { NSEvent.removeMonitor(m); monitor = nil }
        let old = (Prefs.d["hotkeyCode"], Prefs.d["hotkeyMods"], Prefs.d["hotkeyLabel"])
        if let n = new { Prefs.set("hotkeyCode", n.code); Prefs.set("hotkeyMods", n.mods); Prefs.set("hotkeyLabel", n.label) }
        if !registerHotkey() {   // taken by another app: keep the old one
            Prefs.set("hotkeyCode", old.0!); Prefs.set("hotkeyMods", old.1!); Prefs.set("hotkeyLabel", old.2!)
            registerHotkey()
            js("st.taken()")
        }
        push()
    }

    func js(_ s: String) { web?.evaluateJavaScript(s) }

    func helper(_ args: [String]) { let p = py(args); try? p.run(); p.waitUntilExit() }

    func meetings(_ data: [String: Any], _ done: (([String: Any]) -> Void)? = nil) {
        if data["action"] as? String == "delete" {
            let alert = NSAlert(); alert.messageText = "Delete this meeting?"; alert.informativeText = "Its transcript, notes and recap will be removed from this Mac."; alert.addButton(withTitle: "Delete"); alert.addButton(withTitle: "Cancel")
            guard alert.runModal() == .alertFirstButtonReturn else { done?([:]); return }
        }
        DispatchQueue.global().async { [weak self] in
            let p = py(["--meetings"]), input = Pipe(), output = Pipe(); p.standardInput = input; p.standardOutput = output
            fcntl(input.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
            var result: [String: Any] = ["error": "Could not open saved meetings. Try again."]
            do {
                try p.run(); try input.fileHandleForWriting.write(contentsOf: JSONSerialization.data(withJSONObject: data)); try input.fileHandleForWriting.close()
                let body = output.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
                result = (try? JSONSerialization.jsonObject(with: body)) as? [String: Any] ?? result
            } catch { }
            let reply = result
            DispatchQueue.main.async {
                if reply["deleted"] as? String == meeting.archive?.id { meeting.archive = nil; meeting.js("saving", false) }
                if let done { done(reply) } else { self?.send("meetings", reply) }
            }
        }
    }

    func exportMeeting(_ id: String) {
        meetings(["action": "export", "id": id]) { [weak self] result in
            guard let markdown = result["markdown"] as? String else { self?.send("meetings", result); return }
            let chooser = NSSavePanel(); chooser.allowedContentTypes = [UTType(filenameExtension: "md") ?? .plainText];   // .markdown is macOS 27+ chooser.nameFieldStringValue = "Meeting.md"
            chooser.begin { response in
                guard response == .OK, let url = chooser.url else { return }
                do { try MeetingArchive.export(markdown, to: url); self?.send("meetings", ["notice": "Markdown exported."]) }
                catch { self?.send("meetings", ["error": "Could not export. Try another location."]) }
            }
        }
    }

    func apply(_ k: String, _ v: Any) {   // one setting changed, from this window or by voice (atticus.py --set)
        if k == "meetingSave", v as? Bool == false, Prefs.bool("meetingSave") {
            meeting.savingChanged(false); Prefs.set(k, false); push()
            let alert = NSAlert(); alert.messageText = "Keep your saved meetings?"; alert.informativeText = "New transcripts will no longer be saved. You can keep or delete the meetings already on this Mac."; alert.addButton(withTitle: "Keep Meetings"); alert.addButton(withTitle: "Delete All Meetings")
            if alert.runModal() == .alertSecondButtonReturn { meetings(["action": "clear"]) }
            return
        }
        Prefs.set(k, v)
        if k == "meetingSave" { meeting.savingChanged(v as? Bool == true) }
        if k == "meeting", v as? Bool == false { meeting.stop() }
        if k == "meetingNudge", v as? Bool == true, EKEventStore.authorizationStatus(for: .event) != .fullAccess {
            calendar.requestFullAccessToEvents { ok, _ in if !ok { DispatchQueue.main.async { Prefs.set("meetingNudge", false); settings.push() } } }
        }
        if k == "speechModel" { app.prepareSpeech() }
        if k == "improve" { Prefs.set("improveAsked", true) }   // any answer, here or in setup or the card, is the answer
        if k == "speak" { if v as? Bool == true { siriVoice() } else { app.shush() } }
        if k == "hideWhenSharing" { app.panel.sharingType = v as? Bool == true ? .none : .readOnly }
        if k == "menuIcon" { bar.item.isVisible = v as? Bool == true }
        if k == "paused" { if v as? Bool == true { meeting.stop(paused: true); app.close(clear: false) }; bar.paint() }
        if k == "safe" { app.js("mode", v as? Bool == true) }
        if k == "login" {   // the LaunchAgent build.sh installed: enabled = starts at login
            let p = Process(); p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
            p.arguments = [v as? Bool == true ? "enable" : "disable", "gui/\(getuid())/com.atticus.app"]; try? p.run()
        }
    }

    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        guard let b = m.body as? [String: Any], let what = b["do"] as? String else { return }
        switch what {
        case "feedbackInvalidate": feedbackJob += 1; feedbackURL = nil
        case "feedbackPreview": feedbackPreview(b["include"] as? Bool ?? false, b["text"] as? String ?? "", b["revision"] as? Int ?? 0)
        case "feedbackOpen": if let feedbackURL { NSWorkspace.shared.open(feedbackURL) }
        case "meetings": meetings(["action": "list", "query": b["query"] as? String ?? ""])
        case "meetingOpen": if let id = b["id"] as? String { meetings(["action": "get", "id": id]) }
        case "meetingDelete": if let id = b["id"] as? String { meetings(["action": "delete", "id": id]) }
        case "meetingExport": if let id = b["id"] as? String { exportMeeting(id) }
        case "meetingCopy": if let text = b["text"] as? String { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string); send("meetings", ["notice": "Copied."]) }
        case "meetingDemo": if Prefs.bool("meeting") { meeting.open(demo: true) }
        case "set":
            guard let k = b["k"] as? String, let v = b["v"] else { return }
            apply(k, v)
        case "record": record()
        case "cancelRecord": if monitor != nil { done(nil) }
        case "unlearn":
            guard let say = b["say"] as? String else { return }
            DispatchQueue.global().async { [weak self] in self?.helper(["--unlearn", say]); DispatchQueue.main.async { self?.refresh() } }
        case "checkUpdate": Updater.check { [weak self] in self?.push() }
        case "github": NSWorkspace.shared.open(URL(string: "https://github.com/SaarthurR/atticus-mac")!)
        case "resetHotkey":
            Prefs.set("hotkeyCode", 49); Prefs.set("hotkeyMods", controlKey | optionKey); Prefs.set("hotkeyLabel", "⌃⌥Space")
            registerHotkey(); push()
        case "preview":
            if let n = b["sound"] as? String { app.sound(n, Float(Prefs.num("volume"))) }
        case "setup": onboarding.open()
        case "openLog": NSWorkspace.shared.open(URL(fileURLWithPath: NSString(string: "~/.config/atticus/log.jsonl").expandingTildeInPath))
        case "clearRecent": try? FileManager.default.removeItem(atPath: app.recent); app.lastDone = .distantPast
        case "me":   // About you: name / about / drop a fact
            guard let what = b["what"] as? String, let text = b["text"] as? String else { return }
            DispatchQueue.global().async { [weak self] in self?.helper(["--me", what, text]); DispatchQueue.main.async { self?.refresh() } }
        case "forget", "remember":
            guard let line = b["line"] as? String else { return }
            DispatchQueue.global().async { [weak self] in self?.helper(["--" + what, line]); DispatchQueue.main.async { self?.refresh() } }
        case "apps": Apps.q.async { [weak self] in self?.send("apps", Apps.list()) }
        case "allow":
            guard let ids = b["ids"] as? [String] else { return }
            Apps.job += 1; let me = Apps.job
            Apps.q.async { [weak self] in
                Apps.current = me
                Apps.allow(ids) { id, s in self?.send("appStatus", [id, s]) }
                self?.send("allowDone", [Any]())
            }
        case "grant": if let id = b["id"] as? String { onboarding.grant(id) }
        case "stopAllow": Apps.job += 1
        case "automation": NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation")!)
        case "quit": NSApp.terminate(nil)
        default: break
        }
    }

    func windowDidResignKey(_ n: Notification) { if monitor != nil { done(nil) } }

    func windowWillClose(_ n: Notification) {
        feedbackJob += 1; feedbackURL = nil
        if monitor != nil { done(nil) }   // closed mid-recording: keep the old shortcut
        timer?.invalidate(); timer = nil
        web?.configuration.userContentController.removeScriptMessageHandler(forName: "st")
        web = nil; win = nil
    }
}

// Meeting audio stays on-device; the journal stores text, never audio.
final class MeetingArchive {
    let id: String, folder: String
    let handle: FileHandle
    init(title: String, app: String, started: Date) throws {
        id = UUID().uuidString
        let root = (Prefs.path as NSString).deletingLastPathComponent + "/meetings"
        folder = root + "/" + id
        let fm = FileManager.default
        if (try? fm.attributesOfItem(atPath: root)[.type] as? FileAttributeType) == .typeSymbolicLink { throw CocoaError(.fileWriteNoPermission) }
        try fm.createDirectory(atPath: root, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try fm.setAttributes([.posixPermissions: 0o700], ofItemAtPath: root)
        try fm.createDirectory(atPath: folder, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        let metadata: [String: Any] = ["title": title, "app": app, "started": started.timeIntervalSince1970, "version": 1]
        let data = try JSONSerialization.data(withJSONObject: metadata, options: [.sortedKeys])
        guard fm.createFile(atPath: folder + "/metadata.json", contents: data, attributes: [.posixPermissions: 0o600]), fm.createFile(atPath: folder + "/events.jsonl", contents: nil, attributes: [.posixPermissions: 0o600]) else { throw CocoaError(.fileWriteUnknown) }
        let fd = Darwin.open(folder + "/events.jsonl", O_WRONLY | O_APPEND | O_NOFOLLOW)
        guard fd >= 0 else { throw CocoaError(.fileWriteUnknown) }; handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        try handle.synchronize()
    }
    func append(_ event: [String: Any]) throws {
        var data = try JSONSerialization.data(withJSONObject: event, options: [.sortedKeys]); data.append(10)
        try handle.write(contentsOf: data); try handle.synchronize()
    }
    static func export(_ text: String, to url: URL) throws {
        let temp = url.deletingLastPathComponent().appendingPathComponent(".atticus-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: temp) }
        guard FileManager.default.createFile(atPath: temp.path, contents: Data(text.utf8), attributes: [.posixPermissions: 0o600]), Darwin.rename(temp.path, url.path) == 0 else { throw CocoaError(.fileWriteUnknown) }
    }
    deinit { try? handle.close() }
}

// Greetings and tag questions ("How are you?", "…, right?") are for the user to answer, not the AI (same rule as atticus.py).
let meetingSmallTalk = #"^(hi|hey|hello|so|oh|well)?\W*(how are (you|things|we)( doing| going| all)?|how('s| is) (it going|everyone|everybody|life|your day)|how have you been|what'?s up|can (you|everyone|everybody) (hear|see) (me|my screen)|is (everyone|everybody) here|are you there)\W*(\w+\W*)?$|(^|[\s,])(right|okay|ok|yeah|you know|make sense|sound good)\?$"#
func meetingQuestion(_ text: String, _ name: String) -> Bool {
    let line = text.trimmingCharacters(in: .whitespacesAndNewlines)
    let first = name.split(whereSeparator: { $0.isWhitespace }).first.map(String.init) ?? ""
    guard line.range(of: meetingSmallTalk, options: [.regularExpression, .caseInsensitive]) == nil else { return false }
    return !line.isEmpty && (line.hasSuffix("?") || line.range(of: "^(what|why|how|when|where|who|which|can|could|should|would|do|does|did|is|are|will)\\b", options: [.regularExpression, .caseInsensitive]) != nil || (!first.isEmpty && line.range(of: "(?<!\\w)" + NSRegularExpression.escapedPattern(for: first) + "(?!\\w)", options: [.regularExpression, .caseInsensitive]) != nil))
}

final class MeetingAudio: NSObject, SCStreamOutput, SCStreamDelegate {
    var stream: SCStream?, feed: AsyncStream<AnalyzerInput>.Continuation?, micFeed: AsyncStream<AnalyzerInput>.Continuation?
    var format: AVAudioFormat?, converter: AVAudioConverter?, natural: AVAudioFormat?
    var micConverter: AVAudioConverter?, micNatural: AVAudioFormat?
    var onError: ((Error) -> Void)?, onLevel: ((Float) -> Void)?
    var levelAt = Date.distantPast, level: Float = 0, micLevel: Float = 0
    var samples = 0, peak: Float = 0
    let queue = DispatchQueue(label: "meeting.audio")
    func start(_ format: AVAudioFormat?, _ feed: AsyncStream<AnalyzerInput>.Continuation?, _ micFeed: AsyncStream<AnalyzerInput>.Continuation?) async throws {
        self.format = format; self.feed = feed; self.micFeed = micFeed
        let all = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = all.displays.first else { throw NSError(domain: "Meeting", code: 1) }
        let cfg = SCStreamConfiguration()
        cfg.capturesAudio = true; cfg.excludesCurrentProcessAudio = true; cfg.captureMicrophone = micFeed != nil
        cfg.sampleRate = 48000; cfg.channelCount = 2
        cfg.width = 2; cfg.height = 2; cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1); cfg.showsCursor = false
        let s = SCStream(filter: SCContentFilter(display: display, excludingWindows: []), configuration: cfg, delegate: self)
        stream = s
        try s.addStreamOutput(self, type: .audio, sampleHandlerQueue: queue)
        if micFeed != nil { try s.addStreamOutput(self, type: .microphone, sampleHandlerQueue: queue) }
        try await s.startCapture()
    }
    func stop() async {
        let s = stream; stream = nil
        try? await s?.stopCapture()
        queue.sync { feed?.finish(); micFeed?.finish(); feed = nil; micFeed = nil; converter = nil; natural = nil; micConverter = nil; micNatural = nil }
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) { onError?(error) }
    func stream(_ stream: SCStream, didOutputSampleBuffer sample: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio || type == .microphone, sample.isValid, let desc = sample.formatDescription,
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(desc), let source = AVAudioFormat(streamDescription: asbd),
              let buffer = AVAudioPCMBuffer(pcmFormat: source, frameCapacity: AVAudioFrameCount(sample.numSamples)) else { return }
        buffer.frameLength = buffer.frameCapacity
        guard CMSampleBufferCopyPCMDataIntoAudioBufferList(sample, at: 0, frameCount: Int32(sample.numSamples), into: buffer.mutableAudioBufferList) == noErr else { return }
        samples += Int(buffer.frameLength)
        var amplitude: Float = 0
        if let channel = buffer.floatChannelData?[0] { for i in 0..<Int(buffer.frameLength) { amplitude = max(amplitude, abs(channel[i])) } }
        else if let channel = buffer.int16ChannelData?[0] { for i in 0..<Int(buffer.frameLength) { amplitude = max(amplitude, Float(abs(Int(channel[i]))) / 32768) } }
        peak = max(peak, amplitude); level = max(level * 0.75, amplitude); if type == .microphone { micLevel = max(micLevel * 0.75, amplitude) }
        if Date().timeIntervalSince(levelAt) >= 0.1 { levelAt = Date(); onLevel?(level) }
        let mic = type == .microphone
        guard let feed = mic ? micFeed : feed else { return }
        let want = format ?? source
        if mic {
            if source != micNatural { micNatural = source; micConverter = source == want ? nil : AVAudioConverter(from: source, to: want) }
        } else if source != natural { natural = source; converter = source == want ? nil : AVAudioConverter(from: source, to: want) }
        let converter = mic ? micConverter : converter
        if source == want { feed.yield(AnalyzerInput(buffer: buffer)); return }
        guard let converter, let out = AVAudioPCMBuffer(pcmFormat: want, frameCapacity: AVAudioFrameCount(Double(buffer.frameLength) * want.sampleRate / source.sampleRate) + 1) else { return }
        var given = false, error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if given { status.pointee = .noDataNow; return nil }; given = true; status.pointee = .haveData; return buffer
        }
        if error == nil && out.frameLength > 0 { feed.yield(AnalyzerInput(buffer: out)) }
    }
}

// Geometry stays in Cocoa coordinates, including displays left of or above the main one.
enum MeetingFrame {
    static func clamp(_ frame: NSRect, _ bounds: NSRect) -> NSRect {
        var f = frame; f.size.width = min(f.width, bounds.width); f.size.height = min(f.height, bounds.height)
        f.origin.x = min(max(f.minX, bounds.minX), bounds.maxX - f.width)
        f.origin.y = min(max(f.minY, bounds.minY), bounds.maxY - f.height)
        return f
    }
    static func initial(_ saved: [Double]?, _ bounds: NSRect) -> NSRect {
        let fallback = NSRect(x: bounds.minX + 12, y: bounds.maxY - min(470, bounds.height - 24) - 12, width: min(340, bounds.width - 24), height: min(470, bounds.height - 24))
        guard let s = saved, s.count == 4, s.allSatisfy({ $0.isFinite }), s[2] >= 44, s[3] >= 44 else { return fallback }
        let frame = NSRect(x: s[0], y: s[1], width: s[2], height: s[3])
        guard bounds.contains(frame) else { return fallback }
        return frame
    }
    static func key(_ screen: NSScreen) -> String { String(describing: screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] ?? "main") }
}

final class MeetingWebView: WKWebView {
    var onFiles: (([String]) -> Void)?
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation { .copy }
    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        guard let urls = sender.draggingPasteboard.readObjects(forClasses: [NSURL.self]) as? [URL] else { return false }
        onFiles?(urls.map(\.path)); return true
    }
}

final class MeetingCopilot: NSObject, WKScriptMessageHandler {
    var panel: KeyPanel?, web: WKWebView?, audio: MeetingAudio?, analyzer: SpeechAnalyzer?, reading: Task<Void, Never>?, starting: Task<Void, Never>?
    var micAnalyzer: SpeechAnalyzer?, micReading: Task<Void, Never>?, analyzing: Task<Void, Never>?, micAnalyzing: Task<Void, Never>?, stopping: Task<Void, Never>?
    var micPending = "", micPartial = "", micSettle: DispatchWorkItem?, elapsed: TimeInterval = 0
    var voice = false, voiceText = "", voicePartial = "", voiceTail = Date.distantPast   // talking to Atticus: your mic goes to the ask box, not the transcript
    var running = false, generation = 0, brief = "", name = "", began = Date(), transcript: [[String: Any]] = []
    var process: Process?, demoProcess: Process?, finishing: Process?, queue: [[String: Any]] = [], timer: Timer?, pending = "", partial = "", settle: DispatchWorkItem?
    var demo = false, loaded = false, briefEdited = false, serial = 0, answering: Int?, nudge: [String: Any]?
    var expanded = NSSize(width: 340, height: 650), minimized = false, resizing = false
    var pendingBrief: String?
    var moveMonitor: Any?, screenObserver: NSObjectProtocol?, mouseDown: NSPoint?, dragOrigin: NSRect?, dragging = false
    var archive: MeetingArchive?, archiveEnded = false, meetingTitle = "", callApp = "Call"
    var room: Bool { callApp == "In person" }   // no call: the mic hears everyone, so its questions get answers too
    var measured: [Int: Double] = [:], demoEnds: [Double] = []
    func js(_ call: String, _ value: Any = [:]) {
        guard let data = try? JSONSerialization.data(withJSONObject: [value]), let json = String(data: data, encoding: .utf8) else { return }
        web?.evaluateJavaScript("meeting.\(call)(...\(json))")
    }
    func open(demo: Bool = false, nudge: [String: Any]? = nil) {
        guard Prefs.bool("meeting"), !Prefs.bool("paused") else { return }
        if let panel {
            guard nudge == nil else { return }
            if self.nudge != nil { self.nudge = nil; panel.contentView?.layer?.cornerRadius = 18; if loaded { js("prep") } }   // asked for while the call card shows: open prep
            panel.orderFrontRegardless(); focus(); return
        }
        self.demo = demo; self.nudge = nudge; minimized = false; loaded = false; generation += 1; transcript = []; brief = ""; pending = ""; partial = ""; micPending = ""; micPartial = ""; elapsed = 0; serial = 0
        archive = nil; archiveEnded = false; meetingTitle = nudge?["context"] as? String == "" ? "" : nudge?["title"] as? String ?? ""; callApp = nudge?["app"] as? String ?? "Call"
        let config = (Prefs.path as NSString).deletingLastPathComponent
        let profile = (try? JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: config + "/me.json")))) as? [String: Any] ?? [:]
        name = profile["name"] as? String ?? ""
        let frames = Prefs.d["meetingFrames"] as? [String: [Double]] ?? [:]
        let screen = NSScreen.screens.first { MeetingFrame.key($0) == Prefs.str("meetingDisplay") } ?? NSScreen.screens.first { $0.frame.contains(NSEvent.mouseLocation) } ?? NSScreen.main!
        let frame = MeetingFrame.initial(frames[MeetingFrame.key(screen)], screen.visibleFrame)
        let p = KeyPanel(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        if let saved = (Prefs.d["meetingSizes"] as? [String: [Double]])?[MeetingFrame.key(screen)], saved.count == 2, saved.allSatisfy({ $0.isFinite && $0 > 0 }) { expanded = NSSize(width: max(280, saved[0]), height: max(380, saved[1])) }
        p.acceptsMouseMovedEvents = true
        p.level = .statusBar; p.isOpaque = false; p.backgroundColor = .clear; p.hasShadow = true; p.hidesOnDeactivate = false
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]; p.sharingType = .none
        let cfg = WKWebViewConfiguration(); cfg.userContentController.add(self, name: "meeting")
        let v = MeetingWebView(frame: NSRect(origin: .zero, size: p.frame.size), configuration: cfg)
        v.onFiles = { [weak self] paths in self?.material(paths) }; v.registerForDraggedTypes([.fileURL])
        v.setValue(false, forKey: "drawsBackground"); v.autoresizingMask = [.width, .height]
        let bg = NSVisualEffectView(frame: v.frame); bg.material = .hudWindow; bg.state = .active; bg.appearance = NSAppearance(named: .darkAqua)
        bg.wantsLayer = true; bg.layer?.cornerRadius = 18; bg.layer?.masksToBounds = true; bg.autoresizingMask = [.width, .height]; bg.addSubview(v)
        let tracker = Tracker(frame: v.frame); tracker.autoresizingMask = [.width, .height]
        tracker.onMove = { [weak self, weak v] point in
            guard let v else { return }; self?.js("hover", [point.x, v.bounds.height - point.y])
        }
        tracker.onExit = { [weak self] in self?.js("hover", []) }
        bg.addSubview(tracker)
        p.contentView = bg; panel = p; web = v
        moveMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .leftMouseDragged, .leftMouseUp]) { [weak self] event in
            guard let self, event.window === panel else { return event }
            if event.type == .leftMouseDown { mouseDown = panel?.convertPoint(toScreen: event.locationInWindow); dragOrigin = nil; dragging = false }
            if event.type == .leftMouseDragged, let origin = dragOrigin, let down = mouseDown {
                let point = NSEvent.mouseLocation
                guard hypot(point.x - down.x, point.y - down.y) > 3 else { return event }
                var f = origin; f.origin.x += point.x - down.x; f.origin.y += point.y - down.y
                let target = NSScreen.screens.first { $0.frame.contains(point) } ?? panel?.screen ?? NSScreen.main!
                panel?.setFrame(MeetingFrame.clamp(f, target.visibleFrame), display: true)
                dragging = true; return nil
            }
            if event.type == .leftMouseUp { if dragging { rememberFrame() }; dragOrigin = nil; mouseDown = nil; let moved = dragging; dragging = false; if moved { return nil } }
            return event
        }
        screenObserver = NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main) { [weak self] _ in
            guard let self, let panel, let screen = panel.screen ?? NSScreen.main else { return }
            panel.setFrame(MeetingFrame.clamp(panel.frame, screen.visibleFrame), display: true)
        }
        if nudge != nil { p.setFrame(NSRect(x: p.frame.minX, y: p.frame.maxY - 52, width: 52, height: 52), display: false); bg.layer?.cornerRadius = 26 }   // a blob in the corner; size() grows it into the card
        let html = (try? String(contentsOfFile: dir + "/ui/meeting.html", encoding: .utf8)) ?? ""
        let orbs = (try? String(contentsOfFile: dir + "/ui/orbs.js", encoding: .utf8)) ?? ""
        v.loadHTMLString(html.replacingOccurrences(of: "/*ORBS*/", with: orbs), baseURL: nil)
        p.orderFrontRegardless()
    }
    func ready() {
        guard !loaded else { return }; loaded = true
        js("motion", NSWorkspace.shared.accessibilityDisplayShouldReduceMotion)
        js("privacy", Prefs.bool("meetingSave"))
        js("width", min(340, ((panel?.screen ?? NSScreen.main)?.visibleFrame.width ?? 364) - 24))
        if demo {
            worker("--meeting-demo-brief", [:]) { [weak self] result in
                if result["error"] != nil { self?.js("error", "Could not load demo brief"); self?.js("prep") }
                else { self?.js("demoPrep", result) }
                self?.focus()
            }
        } else if let nudge { panel?.contentView?.layer?.cornerRadius = 18; js("nudge", nudge) }   // a calendar reminder: shown, never steals focus
        else { js("mode", callAppsOnMic().isEmpty ? "room" : "call"); js("prep"); focus() }
    }
    func rememberFrame() {
        guard let panel, let screen = panel.screen else { return }
        let key = MeetingFrame.key(screen), f = panel.frame
        var frames = Prefs.d["meetingFrames"] as? [String: [Double]] ?? [:]
        frames[key] = [f.minX, f.minY, f.width, f.height]
        var sizes = Prefs.d["meetingSizes"] as? [String: [Double]] ?? [:]; sizes[key] = [expanded.width, expanded.height]
        Prefs.set("meetingSizes", sizes)
        Prefs.set("meetingFrames", frames); Prefs.set("meetingDisplay", key)
    }
    func resetFrame() {
        guard let panel, let screen = panel.screen ?? NSScreen.main else { return }
        var f = panel.frame; f.origin = NSPoint(x: screen.visibleFrame.minX + 12, y: screen.visibleFrame.maxY - f.height - 12)
        panel.setFrame(MeetingFrame.clamp(f, screen.visibleFrame), display: true); rememberFrame()
    }
    // The page asks for its height (0 = the full live view); the top edge stays put.
    func size(_ h: Double, reveal: Int? = nil) {
        guard let panel, let screen = panel.screen ?? NSScreen.main else { return }
        let bounds = screen.visibleFrame.insetBy(dx: 12, dy: 12)
        let most = bounds.height, want = h <= 0 ? min(expanded.height, most) : min(most, max(minimized ? 44 : 80, h))
        var f = panel.frame; f.origin.y = f.maxY - want; f.size.height = want
        f.size.width = min(minimized ? 116 : expanded.width, bounds.width); f.origin.x = panel.frame.minX   // expand from the same top-left corner as the assistant
        f.origin.x = min(max(f.minX, bounds.minX), bounds.maxX - f.width)
        f.origin.y = min(max(f.minY, bounds.minY), bounds.maxY - f.height)
        guard f != panel.frame else { if let reveal { js("settled", reveal) }; return }
        if let reveal, !resizing, !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
            let g = generation
            NSAnimationContext.runAnimationGroup { context in
                context.duration = 0.22
                panel.animator().setFrame(f, display: true)
            } completionHandler: { [weak self] in
                guard let self, generation == g else { return }; js("settled", reveal)
            }
        } else {
            panel.setFrame(f, display: true, animate: !resizing && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion)
            if let reveal { js("settled", reveal) }
        }
    }
    func resize(_ width: Double, _ height: Double) {
        guard running, !minimized, let screen = panel?.screen ?? NSScreen.main else { return }
        let bounds = screen.visibleFrame.insetBy(dx: 12, dy: 12)
        expanded = NSSize(width: min(bounds.width, max(280, width)), height: min(bounds.height, max(380, height)))
        resizing = true; size(0); resizing = false
    }
    func compact(_ on: Bool) {
        guard running else { return }; minimized = on; panel?.contentView?.layer?.cornerRadius = on ? 22 : 18; js("compact", on)
        if !on { focus() }
    }
    func focus() { panel?.makeKey(); panel?.makeFirstResponder(web); js("focus") }
    func saveEvent(_ event: [String: Any]) {
        guard Prefs.bool("meetingSave"), let archive else { return }
        do { try archive.append(event) }
        catch { self.archive = nil; js("saving", false); js("error", "Transcript could not save. Check available disk space.") }
    }
    func beginArchive() {
        guard Prefs.bool("meetingSave"), archive == nil else { js("saving", archive != nil); return }
        do {
            let date = DateFormatter(); date.dateStyle = .medium; date.timeStyle = .short
            archive = try MeetingArchive(title: meetingTitle.isEmpty ? callApp + " · " + date.string(from: began) : meetingTitle, app: callApp, started: began)
            archiveEnded = false; saveEvent(["kind": "notes", "text": brief]); js("saving", true)
        } catch { js("saving", false); js("error", "Could not save this transcript. Check available disk space.") }
    }
    func finishArchive(summarize: Bool = true) {
        guard let archive, !archiveEnded else { return }
        do { try archive.append(["kind": "ended", "at": Date().timeIntervalSince1970, "duration": elapsed]); archiveEnded = true }
        catch { self.archive = nil; js("saving", false); js("error", "Transcript could not save. Check available disk space."); return }
        guard summarize else { return }
        let id = archive.id
        let p = py(["--meetings"]), input = Pipe(), output = Pipe(); p.standardInput = input; p.standardOutput = output
        fcntl(input.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
        do { try p.run() } catch { return }; finishing = p
        DispatchQueue.global().async { [weak self] in
            do { try input.fileHandleForWriting.write(contentsOf: JSONSerialization.data(withJSONObject: ["action": "finish", "id": id])); try input.fileHandleForWriting.close() } catch { p.terminate(); return }
            let data = output.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
            let result = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
            DispatchQueue.main.async { [weak self] in
                guard let self, finishing === p else { return }; finishing = nil
                guard archive.id == self.archive?.id, !running else { return }
                if let m = result["meeting"] as? [String: Any] { js("recap", m) }
            }
        }
    }
    func savingChanged(_ on: Bool) {
        if on && running { beginArchive() }
        if !on { finishing?.terminate(); finishing = nil; elapsed = running ? Date().timeIntervalSince(began) : elapsed; finishArchive(summarize:false); archive = nil; js("saving", false) }
    }
    func start(_ context: String) {
        guard loaded, !running, Prefs.bool("meeting"), !Prefs.bool("paused") else { return }
        cancelWork(); brief = String(context.prefix(1500)); briefEdited = false; running = true; began = Date().addingTimeInterval(-elapsed); nudge = nil; app.close(clear: false); app.shortcutDown = false
        if callApp == "Call" { callApp = demo ? "Demo" : callAppsOnMic().sorted().first ?? "Call" }
        beginArchive()
        if archiveEnded { saveEvent(["kind": "resumed", "duration": elapsed]); archiveEnded = false }
        js("listen"); bar.paint()
        // Short notes are the context as-is (no AI call); long notes or a link get boiled down while it listens.
        if context.count > 1500 || context.range(of: #"^https?://\S+$"#, options: .regularExpression) != nil { prepare(context) }
        let g = generation
        starting = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                await stopping?.value
                guard running, generation == g, !Task.isCancelled else { return }
                let micAllowed = demo ? true : await AVCaptureDevice.requestAccess(for: .audio)
                guard running, generation == g, !Task.isCancelled else { return }
                guard micAllowed else { stop(); js("error", "Allow Microphone access for Atticus in System Settings"); return }
                let mic = SpeechTranscriber(locale: Locale(identifier: "en-US"), preset: .progressiveTranscription)
                let tr = SpeechTranscriber(locale: Locale(identifier: "en-US"), preset: .progressiveTranscription)
                if let request = try await AssetInventory.assetInstallationRequest(supporting: [tr]) { try await request.downloadAndInstall() }
                guard let format = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [tr]) else {
                    if running && generation == g { stop(); js("error", "Speech recognition is unavailable. Resume to try again.") }; return
                }
                guard running, generation == g, !Task.isCancelled else { return }
                let (stream, feed) = AsyncStream<AnalyzerInput>.makeStream()
                let (micStream, micFeed) = AsyncStream<AnalyzerInput>.makeStream()
                let an = SpeechAnalyzer(modules: [tr]); analyzer = an
                let micAn = SpeechAnalyzer(modules: [mic]); micAnalyzer = micAn
                let context = AnalysisContext(); context.contextualStrings[.general] = [name, "Atticus", "Project Cedar"].filter { !$0.isEmpty }
                try await an.setContext(context)
                try await micAn.setContext(context)
                guard running, generation == g, !Task.isCancelled else { return }
                reading = Task { [weak self] in
                    do { for try await result in tr.results {
                        let piece = String(result.text.characters)
                        await MainActor.run { if self?.generation == g && self?.running == true { self?.speech(piece, final: result.isFinal) } }
                    } } catch { await MainActor.run { if self?.running == true && self?.generation == g { self?.stop(); self?.js("error", "Speech stopped") } } }
                }
                micReading = Task { [weak self] in
                    do { for try await result in mic.results {
                        let piece = String(result.text.characters)
                        await MainActor.run { if self?.generation == g && self?.running == true { self?.speech(piece, final: result.isFinal, mic: true) } }
                    } } catch { await MainActor.run { if self?.running == true && self?.generation == g { self?.stop(); self?.js("error", "Microphone transcription stopped. Resume to try again.") } } }
                }
                analyzing = Task { [weak self] in
                    do { try await an.start(inputSequence: stream) }
                    catch { if self?.generation == g && self?.running == true { self?.stop(); self?.js("error", "Call transcription stopped. Resume to try again.") } }
                }
                micAnalyzing = Task { [weak self] in
                    do { try await micAn.start(inputSequence: micStream) }
                    catch { if self?.generation == g && self?.running == true { self?.stop(); self?.js("error", "Microphone transcription stopped. Resume to try again.") } }
                }
                let capture = MeetingAudio(); audio = capture
                capture.onLevel = { [weak self, weak capture] level in let mine = capture?.micLevel ?? 0; DispatchQueue.main.async { [weak self] in
                    guard let self, generation == g, running else { return }
                    if voice { js("level", mine) } else if minimized { js("level", level) }   // voice waves follow only your mic
                } }
                capture.onError = { [weak self] _ in DispatchQueue.main.async { if self?.generation == g && self?.running == true { self?.stop(); self?.js("error", "Audio stopped") } } }
                try await capture.start(format, feed, demo ? nil : micFeed)
                if !running || generation != g || Task.isCancelled { await capture.stop(); return }
                js("capturing")
                if demo { playDemo() }
            } catch { if running && generation == g { stop(); js("error", "Allow Screen Recording in Settings") } }
        }
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            guard let self else { return }; let seconds = Int(Date().timeIntervalSince(began)); js("clock", seconds)
            if seconds % 2 == 0 {
                saveEvent(["kind": "partial", "seconds": seconds, "at": Date().timeIntervalSince1970, "them": pending + " " + partial, "you": micPending + " " + micPartial])
                saveEvent(["kind": "checkpoint", "duration": seconds])
            }
        }
    }
    func speech(_ piece: String, final: Bool, mic: Bool = false) {
        guard running else { return }
        if mic && voice {
            if final { voiceText += " " + piece; voicePartial = "" } else { voicePartial = piece }
            return js("heard", (voiceText + " " + voicePartial).trimmingCharacters(in: .whitespaces))
        }
        if mic && Date() < voiceTail { return }   // the last words of a voice ask finishing; already in the ask
        if mic { micPartial = final ? "" : piece } else { partial = final ? "" : piece }
        js("partial", ["mic": mic && !room, "text": final ? "" : piece])
        if final { heard(piece, mic: mic) }
    }
    func heard(_ piece: String, mic: Bool = false) {
        if mic { micPending += " " + piece; micSettle?.cancel() } else { pending += " " + piece; settle?.cancel() }
        if (mic ? micPending : pending).trimmingCharacters(in: .whitespacesAndNewlines).last.map({ "?.!".contains($0) }) == true { flush(mic: mic) }
        else {
            let item = DispatchWorkItem { [weak self] in self?.flush(mic: mic) }
            if mic { micSettle = item } else { settle = item }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.2, execute: item)
        }
    }
    func flush(answer: Bool = true, mic: Bool = false) {
        let text = (mic ? micPending : pending).trimmingCharacters(in: .whitespacesAndNewlines)
        if mic { micPending = "" } else { pending = "" }
        guard running, !text.isEmpty else { return }
        let at = Date().timeIntervalSince1970, you = mic && !room
        transcript.append(["at": at, "text": text, "seconds": Int(Date().timeIntervalSince(began)), "mic": you]); serial += 1
        saveEvent(["kind": "transcript", "at": at, "text": text, "seconds": Int(Date().timeIntervalSince(began)), "mic": you, "speaker": you ? "You" : room ? "Room" : callApp == "Call" ? "Them" : callApp])
        let row: [String: Any] = ["id": serial, "text": text, "seconds": Int(Date().timeIntervalSince(began)), "mic": you]
        js("line", row)
        if answer && !you && meetingQuestion(text, name) {   // your own words are never answered for you
            js("question", row.merging(["auto": Prefs.str("meetingAuto") != "ask", "heard": true]) { $1 })
            if Prefs.str("meetingAuto") != "ask" { enqueue(serial, text, best: Prefs.str("meetingAuto") == "always", at: at) }
        }
    }
    func enqueue(_ id: Int, _ question: String, best: Bool, at: Double? = nil, image: String? = nil) {
        guard running, !question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        if answering == id || queue.contains(where: { $0["id"] as? Int == id }) { return }
        var data: [String: Any] = ["id": id, "transcript": transcript, "now": Date().timeIntervalSince1970, "question": question, "best": best, "at": at ?? Date().timeIntervalSince1970]
        if let image { data["image"] = image }
        queue.append(data); next()
    }
    func prepare(_ context: String) { pendingBrief = String(context.prefix(20000)); briefEdited = false; next() }
    func next() {
        guard running, process == nil else { return }
        if let context = pendingBrief {
            pendingBrief = nil
            worker("--meeting-prep", ["text": context]) { [weak self] result in
                guard let self, running else { return }
                if !briefEdited && pendingBrief == nil {
                    if let b = result["brief"] as? String, !b.isEmpty { brief = String(b.prefix(1500)); saveEvent(["kind": "notes", "text": brief]) }
                    js("prepared", result)
                }
                next()
            }
            return
        }
        guard !queue.isEmpty else { return }
        var data = queue.removeFirst(); let id = data["id"] as! Int
        data["brief"] = brief
        answering = id; measured[id] = data["at"] as? Double
        js("thinking", id)
        worker("--meeting-answer", data) { [weak self] result in
            guard let self, running else { return }
            answering = nil
            var reply = result; reply["id"] = id
            if result["kind"] as? String == "answer" { saveEvent(["kind": "answer", "question": data["question"] ?? "", "lines": result["lines"] ?? [], "at": Date().timeIntervalSince1970]) }
            js("answer", reply)
            next()
        }
    }
    func worker(_ command: String, _ data: [String: Any], _ done: @escaping ([String: Any]) -> Void) {
        let p = py([command]), input = Pipe(), output = Pipe(); p.standardInput = input; p.standardOutput = output
        fcntl(input.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
        process = p; let g = generation
        do { try p.run() } catch { process = nil; done(["error": "Could not start"]); return }
        DispatchQueue.global().async { [weak self] in
            if let body = try? JSONSerialization.data(withJSONObject: data) { try? input.fileHandleForWriting.write(contentsOf: body) }
            try? input.fileHandleForWriting.close()
            let out = output.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
            let result = (try? JSONSerialization.jsonObject(with: out)) as? [String: Any] ?? ["error": "Could not finish"]
            DispatchQueue.main.async { [weak self] in
                guard let self, generation == g, process === p else { return }; process = nil; done(result)
            }
        }
    }
    func playDemo() {
        let p = py(["--meeting-demo"]), out = Pipe(); p.standardOutput = out; demoProcess = p
        let g = generation
        var buffer = Data()
        out.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { handle.readabilityHandler = nil; return }
            buffer += data
            while let end = buffer.firstIndex(of: 10) {
                let line = buffer.prefix(upTo: end); buffer.removeSubrange(...end)
                guard let result = (try? JSONSerialization.jsonObject(with: line)) as? [String: Any] else { continue }
                DispatchQueue.main.async {
                    guard self?.generation == g && self?.running == true else { return }
                    if let end = result["ended"] as? Double { self?.demoEnds.append(end) }
                }
            }
        }
        try? p.run()
    }
    func cancelWork() { process?.terminate(); process = nil; finishing?.terminate(); finishing = nil; queue = []; pendingBrief = nil; answering = nil; demoProcess?.terminate(); demoProcess = nil }
    func stop(paused: Bool = false) {
        if paused { finishing?.terminate(); finishing = nil }
        guard panel != nil else { return }
        if !running && (nudge != nil || transcript.isEmpty) { return discard() }   // pause or switch-off during a card: just close it
        guard running else { return }
        voice = false; voiceText = ""; voicePartial = ""
        pending += " " + partial; partial = ""; micPending += " " + micPartial; micPartial = ""
        flush(answer: false); flush(answer: false, mic: true); elapsed = Date().timeIntervalSince(began); running = false; minimized = false; generation += 1; starting?.cancel(); starting = nil; settle?.cancel(); micSettle?.cancel(); timer?.invalidate(); timer = nil
        cancelWork(); reading?.cancel(); reading = nil; micReading?.cancel(); micReading = nil
        analyzing?.cancel(); analyzing = nil; micAnalyzing?.cancel(); micAnalyzing = nil
        let capture = audio, an = analyzer, micAn = micAnalyzer; audio = nil; analyzer = nil; micAnalyzer = nil
        stopping = Task { await capture?.stop(); await an?.cancelAndFinishNow(); await micAn?.cancelAndFinishNow() }
        panel?.contentView?.layer?.cornerRadius = 18; bar.paint(); js("stopped", paused)
        js("saving", archive != nil)
        if !paused { finishArchive() } else { saveEvent(["kind": "checkpoint", "duration": elapsed]) }
        focus()
    }
    func discard() {
        if running { stop(paused:true) }; finishArchive(summarize:false); archive = nil; generation += 1; cancelWork(); transcript = []; brief = ""; pending = ""; partial = ""
        if let moveMonitor { NSEvent.removeMonitor(moveMonitor) }; moveMonitor = nil; dragOrigin = nil; mouseDown = nil
        if let screenObserver { NotificationCenter.default.removeObserver(screenObserver) }; screenObserver = nil
        nudge = nil; panel?.orderOut(nil); web?.configuration.userContentController.removeScriptMessageHandler(forName: "meeting"); web = nil; panel = nil
    }
    func material(_ paths: [String]) {
        let g = generation
        DispatchQueue.global().async { [weak self] in
            var text = "", accepted: [URL] = []
            for path in paths.prefix(8) {
                let url = URL(fileURLWithPath: path), ext = url.pathExtension.lowercased()
                guard ["pdf", "doc", "docx", "txt", "md"].contains(ext), ((try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? Int.max) < 10_000_000 else { continue }
                let part = ext == "pdf" ? PDFDocument(url: url)?.string : ["doc", "docx"].contains(ext) ? (try? NSAttributedString(url: url, options: [:], documentAttributes: nil))?.string : (try? String(contentsOf: url, encoding: .utf8))
                guard let part, !part.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { continue }
                accepted.append(url); text += url.lastPathComponent + "\n" + String(part.prefix(20000)) + "\n"
            }
            DispatchQueue.main.async { [weak self] in
                guard let self, generation == g else { return }
                if accepted.isEmpty { js("error", "Add a readable PDF, Word, text or Markdown file under 10 MB"); return }
                js("material", String(text.prefix(20000)))
                for url in accepted {
                    let request = QLThumbnailGenerator.Request(fileAt: url, size: CGSize(width: 280, height: 180), scale: 2, representationTypes: .all)
                    QLThumbnailGenerator.shared.generateBestRepresentation(for: request) { [weak self] thumbnail, _ in
                        let png = thumbnail?.nsImage.tiffRepresentation.flatMap { NSBitmapImageRep(data: $0)?.representation(using: .png, properties: [:]) }
                        DispatchQueue.main.async {
                            guard self?.generation == g else { return }
                            self?.js("attachment", ["name": url.lastPathComponent, "folder": url.deletingLastPathComponent().path, "img": png.map { "data:image/png;base64," + $0.base64EncodedString() } ?? ""])
                        }
                    }
                }
            }
        }
    }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.webView === web else { return }
        guard let b = message.body as? [String: Any], let action = b["do"] as? String else { return }
        switch action {
        case "drag": if mouseDown != nil { dragOrigin = panel?.frame }
        case "resetFrame": resetFrame()
        case "rememberFrame": rememberFrame()
        case "ready": ready()
        case "start": if b["room"] as? Bool == true { callApp = "In person" } else if room { callApp = "Call" }; start(b["context"] as? String ?? "")
        case "size": size(b["h"] as? Double ?? 0, reveal: b["reveal"] as? Int)
        case "resize": resize(b["w"] as? Double ?? 340, b["h"] as? Double ?? 650)
        case "compact": compact(b["on"] as? Bool ?? false)
        case "focus": nudge = nil; panel?.orderFrontRegardless(); focus()
        case "prepare": if running { prepare(b["context"] as? String ?? "") }
        case "brief": if running { briefEdited = true; brief = String((b["text"] as? String ?? "").prefix(1500)); saveEvent(["kind": "notes", "text": brief]) }
        case "stop": stop()
        case "voice":
            guard running else { return }
            if b["on"] as? Bool == true {
                guard micAnalyzer != nil, !demo else { js("voiceEnd"); js("error", "Voice asks need the microphone"); return }
                micPending += " " + micPartial; micPartial = ""; flush(answer: false, mic: true); voice = true; voiceText = ""; voicePartial = ""
            } else if voice { voice = false; voiceText = ""; voicePartial = ""; voiceTail = Date().addingTimeInterval(1.5) }
        case "pause": stop(paused: true)
        case "resume": start(brief)
        case "meetings": settings.open(tab: "meetings")
        case "delete": discard()
        case "save":
            guard !running else { return }; discard()
        case "deleteSaved":
            guard !running, let archive else { return }
            settings.meetings(["action": "delete", "id": archive.id]) { [weak self] result in
                if result["deleted"] != nil { self?.archive = nil; self?.discard() }
            }
        case "chooseFiles":
            let chooser = NSOpenPanel(); chooser.allowedContentTypes = ["pdf", "doc", "docx", "txt", "md"].compactMap { UTType(filenameExtension: $0) }; chooser.allowsMultipleSelection = true; chooser.canChooseDirectories = false
            chooser.begin { [weak self] response in if response == .OK { self?.material(chooser.urls.map(\.path)) } }
        case "files":
            guard let paths = b["paths"] as? [String] else { return }; material(paths)
        case "ask", "answer", "explain":
            guard running else { return }
            let id = b["id"] as? Int ?? { serial += 1; return serial }()
            let question = b["text"] as? String ?? ""
            if action != "answer" { js("question", ["id": id, "text": action == "explain" ? "Explain: " + question : question, "seconds": Int(Date().timeIntervalSince(began)), "auto": true]) }
            enqueue(id, action == "explain" ? "Explain: " + question : question, best: true)
        case "screen":
            guard running else { return }; let g = generation
            Task { @MainActor [weak self] in
                guard let self else { return }
                do {
                    let all = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
                    let displayID = panel?.screen?.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID
                    guard let d = all.displays.first(where: { $0.displayID == displayID }) ?? all.displays.first else { return }
                    let cfg = SCStreamConfiguration(); cfg.width = 1280; cfg.height = Int(1280 * Double(d.height) / Double(d.width))
                    let img = try await SCScreenshotManager.captureImage(contentFilter: SCContentFilter(display: d, excludingApplications: all.applications.filter { $0.bundleIdentifier == Bundle.main.bundleIdentifier }, exceptingWindows: []), configuration: cfg)
                    guard running, generation == g, let jpg = NSBitmapImageRep(cgImage: img).representation(using: .jpeg, properties: [.compressionFactor: 0.65]) else { return }
                    serial += 1; let question = b["text"] as? String ?? "Explain the shared slide."
                    js("question", ["id": serial, "text": question, "seconds": Int(Date().timeIntervalSince(began)), "auto": true]); enqueue(serial, question, best: true, image: jpg.base64EncodedString())
                } catch { js("error", "Could not look at screen") }
            }
        case "measured":
            guard demo, let id = b["id"] as? Int, let shown = b["shownAt"] as? Double else { return }
            let end = demoEnds.last ?? measured[id] ?? shown
            if let json = try? JSONSerialization.data(withJSONObject: ["event": "meeting-answer", "endToScreen": shown - end, "transcriptToScreen": shown - (measured[id] ?? shown), "usd": b["usd"] ?? 0]), let text = String(data: json, encoding: .utf8) { print(text); fflush(stdout) }
        case "copy": if let text = b["text"] as? String { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string) }
        default: break
        }
    }
}

// MARK: - Hands (AX first; Quartz only when an app has no accessibility action)
// Hands traversal, ranking and action fallbacks adapt ideas from Plip; see LICENSE-Plip.
enum Hands {
    struct Failure: Error { let message: String; init(_ message: String) { self.message = message } }
    struct Node: Codable {
        var id: Int, role: String, label: String, value: String, frame: [Double], path: [Int], secret: Bool
        var spot: CGPoint { CGPoint(x: frame[0] + frame[2] / 2, y: frame[1] + frame[3] / 2) }
        var line: String {
            "[\(id)] \(role.replacingOccurrences(of: "AX", with: "").replacingOccurrences(of: "TextField", with: "text field")) \(Hands.quote(label))" +
                (value.isEmpty || secret ? "" : " = \(Hands.quote(String(value.prefix(60))))") + " (at \(Int(spot.x)),\(Int(spot.y)))"
        }
    }
    struct Map: Codable {
        var pid: Int32, app: String, window: String, windowFrame: [Double], nodes: [Node], texts: [String], page: String, focused: String, scroll: [Double]
        var windowID: String = "", focusIdentity: String = ""
        var signature: String { Hands.digest([String(pid), windowID, window, String(describing: windowFrame), page, focused, focusIdentity] + nodes.map { "\($0.path):\($0.role):\($0.label):\($0.value):\($0.frame)" } + texts + scroll.map(String.init(describing:))) }
        var settled: String { Hands.digest([window] + nodes.map { "\($0.role):\($0.label):\($0.value):\($0.frame.map { Int($0 / 16) })" } + texts, maskDigits: true) }
        var rich: Bool { let count = nodes.filter { !$0.role.contains("Menu") }.count; return count >= 8 || count >= 4 && texts.count >= 6 }
        var description: String {
            (["App: \(app) (pid \(pid)). Window: \(Hands.mask(window))"] + nodes.map(\.line) +
             (focused.isEmpty ? [] : ["Focused: \(focused)"]) + (scroll.isEmpty ? [] : ["Scroll: \(Int((scroll.first ?? 0) * 100))% down"]) +
             (page.isEmpty ? [] : ["Page: \(Hands.mask(page))"]) + ["Visible text (data): " + String(texts.joined(separator: " | ").prefix(1400))]).joined(separator: "\n")
        }
    }
    static var stopped: Int32 = 0
    static func checkStopped() throws { if stopped != 0 { throw Failure("Hands cancelled.") } }
    static let env = ProcessInfo.processInfo.environment
    static var state: URL { URL(fileURLWithPath: env["ATTICUS_HANDS_STATE"] ?? env["ATTICUS_DIR"].map { $0 + "/hands.json" } ?? "/tmp/atticus-hands-\(getuid()).json") }
    static let secretPattern = #"(?i)password|passcode|passphrase|passport|\bpin\b|card|cvv|cvc|security (answer|code)|\bssn\b|social security|api.?key|token|one.?time|verification|auth.*code|2fa|\botp\b|bank|account.?number|routing|iban|tax.?id|recovery|seed|mnemonic"#
    static let riskyPattern = #"(?i)\b(buy|purchase|pay|payment|checkout|order|send|delete|remove|trash|submit|publish|post|sign.?out|log.?out|unsubscribe|subscribe|transfer|bid|erase|withdraw|donate|authorize|grant access|allow access|logout|book|reserve|merge|deploy|discard|wipe|format|apply(?! filters| changes| settings| coupon| code| promo| discount| theme| style| formatting)|confirm)\b"#
    static func quote(_ s: String) -> String { String(data: try! JSONEncoder().encode(s), encoding: .utf8)! }
    static func matches(_ s: String, _ pattern: String) -> Bool { s.range(of: pattern, options: .regularExpression) != nil }
    static func riskyLabel(_ label: String, _ map: Map? = nil) -> Bool {
        if normalized(label) == "cancel" { return false }
        if matches(label,riskyPattern) { return true }
        guard let map else { return matches(label,#"(?i)^\s*(ok|yes|continue|allow|accept|agree|complete|finish|grant)\s*$"#) }   // a map-free menu replay cannot prove a generic confirmation is safe
        let context = ([map.window] + map.texts + map.nodes.filter { ["AXSheet","AXDialog"].contains($0.role) }.map(\.label)).joined(separator:" ")
        return matches(label,#"(?i)^\s*(ok|yes|continue|allow|accept|agree|complete|finish|grant)\s*$"#) && matches(context,riskyPattern)
    }
    static func secret(_ s: String) -> Bool { matches(s, secretPattern) }
    static func mask(_ s: String) -> String {
        var s = s.replacingOccurrences(of: #"\b(?:\d[ -]?){13,19}\b|\b\d{3}[- ]\d{2}[- ]\d{4}\b|\b\d{6,8}\b"#, with: "[SECRET]", options: .regularExpression)
        if matches(s, #"(?i)(one.?time|verification|security|auth|otp|code)\D{0,20}\d{4,8}"#) {
            s = s.replacingOccurrences(of: #"\b\d{4,8}\b"#, with: "[SECRET]", options: .regularExpression)
        }
        return s
    }
    static func digest(_ parts: [String], maskDigits: Bool = false) -> String {
        let s = parts.joined(separator: "\n"), text = maskDigits ? s.replacingOccurrences(of: #"\d"#, with: "#", options: .regularExpression) : s
        // Stable across helper processes (Swift's Hasher is deliberately randomized).
        return String(text.utf8.reduce(UInt64(14695981039346656037)) { ($0 ^ UInt64($1)) &* 1099511628211 }, radix: 16)
    }
    static func normalized(_ s: String) -> String { s.lowercased().split(whereSeparator: \.isWhitespace).joined(separator: " ").replacingOccurrences(of: "…", with: "...").replacingOccurrences(of: "[\u{2010}-\u{2015}\u{2212}]", with: "-", options: .regularExpression) }   // macOS writes "Wi‑Fi" with a non-breaking hyphen
    static func rank(_ label: String, _ text: String) -> Int {
        let l = normalized(label), t = normalized(text)
        guard !t.isEmpty else { return 0 }
        if l == t { return 4 }; if l.hasPrefix(t) { return 3 }
        if matches(l, #"\b"# + NSRegularExpression.escapedPattern(for: t) + #"\b"#) { return 2 }
        return l.contains(t) ? 1 : 0
    }
    static func keys(_ text: String) throws -> (CGKeyCode, CGEventFlags) {
        let input = normalized(text).replacingOccurrences(of:" ",with:"")
        var parts = (input.hasSuffix("++") ? String(input.dropLast()) + "=" : input).split(separator: "+").map(String.init), flags: CGEventFlags = []
        guard let key = parts.popLast(), !key.isEmpty else { throw Failure("Unknown key.") }
        for part in parts {
            switch part {
            case "cmd", "command", "⌘": flags.insert(.maskCommand)
            case "shift", "⇧": flags.insert(.maskShift)
            case "ctrl", "control", "⌃": flags.insert(.maskControl)
            case "alt", "option", "opt", "⌥": flags.insert(.maskAlternate)
            default: throw Failure("Unknown modifier: \(part)")
            }
        }
        let names: [String: CGKeyCode] = ["return":36,"enter":36,"esc":53,"escape":53,"tab":48,"space":49,"delete":51,"backspace":51,"forwarddelete":117,"pagedown":121,"pageup":116,"home":115,"end":119,"left":123,"right":124,"down":125,"up":126,
            "a":0,"s":1,"d":2,"f":3,"h":4,"g":5,"z":6,"x":7,"c":8,"v":9,"b":11,"q":12,"w":13,"e":14,"r":15,"y":16,"t":17,"1":18,"2":19,"3":20,"4":21,"6":22,"5":23,"=":24,"9":25,"7":26,"-":27,"8":28,"0":29,
            "]":30,"o":31,"u":32,"[":33,"i":34,"p":35,"l":37,"j":38,"'":39,"k":40,";":41,"\\":42,",":43,"/":44,"n":45,"m":46,".":47,"`":50,"f1":122,"f2":120,"f3":99,"f4":118,"f5":96,"f6":97,"f7":98,"f8":100,"f9":101,"f10":109,"f11":103,"f12":111]
        guard let code = names[["plus":"=","zoomin":"=","minus":"-","zoomout":"-" ][key] ?? key] else { throw Failure("Unknown key: \(key)") }
        return (code, flags)
    }
    static func riskyKey(_ text: String) throws -> Bool {
        let (code, flags) = try keys(text)
        return (flags.contains(.maskCommand) && [12,13,36,51,117].contains(code)) || (flags.contains([.maskCommand,.maskShift]) && code == 2) || (flags.contains([.maskCommand,.maskAlternate]) && code == 53)
    }
    static func attribute(_ e: AXUIElement, _ name: String) -> CFTypeRef? { axAttribute(e, name) }
    static func element(_ e: AXUIElement, _ name: String) -> AXUIElement? {
        guard let v = attribute(e, name), CFGetTypeID(v) == AXUIElementGetTypeID() else { return nil }; return (v as! AXUIElement)
    }
    static func children(_ e: AXUIElement) -> [AXUIElement] { Array(((attribute(e, kAXChildrenAttribute) as? [AXUIElement]) ?? []).prefix(400)) }
    static func frame(_ e: AXUIElement) -> CGRect {
        var p = CGPoint.zero, s = CGSize.zero
        if let v = attribute(e, kAXPositionAttribute), CFGetTypeID(v) == AXValueGetTypeID() { AXValueGetValue(v as! AXValue, .cgPoint, &p) }
        if let v = attribute(e, kAXSizeAttribute), CFGetTypeID(v) == AXValueGetTypeID() { AXValueGetValue(v as! AXValue, .cgSize, &s) }
        return CGRect(origin: p, size: s)
    }
    static func array(_ r: CGRect) -> [Double] { [r.minX, r.minY, r.width, r.height] }
    static func name(_ e: AXUIElement) -> String {
        for key in [kAXTitleAttribute, kAXDescriptionAttribute, "AXLabel", kAXHelpAttribute, "AXPlaceholderValue"] {
            if let s = attribute(e, key) as? String, !s.isEmpty { return String(mask(s).prefix(160)) }
        }
        let role = attribute(e, kAXRoleAttribute) as? String ?? ""
        return ["AXStaticText", "AXHeading"].contains(role) ? String(mask(attribute(e, kAXValueAttribute) as? String ?? "").prefix(160)) : ""
    }
    static func trusted() throws { guard AXIsProcessTrusted() else { throw Failure("Allow Atticus in System Settings → Privacy & Security → Accessibility") }; AXUIElementSetMessagingTimeout(AXUIElementCreateSystemWide(),0.15) }
    static func app(_ request: String? = nil) throws -> NSRunningApplication {
        if let request, !request.isEmpty {
            if let pid = Int32(request), let a = NSRunningApplication(processIdentifier: pid) { return a }
            let apps = NSWorkspace.shared.runningApplications.filter { normalized($0.localizedName ?? "") == normalized(request) || $0.bundleIdentifier == request }
            guard apps.count == 1 else { throw Failure("No unique running app named \(request).") }; return apps[0]
        }
        guard let a = NSWorkspace.shared.frontmostApplication else { throw Failure("No front app.") }; return a
    }
    static func windowElement(_ e: AXUIElement, app: AXUIElement) -> Bool {
        !CFEqual(e,app) && ["AXWindow","AXSheet"].contains(attribute(e,kAXRoleAttribute) as? String ?? "")
    }
    static func root(_ a: NSRunningApplication) throws -> (AXUIElement, AXUIElement) {
        try checkStopped()
        guard !a.isTerminated else { throw Failure("The mapped app closed. Run see again.") }
        let e = AXUIElementCreateApplication(a.processIdentifier), start = Date()
        let chromium = ["google chrome","chromium","arc","brave browser","microsoft edge","vivaldi","opera"].contains(normalized(a.localizedName ?? ""))
        let electron = a.bundleURL.map { FileManager.default.fileExists(atPath:$0.appendingPathComponent("Contents/Frameworks/Electron Framework.framework").path) } ?? false
        if chromium || electron {
            _ = AXUIElementSetAttributeValue(e, "AXManualAccessibility" as CFString, kCFBooleanTrue)
            _ = AXUIElementSetAttributeValue(e, "AXEnhancedUserInterface" as CFString, kCFBooleanTrue)
        }
        let candidates = [element(e,kAXFocusedWindowAttribute), element(e,kAXMainWindowAttribute)].compactMap { $0 } + ((attribute(e,kAXWindowsAttribute) as? [AXUIElement]) ?? [])
        for w in candidates {
            try checkStopped(); if Date().timeIntervalSince(start) >= 0.3 { break }
            if windowElement(w,app:e) { return (e,w) }
        }
        // Some apps omit AXWindows. Hit-test only this app's own CG window frames.
        let windows = (CGWindowListCopyWindowInfo(.optionAll,kCGNullWindowID) as? [[String:Any]]) ?? []
        for info in windows where (info[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == a.processIdentifier && (info[kCGWindowLayer as String] as? Int).map({ (0..<20).contains($0) || $0 == 101 }) == true {   // 101: pop-up menu level, where menu bar panels (Bluetooth, Wi-Fi) open
            if Date().timeIntervalSince(start) >= 0.3 { break }
            guard let bounds = info[kCGWindowBounds as String] as? NSDictionary, let rect = CGRect(dictionaryRepresentation:bounds) else { continue }
            var hit: AXUIElement?
            AXUIElementCopyElementAtPosition(e,Float(rect.midX),Float(rect.midY),&hit)
            if hit == nil || hit.map({ CFEqual($0,e) }) == true { AXUIElementCopyElementAtPosition(AXUIElementCreateSystemWide(),Float(rect.midX),Float(rect.midY),&hit) }
            if let hit { var pid:pid_t = 0; AXUIElementGetPid(hit,&pid); if pid != a.processIdentifier { continue } }
            if var current = hit {
                for _ in 0..<40 {
                    try checkStopped(); if Date().timeIntervalSince(start) >= 0.3 { break }
                    if windowElement(current,app:e) { var pid:pid_t = 0; AXUIElementGetPid(current,&pid); if pid == a.processIdentifier { return (e,current) } }
                    guard let parent = element(current,kAXParentAttribute), !CFEqual(parent,current) else { break }; current = parent
                }
            }
        }
        // Menu-bar-only apps (Control Center, Wi-Fi, third-party icons at the top right): map their status items instead.
        if let extras = element(e, "AXExtrasMenuBar") { return (e, extras) }
        throw Failure("No accessible window in \(a.localizedName ?? "app").")
    }
    static func capture(_ a: NSRunningApplication, offscreen: Bool = false) throws -> Map {
        let (e, w) = try root(a), wf = frame(w), start = Date()
        var m = Map(pid: a.processIdentifier, app: a.localizedName ?? "app", window: name(w), windowFrame: array(wf), nodes: [], texts: [], page: "", focused: "", scroll: [])
        m.windowID = String(describing: axWindowNumber(w) ?? "" as CFString)
        if UInt32(m.windowID) == nil {
            let windows = (CGWindowListCopyWindowInfo(.optionAll,kCGNullWindowID) as? [[String:Any]] ?? []).filter {
                ($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == a.processIdentifier && ($0[kCGWindowLayer as String] as? Int) == 0 &&
                ($0[kCGWindowBounds as String] as? NSDictionary).flatMap { CGRect(dictionaryRepresentation:$0) }.map { abs($0.minX - wf.minX) < 2 && abs($0.minY - wf.minY) < 2 && abs($0.width - wf.width) < 2 && abs($0.height - wf.height) < 2 } == true
            }
            if windows.count == 1, let id = windows[0][kCGWindowNumber as String] as? NSNumber { m.windowID = id.stringValue }
        }
        var queue: [(AXUIElement, [Int], CGRect)] = [], visited: [AXUIElement] = []
        // Menus get a share of the budget before a large web tree.
        if let menu = element(e, kAXMenuBarAttribute) { queue.append((menu, [-1], .null)) }
        queue.append((w, [], wf))
        for (i, child) in children(e).enumerated() where attribute(child, kAXRoleAttribute) as? String == "AXMenu" { queue.append((child, [-2, i], .null)) }
        let focused = element(e, kAXFocusedUIElementAttribute)
        var cursor = 0, later: [(AXUIElement, [Int], CGRect)] = [], deferring = true
        while true {
            // Web pages last: their links would use up the budget before an app's own toolbar (Chrome's Extensions button). --web reads pages.
            if cursor == queue.count, deferring { deferring = false; queue += later }
            guard cursor < queue.count && cursor < (offscreen ? 6000 : 1800) && Date().timeIntervalSince(start) < (offscreen ? 1 : 0.3) else { break }
            try checkStopped()
            let (item, path, clip) = queue[cursor]; cursor += 1
            if visited.contains(where: { CFEqual($0, item) }) { continue }; visited.append(item)
            let role = attribute(item, kAXRoleAttribute) as? String ?? "", bounds = frame(item)
            let visible = clip.isNull ? bounds : bounds.intersection(clip)
            let menu = role.contains("Menu"), shown = offscreen || menu || bounds.isEmpty || (!visible.isNull && visible.width >= 4 && visible.height >= 4)
            if !shown { continue }
            let label = name(item), hidden = role == "AXSecureTextField" || attribute(item, kAXSubroleAttribute) as? String == "AXSecureTextField" || secret(label)
            var value = ""
            if !hidden, let raw = attribute(item, kAXValueAttribute) {
                value = String(mask(raw as? String ?? (raw as? NSNumber)?.stringValue ?? "").prefix(400))
            }
            if role == "AXWebArea", let url = attribute(item, "AXURL") { let s = (url as? URL)?.absoluteString ?? (url as? String ?? ""); if s.hasPrefix("http") { m.page = mask(s) } }
            if role == "AXWebArea", deferring { later.append((item, path, clip)); visited.removeLast(); continue }
            if let focused, CFEqual(focused, item) { m.focused = mask(label.isEmpty ? role : label); m.focusIdentity = "\(role):\(path):\(array(bounds))" }
            if role == "AXScrollArea", let bar = element(item, kAXVerticalScrollBarAttribute), let n = attribute(bar, kAXValueAttribute) as? NSNumber { m.scroll.append(n.doubleValue) }
            if ["AXStaticText", "AXHeading"].contains(role) {
                let text = mask(label.isEmpty ? value : label)
                if !text.isEmpty && !m.texts.contains(text) && m.texts.count < 40 { m.texts.append(text) }
            } else if !["AXApplication","AXWindow","AXGroup","AXScrollArea","AXWebArea","AXUnknown","AXImage","AXRow","AXCell","AXMenuBar","AXMenu"].contains(role), !(role.isEmpty && label.isEmpty), m.nodes.count < 70, !bounds.isEmpty || menu {   // a background app's menus have no frame but still open by path
                let r = menu || offscreen ? bounds : visible
                if !m.nodes.contains(where: { $0.role == role && $0.label == mask(label) && $0.frame == array(r) }) {
                    m.nodes.append(Node(id: m.nodes.count + 1, role: role, label: mask(label.isEmpty ? role : label), value: value, frame: array(r), path: path, secret: hidden))
                }
            }
            var childClip = clip
            if !offscreen && ["AXWindow","AXSheet","AXScrollArea","AXWebArea"].contains(role), !bounds.isEmpty { childClip = clip.isNull ? bounds : clip.intersection(bounds) }
            if ["AXTextField","AXTextArea","AXSecureTextField","AXSearchField","AXComboBox"].contains(role) { continue }
            if role == "AXMenuBarItem", (attribute(item, kAXSelectedAttribute) as? Bool) != true { continue }
            for (i, child) in children(item).enumerated() { queue.append((child, path + [i], childClip)) }
        }
        return m
    }
    static func save(_ map: Map) throws {
        try FileManager.default.createDirectory(at: state.deletingLastPathComponent(), withIntermediateDirectories: true)
        var stored = try JSONSerialization.jsonObject(with: JSONEncoder().encode(map)) as! [String:Any]
        stored["signature"] = map.signature; stored["rich"] = map.rich
        try JSONSerialization.data(withJSONObject:stored).write(to: state, options: .atomic)
        chmod(state.path, 0o600)
    }
    static func load() throws -> Map {
        guard let data = try? Data(contentsOf: state), let m = try? JSONDecoder().decode(Map.self, from: data) else { throw Failure("Run see first.") }; return m
    }
    static func at(_ path: [Int], _ a: NSRunningApplication) throws -> AXUIElement {
        let (e, w) = try root(a); var current = w, path = path
        if path.first == -1 { guard let menu = element(e, kAXMenuBarAttribute) else { throw Failure("Menu unavailable.") }; current = menu; path.removeFirst() }
        else if path.first == -2 { path.removeFirst(); current = e }
        for i in path { let c = children(current); guard c.indices.contains(i) else { throw Failure("The screen changed. Run see again.") }; current = c[i] }
        return current
    }
    static func point(_ text: String) throws -> CGPoint? {
        let pieces = text.split(separator: ":", omittingEmptySubsequences: false), pair = pieces.last!.split(separator: ",", omittingEmptySubsequences: false)
        guard pair.count == 2 else { return nil }
        guard let x = Double(pair[0]), let y = Double(pair[1]), x.isFinite, y.isFinite else { throw Failure("Invalid coordinates.") }
        if pieces.count == 1 { return CGPoint(x: x, y: y) }
        guard pieces.count == 2, let n = Int(pieces[0]), NSScreen.screens.indices.contains(n - 1) else { throw Failure("No such screen.") }
        let screen = NSScreen.screens[n - 1], id = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? CGMainDisplayID(), r = CGDisplayBounds(id)
        // --look pictures are 1280 pixels wide; Quartz events use display points.
        let scale = r.width / 1280
        guard x >= 0, y >= 0, x <= 1280, y <= r.height / scale else { throw Failure("Point is outside that picture.") }
        return CGPoint(x: r.minX + x * scale, y: r.minY + y * scale)
    }
    static func visibleFrame(_ e: AXUIElement) -> CGRect {
        var visible = frame(e), current = e
        for _ in 0..<40 {
            guard let parent = element(current,kAXParentAttribute) else { break }
            let role = attribute(parent,kAXRoleAttribute) as? String ?? ""
            if ["AXWindow","AXScrollArea","AXWebArea","AXSheet"].contains(role), !frame(parent).isEmpty { visible = visible.intersection(frame(parent)) }
            current = parent
        }
        return visible
    }
    static func resolve(_ text: String, map: Map, a: NSRunningApplication, near: String = "") throws -> (Node, AXUIElement?) {
        if let id = Int(text) {
            guard let n = map.nodes.first(where: { $0.id == id }) else { throw Failure("No such control. Run see again.") }; return (n, try at(n.path, a))
        }
        if let p = try point(text) {
            if let n = map.nodes.filter({ CGRect(x:$0.frame[0],y:$0.frame[1],width:$0.frame[2],height:$0.frame[3]).contains(p) }).min(by: { $0.frame[2] * $0.frame[3] < $1.frame[2] * $1.frame[3] }) { return (n, try at(n.path,a)) }
            let (e, _) = try root(a); var hit: AXUIElement?
            AXUIElementCopyElementAtPosition(e, Float(p.x), Float(p.y), &hit)
            if let hit { var pid: pid_t = 0; AXUIElementGetPid(hit, &pid); guard pid == a.processIdentifier else { throw Failure("That point belongs to another app. Run see again.") } }
            if var current = hit {
                for _ in 0..<5 {
                    let role = attribute(current, kAXRoleAttribute) as? String ?? ""
                    if !name(current).isEmpty && !["AXStaticText","AXGroup","AXWindow","AXApplication","AXScrollArea","AXWebArea"].contains(role) {
                        let n = Node(id: 0, role: role, label: mask(name(current)), value: "", frame: [p.x,p.y,0,0], path: [], secret: secret(name(current)))
                        return (n, current)
                    }
                    guard let parent = element(current, kAXParentAttribute) else { break }; current = parent
                }
            }
            let bounds = CGRect(x:map.windowFrame[0],y:map.windowFrame[1],width:map.windowFrame[2],height:map.windowFrame[3])
            guard bounds.contains(p) else { throw Failure("That point is outside the mapped window. Run see again.") }
            return (Node(id:0,role:"AXUnknown",label:"Unidentified screen point \(Int(p.x)),\(Int(p.y))",value:"",frame:[p.x,p.y,0,0],path:[],secret:false),nil)
        }
        let candidates = map.nodes.filter { rank($0.label, text) > 0 }
        var anchor = map.nodes.first { rank($0.label, near) == 4 }
        if anchor == nil, !near.isEmpty, let e = try findText(near,a), rank(name(e),near) == 4 {
            let bounds = visibleFrame(e)
            if !bounds.isNull && bounds.width >= 4 && bounds.height >= 4 { anchor = Node(id:0,role:"AXStaticText",label:near,value:"",frame:array(bounds),path:[],secret:false) }
        }
        func distance(_ n: Node) -> Double { guard let anchor else { return Double(n.id) }; return hypot(n.spot.x - anchor.spot.x, n.spot.y - anchor.spot.y) }
        let sorted = candidates.sorted { rank($0.label, text) == rank($1.label, text) ? distance($0) < distance($1) : rank($0.label, text) > rank($1.label, text) }
        if near.isEmpty && (sorted.first.map { rank($0.label,text) } ?? 0) < 4, let e = try findText(text,a), rank(name(e),text) > (sorted.first.map { rank($0.label,text) } ?? 0) {
            let r = visibleFrame(e)
            if !r.isNull && r.width >= 4 && r.height >= 4 {
                return (Node(id:0,role:attribute(e,kAXRoleAttribute) as? String ?? "AXStaticText",label:mask(name(e)),value:"",frame:array(r),path:[],secret:false),e)
            }
        }
        guard let n = sorted.first else { throw Failure("No visible control named \(quote(mask(text))). Use scroll-to for offscreen text.") }
        if near.isEmpty && sorted.count > 1 && rank(sorted[1].label, text) == rank(n.label, text) { throw Failure("More than one control named \(quote(text)); use near.") }
        if !near.isEmpty && anchor == nil { throw Failure("No nearby anchor named \(quote(near)).") }
        return (n, try at(n.path, a))
    }
    static func actions(_ e: AXUIElement) -> [String] { var names: CFArray?; AXUIElementCopyActionNames(e, &names); return names as? [String] ?? [] }
    static func perform(_ e: AXUIElement, _ names: [String]) -> Bool {
        let supported = actions(e)
        // cannotComplete: the press opened a modal sheet and the app stopped answering AX; the action ran, so never retry it with the mouse
        return names.contains { supported.contains($0) && [.success, .cannotComplete].contains(AXUIElementPerformAction(e, $0 as CFString)) }
    }
    static func menuItem(_ text: String, _ parent: AXUIElement) throws -> AXUIElement {
        var q = children(parent), i = 0
        while i < q.count && i < 300 {
            let e = q[i]; i += 1
            if rank(name(e), text) == 4 { return e }
            let role = attribute(e, kAXRoleAttribute) as? String ?? ""
            if role == "AXMenu" || role == "AXMenuBarItem" { q += children(e) }
        }
        throw Failure("No menu item named \(quote(text)).")
    }
    static func menu(_ path: String, _ a: NSRunningApplication, act: Bool) throws -> String {
        try checkStopped(); guard !a.isTerminated else { throw Failure("The target app closed.") }
        let e = AXUIElementCreateApplication(a.processIdentifier); AXUIElementSetMessagingTimeout(e,0.15)
        guard var parent = element(e, kAXMenuBarAttribute) else { throw Failure("No accessible menu bar.") }
        let parts = path.components(separatedBy: ">").map { $0.trimmingCharacters(in: .whitespaces) }
        guard parts.count > 1, parts.allSatisfy({ !$0.isEmpty }) else { throw Failure("Invalid menu path.") }
        var restore: (() -> Void)?
        if act {   // a press can bring the app forward: tell the focus guard it's on purpose, then put the user's app back
            DistributedNotificationCenter.default().postNotificationName(.init("atticus.raise"), object: nil, deliverImmediately: true)
            usleep(50_000); restore = restoreFocus(a)
        }
        defer { if let restore { usleep(30_000); restore() } }
        for (index, part) in parts.enumerated() {
            try checkStopped()
            let item = try menuItem(part, parent), label = mask(name(item))
            if act { guard perform(item, ["AXPress","AXPick","AXOpen","AXShowMenu"]) else { throw Failure("Could not open menu \(quote(part)).") }; usleep(15_000) }
            parent = item
            // AX exposes AppKit submenus without opening them; no press occurs during safety resolution.
            if index == parts.count - 1 { return label }
        }
        throw Failure("Invalid menu path.")
    }
    static func sendKeys(_ text: String, pid: Int32, times: Int = 1) throws {
        let (code, flags) = try keys(text)
        guard (1...50).contains(times), let source = CGEventSource(stateID: .privateState) else { throw Failure("Invalid key repeat count.") }
        for _ in 0..<times {
            try checkStopped()
            for down in [true, false] { guard let event = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: down) else { throw Failure("Could not create key event.") }; event.flags = flags; event.postToPid(pid) }
        }
    }
    static func raise(_ a: NSRunningApplication) throws {
        DistributedNotificationCenter.default().postNotificationName(.init("atticus.raise"), object: nil, deliverImmediately: true)   // tell the focus guard this one is on purpose
        usleep(50_000)   // let the guard hear it before the app comes forward
        let (_, w) = try root(a); _ = perform(w, ["AXRaise"]); a.activate(); usleep(30_000)
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == a.processIdentifier else { throw Failure("Could not focus the mapped app.") }
    }
    static func restoreFocus(_ a: NSRunningApplication) -> () -> Void {
        let previous = NSWorkspace.shared.frontmostApplication
        let window = previous.flatMap { element(AXUIElementCreateApplication($0.processIdentifier),kAXFocusedWindowAttribute) }
        return {
            guard let previous, previous != a, !previous.isTerminated, NSWorkspace.shared.frontmostApplication == a else { return }
            previous.activate()
            if let window { _ = perform(window,["AXRaise"]) }
        }
    }
    static func mouse(_ from: CGPoint, _ a: NSRunningApplication, double: Bool = false, right: Bool = false, to: CGPoint? = nil) throws {
        guard env["ATTICUS_AX_ONLY"] != "1" else { throw Failure("Quartz mouse actions disabled for this fixture.") }
        let restore = restoreFocus(a); defer { usleep(30_000); restore() }
        try raise(a)
        guard let source = CGEventSource(stateID: .privateState), let saved = CGEvent(source: source)?.location else { throw Failure("Could not create mouse event.") }
        let button: CGMouseButton = right ? .right : .left
        defer { CGWarpMouseCursorPosition(saved) }
        func post(_ type: CGEventType, _ p: CGPoint, _ count: Int) throws {
            guard let e = CGEvent(mouseEventSource: source, mouseType: type, mouseCursorPosition: p, mouseButton: button) else { throw Failure("Could not create mouse event.") }
            e.flags = []; e.setIntegerValueField(.mouseEventClickState, value: Int64(count)); e.post(tap: .cghidEventTap)
        }
        var held = false
        defer { if held { try? post(right ? .rightMouseUp : .leftMouseUp, to ?? from, 1) } }
        for count in 1...(double ? 2 : 1) {
            try checkStopped()
            try post(right ? .rightMouseDown : .leftMouseDown, from, count)
            held = true
            if let to {
                for i in 1...20 { try checkStopped(); let t = Double(i) / 20; try post(.leftMouseDragged, CGPoint(x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t), count); usleep(8_000) }
            }
            try post(right ? .rightMouseUp : .leftMouseUp, to ?? from, count)
            held = false
        }
    }
    static func fingerprint(_ map: Map) -> [UInt8] {
        // Window-only capture avoids Atticus's ring and unrelated displays. No disk image is kept.
        final class Capture { let lock = NSLock(); var image: CGImage? }
        let result = Capture(), done = DispatchSemaphore(value: 0)
        Task {
            defer { done.signal() }
            guard let all = try? await SCShareableContent.excludingDesktopWindows(true,onScreenWindowsOnly:false),
                  let window = all.windows.first(where: {
                      guard $0.owningApplication?.processID == map.pid && $0.windowLayer == 0 else { return false }
                      if let id = UInt32(map.windowID) { return $0.windowID == id }
                      return array($0.frame) == map.windowFrame
                  }),
                  let image = try? await SCScreenshotManager.captureImage(contentFilter:SCContentFilter(desktopIndependentWindow:window), configuration: {
                    let cfg = SCStreamConfiguration(); cfg.width = 64; cfg.height = 40; return cfg
                  }()) else { return }
            result.lock.withLock { result.image = image }
        }
        guard done.wait(timeout:.now() + 0.3) == .success else { return [] }
        result.lock.lock(); let captured = result.image; result.lock.unlock()
        guard let image = captured else { return [] }
        var pixels = [UInt8](repeating: 0, count: 64 * 40)
        pixels.withUnsafeMutableBytes { buffer in
            if let c = CGContext(data: buffer.baseAddress, width: 64, height: 40, bitsPerComponent: 8, bytesPerRow: 64, space: CGColorSpaceCreateDeviceGray(), bitmapInfo: 0) { c.interpolationQuality = .low; c.draw(image, in: CGRect(x: 0,y: 0,width: 64,height: 40)) }
        }
        return pixels
    }
    static func pixelsChanged(_ before: [UInt8], _ after: [UInt8], threshold: Double = 4) -> Bool {
        guard !before.isEmpty, before.count == after.count else { return false }
        return zip(before, after).reduce(0.0) { $0 + abs(Double($1.0) - Double($1.1)) } / Double(before.count) >= threshold
    }
    static func scrollArea(_ a: NSRunningApplication, target: CGPoint? = nil) throws -> AXUIElement {
        let (_, w) = try root(a), start = Date(); var queue = [w], i = 0, found: [AXUIElement] = []
        while i < queue.count && i < 1800 && Date().timeIntervalSince(start) < 0.3 {
            try checkStopped()
            let e = queue[i]; i += 1
            if attribute(e, kAXRoleAttribute) as? String == "AXScrollArea", target == nil || frame(e).contains(target!) { found.append(e) }
            queue += children(e)
        }
        guard let area = found.sorted(by: { target == nil ? frame($0).width * frame($0).height > frame($1).width * frame($1).height : frame($0).width * frame($0).height < frame($1).width * frame($1).height }).first else { throw Failure("No scroll area.") }; return area
    }
    static func wheel(_ direction: String, _ spot: CGPoint, _ a: NSRunningApplication, fraction: Double = 1) throws {
        guard env["ATTICUS_AX_ONLY"] != "1" else { throw Failure("Quartz mouse actions disabled for this fixture.") }
        let restore = restoreFocus(a); defer { usleep(30_000); restore() }
        try raise(a)
        guard let source = CGEventSource(stateID: .privateState), let saved = CGEvent(source: source)?.location else { throw Failure("Could not create scroll event.") }
        defer { CGWarpMouseCursorPosition(saved) }; CGWarpMouseCursorPosition(spot)
        let vertical = ["down","up"].contains(direction), amount = Int32(((["down","right"].contains(direction) ? -500.0 : 500.0) * fraction).rounded())
        guard let event = CGEvent(scrollWheelEvent2Source: source, units: .pixel, wheelCount: 2, wheel1: vertical ? amount : 0, wheel2: vertical ? 0 : amount, wheel3: 0) else { throw Failure("Could not create scroll event.") }
        event.flags = []; event.post(tap: .cghidEventTap)
    }
    static func contentMoved(_ before: Map, _ after: Map) -> Bool {
        let changedText = Set(before.texts).subtracting(after.texts).count >= 3 && Set(after.texts).subtracting(before.texts).count >= 3
        return changedText || before.nodes.contains { n in
            let hits = after.nodes.filter { $0.role == n.role && $0.label == n.label }
            return hits.count == 1 && hypot(n.spot.x - hits[0].spot.x,n.spot.y - hits[0].spot.y) >= 6
        }
    }
    static func pageKeysAllowed(_ a: NSRunningApplication) -> Bool {
        guard let focused = element(AXUIElementCreateApplication(a.processIdentifier),kAXFocusedUIElementAttribute), let role = attribute(focused,kAXRoleAttribute) as? String else { return false }
        return ["AXWebArea","AXScrollArea","AXGroup","AXLayoutArea","AXWindow","AXTable","AXOutline","AXRow","AXCell","AXBrowser","AXStaticText","AXHeading","AXLink","AXButton","AXImage"].contains(role)
    }
    static func scroll(_ direction: String, pages: Double, all: Bool, a: NSRunningApplication, target: CGPoint? = nil) throws -> String {
        guard ["down","up","left","right"].contains(direction), pages.isFinite && pages >= 0.1 && pages <= 50 else { throw Failure("Use scroll down|up|left|right [pages|all] [target].") }
        let area = try (try? scrollArea(a, target: target)) ?? root(a).1, bar = element(area, ["down","up"].contains(direction) ? kAXVerticalScrollBarAttribute : kAXHorizontalScrollBarAttribute)
        let positive = ["down","right"].contains(direction), end = positive ? 1.0 : 0.0
        var moved = false, performed = 0, atEnd = false
        let fraction = min(1,pages)
        for _ in 0..<(all ? 50 : Int(ceil(pages))) {
            try checkStopped()
            let before = try capture(a), value = bar.flatMap { attribute($0, kAXValueAttribute) as? NSNumber }?.doubleValue
            let pixels = value == nil && env["ATTICUS_AX_ONLY"] != "1" ? fingerprint(before) : []
            if let value, abs(value - end) < 0.001 { atEnd = true; break }
            var methods: [() throws -> Void] = [
                { if fraction == 1 { _ = perform(area, ["AXScroll\(direction.capitalized)ByPage"]) } },
                { if let bar { _ = perform(bar, [positive ? "AXIncrement" : "AXDecrement"]) } },
                { if let bar, let value { _ = AXUIElementSetAttributeValue(bar, kAXValueAttribute as CFString, NSNumber(value: all ? end : max(0,min(1,value + (positive ? 0.15 : -0.15) * fraction)))) } },
                { if fraction == 1 && pageKeysAllowed(a) { try sendKeys(["down":"pagedown","up":"pageup","left":"left","right":"right"][direction]!, pid: a.processIdentifier) } },
                { if env["ATTICUS_AX_ONLY"] != "1" { try wheel(direction, target ?? CGPoint(x: frame(area).midX,y: frame(area).midY), a, fraction:fraction) } },
                { if env["ATTICUS_AX_ONLY"] != "1" { try wheel(direction, CGPoint(x: frame(area).midX,y: positive ? frame(area).maxY - 10 : frame(area).minY + 10), a, fraction:fraction) } }
            ]
            // Exhaust background AX and PID-key paths before borrowing focus for a Quartz wheel.
            if all, let bar { var writable = DarwinBoolean(false); AXUIElementIsAttributeSettable(bar,kAXValueAttribute as CFString,&writable); if writable.boolValue { methods.insert({ _ = AXUIElementSetAttributeValue(bar,kAXValueAttribute as CFString,NSNumber(value:end)) },at:0) } }
            var changed = false
            for method in methods {
                try checkStopped(); try method()
                for poll in 0..<3 {
                    usleep(poll == 0 ? 25_000 : 75_000)
                    let after = try capture(a), newValue = bar.flatMap { attribute($0, kAXValueAttribute) as? NSNumber }?.doubleValue
                    if (value != nil && newValue != nil ? abs(newValue! - value!) >= 0.001 : contentMoved(before,after) || (!pixels.isEmpty && pixelsChanged(pixels, fingerprint(after)))) { changed = true; break }
                }
                if changed { break }
            }
            if !changed { break }; moved = true; performed += 1
            if all, let newValue = bar.flatMap({ attribute($0, kAXValueAttribute) as? NSNumber })?.doubleValue, abs(newValue - end) < 0.001 { break }
        }
        let percent = bar.flatMap { attribute($0,kAXValueAttribute) as? NSNumber }.map { " (now \(Int($0.doubleValue * 100))%)" } ?? ""
        return moved ? "Scrolled \(direction) " + (fraction < 1 ? "a bit" : "\(performed) page\(performed == 1 ? "" : "s")") + percent : atEnd ? "Already at the end" : "No scroll movement detected"
    }
    static func findText(_ text: String, _ a: NSRunningApplication) throws -> AXUIElement? {
        let (_, w) = try root(a), start = Date(); var queue = [w], i = 0, best: AXUIElement?, score = 0
        while i < queue.count && i < 6000 && Date().timeIntervalSince(start) < 1 {
            try checkStopped()
            let e = queue[i]; i += 1; let role = attribute(e,kAXRoleAttribute) as? String ?? ""
            if !["AXTextField","AXTextArea","AXSecureTextField"].contains(role) { let r = rank(name(e), text); if r > score { best = e; score = r }; if r == 4 { return e } }
            queue += children(e)
        }
        return best
    }
    static func scrollTo(_ text: String, _ a: NSRunningApplication) throws -> String {
        func visible() throws -> Bool {
            let m = try capture(a)
            return m.texts.contains(where: { rank($0,text) == 4 }) || m.nodes.contains(where: { rank($0.label,text) == 4 })
        }
        if try visible() { return "Found \(quote(mask(text)))" }
        let found = try findText(text,a)
        if let e = found, perform(e,["AXScrollToVisible"]) {
            for _ in 0..<4 { usleep(25_000); if try visible() { return "Revealed \(quote(mask(text)))" } }
        }
        var direction = "down", reversed = false, target: CGPoint?, limit = 15
        if var e = found {
            for _ in 0..<40 {
                if attribute(e,kAXRoleAttribute) as? String == "AXScrollArea" {
                    let bounds = frame(e); target = CGPoint(x:bounds.midX,y:bounds.midY)
                    if let found, frame(found).maxY < bounds.minY { direction = "up" }
                    if let found, bounds.height > 0 { limit = min(60, max(15, Int(abs(frame(found).midY - bounds.midY) / bounds.height) + 3)) }   // far text: enough pages to reach it
                    break
                }
                guard let parent = element(e,kAXParentAttribute) else { break }; e = parent
            }
        }
        for _ in 0..<limit {
            try checkStopped()
            let m = try capture(a)
            if m.texts.contains(where: { rank($0,text) == 4 }) || m.nodes.contains(where: { rank($0.label,text) == 4 }) { return "Found \(quote(mask(text)))" }
            let result = try scroll(direction,pages: 1,all: false,a: a,target:target)
            if result == "Already at the end" { if reversed { break }; direction = direction == "down" ? "up" : "down"; reversed = true }
            else if result == "No scroll movement detected" { break }
        }
        if try visible() { return "Found \(quote(mask(text)))" }
        throw Failure("Could not find \(quote(mask(text))) within \(limit) pages.")
    }
    static func typeText(_ text: String, _ n: Node, _ e: AXUIElement, _ a: NSRunningApplication, append: Bool) throws {
        guard ["AXTextField","AXTextArea","AXComboBox","AXSearchField","AXSecureTextField"].contains(n.role) else { throw Failure("Target is not a text field.") }
        guard AXUIElementSetAttributeValue(e,kAXFocusedAttribute as CFString,kCFBooleanTrue) == .success else { throw Failure("Could not focus that field.") }
        let old = attribute(e,kAXValueAttribute) as? String ?? "", draft = append ? old + text : text
        if AXUIElementSetAttributeValue(e,kAXValueAttribute as CFString,draft as CFString) == .success {
            guard attribute(e,kAXValueAttribute) as? String == draft else { throw Failure("Text did not land in the field.") }; return
        }
        // PID-directed paste keeps focus in the user’s app; verify the same field before reporting success.
        let pb = NSPasteboard.general, saved = pb.pasteboardItems?.map { i in i.types.compactMap { t in i.data(forType:t).map { (t,$0) } } } ?? []
        pb.clearContents(); guard pb.setString(text,forType:.string) else { throw Failure("Could not prepare paste.") }; let changed = pb.changeCount
        defer { if pb.changeCount == changed { pb.clearContents(); pb.writeObjects(saved.map { pairs in let i = NSPasteboardItem(); pairs.forEach { i.setData($1,forType:$0) }; return i }) } }
        try sendKeys(append ? "cmd+right" : "cmd+a",pid:a.processIdentifier)
        try sendKeys("cmd+v",pid:a.processIdentifier); usleep(150_000)
        if !n.secret, attribute(e,kAXValueAttribute) as? String != draft { throw Failure("Could not verify the pasted text.") }
    }
    static func settle(_ a: NSRunningApplication, seconds: Double) throws -> Bool {
        let start = Date(), initial = try capture(a); var last = initial.settled, since = Date()
        let usePixels = !initial.rich && env["ATTICUS_AX_ONLY"] != "1"
        var pixels = usePixels ? fingerprint(initial) : []
        while Date().timeIntervalSince(start) < seconds {
            try checkStopped()
            usleep(50_000); let map = try capture(a), current = map.settled
            let freshPixels = usePixels ? fingerprint(map) : []
            if current != last || pixelsChanged(pixels,freshPixels,threshold:1.5) { since = Date(); last = current }
            pixels = freshPixels
            if Date().timeIntervalSince(since) >= 0.3 { return true }
        }
        return false
    }
    static func validate(_ args: [String]) throws {
        guard let verb = args.first else { throw Failure("Use see|click|scroll|scroll-to|press|drag|type|wait.") }
        let rest = Array(args.dropFirst())
        guard !rest.contains(where: { $0.hasPrefix("--") }) else { throw Failure("Hands accepts no flags.") }
        switch verb {
        case "menu": guard rest.count == 2, !rest[0].isEmpty, rest[1].components(separatedBy:">").count > 1, rest[1].components(separatedBy:">").allSatisfy({ !$0.trimmingCharacters(in:.whitespaces).isEmpty }) else { throw Failure("Use menu app path.") }
        case "see": guard rest.count <= 1 else { throw Failure("Use see [app].") }
        case "click": guard !rest.isEmpty, rest.count <= 5 else { throw Failure("Use click target [near label] [double] [right].") }; _ = try clickOptions(rest)
        case "scroll": guard (1...3).contains(rest.count), ["down","up","left","right"].contains(rest[0]), rest.count < 3 || rest[1] == "all" || Double(rest[1]).map({ $0.isFinite && $0 >= 0.1 && $0 <= 50 }) == true else { throw Failure("Use scroll direction [pages|all] [target].") }; if rest.count == 2, let n = Double(rest[1]), !n.isFinite || n < 0.1 || n > 50 { throw Failure("Invalid page count.") }
        case "scroll-to": guard rest.count == 1 else { throw Failure("Use scroll-to text.") }
        case "press": guard (1...2).contains(rest.count) else { throw Failure("Use press keys [times].") }; _ = try keys(rest[0]); if rest.count == 2 { guard let n = Int(rest[1]), (1...50).contains(n) else { throw Failure("Invalid repeat count.") } }
        case "drag": guard rest.count == 2 else { throw Failure("Use drag from to.") }
        case "type": guard (2...4).contains(rest.count), rest.dropFirst(2).allSatisfy({ ["submit","append"].contains($0) }) else { throw Failure("Use type target text [submit] [append].") }
        case "wait": guard rest.count <= 1, rest.isEmpty || Double(rest[0]).map({ $0.isFinite && $0 > 0 && $0 <= 30 }) == true else { throw Failure("Use wait [seconds, max 30].") }
        default: throw Failure("Unknown hands verb: \(verb)")
        }
    }
    static func clickOptions(_ args: [String]) throws -> (String,Bool,Bool) {
        var near = "", double = false, right = false, i = 1
        while i < args.count {
            switch args[i] {
            case "near": guard i + 1 < args.count, near.isEmpty else { throw Failure("Use near label.") }; near = args[i+1]; i += 1
            case "double": guard !double else { throw Failure("Duplicate double.") }; double = true
            case "right": guard !right else { throw Failure("Duplicate right.") }; right = true
            default: throw Failure("Unknown click option: \(args[i])")
            }; i += 1
        }
        return (near,double,right)
    }
    static func targets(_ args: [String]) -> [String] {
        switch args[0] {
        case "click", "type": return [args[1]]
        case "drag": return [args[1],args[2]]
        case "scroll": return args.count == 4 ? [args[3]] : args.count == 3 && args[2] != "all" && Double(args[2]) == nil ? [args[2]] : []
        default: return []
        }
    }
    static func freshIDs(_ args: [String], _ old: Map, _ fresh: Map) throws {
        if targets(args).contains(where: { Int($0) != nil }), old.signature != fresh.signature { throw Failure("The screen changed. Run see again.") }
    }
    static func checked(_ args: [String], _ map: Map, _ a: NSRunningApplication) throws -> [String: Any] {
        var labels: [String] = [], secure = false
        let verb = args[0]
        if verb == "click", args[1].contains(">") {
            let (near,double,right) = try clickOptions(Array(args.dropFirst()))
            guard near.isEmpty && !double && !right else { throw Failure("Menu paths accept no click options.") }
            labels = args[1].components(separatedBy:">").dropLast().map { mask($0.trimmingCharacters(in:.whitespaces)) } + [try menu(args[1],a,act:false)]
        }
        else if ["click","drag","type"].contains(verb) {
            let near = verb == "click" ? try clickOptions(Array(args.dropFirst())).0 : ""
            for target in (verb == "drag" ? [args[1],args[2]] : [args[1]]) { let (n, _) = try resolve(target,map:map,a:a,near:near); labels.append(n.label); secure = secure || n.secret }
        } else if verb == "press" { labels = [map.focused, args[1]] }
        let keyRisk = verb == "press" ? try riskyKey(args[1]) : false
        let risk = labels.contains { $0.hasPrefix("Unidentified screen point ") || riskyLabel($0,map) || (verb == "drag" && matches($0,#"(?i)\b(bin|recycle)\b"#)) } || keyRisk || (verb == "type" && args.dropFirst(3).contains("submit"))
        return ["labels":labels,"secure":secure,"risky":risk,"signature":map.signature,"pid":map.pid,"args":args,"windowID":map.windowID,"windowFrame":map.windowFrame,"window":mask(map.window),"app":map.app]
    }
    static func cli(_ input: [String]) -> Int32 {
        let started = DispatchTime.now().uptimeNanoseconds
        defer {
            if env["ATTICUS_HANDS_TIMING"] == "1" {
                let ms = Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000
                FileHandle.standardError.write(Data("HANDS NET \(String(format:"%.2f",ms)) ms\n".utf8))
            }
        }
        stopped = 0
        signal(SIGTERM) { _ in Hands.stopped = 1 }; signal(SIGINT) { _ in Hands.stopped = 1 }
        do {
            if input.first == "label" { let args = Array(input.dropFirst()); try validate(args); try trusted(); let old = try load(), a = try app(String(old.pid)), m = try capture(a); try freshIDs(args,old,m); let checked = try checked(args, m, a); print(String(data:try JSONSerialization.data(withJSONObject:checked),encoding:.utf8)!); return 0 }
            try validate(input); try trusted()
            if input[0] == "see" { let m = try capture(try app(input.count > 1 ? input[1] : nil)); try save(m); print(m.description); return 0 }
            if input[0] == "menu" {
                let a = try app(input[1]), label = try menu(input[2],a,act:false)
                guard !Prefs.bool("safe") || !(riskyLabel(input[2]) || riskyLabel(label)) else { throw Failure("This menu action needs the user's Allow card. Use the normal hands click path.") }
                let target = MiniScreen.windowTarget(a,windows:CGWindowListCopyWindowInfo(.optionAll,kCGNullWindowID) as? [[String:Any]] ?? [])   // optional AX metadata must not turn a successful press into a timeout and duplicate action
                print("Clicked \(quote(try menu(input[2],a,act:true)))")
                if let target,
                   let data = try? JSONSerialization.data(withJSONObject:target.merging(["action":"click"]) { $1 }), let text = String(data:data,encoding:.utf8) { print("▣ " + text) }
                return 0
            }
            let old = try load(), a = try app(String(old.pid)), before = try capture(a), check = try checked(input, before, a)
            try freshIDs(input,old,before)
            let data = env["ATTICUS_HANDS_RECEIPT"] == "1" ? FileHandle.standardInput.readDataToEndOfFile() : Data()
            let receipt = (try? JSONSerialization.jsonObject(with:data)) as? [String:Any]
            if let receipt {
                guard NSDictionary(dictionary:receipt).isEqual(to:check) else { throw Failure("The screen changed while checking permission. Run see again.") }
            } else if (check["risky"] as? Bool == true && Prefs.bool("safe")) || (input[0] == "type" && check["secure"] as? Bool == true) { throw Failure("Use atticus.py --hands so the user can allow this action.") }
            var result = "", spot: CGPoint?
            switch input[0] {
            case "click":
                if input[1].contains(">") { let label = try menu(input[1],a,act:true); result = "Clicked \(quote(label))" }
                else {
                    let (near,double,right) = try clickOptions(Array(input.dropFirst())), (n,e) = try resolve(input[1],map:before,a:a,near:near); spot = n.spot
                    if let e, !double && !right, perform(e,["AXPress","AXPick","AXConfirm","AXOpen"]) { }
                    else { try mouse(n.spot,a,double:double,right:right) }
                    result = "Clicked \(quote(n.label))"
                }
            case "scroll":
                let amount = input.count > 2 ? input[2] : "1", pages = Double(amount) ?? 1
                let target = input.count > 3 ? input[3] : (input.count > 2 && amount != "all" && Double(amount) == nil ? amount : "")
                let p = target.isEmpty ? nil : try resolve(target,map:before,a:a).0.spot
                spot = p ?? CGPoint(x:before.windowFrame[0] + before.windowFrame[2] / 2,y:before.windowFrame[1] + before.windowFrame[3] / 2)
                result = try scroll(input[1],pages:pages,all:amount == "all",a:a,target:p)
            case "scroll-to": result = try scrollTo(input[1],a)
            case "press": try sendKeys(input[1],pid:a.processIdentifier,times:input.count > 2 ? Int(input[2])! : 1); result = "Pressed \(quote(input[1])) in \(a.localizedName ?? "app")"
            case "drag": let from = try resolve(input[1],map:before,a:a).0, to = try resolve(input[2],map:before,a:a).0; try mouse(from.spot,a,to:to.spot); spot = to.spot; result = "Dragged \(quote(from.label)) to \(quote(to.label))"
            case "type": let (n,e) = try resolve(input[1],map:before,a:a); guard let e else { throw Failure("No editable field.") }; spot = n.spot; try typeText(input[2],n,e,a,append:input.dropFirst(3).contains("append")); if input.dropFirst(3).contains("submit") { try sendKeys("return",pid:a.processIdentifier) }; result = "Typed into \(quote(n.label))"
            case "wait": result = try settle(a,seconds:input.count > 1 ? Double(input[1])! : 5) ? "Window settled" : "Window did not settle before the timeout"
            default: throw Failure("Unknown hands verb.")
            }
            if input[0] != "wait" { usleep(25_000) }
            let after = try capture(a)
            if input[0] == "click" {
                let (_, w) = try root(a)
                if let sheet = (attribute(w,"AXSheets") as? [AXUIElement])?.first ?? (attribute(w,kAXRoleAttribute) as? String == "AXSheet" ? w : nil) { result += " — a sheet opened: \(quote(mask(name(sheet))))" }
                else if after.signature == before.signature { result = "Nothing changed after clicking \(quote((check["labels"] as? [String])?.first ?? input[1]))" }
            }
            print(result)
            if let spot { print("@ \(Int(spot.x)) \(Int(spot.y))") }
            let changed = after.nodes.filter { n in !before.nodes.contains { $0.id == n.id && $0.path == n.path && $0.role == n.role && $0.label == n.label && $0.value == n.value && $0.frame == n.frame } }
            let removed = before.nodes.filter { n in !after.nodes.contains { $0.id == n.id && $0.path == n.path && $0.role == n.role && $0.label == n.label } }.map { "Removed: [\($0.id)] \(quote($0.label))" }
            if after.windowID != before.windowID || after.window != before.window || after.windowFrame != before.windowFrame { print(after.description) }
            else { print((["Now: \(mask(after.window))"] + removed + changed.map(\.line) + ["Focused: \(after.focused)"] + (after.scroll.isEmpty ? [] : ["Scroll: \(Int(after.scroll[0] * 100))% down"]) + (after.page == before.page ? [] : ["Page: \(mask(after.page))"]) + [String(after.texts.filter { !before.texts.contains($0) }.joined(separator:" | ").prefix(1400))]).joined(separator:"\n")) }
            try save(after); return 0
        } catch let failure as Failure { print(failure.message); return 1 }
        catch { print("Hands could not finish: \(error.localizedDescription)"); return 1 }
    }
    static func selftest() {
        precondition(rank("Export", "") == 0)
        precondition(rank("Export","export") == 4 && rank("Export PDF","export") == 3 && rank("Start Export Now","export") == 2 && rank("Reexport","export") == 1)
        precondition(mask("4111 1111 1111 1111 / 123-45-6789 / Code 123456") == "[SECRET] / [SECRET] / Code [SECRET]")
        precondition(secret("Password") && secret("one time code") && !secret("Name"))
        let date = "Oct 11, 2026 6:39 PM"
        precondition(!secret(date) && mask(date) == date && !secret("Version 12.34.5678"))
        precondition(mask("4111111111111111") == "[SECRET]")
        let safeMap = Map(pid:123,app:"Fixture",window:"Export options",windowFrame:[0,0,400,400],nodes:[],texts:["Choose a destination"],page:"",focused:"",scroll:[])
        var dangerousMap = safeMap; dangerousMap.texts = ["Delete 3 items?"]
        for label in ["OK","Yes","Continue","Allow","Accept","Agree","Complete","Finish","Grant"] { precondition(!riskyLabel(label,safeMap) && riskyLabel(label,dangerousMap)) }
        precondition(!riskyLabel("Cancel",dangerousMap) && riskyLabel("Confirm",safeMap) && riskyLabel("Allow access",safeMap))
        precondition(matches("Delete draft",riskyPattern) && matches("Send",riskyPattern) && !matches("Export",riskyPattern))
        precondition((try! keys("⌘+⇧+4")).0 == 21 && (try! keys("cmd++")).0 == 24)
        precondition(!(try! riskyKey("return")))
        precondition(try! riskyKey("cmd+q")); precondition(!(try! riskyKey("cmd+t")))
        let (code,flags) = try! keys("cmd+shift+4"); precondition(code == 21 && flags == [.maskCommand,.maskShift])
        precondition(digest(["count 1"],maskDigits:true) == digest(["count 2"],maskDigits:true))
        let node = Node(id:1,role:"AXTextField",label:"Password",value:"private",frame:[0,0,10,10],path:[],secret:true)
        precondition(!node.line.contains("private") && node.line.contains("[1]"))
        precondition(!pixelsChanged([],[]) && pixelsChanged([0,0],[5,5]))
        for args in [["click","Export","--yes"],["press","cmd+q","0"],["type","Name","text","force"],["wait","nan"]] { do { try validate(args); preconditionFailure("Accepted invalid hands args") } catch {} }
    }
}
// MARK: - End Hands

if CommandLine.arguments == [CommandLine.arguments[0], "--raise"] {   // atticus.py is about to bring an app forward on purpose (a move, full screen): the focus guard lets it for 3 s
    DistributedNotificationCenter.default().postNotificationName(.init("atticus.raise"), object: nil, deliverImmediately: true); usleep(50_000); exit(0)
}
if CommandLine.arguments.count >= 2, CommandLine.arguments[1] == "--hands" { exit(Hands.cli(Array(CommandLine.arguments.dropFirst(2)))) }
if CommandLine.arguments.count >= 3, ["--window-target","--target-app"].contains(CommandLine.arguments[1]) {
    let name = CommandLine.arguments[2]
    let url = name.contains(":") ? URL(string:name) : FileManager.default.fileExists(atPath:name) ? URL(fileURLWithPath:name) : nil
    let handler = url.flatMap { NSWorkspace.shared.urlForApplication(toOpen:$0) }, bundle = handler.flatMap { Bundle(url:$0)?.bundleIdentifier }
    let title = CommandLine.arguments.count > 3 && !CommandLine.arguments[3].isEmpty ? CommandLine.arguments[3] : url?.isFileURL == true && FileManager.default.fileExists(atPath:name) ? url!.deletingPathExtension().lastPathComponent : ""
    let frame = CommandLine.arguments.count == 5 ? (try? JSONSerialization.jsonObject(with:Data(CommandLine.arguments[4].utf8))) as? [Double] ?? [] : []
    if !frame.isEmpty && (frame.count != 4 || !frame.allSatisfy(\.isFinite)) { exit(1) }
    let apps = NSWorkspace.shared.runningApplications.filter { $0.localizedName?.localizedCaseInsensitiveCompare(name) == .orderedSame || $0.bundleIdentifier == name || (bundle != nil && $0.bundleIdentifier == bundle) || $0.executableURL?.lastPathComponent.localizedCaseInsensitiveCompare(name) == .orderedSame }
    if CommandLine.arguments[1] == "--target-app" { if apps.count == 1 { print(apps[0].localizedName ?? name) } else if let handler { print(handler.deletingPathExtension().lastPathComponent) }; exit(0) }
    if apps.count == 1, let target = MiniScreen.windowTarget(apps[0],title:title,frame:frame,windows:CGWindowListCopyWindowInfo(.optionAll,kCGNullWindowID) as? [[String:Any]] ?? []),
       let data = try? JSONSerialization.data(withJSONObject:target) { print(String(decoding:data,as:UTF8.self)) }
    exit(0)
}

// One Atticus at a time: a lock the system drops when the process ends (opened by hand + started by launchd = two)
if CommandLine.arguments.dropFirst() == ["--selftest"] {
    precondition(meetingQuestion("Saarth, your thoughts.", "Saarth Ranka"))
    precondition(!meetingQuestion("Saarthi is here.", "Saarth"))
    precondition(meetingQuestion("How will it work", ""))
    precondition(meetingQuestion("The date?", ""))
    precondition(!meetingQuestion("Thank you everyone.", ""))
    precondition(!meetingQuestion("Hey, how are you doing today?", "") && !meetingQuestion("We ship Friday, right?", "") && !meetingQuestion("Can you hear me?", ""))
    precondition(meetingQuestion("How are you thinking about pricing?", "") && meetingQuestion("How was your experience at Google?", ""))
    precondition(transcriptKey(" Open   Notes. ") == transcriptKey("open notes"))
    precondition(transcriptKey("calculate 1.5") != transcriptKey("calculate 15"))
    precondition(transcriptKey("search a b") != transcriptKey("search ab"))
    precondition(transcriptKey("open a-b.com") != transcriptKey("open ab.com"))
    Hands.selftest()
    print("native selftest ok"); exit(0)
}
// The brain's typing helper shares selection validation and clipboard ownership with Replace.
if CommandLine.arguments.dropFirst() == ["--type"] {
    let nsapp = NSApplication.shared; nsapp.setActivationPolicy(.accessory)
    guard let selected = TextSelection.capture(enabled: true, allowEmpty: true), selected.range != nil, selected.editable || selected.pastable else {
        print("Could not type: no text field has the cursor. Make one have it first with --hands (see, then click the field or whatever opens it), then type."); exit(1)
    }
    let draft = String(decoding: FileHandle.standardInput.readDataToEndOfFile(), as: UTF8.self)
    let target = AXUIElementCreateApplication(selected.app.processIdentifier)
    AXUIElementSetMessagingTimeout(target, 0.15)
    selected.apply(draft, valid: {
        guard NSWorkspace.shared.frontmostApplication == selected.app,
              let focused = axAttribute(target, kAXFocusedUIElementAttribute) else { return false }
        return CFEqual(focused, selected.element)
    }) { ok in
        print(ok ? "typed into \(selected.app.localizedName ?? "app")" : "Could not type: the text did not appear in the field.")
        if ok { DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) { exit(0) } }
        else { exit(1) }
    }
    nsapp.run(); exit(1)
}

let lockFD = open(NSString(string: "~/.config/atticus/app.lock").expandingTildeInPath, O_CREAT | O_RDWR, 0o644)
if lockFD >= 0 && flock(lockFD, LOCK_EX | LOCK_NB) != 0 {
    for _ in 0..<15 where flock(lockFD, LOCK_EX | LOCK_NB) != 0 { usleep(100_000) }   // a restart: the old one is exiting
    if flock(lockFD, LOCK_EX | LOCK_NB) != 0 { exit(0) }
}

let meeting = MeetingCopilot()

// "Get ready before calls": once a minute, a call starting in the next 3 min (has guests or a video link) gets one small card.
let calendar = EKEventStore()
var nudged = Set<String>()
func checkCalendar() {
    guard Prefs.bool("meeting"), Prefs.bool("meetingNudge"), !Prefs.bool("paused"), !meeting.running, meeting.panel == nil,
          EKEventStore.authorizationStatus(for: .event) == .fullAccess else { return }
    let now = Date(), link = "zoom\\.us|meet\\.google|teams\\.microsoft|teams\\.live|facetime|webex|whereby"
    let soon = calendar.events(matching: calendar.predicateForEvents(withStart: now.addingTimeInterval(-60), end: now.addingTimeInterval(180), calendars: nil)).sorted { $0.startDate < $1.startDate }
    guard let e = soon.first(where: { e in
        !e.isAllDay && e.status != .canceled && !(e.attendees ?? []).contains(where: { $0.isCurrentUser && $0.participantStatus == .declined }) && e.startDate > now.addingTimeInterval(-60) && !nudged.contains("\(e.eventIdentifier ?? "")@\(e.startDate.timeIntervalSince1970)")
            && (e.hasAttendees || [e.url?.absoluteString, e.location, e.notes].contains { ($0 ?? "").range(of: link, options: [.regularExpression, .caseInsensitive]) != nil })
    }) else { return }
    nudged.insert("\(e.eventIdentifier ?? "")@\(e.startDate.timeIntervalSince1970)")
    let mins = Int(ceil(e.startDate.timeIntervalSince(now) / 60))
    let people = (e.attendees ?? []).filter { !$0.isCurrentUser }.compactMap(\.name)
    let who = people.prefix(2).joined(separator: ", ") + (people.count > 2 ? " +\(people.count - 2)" : "")
    let context = [e.title ?? "", people.isEmpty ? "" : "With: " + people.joined(separator: ", "), e.location ?? "", e.url?.absoluteString ?? "", e.notes ?? ""].filter { !$0.isEmpty }.joined(separator: "\n")
    showNudge(["title": e.title ?? "Call", "when": mins <= 0 ? "Starting now" : "Starts in \(mins) min", "who": who, "context": String(context.prefix(20000))])
}
func showNudge(_ info: [String: Any]) {
    meeting.open(nudge: info)
    // Ignored, it goes by itself; "Get ready" clears meeting.nudge so it stays.
    let g = meeting.generation
    DispatchQueue.main.asyncAfter(deadline: .now() + 45) { if meeting.generation == g && !meeting.running && meeting.nudge != nil { meeting.discard() } }
}
Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in checkCalendar() }

// "Notice when you're in a call": a call app holding the mic for 3 s gets one card per call (like Granola's "Meeting detected").
// Dictation apps (Wispr Flow, Atticus itself) aren't call apps, and a short debounce skips transient mic use. Browser helpers share the browser's prefix.
let callApps = ["us.zoom.xos": "Zoom", "com.microsoft.teams": "Teams", "com.apple.FaceTime": "FaceTime", "com.tinyspeck.slackmacgap": "Slack",
                "net.whatsapp.WhatsApp": "WhatsApp", "com.hnc.Discord": "Discord", "com.cisco.webex": "Webex", "com.google.Chrome": "Chrome",
                "com.apple.WebKit.GPU": "Safari", "company.thebrowser": "Arc", "com.brave.Browser": "Brave", "com.microsoft.edgemac": "Edge", "org.mozilla.firefox": "Firefox"]
func audioProp<T>(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector, _ zero: T) -> [T] {
    var a = AudioObjectPropertyAddress(mSelector: sel, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain), size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(obj, &a, 0, nil, &size) == noErr, size > 0 else { return [] }
    var out = [T](repeating: zero, count: Int(size) / MemoryLayout<T>.stride)
    return AudioObjectGetPropertyData(obj, &a, 0, nil, &size, &out) == noErr ? out : []
}
func callAppsOnMic() -> Set<String> {   // names of call apps whose audio input is running right now (macOS 14.2+ per-process audio objects)
    Set(audioProp(AudioObjectID(kAudioObjectSystemObject), kAudioHardwarePropertyProcessObjectList, AudioObjectID(0)).compactMap { p in
        guard audioProp(p, kAudioProcessPropertyIsRunningInput, UInt32(0)).first ?? 0 != 0 else { return nil }
        var a = AudioObjectPropertyAddress(mSelector: kAudioProcessPropertyBundleID, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
        var id: Unmanaged<CFString>?, size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        guard AudioObjectGetPropertyData(p, &a, 0, nil, &size, &id) == noErr, let bundle = id?.takeRetainedValue() as String? else { return nil }
        return callApps.first { bundle.hasPrefix($0.key) }?.value
    })
}
var onMicSince: [String: Date] = [:], callNudged = Set<String>(), callSeen = false, callGone: Date?
func checkMic() {
    // The call app let go of the mic (hung up): end the meeting like End does. Grace covers a mute that briefly drops input.
    if meeting.running, callApps.values.contains(meeting.callApp) {
        if callAppsOnMic().contains(meeting.callApp) { callSeen = true; callGone = nil }
        else if callSeen, let gone = callGone, Date().timeIntervalSince(gone) >= 2 { callSeen = false; callGone = nil; meeting.stop() }
        else if callSeen && callGone == nil { callGone = Date() }
    } else { callSeen = false; callGone = nil }
    guard Prefs.bool("meeting"), Prefs.bool("meetingDetect"), !Prefs.bool("paused") else { onMicSince = [:]; return }
    let now = callAppsOnMic()
    onMicSince = onMicSince.filter { now.contains($0.key) }; callNudged.formIntersection(now)   // a call that ends can be noticed again next time
    for a in now where onMicSince[a] == nil { onMicSince[a] = Date() }
    guard !meeting.running, meeting.panel == nil else { callNudged.formUnion(now); return }   // already open for this call
    guard let a = onMicSince.first(where: { !callNudged.contains($0.key) && Date().timeIntervalSince($0.value) >= 3 })?.key else { return }
    callNudged.insert(a)
    showNudge(["title": a == "Slack" ? "Huddle detected" : "Meeting detected", "when": "In \(a) · Want Atticus to listen?", "who": "", "context": "", "app": a])
}
Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { _ in checkMic() }
let app = App()
let onboarding = Onboarding()
if !UserDefaults.standard.bool(forKey: "onboarded") { DispatchQueue.main.async { onboarding.open() } }
else { Onboarding.plan { c in if c["ok"] as? Bool != true { onboarding.open() } } }   // set up once, but Claude signed out since
var specs = [EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
             EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased))]
InstallEventHandler(GetApplicationEventTarget(), { _, ev, _ in
    let pressed = GetEventKind(ev) == UInt32(kEventHotKeyPressed)
    var hk = EventHotKeyID()
    GetEventParameter(ev, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil, MemoryLayout<EventHotKeyID>.size, nil, &hk)
    DispatchQueue.main.async { hk.id == 2 ? (pressed ? app.escape() : ()) : app.shortcut(pressed) }
    return noErr
}, 2, &specs, nil, nil)
var ref: EventHotKeyRef?
@discardableResult func registerHotkey() -> Bool {   // false: another app already owns that shortcut
    if let r = ref { UnregisterEventHotKey(r); ref = nil }
    let h = hotkey()
    return RegisterEventHotKey(UInt32(h.code), UInt32(h.mods), EventHotKeyID(signature: 0x41545443, id: 1), GetApplicationEventTarget(), 0, &ref) == noErr
}
registerHotkey()
if Prefs.bool("speak") { siriVoice() }
let settings = SettingsWindow()
let bar = MenuBar()
let delegate = Delegate()
NSApplication.shared.delegate = delegate
Updater.schedule()

// Test hook: `defaults write com.atticus.app demo -string "<request>"` then restart runs it once without the mic.
if let demo = UserDefaults.standard.string(forKey: "demo") {
    UserDefaults.standard.removeObject(forKey: "demo")
    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { app.js("listen"); app.show(); app.js("words", demo); app.run(demo) }
}

// ⌘X/C/V/A/Z in every Atticus text field (typing box, choices, Settings, meetings): a menu-bar-less app has no Edit
// menu to route them, and a non-activating panel never gets menu shortcuts anyway, so send them down the responder chain.
NSEvent.addLocalMonitorForEvents(matching: .keyDown) { e in
    let mods = e.modifierFlags.intersection(.deviceIndependentFlagsMask), k = e.charactersIgnoringModifiers?.lowercased() ?? ""
    let action: Selector? = mods == [.command, .shift] ? (k == "z" ? Selector(("redo:")) : nil) : mods != .command ? nil :
        ["x": #selector(NSText.cut(_:)), "c": #selector(NSText.copy(_:)), "v": #selector(NSText.paste(_:)), "a": #selector(NSText.selectAll(_:)), "z": Selector(("undo:"))][k]
    guard let action, NSApp.sendAction(action, to: nil, from: nil) else { return e }
    return nil
}
NSApplication.shared.setActivationPolicy(.accessory)
NSApplication.shared.run()
