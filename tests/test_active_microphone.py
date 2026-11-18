"""Regression probes for selecting Windows' active capture endpoint."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import stemmero
from microphone_selection import build_input_devices


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


if __name__ == "__main__":
    unittest.main()
