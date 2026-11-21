"""Design screenshots of the real agent shelf and Agent view, VM only (opt-in, not discovered: run this module by name).

run.sh ~/Projects/atticus tests.shoot_agents_design  → PNGs in the VM's ~/atticus/test-artifacts/design.
"""
import json
import time
import unittest
from pathlib import Path
from tests.test_agents_native import ROOT, run_fixture

NOW = time.time()
DOC = 'https://docs.google.com/document/d/1FixtureDocIdForDesignShots0000000/edit'
SRC = {k: {'url': u, 'title': t, 'domain': u.split('/')[2]} for k, u, t in [
    ('rtings', 'https://www.rtings.com/headphones/reviews/best/by-feature/noise-cancelling', 'The 6 Best Noise Cancelling Headphones'),
    ('verge', 'https://www.theverge.com/headphones/best-noise-canceling', 'The best noise-canceling headphones'),
    ('sound', 'https://www.soundguys.com/best-noise-cancelling-headphones/', 'Best noise cancelling headphones'),
    ('bestbuy', 'https://www.bestbuy.com/site/searchpage.jsp?st=wh-1000xm6', 'www.bestbuy.com'),
    ('oracle', 'https://ebikeoracle.com/best/best-lightweight-electric-bikes', 'Best lightweight electric bikes')]}
RESULT = '''I checked current Amazon listings against a review roundup. These are the five cheapest in-stock e-bikes that publish a weight.

| Bike | Price | Weight | Battery |
|---|---|---|---|
| Jasion EB5 26" | $199 | 50 lb | 360 Wh |
| RPINT Mini 14 (folding) | $199 | 55 lb | 480 Wh |
| Vivi MT26 | $289 | 49 lb | 288 Wh |
| Hiboy C1 | $329 | 41 lb | 216 Wh |
| Gotrax Vibe | $349 | 46 lb | 270 Wh |

**Best value:** the RPINT Mini has the biggest battery for the price. Prices change daily, so check each listing before you buy.
[agent-result {"summary":"Found the 5 cheapest e-bikes and put the comparison in a new Google Doc."}]'''
ROWS = [
    {'id': 'a' * 32, 'title': 'Compare noise-cancelling headphones', 'brief': 'Find the best noise-cancelling headphones under $400 with measured isolation, and compare current prices.',
     'status': 'running', 'step': 'Reading bestbuy.com', 'created': NOW - 95, 'started': NOW - 94, 'directory': '/tmp/fixture',
     'steps': ['Searching the web: best noise cancelling headphones measurements', 'Reading rtings.com', 'Reading bestbuy.com'],
     'plan': ['Find measured reviews', 'Shortlist five models', 'Check current prices', 'Write the comparison'], 'completed': 2,
     'sources': [SRC['bestbuy'], SRC['rtings'], SRC['verge']],
     'timeline': [{'text': 'Looking for reviews that actually measure noise cancelling.'},
                  {'tool': 'WebSearch', 'text': 'Searching the web: best noise cancelling headphones measurements'},
                  {'sources': [SRC['rtings'], SRC['sound'], SRC['verge']]},
                  {'tool': 'WebFetch', 'text': 'Reading rtings.com', 'sources': [SRC['rtings']]},
                  {'tool': 'WebFetch', 'text': 'Reading theverge.com', 'sources': [SRC['verge']]},
                  {'text': 'Sony and Bose lead on measured isolation. Checking current prices.'},
                  {'tool': 'Bash', 'text': 'Reading bestbuy.com', 'sources': [SRC['bestbuy']]}]},
    {'id': 'b' * 32, 'title': 'Send Thursday schedule', 'brief': 'Email the crew Thursday’s shoot schedule from the shared doc.', 'status': 'needs-you', 'step': 'Waiting for you',
     'created': NOW - 40, 'started': NOW - 40, 'directory': '/tmp/fixture', 'steps': ['Using Google Drive'],
     'question': {'q': 'Send this email with Gmail?', 'cmd': 'To: crew@studio.example\nSubject: Thursday shoot schedule\n\nHi all, call time is 7:30 at Pier 70. Full schedule attached.', 'task': True, '_a': 'answers/fixture'},
     'timeline': [{'tool': 'mcp__claude_ai_Google_Drive__read_file_content', 'text': 'Using Google Drive'}, {'text': 'Drafted the email from the schedule doc.'}]},
    {'id': 'c' * 32, 'title': 'Cheapest e-bikes on Amazon', 'brief': 'Find the 5 cheapest e-bikes on Amazon, list price, weight and battery, then put the comparison in a new Google Doc.',
     'status': 'done', 'step': 'Done', 'created': NOW - 400, 'started': NOW - 399, 'ended': NOW - 368, 'seen': False, 'directory': '/tmp/fixture', 'cost': .1861,
     'summary': 'Found the 5 cheapest e-bikes and put the comparison in a new Google Doc.', 'result': RESULT, 'changes': '',
     'made': [{'title': 'Cheapest E-Bikes on Amazon – Comparison', 'url': DOC, 'type': 'application/vnd.google-apps.document'}, {'title': 'ebikes.csv', 'url': '/tmp/fixture/ebikes.csv', 'type': ''}],
     'links': [DOC], 'sources': [SRC['oracle']],
     'timeline': [{'text': 'Searching Amazon for cheap e-bikes.'}, {'tool': 'WebSearch', 'text': 'Searching the web: cheapest electric bike amazon price weight battery'},
                  {'tool': 'WebFetch', 'text': 'Reading ebikeoracle.com', 'sources': [SRC['oracle']]}, {'text': 'Five bikes publish a weight; writing the Doc.'},
                  {'tool': 'mcp__claude_ai_Google_Drive__create_file', 'text': 'Using Google Drive'}, {'made': [{'title': 'Cheapest E-Bikes on Amazon – Comparison', 'url': DOC, 'type': 'application/vnd.google-apps.document'}]}]},
    {'id': 'd' * 32, 'title': 'Book a table at Nopa', 'brief': 'Book a table for two at Nopa on Friday around 8pm.', 'status': 'failed',
     'step': 'OpenTable didn’t load, so nothing was booked. Try again in a minute.', 'result': 'OpenTable didn’t load, so nothing was booked.', 'created': NOW - 300, 'started': NOW - 299, 'ended': NOW - 280,
     'directory': '/tmp/fixture', 'timeline': [{'tool': 'WebSearch', 'text': 'Searching the web: Nopa reservations Friday'}, {'tool': 'WebFetch', 'text': 'Reading opentable.com'}]},
]

