"""Maya's Monday deck: one slide per competitor page, built from a run's cases + result.

Maya: "Leadership wants the visual diff, not an essay." Each slide is a screenshot, a
status line and, when something changed, old → new with the link. Rendered as HTML (the web
app) and .pptx (opens in Google Slides via File → Import), from the same slide data.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from brightloop.competitors import COMPETITORS

PAGES = (("pricing", "Pricing page"), ("home", "Homepage"))
DEFAULT_COMPETITORS = ("Lovable", "Replit", "Bolt")


@dataclass
class Slide:
    title: str
    status: str  # changed | unchanged | no-baseline | not-captured | announced
    headline: str
    lines: list[str] = field(default_factory=list)
    url: str | None = None
    current_shot: str | None = None
    previous_shot: str | None = None
    footnote: str = ""


def build_slides(case: dict[str, Any], result: dict[str, Any]) -> list[Slide]:
    tz = ZoneInfo(case.get("timezone") or "UTC")
    signals = {s["id"]: s for s in case.get("signals", []) if isinstance(s, dict) and "id" in s}
    item_of = {sid: item for item in result.get("items", []) for sid in item["source_ids"]}
    skip_of = {s["id"]: s["reason"] for s in result.get("skipped", [])}
    snapshots = [s for s in signals.values() if s.get("snapshot") is True]

    slides: list[Slide] = []
    used_items: set[str] = set()
    competitors = sorted({s["competitor"] for s in snapshots}, key=order) or []
    for competitor in competitors:
        for page, label in PAGES:
            mine = sorted(
                (s for s in snapshots if s["competitor"] == competitor and page_of(s) == page),
                key=lambda s: s["ts"],
            )
            slide = page_slide(competitor, page, label, mine, item_of, skip_of, tz)
            if slide.status == "changed":
                used_items.add(item_of[mine[-1]["id"]]["id"])
            slides.append(slide)

    for item in result.get("items", []):
        if item["id"] in used_items:
            continue
        slides.append(item_slide(item))
    return [summary_slide(case, slides, tz), *slides]


def page_slide(competitor, page, label, mine, item_of, skip_of, tz) -> Slide:
    url = page_url(competitor, page)
    if not mine:
        return Slide(
            f"{competitor} · {label}",
            "not-captured",
            "Not captured this week",
            [
                (
                    "The live page blocked automated access and no archived copy was available. "
                    "Check it by hand."
                )
            ],
            url,
        )
    current, previous = mine[-1], (mine[-2] if len(mine) > 1 else None)
    footnote = capture_note(current, tz)
    shots = {"current_shot": current.get("screenshot"), "url": url, "footnote": footnote}
    item = item_of.get(current["id"])
    if item:
        lines = [f"{c}" for c in item.get("change", [])]
        lines += [f"Caveat: {c}" for c in item.get("caveats", [])]
        return Slide(
            f"{competitor} · {label}",
            "changed",
            "Changed since last week",
            lines,
            previous_shot=previous.get("screenshot") if previous else None,
            **shots,
        )
    reason = skip_of.get(current["id"], "")
    if previous is None or "no earlier snapshot" in reason:
        return Slide(
            f"{competitor} · {label}",
            "no-baseline",
            "First snapshot: nothing to compare yet",
            ["Next week's deck will show what changed against this one."],
            **shots,
        )
    since = when_local(previous["ts"], tz, "%b %d")
    return Slide(f"{competitor} · {label}", "unchanged", f"No change since {since}", [], **shots)


def item_slide(item: dict[str, Any]) -> Slide:
    announced = item.get("page") == "announcement"
    return Slide(
        f"{item.get('competitor', '')} · {'Announced' if announced else 'Change'}",
        "announced" if announced else "changed",
        item["action"],
        [*item.get("change", []), item["why"], *(f"Caveat: {c}" for c in item.get("caveats", []))],
        url=(item.get("links") or [None])[0] or (item.get("cta") or {}).get("url"),
        footnote=f"Confidence {item['confidence']:.2f} · sources: "
        + ", ".join(str(s) for s in item["source_ids"]),
    )


def summary_slide(case: dict[str, Any], slides: list[Slide], tz: ZoneInfo) -> Slide:
    changed = [s for s in slides if s.status in ("changed", "announced")]
    lines = [f"{s.title}: {s.headline}" for s in changed] or ["No pricing or homepage changes."]
    missing = [s.title for s in slides if s.status == "not-captured"]
    if missing:
        lines.append("Not captured (check by hand): " + ", ".join(missing))
    return Slide(
        f"Competitor pages · week {case.get('week', '')}",
        "summary",
        f"{len(changed)} change{'s' if len(changed) != 1 else ''} this week",
        lines,
        footnote="Every number links to the competitor's own page. "
        f"Generated {datetime.now(tz):%a %b %d, %H:%M} ({tz}).",
    )


# ---- Rendering ----------------------------------------------------------------------------

STATUS_LABEL = {
    "changed": "Changed",
    "announced": "Announced: check the page",
    "unchanged": "No change",
    "no-baseline": "First snapshot",
    "not-captured": "Not captured",
    "summary": "This week",
}


def render_html(slides: list[Slide], title: str) -> str:
    def esc(value: str) -> str:
        return html.escape(value or "")

    parts = []
    for s in slides:
        shots = ""
        if s.previous_shot and s.current_shot:
            shots = (
                f'<div class="pair"><figure><img src="{esc(s.previous_shot)}" alt="Before">'
                f"<figcaption>Before</figcaption></figure><figure><img src="
                f'"{esc(s.current_shot)}" alt="Now"><figcaption>Now</figcaption></figure></div>'
            )
        elif s.current_shot:
            shots = f'<figure class="one"><img src="{esc(s.current_shot)}" alt="{esc(s.title)}"></figure>'
        lines = "".join(f"<li>{esc(line)}</li>" for line in s.lines)
        link = f'<a href="{esc(s.url)}">{esc(s.url)}</a>' if s.url else ""
        parts.append(
            f'<section class="slide {s.status}"><header><span class="tag">'
            f"{STATUS_LABEL.get(s.status, s.status)}</span><h2>{esc(s.title)}</h2></header>"
            f'<p class="headline">{esc(s.headline)}</p>{"<ul>" + lines + "</ul>" if lines else ""}'
            f"{shots}<footer>{link}<span>{esc(s.footnote)}</span></footer></section>"
        )
    return HTML_PAGE.replace("{{title}}", html.escape(title)).replace(
        "{{slides}}", "\n".join(parts)
    )


HTML_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{title}}</title>
<style>
:root{--ink:#14181f;--soft:#5b6472;--line:#dfe3e8;--bg:#f4f5f7;--card:#fff;--changed:#b4235a;--ok:#2f7d4f;--warn:#9a6700}
@media (prefers-color-scheme:dark){:root{--ink:#e8ebef;--soft:#9aa3ae;--line:#2c333c;--bg:#11151a;--card:#181d24}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:16px}
.slide{max-width:1100px;margin:0 auto 20px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:24px;aspect-ratio:16/9;display:flex;flex-direction:column;gap:10px;overflow:hidden}
header{display:flex;align-items:center;gap:12px}h2{margin:0;font-size:24px}
.tag{font-size:12px;font-weight:600;padding:3px 8px;border-radius:99px;border:1px solid var(--line);color:var(--soft);white-space:nowrap}
.changed .tag,.announced .tag{color:var(--changed);border-color:var(--changed)}.unchanged .tag{color:var(--ok);border-color:var(--ok)}
.not-captured .tag,.no-baseline .tag{color:var(--warn);border-color:var(--warn)}
.headline{margin:0;font-size:20px;font-weight:600}ul{margin:0;padding-left:20px}
figure{margin:0;min-height:0;flex:1;display:flex;flex-direction:column}figure img{width:100%;height:100%;object-fit:contain;object-position:top;border:1px solid var(--line);border-radius:6px;min-height:0}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px;flex:1;min-height:0}figcaption{font-size:12px;color:var(--soft)}
footer{display:flex;justify-content:space-between;gap:12px;font-size:12px;color:var(--soft);flex-wrap:wrap}footer a{color:inherit}
@media (max-width:700px){.slide{aspect-ratio:auto}.pair{grid-template-columns:1fr}}
@media print{body{background:#fff;padding:0}.slide{break-after:page;border:none}}
</style></head><body>
{{slides}}
</body></html>
"""


