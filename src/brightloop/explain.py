"""Human-readable explanations, generated from the code that actually runs.

- ``rules_markdown()``: every rule, word list, threshold and table the pipeline uses.
- ``trace_markdown(case)``: what happened to each signal, step by step.
- ``eval_markdown(rows)``: the relevance check on labeled real headlines.
"""

from __future__ import annotations

from datetime import tzinfo
from typing import Any

from brightloop import change, competitors, decide, normalize, pipeline, window
from brightloop import select as sel
from brightloop.normalize import Signal


def rules_markdown() -> str:
    c, d, n = change, decide, normalize
    out = [
        "# Pipeline rules (generated from the code)",
        "",
        ("Order: read → normalize → decision tree (select.py) → write → safety → accounting."),
        "",
        "## 1. Read",
        "- Each signal is read on its own; a broken one never stops the run.",
        (
            "- Not an object, or no usable `id` (string or number, not empty) → reported in "
            "`run.errors` (it can't be placed without an id)."
        ),
        "- Duplicate id → placed once, noted in `run.errors`.",
        "",
        "## 2. Normalize",
        (
            f"- **Text** comes from the first non-empty field of: {fmt(n.TEXT_FIELDS)}. "
            f"Lists/objects are flattened. Capped at {n.MAX_TEXT:,} characters."
        ),
        (
            "- Invisible characters (zero-width spaces, soft hyphens, BOM) are removed first. "
            "HTML tags and `<!-- comments -->` are removed. A sentence matching the "
            "instruction patterns below is removed and the signal is flagged "
            "`embedded_instructions`."
        ),
        (
            f"- **Link** comes from the first of: {fmt(n.SOURCE_FIELDS)}. `.example` domains "
            "keep their domain but get no link (they can't be opened). A Wayback Machine link "
            f"is read as the page it archived: `{n.WAYBACK.pattern}`."
        ),
        (
            f"- **Time** comes from the first parseable of: {fmt(n.TIME_FIELDS)}; ads use "
            "`first_seen`/`last_seen` (a date-only `last_seen` means end of that day). Formats: "
            "ISO 8601 (any offset), `… UTC`/`GMT`, date only, epoch seconds or ms, RFC 2822, "
            "`Oct 23, 2026` style. No timezone → the input's `timezone`."
        ),
        (
            "- **Type**: exact synonym, else a synonym word inside the label "
            "(`PRICING_CHANGE` → pricing); otherwise `other`."
        ),
        "",
        table(["Type", "Synonyms"], [(t, fmt(sorted(s))) for t, s in n.TYPE_SYNONYMS.items()]),
        "",
        "**Instruction patterns** (text aimed at an AI system):",
        code(n.INSTRUCTION_PATTERNS.pattern),
        "",
        "### Source class",
        "Checked in this order; the first match wins.",
        "",
        table(
            ["#", "Class", "When"],
            [
                ("1", "sponsored", f"source text matches `{n.SPONSORED.pattern}`"),
                ("2", "anonymous", f"source text matches `{n.ANONYMOUS.pattern}`"),
                ("3", "guest", f"source text matches `{n.GUEST.pattern}`"),
                ("4", "official", "domain is one of the competitor's own domains"),
                (
                    "5",
                    "official / community",
                    (
                        f"social domain ({fmt(sorted(n.SOCIAL_DOMAINS))}): "
                        "official if the handle is the competitor's, else community"
                    ),
                ),
                ("6", "community", fmt(sorted(n.COMMUNITY_DOMAINS))),
                ("7", "press", fmt(sorted(n.PRESS_DOMAINS))),
                ("8", "media", f"domain contains `{n.MEDIA_WORDS.pattern}`"),
                ("9", "advertiser", "type is `ad` (the competitor's own paid message)"),
                ("10", "unknown", "anything else"),
            ],
        ),
        "",
        (
            'If no domain is given but the source names an official page ("Replit pricing page"), '
            "the competitor's official page becomes the link and the item says so."
        ),
        "",
        "### Competitor dictionary",
        (
            "Names are matched case-insensitively to these aliases. Unknown names are kept as given; "
            "a missing name is taken from the source domain if it's a known one."
        ),
        "",
        table(
            ["Competitor", "Aliases", "Official domains", "Official handles", "Pricing page"],
            [
                (name, fmt(i["aliases"]), fmt(i["domains"]), fmt(i["handles"]), i["pricing_url"][0])
                for name, i in competitors.COMPETITORS.items()
            ],
        ),
        "",
        "### Name collisions",
        (
            "- **Look-alike domain**: a domain label equals a bare competitor name (e.g. `bolt` in "
            "`bolt.eu`, `bolt.com`) but the domain is not an official one → skipped."
        ),
        "- **Collision words** with no software context → skipped.",
        "",
        table(["Competitor", "Collision words"], list(n.COLLISION_WORDS.items())),
        "",
        "Software context (cancels collision words):",
        code(n.SOFTWARE_CONTEXT.pattern),
        "",
        "## 3. The decision tree (select.py)",
        (
            'Maya: the competitor\'s own pricing page is "the source of truth"; press or Reddit '
            '"wouldn\'t make the deck without me verifying it against the actual page".'
        ),
        "",
        "Every signal goes down these branches in order; the first branch that decides, decides:",
        "",
        table(
            ["#", "Branch", "Outcome"],
            [
                (
                    "1",
                    "Embedded instructions / name collision / no competitor / no text",
                    "skipped, with the reason",
                ),
                ("2", "Dated after the reporting week", "skipped"),
                (
                    "2",
                    "Dated before the reporting week",
                    "kept only as a **baseline snapshot** of its page; otherwise skipped",
                ),
                (
                    "3",
                    (
                        "Not from the competitor itself (press, community, sponsored, anonymous, "
                        "unknown)"
                    ),
                    (
                        'skipped: "verify on <official pricing page>", or "isn\'t a pricing '
                        'change", or "same change as item X"'
                    ),
                ),
                (
                    "4",
                    "Competitor's **pricing page or homepage**, states a change",
                    f"item, confidence {sel.CONF_PAGE}",
                ),
                (
                    "4",
                    "Competitor's pricing page or homepage, states only the current state",
                    (
                        f"compared with another snapshot of the same page: different → item, "
                        f"confidence {sel.CONF_COMPARED}; same or nothing to compare → skipped"
                    ),
                ),
                (
                    "5",
                    (
                        "Competitor's own other channel (blog, changelog, its X account, its ad) "
                        "with a pricing/packaging change, or its ad naming a price"
                    ),
                    f'item, confidence {sel.CONF_ANNOUNCED}, action "check the official page"',
                ),
                (
                    "5",
                    "Competitor's own other channel, anything else",
                    "skipped: feature → Noa; ad → Daniel (flagged if running 8+ weeks)",
                ),
            ],
        ),
        "",
        (
            "**Reporting week**: `week` (ISO, e.g. `2026-W43`) is Monday 00:00 to the next Monday "
            "00:00 in the input's `timezone` (DST inside the week is handled). Ads count if active "
            "during the week. No date → treated as in the week (−0.1). No/invalid `week` → no filter."
        ),
        "",
        (
            "**Which page** (from the URL): host must be the competitor's main domain or `www` "
            '(a subdomain like `status.bolt.new` or `blog.replit.com` is "other"); path '
            f"`{n.PRICING_PATH.pattern}` → pricing page; `/` → homepage. Without a URL, a source "
            'naming "pricing page" / "homepage" decides.'
        ),
        "",
        (
            "**Official** = the competitor's own domain (dictionary above; for an unlisted "
            'competitor, a domain named after it, e.g. `acmeai.io` for "Acme AI"), its own social '
            "handle, or its own ad (ad library)."
        ),
        "",
        "## 4. Detecting a change inside a signal (change.py)",
        (
            'Domain names are masked first ("Bolt.new" is not the word "new"). Company-finance '
            "text (funding, valuation, revenue) is never a price change. Then, first match wins:"
        ),
        "",
        table(
            ["Change", "Pattern"],
            [
                ("price (old stated)", f"`{c.PREVIOUSLY.pattern}`"),
                (
                    "number (old stated)",
                    f"`{c.NUMBER_PREVIOUSLY.pattern}` → limits if a limit word",
                ),
                (
                    "price (from → to)",
                    (
                        f"`{c.FROM_TO.pattern}` (every match is reported; the same number on both "
                        "sides is not a change)"
                    ),
                ),
                ("wording", f"`{c.QUOTED_PAIR.pattern}`"),
                ("plan removed", f"`{c.PLAN_REMOVED.pattern}`"),
                ("renamed", f"`{c.RENAMED.pattern}`"),
                ("plan added", f"`{c.PLAN_ADDED.pattern}`"),
                (
                    "limits",
                    f"price verb `{c.PRICE_VERB.pattern}` + `{c.LIMITS.pattern}`, no amount",
                ),
                ("price (verb)", "price verb + anything"),
                ("availability", f"`{c.AVAILABILITY.pattern}`"),
                ("price (new only)", f"change word + an amount: `{c.GENERIC_CHANGE.pattern}`"),
                ("other", "change word, no amount"),
            ],
        ),
        "",
        (
            "**Comparing two snapshots** of the same page (same competitor + same page type): "
            "plan → price pairs are read with "
            f"`{c.PLAN_PRICE.pattern}`; changed prices, added and removed plans are reported; "
            "if no plan prices are readable, the set of amounts is compared; then the visible "
            "text lines (noise like dates, cookie and copyright lines removed) are compared: "
            'added and removed lines are the homepage "visual diff".'
        ),
        "",
        "Noise lines ignored when comparing text:",
        code(c.NOISE_LINE.pattern),
        "",
        (
            "**Failed capture guard**: if the earlier snapshot had amounts and the later one has "
            "none and at most 2 text lines, it's treated as a failed capture (skipped, \"check the "
            'page") rather than "every price removed".'
        ),
        "",
        "Domain names are masked before reading change words:",
        code(c.DOMAIN_LIKE.pattern),
        "",
        "## 5. Is an official announcement about pricing? (decide.py)",
        (
            "Only branch 5 and the third-party wording still read the topic. **Pricing score** "
            "(sum of the cues that fire), relevant at 2+:"
        ),
        "",
        table(
            ["Cue", "Points", "Pattern"],
            [
                ("price with a unit", 2, f"`{d.PRICE_WITH_UNIT.pattern}`"),
                ("pricing words", 2, f"`{d.PRICE_WORDS.pattern}`"),
                ("usage limits", 2, f"`{d.USAGE_LIMITS.pattern}`"),
                ("packaging phrase", 2, f"`{d.PACKAGING.pattern}`"),
                ("cost change", 2, f"`{d.COST_CHANGE.pattern}` AND `{d.COST_OBJECT.pattern}`"),
                ("plan words", 1, f"`{d.PLAN_WORDS.pattern}`"),
                ("plan name next to an amount", 1, f"`{d.PLAN_PRICE.pattern}`"),
                ("amount + change word", 1, f"amount AND `{d.CHANGE_WORDS.pattern}`"),
            ],
        ),
        "",
        (
            "**Company finance cap**: with no price with a unit, no pricing words and no plan "
            "words, a text matching this is capped at 1 (money is not a price):"
        ),
        code(d.COMPANY_FINANCE.pattern),
        "",
        "## 6. Confidence",
        "",
        table(
            ["Situation", "Confidence"],
            [
                ("We compared two snapshots of the official page", sel.CONF_COMPARED),
                ("The official page states the change", sel.CONF_PAGE),
                ("The competitor announced it elsewhere (check the page)", sel.CONF_ANNOUNCED),
                ('…the page says "changed" but not what', "−0.10"),
                ("…new price stated, old price not", "−0.05"),
                ("…no date", "−0.10"),
                ("Third party", "never an item"),
            ],
        ),
        "",
        (
            "Merging: a page item absorbs the competitor's own announcements of the same change "
            "(same competitor, ≤72 h, a shared amount, or 2+ shared words incl. one non-generic)."
        ),
        "",
        "## 7. Write (write.py)",
        (
            "- `action`: `Update the <competitor> <pricing|homepage> slide: <what changed>.` For "
            "announcements: `Check <official pricing page> before the 11:00 meeting: <competitor> "
            "announced <…>. Add it to the slide only if the page shows it.`"
        ),
        (
            "- `why`: where and when it was seen (input timezone), or which two snapshots were "
            "compared. Facts only."
        ),
        (
            "- Extra fields: `competitor`, `page` (pricing / home / announcement), `change` "
            "(old → new when known), `links`, `sources` (id, source, class), `caveats`, `cta` (only "
            "when `output.cta_required_per_item` is true)."
        ),
        "",
        "## 8. Safety",
        (
            "- Banned words (`brand.banned_words`, list or comma string) are removed from every "
            "output string except ids."
        ),
        "- Config values under keys matching `" + pipeline.SECRET_KEY.pattern + "` are "
        "redacted anywhere in the output.",
        "- Credential formats are redacted anywhere:",
        code(pipeline.SECRET_PATTERNS.pattern),
        "",
        "## 9. Accounting",
        (
            "Every input id ends up exactly once (in an item's `source_ids` or in `skipped`). "
            "Missing ids are added to `skipped`, repeats and unknown ids removed; every repair "
            "is written to `run.errors`."
        ),
    ]
    return "\n".join(out) + "\n"


