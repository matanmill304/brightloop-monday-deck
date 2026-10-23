"""tests/fixtures/edge_cases.json: one signal per tricky situation, with its expected fate.

The same file can be traced signal by signal with `brightloop explain`.
"""

import json
from pathlib import Path

from brightloop.pipeline import run_pipeline

CASE = json.loads((Path(__file__).parent / "fixtures" / "edge_cases.json").read_text("utf-8"))
OUT = run_pipeline(CASE)
ITEMS = {sid: item for item in OUT["items"] for sid in item["source_ids"]}
SKIPS = {s["id"]: s["reason"] for s in OUT["skipped"]}

# Official pages (and the competitor's own announcements) only; see select.py.
EXPECTED_ITEMS = {
    "real-price",  # stated on Lovable's pricing page
    "real-tier",  # new tier stated on Bolt's pricing page
    "named-page",  # "Replit pricing page" with no URL: linked to the official page
    "same-event-press",  # TechCrunch on the same change: joins real-price's item
    "messaging",  # homepage headline change on lovable.dev
    "dst-sunday-late",  # Sunday 23:30 local, still inside the week across the DST change
    "odd-shapes",  # other field names, nested source and title, epoch time
    "secret",  # a real change; the leaked key is redacted
    "real-limits",  # Replit's own X account: announced, "check the page"
    "ad-offer",  # Bolt's own ad with a price: announced, "check the page"
}
EXPECTED_SKIPS = {
    "funding": "isn't a pricing",
    "feature": "Noa",
    "mislabeled": "Noa",
    "collision-domain": "is not its site",
    "collision-words": "shares the name",
    "rumor": "rumor",
    "no-competitor": "No competitor",
    "before-week": "before the reporting week",
    "after-week": "after the reporting week",
    "no-text": "No text",
    "contradiction": "verify on https://lovable.dev/pricing",
    "sponsored": "sponsored",
    "injection": "instructions aimed at AI",
    "no-link": "verify on https://bolt.new/pricing",
}


def test_items_are_exactly_the_expected_ones():
    assert set(ITEMS) == EXPECTED_ITEMS


def test_each_skip_has_the_expected_reason():
    for sid, words in EXPECTED_SKIPS.items():
        assert words in SKIPS[sid], (sid, SKIPS[sid])


def test_price_change_without_old_value_says_so():
    assert any("previous price not stated" in c for c in ITEMS["named-page"].get("caveats", []))


def test_input_problems_are_reported_not_hidden():
    errors = " ".join(OUT["run"]["errors"])
    assert "duplicate id 'real-price'" in errors
    assert "no usable id" in errors and "not an object" in errors


def test_nothing_unsafe_leaks():
    text = json.dumps(OUT)
    assert "sk-live-abcdefghijklmnop" not in text
    assert "bl_demo_4c19e2" not in text
    assert "Ignore all previous" not in text
