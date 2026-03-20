"""Normalize free-text LLM path names to canonical career path labels.

Uses a deterministic alias map instead of fuzzy matching. Every known
variant maps to exactly one canonical label. Unknown values are returned
unchanged so they surface visibly in dashboards.
"""
from __future__ import annotations

# Canonical labels (must match search-config.json query_pack labels)
CANONICAL = [
    "AI Accounting Startup",
    "domain operations & PE Tech",
    "PE Firm with Portfolio Ops Team",
    "Internal Finance Ops Transformation",
    "Accounting Professional Services",
    "Enterprise Finance Software",
    "domain operations Software",
    "Tier 1 AI Companies",
]

# Alias map: lowercase variant -> canonical label
_ALIAS_MAP: dict[str, str] = {}


def _add(canonical: str, *aliases: str) -> None:
    _ALIAS_MAP[canonical.lower()] = canonical
    for alias in aliases:
        _ALIAS_MAP[alias.lower()] = canonical


_add("AI Accounting Startup",
     "ai accounting", "ai accounting startup", "ai accounting/finance startup",
     "ai domain operations startup", "ai fintech startup", "ai finance startup",
     "ai industry startup")

_add("domain operations & PE Tech",
     "domain operations & pe tech", "domain operations pe tech", "pe domain operations software",
     "pe/domain operations software", "domain operations software & pe tech")

_add("PE Firm with Portfolio Ops Team",
     "pe firm with portfolio ops team", "pe firm with portfolio ops",
     "pe firms", "pe firm", "pe portfolio ops", "pe operating partner")

_add("Internal Finance Ops Transformation",
     "internal finance ops transformation", "finance ops transformation",
     "internal ops transformation", "finance transformation",
     "internal transformation")

_add("Accounting Professional Services",
     "accounting professional services", "professional services",
     "accounting prof services", "accounting / professional services",
     "accounting professional services firms",
     "accounting/professional services")

_add("Enterprise Finance Software",
     "enterprise finance software", "enterprise finance/accounting software",
     "enterprise accounting software", "enterprise finance sw")

_add("domain operations Software",
     "domain operations software", "fund services / domain operations",
     "fund services/domain operations", "fund services/domain operations companies",
     "fund services / domain operations companies", "domain operations services",
     "fund services", "domain operations")

_add("Tier 1 AI Companies",
     "tier 1 ai companies", "tier 1 ai", "tier 1 ai company",
     "tier1 ai", "tier 1", "moonshot ai")


def normalize_path(raw_name: str, canonical_paths: list[str] | None = None) -> str:
    """Map raw LLM path name to canonical label via alias lookup.

    Args:
        raw_name: The path name to normalize.
        canonical_paths: Ignored (kept for backwards compatibility).

    Returns:
        Canonical label if a match is found, otherwise raw_name unchanged.
    """
    if not raw_name:
        return raw_name

    return _ALIAS_MAP.get(raw_name.strip().lower(), raw_name)


# Company-to-path map for well-known companies that should always
# resolve to a specific path regardless of what query discovered them.
_COMPANY_PATH: dict[str, str] = {}


def _company(path: str, *names: str) -> None:
    for n in names:
        _COMPANY_PATH[n.lower()] = path


_company("Tier 1 AI Companies",
         # Add your target Tier 1 AI companies here
         )

_company("AI Industry Startup",
         # Add your target industry startups here
         )

_company("Industry Software",
         # Add your target industry software companies here
         )

_company("PE Firm with Portfolio Ops Team",
         # Add your target PE firms here
         )

_company("Internal Ops Transformation",
         # Add your target transformation companies here
         )

_company("Professional Services",
         # Add your target professional services firms here
         )

_company("Enterprise Software",
         # Add your target enterprise software companies here
         )

_company("Industry Services",
         # Add your target industry services companies here
         )


def infer_path_for_company(company: str) -> str:
    """Return canonical path for a known company, or empty string."""
    return _COMPANY_PATH.get(company.strip().lower(), '')


# Company name aliases: variant -> canonical name
_COMPANY_ALIAS: dict[str, str] = {}


def _company_alias(canonical: str, *aliases: str) -> None:
    _COMPANY_ALIAS[canonical.lower()] = canonical
    for a in aliases:
        _COMPANY_ALIAS[a.lower()] = canonical


# Add your company aliases here. Example:
# _company_alias("Canonical Name", "variant 1", "variant 2")
# This prevents duplicates when different sources use different names.


def normalize_company(name: str) -> str:
    """Normalize company name to canonical form via alias lookup."""
    if not name:
        return name
    return _COMPANY_ALIAS.get(name.strip().lower(), name)


def get_canonical_paths() -> list[str]:
    """Return the list of canonical path labels."""
    return list(CANONICAL)
