"""Pure shared title formatter and both card callers; no browser or app is launched."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def title_script():
    source = (ROOT / 'ui/orbs.js').read_text()
    return source[source.index('function linkTitle('):source.index('export { linkTitle };')] + '\nconst E = {linkTitle};\n'


class LinkTitleTests(unittest.TestCase):
    def test_plip_title_cleanup(self):
        cases = [
            ['  Café\u0301\u0302  work  | Example ', 'https://example.com/work', 'Café work'],
            ['— Portfolio — Example.com |', 'https://example.com/work', 'Portfolio'],
            ['Example', 'https://example.com/garden-design_2026.html', 'Garden design 2026'],
            [' – Example ', 'https://example.com/watch', 'Example'],
            ['Example', 'https://example.com/123-456', 'Example'],
            ['A title | Other', 'https://example.com/', 'A title | Other'],
            ['', 'https://www.example.com/page', 'www.example.com'],
            [None, 'not a URL', 'not a URL'],
            ['東京の庭 – Example', 'https://example.com/', '東京の庭'],
            ['x' * 150, 'https://example.com', 'x' * 120],
        ]
        script = title_script() + 'const cases = ' + json.dumps(cases) + ''';
for (const [title, url, want] of cases) {
  const got = linkTitle(title, url);
  if (got !== want) throw Error(JSON.stringify({title, got, want}));
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_renderers_use_clean_titles_without_changing_presence_or_urls(self):
        overlay = (ROOT / 'ui/ui.html').read_text()
        agents = (ROOT / 'ui/agents.html').read_text()
        code = overlay[overlay.index('  const agentAnswer='):overlay.index('  const keyButton=')]
        code += agents[agents.index('const host='):agents.index('\n', agents.index('const host='))] + '\n'
        code += agents[agents.index('const KINDS='):agents.index('function madeCards')]
        code += agents[agents.index('const answer=r=>'):agents.index('\n', agents.index('const answer=r=>'))]
        script = title_script() + code + '''
const url = 'https://example.com/garden-design', row = {result: url, made: [{url, title:'Example'}]};
for (const make of [things, agentMade]) {
  const cards = make(row);
  if (cards.length !== 1 || cards[0].title !== 'Garden design' || cards[0].url !== url) throw Error(JSON.stringify(cards));
  if (make({result:url, made:[{url,title:''}]}).length) throw Error('cited source became a made card');
  if (make({made:[{url:'/tmp/report.txt',title:'Report | Example'}]})[0].title !== 'Report | Example') throw Error('file title changed');
}
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        chips = agents[agents.index('function sourceChips('):agents.index('const KINDS=')]
        self.assertIn('E.linkTitle(s.title,s.url)', chips)
