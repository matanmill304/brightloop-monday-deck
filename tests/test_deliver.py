"""Delivery: one Slack message with what changed and the .pptx attached (no network here)."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from brightloop import deliver
from brightloop.deck import week_view

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "recordings"
SITE = "https://brightloop-monday-deck.vercel.app"
SLACK = {"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_CHANNEL": "C0TEST"}


def view(week: str) -> dict:
    folder = RECORDINGS / "weeks" / week
    files = ("cases.json", "result.json", "run.json")
    return week_view(*(json.loads((folder / n).read_text(encoding="utf-8")) for n in files))


def texts(message: dict) -> str:
    """Every piece of text in a Block Kit message, for asserting on its content."""
    return json.dumps(message, ensure_ascii=False)


def test_the_message_says_what_changed_with_links():
    text = deliver.slack_text(view("2026-W43"), SITE)
    lines = text.split("\n")
    assert lines[0] == "*Competitor deck so far, for Monday, Oct 26*"
    assert lines[1] == "*1 of 6 pages changed:* <https://bolt.new/pricing|Bolt pricing>"
    assert "300K tokens daily limit" in lines[2] and "Plus 2 wording edits" in lines[2]
    assert lines[3] == "The other 5 pages: no change."
    assert f"<{SITE}/#deck/2026-W43|Open the deck>" in lines[-1]
    assert "archive.org" not in text and len(lines) == 5


def test_a_quiet_week_says_so_and_mentions_nobody():
    text = deliver.slack_text(view("2026-W42"), SITE, mention="U123")
    assert "No changes this week" in text and "<@U123>" not in text
    assert "Check by hand: All 6 screenshots come from the Wayback Machine" in text


def test_a_real_change_mentions_maya_when_configured():
    assert "<@U123>" in deliver.slack_text(view("2026-W43"), SITE, mention="U123")


def test_slack_text_is_escaped():
    assert deliver.md("<b> & </b>") == "&lt;b&gt; &amp; &lt;/b&gt;"


def copy_recordings(tmp_path: Path) -> Path:
    root = tmp_path / "recordings"
    shutil.copytree(RECORDINGS, root)
    return root


class FakeSlack:
    """Slack's Web API, recorded: get an upload URL, receive the file, share it with the lines."""

    def __init__(self, fail: dict | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.uploaded = b""
        self.fail = fail or {}

    def api(self, method, token, payload, form=False):
        assert token == "xoxb-test"
        self.calls.append((method, payload))
        if method in self.fail:
            raise deliver.DeliveryError(self.fail[method])
        if method == "files.getUploadURLExternal":
            return {"ok": True, "upload_url": "https://files.example/upload", "file_id": "F1"}
        return {"ok": True, "ts": "1.0"}

    def send(self, url, data):
        self.uploaded = data


def fake(monkeypatch, slack: FakeSlack) -> FakeSlack:
    monkeypatch.setattr(deliver, "slack_api", slack.api)
    monkeypatch.setattr(deliver, "send_bytes", slack.send)
    return slack


def test_without_a_bot_nothing_is_sent_and_the_log_says_so(tmp_path, monkeypatch):
    root = copy_recordings(tmp_path)
    monkeypatch.setattr(deliver, "slack_api", lambda *a, **k: pytest.fail("nothing may be sent"))
    out = deliver.deliver_week("2026-W42", root, env={})
    assert out["slack"] == "skipped: not connected"
    log = json.loads((root / "runlog.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert log["run"] == "delivery" and log["week"] == "2026-W42"


def test_one_message_with_the_file_and_a_week_only_once(tmp_path, monkeypatch):
    root = copy_recordings(tmp_path)
    slack = fake(monkeypatch, FakeSlack())
    out = deliver.deliver_week("2026-W42", root, env=SLACK)
    assert (out["slack"], out["file"]) == ("posted", "uploaded")
    methods = [m for m, _ in slack.calls]
    assert methods == ["files.getUploadURLExternal", "files.completeUploadExternal"]
    assert slack.uploaded[:2] == b"PK"  # a .pptx
    share = slack.calls[1][1]
    assert share["channel_id"] == "C0TEST"
    assert share["initial_comment"].startswith("*Competitor deck for Monday, Oct 19*")
    assert slack.calls[0][1]["filename"] == "competitor-deck-2026-10-19.pptx"
    again = deliver.deliver_week("2026-W42", root, env=SLACK)
    assert again["slack"] == "skipped: already posted" and len(slack.calls) == 2
    forced = deliver.deliver_week("2026-W42", root, env=SLACK, force=True)
    assert forced["slack"] == "posted" and len(slack.calls) == 4


def test_without_the_file_the_lines_still_go_out(tmp_path, monkeypatch):
    root = copy_recordings(tmp_path)
    slack = fake(monkeypatch, FakeSlack(fail={"files.getUploadURLExternal": "missing_scope"}))
    out = deliver.deliver_week("2026-W42", root, env=SLACK)
    assert out["slack"] == "posted" and out["file"] == "failed: missing_scope"
    assert out["errors"] == ["Slack file: missing_scope"]
    assert slack.calls[-1][0] == "chat.postMessage"
    assert slack.calls[-1][1]["text"].startswith("*Competitor deck for Monday, Oct 19*")


def test_a_slack_error_says_what_to_fix(monkeypatch):
    monkeypatch.setattr(
        deliver, "open_url", lambda request: '{"ok": false, "error": "not_in_channel"}'
    )
    with pytest.raises(deliver.DeliveryError, match="invite it there"):
        deliver.slack_api("chat.postMessage", "xoxb-test", {"channel": "C0TEST"})


def test_a_failed_monday_run_is_announced():
    message = deliver.failure_message("2026-W43", SITE, "https://github.com/x/y/actions/runs/1")
    assert "The deck for Monday, Oct 26 didn't build" in texts(message)


def load_site():
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    site = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(site)
    return site


def test_the_setup_page_shows_slack_from_the_run_log(monkeypatch):
    site = load_site()
    runs = [
        {"run": "delivery", "week": "2026-W42", "started_at": "2026-10-19T04:35:00+00:00",
         "slack": "posted", "file": "uploaded", "errors": []},
    ]  # fmt: skip
    monkeypatch.delenv("SLACK_CONNECTED", raising=False)
    status = site.delivery(runs)["slack"]
    assert status["state"] == "ok" and status["file"] == "uploaded"
    assert site.delivery([])["slack"]["state"] == "not connected"
    monkeypatch.setenv("SLACK_CONNECTED", "false")  # the secret was deleted after the demo
    assert site.delivery(runs)["slack"]["state"] == "not connected"
    row = site.run_rows(runs)[0]
    assert row["run"] == "Delivery" and row["found"] == "Slack: posted · .pptx: uploaded"
