"""Læs mikrofonernes niveauer i en worker uden at optage eller gemme lyd."""
from dataclasses import dataclass
import ctypes
import math
import sys
import threading
import time

from microphone_selection import (
    _GUID, _POINTER, _POINTER_OUT, _UINT,
    _WindowsCaptureDevices, _check_hresult, _com_call, _release,
)

_IID_AUDIO_METER = _GUID.parse('C02216F6-8C67-4B5B-9D00-D008E73E0064')
_IID_AUDIO_ENDPOINT_VOLUME = _GUID.parse('5CDF2C82-841E-4546-9722-0CF74078229A')
_SILENCE_DBFS = -120.0


@dataclass
class _EndpointInterfaces:
    meter: ctypes.c_void_p
    volume: ctypes.c_void_p | None


class WindowsCapturePeakBackend:
    """Alle COM-objekter oprettes, bruges og frigives på samme tråd."""

    def __init__(self, context_factory=_WindowsCaptureDevices, clock=time.monotonic):
        self.factory = context_factory
        self.clock = clock
        self.context = None
        self.devices = None
        self.meters: dict[str, _EndpointInterfaces] = {}
        self.retry = {}
        self.context_retry = 0.0

    def _open(self, identifier):
        endpoint, peak_meter, volume = _POINTER(), _POINTER(), _POINTER()
        try:
            _check_hresult(_com_call(self.devices.enumerator, 5,
                                    (ctypes.c_wchar_p, _POINTER_OUT), identifier, ctypes.byref(endpoint)))
            if not endpoint:
                raise OSError('Windows returnerede ingen mikrofon')
            _check_hresult(_com_call(endpoint, 3,
                                    (ctypes.POINTER(_GUID), _UINT, _POINTER, _POINTER_OUT),
                                    ctypes.byref(_IID_AUDIO_METER), 23, None, ctypes.byref(peak_meter)))
            if not peak_meter:
                raise OSError('Mikrofonens niveaumåler er ikke tilgængelig')
            try:
                _check_hresult(_com_call(endpoint, 3,
                                        (ctypes.POINTER(_GUID), _UINT, _POINTER, _POINTER_OUT),
                                        ctypes.byref(_IID_AUDIO_ENDPOINT_VOLUME), 23, None,
                                        ctypes.byref(volume)))
                if not volume:
                    volume = _POINTER()
            except (OSError, AttributeError, ValueError):
                _release(volume)
                volume = _POINTER()
            interfaces = _EndpointInterfaces(peak_meter, volume if volume else None)
            peak_meter, volume = _POINTER(), _POINTER()
            return interfaces
        except (OSError, AttributeError, ValueError):
            self._release_interfaces(_EndpointInterfaces(peak_meter, volume))
            raise
        finally:
            _release(endpoint)

    @staticmethod
    def _release_interfaces(interfaces):
        if interfaces is None:
            return
        for interface in (interfaces.meter, interfaces.volume):
            if interface:
                try:
                    _release(interface)
                except (OSError, AttributeError, ValueError):
                    pass

    def _close_context(self):
        for interfaces in self.meters.values():
            self._release_interfaces(interfaces)
        self.meters.clear()
        context, self.context = self.context, None
        self.devices = None
        if context is not None:
            try:
                context.__exit__(None, None, None)
            except (OSError, AttributeError, ValueError):
                pass

    def read(self, endpoint_ids):
        identifiers = tuple(sorted({item for item in endpoint_ids if isinstance(item, str) and item}))
        if not identifiers:
            self.close()
            return {}
        if sys.platform != 'win32':
            return None
        now = self.clock()
        if self.devices is None:
            if now < self.context_retry:
                return None
            try:
                context = self.factory()
                self.devices = context.__enter__()
                self.context = context
            except (OSError, AttributeError, ValueError):
                self.context_retry = now + 5
                return None
        for identifier in set(self.meters) - set(identifiers):
            self._release_interfaces(self.meters.pop(identifier))
        self.retry = {key: value for key, value in self.retry.items() if key in identifiers}
        levels = {}
        for identifier in identifiers:
            if now < self.retry.get(identifier, 0):
                continue
            try:
                if identifier not in self.meters:
                    self.meters[identifier] = self._open(identifier)
                interfaces = self.meters[identifier]
                muted = False
                volume_db = None
                if interfaces.volume:
                    try:
                        mute_value = ctypes.c_int32()
                        _check_hresult(_com_call(interfaces.volume, 15,
                                                (ctypes.POINTER(ctypes.c_int32),),
                                                ctypes.byref(mute_value)))
                        muted = bool(mute_value.value)
                    except (OSError, AttributeError, ValueError):
                        muted = False
                    if muted:
                        levels[identifier] = _SILENCE_DBFS
                        continue
                    try:
                        volume_level = ctypes.c_float()
                        _check_hresult(_com_call(interfaces.volume, 8,
                                                (ctypes.POINTER(ctypes.c_float),),
                                                ctypes.byref(volume_level)))
                        if volume_level.value == -math.inf:
                            volume_db = _SILENCE_DBFS
                        elif math.isfinite(volume_level.value):
                            volume_db = volume_level.value
                    except (OSError, AttributeError, ValueError):
                        volume_db = None
                peak = ctypes.c_float()
                _check_hresult(_com_call(interfaces.meter, 3,
                                        (ctypes.POINTER(ctypes.c_float),), ctypes.byref(peak)))
                if not math.isfinite(peak.value) or not 0 <= peak.value <= 1:
                    raise ValueError('Ugyldigt mikrofonniveau')
                if peak.value == 0:
                    levels[identifier] = _SILENCE_DBFS
                    continue
                level = 20 * math.log10(peak.value)
                if volume_db is not None:
                    level += volume_db
                levels[identifier] = max(_SILENCE_DBFS, min(0.0, level))
            except (OSError, AttributeError, ValueError):
                interfaces = self.meters.pop(identifier, None)
                self._release_interfaces(interfaces)
                self.retry[identifier] = now + 5
        if identifiers and not levels and all(identifier in self.retry for identifier in identifiers):
            self._close_context()
            self.context_retry = now + 5
        return levels

    def close(self):
        self._close_context()
        self.retry.clear()
        self.context_retry = 0.0


