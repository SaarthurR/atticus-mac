"""Opt-in real WebKit lifecycle captures, light/dark backdrops; VM only."""
import os
import unittest
from tests import shoot_boxlook as box


@unittest.skipUnless(os.environ.get('ATTICUS_VM'), 'VM only')
class AutoMiniboxShots(box.BoxLook):
    test_measure_glass = None

    def test_shots(self):
        start = "ui.listen();ui.words('Explain how plants use sunlight');"
        box.SCENES = [(f'{phase}-{look}', look, start + action,
                       ("document.body.classList.contains('folded') === " + str(phase == 'working').lower() + " ? 'ok lifecycle' : 'bad fold state'"))
                      for look in ('light', 'dark')
                      for phase, action in [('talking', ''), ('working', 'ui.think();'),
                                            ('streaming', "ui.think();ui.line('… Plants turn sunlight into chemical energy. The leaves capture light and');")]]
        self.run_box('shots', 'box shots ok')
