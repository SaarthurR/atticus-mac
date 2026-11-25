"""Design screenshots of Settings, setup's provider sheet and the box's question cards, VM only (opt-in, not discovered: run this module by name).

run.sh ~/Projects/atticus tests.shoot_settings  → PNGs printed as base64 lines ("PNG <name> <data>"); the runner copies nothing back.
"""
import base64
import json
import unittest
from tests.shoot_agents_design import CARDS, SETUP, ROOT
from tests.test_agents_native import run_fixture

PREFS = {'hotkeyLabel': '⌃⌥Space', 'login': True, 'paused': False, 'volume': .16, 'client': 'claude', 'model': 'haiku',
         'routing': 'balanced', 'microphone': 'automatic', 'agentModel': 'sonnet', 'agentUserTools': True, 'screen': 'auto',
         'speak': False, 'hideWhenSharing': True, 'menuIcon': True, 'autoUpdate': True, 'safe': True, 'meeting': False,
         'meetingSave': True, 'learnMe': True, 'stats': True, 'tips': True, 'draw': True, 'dictateMode': 'verbatim',
         'dictate': True, 'dictateHotkeyLabel': '', 'dictateHistory': True, 'typeRight': True, 'talkMode': 'hold', 'speechModel': 'speech',
         'improve': False, 'drawModel': 'sonnet', 'modelSuggestions': True, 'voiceRate': 196}
STATE = {'today': {'asks': 3, 'usd': .004, 'secs': 3}, 'week': {'asks': 21, 'usd': .03, 'secs': 3.4}, 'all': {'asks': 140, 'usd': .2, 'secs': 3.8},
         'rules': ['When I say focus mode, close Slack and open Notes'], 'skills': [{'say': 'standup', 'reply': 'Opened Zoom and the standup notes'}],
         'me': {'facts': [{'id': 'f1', 'category': 'basics', 'kind': 'name', 'value': 'Sam', 'source': 'you', 'date': 'Oct 19'}]}, 'plan': {'ok': True, 'text': 'Signed in. Claude Max.'},
         'asks': [{'at': '2026-10-19 09:30:00', 'task': 'weather tomorrow', 'reply': 'Sunny, 68°F.'}, {'at': '2026-10-19 08:10:00', 'task': 'open my notes', 'reply': 'Opened Notes.'}]}
ROUTINES = [{'id': 'r1', 'kind': 'time', 'at': '08:00', 'days': 'weekdays', 'ask': 'Summarize my calendar', 'mode': 'cheapest'}]
DICTATION = {'words': ['Atticus', 'PostHog'], 'stats': {'today': 412, 'words': 18250, 'minutes': 96, 'sessions': 320},
             'history': [{'id': 'd1', 'timestamp': 1792425600, 'app': 'Notes', 'text': 'Pick up the desk lamp after school.'},
                         {'id': 'd2', 'timestamp': 1792422000, 'app': 'Messages', 'text': 'On my way, see you in ten.'}]}
MEETINGS = {'meetings': [{'id': 'm1', 'title': 'Design review', 'started': 1792425600, 'duration': 1860, 'app': 'Zoom', 'summary': 'Settings get their colors back.', 'status': 'Saved'}]}
TILE = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 30 30'%3E%3Crect width='30' height='30' rx='7' fill='%23COLOR'/%3E%3C/svg%3E"
APPS = [{'id': n, 'name': n, 'icon': TILE.replace('COLOR', c), 'suggested': True, 'status': st} for n, c, st in
        [('Notes', 'ffcc00', 'allowed'), ('Mail', '0a84ff', 'new'), ('Music', 'ff375f', 'blocked'), ('Calendar', 'ff453a', 'new')]]
PERMS = {'mic': True, 'speech': True, 'ax': True, 'screen': True, 'auto': True, 'chrome': False, 'calendar': True}

