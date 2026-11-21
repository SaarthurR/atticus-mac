"""Drawing math uses the answer formatter offscreen; no windows or external apps."""
import json
import re
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_shelf_page import HARNESS, ROOT
import atticus


# Native geometry fixtures stub the pixel producer; they never need WebKit or app windows. The text gates are the app's own.
_SOURCE = (ROOT / 'Atticus.swift').read_text()
MATH_STUB = 'enum DrawingMath {\n' + _SOURCE[_SOURCE.index('    static func contains(_ text: String)'):_SOURCE.index('    // Rendering: a clear image')] + r'''    static func image(_ text: NSAttributedString, width: CGFloat) -> NSImage? { nil }
    static func layer(_ text: NSAttributedString, image: NSImage?) -> CALayer {
        let layer = CATextLayer(); layer.string = text; layer.isWrapped = true; return layer
    }
    static var changed: (() -> Void)?
    static func reset() {}
}
'''
# The shape of the step card in the user's shot (drawcard-markdown-his-shot.png), line breaks as the reply wrote them.
HIS_CARD = ('The channel has two videos on the Videos tab:\n'
            '- **"Bread shouldn\'t take 12 bowls"** pitches Crumbly as the one place to look instead of many.\n'
            '- **"Loaf — Dough to Crust | Bake Week 2026"** is a 1:16 demo of a separate kitchen project called Loaf. '
            'You point at a part of a photo and Loaf marks it.\n\n'
            'Do you want me to open the website, crumbly.example, and summarize it?')


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class DrawingMathTests(unittest.TestCase):
    def test_drawing_contract_allows_typeset_math(self):
        self.assertNotIn("Drawn text is plain Unicode, no LaTeX", atticus.DRAW_HELP)
        self.assertIn("$…$", atticus.DRAW_HELP)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_overlay_uses_safe_math_with_stubbed_measurement(self):
        source = (ROOT / 'ui/orbs.js').read_text()
        formatter = source[source.index('// TeX → MathML'):source.index('export { MML')]
        page = (ROOT / 'ui/drawing-math.html').read_text()
        script = r'''
import assert from 'node:assert/strict';
class N {
  constructor(tag) { this.tag=tag; this.kids=[]; this.style={}; this.attrs={}; }
  append(...kids) { this.kids.push(...kids); }
  appendChild(k) { this.append(k); return k; }
  replaceChildren(...kids) { this.kids=kids; }
  setAttribute(k,v) { this.attrs[k]=v; }
  set textContent(s) { this.kids=[String(s)]; }
  get textContent() { return this.kids.map(k=>typeof k==='string'?k:k.textContent).join(''); }
  get childNodes() { return this.kids; }
  getBoundingClientRect() { return {width:210.2,height:88.4}; }
  get scrollWidth() { return 211; }
  get scrollHeight() { return 89; }
}
const body=new N('div'), posts=[];
const document={getElementById:()=>body, createElement:t=>new N(t),createElementNS:(ns,t)=>new N(t),createDocumentFragment:()=>new N('#')};
const window={webkit:{messageHandlers:{drawingMath:{postMessage:p=>posts.push(p)}}}};
const HIS=''' + json.dumps(HIS_CARD, ensure_ascii=False) + ''';
''' + formatter + re.search(r'<script type="module">(.*?)</script>', page, re.S)[1] + r'''
const all=n=>typeof n==='string'?[]:[n,...n.kids.flatMap(all)];
const count=tag=>all(body).filter(n=>n.tag===tag).length;
for (const size of [22,28,32]) {
  const measured=window.drawingMath(String.raw`Steps: $\begin{aligned}x^2&=\frac{1}{\sqrt{2}}\\x&=\sqrt{\frac{1}{\sqrt{2}}}\end{aligned}$`,size,'white',420);
  assert.deepEqual(measured,{width:211,height:89});
  assert.deepEqual(['mfrac','msqrt','msup','mtr'].map(count),[2,3,1,2]);
  assert.equal(body.style.fontSize,size+'px');
  assert.equal(body.style.maxWidth,'420px');
}
window.drawingMath(String.raw`<img src=x onerror=alert(1)> $\unknown{x}$`,22,'white',300);
assert.equal(count('img'),0);
assert.ok(body.textContent.includes(String.raw`\unknown{x}`));
window.drawingMath('Two videos:\n- **"Bread basics"** pitches it.\n- **"Loaf"** is a `demo`, see [site](https://crumbly.example).\n\nOpen it?',14,'white',368);
assert.deepEqual(['ul','li','strong','code','p'].map(count),[1,2,2,1,2]);
assert.ok(!/\*\*|`|\]\(|^- /m.test(body.textContent) && body.textContent.includes('site'));
window.drawingMath(HIS,14,'white',368);
assert.deepEqual(['ul','li','strong','table','p'].map(count),[1,2,2,0,2]);
assert.ok(!/\*\*|^\s*- /m.test(body.textContent) && body.textContent.includes('Loaf — Dough to Crust | Bake Week 2026') && body.textContent.includes('crumbly.example'));
assert.deepEqual(posts,[{action:'ready'}]);
'''
        run = subprocess.run(['node', '--input-type=module'], input=script, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_measured_transparent_math_fragments(self):
        page = (ROOT / 'ui/drawing-math.html').read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text())
        script = r'''
const results = [];
for (const size of [22, 28, 32]) {
  const measured = drawingMath(String.raw`Steps: $\begin{aligned}x^2&=\frac{1}{\sqrt{2}}\\x&=\sqrt{\frac{1}{\sqrt{2}}}\end{aligned}$`, size, 'white', 420);
  const n = document.querySelector('#text');
  results.push([measured, n.querySelectorAll('mfrac').length, n.querySelectorAll('msqrt').length,
    n.querySelectorAll('msup').length, n.querySelectorAll('mtr').length, getComputedStyle(document.body).backgroundColor]);
}
drawingMath('<img src=x onerror=alert(1)> $\\unknown{x}$', 22, 'white', 300);
return {results, unsafe: !!document.querySelector('img'), fallback: document.querySelector('.tex')?.textContent,
  windows: window.opener === null};
'''
        with tempfile.TemporaryDirectory() as tmp:
            html, swift, binary = [Path(tmp) / p for p in ('page.html', 'page.swift', 'page')]
            html.write_text(page)
            swift.write_text(HARNESS)
            built = subprocess.run(['swiftc', str(swift), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(html), script], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        out = json.loads(run.stdout)['result']
        for measured, frac, root, sup, rows, background in out['results']:
            self.assertGreater(measured['height'], 50)
            self.assertLessEqual(measured['width'], 420)
            self.assertEqual([frac, root, sup, rows], [2, 3, 1, 2])
            self.assertEqual(background, 'rgba(0, 0, 0, 0)')
        self.assertFalse(out['unsafe'])
        self.assertEqual(out['fallback'], r'\unknown{x}')

    def test_card_is_redrawn_when_the_render_ends_without_pixels(self):
        # The real DrawingMath: while pixels are pending the card holds a clear placeholder, so every ending,
        # pixels or none (too wide, too tall), must ask the card to draw again.
        start = _SOURCE.index('final class DrawingMath: NSObject')
        cls = _SOURCE[start:_SOURCE.index('// Screen drawings use Quartz points throughout', start)]
        swift = r'''import Cocoa
import WebKit
func loadPage(_ web: WKWebView, _ name: String) {
    let ui = CommandLine.arguments[1] + "/ui/"
    let html = try! String(contentsOfFile: ui + name, encoding: .utf8), orbs = try! String(contentsOfFile: ui + "orbs.js", encoding: .utf8)
    let tokens = try! String(contentsOfFile: ui + "tokens.css", encoding: .utf8)
    web.loadHTMLString(html.replacingOccurrences(of: "/*TOKENS*/", with: tokens).replacingOccurrences(of: "/*ORBS*/", with: orbs), baseURL: nil)
}
final class PageErrors { static let shared = PageErrors(); func evaluated(_ call: String, _ error: Error?) {} }
''' + cls + r'''
NSApplication.shared.setActivationPolicy(.prohibited)
let cases: [(String, CGFloat, CGFloat)] = [("A **bold** word.", 22, 300), (CommandLine.arguments[2], 22, 160), (CommandLine.arguments[3], 22, 160)]
var out: [[String: Any]] = [], i = 0, redraws = 0
DrawingMath.changed = { redraws += 1 }
func next() {
    guard i < cases.count else { print(String(data: try! JSONSerialization.data(withJSONObject: out), encoding: .utf8)!); exit(0) }
    let (s, size, width) = cases[i]; redraws = 0
    let text = NSAttributedString(string: s, attributes: [.font: NSFont.systemFont(ofSize: size), .foregroundColor: NSColor.white])
    let pending = DrawingMath.image(text, width: width)
    let key = DrawingMath.jobs.keys.first { $0.hasSuffix("|" + s) }!
    func poll() {
        guard DrawingMath.jobs[key]!.web == nil else { return DispatchQueue.main.asyncAfter(deadline: .now() + 0.1, execute: poll) }
        out.append(["pending": pending != nil, "pixels": DrawingMath.jobs[key]!.image != nil, "redraws": redraws, "after": DrawingMath.image(text, width: width) != nil])
        i += 1; next()
    }
    poll()
}
next()
DispatchQueue.main.asyncAfter(deadline: .now() + 50) { print("timeout"); exit(1) }
NSApplication.shared.run()
'''
        wide = r'Area: $$\int_0^1 x^2 + y^2 + z^2 + w^2 + a^2 + b^2 + c^2 + d^2 \, dx$$'
        tall = ' '.join(['**Step.** Mix the flour and water until smooth.'] * 60)
        with tempfile.TemporaryDirectory() as tmp:
            source, binary = Path(tmp) / 'math.swift', Path(tmp) / 'math'
            source.write_text(swift)
            built = subprocess.run(['swiftc', str(source), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(ROOT), wide, tall], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
        ok, *failed = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual(ok, {'pending': True, 'pixels': True, 'redraws': 1, 'after': True})
        self.assertTrue(failed and all(not f['pixels'] for f in failed), failed)   # the renderer refuses both: the fixture tests the ending without pixels
        for f in failed:
            self.assertEqual((f['pending'], f['redraws'], f['after']), (True, 1, False), f)   # placeholder first, then one redraw to the plain text
