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
    COMPETITORS,
    canonical_competitor,
    competitor_from_domain,
    is_official_domain,
    is_official_handle,
    known_page,
    name_roots,
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
    r"|\b(note|message|instructions?) (to|for) (the )?(ai|llms?|assistants?|models?|ai models?|ai systems?)"
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
    page: str = "other"  # pricing | home | other
    flags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def official(self) -> bool:
        """From the competitor itself: its own site, its own account or its own ad."""
        return self.source_class in ("official", "observed", "advertiser")

    @property
    def is_snapshot(self) -> bool:
        """A captured page (flagged, or many lines of page text): a state, never a statement.

        A full page always contains words like "new" or "now" (badges, buttons), so reading it
        as a stated change would be wrong; it can only be compared with another snapshot.
        """
        return self.raw.get("snapshot") is True or self.text.count("\n") >= 7

    @property
    def on_page(self) -> bool:
        """From one of the two pages Maya treats as the source of truth."""
        return self.source_class in ("official", "observed") and self.page in ("pricing", "home")

    @property
    def when(self) -> datetime | None:
        return self.ts or self.last_seen or self.first_seen


TEXT_FIELDS = ("text", "title", "headline", "summary", "description", "body", "content", "message")
SOURCE_FIELDS = ("source", "url", "link", "source_url", "href", "domain")
TIME_FIELDS = (
    "ts",
    "timestamp",
    "date",
    "datetime",
    "time",
    "published_at",
    "published",
    "created_at",
    "seen_at",
    "observed_at",
    "updated_at",
)
MAX_TEXT = 40000  # longer text is truncated: a 22k-character page scrape still fits


def normalize(raw: dict[str, Any], tz: tzinfo) -> Signal:
    flags: list[str] = []
    raw_type = flatten(raw.get("type") or raw.get("kind") or raw.get("category")).strip().lower()
    sig_type = normalize_type(raw_type)

    raw_text = next((flatten(raw.get(k)) for k in TEXT_FIELDS if flatten(raw.get(k)).strip()), "")
    text, injected = clean_text(raw_text[:MAX_TEXT])
    if injected or any(_looks_injected(flatten(raw.get(k))) for k in ("source", "competitor")):
        flags.append("embedded_instructions")
    if not text:
        flags.append("no_text")

    source = flatten(raw.get("source"))[:500]
    source = re.sub(r"<!--.*?(?:-->|$)", "", source, flags=re.DOTALL).strip()
    link = None
    for key in SOURCE_FIELDS:
        link = find_link(flatten(raw.get(key))[:500])
        if link:
            break
    domain, url = link or (None, None)

    competitor = canonical_competitor(flatten(raw.get("competitor") or raw.get("company")))
    if competitor is None and domain:
        competitor = competitor_from_domain(domain)
    competitor = competitor or "Unknown"
    if domain is None:
        page = known_page(competitor, source)
        if page:
            domain, url = page
            flags.append("link_from_named_page")
    flags.extend(name_collision(competitor, domain, text))

    ts = next((t for k in TIME_FIELDS if (t := parse_when(raw.get(k), tz))), None)
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
        page=page_of(url, source),
        text=text,
        ts=ts,
        first_seen=first_seen,
        last_seen=last_seen,
        flags=flags,
        raw=raw,
    )


