"""The web app's server side: /api/deck rebuilds a week from the recordings without writing."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "recordings"
WEEKS = sorted(p.parent.name for p in RECORDINGS.glob("weeks/*/run.json"))


def load_api(name: str):
    spec = importlib.util.spec_from_file_location(f"api_{name}", ROOT / "api" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not WEEKS, reason="no recorded week")
def test_rebuild_matches_the_recorded_week_and_writes_nothing():
    week = WEEKS[-1]
    before = sorted(p.stat().st_mtime for p in RECORDINGS.rglob("*") if p.is_file())
    data = load_api("deck").deck_data(week, RECORDINGS)
    after = sorted(p.stat().st_mtime for p in RECORDINGS.rglob("*") if p.is_file())
    assert before == after
    assert len(data["slides"]) == 6
    assert all((RECORDINGS / s["shot"]).exists() for s in data["slides"] if s["shot"])
