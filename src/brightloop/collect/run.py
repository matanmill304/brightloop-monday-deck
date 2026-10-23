"""Daily collection and the weekly roll-up.

  brightloop collect [--date 2026-10-23] [--archived]   # daily: today's pages vs the last snapshot
  brightloop week [--week 2026-W43]                      # weekly: the week's signals -> pipeline -> deck

Daily, for each of Maya's pages (Lovable, Replit, Bolt × pricing page, homepage):
  capture the page (live; for a past day or a blocked page, that day's Wayback copy), compare
  it with our latest earlier snapshot (else the latest Wayback copy before that day), and turn
  each change into one signal in the brief's input shape, dated when we saw it.

recordings/
  days/<date>/<page>.json + .jpg   the snapshot (evidence; never part of the input)
  days/<date>/signals.json         that day's changes as signals
  days/<date>/day.json             each page's status that day
  weeks/<week>/cases.json          the week's signals: the same shape as the reviewers' file
  weeks/<week>/result.json         the same pipeline's output
  weeks/<week>/run.json            per page: status for the week, snapshots, signal ids (deck)
  weeks/<week>/deck.html, deck.pptx
  runlog.jsonl                     one line per daily and weekly run
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from brightloop.collect.capture import Capturer, Snapshot, now_iso, slug
from brightloop.collect.events import page_events
from brightloop.competitors import COMPETITORS
from brightloop.deck import write_deck
from brightloop.pipeline import run_pipeline

TIMEZONE = "Asia/Jerusalem"
TZ = ZoneInfo(TIMEZONE)
MAYA_COMPETITORS = ("Lovable", "Replit", "Bolt")  # the ones in her Monday deck
BASELINE_LOOKBACK = timedelta(days=60)
BRAND = {
    "name": "Brightloop",
    "voice": "plain, confident, no hype",
    "banned_words": ["revolutionary", "game-changing", "seamless"],
}


def targets(competitors: tuple[str, ...] = MAYA_COMPETITORS) -> list[tuple[str, str, str]]:
    out = []
    for name in competitors:
        info = COMPETITORS[name]
        out += [(name, "pricing", info["pricing_url"][0]), (name, "home", info["home_url"][0])]
    return out


def page_key(competitor: str, page: str) -> str:
    return f"{slug(competitor)}-{page}"


# ---- Daily -------------------------------------------------------------------------------------


def collect_day(day: date, root: Path, archived: bool = False) -> dict[str, Any]:
    started = now_iso()
    day_start = datetime.combine(day, time.min, TZ)
    day_end = min(day_start + timedelta(days=1), datetime.now(UTC))
    live = not archived and day == datetime.now(TZ).date()
    folder = root / "days" / day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    pages, signals = [], []
    counters = {"pricing": 0, "home": 0}

    capturer = Capturer(folder)
    try:
        for competitor, page, url in targets():
            key = page_key(competitor, page)
            entry: dict[str, Any] = {"competitor": competitor, "page": page, "url": url}
            current = capturer.live(competitor, page, url, name=key) if live else None
            if current is None:
                if live:
                    entry["note"] = (
                        "live page blocked or empty: used the Wayback Machine (not bypassed)"
                    )
                current = capturer.archived(competitor, page, url, day_start, day_end, name=key)
            previous, previous_ref = latest_snapshot(root, key, before=day_start)
            if previous is None:
                previous = capturer.archived(
                    competitor,
                    page,
                    url,
                    day_start - BASELINE_LOOKBACK,
                    day_start,
                    name=f"{key}-baseline",
                )
                previous_ref = save_snapshot(previous, folder, f"{key}-baseline")
            entry["current"] = save_snapshot(current, folder, key)
            entry["previous"] = previous_ref

            if current is None:
                entry["status"] = "not-captured"
            elif previous is None:
                entry["status"] = "first-snapshot"
            else:
                entry["status"], sentences = page_events(previous, current, TZ)
                entry["signal_ids"] = []
                for text in sentences:
                    counters[page] += 1
                    signal = to_signal(current, text, day, counters[page])
                    signals.append(signal)
                    entry["signal_ids"].append(signal["id"])
            pages.append(entry)
    finally:
        capturer.close()

    write_json(folder / "signals.json", signals)
    write_json(folder / "day.json", {"date": day.isoformat(), "pages": pages})
    summary = {
        "run": "daily",
        "date": day.isoformat(),
        "started_at": started,
        "finished_at": now_iso(),
        "mode": "live" if live else "archived",
        "pages": {f"{p['competitor']} {p['page']}": p["status"] for p in pages},
        "signals": len(signals),
    }
    append_log(root, summary)
    return summary


def to_signal(snap: Snapshot, text: str, day: date, n: int) -> dict[str, Any]:
    """The brief's input shape and nothing more: id, type, competitor, source, ts, text."""
    prefix, kind = ("pr", "pricing") if snap.page == "pricing" else ("sg", "launch")
    return {
        "id": f"{prefix}-{day:%m%d}{n:02d}",
        "type": kind,
        "competitor": snap.competitor,
        "source": re.sub(r"^https?://(www\.)?", "", snap.url).rstrip("/"),
        "ts": snap.captured_at.replace("+00:00", "Z"),
        "text": text,
    }


