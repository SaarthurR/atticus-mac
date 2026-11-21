"""Motion clips of the box, Settings and setup, VM only (opt-in, not discovered: run this module by name).

run.sh ~/Projects/atticus tests.shoot_motion  → screen recordings printed as base64 lines ("MOV <name> <data>").
The box is the app's glass panel with the real page; its fade and height follow the app's own rule (the `Motion`
timings when the tree has them, else the old instant resize).
"""
import base64
import json
import unittest
from tests.shoot_settings import PREFS, STATE, PERMS, ROUTINES, DICTATION
from tests.shoot_agents_design import ROOT
from tests.test_agents_native import run_fixture

SOURCE = (ROOT / 'Atticus.swift').read_text()
MOTION = 'enum Motion' in SOURCE
RESIZE = ('if box.isVisible && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion { Motion.run(Motion.fast, { box.animator().setFrame(f, display: true) }) { box.invalidateShadow() } } else { box.setFrame(f, display: true) }'
          if MOTION else 'box.setFrame(f, display: true)')
FADE_IN = ('Motion.fade(box, in: true)' if MOTION else
           'box.alphaValue = 0; box.orderFrontRegardless(); NSAnimationContext.runAnimationGroup { $0.duration = 0.18; box.animator().alphaValue = 1 }')
FADE_OUT = ('Motion.fade(box, in: false)' if MOTION else
            'NSAnimationContext.runAnimationGroup({ $0.duration = 0.2; box.animator().alphaValue = 0 }, completionHandler: { box.orderOut(nil) })')
ANSWER = ('Short answer: yes. A standing desk helps most when you switch between sitting and standing every 30 to 60 minutes. '
          'Look for a frame that stays steady at your standing height, a quiet motor, and a desktop deep enough for your screen.')

