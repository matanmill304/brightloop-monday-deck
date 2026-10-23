"""Vercel function: POST a cases.json, get result.json. Same pipeline as the CLI; no keys.

Every answer to a POST is the output wrapper; a body that can't be read gives the empty
wrapper with the reason in run.errors.
"""

import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brightloop.contract import empty_output, to_json
from brightloop.pipeline import run_bytes

MAX_BYTES = 5_000_000


def respond(content_length, read) -> tuple:
    """(status, body) for a POST with this Content-Length header; `read(n)` reads the body."""
    try:
        length = int(content_length or 0)
    except ValueError:
        length = -1
    if length < 0:
        return 400, empty_output("input: the request has no valid Content-Length; nothing read")
    if length > MAX_BYTES:
        return 413, empty_output("input: the file is over 5 MB; nothing read")
    return 200, run_bytes(read(length), "the uploaded file")


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self._send(*respond(self.headers.get("Content-Length"), self.rfile.read))

    def do_GET(self) -> None:
        self._send(200, {"usage": "POST a cases.json body to this URL to get result.json"})

    def _send(self, status: int, body: dict) -> None:
        data = to_json(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
