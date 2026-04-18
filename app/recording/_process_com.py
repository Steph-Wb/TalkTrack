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


import comtypes
from comtypes import GUID, COMMETHOD, IUnknown
from ctypes import POINTER, byref, c_void_p, c_int32, c_uint32, c_uint64, c_wchar_p


# IActivateAudioInterfaceCompletionHandler
IID_IActivateAudioInterfaceCompletionHandler = GUID(
    "{41D949AB-9862-444A-80F6-C261334DA5EB}"
)

# IActivateAudioInterfaceAsyncOperation
IID_IActivateAudioInterfaceAsyncOperation = GUID(
    "{72A22D78-CDE4-431D-B8CC-843A71199B6D}"
)

# IAudioClient (standard WASAPI IID).
IID_IAudioClient = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")

# IAudioCaptureClient.
IID_IAudioCaptureClient = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = IID_IActivateAudioInterfaceCompletionHandler
    _methods_ = [
        COMMETHOD(
            [], comtypes.HRESULT, "ActivateCompleted",
            (["in"], POINTER(IUnknown), "activateOperation"),
        ),
    ]


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = IID_IActivateAudioInterfaceAsyncOperation
    _methods_ = [
        COMMETHOD(
            [], comtypes.HRESULT, "GetActivateResult",
            (["out"], POINTER(comtypes.HRESULT), "activateResult"),
            (["out"], POINTER(POINTER(IUnknown)), "activatedInterface"),
        ),
    ]


class _CompletionHandler(comtypes.COMObject):
    """Python COM object that signals a Win32 event when activation completes."""
    _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler]

    def __init__(self, event_handle):
        super().__init__()
        self._event = event_handle

    def ActivateCompleted(self, this, activate_operation):
        ctypes.windll.kernel32.SetEvent(self._event)
        return 0   # S_OK


def activate_process_loopback(pid, timeout_ms=5000):
    """Synchronously activate an IAudioClient for per-process loopback.

    Returns (audio_client: IUnknown-pointer, hresult: int).
    On success, hresult == S_OK (0) and audio_client is non-null.
    On failure, audio_client is None and hresult is the error code.
    """
    # Ensure MTA init on this thread.
    ctypes.windll.ole32.CoInitializeEx(None, 0x0)  # COINIT_MULTITHREADED

    # Build params.
    params = AUDIOCLIENT_ACTIVATION_PARAMS()
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
    params.ProcessLoopbackParams.TargetProcessId = pid
    params.ProcessLoopbackParams.ProcessLoopbackMode = (
        PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
    )

    # Wrap as PROPVARIANT(VT_BLOB). The BLOB holds (cbSize, pBlobData).
    # comtypes doesn't expose PROPVARIANT blob construction; build via ctypes.
    class _BLOB(ctypes.Structure):
        _fields_ = [("cbSize", c_uint32), ("pBlobData", c_void_p)]

    class _PROPVARIANT(ctypes.Structure):
        _fields_ = [
            ("vt", ctypes.c_ushort),
            ("wReserved1", ctypes.c_ushort),
            ("wReserved2", ctypes.c_ushort),
            ("wReserved3", ctypes.c_ushort),
            ("blob", _BLOB),
            # Pad to full size (16 bytes on 32-bit, 24 on 64-bit).
            ("_pad", ctypes.c_ubyte * 8),
        ]

    pv = _PROPVARIANT()
    pv.vt = 0x41   # VT_BLOB
    pv.blob.cbSize = ctypes.sizeof(params)
    pv.blob.pBlobData = ctypes.cast(ctypes.pointer(params), c_void_p)

    # Create a manual-reset event for the handler to signal.
    event_handle = ctypes.windll.kernel32.CreateEventW(None, True, False, None)
    if not event_handle:
        return None, -1

    handler = _CompletionHandler(event_handle)

    # Call ActivateAudioInterfaceAsync. Use WinDLL (not OleDLL) so we get the
    # raw HRESULT back rather than an auto-raise — we want to translate failures
    # into last_error strings, not exceptions.
    mmdev = ctypes.WinDLL("Mmdevapi.dll")
    ActivateAudioInterfaceAsync = mmdev.ActivateAudioInterfaceAsync
    ActivateAudioInterfaceAsync.restype = ctypes.c_long
    ActivateAudioInterfaceAsync.argtypes = [
        c_wchar_p, POINTER(GUID), c_void_p,
        POINTER(IActivateAudioInterfaceCompletionHandler),
        POINTER(POINTER(IActivateAudioInterfaceAsyncOperation)),
    ]
    operation = POINTER(IActivateAudioInterfaceAsyncOperation)()
    hr = ActivateAudioInterfaceAsync(
        VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
        byref(IID_IAudioClient),
        ctypes.cast(ctypes.pointer(pv), c_void_p),
        handler,
        byref(operation),
    )
    if hr != 0:
        ctypes.windll.kernel32.CloseHandle(event_handle)
        return None, hr

    # Block until the completion handler fires.
    wait_result = ctypes.windll.kernel32.WaitForSingleObject(event_handle, timeout_ms)
    ctypes.windll.kernel32.CloseHandle(event_handle)
    if wait_result != 0:
        return None, -2   # WAIT_TIMEOUT or WAIT_ABANDONED

    # Pull the activated interface. comtypes returns [out] params as a tuple.
    activate_hr, activated = operation.GetActivateResult()
    if activate_hr != 0:
        return None, activate_hr & 0xFFFFFFFF
    return activated, 0


def read_next_packet(capture_client):
    """Drain the next available packet from an IAudioCaptureClient.

    Returns (data: bytes or None, frames: int, flags: int, hr: int).
    data is None when no packet is ready OR when AUDCLNT_E_DEVICE_INVALIDATED.
    Caller distinguishes by checking hr.
    """
    # Stub body — full implementation uses GetNextPacketSize + GetBuffer +
    # ctypes.string_at + ReleaseBuffer. Fully typed via comtypes IAudioCaptureClient.
    # See design doc Section "COM Integration / read_available() inner loop".
    raise NotImplementedError(
        "read_next_packet must be implemented against IAudioCaptureClient; "
        "see Section 2 of the design doc. For now, ProcessCaptureStream can "
        "inject a fake for tests."
    )
