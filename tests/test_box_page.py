"""ui/ui.html in a real WKWebView that is never put in a window: a streamed answer, the Learned pill and an agent's done card."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_shelf_page import HARNESS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = r'''
const a = () => document.querySelector('#thread .turn:last-child .a'), out = {};
ui.listen(); ui.words('what is it'); ui.think();
ui.line('… See [1] and a[0]\u2028- [ ] a task and'); out.brackets = [...a().querySelectorAll('p, li')].map(e => e.textContent.trim());
ui.line('… '); ui.line('… It [the link](https://x.co'); out.open = a().textContent.trim();
ui.line('… It [the link](https://x.co) and'); out.link = [a().querySelector('a')?.textContent, a().textContent.trim()];
ui.line('✓ It [the link](https://x.co) and more.'); out.final = [a().textContent, a().classList.contains('streaming')];
ui.listen(); ui.words('area'); ui.think(); out.math = [];
for (const s of ['the area is $', 'the area is $\\pi r', 'the area is $\\pi r^2', 'the area is $\\pi r^2$ cm', 'the area is $\\pi r^2$ cm and costs $5 today']) { ui.line('… ' + s); out.math.push(a().textContent.trim()); }
out.math.push(!!a().querySelector('math'));
ui.agentDone({id: 'x', title: 'Compare phones', status: 'done', result: 'Found **three** phones [1].', summary: ''});
const card = document.querySelector('.agent-card');
out.card = [card.querySelector('b').textContent, card.querySelector('.a').textContent.trim(), [...card.querySelectorAll('.agent-actions button')].map(b => b.textContent)];
const later = card.querySelector('.agent-actions button:not(.go)'), settle = () => document.getAnimations().filter(a => a.effect.getTiming().iterations !== Infinity).forEach(a => a.finish());   // no window: WebKit never advances motion
later.scrollIntoView(); const r = later.getBoundingClientRect(), rest = getComputedStyle(later).backgroundColor;
out.hot = [ui.pointer([r.x + r.width / 2, r.y + r.height / 2], false), later.classList.contains('hot'), card.classList.contains('hot')]; settle(); out.hot.push(rest !== getComputedStyle(later).backgroundColor);
out.off = [ui.pointer([]), document.querySelectorAll('.hot').length];
out.x = [ui.pointer([1, 1], true), document.getElementById('x').classList.contains('hot'), later.classList.contains('hot')]; ui.pointer([]);
ui.agentDone({id:'setup', title:'Set up focus time', summary:'Ready.', learned:'focus time'});
out.agentLearned = [document.querySelector('.agent-card .tip.learned')?.dataset.k, document.querySelector('.agent-card .tip.learned')?.textContent];
ui.agentDone({id:'other', title:'Other task', summary:'Done.'}); out.noStaleLearned = !document.querySelector('.agent-card .tip.learned');
const ack = () => document.querySelector('#thread .turn:last-child .agent-ack span').textContent;
ui.listen(); ui.agentSteered({id: 'b1', title: 'Ebikes', steer: {text: 'under $1500'}}); ui.agentStarted({id: 'c1', title: 'Bike locks', status: 'running'});
out.steerAndNew = ack();
ui.listen(); ui.agentStarted({id: 'c1', title: 'Ebikes', status: 'running'}); ui.agentStarted({id: 'd1', title: 'Helmets', status: 'queued'}); out.two = ack();
ui.listen(); ui.agentStarted({id: 'e1', title: 'Tents', status: 'queued'}); ui.agentStarted({id: 'f1', title: 'Stoves', status: 'running'}); ui.agentStarted({id: 'g1', title: 'Maps', status: 'running'}); out.mix = ack();
ui.reset(); out.turns = [];
const thread = document.getElementById('thread');
const inView = e => { const r=e.getBoundingClientRect(), t=thread.getBoundingClientRect(); return r.height>0 && r.top>=t.top && r.bottom<=t.bottom+1; };
out.dismissedDuringAsk = [];
for (const mode of ['typed', 'voice', 'approval']) {
  ui.agentDone({id: 'old', title: 'Earlier task', status: 'done', result: 'Finished.'});
  ui.listen(mode === 'typed'); ui.words('Explain the result');
  if(mode === 'voice')ui.line('▸ Reading the request'); else ui.think();
  const turn=thread.lastElementChild, timer=turn.querySelector('.elapsed');
  if(mode === 'approval')ui.ask(['Continue?', 'echo preview']);
  const status=document.getElementById('status').textContent;
  ui.agentCancelled();
  const keptStatus=document.getElementById('status').textContent===status;
  if(mode === 'approval')turn.querySelector('.ok .go').click();
  ui.think(); ui.line('▸ Explaining the result'); settle();
  out.dismissedDuringAsk.push([!document.querySelector('.agent-card'), keptStatus, turn.querySelectorAll('.elapsed').length, timer===turn.querySelector('.elapsed'), inView(timer)]);
  ui.stopped('Answer stopped');
}
ui.reset();
for (let i=0;i<10;i++) {
  ui.listen(true); ui.words(i===1?'Save it as a shortcut':'Change the setting'); if(i%2===0)ui.think();
  ui.line('▸ Working on the request'); ui.line('… Here is the answer so far and'); settle();
  const turn=thread.lastElementChild;
  out.turns.push([inView(turn.querySelector('.elapsed')), inView(turn.querySelector('.step.live')), !turn.querySelector('.elapsed span'), turn.querySelectorAll('.elapsed').length]);
  ui.line('✓ Finished the request.'); if(i===1)ui.line('i Learned: change the setting'); ui.finished(); settle();
}
ui.line('i Support: Atticus is free, leave a tip'); settle();
const support=document.querySelector('.tip.kofi'), link=support.querySelector('button:not(.off)');
link.scrollIntoView(); const lr=link.getBoundingClientRect(), bg=getComputedStyle(link).backgroundColor;
out.support=[link.tagName, ui.pointer([lr.x+lr.width/2,lr.y+lr.height/2]), getComputedStyle(link).cursor]; settle();
out.support.push(bg!==getComputedStyle(link).backgroundColor);
link.click(); out.support.push(!support.isConnected); ui.pointer([]);
ui.dictate(true); ui.learned('Atticus'); const dn = document.getElementById('dn');
out.learned = [dn.textContent, getComputedStyle(dn).display, dn.className];
return out;
'''


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class BoxPageTests(unittest.TestCase):
    def render(self, script):
        harness = HARNESS.replace('cfg.userContentController.add(h, name: "agents")', 'cfg.userContentController.add(h, name: "c"); cfg.userContentController.add(h, name: "h")')
        harness = harness.replace('?["action"] as? String == "ready"', '?["ready"] != nil')
        self.assertEqual(harness.count('name: "c"') + harness.count('["ready"] != nil'), 2)   # the shelf harness, pointed at the box's bridge
        with tempfile.TemporaryDirectory() as tmp:
            page, src, binary = Path(tmp) / 'ui.html', Path(tmp) / 'page.swift', Path(tmp) / 'page'
            page.write_text((ROOT / 'ui/ui.html').read_text().replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text()))
            src.write_text(harness)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(page), script], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        got = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual([p for p in got['posts'] if isinstance(p, dict) and 'error' in p], [])
        return got

    def test_quiet_follow_up_only_changes_status(self):
        got = self.render(r"""
