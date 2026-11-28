"""Opt-in real WebKit capture of the 2.1.0 update notice, light/dark backdrops; VM only."""
import os
import unittest
from tests import shoot_boxlook as box


@unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'VM only')
class UpdateNoticeShots(box.BoxLook):
    test_measure_glass = None

    def test_shots(self):
        show = box.ask('What time is it in Tokyo?', 'It’s 5:14 AM in Tokyo.') + "ui.updated('2.1.0');"
        box.SCENES = [(f'update-notice-{look}', look, show,
                       "!document.getElementById('updated-box').hidden ? 'ok notice' : 'bad notice'") for look in ('light', 'dark')]
        self.run_box('shots', 'box shots ok')
