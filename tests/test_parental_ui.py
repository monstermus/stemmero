from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from parental_pin import PinStore, PinStoreError
from parental_ui import ParentControls, SESSION_SECONDS


class ParentFlowTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        context = patch('parental_pin.ITERATIONS', 100_000)
        context.start()
        self.addCleanup(context.stop)
        self.store = PinStore(Path(folder.name) / 'pin.json', clock=lambda: 1000)
        self.controls = ParentControls.__new__(ParentControls)
        self.controls.parent = Mock()
        self.controls.store = self.store
        self.controls.on_unlock = Mock()
        self.controls.on_lock = Mock()
        self.controls.recovery_default = True
        self.controls.clock = Mock(return_value=50.0)
        self.controls.busy = False
        self.controls._unlocked = False
        self.controls.unlocked_until = 0
        self.controls.status = Mock()
        for name in ('setup_button', 'unlock_button', 'lock_button', 'change_button', 'recovery_button'):
            setattr(self.controls, name, Mock())
        context = patch('parental_ui.messagebox.showerror')
        self.error = context.start()
        self.addCleanup(context.stop)
        context = patch.object(self.controls, '_show_recovery_code')
        self.code_dialog = context.start()
        self.addCleanup(context.stop)

    def test_setup_confirms_masked_pin_and_opens_short_session(self):
        with patch('parental_ui.simpledialog.askstring', side_effect=['4826', '4826']) as prompt:
            self.controls.setup()
        self.assertTrue(self.store.verify('4826'))
        self.assertEqual(self.controls.unlocked_until, 50 + SESSION_SECONDS)
        self.controls.on_unlock.assert_called_once()
        self.code_dialog.assert_called_once()
        self.assertFalse(self.controls.busy)
        for call in prompt.call_args_list:
            self.assertEqual(call.kwargs['show'], '*')
            self.assertIs(call.kwargs['parent'], self.controls.parent)

    def test_setup_can_disable_recovery(self):
        self.controls.recovery_default = False
        with patch('parental_ui.simpledialog.askstring', side_effect=['4826', '4826']):
            self.controls.setup()
        self.assertFalse(self.store.recovery_enabled)
        self.code_dialog.assert_not_called()

    def test_cancel_or_mismatch_never_creates_pin(self):
        with patch('parental_ui.simpledialog.askstring', side_effect=['4826', '7264']):
            self.controls.setup()
        self.assertFalse(self.store.configured)
        self.assertFalse(self.controls.unlocked)
        self.controls.on_unlock.assert_not_called()
        self.error.assert_called_once()
        with patch('parental_ui.simpledialog.askstring', return_value=None):
            self.controls.setup()
        self.assertFalse(self.store.configured)

    def test_wrong_pin_or_cancel_never_unlocks(self):
        self.store.setup('4826')
        with patch('parental_ui.simpledialog.askstring', return_value='9999'):
            self.controls.unlock()
        self.assertFalse(self.controls.unlocked)
        self.controls.on_unlock.assert_not_called()
        with patch('parental_ui.simpledialog.askstring', return_value=None):
            self.controls.unlock()
        self.assertFalse(self.controls.busy)

    def test_correct_pin_unlocks_and_lock_ends_session(self):
        self.store.setup('4826')
        with patch('parental_ui.simpledialog.askstring', return_value='4826'):
            self.controls.unlock()
        self.assertTrue(self.controls.unlocked)
        self.controls.lock()
        self.assertFalse(self.controls.unlocked)
        self.assertEqual(self.controls.unlocked_until, 0)
        self.controls.on_lock.assert_called_once()

    def test_fresh_auth_always_asks_pin_without_extending_session(self):
        self.store.setup('4826')
        self.controls._unlock_session()
        self.controls.on_unlock.reset_mock()
        with patch('parental_ui.simpledialog.askstring', side_effect=['4826', '9999']) as prompt:
            self.assertTrue(self.controls.fresh_auth())
            self.assertEqual(self.controls.unlocked_until, 50 + SESSION_SECONDS)
            self.controls.on_unlock.assert_not_called()
            self.assertFalse(self.controls.fresh_auth())
        self.assertEqual(prompt.call_count, 2)
        self.assertFalse(self.controls.unlocked)

    def test_cancel_fresh_auth_does_not_approve_action(self):
        self.store.setup('4826')
        with patch('parental_ui.simpledialog.askstring', return_value=None):
            self.assertFalse(self.controls.fresh_auth())
        self.controls.on_unlock.assert_not_called()

    def test_missing_or_damaged_pin_never_approves_action(self):
        self.assertFalse(self.controls.fresh_auth())
        self.store.path.write_text('{')
        with patch('parental_ui.simpledialog.askstring', return_value='4826'):
            self.assertFalse(self.controls.fresh_auth())
        self.assertFalse(self.controls.unlocked)

    def test_busy_covers_modal_and_resets_after_store_error(self):
        self.store.setup('4826')

        def prompt(*_args, **_kwargs):
            self.assertTrue(self.controls.busy)
            return '4826'

        with patch('parental_ui.simpledialog.askstring', side_effect=prompt), patch.object(
            self.store, 'verify', side_effect=PinStoreError('cannot read')
        ):
            self.controls.unlock()
        self.assertFalse(self.controls.busy)
        self.assertFalse(self.controls.unlocked)
        self.error.assert_called_once()

    def test_change_pin_requires_existing_pin_and_confirmation(self):
        self.store.setup('4826')
        with patch('parental_ui.simpledialog.askstring', side_effect=['4826', '7264', '7264']):
            self.controls.change_pin()
        self.assertTrue(self.store.verify('7264'))
        self.assertFalse(self.store.verify('4826'))
        self.assertTrue(self.controls.unlocked)

    def test_recovery_uses_code_and_returns_replacement(self):
        code = self.store.setup('4826', enable_recovery=True)
        with patch('parental_ui.simpledialog.askstring', side_effect=[code, '7264', '7264']):
            self.controls.recover()
        self.assertTrue(self.store.verify('7264'))
        self.assertNotEqual(code, self.code_dialog.call_args.args[0])
        self.assertTrue(self.controls.unlocked)

    def test_corruption_after_unlock_revokes_session(self):
        self.store.setup('4826')
        self.controls._unlock_session()
        self.store.path.write_text('{}')
        self.controls.refresh()
        self.assertFalse(self.controls.unlocked)
        self.controls.on_lock.assert_called_once()
        self.controls.unlock_button.configure.assert_called_with(state='disabled')


@unittest.skipUnless(sys.platform == 'win32', 'Windows tkinter controls')
class ParentWidgetTests(unittest.TestCase):
    def test_bar_has_named_keyboard_accessible_controls(self):
        with tempfile.TemporaryDirectory() as folder:
            root = tk.Tk()
            root.withdraw()
            try:
                controls = ParentControls(root, PinStore(Path(folder) / 'pin.json'), Mock(), Mock())
                controls.frame.pack()
                root.update_idletasks()
                self.assertEqual(str(controls.setup_button['state']), 'normal')
                self.assertEqual(str(controls.unlock_button['state']), 'disabled')
                self.assertEqual(controls.lock_button['text'], 'Lås indstillinger')
                self.assertLess(root.winfo_reqwidth(), 1000)
            finally:
                root.destroy()


if __name__ == '__main__':
    unittest.main()
