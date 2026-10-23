"""The decision tree for Maya: which signals become items in her Monday deck.

Maya: the competitor's own pricing page is "the source of truth"; press or Reddit
"wouldn't make the deck without me verifying it against the actual page"; on the
homepage she wants "what's different from last week's screenshot".

Every signal goes down these branches in order; the first branch that decides, decides:

  1. Unsafe or unusable  -> skipped (embedded instructions, name collision, no competitor, no text)
  2. Outside the week    -> after it: skipped. Before it: kept only as a baseline snapshot
  3. Third party         -> skipped: "verify on the official page"
  4. Official page (pricing page or homepage):
       states a change           -> item (0.9)
       states only the current   -> compared with another snapshot of the same page:
                                    different -> item (0.95); same or nothing to compare -> skipped
  5. Official elsewhere (blog, changelog, own X account, own ad):
       a pricing/packaging change -> item (0.7) with "check the official page"
       anything else              -> skipped, routed to Noa (launch) or Daniel (ad)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache

from brightloop.change import (
    FINANCE,
    NO_CHANGE,
    PLAN_NAMES,
    Change,
    all_price_changes,
    compare,
    looks_like_failed_capture,
    number,
    page_state,
    stated_change,
)
from brightloop.competitors import COMPETITORS, name_roots
from brightloop.decide import (
    HEDGE,
    HYPE,
    content_words,
    is_pricing_related,
    prices,
    running_weeks,
)
from brightloop.normalize import UTC, Signal
from brightloop.window import Week

CONF_COMPARED = 0.95  # we compared two snapshots of the official page ourselves
CONF_PAGE = 0.9  # the official page states the change
CONF_ANNOUNCED = 0.7  # the competitor said it elsewhere; not yet seen on the page
SAME_EVENT = timedelta(hours=72)

PRICING_KINDS = {"price", "plan_added", "plan_removed", "renamed", "limits", "availability"}


@dataclass
class Candidate:
    """One future item: the signals it's built from and what we know about the change."""

    track: str  # compared | page | announced
    signals: list[Signal]
    changes: list[Change]
    confidence: float
    caveats: list[str] = field(default_factory=list)
    corroboration: list[Signal] = field(default_factory=list)  # same change, other sources

    @property
    def lead(self) -> Signal:
        return self.signals[-1]


@dataclass
class Selection:
    candidates: list[Candidate] = field(default_factory=list)
    skipped: list[tuple[Signal, str]] = field(default_factory=list)


def select(signals: list[Signal], week: Week | None) -> Selection:
    result = Selection()
    current: list[Signal] = []
    baselines: list[Signal] = []

    for s in signals:
        reason = unusable(s)
        if reason:
            result.skipped.append((s, reason))
            continue
        timing = place_in_week(s, week)
        if timing == "after":
            result.skipped.append((s, f"Dated after the reporting week ({week.label})."))
        elif timing == "before":
            baselines.append(s)
        else:
            current.append(s)

    page_states: list[Signal] = []
    third_party: list[Signal] = []
    for s in current:
        if not s.official:
            third_party.append(s)
        elif s.on_page:
            change = None if s.is_snapshot else stated_change(s.text)
            if change:
                result.candidates.append(page_candidate(s, change))
            else:
                page_states.append(s)
        else:
            decide_announcement(s, result)

    used_baselines = compare_snapshots(page_states, baselines, result)
    for s in baselines:
        if s.id not in used_baselines:
            result.skipped.append((s, older_reason(s, week)))

    result.candidates = merge_same_events(result.candidates)
    for s in third_party:
        match = next(
            (c for c in result.candidates if any(same_event(s, o) for o in c.signals)), None
        )
        if match:
            match.corroboration.append(s)  # the same change, reported by someone else
        else:
            twin = next((o for o, _ in result.skipped if o.official and same_event(s, o)), None)
            same = f"Same event as {twin.id} ({twin.competitor}'s own source). " if twin else ""
            result.skipped.append((s, same + third_party_reason(s)))
    return result


# ---- 1. Unsafe or unusable ---------------------------------------------------------


def unusable(s: Signal) -> str | None:
    if "embedded_instructions" in s.flags:
        return "Contains instructions aimed at AI systems; ignored and not used." + notes(s)
    if "name_collision_domain" in s.flags:
        return f"A different company named like {s.competitor}: {s.domain} is not its site."
    if "name_collision_text" in s.flags:
        return f"About something else that shares the name {s.competitor}, not the competitor."
    if s.competitor == "Unknown":
        return "No competitor named, so it can't go on a competitor slide."
    if "no_text" in s.flags:
        return "No text to evaluate."
    return None


