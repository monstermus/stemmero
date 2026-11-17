from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import stemmero


class SettingsBoundaryTests(unittest.TestCase):
    def app(self, unlocked=False):
        app = stemmero.App.__new__(stemmero.App)
        app.cfg = dict(stemmero.DEFAULTS)
        app.parents = SimpleNamespace(unlocked=unlocked, unlocked_until=time.monotonic() + 120,
                                      lock=Mock(), fresh_auth=Mock(return_value=False))
        app.audio = Mock()
        app.root = Mock()
        app.overlay = Mock()
        return app

    def test_locked_callbacks_cannot_change_settings_or_sound(self):
        app = self.app()
        before = dict(app.cfg)
        with patch.object(stemmero.filedialog, 'askopenfilename') as dialog:
            app._set('active', False)
            app._set('hold_ms', 100)
            app._choose_sound('red')
            app._reset_sound('red')
            app._preview_sound('red')
            app._stop_preview()
            app._test()
            app._change_device_mode()
            app._manual_device_selected()
            app._save_policy()
            app._apply_hold()
        self.assertEqual(app.cfg, before)
        dialog.assert_not_called()
        self.assertFalse(app.audio.mock_calls)

    def test_no_parent_controller_is_fail_closed(self):
        app = self.app()
        del app.parents
        self.assertFalse(app._require_parent())
        app._set('active', False)
        self.assertTrue(app.cfg['active'])

    def test_expired_session_cannot_apply_change(self):
        app = self.app(True)
        app.parents.unlocked_until = 0
        app._set('active', False)
        app.parents.lock.assert_called_once()
        self.assertTrue(app.cfg['active'])

    def test_session_is_checked_again_after_native_file_dialog(self):
        app = self.app(True)
        def expire(**kwargs):
            app.parents.unlocked_until = 0
            return 'selected.wav'
        with patch.object(stemmero.filedialog, 'askopenfilename', side_effect=expire), patch.object(stemmero, 'import_custom_sound') as copy:
            app._choose_sound('red')
        copy.assert_not_called()

    def test_cancellation_requires_a_new_pin_even_with_an_open_session(self):
        app = self.app(True)
        app.pending_window = None
        app.policy = Mock()
        app._cancel_policy()
        app.parents.fresh_auth.assert_called_once()
        app.policy.cancel.assert_not_called()

    def test_tick_uses_saved_hold_instead_of_a_changed_widget_variable(self):
        app = self.app()
        app.parents.refresh = Mock()
        app.pin_store = SimpleNamespace(damaged=False, configured=True)
        app._check_microphone = Mock()
        app.mic = Mock()
        app.mic.running.return_value = True
        app.mic.level_db.return_value = -60
        app.hold_var = Mock()
        app.hold_var.get.return_value = 100
        app._draw_meter = Mock()
        app.warning_gate = Mock()
        app.warning_gate.update.return_value = -1
        app.current = -1
        app.last_at_level = 0
        app.test_until = 0
        app.root = Mock()
        app.policy = Mock()
        app._show_policy_status = Mock()
        app._tick()
        self.assertEqual(app.cfg['hold_ms'], 350)
        self.assertEqual(app.warning_gate.update.call_args.args[2], 350)
        app.hold_var.get.assert_not_called()

    def test_closed_portaudio_device_is_treated_as_disconnected(self):
        mic = stemmero.MicListener()
        class Disconnected:
            @property
            def active(self):
                raise stemmero.sd.PortAudioError('device removed')
        mic.stream = Disconnected()
        self.assertFalse(mic.running())

    def test_unplug_still_closes_stream_when_stop_fails(self):
        mic = stemmero.MicListener()
        stream = Mock()
        stream.stop.side_effect = stemmero.sd.PortAudioError('removed')
        mic.stream = stream
        mic.stop()
        stream.close.assert_called_once()
        self.assertIsNone(mic.stream)

    def test_native_enumeration_error_preserves_a_healthy_stream(self):
        app = self.app()
        app.mic = Mock()
        app.mic.running.return_value = True
        app.next_device_check = 0
        app.device_signature = ('saved', ('saved',))
        app.last_device_refresh = 0
        app.next_retry = 0
        app._reconnect = Mock()
        with patch.object(stemmero, 'windows_input_signature', return_value=None):
            app._check_microphone(31)
        app._reconnect.assert_not_called()
        self.assertEqual(app.device_signature, ('saved', ('saved',)))

    def test_changed_native_input_refreshes_the_portaudio_inventory(self):
        app = self.app()
        app.mic = Mock()
        app.mic.running.return_value = True
        app.next_device_check = 0
        app.device_signature = ('old', ('old', 'new'))
        app.next_retry = 0
        app._reconnect = Mock()
        with patch.object(stemmero, 'windows_input_signature', return_value=('new', ('new', 'old'))):
            app._check_microphone(31)
        app._reconnect.assert_called_once()



