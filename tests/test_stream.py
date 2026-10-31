"""The main answer streams into the box as it arrives: fake Claude partial-message streams, no Mac actions."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import atticus

ROOT = Path(__file__).resolve().parents[1]
ANSWER = ('Paris is the capital of France. It sits on the Seine in the north of the country, and about two million people '
          'live in the city itself.')
FRIDGE = ("A refrigerator moves heat from inside the cabinet to the room. It does this with a closed loop of refrigerant that repeatedly evaporates (absorbing heat) and condenses (releasing heat). The main parts are:\n\n"
          "1. **Compressor:** An electric motor-driven pump that squeezes low-pressure refrigerant vapor into a hot, high-pressure gas. Compression raises the refrigerant's temperature above the kitchen air temperature.\n"
          "2. **Condenser coils:** Usually on the back or underneath. The hot gas flows through these, releases its heat into the room, and condenses into a warm, high-pressure liquid. A fan often helps this heat escape.\n"
          "3. **Expansion valve (or capillary tube):** A narrow restriction where the high-pressure liquid passes through and suddenly drops in pressure. Part of it flashes into vapor, and the whole mix becomes very cold.\n"
          "4. **Evaporator coils:** Inside the fridge or freezer. The cold, low-pressure refrigerant boils here, absorbing heat from the air and food around it. A fan usually circulates the chilled air.\n"
          "5. **Return to the compressor:** The refrigerant, now a low-pressure vapor, goes back to the compressor and the cycle repeats.\n\n"
          "**Why it works:** A liquid absorbs a lot of energy when it evaporates, and it releases that energy when it condenses. Changing the pressure changes the temperature at which this happens. The compressor raises the pressure so the refrigerant gets hot enough to dump heat outside, and the expansion valve lowers the pressure so it gets cold enough to absorb heat inside.\n\n"
          "**Other parts:**\n- **Thermostat:** Senses the cabinet temperature and turns the compressor on and off to hold a set point.\n"
          "- **Defrost system (frost-free models):** A heater or hot-gas cycle melts frost off the evaporator. Drain tubes carry the meltwater away.\n")


def deltas(text, size=7):
    return [{'type': 'stream_event', 'event': {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': text[i:i + size]}}}
            for i in range(0, len(text), size)]


def message(text='', tool=None):
    rows = [{'type': 'stream_event', 'event': {'type': 'message_start', 'message': {}}},
            {'type': 'stream_event', 'event': {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}}}]
    rows += deltas(text)
    blocks = [{'type': 'text', 'text': text}] if text else []
    if tool:
        rows.append({'type': 'stream_event', 'event': {'type': 'content_block_start', 'index': 1,
                                                       'content_block': {'type': 'tool_use', 'id': tool[0], 'name': 'Bash', 'input': {}}}})
        blocks.append({'type': 'tool_use', 'id': tool[0], 'name': 'Bash', 'input': {'command': tool[1]}})
    return rows + [{'type': 'assistant', 'message': {'content': blocks}}]


def result(tool_id, content='Observed state'):
    return {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': tool_id, 'content': content}]}}


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(); self.addCleanup(self.root.cleanup)
        patcher = patch.multiple(atticus, DIR=self.root.name, HOME=self.root.name, PREFS=str(Path(self.root.name) / 'settings.json'))
        patcher.start(); self.addCleanup(patcher.stop)

    def run_stream(self, rows, final, env=None, ask=''):
        p = Mock(); p.stdin = io.StringIO(); p.ask = ask; p.returncode = 0
        p.stdout = map(json.dumps, rows + [{'type': 'result', 'result': final, 'total_cost_usd': .001}])
        with patch.dict(os.environ, {'ATTICUS_UI': '1', 'ATTICUS_COMMIT': '', **(env or {})}), patch.object(atticus.threading, 'Thread'), \
             patch.object(atticus.threading, 'Timer'), patch.object(atticus, 'preview_commands'), contextlib.redirect_stdout(io.StringIO()) as out:
            reply, _, _ = atticus.run('Request: fixture', p)
        lines = out.getvalue().rstrip('\n').split('\n')   # not splitlines(): an answer's own line breaks travel as U+2028
        return reply, lines, [line[2:] for line in lines if line.startswith('… ')]

    def test_streamed_answer_never_shows_tags_drafts_handoffs_or_sources(self):
        long = ANSWER + ' '
        self.assertEqual(atticus.streamed_answer(long), ANSWER)
        self.assertEqual(atticus.streamed_answer(ANSWER[:100]), '')   # could still be a 3-8 word note
        for held in ('[draft] ' + long, '[insert] ' + long, '[replace] ' + long, '  \n[agent {\n  "title": "x",\n' + long,
                     '```json\n[agent ' + long, '[sonnet]', '[steer {"id":"a","text":"' + long, '[agent-profile {' + long):
            self.assertEqual(atticus.streamed_answer(held), '', held)
        for tag in ('[tip Say "remember: x"]', '[point 1 20 30]', '[workflow x | y]', '[replay open -a Notes]', '[done]',
                    '[agent {"title":"x","brief":"y"}]', '[agent-result {}]', '[steer {"id":"a"}]'):
            self.assertEqual(atticus.streamed_answer(long + tag + ' after the tag'), ANSWER, tag)
        self.assertEqual(atticus.streamed_answer(long + '\nSources: https://x.example'), ANSWER)
        self.assertEqual(atticus.streamed_answer(long + '\nSour'), ANSWER)   # may still become "Sources:"
        self.assertEqual(atticus.streamed_answer(ANSWER + '\n- More'), ANSWER + '\n- More')
        for text in ('See [1], [ ] and a[0].', 'See [the guide](https://x.example) and [Apple](https://apple.example).'):
            self.assertEqual(atticus.streamed_answer(long + text), long + text)   # not a tag: the rest keeps streaming
        self.assertEqual(atticus.streamed_answer(long + 'See [the guide'), long + 'See')   # may still be a tag until it closes as a link
        self.assertEqual(atticus.streamed_answer(long + '[agent {"brief":"read [x](y)"}] after'), ANSWER)

    def test_plain_answer_streams_and_the_final_reply_replaces_it(self):
        reply, lines, shown = self.run_stream(message(ANSWER), ANSWER)
        self.assertEqual(reply, ANSWER)
        self.assertGreater(len(shown), 2, 'the answer arrives in pieces')
        self.assertTrue(all(ANSWER.startswith(s) for s in shown)); self.assertEqual(shown[-1], ANSWER)
        self.assertEqual(shown, sorted(shown, key=len), 'the shown text only grows')
        self.assertTrue(all(len(s) >= 120 for s in shown))

    def test_multi_line_agent_handoff_never_prints_text_and_hands_off(self):
        marker = '[agent ' + json.dumps({'title': 'Research desks', 'brief': 'Compare standing desks under $600 across sources', 'context': ANSWER}, indent=2) + ']'
        ask = tempfile.mkdtemp(dir=self.root.name)
        with patch.object(atticus, 'wait_commit', return_value=True):
            reply, lines, shown = self.run_stream(message(marker + '\n' + ANSWER), marker + '\n' + ANSWER, ask=ask)
        self.assertEqual(reply, ''); self.assertEqual(shown, [])
        self.assertEqual(sum(line.startswith('⤴ ') for line in lines), 1)
        self.assertEqual(atticus.run.handoff['title'], 'Research desks')
        self.assertFalse(any(line.startswith(('✓', '·')) for line in lines))

    def test_note_before_a_tool_never_shows_as_the_answer(self):
        rows = message('Checking the weather', ('t1', 'curl -s wttr.in')) + [result('t1')] + message(ANSWER)
        reply, lines, shown = self.run_stream(rows, ANSWER)
        self.assertEqual(reply, ANSWER)
        self.assertNotIn('Checking the weather', ''.join(shown))
        self.assertIn('· Checking the weather', lines)   # the note is still a status line, as before
        self.assertEqual(shown[-1], ANSWER)
        self.assertLess(lines.index('· Checking the weather'), next(i for i, line in enumerate(lines) if line.startswith('… ')))

    def test_a_long_note_is_cleared_when_its_tool_call_starts(self):
        note = 'I will look this up first. ' * 6
        rows = message(note, ('t1', 'curl -s wttr.in')) + [result('t1')] + message(ANSWER)
        _, lines, shown = self.run_stream(rows, ANSWER)
        clear = lines.index('… ')
        self.assertTrue(any(line.startswith('… I will') for line in lines[:clear]))
        self.assertFalse(any(line.startswith('… I will') for line in lines[clear:]))
        self.assertLess(clear, next(i for i, line in enumerate(lines) if line.startswith(('· ', '▸ '))), 'cleared before its note and step show')

    def test_control_tags_mid_stream_are_never_shown(self):
        for tag in ('[tip Say "remember: open means front"]', '[point 1 200 300]', '[workflow Plan | method]', '[done]', '[agent {"title":"a","brief":"b"}]'):
            with self.subTest(tag=tag):
                text = ANSWER + ' ' + tag + ' Words after the tag.'
                _, _, shown = self.run_stream(message(text), text)
                self.assertTrue(shown); self.assertFalse(any('[' in s or 'after the tag' in s for s in shown))

    def test_nothing_streams_before_the_transcript_is_confirmed_or_outside_the_box(self):
        commit = Path(self.root.name) / 'commit'
        _, _, shown = self.run_stream(message(ANSWER), ANSWER, env={'ATTICUS_COMMIT': str(commit)})
        self.assertEqual(shown, [])
        commit.write_text('go')
        _, _, shown = self.run_stream(message(ANSWER), ANSWER, env={'ATTICUS_COMMIT': str(commit)})
        self.assertEqual(shown[-1], ANSWER)
        _, _, shown = self.run_stream(message(ANSWER), ANSWER, env={'ATTICUS_UI': ''})
        self.assertEqual(shown, [])

    def failed_early_start(self, commit, getppid=os.getppid, sleep=atticus.time.sleep):
        p = Mock(); p.stdin = io.StringIO(); p.ask = ''; p.returncode = 0; p.errors = io.StringIO()
        p.stdout = map(json.dumps, [{'type': 'result', 'is_error': True, 'result': 'API Error: fixture', 'total_cost_usd': 0,
                                     'usage': {'input_tokens': 0, 'output_tokens': 0}, 'modelUsage': {}}])   # ended before any model call
        with patch.dict(os.environ, {'ATTICUS_UI': '1', 'ATTICUS_COMMIT': str(commit)}), patch.object(atticus.threading, 'Thread'), \
             patch.object(atticus.threading, 'Timer'), patch.object(atticus.os, 'getppid', getppid), \
             patch.object(atticus.time, 'sleep', sleep), contextlib.redirect_stdout(io.StringIO()) as out:
            reply, _, _ = atticus.run('Request: fixture', p)
        return reply, out.getvalue().splitlines()

    def test_a_failed_early_start_opens_setup_only_after_the_transcript_is_confirmed(self):
        commit = Path(self.root.name) / 'commit'
        reply, lines = self.failed_early_start(commit, getppid=Mock(side_effect=[100, 101]))   # the app dropped this start unconfirmed
        self.assertIn('Claude stopped', reply)
        self.assertNotIn('! setup', lines)
        _, lines = self.failed_early_start(commit, sleep=lambda _: commit.write_text('go'))   # the user lets go and these words are confirmed
        self.assertEqual(lines.count('! setup'), 1)
        with patch.dict(os.environ, {'ATTICUS_COMMIT': ''}), contextlib.redirect_stdout(io.StringIO()) as out:
            atticus.say('!', 'setup')   # typed asks have no transcript to wait for
        self.assertEqual(out.getvalue(), '! setup\n')

    def test_show_answers_setting_streams_as_they_arrive_or_shows_all_at_once(self):
        _, _, shown = self.run_stream(message(ANSWER), ANSWER)
        self.assertEqual(shown[-1], ANSWER)   # default: as they arrive
        for value, streams in (('stream', True), ('once', False)):
            with self.subTest(value=value):
                Path(atticus.PREFS).write_text(json.dumps({'showAnswers': value}))
                reply, _, shown = self.run_stream(message(ANSWER), ANSWER)
                self.assertEqual(bool(shown), streams); self.assertEqual(reply, ANSWER)   # all at once: only the final reply, with its classic fade
        self.assertEqual(atticus.picks()['showAnswers'], ('Show answers', {'As they arrive': 'stream', 'All at once': 'once'}))
        self.assertIn('"showAnswers": "stream"', (ROOT / 'Atticus.swift').read_text())

    def test_drawing_or_pointing_replies_do_not_stream(self):
        rows = message('Drawing it', ('d1', f'{atticus.ME} --draw \'{{"steps":[]}}\'')) + [result('d1', 'Guide shown (step 1 of 1).')] + message(ANSWER)
        _, _, shown = self.run_stream(rows, ANSWER)
        self.assertEqual(shown, [])

    def test_main_asks_request_partial_messages_and_stay_strict(self):
        with patch.object(atticus.shutil, 'which', return_value='/fixture/claude'), patch.object(atticus.subprocess, 'Popen') as popen, \
             patch.object(atticus.atexit, 'register'), patch.object(atticus.signal, 'signal'):
            atticus.start_claude().errors.close()
        args = popen.call_args.args[0]
        for flag in ('--include-partial-messages', '--no-session-persistence', '--strict-mcp-config'): self.assertIn(flag, args)

    def box(self, checks):
        """Runs the page's real line()/markdown()/reveal() on a tiny fake DOM and clock; the answer starts 100px into a 420px-tall thread."""
        page = (ROOT / 'ui' / 'ui.html').read_text()
        unstream = re.search(r'  const unstream = .*\n', page).group(0)
        shared = (ROOT / 'ui' / 'orbs.js').read_text()
        reveal = shared[shared.index('// TeX → MathML'):shared.index('export { MML')] + page[page.index('  const leaf = c =>'):page.index('  let mini = null')]
        line = page[page.index('    line(l) {'):page.index('    msg(s) {')]
        script = r'''
class C{constructor(n){this.n=n}has(){return this.n.className.split(' ').filter(Boolean)}contains(c){return this.has().includes(c)}
  add(c){if(!this.contains(c))this.n.className=[...this.has(),c].join(' ')}remove(...c){this.n.className=this.has().filter(x=>!c.includes(x)).join(' ')}}
class N{constructor(name,type=1,ns){this.nodeName=name;this.nodeType=type;this.namespaceURI=ns;this.childNodes=[];this.childNodes.at=undefined;this.parentNode=null;this.className='';this.style={};this.dataset={};this.classList=new C(this)}
  append(...k){for(let c of k){if(typeof c==='string')c=new T(c);if(c.nodeName==='#frag'){this.append(...c.childNodes);continue}c.remove();c.parentNode=this;this.childNodes.push(c)}}
  appendChild(c){this.append(c);return c}setAttribute(k,v){this[k]=v}
  get lastChild(){return this.childNodes[this.childNodes.length-1]||null}
  remove(){const p=this.parentNode;if(p){p.childNodes.splice(p.childNodes.indexOf(this),1);this.parentNode=null}}
  replaceWith(...k){const p=this.parentNode,i=p.childNodes.indexOf(this);this.remove();k=k.map(c=>typeof c==='string'?new T(c):c);k.forEach(c=>{c.remove();c.parentNode=p});p.childNodes.splice(i,0,...k)}
  replaceChildren(...k){[...this.childNodes].forEach(c=>c.remove());this.append(...k)}
  contains(n){for(;n;n=n.parentNode)if(n===this)return true;return false}
  get textContent(){return this.childNodes.map(c=>c.textContent).join('')}set textContent(v){this.replaceChildren(v)}
  words(){return this.childNodes.flatMap(c=>c.nodeName==='SPAN'?[c]:c.words?c.words():[])}}
class T extends N{constructor(d){super('#text',3);this.data=d;this.className=undefined}get textContent(){return this.data}words(){return []}}
const document={createElement:t=>new N(t.toUpperCase()),createElementNS:(ns,t)=>new N(t,1,ns),createDocumentFragment:()=>new N('#frag'),querySelectorAll:()=>[]};
let now=0;const performance={now:()=>now};
const a=new N('DIV');a.className='a';a.getBoundingClientRect=()=>({top:116-thread.scrollTop});
const thread={scrollTop:0,clientHeight:420,get scrollHeight(){return 120+a.words().length*40},getBoundingClientRect:()=>({top:0}),querySelectorAll:s=>s==='.a.streaming'&&a.classList.contains('streaming')?[a]:[]};
const $=()=>thread,part=c=>c==='a'?a:null,status=()=>{},settle=()=>{},setState=()=>{},miniFinish=()=>{},clockStop=()=>{},clockBegin=()=>{},turn=()=>null;
let folded=false,atBottom=true,clock=null,working=true;const fit=(follow=true)=>{if(follow&&atBottom)thread.scrollTop=thread.scrollHeight};
''' + unstream + reveal + 'const ui={' + line + r'''};
const words=()=>a.words().map(w=>w.textContent).join(' '),check=(ok,name)=>{if(!ok){console.error(name,'|',words(),'|',a.className,thread.scrollTop);process.exit(1)}};
''' + checks
        result = subprocess.run(['node', '-'], input=script, capture_output=True, text=True)   # stdin: Linux caps one argument at 128 KB
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node runs the box handler')
    def test_box_shows_the_answer_so_far_and_replaces_or_clears_it(self):
        page = (ROOT / 'ui' / 'ui.html').read_text()
        self.box(r'''
ui.line('… First words here');check(words()==='First words'&&a.classList.contains('streaming'),'shows the answer so far, its last word may still be arriving');
ui.line('… First words\u2028- a list item');check(a.childNodes.map(c=>c.nodeName).join()==='P,UL'&&words()==='First words a list','keeps its line breaks');
ui.line('· Checking the weather');check(a.textContent===''&&!a.classList.contains('streaming'),'a note clears it');
ui.line('… Again and');ui.line('… ');check(a.textContent==='','an empty line clears it');
for(const open of ['… It **moves heat from','… It `comp and so','… It [the link](https://x.co']){ui.line(open);check(a.textContent.trim()==='It','an open '+open.split(' ')[2][0]+' waits, never shown as a symbol');}
ui.line('… It **moves heat** via `gas` and [a link](https://x.co) then');check(words()==='It moves heat via gas and a link'&&!a.textContent.includes('*'),'closed marks show as bold, code and a link');
ui.line('… See [1] and a[0]\u2028- [ ] a task and');check(words()==='See [1] and a[0] [ ] a task','a bracket that is not a link shows at once');
ui.line('… ```\u2028x = a[0] and');check(a.textContent.includes('a[0]'),'inside a code block a bracket is text');
ui.line('… ');
ui.line('… Final answer');ui.line('✓ Final answer');check(words()==='Final answer'&&!a.classList.contains('streaming')&&a.dataset.answer==='Final answer','the final reply replaces it');
ui.line('… Late words');check(words()==='Final answer','a finished answer stays');
a.dataset={};a.replaceChildren();ui.line('✓ Fresh reply');check(a.words().length===2&&a.words().every(w=>w.className==='w'&&w.style.animationDelay),'an answer that did not stream still fades in');
''')
        self.assertIn('.a .w { display: inline-block; animation: word', page)   # the streamed words reuse the answer's fade (Reduce Motion turns it off)
        for call in ('    finished() { clockStop(); miniFinish(false); unstream(); unfoldToEnd(); },', "unpin(); unstream();", ".forEach(e => e.remove()); unstream();"):
            self.assertIn(call, page)   # a hand-off, an ask card or a choices card never leaves the provisional text

    @unittest.skipUnless(shutil.which('node'), 'Node runs the box handler')
    def test_streamed_words_fade_in_once_and_the_box_keeps_the_answers_start_in_view(self):
        self.box(r'''
const long=n=>Array.from({length:n},(_,i)=>'w'+i).join(' ');
ui.line('… '+long(6));const first=a.words(),delays=first.map(w=>w.style.animationDelay);
check(first.length===5&&first.every(w=>w.className==='w')&&delays[0]==='0ms','the first words fade in');
check(thread.scrollTop===0&&atBottom,'a short answer: nothing to scroll');
now=1000;ui.line('… '+long(20));const next=a.words();
check(first.every((w,i)=>next[i]===w&&w.style.animationDelay===delays[i]),'words on screen keep their nodes and are not animated again');
check(next.length===19&&next[5].style.animationDelay==='0ms'&&next.slice(5).every(w=>w.className==='w'),'only the new words fade in');
check(thread.scrollTop===100&&!atBottom,'a full box stops at the start of the answer, not the bottom');
ui.line('… '+long(30));check(thread.scrollTop===100,'it stays at the start while more arrives');
thread.scrollTop=700;atBottom=true;ui.line('… '+long(40));check(thread.scrollTop===700,'the user scrolled down: never yanked back up');
thread.scrollTop=40;atBottom=false;ui.line('… '+long(45));check(thread.scrollTop===40,'the user scrolled up: stays there');
const shown=a.words();now=9000;ui.line('✓ '+long(45)+' end.');const done=a.words();
check(shown.every((w,i)=>done[i]===w&&w.style.animationDelay===shown[i].style.animationDelay),'the final reply never re-fades words already shown');
check(done.length===46&&done.slice(44).map(w=>w.textContent).join()==='w44,end.'&&done[44].style.animationDelay==='0ms','only its words not yet shown fade in');
check(thread.scrollTop===40,'the final reply does not jump to the bottom');
''')

    @unittest.skipUnless(shutil.which('node'), 'Node runs the box handler')
    def test_a_long_streamed_answer_fades_in_reading_order_once(self):
        _, _, shown = self.run_stream(message(FRIDGE), FRIDGE)
        with contextlib.redirect_stdout(io.StringIO()) as out: atticus.say('✓', FRIDGE)
        lines = ['… ' + s for s in shown] + [out.getvalue().strip().replace('\u2028', '\n')]   # Swift unfolds the final reply's lines
        self.assertGreater(len(lines), 100)
        self.box('const lines=' + json.dumps(lines) + r''';
const seen=new Set(),starts=[];
lines.forEach((l,k)=>{now=k*25;ui.line(l);a.words().forEach((w,i)=>{if(seen.has(w))return;seen.add(w);
  check(w.className==='w'&&w.style.animationDelay,'no word appears without its fade: '+w.textContent);
  (starts[i]||=[]).push(Math.round(now+parseFloat(w.style.animationDelay)))})});
check(a.words().length===starts.length&&!a.classList.contains('streaming'),'the final reply is all there');
starts.forEach((s,i)=>{check(new Set(s).size===1,'a word re-rendered with the same text never fades again: '+a.words()[i].textContent+' '+s);
  check(!i||s[0]>=starts[i-1][0],'words fade in reading order: '+a.words()[i].textContent+' '+s+' after '+starts[i-1])});
check(Math.max(...starts.flat())-now<=900,'a long backlog catches up instead of lagging');
''')

    def test_closed_output_pipe_cancels_without_a_traceback(self):
        with patch('builtins.print', side_effect=BrokenPipeError), patch('sys.stdout', io.StringIO()), \
             patch.object(atticus, 'stop_workers', side_effect=SystemExit(0)) as stop:
            with self.assertRaises(SystemExit) as ended:
                atticus.say('✓', 'Finished.')
            atticus.sys.stdout.close()
        self.assertEqual(ended.exception.code, 0)
        stop.assert_called_once_with()

    @unittest.skipUnless(shutil.which('node'), 'Node runs the box handler')
    def test_a_streamed_blocks_marker_background_or_border_never_shows_before_its_first_word(self):
        text = ("A fridge pumps heat out of the cabinet. Its work per cycle is $$W = Q_h - Q_c$$ and the main parts are:\n\n## Parts\n\n"
                "- **Compressor:** squeezes the vapor so it gets hot.\n- **Condenser:** gives that heat to the room, check it with `fridge --status` daily.\n\n"
                "1. Compression raises the pressure.\n2. Expansion drops it again.\n\n```\nstate: cooling\nfan: on\n```\n\n"
                "| Part | Where |\n|---|---|\n| Coils | Back |\n| Fan | Inside |\n")
        _, _, shown = self.run_stream(message(text), text)
        with contextlib.redirect_stdout(io.StringIO()) as out: atticus.say('✓', text)
        lines = ['… ' + s for s in shown] + [out.getvalue().strip().replace('\u2028', '\n')]
        self.box('const lines=' + json.dumps(lines) + r''';
const unit=c=>c.className==='w'||c.namespaceURI||/\btex\b/.test(c.className);
const units=n=>n.childNodes.flatMap(c=>c.nodeType!==1?[]:unit(c)?[c]:units(c)),boxes=n=>n.childNodes.flatMap(c=>c.nodeType!==1||unit(c)?[]:[c,...boxes(c)]);
const start=new Map(),seen=new Set();
lines.forEach((l,k)=>{now=k*25;ui.line(l);
  units(a).forEach(u=>start.has(u)||start.set(u,now+parseFloat(u.style.animationDelay||0)));
  boxes(a).forEach(b=>{if(seen.has(b))return;seen.add(b);const us=units(b);
    check(us.length||b.nodeName==='BR','a list item, heading or code block shows only once it has a word: '+b.nodeName);
    if(/^(LI|PRE|CODE|TH|TD)$/.test(b.nodeName))check(b.style.animationDelay&&now+parseFloat(b.style.animationDelay)>=Math.min(...us.map(u=>start.get(u)))-1,
      'its marker, number, background or border fades in with its first word, never before: '+b.nodeName+' '+us[0].textContent)})});
const all=boxes(a).map(b=>b.nodeName+'.'+b.className).join();
check(['UL.','OL.','DIV.h','PRE.','CODE.','TD.'].every(b=>all.includes(b))&&units(a).some(u=>u.namespaceURI),'every kind of block was there: '+all);
''')
        self.assertIn('.turn > .a :is(li, pre, code, th, td) { animation: word .5s var(--ease) both; }', (ROOT / 'ui' / 'ui.html').read_text())   # the word fade; Reduce Motion turns it off


if __name__ == '__main__':
    unittest.main()
