"""Human-readable explanations, generated from the code that actually runs.

- ``rules_markdown()``: every rule, word list, threshold and table the pipeline uses.
- ``trace_markdown(case)``: what happened to each signal, step by step.
- ``eval_markdown(rows)``: the relevance check on labeled real headlines.
"""

from __future__ import annotations

from datetime import tzinfo
from typing import Any

from brightloop import competitors, decide, normalize, pipeline, window, write
from brightloop.normalize import Signal


def rules_markdown() -> str:
    d, n = decide, normalize
    out = [
        "# Pipeline rules (generated from the code)",
        "",
        (
            "Order: read → normalize → reporting week → relevance to Maya → group → trust → "
            "write → safety → accounting."
        ),
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
            "- HTML tags and `<!-- comments -->` are removed. A sentence matching the "
            "instruction patterns below is removed and the signal is flagged "
            "`embedded_instructions`."
        ),
        (
            f"- **Link** comes from the first of: {fmt(n.SOURCE_FIELDS)}. `.example` domains "
            "keep their domain but get no link (they can't be opened)."
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
        "## 3. Reporting week",
        (
            "- `week` (ISO, e.g. `2026-W43`) is computed in the input's `timezone`: Monday 00:00 to "
            "the next Monday 00:00, local time (so a DST change inside the week is handled)."
        ),
        "- Before the week → skipped; on or after the next Monday → skipped.",
        "- Ads count if they were active at any point during the week.",
        "- No date → kept (confidence −0.1). No/invalid `week` → no date filter (noted in errors).",
        "",
        "## 4. Relevance to Maya (pricing, packaging, homepage messaging)",
        "Checked in this order:",
        "1. No text → skipped.",
        "2. Name collision (domain or words) → skipped.",
        "3. No competitor named → skipped.",
        "4. **Pricing score ≥ 2**, or a homepage messaging change from an official source → kept.",
        (
            "5. Otherwise skipped, with a reason naming the owner: ads → Daniel; feature launches → "
            "Noa; mislabeled `pricing` → says so. Ads running 8+ weeks are flagged as worth "
            "passing to Daniel."
        ),
        "",
        "**Pricing score** (sum of the cues that fire):",
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
            "**Company finance cap**: if the text matches the pattern below and has no price with "
            "a unit, no pricing words and no plan words, the score is capped at 1 (money is not a "
            "price: funding, valuation, revenue)."
        ),
        code(d.COMPANY_FINANCE.pattern),
        "",
        "**Homepage messaging** (official sources only):",
        code(d.MESSAGING.pattern),
        "",
        "## 5. Group (same event from several sources)",
        (
            f"Two signals are the same event when all hold: same known competitor; within "
            f"{int(d.SAME_EVENT_WINDOW.total_seconds() // 3600)} hours (if both dated); if both "
            "name amounts, they share one; and they share an amount, or share 2+ content words "
            "of which at least one is not generic. Groups are transitive."
        ),
        "",
        (
            f"Generic words (don't make two reports the same event on their own): "
            f"{fmt(sorted(d.GENERIC))}"
        ),
        "",
        "## 6. Trust → confidence",
        "",
        table(["Best source in the group", "Base"], list(d.BASE_TRUST.items())),
        "",
        table(
            ["Adjustment", "Effect"],
            [
                ("Each extra independent source (different domain/class)", "+0.10, max +0.15"),
                ("Absolute claim, no official source", f"−0.20  `{d.HYPE.pattern}`"),
                ("Every report hedged", f"−0.25  `{d.HEDGE.pattern}`"),
                ("Amounts contradict the official source this week", "−0.30"),
                ("No date", "−0.10"),
                ("No link anywhere in the group (no link, no number)", "capped at 0.40"),
                ("Instructions aimed at AI systems", "capped at 0.20"),
                ("Final", "clamped to 0–0.95"),
            ],
        ),
        "",
        (
            f"**Threshold**: confidence ≥ {d.THRESHOLD} → item; below → every signal in the group "
            "is skipped with the reasons."
        ),
        "",
        "## 7. Write",
        (
            "- `action`: `Flag on the <competitor> slide: <first sentence of the best source> "
            "Check the linked source before the 11:00 meeting.`"
        ),
        (
            "- `why`: who reported it and when (input timezone), which other sources agree, why it "
            "matters (packaging/messaging), and a note if the link came from a named page."
        ),
        (
            "- Extra fields: `competitor`, `kind` (price_change / packaging / messaging), `links`, "
            "`sources` (id, source, class), `caveats` (why confidence went down), `cta` (only "
            "when `output.cta_required_per_item` is true: text + the first link)."
        ),
        "- Lead source order: " + fmt(write.TRUST_ORDER),
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
    week_check = window.window_reason(signal, week) or "inside the week"
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
        f"- Pricing score: **{decide.pricing_score(signal.text)}**"
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
