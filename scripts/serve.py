"""Serve the web app locally the way Vercel does: public/ as static files + the api/ functions.

python scripts/build_site.py && python scripts/serve.py      # http://localhost:8044
"""

from __future__ import annotations

import importlib.util
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8044


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"api_{name}", ROOT / "api" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.handler


API = {"/api/run": load("run"), "/api/deck": load("deck")}


class Handler(SimpleHTTPRequestHandler):
    def _api(self):
        return API.get(self.path.split("?")[0])

    def do_GET(self) -> None:
        if api := self._api():
            api.do_GET(self)
        else:
            super().do_GET()

    def do_POST(self) -> None:
        if api := self._api():
            api.do_POST(self)
        else:
            self.send_error(404)

    def _send(self, status: int, body: dict) -> None:  # used by the api handlers
        self._api()._send(self, status, body)


if __name__ == "__main__":
    server = ThreadingHTTPServer(
        ("127.0.0.1", PORT), partial(Handler, directory=str(ROOT / "public"))
    )
    print(f"http://localhost:{PORT}")
    server.serve_forever()
