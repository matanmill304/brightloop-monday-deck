"""Regenerate the review pack in review/ from the code that actually runs.

python scripts/review_pack.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from test_noisy_inputs import WEEK, noisy_case

from brightloop.explain import eval_markdown, rules_markdown, trace_markdown

OUT = ROOT / "review"


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def write(name: str, text: str) -> None:
    (OUT / name).write_text(text, encoding="utf-8", newline="\n")
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