def render_pptx(slides: list[Slide], folder: Path, path: Path) -> None:
    from PIL import Image
    from pptx import Presentation  # optional dependency: pip install .[deck]
    from pptx.util import Emu, Pt

    deck = Presentation()
    deck.slide_width, deck.slide_height = Emu(12192000), Emu(6858000)  # 16:9
    blank = deck.slide_layouts[6]
    for s in slides:
        slide = deck.slides.add_slide(blank)
        box = slide.shapes.add_textbox(Emu(457200), Emu(228600), Emu(11277600), Emu(1371600))
        frame = box.text_frame
        frame.word_wrap = True
        frame.text = f"{s.title}  ·  {STATUS_LABEL.get(s.status, s.status)}"
        frame.paragraphs[0].runs[0].font.size = Pt(26)
        frame.paragraphs[0].runs[0].font.bold = True
        for text, size in [(s.headline, 18), *((line, 13) for line in s.lines[:6])]:
            para = frame.add_paragraph()
            para.text = text
            para.runs[0].font.size = Pt(size)
        images = [p for p in (s.previous_shot, s.current_shot) if p and (folder / p).exists()]
        top, box_h = 2057400, 4206240
        box_w = 11277600 // max(len(images), 1) - 114300
        for n, image in enumerate(images):
            with Image.open(folder / image) as img:
                ratio = img.width / img.height
            w, h = (
                (box_w, int(box_w / ratio))
                if box_w / ratio <= box_h
                else (int(box_h * ratio), box_h)
            )
            left = 457200 + n * (box_w + 228600)
            slide.shapes.add_picture(str(folder / image), Emu(left), Emu(top), Emu(w), Emu(h))
        foot = slide.shapes.add_textbox(Emu(457200), Emu(6400800), Emu(11277600), Emu(365760))
        foot.text_frame.text = " · ".join(t for t in (s.url, s.footnote) if t)
        foot.text_frame.paragraphs[0].runs[0].font.size = Pt(10)
    deck.save(str(path))


