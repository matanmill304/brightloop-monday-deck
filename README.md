# Maya's Monday competitor deck

Every Monday at 08:30, Maya (Head of Growth at Brightloop) rebuilds the same competitor deck by hand for the 11:00 leadership meeting: screenshots of Lovable's, Replit's and Bolt's pricing pages and homepages. Two hours a week, half of it cropping.

This tool does that job for her: it captures the pages, compares them with last week, decides which changes are real and worth leadership's attention, and builds the deck. Every number carries its source link.

> Status: work in progress (Phase 0, skeleton). See [plan.md](plan.md).

## Run it

Requires Python 3.11+.

```bash
pip install .
brightloop run --input cases.json --output result.json
```

No keys are needed.

## Docs

- [plan.md](plan.md): what we're building and in what order
- [decisions.md](decisions.md): the decision log
- [docs/why-maya.md](docs/why-maya.md): why we built for Maya
- [SPOTTED.md](SPOTTED.md): traps we found and what we did about them
