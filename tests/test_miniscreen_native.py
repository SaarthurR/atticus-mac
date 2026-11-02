"""Mini screen tests use isolated WebKit and colored fixture windows; never the installed app."""
import functools
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import statistics
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
import Cocoa
import WebKit
import AVFoundation
import ScreenCaptureKit

enum Prefs { static func str(_ key: String) -> String { "back" } }
__NATIVE__
let app = NSApplication.shared; app.setActivationPolicy(.accessory)
let activity = ProcessInfo.processInfo.beginActivity(options: [.userInitiated, .idleDisplaySleepDisabled], reason: "Atticus isolated window fixtures")
let mode = CommandLine.arguments[1]
if mode == "cover" || mode == "activation" || mode == "exact" { app.setActivationPolicy(.regular) }
if mode == "exact" {
    let rect=NSRect(x:40,y:40,width:600,height:375),height=NSScreen.screens.first!.frame.height,pid=ProcessInfo.processInfo.processIdentifier
    let target=NSWindow(contentRect:rect,styleMask:[.titled],backing:.buffered,defer:false),other=NSWindow(contentRect:rect,styleMask:[.titled],backing:.buffered,defer:false)
    target.title="Atticus exact target";other.title="Atticus same-frame window"
    target.orderFrontRegardless();other.makeKeyAndOrderFront(nil)
    DispatchQueue.main.asyncAfter(deadline:.now()+0.3) {
        let f=target.frame
        MiniScreen().open(["pid":pid,"windowID":String(target.windowNumber),"windowFrame":[Double(f.minX),Double(height-f.maxY),Double(f.width),Double(f.height)]])
        DispatchQueue.main.asyncAfter(deadline:.now()+0.5) {
            precondition(NSWorkspace.shared.frontmostApplication?.processIdentifier == pid,"Mini click did not bring its app forward")
            precondition(app.keyWindow === target,"Mini click did not key its exact window: \(app.keyWindow?.title ?? "none")")
            print("exact window keyed over a same-frame window; AX trusted: \(AXIsProcessTrusted())");exit(0)
        }
    }
    app.run()
}
if mode == "cover" {
    let cover=NSWindow(contentRect:NSRect(x:100,y:100,width:300,height:200),styleMask:[.titled],backing:.buffered,defer:false)
    cover.title="Atticus activation cover";cover.makeKeyAndOrderFront(nil)
    MiniScreen.activate(ProcessInfo.processInfo.processIdentifier)
    print("READY");fflush(stdout);app.run()
}
if mode == "activation" {
    let target=NSWindow(contentRect:NSRect(x:40,y:40,width:600,height:375),styleMask:[.titled],backing:.buffered,defer:false)
    let other=NSWindow(contentRect:NSRect(x:40,y:40,width:600,height:375),styleMask:[.titled],backing:.buffered,defer:false)   // same frame: only the window number tells them apart
    target.title="Atticus exact activation target";other.title="Atticus other activation window"
    target.orderFrontRegardless();other.orderFrontRegardless()
    let mini=MiniScreen(),pid=ProcessInfo.processInfo.processIdentifier
    let f=target.frame,height=NSScreen.screens.first!.frame.height
    mini.target=["pid":pid,"windowID":String(target.windowNumber),"windowFrame":[Double(f.minX),Double(height-f.maxY),Double(f.width),Double(f.height)]]
    DispatchQueue.main.asyncAfter(deadline:.now()+0.3) {
        let coverPID=Int32(CommandLine.arguments[2])!
        MiniScreen.activate(coverPID)
        precondition(NSWorkspace.shared.frontmostApplication?.processIdentifier == coverPID,"Cover did not activate")
        mini.open()
        DispatchQueue.main.asyncAfter(deadline:.now()+0.3) {
            precondition(NSWorkspace.shared.frontmostApplication?.processIdentifier == pid,"Mini click did not activate its running process")
            if AXIsProcessTrusted() { precondition(app.orderedWindows.first === target,"Mini click raised the wrong window") }
            let key = app.keyWindow === target
            precondition(app.keyWindow !== other,"Mini click keyed a different window at the same frame")
            MiniScreen.activate(coverPID)
            precondition(NSWorkspace.shared.frontmostApplication?.processIdentifier == coverPID,"Guard did not restore the working app")
            print("background process activation, mini handoff and focus restoration ok; AX trusted: \(AXIsProcessTrusted()); exact window key: \(key)");exit(0)
        }
    }
    app.run()
}
let panel = NSWindow(contentRect:NSRect(x:20,y:40,width:460,height:760),styleMask:[.borderless],backing:.buffered,defer:false)
panel.isReleasedWhenClosed = false
let mini = MiniScreen()
if mode == "ui" {
    let web = WKWebView(frame:panel.contentView!.bounds)
    panel.contentView!.addSubview(web); panel.orderFrontRegardless()
    web.load(URLRequest(url:URL(string:CommandLine.arguments[2])!))
    var tries = 0
    Timer.scheduledTimer(withTimeInterval:0.25,repeats:true) { timer in
        tries += 1
        web.evaluateJavaScript("document.getElementById('results')?.textContent") { result, error in
            guard let text = result as? String else { return }
            if text.contains("checks passed") || text.contains("✗") {
                print(text); timer.invalidate(); exit(text.contains("✗") ? 1 : 0)
            }
        }
        if tries > 120 { print("UI fixture timed out"); exit(1) }
    }
} else if mode == "target" {
    let window = NSPanel(contentRect:NSRect(x:40,y:40,width:800,height:500),styleMask:[.borderless,.nonactivatingPanel],backing:.buffered,defer:false)
    let strip = NSPanel(contentRect:NSRect(x:0,y:0,width:1920,height:30),styleMask:[.borderless,.nonactivatingPanel],backing:.buffered,defer:false)
    for p in [window,strip] {p.level = .normal;p.isReleasedWhenClosed=false;p.sharingType = .none;p.ignoresMouseEvents=true;p.alphaValue=0.01;p.orderFrontRegardless()}
    DispatchQueue.main.asyncAfter(deadline:.now()+0.25) {
        let infos = [strip,window].flatMap {CGWindowListCopyWindowInfo(.optionIncludingWindow,CGWindowID($0.windowNumber)) as? [[String:Any]] ?? []}
        guard infos.count == 2, MiniScreen.windowTarget(.current,windows:infos)?["windowID"] as? String == String(window.windowNumber) else {print("Wrong owned-window target: \(infos)");exit(1)}
        print("Real Cocoa 1920x30 helper strip skipped; owned 800x500 window selected");exit(0)
    }
} else {
    let info: (UInt32,CGRect,Int32) -> [String:Any] = { id,frame,pid in
        [kCGWindowNumber as String:id,kCGWindowBounds as String:frame.dictionaryRepresentation,kCGWindowOwnerPID as String:pid,kCGWindowAlpha as String:1]
    }
    let rect = CGRect(x:10,y:10,width:300,height:200), display = CGRect(x:0,y:0,width:1440,height:900)
    let target = info(42,rect,123), coverInfo = info(43,rect,456), hud = info(44,CGRect(x:250,y:150,width:100,height:100),456)
    precondition(!MiniScreen.needsPreview(pid:123,id:42,windows:[target],displays:[display]))
    precondition(!MiniScreen.needsPreview(pid:123,id:42,windows:[hud,target],displays:[display]),"A corner overlay hid a visible window")
    precondition(MiniScreen.needsPreview(pid:123,id:42,windows:[coverInfo,target],displays:[display]))
    precondition(MiniScreen.needsPreview(pid:123,id:42,windows:[],displays:[display]))
    precondition(MiniScreen.needsPreview(pid:123,id:42,windows:[target],displays:[CGRect(x:1440,y:0,width:1440,height:900)]))
    precondition(!MiniScreen.needsPreview(pid:123,id:42,windows:[target],displays:[CGRect(x:1440,y:0,width:1440,height:900),display]),"A window on another awake display is visible")
    let wide=MiniScreen.configuration(CGRect(x:0,y:0,width:1000,height:100)), tall=MiniScreen.configuration(CGRect(x:0,y:0,width:100,height:1000))
    precondition(wide.width == 600 && wide.height == 60 && tall.width == 38 && tall.height == 375)
    precondition(!wide.showsCursor && wide.minimumFrameInterval == CMTime(value:1,timescale:12))
    if mode == "visibility" { print("visibility selftest ok"); exit(0) }
    guard CGPreflightScreenCaptureAccess() else { print("SKIP: scratch binary lacks Screen Recording; no permission requested"); exit(77) }
    let window = NSWindow(contentRect:NSRect(x:40,y:40,width:600,height:375),styleMask:[.titled],backing:.buffered,defer:false)
    window.title = "Mini screen animated fixture"; window.isReleasedWhenClosed = false
    window.contentView!.wantsLayer = true
    let label = NSTextField(labelWithString:"BACKGROUND FIXTURE"); label.frame = NSRect(x:30,y:170,width:500,height:50); label.font = .systemFont(ofSize:28); window.contentView!.addSubview(label)
    window.orderFrontRegardless()
    let cover = NSWindow(contentRect:window.frame,styleMask:[.borderless],backing:.buffered,defer:false)
    cover.isReleasedWhenClosed = false; cover.backgroundColor = .black; cover.level = .floating; cover.orderFrontRegardless()
    panel.contentView!.addSubview(mini.clip); panel.orderFrontRegardless()
    var tick = 0, measured = false, start = 0
    Timer.scheduledTimer(withTimeInterval:0.083,repeats:true) { _ in
        tick += 1; label.stringValue = "BACKGROUND FIXTURE \(tick)"
        window.contentView!.layer?.backgroundColor = NSColor(calibratedRed:Double(tick % 20)/20,green:0.25,blue:0.4,alpha:1).cgColor
    }
    mini.publish = { value in
        mini.layout(["rect":[16.0,80.0,300.0,187.5],"clip":[0.0,0.0,460.0,760.0],"opacity":1.0])
        guard mini.live, !measured else { return }; measured = true; start = mini.frames
        if mode == "stream" {
            DispatchQueue.main.asyncAfter(deadline:.now() + 1) {
                let count = mini.frames - start
                precondition(count >= 5,"Expected five covered-window frames, got \(count)")
                precondition(mini.picture.sampleBufferRenderer.status == .rendering,"Native layer must render the buffers")
                mini.finish(); precondition(mini.stream == nil,"Completion must stop streaming immediately")
                print("covered fixture: \(count) complete frames in 1 s; stream stops on finish")
                DispatchQueue.main.asyncAfter(deadline:.now() + 2.6) { precondition(mini.target != nil && mini.lastSample != nil && mini.holds); mini.reset(); precondition(mini.target == nil); exit(0) }
            }
        }
    }
    if mode != "baseline" {
        DispatchQueue.main.asyncAfter(deadline:.now() + 0.4) {
            let f = window.frame, height = NSScreen.screens.first?.frame.height ?? 900
            mini.receive(["pid":ProcessInfo.processInfo.processIdentifier,"windowID":String(window.windowNumber),"windowFrame":[Double(f.minX),Double(height - f.maxY),Double(f.width),Double(f.height)],"window":window.title,"app":"Fixture","action":"click"])
        }
    }
    if mode == "baseline" || mode == "cpu" {
        print("READY \(ProcessInfo.processInfo.processIdentifier)"); fflush(stdout)
        DispatchQueue.main.asyncAfter(deadline:.now() + 25) { mini.reset(); exit(0) }
    } else {
        DispatchQueue.main.asyncAfter(deadline:.now() + 15) { print("Stream timed out: \(mini.frames) frames"); exit(1) }
    }
}
app.run()
'''


@unittest.skipUnless(sys.platform == 'darwin', 'macOS window capture/WebKit fixture')
class MiniScreenNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name); cls.binary = cls.root / 'Atticus'
        cls.env = {**os.environ, 'ATTICUS_DIR':str(cls.root), 'ATTICUS_RESOURCES_DIR':str(ROOT)}
        swift = (ROOT / 'Atticus.swift').read_text()
        ax = swift[swift.index('func axAttribute('):swift.index('struct TextSelection')]
        mini = swift[swift.index('final class PassView:'):swift.index('final class App:')]
        source = cls.root / 'main.swift'; source.write_text(HARNESS.replace('__NATIVE__',ax + mini))
        result = subprocess.run(['swiftc','-O',str(source),'-o',str(cls.binary)],capture_output=True,text=True,env=cls.env)
        if result.returncode: raise AssertionError(result.stderr)

    def test_background_activation_and_mini_window_handoff(self):
        try:   # activation goes through System Events; without Automation permission osascript waits on a prompt nobody can click (the VM)
            subprocess.run(['osascript','-e','tell application "System Events" to count processes'],capture_output=True,timeout=3,check=True)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError): self.skipTest('System Events automation not allowed here')
        cover =subprocess.Popen([str(self.binary),'cover'],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(cover.stdout.readline().strip(),'READY')
            result = subprocess.run([str(self.binary),'activation',str(cover.pid)],env=self.env,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout.strip(),flush=True)
        finally:
            cover.terminate();cover.communicate(timeout=5)

    def test_click_keys_the_exact_window_without_system_events(self):
        result = subprocess.run([str(self.binary),'exact'],env=self.env,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        print(result.stdout.strip(),flush=True)

    def test_visibility(self):
        result = subprocess.run([str(self.binary),'visibility'],env=self.env,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stdout + result.stderr)

    def test_real_cocoa_helper_strip_does_not_replace_the_content_window(self):
        result = subprocess.run([str(self.binary),'target'],env=self.env,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stdout + result.stderr)
        print(result.stdout.strip(),flush=True)

    def test_covered_window_stream(self):
        result = subprocess.run([str(self.binary),'stream'],env=self.env,capture_output=True,text=True,timeout=20)
        if result.returncode == 77: self.skipTest(result.stdout.strip())
        self.assertEqual(result.returncode,0,result.stdout + result.stderr)
        print(result.stdout.strip(),flush=True)

    @unittest.skipUnless(os.environ.get('ATTICUS_MINISCREEN_CPU') == '1', 'Opt-in 20 s CPU benchmark per mode')
    def test_cpu_cost(self):
        averages = {}
        for mode in ('baseline', 'cpu'):
            process = subprocess.Popen([str(self.binary),mode],env=self.env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                line = process.stdout.readline()
                if 'SKIP:' in line: self.skipTest(line.strip())
                self.assertIn('READY',line)
                time.sleep(1)
                readings = []
                for _ in range(20):
                    result = subprocess.run(['ps','-p',str(process.pid),'-o','%cpu='],capture_output=True,text=True,env=self.env,check=True)
                    readings.append(float(result.stdout)); time.sleep(1)
                averages[mode] = statistics.mean(readings)
                if mode == 'cpu':
                    self.assertGreater(averages[mode],0)
            finally:
                if process.poll() is None: process.terminate()
                process.communicate(timeout=5)
        print(f'MINISCREEN CPU (20 one-second ps samples): off {averages["baseline"]:.2f}%, on {averages["cpu"]:.2f}%, extra {averages["cpu"]-averages["baseline"]:.2f} percentage points',flush=True)

    def test_webkit_interactions(self):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(ROOT))
        server = http.server.ThreadingHTTPServer(('127.0.0.1',0),handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            result = subprocess.run([str(self.binary),'ui',f'http://127.0.0.1:{server.server_port}/tests/ui.html'],env=self.env,capture_output=True,text=True,timeout=40)
            self.assertEqual(result.returncode,0,result.stdout + result.stderr)
            print(result.stdout.strip().splitlines()[-1],flush=True)
        finally: server.shutdown(); server.server_close(); thread.join()

    def test_target_selection_and_minimized_fallback_with_fake_ax(self):
        swift = (ROOT / 'Atticus.swift').read_text()
        mini = swift[swift.index('final class PassView:'):swift.index('final class App:')]
        stub = r'''
