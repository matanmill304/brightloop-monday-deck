"""Compare two snapshots of a page and describe each change in one plain sentence.

"Pro plan price changed from $25/month to $30/month (was $25/month on Oct 19)."
Prices, plans and dates come from the captured pages; nothing is generated.
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from brightloop.change import Change, compare, looks_like_failed_capture, page_state
from brightloop.collect.capture import Snapshot


def page_events(previous: Snapshot, current: Snapshot, tz: ZoneInfo) -> tuple[str, list[str]]:
    """(status, sentences). Status: changed | unchanged | failed-capture."""
    old, new = page_state(previous.text), page_state(current.text)
    if looks_like_failed_capture(old, new):
        return "failed-capture", []
    changes = compare(old, new, same_method=previous.method == current.method)
    then = datetime.fromisoformat(previous.captured_at).astimezone(tz).strftime("%b %d")
    sentences = [s for s in (sentence(c, current.page, then) for c in changes) if s]
    return ("changed" if sentences else "unchanged"), sentences


def sentence(change: Change, page: str, then: str) -> str:
    """One sentence per change, in the style of the brief's sample signals."""
    old, new = tidy(change.old), tidy(change.new)
    if change.kind == "price" and old and new:
        plan_old, price_old = split_plan(old)
        plan_new, price_new = split_plan(new)
        subject = f"{plan_new or plan_old} plan price" if (plan_new or plan_old) else "Prices"
        return f"{subject} changed from {price_old} to {price_new} (was {price_old} on {then})."
    if change.kind == "plan_added" and new:
        plan, price = split_plan(new)
        return f"New {plan} plan added at {price} (not on the page on {then})."
    if change.kind == "plan_removed" and old:
        plan, price = split_plan(old)
        return f"{plan} plan ({price}) removed (it was on the page on {then})."
    if change.kind == "wording" and (old or new):
        where = "Homepage" if page == "home" else "Pricing page"
        if old and new and ";" not in old and ";" not in new:
            return f'{where} text changed from "{old}" to "{new}" since {then}.'
        parts = [f'now says "{new}"' if new else "", f'no longer says "{old}"' if old else ""]
        return f"{where} text changed since {then}: " + "; ".join(p for p in parts if p) + "."
    return ""


def split_plan(value: str) -> tuple[str, str]:
    """'Pro $25/month' -> ('Pro', '$25/month'); '$0, $25' -> ('', '$0, $25')."""
    m = re.match(r"^([A-Za-z][\w ]*?)\s+([$€£].*)$", value)
    return (m.group(1), m.group(2)) if m else ("", value)


def tidy(value: str | None) -> str | None:
    return re.sub(r"\s*/\s*", "/", value).strip() if value else None
