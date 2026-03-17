#!/usr/bin/env python3
"""
Todoist Sync Utility
Syncs completed work to Todoist by fuzzy-matching existing tasks or creating new ones.
Importable by Claude Code skills for automatic task tracking.

Usage:
    python3 todoist_sync.py "Updated job tracker for OpenAI FDE"
    python3 todoist_sync.py --dry-run "Applied to Acme Corp Product Manager"
"""

import json
import re
import sys
import requests
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
from config_loader import get as config_get
from typing import Dict, List, Optional

# --- Auth / Config -----------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CREDS_FILE = PROJECT_ROOT / config_get("credentials.todoist_token", ".credentials/todoist-token.json")
BASE_URL = "https://api.todoist.com/api/v1"

# Words too common to be useful for matching
STOP_WORDS = {
    "the", "a", "an", "to", "for", "of", "in", "on", "at", "and", "or",
    "is", "it", "with", "that", "this", "from", "by", "as", "be", "was",
    "job", "task", "work", "done", "did", "just", "new", "all",
}

# Action verbs that carry strong signal when matching tasks
ACTION_VERBS = {
    "apply", "applied", "application",
    "update", "updated",
    "tailor", "tailored",
    "follow", "follow-up", "followup",
    "research", "researched",
    "submit", "submitted",
    "prepare", "prepared",
    "review", "reviewed",
    "draft", "drafted",
    "send", "sent",
    "track", "tracked",
    "schedule", "scheduled",
}


def _load_token() -> str:
    """Load Todoist API token from credentials file."""
    with open(CREDS_FILE, "r") as f:
        data = json.load(f)
        return data.get("todoist_api_token") or data["api_token"]


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


# --- API helpers (minimal, mirrors TodoistClient pattern) --------------------

def _get_projects(token: str) -> List[Dict]:
    resp = requests.get(f"{BASE_URL}/projects", headers=_headers(token))
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("results", [])


def _get_tasks(token: str, project_id: Optional[str] = None) -> List[Dict]:
    params = {}
    if project_id:
        params["project_id"] = project_id
    resp = requests.get(f"{BASE_URL}/tasks", headers=_headers(token), params=params)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("results", [])


def _add_task(token: str, content: str, project_id: Optional[str] = None) -> Dict:
    payload = {"content": content, "priority": 1}
    if project_id:
        payload["project_id"] = project_id
    resp = requests.post(f"{BASE_URL}/tasks", headers=_headers(token), json=payload)
    resp.raise_for_status()
    return resp.json()


def _complete_task(token: str, task_id: str) -> bool:
    resp = requests.post(f"{BASE_URL}/tasks/{task_id}/close", headers=_headers(token))
    resp.raise_for_status()
    return True


# --- Fuzzy matching ----------------------------------------------------------

def _tokenize(text: str) -> set:
    """Extract meaningful lowercase tokens from text."""
    # Split on whitespace and punctuation, keep hyphenated words too
    raw = re.findall(r"[a-zA-Z0-9][\w'-]*", text.lower())
    return {w for w in raw if w not in STOP_WORDS and len(w) > 1}


def _score_match(description_tokens: set, task_content: str) -> float:
    """
    Score how well a task matches the description.
    Returns 0.0-1.0 based on keyword overlap, with action verb bonus.
    """
    task_tokens = _tokenize(task_content)
    if not description_tokens or not task_tokens:
        return 0.0

    overlap = description_tokens & task_tokens
    if not overlap:
        return 0.0

    # Base score: fraction of description keywords found in task
    base = len(overlap) / len(description_tokens)

    # Bonus for matching action verbs (strong signal)
    action_overlap = overlap & ACTION_VERBS
    verb_bonus = 0.1 * len(action_overlap)

    # Bonus for matching longer tokens (likely company names / role titles)
    long_overlap = {w for w in overlap if len(w) >= 5}
    long_bonus = 0.05 * len(long_overlap)

    return min(1.0, base + verb_bonus + long_bonus)


