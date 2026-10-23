"""What changed: read a change stated inside one signal, or compare two snapshots of a page.

Maya's deck is "what's different from last week", so a signal that only states the current
price ("Pro: $25/month") is a fact, not a change. A change is either:
  A. stated in the text ("was $20", "from $20 to $25", "introduces a Starter tier"), or
  B. found by comparing two snapshots of the same official page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from brightloop.decide import pricing_cues

AMOUNT = r"[$€£]\s?\d[\d,]*(?:\.\d+)?"
UNIT = r"(?:\s?(?:/|per|a)\s?(?:mo(?:nth)?|year|yr|seat|user|member|editor)s?\b)?"
PLAN_NAMES = (
    "free|hobby|starter|basic|core|pro|plus|premium|team|teams|business|scale|growth|max|ultra"
    "|enterprise|launch"
)

# A: the text itself says something changed.
FROM_TO = re.compile(
    rf"(?:from\s+)?({AMOUNT}{UNIT})\s*(?:→|->|=>|to)\s*({AMOUNT}{UNIT})", re.IGNORECASE
)
# "(was $20 last week)", "previously $20", "down from $30": the amount after it is the old one.
PREVIOUSLY = re.compile(
    rf"\b(was|previously|formerly|currently|today|down from|up from|instead of|compared to)"
    rf"\s+({AMOUNT}{UNIT})",
    re.IGNORECASE,
)
# The same with a plain number: "5 messages/day (was 10)", "200 credits (previously 100)".
NUMBER_PREVIOUSLY = re.compile(
    r"\b(was|previously|formerly|currently|down from|up from)\s+(\d[\d,.]*)\b", re.IGNORECASE
)
PRICE_WITH_UNIT_RE = re.compile(rf"{AMOUNT}{UNIT}", re.IGNORECASE)
DOMAIN_LIKE = re.compile(
    r"\b[a-z][\w-]*\.(?:new|dev|app|com|ai|io|so|sh|co|net|org)\b", re.IGNORECASE
)
PRICE_VERB = re.compile(
    r"\b(rais(e|es|ed|ing)|increas(e|es|ed)|hik(e|es|ed)|cut(s|ting)?|lower(s|ed)?|reduc(e|es|ed)"
    r"|drop(s|ped)?|slash(es|ed)?|halv(e|es|ed)|doubl(e|es|ed)|tripl(e|es|ed))\b",
    re.IGNORECASE,
)
PLAN_ADDED = re.compile(
    rf"\b(introduc\w*|add(s|ed)?|launch(es|ed)?|unveil\w*|roll(s|ed)? out|new)\b[^.]{{0,40}}"
    rf"\b(plans?|tiers?|({PLAN_NAMES}) (plan|tier))\b",
    re.IGNORECASE,
)
PLAN_REMOVED = re.compile(
    r"\b(remov\w*|drop(s|ped)?|discontinu\w*|sunset\w*|retir\w*|kill(s|ed)?|eliminat\w*"
    r"|no longer (offers?|available))\b[^.]{0,40}\b(plans?|tiers?)\b"
    r"|\b(plans?|tiers?)\b[^.]{0,30}\b(is|are) (gone|discontinued|retired|no longer)\b",
    re.IGNORECASE,
)
RENAMED = re.compile(r"\brenam\w*\b", re.IGNORECASE)
LIMITS = re.compile(
    r"\b(credits?|limits?|quotas?|requests?|messages?|usage|tokens?|seats?|minutes|builds?)\b",
    re.IGNORECASE,
)
AVAILABILITY = re.compile(
    rf"\b(now|is live|rolls? out|rolled out|available|included|comes with|moved)\b[^.]{{0,40}}"
    rf"\b(all|every|each|paid|({PLAN_NAMES}))\s(plans?|tiers?|users|customers|subscribers)\b",
    re.IGNORECASE,
)
GENERIC_CHANGE = re.compile(
    r"\b(now|no longer|changed?|changes|updated?|updates|replaced|switch(es|ed)?|new|introduc\w*"
    r"|launch(es|ed)?|moved|will (be|cost|go|become|change)|starting|effective|rewrit\w*|swapped|went from|instead of)\b",
    re.IGNORECASE,
)
QUOTED_PAIR = re.compile(r"""from\s+["'“‘](.+?)["'”’]\s+to\s+["'“‘](.+?)["'”’]""", re.IGNORECASE)


