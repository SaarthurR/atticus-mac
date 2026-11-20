"""Opt-in live checks of setup's System Settings hand-off, VM only: the real helper against the real System Settings,
and which app macOS returns to after a permission popup. run.sh <repo> tests.shoot_setup_probe"""
import base64
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'Atticus.swift').read_text()
PRELUDE = r'''import Cocoa
import AVFoundation
setvbuf(stdout,nil,_IONBF,0)
func applySharing(_ w:NSWindow) {}
enum MiniScreen { static func bounds(_ info:[String:Any])->CGRect? { (info[kCGWindowBounds as String] as? NSDictionary).flatMap { CGRect(dictionaryRepresentation:$0) } } }
enum MeetingFrame {
''' + SOURCE[SOURCE.index('    static func clamp(', SOURCE.index('enum MeetingFrame')):SOURCE.index('    static func key(', SOURCE.index('enum MeetingFrame'))] + '''}
func after(_ s:Double,_ f:@escaping()->Void){DispatchQueue.main.asyncAfter(deadline:.now()+s,execute:f)}
let pane="x-apple.systempreferences:com.apple.preference.security?Privacy_"
func settingsApp()->NSRunningApplication?{NSRunningApplication.runningApplications(withBundleIdentifier:"com.apple.systempreferences").first}
func onScreen()->[[String:Any]]{CGWindowListCopyWindowInfo(.optionOnScreenOnly,kCGNullWindowID) as? [[String:Any]] ?? []}
func settingsWindows()->String{
 guard let pid=settingsApp()?.processIdentifier else{return "not running"}
 let mine=onScreen().filter{($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value==pid}
 return mine.isEmpty ? "no windows" : mine.map{w in let b=MiniScreen.bounds(w) ?? .zero
  return "L\\(w[kCGWindowLayer as String] as? Int ?? -1) \\(Int(b.minX)),\\(Int(b.minY)) \\(Int(b.width))x\\(Int(b.height))"}.joined(separator:" | ")}
func quitSettings(_ then:@escaping()->Void){
 settingsApp()?.forceTerminate()
 func wait(_ n:Int){if settingsApp()==nil||n>50{after(0.5,then)}else{after(0.1){wait(n+1)}}}
 wait(0)}
let fixture=NSWindow(contentRect:NSRect(x:80,y:80,width:640,height:560),styleMask:[.titled,.closable],backing:.buffered,defer:false)
fixture.title="Setup fixture";fixture.isReleasedWhenClosed=false
func front()->String{NSWorkspace.shared.frontmostApplication?.localizedName ?? "none"}
func order()->String{   // which is nearer the front: setup's window or System Settings' window
 let ws=onScreen(),pid=settingsApp()?.processIdentifier
 let me=ws.firstIndex{($0[kCGWindowNumber as String] as? NSNumber)?.intValue==fixture.windowNumber}
 let them=ws.firstIndex{($0[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value==pid && ($0[kCGWindowLayer as String] as? Int)==0}
 guard let me else{return "setup hidden"};guard let them else{return "settings hidden"}
 return me<them ? "setup in front" : "settings in front"}
'''

