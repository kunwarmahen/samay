"""Changing a schedule in place.

"Make my morning brief 8 instead of 7" had one road: delete it and make
it again -- its logbook gone, the tools it was allowed asked for again,
a new id on every link to it. The bias these tests encode: A SMALL
CHANGE THAT COSTS THE WHOLE SCHEDULE.

* What it asks, when, its zone, when it tells, which phone: each
  changes alone, and nothing else moves -- id, runs, allowed tools and
  limits stay.
* A new ``when`` counts from the change: "every 2h" changed now runs two
  hours from now, not on the old beat; a finished one with time left
  comes back; a paused one stays paused.
* What it runs (its road, its agent, whether it works the phone) was
  part of the yes it was made with, and is not changed here.
* The same change from the terminal, the agent's tool and the page.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, UTC

import pytest

from samay import schedules
from samay.cli import main
from samay.clock import Clock
from samay.http import Api, SamayServer
from samay.mcp import Tools, answer
from samay.store import Store, from_iso

UTC = UTC
NOW = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMAY_TZ", "UTC")
    return Store(tmp_path / "samay.sqlite3")


def add(store, **kw):
    kw.setdefault("when", {"at": "07:00"})
    return schedules.create(store, prompt="give me my morning brief",
                            now=NOW - timedelta(days=3), **kw)


class TestOneThingChangesAndNothingElse:
    def test_a_new_time_keeps_its_id_runs_tools_and_limits(self, store):
        made = add(store, allow_tools=["web_fetch"], time_limit=900)
        run = store.start_run(made.id, NOW - timedelta(days=1))
        store.finish_run(run)
        changed = schedules.edit(store, made.id, when="at 08:00", now=NOW)
        assert changed.id == made.id
        assert changed.when == {"at": "08:00"}
        assert changed.allow_tools == ["web_fetch"] and changed.time_limit == 900
        assert changed.prompt == made.prompt
        assert [r.id for r in store.runs(made.id)] == [run.id]
        assert changed.next_at.startswith("2026-11-11T08:00")
        assert changed.changed_at

    def test_the_prompt_alone_changes_and_the_beat_does_not(self, store):
        made = add(store, when={"every": "2h"})
        changed = schedules.edit(store, made.id, prompt="  brief, and the weather ",
                                 now=NOW)
        assert changed.prompt == "brief, and the weather"
        assert changed.counted_from == "" and changed.next_at == made.next_at

    def test_notify_and_zone(self, store):
        made = add(store)
        changed = schedules.edit(store, made.id, notify="always",
                                 tz="Asia/Kolkata", now=NOW)
        assert changed.notify == "always" and changed.tz == "Asia/Kolkata"
        assert changed.when == made.when

    def test_nothing_new_is_said_back_not_saved(self, store):
        made = add(store)
        with pytest.raises(schedules.ScheduleError, match="nothing to change"):
            schedules.edit(store, made.id, when="at 07:00", prompt=made.prompt)
        assert store.get(made.id).changed_at == ""


class TestANewWhenCountsFromTheChange:
    def test_every_runs_on_the_new_beat(self, store):
        made = add(store, when={"every": "3h"})
        changed = schedules.edit(store, made.id, when={"every": "2h"}, now=NOW)
        assert from_iso(changed.next_at) == NOW + timedelta(hours=2)
        # the clock reads the same beat after the change
        from samay.store import counts_from
        assert counts_from(changed) == NOW

    def test_a_finished_one_comes_back_with_time_left(self, store):
        made = add(store)
        store.update(made.id, state="done", next_at=None)
        changed = schedules.edit(store, made.id, when="once 2026-11-12T09:00", now=NOW)
        assert changed.state == "active" and changed.next_at.startswith("2026-11-12")

    def test_a_paused_one_stays_paused(self, store):
        made = add(store)
        schedules.pause(store, made.id)
        assert schedules.edit(store, made.id, when="at 09:00", now=NOW).state == "paused"

    def test_a_bad_when_says_so_and_nothing_moves(self, store):
        made = add(store)
        with pytest.raises(schedules.ScheduleError):
            schedules.edit(store, made.id, when="sometimes", now=NOW)
        assert store.get(made.id).when == made.when


class TestWhatItRunsStays:
    def test_a_routine_schedule_s_prompt_is_still_a_routine_name(self, store):
        made = schedules.create(store, prompt="morning-brief", when="at 07:00",
                                runner="vidhi")
        with pytest.raises(schedules.ScheduleError, match="routine's name"):
            schedules.edit(store, made.id, prompt="do the brief please")
        assert schedules.edit(store, made.id, prompt="evening-brief").prompt \
            == "evening-brief"

    def test_which_phone_only_for_one_that_works_a_phone(self, store):
        made = add(store)
        with pytest.raises(schedules.ScheduleError, match="doesn't work a phone"):
            schedules.edit(store, made.id, phone_name="nexus")
        phoned = add(store, phone="pixel")
        assert schedules.edit(store, phoned.id, phone_name="nexus").phone_name == "nexus"

    def test_someone_else_s_schedule_is_no_schedule(self, store):
        made = add(store, owner="asha")
        with pytest.raises(schedules.ScheduleError, match="no schedule"):
            schedules.edit(store, made.id, owner="mahen", prompt="mine now")


class TestTheWhenSaidBackInItsWords:
    @pytest.mark.parametrize("words", [
        "every 30m between 09:00-18:00 on mon-fri", "at 08:00,20:00 on weekends",
        "once 2026-10-06T15:00", "cron 0 */2 * * *", "at 07:00"])
    def test_text_reads_back_as_the_same_form(self, words):
        from samay import when
        form = when.parse_text(words)
        assert when.parse_text(when.text(form)) == form


class TestEveryDoor:
    def test_the_terminal(self, store, tmp_path, capsys):
        made = add(store)
        code = main(["--state", str(tmp_path), "edit", made.id, "--when", "at 08:00",
                     "--prompt", "brief and weather"])
        out = capsys.readouterr().out
        assert code == 0 and f"{made.id} changed: now asks: brief and weather" in out
        assert "runs every day at 08:00" in out

    def test_the_agent_s_tool_is_marked_as_changing(self, store, tmp_path):
        made = add(store)
        tools = Tools(store, tmp_path, person="local")
        listed = answer(tools, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tool = next(t for t in listed["result"]["tools"]
                    if t["name"] == "change_schedule")
        assert tool["annotations"]["readOnlyHint"] is False
        reply = answer(tools, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                               "params": {"name": "change_schedule", "arguments": {
                                   "id": made.id, "when": {"at": "08:30"}}}})
        text = reply["result"]["content"][0]["text"]
        assert not reply["result"]["isError"] and "runs every day at 08:30" in text

    def test_the_page(self, store, tmp_path):
        made = add(store)
        clock = Clock(store, {})
        server = SamayServer(Api(store, clock, tmp_path), "a-token-long-enough-to-be-real",
                             port=0)
        server.start()
        try:
            request = urllib.request.Request(
                server.url.rstrip("/") + f"/api/schedules/{made.id}/edit", method="POST",
                data=json.dumps({"notify": "always", "when": None}).encode(),
                headers={"Authorization": "Bearer a-token-long-enough-to-be-real"})
            with urllib.request.urlopen(request, timeout=10) as response:
                card = json.loads(response.read())
        finally:
            server.stop()
            clock.close()
        assert card["notify"] == "always" and card["when_text"] == "at 07:00"
        assert card["said"] == f"{made.id} changed: tells always"