BODY = r'''let nsapp=NSApplication.shared;nsapp.setActivationPolicy(.accessory)
let out="OUTDIR"
let rows=try! JSONSerialization.jsonObject(with:Data(#"ROWS"#.utf8)) as! [[String:Any]]
let screen=NSScreen.screens[0]
// A dark, wallpaper-like backdrop so the glass reads as it does on a real desktop.
let back=NSWindow(contentRect:screen.frame,styleMask:[.borderless],backing:.buffered,defer:false);let paint=CAGradientLayer();paint.frame=screen.frame
paint.colors=[NSColor(srgbRed:0.16,green:0.20,blue:0.36,alpha:1).cgColor,NSColor(srgbRed:0.30,green:0.16,blue:0.30,alpha:1).cgColor,NSColor(srgbRed:0.06,green:0.07,blue:0.10,alpha:1).cgColor];paint.startPoint=CGPoint(x:0,y:1);paint.endPoint=CGPoint(x:1,y:0)
let backView=NSView(frame:screen.frame);backView.wantsLayer=true;backView.layer=paint;back.contentView=backView;back.orderFrontRegardless()
CGWarpMouseCursorPosition(CGPoint(x:120,y:screen.frame.height-120))   // far from the shelf, which fades near the cursor
let agentsUI=AgentPanels()
func after(_ s:Double,_ f:@escaping()->Void){DispatchQueue.main.asyncAfter(deadline:.now()+s,execute:f)}
func shot(_ name:String,_ w:NSWindow?){guard let w else{print("missing window \(name)");exit(1)};w.sharingType = .readOnly;   // real panels hide from capture; only this VM fixture lifts it
let p=Process();p.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture");let f=w.frame.insetBy(dx:-36,dy:-36).intersection(screen.frame),r="\(Int(f.minX)),\(Int(screen.frame.maxY-f.maxY)),\(Int(f.width)),\(Int(f.height))";p.arguments=["-x","-R"+r,out+"/"+name+".png"];try! p.run();p.waitUntilExit();print("shot \(name)")}
func hover(_ id:String){agentsUI.shelfWeb?.evaluateJavaScript("(r=>agents.pointer([r.x+r.width/2,r.y+r.height/2]))(document.querySelector('.chip[data-id=\"\(id)\"]').getBoundingClientRect())")}
func select(_ id:String){agentsUI.js("view","select",id)}
let ids=rows.map{$0["id"] as! String}
agentsUI.receive(["event":"list","agents":rows]);agentsUI.ensureShelf()
after(2.0){agentsUI.receive(["event":"state","agent":rows[1]])}
after(3.5){shot("shelf-needs-you",agentsUI.shelf);hover(ids[0])
 after(1.0){shot("shelf-running",agentsUI.shelf);agentsUI.shelfWeb?.evaluateJavaScript("document.querySelector('.pill').click()"){_,_ in hover(ids[2])}   // the "✓ 2 done" pill opens the finished chips
  after(1.0){shot("shelf-done",agentsUI.shelf);Prefs.set("agentsHidden",true);agentsUI.openView(ids[0])
   after(3.0){shot("view-running",agentsUI.view);select(ids[1])
    after(1.2){shot("view-needs-you",agentsUI.view);select(ids[2])
     after(1.2){shot("view-done",agentsUI.view);select(ids[3])
      after(1.2){shot("view-failed",agentsUI.view);agentsUI.view?.setContentSize(NSSize(width:560,height:520));select(ids[2])
        after(1.2){shot("view-done-narrow",agentsUI.view);paint.colors=[NSColor.white.cgColor,NSColor.white.cgColor]
         agentsUI.view?.orderOut(nil);Prefs.set("agentsHidden",false);agentsUI.shelf?.orderFrontRegardless();agentsUI.shelfWeb?.evaluateJavaScript("document.querySelector('.pill')?.click()"){_,_ in hover(ids[1])}
         after(1.0){shot("shelf-white-backdrop",agentsUI.shelf);agentsUI.openView(ids[1])
          after(1.2){shot("view-white-backdrop",agentsUI.view);agentsUI.process?.terminate();print("design shots ok");exit(0)}}}}}}}}}}
nsapp.run()'''


class DesignShots(unittest.TestCase):
    def test_shoot(self):
        out = ROOT / 'test-artifacts' / 'design'; out.mkdir(parents=True, exist_ok=True)
        run_fixture(self, BODY.replace('OUTDIR', str(out)).replace('ROWS', json.dumps(ROWS)), 'design shots ok')


