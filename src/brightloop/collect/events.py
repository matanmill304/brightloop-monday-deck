"""Compare two snapshots of a page and describe each change in one plain sentence.

"Pro plan price changed from $25/month to $30/month (was $25/month on Oct 19)."
Prices, plans, lines and dates come from the captured pages; nothing is generated.
"""

from __future__ import annotations

import re
from zoneinfo import ZoneInfo

from brightloop.change import Change, compare, looks_like_failed_capture, page_state
from brightloop.collect.capture import Snapshot
from brightloop.normalize import parse_iso


def page_events(previous: Snapshot, current: Snapshot, tz: ZoneInfo) -> tuple[str, list[str]]:
    """(status, sentences). Status: changed | unchanged | failed-capture | first-snapshot."""
    old, new = page_state(previous.text), page_state(current.text)
    if old.error_page:
        return "first-snapshot", []  # the previous copy was the archive's error page
    if looks_like_failed_capture(old, new):
        return "failed-capture", []
    if previous.method != current.method:
        # An archived copy and a live render differ for reasons that aren't changes (scripts
        # that didn't run, a different billing view): the first live capture is a new baseline.
        return "first-snapshot", []
    then = parse_iso(previous.captured_at).astimezone(tz).strftime("%b %d")
    sentences = []
    if headline_changed(previous.headline, current.headline):
        sentences.append(f'Headline changed from "{previous.headline}" to "{current.headline}".')
    sentences += hero_changes(previous.hero, current.hero)
    sentences += [s for s in (sentence(c, current.page, then) for c in compare(old, new)) if s]
    return ("changed" if sentences else "unchanged"), sentences


def hero_changes(old: dict | None, new: dict | None) -> list[str]:
    """The line under the headline and the buttons next to it, compared as whole lines.
    Only between two captures that both read the top of the page (captures from Oct 24 on)."""
    if not old or not new:
        return []
    out = []
    before, after = (old.get("subheadline") or "").strip(), (new.get("subheadline") or "").strip()
    if before and after and before.lower() != after.lower():
        out.append(f'Subheadline changed from "{before}" to "{after}".')
    was, now = list(old.get("buttons") or []), list(new.get("buttons") or [])
    added = [b for b in now if b not in was]
    removed = [b for b in was if b not in now]
    if was and now and (added or removed):
        parts = [f'now "{b}"' for b in added] + [f'no longer "{b}"' for b in removed]
        out.append("Top-of-page buttons changed: " + "; ".join(parts) + ".")
    return out


def headline_changed(old: str, new: str) -> bool:
    def norm(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip().lower()

    return bool(norm(old)) and bool(norm(new)) and norm(old) != norm(new)


def sentence(change: Change, page: str, then: str) -> str:
    """One sentence per change, in the style of the brief's sample signals."""
    where = "homepage" if page == "home" else "pricing page"
    old, new, plan = tidy(change.old), tidy(change.new), change.plan
    if change.kind == "price" and old and new:
        return f"{plan} plan price changed from {old} to {new} (was {old} on {then})."
    if change.kind == "plan_added" and new:
        return f"New {plan} plan added at {new} (not on the page on {then})."
    if change.kind == "plan_removed" and old:
        return f"{plan} plan ({old}) removed (it was on the page on {then})."
    if plan and change.kind.startswith("line_"):
        where += f" ({plan} plan)"  # the card the line sits in
    if change.kind == "line_changed":
        return f'Changed on the {where}: "{change.old}" → "{change.new}"'
    if change.kind == "line_added" and change.new:
        return f'New on the {where}: "{change.new}"'
    if change.kind == "line_removed" and change.old:
        return f'No longer on the {where}: "{change.old}"'
    return ""


def tidy(value: str | None) -> str | None:
    return re.sub(r"\s*/\s*", "/", value).strip() if value else None