@dataclass
class Change:
    kind: (
        str  # price | plan_added | plan_removed | renamed | limits | availability | wording | other
    )
    old: str | None = None
    new: str | None = None
    evidence: str = ""  # the words that showed the change
    plan: str | None = None


def stated_change(text: str) -> Change | None:
    """The change a signal states about itself, or None if it only states a fact."""
    # Domain names are not words: "Bolt.new" must not read as "new".
    text = DOMAIN_LIKE.sub(" ", text)
    # Money is not a price: "raises $330M at a $6.6B valuation" is company news.
    if "company finance" in pricing_cues(text):
        return None
    if m := PREVIOUSLY.search(text):
        old = clean(m.group(2))
        others = [clean(a.group(0)) for a in PRICE_WITH_UNIT_RE.finditer(text)]
        new = next((a for a in others if a and a != old and not old.startswith(a)), None)
        return Change("price", old, new, m.group(0), plan=plan_name(text))
    if m := NUMBER_PREVIOUSLY.search(text):
        kind = "limits" if LIMITS.search(text) else "other"
        return Change(kind, old=m.group(2), evidence=m.group(0), plan=plan_name(text))
    m = FROM_TO.search(text)
    if m and not re.search(r"\bup to\s*$", text[: m.start()], re.IGNORECASE):
        if number(m.group(1)) == number(m.group(2)):
            return None  # "$25 → $25": the same price on both sides is not a change
        return Change("price", clean(m.group(1)), clean(m.group(2)), m.group(0), plan_name(text))
    if m := QUOTED_PAIR.search(text):
        return Change("wording", m.group(1), m.group(2), m.group(0))
    if m := PLAN_REMOVED.search(text):
        return Change("plan_removed", evidence=m.group(0))
    if m := RENAMED.search(text):
        return Change("renamed", evidence=m.group(0))
    if m := PLAN_ADDED.search(text):
        return Change("plan_added", evidence=m.group(0))
    if (m := PRICE_VERB.search(text)) and LIMITS.search(text) and not re.search(AMOUNT, text):
        return Change("limits", evidence=m.group(0))
    if m := PRICE_VERB.search(text):
        return Change("price", new=first_amount(text), evidence=m.group(0))
    if m := AVAILABILITY.search(text):
        return Change("availability", evidence=m.group(0))
    if (m := GENERIC_CHANGE.search(text)) and (amount := first_amount(text)):
        # "Core plan now $25/month": a new price, the old one isn't stated
        return Change("price", new=amount, evidence=m.group(0), plan=plan_name(text))
    if m := GENERIC_CHANGE.search(text):
        return Change("other", new=first_amount(text), evidence=m.group(0))
    return None


# B: compare two snapshots of the same page.


@dataclass
class PageState:
    prices: dict[str, str] = field(default_factory=dict)  # plan -> price, when readable
    amounts: set[str] = field(default_factory=set)
    blocks: list[str] = field(default_factory=list)  # visible text lines, normalized


PLAN_PRICE = re.compile(rf"\b({PLAN_NAMES})\b[^$€£.\n]{{0,25}}?({AMOUNT}{UNIT})", re.IGNORECASE)
NOISE_LINE = re.compile(
    r"(cookie|privacy|©|copyright|all rights reserved|\b\d{1,2}:\d{2}\b|\b(19|20)\d{2}\b"
    r"|^\W*$|^\d[\d,.]*\+?$)",
    re.IGNORECASE,
)