CARDS = r'''let agentsUI=AgentPanels()
let nsapp=NSApplication.shared;nsapp.setActivationPolicy(.accessory)
let out="OUTDIR",screen=NSScreen.screens[0]
let back=NSWindow(contentRect:screen.frame,styleMask:[.borderless],backing:.buffered,defer:false);let paint=CAGradientLayer();paint.frame=screen.frame
paint.colors=[NSColor(srgbRed:0.16,green:0.20,blue:0.36,alpha:1).cgColor,NSColor(srgbRed:0.30,green:0.16,blue:0.30,alpha:1).cgColor,NSColor(srgbRed:0.06,green:0.07,blue:0.10,alpha:1).cgColor];paint.startPoint=CGPoint(x:0,y:1);paint.endPoint=CGPoint(x:1,y:0)
let backView=NSView(frame:screen.frame);backView.wantsLayer=true;backView.layer=paint;back.contentView=backView;back.orderFrontRegardless()
final class Bridge:NSObject,WKScriptMessageHandler{var ready:()->Void={},got:[[String:Any]]=[];func userContentController(_ c:WKUserContentController,didReceive m:WKScriptMessage){if let b=m.body as? [String:Any]{got.append(b);if b["ready"] != nil{ready()}}}}
let bridge=Bridge(),config=WKWebViewConfiguration();config.userContentController.add(bridge,name:"c");config.userContentController.add(bridge,name:"h")
// The main box as the app shows it: 340 pt of dark HUD glass with the page on top.
let box=NSPanel(contentRect:NSRect(x:340,y:300,width:340,height:300),styleMask:[.nonactivatingPanel,.borderless],backing:.buffered,defer:false);box.isOpaque=false;box.backgroundColor = .clear;box.hasShadow=true;box.level = .floating
let glass=NSVisualEffectView(frame:NSRect(x:0,y:0,width:340,height:300));glass.material = .hudWindow;glass.state = .active;glass.appearance=NSAppearance(named:.darkAqua);glass.wantsLayer=true;glass.layer?.cornerRadius=18;glass.layer?.masksToBounds=true;glass.autoresizingMask=[.width,.height]
let web=WKWebView(frame:glass.bounds,configuration:config);web.setValue(false,forKey:"drawsBackground");web.autoresizingMask=[.width,.height];glass.addSubview(web);box.contentView=glass;box.orderFrontRegardless()
let html=try! String(contentsOfFile:dir+"/ui/ui.html",encoding:.utf8),orbs=try! String(contentsOfFile:dir+"/ui/orbs.js",encoding:.utf8)
web.loadHTMLString(html.replacingOccurrences(of:"/*TOKENS*/",with:(try? String(contentsOfFile:dir+"/ui/tokens.css",encoding:.utf8)) ?? "").replacingOccurrences(of:"/*ORBS*/",with:orbs),baseURL:nil)
func after(_ s:Double,_ f:@escaping()->Void){DispatchQueue.main.asyncAfter(deadline:.now()+s,execute:f)}
func shot(_ name:String,_ done:@escaping()->Void){web.evaluateJavaScript("document.getElementById('card').getBoundingClientRect().height"){value,_ in
 let h=CGFloat((value as? Double) ?? 300);var f=box.frame;f.origin.y=f.maxY-h;f.size.height=h;box.setFrame(f,display:true)
 after(0.5){let f=box.frame.insetBy(dx:-36,dy:-36),p=Process();p.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture");p.arguments=["-x","-R\(Int(f.minX)),\(Int(screen.frame.maxY-f.maxY)),\(Int(f.width)),\(Int(f.height))",out+"/"+name+".png"];try! p.run();p.waitUntilExit();print("shot \(name)");done()}}}
let row=#"ROW"#
// Each scene: the main box as the user meets it while agents exist.
let ask="ui.reset();ui.listen(true);ui.words('Find the five cheapest e-bikes on Amazon and put them in a Google Doc');ui.think();"
let scenes:[(String,String)]=[
 ("header-full-access","ui.reset();ui.agentCount(1);ui.mode(false);ui.think();document.querySelector('#status span').textContent='Thinking through a detailed background result';"),
 ("header-safe-mode","ui.mode(true);"),
 ("steer-confirmation","ui.reset();ui.listen(true);ui.words('Only include products under $200');ui.think();ui.agentSteered({...(\(row)),steer:{text:'Only include products under $200.'}});"),
 ("box-badge","ui.reset();ui.agentCount(2);ui.listen(true);ui.words('What is on my calendar this afternoon?');ui.think();ui.msg('A design review at 3:00 and a one-on-one with Maya at 4:30.');"),
 ("box-badge-needs-you","ui.agentCount({count:2,attention:true});"),
 ("done-card","ui.reset();ui.agentCount(1);ui.agentDone(\(row))")]
func play(_ i:Int){
 guard i<scenes.count else{
  // The done card lists what was made; a row opens that exact thing; Esc picks Later.
  web.evaluateJavaScript("[document.querySelectorAll('.agent-card .made button').length,document.querySelector('.agent-card .go span').textContent,document.querySelector('.agent-card [data-esc] kbd').textContent,document.querySelector('.agent-card .usage').textContent,document.querySelector('.agent-card .made small').textContent].join('|')"){v,_ in
   guard v as? String=="2|Open|esc|≈18.6¢ at API prices|Document · docs.google.com" else{print("done card wrong: \(v ?? "nil")");exit(1)}
   web.evaluateJavaScript("document.querySelector('.agent-card .made button').click()"){_,_ in after(0.2){
    guard bridge.got.contains(where:{($0["agentOpen"] as? String)==(ROWID) && ($0["target"] as? String)?.hasPrefix("https://docs.google.com/document/d/")==true}) else{print("made row did not open its target");exit(1)}
    print("card shots ok");exit(0)}}}
  return}
 web.evaluateJavaScript(scenes[i].1){_,error in guard error == nil else{print("scene failed: \(scenes[i].0): \(error!)");exit(1)};after(1.3){
  let check=i==0 ? "(()=>{const a=['status','agents-pill','mode','x'].map(x=>document.getElementById(x).getBoundingClientRect()),c=a.map(x=>x.y+x.height/2),s=document.querySelector('#status span');return Math.max(...c)-Math.min(...c)<1&&s.scrollWidth>s.clientWidth&&getComputedStyle(s).textOverflow==='ellipsis'})()" :
            i==2 ? "!!document.querySelector('.agent-ack canvas')&&document.querySelector('.agent-ack span').textContent==='Told the Cheapest e-bikes on Amazon agent: Only include products under $200.'" : "true"
  web.evaluateJavaScript(check){value,error in guard error == nil,value as? Bool == true else{print("scene check failed: \(scenes[i].0): \(String(describing:error)) \(String(describing:value))");exit(1)};shot(scenes[i].0){play(i+1)}}}}}
bridge.ready={after(1.0){play(0)}}
nsapp.run()'''


