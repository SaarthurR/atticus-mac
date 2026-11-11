"""Regressions from the 1.3.2 UI review; source and Node checks only, no windows."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


def node(test, script):
    if not shutil.which('node'):
        test.skipTest('Node runs the overlay checks')
    result = subprocess.run(['node', '--input-type=module'], input=script, capture_output=True, text=True)
    test.assertEqual(result.returncode, 0, result.stderr)


def contrast(fg, bg):
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in c]
        return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]
    a, b = lum(fg), lum(bg)
    return (max(a, b) + .05) / (min(a, b) + .05)


def tint(color, alpha, bg='#ffffff'):
    return '#' + ''.join('%02x' % round(alpha * int(color[i:i + 2], 16) + (1 - alpha) * int(bg[i:i + 2], 16)) for i in (1, 3, 5))


class UIReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.swift = (ROOT / 'Atticus.swift').read_text()
        self.box = (ROOT / 'ui/ui.html').read_text()
        self.settings = (ROOT / 'ui/settings.html').read_text()
        self.onboarding = (ROOT / 'ui/onboarding.html').read_text()
        self.agents = (ROOT / 'ui/agents.html').read_text()
        self.meeting = (ROOT / 'ui/meeting.html').read_text()

    def test_native_clicks_reach_try_again_the_agents_pill_and_pill_buttons(self):
        tap = self.box[self.box.index('    tap([x, y])'):self.box.index('    size(h)')]
        node(self, r'''let clicked = '';
const make = key => { const el = { closest: s => s.split(', ').includes(key) ? el : null, click() { clicked = key; } }; return el; };
let folded = false, dictating = false;
const document = { elementFromPoint: () => current, body: { classList: { contains: c => c === 'dictate' && dictating } } }; let current;
const $ = () => ({ classList: { contains: () => false }, value: '' }), drop = () => { clicked = 'typing'; }, comp = () => { clicked = 'typing box'; }, post = () => {}, status = () => {}, fit = () => {};
const ui = {''' + tap + r'''};
for (const key of ['.redo', '#agents-pill', '.dn button']) { current = make(key); clicked = ''; ui.tap([0, 0]); if (clicked !== key) { console.error(key + ' opened the ' + clicked); process.exit(1); } }
dictating = true; current = make('.dn'); clicked = ''; ui.tap([0, 0]); if (clicked) { console.error('a click on the dictation pill opened the ' + clicked); process.exit(1); }
''')

    def test_typing_row_animates_everything_it_changes(self):
        # Oct 20, 2026: the open row's -4px side margins jumped while its 4px padding animated, so the field and buttons slid
        closed = re.search(r'  #comp \{([^}]*)\}', self.box).group(1)
        opened = re.search(r'  #comp\.open \{([^}]*)\}', self.box).group(1)
        animated = {p.split()[0] for p in re.search(r'transition: ([^;]*);', closed).group(1).split(',')}
        for prop in re.findall(r'([a-z-]+):', opened):
            self.assertIn(prop, animated)

    def test_choice_number_shortcuts_work_from_the_empty_composer(self):
        handler = self.box[self.box.index("  $('ask').onkeydown = e => {"):self.box.index('  // the model row:')]
        node(self, r'''let picked = 0, clicked = 0, prevented = false;
const choices = Array.from({length: 3}, (_, i) => ({choose() { picked = i + 1; }, click() { clicked++; }, focus() {}}));
const ask = {value: ''}, thread = {querySelector: () => null, querySelectorAll: () => choices};
const $ = id => id === 'ask' ? ask : thread, part = () => null, status = () => {}, post = () => {};
const window = {ui: {respond: () => false}}; let listening = false, working = false;
''' + handler + r'''
const key = value => ask.onkeydown({key: value, target: ask, isComposing: false, metaKey: false, ctrlKey: false, altKey: false, preventDefault() { prevented = true; }});
key('2'); if (picked !== 2 || clicked || !prevented) process.exit(1);
picked = 0; prevented = false; ask.value = 'version '; key('2'); if (picked || prevented) process.exit(2);
''')
        self.assertIn('c.choose = () => done(i)', self.box)
        self.assertIn('cs[e.key - 1].choose()', self.box)

    def test_question_choices_wrap_inside_narrow_cards(self):
        rule = re.search(r'\.pk \.actions button \{([^}]*)\}', self.agents)
        self.assertIsNotNone(rule)
        for declaration in ('white-space:normal', 'overflow-wrap:anywhere', 'min-width:0',
                            'max-width:100%', 'height:auto', 'min-height:26px'):
            self.assertIn(declaration, rule.group(1))
        self.assertRegex(self.agents, r'\.inside \.pk \.actions \{[^}]*grid-template-columns:repeat\(2,minmax\(0,1fr\)\)')
        # The box picker already wraps list labels and exposes the full label on hover.
        self.assertRegex(self.box, r'\.pk \.g\.list \.n \{[^}]*white-space: normal;[^}]*overflow-wrap: anywhere;')
        self.assertIn("c.title = o.path ? o.path + '/' + o.label : o.label", self.box)

    def test_full_access_badge_is_a_keyboard_control(self):
        self.assertIn('id="mode" role="button" tabindex="0"', self.box)
        self.assertIn('#mode:focus-visible', self.box)
        self.assertIn("$('mode').onclick = enableSafeMode", self.box)
        self.assertIn("if (e.key === 'Enter' || e.key === ' ')", self.box)
        self.assertIn("if (el?.closest('#mode')) return enableSafeMode()", self.box)

    def test_failed_dictation_offers_its_words_to_copy(self):
        dictated = self.box[self.box.index('    dictated({'):self.box.index('    learned(word)')]
        node(self, r'''let sent, button;
const fit = () => {}, setState = () => {}, $ = () => ({ style: {} }), post = m => { sent = m; };
let listening = true, boost = 1;
const document = { body: { classList: { remove() {} } }, createElement: () => ({}) }, pill = () => ({ append: (...a) => { button = a[1]; } });
const ui = {''' + dictated + r'''};
ui.dictated({ text: 'Nothing selected to insert — saved to History.', ok: false }); if (button) process.exit(1);
ui.dictated({ text: 'Couldn’t insert. Your words are still here.', ok: false, words: 'my words' }); button.onclick();
if (sent?.copy !== 'my words' || button.textContent !== 'Copied') process.exit(1);
ui.dictated({ text: 'Couldn’t insert. Press ⌃⌘V to paste it.', ok: false, history: true }); button.onclick();
if (sent?.dictationHistory !== true || button.textContent !== 'History') process.exit(1);
''')

    def test_agent_start_releases_an_empty_typed_composer_for_the_fade(self):
        started = self.box[self.box.index('    agentStarted(row)'):self.box.index('    agentSteered(row)')]
        self.assertIn("if(!$('ask').value)comp(false)", started)

    def test_learned_word_shows_in_the_pill_after_it_folded(self):
        self.assertIn('learnedWord = word; pill(true); show(); js("learned", word)', self.swift)

    def test_reduce_motion_stops_onboarding_loops(self):
        rule = re.search(r'@media \(prefers-reduced-motion: reduce\) \{ \*, \*::before, \*::after \{(.*?)\}', self.onboarding).group(1)
        self.assertIn('animation-iteration-count: 1 !important', rule)
        self.assertIn("const reduced = matchMedia('(prefers-reduced-motion: reduce)')", self.onboarding)
        self.assertIn("reduced.addEventListener('change'", self.onboarding)
        self.assertIn('welcomeGeneration++; previewGeneration++;', self.onboarding)
        self.assertIn('Object.keys(loops).forEach(id => finals[id]())', self.onboarding)
        self.assertIn('if (reduced.matches) { finals[id](); await motionChange(); }', self.onboarding)
        self.assertNotIn("const still = matchMedia('(prefers-reduced-motion: reduce)').matches", self.onboarding)

    def test_onboarding_welcome_orb_keeps_animating(self):
        start = self.onboarding.index("    const cv = $('orb')")
        loop = self.onboarding[start:self.onboarding.index('})(prev);', start) + len('})(prev);')]
        node(self, r'''const run = (isReduced, page) => { let frames = 0, timers = 0, painted = 0;
const canvas2d = { setTransform() {}, clearRect() {} }, $ = () => ({ getContext: () => canvas2d }), E = { r: () => ({ mode: 'm', speed: 1, opts: {} }), M: { m: () => ({}) }, p: () => painted++ };
globalThis.requestAnimationFrame = () => frames++; globalThis.setTimeout = () => timers++;
let reduced = { matches: isReduced }, cur = page, orbWake = null;
''' + loop + r'''
return {frames, timers, painted, waiting: typeof orbWake === 'function'}; };
const active = run(false, 'welcome'), still = run(true, 'welcome'), away = run(false, 'text');
if (active.painted !== 1 || active.frames !== 1 || active.timers || active.waiting) process.exit(1);
if (still.painted !== 1 || still.frames || still.timers || !still.waiting) process.exit(2);
if (away.frames || away.timers || !away.waiting) process.exit(3);
''')

    def test_settings_and_agents_text_colours_are_readable(self):
        light = re.search(r':root \{(.*?)\}', self.settings, re.S).group(1)
        dark = re.search(r'prefers-color-scheme: dark\) \{ :root \{(.*?)\}', self.settings, re.S).group(1)
        var = lambda block, name: re.search(r'--' + name + r': (#[0-9a-f]{6})', block).group(1)
        for name in ('fg3', 'warn', 'danger'):
            self.assertGreaterEqual(contrast(var(light, name), '#f5f5f7' if name == 'fg3' else '#ffffff'), 4.5, name)
        for name in ('fg3', 'warn'):
            self.assertGreaterEqual(contrast(var(dark, name), '#2a2a2c'), 4.5, 'dark ' + name)
        self.assertGreaterEqual(contrast(var(light, 'ok-text'), tint('#34c759', .13)), 4.5)
        self.assertGreaterEqual(contrast(var(light, 'warn'), tint('#ff9f0a', .14)), 4.5)
        self.assertNotRegex(self.settings, r'\{[^}]*\bcolor: #ff(9f0a|453a)')   # text uses the tokens; fills may keep the bright colours
        self.assertGreaterEqual(contrast(re.search(r'--fg3:(#[0-9a-f]{6})', self.agents).group(1), '#1e1e22'), 4.5)
        setup_light = re.search(r':root \{(.*?)\}', self.onboarding, re.S).group(1)
        setup_dark = re.search(r'prefers-color-scheme: dark\) \{ :root \{(.*?)\}', self.onboarding, re.S).group(1)
        self.assertGreaterEqual(contrast(var(setup_light, 'fg3'), '#fbfbfd'), 4.5)
        self.assertGreaterEqual(contrast(var(setup_dark, 'fg3'), '#2a2a2c'), 4.5)
        self.assertGreaterEqual(contrast(re.search(r'--fg3:(#[0-9a-f]{6})', self.meeting).group(1), '#1e1e20'), 4.5)

    def test_settings_exposes_the_current_page_and_app_list_choice(self):
        self.assertIn('class="on" aria-current="page"', self.settings)
        self.assertIn("b.toggleAttribute('aria-current', b === nav)", self.settings)
        self.assertIn('id="appview" role="group" aria-label="App list"', self.settings)
        self.assertIn("b.setAttribute('aria-pressed', on)", self.settings)

    def test_meetings_row_offers_turn_on_instead_of_dead_buttons(self):
        self.assertIn("$('meetingDemo').hidden = $('meetingPrepOpen').hidden = !P.meeting; $('meetingOn').hidden = !!P.meeting;", self.settings)
        self.assertIn("$('meetingOn').onclick = () => set('meeting', true);", self.settings)

    def test_onboarding_recorder_names_a_lone_modifier(self):
        self.assertIn('a modifier on its own', self.onboarding)
        self.assertNotIn('Use modifiers with a key', self.onboarding)

    def test_turned_off_tips_come_back_from_the_menu_bar(self):
        menu = self.swift[self.swift.index('final class MenuBar'):self.swift.index('// Settings window (ui/settings.html)')]
        self.assertIn('if !Prefs.bool("tips") { add(help, "Show Tips Again", #selector(tipsOn), "", "lightbulb") }', menu)
        self.assertIn('add(m, "Help & Feedback", nil, "", "questionmark.circle").submenu = help', menu)
        self.assertIn('@objc func tipsOn() { settings.apply("tips", true); settings.push() }', menu)

    def test_removed_sonnet_offer_leaves_no_card_branch(self):
        self.assertNotIn('Sonnet', self.box[self.box.index('    respond(text)'):self.box.index('    improve()')])
        self.assertNotIn('"escalate"', self.swift[self.swift.index('func userContentController'):self.swift.index('    func show()')])
        self.assertNotIn("j.get('off'", (ROOT / 'atticus.py').read_text())

    def test_agent_cost_reads_like_usage(self):
        script = ''
        for page in (self.box, self.agents):
            line = re.search(r'const apiCost=.*?;', page).group(0)
            script += '{' + line + r'''
if (apiCost(.0412) !== '≈4.12¢ at API prices' || apiCost(.1861) !== '≈18.6¢ at API prices' || apiCost(2.5) !== '≈$2.50 at API prices') process.exit(1); }
'''
        node(self, script)
        self.assertNotIn('Plan usage', self.box + self.agents)

    def test_box_card_screenshots_define_the_agents_panel(self):
        self.assertTrue((ROOT / 'tests/shoot_agents_design.py').read_text().split("CARDS = r'''", 1)[1].startswith('let agentsUI=AgentPanels()\n'))

    def test_usage_history_shows_a_readable_date(self):
        self.assertNotIn('a.at.slice(5, 16)', self.settings)
        self.assertIn("new Date(a.at.replace(' ', 'T')).toLocaleString(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'})", self.settings)

    def test_usage_splits_asks_from_agents_in_unambiguous_dollars(self):
        self.assertIn("const money = u => '$' + u.toFixed(u < .01 ? 4 : 2);", self.settings)
        self.assertIn('${u.asks} asks ${money(u.askUsd ?? u.usd)} · ${u.agentCalls || 0} agent calls ${money(u.agentUsd || 0)}', self.settings)

    def test_a_new_ask_drops_a_paused_card_left_by_resuming_elsewhere(self):
        listen = self.box[self.box.index('    listen(mode)'):self.box.index('    level(v)')]
        self.assertIn("querySelectorAll('.rewrite, .paused, .worker').forEach(e => e.remove())", listen)

    def test_rewrite_buttons_answer_hover_and_press_like_card_buttons(self):
        self.assertIn('.rewrite button:not(:disabled):is(:hover,.hot) { transform: scale(1.03); }', self.box)
        self.assertIn('.rewrite button:not(:disabled):active { transform: scale(.96); }', self.box)

    def test_box_status_markers_share_compact_centered_rows(self):
        self.assertRegex(self.box, r'\.a\.stopped \{[^}]*align-items: center;[^}]*line-height: 16px;')
        self.assertRegex(self.box, r'\.a\.stopped i \{ flex: none; width: 7px; height: 7px;')
        self.assertRegex(self.box, r'\.step \{[^}]*line-height: 16px;[^}]*align-items: center;')
        self.assertIn('#agents-pill i { flex:none;', self.box)
        self.assertRegex(self.box, r'\.agent-card \.eyebrow \{[^}]*align-items:center;[^}]*line-height:14px;')
        self.assertIn('.agent-card .eyebrow i { flex:none;', self.box)

    def test_agent_start_line_sits_beside_its_orb(self):
        self.assertIn('.a:is(.stopped, .agent-ack) > :not(.w) + :not(.w) { margin-top: 0; }', self.box)

    def test_agent_card_can_fold_away(self):
        self.assertIn('.agent-card { max-height:900px; }', self.box)
        self.assertNotIn('.agent-card { max-height:none; }', self.box)

    def test_agent_card_fits_a_short_box(self):
        card = self.box[self.box.index('  const agentCard=row=>'):self.box.index("  $('agents-pill').onclick")]
        fit = card[card.index('    const over='):card.index('    answer.onscroll();')]
        self.assertIn('answer.tabIndex=0', card)
        node(self, r'''const getComputedStyle = () => ({maxHeight: '420px'}), $ = () => ({});
for (const [cardH, want] of [[540, '126px'], [300, undefined], [900, '60px']]) {
  const d = {offsetHeight: cardH}, answer = {clientHeight: 260, style: {}};
''' + fit + r'''
  if (answer.style.maxHeight !== want) { console.error(cardH, answer.style.maxHeight); process.exit(1); }
}
''')

    def test_rewrite_actions_sit_above_the_timer_with_one_try_again(self):
        self.assertIn('.turn:has(.rewrite) .redo { display: none; }', self.box)
        rewrite = self.box[self.box.index('    rewrite([draft, mode, editable])'):self.box.index('    mini(m)')]
        node(self, r'''let placed = '';
const clockRow = { before: () => { placed = 'above the timer'; } }, d = { querySelector: s => s === '.elapsed' ? clockRow : null, append: () => { placed = 'last'; } };
const turn = () => d, part = () => null, post = () => {}, fit = () => {}, $ = () => ({ querySelectorAll: () => [] });
const document = { createElement: () => ({ dataset: {}, append() {}, setAttribute() {} }) };
const ui = {''' + rewrite + r'''};
ui.rewrite(['Hi Dana,', 'draft', true]); if (placed !== 'above the timer') { console.error(placed); process.exit(1); }
''')

    def test_resize_releases_fixed_height_and_uses_live_box_spacing(self):
        methods = self.box[self.box.index('    hold(h)'):self.box.index('    respond(text)')]
        self.assertIn('const chrome = c.offsetHeight - t.offsetHeight', methods)
        self.assertNotIn('h - 26', methods)
        node(self, r'''const classes = new Set(), card = {offsetHeight: 246, style: {minHeight: '', getPropertyValue: () => '700'}, classList: {add: x => classes.add(x), remove: x => classes.delete(x)}};
const thread = {offsetHeight: 120, style: {}}, nodes = {card, thread}, $ = id => nodes[id], sent = [], post = x => sent.push(x);
let fitted = 0; const fit = () => fitted++;
const ui = {''' + methods + r'''};
ui.hold(500);
if (!classes.has('held') || card.style.minHeight !== '500px' || thread.style.maxHeight !== '374px' || sent[0].boxH !== 374) process.exit(1);
ui.resizeDone();
if (classes.has('held') || card.style.minHeight || fitted !== 2) process.exit(2);
''')
        mouse_up = self.swift[self.swift.index('            default:', self.swift.index('var sizing:')):self.swift.index('            return nil', self.swift.index('            default:', self.swift.index('var sizing:')))]
        self.assertIn('js("resizeDone")', mouse_up)

    def test_settings_disabled_segment_looks_off_and_usage_cards_fill_rows(self):
        self.assertIn("[data-k=dictateMode] [data-v=cleanup]').disabled = other", self.settings)
        self.assertIn('.seg button:disabled { opacity: .4; pointer-events: none; }', self.settings)
        self.assertIn('.seg button:disabled { opacity: .4; pointer-events: none; }', self.onboarding)
        self.assertIn('grid-template-columns: repeat(6, 1fr)', self.settings)
        self.assertIn('.stat { grid-column: span 2; } .stat:nth-child(n+4) { grid-column: span 3; }', self.settings)

    def test_small_leftovers(self):
        self.assertIn("moveFailed(){status('Could not move');", self.box)   # a failure, not live work
        self.assertNotIn('js("shortcut"', self.swift)
        self.assertNotIn('shortcut() {}', self.box)
        self.assertIn('d.hidden = skip(pages[i])', self.onboarding)   # Devin/Pi: no dots for skipped pages
        self.assertNotIn('These need your click', self.onboarding)
        self.assertNotIn('Use Verbatim instead', self.onboarding)
        self.assertIn('id="appsback" onclick="st.tab(\'account\')"', self.settings)
        self.assertEqual(self.settings.count('[hidden] {'), 1)
        self.assertNotIn('.ok:hover code', self.box)


if __name__ == '__main__':
    unittest.main()
