"""Unit tests for the collapsed-title suffix builders in source_selector."""
import unittest

from app.ui.source_selector import format_per_app_suffix, format_legacy_suffix


class TestFormatPerAppSuffix(unittest.TestCase):
    def test_empty_list_returns_no_apps_message(self):
        self.assertEqual(format_per_app_suffix([]), "(No apps selected)")

    def test_single_app(self):
        self.assertEqual(format_per_app_suffix(["Microsoft Teams"]), "(Microsoft Teams)")

    def test_two_apps_joined_with_comma(self):
        self.assertEqual(
            format_per_app_suffix(["Microsoft Teams", "Google Chrome"]),
            "(Microsoft Teams, Google Chrome)",
        )

    def test_three_apps_shows_plus_one_more(self):
        self.assertEqual(
            format_per_app_suffix(["Teams", "Chrome", "Zoom"]),
            "(Teams, Chrome +1 more)",
        )

    def test_many_apps_shows_plus_n_more(self):
        self.assertEqual(
            format_per_app_suffix(["A", "B", "C", "D", "E"]),
            "(A, B +3 more)",
        )


class TestFormatLegacySuffix(unittest.TestCase):
    def test_strips_wasapi_loopback_marker(self):
        self.assertEqual(
            format_legacy_suffix("Speakers (Realtek HD) (WASAPI Loopback)"),
            "(Speakers (Realtek HD))",
        )

    def test_preserves_device_name_without_marker(self):
        self.assertEqual(format_legacy_suffix("Speakers"), "(Speakers)")

    def test_preserves_parens_inside_device_name(self):
        self.assertEqual(
            format_legacy_suffix("Speakers (HP) (WASAPI Loopback)"),
            "(Speakers (HP))",
        )


if __name__ == "__main__":
    unittest.main()
