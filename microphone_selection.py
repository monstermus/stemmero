"""Vælg en mikrofon fra et nyt øjebliksbillede af lydenhederne."""
from collections import Counter
from collections.abc import Mapping, Sequence
import ctypes
import operator
import sys
import uuid


InputDevice = tuple[int, str]
_HEADSET_WORDS = ('headset', 'headphone', 'hovedsæt', 'hovedtelefon', 'earbud', 'hands-free', 'handsfree')


class _GUID(ctypes.Structure):
    _fields_ = [('data1', ctypes.c_uint32), ('data2', ctypes.c_uint16),
                ('data3', ctypes.c_uint16), ('data4', ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text):
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)


_CLSID_MMDEVICE_ENUMERATOR = _GUID.parse('BCDE0395-E52F-467C-8E3D-C4579291692E')
_IID_IMMDEVICE_ENUMERATOR = _GUID.parse('A95664D2-9614-4F35-A746-DE8DB63617E6')
_E_NOTFOUND = 0x80070490
_RPC_E_CHANGED_MODE = 0x80010106
_POINTER = ctypes.c_void_p
_POINTER_OUT = ctypes.POINTER(_POINTER)
_HRESULT = ctypes.c_int32
_UINT = ctypes.c_uint32


def _com_call(interface, slot, argtypes, *arguments):
    table = ctypes.cast(interface, ctypes.POINTER(ctypes.POINTER(_POINTER))).contents
    prototype = getattr(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE)
    method = prototype(_HRESULT, _POINTER, *argtypes)(table[slot])
    return method(interface, *arguments)


def _check_hresult(status):
    if status < 0:
        raise OSError(f'MMDevice API fejlede med 0x{status & 0xffffffff:08x}')


def _release(interface):
    if interface:
        _com_call(interface, 2, ())


class _WindowsCaptureDevices:
    """Læs MMDevice-endpoints uden at åbne eller afbryde en lydstrøm."""

    def __init__(self, ole32=None):
        self.ole32 = ole32 if ole32 is not None else ctypes.WinDLL('ole32', use_last_error=True)
        self.ole32.CoInitializeEx.argtypes = [_POINTER, _UINT]
        self.ole32.CoInitializeEx.restype = _HRESULT
        self.ole32.CoUninitialize.argtypes = []
        self.ole32.CoUninitialize.restype = None
        self.ole32.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), _POINTER, _UINT,
                                               ctypes.POINTER(_GUID), _POINTER_OUT]
        self.ole32.CoCreateInstance.restype = _HRESULT
        self.ole32.CoTaskMemFree.argtypes = [_POINTER]
        self.ole32.CoTaskMemFree.restype = None
        self.enumerator = _POINTER()
        self.initialized = False

    def __enter__(self):
        status = self.ole32.CoInitializeEx(None, 0)
        if status & 0xffffffff != _RPC_E_CHANGED_MODE:
            _check_hresult(status)
            self.initialized = True
        try:
            status = self.ole32.CoCreateInstance(
                ctypes.byref(_CLSID_MMDEVICE_ENUMERATOR), None, 1,
                ctypes.byref(_IID_IMMDEVICE_ENUMERATOR), ctypes.byref(self.enumerator))
            _check_hresult(status)
            if not self.enumerator:
                raise OSError('MMDevice API returnerede ingen enumerator')
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        enumerator, self.enumerator = self.enumerator, _POINTER()
        try:
            _release(enumerator)
        finally:
            if self.initialized:
                self.initialized = False
                self.ole32.CoUninitialize()

    def _endpoint_id(self, endpoint):
        identifier = _POINTER()
        try:
            _check_hresult(_com_call(endpoint, 5, (_POINTER_OUT,), ctypes.byref(identifier)))
            if not identifier:
                raise OSError('MMDevice API returnerede intet endpoint-ID')
            return ctypes.wstring_at(identifier)
        finally:
            if identifier:
                self.ole32.CoTaskMemFree(identifier)

    def default_id(self):
        endpoint = _POINTER()
        try:
            # eCapture = 1, eMultimedia = 1.
            status = _com_call(self.enumerator, 4, (ctypes.c_int, ctypes.c_int, _POINTER_OUT),
                               1, 1, ctypes.byref(endpoint))
            if status & 0xffffffff == _E_NOTFOUND:
                return None
            _check_hresult(status)
            if not endpoint:
                raise OSError('MMDevice API returnerede intet standardinput')
            return self._endpoint_id(endpoint)
        finally:
            _release(endpoint)

    def active_ids(self):
        collection = _POINTER()
        try:
            # eCapture = 1, DEVICE_STATE_ACTIVE = 1.
            _check_hresult(_com_call(self.enumerator, 3, (ctypes.c_int, _UINT, _POINTER_OUT),
                                    1, 1, ctypes.byref(collection)))
            if not collection:
                raise OSError('MMDevice API returnerede ingen inputliste')
            count = _UINT()
            _check_hresult(_com_call(collection, 3, (ctypes.POINTER(_UINT),), ctypes.byref(count)))
            result = []
            for index in range(count.value):
                endpoint = _POINTER()
                try:
                    _check_hresult(_com_call(collection, 4, (_UINT, _POINTER_OUT),
                                            index, ctypes.byref(endpoint)))
                    if not endpoint:
                        raise OSError('MMDevice API returnerede et tomt input')
                    result.append(self._endpoint_id(endpoint))
                finally:
                    _release(endpoint)
            return result
        finally:
            _release(collection)