# ---- 2. The reporting week --------------------------------------------------------


def place_in_week(s: Signal, week: Week | None) -> str:
    if week is None:
        return "in"
    if s.first_seen or s.last_seen:  # ads: active at any point during the week
        first = s.first_seen or s.ts or s.last_seen
        last = s.last_seen or s.ts or s.first_seen
        if first >= week.end:
            return "after"
        return "before" if last < week.start else "in"
    if s.ts is None:
        return "in"
    if s.ts >= week.end:
        return "after"
    return "before" if s.ts < week.start else "in"


def older_reason(s: Signal, week: Week | None) -> str:
    label = week.label if week else "this week"
    if s.on_page and (s.is_snapshot or stated_change(s.text) is None):
        return (
            f"Older than the reporting week ({label}) and no newer snapshot of the same page "
            "to compare it with."
        )
    return f"Happened before the reporting week ({label})."


# ---- 4. The official pages ----------------------------------------------------------


def page_candidate(s: Signal, change: Change) -> Candidate:
    caveats = []
    confidence = CONF_PAGE
    if change.kind == "other":
        confidence -= 0.1
        caveats.append("the page says something changed but not exactly what")
    elif change.kind == "price" and not change.old:
        confidence -= 0.05
        caveats.append("previous price not stated: compare with last week's screenshot")
    changes = all_price_changes(s.text) if change.kind == "price" and change.old else []
    return with_penalties(Candidate("page", [s], changes or [change], confidence, caveats))


def compare_snapshots(
    states: list[Signal], baselines: list[Signal], result: Selection
) -> set[object]:
    """Pair snapshots of the same page; return the ids of baselines that were used."""
    used: set[object] = set()
    pages: dict[tuple[str, str], list[Signal]] = {}
    for s in states:
        pages.setdefault(page_key(s), []).append(s)
    old_pages: dict[tuple[str, str], list[Signal]] = {}
    for s in baselines:
        if s.on_page and (s.is_snapshot or stated_change(s.text) is None):
            old_pages.setdefault(page_key(s), []).append(s)

    for key, snaps in pages.items():
        snaps.sort(key=when_key)
        before = sorted(old_pages.get(key, []), key=when_key)
        chain = ([before[-1]] if before else []) + snaps
        if len(chain) < 2:
            result.skipped.append(
                (snaps[0], "Current state only, not a change: no earlier snapshot of this page.")
            )
            continue
        if before:
            used.add(before[-1].id)
        old_state, new_state = page_state(chain[0].text), page_state(chain[-1].text)
        if looks_like_failed_capture(old_state, new_state):
            result.skipped.extend(
                (
                    s,
                    (
                        "The latest snapshot lost all prices and almost all text: it looks like a "
                        "failed capture, not a change. Check the page."
                    ),
                )
                for s in chain
            )
            continue
        same_method = capture_method(chain[0]) == capture_method(chain[-1])
        lines = all(s.is_snapshot for s in chain)  # short statements: prices only
        changes = compare(old_state, new_state, same_method, lines)
        if not lines and key[1] == "home":
            # Two short statements about a homepage: compare whole sentences, never fragments.
            before, after = sentences(chain[0].text), sentences(chain[-1].text)
            added = [x for x in after if x not in before]
            removed = [x for x in before if x not in after]
            if added or removed:
                changes.append(
                    Change("wording", "; ".join(removed) or None, "; ".join(added) or None)
                )
        if changes:
            result.candidates.append(
                with_penalties(
                    Candidate("compared", chain, changes, CONF_COMPARED, homepage_caveat(key))
                )
            )
        else:
            first = chain[0]
            for s in chain:
                result.skipped.append(
                    (s, f"Same as the snapshot `{first.id}` of this page: nothing changed.")
                    if s is not first
                    else (s, "Snapshot of this page; the later snapshot shows no change.")
                )
    return used


