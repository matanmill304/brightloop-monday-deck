"""Step 7: the words. Templates filled from the signals, so no number is ever invented."""

from __future__ import annotations

import re
from datetime import tzinfo
from typing import Any

from brightloop.decide import PRICE, Verdict
from brightloop.normalize import Signal

CLASS_LABEL = {
    "observed": "captured from the page itself",
    "official": "official source",
    "advertiser": "the competitor's own ad",
    "press": "press",
    "media": "third-party blog or media",
    "unknown": "unclassified source",
    "community": "community post",
    "guest": "guest post",
    "sponsored": "sponsored content",
    "anonymous": "anonymous post",
}
TRUST_ORDER = list(CLASS_LABEL)


def build_item(
    item_id: str, group: list[Signal], verdict: Verdict, cta_required: bool, tz: tzinfo
) -> dict[str, Any]:
    lead = min(group, key=lambda s: TRUST_ORDER.index(s.source_class))
    kind = "price_change" if PRICE.search(lead.text) else "packaging"
    summary = first_sentence(lead.text)
    links = unique([s.url for s in group if s.url])

    item: dict[str, Any] = {
        "id": item_id,
        "source_ids": [s.id for s in group],
        "confidence": verdict.confidence,
        "action": (
            f"Flag on the {lead.competitor} slide: {summary} "
            f"Check the linked source before the 11:00 meeting."
        ),
        "why": explain(group, lead, kind, tz),
        "competitor": lead.competitor,
        "kind": kind,
        "links": links,
        "sources": [
            {"id": s.id, "source": s.source or None, "class": s.source_class} for s in group
        ],
    }
    if verdict.reasons:
        item["caveats"] = verdict.reasons
    if cta_required:
        item["cta"] = {
            "text": f"Open the {lead.competitor} source and update the slide",
            "url": links[0] if links else None,
        }
    return item


def explain(group: list[Signal], lead: Signal, kind: str, tz: tzinfo) -> str:
    when = lead.when.astimezone(tz).strftime("%b %d, %Y") if lead.when else "date unknown"
    parts = [f"Reported by {describe(lead)} on {when}."]
    others = [s for s in group if s is not lead]
    if others:
        listed = ", ".join(describe(s) for s in others)
        parts.append(f"Also reported by {listed}, which agree{'s' if len(others) == 1 else ''}.")
    if kind == "packaging":
        parts.append("It changes what is included in which plan, which is what prospects compare.")
    return " ".join(parts)


def describe(signal: Signal) -> str:
    label = CLASS_LABEL.get(signal.source_class, "source")
    where = signal.source or signal.domain or "an unnamed source"
    return f"{where} ({label})"


def skip_reason_for_trust(verdict: Verdict) -> str:
    why = "; ".join(verdict.reasons) or "weak source"
    return f"Not confident enough to put in front of leadership ({verdict.confidence:.2f}): {why}."


def first_sentence(text: str, limit: int = 160) -> str:
    sentence = re.split(r"(?<=[.!?])\s+", text.strip())[0]
    if len(sentence) > limit:
        sentence = sentence[: limit - 1].rsplit(" ", 1)[0] + "…"
    if sentence and sentence[-1] not in ".!?…":
        sentence += "."
    return sentence


def unique(values: list[Any]) -> list[Any]:
    out: list[Any] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out
