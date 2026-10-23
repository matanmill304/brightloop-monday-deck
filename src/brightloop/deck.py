"""Maya's Monday deck: a summary slide, then one slide per competitor page.

The deck is a wrapper for leadership: short and clean. The summary says which pages changed;
each page slide has the screenshot, one status line and one row per change (plan, tag,
old → new). Wording edits (the numbers stayed the same) are shown in grey and never count as
a change. No confidence, sources or caveats on the slides: those stay in result.json.

One slide model, three renderings that can't drift apart: the web app shows `slide_html()`,
deck.html (print view / PDF) wraps the same HTML, and the .pptx (opens in Google Slides via
File → Import slides) is drawn from the same fields with the same fonts and colours.
Every page name, URL and screenshot links to the competitor's live page, never an archive.
"""

from __future__ import annotations

import html
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from brightloop import write_text
from brightloop.change import same_numbers
from brightloop.normalize import parse_iso

PAGES = (("pricing", "pricing"), ("home", "homepage"))
DEFAULT_COMPETITORS = ("Lovable", "Replit", "Bolt")
STATUS_LINE = {
    "wording": "Wording changed, no price or limit changed",
    "unchanged": "No change this week",
    "not-captured": "Not captured this week",
    "first-snapshot": "First capture: nothing to compare yet",
    "failed-capture": "Capture failed: check the page by hand",
}
TAG = {
    "price": "Price",
    "plan_added": "New plan",
    "plan_removed": "Plan removed",
    "headline": "Headline",
    "line_added": "Added",
    "line_removed": "Removed",
}
BRAND = "Competitor watch"
MAX_ROWS = 6  # rows on a page slide; the rest are "And N more lines (see What's new)"


@dataclass
class Slide:
    title: str  # "Bolt pricing"; on the summary, "1 of 6 pages changed"
    status: str  # summary | changed | wording | unchanged | not-captured | first-snapshot | failed-capture
    lead: str  # the status line; on the summary, the subtitle
    rows: list[dict[str, Any]] = field(default_factory=list)  # see page_rows() and summary_slide()
    url: str | None = None  # the competitor's live page
    shot: str | None = None  # screenshot path
    footer: str = ""
    comp: str = ""  # "Bolt"
    page: str = ""  # pricing | homepage
    kicker: str = ""  # "Bolt · Pricing page"; on the summary, "Competitor pages · Oct 19–25"
    real: int = 0  # rows that are a change
    wording: int = 0  # rows that are a wording edit
    exceptions: list[str] = field(default_factory=list)  # "archived copy", "yearly prices shown"
    capture: dict[str, Any] | None = None  # {method, billing, date}


def build_slides(
    case: dict[str, Any], result: dict[str, Any], run: dict[str, Any] | None = None
) -> list[Slide]:
    """With the collector's run.json: the summary, then one slide per page, every page shown
    (also "no change"). Without it (an uploaded cases.json): one slide per item."""
    tz = ZoneInfo(case.get("timezone") or "UTC")
    week = case.get("week")
    lead = footer_lead(week, run, tz)
    signal_ts = {s.get("id"): s.get("ts") for s in case.get("signals", [])}
    item_of = {sid: item for item in result.get("items", []) for sid in item["source_ids"]}
    entries = sorted(
        (run or {}).get("pages", []),
        key=lambda e: (*order(e["competitor"]), [p for p, _ in PAGES].index(e["page"])),
    )
    slides, shown = [], set()
    for entry in entries:
        items = unique_items(item_of.get(sid) for sid in entry.get("signal_ids", []))
        shown.update(item["id"] for item in items)
        slides.append(page_slide(entry, items, signal_ts, lead, tz))
    for item in result.get("items", []):
        if item["id"] not in shown:
            slides.append(item_slide(item, signal_ts, lead, tz))
    if run is not None:
        slides.insert(0, summary_slide(slides, week, lead))
    return slides


def page_slide(
    entry: dict[str, Any],
    items: list[dict[str, Any]],
    signal_ts: dict[str, str],
    lead: str,
    tz: ZoneInfo,
) -> Slide:
    current = entry.get("current") or {}
    rows = page_rows(items, signal_ts, tz)
    status = entry["status"]
    if status == "changed":
        # The page differed, but the analysis kept nothing for Maya: no change. Every row a
        # wording edit: the words changed, no price or limit did.
        status = "unchanged" if not rows else page_status(rows)
    captured = status != "not-captured" and bool(current)
    capture = capture_info(current, tz) if captured else None
    notes = capture_notes(capture, entry["page"])
    return Slide(
        title=f"{entry['competitor']} {dict(PAGES)[entry['page']]}",
        status=status,
        lead=status_line(status, rows),
        rows=rows,
        url=entry["url"],
        shot=current.get("screenshot") if captured else None,
        footer=page_footer(lead, entry["url"], capture, notes),
        comp=entry["competitor"],
        page=dict(PAGES)[entry["page"]],
        kicker=f"{entry['competitor']} · {'Pricing page' if entry['page'] == 'pricing' else 'Homepage'}",
        real=sum(not r["minor"] for r in rows),
        wording=sum(r["minor"] for r in rows),
        exceptions=notes,
        capture=capture,
    )


