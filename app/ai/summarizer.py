"""Meeting summary and action item extraction."""

import json
from app.transcription.transcriber import TranscriptSegment


def _format_transcript(segments, speaker_names):
    lines = []
    for seg in segments:
        name = speaker_names.get(seg.speaker, seg.speaker) if seg.speaker else "Unknown"
        timestamp = f"[{seg.start:.1f}s]"
        lines.append(f"{timestamp} {name}: {seg.text}")
    return "\n".join(lines)


def _format_notes(notes):
    if not notes or not notes.strip():
        return ""
    return f"\n\nUSER NOTES (taken during the meeting):\n{notes.strip()}"


def _format_instruction(instruction):
    if not instruction or not instruction.strip():
        return ""
    return f"\n\nADDITIONAL INSTRUCTIONS FROM USER:\n{instruction.strip()}"


def _format_language(language):
    if not language or not language.strip():
        return ""
    return (
        f"IMPORTANT: Write your response in the language with code "
        f'"{language.strip()}". Do not translate the transcript — only your '
        f"analysis should be in that language.\n\n"
    )


DEFAULT_SUMMARY_PROMPT = (
    "You are a professional meeting analyst. Based on the transcript below, "
    "provide a structured summary with the following sections:\n\n"
    "## Overview\n"
    "One or two sentences summarising the meeting's purpose and outcome.\n\n"
    "## Key Topics\n"
    "Bullet list of the main themes or agenda items discussed.\n\n"
    "## Summary\n"
    "For each key topic, a concise paragraph covering what was discussed, "
    "key points raised, and any relevant context.\n\n"
    "## Decisions\n"
    "Explicit decisions or agreements reached. "
    'If none, write "No explicit decisions recorded."\n\n'
    "## Open Items\n"
    "Open questions, unresolved issues, or items needing follow-up that are "
    "not concrete action items. If none, omit this section.\n\n"
    "Write in a professional, neutral tone. Use markdown formatting."
)


def build_summary_prompt(segments, speaker_names, notes="", instruction="",
                         output_language="", prompt_template=""):
    transcript_text = _format_transcript(segments, speaker_names)
    notes_text = _format_notes(notes)
    instruction_text = _format_instruction(instruction)
    language_text = _format_language(output_language)
    body = prompt_template.strip() if prompt_template and prompt_template.strip() \
        else DEFAULT_SUMMARY_PROMPT
    return (
        f"{language_text}"
        f"{body}\n\n"
        f"TRANSCRIPT:\n{transcript_text}{notes_text}{instruction_text}"
    )


def build_action_items_prompt(segments, speaker_names, notes="", instruction="", output_language=""):
    transcript_text = _format_transcript(segments, speaker_names)
    notes_text = _format_notes(notes)
    instruction_text = _format_instruction(instruction)
    language_text = _format_language(output_language)
    return (
        f"{language_text}"
        "Below is a transcript of a meeting. Extract all action items — tasks, "
        "follow-ups, or commitments made by participants.\n\n"
        "If user notes are included, also extract any action items from them.\n\n"
        "If additional instructions are provided, follow them when extracting "
        "action items.\n\n"
        "Return a JSON array where each item has:\n"
        '- "task": description of the action item\n'
        '- "assignee": who is responsible (speaker name)\n'
        '- "deadline": mentioned deadline or empty string\n\n'
        "Return ONLY the JSON array, no other text.\n\n"
        f"TRANSCRIPT:\n{transcript_text}{notes_text}{instruction_text}"
    )


def parse_action_items(response):
    text = response.strip()
    if "```" in text:
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            text = text[start:end]
    try:
        items = json.loads(text)
        if isinstance(items, list):
            return items
    except (json.JSONDecodeError, ValueError):
        pass
    return []
