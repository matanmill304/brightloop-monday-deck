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

    args = parser.parse_args(argv)
    if args.command == "run":
        return run_file(args.input, args.output)
    return 2


def run_file(input_path: Path, output_path: Path) -> int:
    try:
        case = json.loads(input_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        run = new_run()
        run["errors"].append(f"input: could not read {input_path.name}: {exc}")
        output = build_output(items=[], skipped=[], run=run)
    else:
        output = run_pipeline(case)

    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    placed = sum(len(i["source_ids"]) for i in output["items"]) + len(output["skipped"])
    print(
        f"brightloop: {len(output['items'])} items, {len(output['skipped'])} skipped, "
        f"{placed} ids placed, {len(output['run']['errors'])} errors -> {output_path}",
        file=sys.stderr,
    )
    return 0
