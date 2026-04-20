# Per-App Audio Capture: Windows 11 COM invariants and hard-won gotchas

These are invariants for `app/recording/_process_com.py` and `app/recording/process_audio_capture.py`. Each one bit us during bring-up on Windows 11 Build 26200; violating them reproduces `E_ILLEGAL_METHOD_CALL` (`0x8000000E`) or silent silence.

## Completion handler must implement `IAgileObject`

`ActivateAudioInterfaceAsync` refuses handlers that aren't apartment-neutral and fails **synchronously** with `0x8000000E`. WRL's `RuntimeClass` marks C++ handlers `IAgileObject` automatically. `comtypes.COMObject` does NOT — you must list it:

```python
class _CompletionHandler(comtypes.COMObject):
    _com_interfaces_ = [
        IActivateAudioInterfaceCompletionHandler,
        IAgileObject,    # marker interface, no methods — apartment-neutrality
    ]
```

## Virtual device path is a literal string, NOT a GUID

Per `mmdeviceapi.h`: `#define VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK L"VAD\\Process_Loopback"`. Passing a braced GUID here returns `0x8000000E` synchronously. Our constant is `"VAD\\Process_Loopback"` (Python string with one backslash).

## ctypes arg passing: use `c_void_p` + manual `ctypes.cast`

`ActivateAudioInterfaceAsync.argtypes` is `[c_wchar_p, c_void_p, c_void_p, c_void_p, c_void_p]`. Raw pointer addresses are extracted via `ctypes.cast(ptr, c_void_p).value` and passed as integers. `POINTER(Interface)` argtypes combined with `comtypes.COMObject` instances produce silent coercion failures across comtypes versions — don't use them for C-style API calls.

## Never cache a COM-packet generator

`ProcessCaptureStream._drain_real_source` re-enters `read_next_packet` on every `read_available()` call. A generator that `return`s once is permanently dead — caching one made the stream go silent after the first empty tick. If a COM packet drain loop feels "idiomatic to make a generator", resist.

## HRESULT `0x8000000E` = `E_ILLEGAL_METHOD_CALL`, not a device error

Generic-facility severity-only HRESULT meaning "precondition violated / object in wrong state". Three different PIDs returning the same `0x8000000E` synchronously means a handler or argument config bug — not PID-specific. Check IAgileObject, device path, handler QueryInterface, and PROPVARIANT layout in that order.

## `comtypes.COMObject` subclass methods don't take `this`

The vtable `this` pointer is handled by comtypes internally. Declare methods with only the IDL arg list:

```python
def ActivateCompleted(self, activate_operation):  # no `this` parameter
    ...
```

Adding `this` as a positional arg shifts the real args by one and silently breaks the callback.

## Capture pipeline structure (for orientation)

- `ProcessCaptureStream.activate()` is synchronous. It owns the COM objects for one PID (`_client`, `_capture_client`, `_native_frame_bytes`, resampler).
- `ProcessAudioCapture` owns the single 10 ms polling thread. PIDs are locked at `start()` — no live add/remove.
- Partial activation is tolerated: `start()` returns `{"total": N, "active": K, "failures": {pid: hresult_name}}` and `DualAudioCapture.start()` only raises when `active == 0`.
- `DualAudioCapture` dispatches: `capture_mode == "per_app" and app_pids` → `ProcessAudioCapture`; otherwise → `LoopbackStream` (legacy). The attribute is `self.system_stream` on both branches.
- System activates BEFORE mic in `DualAudioCapture.start()` so an all-PIDs-failed raise doesn't leave the mic orphaned.

## Re-enabling per-step diagnostic logs

Routine logs live at DEBUG. One-line INFO per success. To see full activation trace (apartment, pointer values, each COM call):

```python
import logging
logging.getLogger("app.recording._process_com").setLevel(logging.DEBUG)
```
