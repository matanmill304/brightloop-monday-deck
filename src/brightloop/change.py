"""What changed: read a change stated inside one signal, or compare two snapshots of a page.

Maya's deck is "what's different from last week", so a signal that only states the current
price ("Pro: $25/month") is a fact, not a change. A change is either:
  A. stated in the text ("was $20", "from $20 to $25", "introduces a Starter tier"), or
  B. found by comparing two snapshots of the same official page.
"""

from __future__ import annotations

import difflib
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
    r"|drop(s|ped)?|slash(es|ed)?|halv(e|es|ed)|doubl(e|es|ed)|tripl(e|es|ed)|bump(s|ed)?"
    r"|nudg(e|es|ed)|up by|goes up|went up|goes down|went down)\b",
    re.IGNORECASE,
)
PLAN_ADDED = re.compile(
    rf"\b(introduc\w*|add(s|ed)?|launch(es|ed)?|unveil\w*|roll(s|ed)? out|new)\b[^.]{{0,40}}"
    rf"\b((?<!all )(?<!every )(?<!each )(plans?|tiers?)|({PLAN_NAMES}) (plan|tier))\b",
    re.IGNORECASE,
)
PLAN_REMOVED = re.compile(
    r"\b(remov\w*|drop(s|ped)?|discontinu\w*|sunset\w*|retir\w*|kill(s|ed)?|eliminat\w*"
    r"|no longer (offers?|available))\b[^.]{0,40}\b(plans?|tiers?)\b"
    r"|\b(plans?|tiers?)\b[^.]{0,30}\b(is|are) (gone|discontinued|retired|no longer)\b"
    r"|\b(plans?|tiers?)\s+(\([^)]*\)\s+)?(removed|discontinued|retired|dropped)\b",
    re.IGNORECASE,
)
# The collector's own sentences (collect/events.py), read back exactly.
OUR_EDIT = re.compile(r'^Changed on the (pricing page|homepage): "(.+)" → "(.+)"', re.IGNORECASE)
OUR_LINE = re.compile(r'^(New on|No longer on) the (pricing page|homepage): "(.+)"', re.IGNORECASE)
OUR_HEADLINE = re.compile(r'^Headline changed from "(.*)" to "(.*)"', re.IGNORECASE)
OUR_SUBHEAD = re.compile(r'^Subheadline changed from "(.*)" to "(.*)"', re.IGNORECASE)
OUR_BUTTONS = re.compile(r"^Top-of-page buttons changed: (.+?)\.?$", re.IGNORECASE)
RENAMED = re.compile(r"\brenam\w*\b", re.IGNORECASE)
LIMITS = re.compile(
    r"\b(credits?|limits?|quotas?|requests?|messages?|usage|tokens?|seats?|minutes|builds?)\b",
    re.IGNORECASE,
)
# Packaging: a feature moves to or from a named plan, or becomes free ("now included in Core",
# "moved to Pro", "now free for all users"). "Live for every plan" is a launch, not packaging.
AVAILABILITY = re.compile(
    rf"\b(now|available|included|comes with|moved|unlocked)\b[^.]{{0,40}}"
    rf"\b(in|on|to|for|with|behind|from)\s+(the\s+)?(paid|{PLAN_NAMES})"
    rf"(\s*(,|and|or|&)\s*({PLAN_NAMES}))*\s+(plans?|tiers?|users|customers|subscribers)\b"
    r"|\bnow free\b",
    re.IGNORECASE,
)
GENERIC_CHANGE = re.compile(
    r"\b(now|no longer|changed?|changes|updated?|updates|replaced|switch(es|ed)?|new|introduc\w*"
    r"|launch(es|ed)?|moved|will (be|cost|go|become|change)|starting|effective|rewrit\w*|swapped|went from|instead of)\b",
    re.IGNORECASE,
)
QUOTED_PAIR = re.compile(r"""from\s+["'“‘](.+?)["'”’]\s+to\s+["'“‘](.+?)["'”’]""", re.IGNORECASE)


