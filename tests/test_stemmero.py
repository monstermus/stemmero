import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import stemmero


class ConfigTests(unittest.TestCase):
    def load(self, content):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(content, encoding='utf-8')
            with patch.object(stemmero, 'CONFIG_PATH', str(path)):
                return stemmero.load_config()

    def test_invalid_json_uses_defaults(self):
        self.assertEqual(self.load('{'), stemmero.DEFAULTS)

    def test_non_object_uses_defaults(self):
        self.assertEqual(self.load('[]'), stemmero.DEFAULTS)

    def test_wrong_types_and_unknown_keys_are_ignored(self):
        cfg = self.load(json.dumps({'yellow': None, 'sound': 'false', 'other': 4}))
        self.assertEqual(cfg, stemmero.DEFAULTS)

    def test_ranges_and_threshold_order_are_validated(self):
        cfg = self.load('{"yellow": -5, "orange": -90, "red": -20, '
                        '"hold_ms": -1, "cooldown_s": NaN, "position": "other"}')
        self.assertEqual([cfg[k] for k in ('yellow', 'orange', 'red')], [-60, -20, -5])
        self.assertEqual(cfg['hold_ms'], 100)
        self.assertEqual(cfg['cooldown_s'], stemmero.DEFAULTS['cooldown_s'])
        self.assertEqual(cfg['position'], 'Top')

    def test_save_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(stemmero, 'CONFIG_DIR', directory), patch.object(
                stemmero, 'CONFIG_PATH', str(Path(directory) / 'config.json')
            ):
                stemmero.save_config(stemmero.DEFAULTS)
                self.assertEqual(stemmero.load_config(), stemmero.DEFAULTS)


class WarningTests(unittest.TestCase):
    def test_brief_shout_does_not_trigger(self):
        gate = stemmero.WarningGate()
        self.assertEqual(gate.update(2, 0.0, 350), -1)
        self.assertEqual(gate.update(2, 0.1, 350), -1)
        self.assertEqual(gate.update(-1, 0.2, 350), -1)
        self.assertEqual(gate.update(2, 1.0, 350), -1)

    def test_continuous_shout_triggers_after_hold(self):
        gate = stemmero.WarningGate()
        self.assertEqual(gate.update(2, 0.0, 350), -1)
        self.assertEqual(gate.update(2, 0.36, 350), 2)

    def test_escalation_has_its_own_hold(self):
        gate = stemmero.WarningGate()
        gate.update(0, 0.0, 350)
        self.assertEqual(gate.update(0, 0.36, 350), 0)
        self.assertEqual(gate.update(2, 0.4, 350), 0)
        self.assertEqual(gate.update(2, 0.8, 350), 2)
        self.assertEqual(gate.update(0, 0.9, 350), 0)

    def test_disable_resets_pending_warning(self):
        gate = stemmero.WarningGate()
        gate.update(2, 0.0, 350)
        gate.update(-1, 0.2, 350)
        self.assertEqual(gate.update(2, 0.5, 350), -1)

    def test_threshold_boundaries(self):
        app = stemmero.App.__new__(stemmero.App)
        app.cfg = dict(stemmero.DEFAULTS)
        for db, expected in [(-60, -1), (-24, 0), (-17, 1), (-10, 2), (0, 2)]:
            with self.subTest(db=db):
                self.assertEqual(app._classify(db), expected)

    def test_audio_rms_and_expired_samples(self):
        mic = stemmero.MicListener()
        with patch.object(stemmero.time, 'monotonic', return_value=1.0):
            mic._callback(np.full((256, 1), 0.1, dtype=np.float32), 256, None, None)
            self.assertAlmostEqual(mic.level_db(80), -20, places=4)
        with patch.object(stemmero.time, 'monotonic', return_value=2.0):
            self.assertEqual(mic.level_db(80), stemmero.DB_MIN)

    def test_release_version_matches_installer(self):
        installer = Path(__file__).resolve().parents[1] / 'installer.nsi'
        self.assertIn(f'!define VERSION "{stemmero.APP_VERSION}"', installer.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
