"""First mouse delivery to real, unfocused WebKit windows (VM only)."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''import Cocoa
import WebKit
WEB_CLASS
NSApplication.shared.setActivationPolicy(.regular)
if CommandLine.arguments.count == 2 {
    let w = NSWindow(contentRect:NSRect(x:20,y:20,width:160,height:120),styleMask:[.titled],backing:.buffered,defer:false)
    w.title="Fixture focus"; w.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true)
    NSApplication.shared.run()
}
final class Sink: NSObject, WKScriptMessageHandler {
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {}
}
let sink=Sink(), cfg=WKWebViewConfiguration()
for name in ["st","ob","c","h"] { cfg.userContentController.add(sink,name:name) }
let w=NSWindow(contentRect:NSRect(x:220,y:150,width:780,height:640),styleMask:[.titled,.closable],backing:.buffered,defer:false)
let web=CLICK_WEB(frame:NSRect(x:0,y:0,width:780,height:640),configuration:cfg)
w.contentView=web; w.center(); w.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true)
func wait(_ s:Double) { Thread.sleep(forTimeInterval:s) }
func eval(_ s:String)->Any? { let d=DispatchSemaphore(value:0); var out:Any?; DispatchQueue.main.async { web.evaluateJavaScript(s) { v,e in out=v; if let e { print("JS_ERROR \(e)") }; d.signal() } }; d.wait(); return out }
func main<T>(_ f:@escaping()->T)->T { var r:T?; DispatchQueue.main.sync {r=f()};return r! }
DispatchQueue.global().async {
    let ready = Date().addingTimeInterval(10)
    while eval("!!(window.st || window.ob || window.ui)") as? Bool != true && Date() < ready { wait(0.05) }
    precondition(eval("!!(window.st || window.ob || window.ui)") as? Bool == true, "page never initialized")
    let helper=Process();helper.executableURL=URL(fileURLWithPath:CommandLine.arguments[0]);helper.arguments=["focus"]
    try! helper.run(); defer {helper.terminate()}
    let scenes=(try! JSONSerialization.jsonObject(with:CommandLine.arguments[2].data(using:.utf8)!)) as! [String:String]
    var out:[[String:Any]]=[]
    for (scene,setup) in scenes.sorted(by:{$0.key<$1.key}) {
        _=eval(setup+";1");wait(0.5)
        let count=eval("window.fixtureControls=[...document.querySelectorAll('button,input,textarea,select,summary,a[href],[role=button],#x')].filter(e=>!e.disabled && e.getClientRects().length && getComputedStyle(e).visibility!=='hidden' && !e.closest('[inert]'));fixtureControls.length") as? Int ?? 0
        _=eval("window.fixtureClicks=[];window.fixtureCapture=e=>{const i=fixtureControls.findIndex(c=>c===e.target||c.contains(e.target)||[...c.labels||[]].some(l=>l.contains(e.target)));if(i>=0){fixtureClicks.push(i);e.preventDefault();e.stopImmediatePropagation()}};document.addEventListener('click',fixtureCapture,true);window.fixtureDown=e=>{if(e.target.closest('select'))e.preventDefault()};document.addEventListener('mousedown',fixtureDown,true);1")
        for i in 0..<count {
            // An earlier click in this scene can close what held a control (a picked model closes the picker): nothing to click then.
            guard let p=eval("(()=>{const e=fixtureControls[\(i)];if(!e.isConnected||!e.getClientRects().length||getComputedStyle(e).pointerEvents==='none')return null;for(let n=e;n;n=n.parentElement)if(+getComputedStyle(n).opacity<0.05)return null;e.scrollIntoView({block:'center',inline:'center'});const r=e.getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()") as? [Double] else { continue }
            main { NSRunningApplication(processIdentifier:helper.processIdentifier)?.activate(options:[.activateIgnoringOtherApps]) }
            let unfocused = Date().addingTimeInterval(1)
            while main({w.isKeyWindow || NSApp.isActive}) && Date() < unfocused {wait(0.01)}
            let inactive=main { !w.isKeyWindow && !NSApp.isActive }
            let f=main {w.contentRect(forFrameRect:w.frame)}, top=main {NSScreen.screens[0].frame.maxY}
            let point=CGPoint(x:f.minX+p[0],y:top-f.maxY+p[1])
            for type in [CGEventType.leftMouseDown,.leftMouseUp] {
                let e=CGEvent(mouseEventSource:CGEventSource(stateID:.privateState),mouseType:type,mouseCursorPosition:point,mouseButton:.left)!
                e.setIntegerValueField(.mouseEventClickState,value:1);e.post(tap:.cghidEventTap);wait(0.04)
            }
            wait(0.08)
            let focused=eval("fixtureControls[\(i)]===document.activeElement && fixtureControls[\(i)].matches('input:not([type=checkbox]),textarea,select')") as? Bool ?? false
            let landed=eval("fixtureClicks.filter(i=>i===\(i)).length") as? Int ?? -1
            let label=eval("fixtureControls[\(i)].id||fixtureControls[\(i)].getAttribute('aria-label')||fixtureControls[\(i)].textContent.trim().slice(0,60)||fixtureControls[\(i)].tagName") as? String ?? "?"
            out.append(["scene":scene,"control":label,"inactive":inactive,"clicks":focused ? 1 : landed])
        }
        _=eval("document.removeEventListener('click',fixtureCapture,true);document.removeEventListener('mousedown',fixtureDown,true);1")
    }
    helper.terminate(); helper.waitUntilExit()
    print(String(data:try! JSONSerialization.data(withJSONObject:out),encoding:.utf8)!);exit(0)
}
web.loadHTMLString(try! String(contentsOfFile:CommandLine.arguments[1],encoding:.utf8),baseURL:nil)
DispatchQueue.main.asyncAfter(deadline:.now()+150) {print("timeout");exit(1)}
NSApplication.shared.run()
'''

SCENES = {
    'settings': {tab: "st.load({prefs:{hotkeyLabel:'Control Space',client:'claude',routing:'balanced',autoMinimize:true,speak:true}});st.tab(" + json.dumps(tab) + ");document.querySelectorAll('details.meeting-controls').forEach(e=>e.open=true)" for tab in ('general', 'brain', 'dictation', 'meetings', 'memory', 'usage', 'account', 'about', 'feedback')},
    'onboarding': {page: "ob.prefs({hotkeyLabel:'Control Space',client:'claude'});ob.plan({ok:false,need:'login',client:'claude',text:'Sign in'});document.querySelector('[data-to=\"" + page + "\"]').click()" for page in ('welcome', 'ai', 'model', 'perms', 'try', 'dictate', 'show', 'improve', 'tip', 'done')},
    'ui': {'answer': "ui.autoMinimize(false);ui.listen();ui.words('Example');ui.line('✓ An answer.');ui.finished();ui.compose(true);ui.hover(true);ui.models({list:['cheapest','balanced','capable'],pick:'balanced'});ui.updated('2.0');ui.agentCount(1)"},
}

BOX_TURN = "ui.drawing(false);ui.autoMinimize(false);ui.dictate(false);ui.reset();ui.listen();ui.words('Fixture');ui.think();ui.line('✓ Ready.');ui.finished();"
SCENES['ui'].update({name: BOX_TURN + action for name, action in {
    'approval': "ui.ask(['Continue?', 'echo fixture'])",
    'choices': "ui.pick({q:'Which?',options:[{label:'Blue'},{label:'Red'}]})",
    'upgrade': "ui.upgrade('fixture')",
    'keep-model': "ui.upgradeStarted('fixture');ui.finished()",
    'paused': "ui.paused()",
    'permission': "ui.permission('Allow access for this fixture')",
    'rewrite': "ui.rewrite(['Draft text','replace',true])",
    'worker-failure': "ui.workerFailed()",
    'agent': "ui.agentDone({id:'fixture',title:'Fixture task',status:'done',result:'Ready.'})",
    'dictation': "ui.dictate(true);ui.dictated({text:'Fixture words',words:'Fixture words',history:true})",
    'model-choices': "ui.compose(true);ui.models({list:['cheapest','balanced','capable'],pick:'balanced'});document.getElementById('model').click()",
    'support': "ui.line('i Support: Support Atticus')",
}.items()})


@unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'real mouse and windows: VM only')
class FirstClickTests(unittest.TestCase):
    def test_each_visible_control_receives_one_click_while_unfocused(self):
        source = (ROOT / 'Atticus.swift').read_text()
        match = re.search(r'(?:final )?class ClickWebView: WKWebView \{.*?\n\}\n', source, re.S)
        web_class = match.group(0) if match else ''
        with tempfile.TemporaryDirectory() as tmp:
            src, binary = Path(tmp) / 'click.swift', Path(tmp) / 'click'
            src.write_text(HARNESS.replace('WEB_CLASS', web_class).replace('CLICK_WEB', 'ClickWebView' if web_class else 'WKWebView'))
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            failures = []
            for name, scenes in SCENES.items():
                page = Path(tmp) / (name + '.html')
                page.write_text((ROOT / 'ui' / (name + '.html')).read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text()))
                run = subprocess.run([str(binary), str(page), json.dumps(scenes)], capture_output=True, text=True, timeout=170)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertNotIn('JS_ERROR', run.stdout)
                rows = json.loads(run.stdout.strip().splitlines()[-1])
                print('FIRST_CLICK', name, json.dumps(rows), flush=True)
                self.assertTrue(rows, name)
                failures.extend((name, row) for row in rows if not row['inactive'] or row['clicks'] != 1)
            self.assertEqual(failures, [])
