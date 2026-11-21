"""The answer box over real backdrops, VM only (opt-in, not discovered: run this module by name).

run.sh <repo> tests.shoot_boxlook  → measured glass colors, then PNGs printed as base64 (the runner copies nothing back).
The box is the app's own glass (sliced from Atticus.swift) with the real ui.html on top.
"""
import base64
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATH = (r"Here is the step-by-step solution for problem 36." "\n\n"
        r"To rationalize the denominator of $\frac{\sqrt{7}}{\sqrt{10}-\sqrt{2}}$, multiply the numerator and denominator by the conjugate $\sqrt{10}+\sqrt{2}$:" "\n\n"
        r"$$\frac{\sqrt{7}}{\sqrt{10}-\sqrt{2}}\cdot\frac{\sqrt{10}+\sqrt{2}}{\sqrt{10}+\sqrt{2}}=\frac{\sqrt{70}+\sqrt{14}}{10-2}=\frac{\sqrt{70}+\sqrt{14}}{8}$$")
LIST = ("**Three good options** near you tonight:\n\n1. **Tartine** — bakery, open until 7 pm\n2. **Zuni Café** — dinner, book on [OpenTable](https://www.opentable.com)\n"
        "3. **Nopa** — late night, `walk-in` only\n\nWant me to book one?")
MORE = (r"The roots of $ax^2+bx+c=0$ are" "\n" r"$$x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}$$" "\n"
        r"and $\sum_{i=1}^{n} i=\frac{n(n+1)}{2}$, $\sqrt[3]{27}=3$, $\lim_{x\to 0}\frac{\sin x}{x}=1$." "\n"
        r"$$f(x)=\begin{cases} x^2 & x\ge 0 \\ -x & x<0 \end{cases}\qquad A=\begin{pmatrix}1&2\\3&4\end{pmatrix}$$" "\n"
        r"Unknown TeX shows as written: $\weird{x}$, and $5 or $10 stays money.")
SECTIONS = ("The **Pythagorean theorem** says that in a right triangle, the squares on the two shorter sides add up to the square on the longest side: $a^2+b^2=c^2$.\n\n"
            "### How it works\nIt only applies to right triangles. The longest side, opposite the right angle, is the hypotenuse.\n\n"
            "### Example\nTake legs of 3 and 4 units.\n\n1. Square them: $3^2=9$ and $4^2=16$.\n2. Add: $9+16=25$.\n3. Take the root: $c=5$.")
# A white document page and a dark desktop, so the glass reads as on a real screen.
LIGHT = '<body style="margin:0;padding:40px 60px;background:#fff;color:#1d1d1f;font:15px -apple-system">' + ''.join(
    f'<h2 style="margin:24px 0 8px">Section {i}</h2><p style="line-height:1.6;max-width:900px">' + 'The quick brown fox jumps over the lazy dog while the committee reviews the quarterly figures and the draft budget. ' * 4 + '</p>'
    + '<div style="height:70px;width:420px;border-radius:8px;background:linear-gradient(90deg,#0a84ff,#ff9f0a,#30d158)"></div>' for i in range(1, 7)) + '</body>'
DARK = ('<body style="margin:0;height:100vh;background:linear-gradient(135deg,#283a5c,#4d2a4d 55%,#0f1218);font:15px -apple-system">'
        '<div style="position:absolute;left:80px;top:120px;width:380px;height:260px;border-radius:12px;background:#1e1e22;color:#ddd;padding:20px">Terminal — zsh<br>$ git status<br>On branch main</div></body>')