HELPER = r'''
NSApplication.shared.setActivationPolicy(.accessory)
let help=PermissionHelp()
struct Step{let name:String,quit:Bool,pane:String,delay:Double,front:Bool,away:Bool,shot:String,listed:Bool}
var steps:[Step]=[]
for r in 1...ROUNDS {
 let s=r==1
 steps+=[Step(name:"r\(r) fresh Accessibility",quit:true,pane:"Accessibility",delay:0,front:false,away:false,shot:s ? "helper-accessibility" : "",listed:false),
  Step(name:"r\(r) second click Screen (Settings on Accessibility)",quit:false,pane:"ScreenCapture",delay:0,front:true,away:false,shot:s ? "helper-screen" : "",listed:false),
  Step(name:"r\(r) second click Screen again",quit:false,pane:"ScreenCapture",delay:0,front:true,away:false,shot:"",listed:false),
  Step(name:"r\(r) second click Accessibility (Settings on Screen)",quit:false,pane:"Accessibility",delay:0,front:true,away:false,shot:"",listed:false),
  Step(name:"r\(r) first request Screen, Settings opened later",quit:true,pane:"ScreenCapture",delay:2,front:true,away:false,shot:"",listed:false),
  Step(name:"r\(r) first request Accessibility, Settings already open elsewhere",quit:false,pane:"Accessibility",delay:2,front:true,away:false,shot:"",listed:false),
  Step(name:"r\(r) Screen, Settings leaves the screen for a moment",quit:false,pane:"ScreenCapture",delay:0,front:true,away:true,shot:"",listed:false),
  Step(name:"r\(r) Accessibility, Settings leaves the screen for a moment",quit:false,pane:"Accessibility",delay:0,front:true,away:true,shot:s ? "helper-accessibility-back" : "",listed:false),
  Step(name:"r\(r) Screen, Atticus already in the list",quit:false,pane:"ScreenCapture",delay:0,front:true,away:false,shot:s ? "helper-screen-listed" : "",listed:true)]
}
var failed:[String]=[]
func snap(_ name:String){   // the whole screen: the helper over the real pane
 let p=Process();p.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture");p.arguments=["-x",OUT+"/"+name+".png"];try? p.run();p.waitUntilExit();print("shot \(name)")}
func run(_ i:Int){
 guard i<steps.count else{print("HELPER SUMMARY \(steps.count-failed.count)/\(steps.count) shown and kept");failed.forEach{print("HELPER MISSED \($0)")};exit(0)}
 let s=steps[i]
 let go={
  if s.front{NSApp.activate(ignoringOtherApps:true);fixture.makeKeyAndOrderFront(nil)}
  let open={_=NSWorkspace.shared.open(URL(string:pane+s.pane)!)}
  if s.delay==0{open();help.show(drag:true,target:"Atticus",granted:{false})}
  else{help.show(drag:true,target:"Atticus",granted:{false});after(s.delay,open)}
  if s.away{after(1.5){settingsApp()?.hide()};after(2.5){settingsApp()?.unhide();settingsApp()?.activate()}}   // ⌘H, a Space or Stage Manager: gone, then back
  if s.listed{after(1.0){help.listed()}}
  if !s.shot.isEmpty{after(s.delay+(s.away ? 4.0 : 1.8)){snap(s.shot)}}
  var t=0.0,shown:Double?=nil,lost:Double?=nil,offSince:Double?=nil,last=""
  func sample(){
   let visible=help.panel?.isVisible==true && onScreen().contains{($0[kCGWindowNumber as String] as? NSNumber)?.intValue==help.panel?.windowNumber}
   let settingsUp=settingsWindows().hasPrefix("L")
   if visible && shown==nil{shown=t}
   offSince=visible || !settingsUp ? nil : offSince ?? t
   if let o=offSince,shown != nil,lost==nil,t-o>0.7{lost=o}   // off while Settings is up, longer than one check: nothing to drag
   let w=settingsWindows()+(visible ? " · helper on" : " · helper off");if w != last{print("  \(s.name) t=\(String(format:"%.1f",t)) \(w)");last=w}
   t+=0.1
   if t<s.delay+5{after(0.1,sample);return}
   let ok=shown != nil && lost==nil
   print("STEP \(ok ? "ok  " : "MISS") \(s.name): shown \(shown.map{String(format:"%.1f s",$0)} ?? "never") lost \(lost.map{String(format:"%.1f s",$0)} ?? "no")")
   if !ok{failed.append(s.name)}
   help.close();after(0.4){run(i+1)}}
  sample()}
 if s.quit{quitSettings(go)}else{go()}}
after(0.5){run(0)}
after(Double(steps.count)*8+20){print("helper probe watchdog");exit(2)}
NSApplication.shared.run()
'''

FOCUS = r'''
let policy=CommandLine.arguments.count>1 && CommandLine.arguments[1]=="regular" ? NSApplication.ActivationPolicy.regular : .accessory
NSApplication.shared.setActivationPolicy(policy)
print("policy \(policy == .regular ? "regular" : "accessory") ax=\(AXIsProcessTrusted())")
func popup(_ n:Int,_ done:@escaping()->Void){   // another app's popup takes focus and closes, as macOS's permission box does
 NSApp.activate(ignoringOtherApps:true);fixture.makeKeyAndOrderFront(nil)
 after(1.0){
  print("FOCUS \(n) before popup: front=\(front()), \(order())")
  let p=Process();p.executableURL=URL(fileURLWithPath:"/usr/bin/osascript");p.arguments=["-e","display dialog \"Permission popup\" giving up after 2"]
  p.terminationHandler={_ in DispatchQueue.main.async{AFTER_POPUP;after(0.8){after(0.8){print("FOCUS \(n) after popup: front=\(front()), \(order())");done()}}}}
  try! p.run()}}
func round(_ n:Int){
 guard n<=3 else{print("focus probe ok");exit(0)}
 _=NSWorkspace.shared.open(URL(string:pane+"Accessibility")!)
 after(3.0){popup(n){round(n+1)}}}
quitSettings{round(1)}
after(100){print("focus probe watchdog");exit(2)}
NSApplication.shared.run()
'''


