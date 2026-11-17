"""Current default audio endpoints, asked from the Windows Core Audio API (ctypes, no extra deps).

PortAudio keeps the device list it read at initialisation for as long as any stream of the
process is open, so it cannot notice that Windows switched the default device (headphones
plugged in, a new default chosen in Settings). The capture watchdog compares these ids instead.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import POINTER, byref, c_long, c_uint, c_void_p

RENDER, CAPTURE = 0, 1  # EDataFlow: eRender (speakers -> loopback), eCapture (microphones)
_MULTIMEDIA = 1  # ERole: eMultimedia, the role PortAudio's WASAPI defaults follow
_CLSCTX_INPROC_SERVER = 0x1
_COINIT_MULTITHREADED = 0x0


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(text: str) -> _GUID:
    g = _GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(g))
    return g


def _vcall(obj: int, index: int, argtypes: tuple = (), *args) -> int:
    """Call method `index` of the COM interface pointer `obj` (index 2 = Release)."""
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
    fn = ctypes.WINFUNCTYPE(c_long, c_void_p, *argtypes)(vtbl[index])
    return fn(obj, *args)


_CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_GET_DEFAULT_AUDIO_ENDPOINT = 4  # IMMDeviceEnumerator vtable slot
_GET_ID = 5  # IMMDevice vtable slot
_RELEASE = 2


def default_endpoint_id(flow: int) -> str | None:
    """Id of the current default endpoint for `flow` (RENDER or CAPTURE).

    None when there is no such device or the query fails (also on non-Windows)."""
    if sys.platform != "win32":
        return None
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx.restype = c_long
    ole32.CoCreateInstance.restype = c_long
    hr = ole32.CoInitializeEx(None, _COINIT_MULTITHREADED)
    initialised = hr in (0, 1)  # S_OK / S_FALSE; otherwise COM is already set up differently
    enum, dev, text = c_void_p(), c_void_p(), c_void_p()
    try:
        clsid, iid = _guid(_CLSID_MMDeviceEnumerator), _guid(_IID_IMMDeviceEnumerator)
        if ole32.CoCreateInstance(byref(clsid), None, _CLSCTX_INPROC_SERVER, byref(iid), byref(enum)) != 0:
            return None
        hr = _vcall(
            enum.value, _GET_DEFAULT_AUDIO_ENDPOINT, (c_uint, c_uint, POINTER(c_void_p)),
            flow, _MULTIMEDIA, byref(dev),
        )
        if hr != 0 or not dev.value:
            return None  # E_NOTFOUND: no device of this kind
        if _vcall(dev.value, _GET_ID, (POINTER(c_void_p),), byref(text)) != 0 or not text.value:
            return None
        return ctypes.wstring_at(text.value)
    except OSError:
        return None
    finally:
        if text.value:
            ole32.CoTaskMemFree(text)
        for obj in (dev, enum):
            if obj.value:
                _vcall(obj.value, _RELEASE)
        if initialised:
            ole32.CoUninitialize()
