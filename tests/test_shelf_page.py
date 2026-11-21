"""ui/agents.html's shelf in a real WKWebView that is never put in a window: finished agents fold, open on a click, refold and leave."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''import Cocoa
import WebKit
// Loads the page as AgentPanels does; on its "ready" post runs argv[2] as an async function body, prints {"result", "posts", "errors"}.
final class Harness: NSObject, WKScriptMessageHandler {
    var posts: [Any] = [], web: WKWebView!
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        if m.name == "errors" { posts.append(["error": m.body]); return }
        posts.append(m.body)
        guard (m.body as? [String: Any])?["action"] as? String == "ready" else { return }
        web.callAsyncJavaScript(CommandLine.arguments[2], arguments: [:], in: nil, in: .page) { r in
            switch r {
            case .success(let x):
                let out = try! JSONSerialization.data(withJSONObject: ["result": x ?? NSNull(), "posts": self.posts])
                print(String(data: out, encoding: .utf8)!); exit(0)
            case .failure(let e): print(e); exit(1)
            }
        }
    }
}
NSApplication.shared.setActivationPolicy(.prohibited)   // no Dock icon, no menu, no window
let h = Harness(), cfg = WKWebViewConfiguration()
cfg.userContentController.add(h, name: "agents"); cfg.userContentController.add(h, name: "errors")
cfg.userContentController.addUserScript(WKUserScript(source: "addEventListener('error',e=>webkit.messageHandlers.errors.postMessage(String(e.message)));addEventListener('unhandledrejection',e=>webkit.messageHandlers.errors.postMessage(String(e.reason)))", injectionTime: .atDocumentStart, forMainFrameOnly: true))
h.web = WKWebView(frame: NSRect(x: 0, y: 0, width: 260, height: 400), configuration: cfg)
h.web.loadHTMLString(try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8), baseURL: nil)
DispatchQueue.main.asyncAfter(deadline: .now() + 50) { print("timeout"); exit(1) }
NSApplication.shared.run()
'''
HEAD = r'''
const settle = () => document.getAnimations().filter(a => a.effect.getTiming().iterations !== Infinity).forEach(a => a.finish());   // no window: WebKit never advances motion, so finish it
const tick = ms => new Promise(r => setTimeout(r, ms)), now = Date.now() / 1000, n = s => document.querySelectorAll(s).length, text = s => document.querySelector(s)?.textContent || '';
const work = {id: 'a'.repeat(32), title: 'Working', status: 'running', step: 'Reading', created: now - 20, started: now - 20};
const done = {id: 'b'.repeat(32), title: 'Finished', status: 'done', created: now - 400, started: now - 400, ended: now - 200, summary: 'Done it.', result: 'Done it.'};
const out = {};
'''
SCRIPT = HEAD + r'''
agents.mode('shelf'); agents.prefs({dismissed: [], stack: 'open'});   // an old saved 'open' is not restored: it is only a peek now
agents.list([work, done]); await tick(50);
out.folded = [n('.chip'), text('.pill')];
document.querySelector('.pill').click(); await tick(500); settle();
const op = s => getComputedStyle(document.querySelector(s)).opacity, x = () => document.querySelector('.chip.s-done .ctl button');
out.opened = [n('.chip'), text('.chip.s-done .step'), op('.chip.s-done .ctl'), op('.chip.s-done'), op('.hide-all')];   // controls wait for the pointer
out.focused = [...document.styleSheets[0].cssRules].some(r => ['.chip:focus-within .ctl', '.tray:focus-within .clear', '.hide-all:focus-visible'].every(s => r.selectorText?.includes(s)) && r.style.opacity === '1');   // a page without a window never has focus, so check WebKit kept the rule
const c = document.querySelector('.chip.s-done').getBoundingClientRect(); agents.pointer([c.x + 5, c.y + 5]); await tick(20); settle();
out.hovered = [op('.chip.s-done .ctl'), op('.hide-all'), x().title];
document.querySelector('.chip.s-done .head').click(); await tick(50); settle();   // first click: it opens in place
out.clicked = [agents.expanded() === done.id, n('.chip')];
document.querySelector('.chip.s-done .head').click(); await tick(50);   // second click: the Agent view
agents.pointer([]); await tick(50); out.left = n('.chip');   // the pointer leaving changes nothing
agents.blur(); await tick(50); settle();   // Esc or a click off the shelf: the peek folds back
out.refolded = [n('.chip'), text('.pill')];
agents.state({...done, status: 'running', step: 'Resuming', started: now}); await tick(50);   // a follow-up: a working chip again
out.followup = [n('.chip'), text('.pill'), document.querySelector('.chip[data-id="' + done.id + '"] .ctl button').title];
agents.state({...done, ended: now, seen: true, seenAt: now}); await tick(50);
document.querySelector('.pill').click(); await tick(500);
document.querySelector('.chip.s-done .ctl button').click(); await tick(50); agents.resume();   // × : off the shelf at once (resume re-renders as the leave motion's end does; no window, no motion events)
out.dismissed = [n('.chip'), text('.pill')];
agents.list([{...done, id: 'c'.repeat(32), ended: now - 3600, seenAt: now - 700}]); await tick(1200);   // only one from long ago: nothing lingers
out.expired = [n('.chip'), text('.pill')];
const d2 = {...done, id: 'd'.repeat(32), title: 'Second'}, d3 = {...done, id: 'e'.repeat(32), title: 'Third', ended: now - 100};
agents.prefs({dismissed: [], stack: ''}); agents.list([work, d2, d3]); await tick(50);
out.tray = [n('.chip'), text('.pill'), op('.clear')];
const p = document.querySelector('.pill').getBoundingClientRect(); agents.pointer([p.x + 5, p.y + 5]); await tick(20); settle();
out.trayHover = op('.clear');
document.querySelector('.clear').click(); await tick(50);   // × all done: working stays, finished leave the shelf
out.cleared = [n('.chip'), n('.tray')];
agents.state({...work, status: 'done', ended: now, summary: 'Also done.'}); await tick(50);   // finishes after the clear: a new done agent
out.after = [n('.chip'), text('.pill')];
agents.state({...d2, status: 'running', started: now}); agents.state({...d2, ended: now + 1}); await tick(50);   // a cleared one followed up finishes again
out.again = text('.pill');
const w2 = {...work, id: 'f'.repeat(32)}, w3 = {...work, id: '1'.repeat(32)}, ok = {...done, id: '2'.repeat(32)}, bad = {...done, id: '3'.repeat(32), status: 'failed', step: '', ended: now - 30};
agents.list([work, ok, bad]); await tick(50);
out.failed = [text('.pill'), [...document.querySelectorAll('.pill canvas')].map(c => c.style.filter)];   // a failure never reads as done: its own red orb
document.querySelector('.hide-all').click(); await tick(50);
const fits = () => { const s = document.querySelector('.pill .orbs+span'), t = document.querySelector('.tray').getBoundingClientRect(); return [t.left >= 0 && t.right <= innerWidth, s.scrollWidth <= s.clientWidth]; };   // inside the shelf; the label not cut
out.minimized = [n('.chip'), text('.pill'), ...fits()];
document.querySelector('.pill').click(); await tick(500); settle(); out.peek = n('.chip');
out.chipOrbs = Object.fromEntries([...document.querySelectorAll('.chip')].map(c => [c.className.match(/s-(\S+)/)[1], c.querySelector('.head canvas').style.filter]));   // unminimized, each chip's orb says its state as the pill's orbs do
const q = document.querySelector('.chip').getBoundingClientRect(); agents.pointer([q.x + 5, q.y + 5]); await tick(50); agents.pointer([]); await tick(50); out.stillPeek = n('.chip');
agents.blur(); await tick(50); settle();
out.unpeeked = [n('.chip'), text('.pill')];   // minimized stays minimized
agents.list([work, w2, w3, ok, bad]); await tick(50);
out.widest = [text('.pill'), fits()[0]];
agents.list([]); await tick(50); agents.list([work]); await tick(50);
out.fresh = [n('.chip'), n('.tray')];   // an empty shelf ends minimized: the next agent shows in full
return out;
'''
LAYERS = HEAD + r'''
agents.mode('shelf');
const box = e => e.getBoundingClientRect(), all = s => [...document.querySelectorAll(s)];
const hit = (a, b) => { const r = box(a), s = box(b); return r.width > 0 && s.width > 0 && r.left < s.right - .5 && s.left < r.right - .5 && r.top < s.bottom - .5 && s.top < r.bottom - .5; };
const clash = () => { settle(); const pairs = [];   // shelf rows, the pill's orbs, the tray's × and pill, each chip's title and ×: none may cover another
  for (const g of [all('#shelf > *'), all('.pill canvas'), all('.tray > *'), ...all('.chip').map(c => [c.querySelector('.copy'), c.querySelector('.ctl button')])])
    g.forEach((a, i) => g.slice(i + 1).forEach(b => { if (hit(a, b)) pairs.push(a.className + ' / ' + b.className); }));
  return pairs; };
const form = {...done, id: '4'.repeat(32), title: 'Fill out form', ended: now - 40, seenAt: now - 40}, bikes = {...work, id: '5'.repeat(32), title: 'Best ebikes research', step: 'Starting…', created: now, started: now};
out.layers = {};
for (const home of ['', 'min']) {   // one agent done and folded, then a new one starts (his shelf was minimized)
  agents.list([]); await tick(50); agents.list([form]); agents.prefs({dismissed: [], stack: home}); await tick(50);
  agents.arrive(bikes.id); agents.state(bikes); await tick(30);
  const slot = agents.slot(bikes.id), started = clash();   // the swim outlasts the glide: it lands where the orb rests
  const orb = box(document.querySelector('.chip[data-id="' + bikes.id + '"] canvas, .pill canvas[data-id="' + bikes.id + '"]')); agents.land(bikes.id); agents.state({...bikes, step: 'Searching the web'}); await tick(50);
  out.layers[home || 'auto'] = {slot, miss: [slot[0] - orb.x - orb.width / 2, slot[1] - orb.y - orb.height / 2], started, running: clash(), pill: text('.pill')};   // the start orb lands on its own orb
}
const helmets = {...bikes, id: '6'.repeat(32), title: 'Best helmets research', created: now - 5, started: now - 5};
agents.list([]); await tick(50); agents.prefs({dismissed: [], stack: ''}); agents.list([bikes, helmets, form]); await tick(50);
out.layers.two = [n('.chip'), clash()];
document.querySelector('.hide-all').click(); await tick(50); out.layers.minimized = [n('.chip'), text('.pill'), clash()];
document.querySelector('.pill').click(); await tick(300); out.layers.peek = [n('.chip'), clash()];
const mid = s => { const r = box(document.querySelector(s)); return [r.x + r.width / 2, r.y + r.height / 2]; };
const look = s => { const e = document.querySelector(s), rest = getComputedStyle(e).backgroundColor, hand = agents.pointer(mid(s)); settle(); return [hand, e.classList.contains('hot'), rest !== getComputedStyle(e).backgroundColor]; };
agents.pointer(mid('.chip .head')); await tick(20); settle();   // on a chip: its × shows
out.hot = {x: look('.chip .ctl button'), min: look('.hide-all')};
agents.prefs({dismissed: [], stack: ''}); agents.list([bikes, form]); await tick(50); const calm = getComputedStyle(document.querySelector('.pill')).backgroundColor; out.hot.clear = look('.clear');
out.hot.pillCalm = calm === getComputedStyle(document.querySelector('.pill')).backgroundColor;   // × lights alone: the pill beside it is another click
out.hot.off = [agents.pointer([3, innerHeight - 3]), n('.hot'), agents.pointer([]), n('.hot')];   // off the controls: arrow, no tint
out.ring = [...document.styleSheets[0].cssRules].some(r => r.selectorText === ':focus-visible' && /outline: 2px solid/.test(r.cssText));   // every control keeps the ring (a var() leaves the longhands empty in CSSOM)
return out;
'''
HOVER = HEAD + r'''
agents.mode('shelf');
const mark = value => webkit.messageHandlers.agents.postMessage({action: 'mark', value}), shelf = document.getElementById('shelf');
const mid = e => { const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; };
const seen = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).opacity === '1' && getComputedStyle(e).pointerEvents !== 'none';
agents.prefs({dismissed: [], stack: ''}); agents.list([work, done]); await tick(50); settle();
const chip = document.querySelector('.chip'), h = shelf.scrollHeight, rest = getComputedStyle(chip).backgroundColor;
mark('hover'); const hand = agents.pointer(mid(chip.querySelector('.head')));   // the native pointer on a chip: a tint and the hand, never a resize
const sum = c => c.match(/[\d.]+/g).slice(0, 3).reduce((a, b) => a + +b, 0);
out.instant = [chip.classList.contains('hover'), sum(getComputedStyle(chip).backgroundColor) < sum(rest), parseFloat(getComputedStyle(chip).transitionDuration) <= .08];   // darker within the one call, no timer or frame
await tick(300); settle();
out.hover = [hand, chip.classList.contains('hover'), rest !== getComputedStyle(chip).backgroundColor, chip.classList.contains('expanded'), shelf.scrollHeight === h];
const tray = document.querySelector('.tray');
for (const [node, kind] of [[chip, 'mouseleave'], [shelf, 'mouseleave'], [tray, 'mouseenter']]) node.dispatchEvent(new MouseEvent(kind));   // WebKit's own enter/leave, stale in a panel that is never key
out.stale = [chip.classList.contains('hover'), tray.classList.contains('hover')];
mark('click'); chip.querySelector('.head').click();   // opens inside this call, before any timer or frame
out.click = [chip.classList.contains('expanded'), shelf.scrollHeight > h]; mark('clicked'); await tick(300); settle(); mark('settled');
chip.querySelector('.head').click(); mark('again');   // the open chip, clicked again: the Agent view
agents.blur(); await tick(300); settle(); await tick(50); mark('blurred');
out.blur = [chip.classList.contains('expanded'), shelf.scrollHeight === h];
mark('expand'); agents.expand(done.id); const open = document.querySelector('.chip[data-id="' + done.id + '"]');   // a finished one folded in the pill: out of it, already open
out.expand = [n('.chip'), agents.expanded() === done.id, !!open?.classList.contains('expanded')]; mark('expanded'); await tick(300); settle(); mark('expandSettled');
agents.blur(); await tick(300); settle(); await tick(50); out.expandBlur = [n('.chip'), text('.pill')];
const many = [1, 2, 3, 4].map(i => ({...work, id: String(i + 6).repeat(32), created: now - i, started: now - i})), dones = [{...done, id: 'c'.repeat(32)}, {...done, id: 'd'.repeat(32)}];
const bad = {...done, id: 'e'.repeat(32), status: 'failed', step: ''};
const orbs = () => [...document.querySelectorAll('.pill canvas')].map(c => [...many, ...dones, bad].find(r => r.id === c.dataset.id)?.status);
agents.prefs({dismissed: [], stack: 'min'}); agents.list([...many, ...dones]); await tick(50);
out.orbs = [n('.chip'), orbs(), text('.pill')];
agents.list([...many, ...dones, bad]); await tick(50);
out.orbsFailed = [orbs(), text('.pill')];
out.states = {};
for (const [name, go] of [['auto', () => {}], ['peek', () => document.querySelector('.pill').click()], ['min', () => document.querySelector('.hide-all').click()]]) {
  agents.prefs({dismissed: [], stack: ''}); agents.list([work, done]); await tick(50); go(); await tick(50); settle();
  agents.pointer(mid(document.querySelector('.chip .head, .pill'))); settle();   // anywhere on the shelf shows every control
  const rows = [...shelf.children], clash = rows.some((a, i) => rows.slice(i + 1).some(b => { const r = a.getBoundingClientRect(), s = b.getBoundingClientRect(); return r.height && s.height && r.bottom > s.top + .5 && s.bottom > r.top + .5; }));
  out.states[name] = {chips: n('.chip'), x: [...document.querySelectorAll('.chip .ctl button')].map(seen), clear: seen(document.querySelector('.clear')), min: seen(document.querySelector('.hide-all')), pill: seen(document.querySelector('.pill')), clash};
}
document.querySelector('.pill').click(); await tick(50); settle();   // peek again: × all done is still there, lights up and clears only the finished one
const clear = document.querySelector('.clear'); out.peekClear = [agents.pointer(mid(clear)), clear.classList.contains('hot')];
mark('clear'); clear.click(); await tick(50); agents.resume(); out.cleared = [n('.chip'), n('.tray')];
return out;
'''

HELD = HEAD + r'''
agents.mode('shelf');
const mid = e => { const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; };
const w2 = {...work, id: '7'.repeat(32), title: 'Second', created: now - 10, started: now - 10};
agents.prefs({dismissed: [], stack: ''}); agents.list([work, w2]); await tick(50); settle();
const at = mid(document.querySelector('.chip[data-id="' + w2.id + '"] .head')); agents.pointer(at); settle();
agents.state({...w2, status: 'done', ended: now, summary: 'Done it.'}); await tick(50); settle();   // it finishes while the pointer is on it
const under = () => document.elementFromPoint(...at)?.closest('.chip')?.dataset.id;
out.held = [n('.chip'), under() === w2.id, agents.expanded() === ''];   // hover never opens it
agents.pointer(at); settle(); out.still = [n('.chip'), under() === w2.id];
agents.pointer([]); for (let i = 0; i < 8 && n('.chip') > 1; i++) await tick(500);
settle(); out.left = [n('.chip'), text('.pill')];   // off the shelf: it folds
agents.list([]); await tick(50);
const ask = [1, 2, 3].map(i => ({...work, id: String(i + 4).repeat(32), title: 'Task ' + i, step: 'Starting…', created: now + i / 100, started: now + i / 100}));
for (const r of ask) { agents.arrive(r.id); agents.state(r); }   // three agents from one ask; native reads each slot once all have their place
const slots = ask.map(r => agents.slot(r.id)); settle();
out.ask = ask.map((r, i) => { const o = mid(document.querySelector('.chip[data-id="' + r.id + '"] .head canvas, .pill canvas')); return Math.hypot(slots[i][0] - o[0], slots[i][1] - o[1]); });
return out;
'''

EXPAND = HEAD + r'''
agents.mode('shelf'); agents.prefs({dismissed: [], stack: 'min'}); agents.list([work, {...done, status: 'running'}]); await tick(50); settle();
out.before = [n('.chip'), text('.pill')];
agents.state({...done, ended: now}); agents.expand(done.id); await tick(50); settle();   // native, on its finish ping
const chip = document.querySelector('.chip[data-id="' + done.id + '"]');
out.after = [!!chip && chip.classList.contains('expanded'), agents.expanded() === done.id, text('.chip.s-done .inside').includes('Done it.')];
agents.state({...work, status: 'needs-you', question: {q: 'ok?'}}); await tick(50);   // a question shows its chip on a minimized shelf too
out.amber = document.querySelector('.chip.s-needs-you .head canvas')?.style.filter;
return out;
'''

AUTOFOLD = HEAD + r'''
const real = [setTimeout.bind(window), clearTimeout.bind(window)], due = new Map(); let clock = 0, seq = 0;   // fake clock for the 4 s fold (and any longer timer); shorter ones stay real
window.setTimeout = (f, ms, ...a) => ms >= 4000 ? (due.set(--seq, [clock + ms, f]), seq) : real[0](f, ms, ...a);
window.clearTimeout = id => id < 0 ? due.delete(id) : real[1](id);
const advance = async ms => { clock += ms; for (const [id, [at, f]] of [...due]) if (at <= clock) { due.delete(id); f(); } await tick(30); settle(); await tick(30); settle(); };
const mid = s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; };
const b = {...done, id: 'c'.repeat(32), title: 'Other'}, look = () => [n('.chip'), agents.expanded() === done.id, document.querySelector('.pill')?.getClientRects().length ? text('.pill') : ''];
const start = async home => { agents.list([]); await tick(30); agents.list([work, {...done, status: 'running'}, {...b, status: 'running'}]); agents.prefs({dismissed: [], stack: home}); await tick(30); settle(); };   // prefs after the list: an empty shelf ends minimized
const finish = async r => { agents.state({...r, ended: Date.now() / 1000}); agents.expand(r.id); await tick(30); settle(); };
agents.mode('shelf');
await start('min'); await finish(done); out.popped = look();
await advance(3900); out.early = look();
await advance(100); out.folded = look();
await start(''); await finish(done); await advance(4000); out.auto = look();
await start('min'); await finish(done); agents.pointer(mid('.chip.expanded .head')); await advance(20000); out.held = look();
agents.pointer([]); await advance(3900); out.leftEarly = look(); await advance(100); out.leftFolded = look();
await start('min'); await finish(done); agents.pointer(mid('.chip.expanded .head')); document.querySelector('.chip.expanded .head').click(); agents.pointer([]); await advance(20000); out.clicked = look();
agents.blur(); await tick(30); settle(); await tick(30); out.clickedBlur = look();
await start('min'); await finish(b); await advance(2000); await finish(done); out.twice = [...look(), due.size]; await advance(2000); out.twiceEarly = look(); await advance(2000); out.twiceFolded = look();
const fits = [], s = () => document.querySelector('.pill .orbs+span');
for (const home of ['min', '']) {
  for (let w = 0; w <= 9; w++) for (let q = 0; w + q <= 9; q++) for (let f = 0; w + q + f <= 9; f++) for (let d = 0; w + q + f + d <= 9; d++) {
    if (!(w + q + f + d)) continue; let k = 0; const make = (status, count) => Array.from({length: count}, () => { k++; return {...(status === 'done' || status === 'failed' ? done : work), id: k.toString(16).padStart(32, '0'), status, ended: now - k, created: now - k, started: now - k, ...(status === 'needs-you' ? {question: {q: 'ok?'}} : {})}; });
    agents.list([...make('running', w), ...make('needs-you', q), ...make('failed', f), ...make('done', d)]); agents.prefs({dismissed: [], stack: home});
    const p = s(); if (p && p.getClientRects().length && p.scrollWidth > p.clientWidth) fits.push([home, w, q, f, d, p.textContent]); } }
out.fits = fits;
agents.list([work, {...done, id: '2'.repeat(32)}, {...done, id: '3'.repeat(32), status: 'failed'}]); agents.prefs({dismissed: [], stack: 'min'});
out.aria = [text('.pill'), document.querySelector('.pill').getAttribute('aria-label')];
return out;
'''

STARTFOLD = AUTOFOLD.split('const b =')[0] + r'''
const pill = () => document.querySelector('.pill')?.getClientRects().length ? text('.pill') : '', look = () => [n('.chip'), pill()];
const begin = async (ids, more = {}) => { const ask = ids.map(i => ({...work, id: String(i).repeat(32), title: 'Task ' + i, step: 'Starting…', created: now + i / 100, started: now + i / 100, ...more}));
  for (const r of ask) { agents.arrive(r.id); agents.state(r); } settle(); const slots = ask.map(r => agents.slot(r.id));   // native: arrive + state per agent, then reads each slot
  const miss = ask.map((r, i) => { const o = mid('.chip[data-id="' + r.id + '"] .head canvas'); return Math.hypot(slots[i][0] - o[0], slots[i][1] - o[1]) < 1; });
  for (const r of ask) agents.land(r.id); await tick(30); settle(); return miss; };
const go = async (ids, home, linger) => { agents.list([]); await tick(30); if (linger) { agents.list([linger]); agents.prefs({dismissed: [], stack: home}); await tick(30); } return begin(ids); };   // prefs after the list: an empty shelf ends minimized
agents.mode('shelf');
out.miss = await go([4, 5, 6], ''); out.started = look();
await advance(3900); out.early = look(); await advance(100); out.folded = look();
await go([4, 5, 6], ''); agents.pointer(mid('.chip .head')); await advance(20000); out.held = look();
agents.pointer([]); await advance(3900); out.leftEarly = look(); await advance(100); out.leftFolded = look();
await go([4, 5, 6], ''); document.querySelector('.chip .head').click(); await advance(20000); out.clicked = look();
agents.blur(); await tick(30); settle(); await tick(30); out.clickedBlur = look();
const linger = {...done, ended: now - 30};
out.minMiss = await go([4, 5, 6], 'min', linger); out.min = look();
await advance(4000); out.minFolded = [...look(), [...document.querySelectorAll('.pill canvas')].map(c => c.style.filter.startsWith('hue') ? 'working' : 'done')];
await go([4, 5], ''); await advance(2000); await begin([6]); out.later = look();   // one more starts 2 s later: one timer, from the last start
await advance(2000); out.laterEarly = look(); await advance(2000); out.laterFolded = look();
await go([4, 5, 6], ''); await advance(2000); agents.state({...work, id: '5'.repeat(32), title: 'Task 5', status: 'done', ended: Date.now() / 1000, summary: 'Done it.'}); agents.expand('5'.repeat(32)); await tick(30); settle();   // one finishes 2 s in: native's state, then its pop
out.finish = [...look(), agents.expanded() === '5'.repeat(32)]; await advance(3900); out.finishEarly = look(); await advance(100); out.finishFolded = [...look(), agents.expanded()];
await go([4, 5], ''); await advance(2000); await begin([6], {status: 'queued', step: 'Queued'}); out.queued = look();   // a queued one arrives 2 s later
await advance(3900); out.queuedEarly = look(); await advance(100); out.queuedFolded = look();
agents.state({...work, id: '4'.repeat(32), title: 'Task 4', step: 'Reading', created: now + .04, started: now + .04}); await tick(30); out.queuedLive = look();   // live updates keep them folded
return out;
'''


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class ShelfPageTests(unittest.TestCase):
    def run_page(self, script):
        with tempfile.TemporaryDirectory() as tmp:
            page, src, binary = Path(tmp) / 'agents.html', Path(tmp) / 'page.swift', Path(tmp) / 'page'
            page.write_text((ROOT / 'ui/agents.html').read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/', (ROOT / 'ui/orbs.js').read_text()))
            src.write_text(HARNESS)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(page), script], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        got = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual([p for p in got['posts'] if 'error' in p], [])
        return got['posts'], got['result']

    def test_shelf_layers_never_overlap_and_controls_answer_the_pointer(self):
        _, out = self.run_page(LAYERS)
        for home in ('auto', 'min'):
            got = out['layers'][home]
            self.assertEqual([got['started'], got['running']], [[], []], home)
            self.assertTrue(all(abs(d) < 1 for d in got['miss']), got)   # the start orb lands on its own orb, not a fixed corner
        self.assertEqual(out['layers']['auto']['slot'], [24, 50])   # under the minimize row: the old fixed target (24, 26) missed by a row
        self.assertEqual(out['layers']['auto']['pill'], '✓ 1 done')
        self.assertEqual(out['layers']['min']['pill'], '✓ 1 done')   # his minimized shelf: the new agent's chip shows over the pill until the 4 s fold
        self.assertEqual(out['layers']['two'], [2, []])
        self.assertEqual(out['layers']['minimized'], [0, '2 agents · 1 done', []])
        self.assertEqual(out['layers']['peek'], [3, []])
        for name in ('x', 'min', 'clear'):
            self.assertEqual(out['hot'][name], [True, True, True], name)   # pointing hand, .hot, a visible tint
        self.assertEqual(out['hot']['off'], [False, 0, False, 0])
        self.assertTrue(out['hot']['pillCalm'])
        self.assertTrue(out['ring'])

    def test_click_opens_in_place_then_the_view_and_every_control_shows_in_every_state(self):
        posts, out = self.run_page(HOVER)
        marks = {p['value']: i for i, p in enumerate(posts) if p.get('action') == 'mark'}
        between = lambda a, b, kind='size': [p for p in posts[marks[a] + 1:marks[b]] if p.get('action') == kind]
        self.assertEqual(out['instant'], [True, True, True])   # Oct 21: the tint was "laggy sometimes"
        self.assertEqual(out['hover'], [True, True, True, False, True])   # hand, tint; was an expand with no delay (Oct 21: laggy)
        self.assertEqual(out['stale'], [True, False])   # only the native pointer moves the tint
        self.assertEqual(between('hover', 'click'), [])
        self.assertEqual(out['click'], [True, True])
        self.assertEqual(len(between('click', 'clicked')), 1)   # one panel resize, posted in the same call
        self.assertEqual(between('clicked', 'settled'), [])   # and no second one while it settles
        self.assertEqual([p.get('id') for p in between('settled', 'again', 'view')], ['a' * 32])
        self.assertEqual(out['blur'], [False, True])
        self.assertEqual(len(between('again', 'blurred')), 1)
        self.assertEqual(out['expand'], [2, True, True])   # agents.expand(id): what a finish calls
        self.assertEqual(len(between('expand', 'expanded')), 1); self.assertEqual(between('expanded', 'expandSettled'), [])
        self.assertEqual(out['expandBlur'], [1, '✓ 1 done'])
        self.assertEqual(out['orbs'], [0, ['running', 'done'], '4 agents · 2 done'])   # one orb per state, never per agent
        self.assertEqual(out['orbsFailed'], [['running', 'done', 'failed'], '4 · 1 failed · 2 done'])
        self.assertEqual(out['states']['auto'], {'chips': 1, 'x': [True], 'clear': True, 'min': True, 'pill': True, 'clash': False})
        self.assertEqual(out['states']['peek'], {'chips': 2, 'x': [True, True], 'clear': True, 'min': True, 'pill': False, 'clash': False})
        self.assertEqual(out['states']['min'], {'chips': 0, 'x': [], 'clear': True, 'min': False, 'pill': True, 'clash': False})
        self.assertEqual(out['peekClear'], [True, True])
        self.assertEqual(out['cleared'], [1, 0])
        cleared = [p.get('id') for p in posts[marks['clear']:] if p.get('action') == 'dismiss']
        self.assertEqual(cleared, ['b' * 32])

    def test_a_finish_under_the_pointer_waits_and_each_agent_of_one_ask_lands_on_its_orb(self):
        _, out = self.run_page(HELD)
        self.assertEqual(out['held'], [2, True, True])   # was: it folded away and the other chip slid under the pointer
        self.assertEqual(out['still'], [2, True])
        self.assertEqual(out['left'], [1, '✓ 1 done'])
        self.assertTrue(all(d < 1 for d in out['ask']), out['ask'])   # each slot is where its orb (or the pill's orb for its state) rests, not mid-glide

    def test_a_finish_opens_its_own_chip_even_on_a_minimized_shelf(self):
        _, out = self.run_page(EXPAND)
        self.assertEqual(out['before'], [0, '2 agents'])
        self.assertEqual(out['after'], [True, True, True])
        self.assertEqual(out['amber'], 'sepia(1) saturate(6)')

    def test_a_finish_pops_open_then_folds_back_after_four_seconds_unless_held(self):
        _, out = self.run_page(AUTOFOLD)
        self.assertEqual([out['popped'], out['early']], [[1, True, '2 more'], [1, True, '2 more']])   # minimized, a finish: only its chip comes up, open, over the pill
        self.assertEqual(out['folded'], [0, False, '2 agents · 1 done'])   # 4 s: minimized again, it sits in the pill
        self.assertEqual(out['auto'], [2, False, '✓ 1 done'])   # auto stays auto
        self.assertEqual([out['held'], out['leftEarly'], out['leftFolded']], [[1, True, '2 more'], [1, True, '2 more'], [0, False, '2 agents · 1 done']])   # the pointer on the shelf holds it; off it, the same 4 s
        self.assertEqual([out['clicked'], out['clickedBlur']], [[1, True, '2 more'], [0, False, '2 agents · 1 done']])   # clicked: it stays until Esc or a click off
        self.assertEqual([out['twice'], out['twiceEarly'], out['twiceFolded']], [[1, True, '1 more · 1 done', 1], [1, True, '1 more · 1 done'], [0, False, '1 agent · 2 done']])   # one timer, the newest shown
        self.assertEqual(out['fits'], [])   # 1-9 agents, every mix of working, needs you, failed and done, minimized or auto: the label never cuts off
        self.assertEqual(out['aria'], ['1 · 1 failed · 1 done', '1 agent · 1 failed · 1 done. Show agents'])   # VoiceOver keeps the words

    def test_agents_started_together_all_show_then_fold_after_four_seconds_unless_held(self):
        _, out = self.run_page(STARTFOLD)
        self.assertEqual([out['miss'], out['minMiss']], [[True] * 3, [True] * 3])   # each start orb lands on its own chip
        self.assertEqual([out['started'], out['early'], out['folded']], [[3, ''], [3, ''], [0, '3 agents']])   # Oct 21: the third folded the older two at once; then the fold left the newest open
        self.assertEqual([out['held'], out['leftEarly'], out['leftFolded']], [[3, ''], [3, ''], [0, '3 agents']])   # the pointer on the shelf holds them; off it, the same 4 s
        self.assertEqual([out['clicked'], out['clickedBlur']], [[3, ''], [0, '3 agents']])   # clicked: they stay until Esc or a click off
        self.assertEqual([out['min'], out['minFolded']], [[3, '✓ 1 done'], [0, '3 agents · 1 done', ['working', 'done']]])   # minimized stays minimized, its per-state orbs
        self.assertEqual([out['later'], out['laterEarly'], out['laterFolded']], [[3, ''], [3, ''], [0, '3 agents']])
        self.assertEqual([out['finish'], out['finishEarly'], out['finishFolded']], [[3, '', True], [3, ''], [0, '2 agents · 1 done', '']])   # a finish 2 s in: one timer, all fold 4 s after it
        self.assertEqual([out['queued'], out['queuedEarly'], out['queuedFolded'], out['queuedLive']], [[3, ''], [3, ''], [0, '3 agents'], [0, '3 agents']])

    def test_finished_agents_on_the_real_webkit_shelf(self):
        posts, out = self.run_page(SCRIPT)
        self.assertEqual(out['folded'], [1, '✓ 1 done'])
        self.assertEqual(out['opened'][:2], [2, 'Done · 3m ago'])
        self.assertEqual([out['opened'][2], out['opened'][4]], ['0', '0'])   # × and minimize-all wait for the pointer
        self.assertAlmostEqual(float(out['opened'][3]), .82, places=2)
        self.assertTrue(out['focused'])   # keyboard focus reveals the controls too
        self.assertEqual(out['hovered'], ['1', '1', 'Hide (stays in Agents)'])
        self.assertEqual([out['clicked'], out['left']], [[True, 2], 2])
        self.assertEqual(out['refolded'], [1, '✓ 1 done'])
        self.assertEqual(out['followup'], [2, '', 'Hide (keeps working)'])   # the tooltip follows its status
        self.assertEqual(out['dismissed'], [1, ''])
        self.assertEqual(out['expired'], [0, ''])
        self.assertEqual(out['tray'], [1, '✓ 2 done', '0'])
        self.assertEqual(out['trayHover'], '1')
        self.assertEqual(out['cleared'], [1, 0])
        self.assertEqual(out['after'], [0, '✓ 1 done'])
        self.assertEqual(out['again'], '✓ 2 done')
        self.assertEqual(out['failed'], ['1 failed · 1 done', ['sepia(1) saturate(4) hue-rotate(95deg)', 'sepia(1) saturate(8) hue-rotate(-35deg)']])   # green done orb, red failed orb
        self.assertEqual(out['minimized'], [0, '1 · 1 failed · 1 done', True, True])
        self.assertEqual(out['peek'], 3)
        self.assertEqual([out['chipOrbs']['done'], out['chipOrbs']['failed']], out['failed'][1])   # green done, red failed: the pill's colors
        self.assertTrue(out['chipOrbs']['running'].startswith('hue-rotate('))   # working keeps its own hue
        self.assertEqual([out['stillPeek'], out['unpeeked']], [3, [0, '1 · 1 failed · 1 done']])
        self.assertEqual(out['widest'], ['3 · 1 failed · 1 done', True])
        self.assertEqual(out['fresh'], [1, 0])
        actions = [(p.get('action'), p.get('value', p.get('id'))) for p in posts if isinstance(p, dict)]
        self.assertEqual([v for a, v in actions if a == 'stack'][-4:], ['min', 'min', 'min', ''])   # a peek keeps the saved choice; an empty shelf clears it
        self.assertIn(('view', 'b' * 32), actions); self.assertNotIn(('show', 'b' * 32), actions)   # a finished chip opens in place, then the Agent view; no Atticus box
        self.assertIn(('dismiss', 'b' * 32), actions)
        self.assertIn(('dismiss', 'd' * 32), actions); self.assertIn(('dismiss', 'e' * 32), actions); self.assertNotIn(('dismiss', 'a' * 32), actions)
        self.assertNotIn(('stack', 'open'), actions)
        lingering = [v for a, v in actions if a == 'lingering']
        # empty, pill, follow-up runs, done again, ×, two done, × all done, a finish after the clear, the shelf emptied
        self.assertEqual(lingering, [False, True, False, True, False, True, False, True, False])


if __name__ == '__main__':
    unittest.main()
