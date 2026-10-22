"""Steps 4 to 6: group, trust, and relevance to Maya. The rules-based version.

These are the judgments about meaning. With a Jev key, the same questions can
be answered by Jev; without keys (the reviewers' runs) these rules are used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

from brightloop.normalize import Signal

# ---- What the text says -------------------------------------------------------

# A money amount. On its own it is NOT a price: funding rounds and revenue are money too.
MONEY = (
    r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?\s?[kmb]?\b|\b\d[\d,]*(?:\.\d+)?\s?(?:usd|eur|gbp|dollars?)\b)"
)
PRICE = re.compile(MONEY, re.IGNORECASE)
# A price: money with a unit ("$25/month", "$3 per million tokens").
PRICE_WITH_UNIT = re.compile(
    MONEY + r"\s?(?:/|per|a|an|each)\s?(?:mo(?:nth)?|year|yr|seat|user|member|editor"
    r"|million tokens|m tokens|1m|request|credit|hour)s?\b",
    re.IGNORECASE,
)
# Words that only appear when talking about what customers pay.
PRICE_WORDS = re.compile(
    r"\b(pric(e|es|ed|ing)|billing|billed|subscriptions?|pay[- ]as[- ]you[- ]go|usage[- ]based"
    r"|free (tier|plan)|freemium|paywall(ed)?|credits?|token[- ]based|per[- ]seat|refunds?)\b",
    re.IGNORECASE,
)
PLAN_WORDS = re.compile(
    r"\b(plans?|tiers?|seats?|trials?|discounts?|(pro|team|teams|business|enterprise|starter"
    r"|hobby|core|max|plus|premium|free) (plan|tier|users|customers|subscribers))\b",
    re.IGNORECASE,
)
CHANGE_WORDS = re.compile(
    r"\b(rais(e|es|ed|ing)|cut(s|ting)?|slash(es|ed)?|halv(e|es|ed)|doubl(e|es|ed)|hikes?"
    r"|increas(e|es|ed)|reduc(e|es|ed)|drops?|lower(s|ed)?|now|new|adds?|introduc(e|es|ed)"
    r"|launch(es|ed)?|remov(e|es|ed)|ends?|expir(e|es|ed)|brings? back|moves?|changes?"
    r"|updates?|switch(es|ed)?|shifts?|cheaper|costlier|more expensive)\b",
    re.IGNORECASE,
)
USAGE_LIMITS = re.compile(
    r"\b((usage|rate|weekly|daily|hourly|monthly|five-hour|session)( [\w-]+){0,2}"
    r" (limits?|caps?|boost)|quotas?|increased usage|more usage|limits? (on|for|to)"
    r"|unlimited (access|usage|requests))\b",
    re.IGNORECASE,
)
# A cost change on something customers buy ("cache-read cost by 50%", "half the API cost").
COST_CHANGE = re.compile(
    r"(\bcosts?\b.{0,30}\b(cut|slash|reduc|half|halv|lower|drop|by \d+ ?%)"
    r"|\b(cut|slash|reduc|half|halv|lower|\d+ ?%)\w*\b.{0,30}\bcosts?\b)",
    re.IGNORECASE,
)
# ...and it only counts when the cost is on something customers buy, not an efficiency gain.
COST_OBJECT = re.compile(
    r"\b(api|cache|tokens?|input|output|plans?|subscriptions?|seats?)\b", re.IGNORECASE
)
PACKAGING = re.compile(
    r"\b((all|every|each) (plans?|tiers?|paid plans?|users|customers|subscribers)"
    r"|available (on|to|for|in) (free|pro|team|teams|business|enterprise|all|every|paid)"
    r"|now (free|included)|included (in|with)|moved (to|behind)|subscriptions? (with|for))\b",
    re.IGNORECASE,
)
# Company finance: money about the company, not about what customers pay.
COMPANY_FINANCE = re.compile(
    r"\b(valuation|valued|funding|raise[sd]?|raising|round|series [a-h]|seed|investors?"
    r"|backs?|backed|revenue|arr|ipo|acquir(e|es|ed|ing)|acquisition|buys?|bought|profit"
    r"|earnings|layoffs?|headcount)\b",
    re.IGNORECASE,
)
# A plan name next to an amount ("Pro is $15 now") reads as a price.
PLAN_PRICE = re.compile(
    r"\b(pro|team|teams|business|enterprise|starter|hobby|core|max|plus|premium|basic)\b"
    r"[^.$€£]{0,20}" + MONEY,
    re.IGNORECASE,
)
HYPE = re.compile(
    r"\b(free forever|forever free|no limits|unlimited|100%|guaranteed|best ever|#1"
    r"|never pay|completely free|totally free)\b",
    re.IGNORECASE,
)
HEDGE = re.compile(
    r"(\bheard\b|\brumou?rs?\b|\bapparently\b|\breportedly\b|\ballegedly\b|\bunconfirmed\b"
    r"|\bmight\b|\bmaybe\b|\bcould be\b|\bsources say\b|\bleak(ed|s)?\b|\?\?|\?\s*$)",
    re.IGNORECASE,
)

STOPWORDS = frozenset(
    re.findall(
        r"\w+",
        "a an the and or of to for in on at by with is are was were be been it its this that "
        "now new just has have had will can our their from as all every each",
    )
)
GENERIC = frozenset(
    re.findall(
        r"\w+", "plan plans tier tiers pricing price prices month monthly free pro team users"
    )
)


def pricing_score(text: str) -> int:
    """How strongly the text describes what customers pay or get. 2+ = relevant to Maya.

    Strong cues (2 each): a price with a unit, pricing/billing words, usage limits,
    packaging phrases. Weak cues (1 each): plan/tier/seat words; a money amount next to a
    change word. Company finance (funding, valuation, revenue) caps the score at 1 unless
    customer pricing words are also present: money is not a price.
    """
    cues = pricing_cues(text)
    score = sum(points for name, (points, _) in cues.items() if name != "company finance")
    if "company finance" in cues:
        score = min(score, 1)
    return score


def pricing_cues(text: str) -> dict[str, tuple[int, str]]:
    """Which relevance cues fired, with their points and the words that matched."""

    def hit(pattern: re.Pattern[str]) -> str | None:
        match = pattern.search(text)
        return match.group(0) if match else None

    cues: dict[str, tuple[int, str]] = {}
    checks = [
        ("price with a unit", 2, hit(PRICE_WITH_UNIT)),
        ("pricing words", 2, hit(PRICE_WORDS)),
        ("usage limits", 2, hit(USAGE_LIMITS)),
        ("packaging phrase", 2, hit(PACKAGING)),
        ("cost change", 2, hit(COST_CHANGE) if COST_OBJECT.search(text) else None),
        ("plan words", 1, hit(PLAN_WORDS)),
        ("plan name next to an amount", 1, hit(PLAN_PRICE)),
        ("amount + change word", 1, hit(PRICE) if CHANGE_WORDS.search(text) else None),
    ]
    for name, points, matched in checks:
        if matched:
            cues[name] = (points, matched)
    # "$25/month" is never a funding round, so customer-pricing cues override the finance check.
    finance = hit(COMPANY_FINANCE)
    customer = {"price with a unit", "pricing words", "plan words"} & cues.keys()
    if finance and not customer:
        cues["company finance"] = (0, finance)
    return cues


def is_pricing_related(signal: Signal) -> bool:
    """Maya's scope: is this about price, plans or packaging? Judged on content."""
    return pricing_score(signal.text) >= 2