def windows_input_signature() -> tuple[str | None, tuple[str, ...]] | None:
    """Returnér standardinput og aktive input-ID'er til ændringsdetektion.

    Et Windows-system uden mikrofon returnerer ``(None, ())``. Anden
    platform eller fejl returnerer ``None``. ID'erne bruges kun til
    ændringsdetektion og til at matche Windows' standardinput med et
    PortAudio WASAPI-input ved automatisk valg.
    """
    if sys.platform != 'win32':
        return None
    try:
        with _WindowsCaptureDevices() as devices:
            return devices.default_id(), tuple(sorted(set(devices.active_ids())))
    except (OSError, AttributeError, ValueError):
        return None


def windows_capture_device_ids(library_path, device_indices) -> dict[int, str] | None:
    """Map global PortAudio indexes to their WASAPI MMDevice IDs.

    Non-WASAPI indexes are skipped. The IMMDevice pointer returned by
    PortAudio is borrowed, so this function reads its ID without releasing
    the interface. ``None`` means the Windows extension could not be used.
    """
    if sys.platform != 'win32' or not library_path:
        return None

    try:
        library = ctypes.CDLL(library_path)
        get_imm_device = library.PaWasapi_GetIMMDevice
        get_imm_device.argtypes = [ctypes.c_int, _POINTER_OUT]
        get_imm_device.restype = _HRESULT
        ole32 = ctypes.WinDLL('ole32', use_last_error=True)
        ole32.CoInitializeEx.argtypes = [_POINTER, _UINT]
        ole32.CoInitializeEx.restype = _HRESULT
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None
        ole32.CoTaskMemFree.argtypes = [_POINTER]
        ole32.CoTaskMemFree.restype = None
    except (AttributeError, OSError, TypeError, ValueError):
        return None

    initialized = False
    try:
        status = ole32.CoInitializeEx(None, 0)
        if status & 0xffffffff != _RPC_E_CHANGED_MODE:
            _check_hresult(status)
            initialized = True

        result = {}
        for value in device_indices:
            index = _device_index(value)
            if index is None or index > 0x7fffffff:
                continue
            endpoint = _POINTER()
            status = get_imm_device(index, ctypes.byref(endpoint))
            if status < 0 or not endpoint:
                continue

            identifier = _POINTER()
            try:
                _check_hresult(_com_call(endpoint, 5, (_POINTER_OUT,), ctypes.byref(identifier)))
                if identifier:
                    result[index] = ctypes.wstring_at(identifier)
            except (OSError, AttributeError, ValueError):
                continue
            finally:
                if identifier:
                    ole32.CoTaskMemFree(identifier)
        return result
    except (OSError, AttributeError, TypeError, ValueError):
        return None
    finally:
        if initialized:
            ole32.CoUninitialize()


