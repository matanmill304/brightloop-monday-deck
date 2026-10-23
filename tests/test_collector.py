"""The collector's pure parts: page snapshots in, event signals in the brief's shape out."""

from zoneinfo import ZoneInfo

from brightloop.collect.capture import Snapshot
from brightloop.collect.events import page_events
from brightloop.collect.run import to_signal
from brightloop.deck import build_slides
from brightloop.pipeline import run_pipeline

TZ = ZoneInfo("Asia/Jerusalem")
PAGE = "Pricing\nFree\n$0\nPro\nFor teams building together.\n$25\n/ month\nBusiness\n$50\n/ month"


def snap(text, when="2026-10-26T04:30:00+00:00", method="live", page="pricing"):
    url = "https://lovable.dev/pricing" if page == "pricing" else "https://lovable.dev"
    return Snapshot("Lovable", page, url, when, method, text)


OLD = snap(PAGE, "2026-10-19T08:00:00+00:00")


def test_price_change_and_new_plan_become_two_sentences():
    new = snap(PAGE.replace("$25", "$30") + "\nStarter\n$9\n/ month")
    status, texts = page_events(OLD, new, TZ)
    assert status == "changed"
    assert texts == [
        "Pro plan price changed from $25/month to $30/month (was $25/month on Oct 19).",
        "New Starter plan added at $9/month (not on the page on Oct 19).",
    ]


def test_no_change():
    assert page_events(OLD, snap(PAGE), TZ) == ("unchanged", [])


def test_failed_capture_is_not_a_change():
    assert page_events(OLD, snap("Loading…"), TZ) == ("failed-capture", [])


def test_archived_vs_live_compares_prices_only():
    old = snap(PAGE + "\nLog in to see our new menu layout today", method="archived")
    status, _ = page_events(old, snap(PAGE + "\nA completely different footer text here"), TZ)
    assert status == "unchanged"


def test_signal_has_exactly_the_brief_fields_in_their_style():
    signal = to_signal(
        snap(PAGE), "Pro plan price changed from $25/month to $30/month.", "2026-W44", 1
    )
    assert signal == {
        "id": "pr-4401",
        "type": "pricing",
        "competitor": "Lovable",
        "source": "lovable.dev/pricing",
        "ts": "2026-10-26T04:30:00Z",
        "text": "Pro plan price changed from $25/month to $30/month.",
    }
    home = to_signal(snap("x", page="home"), "Homepage text changed.", "2026-W44", 2)
    assert home["id"] == "sg-4402" and home["type"] == "launch" and home["source"] == "lovable.dev"


def test_collected_signals_go_through_the_same_pipeline():
    new = snap(PAGE.replace("$25", "$30"))
    _, texts = page_events(OLD, new, TZ)
    signals = [to_signal(new, t, "2026-W44", n) for n, t in enumerate(texts, 1)]
    out = run_pipeline({"week": "2026-W44", "timezone": "Asia/Jerusalem", "signals": signals})
    assert [i["source_ids"] for i in out["items"]] == [["pr-4401"]]
    assert out["items"][0]["confidence"] == 0.9


def test_deck_shows_every_page_status():
    run = {
        "pages": [
            {
                "competitor": "Lovable",
                "page": "pricing",
                "url": "https://lovable.dev/pricing",
                "status": "changed",
                "signal_ids": ["pr-4401"],
                "current": {
                    "captured_at": "2026-10-26T04:30:00+00:00",
                    "method": "live",
                    "screenshot": "a.jpg",
                },
                "previous": {
                    "captured_at": "2026-10-19T08:00:00+00:00",
                    "method": "live",
                    "screenshot": "b.jpg",
                },
            },
            {
                "competitor": "Lovable",
                "page": "home",
                "url": "https://lovable.dev",
                "status": "not-captured",
            },
            {
                "competitor": "Bolt",
                "page": "pricing",
                "url": "https://bolt.new/pricing",
                "status": "unchanged",
                "current": {"captured_at": "2026-10-26T04:30:00+00:00", "method": "archived"},
                "previous": {"captured_at": "2026-10-19T08:00:00+00:00", "method": "live"},
            },
        ]
    }
    signal = to_signal(
        snap(PAGE), "Pro plan price changed from $25/month to $30/month.", "2026-W44", 1
    )
    case = {"week": "2026-W44", "timezone": "Asia/Jerusalem", "signals": [signal]}
    slides = build_slides(case, run_pipeline(case), run)
    assert [s.status for s in slides] == ["summary", "changed", "not-captured", "unchanged"]
    assert slides[1].previous_shot == "b.jpg" and slides[1].current_shot == "a.jpg"
    assert "Archived copy" in slides[3].footnote


def test_deck_without_run_shows_items_only():
    case = {
        "week": "2026-W43",
        "timezone": "Asia/Jerusalem",
        "signals": [
            {
                "id": "pr-1",
                "type": "pricing",
                "competitor": "Lovable",
                "source": "lovable.dev/pricing",
                "ts": "2026-10-23T08:00:00Z",
                "text": "Pro plan shown at $25/month (was $20 last week).",
            }
        ],
    }
    slides = build_slides(case, run_pipeline(case))
    assert [s.status for s in slides] == ["summary", "changed"]
