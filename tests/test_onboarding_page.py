"""Onboarding layout checks in an offscreen WKWebView: no app, window, or user settings."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''import Cocoa
import WebKit
// Loads argv[1] at argv[2]×argv[3] with a recording "ob" bridge, runs argv[4] as an async function body, prints {"result", "posts"}.
final class Harness: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    var posts: [Any] = []
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) { posts.append(m.body) }
    func webView(_ view: WKWebView, didFinish navigation: WKNavigation!) {
        view.callAsyncJavaScript(CommandLine.arguments[4], arguments: [:], in: nil, in: .page) { r in
            switch r {
            case .success(let x):
                let out = try! JSONSerialization.data(withJSONObject: ["result": x ?? NSNull(), "posts": self.posts])
                print(String(data: out, encoding: .utf8)!); exit(0)
            case .failure(let e): print(e); exit(1)
            }
        }
    }
}
let app = NSApplication.shared
let harness = Harness(), cfg = WKWebViewConfiguration(), width = Double(CommandLine.arguments[2])!, height = Double(CommandLine.arguments[3])!
cfg.userContentController.add(harness, name: "ob")
cfg.userContentController.add(harness, name: "c")
cfg.userContentController.add(harness, name: "h")
let view = WKWebView(frame: NSRect(x: 0, y: 0, width: width, height: height), configuration: cfg)
view.navigationDelegate = harness
view.loadHTMLString(try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8), baseURL: nil)
DispatchQueue.main.asyncAfter(deadline: .now() + 20) { print("timeout"); exit(3) }
app.run()
'''
EVERY_PAGE = '''
  const filler = ' Extra setup guidance that can wrap onto several lines on a small display.'.repeat(5);
  const list = document.getElementById('list');
  if (!list.children.length) list.innerHTML = Array.from({length: 5}, (_, i) =>
    `<div class="row"><div class="txt"><b>Permission ${i + 1}</b><span>Why this permission is needed.${filler}</span></div><button class="allow">Allow</button></div>`).join('');
  document.querySelectorAll('p.sub, .txt span, .note').forEach(node => node.textContent += filler);
  document.getElementById('srv').hidden = false;   // the AI step at its tallest: custom server fields open
  const rows = [], bar = document.getElementById('bar');
  for (const page of document.querySelectorAll('.page')) {
    document.querySelectorAll('.page').forEach(other => other.classList.toggle('on', other === page));
    page.inert = false;
    page.scrollTop = page.scrollHeight;
    void page.offsetHeight;
    const frame = page.getBoundingClientRect(), welcome = page.id === 'welcome';
    const actions = welcome ? [document.getElementById('start')] : [...bar.querySelectorAll('button:not([hidden])')];
    rows.push({
      id: page.id,
      horizontal: page.scrollWidth <= page.clientWidth + 1,
      actions: actions.length,
      reachable: actions.every(button => {
        const rect = button.getBoundingClientRect();
        return rect.top >= 0 && rect.bottom <= innerHeight && rect.left >= 0 && rect.right <= innerWidth
          && (welcome ? rect.top >= frame.top - 1 && rect.bottom <= frame.bottom + 1 : rect.top >= frame.bottom - 1);   // the bar never covers a step
      })
    });
  }
  return JSON.stringify({rows});
'''
# The real page script with live status sent in like Onboarding.push/checkPlan, then every row is scrolled to and clicked like a user would.
PERMISSION_ROWS = '''
  const tick = ms => new Promise(r => setTimeout(r, ms));
  while (!window.ob) await tick(10);
  const $ = id => document.getElementById(id), on = GRANTED;
  ob.plan(on ? {ok: true, need: '', client: 'claude', text: 'Ready with your Claude plan.'} : {ok: false, need: 'login', client: 'claude', text: 'Sign in to Claude Code to use your plan.'});
  ob.set(Object.fromEntries(['mic', 'speech', 'ax', 'screen', 'auto', 'calendar', 'tools', 'chrome'].map(k => [k, on])));
  const reveal = (el, page) => {   // scroll the page only: an overflow:hidden list is not something a user can scroll
    const r = el.getBoundingClientRect(), f = page.getBoundingClientRect();
    page.scrollTop += r.top - f.top - (f.height - r.height) / 2; void page.offsetHeight;
  };
  const inside = (el, box) => { const r = el.getBoundingClientRect(), f = box.getBoundingClientRect(); return r.top >= f.top - 1 && r.bottom <= f.bottom + 1 && r.left >= f.left - 1 && r.right <= f.right + 1; };
  const hit = (el, page) => {
    reveal(el, page);
    const r = el.getBoundingClientRect(), h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return h && el.contains(h) ? h : null;
  };
  const tap = (el, page) => { const h = hit(el, page); h?.click(); return !!h; };
  const rows = page => [...$(page).querySelectorAll('.row')].map(row => {
    const list = row.parentElement, allow = row.querySelector('.allow'), shows = getComputedStyle(allow).display !== 'none';
    reveal(row, $(page));
    return {page, id: row.id, inList: inside(row, list), onPage: inside(row, $(page)),
      why: !!hit(row.querySelector('.txt span'), $(page)), name: !!hit(row.querySelector('.txt b'), $(page)),
      check: row.classList.contains('ok') && !shows && !!hit(row.querySelector('.check'), $(page)), allow: shows && tap(allow, $(page)) && allow.dataset.id};
  });
  const out = [], stuck = error => JSON.stringify({error});
  if (!tap($('start'), $('welcome'))) return stuck('Get Started is unreachable');
  out.push(...rows('ai'));
  if (!tap($('next'), document.body)) return stuck('AI has no reachable way on');
  if ($('model').classList.contains('on') !== on) return stuck('the work model step shows only once the Claude plan works');
  if (on && !tap($('next'), document.body)) return stuck('work model has no reachable way on');
  if (!$('perms').classList.contains('on')) return stuck('AI has no way on to Mac access');
  out.push(...rows('perms'));
  if (!tap($('next'), document.body) || !$('try').classList.contains('on')) return stuck('permissions have no reachable way on');
  return JSON.stringify(out);
'''


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class OnboardingPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        html = (ROOT / 'ui/onboarding.html').read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text())
        cls.page = Path(cls.tmp.name) / 'onboarding.html'
        still = '<style>*,*::before,*::after{transition:none!important;animation:none!important}</style>'   # rows land at once, as under Reduce Motion
        cls.page.write_text(re.sub(r'<script\b.*?</script>', '', html, flags=re.S).replace('<head>', '<head>' + still, 1))
        cls.live = Path(cls.tmp.name) / 'live.html'
        cls.live.write_text(html.replace('<head>', '<head>' + still, 1))
        cls.box = Path(cls.tmp.name) / 'box.html'
        cls.box.write_text((ROOT / 'ui/ui.html').read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text()))
        source, cls.binary = Path(cls.tmp.name) / 'page.swift', Path(cls.tmp.name) / 'page'
        source.write_text(HARNESS)
        built = subprocess.run(['swiftc', str(source), '-o', str(cls.binary)], capture_output=True, text=True)
        assert built.returncode == 0, built.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_page(self, page, width, height, script):
        result = subprocess.run(
            [str(self.binary), str(page), str(width), str(height), script],
            capture_output=True, text=True, timeout=30, env={**os.environ, 'ATTICUS_DIR': self.tmp.name})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_missing_permission_line_and_one_settings_button(self):
        out = self.run_page(self.box, 640, 612, """
