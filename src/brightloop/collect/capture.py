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
from datetime import UTC, datetime
from pathlib import Path

USER_AGENT = "BrightloopMondayDeck/0.1 (competitor pricing snapshots; weekly)"
PAUSE_SECONDS = 1.5
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

    def to_json(self) -> dict:
        return asdict(self)


def wayback_closest(url: str, when: datetime) -> tuple[str, str] | None:
    """(timestamp, archived URL) of the Wayback copy closest to `when`, or None."""
    query = urllib.parse.urlencode({"url": url, "timestamp": when.strftime("%Y%m%d%H%M%S")})
    data = fetch_json(f"https://archive.org/wayback/available?{query}")
    closest = (data or {}).get("archived_snapshots", {}).get("closest")
    if not closest or not closest.get("available"):
        return None
    return closest["timestamp"], closest["url"].replace("http://", "https://", 1)


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
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._page = self._browser.new_page(
            viewport={"width": 1440, "height": 1000}, user_agent=None
        )

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()

    def live(self, competitor: str, page: str, url: str) -> Snapshot | None:
        """The page as it is now; None if it's blocked or empty."""
        text, headline = self._render(url)
        if text is None or BLOCK_MARKERS.search(text[:2000]) or len(text) < 200:
            return None
        shot = self._screenshot(competitor, page, "live")
        return Snapshot(competitor, page, url, now_iso(), "live", text, headline, shot)

    def archived(self, competitor: str, page: str, url: str, when: datetime) -> Snapshot | None:
        """The Wayback copy closest to `when`, rendered without the archive toolbar."""
        found = wayback_closest(url, when)
        if not found:
            return None
        timestamp, archive_url = found
        frame_url = re.sub(r"/web/(\d+)/", r"/web/\1if_/", archive_url)
        text, headline = self._render(frame_url)
        if text is None or len(text) < 200:
            return None
        captured = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        shot = self._screenshot(competitor, page, f"archived-{timestamp}")
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
        )

    def _render(self, url: str) -> tuple[str | None, str]:
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
            self._page.wait_for_timeout(6000)
            self._page.add_style_tag(content=HIDE_BANNERS)
            text = self._page.evaluate(VISIBLE_TEXT_JS)
            h1 = self._page.locator("h1").first
            headline = h1.inner_text(timeout=2000) if self._page.locator("h1").count() else ""
            return condense(text), headline.strip()
        except Exception:  # noqa: BLE001 - any capture failure means "try the next method"
            return None, ""
        finally:
            time.sleep(PAUSE_SECONDS)

    def _screenshot(self, competitor: str, page: str, label: str) -> str:
        name = f"{slug(competitor)}-{page}-{label}.jpg"
        self._page.screenshot(path=str(self.out_dir / name), type="jpeg", quality=70)
        return name


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