def save_snapshot(snap: Snapshot | None, folder: Path, name: str) -> dict[str, Any] | None:
    if snap is None:
        return None
    write_json(folder / f"{name}.json", snap.to_json())
    return snapshot_ref(snap, folder / f"{name}.json")


def snapshot_ref(snap: Snapshot, path: Path) -> dict[str, Any]:
    """What run files record about a snapshot; paths relative to recordings/."""
    day_folder = path.parent.name
    return {
        "captured_at": snap.captured_at,
        "method": snap.method,
        "snapshot": f"days/{day_folder}/{path.name}",
        "screenshot": f"days/{day_folder}/{snap.screenshot}" if snap.screenshot else None,
        "archive_url": snap.archive_url,
    }


def latest_snapshot(root: Path, key: str, before: datetime):
    """Our latest snapshot of a page taken before `before` (any earlier day)."""
    best = None
    for path in (root / "days").glob(f"*/{key}.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        captured = datetime.fromisoformat(data["captured_at"])
        if captured < before and (best is None or captured > best[0]):
            best = (captured, path, data)
    if best is None:
        return None, None
    _, path, data = best
    snap = Snapshot(**data)
    return snap, snapshot_ref(snap, path)


# ---- Weekly ------------------------------------------------------------------------------------


def week_bounds(label: str) -> tuple[datetime, datetime]:
    year, number = (int(x) for x in re.fullmatch(r"(\d{4})-W(\d{1,2})", label).groups())
    start = datetime.combine(date.fromisocalendar(year, number, 1), time.min, TZ)
    return start, start + timedelta(days=7)


def last_complete_week() -> str:
    year, number, _ = (datetime.now(TZ) - timedelta(days=7)).isocalendar()
    return f"{year}-W{number:02d}"


def build_week(week: str, root: Path) -> dict[str, Any]:
    """The Monday roll-up: compute the week, write its files and deck, log the run."""
    started = now_iso()
    case, result, run = assemble_week(week, root)
    run["started_at"] = started
    folder = root / "weeks" / week
    folder.mkdir(parents=True, exist_ok=True)
    write_json(folder / "cases.json", case)
    write_json(folder / "result.json", result)
    write_json(folder / "run.json", run)
    write_deck(folder, assets_root=root)
    summary = {
        "run": "weekly",
        "week": week,
        "started_at": started,
        "finished_at": run["finished_at"],
        "pages": {f"{p['competitor']} {p['page']}": p["status"] for p in run["pages"]},
        "signals": len(case["signals"]),
        "items": len(result["items"]),
        "skipped": len(result["skipped"]),
        "errors": result["run"]["errors"],
    }
    append_log(root, summary)
    return summary


def assemble_week(week: str, root: Path) -> tuple[dict, dict, dict]:
    """(cases, result, run) for a week from its days' captures. Writes nothing, so the web
    app can rebuild a week on demand."""
    started = now_iso()
    start, _end = week_bounds(week)
    days = [(start + timedelta(days=n)).date() for n in range(7)]
    signals, day_pages = [], []
    for day in days:
        folder = root / "days" / day.isoformat()
        if (folder / "signals.json").exists():
            signals += json.loads((folder / "signals.json").read_text(encoding="utf-8"))
        if (folder / "day.json").exists():
            day_pages += json.loads((folder / "day.json").read_text(encoding="utf-8"))["pages"]

    case = {
        "week": week,
        "timezone": TIMEZONE,
        "brand": BRAND,
        "config": {"utm_source": "brightloop"},
        "output": {"cta_required_per_item": True},
        "signals": signals,
    }
    result = run_pipeline(case)
    pages = []
    for competitor, page, url in targets():
        mine = [p for p in day_pages if p["competitor"] == competitor and p["page"] == page]
        captured = [p["current"] for p in mine if p.get("current")]
        ids = [sid for p in mine for sid in p.get("signal_ids", [])]
        previous, _ = latest_snapshot(root, page_key(competitor, page), before=start)
        if ids:
            status = "changed"
        elif not captured:
            status = "not-captured"
        elif previous is None and not any(p.get("previous") for p in mine):
            status = "first-snapshot"
        else:
            status = "unchanged"
        first_prev = next((p["previous"] for p in mine if p.get("previous")), None)
        pages.append(
            {
                "competitor": competitor,
                "page": page,
                "url": url,
                "status": status,
                "signal_ids": ids,
                "current": max(captured, key=lambda c: c["captured_at"]) if captured else None,
                "previous": first_prev,
                "days_captured": len(captured),
            }
        )
    run = {"week": week, "started_at": started, "finished_at": now_iso(), "pages": pages}
    return case, result, run


# ---- Files -------------------------------------------------------------------------------------


def append_log(root: Path, entry: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "runlog.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def write_json(path: Path, data: Any) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
