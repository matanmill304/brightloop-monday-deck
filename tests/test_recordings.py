"""Recorded real runs replay with zero keys and give the same result as when recorded.

This is the brief's "the repo still runs on data you recorded from your real runs".
"""

import json
from pathlib import Path

import pytest

from brightloop.contract import check_contract
from brightloop.pipeline import run_pipeline

RECORDINGS = sorted((Path(__file__).resolve().parents[1] / "recordings").glob("*/cases.json"))


@pytest.mark.parametrize("cases", RECORDINGS, ids=[p.parent.name for p in RECORDINGS])
def test_recording_replays_to_the_recorded_result(cases):
    case = json.loads(cases.read_text(encoding="utf-8"))
    recorded = json.loads((cases.parent / "result.json").read_text(encoding="utf-8"))
    replayed = run_pipeline(case)
    assert check_contract(replayed, [s["id"] for s in case["signals"]]) == []
    for out in (recorded, replayed):
        out["run"].pop("started_at")
    assert replayed == recorded


def test_there_is_at_least_one_recording():
    assert RECORDINGS, "no recorded run in recordings/"