def trace_markdown(case: Any, title: str) -> str:
    output = pipeline.run_pipeline(case)
    placed: dict[Any, str] = {}
    for item in output["items"]:
        caveats = f" (caveats: {'; '.join(item['caveats'])})" if item.get("caveats") else ""
        for sid in item["source_ids"]:
            others = [s for s in item["source_ids"] if s != sid]
            merged = f", merged with {fmt(others)}" if others else ""
            placed[sid] = (
                f"**ITEM `{item['id']}`**, confidence {item['confidence']}{merged}{caveats}\n"
                f"  - action: {item['action']}\n  - why: {item['why']}"
            )
    for skip in output["skipped"]:
        placed[skip["id"]] = f"**SKIPPED**: {skip['reason']}"

    errors: list[str] = []
    raw_signals, _ = pipeline.read_signals(case, errors)
    case = case if isinstance(case, dict) else {}
    tz = window.resolve_timezone(case.get("timezone"), [])
    week = window.resolve_week(case.get("week"), tz, [])

    lines = [
        f"# Trace: {title}",
        "",
        (
            f"Week: {week.label if week else 'none (no date filter)'} · timezone: {tz} · "
            f"{len(output['items'])} items · {len(output['skipped'])} skipped"
        ),
        "",
    ]
    if output["run"]["errors"]:
        lines += ["Run errors:", *[f"- {e}" for e in output["run"]["errors"]], ""]
    for raw in raw_signals:
        signal = normalize.normalize(raw, tz)
        lines += trace_signal(signal, tz, week, placed.get(signal.id, "(not placed)"))
    return "\n".join(lines) + "\n"