class CardShots(unittest.TestCase):
    def test_shoot(self):
        out = ROOT / 'test-artifacts' / 'design' / 'round2'; out.mkdir(parents=True, exist_ok=True)
        row = dict(ROWS[2], status='done')
        run_fixture(self, CARDS.replace('OUTDIR', str(out)).replace('ROWID', json.dumps(row['id'])).replace('ROW', json.dumps(row)), 'card shots ok')


PAGE = '''<body style="margin:0;font:13px -apple-system;background:#fff;color:#1d1d1f"><div style="padding:14px 18px;border-bottom:1px solid #eee;font-weight:600">Standing desks under $600</div><div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;padding:16px">''' + ''.join(
    f'<div style="border:1px solid #eee;border-radius:10px;padding:10px"><div style="height:80px;border-radius:6px;background:linear-gradient(135deg,{c},#ddd)"></div><b style="display:block;margin-top:8px">{n}</b><span style="color:#0071e3">{p}</span></div>'
    for n, p, c in [('FlexiSpot E7', '$499', '#c9b28f'), ('Uplift V2', '$579', '#8fa3c9'), ('Vari Electric', '$545', '#9fc98f'), ('Fully Jarvis', '$589', '#c98f9f'), ('Branch Duo', '$495', '#8fc9c4'), ('IKEA Trotten', '$369', '#c9c38f')]) + '</div></body>'
OFFER = {'id': 'e' * 32, 'title': 'Compare standing desks', 'brief': 'Find the best standing desks under $600 with a stable frame, and compare prices and warranties.', 'status': 'offered', 'created': NOW, 'directory': '/tmp/fixture'}

