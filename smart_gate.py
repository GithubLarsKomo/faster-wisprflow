"""Heuristic correction gate for Fast / Smart / Polish modes.

Stage 1 deliberately uses only deterministic local signals. It never attempts
semantic classification; uncertain cases stay on the existing LLM-correction
path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_VALID_MODES = {"fast", "smart", "polish"}
_WORD_RE = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)
_TERMINAL_RE = re.compile(r'[.!?…][\")\]\}»”’]*$')
_SELF_CORRECTION_RE = re.compile(
    r"\b(?:ähm?|ich\s+meine|also\s+nein|äh\s+nein|nein\s+doch)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CorrectionDecision:
    use_llm: bool
    reason: str
    word_count: int


def normalize_correction_mode(value: str | None) -> str:
    mode = (value or "smart").strip().lower()
    return mode if mode in _VALID_MODES else "smart"


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _has_adjacent_repetition(words: list[str]) -> bool:
    folded = [word.casefold() for word in words]
    return any(a == b for a, b in zip(folded, folded[1:]))


def _has_unbalanced_delimiters(text: str) -> bool:
    pairs = (("(", ")"), ("[", "]"), ("{", "}"))
    return any(text.count(left) != text.count(right) for left, right in pairs)


def _first_alpha_is_lower(text: str) -> bool:
    for char in text:
        if char.isalpha():
            return char.islower()
    return False


def correction_decision(
    text: str,
    *,
    correction_enabled: bool,
    mode: str | None,
) -> CorrectionDecision:
    """Return whether the existing generative corrector should run.

    Fast always bypasses the LLM, Polish preserves the historical
    always-correct behavior, and Smart uses a conservative local gate.

    The Smart gate only bypasses correction for short, structurally clean
    transcripts. Any explicit uncertainty signal routes to the LLM.
    """

    words = _words(text)
    word_count = len(words)
    normalized_mode = normalize_correction_mode(mode)

    if not correction_enabled:
        return CorrectionDecision(False, "correction_disabled", word_count)
    if normalized_mode == "fast":
        return CorrectionDecision(False, "fast_mode", word_count)
    if normalized_mode == "polish":
        return CorrectionDecision(bool(text.strip()), "polish_mode", word_count)

    stripped = text.strip()
    if not stripped:
        return CorrectionDecision(False, "empty", word_count)

    if _SELF_CORRECTION_RE.search(stripped):
        return CorrectionDecision(True, "self_correction_signal", word_count)
    if _has_adjacent_repetition(words):
        return CorrectionDecision(True, "adjacent_repetition", word_count)
    if _has_unbalanced_delimiters(stripped):
        return CorrectionDecision(True, "unbalanced_delimiters", word_count)

    if word_count <= 4:
        return CorrectionDecision(False, "short_clean_fragment", word_count)

    if word_count > 12:
        return CorrectionDecision(True, "long_utterance", word_count)

    if not _TERMINAL_RE.search(stripped):
        return CorrectionDecision(True, "missing_terminal_punctuation", word_count)

    if _first_alpha_is_lower(stripped):
        return CorrectionDecision(True, "lowercase_sentence_start", word_count)

    return CorrectionDecision(False, "short_structurally_clean", word_count)
