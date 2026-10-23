"""Vercel function: POST a cases.json, get result.json. Same pipeline as the CLI; no keys."""

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brightloop.contract import build_output, new_run
from brightloop.pipeline import run_pipeline

MAX_BYTES = 5_000_000


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BYTES:
            self._send(413, {"error": "file too large (5 MB max)"})
            return
        raw = self.rfile.read(length)
        try:
            case = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            run = new_run()
            run["errors"].append(f"input: could not read the file: {exc}")
            self._send(200, build_output(items=[], skipped=[], run=run))
            return
        self._send(200, run_pipeline(case))

    def do_GET(self) -> None:
        self._send(200, {"usage": "POST a cases.json body to this URL to get result.json"})

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