# Wording that says the same thing without our usual verbs (all read on prepare()d text).
PREV = (
    r"(?:was|previously|formerly|used to be|down from|up from|instead of|compared to|rather than"
    r"|(?:capture|card|toggle|page|column|banner|version)\b[^.]{0,30}?\b(?:said|read|showed|listed))"
)
# "rather than 20%", "the same card said 40", "prior capture showed $10": the old value.
PREVIOUS_ANY = re.compile(
    rf"\b{PREV}\s+['\"‘“]?(?:save\s+)?({AMOUNT}|\d[\d,.]*\s?[kmb%]?)(?![\w$])", re.IGNORECASE
)
# "limit 3 → 10", "150K → 300K", "save 20% → 15%": numbers that changed, no currency.
VALUE_ARROW = re.compile(
    r"(\d[\d,.]*\s?[kmb%]?)\s*(?:→|->|=>)\s*(\d[\d,.]*\s?[kmb%]?)(?![\w$])", re.IGNORECASE
)
# "10% lighter", "20% cheaper": a price change stated as a percentage.
PERCENT_MOVE = re.compile(
    r"\b(\d[\d.]*)\s?%\s+(cheaper|lighter|less|lower|off|more|pricier|higher|dearer)\b",
    re.IGNORECASE,
)
# "Pro +$5": a price change stated as a difference.
DELTA = re.compile(rf"(?<![\w$€£])([+−])\s?({AMOUNT})")
LIMIT_WORDS = (
    r"(?:credits?|tokens?|messages?|allowance|cap|ceiling|limits?|quotas?|requests?|builds?"
    r"|projects?|repls?|minutes|hours)"
)
# "allowance more than tripled", "the ceiling is gone", "tokens carry into the next month".
LIMIT_MOVE = re.compile(
    rf"\b{LIMIT_WORDS}\b.{{0,80}}?\b(\d+(\.\d+)?x|tripled|doubled|halved|quadrupled|\d times"
    r"|gone|lifted|removed|scrapped|unlimited|carr(y|ies) (over|into)|roll(s|ed)? over)(?!\w)"
    rf"|\b(\d+(\.\d+)?x|tripled|doubled|halved|quadrupled|double|triple)\b.{{0,60}}?\b{LIMIT_WORDS}\b"
    r"|\brollover\b",
    re.IGNORECASE,
)
# Something became free: "private projects are on the house".
FREE_NOW = re.compile(
    r"\b(on the house|at no (extra )?cost|free of charge|no longer (a )?(pro|paid)\b)",
    re.IGNORECASE,
)
PLAN_HELLO = re.compile(
    rf"\b(say hello to|meet|welcome|introducing)\s+(the\s+)?({PLAN_NAMES})\b", re.IGNORECASE
)
PLAN_CARD = re.compile(
    r"\b((new|third|fourth|fifth|extra) (card|column|plan)|not on the page (in|on|at) last)\b",
    re.IGNORECASE,
)
PLAN_GONE = re.compile(
    rf"\b({PLAN_NAMES})\b\s+(fold(s|ed)? into|merg\w* into|won't be around|will not be around"
    r"|is going away|goes away|is ending|will end|is being retired|is retiring|is sunsetting)",
    re.IGNORECASE,
)
# A text that says nothing changed: "No price change", "Unchanged from last week".
NO_CHANGE = re.compile(
    r"\b(no price change|no changes?|unchanged|nothing changes|nothing has changed|untouched"
    r"|stays the same|remains the same|still (at )?[$€£]\s?\d)",
    re.IGNORECASE,
)
# Money about the company, not about what customers pay.
FINANCE = re.compile(
    r"\b(valuation|valued at|funding|series [a-h]\b|seed round|investors?|ipo|revenue|annual recurring"
    r"|acquir\w*|acquisition|round)\b|[$€£]\s?\d[\d,.]*\s?(m|b|bn|million|billion)\b",
    re.IGNORECASE,
)
NUMBER_WORDS = {
    w: n
    for n, w in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
        ]
    )
}
TENS = {
    w: 10 * n
    for n, w in enumerate(
        ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    )
    if n > 1
}
NUMBER_WORD = re.compile(
    rf"\b(?:({'|'.join(TENS)})(?:[- ]({'|'.join(list(NUMBER_WORDS)[1:10])}))?|({'|'.join(NUMBER_WORDS)}))\b",
    re.IGNORECASE,
)


