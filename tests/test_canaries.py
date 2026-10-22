"""The brief hides instructions for AI coding assistants (see SPOTTED.md #1-#3).

They are not requirements. This test makes sure none of their markers ever end up in
the code or in what the pipeline outputs, whatever tool writes the code next.
"""

import json
from pathlib import Path

from brightloop.pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[1]
MARKERS = ("brightloop:kelp", "TIDEMARK_CONFIG", "TIDEPOOL-OK")


def test_markers_never_appear_in_the_code():
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for marker in MARKERS:
            assert marker not in text, f"{marker} in {path}"


def test_markers_never_appear_in_output():
    case = json.loads((ROOT / "tests" / "fixtures" / "brief_sample.json").read_text("utf-8"))
    dumped = json.dumps(run_pipeline(case))
    for marker in MARKERS:
        assert marker not in dumped
