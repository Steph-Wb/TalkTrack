"""Windows 11 process-loopback COM shim.

This module owns ctypes struct definitions, GUID constants, HRESULT name
mapping, and the thin wrappers that call into comtypes. It exists as a
separate file because mocking these is a high-effort/low-signal rabbit hole
- downstream code injects fakes for the activate/read functions when testing.
"""

# HRESULT codes from Audioclient.h / winerror.h. Add more as needed.
# Reference: https://learn.microsoft.com/en-us/windows/win32/api/audioclient/
_HRESULT_NAMES = {
    0x00000000: "S_OK",
    0x80004001: "E_NOTIMPL",
    0x80004002: "E_NOINTERFACE",
    0x80004003: "E_POINTER",
    0x80004004: "E_ABORT",
    0x80004005: "E_FAIL",
    0x80070005: "E_ACCESSDENIED",
    0x80070057: "E_INVALIDARG",
    0x80070490: "ERROR_NOT_FOUND_HRESULT",
    # AUDCLNT_ERR codes (AUDCLNT severity bits = 0x8889xxxx)
    0x88890001: "AUDCLNT_E_NOT_INITIALIZED",
    0x88890002: "AUDCLNT_E_ALREADY_INITIALIZED",
    0x88890003: "AUDCLNT_E_WRONG_ENDPOINT_TYPE",
    0x88890004: "AUDCLNT_E_DEVICE_INVALIDATED",
    0x88890005: "AUDCLNT_E_NOT_STOPPED",
    0x88890006: "AUDCLNT_E_BUFFER_TOO_LARGE",
    0x88890008: "AUDCLNT_E_OUT_OF_ORDER",
    0x88890009: "AUDCLNT_E_UNSUPPORTED_FORMAT",
    0x8889000A: "AUDCLNT_E_INVALID_SIZE",
    0x8889000B: "AUDCLNT_E_DEVICE_IN_USE",
    0x8889000C: "AUDCLNT_E_BUFFER_OPERATION_PENDING",
    0x88890017: "AUDCLNT_E_CPUUSAGE_EXCEEDED",
    0x88890021: "AUDCLNT_E_RESOURCES_INVALIDATED",
}


def hresult_name(hr):
    """Map an HRESULT to a symbolic name, falling back to hex for unknowns."""
    # Normalize signed ints returned by ctypes (-0x77767FFC → 0x88890004).
    hr_u32 = hr & 0xFFFFFFFF
    if hr_u32 in _HRESULT_NAMES:
        return _HRESULT_NAMES[hr_u32]
    return f"0x{hr_u32:08X}"


import ctypes
from ctypes import wintypes


# --- Constants from audioclient.h / audioclientactivationparams.h ---

# Virtual device string for process-loopback activation. This is a stable GUID
# string; not an interface IID.
VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "{8FDC6FBC-56CC-4DA6-B4FA-9CB9F1E09B72}"

# AUDIOCLIENT_ACTIVATION_TYPE enum.
AUDIOCLIENT_ACTIVATION_TYPE_DEFAULT = 0
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1

# PROCESS_LOOPBACK_MODE enum.
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE = 1

# IAudioClient::Initialize flags.
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_SHAREMODE_SHARED = 0

# WAVE_FORMAT tags.
WAVE_FORMAT_PCM = 0x0001
WAVE_FORMAT_IEEE_FLOAT = 0x0003

# AUDCLNT_BUFFERFLAGS bits.
AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY = 0x1
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
AUDCLNT_BUFFERFLAGS_TIMESTAMP_ERROR = 0x4

# GetNextPacketSize / GetBuffer status hints.
AUDCLNT_S_BUFFER_EMPTY = 0x08890001

# Common HRESULTs for activation (32-bit unsigned form).
AUDCLNT_E_DEVICE_INVALIDATED = 0x88890004
E_ACCESSDENIED = 0x80070005


# --- Struct definitions ---

class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(ctypes.Structure):
    _fields_ = [
        ("TargetProcessId", wintypes.DWORD),
        ("ProcessLoopbackMode", wintypes.DWORD),  # PROCESS_LOOPBACK_MODE enum
    ]


class AUDIOCLIENT_ACTIVATION_PARAMS(ctypes.Structure):
    """Passed as a PROPVARIANT(VT_BLOB) to ActivateAudioInterfaceAsync."""
    _fields_ = [
        ("ActivationType", wintypes.DWORD),
        ("ProcessLoopbackParams", AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS),
    ]


class WAVEFORMATEX(ctypes.Structure):
    """WAVEFORMATEX as defined in mmreg.h."""
    _pack_ = 1
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


def make_format_ieee_float(sample_rate=48000, channels=2, bits=32):
    """Build a WAVEFORMATEX for IEEE_FLOAT PCM."""
    fmt = WAVEFORMATEX()
    fmt.wFormatTag = WAVE_FORMAT_IEEE_FLOAT
    fmt.nChannels = channels
    fmt.nSamplesPerSec = sample_rate
    fmt.wBitsPerSample = bits
    fmt.nBlockAlign = (channels * bits) // 8
    fmt.nAvgBytesPerSec = sample_rate * fmt.nBlockAlign
    fmt.cbSize = 0
    return fmt
