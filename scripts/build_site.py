"""Build the static web app in public/ from recordings/.

    python scripts/build_site.py

public/
  index.html               this week's deck, earlier weeks, run log, links
  upload.html              upload a cases.json -> download result.json (calls /api/run)
  weeks/<week>/            deck.html, deck.pptx, cases.json, result.json, run.json, snapshots/
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDINGS = ROOT / "recordings"
PUBLIC = ROOT / "public"
REPO = "https://github.com/matanmill304/brightloop-monday-deck"
RUN_NOW = f"{REPO}/actions/workflows/daily.yml"

STYLE = """
:root{--ink:#14181f;--soft:#5b6472;--line:#dfe3e8;--bg:#f4f5f7;--card:#fff;--accent:#2a46c9}
@media (prefers-color-scheme:dark){:root{--ink:#e8ebef;--soft:#9aa3ae;--line:#2c333c;--bg:#11151a;--card:#181d24;--accent:#8ea2ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;padding:16px}
main{max-width:1100px;margin:0 auto;display:flex;flex-direction:column;gap:16px}
h1{margin:8px 0 0;font-size:28px}h2{margin:0 0 8px;font-size:19px}p{margin:0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px}
a{color:var(--accent)}.soft{color:var(--soft);font-size:14px}
table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.links{display:flex;gap:12px;flex-wrap:wrap}.links a{font-weight:600}
iframe{width:100%;height:80vh;border:1px solid var(--line);border-radius:8px;background:var(--card)}
button{font:inherit;padding:8px 14px;border-radius:6px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer}
pre{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:10px;overflow:auto;max-height:50vh;font-size:13px}
"""


def page(title: str, body: str) -> str:
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>\n"
    )


def build() -> None:
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    weeks = sorted((p.parent for p in RECORDINGS.glob("*-W*/run.json")), reverse=True)
    for folder in weeks:
        target = PUBLIC / "weeks" / folder.name
        shutil.copytree(folder, target)
    (PUBLIC / "index.html").write_text(index_page(weeks), encoding="utf-8", newline="\n")
    (PUBLIC / "upload.html").write_text(upload_page(), encoding="utf-8", newline="\n")
    print(f"built public/ with {len(weeks)} week(s)")


def index_page(weeks: list[Path]) -> str:
    runs = []
    log = RECORDINGS / "runlog.jsonl"
    if log.exists():
        runs = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
    latest = weeks[0].name if weeks else None
    deck = (
        f'<iframe src="weeks/{latest}/deck.html" title="Deck {latest}"></iframe>'
        if latest
        else "<p>No run recorded yet.</p>"
    )
    week_rows = "".join(
        f"<tr><td>{w.name}</td><td><a href='weeks/{w.name}/deck.html'>deck</a> · "
        f"<a href='weeks/{w.name}/deck.pptx'>.pptx</a> · <a href='weeks/{w.name}/cases.json'>"
        f"signals</a> · <a href='weeks/{w.name}/result.json'>result</a></td></tr>"
        for w in weeks
    )
    run_rows = "".join(
        f"<tr><td>{html.escape(r['started_at'])}</td><td>{r['week']}</td><td>{r['mode']}</td>"
        f"<td>{html.escape(', '.join(f'{k}: {v}' for k, v in r['pages'].items()))}</td>"
        f"<td>{r['signals']}</td><td>{r['items']}</td><td>{html.escape('; '.join(r['errors'])) or '-'}</td></tr>"
        for r in reversed(runs)
    )
    return page(
        "Competitor pages: Monday deck",
        f"""
<h1>Competitor pages: Monday deck</h1>
<p class="soft">For Maya, Head of Growth. Every Monday at 07:30 (Israel time) the pricing pages and
homepages of Lovable, Replit and Bolt are captured, compared with last week, and turned into this deck.
Only the competitors' own pages count; every change links to its source.</p>
<div class="links"><a href="weeks/{latest}/deck.pptx">Download this week's .pptx</a>
<a href="upload.html">Test with your own cases.json</a><a href="{RUN_NOW}">Run now (GitHub Actions)</a>
<a href="{REPO}">Code</a></div>
<section class="card"><h2>This week: {latest or "-"}</h2>{deck}</section>
<section class="card"><h2>All weeks</h2><table><tr><th>Week</th><th>Files</th></tr>{week_rows}</table></section>
<section class="card"><h2>Run log</h2><table><tr><th>Started (UTC)</th><th>Week</th><th>Mode</th>
<th>Pages</th><th>Signals</th><th>Items</th><th>Errors</th></tr>{run_rows}</table></section>
""",
    )


def upload_page() -> str:
    return page(
        "Test with your own cases.json",
        """
<h1>Test with your own cases.json</h1>
<p class="soft">Upload a file in the input format; the same pipeline that builds the deck returns
<code>result.json</code>. No keys, nothing stored.</p>
<section class="card"><input type="file" id="file" accept=".json,application/json">
<button id="go" type="button">Run</button> <a id="download" hidden download="result.json">Download result.json</a>
<p id="status" class="soft"></p><pre id="out" hidden></pre></section>
<p><a href="index.html">Back to the deck</a></p>
<script>
const $ = (id) => document.getElementById(id);
$("go").addEventListener("click", async () => {
  const file = $("file").files[0];
  if (!file) { $("status").textContent = "Choose a cases.json file first."; return; }
  $("status").textContent = "Running…";
  try {
    const response = await fetch("/api/run", { method: "POST", body: await file.text(),
      headers: { "Content-Type": "application/json" } });
    const text = await response.text();
    if (!response.ok) throw new Error(text);
    const result = JSON.parse(text);
    $("status").textContent = `${result.items.length} items, ${result.skipped.length} skipped, ${result.run.errors.length} errors.`;
    $("out").textContent = JSON.stringify(result, null, 2); $("out").hidden = false;
    const link = $("download");
    link.href = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
    link.hidden = false;
  } catch (error) { $("status").textContent = "Failed: " + error.message; }
});
</script>
""",
    )


if __name__ == "__main__":
    build()
