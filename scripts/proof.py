"""The one command that proves it works (./proof). Zero keys, no install, no network.

1. Replays every recorded real run (recordings/<week>/cases.json): the pipeline must
   reproduce the recorded result.json exactly.
2. Runs the brief's sample input and checks the output contract.
3. Runs the edge-case file (27 tricky signals) and checks the contract.
Exit code 0 = all good.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brightloop.contract import check_contract
from brightloop.pipeline import run_pipeline


def ids(case: dict) -> list:
    out = []
    for s in case.get("signals", []):
        sid = s.get("id") if isinstance(s, dict) else None
        if (
            isinstance(sid, (str, int))
            and not isinstance(sid, bool)
            and sid != ""
            and sid not in out
        ):
            out.append(sid)
    return out


def main() -> int:
    failures = 0
    recordings = sorted((ROOT / "recordings").glob("*-W*/cases.json"))
    for path in recordings:
        case = json.loads(path.read_text(encoding="utf-8"))
        recorded = json.loads((path.parent / "result.json").read_text(encoding="utf-8"))
        replayed = run_pipeline(case)
        problems = check_contract(replayed, ids(case))
        for out in (recorded, replayed):
            out["run"].pop("started_at", None)
        same = replayed == recorded
        failures += bool(problems) or not same
        print(
            f"{'OK ' if same and not problems else 'FAIL'} recorded run {path.parent.name}: "
            f"{len(case['signals'])} signals -> {len(replayed['items'])} items, "
            f"{len(replayed['skipped'])} skipped{'' if same else ' (differs from recording)'}"
        )
    for name in ("brief_sample.json", "edge_cases.json"):
        case = json.loads((ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8"))
        out = run_pipeline(case)
        problems = check_contract(out, ids(case))
        failures += bool(problems)
        print(
            f"{'OK ' if not problems else 'FAIL'} {name}: {len(out['items'])} items, "
            f"{len(out['skipped'])} skipped, every id placed once{'' if not problems else ': ' + str(problems)}"
        )
    if not recordings:
        print("FAIL no recorded run found in recordings/")
        failures += 1
    print("proof: all good" if not failures else f"proof: {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
