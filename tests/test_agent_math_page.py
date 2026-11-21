"""ui/agents.html in a real WKWebView that is never put in a window: an agent's answer renders as the box's does, math as MathML and lists as lists, in the view, its timeline, the chip and while it streams."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_shelf_page import HARNESS, ROOT

RESULT = ("Don't cross-multiply. That trick is only for solving a proportion with an equals sign, and these problems don't have one.\n\n"
          "For a fraction of radicals, work straight across:\n"
          "- Outside numbers go with outside numbers, and the insides go with the insides. For example, $\\dfrac{4\\sqrt{18}}{2\\sqrt{6}} = \\dfrac{4}{2}\\sqrt{\\dfrac{18}{6}} = 2\\sqrt{3}$.\n"
          "- If a radical is left on the bottom, multiply the top and bottom by what's missing to rationalize it. For $\\dfrac{5}{\\sqrt{3}}$, multiply by $\\dfrac{\\sqrt{3}}{\\sqrt{3}}$ to get $\\dfrac{5\\sqrt{3}}{3}$.\n\n"
          "I couldn't tell exactly how problem C is set up from the page text. If you tell me which C it is, or hold it up on screen, I'll walk through it step by step.")
DISPLAY = 'The area:\n$$\nA = \\pi r^2\n$$\nso it grows with $r^2$.'
SCRIPT = r'''
const tick = ms => new Promise(r => setTimeout(r, ms)), now = Date.now() / 1000, out = {};
const settle = () => document.getAnimations().filter(a => a.effect.getTiming().iterations !== Infinity).forEach(a => a.finish());
const raw = n => /[$\\{}^]/.test(n.textContent);   // TeX source on screen
const look = n => n && {math: n.querySelectorAll('math').length, failed: n.querySelectorAll('.tex').length, raw: raw(n), items: n.querySelectorAll('ul > li').length,
  frac: Math.max(0, ...[...n.querySelectorAll('mfrac')].map(f => Math.round(f.getBoundingClientRect().height)))};   // stacked, not one line of text
const row = (id, result, more = {}) => ({id: id.repeat(32), title: 'Radicals', status: 'done', created: now - 60, started: now - 60, ended: now - 5, result, summary: result, timeline: [{text: result}], cost: 0, ...more});
const done = row('a', RESULT), links = row('c', 'See [the docs](https://example.com/d).\n\n| Item | Price |\n|---|---|\n| Pen | $5 |');
agents.mode('view'); agents.list([done, links]); agents.select(done.id); await tick(50);
out.view = look(document.querySelector('[data-key=result] .result')); out.note = look(document.querySelector('.entry.note'));
agents.select(links.id); await tick(30); document.querySelector('.result a').click();
out.num = [...document.querySelectorAll('.result th, .result td')].map(c => c.className);
const stream = async (text, id) => { const bad = []; let at = 0;
  agents.list([row(id, '', {status: 'running', summary: '', timeline: [], ended: 0})]); agents.select(id.repeat(32));
  while (at < text.length) { const next = Math.min(text.length, at + 3); agents.text({id: id.repeat(32), text: text.slice(at, next)}); at = next;
    agents.select(id.repeat(32)); const w = document.querySelector('.writing .result'); if (!w || raw(w)) bad.push(text.slice(0, at)); }   // windowless: no frames, so render as the next frame would
  return [bad.slice(0, 3), look(document.querySelector('.writing .result'))]; };
const narration = String.raw`Use **radicals**: \(\dfrac{4}{2}\) and \[\sqrt{3}\].`;
const working = row('e', '', {status: 'running', step: narration, note: narration, timeline: [{text: narration}], ended: 0});
agents.list([working]); agents.select(working.id);
out.current = look(document.querySelector('.now .current'));
out.currentBold = !!document.querySelector('.now .current strong');
agents.state({...working, note: String.raw`Still \(\dfrac{4}`, step: String.raw`Still \(\dfrac{4}`});
out.openCurrent = look(document.querySelector('.now .current'));
const label = 'Reading $file_name$';
agents.state({...working, note: undefined, step: label, timeline: [{tool: 'Read', text: label}]});
out.label = [document.querySelector('.now .current').textContent, document.querySelector('.entry.read .line span').textContent];
agents.list([row('f', 'Finished.', {changes: narration})]); agents.select('f'.repeat(32));
out.changes = look(document.querySelector('.result .changes'));
out.stream = await stream(RESULT, 'b'); out.display = await stream(DISPLAY, 'd');
agents.mode('shelf'); agents.list([done]); agents.expand(done.id); await tick(30); settle();
out.chip = look(document.querySelector('.chip.expanded .current'));
return out;
'''.replace('RESULT', json.dumps(RESULT)).replace('DISPLAY', json.dumps(DISPLAY))


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class AgentMathPageTests(unittest.TestCase):
    def test_agent_answers_render_markdown_and_math_like_the_box(self):
        with tempfile.TemporaryDirectory() as tmp:
            page, src, binary = Path(tmp) / 'agents.html', Path(tmp) / 'page.swift', Path(tmp) / 'page'
            page.write_text((ROOT / 'ui/agents.html').read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text()))
            src.write_text(HARNESS)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(page), SCRIPT], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        got = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual([p for p in got['posts'] if 'error' in p], [])
        out = got['result']
        for where in ('view', 'note', 'chip'):
            with self.subTest(where=where):
                self.assertEqual(out[where]['math'], 4)   # every $…$ is a formula
                self.assertEqual([out[where]['failed'], out[where]['raw'], out[where]['items']], [0, False, 2])   # none shown as TeX source; the bullets are a list
                self.assertGreater(out[where]['frac'], 20)   # \dfrac stacks
        for where in ('current', 'changes'):
            self.assertEqual([out[where]['math'], out[where]['failed'], out[where]['raw']], [2, 0, False])
        self.assertTrue(out['currentBold'])
        self.assertFalse(out['openCurrent']['raw'])   # the 200-character narration can end inside math
        self.assertEqual(out['label'], ['Reading $file_name$'] * 2)   # tool labels stay literal
        self.assertEqual(out['stream'][0], [])   # no frame of the stream shows a $ or \dfrac
        self.assertEqual([out['stream'][1]['math'], out['stream'][1]['items']], [4, 2])
        self.assertEqual(out['display'][0], [])   # $$ display math open across lines waits too
        self.assertEqual(out['display'][1]['math'], 2)
        self.assertIn({'action': 'open', 'id': 'c' * 32, 'target': 'https://example.com/d'}, got['posts'])   # an answer's link opens through the agent
        self.assertEqual(out['num'], ['', 'num', '', 'num'])   # a price column aligns right


if __name__ == '__main__':
    unittest.main()
