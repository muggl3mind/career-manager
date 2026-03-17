#!/usr/bin/env python3
"""
Load and validate search-config.json for the discovery pipeline.

Provides a single function `load_search_config()` that returns a validated
config dict or None (with a printed message) if the file is missing or invalid.
"""

import json
import re
from pathlib import Path
from typing import Optional

REQUIRED_KEYS = [
    "query_packs",
    "role_include_patterns",
    "role_exclude_patterns",
    "employer_exclude_patterns",
    "location_exclude_patterns",
    "keywords",
    "gold_companies",
]


def load_search_config(config_path: Path) -> Optional[dict]:
    """
    Load and validate search-config.json.

    Returns the parsed config dict, or None if the file is missing,
    malformed, or missing required keys.
    """
    if not config_path.exists():
        print(f"[search] No search-config.json found at {config_path}")
        print("[search] Run the onboarding skill to generate your search configuration.")
        return None

    try:
        with open(config_path) as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[search] Error reading {config_path}: {e}")
        return None

    # Validate required keys
    missing = [k for k in REQUIRED_KEYS if k not in config]
    if missing:
        print(f"[search] search-config.json is missing required keys: {missing}")
        print("[search] Re-run the onboarding skill to regenerate.")
        return None

    # Validate regex patterns are compilable
    for key in ["role_include_patterns", "role_exclude_patterns",
                "employer_exclude_patterns", "location_exclude_patterns"]:
        patterns = config.get(key, [])
        for i, p in enumerate(patterns):
            try:
                re.compile(p)
            except re.error as e:
                print(f"[search] Invalid regex in {key}[{i}]: {p!r} — {e}")
                return None

    return config
