"""Hostile files: the CLI and the upload endpoint always answer with the output wrapper.

Never a traceback; every problem is named in run.errors; the output is strict JSON.
"""

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from brightloop.cli import main
from brightloop.contract import to_json
from brightloop.normalize import parse_iso

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (ROOT / "tests" / "fixtures" / "brief_sample.json").read_bytes()
SAMPLE_IDS = {s["id"] for s in json.loads(SAMPLE)["signals"]}


def strict_load(text):
    """Parse output the way a strict JSON reader would (no NaN, no Infinity)."""

    def reject(word):
        raise AssertionError(f"output contains {word}, which is not JSON")

    out = json.loads(text, parse_constant=reject)
    assert set(out) == {"built_for", "items", "skipped", "run"}
    assert out["built_for"] == "maya" and isinstance(out["run"]["errors"], list)
    return out


def run_cli(tmp_path, content):
    """Write `content` (bytes or text) as cases.json, run the CLI, return (exit code, output)."""
    cases = tmp_path / "cases.json"
    cases.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    result = tmp_path / "result.json"
    code = main(["run", "--input", str(cases), "--output", str(result)])
    return code, strict_load(result.read_text(encoding="utf-8"))


def errors(out):
    return " | ".join(out["run"]["errors"])


def placed(out):
    return {sid for item in out["items"] for sid in item["source_ids"]} | {
        s["id"] for s in out["skipped"]
    }


# ---- Files that can't be read at all ------------------------------------------


def test_empty_file(tmp_path):
    code, out = run_cli(tmp_path, b"")
    assert code == 0 and out["items"] == [] and out["skipped"] == []
    assert "the file is empty" in errors(out)


def test_whitespace_only_file(tmp_path):
    code, out = run_cli(tmp_path, " \n\t\r\n ")
    assert code == 0 and "the file is empty" in errors(out)


def test_yaml_file(tmp_path):
    code, out = run_cli(tmp_path, "week: 2026-W43\nsignals:\n  - id: pr-401\n")
    assert code == 0 and "not valid JSON" in errors(out)


def test_plain_text_file(tmp_path):
    code, out = run_cli(tmp_path, "Lovable raised Pro to $30 this week.")
    assert code == 0 and "not valid JSON" in errors(out)


