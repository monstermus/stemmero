from array import array
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

import warning_audio as audio


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.backend = Mock(SND_FILENAME=1, SND_ASYNC=2, SND_NODEFAULT=4)
        self.clock = Mock(return_value=100.0)
        self.player = audio.WarningAudio(self.backend, self.clock)

    def wav(self, name='custom.wav', seconds=1, channels=1, width=2):
        path = self.root / name
        with wave.open(str(path), 'wb') as sound:
            sound.setnchannels(channels)
            sound.setsampwidth(width)
            sound.setframerate(8000)
            sound.writeframes(b'\0' * int(8000 * seconds) * channels * width)
        return path

    def test_all_bundled_voices_are_non_silent_pcm(self):
        for key in audio.SOUND_KEYS:
            with self.subTest(key=key):
                path = audio.default_sound(key)
                self.assertGreater(audio.wav_duration(path), 0.5)
                self.assertLess(audio.wav_duration(path), 6)
                with wave.open(str(path), 'rb') as sound:
                    self.assertEqual(sound.getsampwidth(), 2)
                    samples = array('h', sound.readframes(sound.getnframes()))
                self.assertGreater(max(abs(value) for value in samples), 100)

    def test_custom_sound_survives_removal_of_original(self):
        source = self.wav()
        imported = audio.import_custom_sound(source, 'orange', self.root / 'settings')
        source.unlink()
        self.assertTrue(self.player.play('orange', imported))
        self.backend.PlaySound.assert_called_once_with(imported, 7)

    def test_each_level_has_its_own_imported_copy(self):
        source = self.wav()
        yellow = audio.import_custom_sound(source, 'yellow', self.root / 'settings')
        red = audio.import_custom_sound(source, 'red', self.root / 'settings')
        self.assertNotEqual(yellow, red)
        self.assertEqual(Path(yellow).read_bytes(), Path(red).read_bytes())

    def test_invalid_import_preserves_previous_file(self):
        source = self.wav()
        imported = Path(audio.import_custom_sound(source, 'yellow', self.root / 'settings'))
        previous = imported.read_bytes()
        broken = self.root / 'broken.wav'
        broken.write_text('not audio')
        with self.assertRaises(ValueError):
            audio.import_custom_sound(broken, 'yellow', self.root / 'settings')
        self.assertEqual(imported.read_bytes(), previous)

    def test_rejects_other_formats_and_unplayable_wav(self):
        for path in (self.wav('fake.mp3'), self.wav('empty.wav', seconds=0),
                     self.wav('long.wav', seconds=31), self.wav('surround.wav', channels=6),
                     self.wav('wide.wav', width=3)):
            with self.subTest(path=path.name), self.assertRaises(ValueError):
                audio.wav_duration(path)

    def test_rejects_oversized_and_truncated_files(self):
        path = self.wav()
        with patch.object(audio, 'MAX_BYTES', 10), self.assertRaises(ValueError):
            audio.wav_duration(path)
        path.write_bytes(path.read_bytes()[:-100])
        with self.assertRaisesRegex(ValueError, 'ufuldstændig'):
            audio.wav_duration(path)

    def test_missing_custom_file_uses_default(self):
        self.assertTrue(self.player.play('red', self.root / 'missing.wav'))
        self.assertEqual(self.backend.PlaySound.call_args.args[0], str(audio.default_sound('red')))
        self.assertIn('Standardstemmen', self.player.last_error)

    def test_playback_error_uses_default(self):
        self.backend.PlaySound.side_effect = [RuntimeError('cannot decode'), None]
        self.assertTrue(self.player.play('yellow', self.wav()))
        self.assertEqual(self.backend.PlaySound.call_count, 2)
        self.assertIn('Standardstemmen', self.player.last_error)

    def test_repeat_does_not_restart_a_playing_clip(self):
        self.player.play('yellow')
        self.assertFalse(self.player.play('yellow'))
        self.assertEqual(self.backend.PlaySound.call_count, 1)
        self.clock.return_value = 200
        self.assertTrue(self.player.play('yellow'))
        self.assertEqual(self.backend.PlaySound.call_count, 2)

    def test_long_clip_is_not_restarted_before_playback_actually_finishes(self):
        path = self.wav(seconds=30)
        # Filkontrol og Windows' opstart af lyden kan tage tid.
        self.backend.PlaySound.side_effect = lambda *_: setattr(self.clock, 'return_value', 101.0)
        self.assertTrue(self.player.play('red', path))
        self.backend.PlaySound.side_effect = None
        self.clock.return_value = 130.5
        self.assertFalse(self.player.play('red', path))
        self.assertEqual(self.backend.PlaySound.call_count, 1)
        self.clock.return_value = 131.1
        self.assertTrue(self.player.play('red', path))

    def test_red_interrupts_yellow_and_lower_levels_wait(self):
        self.player.play('yellow')
        self.assertTrue(self.player.play('red'))
        self.assertFalse(self.player.play('orange'))
        self.assertEqual(self.backend.PlaySound.call_count, 2)

    def test_preview_can_interrupt_and_stop_resets_playback(self):
        self.player.play('red')
        self.assertTrue(self.player.play('yellow', preview=True))
        self.player.stop()
        self.backend.PlaySound.assert_called_with(None, 0)
        self.assertEqual(self.player.until, 0)
        self.assertEqual(self.player.priority, -1)

    def test_no_audio_device_does_not_crash(self):
        self.backend.PlaySound.side_effect = RuntimeError('no device')
        self.assertFalse(self.player.play('red'))
        self.assertIn('no device', self.player.last_error)
        self.player.stop()

    def test_frozen_app_uses_its_bundled_assets(self):
        with patch.object(audio.sys, '_MEIPASS', str(self.root), create=True):
            self.assertEqual(audio.default_sound('yellow'), self.root / 'assets/sounds/yellow.wav')


if __name__ == '__main__':
    unittest.main()
