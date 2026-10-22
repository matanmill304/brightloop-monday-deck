"""One collection run for one reporting week.

  brightloop collect                      # this week: live captures, last week as baseline
  brightloop collect --week 2026-W40 --archived   # a past week, rebuilt from the Wayback Machine

Writes recordings/<week>/: cases.json (same format as the reviewers' file), result.json
(the same pipeline's output), screenshots, and appends one line to recordings/runlog.jsonl.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from brightloop.collect.capture import Capturer, Snapshot, now_iso, slug
from brightloop.competitors import COMPETITORS
from brightloop.pipeline import run_pipeline

TIMEZONE = "Asia/Jerusalem"
MAYA_COMPETITORS = ("Lovable", "Replit", "Bolt")  # the ones in her Monday deck
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
    tz = ZoneInfo(TIMEZONE)
    start = datetime.combine(date.fromisocalendar(year, number, 1), time.min, tz)
    return start, start + timedelta(days=7)


def current_week() -> str:
    year, number, _ = datetime.now(ZoneInfo(TIMEZONE)).isocalendar()
    return f"{year}-W{number:02d}"


def collect(week: str, root: Path, archived: bool = False) -> dict[str, Any]:
    """Capture every page for `week` plus a baseline from the week before; run the pipeline."""
    started = now_iso()
    start, end = week_bounds(week)
    out_dir = root / week
    out_dir.mkdir(parents=True, exist_ok=True)
    log: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []

    capturer = Capturer(out_dir)
    try:
        for competitor, page, url in targets():
            entry: dict[str, Any] = {"competitor": competitor, "page": page, "url": url}
            current = None
            if not archived:
                current = capturer.live(competitor, page, url)
                if current is None:
                    entry["live"] = "blocked or empty: used the Wayback Machine (not bypassed)"
            if current is None:
                moment = min(end - timedelta(minutes=1), datetime.now(UTC))
                current = capturer.archived(competitor, page, url, moment)
            baseline = previous_snapshot(root, week, competitor, page) or capturer.archived(
                competitor, page, url, start - timedelta(minutes=1)
            )
            for label, snap in (("baseline", baseline), ("current", current)):
                if snap is None:
                    entry[label] = "not available"
                    continue
                entry[label] = f"{snap.method} {snap.captured_at}"
                signals.append(to_signal(snap))
            log.append(entry)
    finally:
        capturer.close()

    signals = dedupe(signals)
    case = {
        "week": week,
        "timezone": TIMEZONE,
        "brand": BRAND,
        "config": {"utm_source": "brightloop"},
        "output": {"cta_required_per_item": True},
        "signals": signals,
    }
    write_json(out_dir / "cases.json", case)
    result = run_pipeline(case)
    write_json(out_dir / "result.json", result)
    run_entry = {
        "started_at": started,
        "finished_at": now_iso(),
        "week": week,
        "mode": "archived" if archived else "live",
        "pages": log,
        "signals": len(signals),
        "items": len(result["items"]),
        "skipped": len(result["skipped"]),
        "errors": result["run"]["errors"],
    }
    with (root / "runlog.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(run_entry, ensure_ascii=False) + "\n")
    return run_entry


def to_signal(snap: Snapshot) -> dict[str, Any]:
    stamp = re.sub(r"\D", "", snap.captured_at)[:12]
    return {
        "id": f"{slug(snap.competitor)}-{snap.page}-{stamp}",
        "type": "pricing" if snap.page == "pricing" else "launch",
        "competitor": snap.competitor,
        "source": snap.url,
        "ts": snap.captured_at,
        "text": snap.text,
        "snapshot": True,  # a captured page: a state to compare, never a statement of a change
        "headline": snap.headline,
        "capture": snap.method,
        "archive_url": snap.archive_url,
        "screenshot": snap.screenshot,
        "notes": snap.notes,
    }


def previous_snapshot(root: Path, week: str, competitor: str, page: str) -> Snapshot | None:
    """The latest snapshot of this page from an earlier recorded week, if we have one."""
    earlier = sorted(p for p in root.glob("*-W*/cases.json") if p.parent.name < week)
    for path in reversed(earlier):
        case = json.loads(path.read_text(encoding="utf-8"))
        mine = [
            s
            for s in case["signals"]
            if s.get("competitor") == competitor
            and s.get("id", "").startswith(f"{slug(competitor)}-{page}-")
        ]
        if mine:
            s = max(mine, key=lambda s: s["ts"])
            return Snapshot(
                competitor,
                page,
                s["source"],
                s["ts"],
                s.get("capture", "live"),
                s["text"],
                s.get("headline", ""),
                None,
                s.get("archive_url"),
                [f"baseline from the {path.parent.name} run"],
            )
    return None


def dedupe(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for s in signals:
        if s["id"] not in seen:
            seen.add(s["id"])
            out.append(s)
    return out


def write_json(path: Path, data: Any) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
