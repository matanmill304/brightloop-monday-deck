"""Known competitors: name variants, official domains and official social handles.

Unknown competitors are never dropped; they just can't be matched to an
official source, so their claims get no "official" trust.
"""

from __future__ import annotations

import re

COMPETITORS: dict[str, dict[str, list[str]]] = {
    "Lovable": {
        "aliases": ["lovable", "lovable.dev", "lovable ai"],
        "domains": ["lovable.dev"],
        "handles": ["lovable_dev", "lovable"],
        "pricing_url": ["https://lovable.dev/pricing"],
        "home_url": ["https://lovable.dev"],
    },
    "Replit": {
        "aliases": ["replit", "replit.com", "replit agent"],
        "domains": ["replit.com"],
        "handles": ["replit", "amasad"],
        "pricing_url": ["https://replit.com/pricing"],
        "home_url": ["https://replit.com"],
    },
    "Bolt": {
        "aliases": ["bolt", "bolt.new", "boltnew", "stackblitz", "bolt by stackblitz"],
        "domains": ["bolt.new", "stackblitz.com"],
        "handles": ["boltdotnew", "stackblitz"],
        "pricing_url": ["https://bolt.new/pricing"],
        "home_url": ["https://bolt.new"],
    },
    "v0": {
        "aliases": ["v0", "v0.dev", "v0.app", "vercel v0", "v0 by vercel"],
        "domains": ["v0.dev", "v0.app", "vercel.com"],
        "handles": ["v0", "vercel"],
        "pricing_url": ["https://v0.app/pricing"],
        "home_url": ["https://v0.app"],
    },
    "Codex": {
        "aliases": ["codex", "openai codex", "codex cli"],
        "domains": ["openai.com", "chatgpt.com"],
        "handles": ["openai", "openaidevs"],
        "pricing_url": ["https://chatgpt.com/pricing"],
        "home_url": ["https://openai.com/codex"],
    },
    "Claude Code": {
        "aliases": ["claude code", "claude-code", "anthropic claude code"],
        "domains": ["anthropic.com", "claude.com", "claude.ai"],
        "handles": ["anthropicai", "claudeai"],
        "pricing_url": ["https://claude.com/pricing"],
        "home_url": ["https://claude.com/product/claude-code"],
    },
    "Cursor": {
        "aliases": ["cursor", "cursor.com", "anysphere"],
        "domains": ["cursor.com"],
        "handles": ["cursor_ai"],
        "pricing_url": ["https://cursor.com/pricing"],
        "home_url": ["https://cursor.com"],
    },
    "Windsurf": {
        "aliases": ["windsurf", "codeium", "windsurf.com"],
        "domains": ["windsurf.com", "codeium.com"],
        "handles": ["windsurf", "codeium"],
        "pricing_url": ["https://windsurf.com/pricing"],
        "home_url": ["https://windsurf.com"],
    },
    "Base44": {
        "aliases": ["base44", "base 44", "base44.com"],
        "domains": ["base44.com"],
        "handles": ["base44"],
        "pricing_url": ["https://base44.com/pricing"],
        "home_url": ["https://base44.com"],
    },
}

_ALIAS_INDEX = {alias: name for name, info in COMPETITORS.items() for alias in info["aliases"]}


def _key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def canonical_competitor(raw: object) -> str | None:
    """Map a competitor name variant to its canonical name; keep unknown names as given."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    key = _key(raw)
    if key in _ALIAS_INDEX:
        return _ALIAS_INDEX[key]
    stripped = re.sub(r"^(the|by)\s+", "", key)
    return _ALIAS_INDEX.get(stripped, raw.strip())


def competitor_from_domain(domain: str) -> str | None:
    for name, info in COMPETITORS.items():
        if any(domain == d or domain.endswith("." + d) for d in info["domains"]):
            return name
    return None


def is_official_domain(competitor: str, domain: str) -> bool:
    info = COMPETITORS.get(competitor)
    if not info:
        return False
    return any(domain == d or domain.endswith("." + d) for d in info["domains"])


def is_official_handle(competitor: str, handle: str) -> bool:
    info = COMPETITORS.get(competitor)
    return bool(info) and handle.lower().lstrip("@") in info["handles"]


def known_page(competitor: str, source: str) -> tuple[str, str] | None:
    """For a source like "Lovable pricing page" with no URL, the official page to check."""
    info = COMPETITORS.get(competitor)
    text = source.lower()
    if not info or not re.search(r"\b(pricing|official|homepage|home page|website|site)\b", text):
        return None
    url = info["pricing_url"][0] if "pric" in text else info["home_url"][0]
    return info["domains"][0], url
