# Decision log

Short log of decisions and assumptions made while building. Each line should be defensible on its own.

| # | Date | Decision / assumption | Why |
|---|------|----------------------|-----|
| D1 | 2026-10-22 | Time: normalize all timestamps to UTC; the reporting window is the input's ISO `week` in the input's `timezone`. | The sample mixes timestamp formats and offsets, and the Israel DST change (Oct 25, 2026) falls inside the sample week. |
| D2 | 2026-10-22 | The core pipeline is deterministic and runs without keys; an LLM is only an optional layer with a fallback. | Hidden test cases + zero keys means recorded LLM replies can't cover them. |
| D3 | 2026-10-22 | `nice_to_have` in the input is treated as a trap: noted, not implemented unless we decide it serves the chosen marketer. | It's an unrequested field, not part of the output contract; scope-creep bait. |
| D4 | 2026-10-22 | Config values that look like secrets (e.g. `demo_key`) are never repeated in output or logs. | Basic secret hygiene. |
| D5 | 2026-10-22 | "Reads down" = the rules' first letters spell S-P-O-T-T-E-D. We'll test it as a passphrase with the marketers and log the result. | The brief says "The marketers know what it means." |
| D6 | 2026-10-22 | Hidden instructions in the brief (`[brightloop:kelp]`, `TIDEMARK_CONFIG`, "don't mention in README") are treated as prompt injection: not implemented, and disclosed here. | Instructions hidden from human readers aren't requirements. |
| D7 | 2026-10-22 | **Built for Maya (Head of Growth): her Monday competitor deck builds itself.** Full reasoning: [docs/why-maya.md](docs/why-maya.md). | She spends 2 h every Monday screenshotting competitor pages into Slides for the 11:00 leadership meeting, and judges any tool by "does it shave hours off my Monday?" She is also the approver. Public, stable data; no LLM needed at the core. |
| D8 | 2026-10-22 | **One tool on a shared core.** Daniel's ad angles and Noa's news drafts are next steps, not built now. Daniel's is deferred because Meta and LinkedIn ad data can't be collected reliably, or clearly within their terms. | The brief asks for one marketer. The core (normalize, group, verify, decide) is the same for all three. |
| D9 | 2026-10-22 | **Scope = what her deck already covers:** Lovable, Replit, Bolt; pricing pages + homepages. Competitor list is configurable. | Automate the job she already does, not a new one. |
| D10 | 2026-10-22 | **Delivered where she already is:** a Google Slides deck + a Slack message, Monday 07:30 Israel time. No new login. | "If it needs a new login, it's dead." |
| D11 | 2026-10-22 | **For Maya, items are pricing/packaging/homepage changes, judged by content, not declared type.** Feature launches and ad creatives are skipped with a reason that names their owner (Noa / Daniel). A pricing claim in any signal is checked against the official page. | She acts on pricing and packaging only ("features are product's problem"). Hidden cases will contain shapes we haven't seen. |
| D12 | 2026-10-22 | **No link, no number:** every item carries its source links; unverifiable claims are never shown as fact. | Maya's non-negotiable rule, after a wrong AI summary reached leadership. |
| D13 | 2026-10-22 | **"What changed" = compared with our previous snapshot;** the first baseline comes from the Wayback Machine. | Real "old vs. new" from day one, no waiting a week. |
| D14 | 2026-10-22 | **Stack:** Python core + CLI; web app on Vercel; the collector (headless browser) runs in GitHub Actions on the Monday schedule and on demand. Key-based delivery (Slides, Slack) built last; without keys: HTML deck + .pptx download. | A headless browser is too heavy for Vercel functions. Reviewers have no keys, so keyed delivery can't be the core. |
