"""Normalize free-text LLM path names to canonical career path labels."""
from __future__ import annotations

from difflib import SequenceMatcher

THRESHOLD = 0.6


def normalize_path(raw_name: str, canonical_paths: list[str]) -> str:
    """Match raw LLM path name to closest canonical path.

    Uses difflib.SequenceMatcher (case-insensitive).
    Returns best match if similarity >= THRESHOLD, otherwise returns raw_name unchanged.
    """
    if not raw_name or not canonical_paths:
        return raw_name

    raw_lower = raw_name.lower()
    best_score = 0.0
    best_match = raw_name

    for canon in canonical_paths:
        score = SequenceMatcher(None, raw_lower, canon.lower()).ratio()
        if score > best_score:
            best_score = score
            best_match = canon

    if best_score >= THRESHOLD:
        return best_match
    return raw_name
