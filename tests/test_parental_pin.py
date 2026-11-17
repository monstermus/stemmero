import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from parental_pin import LOCK_SECONDS, MAX_FAILURES, PinStore, PinStoreError


class PinStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'parental-pin.json'
        self.clock = Mock(return_value=1000.0)
        self.store = PinStore(self.path, self.clock)
        context = patch('parental_pin.ITERATIONS', 100_000)
        context.start()
        self.addCleanup(context.stop)

    def test_new_store_needs_an_adult_to_choose_pin(self):
        self.assertFalse(self.store.configured)
        self.assertFalse(self.store.damaged)
        self.assertFalse(self.store.verify('4826'))
        self.assertEqual(self.store.remaining_lock_seconds, 0)
        self.assertIsNone(self.store.setup('4826'))
        self.assertTrue(self.store.configured)
        self.assertFalse(self.store.recovery_enabled)
        self.assertTrue(self.store.verify('4826'))
        self.assertFalse(self.store.verify('9999'))

    def test_pin_format_rejects_short_non_ascii_or_non_digit_values(self):
        for pin in ('123', '1' * 13, '１２３４', 'abcd', '123 4', 1234, None):
            with self.subTest(pin=repr(pin)), self.assertRaises(ValueError):
                self.store.setup(pin)
        self.assertFalse(self.path.exists())

    def test_same_pin_has_independent_salt_and_no_plaintext_storage(self):
        self.store.setup('4826')
        other_path = self.path.with_name('other.json')
        PinStore(other_path).setup('4826')
        first = json.loads(self.path.read_text())
        second = json.loads(other_path.read_text())
        self.assertNotEqual(first['pin']['salt'], second['pin']['salt'])
        self.assertNotEqual(first['pin']['digest'], second['pin']['digest'])
        self.assertNotIn('"4826"', self.path.read_text())
        self.assertEqual(len(first['pin']['digest']), 64)
        if os.name != 'nt':
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_wrong_pin_cannot_replace_or_remove_pin(self):
        self.store.setup('4826')
        with self.assertRaises(PermissionError):
            self.store.setup('9999')
        with self.assertRaises(PermissionError):
            self.store.change_pin('9999', '7264')
        with self.assertRaises(PermissionError):
            self.store.clear('9999')
        self.assertTrue(self.store.verify('4826'))

    def test_correct_pin_can_be_changed_and_explicitly_removed(self):
        self.store.setup('4826')
        self.store.change_pin('4826', '7264')
        self.assertFalse(self.store.verify('4826'))
        self.assertTrue(self.store.verify('7264'))
        self.store.clear('7264')
        self.assertFalse(self.path.exists())
        self.assertFalse(self.store.configured)
        self.assertFalse(PinStore(self.path).configured)
        self.store.setup('1937')
        self.assertTrue(self.store.verify('1937'))

    def test_invalid_new_pin_leaves_old_pin_unchanged(self):
        self.store.setup('4826')
        with self.assertRaises(ValueError):
            self.store.change_pin('4826', '123')
        self.assertTrue(self.store.verify('4826'))

    def test_lockout_survives_restart_and_correct_pin_cannot_skip_wait(self):
        self.store.setup('4826')
        for _ in range(MAX_FAILURES):
            self.assertFalse(self.store.verify('9999'))
        restarted = PinStore(self.path, self.clock)
        self.assertEqual(restarted.remaining_lock_seconds, LOCK_SECONDS)
        self.assertFalse(restarted.verify('4826'))
        self.clock.return_value += LOCK_SECONDS - 0.2
        self.assertEqual(restarted.remaining_lock_seconds, 1)
        self.assertFalse(restarted.verify('4826'))
        self.clock.return_value += 0.2
        self.assertTrue(restarted.verify('4826'))
        self.assertEqual(restarted.remaining_lock_seconds, 0)

    def test_failed_attempt_count_survives_each_restart(self):
        self.store.setup('4826')
        for _ in range(MAX_FAILURES):
            restarted = PinStore(self.path, self.clock)
            self.assertFalse(restarted.verify('9999'))
        self.assertEqual(PinStore(self.path, self.clock).remaining_lock_seconds, LOCK_SECONDS)

    def test_success_resets_incorrect_attempts(self):
        self.store.setup('4826')
        for _ in range(MAX_FAILURES - 1):
            self.store.verify('9999')
        self.assertTrue(self.store.verify('4826'))
        self.assertFalse(self.store.verify('9999'))
        self.assertEqual(self.store.remaining_lock_seconds, 0)

    def test_recovery_is_opt_in_and_rotates_after_use(self):
        code = self.store.setup('4826', enable_recovery=True)
        self.assertTrue(self.store.recovery_enabled)
        self.assertNotIn(code, self.path.read_text())
        self.assertNotIn(code.replace('-', ''), self.path.read_text())
        replacement = self.store.recover(code.lower().replace('-', ' '), '7264')
        self.assertNotEqual(code, replacement)
        self.assertFalse(self.store.verify('4826'))
        self.assertTrue(self.store.verify('7264'))
        with self.assertRaises(PermissionError):
            self.store.recover(code, '1937')
        self.assertTrue(self.store.verify('7264'))
        self.store.recover(replacement, '1937')
        self.assertTrue(self.store.verify('1937'))

    def test_recovery_and_pin_share_attempt_limits(self):
        code = self.store.setup('4826', enable_recovery=True)
        for _ in range(MAX_FAILURES):
            with self.assertRaises(PermissionError):
                self.store.recover('wrong', '7264')
        with self.assertRaises(PermissionError):
            PinStore(self.path, self.clock).recover(code, '7264')
        self.clock.return_value += LOCK_SECONDS
        PinStore(self.path, self.clock).recover(code, '7264')
        self.assertTrue(self.store.verify('7264'))

    def test_no_recovery_code_can_reset_when_recovery_was_disabled(self):
        self.store.setup('4826')
        with self.assertRaises(PermissionError):
            self.store.recover('A' * 32, '7264')
        self.assertTrue(self.store.verify('4826'))

    def test_change_preserves_an_enabled_recovery_code(self):
        code = self.store.setup('4826', enable_recovery=True)
        self.store.change_pin('4826', '7264')
        self.store.recover(code, '1937')
        self.assertTrue(self.store.verify('1937'))

    def test_corrupt_files_keep_settings_locked(self):
        for content in ('{', 'null', '[]', '{}', '\xff', '[' * 2000, 'x' * 20_000):
            with self.subTest(content=content[:20]):
                self.path.write_text(content)
                store = PinStore(self.path, self.clock)
                self.assertTrue(store.configured)
                self.assertTrue(store.damaged)
                with self.assertRaises(PinStoreError):
                    store.verify('4826')
                with self.assertRaises(PermissionError):
                    store.setup('4826')

    def test_malformed_crypto_and_attempt_records_are_rejected(self):
        self.store.setup('4826')
        good = json.loads(self.path.read_text())
        mutations = [
            {'version': True}, {'pin': {}}, {'pin': {**good['pin'], 'iterations': 100_000_000}},
            {'pin': {**good['pin'], 'salt': 'z' * 32}}, {'recovery': {}},
            {'failed_attempts': -1}, {'failed_attempts': True}, {'failed_attempts': MAX_FAILURES},
            {'blocked_until': float('inf')}, {'blocked_until': -1}, {'blocked_until': False},
        ]
        for changes in mutations:
            with self.subTest(changes=changes):
                self.path.write_text(json.dumps({**good, **changes}))
                self.assertTrue(self.store.configured)
                self.assertTrue(self.store.damaged)
                with self.assertRaises(PinStoreError):
                    self.store.verify('4826')

    def test_deleting_a_pin_file_does_not_unlock_running_process(self):
        self.store.setup('4826')
        self.path.unlink()
        self.assertTrue(self.store.configured)
        self.assertTrue(self.store.damaged)
        with self.assertRaises(PinStoreError):
            self.store.verify('4826')

    def test_failed_atomic_replace_preserves_previous_pin(self):
        self.store.setup('4826')
        previous = self.path.read_bytes()
        replace = os.replace
        calls = []

        def fail_second_replace(source, target):
            calls.append(target)
            if len(calls) == 2:
                raise OSError('disk error')
            replace(source, target)

        with patch('parental_pin.os.replace', side_effect=fail_second_replace):
            with self.assertRaises(PinStoreError):
                self.store.change_pin('4826', '7264')
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertFalse(any(self.path.parent.glob('*.tmp')))
        self.assertTrue(self.store.verify('4826'))
        self.assertFalse(self.store.verify('7264'))

    def test_failure_to_save_attempt_counter_does_not_allow_unlock(self):
        self.store.setup('4826')
        with patch('parental_pin.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(PinStoreError):
                self.store.verify('4826')
        self.assertTrue(self.store.configured)

    def test_permission_error_during_read_keeps_settings_locked(self):
        self.store.setup('4826')
        with patch.object(Path, 'open', side_effect=PermissionError('denied')):
            self.assertTrue(self.store.configured)
            self.assertTrue(self.store.damaged)
            with self.assertRaises(PinStoreError):
                self.store.verify('4826')


if __name__ == '__main__':
    unittest.main()