def item_slide(item: dict[str, Any], signal_ts: dict[str, str], lead: str, tz: ZoneInfo) -> Slide:
    page = dict(PAGES).get(item.get("page", ""), "")
    url = (item.get("links") or [None])[0] or (item.get("cta") or {}).get("url")
    rows = page_rows([item], signal_ts, tz)
    status = page_status(rows)
    return Slide(
        title=f"{item.get('competitor', '')} {page}".strip(),
        status=status,
        lead=status_line(status, rows),
        rows=rows,
        url=url,
        footer=page_footer(lead, url, None, []),
        comp=item.get("competitor", ""),
        page=page,
        kicker=item.get("competitor", ""),
        real=sum(not r["minor"] for r in rows),
        wording=sum(r["minor"] for r in rows),
    )


def summary_slide(pages: list[Slide], week: str | None, lead: str) -> Slide:
    """The first slide: which pages changed, which didn't, and what to check by hand.
    Leadership can stop here."""
    changed = [s for s in pages if s.status == "changed"]
    wording = [s for s in pages if s.status == "wording"]
    quiet = [s for s in pages if s.status == "unchanged"]
    rows: list[dict[str, Any]] = []
    for s in changed:
        first = next((r for r in s.rows if not r["minor"]), s.rows[0])
        more = []
        if s.real > 1:
            more.append("Plus " + plural(s.real - 1, "more change", "more changes"))
        if s.wording:
            more.append("Plus " + plural(s.wording, "wording edit", "wording edits"))
        rows.append(
            {
                "type": "changed",
                "name": s.title,
                "url": s.url,
                "text": first["text"],
                "more": " · ".join(more),
                "date": first["date"],
            }
        )
    for s in wording:
        rows.append(
            {
                "type": "wording",
                "name": s.title,
                "url": s.url,
                "date": s.rows[0]["date"],
                "text": plural(s.wording, "wording edit", "wording edits"),
                "more": "",
            }
        )
    if quiet:
        rows.append({"type": "quiet", "pages": [{"name": s.title, "url": s.url} for s in quiet]})
    for e in week_exceptions(pages):
        rows.append({"type": "check", "text": e["text"]})
    competitors = list(dict.fromkeys(s.comp for s in pages if s.comp))
    kinds = list(dict.fromkeys(s.page for s in pages if s.page))
    sub = " · ".join(
        p
        for p in (
            join_and(competitors),
            join_and([f"{k} pages" if k == "pricing" else "homepages" for k in kinds]),
        )
        if p
    )
    archived = sum(1 for s in pages if s.capture and s.capture["method"] != "live")
    dates = [s.capture["day"] for s in pages if s.capture]
    shots = ""
    if dates:
        how = plural(archived, "archived copy", "archived copies") if archived else "live"
        shots = f" · screenshots {date_span(dates)} ({how})"
    return Slide(
        title=summary_title(len(changed), len(pages), bool(wording)),
        status="summary",
        lead=sub,
        rows=rows,
        footer=f"{lead} · {plural(len(pages), 'page', 'pages')}{shots}",
        kicker=f"Competitor pages · {week_range(week)}" if week_range(week) else "Competitor pages",
        real=len(changed),
        wording=sum(s.wording for s in wording + changed),
    )


def summary_title(changed: int, total: int, wording: bool) -> str:
    if changed:
        return f"{changed} of {total} pages changed"
    return "No price or limit changed" if wording else "No changes this week"


def page_rows(
    items: list[dict[str, Any]], signal_ts: dict[str, str], tz: ZoneInfo
) -> list[dict[str, Any]]:
    """One row per change: {date, plan, kind, tag, minor, old, new, text}. Real changes first,
    then wording edits; by date within each. The same change read on two pages (one item)
    shows once, with its plan when one page knew it."""
    rows: list[dict[str, Any]] = []
    for item in items:
        stamp = first_seen(item, signal_ts)
        day = short_date(stamp, tz) if stamp else ""
        announced = item.get("page") == "announcement"
        details = item.get("change_detail") or [
            {"kind": "other", "plan": None, "old": None, "new": None} for _ in item_changes(item)
        ]
        for detail, said in zip(details, item_changes(item)):
            row = make_row(detail, said, day, announced)
            row["_ts"] = stamp or ""
            same = next((r for r in rows if same_row(r, row)), None)
            if same is None:
                rows.append(row)
            elif row["plan"] and not same["plan"]:
                rows[rows.index(same)] = row
    rows.sort(key=lambda r: (r["minor"], r["_ts"]))
    for r in rows:
        del r["_ts"]
    return rows


def make_row(detail: dict[str, Any], said: str, day: str, announced: bool) -> dict[str, Any]:
    kind, plan, old, new = (detail.get(k) for k in ("kind", "plan", "old", "new"))
    minor = is_wording_only(detail)
    if not old and not new:
        new = said  # a change stated without its values: the source's own words
    text = slide_text(kind, plan, old, new, said)
    if announced:
        text = f"Announced, not yet on the pricing page: {text}"
    return {
        "date": day,
        "plan": plan,
        "kind": kind,
        "tag": "Wording" if minor else TAG.get(kind, "Changed"),
        "minor": minor,
        "old": old,
        "new": new,
        "text": text,
    }


def is_wording_only(detail: dict[str, Any]) -> bool:
    """An edited line that keeps every number and its unit ("1M tokens per month" ->
    "1M tokens/month to try Bolt"): the words changed, not the offer. Shown in grey and never
    counted as a change; the item stays in result.json as it is."""
    return detail.get("kind") == "line_changed" and same_numbers(
        detail.get("old"), detail.get("new")
    )


