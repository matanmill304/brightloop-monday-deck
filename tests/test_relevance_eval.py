"""Is the keyless relevance check overfitted to our sample? Measured on real headlines.

Real Google News headlines about the competitors (Oct 2026), labeled by hand as a
pricing/packaging event or not. Guides, reviews, comparisons and name collisions
(Bolt scooters, Chevy Bolt, "lovable" the adjective) were left out: test cases are
things that happened, about the competitor named.

- headlines_dev.json was used to design the rules.
- headlines_holdout.json was labeled afterwards and scored once, untouched by tuning.
"""

import json
from pathlib import Path

import pytest

from brightloop.decide import pricing_score

EVAL = Path(__file__).parent / "eval"


def score(name):
    rows = json.loads((EVAL / name).read_text(encoding="utf-8"))
    tp = fp = fn = 0
    for row in rows:
        predicted = pricing_score(row["title"]) >= 2
        gold = row["label"] == "pricing"
        tp += predicted and gold
        fp += predicted and not gold
        fn += gold and not predicted
    return tp / (tp + fp), tp / (tp + fn)


@pytest.mark.parametrize(
    ("name", "min_precision", "min_recall"),
    [("headlines_dev.json", 0.95, 0.9), ("headlines_holdout.json", 0.95, 0.8)],
)
def test_relevance_on_real_headlines(name, min_precision, min_recall):
    precision, recall = score(name)
    # Precision matters most: a non-pricing item in Maya's deck costs her trust.
    assert precision >= min_precision, f"{name}: precision {precision:.2f}"
    assert recall >= min_recall, f"{name}: recall {recall:.2f}"


@pytest.mark.parametrize(
    "text",
    [
        "Lovable raises $400 million at $13.3 billion valuation",
        "Replit Closes $250 Million in Funding to Build on Customer Momentum",
        "Lovable's annual revenue surpasses $600M",
        "Lovable Opens Boston Office, Plans To Hire Dozens",
        "Cursor's Popularity Has Come at a Cost",
    ],
)
def test_money_and_plans_that_are_not_pricing(text):
    assert pricing_score(text) < 2
