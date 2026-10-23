"""The collector's pure parts: page snapshots in, event signals in the brief's shape out."""

from datetime import date
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


def test_archived_copy_vs_live_capture_is_a_new_baseline_not_a_change():
    # Real case: Replit, Oct 21 archived (yearly view) vs Oct 23 live (monthly) once read
    # as "$90 -> $0". Two different renders are never compared.
    old = snap(PAGE.replace("$25", "$20"), method="archived")
    assert page_events(old, snap(PAGE), TZ) == ("first-snapshot", [])


def test_signal_has_exactly_the_brief_fields_in_their_style():
    signal = to_signal(
        snap(PAGE), "Pro plan price changed from $25/month to $30/month.", date(2026, 10, 26), 1
    )
    assert signal == {
        "id": "pr-102601",
        "type": "pricing",
        "competitor": "Lovable",
        "source": "lovable.dev/pricing",
        "ts": "2026-10-26T04:30:00Z",
        "text": "Pro plan price changed from $25/month to $30/month.",
    }
    home = to_signal(snap("x", page="home"), "Homepage text changed.", date(2026, 10, 26), 2)
    assert (
        home["id"] == "sg-102602" and home["type"] == "launch" and home["source"] == "lovable.dev"
    )


def test_collected_signals_go_through_the_same_pipeline():
    new = snap(PAGE.replace("$25", "$30"))
    _, texts = page_events(OLD, new, TZ)
    signals = [to_signal(new, t, date(2026, 10, 26), n) for n, t in enumerate(texts, 1)]
    out = run_pipeline({"week": "2026-W44", "timezone": "Asia/Jerusalem", "signals": signals})
    assert [i["source_ids"] for i in out["items"]] == [["pr-102601"]]
    assert out["items"][0]["confidence"] == 0.9


def test_deck_shows_every_page_status():
    run = {
        "pages": [
            {
                "competitor": "Lovable",
                "page": "pricing",
                "url": "https://lovable.dev/pricing",
                "status": "changed",
                "signal_ids": ["pr-102601"],
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
        snap(PAGE), "Pro plan price changed from $25/month to $30/month.", date(2026, 10, 26), 1
    )
    case = {"week": "2026-W44", "timezone": "Asia/Jerusalem", "signals": [signal]}
    summary, *slides = build_slides(case, run_pipeline(case), run)
    assert summary.status == "summary" and summary.title == "1 of 3 pages changed"
    assert [s.title for s in slides] == ["Lovable pricing", "Lovable homepage", "Bolt pricing"]
    assert [s.status for s in slides] == ["changed", "not-captured", "unchanged"]
    assert slides[0].shot == "a.jpg" and slides[1].shot is None
    assert [(r["date"], r["plan"], r["tag"], r["old"], r["new"]) for r in slides[0].rows] == [
        ("Oct 26", "Pro", "Price", "$25/month", "$30/month")
    ]
    assert slides[0].rows[0]["text"] == "Pro: $25/month → $30/month"
    assert (
        slides[0].footer == "Deck for Mon, Nov 2 · Source: lovable.dev/pricing · Screenshot Oct 26"
    )
    assert slides[2].footer.endswith(" · archived copy")


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
    assert [(s.title, s.status) for s in slides] == [("Lovable pricing", "changed")]
    assert slides[0].rows[0]["date"] == "Oct 23"


def test_the_daily_refresh_adds_no_run_log_line(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    from brightloop.collect.run import build_week

    days = Path(__file__).resolve().parents[1] / "recordings" / "days"
    for day in ("2026-09-29", "2026-09-30", "2026-10-01"):
        shutil.copytree(days / day, tmp_path / "days" / day)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    log = tmp_path / "runlog.jsonl"
    build_week("2026-W40", tmp_path, final=False)
    assert not log.exists()
    summary = build_week("2026-W40", tmp_path)
    assert log.read_text().count("\n") == 1 and summary["trigger"] == "scheduled"
    assert summary["items"] == 2  # Bolt Lite appeared on Sep 30 and was gone on Oct 1


def test_homepage_top_changes_become_signals_and_items():
    hero = {
        "headline": "What will you build?",
        "subheadline": "Turn ideas into apps in minutes",
        "buttons": ["Start building", "Website"],
    }
    old = Snapshot(
        "Replit",
        "home",
        "https://replit.com",
        "2026-10-26T04:30:00+00:00",
        "live",
        PAGE,
        "What will you build?",
        hero=hero,
    )
    new_hero = {
        **hero,
        "subheadline": "Ship real software with an AI agent",
        "buttons": ["Start for free", "Website"],
    }
    new = Snapshot(
        "Replit",
        "home",
        "https://replit.com",
        "2026-10-27T04:30:00+00:00",
        "live",
        PAGE,
        "What will you build?",
        hero=new_hero,
    )
    status, texts = page_events(old, new, TZ)
    assert status == "changed"
    subheadline = (
        'Subheadline changed from "Turn ideas into apps in minutes" to '
        '"Ship real software with an AI agent".'
    )
    buttons = 'Top-of-page buttons changed: now "Start for free"; no longer "Start building".'
    assert texts == [subheadline, buttons]
    signals = [to_signal(new, t, date(2026, 10, 27), n) for n, t in enumerate(texts, 1)]
    out = run_pipeline({"week": "2026-W44", "timezone": "Asia/Jerusalem", "signals": signals})
    assert [i["page"] for i in out["items"]] == ["home", "home"]
    assert out["items"][0]["change"] == [
        'subheadline: "Turn ideas into apps in minutes" → "Ship real software with an AI agent"'
    ]


def test_snapshots_saved_before_the_top_of_page_was_read_still_load():
    old = snap(PAGE)  # no hero: captures before Oct 24
    new = Snapshot(
        "Lovable",
        "pricing",
        "https://lovable.dev/pricing",
        "2026-10-27T04:30:00+00:00",
        "live",
        PAGE,
        hero={"headline": "Pricing", "subheadline": "x", "buttons": ["a"]},
    )
    assert page_events(old, new, TZ) == ("unchanged", [])
