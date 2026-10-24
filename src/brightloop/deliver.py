"""Deliver the Monday deck in Slack: one message with what changed, and the .pptx attached.

    brightloop deliver [--week 2026-W43] [--force]

On Monday morning, right after the deck is built, Maya gets one message in her team's
channel: a few short lines (what changed, with the page's link; what to check by hand; a link
to the deck) and the week's .pptx attached right under them. She opens it, or imports it into
her 11:00 deck in Google Slides (File → Import slides). Google Slides itself isn't connected
(decision D20).

Every word comes from the same week data as the app and the slides (templates, no LLM), so
the three can't disagree. The bot's token and channel come from the environment (GitHub
Actions secrets); without them delivery is skipped and the run log says so. A week is posted
once; --force posts it again.
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from brightloop.collect.capture import now_iso
from brightloop.collect.run import append_log, last_complete_week, trigger
from brightloop.deck import (
    build_slides,
    join_and,
    meeting_iso,
    meeting_label,
    plural,
    render_pptx,
    week_view,
)

SITE = "https://brightloop-monday-deck.vercel.app"
SLACK_API = "https://slack.com/api/"
TIMEOUT = 60  # seconds

# What a Slack error means for whoever set the bot up.
SLACK_HINTS = {
    "not_in_channel": "the bot isn't in the channel: /invite it there",
    "channel_not_found": "the channel ID is wrong, or the bot can't see the channel",
    "missing_scope": "the bot needs the chat:write and files:write scopes (then reinstall it)",
    "invalid_auth": "the bot token is wrong or was revoked",
    "token_revoked": "the bot token was revoked",
    "account_inactive": "the bot token was revoked",
}


def deliver_week(week: str | None, root: Path, force: bool = False, env=None) -> dict[str, Any]:
    """One Slack message: the week's lines with its .pptx attached; one run-log line."""
    env = os.environ if env is None else env
    week = week or last_complete_week()
    entry: dict[str, Any] = {"run": "delivery", "week": week, **trigger(), "started_at": now_iso()}
    folder = root / "weeks" / week
    token, channel = env.get("SLACK_BOT_TOKEN"), env.get("SLACK_CHANNEL")
    if not (folder / "run.json").exists():
        entry.update(slack="skipped: no deck for this week", file="skipped")
        return finish(root, entry)
    if not (token and channel):
        entry.update(slack="skipped: not connected", file="skipped")
        return finish(root, entry)
    if not force and already_posted(root, week):
        entry.update(slack="skipped: already posted", file="skipped")
        return finish(root, entry)

    case, result, run = (
        json.loads((folder / name).read_text(encoding="utf-8"))
        for name in ("cases.json", "result.json", "run.json")
    )
    view = week_view(case, result, run)
    text = slack_text(view, env.get("SITE_URL") or SITE, env.get("SLACK_MENTION") or None)
    try:
        upload_deck(case, result, run, root, view, token, channel, text)
        entry.update(slack="posted", file="uploaded")
    except DeliveryError as file_error:
        # Without the file, the lines still go out on their own: Maya shouldn't wait for them.
        try:
            slack_api("chat.postMessage", token, {"channel": channel, "text": text})
            entry.update(slack="posted", file=f"failed: {file_error}")
            entry["errors"] = [f"Slack file: {file_error}"]
        except DeliveryError as exc:
            entry.update(slack=f"failed: {exc}", file=f"failed: {file_error}")
            entry["errors"] = [f"Slack: {exc}"]
    return finish(root, entry)


def deliver_failure(week: str | None, env=None) -> dict[str, Any]:
    """The Monday run failed before the deck: say so, so Maya doesn't wait for a post."""
    env = os.environ if env is None else env
    week = week or last_complete_week()
    token, channel = env.get("SLACK_BOT_TOKEN"), env.get("SLACK_CHANNEL")
    if not (token and channel):
        return {"slack": "skipped: not connected"}
    run_url = None
    if env.get("GITHUB_RUN_ID"):
        server = env.get("GITHUB_SERVER_URL", "https://github.com")
        run_url = f"{server}/{env.get('GITHUB_REPOSITORY', '')}/actions/runs/{env['GITHUB_RUN_ID']}"
    message = failure_message(week, env.get("SITE_URL") or SITE, run_url)
    try:
        slack_api("chat.postMessage", token, {"channel": channel, **message})
    except DeliveryError as exc:
        return {"slack": f"failed: {exc}"}
    return {"slack": "posted"}


def finish(root: Path, entry: dict[str, Any]) -> dict[str, Any]:
    entry.setdefault("errors", [])
    entry["finished_at"] = now_iso()
    append_log(root, entry)
    return entry


def already_posted(root: Path, week: str) -> bool:
    """A week is posted once: a re-run on the same Monday doesn't post again."""
    path = root / "runlog.jsonl"
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        if '"delivery"' in line:
            entry = json.loads(line)
            if entry.get("week") == week and entry.get("slack") == "posted":
                return True
    return False


# ---- The message ---------------------------------------------------------------------------------


