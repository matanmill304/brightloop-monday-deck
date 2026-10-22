"""tests/fixtures/edge_cases.json: one signal per tricky situation, with its expected fate.

The same file is traced signal by signal in the review pack (`brightloop explain`).
"""

import json
from pathlib import Path

from brightloop.pipeline import run_pipeline

CASE = json.loads((Path(__file__).parent / "fixtures" / "edge_cases.json").read_text("utf-8"))
OUT = run_pipeline(CASE)
ITEMS = {sid: item for item in OUT["items"] for sid in item["source_ids"]}
SKIPS = {s["id"]: s["reason"] for s in OUT["skipped"]}

EXPECTED_ITEMS = {
    "real-price",
    "same-event-press",
    "real-tier",
    "real-limits",
    "named-page",
    "messaging",
    "dst-sunday-late",
    "odd-shapes",
    "secret",
    "ad-offer",
}
EXPECTED_SKIPS = {
    "funding": "Not a pricing",
    "feature": "Noa",
    "mislabeled": "Labeled pricing",
    "collision-domain": "not Bolt's site",
    "collision-words": "shares the name",
    "rumor": "rumor",
    "no-competitor": "No competitor",
    "before-week": "before the reporting week",
    "after-week": "after the reporting week",
    "no-text": "No text",
    "contradiction": "contradicts the official",
    "sponsored": "sponsored",
    "injection": "instructions aimed at AI",
    "no-link": "no link",
}


def test_items_are_exactly_the_expected_ones():
    assert set(ITEMS) == EXPECTED_ITEMS


def test_each_skip_has_the_expected_reason():
    for sid, words in EXPECTED_SKIPS.items():
        assert words in SKIPS[sid], (sid, SKIPS[sid])


def test_same_event_from_two_sources_is_one_item():
    assert ITEMS["real-price"] is ITEMS["same-event-press"]


def test_input_problems_are_reported_not_hidden():
    errors = " ".join(OUT["run"]["errors"])
    assert "duplicate id 'real-price'" in errors
    assert "no usable id" in errors and "not an object" in errors


def test_nothing_unsafe_leaks():
    text = json.dumps(OUT)
    assert "sk-live-abcdefghijklmnop" not in text
    assert "bl_demo_4c19e2" not in text
    assert "Ignore all previous" not in text
