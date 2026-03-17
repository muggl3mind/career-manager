#!/usr/bin/env python3
"""Resolve portable CV index paths using .claude/config.json or CV_BASE_PATH."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Any

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts"))
from config_loader import get as config_get

SCRIPT_DIR = Path(__file__).resolve().parent          # job-search/scripts/core/
JOB_SEARCH_DIR = SCRIPT_DIR.parent.parent             # job-search/
CV_INDEX_PATH = JOB_SEARCH_DIR / "data" / "cv-index.json"
WORKSPACE = Path.home() / ".openclaw" / "agents" / "[YOUR_WORKSPACE]" / "workspace"
CLAUDE_DIR = WORKSPACE / ".claude"
CONFIG_PATH = CLAUDE_DIR / "config.json"


def get_cv_base_path() -> Path:
    env = os.getenv("CV_BASE_PATH", "").strip()
    if env:
        return Path(env)
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            p = (cfg.get("cv_base_path") or "").strip()
            if p:
                return Path(p)
        except Exception:
            pass
    return Path(config_get("paths.cv_base", str(Path.home() / "Documents/CV")))


def load_cv_index() -> Dict[str, Any]:
    return json.loads(CV_INDEX_PATH.read_text(encoding="utf-8"))


def resolve_templates() -> Dict[str, str]:
    idx = load_cv_index()
    base = get_cv_base_path()
    out: Dict[str, str] = {}
    for name, meta in idx.get("cv_templates", {}).items():
        rel = meta.get("template_rel_path")
        if rel:
            out[name] = str((base / rel).resolve())
        elif meta.get("template_path"):
            out[name] = str(Path(meta["template_path"]).resolve())
    return out


if __name__ == "__main__":
    templates = resolve_templates()
    print(json.dumps({"cv_base_path": str(get_cv_base_path()), "templates": templates}, indent=2))