def flatten(value: Any, depth: int = 0) -> str:
    """Any JSON value as text: strings as-is, lists/objects as their string leaves joined."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or value is None or depth > 3:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(flatten(v, depth + 1) for v in value.values()).strip()
    if isinstance(value, (list, tuple)):
        return " ".join(flatten(v, depth + 1) for v in value).strip()
    return ""


def normalize_type(raw_type: str) -> str:
    """Exact synonyms first ("price"), then words inside labels ("pricing_change", "Ad creative")."""
    for sig_type, names in TYPE_SYNONYMS.items():
        if raw_type in names:
            return sig_type
    words = set(re.findall(r"[a-z]+", raw_type))
    for sig_type, names in TYPE_SYNONYMS.items():
        if words & names:
            return sig_type
    return "other"


# Things that share a competitor's name. A source domain that carries the name but is not the
# competitor's own site, or text about scooters under "Bolt", means a different "Bolt".
COLLISION_WORDS = {
    "Bolt": r"scooters?|e-scooters?|taxis?|ride-hailing|rides?|fares?|drivers?|fleet"
    r"|micromobility|couriers?|food delivery|chevy|chevrolet|\bev\b|e-bikes?|bikes?|charging"
    r"|usain|pistols?|smart locks?|pok[eé]mon",
    "Cursor": r"mouse|pointer|powertoys|caret|blinking",
    "Windsurf": r"surf(ing|ers?)?|board|foil|sail(ing)?|waves|beach",
    "Lovable": r"anime|puppy|kitten|character|neighbou?rhood|bookstore|quirks|lunch(es)?",
    "v0": r"\bv0\.\d",
}
SOFTWARE_CONTEXT = re.compile(
    r"\b(ai|apps?|code|coding|coders?|developers?|devs?|software|agents?|vibe|builds?|builder"
    r"|deploy\w*|ide|llms?|models?|prompts?|saas|web\s?apps?|websites?|platform|github"
    r"|programming|no-code|low-code|full-stack|frontend|backend)\b",
    re.IGNORECASE,
)


def name_collision(competitor: str, domain: str | None, text: str) -> list[str]:
    flags = []
    if domain and lookalike_domain(competitor, domain):
        flags.append("name_collision_domain")
    words = COLLISION_WORDS.get(competitor)
    if (
        words
        and re.search(rf"\b(?:{words})\b", text, re.IGNORECASE)
        and not SOFTWARE_CONTEXT.search(text)
    ):
        flags.append("name_collision_text")
    return flags


def lookalike_domain(competitor: str, domain: str) -> bool:
    """bolt.eu or bolt.com for Bolt (whose site is bolt.new): same name, not the same company."""
    if is_official_domain(competitor, domain):
        return False
    roots = name_roots(competitor)
    labels = domain.split(".")[:-1]  # drop the TLD
    return any(label == root or label.startswith(root + "-") for label in labels for root in roots)


def clean_text(value: Any) -> tuple[str, bool]:
    """Strip HTML and hidden comments; report whether instructions to an AI were found."""
    if not isinstance(value, str):
        return "", False
    # Zero-width and other invisible characters can split words to dodge the patterns.
    value = re.sub("[\u200b-\u200f\u2060-\u2064\ufeff\u00ad]", "", value)
    injected = bool(INSTRUCTION_PATTERNS.search(value))
    comments = re.findall(r"<!--(.*?)(?:-->|$)", value, flags=re.DOTALL)
    if any(c.strip() for c in comments):
        injected = True
    text = re.sub(r"<!--.*?(?:-->|$)", " ", value, flags=re.DOTALL)
    text = re.sub(r"<[^>]{0,200}>", " ", text)
    text = html.unescape(text)
    # Drop sentences that address an AI system instead of describing an event. Line breaks are
    # kept: page snapshots are line-based (plan name, then its price on the next line).
    kept = []
    for line in text.splitlines():
        sentences = re.split(r"(?<=[.!?])\s+", line)
        kept.append(" ".join(s for s in sentences if not INSTRUCTION_PATTERNS.search(s)))
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in kept]
    return "\n".join(line for line in lines if line), injected


def _looks_injected(value: Any) -> bool:
    return isinstance(value, str) and ("<!--" in value or bool(INSTRUCTION_PATTERNS.search(value)))


WAYBACK = re.compile(r"web\.archive\.org/web/(\d{4,14})\w*/(https?://\S+)", re.IGNORECASE)


def find_link(source: str) -> tuple[str, str | None] | None:
    # An archived copy of a page is that page: read the original URL out of the Wayback link.
    if archived := WAYBACK.search(source or ""):
        source = archived.group(2)
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
    if sig_type == "ad" and (domain is None or any(domain.endswith(d) for d in AD_LIBRARIES)):
        # An ad library entry is the competitor's own paid message.
        return "advertiser"
    if domain:
        if is_official_domain(competitor, domain) or own_domain_by_name(competitor, domain):
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


AD_LIBRARIES = ("facebook.com", "adstransparency.google.com", "linkedin.com")


def own_domain_by_name(competitor: str, domain: str) -> bool:
    """For a competitor missing from our dictionary: acme.io is Acme's own site."""
    if competitor in COMPETITORS or competitor == "Unknown":
        return False
    slug = re.sub(r"[^a-z0-9]", "", competitor.lower())
    return bool(slug) and slug in domain.split(".")[:-1]


PRICING_PATH = re.compile(
    r"/(pricing|plans?|billing|subscribe|upgrade|prices?)(/|$|\?|#)", re.IGNORECASE
)
HOME_PATH = re.compile(r"^/?((en|us|en-us|home)/?)?$", re.IGNORECASE)


def page_of(url: str | None, source: str) -> str:
    """Which page a signal describes: pricing, home, or other (blog, changelog, social…)."""
    if url:
        host = re.sub(r"^https?://", "", url).split("/")[0].removeprefix("www.")
        path = re.sub(r"^https?://[^/]+", "", url)
        if host.count(".") > 1:
            # status.bolt.new or blog.replit.com is not the pricing page or the homepage
            return "other"
        if PRICING_PATH.search(path + "/"):
            return "pricing"
        if HOME_PATH.fullmatch(path.split("?")[0]):
            return "home"
        return "other"
    text = source.lower()
    if re.search(r"\bpric(ing|es)\b|\bplans? page\b", text):
        return "pricing"
    if re.search(r"\bhome ?page\b|\blanding page\b", text):
        return "home"
    return "other"


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