ROUND3 = r'''setvbuf(stdout,nil,_IONBF,0)   // prints survive a crash
let nsapp=NSApplication.shared;nsapp.setActivationPolicy(.accessory)
let out="OUTDIR",screen=NSScreen.screens[0],top=screen.frame.maxY
let back=NSWindow(contentRect:screen.frame,styleMask:[.borderless],backing:.buffered,defer:false);let paint=CAGradientLayer();paint.frame=screen.frame
paint.colors=[NSColor(srgbRed:0.16,green:0.20,blue:0.36,alpha:1).cgColor,NSColor(srgbRed:0.30,green:0.16,blue:0.30,alpha:1).cgColor,NSColor(srgbRed:0.06,green:0.07,blue:0.10,alpha:1).cgColor];paint.startPoint=CGPoint(x:0,y:1);paint.endPoint=CGPoint(x:1,y:0)
let backView=NSView(frame:screen.frame);backView.wantsLayer=true;backView.layer=paint;back.contentView=backView;back.orderFrontRegardless()
func move(_ p:CGPoint){CGEvent(mouseEventSource:CGEventSource(stateID:.hidSystemState),mouseType:.mouseMoved,mouseCursorPosition:p,mouseButton:.left)?.post(tap:.cghidEventTap)}
let away=CGPoint(x:300,y:top-60);CGWarpMouseCursorPosition(away)
// A stand-in browser window the window agent drives: real pixels for its live thumbnail.
let deskPage=NSHomeDirectory()+"/desks.html";try! ##"PAGE"##.write(toFile:deskPage,atomically:true,encoding:.utf8)   // Safari will not open files from /tmp
let safari=Process();safari.executableURL=URL(fileURLWithPath:"/usr/bin/open");safari.arguments=["-g","-a","Safari",deskPage];try! safari.run()
// The main box: the real ui.html in the stub app panel, so the orb lifts off the real card.
final class Bridge:NSObject,WKScriptMessageHandler{var ready:()->Void={};func userContentController(_ c:WKUserContentController,didReceive m:WKScriptMessage){if (m.body as? [String:Any])?["ready"] != nil{ready()}}}
let bridge=Bridge();app.web.configuration.userContentController.add(bridge,name:"c");app.web.configuration.userContentController.add(bridge,name:"h")
app.panel.setFrame(NSRect(x:24,y:top-36-330,width:340,height:330),display:true);app.panel.isOpaque=false;app.panel.backgroundColor = .clear;app.panel.level = .floating;app.panel.hasShadow=true
let glass=NSVisualEffectView(frame:NSRect(x:0,y:0,width:340,height:330));glass.material = .hudWindow;glass.state = .active;glass.appearance=NSAppearance(named:.darkAqua);glass.wantsLayer=true;glass.layer?.cornerRadius=18;glass.layer?.masksToBounds=true
app.web.frame=glass.bounds;app.web.autoresizingMask=[.width,.height];app.web.setValue(false,forKey:"drawsBackground");glass.addSubview(app.web);app.panel.contentView=glass;app.panel.orderFrontRegardless()
app.web.loadHTMLString((try! String(contentsOfFile:dir+"/ui/ui.html",encoding:.utf8)).replacingOccurrences(of:"/*TOKENS*/",with:(try? String(contentsOfFile:dir+"/ui/tokens.css",encoding:.utf8)) ?? "").replacingOccurrences(of:"/*ORBS*/",with:try! String(contentsOfFile:dir+"/ui/orbs.js",encoding:.utf8)),baseURL:nil)
let agentsUI=AgentPanels()
var rows=try! JSONSerialization.jsonObject(with:Data(#"ROWS"#.utf8)) as! [[String:Any]]
let offer=try! JSONSerialization.jsonObject(with:Data(#"OFFER"#.utf8)) as! [String:Any],offerID=offer["id"] as! String
agentsUI.receive(["event":"list","agents":rows+[offer]]);agentsUI.ensureShelf()
func after(_ s:Double,_ f:@escaping()->Void){DispatchQueue.main.asyncAfter(deadline:.now()+s,execute:f)}
func box(_ code:String,_ done:@escaping(Any?)->Void={_ in}){app.web.evaluateJavaScript(code){v,_ in done(v)}}
func shelfJS(_ code:String,_ done:@escaping(Any?)->Void={_ in}){agentsUI.shelfWeb?.evaluateJavaScript(code){v,_ in done(v)}}
func shoot(_ name:String,_ cocoa:NSRect){for w in [agentsUI.shelf,agentsUI.view,agentsUI.flight]{w?.sharingType = .readOnly}   // real panels hide from capture; only this VM fixture lifts it
 let f=cocoa.insetBy(dx:-30,dy:-30).intersection(screen.frame),p=Process();p.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture")
 p.arguments=["-x","-R\(Int(f.minX)),\(Int(top-f.maxY)),\(Int(f.width)),\(Int(f.height))",out+"/"+name+".png"];try! p.run();p.waitUntilExit();print("shot \(name)")}
func both()->NSRect{app.panel.frame.union(agentsUI.shelf!.frame)}
func chipCenter(_ id:String,_ done:@escaping(CGPoint)->Void){shelfJS("(r=>[r.x+r.width/2,r.y+22])(document.querySelector('.chip[data-id=\"\(id)\"]').getBoundingClientRect())"){v in guard let r=v as? [Double],let f=agentsUI.shelf?.frame else{print("chip \(id) not found");return};done(CGPoint(x:f.minX+r[0],y:top-(f.maxY-r[1])))}}
// The scene as a flat list of (wait, action) steps.
var steps:[(Double,()->Void)]=[],from:[Double]=[],point=CGPoint.zero
let winID=String(repeating:"f",count:32),offerJSON=String(data:try! JSONSerialization.data(withJSONObject:offer),encoding:.utf8)!
func run(_ i:Int){guard i<steps.count else{return};after(steps[i].0){steps[i].1();run(i+1)}}
steps.append((1.2,{box("ui.reset();ui.agentCount(2);ui.listen(true);ui.words('Compare standing desks under $600 for me');ui.think();ui.movePending()")}))
steps.append((1.4,{shoot("1-handoff",both());box("ui.moveSource()"){v in from=v as? [Double] ?? []}}))
steps.append((0.3,{agentsUI.flightPace=8;agentsUI.accept(offerID,from:from);box("ui.agentStarted()")
 after(0.5){box("document.getElementById('card').getBoundingClientRect().height"){v in var f=app.panel.frame;let h=CGFloat(v as? Double ?? 330);f.origin.y=f.maxY-h;f.size.height=h;app.panel.setFrame(f,display:true)}}}))   // the app sizes its box to the page; this stub does it once   // the swim at 1/8 speed, captured as frames
for i in 0..<7{steps.append((i==0 ? 0.25 : 0.62,{shoot("2-swim-\(i)",both().union(agentsUI.flight?.frame ?? .zero))}))}
steps.append((1.6,{agentsUI.flightPace=1;shoot("3-after-start",both());shelfJS("document.querySelector('.pill')?.click()")}))
steps.append((1.0,{shoot("4-shelf-open",agentsUI.shelf!.frame);chipCenter(offerID){point=$0}}))
steps.append((0.3,{move(point)}))
steps.append((1.0,{shoot("5-hover-controls",agentsUI.shelf!.frame);move(away)}))
steps.append((0.8,{
 let list=CGWindowListCopyWindowInfo([.optionOnScreenOnly,.excludeDesktopElements],kCGNullWindowID) as? [[String:Any]] ?? []
 let w=list.filter{($0[kCGWindowOwnerName as String] as? String)=="Safari" && ($0[kCGWindowLayer as String] as? Int)==0}.max{(($0[kCGWindowBounds as String] as? [String:Double])?["Width"] ?? 0)<(($1[kCGWindowBounds as String] as? [String:Double])?["Width"] ?? 0)}
 let b=w?[kCGWindowBounds as String] as? [String:Double] ?? [:]
 let target:[String:Any]=["pid":w?[kCGWindowOwnerPID as String] as? NSNumber ?? 0,"windowID":(w?[kCGWindowNumber as String] as? NSNumber)?.stringValue ?? "0","windowFrame":[b["X"] ?? 0,b["Y"] ?? 0,b["Width"] ?? 1,b["Height"] ?? 1],"window":w?[kCGWindowName as String] as? String ?? "Safari","app":"Safari"]
 print("window target \(target["windowID"]!) \(target["windowFrame"]!)")
 var win:[String:Any]=["id":winID,"title":"Order the FlexiSpot E7","brief":"Add the FlexiSpot E7 to the cart and stop before checkout.","status":"running","step":"Choosing the desk top","directory":"/tmp/fixture"]
 win["created"]=Date().timeIntervalSince1970;win["started"]=Date().timeIntervalSince1970;win["target"]=target;win["steps"]=["Opening the product page","Choosing the desk top"]
 win["timeline"]=[["tool":"mcp__hands","text":"Opening the product page"],["tool":"mcp__hands","text":"Choosing the desk top"]]
 agentsUI.receive(["event":"state","agent":win])}))
steps.append((5.5,{print("mini live \(agentsUI.mini.live) failed \(agentsUI.mini.failed) frames \(agentsUI.mini.frames) target \(agentsUI.mini.target != nil)");shoot("6-window-thumbnail",agentsUI.shelf!.frame);chipCenter(winID){point=$0}}))
steps.append((0.3,{move(point)}))
steps.append((2.0,{shoot("7-window-expanded",agentsUI.shelf!.frame);move(away)}))
steps.append((0.8,{shelfJS("document.querySelector('.chip .ctl button').click()")}))
steps.append((1.0,{shoot("8-minimized",agentsUI.shelf!.frame);Prefs.set("agentsHidden",true);agentsUI.openView(winID)}))
steps.append((3.0,{shoot("9-view-window",agentsUI.view!.frame);agentsUI.process?.terminate();print("round3 shots ok");exit(0)}))
bridge.ready={run(0)}
nsapp.run()'''


