# Maya's Monday competitor deck

Every Monday, Maya (Head of Growth at Brightloop) rebuilt the same deck by hand for the 11:00 leadership meeting: screenshots of Lovable's, Replit's and Bolt's pricing pages and homepages, with what changed. Two hours, half of it cropping.

This app does that job. Every day it captures those six pages and compares each with its last capture. Every change becomes a signal in the brief's input format. On Mondays, the same pipeline the graders test decides what belongs in the deck and builds it: a summary slide, then one slide per page with the screenshot and each change in the page's own words.

**Her rule, applied throughout:** the competitor's own page is the source of truth. Press, Reddit and ads are never shown as fact.

- **Live app:** [_Brightloop deck app_](https://brightloop-monday-deck.vercel.app/): What's new this week, the deck (built Monday morning, or now for the week so far), a Test page for uploading `cases.json`, and Setup with the run log
- **Decisions:** [decisions.md](decisions.md) · **Traps we found:** [SPOTTED.md](SPOTTED.md) · **Why Maya:** [docs/why-maya.md](docs/why-maya.md) · **Every situation and its test:** [docs/uat.md](docs/uat.md)

## Run it

Fresh clone, zero keys, no install. Python 3.9+ (the `python3` that ships with macOS works).

**The one command that proves it works**, on our data: the signals our daily job collected from the real pages in week 43, in the brief's input format:

```bash
./run --input recordings/weeks/2026-W43/cases.json --output result.json
```

**On your file:**

```bash
./run --input cases.json --output result.json
```

Or upload `cases.json` on the live app's **Test** page and download `result.json`. Both run the same pipeline as the daily job; only the source of the signals differs. Every recorded week is in `recordings/weeks/<week>/cases.json`.

Any file gets a `result.json`. An empty, binary, non-JSON or wrongly shaped file gives the wrapper with the reason in `run.errors`, and the exit code is 0. The exit code is 1 only when `result.json` itself can't be written.

## How it works

```
LIVE  GitHub Actions, daily from 00:15 Israel time, ready by 06:30 (backups to 04:30 UTC)
      capture 6 pages in Chrome (Wayback Machine copy if a page fails, labeled "archived")
      compare each page with its last good capture, like with like
      each change -> one signal in the brief's input shape
      Mondays: last week's signals -> cases.json ──┐
                                                    │      TEST  your cases.json
                                                    ▼             │
                 the pipeline (no keys, no LLM) ◄───────────────────┘
                 read → normalize → decide → group → write → scrub → place every id once
                                                    ▼
                                    result.json → the deck (web + .pptx)
```

**What counts as a change on a captured page:** a plan's price (compared plan by plan, in the same billing view only), a plan added or removed, any line that mentions a price, a percentage or a limit, and the top of the homepage: the headline, the line under it and the buttons next to it. The top of the page is read twice, a few seconds apart, and text that rotates on its own is left out. An archived copy is never compared with a live one, and the archive's own error pages are ignored. Menus and FAQ prose are not compared. Each changed line is labelled with the plan whose card it sits in, only when that's clear. An edit that keeps every number ("1M tokens per month" → "1M tokens/month to try Bolt") is shown as a wording edit, in grey, and doesn't count as a change on the slide.

**The decision tree** (the first branch that decides, decides):
1. **Unsafe or unusable → skipped.** Instructions aimed at an AI (in the text, source or competitor field), a different company with the same name (bolt.eu vs bolt.new), no competitor, no text.
2. **Outside the input's `week`** (in its `timezone`) **→ skipped.** An ad counts if it ran at any point during the week.
3. **Not from the competitor itself → skipped** with "verify on the official page". The exception: if the competitor's own source states the same change, the report joins that item.
4. **A change stated on the competitor's own pricing page or homepage → item.** A current price with no change ("Pro: $25/month") is a fact, not a change, so it's skipped.
5. **The competitor's own blog, changelog, X account or ad announcing a pricing or packaging change → item**, at lower confidence, with "check the official pricing page". Packaging means something moved to or from a named plan, or became free. A feature launched on every plan is a launch: skipped and routed to Noa. Ad creatives are routed to Daniel.

**Grouping:** one item per change, whatever the wording. "Pro plan now costs $30 per month, up from $25" and "Lovable raises Pro plan to $30/month" are one item. Different changes stay separate items, listed by date on the page's slide.

**Mondays:** right after the deck is built, one Slack message goes to the team's channel: what changed, with links, and the .pptx attached (D20).

## Output

The required wrapper (`built_for`, `items`, `skipped`, `run`) with `built_for: "maya"`. For example, the brief's sample gives:

```json
{
  "built_for": "maya",
  "items": [{
    "id": "maya-lovable-1",
    "source_ids": ["pr-401"],
    "confidence": 0.9,
    "action": "Update the Lovable pricing slide: Pro: $20 → $25/month.",
    "why": "Stated on Lovable's own pricing page (https://lovable.dev/pricing) on Oct 23, 2026.",
    "competitor": "Lovable", "page": "pricing", "change": ["Pro: $20 → $25/month"],
    "links": ["https://lovable.dev/pricing"],
    "sources": [{"id": "pr-401", "source": "lovable.dev/pricing", "class": "official"}],
    "cta": {"text": "Open Lovable's pricing page", "url": "https://lovable.dev/pricing"}
  }],
  "skipped": [
    {"id": "pr-402", "reason": "Not from Bolt's own pages (sponsored source); verify on https://bolt.new/pricing. …"},
    {"id": "sg-302", "reason": "Same event as sg-301 (Replit's own source). Third-party news (media source) that isn't a pricing or packaging change."}
  ],
  "run": {"started_at": "…", "cost_usd": 0.0, "errors": []}
}
```

Extra fields inside each item:

| Field | Meaning |
|---|---|
| `competitor` | Canonical competitor name |
| `page` | `pricing`, `home`, or `announcement` (said elsewhere: check the page) |
| `change` | What changed, in the source's own words; `old → new` when both are known |
| `change_detail` | Each change as `{kind, plan, old, new}`, for building slides |
| `links` | The competitor's own page(s) |
| `sources` | Each source id with its class (official, press, community, sponsored, …) |
| `caveats` | Why confidence is below the maximum (e.g. "previous price not stated") |
| `cta` | Only when `output.cta_required_per_item` is true: text plus the page to open |

**Confidence:**
- 0.95: we compared two captures of the official page ourselves.
- 0.9: the official page states the change.
- 0.7: the competitor announced it elsewhere.
- Lowered for a missing date (−0.1), an unclear change (−0.1) or a missing old price (−0.05).

## How we know it works

- **Recorded weeks replay exactly:** a test runs every recorded week again and checks the result matches what was recorded.
- **Adversarial files written blind.** Two agents that never saw the code wrote 96 signals meant to break it, each with the outcome they expected (`tests/fixtures/adversarial/`):
  - broken formats: 22/22;
  - broken top level: 2/2;
  - judgment traps: 37/37;
  - the same changes in unusual wording: 31/35.

  No wrong merges. Scored by `scripts/score_cases.py` and kept by a test.
- **Real data.** The first live runs found problems no synthetic test showed: yearly vs monthly views, the archive's error pages, prices drawn as images. Each one is now a test built from the real capture (`tests/test_real_captures.py`).
- **Real headlines.** 139 news headlines labeled by hand. The "is this about pricing" check scores precision 1.00 and recall 0.85 on a held-out set it was never tuned on.
- **Tests, by situation:**
  - file safety: any broken file still produces an output;
  - odd field shapes, timestamps and the DST week;
  - sources and name collisions;
  - change detection and grouping;
  - safety: injections, secrets, banned words;
  - the output contract on random inputs;
  - recordings replay.

  They run on every pull request, on Python 3.9 and 3.12. A separate CI job repeats the graders' run: fresh clone, Python 3.9, zero keys, `./run` on our week and on the brief's sample.

## Known limits

- **Rule-based reading, by design (no LLM; decision D2).** Slang and paraphrased reports ("a fiver more", "shaved five points off") can be missed. They are skipped with a reason, never shown as fact.
- **Monthly prices only.** Yearly prices aren't tracked yet (D15).
- **Billing views.** Plan prices are compared only within the same view; other lines are compared even across the monthly and yearly views.
- **Some limits aren't read yet:** sizes in MB ("10MB file upload limit") and limits without a number ("No daily token limit").
- **History before Oct 23 comes from the Wayback Machine and has gaps.** Archived Lovable pricing pages show no prices, and some days have no copy (D14). From Oct 23, all six pages are captured live every day.
- **English pages only.** US-style dates (`10/23/2026`) are read as "no date".

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,collect]" && python -m playwright install chrome
pytest
brightloop collect                    # capture today's pages (needs network)
brightloop week --week 2026-W43       # the week's signals -> cases.json, result.json, deck
python scripts/rebuild_history.py --reason "…"   # re-derive all days and weeks from stored captures
python scripts/score_cases.py         # score the adversarial files
python scripts/build_site.py          # the web app in public/
```

| Path | What |
|---|---|
| `src/brightloop/pipeline.py`, `select.py`, `change.py` | The pipeline, its decision tree, change reading |
| `src/brightloop/collect/` | Page capture and signals |
| `src/brightloop/deck.py` | The deck (HTML + .pptx) |
| `api/`, `site/`, `scripts/build_site.py` | The web app (Vercel) |
| `recordings/days/<date>/` | Each day: captures, screenshots, that day's signals |
| `recordings/weeks/<week>/` | Each week: `cases.json`, `result.json`, deck |
| `recordings/runlog.jsonl` | One line per daily run, per Monday deck and per rebuild |
| `.github/workflows/daily.yml` | The daily capture, Monday's deck, and "Run workflow" |
