"""Deliver the Monday deck: a post in Slack and a native copy in Google Slides.

    brightloop deliver [--week 2026-W43] [--force]

On Monday morning, right after the deck is built, Maya gets one Slack post in
#competitor-watch: what changed (each with its link), what didn't, what to check by hand, and
buttons to the deck, its Google Slides copy and the .pptx. The Slides copy is the same .pptx,
converted into a Google Slides file in a Drive folder (see integrations/google-slides/).

Every word comes from the same week data as the app and the slides (templates, no LLM), so
the three can't disagree. Secrets come from the environment (GitHub Actions secrets); without
them delivery is skipped and the run log says so. A week is posted once; --force posts again.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from brightloop.collect.capture import now_iso
from brightloop.collect.run import append_log, last_complete_week, trigger
from brightloop.deck import build_slides, join_and, plural, render_pptx, week_view

SITE = "https://brightloop-monday-deck.vercel.app"
TIMEOUT = 60  # seconds; converting a deck in Google Slides takes a few


def deliver_week(week: str | None, root: Path, force: bool = False, env=None) -> dict[str, Any]:
    """Post the week's deck to Slack and save it to Google Slides; one run-log line."""
    env = os.environ if env is None else env
    week = week or last_complete_week()
    started = now_iso()
    entry: dict[str, Any] = {"run": "delivery", "week": week, **trigger(), "started_at": started}
    folder = root / "weeks" / week
    if not (folder / "run.json").exists():
        entry.update(
            slack="skipped: no deck for this week", slides="skipped: no deck for this week"
        )
        return finish(root, entry)
    if not force and already_posted(root, week):
        entry.update(slack="skipped: already posted", slides="skipped: already posted")
        return finish(root, entry)

    case, result, run = (
        json.loads((folder / name).read_text(encoding="utf-8"))
        for name in ("cases.json", "result.json", "run.json")
    )
    view = week_view(case, result, run)
    site = env.get("SITE_URL") or SITE
    errors: list[str] = []

    slides_url = None
    hook, token = env.get("GSLIDES_HOOK_URL"), env.get("GSLIDES_TOKEN")
    if hook and token:
        try:
            slides_url = save_to_slides(case, result, run, root, slides_name(view), hook, token)
            entry["slides"] = "saved"
        except DeliveryError as exc:
            entry["slides"] = f"failed: {exc}"
            errors.append(f"Google Slides: {exc}")
    else:
        entry["slides"] = "skipped: not connected"
    entry["slides_url"] = slides_url

    webhook = env.get("SLACK_WEBHOOK_URL")
    if webhook:
        message = slack_message(view, site, slides_url, env.get("SLACK_MENTION") or None)
        try:
            status, body = post_json(webhook, message)
            if status != 200:
                raise DeliveryError(f"Slack answered {status}: {body[:80]}")
            entry["slack"] = "posted"
        except DeliveryError as exc:
            entry["slack"] = f"failed: {exc}"
            errors.append(f"Slack: {exc}")
    else:
        entry["slack"] = "skipped: not connected"
    entry["errors"] = errors
    return finish(root, entry)


def deliver_failure(week: str | None, env=None) -> dict[str, Any]:
    """The Monday run failed before the deck: say so, so Maya doesn't wait for a post."""
    env = os.environ if env is None else env
    week = week or last_complete_week()
    webhook = env.get("SLACK_WEBHOOK_URL")
    if not webhook:
        return {"slack": "skipped: not connected"}
    run_url = None
    if env.get("GITHUB_RUN_ID"):
        server = env.get("GITHUB_SERVER_URL", "https://github.com")
        run_url = f"{server}/{env.get('GITHUB_REPOSITORY', '')}/actions/runs/{env['GITHUB_RUN_ID']}"
    message = failure_message(week, env.get("SITE_URL") or SITE, run_url)
    try:
        status, _ = post_json(webhook, message)
    except DeliveryError as exc:
        return {"slack": f"failed: {exc}"}
    return {"slack": "posted" if status == 200 else f"failed: Slack answered {status}"}


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


# ---- Slack ---------------------------------------------------------------------------------------


