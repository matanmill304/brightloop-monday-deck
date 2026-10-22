import json
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from brightloop.cli import run_file
from brightloop.contract import check_contract
from brightloop.pipeline import run_pipeline

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def input_ids(case):
    ids = []
    raw = case.get("signals") if isinstance(case, dict) else None
    for s in raw if isinstance(raw, list) else []:
        sid = s.get("id") if isinstance(s, dict) else None
        usable = isinstance(sid, (str, int)) and not isinstance(sid, bool) and sid != ""
        if usable and sid not in ids:
            ids.append(sid)
    return ids


def test_brief_sample_meets_contract():
    case = load("brief_sample.json")
    out = run_pipeline(case)
    assert out["built_for"] == "maya"
    assert check_contract(out, input_ids(case)) == []


def test_cli_writes_valid_output(tmp_path):
    out_path = tmp_path / "result.json"
    assert run_file(FIXTURES / "brief_sample.json", out_path) == 0
    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert check_contract(out, input_ids(load("brief_sample.json"))) == []


def test_unreadable_input_still_writes_output(tmp_path):
    bad = tmp_path / "cases.json"
    bad.write_text("{not json", encoding="utf-8")
    out_path = tmp_path / "result.json"
    assert run_file(bad, out_path) == 0
    out = json.loads(out_path.read_text(encoding="utf-8"))
    assert out["items"] == [] and out["skipped"] == []
    assert out["run"]["errors"]


def test_duplicate_and_missing_ids():
    case = {"signals": [{"id": "a"}, {"id": "a"}, {"text": "no id"}, "garbage", {"id": "b"}]}
    out = run_pipeline(case)
    assert check_contract(out, ["a", "b"]) == []
    assert any("duplicate id" in e for e in out["run"]["errors"])
    assert any("no usable id" in e for e in out["run"]["errors"])


json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=20),
    lambda children: (
        st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=8), children, max_size=4)
    ),
    max_leaves=12,
)
signal = st.fixed_dictionaries(
    {"id": st.one_of(st.text(max_size=6), st.integers(0, 50), st.none())},
    optional={
        "type": st.sampled_from(["pricing", "ad", "launch", "hiring", "", None]),
        "text": st.text(max_size=40),
        "ts": st.one_of(st.text(max_size=25), st.integers()),
        "extra": json_values,
    },
)


@settings(max_examples=200, deadline=None)
@given(st.one_of(json_values, st.fixed_dictionaries({"signals": st.lists(signal, max_size=12)})))
def test_any_input_meets_contract(case):
    out = run_pipeline(case)
    assert check_contract(out, input_ids(case)) == []