class Round3Shots(unittest.TestCase):
    def test_shoot(self):
        out = ROOT / 'test-artifacts' / 'design' / 'round3'; out.mkdir(parents=True, exist_ok=True)
        rows = [dict(ROWS[0], started=NOW - 95), dict(ROWS[2], seen=False)]
        run_fixture(self, ROUND3.replace('OUTDIR', str(out)).replace('PAGE', PAGE).replace('OFFER', json.dumps(OFFER)).replace('ROWS', json.dumps(rows)), 'round3 shots ok', real_mini=True)


# Round 4: setup asks on an agent's chip, steering, and the new setup screens.
ASKS = [dict(id='1' * 32, title='Fill the expense form', brief='Fill the expense form from the receipt photo.', status='needs-you', step='Waiting for you',
             created=NOW - 50, started=NOW - 50, directory='/tmp/fixture', steps=['Reading the form'],
             timeline=[{'tool': 'Bash', 'text': 'Reading the form'}],
             question={'need': 'screen', 'q': 'Turn on Screen Recording', 'cmd': 'To see the receipt photo on your screen.', 'app': '', '_a': 'answers/1'}),
        dict(id='2' * 32, title='Track the package', brief='Check where my package is on the carrier page.', status='needs-you', step='Waiting for you',
             created=NOW - 30, started=NOW - 30, directory='/tmp/fixture', steps=['Opening the tracking page'], timeline=[{'tool': 'Bash', 'text': 'Opening the tracking page'}],
             question={'need': 'page-js', 'q': 'I can turn on page reading in Google Chrome for you', 'cmd': 'To read the tracking page without bringing Chrome forward.', 'app': 'Google Chrome', '_a': 'answers/2'}),
        dict(id='3' * 32, title='Summarize unread email', brief='Summarize my unread email from today.', status='needs-you', step='Needs Gmail',
             created=NOW - 20, started=NOW - 80, ended=NOW - 20, directory='/tmp/fixture', steps=['Looking for a mail connector'], timeline=[{'tool': 'ToolSearch', 'text': 'Looking for a mail connector'}],
             question={'need': 'connector', 'q': 'Connect Gmail in Claude', 'cmd': 'Your inbox needs the Gmail connector. Everything else is ready.', 'app': 'Gmail', '_a': 'connector'})]
STEER = dict(ROWS[0], id='4' * 32, title='Find AC filter cart', brief='Find the cheapest, best-rated 24x24x1 AC filter 3-pack on Amazon and add it to the cart.', step='Reading the window',
             sources=[], plan=[], timeline=[{'text': 'Checking the current Amazon page.'}, {'tool': 'Bash', 'text': 'Reading the window'},
                                            {'user': 'For that AC filter agent, can you steer it? I meant 12 x 24, not 24 x 24?'}, {'text': 'Switching the search to 12x24x1.'}])