def slide_text(kind: str, plan: str | None, old: str | None, new: str | None, said: str) -> str:
    """The change as one line for the summary slide and the .pptx (spec 5.5)."""
    on = f"{plan}: " if plan else ""
    if kind == "price" and old and new:
        text = f"{on}{old} → {new}"
    elif kind == "plan_added":
        text = f"New plan: {plan} at {new}" if plan and new else said
    elif kind == "plan_removed":
        text = f"Plan removed: {plan} ({old})" if plan and old else said
    elif kind == "headline" and old and new:
        text = f'Headline: "{old}" → "{new}"'
    elif kind == "line_removed" and old:
        text = f'{on}"{old}" is no longer on the page'
    elif kind == "line_added" and new:
        text = f'{on}new on the page: "{new}"'
    elif kind == "line_changed" and old and new:
        text = f'{on}"{old}" → "{new}"'
    else:
        text = said
    return text[:1].upper() + text[1:]


def same_row(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (a["kind"], a["old"], a["new"]) == (b["kind"], b["old"], b["new"])


def page_status(rows: list[dict[str, Any]]) -> str:
    return "changed" if any(not r["minor"] for r in rows) or not rows else "wording"


def status_line(status: str, rows: list[dict[str, Any]]) -> str:
    if status != "changed":
        return STATUS_LINE.get(status, status)
    real, minor = sum(not r["minor"] for r in rows), sum(r["minor"] for r in rows)
    line = "Changed this week · " + plural(real, "change", "changes")
    return line + (", " + plural(minor, "wording edit", "wording edits") if minor else "")


def item_changes(item: dict[str, Any]) -> list[str]:
    return list(item.get("change") or []) or [item["action"]]


def unique_items(items) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if item and all(item["id"] != o["id"] for o in out):
            out.append(item)
    return out


def first_seen(item: dict[str, Any], signal_ts: dict[str, str]) -> str | None:
    """When the item's first signal was seen."""
    stamps = sorted(ts for sid in item["source_ids"] if (ts := signal_ts.get(sid)))
    return stamps[0] if stamps else None


# ---- Captures, exceptions, footers ------------------------------------------------------------


def capture_info(current: dict[str, Any], tz: ZoneInfo) -> dict[str, Any] | None:
    if not current.get("captured_at"):
        return None
    moment = parse_iso(current["captured_at"]).astimezone(tz)
    return {
        "method": current.get("method") or "live",
        "billing": current.get("billing"),
        "date": short_date(current["captured_at"], tz),
        "day": moment.date().isoformat(),
    }


def capture_notes(capture: dict[str, Any] | None, page: str) -> list[str]:
    """What Maya should know about a screenshot: it's an archived copy, it shows yearly prices.
    Only a pricing page's screenshot shows prices; a homepage's shows the top of the page."""
    if not capture:
        return []
    notes = []
    if capture["method"] != "live":
        notes.append("archived copy")
    if page == "pricing" and capture.get("billing") == "yearly":
        notes.append("yearly prices shown")
    return notes


def week_exceptions(pages: list[Slide]) -> list[dict[str, Any]]:
    """The cases where Maya must check by hand (spec 5.3): {tag, text, url?}."""
    out: list[dict[str, Any]] = []
    archived = [s for s in pages if s.capture and s.capture["method"] != "live"]
    if archived:
        span = date_span([s.capture["day"] for s in archived])
        if len(archived) == len(pages):
            text = (
                f"All {len(pages)} screenshots come from the Wayback Machine ({span}), "
                "so some may be a few days old."
            )
        elif len(archived) == 1:
            text = (
                f"{archived[0].title} comes from the Wayback Machine ({span}), "
                "so it may be a few days old."
            )
        else:
            names = join_and([s.title for s in archived])
            text = f"{names} come from the Wayback Machine ({span}), so they may be a few days old."
        out.append({"tag": "Archived copies", "text": text})
    for s in pages:
        if s.capture and "yearly prices shown" in s.exceptions:
            why = (
                " (the archived copy can't switch to Monthly)"
                if s.capture["method"] != "live"
                else ""
            )
            out.append(
                {
                    "tag": "Yearly prices",
                    "text": f"The {s.title} screenshot shows yearly prices{why}.",
                }
            )
    for s in pages:
        if s.status == "not-captured":
            text = f"{s.title} was not captured this week: check it by hand."
            out.append({"tag": "Not captured", "text": text, "url": s.url})
        elif s.status == "failed-capture":
            text = f"{s.title} could not be read this week: check it by hand."
            out.append({"tag": "Capture failed", "text": text, "url": s.url})
        elif s.status == "first-snapshot":
            text = f"First capture of {s.title}: nothing to compare yet."
            out.append({"tag": "First capture", "text": text})
    return out


def footer_lead(week: str | None, run: dict[str, Any] | None, tz: ZoneInfo) -> str:
    if run is not None and is_partial(week, run, tz):
        return "Week in progress"
    meeting = meeting_label(week, short=True)
    return f"Deck for {meeting}" if meeting else ""


def page_footer(
    lead: str, url: str | None, capture: dict[str, Any] | None, notes: list[str]
) -> str:
    """'Deck for Mon, Oct 26 · Source: bolt.new/pricing · Screenshot Oct 23 · archived copy'."""
    parts = [lead] if lead else []
    if url:
        parts.append(f"Source: {bare_url(url)}")
    if capture:
        parts.append(f"Screenshot {capture['date']}")
    return " · ".join(parts + notes)


def is_partial(week: str | None, run: dict[str, Any], tz: ZoneInfo) -> bool:
    """The run finished before the week ended: the week's deck so far."""
    end = week_end(week, tz)
    finished = run.get("finished_at")
    return bool(end and finished) and parse_iso(finished) < end


def week_end(week: str | None, tz: ZoneInfo) -> datetime | None:
    monday = week_monday(week)
    return datetime.combine(monday + timedelta(days=7), time.min, tz) if monday else None


# ---- The week, for the web app and /api/deck ----------------------------------------------------


def week_view(
    case: dict[str, Any], result: dict[str, Any], run: dict[str, Any], tz_name: str | None = None
) -> dict[str, Any]:
    """Everything the app shows for one week (spec 6.3). The site build and /api/deck both
    use it, so a rebuilt week can be compared with the stored one like for like."""
    tz = ZoneInfo(tz_name or case.get("timezone") or "UTC")
    week = case.get("week") or run.get("week")
    slides = build_slides(case, result, run)
    pages = slides[1:]
    built = parse_iso(run["finished_at"]).astimezone(tz)
    return {
        "week": week,
        "meeting": meeting_label(week),
        "meeting_short": meeting_label(week, short=True),
        "range": week_range(week),
        "partial": is_partial(week, run, tz),
        "built_at": run["finished_at"],
        "built": clock(built),
        "pages_total": len(pages),
        "changed": sum(s.status == "changed" for s in pages),
        "wording": sum(s.status == "wording" for s in pages),
        # each slide with its rendered HTML: the same markup as deck.html
        "slides": [{**vars(s), "html": slide_html(s)} for s in slides],
        "changes": [
            {
                "index": n + 1,
                "name": s.title,
                "comp": s.comp,
                "page": s.page,
                "url": s.url,
                "real": s.real,
                "wording": s.wording,
                "rows": s.rows,
            }
            for status in ("changed", "wording")
            for n, s in enumerate(pages)
            if s.status == status
        ],
        "quiet": [{"name": s.title, "url": s.url} for s in pages if s.status == "unchanged"],
        "exceptions": week_exceptions(pages),
    }


# ---- Rendering: HTML ------------------------------------------------------------------------------

LOCK = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="18" '
    'height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'
)
DOT = {
    "changed": "dot",
    "wording": "dot dot--none",
    "unchanged": "dot dot--none",
    "not-captured": "dot dot--missing",
    "first-snapshot": "dot dot--first",
    "failed-capture": "dot dot--danger",
}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def ext_link(url: str | None, text: str, cls: str = "") -> str:
    if not url:
        return esc(text)
    attr = f' class="{cls}"' if cls else ""
    return f'<a{attr} href="{esc(url)}" target="_blank" rel="noopener">{esc(text)}</a>'


