"""Local graph protocol and real WebKit rendering; all execution stays in Tart."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import atticus
from tests import run_swift
from tests.test_shelf_page import HARNESS, ROOT

PARABOLA = {'type': 'function', 'title': 'Parabola', 'x': [-4, 4], 'y': [-2, 10],
            'curves': [{'fn': 'x^2', 'label': 'y = x²'}], 'points': [{'x': 0, 'y': 0, 'label': 'Vertex (0, 0)'}]}
CASES = {
    'parabola': PARABOLA,
    'two-curves': {'title': 'Two curves', 'fn': ['x^2', '2x+1'], 'points': [[0, 0, 'Vertex (0, 0)']]},   # the prompt's short form
    'bar': {'type': 'bar', 'title': 'Sales by quarter', 'series': [{'label': 'Sales', 'data': [[1, 12], [2, 8], [3, 17], [4, 14]]}]},
    'bad-spec': {'type': 'function', 'x': [-4, 4], 'y': [-2, 10], 'curves': [{'fn': 'window.alert(1)'}]},
}

@unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'VM only')
class ChartsTests(unittest.TestCase):
    def test_stream_reserves_graph_before_json_and_keeps_fenced_text_inert(self):
        self.assertEqual(atticus.streamed_answer('```graph\n'), '```graph')
        self.assertEqual(atticus.streamed_answer('Here:\n```graph\n'), 'Here:\n```graph')
        text = '```graph\n{"title":"[agent do not run]"}\n```'
        self.assertEqual(atticus.streamed_answer(text), text)
        prompt = atticus.system_prompt(atticus.NEVER)
        self.assertEqual(prompt.count('Graphs: ```graph'), 1)

    def test_native_escape_shrinks_graph_before_closing_box(self):
        source = (ROOT / 'Atticus.swift').read_text()
        escape = source[source.index('    func escape() {'):source.index('    func hush() {')]
        self.assertIn('} else if panel.isVisible {\n            shrinkGraphOrClose()\n        }\n    }', escape)
        start = source.index('    func shrinkGraphOrClose()'); method = source[start:source.index('\n    }\n', start) + 7]   # the method alone
        run_swift(self, '''import Foundation
final class Web {
    var shrunk: Any? = true
    var delayed = false, pending: ((Any?, Error?) -> Void)?
    func evaluateJavaScript(_ script: String, completionHandler: @escaping (Any?, Error?) -> Void) {
        precondition(script == "ui.graphShrink()")
        if delayed { pending = completionHandler } else { completionHandler(shrunk, nil) }
    }
}
final class App { let web = Web(); var closes = 0, gen = 0; func close(clear: Bool) { precondition(!clear); closes += 1 }
''' + method + '''}
let app = App(); app.shrinkGraphOrClose(); precondition(app.closes == 0)
app.web.shrunk = false; app.shrinkGraphOrClose(); precondition(app.closes == 1)
app.web.shrunk = nil; app.shrinkGraphOrClose(); precondition(app.closes == 2)
app.web.delayed = true; app.shrinkGraphOrClose()
app.gen += 1   // a new ask reopens the box before WebKit returns the old Escape result
app.web.pending?(false, nil)
precondition(app.closes == 2, "An old Escape closed a new ask")
app.shrinkGraphOrClose(); app.web.pending?(false, nil)
precondition(app.closes == 3, "The current Escape must still close")
''')

    def test_graphs_in_real_answer_box_and_shots(self):
        harness = HARNESS.replace('cfg.userContentController.add(h, name: "agents")',
            'cfg.userContentController.add(h, name: "c"); cfg.userContentController.add(h, name: "h"); cfg.userContentController.add(h, name: "snapshot")')
        harness = harness.replace('?["action"] as? String == "ready"', '?["ready"] != nil')
        harness = harness.replace('width: 260, height: 400', 'width: 460, height: 760')
        harness = harness.replace('        posts.append(m.body)', r'''
        if m.name == "snapshot", let name = m.body as? String {
            let cfg = WKSnapshotConfiguration(); cfg.snapshotWidth = 920
            web.takeSnapshot(with: cfg) { image, error in
                guard let image, let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff),
                    let png = bitmap.representation(using: .png, properties: [:]) else { print("snapshot failed: \(String(describing: error))"); exit(1) }
                print("PNG \(name).png \(png.base64EncodedString())")
                self.web.evaluateJavaScript("window.snapshotReady()", completionHandler: nil)
            }; return
        }
        posts.append(m.body)''')
        harness = harness.replace('h.web.loadHTMLString', '''
let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 460, height: 760), styleMask: [.borderless], backing: .buffered, defer: false)
window.contentView = h.web; window.orderFrontRegardless()
h.web.loadHTMLString''')
        script = r'''
const {graph, graphFunction, markdown} = window.charts;
const check = (ok, message) => {if (!ok) throw Error(message);};
const settle = () => document.getAnimations().filter(a => a.effect.getTiming().iterations !== Infinity).forEach(a => a.finish());
const tick = () => new Promise(r => setTimeout(r, 80));
check(graphFunction('-x^2')(3) === -9 && graphFunction('2^3^2')(0) === 512, 'power precedence');
check(graphFunction('sin(pi/2)+sqrt(4)+abs(-3)+log(e)')(0) === 7, 'math functions');
check(graphFunction('2x+1')(3) === 7 && graphFunction('y = 3(x-1)')(2) === 3 && graphFunction('2sin(0)+x')(1) === 1, 'implicit multiply');
const taught = graph('{"fn":["x^2-4"],"points":[[0,-4,"vertex"]]}');
check(taught.classList.contains('graph') && taught.textContent.includes('vertex') && taught.querySelector('svg').textContent.includes('-4'), 'prompt example plots');
check(graph('{"bar":[[1,5],[2,3]]}').querySelectorAll('rect').length === 2, 'prompt bar example plots');
for (const bad of ['{"fn":["x;fetch(1)"]}', '{"fn":"x","points":[[0]]}', '{"bar":[[1,"a"]]}', '{"fn":["1/0"]}']) check(graph(bad).tagName === 'PRE', 'bad short form is text: '+bad);
const cases = CASES;
check(graph(JSON.stringify({...cases.parabola,curves:[{fn:'x'+'+0'.repeat(40)}]})).classList.contains('graph'), 'long expression has a bounded default legend');
for (const spec of [null, {}, {...cases.parabola, x:[2,2]}, {...cases.parabola, curves:[{fn:'x;fetch("secret")'}]},
    {...cases.parabola, curves:[{fn:'constructor(1)'}]}, {...cases.parabola, curves:[{fn:'('.repeat(80)+'x'+')'.repeat(80)}]},
    {...cases.parabola, points:[{x:0,y:0,label:'x'.repeat(61)}]}, {type:'line',series:[{data:[[0,'bad']]}]}]) {
    check(graph(JSON.stringify(spec)).tagName === 'PRE', 'invalid spec must be literal');
}
for (const tiny of [{fn:'x', x:[1e9 - 2 ** -22, 1e9]}, {line:[[1e9 - 2 ** -22, 1], [1e9, 2]]}])   // a step under half an ulp never advances
    { const g = graph(JSON.stringify(tiny)); check(g.classList.contains('graph') && g.querySelectorAll('svg > text').length <= 24, 'ticks bounded on a sub-ulp range'); }
check(graph('not JSON <img src=x onerror=alert(1)>').textContent.includes('<img'), 'bad input preserved');
const labelClear = node => {   // a marked point's label never sits on a curve
    const b = [...node.querySelectorAll('svg text')].find(t => t.textContent.startsWith('Vertex')).getBBox();
    return [...node.querySelectorAll('svg svg path')].every(p => { for (let s = 0, n = p.getTotalLength(); s <= n; s++) { const q = p.getPointAtLength(s); if (q.x >= b.x && q.x <= b.x + b.width && q.y >= b.y && q.y <= b.y + b.height) return false; } return true; });
};
check(!graph(JSON.stringify({...cases.parabola,title:'<img src=x onerror=alert(1)>'})).querySelector('img'), 'markup inert');
for (const type of ['line','scatter','bar']) {
    const g = graph(JSON.stringify({type,series:[{data:[[0,-2],[1,4],[2,1]]}]}));
    check(g.classList.contains('graph') && !/NaN|Infinity/.test(g.innerHTML), type+' plots');
}
ui.listen(); ui.words('Graph fixture'); ui.think();
ui.line('… ```graph\n');
settle();
const reserved = document.querySelector('.graph').offsetHeight;
check(reserved === 270 && document.querySelector('.graph.pending'), 'fence-open reservation: '+reserved);
const source = '```graph\n'+JSON.stringify(cases.parabola)+'\n```';
for(let n=0;n<source.length;n++) ui.line('… '+source.slice(0,n+1));
ui.line('… '+source+'\nMore wor');
check(!document.querySelector('.a').textContent.includes('wor'), 'a last word still arriving waits after a graph');
ui.line('… '+source+'\nMore words '); settle(); await tick();
let g=document.querySelector('.graph');
check(!g.classList.contains('pending') && g.offsetHeight === reserved, 'stream height stable');
check(g.querySelector('svg path[stroke="#368de8"]').getAttribute('d').startsWith('M'), 'curve path');
const point = g.querySelector('circle').getBoundingClientRect();
ui.pointer([point.x+point.width/2,point.y+point.height/2]);
check(!g.querySelector('.graph-tip').hidden && g.querySelector('.graph-tip').textContent.includes('Vertex'), 'native hover');
ui.pointer([]); check(g.querySelector('.graph-tip').hidden, 'hover leaves');
const rect=g.getBoundingClientRect(); ui.tap([rect.x+10,rect.y+10]);
g=document.querySelector('.graph');
check(g.classList.contains('expanded') && g.querySelector('svg').viewBox.baseVal.height === 360, 'native tap expands actual plot');
ui.line('… '+source+'\nMore words follow ');
check(document.querySelector('.graph') === g, 'stream preserves interactive graph');
ui.line('✓ '+source+'\nMore words follow.');
check(document.querySelector('.graph') === g, 'final preserves expanded graph');
check(ui.graphShrink() && !document.querySelector('.graph.expanded') && !ui.graphShrink(), 'native Escape bridge');
document.querySelector('.graph').click();
document.querySelector('.graph').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
check(!document.querySelector('.graph.expanded'), 'keyboard Escape');
ui.agentDone({id:'c'.repeat(32),status:'done',title:'Graph answer',result:source});
const card=document.querySelector('.agent-card'), cardGraph=card.querySelector('.graph'); let opened=0;
card.querySelector('.go').onclick=()=>opened++;
cardGraph.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
check(!opened && card.querySelector('.graph.expanded'), 'graph Enter does not open the agent default'); card.remove();
ui.listen(); ui.words('Malformed'); ui.think(); ui.line('✓ ```graph\n{bad');
check(!document.querySelector('.turn:last-child .graph') && document.querySelector('.turn:last-child pre').textContent === '{bad', 'unclosed final shows text');
ui.listen(); ui.words('Mixed'); ui.think(); ui.line('✓ Area $x^2$ here:\n```graph\n{"fn":"x"}\n```\n```\n[agent not a tag]\n```');
check(document.querySelector('.turn:last-child math') && document.querySelector('.turn:last-child .graph svg') && document.querySelector('.turn:last-child pre').textContent === '[agent not a tag]', 'math, graph and code render together');
for(const theme of ['dark','light']) for(const [name,spec] of Object.entries(cases)) {
    ui.listen(); ui.words('Draw this graph'); ui.think(); ui.line('✓ ```graph\n'+JSON.stringify(spec)+'\n```'); ui.finished();
    document.documentElement.style.colorScheme=theme;
    document.body.style.background=theme==='dark'?'#242427':'#fafafa'; document.body.style.color=theme==='dark'?'#f5f5f7':'#1d1d1f';
    document.querySelectorAll('.turn:not(:last-child)').forEach(n=>n.remove());
    settle(); await tick();
    const answer=document.querySelector('.a'), node=answer.querySelector(name==='bad-spec'?'pre':'.graph');
    check(!!node, name+' rendered');
    check(node.getBoundingClientRect().right <= 460, name+' fits');
    if(name==='bad-spec') check(!answer.querySelector('svg'), 'bad spec no box');
    if(name==='parabola'||name==='two-curves') check(labelClear(node), name+' label off the curves');
    if(name==='bar') {
        const bar=node.querySelectorAll('rect')[2].getBoundingClientRect();
        ui.pointer([bar.x+bar.width/2,bar.bottom-3]);
        check(node.querySelector('.graph-tip').textContent === 'Sales: (3, 17)', 'hover inside tall bar'); ui.pointer([]);
    }
    await new Promise(resolve => {window.snapshotReady=resolve;webkit.messageHandlers.snapshot.postMessage('charts-'+name+'-'+theme);});
    if(name==='parabola') {
        node.click(); settle(); await tick();
        check(labelClear(answer.querySelector('.graph')), 'expanded label off the curve');
        await new Promise(resolve => {window.snapshotReady=resolve;webkit.messageHandlers.snapshot.postMessage('charts-expanded-'+theme);});
    }
}
return {shots:10, reserved, safe:true};
'''.replace('CASES', json.dumps(CASES))
        with tempfile.TemporaryDirectory() as tmp:
            src, binary, page = [Path(tmp) / n for n in ('page.swift', 'page', 'page.html')]
            orbs = (ROOT / 'ui/orbs.js').read_text()
            formatter = orbs[orbs.index('// TeX → MathML'):orbs.index('export { MML')]
            page.write_text((ROOT / 'ui/ui.html').read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/', orbs)
                            + '<script type="module">'+formatter+'\nwindow.charts={graph,graphFunction,markdown};</script>')
            src.write_text(harness)
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(page), "ui.autoMinimize(false);" + script], capture_output=True, text=True, timeout=90)
        self.assertEqual(run.returncode, 0, run.stdout[-4000:] + run.stderr)
        for line in run.stdout.splitlines():
            if line.startswith('PNG '): print(line, flush=True)
        got = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertFalse([p for p in got['posts'] if isinstance(p, dict) and 'error' in p], got['posts'])
        self.assertEqual(got['result'], {'shots': 10, 'reserved': 270, 'safe': True})
