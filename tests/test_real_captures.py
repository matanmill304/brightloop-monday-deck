"""Regression tests from real captures in recordings/days/ (stored snapshots never change).

Each test is a case the first version got wrong on a real competitor page.
"""

import json
from pathlib import Path
from zoneinfo import ZoneInfo

from brightloop.change import Change, PageState, compare, page_state, stated_change
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
        'Changed on the pricing page (Core plan): "$20 towards most powerful models" → '
        '"$20 towards more powerful models"'
    )
    assert events("2026-10-05", "2026-10-07", "replit-pricing") == ("changed", [edit])
    # On the homepage the line sits in a card we can't name ("Replit Core"): no plan, not a
    # wrong one ("Starter", the last name we could read above it).
    home = 'Changed on the homepage: "$20 towards most powerful models" → "$20 towards more'
    assert events("2026-10-05", "2026-10-07", "replit-home")[1][0].startswith(home)


def test_bolts_october_allowance_change():
    # Pairing by number in the same card: "Start at 10M…" -> "10M tokens/month…" is one edit.
    status, sentences = events("2026-10-16", "2026-10-20", "bolt-pricing")
    assert status == "changed"
    free = 'Changed on the pricing page (Free plan): "1M tokens per month" → '
    pro = 'Changed on the pricing page (Pro plan): "Start at 10M tokens per month" → '
    assert sentences == [
        free + '"1M tokens/month to try Bolt"',
        pro + '"10M tokens/month, rollover included"',
        'No longer on the pricing page (Free plan): "300K tokens daily limit"',
    ]


def test_each_line_gets_the_plan_card_it_sits_in():
    before = page_state(snap("2026-10-16", "bolt-pricing").text).plans
    after = page_state(snap("2026-10-20", "bolt-pricing").text).plans
    assert before["300K tokens daily limit"] == "Free"
    assert before["1M tokens per month"] == "Free"
    assert before["Start at 10M tokens per month"] == "Pro"
    assert after["10M tokens/month, rollover included"] == "Pro"
    # The Bolt Lite footnote sits under the Enterprise card (no price): no plan.
    lite = page_state(snap("2026-09-30", "bolt-pricing").text)
    assert LITE.strip('"') in lite.lines and LITE.strip('"') not in lite.plans


def test_two_lines_sharing_a_number_in_different_plans_are_not_one_edit():
    old = PageState(lines=["$20 towards more powerful models"], plans={})
    new = PageState(lines=["Teams get $20 of credits for each seat"], plans={})
    old.plans = {"$20 towards more powerful models": "Core"}
    new.plans = {"Teams get $20 of credits for each seat": "Teams"}
    kinds = [c.kind for c in compare(old, new)]
    assert kinds == ["line_added", "line_removed"]


def test_sentences_written_before_plans_still_parse_the_same():
    old = stated_change('Changed on the pricing page: "1M tokens per month" → "1M tokens/month"')
    assert old == Change(
        "line_changed",
        "1M tokens per month",
        "1M tokens/month",
        'Changed on the pricing page: "1M tokens per month" → "1M tokens/month"',
        None,
    )
    gone = stated_change('No longer on the pricing page: "Pro plan: 300K tokens daily limit"')
    assert (gone.kind, gone.old, gone.plan) == (
        "line_removed",
        "Pro plan: 300K tokens daily limit",
        "Pro",
    )
    new = stated_change('No longer on the pricing page (Free plan): "300K tokens daily limit"')
    assert (new.kind, new.old, new.plan) == ("line_removed", "300K tokens daily limit", "Free")
