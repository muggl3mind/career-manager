#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / 'data'
REG_PATH = DATA_DIR / 'cv-registry.json'
FAM_PATH = DATA_DIR / 'cv-role-families.json'


def _resolve_cv_base() -> Path:
    """Resolve CV base path: env var → .claude/config.json → legacy default."""
    import os
    env = os.getenv('CV_BASE_PATH', '').strip()
    if env:
        return Path(env)
    config = SCRIPT_DIR.parents[4] / '.claude' / 'config.json'
    if config.exists():
        try:
            cfg = json.loads(config.read_text(encoding='utf-8'))
            p = (cfg.get('cv_base_path') or '').strip()
            if p:
                return Path(p)
        except Exception:
            pass
    return SCRIPT_DIR.parents[0] / 'data' / 'CV'


CV_BASE = _resolve_cv_base()


def ensure_defaults() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not FAM_PATH.exists():
        FAM_PATH.write_text(json.dumps({
            'roleFamilies': {
                # Populated by onboarding — maps your career paths to role keywords
            }, indent=2), encoding='utf-8')


def infer_kind(name: str) -> str:
    n = name.lower()
    if 'cover' in n:
        return 'cover_letter'
    if 'redline' in n:
        return 'redline'
    if 'resume' in n or 'cv' in n:
        return 'resume'
    if 'email' in n or 'dm' in n or 'linkedin' in n:
        return 'outreach_message'
    if 'analysis' in n:
        return 'analysis'
    if 'manifest' in n or n.startswith('qc_') or 'changes_applied' in n:
        return 'meta'
    return 'other'


def rebuild_registry(cv_root: Path = CV_BASE) -> Dict[str, Any]:
    ensure_defaults()
    entries: List[Dict[str, Any]] = []
    for p in cv_root.rglob('*'):
        if not p.is_file():
            continue
        if p.name.startswith('~$'):
            continue
        if p.suffix.lower() not in {'.docx', '.pdf', '.txt', '.json'}:
            continue
        rel = str(p.relative_to(cv_root))
        company = rel.split('/')[0] if '/' in rel else cv_root.name
        entries.append({
            'path': str(p),
            'relative_path': rel,
            'company': company,
            'kind': infer_kind(p.name),
            'ext': p.suffix.lower(),
            'updated_at': datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
        })

    masters = [e['path'] for e in entries if e['kind'] == 'resume' and 'master cv' in e['relative_path'].lower() and e['ext'] == '.docx']
    reg = {
        'root': str(cv_root),
        'updated_at': datetime.now().isoformat(),
        'master_cv_candidates': sorted(masters),
        'counts': {
            'total': len(entries),
            'resumes': sum(1 for e in entries if e['kind'] == 'resume'),
            'cover_letters': sum(1 for e in entries if e['kind'] == 'cover_letter'),
            'redlines': sum(1 for e in entries if e['kind'] == 'redline'),
        },
        'entries': sorted(entries, key=lambda e: (e['company'].lower(), e['relative_path'].lower())),
    }
    REG_PATH.write_text(json.dumps(reg, indent=2), encoding='utf-8')
    return reg


def load_registry() -> Dict[str, Any]:
    ensure_defaults()
    if not REG_PATH.exists():
        return rebuild_registry()
    return json.loads(REG_PATH.read_text(encoding='utf-8'))


if __name__ == '__main__':
    reg = rebuild_registry()
    print(json.dumps({'registry': str(REG_PATH), 'counts': reg.get('counts', {})}, indent=2))
