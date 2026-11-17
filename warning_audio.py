"""Afspil danske advarsler og importer brugerens WAV-filer lokalt."""
from pathlib import Path
import os
import sys
import tempfile
import time
import wave

try:
    import winsound
except ImportError:
    winsound = None

SOUND_KEYS = ('yellow', 'orange', 'red')
SPOKEN_MESSAGES = {
    'yellow': 'Du taler lidt for højt.',
    'orange': 'Du taler for højt. Skru ned for stemmen.',
    'red': 'Du taler alt for højt. Tal lavere nu.',
}
MAX_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 30


def default_sound(key):
    if key not in SOUND_KEYS:
        raise ValueError('Ukendt advarselsniveau')
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return root / 'assets' / 'sounds' / f'{key}.wav'


def wav_duration(path):
    """Kontrollér format og filindhold før import og afspilning."""
    path = Path(path)
    if path.suffix.lower() != '.wav':
        raise ValueError('Vælg en WAV-fil.')
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Lydfilen må højst fylde 10 MB.')
    try:
        with wave.open(str(path), 'rb') as sound:
            frames = sound.getnframes()
            rate = sound.getframerate()
            if sound.getnchannels() not in (1, 2) or sound.getsampwidth() not in (1, 2):
                raise ValueError('Brug en ukomprimeret WAV-fil med 8- eller 16-bit PCM-lyd.')
            if not 8000 <= rate <= 192000 or frames <= 0:
                raise ValueError('WAV-filen indeholder ingen gyldig lyd.')
            duration = frames / rate
            if duration > MAX_SECONDS:
                raise ValueError('Lyden må højst vare 30 sekunder.')
            expected = frames * sound.getnchannels() * sound.getsampwidth()
            if len(sound.readframes(frames)) != expected:
                raise ValueError('WAV-filen er beskadiget eller ufuldstændig.')
    except (wave.Error, EOFError) as error:
        raise ValueError('Brug en ukomprimeret WAV-fil med PCM-lyd.') from error
    return duration


def import_custom_sound(source, key, config_dir):
    """Gem en kopi, så den valgte originalfil kan flyttes bagefter."""
    if key not in SOUND_KEYS:
        raise ValueError('Ukendt advarselsniveau')
    wav_duration(source)
    folder = Path(config_dir) / 'sounds'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'{key}.wav'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=folder, suffix='.wav', delete=False) as out:
            temporary = Path(out.name)
            out.write(Path(source).read_bytes())
        wav_duration(temporary)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(target.resolve())


class WarningAudio:
    """Afspil uden at blokere vinduet eller overlappe advarsler."""

    def __init__(self, backend=winsound, clock=time.monotonic):
        self.backend = backend
        self.clock = clock
        self.until = 0.0
        self.priority = -1
        self.last_error = ''

    def play(self, key, custom_path='', preview=False):
        priority = SOUND_KEYS.index(key)
        now = self.clock()
        if not preview and now < self.until and priority <= self.priority:
            return False
        self.last_error = ''
        if self.backend is None:
            self.last_error = 'Afspilning af advarselslyde kræver Windows.'
            return False
        candidates = [Path(custom_path)] if custom_path else []
        candidates.append(default_sound(key))
        for path in candidates:
            try:
                duration = wav_duration(path)
                flags = self.backend.SND_FILENAME | self.backend.SND_ASYNC | self.backend.SND_NODEFAULT
                self.backend.PlaySound(str(path.resolve()), flags)
            except (OSError, ValueError, RuntimeError) as error:
                self.last_error = f'Lyden kunne ikke afspilles: {error}'
                continue
            self.until = self.clock() + duration
            self.priority = priority
            if custom_path and path != Path(custom_path):
                self.last_error = 'Din lyd kunne ikke afspilles. Standardstemmen bruges.'
            return True
        return False

    def stop(self):
        if self.backend is not None:
            try:
                self.backend.PlaySound(None, 0)
            except RuntimeError:
                pass
        self.until = 0.0
        self.priority = -1
