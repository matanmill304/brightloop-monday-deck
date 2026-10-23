"""One collection run for one reporting week.

  brightloop collect                              # this week, live (Wayback when blocked)
  brightloop collect --week 2026-W40 --archived   # a past week, from the Wayback Machine

For each of Maya's pages (Lovable, Replit, Bolt × pricing page, homepage):
  1. capture now (live; the latest Wayback copy inside the week if blocked);
  2. baseline = our latest earlier snapshot, else the latest Wayback copy before the week;
  3. compare; each change becomes one short event signal in the brief's input shape.

Writes recordings/<week>/:
  snapshots/*.json + *.jpg  page text + screenshots (evidence; never in the input)
  cases.json                the week's event signals, same shape as the reviewers' file
  result.json               the pipeline's output on cases.json (same pipeline as file mode)
  run.json                  per page: status, snapshots, screenshots, signal ids (for the deck)
and appends one line to recordings/runlog.jsonl.
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


def week_bounds(label: str) -> tuple[datetime, datetime]:
    year, number = (int(x) for x in re.fullmatch(r"(\d{4})-W(\d{1,2})", label).groups())
    start = datetime.combine(date.fromisocalendar(year, number, 1), time.min, ZoneInfo(TIMEZONE))
    return start, start + timedelta(days=7)


def current_week() -> str:
    year, number, _ = datetime.now(ZoneInfo(TIMEZONE)).isocalendar()
    return f"{year}-W{number:02d}"


def collect(week: str, root: Path, archived: bool = False) -> dict[str, Any]:
    started = now_iso()
    tz = ZoneInfo(TIMEZONE)
    start, end = week_bounds(week)
    now = datetime.now(UTC)
    out_dir = root / week
    (out_dir / "snapshots").mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    counters = {"pricing": 0, "home": 0}

    capturer = Capturer(out_dir / "snapshots")
    try:
        for competitor, page, url in targets():
            entry: dict[str, Any] = {"competitor": competitor, "page": page, "url": url}
            current = None if archived else capturer.live(competitor, page, url)
            if current is None:
                if not archived:
                    entry["note"] = (
                        "live page blocked or empty: used the Wayback Machine (not bypassed)"
                    )
                current = capturer.archived(competitor, page, url, start, min(end, now))
            previous = earlier_snapshot(root, week, competitor, page, start) or capturer.archived(
                competitor, page, url, start - BASELINE_LOOKBACK, start
            )
            entry["current"] = save(current, out_dir)
            entry["previous"] = save(previous, out_dir)

            if current is None:
                entry["status"] = "not-captured"
            elif previous is None:
                entry["status"] = "first-snapshot"
            else:
                entry["status"], sentences = page_events(previous, current, tz)
                entry["signal_ids"] = []
                for text in sentences:
                    counters[page] += 1
                    signal = to_signal(current, text, week, counters[page])
                    signals.append(signal)
                    entry["signal_ids"].append(signal["id"])
            pages.append(entry)
    finally:
        capturer.close()

    case = {
        "week": week,
        "timezone": TIMEZONE,
        "brand": BRAND,
        "config": {"utm_source": "brightloop"},
        "output": {"cta_required_per_item": True},
        "signals": signals,
    }
    result = run_pipeline(case)
    run = {
        "week": week,
        "started_at": started,
        "finished_at": now_iso(),
        "mode": "archived" if archived else "live",
        "pages": pages,
    }
    write_json(out_dir / "cases.json", case)
    write_json(out_dir / "result.json", result)
    write_json(out_dir / "run.json", run)
    write_deck(out_dir)
    summary = {
        **{k: run[k] for k in ("week", "started_at", "finished_at", "mode")},
        "pages": {f"{p['competitor']} {p['page']}": p["status"] for p in pages},
        "signals": len(signals),
        "items": len(result["items"]),
        "skipped": len(result["skipped"]),
        "errors": result["run"]["errors"],
    }
    with (root / "runlog.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return summary


def to_signal(snap: Snapshot, text: str, week: str, n: int) -> dict[str, Any]:
    """The brief's input shape and nothing more: id, type, competitor, source, ts, text."""
    prefix, kind = ("pr", "pricing") if snap.page == "pricing" else ("sg", "launch")
    return {
        "id": f"{prefix}-{int(week[-2:])}{n:02d}",
        "type": kind,
        "competitor": snap.competitor,
        "source": re.sub(r"^https?://(www\.)?", "", snap.url).rstrip("/"),
        "ts": snap.captured_at.replace("+00:00", "Z"),
        "text": text,
    }


def save(snap: Snapshot | None, out_dir: Path) -> dict[str, Any] | None:
    """Write a snapshot's JSON next to its screenshot; return what run.json records about it."""
    if snap is None:
        return None
    stamp = re.sub(r"\D", "", snap.captured_at)[:12]
    name = f"{slug(snap.competitor)}-{snap.page}-{stamp}"
    path = out_dir / "snapshots" / f"{name}.json"
    if not path.exists():
        write_json(path, snap.to_json())
    return {
        "captured_at": snap.captured_at,
        "method": snap.method,
        "snapshot": f"snapshots/{path.name}",
        "screenshot": f"snapshots/{snap.screenshot}" if snap.screenshot else None,
        "archive_url": snap.archive_url,
    }


def earlier_snapshot(
    root: Path, week: str, competitor: str, page: str, before: datetime
) -> Snapshot | None:
    """Our own latest snapshot of this page from before the week (no Wayback needed)."""
    candidates = []
    for path in root.glob(f"*-W*/snapshots/{slug(competitor)}-{page}-*.json"):
        if path.parent.parent.name >= week:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if datetime.fromisoformat(data["captured_at"]) < before:
            candidates.append((data["captured_at"], path, data))
    if not candidates:
        return None
    _, path, data = max(candidates)
    snap = Snapshot(**data)
    if snap.screenshot and not snap.screenshot.startswith("../"):
        snap.screenshot = f"../../{path.parent.parent.name}/snapshots/{snap.screenshot}"
    return snap


def write_json(path: Path, data: Any) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