SWIFT = r'''import Cocoa
import WebKit
setvbuf(stdout,nil,_IONBF,0)
let nsapp=NSApplication.shared;nsapp.setActivationPolicy(.accessory)
let args=CommandLine.arguments,dir=args[1],out=args[2],mode=args[3]
let screen=NSScreen.screens[0],top=screen.frame.maxY
func after(_ s:Double,_ f:@escaping()->Void){DispatchQueue.main.asyncAfter(deadline:.now()+s,execute:f)}
let back=NSWindow(contentRect:screen.frame,styleMask:[.borderless],backing:.buffered,defer:false);let page=WKWebView(frame:NSRect(origin:.zero,size:screen.frame.size))
back.contentView=page;back.orderFrontRegardless()
final class Bridge:NSObject,WKScriptMessageHandler{var ready:()->Void={};func userContentController(_ c:WKUserContentController,didReceive m:WKScriptMessage){if (m.body as? [String:Any])?["ready"] != nil{ready()}}}
let bridge=Bridge(),cfg=WKWebViewConfiguration();cfg.userContentController.add(bridge,name:"c");cfg.userContentController.add(bridge,name:"h")
let web=WKWebView(frame:NSRect(x:0,y:0,width:500,height:300),configuration:cfg)
var tintAlpha=CGFloat(0.9)
let panel=NSPanel(contentRect:NSRect(x:200,y:top-80-300,width:500,height:300),styleMask:[.nonactivatingPanel,.borderless],backing:.buffered,defer:false)
panel.isOpaque=false;panel.backgroundColor = .clear;panel.hasShadow=true;panel.level = .floating
func glass(){
GLASS
web.setValue(false,forKey:"drawsBackground");web.autoresizingMask=[.width,.height];bg.addSubview(web);panel.contentView=bg;panel.orderFrontRegardless()}
CGWarpMouseCursorPosition(CGPoint(x:screen.frame.maxX-40,y:top-40))
func capture(_ name:String)->NSBitmapImageRep{let f=panel.frame.insetBy(dx:-30,dy:-30).intersection(screen.frame),path=out+"/"+name+".png",p=Process();p.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture")
 p.arguments=["-x","-R\(Int(f.minX)),\(Int(top-f.maxY)),\(Int(f.width)),\(Int(f.height))",path];try! p.run();p.waitUntilExit();print("shot \(name)");return NSBitmapImageRep(data:try! Data(contentsOf:URL(fileURLWithPath:path)))!}
if mode=="measure"{   // the glass alone (no page) over flat backdrops: the material's own darkening, per tint
 var runs:[(Int,CGFloat)]=[];for g in [255,128,0]{for a in [0,0.5,0.6,0.65,0.7,0.75,0.8,0.82,0.85,0.88,0.9]{runs.append((g,CGFloat(a)))}}
 func next(_ i:Int){guard i<runs.count else{print("measure ok");exit(0)};let (g,a)=runs[i];tintAlpha=a;glass()
  page.loadHTMLString("<body style='margin:0;height:100vh;background:rgb(\(g),\(g),\(g))'></body>",baseURL:nil)
  after(1.2){let img=capture("measure");let c=img.colorAt(x:img.pixelsWide/2,y:img.pixelsHigh/2)!.usingColorSpace(.sRGB)!
   print("glass backdrop \(g) tint \(a) -> \(Int(c.redComponent*255)),\(Int(c.greenComponent*255)),\(Int(c.blueComponent*255))");next(i+1)}}
 after(0.5){next(0)}
}else{
 glass()
 let html=try! String(contentsOfFile:dir+"/ui/ui.html",encoding:.utf8),orbs=try! String(contentsOfFile:dir+"/ui/orbs.js",encoding:.utf8)
 web.loadHTMLString(html.replacingOccurrences(of:"/*TOKENS*/",with:(try? String(contentsOfFile:dir+"/ui/tokens.css",encoding:.utf8)) ?? "").replacingOccurrences(of:"/*ORBS*/",with:orbs),baseURL:nil)
 let backs=["light":#"LIGHT"#,"dark":#"DARK"#]
 let scenes:[(String,String,String,String)]=SCENES
 func play(_ i:Int){guard i<scenes.count else{print("box shots ok");exit(0)};let (name,look,ask,check)=scenes[i]
  page.loadHTMLString(backs[look]!,baseURL:nil)
  web.evaluateJavaScript("ui.reset();ui.size(420);"+ask){_,e in if let e{print("scene \(name) failed: \(e)");exit(1)}
   after(1.6){web.evaluateJavaScript("document.getElementById('card').getBoundingClientRect().height"){v,_ in
    let h=CGFloat((v as? Double) ?? 300);var f=panel.frame;f.origin.y=f.maxY-h;f.size.height=h;panel.setFrame(f,display:true)
    after(0.6){web.evaluateJavaScript(check){v,e in guard e==nil,let s=v as? String,s.hasPrefix("ok") else{print("check \(name) failed: \(String(describing:e)) \(String(describing:v))");exit(1)};print("check \(name): \(s)")
     _=capture(name);play(i+1)}}}}}}
 bridge.ready={after(0.8){play(0)}}
}
nsapp.run()'''


def ask(q, a, steps=()):
    return f'ui.listen(true);ui.words({json.dumps(q)});ui.think();' + ''.join(f'ui.line({json.dumps("▸ " + x)});' for x in steps) + f'ui.line({json.dumps("✓ " + a)});'


CHECK_MATH = ("(()=>{const a=document.querySelector('.turn:last-child .a'),m=a.querySelectorAll('math');"
              "return m.length===3&&!a.querySelector('.tex')&&a.querySelectorAll('mfrac').length===5&&a.querySelectorAll('msqrt').length===16&&a.querySelector('math[display=block]')?"
              "'ok math '+m.length+' fractions '+a.querySelectorAll('mfrac').length+' block '+getComputedStyle(a.querySelector('math[display=block]')).display:'bad '+a.innerHTML.slice(0,400)})()")
