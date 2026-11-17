"""Tæl advarselsperioder og gem valgfri låsning eller nedlukning lokalt.

GUI-kalderen skal kræve forældre-PIN før configure() eller cancel().
Kun en eksplicit executor kan udføre Windows-handlinger. Den medfølgende
WindowsActions bruges aldrig automatisk af dette modul.
"""
from dataclasses import asdict, dataclass
import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


MAX_EVENTS = 1000
MAX_STATE_BYTES = 128 * 1024
MAX_COUNTDOWN = 600


class PolicyStateError(RuntimeError):
    """Konsekvensdata kunne ikke gemmes, så handlinger er sat på pause."""


@dataclass(frozen=True)
class PolicyConfig:
    enabled: bool = False
    count: int = 5
    window_seconds: int = 600
    action: str = 'lock'
    countdown_seconds: int = 60
    mode: str = 'all'
    quiet_seconds: float = 1.2

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError('enabled skal være sand eller falsk')
        for name, minimum, maximum in (
            ('count', 1, MAX_EVENTS), ('window_seconds', 1, 86400),
            ('countdown_seconds', 5, MAX_COUNTDOWN),
        ):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f'Ugyldig værdi for {name}')
        if self.action not in ('lock', 'shutdown'):
            raise ValueError('Vælg låsning eller nedlukning')
        if self.mode not in ('all', 'orange_red'):
            raise ValueError('Ukendt optælling af advarsler')
        if not _number(self.quiet_seconds) or not 0.1 <= self.quiet_seconds <= 30:
            raise ValueError('Ugyldig tid til at afslutte et udbrud')


@dataclass(frozen=True)
class PolicyStatus:
    count: int
    pending_action: str | None
    due_at: float | None
    remaining_seconds: int
    action_failed: bool
    error: str
    damaged: bool


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _timestamp(value):
    return _number(value) and 0 <= value <= 2 ** 53


