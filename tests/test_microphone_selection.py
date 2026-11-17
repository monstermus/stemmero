import ctypes
import sys
import unittest
from unittest.mock import Mock, patch

import microphone_selection as selection
from microphone_selection import build_input_devices, choose_input_device


class MicrophoneSelectionTests(unittest.TestCase):
    def setUp(self):
        self.devices = [(0, 'Laptop  [MME]'), (3, 'USB Headset  [WASAPI]')]

    def test_windows_default_wins_over_previous_selection_and_headset(self):
        self.assertEqual(choose_input_device(self.devices, 0, self.devices[1][1]), self.devices[0])

    def test_auto_follows_a_changed_default_while_both_inputs_exist(self):
        self.assertEqual(choose_input_device(self.devices, 0), self.devices[0])
        self.assertEqual(choose_input_device(self.devices, 3), self.devices[1])

    def test_unplug_and_replug_recalculates_auto_without_saving_fallback(self):
        preferred = self.devices[1]
        self.assertEqual(choose_input_device(self.devices, preferred[0]), preferred)
        self.assertEqual(choose_input_device(self.devices[:1], preferred[0]), self.devices[0])
        self.assertEqual(choose_input_device(self.devices, preferred[0]), preferred)

    def test_manual_selection_stays_when_the_windows_default_changes(self):
        self.assertEqual(choose_input_device(self.devices, 0, self.devices[1][1], 'manual'), self.devices[1])

    def test_missing_manual_preference_is_not_replaced_by_its_fallback(self):
        saved_label = self.devices[1][1]
        self.assertEqual(choose_input_device(self.devices[:1], 0, saved_label, 'manual'), self.devices[0])
        self.assertEqual(saved_label, self.devices[1][1])
        self.assertEqual(choose_input_device(self.devices, 0, saved_label, 'manual'), self.devices[1])

    def test_malformed_or_missing_defaults_use_headset(self):
        for default in (None, -1, -99, 999, '3', 3.0, True, object()):
            with self.subTest(default=default):
                self.assertEqual(choose_input_device(self.devices, default), self.devices[1])

    def test_danish_headset_name_is_recognized(self):
        devices = [(0, 'Indbygget mikrofon'), (1, 'Bluetooth-hovedsæt')]
        self.assertEqual(choose_input_device(devices, -1), devices[1])

    def test_no_headset_or_default_uses_first_valid_input(self):
        devices = [(5, 'Ekstern mikrofon'), (9, 'Indbygget mikrofon')]
        self.assertEqual(choose_input_device(devices, -1), devices[0])

    def test_no_inputs_returns_none(self):
        self.assertIsNone(choose_input_device([], 0))

    def test_unknown_mode_uses_automatic_selection(self):
        self.assertEqual(choose_input_device(self.devices, 0, self.devices[1][1], 'invalid'), self.devices[0])

    def test_bad_or_duplicate_input_records_are_ignored(self):
        devices = [(True, 'Bad'), (-1, 'Bad'), (3.5, 'Bad'), (0, ''), (0, None), (), 'bad', (3, 'Input'), (3, 'Duplicate')]
        self.assertEqual(choose_input_device(devices, 3), (3, 'Input'))

    def test_enumeration_filters_output_and_preserves_global_indices(self):
        raw = [
            {'name': 'Speakers', 'hostapi': 0, 'max_input_channels': 0},
            {'name': 'Laptop', 'hostapi': 0, 'max_input_channels': 2},
            {'name': 'Headphones', 'hostapi': 1, 'max_input_channels': 0},
            {'name': 'USB Headset', 'hostapi': 1, 'max_input_channels': 1},
        ]
        devices = build_input_devices(raw, [{'name': 'MME'}, {'name': 'WASAPI'}])
        self.assertEqual(devices, [(1, 'Laptop  [MME]'), (3, 'USB Headset  [WASAPI]')])
        self.assertEqual(choose_input_device(devices, 2), devices[1])

    def test_same_device_name_in_different_host_apis_remains_distinct(self):
        raw = [
            {'name': 'Headset', 'hostapi': 0, 'max_input_channels': 1},
            {'name': 'Headset', 'hostapi': 1, 'max_input_channels': 1},
        ]
        devices = build_input_devices(raw, [{'name': 'MME'}, {'name': 'WASAPI'}])
        self.assertNotEqual(devices[0][1], devices[1][1])
        self.assertEqual(choose_input_device(devices, 1), devices[1])

    def test_identical_names_in_one_api_get_unique_manual_choices(self):
        raw = [{'name': 'Headset', 'hostapi': 0, 'max_input_channels': 1}] * 2
        devices = build_input_devices(raw, [{'name': 'WASAPI'}])
        self.assertNotEqual(devices[0][1], devices[1][1])
        self.assertEqual(choose_input_device(devices, 0, devices[1][1], 'manual'), devices[1])

    def test_malformed_metadata_cannot_produce_output_choices(self):
        raw = [None, {'name': 'Bad', 'max_input_channels': '1'}, {'name': 'Bad', 'max_input_channels': -1},
               {'name': 'Bad', 'max_input_channels': True}, {'name': '', 'hostapi': -1, 'max_input_channels': 1}]
        self.assertEqual(build_input_devices(raw, []), [(4, 'Mikrofon 5  [Ukendt lydsystem]')])