ROUND4 = r'''setvbuf(stdout,nil,_IONBF,0)
let nsapp=NSApplication.shared;nsapp.setActivationPolicy(.accessory)
let out="OUTDIR",screen=NSScreen.screens[0],top=screen.frame.maxY
let back=NSWindow(contentRect:screen.frame,styleMask:[.borderless],backing:.buffered,defer:false);let paint=CAGradientLayer();paint.frame=screen.frame
paint.colors=[NSColor(srgbRed:0.16,green:0.20,blue:0.36,alpha:1).cgColor,NSColor(srgbRed:0.30,green:0.16,blue:0.30,alpha:1).cgColor,NSColor(srgbRed:0.06,green:0.07,blue:0.10,alpha:1).cgColor];paint.startPoint=CGPoint(x:0,y:1);paint.endPoint=CGPoint(x:1,y:0)
let backView=NSView(frame:screen.frame);backView.wantsLayer=true;backView.layer=paint;back.contentView=backView;back.orderFrontRegardless()
CGWarpMouseCursorPosition(CGPoint(x:120,y:top-120))
func after(_ s:Double,_ f:@escaping()->Void){DispatchQueue.main.asyncAfter(deadline:.now()+s,execute:f)}
func shoot(_ name:String,_ cocoa:NSRect){for w in [agentsUI.shelf,agentsUI.view]{w?.sharingType = .readOnly}
 let f=cocoa.insetBy(dx:-30,dy:-30).intersection(screen.frame),p=Process();p.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture")
 p.arguments=["-x","-R\(Int(f.minX)),\(Int(top-f.maxY)),\(Int(f.width)),\(Int(f.height))",out+"/"+name+".png"];try! p.run();p.waitUntilExit();print("shot \(name)")}
func fail(_ t:String)->Never{print(t);agentsUI.process?.terminate();exit(1)}
let agentsUI=AgentPanels()
let asks=try! JSONSerialization.jsonObject(with:Data(#"ASKS"#.utf8)) as! [[String:Any]]
var steer=try! JSONSerialization.jsonObject(with:Data(#"STEER"#.utf8)) as! [String:Any]
func shelfJS(_ code:String,_ done:@escaping(Any?)->Void={_ in}){agentsUI.shelfWeb?.evaluateJavaScript(code){v,e in if let e{print("js error \(e)")};done(v)}}
func ask(_ row:[String:Any]){agentsUI.receive(["event":"state","agent":row])}
func waiting(_ row:[String:Any])->[String:Any]{var r=row,q=row["question"] as! [String:Any];q["waiting"]=true;r["question"]=q;r["step"]="Waiting for you to turn it on";return r}
agentsUI.receive(["event":"list","agents":[steer]]);agentsUI.ensureShelf()
var steps:[(Double,()->Void)]=[]
func run(_ i:Int){guard i<steps.count else{return};after(steps[i].0){steps[i].1();run(i+1)}}
steps.append((2.5,{ask(asks[0])}))
steps.append((1.5,{shoot("1-ask-macos",agentsUI.shelf!.frame)
 // Allow on the card reaches the setup flow (the real one opens System Settings and points at the switch)
 shelfJS("[...document.querySelectorAll('.chip[data-id=\"\(asks[0]["id"]!)\"] .pk button')].map(b=>b.textContent+'|'+(b.getAttribute('aria-keyshortcuts')||'')).join(',')"){v in print("ask buttons \(v ?? "none")")}
 shelfJS("document.querySelector('.chip[data-id=\"\(asks[0]["id"]!)\"] .pk button.go').click()")}))
steps.append((0.8,{if onboarding.allowed != ["screen"]{fail("Allow did not reach setup: \(onboarding.allowed)")};print("allow reached setup");ask(waiting(asks[0]))}))
steps.append((1.2,{shoot("2-ask-waiting",agentsUI.shelf!.frame);ask(asks[1])}))
steps.append((1.5,{shoot("3-ask-do-it",agentsUI.shelf!.frame);ask(asks[2])}))
steps.append((1.5,{shoot("4-ask-connector",agentsUI.shelf!.frame);for r in asks{agentsUI.receive(["event":"state","agent":r.merging(["status":"running","question":NSNull(),"step":"Working…"]){$1}])}}))
steps.append((1.2,{steer["steer"]=["ack":"Got it: 12×24, not 24×24","at":Date().timeIntervalSince1970];agentsUI.receive(["event":"steered","agent":steer])}))
steps.append((0.9,{shoot("5-steered-chip",agentsUI.shelf!.frame)
 shelfJS("document.querySelector('.chip[data-id=\"\(steer["id"]!)\"]').className"){v in print("steered class \(v ?? "")")}}))
steps.append((4.0,{shelfJS("document.querySelector('.chip[data-id=\"\(steer["id"]!)\"]').className"){v in if (v as? String ?? "").contains("steered"){fail("glow did not end")};print("glow ended")}
 Prefs.set("agentsHidden",true);agentsUI.openView(steer["id"] as! String)}))
steps.append((3.0,{shoot("6-view-steer",agentsUI.view!.frame);ask(asks[0]);agentsUI.js("view","select",asks[0]["id"]!)}))
steps.append((1.5,{shoot("7-view-ask",agentsUI.view!.frame);agentsUI.process?.terminate();print("round4 shots ok");exit(0)}))
after(0.1){run(0)}
nsapp.run()'''