def slack_message(
    view: dict[str, Any], site: str, slides_url: str | None = None, mention: str | None = None
) -> dict[str, Any]:
    """The Monday post (Slack Block Kit), filled from the week's data."""
    week = view["week"]
    pages = view["slides"][1:]
    summary = view["slides"][0]
    changed = [s for s in pages if s["status"] == "changed"]
    wording = [s for s in pages if s["status"] == "wording"]
    quiet = [s for s in pages if s["status"] == "unchanged"]
    edits = sum(s["wording"] for s in pages)
    if view["partial"]:
        title = f"Competitor deck so far, for {view['meeting']}"
    else:
        title = f"Competitor deck for {view['meeting']} is ready"

    if changed:
        names = md(join_and([s["title"] for s in changed]))
        lead = f"*{len(changed)} of {len(pages)} pages changed: {names}.*"
        if mention:
            lead = f"<@{md(mention)}> {lead}"
    elif edits:
        lead = (
            "*No price or limit changed.* "
            + md(plural(edits, "wording edit", "wording edits"))
            + ", on "
            + md(join_and([s["title"] for s in wording]))
            + "."
        )
    else:
        lead = (
            f"*No changes this week.* All {len(pages)} pages were checked; "
            "the deck has a screenshot of each."
        )

    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": title[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": lead}},
    ]
    for row in summary["rows"]:
        if row["type"] != "changed":
            continue
        line = f"• {link(row['url'], row['name'])}: {md(row['text'])} · {md(row['date'])}"
        if row.get("more"):
            line += f"\n      _{md(row['more'])}_"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": line}})

    notes = []
    if wording:
        names = ", ".join(link(s["url"], s["title"]) for s in wording)
        notes.append(f"Wording only, no price or limit changed: {names}")
    if quiet and (changed or wording):
        notes.append("No change: " + " · ".join(link(s["url"], s["title"]) for s in quiet))
    for e in view["exceptions"]:
        text = f"Check by hand: {md(e['text'])}"
        if e.get("url"):
            text += f" {link(e['url'], 'Open the page')}"
        notes.append(text)
    if notes:
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": n} for n in notes[:10]]}
        )

    buttons = [button("Open the deck", f"{site}/#deck/{week}", primary=True)]
    if slides_url:
        buttons.append(button("Open in Google Slides", slides_url))
    pptx = (
        f"{site}/api/deck?week={week}&format=pptx"
        if view["partial"]
        else f"{site}/weeks/{week}/deck.pptx"
    )
    buttons.append(button("Download .pptx", pptx))
    blocks.append({"type": "actions", "elements": buttons})
    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": md(f"{summary['footer']} · built {view['built']}")}
            ],
        }
    )
    plain = lead.replace("*", "")
    return {"text": f"{title}: {strip_links(plain)}", "blocks": blocks}


def failure_message(week: str, site: str, run_url: str | None) -> dict[str, Any]:
    from brightloop.deck import meeting_label

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


def strip_links(text: str) -> str:
    import re

    return re.sub(r"<[^|>]+\|([^>]+)>", r"\1", re.sub(r"<@[^>]+>\s*", "", text))


# ---- Google Slides -------------------------------------------------------------------------------


def slides_name(view: dict[str, Any]) -> str:
    """'Competitor deck · Mon, Oct 26': one file per week; a re-run replaces it."""
    return f"Competitor deck · {view['meeting_short']}" + (" (so far)" if view["partial"] else "")


def save_to_slides(
    case: dict, result: dict, run: dict, root: Path, name: str, hook: str, token: str
) -> str:
    """Send the week's .pptx to the Google Apps Script, which saves it as Google Slides."""
    slides = build_slides(case, result, run)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "deck.pptx"
        try:
            render_pptx(slides, root, path)
        except ImportError as exc:
            raise DeliveryError("python-pptx is not installed") from exc
        pptx = base64.b64encode(path.read_bytes()).decode("ascii")
    status, body = post_json(hook, {"token": token, "name": name, "pptx": pptx})
    try:
        answer = json.loads(body)
    except ValueError as exc:
        raise DeliveryError(f"the Google script answered {status} without JSON") from exc
    if not answer.get("ok") or not answer.get("url"):
        raise DeliveryError(f"the Google script said: {answer.get('error') or 'no link'}")
    return str(answer["url"])


# ---- HTTP ----------------------------------------------------------------------------------------


class DeliveryError(Exception):
    """A delivery that didn't go through; recorded in the run log, never fatal."""


def post_json(url: str, payload: dict[str, Any]) -> tuple[int, str]:
    """POST JSON; follow redirects (Google Apps Script answers through one)."""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DeliveryError(f"couldn't reach the server ({type(exc).__name__})") from exc