class WindowsInputSignatureTests(unittest.TestCase):
    def adapter(self, default='default-input', active=('input-b', 'default-input', 'input-b')):
        devices = Mock()
        devices.__enter__ = Mock(return_value=devices)
        devices.__exit__ = Mock(return_value=False)
        devices.default_id.return_value = default
        devices.active_ids.return_value = active
        return devices

    def test_signature_is_stable_when_enumeration_order_changes(self):
        devices = self.adapter()
        with patch.object(selection.sys, 'platform', 'win32'), patch.object(selection, '_WindowsCaptureDevices', return_value=devices):
            before = selection.windows_input_signature()
            devices.active_ids.return_value = ('default-input', 'input-b')
            self.assertEqual(selection.windows_input_signature(), before)
        self.assertEqual(before, ('default-input', ('default-input', 'input-b')))
        self.assertEqual(devices.__exit__.call_count, 2)

    def test_default_change_and_unplug_replug_change_the_token(self):
        devices = self.adapter()
        with patch.object(selection.sys, 'platform', 'win32'), patch.object(selection, '_WindowsCaptureDevices', return_value=devices):
            before = selection.windows_input_signature()
            devices.default_id.return_value = 'input-b'
            self.assertNotEqual(selection.windows_input_signature(), before)
            devices.default_id.return_value = None
            devices.active_ids.return_value = ()
            self.assertEqual(selection.windows_input_signature(), (None, ()))
            devices.default_id.return_value = 'default-input'
            devices.active_ids.return_value = ('default-input', 'input-b')
            self.assertEqual(selection.windows_input_signature(), before)

    def test_failures_return_none_and_close_the_adapter(self):
        for error in (OSError('MMDevice unavailable'), AttributeError('unsupported'), ValueError('invalid result')):
            with self.subTest(error=type(error).__name__):
                devices = self.adapter()
                devices.active_ids.side_effect = error
                with patch.object(selection.sys, 'platform', 'win32'), patch.object(selection, '_WindowsCaptureDevices', return_value=devices):
                    self.assertIsNone(selection.windows_input_signature())
                devices.__exit__.assert_called_once()

    def test_other_platform_does_not_load_windows_dlls(self):
        with patch.object(selection.sys, 'platform', 'linux'), patch.object(selection, '_WindowsCaptureDevices') as factory:
            self.assertIsNone(selection.windows_input_signature())
        factory.assert_not_called()

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows MMDevice API')
    def test_native_windows_enumeration(self):
        signature = selection.windows_input_signature()
        if signature is None:
            self.skipTest('MMDevice API is unavailable on this Windows runner')
        default, active = signature
        self.assertTrue(default is None or isinstance(default, str))
        self.assertIsInstance(active, tuple)
        self.assertEqual(active, tuple(sorted(set(active))))
        self.assertTrue(all(isinstance(identifier, str) and identifier for identifier in active))


class WindowsComLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.ole32 = Mock()
        self.ole32.CoInitializeEx.return_value = 0
        self.ole32.CoCreateInstance.side_effect = self.create_instance
        self.released = []
        self.allocations = []
        self.empty = False
        self.fail_get_id = False

    @staticmethod
    def set_pointer(output, value):
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = value

    def create_instance(self, _clsid, _outer, _context, _iid, output):
        self.set_pointer(output, 10)
        return 0

    def com_call(self, interface, slot, _types, *arguments):
        address = interface.value
        if slot == 2:
            self.released.append(address)
            return 0
        if (address, slot) == (10, 4):
            self.assertEqual(arguments[:2], (1, 1))
            if self.empty:
                return ctypes.c_int32(selection._E_NOTFOUND).value
            self.set_pointer(arguments[-1], 30)
        elif (address, slot) == (10, 3):
            self.assertEqual(arguments[:2], (1, 1))
            self.set_pointer(arguments[-1], 20)
        elif (address, slot) == (20, 3):
            ctypes.cast(arguments[0], ctypes.POINTER(ctypes.c_uint32))[0] = 0 if self.empty else 1
        elif (address, slot) == (20, 4):
            self.set_pointer(arguments[-1], 40)
        elif slot == 5 and address in (30, 40):
            identifier = ctypes.create_unicode_buffer('input-endpoint')
            self.allocations.append(identifier)
            self.set_pointer(arguments[0], ctypes.addressof(identifier))
            if self.fail_get_id:
                return ctypes.c_int32(0x80004005).value
        else:
            self.fail(f'Unexpected COM call: {address}, {slot}')
        return 0

    def test_enumeration_releases_all_interfaces_and_allocated_ids(self):
        with patch.object(selection, '_com_call', side_effect=self.com_call):
            with selection._WindowsCaptureDevices(self.ole32) as devices:
                self.assertEqual(devices.default_id(), 'input-endpoint')
                self.assertEqual(devices.active_ids(), ['input-endpoint'])
        self.assertEqual(self.released, [30, 40, 20, 10])
        self.assertEqual(self.ole32.CoTaskMemFree.call_count, 2)
        self.ole32.CoUninitialize.assert_called_once()

    def test_no_audio_is_a_valid_empty_snapshot(self):
        self.empty = True
        with patch.object(selection, '_com_call', side_effect=self.com_call):
            with selection._WindowsCaptureDevices(self.ole32) as devices:
                self.assertIsNone(devices.default_id())
                self.assertEqual(devices.active_ids(), [])
        self.assertEqual(self.released, [20, 10])
        self.ole32.CoTaskMemFree.assert_not_called()
        self.ole32.CoUninitialize.assert_called_once()

    def test_get_id_failure_still_frees_id_and_releases_interfaces(self):
        self.fail_get_id = True
        with patch.object(selection, '_com_call', side_effect=self.com_call):
            with self.assertRaises(OSError):
                with selection._WindowsCaptureDevices(self.ole32) as devices:
                    devices.active_ids()
        self.assertEqual(self.released, [40, 20, 10])
        self.ole32.CoTaskMemFree.assert_called_once()
        self.ole32.CoUninitialize.assert_called_once()

    def test_changed_apartment_does_not_uninitialize_someone_elses_com(self):
        self.ole32.CoInitializeEx.return_value = ctypes.c_int32(selection._RPC_E_CHANGED_MODE).value
        with patch.object(selection, '_com_call', side_effect=self.com_call):
            with selection._WindowsCaptureDevices(self.ole32):
                pass
        self.assertEqual(self.released, [10])
        self.ole32.CoUninitialize.assert_not_called()

    def test_already_initialized_thread_is_balanced_and_close_is_idempotent(self):
        self.ole32.CoInitializeEx.return_value = 1
        with patch.object(selection, '_com_call', side_effect=self.com_call):
            with selection._WindowsCaptureDevices(self.ole32) as devices:
                pass
            devices.close()
        self.assertEqual(self.released, [10])
        self.ole32.CoUninitialize.assert_called_once()

    def test_failed_creation_still_uninitializes_the_thread(self):
        self.ole32.CoCreateInstance.side_effect = None
        self.ole32.CoCreateInstance.return_value = ctypes.c_int32(0x80004005).value
        with self.assertRaises(OSError):
            with selection._WindowsCaptureDevices(self.ole32):
                self.fail('Failed creation must not enter the context')
        self.ole32.CoUninitialize.assert_called_once()

    def test_failed_initialization_does_not_create_or_uninitialize(self):
        self.ole32.CoInitializeEx.return_value = ctypes.c_int32(0x80004005).value
        with self.assertRaises(OSError):
            with selection._WindowsCaptureDevices(self.ole32):
                self.fail('Failed initialization must not enter the context')
        self.ole32.CoCreateInstance.assert_not_called()
        self.ole32.CoUninitialize.assert_not_called()

    def test_native_vtable_marshalling_uses_pointer_sized_interfaces(self):
        prototype = getattr(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE)
        callback_type = prototype(ctypes.c_int32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))

        @callback_type
        def count_method(_this, output):
            output[0] = 123
            return 0

        table = (ctypes.c_void_p * 4)()
        table[3] = ctypes.cast(count_method, ctypes.c_void_p)
        interface = ctypes.pointer(ctypes.cast(table, ctypes.POINTER(ctypes.c_void_p)))
        count = ctypes.c_uint32()
        status = selection._com_call(ctypes.cast(interface, ctypes.c_void_p), 3,
                                     (ctypes.POINTER(ctypes.c_uint32),), ctypes.byref(count))
        self.assertEqual(status, 0)
        self.assertEqual(count.value, 123)
        self.assertEqual(ctypes.sizeof(selection._GUID), 16)


if __name__ == '__main__':
    unittest.main()
