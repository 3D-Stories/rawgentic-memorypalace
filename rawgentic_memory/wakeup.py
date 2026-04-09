"""Tiered wake-up context generation (L0 + L1).

L0: Static identity file read from disk (~50 tokens).
L1: Critical facts generated on-the-fly from ChromaDB data, ranked by
    recency + frequency (~120 tokens).

The combined context is returned by the /wakeup endpoint and injected
into sessions by the SessionStart hook.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from rawgentic_memory.backend import MemoryBackend
from rawgentic_memory.models import WakeupContext

logger = logging.getLogger(__name__)

_L1_TOP_K = 10
_L1_FACT_TYPES = frozenset({"decision", "discovery", "preference"})


def _estimate_tokens(text: str) -> int:
    """Rough token estimate based on word count."""
    return len(text.split()) if text else 0


def _parse_timestamp(ts: str) -> datetime:
    """Parse ISO 8601 timestamp. Returns epoch-ish date if unparseable."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return datetime(2000, 1, 1, tzinfo=timezone.utc)


def load_l0(l0_path: Path | str | None = None) -> str:
    """Load L0 identity text from a static file.

    Returns empty string if the file does not exist or is unreadable.
    """
    if l0_path is None:
        return ""

    path = Path(l0_path).expanduser().resolve()
    if not path.is_file():
        return ""

    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        logger.warning("Failed to read L0 identity file: %s", path)
        return ""


def generate_l1(
    documents: list[dict],
    max_tokens: int = 120,
    now: datetime | None = None,
) -> str:
    """Generate L1 critical facts from a list of backend documents.

    Groups documents by topic, scores each topic by
    ``frequency * 1/(1 + days_old/30)``, and returns the top 10
    as a bullet list capped at ``max_tokens`` approximate words.

    Args:
        documents: List of ``{"content": str, "metadata": dict}`` dicts
            as returned by ``MemoryBackend.get_project_documents()``.
        max_tokens: Approximate word budget for the output.
        now: Reference timestamp for recency scoring (default: current UTC).
    """
    if not documents:
        return ""

    if now is None:
        now = datetime.now(timezone.utc)

    # Filter to fact types (decisions, discoveries, preferences)
    facts = [d for d in documents
             if d.get("metadata", {}).get("memory_type") in _L1_FACT_TYPES]
    if not facts:
        # Fallback to all types if no fact types found
        facts = documents

    # Group by topic
    topic_groups: dict[str, list[dict]] = defaultdict(list)
    for doc in facts:
        topic = doc.get("metadata", {}).get("topic", "unknown")
        topic_groups[topic].append(doc)

    # Score each topic: frequency * recency_weight
    scored: list[dict] = []
    for topic, group in topic_groups.items():
        frequency = len(group)
        timestamps = [_parse_timestamp(d.get("metadata", {}).get("timestamp", ""))
                      for d in group]
        most_recent = max(timestamps)
        days_old = max(0, (now - most_recent).days)
        recency_weight = 1.0 / (1.0 + days_old / 30.0)
        score = frequency * recency_weight

        # Pick the most recent document as representative (use parsed datetimes,
        # not lexicographic string comparison, to handle mixed TZ formats).
        best_idx = timestamps.index(most_recent)
        best_doc = group[best_idx]
        scored.append({
            "topic": topic,
            "content": best_doc["content"],
            "score": score,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    top_facts = scored[:_L1_TOP_K]

    # Format as bullet list, respecting token budget
    lines: list[str] = []
    token_count = 0
    for fact in top_facts:
        line = f"- {fact['content']}"
        line_tokens = _estimate_tokens(line)
        if token_count + line_tokens > max_tokens and lines:
            break
        lines.append(line)
        token_count += line_tokens

    return "\n".join(lines)


def generate_wakeup(
    backend: MemoryBackend | None,
    project: str | None,
    l0_path: Path | str | None = None,
) -> WakeupContext:
    """Generate combined L0 + L1 wake-up context.

    Gracefully degrades at every level:
    - No backend + no L0 file -> empty context
    - No backend, L0 file exists -> L0 only
    - Backend + data, no L0 file -> L1 only
    - Backend + data + L0 file -> L0 + L1

    Args:
        backend: A MemoryBackend instance (or None for degraded mode).
        project: Project name for scoping L1 facts.
        l0_path: Path to the L0 identity file (or None to skip L0).
    """
    layers: list[str] = []
    parts: list[str] = []

    # L0: static identity
    l0_text = load_l0(l0_path)
    if l0_text:
        parts.append(l0_text)
        layers.append("L0")

    # L1: critical facts from backend (requires a project name)
    l1_text = ""
    if backend is not None and project:
        try:
            docs = backend.get_project_documents(project)
            l1_text = generate_l1(docs)
        except Exception:
            logger.warning("Failed to generate L1 for project %s", project,
                           exc_info=True)

    if l1_text:
        parts.append(l1_text)
        layers.append("L1")

    text = "\n\n".join(parts)
    tokens = _estimate_tokens(text)

    return WakeupContext(
        text=text,
        tokens=tokens,
        layers=layers,
        backend="native",
    )