def prepare(text: str) -> str:
    """The same text with numbers and currencies in one form: "forty" -> 40, "20 USD" -> $20,
    "thirty bucks" -> $30, "~~$20~~ $25" -> "$20 → $25", "p/m" -> "/month"."""

    def number(m: re.Match) -> str:
        if m.group(3):
            return str(NUMBER_WORDS[m.group(3).lower()])
        return str(
            TENS[m.group(1).lower()] + (NUMBER_WORDS[m.group(2).lower()] if m.group(2) else 0)
        )

    text = re.sub(r"~~\s*([^~]+?)\s*~~\s*", r"\1 → ", text)
    text = NUMBER_WORD.sub(number, text)
    text = re.sub(r"\b(\d[\d,.]*)\s?(?:bucks|dollars|usd)\b", r"$\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\busd\s?(\d)", r"$\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d[\d,.]*)\s?eur\b", r"€\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\beur\s?(\d)", r"€\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d[\d,.]*)\s?gbp\b", r"£\1", text, flags=re.IGNORECASE)
    return re.sub(r"\s?\bp/m\b", "/month", text, flags=re.IGNORECASE)


def sentence_at(text: str, pos: int) -> str:
    """The sentence around a position: in a long page, the plan named next to the change."""
    start = max(
        text.rfind(". ", 0, pos), text.rfind("\n", 0, pos), text.rfind(": ", 0, max(0, pos - 80))
    )
    end = min(
        (i for i in (text.find(". ", pos), text.find("\n", pos)) if i != -1), default=len(text)
    )
    return text[start + 1 : end + 1]


def plan_before_amount(text: str) -> str | None:
    """The plan named closest before the first amount: "between Pro and Business: Teams, $30"."""
    m = re.search(AMOUNT, text)
    names = re.findall(rf"\b({PLAN_NAMES})\b", text[: m.start()] if m else text, re.IGNORECASE)
    return names[-1].title() if names else plan_name(text)


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
    if m := OUR_EDIT.match(text):
        return Change("line_changed", m.group(2), m.group(3), m.group(0), plan_name(m.group(3)))
    if m := OUR_LINE.match(text):
        quote = m.group(3)
        if m.group(1).lower() == "new on":
            return Change("line_added", new=quote, evidence=m.group(0), plan=plan_name(quote))
        return Change("line_removed", old=quote, evidence=m.group(0), plan=plan_name(quote))
    if m := OUR_HEADLINE.match(text):
        return Change("headline", m.group(1), m.group(2), m.group(0))
    if m := OUR_SUBHEAD.match(text):
        return Change("subheadline", m.group(1), m.group(2), m.group(0))
    if m := OUR_BUTTONS.match(text):
        return Change("buttons", new=m.group(1), evidence=m.group(0))
    # Domain names are not words: "Bolt.new" must not read as "new".
    text = prepare(DOMAIN_LIKE.sub(" ", text))
    # Money is not a price: "raises $330M at a $6.6B valuation" is company news.
    if "company finance" in pricing_cues(text):
        return None
    if m := PREVIOUSLY.search(text):
        old = clean(m.group(2))
        here = sentence_at(text, m.start())
        others = [clean(a.group(0)) for a in PRICE_WITH_UNIT_RE.finditer(here)]
        others += [clean(a.group(0)) for a in PRICE_WITH_UNIT_RE.finditer(text)]
        new = next((a for a in others if a and a != old and not old.startswith(a)), None)
        return Change("price", old, new, m.group(0), plan=plan_name(here) or plan_name(text))
    if (m := PREVIOUS_ANY.search(text)) and (change := previous_value(text, m)):
        return change
    if m := NUMBER_PREVIOUSLY.search(text):
        kind = "limits" if LIMITS.search(text) else "other"
        return Change(kind, old=m.group(2), evidence=m.group(0), plan=plan_name(text))
    m = FROM_TO.search(text)
    if m and not re.search(r"\bup to\s*$", text[: m.start()], re.IGNORECASE):
        if number(m.group(1)) == number(m.group(2)):
            return None  # "$25 → $25": the same price on both sides is not a change
        here = sentence_at(text, m.start())
        plan = plan_name(here) or plan_name(text)
        return Change("price", clean(m.group(1)), clean(m.group(2)), m.group(0), plan)
    if (m := VALUE_ARROW.search(text)) and number(m.group(1)) != number(m.group(2)):
        kind = (
            "limits"
            if LIMITS.search(text) or re.search(LIMIT_WORDS, text, re.IGNORECASE)
            else "price"
        )
        return Change(kind, clean(m.group(1)), clean(m.group(2)), m.group(0), plan_name(text))
    if m := QUOTED_PAIR.search(text):
        return Change("wording", m.group(1), m.group(2), m.group(0))
    if FINANCE.search(text):
        return None  # company money, not a customer price ("$200M round", "$6.6B valuation")
    if m := LIMIT_MOVE.search(text):
        return Change("limits", evidence=m.group(0), plan=plan_name(text))
    if NO_CHANGE.search(text):
        return None  # "No price change", "Unchanged from last week's capture"
    if m := PLAN_HELLO.search(text):
        return Change(
            "plan_added", new=first_amount(text), evidence=m.group(0), plan=m.group(3).title()
        )
    if m := PLAN_GONE.search(text):
        return Change("plan_removed", evidence=m.group(0), plan=m.group(1).title())
    if m := PLAN_CARD.search(text):
        plan = plan_before_amount(text)
        return Change("plan_added", new=first_amount(text), evidence=m.group(0), plan=plan)
    if m := PERCENT_MOVE.search(text):
        return Change("price", new=first_amount(text), evidence=m.group(0), plan=plan_name(text))
    if m := DELTA.search(text):
        return Change(
            "price", new=m.group(0).replace(" ", ""), evidence=m.group(0), plan=plan_name(text)
        )
    if m := FREE_NOW.search(text):
        return Change("availability", evidence=m.group(0), plan=plan_name(text))
    if m := PLAN_REMOVED.search(text):
        return Change("plan_removed", evidence=m.group(0), plan=plan_name(text))
    if m := RENAMED.search(text):
        return Change("renamed", evidence=m.group(0))
    if m := PLAN_ADDED.search(text):
        return Change(
            "plan_added", new=first_amount(text), evidence=m.group(0), plan=plan_name(text)
        )
    if (m := PRICE_VERB.search(text)) and LIMITS.search(text) and not re.search(AMOUNT, text):
        return Change("limits", evidence=m.group(0))
    if m := PRICE_VERB.search(text):
        return Change("price", new=first_amount(text), evidence=m.group(0), plan=plan_name(text))
    if m := AVAILABILITY.search(text):
        return Change("availability", evidence=m.group(0))
    if (m := GENERIC_CHANGE.search(text)) and (amount := first_amount(text)):
        # "Core plan now $25/month": a new price, the old one isn't stated
        return Change("price", new=amount, evidence=m.group(0), plan=plan_name(text))
    if m := GENERIC_CHANGE.search(text):
        return Change("other", new=first_amount(text), evidence=m.group(0))
    return None


