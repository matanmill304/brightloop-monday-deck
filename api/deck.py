"""Vercel function: build a week's deck from the daily captures, on request.

    GET /api/deck?week=2026-W43                 the week's slides as data (the Test page's check)
    GET /api/deck?week=2026-W44&format=pptx     the deck as .pptx, from the captures so far
    GET /api/deck?week=2026-W44&format=html     the print view (save as PDF)

Same code as the Monday run (assemble_week -> pipeline -> slides). Nothing is written. The
Monday deck is built once by the daily job; this is the app's "Build deck now" for the week
in progress. It uses the captures already stored (the last daily run): Vercel can't run
the browser that captures pages.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brightloop.collect.run import assemble_week, last_complete_week, week_bounds
from brightloop.deck import (
    build_slides,
    deck_title,
    is_partial,
    meeting_iso,
    render_html,
    render_pptx,
    week_view,
)

WEEK = re.compile(r"^\d{4}-W\d{2}$")
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def captured_days(week: str, recordings: Path) -> list[str] | None:
    """The days of the week that have captures; None for a week that doesn't exist (2026-W99)."""
    try:
        start, _end = week_bounds(week)
    except ValueError:
        return None
    days = [(start + timedelta(days=n)).date().isoformat() for n in range(7)]
    return [day for day in days if (recordings / "days" / day / "day.json").exists()]


def deck_data(week: str, recordings: Path) -> dict:
    started = time.perf_counter()
    case, result, run = assemble_week(week, recordings)
    view = week_view(case, result, run)
    view["seconds"] = round(time.perf_counter() - started, 1)
    return view


def deck_file(week: str, recordings: Path, fmt: str) -> tuple[bytes, str, str]:
    """(body, content type, download name) for the deck built now."""
    case, result, run = assemble_week(week, recordings)
    slides = build_slides(case, result, run)
    tz = ZoneInfo(case.get("timezone") or "UTC")
    name = f"competitor-deck-{meeting_iso(week)}" + ("-so-far" if is_partial(week, run, tz) else "")
    if fmt == "html":
        for slide in slides:  # screenshots are served from the site root (/days/…)
            if slide.shot:
                slide.shot = f"/{slide.shot}"
        html = render_html(slides, deck_title(case, run, week))
        return html.encode("utf-8"), "text/html; charset=utf-8", f"{name}.html"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "deck.pptx"
        render_pptx(slides, recordings, path)
        return path.read_bytes(), PPTX, f"{name}.pptx"


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        week = (query.get("week") or [last_complete_week()])[0]
        fmt = (query.get("format") or ["json"])[0]
        if not WEEK.match(week):
            self._send(400, {"error": "week must look like 2026-W43"})
            return
        if fmt not in ("json", "pptx", "html"):
            self._send(400, {"error": "format must be json, pptx or html"})
            return
        days = captured_days(week, ROOT / "recordings")
        if days is None:
            self._send(400, {"error": f"there is no week {week}"})
            return
        if not days:
            self._send(404, {"error": f"nothing was captured in {week}"})
            return
        if fmt == "json":
            self._send(200, deck_data(week, ROOT / "recordings"))
            return
        try:
            body, kind, name = deck_file(week, ROOT / "recordings", fmt)
        except ImportError:
            self._send(501, {"error": "this server can't build .pptx files (python-pptx missing)"})
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if fmt == "pptx":
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.end_headers()
        self.wfile.write(body)

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