MESSAGING = re.compile(
    r"\b(homepage|home page|headline|tagline|hero (text|copy|section)|positioning|slogan"
    r"|rebrand(s|ed|ing)?|now (calls|describes|positions) itself)\b",
    re.IGNORECASE,
)


def is_messaging_change(signal: Signal) -> bool:
    """A change to how a competitor presents itself on its own homepage (in Maya's deck)."""
    official = signal.source_class in ("official", "observed")
    return official and bool(MESSAGING.search(signal.text) or MESSAGING.search(signal.source))


def prices(text: str) -> set[str]:
    return {re.sub(r"\s", "", m.group(0)).lower() for m in PRICE.finditer(text)}


def content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)?", text.lower())
    return {w for w in words if w.isdigit() or (w not in STOPWORDS and len(w) > 1)}


# ---- Relevance to Maya --------------------------------------------------------


def relevance_reason(signal: Signal) -> str | None:
    """None if the signal belongs in Maya's deck, else why not (naming who owns it)."""
    if "no_text" in signal.flags:
        return with_notes("No text to evaluate.", signal)
    if "name_collision_domain" in signal.flags:
        return (
            f"Probably a different company named like {signal.competitor}: "
            f"{signal.domain} is not {signal.competitor}'s site."
        )
    if "name_collision_text" in signal.flags:
        return f"About something else that shares the name {signal.competitor}, not the competitor."
    if signal.competitor == "Unknown":
        return with_notes("No competitor named, so it can't go on a competitor slide.", signal)
    if is_pricing_related(signal) or is_messaging_change(signal):
        return None
    if signal.type == "ad":
        reason = "Ad creative with no pricing claim: Daniel's area (paid), not Maya's deck."
        weeks = running_weeks(signal)
        if weeks is not None and weeks >= 8:
            reason += f" It has been running about {weeks} weeks, so worth passing to Daniel."
    elif signal.type == "launch":
        reason = "Feature launch with no pricing or packaging change: product's area; route to Noa."
    elif signal.type == "pricing":
        reason = "Labeled pricing, but the text describes no price, plan or packaging change."
    else:
        reason = "Not a pricing or packaging change, which is all Maya's deck covers."
    return with_notes(reason, signal)


