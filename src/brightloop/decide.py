"""Text cues: what a text talks about. Rule-based, so it runs with no keys.

Used where the decision tree (select.py) still needs to read meaning: is an official
announcement about pricing, and is an amount company finance rather than a price.
No model answers them instead: the same rules run live and on the reviewers' files (decision D2).
"""

from __future__ import annotations

import re

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
# Packaging: what a specific plan includes, or something becoming free. "Live for every plan"
# and "available to all users" describe a launch: nothing moved between tiers.
NAMED_PLAN = r"(the )?(free|pro|team|teams|business|enterprise|starter|hobby|core|paid|plus|max)"
PACKAGING = re.compile(
    rf"\b((available|included) (on|to|for|in|with) {NAMED_PLAN}"
    r"|now free|moved (to|behind)|subscriptions? (with|for))\b",
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


def prices(text: str) -> set[str]:
    return {re.sub(r"\s", "", m.group(0)).lower() for m in PRICE.finditer(text)}


def content_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)?", text.lower())
    return {w for w in words if w.isdigit() or (w not in STOPWORDS and len(w) > 1)}


def running_weeks(signal: Signal) -> int | None:
    if signal.first_seen and signal.last_seen:
        return max(0, (signal.last_seen - signal.first_seen).days // 7)
    return None
