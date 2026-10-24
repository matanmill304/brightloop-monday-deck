"""Capture a page: visible text + a screenshot, live first, the Wayback Machine as fallback.

Rules we hold ourselves to:
- A page that shows a bot check or a block is never bypassed. We fall back to the latest
  Wayback Machine copy and label it "archived" with its date.
- Cookie banners are hidden for the screenshot, never accepted.
- Requests are slow and identify themselves.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc  # datetime.UTC is 3.11+

USER_AGENT = "BrightloopMondayDeck/0.1 (competitor pricing snapshots; weekly)"
PAUSE_SECONDS = 1.5
RETRY_SECONDS = 20  # a security check is decided per visit: one more try, a little later
BLOCK_MARKERS = re.compile(
    r"(verify you are human|you have been blocked|just a moment|attention required|access denied"
    r"|performing security verification|enable javascript and cookies|are you a robot)",
    re.IGNORECASE,
)
# Each visible text node on its own line: innerText glues inline elements together
# ("Log in" + "Create account" -> "Log inCreate account"), which looks like a change.
VISIBLE_TEXT_JS = """
() => {
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const el = node.parentElement;
    if (!el || el.closest("svg, script, style, noscript, template")) continue;
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    const text = node.textContent.replace(/\\s+/g, " ").trim();
    if (text) out.push(text);
  }
  return out.join("\\n");
}
"""
# The top of the page, where Maya looks for "new headlines, changed CTAs": the visible h1, the
# closest short text block under it, and the links/buttons near it (outside the nav).
HERO_JS = r"""
() => {
  const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
  const words = (t) => t.split(' ').filter(Boolean).length;
  const shown = (el) => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 20 && r.height > 8 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  // Only the text a person sees: hidden tooltips and screen-reader text are skipped.
  const seen = (el) => {
    const parts = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const parent = walker.currentNode.parentElement;
      if (parent && shown(parent)) parts.push(walker.currentNode.textContent);
    }
    return clean(parts.join(' '));
  };
  const chrome = (el) => !!el.closest('nav, header, footer, [role=navigation], [role=banner], dialog');
  const h1 = [...document.querySelectorAll('h1')].find((el) => shown(el) && clean(el.innerText));
  if (!h1) return null;
  const box = h1.getBoundingClientRect(), top = box.top + window.scrollY, bottom = box.bottom + window.scrollY;
  const y = (el) => el.getBoundingClientRect().top + window.scrollY;
  const INLINE = new Set(['SPAN', 'A', 'STRONG', 'EM', 'B', 'I', 'BR', 'SUP', 'SUB', 'MARK']);
  const sub = [...document.querySelectorAll('p, h2, h3, div, span')]
    .filter((el) => shown(el) && !chrome(el) && !h1.contains(el) && !el.contains(h1))
    .filter((el) => y(el) >= bottom - 4 && y(el) <= bottom + 240)
    .filter((el) => [...el.children].every((c) => INLINE.has(c.tagName)))
    .map((el) => ({ y: y(el), t: seen(el), size: parseFloat(getComputedStyle(el).fontSize) || 0 }))
    .filter((c) => words(c.t) >= 4 && words(c.t) <= 40)
    // The largest text under the headline is the subheadline; hints and tooltips are smaller.
    .sort((a, b) => b.size - a.size || a.y - b.y || a.t.length - b.t.length)[0];
  const buttons = [];
  for (const el of document.querySelectorAll('a, button')) {
    if (!shown(el) || chrome(el) || y(el) < top - 40 || y(el) > top + 480) continue;
    const t = clean(el.innerText);
    if (t && words(t) <= 6 && !buttons.includes(t)) buttons.push(t);
  }
  return { headline: clean(h1.innerText), subheadline: sub ? sub.t : '', buttons: buttons.slice(0, 8) };
}
"""
HIDE_BANNERS = """
[id*="cookie" i], [class*="cookie" i], [id*="consent" i], [class*="consent" i],
[aria-label*="cookie" i], [id*="onetrust" i] { display: none !important; }
"""


@dataclass
class Snapshot:
    competitor: str
    page: str  # pricing | home
    url: str  # the page itself (never the archive URL)
    captured_at: str  # when the content is from (ISO 8601, UTC)
    method: str  # live | archived
    text: str
    headline: str = ""
    screenshot: str | None = None  # path relative to the run folder
    archive_url: str | None = None
    notes: list[str] = field(default_factory=list)
    hero: dict | None = None  # the top of the page: headline, the line under it, its buttons

    def to_json(self) -> dict:
        return asdict(self)


def wayback_latest(url: str, after: datetime, before: datetime) -> tuple[str, str] | None:
    """(timestamp, archived URL) of the latest Wayback copy in [after, before), or None.

    A window, not "closest": the baseline must come from before the week and the current
    copy from inside it.
    """
    query = urllib.parse.urlencode(
        {
            "url": url,
            "from": after.astimezone(UTC).strftime("%Y%m%d%H%M%S"),
            "to": (before - timedelta(seconds=1)).astimezone(UTC).strftime("%Y%m%d%H%M%S"),
            "output": "json",
            "fl": "timestamp",
            "filter": "statuscode:200",
            "limit": "-1",  # the last one in the window
        }
    )
    rows = fetch_json(f"https://web.archive.org/cdx/search/cdx?{query}")
    if not rows or len(rows) < 2:
        return None
    timestamp = rows[-1][0]
    return timestamp, f"https://web.archive.org/web/{timestamp}/{url}"


_CACHE: dict[str, dict | None] = {}


def fetch_json(url: str, attempts: int = 4) -> dict | None:
    """GET JSON politely: on 429/5xx wait (Retry-After, else 15s, 30s, 60s) and try again."""
    if url in _CACHE:
        return _CACHE[url]
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    result = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                result = json.loads(response.read().decode("utf-8"))
                break
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                break
            retry_after = error.headers.get("Retry-After", "")
            time.sleep(int(retry_after) if retry_after.isdigit() else 15 * 2**attempt)
        except (OSError, ValueError):
            break
        finally:
            time.sleep(PAUSE_SECONDS)
    _CACHE[url] = result
    return result


class Capturer:
    """One headless browser for a whole run."""

    def __init__(self, out_dir: Path):
        from playwright.sync_api import (
            sync_playwright,
        )  # optional dependency: pip install .[collect]

        self.out_dir = out_dir
        self.problem: str | None = None  # why the last live capture failed
        self._error: str | None = None
        self._pw = sync_playwright().start()
        # Real Chrome in a window, not headless: Cloudflare blocks headless Chrome on Lovable's
        # homepage and on Replit. On a server, run under a virtual screen (xvfb-run).
        # The window opens off-screen so a daily run on a desktop doesn't get in the way.
        self._browser = self._pw.chromium.launch(
            channel="chrome", headless=False, args=["--window-position=-2400,-2400"]
        )
        self._page = self._browser.new_page(
            viewport={"width": 1440, "height": 1000}, user_agent=None
        )

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()

    def live(self, competitor: str, page: str, url: str, name: str) -> Snapshot | None:
        """The page as it is now; None if it's blocked or empty after a second try.
        `self.problem` then says what was seen (a security check, an empty page), for the
        run log. A security check is never bypassed: the day falls back to the Wayback copy."""
        for attempt in (1, 2):
            text, headline, hero = self._render(url)
            self.problem = self._problem(text)
            if not self.problem:
                shot = self._screenshot(name)
                return Snapshot(
                    competitor, page, url, now_iso(), "live", text, headline, shot, hero=hero
                )
            if attempt == 1:
                time.sleep(RETRY_SECONDS)
        return None

    def _problem(self, text: str | None) -> str | None:
        """Why a live render isn't the page, in plain words; None when it is the page."""
        if text is None:
            return f"didn't load ({self._error or 'error'})"
        if m := BLOCK_MARKERS.search(text[:2000]):
            return f'showed a security check ("{m.group(0)}")'
        if len(text) < 200:
            return f"was almost empty ({len(text)} characters)"
        return None

    def archived(
        self, competitor: str, page: str, url: str, after: datetime, before: datetime, name: str
    ) -> Snapshot | None:
        """The latest Wayback copy in [after, before), rendered without the archive toolbar."""
        found = wayback_latest(url, after, before)
        if not found:
            return None
        timestamp, archive_url = found
        frame_url = re.sub(r"/web/(\d+)/", r"/web/\1if_/", archive_url)
        text, headline, hero = self._render(frame_url)
        if text is None or len(text) < 200:
            return None
        captured = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        shot = self._screenshot(name)
        return Snapshot(
            competitor,
            page,
            url,
            captured.isoformat(timespec="seconds"),
            "archived",
            text,
            headline,
            shot,
            archive_url,
            [f"archived copy from {captured:%b %d, %Y} (Wayback Machine)"],
            hero,
        )

    def _render(self, url: str) -> tuple[str | None, str, dict | None]:
        self._error = None
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
            self._page.wait_for_timeout(6000)
            self._show_monthly_prices()
            self._page.add_style_tag(content=HIDE_BANNERS)
            text = self._page.evaluate(VISIBLE_TEXT_JS)
            h1 = self._page.locator("h1").first
            headline = h1.inner_text(timeout=2000) if self._page.locator("h1").count() else ""
            hero = self._stable_hero()
            return condense(text), headline.strip(), hero
        except Exception as exc:  # noqa: BLE001 - any capture failure means "try the next method"
            self._error = type(exc).__name__
            return None, "", None
        finally:
            time.sleep(PAUSE_SECONDS)

    def _stable_hero(self) -> dict | None:
        """The top of the page, read twice 4 s apart. Text that changed between the two reads
        rotates on its own (Replit's subheadline cycles between two lines), so it is left out:
        comparing it from day to day would report changes that aren't changes."""
        try:
            first = self._page.evaluate(HERO_JS)
            self._page.wait_for_timeout(4000)
            second = self._page.evaluate(HERO_JS)
        except Exception:  # noqa: BLE001 - no hero is not a failed capture
            return None
        if not first or not second:
            return None
        return {
            "headline": first["headline"] if first["headline"] == second["headline"] else "",
            "subheadline": first["subheadline"]
            if first["subheadline"] == second["subheadline"]
            else "",
            "buttons": [b for b in first["buttons"] if b in second["buttons"]],
        }

    def _show_monthly_prices(self) -> None:
        """Pricing pages with a Monthly/Yearly toggle: always capture the monthly view, so two
        weeks are compared in the same view (a normal click on the page's own toggle)."""
        try:
            toggle = self._page.get_by_text(re.compile(r"^\s*Monthly\s*$", re.IGNORECASE)).first
            if toggle.count() and toggle.is_visible():
                toggle.click(timeout=3000)
                self._page.wait_for_timeout(1500)
        except Exception:  # noqa: BLE001, S110 - no toggle or not clickable: keep the default view
            pass

    def _screenshot(self, name: str) -> str:
        """Viewport screenshot (top of the page: plans and prices, the hero) as <name>.jpg."""
        filename = f"{name}.jpg"
        self._page.screenshot(path=str(self.out_dir / filename), type="jpeg", quality=70)
        return filename


def condense(text: str, limit: int = 4500) -> str:
    """Visible text as short lines, duplicates removed, capped (prices sit near the top)."""
    lines, seen = [], set()
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if 1 < len(line) <= 200 and line not in seen:
            seen.add(line)
            lines.append(line)
    out = "\n".join(lines)
    return out[:limit]


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
