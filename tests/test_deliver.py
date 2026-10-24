"""Delivery: the Monday post in Slack and the Google Slides copy (no network in these tests)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from brightloop import deliver
from brightloop.deck import week_view

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "recordings"
SITE = "https://brightloop-monday-deck.vercel.app"


def view(week: str) -> dict:
    folder = RECORDINGS / "weeks" / week
    return week_view(
        *(
            json.loads((folder / n).read_text(encoding="utf-8"))
            for n in ("cases.json", "result.json", "run.json")
        )
    )


def texts(message: dict) -> str:
    """Every piece of text in a Block Kit message, for asserting on its content."""
    return json.dumps(message, ensure_ascii=False)


def test_the_post_says_what_changed_with_links():
    message = deliver.slack_message(
        view("2026-W43"), SITE, "https://docs.google.com/presentation/d/x/edit"
    )
    blob = texts(message)
    assert "1 of 6 pages changed: Bolt pricing." in blob
    assert "<https://bolt.new/pricing|Bolt pricing>" in blob
    assert "300K tokens daily limit" in blob and blob.count("Plus 2 wording edits") == 1
    buttons = [
        b for block in message["blocks"] if block["type"] == "actions" for b in block["elements"]
    ]
    assert [b["text"]["text"] for b in buttons] == [
        "Open the deck",
        "Open in Google Slides",
        "Download .pptx",
    ]
    assert buttons[0]["url"] == f"{SITE}/#deck/2026-W43"
    assert "archive.org" not in blob
    assert message["text"].startswith("Competitor deck")


def test_a_quiet_week_says_so_and_mentions_nobody():
    message = deliver.slack_message(view("2026-W42"), SITE, None, mention="U123")
    blob = texts(message)
    assert "No changes this week." in blob and "<@U123>" not in blob
    assert "Check by hand: All 6 screenshots come from the Wayback Machine" in blob
    buttons = [
        b["text"]["text"]
        for block in message["blocks"]
        if block["type"] == "actions"
        for b in block["elements"]
    ]
    assert "Open in Google Slides" not in buttons  # no copy, no button


def test_a_real_change_mentions_maya_when_configured():
    assert "<@U123>" in texts(deliver.slack_message(view("2026-W43"), SITE, None, mention="U123"))


def test_slack_text_is_escaped():
    assert deliver.md("<b> & </b>") == "&lt;b&gt; &amp; &lt;/b&gt;"


def copy_recordings(tmp_path: Path) -> Path:
    root = tmp_path / "recordings"
    shutil.copytree(RECORDINGS, root)
    return root


def last_log(root: Path) -> dict:
    return json.loads((root / "runlog.jsonl").read_text(encoding="utf-8").splitlines()[-1])


def test_without_secrets_nothing_is_sent_and_the_log_says_so(tmp_path, monkeypatch):
    root = copy_recordings(tmp_path)
    monkeypatch.setattr(deliver, "post_json", lambda *a: pytest.fail("nothing may be sent"))
    out = deliver.deliver_week("2026-W42", root, env={})
    assert out["slack"] == "skipped: not connected" and out["slides"] == "skipped: not connected"
    assert last_log(root)["run"] == "delivery"


def test_it_posts_once_with_the_slides_link_and_posts_again_only_on_request(tmp_path, monkeypatch):
    root = copy_recordings(tmp_path)
    sent = []

    def fake_post(url, payload):
        sent.append((url, payload))
        if url == "https://script.example/exec":
            assert (
                payload["token"] == "t0k"
                and payload["pptx"]
                and payload["name"] == "Competitor deck · Mon, Oct 19"
            )
            return 200, json.dumps(
                {"ok": True, "url": "https://docs.google.com/presentation/d/abc/edit"}
            )
        return 200, "ok"

    monkeypatch.setattr(deliver, "post_json", fake_post)
    env = {
        "SLACK_WEBHOOK_URL": "https://hooks.example/1",
        "GSLIDES_HOOK_URL": "https://script.example/exec",
        "GSLIDES_TOKEN": "t0k",
    }
    out = deliver.deliver_week("2026-W42", root, env=env)
    assert (out["slack"], out["slides"]) == ("posted", "saved")
    assert out["slides_url"] == "https://docs.google.com/presentation/d/abc/edit"
    assert "docs.google.com/presentation/d/abc" in texts(
        sent[-1][1]
    )  # the Slack post carries the link
    again = deliver.deliver_week("2026-W42", root, env=env)
    assert again["slack"] == "skipped: already posted" and len(sent) == 2
    forced = deliver.deliver_week("2026-W42", root, env=env, force=True)
    assert forced["slack"] == "posted" and len(sent) == 4


def test_slack_still_posts_when_google_fails(tmp_path, monkeypatch):
    root = copy_recordings(tmp_path)

    def fake_post(url, payload):
        if "script" in url:
            return 200, json.dumps({"ok": False, "error": "wrong token"})
        return 200, "ok"

    monkeypatch.setattr(deliver, "post_json", fake_post)
    env = {
        "SLACK_WEBHOOK_URL": "https://hooks.example/1",
        "GSLIDES_HOOK_URL": "https://script.example/exec",
        "GSLIDES_TOKEN": "x",
    }
    out = deliver.deliver_week("2026-W42", root, env=env)
    assert out["slack"] == "posted" and out["slides"].startswith(
        "failed: the Google script said: wrong token"
    )
    assert out["errors"] == ["Google Slides: the Google script said: wrong token"]


def test_a_failed_monday_run_is_announced():
    message = deliver.failure_message("2026-W43", SITE, "https://github.com/x/y/actions/runs/1")
    assert "The deck for Monday, Oct 26 didn't build" in texts(message)


def test_the_setup_page_reads_delivery_from_the_run_log():
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    site = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(site)
    runs = [
        {"run": "delivery", "week": "2026-W42", "started_at": "2026-10-19T04:35:00+00:00", "slack": "posted",
         "slides": "saved", "slides_url": "https://docs.google.com/presentation/d/abc/edit", "errors": []},
    ]  # fmt: skip
    status = site.delivery(runs)
    assert status["slack"]["state"] == "ok" and status["slides"]["url"].endswith("/abc/edit")
    assert site.slides_links(runs) == {
        "2026-W42": "https://docs.google.com/presentation/d/abc/edit"
    }
    assert site.delivery([])["slack"] == {"state": "not set up"}
    row = site.run_rows(runs)[0]
    assert row["run"] == "Delivery" and row["found"] == "Slack: posted · Slides: saved"