def trace_signal(signal: Signal, tz: tzinfo, week: Any, result: str) -> list[str]:
    cues = decide.pricing_cues(signal.text)
    cue_text = " + ".join(f'{name} ({pts}: "{m}")' for name, (pts, m) in cues.items())
    when = signal.when.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z") if signal.when else "none"
    week_check = {"in": "inside the week", "before": "before the week", "after": "after the week"}[
        sel.place_in_week(signal, week)
    ]
    stated = change.stated_change(signal.text)
    stated_text = (
        f'{stated.kind} ("{stated.evidence}"){": " + change.describe(stated) if change.describe(stated) else ""}'
        if stated
        else "none (states a fact only)"
    )
    origin = (
        "its own pricing page or homepage"
        if signal.on_page
        else "the competitor itself, another channel"
        if signal.official
        else "a third party"
    )
    return [
        f"## `{signal.id}`",
        (
            f"- Input: type `{signal.raw_type or '-'}` · competitor "
            f"`{signal.raw.get('competitor', '-')}` · source `{signal.source or '-'}`"
        ),
        (
            f"- Read as: **{signal.type}** · **{signal.competitor}** · source class "
            f"**{signal.source_class}** · domain `{signal.domain or '-'}` · link "
            f"{signal.url or '-'} · time {when}"
        ),
        f'- Text used: "{signal.text[:400]}"',
        f"- Flags: {fmt(signal.flags) if signal.flags else 'none'}",
        f"- Week: {week_check}",
        f"- From: **{origin}** · page **{signal.page}**",
        f"- Change stated: {stated_text}",
        f"- Pricing score (used for announcements only): **{decide.pricing_score(signal.text)}**"
        + (f" = {cue_text}" if cue_text else ""),
        f"- Result: {result}",
        "",
    ]


