"""The adversarial files (tests/fixtures/adversarial/) keep their scores.

The files were written by agents that never saw the code, each with the outcome they
expected. Contract, safety and wrong merges must never fail; the placement scores may only
go up. Known misses are slang ("a fiver more") and third-party paraphrases.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "tests" / "fixtures" / "adversarial"
spec = importlib.util.spec_from_file_location("score_cases", ROOT / "scripts" / "score_cases.py")
score_cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score_cases)


@pytest.mark.parametrize(
    ("name", "at_least"),
    [("broken-top", 2), ("broken", 22), ("confusing", 37), ("wording", 31)],
)
def test_adversarial_file_keeps_its_score(name, at_least):
    agree, _checked, problems = score_cases.score(FILES / f"{name}.json")
    hard = [p for p in problems if p.startswith(("contract", "safety", "merged but", "run.errors"))]
    assert not hard, hard
    assert agree >= at_least, problems