while (!window.ui) await new Promise(r=>setTimeout(r,10));
ui.permission('Waiting for voice access…');
const waiting=document.querySelector('.permission button').hidden;
ui.permission('Allow Microphone for Atticus to listen to you.');
const card=document.querySelector('.permission'), text=card.querySelector('b').textContent;
card.querySelector('button').click();
const buttons=card.querySelectorAll('button').length;
ui.permission(null);
return {waiting,text,buttons,cleared:!document.querySelector('.permission')};
""")
        self.assertEqual(out['result'], dict(waiting=True, text='Allow Microphone for Atticus to listen to you.', buttons=1, cleared=True))
        self.assertEqual([p for p in out['posts'] if isinstance(p,dict) and 'permissionSettings' in p], [{'permissionSettings':True}])

    def test_every_step_scrolls_at_small_sizes(self):
        for width, height in ((640, 612), (480, 420), (360, 320)):
            with self.subTest(size=(width, height)):
                measured = json.loads(self.run_page(self.page, width, height, EVERY_PAGE)['result'])
                self.assertEqual([page['id'] for page in measured['rows']], ['welcome', 'ai', 'model', 'perms', 'try', 'dictate', 'show', 'improve', 'tip', 'done'])
                for page in measured['rows']:
                    self.assertTrue(page['horizontal'], f"{page['id']} overflows horizontally at {width}×{height}")
                    self.assertGreater(page['actions'], 0, f"{page['id']} has no action")
                    self.assertTrue(page['reachable'], f"{page['id']} action is unreachable at {width}×{height}")

    def test_inline_dictation_uses_focused_field_and_preserves_selection(self):
        out = self.run_page(self.live, 640, 612, """
