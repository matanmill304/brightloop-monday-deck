"""The output wrapper the reviewers score against, and the accounting rule.

Rule from the brief: every input id ends up in exactly one place, inside an
item's ``source_ids`` or in ``skipped``. Nothing may silently disappear.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from brightloop import BUILT_FOR


def new_run(started_at: datetime | None = None) -> dict[str, Any]:
    started = started_at or datetime.now(UTC)
    return {
        "started_at": started.isoformat(timespec="seconds"),
        "cost_usd": 0.0,
        "errors": [],
    }


def build_output(
    items: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    run: dict[str, Any],
) -> dict[str, Any]:
    return {"built_for": BUILT_FOR, "items": items, "skipped": skipped, "run": run}


def enforce_accounting(output: dict[str, Any], input_ids: list[Any]) -> dict[str, Any]:
    """Make sure every input id appears exactly once across items and skipped.

    Missing ids are added to ``skipped``; extra or repeated placements are
    removed. Every repair is recorded in ``run.errors`` so it never happens
    silently.
    """
    errors = output["run"]["errors"]
    expected = _unique(input_ids)
    expected_set = set(expected)
    seen: set[Any] = set()

    for item in output["items"]:
        kept = []
        for sid in item.get("source_ids", []):
            if sid not in expected_set:
                errors.append(
                    f"accounting: removed unknown id {sid!r} from item {item.get('id')!r}"
                )
            elif sid in seen:
                errors.append(
                    f"accounting: removed repeated id {sid!r} from item {item.get('id')!r}"
                )
            else:
                kept.append(sid)
                seen.add(sid)
        item["source_ids"] = kept
    empty = [item for item in output["items"] if not item["source_ids"]]
    for item in empty:
        errors.append(f"accounting: dropped item {item.get('id')!r} with no remaining source ids")
    output["items"] = [item for item in output["items"] if item["source_ids"]]

    kept_skips = []
    for skip in output["skipped"]:
        sid = skip.get("id")
        if sid not in expected_set:
            errors.append(f"accounting: removed unknown id {sid!r} from skipped")
        elif sid in seen:
            errors.append(f"accounting: removed repeated id {sid!r} from skipped")
        else:
            kept_skips.append(skip)
            seen.add(sid)
    output["skipped"] = kept_skips

    for sid in expected:
        if sid not in seen:
            output["skipped"].append(
                {"id": sid, "reason": "Not processed (internal error); see run.errors."}
            )
            errors.append(f"accounting: id {sid!r} was not placed by the pipeline")
            seen.add(sid)

    return output


def check_contract(output: dict[str, Any], input_ids: list[Any]) -> list[str]:
    """Return a list of contract violations (empty when the output is valid)."""
    problems: list[str] = []
    for key in ("built_for", "items", "skipped", "run"):
        if key not in output:
            problems.append(f"missing top-level key {key!r}")
    if problems:
        return problems

    placed: list[Any] = []
    for item in output["items"]:
        for key in ("id", "source_ids", "confidence", "action", "why"):
            if key not in item:
                problems.append(f"item {item.get('id')!r} missing {key!r}")
        conf = item.get("confidence")
        if not isinstance(conf, (int, float)) or isinstance(conf, bool) or not 0 <= conf <= 1:
            problems.append(f"item {item.get('id')!r} confidence out of range: {conf!r}")
        placed.extend(item.get("source_ids", []))
    for skip in output["skipped"]:
        if "id" not in skip or "reason" not in skip:
            problems.append(f"skipped entry malformed: {skip!r}")
        placed.append(skip.get("id"))

    expected = _unique(input_ids)
    for sid in expected:
        count = placed.count(sid)
        if count != 1:
            problems.append(f"id {sid!r} placed {count} times")
    for sid in placed:
        if sid not in expected:
            problems.append(f"unknown id {sid!r} in output")

    run = output["run"]
    for key in ("started_at", "cost_usd", "errors"):
        if key not in run:
            problems.append(f"run missing {key!r}")
    return problems


def _unique(values: list[Any]) -> list[Any]:
    out: list[Any] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out