def write_deck(folder: Path, pptx: bool = True) -> list[Path]:
    """Build deck.html (and deck.pptx) next to a run's cases.json and result.json."""
    case = json.loads((folder / "cases.json").read_text(encoding="utf-8"))
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    slides = build_slides(case, result)
    title = f"Competitor pages · {case.get('week', folder.name)}"
    out = [folder / "deck.html"]
    out[0].write_text(render_html(slides, title), encoding="utf-8", newline="\n")
    if pptx:
        try:
            render_pptx(slides, folder, folder / "deck.pptx")
            out.append(folder / "deck.pptx")
        except ImportError:
            pass  # .pptx needs python-pptx; the HTML deck is always written
    return out


# ---- Helpers ---------------------------------------------------------------------------------


def page_of(signal: dict[str, Any]) -> str:
    return "pricing" if "/pricing" in str(signal.get("source", "")) else "home"


def page_url(competitor: str, page: str) -> str | None:
    info = COMPETITORS.get(competitor)
    if not info:
        return None
    return info["pricing_url"][0] if page == "pricing" else info["home_url"][0]


def capture_note(signal: dict[str, Any], tz: ZoneInfo) -> str:
    when = when_local(signal["ts"], tz, "%b %d, %H:%M")
    if signal.get("capture") == "archived":
        return (
            f"Archived copy from {when} (Wayback Machine): the live page blocked automated access"
        )
    return f"Captured live {when}"


def when_local(ts: str, tz: ZoneInfo, fmt: str) -> str:
    try:
        return datetime.fromisoformat(ts).astimezone(tz).strftime(fmt)
    except ValueError:
        return ts


def order(competitor: str) -> tuple[int, str]:
    known = list(DEFAULT_COMPETITORS)
    return (known.index(competitor) if competitor in known else len(known), competitor)