def _device_index(value):
    if isinstance(value, bool):
        return None
    try:
        index = operator.index(value)
    except TypeError:
        return None
    return index if index >= 0 else None


def build_input_devices(raw_devices: Sequence[Mapping], hostapis: Sequence[Mapping]) -> list[InputDevice]:
    """Bevar PortAudios globale indeks og giv kun inputenheder et navn."""
    inputs = []
    for index, device in enumerate(raw_devices):
        if not isinstance(device, Mapping):
            continue
        channels = _device_index(device.get('max_input_channels'))
        if not channels:
            continue
        name = device.get('name')
        name = name.strip() if isinstance(name, str) else ''
        name = name or f'Mikrofon {index + 1}'
        api_index = _device_index(device.get('hostapi'))
        api_name = 'Ukendt lydsystem'
        if api_index is not None and api_index < len(hostapis):
            api = hostapis[api_index]
            if isinstance(api, Mapping):
                candidate = api.get('name')
                if isinstance(candidate, str) and candidate.strip():
                    api_name = candidate.strip()
        inputs.append((index, f'{name}  [{api_name}]'))

    counts = Counter(label for _, label in inputs)
    result = []
    used = set()
    for index, label in inputs:
        if counts[label] > 1:
            label = f'{label} (enhed {index + 1})'
        while label in used:
            label = f'{label} #{index + 1}'
        used.add(label)
        result.append((index, label))
    return result


def choose_input_device(
    devices: Sequence[InputDevice],
    default_input,
    saved_label: str | None = None,
    mode: str = 'auto',
    *,
    windows_default_id: str | None = None,
    endpoint_ids: Mapping | None = None,
    active_endpoint_ids: Sequence[str] | None = None,
) -> InputDevice | None:
    """Vælg standardinput i auto, eller det gemte navn i manuel tilstand.

    Et manglende manuelt valg får et midlertidigt automatisk alternativ.
    Funktionen ændrer aldrig det gemte valg. Kald den igen med et nyt
    øjebliksbillede, når enheder eller Windows' standardinput ændres.
    Ukendt tilstand bruger automatisk valg.
    """
    available = []
    seen = set()
    for device in devices:
        if not isinstance(device, (tuple, list)) or len(device) != 2:
            continue
        index, label = device
        index = _device_index(index)
        if index is None or index in seen or not isinstance(label, str) or not label:
            continue
        seen.add(index)
        available.append((index, label))
    if not available:
        return None

    default_index = _device_index(default_input)
    active_snapshot = (
        isinstance(active_endpoint_ids, Sequence)
        and not isinstance(active_endpoint_ids, (str, bytes))
    )
    active_ids = (
        {identifier for identifier in active_endpoint_ids if isinstance(identifier, str)}
        if active_snapshot else None
    )
    endpoint_ids = endpoint_ids if isinstance(endpoint_ids, Mapping) else {}

    def endpoint_id(index):
        identifier = endpoint_ids.get(index)
        return identifier if isinstance(identifier, str) and identifier else None

    if active_snapshot and not active_ids:
        return None

    if mode == 'manual' and isinstance(saved_label, str):
        for device in available:
            if device[1] == saved_label:
                identifier = endpoint_id(device[0])
                if not active_snapshot or identifier is None or identifier in active_ids:
                    return device

    if active_snapshot and isinstance(windows_default_id, str):
        if windows_default_id in active_ids:
            for index, label in available:
                if endpoint_id(index) == windows_default_id:
                    return index, label

    if active_snapshot:
        active_devices = [device for device in available if endpoint_id(device[0]) in active_ids]
        for device in active_devices:
            if device[0] == default_index:
                return device
        if active_devices:
            return active_devices[0]

    default_device = next((device for device in available if device[0] == default_index), None)
    if default_device is not None:
        identifier = endpoint_id(default_device[0])
        if not active_snapshot or identifier is None or identifier in active_ids:
            return default_device

    fallback_devices = [
        device for device in available
        if not active_snapshot or endpoint_id(device[0]) is None or endpoint_id(device[0]) in active_ids
    ]
    for device in fallback_devices:
        if any(word in device[1].casefold() for word in _HEADSET_WORDS):
            return device
    return fallback_devices[0] if fallback_devices else None
