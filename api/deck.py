"""Vercel function: rebuild a week's deck from the daily captures. GET /api/deck?week=2026-W43

Same code as the Monday run (assemble_week -> pipeline -> slides), computed on request and
returned in the same shape as the app's stored week, so the Test page can compare the two.
Nothing is written. Screenshot paths are relative to the site root.
"""

import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brightloop.collect.run import assemble_week, last_complete_week
from brightloop.deck import week_view

WEEK = re.compile(r"^\d{4}-W\d{2}$")


def deck_data(week: str, recordings: Path) -> dict:
    started = time.perf_counter()
    case, result, run = assemble_week(week, recordings)
    view = week_view(case, result, run)
    view["seconds"] = round(time.perf_counter() - started, 1)
    return view


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        week = (parse_qs(urlparse(self.path).query).get("week") or [last_complete_week()])[0]
        if not WEEK.match(week):
            self._send(400, {"error": "week must look like 2026-W43"})
            return
        self._send(200, deck_data(week, ROOT / "recordings"))

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
