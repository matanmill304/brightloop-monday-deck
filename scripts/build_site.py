"""Build the web app in public/ from recordings/.

    python scripts/build_site.py

public/
  index.html               the app (site/app.html + this data): What's new, Deck, Test, Setup
  weeks/<week>/            deck.html (print view / PDF), deck.pptx, cases.json, result.json, run.json
  days/<date>/*.jpg        the screenshots the decks show
  runlog.jsonl             every daily, weekly and rebuild run (the brief's run log)

The Test page calls /api/run, and its rebuild check calls /api/deck (Vercel Python functions
in api/).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brightloop import write_text
from brightloop.collect.run import TZ, targets
from brightloop.deck import clock, is_partial, week_label, week_view
from brightloop.explain import SKIP_GROUPS
from brightloop.normalize import UTC, parse_iso

RECORDINGS = ROOT / "recordings"
PUBLIC = ROOT / "public"
TEMPLATE = ROOT / "site" / "app.html"
REPO = "https://github.com/matanmill304/brightloop-monday-deck"
BRIEF_SAMPLE = ROOT / "tests" / "fixtures" / "brief_sample.json"
CAPTURE_AT = time(4, 30)  # UTC, .github/workflows/daily.yml
RUNS_SHOWN = 14


def build() -> None:
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    PUBLIC.mkdir()
    weeks = [week_data(f) for f in sorted(RECORDINGS.glob("weeks/*/run.json"), reverse=True)]
    for week in weeks:
        shutil.copytree(RECORDINGS / "weeks" / week["week"], PUBLIC / "weeks" / week["week"])
        for shot in week.pop("shots"):
            (PUBLIC / shot).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(RECORDINGS / shot, PUBLIC / shot)
    runs = read_runlog()
    shutil.copy2(RECORDINGS / "runlog.jsonl", PUBLIC / "runlog.jsonl")
    data = {
        "default_week": default_week(weeks),
        "weeks": weeks,
        "runs": run_rows(runs),
        "delivery": delivery(runs),
        "health": health(runs),
        "tracked": tracked(),
        "samples": samples(weeks),
        "skip_groups": [list(group) for group in SKIP_GROUPS],
        "links": links(),
        "repo": REPO,
    }
    embedded = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", embedded)
    write_text(PUBLIC / "index.html", html)
    print(f"built public/ with {len(weeks)} week(s)")


def week_data(run_file: Path) -> dict:
    folder = run_file.parent
    case, result, run = (
        json.loads((folder / name).read_text(encoding="utf-8"))
        for name in ("cases.json", "result.json", "run.json")
    )
    view = week_view(case, result, run)
    refs = [p.get(k) for p in run["pages"] for k in ("current", "previous")]
    view["shots"] = sorted({r["screenshot"] for r in refs if r and r.get("screenshot")})
    return view


def default_week(weeks: list[dict]) -> int:
    """The newest complete week: on Monday morning that's the deck for the 11:00 meeting, not
    the week that just started. With no complete week, the newest."""
    return next((i for i, w in enumerate(weeks) if not w["partial"]), 0)


def read_runlog() -> list[dict]:
    path = RECORDINGS / "runlog.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [json.loads(line) for line in lines if line]


def israel(iso: str) -> str:
    return clock(parse_iso(iso).astimezone(TZ))


def health(runs: list[dict]) -> dict:
    daily = [r for r in runs if r["run"] == "daily"]
    last = max(daily, key=lambda r: r["started_at"]) if daily else None
    now = datetime.now(UTC)
    fresh = bool(last) and now - parse_iso(last["started_at"]) < timedelta(days=2)
    latest = max(runs, key=lambda r: r["started_at"]) if runs else None
    return {
        "ok": fresh,  # a page that wasn't captured shows in the run log, not as a red light
        "last_capture": israel(last["started_at"]) if last else None,
        "last_run": israel(latest["started_at"]) if latest else None,
        "next_deck": clock(next_deck(now).astimezone(TZ)),
    }


def next_deck(now: datetime) -> datetime:
    """The next Monday's scheduled run, when the week's deck is built."""
    monday = (now + timedelta(days=-now.weekday() % 7)).date()
    run = datetime.combine(monday, CAPTURE_AT, UTC)
    return run if run > now else run + timedelta(days=7)


RUN_NAME = {
    "daily": "Daily capture",
    "weekly": "Weekly deck",
    "rebuild": "Rebuild",
    "delivery": "Delivery",
}


def short(result: str | None) -> str:
    """A delivery result in a word or two: "posted", "skipped", "failed"."""
    return (result or "—").split(":")[0]


def delivery(runs: list[dict]) -> dict:
    """Slack on the Setup page: connected or not, and the last post. Whether it's connected
    comes from the daily job (SLACK_CONNECTED, from the secrets' presence); the last result
    from the run log. The site never sees a secret."""
    flag = os.environ.get("SLACK_CONNECTED", "").lower()
    lines = sorted((r for r in runs if r["run"] == "delivery"), key=lambda r: r["started_at"])
    tried = [r for r in lines if not str(r.get("slack", "")).startswith("skipped")]
    last = tried[-1] if tried else None
    out: dict = {"connected": flag == "true" if flag in ("true", "false") else None}
    if last is not None:
        result = str(last.get("slack"))
        out.update(
            state="ok" if result == "posted" else "failed",
            at=israel(last["started_at"]),
            week=last.get("week"),
            detail=result,
            file=last.get("file"),
        )
    if out["connected"] is False:
        out["state"] = "not connected"  # disconnected: its last post (if any) stays as history
    elif last is None:
        out["state"] = "not connected"
    return {"slack": out}


def run_rows(runs: list[dict]) -> list[dict]:
    """The last runs, newest first, shaped for the Setup page's run log table."""
    order = [f"{c} {p}" for c, p, _url in targets()]
    rows = []
    for r in sorted(runs, key=lambda r: r["started_at"], reverse=True)[:RUNS_SHOWN]:
        pages = r.get("pages") or {}
        errors = r.get("errors")
        if errors is None:  # entries written before daily runs listed their errors
            names = {"not-captured": "not captured", "failed-capture": "capture failed"}
            errors = [f"{k}: {names[v]}" for k, v in pages.items() if v in names]
        row = {
            "when": israel(r["started_at"]),
            "run": RUN_NAME.get(r["run"], r["run"]),
            "pages": [pages.get(key, "not-captured") for key in order] if pages else None,
            "problems": "; ".join(readable(e) for e in errors) or "—",
        }
        if r["run"] == "daily":
            day = parse_iso(r["date"] + "T12:00:00+00:00")
            row["for"] = f"{day:%b} {day.day} · {r.get('mode', 'live')}"
            row["found"] = plural(r.get("signals", 0), "signal", "signals")
        elif r["run"] == "weekly":
            partial = is_partial(r["week"], r, TZ)
            row["for"] = r["week"] + (" (so far)" if partial else "")
            row["found"] = plural(r.get("items", 0), "item", "items")
        elif r["run"] == "delivery":
            row["for"] = r.get("week", "")
            row["found"] = f"Slack: {short(r.get('slack'))} · .pptx: {short(r.get('file'))}"
        else:
            weeks = r.get("weeks") or {}
            newest = max(weeks) if weeks else None
            row["for"] = f"All {len(weeks)} weeks" + (
                f" · {r['reason']}" if r.get("reason") else ""
            )
            row["found"] = (
                f"{newest[5:]}: {plural(weeks[newest]['items'], 'item', 'items')}"
                if newest
                else "—"
            )
        rows.append(row)
    return rows


def readable(error: str) -> str:
    """Run-log errors written before they were plain words: "Lovable home: not-captured"."""
    error = error.replace(" home:", " homepage:")
    return error.replace(": not-captured", ": not captured").replace(
        ": failed-capture", ": capture failed"
    )


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def tracked() -> list[dict]:
    latest: dict[tuple[str, str], dict] = {}
    for day in sorted(RECORDINGS.glob("days/*/day.json")):
        for page in json.loads(day.read_text(encoding="utf-8"))["pages"]:
            if page.get("current"):
                latest[(page["competitor"], page["page"])] = page["current"]
    out: dict[str, dict] = {}
    for competitor, page, url in targets():
        row = out.setdefault(competitor, {"name": competitor, "last": None, "live": False})
        row["pricing" if page == "pricing" else "home"] = url
        current = latest.get((competitor, page))
        if current and (row.get("_at") is None or current["captured_at"] > row["_at"]):
            row["_at"], row["live"] = current["captured_at"], current["method"] == "live"
            row["last"] = israel(current["captured_at"])
    for row in out.values():
        row.pop("_at", None)
    return list(out.values())


def links() -> dict:
    blob = f"{REPO}/blob/main"
    return {
        "repo": REPO,
        "readme": f"{blob}/README.md",
        "why_maya": f"{blob}/docs/why-maya.md",
        "decisions": f"{blob}/decisions.md",
        "spotted": f"{blob}/SPOTTED.md",
    }


def samples(weeks: list[dict]) -> list[dict]:
    out = []
    if BRIEF_SAMPLE.exists():
        out.append(
            {
                "name": "The brief's sample",
                "cases": json.loads(BRIEF_SAMPLE.read_text(encoding="utf-8")),
            }
        )
    for week in weeks:
        cases = json.loads(
            (RECORDINGS / "weeks" / week["week"] / "cases.json").read_text(encoding="utf-8")
        )
        if cases["signals"]:
            label = week_label(week["week"])
            out.append({"name": f"Our {label[:1].lower()}{label[1:]}", "cases": cases})
            break
    return out


if __name__ == "__main__":
    build()
    print(f"at {datetime.now(UTC):%Y-%m-%d %H:%M} UTC")
