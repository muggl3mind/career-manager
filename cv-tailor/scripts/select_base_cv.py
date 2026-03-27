#!/usr/bin/env python3
from __future__ import annotations
import json, re
from pathlib import Path
from index_store import load_registry, FAM_PATH

FAM=FAM_PATH


def norm(s:str)->str:
    return re.sub(r'\s+',' ',(s or '').lower()).strip()


def family_for_role(role:str, families:dict)->str:
    r=norm(role)
    for fam, kws in families.items():
        if any(k in r for k in kws):
            return fam
    return 'general'


def score_entry(e:dict, role:str, company:str, family:str)->int:
    s=0
    rp=norm(e.get('relative_path',''))
    if e.get('kind')!='resume' or e.get('ext')!='.docx':
        return -999
    if company and norm(company) in rp:
        s += 60
    if role and any(tok in rp for tok in norm(role).split() if len(tok)>3):
        s += 20
    # family hinting from filename — aligned with job-search 8 paths
    fam_hints={}  # Populated by onboarding — maps career paths to role keywords
    for h in fam_hints.get(family,[]):
        if h in rp:
            s += 8
    # prefer non-archive by default
    if '/archive/' not in rp:
        s += 6
    return s


def select(role:str, company:str):
    reg=load_registry()
    fams=json.loads(FAM.read_text(encoding='utf-8'))['roleFamilies']
    family=family_for_role(role,fams)
    entries=reg['entries']
    ranked=sorted(entries,key=lambda e:score_entry(e,role,company,family), reverse=True)
    top=ranked[0] if ranked else None
    top_score=score_entry(top,role,company,family) if top else -999

    masters=reg.get('master_cv_candidates',[])
    master_docx=next((m for m in masters if m.lower().endswith('.docx')), None)

    # confidence rule: if no strong match, use master docx as default canonical base
    # strong match threshold: >= 30 (company hit and/or meaningful role hint)
    use_master = (top is None) or (top_score < 30)

    selected = master_docx if (use_master and master_docx) else (top['path'] if top else master_docx)
    selected_source = 'master_default' if (use_master and master_docx) else 'closest_prior'

    return {
      'role': role,
      'company': company,
      'role_family': family,
      'selected_base_cv': selected,
      'selected_source': selected_source,
      'selected_score': top_score if top else None,
      'master_cv_candidate': master_docx or (masters[0] if masters else None),
      'top_5': [{
        'path': e['path'],
        'score': score_entry(e,role,company,family)
      } for e in ranked[:5]]
    }

if __name__=='__main__':
    import sys
    role=sys.argv[1] if len(sys.argv)>1 else ''
    company=sys.argv[2] if len(sys.argv)>2 else ''
    print(json.dumps(select(role,company),indent=2))
