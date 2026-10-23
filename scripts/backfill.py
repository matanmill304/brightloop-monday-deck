"""One-time history: collect each past day from the Wayback Machine, then build the weeks.

    python scripts/backfill.py --weeks 3

Collects day by day, oldest first (each day is compared with the day before), then today
live, then builds each complete week plus the current one. Slow on purpose: the Wayback
Machine rate-limits, and the collector backs off politely.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from brightloop.collect.run import TZ, build_week, collect_day

ROOT = Path("recordings")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", type=int, default=3)
    args = parser.parse_args()

    today = datetime.now(TZ).date()
    this_monday = today - timedelta(days=today.weekday())
    first = this_monday - timedelta(weeks=args.weeks)
    day = first
    while day < today:
        if not (ROOT / "days" / day.isoformat() / "day.json").exists():
            print(json.dumps(collect_day(day, ROOT, archived=True)), flush=True)
        day += timedelta(days=1)
    print(json.dumps(collect_day(today, ROOT)), flush=True)

    monday = first
    while monday <= this_monday:
        year, number, _ = monday.isocalendar()
        print(json.dumps(build_week(f"{year}-W{number:02d}", ROOT)), flush=True)
        monday += timedelta(weeks=1)


if __name__ == "__main__":
    main()
