import ctypes
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import Mock, patch

import input_meter as meter

ENDPOINT_VOLUME_IID_DATA1 = meter._GUID.parse('5CDF2C82-841E-4546-9722-0CF74078229A').data1


class NativeMeterTests(unittest.TestCase):
    @staticmethod
    def pointer(output, value):
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = value

    def setUp(self):
        self.devices = SimpleNamespace(enumerator=ctypes.c_void_p(10))
        self.context = Mock()
        self.context.__enter__ = Mock(return_value=self.devices)
        self.context.__exit__ = Mock(return_value=False)
        self.clock = Mock(return_value=100.0)
        self.backend = meter.WindowsCapturePeakBackend(lambda: self.context, self.clock)
        self.peak = 0.1
        self.muted = False
        self.gain_db = 0.0
        self.fail_volume_activation = False
        self.fail_get_device = False
        self.fail_meter = False
        self.calls = []

    def native(self, interface, slot, argtypes, *args):
        self.calls.append((interface.value, slot))
        if interface.value in (10, 11, 12) and slot == 5:
            if self.fail_get_device:
                raise OSError('audio service restarted')
            self.assertIn(args[0], ('mic-a', 'mic-b'))
            self.pointer(args[1], 20)
        elif (interface.value, slot) == (20, 3):
            identifier = ctypes.cast(args[0], ctypes.POINTER(meter._GUID)).contents
            if identifier.data1 == meter._IID_AUDIO_METER.data1:
                self.pointer(args[3], 30)
            elif identifier.data1 == ENDPOINT_VOLUME_IID_DATA1:
                if self.fail_volume_activation:
                    return -1
                self.pointer(args[3], 40)
            else:
                self.fail(f'Unexpected interface IID: {identifier.data1:08x}')
        elif (interface.value, slot) == (30, 3):
            if self.fail_meter:
                raise OSError('device removed')
            ctypes.cast(args[0], ctypes.POINTER(ctypes.c_float))[0] = self.peak
        elif (interface.value, slot) == (40, 15):
            ctypes.cast(args[0], ctypes.POINTER(ctypes.c_int32))[0] = int(self.muted)
        elif (interface.value, slot) == (40, 8):
            ctypes.cast(args[0], ctypes.POINTER(ctypes.c_float))[0] = self.gain_db
        else:
            self.fail(f'Unexpected native call {interface.value}/{slot}')
        return 0

    def test_reads_input_peak_as_dbfs_and_reuses_meter_between_polls(self):
        with patch.object(meter.sys, 'platform', 'win32'), patch.object(meter, '_com_call', side_effect=self.native), patch.object(meter, '_release') as release:
            first = self.backend.read(('mic-a',))
            second = self.backend.read(('mic-a',))
            self.assertAlmostEqual(first['mic-a'], -20, places=4)
            self.assertEqual(first, second)
            self.assertEqual(self.calls.count((20, 3)), 2)
            self.backend.close()
        self.context.__enter__.assert_called_once()
        self.context.__exit__.assert_called_once()
        self.assertEqual([call.args[0].value for call in release.call_args_list], [20, 30, 40])

    def test_muted_endpoint_with_high_raw_peak_is_silence(self):
        self.peak = 0.9
        self.muted = True
        with patch.object(meter.sys, 'platform', 'win32'), \
             patch.object(meter, '_com_call', side_effect=self.native), \
             patch.object(meter, '_release'):
            self.assertEqual(self.backend.read(('mic-a',)), {'mic-a': -120.0})
            self.assertNotIn((30, 3), self.calls)
            self.backend.close()

    def test_low_endpoint_gain_reduces_effective_peak(self):
        self.peak = 0.9
        self.gain_db = -60.0
        with patch.object(meter.sys, 'platform', 'win32'), \
             patch.object(meter, '_com_call', side_effect=self.native), \
             patch.object(meter, '_release'):
            self.assertAlmostEqual(self.backend.read(('mic-a',))['mic-a'], -60.9151498, places=4)
            self.gain_db = float('-inf')
            self.assertEqual(self.backend.read(('mic-a',))['mic-a'], -120.0)
            self.backend.close()

    def test_missing_volume_api_falls_back_to_raw_meter_peak(self):
        self.fail_volume_activation = True
        with patch.object(meter.sys, 'platform', 'win32'), \
             patch.object(meter, '_com_call', side_effect=self.native), \
             patch.object(meter, '_release'):
            self.assertAlmostEqual(self.backend.read(('mic-a',))['mic-a'], -20.0, places=4)
            self.backend.close()

    def test_silence_is_a_floor_and_missing_endpoint_closes_meter(self):
        self.peak = 0.0
        self.gain_db = 80.0
        with patch.object(meter.sys, 'platform', 'win32'), patch.object(meter, '_com_call', side_effect=self.native), patch.object(meter, '_release'):
            self.assertEqual(self.backend.read(('mic-a',)), {'mic-a': -120})
            self.assertEqual(self.backend.read(()), {})
        self.context.__exit__.assert_called_once()
        self.assertFalse(self.backend.meters)

    def test_removed_device_is_closed_and_retried_after_backoff(self):
        with patch.object(meter.sys, 'platform', 'win32'), patch.object(meter, '_com_call', side_effect=self.native), patch.object(meter, '_release'):
            self.backend.read(('mic-a',))
            self.fail_meter = True
            self.assertEqual(self.backend.read(('mic-a',)), {})
            self.fail_meter = False
            self.assertIsNone(self.backend.read(('mic-a',)))
            self.clock.return_value = 106
            self.assertIn('mic-a', self.backend.read(('mic-a',)))
            self.backend.close()

    def test_all_endpoint_failures_reopen_context_after_backoff(self):
        second_devices = SimpleNamespace(enumerator=ctypes.c_void_p(11))
        second_context = Mock()
        second_context.__enter__ = Mock(return_value=second_devices)
        second_context.__exit__ = Mock(return_value=False)
        third_devices = SimpleNamespace(enumerator=ctypes.c_void_p(12))
        third_context = Mock()
        third_context.__enter__ = Mock(return_value=third_devices)
        third_context.__exit__ = Mock(return_value=False)
        factory = Mock(side_effect=(self.context, second_context, third_context))
        backend = meter.WindowsCapturePeakBackend(factory, self.clock)

        with patch.object(meter.sys, 'platform', 'win32'), \
             patch.object(meter, '_com_call', side_effect=self.native), \
             patch.object(meter, '_release'):
            self.assertIn('mic-a', backend.read(('mic-a',)))
            self.fail_meter = True
            self.clock.return_value = 101
            self.assertEqual(backend.read(('mic-a',)), {})
            self.fail_meter = False
            self.fail_get_device = True
            self.clock.return_value = 106
            self.assertEqual(backend.read(('mic-a',)), {})
            self.context.__exit__.assert_called_once()
            second_context.__exit__.assert_called_once()
            self.assertIsNone(backend.read(('mic-a',)))
            self.assertEqual(factory.call_count, 2)
            self.fail_get_device = False
            self.clock.return_value = 111
            self.assertIn('mic-a', backend.read(('mic-a',)))
            backend.close()

        third_context.__exit__.assert_called_once()

    def test_nan_and_impossible_levels_are_not_signals(self):
        with patch.object(meter.sys, 'platform', 'win32'), patch.object(meter, '_com_call', side_effect=self.native), patch.object(meter, '_release'):
            for peak in (float('nan'), float('inf'), -1, 2):
                self.peak = peak
                self.clock.return_value += 6
                self.assertEqual(self.backend.read(('mic-a',)), {})
            self.backend.close()

    def test_unavailable_api_is_optional_and_backs_off(self):
        factory = Mock(side_effect=OSError('audio service unavailable'))
        backend = meter.WindowsCapturePeakBackend(factory, self.clock)
        with patch.object(meter.sys, 'platform', 'win32'):
            self.assertIsNone(backend.read(('mic-a',)))
            self.assertIsNone(backend.read(('mic-a',)))
        factory.assert_called_once()

    def test_other_platform_does_not_load_windows_objects(self):
        factory = Mock()
        with patch.object(meter.sys, 'platform', 'linux'):
            backend = meter.WindowsCapturePeakBackend(factory)
            self.assertIsNone(backend.read(('mic-a',)))
        factory.assert_not_called()


