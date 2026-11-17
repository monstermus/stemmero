from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import stemmero
from warning_audio import default_sound


@unittest.skipUnless(sys.platform == 'win32', 'Windows tkinter controls')
class SoundSettingsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = stemmero.App.__new__(stemmero.App)
        self.app.root = self.root
        self.app.cfg = dict(stemmero.DEFAULTS)
        self.app.audio = Mock(last_error='')
        for target, value in [('save_config', None), ('input_devices', []), ('CONFIG_DIR', self.folder.name)]:
            context = patch.object(stemmero, target, return_value=value) if target != 'CONFIG_DIR' else patch.object(stemmero, target, value)
            context.start()
            self.addCleanup(context.stop)
        self.app._build_ui()
        self.root.update_idletasks()

    def test_choose_preview_and_restore(self):
        with patch.object(stemmero.filedialog, 'askopenfilename', return_value=str(default_sound('red'))):
            self.app._choose_sound('red')
        selected = self.app.cfg['sound_red']
        self.assertTrue(Path(selected).is_file())
        self.assertEqual(str(self.app.sound_reset_buttons['red']['state']), 'normal')
        self.app._preview_sound('red')
        self.app.audio.play.assert_called_with('red', selected, preview=True)
        self.app._reset_sound('red')
        self.assertEqual(self.app.cfg['sound_red'], '')
        self.assertEqual(str(self.app.sound_reset_buttons['red']['state']), 'disabled')

    def test_cancel_and_bad_file_keep_previous_selection(self):
        self.app.cfg['sound_yellow'] = 'previous.wav'
        with patch.object(stemmero.filedialog, 'askopenfilename', return_value=''):
            self.app._choose_sound('yellow')
        self.assertEqual(self.app.cfg['sound_yellow'], 'previous.wav')
        with patch.object(stemmero.filedialog, 'askopenfilename', return_value='missing.wav'), patch.object(stemmero.messagebox, 'showerror') as error:
            self.app._choose_sound('yellow')
        self.assertEqual(self.app.cfg['sound_yellow'], 'previous.wav')
        error.assert_called_once()

    def test_muting_stops_playback_but_explicit_preview_still_works(self):
        self.app._set('sound', False)
        self.app.audio.stop.assert_called_once()
        self.app._preview_sound('yellow')
        self.app.audio.play.assert_called_once_with('yellow', '', preview=True)

    def test_real_warning_uses_selected_level_sound(self):
        self.app.overlay = Mock()
        self.app.last_sound = {}
        self.app.test_until = 0
        self.app.cfg['sound_orange'] = 'selected.wav'
        self.app._alert(1, 100, True)
        self.app.audio.play.assert_called_once_with('orange', 'selected.wav')
        self.assertEqual(self.app.last_sound[1], 100)

    def test_failed_sound_obeys_cooldown(self):
        self.app.overlay = Mock()
        self.app.last_sound = {}
        self.app.test_until = 0
        self.app.audio.play.return_value = False
        self.app._alert(1, 100, True)
        self.app._alert(1, 100.04, False)
        self.assertEqual(self.app.audio.play.call_count, 1)


if __name__ == '__main__':
    unittest.main()