def test_truncated_json(tmp_path):
    code, out = run_cli(tmp_path, SAMPLE[: len(SAMPLE) // 2])
    assert code == 0 and out["items"] == [] and "not valid JSON" in errors(out)


def test_random_binary(tmp_path):
    code, out = run_cli(tmp_path, bytes(range(256)) * 8)
    assert code == 0 and "not UTF-8 text" in errors(out)


def test_invalid_utf8(tmp_path):
    code, out = run_cli(tmp_path, b'{"signals": [{"id": "a", "text": "caf\xe9"}]}')
    assert code == 0 and "not UTF-8 text (bad byte at position" in errors(out)


def test_very_deep_nesting(tmp_path):
    code, out = run_cli(tmp_path, "[" * 5000 + "]" * 5000)
    assert code == 0 and "nested more than 100 levels deep" in errors(out)


def test_deep_nesting_inside_one_signal(tmp_path):
    deep = "[" * 500 + "]" * 500
    code, out = run_cli(tmp_path, '{"signals": [{"id": "a", "text": ' + deep + "}]}")
    assert code == 0 and "nested more than 100 levels deep" in errors(out)


# ---- Files that parse, with a twist -----------------------------------------


def test_utf8_bom_still_parses(tmp_path):
    code, out = run_cli(tmp_path, b"\xef\xbb\xbf" + SAMPLE)
    assert code == 0 and out["items"] and placed(out) == SAMPLE_IDS
    assert "could not read" not in errors(out)


def test_utf16_file_from_powershell_still_parses(tmp_path):
    code, out = run_cli(tmp_path, SAMPLE.decode("utf-8").encode("utf-16"))
    assert code == 0 and out["items"] and placed(out) == SAMPLE_IDS


def test_nan_and_infinity_are_read_as_null_and_never_written(tmp_path):
    text = '{"week": NaN, "signals": [{"id": "a", "ts": Infinity, "n": -Infinity, "x": 1e999}]}'
    code, out = run_cli(tmp_path, text)
    assert code == 0 and placed(out) == {"a"}
    assert "4 value(s) like NaN are not valid JSON; read as null" in errors(out)


def test_non_finite_numbers_are_never_written():
    assert json.loads(to_json({"a": float("nan"), "b": [float("inf")]})) == {"a": None, "b": [None]}


def test_lone_surrogate_escapes_are_written_escaped(tmp_path):
    code, out = run_cli(tmp_path, '{"signals": [{"id": "\\ud800", "text": "x\\udfff"}]}')
    assert code == 0 and placed(out) == {"\ud800"}


def test_duplicate_keys_last_one_wins(tmp_path):
    code, out = run_cli(tmp_path, '{"signals": "nope", "signals": [{"id": "a"}, {"id": "b"}]}')
    assert code == 0 and placed(out) == {"a", "b"}


@pytest.mark.parametrize("top", ["[]", '[{"id": "a"}]', '"pr-401"', "42", "null", "true"])
def test_top_level_that_is_not_an_object(tmp_path, top):
    code, out = run_cli(tmp_path, top)
    assert code == 0 and out["items"] == [] and out["skipped"] == []
    assert "top level is not a JSON object" in errors(out)


@pytest.mark.parametrize("signals", ['{"id": "a"}', '"pr-401"', "null", "7"])
def test_signals_that_is_not_a_list(tmp_path, signals):
    code, out = run_cli(tmp_path, '{"week": "2026-W43", "signals": ' + signals + "}")
    assert code == 0 and out["items"] == [] and out["skipped"] == []
    assert "'signals'" in errors(out)


def test_week_timezone_and_output_of_the_wrong_type(tmp_path):
    text = '{"week": [2026, 43], "timezone": 3, "output": "yes", "signals": [{"id": "a"}]}'
    code, out = run_cli(tmp_path, text)
    assert code == 0 and placed(out) == {"a"}
    assert "could not read week [2026, 43]" in errors(out)
    assert "timezone 3 is not a name" in errors(out)
    assert "'output' is not an object" in errors(out)


@pytest.mark.parametrize("zone", ["America", "A" * 5000, "../../etc/passwd", "UTC\u0000"])
def test_timezone_that_is_a_folder_a_path_or_huge(tmp_path, zone):
    code, out = run_cli(tmp_path, json.dumps({"timezone": zone, "signals": [{"id": "a"}]}))
    assert code == 0 and placed(out) == {"a"}
    assert "unknown timezone" in errors(out) and len(errors(out)) < 200


# ---- Paths -------------------------------------------------------------------


def test_input_file_that_does_not_exist(tmp_path):
    result = tmp_path / "result.json"
    code = main(["run", "--input", str(tmp_path / "missing.json"), "--output", str(result)])
    out = strict_load(result.read_text(encoding="utf-8"))
    assert code == 0 and "No such file or directory" in errors(out)


def test_input_that_is_a_folder(tmp_path):
    result = tmp_path / "result.json"
    code = main(["run", "--input", str(tmp_path), "--output", str(result)])
    assert code == 0 and "could not read" in errors(strict_load(result.read_text("utf-8")))


def test_output_folder_that_does_not_exist_is_created(tmp_path):
    (tmp_path / "cases.json").write_bytes(SAMPLE)
    result = tmp_path / "new" / "deeper" / "result.json"
    assert main(["run", "--input", str(tmp_path / "cases.json"), "--output", str(result)]) == 0
    assert placed(strict_load(result.read_text("utf-8"))) == SAMPLE_IDS


def test_output_that_cannot_be_written_exits_1_with_a_message(tmp_path, capsys):
    (tmp_path / "cases.json").write_bytes(SAMPLE)
    (tmp_path / "a-file").write_text("not a folder")
    result = tmp_path / "a-file" / "result.json"
    assert main(["run", "--input", str(tmp_path / "cases.json"), "--output", str(result)]) == 1
    assert "part of the path is a file, not a folder" in capsys.readouterr().err


# ---- The upload endpoint (api/run.py) ----------------------------------------


def load_api():
    spec = importlib.util.spec_from_file_location("api_run", ROOT / "api" / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def post(body, length="auto"):
    """What /api/run answers to a POST with this body and Content-Length: (status, JSON)."""
    api = load_api()
    status, out = api.respond(str(len(body)) if length == "auto" else length, lambda n: body[:n])
    return status, strict_load(to_json(out))


def test_api_good_body():
    status, out = post(SAMPLE)
    assert status == 200 and out["items"] and placed(out) == SAMPLE_IDS


def test_api_body_not_json():
    status, out = post(b"signals: [pr-401]")
    assert status == 200 and "not valid JSON" in errors(out)


def test_api_empty_body():
    status, out = post(b"")
    assert status == 200 and "the file is empty" in errors(out)


def test_api_missing_content_length():
    status, out = post(b"", length=None)
    assert status == 200 and "the file is empty" in errors(out)


def test_api_body_over_5mb():
    status, out = post(b"x", length=str(5_000_001))
    assert status == 413 and out["items"] == [] and "over 5 MB" in errors(out)


def test_api_bad_content_length():
    status, out = post(b"{}", length="lots")
    assert status == 400 and "Content-Length" in errors(out)


def test_api_non_utf8_body():
    status, out = post(b'{"signals": [{"id": "\xff"}]}')
    assert status == 200 and "not UTF-8 text" in errors(out)


# ---- Timestamps read the same on Python 3.9 and 3.11+ -------------------------


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-22T07:00:00Z",
        "2026-10-22T07:00:00z",
        "2026-10-22T10:00:00+0300",
        "2026-10-22T07:00:00.5Z",
        "2026-10-22T07:00:00.123456789+00:00",
    ],
)
def test_iso_timestamps_with_z_offsets_and_fractions(text):
    moment = parse_iso(text).astimezone(timezone.utc)
    assert moment.replace(microsecond=0) == datetime(2026, 10, 22, 7, tzinfo=timezone.utc)
