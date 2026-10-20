"""What a schedule may do unasked, and who it can ask when it is not.

"Turn off the stairs light in five minutes" was saved with nothing
allowed and ran on the direct road, where nobody could be asked: the
switch was refused while its person sat in front of Telegram, and the
run was filed ``ok``. The bias these tests encode: A YES THAT DOES NOT
COVER THE JOB, AND NO WAY TO GIVE ONE.

* A grant may fix a tool to what it acts on; one Samay cannot read is
  refused when the schedule is saved, never at three in the morning.
* A tool can be allowed later (``samay allow``, ``allow_for_schedule``)
  -- added beside what was allowed, never in place of it.
* The direct road can ask through Dvara when this Samay knows one, and
  waiting for that yes does not eat the work's time limit; with no
  Dvara, nothing claims it can ask.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from samay import schedules
from samay.dvara import Dvara
from samay.mcp import Tools, answer
from samay.runners import DirectRunner
from samay.store import Schedule, Store

STAIRS = ("mcp__homeassistant-home__call_service(domain=switch, service=turn_off, "
          "entity_id=switch.lights_2)")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMAY_TZ", "UTC")
    return Store(tmp_path / "samay.sqlite3")


def add(store, **kw):
    return schedules.create(store, prompt="turn off the stairs light",
                            when={"every": "1h"}, **kw)


class TestAGrantIsCheckedWhenSaved:
    def test_a_narrow_grant_is_kept_as_written(self, store):
        made = add(store, allow_tools=[STAIRS, "browser_*"])
        assert store.get(made.id).allow_tools == [STAIRS, "browser_*"]

    @pytest.mark.parametrize("bad", ["call_service(domain=switch", "call_service()",
                                     "call_service(domain)", "two words"])
    def test_one_samay_cannot_read_is_refused_at_once(self, store, bad):
        with pytest.raises(schedules.ScheduleError, match="not a tool to allow"):
            add(store, allow_tools=[bad])


class TestAllowingLater:
    def test_a_tool_is_added_beside_what_was_allowed(self, store):
        made = add(store, allow_tools=["web_fetch"])
        after = schedules.allow(store, made.id, [STAIRS, "web_fetch"])
        assert after.allow_tools == ["web_fetch", STAIRS]

    def test_only_the_owners_own_schedule(self, store):
        made = add(store, owner="raj")
        with pytest.raises(schedules.ScheduleError, match="no schedule"):
            schedules.allow(store, made.id, ["web_fetch"], owner="mahen")

    def test_nothing_named_is_not_a_change(self, store):
        made = add(store)
        with pytest.raises(schedules.ScheduleError, match="which tool"):
            schedules.allow(store, made.id, [" "])

    def test_the_command_says_what_it_may_now_use(self, store, tmp_path):
        made = add(store)
        done = subprocess.run(
            [sys.executable, "-m", "samay.cli", "--state", str(tmp_path), "allow",
             made.id, STAIRS], capture_output=True, text=True, timeout=30,
            env={"SAMAY_TZ": "UTC", "PATH": "/usr/bin:/bin"})
        assert done.returncode == 0, done.stderr
        assert f"{made.id} may now use without asking: {STAIRS}" in done.stdout

    def test_the_agent_can_allow_it_and_says_when_a_one_off_is_over(self, store, tmp_path):
        tools = Tools(store, tmp_path, person="local")
        made = add(store)
        store.update(made.id, state="done")
        reply = answer(tools, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": "allow_for_schedule", "arguments": {
                                   "id": made.id, "allow_tools": [STAIRS]}}})
        text = reply["result"]["content"][0]["text"]
        assert not reply["result"]["isError"]
        assert STAIRS in text and "will not run again" in text


def schedule(**kw) -> Schedule:
    base = dict(id="abc123", owner="local", prompt="p", when={"every": "1h"},
                tz="UTC", time_limit=60, wait=20)
    return Schedule(**{**base, **kw})


def fake_yantra(tmp_path):
    script = tmp_path / "fake_yantra.py"
    data = {"format": "yantra.run.v1", "ok": True, "text": "hi"}
    script.write_text(
        "import json, os\n"
        f"open({str(tmp_path / 'env.json')!r}, 'w').write(json.dumps("
        "{k: v for k, v in os.environ.items() if k.startswith('YANTRA_ASK')}))\n"
        f"print({json.dumps(json.dumps(data))})\n")
    return [sys.executable, str(script)]


class TestTheDirectRoadCanAsk:
    def test_with_a_dvara_the_run_is_told_where_to_ask_and_for_how_long(self, tmp_path):
        dvara = Dvara("http://dvara:8765", "tok", actor="owner")
        runner = DirectRunner(tmp_path / "work", command=fake_yantra(tmp_path), ask=dvara)
        assert runner.run(schedule(), "p").ok
        env = json.loads((tmp_path / "env.json").read_text())
        assert env == {"YANTRA_ASK_URL": "http://dvara:8765", "YANTRA_ASK_TOKEN": "tok",
                       "YANTRA_ASK_ACTOR": "owner", "YANTRA_ASK_WAIT": "1200"}

    def test_waiting_for_a_yes_does_not_eat_the_works_time_limit(self, tmp_path):
        dvara = Dvara("http://dvara:8765", "tok", actor="owner")
        assert DirectRunner(tmp_path, ask=dvara).time_limit(schedule()) == 60 + 1200
        assert DirectRunner(tmp_path).time_limit(schedule()) == 60

    def test_a_schedule_for_someone_dvara_knows_asks_them(self, tmp_path):
        dvara = Dvara("http://dvara:8765", "tok", actor="owner")
        assert DirectRunner(tmp_path, ask=dvara).asks_whom(schedule(owner="raj")) == "raj"

    def test_without_one_nothing_claims_it_can_ask(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YANTRA_ASK_URL", "http://left-over")
        runner = DirectRunner(tmp_path / "work", command=fake_yantra(tmp_path))
        runner.run(schedule(), "p")
        assert json.loads((tmp_path / "env.json").read_text()) == {}

    def test_a_dvara_with_nobody_to_run_as_asks_nobody(self, tmp_path):
        runner = DirectRunner(tmp_path, ask=Dvara("http://dvara:8765", "tok"))
        assert runner.asks_whom(schedule()) == ""
        assert "YANTRA_ASK_URL" not in runner.env(schedule())


class StubDvara(Dvara):
    """A Dvara whose phone check answers as told, and remembers it was asked."""

    def __init__(self, why=None):
        super().__init__("http://dvara:8765", "tok", actor="owner")
        self.why, self.asked = why, []

    def phone_ready(self, actor, wait, about, phone=""):
        self.asked.append((actor, wait, about))
        self.phones = [*getattr(self, "phones", []), phone]
        return self.why


class TestTheDirectRoadMayWorkThePhone:
    """Made on Yantra's page, a schedule that reads the iPhone's battery ran
    on the direct road with no phone, and answered from Home Assistant."""

    def test_a_phone_schedule_is_checked_by_dvara_then_runs_with_the_phone(self, tmp_path):
        dvara = StubDvara()
        runner = DirectRunner(tmp_path / "work", command=fake_yantra(tmp_path), ask=dvara)
        assert runner.run(schedule(phone=True, prompt="read the battery row"), "p").ok
        assert dvara.asked == [("owner", 1200, "read the battery row")]
        assert runner.env(schedule(phone=True))["YANTRA_PHONE_RUN"] == "1"
        assert "YANTRA_PHONE" not in runner.env(schedule(phone=True))
        assert runner.env(schedule(phone=True, phone_name="nexus"))["YANTRA_PHONE"] == "nexus"
        assert "YANTRA_PHONE_RUN" not in runner.env(schedule())

    def test_a_phone_dvara_says_isnt_free_is_skipped_and_yantra_never_started(
            self, tmp_path):
        runner = DirectRunner(tmp_path / "work", command=fake_yantra(tmp_path),
                              ask=StubDvara("skipped: the phone stayed locked"))
        got = runner.run(schedule(phone=True), "p")
        assert got.skipped and "stayed locked" in got.detail
        assert not (tmp_path / "env.json").exists()

    def test_with_nobody_to_ask_a_phone_schedule_is_skipped_and_says_why(self, tmp_path):
        got = DirectRunner(tmp_path / "work", command=fake_yantra(tmp_path)).run(
            schedule(phone=True), "p")
        assert got.skipped and "no Dvara here" in got.detail

    def test_made_in_a_chat_with_the_phone_granting_its_tools_it_is_a_phone_schedule(
            self, tmp_path):
        store = Store(tmp_path / "s.sqlite3")
        tools = Tools(store, tmp_path, person="local", phone=True)
        text = tools.call("create_schedule", {
            "prompt": "read the battery row", "when": "every 1d",
            "allow_tools": ["mcp__sparsh__look", "mcp__sparsh__tap"]})
        made = store.schedules()[-1]
        assert made.phone and made.runner == "direct", text
