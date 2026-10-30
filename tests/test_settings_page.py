"""ui/settings.html in a real offscreen WKWebView with a recording bridge: no app, window or user settings."""
import contextlib
import io
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''import Cocoa
import WebKit
// Loads the page like SettingsWindow, runs argv[2] as an async function body, prints {"result", "posts"}.
final class Harness: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    var posts: [Any] = []
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) { posts.append(m.body) }
    func webView(_ v: WKWebView, didFinish n: WKNavigation!) {
        v.callAsyncJavaScript(CommandLine.arguments[2], arguments: [:], in: nil, in: .page) { r in
            switch r {
            case .success(let x):
                let out = try! JSONSerialization.data(withJSONObject: ["result": x ?? NSNull(), "posts": self.posts])
                print(String(data: out, encoding: .utf8)!); exit(0)
            case .failure(let e): print(e); exit(1)
            }
        }
    }
}
let nsapp = NSApplication.shared
let h = Harness(), cfg = WKWebViewConfiguration()
cfg.userContentController.add(h, name: "st")
let v = WKWebView(frame: NSRect(x: 0, y: 0, width: 780, height: 560), configuration: cfg)
v.navigationDelegate = h
v.loadHTMLString(try! String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8), baseURL: nil)
DispatchQueue.main.asyncAfter(deadline: .now() + 20) { print("timeout"); exit(1) }
nsapp.run()
'''
SETUP = '''
st.load({prefs: {hotkeyLabel: '⌃⌥Space', volume: .16, meeting: true}});
const use = {asks: 0, usd: 0, secs: 0};
st.state({today: use, week: use, all: use, rules: ['Keep it short'], skills: [{say: 'focus mode', reply: 'Done'}],
  me: {facts: [{id: 'f1', category: 'basics', kind: 'name', value: 'Sam', source: 'you', date: ''}]}, plan: {ok: true, text: 'Ready'}});