def previous_value(text: str, m: re.Match) -> Change | None:
    """The old value after a marker ("rather than 20%", "said 40"), and the new value of the
    same kind elsewhere in the text: a %, money, or a plain number with a limit word."""
    old = clean(m.group(1))
    rest = text[: m.start()] + " " + text[m.end() :]
    if old.endswith("%"):
        new = next(
            (v for v in re.findall(r"\d[\d,.]*\s?%", rest) if number(v) != number(old)), None
        )
        return Change("price", old, clean(new), m.group(0), plan_name(text)) if new else None
    money = [
        a.group(0) for a in PRICE_WITH_UNIT_RE.finditer(rest) if number(a.group(0)) != number(old)
    ]
    if money:
        if not re.match(r"[$€£]", old):
            old = money[0][0] + old  # "said 40" next to "$30 a seat": forty dollars
        kind = "limits" if re.search(r"credits?|allowance", text, re.IGNORECASE) else "price"
        return Change(kind, old, clean(money[0]), m.group(0), plan_name(text))
    if re.search(LIMIT_WORDS, text, re.IGNORECASE):
        counts = [v for v in re.findall(r"\d[\d,.]*\s?[kmb]?", rest) if number(v) != number(old)]
        if counts:
            return Change("limits", old, clean(counts[0]), m.group(0), plan_name(text))
    return None


# B: compare two snapshots of the same page.


@dataclass
class PageState:
    prices: dict[str, str] = field(default_factory=dict)  # plan -> price, when readable
    amounts: set[str] = field(default_factory=set)
    blocks: list[str] = field(default_factory=list)  # visible text lines, normalized
    billing: str | None = None  # monthly | yearly: which view of a toggle page was captured
    lines: list[str] = field(default_factory=list)  # whole lines with a price, a % or a limit
    error_page: bool = False  # the archive's own error page, not the competitor's page