while (!window.ob) await new Promise(r=>setTimeout(r,10));
const $=id=>document.getElementById(id), visit=id=>document.querySelector(`[data-to="${id}"]`).click();
ob.set({ax:true});ob.prefs({hotkeyLabel:'fn',dictateHotkeyLabel:'⌃D'});
visit('dictate');visit('dictate');webkit.messageHandlers.ob.postMessage({do:'mark'});ob.keys('⌃');
const lit=$('dictatekeys').firstChild.classList.contains('lit');ob.keys('');
const released=!$('dictatekeys').firstChild.classList.contains('lit');
ob.keys(['⌃','D']);const letter=$('dictatekeys').lastChild.classList.contains('lit');ob.keys(['Space']);const exact=!$('dictatekeys').lastChild.classList.contains('lit');
const field=$('dictate-field');field.value='before after';field.setSelectionRange(7,7);
ob.dictationBegin(42);const inserted=ob.dictated(42,'hello '), value=field.value;
ob.dictationBegin(43);field.setSelectionRange(0,6);const moved=ob.dictated(43,'wrong');
field.setSelectionRange(0,0);ob.dictationBegin(44);ob.dictationCancel();const cancelled=ob.dictated(44,'wrong');
visit('try');const stale=ob.dictated(42,'wrong');
ob.prefs({dictateHotkeyLabel:'⌃D',dictateHotkeyTaken:true});const blocked=$('dictate-talk').textContent;
visit('perms');visit('ai');visit('perms');visit('try');
return {lit,released,letter,exact,inserted,value,stale,moved,cancelled,blocked};
""")
        self.assertEqual(out['result'], {'lit':True,'released':True,'letter':True,'exact':True,'inserted':True,'value':'before hello after','stale':False,'moved':False,'cancelled':False,'blocked':'This shortcut is in use by another app.'})
        self.assertEqual(len([p for p in out['posts'] if p.get('do') == 'permissionsReady']), 1)
        before_mark = out['posts'][:out['posts'].index({'do':'mark'})]
        self.assertEqual([p['v'] for p in before_mark if p.get('do') == 'dictationFocus'], ['true'], 'revisiting a focused practice field keeps it the dictation target')

    def test_provider_radio_keys_select_and_wrap(self):
        got = self.run_page(self.live, 640, 612, '''
while(!window.ob) await new Promise(r=>setTimeout(r,10));
document.querySelector('[data-to=ai]').click();
const buttons=[...document.querySelectorAll('.opt')];
buttons[0].dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true}));
const selected=buttons.map(b=>[b.getAttribute('aria-checked'),b.tabIndex]);
buttons[1].dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true,cancelable:true}));
buttons[0].dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true,cancelable:true}));
return {selected,server:!document.getElementById('srv').hidden,tab:buttons.map(b=>b.tabIndex)};
''')
        self.assertEqual(got['result'], {'selected':[['false',-1],['true',0],['false',-1],['false',-1]], 'server':True, 'tab':[-1,-1,-1,0]})
        self.assertEqual([p['client'] for p in got['posts'] if isinstance(p,dict) and p.get('do')=='provider'], ['devin','claude'])

    def test_skip_setup_stays_at_top_right_and_jumps_to_the_optional_pages(self):
        script = '''
          while (!window.ob) await new Promise(r => setTimeout(r, 10));
          const skip = document.getElementById('skip'), rows = [];
          for (const id of ['welcome', 'ai', 'model', 'perms', 'try', 'dictate']) {
            document.querySelector(`[data-to="${id}"]`)?.click();

            const page = document.getElementById(id);
            page.scrollTop = page.scrollHeight;
            const r = skip.getBoundingClientRect(), hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
            rows.push(page.classList.contains('on') && r.top >= 0 && r.bottom <= 50 && r.right <= innerWidth && r.left > innerWidth / 2 && skip.contains(hit));
            hit?.click();
            rows.push(document.getElementById('improve').classList.contains('on') && !skip.hidden);
          }
          return rows;
        '''
        for width, height in ((640, 612), (480, 420), (360, 320)):
            out = self.run_page(self.live, width, height, script)
            self.assertTrue(all(out['result']), out['result'])
            self.assertNotIn({'do': 'done'}, out['posts'])

    def test_optional_choices_and_final_actions_use_the_shared_bar(self):
        out = self.run_page(self.live, 640, 612, """
