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
    # The summary, then one slide per page; the summary is never counted as a changed page.
    assert len(data["slides"]) == 7 and data["slides"][0]["status"] == "summary"
    assert data["changed"] == sum(s["status"] == "changed" for s in data["slides"][1:])
    assert all((RECORDINGS / s["shot"]).exists() for s in data["slides"] if s["shot"])


@pytest.mark.skipif(not WEEKS, reason="no recorded week")
def test_a_rebuilt_week_is_identical_to_the_stored_one():
    """What the Test page's rebuild check compares: the stored week's slides (site data) and
    the slides /api/deck computes again from the captures."""
    import json

    from brightloop.deck import week_view

    for week in WEEKS:
        folder = RECORDINGS / "weeks" / week
        stored = week_view(
            *(
                json.loads((folder / n).read_text(encoding="utf-8"))
                for n in ("cases.json", "result.json", "run.json")
            )
        )
        fresh = load_api("deck").deck_data(week, RECORDINGS)
        if not stored["partial"]:
            assert fresh["slides"] == stored["slides"], week


def test_a_week_without_captures_gets_a_reason_not_a_crash():
    api = load_api("deck")
    assert api.captured_days("2026-W99", RECORDINGS) is None  # no such week: 400
    assert api.captured_days("2026-W39", RECORDINGS) == []  # before the first capture: 404
    assert len(api.captured_days("2026-W42", RECORDINGS)) == 7
