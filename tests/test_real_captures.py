"""Regression tests from real captures in recordings/days/ (stored snapshots never change).

Each test is a case the first version got wrong on a real competitor page.
"""

import json
from pathlib import Path
from zoneinfo import ZoneInfo

from brightloop.change import page_state
from brightloop.collect.capture import Snapshot
from brightloop.collect.events import page_events

DAYS = Path(__file__).resolve().parents[1] / "recordings" / "days"
TZ = ZoneInfo("Asia/Jerusalem")
LITE = (
    '"Bolt Lite ($9/month, invite only during the research preview) is powered by Bolt Forge '
    'and is the only AI mode on that plan."'
)


def snap(day: str, page: str) -> Snapshot:
    return Snapshot(**json.loads((DAYS / day / f"{page}.json").read_text(encoding="utf-8")))


def events(before: str, after: str, page: str):
    return page_events(snap(before, page), snap(after, page), TZ)


def test_archived_yearly_view_vs_live_monthly_view_is_not_a_price_change():
    # v1 told leadership "Replit homepage: $90 -> $0" and "Replit pricing: $90 -> $100".
    for page in ("replit-pricing", "replit-home"):
        assert events("2026-10-21", "2026-10-23", page) == ("first-snapshot", [])


def test_plan_prices_are_read_plan_by_plan():
    assert page_state(snap("2026-10-23", "replit-pricing").text).prices == {
        "Core": "$20",
        "Pro": "$100",
    }
    bolt_live = page_state(snap("2026-10-23", "bolt-pricing").text)
    assert bolt_live.prices == {"Free": "$0/month", "Pro": "$25", "Teams": "$30"}
    assert page_state(snap("2026-10-22", "bolt-pricing").text).billing == "yearly"


def test_prices_drawn_without_a_currency_sign_are_read():
    # Lovable draws "$" as an image: the text says "Pro … 25 / month". v1 found no prices.
    prices = page_state(snap("2026-10-23", "lovable-pricing").text).prices
    assert prices == {"Pro": "$25/ month", "Business": "$50"}


def test_the_archives_own_error_page_is_never_compared():
    # Sep 28's "copy" of bolt.new/pricing is the Wayback Machine's "Temporarily Offline" page.
    assert page_state(snap("2026-09-28", "bolt-pricing").text).error_page
    assert events("2026-09-28", "2026-09-29", "bolt-pricing") == ("first-snapshot", [])


def test_a_footnote_with_a_price_is_reported_in_the_pages_own_words():
    # v1: one item quoting a lowercase fragment ("bolt lite $9/month, invite only during…").
    assert events("2026-09-29", "2026-09-30", "bolt-pricing") == (
        "changed",
        [f"New on the pricing page: {LITE}"],
    )
    assert events("2026-09-30", "2026-10-01", "bolt-pricing") == (
        "changed",
        [f"No longer on the pricing page: {LITE}"],
    )


def test_an_edited_line_is_one_change_not_two():
    edit = (
        'Changed on the pricing page: "$20 towards most powerful models" → '
        '"$20 towards more powerful models"'
    )
    assert events("2026-10-05", "2026-10-07", "replit-pricing") == ("changed", [edit])


def test_bolts_october_allowance_change():
    status, sentences = events("2026-10-16", "2026-10-20", "bolt-pricing")
    assert status == "changed"
    assert sentences == [
        'Changed on the pricing page: "1M tokens per month" → "1M tokens/month to try Bolt"',
        'New on the pricing page: "10M tokens/month, rollover included"',
        'No longer on the pricing page: "300K tokens daily limit"',
        'No longer on the pricing page: "Start at 10M tokens per month"',
    ]