ui.listen(); ui.words('First ask'); ui.think(); ui.line('✓ An answer to read.'); ui.finished();
const thread = document.getElementById('thread'), before = thread.innerHTML;
const orb = document.getElementById('orb').getAttribute('style');
ui.quietListen(true);
const quiet = [document.querySelector('.elapsed .hf')?.textContent, document.getElementById('status').textContent,
    document.body.classList.contains('hearing'), document.getElementById('orb').getAttribute('style') === orb];
ui.quietListen(false); const timeout = [thread.innerHTML === before, document.querySelectorAll('.hf').length];
ui.quietListen(true); ui.listen(); ui.words('And these words');
return {quiet, timeout, gone: document.querySelectorAll('.hf').length, words: thread.lastElementChild.querySelector('.q').textContent};
""")['result']
        self.assertEqual(got['quiet'], ['Listening...', '', False, True])
        self.assertEqual(got['timeout'], [True, 0])
        self.assertEqual(got['gone'], 0)
        self.assertEqual(got['words'], 'And these words')

    def test_box_on_real_webkit(self):
        got = self.render(SCRIPT)
        out = got['result']
        self.assertEqual(out['brackets'], ['See [1] and a[0]', '[ ] a task'])   # a bracket that is no link shows at once
        self.assertEqual(out['open'], 'It')   # a link still arriving waits
        self.assertEqual(out['link'], ['the link', 'It the link'])
        self.assertEqual(out['final'], ['It the link and more.', False])
        self.assertEqual(out['card'][:2], ['Compare phones', 'Found three phones [1].'])
        self.assertIn('Later', ' '.join(out['card'][2]))
        self.assertEqual(out['hot'], [True, True, True, True])   # the box never activates: the native pointer tints a card button and asks for the hand
        self.assertEqual(out['off'], [False, 0])   # off the box: arrow, no tint
        self.assertEqual(out['x'], [True, True, False])   # native's × corner lights the ×
        self.assertEqual(out['agentLearned'], ['Learned', 'Say “focus time” any time.'])
        self.assertTrue(out['noStaleLearned'])
        self.assertEqual(out['steerAndNew'], 'Told the Ebikes agent: under $1500. I started an agent on “Bike locks”. I’ll ping you when it’s done.')   # one ask, both parts
        self.assertEqual(out['math'][:3], ['the area is', 'the area is', 'the area is'])   # math still arriving waits, never a raw $
        self.assertNotIn('$', out['math'][3]); self.assertTrue(out['math'][3].startswith('the area is π'))
        self.assertTrue(out['math'][4].endswith('and costs $5'))   # a price shows at once
        self.assertTrue(out['math'][5])
        self.assertEqual(out['two'], 'I started an agent on “Ebikes”. I’ll ping you when it’s done. Queued an agent for “Helmets”. It starts when another one finishes.')   # the queued one is not called started
        self.assertEqual(out['mix'], 'Queued an agent for “Tents”. It starts when another one finishes. I started agents on “Stoves” and “Maps”. I’ll ping you when they’re done.')
        self.assertEqual(out['turns'], [[True, True, True, 1]] * 10)
        self.assertEqual(out['dismissedDuringAsk'], [[True, True, 1, True, True]] * 3)
        self.assertEqual(out['support'], ['BUTTON', True, 'pointer', True, True])
        self.assertTrue(any(isinstance(p, dict) and p.get('kofi') for p in got['posts']))
        self.assertEqual(out['learned'], ['Learned “Atticus” Undo', 'flex', 'dn tick'])

    def test_minimize_keeps_live_work_and_restores_scroll(self):
        got = self.render(r'''
const tick = ms => new Promise(r => setTimeout(r, ms));
const settle = () => document.getAnimations().filter(a => a.effect.getTiming().iterations !== Infinity).forEach(a => a.finish());
ui.listen(true); ui.words('Explain'); ui.think(); ui.mode(false);
ui.line('… ' + 'A long answer. '.repeat(300));
const thread = document.getElementById('thread'), fold = document.getElementById('fold');
const shown = id => getComputedStyle(document.getElementById(id)).display !== 'none';
thread.dispatchEvent(new WheelEvent('wheel', {deltaY: -1})); thread.scrollTop = 45;
const scroll = thread.scrollTop, height = document.getElementById('card').offsetHeight;
fold.click();
await tick(350); settle();
const out = {compact: [document.body.classList.contains('folded'), document.getElementById('card').offsetHeight < height,
  ...['orb', 'status', 'x'].map(shown), ...['thread', 'comp', 'mode', 'agents-pill', 'grip'].map(shown), fold.getAttribute('aria-expanded')]};
ui.line('▸ Reading the document'); out.step = document.getElementById('status').textContent;
ui.tap([30, 20]); ui.hover(true); out.hover = [document.body.classList.contains('folded'), shown('comp')];
ui.pointer([10, 10]); out.affordance = getComputedStyle(fold).opacity; ui.pointer([]);
ui.line('✓ ' + 'Finished. '.repeat(300));
const r = fold.getBoundingClientRect(); ui.pointer([r.x + r.width / 2, r.y + r.height / 2]); ui.tap([r.x + r.width / 2, r.y + r.height / 2]); await tick(350); settle(); out.restored = [thread.scrollTop === scroll, shown('mode'), fold.getAttribute('aria-expanded')];
fold.click(); await tick(350); settle();
ui.finished(); await tick(350); settle();
out.done = [document.body.classList.contains('folded'), shown('thread'), thread.scrollHeight - thread.scrollTop - thread.clientHeight < 2];
fold.click(); await tick(350); settle(); ui.listen(); out.next = [document.body.classList.contains('folded'), shown('thread')];
fold.click(); await tick(350); settle(); ui.compose(true); out.typing = !document.body.classList.contains('folded');
return out;
''')
        self.assertEqual(got['result'], {
            'compact': [True, True, True, True, True, False, False, False, False, False, 'false'],
            'step': 'Reading the document', 'hover': [True, False], 'affordance': '1',
            'done': [False, True, True], 'restored': [True, True, 'true'],
            'next': [False, True], 'typing': True,
        })
        self.assertIn(56, got['posts'])  # the native height bridge shrinks the actual panel

    def test_picker_renders_answers_and_accepts_spoken_other(self):
        got = self.render(r'''
ui.listen(); ui.words('choose'); ui.think();
ui.pick({q: '**Which** $x^2$?', options: [{label: '**Answer** $\\frac{1}{2}$ <img src=x onerror=alert(1)>', sub: ''}]});
const card = document.querySelector('.pk'), title = card.querySelector('b'), label = card.querySelector('.n');
const out = {rich: [title.querySelector('strong')?.textContent, title.querySelectorAll('math').length, label.querySelector('strong')?.textContent, label.querySelectorAll('math').length], safe: !label.querySelector('img,script') && label.textContent.includes('<img'), margins: [getComputedStyle(title.firstChild).marginTop, getComputedStyle(label.firstChild).marginBottom]};
out.responded = ui.respond('use a different answer'); out.gone = card.classList.contains('gone');
return out;
''')
        self.assertEqual(got['result'], {'rich': ['Which', 1, 'Answer', 1], 'safe': True,
                                        'margins': ['0px', '0px'], 'responded': True, 'gone': True})
        self.assertEqual([p['pick'] for p in got['posts'] if isinstance(p, dict) and 'pick' in p],
                         ['=use a different answer'])

    def test_talking_over_a_picker_hides_it_and_cancel_brings_it_back(self):
        got = self.render(r'''
ui.listen(); ui.words('choose'); ui.think();
ui.pick({q: 'Which?', options: [{label: 'Blue', sub: ''}, {label: 'Red', sub: ''}]});
const card = document.querySelector('.pk'), reply = () => document.querySelector('.q.reply'), status = () => document.getElementById('status').textContent;
ui.pickHear(''); ui.pickHear('the red');
const out = {hidden: card.hidden, said: reply()?.textContent, status: status(), box: document.getElementById('ask').value};
ui.pickHear(); out.back = [card.hidden, !!reply(), status(), card.querySelectorAll('.c').length];
ui.pickHear(''); ui.pickHear('the red one'); out.responded = ui.respond('the red one'); out.gone = card.classList.contains('gone') && !reply();
return out;
''')
        self.assertEqual(got['result'], {'hidden': True, 'said': 'the red', 'status': 'Listening…', 'box': '',
                                         'back': [False, False, 'Waiting for you', 2], 'responded': True, 'gone': True})
        self.assertEqual([p['pick'] for p in got['posts'] if isinstance(p, dict) and 'pick' in p], ['=the red one'])


if __name__ == '__main__':
    unittest.main()
