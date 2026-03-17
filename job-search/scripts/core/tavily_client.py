#!/usr/bin/env python3
"""
Tavily API client for discovering job listing URLs on careers pages.

Uses Tavily Extract API to fetch careers page content and parse out job posting
URLs. Graceful degradation: returns empty dict if Tavily is not configured.

Usage:
    from tavily_client import extract_careers_page, is_available

    if is_available():
        result = extract_careers_page('https://jobs.ashbyhq.com/company')
        # result = {'raw_content': '...markdown with role links...', 'url': '...'}
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List
from urllib.parse import urljoin

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts"))
from config_loader import get as config_get

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

try:
    from tavily import TavilyClient
    TAVILY_SDK_AVAILABLE = True
except ImportError:
    TAVILY_SDK_AVAILABLE = False


def _load_api_key() -> str | None:
    """Load Tavily API key from credentials file."""
    creds_path = config_get("credentials.tavily_token", "")
    if not creds_path:
        return None
    path = Path(creds_path) if Path(creds_path).is_absolute() else PROJECT_ROOT / creds_path
    if not path.exists():
        return None
    try:
        with path.open() as f:
            data = json.load(f)
            return data.get("api_key")
    except (json.JSONDecodeError, KeyError):
        return None


def _get_client() -> "TavilyClient | None":
    """Get a configured Tavily client, or None if unavailable."""
    if not TAVILY_SDK_AVAILABLE:
        return None
    if not config_get("integrations.tavily_enabled", False):
        return None
    api_key = _load_api_key()
    if not api_key:
        return None
    return TavilyClient(api_key=api_key)


def is_available() -> bool:
    """Check if Tavily is configured and ready to use."""
    return _get_client() is not None


def extract_careers_page(url: str) -> Dict:
    """
    Extract content from a careers page using Tavily Extract API.

    Returns the raw markdown content which includes role titles and their
    relative URLs (e.g., [### Role Title](/company/uuid)).

    Args:
        url: The careers page URL to extract.

    Returns:
        Dict with 'raw_content' and 'url' keys. Empty dict if unavailable.
    """
    client = _get_client()
    if client is None:
        return {}
    try:
        response = client.extract(urls=[url])
        results = response.get('results', [])
        if results:
            return results[0]
        return {}
    except Exception as e:
        print(f"  [tavily] WARN: extract failed for {url}: {e}")
        return {}


def find_role_urls(careers_url: str, role_titles: List[str]) -> Dict[str, str]:
    """
    Extract a careers page and match role titles to their posting URLs.

    Args:
        careers_url: The careers page URL.
        role_titles: List of role titles to find URLs for.

    Returns:
        Dict mapping role title -> full URL. Only includes matched roles.
    """
    result = extract_careers_page(careers_url)
    if not result:
        return {}

    content = result.get('raw_content', '')
    if not content:
        return {}

    # Parse markdown links: [### Role Title](relative_url) or [Role Title](url)
    # Tavily returns content like: [### ML/AI Engineer\n\nEngineering...](/company/uuid)
    link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    links = link_pattern.findall(content)

    # Build base URL for resolving relative paths
    matches = {}
    for role_title in role_titles:
        role_lower = role_title.strip().lower()
        for link_text, link_url in links:
            # Clean markdown headers from link text
            clean_text = re.sub(r'#+\s*', '', link_text).strip().lower()
            # Split on newlines — role title is usually the first line
            first_line = clean_text.split('\n')[0].strip()

            if role_lower in first_line or first_line in role_lower:
                # Resolve relative URL
                if link_url.startswith('/'):
                    full_url = urljoin(careers_url, link_url)
                elif link_url.startswith('http'):
                    full_url = link_url
                else:
                    full_url = urljoin(careers_url, link_url)
                matches[role_title] = full_url
                break

    return matches
