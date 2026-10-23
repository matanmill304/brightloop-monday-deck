# Maya's Monday competitor deck

Every Monday at 08:30, Maya (Head of Growth at Brightloop) used to rebuild the same competitor deck by hand for the 11:00 leadership meeting: screenshots of Lovable's, Replit's and Bolt's pricing pages and homepages. Two hours a week, half of it cropping.

This app does it for her. Every Monday at 07:30 (Israel time) it captures those six pages, compares them with last week, turns each change into a signal, decides what belongs in the deck, and builds the deck: a screenshot per page, what changed (old → new), and a link to the competitor's own page. Her rule, applied throughout: **the competitor's own pricing page is the source of truth**; press, Reddit and ads are never shown as fact.

- **Live app:** [_URL added at deploy_](https://brightloop-monday-deck.vercel.app/)
- **Why Maya:** [docs/why-maya.md](docs/why-maya.md) · **Decisions:** [decisions.md](decisions.md) · **Traps we found:** [SPOTTED.md](SPOTTED.md)

## Prove it works (fresh clone, zero keys, no install)

Needs Python 3.9+ only (the `python3` that ships with macOS works).

```bash
./proof
```

It replays every recorded real run in `recordings/` (the result must match the recording exactly), runs the brief's sample input and a file of 27 edge cases, and checks the output contract. Exit code 0 = good.

## Run the test file

```bash
./run --input cases.json --output result.json
```

Or upload `cases.json` on the live app's **Test** page and download `result.json`. Both run the same pipeline as the scheduled job; only the source of the signals differs.

Any file gets a `result.json`: an empty, binary, non-JSON or wrongly shaped file gives the empty wrapper with the reason in `run.errors` (exit code 0). The exit code is 1 only when `result.json` itself can't be written.

## How it works

```
daily (GitHub Actions, 04:30 UTC)                      test (./run or the upload page)
  capture 6 pages (live; Wayback copy if blocked)        your cases.json
  compare with the day before                                  │
  each change -> one signal (the brief's input shape)          │
Mondays: last week's signals -> cases.json ────────────────────┤
                                                               ▼
                      the pipeline (src/brightloop/select.py, no keys)
                      read → normalize → decision tree → write → safety → accounting
                                                               ▼
                                                         result.json → deck (HTML + .pptx)
```

**The decision tree** (first branch that decides, decides):
1. Unsafe or unusable (instructions aimed at AI, name collision like bolt.eu vs bolt.new, no competitor, no text) → skipped.
2. Outside the input's `week` (in its `timezone`) → skipped.
3. Not from the competitor itself (press, community, sponsored, anonymous) → skipped: "verify on <official page>".
4. The competitor's own pricing page or homepage, and a **change** (stated, or found by comparing two snapshots) → **item**. A state with no change ("Pro: $25/month") is a fact, not a change → skipped.
5. The competitor's own blog, changelog, X account or ad announcing a pricing change → **item** with "check the official pricing page" (lower confidence). Feature launches → skipped, routed to Noa; ad creatives → skipped, routed to Daniel.

Full rules, every pattern and word list: run `python scripts/review_pack.py` (writes `review/1-pipeline-rules.md`, generated from the code).

## Output

The required wrapper (`built_for`, `items`, `skipped`, `run`), with `built_for: "maya"`. Extra fields inside each item:

| Field | Meaning |
|---|---|
| `competitor` | Canonical competitor name |
| `page` | `pricing`, `home`, or `announcement` (said elsewhere; check the page) |
| `change` | What changed, `old → new` when both are known |
| `links` | The competitor's own page(s) |
| `sources` | Each source id with its class (official, press, community, …) |
| `caveats` | Why confidence is below the maximum (e.g. "previous price not stated") |
| `cta` | Only when `output.cta_required_per_item` is true: text + the page to open |

Confidence: 0.95 two snapshots of the official page compared · 0.9 stated on the official page · 0.7 announced by the competitor elsewhere · −0.1 no date or unclear change · −0.05 old price not stated.

## How we know it works

- **`./proof`**: recorded real runs replay exactly; contract checks.
- **`pytest`** (130+ tests), listed by situation in **[docs/uat.md](docs/uat.md)**: input robustness, the week and DST, sources and name collisions, change detection, snapshots, safety (injection, secrets, banned words), output.
- **35 adversarial signals** built to break it (`tests/adversarial_cases.py`): all handled except 2 documented weaknesses, which tests keep honest.
- **Real headlines**: 139 real news headlines labeled by hand; the "is this about pricing" check scores precision 1.00 and recall 0.85 on a held-out set it was never tuned on.
- **Real pages**: the first live runs found and fixed problems no synthetic test showed (archived vs live renders, menu text, inline-SVG CSS, glued words).

## Known limits

- Without keys, reading is rule-based: unusual wording can be missed (it's skipped with a reason, never shown as fact). There is no LLM by design: the live app and a keyless clone run the same rules (decisions D26).
- English pages; US-style dates (`10/23/2026`) are read as "no date".
- Replit's pages and Lovable's homepage block automated access. We never bypass that: those come from the Wayback Machine's latest copy, labeled with its date, which can be days old or missing.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,collect]" && python -m playwright install chromium
pytest
brightloop collect                 # capture today's pages, compare with the day before (needs network)
brightloop week --week 2026-W43    # the week's signals -> cases.json, result.json, deck
python scripts/backfill.py --weeks 3   # one-time history from the Wayback Machine (slow)
python scripts/build_site.py       # the web app in public/
```

| Path | What |
|---|---|
| `src/brightloop/pipeline.py`, `select.py`, `change.py` | The pipeline and its decision tree |
| `src/brightloop/collect/` | Page capture and event signals |
| `src/brightloop/deck.py` | The deck (HTML + .pptx) |
| `api/run.py`, `scripts/build_site.py` | The web app (Vercel) |
| `recordings/days/<date>/` | Each day: snapshots, screenshots, that day's signals |
| `recordings/weeks/<week>/` | Each Monday: the week's `cases.json`, `result.json`, deck |
| `.github/workflows/daily.yml` | The daily capture, Monday's deck (and "run now") |
