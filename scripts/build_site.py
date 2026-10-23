"""Build the web app in public/ from recordings/.

    python scripts/build_site.py

public/
  index.html               the app (site/app.html + this data): Deck, Test, Setup
  weeks/<week>/            deck.html (print view / PDF), deck.pptx, cases.json, result.json, run.json
  days/<date>/*.jpg        the screenshots the decks show
  runlog.jsonl             every daily and weekly run (the brief's run log)

The Test page calls /api/run and "Rebuild" calls /api/deck (Vercel Python functions in api/).
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brightloop.collect.run import TZ, targets, week_bounds
from brightloop.deck import build_slides, week_label

RECORDINGS = ROOT / "recordings"
PUBLIC = ROOT / "public"
TEMPLATE = ROOT / "site" / "app.html"
REPO = "https://github.com/matanmill304/brightloop-monday-deck"
BRIEF_SAMPLE = ROOT / "tests" / "fixtures" / "brief_sample.json"


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
        "weeks": weeks,
        "health": health(runs),
        "tracked": tracked(),
        "samples": samples(weeks),
        "repo": REPO,
    }
    embedded = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", embedded)
    (PUBLIC / "index.html").write_text(html, encoding="utf-8", newline="\n")
    print(f"built public/ with {len(weeks)} week(s)")


def week_data(run_file: Path) -> dict:
    folder = run_file.parent
    case, result, run = (
        json.loads((folder / name).read_text(encoding="utf-8"))
        for name in ("cases.json", "result.json", "run.json")
    )
    slides = [vars(s) for s in build_slides(case, result, run)]
    refs = [p.get(k) for p in run["pages"] for k in ("current", "previous")]
    _start, end = week_bounds(folder.name)
    return {
        "week": folder.name,
        "label": week_label(folder.name),
        "built_at": run["finished_at"],
        "partial": datetime.fromisoformat(run["finished_at"]) < end,
        "slides": slides,
        "changed": sum(s["status"] == "changed" for s in slides),
        "shots": sorted({r["screenshot"] for r in refs if r and r.get("screenshot")}),
    }


def read_runlog() -> list[dict]:
    path = RECORDINGS / "runlog.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [json.loads(line) for line in lines if line]


def health(runs: list[dict]) -> dict:
    daily = [r for r in runs if r["run"] == "daily"]
    last = max(daily, key=lambda r: r["started_at"]) if daily else None
    now = datetime.now(TZ)
    monday = (now + timedelta(days=(7 - now.weekday()) % 7 or 7)).date()
    fresh = bool(last) and now - datetime.fromisoformat(last["started_at"]) < timedelta(days=2)
    return {
        "ok": fresh,
        "last_run": max(r["started_at"] for r in runs) if runs else None,
        "last_capture": last["started_at"] if last else None,
        "next_deck": f"{monday:%a}, {monday:%b} {monday.day}",
    }


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
        if current and (row["last"] is None or current["captured_at"] > row["last"]):
            row["last"], row["live"] = current["captured_at"], current["method"] == "live"
    return list(out.values())


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
            out.append({"name": f"Our {week['label'].lower()}", "cases": cases})
            break
    return out


if __name__ == "__main__":
    build()
    print(f"at {datetime.now(UTC):%Y-%m-%d %H:%M} UTC")