CHECK_LIST = ("(()=>{const a=document.querySelector('.turn:last-child .a'),l=a.querySelector('a[href]');"
              "return a.querySelectorAll('ol li').length===3&&a.querySelectorAll('strong').length===4&&l&&l.href.startsWith('https://www.opentable.com')&&a.querySelector('code')&&!a.textContent.includes('**')?"
              "'ok list '+a.querySelectorAll('li').length+' link '+l.href:'bad '+a.innerHTML.slice(0,400)})()")
CHECK_MORE = ("(()=>{const a=document.querySelector('.turn:last-child .a'),t=[...a.querySelectorAll('.tex')].map(e=>e.textContent);"
              "return t.length===1&&t[0]==='\\\\weird{x}'&&a.querySelectorAll('mtable').length===2&&a.querySelector('mroot')&&a.querySelector('munderover')&&a.textContent.includes('$5 or $10')?"
              "'ok fallback '+t[0]+' tables 2':'bad '+JSON.stringify(t)+a.innerHTML.slice(0,300)})()")
CHECK_SECTIONS = ("(()=>{const a=document.querySelector('.turn:last-child .a'),h=a.querySelectorAll('.h');"
                  "return h.length===2&&getComputedStyle(h[0]).textTransform==='uppercase'&&a.querySelectorAll('ol li').length===3&&!a.textContent.includes('#')?"
                  "'ok headings '+h.length+' '+getComputedStyle(h[0]).textTransform:'bad '+a.innerHTML.slice(0,400)})()")
SCENES = [('sections-dark', 'dark', ask('can you tell me the pythagorean theorem and explain', SECTIONS, ['Searching the web: pythagorean theorem', 'Drawing on your screen']), CHECK_SECTIONS),
          ('sections-light', 'light', ask('can you tell me the pythagorean theorem and explain', SECTIONS, ['Searching the web: pythagorean theorem', 'Drawing on your screen']), CHECK_SECTIONS),('math-light', 'light', ask('and 36', MATH), CHECK_MATH), ('math-dark', 'dark', ask('and 36', MATH), CHECK_MATH),
          ('list-light', 'light', ask('Where should we eat tonight?', LIST), CHECK_LIST), ('list-dark', 'dark', ask('Where should we eat tonight?', LIST), CHECK_LIST),
          ('math-more-dark', 'dark', ask('Show me some formulas', MORE), CHECK_MORE)]
PICK = "ui.listen(false);ui.models({list:['cheapest','balanced','capable'],pick:'balanced'});ui.hover(true);document.getElementById('model').click();"
CHECK_PICK = "(()=>{const e=document.getElementById('modewhy');return !e.hidden&&e.textContent.length>40?'ok why '+e.textContent:'bad '+e.outerHTML})()"
SCENES += [('picker-light', 'light', PICK, CHECK_PICK), ('picker-dark', 'dark', PICK, CHECK_PICK),
           ('picker-cheapest-dark', 'dark', PICK + "document.querySelector('#models [data-v=cheapest]').focus();", CHECK_PICK)]


def fixture():
    source = (ROOT / 'Atticus.swift').read_text()
    start = source.index('        let bg = NSVisualEffectView(frame: web.frame)')
    glass = source[start:source.index('bg.addSubview(tint)', start)] + 'bg.addSubview(tint)'
    tint = re.search(r'alpha:([\d.]+)\)\.cgColor', glass)[1]
    glass = glass.replace(f'alpha:{tint}).cgColor', 'alpha:tintAlpha).cgColor', 1)   # measure mode varies the box tint; shots use the app's
    swift_str = lambda s: s.replace('\\', '\\\\').replace('"', '\\"')
    scenes = '[' + ','.join('("%s","%s","%s","%s")' % tuple(swift_str(x) for x in s) for s in SCENES) + ']'
    return SWIFT.replace('CGFloat(0.9)', f'CGFloat({tint})').replace('GLASS', glass).replace('#"LIGHT"#', '"' + swift_str(LIGHT) + '"').replace('#"DARK"#', '"' + swift_str(DARK) + '"').replace('SCENES', scenes)


class BoxLook(unittest.TestCase):
    def run_box(self, mode, marker):
        with tempfile.TemporaryDirectory() as folder:
            src, binary, out = Path(folder) / 'box.swift', Path(folder) / 'box', Path(folder) / 'out'
            out.mkdir(); src.write_text(fixture())
            build = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(binary), str(ROOT), str(out), mode], capture_output=True, text=True, timeout=180)
            print(result.stdout.strip(), flush=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(marker, result.stdout)
            if mode == 'shots':
                for png in sorted(out.glob('*.png')): print('PNG', png.name, base64.b64encode(png.read_bytes()).decode(), flush=True)

    def test_measure_glass(self):
        self.run_box('measure', 'measure ok')

    def test_shots(self):
        self.run_box('shots', 'box shots ok')


if __name__ == '__main__':
    unittest.main()