const tick = ms => new Promise(r => setTimeout(r, ms));
'''


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class SettingsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        src, cls.binary = Path(cls.tmp.name) / 'page.swift', Path(cls.tmp.name) / 'page'
        src.write_text(HARNESS)
        built = subprocess.run(['swiftc', str(src), '-o', str(cls.binary)], capture_output=True, text=True)
        assert built.returncode == 0, built.stderr

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def page(self, script):
        p = subprocess.run([str(self.binary), str(ROOT / 'ui/settings.html'), SETUP + script], capture_output=True, text=True,
                           timeout=30, env={**os.environ, 'ATTICUS_DIR': self.tmp.name})
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout.strip().splitlines()[-1])

    def test_wake_word_defaults_off_and_saves_one_toggle(self):
        out = self.page("""const wake=document.querySelector('[data-k=wakeWord]');
            const before=wake.checked; wake.click(); await tick(20);
            st.load({prefs:{hotkeyLabel:'⌃⌥Space',wakeWord:false}});
            return [before,wake.checked,wake.closest('.group') === document.querySelector('[data-k=talkMode]').closest('.group'),wake.closest('.row') === wake.closest('.group').lastElementChild];""")
        self.assertEqual(out['result'], [False, False, True, True])
        self.assertIn({'do': 'set', 'k': 'wakeWord', 'v': True}, out['posts'])

    def test_wake_word_name_saves_trimmed_and_shows_saved(self):
        out = self.page("""const name=document.querySelector('[data-k=wakeWordName]');
            st.load({prefs:{hotkeyLabel:'⌃⌥Space',wakeWordName:'Jarvis'}}); const shown=name.value;
            name.value='  Friday '; name.dispatchEvent(new Event('change')); await tick(20);
            return shown;""")
        self.assertEqual(out['result'], 'Jarvis')
        self.assertIn({'do': 'set', 'k': 'wakeWordName', 'v': 'Friday'}, out['posts'])

    def test_sharing_compatibility_notice_preserves_saved_choice(self):
        out = self.page("""st.load({prefs:{hotkeyLabel:'⌃⌥Space',hideWhenSharing:true},sharingUnavailable:true});
            const before=[!$('sharingUnavailable').hidden,document.querySelector('[data-k=hideWhenSharing]').checked];
            st.load({prefs:{hotkeyLabel:'⌃⌥Space',hideWhenSharing:false},sharingUnavailable:false});
            return [before,$('sharingUnavailable').hidden,document.querySelector('[data-k=hideWhenSharing]').checked];""")
        self.assertEqual(out['result'], [[True, True], True, False])
        self.assertNotIn({'do': 'set', 'k': 'hideWhenSharing', 'v': False}, out['posts'])

    def test_row_lines_stay_short(self):
        page = (ROOT / 'ui/settings.html').read_text()
        lines = [re.sub(r'<i class="info"[^>]*>i</i>|<[^>]+>', '', m).strip() for m in re.findall(r'</b><span[^>]*>(.*?)</span></div>', page) if '${' not in m]
        self.assertGreater(len(lines), 40)
        self.assertEqual([t for t in lines if len(t.split()) > 14], [])   # rare detail goes in an info tip
        self.assertTrue(all(re.search(r'<i class="info" title="[^"]+">i</i></span>', m) for m in re.findall(r'<span>[^<]*<i class="info".*?</span>', page)))
        self.assertIn('Risky actions need approval. Background agents use a scratch folder.', page)

    def test_whisper_rows_follow_the_speech_model_and_report_status(self):
        out = self.page("""const rows=()=>[...document.querySelectorAll('[data-w]')].map(r=>!r.hidden);
            const W=(over,models)=>({server:true,model:'turbo',running:false,error:null,models:models||[{id:'turbo',name:'Turbo',size:'574 MB',have:false,progress:null},
              {id:'large',name:'Large v3',size:'1.1 GB',have:true,progress:null},{id:'small',name:'Small',size:'190 MB',have:false,progress:.42}],...over});
            const shown=()=>[$('wtext').textContent,['winstall','wdownload','wcancel','wdelete'].filter(b=>!$(b).hidden).join()];
            st.whisper(W({server:false}));
            const early=rows(); set('speechModel','dictation'); const dictation=rows();
            document.querySelector('[data-k=speechModel] [data-v=whisper]').click(); const whisper=rows();
            const states=[shown()];
            st.whisper(W({server:true})); states.push(shown(), [$('wdownload').textContent]);
            $('wdownload').click();
            document.querySelector('[data-k=whisperModel]').value='small'; document.querySelector('[data-k=whisperModel]').onchange(); states.push(shown()); $('wcancel').click();
            document.querySelector('[data-k=whisperModel]').value='large'; document.querySelector('[data-k=whisperModel]').onchange(); states.push(shown()); $('wdelete').click();
            document.querySelector('[data-k=whisperModel]').value='turbo'; document.querySelector('[data-k=whisperModel]').onchange();
            st.whisper(W({error:'Download failed. Check your connection and try again.'})); states.push(shown()); $('wdownload').click();
            const lang=document.querySelector('[data-k=whisperLanguage]'); lang.value='id'; lang.onchange();
            return [early,dictation,whisper,states,P.whisperLanguage,lang.value];""")
        self.assertEqual(out['result'], [[False] * 3, [False] * 3, [True] * 3,
            [['Needs whisper.cpp.', 'winstall'], ['Model not downloaded.', 'wdownload'], ['Download 574 MB'], ['Downloading 42%…', 'wcancel'],
             ['Ready. Runs on this Mac.', 'wdelete'], ['Download failed. Check your connection and try again.', 'wdownload']], 'id', 'id'])
        for m in [{'do': 'set', 'k': 'speechModel', 'v': 'whisper'}, {'do': 'set', 'k': 'whisperModel', 'v': 'small'}, {'do': 'set', 'k': 'whisperLanguage', 'v': 'id'},
                  {'do': 'whisperDownload', 'id': 'turbo'}, {'do': 'whisperCancel', 'id': 'small'}, {'do': 'whisperDelete', 'id': 'large'}]:
            self.assertIn(m, out['posts'])

    def test_whisper_install_button_posts_install(self):
        out = self.page("""set('speechModel','whisper'); st.whisper({server:false,models:[]}); $('winstall').click();
            const sel=document.querySelector('[data-k=whisperModel]'); sel.focus(); st.whisper({server:true,models:[]}); st.whisper({server:true,models:[]});
            return [document.activeElement===sel,$('wtext').textContent];""")
        self.assertEqual(out['result'], [True, 'Model not downloaded.'])
        self.assertIn({'do': 'whisperInstall'}, out['posts'])

    def test_notice_shows_and_its_action_runs_once(self):
        out = self.page('''st.notice({text: 'Couldn’t save that change, so the old setting is back.'});
            const shown = !$('notice').hidden && $('noticebtn').hidden;
            let ran = 0; showNotice('Rule forgotten.', 'Undo', () => ran++); $('noticebtn').click();
            return [shown, ran, $('notice').hidden];''')
        self.assertEqual(out['result'], [True, 1, True])

    def test_dictation_stays_off_until_its_shortcut_is_recorded(self):
        out = self.page("""const field=$('dictatechange'),mode=()=>document.querySelector('[data-k=dictateMode]').closest('.row').classList.contains('dim');
            const before=[field.textContent,$('dictateclear').hidden,mode()];
            document.querySelector('[data-k=dictateMode] [data-v=cleanup]').click(); const chosen=P.dictateMode;
            field.click(); await tick(20); const typing=[field.textContent,field.classList.contains('rec')];
            st.rec('⌃⌥'); const held=[...field.querySelectorAll('.cap')].map(c=>c.textContent).join('');
            st.load({prefs:{hotkeyLabel:'⌃⌥Space',dictateHotkeyLabel:'⌃⌥D'}});
            const set=[[...field.querySelectorAll('.cap')].map(c=>c.textContent).join(''),field.classList.contains('rec'),$('dictateclear').hidden,mode()];
            $('dictateclear').click(); await tick(20);
            return [before,chosen,typing,held,set];""")
        self.assertEqual(out['result'], [['Record Shortcut', True, True], 'cleanup', ['Type Shortcut', True], '⌃⌥', ['⌃⌥D', False, False, False]])
        self.assertIn({'do': 'set', 'k': 'dictateMode', 'v': 'cleanup'}, out['posts'])
        self.assertIn({'do': 'recordDictate'}, out['posts'])
        self.assertIn({'do': 'clearDictate'}, out['posts'])

    def test_globe_key_fix_shows_only_while_macos_takes_fn(self):
        out = self.page("""st.load({prefs:{hotkeyLabel:'⌃⌥Space',dictateHotkeyLabel:'fn'},globeTaken:true});
            const row=$('globefix'), shown=[!row.hidden,row.textContent.includes('Set Press 🌐 key to Do Nothing'),$('dictatehint').textContent];
            row.querySelector('button').click(); await tick(20); st.globe(false);
            return [shown,row.hidden];""")
        self.assertEqual(out['result'], [[True, True, 'Hold to talk. Double-tap to lock.'], True])
        self.assertIn({'do': 'globeKey'}, out['posts'])

    def test_cleanup_is_disabled_with_a_reason_for_pi_and_devin(self):
        out = self.page("""const state=client=>{st.load({prefs:{client,hotkeyLabel:'⌃⌥Space',dictateHotkeyLabel:'⌃⌥D',dictateMode:'cleanup'}});
            const clean=document.querySelector('[data-k=dictateMode] [data-v=cleanup]');
            return [clean.disabled,$('dictatemodehint').textContent];};
            return [state('pi'),state('devin'),state('claude')];""")
        self.assertEqual(out['result'], [[True, 'Clean up needs Claude.'],
                                         [True, 'Clean up needs Claude.'],
                                         [False, 'Clean up drops fillers, fixes misheard words.']])

    def test_dictation_clash_warns_in_its_row_then_settles(self):
        out = self.page("""st.load({prefs:{hotkeyLabel:'⌃⌥Space',dictateHotkeyLabel:'⌃⌥D'},dictateHotkeyTaken:true});
            const taken=[$('dictatehint').textContent,$('dictatehint').className,$('dictatechange').classList.contains('bad')];
            $('dictatechange').click(); await tick(20); st.taken('dictate',true); st.load({prefs:{hotkeyLabel:'⌃⌥Space',dictateHotkeyLabel:'⌃⌥D'}});
            const own=[$('dictatehint').textContent,$('dictatehint').className,$('schint').className];
            return [taken,own];""")
        taken, own = out['result']
        self.assertEqual(taken[1:], ['taken', True])
        self.assertIn('Another app uses this shortcut', taken[0])
        self.assertEqual(own, ['That’s already your Atticus shortcut. Kept your old one.', 'warn', ''])

    def test_sections_open_at_top_and_apps_opens_under_account(self):
        out = self.page("""const main=document.querySelector('main');st.tab('brain');main.scrollTop=300;const scrolled=main.scrollTop>0;
            st.tab('account');st.tab('brain');const top=main.scrollTop;st.tab('apps');
            return [scrolled,top,$('apps').classList.contains('on'),document.querySelector('nav button.on')?.dataset.s];""")
        self.assertEqual(out['result'], [True, 0, True, 'account'])
        self.assertIn({'do': 'apps'}, out['posts'])

    def test_nix_install_shows_its_real_update_path(self):
        out = self.page("""st.load({prefs:{hotkeyLabel:'⌃⌥Space'},managedUpdates:true,update:'Run nix profile upgrade or nix run again.',version:'1.3.3 · Nix'});
            return [$('autoUpdateRow').hidden,$('checkUpdate').hidden,$('updateTitle').textContent,$('upstatus').textContent,$('aboutver').textContent];""")
        self.assertEqual(out['result'], [True, True, 'Updates are managed by Nix', 'Run nix profile upgrade or nix run again.', 'Version 1.3.3 · Nix'])

    def test_retired_settings_are_hidden_and_keep_saved_values(self):
        sys.path.insert(0, str(ROOT)); import atticus
        source, page = (ROOT / 'Atticus.swift').read_text(), (ROOT / 'ui/settings.html').read_text()
        retired = re.findall(r'"(\w+)"', source[source.index('static let retiredKeys'):source.index(']', source.index('static let retiredKeys'))])
        self.assertIn('workIn', retired)
        defaults = source[source.index('static let defaults'):source.index('static let retiredKeys')]
        self.assertIn('"quietAudio": false', defaults)
        self.assertNotIn('retiredKeys.filter', source)
        for key in retired:
            with self.subTest(key=key):
                self.assertIn(f'"{key}":', defaults)   # new users still receive a value
                self.assertNotIn(f'data-k="{key}"', page)
                self.assertNotIn(key, atticus.switches())
                self.assertNotIn(key, atticus.picks())
        self.assertEqual(len(page.split('<nav>')[1].split('</nav>')[0].split('data-s=')) - 1, 9)   # 8 pages and Report feedback

    def test_pages_wear_their_sidebar_color_and_row_actions_show_on_focus(self):
        out = self.page("""document.body.classList.add('reduce');
            const nav=[...document.querySelectorAll('nav button[data-s] .ni')].map(i=>i.style.background);
            const titled=[...document.querySelectorAll('nav button[data-s] .ni')].map(i=>$(i.parentNode.dataset.s).querySelector('h1 .ni')?.style.background===i.style.background);
            st.load({prefs:{hotkeyLabel:'⌃⌥Space'},routines:[{id:'r',kind:'interval',every:3600,ask:'Check'}]}); const x=$('routines').querySelector('.x');
            const reveal=[...document.styleSheets[0].cssRules].find(r=>r.selectorText?.includes('.row:hover > .x'))?.selectorText||'';   // a windowless view never takes focus
            return [new Set(nav).size===nav.length,titled,getComputedStyle(x).opacity,reveal.includes('.row:focus-within > .x'),!!$('general').querySelector('[data-do=quit]'),!!$('account').querySelector('[data-do=quit]')];""")
        distinct, titled, hidden, keyboard, quit_general, quit_account = out['result']
        self.assertTrue(distinct)
        self.assertEqual(titled, [True] * 7 + [False])   # About has its own big icon
        self.assertEqual((hidden, keyboard), ('0', True))
        self.assertEqual((quit_general, quit_account), (True, False))

    def test_long_asks_always_move_so_there_is_no_choice(self):
        sys.path.insert(0, str(ROOT)); import atticus
        for gone in ('agentsAuto', 'longAsks'):
            self.assertNotIn(gone, (ROOT / 'ui/settings.html').read_text())
            self.assertNotIn(gone, atticus.switches())
            self.assertNotIn(gone, atticus.picks())
        self.assertEqual(atticus.picks()['dictateMode'][1], {'Verbatim': 'verbatim', 'Clean up': 'cleanup'})

    def test_scheduled_routines_list_and_remove(self):
        out = self.page("""st.load({prefs:{hotkeyLabel:'⌃⌥Space'},routines:[
              {id:'weekday',kind:'time',at:'08:00',days:'weekdays',ask:'Summarize my calendar'},
              {id:'hourly',kind:'interval',every:3600,ask:'Check the fixture'}]});
            const labels=[...$('routines').querySelectorAll('.t b')].map(e=>e.textContent);
            $('routines').querySelector('.x').click(); return labels;""")
        self.assertEqual(out['result'], ['Weekdays at 8:00 AM', 'Every hour'])
        self.assertIn({'do': 'routineRemove', 'id': 'weekday'}, out['posts'])

    def test_single_deletes_wait_for_undo(self):
        out = self.page('''const row = () => document.querySelector('#rules [data-i="0"]').closest('.row');
            document.querySelector('#rules [data-i="0"]').click(); const hidden = row().hidden;
            $('noticebtn').click(); const back = !row().hidden;
            document.querySelector('[data-profile-drop="f1"]').click();
            document.querySelector('[data-u="0"]').click();   // a second delete sends the first
            const closing = st.flush(); await tick(30);
            return [hidden, back, closing];''')
        hidden, back, closing = out['result']
        self.assertTrue(hidden and back)
        self.assertEqual(closing, {'do': 'unlearn', 'say': 'focus mode'})
        self.assertEqual([p for p in out['posts'] if p.get('do') in ('forget', 'me', 'unlearn')], [{'do': 'me', 'action': 'drop', 'id': 'f1'}])

    def test_custom_server_says_whether_it_answered(self):
        out = self.page('''$('apiBase').value = 'http://localhost:1'; $('apiBase').onchange(); const checking = $('srvnote').textContent;
            st.models({base: P.apiBase, key: P.apiKey || '', list: []}); const none = $('srvnote').textContent;
            st.models({base: P.apiBase, key: P.apiKey || '', list: ['m1', 'm2']}); return [checking, none, $('srvnote').textContent, P.apiModel];''')
        checking, none, found, model = out['result']
        self.assertEqual(checking, 'Checking the server…')
        self.assertIn('No models found there', none)
        self.assertTrue(found.startswith('Found 2 models') and model == 'm1')
        self.assertIn({'do': 'models'}, out['posts'])

    def test_running_local_server_can_fill_address_and_model(self):
        out = self.page("""P.client='pi'; st.local([{name:'Ollama',base:'http://localhost:11434',models:['qwen3']}]);
            const offered=!$('localserver').hidden&&$('uselocal').textContent==='Use Ollama';
            $('uselocal').click(); return [offered,P.client,P.apiBase,P.apiModel,$('localserver').hidden];""")
        self.assertEqual(out['result'], [True, 'claude', 'http://localhost:11434', 'qwen3', True])
        self.assertIn({'do': 'set', 'k': 'client', 'v': 'claude'}, out['posts'])
        self.assertIn({'do': 'set', 'k': 'apiBase', 'v': 'http://localhost:11434'}, out['posts'])
        self.assertIn({'do': 'set', 'k': 'apiModel', 'v': 'qwen3'}, out['posts'])

    def test_pi_client_explains_its_provider_and_hides_claude_models(self):
        out = self.page("""st.load({prefs:{client:'pi',hotkeyLabel:'⌃⌥Space'}});
            const model=document.querySelector('[data-k=model]').closest('.row');
            return [$('brainlede').textContent,$('clientwhy').textContent,model.hidden,$('planname').textContent,$('safenote').textContent,$('agentsettings').hidden];""")
        lede, why, hidden, plan, safety, agents_hidden = out['result']
        self.assertIn('selected in Pi', lede)
        self.assertIn('local models', why)
        self.assertTrue(hidden)
        self.assertEqual(plan, 'Pi')
        self.assertIn('approval', safety)
        self.assertTrue(agents_hidden)

    def test_stale_server_models_cannot_change_the_current_model(self):
        out = self.page("""P.apiBase='server-b'; P.apiKey='key-b';
            st.models({base:'server-b',key:'key-b',list:['b']});
            st.models({base:'server-a',key:'key-a',list:['a']});
            st.models({base:'server-b',key:'old-key',list:['old']});
            return [P.apiModel, $('apimodels').options[0].value, $('srvnote').textContent];""")
        self.assertEqual(out['result'][0:2], ['b', 'b'])
        self.assertIn('Found 1 model', out['result'][2])
        self.assertFalse(any(p.get('value') in ('a', 'old') for p in out['posts']))

    def test_history_lists_searches_and_copies_answers(self):
        out = self.page('''st.state({today: use, week: use, all: use, rules: [], skills: [], me: {facts: []}, plan: {ok: true, text: ''},
              asks: [{at: '2026-10-15 09:30:00', task: 'weather', reply: 'Sunny'}, {at: '2026-10-14 08:00:00', task: 'open notes', reply: 'Opened Notes'}]});
            const all = $('asklist').querySelectorAll('.row').length;
            $('askq').value = 'notes'; $('askq').oninput(); const rows = [...$('asklist').querySelectorAll('.row b')].map(b => b.textContent);
            $('asklist').querySelector('.x.copy').click(); return [all, rows];''')
        self.assertEqual(out['result'], [2, ['open notes']])
        self.assertIn({'do': 'copy', 'text': 'Opened Notes'}, out['posts'])

    def test_import_failure_offers_the_settings_that_fix_it(self):
        out = self.page('''st.profileImport({errors: ['mail'], errorReasons: {mail:'automation'}, counts: {contacts: 3}}); const one = $('profileStatus').textContent;
            $('profileStatus').querySelector('.btn').click();
            st.profileImport({errors: ['contacts', 'mail'], errorReasons: {contacts:'automation',mail:'automation'}, counts: {}}); return [one, $('profileStatus').textContent];''')
        one, both = out['result']
        self.assertIn('3 from Contacts', one); self.assertIn('Allow Mail in Automation', one)
        self.assertIn('Allow Contacts and Mail in Automation', both)
        self.assertIn({'do': 'automation'}, out['posts'])

    def test_import_read_failure_offers_retry_without_false_permission_action(self):
        out = self.page("""st.profileImport({errors:['contacts','mail'],errorReasons:{contacts:'read',mail:'automation'},counts:{}});
            const mixed=$('profileStatus').textContent;
            st.profileImport({errors:['mail'],errorReasons:{mail:'read'},counts:{contacts:2}});
            return [mixed,$('profileStatus').textContent,$('profileStatus').querySelectorAll('.btn').length];""")
        self.assertIn('Allow Mail in Automation', out['result'][0])
        self.assertNotIn('Allow Contacts', out['result'][0])
        self.assertIn('Try importing again', out['result'][1])
        self.assertEqual(out['result'][2], 0)

    def test_state_lists_recent_answers_newest_first(self):
        sys.path.insert(0, str(ROOT)); import atticus
        rows = [{'at': '2026-10-14 08:00:00', 'task': 'open notes', 'reply': 'Opened Notes', 'usd': 0, 'secs': 1},
                {'id': '1-1', 'at': '2026-10-15 09:00:00', 'task': 'weather', 'status': 'running', 'pid': os.getpid()},   # a checkpoint with no answer yet
                {'at': '2026-10-15 09:30:00', 'task': 'weather', 'reply': 'Sunny', 'usd': 0, 'secs': 1}]
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'log.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
            with patch.object(atticus, 'DIR', root), patch.object(atticus, 'MEMORY', str(Path(root) / 'memory.md')), \
                 patch.object(atticus, 'SKILLS', str(Path(root) / 'skills.json')), patch.object(atticus, 'plan', return_value={}), \
                 patch.object(atticus, 'me', return_value={}), patch('sys.argv', ['atticus.py', '--state']), \
                 contextlib.redirect_stdout(io.StringIO()) as out:
                atticus.main()
        self.assertEqual([(a['task'], a['reply']) for a in json.loads(out.getvalue())['asks']], [('weather', 'Sunny'), ('open notes', 'Opened Notes')])


if __name__ == '__main__':
    unittest.main()
