import unittest
import json


class TestSummaryPromptBuilder(unittest.TestCase):
    def test_build_summary_prompt(self):
        from app.ai.summarizer import build_summary_prompt
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(0.0, 5.0, "Let's discuss the budget.", speaker="Alice"),
            TranscriptSegment(5.0, 10.0, "I think we need more funding.", speaker="Bob"),
        ]
        prompt = build_summary_prompt(segments, {"Alice": "Alice", "Bob": "Bob"})
        self.assertIn("Alice", prompt)
        self.assertIn("budget", prompt)

    def test_build_summary_prompt_with_notes(self):
        from app.ai.summarizer import build_summary_prompt
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(0.0, 5.0, "Let's discuss the budget.", speaker="Alice"),
        ]
        prompt = build_summary_prompt(segments, {"Alice": "Alice"}, notes="Ask about Q3 numbers")
        self.assertIn("Ask about Q3 numbers", prompt)
        self.assertIn("USER NOTES", prompt)

    def test_build_summary_prompt_without_notes(self):
        from app.ai.summarizer import build_summary_prompt
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(0.0, 5.0, "Hello.", speaker="Alice"),
        ]
        prompt = build_summary_prompt(segments, {"Alice": "Alice"}, notes="")
        self.assertNotIn("USER NOTES", prompt)

    def test_build_action_items_prompt(self):
        from app.ai.summarizer import build_action_items_prompt
        from app.transcription.transcriber import TranscriptSegment
        segments = [
            TranscriptSegment(0.0, 5.0, "Bob, can you send the report by Friday?", speaker="Alice"),
        ]
        prompt = build_action_items_prompt(segments, {"Alice": "Alice", "Bob": "Bob"})
        self.assertIn("action item", prompt.lower())
        self.assertIn("report", prompt)


class TestParseActionItems(unittest.TestCase):
    def test_parse_json_response(self):
        from app.ai.summarizer import parse_action_items
        response = json.dumps([
            {"task": "Send report", "assignee": "Bob", "deadline": "Friday"},
            {"task": "Review budget", "assignee": "Alice", "deadline": ""},
        ])
        items = parse_action_items(response)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["task"], "Send report")

    def test_parse_malformed_response(self):
        from app.ai.summarizer import parse_action_items
        items = parse_action_items("This is not JSON")
        self.assertEqual(items, [])


class TestSummaryLanguage(unittest.TestCase):

    def _seg(self):
        from app.transcription.transcriber import TranscriptSegment
        return [TranscriptSegment(0.0, 5.0, "Hello.", speaker="Alice")]

    def test_build_summary_prompt_with_language(self):
        from app.ai.summarizer import build_summary_prompt
        prompt = build_summary_prompt(self._seg(), {"Alice": "Alice"}, output_language="de")
        self.assertIn("de", prompt)
        self.assertIn("IMPORTANT", prompt)

    def test_build_summary_prompt_no_language_directive_when_empty(self):
        from app.ai.summarizer import build_summary_prompt
        prompt = build_summary_prompt(self._seg(), {"Alice": "Alice"}, output_language="")
        self.assertNotIn("IMPORTANT", prompt)

    def test_build_action_items_prompt_with_language(self):
        from app.ai.summarizer import build_action_items_prompt
        prompt = build_action_items_prompt(self._seg(), {"Alice": "Alice"}, output_language="fr")
        self.assertIn("fr", prompt)
        self.assertIn("IMPORTANT", prompt)

    def test_build_action_items_prompt_no_language_directive_when_empty(self):
        from app.ai.summarizer import build_action_items_prompt
        prompt = build_action_items_prompt(self._seg(), {"Alice": "Alice"}, output_language="")
        self.assertNotIn("IMPORTANT", prompt)

    def test_language_directive_comes_first(self):
        from app.ai.summarizer import build_summary_prompt
        prompt = build_summary_prompt(self._seg(), {"Alice": "Alice"}, output_language="ja")
        self.assertTrue(prompt.startswith("IMPORTANT"), "language directive must be first")


class TestSummaryPromptTemplate(unittest.TestCase):

    def _seg(self):
        from app.transcription.transcriber import TranscriptSegment
        return [TranscriptSegment(0.0, 5.0, "Let's ship v2.", speaker="Alice")]

    def test_custom_template_replaces_default(self):
        from app.ai.summarizer import build_summary_prompt
        prompt = build_summary_prompt(
            self._seg(), {"Alice": "Alice"},
            prompt_template="You are a legal analyst. Focus on risks.",
        )
        self.assertIn("legal analyst", prompt)
        self.assertNotIn("Key Topics", prompt)

    def test_empty_template_uses_default(self):
        from app.ai.summarizer import build_summary_prompt
        prompt = build_summary_prompt(self._seg(), {"Alice": "Alice"}, prompt_template="")
        self.assertIn("Overview", prompt)

    def test_whitespace_only_template_uses_default(self):
        from app.ai.summarizer import build_summary_prompt
        prompt = build_summary_prompt(self._seg(), {"Alice": "Alice"}, prompt_template="   ")
        self.assertIn("Overview", prompt)

    def test_transcript_always_appended(self):
        from app.ai.summarizer import build_summary_prompt
        prompt = build_summary_prompt(
            self._seg(), {"Alice": "Alice"},
            prompt_template="Custom instructions.",
        )
        self.assertIn("TRANSCRIPT:", prompt)
        self.assertIn("ship v2", prompt)

    def test_default_summary_prompt_exported(self):
        from app.ai.summarizer import DEFAULT_SUMMARY_PROMPT
        self.assertIn("Overview", DEFAULT_SUMMARY_PROMPT)
        self.assertIn("Decisions", DEFAULT_SUMMARY_PROMPT)


if __name__ == "__main__":
    unittest.main()
