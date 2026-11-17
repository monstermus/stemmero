from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from warning_policy import PolicyConfig, PolicyStateError, WarningPolicy, WindowsActions


class WarningPolicyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'policy.json'
        self.clock = Mock(return_value=1000.0)
        self.executor = Mock()
        self.config = PolicyConfig(enabled=True, count=3, window_seconds=60)
        self.policy = WarningPolicy(self.path, self.config, self.clock, self.executor)

    def at(self, now, level, **kwargs):
        self.clock.return_value = now
        return self.policy.observe(level, **kwargs)

    def episode(self, now, level=0):
        self.at(now - 2, -1)
        return self.at(now, level)

    def test_disabled_by_default_and_no_implicit_executor(self):
        policy = WarningPolicy(self.path, clock=self.clock)
        for _ in range(20):
            policy.observe(2)
        self.assertEqual(policy.status.count, 0)
        self.assertIsNone(policy.status.pending_action)
        policy.configure(PolicyConfig(enabled=True, count=1))
        policy.observe(2)
        self.assertEqual(policy.tick().pending_action, 'lock')
        self.executor.assert_not_called()

    def test_sustained_burst_and_escalation_count_once(self):
        self.assertEqual(self.at(1000, 0).count, 1)
        self.assertEqual(self.at(1001, 1).count, 1)
        self.assertEqual(self.at(1002, 2).count, 1)
        self.assertEqual(self.at(1003, 2).count, 1)
        self.assertEqual(self.at(1004, -1).count, 1)
        self.assertEqual(self.at(1004.5, 2).count, 1)
        self.assertEqual(self.episode(1010, 2).count, 2)

    def test_quiet_boundary_rearms_without_intermediate_poll(self):
        self.at(1000, 2)
        self.at(1001, -1)
        self.assertEqual(self.at(1002.3, 1).count, 2)

    def test_hold_time_after_short_pause_is_not_counted_as_quiet(self):
        self.at(1000, 2)
        self.at(1001, -1, quiet=True)
        self.at(1001.9, -1, quiet=False)
        self.assertEqual(self.at(1002.25, 2, quiet=False).count, 1)
        self.at(1003, -1, quiet=True)
        self.assertEqual(self.at(1004.3, 2, quiet=False).count, 2)

    def test_unqualified_spike_breaks_quiet_without_adding_warning(self):
        self.at(1000, 1)
        self.at(1001, -1, quiet=True)
        self.assertEqual(self.at(1001.9, -1, quiet=False).count, 1)
        self.at(1002, -1, quiet=True)
        self.assertEqual(self.at(1002.8, 1, quiet=False).count, 1)

    def test_orange_red_mode_ignores_yellow_but_counts_escalation(self):
        self.policy.configure(replace(self.config, mode='orange_red'))
        self.assertEqual(self.at(1000, 0).count, 0)
        self.assertEqual(self.at(1001, 1).count, 1)
        self.assertEqual(self.at(1002, 2).count, 1)
        self.assertEqual(self.at(1003, 0).count, 1)
        self.assertEqual(self.at(1004, 2).count, 1)

    def test_rolling_window_excludes_exact_expiry(self):
        self.at(1000, 0)
        self.episode(1030)
        self.assertEqual(self.episode(1060).count, 2)
        self.assertIsNone(self.policy.status.pending_action)

    def test_threshold_arms_one_lock_and_tick_resets_counter(self):
        self.at(1000, 0)
        self.episode(1010)
        status = self.episode(1020)
        self.assertEqual(status.pending_action, 'lock')
        self.executor.lock.assert_not_called()
        self.policy.tick()
        self.executor.lock.assert_called_once_with()
        self.assertEqual(self.policy.status.count, 0)
        self.assertIsNone(self.policy.status.pending_action)
        self.at(1021, 2)
        self.policy.tick()
        self.executor.lock.assert_called_once_with()
        self.assertEqual(self.policy.status.count, 0)

    def test_shutdown_countdown_survives_restart_and_does_not_run_early(self):
        config = replace(self.config, count=1, action='shutdown', countdown_seconds=60)
        self.policy.configure(config)
        self.assertEqual(self.at(1000, 1).remaining_seconds, 60)
        self.clock.return_value = 1030
        policy = WarningPolicy(self.path, clock=self.clock, executor=self.executor)
        self.assertEqual(policy.status.remaining_seconds, 30)
        policy.tick()
        self.executor.shutdown.assert_not_called()
        self.clock.return_value = 1060
        policy.tick()
        self.executor.shutdown.assert_called_once_with()
        self.assertEqual(policy.status.count, 0)
        self.assertIsNone(policy.status.pending_action)
        self.assertEqual(WarningPolicy(self.path, clock=self.clock).status.count, 0)

    def test_zero_seconds_requests_shutdown_immediately_and_only_once(self):
        self.policy.configure(replace(self.config, count=1, action='shutdown', countdown_seconds=0))
        status = self.at(1000, 2)
        self.assertEqual(status.remaining_seconds, 0)
        self.assertEqual(status.due_at, 1000)
        self.executor.shutdown.assert_not_called()
        self.policy.tick()
        self.policy.tick()
        self.executor.shutdown.assert_called_once_with()

    def test_zero_seconds_survives_restart_without_adding_a_delay(self):
        self.policy.configure(replace(self.config, count=1, action='shutdown', countdown_seconds=0))
        self.at(1000, 1)
        restarted = WarningPolicy(self.path, clock=self.clock, executor=self.executor)
        self.assertEqual(restarted.config.countdown_seconds, 0)
        restarted.tick()
        self.executor.shutdown.assert_called_once_with()

    def test_short_delays_use_seconds_without_a_minimum_wait(self):
        for seconds in (1, 2, 4):
            with self.subTest(seconds=seconds):
                self.clock.return_value = 1000
                executor = Mock()
                policy = WarningPolicy(self.path.parent / f'{seconds}.json',
                                       replace(self.config, count=1, action='shutdown', countdown_seconds=seconds),
                                       self.clock, executor)
                policy.observe(2)
                self.clock.return_value = 1000 + seconds - 0.1
                policy.tick()
                executor.shutdown.assert_not_called()
                self.clock.return_value = 1000 + seconds
                policy.tick()
                executor.shutdown.assert_called_once_with()

    def test_history_and_episode_survive_restart(self):
        self.at(1000, 1)
        self.clock.return_value = 1001
        self.policy = WarningPolicy(self.path, clock=self.clock, executor=self.executor)
        self.assertEqual(self.at(1001, 2).count, 1)
        self.assertEqual(self.episode(1010).count, 2)

    def test_parent_cancel_removes_pending_and_history(self):
        self.policy.configure(replace(self.config, count=1, action='shutdown'))
        self.at(1000, 2)
        status = self.policy.cancel()
        self.assertEqual(status.count, 0)
        self.assertIsNone(status.pending_action)
        self.clock.return_value = 2000
        self.policy.tick()
        self.executor.shutdown.assert_not_called()

    def test_monitoring_absence_counts_nothing_and_preserves_pending(self):
        self.policy.configure(replace(self.config, count=1, action='shutdown'))
        self.at(1000, 2)
        self.at(1001, -1, monitoring=False)
        self.assertEqual(self.policy.status.count, 1)
        self.assertEqual(self.policy.status.pending_action, 'shutdown')
        self.clock.return_value = 1060
        self.policy.tick()
        self.executor.shutdown.assert_called_once()

    def test_missing_mic_does_not_leave_episode_permanently_latched(self):
        self.at(1000, 1)
        self.at(1001, -1, monitoring=False)
        self.assertEqual(self.at(1002, 1).count, 2)

    def test_banner_test_does_not_count_or_change_episode(self):
        self.at(1000, 2, test=True)
        self.assertEqual(self.policy.status.count, 0)
        self.assertEqual(self.at(1001, 2).count, 1)

    def test_disabling_cancels_pending_and_counter(self):
        self.policy.configure(replace(self.config, count=1, action='shutdown'))
        self.at(1000, 2)
        self.policy.configure(replace(self.config, enabled=False))
        self.clock.return_value = 1060
        self.policy.tick()
        self.executor.shutdown.assert_not_called()
        self.assertEqual(self.policy.status.count, 0)

    def test_disabled_override_clears_persisted_pending_before_tick(self):
        for action in ('lock', 'shutdown'):
            with self.subTest(action=action):
                self.path.unlink(missing_ok=True)
                self.clock.return_value = 1000
                config = replace(self.config, count=1, action=action)
                self.policy = WarningPolicy(self.path, config, self.clock, self.executor)
                self.at(1000, 2)
                self.clock.return_value = 1061
                restarted = WarningPolicy(self.path, replace(config, enabled=False), self.clock, self.executor)
                self.assertIsNone(restarted.status.pending_action)
                self.assertEqual(restarted.status.count, 0)
                restarted.tick()
                self.executor.lock.assert_not_called()
                self.executor.shutdown.assert_not_called()
                again = WarningPolicy(self.path, clock=self.clock, executor=self.executor)
                self.assertFalse(again.config.enabled)
                self.assertIsNone(again.tick().pending_action)
                self.path.unlink()
                self.clock.return_value = 1000

    def test_explicit_disable_clears_pending_even_if_config_already_disabled(self):
        self.policy.configure(replace(self.config, count=1, action='shutdown'))
        self.at(1000, 2)
        disabled = replace(self.policy.config, enabled=False)
        self.policy.config = disabled
        self.assertIsNone(self.policy.configure(disabled).pending_action)
        self.assertEqual(self.policy.status.count, 0)
        self.clock.return_value = 1061
        self.policy.tick()
        self.executor.shutdown.assert_not_called()

    def test_tick_never_executes_when_current_config_is_disabled(self):
        self.policy.configure(replace(self.config, count=1))
        self.at(1000, 2)
        self.policy.config = replace(self.policy.config, enabled=False)
        self.policy.tick()
        self.executor.lock.assert_not_called()

    def test_disabled_stored_config_cannot_revive_inconsistent_pending(self):
        self.policy.configure(replace(self.config, count=1))
        self.at(1000, 2)
        state = json.loads(self.path.read_text())
        state['config']['enabled'] = False
        self.path.write_text(json.dumps(state))
        restarted = WarningPolicy(self.path, clock=self.clock, executor=self.executor)
        self.assertFalse(restarted.config.enabled)
        self.assertIsNone(restarted.tick().pending_action)
        self.executor.lock.assert_not_called()

    def test_disabled_override_is_saved_even_without_pending_or_history(self):
        self.policy.configure(replace(self.config, count=4))
        disabled = WarningPolicy(self.path, replace(self.config, enabled=False), self.clock)
        self.assertFalse(disabled.config.enabled)
        self.assertFalse(WarningPolicy(self.path, clock=self.clock).config.enabled)

    def test_action_failure_is_visible_and_not_retried(self):
        self.policy.configure(replace(self.config, count=1))
        self.executor.lock.side_effect = OSError('denied')
        self.at(1000, 0)
        status = self.policy.tick()
        self.assertTrue(status.action_failed)
        self.assertIn('denied', status.error)
        self.policy.tick()
        restarted = WarningPolicy(self.path, clock=self.clock, executor=self.executor)
        restarted.tick()
        self.executor.lock.assert_called_once()
        self.assertTrue(restarted.status.action_failed)
        self.assertEqual(restarted.cancel().count, 0)

    def test_interrupted_execution_is_not_replayed_after_restart(self):
        self.policy.configure(replace(self.config, count=1))
        self.at(1000, 2)
        state = json.loads(self.path.read_text())
        state['pending']['phase'] = 'executing'
        self.path.write_text(json.dumps(state))
        restarted = WarningPolicy(self.path, clock=self.clock, executor=self.executor)
        self.assertTrue(restarted.tick().action_failed)
        self.executor.lock.assert_not_called()

    def test_clock_rollback_does_not_remove_existing_warnings(self):
        self.at(1000, 2)
        self.assertEqual(self.at(900, -1).count, 1)
        self.assertEqual(self.policy.status.count, 1)

    def test_corrupt_and_malicious_state_never_executes(self):
        self.policy.configure(replace(self.config, count=1))
        self.at(1000, 1)
        good = json.loads(self.path.read_text())
        variants = ['{', '[]', json.dumps({**good, 'events': [float('nan')]}),
                    json.dumps({**good, 'events': [2000]}),
                    json.dumps({**good, 'pending': {**good['pending'], 'action': 'arbitrary.exe'}}),
                    json.dumps({**good, 'pending': {**good['pending'], 'due_at': 1e90}}),
                    json.dumps({**good, 'config': {**good['config'], 'enabled': 'true'}})]
        for contents in variants:
            with self.subTest(contents=contents[:80]):
                self.path.write_text(contents)
                policy = WarningPolicy(self.path, clock=self.clock, executor=self.executor)
                self.assertTrue(policy.status.damaged)
                policy.observe(2)
                policy.tick()
                self.executor.lock.assert_not_called()
                self.executor.shutdown.assert_not_called()
                with self.assertRaises(PolicyStateError):
                    policy.configure(self.config)
                self.assertFalse(policy.cancel().damaged)

    def test_failed_atomic_save_prevents_any_action(self):
        self.policy.configure(replace(self.config, count=1))
        with patch('warning_policy.os.replace', side_effect=OSError('read only')):
            with self.assertRaises(PolicyStateError):
                self.at(1000, 2)
        self.assertTrue(self.policy.status.damaged)
        self.policy.tick()
        self.executor.lock.assert_not_called()

    def test_execution_must_be_persisted_before_requesting_windows(self):
        self.policy.configure(replace(self.config, count=1))
        self.at(1000, 2)
        with patch('warning_policy.os.replace', side_effect=OSError('read only')):
            with self.assertRaises(PolicyStateError):
                self.policy.tick()
        self.executor.lock.assert_not_called()

    def test_switching_count_mode_starts_a_new_history(self):
        self.at(1000, 0)
        self.policy.configure(replace(self.config, mode='orange_red'))
        self.assertEqual(self.policy.status.count, 0)
        self.assertEqual(self.at(1001, 1).count, 1)
        self.assertFalse(list(self.path.parent.glob('policy.json.*')))

    def test_invalid_configuration_is_rejected(self):
        invalid = [dict(count=0), dict(count=True), dict(count=1001), dict(action='run'),
                   dict(enabled='yes'), dict(countdown_seconds=-1), dict(mode='each'),
                   dict(quiet_seconds=float('nan'))]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                PolicyConfig(**values)


class WindowsActionsTests(unittest.TestCase):
    def test_shutdown_requests_no_forced_close_and_no_system_countdown(self):
        with patch('warning_policy.sys.platform', 'win32'), patch('warning_policy.subprocess.run') as run:
            WindowsActions().shutdown()
        arguments = run.call_args.args[0]
        self.assertEqual(arguments[1:], ['/s', '/t', '0'])
        self.assertNotIn('/f', arguments)
        self.assertTrue(run.call_args.kwargs['check'])

    def test_lock_uses_checked_typed_win32_request(self):
        function = Mock(return_value=1)
        user32 = Mock(LockWorkStation=function)
        with patch('warning_policy.sys.platform', 'win32'), patch('warning_policy.ctypes.WinDLL', create=True, return_value=user32):
            WindowsActions().lock()
        function.assert_called_once_with()
        self.assertEqual(function.argtypes, [])

    def test_no_native_actions_on_other_systems(self):
        with patch('warning_policy.sys.platform', 'linux'), patch('warning_policy.subprocess.run') as run:
            with self.assertRaises(OSError):
                WindowsActions().shutdown()
            with self.assertRaises(OSError):
                WindowsActions().lock()
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
