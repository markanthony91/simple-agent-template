"""Local prototype for splitting one assistant turn into delivery messages.

No channel sends from here. The Runtime keeps one logical assistant response;
channel adapters can deliver the returned segments as separate messages.
"""

from __future__ import annotations

import re


_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ])")
_ABBREVIATIONS = {"dr.", "dra.", "sr.", "sra.", "prof.", "profa.", "res.", "art."}


def split_reply_for_delivery(text: str, max_chars: int = 240) -> list[str]:
    """Respect deliberate paragraphs; group unmarked sentences conservatively.

    ``max_chars`` is a soft target, never permission to cut a sentence or fact.
    """
    if max_chars < 1:
        raise ValueError("max_chars_must_be_positive")
    cleaned = text.strip().replace("\r\n", "\n")
    if not cleaned:
        return []
    if re.search(r"(?m)^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|```)", cleaned):
        return [cleaned]

    paragraphs = [
        part.strip() for part in _PARAGRAPH_BREAK.split(cleaned) if part.strip()
    ]
    if len(paragraphs) > 1:
        return paragraphs if len(paragraphs) <= 12 else [cleaned]

    sentences: list[str] = []
    for phrase in _SENTENCE_BREAK.split(cleaned):
        if sentences and sentences[-1].split()[-1].lower() in _ABBREVIATIONS:
            sentences[-1] += " " + phrase
        else:
            sentences.append(phrase)
    if len(sentences) < 3:
        return [cleaned]

    segments: list[str] = []
    # shortcut: a short opening is treated as an acknowledgement only when
    # followed by enough text; explicit paragraph breaks remain authoritative.
    if len(sentences) >= 4 and len(sentences[0]) <= 70:
        segments.append(sentences.pop(0))

    current = ""
    for sentence in sentences:
        if current and len(current) + 1 + len(sentence) > max_chars:
            segments.append(current)
            current = ""
        current = f"{current} {sentence}" if current else sentence
    if current:
        segments.append(current)
    return segments if len(segments) <= 12 else [cleaned]