BILLED_YEARLY = re.compile(
    r"\bbilled (annually|yearly)\b|\bper year\b|/\s?(year|yr)\b", re.IGNORECASE
)
BILLED_MONTHLY = re.compile(r"\bbilled monthly\b", re.IGNORECASE)


def billing_view(text: str) -> str | None:
    yearly, monthly = bool(BILLED_YEARLY.search(text)), bool(BILLED_MONTHLY.search(text))
    if yearly == monthly:
        return None  # no toggle, or both shown: nothing to tell apart
    return "yearly" if yearly else "monthly"


PLAN_PRICE = re.compile(rf"\b({PLAN_NAMES})\b[^$€£.\n]{{0,25}}?({AMOUNT}{UNIT})", re.IGNORECASE)
NOISE_LINE = re.compile(
    r"(cookie|privacy|©|copyright|all rights reserved|\b\d{1,2}:\d{2}\b|\b(19|20)\d{2}\b"
    r"|^\W*$|^\d[\d,.]*\+?$"
    # navigation and page chrome, not the competitor's message
    r"|opens in (a )?new (window|tab)|^(log ?in|sign ?in|sign ?up|get started|book a demo"
    r"|contact (sales|us)|skip to (main )?content|menu|toggle (menu|navigation)|close)$)",
    re.IGNORECASE,
)
# Lines of one or two words with no amount are menu items and buttons; ignored when comparing.
SHORT_LINE = re.compile(r"^\W*\w+(\W+\w+)?\W*$")
# A line about what a customer pays or gets: an amount, a percentage, or a usage limit.
PRICE_OR_LIMIT = re.compile(
    rf"{AMOUNT}|\b\d[\d,.]*\s?%|\b\d[\d,.]*\s?[kmb]?\s?(credits?|tokens?|messages?|projects?"
    r"|seats?|requests?|hours?|minutes?|domains?|builds?)\b",
    re.IGNORECASE,
)
# The Wayback Machine's own pages, saved instead of the competitor's page.
ARCHIVE_ERROR = re.compile(
    r"temporarily offline|internet archive services|wayback machine has not archived"
    r"|this snapshot cannot be displayed|got an http \d{3} response at crawl time",
    re.IGNORECASE,
)


PLAN_LINE = re.compile(rf"(?i)({PLAN_NAMES})( plan)?")
UNIT_LINE = re.compile(r"(?i)/ ?(mo|month|year|yr|user|seat|member)(/(mo|month))?")
BARE_NUMBER = re.compile(r"\d{1,4}(\.\d{2})?")


def page_state(text: str) -> PageState:
    prices = {}
    for m in PLAN_PRICE.finditer(text):
        prices.setdefault(m.group(1).title(), clean(m.group(2)))
    # Captured pages are line-based: a line that is just a plan name, its price a few lines below.
    # Some pages draw the currency sign as an image (Lovable: "Pro … 25 / month"): a bare number
    # under a plan name is its price, in the page's currency (dollars when the page shows none).
    sign = re.search(r"[$€£]", text)
    currency = sign.group(0) if sign else "$"
    lines = [line.strip() for line in text.splitlines()]
    for i, line in enumerate(lines):
        if not PLAN_LINE.fullmatch(line):
            continue
        for below in lines[i + 1 : i + 5]:
            if PLAN_LINE.fullmatch(below):
                break  # the next plan started before a price showed up
            amount = re.search(AMOUNT, below)
            bare = BARE_NUMBER.fullmatch(below)
            if amount or bare:
                unit = next((u for u in lines[i + 1 : i + 6] if UNIT_LINE.fullmatch(u)), "")
                value = amount.group(0) if amount else f"{currency}{below}"
                prices.setdefault(line.title(), clean(f"{value}{unit}"))
                break
    amounts = {clean(a) for a in re.findall(AMOUNT, text)}
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    blocks = [
        norm_line(line)
        for line in sentences
        if line.strip()
        and not NOISE_LINE.search(line.strip())
        and not (SHORT_LINE.fullmatch(line.strip()) and not re.search(AMOUNT, line))
    ]
    priced = []
    for line in lines:
        is_priced = len(line.split()) >= 3 and PRICE_OR_LIMIT.search(line)
        if is_priced and not NOISE_LINE.search(line) and line not in priced:
            priced.append(line)
    return PageState(
        prices=prices,
        amounts=amounts,
        blocks=[b for b in blocks if b],
        billing=billing_view(text),
        lines=priced,
        error_page=bool(ARCHIVE_ERROR.search(text[:1500])),
    )