def page_state(text: str) -> PageState:
    prices = {}
    for m in PLAN_PRICE.finditer(text):
        prices.setdefault(m.group(1).title(), clean(m.group(2)))
    amounts = {clean(a) for a in re.findall(AMOUNT, text)}
    lines = re.split(r"(?<=[.!?])\s+|\n+", text)
    blocks = [norm_line(line) for line in lines if line.strip() and not NOISE_LINE.search(line)]
    return PageState(prices=prices, amounts=amounts, blocks=[b for b in blocks if b])


def compare(old: PageState, new: PageState) -> list[Change]:
    """Differences between two snapshots of the same page, most specific first."""
    changes: list[Change] = []
    for plan in sorted(old.prices.keys() & new.prices.keys()):
        if old.prices[plan] != new.prices[plan]:
            changes.append(
                Change("price", f"{plan} {old.prices[plan]}", f"{plan} {new.prices[plan]}")
            )
    for plan in sorted(new.prices.keys() - old.prices.keys()):
        if old.prices:
            changes.append(Change("plan_added", new=f"{plan} {new.prices[plan]}"))
    for plan in sorted(old.prices.keys() - new.prices.keys()):
        if new.prices:
            changes.append(Change("plan_removed", old=f"{plan} {old.prices[plan]}"))
    if not changes and old.amounts != new.amounts and (old.amounts or new.amounts):
        changes.append(
            Change("price", ", ".join(sorted(old.amounts)) or None, ", ".join(sorted(new.amounts)))
        )
    added = [b for b in new.blocks if b not in old.blocks]
    removed = [b for b in old.blocks if b not in new.blocks]
    if added or removed:
        changes.append(
            Change("wording", "; ".join(removed[:3]) or None, "; ".join(added[:3]) or None)
        )
    return changes


def describe(change: Change) -> str:
    if change.old and change.new:
        plan = f"{change.plan}: " if change.plan else ""
        return f"{plan}{change.old} → {change.new}"
    if change.kind == "plan_added" and change.new:
        return f"new plan: {change.new}"
    if change.kind == "plan_removed" and change.old:
        return f"plan removed: {change.old}"
    if change.kind == "wording":
        parts = []
        if change.new:
            parts.append(f'added "{change.new}"')
        if change.old:
            parts.append(f'removed "{change.old}"')
        return "; ".join(parts)
    return change.new or ""


def plan_name(text: str) -> str | None:
    m = re.search(r"\b(" + PLAN_NAMES + r")\b", text, re.IGNORECASE)
    return m.group(1).title() if m else None


def first_amount(text: str) -> str | None:
    m = re.search(rf"{AMOUNT}{UNIT}", text)
    return clean(m.group(0)) if m else None


def clean(value: str | None) -> str | None:
    return re.sub(r"\s+", " ", value).strip() if value else None


def norm_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip().strip(".").lower()[:200]


def number(value: str) -> float | None:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", value or "")
    return float(m.group(0).replace(",", "")) if m else None


def all_price_changes(text: str) -> list[Change]:
    """Every "old → new" in one signal: "Pro $20 → $25; Business $40 → $50" is two changes."""
    text = DOMAIN_LIKE.sub(" ", text)
    changes = []
    for m in FROM_TO.finditer(text):
        if number(m.group(1)) != number(m.group(2)):
            before = text[max(0, m.start() - 30) : m.start()]
            names = re.findall(r"(?i)\b(" + PLAN_NAMES + r")\b", before)
            plan = names[-1].title() if names else None  # the nearest plan name before the price
            changes.append(Change("price", clean(m.group(1)), clean(m.group(2)), m.group(0), plan))
    return changes


def looks_like_failed_capture(old: PageState, new: PageState) -> bool:
    """A page that suddenly lost all its prices and almost all its text was not captured."""
    return bool(old.amounts) and not new.amounts and len(new.blocks) <= 2
