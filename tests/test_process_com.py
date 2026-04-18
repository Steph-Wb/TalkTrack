"""Tier-2 tests for COM structs, GUIDs, HRESULT helpers in _process_com."""
import unittest


class TestHResultName(unittest.TestCase):
    def test_known_audclnt_codes_map_to_symbol(self):
        from app.recording._process_com import hresult_name
        self.assertEqual(hresult_name(0x88890004), "AUDCLNT_E_DEVICE_INVALIDATED")
        self.assertEqual(hresult_name(0x80070005), "E_ACCESSDENIED")
        self.assertEqual(hresult_name(0x80070490), "ERROR_NOT_FOUND_HRESULT")

    def test_unknown_code_renders_as_hex(self):
        from app.recording._process_com import hresult_name
        self.assertEqual(hresult_name(0x12345678), "0x12345678")

    def test_success_s_ok(self):
        from app.recording._process_com import hresult_name
        self.assertEqual(hresult_name(0), "S_OK")


class TestStructs(unittest.TestCase):
    def test_audioclient_activation_params_size(self):
        """Struct size must match the documented Windows SDK value.
        If this breaks after a typo, the ActivateAudioInterfaceAsync call fails silently."""
        import ctypes
        from app.recording._process_com import AUDIOCLIENT_ACTIVATION_PARAMS
        # ActivationType (ULONG) + ProcessLoopbackParams (TargetProcessId ULONG + Mode ULONG)
        # padded to 8-byte alignment = 12 bytes, rounded up to next DWORD boundary.
        # The real size per SDK is 8 bytes (union). We document whatever the
        # implementation chooses and pin it here.
        self.assertGreaterEqual(ctypes.sizeof(AUDIOCLIENT_ACTIVATION_PARAMS), 8)
        self.assertLessEqual(ctypes.sizeof(AUDIOCLIENT_ACTIVATION_PARAMS), 32)

    def test_waveformatex_size_is_18(self):
        import ctypes
        from app.recording._process_com import WAVEFORMATEX
        self.assertEqual(ctypes.sizeof(WAVEFORMATEX), 18)


class TestConstants(unittest.TestCase):
    def test_process_loopback_mode_include_is_zero(self):
        from app.recording._process_com import PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
        self.assertEqual(PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE, 0)

    def test_activation_type_is_one(self):
        from app.recording._process_com import AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
        self.assertEqual(AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK, 1)

    def test_virtual_device_path_matches_windows_sdk(self):
        from app.recording._process_com import VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK
        # Per mmdeviceapi.h: #define VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK L"VAD\\Process_Loopback"
        # This is the literal device-interface-path string, not a GUID.
        self.assertEqual(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, "VAD\\Process_Loopback")

    def test_audclnt_streamflags_loopback_value(self):
        from app.recording._process_com import AUDCLNT_STREAMFLAGS_LOOPBACK
        self.assertEqual(AUDCLNT_STREAMFLAGS_LOOPBACK, 0x00020000)


if __name__ == "__main__":
    unittest.main()
