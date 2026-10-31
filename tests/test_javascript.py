"""Syntax checks for the embedded UI modules using the installed Node runtime."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which('node'), 'Node is optional for UI syntax checks')
class JavaScriptTests(unittest.TestCase):
    def test_embedded_scripts_parse(self):
        root = Path(__file__).resolve().parents[1]
        files = list((root / 'ui').glob('*.html')) + list((root / 'tests').glob('*.html'))
        for path in files:
            for attrs, code in re.findall(r'<script([^>]*)>(.*?)</script>', path.read_text(), re.S):
                if 'text/plain' in attrs or 'src=' in attrs:
                    continue
                with self.subTest(file=path.name):
                    p = subprocess.run(['node', '--check', '--input-type=module'], input=code, capture_output=True, text=True)
                    self.assertEqual(p.returncode, 0, p.stderr)

    def test_failed_meeting_stream_restores_retry(self):
        source = (Path(__file__).resolve().parents[1] / 'ui' / 'meeting.html').read_text()
        helper = re.search(r'const retryAnswer=.*?;\n', source).group(0)
        script = '''
let sent, touched=new Set(), post=value=>sent=value;
const old={removed:false,remove(){this.removed=true}};
const body={button:null,append(value){this.button=value}};
const card={dataset:{id:'q1',question:'Question?'},querySelector(selector){
 if(selector==='.response.streaming')return old;
 if(selector==='.answer')return body.button;
 if(selector==='.body')return body;
}};
const document={createElement:()=>({className:'',classList:{remove(){}},disabled:true,textContent:'',onclick:null})};
''' + helper + '''
const button=retryAnswer(card);
button.onclick();
if(!old.removed||button.disabled||button.textContent!=='Try again'||sent.id!=='q1'||sent.text!=='Question?'||!touched.has('q1'))process.exit(1);
'''
        result = subprocess.run(['node', '--input-type=module'], input=script, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dictation_pill_shows_the_wave_not_the_words(self):
        source = (Path(__file__).resolve().parents[1] / 'ui' / 'ui.html').read_text()
        native = (Path(__file__).resolve().parents[1] / 'Atticus.swift').read_text()
        self.assertIn('<span id="dictwave" role="img" aria-label="Listening"></span>', source)
        helper = source[source.index('  const dictateMode ='):source.index('\n  };', source.index('  const dictateMode =')) + 5]
        dictate = source[source.index('    dictate(on) {'):source.index('    locked(on) {')]
        script = '''const foldBox = () => {}; const bars=[{style:{height:'21px'}},{style:{height:'9px'}}];let gone=0,state;
const $=id=>id==='thread'?{querySelectorAll:s=>s==='.turn.dict'?[{remove(){gone++;}}]:[]}:{children:bars},pill=s=>{state=s;};
const document={body:{classList:{toggle(){},remove(){}}}};
''' + helper + '''
const ui={''' + dictate + '''};ui.dictate(true);if(bars.some(b=>b.style.height)||gone!==1||state!=='')process.exit(1);'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, "a new dictation shows the last one's wave, state or empty turn " + result.stderr)
        self.assertIn('body.dictate.hearing #dictwave', source)
        self.assertIn("classList.toggle('hearing', listening)", source)
        self.assertIn("for (let i = 0; i < 9; i++) $('dictwave').append", source)
        self.assertIn('if dictating { scheduleDictateAhead(); return }', native)

    def test_onboarding_finish_names_missing_voice_requirements(self):
        source = (Path(__file__).resolve().parents[1] / 'ui' / 'onboarding.html').read_text()
        helper = source[source.index('  const paintDone='):source.index('\n  window.ob', source.index('  const paintDone='))]
        script = '''
const nodes=new Map(),$=id=>{if(!nodes.has(id))nodes.set(id,{textContent:''});return nodes.get(id)};
''' + helper + '''
paintDone({claude:false,mic:true,speech:false,ax:false});
if($('done-title').textContent!=='Setup isn’t finished yet'||!$('done-sub').textContent.includes('AI provider, Speech Recognition, Accessibility')||$('finish').textContent!=='Finish Setup Later')process.exit(1);
paintDone({claude:true,mic:true,speech:true,ax:false});
if($('done-title').textContent!=='Voice is ready'||$('finish').textContent!=='Start Using Atticus')process.exit(2);
'''
        result = subprocess.run(['node', '--input-type=module'], input=script, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_answer_markdown_and_math_build_safe_dom(self):
        source = (Path(__file__).resolve().parents[1] / 'ui' / 'orbs.js').read_text()
        helper = source[source.index('// TeX → MathML'):source.index('export { MML')]
        script = r'''
class N{constructor(tag,ns){this.tag=tag;this.ns=ns||'';this.kids=[];this.attrs={};this.className=''}
 append(...k){this.kids.push(...k)}appendChild(k){this.kids.push(k);return k}setAttribute(k,v){this.attrs[k]=v}
 set textContent(s){this.kids=[String(s)]}get textContent(){return this.kids.map(k=>typeof k==='string'?k:k.textContent).join('')}get childNodes(){return this.kids}}
const document={createElement:t=>new N(t),createElementNS:(ns,t)=>new N(t,ns),createDocumentFragment:()=>new N('#')};
const html=n=>typeof n==='string'?n:'<'+n.tag+(n.className?'.'+n.className:'')+Object.entries({...n.attrs,...(n.title?{title:n.title}:{}),...(n.href?{href:n.href}:{}),...(n.start?{start:n.start}:{})}).map(([k,v])=>' '+k+'='+v).join('')+'>'+n.kids.map(html).join('')+'</'+n.tag+'>';
''' + helper + r'''
const md=t=>html(markdown(t)),expect=(got,want,name)=>{if(!got.includes(want)){console.error(name+'\n got: '+got+'\nwant: '+want);process.exit(1)}};
expect(md('$\\frac{\\sqrt{7}}{\\sqrt{10}-\\sqrt{2}}$'),'<math displaystyle=true><mfrac><msqrt><mn>7</mn></msqrt><mrow><msqrt><mn>10</mn></msqrt><mo>−</mo><msqrt><mn>2</mn></msqrt></mrow></mfrac></math>','A stacked fraction with real radicals');
expect(md('$$x^2_1$$'),'<math display=block><msubsup><mi>x</mi><mn>1</mn><mn>2</mn></msubsup></math>','Display math with scripts');
expect(md('$\\sum_{i=1}^n i$'),'<munderover><mo movablelimits=true>∑</mo>','Big operators take limits');
expect(md('$\\begin{pmatrix}1&2\\\\3&4\\end{pmatrix}$'),'<mo fence=true stretchy=true>(</mo><mtable><mtr><mtd><mn>1</mn></mtd><mtd><mn>2</mn></mtd></mtr><mtr>','Matrices are tables in fences');
expect(md('$f(x)=\\sin x$'),'<mi>f</mi><mo stretchy=false>(</mo><mi>x</mi><mo stretchy=false>)</mo><mo>=</mo><mrow><mi>sin</mi><mspace width=0.1667em></mspace></mrow><mi>x</mi>','Plain parentheses keep their size; a function name is spaced');
expect(md('$\\frac12$ and $\\text{area } r$'),'<mfrac><mn>1</mn><mn>2</mn></mfrac>','\\frac12 takes one digit each');
expect(md('$\\text{area } r$'),'<mtext>area </mtext>','Text keeps its spaces');
expect(md('$\\weird{x}$'),'<span.tex>\\weird{x}</span>','Unknown TeX shows as written');
expect(md('$\\frac{1}{$'),'<span.tex>\\frac{1}{</span>','A broken formula shows as written');
expect(md('It costs $5 or $10, and \\$3 more.'),'<p>It costs $5 or $10, and $3 more.</p>','Dollar amounts stay money');
expect(md('**Bold** *it* `code` [OpenTable](https://www.opentable.com) see https://example.com/a.'),'<p><strong>Bold</strong> <em>it</em> <code>code</code> <a title=https://www.opentable.com href=https://www.opentable.com>OpenTable</a> see <a href=https://example.com/a>https://example.com/a</a>.</p>','Inline Markdown');
expect(md('[x](javascript:alert(1)) <img src=x onerror=alert(1)>'),'<p>[x](javascript:alert(1)) <img src=x onerror=alert(1)></p>','No script links and no HTML: only text');
expect(md('## Steps\n3. one\n4. **two**\n\n- a\n- b'),'<div.h>Steps</div><ol start=3><li>one</li><li><strong>two</strong></li></ol><ul><li>a</li><li>b</li></ul>','Headings and lists');
expect(md('one line\nnext line\n\nnew para'),'<p>one line<br></br>next line</p><p>new para</p>','Paragraphs keep the line breaks the answer has');
expect(md('**Branch:** r2\n**Commit:** 3c14f84'),'<p><strong>Branch:</strong> r2<br></br><strong>Commit:</strong> 3c14f84</p>','Label lines stay on their own lines');
expect(md('$$\na^2\n$$'),'<math display=block><msup><mi>a</mi><mn>2</mn></msup></math>','Display math may span lines');
expect(md('Desks:\n| Desk | Price |\n|---|:-:|\n| **E7** | $300 |'),'<p>Desks:</p><div.table><table><tr><th>Desk</th><th>Price</th></tr><tr><td><strong>E7</strong></td><td>$300</td></tr></table></div>','Tables');
expect(md('See:\n```\n  /|\n\n /_|  **b**\n```\nDone.'),'<p>See:</p><pre>  /|\n\n /_|  **b**</pre><p>Done.</p>','Fenced blocks keep their lines as plain text');
expect(md('Above\n---\nBelow'),'<p>Above</p><hr></hr><p>Below</p>','A rule between paragraphs');
expect(md('snake_case_name and _em_'),'<p>snake_case_name and <em>em</em></p>','Underscores inside words stay');
'''
        result = subprocess.run(['node', '--input-type=module'], input=script, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_worker_start_failure_has_persistent_recovery_actions(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / 'ui' / 'ui.html').read_text()
        native = (root / 'Atticus.swift').read_text()
        self.assertIn('Atticus’s helper couldn’t start', page)
        self.assertIn("post({workerRetry:true})", page)
        self.assertIn("post({setup:true})", page)
        self.assertIn('pinned = true; js("workerFailed"); show()', native)
        self.assertIn('if b["workerRetry"] != nil, !busy', native)
        failed = page[page.index('    workerFailed(){'):page.index('    agentDone(row)')]
        self.assertNotIn('retry', re.search(r"className='([^']*)'", failed).group(1), 'typed asks are not answers to this card')
        self.assertIn("'.rewrite, .paused, .worker'", page)

    def test_paused_shortcut_offers_rate_limited_resume(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / 'ui' / 'ui.html').read_text()
        native = (root / 'Atticus.swift').read_text()
        self.assertIn("post({resume:true})", page)
        self.assertIn("Date().timeIntervalSince(pausedNotice) > 4", native)
        resume = native[native.index('if b["resume"] != nil {'):native.index('if b["kofi"]')]
        self.assertIn('Atticus.settings.apply("paused", false)', resume)

    def test_minimize_animates_via_fold_bridge_and_refolds_after_questions(self):
        root = Path(__file__).resolve().parents[1]
        box = (root / 'ui/ui.html').read_text()
        swift = (root / 'Atticus.swift').read_text()
        self.assertIn('body.fold-morph', box)
        self.assertIn('foldBeforeQuestion', box)
        self.assertIn('unfoldForAnswer(focusAnswer)', box)
        self.assertIn('refoldIfAsked()', box)
        self.assertIn('if let id = b["fold"] as? Int, let h = b["h"] as? NSNumber', swift)
        self.assertIn('js("foldSettled", id)', swift)


if __name__ == '__main__':
    unittest.main()
