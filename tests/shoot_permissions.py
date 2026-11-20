"""Opt-in real WebKit setup and refused-permission screenshots, VM only."""
import unittest
from tests import shoot_boxlook
from tests.shoot_agents_design import SETUP
from tests import shoot_settings

SETUP_SHOTS = SETUP[:SETUP.index('let (ow,ov)=page(')] + shoot_settings.SNAP + r'''
let (ow,ov)=page("onboarding.html",NSSize(width:640,height:640),"ob")
let looks:[(String,NSAppearance.Name)]=[("light",.aqua),("dark",.darkAqua)]
func play(_ i:Int){
 guard i<looks.count else {print("permission setup shots ok");exit(0)}
 nsapp.appearance=NSAppearance(named:looks[i].1)
 ov.evaluateJavaScript("ob.plan({ok:true,client:'claude',text:'Ready'});ob.set({mic:false,speech:false,ax:false,screen:false,auto:false,chrome:false});document.querySelector('[data-to=perms]').click();document.querySelectorAll('#list .row').length===5 && document.getElementById('p-ax')!==null"){value,error in
  guard value as? Bool == true,error == nil else {print("wrong setup permissions");exit(1)}
  after(0.7){snap("setup-permissions-"+looks[i].0,ow);play(i+1)}}
}
func ready(_ n:Int){ov.evaluateJavaScript("typeof ob"){v,_ in
 if v as? String == "object" {play(0)}
 else if n<60 {after(0.2){ready(n+1)}} else {print("setup did not load");exit(1)}
}}
after(0.5){ready(0)}
nsapp.run()
'''


class PermissionShots(unittest.TestCase):
    def test_setup_light_dark(self):
        shoot_settings.SettingsShots.shots(self, 'permissions', SETUP_SHOTS, 'permission setup shots ok')

    def test_missing_line_light_dark(self):
        old, old_swift = shoot_boxlook.SCENES, shoot_boxlook.SWIFT
        # Capture this window only: an unrelated guest consent dialog must not cover the evidence.
        shoot_boxlook.SWIFT = old_swift.replace(
            r'p.arguments=["-x","-R\(Int(f.minX)),\(Int(top-f.maxY)),\(Int(f.width)),\(Int(f.height))",path]',
            r'p.arguments=["-x","-o","-l\(panel.windowNumber)",path]')
        self.assertNotEqual(shoot_boxlook.SWIFT, old_swift)
        shoot_boxlook.SCENES = []
        for look in ('light', 'dark'):
            script = "ui.reset();ui.permission('Allow Speech Recognition for Atticus to listen to you.');"
            check = "document.querySelector('.permission b').textContent==='Allow Speech Recognition for Atticus to listen to you.' && !document.querySelector('.permission button').hidden ? 'ok missing permission and Settings' : 'bad missing permission'"
            shoot_boxlook.SCENES.append(('missing-permission-' + look, look, script, check))
        try:
            shoot_boxlook.BoxLook.run_box(self, 'shots', 'box shots ok')
        finally:
            shoot_boxlook.SCENES, shoot_boxlook.SWIFT = old, old_swift
