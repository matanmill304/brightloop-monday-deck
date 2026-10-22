# Why we built for Maya

**Decision:** build for Maya (Head of Growth): her Monday competitor deck builds itself. (Decision log D7.)

## What each marketer told us

| | Maya, Head of Growth | Daniel, Paid ads | Noa, PMM / content |
|---|---|---|---|
| **Recurring job** | Every Monday 8:30–10:30: screenshots of Lovable's, Replit's and Bolt's pricing pages and homepages into Google Slides for the 11:00 leadership meeting | Weekly: scroll Meta's Ad Library for competitor angles, write briefs in Notion | Track competitor news, write reaction posts in Google Docs, publish to blog/LinkedIn |
| **Measured pain** | **2 hours a week, half of it cropping screenshots** | ~30 ideas → 4 approved a month; 2–3 h/week on Meta; LinkedIn never checked | ~1 of 3 drafts ships; the same launch arrives 4× (30 min to untangle); 3 days late = dead |
| **How they'd judge a tool** | "Does it shave hours off my Monday? … If it does that, it stays." | Approval rate (visible over weeks) | Publish rate (visible over weeks) |
| **Where they work** | Slides, Sheets, Slack. "If it needs a new login, it's dead." | Notion | Google Docs |

## The options

| | **A. Maya: deck builds itself** ✅ | B. Daniel: proven ad angles | C. Noa: verified news + drafts |
|---|---|---|---|
| Success visible to its owner | **Week 1** | Weeks | Weeks |
| Fits the approver (Maya) | **Her own criterion** | She doubts his briefs ("no clear signup thesis") | "Features are product's problem" |
| Data | **Public pricing pages + homepages: stable, legal** | Meta Ad Library scraping is fragile and likely blocked from cloud servers; LinkedIn has no API and unclear terms | Feeds and official pages |
| Needs an LLM at the core | No | No | Yes (drafts) |
| Cost of a mistake | Medium, made checkable by screenshots + links | Low | High (a wrong public post) |
| Build risk by the deadline | **Low** | High | Medium |

## Why A
1. **Its owner can see the win in week one**, by her own yardstick: a 2-hour job becomes a short review.
2. **She's the approver.** The other two depend on her blessing for areas she doubts.
3. **Her trust rule becomes a feature.** "No link, no number": dated screenshots and links make every number checkable, so a wrong claim (like the "competitor cut prices 30%" summary that once reached leadership) is caught before the deck.
4. **Lowest data risk, no LLM at the core, a natural weekly schedule.**

## What we gave up, and what's next
- **B has the most direct line to signups** (paid ads), but depends on ad data we can't collect reliably or clearly within the platforms' terms. Next step: the same pipeline with an official/commercial ad API and Notion as the destination.
- **C** fits the same pipeline (grouping duplicates, verification, rumor handling are already built for A); adding reaction drafts needs an LLM and a faster schedule.
