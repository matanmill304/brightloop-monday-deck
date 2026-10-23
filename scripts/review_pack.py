"""Regenerate the review pack in review/ from the code that actually runs.

python scripts/review_pack.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from test_noisy_inputs import WEEK, noisy_case

from brightloop import write_text
from brightloop.explain import eval_markdown, rules_markdown, trace_markdown

OUT = ROOT / "review"


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def write(name: str, text: str) -> None:
    write_text(OUT / name, text)
    print(f"wrote review/{name}")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    write("1-pipeline-rules.md", rules_markdown())
    write(
        "2-trace-brief-sample.md",
        trace_markdown(load("tests/fixtures/brief_sample.json"), "the brief's sample input"),
    )
    write(
        "3-trace-edge-cases.md",
        trace_markdown(load("tests/fixtures/edge_cases.json"), "edge cases (one per situation)"),
    )
    write(
        "4-trace-noisy-input.md",
        trace_markdown(
            {**WEEK, "signals": noisy_case(seed=0, copies=1)},
            "noisy input: 3 real changes hidden among 21 unrelated signals",
        ),
    )
    write(
        "5-real-headlines-eval.md",
        eval_markdown(
            {
                "Dev set (used to design the rules)": load("tests/eval/headlines_dev.json"),
                "Held-out set (scored once, not tuned)": load("tests/eval/headlines_holdout.json"),
            }
        ),
    )


def adversarial_markdown() -> str:
    from adversarial_cases import CASES
    from test_adversarial import outcome

    from brightloop.explain import table

    rows, weak = [], 0
    for case in CASES:
        ok, got, detail = outcome(case)
        weak += case["weak"]
        verdict = "✅" if ok else "❌ known weakness"
        note = case.get("instead", "") if case["weak"] else ""
        rows.append((verdict, case["name"], case["expect"], got, case["why"], note or detail[:90]))
    rows.sort(key=lambda r: r[0] == "✅")
    head = [
        "# Adversarial signals: built to break the pipeline",
        "",
        (
            f"{len(CASES)} cases, {len(CASES) - weak} handled, **{weak} known weaknesses**. "
            "Source: `tests/adversarial_cases.py`; enforced by `tests/test_adversarial.py` "
            "(a weakness that starts passing fails the test, so this list stays honest)."
        ),
        "",
    ]
    body = table(["", "Case", "Expected", "Got", "Why it's hard", "What we do"], rows)
    return "\n".join(head) + body + "\n"


if __name__ == "__main__":
    write("6-adversarial-results.md", adversarial_markdown())


def live_run_markdown(week: str = "2026-W43") -> str:
    from brightloop.explain import table, trace_markdown

    folder = ROOT / "recordings" / week
    if not (folder / "cases.json").exists():
        return f"# Live run {week}\n\nNo recording yet. Run `brightloop collect --week {week}`.\n"
    runs = [
        json.loads(line)
        for line in (ROOT / "recordings" / "runlog.jsonl").read_text("utf-8").splitlines()
    ]
    run = [r for r in runs if r["week"] == week][-1]
    pages = [
        (p["competitor"], p["page"], p.get("live", "ok"), p["baseline"], p["current"])
        for p in run["pages"]
    ]
    result = load(f"recordings/{week}/result.json")
    rows = [
        (", ".join(map(str, i["source_ids"])), i["confidence"], i["action"])
        for i in result["items"]
    ]
    rows += [(s["id"], "-", "SKIPPED: " + s["reason"]) for s in result["skipped"]]
    return "\n".join(
        [
            f"# Live run {week}",
            "",
            (
                f"Started {run['started_at']}, finished {run['finished_at']} · {run['signals']} snapshots · "
                f"{run['items']} items · {run['skipped']} skipped · errors: {run['errors'] or 'none'}"
            ),
            "",
            "## Pages captured",
            "",
            table(["Competitor", "Page", "Live", "Baseline (last week)", "Current"], pages),
            "",
            "## Result",
            "",
            table(["Signals", "Confidence", "Action / reason"], rows),
            "",
            (
                f"Screenshots: `recordings/{week}/*.jpg`. Cases file: `recordings/{week}/cases.json` "
                "(replay with `brightloop run --input recordings/{week}/cases.json --output result.json`)."
            ),
            "",
            trace_markdown(load(f"recordings/{week}/cases.json"), f"recorded live run {week}"),
        ]
    )


if __name__ == "__main__":
    write("7-first-live-run.md", live_run_markdown())