@unittest.skipUnless(sys.platform == 'win32', 'Full Windows tkinter integration')
class WindowsAppTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        for name, value in [('CONFIG_DIR', self.folder.name),
                            ('CONFIG_PATH', str(Path(self.folder.name) / 'config.json'))]:
            context = patch.object(stemmero, name, value)
            context.start()
            self.addCleanup(context.stop)
        for name, kwargs in [('input_devices', {'return_value': []}),
                             ('windows_input_signature', {'return_value': (None, ())}),
                             ('WindowsActions', {'return_value': Mock()})]:
            context = patch.object(stemmero, name, **kwargs)
            context.start()
            self.addCleanup(context.stop)
        self.app = stemmero.App()
        self.addCleanup(self.app.root.destroy)
        self.app.root.withdraw()
        self.app.root.update_idletasks()

    def unlock(self):
        self.app.pin_store.setup('2468')
        with patch.object(self.app.parents, '_ask_pin', return_value='2468'):
            self.app.parents.unlock()
        self.assertTrue(self.app.parents.unlocked)

    def test_startup_is_locked_and_every_settings_control_is_disabled(self):
        self.assertFalse(self.app.parents.unlocked)
        self.assertGreater(len(self.app.settings_states), 15)
        self.assertTrue(all(str(widget.cget('state')) == 'disabled' for widget in self.app.settings_states))
        self.assertFalse(self.app.policy.config.enabled)
        self.assertIsNone(self.app.policy.executor)

    def test_pin_unlock_then_lock_restores_readonly_and_default_sound_states(self):
        self.unlock()
        self.assertEqual(str(self.app.device_combo.cget('state')), 'disabled')
        self.app.auto_device_var.set(False)
        self.app._change_device_mode()
        self.assertEqual(str(self.app.device_combo.cget('state')), 'readonly')
        self.app.parents.lock()
        self.assertTrue(all(str(widget.cget('state')) == 'disabled' for widget in self.app.settings_states))

    def test_adult_can_save_a_rule_without_any_real_windows_action(self):
        self.unlock()
        values = {'policy_enabled': True, 'policy_count': '3', 'policy_minutes': '4',
                  'policy_action': 'Sluk computeren', 'policy_mode': 'Kun orange og rød', 'policy_countdown': '60'}
        for key, value in values.items():
            self.app.policy_vars[key].set(value)
        self.app._save_policy()
        config = self.app.policy.config
        self.assertTrue(config.enabled)
        self.assertEqual((config.count, config.window_seconds, config.action, config.mode), (3, 240, 'shutdown', 'orange_red'))
        self.assertIsInstance(self.app.policy.executor, Mock)
        self.assertFalse(self.app.policy.executor.mock_calls)

    def test_close_window_keeps_the_process_and_microphone_alive(self):
        self.unlock()
        with patch.object(self.app.mic, 'stop') as stop:
            self.app.hide_settings()
        self.assertFalse(self.app.parents.unlocked)
        self.assertTrue(self.app.root.winfo_exists())
        stop.assert_not_called()


if __name__ == '__main__':
    unittest.main()
