"""The one pipeline. The web source and the file source both end here.

read -> normalize -> window -> relevance -> group -> trust -> write -> safety -> account
"""

from __future__ import annotations

import re
from typing import Any

from brightloop.contract import build_output, enforce_accounting, new_run
from brightloop.decide import THRESHOLD, assess, group_signals, prices, relevance_reason
from brightloop.normalize import Signal, normalize
from brightloop.window import resolve_timezone, resolve_week, window_reason
from brightloop.write import build_item, skip_reason_for_trust

SECRET_KEY = re.compile(r"(key|token|secret|password|passwd|credential|auth)", re.IGNORECASE)
# Well-known credential formats, redacted wherever they appear (even inside signal text).
SECRET_PATTERNS = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)


def run_pipeline(case: Any) -> dict[str, Any]:
    run = new_run()
    errors = run["errors"]
    raw_signals, input_ids = read_signals(case, errors)
    case = case if isinstance(case, dict) else {}

    tz = resolve_timezone(case.get("timezone"), errors)
    week = resolve_week(case.get("week"), tz, errors)
    output_cfg = case.get("output") if isinstance(case.get("output"), dict) else {}
    cta_required = truthy(output_cfg.get("cta_required_per_item", False))

    skipped: list[dict[str, Any]] = []
    candidates: list[Signal] = []
    for raw in raw_signals:
        try:
            signal = normalize(raw, tz)
        except Exception as exc:  # noqa: BLE001 - one bad signal must never stop the run
            errors.append(f"signal {raw.get('id')!r}: could not be read ({type(exc).__name__})")
            skipped.append({"id": raw.get("id"), "reason": "Could not be read; see run.errors."})
            continue
        reason = window_reason(signal, week) or relevance_reason(signal)
        if reason:
            skipped.append({"id": signal.id, "reason": reason})
        else:
            candidates.append(signal)

    official_prices: dict[str, set[str]] = {}
    for s in candidates:
        if s.source_class in ("official", "observed"):
            official_prices.setdefault(s.competitor, set()).update(prices(s.text))

    items: list[dict[str, Any]] = []
    counters: dict[str, int] = {}
    for group in group_signals(candidates):
        verdict = assess(group, official_prices)
        if verdict.confidence < THRESHOLD:
            reason = skip_reason_for_trust(verdict)
            skipped.extend({"id": s.id, "reason": reason} for s in group)
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", group[0].competitor.lower()).strip("-") or "unknown"
        counters[slug] = counters.get(slug, 0) + 1
        items.append(build_item(f"maya-{slug}-{counters[slug]}", group, verdict, cta_required, tz))

    items.sort(key=lambda item: -item["confidence"])
    output = build_output(items=items, skipped=skipped, run=run)
    scrub(output, banned_words(case), secret_values(case), errors)
    return enforce_accounting(output, input_ids)


def read_signals(case: Any, errors: list[str]) -> tuple[list[dict[str, Any]], list[Any]]:
    """Pull signals out of the input without ever crashing.

    Returns the usable signal dicts and the list of input ids (first occurrence
    order, duplicates removed). Signals without a usable id can't be placed in
    the output, so they are reported in ``errors`` instead.
    """
    if not isinstance(case, dict):
        errors.append("input: top level is not a JSON object; no signals read")
        return [], []

    raw = case.get("signals")
    if raw is None:
        errors.append("input: no 'signals' field")
        return [], []
    if not isinstance(raw, list):
        errors.append("input: 'signals' is not a list; no signals read")
        return [], []

    signals: list[dict[str, Any]] = []
    ids: list[Any] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            errors.append(f"input: signal #{index} is not an object; ignored")
            continue
        sid = entry.get("id")
        if not isinstance(sid, (str, int)) or isinstance(sid, bool) or sid == "":
            errors.append(f"input: signal #{index} has no usable id; ignored")
            continue
        if sid in ids:
            errors.append(f"input: duplicate id {sid!r}; placed once")
            continue
        ids.append(sid)
        signals.append(entry)
    return signals, ids


# ---- Safety: what must never appear in the output ------------------------------


def truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "y")
    return bool(value)


def banned_words(case: dict[str, Any]) -> list[str]:
    brand = case.get("brand") if isinstance(case.get("brand"), dict) else {}
    words = brand.get("banned_words")
    if isinstance(words, str):
        words = words.split(",")
    if not isinstance(words, list):
        return []
    return [w.strip() for w in words if isinstance(w, str) and w.strip()]


def secret_values(case: dict[str, Any]) -> list[str]:
    found: list[str] = []

    def walk(node: Any, key: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, str(k))
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, str) and SECRET_KEY.search(key) and len(node) >= 4:
            found.append(node)

    walk({k: v for k, v in case.items() if k != "signals"})
    return found


def scrub(node: Any, banned: list[str], secrets: list[str], errors: list[str]) -> Any:
    """Remove banned words and secret values from every string we output."""
    patterns = [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in banned]

    def clean(text: str) -> str:
        for secret in secrets:
            if secret in text:
                text = text.replace(secret, "[redacted]")
                errors.append("safety: removed a config secret from the output")
        if SECRET_PATTERNS.search(text):
            text = SECRET_PATTERNS.sub("[redacted]", text)
            errors.append("safety: removed a credential-like string from the output")
        for pattern in patterns:
            if pattern.search(text):
                text = pattern.sub("", text)
                text = re.sub(r"\s{2,}", " ", text).replace(" .", ".").strip()
        return text

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            for k, v in value.items():
                if k != "id" and k != "source_ids":
                    value[k] = walk(v)
            return value
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, str):
            return clean(value)
        return value

    for section in ("items", "skipped"):
        node[section] = walk(node[section])
    return node
