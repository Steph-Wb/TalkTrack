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


if __name__ == "__main__":
    unittest.main()