# Each scene: JavaScript run on the Settings page, then one shot of the whole window.
SCENES = [
    ('settings-dictation', "load({dictateHotkeyLabel:'fn'});st.tab('dictation');up()"),
    ('settings-dictation-end', "document.querySelector('main').scrollTop=1e5"),
    ('settings-dictation-keyboard', "(b=>{b.focus();b.scrollIntoView({block:'center'})})(document.querySelector('#dictationhistory .x.copy'))"),   # focus shows a row's actions, like hover
    ('settings-dictation-off', "load({dictateHotkeyLabel:'fn',dictate:false});st.tab('dictation');up()"),
    ('settings-general', "load({});st.tab('general');up()"),
    ('settings-general-voice', "document.querySelector('[data-do=testVoice]').scrollIntoView({block:'center'})"),
    ('settings-general-voicespeed', "(r=>{r.focus();r.scrollIntoView({block:'center'})})(document.querySelector('[data-k=voiceRate]'))"),
    ('settings-general-end', "document.querySelector('main').scrollTop=1e5"),
    # rows that hide and show close and open (expand): each shot is after the motion, so nothing is left half-way
    ('settings-general-typeright-off', "up();document.querySelector('[data-k=typeRight]').click()"),
    ('settings-general-typeright-on', "document.querySelector('[data-k=typeRight]').click()"),
    ('settings-general-whisper', "document.querySelector('[data-k=speechModel] button[data-v=whisper]').click();document.querySelector('[data-k=speechModel]').scrollIntoView({block:'center'})"),
    ('settings-general-switch', "load({});document.querySelector('#general .sw').scrollIntoView({block:'center'})"),
    ('settings-intelligence', "st.tab('brain');up()"),
    ('settings-intelligence-end', "document.querySelector('main').scrollTop=1e5"),
    ('settings-intelligence-cheapest', "load({routing:'cheapest'});st.tab('brain');up()"),
    ('settings-intelligence-server', "load({apiBase:'http://localhost:11434',apiModel:'qwen3'});st.tab('brain');up();st.models({base:'http://localhost:11434',key:'',list:['qwen3','llama3.2']})"),
    ('settings-memory', "load({});st.tab('memory');up();document.querySelector('.profile-category').open=true"),
    ('settings-memory-end', "document.querySelector('main').scrollTop=1e5"),
    ('settings-meetings', "st.tab('meetings');up();st.meetings(MEETINGS_JSON)"),
    ('settings-usage', "st.tab('usage');up()"),
    ('settings-account', "st.tab('account');up()"),
    ('settings-account-end', "document.querySelector('main').scrollTop=1e5"),
    ('settings-apps', "st.tab('apps');st.apps(APPS_JSON)"),
    ('settings-about', "st.tab('about');up()"),
    ('settings-feedback', "st.tab('feedback');up()"),
]
SCENES = [(n, js.replace('MEETINGS_JSON', json.dumps(MEETINGS)).replace('APPS_JSON', json.dumps(APPS))) for n, js in SCENES]
SETUP_PAGES = ['welcome', 'ai', 'model', 'perms', 'try', 'dictate', 'show', 'improve', 'tip', 'done']   # setup's steps after the permissions, in order

