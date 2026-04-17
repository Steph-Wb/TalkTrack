"""Tests for TranscriptSegment and TranscriptResult."""
import unittest
from app.transcription.transcriber import TranscriptSegment, TranscriptResult


class TestTranscriptSegment(unittest.TestCase):

    def test_to_dict_without_original_text(self):
        seg = TranscriptSegment(start=1.0, end=2.0, text="hello")
        d = seg.to_dict()
        self.assertEqual(d["text"], "hello")
        self.assertNotIn("original_text", d)

    def test_to_dict_with_original_text(self):
        seg = TranscriptSegment(start=1.0, end=2.0, text="Q4", original_text="quarterly")
        d = seg.to_dict()
        self.assertEqual(d["text"], "Q4")
        self.assertEqual(d["original_text"], "quarterly")

    def test_to_dict_with_empty_original_text_omits_it(self):
        seg = TranscriptSegment(start=1.0, end=2.0, text="hello", original_text="")
        d = seg.to_dict()
        self.assertNotIn("original_text", d)

    def test_from_dict_with_original_text(self):
        """TranscriptSegment(**dict) should accept original_text."""
        data = {"start": 1.0, "end": 2.0, "text": "Q4", "original_text": "quarterly",
                "speaker": "", "confidence": 0.0}
        seg = TranscriptSegment(**data)
        self.assertEqual(seg.original_text, "quarterly")

    def test_from_dict_without_original_text(self):
        data = {"start": 1.0, "end": 2.0, "text": "hello", "speaker": "", "confidence": 0.0}
        seg = TranscriptSegment(**data)
        self.assertEqual(seg.original_text, "")

    def test_from_dict_ignores_unknown_keys(self):
        """from_dict should ignore extra keys like speaker_name."""
        data = {"start": 1.0, "end": 2.0, "text": "hello", "speaker": "SPEAKER_00",
                "confidence": 0.9, "speaker_name": "Alice", "extra_field": 42}
        seg = TranscriptSegment.from_dict(data)
        self.assertEqual(seg.text, "hello")
        self.assertEqual(seg.speaker, "SPEAKER_00")
        self.assertFalse(hasattr(seg, "speaker_name"))


class TestTranscriptResultExports(unittest.TestCase):

    def _make_result(self):
        return TranscriptResult(
            segments=[
                TranscriptSegment(start=0.0, end=5.0, text="Hello everyone", speaker="SPEAKER_00"),
                TranscriptSegment(start=5.0, end=10.0, text="Hi there", speaker="SPEAKER_01"),
            ],
            language="en",
            duration=10.0,
        )

    def test_to_text_without_speaker_names(self):
        result = self._make_result()
        text = result.to_text()
        self.assertIn("[SPEAKER_00]", text)
        self.assertIn("[SPEAKER_01]", text)

    def test_to_text_with_speaker_names(self):
        result = self._make_result()
        names = {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}
        text = result.to_text(speaker_names=names)
        self.assertIn("[Alice]", text)
        self.assertIn("[Bob]", text)
        self.assertNotIn("SPEAKER_00", text)

    def test_to_text_with_partial_speaker_names(self):
        result = self._make_result()
        names = {"SPEAKER_00": "Alice"}
        text = result.to_text(speaker_names=names)
        self.assertIn("[Alice]", text)
        self.assertIn("[SPEAKER_01]", text)

    def test_to_srt_with_speaker_names(self):
        result = self._make_result()
        names = {"SPEAKER_00": "Alice"}
        srt = result.to_srt(speaker_names=names)
        self.assertIn("[Alice]", srt)
        self.assertIn("[SPEAKER_01]", srt)

    def test_to_dict_with_speaker_names(self):
        result = self._make_result()
        names = {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}
        d = result.to_dict(speaker_names=names)
        self.assertEqual(d["segments"][0]["speaker_name"], "Alice")
        self.assertEqual(d["segments"][1]["speaker_name"], "Bob")
        # Original speaker IDs preserved
        self.assertEqual(d["segments"][0]["speaker"], "SPEAKER_00")

    def test_to_dict_without_speaker_names_has_no_speaker_name_key(self):
        result = self._make_result()
        d = result.to_dict()
        self.assertNotIn("speaker_name", d["segments"][0])


class TestToPlainText(unittest.TestCase):
    """TranscriptResult.to_plain_text: clipboard-friendly, no timestamps."""

    def _make_result(self, segs):
        return TranscriptResult(segments=segs, language="en", duration=10.0)

    def test_empty_transcript_returns_empty_string(self):
        r = self._make_result([])
        self.assertEqual(r.to_plain_text(), "")

    def test_uses_raw_speaker_id_when_no_name_mapping(self):
        segs = [TranscriptSegment(0.0, 1.0, "Hi there.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        self.assertEqual(r.to_plain_text(), "SPEAKER_00: Hi there.")

    def test_uses_friendly_name_when_provided(self):
        segs = [TranscriptSegment(0.0, 1.0, "Hi there.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        out = r.to_plain_text(speaker_names={"SPEAKER_00": "Alice"})
        self.assertEqual(out, "Alice: Hi there.")

    def test_empty_friendly_name_falls_back_to_raw_id(self):
        segs = [TranscriptSegment(0.0, 1.0, "Hi.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        out = r.to_plain_text(speaker_names={"SPEAKER_00": ""})
        self.assertEqual(out, "SPEAKER_00: Hi.")

    def test_segment_without_speaker_has_no_prefix(self):
        segs = [TranscriptSegment(0.0, 1.0, "Unidentified line.")]
        r = self._make_result(segs)
        self.assertEqual(r.to_plain_text(), "Unidentified line.")

    def test_blank_line_between_speaker_changes(self):
        segs = [
            TranscriptSegment(0.0, 1.0, "One.", speaker="SPEAKER_00"),
            TranscriptSegment(1.0, 2.0, "Two.", speaker="SPEAKER_00"),
            TranscriptSegment(2.0, 3.0, "Three.", speaker="SPEAKER_01"),
            TranscriptSegment(3.0, 4.0, "Four.", speaker="SPEAKER_00"),
        ]
        r = self._make_result(segs)
        names = {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}
        out = r.to_plain_text(speaker_names=names)
        expected = (
            "Alice: One.\n"
            "Alice: Two.\n"
            "\n"
            "Bob: Three.\n"
            "\n"
            "Alice: Four."
        )
        self.assertEqual(out, expected)

    def test_no_timestamps_in_output(self):
        segs = [
            TranscriptSegment(0.0, 1.5, "Hello.", speaker="SPEAKER_00"),
            TranscriptSegment(1.5, 3.0, "World.", speaker="SPEAKER_00"),
        ]
        r = self._make_result(segs)
        out = r.to_plain_text(speaker_names={"SPEAKER_00": "Alice"})
        # No digits-colon-digits timestamps and no square brackets
        self.assertNotIn("[", out)
        self.assertNotIn("]", out)
        self.assertNotIn("->", out)

    def test_no_trailing_newline(self):
        segs = [TranscriptSegment(0.0, 1.0, "Hi.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        out = r.to_plain_text()
        self.assertFalse(out.endswith("\n"))

    def test_text_is_stripped_of_leading_whitespace(self):
        """Whisper often emits leading spaces on segment text."""
        segs = [TranscriptSegment(0.0, 1.0, " Hello.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        self.assertEqual(r.to_plain_text(), "SPEAKER_00: Hello.")


if __name__ == "__main__":
    unittest.main()