def slack_text(view: dict[str, Any], site: str, mention: str | None = None) -> str:
    """The Monday message: a few short lines (Slack mrkdwn), filled from the week's data."""
    week = view["week"]
    pages = view["slides"][1:]
    rows = [r for r in view["slides"][0]["rows"] if r["type"] == "changed"]
    changed = [s for s in pages if s["status"] == "changed"]
    wording = [s for s in pages if s["status"] == "wording"]
    quiet = [s for s in pages if s["status"] == "unchanged"]
    edits = sum(s["wording"] for s in pages)
    title = f"Competitor deck {'so far, ' if view['partial'] else ''}for {view['meeting']}"
    lines = [f"*{md(title)}*"]
    if changed:
        names = join_and([link(s["url"], s["title"]) for s in changed])
        lead = f"*{len(changed)} of {len(pages)} pages changed:* {names}"
        lines.append(f"<@{md(mention)}> {lead}" if mention else lead)
        for row in rows:
            name = f"{md(row['name'])}, " if len(rows) > 1 else ""
            more = f" {md(row['more'])}." if row.get("more") else ""
            lines.append(f"• {name}{md(row['text'])} ({md(row['date'])}).{more}")
        if wording:
            lines.append(
                "Wording only, no price or limit changed: "
                + md(join_and([s["title"] for s in wording]))
                + "."
            )
        if quiet:
            lines.append(
                f"The other {len(quiet)} {'page' if len(quiet) == 1 else 'pages'}: no change."
            )
    elif edits:
        lines.append(
            f"*No price or limit changed.* {plural(edits, 'wording edit', 'wording edits')}, on "
            + md(join_and([s["title"] for s in wording]))
            + "."
        )
    else:
        lines.append(
            f"No changes this week: all {len(pages)} pages checked, "
            "each one's screenshot is in the deck."
        )
    for e in view["exceptions"]:
        page = f" {link(e['url'], 'Open the page')}" if e.get("url") else ""
        lines.append(f"Check by hand: {md(e['text'])}{page}")
    lines.append(
        f"{link(f'{site}/#deck/{week}', 'Open the deck')} · "
        "Import into Google Slides: File → Import slides"
    )
    return "\n".join(lines)


def failure_message(week: str, site: str, run_url: str | None) -> dict[str, Any]:
    title = f"The deck for {meeting_label(week) or week} didn't build"
    text = "The Monday run stopped before the deck was built. Last week's deck is still in the app."
    buttons = [button("Open the app", f"{site}/#deck", primary=True)]
    if run_url:
        buttons.append(button("See the run", run_url))
    return {
        "text": f"{title}. {text}",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": title[:150]}},
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {"type": "actions", "elements": buttons},
        ],
    }


def button(text: str, url: str, primary: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "button",
        "text": {"type": "plain_text", "text": text},
        "url": url,
    }
    if primary:
        out["style"] = "primary"
    return out


def md(text: str) -> str:
    """Slack mrkdwn needs &, < and > escaped."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def link(url: str | None, text: str) -> str:
    return f"<{url}|{md(text)}>" if url else md(text)


# ---- The file ------------------------------------------------------------------------------------


def deck_file_name(view: dict[str, Any]) -> str:
    suffix = "-so-far" if view["partial"] else ""
    return f"competitor-deck-{meeting_iso(view['week'])}{suffix}.pptx"


def upload_deck(
    case: dict,
    result: dict,
    run: dict,
    root: Path,
    view: dict[str, Any],
    token: str,
    channel: str,
    text: str,
) -> None:
    """One message: the lines, with the week's .pptx attached (Slack's upload: get a URL,
    send the file, share it with the text as its comment)."""
    slides = build_slides(case, result, run)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "deck.pptx"
        try:
            render_pptx(slides, root, path)
        except ImportError as exc:
            raise DeliveryError("python-pptx is not installed") from exc
        data = path.read_bytes()
    name = deck_file_name(view)
    slot = slack_api(
        "files.getUploadURLExternal", token, {"filename": name, "length": len(data)}, form=True
    )
    send_bytes(slot["upload_url"], data)
    slack_api(
        "files.completeUploadExternal",
        token,
        {
            "files": json.dumps([{"id": slot["file_id"], "title": name}]),
            "channel_id": channel,
            "initial_comment": text,
        },
        form=True,
    )


# ---- HTTP ----------------------------------------------------------------------------------------


class DeliveryError(Exception):
    """A delivery that didn't go through; recorded in the run log, never fatal."""


def slack_api(
    method: str, token: str, payload: dict[str, Any], form: bool = False
) -> dict[str, Any]:
    """Call Slack's Web API; Slack answers 200 with {"ok": false, "error": ...} on errors."""
    if form:
        data = urllib.parse.urlencode({k: str(v) for k, v in payload.items()}).encode("utf-8")
        kind = "application/x-www-form-urlencoded"
    else:
        data = json.dumps(payload).encode("utf-8")
        kind = "application/json; charset=utf-8"
    request = urllib.request.Request(
        SLACK_API + method,
        data=data,
        headers={"Content-Type": kind, "Authorization": f"Bearer {token}"},
        method="POST",
    )
    body = open_url(request)
    try:
        answer = json.loads(body)
    except ValueError as exc:
        raise DeliveryError(f"Slack's {method} didn't answer JSON") from exc
    if not answer.get("ok"):
        error = str(answer.get("error") or "unknown error")
        raise DeliveryError(f"{error} ({SLACK_HINTS[error]})" if error in SLACK_HINTS else error)
    return answer


def send_bytes(url: str, data: bytes) -> None:
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/octet-stream"}, method="POST"
    )
    open_url(request)


def open_url(request: urllib.request.Request) -> str:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise DeliveryError(f"Slack answered {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DeliveryError(f"couldn't reach Slack ({type(exc).__name__})") from exc