import Cocoa
import AVFoundation
import ScreenCaptureKit
let node = AXUIElementCreateApplication(ProcessInfo.processInfo.processIdentifier)
var minimized = false
func axAttribute(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
 switch name {
 case kAXWindowsAttribute: return [node] as CFArray
 case kAXFocusedWindowAttribute: return node
 case kAXMinimizedAttribute: return NSNumber(value:minimized)
 case kAXTitleAttribute: return "Hidden Notes" as CFString
 default: return nil
 }
}
func axWindowNumber(_ element: AXUIElement) -> NSNumber? { NSNumber(value:42) }
'''
        start_at=swift.index('    func start(dictate: Bool, quiet: Bool = false)')
        body_at=swift.index('        drawingReply = !dictate',start_at)
        start='    func start() { let dictate = false\n'+swift[body_at:swift.index('        guard !Prefs.bool("paused")',start_at)]+'    }\n'
        starter='''enum Prefs { static func bool(_ name:String)->Bool { false }; static func str(_ name:String)->String { "back" } }
final class EngineStub { var isRunning=false }
final class PanelStub { var isVisible=false }
final class DrawingStub { var active=false,hasInput=false,clears=0;func clear() {clears += 1;active=false;hasInput=false};func stopVoice() {} }
final class Starter {
 let drawing=DrawingStub();var drawingReply=false
 let mini=MiniScreen(),engine=EngineStub(),panel=PanelStub();var busy=false,fresh=false,retryOffer=false,askFile="",agentCard="",replyAgent="",focusFile=NSTemporaryDirectory()+"atticus-focus-fixture"
 func shush() {}
 func hush(keepReply:Bool) {if !keepReply {drawingReply=false}}
 func dismiss() {}
 func cancel() {}
 func cancelFast() {}
''' + start + '}\n'
        check = r'''
let app=NSApplication.shared;app.setActivationPolicy(.accessory)
let pid=ProcessInfo.processInfo.processIdentifier, rect=CGRect(x:10,y:10,width:300,height:200)
func info(_ id:UInt32,_ title:String,_ layer:Int=0)->[String:Any] {
 [kCGWindowNumber as String:id,kCGWindowBounds as String:rect.dictionaryRepresentation,kCGWindowOwnerPID as String:pid,kCGWindowLayer as String:layer,kCGWindowName as String:title]
}
let candidates=[info(41,"Budget"),info(42,"Notes"),info(43,"Popup",3)]
precondition(MiniScreen.windowTarget(.current,windows:candidates)?["windowID"] as? String == "42")
precondition(MiniScreen.windowTarget(.current,title:"Budget",windows:candidates)?["windowID"] as? String == "41")
precondition(MiniScreen.windowTarget(.current,title:"Popup",windows:candidates) == nil)
var moved=info(41,"Budget");moved[kCGWindowBounds as String]=CGRect(x:500,y:100,width:400,height:300).dictionaryRepresentation
precondition(MiniScreen.windowTarget(.current,screen:CGRect(x:400,y:0,width:600,height:600),windows:[info(42,"Notes"),moved])?["windowID"] as? String == "41",
             "Request-display targeting ignored the window on that display")
precondition(MiniScreen.windowTarget(.current,frame:[500,100,400,300],windows:[info(42,"Notes"),moved])?["windowID"] as? String == "41", "Pinned bounds must beat the app's focused window")
precondition(MiniScreen.windowTarget(.current,frame:[999,100,400,300],windows:candidates) == nil,"Never preview an unrelated window")
// apps own invisible full-width strips listed before their real window; AX-known windows win, else the largest
let strip:[String:Any]=[kCGWindowNumber as String:40,kCGWindowBounds as String:CGRect(x:0,y:0,width:1000,height:30).dictionaryRepresentation,kCGWindowOwnerPID as String:pid,kCGWindowLayer as String:0]
precondition(MiniScreen.windowTarget(.current,windows:[strip,info(42,"Notes")])?["windowID"] as? String == "42")
precondition(MiniScreen.windowTarget(.current,windows:[strip,info(44,"Other")])?["windowID"] as? String == "44")
var hidden=info(42,"Notes");hidden.removeValue(forKey:kCGWindowName as String)
precondition(MiniScreen.windowTarget(.current,title:"Hidden Notes",windows:[hidden])?["windowID"] as? String == "42")
let mini=MiniScreen();var events=[[String:Any]]();mini.publish={events.append($0)}
mini.target=["pid":pid,"windowID":"42","windowFrame":[10.0,10.0,300.0,200.0],"app":"Fixture","window":"Notes","minimized":false]
mini.live=true;minimized=true;mini.refresh()
precondition(mini.target?["minimized"] as? Bool == true && !mini.live && mini.stream == nil)
precondition(events.last?["live"] as? Bool == false && events.last?["shown"] as? Bool == true)
minimized=false;mini.starting=true;mini.refresh()
precondition(mini.target?["minimized"] as? Bool == false && events.last?["minimized"] as? Bool == false)
mini.reset();
let starter=Starter();starter.mini.target=["pid":pid,"windowID":"42"];starter.mini.shown=true
precondition(starter.mini.holds);starter.start();precondition(starter.mini.target == nil && !starter.mini.holds)
let guide=Starter();guide.drawing.active=true;guide.start()
precondition(guide.drawing.active && guide.drawingReply && guide.drawing.clears == 0,"Starting a spoken guide reply cleared the guide")
print("target, minimized fallback and next-ask release fixture ok")
'''
        source=self.root/'minimized.swift';source.write_text(stub+mini+starter+check)
        binary=self.root/'minimized'
        result=subprocess.run(['swiftc',str(source),'-o',str(binary)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        result=subprocess.run([str(binary)],env=self.env,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__ == '__main__': unittest.main()