def redline(row: dict[str, Any]) -> str:
    """Old value struck through, an arrow, the new value highlighted."""
    parts = []
    if row["old"] is not None:
        parts.append(f"<s>{esc(row['old'])}</s>")
    if row["old"] is not None and row["new"] is not None:
        parts.append('<span class="arrow">→</span>')
    if row["new"] is not None:
        parts.append(f"<mark>{esc(row['new'])}</mark>")
    return f'<span class="redline">{" ".join(parts)}</span>'


def tag_class(row: dict[str, Any]) -> str:
    if row["minor"]:
        return "tag tag--wording"
    return "tag tag--added" if row["tag"] == "Added" else "tag"


def slide_html(s: Slide) -> str:
    """One slide (a `.slide` element, 16:9, sized in cqw): the app, deck.html and the PDF."""
    if s.status == "summary":
        return summary_html(s)
    shown = s.rows if len(s.rows) <= MAX_ROWS + 1 else s.rows[:MAX_ROWS]
    rows = "".join(
        f'<div class="slide-row{" slide-row--wording" if r["minor"] else ""}">'
        + (
            f'<span class="plan">{esc(r["plan"])}</span>'
            if r["plan"]
            else '<span class="plan plan--none">—</span>'
        )
        + f'<span><span class="{tag_class(r)}">{esc(r["tag"])}</span></span>{redline(r)}</div>'
        for r in shown
    )
    if len(s.rows) > len(shown):
        more = f"And {len(s.rows) - len(shown)} more lines (see What's new)"
        rows += f'<div class="slide-row slide-row--wording"><span></span><span></span><span>{esc(more)}</span></div>'
    shot = ""
    if s.shot:
        archived = "archived copy" in s.exceptions
        alt = f"{s.title}, {'archived copy' if archived else 'captured'} {(s.capture or {}).get('date', '')}"
        shot = (
            f'<a class="slide-shot" href="{esc(s.url)}" target="_blank" rel="noopener" '
            f'aria-label="{esc("Open " + bare_url(s.url))}">'
            f'<div class="slide-urlbar">{LOCK}{esc(bare_url(s.url))}</div>'
            f'<div class="slide-img"><img src="{esc(s.shot)}" alt="{esc(alt.strip())}"></div></a>'
        )
    return (
        '<div class="slide"><div class="slide-main">'
        f'<div class="slide-kicker">{esc(s.kicker)}</div>'
        f'<div class="slide-title">{esc(s.title)}</div>'
        f'<div class="slide-status"><span class="{DOT.get(s.status, "dot dot--none")}"></span>{esc(keep_counts(s.lead))}</div>'
        + (f'<div class="slide-rows">{rows}</div>' if rows else "")
        + f"</div>{shot}"
        f'<div class="slide-foot"><span>{footer_html(s)}</span><span>{BRAND}</span></div></div>'
    )