def sentences(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", text) if x.strip()]


def homepage_caveat(key: tuple[str, str]) -> list[str]:
    if key[1] != "home":
        return []
    return ["homepages carry rotating content (testimonials, carousels): check the screenshots"]


def when_key(s: Signal) -> datetime:
    return s.when or EPOCH


EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def page_key(s: Signal) -> tuple[str, str]:
    return (s.competitor, s.page)


# ---- 5. Official, but not the page --------------------------------------------------


def decide_announcement(s: Signal, result: Selection) -> None:
    change = stated_change(s.text)
    pricing = is_pricing_related(s) or (change is not None and change.kind in PRICING_KINDS)
    is_ad_offer = s.type == "ad" and bool(prices(s.text)) and bool(PROMO.search(s.text))
    if pricing and (change is not None or is_ad_offer):
        result.candidates.append(
            with_penalties(
                Candidate(
                    "announced",
                    [s],
                    [change or Change("price", new=None, evidence="ad offer")],
                    CONF_ANNOUNCED,
                    ["announced by the competitor, not yet confirmed on its pricing page"],
                )
            )
        )
        return
    if s.type == "ad":
        reason = "Ad creative with no pricing claim: Daniel's area (paid), not Maya's deck."
        if prices(s.text):
            reason = "Ad showing the current price, not a change: Daniel's area (paid)."
        weeks = running_weeks(s)
        if weeks is not None and weeks >= 8:
            reason += f" It has been running about {weeks} weeks, so worth passing to Daniel."
    elif FINANCE.search(s.text):
        reason = "Company news (funding, valuation, revenue): money, not a customer price."
    elif NO_CHANGE.search(s.text):
        reason = "Says nothing changed; Maya's deck tracks what changed."
    elif pricing:
        reason = "States the current price, not a change; Maya's deck tracks what changed."
    else:
        reason = "Feature launch with no pricing or packaging change: product's area; route to Noa."
    result.skipped.append((s, reason + notes(s)))


# ---- 3. Third parties ----------------------------------------------------------------


def third_party_reason(s: Signal) -> str:
    page = pricing_url(s.competitor)
    change = stated_change(s.text)
    about_pricing = is_pricing_related(s) or (change is not None and change.kind in PRICING_KINDS)
    if not about_pricing:
        return (
            f"Third-party news ({s.source_class} source) that isn't a pricing or packaging "
            "change." + notes(s)
        )
    where = f"; verify on {page}" if page else ""
    return f"Not from {s.competitor}'s own pages ({s.source_class} source){where}." + notes(s)


def pricing_url(competitor: str) -> str | None:
    info = COMPETITORS.get(competitor)
    return info["pricing_url"][0] if info else None


# ---- Shared helpers ---------------------------------------------------------------------


def with_penalties(c: Candidate) -> Candidate:
    if any("no_date" in s.flags for s in c.signals):
        c.confidence -= 0.1
        c.caveats.append("no date")
    if any("link_from_named_page" in s.flags for s in c.signals):
        c.caveats.append("the input named the page but gave no URL; linked to the official page")
    c.confidence = round(max(0.0, min(c.confidence, 0.95)), 2)
    return c


def merge_same_events(candidates: list[Candidate]) -> list[Candidate]:
    """One item per change: a page item absorbs announcements of the same change."""
    order = {"compared": 0, "page": 1, "announced": 2}
    merged: list[Candidate] = []
    for c in sorted(candidates, key=lambda c: order[c.track]):
        home = next((m for m in merged if mergeable(m, c)), None)
        if home is None:
            merged.append(c)
        else:
            home.signals[:0] = c.signals  # the first source found stays the lead
            home.changes.extend(c.changes)
            if c.track != "announced":
                home.confidence = max(home.confidence, c.confidence)
    return merged


def mergeable(kept: Candidate, new: Candidate) -> bool:
    """Announcements join the item of the same change; two different pages never merge."""
    if new.track != "announced" and kept.track != "announced" and kept.lead.page != new.lead.page:
        key = change_key(kept.lead)
        if not (key and key == change_key(new.lead)):
            return False  # two pages merge only when they state the same specific change
    if new.track == "compared" or kept.track == "compared" and new.track != "announced":
        return False  # a compared page is its own item; only announcements join it
    return any(same_event(a, b) for a in kept.signals for b in new.signals)


def capture_method(s: Signal) -> str:
    return str(s.raw.get("capture") or "input")


def same_event(a: Signal, b: Signal) -> bool:
    """The same change, possibly in other words.

    "Pro plan now costs $30 per month, up from $25" and "Lovable raises Pro plan to $30/month"
    are one event (same plan, same new price). "New on the page: Bolt Lite ($9/month…)" on
    Sep 30 and "No longer on the page: Bolt Lite ($9/month…)" on Oct 1 are two.
    """
    if a.competitor != b.competitor:
        return False
    if not close_in_time(a, b):
        return False
    key_a, key_b = change_key(a), change_key(b)
    if key_a or key_b:
        return key_a == key_b  # a specific change only matches the same specific change
    # Neither is that specific ("Agent 4 is live for every plan" / "Replit rolls out Agent 4
    # to all tiers"): the same event only if they share a distinctive name, not common words.
    return bool(anchors(a) & anchors(b))


def close_in_time(a: Signal, b: Signal) -> bool:
    """Within SAME_EVENT of each other. An ad's time is its whole run, not one day."""
    spans = []
    for s in (a, b):
        start = s.first_seen or s.ts or s.last_seen
        end = s.last_seen or s.ts or s.first_seen
        if start is None:
            return True  # no date: time can't rule it out
        spans.append((start, end))
    gap = max(spans[0][0], spans[1][0]) - min(spans[0][1], spans[1][1])
    return gap <= SAME_EVENT


# An ad that offers something ("for your first 3 months", "20% off", "now $35") vs one that
# shows a price ("from $25/mo").
PROMO = re.compile(
    r"\b(for (your|the) first|for \d+ months?|off|limited|this week|only|was|save|discount|introductory|promo"
    r"|deal|now|down from|up from)\b|%",
    re.IGNORECASE,
)


def change_key(s: Signal) -> tuple | None:
    """What exactly changed, comparable across wordings; None when it isn't that specific."""
    return text_key(s.text)


@lru_cache(maxsize=65536)
def text_key(text: str) -> tuple | None:
    """change_key for one text, computed once: grouping compares every pair of signals."""
    change = stated_change(text)
    if change is None:
        return None
    if change.kind == "price" and change.new:
        return ("price", change.plan, number(change.new))
    if change.kind in ("plan_added", "plan_removed") and change.plan:
        return (change.kind, change.plan)
    if change.kind in ("line_added", "line_removed", "line_changed"):
        return (change.kind, (change.new or change.old or "").lower())
    if change.kind in ("headline", "subheadline", "buttons"):
        return (change.kind, (change.new or "").lower())
    if change.kind == "limits" and change.new:
        return ("limits", change.plan, number(change.new))
    return None


CHANGE_VERBS = frozenset(
    re.findall(
        r"\w+",
        "raise raises raised hike hikes hiked cut cuts drop drops dropped bump bumped live "
        "available roll rolls rolled out launch launches launched add adds added introduce "
        "introduces introduced remove removes removed ship ships shipped update updates updated "
        "change changes changed cost costs move moves goes starting today included per month "
        "monthly year",
    )
)
COMMON_WORDS = frozenset(
    re.findall(
        r"\w+",
        "you your we us our they them just only first more most less very also out about after "
        "before into over than then there these those what when which who why how here months "
        "weeks days years week day users customers everyone people page site homepage website "
        "says said announced announces report reports reported anyone anything something someone "
        "everybody else keep making make makes thing things option options seeing feels new old "
        "accounts account free paid plan tokens token credits credit messages message allowance "
        "limit limits usage seats seat",
    )
)


def anchors(s: Signal) -> set[str]:
    """Distinctive words two reports of one event share: not numbers, plan names, the
    competitor's own name, or change verbs."""
    return text_anchors(s.text, s.competitor)


@lru_cache(maxsize=65536)
def text_anchors(text: str, competitor: str) -> frozenset[str]:
    own = {*name_roots(competitor), competitor.lower()}
    words = content_words(text) - GENERIC_WORDS - CHANGE_VERBS - COMMON_WORDS - own
    return frozenset(
        w
        for w in words
        if len(w) >= 3 and not w.replace(".", "").isdigit() and not re.fullmatch(PLAN_NAMES, w)
    )


GENERIC_WORDS = frozenset(
    [
        "plan",
        "plans",
        "tier",
        "tiers",
        "pricing",
        "price",
        "prices",
        "month",
        "monthly",
        "free",
        "pro",
        "team",
        "users",
        "now",
        "new",
    ]
)


def notes(s: Signal) -> str:
    extra = []
    if s.source_class in ("anonymous", "sponsored", "guest"):
        extra.append(f"{s.source_class} source")
    if HEDGE.search(s.text) and not s.official:
        extra.append("unconfirmed rumor wording")
    if HYPE.search(s.text) and not s.official:
        extra.append("absolute marketing claim")
    return f" Also: {'; '.join(extra)}." if extra else ""
