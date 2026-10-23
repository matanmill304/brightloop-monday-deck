"""Score the pipeline on test files that come with an expected outcome.

    python scripts/score_cases.py [tests/fixtures/adversarial]

For each <name>.json next to a <name>.expected.json: run the same pipeline as `./run`, check
the output contract (every id placed exactly once, no secrets, no banned words), and compare
each id with what was expected: item or skipped, and which ids belong in the same item.
Writes each output to review/adversarial/<name>.result.json and prints the mismatches.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from brightloop.contract import check_contract
from brightloop.pipeline import run_pipeline, secret_values

OUT = ROOT / "review" / "adversarial"


def input_ids(case: dict) -> list:
    ids = []
    for s in case.get("signals", []) if isinstance(case.get("signals"), list) else []:
        sid = s.get("id") if isinstance(s, dict) else None
        if (
            isinstance(sid, (str, int))
            and not isinstance(sid, bool)
            and sid != ""
            and sid not in ids
        ):
            ids.append(sid)
    return ids


def score(path: Path) -> tuple[int, int, list[str]]:
    case = json.loads(path.read_text(encoding="utf-8"))
    expected = json.loads(path.with_suffix(".expected.json").read_text(encoding="utf-8"))
    out = run_pipeline(case)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{path.stem}.result.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    problems = [f"contract: {p}" for p in check_contract(out, input_ids(case))]
    text = json.dumps({"items": out["items"], "skipped": out["skipped"]}, ensure_ascii=False)
    for secret in secret_values(case if isinstance(case, dict) else {}):
        if secret in text:
            problems.append(f"safety: a config secret appears in the output ({secret[:6]}…)")
    brand = case.get("brand") if isinstance(case.get("brand"), dict) else {}
    for word in brand.get("banned_words") or []:
        if isinstance(word, str) and word.lower() in text.lower():
            problems.append(f"safety: banned word {word!r} appears in the output")
    if expected.get("_file", {}).get("errors_expected") and not out["run"]["errors"]:
        problems.append("run.errors is empty, but the file has errors to report")

    # Expected files key ids as strings; an input id may be a number (14).
    item_of = {str(sid): i for i, item in enumerate(out["items"]) for sid in item["source_ids"]}
    reason_of = {str(s["id"]): s["reason"] for s in out["skipped"]}
    checked = agree = 0
    for sid, exp in expected.items():
        if sid.startswith("_"):
            continue
        want = exp.get("expect")
        got = "item" if sid in item_of else "skipped" if sid in reason_of else "missing"
        if want == "either":
            continue
        checked += 1
        detail = (
            out["items"][item_of[sid]]["action"][:110] if got == "item" else reason_of.get(sid, "")
        )
        if got != want:
            problems.append(
                f"{sid}: expected {want}, got {got} | {detail[:110]} | ({exp.get('note', '')})"
            )
            continue
        agree += 1
    # Grouping: ids with the same group label must share one item; ids from different
    # groups (or none) must not share one.
    groups: dict[str, list] = {}
    for sid, exp in expected.items():
        if not sid.startswith("_") and exp.get("group") and exp.get("expect") == "item":
            groups.setdefault(exp["group"], []).append(sid)
    for label, ids in groups.items():
        homes = {item_of.get(sid) for sid in ids}
        if len(homes) > 1 or None in homes:
            problems.append(
                f"group {label}: {ids} should be one item; got items {sorted(map(str, homes))}"
            )
    for item in out["items"]:
        labels = {
            expected.get(str(sid), {}).get("group") or f"solo:{sid}" for sid in item["source_ids"]
        }
        if len(labels) > 1:
            problems.append(f"merged but expected separate: {item['source_ids']}")
    return agree, checked, problems


def main() -> int:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests" / "fixtures" / "adversarial"
    files = sorted(p for p in folder.glob("*.json") if not p.name.endswith(".expected.json"))
    total_agree = total_checked = 0
    for path in files:
        if not path.with_suffix(".expected.json").exists():
            continue
        agree, checked, problems = score(path)
        total_agree += agree
        total_checked += checked
        print(f"\n## {path.name}: {agree}/{checked} placed as expected, {len(problems)} problem(s)")
        for p in problems:
            print(f"  - {p}")
    print(f"\nTotal: {total_agree}/{total_checked} placed as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
