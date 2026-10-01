#!/usr/bin/env python3
"""Canonical llm_flags separator and helpers (finding M6).

Single source of truth for how llm_flags strings are joined and split.

The bug this fixes: web_prospecting joined flags with ',' (and its
results schema told agents "Comma-separated"), while the monitor
lifecycle logic parsed flags with split('|'). A comma-separated
"comp_unknown,fetch_empty" therefore never matched 'fetch_empty', the
unreachable-page safety valve was neutralized, and a dead company was
counted as freshly verified.

Rules:
- Writers join flags with FLAG_SEPARATOR (',').
- Readers split tolerantly on both ',' and '|' (legacy rows and agent
  output in either style keep working) and strip whitespace.
- Membership checks always go through has_flag(); never use
  `'x' in flags_string` (substring matching) or a hand-rolled split.
"""

from __future__ import annotations

import re
from typing import Iterable, List

# Canonical separator used when WRITING llm_flags.
FLAG_SEPARATOR = ','

# Tolerant pattern used when READING llm_flags: accepts the canonical
# comma plus the legacy pipe (older rows and ' | '-joined red flags).
_SPLIT_RE = re.compile(r'[|,]')


def split_flags(value: object) -> List[str]:
    """Split a flags string into a clean list of flag tokens.

    Accepts both ',' and '|' separators, strips whitespace, and drops
    empty tokens. None and '' return [].
    """
    if not value:
        return []
    return [tok.strip() for tok in _SPLIT_RE.split(str(value)) if tok.strip()]


def join_flags(flags: Iterable[str]) -> str:
    """Join flag tokens with the canonical separator, dropping empties."""
    return FLAG_SEPARATOR.join(
        tok.strip() for tok in flags if tok and tok.strip()
    )


def normalize_flags(value: object) -> str:
    """Re-serialize any flags string in canonical form (',' separated)."""
    return join_flags(split_flags(value))


def has_flag(value: object, flag: str) -> bool:
    """True when `flag` is present as a whole token in the flags string."""
    return flag in split_flags(value)


def add_flag(value: object, flag: str) -> str:
    """Return the flags string with `flag` appended once, canonical form."""
    flags = split_flags(value)
    if flag not in flags:
        flags.append(flag)
    return join_flags(flags)


def remove_flag(value: object, flag: str) -> str:
    """Return the flags string with every occurrence of `flag` removed."""
    return join_flags(tok for tok in split_flags(value) if tok != flag)
