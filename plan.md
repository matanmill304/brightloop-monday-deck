# Plan — Brightloop home assignment

> **North star:** Maya's Monday competitor deck builds itself, with every number linked and checkable, and the same logic passes test cases we've never seen, with zero keys.

**Deadline:** Monday morning (2026-10-26). Limited hours, so every phase is time-boxed.
**Built for:** Maya, Head of Growth (see decisions D7–D14, `docs/why-maya.md`).

---

## Task

### What they're testing
1. **Discovery:** talk to the users, pick the one problem worth solving. ✅ Done.
2. **Judgment over AI tools and data:** prompt injection, weak sources, misleading metrics, scope creep (see SPOTTED.md).
3. **Shipping like R&D:** the core loop must run, plus repo hygiene, tests, CI, a run log and a decision log.

### How success is measured
| Gate / score | What has to be true |
|---|---|
| **Hard gate** | Fresh clone, **zero keys**, one command → it runs. "If the core loop doesn't run, we stop reading." |
| **Hidden-case scoring** | Output on unseen cases uses the required wrapper; every input id exactly once; sensible grouping, confidence, action, reasons. |
| **Product fit** | `built_for: "maya"`, matching what we learned. |
| **Rules 1–7** | Live URL + repo; background schedule + run log; real web data; test path; engineering quality; decision log. |
| **Video** | ≤10 min, live, cold start → real output. |

---

## What we build

**The product:** every Monday at 07:30 Israel time, the tool captures Lovable's, Replit's and Bolt's pricing pages and homepages, compares them with last week, decides what is a real pricing/packaging/messaging change worth showing leadership, and produces a deck: screenshots + flagged changes (old vs. new) + links.

**How the required output fits:** `items` = what goes into the deck (one per real change); `skipped` = what was kept out and why (rumors, sponsored claims, feature news → Noa, ad creatives → Daniel). The deck is drawn from the items.

### Architecture
- **Two sources, one pipeline:** a web source (live captures → diff → signals) and a file source (`cases.json` → signals) feed the same pipeline.
- **Outputs:** `result.json`, HTML deck + .pptx download (no keys), Google Slides + Slack message (our keys, built last), web app with run log.
- **Runners:** GitHub Actions runs the collector (Monday cron + "run now"); Vercel hosts the web app.

### Pipeline (deterministic, no keys)
| Step | What it does | Robust to unseen cases because… |
|---|---|---|
| 1. Read | Validates each signal on its own | One bad signal never breaks the run; it's skipped with a reason |
| 2. Normalize | Times, competitor names, types, text | Any timestamp format; input timezone; name variants; embedded instructions stripped and flagged |
| 3. Window | Keeps the reporting week | Week in the input's timezone; ads count if active during it |
| 4. Group | Merges the same event from several sources | Conservative: shared price/plan/version + close in time; look-alikes stay separate |
| 5. Trust | Scores source and claim → confidence | Source class base; independent agreement raises it; hype, hedging, contradicting the official page, injection lower it |
| 6. Relevance to Maya | Pricing/packaging/homepage changes → items; the rest skipped with a reason naming the owner | Judged by content, not declared type |
| 7. Write | `action`, `why`, links, confidence | Templates without keys; banned words and secrets never appear |
| 8. Account | Every input id exactly once | Auto-fixes anything missing and logs an error |

### Real data to collect (no mock data in the app)
- Wayback Machine history of the pricing pages (baseline + real past changes to replay)
- Today's live captures (Playwright): screenshots + text + prices
- Third-party pricing claims (Google News RSS, Reddit): real claims to verify
- Official changelog/blog feeds: packaging launches vs. pure feature launches
- Adversarial cases: test-only, never in the app

---

## Phases

| # | Phase | Hours | Done when | Status |
|---|---|---|---|---|
| 0 | Repo, skeleton, CI, output contract | 1 | `run --input --output` returns valid output | ✅ |
| 1 | Core pipeline + tests | 4–5 | Sample + adversarial suite pass; randomized tests hold | |
| 2 | Live collector (captures, prices, diff, Wayback baseline) + recordings | 3 | A real run produces real changes; replays without keys | |
| 3 | Web app (upload/download, latest deck, run log) on Vercel; HTML deck + .pptx | 2–3 | Live URL works end to end | |
| 4 | Monday schedule + run now (GitHub Actions) + run log | 1 | A scheduled run appears in the log | |
| 5 | Keyed delivery (Google Slides, Slack), last | 1–2 | Monday run posts to Slack with a Slides link | |
| 6 | Show Maya a real deck, README, final docs, video | 2 | Submitted | |

---

## Open questions
- **Future-dated signals / "now":** in file mode the window comes from the input's `week`; how to treat signals after the reporting week is decided in Phase 1.
- **How many hours are available until Monday:** if short, cut Phase 5 first (keep HTML deck + .pptx).