def with_notes(reason: str, signal: Signal) -> str:
    """Add what else is wrong with a skipped signal, so the reason tells the whole story."""
    notes = []
    if signal.source_class in ("anonymous", "sponsored", "guest"):
        notes.append(f"{signal.source_class} source")
    if HEDGE.search(signal.text):
        notes.append("unconfirmed rumor wording")
    if "embedded_instructions" in signal.flags:
        notes.append("contained instructions aimed at AI systems, which were ignored")
    return reason + (f" Also: {'; '.join(notes)}." if notes else "")


def running_weeks(signal: Signal) -> int | None:
    if signal.first_seen and signal.last_seen:
        return max(0, (signal.last_seen - signal.first_seen).days // 7)
    return None


# ---- Grouping -----------------------------------------------------------------

SAME_EVENT_WINDOW = timedelta(hours=72)


def same_event(a: Signal, b: Signal) -> bool:
    if a.competitor != b.competitor or a.competitor == "Unknown":
        return False
    if a.when and b.when and abs(a.when - b.when) > SAME_EVENT_WINDOW:
        return False
    pa, pb = prices(a.text), prices(b.text)
    if pa and pb and not (pa & pb):
        return False  # different numbers: a conflict, not the same report
    shared = content_words(a.text) & content_words(b.text)
    distinctive = shared - GENERIC
    return bool(pa & pb) or (len(shared) >= 2 and bool(distinctive))


def group_signals(signals: list[Signal]) -> list[list[Signal]]:
    parent = list(range(len(signals)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(signals)):
        for j in range(i + 1, len(signals)):
            if same_event(signals[i], signals[j]):
                parent[find(j)] = find(i)
    groups: dict[int, list[Signal]] = {}
    for i, signal in enumerate(signals):
        groups.setdefault(find(i), []).append(signal)
    return list(groups.values())


# ---- Trust --------------------------------------------------------------------

BASE_TRUST = {
    "observed": 0.95,  # captured by our own collector, with a screenshot
    "official": 0.9,
    "advertiser": 0.7,
    "press": 0.7,
    "media": 0.6,
    "unknown": 0.5,
    "community": 0.35,
    "guest": 0.35,
    "sponsored": 0.25,
    "anonymous": 0.2,
}
THRESHOLD = 0.5


@dataclass
class Verdict:
    confidence: float
    reasons: list[str] = field(default_factory=list)  # why confidence went down


def assess(group: list[Signal], official_prices: dict[str, set[str]]) -> Verdict:
    classes = [s.source_class for s in group]
    best = max(group, key=lambda s: BASE_TRUST.get(s.source_class, 0.5))
    score = BASE_TRUST.get(best.source_class, 0.5)
    reasons: list[str] = []

    independent = {s.domain or s.source_class for s in group}
    if len(independent) > 1:
        score += min(0.1 * (len(independent) - 1), 0.15)

    has_official = "official" in classes or "observed" in classes
    # The competitor's own ad is its own word: a different price there is a promo, not a lie.
    own_word = has_official or "advertiser" in classes
    if not has_official and any(HYPE.search(s.text) for s in group):
        score -= 0.2
        reasons.append("absolute marketing claim")
    # Official pages say "prices may change"; hedging only matters from third parties.
    if not has_official and all(HEDGE.search(s.text) for s in group):
        score -= 0.25
        reasons.append("hedged, unconfirmed wording")
    if not own_word:
        known = official_prices.get(best.competitor)
        claimed = set().union(*(prices(s.text) for s in group))
        if known and claimed and not (known & claimed):
            score -= 0.3
            reasons.append("contradicts the official pricing source this week")
    if any("no_date" in s.flags for s in group):
        score -= 0.1
        reasons.append("no date")
    if not any(s.url for s in group):
        score = min(score, 0.4)
        reasons.append("no link to check (no link, no number)")
    if any("embedded_instructions" in s.flags for s in group):
        score = min(score, 0.2)
        reasons.append("contains instructions aimed at AI systems")
    if best.source_class in ("sponsored", "anonymous", "guest", "community") and not has_official:
        reasons.insert(0, f"{best.source_class} source")

    return Verdict(confidence=round(max(0.0, min(score, 0.95)), 2), reasons=reasons)
