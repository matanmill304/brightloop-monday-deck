"""Step 2: turn each raw signal into one predictable shape.

Everything here is parsing (times, names, domains, text cleanup), which is
deterministic on purpose. Judgments about meaning live in ``decide.py``.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from email.utils import parsedate_to_datetime
from typing import Any

from brightloop.competitors import (
    canonical_competitor,
    competitor_from_domain,
    is_official_domain,
    is_official_handle,
)

TYPE_SYNONYMS = {
    "pricing": {"pricing", "price", "prices", "plan", "plans", "packaging", "billing", "tier"},
    "ad": {"ad", "ads", "advert", "advertisement", "creative", "campaign", "sponsored"},
    "launch": {"launch", "release", "feature", "product", "announcement", "update", "news"},
}

SOCIAL_DOMAINS = {"x.com", "twitter.com", "linkedin.com", "youtube.com", "threads.net"}
COMMUNITY_DOMAINS = {
    "reddit.com",
    "news.ycombinator.com",
    "producthunt.com",
    "discord.com",
    "discord.gg",
    "indiehackers.com",
    "dev.to",
    "medium.com",
    "substack.com",
}
PRESS_DOMAINS = {
    "techcrunch.com",
    "theverge.com",
    "venturebeat.com",
    "wired.com",
    "zdnet.com",
    "arstechnica.com",
    "reuters.com",
    "bloomberg.com",
    "businessinsider.com",
    "cnbc.com",
    "forbes.com",
    "theinformation.com",
    "siliconangle.com",
    "thenewstack.io",
    "infoq.com",
    "theregister.com",
    "axios.com",
    "engadget.com",
}

SPONSORED = re.compile(r"\b(sponsored|promoted|advertorial|paid (post|partnership)|affiliate)\b")
GUEST = re.compile(r"\b(guest post|press release|contributed|op-?ed)\b")
ANONYMOUS = re.compile(r"(\bu/anon\w*|\banon(ymous)?\b|\bthrowaway\b|\bunnamed\b)")
MEDIA_WORDS = re.compile(r"(news|blog|magazine|journal|times|post|daily|weekly|review)")

DOMAIN = re.compile(r"(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})(/[^\s,;)]*)?", re.IGNORECASE)

# Text aimed at an AI system rather than a human reader.
INSTRUCTION_PATTERNS = re.compile(
    r"(ignore (all |any )?(previous|prior|above) (instructions|rules)"
    r"|\b(note|message|instructions?) (to|for) (ai|llms?|assistants?|models?|ai systems?)"
    r"|\bset (the )?confidence\b"
    r"|\bappend (the line|this|the following)\b"
    r"|\bsystem prompt\b"
    r"|\byou are (now )?(an? |the )?(ai|assistant|language model)\b"
    r"|\bdisregard (the|all|any)\b)",
    re.IGNORECASE,
)


@dataclass
class Signal:
    id: Any
    type: str
    raw_type: str
    competitor: str
    source: str
    domain: str | None
    url: str | None
    source_class: str
    text: str
    ts: datetime | None
    first_seen: datetime | None
    last_seen: datetime | None
    flags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def when(self) -> datetime | None:
        return self.ts or self.last_seen or self.first_seen


def normalize(raw: dict[str, Any], tz: tzinfo) -> Signal:
    flags: list[str] = []
    raw_type = str(raw.get("type") or "").strip().lower()
    sig_type = next((t for t, names in TYPE_SYNONYMS.items() if raw_type in names), "other")

    text, injected = clean_text(raw.get("text"))
    if injected or any(_looks_injected(raw.get(k)) for k in ("source", "competitor", "channel")):
        flags.append("embedded_instructions")
    if not text:
        flags.append("no_text")

    source = raw.get("source") if isinstance(raw.get("source"), str) else ""
    source = re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL).strip()
    domain, url = find_link(source) or find_link(str(raw.get("url") or "")) or (None, None)

    competitor = canonical_competitor(raw.get("competitor"))
    if competitor is None and domain:
        competitor = competitor_from_domain(domain)
    competitor = competitor or "Unknown"

    ts = parse_when(raw.get("ts") or raw.get("date") or raw.get("timestamp"), tz)
    first_seen = parse_when(raw.get("first_seen"), tz)
    last_seen = parse_when(raw.get("last_seen"), tz, end_of_day=True)
    if ts is None and first_seen is None and last_seen is None:
        flags.append("no_date")

    return Signal(
        id=raw.get("id"),
        type=sig_type,
        raw_type=raw_type,
        competitor=competitor,
        source=source,
        domain=domain,
        url=url,
        source_class=classify_source(sig_type, competitor, source, domain, url),
        text=text,
        ts=ts,
        first_seen=first_seen,
        last_seen=last_seen,
        flags=flags,
        raw=raw,
    )


def clean_text(value: Any) -> tuple[str, bool]:
    """Strip HTML and hidden comments; report whether instructions to an AI were found."""
    if not isinstance(value, str):
        return "", False
    injected = bool(INSTRUCTION_PATTERNS.search(value))
    comments = re.findall(r"<!--(.*?)(?:-->|$)", value, flags=re.DOTALL)
    if any(c.strip() for c in comments):
        injected = True
    text = re.sub(r"<!--.*?(?:-->|$)", " ", value, flags=re.DOTALL)
    text = re.sub(r"<[^>]{0,200}>", " ", text)
    text = html.unescape(text)
    # Drop sentences that address an AI system instead of describing an event.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    text = " ".join(s for s in sentences if not INSTRUCTION_PATTERNS.search(s))
    return re.sub(r"\s+", " ", text).strip(), injected


def _looks_injected(value: Any) -> bool:
    return isinstance(value, str) and ("<!--" in value or bool(INSTRUCTION_PATTERNS.search(value)))


def find_link(source: str) -> tuple[str, str | None] | None:
    match = DOMAIN.search(source or "")
    if not match:
        return None
    domain = match.group(1).lower().removeprefix("www.")
    if domain.endswith(".example") or "." not in domain:
        # Reserved example domains can't be opened; keep the domain for trust, no link.
        return domain, None
    path = (match.group(2) or "").rstrip(".")
    if domain in SOCIAL_DOMAINS:
        path = path.replace("/@", "/")
    return domain, f"https://{domain}{path}"


def classify_source(
    sig_type: str, competitor: str, source: str, domain: str | None, url: str | None
) -> str:
    """official | press | community | sponsored | guest | anonymous | unknown."""
    text = source.lower()
    if SPONSORED.search(text):
        return "sponsored"
    if ANONYMOUS.search(text):
        return "anonymous"
    if GUEST.search(text):
        return "guest"
    if domain:
        if is_official_domain(competitor, domain):
            return "official"
        if domain in SOCIAL_DOMAINS:
            handle = _handle(url or source)
            if handle and is_official_handle(competitor, handle):
                return "official"
            return "community"
        if domain in COMMUNITY_DOMAINS or any(domain.endswith("." + d) for d in COMMUNITY_DOMAINS):
            return "community"
        if domain in PRESS_DOMAINS:
            return "press"
        if MEDIA_WORDS.search(domain):
            return "media"
    if sig_type == "ad":
        # An ad library entry is the competitor's own paid message.
        return "advertiser"
    return "unknown"


def _handle(value: str) -> str | None:
    match = re.search(r"(?:x|twitter|linkedin|threads)\.(?:com|net)/(?:company/)?@?([\w.]+)", value)
    return match.group(1) if match else None


def parse_when(value: Any, tz: tzinfo, end_of_day: bool = False) -> datetime | None:
    """Parse almost any timestamp; naive times are read in the input's timezone. Returns UTC."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None

    text = value.strip()
    date_only = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", text))
    utc_suffix = re.search(r"\s*\b(UTC|GMT|Z)$", text, re.IGNORECASE)
    if utc_suffix and not text.endswith("Z"):
        text = text[: utc_suffix.start()] + "+00:00"

    parsed = _try_iso(text) or _try_rfc2822(text) or _try_formats(text)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    if date_only and end_of_day:
        parsed = parsed + timedelta(days=1) - timedelta(seconds=1)
    return parsed.astimezone(UTC)


def _try_iso(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace(" ", "T", 1) if "T" not in text else text)
    except ValueError:
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None


def _try_rfc2822(text: str) -> datetime | None:
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None


def _try_formats(text: str) -> datetime | None:
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%Y/%m/%d", "%b %d %Y %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