BODY = r'''setvbuf(stdout,nil,_IONBF,0)
let agentsUI=AgentPanels()
let nsapp=NSApplication.shared;nsapp.setActivationPolicy(.accessory)
let out="OUTDIR",screen=NSScreen.screens[0],top=screen.frame.maxY
func after(_ s:Double,_ f:@escaping()->Void){DispatchQueue.main.asyncAfter(deadline:.now()+s,execute:f)}
let back=NSWindow(contentRect:screen.frame,styleMask:[.borderless],backing:.buffered,defer:false);let paint=CAGradientLayer();paint.frame=screen.frame
paint.colors=[NSColor(srgbRed:0.16,green:0.20,blue:0.36,alpha:1).cgColor,NSColor(srgbRed:0.30,green:0.16,blue:0.30,alpha:1).cgColor,NSColor(srgbRed:0.06,green:0.07,blue:0.10,alpha:1).cgColor];paint.startPoint=CGPoint(x:0,y:1);paint.endPoint=CGPoint(x:1,y:0)
let backView=NSView(frame:screen.frame);backView.wantsLayer=true;backView.layer=paint;back.contentView=backView;back.orderFrontRegardless()
final class Sink:NSObject,WKScriptMessageHandler{var onH:(CGFloat)->Void={_ in}
 func userContentController(_ c:WKUserContentController,didReceive m:WKScriptMessage){
  guard m.name=="h",let n=(m.body as? [NSNumber])?.last ?? (m.body as? NSNumber) else{return};onH(CGFloat(n.doubleValue))}}
let sink=Sink()
// The box: 340 pt of dark HUD glass with the page on top, its top edge fixed, as the app shows it.
let boxCfg=WKWebViewConfiguration();for n in ["c","h"]{boxCfg.userContentController.add(sink,name:n)}
let box=NSPanel(contentRect:NSRect(x:screen.visibleFrame.minX+14,y:screen.visibleFrame.maxY-10-120,width:340,height:120),styleMask:[.nonactivatingPanel,.borderless],backing:.buffered,defer:false)
box.isOpaque=false;box.backgroundColor = .clear;box.hasShadow=true;box.level = .floating
let glass=NSVisualEffectView(frame:NSRect(x:0,y:0,width:340,height:120));glass.material = .hudWindow;glass.state = .active;glass.appearance=NSAppearance(named:.darkAqua);glass.wantsLayer=true;glass.layer?.cornerRadius=18;glass.layer?.masksToBounds=true;glass.autoresizingMask=[.width,.height]
let web=WKWebView(frame:glass.bounds,configuration:boxCfg);web.setValue(false,forKey:"drawsBackground");web.autoresizingMask=[.width,.height];glass.addSubview(web);box.contentView=glass
web.loadHTMLString((try! String(contentsOfFile:dir+"/ui/ui.html",encoding:.utf8)).replacingOccurrences(of:"/*TOKENS*/",with:(try? String(contentsOfFile:dir+"/ui/tokens.css",encoding:.utf8)) ?? "").replacingOccurrences(of:"/*ORBS*/",with:(try! String(contentsOfFile:dir+"/ui/orbs.js",encoding:.utf8))),baseURL:nil)
sink.onH={h in guard h>0 else{return};var f=box.frame;f.origin.y=f.maxY-h;f.size.height=h;guard f != box.frame else{return}
 RESIZE}
func boxJS(_ s:String){web.evaluateJavaScript(s){_,e in if let e{print("box js error \(e)")}}}
func boxShow(){FADE_IN}
func boxHide(){FADE_OUT}
// Settings and setup: the real pages in titled windows, as SettingsWindow and the first-run window open them,
// low on the screen, clear of any system alert another run left up in the shared VM.
func page(_ file:String,_ size:NSSize,_ handler:String,_ x:CGFloat)->(NSWindow,WKWebView){
 let w=NSWindow(contentRect:NSRect(x:x,y:screen.visibleFrame.minY+20,width:size.width,height:size.height),styleMask:[.titled,.closable,.fullSizeContentView],backing:.buffered,defer:false)
 w.titlebarAppearsTransparent=true;w.titleVisibility = .hidden
 let bg=NSVisualEffectView(frame:w.contentRect(forFrameRect:w.frame));bg.material = .underWindowBackground;bg.blendingMode = .behindWindow;bg.state = .active
 let cfg=WKWebViewConfiguration();cfg.userContentController.add(sink,name:handler)
 let v=WKWebView(frame:NSRect(x:0,y:0,width:size.width,height:size.height-28),configuration:cfg);v.setValue(false,forKey:"drawsBackground");v.autoresizingMask=[.width,.height]
 v.loadHTMLString((try! String(contentsOfFile:dir+"/ui/"+file,encoding:.utf8)).replacingOccurrences(of:"/*TOKENS*/",with:(try? String(contentsOfFile:dir+"/ui/tokens.css",encoding:.utf8)) ?? "").replacingOccurrences(of:"/*ORBS*/",with:(try? String(contentsOfFile:dir+"/ui/orbs.js",encoding:.utf8)) ?? ""),baseURL:nil)
 bg.addSubview(v);w.contentView=bg;return (w,v)}
let (sw,sv)=page("settings.html",NSSize(width:780,height:560),"st",60)
let (ow,ov)=page("onboarding.html",NSSize(width:640,height:640),"ob",60)
func js(_ v:WKWebView,_ s:String){v.evaluateJavaScript(s){_,e in if let e{print("js error \(e)")}}}
// One take of the whole screen while every scene plays on one clock: the VM's screencapture often never starts
// a second or third short recording, so the scenes are cut from the take on the host ("scene <name> <s> <x,y,w,h>",
// seconds into the take give or take its start-up, rect in top-left points). A take that never starts is tried once more.
func take(_ name:String,_ secs:Double,retry:Bool=true,_ steps:@escaping()->Void,_ done:@escaping()->Void){
 let p=Process();p.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture")
 p.arguments=["-x","-v","-V","\(Int(secs.rounded(.up)))",out+"/"+name+".mov"]
 p.terminationHandler={_ in DispatchQueue.main.async{let ok=FileManager.default.fileExists(atPath:out+"/"+name+".mov");print("take \(name) \(p.terminationStatus) \(ok)")
  if !ok && retry{after(1.0){take(name,secs,retry:false,steps,done)}}else{after(0.3,done)}}}
 try! p.run();print("recording \(name)")
 after(secs+1.5){if p.isRunning{print("screencapture ran over, stopping: \(name)");p.interrupt()}}   // SIGINT ends a recording and keeps the movie
 after(secs+8){if p.isRunning{print("screencapture stuck: \(name)");p.terminate()}}
 steps()}
let boxRect=NSRect(x:box.frame.minX,y:screen.visibleFrame.maxY-10-420,width:340,height:420)
let answer=#"ANSWER"#
var stream:[(Double,()->Void)]=[(0,{boxJS("ui.reset();ui.visible(true);ui.listen(false)");boxShow()}),
 (0.5,{boxJS("ui.words('What should I look for in a standing desk?')")}),(0.6,{boxJS("ui.think()")}),(0.6,{boxJS("ui.line('▸ Searching the web: standing desks')")})]
let cut=answer.split(separator:" ");for i in stride(from:3,to:cut.count,by:3){let part=cut[0..<i].joined(separator:" ");stream.append((0.12,{boxJS("ui.line('… "+part+"')")}))}
stream+=[(0.2,{boxJS("ui.line('✓ "+answer+"')")}),(1.4,{boxJS("ui.visible(false)");boxHide()})]
let clips:[(String,NSRect,Int,[(Double,()->Void)])]=[
 ("box-open-stream-close",boxRect,8,stream),
 ("box-card",boxRect,5,[(0,{boxJS("ui.reset();ui.visible(true);ui.listen(true);ui.words('Delete the old notes on my desktop');ui.think()");boxShow()}),
  (1.0,{boxJS("ui.ask(['Delete this file?','rm ~/Desktop/old-notes.txt','','',''])")}),(1.6,{boxJS("document.querySelector('.ok .no, .ok button:not(.go)')?.click()")}),(0.8,{boxHide()})]),
 ("settings-toggle-segment",sw.frame,5,[(0,{sw.orderFrontRegardless()}),
  (0.7,{js(sv,"document.querySelector('#general .seg button:not(.on)').click()")}),(0.7,{js(sv,"document.querySelector('#general .seg button:not(.on)').click()")}),   // Typing hides "Shortcut behavior", Voice brings it back
  (0.6,{js(sv,"document.querySelector('#general .sw').scrollIntoView({block:'center'})")}),(0.5,{js(sv,"document.querySelector('#general .sw input').click()")}),(0.7,{js(sv,"document.querySelector('#general .sw input').click()")})]),
 ("settings-reduce",sw.frame,4,[(0,{js(sv,"st.motion(true);document.querySelector('main').scrollTop=0")}),(0.4,{js(sv,"document.querySelector('#general .seg button:not(.on)').click()")}),(0.7,{js(sv,"document.querySelector('#general .seg button:not(.on)').click()")}),
  (0.7,{js(sv,"document.querySelector('nav button[data-s=brain]').click()")}),(0.8,{js(sv,"document.querySelector('nav button[data-s=general]').click();st.motion(false)")})]),
 ("settings-pages",sw.frame,4,[(0.3,{js(sv,"document.querySelector('nav button[data-s=brain]').click()")}),(0.9,{js(sv,"document.querySelector('nav button[data-s=memory]').click()")}),
  (0.9,{js(sv,"document.querySelector('nav button[data-s=general]').click()")}),(0.6,{sw.orderOut(nil)})]),
 ("setup-steps",ow.frame,4,[(0,{ow.orderFrontRegardless()}),(0.5,{js(ov,"document.getElementById('start').click()")}),(1.0,{js(ov,"document.getElementById('next').click()")}),(1.0,{js(ov,"document.getElementById('next').click()")})])]
func scenes(){var base=1.0
 for (name,rect,secs,steps) in clips{let f=rect.insetBy(dx:-30,dy:-30).intersection(screen.frame)
  print("scene \(name) \(base) \(Int(f.minX)),\(Int(top-f.maxY)),\(Int(f.width)),\(Int(f.height))")
  var t=base;for (d,s) in steps{t+=d;after(t,s)};base+=Double(secs)+1}}
func warm(){take("warm-up",1,retry:false,{}){take("take",clips.reduce(1.0){$0+Double($1.2)+1},scenes){print("motion clips ok");exit(0)}}}
let setup=#"const PREFS=PREFS_JSON,STATE=STATE_JSON;st.load({prefs:PREFS,state:STATE,routines:ROUTINES_JSON});st.perms(PERMS_JSON);st.dictation(DICTATION_JSON);st.tab('general');"#
func ready(_ tries:Int){
 sv.evaluateJavaScript("typeof st"){v,_ in ov.evaluateJavaScript("typeof ob"){o,_ in web.evaluateJavaScript("typeof ui"){u,_ in
  guard v as? String=="object",o as? String=="object",u as? String=="object" else{if tries>60{print("pages never loaded");exit(1)};after(0.5){ready(tries+1)};return}
  print("pages ready");js(sv,setup);js(ov,"ob.plan({ok:true,text:'Signed in. Claude Max.'});ob.set({mic:true,speech:true,ax:true,screen:false,auto:true,chrome:false,calendar:false,tools:true})")
  after(1.0){warm()}}}}}
print("screen \(screen.frame)");after(1.0){ready(0)}
after(190){print("motion watchdog: gave up");exit(2)}   // the fixture's 120 s limit would swallow this output
nsapp.run()'''


class MotionClips(unittest.TestCase):
    def test_clips(self):
        out = ROOT / 'test-artifacts' / 'motion'; out.mkdir(parents=True, exist_ok=True)
        for old in out.glob('*.mov'): old.unlink()
        body = (BODY.replace('OUTDIR', str(out)).replace('RESIZE', RESIZE).replace('FADE_IN', FADE_IN).replace('FADE_OUT', FADE_OUT)
                .replace('ANSWER', ANSWER).replace('PREFS_JSON', json.dumps(PREFS)).replace('STATE_JSON', json.dumps(STATE))
                .replace('ROUTINES_JSON', json.dumps(ROUTINES)).replace('PERMS_JSON', json.dumps(PERMS)).replace('DICTATION_JSON', json.dumps(DICTATION)))
        run_fixture(self, body, 'motion clips ok', timeout=200)
        for mov in sorted(out.glob('*.mov')):
            if mov.name == 'take.mov': print('MOV', mov.name, base64.b64encode(mov.read_bytes()).decode(), flush=True)


if __name__ == '__main__':
    unittest.main()