# By window ID: a stray system prompt in the VM cannot cover the shot.
SNAP = r'''func snap(_ name:String,_ w:NSWindow){w.sharingType = .readOnly;let p=Process();p.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture");p.arguments=["-x","-o","-l\(w.windowNumber)",out+"/"+name+".png"];try! p.run();p.waitUntilExit();print("shot \(name)")}
'''
SHOTS = SETUP[:SETUP.index('let (ow,ov)=page(')] + SNAP + r'''
let tall=min(1500,screen.visibleFrame.height-120)
let (sw,sv)=page("settings.html",NSSize(width:780,height:tall),"st")   // as SettingsWindow.open, taller to show whole sections
let scenes=try! JSONSerialization.jsonObject(with:Data(#"SCENES"#.utf8)) as! [[String]]
let pages=try! JSONSerialization.jsonObject(with:Data(#"OBPAGES"#.utf8)) as! [String]
let setup=#"const PREFS=PREFS_JSON,STATE=STATE_JSON,up=()=>document.querySelector('main').scrollTop=0,load=p=>{st.load({prefs:{...PREFS,...p},state:STATE,routines:ROUTINES_JSON});st.perms(PERMS_JSON);st.dictation(DICTATION_JSON)};"#
// Each pass switches the whole app's appearance with the pages already loaded, as System Settings does: no reload.
let looks:[(String,NSAppearance.Name)]=[("light",.aqua),("dark",.darkAqua)]
func settingsScene(_ i:Int,_ look:Int){
 if i==0{nsapp.appearance=NSAppearance(named:looks[look].1);sw.orderFrontRegardless();nsapp.activate(ignoringOtherApps:true);sw.makeKey();sw.makeFirstResponder(sv)}   // key, so keyboard focus shows
 guard i<scenes.count else{sw.orderOut(nil);onboardingScene(look);return}
 sv.evaluateJavaScript(scenes[i][1]){_,e in if let e{print("scene failed \(scenes[i][0]): \(e)");exit(1)}
  after(0.9){snap(scenes[i][0]+"-"+looks[look].0,sw);settingsScene(i+1,look)}}}
// Setup's permissions, the AI step with the custom server fields open, then each later step.
let (ow,ov)=page("onboarding.html",NSSize(width:640,height:640),"ob");ow.orderOut(nil)
func obReady(_ tries:Int,_ go:@escaping()->Void){ov.evaluateJavaScript("typeof ob"){v,_ in   // with no Settings scenes first, setup may still be loading
 if v as? String == "object"{go()}else if tries>60{print("setup page never loaded");exit(1)}else{after(0.5){obReady(tries+1,go)}}}}
func onboardingScene(_ look:Int){
 let name=looks[look].0;ow.orderFrontRegardless()
 obReady(0){ov.evaluateJavaScript("ob.prefs({draw:true,meeting:false,routing:'balanced',dictateMode:'verbatim',dictateHotkeyLabel:''});ob.plan({ok:true,client:'claude',text:'Signed in. Claude Max.'});ob.set({mic:true,speech:true,ax:true,screen:false,auto:true});document.querySelector('[data-to=perms]').click();if(document.querySelector('.page.on').id!=='perms')throw Error('wrong permission shot')"){_,_ in
  after(1.4){snap("setup-perms-"+name,ow)
   ov.evaluateJavaScript("document.querySelector('[data-to=\"ai\"]').click();document.querySelector('.opt[data-p=\"server\"]').click();ob.models(['qwen3','llama3.2'])"){_,_ in
    after(0.9){snap("setup-provider-"+name,ow)
     ov.evaluateJavaScript("document.querySelector('[data-to=\"perms\"]').click()"){_,_ in after(0.6){featurePage(0,look)}}}}}}}}
func featurePage(_ i:Int,_ look:Int){
 guard i<pages.count else{
  guard look+1<looks.count else{print("settings shots ok");exit(0)}
  ow.orderOut(nil);settingsScene(0,look+1);return}
 ov.evaluateJavaScript("document.querySelector('[data-to=\"\(pages[i])\"]').click()"){_,e in if let e{print("page failed \(pages[i]): \(e)");exit(1)}
  after(2.6){snap("setup-"+pages[i]+"-"+looks[look].0,ow);if pages[i]=="show"{frames(0,look){featurePage(i+1,look)}}else if pages[i]=="model"{opus(look){featurePage(i+1,look)}}else{featurePage(i+1,look)}}}}
// The work model step with the other card picked, then back to the default.
func opus(_ look:Int,_ done:@escaping()->Void){
 ov.evaluateJavaScript("document.querySelector('.mc[data-m=opus]').click()"){_,_ in
  after(0.6){snap("setup-model-opus-"+looks[look].0,ow);ov.evaluateJavaScript("document.querySelector('.mc[data-m=sonnet]').click()"){_,_ in done()}}}}
// Show me how's loop held at five moments: keys down and the mouse setting off, the loop half round, nearly closed, the resting dot, the answer.
let frameAt=[1100,1800,2500,3150,4700]
func frames(_ f:Int,_ look:Int,_ done:@escaping()->Void){
 guard f<frameAt.count else{ov.evaluateJavaScript("ob.showAt(null)"){_,_ in done()};return}
 ov.evaluateJavaScript("ob.showAt(\(frameAt[f]))"){_,_ in
  after(0.6){snap("setup-show-frame\(f+1)-"+looks[look].0,ow);frames(f+1,look,done)}}}
func ready(_ tries:Int){sv.evaluateJavaScript("typeof st"){v,_ in   // a busy VM can take a while to load the page
 guard v as? String == "object" else{if tries>60{print("settings page never loaded");exit(1)};after(0.5){ready(tries+1)};return}
 sv.evaluateJavaScript(setup+"load({});"){_,e in if let e{print("load failed: \(e)");exit(1)};settingsScene(0,0)}}}
after(1.0){ready(0)}
nsapp.run()'''