while (!window.ob) await new Promise(r=>setTimeout(r,10));
const $=id=>document.getElementById(id), visit=id=>document.querySelector(`[data-to="${id}"]`).click();
visit('show');$('next').click();
const improve=$('improve').classList.contains('on')&&!$('later').hidden&&$('later').textContent==='Not Now'&&$('next').textContent==='Help Improve';
$('later').click();const no=$('tip').classList.contains('on');
$('back').click();$('next').click();const yes=$('tip').classList.contains('on');
$('kofi').click();const stays=$('tip').classList.contains('on');$('next').click();
ob.prefs({dictateHotkeyLabel:'fn⌃'});const keys=$('idea-key').textContent;
ob.prefs({dictateHotkeyLabel:''});const hidden=$('idea-dict').hidden;
$('feedback-link').click();const label=$('next').textContent;$('next').click();
return {improve,no,yes,stays,keys,hidden,label,done:$('done').classList.contains('on'),actions:[...$('bar').querySelectorAll('button')].filter(b=>!b.hidden).map(b=>b.id)};
""")
        self.assertEqual(out['result'], dict(improve=True, no=True, yes=True, stays=True, keys='fn⌃', hidden=True, label='Start Using Atticus', done=True, actions=['back','next']))
        self.assertEqual([p for p in out['posts'] if p.get('do') in ('set','kofi','feedback','done')], [
            {'do':'set','k':'improve','v':'false'}, {'do':'set','k':'improve','v':'true'},
            {'do':'kofi'}, {'do':'feedback'}, {'do':'done'}])

    def test_work_model_step_follows_the_ai(self):
        out = self.run_page(self.live, 640, 612, """
