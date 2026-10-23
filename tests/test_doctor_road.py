"""The doctor road: Sarathi's doctor asked, and only what's new told.

The bias: A MORNING MESSAGE THAT NAGS, OR ONE THAT HIDES. A phone left
unplugged all week is said once (the doctor marks it not new), so the
answer is NOTHING NEW; something newly red or amber is said with its
fix; a doctor that can't be reached, or answers in a shape this Samay
doesn't know, is a failed run with why -- never a quiet one.
"""

from __future__ import annotations

import pytest
from test_runners import schedule

from samay import schedules
from samay.clock import is_quiet
from samay.runners import DoctorRunner, doctor_said
from samay.schedules import ScheduleError
from samay.store import Store


def answer(new=(), gone=(), red=0, amber=1) -> dict:
    return {"format": "sarathi.doctor.v1", "red": red, "amber": amber, "green": 8,
            "lines": [], "news": {"new": list(new), "gone": list(gone)}}


PHONE = {"level": "amber", "about": "phone", "said": "nexus isn't connected",
         "fix": "plug it in"}
STOPPED = {"level": "red", "about": "dvara", "said": "stopped", "fix": "sarathi up"}


def run(data):
    runner = DoctorRunner(url="http://home/api/doctor?news=1", token="t",
                          fetch=lambda url, token, timeout: data)
    return runner.run(schedule(runner="doctor"), "the house")


def test_nothing_new_is_quiet_even_with_old_problems():
    result = run(answer())
    assert result.ok and is_quiet(result.text)
    assert "0 to fix, 1 worth a look" in result.text


def test_something_new_is_said_with_its_fix():
    result = run(answer(new=[STOPPED], red=1))
    assert result.ok and not is_quiet(result.text)
    assert "needs fixing -- dvara: stopped" in result.text
    assert "fix: sarathi up" in result.text


def test_a_new_green_line_is_not_news_but_a_fix_is_mentioned():
    text = doctor_said(answer(new=[{"level": "green", "about": "disk", "said": "ok"}],
                              gone=[PHONE]))
    assert is_quiet(text) and "Fixed since last time: phone" in text


def test_no_doctor_to_ask_is_a_failed_run_that_says_why():
    result = DoctorRunner(url="", token="").run(schedule(runner="doctor"), "x")
    assert not result.ok and "sarathi up" in result.detail


def test_an_unreachable_or_unknown_doctor_fails_out_loud():
    def down(url, token, timeout):
        raise OSError("connection refused")
    result = DoctorRunner(url="http://x", token="t", fetch=down).run(
        schedule(runner="doctor"), "x")
    assert not result.ok and "connection refused" in result.detail
    assert not run({"format": "sarathi.doctor.v9"}).ok


def test_the_key_goes_in_a_header(monkeypatch):
    seen = {}

    def fetch(url, token, timeout):
        seen.update(url=url, token=token)
        return answer()
    DoctorRunner(url="http://home/api/doctor?news=1", token="k",
                 fetch=fetch).run(schedule(runner="doctor"), "x")
    assert seen == {"url": "http://home/api/doctor?news=1", "token": "k"}


def test_a_doctor_schedule_takes_no_agent(tmp_path):
    store = Store(tmp_path / "samay.db")
    made = schedules.create(store, prompt="the house each morning", when="at 07:30",
                            runner="doctor")
    assert made.runner == "doctor"
    with pytest.raises(ScheduleError):
        schedules.create(store, prompt="x", when="at 07:30", runner="doctor",
                         agent="minder")