# The box's question cards side by side: a command approval, the calendar change, Long asks, and a plain offer.
EVENT = 'Dentist → Mon Oct 19, 4:00 PM – 5:00 PM · from Mon Oct 19, 3:00 PM – 4:00 PM · Home · this occurrence only'   # as atticus.calendar_tool words it
ASK = "ui.reset();ui.listen(true);ui.words(WORDS);ui.think();"
BOX = CARDS[:CARDS.index('let row=#"ROW"#')] + SNAP + r'''func fitted(_ name:String,_ done:@escaping()->Void){web.evaluateJavaScript("document.getElementById('card').getBoundingClientRect().height"){value,_ in
 let h=CGFloat((value as? Double) ?? 300);var f=box.frame;f.origin.y=f.maxY-h;f.size.height=h;box.setFrame(f,display:true);after(0.5){snap(name,box);done()}}}
let scenes=try! JSONSerialization.jsonObject(with:Data(#"BOXSCENES"#.utf8)) as! [[String]]
func play(_ i:Int){
 guard i<scenes.count else{print("box shots ok");exit(0)}
 web.evaluateJavaScript(scenes[i][1]){_,error in guard error == nil else{print("scene failed: \(scenes[i][0]): \(error!)");exit(1)};after(1.3){fitted(scenes[i][0]){play(i+1)}}}}
bridge.ready={after(1.0){play(0)}}
nsapp.run()'''
BOX_SCENES = [
    ('box-command', ASK.replace('WORDS', json.dumps('Delete the old notes on my desktop')) + "ui.ask(['Delete this file?','rm ~/Desktop/old-notes.txt','','',''])"),
    ('box-calendar', ASK.replace('WORDS', json.dumps('Move my dentist appointment to 4')) + f"ui.ask(['Move this event?',{json.dumps(EVENT)},'','',''])"),
    ('box-move', ASK.replace('WORDS', json.dumps('Research the best standing desks under $600')) + "ui.line('Searching the web: standing desks under 600');ui.movePending();"),
    ('box-improve', "ui.reset();ui.listen(true);ui.words('Open Notes');ui.think();ui.msg('Opened Notes.');ui.improve();"),
]


class SettingsShots(unittest.TestCase):
    def shots(self, name, body, marker):
        out = ROOT / 'test-artifacts' / 'design' / 'settings'; out.mkdir(parents=True, exist_ok=True)
        run_fixture(self, body.replace('OUTDIR', str(out)), marker)
        for png in sorted(out.glob('*.png')): print('PNG', png.name, base64.b64encode(png.read_bytes()).decode(), flush=True)

    def page_shots(self, scenes, pages):
        self.shots('settings', SHOTS.replace('SCENES', json.dumps(scenes)).replace('OBPAGES', json.dumps(pages)).replace('PREFS_JSON', json.dumps(PREFS))
                   .replace('STATE_JSON', json.dumps(STATE)).replace('PERMS_JSON', json.dumps(PERMS))
                   .replace('ROUTINES_JSON', json.dumps(ROUTINES)).replace('DICTATION_JSON', json.dumps(DICTATION)), 'settings shots ok')

    def test_ask_history(self):
        state = {**STATE, 'asks': [
            {'at': '2026-11-24 09:32:00', 'task': 'Add a shaded bed\nInclude mint and ferns.', 'reply': '', 'status': 'cancelled'},
            {'at': '2026-11-24 09:31:00', 'task': 'Try a smaller bed', 'reply': 'The plan could not be saved.\nYour existing plan is unchanged.', 'status': 'failed'},
            {'at': '2026-11-24 09:30:00', 'task': 'Plan a garden for a small courtyard.\nUse containers and leave room for a table.',
             'reply': '1. Put herbs in pots near the door.\n2. Keep the center clear for a table.\n3. Place taller plants along the back wall.\n\nWater containers when the top layer of soil is dry.', 'status': 'completed'}]}
        scenes = [
            ('history-closed', 'st.state(' + json.dumps(state) + ");st.tab('usage');document.querySelector('#asklist').scrollIntoView({block:'center'})"),
            ('history-open', "document.querySelectorAll('#asklist summary')[2].click();document.querySelectorAll('#asklist .x.copy')[2].focus({preventScroll:true})"),
            ('history-stopped', "document.querySelectorAll('#asklist summary')[2].click();document.querySelector('#asklist summary').click()")]
        scenes = [(name, js + ";setTimeout(()=>document.querySelector('#askq').scrollIntoView({block:'start',behavior:'instant'}),300)") for name, js in scenes]
        body = SHOTS.replace('sw.orderOut(nil);onboardingScene(look);return',
            'if look+1<looks.count{settingsScene(0,look+1)}else{print("settings shots ok");exit(0)};return')
        self.shots('history', body.replace('SCENES', json.dumps(scenes)).replace('OBPAGES', '[]').replace('PREFS_JSON', json.dumps(PREFS))
                   .replace('STATE_JSON', json.dumps(state)).replace('PERMS_JSON', json.dumps(PERMS))
                   .replace('ROUTINES_JSON', '[]').replace('DICTATION_JSON', json.dumps(DICTATION)), 'settings shots ok')

    def test_settings_and_setup(self):
        self.page_shots(SCENES, [])

    def test_setup_feature_pages(self):   # its own run: two appearances of every page would pass the fixture's time limit
        self.page_shots([], SETUP_PAGES)

    def test_box_cards(self):
        self.shots('box', BOX.replace('BOXSCENES', json.dumps(BOX_SCENES)), 'box shots ok')


if __name__ == '__main__':
    unittest.main()
