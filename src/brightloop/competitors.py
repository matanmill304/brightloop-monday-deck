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
    },
    "Replit": {
        "aliases": ["replit", "replit.com", "replit agent"],
        "domains": ["replit.com"],
        "handles": ["replit", "amasad"],
    },
    "Bolt": {
        "aliases": ["bolt", "bolt.new", "boltnew", "stackblitz", "bolt by stackblitz"],
        "domains": ["bolt.new", "stackblitz.com"],
        "handles": ["boltdotnew", "stackblitz"],
    },
    "v0": {
        "aliases": ["v0", "v0.dev", "v0.app", "vercel v0", "v0 by vercel"],
        "domains": ["v0.dev", "v0.app", "vercel.com"],
        "handles": ["v0", "vercel"],
    },
    "Codex": {
        "aliases": ["codex", "openai codex", "codex cli"],
        "domains": ["openai.com", "chatgpt.com"],
        "handles": ["openai", "openaidevs"],
    },
    "Claude Code": {
        "aliases": ["claude code", "claude-code", "anthropic claude code"],
        "domains": ["anthropic.com", "claude.com", "claude.ai"],
        "handles": ["anthropicai", "claudeai"],
    },
    "Cursor": {
        "aliases": ["cursor", "cursor.com", "anysphere"],
        "domains": ["cursor.com"],
        "handles": ["cursor_ai"],
    },
    "Windsurf": {
        "aliases": ["windsurf", "codeium", "windsurf.com"],
        "domains": ["windsurf.com", "codeium.com"],
        "handles": ["windsurf", "codeium"],
    },
    "Base44": {
        "aliases": ["base44", "base 44", "base44.com"],
        "domains": ["base44.com"],
        "handles": ["base44"],
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
