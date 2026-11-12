"""The routine road: a schedule that starts one of the person's routines.

The bias: A ROUTINE THAT DIDN'T START AND NOBODY HEARD, or one started as
the wrong person. A start that went well is NOTHING NEW (Vidhi tells the
person what the routine found, so Samay saying "started" every morning
would be a second message about the same thing); a routine that is
paused, gone, or already has too many runs open is a failed run that
says why, in Vidhi's own words. And the routine is always started AS the
schedule's own person.
"""

from __future__ import annotations

import json
import sys

import pytest
from test_runners import schedule

from samay import schedules
from samay.clock import is_quiet
from samay.mcp import Tools
from samay.runners import VidhiRunner
from samay.schedules import ScheduleError
from samay.store import Store

FAKE = '''
import json, sys
argv = sys.argv[1:]
open(sys.argv[0] + ".log", "w").write(json.dumps(argv))
if argv[1] == "paused-one":
    print(json.dumps({"error": "paused-one is paused: vidhi resume paused-one"}))
    print("error: paused-one is paused: vidhi resume paused-one", file=sys.stderr)
    sys.exit(1)
print(json.dumps({"id": "ab12cd34", "state": "queued"}))
'''


@pytest.fixture
def vidhi(tmp_path):
    script = tmp_path / "vidhi.py"
    script.write_text(FAKE)
    return [sys.executable, str(script)], tmp_path / "vidhi.py.log"


def test_a_start_that_went_well_is_quiet_and_says_which_run(vidhi):
    command, log = vidhi
    result = VidhiRunner(command=command).run(
        schedule(runner="vidhi", prompt="morning-brief", owner="asha"), "")
    assert result.ok and is_quiet(result.text)
    assert "morning-brief (run ab12cd34)" in result.text
    assert json.loads(log.read_text()) == ["start", "morning-brief", "--as=asha",
                                          "--by=samay:abc123", "--json"]


def test_a_routine_that_would_not_start_fails_in_vidhis_words(vidhi):
    command, _ = vidhi
    result = VidhiRunner(command=command).run(
        schedule(runner="vidhi", prompt="paused-one"), "")
    assert not result.ok
    assert result.detail == ("the routine didn't start: paused-one is paused: "
                             "vidhi resume paused-one")


def test_no_vidhi_fails_out_loud(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    result = VidhiRunner().run(schedule(runner="vidhi", prompt="morning-brief"), "")
    assert not result.ok and "cannot find vidhi" in result.detail


def test_a_routine_schedule_takes_a_routines_name_and_no_agent(tmp_path):
    store = Store(tmp_path / "samay.db")
    made = schedules.create(store, prompt="morning-brief", when="at 07:00", runner="vidhi")
    assert made.runner == "vidhi"
    with pytest.raises(ScheduleError, match="no agent"):
        schedules.create(store, prompt="morning-brief", when="at 07:00", runner="vidhi",
                         allow_tools=["web_fetch"])
    with pytest.raises(ScheduleError, match="the routine's name"):
        schedules.create(store, prompt="Write me a brief", when="at 07:00", runner="vidhi")


def test_an_agent_schedules_a_routine_by_its_name(tmp_path):
    store = Store(tmp_path / "samay.db")
    tools = Tools(store, tmp_path, person="asha", runner="dvara", agent="helper")
    said = tools.call("create_schedule", {"routine": "morning-brief",
                                          "when": {"at": "07:00"}})
    assert "starts the routine morning-brief" in said
    made = store.schedules(owner="asha")[0]
    assert made.runner == "vidhi" and made.prompt == "morning-brief" and made.agent == ""


# A schedule's own inputs. The bias: ONE ROUTINE FOR TWO CITIES meant two
# installs, or worse, a schedule that quietly ran with the installed city.


def test_a_schedules_own_inputs_go_with_every_start(vidhi, tmp_path):
    command, log = vidhi
    store = Store(tmp_path / "samay.db")
    made = schedules.create(store, prompt="morning-brief", when="at 07:00", runner="vidhi",
                            inputs=["city=Cary", "line = 60"])
    assert store.get(made.id).inputs == {"city": "Cary", "line": "60"}
    VidhiRunner(command=command).run(store.get(made.id), "")
    argv = json.loads(log.read_text())
    assert "--input=city=Cary" in argv and "--input=line=60" in argv


def test_inputs_are_for_a_routine_schedule_and_well_formed(tmp_path):
    store = Store(tmp_path / "samay.db")
    with pytest.raises(ScheduleError, match="routine schedule"):
        schedules.create(store, prompt="Check the weather", when="at 07:00",
                         inputs={"city": "Cary"})
    with pytest.raises(ScheduleError, match="NAME=VALUE"):
        schedules.create(store, prompt="brief", when="at 07:00", runner="vidhi",
                         inputs=["Cary"])
    with pytest.raises(ScheduleError, match="one lowercase word"):
        schedules.create(store, prompt="brief", when="at 07:00", runner="vidhi",
                         inputs={"The City": "Cary"})


def test_an_agent_schedules_a_routine_with_its_own_inputs(tmp_path):
    store = Store(tmp_path / "samay.db")
    tools = Tools(store, tmp_path, person="asha", runner="dvara", agent="helper")
    said = tools.call("create_schedule", {"routine": "morning-brief",
                                          "routine_inputs": {"city": "Durham"},
                                          "when": {"at": "07:00"}})
    assert "starts the routine morning-brief with city = Durham" in said
    assert store.schedules(owner="asha")[0].inputs == {"city": "Durham"}


# -- from the page ------------------------------------------------------------------------

LISTING = '''
import json, sys
if sys.argv[1:2] == ["list"]:
    print(json.dumps([{"name": "cold-night", "title": "Cold night warning",
                       "state": "active", "about": "Reads a temperature",
                       "inputs": {"line": 35},
                       "inputs_spec": [{"name": "line", "label": "Cold means below",
                                        "kind": "number"}]}]))
'''


def test_the_page_lists_the_routines_with_their_blanks(tmp_path, monkeypatch):
    from samay.http import _routines
    script = tmp_path / "vidhi.py"
    script.write_text(LISTING)
    monkeypatch.setenv("SAMAY_VIDHI", f"{sys.executable} {script}")
    got = _routines()
    assert got["said"] == "" and got["routines"][0]["name"] == "cold-night"
    assert got["routines"][0]["blanks"] == [{"name": "line", "label": "Cold means below",
                                            "kind": "number"}]
    assert got["routines"][0]["inputs"] == {"line": 35}


def test_with_no_vidhi_the_page_says_so_and_lists_none(monkeypatch, tmp_path):
    from samay.http import _routines
    monkeypatch.setenv("SAMAY_VIDHI", str(tmp_path / "nothing"))
    got = _routines()
    assert got["routines"] == [] and got["said"]


def test_a_schedule_made_on_the_page_keeps_only_the_blanks_given(tmp_path):
    from samay.http import Api
    from samay.store import Store
    api = Api(Store(tmp_path / "s.sqlite3"), None, tmp_path)
    made = api._create({"prompt": "cold-night", "when": "at 20:00", "runner": "vidhi",
                        "inputs": {"line": "33", "message": ""}})
    assert made.runner == "vidhi" and made.prompt == "cold-night"
    assert made.inputs == {"line": "33"}


def test_an_agent_schedule_from_the_page_carries_no_blanks(tmp_path):
    from samay.http import Api
    from samay.store import Store
    api = Api(Store(tmp_path / "s.sqlite3"), None, tmp_path)
    made = api._create({"prompt": "check mail", "when": "every 2h", "inputs": {"x": "1"}})
    assert made.inputs == {}
