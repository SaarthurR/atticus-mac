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


# Native geometry fixtures stub the pixel producer; they never need WebKit or app windows.
MATH_STUB = r'''enum DrawingMath {
    static func contains(_ text: String) -> Bool { text.contains("$") || text.contains("\\(") || text.contains("\\[") }
    static func image(_ text: NSAttributedString, width: CGFloat) -> NSImage? { nil }
    static func layer(_ text: NSAttributedString, image: NSImage?) -> CALayer {
        let layer = CATextLayer(); layer.string = text; layer.isWrapped = true; return layer
    }
    static var changed: (() -> Void)?
    static func reset() {}
}
'''


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
assert.deepEqual(posts,[{action:'ready'}]);
'''
        run = subprocess.run(['node', '--input-type=module'], input=script, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_measured_transparent_math_fragments(self):
        page = (ROOT / 'ui/drawing-math.html').read_text().replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text())
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
