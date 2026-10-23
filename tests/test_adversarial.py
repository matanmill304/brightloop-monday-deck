"""Run the adversarial cases. Known weaknesses must still fail the way we documented.

If a weak case starts passing, the test fails too: then it's no longer a weakness and
the list must be updated.
"""

import pytest
from adversarial_cases import CASES

from brightloop.contract import check_contract
from brightloop.pipeline import run_pipeline

WEEK = {"week": "2026-W43", "timezone": "Asia/Jerusalem", "output": {"cta_required_per_item": True}}


def outcome(case):
    out = run_pipeline({**WEEK, "signals": case["signals"]})
    ids = [s["id"] for s in case["signals"]]
    assert check_contract(out, ids) == []
    items = {sid: item for item in out["items"] for sid in item["source_ids"]}
    skips = {s["id"]: s["reason"] for s in out["skipped"]}
    sid = case["id"]
    got = "item" if sid in items else "skip"
    ok = got == case["expect"]
    if ok and got == "item":
        item = items[sid]
        if "contains" in case:
            ok = case["contains"] in item["action"] + " ".join(item["change"])
        if "contains_caveat" in case:
            ok = ok and False  # a caveat means the date was not understood
            ok = case["contains_caveat"] not in " ".join(item.get("caveats", []))
        if "same_item_as" in case:
            ok = items.get(case["same_item_as"]) is item
        if "different_item_from" in case:
            ok = items.get(case["different_item_from"]) is not item
    detail = items[sid]["action"] if got == "item" else skips.get(sid, "")
    return ok, got, detail


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_adversarial(case):
    ok, got, detail = outcome(case)
    if case["weak"]:
        assert not ok, f"now passes: no longer a weakness, update the list ({got}: {detail})"
    else:
        assert ok, f"expected {case['expect']}, got {got}: {detail}"
