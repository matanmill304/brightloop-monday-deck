"""Step 3: the reporting week, computed in the input's timezone."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from brightloop.normalize import Signal

DEFAULT_TZ = "UTC"


def resolve_timezone(value: object, errors: list[str]) -> tzinfo:
    if isinstance(value, str) and value.strip():
        try:
            return ZoneInfo(value.strip())
        except (ZoneInfoNotFoundError, ValueError):
            errors.append(f"input: unknown timezone {value!r}; using UTC")
    return ZoneInfo(DEFAULT_TZ)


@dataclass
class Week:
    label: str
    start: datetime  # UTC, inclusive
    end: datetime  # UTC, exclusive


def resolve_week(value: object, tz: tzinfo, errors: list[str]) -> Week | None:
    """Parse an ISO week like 2026-W43. No week means no date filtering."""
    if value is None or value == "":
        return None
    match = re.fullmatch(r"\s*(\d{4})-?W(\d{1,2})\s*", str(value), re.IGNORECASE)
    if not match:
        errors.append(f"input: could not read week {value!r}; no date filtering applied")
        return None
    year, number = int(match.group(1)), int(match.group(2))
    try:
        monday = date.fromisocalendar(year, number, 1)
    except ValueError:
        errors.append(f"input: week {value!r} does not exist; no date filtering applied")
        return None
    start = datetime.combine(monday, time.min, tz).astimezone(UTC)
    end = datetime.combine(monday + timedelta(days=7), time.min, tz).astimezone(UTC)
    return Week(label=f"{year}-W{number:02d}", start=start, end=end)


def window_reason(signal: Signal, week: Week | None) -> str | None:
    """Return a skip reason if the signal falls outside the week, else None."""
    if week is None:
        return None
    if signal.first_seen or signal.last_seen:
        first = signal.first_seen or signal.ts or signal.last_seen
        last = signal.last_seen or signal.ts or signal.first_seen
        if last < week.start:
            return f"Stopped before the reporting week ({week.label})."
        if first >= week.end:
            return f"Starts after the reporting week ({week.label})."
        return None
    if signal.ts is None:
        return None
    if signal.ts < week.start:
        return f"Happened before the reporting week ({week.label})."
    if signal.ts >= week.end:
        return f"Dated after the reporting week ({week.label})."
    return None