while (!window.ob) await new Promise(r=>setTimeout(r,10));
const $=id=>document.getElementById(id), on=()=>document.querySelector('.page.on').id, dot=()=>!document.querySelector('[data-to=model]').hidden;
const after=(plan, prefs={}, server='')=>{ob.server({apiBase:server,apiModel:''});ob.prefs({routing:'balanced',...prefs});ob.plan(plan);$('ai').classList.contains('on')||document.querySelector('[data-to=ai]').click();$('next').click();const next=on();$('back').click();return [next,dot(),on()];};
const ok=c=>({ok:true,need:'',client:c,text:'Ready.'});
const claude=after(ok('claude')), devin=after(ok('devin')), pi=after(ok('pi')), server=after(ok('server'),{},'http://localhost:11434');
const cheapest=after(ok('claude'),{routing:'cheapest'}), signedOut=after({ok:false,need:'login',client:'claude',text:'Sign in'});
after(ok('claude'),{model:'haiku',agentModel:'sonnet'});$('next').click();
const picked=document.querySelector('.mc[aria-checked=true]').dataset.m;
document.querySelector('.mc[data-m=opus]').click();const opus=document.querySelector('.mc[aria-checked=true]').dataset.m;$('next').click();
return {claude,devin,pi,server,cheapest,signedOut,picked,opus,after:on()};
""")
        self.assertEqual(out['result'], {'claude': ['model', True, 'ai'], 'devin': ['perms', False, 'ai'], 'pi': ['perms', False, 'ai'],
                                         'server': ['perms', False, 'ai'], 'cheapest': ['perms', False, 'ai'], 'signedOut': ['perms', False, 'ai'],
                                         'picked': 'sonnet', 'opus': 'opus', 'after': 'perms'})
        self.assertEqual([p for p in out['posts'] if p.get('do') == 'set'], [{'do': 'set', 'k': 'model', 'v': 'opus'}])

    def test_work_model_skip_and_continue_keep_the_default(self):
        out = self.run_page(self.live, 640, 612, """
while (!window.ob) await new Promise(r=>setTimeout(r,10));
const $=id=>document.getElementById(id), on=()=>document.querySelector('.page.on').id;
ob.server({apiBase:'',apiModel:''});ob.prefs({model:'haiku',agentModel:'sonnet',routing:'balanced'});ob.plan({ok:true,need:'',client:'claude',text:'Ready.'});
document.querySelector('[data-to=model]').click();const label=$('next').textContent, main=!$('next').classList.contains('quiet');
document.querySelector('.mc[data-m=sonnet]').click();$('next').click();const next=on();
document.querySelector('[data-to=model]').click();$('skip').click();
return {label,main,next,skip:on()};
""")
        self.assertEqual(out['result'], {'label': 'Continue', 'main': True, 'next': 'perms', 'skip': 'improve'})
        self.assertEqual([p for p in out['posts'] if p.get('do') == 'set'], [])

    def test_every_permission_row_scrolls_into_reach(self):
        for width, height in ((640, 612), (480, 420)):
            for granted in (False, True):
                with self.subTest(size=(width, height), granted=granted):
                    out = self.run_page(self.live, width, height, PERMISSION_ROWS.replace('GRANTED', str(granted).lower()))
                    rows = json.loads(out['result'])
                    self.assertIsInstance(rows, list, rows)
                    self.assertEqual([r['page'] for r in rows].count('perms'), 5)
                    self.assertEqual([r['page'] for r in rows].count('ai'), 1)   # the AI's status row
                    for r in rows:
                        where = f"{r['id']} at {width}×{height}"
                        self.assertTrue(r['inList'], f'{where} is clipped by its list')
                        self.assertTrue(r['onPage'], f'{where} cannot be scrolled into view')
                        self.assertTrue(r['name'] and r['why'], f'{where} name or description is hidden')
                        if granted:
                            self.assertTrue(r['check'], f'{where} does not show its check')
                        else:
                            self.assertTrue(r['allow'], f'{where} button cannot be clicked')
                    grants = [p['id'] for p in out['posts'] if p.get('do') == 'grant']
                    self.assertEqual(grants, [] if granted else [r['allow'] for r in rows])


if __name__ == '__main__':
    unittest.main()
