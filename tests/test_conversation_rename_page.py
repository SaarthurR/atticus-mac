"""Real WKWebView conversation rename controls; run only through the VM runner."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_shelf_page import HARNESS, ROOT

SCRIPT = r'''
const tick = () => new Promise(r => setTimeout(r, 50)), now = Date.now()/1000;
const rows = ['a','b'].map(id => ({id:id.repeat(32),title:'Original '+id,status:'done',created:now,ended:now,summary:'Saved answer'}));
const rename = () => document.querySelector('#tools .rename').click();
const input = () => document.querySelector('#title input');
const key = (value, more={}) => input().dispatchEvent(new KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true,...more}));
const click = text => [...document.querySelectorAll('#title button')].find(b=>b.textContent===text).click();
agents.mode('view'); agents.list(rows); agents.select(rows[0].id); rename(); await tick();
const out = {focused:document.activeElement===input(), selected:input().selectionEnd===rows[0].title.length};
const header=document.querySelector('header').getBoundingClientRect();
out.fits=[input(),...document.querySelectorAll('#title button')].every(n=>{const r=n.getBoundingClientRect();return r.width>0&&r.left>=header.left&&r.right<=header.right;});
input().value='Draft'; agents.state({...rows[0],status:'running',step:'Working'}); await tick();
out.draft=input().value;
key('Escape'); await tick(); out.cancelled=!input(); out.focusReturned=document.activeElement===document.querySelector('#tools .rename');
rename(); await tick(); input().value='  '; key('Enter'); out.blankStays=!!input();
input().value='旅行 <notes> & “plans”'; key('Enter',{isComposing:true}); out.composingStays=!!input();
key('Enter'); await tick(); out.saved=!input();
agents.state({...rows[0],title:'旅行 <notes> & “plans”'}); await tick();
out.title=document.querySelector('#title').textContent;
out.sidebar=document.querySelector('.item[data-id="'+rows[0].id+'"] b').textContent;
out.noMarkup=!document.querySelector('#title notes');
// Same-status selection must rebind the toolbar to the second conversation.
agents.select(rows[1].id); rename(); await tick(); input().value='Second name'; click('Save'); await tick();
rename(); await tick(); input().value='Discard me'; click('Cancel'); await tick();
out.buttonCancel=!input();
agents.mode('shelf'); agents.prefs({stack:'open'}); agents.list([{...rows[0],title:out.title,status:'running'}]); await tick();
out.shelf=document.querySelector('.chip .title').textContent;
return out;
'''


CHAT_SCRIPT = r'''
const tick = () => new Promise(r => setTimeout(r, 50)), now = Date.now()/1000;
const chat = {id:'c'.repeat(32),title:'Daily talk',created:now,turns:[{t:now,q:'<img src=x onerror=alert(1)>',a:'A [source](https://example.com/chat).'}]};
const agent = {id:'a'.repeat(32),title:'Agent task',status:'done',created:now,ended:now,summary:'Done'};
const shows=id=>!!document.querySelector('#list .item[data-id="'+id+'"]'),pressed=()=>document.querySelector('#tabs [aria-pressed="true"]').textContent,foot=()=>document.querySelector('#aside-foot').hidden;
agents.mode('view');agents.list([agent]);agents.chats([chat]);agents.select(chat.id);await tick();
const out={chatsTab:!document.querySelector('#tabs').hidden&&pressed()==='Chats'&&shows(chat.id)&&!shows(agent.id)&&foot()};
document.querySelector('#tabs [data-v=""]').click();await tick();
out.agentsTab=pressed()==='Agents'&&shows(agent.id)&&!shows(chat.id)&&!foot();
agents.prefs({tab:'chats'});out.remembered=pressed()==='Chats'&&shows(chat.id);
Object.assign(out,{literal:document.querySelector('.entry.user .line span').textContent===chat.turns[0].q,
 noMarkup:!document.querySelector('#body img'),disabled:document.querySelector('#followup').disabled&&document.querySelector('#send').disabled});
document.querySelector('#body a').click();
document.querySelector('#tools .rename').click();await tick();
document.querySelector('#title input').value='  Renamed chat  ';
document.querySelector('#title input').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
agents.chats([{...chat,title:'Renamed chat'}]);await tick();
out.title=document.querySelector('#title').textContent;
out.sidebar=document.querySelector('.item[data-id="'+chat.id+'"] b').textContent;
agents.select(agent.id);out.enabled=!document.querySelector('#followup').disabled&&!document.querySelector('#send').disabled;
agents.prefs({tab:'chats'});agents.chats([]);await tick();out.noTabs=document.querySelector('#tabs').hidden&&shows(agent.id)&&!foot();
agents.list([]);agents.mode('shelf');await tick();out.noShelf=!document.querySelector('.chip');
return out;
'''


@unittest.skipUnless(sys.platform == 'darwin', 'macOS WebKit page check')
class ConversationRenamePageTests(unittest.TestCase):
    def run_page(self, script):
        with tempfile.TemporaryDirectory() as tmp:
            page, src, binary = Path(tmp)/'agents.html', Path(tmp)/'page.swift', Path(tmp)/'page'
            page.write_text((ROOT/'ui/agents.html').read_text().replace('/*TOKENS*/', (ROOT / 'ui/tokens.css').read_text()).replace('/*ORBS*/', (ROOT/'ui/orbs.js').read_text()))
            src.write_text(HARNESS.replace('width: 260, height: 400', 'width: 660, height: 580'))
            built = subprocess.run(['swiftc', str(src), '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            run = subprocess.run([str(binary), str(page), script], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        got = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual([p for p in got['posts'] if 'error' in p], [])
        return got

    def test_chats_share_rename_and_stay_off_the_shelf(self):
        got = self.run_page(CHAT_SCRIPT)
        for field in ('chatsTab','agentsTab','remembered','literal','noMarkup','disabled','enabled','noTabs','noShelf'):
            self.assertTrue(got['result'][field], field)
        self.assertIn({'action':'tab','value':''}, got['posts'])
        for field in ('title','sidebar'):
            self.assertEqual(got['result'][field], 'Renamed chat')
        self.assertIn({'action':'rename','id':'c'*32,'title':'Renamed chat'}, got['posts'])
        self.assertIn({'action':'open','id':'c'*32,'target':'https://example.com/chat'}, got['posts'])

    def test_rename_keyboard_buttons_live_updates_and_selected_identity(self):
        got = self.run_page(SCRIPT)
        posts = [p for p in got['posts'] if p.get('action') == 'rename']
        self.assertEqual(posts, [{'action':'rename','id':'a'*32,'title':'旅行 <notes> & “plans”'},
                                 {'action':'rename','id':'b'*32,'title':'Second name'}])
        out = got['result']
        for field in ('focused','selected','fits','cancelled','focusReturned','blankStays','composingStays','saved','noMarkup','buttonCancel'):
            self.assertTrue(out[field], field)
        self.assertEqual(out['draft'], 'Draft')
        for field in ('title','sidebar','shelf'):
            self.assertEqual(out[field], '旅行 <notes> & “plans”', field)