POPUPS = r'''
import Speech
NSApplication.shared.setActivationPolicy(.accessory)
func settingsFront()->Bool{NSWorkspace.shared.frontmostApplication?.bundleIdentifier=="com.apple.systempreferences"}
// One permission: the request the setup row makes (status first: a popup only while macOS can still ask), answered by its button.
func ask(_ name:String,status:@escaping()->String,request:@escaping(@escaping(Bool)->Void)->Void,_ next:@escaping()->Void){
 NSApp.activate(ignoringOtherApps:true);fixture.makeKeyAndOrderFront(nil)
 after(1.0){
  let before=status(),asking=NSApp.keyWindow
  print("POPUP \(name) status before: \(before), front=\(front()), \(order())")
  var settingsCameUp=false,answered=false
  request{ok in DispatchQueue.main.async{answered=true;ANSWERED;after(1.0){
   print("POPUP \(name) answered ok=\(ok) status=\(status()) front=\(front()), \(order()), Settings fronted while asking: \(settingsCameUp)");next()}}}
  func watch(_ n:Int){if !answered{if settingsFront(){settingsCameUp=true};if n<200{after(0.1){watch(n+1)}}}}
  watch(0)}}
let mic={ ["notDetermined","restricted","denied","authorized"][AVCaptureDevice.authorizationStatus(for:.audio).rawValue] }
let speech={ ["notDetermined","denied","restricted","authorized"][SFSpeechRecognizer.authorizationStatus().rawValue] }
quitSettings{
 _=NSWorkspace.shared.open(URL(string:pane+"Accessibility")!)   // the Accessibility row, first on the page, left Settings open
 after(3.0){
  ask("Microphone",status:mic,request:{d in AVCaptureDevice.requestAccess(for:.audio,completionHandler:d)}){
   ask("Speech Recognition",status:speech,request:{d in SFSpeechRecognizer.requestAuthorization{d($0 == .authorized)}}){
    print("popup probe done");exit(0)}}}}
after(60){print("popup probe watchdog");exit(2)}
NSApplication.shared.run()
'''


CLICK = r'''import Cocoa
// macOS's own box (260 wide, Don't Allow and Allow along its bottom), clicked where he clicks it
var box:[String:Any]?
for _ in 0..<50 {
 box=(CGWindowListCopyWindowInfo(.optionOnScreenOnly,kCGNullWindowID) as? [[String:Any]] ?? []).first{($0[kCGWindowOwnerName as String] as? String)=="UserNotificationCenter" && ($0[kCGWindowLayer as String] as? Int ?? 0)>0}
 if box != nil{break};usleep(200_000)}
guard let box,let r=(box[kCGWindowBounds as String] as? NSDictionary).flatMap({CGRect(dictionaryRepresentation:$0)}) else{print("no popup");exit(1)}
let at=CGPoint(x:CommandLine.arguments[1]=="allow" ? r.maxX-71 : r.minX+71,y:r.maxY-29)
for t in [CGEventType.leftMouseDown,.leftMouseUp]{CGEvent(mouseEventSource:nil,mouseType:t,mouseCursorPosition:at,mouseButton:.left)?.post(tap:.cghidEventTap);usleep(80_000)}
print("\(box[kCGWindowOwnerName as String] ?? "?") \(Int(r.width))x\(Int(r.height)) clicked \(CommandLine.arguments[1]) at \(Int(at.x)),\(Int(at.y))")
'''


def answer(clicker, button):   # from the test, which may post clicks; the probe app may not
    run = subprocess.run([str(clicker), button], capture_output=True, text=True, timeout=15)
    return (run.stdout + run.stderr).strip()

def bundle(tmp, name, ident, driver, extra=None):
    app = Path(tmp) / f'{name}.app' / 'Contents'
    binary = app / 'MacOS' / 'Atticus'
    binary.parent.mkdir(parents=True)
    (app / 'Resources').mkdir()
    shutil.copy(ROOT / 'ui/AppIcon.icns', app / 'Resources/AppIcon.icns')
    (app / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'Atticus', 'CFBundleIdentifier': ident, 'CFBundleName': 'Atticus',
                                                     'CFBundleIconFile': 'AppIcon', **(extra or {})}))
    swift = Path(tmp) / f'{name}.swift'; swift.write_text(driver)
    built = subprocess.run(['swiftc', str(swift), '-o', str(binary)], capture_output=True, text=True)
    return binary, built


@unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'live System Settings: VM only')
class SetupProbe(unittest.TestCase):
    def test_helper_against_real_settings(self):
        help_source = SOURCE[SOURCE.index('final class PermissionIcon:'):SOURCE.index('// `Atticus --look')]
        out = ROOT / 'test-artifacts' / 'setup-probe'; out.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            driver = PRELUDE + help_source + HELPER.replace('ROUNDS', os.environ.get('PROBE_ROUNDS', '3')).replace('OUT+', f'"{out}"+')
            binary, built = bundle(tmp, 'Helper', 'local.atticus.setup-probe', driver)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=260)
            subprocess.run(['killall', 'System Settings'], capture_output=True)
        print(run.stdout, flush=True)
        for png in sorted(out.glob('*.png')): print('PNG', png.name, base64.b64encode(png.read_bytes()).decode(), flush=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn('HELPER MISSED', run.stdout)

    def test_focus_after_popup(self):
        line = SOURCE.index('    static func back(to w: NSWindow?)') if 'static func back(to w: NSWindow?)' in SOURCE else -1
        after = 'enum Onboarding {\n' + SOURCE[line:SOURCE.index('\n', line) + 1] + '}\n' if line >= 0 else ''
        out = []
        with tempfile.TemporaryDirectory() as tmp:
            binary, built = bundle(tmp, 'Focus', 'local.atticus.focus-probe', PRELUDE + after + FOCUS.replace('AFTER_POPUP', 'Onboarding.back(to: fixture)' if after else '()'))
            self.assertEqual(built.returncode, 0, built.stderr)
            for policy in ('accessory', 'regular'):
                run = subprocess.run([str(binary), policy], capture_output=True, text=True, timeout=120)
                out.append(run.stdout)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            subprocess.run(['killall', 'System Settings'], capture_output=True)
        print('\n'.join(out), flush=True)
        if after:
            self.assertNotIn('after popup: front=System Settings', '\n'.join(out))

    def test_real_mic_and_speech_popups(self):
        line = SOURCE.index('    static func back(to w: NSWindow?)')
        back = 'enum Onboarding {\n' + SOURCE[line:SOURCE.index('\n', line) + 1] + '}\n'
        usage = {'NSMicrophoneUsageDescription': 'Probe', 'NSSpeechRecognitionUsageDescription': 'Probe'}
        runs = {}
        out = ROOT / 'test-artifacts' / 'setup-probe'; out.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            clicker = Path(tmp) / 'click'; (Path(tmp) / 'click.swift').write_text(CLICK)
            self.assertEqual(subprocess.run(['swiftc', str(Path(tmp) / 'click.swift'), '-o', str(clicker)]).returncode, 0)
            for variant, answered in (('without back(to:)', '()'), ('with back(to:)', 'Onboarding.back(to: asking)')):
                ident = f'local.atticus.popup-probe.{os.getpid()}.{len(runs)}'   # never asked before: macOS can still show its popup
                tag = 'fixed' if runs else 'before'
                binary, built = bundle(tmp, f'Popups{len(runs)}', ident, PRELUDE + back + POPUPS.replace('ANSWERED', answered), usage)
                self.assertEqual(built.returncode, 0, built.stderr)
                # opened by LaunchServices, so macOS asks for this app, not for the shell that runs the tests
                log = Path(tmp) / f'popups{len(runs)}.log'; log.touch()
                opened = subprocess.Popen(['open', '-W', '-n', '--stdout', str(log), '--stderr', str(log), str(binary.parents[2])])
                clicks = []
                for name, button in (('Microphone', 'allow'), ('Speech Recognition', 'deny')):
                    deadline = time.time() + 30
                    while f'POPUP {name} status before' not in log.read_text() and time.time() < deadline: time.sleep(0.2)
                    time.sleep(2.0)
                    subprocess.run(['screencapture', '-x', str(out / f'popup-{name.split()[0].lower()}-{tag}.png')])
                    clicks.append(f'{name}: {answer(clicker, button)}')
                    time.sleep(0.8)   # answered, before the probe's next ask brings its window forward again
                    subprocess.run(['screencapture', '-x', str(out / f'popup-{name.split()[0].lower()}-answered-{tag}.png')])
                    time.sleep(1.7)
                try: opened.wait(timeout=30)
                except subprocess.TimeoutExpired: opened.kill()
                subprocess.run(['pkill', '-f', str(binary)], capture_output=True)
                subprocess.run(['killall', 'System Settings'], capture_output=True)
                runs[variant] = log.read_text() + '\n'.join(clicks)
                print(f'== {variant}\n' + runs[variant], flush=True)
        for png in sorted(out.glob('popup-*.png')): print('PNG', png.name, base64.b64encode(png.read_bytes()).decode(), flush=True)
        for variant, run in runs.items():
            self.assertIn('popup probe done', run)
            self.assertIn('POPUP Microphone status before: notDetermined', run)
            self.assertIn('POPUP Speech Recognition status before: notDetermined', run)
        before, fixed = runs['without back(to:)'], runs['with back(to:)']
        self.assertIn('POPUP Microphone answered ok=true status=authorized front=System Settings, settings in front', before)   # his bug, live
        self.assertNotIn('Settings fronted while asking: true', fixed)
        self.assertIn('POPUP Microphone answered ok=true status=authorized front=Atticus, setup in front', fixed)
        self.assertIn('POPUP Speech Recognition answered ok=false status=denied front=Atticus, setup in front', fixed)


if __name__ == '__main__':
    unittest.main()