def eval_markdown(sets: dict[str, list[dict[str, Any]]]) -> str:
    lines = ["# Relevance on real headlines", ""]
    for name, rows in sets.items():
        tp = fp = fn = 0
        body = []
        for row in rows:
            score = decide.pricing_score(row["title"])
            predicted, gold = score >= 2, row["label"] == "pricing"
            tp += predicted and gold
            fp += predicted and not gold
            fn += gold and not predicted
            verdict = (
                "✅" if predicted == gold else ("❌ false alarm" if predicted else "❌ missed")
            )
            cues = ", ".join(decide.pricing_cues(row["title"])) or "-"
            body.append((verdict, row["label"], score, row["title"], cues))
        body.sort(key=lambda r: (r[0] == "✅", r[1]))
        lines += [
            (
                f"## {name}: precision {tp / (tp + fp):.2f}, recall {tp / (tp + fn):.2f} "
                f"({len(rows)} headlines)"
            ),
            "",
            table(["", "Label", "Score", "Headline", "Cues"], body),
            "",
        ]
    return "\n".join(lines) + "\n"


def table(headers: list[str], rows: list[tuple[Any, ...]]) -> str:
    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(out)


def code(text: str) -> str:
    return f"```\n{text}\n```"


def fmt(values: Any) -> str:
    return ", ".join(f"`{v}`" for v in values)
