"""Rule-based enrichment pipeline for extracting memory segments.

Extracts five memory types from session notes using regex/heuristics:
- decision: choices made, approaches selected
- event: deployments, merges, releases, errors
- discovery: things learned, realized, found
- preference: guidelines, rules, always/never statements
- artifact: files created, PRs, commits, URLs
"""

from __future__ import annotations

import re

from rawgentic_memory.models import EnrichedSegment

# --- Compiled regex patterns per memory type ---
# Each pattern matches a full sentence or line containing the trigger.

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

_DECISION_PATTERNS = [
    re.compile(r".*\b(?:decided|decide)\b\s+to\b.*", re.IGNORECASE),
    re.compile(r".*\bchose\b\s+\w+.*", re.IGNORECASE),
    re.compile(r".*\bwent\s+with\b.*", re.IGNORECASE),
    re.compile(r".*\bgoing\s+with\b.*", re.IGNORECASE),
    re.compile(r".*\bdecision\s*:\s*.*", re.IGNORECASE),
    re.compile(r"^#{1,4}\s+decision\b.*", re.IGNORECASE | re.MULTILINE),
]

_EVENT_PATTERNS = [
    re.compile(r".*\bdeployed\b.*", re.IGNORECASE),
    re.compile(r".*\bmerged\b\s+(?:PR|pull\s+request|branch)\b.*", re.IGNORECASE),
    re.compile(r".*\breleased\b\s+(?:version|v\d).*", re.IGNORECASE),
    re.compile(r".*\bERROR\b\s*:.*"),  # case-sensitive: ERROR:
    re.compile(r".*\bfixed\b\s+(?:in|the|a|bug)\b.*", re.IGNORECASE),
    re.compile(r".*\bmigrated\b.*", re.IGNORECASE),
]

_DISCOVERY_PATTERNS = [
    re.compile(r".*\bfound\s+that\b.*", re.IGNORECASE),
    re.compile(r".*\blearned\s+that\b.*", re.IGNORECASE),
    re.compile(r".*\brealized\s+that\b.*", re.IGNORECASE),
    re.compile(r".*\bdiscovered\s+that\b.*", re.IGNORECASE),
    re.compile(r".*\bturns?\s+out\b.*", re.IGNORECASE),
]

_PREFERENCE_PATTERNS = [
    re.compile(r".*\bprefer\b\s+(?:using|to\s+use)\b.*", re.IGNORECASE),
    re.compile(r"^\s*always\s+(?:use|run|check)\b.*", re.IGNORECASE),
    re.compile(r"^\s*never\s+(?:push|use|skip|commit)\b.*", re.IGNORECASE),
    re.compile(r".*\bshould\s+always\b.*", re.IGNORECASE),
    re.compile(r".*\bmust\s+(?:not|never|always)\b.*", re.IGNORECASE),
]

_ARTIFACT_PATTERNS = [
    re.compile(r".*\b(?:created|added)\b\s+\S+\.\w{1,5}\b.*", re.IGNORECASE),
    re.compile(r".*\bPR\s+#\d+\b.*"),
    re.compile(r".*\bcommit\s+[0-9a-f]{7,}\b.*", re.IGNORECASE),
    re.compile(r".*\b\w+/[\w.]+\.\w{1,5}\b.*"),  # file paths like rawgentic_memory/server.py
]

_EXTRACTORS: list[tuple[str, list[re.Pattern]]] = [
    ("decision", _DECISION_PATTERNS),
    ("event", _EVENT_PATTERNS),
    ("discovery", _DISCOVERY_PATTERNS),
    ("preference", _PREFERENCE_PATTERNS),
    ("artifact", _ARTIFACT_PATTERNS),
]

# --- Topic extraction ---
# Extracts a short topic phrase from the content.

_TOPIC_STOPWORDS = frozenset({
    "a", "an", "the", "to", "of", "in", "on", "at", "is", "was", "are",
    "were", "be", "been", "that", "this", "it", "we", "i", "they", "he",
    "she", "for", "with", "from", "by", "as", "or", "and", "but", "not",
    "so", "if", "do", "did", "has", "had", "have", "will", "would",
    "should", "could", "can", "may", "might", "shall", "let", "us",
    "out", "up", "use", "get", "got", "just", "also", "than", "then",
    "very", "too", "our", "its", "my", "about",
})

_WORD_RE = re.compile(r"[a-zA-Z][\w'-]*")


def extract_topic(text: str) -> str:
    """Extract a concise topic phrase from text content.

    Returns the first 3-5 meaningful words (non-stopwords) as a
    lowercase hyphenated slug, or empty string for empty input.
    """
    if not text or not text.strip():
        return ""

    words = _WORD_RE.findall(text)
    meaningful = [w.lower() for w in words if w.lower() not in _TOPIC_STOPWORDS]

    if not meaningful:
        return ""

    # Take up to 4 meaningful words for a concise topic
    topic_words = meaningful[:4]
    return "-".join(topic_words)


def _split_into_segments(text: str) -> list[str]:
    """Split text into sentence-like segments for individual extraction."""
    segments = _SENTENCE_SPLIT.split(text.strip())
    return [s.strip() for s in segments if s.strip()]


def _extract_type(
    segment: str, memory_type: str, patterns: list[re.Pattern]
) -> EnrichedSegment | None:
    """Check if a segment matches any pattern for a given memory type."""
    for pattern in patterns:
        if pattern.match(segment):
            return EnrichedSegment(
                content=segment,
                memory_type=memory_type,
                topic=extract_topic(segment),
            )
    return None


def enrich(text: str, source_file: str) -> list[EnrichedSegment]:
    """Extract enriched memory segments from text using regex heuristics.

    Args:
        text: Raw session notes or markdown content.
        source_file: Path to the source file (stored as metadata).

    Returns:
        List of EnrichedSegment with memory_type, topic, and content.
    """
    if not text or not text.strip():
        return []

    segments = _split_into_segments(text)
    results: list[EnrichedSegment] = []
    seen_contents: set[str] = set()

    for segment in segments:
        for memory_type, patterns in _EXTRACTORS:
            enriched = _extract_type(segment, memory_type, patterns)
            if enriched and enriched.content not in seen_contents:
                enriched.source_file = source_file
                seen_contents.add(enriched.content)
                results.append(enriched)
                break  # first matching type wins per segment

    return results
