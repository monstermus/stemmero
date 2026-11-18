"""Regression probes for selecting Windows' active capture endpoint."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import stemmero
from microphone_selection import build_input_devices
from input_meter import InputSample
from signal_selection import SignalSelector


class ActiveMicrophoneIntegrationTests(unittest.TestCase):
    def test_windows_default_change_opens_its_endpoint_not_stale_portaudio_default(self):
        """A Windows endpoint change can leave PortAudio's default index stale."""
        app = stemmero.App.__new__(stemmero.App)
        app.cfg = {"device_mode": "auto", "device_label": ""}
        app.mic = Mock()
        app.mic.running.return_value = True
        app.devices = []
        app.device_combo = Mock()
        app.device_var = Mock()
        app.status = Mock()
        app.selected_device = None
        app.device_signature = ("old-endpoint", ("old-endpoint", "new-endpoint"))
        app.next_device_check = 0
        app.next_retry = 0

        inventory = build_input_devices(
            [
                {"name": "Old wireless headset", "max_input_channels": 1, "hostapi": 0},
                {"name": "Active USB headset", "max_input_channels": 1, "hostapi": 1},
            ],
            [{"name": "MME"}, {"name": "Windows WASAPI"}],
        )
        endpoint_by_portaudio_index = {0: "old-endpoint", 1: "new-endpoint"}

        with (
            patch.object(stemmero, "windows_input_signature",
                         return_value=("new-endpoint", ("new-endpoint",))),
            patch.object(stemmero, "input_devices", return_value=inventory),
            patch.object(stemmero, "windows_capture_device_ids",
                         return_value=endpoint_by_portaudio_index, create=True),
            patch.object(stemmero.sd, "default", SimpleNamespace(device=(0, 0))),
            patch.object(stemmero.sd, "_terminate"),
            patch.object(stemmero.sd, "_initialize"),
        ):
            app._check_microphone(10)

        # Windows now reports only endpoint 1 as active, while PortAudio
        # still reports the stale index 0 as its default input.
        app.mic.start.assert_called_once_with(1)


class SignalMicrophoneIntegrationTests(unittest.TestCase):
    def app(self):
        app = stemmero.App.__new__(stemmero.App)
        app.cfg = {'device_mode': 'auto', 'device_label': ''}
        app.devices = [(0, 'Default headset'), (1, 'Mic receiving audio')]
        app.device_signature = ('default', ('default', 'receiving'))
        app.input_endpoint_ids = {0: 'default', 1: 'receiving'}
        app.selected_device = app.devices[0]
        app.signal_endpoint_id = None
        app.signal_selector = SignalSelector()
        app.input_activity = Mock()
        app.next_signal_check = 0
        app.audio = SimpleNamespace(until=0)
        app.test_until = 0
        app.preview_until = 0
        app.mic = Mock()
        app.mic.running.return_value = True
        app.device_var = Mock()
        app.status = Mock()
        return app

    def feed(self, app, at, peaks, **kwargs):
        app.next_signal_check = 0
        app.input_activity.snapshot.return_value = InputSample(peaks, at)
        app._check_signal_activity(kwargs.get('read_at', at + 0.01))

    def test_audio_signal_overrides_windows_default_in_real_stream_start(self):
        app = self.app()
        with patch.object(stemmero.sd, 'default', SimpleNamespace(device=(0, 0))):
            for at in (10, 10.2, 10.4, 10.6, 10.8, 11, 11.2):
                self.feed(app, at, {'default': -120, 'receiving': -20})
        app.mic.start.assert_called_once_with(1)
        self.assertEqual(app.selected_device, app.devices[1])
        self.assertEqual(app.signal_endpoint_id, 'receiving')
        self.assertIn('registreret lyd', app.status.configure.call_args.kwargs['text'])

    def test_speech_with_short_pauses_selects_the_receiving_microphone(self):
        app = self.app()
        levels = (-20, -20, -120, -20, -20, -120, -20, -20, -20, -20, -20, -20)
        with patch.object(stemmero.sd, 'default', SimpleNamespace(device=(0, 0))):
            for step, level in enumerate(levels):
                self.feed(app, 10 + step * 0.2, {'default': -120, 'receiving': level})
        app.mic.start.assert_called_once_with(1)

    def test_manual_choice_is_never_overridden_by_signal(self):
        app = self.app()
        app.cfg['device_mode'] = 'manual'
        self.feed(app, 10, {'default': -120, 'receiving': -20})
        app.input_activity.set_endpoints.assert_called_once_with(())
        app.mic.start.assert_not_called()

    def test_silence_keeps_current_and_does_not_switch_on_one_spike(self):
        app = self.app()
        self.feed(app, 10, {'default': -120, 'receiving': -5})
        for at in (10.2, 10.4, 10.6, 11, 11.2):
            self.feed(app, at, {'default': -120, 'receiving': -120})
        app.mic.start.assert_not_called()

    def test_old_meter_snapshots_never_qualify_a_candidate(self):
        app = self.app()
        for now in (10, 10.2, 10.4, 10.6, 10.8, 11.2):
            self.feed(app, 1, {'default': -120, 'receiving': -10}, read_at=now)
        app.mic.start.assert_not_called()

    def test_warning_playback_and_preview_do_not_select_echo_from_another_mic(self):
        for kind in ('audio', 'preview', 'banner'):
            with self.subTest(kind=kind):
                app = self.app()
                if kind == 'audio':
                    app.audio.until = 20
                elif kind == 'preview':
                    app.preview_until = 20
                else:
                    app.test_until = 20
                for at in (10, 10.2, 10.4, 10.6, 10.8, 11.2):
                    self.feed(app, at, {'default': -120, 'receiving': -10})
                app.mic.start.assert_not_called()

    def test_signal_choice_can_work_without_a_default_signature(self):
        app = self.app()
        app.device_signature = None
        with patch.object(stemmero.sd, 'default', SimpleNamespace(device=(0, 0))):
            for at in (10, 10.2, 10.4, 10.6, 10.8, 11, 11.2):
                self.feed(app, at, {'default': -120, 'receiving': -20})
        app.mic.start.assert_called_once_with(1)

if __name__ == "__main__":
    unittest.main()