def _find_best_match(description: str, tasks: List[Dict], threshold: float) -> Optional[Dict]:
    """Find the best matching task above threshold. Returns (task, score) or None."""
    desc_tokens = _tokenize(description)
    best_task = None
    best_score = 0.0

    for task in tasks:
        content = task.get("content", "")
        score = _score_match(desc_tokens, content)
        if score > best_score:
            best_score = score
            best_task = task

    if best_task and best_score >= threshold:
        return best_task
    return None


# --- Main sync function ------------------------------------------------------

def sync_completed_work(
    description: str,
    project_name: str = "Job Search",
    match_threshold: float = 0.4,
) -> dict:
    """
    Sync a completed work description to Todoist.

    1. Finds the target project by name.
    2. Fetches open tasks and fuzzy-matches against the description.
    3. If match found: completes the existing task.
    4. If no match: creates a new task and immediately completes it.

    Args:
        description: What was done, e.g. "Updated job tracker for OpenAI FDE Financial Services"
        project_name: Todoist project to search/create in (default "Job Search")
        match_threshold: Minimum keyword-overlap score to accept a match (0.0-1.0)

    Returns:
        dict with keys: action, task_content, task_id
    """
    if not config_get("integrations.todoist_enabled", False):
        print("[todoist] Sync skipped — todoist_enabled is false in config.yaml")
        return {"action": "skipped", "task_content": description, "task_id": None}

    token = _load_token()

    # Resolve project
    project_id = None
    projects = _get_projects(token)
    for proj in projects:
        if proj.get("name", "").lower() == project_name.lower():
            project_id = proj.get("id")
            break

    # Fetch open tasks (scoped to project if found)
    tasks = _get_tasks(token, project_id=project_id)

    # Try to match
    match = _find_best_match(description, tasks, match_threshold)

    if match:
        task_id = match["id"]
        _complete_task(token, task_id)
        return {
            "action": "completed_existing",
            "task_content": match.get("content", ""),
            "task_id": str(task_id),
        }
    else:
        new_task = _add_task(token, description, project_id=project_id)
        task_id = new_task["id"]
        _complete_task(token, task_id)
        return {
            "action": "created_and_completed",
            "task_content": description,
            "task_id": str(task_id),
        }


def sync_completed_work_dry_run(
    description: str,
    project_name: str = "Job Search",
    match_threshold: float = 0.4,
) -> dict:
    """
    Dry-run version: shows what would happen without making changes.
    """
    if not config_get("integrations.todoist_enabled", False):
        print("[todoist] Sync skipped — todoist_enabled is false in config.yaml")
        return {"action": "skipped", "task_content": description, "task_id": None}

    token = _load_token()

    project_id = None
    projects = _get_projects(token)
    for proj in projects:
        if proj.get("name", "").lower() == project_name.lower():
            project_id = proj.get("id")
            break

    tasks = _get_tasks(token, project_id=project_id)
    match = _find_best_match(description, tasks, match_threshold)

    if match:
        return {
            "action": "would_complete_existing",
            "task_content": match.get("content", ""),
            "task_id": str(match["id"]),
            "dry_run": True,
        }
    else:
        return {
            "action": "would_create_and_complete",
            "task_content": description,
            "task_id": None,
            "dry_run": True,
        }


# --- CLI ---------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Sync completed work to Todoist")
    parser.add_argument("description", help="Description of work done")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")
    parser.add_argument("--project", default="Job Search", help="Todoist project name (default: Job Search)")
    parser.add_argument("--threshold", type=float, default=0.4, help="Match threshold 0.0-1.0 (default: 0.4)")

    args = parser.parse_args()

    if args.dry_run:
        result = sync_completed_work_dry_run(args.description, args.project, args.threshold)
    else:
        result = sync_completed_work(args.description, args.project, args.threshold)

    # Pretty output
    action = result["action"]
    content = result["task_content"]
    task_id = result.get("task_id", "n/a")

    print(f"Action:  {action}")
    print(f"Task:    {content}")
    print(f"Task ID: {task_id}")

    if result.get("dry_run"):
        print("(dry run - no changes made)")


if __name__ == "__main__":
    main()