class WarningPolicy:
    """Gem optælling og nedtælling, også når appen genstartes.

    observe() får et kvalificeret niveau -1, 0, 1 eller 2. quiet kan
    angive faktisk lydniveau under gul, så reaktionstid ikke tæller
    som stilhed. Et udbrud kan optrappes uden at tælle igen. Efter
    quiet_seconds under gul kan et nyt udbrud tælle.
    monitoring=False tæller intet og frigiver kun
    udbrudsmarkøren. Historik og en verserende handling bevares.
    """

    def __init__(self, path, config=None, clock=time.time, executor=None):
        if config is not None and not isinstance(config, PolicyConfig):
            raise TypeError('config skal være PolicyConfig')
        self.path = Path(path)
        self.clock = clock
        self.executor = executor
        self.config = config or PolicyConfig()
        self.damaged = False
        self._error = ''
        self._events = []
        self._episode_counted = False
        self._quiet_since = None
        self._pending = None
        self._last_at = 0.0
        self._last_seen = 0.0
        self._load(config)

    def _now(self):
        value = self.clock()
        if not _timestamp(value):
            raise ValueError('Ugyldigt tidspunkt')
        self._last_seen = max(float(value), self._last_at, self._last_seen)
        return self._last_seen

    def _load(self, override):
        try:
            if not self.path.exists():
                return
            if self.path.stat().st_size > MAX_STATE_BYTES:
                raise ValueError('Konsekvensfilen er for stor')
            state = json.loads(self.path.read_text(encoding='utf-8'))
            expected = {'version', 'config', 'events', 'episode_counted',
                        'quiet_since', 'pending', 'last_at', 'error'}
            if type(state) is not dict or set(state) != expected or state['version'] != 1:
                raise ValueError('Ukendt konsekvensformat')
            stored_config = state['config']
            if type(stored_config) is not dict:
                raise ValueError('Ugyldig konfiguration')
            loaded_config = PolicyConfig(**stored_config)
            last_at = state['last_at']
            if not _timestamp(last_at):
                raise ValueError('Ugyldigt tidspunkt')
            events = state['events']
            if type(events) is not list or len(events) > MAX_EVENTS:
                raise ValueError('Ugyldig advarselshistorik')
            if any(not _timestamp(event) or event > last_at for event in events):
                raise ValueError('Ugyldigt advarselstidspunkt')
            if events != sorted(events):
                raise ValueError('Historikken er ikke i tidsorden')
            if type(state['episode_counted']) is not bool:
                raise ValueError('Ugyldigt udbrud')
            quiet_since = state['quiet_since']
            if quiet_since is not None and (not _timestamp(quiet_since) or quiet_since > last_at):
                raise ValueError('Ugyldig stilhedsperiode')
            error = state['error']
            if type(error) is not str or len(error) > 1024:
                raise ValueError('Ugyldig fejltekst')
            pending = state['pending']
            if pending is not None:
                required = {'action', 'triggered_at', 'due_at', 'phase'}
                if type(pending) is not dict or set(pending) != required:
                    raise ValueError('Ugyldig verserende handling')
                trigger, due = pending['triggered_at'], pending['due_at']
                if pending['action'] not in ('lock', 'shutdown') or pending['phase'] not in ('ready', 'executing', 'failed'):
                    raise ValueError('Ukendt handling')
                if not _timestamp(trigger) or not _timestamp(due) or trigger > last_at:
                    raise ValueError('Ugyldigt handlingstidspunkt')
                if not trigger <= due <= trigger + MAX_COUNTDOWN:
                    raise ValueError('Ugyldig nedtælling')
                if pending['action'] == 'lock' and due != trigger:
                    raise ValueError('Ugyldigt låsningstidspunkt')
            self.config = override or loaded_config
            self._events = events
            self._last_at = float(last_at)
            self._episode_counted = state['episode_counted']
            self._quiet_since = quiet_since
            self._pending = pending
            self._error = error
            if not self.config.enabled:
                if loaded_config.enabled or events or pending or self._episode_counted or quiet_since is not None or error:
                    self._clear_disabled_state()
                    self._save(self._now())
            elif pending is not None and pending['phase'] == 'executing':
                self._pending['phase'] = 'failed'
                self._error = 'En handling blev afbrudt. En voksen skal nulstille konsekvensen.'
                self._save(self._now())
        except (OSError, ValueError, TypeError, KeyError, PolicyStateError) as error:
            self.damaged = True
            self._pending = None
            self._events = []
            self._error = f'Konsekvensdata kunne ikke læses: {error}'

    def _clear_disabled_state(self):
        self._events = []
        self._pending = None
        self._episode_counted = False
        self._quiet_since = None
        self._error = ''

    def _save(self, now):
        state = {
            'version': 1, 'config': asdict(self.config), 'events': self._events,
            'episode_counted': self._episode_counted, 'quiet_since': self._quiet_since,
            'pending': self._pending, 'last_at': now, 'error': self._error,
        }
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix=self.path.name + '.', delete=False) as output:
                temporary = Path(output.name)
                os.chmod(temporary, 0o600)
                json.dump(state, output, ensure_ascii=False, allow_nan=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            self._last_at = now
        except OSError as error:
            self.damaged = True
            self._error = 'Konsekvensdata kunne ikke gemmes. En voksen skal kontrollere indstillingerne.'
            raise PolicyStateError(self._error) from error
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    @property
    def status(self):
        now = self._now()
        cutoff = now - self.config.window_seconds
        pending = self._pending
        return PolicyStatus(
            count=sum(event > cutoff for event in self._events),
            pending_action=pending['action'] if pending else None,
            due_at=pending['due_at'] if pending else None,
            remaining_seconds=max(0, math.ceil(pending['due_at'] - now)) if pending else 0,
            action_failed=bool(pending and pending['phase'] == 'failed'),
            error=self._error, damaged=self.damaged,
        )

    def configure(self, config):
        """Kræver PIN-kontrol hos kalderen. Deaktivering annullerer alt."""
        if not isinstance(config, PolicyConfig):
            raise TypeError('config skal være PolicyConfig')
        if self.damaged and config.enabled:
            raise PolicyStateError('En voksen skal nulstille beskadigede konsekvensdata først.')
        if config == self.config and config.enabled:
            return self.status
        now = self._now()
        mode_changed = config.mode != self.config.mode
        self.config = config
        if not config.enabled:
            self._clear_disabled_state()
            self.damaged = False
        elif mode_changed and self._pending is None:
            self._events = []
            self._episode_counted = False
            self._quiet_since = None
        self._events = [event for event in self._events if event > now - config.window_seconds]
        self._save(now)
        return self.status

    def cancel(self):
        """Nulstil efter kalderens PIN-kontrol. Reparerer også en datafil."""
        now = self._now()
        self._events = []
        self._pending = None
        self._error = ''
        self.damaged = False
        self._save(now)
        return self.status

    def observe(self, level, monitoring=True, test=False, quiet=None):
        if type(level) is not int or level not in (-1, 0, 1, 2):
            raise ValueError('Niveauet skal være -1, 0, 1 eller 2')
        if quiet is not None and type(quiet) is not bool:
            raise ValueError('quiet skal være sand, falsk eller None')
        now = self._now()
        if self.damaged or test:
            return self.status
        if not monitoring:
            if self._episode_counted or self._quiet_since is not None:
                self._episode_counted = False
                self._quiet_since = None
                self._save(now)
            return self.status
        if not self.config.enabled:
            return self.status
        previous = (tuple(self._events), self._episode_counted, self._quiet_since)
        self._events = [event for event in self._events if event > now - self.config.window_seconds]
        is_quiet = level < 0 if quiet is None else quiet
        if is_quiet:
            if self._quiet_since is None:
                self._quiet_since = now
            if now - self._quiet_since >= self.config.quiet_seconds:
                self._episode_counted = False
        else:
            if self._quiet_since is not None and now - self._quiet_since >= self.config.quiet_seconds:
                self._episode_counted = False
            self._quiet_since = None
            minimum = 1 if self.config.mode == 'orange_red' else 0
            if level >= minimum and not self._episode_counted:
                self._episode_counted = True
                if self._pending is None:
                    self._events.append(now)
                    if len(self._events) >= self.config.count:
                        delay = self.config.countdown_seconds if self.config.action == 'shutdown' else 0
                        self._pending = {'action': self.config.action, 'triggered_at': now,
                                         'due_at': now + delay, 'phase': 'ready'}
        current = (tuple(self._events), self._episode_counted, self._quiet_since)
        if current != previous:
            self._save(now)
        return self.status

    def tick(self):
        """Anmod Windows om en forfalden handling højst én gang."""
        now = self._now()
        pending = self._pending
        if self.damaged or not self.config.enabled or pending is None or self.executor is None:
            return self.status
        if pending['phase'] != 'ready' or pending['due_at'] > now:
            return self.status
        pending['phase'] = 'executing'
        self._save(now)
        try:
            method = self.executor.lock if pending['action'] == 'lock' else self.executor.shutdown
            result = method()
            if result is False:
                raise OSError('Windows afviste handlingen')
        except Exception as error:
            pending['phase'] = 'failed'
            self._error = f'Handlingen kunne ikke startes: {error}'[:1024]
            self._save(now)
            return self.status
        self._events = []
        self._pending = None
        self._error = ''
        self._save(now)
        return self.status


class WindowsActions:
    """Anmod Windows om låsning eller almindelig nedlukning uden /f."""

    def lock(self):
        if sys.platform != 'win32':
            raise OSError('Låsning kræver Windows')
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.LockWorkStation.argtypes = []
        user32.LockWorkStation.restype = wintypes.BOOL
        if not user32.LockWorkStation():
            raise ctypes.WinError(ctypes.get_last_error())

    def shutdown(self):
        if sys.platform != 'win32':
            raise OSError('Nedlukning kræver Windows')
        executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'shutdown.exe'
        subprocess.run([str(executable), '/s', '/t', '0'], check=True, capture_output=True,
                       text=True, creationflags=0x08000000)
