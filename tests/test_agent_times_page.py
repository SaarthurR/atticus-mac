"""ui/agents.html's Agent view in a real WKWebView that is never put in a window: each agent shows when it started, on a fixed clock."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_shelf_page import HARNESS, ROOT

SCRIPT = r'''
const tick = ms => new Promise(r => setTimeout(r, ms)), Real = Date, at = (...a) => new Real(...a).getTime() / 1000;
let T = new Real(2026, 9, 21, 20, 59).getTime();   // Oct 21, 8:59 PM local
globalThis.Date = class extends Real { constructor(...a) { super(...(a.length ? a : [T])); } static now() { return T; } };
const row = (id, title, started) => ({id: id.repeat(32), title, status: 'done', created: started - 5, started, ended: started + 90, summary: 'ok', result: 'ok'});
const rows = [row('a', 'Today', at(2026, 9, 21, 20, 28)), row('b', 'A long title that runs well past the narrow sidebar', at(2026, 9, 20, 20, 28)),
  row('c', 'Older', at(2026, 9, 19, 20, 28)), {id: 'd'.repeat(32), title: 'Queued', status: 'queued', created: at(2026, 9, 21, 8, 5)}];
const clock = new Intl.DateTimeFormat(undefined, {hour: 'numeric', minute: '2-digit'}), day = new Intl.DateTimeFormat(undefined, {month: 'short', day: 'numeric'}), dated = d => day.format(d) + ', ' + clock.format(d);
const items = () => [...document.querySelectorAll('#list .item')], look = () => Object.fromEntries(items().map(b => [b.querySelector('b').textContent.split(' ')[0], b.querySelector('.started').textContent]));
const heights = () => [...new Set(items().map(b => b.offsetHeight))], header = () => document.querySelector('#status .started').textContent;
agents.mode('view'); agents.list(rows); await tick(50);
const out = {locale: new Intl.DateTimeFormat().resolvedOptions().locale, sidebar: document.querySelector('aside').offsetWidth};
out.rows = look(); out.heights = heights();
out.expected = {Today: clock.format(new Real(2026, 9, 21, 20, 28)), A: 'Yesterday ' + clock.format(new Real(2026, 9, 20, 20, 28)), Older: dated(new Real(2026, 9, 19, 20, 28)), Queued: clock.format(new Real(2026, 9, 21, 8, 5))};
out.fits = items().every(b => { const s = b.querySelector('.started'); return s.scrollWidth <= s.clientWidth; });
const long = items().find(b => b.textContent.startsWith('A long')).querySelector('b');
out.ellipsis = long.scrollWidth > long.clientWidth && getComputedStyle(long).textOverflow === 'ellipsis';
agents.select(rows[1].id); await tick(50); out.header = header();
agents.select(rows[2].id); await tick(50); out.switched = header();   // another done agent: its own start, not the last one's
T = new Real(2026, 9, 22, 0, 10).getTime(); await tick(1100);   // past midnight: the 1 s tick rolls the words over in place
out.rolled = look(); out.rolledHeights = heights(); out.rolledHeader = header();
out.rolledExpected = {Today: 'Yesterday ' + clock.format(new Real(2026, 9, 21, 20, 28)), A: dated(new Real(2026, 9, 20, 20, 28))};
return out;
'''


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class AgentTimesPageTests(unittest.TestCase):
    def test_each_agent_shows_its_start_today_yesterday_or_older(self):
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
        self.assertEqual(out['sidebar'], 172)   # the narrow layout: the tightest row
        self.assertEqual(out['rows'], out['expected'])
        if out['locale'] == 'en-US':
            self.assertEqual(out['rows'], {'Today': '8:28 PM', 'A': 'Yesterday 8:28 PM', 'Older': 'Oct 19, 8:28 PM', 'Queued': '8:05 AM'})
            self.assertEqual([out['header'], out['switched'], out['rolledHeader']], ['· Started Yesterday 8:28 PM', '· Started Oct 19, 8:28 PM', '· Started Oct 19, 8:28 PM'])
        self.assertTrue(out['fits'])   # the start time is never cut off
        self.assertTrue(out['ellipsis'])   # a long title ends in … instead
        self.assertEqual(len(out['heights']), 1)   # every row the same height
        self.assertEqual(out['rolledHeights'], out['heights'])   # no jump when the words change
        self.assertEqual({k: out['rolled'][k] for k in ('Today', 'A')}, out['rolledExpected'])


if __name__ == '__main__':
    unittest.main()
