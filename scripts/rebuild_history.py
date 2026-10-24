"""Rebuild every recorded day's signals, and every week, from the snapshots already stored.

    python scripts/rebuild_history.py [--reason "plan names and wording edits"]

Run it after the comparison rules change. No page is captured again: the snapshots in
recordings/days/ are the evidence. Each page is compared day by day with its last good
snapshot, then each week goes through the same pipeline and gets a new deck. The run log
gets one "rebuild" line with the reason, so it never contradicts the decks it shows.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brightloop.change import page_state
from brightloop.collect.capture import Snapshot, now_iso
from brightloop.collect.events import page_events
from brightloop.collect.run import (
    append_log,
    assemble_week,
    page_key,
    remove_deck,
    snapshot_ref,
    targets,
    to_signal,
    write_json,
)
from brightloop.deck import is_partial, write_deck

TZ = ZoneInfo("Asia/Jerusalem")
RECORDINGS = ROOT / "recordings"


def load(path: Path) -> Snapshot | None:
    if not path.exists():
        return None
    snap = Snapshot(**json.loads(path.read_text(encoding="utf-8")))
    return None if page_state(snap.text).error_page else snap


def rebuild_days(root: Path) -> None:
    days = sorted(p.name for p in (root / "days").iterdir() if p.is_dir())
    signals: dict[str, list] = {d: [] for d in days}
    pages: dict[tuple[str, str], dict] = {}
    for competitor, page, _url in targets():
        key = page_key(competitor, page)
        baseline_path = root / "days" / days[0] / f"{key}-baseline.json"
        previous, previous_path = load(baseline_path), baseline_path
        for day in days:
            path = root / "days" / day / f"{key}.json"
            current = load(path)
            entry = {"previous": snapshot_ref(previous, previous_path) if previous else None}
            if current is not None:
                entry["current"] = snapshot_ref(current, path)  # refreshes fields like billing
            if current is None:
                entry.update(status="not-captured", signal_ids=[])
            elif previous is None:
                entry.update(status="first-snapshot", signal_ids=[])
            else:
                status, sentences = page_events(previous, current, TZ)
                ids = []
                for text in sentences:
                    prefix = "pricing" if page == "pricing" else "launch"
                    n = sum(1 for s in signals[day] if s["type"] == prefix) + 1
                    signal = to_signal(current, text, date.fromisoformat(day), n)
                    signals[day].append(signal)
                    ids.append(signal["id"])
                entry.update(status=status, signal_ids=ids)
            pages[(day, key)] = entry
            if current is not None and entry["status"] != "failed-capture":
                previous, previous_path = current, path
    for day in days:
        folder = root / "days" / day
        write_json(folder / "signals.json", signals[day])
        day_file = folder / "day.json"
        if day_file.exists():
            data = json.loads(day_file.read_text(encoding="utf-8"))
            for p in data["pages"]:
                p.update(pages[(day, page_key(p["competitor"], p["page"]))])
            write_json(day_file, data)
        for s in signals[day]:
            print(f"{day}  {s['id']:10} {s['text']}")


def rebuild_weeks(root: Path) -> dict[str, dict[str, int]]:
    out = {}
    for folder in sorted((root / "weeks").iterdir()):
        case, result, run = assemble_week(folder.name, root)
        write_json(folder / "cases.json", case)
        write_json(folder / "result.json", result)
        write_json(folder / "run.json", run)
        if is_partial(folder.name, run, TZ):
            remove_deck(folder)  # the week in progress: deck files are made on Monday
        else:
            write_deck(folder, assets_root=root)
        out[folder.name] = {"signals": len(case["signals"]), "items": len(result["items"])}
        print(f"{folder.name}: {len(case['signals'])} signals -> {len(result['items'])} items")
    return out


def rebuild(root: Path, reason: str) -> dict:
    started = now_iso()
    rebuild_days(root)
    weeks = rebuild_weeks(root)
    entry = {
        "run": "rebuild",
        "started_at": started,
        "finished_at": now_iso(),
        "reason": reason,
        "weeks": weeks,
    }
    append_log(root, entry)
    return entry


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reason", default="comparison rules updated")
    rebuild(RECORDINGS, parser.parse_args().reason)