# The setup screens themselves: the real onboarding and Settings pages, with live status sent in like the app does.
SETUP = r'''setvbuf(stdout,nil,_IONBF,0)
let agentsUI=AgentPanels()
let nsapp=NSApplication.shared;nsapp.setActivationPolicy(.accessory)
let out="OUTDIR",screen=NSScreen.screens[0],top=screen.frame.maxY
func after(_ s:Double,_ f:@escaping()->Void){DispatchQueue.main.asyncAfter(deadline:.now()+s,execute:f)}
final class Sink:NSObject,WKScriptMessageHandler{var got:[Any]=[];func userContentController(_ c:WKUserContentController,didReceive m:WKScriptMessage){got.append(m.body)}}
let sink=Sink()
func page(_ file:String,_ size:NSSize,_ handler:String)->(NSWindow,WKWebView){
 let w=NSWindow(contentRect:NSRect(x:60,y:top-80-size.height,width:size.width,height:size.height),styleMask:[.titled,.closable,.fullSizeContentView],backing:.buffered,defer:false)
 w.titlebarAppearsTransparent=true;w.titleVisibility = .hidden
 let bg=NSVisualEffectView(frame:w.contentRect(forFrameRect:w.frame));bg.material = .underWindowBackground;bg.blendingMode = .behindWindow;bg.state = .active
 let cfg=WKWebViewConfiguration();cfg.userContentController.add(sink,name:handler)
 if handler=="ob",let arrow=arrowCursorScript(){cfg.userContentController.addUserScript(arrow)}   // as Onboarding.open
 let v=WKWebView(frame:NSRect(x:0,y:0,width:size.width,height:size.height-28),configuration:cfg);v.setValue(false,forKey:"drawsBackground");v.autoresizingMask=[.width,.height]
 let html=(try! String(contentsOfFile:dir+"/ui/"+file,encoding:.utf8)).replacingOccurrences(of:"/*TOKENS*/",with:(try? String(contentsOfFile:dir+"/ui/tokens.css",encoding:.utf8)) ?? "").replacingOccurrences(of:"/*ORBS*/",with:(try? String(contentsOfFile:dir+"/ui/orbs.js",encoding:.utf8)) ?? "")
 v.loadHTMLString(html,baseURL:nil);bg.addSubview(v);w.contentView=bg;w.orderFrontRegardless();return (w,v)}
func shoot(_ name:String,_ w:NSWindow){let f=w.frame.insetBy(dx:-24,dy:-24).intersection(screen.frame),p=Process();p.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture")
 p.arguments=["-x","-R\(Int(f.minX)),\(Int(top-f.maxY)),\(Int(f.width)),\(Int(f.height))",out+"/"+name+".png"];try! p.run();p.waitUntilExit();print("shot \(name)")}
let (ow,ov)=page("onboarding.html",NSSize(width:640,height:640),"ob")
func ob(_ js:String,_ done:@escaping(Any?)->Void={_ in}){ov.evaluateJavaScript(js){v,e in if let e{print("js error \(e)")};done(v)}}
let some="{mic:true,speech:true,ax:true,screen:false,auto:true,chrome:false,calendar:false,tools:true}"
var steps:[(Double,()->Void)]=[]
func run(_ i:Int){guard i<steps.count else{return};after(steps[i].0){steps[i].1();run(i+1)}}
steps.append((2.0,{ob("ob.plan({ok:true,text:'Signed in. Claude Max.'});ob.set(\(some));document.querySelector('[data-to=perms]').click()")}))
steps.append((1.0,{shoot("8-setup-perms",ow);ob("document.querySelector('[data-to=ai]').click()")}))
steps.append((1.0,{shoot("9-setup-ai",ow);ob("document.querySelector('[data-to=try]').click()")}))
steps.append((1.2,{shoot("12-setup-try",ow);ow.orderOut(nil)
 let (sw,sv)=page("settings.html",NSSize(width:780,height:560),"st");sw.appearance=NSAppearance(named:.darkAqua)   // as SettingsWindow.open
 after(2.0){sv.evaluateJavaScript("st.tab('account');st.perms({mic:true,speech:true,ax:true,screen:true,auto:true,chrome:false,calendar:false});st.connectors({connected:['Gmail','Google Drive','Google Calendar','Slack','Figma'],signin:['Notion','Canva']});st.walk('calendar');document.getElementById('agentsetup').scrollIntoView({block:'center'})"){_,e in if let e{print("js error \(e)")}}
  after(1.2){shoot("13-settings-agents",sw);print("setup shots ok");exit(0)}}}))
after(0.1){run(0)}
nsapp.run()'''

# Show, don't tell: open a real privacy pane in the VM and point at Atticus's switch with the app's own code.
def point_fixture():
    source = (ROOT / 'Atticus.swift').read_text()
    cut = lambda start, end: source[source.index(start):source.index(end, source.index(start))]
    return ('import Cocoa\n' + cut('func axAttribute(', '// AX has no public') + 'enum Hands {\n' + cut('    static func attribute(_ e: AXUIElement', '    static func array(') + '}\n'
            + 'enum Prefs { static func bool(_ key: String) -> Bool { false } }\n' + cut('func applySharing(', 'func profileName(')
            + 'var leader: NSPanel?\nfunc lead(from: NSRect, to: NSRect) -> Bool { preconditionFailure("Switch ring has no answer box") }\n'
            + cut('var ring: NSPanel?', '// A line from the box') + 'enum Onboarding {\n static let name = "Atticus"\n' + cut('    static func pointSwitch(', '    static func bundle(') + '}\n'
            + r'''setvbuf(stdout,nil,_IONBF,0)
let nsapp=NSApplication.shared;nsapp.setActivationPolicy(.accessory)
NSWorkspace.shared.open(URL(string:"x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture")!)
Onboarding.pointSwitch("Atticus")
var tries=0
Timer.scheduledTimer(withTimeInterval:0.25,repeats:true){t in tries+=1
 if let r=ring{t.invalidate();print("ring at \(r.frame)");r.sharingType = .readOnly
  DispatchQueue.main.asyncAfter(deadline:.now()+0.6){let p=Process();p.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture");p.arguments=["-x","OUTDIR/14-point-switch.png"];try! p.run();p.waitUntilExit();print("point shot ok");exit(0)}}
 else if tries>60{print("no switch found to point at");let p=Process();p.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture");p.arguments=["-x","OUTDIR/14-point-missing.png"];try! p.run();p.waitUntilExit();exit(1)}}
nsapp.run()''')


class Round4Shots(unittest.TestCase):
    def out(self):
        out = ROOT / 'test-artifacts' / 'design' / 'round4'; out.mkdir(parents=True, exist_ok=True); return str(out)

    def test_asks_and_steer(self):
        run_fixture(self, ROUND4.replace('OUTDIR', self.out()).replace('ASKS', json.dumps(ASKS)).replace('STEER', json.dumps(STEER)), 'round4 shots ok')

    def test_setup_screens(self):
        run_fixture(self, SETUP.replace('OUTDIR', self.out()), 'setup shots ok')

    def test_point_at_switch(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder) / 'point.swift'; src.write_text(point_fixture().replace('OUTDIR', self.out()))
            build = subprocess.run(['swiftc', str(src), '-o', str(Path(folder) / 'point')], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(Path(folder) / 'point')], capture_output=True, text=True, timeout=60)
            subprocess.run(['osascript', '-e', 'quit app "System Settings"'], capture_output=True)
            print(result.stdout.strip(), flush=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
