#!/usr/bin/env python3
"""
Post-setup smoke test — verifies everything loads before running the pipeline.

Usage:
    python3 scripts/smoke_test.py

Run this once after setup/onboarding to catch import errors, missing config,
or environment issues before they surface mid-pipeline.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OK = "\033[92m  PASS\033[0m"
FAIL = "\033[91m  FAIL\033[0m"
WARN = "\033[93m  WARN\033[0m"

failures = 0
warnings = 0


def check(label, fn):
    global failures, warnings
    try:
        result = fn()
        if result is True:
            print(f"{OK}  {label}")
        elif result == "warn":
            print(f"{WARN}  {label}")
            warnings += 1
        else:
            print(f"{FAIL}  {label}: {result}")
            failures += 1
    except Exception as e:
        print(f"{FAIL}  {label}: {e}")
        failures += 1


def main():
    print("\n" + "=" * 60)
    print("  SMOKE TEST — Post-Setup Verification")
    print("=" * 60 + "\n")

    # --- 1. Required directories ---
    print("[Directories]")
    for d in [
        "job-search/data",
        "job-tracker/data",
        "cv-tailor/data/CV/Master CV",
        "references",
        "scripts",
    ]:
        check(d, lambda d=d: True if (PROJECT_ROOT / d).exists() else f"Missing: {d}")

    # --- 2. Required config files ---
    print("\n[Config Files]")
    config_yaml = PROJECT_ROOT / "config.yaml"
    check("config.yaml", lambda: True if config_yaml.exists() else "Missing — run onboarding or copy config.yaml.example")

    search_config = PROJECT_ROOT / "job-search" / "data" / "search-config.json"
    check("search-config.json", lambda: True if search_config.exists() else "Missing — run onboarding to generate")

    # --- 3. Python dependencies ---
    print("\n[Python Dependencies]")
    for mod, optional in [
        ("yaml", False),
        ("requests", False),
        ("docx", False),
        ("openpyxl", False),
        ("jobspy", True),
        ("google.auth", True),
        ("googleapiclient", True),
    ]:
        def check_import(m=mod, opt=optional):
            try:
                __import__(m)
                return True
            except ImportError:
                if opt:
                    return "warn"
                return f"Not installed — run: pip install -r requirements.txt"
        label = f"{mod}" + (" (optional)" if optional else "")
        check(label, check_import)

    # --- 4. Config loader ---
    print("\n[Config Loader]")
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    check("config_loader imports", lambda: (__import__("config_loader"), True)[1])

    if config_yaml.exists():
        from config_loader import get
        check("config.yaml reads", lambda: True if get("integrations") is not None else "config.yaml exists but couldn't read integrations key")

    # --- 5. Search config loader + validation ---
    print("\n[Search Config]")
    sys.path.insert(0, str(PROJECT_ROOT / "job-search" / "scripts" / "core"))

    check("search_config_loader imports", lambda: (__import__("search_config_loader"), True)[1])

    if search_config.exists():
        from search_config_loader import load_search_config
        config = load_search_config(search_config)
        check("search-config.json validates", lambda: True if config else "Validation failed — re-run onboarding")
        if config:
            qp = config.get("query_packs", {})
            check("query_packs is a dict (not list)", lambda: True if isinstance(qp, dict) else "query_packs must be a dict keyed by name, not a list — re-run onboarding")
            check(f"query_packs: {len(qp)} packs", lambda: True if qp else "No query packs")
            pci = config.get("path_check_instructions", {})
            check("path_check_instructions is a dict", lambda: True if isinstance(pci, dict) else "path_check_instructions must be a dict keyed by path number, not a string — re-run onboarding")
            check(f"gold_companies: {len(config.get('gold_companies', []))} companies", lambda: True if config.get("gold_companies") else "No gold companies")
            pp = config.get("prospecting_paths", [])
            check(f"prospecting_paths: {len(pp)} paths", lambda: True if pp else "No prospecting paths — web prospecting won't work")
            scoring = config.get("scoring", {})
            check(f"scoring keywords: {len(scoring)} groups", lambda: True if scoring else "No scoring config — companies won't be scored")

    # --- 6. Pipeline module imports ---
    print("\n[Pipeline Modules]")
    sys.path.insert(0, str(PROJECT_ROOT / "job-search" / "scripts" / "ops"))

    for mod_name in [
        "web_prospecting",
        "monitor_watchlist",
        "run_pipeline",
    ]:
        def check_mod(m=mod_name):
            try:
                __import__(m)
                return True
            except SystemExit:
                return True  # Some modules exit(0) when config missing — that's OK
            except Exception as e:
                return f"{type(e).__name__}: {e}"
        check(mod_name, check_mod)

    # --- 7. Generated files (from onboarding) ---
    print("\n[Onboarding Output]")
    for f, label in [
        ("job-search/references/criteria.md", "criteria.md"),
        ("job-search/references/background-context.md", "background-context.md"),
    ]:
        path = PROJECT_ROOT / f
        def check_file(p=path):
            if not p.exists():
                return "Missing — run onboarding"
            content = p.read_text()
            if "Run the onboarding skill" in content:
                return "Template placeholder — run onboarding to personalize"
            return True
        check(label, check_file)

    # --- Summary ---
    print("\n" + "=" * 60)
    if failures == 0 and warnings == 0:
        print("  ALL CHECKS PASSED — pipeline is ready to run")
    elif failures == 0:
        print(f"  PASSED with {warnings} warning(s) — pipeline should work")
    else:
        print(f"  {failures} FAILURE(S), {warnings} warning(s) — fix issues above before running")
    print("=" * 60 + "\n")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
