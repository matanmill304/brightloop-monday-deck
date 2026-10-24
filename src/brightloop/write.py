"""Step 7: the words. Facts filled into templates, so no number is ever invented.

Maya: "Leadership wants the visual diff, not an essay." So `action` says which slide to
update and what changed; `why` says where it was seen and when. Nothing else.
"""

from __future__ import annotations

import re
from datetime import tzinfo
from typing import Any

from brightloop.change import describe
from brightloop.select import Candidate, pricing_url

SLIDE = {"pricing": "pricing", "home": "homepage", "other": "pricing"}


def build_item(item_id: str, c: Candidate, cta_required: bool, tz: tzinfo) -> dict[str, Any]:
    lead = c.lead
    links = unique([s.url for s in c.signals if s.url])
    what = change_text(c)
    slide = SLIDE[lead.page] if c.track != "announced" else "pricing"
    check = pricing_url(lead.competitor) or (links[0] if links else None)

    if c.track == "announced":
        page = check or f"{lead.competitor}'s pricing page"
        action = (
            f'Check {page} before the 11:00 meeting: {lead.competitor} announced "{what}". '
            f"Add it to the {lead.competitor} pricing slide only if the page shows it."
        )
    else:
        action = f"Update the {lead.competitor} {slide} slide: {what}."

    change, change_detail = [], []
    for ch in most_specific(c.changes):
        text = describe(ch) or first_sentence(lead.text)
        if text not in change:
            change.append(text)
            change_detail.append({"kind": ch.kind, "plan": ch.plan, "old": ch.old, "new": ch.new})
    item: dict[str, Any] = {
        "id": item_id,
        "source_ids": [s.id for s in c.signals + c.corroboration],
        "confidence": c.confidence,
        "action": action,
        "why": explain(c, tz),
        "competitor": lead.competitor,
        "page": lead.page if c.track != "announced" else "announcement",
        "change": change,
        "change_detail": change_detail,  # the same changes as {kind, plan, old, new}, for slides
        "links": links,
        "sources": [
            {"id": s.id, "source": s.source or None, "class": s.source_class}
            for s in c.signals + c.corroboration
        ],
    }
    if c.caveats:
        item["caveats"] = c.caveats
    if cta_required:
        if c.track == "announced":
            item["cta"] = {"text": "Check the official pricing page", "url": check}
        else:
            item["cta"] = {
                "text": f"Open {lead.competitor}'s {slide} page",
                "url": links[0] if links else check,
            }
    return item


def most_specific(changes: list) -> list:
    """Old → new beats a new price alone: several reports of one change show it once."""
    return [ch for ch in changes if ch.old and ch.new] or changes[:1]


def change_text(c: Candidate) -> str:
    """The change in one line: old → new when we have both, else the source's own words."""
    described = [describe(ch) for ch in c.changes if describe(ch)]
    if c.track == "compared" and described:
        return "; ".join(described[:3])
    first = c.changes[0]
    if (first.old and first.new) or first.kind.startswith("line_") or first.kind == "headline":
        return describe(first)
    return first_sentence(c.lead.text)


def explain(c: Candidate, tz: tzinfo) -> str:
    lead = c.lead
    when = lead.when.astimezone(tz).strftime("%b %d, %Y") if lead.when else "date unknown"
    where = lead.url or lead.source or lead.domain or "its own site"
    if c.track == "compared":
        first = c.signals[0]
        then = first.when.astimezone(tz).strftime("%b %d") if first.when else "earlier"
        text = (
            f"Compared two snapshots of {lead.competitor}'s own {SLIDE[lead.page]} page "
            f"({where}): {then} vs {when}."
        )
    elif c.track == "page":
        text = f"Stated on {lead.competitor}'s own {SLIDE[lead.page]} page ({where}) on {when}."
    else:
        text = (
            f"Announced by {lead.competitor} itself ({where}) on {when}, not on its pricing page."
        )
    others = unique([s.source or str(s.id) for s in c.signals if s is not lead])
    others = [o for o in others if o != (lead.source or str(lead.id))]
    if others and c.track != "compared":
        text += " Also stated by " + ", ".join(others) + "."
    if c.corroboration:
        reports = unique([f"{s.source or s.id} ({s.source_class})" for s in c.corroboration])
        text += " Also reported by " + ", ".join(reports) + "."
    return text


def first_sentence(text: str, limit: int = 160) -> str:
    sentence = re.split(r"(?<=[.!?])\s+", text.strip())[0].rstrip(".")
    if len(sentence) > limit:
        sentence = sentence[: limit - 1].rsplit(" ", 1)[0] + "…"
    return sentence


def unique(values: list[Any]) -> list[Any]:
    out: list[Any] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out