def keep_counts(line: str) -> str:
    """'Changed this week · 1 change, 2 wording edits' with each count kept on one line."""
    head, sep, counts = line.partition(" · ")
    return head + sep + ", ".join(c.replace(" ", "\u00a0") for c in counts.split(", "))


def footer_html(s: Slide) -> str:
    """The footer with its source URL as a link to the live page."""
    bare = bare_url(s.url) if s.url else ""
    if not bare or f"Source: {bare}" not in s.footer:
        return esc(s.footer)
    before, after = s.footer.split(f"Source: {bare}", 1)
    return f"{esc(before)}Source: {ext_link(s.url, bare)}{esc(after)}"


def summary_html(s: Slide) -> str:
    rows = []
    for r in s.rows:
        if r["type"] in ("changed", "wording"):
            more = f'<span class="more">{esc(r["more"])}</span>' if r.get("more") else ""
            wording = r["type"] == "wording"
            rows.append(
                f'<div class="slide-sum-row{" slide-sum-row--wording" if wording else ""}">'
                f'<span class="{"dot dot--none" if wording else "dot"}"></span>'
                f"{ext_link(r['url'], r['name'])}<span>{esc(r['text'])}{more}</span>"
                f'<span class="muted">{esc(r["date"])}</span></div>'
            )
        elif r["type"] == "quiet":
            links = " · ".join(ext_link(p["url"], p["name"]) for p in r["pages"])
            rows.append(
                '<div class="slide-sum-row slide-sum-row--quiet"><span class="dot dot--none"></span>'
                f"<span>No change</span><span>{links}</span><span></span></div>"
            )
        else:
            rows.append(
                '<div class="slide-sum-row slide-sum-row--quiet"><span class="dot dot--warn"></span>'
                f"<span>Check by hand</span><span>{esc(r['text'])}</span><span></span></div>"
            )
    return (
        '<div class="slide slide--summary"><div class="slide-main">'
        f'<div class="slide-kicker">{esc(s.kicker)}</div>'
        f'<div class="slide-title">{esc(s.title)}</div>'
        f'<div class="slide-sub">{esc(s.lead)}</div>'
        f'<div class="slide-rows">{"".join(rows)}</div></div>'
        f'<div class="slide-foot"><span>{esc(s.footer)}</span><span>{BRAND}</span></div></div>'
    )


def render_html(slides: list[Slide], title: str) -> str:
    frames = "\n".join(f'<div class="slide-frame">{slide_html(s)}</div>' for s in slides)
    return HTML_PAGE.replace("{{title}}", html.escape(title)).replace("{{slides}}", frames)


# The design system's slide styles (docs: tokens.css + components.css "Slides"), as literals.
HTML_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{title}}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@300;400;500&family=Inter:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--ink:#18181B;--ink-2:#44423E;--muted:#6B6964;--quiet:#8A8780;--line:#ECEAE5;--line-strong:#DDDAD3;
  --wash:#F7F6F3;--accent:#FF6A00;--change-bg:#FFF1E6;--change-ink:#9A3412;--added-bg:#ECFDF3;--added-ink:#166534;
  --warn-ink:#92400E;--danger:#B42318;--ok:#15803D;--marker:#FFD9BD;--dot-none:#D6D3CC;
  --font-display:"Inter Tight",Inter,system-ui,sans-serif;--font-ui:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;
  --font-mono:"Geist Mono",ui-monospace,"SF Mono",Menlo,monospace}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;padding:24px 16px;background:#F3F2EF;color:var(--ink);font:400 14px/1.5 var(--font-ui);-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.slide-frame{container-type:inline-size;max-width:1280px;margin:0 auto 24px;border-radius:10px;overflow:hidden;background:#fff;
  box-shadow:0 1px 2px rgba(24,24,27,.05),0 18px 40px -24px rgba(24,24,27,.35)}
.muted{color:var(--muted)}
.dot{display:inline-block;width:7px;height:7px;flex:none;border-radius:999px;background:var(--accent)}
.dot--none{background:var(--dot-none)}.dot--first{background:transparent;box-shadow:inset 0 0 0 1.5px var(--muted)}
.dot--missing{width:6px;height:6px;border-radius:1px;background:var(--warn-ink)}.dot--danger{background:var(--danger)}
.dot--warn{background:var(--warn-ink)}
.tag{display:inline-block;padding:2px 8px;border-radius:999px;font-size:10px;font-weight:600;letter-spacing:.06em;
  text-transform:uppercase;white-space:nowrap;background:var(--change-bg);color:var(--change-ink)}