class MonitorThreadTests(unittest.TestCase):
    def test_native_work_stays_off_gui_thread_and_snapshot_expires(self):
        main = threading.get_ident()
        ids = []
        closed = threading.Event()
        class Backend:
            def read(self, endpoints):
                ids.append(threading.get_ident())
                return {key: -20.0 for key in endpoints}
            def close(self):
                ids.append(threading.get_ident())
                closed.set()
        now = Mock(return_value=100)
        monitor = meter.InputActivityMonitor(Backend, now, interval=10)
        self.addCleanup(monitor.close)
        monitor.set_endpoints(('mic-a',))
        deadline = time.monotonic() + 2
        while monitor.snapshot() is None and time.monotonic() < deadline:
            time.sleep(0.005)
        sample = monitor.snapshot()
        self.assertIsNotNone(sample)
        self.assertEqual(sample.peaks, {'mic-a': -20.0})
        self.assertEqual(sample.at, 100)
        sample.peaks['mic-a'] = 0
        self.assertEqual(monitor.snapshot().peaks['mic-a'], -20)
        now.return_value = 102
        self.assertIsNone(monitor.snapshot())
        monitor.close()
        self.assertTrue(closed.is_set())
        self.assertTrue(ids)
        self.assertNotIn(main, ids)

    def test_no_thread_or_native_api_is_started_without_devices(self):
        factory = Mock()
        monitor = meter.InputActivityMonitor(factory)
        monitor.set_endpoints(())
        self.assertIsNone(monitor.thread)
        self.assertIsNone(monitor.snapshot())
        monitor.close()
        factory.assert_not_called()

    def test_endpoint_changes_invalidate_old_snapshot(self):
        entered = threading.Event()
        proceed = threading.Event()
        class Backend:
            def read(self, endpoints):
                entered.set()
                proceed.wait(1)
                return {key: -20 for key in endpoints}
            def close(self):
                pass
        monitor = meter.InputActivityMonitor(Backend, interval=10)
        self.addCleanup(monitor.close)
        self.addCleanup(proceed.set)
        monitor.set_endpoints(('old',))
        self.assertTrue(entered.wait(1))
        monitor.set_endpoints(())
        proceed.set()
        deadline = time.monotonic() + 1
        while monitor.snapshot() is None and time.monotonic() < deadline:
            time.sleep(0.005)
        sample = monitor.snapshot()
        self.assertTrue(sample is None or 'old' not in sample.peaks)

    def test_close_prevents_blocked_worker_from_publishing_a_late_snapshot(self):
        entered = threading.Event()
        proceed = threading.Event()
        backend_closed = threading.Event()

        class Backend:
            def read(self, endpoints):
                entered.set()
                proceed.wait(2)
                return {key: -8.0 for key in endpoints}

            def close(self):
                backend_closed.set()

        monitor = meter.InputActivityMonitor(Backend, interval=10)
        monitor.set_endpoints(('mic-a',))
        self.assertTrue(entered.wait(1))
        closer = threading.Thread(target=monitor.close)
        closer.start()
        closer.join(2)
        self.assertFalse(closer.is_alive())
        self.assertIsNone(monitor.snapshot())

        proceed.set()
        self.assertTrue(backend_closed.wait(1))
        self.assertIsNone(monitor.snapshot())


if __name__ == '__main__':
    unittest.main()