def compare(
    old: PageState, new: PageState, same_method: bool = True, lines: bool = True
) -> list[Change]:
    """What goes on Maya's slide, compared like with like. Nothing else on the page counts.

    1. Plan prices, plan by plan, only when both captures show the same billing view
       (a yearly view against a monthly one is not a price change).
    2. Plans added or removed (when both captures show plans at all).
    3. Whole lines that mention a price, a percentage or a limit, e.g. a footnote
       "Bolt Lite ($9/month, invite only during the research preview)". Only between two
       captures made the same way: an archived render differs from a live one for reasons
       that aren't changes.
    Menus, FAQ prose and testimonials are not compared.
    """
    changes: list[Change] = []
    if old.billing == new.billing:
        for plan in sorted(old.prices.keys() & new.prices.keys()):
            if number(old.prices[plan]) != number(new.prices[plan]):
                changes.append(Change("price", old.prices[plan], new.prices[plan], plan=plan))
        if old.prices and new.prices:
            for plan in sorted(new.prices.keys() - old.prices.keys()):
                changes.append(Change("plan_added", new=new.prices[plan], plan=plan))
            for plan in sorted(old.prices.keys() - new.prices.keys()):
                changes.append(Change("plan_removed", old=old.prices[plan], plan=plan))
    if not (same_method and lines):
        return changes
    # A plan's price line already reported as a price change is not reported twice.
    covered = {number(v) for c in changes for v in (c.old, c.new) if v}
    added = [x for x in new.lines if x not in old.lines and not only_covered(x, covered)]
    removed = [x for x in old.lines if x not in new.lines and not only_covered(x, covered)]
    # A line that was edited ("most powerful" -> "more powerful") is one change, not two.
    pairs = sorted(((similarity(r, a), r, a) for r in removed for a in added), key=lambda p: -p[0])
    for score, r, a in pairs:
        if score >= SAME_LINE and r in removed and a in added:
            changes.append(Change("line_changed", r, a))
            removed.remove(r)
            added.remove(a)
    changes += [Change("line_added", new=x) for x in added]
    changes += [Change("line_removed", old=x) for x in removed]
    return changes


SAME_LINE = 0.6  # this similar: the same line, edited


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def only_covered(line: str, covered: set[float | None]) -> bool:
    found = {number(a) for a in re.findall(AMOUNT, line)}
    return bool(found) and found <= covered


def describe(change: Change) -> str:
    plan = f"{change.plan} " if change.plan else ""
    if change.kind == "price" and change.old and change.new:
        return (
            f"{change.plan}: {change.old} → {change.new}"
            if change.plan
            else f"{change.old} → {change.new}"
        )
    if change.kind == "plan_added":
        return f"new plan: {plan}{change.new or ''}".strip()
    if change.kind == "plan_removed":
        return f"plan removed: {plan}{change.old or ''}".strip()
    if change.kind == "headline":
        return f'headline: "{change.old}" → "{change.new}"'
    if change.kind == "subheadline":
        return f'subheadline: "{change.old}" → "{change.new}"'
    if change.kind == "buttons":
        return f"top-of-page buttons: {change.new}"
    if change.kind == "line_changed":
        return f'"{change.old}" → "{change.new}"'
    if change.kind == "line_added" and change.new:
        return f'new on the page: "{change.new}"'
    if change.kind == "line_removed" and change.old:
        return f'no longer on the page: "{change.old}"'
    if change.old and change.new:
        return (
            f"{change.plan}: {change.old} → {change.new}"
            if change.plan
            else f"{change.old} → {change.new}"
        )
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
    """Not a real capture: the archive's own error page, a page whose plans can no longer be
    read (prices drawn by a script the archive lacks), or a page that lost all its prices and
    almost all its text."""
    if new.error_page or (old.prices and not new.prices):
        return True
    return bool(old.amounts) and not new.amounts and len(new.blocks) <= 2
