"""Opt-in VM WebKit screenshots for an ask waiting without answer tokens."""
import unittest

from tests import shoot_boxlook


class StallLook(unittest.TestCase):
    def test_waiting_light_and_dark(self):
        old = shoot_boxlook.SCENES
        old_swift = shoot_boxlook.SWIFT
        shoot_boxlook.SWIFT = old_swift.replace('panel.level = .floating', 'panel.level = .screenSaver')
        native = (shoot_boxlook.ROOT / 'Atticus.swift').read_text()
        release = native.split('else if offerText == nil { js("think"); ', 1)[1].split(' }', 1)[0]
        waiting = native.split('if !speculative { js("think"); ', 1)[1].split(' }', 1)[0]
        # Use the actual native bridge calls, translated literally to page calls.
        def page_call(call):
            return 'ui.' + call.removeprefix('js(').replace('"line", ', 'line(') + ';'
        release_call, waiting_call = page_call(release), page_call(waiting)
        shoot_boxlook.SCENES = []
        for look in ('light', 'dark'):
            script = "ui.listen();ui.words('Can you teach me how to use orca');ui.think();"
            script += release_call + 'ui.tail(true);'
            script += "if(document.getElementById('status').textContent!=='Confirming your words…')throw Error('missing speech wait');"
            script += 'ui.tail(false);ui.think();' + waiting_call
            check = "document.getElementById('status').textContent==='Waiting for the answer…' && !document.querySelector('.a').textContent.trim() ? 'ok visible wait without answer' : 'bad wait'"
            shoot_boxlook.SCENES.append(('stall-' + look, look, script, check))
        try:
            shoot_boxlook.BoxLook.run_box(self, 'shots', 'box shots ok')
        finally:
            shoot_boxlook.SCENES = old
            shoot_boxlook.SWIFT = old_swift
