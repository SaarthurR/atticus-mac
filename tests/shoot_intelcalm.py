"""Opt-in VM WebKit shots: Models in every mode, light and dark.

Run via run.sh <worktree> tests.shoot_intelcalm; PNGs are printed as base64.
"""
import unittest
from tests import shoot_settings


class IntelligenceShots(unittest.TestCase):
    shots = shoot_settings.SettingsShots.shots
    page_shots = shoot_settings.SettingsShots.page_shots

    def test_models(self):
        self.page_shots([
            ('intelcalm-' + mode,
             "load({routing:'" + mode + "'});st.tab('brain');up()")
            for mode in ('cheapest', 'balanced', 'capable')
        ], [])
