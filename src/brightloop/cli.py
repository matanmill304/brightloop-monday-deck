"""Command line: ``brightloop run --input cases.json --output result.json``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from brightloop.contract import build_output, new_run
from brightloop.pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="brightloop")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="Run the pipeline on a cases file")
    run_cmd.add_argument("--input", required=True, type=Path)
    run_cmd.add_argument("--output", required=True, type=Path)

    explain_cmd = sub.add_parser(
        "explain", help="Write a step-by-step trace of every signal (and the rules) as Markdown"
    )
    explain_cmd.add_argument("--input", type=Path, help="Cases file to trace")
    explain_cmd.add_argument("--output", required=True, type=Path)

    collect_cmd = sub.add_parser(
        "collect", help="Capture Maya's competitor pages for a week and run the pipeline on them"
    )
    collect_cmd.add_argument("--week", help="ISO week, e.g. 2026-W43 (default: this week)")
    collect_cmd.add_argument(
        "--archived", action="store_true", help="Rebuild a past week from the Wayback Machine"
    )
    collect_cmd.add_argument("--root", type=Path, default=Path("recordings"))

    args = parser.parse_args(argv)
    if args.command == "run":
        return run_file(args.input, args.output)
    if args.command == "explain":
        return explain_file(args.input, args.output)
    if args.command == "collect":
        from brightloop.collect.run import collect, current_week

        entry = collect(args.week or current_week(), args.root, archived=args.archived)
        print(json.dumps(entry, indent=2, ensure_ascii=False))
        return 0
    return 2


def explain_file(input_path: Path | None, output_path: Path) -> int:
    from brightloop.explain import rules_markdown, trace_markdown

    if input_path is None:
        text = rules_markdown()
    else:
        case = json.loads(input_path.read_text(encoding="utf-8-sig"))
        text = trace_markdown(case, input_path.name)
    output_path.write_text(text, encoding="utf-8")
    print(f"brightloop: explanation written to {output_path}", file=sys.stderr)
    return 0


def run_file(input_path: Path, output_path: Path) -> int:
    try:
        case = json.loads(input_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        run = new_run()
        run["errors"].append(f"input: could not read {input_path.name}: {exc}")
        output = build_output(items=[], skipped=[], run=run)
    else:
        output = run_pipeline(case)

    text = json.dumps(output, indent=2, ensure_ascii=False) + "\n"
    output_path.write_text(text, encoding="utf-8", newline="\n")
    placed = sum(len(i["source_ids"]) for i in output["items"]) + len(output["skipped"])
    print(
        f"brightloop: {len(output['items'])} items, {len(output['skipped'])} skipped, "
        f"{placed} ids placed, {len(output['run']['errors'])} errors -> {output_path}",
        file=sys.stderr,
    )
    return 0