@dataclass(frozen=True)
class InputSample:
    peaks: dict[str, float]
    at: float


class InputActivityMonitor:
    """Send kun tal og måletid til GUI-tråden, aldrig lyd eller COM-pointere."""

    def __init__(self, backend_factory=WindowsCapturePeakBackend, clock=time.monotonic, interval=0.2):
        self.factory = backend_factory
        self.clock = clock
        self.interval = interval
        self.lock = threading.Lock()
        self.changed = threading.Event()
        self.stopping = threading.Event()
        self.endpoints = ()
        self.latest = None
        self.thread = None

    def set_endpoints(self, endpoint_ids):
        identifiers = tuple(sorted({item for item in endpoint_ids if isinstance(item, str) and item}))
        with self.lock:
            if identifiers != self.endpoints:
                self.endpoints = identifiers
                self.latest = None
                self.changed.set()
            if identifiers and self.thread is None and not self.stopping.is_set():
                self.thread = threading.Thread(target=self._run, daemon=True, name='Stemmero-input-meter')
                self.thread.start()

    def snapshot(self, max_age=1.0):
        with self.lock:
            if self.latest is None or self.clock() - self.latest.at > max_age:
                return None
            return InputSample(dict(self.latest.peaks), self.latest.at)

    def _run(self):
        backend = self.factory()
        try:
            while not self.stopping.is_set():
                self.changed.clear()
                with self.lock:
                    identifiers = self.endpoints
                try:
                    levels = backend.read(identifiers)
                except (OSError, AttributeError, ValueError):
                    levels = None
                sample = InputSample(levels, self.clock()) if isinstance(levels, dict) else None
                with self.lock:
                    if not self.stopping.is_set() and self.endpoints == identifiers:
                        self.latest = sample
                self.changed.wait(self.interval if identifiers else None)
        finally:
            backend.close()

    def close(self):
        with self.lock:
            self.stopping.set()
            self.latest = None
        self.changed.set()
        if self.thread is not None:
            self.thread.join(timeout=1)
