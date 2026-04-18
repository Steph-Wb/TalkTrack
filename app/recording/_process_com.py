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