.tag--added{background:var(--added-bg);color:var(--added-ink)}
.tag--wording{background:transparent;box-shadow:inset 0 0 0 1px #E8E6E1;color:var(--muted)}
.redline s{color:var(--muted);text-decoration-thickness:1px}.redline .arrow{color:var(--quiet)}
.redline mark{color:var(--ink);background:linear-gradient(transparent 56%,var(--marker) 56%);padding:0 1px}
.slide{aspect-ratio:16/9;padding:5cqw 5.4cqw 3.2cqw;display:grid;grid-template-columns:31cqw minmax(0,1fr);
  grid-template-rows:minmax(0,1fr) auto;column-gap:4.4cqw;color:var(--ink);font-family:var(--font-ui)}
.slide--summary{grid-template-columns:minmax(0,1fr)}
.slide-main{min-width:0;overflow:hidden}
.slide-kicker{font-size:.95cqw;font-weight:500;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.slide-title{margin-top:1cqw;font-family:var(--font-display);font-size:4.2cqw;font-weight:400;letter-spacing:-.045em;line-height:1.02}
.slide--summary .slide-title{font-size:4.4cqw}
.slide-sub{margin-top:1cqw;font-size:1.56cqw;color:var(--muted)}
.slide-status{margin-top:1.3cqw;display:flex;align-items:flex-start;gap:.7cqw;font-size:1.45cqw;line-height:1.4;color:var(--ink-2);text-wrap:balance}
.slide-status .dot{width:.7cqw;height:.7cqw;margin-top:.66cqw}
.slide-rows{margin-top:3cqw}
.slide-row{display:grid;grid-template-columns:5.4cqw 7.4cqw minmax(0,1fr);align-items:baseline;padding:1.1cqw 0;
  border-top:1px solid var(--line);font-size:1.32cqw;line-height:1.45}
.slide-row .tag{font-size:.78cqw;padding:.15cqw .55cqw}
.slide-row .plan{font-weight:500}.slide-row .plan--none{color:#C9C6BF}
.slide-row--wording{color:var(--muted)}.slide-row--wording mark{background:none;color:var(--ink-2)}
.slide-sum-row{display:grid;grid-template-columns:1.6cqw minmax(0,15cqw) minmax(0,1fr) auto;align-items:baseline;gap:0 1cqw;
  padding:1.4cqw 0;border-top:1px solid var(--line);font-size:1.66cqw}
.slide-sum-row .dot{width:.8cqw;height:.8cqw}
.slide-sum-row .more{display:block;margin-top:.3cqw;font-size:1.25cqw;color:var(--muted)}
.slide-sum-row--quiet{font-size:1.46cqw;color:var(--ink-2)}.slide-sum-row--wording{color:var(--muted)}
.slide-sum-row a{font-weight:500;text-decoration:underline;text-decoration-color:var(--line-strong);text-underline-offset:.3cqw}
.slide-shot{display:block;align-self:start;overflow:hidden;border-radius:.8cqw;box-shadow:0 0 0 1px var(--line),0 1.4cqw 3cqw -1.6cqw rgba(24,24,27,.3)}
.slide-urlbar{display:flex;align-items:center;gap:.6cqw;height:2.3cqw;padding:0 1cqw;background:var(--wash);border-bottom:1px solid var(--line);
  font-family:var(--font-mono);font-size:.9cqw;color:var(--muted)}
.slide-urlbar svg{width:.9cqw;height:.9cqw}
.slide-img{max-height:38cqw;overflow:hidden}.slide-img img{width:100%;display:block}
.slide-foot{grid-column:1/-1;display:flex;justify-content:space-between;gap:2cqw;padding-top:1.8cqw;font-size:.92cqw;color:var(--quiet)}
.slide-foot a{text-decoration:underline;text-underline-offset:.2cqw}
@media print{body{background:#fff;padding:0}.slide-frame{max-width:none;margin:0;border-radius:0;box-shadow:none;break-after:page}}
</style></head><body>
{{slides}}
</body></html>
"""


# ---- Rendering: .pptx ---------------------------------------------------------------------------


def render_pptx(slides: list[Slide], folder: Path, path: Path) -> None:
    """The same slides as .pptx for Google Slides (File → Import slides): the design system's
    fonts and hex values, the footer URL and the screenshot linked to the live page."""
    from PIL import Image
    from pptx import Presentation  # optional dependency: pip install .[deck]
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu, Pt

    px = 12192000 // 1920  # EMU per slide pixel: a 1920×1080 layout, as in the HTML (2px = 1pt)

    def rgb(hex_value: str) -> RGBColor:
        return RGBColor.from_string(hex_value.lstrip("#"))

    INK, INK2, MUTED, QUIET, WASH = "#18181B", "#44423E", "#6B6964", "#8A8780", "#F7F6F3"
    TAGS = {"change": "#9A3412", "added": "#166534", "wording": MUTED}
    DOTS = {"changed": "#FF6A00", "wording": "#D6D3CC", "unchanged": "#D6D3CC"}

    deck = Presentation()
    deck.slide_width, deck.slide_height = Emu(1920 * px), Emu(1080 * px)
    blank = deck.slide_layouts[6]
    link_colour(deck, INK2)

    def box(slide, x, y, w, h):
        frame = slide.shapes.add_textbox(
            Emu(x * px), Emu(y * px), Emu(w * px), Emu(h * px)
        ).text_frame
        frame.word_wrap = True
        frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
        return frame

    def para(frame, first: bool = False, space_before: float = 0, align=None):
        p = frame.paragraphs[0] if first else frame.add_paragraph()
        p.space_before = Pt(space_before)
        if align is not None:
            p.alignment = align
        return p

    def run(
        p,
        text,
        size,
        color,
        font="Inter",
        bold=False,
        strike=False,
        caps=False,
        spacing=None,
        link=None,
        underline=False,
    ):
        r = p.add_run()
        r.text = text
        r.font.name, r.font.size, r.font.bold = font, Pt(size), bold
        r.font.color.rgb = rgb(color)
        rpr = r._r.get_or_add_rPr()
        if strike:
            rpr.set("strike", "sngStrike")
        if caps:
            rpr.set("cap", "all")
        if spacing is not None:
            rpr.set("spc", str(int(spacing * 100)))
        if link:
            r.hyperlink.address = link
            r.font.color.rgb = rgb(color)
            r.font.underline = underline
        return r

    def footer(slide, s: Slide):
        frame = box(slide, 104, 1018, 1400, 30)
        p = para(frame, first=True)
        bare = bare_url(s.url) if s.url else ""
        if bare and f"Source: {bare}" in s.footer:
            before, after = s.footer.split(f"Source: {bare}", 1)
            run(p, before + "Source: ", 9, QUIET)
            run(p, bare, 9, QUIET, link=s.url, underline=True)
            run(p, after, 9, QUIET)
        else:
            run(p, s.footer, 9, QUIET)
        right = box(slide, 1516, 1018, 300, 30)
        run(para(right, first=True, align=PP_ALIGN.RIGHT), BRAND, 9, QUIET)

    def heading(frame, s: Slide, title_size: float):
        run(para(frame, first=True), s.kicker, 9, MUTED, bold=False, caps=True, spacing=0.9)
        run(
            para(frame, space_before=6),
            s.title,
            title_size,
            INK,
            font="Inter Tight",
            spacing=-title_size * 0.045,
        )

    def tag_color(row) -> str:
        if row["minor"]:
            return TAGS["wording"]
        return TAGS["added"] if row["tag"] == "Added" else TAGS["change"]

    for s in slides:
        slide = deck.slides.add_slide(blank)
        if s.status == "summary":
            frame = box(slide, 104, 96, 1712, 900)
            heading(frame, s, 42)
            run(para(frame, space_before=6), s.lead, 15, MUTED)
            first = True
            for r in s.rows:
                p = para(frame, space_before=24 if first else 14)
                first = False
                if r["type"] in ("changed", "wording"):
                    wording = r["type"] == "wording"
                    run(p, "●  ", 12, DOTS["wording" if wording else "changed"])
                    run(
                        p,
                        r["name"],
                        16,
                        MUTED if wording else INK,
                        bold=True,
                        link=r["url"],
                        underline=True,
                    )
                    run(p, "    " + r["text"], 16, MUTED if wording else INK)
                    run(p, "    " + r["date"], 12, MUTED)
                    if r.get("more"):
                        run(para(frame, space_before=2), "      " + r["more"], 12, MUTED)
                elif r["type"] == "quiet":
                    run(p, "●  ", 12, DOTS["unchanged"])
                    run(p, "No change    ", 14, INK2)
                    for n, page in enumerate(r["pages"]):
                        if n:
                            run(p, " · ", 14, INK2)
                        run(p, page["name"], 14, INK2, link=page["url"], underline=True)
                else:
                    run(p, "■  ", 10, "#92400E")
                    run(p, "Check by hand    ", 14, INK2)
                    run(p, r["text"], 14, INK2)
            footer(slide, s)
            continue

        frame = box(slide, 104, 96, 595, 900)
        heading(frame, s, 40)
        p = para(frame, space_before=10)
        run(p, "●  " if s.status != "not-captured" else "■  ", 12, DOTS.get(s.status, "#D6D3CC"))
        run(p, s.lead, 14, INK2)
        shown = s.rows if len(s.rows) <= MAX_ROWS + 1 else s.rows[:MAX_ROWS]
        for n, r in enumerate(shown):
            p = para(frame, space_before=24 if n == 0 else 10)
            ink = MUTED if r["minor"] else INK
            run(p, (r["plan"] or "—") + "   ", 12.5, ink if r["plan"] else "#C9C6BF", bold=True)
            run(p, r["tag"] + "   ", 7.5, tag_color(r), bold=True, caps=True, spacing=0.45)
            if r["old"] is not None:
                run(p, r["old"], 12.5, MUTED, strike=True)
            if r["old"] is not None and r["new"] is not None:
                run(p, "  →  ", 12.5, QUIET)
            if r["new"] is not None:
                run(p, r["new"], 12.5, ink, bold=not r["minor"])
        if len(s.rows) > len(shown):
            run(
                para(frame, space_before=10),
                f"And {len(s.rows) - len(shown)} more lines (see What's new)",
                12.5,
                MUTED,
            )

        if s.shot and (folder / s.shot).exists():
            left, top, width = 104 + 595 + 84, 96, 1920 - 104 - (104 + 595 + 84)
            bar_h = 44
            bar = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE, Emu(left * px), Emu(top * px), Emu(width * px), Emu(bar_h * px)
            )
            bar.fill.solid()
            bar.fill.fore_color.rgb = rgb(WASH)
            bar.line.color.rgb = rgb("#ECEAE5")
            bar.shadow.inherit = False
            bar.click_action.hyperlink.address = s.url
            tf = bar.text_frame
            tf.margin_left, tf.vertical_anchor = Emu(20 * px), MSO_ANCHOR.MIDDLE
            run(
                para(tf, first=True, align=PP_ALIGN.LEFT),
                bare_url(s.url),
                9,
                MUTED,
                font="Geist Mono",
            )
            with Image.open(folder / s.shot) as img:
                ratio = img.width / img.height
            room = 1018 - 30 - (top + bar_h)  # down to just above the footer
            height = width / ratio
            pic = slide.shapes.add_picture(
                str(folder / s.shot), Emu(left * px), Emu((top + bar_h) * px), Emu(width * px)
            )
            if height > room:  # crop the bottom of tall screenshots to the slide area
                pic.crop_bottom = 1 - room / height
                pic.height = Emu(int(room * px))
            pic.click_action.hyperlink.address = s.url
            pic.line.color.rgb = rgb("#ECEAE5")
        footer(slide, s)
    deck.save(str(path))


def link_colour(deck, hex_value: str) -> None:
    """Links in the theme's colour, not the default blue: a link looks like the text around it
    (Slides and PowerPoint draw hyperlinks in the theme's link colour)."""
    import re

    from pptx.opc.constants import RELATIONSHIP_TYPE as RT

    theme = deck.slide_master.part.part_related_by(RT.THEME)
    colour = f'<a:srgbClr val="{hex_value.lstrip("#")}"/>'.encode()
    blob = theme.blob
    for tag in (b"hlink", b"folHlink"):
        blob = re.sub(
            rb"<a:" + tag + rb">.*?</a:" + tag + rb">",
            b"<a:" + tag + b">" + colour + b"</a:" + tag + b">",
            blob,
            flags=re.DOTALL,
        )
    theme._blob = blob


def write_deck(folder: Path, pptx: bool = True, assets_root: Path | None = None) -> list[Path]:
    """Build deck.html (and deck.pptx) next to a run's cases.json and result.json.

    Screenshot paths in run.json are relative to `assets_root` (recordings/); the deck
    rewrites them relative to its own folder so the HTML works when served as files."""
    case = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    run_path = folder / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else None
    slides = build_slides(case, result, run)
    if assets_root is not None:
        prefix = Path(os.path.relpath(assets_root, folder)).as_posix()
        for slide in slides:
            if slide.shot:
                slide.shot = f"{prefix}/{slide.shot}"
    out = [folder / "deck.html"]
    write_text(out[0], render_html(slides, deck_title(case, run, folder.name)))
    if pptx:
        try:
            render_pptx(slides, folder, folder / "deck.pptx")
            out.append(folder / "deck.pptx")
        except ImportError:
            pass  # .pptx needs python-pptx; the HTML deck is always written
    return out


def deck_title(case: dict[str, Any], run: dict[str, Any] | None, fallback: str) -> str:
    week = case.get("week")
    tz = ZoneInfo(case.get("timezone") or "UTC")
    if run is not None and is_partial(week, run, tz):
        return f"{BRAND} · {week} so far"
    meeting = meeting_label(week)
    return f"{BRAND} · Deck for {meeting}" if meeting else f"{BRAND} · {fallback}"


# ---- Helpers ---------------------------------------------------------------------------------


def week_monday(week: str | None) -> date | None:
    try:
        year, number = week.split("-W")
        return date.fromisocalendar(int(year), int(number), 1)
    except (AttributeError, ValueError):
        return None


def week_label(week: str | None) -> str:
    """'2026-W40' -> 'Week of Sep 28'."""
    monday = week_monday(week)
    return f"Week of {monday:%b} {monday.day}" if monday else ""


def meeting_label(week: str | None, short: bool = False) -> str:
    """The Monday the deck is presented: '2026-W43' -> 'Monday, Oct 26' ('Mon, Oct 26')."""
    monday = week_monday(week)
    if monday is None:
        return ""
    meeting = monday + timedelta(days=7)
    day = meeting.strftime("%a" if short else "%A")
    return f"{day}, {meeting:%b} {meeting.day}"


def week_range(week: str | None) -> str:
    """The days the week covers: 'Oct 19–25', across months 'Sep 28–Oct 4'."""
    monday = week_monday(week)
    if monday is None:
        return ""
    sunday = monday + timedelta(days=6)
    end = f"{sunday.day}" if sunday.month == monday.month else f"{sunday:%b} {sunday.day}"
    return f"{monday:%b} {monday.day}–{end}"


def date_span(days: list[str]) -> str:
    """'Oct 23', 'Oct 14–18', 'Sep 30–Oct 4' from ISO dates."""
    ordered = sorted(date.fromisoformat(d) for d in days)
    lo, hi = ordered[0], ordered[-1]
    if lo == hi:
        return f"{lo:%b} {lo.day}"
    end = f"{hi.day}" if hi.month == lo.month else f"{hi:%b} {hi.day}"
    return f"{lo:%b} {lo.day}–{end}"


def clock(moment: datetime) -> str:
    """'Mon 26 Oct, 06:30'."""
    return f"{moment:%a} {moment.day} {moment:%b}, {moment:%H:%M}"


def short_date(ts: str, tz: ZoneInfo) -> str:
    try:
        moment = parse_iso(ts).astimezone(tz)
    except ValueError:
        return ts
    return f"{moment:%b} {moment.day}"


def bare_url(url: str | None) -> str:
    value = (url or "").replace("https://", "").replace("http://", "")
    return value.removeprefix("www.").rstrip("/")


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def join_and(values: list[str]) -> str:
    if len(values) < 2:
        return "".join(values)
    return ", ".join(values[:-1]) + " and " + values[-1]


def order(competitor: str) -> tuple[int, str]:
    known = list(DEFAULT_COMPETITORS)
    return (known.index(competitor) if competitor in known else len(known), competitor)
