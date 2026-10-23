"""The tests road: every kept test replayed, and only news told.

The bias: A NIGHT THAT WENT WRONG MUST SAY SO, AND A NIGHT WITH NOTHING
NEW MUST STAY QUIET. A suite that could not run is a failed run with its
reason, never a quiet one; something that broke since last time is news
even when most passed; red that was red yesterday is not news. And a
tests schedule asks no agent anything, so it takes no agent or tools.
"""

from __future__ import annotations

import json

import pytest
from test_runners import fake_yantra, schedule, seen

from samay import schedules
from samay.runners import KeptTestsRunner, read_tests, night_said
from samay.schedules import ScheduleError
from samay.store import Store


def night(**over) -> dict:
    data = {"format": "yantra.tests.v1", "at": "2026-10-23T03:00:00-04:00",
            "suites": [{"agent": "yantra", "person": "", "cases": 2, "passed": 2,
                        "red": [], "broke": [], "fixed": [], "error": ""}],
            "cases": 2, "passed": 2, "broke": 0, "fixed": 0, "errors": 0,
            "green": True}
    return {**data, **over}


def printed(data: dict) -> str:
    return f"print('a line first'); print({json.dumps(json.dumps(data))})\n"


def test_it_asks_yantra_for_every_kept_test_as_json(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMAY_TESTS_PROVIDER", "ollama")
    monkeypatch.setenv("SAMAY_TESTS_MODEL", "qwen3.8:latest")
    runner = KeptTestsRunner(command=fake_yantra(tmp_path, printed(night())))
    result = runner.run(schedule(runner="tests"), "the night's tests")
    assert seen(tmp_path)["argv"] == ["--tests", "--json", "--provider", "ollama",
                                     "--model", "qwen3.8:latest"]
    assert seen(tmp_path)["unattended"] == "1"
    assert result.ok and result.text.startswith("NOTHING NEW")


def test_something_broke_is_news():
    data = night(broke=1, passed=1, green=False, suites=[
        {"agent": "minder", "person": "naina", "cases": 2, "passed": 1,
         "red": ["kept-a"], "broke": ["kept-a"], "fixed": [], "error": ""}])
    said = night_said(data)
    assert not said.startswith("NOTHING NEW")
    assert "1 broke since last time" in said and "naina's minder: broke kept-a" in said


def test_red_that_was_red_yesterday_is_not_news():
    data = night(passed=1, green=False)
    assert night_said(data).startswith("NOTHING NEW")


def test_a_suite_that_could_not_run_is_a_failed_run_with_its_reason():
    data = night(errors=1, green=False, suites=[
        {"agent": "yantra", "person": "", "cases": 0, "passed": 0, "red": [],
         "broke": [], "fixed": [], "error": "the model is not answering"}])
    result = read_tests(json.dumps(data), "")
    assert not result.ok and "could not run" in result.detail
    assert "the model is not answering" in result.text
    assert not result.text.startswith("NOTHING NEW")


def test_an_unknown_shape_or_nothing_printed_is_refused():
    assert "does not know" in read_tests(json.dumps({"format": "x"}), "").detail
    assert read_tests("", "boom").detail == "boom"


def test_a_tests_schedule_takes_no_agent_or_tools(tmp_path):
    store = Store(tmp_path / "s.sqlite3")
    made = schedules.create(store, prompt="the night's tests", when="at 03:00",
                            runner="tests")
    assert made.runner == "tests"
    with pytest.raises(ScheduleError, match="asks no agent"):
        schedules.create(store, prompt="x", when="at 03:00", runner="tests",
                         allow_tools=["browser_*"])
