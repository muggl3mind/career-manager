"""Shared configuration loader for career-manager pipeline."""

import os
from pathlib import Path

import yaml

_config = None

def _find_config_path() -> Path:
    """Walk up from this file to find config.yaml at project root."""
    current = Path(__file__).resolve().parent
    for _ in range(5):
        candidate = current / "config.yaml"
        if candidate.exists():
            return candidate
        current = current.parent
    return Path(__file__).resolve().parent.parent / "config.yaml"

def load_config() -> dict:
    global _config
    if _config is not None:
        return _config

    config_path = _find_config_path()
    if not config_path.exists():
        print(f"[config] No config.yaml found at {config_path}, using defaults")
        _config = {}
        return _config

    with open(config_path) as f:
        _config = yaml.safe_load(f) or {}
    return _config

def get(key: str, default=None):
    """Get a config value by dot-notation key. Example: get('paths.cv_base')"""
    config = load_config()
    keys = key.split(".")
    val = config
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return default
    return val if val is not None else default
