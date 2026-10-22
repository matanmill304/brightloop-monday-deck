"""The one pipeline. The web source and the file source both end here.

Phase 0 skeleton: reads signals defensively and accounts for every id.
The real steps (normalize, window, group, trust, relevance, write) land in Phase 1.
"""

from __future__ import annotations

from typing import Any

from brightloop.contract import build_output, enforce_accounting, new_run


def run_pipeline(case: Any) -> dict[str, Any]:
    run = new_run()
    _signals, input_ids = read_signals(case, run["errors"])

    skipped = [{"id": sid, "reason": "Not processed yet (pipeline skeleton)."} for sid in input_ids]
    output = build_output(items=[], skipped=skipped, run=run)
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
