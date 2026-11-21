"""Inline formulas reserve their full height and leading in real VM WebKit."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests.test_shelf_page import HARNESS, ROOT

# Exact saved answer shown in math-overlap-his.png, including its automatic wraps.
ANSWER = (r'The surface area is $S = \dfrac{4x^3+22x^2+52x+10}{3x(x+1)}$, from '
          r'dimensions $\frac{x+5}{x}$, $\frac{x+1}{3}$, and $\frac{x}{x+1}$. '
          r'Check: at $x=1$ the box is $6 \times \frac{2}{3} \times \frac{1}{2}$, '
          r'with surface area $\frac{44}{3}$, which matches the formula.')
SCRIPT = r'''
const source=ANSWER, surface=SURFACE, markdown=window.fixtureMarkdown;
const measure=box=>{
  const text=[], walker=document.createTreeWalker(box,NodeFilter.SHOW_TEXT);
  while(walker.nextNode()) {
    const n=walker.currentNode; if(n.parentElement.closest('math')) continue;
    for(let i=0;i<n.length;i++) {
      if(!n.data[i].trim()) continue;
      const range=document.createRange(); range.setStart(n,i); range.setEnd(n,i+1);
      text.push(range.getBoundingClientRect());
    }
  }
  const formulas=[...box.querySelectorAll('math')];
  return formulas.map(m=>{
    const marker=document.createElement('span'); marker.style.cssText='display:inline-block;width:0;height:0';
    const parent=m.parentElement; (parent.style.display==='inline-block'?parent:m).after(marker);
    const baseline=marker.getBoundingClientRect().top; marker.remove();
    const r=m.getBoundingClientRect();
    // Same-line punctuation can share italic overhang; compare neighboring lines.
    const neighbors=[...text.filter(t=>!(t.top<baseline && t.bottom>baseline)),
      ...formulas.filter(n=>n!==m).map(n=>n.getBoundingClientRect())]
      .filter(t=>Math.min(t.right,r.right)-Math.max(t.left,r.left)>0.5);
    const gaps=neighbors.map(t=>Math.max(t.top-r.bottom,r.top-t.bottom));
    return {math:m.textContent,top:r.top,bottom:r.bottom,minGap:gaps.length?Math.min(...gaps):null};
  });
};
const results=[];
let streamed;
if(surface==='box') {
  ui.listen(); ui.words('answer problem 54'); ui.think(); ui.line('✓ '+source);
  streamed=document.querySelector('#thread .a');
}
for(const width of [420,300]) {
  const box=surface==='drawing'?document.querySelector('#text'):streamed||document.createElement('div');
  if(!streamed && surface!=='drawing') {box.className=surface==='agent'?'result md':'a';box.append(markdown(source));}
  box.style.cssText='width:'+width+'px;margin:0';
  [...document.body.children].forEach(n=>n.style.display='none'); document.body.append(box);
  box.style.display=surface==='drawing'?'inline-block':'block';
  document.body.style.cssText='margin:20px;background:#333;color:white;overflow:visible';
  if(surface==='card') {const card=document.createElement('div');card.className='agent-card';box.replaceWith(card);card.append(box);}
  let target=box;
  if(surface==='drawing') {
    box.id='text'; drawingMath(source,22,'white',width); target=document.querySelector('#text');
  }
  document.getAnimations().forEach(a=>a.cancel());
  const boxes=measure(target);
  await new Promise(r=>setTimeout(r,100));
  results.push({width,boxes,stable:JSON.stringify(boxes)===JSON.stringify(measure(target))});
}
return results;
'''


@unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'VM WebKit only')
class InlineMathPageTests(unittest.TestCase):
    def test_inline_math_clears_neighboring_lines_on_all_surfaces(self):
        orbs=(ROOT/'ui/orbs.js').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            src,binary,html=[Path(tmp)/p for p in ('page.swift','page','page.html')]
            for surface,file in [('box','ui/ui.html'),('card','ui/ui.html'),('agent','ui/agents.html'),('drawing','ui/drawing-math.html')]:
                page=(ROOT/file).read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/',orbs)
                formatter=orbs[orbs.index('// TeX → MathML'):orbs.index('export { MML')]
                page+='<script type="module">'+formatter+'\nwindow.fixtureMarkdown=markdown;</script>'
                html.write_text(page)
                harness=HARNESS.replace('width: 260, height: 400','width: 460, height: 700')
                if surface in ('box','card'):
                    harness=harness.replace('cfg.userContentController.add(h, name: "agents")','cfg.userContentController.add(h, name: "c"); cfg.userContentController.add(h, name: "h")').replace('?["action"] as? String == "ready"','?["ready"] != nil')
                src.write_text(harness)
                built=subprocess.run(['swiftc',str(src),'-o',str(binary)],capture_output=True,text=True)
                self.assertEqual(built.returncode,0,built.stderr)
                script=SCRIPT.replace('ANSWER',json.dumps(ANSWER)).replace('SURFACE',json.dumps(surface))
                run=subprocess.run([str(binary),str(html),script],capture_output=True,text=True,timeout=60)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                got=json.loads(run.stdout.strip().splitlines()[-1])
                self.assertFalse([p for p in got['posts'] if isinstance(p,dict) and 'error' in p],got['posts'])
                print('MATH',surface,json.dumps(got['result']),flush=True)
                for row in got['result']:
                    self.assertEqual(len(row['boxes']),7)
                    self.assertTrue(row['stable'],surface)
                    self.assertTrue(all(b['minGap'] is None or b['minGap']>=2 for b in row['boxes']),(surface,row))
